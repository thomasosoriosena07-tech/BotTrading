"""Evaluación del holdout con datos sintéticos (nunca con los datos reales)."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from bottrading.config import BacktestConfig
from bottrading.data import Candle
from bottrading.holdout import (
    SCENARIOS,
    evaluate_holdout,
    main,
    parse_candidate,
)
from bottrading.metrics import compute_metrics
from bottrading.splits import DAILY, evaluate_segment, plan_splits
from bottrading.strategy import buy_and_hold_signals
from bottrading.walkforward import Candidate
from tests.test_walkforward import write_klines

START = datetime(2020, 1, 1, tzinfo=timezone.utc)
CANDIDATE = Candidate("trend_filter", (("window", 50),))


def candles_from(prices):
    return [Candle(START + timedelta(days=i), p, p * 1.01, p * 0.99, p, 1.0)
            for i, p in enumerate(prices)]


def wave(days):
    return [100 * (1 + 0.3 * math.sin(i / 40)) * (1 + i / 3000) for i in range(days)]


@pytest.fixture(scope="module")
def setup():
    candles = candles_from(wave(2465))
    plan = plan_splits([c.timestamp for c in candles], DAILY)
    return candles, plan, evaluate_holdout(candles, plan, CANDIDATE)


def test_scenarios_match_d023():
    assert [(s.name, s.commission_rate, s.slippage_rate) for s in SCENARIOS] == [
        ("sin costes", 0.0, 0.0), ("bajo", 0.00075, 0.0002),
        ("base", 0.001, 0.0005), ("alto", 0.002, 0.001)]


def test_runs_cover_only_the_holdout(setup):
    candles, plan, result = setup
    holdout_times = [c.timestamp for c in candles[plan.holdout_start:]]
    for run in result.runs:
        assert run.strategy.timestamps == holdout_times
        assert run.benchmark.timestamps == holdout_times


def test_base_run_matches_direct_evaluation(setup):
    candles, plan, result = setup
    config = BacktestConfig(10_000, commission_rate=0.001, slippage_rate=0.0005)
    direct = evaluate_segment(candles, plan.holdout_start, plan.holdout_end,
                              CANDIDATE.signals, config)
    assert result.run("base").strategy == direct
    bench = evaluate_segment(candles, plan.holdout_start, plan.holdout_end,
                             lambda closes: buy_and_hold_signals(len(closes)), config)
    assert result.run("base").benchmark == bench
    assert result.run("base").strategy_metrics == compute_metrics(direct)


def test_higher_costs_never_help(setup):
    _, _, result = setup
    returns = [run.strategy_metrics.total_return for run in result.runs]
    assert returns == sorted(returns, reverse=True)  # sin costes >= bajo >= base >= alto


def test_verdict_applies_d023_rules(setup):
    _, _, result = setup
    base = result.run("base")
    verdict = result.verdict
    assert verdict.earns_more is (base.excess_return > 0)
    assert verdict.better_risk_adjusted is (
        base.strategy_metrics.sharpe > base.benchmark_metrics.sharpe)
    signs = {result.run(n).excess_return > 0 for n in ("bajo", "base", "alto")}
    assert verdict.robust_to_costs is (len(signs) == 1)


def test_mismatched_candles_are_rejected(setup):
    candles, plan, _ = setup
    with pytest.raises(ValueError, match="no coinciden"):
        evaluate_holdout(candles[:-1], plan, CANDIDATE)


# --- parse_candidate ---------------------------------------------------------------


def test_parse_candidate():
    assert parse_candidate("trend_filter:window=50") == CANDIDATE
    assert parse_candidate("sma_crossover:fast=10,slow=50") == Candidate(
        "sma_crossover", (("fast", 10), ("slow", 50)))


@pytest.mark.parametrize("text", ["trend_filter:window=51", "magia:x=1",
                                  "trend_filter:window=abc", "trend_filter"])
def test_parse_candidate_rejects_unregistered(text):
    with pytest.raises(ValueError):
        parse_candidate(text)


# --- CLI ------------------------------------------------------------------------------


def test_cli_requires_explicit_confirmation(tmp_path, capsys):
    assert main(["--binance", str(tmp_path), "--candidate", "trend_filter:window=50"]) == 2
    assert "--open-holdout" in capsys.readouterr().err


def test_cli_writes_holdout_report(tmp_path, capsys):
    data = tmp_path / "SYN-1d"
    write_klines(data, wave(2465))
    out = tmp_path / "out"
    code = main(["--binance", str(data), "--candidate", "trend_filter:window=50",
                 "--open-holdout", "--out", str(out)])
    assert code == 0
    text = (out / "holdout.md").read_text(encoding="utf-8")
    assert "trend_filter(window=50)" in text and "D023" in text
    assert "## Interpretación (reglas de D023" in text
    assert "| alto | 0.200 % | 0.100 % |" in text
    assert (out / "trades.csv").exists() and (out / "equity.csv").exists()


def test_cli_report_is_reproducible(tmp_path):
    data = tmp_path / "SYN-1d"
    write_klines(data, wave(2465))
    for name in ("a", "b"):
        main(["--binance", str(data), "--candidate", "trend_filter:window=50",
              "--open-holdout", "--out", str(tmp_path / name)])
    for file in ("holdout.md", "trades.csv", "equity.csv"):
        assert (tmp_path / "a" / file).read_bytes() == (tmp_path / "b" / file).read_bytes()


def test_cli_rejects_unregistered_candidate(tmp_path, capsys):
    data = tmp_path / "SYN-1d"
    write_klines(data, wave(2465))
    assert main(["--binance", str(data), "--candidate", "trend_filter:window=51",
                 "--open-holdout", "--out", str(tmp_path / "o")]) == 2
    assert "no está en la rejilla" in capsys.readouterr().err
