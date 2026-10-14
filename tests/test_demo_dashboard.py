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
