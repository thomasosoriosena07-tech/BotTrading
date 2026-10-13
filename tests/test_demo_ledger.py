"""Registro privado y protocolo idempotente (D030, F2b-1) con un servidor simulado."""

import subprocess
import sys
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

import pytest

from bottrading.demo_ledger import (
    CoverageProof,
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
    issue_coverage_proof,
    resolve,
)
from bottrading.execution import OrderIntent
from bottrading.strategy import Signal

DAY = datetime(2026, 10, 12, tzinfo=timezone.utc)
BUY = OrderIntent("BTCUSDT", Signal.BUY, DAY, quote_amount=1000.0)
SELL = OrderIntent("ETHUSDT", Signal.SELL, DAY, quantity=0.5)
FILLED = OrderStatus("FILLED", 0.0123)
CLOCK = lambda: datetime(2026, 10, 13, 0, 5, tzinfo=timezone.utc)  # noqa: E731
COVERAGE = issue_coverage_proof(frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"}), date(2026, 10, 1))


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
        if outcome == "reject_but_filled":
            raise GatewayRejected(-2010)  # adaptador que clasifica mal una respuesta
        if outcome == "timeout_after_fill":
            raise GatewayUnknown()  # se ejecutó, pero la respuesta no llegó
        if outcome == "timeout_lost":
            del self.orders[intent.client_order_id]
            raise GatewayUnknown()  # no llegó al motor
        return FILLED


def no_sleep(seconds):
    pass


@pytest.fixture
def book(tmp_path):
    ledger = OrderLedger(tmp_path / "orders.csv", CLOCK, create=True)
    yield ledger
    ledger.close()


def reopen(ledger):
    ledger.close()
    return OrderLedger(ledger.path, CLOCK)


def events(ledger, client_order_id):
    return [row[3] for row in ledger._rows if row[2] == client_order_id]


# --- envío normal e idempotencia -----------------------------------------------------


def test_normal_flow_writes_intent_and_sent_before_the_post(book):
    exchange = FakeExchange()
    record = execute_intent(book, exchange, BUY, no_sleep)
    assert (record.state, record.status, record.executed_qty) == ("FINAL", "FILLED", 0.0123)
    assert events(book, BUY.client_order_id) == ["INTENT", "SENT", "FINAL"]
    assert exchange.posts == [BUY.client_order_id]
    assert exchange.queries == 3  # 3 "no existe" coherentes antes de enviar


def test_repeating_the_same_intent_sends_zero_even_if_server_would_accept(book):
    # D030 / revisión de Codex: el servidor ACEPTARÍA el mismo id (anterior FILLED).
    exchange = FakeExchange()
    execute_intent(book, exchange, BUY, no_sleep)
    ledger = book
    for _ in range(3):
        execute_intent(ledger, exchange, BUY, no_sleep)
        ledger = reopen(ledger)  # nueva ejecución
        execute_intent(ledger, exchange, BUY, no_sleep)
    ledger.close()
    assert exchange.posts == [BUY.client_order_id]


def test_existing_order_is_adopted_without_posting(book):
    exchange = FakeExchange()
    exchange.orders[BUY.client_order_id] = FILLED
    record = execute_intent(book, exchange, BUY, no_sleep)
    assert record.status == "FILLED" and exchange.posts == []


def test_rejection_is_confirmed_by_query_final_and_not_retried(book):
    exchange = FakeExchange("reject")
    record = execute_intent(book, exchange, SELL, no_sleep)
    assert (record.state, record.status) == ("FINAL", "REJECTED")
    assert exchange.queries == 6  # 3 antes de enviar y 3 tras el rechazo
    execute_intent(book, exchange, SELL, no_sleep)
    assert exchange.posts == [SELL.client_order_id]


def test_misclassified_rejection_does_not_hide_an_executed_order(book):
    # Revisión de Codex: un GatewayRejected erróneo no debe ocultar un FILLED.
    exchange = FakeExchange("reject_but_filled")
    record = execute_intent(book, exchange, BUY, no_sleep)
    assert (record.state, record.status) == ("FINAL", "FILLED")
    assert exchange.posts == [BUY.client_order_id]


def test_same_id_with_different_content_is_refused(book):
    execute_intent(book, FakeExchange(), BUY, no_sleep)
    changed = OrderIntent("BTCUSDT", Signal.BUY, DAY, quote_amount=999.0)
    with pytest.raises(StopTheDay, match="distinta"):
        execute_intent(book, FakeExchange(), changed, no_sleep)


# --- estados ambiguos ----------------------------------------------------------------


def test_timeout_after_execution_is_resolved_by_query_not_resent(book):
    exchange = FakeExchange("timeout_after_fill")
    record = execute_intent(book, exchange, BUY, no_sleep)
    assert record.status == "FILLED"
    assert events(book, BUY.client_order_id) == ["INTENT", "SENT", "UNKNOWN", "FINAL"]
    assert exchange.posts == [BUY.client_order_id]


def test_timeout_without_execution_stops_the_day_and_never_resends(book):
    exchange = FakeExchange("timeout_lost")
    with pytest.raises(StopTheDay, match="adjudicación"):
        execute_intent(book, exchange, BUY, no_sleep)
    ledger = book
    for _ in range(2):  # reinicios: siguen sin reenviar
        ledger = reopen(ledger)
        with pytest.raises(StopTheDay):
            execute_intent(ledger, exchange, BUY, no_sleep)
    assert exchange.posts == [BUY.client_order_id]
    assert ledger.record(BUY.client_order_id).state == "UNKNOWN"
    ledger.close()


def test_duplicate_answer_is_treated_as_existing_order(book):
    exchange = FakeExchange()
    exchange.orders[BUY.client_order_id] = OrderStatus("NEW", 0.0)
    exchange.answers = [None, None, None]  # consultas previas no la ven (inconsistencia)
    record = execute_intent(book, exchange, BUY, no_sleep)
    assert record.status == "NEW" and record.state == "ACK"
    assert exchange.posts == [BUY.client_order_id]  # un solo intento, rechazado por duplicado


def test_crash_after_sent_never_resends(book):
    book.append(BUY, "INTENT")
    book.append(BUY, "SENT")  # el proceso murió durante el POST
    exchange = FakeExchange()
    ledger = reopen(book)
    with pytest.raises(StopTheDay):
        execute_intent(ledger, exchange, BUY, no_sleep)
    assert exchange.posts == []
    exchange.orders[BUY.client_order_id] = FILLED  # sí llegó: se adopta
    ledger = reopen(ledger)
    assert execute_intent(ledger, exchange, BUY, no_sleep).status == "FILLED"
    assert exchange.posts == []
    ledger.close()


def test_crash_after_intent_only_continues_the_protocol(book):
    book.append(BUY, "INTENT")  # murió antes de escribir SENT: el POST no empezó
    exchange = FakeExchange()
    ledger = reopen(book)
    assert execute_intent(ledger, exchange, BUY, no_sleep).status == "FILLED"
    assert exchange.posts == [BUY.client_order_id]
    ledger.close()


def test_partial_fill_blocks_new_orders_for_that_symbol(book):
    record = execute_intent(book, FakeExchange("partial"), BUY, no_sleep)
    assert (record.state, record.status) == ("ACK", "PARTIALLY_FILLED")
    later = OrderIntent("BTCUSDT", Signal.SELL, DAY + timedelta(days=1), quantity=0.005)
    with pytest.raises(StopTheDay, match="sin resolver"):
        execute_intent(book, FakeExchange(), later, no_sleep)
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


# --- instancia única e inicialización explícita (revisión de Codex) -----------------


def test_second_instance_is_refused_while_the_first_is_open(book):
    with pytest.raises(StopTheDay, match="otra instancia"):
        OrderLedger(book.path, CLOCK)
    book.close()
    with OrderLedger(book.path, CLOCK) as again:  # liberado: se puede abrir
        with pytest.raises(StopTheDay, match="otra instancia"):
            OrderLedger(book.path, CLOCK)
        assert again.records() == {}


def test_lock_works_across_real_processes(book):
    # Otro proceso de Python (sin red) intenta abrir el registro mientras está abierto.
    code = ("import sys; from pathlib import Path; "
            "from bottrading.demo_ledger import OrderLedger, StopTheDay\n"
            "try:\n    OrderLedger(Path(sys.argv[1]))\n"
            "except StopTheDay:\n    sys.exit(3)\nsys.exit(0)")
    run = lambda: subprocess.run([sys.executable, "-c", code, str(book.path)],  # noqa: E731
                                 capture_output=True, timeout=60).returncode
    assert run() == 3
    book.close()
    assert run() == 0


def test_lock_is_released_when_the_owner_process_is_killed(book):
    # Revisión de Codex: el SO debe liberar el bloqueo si el proceso muere de golpe.
    book.close()
    code = ("import sys, time; from pathlib import Path; "
            "from bottrading.demo_ledger import OrderLedger\n"
            "ledger = OrderLedger(Path(sys.argv[1]))\n"
            "print('abierto', flush=True)\ntime.sleep(60)")
    owner = subprocess.Popen([sys.executable, "-c", code, str(book.path)],
                             stdout=subprocess.PIPE, text=True)
    try:
        assert owner.stdout.readline().strip() == "abierto"
        with pytest.raises(StopTheDay, match="otra instancia"):
            OrderLedger(book.path, CLOCK)
        owner.kill()  # terminación abrupta, sin close()
        owner.wait(timeout=30)
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.stdout.close()
    with OrderLedger(book.path, CLOCK) as again:
        assert again.records() == {}


def test_concurrent_runs_cannot_both_post(book):
    # Dos ejecuciones: la segunda no puede ni abrir el registro mientras la primera trabaja.
    exchange = FakeExchange()
    execute_intent(book, exchange, BUY, no_sleep)
    with pytest.raises(StopTheDay):
        execute_intent(OrderLedger(book.path, CLOCK), exchange, BUY, no_sleep)
    assert exchange.posts == [BUY.client_order_id]


def test_closed_ledger_cannot_write(book):
    book.close()
    with pytest.raises(StopTheDay, match="cerrado"):
        book.append(BUY, "INTENT")


def test_missing_ledger_is_not_a_clean_start(tmp_path):
    with pytest.raises(LedgerIntegrityError, match="inexistente"):
        OrderLedger(tmp_path / "orders.csv", CLOCK)
    with OrderLedger(tmp_path / "orders.csv", CLOCK, create=True) as ledger:
        execute_intent(ledger, FakeExchange(), BUY, no_sleep)
    (tmp_path / "orders.csv").unlink()
    (tmp_path / "orders.state").unlink()  # pérdida conjunta tras haberse usado
    with pytest.raises(LedgerIntegrityError, match="inexistente"):
        OrderLedger(tmp_path / "orders.csv", CLOCK)
    # el bloqueo se liberó tras el error: falla por integridad, no por "otra instancia"
    with pytest.raises(LedgerIntegrityError, match="inexistente"):
        OrderLedger(tmp_path / "orders.csv", CLOCK)


def test_existing_ledger_is_never_reinitialized(book):
    execute_intent(book, FakeExchange(), BUY, no_sleep)
    book.close()
    with pytest.raises(LedgerIntegrityError, match="ya existe"):
        OrderLedger(book.path, CLOCK, create=True)
    with OrderLedger(book.path, CLOCK) as again:
        assert again.record(BUY.client_order_id).status == "FILLED"


# --- adjudicación manual -------------------------------------------------------------


def lost_order(book):
    exchange = FakeExchange("timeout_lost")
    with pytest.raises(StopTheDay):
        execute_intent(book, exchange, BUY, no_sleep)
    return exchange


def test_adjudication_requires_approval_coverage_and_absence(book):
    exchange = lost_order(book)
    with pytest.raises(StopTheDay, match="aprobación"):
        adjudicate_not_sent(book, exchange, BUY.client_order_id, " ", COVERAGE, no_sleep)
    bad_coverage = [
        True,  # un booleano suelto no es una prueba
        CoverageProof(COVERAGE.symbols, COVERAGE.since, True),  # fabricada a mano: no emitida
        issue_coverage_proof(frozenset({"ETHUSDT"}), COVERAGE.since),
        issue_coverage_proof(COVERAGE.symbols, date(2026, 10, 13)),  # empieza después
    ]
    for coverage in bad_coverage:
        with pytest.raises(StopTheDay, match="cobertura"):
            adjudicate_not_sent(book, exchange, BUY.client_order_id, "ok usuario", coverage,
                                no_sleep)
    exchange.orders[BUY.client_order_id] = FILLED
    with pytest.raises(StopTheDay, match="existe"):
        adjudicate_not_sent(book, exchange, BUY.client_order_id, "ok usuario", COVERAGE, no_sleep)
    del exchange.orders[BUY.client_order_id]
    record = adjudicate_not_sent(book, exchange, BUY.client_order_id, "ok usuario", COVERAGE,
                                 no_sleep)
    assert (record.state, record.status) == ("ADJUDICATED_NOT_SENT", "NOT_SENT")
    assert events(book, BUY.client_order_id) == ["INTENT", "SENT", "UNKNOWN",
                                                 "ADJUDICATED_NOT_SENT"]
    # el historial se conserva y la intención no se reenvía automáticamente
    execute_intent(book, exchange, BUY, no_sleep)
    assert exchange.posts == [BUY.client_order_id]
    assert book._rows[-1][11] == "aprobación: ok usuario"


def test_nothing_to_adjudicate_for_final_or_unknown_ids(book):
    execute_intent(book, FakeExchange(), BUY, no_sleep)
    for client_order_id in (BUY.client_order_id, "bt-SOLUSDT-20261012-B"):
        with pytest.raises(StopTheDay, match="nada que adjudicar"):
            adjudicate_not_sent(book, FakeExchange(), client_order_id, "ok", COVERAGE, no_sleep)


# --- integridad del registro ---------------------------------------------------------


def test_ledger_survives_reload_and_feeds_check_limits(book):
    execute_intent(book, FakeExchange(), BUY, no_sleep)
    execute_intent(book, FakeExchange(), SELL, no_sleep)
    before = book.records()
    with reopen(book) as again:
        assert again.orders_on(DAY.date()) == [BUY, SELL]
        assert again.orders_on(DAY.date() + timedelta(days=1)) == []
        assert again.records() == before


@pytest.mark.parametrize("damage", ["truncate", "edit", "drop_anchor", "drop_ledger", "reorder"])
def test_damaged_ledger_stops(book, damage):
    execute_intent(book, FakeExchange(), BUY, no_sleep)
    book.close()
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
        OrderLedger(book.path, CLOCK)


def test_crash_between_ledger_and_anchor_writes_fails_closed(book):
    execute_intent(book, FakeExchange(), BUY, no_sleep)
    book.close()
    anchor = book.anchor.read_bytes()
    with OrderLedger(book.path, CLOCK) as ledger:
        ledger.append(SELL, "INTENT")
    book.anchor.write_bytes(anchor)  # el ancla quedó en la versión anterior
    with pytest.raises(LedgerIntegrityError, match="ancla"):
        OrderLedger(book.path, CLOCK)


@pytest.fixture
def private_env(monkeypatch, tmp_path):
    for name in ("LOCALAPPDATA", "APPDATA", "OneDrive"):
        monkeypatch.setenv(name, str(tmp_path / name))
    for name in ("OneDriveConsumer", "OneDriveCommercial", "HOME"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_default_location_is_in_the_user_profile(monkeypatch, private_env):
    monkeypatch.setenv("USERPROFILE", str(private_env / "perfil"))
    assert default_ledger_path() == private_env / "perfil" / ".bottrading" / "demo" / "orders.csv"
    monkeypatch.delenv("USERPROFILE")
    with pytest.raises(StopTheDay, match="USERPROFILE"):
        default_ledger_path()


def test_onedrive_from_registry_or_folder_name_is_refused_without_env_vars(private_env):
    # Revisión de Codex: perfil sincronizado sin variables OneDrive* que lo indiquen.
    from bottrading.demo_ledger import check_private_location
    synced = private_env / "Sincronizado"
    with pytest.raises(StopTheDay, match="no permitida"):
        check_private_location(synced / ".bottrading" / "orders.csv", lambda: [synced])
    with pytest.raises(StopTheDay, match="carpeta OneDrive"):
        check_private_location(private_env / "OneDrive - Empresa" / "x" / "orders.csv", lambda: [])
    with pytest.raises(StopTheDay, match="carpeta OneDrive"):
        check_private_location(private_env / "onedrive-copia" / "orders.csv", lambda: [])
    check_private_location(private_env / "perfil" / ".bottrading" / "orders.csv", lambda: [])


def test_relative_paths_case_and_links_are_resolved_first(monkeypatch, private_env):
    from bottrading.demo_ledger import check_private_location
    synced = private_env / "Sincronizado"
    (synced / "dentro").mkdir(parents=True)
    monkeypatch.chdir(synced)
    with pytest.raises(StopTheDay, match="no permitida"):  # ruta relativa
        check_private_location(Path("dentro") / "orders.csv", lambda: [synced])
    upper = Path(str(synced).upper()) / "dentro" / "orders.csv"
    with pytest.raises(StopTheDay, match="no permitida"):  # mayúsculas (Windows)
        check_private_location(upper, lambda: [synced])
    link = private_env / "enlace"
    try:
        link.symlink_to(synced / "dentro", target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("no se pudo crear el enlace")
        # Unión de directorios: no requiere modo desarrollador ni administrador.
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(synced / "dentro")],
                       check=True, capture_output=True)
    with pytest.raises(StopTheDay, match="no permitida"):  # enlace hacia OneDrive
        check_private_location(link / "orders.csv", lambda: [synced])


class FakeRegistry:
    """winreg simulado: cuentas -> UserFolder o excepción."""

    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, accounts=None, open_root=None, enum_error=None):
        self.accounts, self.open_root, self.enum_error = accounts or {}, open_root, enum_error

    class Key:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, parent, name):
        if parent == self.HKEY_CURRENT_USER:
            if self.open_root:
                raise self.open_root
            return self.Key("root")
        return self.Key(name)

    def EnumKey(self, key, index):
        names = list(self.accounts)
        if index < len(names):
            return names[index]
        if self.enum_error:
            raise self.enum_error
        error = OSError("no more items")
        error.winerror = 259
        raise error

    def QueryValueEx(self, key, value):
        folder = self.accounts[key.name]
        if isinstance(folder, Exception):
            raise folder
        return folder, 1


def test_registry_absence_is_normal_but_other_read_errors_stop():
    # Revisión de Codex: fallo cerrado ante errores inesperados de lectura.
    from bottrading.demo_ledger import onedrive_registry_roots
    assert onedrive_registry_roots(FakeRegistry(open_root=FileNotFoundError())) == []
    assert onedrive_registry_roots(FakeRegistry(
        {"Personal": "C:\\Sinc", "Business1": FileNotFoundError(), "Vacia": ""})) == \
        [Path("C:\\Sinc")]
    for registry in (FakeRegistry(open_root=PermissionError()),
                     FakeRegistry({"Personal": PermissionError()}),
                     FakeRegistry({"Personal": "C:\\Sinc"}, enum_error=PermissionError())):
        with pytest.raises(StopTheDay, match="registro"):
            onedrive_registry_roots(registry)


def test_real_registry_reader_returns_paths():
    from bottrading.demo_ledger import onedrive_registry_roots
    assert all(isinstance(root, Path) for root in onedrive_registry_roots())


@pytest.mark.parametrize("inside", ["OneDrive", "LOCALAPPDATA", "APPDATA", "repo"])
def test_private_location_refuses_repo_onedrive_and_appdata(monkeypatch, private_env, inside):
    # El repositorio se publica, OneDrive se sincroniza y AppData lo virtualiza el
    # Python de la Store (y lo borra al desinstalarse): ninguno sirve.
    from bottrading.demo_ledger import REPO_ROOT
    home = REPO_ROOT if inside == "repo" else private_env / inside / "sub"
    monkeypatch.setenv("USERPROFILE", str(home))
    with pytest.raises(StopTheDay, match="no permitida"):
        default_ledger_path()
