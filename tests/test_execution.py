"""Capa de ejecución local (D030, F1): sin red, sin claves, sin tocar paper/."""

import math
import shutil
import socket
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from bottrading.config import BacktestConfig
from bottrading.crossasset import CONFIG
from bottrading.data import Candle
from bottrading.execution import (
    BUDGET_PER_ASSET,
    MAX_EXPOSURE_AT_COST,
    Holding,
    LimitExceeded,
    OrderIntent,
    check_limits,
    client_order_id,
    decide,
    run_local,
)
from bottrading.paper import (
    SYMBOLS,
    ledger_rows,
    load_forward_candles,
    read_anchor,
    simulate,
)
from bottrading.strategy import Signal

from conftest import PAPER_DIR, NetworkBlocked

T0 = datetime(2026, 10, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def synthetic(n, phase=0.0, start=datetime(2025, 1, 1, tzinfo=timezone.utc)):
    candles = []
    for i in range(n):
        p = 100 * (1 + 0.3 * math.sin(i / 9 + phase) + 0.1 * math.sin(i / 2.3 + 2 * phase))
        o = p * (1 + 0.004 * math.cos(i + phase))
        candles.append(Candle(start + timedelta(days=i), o, max(o, p) * 1.01,
                              min(o, p) * 0.99, p, 1.0))
    return candles


# --- red bloqueada (conftest) ------------------------------------------------------


def test_network_is_blocked_during_tests():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 443))
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("example.com", 443)
    with socket.socket() as raw, pytest.raises(NetworkBlocked):
        raw.connect(("93.184.216.34", 443))


# --- clientOrderId -----------------------------------------------------------------


def test_client_order_id_is_deterministic_and_in_format():
    assert client_order_id("BTCUSDT", T0, Signal.BUY) == "bt-BTCUSDT-20261012-B"
    assert client_order_id("SOLUSDT", T0, Signal.SELL) == "bt-SOLUSDT-20261012-S"
    # el símbolo más largo admitido por el descargador (20) cabe en 36
    assert len(client_order_id("A" * 20, T0, Signal.BUY)) <= 36


def test_client_order_id_rejects_hold_and_bad_symbols():
    with pytest.raises(ValueError):
        client_order_id("BTCUSDT", T0, Signal.HOLD)
    with pytest.raises(ValueError):
        client_order_id("BTC/USDT", T0, Signal.BUY)
    with pytest.raises(ValueError):
        client_order_id("A" * 30, T0, Signal.BUY)


# --- decide ------------------------------------------------------------------------


def test_decide_follows_engine_semantics():
    flat, held = Holding(500.0), Holding(0.0, 2.0, 500.0)
    assert decide("BTCUSDT", Signal.BUY, T0, flat) == OrderIntent(
        "BTCUSDT", Signal.BUY, T0, quote_amount=500.0)
    assert decide("BTCUSDT", Signal.SELL, T0, held) == OrderIntent(
        "BTCUSDT", Signal.SELL, T0, quantity=2.0)
    assert decide("BTCUSDT", Signal.BUY, T0, held) is None
    assert decide("BTCUSDT", Signal.SELL, T0, flat) is None
    assert decide("BTCUSDT", Signal.HOLD, T0, flat) is None
    assert decide("BTCUSDT", Signal.BUY, T0, Holding(0.0)) is None


@pytest.mark.parametrize(("cash", "spend"), [(1200.0, 1000.0), (800.0, 800.0), (1000.0, 1000.0)])
def test_budget_is_not_reinvested(cash, spend):
    # D030: presupuesto no reinvertible; tras ganancia compra 1000, tras pérdida 800.
    intent = decide("ETHUSDT", Signal.BUY, T0, Holding(cash), budget=BUDGET_PER_ASSET)
    assert intent.quote_amount == spend


# --- límites -----------------------------------------------------------------------


def buy(symbol, amount, when=T0):
    return OrderIntent(symbol, Signal.BUY, when, quote_amount=amount)


def sell(symbol, quantity=1.0, when=T0):
    return OrderIntent(symbol, Signal.SELL, when, quantity=quantity)


@pytest.mark.parametrize(("amount", "ok"), [(999.99, True), (1000.0, True), (1000.01, False)])
def test_limit_per_order(amount, ok):
    if ok:
        check_limits([buy("BTCUSDT", amount)], {})
    else:
        with pytest.raises(LimitExceeded):
            check_limits([buy("BTCUSDT", amount)], {})


@pytest.mark.parametrize(("open_cost", "ok"), [(999.99, True), (1000.0, True), (1000.01, False)])
def test_limit_exposure_at_cost(open_cost, ok):
    holdings = {"BTCUSDT": Holding(0.0, 1.0, 1000.0), "ETHUSDT": Holding(0.0, 1.0, open_cost)}
    intents = [buy("SOLUSDT", 1000.0)]
    assert MAX_EXPOSURE_AT_COST == 3000.0
    if ok:
        check_limits(intents, holdings)
    else:
        with pytest.raises(LimitExceeded, match="exposición"):
            check_limits(intents, holdings)


def test_selling_frees_exposure_the_same_day():
    holdings = {"BTCUSDT": Holding(0.0, 1.0, 1000.0), "ETHUSDT": Holding(0.0, 1.0, 1500.0)}
    check_limits([sell("ETHUSDT"), buy("SOLUSDT", 1000.0)], holdings)


def test_limit_orders_per_symbol_and_per_day():
    check_limits([buy("BTCUSDT", 10), buy("ETHUSDT", 10), buy("SOLUSDT", 10)], {})
    with pytest.raises(LimitExceeded, match="por símbolo"):
        check_limits([buy("BTCUSDT", 10), sell("BTCUSDT")], {})
    with pytest.raises(LimitExceeded):
        check_limits([buy("BTCUSDT", 10), buy("ETHUSDT", 10), buy("SOLUSDT", 10),
                      sell("BTCUSDT")], {})


def test_limit_symbols_and_single_day():
    with pytest.raises(LimitExceeded, match="no permitidos"):
        check_limits([buy("BNBUSDT", 10)], {})
    with pytest.raises(LimitExceeded, match="varios días"):
        check_limits([buy("BTCUSDT", 10), buy("ETHUSDT", 10, T0 + timedelta(days=1))], {})
    with pytest.raises(LimitExceeded):
        check_limits([OrderIntent("BTCUSDT", Signal.BUY, T0)], {})


# --- paridad con paper (D027) ------------------------------------------------------


@pytest.mark.parametrize("phase", [0.0, 0.7, 1.9, 3.1])
@pytest.mark.parametrize("start", [60, 140, 233])
def test_run_local_reproduces_paper_simulation_exactly(phase, start):
    candles = synthetic(320, phase)
    expected = simulate("BTCUSDT", candles, start).strategy
    run = run_local("BTCUSDT", candles, start)
    assert run.trades == expected.trades  # igualdad exacta de floats
    assert run.holding.cash == expected.final_cash
    assert run.holding.quantity == expected.final_quantity
    assert len(run.trades) >= 2


def test_run_local_with_end_matches_truncated_simulation():
    candles = synthetic(320, 1.3)
    assert run_local("ETHUSDT", candles, 100, 250).trades == \
        simulate("ETHUSDT", candles, 100, 250).strategy.trades


def test_run_local_with_budget_caps_buys_and_keeps_gains_idle():
    candles = synthetic(400, 0.4)
    run = run_local("SOLUSDT", candles, 60, budget=BUDGET_PER_ASSET)
    buys = [t for t in run.trades if t.side is Signal.BUY]
    assert buys and all(t.quantity * t.price + t.fee <= BUDGET_PER_ASSET + 1e-9 for t in buys)
    assert run.trades[0].cash_after == CONFIG.initial_capital - BUDGET_PER_ASSET


def test_run_local_rejects_partial_position_fraction_and_bad_segment():
    candles = synthetic(100)
    with pytest.raises(ValueError, match="max_position_fraction"):
        run_local("BTCUSDT", candles, 60,
                  config=BacktestConfig(10_000.0, max_position_fraction=0.5))
    with pytest.raises(ValueError, match="segmento"):
        run_local("BTCUSDT", candles, 100)


def test_real_ledger_parity_on_a_copy(tmp_path):
    """Con los datos reales descargados (si existen), las operaciones de
    run_local reproducen byte a byte una COPIA de paper/ledger.csv hasta
    el día del ancla. No escribe en paper/."""
    data = ROOT / "data"
    ledger = tmp_path / "ledger.csv"
    if not all((data / f"{s}-1d-daily").is_dir() for s in SYMBOLS):
        pytest.skip("sin datos reales descargados en data/")
    shutil.copyfile(PAPER_DIR / "ledger.csv", ledger)
    shutil.copyfile(PAPER_DIR / "ledger.state", tmp_path / "ledger.state")
    last_day = read_anchor(tmp_path / "ledger.state").last_day

    assets = []
    for symbol in SYMBOLS:
        candles, start = load_forward_candles(data / f"{symbol}-1d", data / f"{symbol}-1d-daily")
        days = [c.timestamp.date() for c in candles]
        if last_day not in days:
            pytest.skip(f"data/ no llega a {last_day}")
        run = run_local(symbol, candles, start, days.index(last_day) + 1)
        assets.append(SimpleNamespace(symbol=symbol, strategy=SimpleNamespace(trades=run.trades)))
    rows = ledger_rows(SimpleNamespace(assets=assets))
    expected = [line.split(",") for line in ledger.read_text(encoding="utf-8").splitlines()[1:]]
    assert rows == expected
    assert isinstance(last_day, date)
