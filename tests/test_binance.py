"""Importador de klines de Binance con archivos sintéticos (sin red)."""

import hashlib
import zipfile
from datetime import datetime, timezone

import pytest

from bottrading.__main__ import main
from bottrading.binance import (
    expand_paths,
    load_binance_klines,
    parse_kline_time,
    verify_checksum,
)
from bottrading.data import DataValidationError

HOUR_US = 3_600_000_000
JAN_2025_US = 1_735_689_600_000_000  # 2025-01-01T00:00:00Z en µs


def kline(open_us, price=100.0, unit="us"):
    """Fila de 12 columnas como las de data.binance.vision."""
    div = 1 if unit == "us" else 1_000
    open_t = open_us // div
    close_t = (open_us + HOUR_US) // div - 1
    return (
        f"{open_t},{price:.8f},{price + 1:.8f},{price - 1:.8f},{price:.8f},"
        f"10.0,{close_t},1000.0,5,4.0,400.0,0"
    )


def rows(start_hour, count, unit="us"):
    return [kline(JAN_2025_US + (start_hour + i) * HOUR_US, 100 + i, unit)
            for i in range(count)]


def write_zip(path, lines, checksum=None):
    csv_name = path.with_suffix(".csv").name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(csv_name, "\n".join(lines) + "\n")
    if checksum == "ok":
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_name(path.name + ".CHECKSUM").write_text(f"{digest}  {path.name}")
    elif checksum == "bad":
        path.with_name(path.name + ".CHECKSUM").write_text(f"{'0' * 64}  {path.name}")
    return path


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# --- tiempos -----------------------------------------------------------------------


def test_microseconds_and_milliseconds_are_detected():
    assert parse_kline_time(str(JAN_2025_US)) == utc(2025, 1, 1)
    assert parse_kline_time(str(JAN_2025_US // 1000)) == utc(2025, 1, 1)


@pytest.mark.parametrize("raw", ["1735689600", "-5", "1.5e15", "abc", ""])
def test_invalid_times_are_rejected(raw):
    with pytest.raises(DataValidationError):
        parse_kline_time(raw)


# --- carga -------------------------------------------------------------------------


def test_loads_zip(tmp_path):
    path = write_zip(tmp_path / "BTCUSDT-1h-2025-01.zip", rows(0, 3), checksum="ok")
    candles = load_binance_klines([path])
    assert [c.timestamp for c in candles] == [utc(2025, 1, 1, h) for h in range(3)]
    assert candles[0].open == 100.0 and candles[0].high == 101.0
    assert candles[0].volume == 10.0


def test_loads_extracted_csv_with_milliseconds(tmp_path):
    path = tmp_path / "old.csv"
    path.write_text("\n".join(rows(0, 2, unit="ms")) + "\n", encoding="utf-8")
    assert len(load_binance_klines([path])) == 2


def test_header_row_is_tolerated(tmp_path):
    path = tmp_path / "with_header.csv"
    header = ("open_time,open,high,low,close,volume,close_time,quote_volume,"
              "count,taker_buy_volume,taker_buy_quote_volume,ignore")
    path.write_text("\n".join([header, *rows(0, 2)]) + "\n", encoding="utf-8")
    assert len(load_binance_klines([path])) == 2


def test_directory_merges_files_in_order(tmp_path):
    write_zip(tmp_path / "b.zip", rows(3, 2))
    write_zip(tmp_path / "a.zip", rows(0, 3))
    candles = load_binance_klines([tmp_path])
    assert len(candles) == 5
    assert candles == sorted(candles, key=lambda c: c.timestamp)


def test_expand_paths_ignores_checksum_files(tmp_path):
    write_zip(tmp_path / "a.zip", rows(0, 1), checksum="ok")
    assert [p.name for p in expand_paths([tmp_path])] == ["a.zip"]


def test_duplicates_across_files_report_both_locations(tmp_path):
    write_zip(tmp_path / "a.zip", rows(0, 3))
    write_zip(tmp_path / "b.zip", rows(2, 2))  # la hora 2 está en ambos
    with pytest.raises(DataValidationError, match=r"b\.zip:1: .*ya en a\.zip:3"):
        load_binance_klines([tmp_path])


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("1,2,3", "3 columnas"),
        (kline(JAN_2025_US).replace(",10.0,", ",-1.0,", 1), "volumen"),
        (kline(JAN_2025_US).replace("101.00000000", "50.00000000", 1), "high es menor"),
        (f"{JAN_2025_US},1,1,1,1,1,{JAN_2025_US},0,0,0,0,0", "close_time no es posterior"),
        (kline(JAN_2025_US).replace("100.00000000", "nan", 1), "no es finito"),
    ],
)
def test_invalid_rows_report_file_and_line(tmp_path, line, message):
    path = write_zip(tmp_path / "x.zip", [*rows(-2, 1), line])
    with pytest.raises(DataValidationError, match=f"x.zip:2: .*{message}"):
        load_binance_klines([path])


def test_blank_line_between_rows_is_rejected(tmp_path):
    path = tmp_path / "gap.csv"
    path.write_text("\n".join([rows(0, 1)[0], "", rows(1, 1)[0]]) + "\n", encoding="utf-8")
    with pytest.raises(DataValidationError, match="línea vacía"):
        load_binance_klines([path])


def test_zip_must_contain_exactly_one_csv(tmp_path):
    path = tmp_path / "two.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.csv", rows(0, 1)[0])
        archive.writestr("b.csv", rows(1, 1)[0])
    with pytest.raises(DataValidationError, match="un CSV dentro del ZIP, hay 2"):
        load_binance_klines([path])


def test_corrupt_zip_is_rejected(tmp_path):
    path = tmp_path / "broken.zip"
    path.write_bytes(b"esto no es un zip")
    with pytest.raises(DataValidationError, match="ZIP dañado"):
        load_binance_klines([path])


def test_missing_path_and_empty_directory_are_rejected(tmp_path):
    with pytest.raises(DataValidationError, match="no existe"):
        load_binance_klines([tmp_path / "nope.zip"])
    with pytest.raises(DataValidationError, match="no contiene archivos"):
        load_binance_klines([tmp_path])


# --- checksum ----------------------------------------------------------------------


def test_matching_checksum_is_verified(tmp_path):
    path = write_zip(tmp_path / "a.zip", rows(0, 1), checksum="ok")
    assert verify_checksum(path) is True


def test_missing_checksum_warns(tmp_path, caplog):
    path = write_zip(tmp_path / "a.zip", rows(0, 1))
    assert verify_checksum(path) is False
    load_binance_klines([path])
    assert "sin .CHECKSUM" in caplog.text


def test_wrong_checksum_is_rejected(tmp_path):
    path = write_zip(tmp_path / "a.zip", rows(0, 1), checksum="bad")
    with pytest.raises(DataValidationError, match="SHA-256 no coincide"):
        load_binance_klines([path])


# --- línea de comandos ---------------------------------------------------------------


def test_cli_with_binance_directory(tmp_path, capsys):
    data = tmp_path / "data"
    data.mkdir()
    write_zip(data / "BTCUSDT-1h-2025-01.zip", rows(0, 40), checksum="ok")
    write_zip(data / "BTCUSDT-1h-2025-02.zip", rows(40, 40))
    out = tmp_path / "out"
    code = main(["--binance", str(data), "--fast", "3", "--slow", "8", "--out", str(out)])
    assert code == 0
    text = (out / "report.md").read_text(encoding="utf-8")
    assert "Archivos (2)" in text
    assert "`BTCUSDT-1h-2025-01.zip`" in text and "(checksum verificado)" in text
    assert "`BTCUSDT-1h-2025-02.zip`" in text and "(sin .CHECKSUM)" in text
    assert "Velas: 80" in text


def test_cli_default_output_name(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    write_zip(data / "BTCUSDT-1h-2025-01.zip", rows(0, 20))
    write_zip(data / "BTCUSDT-1h-2025-02.zip", rows(20, 20))
    monkeypatch.chdir(tmp_path)
    assert main(["--binance", "data", "--fast", "3", "--slow", "8"]) == 0
    expected = "BTCUSDT-1h-2025-01_a_BTCUSDT-1h-2025-02_sma3-8"
    assert (tmp_path / "reports" / expected / "report.md").exists()


def test_cli_rejects_csv_and_binance_together(tmp_path):
    with pytest.raises(SystemExit):
        main(["--csv", "a.csv", "--binance", "b.zip"])


def test_cli_reports_bad_binance_data(tmp_path, capsys):
    path = write_zip(tmp_path / "a.zip", rows(0, 1), checksum="bad")
    assert main(["--binance", str(path), "--out", str(tmp_path / "o")]) == 2
    assert "SHA-256 no coincide" in capsys.readouterr().err


# --- entradas dañadas (revisión de Codex de T013) ------------------------------------


def test_zip_with_bad_crc_is_rejected(tmp_path):
    path = tmp_path / "crc.zip"
    content = ("\n".join(rows(0, 3)) + "\n").encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("crc.csv", content)
    raw = bytearray(path.read_bytes())
    offset = raw.index(content)  # sin compresión el CSV aparece tal cual
    raw[offset] ^= 0x01  # cambia un byte: el CRC-32 deja de coincidir
    path.write_bytes(bytes(raw))
    with pytest.raises(DataValidationError, match="contenido del ZIP dañado"):
        load_binance_klines([path])


@pytest.mark.parametrize("raw", ["9" * 20, "9" * 40])
def test_huge_times_are_rejected(raw):
    with pytest.raises(DataValidationError, match="fuera de rango"):
        parse_kline_time(raw)


def test_huge_time_in_file_reports_location(tmp_path):
    bad = f"{'9' * 20},1,1,1,1,1,{'9' * 21},0,0,0,0,0"
    path = write_zip(tmp_path / "x.zip", [*rows(0, 1), bad])
    with pytest.raises(DataValidationError, match="x.zip:2: tiempo fuera de rango"):
        load_binance_klines([path])
