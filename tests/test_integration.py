"""Pruebas de integración: CSV -> señales -> backtest -> métricas -> informe.

Usan el dataset sintético versionado en examples/ (sin descargas).
"""

import math
from dataclasses import replace
from pathlib import Path

import pytest

from bottrading.__main__ import main
from bottrading.backtest import run_backtest
from bottrading.config import BacktestConfig
from bottrading.data import load_ohlcv_csv
from bottrading.metrics import compute_metrics
from bottrading.report import file_sha256
from bottrading.strategy import Signal, buy_and_hold_signals, crossover_signals

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "synthetic_daily.csv"
FAST, SLOW = 10, 30
CONFIG = BacktestConfig(initial_capital=10_000)
NO_COSTS = replace(CONFIG, commission_rate=0, slippage_rate=0)


@pytest.fixture(scope="module")
def candles():
    return load_ohlcv_csv(SAMPLE)


def simulate(candles, config=CONFIG):
    closes = [c.close for c in candles]
    return run_backtest(candles, crossover_signals(closes, FAST, SLOW), config)


def test_sample_dataset_loads(candles):
    assert len(candles) == 800
    assert all(a.timestamp < b.timestamp for a, b in zip(candles, candles[1:]))


def test_strategy_trades_on_sample(candles):
    result = simulate(candles)
    assert len(result.trades) > 0
    sides = [t.side for t in result.trades]
    # Alterna compra/venta empezando por compra: nunca dos compras seguidas.
    assert sides == [Signal.BUY if i % 2 == 0 else Signal.SELL for i in range(len(sides))]


def test_every_trade_executes_on_the_candle_after_its_signal(candles):
    index = {c.timestamp: i for i, c in enumerate(candles)}
    for trade in simulate(candles).trades:
        assert index[trade.execution_time] == index[trade.signal_time] + 1
        assert trade.reference_price == candles[index[trade.execution_time]].open


def test_no_look_ahead_end_to_end(candles):
    # Recortar los datos en k no cambia nada de lo ocurrido antes de k.
    full = simulate(candles)
    for k in (100, 400, 650):
        partial = simulate(candles[:k])
        assert partial.equity == full.equity[:k]
        executed = [t for t in full.trades if t.execution_time < candles[k].timestamp]
        assert partial.trades == executed


def test_cash_accounting_matches_round_trips(candles):
    result = simulate(candles)
    metrics = compute_metrics(result)
    pnl = math.fsum(trip.pnl for trip in metrics.round_trips)
    # Con SMA 10/30 el ejemplo termina sin posición: todo el PnL está cerrado.
    assert result.final_quantity == 0
    assert result.final_cash == pytest.approx(CONFIG.initial_capital + pnl)


def test_costs_reduce_final_value(candles):
    with_costs = compute_metrics(simulate(candles, CONFIG))
    without = compute_metrics(simulate(candles, NO_COSTS))
    assert with_costs.final_value_net < without.final_value_net
    assert with_costs.total_fees > 0 and without.total_fees == 0


def test_buy_and_hold_without_costs_tracks_price(candles):
    result = run_backtest(candles, buy_and_hold_signals(len(candles)), NO_COSTS)
    metrics = compute_metrics(result)
    expected = candles[-1].close / candles[1].open - 1
    assert metrics.total_return == pytest.approx(expected)


def test_metrics_available_for_two_years_of_daily_data(candles):
    metrics = compute_metrics(simulate(candles))
    assert metrics.periods_per_year == pytest.approx(365)
    assert metrics.annualized_return is not None
    assert metrics.volatility is not None and metrics.sharpe is not None


def test_cli_end_to_end_on_sample(tmp_path, capsys):
    out = tmp_path / "report"
    assert main(["--csv", str(SAMPLE), "--out", str(out)]) == 0
    text = (out / "report.md").read_text(encoding="utf-8")
    assert file_sha256(SAMPLE) in text
    assert "Velas: 800" in text
    assert "Simulación educativa" in text
    assert "Simulación educativa" in capsys.readouterr().out
