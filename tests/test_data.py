from datetime import datetime, timezone

import pytest

from bottrading.data import (
    Candle,
    DataValidationError,
    load_ohlcv_csv,
    parse_timestamp,
)

HEADER = "timestamp,open,high,low,close,volume\n"


def write_csv(tmp_path, body, header=HEADER):
    path = tmp_path / "ohlcv.csv"
    path.write_text(header + body, encoding="utf-8")
    return path


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# --- parse_timestamp ---------------------------------------------------------


def test_iso_with_z_is_utc():
    assert parse_timestamp("2024-01-01T00:00:00Z") == utc(2024, 1, 1)


def test_iso_with_offset_is_converted_to_utc():
    assert parse_timestamp("2024-01-01T02:00:00+02:00") == utc(2024, 1, 1)


def test_epoch_milliseconds_by_default():
    assert parse_timestamp("1704067200000") == utc(2024, 1, 1)


def test_epoch_seconds_when_requested():
    assert parse_timestamp("1704067200", epoch_unit="s") == utc(2024, 1, 1)


@pytest.mark.parametrize("raw", ["2024-01-01T00:00:00", "2024-01-01"])
def test_naive_timestamp_is_rejected(raw):
    with pytest.raises(DataValidationError, match="sin zona horaria"):
        parse_timestamp(raw)


@pytest.mark.parametrize("raw", ["ayer", "", "nan", "1e30"])
def test_invalid_timestamp_is_rejected(raw):
    with pytest.raises(DataValidationError):
        parse_timestamp(raw)


def test_unknown_epoch_unit_is_rejected():
    with pytest.raises(ValueError, match="epoch_unit"):
        parse_timestamp("1704067200", epoch_unit="us")


# --- load_ohlcv_csv: casos válidos --------------------------------------------


def test_loads_valid_csv(tmp_path):
    path = write_csv(
        tmp_path,
        "2024-01-01T00:00:00Z,100,110,95,105,12.5\n"
        "2024-01-01T01:00:00Z,105,108,100,101,0\n",
    )
    candles = load_ohlcv_csv(path)
    assert candles == [
        Candle(utc(2024, 1, 1, 0), 100.0, 110.0, 95.0, 105.0, 12.5),
        Candle(utc(2024, 1, 1, 1), 105.0, 108.0, 100.0, 101.0, 0.0),
    ]


def test_header_is_case_and_space_insensitive_and_extra_columns_ignored(
    tmp_path, caplog
):
    caplog.set_level("INFO")
    header = " Timestamp ,OPEN,High,Low,Close,Volume,trades\n"
    path = write_csv(tmp_path, "1704067200000,1,2,0.5,1.5,3,7\n", header=header)
    assert load_ohlcv_csv(path)[0].close == 1.5
    assert "columnas ignoradas (no OHLCV): trades" in caplog.text


def test_unordered_rows_are_sorted_with_warning(tmp_path, caplog):
    path = write_csv(
        tmp_path,
        "2024-01-01T01:00:00Z,2,2,2,2,1\n"
        "2024-01-01T00:00:00Z,1,1,1,1,1\n",
    )
    candles = load_ohlcv_csv(path)
    assert [c.open for c in candles] == [1.0, 2.0]
    assert "desordenadas" in caplog.text


# --- load_ohlcv_csv: casos inválidos ------------------------------------------


def test_missing_columns_are_reported(tmp_path):
    path = write_csv(tmp_path, "x,1,1,1,1\n", header="timestamp,open,high,low,close\n")
    with pytest.raises(DataValidationError, match="faltan columnas: volume"):
        load_ohlcv_csv(path)


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DataValidationError, match="cabecera"):
        load_ohlcv_csv(path)


def test_header_without_rows_is_rejected(tmp_path):
    with pytest.raises(DataValidationError, match="no contiene filas"):
        load_ohlcv_csv(write_csv(tmp_path, ""))


def test_duplicate_timestamps_are_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "2024-01-01T00:00:00Z,1,1,1,1,1\n"
        "2024-01-01T01:00:00+01:00,1,1,1,1,1\n",
    )
    with pytest.raises(DataValidationError, match="duplicado"):
        load_ohlcv_csv(path)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("2024-01-01T00:00:00,1,1,1,1,1", "sin zona horaria"),
        ("2024-01-01T00:00:00Z,,1,1,1,1", "valor vacío"),
        ("2024-01-01T00:00:00Z,abc,1,1,1,1", "no es numérico"),
        ("2024-01-01T00:00:00Z,nan,1,1,1,1", "no es finito"),
        ("2024-01-01T00:00:00Z,0,1,0,1,1", "positivos"),
        ("2024-01-01T00:00:00Z,1,1,1,1,-1", "negativo"),
        ("2024-01-01T00:00:00Z,1,2,1.5,1,1", "low es mayor"),
        ("2024-01-01T00:00:00Z,1,1.5,1,2,1", "high es menor"),
        ("2024-01-01T00:00:00Z,1,1,1", "4 campos; la cabecera tiene 6"),
        ("2024-01-01T00:00:00Z,1,1,1,1,1,9", "7 campos; la cabecera tiene 6"),
        ("1704067200,1,1,1,1,1", "parece estar en segundos"),
    ],
)
def test_invalid_rows_report_line_number(tmp_path, row, message):
    path = write_csv(tmp_path, "2024-01-01T23:00:00Z,1,1,1,1,1\n" + row + "\n")
    with pytest.raises(DataValidationError, match=f"línea 3: .*{message}"):
        load_ohlcv_csv(path)


def test_epoch_seconds_with_default_ms_unit_is_rejected():
    with pytest.raises(DataValidationError, match="epoch_unit='s'"):
        parse_timestamp("1704067200")


def test_epoch_milliseconds_with_seconds_unit_is_rejected():
    with pytest.raises(DataValidationError, match="epoch_unit='ms'"):
        parse_timestamp("1704067200000", epoch_unit="s")


def test_dst_offsets_are_converted_to_utc():
    # Cambio de horario en Nueva York (2024-03-10): -05:00 -> -04:00.
    before = parse_timestamp("2024-03-10T01:30:00-05:00")
    after = parse_timestamp("2024-03-10T03:30:00-04:00")
    assert before == utc(2024, 3, 10, 6, 30)
    assert after == utc(2024, 3, 10, 7, 30)


def test_utf8_bom_is_accepted(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_bytes(
        b"\xef\xbb\xbf" + (HEADER + "1704067200000,1,1,1,1,1\n").encode("utf-8")
    )
    assert load_ohlcv_csv(path)[0].timestamp == utc(2024, 1, 1)


def test_repeated_header_columns_are_rejected(tmp_path):
    header = "timestamp,open,high,low,close,volume,Close\n"
    path = write_csv(tmp_path, "1704067200000,1,1,1,1,1,1\n", header=header)
    with pytest.raises(DataValidationError, match="columnas repetidas: close"):
        load_ohlcv_csv(path)


def test_blank_line_between_rows_is_rejected(tmp_path):
    path = write_csv(
        tmp_path,
        "2024-01-01T00:00:00Z,1,1,1,1,1\n"
        "\n"
        "2024-01-01T01:00:00Z,1,1,1,1,1\n",
    )
    with pytest.raises(DataValidationError, match="línea 3: línea vacía"):
        load_ohlcv_csv(path)


def test_trailing_blank_lines_are_ignored(tmp_path):
    path = write_csv(tmp_path, "2024-01-01T00:00:00Z,1,1,1,1,1\n\n\n")
    assert len(load_ohlcv_csv(path)) == 1


def test_duplicate_reports_both_line_numbers(tmp_path):
    path = write_csv(
        tmp_path,
        "2024-01-01T00:00:00Z,1,1,1,1,1\n"
        "2024-01-01T02:00:00Z,1,1,1,1,1\n"
        "2024-01-01T01:00:00+01:00,1,1,1,1,1\n",
    )
    with pytest.raises(DataValidationError, match=r"línea 4: .*ya en línea 2"):
        load_ohlcv_csv(path)
