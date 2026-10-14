"""EXP-15M-001: métricas, marcas y criterios C6/C8/C9 (EXPERIMENT_15M.md A.5, A.8, A.9; D031).

Funciones puras sobre un BacktestResult del motor del baseline (que no se
modifica) y la historia de velas 15m usada para calcularlo. Sin red ni E/S.

- Muestreo diario (A.8): el valor del día D es la valoración al cierre de la
  última vela del día D (la de D 23:45 si existe). Un día UTC sin ninguna vela
  arrastra el valor anterior y se marca como "día arrastrado". Los rendimientos
  diarios parten del capital inicial: n días dan n rendimientos.
- Marcas por operación (A.4, A.5, enmienda 1): "tras hueco" (la vela anterior a
  la de ejecución no es la de 15 min antes), "vela truncada" (se ejecuta en la
  apertura de una vela truncada) y "liquidez dudosa" (N > 1 % de V).
- C8 (concentración), C9 (bootstrap de bloques circular), prueba de exclusión,
  cota de redondeo e identidades contables (defecto crítico 3), tal como están
  definidos en A.9.
"""

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from bottrading.backtest import BacktestResult, Trade
from bottrading.data import Candle
from bottrading.metrics import MIN_RETURNS_FOR_RISK_METRICS, max_drawdown
from bottrading.strategy import Signal

INTERVAL = timedelta(minutes=15)
DAYS_PER_YEAR = 365  # como metrics.py:19 (mercado 24/7)
STEP_SIZE_BTC = 0.00001  # A.5: paso de cantidad (INFERIDO; confirmar con exchangeInfo antes del holdout)
LIQUIDITY_FRACTION = 0.01  # A.5, convención aprobada
CONCENTRATION_FRACTION = 0.05  # C8, convención aprobada
MIN_ROUND_TRIPS = 30  # C6, convención aprobada
BOOTSTRAP_RESAMPLES = 10_000  # C9
BOOTSTRAP_SEED = 20261101  # C9
AFTER_GAP, TRUNCATED, LOW_LIQUIDITY = "tras hueco", "vela truncada", "liquidez dudosa"
EQUITY_TOLERANCE = 1e-6  # USDT (defecto crítico 3)
RELATIVE_TOLERANCE = 1e-9  # comisiones y slippage (defecto crítico 3)


@dataclass(frozen=True)
class DailySeries:
    days: tuple[date, ...]
    values: tuple[float, ...]
    carried: tuple[date, ...]  # días UTC sin ninguna vela (valor arrastrado)

    def returns(self, initial: float, skip_carried: bool = False) -> list[float]:
        """Rendimientos diarios desde el capital inicial (n días -> n rendimientos).

        Con skip_carried se quitan los días arrastrados (repetición de C9); el
        movimiento acumulado queda en el siguiente día con datos.
        """
        result, previous = [], initial
        carried = set(self.carried)
        for day, value in zip(self.days, self.values):
            if skip_carried and day in carried:
                continue
            result.append(value / previous - 1)
            previous = value
        return result


@dataclass(frozen=True)
class Trip:
    """Ida y vuelta. exit=None: posición abierta al final, valorada con su liquidación."""

    entry: int  # índice de la compra en result.trades
    exit: int | None
    cost: float  # nominal + comisión de la compra
    proceeds: float  # nominal − comisión de la venta (o liquidación final)

    @property
    def pnl(self) -> float:
        return self.proceeds - self.cost

    @property
    def net_return(self) -> float:
        return self.pnl / self.cost


@dataclass(frozen=True)
class Summary:
    """Métricas de A.8 para una evaluación (un tramo y un escenario de costes)."""

    initial_capital: float
    net_return: float  # con la liquidación final y sus costes
    rounding_bound: float  # USDT, cota acumulada del redondeo (A.5)
    net_return_after_rounding: float  # la que usan C2 y C3
    max_drawdown_intraday: float  # curva 15m completa (C5)
    max_drawdown_daily: float
    volatility: float | None  # anualizada, sobre rendimientos diarios
    sharpe: float | None  # diario anualizado, tasa libre de riesgo 0
    exposure: float  # fracción de velas con posición al cierre
    trades: int
    round_trips: int  # incluida la posición abierta al final
    trades_per_day: float
    total_fees: float
    total_slippage: float
    cost_share_of_gross: float | None  # costes / (PnL neto + costes); None si bruto <= 0
    mean_trip_return: float | None
    worst_trip_return: float | None
    flag_counts: dict[str, int]
    carried_days: int
    days: int


def daily_series(timestamps: Sequence[datetime], equity: Sequence[float]) -> DailySeries:
    """Valor de cada día UTC entre la primera y la última vela (A.8)."""
    if not timestamps or len(timestamps) != len(equity):
        raise ValueError("se necesitan velas y una valoración por vela")
    last_of_day: dict[date, float] = {}
    for moment, value in zip(timestamps, equity):
        last_of_day[moment.date()] = value  # velas ordenadas: queda la última del día
    days, values, carried = [], [], []
    current = timestamps[0].date()
    previous = None
    while current <= timestamps[-1].date():
        if current in last_of_day:
            previous = last_of_day[current]
        else:
            carried.append(current)
        days.append(current)
        values.append(previous)
        current += timedelta(days=1)
    return DailySeries(tuple(days), tuple(values), tuple(carried))


def risk(returns: Sequence[float]) -> tuple[float | None, float | None]:
    """(volatilidad, Sharpe) anualizados con 365 días; None si no se pueden estimar."""
    if len(returns) < MIN_RETURNS_FOR_RISK_METRICS:
        return None, None
    stdev = statistics.stdev(returns)
    volatility = stdev * math.sqrt(DAYS_PER_YEAR)
    if stdev == 0:
        return volatility, None
    return volatility, statistics.fmean(returns) / stdev * math.sqrt(DAYS_PER_YEAR)


def round_trips(result: BacktestResult) -> list[Trip]:
    trips, entry = [], None
    for index, trade in enumerate(result.trades):
        if trade.side is Signal.BUY:
            entry = index
        elif trade.side is Signal.SELL and entry is not None:
            buy = result.trades[entry]
            trips.append(Trip(entry, index, buy.quantity * buy.price + buy.fee,
                              trade.quantity * trade.price - trade.fee))
            entry = None
    if entry is not None and result.final_quantity > 0:
        buy = result.trades[entry]
        trips.append(Trip(entry, None, buy.quantity * buy.price + buy.fee,
                          result.final_liquidation_value - result.final_cash))
    return trips


def trade_flags(result: BacktestResult, history: Sequence[Candle],
                truncated: frozenset[datetime] = frozenset()) -> list[frozenset[str]]:
    """Marcas de cada operación (A.4, A.5 y enmienda 1); `history` = velas usadas.

    La vela p es la existente inmediatamente anterior a la de ejecución.
    """
    position = {candle.timestamp: i for i, candle in enumerate(history)}
    flags = []
    for trade in result.trades:
        k = position.get(trade.execution_time)
        if k is None:
            raise ValueError(f"operación en {trade.execution_time.isoformat()} fuera de la historia")
        marks = set()
        if trade.execution_time in truncated:
            marks.add(TRUNCATED)
        if k == 0:
            marks.update((AFTER_GAP, LOW_LIQUIDITY))  # sin vela anterior conocida
        else:
            previous = history[k - 1]
            if trade.execution_time - previous.timestamp != INTERVAL:
                marks.add(AFTER_GAP)
            reference_volume = previous.volume * previous.close
            if trade.quantity * trade.price > LIQUIDITY_FRACTION * reference_volume:
                marks.add(LOW_LIQUIDITY)
        flags.append(frozenset(marks))
    return flags


def rounding_bound(result: BacktestResult, last_close: float) -> float:
    """Σ paso de cantidad × precio de cada operación (+ la liquidación final), en USDT."""
    bound = math.fsum(STEP_SIZE_BTC * trade.price for trade in result.trades)
    if result.final_quantity > 0:
        bound += STEP_SIZE_BTC * last_close
    return bound


def summarize(result: BacktestResult, history: Sequence[Candle],
              truncated: frozenset[datetime] = frozenset()) -> Summary:
    """Métricas de A.8. `history` contiene al menos las velas del tramo evaluado."""
    initial = result.config.initial_capital
    series = daily_series(result.timestamps, result.equity)
    volatility, sharpe = risk(series.returns(initial))
    trips = round_trips(result)
    flags = trade_flags(result, history, truncated)
    bound = rounding_bound(result, history[-1].close if history else 0.0)
    pnl = result.final_liquidation_value - initial
    costs = result.total_fees + result.total_slippage
    gross = pnl + costs
    days = len(series.days)
    counts = {mark: sum(mark in f for f in flags) for mark in (AFTER_GAP, TRUNCATED, LOW_LIQUIDITY)}
    return Summary(
        initial_capital=initial,
        net_return=pnl / initial,
        rounding_bound=bound,
        net_return_after_rounding=(pnl - bound) / initial,
        max_drawdown_intraday=max_drawdown([initial, *result.equity]),
        max_drawdown_daily=max_drawdown([initial, *series.values]),
        volatility=volatility,
        sharpe=sharpe,
        exposure=_exposure(result),
        trades=len(result.trades),
        round_trips=len(trips),
        trades_per_day=len(result.trades) / days,
        total_fees=result.total_fees,
        total_slippage=result.total_slippage,
        cost_share_of_gross=costs / gross if gross > 0 else None,
        mean_trip_return=statistics.fmean(t.net_return for t in trips) if trips else None,
        worst_trip_return=min((t.net_return for t in trips), default=None),
        flag_counts=counts,
        carried_days=len(series.carried),
        days=days,
    )


def concentration_ok(trips: Sequence[Trip]) -> bool:
    """C8: PnL total sin las k = techo(5 % de N) mejores idas y vueltas (mínimo 1) > 0."""
    if not trips:
        return False
    k = max(1, math.ceil(CONCENTRATION_FRACTION * len(trips)))
    ranked = sorted((trip.pnl for trip in trips), reverse=True)
    return math.fsum(ranked) - math.fsum(ranked[:k]) > 0


def excluded_pnl(trips: Sequence[Trip], flags: Sequence[frozenset[str]]) -> float:
    """PnL de las idas y vueltas con alguna operación marcada (prueba de exclusión, A.9)."""
    return math.fsum(trip.pnl for trip in trips
                     if flags[trip.entry] or (trip.exit is not None and flags[trip.exit]))


def block_length(n: int) -> int:
    """L = techo(n^(1/3)) con aritmética entera (evita errores de coma flotante)."""
    if n < 1:
        raise ValueError("se necesita al menos un valor")
    length = 1
    while length ** 3 < n:
        length += 1
    return length


def bootstrap_lower_bound(values: Sequence[float], resamples: int = BOOTSTRAP_RESAMPLES,
                          seed: int = BOOTSTRAP_SEED) -> float:
    """C9: percentil 2,5 (rango más cercano) de la media, bootstrap de bloques circular.

    Algoritmo exacto de A.9: un único random.Random(seed); para cada remuestreo,
    mientras la lista tenga < n valores se toma s = rng.randrange(n) y se añaden
    values[(s + j) % n] para j = 0..L-1; se recorta a n y se guarda su media.
    Se ordenan las medias y se toma la de índice techo(0,025 × B) − 1.
    """
    n = len(values)
    length = block_length(n)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(values[(start + j) % n] for j in range(length))
        means.append(statistics.fmean(sample[:n]))
    means.sort()
    return means[lower_rank_index(resamples)]


def lower_rank_index(resamples: int) -> int:
    """Índice (base 0) del percentil 2,5 por rango más cercano: techo(0,025 × B) − 1."""
    return (25 * resamples + 999) // 1000 - 1


def accounting_problems(result: BacktestResult, candles: Sequence[Candle]) -> list[str]:
    """Identidades contables por vela (defecto crítico 3 de A.9); vacía = correctas.

    `candles` son las velas del tramo, alineadas con result.timestamps.
    """
    if [c.timestamp for c in candles] != list(result.timestamps):
        return ["las velas no coinciden con las del resultado"]
    config = result.config
    problems = []
    by_time = {trade.execution_time: trade for trade in result.trades}
    if len(by_time) != len(result.trades):
        problems.append("más de una operación en la misma vela")
    cash, quantity = float(config.initial_capital), 0.0
    for i, candle in enumerate(candles):
        trade = by_time.get(candle.timestamp)
        if trade is not None:
            problems += _trade_problems(trade, cash, config.commission_rate, config.slippage_rate)
            cash = trade.cash_after
            quantity = trade.quantity if trade.side is Signal.BUY else 0.0
        if cash < -EQUITY_TOLERANCE or quantity < 0:
            problems.append(f"{candle.timestamp.isoformat()}: efectivo o cantidad negativos")
        if abs(result.equity[i] - (cash + quantity * candle.close)) > EQUITY_TOLERANCE:
            problems.append(f"{candle.timestamp.isoformat()}: capital ≠ efectivo + cantidad × cierre")
    return problems


def _trade_problems(trade: Trade, cash_before: float, commission: float,
                    slippage: float) -> list[str]:
    when = trade.execution_time.isoformat()
    notional = trade.quantity * trade.price
    if trade.side is Signal.BUY:
        expected_price = trade.reference_price * (1 + slippage)
        expected_cash = cash_before - notional - trade.fee
        expected_slippage = trade.quantity * (trade.price - trade.reference_price)
    else:
        expected_price = trade.reference_price * (1 - slippage)
        expected_cash = cash_before + notional - trade.fee
        expected_slippage = trade.quantity * (trade.reference_price - trade.price)
    checks = (("precio con slippage", trade.price, expected_price),
              ("comisión", trade.fee, notional * commission),
              ("coste de slippage", trade.slippage_cost, expected_slippage),
              ("efectivo tras la operación", trade.cash_after, expected_cash))
    return [f"{when}: {name} no coincide con la fórmula" for name, actual, expected in checks
            if not _close(actual, expected)]


def _close(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= RELATIVE_TOLERANCE * max(1.0, abs(expected))


def _exposure(result: BacktestResult) -> float:
    by_time = {trade.execution_time: trade for trade in result.trades}
    holding, inside = False, 0
    for moment in result.timestamps:
        trade = by_time.get(moment)
        if trade is not None:
            holding = trade.side is Signal.BUY
        inside += holding
    return inside / len(result.timestamps)
