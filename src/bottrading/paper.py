"""Paper trading de la estrategia congelada desde 2026-10-01 (protocolo D027).

Simulación sin dinero: no accede a la red ni envía órdenes. Lee los
klines mensuales (historial hasta 2026-09-30, solo calentamiento) y los
diarios descargados con `python -m bottrading.download --daily`, y
recalcula todo de forma determinista en cada ejecución.

El diario de operaciones (paper/ledger.csv, versionado en Git) solo
admite añadir filas: si una ejecución no reproduce exactamente las filas
ya registradas, se detiene con error. Un ancla (paper/ledger.state:
último día, filas y SHA-256 del diario) detecta además truncamientos,
ediciones y filas nuevas con fecha ya simulada (revisión de Codex).

Uso:
    python -m bottrading.paper
"""

import argparse
import csv
import hashlib
import io
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


@dataclass(frozen=True)
class Anchor:
    last_day: date
    rows: int
    sha256: str


def anchor_path(ledger: Path) -> Path:
    return ledger.with_name("ledger.state")


def read_anchor(path: Path) -> Anchor:
    try:
        fields = dict(line.split("=", 1) for line in
                      path.read_text(encoding="utf-8").splitlines() if line)
        return Anchor(date.fromisoformat(fields["last_day"]), int(fields["rows"]),
                      fields["sha256"])
    except (KeyError, ValueError) as exc:
        raise LedgerIntegrityError(f"{path}: ancla con formato inesperado") from exc


def update_ledger(path: Path, rows: list[list[str]], last_day: date,
                  init_anchor: bool = False) -> int:
    """Escribe el diario y su ancla si la historia se conserva; devuelve filas nuevas.

    Errores (LedgerIntegrityError), sin escribir nada:
    - el diario no coincide con su ancla (truncado, editado o borrado);
    - la simulación no reproduce las filas ya registradas;
    - hay filas nuevas con fecha de ejecución ya simulada (<= último día
      anclado) o los datos retroceden;
    - existe diario sin ancla (salvo `init_anchor`, que exige reproducir
      el diario exactamente y crea el ancla).
    """
    anchor_file = anchor_path(path)
    existing_bytes = path.read_bytes() if path.exists() else None
    anchor = read_anchor(anchor_file) if anchor_file.exists() else None

    if init_anchor and (existing_bytes is None or anchor is not None):
        raise LedgerIntegrityError(
            "--init-anchor solo sirve para un diario existente sin ancla")
    if anchor is None and existing_bytes is not None and not init_anchor:
        raise LedgerIntegrityError(f"{path}: existe el diario pero falta su ancla "
                                   f"{anchor_file.name}")
    if anchor is not None and existing_bytes is None:
        raise LedgerIntegrityError(f"{path}: falta el diario pero existe su ancla")
    existing = _parse_ledger(path, existing_bytes) if existing_bytes is not None else []
    if anchor is not None:
        digest = hashlib.sha256(existing_bytes).hexdigest()
        if digest != anchor.sha256 or len(existing) != anchor.rows:
            raise LedgerIntegrityError(
                f"{path}: el diario no coincide con su ancla ({len(existing)} filas, "
                f"ancla {anchor.rows}); ¿truncado o editado? Recupéralo desde Git.")
        if last_day < anchor.last_day:
            raise LedgerIntegrityError(f"los datos llegan a {last_day}, antes del último "
                                       f"día anclado {anchor.last_day}")
    if rows[:len(existing)] != existing:
        raise LedgerIntegrityError(
            f"{path}: la simulación ya no reproduce las {len(existing)} operaciones "
            "registradas (¿cambiaron los datos o el código?). No se sobrescribe.")
    new_rows = rows[len(existing):]
    if anchor is not None:
        stale = [row for row in new_rows
                 if date.fromisoformat(row[3][:10]) <= anchor.last_day]
        if stale:
            raise LedgerIntegrityError(
                f"{len(stale)} operaciones nuevas con fecha ya simulada "
                f"(<= {anchor.last_day}): ¿se corrigieron datos históricos?")
    if init_anchor and new_rows:
        raise LedgerIntegrityError("--init-anchor exige reproducir el diario sin filas nuevas")

    content = _render_ledger(rows)
    _write_atomic(path, content)
    _write_atomic(anchor_file, (f"last_day={last_day.isoformat()}\nrows={len(rows)}\n"
                                f"sha256={hashlib.sha256(content).hexdigest()}\n").encode())
    return len(new_rows)


def _parse_ledger(path: Path, content: bytes) -> list[list[str]]:
    reader = csv.reader(content.decode("utf-8").splitlines())
    if next(reader, None) != LEDGER_COLUMNS:
        raise LedgerIntegrityError(f"{path}: cabecera inesperada")
    return list(reader)


def _render_ledger(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(LEDGER_COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(content)
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bottrading.paper",
        description="Paper trading de la estrategia congelada (D027). Sin dinero ni red.",
    )
    parser.add_argument("--data", type=Path, default=Path("data"),
                        help="carpeta con <SYM>-1d y <SYM>-1d-daily")
    parser.add_argument("--out", type=Path, default=Path("paper"),
                        help="carpeta del diario y del informe (versionada)")
    parser.add_argument("--init-anchor", action="store_true",
                        help="crea el ancla de un diario existente (debe reproducirse)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        state = run_paper(args.data)
        added = update_ledger(args.out / "ledger.csv", ledger_rows(state),
                              state.last_day, init_anchor=args.init_anchor)
        paths = write_paper_report(args.out, state=state)
    except (DataValidationError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("Paper trading simulado: sin dinero ni órdenes reales.")
    print(f"Datos hasta {state.last_day}; operaciones nuevas en el diario: {added}")
    for path in [args.out / "ledger.csv", args.out / "ledger.state", *paths.values()]:
        print(f"escrito {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
