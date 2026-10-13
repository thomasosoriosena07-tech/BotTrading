"""Carga y validación de datos OHLCV desde CSV.

Reglas (ver DECISIONS.md D011):
- Columnas obligatorias: timestamp, open, high, low, close, volume.
- timestamp: ISO 8601 con zona horaria explícita, o epoch numérico
  (UTC por definición). Las fechas sin zona horaria se rechazan.
- Todas las fechas se normalizan a UTC.
- Filas inválidas o duplicadas provocan DataValidationError con número
  de línea; nunca se corrigen ni se descartan en silencio.
- Filas desordenadas se ordenan cronológicamente y se registra un aviso.
"""

import csv
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
EPOCH_DIVISORS = {"s": 1, "ms": 1_000}
# 1e11 ms = 1973-03-03 y 1e11 s = año 5138: separa ambas unidades sin
# ambigüedad para datos realistas y detecta una unidad equivocada.
EPOCH_UNIT_BOUNDARY = 100_000_000_000


class DataValidationError(ValueError):
    """El CSV no cumple el formato o contiene valores inválidos."""


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def parse_timestamp(raw: str, epoch_unit: str = "ms") -> datetime:
    """Convierte un timestamp a datetime en UTC."""
    if epoch_unit not in EPOCH_DIVISORS:
        raise ValueError(f"epoch_unit debe ser 's' o 'ms', no {epoch_unit!r}")
    text = raw.strip()
    if not text:
        raise DataValidationError("timestamp vacío")

    if _is_number(text):
        return _parse_epoch(text, epoch_unit)

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DataValidationError(f"timestamp no reconocido: {text!r}") from exc
    if parsed.tzinfo is None:
        raise DataValidationError(f"timestamp sin zona horaria: {text!r}")
    return parsed.astimezone(timezone.utc)


def load_ohlcv_csv(path: Path, epoch_unit: str = "ms") -> list[Candle]:
    """Lee un CSV OHLCV, lo valida y devuelve las velas ordenadas en UTC."""
    path = Path(path)
    # utf-8-sig acepta archivos con BOM (p. ej. exportados desde Excel).
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        columns = _column_indexes(header)
        records = _read_records(reader, columns, len(header), epoch_unit)

    if not records:
        raise DataValidationError(f"{path.name}: no contiene filas de datos")

    _check_duplicates(records)
    candles = [candle for _, candle in records]
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    if ordered != candles:
        logger.warning("%s: filas desordenadas; se ordenan por timestamp", path.name)
    logger.info("%s: %d velas cargadas", path.name, len(ordered))
    return ordered


def _read_records(
    reader, columns: dict[str, int], width: int, epoch_unit: str
) -> list[tuple[int, Candle]]:
    """Devuelve (línea, vela). Se toleran líneas vacías solo al final."""
    records = []
    blank_line = None
    for row in reader:
        line = reader.line_num
        if not row:
            blank_line = blank_line or line
            continue
        if blank_line is not None:
            raise DataValidationError(f"línea {blank_line}: línea vacía entre datos")
        try:
            records.append((line, _parse_row(row, columns, width, epoch_unit)))
        except DataValidationError as exc:
            raise DataValidationError(f"línea {line}: {exc}") from exc
    return records


def _column_indexes(header: list[str] | None) -> dict[str, int]:
    """Mapea nombre normalizado -> posición en la cabecera."""
    if not header:
        raise DataValidationError("el CSV no tiene cabecera")
    names = [name.strip().lower() for name in header]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise DataValidationError(f"columnas repetidas: {', '.join(repeated)}")
    missing = [name for name in REQUIRED_COLUMNS if name not in names]
    if missing:
        raise DataValidationError(f"faltan columnas: {', '.join(missing)}")
    extra = [name for name in names if name not in REQUIRED_COLUMNS]
    if extra:
        logger.info("columnas ignoradas (no OHLCV): %s", ", ".join(extra))
    return {name: names.index(name) for name in REQUIRED_COLUMNS}


def _parse_row(
    row: list[str], columns: dict[str, int], width: int, epoch_unit: str
) -> Candle:
    if len(row) != width:
        raise DataValidationError(
            f"{len(row)} campos; la cabecera tiene {width}"
        )
    values = {name: _cell(row[index], name) for name, index in columns.items()}
    candle = Candle(
        timestamp=parse_timestamp(values["timestamp"], epoch_unit),
        open=_to_float(values["open"], "open"),
        high=_to_float(values["high"], "high"),
        low=_to_float(values["low"], "low"),
        close=_to_float(values["close"], "close"),
        volume=_to_float(values["volume"], "volume"),
    )
    _check_values(candle)
    return candle


def _cell(value: str, column: str) -> str:
    if not value.strip():
        raise DataValidationError(f"valor vacío en '{column}'")
    return value


def _to_float(raw: str, name: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise DataValidationError(f"'{name}' no es numérico: {raw!r}") from exc
    if not math.isfinite(value):
        raise DataValidationError(f"'{name}' no es finito: {raw!r}")
    return value


def _parse_epoch(text: str, epoch_unit: str) -> datetime:
    value = float(text)
    if not math.isfinite(value):
        raise DataValidationError(f"epoch no finito: {text!r}")
    if epoch_unit == "ms" and value < EPOCH_UNIT_BOUNDARY:
        raise DataValidationError(
            f"epoch {text!r} parece estar en segundos; usa epoch_unit='s'"
        )
    if epoch_unit == "s" and value >= EPOCH_UNIT_BOUNDARY:
        raise DataValidationError(
            f"epoch {text!r} parece estar en milisegundos; usa epoch_unit='ms'"
        )
    try:
        return datetime.fromtimestamp(value / EPOCH_DIVISORS[epoch_unit], tz=timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise DataValidationError(f"epoch fuera de rango: {text!r}") from exc


def _check_values(candle: Candle) -> None:
    prices = (candle.open, candle.high, candle.low, candle.close)
    if min(prices) <= 0:
        raise DataValidationError("los precios deben ser positivos")
    if candle.volume < 0:
        raise DataValidationError("el volumen no puede ser negativo")
    if candle.high < max(candle.open, candle.close, candle.low):
        raise DataValidationError("high es menor que open, close o low")
    if candle.low > min(candle.open, candle.close):
        raise DataValidationError("low es mayor que open o close")


def _check_duplicates(records: list[tuple[int, Candle]]) -> None:
    first_seen: dict[datetime, int] = {}
    for line, candle in records:
        if candle.timestamp in first_seen:
            raise DataValidationError(
                f"línea {line}: timestamp duplicado "
                f"{candle.timestamp.isoformat()} (ya en línea {first_seen[candle.timestamp]})"
            )
        first_seen[candle.timestamp] = line


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
