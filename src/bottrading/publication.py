"""Validación de lo que la automatización publica en GitHub (D030 punto 7, F2b-3).

La tarea diaria (D028) solo puede publicar una lista CERRADA de archivos de
paper/. Antes del push, scripts/paper_daily.ps1 extrae esos archivos del
commit final (SHA fijado) con `git archive` a un zip y este módulo valida su
contenido con esquemas cerrados:

- ledger.csv: columnas fijas; símbolo de la lista; lado buy/sell; fechas ISO;
  números finitos.
- ledger.state: last_day, rows y sha256 coherentes con ledger.csv.
- equity.csv: columnas fijas; fecha, símbolo y números finitos.
- dashboard.html: LISTA BLANCA de etiquetas y atributos (exactamente los que
  genera dashboard.py), style solo "background: var(--x)", meta solo charset
  y viewport, <style> sin url()/@import/expression; sin URLs externas.
- report.md: Markdown sin ninguna etiqueta HTML ni enlaces, sin URLs.
- Todos: tamaño acotado y sin patrones de credenciales (defensa adicional,
  no criterio principal).

Sin red. Uso:
    python -m bottrading.publication <archivo.zip>
"""

import argparse
import csv
import hashlib
import io
from html.parser import HTMLParser
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
# Formato de repr(float): sin espacios, guiones bajos, signo + ni inf/nan.
DECIMAL = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?")  # solo dígitos ASCII
# Lista blanca del panel (revisión de Codex): exactamente lo que genera
# dashboard.py. Cualquier otra etiqueta o atributo (onerror, href, src...)
# se rechaza. Si dashboard.py cambia, la prueba con el panel real lo exige.
HTML_TAGS = frozenset({
    "article", "b", "body", "code", "div", "footer", "h1", "h2", "h3", "head", "header",
    "html", "i", "line", "main", "meta", "p", "polyline", "section", "span", "style", "svg",
    "table", "tbody", "td", "text", "th", "thead", "title", "tr"})
HTML_ATTRIBUTES = frozenset({
    "aria-label", "charset", "class", "content", "lang", "name", "points", "role", "style",
    "text-anchor", "viewbox", "x", "x1", "x2", "y", "y1", "y2"})
STYLE_ATTRIBUTE = re.compile(r"background: var\(--[a-z-]+\)")
META_ALLOWED = ({("charset", "utf-8")},
                {("name", "viewport"), ("content", "width=device-width, initial-scale=1")})
STYLE_FORBIDDEN = re.compile(r"url\s*\(|@import|expression\s*\(|javascript:|behavior\s*:", re.I)


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
    _validate_report(texts["paper/report.md"])
    _validate_dashboard(texts["paper/dashboard.html"])


def _validate_report(text: str) -> None:
    name = "paper/report.md"
    if re.search(r"<\s*[A-Za-z!/?]", text) or "](" in text or EXTERNAL_URL.search(text) \
            or re.search(r"javascript:", text, re.I):
        raise PublicationError(f"{name}: contiene HTML, enlaces, scripts o URLs externas")


class _DashboardChecker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        if tag not in HTML_TAGS:
            self.problems.append(f"etiqueta no permitida <{tag}>")
        for key, value in attrs:
            if key not in HTML_ATTRIBUTES:
                self.problems.append(f"atributo no permitido {key}")
            elif key == "style" and not STYLE_ATTRIBUTE.fullmatch(value or ""):
                self.problems.append("atributo style no permitido")
        if tag == "meta" and set(attrs) not in META_ALLOWED:
            self.problems.append("meta no permitido")
        self._in_style = tag == "style"

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        self._in_style = False

    def handle_data(self, data):
        if self._in_style and STYLE_FORBIDDEN.search(data):
            self.problems.append("CSS con url(), @import o expresiones")

    def handle_pi(self, data):
        self.problems.append("instrucción de procesamiento")

    def unknown_decl(self, data):
        self.problems.append("declaración desconocida")


def _validate_dashboard(text: str) -> None:
    name = "paper/dashboard.html"
    checker = _DashboardChecker()
    checker.feed(text)
    checker.close()
    if EXTERNAL_URL.search(text) or re.search(r"javascript:", text, re.I):
        checker.problems.append("URL externa o javascript:")
    if checker.problems:
        raise PublicationError(f"{name}: contiene scripts o contenido no permitido "
                               f"({'; '.join(sorted(set(checker.problems)))})")


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
    ok = DECIMAL.fullmatch(value) is not None and math.isfinite(float(value))
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
    pattern = re.compile(r"last_day=([0-9]{4}-[0-9]{2}-[0-9]{2})\nrows=([0-9]+)\n"
                         r"sha256=([0-9a-f]{64})\n")
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
            valid_day = re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day) is not None
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
