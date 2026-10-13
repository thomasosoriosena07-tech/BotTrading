"""Descarga de klines históricos PÚBLICOS de data.binance.vision (D019).

Único módulo del proyecto con acceso a red. Solo descarga archivos
públicos mensuales de spot: sin cuenta, sin claves API, sin órdenes.
Cada ZIP se verifica con su .CHECKSUM antes de guardarse.

Uso:
    python -m bottrading.download --symbol BTCUSDT --interval 1d \
        --start 2020-01 --end 2026-09
"""

import argparse
import hashlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
ALLOWED_HOST = "data.binance.vision"
INTERVALS = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d")
SYMBOL_PATTERN = re.compile(r"[A-Z0-9]{2,20}")
MONTH_PATTERN = re.compile(r"(\d{4})-(\d{2})")
PAUSE_SECONDS = 0.2  # pausa entre descargas para no saturar el servidor
TIMEOUT_SECONDS = 30

Fetch = Callable[[str], bytes | None]


class DownloadError(Exception):
    """Descarga fallida o archivo que no supera la verificación."""


def month_range(start: str, end: str) -> list[str]:
    """Meses 'YYYY-MM' de start a end, ambos incluidos."""
    first, last = _parse_month(start), _parse_month(end)
    if first > last:
        raise ValueError(f"start ({start}) es posterior a end ({end})")
    months = []
    year, month = first
    while (year, month) <= last:
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def last_complete_month(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    year, month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    return f"{year:04d}-{month:02d}"


def kline_file_name(symbol: str, interval: str, month: str) -> str:
    return f"{symbol}-{interval}-{month}.zip"


def kline_url(symbol: str, interval: str, month: str) -> str:
    return f"{BASE_URL}/{symbol}/{interval}/{kline_file_name(symbol, interval, month)}"


def download_month(
    symbol: str, interval: str, month: str, out_dir: Path, fetch: Fetch
) -> str:
    """Devuelve 'descargado', 'ya presente' o 'no disponible'."""
    zip_path = out_dir / kline_file_name(symbol, interval, month)
    checksum_path = zip_path.with_name(zip_path.name + ".CHECKSUM")
    if zip_path.exists() and checksum_path.exists():
        expected = _checksum_value(checksum_path.read_bytes(), zip_path.name)
        if hashlib.sha256(zip_path.read_bytes()).hexdigest() == expected:
            return "ya presente"

    url = kline_url(symbol, interval, month)
    checksum = fetch(url + ".CHECKSUM")
    if checksum is None:
        return "no disponible"
    content = fetch(url)
    if content is None:
        return "no disponible"
    expected = _checksum_value(checksum, zip_path.name)
    if hashlib.sha256(content).hexdigest() != expected:
        raise DownloadError(f"{zip_path.name}: SHA-256 no coincide; no se guarda")

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(zip_path, content)
    _write_atomic(checksum_path, checksum)
    return "descargado"


def is_allowed_url(url: str) -> bool:
    """Solo HTTPS al host de datos públicos de Binance."""
    parts = urllib.parse.urlsplit(url)
    return (parts.scheme == "https" and parts.hostname == ALLOWED_HOST
            and parts.username is None and parts.port in (None, 443))


class SameHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Sigue redirecciones solo si el destino también es un URL permitido."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_allowed_url(newurl):
            raise DownloadError(f"redirección no permitida: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Sustituye al manejador de redirecciones por defecto de urllib.
_OPENER = urllib.request.build_opener(SameHostRedirectHandler)


def fetch_url(url: str) -> bytes | None:
    """GET HTTPS a data.binance.vision. None si el archivo no existe (404)."""
    if not url.startswith(BASE_URL + "/") or not is_allowed_url(url):
        raise DownloadError(f"URL no permitida: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "bottrading-educativo"})
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            if not is_allowed_url(response.geturl()):
                raise DownloadError(f"respuesta desde URL no permitida: {response.geturl()}")
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise DownloadError(f"{url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"{url}: {exc.reason}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bottrading.download",
        description="Descarga klines mensuales públicos de data.binance.vision.",
    )
    parser.add_argument("--symbol", required=True, help="p. ej. BTCUSDT")
    parser.add_argument("--interval", required=True, choices=INTERVALS)
    parser.add_argument("--start", required=True, help="primer mes, YYYY-MM")
    parser.add_argument("--end", default=None,
                        help="último mes, YYYY-MM (por defecto el último mes cerrado)")
    parser.add_argument("--out", type=Path, default=None,
                        help="carpeta destino (por defecto data/<SYMBOL>-<interval>)")
    return parser


def main(
    argv: Sequence[str] | None = None,
    fetch: Fetch = fetch_url,
    pause: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not SYMBOL_PATTERN.fullmatch(args.symbol):
            raise ValueError(f"símbolo no válido: {args.symbol!r} (p. ej. BTCUSDT)")
        latest = last_complete_month(now)
        end = args.end or latest
        if _parse_month(end) > _parse_month(latest):
            raise ValueError(f"{end} no es un mes cerrado (último: {latest})")
        months = month_range(args.start, end)
        out_dir = args.out or Path("data") / f"{args.symbol}-{args.interval}"

        statuses: dict[str, list[str]] = {}
        for i, month in enumerate(months):
            if i:
                pause(PAUSE_SECONDS)
            status = download_month(args.symbol, args.interval, month, out_dir, fetch)
            statuses.setdefault(status, []).append(month)
            print(f"{month}: {status}")
    except (ValueError, DownloadError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Carpeta: {out_dir}")
    for status, done in statuses.items():
        print(f"{status}: {len(done)}")
    if "no disponible" in statuses:
        print("Meses no disponibles (p. ej. antes del listado del símbolo): "
              + ", ".join(statuses["no disponible"]))
    return 0


def _parse_month(text: str) -> tuple[int, int]:
    match = MONTH_PATTERN.fullmatch(text)
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise ValueError(f"mes no válido: {text!r} (formato YYYY-MM)")
    return int(match.group(1)), int(match.group(2))


def _checksum_value(content: bytes, file_name: str) -> str:
    parts = content.decode("utf-8", errors="replace").split()
    if len(parts) < 2 or parts[1] != file_name or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
        raise DownloadError(f"{file_name}: .CHECKSUM con formato inesperado")
    return parts[0]


def _write_atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(content)
    temporary.replace(path)


if __name__ == "__main__":
    sys.exit(main())
