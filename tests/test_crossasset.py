"""Comprobación en otros activos con datos sintéticos (sin datos reales)."""

import math
import zipfile
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from bottrading.crossasset import (
    CONFIG,
    FROZEN_CANDIDATE,
    SEGMENTS,
    AssetResult,
    SegmentResult,
    evaluate_asset,
    main,
    segment_bounds,
)
from bottrading.data import Candle
from bottrading.metrics import compute_metrics
from bottrading.splits import evaluate_segment

START = datetime(2020, 1, 1, tzinfo=timezone.utc)
DAYS = 2465  # 2020-01-01 a 2026-09-30


def wave(days, phase=0.0):
    return [100 * (1 + 0.3 * math.sin(i / 40 + phase)) * (1 + i / 3000) for i in range(days)]


def candles_from(prices, start=START):
    return [Candle(start + timedelta(days=i), p, p * 1.01, p * 0.99, p, 1.0)
            for i, p in enumerate(prices)]


def write_klines(directory, candles):
    directory.mkdir(parents=True)
    day_us = 86_400_000_000
    for chunk in range(0, len(candles), 31):
        rows = []
        for c in candles[chunk:chunk + 31]:
            t = int(c.timestamp.timestamp()) * 1_000_000
            rows.append(f"{t},{c.open},{c.high},{c.low},{c.close},1.0,{t + day_us - 1},0,0,0,0,0")
        with zipfile.ZipFile(directory / f"X-1d-{chunk:05d}.zip", "w") as archive:
            archive.writestr(f"X-1d-{chunk:05d}.csv", "\n".join(rows) + "\n")


def test_segments_are_the_btc_dates():
    assert SEGMENTS[0][1] == date(2022, 11, 26)
    assert SEGMENTS[-1] == ("holdout", date(2025, 5, 26), date(2026, 9, 30))
    for (_, _, end), (_, start, _) in zip(SEGMENTS, SEGMENTS[1:]):
        assert start == end + timedelta(days=1)  # consecutivos, sin huecos


def test_frozen_configuration_matches_d022_and_d014():
    assert FROZEN_CANDIDATE.label == "trend_filter(window=50)"
    assert (CONFIG.initial_capital, CONFIG.commission_rate, CONFIG.slippage_rate) == (
        10_000, 0.001, 0.0005)


def test_segment_bounds_find_inclusive_dates():
    candles = candles_from(wave(DAYS))
    start, end = segment_bounds(candles, date(2022, 11, 26), date(2023, 5, 25))
    assert candles[start].timestamp.date() == date(2022, 11, 26)
    assert candles[end - 1].timestamp.date() == date(2023, 5, 25)


def test_segment_bounds_reject_missing_days():
    candles = candles_from(wave(DAYS))
    gapped = candles[:1100] + candles[1101:]
    with pytest.raises(ValueError, match="faltan velas"):
        segment_bounds(gapped, date(2022, 11, 26), date(2023, 5, 25))


def test_segment_bounds_require_warmup():
    late = candles_from(wave(1500), start=datetime(2022, 10, 20, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="calentamiento"):
        segment_bounds(late, date(2022, 11, 26), date(2023, 5, 25))


def test_asset_evaluation_matches_direct_segments():
    candles = candles_from(wave(DAYS))
    result = evaluate_asset("X", candles)
    assert [s.name for s in result.segments] == [s[0] for s in SEGMENTS]
    start, end = segment_bounds(candles, SEGMENTS[2][1], SEGMENTS[2][2])
    direct = compute_metrics(evaluate_segment(candles, start, end,
                                              FROZEN_CANDIDATE.signals, CONFIG))
    assert result.segments[2].strategy == direct


def test_later_candles_do_not_affect_earlier_segments():
    candles = candles_from(wave(DAYS))
    altered = candles[:2300] + [replace(c, open=c.open * 4, high=c.high * 4,
                                        low=c.low * 4, close=c.close * 4)
                                for c in candles[2300:]]  # solo el final del holdout
    original, changed = evaluate_asset("X", candles), evaluate_asset("X", altered)
    assert original.segments[:5] == changed.segments[:5]


def metrics_with(total_return, drawdown):
    base = compute_metrics(evaluate_segment(candles_from([100.0] * 60), 55, 60,
                                            FROZEN_CANDIDATE.signals, CONFIG))
    return replace(base, total_return=total_return, max_drawdown=drawdown)


def segment(strategy_return, bench_return, strategy_dd=0.1, bench_dd=0.2):
    return SegmentResult("S", metrics_with(strategy_return, strategy_dd),
                         metrics_with(bench_return, bench_dd))


def test_d025_rules():
    asset = AssetResult("X", [
        segment(0.05, -0.20),  # bajista, gana
        segment(0.30, 0.50),  # alcista, se queda atrás
        segment(0.10, 0.15),
        segment(0.02, 0.05, 0.3, 0.2),  # más drawdown
        segment(-0.01, -0.10),  # bajista, gana
        segment(0.20, 0.25),
    ])
    assert asset.protected_segments == 5 and asset.protection
    assert asset.bear_outperformance is True
    assert asset.bull_lag == 4
    assert asset.pattern_repeats


def test_d025_pattern_fails_if_it_loses_in_a_bear_segment():
    asset = AssetResult("X", [segment(-0.30, -0.20)] + [segment(0.1, 0.2)] * 5)
    assert asset.bear_outperformance is False
    assert not asset.pattern_repeats


def test_d025_pattern_fails_without_protection():
    asset = AssetResult("X", [segment(0.1, 0.2, 0.3, 0.2)] * 3 + [segment(0.1, 0.2)] * 3)
    assert asset.protected_segments == 3 and not asset.protection
    assert not asset.pattern_repeats


def test_no_bear_segments_gives_none():
    asset = AssetResult("X", [segment(0.1, 0.2)] * 6)
    assert asset.bear_outperformance is None
    assert asset.pattern_repeats  # solo depende de la protección


def test_cli_writes_report_for_several_assets(tmp_path, capsys):
    write_klines(tmp_path / "AAA-1d", candles_from(wave(DAYS)))
    write_klines(tmp_path / "BBB-1d", candles_from(wave(DAYS, phase=1.5)))
    out = tmp_path / "out"
    assert main(["--asset", str(tmp_path / "AAA-1d"), "--asset", str(tmp_path / "BBB-1d"),
                 "--out", str(out)]) == 0
    text = (out / "crossasset.md").read_text(encoding="utf-8")
    assert "## AAA-1d" in text and "## BBB-1d" in text and "D025" in text
    assert "¿Se repite el patrón de BTC (D025)?" in text
    rows = (out / "segments.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 + 2 * 6 * 2  # cabecera + activos × tramos × (estrategia, b&h)


def test_cli_is_reproducible(tmp_path):
    write_klines(tmp_path / "AAA-1d", candles_from(wave(DAYS)))
    for name in ("a", "b"):
        main(["--asset", str(tmp_path / "AAA-1d"), "--out", str(tmp_path / name)])
    for file in ("crossasset.md", "segments.csv"):
        assert (tmp_path / "a" / file).read_bytes() == (tmp_path / "b" / file).read_bytes()


def test_cli_rejects_asset_without_enough_history(tmp_path, capsys):
    short = candles_from(wave(1500), start=datetime(2022, 10, 20, tzinfo=timezone.utc))
    write_klines(tmp_path / "NEW-1d", short)
    assert main(["--asset", str(tmp_path / "NEW-1d"), "--out", str(tmp_path / "o")]) == 2
    assert "calentamiento" in capsys.readouterr().err
