"""EXP-15M-001: validación walk-forward y selección única (A.6-A.8). Sin red."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from bottrading import exp15m_eval
from bottrading.data import Candle, DataValidationError
from bottrading.exp15m_eval import (
    CONFIGS,
    QUARTERS,
    Evaluation,
    bounds,
    cached_signals,
    label,
    render_report,
    render_trials,
    run_validation,
    select,
)
from bottrading.exp15m_eval import SCENARIOS
from bottrading.strategy import donchian_signals

UTC = timezone.utc
STEP = timedelta(minutes=15)


def test_quarters_are_the_eleven_natural_quarters_2024_to_2026q3():
    assert len(QUARTERS) == 11
    assert QUARTERS[0][0] == datetime(2024, 1, 1, tzinfo=UTC)
    assert QUARTERS[-1] == (datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    assert all(a[1] == b[0] for a, b in zip(QUARTERS, QUARTERS[1:]))  # contiguos


def test_configs_are_the_four_preregistered_ones():
    assert CONFIGS == ((48, 24), (48, 48), (96, 24), (96, 48))


def test_copied_baseline_values_are_identical_to_the_frozen_ones():
    # El evaluador no importa holdout/crossasset (arrastran report y paper); la copia
    # debe coincidir exactamente con los valores congelados del baseline.
    from bottrading import crossasset, holdout
    assert [(s.name, s.commission_rate, s.slippage_rate) for s in exp15m_eval.SCENARIOS] == \
        [(s.name, s.commission_rate, s.slippage_rate) for s in holdout.SCENARIOS]
    assert crossasset.FROZEN_CANDIDATE.strategy == "trend_filter"
    assert crossasset.FROZEN_CANDIDATE.params == (("window", exp15m_eval.BASELINE_WINDOW),)
    closes = [100 + math.sin(i / 3) * 4 + i * 0.1 for i in range(200)]
    assert exp15m_eval.baseline_signals(closes) == crossasset.FROZEN_CANDIDATE.signals(closes)


def ev(config, segment, sharpe, drawdown, scenario="base"):
    return Evaluation(label(config), segment, scenario, None, 0.0, sharpe, drawdown)


def evaluations_with(sharpes: dict, drawdowns: dict | None = None):
    rows = []
    for config in CONFIGS:
        for q in range(len(QUARTERS)):
            dd = (drawdowns or {}).get(config, 0.1)
            rows.append(ev(config, f"q{q}", sharpes[config][q], dd))
            rows.append(ev(config, f"q{q}", 99.0, 0.0, scenario="alto"))  # no cuenta
        rows.append(ev(config, "desarrollo", 99.0, 0.0))  # no cuenta
    return rows


def test_selection_uses_median_sharpe_of_base_quarters_only():
    sharpes = {c: [0.5] * 11 for c in CONFIGS}
    sharpes[(96, 24)] = [1.0] * 6 + [-5.0] * 5  # mediana 1.0
    selection = select(evaluations_with(sharpes))
    assert selection.config == (96, 24) and selection.c7
    assert selection.medians[(96, 24)][0] == 1.0


def test_unavailable_sharpe_counts_as_zero_and_c7_requires_positive():
    sharpes = {c: [None] * 11 for c in CONFIGS}
    selection = select(evaluations_with(sharpes))
    assert all(m[0] == 0.0 for m in selection.medians.values())
    assert not selection.c7


def test_ties_break_by_lower_median_drawdown_then_config_order():
    sharpes = {c: [0.3] * 11 for c in CONFIGS}
    drawdowns = {(48, 24): 0.2, (48, 48): 0.05, (96, 24): 0.05, (96, 48): 0.3}
    assert select(evaluations_with(sharpes, drawdowns)).config == (48, 48)


def test_selection_rejects_missing_quarters():
    rows = [r for r in evaluations_with({c: [0.1] * 11 for c in CONFIGS}) if r.segment != "q3"]
    with pytest.raises(ValueError, match="trimestres"):
        select(rows)


def test_cached_signals_equal_direct_computation_on_every_prefix():
    closes = [100 + math.sin(i / 7) * 5 + i * 0.01 for i in range(400)]
    signals = cached_signals(closes, (48, 24), check_points=[100, 250, 400])
    for cut in (1, 49, 100, 333, 400):
        assert signals(closes[:cut]) == donchian_signals(closes[:cut], 48, 24)
    with pytest.raises(ValueError, match="prefijos"):
        signals([1.0, 2.0])


def test_bounds_and_empty_segment():
    candles = synthetic(datetime(2024, 1, 1, tzinfo=UTC), 10)
    assert bounds(candles, candles[2].timestamp, candles[5].timestamp) == (2, 5)
    with pytest.raises(DataValidationError):
        bounds(candles, candles[5].timestamp, candles[5].timestamp)


# --- tubería completa con datos sintéticos (trimestres reducidos a días) ---------------


def synthetic(start: datetime, count: int, step: timedelta = STEP, seed: float = 0.0) -> list[Candle]:
    out = []
    for i in range(count):
        price = 100 + 8 * math.sin((i + seed) / 37) + 3 * math.sin((i + seed) / 5) + i * 0.002
        out.append(Candle(start + i * step, price, price * 1.002, price * 0.998, price, 1e6))
    return out


@pytest.fixture
def small_protocol(monkeypatch):
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    days = [(t0 + timedelta(days=d), t0 + timedelta(days=d + 1)) for d in range(3, 6)]
    monkeypatch.setattr(exp15m_eval, "DEVELOPMENT", (t0, t0 + timedelta(days=3)))
    monkeypatch.setattr(exp15m_eval, "QUARTERS", tuple(days))
    monkeypatch.setattr(exp15m_eval, "quarter_name", lambda start: f"d{start:%d}")
    return t0


def run_small(candles):
    daily = synthetic(datetime(2023, 11, 1, tzinfo=UTC), 70, step=timedelta(days=1))
    return run_validation(candles, daily, frozenset())


def test_full_validation_pipeline_on_synthetic_data(small_protocol):
    candles = synthetic(small_protocol, 6 * 96)
    evaluations, selection, references = run_small(candles)
    strategies = [e for e in evaluations if e.label.startswith("donchian")]
    assert len(strategies) == len(CONFIGS) * 4 * len(SCENARIOS)  # 3 "trimestres" + desarrollo
    assert {e.label for e in evaluations} == {label(c) for c in CONFIGS} | {"buy-and-hold",
                                                                            "baseline T019"}
    assert selection.config in CONFIGS
    assert list(references) == ["desarrollo", "d04", "d05", "d06"]
    assert references["d05"][2] == 96
    report = render_report(evaluations, selection, references, "p" * 64, "m" * 64, "d" * 64)
    assert "Elegida: **" in report and "No es un resultado real" in report
    assert len(render_trials(evaluations).splitlines()) == 1 + len(evaluations)


def test_validation_results_do_not_depend_on_later_candles(small_protocol):
    # A.10 (prefijos de la tubería): cambiar las velas del último día no cambia
    # ningún resultado de los tramos anteriores (desarrollo, d04 y d05).
    candles = synthetic(small_protocol, 6 * 96)
    first, _, _ = run_small(candles)
    changed = candles[:5 * 96] + synthetic(small_protocol + timedelta(days=5), 96, seed=999.0)
    second, _, _ = run_small(changed)

    def results(rows):
        return {(e.label, e.segment, e.scenario): (e.net_return, e.sharpe, e.max_drawdown)
                for e in rows if e.segment != "d06" and e.label != "baseline T019"}
    assert results(first) == results(second)
    assert len(results(first)) == 5 * 3 * len(SCENARIOS)  # 4 configuraciones + buy-and-hold
    last = {(e.label, e.scenario): e.net_return for e in first if e.segment == "d06"}
    assert last != {(e.label, e.scenario): e.net_return for e in second if e.segment == "d06"}


def test_validation_refuses_holdout_data(small_protocol):
    late = synthetic(datetime(2026, 9, 30, 23, 0, tzinfo=UTC), 8)
    daily = synthetic(datetime(2026, 9, 1, tzinfo=UTC), 30, step=timedelta(days=1))
    with pytest.raises(DataValidationError, match="2026-10-01"):
        run_validation(late, daily, frozenset())


def test_cli_without_data_fails_cleanly(tmp_path, capsys):
    assert exp15m_eval.main(["validate", "--data", str(tmp_path / "x"),
                             "--daily", str(tmp_path / "y"), "--out", str(tmp_path)]) == 2
    assert "error" in capsys.readouterr().err
