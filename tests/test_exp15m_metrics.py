"""EXP-15M-001: métricas, marcas, C8, C9 e identidades contables (A.5, A.8, A.9). Sin red."""

import math
import random
import statistics
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from bottrading.backtest import run_backtest
from bottrading.config import BacktestConfig
from bottrading.data import Candle
from bottrading.exp15m_metrics import (
    AFTER_GAP,
    LOW_LIQUIDITY,
    TRUNCATED,
    Trip,
    accounting_problems,
    block_length,
    bootstrap_lower_bound,
    concentration_ok,
    daily_series,
    excluded_pnl,
    lower_rank_index,
    risk,
    round_trips,
    rounding_bound,
    summarize,
    trade_flags,
)
from bottrading.strategy import Signal

UTC = timezone.utc
STEP = timedelta(minutes=15)
T0 = datetime(2024, 1, 1, tzinfo=UTC)
B, S, H = Signal.BUY, Signal.SELL, Signal.HOLD
CONFIG = BacktestConfig(initial_capital=10_000.0, commission_rate=0.001, slippage_rate=0.0005)


def candle(moment: datetime, price: float, volume: float = 1_000_000.0) -> Candle:
    return Candle(moment, price, price * 1.01, price * 0.99, price, volume)


def candles_at(moments, prices, volume: float = 1_000_000.0) -> list[Candle]:
    return [candle(m, p, volume) for m, p in zip(moments, prices)]


def regular(count: int, prices=None, start: datetime = T0) -> list[Candle]:
    prices = prices or [100.0 + i for i in range(count)]
    return candles_at([start + i * STEP for i in range(count)], prices)


# --- muestreo diario (A.8) -------------------------------------------------------------


def test_daily_value_is_the_last_candle_of_each_utc_day():
    moments = [T0, T0 + timedelta(hours=23, minutes=45),
               T0 + timedelta(days=1, hours=3), T0 + timedelta(days=1, hours=10)]
    series = daily_series(moments, [1.0, 2.0, 3.0, 4.0])
    assert series.days == (date(2024, 1, 1), date(2024, 1, 2))
    assert series.values == (2.0, 4.0)  # día 2 sin vela de las 23:45: la última del día
    assert series.carried == ()


def test_day_without_candles_is_carried_and_marked():
    moments = [T0 + timedelta(hours=23, minutes=45), T0 + timedelta(days=2, hours=23, minutes=45)]
    series = daily_series(moments, [110.0, 121.0])
    assert series.values == (110.0, 110.0, 121.0)
    assert series.carried == (date(2024, 1, 2),)
    assert series.returns(100.0) == pytest.approx([0.10, 0.0, 0.10])
    assert series.returns(100.0, skip_carried=True) == pytest.approx([0.10, 0.10])


def test_daily_returns_start_from_initial_capital():
    series = daily_series([T0], [105.0])
    assert series.returns(100.0) == pytest.approx([0.05])


def test_risk_needs_thirty_returns_and_uses_365_days():
    assert risk([0.01] * 29) == (None, None)
    volatility, sharpe = risk([0.01] * 30)
    assert volatility == 0 and sharpe is None
    values = [0.01, -0.01] * 15
    volatility, sharpe = risk(values)
    stdev = statistics.stdev(values)
    assert volatility == pytest.approx(stdev * math.sqrt(365))
    assert sharpe == pytest.approx(0.0)


# --- idas y vueltas, marcas y redondeo -----------------------------------------------


def test_round_trips_include_open_position_valued_at_liquidation():
    history = regular(6, [100, 100, 110, 110, 120, 130])
    result = run_backtest(history, [B, H, S, B, H, H], CONFIG)
    trips = round_trips(result)
    assert [(t.entry, t.exit) for t in trips] == [(0, 1), (2, None)]
    assert trips[1].proceeds == pytest.approx(result.final_liquidation_value - result.final_cash)
    first = result.trades[0]
    assert trips[0].cost == pytest.approx(first.quantity * first.price + first.fee)


def test_flags_after_gap_truncated_and_low_liquidity():
    moments = [T0, T0 + STEP, T0 + 5 * STEP, T0 + 6 * STEP, T0 + 7 * STEP]
    history = candles_at(moments, [100.0] * 5)
    # Volumen de la vela anterior a la 3.ª operación muy pequeño -> liquidez dudosa.
    history[2] = candle(moments[2], 100.0, volume=1.0)
    result = run_backtest(history, [B, S, B, H, H], CONFIG)
    # Compra en 1 (sin hueco), venta en 2 (tras hueco), compra en 3 (vela 2 con poco volumen).
    flags = trade_flags(result, history, truncated=frozenset({moments[3]}))
    assert flags[0] == frozenset()
    assert flags[1] == frozenset({AFTER_GAP})
    assert flags[2] == frozenset({TRUNCATED, LOW_LIQUIDITY})


def test_liquidity_threshold_is_strict_and_uses_previous_close():
    history = regular(3, [100.0, 100.0, 100.0])
    result = run_backtest(history, [B, H, H], CONFIG)
    notional = result.trades[0].quantity * result.trades[0].price
    exact = notional / (0.01 * 100.0)  # volumen con el que N == 1 % de V
    at_limit = [replace(history[0], volume=exact), *history[1:]]
    assert trade_flags(result, at_limit)[0] == frozenset()
    below = [replace(history[0], volume=exact * 0.999), *history[1:]]
    assert trade_flags(result, below)[0] == frozenset({LOW_LIQUIDITY})


def test_trade_on_first_known_candle_is_flagged_conservatively():
    history = regular(3)
    result = run_backtest(history, [H, H, H], CONFIG, initial_signal=B,
                          initial_signal_time=T0 - STEP)
    assert trade_flags(result, history)[0] == frozenset({AFTER_GAP, LOW_LIQUIDITY})


def test_rounding_bound_adds_one_step_per_trade_and_final_liquidation():
    history = regular(4, [100, 100, 200, 300])
    result = run_backtest(history, [B, S, B, H], CONFIG)
    expected = 0.00001 * (sum(t.price for t in result.trades) + 300)
    assert rounding_bound(result, history[-1].close) == pytest.approx(expected)


def test_summary_exposure_costs_and_after_rounding_return():
    history = regular(8, [100, 100, 102, 104, 106, 108, 108, 108])
    result = run_backtest(history, [B, H, H, S, H, H, H, H], CONFIG)
    summary = summarize(result, history)
    assert summary.exposure == pytest.approx(3 / 8)  # posición al cierre de las velas 1-3
    assert summary.trades == 2 and summary.round_trips == 1
    pnl = result.final_liquidation_value - 10_000
    assert summary.net_return == pytest.approx(pnl / 10_000)
    assert summary.net_return_after_rounding == pytest.approx((pnl - summary.rounding_bound) / 10_000)
    costs = result.total_fees + result.total_slippage
    assert summary.cost_share_of_gross == pytest.approx(costs / (pnl + costs))
    assert summary.flag_counts == {AFTER_GAP: 0, TRUNCATED: 0, LOW_LIQUIDITY: 0}
    assert summary.days == 1 and summary.carried_days == 0


def test_intraday_drawdown_sees_what_daily_sampling_hides():
    prices = [100.0] * 40 + [50.0] + [100.0] * 55  # caída y recuperación dentro del día
    history = regular(96, prices)
    result = run_backtest(history, [B] + [H] * 95, CONFIG)
    summary = summarize(result, history)
    assert summary.max_drawdown_intraday > 0.49
    assert summary.max_drawdown_daily < 0.01


# --- C8, exclusión -----------------------------------------------------------------------


def trips_with(pnls) -> list[Trip]:
    return [Trip(i, i, 100.0, 100.0 + p) for i, p in enumerate(pnls)]


def test_concentration_removes_ceil_five_percent_at_least_one():
    assert concentration_ok(trips_with([10] + [1] * 19))  # N=20 -> k=1: 19 > 0
    assert not concentration_ok(trips_with([30, -1, -1, -1]))  # k=1: -3
    # N=21 -> k=techo(1,05)=2: quita 50 y 40.
    assert not concentration_ok(trips_with([50, 40] + [-1] * 19))
    assert concentration_ok(trips_with([50] + [1] * 20))
    assert not concentration_ok([])


def test_excluded_pnl_sums_trips_with_any_flagged_trade():
    trips = [Trip(0, 1, 100, 110), Trip(2, 3, 100, 95), Trip(4, None, 100, 120)]
    flags = [frozenset(), frozenset({AFTER_GAP}), frozenset(), frozenset(),
             frozenset({LOW_LIQUIDITY})]
    assert excluded_pnl(trips, flags) == pytest.approx(10 + 20)


# --- C9 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("n,length", [(1, 1), (8, 2), (9, 3), (27, 3), (28, 4), (92, 5),
                                      (125, 5), (126, 6)])
def test_block_length_is_integer_ceiling_of_cube_root(n, length):
    assert block_length(n) == length


def test_lower_rank_index_matches_protocol():
    assert lower_rank_index(10_000) == 249
    assert lower_rank_index(200) == 4  # techo(5) - 1
    assert lower_rank_index(201) == 5  # techo(5,025) - 1


def reference_bootstrap(values, resamples, seed):
    # Implementación independiente, escrita de nuevo a partir del texto de A.9.
    n = len(values)
    length = next(l for l in range(1, n + 2) if l ** 3 >= n)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        out = []
        while len(out) < n:
            s = rng.randrange(n)
            for j in range(length):
                out.append(values[(s + j) % n])
        means.append(sum(out[:n]) / n)
    means.sort()
    return means[math.ceil(0.025 * resamples) - 1]


VECTOR = [0.01, -0.02, 0.03, 0.0, 0.015, -0.005, 0.02, -0.01, 0.005, 0.012]


def test_bootstrap_matches_independent_reference_and_pinned_values():
    assert bootstrap_lower_bound(VECTOR, 200, 7) == pytest.approx(reference_bootstrap(VECTOR, 200, 7))
    # Valores fijados (regresión): misma semilla -> mismo resultado.
    assert bootstrap_lower_bound(VECTOR, 200, 7) == pytest.approx(0.0007)
    assert bootstrap_lower_bound(VECTOR) == pytest.approx(0.0009)
    assert bootstrap_lower_bound(VECTOR) == bootstrap_lower_bound(VECTOR)


def test_bootstrap_of_constant_series_is_that_constant():
    assert bootstrap_lower_bound([0.002] * 92, 300) == pytest.approx(0.002)


def test_bootstrap_rejects_empty_series():
    with pytest.raises(ValueError):
        bootstrap_lower_bound([], 10)


# --- identidades contables (defecto crítico 3) -----------------------------------------


def test_accounting_of_a_real_backtest_is_consistent():
    history = regular(10, [100, 101, 99, 105, 103, 108, 107, 110, 111, 109])
    result = run_backtest(history, [B, H, S, H, B, H, S, B, H, H], CONFIG)
    assert accounting_problems(result, history) == []


def test_accounting_detects_tampered_fee_equity_and_cash():
    history = regular(5, [100, 101, 102, 103, 104])
    result = run_backtest(history, [B, H, S, H, H], CONFIG)
    bad_fee = replace(result, trades=[replace(result.trades[0], fee=result.trades[0].fee * 2),
                                      *result.trades[1:]])
    assert any("comisión" in p for p in accounting_problems(bad_fee, history))
    bad_equity = replace(result, equity=[*result.equity[:-1], result.equity[-1] + 1])
    assert any("capital" in p for p in accounting_problems(bad_equity, history))
    bad_cash = replace(result, trades=[replace(result.trades[0], cash_after=-5.0),
                                       *result.trades[1:]])
    assert accounting_problems(bad_cash, history)
    assert accounting_problems(result, history[1:]) == ["las velas no coinciden con las del resultado"]


# Revisión de Codex de I2: falsos negativos detectados en memoria y casos sin prueba.


def sample():
    history = regular(6, [100, 101, 102, 103, 104, 105])
    return history, run_backtest(history, [B, H, S, H, B, H], CONFIG)


def test_accounting_detects_corrupted_final_state():
    history, result = sample()
    assert result.final_quantity > 0 and accounting_problems(result, history) == []
    for field, delta in (("final_liquidation_value", 1_000.0), ("final_cash", 1.0),
                         ("final_quantity", 0.001)):
        broken = replace(result, **{field: getattr(result, field) + delta})
        assert any("no coincide con la reconstrucción" in p
                   for p in accounting_problems(broken, history)), field


def test_accounting_detects_selling_more_than_held():
    history, result = sample()
    sell = result.trades[1]
    bigger = sell.quantity * 1.01
    notional = bigger * sell.price
    fee = notional * CONFIG.commission_rate
    cash_before = result.trades[0].cash_after
    forged = replace(sell, quantity=bigger, fee=fee,
                     slippage_cost=bigger * (sell.reference_price - sell.price),
                     cash_after=cash_before + notional - fee)
    trades = [result.trades[0], forged, *result.trades[2:]]
    equity = list(result.equity)
    equity[2] = forged.cash_after  # sin posición tras la venta
    broken = replace(result, trades=trades, equity=equity)
    problems = accounting_problems(broken, history)
    assert any("no es exactamente la cantidad" in p for p in problems)


def test_accounting_detects_buy_while_holding_and_non_positive_quantity():
    history, result = sample()
    double_buy = replace(result, trades=[result.trades[0],
                                         replace(result.trades[1], side=Signal.BUY),
                                         *result.trades[2:]])
    assert any("compra con una posición abierta" in p
               for p in accounting_problems(double_buy, history))
    negative = replace(result, trades=[replace(result.trades[0], quantity=-1.0),
                                       *result.trades[1:]])
    problems = accounting_problems(negative, history)
    assert any("no positiva" in p for p in problems)
    assert any("negativos" in p for p in problems)


def test_accounting_detects_altered_slippage_and_reference_price():
    history, result = sample()
    first = result.trades[0]
    slipped = replace(result, trades=[replace(first, slippage_cost=first.slippage_cost * 1.5),
                                      *result.trades[1:]])
    assert any("slippage" in p for p in accounting_problems(slipped, history))
    moved = replace(result, trades=[replace(first, reference_price=first.reference_price + 1,
                                            price=(first.reference_price + 1) * 1.0005),
                                    *result.trades[1:]])
    assert any("apertura de la vela" in p for p in accounting_problems(moved, history))


def test_accounting_rejects_any_negative_cash_and_trades_outside_the_segment():
    history, result = sample()
    tiny = replace(result, trades=[replace(result.trades[0], cash_after=-1e-9),
                                   *result.trades[1:]])
    assert any("negativos" in p for p in accounting_problems(tiny, history))
    outside = replace(result, trades=[*result.trades,
                                      replace(result.trades[-1],
                                              execution_time=T0 + 100 * STEP)])
    assert any("fuera de las velas" in p for p in accounting_problems(outside, history))


@pytest.mark.parametrize("commission,slippage", [(0.0, 0.0), (0.00075, 0.0002), (0.002, 0.001)])
def test_accounting_is_clean_in_every_cost_scenario(commission, slippage):
    config = BacktestConfig(initial_capital=10_000.0, commission_rate=commission,
                            slippage_rate=slippage)
    history = regular(10, [100, 103, 99, 105, 103, 108, 107, 110, 111, 109])
    result = run_backtest(history, [B, H, S, H, B, H, S, B, H, H], config)
    assert accounting_problems(result, history) == []
