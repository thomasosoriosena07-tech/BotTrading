"""Motor de backtesting spot, solo largo (ver DECISIONS.md D012-D014).

Por cada vela i, en este orden:
1. Se ejecuta la orden pendiente de la señal de i - 1 a la apertura de i,
   con slippage adverso y comisión.
2. Se valora la cartera al cierre de i (curva de capital).
3. La señal de i queda pendiente para la apertura de i + 1.

Simulación educativa: los resultados no representan operaciones reales.
"""

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from bottrading.config import BacktestConfig
from bottrading.data import Candle, DataValidationError, validate_candle
from bottrading.strategy import Signal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Trade:
    side: Signal
    signal_time: datetime
    execution_time: datetime
    reference_price: float  # apertura de la vela de ejecución
    price: float  # precio efectivo tras slippage
    quantity: float
    fee: float
    slippage_cost: float
    cash_after: float


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    trades: list[Trade]
    timestamps: list[datetime]
    equity: list[float]  # mark-to-market al cierre, sin costes de salida
    final_cash: float
    final_quantity: float
    # Efectivo final si la posición abierta se vendiera al último cierre
    # con slippage y comisión. Igual a final_cash si no hay posición.
    final_liquidation_value: float

    @property
    def total_fees(self) -> float:
        return math.fsum(trade.fee for trade in self.trades)

    @property
    def total_slippage(self) -> float:
        return math.fsum(trade.slippage_cost for trade in self.trades)


def run_backtest(
    candles: Sequence[Candle], signals: Sequence[Signal], config: BacktestConfig
) -> BacktestResult:
    """Simula las señales sobre las velas con costes y límite de posición."""
    _validate_inputs(candles, signals, config)

    cash = float(config.initial_capital)
    quantity = 0.0
    trades: list[Trade] = []
    equity: list[float] = []
    pending: Signal = Signal.HOLD

    for i, candle in enumerate(candles):
        if pending is Signal.BUY and quantity == 0:
            trade = _buy(config, cash, candles[i - 1], candle)
            cash, quantity = trade.cash_after, trade.quantity
            trades.append(trade)
        elif pending is Signal.SELL and quantity > 0:
            trade = _sell(config, cash, quantity, candles[i - 1], candle)
            cash, quantity = trade.cash_after, 0.0
            trades.append(trade)
        elif pending is not Signal.HOLD:
            logger.debug("%s ignorada en %s: sin efecto sobre la posición",
                         pending.value, candle.timestamp.isoformat())

        # Valoración al cierre sin descontar costes de una venta futura.
        equity.append(cash + quantity * candle.close)
        pending = signals[i]

    if pending is not Signal.HOLD:
        logger.info("señal %s en la última vela: no se ejecuta", pending.value)

    return BacktestResult(
        config=config,
        trades=trades,
        timestamps=[candle.timestamp for candle in candles],
        equity=equity,
        final_cash=cash,
        final_quantity=quantity,
        final_liquidation_value=_liquidation_value(config, cash, quantity, candles),
    )


def _liquidation_value(config: BacktestConfig, cash: float, quantity: float,
                       candles: Sequence[Candle]) -> float:
    if quantity == 0:
        return cash
    price = candles[-1].close * (1 - config.slippage_rate)
    return cash + quantity * price * (1 - config.commission_rate)


def _buy(config: BacktestConfig, cash: float, signal_candle: Candle,
         candle: Candle) -> Trade:
    """Invierte `max_position_fraction` del efectivo, comisión incluida.

    budget = nominal + comisión, con comisión = nominal × commission_rate,
    así que el coste total nunca supera el efectivo disponible.
    """
    price = candle.open * (1 + config.slippage_rate)
    budget = cash * config.max_position_fraction
    notional = budget / (1 + config.commission_rate)
    quantity = notional / price
    return Trade(
        side=Signal.BUY,
        signal_time=signal_candle.timestamp,
        execution_time=candle.timestamp,
        reference_price=candle.open,
        price=price,
        quantity=quantity,
        fee=budget - notional,
        slippage_cost=quantity * (price - candle.open),
        cash_after=cash - budget,
    )


def _sell(config: BacktestConfig, cash: float, quantity: float,
          signal_candle: Candle, candle: Candle) -> Trade:
    price = candle.open * (1 - config.slippage_rate)
    notional = quantity * price
    fee = notional * config.commission_rate
    return Trade(
        side=Signal.SELL,
        signal_time=signal_candle.timestamp,
        execution_time=candle.timestamp,
        reference_price=candle.open,
        price=price,
        quantity=quantity,
        fee=fee,
        slippage_cost=quantity * (candle.open - price),
        cash_after=cash + notional - fee,
    )


def _validate_inputs(
    candles: Sequence[Candle], signals: Sequence[Signal], config: BacktestConfig
) -> None:
    if not isinstance(config, BacktestConfig):
        raise ValueError(f"config debe ser BacktestConfig, no {type(config).__name__}")
    if len(candles) != len(signals):
        raise ValueError(
            f"hay {len(candles)} velas y {len(signals)} señales; deben coincidir"
        )
    # La API pública no confía en que las velas vengan del cargador.
    for candle in candles:
        prices = (candle.open, candle.high, candle.low, candle.close)
        if not all(math.isfinite(price) and price > 0 for price in prices):
            raise ValueError(
                f"vela con precios no positivos o no finitos: {candle.timestamp.isoformat()}"
            )
        if not math.isfinite(candle.volume):
            raise ValueError(f"vela con volumen no finito: {candle.timestamp.isoformat()}")
        try:
            validate_candle(candle)
        except DataValidationError as exc:
            raise ValueError(f"vela inválida en {candle.timestamp.isoformat()}: {exc}") from exc
    for previous, current in zip(candles, candles[1:]):
        if current.timestamp <= previous.timestamp:
            raise ValueError(
                f"velas no ordenadas estrictamente: {current.timestamp.isoformat()}"
            )
    unknown = {type(signal).__name__ for signal in signals if not isinstance(signal, Signal)}
    if unknown:
        raise ValueError(f"señales con tipo inválido: {', '.join(sorted(unknown))}")
