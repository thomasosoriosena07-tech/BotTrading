"""Cliente demo de solo lectura (D030, F2a): sin red, con transporte falso."""

import http.client
import logging
import sys
import urllib.error
import urllib.parse
import urllib.request

import pytest

import bottrading.demo_client as demo
from bottrading.demo_client import (
    API_KEY_HEADER,
    ENDPOINTS,
    CredentialError,
    Credentials,
    DemoApiError,
    DemoClient,
    NoRedirectHandler,
    PreparedRequest,
    RequestRefused,
    Response,
    build_opener,
    decode_credential_blob,
    parse_credential,
    read_windows_credential,
    sign,
    urllib_transport,
    validate_request,
)

API_KEY = "FAKEapiKEY0123456789abcdefABCDEF"
SECRET = "FAKEsecret9876543210zyxwvuZYXWVU"
CLOCK = lambda: 1_760_000_000.123  # noqa: E731


class FakeTransport:
    def __init__(self, status=200, body=b"{}", retry_after=None, url=None):
        self.status, self.body, self.retry_after, self.url = status, body, retry_after, url
        self.calls = []

    def __call__(self, request, headers):
        self.calls.append((request, dict(headers)))
        return Response(self.status, self.body, self.url or request.url, self.retry_after)


def must_not_be_called(request, headers):
    raise AssertionError("el transporte no debía llamarse")


def client(transport=must_not_be_called, credentials=lambda: Credentials(API_KEY, SECRET)):
    return DemoClient(credentials, transport, CLOCK)


def signed_url(path="/api/v3/allOrders", **params):
    params = params or {"symbol": "BTCUSDT", "limit": "1000"}
    request, _ = client().prepare(path, params)
    return request.url


def verify(payload, signature):
    return sign(SECRET, payload) == signature


# --- firma ---------------------------------------------------------------------------


def test_signature_matches_official_binance_vector():
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    payload = ("symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1"
               "&recvWindow=5000&timestamp=1499827319559")
    assert sign(secret, payload) == \
        "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


def test_signed_request_has_timestamp_recvwindow_signature_last_and_key_header():
    transport = FakeTransport(body=b"[]")
    assert client(transport).all_orders("ETHUSDT", order_id=42) == []
    request, headers = transport.calls[0]
    query = urllib.parse.urlsplit(request.url).query
    keys = [k for k, _ in urllib.parse.parse_qsl(query)]
    assert keys == ["symbol", "limit", "orderId", "recvWindow", "timestamp", "signature"]
    assert "timestamp=1760000000123" in query and "recvWindow=5000" in query
    assert headers == {API_KEY_HEADER: API_KEY}
    assert request.url.startswith("https://demo-api.binance.com/api/v3/allOrders?")


def test_public_requests_need_no_credentials():
    transport = FakeTransport(body=b'{"serverTime": 1760000000000}')
    assert DemoClient(None, transport, CLOCK).server_time() == 1760000000000
    assert transport.calls[0][1] == {}
    with pytest.raises(CredentialError):
        DemoClient(None, must_not_be_called, CLOCK).account()


# --- barrera: validación antes del transporte ----------------------------------------


GOOD = "https://demo-api.binance.com/api/v3/allOrders"


@pytest.mark.parametrize("prefix", [
    "https://api.binance.com", "https://api1.binance.com", "https://api2.binance.com",
    "https://api3.binance.com", "https://api4.binance.com", "https://api-gcp.binance.com",
    "https://testnet.binance.vision", "https://DEMO-API.binance.com",
    "https://demo-api.binance.com.", "https://demo-api.binance.com.evil.example",
    "https://127.0.0.1", "https://demo-api.binance.com:8443",
    "https://user@demo-api.binance.com", "https://user:pw@demo-api.binance.com",
    "http://demo-api.binance.com", "ftp://demo-api.binance.com",
])
def test_production_and_other_hosts_are_refused(prefix):
    url = signed_url().replace("https://demo-api.binance.com", prefix, 1)
    with pytest.raises(RequestRefused):
        validate_request("GET", url, verify)


def test_explicit_port_443_is_the_same_host():
    url = signed_url().replace("demo-api.binance.com", "demo-api.binance.com:443", 1)
    assert validate_request("GET", url, verify) == "/api/v3/allOrders"


def tamper(url, old, new):
    assert old in url
    return url.replace(old, new, 1)


@pytest.mark.parametrize(("method", "mutate"), [
    ("POST", lambda u: u),
    ("DELETE", lambda u: u),
    ("GET", lambda u: tamper(u, "/api/v3/allOrders", "/api/v3/%61llOrders")),
    ("GET", lambda u: tamper(u, "/api/v3/allOrders", "/sapi/v1/allOrders")),
    ("GET", lambda u: tamper(u, "/api/v3/allOrders", "/api/v3/order")),  # otros parámetros
    ("GET", lambda u: tamper(u, "/api/v3/allOrders", "/api/v3/allOrders;x")),
    ("GET", lambda u: u + "#frag"),
    ("GET", lambda u: u + "&extra=1"),
    ("GET", lambda u: tamper(u, "limit=1000", "limit=1000&limit=1000")),
    ("GET", lambda u: tamper(u, "symbol=BTCUSDT", "symbol=ETHUSDT")),  # alterada tras firmar
    ("GET", lambda u: tamper(u, "symbol=BTCUSDT", "symbol=%42TCUSDT")),
    ("GET", lambda u: u[:-64] + "0" * 64),
    ("GET", lambda u: u[:-64] + "XYZ"),
    ("GET", lambda u: tamper(u, "&signature=", "&s=1&signature=")),
    ("GET", lambda u: u.split("&signature=")[0]),
    ("GET", lambda u: u.split("?")[0]),
    ("GET", lambda u: u + "&"),
])
def test_altered_requests_are_refused(method, mutate):
    with pytest.raises(RequestRefused):
        validate_request(method, mutate(signed_url()), verify)


@pytest.mark.parametrize("mutate", [
    lambda u: tamper(u, "/api/v3/allOrders", "/api/v3/all\nOrders"),
    lambda u: tamper(u, "/api/v3/allOrders", "/api/v3/all\tOrders"),
    lambda u: " " + u,
    lambda u: u + " ",
    lambda u: u + "\r\n",
    lambda u: tamper(u, "demo-api", "demo-аpi"),  # 'a' cirílica
])
def test_whitespace_control_and_non_ascii_characters_are_refused(mutate):
    # urlsplit los eliminaría y validaría un texto distinto del enviado.
    with pytest.raises(RequestRefused, match="caracteres"):
        validate_request("GET", mutate(signed_url()), verify)


def no_opener():
    raise AssertionError("no debía construirse el opener")


def test_transport_revalidates_requests_not_built_by_prepare(monkeypatch):
    monkeypatch.setattr(demo, "build_opener", no_opener)
    good, headers = prepared_with_headers()
    for url in (good.url.replace("demo-api.binance.com", "api.binance.com"),
                good.url + "&extra=1", "https://demo-api.binance.com/sapi/v1/account"):
        with pytest.raises(RequestRefused):
            urllib_transport(PreparedRequest("GET", url, "/x", True), headers, FAKE_STORED)
    with pytest.raises(RequestRefused):
        urllib_transport(PreparedRequest("POST", good.url, good.path, True), headers, FAKE_STORED)


def test_transport_verifies_signature_with_the_stored_credential(monkeypatch):
    # Revisión de Codex: una firma inventada (64 ceros) llegaba al transporte.
    monkeypatch.setattr(demo, "build_opener", no_opener)
    good, headers = prepared_with_headers()
    forged = PreparedRequest("GET", good.url[:-64] + "0" * 64, good.path, True)
    with pytest.raises(RequestRefused, match="firma"):
        urllib_transport(forged, headers, FAKE_STORED)
    other_secret = lambda: Credentials(API_KEY, "OTROsecret0123456789abcdefABCDEF")  # noqa: E731
    with pytest.raises(RequestRefused, match="firma"):
        urllib_transport(good, headers, other_secret)  # firmada con otro secreto
    with pytest.raises(RequestRefused, match="cabecera"):
        urllib_transport(good, {API_KEY_HEADER: "OTRAclave0123456789abcdef"}, FAKE_STORED)
    with pytest.raises(RequestRefused, match="cabecera"):
        urllib_transport(good, {}, FAKE_STORED)


def test_transport_default_reads_the_windows_credential(monkeypatch):
    monkeypatch.setattr(demo, "build_opener", no_opener)
    calls = []
    monkeypatch.setattr(demo, "read_windows_credential",
                        lambda: calls.append(1) or Credentials(API_KEY, SECRET))
    forged, headers = prepared_with_headers()
    with pytest.raises(RequestRefused):
        urllib_transport(PreparedRequest("GET", forged.url[:-64] + "0" * 64, forged.path, True),
                         headers)
    assert calls == [1]


def test_signature_must_be_last_and_verified():
    url = signed_url()
    base, signature = url.split("&signature=")
    path, query = base.split("?")
    moved = f"{path}?signature={signature}&{query}"
    with pytest.raises(RequestRefused):
        validate_request("GET", moved, verify)
    with pytest.raises(RequestRefused, match="firma"):
        validate_request("GET", url, None)  # sin verificador no se acepta una firmada


@pytest.mark.parametrize(("call", "args"), [
    ("order", ("BNBUSDT", "bt-BNBUSDT-20261012-B")),
    ("order", ("BTCUSDT", "manual-123")),
    ("all_orders", ("BTCUSDT", None, 5000)),
    ("all_orders", ("BTCUSDT", -1)),
    ("my_trades", ("btcusdt",)),
])
def test_invalid_parameters_never_reach_the_transport(call, args):
    with pytest.raises(RequestRefused):
        getattr(client(), call)(*args)


def test_unknown_or_write_endpoints_are_refused_before_signing():
    def no_credentials():
        raise AssertionError("no debía leerse la credencial")
    reader = DemoClient(no_credentials, must_not_be_called, CLOCK)
    for path in ("/sapi/v1/account", "/api/v3/order/test", "/fapi/v1/order"):
        with pytest.raises(RequestRefused):
            reader.prepare(path, {})


def test_client_is_read_only_by_default():
    # F4 (aprobación (b) de D030): las únicas escrituras son POST y DELETE de
    # /api/v3/order, y solo un cliente con un OrderConsent emitido puede prepararlas.
    writes = {key for key in ENDPOINTS if key[0] != "GET"}
    assert writes == {("POST", "/api/v3/order"), ("DELETE", "/api/v3/order")}
    reader = DemoClient(lambda: Credentials(API_KEY, SECRET), must_not_be_called, CLOCK)
    with pytest.raises(RequestRefused, match="solo lectura"):
        reader.new_market_order("BTCUSDT", "BUY", "bt-BTCUSDT-20261012-B", quote_order_qty="10")
    with pytest.raises(RequestRefused, match="solo lectura"):
        reader.cancel_order("BTCUSDT", "bt-BTCUSDT-20261012-B")
    order_url = signed_url("/api/v3/order", symbol="BTCUSDT",
                           origClientOrderId="bt-BTCUSDT-20261012-B")
    for method in ("POST", "PUT", "PATCH"):  # GET de consulta no vale como escritura
        with pytest.raises(RequestRefused):
            validate_request(method, order_url, verify)


def test_recv_window_and_limit_bounds():
    assert demo.RECV_WINDOW_MS == 5000
    url = signed_url()
    for bad in ("recvWindow=5001", "recvWindow=60000", "recvWindow=0"):
        with pytest.raises(RequestRefused):
            validate_request("GET", tamper(url, "recvWindow=5000", bad), lambda p, s: True)


def test_response_from_another_url_is_refused():
    transport = FakeTransport(url="https://api.binance.com/api/v3/time")
    with pytest.raises(RequestRefused, match="otro URL"):
        client(transport).server_time()


# --- transporte real (sin red): proxies y redirecciones ------------------------------


def test_opener_ignores_environment_proxies(monkeypatch):
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy"):
        monkeypatch.setenv(name, "http://proxy.evil.example:3128")
    # El opener por defecto SÍ tomaría el proxy del entorno...
    default = urllib.request.build_opener()
    assert any(isinstance(h, urllib.request.ProxyHandler) and h.proxies
               for h in default.handlers)
    # ...el del cliente no: ProxyHandler({}) sustituye al de entorno y, al no
    # manejar ningún protocolo, ni siquiera queda registrado.
    opener = build_opener()
    assert not any(isinstance(h, urllib.request.ProxyHandler) for h in opener.handlers)
    assert not any(hasattr(h, "proxy_open") for h in opener.handlers)


def test_opener_refuses_every_redirect():
    handlers = [type(h) for h in build_opener().handlers]
    assert NoRedirectHandler in handlers
    assert urllib.request.HTTPRedirectHandler not in handlers
    handler = NoRedirectHandler()
    request = urllib.request.Request(GOOD)
    for code in (301, 302, 303, 307, 308):
        with pytest.raises(RequestRefused, match="redirección"):
            handler.redirect_request(request, None, code, "x", {}, "https://api.binance.com/x")


class FakeOpener:
    def __init__(self, error):
        self.error = error

    def open(self, request, timeout):
        raise self.error


FAKE_STORED = lambda: Credentials(API_KEY, SECRET)  # noqa: E731


def prepared_with_headers():
    return client().prepare("/api/v3/account", {"omitZeroBalances": "true"})


def prepared():
    return prepared_with_headers()[0]


def test_transport_http_error_keeps_status_code_and_retry_after(monkeypatch):
    request, headers = prepared_with_headers()
    error = urllib.error.HTTPError(request.url, 429, "x", {"Retry-After": "7"}, None)
    monkeypatch.setattr(demo, "build_opener", lambda: FakeOpener(error))
    response = urllib_transport(request, headers, FAKE_STORED)
    assert (response.status, response.retry_after, response.url) == (429, 7, request.url)


def test_transport_failure_keeps_no_exception_with_the_signed_url(monkeypatch):
    # Revisión de Codex: `from None` ocultaba el contexto pero lo conservaba.
    request, headers = prepared_with_headers()
    monkeypatch.setattr(demo, "build_opener",
                        lambda: FakeOpener(urllib.error.URLError(f"fallo en {request.url}")))
    with pytest.raises(DemoApiError) as info:
        urllib_transport(request, headers, FAKE_STORED)
    assert info.value.kind == "transport"
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert not any("signature" in text for text in exception_texts(info.value))


class FailingBody:
    def read(self, *args):
        raise ConnectionResetError("corte al leer el cuerpo")

    def close(self):
        pass


def test_unreadable_http_error_body_keeps_no_signed_url(monkeypatch):
    # Revisión de Codex: si exc.read() fallaba, el HTTPError quedaba en __context__.
    request, headers = prepared_with_headers()
    error = urllib.error.HTTPError(request.url, 503, "x", {"Retry-After": "3"}, FailingBody())
    monkeypatch.setattr(demo, "build_opener", lambda: FakeOpener(error))
    with pytest.raises(DemoApiError) as info:
        urllib_transport(request, headers, FAKE_STORED)
    assert (info.value.kind, info.value.status, info.value.retry_after) == ("unknown", 503, 3)
    assert info.value.__context__ is None and info.value.__cause__ is None
    assert not any("signature" in text for text in exception_texts(info.value))


class IncompleteResponse:
    status = 200

    def read(self):
        raise http.client.IncompleteRead(b"parcial", 100)

    def geturl(self):
        return "irrelevante"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class OpenerReturning:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


def test_incomplete_read_is_sanitized(monkeypatch):
    request, headers = prepared_with_headers()
    monkeypatch.setattr(demo, "build_opener", lambda: OpenerReturning(IncompleteResponse()))
    with pytest.raises(DemoApiError) as info:
        urllib_transport(request, headers, FAKE_STORED)
    assert info.value.kind == "transport"
    assert info.value.__context__ is None and "parcial" not in str(info.value)


def test_invalid_json_and_bad_query_keep_no_context():
    with pytest.raises(DemoApiError) as info:
        client(FakeTransport(body=b'{"saldo": no-json')).account()
    assert info.value.__context__ is None
    with pytest.raises(RequestRefused) as info:
        validate_request("GET", GOOD + "?symbol", verify)
    assert info.value.__context__ is None


def test_undecodable_credential_blob_keeps_no_bytes():
    blob = "SECRETO-NO-VISIBLE".encode("utf-16-le") + bytes([0])  # longitud impar
    with pytest.raises(CredentialError) as info:
        decode_credential_blob(blob)
    assert info.value.__context__ is None and info.value.__cause__ is None
    assert not any("SECRETO" in text or "S\x00E" in text for text in exception_texts(info.value))
    assert decode_credential_blob(f"{API_KEY}:{SECRET}".encode("utf-16-le")) == f"{API_KEY}:{SECRET}"


# --- clasificación de errores --------------------------------------------------------


@pytest.mark.parametrize(("status", "body", "retry", "kind", "code"), [
    (429, b'{"code":-1003,"msg":"x"}', 7, "rate_limited", -1003),
    (418, b"", 120, "rate_limited", None),
    (500, b"<html>", None, "unknown", None),
    (503, b'{"code":-1007,"msg":"x"}', None, "unknown", -1007),
    (408, b'{"code":-1007,"msg":"x"}', None, "unknown", -1007),
    (400, b'{"code":-2013,"msg":"Order does not exist."}', None, "rejected", -2013),
    (401, b'{"code":-2015,"msg":"x"}', None, "rejected", -2015),
    (400, b'{"code":"texto"}', None, "rejected", None),
])
def test_errors_are_classified_without_copying_the_body(status, body, retry, kind, code):
    with pytest.raises(DemoApiError) as info:
        client(FakeTransport(status, body, retry)).account()
    error = info.value
    assert (error.kind, error.code, error.retry_after, error.status) == (kind, code, retry, status)
    assert "msg" not in str(error) and "does not exist" not in str(error)


def test_invalid_json_on_success_is_an_error():
    with pytest.raises(DemoApiError):
        client(FakeTransport(body=b"no-json")).account()


# --- secretos ------------------------------------------------------------------------


def exception_texts(error):
    texts = []
    while error is not None:
        texts += [str(error), repr(error)]
        error = error.__cause__ or error.__context__
    return texts


def test_keys_never_appear_in_logs_reprs_or_errors(caplog):
    caplog.set_level(logging.DEBUG)
    texts = [repr(Credentials(API_KEY, SECRET)), repr(prepared())]
    client(FakeTransport(body=b"{}")).account()
    for status in (400, 429, 500):
        with pytest.raises(DemoApiError) as info:
            client(FakeTransport(status, b'{"code":-1}')).my_trades("BTCUSDT")
        texts += exception_texts(info.value)
    with pytest.raises(RequestRefused) as info:
        validate_request("GET", signed_url() + "&extra=1", verify)
    texts += exception_texts(info.value)
    texts.append(caplog.text)
    joined = "\n".join(texts)
    assert API_KEY not in joined and SECRET not in joined
    assert "signature=" not in joined and "timestamp=" not in joined


def test_parse_credential_accepts_key_colon_secret_only():
    credentials = parse_credential(f"{API_KEY}:{SECRET}\n")
    assert (credentials.api_key, credentials.secret) == (API_KEY, SECRET)
    for bad in ("", API_KEY, f"{API_KEY}:", f":{SECRET}", f"{API_KEY}:{SECRET}:x",
                f"{API_KEY} {SECRET}", "corta:corta"):
        with pytest.raises(CredentialError) as info:
            parse_credential(bad)
        assert API_KEY not in str(info.value) and SECRET not in str(info.value)


@pytest.mark.skipif(sys.platform != "win32", reason="Administrador de credenciales de Windows")
def test_missing_windows_credential_is_a_clear_error():
    # Llamada local al sistema operativo (sin red) con un destino inexistente.
    with pytest.raises(CredentialError, match="no se pudo leer"):
        read_windows_credential("BotTrading-Demo-prueba-inexistente-7f3a")


def test_prepared_request_repr_hides_query():
    request = PreparedRequest("GET", signed_url(), "/api/v3/allOrders", True)
    assert repr(request) == "PreparedRequest(GET /api/v3/allOrders)"
