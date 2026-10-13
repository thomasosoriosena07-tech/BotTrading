"""Reconciliación de la cuenta demo (D030, F2b-2) con datos sintéticos, sin red."""

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from decimal import Decimal

import pytest

from bottrading.demo_ledger import (
    CoverageProof,
    OrderLedger,
    OrderStatus,
    StopTheDay,
    adjudicate_not_sent,
    execute_intent,
)
from bottrading.demo_reconcile import (
    PAGE_LIMIT,
    Baseline,
    History,
    SymbolInfo,
    baseline_from,
    fetch_after,
    load_baseline,
    reconcile,
    reconcile_data,
    save_baseline,
    symbol_info,
)
from bottrading.execution import BUDGET_PER_ASSET, OrderIntent, check_limits
from bottrading.strategy import Signal

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DAY = datetime(2026, 10, 12, tzinfo=timezone.utc)
CLOCK = lambda: datetime(2026, 10, 13, tzinfo=timezone.utc)  # noqa: E731
INFOS = {"BTCUSDT": SymbolInfo("BTCUSDT", "BTC", Decimal("0.00001")),
         "ETHUSDT": SymbolInfo("ETHUSDT", "ETH", Decimal("0.0001")),
         "SOLUSDT": SymbolInfo("SOLUSDT", "SOL", Decimal("0.001"))}
BASE_BALANCES = {"USDT": Decimal("5000"), "BNB": Decimal("1"), "LTC": Decimal("3")}
BASELINE = Baseline(date(2026, 10, 1), dict(BASE_BALANCES),
                    {s: 0 for s in SYMBOLS}, {s: 0 for s in SYMBOLS})
BUY = OrderIntent("BTCUSDT", Signal.BUY, DAY, quote_amount=1000.0)


def no_sleep(seconds):
    pass


class Exchange:
    """Servidor simulado coherente: órdenes, fills y saldos."""

    def __init__(self, fee_asset="BTC"):
        self.orders, self.status = {s: [] for s in SYMBOLS}, {}
        self.trades = {s: [] for s in SYMBOLS}
        self.balances = dict(BASE_BALANCES)
        self.fee_asset, self.next_id = fee_asset, 1

    # interfaz Gateway (para crear órdenes reales del registro en las pruebas)
    def query(self, intent):
        return self.status.get(intent.client_order_id)

    def submit(self, intent):
        price, qty = Decimal("50000"), Decimal("0.01998")
        quote = qty * price  # 999.00 USDT
        self.fill(intent.symbol, intent.client_order_id, "BUY", qty, quote, Decimal("0.00001998"))
        self.status[intent.client_order_id] = OrderStatus("FILLED", float(qty))
        return self.status[intent.client_order_id]

    def fill(self, symbol, client_id, side, qty, quote, fee, fee_asset=None):
        order_id = self.next_id
        self.next_id += 1
        self.orders[symbol].append({"symbol": symbol, "orderId": order_id,
                                    "clientOrderId": client_id, "status": "FILLED",
                                    "side": side, "executedQty": str(qty),
                                    "cummulativeQuoteQty": str(quote)})
        fee_asset = fee_asset or self.fee_asset
        self.trades[symbol].append({"symbol": symbol, "id": 100 + order_id, "orderId": order_id,
                                    "qty": str(qty), "quoteQty": str(quote),
                                    "commission": str(fee), "commissionAsset": fee_asset})
        base = INFOS[symbol].base_asset
        sign = 1 if side == "BUY" else -1
        self.balances[base] = self.balances.get(base, Decimal(0)) + sign * qty
        self.balances["USDT"] -= sign * quote
        self.balances[fee_asset] = self.balances.get(fee_asset, Decimal(0)) - fee

    def account(self):
        return {"balances": [{"asset": a, "free": str(v), "locked": "0"}
                             for a, v in self.balances.items()]}


SECRET = "FAKEsecret9876543210zyxwvuZYXWVU"


def history(rows, key, after=0):
    # Única forma de obtener un History: una paginación completa con fetch_after.
    return fetch_after(lambda c: [r for r in rows if r[key] >= c], after, key)


def data(exchange, open_orders=None):
    return dict(open_orders=open_orders or {s: [] for s in SYMBOLS},
                orders={s: history(exchange.orders[s], "orderId") for s in SYMBOLS},
                trades={s: history(exchange.trades[s], "id") for s in SYMBOLS},
                account=exchange.account())


@pytest.fixture
def book(tmp_path):
    ledger = OrderLedger(tmp_path / "orders.csv", CLOCK, create=True)
    yield ledger
    ledger.close()


def filled_book(book, exchange):
    execute_intent(book, exchange, BUY, no_sleep)
    return book.records()


# --- caso correcto -------------------------------------------------------------------


def test_clean_account_reconciles_and_gives_holdings_and_coverage(book):
    exchange = Exchange()
    records = filled_book(book, exchange)
    result = reconcile_data(BASELINE, INFOS, records, **data(exchange))
    btc = result.holdings["BTCUSDT"]
    assert btc.cash == pytest.approx(BUDGET_PER_ASSET - 999.0)
    assert btc.quantity == pytest.approx(0.01998 - 0.00001998)
    assert btc.cost == pytest.approx(999.0)
    assert result.holdings["ETHUSDT"].quantity == 0 and result.holdings["ETHUSDT"].cash == 1000.0
    assert result.coverage == CoverageProof(frozenset(SYMBOLS), date(2026, 10, 1), True)
    # alimenta check_limits con already_today del MISMO registro (cautela de Codex en F1)
    with pytest.raises(Exception, match="por símbolo"):
        check_limits([OrderIntent("BTCUSDT", Signal.SELL, DAY, quantity=btc.quantity)],
                     result.holdings, already_today=book.orders_on(DAY.date()))


def test_coverage_proof_enables_adjudication_only_after_reconciliation(book):
    exchange = Exchange()
    filled_book(book, exchange)
    result = reconcile_data(BASELINE, INFOS, book.records(), **data(exchange))
    assert isinstance(result.coverage, CoverageProof) and result.coverage.complete
    with pytest.raises(StopTheDay, match="nada que adjudicar"):
        adjudicate_not_sent(book, exchange, BUY.client_order_id, "ok", result.coverage, no_sleep)


@pytest.mark.parametrize("fee_asset", ["BTC", "USDT", "BNB"])
def test_commission_in_base_quote_or_bnb_is_accounted(book, fee_asset):
    exchange = Exchange(fee_asset)
    records = filled_book(book, exchange)
    holding = reconcile_data(BASELINE, INFOS, records, **data(exchange)).holdings["BTCUSDT"]
    expected_qty = 0.01998 - (0.00001998 if fee_asset == "BTC" else 0)
    assert holding.quantity == pytest.approx(expected_qty)


def test_sell_leaving_dust_counts_as_flat(book):
    exchange = Exchange()
    records = filled_book(book, exchange)
    sold = Decimal("0.01996")  # 0.01996002 poseídos, redondeado a stepSize: polvo 2e-8
    exchange.fill("BTCUSDT", "bt-BTCUSDT-20261013-S", "SELL", sold, sold * 51000, Decimal("1"),
                  "USDT")
    sell = OrderIntent("BTCUSDT", Signal.SELL, DAY.replace(day=13), quantity=float(sold))
    book.append(sell, "INTENT")
    book.append(sell, "SENT")
    book.append(sell, "FINAL", "FILLED", float(sold))
    holding = reconcile_data(BASELINE, INFOS, book.records(), **data(exchange)).holdings["BTCUSDT"]
    assert (holding.quantity, holding.cost) == (0.0, 0.0)
    assert holding.cash == pytest.approx(1000 - 999 + 0.01996 * 51000 - 1)


# --- discrepancias: siempre StopTheDay -----------------------------------------------


def stop(book, exchange, match, **overrides):
    kwargs = {**data(exchange), **overrides}
    with pytest.raises(StopTheDay, match=match):
        reconcile_data(BASELINE, INFOS, book.records(), **kwargs)


def test_foreign_or_unrecorded_order_stops(book):
    exchange = Exchange()
    filled_book(book, exchange)
    exchange.fill("ETHUSDT", "manual-123", "BUY", Decimal("0.1"), Decimal("250"), Decimal("0"))
    stop(book, exchange, "ajena")
    lost = Exchange()
    lost.fill("BTCUSDT", BUY.client_order_id, "BUY", Decimal("0.01"), Decimal("500"),
              Decimal("0"))  # orden bt- que un registro vacío no tiene (registro perdido)
    with pytest.raises(StopTheDay, match="ajena"):
        reconcile_data(BASELINE, INFOS, {}, **data(lost))


def test_recorded_order_missing_on_the_exchange_stops(book):
    exchange = Exchange()
    filled_book(book, exchange)
    exchange.orders["BTCUSDT"].clear()
    exchange.trades["BTCUSDT"].clear()
    stop(book, exchange, "no en el exchange")


def test_status_or_quantity_mismatch_stops(book):
    exchange = Exchange()
    filled_book(book, exchange)
    exchange.orders["BTCUSDT"][0]["executedQty"] = "0.01"
    stop(book, exchange, "distintos del registro")


def test_fills_must_add_up(book):
    exchange = Exchange()
    filled_book(book, exchange)
    exchange.trades["BTCUSDT"][0]["qty"] = "0.019"
    stop(book, exchange, "no suman executedQty")
    exchange.trades["BTCUSDT"][0]["qty"] = "0.01998"  # restaurado
    exchange.trades["BTCUSDT"].append(dict(exchange.trades["BTCUSDT"][0], id=999, orderId=77))
    stop(book, exchange, "no está en el historial")


def test_commission_in_other_asset_stops(book):
    exchange = Exchange("ETH")
    filled_book(book, exchange)
    stop(book, exchange, "comisión")


def test_open_order_stops(book):
    exchange = Exchange()
    filled_book(book, exchange)
    stop(book, exchange, "orden abierta",
         open_orders={**{s: [] for s in SYMBOLS}, "SOLUSDT": [{"orderId": 5}]})


def test_unresolved_record_stops(book):
    exchange = Exchange()
    book.append(BUY, "INTENT")
    book.append(BUY, "SENT")
    stop(book, exchange, "sin resolver")


@pytest.mark.parametrize(("asset", "delta", "ok"), [
    ("USDT", "0.01", True), ("USDT", "0.0101", False),
    ("BTC", "0.00002", True), ("BTC", "0.0000201", False),
    ("BNB", "0.00000002", True), ("BNB", "0.00000003", False),
    ("LTC", "0.00000001", False),  # activo ajeno: debe seguir exactamente igual
    ("DOGE", "5", False),  # activo nuevo
])
def test_balance_tolerances(book, asset, delta, ok):
    exchange = Exchange()
    records = filled_book(book, exchange)
    exchange.balances[asset] = exchange.balances.get(asset, Decimal(0)) + Decimal(delta)
    if ok:
        reconcile_data(BASELINE, INFOS, records, **data(exchange))
    else:
        stop(book, exchange, "saldo")


def test_malformed_numbers_stop(book):
    exchange = Exchange()
    filled_book(book, exchange)
    exchange.trades["BTCUSDT"][0]["commission"] = "NaN"
    stop(book, exchange, "numérico")


# --- paginación ----------------------------------------------------------------------


def pager(ids, limit=PAGE_LIMIT):
    calls = []

    def fetch(cursor):
        calls.append(cursor)
        return [{"orderId": i} for i in sorted(ids) if i >= cursor][:limit]
    return fetch, calls


def test_pagination_with_inclusive_cursor_and_gaps():
    ids = [3, 7, 8] + list(range(20, 2020, 2))  # huecos numéricos: no son falta de datos
    fetch, calls = pager(ids)
    rows = fetch_after(fetch, 7, "orderId").rows
    assert [r["orderId"] for r in rows] == [i for i in ids if i > 7]
    assert calls[0] == 7 and len(calls) == 2  # la fila igual al cursor se descarta


def test_pagination_refuses_unsorted_repeated_or_early_pages():
    with pytest.raises(StopTheDay, match="no ordenados"):
        fetch_after(lambda c: [{"orderId": 5}, {"orderId": 4}], 0, "orderId")
    with pytest.raises(StopTheDay, match="no ordenados"):
        fetch_after(lambda c: [{"orderId": 5}, {"orderId": 5}], 0, "orderId")
    with pytest.raises(StopTheDay, match="no ordenados"):
        fetch_after(lambda c: [{"orderId": "5"}], 0, "orderId")
    with pytest.raises(StopTheDay, match="antes del cursor"):
        fetch_after(lambda c: [{"orderId": 1}], 3, "orderId")
    # un servidor que repite la misma página llena: los ids repetidos se detectan
    full = [{"orderId": 10 + i} for i in range(PAGE_LIMIT)]
    with pytest.raises(StopTheDay, match="antes del cursor"):
        fetch_after(lambda c: full, 10, "orderId")


# --- línea base ----------------------------------------------------------------------


def test_baseline_requires_no_open_orders_and_short_history(tmp_path):
    empty = {s: [] for s in SYMBOLS}
    account = {"balances": [{"asset": "USDT", "free": "10", "locked": "5"},
                            {"asset": "XRP", "free": "0", "locked": "0"}]}
    baseline = baseline_from(date(2026, 10, 14), account, empty,
                             {**empty, "BTCUSDT": [{"orderId": 41}]},
                             {**empty, "ETHUSDT": [{"id": 9}]})
    assert baseline.balances == {"USDT": Decimal("15")}
    assert baseline.last_order_id == {"BTCUSDT": 41, "ETHUSDT": 0, "SOLUSDT": 0}
    assert baseline.last_trade_id["ETHUSDT"] == 9
    with pytest.raises(StopTheDay, match="abiertas"):
        baseline_from(date(2026, 10, 14), account, {**empty, "SOLUSDT": [{"orderId": 1}]},
                      empty, empty)
    with pytest.raises(StopTheDay, match="demasiado largo"):
        baseline_from(date(2026, 10, 14), account, empty,
                      {**empty, "BTCUSDT": [{"orderId": i} for i in range(PAGE_LIMIT)]}, empty)


def test_baseline_is_saved_once_and_tamper_evident(tmp_path):
    path = tmp_path / "baseline.json"
    with pytest.raises(StopTheDay, match="no hay línea base"):
        load_baseline(path, SECRET)
    save_baseline(path, BASELINE, SECRET)
    assert load_baseline(path, SECRET) == BASELINE
    with pytest.raises(StopTheDay, match="ya existe"):
        save_baseline(path, BASELINE, SECRET)
    with pytest.raises(StopTheDay, match="HMAC"):
        load_baseline(path, "OTROsecret0123456789abcdefABCDEF")  # clave distinta
    document = json.loads(path.read_text(encoding="utf-8"))
    document["balances"]["USDT"] = "999999"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(StopTheDay, match="HMAC"):
        load_baseline(path, SECRET)


def test_coordinated_edit_with_a_recomputed_hash_is_detected(tmp_path):
    # Revisión de Codex: editar los datos y recalcular un SHA-256 no debe bastar.
    import hashlib
    path = tmp_path / "baseline.json"
    save_baseline(path, BASELINE, SECRET)
    document = json.loads(path.read_text(encoding="utf-8"))
    document.pop("hmac")
    document["balances"]["USDT"] = "999999"
    canonical = json.dumps(document, sort_keys=True).encode("utf-8")
    for field in ("hmac", "sha256"):
        forged = {**document, field: hashlib.sha256(canonical).hexdigest()}
        path.write_text(json.dumps(forged), encoding="utf-8")
        with pytest.raises(StopTheDay, match="HMAC"):
            load_baseline(path, SECRET)


def test_symbol_info_validates_exchange_info():
    info = {"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT",
                         "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.00001000"}]}]}
    assert symbol_info(info, "BTCUSDT") == SymbolInfo("BTCUSDT", "BTC", Decimal("0.00001"))
    for broken in ({"symbols": []},
                   {"symbols": [dict(info["symbols"][0], quoteAsset="BUSD")]},
                   {"symbols": [dict(info["symbols"][0], filters=[])]},
                   {"symbols": [dict(info["symbols"][0], filters=[{"filterType": "LOT_SIZE",
                                                                   "stepSize": "0"}])]}):
        with pytest.raises(StopTheDay):
            symbol_info(broken, "BTCUSDT")


# --- envoltorio con un cliente falso (solo lectura) ----------------------------------


class FakeClient:
    def __init__(self, exchange):
        self.exchange, self.calls = exchange, []

    def exchange_info(self, symbol):
        info = INFOS[symbol]
        return {"symbols": [{"symbol": symbol, "baseAsset": info.base_asset,
                             "quoteAsset": "USDT",
                             "filters": [{"filterType": "LOT_SIZE",
                                          "stepSize": str(info.step_size)}]}]}

    def open_orders(self, symbol):
        return []

    def all_orders(self, symbol, order_id=None, limit=1000):
        self.calls.append(("all_orders", symbol, order_id))
        return [o for o in self.exchange.orders[symbol] if o["orderId"] >= (order_id or 0)]

    def my_trades(self, symbol, from_id=None, limit=1000):
        self.calls.append(("my_trades", symbol, from_id))
        return [t for t in self.exchange.trades[symbol] if t["id"] >= (from_id or 0)]

    def account(self):
        return self.exchange.account()


def test_reconcile_reads_only_and_uses_baseline_cursors(book):
    exchange = Exchange()
    filled_book(book, exchange)
    client = FakeClient(exchange)
    result = reconcile(client, book, BASELINE)
    assert result.holdings["BTCUSDT"].quantity > 0
    assert ("all_orders", "BTCUSDT", 0) in client.calls and ("my_trades", "SOLUSDT", 0) in client.calls
    assert not any(name.startswith(("new", "cancel", "submit")) for name, *_ in client.calls)


# --- revisión de Codex de F2b-2 ------------------------------------------------------


def test_duplicate_client_order_id_on_the_exchange_stops(book):
    exchange = Exchange()
    filled_book(book, exchange)
    exchange.fill("BTCUSDT", BUY.client_order_id, "BUY", Decimal("0.01998"),
                  Decimal("999.00000"), Decimal("0.00001998"))  # mismo id, fills coherentes
    stop(book, exchange, "más de una vez")


@pytest.mark.parametrize(("field", "value"), [("side", "SELL"), ("symbol", "ETHUSDT")])
def test_side_or_symbol_different_from_the_intent_stops(book, field, value):
    exchange = Exchange()
    filled_book(book, exchange)
    exchange.orders["BTCUSDT"][0][field] = value
    stop(book, exchange, "símbolo o lado")


def record_sell(book, exchange, quantity, day=13, fee="0"):
    sell = OrderIntent("BTCUSDT", Signal.SELL, DAY.replace(day=day), quantity=float(quantity))
    exchange.fill("BTCUSDT", sell.client_order_id, "SELL", quantity, quantity * 50000,
                  Decimal(fee), "USDT")
    book.append(sell, "INTENT")
    book.append(sell, "SENT")
    book.append(sell, "FINAL", "FILLED", float(quantity))


def test_sell_without_bot_position_stops(book):
    exchange = Exchange()
    exchange.balances["BTC"] = Decimal("1")  # BTC precargado, no del bot
    baseline = Baseline(BASELINE.since, {**BASE_BALANCES, "BTC": Decimal("1")},
                        BASELINE.last_order_id, BASELINE.last_trade_id)
    record_sell(book, exchange, Decimal("0.5"))
    with pytest.raises(StopTheDay, match="venta sin posición"):
        reconcile_data(baseline, INFOS, book.records(), **data(exchange))


def test_selling_more_than_the_bot_position_stops_even_if_balances_match(book):
    exchange = Exchange()
    exchange.balances["BTC"] = Decimal("1")  # el saldo total cuadraría gracias al precargado
    baseline = Baseline(BASELINE.since, {**BASE_BALANCES, "BTC": Decimal("1")},
                        BASELINE.last_order_id, BASELINE.last_trade_id)
    filled_book(book, exchange)
    record_sell(book, exchange, Decimal("0.5"))
    with pytest.raises(StopTheDay, match="más de lo poseído"):
        reconcile_data(baseline, INFOS, book.records(), **data(exchange))


def test_buy_over_budget_stops(book):
    exchange = Exchange()
    intent = OrderIntent("SOLUSDT", Signal.BUY, DAY, quote_amount=1000.0)
    exchange.fill("SOLUSDT", intent.client_order_id, "BUY", Decimal("10"), Decimal("1500"),
                  Decimal("0"), "USDT")
    book.append(intent, "INTENT")
    book.append(intent, "SENT")
    book.append(intent, "FINAL", "FILLED", 10.0)
    stop(book, exchange, "presupuesto")


def test_second_buy_with_open_position_stops(book):
    exchange = Exchange()
    filled_book(book, exchange)
    again = OrderIntent("BTCUSDT", Signal.BUY, DAY.replace(day=14), quote_amount=1.0)
    exchange.fill("BTCUSDT", again.client_order_id, "BUY", Decimal("0.00002"), Decimal("1"),
                  Decimal("0"), "USDT")
    book.append(again, "INTENT")
    book.append(again, "SENT")
    book.append(again, "FINAL", "FILLED", 0.00002)
    stop(book, exchange, "ya abierta")


def test_reconcile_data_requires_complete_paginated_history(book):
    exchange = Exchange()
    records = filled_book(book, exchange)
    plain = {**data(exchange), "orders": exchange.orders}  # listas sueltas
    with pytest.raises(StopTheDay, match="paginación completa"):
        reconcile_data(BASELINE, INFOS, records, **plain)
    late = {**data(exchange), "trades": {s: history(exchange.trades[s], "id", 5) for s in SYMBOLS}}
    with pytest.raises(StopTheDay, match="paginación completa"):
        reconcile_data(BASELINE, INFOS, records, **late)  # no empieza en la línea base
    swapped = {**data(exchange), "orders": {s: history(exchange.trades[s], "id") for s in SYMBOLS}}
    with pytest.raises(StopTheDay, match="paginación completa"):
        reconcile_data(BASELINE, INFOS, records, **swapped)


def test_only_reconciliation_builds_coverage_and_only_fetch_after_builds_history():
    src = Path(__file__).resolve().parents[1] / "src" / "bottrading"
    builders = {}
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("CoverageProof(", "History("):
            for match in re.finditer(rf"(?<![\w.])(?<!class ){re.escape(name)}", text):
                builders.setdefault(name, set()).add(path.name)
    assert builders["CoverageProof("] == {"demo_reconcile.py"}
    assert builders["History("] == {"demo_reconcile.py"}
    text = (src / "demo_reconcile.py").read_text(encoding="utf-8")
    assert text.count("CoverageProof(frozenset") == 1  # un solo punto: el final de reconcile_data
    assert text.count("return History(") == 1  # un solo punto: el final de fetch_after
