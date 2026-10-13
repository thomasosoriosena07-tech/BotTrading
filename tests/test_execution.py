"""Capa de ejecución local (D030, F1): sin red, sin claves, sin tocar paper/."""

import math
import shutil
import socket
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from bottrading.config import BacktestConfig
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
from bottrading.paper import _render_ledger
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
    with pytest.raises(NetworkBlocked):
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP: ni siquiera se crea
    with pytest.raises(NetworkBlocked):
        socket.socket()
    with pytest.raises(NetworkBlocked):
        socket.socketpair()
    # envío y conexión parcheados también en la clase (sockets ya creados)
    for method in ("sendto", "sendmsg", "connect", "connect_ex"):
        with pytest.raises(NetworkBlocked):
            getattr(socket.socket, method)(None, ("192.0.2.1", 53))


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


FLAT = {s: Holding(2000.0) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}


@pytest.mark.parametrize(("amount", "ok"), [(999.99, True), (1000.0, True), (1000.01, False)])
def test_limit_per_order(amount, ok):
    if ok:
        check_limits([buy("BTCUSDT", amount)], FLAT)
    else:
        with pytest.raises(LimitExceeded, match="máximo"):
            check_limits([buy("BTCUSDT", amount)], FLAT)


@pytest.mark.parametrize(("open_cost", "ok"), [(999.99, True), (1000.0, True), (1000.01, False)])
def test_limit_exposure_at_cost(open_cost, ok):
    holdings = {"BTCUSDT": Holding(0.0, 1.0, 1000.0), "ETHUSDT": Holding(0.0, 1.0, open_cost),
                "SOLUSDT": Holding(1000.0)}
    intents = [buy("SOLUSDT", 1000.0)]
    assert MAX_EXPOSURE_AT_COST == 3000.0
    if ok:
        check_limits(intents, holdings)
    else:
        with pytest.raises(LimitExceeded, match="exposición"):
            check_limits(intents, holdings)


def test_same_day_sell_does_not_free_exposure():
    # Conservador (revisión de Codex): la venta aún no consta confirmada.
    holdings = {"BTCUSDT": Holding(0.0, 1.0, 1000.0), "ETHUSDT": Holding(0.0, 2.0, 1000.01),
                "SOLUSDT": Holding(1000.0)}
    with pytest.raises(LimitExceeded, match="exposición"):
        check_limits([sell("ETHUSDT", 2.0), buy("SOLUSDT", 1000.0)], holdings)


def test_limit_orders_per_symbol_and_per_day():
    check_limits([buy("BTCUSDT", 10), buy("ETHUSDT", 10), buy("SOLUSDT", 10)], FLAT)
    with pytest.raises(LimitExceeded, match="por símbolo"):
        check_limits([buy("BTCUSDT", 10), buy("BTCUSDT", 10)], FLAT)
    with pytest.raises(LimitExceeded):
        check_limits([buy("BTCUSDT", 10), buy("ETHUSDT", 10), buy("SOLUSDT", 10),
                      buy("BTCUSDT", 10)], FLAT)


def test_limits_are_cumulative_with_orders_already_recorded_today():
    # Revisión de Codex: dos llamadas el mismo día no pueden sumar más.
    done = [buy("BTCUSDT", 10)]
    check_limits([buy("ETHUSDT", 10)], FLAT, already_today=done)
    with pytest.raises(LimitExceeded, match="por símbolo"):
        check_limits([buy("BTCUSDT", 10)], FLAT, already_today=done)
    with pytest.raises(LimitExceeded):  # 4.ª orden del día (y 2.ª de SOL)
        check_limits([sell("SOLUSDT")], {"SOLUSDT": Holding(0.0, 1.0, 10.0), **FLAT},
                     already_today=[buy("BTCUSDT", 10), buy("ETHUSDT", 10), buy("SOLUSDT", 10)])
    # una compra registrada pero aún sin ejecutar cuenta en la exposición
    holdings = {"BTCUSDT": Holding(0.0, 1.0, 1000.0), "ETHUSDT": Holding(1000.0),
                "SOLUSDT": Holding(1000.0)}
    with pytest.raises(LimitExceeded, match="exposición"):
        check_limits([buy("SOLUSDT", 1000.0)], holdings, already_today=[buy("ETHUSDT", 1000.01)])


def test_intents_must_match_the_confirmed_position():
    held = {"BTCUSDT": Holding(0.0, 2.0, 900.0), "ETHUSDT": Holding(500.0)}
    check_limits([sell("BTCUSDT", 2.0)], held)
    with pytest.raises(LimitExceeded, match="venta"):
        check_limits([sell("BTCUSDT", 3.0)], held)
    with pytest.raises(LimitExceeded, match="venta"):
        check_limits([sell("ETHUSDT", 1.0)], held)  # sin posición
    with pytest.raises(LimitExceeded, match="posición abierta"):
        check_limits([buy("BTCUSDT", 10)], held)
    with pytest.raises(LimitExceeded, match="efectivo"):
        check_limits([buy("ETHUSDT", 500.01)], held)
    with pytest.raises(LimitExceeded, match="efectivo"):
        check_limits([buy("SOLUSDT", 1.0)], held)  # activo sin efectivo en el ledger


def test_limit_symbols_and_single_day():
    with pytest.raises(LimitExceeded, match="no permitidos"):
        check_limits([buy("BNBUSDT", 10)], FLAT)
    with pytest.raises(LimitExceeded, match="varios días"):
        check_limits([buy("BTCUSDT", 10), buy("ETHUSDT", 10, T0 + timedelta(days=1))], FLAT)
    with pytest.raises(LimitExceeded):
        check_limits([OrderIntent("BTCUSDT", Signal.BUY, T0)], FLAT)
    with pytest.raises(LimitExceeded, match="sin lado"):
        check_limits([OrderIntent("BTCUSDT", Signal.HOLD, T0)], FLAT)


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


@pytest.mark.parametrize("phase", [0.0, 0.4, 1.9, 3.1])
def test_run_local_budget_starts_at_budget_and_never_reinvests(phase):
    # Revisión de Codex: el efectivo D030 empieza en 1000, no en el capital
    # de paper; cada compra gasta min(efectivo, 1000).
    run = run_local("SOLUSDT", synthetic(500, phase), 60, budget=BUDGET_PER_ASSET)
    cash = BUDGET_PER_ASSET
    for trade in run.trades:
        if trade.side is Signal.BUY:
            assert cash - trade.cash_after == min(cash, BUDGET_PER_ASSET)
        cash = trade.cash_after
    assert run.holding.cash == cash
    assert len(run.trades) >= 4


def test_run_local_budget_rebuy_after_a_loss_uses_remaining_cash():
    # compra, venta con pérdida y recompra con lo que queda (< 1000)
    found = False
    for phase in (0.0, 0.4, 0.7, 1.3, 1.9, 2.5, 3.1):
        trades = run_local("SOLUSDT", synthetic(500, phase), 60, budget=BUDGET_PER_ASSET).trades
        for before, after in zip(trades, trades[1:]):
            if before.side is Signal.SELL and before.cash_after < BUDGET_PER_ASSET:
                assert after.side is Signal.BUY and after.cash_after == 0.0
                found = True
    assert found


def test_run_local_validates_candles_and_signals_like_the_engine():
    candles = synthetic(100)
    broken = candles[:50] + [replace(candles[50], open=-1.0)] + candles[51:]
    with pytest.raises(ValueError, match="precios"):
        run_local("BTCUSDT", broken, 60)
    with pytest.raises(ValueError, match="señales"):
        run_local("BTCUSDT", candles, 60, signal_function=lambda closes: [Signal.HOLD])
    with pytest.raises(ValueError, match="tipo"):
        run_local("BTCUSDT", candles, 60, signal_function=lambda closes: ["buy"] * len(closes))


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
    # Byte a byte con el mismo serializador del diario (revisión de Codex).
    assert _render_ledger(rows) == ledger.read_bytes()
    assert isinstance(last_day, date)
