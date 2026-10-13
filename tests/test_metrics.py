import math
from datetime import datetime, timedelta, timezone

import pytest

from bottrading.backtest import run_backtest
from bottrading.config import BacktestConfig
from bottrading.data import Candle
from bottrading.metrics import (
    compare_with_buy_and_hold,
    compute_metrics,
    irregular_gaps,
    max_drawdown,
)
from bottrading.strategy import Signal, buy_and_hold_signals

B, S, H = Signal.BUY, Signal.SELL, Signal.HOLD
START = datetime(2024, 1, 1, tzinfo=timezone.utc)
NO_COSTS = BacktestConfig(initial_capital=1000, commission_rate=0, slippage_rate=0)
COSTS = BacktestConfig(initial_capital=1000, commission_rate=0.01, slippage_rate=0.02)


def make_candles(prices, interval=timedelta(hours=1)):
    """Velas con open == close == precio, para cálculos a mano sencillos."""
    return [
        Candle(START + i * interval, p, p, p, p, 1.0) for i, p in enumerate(prices)
    ]


# --- max_drawdown --------------------------------------------------------------


def test_max_drawdown_takes_worst_peak_to_trough():
    assert max_drawdown([100, 120, 90, 130, 65]) == pytest.approx(0.5)


def test_max_drawdown_is_zero_for_rising_curve():
    assert max_drawdown([1, 2, 3]) == 0


# --- rendimiento -----------------------------------------------------------------


def test_total_return_without_costs():
    result = run_backtest(make_candles([10, 10, 20, 20]), [B, H, S, H], NO_COSTS)
    assert compute_metrics(result).total_return == pytest.approx(1.0)


def test_total_return_with_open_position_uses_liquidation_value():
    result = run_backtest(make_candles([10, 10, 20]), [B, H, H], COSTS)
    metrics = compute_metrics(result)
    assert metrics.open_position
    assert metrics.final_value_net == pytest.approx(result.final_liquidation_value)
    assert metrics.final_value_net < metrics.final_equity_mtm
    assert metrics.total_return == pytest.approx(result.final_liquidation_value / 1000 - 1)
    assert any("posición abierta" in note for note in metrics.notes)


def test_annualized_return_needs_a_full_year():
    result = run_backtest(make_candles([10] * 10), [H] * 10, NO_COSTS)
    metrics = compute_metrics(result)
    assert metrics.annualized_return is None
    assert any("annualized_return no disponible" in n for n in metrics.notes)


def test_annualized_return_over_two_years():
    # 731 velas diarias = 730 días. Compra en la vela 1 a 100, vale 400 al final.
    prices = [100.0] * 730 + [400.0]
    result = run_backtest(
        make_candles(prices, timedelta(days=1)), buy_and_hold_signals(731), NO_COSTS
    )
    metrics = compute_metrics(result)
    assert metrics.total_return == pytest.approx(3.0)
    assert metrics.annualized_return == pytest.approx(1.0)  # (1 + 3) ** (1/2) - 1


# --- riesgo ----------------------------------------------------------------------


def test_periods_per_year_from_candle_interval():
    hourly = compute_metrics(run_backtest(make_candles([10] * 3), [H] * 3, NO_COSTS))
    daily = compute_metrics(
        run_backtest(make_candles([10] * 3, timedelta(days=1)), [H] * 3, NO_COSTS)
    )
    assert hourly.periods_per_year == pytest.approx(8760)
    assert daily.periods_per_year == pytest.approx(365)


def test_risk_metrics_need_enough_returns():
    result = run_backtest(make_candles([10] * 30), [H] * 30, NO_COSTS)  # 29 rend.
    metrics = compute_metrics(result)
    assert metrics.volatility is None and metrics.sharpe is None
    assert any("29 rendimientos" in n for n in metrics.notes)


def test_flat_equity_has_zero_volatility_and_no_sharpe():
    result = run_backtest(make_candles([10] * 40), [H] * 40, NO_COSTS)
    metrics = compute_metrics(result)
    assert metrics.volatility == 0
    assert metrics.sharpe is None
    assert any("volatilidad cero" in n for n in metrics.notes)


def test_volatility_and_sharpe_values():
    # Buy-and-hold sin costes; la curva sigue al precio desde la vela 1.
    # Precio alterno 99.5 / 101: rendimientos distintos de cero.
    prices = [100.0] + [101.0 if i % 2 else 99.5 for i in range(40)]
    candles = make_candles(prices, timedelta(days=1))
    result = run_backtest(candles, buy_and_hold_signals(len(candles)), NO_COSTS)
    returns = [b / a - 1 for a, b in zip(result.equity, result.equity[1:])]
    stdev = math_stdev(returns)
    mean = sum(returns) / len(returns)
    metrics = compute_metrics(result)
    assert metrics.volatility == pytest.approx(stdev * math.sqrt(365))
    assert metrics.sharpe == pytest.approx(mean / stdev * math.sqrt(365))
    with_rf = compute_metrics(result, risk_free_rate=0.05)
    assert with_rf.sharpe < metrics.sharpe


def math_stdev(values):
    """Desviación típica muestral escrita aparte para no reutilizar statistics."""
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


# --- operaciones -----------------------------------------------------------------


def test_round_trips_and_win_rate():
    # Gana 10 -> 20, pierde 20 -> 15.
    prices = [10, 10, 20, 20, 20, 15, 15]
    result = run_backtest(make_candles(prices), [B, H, S, B, H, S, H], NO_COSTS)
    metrics = compute_metrics(result)
    assert metrics.num_trades == 4
    assert [round(t.pnl, 6) for t in metrics.round_trips] == [1000.0, -500.0]
    assert metrics.win_rate == 0.5


def test_win_rate_not_available_without_closed_trades():
    result = run_backtest(make_candles([10, 10, 12]), [B, H, H], NO_COSTS)
    metrics = compute_metrics(result)
    assert metrics.win_rate is None
    assert metrics.round_trips == []


def test_round_trip_pnl_includes_costs():
    # Precio constante: cada ida y vuelta pierde exactamente los costes.
    result = run_backtest(make_candles([10] * 4), [B, H, S, H], COSTS)
    metrics = compute_metrics(result)
    (trip,) = metrics.round_trips
    assert trip.pnl == pytest.approx(-(metrics.total_fees + metrics.total_slippage))
    assert metrics.win_rate == 0


# --- comparación con buy-and-hold -------------------------------------------------


def test_buy_and_hold_signals():
    assert buy_and_hold_signals(3) == [B, H, H]
    assert buy_and_hold_signals(0) == []


def test_compare_with_buy_and_hold_uses_same_rules():
    prices = [10, 10, 20, 20, 30]
    comparison = compare_with_buy_and_hold(make_candles(prices), [B, H, S, H, H], NO_COSTS)
    assert comparison.strategy.total_return == pytest.approx(1.0)  # 10 -> 20
    assert comparison.benchmark.total_return == pytest.approx(2.0)  # 10 -> 30
    assert comparison.excess_return == pytest.approx(-1.0)


def test_benchmark_pays_costs_too():
    comparison = compare_with_buy_and_hold(make_candles([10] * 5), [H] * 5, COSTS)
    assert comparison.benchmark.total_fees > 0
    assert comparison.benchmark.total_return < 0
    assert comparison.strategy.total_return == 0


# --- validación ------------------------------------------------------------------


def test_empty_result_is_rejected():
    with pytest.raises(ValueError, match="sin velas"):
        compute_metrics(run_backtest([], [], NO_COSTS))


@pytest.mark.parametrize("rate", [-1, -2, float("nan"), float("inf"), True, "0.05"])
def test_invalid_risk_free_rate_is_rejected(rate):
    result = run_backtest(make_candles([10] * 3), [H] * 3, NO_COSTS)
    with pytest.raises(ValueError, match="risk_free_rate"):
        compute_metrics(result, risk_free_rate=rate)


# --- costes estimados de salida y huecos (T009) ------------------------------


def test_estimated_exit_costs_are_separate_from_executed_costs():
    result = run_backtest(make_candles([10, 10, 20]), [B, H, H], COSTS)
    metrics = compute_metrics(result)
    expected = metrics.final_equity_mtm - metrics.final_value_net
    assert metrics.estimated_exit_costs == pytest.approx(expected)
    assert metrics.estimated_exit_costs > 0
    # total_fees solo incluye la compra ejecutada.
    assert metrics.total_fees == pytest.approx(result.trades[0].fee)


def test_estimated_exit_costs_are_zero_when_flat():
    result = run_backtest(make_candles([10, 10, 20, 20]), [B, H, S, H], COSTS)
    assert compute_metrics(result).estimated_exit_costs == 0


def test_irregular_gaps_are_counted_and_noted():
    candles = make_candles([10] * 6)
    # Quita las velas 2 y 3: un hueco de 3 horas con mediana de 1 hora.
    gapped = candles[:2] + candles[4:]
    assert irregular_gaps([c.timestamp for c in gapped]) == 1
    metrics = compute_metrics(run_backtest(gapped, [H] * 4, NO_COSTS))
    assert any("huecos" in note for note in metrics.notes)


def test_regular_series_has_no_gap_note():
    metrics = compute_metrics(run_backtest(make_candles([10] * 5), [H] * 5, NO_COSTS))
    assert irregular_gaps([START + timedelta(hours=i) for i in range(5)]) == 0
    assert not any("huecos" in note for note in metrics.notes)
