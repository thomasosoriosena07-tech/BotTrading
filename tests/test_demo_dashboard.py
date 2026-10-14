"""Panel privado de la cuenta demo (D030, F5). Sin red."""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from bottrading.demo_dashboard import asset_value, render_demo_dashboard
from bottrading.demo_report import RunEntry
from bottrading.execution import Holding

TODAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 13, 5, tzinfo=timezone.utc)
HOLDINGS = {"BTCUSDT": Holding(0.27, 0.01191807, 999.73),
            "ETHUSDT": Holding(1000.0), "SOLUSDT": Holding(1000.0)}
PRICES = {"BTCUSDT": Decimal("85000"), "ETHUSDT": Decimal("2500"), "SOLUSDT": None}


def page(**overrides):
    kwargs = dict(fills=[], records={}, runs=[RunEntry(TODAY, "2026-10-14T13:05:00+00:00",
                                                       "ok", 0, "sin incidencias")],
                  holdings=HOLDINGS, prices=PRICES, today=TODAY, generated_at=NOW,
                  paper_dashboard=Path("C:/repo/paper/dashboard.html"))
    kwargs.update(overrides)
    return render_demo_dashboard(**kwargs)


def test_asset_value_uses_the_price_only_with_a_position():
    btc = asset_value(HOLDINGS["BTCUSDT"], Decimal("85000"))
    assert btc == Decimal("0.27") + Decimal("0.01191807") * 85000
    assert asset_value(HOLDINGS["ETHUSDT"], None) == Decimal("1000.0")  # sin posición
    assert asset_value(HOLDINGS["BTCUSDT"], None) is None  # sin precio: n/d


def test_dashboard_shows_account_streak_and_is_self_contained():
    text = page()
    for symbol in HOLDINGS:
        assert symbol in text
    assert "dentro del mercado" in text and "fuera del mercado" in text
    value = Decimal("0.27") + Decimal("0.01191807") * 85000
    assert f"{value:,.2f} USDT" in text
    assert "1 de 30" in text and "privado" in text
    assert "<script" not in text.lower() and "http" not in text.lower()


def test_total_is_unknown_when_a_held_asset_has_no_price():
    text = page(prices={"BTCUSDT": None, "ETHUSDT": None, "SOLUSDT": None})
    assert "Valor de la cuenta del bot</div><div class=\"value\">n/d" in text


def test_untrusted_text_is_escaped():
    text = page(runs=[RunEntry(TODAY, "2026-10-14T13:05:00+00:00", "detenido", None,
                               "<img src=x onerror=alert(1)>")])
    assert "<img" not in text and "&lt;img" in text and "desconocido" in text


# --- revisión de Codex de e945563 -------------------------------------------------------


def test_run_details_are_redacted_in_panel_and_report():
    from bottrading.demo_report import render_report
    key = "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A"
    runs = [RunEntry(TODAY, "2026-10-14T13:05:00+00:00", "detenido", 0,
                     f"fallo con {key} y signature=abc123 en bt-BTCUSDT-20260817-B")]
    for text in (page(runs=runs), render_report([], {}, runs, TODAY)):
        assert key not in text and "abc123" not in text
        assert "bt-BTCUSDT-20260817-B" in text  # ids con separadores intactos


class Tickers:
    def __init__(self, answers):
        self.answers = answers

    def book_ticker(self, symbol):
        answer = self.answers[symbol]
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_only_finite_positive_coherent_prices_are_used():
    from bottrading.demo_client import DemoApiError, _prices
    prices = _prices(Tickers({
        "BTCUSDT": {"bidPrice": "NaN", "askPrice": "1"},
        "ETHUSDT": {"bidPrice": "2500", "askPrice": "2400"},  # ask < bid
        "SOLUSDT": {"bidPrice": "-1", "askPrice": "1"},
    }))
    assert prices == {"BTCUSDT": None, "ETHUSDT": None, "SOLUSDT": None}
    prices = _prices(Tickers({
        "BTCUSDT": {"bidPrice": "84999", "askPrice": "85001"},
        "ETHUSDT": {"bidPrice": "Infinity", "askPrice": "Infinity"},
        "SOLUSDT": DemoApiError("GET", "/api/v3/ticker/bookTicker", 500),
    }))
    assert prices == {"BTCUSDT": Decimal("85000"), "ETHUSDT": None, "SOLUSDT": None}
    assert _prices(Tickers({"BTCUSDT": {}, "ETHUSDT": {"bidPrice": "x", "askPrice": "1"},
                            "SOLUSDT": {"bidPrice": "0", "askPrice": "0"}})) == \
        {"BTCUSDT": None, "ETHUSDT": None, "SOLUSDT": None}


def test_explicit_paths_inside_the_repository_or_onedrive_are_refused(tmp_path, monkeypatch):
    from bottrading.demo_client import Credentials, DemoPaths, main
    from bottrading.demo_ledger import REPO_ROOT
    inside = REPO_ROOT / "estado_privado_prueba"
    monkeypatch.setenv("OneDrive", str(tmp_path / "OneDrive"))
    for folder in (inside, tmp_path / "OneDrive" / "x"):
        lines = []
        paths = DemoPaths(folder / "orders.csv", folder / "baseline.json", folder / "STOP")
        code = main(["report"], credentials=lambda: Credentials("a" * 32, "b" * 32),
                    transport=lambda request, headers: None, paths=paths, out=lines.append)
        assert code == 1 and "ubicación privada no permitida" in lines[-1]
        assert not folder.exists()
