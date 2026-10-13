from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bottrading.backtest import run_backtest
from bottrading.config import BacktestConfig
from bottrading.data import Candle
from bottrading.strategy import Signal

B, S, H = Signal.BUY, Signal.SELL, Signal.HOLD
START = datetime(2024, 1, 1, tzinfo=timezone.utc)
# Sin costes: aísla la mecánica del motor. Los costes se prueban aparte.
NO_COSTS = BacktestConfig(initial_capital=1000, commission_rate=0, slippage_rate=0)


def make_candles(opens, closes):
    """Velas sintéticas horarias; high/low envuelven open y close."""
    return [
        Candle(
            timestamp=START + timedelta(hours=i),
            open=float(o),
            high=float(max(o, c)),
            low=float(min(o, c)),
            close=float(c),
            volume=1.0,
        )
        for i, (o, c) in enumerate(zip(opens, closes))
    ]


# Aperturas y cierres distintos para detectar a qué precio se ejecuta.
OPENS = [10, 11, 12, 13, 14]
CLOSES = [10.5, 11.5, 12.5, 13.5, 14.5]


def test_buy_executes_at_next_open_not_signal_close():
    result = run_backtest(make_candles(OPENS, CLOSES), [B, H, H, H, H], NO_COSTS)
    (trade,) = result.trades
    assert trade.side is B
    assert trade.signal_time == START
    assert trade.execution_time == START + timedelta(hours=1)
    assert trade.price == 11.0  # apertura de la vela 1, no cierre de la 0
    assert trade.quantity == pytest.approx(1000 / 11)


def test_round_trip_cash_and_equity():
    result = run_backtest(make_candles(OPENS, CLOSES), [B, H, S, H, H], NO_COSTS)
    buy, sell = result.trades
    qty = 1000 / 11
    assert sell.price == 13.0  # apertura de la vela 3
    assert sell.cash_after == pytest.approx(qty * 13)
    assert result.final_quantity == 0
    assert result.final_cash == pytest.approx(qty * 13)
    assert result.equity == pytest.approx(
        [1000, qty * 11.5, qty * 12.5, qty * 13, qty * 13]
    )


def test_no_signals_keeps_capital_flat():
    result = run_backtest(make_candles(OPENS, CLOSES), [H] * 5, NO_COSTS)
    assert result.trades == []
    assert result.equity == [1000.0] * 5


def test_signal_on_last_candle_is_not_executed():
    result = run_backtest(make_candles(OPENS, CLOSES), [H, H, H, H, B], NO_COSTS)
    assert result.trades == []
    assert result.final_cash == 1000


def test_open_position_is_marked_to_last_close():
    result = run_backtest(make_candles(OPENS, CLOSES), [H, H, B, H, H], NO_COSTS)
    qty = 1000 / 13
    assert result.final_quantity == pytest.approx(qty)
    assert result.equity[-1] == pytest.approx(qty * 14.5)


def test_redundant_signals_are_ignored():
    # SELL sin posición y BUY estando dentro no generan operaciones.
    result = run_backtest(make_candles(OPENS, CLOSES), [S, B, B, H, H], NO_COSTS)
    assert [t.side for t in result.trades] == [B]
    assert result.trades[0].price == 12.0


def test_never_negative_cash_or_quantity():
    signals = [B, S, B, S, B]
    result = run_backtest(make_candles(OPENS, CLOSES), signals, NO_COSTS)
    assert all(t.cash_after >= 0 and t.quantity >= 0 for t in result.trades)
    assert result.final_cash >= 0 and result.final_quantity >= 0


def test_future_candles_do_not_change_past_equity():
    # Sin look-ahead en el motor: alterar velas posteriores a k no cambia
    # la curva de capital hasta k.
    candles = make_candles(OPENS, CLOSES)
    altered = candles[:3] + [
        replace(candle, open=99.0, high=99.0, low=1.0, close=1.0)
        for candle in candles[3:]
    ]
    signals = [B, H, H, S, H]
    base = run_backtest(candles, signals, NO_COSTS).equity
    other = run_backtest(altered, signals, NO_COSTS).equity
    assert other[:3] == base[:3]
    assert other[3:] != base[3:]  # la alteración sí afecta al futuro


def test_empty_input_returns_empty_result():
    result = run_backtest([], [], NO_COSTS)
    assert result.trades == [] and result.equity == []
    assert result.final_cash == 1000


def test_config_object_is_required():
    with pytest.raises(ValueError, match="BacktestConfig"):
        run_backtest(make_candles(OPENS, CLOSES), [H] * 5, 1000)


# --- Costes y límites (T007) --------------------------------------------------

COSTS = BacktestConfig(initial_capital=1000, commission_rate=0.01, slippage_rate=0.02)


def test_buy_applies_adverse_slippage_and_commission():
    result = run_backtest(make_candles(OPENS, CLOSES), [B, H, H, H, H], COSTS)
    (buy,) = result.trades
    price = 11 * 1.02  # compra por encima de la apertura
    notional = 1000 / 1.01  # nominal + 1 % de comisión = 1000
    assert buy.reference_price == 11.0
    assert buy.price == pytest.approx(price)
    assert buy.quantity == pytest.approx(notional / price)
    assert buy.fee == pytest.approx(notional * 0.01)
    assert buy.slippage_cost == pytest.approx(buy.quantity * 11 * 0.02)
    assert buy.cash_after == pytest.approx(0.0)


def test_sell_applies_adverse_slippage_and_commission():
    result = run_backtest(make_candles(OPENS, CLOSES), [B, H, S, H, H], COSTS)
    buy, sell = result.trades
    price = 13 * 0.98  # venta por debajo de la apertura
    gross = buy.quantity * price
    assert sell.price == pytest.approx(price)
    assert sell.fee == pytest.approx(gross * 0.01)
    assert sell.slippage_cost == pytest.approx(buy.quantity * 13 * 0.02)
    assert sell.cash_after == pytest.approx(gross * 0.99)
    assert result.final_cash == pytest.approx(gross * 0.99)


def test_totals_add_up_costs_of_all_trades():
    result = run_backtest(make_candles(OPENS, CLOSES), [B, H, S, H, H], COSTS)
    assert result.total_fees == pytest.approx(sum(t.fee for t in result.trades))
    assert result.total_slippage == pytest.approx(
        sum(t.slippage_cost for t in result.trades)
    )


def test_costs_make_round_trip_worse_than_frictionless():
    signals = [B, H, S, H, H]
    free = run_backtest(make_candles(OPENS, CLOSES), signals, NO_COSTS)
    paid = run_backtest(make_candles(OPENS, CLOSES), signals, COSTS)
    assert paid.final_cash < free.final_cash


def test_flat_market_round_trip_loses_exactly_the_costs():
    # Precio constante: sin costes se recupera el capital; con costes,
    # el capital final = inicial - comisiones - slippage.
    candles = make_candles([10] * 5, [10] * 5)
    result = run_backtest(candles, [B, H, S, H, H], COSTS)
    assert result.final_cash == pytest.approx(
        1000 - result.total_fees - result.total_slippage
    )
    assert result.final_cash < 1000


def test_position_fraction_limits_buy_and_keeps_rest_in_cash():
    config = replace(NO_COSTS, max_position_fraction=0.25)
    result = run_backtest(make_candles(OPENS, CLOSES), [B, H, H, H, H], config)
    (buy,) = result.trades
    assert buy.quantity == pytest.approx(250 / 11)
    assert buy.cash_after == pytest.approx(750)
    assert result.equity[-1] == pytest.approx(750 + 250 / 11 * 14.5)


def test_position_fraction_with_costs():
    config = replace(COSTS, max_position_fraction=0.4)
    result = run_backtest(make_candles(OPENS, CLOSES), [B, H, H, H, H], config)
    (buy,) = result.trades
    budget = 400  # 40 % de 1000, comisión incluida
    notional = budget / 1.01
    assert buy.quantity == pytest.approx(notional / (11 * 1.02))
    assert buy.fee == pytest.approx(notional * 0.01)
    assert buy.quantity * buy.price + buy.fee == pytest.approx(budget)
    assert buy.cash_after == pytest.approx(600)


def test_buy_cost_never_exceeds_available_cash():
    # Varias idas y vueltas con costes altos: el efectivo nunca es negativo.
    config = BacktestConfig(1000, commission_rate=0.05, slippage_rate=0.05)
    candles = make_candles([10, 12, 9, 11, 8, 13], [11, 10, 10, 9, 12, 12])
    result = run_backtest(candles, [B, S, B, S, B, H], config)
    assert len(result.trades) == 5
    assert all(t.cash_after >= 0 for t in result.trades)


def test_length_mismatch_is_rejected():
    with pytest.raises(ValueError, match="deben coincidir"):
        run_backtest(make_candles(OPENS, CLOSES), [H] * 4, NO_COSTS)


def test_unordered_candles_are_rejected():
    candles = make_candles(OPENS, CLOSES)
    with pytest.raises(ValueError, match="no ordenadas"):
        run_backtest([candles[1], candles[0]], [H, H], NO_COSTS)


@pytest.mark.parametrize("price", [0.0, -1.0, float("nan"), float("inf")])
@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_invalid_candle_prices_are_rejected(field, price):
    # Candle no valida sus valores; el motor no debe confiar en el cargador.
    candles = make_candles(OPENS, CLOSES)
    candles[1] = replace(candles[1], **{field: price})
    with pytest.raises(ValueError, match="precios no positivos o no finitos"):
        run_backtest(candles, [B, H, H, H, H], NO_COSTS)


def test_invalid_signal_type_is_rejected():
    with pytest.raises(ValueError, match="tipo inválido"):
        run_backtest(make_candles(OPENS, CLOSES), [H, H, "buy", H, H], NO_COSTS)
