"""Registro privado y protocolo idempotente (D030, F2b-1) con un servidor simulado."""

from datetime import datetime, timedelta, timezone

import pytest

from bottrading.demo_ledger import (
    DuplicateOrder,
    GatewayRejected,
    GatewayUnknown,
    LedgerIntegrityError,
    OrderLedger,
    OrderStatus,
    StopTheDay,
    adjudicate_not_sent,
    default_ledger_path,
    execute_intent,
    resolve,
)
from bottrading.execution import OrderIntent
from bottrading.strategy import Signal

DAY = datetime(2026, 10, 12, tzinfo=timezone.utc)
BUY = OrderIntent("BTCUSDT", Signal.BUY, DAY, quote_amount=1000.0)
SELL = OrderIntent("ETHUSDT", Signal.SELL, DAY, quantity=0.5)
FILLED = OrderStatus("FILLED", 0.0123)


class FakeExchange:
    """Semántica documentada de Binance: un id repetido se ACEPTA si la orden
    anterior con ese id está FILLED (no hay idempotencia en el servidor)."""

    def __init__(self, submit_outcome="fill", answers=None):
        self.orders, self.posts, self.queries = {}, [], 0
        self.submit_outcome = submit_outcome
        self.answers = list(answers or [])  # respuestas forzadas a query, en orden

    def query(self, intent):
        self.queries += 1
        if self.answers:
            answer = self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return self.orders.get(intent.client_order_id)

    def submit(self, intent):
        self.posts.append(intent.client_order_id)
        current = self.orders.get(intent.client_order_id)
        if current is not None and current.status != "FILLED":
            raise DuplicateOrder()
        outcome = self.submit_outcome
        if outcome == "reject":
            raise GatewayRejected(-2010)
        if outcome == "partial":
            self.orders[intent.client_order_id] = OrderStatus("PARTIALLY_FILLED", 0.005)
            return self.orders[intent.client_order_id]
        self.orders[intent.client_order_id] = FILLED
        if outcome == "timeout_after_fill":
            raise GatewayUnknown()  # se ejecutó, pero la respuesta no llegó
        if outcome == "timeout_lost":
            del self.orders[intent.client_order_id]
            raise GatewayUnknown()  # no llegó al motor
        return FILLED


def no_sleep(seconds):
    pass


def ledger(tmp_path, clock=None):
    return OrderLedger(tmp_path / "orders.csv",
                       clock or (lambda: datetime(2026, 10, 13, 0, 5, tzinfo=timezone.utc)))


def events(book, client_order_id):
    return [row[3] for row in book._rows if row[2] == client_order_id]


# --- envío normal e idempotencia -----------------------------------------------------


def test_normal_flow_writes_intent_and_sent_before_the_post(tmp_path):
    book, exchange = ledger(tmp_path), FakeExchange()
    record = execute_intent(book, exchange, BUY, no_sleep)
    assert (record.state, record.status, record.executed_qty) == ("FINAL", "FILLED", 0.0123)
    assert events(book, BUY.client_order_id) == ["INTENT", "SENT", "FINAL"]
    assert exchange.posts == [BUY.client_order_id]
    assert exchange.queries == 3  # 3 "no existe" coherentes antes de enviar


def test_repeating_the_same_intent_sends_zero_even_if_server_would_accept(tmp_path):
    # D030 / revisión de Codex: el servidor ACEPTARÍA el mismo id (anterior FILLED).
    book, exchange = ledger(tmp_path), FakeExchange()
    execute_intent(book, exchange, BUY, no_sleep)
    for _ in range(3):
        execute_intent(book, exchange, BUY, no_sleep)
        execute_intent(OrderLedger(book.path), exchange, BUY, no_sleep)  # nueva ejecución
    assert exchange.posts == [BUY.client_order_id]


def test_existing_order_is_adopted_without_posting(tmp_path):
    # El registro se perdió con la orden ya enviada: la consulta previa la encuentra.
    exchange = FakeExchange()
    exchange.orders[BUY.client_order_id] = FILLED
    record = execute_intent(ledger(tmp_path), exchange, BUY, no_sleep)
    assert record.status == "FILLED" and exchange.posts == []


def test_rejection_is_final_and_not_retried(tmp_path):
    book, exchange = ledger(tmp_path), FakeExchange("reject")
    record = execute_intent(book, exchange, SELL, no_sleep)
    assert (record.state, record.status) == ("FINAL", "REJECTED")
    execute_intent(book, exchange, SELL, no_sleep)
    assert exchange.posts == [SELL.client_order_id]


def test_same_id_with_different_content_is_refused(tmp_path):
    book = ledger(tmp_path)
    execute_intent(book, FakeExchange(), BUY, no_sleep)
    changed = OrderIntent("BTCUSDT", Signal.BUY, DAY, quote_amount=999.0)
    with pytest.raises(StopTheDay, match="distinta"):
        execute_intent(book, FakeExchange(), changed, no_sleep)


# --- estados ambiguos ----------------------------------------------------------------


def test_timeout_after_execution_is_resolved_by_query_not_resent(tmp_path):
    book, exchange = ledger(tmp_path), FakeExchange("timeout_after_fill")
    record = execute_intent(book, exchange, BUY, no_sleep)
    assert record.status == "FILLED"
    assert events(book, BUY.client_order_id) == ["INTENT", "SENT", "UNKNOWN", "FINAL"]
    assert exchange.posts == [BUY.client_order_id]


def test_timeout_without_execution_stops_the_day_and_never_resends(tmp_path):
    book, exchange = ledger(tmp_path), FakeExchange("timeout_lost")
    with pytest.raises(StopTheDay, match="adjudicación"):
        execute_intent(book, exchange, BUY, no_sleep)
    for _ in range(2):  # reinicios: siguen sin reenviar
        with pytest.raises(StopTheDay):
            execute_intent(OrderLedger(book.path), exchange, BUY, no_sleep)
    assert exchange.posts == [BUY.client_order_id]
    assert book.record(BUY.client_order_id).state == "UNKNOWN"


def test_duplicate_answer_is_treated_as_existing_order(tmp_path):
    book, exchange = ledger(tmp_path), FakeExchange()
    exchange.orders[BUY.client_order_id] = OrderStatus("NEW", 0.0)
    exchange.answers = [None, None, None]  # consultas previas no la ven (inconsistencia)
    record = execute_intent(book, exchange, BUY, no_sleep)
    assert record.status == "NEW" and record.state == "ACK"
    assert exchange.posts == [BUY.client_order_id]  # un solo intento, rechazado por duplicado


def test_crash_after_sent_never_resends(tmp_path):
    book = ledger(tmp_path)
    book.append(BUY, "INTENT")
    book.append(BUY, "SENT")  # el proceso murió durante el POST
    exchange = FakeExchange()
    with pytest.raises(StopTheDay):
        execute_intent(OrderLedger(book.path), exchange, BUY, no_sleep)
    assert exchange.posts == []
    exchange.orders[BUY.client_order_id] = FILLED  # sí llegó: se adopta
    assert execute_intent(OrderLedger(book.path), exchange, BUY, no_sleep).status == "FILLED"
    assert exchange.posts == []


def test_crash_after_intent_only_continues_the_protocol(tmp_path):
    book = ledger(tmp_path)
    book.append(BUY, "INTENT")  # murió antes de escribir SENT: el POST no empezó
    exchange = FakeExchange()
    assert execute_intent(OrderLedger(book.path), exchange, BUY, no_sleep).status == "FILLED"
    assert exchange.posts == [BUY.client_order_id]


def test_partial_fill_blocks_new_orders_for_that_symbol(tmp_path):
    book, exchange = ledger(tmp_path), FakeExchange("partial")
    record = execute_intent(book, exchange, BUY, no_sleep)
    assert (record.state, record.status) == ("ACK", "PARTIALLY_FILLED")
    later = OrderIntent("BTCUSDT", Signal.SELL, DAY + timedelta(days=1), quantity=0.005)
    with pytest.raises(StopTheDay, match="sin resolver"):
        execute_intent(book, exchange, later, no_sleep)
    execute_intent(book, FakeExchange(), SELL, no_sleep)  # otro símbolo no se bloquea
    assert [r.intent.symbol for r in book.unresolved()] == ["BTCUSDT"]


def test_resolve_requires_consistent_answers():
    found = OrderStatus("FILLED", 1.0)
    exchange = FakeExchange(answers=[None, found, None, found, found])
    with pytest.raises(StopTheDay, match="coherente"):
        resolve(exchange, BUY, no_sleep)
    exchange = FakeExchange(answers=[None, found, found, found])
    assert resolve(exchange, BUY, no_sleep) == found
    exchange = FakeExchange(answers=[GatewayUnknown(), None, GatewayUnknown(), None, None])
    with pytest.raises(StopTheDay):
        resolve(exchange, BUY, no_sleep)
    pauses = []
    resolve(FakeExchange(answers=[None, None, None]), BUY, pauses.append)
    assert pauses == [2.0, 2.0]


# --- adjudicación manual -------------------------------------------------------------


def lost_order(tmp_path):
    book, exchange = ledger(tmp_path), FakeExchange("timeout_lost")
    with pytest.raises(StopTheDay):
        execute_intent(book, exchange, BUY, no_sleep)
    return book, exchange


def test_adjudication_requires_approval_coverage_and_absence(tmp_path):
    book, exchange = lost_order(tmp_path)
    with pytest.raises(StopTheDay, match="aprobación"):
        adjudicate_not_sent(book, exchange, BUY.client_order_id, " ", True, no_sleep)
    with pytest.raises(StopTheDay, match="cobertura"):
        adjudicate_not_sent(book, exchange, BUY.client_order_id, "ok usuario", False, no_sleep)
    exchange.orders[BUY.client_order_id] = FILLED
    with pytest.raises(StopTheDay, match="existe"):
        adjudicate_not_sent(book, exchange, BUY.client_order_id, "ok usuario", True, no_sleep)
    del exchange.orders[BUY.client_order_id]
    record = adjudicate_not_sent(book, exchange, BUY.client_order_id, "ok usuario", True, no_sleep)
    assert (record.state, record.status) == ("ADJUDICATED_NOT_SENT", "NOT_SENT")
    assert events(book, BUY.client_order_id) == ["INTENT", "SENT", "UNKNOWN",
                                                 "ADJUDICATED_NOT_SENT"]
    # el historial se conserva y la intención no se reenvía automáticamente
    execute_intent(book, exchange, BUY, no_sleep)
    assert exchange.posts == [BUY.client_order_id]
    assert book._rows[-1][11] == "aprobación: ok usuario"


def test_nothing_to_adjudicate_for_final_or_unknown_ids(tmp_path):
    book = ledger(tmp_path)
    execute_intent(book, FakeExchange(), BUY, no_sleep)
    for client_order_id in (BUY.client_order_id, "bt-SOLUSDT-20261012-B"):
        with pytest.raises(StopTheDay, match="nada que adjudicar"):
            adjudicate_not_sent(book, FakeExchange(), client_order_id, "ok", True, no_sleep)


# --- integridad del registro ---------------------------------------------------------


def test_ledger_survives_reload_and_feeds_check_limits(tmp_path):
    book = ledger(tmp_path)
    execute_intent(book, FakeExchange(), BUY, no_sleep)
    execute_intent(book, FakeExchange(), SELL, no_sleep)
    again = OrderLedger(book.path)
    assert again.orders_on(DAY.date()) == [BUY, SELL]
    assert again.orders_on(DAY.date() + timedelta(days=1)) == []
    assert again.records() == book.records()


@pytest.mark.parametrize("damage", ["truncate", "edit", "drop_anchor", "drop_ledger", "reorder"])
def test_damaged_ledger_stops(tmp_path, damage):
    book = ledger(tmp_path)
    execute_intent(book, FakeExchange(), BUY, no_sleep)
    content = book.path.read_bytes()
    if damage == "truncate":
        book.path.write_bytes(content[: content.rindex(b"\n", 0, len(content) - 1) + 1])
    elif damage == "edit":
        book.path.write_bytes(content.replace(b"FILLED", b"CANCELED"))
    elif damage == "drop_anchor":
        book.anchor.unlink()
    elif damage == "drop_ledger":
        book.path.unlink()
    else:
        lines = content.split(b"\n")
        lines[1], lines[2] = lines[2], lines[1]
        book.path.write_bytes(b"\n".join(lines))
    with pytest.raises(LedgerIntegrityError):
        OrderLedger(book.path)


def test_default_location_is_outside_the_repository(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_ledger_path() == tmp_path / "BotTrading" / "demo" / "orders.csv"
    monkeypatch.delenv("LOCALAPPDATA")
    with pytest.raises(StopTheDay):
        default_ledger_path()
