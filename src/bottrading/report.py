"""Informe reproducible de un backtest (ver DECISIONS.md D016).

Escribe en un directorio:
- report.md: datos usados, parámetros, métricas frente a buy-and-hold,
  notas y limitaciones.
- trades.csv: cada operación simulada con sus costes.
- equity.csv: curva de capital de la estrategia y de buy-and-hold.

Mismas entradas -> mismos archivos byte a byte (sin fecha de ejecución).
"""

import csv
import hashlib
from collections.abc import Sequence
from pathlib import Path

from bottrading.backtest import BacktestResult
from bottrading.data import Candle
from bottrading.metrics import Comparison, Metrics, compute_metrics, irregular_gaps

DISCLAIMER = (
    "**Simulación educativa.** Estos resultados no representan operaciones "
    "reales y la rentabilidad histórica no garantiza rentabilidades futuras."
)


def write_report(
    out_dir: Path,
    *,
    data_path: Path,
    candles: Sequence[Candle],
    fast: int,
    slow: int,
    strategy: BacktestResult,
    benchmark: BacktestResult,
    risk_free_rate: float = 0.0,
) -> dict[str, Path]:
    """Escribe report.md, trades.csv y equity.csv; devuelve sus rutas."""
    if not candles:
        raise ValueError("no se puede generar un informe sin velas")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    comparison = Comparison(
        strategy=compute_metrics(strategy, risk_free_rate),
        benchmark=compute_metrics(benchmark, risk_free_rate),
    )
    paths = {
        "report": out_dir / "report.md",
        "trades": out_dir / "trades.csv",
        "equity": out_dir / "equity.csv",
    }
    markdown = render_markdown(
        data_path=Path(data_path), candles=candles, fast=fast, slow=slow,
        strategy=strategy, comparison=comparison,
    )
    paths["report"].write_text(markdown, encoding="utf-8", newline="\n")
    _write_trades(paths["trades"], strategy)
    _write_equity(paths["equity"], strategy, benchmark)
    return paths


def render_markdown(
    *,
    data_path: Path,
    candles: Sequence[Candle],
    fast: int,
    slow: int,
    strategy: BacktestResult,
    comparison: Comparison,
) -> str:
    config = strategy.config
    s, b = comparison.strategy, comparison.benchmark
    lines = [
        f"# Informe de backtest: cruce SMA {fast}/{slow}",
        "",
        DISCLAIMER,
        "",
        "## Datos",
        "",
        f"- Archivo: `{data_path.name}` (identificado por su SHA-256)",
        f"- SHA-256: `{file_sha256(data_path)}`",
        f"- Velas: {len(candles)}",
        f"- Desde: {candles[0].timestamp.isoformat()}",
        f"- Hasta: {candles[-1].timestamp.isoformat()}",
        f"- Intervalos irregulares (> 1.5 × mediana): "
        f"{irregular_gaps([c.timestamp for c in candles])}",
        "",
        "## Parámetros",
        "",
        f"- Estrategia: cruce de medias simples, rápida {fast}, lenta {slow}",
        f"- Capital inicial: {_money(config.initial_capital)}",
        f"- Comisión: {_pct(config.commission_rate, 3)} por operación",
        f"- Slippage: {_pct(config.slippage_rate, 3)} (adverso)",
        f"- Tamaño máximo de posición: {_pct(config.max_position_fraction)} del efectivo",
        f"- Tasa libre de riesgo anual: {_pct(s.risk_free_rate)}",
        "- Ejecución: señal al cierre de la vela, operación a la apertura de la siguiente",
        "",
        "## Resultados",
        "",
        "| Métrica | Estrategia | Buy-and-hold |",
        "|---|---:|---:|",
        *_metric_rows(s, b),
        "",
        f"Diferencia de retorno total (estrategia − buy-and-hold): "
        f"**{_pct(comparison.excess_return)}**",
        "",
        "## Notas",
        "",
        *_notes("Estrategia", s),
        *_notes("Buy-and-hold", b),
        "",
        "## Limitaciones",
        "",
        "- Se asume que el CSV contiene solo velas cerradas.",
        "- Las velas por año se estiman con la mediana del intervalo entre "
        "velas; con huecos frecuentes, las métricas anualizadas son menos "
        "representativas.",
        "- El drawdown y la volatilidad usan la curva mark-to-market, sin "
        "costes de una venta futura.",
        "- Los costes ejecutados no incluyen los costes estimados de "
        "liquidar una posición abierta; se muestran por separado.",
        "- Sin cortos, apalancamiento ni margen. Una sola posición a la vez.",
        "- Los parámetros no se han optimizado; un único backtest no "
        "demuestra ventaja estadística.",
        "",
    ]
    return "\n".join(lines)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _metric_rows(s: Metrics, b: Metrics) -> list[str]:
    rows = [
        ("Valor final neto (liquidación)", _money(s.final_value_net), _money(b.final_value_net)),
        ("Valor final mark-to-market", _money(s.final_equity_mtm), _money(b.final_equity_mtm)),
        ("Retorno total (neto)", _pct(s.total_return), _pct(b.total_return)),
        ("Retorno anualizado", _pct(s.annualized_return), _pct(b.annualized_return)),
        ("Drawdown máximo", _pct(s.max_drawdown), _pct(b.max_drawdown)),
        ("Volatilidad anualizada", _pct(s.volatility), _pct(b.volatility)),
        ("Sharpe anualizado", _num(s.sharpe), _num(b.sharpe)),
        ("Operaciones ejecutadas", str(s.num_trades), str(b.num_trades)),
        ("Idas y vueltas cerradas", str(len(s.round_trips)), str(len(b.round_trips))),
        ("Porcentaje de ganadoras", _pct(s.win_rate), _pct(b.win_rate)),
        ("Comisiones ejecutadas", _money(s.total_fees), _money(b.total_fees)),
        ("Slippage ejecutado", _money(s.total_slippage), _money(b.total_slippage)),
        ("Costes estimados de liquidación", _money(s.estimated_exit_costs),
         _money(b.estimated_exit_costs)),
        ("Posición abierta al final", _yes_no(s.open_position), _yes_no(b.open_position)),
    ]
    return [f"| {name} | {left} | {right} |" for name, left, right in rows]


def _notes(label: str, metrics: Metrics) -> list[str]:
    if not metrics.notes:
        return [f"- {label}: sin observaciones."]
    return [f"- {label}: {note}." for note in metrics.notes]


def _write_trades(path: Path, result: BacktestResult) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([
            "side", "signal_time", "execution_time", "reference_price", "price",
            "quantity", "fee", "slippage_cost", "cash_after",
        ])
        for t in result.trades:
            writer.writerow([
                t.side.value, t.signal_time.isoformat(), t.execution_time.isoformat(),
                repr(t.reference_price), repr(t.price), repr(t.quantity),
                repr(t.fee), repr(t.slippage_cost), repr(t.cash_after),
            ])


def _write_equity(path: Path, strategy: BacktestResult, benchmark: BacktestResult) -> None:
    if strategy.timestamps != benchmark.timestamps:
        raise ValueError("estrategia y buy-and-hold deben usar las mismas velas")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["timestamp", "strategy_equity", "buy_and_hold_equity"])
        for timestamp, ours, theirs in zip(
            strategy.timestamps, strategy.equity, benchmark.equity
        ):
            writer.writerow([timestamp.isoformat(), repr(ours), repr(theirs)])


def _pct(value: float | None, decimals: int = 2) -> str:
    return "n/d" if value is None else f"{value * 100:.{decimals}f} %"


def _money(value: float) -> str:
    return f"{value:.2f}"


def _num(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.2f}"


def _yes_no(value: bool) -> str:
    return "sí" if value else "no"
