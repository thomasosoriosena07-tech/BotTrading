from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bottrading.config import BacktestConfig
from bottrading.data import Candle
from bottrading.splits import (
    DAILY,
    HOURLY,
    InsufficientDataError,
    Scheme,
    add_months,
    evaluate_segment,
    plan_splits,
)
from bottrading.strategy import (
    Signal,
    buy_and_hold_signals,
    crossover_signals,
    donchian_signals,
    trend_filter_signals,
)

START = datetime(2020, 1, 1, tzinfo=timezone.utc)
NO_COSTS = BacktestConfig(initial_capital=1000, commission_rate=0, slippage_rate=0)


def daily(days, start=START):
    return [start + timedelta(days=i) for i in range(days)]


def candles_from(prices, interval=timedelta(days=1)):
    return [Candle(START + i * interval, p, p, p, p, 1.0) for i, p in enumerate(prices)]


# --- add_months ----------------------------------------------------------------------


def test_add_months_clamps_day_and_crosses_years():
    assert add_months(datetime(2024, 1, 31, tzinfo=timezone.utc), 1).day == 29
    assert add_months(datetime(2024, 11, 15, tzinfo=timezone.utc), 3) == datetime(
        2025, 2, 15, tzinfo=timezone.utc)
    assert add_months(datetime(2024, 3, 31, tzinfo=timezone.utc), -1) == datetime(
        2024, 2, 29, tzinfo=timezone.utc)


# --- plan_splits ---------------------------------------------------------------------


def test_daily_plan_structure():
    timestamps = daily(2465)  # ~6,75 años, como los datos reales
    plan = plan_splits(timestamps, DAILY)
    assert len(plan.windows) == 5
    assert plan.holdout_end == 2465
    assert plan.holdout_start == 2465 - round(2465 * 0.2)
    # Validaciones consecutivas, sin solapamiento, pegadas al holdout.
    for previous, current in zip(plan.windows, plan.windows[1:]):
        assert previous.validation_end == current.validation_start
    assert plan.windows[-1].validation_end == plan.holdout_start
    for window in plan.windows:
        assert window.train_start == 0
        assert window.train_end == window.validation_start  # ajuste = todo lo anterior
        assert window.validation_end <= plan.holdout_start


def test_validation_windows_span_the_scheme_months():
    timestamps = daily(2465)
    plan = plan_splits(timestamps, DAILY)
    first = timestamps[plan.windows[0].validation_start]
    assert add_months(first, 6 * 5).date() == timestamps[plan.holdout_start].date()


def test_initial_train_covers_required_months():
    timestamps = daily(2465)
    plan = plan_splits(timestamps, DAILY)
    first_validation = timestamps[plan.windows[0].validation_start]
    assert add_months(timestamps[0], 24) <= first_validation


def test_insufficient_history_is_rejected():
    # 3 años no bastan: 20 % de holdout + 30 meses de validación + 24 de ajuste.
    with pytest.raises(InsufficientDataError, match="necesita datos desde"):
        plan_splits(daily(3 * 365), DAILY)


def test_short_holdout_is_flagged_not_annualizable():
    # 15 meses horarios: holdout de ~3 meses (< 1 año), selección de ~12.
    hours = [START + timedelta(hours=i) for i in range(24 * 456)]
    plan = plan_splits(hours, HOURLY)
    assert not plan.holdout_annualizable
    assert "insuficiente para publicar métricas anualizadas" in plan.notes[0]


def test_long_holdout_is_annualizable():
    assert plan_splits(daily(2465), DAILY).holdout_annualizable


@pytest.mark.parametrize(
    "scheme",
    [
        Scheme(0, 6, 5), Scheme(24, 0, 5), Scheme(24, 6, 0), Scheme(24, 6, 5, 0.0),
        Scheme(24, 6, 5, 0.6), Scheme(24.0, 6, 5), Scheme(True, 6, 5),
    ],
)
def test_invalid_schemes_are_rejected(scheme):
    with pytest.raises(ValueError):
        plan_splits(daily(2465), scheme)


def test_too_few_candles_for_holdout():
    with pytest.raises(InsufficientDataError, match="holdout"):
        plan_splits(daily(5), Scheme(1, 1, 1))


def test_plan_depends_only_on_timestamps():
    # Las particiones no miran precios: mismas fechas -> mismo plan.
    timestamps = daily(2465)
    assert plan_splits(timestamps, DAILY) == plan_splits(list(timestamps), DAILY)


# --- evaluate_segment ----------------------------------------------------------------


def sma(fast, slow):
    return lambda closes: crossover_signals(closes, fast, slow)


def test_segment_trades_only_inside_its_range():
    prices = [10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 10, 9, 8, 7, 6] * 4
    candles = candles_from(prices)
    result = evaluate_segment(candles, 20, 40, sma(2, 3), NO_COSTS)
    assert result.timestamps == [c.timestamp for c in candles[20:40]]
    for trade in result.trades:
        assert candles[20].timestamp <= trade.signal_time
        assert trade.execution_time < candles[40].timestamp


def test_segment_uses_prior_data_for_warmup():
    # Cruce alcista en la primera vela del segmento: con calentamiento se
    # detecta (y se compra en la siguiente); sin historial no habría medias.
    prices = [10, 9, 8, 7, 6, 9, 12, 13]
    candles = candles_from(prices)
    full = crossover_signals(prices, 2, 4)
    cross = full.index(Signal.BUY)
    result = evaluate_segment(candles, cross, len(prices), sma(2, 4), NO_COSTS)
    assert result.trades[0].signal_time == candles[cross].timestamp
    assert result.trades[0].execution_time == candles[cross + 1].timestamp


def test_without_inheritance_segment_starts_flat():
    # Modo sin herencia: la compra anterior al segmento no se arrastra.
    prices = [10, 9, 8, 7, 6, 9, 12, 13, 14, 15]
    candles = candles_from(prices)
    cross = crossover_signals(prices, 2, 4).index(Signal.BUY)
    result = evaluate_segment(candles, cross + 2, len(prices), sma(2, 4), NO_COSTS,
                              inherit_position=False)
    assert result.trades == []
    assert result.equity[0] == 1000


def test_segment_inherits_long_position_at_its_first_open():
    # La estrategia compró antes del segmento: el segmento entra a la
    # apertura de su primera vela (pagando costes), no espera otro cruce.
    prices = [10, 9, 8, 7, 6, 9, 12, 13, 14, 15]
    candles = candles_from(prices)
    cross = crossover_signals(prices, 2, 4).index(Signal.BUY)
    start = cross + 3
    result = evaluate_segment(candles, start, len(prices), sma(2, 4), NO_COSTS)
    (buy,) = result.trades
    assert buy.side is Signal.BUY
    assert buy.signal_time == candles[cross].timestamp  # señal heredada
    assert buy.execution_time == candles[start].timestamp
    assert buy.reference_price == candles[start].open


def test_segment_inherits_flat_after_a_sell():
    prices = [6, 7, 8, 9, 10, 7, 4, 3, 2, 1]
    candles = candles_from(prices)
    signals = crossover_signals(prices, 2, 4)
    assert Signal.SELL in signals
    start = signals.index(Signal.SELL) + 2
    assert evaluate_segment(candles, start, len(prices), sma(2, 4), NO_COSTS).trades == []


def test_strategy_and_buy_and_hold_enter_segment_at_same_open():
    # Igualdad de condiciones (revisión de Codex de T014).
    prices = [10, 9, 8, 7, 6, 9, 12, 13, 14, 15]
    candles = candles_from(prices)
    start = 8
    strategy = evaluate_segment(candles, start, len(prices), sma(2, 4), NO_COSTS)
    benchmark = evaluate_segment(candles, start, len(prices),
                                 lambda closes: buy_and_hold_signals(len(closes)), NO_COSTS)
    assert strategy.trades[0].execution_time == benchmark.trades[0].execution_time
    assert strategy.equity == benchmark.equity


@pytest.mark.parametrize(
    "signal_function",
    [lambda closes: trend_filter_signals(closes, 3),
     lambda closes: donchian_signals(closes, 3, 2)],
)
def test_new_strategies_inherit_long_position(signal_function):
    # Revisión de Codex de T015: herencia también con las nuevas estrategias.
    prices = [10, 9, 8, 7, 6, 9, 12, 13, 14, 15, 16, 17]
    candles = candles_from(prices)
    signals = signal_function(prices)
    entry = signals.index(Signal.BUY)
    start = entry + 3
    assert Signal.SELL not in signals[entry:start]
    result = evaluate_segment(candles, start, len(prices), signal_function, NO_COSTS)
    assert result.trades[0].side is Signal.BUY
    assert result.trades[0].execution_time == candles[start].timestamp


def test_unordered_timestamps_are_rejected():
    timestamps = daily(2465)
    timestamps[10], timestamps[11] = timestamps[11], timestamps[10]
    with pytest.raises(ValueError, match="no ordenadas"):
        plan_splits(timestamps, DAILY)


def test_changing_holdout_prices_does_not_change_selection_results():
    prices = [100 + (i % 17) - (i % 5) * 2 for i in range(2465)]
    candles = candles_from(prices)
    plan = plan_splits([c.timestamp for c in candles], DAILY)
    altered = candles[:plan.holdout_start] + [
        replace(c, open=c.open * 3, high=c.high * 3, low=c.low * 3, close=c.close * 3)
        for c in candles[plan.holdout_start:]
    ]
    for window in plan.windows:
        for start, end in ((window.train_start, window.train_end),
                           (window.validation_start, window.validation_end)):
            original = evaluate_segment(candles, start, end, sma(5, 20), NO_COSTS)
            changed = evaluate_segment(altered, start, end, sma(5, 20), NO_COSTS)
            assert original == changed


def test_invalid_segment_bounds():
    candles = candles_from([1.0] * 5)
    for start, end in ((3, 3), (-1, 2), (0, 6)):
        with pytest.raises(ValueError, match="segmento inválido"):
            evaluate_segment(candles, start, end, sma(1, 2), NO_COSTS)


def test_signal_function_must_return_one_signal_per_candle():
    candles = candles_from([1.0] * 5)
    with pytest.raises(ValueError, match="una señal por vela"):
        evaluate_segment(candles, 0, 5, lambda closes: [Signal.HOLD], NO_COSTS)
