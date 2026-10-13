"""Paper trading de la estrategia congelada desde 2026-10-01 (protocolo D027).

Simulación sin dinero: no accede a la red ni envía órdenes. Lee los
klines mensuales (historial hasta 2026-09-30, solo calentamiento) y los
diarios descargados con `python -m bottrading.download --daily`, y
recalcula todo de forma determinista en cada ejecución.

El diario de operaciones (paper/ledger.csv, versionado en Git) solo
admite añadir filas: si una ejecución no reproduce exactamente las filas
ya registradas, se detiene con error.

Uso:
    python -m bottrading.paper
"""

import argparse
import csv
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from bottrading.backtest import BacktestResult
from bottrading.binance import expand_paths, load_binance_klines
from bottrading.crossasset import CONFIG, FROZEN_CANDIDATE
from bottrading.data import Candle, DataValidationError
from bottrading.metrics import Metrics, compute_metrics
from bottrading.report import write_paper_report
from bottrading.splits import evaluate_segment
from bottrading.strategy import buy_and_hold_signals

# D027: fijado antes de empezar.
FORWARD_START = date(2026, 10, 1)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
CHECKPOINTS = (("6 meses (preliminar)", date(2027, 3, 31)),
               ("12 meses (principal)", date(2027, 9, 30)))
LEDGER_COLUMNS = ["symbol", "side", "signal_time", "execution_time", "reference_price",
                  "price", "quantity", "fee", "slippage_cost", "cash_after"]


class LedgerIntegrityError(ValueError):
    """Una ejecución no reproduce las filas ya registradas en el diario."""


@dataclass(frozen=True)
class PaperAsset:
    symbol: str
    strategy: BacktestResult
    benchmark: BacktestResult

    @property
    def strategy_metrics(self) -> Metrics:
        return compute_metrics(self.strategy)

    @property
    def benchmark_metrics(self) -> Metrics:
        return compute_metrics(self.benchmark)


@dataclass(frozen=True)
class Checkpoint:
    label: str
    day: date
    assets: list[PaperAsset]  # simulados solo hasta `day`


@dataclass(frozen=True)
class PaperState:
    last_day: date
    assets: list[PaperAsset]
    checkpoints: list[Checkpoint]  # solo los ya alcanzados
    pending: list[tuple[str, date]]  # puntos de control aún no alcanzados
    forward_start: date = FORWARD_START


def load_forward_candles(monthly_dir: Path, daily_dir: Path) -> tuple[list[Candle], int]:
    """Historial (< FORWARD_START) + días desde FORWARD_START, sin huecos."""
    history = [c for c in load_binance_klines(expand_paths([monthly_dir]))
               if c.timestamp.date() < FORWARD_START]
    forward = load_binance_klines(expand_paths([daily_dir]))
    if not history or history[-1].timestamp.date() != FORWARD_START - timedelta(days=1):
        raise DataValidationError(f"{monthly_dir}: el historial debe llegar a "
                                  f"{FORWARD_START - timedelta(days=1)}")
    early = [c for c in forward if c.timestamp.date() < FORWARD_START]
    if early:
        raise DataValidationError(f"{daily_dir}: hay días anteriores a {FORWARD_START}")
    candles = history + forward
    for previous, current in zip(candles[len(history) - 1:], candles[len(history):]):
        if current.timestamp - previous.timestamp != timedelta(days=1):
            missing = previous.timestamp.date() + timedelta(days=1)
            raise DataValidationError(f"{daily_dir}: falta el día {missing}")
    if len(candles) == len(history):
        raise DataValidationError(f"{daily_dir}: no hay días desde {FORWARD_START}")
    return candles, len(history)


def simulate(symbol: str, candles: Sequence[Candle], start: int,
             end: int | None = None) -> PaperAsset:
    end = len(candles) if end is None else end
    strategy = evaluate_segment(candles, start, end, FROZEN_CANDIDATE.signals, CONFIG)
    benchmark = evaluate_segment(candles, start, end,
                                 lambda closes: buy_and_hold_signals(len(closes)), CONFIG)
    return PaperAsset(symbol, strategy, benchmark)


def run_paper(data_dir: Path, symbols: Sequence[str] = SYMBOLS) -> PaperState:
    loaded = {}
    for symbol in symbols:
        loaded[symbol] = load_forward_candles(data_dir / f"{symbol}-1d",
                                              data_dir / f"{symbol}-1d-daily")
    last_days = {s: candles[-1].timestamp.date() for s, (candles, _) in loaded.items()}
    if len(set(last_days.values())) != 1:
        raise DataValidationError(f"los activos no llegan al mismo día: {last_days}")
    last_day = next(iter(last_days.values()))

    assets = [simulate(s, candles, start) for s, (candles, start) in loaded.items()]
    reached, pending = [], []
    for label, day in CHECKPOINTS:
        if last_day < day:
            pending.append((label, day))
        else:
            at_day = []
            for s, (candles, start) in loaded.items():
                end = next(i for i, c in enumerate(candles) if c.timestamp.date() == day) + 1
                at_day.append(simulate(s, candles, start, end))
            reached.append(Checkpoint(label, day, at_day))
    return PaperState(last_day, assets, reached, pending)


def ledger_rows(state: PaperState) -> list[list[str]]:
    """Operaciones de la estrategia ordenadas por ejecución y símbolo."""
    rows = []
    for asset in state.assets:
        for t in asset.strategy.trades:
            rows.append([asset.symbol, t.side.value, t.signal_time.isoformat(),
                         t.execution_time.isoformat(), repr(t.reference_price),
                         repr(t.price), repr(t.quantity), repr(t.fee),
                         repr(t.slippage_cost), repr(t.cash_after)])
    return sorted(rows, key=lambda row: (row[3], row[0]))


def update_ledger(path: Path, rows: list[list[str]]) -> int:
    """Escribe el diario si conserva las filas previas; devuelve filas nuevas."""
    existing: list[list[str]] = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header != LEDGER_COLUMNS:
                raise LedgerIntegrityError(f"{path}: cabecera inesperada")
            existing = list(reader)
    if rows[:len(existing)] != existing:
        raise LedgerIntegrityError(
            f"{path}: la simulación ya no reproduce las {len(existing)} operaciones "
            "registradas (¿cambiaron los datos o el código?). No se sobrescribe.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(LEDGER_COLUMNS)
        writer.writerows(rows)
    temporary.replace(path)
    return len(rows) - len(existing)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bottrading.paper",
        description="Paper trading de la estrategia congelada (D027). Sin dinero ni red.",
    )
    parser.add_argument("--data", type=Path, default=Path("data"),
                        help="carpeta con <SYM>-1d y <SYM>-1d-daily")
    parser.add_argument("--out", type=Path, default=Path("paper"),
                        help="carpeta del diario y del informe (versionada)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        state = run_paper(args.data)
        added = update_ledger(args.out / "ledger.csv", ledger_rows(state))
        paths = write_paper_report(args.out, state=state)
    except (DataValidationError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("Paper trading simulado: sin dinero ni órdenes reales.")
    print(f"Datos hasta {state.last_day}; operaciones nuevas en el diario: {added}")
    for path in [args.out / "ledger.csv", *paths.values()]:
        print(f"escrito {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
