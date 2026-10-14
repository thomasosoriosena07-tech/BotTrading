"""EXP-15M-001: validación walk-forward y selección única (EXPERIMENT_15M.md A.6-A.8; D031).

`python -m bottrading.exp15m_eval validate` evalúa las 4 configuraciones en los
11 trimestres de validación (2024-01 a 2026-09) y los 4 escenarios de coste
(176 evaluaciones), aplica la regla de selección única de A.6 y escribe el
informe de validación. Sin red. Nunca lee datos del holdout: se detiene si
hay velas desde 2026-10-01.

- Señales: donchian_signals sobre cierres 15m, calculadas una vez por
  configuración sobre toda la historia (son causales) y recortadas; antes de
  usarlas se comprueba en puntos de corte que coinciden con un cálculo directo
  sobre el prefijo (prueba de prefijos con datos reales).
- Cada tramo se evalúa con evaluate_segment (calentamiento causal y herencia
  de posición, D020) y pasa las identidades contables (defecto crítico 3); un
  fallo detiene todo.
- Referencias por trimestre: buy-and-hold 15m, baseline operativo T019 (código
  congelado sobre velas diarias) y efectivo (0 %).
- Desarrollo (2020-2023): se publica como información; no entra en la selección.
"""

import argparse
import csv
import hashlib
import io
import statistics
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bottrading.backtest import BacktestResult
from bottrading.binance import load_binance_klines
from bottrading.config import BacktestConfig
from bottrading.data import Candle, DataValidationError
from bottrading.exp15m_data import (
    build_manifest,
    check_manifest,
    load_15m,
    render_manifest,
    zip_files,
)
from bottrading.exp15m_metrics import Summary, accounting_problems, daily_series, risk, summarize
from bottrading.metrics import max_drawdown
from bottrading.splits import evaluate_segment
from bottrading.strategy import Signal, buy_and_hold_signals, donchian_signals, trend_filter_signals

# No se importan holdout, crossasset ni walkforward: arrastran report y paper. Sus
# valores se copian aquí y una prueba exige que sean idénticos a los del baseline.
BASELINE_WINDOW = 50  # crossasset.FROZEN_CANDIDATE = trend_filter(window=50), D022


@dataclass(frozen=True)
class Scenario:
    name: str
    commission_rate: float
    slippage_rate: float


SCENARIOS = (  # = holdout.SCENARIOS (D023), escenarios aprobados en A.12-2
    Scenario("sin costes", 0.0, 0.0),
    Scenario("bajo", 0.00075, 0.0002),
    Scenario("base", 0.001, 0.0005),
    Scenario("alto", 0.002, 0.001),
)
UTC = timezone.utc
CAPITAL = 10_000.0
BASE = "base"
CONFIGS = ((48, 24), (48, 48), (96, 24), (96, 48))  # entry × exit (A.6), orden fijo
HOLDOUT_START = datetime(2026, 10, 1, tzinfo=UTC)  # separación + holdout: nunca se leen aquí
DEVELOPMENT = (datetime(2020, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC))


def _quarters() -> tuple[tuple[datetime, datetime], ...]:
    """Los 11 trimestres naturales de validación, de 2024T1 a 2026T3 ([inicio, fin))."""
    quarters = []
    for year in (2024, 2025, 2026):
        for month in (1, 4, 7, 10):
            if (year, month) > (2026, 7):
                break
            end = (datetime(year + 1, 1, 1, tzinfo=UTC) if month == 10
                   else datetime(year, month + 3, 1, tzinfo=UTC))
            quarters.append((datetime(year, month, 1, tzinfo=UTC), end))
    return tuple(quarters)


QUARTERS = _quarters()


@dataclass(frozen=True)
class Evaluation:
    label: str  # "donchian(48,24)", "buy-and-hold", "baseline T019"
    segment: str  # "2024T1"... o "desarrollo"
    scenario: str
    summary: Summary | None  # None para el baseline diario (ver BaselineSummary)
    net_return: float
    sharpe: float | None
    max_drawdown: float  # intradía 15m (o diario para el baseline)


@dataclass(frozen=True)
class Selection:
    config: tuple[int, int]
    medians: dict[tuple[int, int], tuple[float, float]]  # (mediana Sharpe, mediana DD)
    c7: bool


def label(config: tuple[int, int]) -> str:
    return f"donchian({config[0]},{config[1]})"


def quarter_name(start: datetime) -> str:
    return f"{start.year}T{(start.month - 1) // 3 + 1}"


def bounds(candles: Sequence[Candle], start: datetime, end: datetime) -> tuple[int, int]:
    """Índices [i, j) de las velas con start <= open_time < end."""
    i = next((k for k, c in enumerate(candles) if c.timestamp >= start), len(candles))
    j = next((k for k, c in enumerate(candles) if c.timestamp >= end), len(candles))
    if i >= j:
        raise DataValidationError(f"no hay velas entre {start:%Y-%m-%d} y {end:%Y-%m-%d}")
    return i, j


def cached_signals(closes: Sequence[float], config: tuple[int, int],
                   check_points: Sequence[int]) -> Callable[[Sequence[float]], list[Signal]]:
    """Señales calculadas una vez (causales) y recortadas al prefijo pedido.

    Antes de devolverlas comprueba, en cada punto de corte, que coinciden con
    un cálculo directo sobre el prefijo (prueba de prefijos, A.10 y defecto 4).
    """
    full = donchian_signals(closes, *config)
    for cut in check_points:
        if donchian_signals(closes[:cut], *config) != full[:cut]:
            raise DataValidationError(f"{label(config)}: la prueba de prefijos falla en {cut}")

    def signals(prefix: Sequence[float]) -> list[Signal]:
        if len(prefix) > len(closes) or list(prefix) != list(closes[:len(prefix)]):
            raise ValueError("las señales en caché solo valen para prefijos de la misma historia")
        return full[:len(prefix)]
    return signals


def evaluate(candles: Sequence[Candle], start: int, end: int, signal_function,
             config: BacktestConfig, truncated: frozenset[datetime]) -> tuple[BacktestResult, Summary]:
    result = evaluate_segment(candles, start, end, signal_function, config)
    problems = accounting_problems(result, candles[start:end])
    if problems:
        raise DataValidationError("defecto crítico (contabilidad): " + "; ".join(problems[:3]))
    return result, summarize(result, candles[:end], truncated)


def baseline_daily(daily: Sequence[Candle], start: datetime, end: datetime,
                   config: BacktestConfig) -> tuple[float, float | None, float]:
    """Baseline operativo T019 (código congelado) sobre velas diarias: (retorno, Sharpe, DD)."""
    i, j = bounds(daily, start, end)
    result = evaluate_segment(daily, i, j, baseline_signals, config)
    if accounting_problems(result, daily[i:j]):
        raise DataValidationError("defecto crítico (contabilidad) en el baseline diario")
    series = daily_series(result.timestamps, result.equity)
    _, sharpe = risk(series.returns(config.initial_capital))
    return (result.final_liquidation_value / config.initial_capital - 1, sharpe,
            max_drawdown([config.initial_capital, *result.equity]))


def select(evaluations: Sequence[Evaluation]) -> Selection:
    """Regla única de A.6: mayor mediana del Sharpe (base, 11 trimestres; None = 0);
    desempate por menor mediana de drawdown intradía y después por el orden de CONFIGS."""
    medians = {}
    for config in CONFIGS:
        rows = [e for e in evaluations
                if e.label == label(config) and e.scenario == BASE and e.segment != "desarrollo"]
        if len(rows) != len(QUARTERS):
            raise ValueError(f"{label(config)}: {len(rows)} trimestres, se esperaban {len(QUARTERS)}")
        medians[config] = (statistics.median(e.sharpe or 0.0 for e in rows),
                           statistics.median(e.max_drawdown for e in rows))
    chosen = min(CONFIGS, key=lambda c: (-medians[c][0], medians[c][1], CONFIGS.index(c)))
    return Selection(chosen, medians, medians[chosen][0] > 0)


def run_validation(candles: Sequence[Candle], daily: Sequence[Candle],
                   truncated: frozenset[datetime]) -> tuple[list[Evaluation], Selection,
                                                            dict[str, tuple]]:
    if candles[-1].timestamp >= HOLDOUT_START or daily[-1].timestamp >= HOLDOUT_START:
        raise DataValidationError("hay datos desde 2026-10-01: la validación no puede leerlos")
    closes = [c.close for c in candles]
    segments = [("desarrollo", *bounds(candles, *DEVELOPMENT))]
    segments += [(quarter_name(s), *bounds(candles, s, e)) for s, e in QUARTERS]
    cuts = [end for _, _, end in segments]
    evaluations: list[Evaluation] = []
    for config in CONFIGS:
        signals = cached_signals(closes, config, cuts)
        for scenario in SCENARIOS:
            cost = _config(scenario)
            for name, start, end in segments:
                _, summary = evaluate(candles, start, end, signals, cost, truncated)
                evaluations.append(Evaluation(label(config), name, scenario.name, summary,
                                              summary.net_return, summary.sharpe,
                                              summary.max_drawdown_intraday))
    references: dict[str, tuple] = {}
    for scenario in SCENARIOS:
        cost = _config(scenario)
        for (name, start, end), (q_start, q_end) in zip(segments, [DEVELOPMENT, *QUARTERS]):
            _, hold = evaluate(candles, start, end, _hold_signals, cost, truncated)
            evaluations.append(Evaluation("buy-and-hold", name, scenario.name, hold,
                                          hold.net_return, hold.sharpe, hold.max_drawdown_intraday))
            ret, sharpe, drawdown = baseline_daily(daily, q_start, q_end, cost)
            evaluations.append(Evaluation("baseline T019", name, scenario.name, None,
                                          ret, sharpe, drawdown))
    for name, start, end in segments:
        references[name] = (candles[start].timestamp, candles[end - 1].timestamp, end - start)
    return evaluations, select(evaluations), references


def baseline_signals(closes: Sequence[float]) -> list[Signal]:
    """Baseline operativo T019: trend_filter(window=50) congelado (D022)."""
    return trend_filter_signals(closes, BASELINE_WINDOW)


def _hold_signals(closes: Sequence[float]) -> list[Signal]:
    return buy_and_hold_signals(len(closes))


def _config(scenario: Scenario) -> BacktestConfig:
    return BacktestConfig(CAPITAL, scenario.commission_rate, scenario.slippage_rate)


# --- informe ---------------------------------------------------------------------------


def render_trials(evaluations: Sequence[Evaluation]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["estrategia", "tramo", "escenario", "retorno_neto", "retorno_tras_redondeo",
                     "sharpe_diario", "drawdown", "exposicion", "operaciones", "idas_y_vueltas",
                     "comisiones", "slippage", "tras_hueco", "vela_truncada", "liquidez_dudosa"])
    for e in evaluations:
        s = e.summary
        writer.writerow([e.label, e.segment, e.scenario, _f(e.net_return),
                         _f(s.net_return_after_rounding) if s else "", _f(e.sharpe),
                         _f(e.max_drawdown), _f(s.exposure) if s else "",
                         s.trades if s else "", s.round_trips if s else "",
                         _f(s.total_fees) if s else "", _f(s.total_slippage) if s else "",
                         *(list(s.flag_counts.values()) if s else ["", "", ""])])
    return buffer.getvalue()


def render_report(evaluations: Sequence[Evaluation], selection: Selection,
                  references: dict[str, tuple], protocol_sha: str, manifest_sha: str,
                  daily_manifest_sha: str) -> str:
    def row(label_: str, segment: str, scenario: str = BASE) -> Evaluation:
        return next(e for e in evaluations
                    if e.label == label_ and e.segment == segment and e.scenario == scenario)

    quarters = [quarter_name(s) for s, _ in QUARTERS]
    lines = [
        "# EXP-15M-001 — Informe de validación (walk-forward)",
        "",
        "> Simulación histórica con costes modelados. **No es un resultado real ni una "
        "garantía de rentabilidad futura.** La validación sirve para ELEGIR una configuración "
        "(A.6); el veredicto del experimento solo lo da el holdout prospectivo "
        "2026-11-01 → 2027-01-31, que se abrirá una vez a partir del 2027-02-01.",
        "",
        f"- Protocolo EXPERIMENT_15M.md, SHA-256 {protocol_sha}",
        f"- Manifiesto 15m {manifest_sha}; manifiesto diario {daily_manifest_sha}",
        f"- Capital {_money(CAPITAL)} USDT; escenario principal: base (comisión 0,1 %, "
        "slippage 0,05 % por lado); 4 configuraciones × 11 trimestres × 4 escenarios = "
        f"{len(CONFIGS) * len(QUARTERS) * len(SCENARIOS)} evaluaciones de validación.",
        "",
        "## Selección (regla única de A.6, escenario base)",
        "",
        "| Configuración | Mediana del Sharpe diario | Mediana del drawdown intradía |",
        "|---|---:|---:|",
    ]
    for config in CONFIGS:
        sharpe, drawdown = selection.medians[config]
        mark = " **(elegida)**" if config == selection.config else ""
        lines.append(f"| {label(config)}{mark} | {sharpe:.2f} | {_share(drawdown)} |")
    lines += [
        "",
        f"- Elegida: **{label(selection.config)}**. Es la única que se evaluará en el holdout.",
        f"- C7 (mediana del Sharpe de la elegida > 0): **{'sí' if selection.c7 else 'no'}**. "
        "Es optimista: se mide en los mismos trimestres que la eligieron (condición necesaria, "
        "no prueba).",
        "",
        "## Retorno neto por trimestre (escenario base)",
        "",
        "| Trimestre | " + " | ".join(label(c) for c in CONFIGS)
        + " | Buy-and-hold | Baseline T019 | Efectivo |",
        "|---|" + "---:|" * (len(CONFIGS) + 3),
    ]
    for q in quarters:
        cells = [_pct(row(label(c), q).net_return) for c in CONFIGS]
        cells += [_pct(row("buy-and-hold", q).net_return), _pct(row("baseline T019", q).net_return),
                  "0,00 %"]
        regime = "alcista" if row("buy-and-hold", q).net_return > 0 else "bajista"
        lines.append(f"| {q} ({regime}) | " + " | ".join(cells) + " |")
    lines += ["", "## Sharpe diario por trimestre (escenario base)", "",
              "| Trimestre | " + " | ".join(label(c) for c in CONFIGS)
              + " | Buy-and-hold | Baseline T019 |",
              "|---|" + "---:|" * (len(CONFIGS) + 2)]
    for q in quarters:
        cells = [_num(row(label(c), q).sharpe) for c in CONFIGS]
        cells += [_num(row("buy-and-hold", q).sharpe), _num(row("baseline T019", q).sharpe)]
        lines.append(f"| {q} | " + " | ".join(cells) + " |")
    lines += ["", "## Sensibilidad a costes (mediana del retorno neto trimestral)", "",
              "| Estrategia | " + " | ".join(s.name for s in SCENARIOS) + " |",
              "|---|" + "---:|" * len(SCENARIOS)]
    for name in [label(c) for c in CONFIGS] + ["buy-and-hold", "baseline T019"]:
        cells = [_pct(statistics.median(row(name, q, s.name).net_return for q in quarters))
                 for s in SCENARIOS]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## Actividad y costes (escenario base, suma de los 11 trimestres)", "",
              "| Configuración | Operaciones | Idas y vueltas | Exposición media | Comisiones | "
              "Slippage | Tras hueco | Vela truncada | Liquidez dudosa |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for config in CONFIGS:
        rows = [row(label(config), q).summary for q in quarters]
        lines.append(
            f"| {label(config)} | {sum(s.trades for s in rows)} | "
            f"{sum(s.round_trips for s in rows)} | "
            f"{_share(statistics.fmean(s.exposure for s in rows))} | "
            f"{_money(sum(s.total_fees for s in rows))} | {_money(sum(s.total_slippage for s in rows))} | "
            + " | ".join(str(sum(s.flag_counts[k] for s in rows))
                         for k in rows[0].flag_counts) + " |")
    lines += ["", "## Desarrollo 2020-2023 (información; no entra en la selección)", "",
              "| Estrategia | " + " | ".join(s.name for s in SCENARIOS) + " | Drawdown (base) |",
              "|---|" + "---:|" * (len(SCENARIOS) + 1)]
    for name in [label(c) for c in CONFIGS] + ["buy-and-hold", "baseline T019"]:
        cells = [_pct(row(name, "desarrollo", s.name).net_return) for s in SCENARIOS]
        lines.append(f"| {name} | " + " | ".join(cells)
                     + f" | {_share(row(name, 'desarrollo').max_drawdown)} |")
    lines += ["", "## Tramos", "", "| Tramo | Primera vela | Última vela | Velas |", "|---|---|---|---:|"]
    for name, (first, last, count) in references.items():
        lines.append(f"| {name} | {first:%Y-%m-%d %H:%M} | {last:%Y-%m-%d %H:%M} | {count} |")
    lines += ["", "Lectura: esto es validación de un solo activo y un periodo concreto. Un buen "
              "resultado aquí no demuestra ventaja estadística; el holdout lo juzga con C1-C9.", ""]
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "n/d" if value is None else f"{value * 100:+.2f} %".replace(".", ",")


def _share(value: float) -> str:
    """Porcentaje sin signo (drawdown, exposición)."""
    return f"{value * 100:.2f} %".replace(".", ",")


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _num(value: float | None) -> str:
    return "n/d" if value is None else f"{value:.2f}"


def _f(value: float | None) -> str:
    return "" if value is None else repr(value)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# --- CLI -------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bottrading.exp15m_eval",
                                     description="EXP-15M-001: validación walk-forward (sin red).")
    parser.add_argument("command", choices=("validate", "daily-manifest"))
    parser.add_argument("--data", type=Path, default=Path("data/BTCUSDT-15m"))
    parser.add_argument("--daily", type=Path, default=Path("data/BTCUSDT-1d"))
    parser.add_argument("--out", type=Path, default=Path("reports/exp15m"))
    parser.add_argument("--protocol", type=Path, default=Path("EXPERIMENT_15M.md"))
    return parser


def main(argv: Sequence[str] | None = None, now: datetime | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest, daily_manifest = args.out / "data_manifest.csv", args.out / "daily_manifest.csv"
    try:
        daily_files = sorted(args.daily.glob("*.zip"))
        if not daily_files:
            raise DataValidationError(f"{args.daily}: no contiene archivos .zip")
        if args.command == "daily-manifest":
            args.out.mkdir(parents=True, exist_ok=True)
            with daily_manifest.open("x", encoding="utf-8", newline="") as handle:
                handle.write(render_manifest(build_manifest(daily_files)))
            print(f"Manifiesto diario creado: {daily_manifest} ({len(daily_files)} archivos)")
            return 0
        files = zip_files(args.data)
        for path, listed in ((manifest, files), (daily_manifest, daily_files)):
            problems = check_manifest(path, listed)
            if problems:
                raise DataValidationError(f"{path.name} no coincide: " + "; ".join(problems))
        candles, report = load_15m(files, now)
        daily = load_binance_klines(daily_files)
        evaluations, selection, references = run_validation(
            candles, daily, frozenset(report.truncated))
        text = render_report(evaluations, selection, references, _sha(args.protocol),
                             _sha(manifest), _sha(daily_manifest))
        (args.out / "validation.md").write_text(text, encoding="utf-8", newline="\n")
        (args.out / "validation_trials.csv").write_text(render_trials(evaluations),
                                                        encoding="utf-8", newline="\n")
    except FileExistsError as exc:
        print(f"error: ya existe {exc.filename}; no se sobrescribe", file=sys.stderr)
        return 2
    except (DataValidationError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Elegida: {label(selection.config)}; C7: {'sí' if selection.c7 else 'no'}")
    print(f"Informe: {args.out / 'validation.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
