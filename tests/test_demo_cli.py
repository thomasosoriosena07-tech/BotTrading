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
    assert "sin inicializar" in text
    assert set(demo.methods) == {"GET"}


def test_missing_credential_stops_clearly(tmp_path):
    def missing():
        raise CredentialError("no se pudo leer la credencial 'BotTrading-Demo'")
    code, text = run(tmp_path, "check", credentials=missing)
    assert code == 1 and text.startswith("DETENIDO: no se pudo leer la credencial")


def test_clock_skew_stops(tmp_path):
    code, text = run(tmp_path, "check", FakeDemo(server_ms=int(NOW * 1000) - 1500))
    assert code == 1 and "reloj desfasado" in text


def test_kill_switch_status_is_shown(tmp_path):
    (tmp_path / "STOP").write_text("", encoding="utf-8")
    code, text = run(tmp_path, "check")
    assert code == 0 and "ACTIVO" in text


def test_init_requires_the_exact_confirmation_word(tmp_path):
    for answer in ("", "inicializar", "si", "INICIALIZAR AHORA"):
        code, text = run(tmp_path, "init", answer=answer)
        assert code == 1 and "no se ha guardado nada" in text
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
