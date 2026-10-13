"""Motor de backtesting spot, solo largo (ver DECISIONS.md D012 y D013).

Por cada vela i, en este orden:
1. Se ejecuta la orden pendiente de la señal de i - 1 a la apertura de i.
2. Se valora la cartera al cierre de i (curva de capital).
3. La señal de i queda pendiente para la apertura de i + 1.

Simulación educativa: los resultados no representan operaciones reales.
Costes y límites de posición: pendientes de T007.
"""

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from bottrading.data import Candle
from bottrading.strategy import Signal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Trade:
    side: Signal
    signal_time: datetime
    execution_time: datetime
    price: float
    quantity: float
    cash_after: float


@dataclass(frozen=True)
class BacktestResult:
    initial_capital: float
    trades: list[Trade]
    timestamps: list[datetime]
    equity: list[float]
    final_cash: float
    final_quantity: float


def run_backtest(
    candles: Sequence[Candle], signals: Sequence[Signal], initial_capital: float
) -> BacktestResult:
    """Simula las señales sobre las velas con todo el capital disponible."""
    _validate_inputs(candles, signals, initial_capital)

    cash = float(initial_capital)
    quantity = 0.0
    trades: list[Trade] = []
    equity: list[float] = []
    pending: Signal = Signal.HOLD

    for i, candle in enumerate(candles):
        if pending is Signal.BUY and quantity == 0:
            quantity = cash / candle.open
            cash = 0.0
            trades.append(_trade(pending, candles[i - 1], candle, quantity, cash))
        elif pending is Signal.SELL and quantity > 0:
            cash = quantity * candle.open
            trades.append(_trade(pending, candles[i - 1], candle, quantity, cash))
            quantity = 0.0
        elif pending is not Signal.HOLD:
            logger.debug("%s ignorada en %s: sin efecto sobre la posición",
                         pending.value, candle.timestamp.isoformat())

        equity.append(cash + quantity * candle.close)
        pending = signals[i]

    if pending is not Signal.HOLD:
        logger.info("señal %s en la última vela: no se ejecuta", pending.value)

    return BacktestResult(
        initial_capital=float(initial_capital),
        trades=trades,
        timestamps=[candle.timestamp for candle in candles],
        equity=equity,
        final_cash=cash,
        final_quantity=quantity,
    )


def _trade(side: Signal, signal_candle: Candle, candle: Candle,
           quantity: float, cash_after: float) -> Trade:
    return Trade(
        side=side,
        signal_time=signal_candle.timestamp,
        execution_time=candle.timestamp,
        price=candle.open,
        quantity=quantity,
        cash_after=cash_after,
    )


def _validate_inputs(
    candles: Sequence[Candle], signals: Sequence[Signal], initial_capital: float
) -> None:
    if len(candles) != len(signals):
        raise ValueError(
            f"hay {len(candles)} velas y {len(signals)} señales; deben coincidir"
        )
    if isinstance(initial_capital, bool) or not isinstance(initial_capital, (int, float)):
        raise ValueError(f"initial_capital debe ser numérico, no {initial_capital!r}")
    if not math.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError(f"initial_capital debe ser positivo y finito, no {initial_capital}")
    for candle in candles:
        prices = (candle.open, candle.high, candle.low, candle.close)
        if not all(math.isfinite(price) and price > 0 for price in prices):
            raise ValueError(
                f"vela con precios no positivos o no finitos: {candle.timestamp.isoformat()}"
            )
    for previous, current in zip(candles, candles[1:]):
        if current.timestamp <= previous.timestamp:
            raise ValueError(
                f"velas no ordenadas estrictamente: {current.timestamp.isoformat()}"
            )
    unknown = {type(signal).__name__ for signal in signals if not isinstance(signal, Signal)}
    if unknown:
        raise ValueError(f"señales con tipo inválido: {', '.join(sorted(unknown))}")
