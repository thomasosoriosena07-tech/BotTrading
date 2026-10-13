"""Importación de klines históricos de Binance (ver DECISIONS.md D018).

Lee los archivos públicos de data.binance.vision descargados a mano
(ZIP con un CSV dentro, o el CSV ya extraído). No accede a la red.

Columnas (sin cabecera): 0 open_time, 1 open, 2 high, 3 low, 4 close,
5 volume, 6 close_time, 7-11 se ignoran (quote volume, trades, ...).
"""

import csv
import hashlib
import io
import logging
import zipfile
import zlib
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bottrading.data import Candle, DataValidationError, parse_float, validate_candle

logger = logging.getLogger(__name__)

KLINE_COLUMNS = 12
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# Spot usa µs desde 2025 (16 dígitos); antes, ms (13 dígitos).
MICROSECONDS_FROM = 10**14  # 1e14 ms sería el año 5138
MILLISECONDS_FROM = 10**11  # 1e11 ms = 1973-03-03


def parse_kline_time(raw: str) -> datetime:
    """Convierte open_time/close_time (ms o µs, por magnitud) a UTC."""
    text = raw.strip()
    if not text.isdigit():
        raise DataValidationError(f"tiempo no entero: {raw!r}")
    value = int(text)
    try:
        if value >= MICROSECONDS_FROM:
            return EPOCH + timedelta(microseconds=value)
        if value >= MILLISECONDS_FROM:
            return EPOCH + timedelta(milliseconds=value)
    except OverflowError as exc:
        raise DataValidationError(f"tiempo fuera de rango: {raw!r}") from exc
    raise DataValidationError(f"tiempo fuera de rango (ni ms ni µs): {raw!r}")


def expand_paths(paths: Sequence[Path]) -> list[Path]:
    """Directorios -> sus .zip y .csv ordenados por nombre; archivos tal cual."""
    expanded: list[Path] = []
    for path in map(Path, paths):
        if path.is_dir():
            found = sorted(
                p for p in path.iterdir() if p.suffix.lower() in (".zip", ".csv")
            )
            if not found:
                raise DataValidationError(f"{path}: no contiene archivos .zip ni .csv")
            expanded.extend(found)
        elif path.is_file():
            expanded.append(path)
        else:
            raise DataValidationError(f"no existe: {path}")
    return expanded


def load_binance_klines(paths: Sequence[Path]) -> list[Candle]:
    """Carga y valida klines de uno o varios archivos; velas ordenadas en UTC."""
    records: list[tuple[str, Candle]] = []
    for path in expand_paths(paths):
        if not verify_checksum(path) and path.suffix.lower() == ".zip":
            logger.warning("%s: sin .CHECKSUM; integridad no verificada", path.name)
        for line, row in _read_rows(path):
            where = f"{path.name}:{line}"
            try:
                records.append((where, _parse_row(row)))
            except DataValidationError as exc:
                raise DataValidationError(f"{where}: {exc}") from exc

    if not records:
        raise DataValidationError("los archivos no contienen velas")
    _check_duplicates(records)
    candles = [candle for _, candle in records]
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    if ordered != candles:
        logger.warning("velas desordenadas entre archivos; se ordenan por open_time")
    logger.info("%d velas de Binance cargadas", len(ordered))
    return ordered


def verify_checksum(path: Path) -> bool:
    """Compara con `<archivo>.CHECKSUM` si existe. Devuelve si se verificó."""
    checksum_file = path.with_name(path.name + ".CHECKSUM")
    if not checksum_file.exists():
        return False
    expected = checksum_file.read_text(encoding="utf-8").split()[0].lower()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise DataValidationError(
            f"{path.name}: SHA-256 no coincide con {checksum_file.name}"
        )
    return True


def _read_rows(path: Path) -> Iterator[tuple[int, list[str]]]:
    """(línea, fila). Se toleran una cabecera y líneas vacías al final."""
    with _open_text(path) as handle:
        reader = csv.reader(handle)
        blank_line = None
        for row in reader:
            line = reader.line_num
            if not row:
                blank_line = blank_line or line
                continue
            if blank_line is not None:
                raise DataValidationError(
                    f"{path.name}:{blank_line}: línea vacía entre datos"
                )
            if line == 1 and row[0].strip().lower() == "open_time":
                continue
            yield line, row


def _open_text(path: Path) -> io.TextIOBase:
    if path.suffix.lower() != ".zip":
        return path.open(newline="", encoding="utf-8-sig")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise DataValidationError(f"{path.name}: ZIP dañado o no válido") from exc
    with archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise DataValidationError(
                f"{path.name}: se esperaba un CSV dentro del ZIP, hay {len(members)}"
            )
        try:
            data = archive.read(members[0])
        except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
            # p. ej. CRC-32 incorrecto: el ZIP abre pero su contenido está dañado.
            raise DataValidationError(f"{path.name}: contenido del ZIP dañado ({exc})") from exc
    return io.TextIOWrapper(io.BytesIO(data), encoding="utf-8-sig", newline="")


def _parse_row(row: list[str]) -> Candle:
    if len(row) != KLINE_COLUMNS:
        raise DataValidationError(f"{len(row)} columnas; se esperaban {KLINE_COLUMNS}")
    open_time = parse_kline_time(row[0])
    close_time = parse_kline_time(row[6])
    if close_time <= open_time:
        raise DataValidationError("close_time no es posterior a open_time")
    candle = Candle(
        timestamp=open_time,
        open=parse_float(row[1], "open"),
        high=parse_float(row[2], "high"),
        low=parse_float(row[3], "low"),
        close=parse_float(row[4], "close"),
        volume=parse_float(row[5], "volume"),
    )
    validate_candle(candle)
    return candle


def _check_duplicates(records: list[tuple[str, Candle]]) -> None:
    first_seen: dict[datetime, str] = {}
    for where, candle in records:
        if candle.timestamp in first_seen:
            raise DataValidationError(
                f"{where}: open_time duplicado {candle.timestamp.isoformat()} "
                f"(ya en {first_seen[candle.timestamp]})"
            )
        first_seen[candle.timestamp] = where
