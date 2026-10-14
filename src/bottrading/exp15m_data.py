"""EXP-15M-001: datos de velas de 15 minutos (EXPERIMENT_15M.md, Anexo A.4; D031).

Validador estricto de la serie 15m y manifiesto SHA-256 de los ZIP. Sin red:
lee los archivos que dejó el descargador (download.py). Reutiliza el lector
de klines del baseline (binance.py) sin modificarlo.

Reglas (A.4):
- Solo ZIP mensuales `<SÍMBOLO>-15m-AAAA-MM.zip` con su `.CHECKSUM` verificado.
- Solo meses cerrados: un archivo del mes en curso (o futuro) se rechaza.
- Cada vela pertenece al mes de su archivo, su open_time es múltiplo de 15 min
  en UTC y su close_time es open_time + 15 min menos una unidad (1 ms o 1 µs).
- Orden estrictamente creciente en el orden de los archivos: nada se reordena.
- Los huecos (velas que faltan) NO son error: se cuentan, se listan y no se
  rellenan. Los días UTC sin ninguna vela también se listan (A.8).
- Enmienda 1 de A.4 (2026-10-14, antes de ver el holdout; motivo: paradas del
  exchange en los datos reales de 2020-2023):
  - Vela SIN NEGOCIACIÓN (0 operaciones y volumen 0): se descarta y queda como
    hueco; una orden en una parada espera a que se vuelva a negociar. Tener 0
    operaciones con volumen > 0, o al revés, es error.
  - Vela TRUNCADA (con operaciones y close_time anterior al fin nominal pero
    posterior a su open_time): se conserva y se marca; las órdenes ejecutadas
    en ella pasan por la prueba de exclusión de A.9, como las "tras hueco".
Cualquier otra anomalía es DataValidationError (defecto crítico 2 de A.9).
"""

import argparse
import csv
import hashlib
import io
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Lector del baseline reutilizado tal cual (no se modifica binance.py).
from bottrading.binance import _parse_row, _read_rows, parse_kline_time, verify_checksum
from bottrading.data import Candle, DataValidationError

INTERVAL = timedelta(minutes=15)
CLOSE_OFFSETS = (INTERVAL - timedelta(milliseconds=1), INTERVAL - timedelta(microseconds=1))
VOLUME_COLUMN = 5
TRADES_COLUMN = 8  # número de operaciones del kline
FILE_PATTERN = re.compile(
    r"(?P<symbol>[A-Z0-9]{2,20})-15m-(?P<year>[0-9]{4})-(?P<month>[0-9]{2})\.zip")
MANIFEST_COLUMNS = ("file", "bytes", "sha256")


@dataclass(frozen=True)
class Gap:
    """Hueco: tras la vela `after` faltan `missing` velas de 15 min."""

    after: datetime
    missing: int


@dataclass(frozen=True)
class GridReport:
    candles: int
    first: datetime
    last: datetime
    gaps: tuple[Gap, ...]
    empty_days: tuple[date, ...]  # días UTC entre first y last sin ninguna vela
    truncated: tuple[datetime, ...] = ()  # open_time de velas truncadas (enmienda 1)
    no_trade: tuple[datetime, ...] = ()  # open_time de velas sin negociación descartadas

    @property
    def missing(self) -> int:
        return sum(gap.missing for gap in self.gaps)


def zip_files(data_dir: Path) -> list[Path]:
    """Los ZIP de la carpeta, ordenados por nombre (= orden cronológico)."""
    if not data_dir.is_dir():
        raise DataValidationError(f"no existe la carpeta de datos: {data_dir}")
    files = sorted(p for p in data_dir.iterdir() if p.suffix.lower() == ".zip")
    if not files:
        raise DataValidationError(f"{data_dir}: no contiene archivos .zip")
    return files


def load_15m(files: Sequence[Path], now: datetime | None = None) -> tuple[list[Candle], GridReport]:
    """Carga y valida los ZIP 15m (A.4). Devuelve las velas y el informe de rejilla."""
    now = now or datetime.now(timezone.utc)
    candles: list[Candle] = []
    truncated: list[datetime] = []
    no_trade: list[datetime] = []
    for path in files:
        year, month = _file_month(path, now)
        if not verify_checksum(path):
            raise DataValidationError(f"{path.name}: falta su .CHECKSUM")
        for line, row in _read_rows(path):
            where = f"{path.name}:{line}"
            try:
                if _without_trades(row):
                    moment = _check_open_time(parse_kline_time(row[0]), year, month)
                    _check_order(moment, candles, no_trade)
                    no_trade.append(moment)
                    continue
                candle = _parse_row(row)
                if _check_candle(candle, parse_kline_time(row[6]), year, month):
                    truncated.append(candle.timestamp)
                _check_order(candle.timestamp, candles, no_trade)
            except DataValidationError as exc:
                raise DataValidationError(f"{where}: {exc}") from exc
            candles.append(candle)
    if not candles:
        raise DataValidationError("los archivos no contienen velas")
    report = grid_report(candles)
    return candles, GridReport(report.candles, report.first, report.last, report.gaps,
                               report.empty_days, tuple(truncated), tuple(no_trade))


def grid_report(candles: Sequence[Candle]) -> GridReport:
    """Huecos y días vacíos de una serie ya validada (alineada y creciente)."""
    gaps = []
    for previous, current in zip(candles, candles[1:]):
        step = current.timestamp - previous.timestamp
        if step != INTERVAL:
            gaps.append(Gap(previous.timestamp, step // INTERVAL - 1))
    present = {candle.timestamp.date() for candle in candles}
    first, last = candles[0].timestamp, candles[-1].timestamp
    days = (last.date() - first.date()).days
    empty = tuple(day for day in (first.date() + timedelta(days=i) for i in range(days + 1))
                  if day not in present)
    return GridReport(len(candles), first, last, tuple(gaps), empty)


def build_manifest(files: Sequence[Path]) -> list[tuple[str, int, str]]:
    """(nombre, bytes, SHA-256) de cada ZIP, en orden de nombre."""
    return [(p.name, p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(files, key=lambda p: p.name)]


def render_manifest(rows: Sequence[tuple[str, int, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(MANIFEST_COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue()


def read_manifest(path: Path) -> list[tuple[str, int, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        if next(reader, None) != list(MANIFEST_COLUMNS):
            raise DataValidationError(f"{path.name}: cabecera de manifiesto no válida")
        rows = []
        for row in reader:
            if len(row) != len(MANIFEST_COLUMNS) or not row[1].isdigit():
                raise DataValidationError(f"{path.name}:{reader.line_num}: fila no válida")
            rows.append((row[0], int(row[1]), row[2]))
        return rows


def check_manifest(manifest: Path, files: Sequence[Path]) -> list[str]:
    """Diferencias entre el manifiesto y los ZIP presentes (vacía = coinciden)."""
    expected = {name: (size, digest) for name, size, digest in read_manifest(manifest)}
    actual = {name: (size, digest) for name, size, digest in build_manifest(files)}
    problems = [f"falta {name}" for name in sorted(expected.keys() - actual.keys())]
    problems += [f"no está en el manifiesto: {name}"
                 for name in sorted(actual.keys() - expected.keys())]
    problems += [f"tamaño o SHA-256 distinto: {name}"
                 for name in sorted(expected.keys() & actual.keys())
                 if expected[name] != actual[name]]
    return problems


def _file_month(path: Path, now: datetime) -> tuple[int, int]:
    match = FILE_PATTERN.fullmatch(path.name)
    if not match:
        raise DataValidationError(f"{path.name}: no es un ZIP mensual <SÍMBOLO>-15m-AAAA-MM.zip")
    year, month = int(match["year"]), int(match["month"])
    if not 1 <= month <= 12:
        raise DataValidationError(f"{path.name}: mes no válido")
    if (year, month) >= (now.year, now.month):
        raise DataValidationError(f"{path.name}: mes en curso o futuro; solo meses cerrados")
    return year, month


def _without_trades(row: list[str]) -> bool:
    """True si la vela no tuvo negociación (0 operaciones y volumen 0)."""
    if len(row) <= TRADES_COLUMN:
        return False  # _parse_row rechazará el número de columnas
    trades, volume = row[TRADES_COLUMN].strip(), row[VOLUME_COLUMN].strip()
    if not trades.isdigit():
        raise DataValidationError(f"número de operaciones no válido: {trades!r}")
    try:
        no_volume = float(volume) == 0
    except ValueError as exc:
        raise DataValidationError(f"volumen no numérico: {volume!r}") from exc
    no_trades = int(trades) == 0
    if no_trades != no_volume:
        raise DataValidationError(f"operaciones ({trades}) y volumen ({volume}) incoherentes")
    return no_trades


def _check_open_time(moment: datetime, year: int, month: int) -> datetime:
    if (moment.year, moment.month) != (year, month):
        raise DataValidationError(f"vela de {moment:%Y-%m} en el archivo de {year:04d}-{month:02d}")
    if moment.microsecond or moment.second or moment.minute % 15:
        raise DataValidationError(f"open_time {moment.isoformat()} fuera de la rejilla de 15 min")
    return moment


def _check_candle(candle: Candle, close_time: datetime, year: int, month: int) -> bool:
    """Valida la vela; devuelve True si está truncada (enmienda 1)."""
    moment = _check_open_time(candle.timestamp, year, month)
    duration = close_time - moment
    if duration in CLOSE_OFFSETS:
        return False
    if timedelta(0) < duration < CLOSE_OFFSETS[0]:
        return True
    raise DataValidationError(
        f"close_time {close_time.isoformat()} no corresponde a la vela {moment.isoformat()}")


def _check_order(moment: datetime, candles: Sequence[Candle], no_trade: Sequence[datetime]) -> None:
    """Estrictamente creciente respecto a todo lo leído (incluidas las descartadas)."""
    seen = ([candles[-1].timestamp] if candles else []) + ([no_trade[-1]] if no_trade else [])
    previous = max(seen, default=None)
    if previous is not None and moment <= previous:
        raise DataValidationError(
            f"open_time {moment.isoformat()} no es posterior a {previous.isoformat()} "
            "(duplicado o desorden)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bottrading.exp15m_data",
        description="EXP-15M-001: valida las velas 15m y su manifiesto SHA-256 (sin red).")
    parser.add_argument("--data", type=Path, default=Path("data/BTCUSDT-15m"))
    parser.add_argument("--manifest", type=Path,
                        default=Path("reports/exp15m/data_manifest.csv"))
    parser.add_argument("--write-manifest", action="store_true",
                        help="crea el manifiesto (nunca sobrescribe uno existente)")
    return parser


def main(argv: Sequence[str] | None = None, now: datetime | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        files = zip_files(args.data)
        _, report = load_15m(files, now)
        if args.write_manifest:
            if args.manifest.exists():
                raise DataValidationError(f"{args.manifest} ya existe; no se sobrescribe")
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            with args.manifest.open("x", encoding="utf-8", newline="") as handle:
                handle.write(render_manifest(build_manifest(files)))
            print(f"Manifiesto creado: {args.manifest} ({len(files)} archivos)")
        else:
            problems = check_manifest(args.manifest, files)
            if problems:
                raise DataValidationError("el manifiesto no coincide: " + "; ".join(problems))
            print(f"Manifiesto OK: {args.manifest} ({len(files)} archivos)")
    except (DataValidationError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Velas: {report.candles} ({report.first.isoformat()} a {report.last.isoformat()})")
    print(f"Huecos: {len(report.gaps)} ({report.missing} velas que faltan)")
    for gap in report.gaps:
        print(f"  tras {gap.after.isoformat()}: faltan {gap.missing}")
    print(f"Velas sin negociación descartadas (cuentan como hueco): {len(report.no_trade)}")
    print(f"Velas truncadas (marcadas): {len(report.truncated)}"
          + (" (" + ", ".join(t.isoformat() for t in report.truncated) + ")"
             if report.truncated else ""))
    print(f"Días UTC sin ninguna vela: {len(report.empty_days)}"
          + (" (" + ", ".join(d.isoformat() for d in report.empty_days) + ")"
             if report.empty_days else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
