"""Particiones temporales: walk-forward para elegir y holdout final (D020).

    |<------------- selección ------------->|<--- holdout final --->|
    | ajuste (crece) | val 1 | val 2 | ... | val N |                       |

- El holdout final es el último `holdout_fraction` de las velas y no se
  usa hasta que estrategias, rejilla y criterio estén fijados (T017).
- Las N ventanas de validación son consecutivas y terminan justo antes
  del holdout. El ajuste de cada ventana es todo lo anterior a ella.
- Las funciones de selección solo reciben velas anteriores al holdout.
"""

import bisect
import calendar
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from bottrading.backtest import BacktestResult, run_backtest
from bottrading.config import BacktestConfig
from bottrading.data import Candle
from bottrading.strategy import Signal

MIN_HOLDOUT_FOR_ANNUALIZED = timedelta(days=365)

SignalFunction = Callable[[Sequence[float]], list[Signal]]


class InsufficientDataError(ValueError):
    """No hay datos suficientes para el esquema de particiones pedido."""


@dataclass(frozen=True)
class Scheme:
    initial_train_months: int
    validation_months: int
    windows: int
    holdout_fraction: float = 0.2


# Diseño inicial propuesto por Codex en la revisión del plan de la fase 2.
DAILY = Scheme(initial_train_months=24, validation_months=6, windows=5)
HOURLY = Scheme(initial_train_months=6, validation_months=1, windows=5)


@dataclass(frozen=True)
class Window:
    """Rangos semiabiertos [inicio, fin) de índices de velas."""

    number: int
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int


@dataclass(frozen=True)
class SplitPlan:
    scheme: Scheme
    windows: list[Window]
    holdout_start: int
    holdout_end: int
    holdout_annualizable: bool
    notes: list[str] = field(default_factory=list)


def plan_splits(timestamps: Sequence[datetime], scheme: Scheme) -> SplitPlan:
    """Calcula las particiones a partir de las fechas (no de los precios)."""
    _validate_scheme(scheme)
    for previous, current in zip(timestamps, timestamps[1:]):
        if current <= previous:
            raise ValueError(f"fechas no ordenadas estrictamente: {current.isoformat()}")
    count = len(timestamps)
    holdout_size = round(count * scheme.holdout_fraction)
    if holdout_size < 2 or holdout_size >= count:
        raise InsufficientDataError(f"{count} velas no permiten un holdout del "
                                    f"{scheme.holdout_fraction:.0%}")
    holdout_start = count - holdout_size

    boundaries = [
        add_months(timestamps[holdout_start], -scheme.validation_months * k)
        for k in range(scheme.windows, -1, -1)
    ]
    starts = [bisect.bisect_left(timestamps, b, 0, holdout_start) for b in boundaries[:-1]]
    ends = starts[1:] + [holdout_start]
    first_validation = boundaries[0]
    required_start = add_months(first_validation, -scheme.initial_train_months)
    if timestamps[0] > required_start:
        raise InsufficientDataError(
            f"el ajuste inicial empieza en {timestamps[0].date()} y necesita datos "
            f"desde {required_start.date()} ({scheme.initial_train_months} meses antes "
            f"de la primera validación, {first_validation.date()})"
        )
    windows = []
    for number, (start, end) in enumerate(zip(starts, ends), start=1):
        if end - start < 2:
            raise InsufficientDataError(f"la ventana {number} tiene {end - start} velas")
        windows.append(Window(number, 0, start, start, end))

    span = timestamps[-1] - timestamps[holdout_start]
    annualizable = span >= MIN_HOLDOUT_FOR_ANNUALIZED
    notes = []
    if not annualizable:
        notes.append(f"holdout de {span.days} días (< 365): muestra insuficiente "
                     "para publicar métricas anualizadas del holdout")
    return SplitPlan(scheme, windows, holdout_start, count, annualizable, notes)


def evaluate_segment(
    candles: Sequence[Candle],
    start: int,
    end: int,
    signal_function: SignalFunction,
    config: BacktestConfig,
    inherit_position: bool = True,
) -> BacktestResult:
    """Simula solo en [start, end).

    Las señales se calculan con todas las velas hasta `end` (calentamiento
    con datos anteriores; las señales son causales) y luego se recortan.
    Con `inherit_position` (por defecto, D020) el tramo hereda la posición
    que la estrategia tendría al llegar a `start`: si su última señal
    anterior es BUY, compra a la apertura de `start` pagando costes. Así
    estrategia y buy-and-hold empiezan en igualdad de condiciones. Sin
    herencia, el tramo empieza sin posición ni órdenes previas.
    """
    if not 0 <= start < end <= len(candles):
        raise ValueError(f"segmento inválido [{start}, {end}) con {len(candles)} velas")
    history = candles[:end]
    signals = signal_function([candle.close for candle in history])
    if len(signals) != len(history):
        raise ValueError("la función de señales debe devolver una señal por vela")
    initial, initial_time = Signal.HOLD, None
    if inherit_position:
        last = _last_action(signals[:start])
        if last is not None and signals[last] is Signal.BUY:
            initial, initial_time = Signal.BUY, history[last].timestamp
    return run_backtest(history[start:], signals[start:], config,
                        initial_signal=initial, initial_signal_time=initial_time)


def _last_action(signals: Sequence[Signal]) -> int | None:
    """Índice de la última señal BUY o SELL, o None."""
    for index in range(len(signals) - 1, -1, -1):
        if signals[index] is not Signal.HOLD:
            return index
    return None


def add_months(moment: datetime, months: int) -> datetime:
    """Suma meses de calendario; el día se ajusta al último del mes si hace falta."""
    total = moment.year * 12 + (moment.month - 1) + months
    year, month = divmod(total, 12)
    day = min(moment.day, calendar.monthrange(year, month + 1)[1])
    return moment.replace(year=year, month=month + 1, day=day)


def _validate_scheme(scheme: Scheme) -> None:
    for name in ("initial_train_months", "validation_months", "windows"):
        value = getattr(scheme, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} debe ser un entero >= 1, no {value!r}")
    fraction = scheme.holdout_fraction
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) \
            or not 0 < fraction <= 0.5:
        raise ValueError(f"holdout_fraction debe estar en (0, 0.5], no {fraction!r}")
