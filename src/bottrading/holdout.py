"""Evaluación ÚNICA del holdout final (protocolo D023).

Evalúa la combinación congelada (D022) y buy-and-hold en el holdout, con
los escenarios de costes fijados de antemano, y aplica las reglas de
interpretación de D023. No elige nada: solo mide.

La CLI está bloqueada al protocolo: solo la combinación, el esquema y el
capital congelados (revisión de Codex de T018).

Uso (requiere confirmación explícita):
    python -m bottrading.holdout --binance data/BTCUSDT-1d \
        --candidate trend_filter:window=50 --open-holdout
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bottrading.backtest import BacktestResult
from bottrading.binance import expand_paths, load_binance_klines
from bottrading.config import BacktestConfig
from bottrading.data import Candle, DataValidationError
from bottrading.metrics import Metrics, compute_metrics
from bottrading.report import write_holdout_report
from bottrading.splits import SplitPlan, evaluate_segment, plan_splits
from bottrading.strategy import buy_and_hold_signals
from bottrading.walkforward import SCHEMES, Candidate, default_grid


@dataclass(frozen=True)
class Scenario:
    name: str
    commission_rate: float
    slippage_rate: float


# D023: fijados antes de abrir el holdout.
SCENARIOS = (
    Scenario("sin costes", 0.0, 0.0),
    Scenario("bajo", 0.00075, 0.0002),
    Scenario("base", 0.001, 0.0005),
    Scenario("alto", 0.002, 0.001),
)
BASE = "base"

# D022/D023: lo único que la CLI acepta evaluar en el holdout final.
FROZEN_CANDIDATE = Candidate("trend_filter", (("window", 50),))
FROZEN_SCHEME = "daily"
FROZEN_CAPITAL = 10_000.0


@dataclass(frozen=True)
class ScenarioRun:
    scenario: Scenario
    strategy: BacktestResult
    benchmark: BacktestResult
    strategy_metrics: Metrics
    benchmark_metrics: Metrics

    @property
    def excess_return(self) -> float:
        return self.strategy_metrics.total_return - self.benchmark_metrics.total_return


@dataclass(frozen=True)
class Verdict:
    """Reglas de interpretación de D023, aplicadas mecánicamente."""

    earns_more: bool
    better_risk_adjusted: bool | None  # None si algún Sharpe no está disponible
    lower_risk: bool | None
    robust_to_costs: bool


@dataclass(frozen=True)
class HoldoutResult:
    plan: SplitPlan
    candidate: Candidate
    runs: list[ScenarioRun]

    def run(self, name: str) -> ScenarioRun:
        return next(run for run in self.runs if run.scenario.name == name)

    @property
    def verdict(self) -> Verdict:
        base = self.run(BASE)
        s, b = base.strategy_metrics, base.benchmark_metrics
        sharpe = None if s.sharpe is None or b.sharpe is None else s.sharpe > b.sharpe
        lower_risk = (None if s.volatility is None or b.volatility is None
                      else s.max_drawdown < b.max_drawdown and s.volatility < b.volatility)
        signs = {self.run(name).excess_return > 0 for name in ("bajo", BASE, "alto")}
        return Verdict(base.excess_return > 0, sharpe, lower_risk, len(signs) == 1)


def evaluate_holdout(
    candles: Sequence[Candle],
    plan: SplitPlan,
    candidate: Candidate,
    capital: float = 10_000.0,
    scenarios: Sequence[Scenario] = SCENARIOS,
) -> HoldoutResult:
    if len(candles) != plan.holdout_end:
        raise ValueError("las velas no coinciden con el plan de particiones")
    runs = []
    for scenario in scenarios:
        config = BacktestConfig(initial_capital=capital,
                                commission_rate=scenario.commission_rate,
                                slippage_rate=scenario.slippage_rate)
        strategy = evaluate_segment(candles, plan.holdout_start, plan.holdout_end,
                                    candidate.signals, config)
        benchmark = evaluate_segment(candles, plan.holdout_start, plan.holdout_end,
                                     lambda closes: buy_and_hold_signals(len(closes)),
                                     config)
        runs.append(ScenarioRun(scenario, strategy, benchmark,
                                compute_metrics(strategy), compute_metrics(benchmark)))
    return HoldoutResult(plan, candidate, runs)


def parse_candidate(text: str) -> Candidate:
    """'trend_filter:window=50' -> Candidate; debe estar en la rejilla de D021."""
    strategy, _, raw = text.partition(":")
    try:
        params = tuple((name, int(value)) for name, value in
                       (item.split("=") for item in raw.split(",") if item))
    except ValueError as exc:
        raise ValueError(f"combinación mal escrita: {text!r} "
                         "(ej. trend_filter:window=50)") from exc
    candidate = Candidate(strategy, params)
    if candidate not in default_grid():
        raise ValueError(f"{candidate.label} no está en la rejilla registrada (D021)")
    return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bottrading.holdout",
        description="Evaluación única del holdout final (D023). Solo simulación.",
    )
    parser.add_argument("--binance", type=Path, nargs="+", required=True, metavar="RUTA")
    parser.add_argument("--candidate", required=True,
                        help=f"debe ser la combinación congelada en D022 "
                             f"({FROZEN_CANDIDATE.strategy}:window=50)")
    parser.add_argument("--open-holdout", action="store_true",
                        help="confirmación explícita: el holdout solo debe abrirse una vez")
    parser.add_argument("--out", type=Path, default=None,
                        help="directorio de salida (por defecto reports/holdout_<datos>)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if not args.open_holdout:
        print("error: abrir el holdout requiere --open-holdout (D023: una sola vez)",
              file=sys.stderr)
        return 2
    try:
        candidate = parse_candidate(args.candidate)
        if candidate != FROZEN_CANDIDATE:
            raise ValueError(f"D023 solo permite evaluar {FROZEN_CANDIDATE.label} en el "
                             f"holdout, no {candidate.label}")
        data_paths = expand_paths(args.binance)
        candles = load_binance_klines(data_paths)
        plan = plan_splits([c.timestamp for c in candles], SCHEMES[FROZEN_SCHEME])
        result = evaluate_holdout(candles, plan, candidate, FROZEN_CAPITAL)
        out_dir = args.out or Path("reports") / f"holdout_{data_paths[0].parent.name}"
        paths = write_holdout_report(out_dir, data_paths=data_paths, candles=candles,
                                     result=result)
    except (DataValidationError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("Simulación educativa: no son resultados reales.")
    for path in paths.values():
        print(f"escrito {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
