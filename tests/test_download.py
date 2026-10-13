"""Descargador con un `fetch` falso: ninguna prueba usa la red."""

import hashlib
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

import bottrading.download as download
from bottrading.download import (
    DownloadError,
    SameHostRedirectHandler,
    download_month,
    fetch_url,
    is_allowed_url,
    kline_url,
    last_complete_month,
    main,
    month_range,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "bottrading"
NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


class FakeServer:
    """Sirve ZIP y CHECKSUM en memoria; registra las URL pedidas."""

    def __init__(self, months=(), corrupt=()):
        self.files = {}
        self.requested = []
        for month in months:
            name = f"BTCUSDT-1d-{month}.zip"
            content = f"zip {month}".encode()
            digest = hashlib.sha256(b"otro" if month in corrupt else content).hexdigest()
            url = kline_url("BTCUSDT", "1d", month)
            self.files[url] = content
            self.files[url + ".CHECKSUM"] = f"{digest}  {name}\n".encode()

    def __call__(self, url):
        self.requested.append(url)
        return self.files.get(url)


def test_month_range_crosses_years():
    assert month_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]


@pytest.mark.parametrize(("start", "end"), [("2026-02", "2026-01"), ("2026-13", "2026-12"), ("26-01", "2026-02")])
def test_month_range_rejects_invalid(start, end):
    with pytest.raises(ValueError):
        month_range(start, end)


def test_last_complete_month():
    assert last_complete_month(NOW) == "2026-09"
    assert last_complete_month(datetime(2026, 1, 5, tzinfo=timezone.utc)) == "2025-12"


def test_kline_url():
    assert kline_url("BTCUSDT", "1d", "2026-09") == (
        "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2026-09.zip"
    )


def test_download_verifies_and_writes(tmp_path):
    server = FakeServer(["2026-08"])
    assert download_month("BTCUSDT", "1d", "2026-08", tmp_path, server) == "descargado"
    assert (tmp_path / "BTCUSDT-1d-2026-08.zip").read_bytes() == b"zip 2026-08"
    assert (tmp_path / "BTCUSDT-1d-2026-08.zip.CHECKSUM").exists()
    assert not list(tmp_path.glob("*.part"))


def test_verified_existing_file_is_not_downloaded_again(tmp_path):
    server = FakeServer(["2026-08"])
    download_month("BTCUSDT", "1d", "2026-08", tmp_path, server)
    server.requested.clear()
    assert download_month("BTCUSDT", "1d", "2026-08", tmp_path, server) == "ya presente"
    assert server.requested == []


def test_missing_month_is_reported_not_written(tmp_path):
    assert download_month("BTCUSDT", "1d", "2017-01", tmp_path, FakeServer()) == "no disponible"
    assert not tmp_path.exists() or not list(tmp_path.iterdir())


def test_checksum_mismatch_is_an_error_and_nothing_is_saved(tmp_path):
    server = FakeServer(["2026-08"], corrupt={"2026-08"})
    out_dir = tmp_path / "out"
    with pytest.raises(DownloadError, match="SHA-256 no coincide"):
        download_month("BTCUSDT", "1d", "2026-08", out_dir, server)
    # Nada escrito: ni ZIP, ni .CHECKSUM, ni .part, ni la carpeta.
    assert not out_dir.exists()


def test_cli_downloads_range_with_pauses(tmp_path, capsys):
    server = FakeServer(["2026-07", "2026-08", "2026-09"])
    pauses = []
    code = main(["--symbol", "BTCUSDT", "--interval", "1d", "--start", "2026-06",
                 "--out", str(tmp_path)], fetch=server, pause=pauses.append, now=NOW)
    out = capsys.readouterr().out
    assert code == 0
    assert "2026-06: no disponible" in out and "descargado: 3" in out
    assert len(pauses) == 3  # entre los 4 meses
    assert len(list(tmp_path.glob("*.zip"))) == 3


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--symbol", "btc/usdt", "--start", "2026-01"], "símbolo no válido"),
        (["--symbol", "BTCUSDT", "--start", "2026-01", "--end", "2026-10"], "no es un mes cerrado"),
        (["--symbol", "BTCUSDT", "--start", "2026-05", "--end", "2026-01"], "posterior"),
    ],
)
def test_cli_rejects_invalid_arguments(tmp_path, capsys, args, message):
    code = main([*args, "--interval", "1d", "--out", str(tmp_path)],
                fetch=FakeServer(), pause=lambda s: None, now=NOW)
    assert code == 2
    assert message in capsys.readouterr().err


def test_cli_reports_checksum_mismatch(tmp_path, capsys):
    server = FakeServer(["2026-09"], corrupt={"2026-09"})
    code = main(["--symbol", "BTCUSDT", "--interval", "1d", "--start", "2026-09",
                 "--out", str(tmp_path)], fetch=server, pause=lambda s: None, now=NOW)
    assert code == 2
    assert "SHA-256 no coincide" in capsys.readouterr().err


# D019: guarda ESTÁTICA, no un límite de seguridad. Ningún otro módulo
# importa librerías de red, el descargador, ni importa código dinámicamente.
NETWORK_GUARD = re.compile(
    r"^\s*(import|from)\s+(urllib|http|socket|ssl|requests|httpx|aiohttp|"
    r"websocket|websockets|bottrading\.download)\b"
    r"|^\s*from\s+bottrading\s+import\s+.*\bdownload\b"
    r"|\b(__import__|importlib)\b",
    re.M,
)


def test_only_download_module_uses_the_network():
    offenders = [
        path.name for path in SRC.glob("*.py")
        if path.name != "download.py"
        and NETWORK_GUARD.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_network_guard_detects_offenders():
    # La expresión de la guarda sí detecta los casos que pretende cubrir.
    samples = ["import socket", "from urllib import request", "import httpx",
               "from bottrading.download import fetch_url",
               "from bottrading import download", "x = __import__('ssl')"]
    assert all(NETWORK_GUARD.search(sample) for sample in samples)
    assert not NETWORK_GUARD.search("from bottrading.data import Candle")


# --- redirecciones (revisión de Codex de T013b) -------------------------------------


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://data.binance.vision/data/x.zip", True),
        ("http://data.binance.vision/data/x.zip", False),
        ("https://evil.example/data/x.zip", False),
        ("https://data.binance.vision.evil.example/x.zip", False),
        ("https://user@data.binance.vision/x.zip", False),
        ("https://data.binance.vision:8443/x.zip", False),
    ],
)
def test_is_allowed_url(url, allowed):
    assert is_allowed_url(url) is allowed


def test_redirect_to_other_host_or_http_is_refused():
    handler = SameHostRedirectHandler()
    request = urllib.request.Request(kline_url("BTCUSDT", "1d", "2026-09"))
    for target in ("https://evil.example/x", "http://data.binance.vision/x"):
        with pytest.raises(DownloadError, match="redirección no permitida"):
            handler.redirect_request(request, None, 302, "Found", {}, target)


def test_redirect_within_allowed_host_is_followed():
    handler = SameHostRedirectHandler()
    request = urllib.request.Request(kline_url("BTCUSDT", "1d", "2026-09"))
    new = handler.redirect_request(request, None, 302, "Found", {},
                                   "https://data.binance.vision/otra/ruta.zip")
    assert new.full_url == "https://data.binance.vision/otra/ruta.zip"


def test_opener_uses_only_the_restricted_redirect_handler():
    handlers = [type(h) for h in download._OPENER.handlers]
    assert SameHostRedirectHandler in handlers
    assert urllib.request.HTTPRedirectHandler not in handlers


class FakeResponse:
    def __init__(self, url, body=b"datos"):
        self.url, self.body = url, body

    def geturl(self):
        return self.url

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error

    def open(self, request, timeout):
        if self.error:
            raise self.error
        return self.response


URL = kline_url("BTCUSDT", "1d", "2026-09")


def test_fetch_url_returns_body(monkeypatch):
    monkeypatch.setattr(download, "_OPENER", FakeOpener(FakeResponse(URL)))
    assert fetch_url(URL) == b"datos"


def test_fetch_url_rejects_response_from_other_host(monkeypatch):
    monkeypatch.setattr(download, "_OPENER", FakeOpener(FakeResponse("https://evil.example/x")))
    with pytest.raises(DownloadError, match="URL no permitida"):
        fetch_url(URL)


def test_fetch_url_maps_404_to_none_and_other_errors(monkeypatch):
    monkeypatch.setattr(download, "_OPENER",
                        FakeOpener(error=urllib.error.HTTPError(URL, 404, "NF", {}, None)))
    assert fetch_url(URL) is None
    monkeypatch.setattr(download, "_OPENER",
                        FakeOpener(error=urllib.error.HTTPError(URL, 500, "E", {}, None)))
    with pytest.raises(DownloadError, match="HTTP 500"):
        fetch_url(URL)


def test_fetch_url_rejects_urls_outside_base():
    with pytest.raises(DownloadError, match="URL no permitida"):
        fetch_url("https://data.binance.vision/otra/cosa.zip")
