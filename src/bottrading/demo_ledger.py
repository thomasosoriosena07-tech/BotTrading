"""Registro privado de órdenes demo y protocolo de envío idempotente (D030, F2b-1).

Sin red: el protocolo usa una interfaz `Gateway` (consultar y enviar una
orden). No existe ninguna implementación real de envío: llegará en F4,
solo tras la aprobación (b) de D030. Las pruebas usan un servidor
simulado con la semántica documentada de Binance.

Registro (D030, punto 5): CSV de eventos solo de añadir, FUERA del
repositorio (%USERPROFILE%\\.bottrading\\demo\\orders.csv), con un ancla
(filas y SHA-256). Cada transición se escribe de forma atómica ANTES del
paso de red correspondiente:

    INTENT -> SENT -> ACK | UNKNOWN -> FINAL

- INTENT sin SENT: el envío no empezó; se puede continuar el protocolo.
- SENT o UNKNOWN: pudo enviarse; NUNCA se reenvía. Solo se resuelve por
  consultas (máximo 5, se exigen 3 respuestas consecutivas iguales); si no
  aparece, se detiene el día y queda para adjudicación manual.
- Binance acepta un clientOrderId repetido si la orden anterior está
  FILLED: por eso antes de cualquier envío se consulta (también con 3
  respuestas iguales) y el registro, no el servidor, garantiza la
  idempotencia. Repetir la misma intención envía 0 órdenes.
"""

import csv
import hashlib
import io
import os
import sys
import time
import weakref
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol

from bottrading.execution import CLIENT_ORDER_ID_PATTERN, OrderIntent
from bottrading.strategy import Signal

FINAL_STATUSES = frozenset({"FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH",
                            "REJECTED", "NOT_SENT"})
OPEN_STATUSES = frozenset({"NEW", "PENDING_NEW", "PARTIALLY_FILLED"})
QUERY_ATTEMPTS = 5
CONSISTENT_ANSWERS = 3
QUERY_PAUSE_SECONDS = 2.0
COLUMNS = ["seq", "at", "client_order_id", "event", "symbol", "side", "signal_day",
           "quote_amount", "quantity", "status", "executed_qty", "detail"]
EVENTS = ("INTENT", "SENT", "ACK", "UNKNOWN", "FINAL", "ADJUDICATED_NOT_SENT")


REPO_ROOT = Path(__file__).resolve().parents[2]
# Carpetas donde el estado privado NO puede vivir: el repositorio (se publica),
# OneDrive (se sincroniza a la nube) y AppData (el Python de Microsoft Store
# virtualiza esas escrituras y las borra al desinstalarse o cambiar de versión).
FORBIDDEN_ROOT_VARIABLES = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial",
                            "LOCALAPPDATA", "APPDATA")


def default_ledger_path() -> Path:
    """%USERPROFILE%\\.bottrading\\demo\\orders.csv (D030): local, estable y privado."""
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not home:
        raise StopTheDay("USERPROFILE no definida: no hay ubicación privada para el registro")
    path = Path(home) / ".bottrading" / "demo" / "orders.csv"
    check_private_location(path)
    return path


ERROR_NO_MORE_ITEMS = 259  # fin normal de la enumeración de subclaves


def onedrive_registry_roots(registry=None) -> list[Path]:
    """Carpetas que OneDrive sincroniza de verdad, según el registro de Windows
    (HKCU\\Software\\Microsoft\\OneDrive\\Accounts\\*\\UserFolder).

    Fallo cerrado (revisión de Codex): solo la AUSENCIA de la clave o del
    valor (FileNotFoundError) y el fin de la enumeración (error 259) son
    normales; cualquier otro error de lectura (p. ej. permisos) detiene,
    porque podría ocultar una carpeta sincronizada con nombre no habitual.
    `registry` permite inyectar un winreg simulado en las pruebas.
    """
    if registry is None:
        if sys.platform != "win32":
            return []
        import winreg as registry
    roots, unexpected = [], None
    try:
        accounts = registry.OpenKey(registry.HKEY_CURRENT_USER,
                                    r"Software\Microsoft\OneDrive\Accounts")
    except FileNotFoundError:
        return []  # OneDrive no está configurado para este usuario
    except OSError as error:
        accounts, unexpected = None, type(error).__name__
    if accounts is not None:
        with accounts:
            index = 0
            while unexpected is None:
                try:
                    name = registry.EnumKey(accounts, index)
                except OSError as error:
                    if getattr(error, "winerror", None) != ERROR_NO_MORE_ITEMS:
                        unexpected = type(error).__name__
                    break
                index += 1
                folder = None
                try:
                    with registry.OpenKey(accounts, name) as account:
                        folder, _ = registry.QueryValueEx(account, "UserFolder")
                except FileNotFoundError:
                    folder = None  # cuenta sin carpeta sincronizada
                except OSError as error:
                    unexpected = type(error).__name__
                if isinstance(folder, str) and folder:
                    roots.append(Path(folder))
    if unexpected is not None:
        raise StopTheDay(f"no se pudo leer la configuración de OneDrive del registro "
                         f"({unexpected}): no se puede garantizar una ubicación privada")
    return roots


def check_private_location(path: Path,
                           registry_roots: Callable[[], list[Path]] = onedrive_registry_roots
                           ) -> None:
    """Se niega a usar una carpeta privada dentro del repositorio, OneDrive o AppData.

    OneDrive se detecta por tres vías (revisión de Codex): variables de
    entorno, carpetas sincronizadas declaradas en el registro y, como
    respaldo, cualquier carpeta de la ruta cuyo nombre empiece por
    "OneDrive". La ruta se resuelve antes (enlaces, relativas, mayúsculas).
    """
    resolved = path.resolve()
    roots = [REPO_ROOT] + [Path(os.environ[name]) for name in FORBIDDEN_ROOT_VARIABLES
                           if os.environ.get(name)] + list(registry_roots())
    for root in roots:
        if resolved.is_relative_to(root.resolve()):
            raise StopTheDay(f"ubicación privada no permitida (dentro de {root}): "
                             "debe estar fuera del repositorio, OneDrive y AppData")
    if any(part.casefold().startswith("onedrive") for part in resolved.parts):
        raise StopTheDay(f"ubicación privada no permitida (carpeta OneDrive en {resolved}): "
                         "debe estar fuera del repositorio, OneDrive y AppData")


class LedgerIntegrityError(RuntimeError):
    """El registro privado no coincide con su ancla: detenerse (D030)."""


class StopTheDay(RuntimeError):
    """Situación que exige detenerse sin enviar nada más ese día."""


# --- interfaz con el exchange (sin implementación real hasta F4) ---------------------


@dataclass(frozen=True)
class OrderStatus:
    status: str
    executed_qty: float

    @property
    def final(self) -> bool:
        return self.status in FINAL_STATUSES


class GatewayUnknown(Exception):
    """Sin respuesta concluyente (timeout, 5XX, -1007, 429/418, corte)."""


class GatewayRejected(Exception):
    """Rechazo definitivo antes de ejecutarse (p. ej. filtros, saldo).

    Contrato del adaptador (revisión de Codex): solo para respuestas 4XX con
    un código de rechazo previo al motor (-1013, -2010 salvo duplicado,
    -1100...). Todo lo ambiguo (5XX, -1007, timeouts, 429/418, cortes) es
    GatewayUnknown. Aun así, el protocolo consulta tras un rechazo.
    """

    def __init__(self, code: int | None):
        self.code = code
        super().__init__(f"orden rechazada (código {code})")


class DuplicateOrder(Exception):
    """'Duplicate order sent.': el id ya existe; se consulta, no se reenvía."""


class Gateway(Protocol):
    def query(self, intent: OrderIntent) -> OrderStatus | None:
        """Estado de la orden por clientOrderId; None si no existe (-2013)."""

    def submit(self, intent: OrderIntent) -> OrderStatus:
        """Envía la orden MARKET; puede lanzar GatewayUnknown/Rejected/DuplicateOrder."""


# --- instancia única ----------------------------------------------------------------


class InstanceLock:
    """Bloqueo exclusivo NO bloqueante sobre orders.lock (revisión de Codex).

    msvcrt/fcntl: el sistema operativo lo libera si el proceso muere, así que
    no quedan bloqueos huérfanos. Una segunda instancia se detiene.
    """

    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        locked = True
        try:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            locked = False
        if not locked:
            handle.close()
            raise StopTheDay("otra instancia usa el registro de órdenes: detenerse")
        self._handle = handle

    @property
    def held(self) -> bool:
        return self._handle is not None

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


# --- registro de eventos con ancla ---------------------------------------------------


@dataclass(frozen=True)
class OrderRecord:
    intent: OrderIntent
    state: str  # último evento
    status: str | None
    executed_qty: float | None

    @property
    def final(self) -> bool:
        return self.state in ("FINAL", "ADJUDICATED_NOT_SENT")


class OrderLedger:
    """CSV de eventos solo de añadir con ancla `orders.state` (filas y SHA-256).

    Abrirlo toma el bloqueo de instancia única hasta close() (o fin del
    `with`). Solo se crea con `create=True` (inicialización explícita): si
    faltan registro y ancla a la vez NO es un inicio limpio, es una pérdida
    y hay que detenerse (revisión de Codex; la reconciliación de F2b-2
    detecta además órdenes bt- del exchange que no estén en el registro).
    """

    def __init__(self, path: Path, clock: Callable[[], datetime] | None = None,
                 *, create: bool = False):
        self.path = path
        self.anchor = path.with_name("orders.state")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = InstanceLock(path.with_name("orders.lock"))
        self._lock.acquire()
        try:
            self._rows = self._load(create)
        except BaseException:
            self._lock.release()
            raise

    def close(self) -> None:
        self._lock.release()

    def __enter__(self) -> "OrderLedger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _load(self, create: bool) -> list[list[str]]:
        has_ledger, has_anchor = self.path.exists(), self.anchor.exists()
        if create:
            if has_ledger or has_anchor:
                raise LedgerIntegrityError("el registro ya existe: no se reinicializa")
            self._write([])
            return []
        if not has_ledger and not has_anchor:
            raise LedgerIntegrityError("registro de órdenes inexistente: si es el primer uso, "
                                       "inicialízalo explícitamente; si no, investiga su pérdida")
        if has_ledger != has_anchor:
            raise LedgerIntegrityError("registro o ancla ausente: detenerse (D030)")
        content = self.path.read_bytes()
        fields = dict(line.split("=", 1) for line in
                      self.anchor.read_text(encoding="utf-8").splitlines() if "=" in line)
        rows = list(csv.reader(io.StringIO(content.decode("utf-8"))))
        if rows[:1] != [COLUMNS]:
            raise LedgerIntegrityError("registro con cabecera inesperada")
        rows = rows[1:]
        if fields.get("rows") != str(len(rows)) or \
                fields.get("sha256") != hashlib.sha256(content).hexdigest():
            raise LedgerIntegrityError("el registro no coincide con su ancla: detenerse (D030)")
        for number, row in enumerate(rows, 1):
            if len(row) != len(COLUMNS) or row[0] != str(number) or row[3] not in EVENTS:
                raise LedgerIntegrityError(f"fila {number} del registro con formato inesperado")
        return rows

    def append(self, intent: OrderIntent, event: str, status: str | None = None,
               executed_qty: float | None = None, detail: str = "") -> None:
        """Añade un evento y reescribe registro y ancla de forma atómica."""
        if event not in EVENTS:
            raise ValueError(f"evento desconocido: {event}")
        if not self._lock.held:
            raise StopTheDay("registro cerrado: no se puede escribir sin el bloqueo")
        row = [str(len(self._rows) + 1), self._clock().isoformat(), intent.client_order_id,
               event, intent.symbol, intent.side.value, intent.signal_time.date().isoformat(),
               _number(intent.quote_amount), _number(intent.quantity), status or "",
               _number(executed_qty), detail]
        self._write([*self._rows, row])

    def _write(self, rows: list[list[str]]) -> None:
        content = _render(rows)
        _write_atomic(self.path, content)
        _write_atomic(self.anchor, f"rows={len(rows)}\nsha256="
                      f"{hashlib.sha256(content).hexdigest()}\n".encode("utf-8"))
        self._rows = rows

    def records(self) -> dict[str, OrderRecord]:
        """Último estado de cada orden, por clientOrderId."""
        records: dict[str, OrderRecord] = {}
        for row in self._rows:
            intent = _intent_from_row(row)
            previous = records.get(row[2])
            status = row[9] or (previous.status if previous else None)
            executed = float(row[10]) if row[10] else (previous.executed_qty if previous else None)
            records[row[2]] = OrderRecord(intent, row[3], status, executed)
        return records

    def record(self, client_order_id: str) -> OrderRecord | None:
        return self.records().get(client_order_id)

    def orders_on(self, day: date) -> list[OrderIntent]:
        """Intenciones registradas para un día de señal (para check_limits)."""
        return [r.intent for r in self.records().values()
                if r.intent.signal_time.date() == day]

    def unresolved(self, symbol: str | None = None) -> list[OrderRecord]:
        """Órdenes no finales: bloquean nuevas órdenes de su símbolo (D030, punto 4)."""
        return [r for r in self.records().values()
                if not r.final and (symbol is None or r.intent.symbol == symbol)]


def _number(value: float | None) -> str:
    return "" if value is None else repr(float(value))


def _intent_from_row(row: list[str]) -> OrderIntent:
    signal_time = datetime.combine(date.fromisoformat(row[6]), datetime.min.time(),
                                   tzinfo=timezone.utc)
    intent = OrderIntent(row[4], Signal(row[5]), signal_time,
                         quote_amount=float(row[7]) if row[7] else None,
                         quantity=float(row[8]) if row[8] else None)
    if intent.client_order_id != row[2]:
        raise LedgerIntegrityError(f"fila {row[0]}: clientOrderId incoherente")
    return intent


def _render(rows: Sequence[Sequence[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    with open(temporary, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


# --- protocolo -----------------------------------------------------------------------


def resolve(gateway: Gateway, intent: OrderIntent,
            sleep: Callable[[float], None] = time.sleep) -> OrderStatus | None:
    """Consulta hasta QUERY_ATTEMPTS veces; exige CONSISTENT_ANSWERS iguales seguidas.

    Devuelve el estado (o None si la orden no existe). Si no hay respuesta
    coherente, lanza StopTheDay: nunca se decide con una sola consulta.
    """
    previous, streak = object(), 0
    for attempt in range(QUERY_ATTEMPTS):
        if attempt:
            sleep(QUERY_PAUSE_SECONDS)
        try:
            answer = gateway.query(intent)
        except GatewayUnknown:
            previous, streak = object(), 0
            continue
        streak = streak + 1 if answer == previous else 1
        previous = answer
        if streak >= CONSISTENT_ANSWERS:
            return answer
    raise StopTheDay(f"{intent.client_order_id}: consultas sin respuesta coherente")


def execute_intent(ledger: OrderLedger, gateway: Gateway, intent: OrderIntent,
                   sleep: Callable[[float], None] = time.sleep) -> OrderRecord:
    """Lleva una intención a un estado conocido sin enviarla nunca dos veces.

    Lanza StopTheDay si la orden pudo enviarse y no aparece, o si las
    consultas no son coherentes; queda para adjudicación manual.
    """
    if not CLIENT_ORDER_ID_PATTERN.fullmatch(intent.client_order_id):
        raise ValueError("clientOrderId fuera de formato")
    record = ledger.record(intent.client_order_id)
    if record is not None and record.intent != intent:
        raise StopTheDay(f"{intent.client_order_id}: intención distinta de la registrada")
    if record is not None and record.final:
        return record  # repetir la misma intención envía 0
    if record is not None and record.state != "INTENT":
        return _adopt_or_stop(ledger, gateway, intent, sleep)  # SENT/ACK/UNKNOWN: nunca reenviar
    blocking = [r for r in ledger.unresolved(intent.symbol)
                if r.intent.client_order_id != intent.client_order_id]
    if blocking:
        raise StopTheDay(f"{intent.symbol}: orden previa sin resolver "
                         f"({blocking[0].intent.client_order_id})")
    if record is None:
        ledger.append(intent, "INTENT")

    existing = resolve(gateway, intent, sleep)  # obligatorio: el servidor admite ids repetidos
    if existing is not None:
        return _store(ledger, intent, existing, "adoptada antes de enviar")

    ledger.append(intent, "SENT")  # ANTES del envío
    rejected, code = False, None
    try:
        status = gateway.submit(intent)
    except GatewayRejected as error:
        status, rejected, code = None, True, error.code
    except (GatewayUnknown, DuplicateOrder):
        status = None
    if rejected:
        # Se consulta aunque el adaptador diga "rechazo": una orden ejecutada
        # no debe quedar oculta como REJECTED (revisión de Codex).
        found = resolve(gateway, intent, sleep)
        if found is not None:
            return _store(ledger, intent, found, f"existía pese al rechazo {code}")
        ledger.append(intent, "FINAL", "REJECTED", 0.0, f"código {code}")
        return ledger.record(intent.client_order_id)
    if status is None:
        ledger.append(intent, "UNKNOWN")
        return _adopt_or_stop(ledger, gateway, intent, sleep)
    return _store(ledger, intent, status)


def _adopt_or_stop(ledger: OrderLedger, gateway: Gateway, intent: OrderIntent,
                   sleep: Callable[[float], None]) -> OrderRecord:
    found = resolve(gateway, intent, sleep)
    if found is None:
        raise StopTheDay(f"{intent.client_order_id}: pudo enviarse y no aparece; "
                         "requiere adjudicación manual")
    return _store(ledger, intent, found)


def _store(ledger: OrderLedger, intent: OrderIntent, status: OrderStatus,
           detail: str = "") -> OrderRecord:
    record = ledger.record(intent.client_order_id)
    unchanged = record is not None and (record.status, record.executed_qty) == \
        (status.status, status.executed_qty) and record.state in ("ACK", "FINAL")
    if not unchanged:
        ledger.append(intent, "FINAL" if status.final else "ACK", status.status,
                      status.executed_qty, detail)
    return ledger.record(intent.client_order_id)


@dataclass(frozen=True, eq=False)
class CoverageProof:
    """Resultado de la reconciliación (F2b-2): historial de órdenes y fills
    de `symbols` revisado por completo desde `since`. No es un booleano suelto
    (revisión de Codex): debe cubrir el símbolo y el día de la orden.

    Procedencia: adjudicate_not_sent solo acepta los objetos EMITIDOS por
    issue_coverage_proof (registro de identidades); uno construido a mano se
    rechaza. Dentro de un mismo proceso de Python nada es infalsificable:
    saltárselo exigiría usar deliberadamente esa función, y un test estático
    comprueba que solo la llama demo_reconcile.py.
    """

    symbols: frozenset[str]
    since: date
    complete: bool


_ISSUED_PROOFS: "weakref.WeakSet[CoverageProof]" = weakref.WeakSet()


def issue_coverage_proof(symbols: frozenset[str], since: date) -> CoverageProof:
    """Solo para demo_reconcile, al final de una reconciliación completa."""
    proof = CoverageProof(frozenset(symbols), since, True)
    _ISSUED_PROOFS.add(proof)
    return proof


def is_issued_coverage_proof(proof: object) -> bool:
    return isinstance(proof, CoverageProof) and proof in _ISSUED_PROOFS


def adjudicate_not_sent(ledger: OrderLedger, gateway: Gateway, client_order_id: str,
                        approval: str, coverage: CoverageProof,
                        sleep: Callable[[float], None] = time.sleep) -> OrderRecord:
    """Marca como NO enviada una orden SENT/UNKNOWN que no aparece (D030, punto 5).

    Requiere la aprobación explícita del usuario (la recogerá de forma
    interactiva el comando de F4), una prueba de cobertura completa de la
    reconciliación que incluya el símbolo y el día, y 3 consultas coherentes
    de "no existe". Conserva todo el historial. La señal no se repite sola.
    """
    record = ledger.record(client_order_id)
    if record is None or record.final or record.state == "INTENT":
        raise StopTheDay(f"{client_order_id}: no hay nada que adjudicar")
    if not approval.strip():
        raise StopTheDay("la adjudicación requiere la aprobación explícita del usuario")
    if not (is_issued_coverage_proof(coverage) and coverage.complete
            and record.intent.symbol in coverage.symbols
            and coverage.since <= record.intent.signal_time.date()):
        raise StopTheDay("la adjudicación requiere cobertura completa de la reconciliación "
                         "para ese símbolo y día")
    if resolve(gateway, record.intent, sleep) is not None:
        raise StopTheDay(f"{client_order_id}: la orden existe; se adopta, no se adjudica")
    ledger.append(record.intent, "ADJUDICATED_NOT_SENT", "NOT_SENT", 0.0,
                  f"aprobación: {approval.strip()}")
    return ledger.record(client_order_id)
