"""Comandos de F3 (check, init, reconcile) con transporte falso: sin red ni claves reales."""

import json
import urllib.parse

import pytest

from bottrading.demo_client import (
    CONFIRMATION_WORD,
    CredentialError,
    Credentials,
    DemoPaths,
    Response,
    main,
)

API_KEY = "FAKEapiKEY0123456789abcdefABCDEF"
SECRET = "FAKEsecret9876543210zyxwvuZYXWVU"
NOW = 1_760_400_000.0  # segundos
BASES = {"BTCUSDT": ("BTC", "0.00001000"), "ETHUSDT": ("ETH", "0.00010000"),
         "SOLUSDT": ("SOL", "0.00100000")}


class FakeDemo:
    """Responde por ruta como la API demo; registra que todo sea GET."""

    def __init__(self, server_ms=None, balances=None):
        self.server_ms = server_ms if server_ms is not None else int(NOW * 1000) - 120
        self.balances = balances or {"USDT": "5000.00000000", "BNB": "1.00000000"}
        self.methods = []

    def __call__(self, request, headers):
        self.methods.append(request.method)
        parts = urllib.parse.urlsplit(request.url)
        params = dict(urllib.parse.parse_qsl(parts.query))
        body = self.answer(parts.path, params)
        return Response(200, json.dumps(body).encode("utf-8"), request.url)

    def answer(self, path, params):
        if path == "/api/v3/time":
            return {"serverTime": self.server_ms}
        if path == "/api/v3/exchangeInfo":
            base, step = BASES[params["symbol"]]
            return {"symbols": [{"symbol": params["symbol"], "baseAsset": base,
                                 "quoteAsset": "USDT",
                                 "filters": [{"filterType": "LOT_SIZE", "stepSize": step}]}]}
        if path == "/api/v3/account":
            return {"canTrade": True, "balances": [
                {"asset": a, "free": v, "locked": "0.00000000"} for a, v in self.balances.items()]}
        if path in ("/api/v3/openOrders", "/api/v3/allOrders", "/api/v3/myTrades"):
            return []
        raise AssertionError(f"ruta inesperada {path}")


def fake_credentials():
    return Credentials(API_KEY, SECRET)


def run(tmp_path, command, demo=None, answer=CONFIRMATION_WORD, credentials=fake_credentials):
    lines = []
    paths = DemoPaths(tmp_path / "orders.csv", tmp_path / "baseline.json", tmp_path / "STOP")
    code = main([command], credentials=credentials, transport=demo or FakeDemo(),
                clock=lambda: NOW, paths=paths, ask=lambda prompt: answer, out=lines.append)
    text = "\n".join(lines)
    assert API_KEY not in text and SECRET not in text and "signature" not in text
    return code, text


def test_check_before_init_reports_without_secrets(tmp_path):
    demo = FakeDemo()
    code, text = run(tmp_path, "check", demo)
    assert code == 0
    assert "Credencial demo: presente (valor oculto)" in text
    assert "desfase con el servidor 120 ms" in text
    assert "BTCUSDT: activo base BTC, stepSize 0.00001000" in text
    assert "Kill switch (STOP): inactivo" in text
    assert "Línea base: sin fijar" in text
    assert set(demo.methods) == {"GET"}


def test_missing_credential_stops_clearly(tmp_path):
    def missing():
        raise CredentialError("no se pudo leer la credencial 'BotTrading-Demo'")
    code, text = run(tmp_path, "check", credentials=missing)
    assert code == 1 and "DETENIDO: no se pudo leer la credencial" in text


def test_clock_skew_stops(tmp_path):
    code, text = run(tmp_path, "check", FakeDemo(server_ms=int(NOW * 1000) - 1500))
    assert code == 1 and "reloj desfasado" in text


def test_kill_switch_is_shown_by_check_and_blocks_every_command(tmp_path):
    # Revisión de Codex: el STOP debe detener, no solo informarse.
    (tmp_path / "STOP").write_text("", encoding="utf-8")
    code, text = run(tmp_path, "check")
    assert code == 1 and "Kill switch (STOP): ACTIVO" in text and "DETENIDO: kill switch" in text
    for command in ("init", "reconcile"):
        demo = FakeDemo()
        code, text = run(tmp_path, command, demo)
        assert code == 1 and "DETENIDO: kill switch" in text
        assert demo.methods == []  # ni siquiera consulta el exchange
    assert not (tmp_path / "baseline.json").exists()


def test_init_requires_the_exact_confirmation_word(tmp_path):
    for answer in ("", "inicializar", "si", "INICIALIZAR AHORA"):
        code, text = run(tmp_path, "init", answer=answer)
        assert code == 1 and "no se ha guardado la línea base" in text
        assert not (tmp_path / "baseline.json").exists() and not (tmp_path / "orders.csv").exists()


def test_init_then_check_reconciles_and_init_is_not_repeatable(tmp_path):
    code, text = run(tmp_path, "init")
    assert code == 0 and "USDT: 5000" in text and "Inicializado" in text
    assert (tmp_path / "baseline.json").exists() and (tmp_path / "orders.state").exists()
    code, text = run(tmp_path, "check")
    assert code == 0 and "Reconciliación: OK" in text
    assert "BTCUSDT: efectivo 1000.00 USDT" in text
    code, text = run(tmp_path, "init")
    assert code == 1 and "ya inicializado" in text


def test_reconcile_stops_on_balance_change_or_tampered_baseline(tmp_path):
    run(tmp_path, "init")
    code, text = run(tmp_path, "reconcile", FakeDemo(balances={"USDT": "4000", "BNB": "1"}))
    assert code == 1 and "USDT: saldo distinto" in text
    document = json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))
    document["balances"]["USDT"] = "4000"
    (tmp_path / "baseline.json").write_text(json.dumps(document), encoding="utf-8")
    code, text = run(tmp_path, "reconcile", FakeDemo(balances={"USDT": "4000", "BNB": "1"}))
    assert code == 1 and "HMAC" in text


def test_reconcile_without_init_stops(tmp_path):
    code, text = run(tmp_path, "reconcile")
    assert code == 1 and "no hay línea base" in text


def test_unknown_command_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit):
        run(tmp_path, "buy")


class Recorder(FakeDemo):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.paths = []

    def __call__(self, request, headers):
        self.paths.append(urllib.parse.urlsplit(request.url).path)
        return super().__call__(request, headers)


@pytest.mark.parametrize("command", ["check", "init", "reconcile"])
def test_clock_is_checked_first_by_every_command(tmp_path, command):
    # Revisión de Codex: ninguna petición firmada antes de comprobar el reloj.
    demo = Recorder(server_ms=int(NOW * 1000) + 1500)
    code, text = run(tmp_path, command, demo)
    assert code == 1 and "reloj desfasado" in text
    assert demo.paths == ["/api/v3/time"]


def test_interrupted_init_is_recoverable(tmp_path):
    # Revisión de Codex: el registro vacío de un init interrumpido se reutiliza.
    from bottrading.demo_ledger import OrderLedger
    OrderLedger(tmp_path / "orders.csv", create=True).close()  # init cortado antes de la línea base
    code, text = run(tmp_path, "reconcile")
    assert code == 1 and "no hay línea base" in text
    code, text = run(tmp_path, "init")
    assert code == 0 and "se reutiliza" in text and "Inicializado" in text
    code, text = run(tmp_path, "reconcile")
    assert code == 0 and "Reconciliación: OK" in text


def test_init_never_reuses_a_ledger_with_orders(tmp_path):
    from datetime import datetime, timezone
    from bottrading.demo_ledger import OrderLedger
    from bottrading.execution import OrderIntent
    from bottrading.strategy import Signal
    with OrderLedger(tmp_path / "orders.csv", create=True) as ledger:
        ledger.append(OrderIntent("BTCUSDT", Signal.BUY, datetime(2026, 10, 12, tzinfo=timezone.utc),
                                  quote_amount=10.0), "INTENT")
    code, text = run(tmp_path, "init")
    assert code == 1 and "registro con órdenes sin línea base" in text
    assert not (tmp_path / "baseline.json").exists()


def test_io_and_corrupt_file_errors_become_detenido(tmp_path):
    # Revisión de Codex: errores de E/S sin traceback.
    run(tmp_path, "init")
    (tmp_path / "baseline.json").write_text("{no es json", encoding="utf-8")
    code, text = run(tmp_path, "reconcile")
    assert code == 1 and text.splitlines()[-1].startswith("DETENIDO: JSONDecodeError")
    blocker = tmp_path / "bloqueo"
    blocker.write_text("soy un archivo", encoding="utf-8")
    lines = []
    paths = DemoPaths(blocker / "orders.csv", blocker / "baseline.json", blocker / "STOP")
    code = main(["init"], credentials=fake_credentials, transport=FakeDemo(), clock=lambda: NOW,
                paths=paths, ask=lambda prompt: CONFIRMATION_WORD, out=lines.append)
    assert code == 1 and lines[-1].startswith("DETENIDO: ")


# --- rotación de clave (rekey) ---------------------------------------------------------

NEW_KEY = "NUEVAapiKEY0123456789abcdefABCDE"
NEW_SECRET = "NUEVOsecret9876543210zyxwvuZYXWV"


def new_credentials():
    return Credentials(NEW_KEY, NEW_SECRET)


def rekey(tmp_path, answer="REFIRMAR", new=new_credentials, demo=None):
    lines = []
    paths = DemoPaths(tmp_path / "orders.csv", tmp_path / "baseline.json", tmp_path / "STOP")
    code = main(["rekey"], credentials=fake_credentials, new_credentials=new,
                transport=demo or FakeDemo(), clock=lambda: NOW, paths=paths,
                ask=lambda prompt: answer, out=lines.append)
    text = "\n".join(lines)
    for secret in (API_KEY, SECRET, NEW_KEY, NEW_SECRET):
        assert secret not in text
    return code, text


def test_rekey_resigns_the_baseline_with_the_new_secret(tmp_path):
    from bottrading.demo_reconcile import load_baseline
    run(tmp_path, "init")
    before = load_baseline(tmp_path / "baseline.json", SECRET)
    code, text = rekey(tmp_path)
    assert code == 0 and "firmada con la clave nueva" in text
    assert load_baseline(tmp_path / "baseline.json", NEW_SECRET) == before  # mismo contenido
    with pytest.raises(Exception, match="HMAC"):
        load_baseline(tmp_path / "baseline.json", SECRET)
    assert load_baseline(tmp_path / "baseline.json.anterior", SECRET) == before


def test_rekey_needs_confirmation_a_different_working_key_and_a_valid_baseline(tmp_path):
    from bottrading.demo_reconcile import load_baseline
    run(tmp_path, "init")
    original = (tmp_path / "baseline.json").read_bytes()
    code, text = rekey(tmp_path, answer="si")
    assert code == 1 and "no se ha cambiado nada" in text
    code, text = rekey(tmp_path, new=fake_credentials)
    assert code == 1 and "igual a la actual" in text

    class Refuses(FakeDemo):
        def __call__(self, request, headers):
            if request.path == "/api/v3/account":
                return Response(401, b'{"code":-2015,"msg":"x"}', request.url)
            return super().__call__(request, headers)
    code, text = rekey(tmp_path, demo=Refuses())
    assert code == 1 and "DETENIDO" in text
    assert (tmp_path / "baseline.json").read_bytes() == original
    assert not (tmp_path / "baseline.json.anterior").exists()
    assert load_baseline(tmp_path / "baseline.json", SECRET)


def test_rekey_stops_if_the_baseline_does_not_verify_with_the_current_key(tmp_path):
    run(tmp_path, "init")
    lines = []
    paths = DemoPaths(tmp_path / "orders.csv", tmp_path / "baseline.json", tmp_path / "STOP")
    code = main(["rekey"], credentials=new_credentials,
                new_credentials=lambda: Credentials(API_KEY + "X", SECRET + "X"),
                transport=FakeDemo(), clock=lambda: NOW, paths=paths,
                ask=lambda prompt: "REFIRMAR", out=lines.append)
    assert code == 1 and "HMAC" in "\n".join(lines)
