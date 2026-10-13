import csv
from datetime import datetime, timedelta, timezone

import pytest

from bottrading.__main__ import main
from bottrading.backtest import run_backtest
from bottrading.config import BacktestConfig
from bottrading.data import load_ohlcv_csv
from bottrading.report import DISCLAIMER, file_sha256, write_report
from bottrading.strategy import buy_and_hold_signals, crossover_signals

START = datetime(2024, 1, 1, tzinfo=timezone.utc)
# Serie sintética: baja, sube y baja, con suficientes velas para señales.
PRICES = [100 - i for i in range(10)] + [91 + 2 * i for i in range(15)] + [
    119 - 3 * i for i in range(10)
]


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "prices.csv"
    lines = ["timestamp,open,high,low,close,volume"]
    for i, price in enumerate(PRICES):
        ts = (START + timedelta(hours=i)).isoformat()
        lines.append(f"{ts},{price},{price + 1},{price - 1},{price},10")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_report(csv_path, out_dir, config=None):
    config = config or BacktestConfig(initial_capital=1000)
    candles = load_ohlcv_csv(csv_path)
    closes = [c.close for c in candles]
    strategy = run_backtest(candles, crossover_signals(closes, 3, 6), config)
    benchmark = run_backtest(candles, buy_and_hold_signals(len(candles)), config)
    paths = write_report(
        out_dir, data_path=csv_path, candles=candles, fast=3, slow=6,
        strategy=strategy, benchmark=benchmark,
    )
    return paths, strategy, benchmark


def test_report_files_are_written(csv_path, tmp_path):
    paths, _, _ = build_report(csv_path, tmp_path / "out")
    assert set(paths) == {"report", "trades", "equity"}
    assert all(path.exists() for path in paths.values())


def test_report_is_byte_reproducible(csv_path, tmp_path):
    first, _, _ = build_report(csv_path, tmp_path / "a")
    second, _, _ = build_report(csv_path, tmp_path / "b")
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()


def test_report_content(csv_path, tmp_path):
    paths, strategy, _ = build_report(csv_path, tmp_path / "out")
    text = paths["report"].read_text(encoding="utf-8")
    assert DISCLAIMER in text
    assert file_sha256(csv_path) in text
    assert f"Velas: {len(PRICES)}" in text
    assert "rápida 3, lenta 6" in text
    assert "| Retorno total (neto) |" in text
    assert "Costes estimados de liquidación" in text
    assert "## Limitaciones" in text
    assert strategy.trades, "la serie de prueba debe generar operaciones"


def test_unavailable_metrics_are_shown_as_nd(csv_path, tmp_path):
    # 35 velas horarias cubren menos de un año: el retorno anualizado
    # debe aparecer como n/d, con su nota.
    paths, _, _ = build_report(csv_path, tmp_path / "out")
    text = paths["report"].read_text(encoding="utf-8")
    assert "| Retorno anualizado | n/d | n/d |" in text
    assert "annualized_return no disponible" in text


def test_trades_csv_matches_result(csv_path, tmp_path):
    paths, strategy, _ = build_report(csv_path, tmp_path / "out")
    with paths["trades"].open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(strategy.trades)
    for row, trade in zip(rows, strategy.trades):
        assert row["side"] == trade.side.value
        assert float(row["price"]) == trade.price
        assert float(row["fee"]) == trade.fee


def test_equity_csv_has_both_curves(csv_path, tmp_path):
    paths, strategy, benchmark = build_report(csv_path, tmp_path / "out")
    with paths["equity"].open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(PRICES)
    assert [float(r["strategy_equity"]) for r in rows] == strategy.equity
    assert [float(r["buy_and_hold_equity"]) for r in rows] == benchmark.equity


def test_report_rejects_empty_candles(tmp_path):
    empty = run_backtest([], [], BacktestConfig(initial_capital=1000))
    with pytest.raises(ValueError, match="sin velas"):
        write_report(tmp_path, data_path=tmp_path / "x.csv", candles=[], fast=1,
                     slow=2, strategy=empty, benchmark=empty)


# --- línea de comandos -----------------------------------------------------------


def test_cli_writes_report(csv_path, tmp_path, capsys):
    out_dir = tmp_path / "cli"
    code = main(["--csv", str(csv_path), "--fast", "3", "--slow", "6",
                 "--capital", "1000", "--out", str(out_dir)])
    assert code == 0
    assert (out_dir / "report.md").exists()
    assert "Simulación educativa" in capsys.readouterr().out


def test_cli_matches_library_output(csv_path, tmp_path):
    out_dir = tmp_path / "cli"
    main(["--csv", str(csv_path), "--fast", "3", "--slow", "6",
          "--capital", "1000", "--out", str(out_dir)])
    paths, _, _ = build_report(csv_path, tmp_path / "lib")
    for key, path in paths.items():
        assert (out_dir / path.name).read_bytes() == path.read_bytes(), key


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--fast", "6", "--slow", "3"], "menor que slow"),
        (["--commission", "-0.1"], "commission_rate"),
        (["--position-fraction", "2"], "max_position_fraction"),
        (["--capital", "0"], "initial_capital"),
    ],
)
def test_cli_rejects_invalid_configuration(csv_path, tmp_path, capsys, args, message):
    code = main(["--csv", str(csv_path), "--out", str(tmp_path / "o"), *args])
    assert code == 2
    assert message in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_cli_reports_invalid_csv(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("timestamp,open\n2024-01-01T00:00:00Z,1\n", encoding="utf-8")
    assert main(["--csv", str(bad), "--out", str(tmp_path / "o")]) == 2
    assert "faltan columnas" in capsys.readouterr().err


def test_cli_reports_missing_file(tmp_path, capsys):
    assert main(["--csv", str(tmp_path / "nope.csv"), "--out", str(tmp_path / "o")]) == 2
    assert "error:" in capsys.readouterr().err
