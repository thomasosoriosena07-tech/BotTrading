"""EXP-15M-001: validador de velas 15m y manifiesto (Anexo A.4, enmienda 1). Sin red."""

import ast
import hashlib
import io
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from bottrading import exp15m_data
from bottrading.data import DataValidationError
from bottrading.exp15m_data import (
    Gap,
    build_manifest,
    check_manifest,
    load_15m,
    main,
    render_manifest,
    zip_files,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def row(moment: datetime, *, close: datetime | None = None, trades: int = 10,
        volume: str = "1.5", micro: bool = False) -> list[str]:
    close = close or moment + STEP - (timedelta(microseconds=1) if micro else timedelta(milliseconds=1))
    open_raw = int(moment.timestamp() * 1_000_000) if micro else ms(moment)
    close_raw = int(close.timestamp() * 1_000_000) if micro else ms(close)
    return [str(open_raw), "100", "101", "99", "100.5", volume, str(close_raw),
            "150", str(trades), "0.7", "70", "0"]


def write_zip(folder: Path, name: str, rows: list[list[str]], checksum: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    text = "\n".join(",".join(r) for r in rows) + "\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name.replace(".zip", ".csv"), text)
    path = folder / name
    path.write_bytes(buffer.getvalue())
    if checksum:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (folder / (name + ".CHECKSUM")).write_text(f"{digest}  {name}\n", encoding="utf-8")
    return path


def series(start: datetime, count: int, **kwargs) -> list[list[str]]:
    return [row(start + i * STEP, **kwargs) for i in range(count)]


JAN = datetime(2024, 1, 1, tzinfo=UTC)


def test_valid_month_has_no_gaps(tmp_path):
    path = write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", series(JAN, 200))
    candles, report = load_15m([path], NOW)
    assert len(candles) == report.candles == 200
    assert report.gaps == () and report.missing == 0
    assert report.truncated == () and report.no_trade == () and report.empty_days == ()


def test_microsecond_timestamps_are_accepted(tmp_path):
    path = write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", series(JAN, 10, micro=True))
    candles, report = load_15m([path], NOW)
    assert candles[0].timestamp == JAN and report.gaps == ()


def test_missing_candles_are_listed_not_filled(tmp_path):
    rows = series(JAN, 5) + series(JAN + 8 * STEP, 3)  # faltan 3 velas
    candles, report = load_15m([write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", rows)], NOW)
    assert len(candles) == 8
    assert report.gaps == (Gap(JAN + 4 * STEP, 3),) and report.missing == 3


def test_open_time_off_grid_is_rejected(tmp_path):
    rows = series(JAN, 2) + [row(JAN + 2 * STEP + timedelta(minutes=7))]
    with pytest.raises(DataValidationError, match="rejilla"):
        load_15m([write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", rows)], NOW)


def test_close_time_longer_than_its_candle_is_rejected(tmp_path):
    rows = [row(JAN, close=JAN + STEP + timedelta(seconds=1))]
    with pytest.raises(DataValidationError, match="close_time"):
        load_15m([write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", rows)], NOW)


def test_truncated_candle_with_trades_is_kept_and_marked(tmp_path):
    rows = series(JAN, 2) + [row(JAN + 2 * STEP, close=JAN + 2 * STEP + timedelta(minutes=5))]
    candles, report = load_15m([write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", rows)], NOW)
    assert len(candles) == 3 and report.truncated == (JAN + 2 * STEP,)


def test_candle_without_trades_becomes_a_gap(tmp_path):
    # Como en la parada real del 2020-12-21: 0 operaciones, volumen 0 y close_time absurdo.
    halted = row(JAN + 2 * STEP, close=JAN + STEP, trades=0, volume="0.00000000")
    rows = series(JAN, 2) + [halted] + [row(JAN + 3 * STEP)]
    candles, report = load_15m([write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", rows)], NOW)
    assert [c.timestamp for c in candles] == [JAN, JAN + STEP, JAN + 3 * STEP]
    assert report.no_trade == (JAN + 2 * STEP,)
    assert report.gaps == (Gap(JAN + STEP, 1),)


@pytest.mark.parametrize("trades,volume", [(0, "2.0"), (5, "0")])
def test_trades_and_volume_must_agree(tmp_path, trades, volume):
    rows = [row(JAN, trades=trades, volume=volume)]
    with pytest.raises(DataValidationError, match="incoherentes"):
        load_15m([write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", rows)], NOW)


def test_duplicate_or_disorder_is_rejected_never_sorted(tmp_path):
    rows = series(JAN, 3) + [row(JAN + STEP)]
    with pytest.raises(DataValidationError, match="duplicado o desorden"):
        load_15m([write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", rows)], NOW)


def test_duplicate_of_a_discarded_candle_is_rejected(tmp_path):
    rows = [row(JAN), row(JAN + STEP, trades=0, volume="0"), row(JAN + STEP)]
    with pytest.raises(DataValidationError, match="duplicado o desorden"):
        load_15m([write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", rows)], NOW)


def test_disorder_across_files_is_rejected(tmp_path):
    feb = datetime(2024, 2, 1, tzinfo=UTC)
    first = write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", series(JAN, 2))
    second = write_zip(tmp_path, "BTCUSDT-15m-2024-02.zip", series(feb, 2))
    load_15m([first, second], NOW)
    with pytest.raises(DataValidationError, match="duplicado o desorden"):
        load_15m([second, first], NOW)


def test_candle_outside_its_file_month_is_rejected(tmp_path):
    rows = [row(datetime(2024, 2, 1, tzinfo=UTC))]
    with pytest.raises(DataValidationError, match="en el archivo de 2024-01"):
        load_15m([write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", rows)], NOW)


def test_current_or_future_month_is_rejected(tmp_path):
    october = datetime(2026, 10, 1, tzinfo=UTC)
    current = write_zip(tmp_path, "BTCUSDT-15m-2026-10.zip", series(october, 2))
    with pytest.raises(DataValidationError, match="mes en curso"):
        load_15m([current], NOW)
    september = datetime(2026, 9, 1, tzinfo=UTC)
    closed = write_zip(tmp_path, "BTCUSDT-15m-2026-09.zip", series(september, 2))
    assert load_15m([closed], NOW)[1].candles == 2


def test_missing_checksum_is_rejected(tmp_path):
    path = write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", series(JAN, 2), checksum=False)
    with pytest.raises(DataValidationError, match="CHECKSUM"):
        load_15m([path], NOW)


def test_wrong_checksum_is_rejected(tmp_path):
    path = write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", series(JAN, 2))
    (tmp_path / (path.name + ".CHECKSUM")).write_text("0" * 64 + "  x\n", encoding="utf-8")
    with pytest.raises(DataValidationError, match="SHA-256"):
        load_15m([path], NOW)


@pytest.mark.parametrize("name", ["BTCUSDT-1h-2024-01.zip", "BTCUSDT-15m-2024-13.zip",
                                  "BTCUSDT-15m-2024-01-02.zip"])
def test_unexpected_file_names_are_rejected(tmp_path, name):
    path = write_zip(tmp_path, name, series(JAN, 2))
    with pytest.raises(DataValidationError):
        load_15m([path], NOW)


def test_utc_days_without_any_candle_are_listed(tmp_path):
    rows = series(JAN, 4) + series(JAN + timedelta(days=2), 4)
    _, report = load_15m([write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", rows)], NOW)
    assert report.empty_days == (date(2024, 1, 2),)


# --- manifiesto ------------------------------------------------------------------------


def test_manifest_detects_changes_missing_and_extra_files(tmp_path):
    data = tmp_path / "data"
    first = write_zip(data, "BTCUSDT-15m-2024-01.zip", series(JAN, 2))
    manifest = tmp_path / "m.csv"
    manifest.write_text(render_manifest(build_manifest([first])), encoding="utf-8")
    assert check_manifest(manifest, [first]) == []
    feb = datetime(2024, 2, 1, tzinfo=UTC)
    second = write_zip(data, "BTCUSDT-15m-2024-02.zip", series(feb, 2))
    assert check_manifest(manifest, [first, second]) == [f"no está en el manifiesto: {second.name}"]
    assert check_manifest(manifest, []) == [f"falta {first.name}"]
    first.write_bytes(first.read_bytes() + b"x")
    assert check_manifest(manifest, [first]) == [f"tamaño o SHA-256 distinto: {first.name}"]


def test_manifest_with_repeated_file_is_rejected(tmp_path):
    # Revisión de Codex (I1): un manifiesto alterado con un nombre repetido no se acepta.
    path = write_zip(tmp_path / "data", "BTCUSDT-15m-2024-01.zip", series(JAN, 2))
    text = render_manifest(build_manifest([path]))
    manifest = tmp_path / "m.csv"
    manifest.write_text(text + text.splitlines()[1] + "\n", encoding="utf-8")
    with pytest.raises(DataValidationError, match="repetido"):
        check_manifest(manifest, [path])


def test_cli_writes_manifest_once_then_checks_it(tmp_path, capsys):
    data = tmp_path / "data"
    write_zip(data, "BTCUSDT-15m-2024-01.zip", series(JAN, 3))
    manifest = tmp_path / "out" / "data_manifest.csv"
    args = ["--data", str(data), "--manifest", str(manifest)]
    assert main(args + ["--write-manifest"], now=NOW) == 0
    assert main(args + ["--write-manifest"], now=NOW) == 2  # nunca sobrescribe
    assert "no se sobrescribe" in capsys.readouterr().err
    assert main(args, now=NOW) == 0
    assert "Manifiesto OK" in capsys.readouterr().out
    (data / "BTCUSDT-15m-2024-01.zip").write_bytes(b"cambiado")
    assert main(args, now=NOW) == 2


def test_cli_without_data_folder_fails_cleanly(tmp_path, capsys):
    assert main(["--data", str(tmp_path / "nada")], now=NOW) == 2
    assert "no existe" in capsys.readouterr().err


def test_zip_files_lists_only_zips_in_name_order(tmp_path):
    feb = datetime(2024, 2, 1, tzinfo=UTC)
    write_zip(tmp_path, "BTCUSDT-15m-2024-02.zip", series(feb, 1))
    write_zip(tmp_path, "BTCUSDT-15m-2024-01.zip", series(JAN, 1))
    assert [p.name for p in zip_files(tmp_path)] == ["BTCUSDT-15m-2024-01.zip",
                                                     "BTCUSDT-15m-2024-02.zip"]


# --- aislamiento (A.3-4) ---------------------------------------------------------------


def _imports(path: Path) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # Revisión de Codex de I2: la guarda no sigue importaciones relativas, así
            # que se prohíben en el paquete (todas son absolutas).
            assert node.level == 0, f"{path.name}: importación relativa"
            names.append(node.module or "")
            # "from bottrading import demo_client" importa un módulo por su nombre.
            if node.module == "bottrading":
                names += [f"bottrading.{alias.name}" for alias in node.names]
    return names


def test_experiment_modules_never_import_demo_or_network_modules():
    # Recorre también, de forma transitiva, los módulos de bottrading de los que dependen
    # (revisión de Codex de I1: la guarda no debe limitarse a exp15m*.py).
    package = Path(exp15m_data.__file__).parent
    forbidden = {"demo_client", "demo_ledger", "demo_reconcile", "demo_report",
                 "demo_dashboard", "execution", "download", "paper", "publication",
                 "urllib", "socket", "http", "requests", "ssl", "importlib"}
    pending = sorted(package.glob("exp15m*.py"))
    assert pending
    seen: set[Path] = set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        for name in _imports(module):
            parts = name.split(".")
            assert not set(parts) & forbidden, f"{module.name} importa {name}"
            if parts[0] == "bottrading" and len(parts) > 1:
                pending.append(package / f"{parts[1]}.py")
    assert package / "binance.py" in seen  # la dependencia del baseline también se revisa


def test_package_is_imported_from_this_worktree():
    # A.3-2: el código que se ejecuta es el de esta copia, no el de otra.
    repo = Path(__file__).resolve().parents[1]
    assert Path(exp15m_data.__file__).resolve().is_relative_to(repo / "src")
