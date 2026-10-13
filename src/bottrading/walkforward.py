"""Selección walk-forward de estrategia y parámetros (D021, D022).

Evalúa cada combinación de la rejilla en las ventanas de validación del
plan (D020) y elige con el criterio fijado de antemano: mayor mediana del
Sharpe por ventana; desempate por menor mediana del drawdown máximo.

El holdout final NO se usa: run_selection recorta las velas en
`plan.holdout_start` antes de evaluar nada.

Uso:
    python -m bottrading.walkforward --binance data/BTCUSDT-1d --scheme daily
"""

import argparse
import logging
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bottrading.binance import expand_paths, load_binance_klines
from bottrading.config import BacktestConfig
from bottrading.data import Candle, DataValidationError
from bottrading.metrics import compute_metrics
from bottrading.report import write_selection_report
from bottrading.splits import DAILY, HOURLY, SplitPlan, evaluate_segment, plan_splits
from bottrading.strategy import (
    Signal,
    buy_and_hold_signals,
    crossover_signals,
    donchian_signals,
    trend_filter_signals,
)

SCHEMES = {"daily": DAILY, "hourly": HOURLY}


@dataclass(frozen=True)
class Candidate:
    strategy: str  # "sma_crossover", "trend_filter" o "donchian"
    params: tuple[tuple[str, int], ...]

    @property
    def label(self) -> str:
        args = ", ".join(f"{name}={value}" for name, value in self.params)
        return f"{self.strategy}({args})"

    def signals(self, closes: Sequence[float]) -> list[Signal]:
        p = dict(self.params)
        if self.strategy == "sma_crossover":
            return crossover_signals(closes, p["fast"], p["slow"])
        if self.strategy == "trend_filter":
            return trend_filter_signals(closes, p["window"])
        if self.strategy == "donchian":
            return donchian_signals(closes, p["entry"], p["exit"])
        raise ValueError(f"estrategia desconocida: {self.strategy}")


def default_grid() -> list[Candidate]:
    """Las 22 combinaciones registradas en D021 antes de ejecutar."""
    grid = [
        Candidate("sma_crossover", (("fast", fast), ("slow", slow)))
        for fast in (10, 20, 50) for slow in (50, 100, 200) if fast < slow
    ]
    grid += [Candidate("trend_filter", (("window", n),)) for n in (20, 50, 100, 150, 200)]
    grid += [
        Candidate("donchian", (("entry", entry), ("exit", exit)))
        for entry in (20, 55, 100) for exit in (10, 20, 50)
    ]
    return grid


@dataclass(frozen=True)
class WindowScore:
    window: int
    sharpe: float | None
    total_return: float
    max_drawdown: float
    num_trades: int
    volatility: float | None = None  # anualizada; informativa (no decide)


@dataclass(frozen=True)
class CandidateScore:
    candidate: Candidate
    windows: list[WindowScore]

    @property
    def median_sharpe(self) -> float:
        # D021: Sharpe no disponible (p. ej. todo el tramo en efectivo) = 0.
        return statistics.median(w.sharpe if w.sharpe is not None else 0.0
                                 for w in self.windows)

    @property
    def median_drawdown(self) -> float:
        return statistics.median(w.max_drawdown for w in self.windows)


@dataclass(frozen=True)
class SelectionResult:
    plan: SplitPlan
    ranking: list[CandidateScore]  # de mejor a peor según D021
    benchmark: list[WindowScore]  # buy-and-hold en las mismas ventanas

    @property
    def winner(self) -> CandidateScore:
        return self.ranking[0]

    @property
    def has_edge(self) -> bool:
        """D021: sin ventaja si la mediana del Sharpe ganadora es <= 0."""
        return self.winner.median_sharpe > 0

    @property
    def trials(self) -> int:
        return len(self.ranking)


def run_selection(
    candles: Sequence[Candle],
    plan: SplitPlan,
    candidates: Sequence[Candidate],
    config: BacktestConfig,
    risk_free_rate: float = 0.0,
) -> SelectionResult:
    if not candidates:
        raise ValueError("la rejilla está vacía")
    if len({c.label for c in candidates}) != len(candidates):
        raise ValueError("la rejilla tiene combinaciones repetidas")
    if len(candles) < plan.holdout_start:
        raise ValueError("hay menos velas que las que indica el plan")
    selection = list(candles[:plan.holdout_start])  # el holdout no pasa de aquí

    def score(signal_function) -> list[WindowScore]:
        scores = []
        for window in plan.windows:
            result = evaluate_segment(selection, window.validation_start,
                                      window.validation_end, signal_function, config)
            metrics = compute_metrics(result, risk_free_rate)
            scores.append(WindowScore(window.number, metrics.sharpe, metrics.total_return,
                                      metrics.max_drawdown, metrics.num_trades,
                                      metrics.volatility))
        return scores

    ranking = sorted(
        (CandidateScore(candidate, score(candidate.signals)) for candidate in candidates),
        key=lambda s: (-s.median_sharpe, s.median_drawdown, s.candidate.label),
    )
    benchmark = score(lambda closes: buy_and_hold_signals(len(closes)))
    return SelectionResult(plan, ranking, benchmark)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bottrading.walkforward",
        description="Selección walk-forward sin usar el holdout final (solo simulación).",
    )
    parser.add_argument("--binance", type=Path, nargs="+", required=True, metavar="RUTA",
                        help="klines de Binance: archivos .zip/.csv o carpetas")
    parser.add_argument("--scheme", choices=sorted(SCHEMES), default="daily")
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--commission", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--out", type=Path, default=None,
                        help="directorio de salida (por defecto reports/seleccion_<datos>)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        config = BacktestConfig(initial_capital=args.capital,
                                commission_rate=args.commission,
                                slippage_rate=args.slippage)
        data_paths = expand_paths(args.binance)
        candles = load_binance_klines(data_paths)
        plan = plan_splits([c.timestamp for c in candles], SCHEMES[args.scheme])
        result = run_selection(candles, plan, default_grid(), config)
        out_dir = args.out or Path("reports") / f"seleccion_{data_paths[0].parent.name}"
        paths = write_selection_report(out_dir, data_paths=data_paths, candles=candles,
                                       result=result)
    except (DataValidationError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("Simulación educativa: no son resultados reales. Holdout final sin usar.")
    for path in paths.values():
        print(f"escrito {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
