"""Informe de ejecución demo (D030, F5): métricas, diario y racha. Sin red."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bottrading.data import Candle
from bottrading.demo_ledger import OrderRecord
from bottrading.demo_report import (
    RunEntry,
    append_run,
    clean_streak,
    collect_fills,
    fill_metrics,
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
