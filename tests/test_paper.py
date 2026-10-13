"""Paper trading con datos sintéticos (sin red ni datos reales)."""

import hashlib
import math
import zipfile
from datetime import date, datetime, timedelta, timezone

import pytest

from bottrading.crossasset import CONFIG as CROSS_CONFIG
from bottrading.crossasset import FROZEN_CANDIDATE as CROSS_CANDIDATE
from bottrading.data import Candle, DataValidationError
from bottrading.paper import (
    CHECKPOINTS,
    FORWARD_START,
    SYMBOLS,
    LedgerIntegrityError,
    anchor_path,
    ledger_rows,
    load_forward_candles,
    main,
    read_anchor,
    run_paper,
    simulate,
    update_ledger,
)

HISTORY_START = datetime(2026, 3, 1, tzinfo=timezone.utc)
DAY_US = 86_400_000_000


def price(i, phase=0.0):
    return 100 * (1 + 0.25 * math.sin(i / 12 + phase))


def candle(day_index, phase=0.0):
    p = price(day_index, phase)
    return Candle(HISTORY_START + timedelta(days=day_index), p, p * 1.01, p * 0.99, p, 1.0)


def write_zip(path, candles):
    rows = []
    for c in candles:
        t = int(c.timestamp.timestamp()) * 1_000_000
        rows.append(f"{t},{c.open},{c.high},{c.low},{c.close},1.0,{t + DAY_US - 1},0,0,0,0,0")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.with_suffix(".csv").name, "\n".join(rows) + "\n")


def build_data(root, forward_days, symbols=SYMBOLS, skip_day=None):
    """<SYM>-1d: un ZIP con el historial hasta 2026-09-30 (y octubre, que
    debe ignorarse); <SYM>-1d-daily: un ZIP por día desde 2026-10-01."""
    first_forward = (datetime(2026, 10, 1, tzinfo=timezone.utc) - HISTORY_START).days
    for k, symbol in enumerate(symbols):
        monthly, daily = root / f"{symbol}-1d", root / f"{symbol}-1d-daily"
        monthly.mkdir(parents=True)
        daily.mkdir(parents=True)
        history = [candle(i, k) for i in range(first_forward)]
        write_zip(monthly / f"{symbol}-1d-history.zip", history)
        # Mensual de octubre (se publica en noviembre): debe ignorarse,
        # porque desde 2026-10-01 solo cuentan los archivos diarios.
        october = [candle(i, k + 7) for i in range(first_forward, first_forward + 31)]
        write_zip(monthly / f"{symbol}-1d-2026-10.zip", october)
        for i in range(first_forward, first_forward + forward_days):
            c = candle(i, k)
            if skip_day == c.timestamp.date():
                continue
            write_zip(daily / f"{symbol}-1d-{c.timestamp.date()}.zip", [c])


def test_protocol_constants_match_d027():
    assert FORWARD_START == date(2026, 10, 1)
    assert SYMBOLS == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert [day for _, day in CHECKPOINTS] == [date(2027, 3, 31), date(2027, 9, 30)]
    assert CROSS_CANDIDATE.label == "trend_filter(window=50)"
    assert (CROSS_CONFIG.commission_rate, CROSS_CONFIG.slippage_rate) == (0.001, 0.0005)


def test_load_forward_candles_joins_history_and_days(tmp_path):
    build_data(tmp_path, 10, symbols=("BTCUSDT",))
    candles, start = load_forward_candles(tmp_path / "BTCUSDT-1d", tmp_path / "BTCUSDT-1d-daily")
    assert candles[start].timestamp.date() == FORWARD_START
    assert candles[start - 1].timestamp.date() == date(2026, 9, 30)
    assert candles[-1].timestamp.date() == date(2026, 10, 10)
    # El precio de octubre viene del archivo diario, no del mensual de octubre.
    first_forward = (datetime(2026, 10, 1, tzinfo=timezone.utc) - HISTORY_START).days
    assert candles[start].close == price(first_forward, 0)
    assert candles[start].close != price(first_forward, 7)


def test_missing_day_is_rejected(tmp_path):
    build_data(tmp_path, 10, symbols=("BTCUSDT",), skip_day=date(2026, 10, 5))
    with pytest.raises(DataValidationError, match="falta el día 2026-10-05"):
        load_forward_candles(tmp_path / "BTCUSDT-1d", tmp_path / "BTCUSDT-1d-daily")


def test_no_forward_days_is_rejected(tmp_path):
    build_data(tmp_path, 1, symbols=("BTCUSDT",))
    for path in (tmp_path / "BTCUSDT-1d-daily").iterdir():
        path.unlink()
    with pytest.raises(DataValidationError):
        load_forward_candles(tmp_path / "BTCUSDT-1d", tmp_path / "BTCUSDT-1d-daily")


def test_assets_must_reach_the_same_day(tmp_path):
    build_data(tmp_path, 10)
    (tmp_path / "SOLUSDT-1d-daily" / "SOLUSDT-1d-2026-10-10.zip").unlink()
    with pytest.raises(DataValidationError, match="mismo día"):
        run_paper(tmp_path)


def test_simulation_trades_only_from_forward_start(tmp_path):
    build_data(tmp_path, 40)
    state = run_paper(tmp_path)
    assert state.last_day == date(2026, 11, 9)
    for asset in state.assets:
        assert asset.strategy.timestamps[0].date() == FORWARD_START
        assert all(t.execution_time.date() >= FORWARD_START for t in asset.strategy.trades)


def test_simulation_matches_direct_evaluation(tmp_path):
    build_data(tmp_path, 40, symbols=("BTCUSDT",))
    candles, start = load_forward_candles(tmp_path / "BTCUSDT-1d", tmp_path / "BTCUSDT-1d-daily")
    state = run_paper(tmp_path, symbols=("BTCUSDT",))
    assert state.assets[0].strategy == simulate("BTCUSDT", candles, start).strategy


# --- diario solo de añadir -------------------------------------------------------------


def extend_data(data, until_offset):
    base = (datetime(2026, 10, 1, tzinfo=timezone.utc) - HISTORY_START).days
    for k, symbol in enumerate(SYMBOLS):
        for i in range(base, base + until_offset):
            c = candle(i, k)
            path = data / f"{symbol}-1d-daily" / f"{symbol}-1d-{c.timestamp.date()}.zip"
            if not path.exists():
                write_zip(path, [c])


@pytest.fixture
def anchored(tmp_path):
    """Diario con ancla tras 30 días simulados."""
    data, ledger = tmp_path / "data", tmp_path / "paper" / "ledger.csv"
    build_data(data, 30)
    state = run_paper(data)
    rows = ledger_rows(state)
    assert rows, "la serie sintética debe generar operaciones"
    update_ledger(ledger, rows, state.last_day)
    return data, ledger, state, rows


def test_ledger_grows_by_appending(anchored):
    data, ledger, _, first_rows = anchored
    extend_data(data, 60)
    state = run_paper(data)
    more_rows = ledger_rows(state)
    assert more_rows[:len(first_rows)] == first_rows
    assert update_ledger(ledger, more_rows, state.last_day) == len(more_rows) - len(first_rows)
    anchor = read_anchor(anchor_path(ledger))
    assert anchor.last_day == state.last_day and anchor.rows == len(more_rows)
    assert anchor.sha256 == hashlib.sha256(ledger.read_bytes()).hexdigest()


def test_ledger_rejects_rewriting_history(anchored):
    _, ledger, state, rows = anchored
    before = ledger.read_bytes()
    tampered = [row[:] for row in rows]
    tampered[0][5] = "1.0"  # precio distinto en una operación ya registrada
    with pytest.raises(LedgerIntegrityError, match="no reproduce"):
        update_ledger(ledger, tampered, state.last_day)
    assert ledger.read_bytes() == before  # el diario no se tocó


def test_truncated_ledger_is_detected(anchored):
    # Revisión de Codex de T019: borrar las últimas filas ya no pasa.
    _, ledger, state, rows = anchored
    lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
    ledger.write_text("".join(lines[:-1]), encoding="utf-8")
    with pytest.raises(LedgerIntegrityError, match="no coincide con su ancla"):
        update_ledger(ledger, rows, state.last_day)


def test_edited_ledger_is_detected(anchored):
    _, ledger, state, rows = anchored
    ledger.write_text(ledger.read_text(encoding="utf-8").replace("buy", "sell", 1),
                      encoding="utf-8")
    with pytest.raises(LedgerIntegrityError, match="no coincide con su ancla"):
        update_ledger(ledger, rows, state.last_day)


def test_new_rows_dated_in_simulated_period_are_rejected(anchored):
    # Revisión de Codex: una operación "nueva" con fecha ya simulada.
    _, ledger, state, rows = anchored
    stale = rows[-1][:]  # copia con la misma fecha de ejecución que la última fila
    with pytest.raises(LedgerIntegrityError, match="fecha ya simulada"):
        update_ledger(ledger, rows + [stale], state.last_day + timedelta(days=5))


def test_data_going_backwards_is_rejected(anchored):
    _, ledger, state, rows = anchored
    with pytest.raises(LedgerIntegrityError, match="antes del último día anclado"):
        update_ledger(ledger, rows, state.last_day - timedelta(days=1))


def test_missing_anchor_or_ledger_is_rejected(anchored):
    _, ledger, state, rows = anchored
    anchor_file = anchor_path(ledger)
    saved = anchor_file.read_bytes()
    anchor_file.unlink()
    with pytest.raises(LedgerIntegrityError, match="falta su ancla"):
        update_ledger(ledger, rows, state.last_day)
    anchor_file.write_bytes(saved)
    ledger.unlink()
    with pytest.raises(LedgerIntegrityError, match="falta el diario"):
        update_ledger(ledger, rows, state.last_day)


def test_init_anchor_requires_exact_reproduction(anchored):
    _, ledger, state, rows = anchored
    anchor_path(ledger).unlink()
    with pytest.raises(LedgerIntegrityError, match="sin filas nuevas"):
        update_ledger(ledger, rows + [rows[-1]], state.last_day, init_anchor=True)
    assert update_ledger(ledger, rows, state.last_day, init_anchor=True) == 0
    assert anchor_path(ledger).exists()


def test_ledger_rejects_unexpected_header(tmp_path):
    ledger = tmp_path / "ledger.csv"
    ledger.write_text("otra,cabecera\n", encoding="utf-8")
    with pytest.raises(LedgerIntegrityError, match="cabecera"):
        update_ledger(ledger, [], date(2026, 10, 1), init_anchor=True)


# --- puntos de control e informe ----------------------------------------------------------


def test_checkpoint_appears_only_when_reached(tmp_path):
    build_data(tmp_path / "a", 30, symbols=("BTCUSDT",))
    assert run_paper(tmp_path / "a", symbols=("BTCUSDT",)).checkpoints == []
    build_data(tmp_path / "b", 185, symbols=("BTCUSDT",))  # hasta 2027-04-03
    state = run_paper(tmp_path / "b", symbols=("BTCUSDT",))
    (checkpoint,) = state.checkpoints
    assert checkpoint.day == date(2027, 3, 31)
    assert checkpoint.assets[0].strategy.timestamps[-1].date() == date(2027, 3, 31)
    assert [day for _, day in state.pending] == [date(2027, 9, 30)]


def test_cli_writes_versionable_outputs(tmp_path, capsys):
    build_data(tmp_path / "data", 30)
    out = tmp_path / "paper"
    assert main(["--data", str(tmp_path / "data"), "--out", str(out)]) == 0
    text = (out / "report.md").read_text(encoding="utf-8")
    assert "Simulación sin dinero" in text and "D027" in text
    assert "Datos hasta: **2026-10-30**" in text
    assert "6 meses (preliminar) el 2027-03-31" in text
    assert all((out / name).exists() for name in ("ledger.csv", "equity.csv"))
    assert "sin dinero ni órdenes reales" in capsys.readouterr().out


def test_cli_is_reproducible(tmp_path):
    build_data(tmp_path / "data", 30)
    for name in ("a", "b"):
        main(["--data", str(tmp_path / "data"), "--out", str(tmp_path / name)])
    for file in ("report.md", "ledger.csv", "equity.csv"):
        assert (tmp_path / "a" / file).read_bytes() == (tmp_path / "b" / file).read_bytes()


def test_cli_reports_missing_data(tmp_path, capsys):
    assert main(["--data", str(tmp_path), "--out", str(tmp_path / "o")]) == 2
    assert "error:" in capsys.readouterr().err
