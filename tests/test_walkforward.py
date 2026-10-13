"""Selección walk-forward con datos sintéticos (sin red ni datos reales)."""

import csv
import math
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bottrading.config import BacktestConfig
from bottrading.data import Candle
from bottrading.splits import DAILY, Scheme, evaluate_segment, plan_splits
from bottrading.walkforward import (
    Candidate,
    CandidateScore,
    WindowScore,
    default_grid,
    main,
    run_selection,
)
from bottrading.strategy import crossover_signals

START = datetime(2020, 1, 1, tzinfo=timezone.utc)
CONFIG = BacktestConfig(initial_capital=10_000)
SMALL = Scheme(initial_train_months=3, validation_months=1, windows=3)


def candles_from(prices):
    return [Candle(START + timedelta(days=i), p, p * 1.01, p * 0.99, p, 1.0)
            for i, p in enumerate(prices)]


def wave(days):
    """Serie determinista con tendencias y ciclos (sin azar)."""
    return [100 * (1 + 0.3 * math.sin(i / 40)) * (1 + i / 3000) for i in range(days)]


SMALL_GRID = [
    Candidate("sma_crossover", (("fast", 5), ("slow", 20))),
    Candidate("trend_filter", (("window", 10),)),
    Candidate("donchian", (("entry", 10), ("exit", 5))),
]


# --- rejilla ---------------------------------------------------------------------------


def test_default_grid_matches_d021():
    grid = default_grid()
    assert len(grid) == 22
    by_strategy = {}
    for candidate in grid:
        by_strategy.setdefault(candidate.strategy, []).append(candidate)
    assert {k: len(v) for k, v in by_strategy.items()} == {
        "sma_crossover": 8, "trend_filter": 5, "donchian": 9}
    assert all(dict(c.params)["fast"] < dict(c.params)["slow"]
               for c in by_strategy["sma_crossover"])
    assert len({c.label for c in grid}) == 22


def test_candidate_label_and_signals():
    candidate = Candidate("sma_crossover", (("fast", 2), ("slow", 3)))
    assert candidate.label == "sma_crossover(fast=2, slow=3)"
    closes = [10, 9, 8, 7, 6, 7, 8, 9, 10]
    assert candidate.signals(closes) == crossover_signals(closes, 2, 3)


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError, match="desconocida"):
        Candidate("magia", ()).signals([1.0, 2.0])


# --- puntuación y ranking -----------------------------------------------------------


def score(label, sharpes, drawdowns):
    windows = [WindowScore(i + 1, s, 0.0, d, 0) for i, (s, d) in
               enumerate(zip(sharpes, drawdowns))]
    return CandidateScore(Candidate(label, ()), windows)


def test_median_sharpe_counts_unavailable_as_zero():
    assert score("x", [1.0, None, -1.0, 2.0, None], [0.1] * 5).median_sharpe == 0.0
    assert score("x", [3.0, 1.0, 2.0], [0.1] * 3).median_sharpe == 2.0


def test_ranking_uses_median_sharpe_then_drawdown():
    candles = candles_from(wave(400))
    plan = plan_splits([c.timestamp for c in candles], SMALL)
    result = run_selection(candles, plan, SMALL_GRID, CONFIG)
    keys = [(-s.median_sharpe, s.median_drawdown) for s in result.ranking]
    assert keys == sorted(keys)
    assert result.trials == 3
    assert result.winner is result.ranking[0]


def test_window_scores_match_direct_evaluation():
    candles = candles_from(wave(400))
    plan = plan_splits([c.timestamp for c in candles], SMALL)
    result = run_selection(candles, plan, SMALL_GRID[:1], CONFIG)
    from bottrading.metrics import compute_metrics
    for window, scored in zip(plan.windows, result.ranking[0].windows):
        direct = compute_metrics(evaluate_segment(
            candles, window.validation_start, window.validation_end,
            SMALL_GRID[0].signals, CONFIG))
        assert scored.sharpe == direct.sharpe
        assert scored.total_return == direct.total_return
        assert scored.volatility == direct.volatility  # revisión de Codex de T016


def test_benchmark_is_evaluated_on_the_same_windows():
    candles = candles_from(wave(400))
    plan = plan_splits([c.timestamp for c in candles], SMALL)
    result = run_selection(candles, plan, SMALL_GRID, CONFIG)
    assert [w.window for w in result.benchmark] == [w.number for w in plan.windows]


def test_has_edge_depends_on_winner_median():
    candles = candles_from(wave(400))
    plan = plan_splits([c.timestamp for c in candles], SMALL)
    result = run_selection(candles, plan, SMALL_GRID, CONFIG)
    assert result.has_edge is (result.winner.median_sharpe > 0)


def test_selection_ignores_holdout_prices():
    # Requisito de T016: alterar el holdout no cambia nada de la selección.
    candles = candles_from(wave(400))
    plan = plan_splits([c.timestamp for c in candles], SMALL)
    altered = candles[:plan.holdout_start] + [
        replace(c, open=c.open * 5, high=c.high * 5, low=c.low * 5, close=c.close * 5)
        for c in candles[plan.holdout_start:]
    ]
    assert run_selection(candles, plan, SMALL_GRID, CONFIG) == \
        run_selection(altered, plan, SMALL_GRID, CONFIG)


def test_selection_works_without_holdout_candles():
    # Solo con las velas de selección se obtiene el mismo resultado.
    candles = candles_from(wave(400))
    plan = plan_splits([c.timestamp for c in candles], SMALL)
    assert run_selection(candles[:plan.holdout_start], plan, SMALL_GRID, CONFIG) == \
        run_selection(candles, plan, SMALL_GRID, CONFIG)


@pytest.mark.parametrize(
    ("grid", "message"),
    [([], "vacía"), ([SMALL_GRID[0], SMALL_GRID[0]], "repetidas")],
)
def test_invalid_grids_are_rejected(grid, message):
    candles = candles_from(wave(400))
    plan = plan_splits([c.timestamp for c in candles], SMALL)
    with pytest.raises(ValueError, match=message):
        run_selection(candles, plan, grid, CONFIG)


def test_too_few_candles_for_plan_is_rejected():
    candles = candles_from(wave(400))
    plan = plan_splits([c.timestamp for c in candles], SMALL)
    with pytest.raises(ValueError, match="menos velas"):
        run_selection(candles[:plan.holdout_start - 1], plan, SMALL_GRID, CONFIG)


# --- informe y CLI ---------------------------------------------------------------------


def write_klines(directory, prices):
    """Un ZIP mensual por cada 30 velas, con el formato de Binance."""
    directory.mkdir(parents=True, exist_ok=True)
    day_us = 86_400_000_000
    base_us = int(START.timestamp()) * 1_000_000
    for chunk, offset in enumerate(range(0, len(prices), 30)):
        rows = []
        for i, price in enumerate(prices[offset:offset + 30], start=offset):
            open_us = base_us + i * day_us
            rows.append(f"{open_us},{price},{price * 1.01},{price * 0.99},{price},"
                        f"1.0,{open_us + day_us - 1},0,0,0,0,0")
        with zipfile.ZipFile(directory / f"SYN-1d-{chunk:03d}.zip", "w") as archive:
            archive.writestr(f"SYN-1d-{chunk:03d}.csv", "\n".join(rows) + "\n")


def test_cli_writes_selection_report_without_holdout_metrics(tmp_path, capsys):
    data = tmp_path / "SYN-1d"
    write_klines(data, wave(2465))  # misma longitud que los datos reales
    out = tmp_path / "out"
    assert main(["--binance", str(data), "--scheme", "daily", "--out", str(out)]) == 0
    text = (out / "selection.md").read_text(encoding="utf-8")
    assert "El holdout final no se ha usado" in text
    assert "Combinaciones probadas: **22**" in text
    assert "(sin usar)" in text
    assert "buy-and-hold (referencia)" in text
    assert "| Mediana volatilidad |" in text
    assert "Retorno neto por ventana de la elegida frente a buy-and-hold" in text
    with (out / "trials.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 22 * 5 + 5  # 22 combinaciones × 5 ventanas + referencia
    assert all(row["volatility"] for row in rows)
    assert "Holdout final sin usar" in capsys.readouterr().out


def test_cli_report_is_reproducible(tmp_path):
    data = tmp_path / "SYN-1d"
    write_klines(data, wave(2465))
    for name in ("a", "b"):
        assert main(["--binance", str(data), "--out", str(tmp_path / name)]) == 0
    for file in ("selection.md", "trials.csv"):
        assert (tmp_path / "a" / file).read_bytes() == (tmp_path / "b" / file).read_bytes()


def test_cli_rejects_insufficient_data(tmp_path, capsys):
    data = tmp_path / "SYN-1d"
    write_klines(data, wave(300))
    assert main(["--binance", str(data), "--scheme", "daily", "--out", str(tmp_path / "o")]) == 2
    assert "necesita datos desde" in capsys.readouterr().err


def test_daily_scheme_is_the_default():
    from bottrading.walkforward import SCHEMES, build_parser
    args = build_parser().parse_args(["--binance", "x"])
    assert SCHEMES[args.scheme] is DAILY
