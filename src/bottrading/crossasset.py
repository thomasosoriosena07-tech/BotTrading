"""Comprobación en otros activos de la estrategia congelada (protocolo D025).

Evalúa trend_filter(window=50) (D022) frente a buy-and-hold en los mismos
tramos de calendario usados con BTC (5 validaciones + holdout), con costes
base, y aplica las reglas de interpretación fijadas en D025. No elige ni
ajusta nada: la estrategia y los tramos están congelados.

Uso:
    python -m bottrading.crossasset --asset data/BTCUSDT-1d \
        --asset data/ETHUSDT-1d --asset data/SOLUSDT-1d
"""

import argparse
import bisect
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from bottrading.binance import expand_paths, load_binance_klines
from bottrading.config import BacktestConfig
from bottrading.data import Candle, DataValidationError
from bottrading.metrics import Metrics, compute_metrics
from bottrading.report import write_crossasset_report
from bottrading.splits import evaluate_segment
from bottrading.strategy import buy_and_hold_signals
from bottrading.walkforward import Candidate

# D025: congelado antes de ejecutar con ETH y SOL.
FROZEN_CANDIDATE = Candidate("trend_filter", (("window", 50),))
CONFIG = BacktestConfig(initial_capital=10_000.0, commission_rate=0.001, slippage_rate=0.0005)
SEGMENTS = (  # fechas inclusivas, iguales a las de BTC en D020/D022/D024
    ("V1", date(2022, 11, 26), date(2023, 5, 25)),
    ("V2", date(2023, 5, 26), date(2023, 11, 25)),
    ("V3", date(2023, 11, 26), date(2024, 5, 25)),
    ("V4", date(2024, 5, 26), date(2024, 11, 25)),
    ("V5", date(2024, 11, 26), date(2025, 5, 25)),
    ("holdout", date(2025, 5, 26), date(2026, 9, 30)),
)
MIN_PROTECTED_SEGMENTS = 4  # D025: menor drawdown en al menos 4 de 6 tramos


@dataclass(frozen=True)
class SegmentResult:
    name: str
    strategy: Metrics
    benchmark: Metrics

    @property
    def bearish(self) -> bool:
        """Tramo bajista según D025: buy-and-hold pierde."""
        return self.benchmark.total_return < 0


@dataclass(frozen=True)
class AssetResult:
    name: str
    segments: list[SegmentResult]

    @property
    def protected_segments(self) -> int:
        return sum(s.strategy.max_drawdown < s.benchmark.max_drawdown for s in self.segments)

    @property
    def protection(self) -> bool:
        return self.protected_segments >= MIN_PROTECTED_SEGMENTS

    @property
    def bear_outperformance(self) -> bool | None:
        """Gana a buy-and-hold en TODOS los tramos bajistas; None si no hay."""
        bears = [s for s in self.segments if s.bearish]
        if not bears:
            return None
        return all(s.strategy.total_return > s.benchmark.total_return for s in bears)

    @property
    def bull_lag(self) -> int:
        """Tramos alcistas en los que gana menos que buy-and-hold (informativo)."""
        return sum(s.strategy.total_return < s.benchmark.total_return
                   for s in self.segments if not s.bearish)

    @property
    def pattern_repeats(self) -> bool:
        """D025: protección y ganar en todos los tramos bajistas (si los hay)."""
        return self.protection and self.bear_outperformance is not False


def segment_bounds(candles: Sequence[Candle], first: date, last: date) -> tuple[int, int]:
    """Índices [inicio, fin) del tramo; exige velas diarias completas en él."""
    days = [candle.timestamp.date() for candle in candles]
    start = bisect.bisect_left(days, first)
    end = bisect.bisect_right(days, last)
    expected = (last - first).days + 1
    if end - start != expected or days[start] != first:
        raise ValueError(f"faltan velas diarias entre {first} y {last} "
                         f"({end - start} de {expected})")
    if start < 50:
        raise ValueError(f"menos de 50 velas antes de {first}: sin calentamiento")
    return start, end


def evaluate_asset(name: str, candles: Sequence[Candle]) -> AssetResult:
    results = []
    for label, first, last in SEGMENTS:
        start, end = segment_bounds(candles, first, last)
        # Las velas posteriores al tramo no intervienen (evaluate_segment
        # usa solo candles[:end]).
        strategy = evaluate_segment(candles, start, end, FROZEN_CANDIDATE.signals, CONFIG)
        benchmark = evaluate_segment(candles, start, end,
                                     lambda closes: buy_and_hold_signals(len(closes)), CONFIG)
        results.append(SegmentResult(label, compute_metrics(strategy),
                                     compute_metrics(benchmark)))
    return AssetResult(name, results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bottrading.crossasset",
        description="Estrategia congelada en otros activos (D025). Solo simulación.",
    )
    parser.add_argument("--asset", type=Path, action="append", required=True, metavar="CARPETA",
                        help="carpeta con klines diarios de un activo (repetible)")
    parser.add_argument("--out", type=Path, default=Path("reports") / "crossasset")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        assets, all_paths = [], []
        for folder in args.asset:
            paths = expand_paths([folder])
            assets.append(evaluate_asset(Path(folder).name, load_binance_klines(paths)))
            all_paths.extend(paths)
        written = write_crossasset_report(args.out, data_paths=all_paths, assets=assets)
    except (DataValidationError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("Simulación educativa: no son resultados reales.")
    for path in written.values():
        print(f"escrito {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
