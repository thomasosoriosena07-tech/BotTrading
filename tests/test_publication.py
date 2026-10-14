"""Validación de lo publicable (D030 punto 7, F2b-3): sin red ni escritura en paper/."""

import hashlib
import zipfile

import pytest

import bottrading.publication as publication
from bottrading.publication import PUBLISHABLE, PublicationError, main, validate_files

from conftest import PAPER_DIR

LEDGER_HEADER = ("symbol,side,signal_time,execution_time,reference_price,price,quantity,fee,"
                 "slippage_cost,cash_after\n")
ROW = ("BTCUSDT,buy,2026-08-17T00:00:00+00:00,2026-10-01T00:00:00+00:00,83623.59,83665.4,"
       "0.1194,9.99,4.99,0.0\n")


def anchor(ledger: bytes, rows: int, day="2026-10-13") -> bytes:
    return f"last_day={day}\nrows={rows}\nsha256={hashlib.sha256(ledger).hexdigest()}\n".encode()


def good_files() -> dict[str, bytes]:
    ledger = (LEDGER_HEADER + ROW).encode()
    return {
        "paper/ledger.csv": ledger,
        "paper/ledger.state": anchor(ledger, 1),
        "paper/equity.csv": b"date,symbol,strategy_equity,buy_and_hold_equity\n"
                            b"2026-10-01,BTCUSDT,10135.04,10135.04\n",
        "paper/report.md": "# Paper trading\n\nSimulación sin dinero.\n".encode(),
        "paper/dashboard.html": b"<!doctype html><svg viewBox='0 0 1 1'></svg>",
    }


def zip_of(tmp_path, files, name="pub.zip"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for member, content in files.items():
            archive.writestr(member, content)
    return path


def test_real_committed_paper_files_are_publishable(tmp_path):
    files = {name: (PAPER_DIR.parent / name).read_bytes() for name in PUBLISHABLE}
    assert main([str(zip_of(tmp_path, files))]) == 0


def test_synthetic_good_files_are_publishable():
    validate_files(good_files())


@pytest.mark.parametrize("change", ["extra", "missing", "renamed"])
def test_only_the_closed_list_can_be_published(tmp_path, change, capsys):
    files = good_files()
    if change == "extra":
        files["paper/notas.txt"] = b"x"
    elif change == "missing":
        del files["paper/report.md"]
    else:
        files["paper/Report.md"] = files.pop("paper/report.md")
    assert main([str(zip_of(tmp_path, files))]) == 1
    assert "lista cerrada" in capsys.readouterr().out


@pytest.mark.parametrize("row", [
    ROW.replace("BTCUSDT", "BNBUSDT"),
    ROW.replace(",buy,", ",short,"),
    ROW.replace("2026-08-17T00:00:00+00:00", "2026-08-17T00:00:00"),  # sin zona
    ROW.replace("2026-08-17T00:00:00+00:00", "17/08/2026"),
    ROW.replace("83623.59", "nan"),
    ROW.replace("83623.59", "inf"),
    ROW.replace("0.0\n", "0.0,extra\n"),
    ROW.replace("\n", "\r\n"),
])
def test_ledger_schema_is_closed(row):
    files = good_files()
    ledger = (LEDGER_HEADER + row).encode()
    files["paper/ledger.csv"] = ledger
    files["paper/ledger.state"] = anchor(ledger, 1)
    with pytest.raises(PublicationError, match="ledger.csv"):
        validate_files(files)


@pytest.mark.parametrize("state", [
    lambda ledger: anchor(ledger, 2),
    lambda ledger: anchor(ledger + b"x", 1),
    lambda ledger: anchor(ledger, 1, "2026-13-40"),
    lambda ledger: anchor(ledger, 1) + b"extra=1\n",
    lambda ledger: anchor(ledger, 1).replace(b"\n", b"\r\n"),
])
def test_anchor_must_match_the_ledger(state):
    files = good_files()
    files["paper/ledger.state"] = state(files["paper/ledger.csv"])
    with pytest.raises(PublicationError, match="ledger.state"):
        validate_files(files)


@pytest.mark.parametrize("row", [
    b"2026-10-1,BTCUSDT,1,1\n", b"2026-10-01,XRPUSDT,1,1\n", b"2026-10-01,BTCUSDT,abc,1\n",
    b"2026-10-01,BTCUSDT,1\n",
])
def test_equity_schema_is_closed(row):
    files = good_files()
    files["paper/equity.csv"] = b"date,symbol,strategy_equity,buy_and_hold_equity\n" + row
    with pytest.raises(PublicationError, match="equity.csv"):
        validate_files(files)


@pytest.mark.parametrize(("name", "content"), [
    ("paper/dashboard.html", b"<html><script>alert(1)</script></html>"),
    ("paper/dashboard.html", b"<img src='https://evil.example/x.png'>"),
    ("paper/dashboard.html", b"<link href='//cdn.example.com/a.css'>"),
    ("paper/report.md", b"ver http://example.com"),
])
def test_scripts_and_external_urls_are_refused(name, content):
    files = good_files()
    files[name] = content
    with pytest.raises(PublicationError, match="scripts o URLs"):
        validate_files(files)


@pytest.mark.parametrize("leak", [
    "apiKey=abc", "X-MBX-APIKEY: abc", "secret", "signature=abc", "api_key",
    "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A",  # clave de ejemplo
])
def test_credential_patterns_are_refused(leak):
    files = good_files()
    files["paper/report.md"] = f"# Informe\n{leak}\n".encode()
    with pytest.raises(PublicationError, match="credencial"):
        validate_files(files)


def test_lowercase_sha256_is_not_mistaken_for_a_key():
    files = good_files()
    files["paper/report.md"] = ("hash " + hashlib.sha256(b"x").hexdigest() + "\n").encode()
    validate_files(files)


def test_non_utf8_and_oversized_files_are_refused(tmp_path, monkeypatch, capsys):
    files = good_files()
    files["paper/report.md"] = "Simulación".encode("latin-1")
    with pytest.raises(PublicationError, match="UTF-8"):
        validate_files(files)
    monkeypatch.setattr(publication, "MAX_BYTES", 10)
    assert main([str(zip_of(tmp_path, good_files()))]) == 1
    assert "tamaño excesivo" in capsys.readouterr().out


def test_missing_or_corrupt_archive_is_rejected_without_traceback(tmp_path, capsys):
    assert main([str(tmp_path / "no-existe.zip")]) == 1
    (tmp_path / "roto.zip").write_bytes(b"no es un zip")
    assert main([str(tmp_path / "roto.zip")]) == 1
    assert capsys.readouterr().out.count("PUBLICACION RECHAZADA") == 2
