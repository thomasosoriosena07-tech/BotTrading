"""Panel HTML PRIVADO de la cuenta demo (D030, F5). Sin red.

Se escribe junto al registro privado (%USERPROFILE%\\.bottrading\\demo\\) y
nunca en paper/ (que se publica en GitHub). Página autónoma con el mismo
estilo que el panel de paper: sin scripts ni recursos externos.

Muestra la cuenta demo por activo (efectivo, cantidad, coste, valor al
precio del momento y resultado frente al presupuesto de 1000 USDT), las
órdenes del bot frente al modelo, la racha hacia los 30 días sin
incidencias y las últimas ejecuciones. Dinero ficticio: mide la ejecución,
no la rentabilidad (eso es T019).
"""

import html
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from bottrading.dashboard import STYLE
from bottrading.demo_ledger import OrderRecord
from bottrading.demo_report import FillMetrics, RunEntry, clean_streak, redact
from bottrading.execution import BUDGET_PER_ASSET, Holding

BUDGET = Decimal(repr(BUDGET_PER_ASSET))


def asset_value(holding: Holding, price: Decimal | None) -> Decimal | None:
    """Efectivo + posición al precio dado; None si no hay precio y hay posición."""
    cash, quantity = Decimal(repr(holding.cash)), Decimal(repr(holding.quantity))
    if quantity == 0:
        return cash
    return None if price is None else cash + quantity * price


def render_demo_dashboard(fills: Sequence[FillMetrics], records: Mapping[str, OrderRecord],
                          runs: Sequence[RunEntry], holdings: Mapping[str, Holding],
                          prices: Mapping[str, Decimal | None], today: date,
                          generated_at: datetime, paper_dashboard: Path) -> str:
    values = {s: asset_value(h, prices.get(s)) for s, h in holdings.items()}
    known = [v for v in values.values() if v is not None]
    total = sum(known, Decimal(0)) if len(known) == len(values) else None
    budget = BUDGET * len(holdings)
    last = runs[-1] if runs else None
    parts = [
        "<!doctype html>", '<html lang="es">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Cuenta demo BotTrading</title>", f"<style>{STYLE}</style>", "</head>",
        "<body><main>",
        "<h1>Cuenta demo de Binance: ejecución del bot</h1>",
        '<p class="notice">Dinero ficticio (Binance Spot Demo). El bot decide una vez al '
        "día con velas diarias cerradas; la mayoría de los días no opera. Este panel es "
        "privado: no se publica. Mide la ejecución, no la rentabilidad de la estrategia "
        "(eso es el paper trading, T019).</p>",
        '<section class="summary">',
        _stat("Valor de la cuenta del bot",
              "n/d" if total is None else f"{total:,.2f} USDT"),
        _stat("Resultado frente al presupuesto",
              "n/d" if total is None else _signed(total - budget, budget)),
        _stat("Días seguidos sin incidencias", f"{clean_streak(runs, today)} de 30"),
        _stat("Última ejecución",
              f"{last.at[:16].replace('T', ' ')} UTC: {last.outcome}" if last else "ninguna"),
        "</section>",
        "<h2>Activos</h2>",
        '<section class="cards">',
        *[_asset_card(s, holdings[s], prices.get(s), values[s]) for s in sorted(holdings)],
        "</section>",
        "<h2>Órdenes del bot frente al modelo</h2>",
        _orders_table(fills),
        "<h2>Últimas ejecuciones</h2>",
        _runs_table(runs),
        f"<footer>Generado {html.escape(generated_at.strftime('%Y-%m-%d %H:%M'))} UTC con "
        "<code>python -m bottrading.demo_client report</code> o con la ejecución diaria. "
        "Precio en vivo y órdenes en demo.binance.com (Historial de órdenes, ids bt-...). "
        f"Panel de la estrategia (paper): <code>{html.escape(str(paper_dashboard))}</code>. "
        f"Órdenes registradas: {len(records)}.</footer>",
        "</main></body></html>", "",
    ]
    return "\n".join(parts)


def _stat(label: str, value: str) -> str:
    return (f'<div class="stat"><div class="label">{html.escape(label)}</div>'
            f'<div class="value">{html.escape(value)}</div></div>')


def _metric(label: str, value: str) -> str:
    return f"<div><span>{html.escape(label)}</span>{html.escape(value)}</div>"


def _signed(amount: Decimal, base: Decimal) -> str:
    pct = amount / base * 100 if base else Decimal(0)
    return f"{amount:+,.2f} USDT ({pct:+.2f} %)"


def _asset_card(symbol: str, holding: Holding, price: Decimal | None,
                value: Decimal | None) -> str:
    inside = holding.quantity > 0
    badge = ('<span class="badge in">dentro del mercado</span>' if inside
             else '<span class="badge out">fuera del mercado</span>')
    return "\n".join([
        '<article class="card">',
        f"<header><h3>{html.escape(symbol)}</h3>{badge}</header>",
        '<div class="metrics">',
        _metric("Precio del momento", "n/d" if price is None else f"{price:,.2f}"),
        _metric("Cantidad", f"{Decimal(repr(holding.quantity)).normalize():f}"),
        _metric("Coste de la posición", f"{holding.cost:,.2f} USDT"),
        _metric("Efectivo", f"{holding.cash:,.2f} USDT"),
        _metric("Valor", "n/d" if value is None else f"{value:,.2f} USDT"),
        _metric("Resultado vs 1000", "n/d" if value is None else _signed(value - BUDGET, BUDGET)),
        "</div>",
        "</article>",
    ])


def _orders_table(fills: Sequence[FillMetrics]) -> str:
    rows = []
    for f in reversed(fills):
        fee = (f"{f.fee_rate * 100:.3f} %" if f.fee_rate is not None
               else f"{f.fee_amount.normalize():f} {f.fee_asset}")
        cells = [f.client_order_id, f.side,
                 f.executed_at.strftime("%Y-%m-%d %H:%M") if f.executed_at else "n/d",
                 f"{f.average_price:,.2f}",
                 "vela pendiente" if f.open_price is None else f"{f.open_price:,.2f}",
                 _bps(f.vs_open_bps), _bps(f.vs_model_bps), fee]
        rows.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
    if not rows:
        rows.append('<tr><td colspan="8">Todavía no hay órdenes ejecutadas</td></tr>')
    header = ["Orden", "Lado", "Ejecución (UTC)", "Precio medio", "Apertura del día",
              "vs apertura (pb)", "vs modelo (pb)", "Comisión"]
    return _table(header, rows)


def _runs_table(runs: Sequence[RunEntry]) -> str:
    rows = []
    for run in list(reversed(runs))[:15]:
        cells = [run.at[:16].replace("T", " "), run.outcome,
                 "desconocido" if run.orders is None else str(run.orders), redact(run.detail)]
        rows.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
    if not rows:
        rows.append('<tr><td colspan="4">Todavía no hay ejecuciones registradas</td></tr>')
    return _table(["Fecha (UTC)", "Resultado", "Envíos", "Detalle"], rows)


def _table(header: Sequence[str], rows: Sequence[str]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    return ('<div class="table-wrap"><table><thead><tr>' + head + "</tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>")


def _bps(value: Decimal | None) -> str:
    return "n/d" if value is None else f"{value:+.1f}"
