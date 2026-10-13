from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bottrading.backtest import run_backtest
from bottrading.data import Candle
from bottrading.strategy import Signal

B, S, H = Signal.BUY, Signal.SELL, Signal.HOLD
START = datetime(2024, 1, 1, tzinfo=timezone.utc)


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
    result = run_backtest(make_candles(OPENS, CLOSES), [B, H, H, H, H], 1000)
    (trade,) = result.trades
    assert trade.side is B
    assert trade.signal_time == START
    assert trade.execution_time == START + timedelta(hours=1)
    assert trade.price == 11.0  # apertura de la vela 1, no cierre de la 0
    assert trade.quantity == pytest.approx(1000 / 11)


def test_round_trip_cash_and_equity():
    result = run_backtest(make_candles(OPENS, CLOSES), [B, H, S, H, H], 1000)
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
    result = run_backtest(make_candles(OPENS, CLOSES), [H] * 5, 1000)
    assert result.trades == []
    assert result.equity == [1000.0] * 5


def test_signal_on_last_candle_is_not_executed():
    result = run_backtest(make_candles(OPENS, CLOSES), [H, H, H, H, B], 1000)
    assert result.trades == []
    assert result.final_cash == 1000


def test_open_position_is_marked_to_last_close():
    result = run_backtest(make_candles(OPENS, CLOSES), [H, H, B, H, H], 1000)
    qty = 1000 / 13
    assert result.final_quantity == pytest.approx(qty)
    assert result.equity[-1] == pytest.approx(qty * 14.5)


def test_redundant_signals_are_ignored():
    # SELL sin posición y BUY estando dentro no generan operaciones.
    result = run_backtest(make_candles(OPENS, CLOSES), [S, B, B, H, H], 1000)
    assert [t.side for t in result.trades] == [B]
    assert result.trades[0].price == 12.0


def test_never_negative_cash_or_quantity():
    signals = [B, S, B, S, B]
    result = run_backtest(make_candles(OPENS, CLOSES), signals, 1000)
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
    base = run_backtest(candles, signals, 1000).equity
    other = run_backtest(altered, signals, 1000).equity
    assert other[:3] == base[:3]
    assert other[3:] != base[3:]  # la alteración sí afecta al futuro


def test_empty_input_returns_empty_result():
    result = run_backtest([], [], 1000)
    assert result.trades == [] and result.equity == []
    assert result.final_cash == 1000


@pytest.mark.parametrize("capital", [0, -1, float("nan"), float("inf"), True, "1000"])
def test_invalid_capital_is_rejected(capital):
    with pytest.raises(ValueError, match="initial_capital"):
        run_backtest(make_candles(OPENS, CLOSES), [H] * 5, capital)


def test_length_mismatch_is_rejected():
    with pytest.raises(ValueError, match="deben coincidir"):
        run_backtest(make_candles(OPENS, CLOSES), [H] * 4, 1000)


def test_unordered_candles_are_rejected():
    candles = make_candles(OPENS, CLOSES)
    with pytest.raises(ValueError, match="no ordenadas"):
        run_backtest([candles[1], candles[0]], [H, H], 1000)


@pytest.mark.parametrize("price", [0.0, -1.0, float("nan"), float("inf")])
@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_invalid_candle_prices_are_rejected(field, price):
    # Candle no valida sus valores; el motor no debe confiar en el cargador.
    candles = make_candles(OPENS, CLOSES)
    candles[1] = replace(candles[1], **{field: price})
    with pytest.raises(ValueError, match="precios no positivos o no finitos"):
        run_backtest(candles, [B, H, H, H, H], 1000)


def test_invalid_signal_type_is_rejected():
    with pytest.raises(ValueError, match="tipo inválido"):
        run_backtest(make_candles(OPENS, CLOSES), [H, H, "buy", H, H], 1000)
