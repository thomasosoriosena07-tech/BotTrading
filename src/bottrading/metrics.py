"""Métricas de rendimiento y riesgo (ver DECISIONS.md D015).

Si no hay datos suficientes para una métrica, vale None y `notes`
explica por qué: no se publican cifras engañosas.
Resultados simulados; no garantizan rendimientos futuros.
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from bottrading.backtest import BacktestResult, run_backtest
from bottrading.config import BacktestConfig
from bottrading.data import Candle
from bottrading.strategy import Signal, buy_and_hold_signals

YEAR = timedelta(days=365)  # mercado 24/7 (cripto)
MIN_DAYS_FOR_ANNUALIZED_RETURN = 365
MIN_RETURNS_FOR_RISK_METRICS = 30


@dataclass(frozen=True)
class RoundTrip:
    entry_time: datetime
    exit_time: datetime
    cost: float  # nominal + comisión de la compra
    proceeds: float  # nominal − comisión de la venta

    @property
    def pnl(self) -> float:
        return self.proceeds - self.cost


@dataclass(frozen=True)
class Metrics:
    initial_capital: float
    final_equity_mtm: float  # valoración al cierre, sin costes de salida
    final_value_net: float  # liquidación neta de costes de salida
    total_return: float  # sobre final_value_net
    annualized_return: float | None
    max_drawdown: float  # fracción positiva, sobre la curva mark-to-market
    volatility: float | None  # anualizada
    sharpe: float | None  # anualizado
    periods_per_year: float | None
    risk_free_rate: float
    num_trades: int  # ejecuciones (compras + ventas)
    round_trips: list[RoundTrip]
    win_rate: float | None  # solo sobre operaciones cerradas
    open_position: bool
    total_fees: float  # comisiones de operaciones ejecutadas
    total_slippage: float  # slippage de operaciones ejecutadas
    # Costes hipotéticos de cerrar la posición abierta (0 si no hay):
    # final_equity_mtm − final_value_net. No incluidos en total_fees.
    estimated_exit_costs: float
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Comparison:
    strategy: Metrics
    benchmark: Metrics  # buy-and-hold con las mismas reglas y costes

    @property
    def excess_return(self) -> float:
        return self.strategy.total_return - self.benchmark.total_return


def compute_metrics(result: BacktestResult, risk_free_rate: float = 0.0) -> Metrics:
    """Calcula las métricas de un backtest. risk_free_rate es anual."""
    _validate_risk_free_rate(risk_free_rate)
    if not result.equity:
        raise ValueError("no se pueden calcular métricas sin velas")

    notes: list[str] = []
    initial = result.config.initial_capital
    total_return = result.final_liquidation_value / initial - 1
    periods_per_year = _periods_per_year(result.timestamps)
    returns = [b / a - 1 for a, b in zip(result.equity, result.equity[1:])]
    volatility, sharpe = _risk_metrics(returns, periods_per_year, risk_free_rate, notes)
    round_trips = _round_trips(result)

    if not round_trips:
        notes.append("win_rate no disponible: no hay operaciones cerradas")
    if result.final_quantity > 0:
        notes.append("posición abierta al final: total_return usa su valor de liquidación")
    gaps = irregular_gaps(result.timestamps)
    if gaps:
        notes.append(
            f"{gaps} intervalos entre velas superan 1.5 veces la mediana: "
            "hay huecos y las métricas anualizadas son menos representativas"
        )

    return Metrics(
        initial_capital=initial,
        final_equity_mtm=result.equity[-1],
        final_value_net=result.final_liquidation_value,
        total_return=total_return,
        annualized_return=_annualized_return(total_return, result.timestamps, notes),
        max_drawdown=max_drawdown(result.equity),
        volatility=volatility,
        sharpe=sharpe,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
        num_trades=len(result.trades),
        round_trips=round_trips,
        win_rate=(
            sum(trip.pnl > 0 for trip in round_trips) / len(round_trips)
            if round_trips else None
        ),
        open_position=result.final_quantity > 0,
        total_fees=result.total_fees,
        total_slippage=result.total_slippage,
        estimated_exit_costs=result.equity[-1] - result.final_liquidation_value,
        notes=notes,
    )


def irregular_gaps(timestamps: Sequence[datetime], tolerance: float = 1.5) -> int:
    """Cuenta intervalos mayores que `tolerance` veces la mediana."""
    if len(timestamps) < 3:
        return 0
    gaps = [(b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:])]
    limit = statistics.median(gaps) * tolerance
    return sum(gap > limit for gap in gaps)


def compare_with_buy_and_hold(
    candles: Sequence[Candle],
    signals: Sequence[Signal],
    config: BacktestConfig,
    risk_free_rate: float = 0.0,
) -> Comparison:
    strategy = run_backtest(candles, signals, config)
    benchmark = run_backtest(candles, buy_and_hold_signals(len(candles)), config)
    return Comparison(
        strategy=compute_metrics(strategy, risk_free_rate),
        benchmark=compute_metrics(benchmark, risk_free_rate),
    )


def max_drawdown(equity: Sequence[float]) -> float:
    """Mayor caída desde un máximo previo, como fracción (0 si no cae)."""
    peak = -math.inf
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        worst = max(worst, 1 - value / peak)
    return worst


def _periods_per_year(timestamps: Sequence[datetime]) -> float | None:
    """Velas por año a partir de la mediana del intervalo entre velas."""
    if len(timestamps) < 2:
        return None
    gaps = [(b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:])]
    return YEAR.total_seconds() / statistics.median(gaps)


def _annualized_return(
    total_return: float, timestamps: Sequence[datetime], notes: list[str]
) -> float | None:
    span = timestamps[-1] - timestamps[0]
    if span < timedelta(days=MIN_DAYS_FOR_ANNUALIZED_RETURN):
        notes.append(
            f"annualized_return no disponible: periodo de {span.days} días "
            f"(< {MIN_DAYS_FOR_ANNUALIZED_RETURN})"
        )
        return None
    return (1 + total_return) ** (YEAR / span) - 1


def _risk_metrics(
    returns: list[float],
    periods_per_year: float | None,
    risk_free_rate: float,
    notes: list[str],
) -> tuple[float | None, float | None]:
    if len(returns) < MIN_RETURNS_FOR_RISK_METRICS or periods_per_year is None:
        notes.append(
            f"volatility y sharpe no disponibles: {len(returns)} rendimientos "
            f"(< {MIN_RETURNS_FOR_RISK_METRICS})"
        )
        return None, None
    stdev = statistics.stdev(returns)
    volatility = stdev * math.sqrt(periods_per_year)
    if stdev == 0:
        notes.append("sharpe no disponible: volatilidad cero")
        return volatility, None
    rf_per_period = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    excess = statistics.fmean(returns) - rf_per_period
    return volatility, excess / stdev * math.sqrt(periods_per_year)


def _round_trips(result: BacktestResult) -> list[RoundTrip]:
    trips = []
    entry = None
    for trade in result.trades:
        if trade.side is Signal.BUY:
            entry = trade
        elif trade.side is Signal.SELL and entry is not None:
            trips.append(RoundTrip(
                entry_time=entry.execution_time,
                exit_time=trade.execution_time,
                cost=entry.quantity * entry.price + entry.fee,
                proceeds=trade.quantity * trade.price - trade.fee,
            ))
            entry = None
    return trips


def _validate_risk_free_rate(rate: float) -> None:
    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        raise ValueError(f"risk_free_rate debe ser numérico, no {rate!r}")
    if not math.isfinite(rate) or rate <= -1:
        raise ValueError(f"risk_free_rate debe ser finito y > -1, no {rate}")
