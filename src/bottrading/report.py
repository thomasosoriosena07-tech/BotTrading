"""Informe reproducible de un backtest (ver DECISIONS.md D016).

Escribe en un directorio:
- report.md: datos usados, parámetros, métricas frente a buy-and-hold,
  notas y limitaciones.
- trades.csv: cada operación simulada con sus costes.
- equity.csv: curva de capital de la estrategia y de buy-and-hold.

Mismas entradas -> mismos archivos byte a byte (sin fecha de ejecución).

write_selection_report (T016) escribe selection.md y trials.csv con la
selección walk-forward, sin métricas del holdout final.
"""

from __future__ import annotations

import csv
import hashlib
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from bottrading.backtest import BacktestResult
from bottrading.binance import verify_checksum
from bottrading.data import Candle
from bottrading.metrics import Comparison, Metrics, compute_metrics, irregular_gaps

if TYPE_CHECKING:  # solo tipos: walkforward importa este módulo
    from bottrading.walkforward import SelectionResult, WindowScore

DISCLAIMER = (
    "**Simulación educativa.** Estos resultados no representan operaciones "
    "reales y la rentabilidad histórica no garantiza rentabilidades futuras."
)


def write_report(
    out_dir: Path,
    *,
    data_paths: Sequence[Path],
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
        data_paths=[Path(path) for path in data_paths], candles=candles,
        fast=fast, slow=slow,
        strategy=strategy, comparison=comparison,
    )
    paths["report"].write_text(markdown, encoding="utf-8", newline="\n")
    _write_trades(paths["trades"], strategy)
    _write_equity(paths["equity"], strategy, benchmark)
    return paths


def render_markdown(
    *,
    data_paths: Sequence[Path],
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
        *_data_files(data_paths),
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


def _data_files(paths: Sequence[Path]) -> list[str]:
    """Nombre y SHA-256 de cada archivo; no la ruta (no depende de la ubicación)."""
    if len(paths) == 1:
        return [
            f"- Archivo: `{paths[0].name}` (identificado por su SHA-256)",
            f"- SHA-256: `{file_sha256(paths[0])}`",
        ]
    return [f"- Archivos ({len(paths)}), identificados por su SHA-256:"] + [
        f"  - `{path.name}`: `{file_sha256(path)}` ({_checksum_label(path)})"
        for path in paths
    ]


def _checksum_label(path: Path) -> str:
    # verify_checksum lanza error si el .CHECKSUM existe y no coincide.
    return "checksum verificado" if verify_checksum(path) else "sin .CHECKSUM"



def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_selection_report(
    out_dir: Path,
    *,
    data_paths: Sequence[Path],
    candles: Sequence[Candle],
    result: SelectionResult,
) -> dict[str, Path]:
    """Escribe selection.md y trials.csv (todas las pruebas, D021)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"selection": out_dir / "selection.md", "trials": out_dir / "trials.csv"}
    text = render_selection_markdown(
        data_paths=[Path(p) for p in data_paths], candles=candles, result=result)
    paths["selection"].write_text(text, encoding="utf-8", newline="\n")
    _write_trials(paths["trials"], result)
    return paths


def render_selection_markdown(
    *, data_paths: Sequence[Path], candles: Sequence[Candle], result: SelectionResult
) -> str:
    plan, winner = result.plan, result.winner

    def day(index: int) -> str:
        return candles[index].timestamp.date().isoformat()

    numbers = [w.number for w in plan.windows]
    header = ("| # | Combinación | Mediana Sharpe | Mediana drawdown | Mediana retorno "
              "| Mediana volatilidad | "
              + " | ".join(f"Sharpe V{n}" for n in numbers) + " |")
    divider = "|---:|---|---:|---:|---:|---:|" + "---:|" * len(numbers)
    rows = [
        _selection_row(str(rank), f"`{score.candidate.label}`", score.windows)
        for rank, score in enumerate(result.ranking, start=1)
    ]
    rows.append(_selection_row("—", "buy-and-hold (referencia)", result.benchmark))
    returns_header = "| Combinación | " + " | ".join(f"Retorno V{n}" for n in numbers) + " |"
    returns_divider = "|---|" + "---:|" * len(numbers)
    returns_rows = [
        f"| `{winner.candidate.label}` (elegida) | "
        + " | ".join(_pct(w.total_return) for w in winner.windows) + " |",
        "| buy-and-hold | " + " | ".join(_pct(w.total_return) for w in result.benchmark) + " |",
    ]
    edge = (
        f"La combinación elegida es **`{winner.candidate.label}`** "
        f"(mediana del Sharpe {_num(winner.median_sharpe)})."
        if result.has_edge else
        "**Ninguna combinación mostró ventaja en validación** (la mejor mediana "
        f"del Sharpe es {_num(winner.median_sharpe)} <= 0). Se registra igualmente "
        f"`{winner.candidate.label}` como la elegida por el criterio."
    )
    lines = [
        "# Selección walk-forward",
        "",
        DISCLAIMER,
        "",
        "**El holdout final no se ha usado**: sus precios no intervienen en "
        "ningún resultado de este informe.",
        "",
        "## Datos",
        "",
        *_data_files(data_paths),
        f"- Velas: {len(candles)} ({day(0)} a {day(len(candles) - 1)})",
        "",
        "## Particiones",
        "",
        "| Ventana | Ajuste (historial) | Validación | Velas de validación |",
        "|---|---|---|---:|",
        *[
            f"| V{w.number} | {day(w.train_start)} a {day(w.train_end - 1)} | "
            f"{day(w.validation_start)} a {day(w.validation_end - 1)} | "
            f"{w.validation_end - w.validation_start} |"
            for w in plan.windows
        ],
        f"| Holdout final | — | {day(plan.holdout_start)} a {day(plan.holdout_end - 1)} "
        f"(sin usar) | {plan.holdout_end - plan.holdout_start} |",
        "",
        "## Criterio (fijado antes de ejecutar, D021)",
        "",
        "- Mayor mediana del Sharpe en las ventanas de validación; desempate por "
        "menor mediana del drawdown máximo. Sharpe no disponible = 0.",
        "- Cada ventana hereda la posición de la estrategia (D020); buy-and-hold "
        "se evalúa con la misma regla.",
        f"- Combinaciones probadas: **{result.trials}**.",
        "",
        "## Resultado",
        "",
        edge,
        "",
        header,
        divider,
        *rows,
        "",
        "Retorno neto por ventana de la elegida frente a buy-and-hold:",
        "",
        returns_header,
        returns_divider,
        *returns_rows,
        "",
        "## Advertencias",
        "",
        f"- Se eligió la mejor de {result.trials} combinaciones: su resultado en "
        "validación está sesgado al alza por la propia selección.",
        "- Las ventanas de validación sirven para elegir; no son una prueba "
        "independiente. La evaluación independiente es el holdout final (T017).",
        "- Datos de un solo símbolo existente hoy (sesgo de supervivencia) y de "
        "un periodo concreto (cambios de régimen).",
        "- Comisión y slippage son supuestos configurables, no costes reales "
        "garantizados.",
        "",
    ]
    return "\n".join(lines)


def _write_trials(path: Path, result: SelectionResult) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["rank", "candidate", "strategy", "params", "window",
                         "sharpe", "total_return", "max_drawdown", "num_trades",
                         "volatility"])
        for rank, score in enumerate(result.ranking, start=1):
            params = ";".join(f"{k}={v}" for k, v in score.candidate.params)
            for w in score.windows:
                writer.writerow(_trial_row(rank, score.candidate.label,
                                           score.candidate.strategy, params, w))
        for w in result.benchmark:
            writer.writerow(_trial_row("", "buy_and_hold", "buy_and_hold", "", w))


def _trial_row(rank, label: str, strategy: str, params: str, w: WindowScore) -> list:
    return [rank, label, strategy, params, w.window,
            "" if w.sharpe is None else repr(w.sharpe),
            repr(w.total_return), repr(w.max_drawdown), w.num_trades,
            "" if w.volatility is None else repr(w.volatility)]


def _selection_row(rank: str, label: str, windows: Sequence[WindowScore]) -> str:
    sharpe = statistics.median(0.0 if w.sharpe is None else w.sharpe for w in windows)
    volatilities = [w.volatility for w in windows if w.volatility is not None]
    volatility = statistics.median(volatilities) if volatilities else None
    return (
        f"| {rank} | {label} | {_num(sharpe)} | "
        f"{_pct(statistics.median(w.max_drawdown for w in windows))} | "
        f"{_pct(statistics.median(w.total_return for w in windows))} | {_pct(volatility)} | "
        + " | ".join(_num(w.sharpe) for w in windows) + " |"
    )


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
