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
"""

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
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from bottrading.execution import DEMO_SYMBOLS

logger = logging.getLogger(__name__)

DEMO_HOST = "demo-api.binance.com"
BASE_URL = f"https://{DEMO_HOST}"
API_KEY_HEADER = "X-MBX-APIKEY"
CREDENTIAL_TARGET = "BotTrading-Demo"
RECV_WINDOW_MS = 5000  # D030: <= 5000
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
                 code: int | None = None, retry_after: int | None = None):
        self.method, self.path, self.status = method, path, status
        self.code, self.retry_after = code, retry_after
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


# Solo lectura. POST/DELETE /api/v3/order se añadirán únicamente tras la
# aprobación (b) de D030.
ENDPOINTS: Mapping[tuple[str, str], Endpoint] = {
    ("GET", "/api/v3/time"): Endpoint(False),
    ("GET", "/api/v3/exchangeInfo"): Endpoint(False, frozenset({"symbol"})),
    ("GET", "/api/v3/ticker/bookTicker"): Endpoint(False, frozenset({"symbol"})),
    ("GET", "/api/v3/account"): _signed(optional="omitZeroBalances"),
    ("GET", "/api/v3/order"): _signed("symbol origClientOrderId"),
    ("GET", "/api/v3/openOrders"): _signed("symbol"),
    ("GET", "/api/v3/allOrders"): _signed("symbol", "orderId startTime endTime limit"),
    ("GET", "/api/v3/myTrades"): _signed("symbol", "orderId startTime endTime fromId limit"),
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


class DemoClient:
    """Lecturas de la cuenta demo. Sin métodos de órdenes (aprobación (b))."""

    def __init__(self, credentials: Callable[[], Credentials] | None = read_windows_credential,
                 transport: Transport = urllib_transport,
                 clock: Callable[[], float] = time.time):
        self._credentials, self._transport, self._clock = credentials, transport, clock

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

    def prepare(self, path: str, params: Mapping[str, str]) -> tuple[PreparedRequest, dict]:
        """Construye, firma y valida la petición GET; devuelve también las cabeceras."""
        endpoint = ENDPOINTS.get(("GET", path))
        if endpoint is None:
            raise RequestRefused(f"petición no permitida: GET {path}")
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
        validate_request("GET", url, verify)
        return PreparedRequest("GET", url, path, endpoint.signed), headers

    def _read_credentials(self) -> Credentials:
        if self._credentials is None:
            raise CredentialError("cliente sin lector de credenciales: solo peticiones públicas")
        return self._credentials()

    def _get(self, path: str, params: Mapping[str, str]):
        request, headers = self.prepare(path, params)
        response = self._transport(request, headers)
        if response.url != request.url:
            raise RequestRefused(f"{path}: la respuesta procede de otro URL")
        logger.info("GET %s -> HTTP %s", path, response.status)
        if response.status != 200:
            raise DemoApiError("GET", path, response.status, _error_code(response.body),
                               response.retry_after)
        try:
            return json.loads(response.body)
        except ValueError:  # JSONDecodeError guarda el cuerpo en .doc: no se encadena
            pass
        raise DemoApiError("GET", path, response.status)


def sign(secret: str, payload: str) -> str:
    """HMAC-SHA256 en hexadecimal (firma de Binance para claves HMAC)."""
    return hmac.new(secret.encode("ascii"), payload.encode("ascii"), hashlib.sha256).hexdigest()


def _error_code(body: bytes) -> int | None:
    """Solo el código numérico de Binance; el texto del cuerpo no se conserva."""
    try:
        code = json.loads(body).get("code")
    except (ValueError, AttributeError):
        return None
    return code if isinstance(code, int) else None
