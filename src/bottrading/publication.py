"""Validación de lo que la automatización publica en GitHub (D030 punto 7, F2b-3).

La tarea diaria (D028) solo puede publicar una lista CERRADA de archivos de
paper/. Antes del push, scripts/paper_daily.ps1 extrae esos archivos del
commit final (SHA fijado) con `git archive` a un zip y este módulo valida su
contenido con esquemas cerrados:

- ledger.csv: columnas fijas; símbolo de la lista; lado buy/sell; fechas ISO;
  números finitos.
- ledger.state: last_day, rows y sha256 coherentes con ledger.csv.
- equity.csv: columnas fijas; fecha, símbolo y números finitos.
- report.md y dashboard.html: UTF-8, sin <script> ni URLs externas.
- Todos: tamaño acotado y sin patrones de credenciales (defensa adicional,
  no criterio principal).

Sin red. Uso:
    python -m bottrading.publication <archivo.zip>
"""

import argparse
import csv
import hashlib
import io
import math
import re
import sys
import zipfile
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from bottrading.paper import LEDGER_COLUMNS, SYMBOLS

PUBLISHABLE = ("paper/ledger.csv", "paper/ledger.state", "paper/report.md",
               "paper/equity.csv", "paper/dashboard.html")
EQUITY_COLUMNS = ["date", "symbol", "strategy_equity", "buy_and_hold_equity"]
MAX_BYTES = 5_000_000
# Defensa adicional: nombres de credenciales y tokens de 64 caracteres con
# mayúsculas (las claves de Binance son alfanuméricas mixtas; un SHA-256 en
# hexadecimal en minúsculas no coincide).
CREDENTIAL_PATTERNS = (
    re.compile(r"api[_-]?key|secret|signature=|x-mbx-apikey|password|contraseña", re.I),
    re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*[A-Z])[A-Za-z0-9]{64}(?![A-Za-z0-9])"),
)
EXTERNAL_URL = re.compile(r"(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)


class PublicationError(ValueError):
    """El contenido que se iba a publicar no cumple su esquema."""


def validate_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = sorted(n for n in archive.namelist() if not n.endswith("/"))
        if names != sorted(PUBLISHABLE):
            raise PublicationError(f"archivos distintos de la lista cerrada: {names}")
        files = {}
        for name in PUBLISHABLE:
            if archive.getinfo(name).file_size > MAX_BYTES:
                raise PublicationError(f"{name}: tamaño excesivo")
            files[name] = archive.read(name)
    validate_files(files)


def validate_files(files: dict[str, bytes]) -> None:
    texts = {}
    for name, content in files.items():
        try:
            texts[name] = content.decode("utf-8")
        except UnicodeDecodeError:
            raise PublicationError(f"{name}: no es UTF-8") from None
        for pattern in CREDENTIAL_PATTERNS:
            if pattern.search(texts[name]):
                raise PublicationError(f"{name}: contiene un patrón de credencial")
    ledger_rows = _validate_ledger(texts["paper/ledger.csv"])
    _validate_anchor(texts["paper/ledger.state"], files["paper/ledger.csv"], ledger_rows)
    _validate_equity(texts["paper/equity.csv"])
    for name in ("paper/report.md", "paper/dashboard.html"):
        if re.search(r"<\s*script", texts[name], re.I) or EXTERNAL_URL.search(texts[name]):
            raise PublicationError(f"{name}: contiene scripts o URLs externas")


def _rows(text: str, name: str, columns: Sequence[str]) -> list[list[str]]:
    if "\r" in text or not text.endswith("\n"):
        raise PublicationError(f"{name}: terminadores de línea inesperados")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0] != list(columns):
        raise PublicationError(f"{name}: cabecera inesperada")
    for number, row in enumerate(rows[1:], 2):
        if len(row) != len(columns):
            raise PublicationError(f"{name}: fila {number} con {len(row)} campos")
    return rows[1:]


def _finite(value: str, name: str, number: int) -> None:
    try:
        ok = math.isfinite(float(value))
    except ValueError:
        ok = False
    if not ok:
        raise PublicationError(f"{name}: fila {number} con un número no válido")


def _validate_ledger(text: str) -> int:
    name = "paper/ledger.csv"
    rows = _rows(text, name, LEDGER_COLUMNS)
    for number, row in enumerate(rows, 2):
        symbol, side, signal_time, execution_time, *numbers = row
        if symbol not in SYMBOLS or side not in ("buy", "sell"):
            raise PublicationError(f"{name}: fila {number} con símbolo o lado no permitido")
        for stamp in (signal_time, execution_time):
            try:
                parsed = datetime.fromisoformat(stamp)
            except ValueError:
                parsed = None
            if parsed is None or parsed.utcoffset() is None or parsed.isoformat() != stamp:
                raise PublicationError(f"{name}: fila {number} con fecha no válida")
        for value in numbers:
            _finite(value, name, number)
    return len(rows)


def _validate_anchor(text: str, ledger: bytes, rows: int) -> None:
    name = "paper/ledger.state"
    lines = text.split("\n")
    pattern = re.compile(r"last_day=(\d{4}-\d{2}-\d{2})\nrows=(\d+)\nsha256=([0-9a-f]{64})\n")
    match = pattern.fullmatch(text)
    if match is None or len(lines) != 4:
        raise PublicationError(f"{name}: formato inesperado")
    try:
        date.fromisoformat(match.group(1))
    except ValueError:
        raise PublicationError(f"{name}: fecha no válida") from None
    if int(match.group(2)) != rows or match.group(3) != hashlib.sha256(ledger).hexdigest():
        raise PublicationError(f"{name}: no coincide con ledger.csv")


def _validate_equity(text: str) -> None:
    name = "paper/equity.csv"
    for number, (day, symbol, *numbers) in enumerate(_rows(text, name, EQUITY_COLUMNS), 2):
        try:
            date.fromisoformat(day)
            valid_day = re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) is not None
        except ValueError:
            valid_day = False
        if not valid_day or symbol not in SYMBOLS:
            raise PublicationError(f"{name}: fila {number} con fecha o símbolo no válidos")
        for value in numbers:
            _finite(value, name, number)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida lo que se va a publicar (D030).")
    parser.add_argument("archive", type=Path)
    archive = parser.parse_args(argv).archive
    problem = None
    try:
        validate_archive(archive)
    except (PublicationError, OSError, zipfile.BadZipFile, KeyError) as error:
        problem = f"{type(error).__name__}: {error}"
    if problem:
        print(f"PUBLICACION RECHAZADA: {problem}")
        return 1
    print("publicacion valida")
    return 0


if __name__ == "__main__":
    sys.exit(main())
