"""Informe de ejecución demo (D030, F5): métricas, diario y racha. Sin red."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bottrading.data import Candle
from bottrading.demo_ledger import OrderRecord
from bottrading.demo_report import (
    RunEntry,
    SendQuote,
    append_quote,
    append_run,
    clean_streak,
    collect_fills,
    fill_metrics,
    read_quotes,
    read_runs,
    render_report,
)
from bottrading.execution import OrderIntent
from bottrading.strategy import Signal

SIGNAL = datetime(2026, 8, 17, tzinfo=timezone.utc)
EXEC_MS = int(datetime(2026, 10, 14, 3, 54, 36, tzinfo=timezone.utc).timestamp() * 1000)
BUY = OrderIntent("BTCUSDT", Signal.BUY, SIGNAL, quote_amount=1000.0)
RECORD = OrderRecord(BUY, "FINAL", "FILLED", 0.01193)
OPENS = {date(2026, 10, 14): Decimal("83000")}


def trade(qty, quote, fee="0.00001193", asset="BTC", time=EXEC_MS, order_id=7, trade_id=1):
    return {"id": trade_id, "orderId": order_id, "qty": qty, "quoteQty": quote,
            "commission": fee, "commissionAsset": asset, "time": time}


ORDER = {"orderId": 7, "clientOrderId": BUY.client_order_id, "side": "BUY",
         "executedQty": "0.01193000", "status": "FILLED"}


def test_metrics_of_the_first_real_demo_order():
    # Primera orden real: 0.01193 BTC por 999.73 USDT; comisión en BTC.
    m = fill_metrics(RECORD, ORDER, [trade("0.01193", "999.73")], OPENS, "BTC")
    assert m.average_price == Decimal("999.73") / Decimal("0.01193")
    assert m.open_price == Decimal("83000")
    assert m.modeled_price == Decimal("83000") * Decimal("1.0005")
    # compra por encima de la apertura: coste positivo
    assert m.vs_open_bps == (m.average_price - 83000) / 83000 * 10_000
    assert m.vs_model_bps < m.vs_open_bps  # el modelo ya incluía 5 pb
    assert m.fee_rate == Decimal("0.00001193") * m.average_price / Decimal("999.73")
    assert m.fee_rate == pytest.approx(Decimal("0.001"), rel=Decimal("1e-9"))
    assert m.delay_hours == pytest.approx(Decimal(3 * 3600 + 54 * 60 + 36) / 3600)


def test_sell_slippage_sign_and_fee_in_usdt():
    sell = OrderIntent("BTCUSDT", Signal.SELL, SIGNAL, quantity=0.01)
    record = OrderRecord(sell, "FINAL", "FILLED", 0.01)
    order = dict(ORDER, side="SELL", clientOrderId=sell.client_order_id)
    m = fill_metrics(record, order, [trade("0.01", "820", fee="0.82", asset="USDT")], OPENS, "BTC")
    assert m.average_price == Decimal("82000")
    assert m.vs_open_bps > 0  # vender por debajo de la apertura es peor
    assert m.fee_rate == Decimal("0.001")


def test_bnb_fee_pending_candle_and_missing_time():
    m = fill_metrics(RECORD, ORDER, [trade("0.01193", "999.73", fee="0.001", asset="BNB",
                                           time=None)], OPENS, "BTC")
    assert m.fee_rate is None and m.fee_asset == "BNB" and m.fee_amount == Decimal("0.001")
    text = render_report([m], {BUY.client_order_id: RECORD}, [], date(2026, 10, 14))
    assert "0.001 BNB (sin convertir)" in text  # revisión de Codex: importe visible
    assert m.executed_at is None and m.delay_hours is None and m.open_price is None
    later = fill_metrics(RECORD, ORDER, [trade("0.01193", "999.73")], {}, "BTC")
    assert later.open_price is None and later.vs_open_bps is None and later.modeled_price is None


def test_collect_fills_uses_only_the_bot_orders_with_executions():
    candles = {"BTCUSDT": [Candle(datetime(2026, 10, 14, tzinfo=timezone.utc),
                                  83000.0, 84000.0, 82000.0, 83500.0, 1.0)]}
    orders = {"BTCUSDT": [ORDER, dict(ORDER, orderId=8, clientOrderId="ajena"),
                          dict(ORDER, orderId=9, executedQty="0")],
              "ETHUSDT": [], "SOLUSDT": []}
    trades = {"BTCUSDT": [trade("0.01193", "999.73")], "ETHUSDT": [], "SOLUSDT": []}
    fills = collect_fills({BUY.client_order_id: RECORD}, orders, trades, candles,
                          {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL"})
    assert [f.client_order_id for f in fills] == [BUY.client_order_id]
    assert fills[0].open_price == Decimal("83000.0")


def runs(*days_outcomes):
    return [RunEntry(day, f"{day}T13:00:00+00:00", outcome, 0, "x")
            for day, outcome in days_outcomes]


def test_clean_streak_counts_consecutive_ok_days():
    d = date(2026, 10, 20)
    assert clean_streak([], d) == 0
    assert clean_streak(runs((d, "ok")), d) == 1
    history = runs((d - timedelta(days=2), "ok"), (d - timedelta(days=1), "ok"), (d, "ok"))
    assert clean_streak(history, d) == 3
    # hoy aún no ha corrido: cuenta hasta ayer
    assert clean_streak(history[:2], d) == 2
    # un día con una ejecución detenida corta la racha, aunque luego haya otra ok
    broken = runs((d - timedelta(days=1), "ok"), (d, "detenido"), (d, "ok"))
    assert clean_streak(broken, d) == 0
    # un día sin ejecución corta la racha
    gap = runs((d - timedelta(days=3), "ok"), (d - timedelta(days=1), "ok"), (d, "ok"))
    assert clean_streak(gap, d) == 2


def test_run_journal_appends_and_reads_back(tmp_path):
    path = tmp_path / "runs.csv"
    at = datetime(2026, 10, 14, 13, 5, tzinfo=timezone.utc)
    append_run(path, at.date(), at, "ok", 1, "sin incidencias")
    append_run(path, at.date(), at, "detenido", 0, "reloj desfasado\nlínea 2")
    append_run(path, at.date(), at, "detenido", None, "registro ilegible")
    entries = read_runs(path)
    assert [e.outcome for e in entries] == ["ok", "detenido", "detenido"]
    assert [e.orders for e in entries] == [1, 0, None]
    assert entries[1].detail == "reloj desfasado línea 2"
    path.write_text("otra,cabecera\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cabecera"):
        read_runs(path)


def test_render_report_states_scope_and_numbers():
    m = fill_metrics(RECORD, ORDER, [trade("0.01193", "999.73")], OPENS, "BTC")
    text = render_report([m], {BUY.client_order_id: RECORD},
                         runs((date(2026, 10, 14), "ok")), date(2026, 10, 14))
    assert "DEMO (dinero ficticio)" in text and "No mide la rentabilidad" in text
    assert BUY.client_order_id in text and "BUY" in text
    assert "Días seguidos sin incidencias: 1 de 30" in text
    assert "0.100 %" in text  # comisión real calculada
    empty = render_report([], {}, [], date(2026, 10, 14))
    assert "(ninguna)" in empty and "0 de 30" in empty


# --- slippage real frente a la cotización del envío (opción 1, 2026-10-15) ------------

CAPTURED = datetime(2026, 10, 14, 3, 54, 30, tzinfo=timezone.utc)


def test_buy_separates_real_slippage_from_timing():
    m = fill_metrics(RECORD, ORDER, [trade("0.01193", "999.73")], OPENS, "BTC")
    quote = SendQuote(BUY.client_order_id, CAPTURED, Decimal("83790"), Decimal("83795"))
    q = replace(m, send_quote=quote)
    assert q.send_reference == Decimal("83795")  # al comprar, el ask
    assert q.slippage_bps == (q.average_price - 83795) / Decimal(83795) * 10_000
    assert q.timing_bps == (Decimal(83795) - 83000) / Decimal(83000) * 10_000  # mercado, no ejecución
    assert q.spread_bps == Decimal(5) / Decimal("83792.5") * 10_000
    assert q.latency_seconds == Decimal(6)
    assert m.slippage_bps is None and m.timing_bps is None  # sin cotización: n/d


def test_sell_uses_the_bid_and_lower_is_worse():
    sell = OrderIntent("BTCUSDT", Signal.SELL, SIGNAL, quantity=0.01)
    record = OrderRecord(sell, "FINAL", "FILLED", 0.01)
    order = dict(ORDER, side="SELL", clientOrderId=sell.client_order_id)
    m = fill_metrics(record, order, [trade("0.01", "820", fee="0.82", asset="USDT")], OPENS, "BTC")
    q = replace(m, send_quote=SendQuote(sell.client_order_id, CAPTURED, Decimal("82100"),
                                        Decimal("82110")))
    assert q.send_reference == Decimal("82100")
    assert q.slippage_bps > 0  # vendió a 82000, por debajo del bid de 82100
    assert q.timing_bps > 0  # el bid ya estaba por debajo de la apertura (83000)


def test_quotes_round_trip_and_the_last_one_per_order_wins(tmp_path):
    path = tmp_path / "send_quotes.csv"
    first = SendQuote("bt-A", CAPTURED, Decimal("1.5"), Decimal("1.6"))
    retry = SendQuote("bt-A", CAPTURED + timedelta(days=1), Decimal("2.5"), Decimal("2.6"))
    other = SendQuote("bt-B", CAPTURED, Decimal("10"), Decimal("10"))
    for quote in (first, other, retry):
        append_quote(path, quote)
    assert read_quotes(path) == {"bt-A": retry, "bt-B": other}
    assert read_quotes(tmp_path / "no-existe.csv") == {}


@pytest.mark.parametrize("bid,ask", [("0", "1"), ("2", "1"), ("NaN", "1"), ("-1", "1")])
def test_invalid_quotes_are_never_written(tmp_path, bid, ask):
    path = tmp_path / "send_quotes.csv"
    with pytest.raises(ValueError):
        append_quote(path, SendQuote("bt-A", CAPTURED, Decimal(bid), Decimal(ask)))
    assert not path.exists()


@pytest.mark.parametrize("content", [
    "otra,cabecera\n",
    "client_order_id,captured_at,bid,ask\nbt-A,2026-10-14T03:54:30,1,2\n",  # sin zona horaria
    "client_order_id,captured_at,bid,ask\nbt-A,2026-10-14T03:54:30+00:00,3,2\n",  # bid > ask
    "client_order_id,captured_at,bid,ask\nbt-A,2026-10-14T03:54:30+00:00,1\n",
])
def test_corrupt_quote_files_are_rejected(tmp_path, content):
    path = tmp_path / "send_quotes.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        read_quotes(path)


def test_report_shows_real_slippage_and_marks_orders_without_quote():
    m = fill_metrics(RECORD, ORDER, [trade("0.01193", "999.73")], OPENS, "BTC")
    quoted = replace(m, client_order_id="bt-X",
                     send_quote=SendQuote("bt-X", CAPTURED, Decimal("83790"), Decimal("83795")))
    text = render_report([m, quoted], {}, [], date(2026, 10, 15))
    assert "## Calidad de ejecución (frente a la cotización del envío)" in text
    assert "Slippage real medio:" in text and "en 1 órdenes con cotización" in text
    assert "sin cotización" in text
