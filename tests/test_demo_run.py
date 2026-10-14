"""F4 (aprobación (b) de D030): órdenes demo con un exchange simulado. Sin red."""

import json
import math
import urllib.parse
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

import pytest

from bottrading.demo_client import (
    ORDERS_ENV,
    Credentials,
    DemoApiError,
    DemoClient,
    DemoGateway,
    DemoPaths,
    RequestRefused,
    Response,
    main,
    order_amounts,
)
from bottrading.demo_ledger import (
    DuplicateOrder,
    GatewayRejected,
    GatewayUnknown,
    OrderLedger,
    OrderStatus,
)
from bottrading.execution import (
    Holding,
    LimitExceeded,
    OrderIntent,
    check_limits,
    target_intents,
)
from bottrading.strategy import Signal

from test_paper import build_data

API_KEY = "FAKEapiKEY0123456789abcdefABCDEF"
SECRET = "FAKEsecret9876543210zyxwvuZYXWVU"
TODAY = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
NOW = TODAY.timestamp()
STEPS = {"BTCUSDT": Decimal("0.00001"), "ETHUSDT": Decimal("0.0001"), "SOLUSDT": Decimal("0.001")}
BASES = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL"}
DAY = datetime(2026, 10, 12, tzinfo=timezone.utc)


def credentials():
    return Credentials(API_KEY, SECRET)


class Exchange:
    """Exchange demo simulado y coherente (órdenes, fills, saldos) tras la API."""

    def __init__(self, price=Decimal("100")):
        self.price = price
        self.balances = {"USDT": Decimal("5000"), "USDC": Decimal("5000"), "BNB": Decimal("1")}
        self.orders = {s: [] for s in STEPS}
        self.trades = {s: [] for s in STEPS}
        self.calls, self.next_id = [], 1
        self.fail_post = None  # (status, body) para simular errores

    def __call__(self, request, headers):
        parts = urllib.parse.urlsplit(request.url)
        params = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((request.method, parts.path))
        status, body = self.answer(request.method, parts.path, params)
        return Response(status, json.dumps(body).encode(), request.url)

    def answer(self, method, path, params):
        symbol = params.get("symbol")
        if path == "/api/v3/time":
            return 200, {"serverTime": int(NOW * 1000)}
        if path == "/api/v3/exchangeInfo":
            return 200, {"symbols": [{"symbol": symbol, "baseAsset": BASES[symbol],
                                      "quoteAsset": "USDT", "filters": [
                                          {"filterType": "LOT_SIZE",
                                           "stepSize": str(STEPS[symbol])}]}]}
        if path == "/api/v3/account":
            return 200, {"canTrade": True, "balances": [
                {"asset": a, "free": str(v), "locked": "0"} for a, v in self.balances.items() if v]}
        if path == "/api/v3/openOrders":
            return 200, []
        if path == "/api/v3/allOrders":
            return 200, [o for o in self.orders[symbol] if o["orderId"] >= int(params["orderId"])]
        if path == "/api/v3/myTrades":
            return 200, [t for t in self.trades[symbol] if t["id"] >= int(params["fromId"])]
        if path == "/api/v3/order" and method == "GET":
            found = [o for o in self.orders[symbol]
                     if o["clientOrderId"] == params["origClientOrderId"]]
            return (200, found[-1]) if found else (400, {"code": -2013, "msg": "x"})
        if path == "/api/v3/order" and method == "POST":
            return self.post(params)
        raise AssertionError(f"petición inesperada {method} {path}")

    def post(self, params):
        if self.fail_post:
            return self.fail_post
        symbol, side = params["symbol"], params["side"]
        step, base = STEPS[symbol], BASES[symbol]
        if side == "BUY":
            qty = (Decimal(params["quoteOrderQty"]) / self.price / step).to_integral_value(
                rounding=ROUND_DOWN) * step
        else:
            qty = Decimal(params["quantity"])
        quote = qty * self.price
        order_id = self.next_id
        self.next_id += 1
        order = {"symbol": symbol, "orderId": order_id, "clientOrderId": params["newClientOrderId"],
                 "status": "FILLED", "side": side, "executedQty": str(qty),
                 "cummulativeQuoteQty": str(quote)}
        self.orders[symbol].append(order)
        fee = Decimal("0.001")
        self.trades[symbol].append({"symbol": symbol, "id": 100 + order_id, "orderId": order_id,
                                    "qty": str(qty), "quoteQty": str(quote),
                                    "commission": str(fee), "commissionAsset": "BNB"})
        sign = 1 if side == "BUY" else -1
        self.balances[base] = self.balances.get(base, Decimal(0)) + sign * qty
        self.balances["USDT"] -= sign * quote
        self.balances["BNB"] -= fee
        return 200, order

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


@pytest.fixture
def world(tmp_path):
    data = tmp_path / "data"
    build_data(data, forward_days=13)  # velas cerradas hasta 2026-10-13 (ayer)
    paths = DemoPaths(tmp_path / "estado" / "orders.csv", tmp_path / "estado" / "baseline.json",
                      tmp_path / "estado" / "STOP")
    exchange = Exchange()
    return data, paths, exchange


def run(world, command="run", *flags, env=None, answer="INICIALIZAR"):
    data, paths, exchange = world
    lines = []
    code = main([command, *flags], credentials=credentials, transport=exchange,
                clock=lambda: NOW, paths=paths, ask=lambda prompt: answer, out=lines.append,
                environ=env or {}, data_dir=data, sleep=lambda s: None)
    text = "\n".join(lines)
    assert API_KEY not in text and SECRET not in text and "signature" not in text
    return code, text


def expected_intents(data):
    from bottrading.paper import load_forward_candles
    candles = {s: load_forward_candles(data / f"{s}-1d", data / f"{s}-1d-daily")[0]
               for s in STEPS}
    return target_intents(candles, {s: Holding(1000.0) for s in STEPS})


# --- consentimiento y modo simulación ------------------------------------------------


@pytest.mark.parametrize(("flags", "env"), [
    ((), {}), (("--send-orders",), {}), ((), {ORDERS_ENV: "1"}),
    (("--send-orders",), {ORDERS_ENV: "true"}),
])
def test_without_both_consents_run_only_simulates(world, flags, env):
    assert run(world, "init")[0] == 0
    code, text = run(world, "run", *flags, env=env)
    assert code == 0 and "simulación" in text
    assert world[2].posts() == []


def test_run_sends_aligns_and_repeating_sends_zero(world):
    data, paths, exchange = world
    assert run(world, "init")[0] == 0
    planned = expected_intents(data)
    assert planned, "los datos sintéticos deben producir al menos una orden"
    code, text = run(world, "run", "--send-orders", env={ORDERS_ENV: "1"})
    assert code == 0, text
    assert len(exchange.posts()) == len(planned)
    assert "Reconciliación posterior: OK" in text
    for intent in planned:
        assert intent.client_order_id in text
    # repetir el mismo día (y otro día con los mismos datos) no envía nada nuevo
    code, text = run(world, "run", "--send-orders", env={ORDERS_ENV: "1"})
    assert code == 0 and len(exchange.posts()) == len(planned), text
    assert "Sin órdenes" in text


def test_kill_switch_and_stale_data_block_before_any_order(world, tmp_path):
    data, paths, exchange = world
    assert run(world, "init")[0] == 0
    paths.kill_switch.write_text("", encoding="utf-8")
    code, text = run(world, "run", "--send-orders", env={ORDERS_ENV: "1"})
    assert code == 1 and "kill switch" in text and exchange.posts() == []
    paths.kill_switch.unlink()
    stale = tmp_path / "viejos"
    build_data(stale, forward_days=12)  # solo hasta 2026-10-12
    lines = []
    code = main(["run", "--send-orders"], credentials=credentials, transport=exchange,
                clock=lambda: NOW, paths=paths, out=lines.append,
                environ={ORDERS_ENV: "1"}, data_dir=stale, sleep=lambda s: None)
    assert code == 1 and "ejecuta antes la descarga" in "\n".join(lines)
    assert exchange.posts() == []


def test_rejected_order_is_final_and_reconciliation_still_runs(world):
    data, paths, exchange = world
    assert run(world, "init")[0] == 0
    exchange.fail_post = (400, {"code": -2010, "msg": "Account has insufficient balance."})
    code, text = run(world, "run", "--send-orders", env={ORDERS_ENV: "1"})
    assert code == 0 and "FINAL REJECTED" in text
    exchange.fail_post = None
    run(world, "run", "--send-orders", env={ORDERS_ENV: "1"})  # mismo id: no se reintenta
    assert len(exchange.posts()) == len(expected_intents(data))


def test_unknown_outcome_stops_without_resending(world):
    data, paths, exchange = world
    assert run(world, "init")[0] == 0
    exchange.fail_post = (503, {"code": -1007, "msg": "timeout"})
    code, text = run(world, "run", "--send-orders", env={ORDERS_ENV: "1"})
    assert code == 1 and "adjudicación" in text
    first = len(exchange.posts())
    code, text = run(world, "run", "--send-orders", env={ORDERS_ENV: "1"})
    assert code == 1 and len(exchange.posts()) == first  # nunca se reenvía
    code, text = run(world, "run")  # sin envío: se niega a seguir con pendientes
    assert code == 1 and "sin resolver" in text


# --- piezas puras ---------------------------------------------------------------------


def test_order_amounts_round_down_deterministically():
    buy = OrderIntent("BTCUSDT", Signal.BUY, DAY, quote_amount=999.999)
    assert order_amounts(buy, STEPS["BTCUSDT"]) == (None, "999.99")
    sell = OrderIntent("ETHUSDT", Signal.SELL, DAY, quantity=0.123456789)
    assert order_amounts(sell, STEPS["ETHUSDT"]) == ("0.1234", None)
    tiny = OrderIntent("SOLUSDT", Signal.SELL, DAY, quantity=0.0004)
    assert order_amounts(tiny, STEPS["SOLUSDT"]) == ("0", None)


def candles_from(closes):
    from bottrading.data import Candle
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle(start + timedelta(days=i), c, c * 1.01, c * 0.99, c, 1.0)
            for i, c in enumerate(closes)]


def test_target_intents_follow_the_last_signal_with_its_date():
    rising = candles_from([100 - i * 0.5 for i in range(60)] + [200, 201, 202])
    falling = candles_from([100 + i * 0.5 for i in range(60)] + [10, 9, 8])
    flat = {s: Holding(1000.0) for s in STEPS}
    holding = {**flat, "ETHUSDT": Holding(0.0, 2.0, 900.0)}
    intents = target_intents({"BTCUSDT": rising, "ETHUSDT": falling}, holding)
    by_symbol = {i.symbol: i for i in intents}
    assert by_symbol["BTCUSDT"].side is Signal.BUY
    assert by_symbol["BTCUSDT"].signal_time == rising[60].timestamp  # fecha del cruce
    assert by_symbol["BTCUSDT"].quote_amount == 1000.0
    assert by_symbol["ETHUSDT"].side is Signal.SELL and by_symbol["ETHUSDT"].quantity == 2.0
    # ya alineado: nada que hacer; sin señales: nada
    assert target_intents({"BTCUSDT": rising}, {"BTCUSDT": Holding(0.0, 1.0, 1000.0)}) == []
    assert target_intents({"BTCUSDT": candles_from([100.0] * 10)}, flat) == []


def test_check_limits_by_execution_day_allows_mixed_signal_dates():
    a = OrderIntent("BTCUSDT", Signal.BUY, DAY, quote_amount=500.0)
    b = OrderIntent("ETHUSDT", Signal.BUY, DAY - timedelta(days=40), quote_amount=500.0)
    holdings = {s: Holding(1000.0) for s in STEPS}
    with pytest.raises(LimitExceeded, match="varios días"):
        check_limits([a, b], holdings)
    check_limits([a, b], holdings, execution_day=TODAY.date())
    with pytest.raises(LimitExceeded, match="por símbolo"):
        check_limits([a], holdings, [a], execution_day=TODAY.date())


def test_ledger_reports_orders_recorded_on_the_execution_day(tmp_path):
    clock = lambda: TODAY  # noqa: E731
    with OrderLedger(tmp_path / "orders.csv", clock, create=True) as ledger:
        intent = OrderIntent("BTCUSDT", Signal.BUY, DAY - timedelta(days=50), quote_amount=10.0)
        ledger.append(intent, "INTENT")
        ledger.append(intent, "SENT")
        assert ledger.orders_recorded_on(TODAY.date()) == [intent]
        assert ledger.orders_recorded_on(TODAY.date() - timedelta(days=1)) == []


# --- adaptador ------------------------------------------------------------------------


class Scripted:
    """Transporte que devuelve respuestas fijas por método."""

    def __init__(self, get=None, post=None):
        self.get, self.post = get, post

    def __call__(self, request, headers):
        status, body = self.post if request.method == "POST" else self.get
        return Response(status, json.dumps(body).encode(), request.url)


def gateway(get=None, post=None):
    client = DemoClient(credentials, Scripted(get, post), lambda: NOW, trading=True)
    return DemoGateway(client, STEPS)


BUY = OrderIntent("BTCUSDT", Signal.BUY, DAY, quote_amount=1000.0)


def test_gateway_query_maps_absence_unknown_and_status():
    assert gateway(get=(400, {"code": -2013, "msg": "x"})).query(BUY) is None
    with pytest.raises(GatewayUnknown):
        gateway(get=(500, {})).query(BUY)
    with pytest.raises(GatewayUnknown):
        gateway(get=(429, {"code": -1003})).query(BUY)
    status = gateway(get=(200, {"status": "FILLED", "executedQty": "0.01000000"})).query(BUY)
    assert status == OrderStatus("FILLED", 0.01)


@pytest.mark.parametrize(("post", "error"), [
    ((400, {"code": -2010, "msg": "Duplicate order sent."}), DuplicateOrder),
    ((400, {"code": -2010, "msg": "Account has insufficient balance."}), GatewayRejected),
    ((400, {"code": -1013, "msg": "Filter failure: NOTIONAL"}), GatewayRejected),
    ((503, {"code": -1007, "msg": "timeout"}), GatewayUnknown),
    ((429, {"code": -1003}), GatewayUnknown),
    ((418, {}), GatewayUnknown),
    ((200, {"status": "FILLED"}), GatewayUnknown),  # respuesta incompleta
])
def test_gateway_submit_follows_the_d030_contract(post, error):
    with pytest.raises(error):
        gateway(post=post).submit(BUY)


def test_gateway_errors_keep_no_context():
    with pytest.raises(GatewayRejected) as info:
        gateway(post=(400, {"code": -2010, "msg": "x"})).submit(BUY)
    assert info.value.__context__ is None and info.value.__cause__ is None


@pytest.mark.parametrize(("params", "ok"), [
    ({"side": "BUY", "quote_order_qty": "10.5"}, True),
    ({"side": "SELL", "quantity": "0.001"}, True),
    ({"side": "BUY", "quantity": "0.001"}, False),  # compra por cantidad
    ({"side": "SELL", "quote_order_qty": "10"}, False),  # venta por USDT
    ({"side": "BUY", "quote_order_qty": "0"}, False),
    ({"side": "BUY", "quote_order_qty": "1e3"}, False),
    ({"side": "BUY", "quote_order_qty": "10", "quantity": "1"}, False),
    ({"side": "HOLD", "quote_order_qty": "10"}, False),
])
def test_order_parameters_are_validated_before_the_transport(params, ok):
    def must_not_send(request, headers):
        raise AssertionError("no debía enviarse")
    client = DemoClient(credentials, must_not_send if not ok else Scripted(
        post=(200, {"status": "FILLED", "executedQty": "1"})), lambda: NOW, trading=True)
    side = params.pop("side")
    call = lambda: client.new_market_order("BTCUSDT", side, "bt-BTCUSDT-20261012-B",  # noqa: E731
                                          **params)
    if ok:
        call()
    else:
        with pytest.raises(RequestRefused):
            call()


def test_order_ids_and_types_are_closed():
    client = DemoClient(credentials, Scripted(post=(200, {})), lambda: NOW, trading=True)
    for bad_id in ("manual-1", "bt-x y", ""):
        with pytest.raises(RequestRefused):
            client.new_market_order("BTCUSDT", "BUY", bad_id, quote_order_qty="10")
    with pytest.raises(RequestRefused):
        client.new_market_order("BNBUSDT", "BUY", "bt-BNBUSDT-20261012-B", quote_order_qty="10")
    assert math.isfinite(NOW) and isinstance(DemoApiError("GET", "/x", 400).duplicate, bool)
