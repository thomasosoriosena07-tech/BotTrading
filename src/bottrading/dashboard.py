"""Panel HTML del paper trading (paper/dashboard.html, D029).

Página autónoma: CSS y gráficos SVG en línea, sin scripts ni recursos
externos (no accede a la red al abrirla). Se regenera en cada ejecución
de `python -m bottrading.paper`. Sin fecha de generación: mismas entradas,
mismo archivo.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING

from bottrading.strategy import Signal

if TYPE_CHECKING:  # solo tipos: paper importa report, que importa este módulo
    from bottrading.paper import PaperAsset, PaperState

CHART_WIDTH, CHART_HEIGHT = 640, 220
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 64, 16, 16, 28

STYLE = """
:root {
  --bg: #f7f7f5; --surface: #ffffff; --text: #1d1d1f; --muted: #6b6b70;
  --border: #e3e3e0; --strategy: #2f6fde; --benchmark: #9a9aa0;
  --up: #1f8a4c; --down: #c23b32; --badge-in: #e6f2ea; --badge-out: #f4ece4;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #141416; --surface: #1d1d20; --text: #ededf0; --muted: #a0a0a8;
    --border: #2e2e33; --strategy: #6ea2ff; --benchmark: #75757d;
    --up: #4cc27e; --down: #ff7a6e; --badge-in: #1d3326; --badge-out: #3a2c20;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 32px 0 12px; }
.notice { color: var(--muted); margin: 0 0 20px; }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px; margin-bottom: 8px; }
.stat, .card { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px; }
.stat .label { color: var(--muted); font-size: 13px; }
.stat .value { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }
.cards { display: grid; gap: 16px; }
.card header { display: flex; align-items: baseline; justify-content: space-between;
  flex-wrap: wrap; gap: 8px; }
.card h3 { margin: 0; font-size: 18px; }
.badge { font-size: 13px; padding: 2px 10px; border-radius: 999px; }
.badge.in { background: var(--badge-in); color: var(--up); }
.badge.out { background: var(--badge-out); color: var(--down); }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px; margin: 12px 0; font-variant-numeric: tabular-nums; }
.metrics div span { display: block; color: var(--muted); font-size: 13px; }
.up { color: var(--up); } .down { color: var(--down); }
svg { width: 100%; height: auto; display: block; }
svg text { fill: var(--muted); font-size: 11px; }
svg .grid { stroke: var(--border); stroke-width: 1; }
svg .strategy { stroke: var(--strategy); }
svg .benchmark { stroke: var(--benchmark); stroke-dasharray: 5 4; }
svg polyline { fill: none; stroke-width: 2; }
.legend { display: flex; gap: 16px; color: var(--muted); font-size: 13px; }
.legend i { display: inline-block; width: 18px; height: 3px; margin-right: 6px;
  vertical-align: middle; }
.table-wrap { overflow-x: auto; background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border);
  white-space: nowrap; }
th { color: var(--muted); font-weight: 500; font-size: 13px; }
tr:last-child td { border-bottom: 0; }
footer { color: var(--muted); font-size: 13px; margin-top: 32px; }
"""


def render_dashboard(state: PaperState) -> str:
    pending = state.pending[0] if state.pending else None
    days = (state.last_day - state.forward_start).days + 1
    parts = [
        "<!doctype html>",
        '<html lang="es">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Paper trading BotTrading</title>",
        f"<style>{STYLE}</style>",
        "</head>",
        "<body><main>",
        "<h1>Paper trading: filtro de tendencia de 50 días</h1>",
        '<p class="notice">Simulación sin dinero: no se envían órdenes ni se usan '
        "cuentas o claves. Velas diarias cerradas de Binance; se actualiza una vez "
        "al día. Los resultados simulados no garantizan rentabilidades futuras.</p>",
        '<section class="summary">',
        _stat("Datos hasta", state.last_day.isoformat()),
        _stat("Días simulados", str(days)),
        _stat("Inicio", state.forward_start.isoformat()),
        _stat("Próximo control",
              f"{pending[1].isoformat()} ({(pending[1] - state.last_day).days} días)"
              if pending else "prueba completada"),
        "</section>",
        "<h2>Activos</h2>",
        '<section class="cards">',
        *[_asset_card(asset) for asset in state.assets],
        "</section>",
        *_checkpoint_sections(state),
        "<h2>Operaciones simuladas</h2>",
        _trades_table(state),
        "<footer>Protocolo fijado antes de empezar (DECISIONS.md D027): estrategia, "
        "costes (comisión 0,1 %, deslizamiento 0,05 %) y capital de 10 000 por "
        "activo congelados. Diario de operaciones en ledger.csv, verificado en cada "
        "ejecución. Generado por <code>python -m bottrading.paper</code>.</footer>",
        "</main></body></html>",
        "",
    ]
    return "\n".join(parts)


def _stat(label: str, value: str) -> str:
    return (f'<div class="stat"><div class="label">{html.escape(label)}</div>'
            f'<div class="value">{html.escape(value)}</div></div>')


def _asset_card(asset: PaperAsset) -> str:
    s, b = asset.strategy_metrics, asset.benchmark_metrics
    inside = asset.strategy.final_quantity > 0
    badge = ('<span class="badge in">dentro del mercado</span>' if inside
             else '<span class="badge out">fuera del mercado</span>')
    diff = s.total_return - b.total_return
    return "\n".join([
        '<article class="card">',
        f"<header><h3>{html.escape(asset.symbol)}</h3>{badge}</header>",
        '<div class="metrics">',
        _metric("Estrategia", _signed_pct(s.total_return)),
        _metric("Buy-and-hold", _signed_pct(b.total_return)),
        _metric("Diferencia", _signed_pct(diff)),
        _metric("Caída máx. estrategia", _pct(s.max_drawdown)),
        _metric("Caída máx. buy-and-hold", _pct(b.max_drawdown)),
        _metric("Operaciones", str(s.num_trades)),
        "</div>",
        _equity_chart(asset),
        '<div class="legend"><span><i style="background: var(--strategy)"></i>'
        "Estrategia</span><span><i style=\"background: var(--benchmark)\"></i>"
        "Buy-and-hold</span></div>",
        "</article>",
    ])


def _metric(label: str, value: str) -> str:
    return f"<div><span>{html.escape(label)}</span>{value}</div>"


def _equity_chart(asset: PaperAsset) -> str:
    dates = [t.date() for t in asset.strategy.timestamps]
    # Buy-and-hold primero: la estrategia se dibuja encima y sigue visible
    # cuando ambas curvas coinciden (estrategia dentro del mercado).
    series = [("benchmark", asset.benchmark.equity), ("strategy", asset.strategy.equity)]
    return svg_line_chart(dates, series, f"Capital de {asset.symbol}: estrategia "
                          "frente a buy-and-hold")


def svg_line_chart(dates: Sequence[date], series: Sequence[tuple[str, Sequence[float]]],
                   title: str) -> str:
    """Gráfico de líneas SVG con eje Y (capital) y fechas extremas en el eje X."""
    values = [v for _, points in series for v in points]
    low, high = min(values), max(values)
    if high == low:
        low, high = low - 1, high + 1
    plot_w = CHART_WIDTH - PAD_LEFT - PAD_RIGHT
    plot_h = CHART_HEIGHT - PAD_TOP - PAD_BOTTOM

    def x(i: int) -> float:
        return PAD_LEFT + (plot_w / 2 if len(dates) == 1 else plot_w * i / (len(dates) - 1))

    def y(v: float) -> float:
        return PAD_TOP + plot_h * (high - v) / (high - low)

    out = [f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" role="img" '
           f'aria-label="{html.escape(title)}"><title>{html.escape(title)}</title>']
    for k in range(4):
        value = low + (high - low) * k / 3
        out.append(f'<line class="grid" x1="{PAD_LEFT}" x2="{CHART_WIDTH - PAD_RIGHT}" '
                   f'y1="{y(value):.1f}" y2="{y(value):.1f}"/>')
        out.append(f'<text x="{PAD_LEFT - 8}" y="{y(value) + 4:.1f}" '
                   f'text-anchor="end">{value:,.0f}</text>')
    out.append(f'<text x="{PAD_LEFT}" y="{CHART_HEIGHT - 8}">{dates[0].isoformat()}</text>')
    out.append(f'<text x="{CHART_WIDTH - PAD_RIGHT}" y="{CHART_HEIGHT - 8}" '
               f'text-anchor="end">{dates[-1].isoformat()}</text>')
    for css_class, points in series:
        coords = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(points))
        out.append(f'<polyline class="{css_class}" points="{coords}"/>')
    out.append("</svg>")
    return "".join(out)


def _checkpoint_sections(state: PaperState) -> list[str]:
    parts = []
    for checkpoint in state.checkpoints:
        rows = []
        for asset in checkpoint.assets:
            s, b = asset.strategy_metrics, asset.benchmark_metrics
            rows.append(
                f"<tr><td>{html.escape(asset.symbol)}</td>"
                f"<td>{_yes_no(s.total_return > b.total_return)}</td>"
                f"<td>{_yes_no(s.max_drawdown < b.max_drawdown)}</td>"
                f"<td>{_signed_pct(s.total_return)}</td><td>{_signed_pct(b.total_return)}</td></tr>")
        parts += [
            f"<h2>Punto de control: {html.escape(checkpoint.label)}, "
            f"{checkpoint.day.isoformat()}</h2>",
            '<div class="table-wrap"><table><thead><tr><th>Activo</th><th>¿Gana más?</th>'
            "<th>¿Menor caída?</th><th>Estrategia</th><th>Buy-and-hold</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>",
        ]
    return parts


def _trades_table(state: PaperState) -> str:
    rows = []
    for asset in state.assets:
        for t in asset.strategy.trades:
            side = "compra" if t.side is Signal.BUY else "venta"
            rows.append((t.execution_time.date().isoformat(), asset.symbol,
                         f"<tr><td>{t.execution_time.date().isoformat()}</td>"
                         f"<td>{html.escape(asset.symbol)}</td><td>{side}</td>"
                         f"<td>{t.price:,.2f}</td><td>{t.quantity:.6f}</td>"
                         f"<td>{t.fee:,.2f}</td></tr>"))
    if not rows:
        return '<p class="notice">Todavía no hay operaciones.</p>'
    body = "".join(row for *_, row in sorted(rows, reverse=True))  # más recientes arriba
    return ('<div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Activo</th>'
            "<th>Lado</th><th>Precio</th><th>Cantidad</th><th>Comisión</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def _pct(value: float) -> str:
    return f"{value * 100:.2f} %"


def _signed_pct(value: float) -> str:
    css = "up" if value > 0 else "down" if value < 0 else ""
    return f'<b class="{css}">{value * 100:+.2f} %</b>'


def _yes_no(value: bool) -> str:
    return "sí" if value else "no"
