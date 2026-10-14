"""Reconciliación de la cuenta demo con el registro privado (D030, F2b-2).

Solo lectura. Compara la línea base (saldos al empezar), el registro de
órdenes del bot y el historial del exchange (allOrders, myTrades, saldos,
órdenes abiertas). Si TODO cuadra, devuelve las posiciones reales por
activo (para decide/check_limits) y una CoverageProof; ante cualquier
discrepancia lanza StopTheDay y no se envía nada (D030, punto 3).

- Cobertura por claves y cursores inclusivos, no por ids consecutivos: se
  pagina desde el último id conocido descartando lo ya visto, hasta una
  página con menos de PAGE_LIMIT filas.
- Comisiones en el activo base, USDT o BNB; cualquier otra -> detenerse.
- Activos ajenos a BTC/ETH/SOL/USDT/BNB deben seguir exactamente como en la
  línea base.
- Una orden abierta (remanente) detiene: cancelarla es una escritura que
  requiere la aprobación (b) de D030.
- Las cifras se tratan con Decimal a partir de los textos de Binance.
"""

import hashlib
import hmac
import json
import os
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bottrading.demo_ledger import (
    CoverageProof,
    OrderLedger,
    OrderRecord,
    StopTheDay,
    issue_coverage_proof,
)
from bottrading.execution import BUDGET_PER_ASSET, DEMO_SYMBOLS, Holding

QUOTE_ASSET = "USDT"
FEE_ASSET = "BNB"
PAGE_LIMIT = 1000
TOLERANCE = {QUOTE_ASSET: Decimal("0.01"), FEE_ASSET: Decimal("0.00000002")}
NO_EXCHANGE_TRACE = frozenset({"REJECTED", "NOT_SENT"})  # pueden no existir en el exchange


def _decimal(value: object, what: str) -> Decimal:
    number = None
    if isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation:
            number = None
    if number is None or not number.is_finite():
        raise StopTheDay(f"valor numérico inesperado en {what}")
    return number


# --- información de símbolos ---------------------------------------------------------


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    base_asset: str
    step_size: Decimal


def symbol_info(exchange_info: Mapping, symbol: str) -> SymbolInfo:
    entries = [s for s in exchange_info.get("symbols", []) if s.get("symbol") == symbol]
    if len(entries) != 1 or entries[0].get("quoteAsset") != QUOTE_ASSET:
        raise StopTheDay(f"{symbol}: exchangeInfo inesperado")
    lot = [f for f in entries[0].get("filters", []) if f.get("filterType") == "LOT_SIZE"]
    step = _decimal(lot[0].get("stepSize") if len(lot) == 1 else None, f"{symbol} stepSize")
    base = entries[0].get("baseAsset")
    if step <= 0 or not isinstance(base, str) or not base:
        raise StopTheDay(f"{symbol}: precisión o activo base desconocidos")
    return SymbolInfo(symbol, base, step)


# --- línea base ----------------------------------------------------------------------


@dataclass(frozen=True)
class Baseline:
    since: date
    balances: dict[str, Decimal]
    last_order_id: dict[str, int]
    last_trade_id: dict[str, int]

    def payload(self) -> dict:
        return {"since": self.since.isoformat(),
                "balances": {a: str(v) for a, v in sorted(self.balances.items())},
                "last_order_id": dict(sorted(self.last_order_id.items())),
                "last_trade_id": dict(sorted(self.last_trade_id.items()))}


def account_balances(account: Mapping) -> dict[str, Decimal]:
    """free + locked de cada activo con saldo distinto de cero."""
    balances = {}
    for entry in account.get("balances", []):
        total = _decimal(entry.get("free"), "free") + _decimal(entry.get("locked"), "locked")
        if total:
            balances[entry["asset"]] = total
    return balances


def baseline_from(day: date, account: Mapping, open_orders: Mapping[str, Sequence],
                  orders: Mapping[str, Sequence], trades: Mapping[str, Sequence]) -> Baseline:
    """Línea base (D030): cero órdenes abiertas y historial < PAGE_LIMIT por símbolo."""
    for symbol in DEMO_SYMBOLS:
        if open_orders[symbol]:
            raise StopTheDay(f"{symbol}: hay órdenes abiertas; no se fija la línea base")
        if len(orders[symbol]) >= PAGE_LIMIT or len(trades[symbol]) >= PAGE_LIMIT:
            raise StopTheDay(f"{symbol}: historial demasiado largo para fijar la línea base")
    return Baseline(day, account_balances(account),
                    {s: max((o["orderId"] for o in orders[s]), default=0) for s in DEMO_SYMBOLS},
                    {s: max((t["id"] for t in trades[s]), default=0) for s in DEMO_SYMBOLS})


# Integridad (revisión de Codex): un hash dentro del propio archivo se puede
# recalcular tras editarlo. Se usa un HMAC con una clave derivada del SECRETO
# de la credencial demo (Administrador de credenciales): editar la línea base
# de forma coherente exige conocer ese secreto. Límite: ningún mecanismo
# local impide del todo a un proceso del mismo usuario que lea la credencial.


def _baseline_mac(secret: str, payload: dict) -> str:
    key = hmac.new(secret.encode("ascii"), b"bottrading-baseline-v1", hashlib.sha256).digest()
    canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def save_baseline(path: Path, baseline: Baseline, secret: str) -> None:
    """Solo desde la inicialización explícita y aprobada; creación EXCLUSIVA."""
    payload = baseline.payload()
    document = {**payload, "hmac": _baseline_mac(secret, payload)}
    content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    created = True
    try:
        handle = open(path, "xb")  # falla si ya existe, de forma atómica
    except FileExistsError:
        created = False
    if not created:
        raise StopTheDay("la línea base ya existe: una nueva requiere --rebaseline aprobado")
    with handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def resign_baseline(path: Path, old_secret: str, new_secret: str) -> None:
    """Rotación de clave (D030): verifica la línea base con el secreto ANTERIOR
    y la vuelve a firmar con el NUEVO sin tocar su contenido. Guarda una copia
    exclusiva de la versión anterior; nunca crea una línea base nueva."""
    load_baseline(path, old_secret)  # detiene si no verifica con la clave anterior
    original = path.read_bytes()
    document = json.loads(original.decode("utf-8"))
    document.pop("hmac")
    document["hmac"] = _baseline_mac(new_secret, document)
    backup = path.with_name(path.name + ".anterior")
    created = True
    try:
        handle = open(backup, "xb")
    except FileExistsError:
        created = False
    if not created:
        raise StopTheDay("ya existe una copia de una rotación anterior: revisarla antes")
    with handle:
        handle.write(original)
        handle.flush()
        os.fsync(handle.fileno())
    temporary = path.with_name(path.name + ".nuevo")
    with open(temporary, "xb") as handle:
        handle.write((json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    load_baseline(path, new_secret)  # comprobación final


def load_baseline(path: Path, secret: str) -> Baseline:
    if not path.exists():
        raise StopTheDay("no hay línea base: inicializa la cuenta demo de forma explícita")
    document = json.loads(path.read_text(encoding="utf-8"))
    mac = document.pop("hmac", None)
    if not isinstance(mac, str) or not hmac.compare_digest(mac, _baseline_mac(secret, document)):
        raise StopTheDay("la línea base no coincide con su HMAC (editada o clave distinta)")
    return Baseline(date.fromisoformat(document["since"]),
                    {a: Decimal(v) for a, v in document["balances"].items()},
                    {s: int(v) for s, v in document["last_order_id"].items()},
                    {s: int(v) for s, v in document["last_trade_id"].items()})


# --- paginación con cursores inclusivos ----------------------------------------------


@dataclass(frozen=True, eq=False)
class History:
    """Historial completo de un símbolo tras last_id, emitido por fetch_after.

    Procedencia (revisión de Codex): reconcile_data solo acepta los objetos
    que fetch_after registró al terminar una paginación completa; un History
    construido a mano se rechaza aunque tenga la clave y el cursor correctos.
    Dentro del mismo proceso nada es infalsificable: saltárselo exige tocar
    deliberadamente _ISSUED_HISTORIES (un test estático vigila su uso).
    """

    rows: tuple[Mapping, ...]
    key: str
    after: int


_ISSUED_HISTORIES: "weakref.WeakSet[History]" = weakref.WeakSet()


def fetch_after(fetch_page: Callable[[int], Sequence[Mapping]], last_id: int,
                key: str) -> History:
    """Filas con `key` > last_id. fetch_page(cursor) devuelve filas con key >= cursor."""
    rows, cursor = [], last_id
    while True:
        page = list(fetch_page(cursor))
        ids = [row.get(key) for row in page]
        if not all(isinstance(i, int) for i in ids) or ids != sorted(set(ids)):
            raise StopTheDay(f"página con {key} no ordenados o repetidos")
        if ids and ids[0] < cursor:
            raise StopTheDay(f"página que empieza antes del cursor ({key})")
        rows += [row for row in page if row[key] > cursor]
        if len(page) < PAGE_LIMIT:
            issued = History(tuple(rows), key, last_id)
            _ISSUED_HISTORIES.add(issued)
            return issued
        # Página llena, ordenada, sin repetidos y desde el cursor: ids[-1] > cursor,
        # así que siempre avanza; un servidor que repita la página cae en
        # "antes del cursor" en la siguiente vuelta.
        cursor = ids[-1]


# --- reconciliación pura --------------------------------------------------------------


@dataclass(frozen=True)
class Reconciliation:
    holdings: dict[str, Holding]
    coverage: CoverageProof
    balances: dict[str, Decimal]
    # Historial ya validado (F5: informe de ejecución): órdenes y fills por símbolo.
    orders: dict[str, list] = field(default_factory=dict)
    trades: dict[str, list] = field(default_factory=dict)


def reconcile_data(baseline: Baseline, infos: Mapping[str, SymbolInfo],
                   records: Mapping[str, OrderRecord], open_orders: Mapping[str, Sequence],
                   orders: Mapping[str, History], trades: Mapping[str, History],
                   account: Mapping) -> Reconciliation:
    """Lanza StopTheDay ante cualquier discrepancia; si no, posiciones y cobertura."""
    for symbol in DEMO_SYMBOLS:
        expected_keys = (("orderId", orders, baseline.last_order_id),
                         ("id", trades, baseline.last_trade_id))
        for key, histories, last_ids in expected_keys:
            history = histories.get(symbol)
            if not isinstance(history, History) or history not in _ISSUED_HISTORIES or \
                    history.key != key or \
                    history.after != last_ids.get(symbol, 0):
                raise StopTheDay(f"{symbol}: historial sin paginación completa desde la línea base")
    orders = {s: list(h.rows) for s, h in orders.items()}
    trades = {s: list(h.rows) for s, h in trades.items()}
    problems: list[str] = []
    for record in records.values():
        if not record.final:
            problems.append(f"{record.intent.client_order_id}: orden sin resolver en el registro")
    expected = dict(baseline.balances)
    holdings = {}
    for symbol in DEMO_SYMBOLS:
        info = infos[symbol]
        if open_orders[symbol]:
            problems.append(f"{symbol}: orden abierta (remanente); cancelarla requiere (b)")
        problems += _check_orders(symbol, orders[symbol], trades[symbol], records)
        allowed_fees = {info.base_asset, QUOTE_ASSET, FEE_ASSET}
        for trade in trades[symbol]:
            if trade.get("commissionAsset") not in allowed_fees:
                problems.append(f"{symbol}: comisión en un activo no admitido")
        if not problems:
            _apply_trades(expected, info, orders[symbol], trades[symbol])
            holding, holding_problems = _holding(info, orders[symbol], trades[symbol])
            problems += holding_problems
            holdings[symbol] = holding
    if problems:
        raise StopTheDay("reconciliación incompleta o con discrepancias: " + "; ".join(problems))

    actual = account_balances(account)
    tolerances = {**TOLERANCE, **{i.base_asset: 2 * i.step_size for i in infos.values()}}
    for asset in sorted(expected.keys() | actual.keys()):
        difference = abs(actual.get(asset, Decimal(0)) - expected.get(asset, Decimal(0)))
        if difference > tolerances.get(asset, Decimal(0)):
            problems.append(f"{asset}: saldo distinto del esperado")
    if problems:
        raise StopTheDay("reconciliación con discrepancias de saldo: " + "; ".join(problems))
    return Reconciliation(holdings, issue_coverage_proof(frozenset(DEMO_SYMBOLS), baseline.since),
                          actual, orders, trades)


def _check_orders(symbol: str, orders: Sequence[Mapping], trades: Sequence[Mapping],
                  records: Mapping[str, OrderRecord]) -> list[str]:
    problems = []
    seen = set()
    by_order: dict[int, list[Mapping]] = {}
    for trade in trades:
        by_order.setdefault(trade.get("orderId"), []).append(trade)
    for order in orders:
        client_id, order_id = order.get("clientOrderId"), order.get("orderId")
        record = records.get(client_id)
        if record is None or record.intent.symbol != symbol:
            problems.append(f"{symbol}: orden {order_id} ajena o fuera del registro")
            continue
        if client_id in seen:  # revisión de Codex: dos órdenes con el mismo id
            problems.append(f"{client_id}: aparece más de una vez en el exchange")
            continue
        seen.add(client_id)
        if order.get("symbol") != symbol or \
                order.get("side") != record.intent.side.value.upper():
            problems.append(f"{client_id}: símbolo o lado distintos de la intención")
        executed = _decimal(order.get("executedQty"), "executedQty")
        quote = _decimal(order.get("cummulativeQuoteQty"), "cummulativeQuoteQty")
        if record.status != order.get("status") or record.executed_qty is None or \
                _decimal(repr(record.executed_qty), "registro") != executed:
            problems.append(f"{client_id}: estado o cantidad distintos del registro")
        fills = by_order.pop(order_id, [])
        if sum((_decimal(t.get("qty"), "qty") for t in fills), Decimal(0)) != executed:
            problems.append(f"{client_id}: los fills no suman executedQty")
        fill_quote = sum((_decimal(t.get("quoteQty"), "quoteQty") for t in fills), Decimal(0))
        if abs(fill_quote - quote) > TOLERANCE[QUOTE_ASSET]:
            problems.append(f"{client_id}: los fills no suman cummulativeQuoteQty")
    for order_id in by_order:
        problems.append(f"{symbol}: fills de la orden {order_id}, que no está en el historial")
    for client_id, record in records.items():
        if record.intent.symbol == symbol and client_id not in seen and record.final \
                and record.status not in NO_EXCHANGE_TRACE:
            problems.append(f"{client_id}: en el registro pero no en el exchange")
    return problems


def _apply_trades(balances: dict[str, Decimal], info: SymbolInfo, orders: Sequence[Mapping],
                  trades: Sequence[Mapping]) -> None:
    sides = {o["orderId"]: o.get("side") for o in orders}
    for trade in trades:
        qty, quote = _decimal(trade["qty"], "qty"), _decimal(trade["quoteQty"], "quoteQty")
        sign = 1 if sides.get(trade["orderId"]) == "BUY" else -1
        balances[info.base_asset] = balances.get(info.base_asset, Decimal(0)) + sign * qty
        balances[QUOTE_ASSET] = balances.get(QUOTE_ASSET, Decimal(0)) - sign * quote
        fee_asset = trade["commissionAsset"]
        balances[fee_asset] = balances.get(fee_asset, Decimal(0)) - \
            _decimal(trade["commission"], "commission")


def _holding(info: SymbolInfo, orders: Sequence[Mapping],
             trades: Sequence[Mapping]) -> tuple[Holding, list[str]]:
    """Posición del presupuesto de D030 a partir de los fills reales.

    Un resto en [0, stepSize) (polvo tras pagar comisión en el activo base)
    cuenta como sin posición. `cost` es lo pagado por la compra que abrió la
    posición vigente. Se rechazan estados imposibles (revisión de Codex):
    comprar con posición abierta, vender sin posición o más de lo poseído,
    efectivo negativo o cantidad negativa.
    """
    sides = {o["orderId"]: o.get("side") for o in orders}
    cash, quantity, cost = Decimal(str(BUDGET_PER_ASSET)), Decimal(0), Decimal(0)
    order_start: dict[int, tuple[Decimal, Decimal]] = {}  # (cantidad, efectivo) antes
    order_quote: dict[int, Decimal] = {}  # USDT gastados por cada compra (todos sus fills)
    problems = []
    for trade in sorted(trades, key=lambda t: t["id"]):
        qty, quote = _decimal(trade["qty"], "qty"), _decimal(trade["quoteQty"], "quoteQty")
        fee = _decimal(trade["commission"], "commission")
        start_qty, start_cash = order_start.setdefault(trade["orderId"], (quantity, cash))
        if sides.get(trade["orderId"]) == "BUY":
            if start_qty >= info.step_size:
                problems.append(f"{info.symbol}: compra con una posición ya abierta")
            if start_qty < info.step_size and quantity == start_qty:
                cost = Decimal(0)  # primer fill de una nueva posición
            cash, quantity, cost = cash - quote, quantity + qty, cost + quote
            spent = order_quote[trade["orderId"]] = order_quote.get(trade["orderId"], 0) + quote
            if spent > min(start_cash, Decimal(str(BUDGET_PER_ASSET))):
                # revisión de Codex: tope min(efectivo, 1000) por compra (D030)
                problems.append(f"{info.symbol}: compra mayor que min(efectivo, presupuesto)")
        else:
            if start_qty < info.step_size:
                problems.append(f"{info.symbol}: venta sin posición del bot")
            cash, quantity = cash + quote, quantity - qty
        if trade["commissionAsset"] == QUOTE_ASSET:
            cash -= fee
        elif trade["commissionAsset"] == info.base_asset:
            quantity -= fee
        if quantity < 0:
            problems.append(f"{info.symbol}: se vendió más de lo poseído")
        if cash < 0:
            problems.append(f"{info.symbol}: efectivo negativo; se superó el presupuesto")
    if problems:
        return Holding(0.0), sorted(set(problems))
    if quantity < info.step_size:
        return Holding(float(cash)), []
    return Holding(float(cash), float(quantity), float(cost)), []


# --- obtención de datos (solo lectura) -----------------------------------------------


def take_baseline(client, day: date) -> Baseline:
    """Lee la cuenta para fijar la línea base (solo lectura; guardarla es aparte)."""
    return baseline_from(day, client.account(),
                         {s: client.open_orders(s) for s in DEMO_SYMBOLS},
                         {s: client.all_orders(s, None, PAGE_LIMIT) for s in DEMO_SYMBOLS},
                         {s: client.my_trades(s, None, PAGE_LIMIT) for s in DEMO_SYMBOLS})


def reconcile(client, ledger: OrderLedger, baseline: Baseline) -> Reconciliation:
    """Lee el exchange con DemoClient (solo lectura) y reconcilia."""
    infos, open_orders, orders, trades = {}, {}, {}, {}
    for symbol in DEMO_SYMBOLS:
        infos[symbol] = symbol_info(client.exchange_info(symbol), symbol)
        open_orders[symbol] = client.open_orders(symbol)
        orders[symbol] = fetch_after(lambda c, s=symbol: client.all_orders(s, c, PAGE_LIMIT),
                                     baseline.last_order_id.get(symbol, 0), "orderId")
        trades[symbol] = fetch_after(lambda c, s=symbol: client.my_trades(s, c, PAGE_LIMIT),
                                     baseline.last_trade_id.get(symbol, 0), "id")
    return reconcile_data(baseline, infos, ledger.records(), open_orders, orders, trades,
                          client.account())
