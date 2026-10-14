"""Cliente de SOLO LECTURA para Binance Spot Demo Mode (D030, fase F2a).

Segundo y último módulo con acceso a red (junto a download.py). Solo
habla con https://demo-api.binance.com y solo con las peticiones de
lectura de la tabla cerrada `ENDPOINTS`: no existe código para enviar ni
cancelar órdenes (requiere la aprobación (b) de D030) ni para producción.

Barrera (D030, punto 1): cada petición se valida YA FIRMADA antes de
llegar al transporte (esquema, host exacto, puerto, ruta, método,
parámetros permitidos con su patrón, sin duplicados, firma al final y
recalculada). El transporte real ignora los proxies del entorno y
rechaza toda redirección.

Secretos (D030, punto 6): la credencial se lee del Administrador de
credenciales de Windows solo al firmar; nunca se registra, se guarda en
archivos ni aparece en mensajes de error (solo método, ruta, código
HTTP y código de Binance).

Uso (F3, solo lectura; ver D030):
    python -m bottrading.demo_client check      # credencial, hora, símbolos, cuenta
    python -m bottrading.demo_client init       # fija línea base y registro (confirmación)
    python -m bottrading.demo_client reconcile  # reconcilia cuenta y registro
"""

import argparse
import ctypes
import hashlib
import hmac
import http.client
import json
import logging
import re
import sys
import time
import urllib.error
import weakref
import urllib.parse
import urllib.request
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from bottrading.demo_ledger import (
    REPO_ROOT,
    DuplicateOrder,
    GatewayRejected,
    GatewayUnknown,
    LedgerIntegrityError,
    OrderLedger,
    OrderStatus,
    StopTheDay,
    default_ledger_path,
    execute_intent,
)
from bottrading.demo_reconcile import (
    load_baseline,
    reconcile,
    resign_baseline,
    save_baseline,
    symbol_info,
    take_baseline,
)
from bottrading.execution import (
    DEMO_SYMBOLS,
    LimitExceeded,
    OrderIntent,
    check_limits,
    target_intents,
)
from bottrading.paper import load_forward_candles
from bottrading.strategy import Signal

logger = logging.getLogger(__name__)

DEMO_HOST = "demo-api.binance.com"
BASE_URL = f"https://{DEMO_HOST}"
API_KEY_HEADER = "X-MBX-APIKEY"
CREDENTIAL_TARGET = "BotTrading-Demo"
NEW_CREDENTIAL_TARGET = "BotTrading-Demo-Nueva"  # solo durante una rotación (rekey)
RECV_WINDOW_MS = 5000  # D030: <= 5000
ORDERS_ENV = "BOTTRADING_DEMO_ORDERS"
TIMEOUT_SECONDS = 10


class DemoClientError(Exception):
    """Error del cliente demo. Su mensaje nunca contiene claves ni la query."""


class RequestRefused(DemoClientError):
    """La petición no supera la validación: no se llama al transporte."""


class CredentialError(DemoClientError):
    """No se pudo leer la credencial demo (sin detalles de su contenido)."""


class DemoApiError(DemoClientError):
    """Respuesta de error de la API, clasificada sin copiar el cuerpo."""

    def __init__(self, method: str, path: str, status: int | None,
                 code: int | None = None, retry_after: int | None = None,
                 duplicate: bool = False):
        self.method, self.path, self.status = method, path, status
        self.code, self.retry_after = code, retry_after
        self.duplicate = duplicate  # -2010 "Duplicate order sent." (sin guardar el texto)
        super().__init__(f"{method} {path}: {self.kind} (HTTP {status}, código {code})")

    @property
    def kind(self) -> str:
        """unknown: estado de ejecución desconocido (5XX, -1007); rate_limited:
        429/418 (respetar retry_after); transport: sin respuesta; rejected: resto."""
        if self.status is None:
            return "transport"
        if self.status in (418, 429):
            return "rate_limited"
        if self.status >= 500 or self.code == -1007:
            return "unknown"
        return "rejected"


# --- tabla cerrada de peticiones (D030, punto 1) ------------------------------------

_SYMBOL = "|".join(DEMO_SYMBOLS)
PATTERNS = {
    "symbol": re.compile(f"(?:{_SYMBOL})"),
    "timestamp": re.compile(r"[0-9]{13}"),
    "startTime": re.compile(r"[0-9]{13}"),
    "endTime": re.compile(r"[0-9]{13}"),
    "recvWindow": re.compile(r"[1-9][0-9]{0,3}|5000"),  # 1..5000 con la comprobación numérica
    "orderId": re.compile(r"[0-9]{1,20}"),
    "fromId": re.compile(r"[0-9]{1,20}"),
    "limit": re.compile(r"[1-9][0-9]{0,2}|1000"),  # 1..1000
    "origClientOrderId": re.compile(r"bt-[A-Za-z0-9_-]{1,33}"),
    "omitZeroBalances": re.compile(r"true|false"),
    # Órdenes (aprobación (b) de D030): solo MARKET, solo ids del bot, cantidades
    # decimales sin exponente ni signo.
    "side": re.compile(r"BUY|SELL"),
    "type": re.compile(r"MARKET"),
    "newClientOrderId": re.compile(r"bt-[A-Za-z0-9_-]{1,33}"),
    "quantity": re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,8})?"),
    "quoteOrderQty": re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,8})?"),
    "newOrderRespType": re.compile(r"RESULT"),
    "signature": re.compile(r"[0-9a-f]{64}"),
}


@dataclass(frozen=True)
class Endpoint:
    signed: bool
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()


def _signed(required: str = "", optional: str = "") -> Endpoint:
    return Endpoint(True, frozenset(required.split() + ["timestamp"]),
                    frozenset(optional.split() + ["recvWindow"]))


# POST/DELETE /api/v3/order: añadidos con la aprobación (b) de D030 (órdenes
# MARKET en la cuenta DEMO). Solo un DemoClient con un OrderConsent EMITIDO por
# grant_order_consent puede prepararlos; si no, el cliente es de solo lectura.
WRITE_METHODS = frozenset({"POST", "DELETE"})
ENDPOINTS: Mapping[tuple[str, str], Endpoint] = {
    ("GET", "/api/v3/time"): Endpoint(False),
    ("GET", "/api/v3/exchangeInfo"): Endpoint(False, frozenset({"symbol"})),
    ("GET", "/api/v3/ticker/bookTicker"): Endpoint(False, frozenset({"symbol"})),
    ("GET", "/api/v3/account"): _signed(optional="omitZeroBalances"),
    ("GET", "/api/v3/order"): _signed("symbol origClientOrderId"),
    ("GET", "/api/v3/openOrders"): _signed("symbol"),
    ("GET", "/api/v3/allOrders"): _signed("symbol", "orderId startTime endTime limit"),
    ("GET", "/api/v3/myTrades"): _signed("symbol", "orderId startTime endTime fromId limit"),
    ("POST", "/api/v3/order"): _signed("symbol side type newClientOrderId newOrderRespType",
                                       "quantity quoteOrderQty"),
    ("DELETE", "/api/v3/order"): _signed("symbol origClientOrderId"),
}


@dataclass(frozen=True)
class PreparedRequest:
    method: str
    url: str  # incluye la query firmada: nunca se registra ni se muestra
    path: str
    signed: bool

    def __repr__(self) -> str:
        return f"PreparedRequest({self.method} {self.path})"


def validate_request(method: str, url: str,
                     verify_signature: Callable[[str, str], bool] | None = None) -> str:
    """Comprueba la petición completa; devuelve la ruta o lanza RequestRefused.

    `verify_signature(payload, signature)` recalcula la firma para detectar
    una query alterada después de firmar.
    """
    # urlsplit elimina \n, \t y espacios: se rechazan antes para que lo
    # validado sea exactamente lo que se enviaría.
    if not re.fullmatch(r"[\x21-\x7e]+", url):
        raise RequestRefused("URL con espacios, caracteres de control o no ASCII")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise RequestRefused("esquema no permitido")
    if parts.netloc not in (DEMO_HOST, f"{DEMO_HOST}:443"):
        raise RequestRefused("host no permitido")  # cubre userinfo, puerto, mayúsculas, IP
    if parts.fragment or "%" in parts.path or ";" in parts.path:
        raise RequestRefused("ruta no permitida")
    endpoint = ENDPOINTS.get((method, parts.path))
    if endpoint is None:
        raise RequestRefused(f"petición no permitida: {method} {parts.path}")
    # Ningún error se lanza dentro de un except: así no queda en __context__
    # una excepción con la query (revisión de Codex).
    try:
        pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True,
                                       strict_parsing=bool(parts.query))
    except ValueError:
        pairs = None
    if pairs is None:
        raise RequestRefused(f"{parts.path}: query mal formada")
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise RequestRefused(f"{parts.path}: parámetros duplicados")
    allowed = endpoint.required | endpoint.optional | ({"signature"} if endpoint.signed else set())
    if not endpoint.required <= set(keys) or not set(keys) <= allowed:
        raise RequestRefused(f"{parts.path}: parámetros no permitidos o incompletos")
    for key, value in pairs:
        if not PATTERNS[key].fullmatch(value):
            raise RequestRefused(f"{parts.path}: valor no permitido en {key}")
    if "recvWindow" in keys and int(dict(pairs)["recvWindow"]) > RECV_WINDOW_MS:
        raise RequestRefused(f"{parts.path}: recvWindow mayor que {RECV_WINDOW_MS}")
    if method == "POST":
        values = dict(pairs)
        amount = "quoteOrderQty" if values["side"] == "BUY" else "quantity"
        if {"quantity", "quoteOrderQty"} & set(keys) != {amount} or float(values[amount]) <= 0:
            raise RequestRefused(f"{parts.path}: la compra va por quoteOrderQty y la venta "
                                 "por quantity, siempre mayores que 0")
    if urllib.parse.urlencode(pairs) != parts.query:
        raise RequestRefused(f"{parts.path}: query con codificación no canónica")
    if endpoint.signed:
        if keys[-1:] != ["signature"]:
            raise RequestRefused(f"{parts.path}: falta la firma al final")
        payload = urllib.parse.urlencode(pairs[:-1])
        if verify_signature is None or not verify_signature(payload, pairs[-1][1]):
            raise RequestRefused(f"{parts.path}: firma que no corresponde a la query")
    return parts.path


# --- credencial (D030, punto 6) ----------------------------------------------------


@dataclass(frozen=True)
class Credentials:
    api_key: str = field(repr=False)
    secret: str = field(repr=False)

    def __repr__(self) -> str:
        return "Credentials(<oculto>)"


def parse_credential(text: str) -> Credentials:
    """'APIKEY:SECRET' -> Credentials. El error nunca incluye el contenido."""
    api_key, separator, secret = text.strip().partition(":")
    if not separator or not re.fullmatch(r"[A-Za-z0-9]{16,128}", api_key) \
            or not re.fullmatch(r"[A-Za-z0-9]{16,128}", secret):
        raise CredentialError("credencial demo con formato inesperado (se espera APIKEY:SECRET)")
    return Credentials(api_key, secret)


def read_windows_credential(target: str = CREDENTIAL_TARGET) -> Credentials:
    """Lee la credencial genérica `target` del Administrador de credenciales.

    La crea el usuario con `cmdkey /generic:BotTrading-Demo /user:bottrading /pass`
    pegando APIKEY:SECRET cuando se le pide (D030).
    """
    if sys.platform != "win32":
        raise CredentialError("el Administrador de credenciales solo existe en Windows")
    from ctypes import wintypes

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                    ("UserName", wintypes.LPWSTR)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    pointer = ctypes.POINTER(CREDENTIALW)()
    if not advapi32.CredReadW(target, 1, 0, ctypes.byref(pointer)):  # 1 = CRED_TYPE_GENERIC
        raise CredentialError(f"no se pudo leer la credencial '{target}' "
                              f"(error de Windows {ctypes.get_last_error()})")
    try:
        credential = pointer.contents
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
    finally:
        advapi32.CredFree(pointer)
    return parse_credential(decode_credential_blob(blob))


def decode_credential_blob(blob: bytes) -> str:
    """UTF-16LE (formato de cmdkey). El error no conserva los bytes: el
    UnicodeDecodeError los llevaría en .object y en __context__."""
    try:
        text = blob.decode("utf-16-le")
    except UnicodeDecodeError:
        text = None
    if text is None:
        raise CredentialError("credencial demo con codificación inesperada")
    return text


# --- transporte ----------------------------------------------------------------------


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    url: str
    retry_after: int | None = None


Transport = Callable[[PreparedRequest, Mapping[str, str]], Response]


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Rechaza cualquier redirección (D030): en demo no hace falta ninguna."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RequestRefused(f"redirección rechazada (HTTP {code})")


def build_opener() -> urllib.request.OpenerDirector:
    # ProxyHandler({}) sustituye al que lee HTTPS_PROXY/HTTP_PROXY/ALL_PROXY.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirectHandler)


def urllib_transport(request: PreparedRequest, headers: Mapping[str, str],
                     credentials: Callable[[], Credentials] | None = None) -> Response:
    """Transporte real. Solo se usa en F3 en adelante; las pruebas lo sustituyen.

    Revalida TODA petición aunque no venga de DemoClient.prepare (revisión
    de Codex): estructura y, si es firmada, la firma recalculada con la
    credencial guardada y la cabecera de clave. Una firma inventada no pasa
    sin conocer el secreto.
    """
    verify = None  # sin endpoint conocido, validate_request rechaza sin leer la credencial
    endpoint = ENDPOINTS.get((request.method, urllib.parse.urlsplit(request.url).path))
    if endpoint is not None and endpoint.signed:
        stored = (credentials or read_windows_credential)()
        if not hmac.compare_digest(headers.get(API_KEY_HEADER, ""), stored.api_key):
            raise RequestRefused("cabecera de clave que no corresponde a la credencial")
        verify = lambda payload, signature: hmac.compare_digest(  # noqa: E731
            sign(stored.secret, payload), signature)
    validate_request(request.method, request.url, verify)
    http_request = urllib.request.Request(request.url, method=request.method,
                                          headers={**headers, "User-Agent": "bottrading-educativo"})
    # Todo error se lanza FUERA de los except: ni HTTPError (su .url lleva la
    # query firmada) ni otra excepción queda en __context__ (revisión de Codex).
    status, retry_after, body = None, None, None
    try:
        with build_opener().open(http_request, timeout=TIMEOUT_SECONDS) as response:
            status, body, final_url = response.status, response.read(), response.geturl()
    except urllib.error.HTTPError as exc:
        status, retry_after, final_url = exc.code, _retry_after(exc.headers), request.url
        body = _read_quietly(exc)
    except (OSError, http.client.HTTPException):  # sin respuesta, corte o lectura incompleta
        status, body = None, None
    if status is None or body is None:
        raise DemoApiError(request.method, request.path, status, retry_after=retry_after)
    return Response(status, body, final_url, retry_after)


def _read_quietly(error: urllib.error.HTTPError) -> bytes | None:
    """Cuerpo de un HTTPError, o None si no se puede leer (sin encadenar nada)."""
    try:
        return error.read() or b""
    except Exception:  # noqa: BLE001 - cualquier fallo se reduce a "sin cuerpo" para no
        return None    # propagar una excepción que arrastre el HTTPError con la query firmada


def _retry_after(headers) -> int | None:
    value = headers.get("Retry-After") if headers is not None else None
    return int(value) if value is not None and str(value).isdigit() else None


# --- cliente -------------------------------------------------------------------------


# --- consentimiento de órdenes (revisión de Codex de F4) ----------------------------


@dataclass(frozen=True, eq=False)
class OrderConsent:
    """Permiso para enviar órdenes a la cuenta DEMO en este proceso.

    Solo vale si lo emitió _grant_order_consent desde main(), con el flag
    --send-orders del comando Y la variable BOTTRADING_DEMO_ORDERS=1 del
    entorno REAL del proceso (os.environ; quien llama no puede elegir los
    valores; revisión de Codex). La variable se vuelve a leer en cada envío.
    Un objeto construido a mano se rechaza (registro de identidades). Límite:
    dentro de un proceso de Python nada es infalsificable; saltárselo exige
    usar a propósito funciones privadas o cambiar el entorno del proceso, y un
    test estático comprueba que solo main() emite permisos.
    """


_ISSUED_CONSENTS: "weakref.WeakSet[OrderConsent]" = weakref.WeakSet()


def _orders_enabled_in_environment() -> bool:
    return os.environ.get(ORDERS_ENV) == "1"


def _grant_order_consent(send_orders: bool) -> OrderConsent | None:
    """Doble consentimiento de D030; None si falta cualquiera de los dos."""
    if not (send_orders is True and _orders_enabled_in_environment()):
        return None
    consent = OrderConsent()
    _ISSUED_CONSENTS.add(consent)
    return consent


def _consent_is_valid(consent: object) -> bool:
    # Emitido por main() y con la variable todavía activa al enviar.
    return (isinstance(consent, OrderConsent) and consent in _ISSUED_CONSENTS
            and _orders_enabled_in_environment())


class DemoClient:
    """Lecturas de la cuenta demo. Sin métodos de órdenes (aprobación (b))."""

    def __init__(self, credentials: Callable[[], Credentials] | None = read_windows_credential,
                 transport: Transport = urllib_transport,
                 clock: Callable[[], float] = time.time, *,
                 consent: OrderConsent | None = None):
        self._credentials, self._transport, self._clock = credentials, transport, clock
        self._consent = consent  # solo grant_order_consent lo emite (D030)

    def new_market_order(self, symbol: str, side: str, client_order_id: str, *,
                         quantity: str | None = None, quote_order_qty: str | None = None) -> dict:
        params = {"symbol": symbol, "side": side, "type": "MARKET",
                  "newClientOrderId": client_order_id, "newOrderRespType": "RESULT"}
        if quantity is not None:
            params["quantity"] = quantity
        if quote_order_qty is not None:
            params["quoteOrderQty"] = quote_order_qty
        return self._send("POST", "/api/v3/order", params)

    def cancel_order(self, symbol: str, client_order_id: str) -> dict:
        return self._send("DELETE", "/api/v3/order",
                          {"symbol": symbol, "origClientOrderId": client_order_id})

    def server_time(self) -> int:
        return self._get("/api/v3/time", {})["serverTime"]

    def exchange_info(self, symbol: str) -> dict:
        return self._get("/api/v3/exchangeInfo", {"symbol": symbol})

    def book_ticker(self, symbol: str) -> dict:
        return self._get("/api/v3/ticker/bookTicker", {"symbol": symbol})

    def account(self) -> dict:
        return self._get("/api/v3/account", {"omitZeroBalances": "true"})

    def order(self, symbol: str, client_order_id: str) -> dict:
        return self._get("/api/v3/order", {"symbol": symbol, "origClientOrderId": client_order_id})

    def open_orders(self, symbol: str) -> list:
        return self._get("/api/v3/openOrders", {"symbol": symbol})

    def all_orders(self, symbol: str, order_id: int | None = None, limit: int = 1000) -> list:
        params = {"symbol": symbol, "limit": str(limit)}
        if order_id is not None:
            params["orderId"] = str(order_id)
        return self._get("/api/v3/allOrders", params)

    def my_trades(self, symbol: str, from_id: int | None = None, limit: int = 1000) -> list:
        params = {"symbol": symbol, "limit": str(limit)}
        if from_id is not None:
            params["fromId"] = str(from_id)
        return self._get("/api/v3/myTrades", params)

    def prepare(self, path: str, params: Mapping[str, str],
                method: str = "GET") -> tuple[PreparedRequest, dict]:
        """Construye, firma y valida la petición; devuelve también las cabeceras."""
        if method in WRITE_METHODS and not _consent_is_valid(self._consent):
            raise RequestRefused(f"cliente de solo lectura: {method} no permitido sin "
                                 f"--send-orders y {ORDERS_ENV}=1")
        endpoint = ENDPOINTS.get((method, path))
        if endpoint is None:
            raise RequestRefused(f"petición no permitida: {method} {path}")
        query, headers = urllib.parse.urlencode(list(params.items())), {}
        verify = None
        if endpoint.signed:
            credentials = self._read_credentials()
            stamp = {"recvWindow": str(RECV_WINDOW_MS), "timestamp": str(int(self._clock() * 1000))}
            query = urllib.parse.urlencode([*params.items(), *stamp.items()])
            query += "&signature=" + sign(credentials.secret, query)
            headers[API_KEY_HEADER] = credentials.api_key
            verify = lambda payload, signature: hmac.compare_digest(  # noqa: E731
                sign(credentials.secret, payload), signature)
        url = f"{BASE_URL}{path}?{query}" if query else f"{BASE_URL}{path}"
        validate_request(method, url, verify)
        return PreparedRequest(method, url, path, endpoint.signed), headers

    def _read_credentials(self) -> Credentials:
        if self._credentials is None:
            raise CredentialError("cliente sin lector de credenciales: solo peticiones públicas")
        return self._credentials()

    def _get(self, path: str, params: Mapping[str, str]):
        return self._send("GET", path, params)

    def _send(self, method: str, path: str, params: Mapping[str, str]):
        request, headers = self.prepare(path, params, method)
        response = self._transport(request, headers)
        if response.url != request.url:
            raise RequestRefused(f"{path}: la respuesta procede de otro URL")
        logger.info("%s %s -> HTTP %s", method, path, response.status)
        if response.status != 200:
            code = _error_code(response.body)
            raise DemoApiError(method, path, response.status, code, response.retry_after,
                               duplicate=code == -2010 and _is_duplicate(response.body))
        try:
            return json.loads(response.body)
        except ValueError:  # JSONDecodeError guarda el cuerpo en .doc: no se encadena
            pass
        raise DemoApiError(method, path, response.status)


def sign(secret: str, payload: str) -> str:
    """HMAC-SHA256 en hexadecimal (firma de Binance para claves HMAC)."""
    return hmac.new(secret.encode("ascii"), payload.encode("ascii"), hashlib.sha256).hexdigest()


def _is_duplicate(body: bytes) -> bool:
    """Solo distingue "Duplicate order sent."; el texto no se guarda."""
    try:
        return json.loads(body).get("msg") == "Duplicate order sent."
    except (ValueError, AttributeError):
        return False


def _error_code(body: bytes) -> int | None:
    """Solo el código numérico de Binance; el texto del cuerpo no se conserva."""
    try:
        code = json.loads(body).get("code")
    except (ValueError, AttributeError):
        return None
    return code if isinstance(code, int) else None


# --- adaptador del protocolo (F4, aprobación (b) de D030) ---------------------------

QUOTE_STEP = Decimal("0.01")  # USDT: la compra se redondea hacia abajo a céntimos


def order_amounts(intent: OrderIntent, step_size: Decimal) -> tuple[str | None, str | None]:
    """(quantity, quoteOrderQty) deterministas para una intención, redondeados
    hacia abajo: compra por USDT a céntimos, venta por cantidad a stepSize."""
    if intent.side is Signal.BUY:
        quote = Decimal(repr(intent.quote_amount)).quantize(QUOTE_STEP, rounding=ROUND_DOWN)
        return None, format(quote, "f")
    units = (Decimal(repr(intent.quantity)) / step_size).to_integral_value(rounding=ROUND_DOWN)
    return format((units * step_size).normalize(), "f"), None


def _positive(amounts: tuple[str | None, str | None]) -> bool:
    return any(value is not None and Decimal(value) > 0 for value in amounts)


class DemoGateway:
    """Gateway del protocolo de demo_ledger sobre DemoClient (solo cuenta demo).

    Contrato (D030): GatewayRejected solo para rechazos 4XX previos al motor;
    5XX, -1007, 429/418 y fallos de transporte son GatewayUnknown; "Duplicate
    order sent." es DuplicateOrder. Las excepciones se lanzan fuera del except.
    """

    def __init__(self, client: "DemoClient", step_sizes: Mapping[str, Decimal]):
        self._client, self._steps = client, dict(step_sizes)

    def query(self, intent: OrderIntent) -> OrderStatus | None:
        failure, answer = None, None
        try:
            answer = self._client.order(intent.symbol, intent.client_order_id)
        except DemoApiError as error:
            failure = "absent" if error.code == -2013 else "unknown"
        if failure == "absent":
            return None
        if failure == "unknown":
            raise GatewayUnknown()
        return _status(answer)

    def submit(self, intent: OrderIntent) -> OrderStatus:
        quantity, quote = order_amounts(intent, self._steps[intent.symbol])
        outcome, answer = None, None
        try:
            answer = self._client.new_market_order(
                intent.symbol, intent.side.value.upper(), intent.client_order_id,
                quantity=quantity, quote_order_qty=quote)
        except DemoApiError as error:
            outcome = ("duplicate" if error.duplicate else
                       "rejected" if error.kind == "rejected" else "unknown", error.code)
        if outcome is not None:
            kind, code = outcome
            if kind == "duplicate":
                raise DuplicateOrder()
            if kind == "rejected":
                raise GatewayRejected(code)
            raise GatewayUnknown()
        return _status(answer)


def _status(answer: Mapping) -> OrderStatus:
    status, executed = answer.get("status"), answer.get("executedQty")
    if not isinstance(status, str) or not isinstance(executed, str):
        raise GatewayUnknown()  # respuesta incompleta: se resolverá por consulta
    return OrderStatus(status, float(Decimal(executed)))


# --- línea de comandos (F3 solo lectura; F4 run) -------------------------------------

MAX_CLOCK_SKEW_MS = 1000  # Binance rechaza marcas >= 1 s por delante del servidor
CONFIRMATION_WORD = "INICIALIZAR"


@dataclass(frozen=True)
class DemoPaths:
    ledger: Path
    baseline: Path
    kill_switch: Path

    @classmethod
    def default(cls) -> "DemoPaths":
        ledger = default_ledger_path()
        return cls(ledger, ledger.with_name("baseline.json"), ledger.with_name("STOP"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bottrading.demo_client",
        description="Cuenta Binance Spot DEMO (D030). Solo envía órdenes con run, "
                    f"--send-orders y {ORDERS_ENV}=1.")
    parser.add_argument("command", choices=("check", "init", "reconcile", "run", "rekey"))
    parser.add_argument("--send-orders", action="store_true",
                        help="run: envía de verdad (exige también la variable de entorno)")
    return parser


def main(argv: Sequence[str] | None = None, *,
         credentials: Callable[[], Credentials] = read_windows_credential,
         transport: Transport = urllib_transport,
         clock: Callable[[], float] = time.time,
         paths: DemoPaths | None = None,
         ask: Callable[[str], str] = input,
         out: Callable[[str], None] = print,
         data_dir: Path | None = None,
         sleep: Callable[[float], None] = time.sleep,
         new_credentials: Callable[[], Credentials] | None = None) -> int:
    """0 si todo está bien; 1 si hay que detenerse. Nunca muestra claves.

    Todo comando comprueba primero el reloj (antes de cualquier petición
    firmada) y, salvo el diagnóstico de check, el kill switch.
    """
    args = build_parser().parse_args(argv)
    command = args.command
    # Doble consentimiento (D030): solo elige entre simulación y envío DENTRO de
    # demo; el host y la tabla de peticiones siguen fijos.
    consent = _grant_order_consent(args.send_orders) if command == "run" else None
    send = consent is not None
    failure = None
    try:
        paths = paths or DemoPaths.default()
        client = DemoClient(credentials, transport, clock, consent=consent)
        if command != "check":
            _assert_no_kill_switch(paths)
        _assert_clock(client, clock, out)
        if command == "run":
            return _run(client, credentials, clock, paths, out, send,
                        data_dir or REPO_ROOT / "data", sleep)
        if command == "rekey":
            reader = new_credentials or (lambda: read_windows_credential(NEW_CREDENTIAL_TARGET))
            return _rekey(credentials, reader, transport, clock, paths, ask, out)
        handler = {"check": _check, "init": _init, "reconcile": _reconcile}[command]
        return handler(client, credentials, clock, paths, ask, out)
    except (DemoClientError, StopTheDay, LedgerIntegrityError, LimitExceeded) as error:
        failure = str(error)  # mensajes saneados: sin claves, query ni cuerpo
    except (OSError, ValueError, KeyError) as error:  # E/S o archivos privados ilegibles
        failure = f"{type(error).__name__}: {error}"
    out(f"DETENIDO: {failure}")
    return 1


def _assert_clock(client, clock, out) -> None:
    server_ms = client.server_time()  # pública, sin firma
    skew = int(clock() * 1000) - server_ms
    out(f"Hora: desfase con el servidor {skew} ms")
    if abs(skew) >= MAX_CLOCK_SKEW_MS:
        raise StopTheDay(f"reloj desfasado {skew} ms: sincroniza la hora de Windows")


def _assert_no_kill_switch(paths: DemoPaths) -> None:
    if paths.kill_switch.exists():
        raise StopTheDay(f"kill switch activo ({paths.kill_switch}): bórralo para continuar")


def _check(client, credentials, clock, paths, ask, out) -> int:
    credentials()  # solo comprueba que existe y tiene formato; no se muestra
    out("Credencial demo: presente (valor oculto)")
    for symbol in DEMO_SYMBOLS:
        info = symbol_info(client.exchange_info(symbol), symbol)
        out(f"{symbol}: activo base {info.base_asset}, stepSize {info.step_size}")
    account = client.account()
    assets = sorted(b["asset"] for b in account.get("balances", []))
    out(f"Cuenta: {len(assets)} activos con saldo ({', '.join(assets)}); "
        f"canTrade de la CUENTA = {account.get('canTrade')} "
        "(los permisos de la CLAVE se gestionan en la web de Binance Demo)")
    active = paths.kill_switch.exists()
    out(f"Kill switch ({paths.kill_switch.name}): {'ACTIVO' if active else 'inactivo'}")
    _assert_no_kill_switch(paths)
    if not paths.baseline.exists():
        out("Línea base: sin fijar (siguiente paso: init)")
        return 0
    return _reconcile(client, credentials, clock, paths, ask, out)


def _init(client, credentials, clock, paths, ask, out) -> int:
    """Fija la línea base y prepara el registro: solo con confirmación explícita.

    Orden recuperable (revisión de Codex): primero el registro VACÍO, al final
    la línea base. Si falla entre ambos, el siguiente init reutiliza ese
    registro vacío; un registro con eventos nunca se reutiliza.
    """
    if paths.baseline.exists():
        raise StopTheDay("ya inicializado: una nueva línea base requiere --rebaseline aprobado")
    if paths.ledger.exists() or paths.ledger.with_name("orders.state").exists():
        with OrderLedger(paths.ledger) as existing:  # verifica ancla e integridad
            if existing.records():
                raise StopTheDay("hay un registro con órdenes sin línea base: investigar")
        out("Registro vacío de un init anterior incompleto: se reutiliza")
    today = datetime.fromtimestamp(clock(), timezone.utc).date()
    baseline = take_baseline(client, today)
    out(f"Línea base propuesta ({today}):")
    for asset, amount in sorted(baseline.balances.items()):
        out(f"  {asset}: {amount}")
    out(f"  Último orderId por símbolo: {baseline.last_order_id}")
    out("Esto fija el punto de partida de la cuenta demo DEDICADA (D030). A partir de")
    out("ahora no debe haber operaciones manuales ni otros bots en esa cuenta.")
    if ask(f"Escribe {CONFIRMATION_WORD} para confirmar: ").strip() != CONFIRMATION_WORD:
        out("Cancelado: no se ha guardado la línea base.")
        return 1
    secret = credentials().secret
    if not paths.ledger.exists():
        OrderLedger(paths.ledger, create=True).close()
    save_baseline(paths.baseline, baseline, secret)  # último paso: marca init completo
    out(f"Inicializado: línea base y registro en {paths.ledger.parent}")
    return 0


def _reconcile(client, credentials, clock, paths, ask, out) -> int:
    baseline = load_baseline(paths.baseline, credentials().secret)
    with OrderLedger(paths.ledger) as ledger:
        result = reconcile(client, ledger, baseline)
    out(f"Reconciliación: OK (cobertura desde {result.coverage.since})")
    for symbol, holding in sorted(result.holdings.items()):
        out(f"  {symbol}: efectivo {holding.cash:.2f} USDT, cantidad {holding.quantity}, "
            f"coste {holding.cost:.2f}")
    return 0


REKEY_WORD = "REFIRMAR"


def _rekey(credentials, new_credentials, transport, clock, paths, ask, out) -> int:
    """Rotación de clave: la línea base pasa a firmarse con la clave nueva.

    La clave nueva se guarda antes en el Administrador de credenciales como
    BotTrading-Demo-Nueva. Se comprueba que funciona (lectura firmada), se
    verifica la línea base con la clave actual y se vuelve a firmar.
    """
    old, new = credentials(), new_credentials()
    if hmac.compare_digest(old.secret, new.secret):
        raise StopTheDay("la clave nueva es igual a la actual: no hay nada que rotar")
    DemoClient(new_credentials, transport, clock).account()  # la clave nueva funciona
    out("Clave nueva: lectura firmada OK (valor oculto)")
    load_baseline(paths.baseline, old.secret)
    out("Línea base: verificada con la clave actual")
    if ask(f"Escribe {REKEY_WORD} para volver a firmarla con la clave nueva: ").strip() \
            != REKEY_WORD:
        out("Cancelado: no se ha cambiado nada.")
        return 1
    resign_baseline(paths.baseline, old.secret, new.secret)
    out("Línea base firmada con la clave nueva (copia anterior: baseline.json.anterior).")
    out(f"Ahora sustituye la credencial: cmdkey /delete:{CREDENTIAL_TARGET}, vuelve a")
    out(f"crearla con la clave nueva y borra {NEW_CREDENTIAL_TARGET}.")
    return 0


def _run(client, credentials, clock, paths, out, send, data_dir, sleep) -> int:
    """Alinea la cuenta demo con la posición objetivo de la estrategia (F4).

    Orden: resolver órdenes pendientes (solo consultas) -> reconciliar ->
    posición objetivo con velas cerradas hasta ayer -> límites -> enviar con
    el protocolo idempotente -> reconciliar otra vez. Sin envío confirmado,
    solo muestra lo que haría.
    """
    out("MODO: " + ("ENVÍO de órdenes a la cuenta DEMO" if send else
                    f"simulación (falta --send-orders y {ORDERS_ENV}=1); no se envía nada"))
    baseline = load_baseline(paths.baseline, credentials().secret)
    today = datetime.fromtimestamp(clock(), timezone.utc).date()
    with OrderLedger(paths.ledger) as ledger:
        steps = {s: symbol_info(client.exchange_info(s), s).step_size for s in DEMO_SYMBOLS}
        gateway = DemoGateway(client, steps)
        pending = ledger.unresolved()
        if pending and not send:
            raise StopTheDay(f"{len(pending)} órdenes sin resolver: ejecuta run con envío "
                             "confirmado para resolverlas por consulta")
        for record in pending:  # SENT/UNKNOWN: solo consultas; nunca se reenvían
            execute_intent(ledger, gateway, record.intent, sleep)
        before = reconcile(client, ledger, baseline)
        candles = {}
        for symbol in DEMO_SYMBOLS:
            series, _ = load_forward_candles(data_dir / f"{symbol}-1d",
                                             data_dir / f"{symbol}-1d-daily")
            if series[-1].timestamp.date() != today - timedelta(days=1):
                raise StopTheDay(f"{symbol}: los datos llegan a {series[-1].timestamp.date()}, "
                                 f"no a {today - timedelta(days=1)}; ejecuta antes la descarga")
            candles[symbol] = series
        intents = target_intents(candles, before.holdings)
        new = [i for i in intents if ledger.record(i.client_order_id) is None]
        check_limits(new, before.holdings, ledger.orders_recorded_on(today), execution_day=today)
        for intent in intents:
            quantity, quote = order_amounts(intent, steps[intent.symbol])
            if not _positive((quantity, quote)):
                raise StopTheDay(f"{intent.client_order_id}: importe nulo tras redondear")
            out(f"Orden: {intent.client_order_id} {intent.side.value.upper()} "
                + (f"por {quote} USDT" if quote else f"{quantity} {intent.symbol}"))
        if not intents:
            out("Sin órdenes: la cuenta ya coincide con la posición objetivo")
        if not send:
            return 0
        for intent in intents:
            record = execute_intent(ledger, gateway, intent, sleep)
            out(f"  {intent.client_order_id}: {record.state} {record.status} "
                f"ejecutado {record.executed_qty}")
        after = reconcile(client, ledger, baseline)
    out("Reconciliación posterior: OK")
    for symbol, holding in sorted(after.holdings.items()):
        out(f"  {symbol}: efectivo {holding.cash:.2f} USDT, cantidad {holding.quantity}, "
            f"coste {holding.cost:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
