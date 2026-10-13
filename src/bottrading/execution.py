"""Capa de ejecución: intención de orden y ejecutor local (D030, fase F1).

Separa QUÉ orden corresponde a una señal (`decide`, función pura) de CÓMO
se ejecuta. `run_local` ejecuta las intenciones con el mismo modelo de
costes del motor (D014), así que reproduce el paper trading de D027
operación por operación; servirá de "orden prevista" frente a lo que
ejecute la cuenta demo en fases posteriores.

Sin red y sin claves. No modifica paper.py ni el diario de paper/.
Simulación educativa: los resultados no representan operaciones reales.
"""

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

# Helpers internos del motor: reutilización provisional para garantizar la
# paridad con D014 (revisión de Codex); antes de una API estable se expondrá
# una interfaz pública común con las mismas pruebas.
from bottrading.backtest import Trade, _buy, _sell, _validate_inputs
from bottrading.config import BacktestConfig
from bottrading.crossasset import CONFIG, FROZEN_CANDIDATE
from bottrading.data import Candle
from bottrading.strategy import Signal

# D030, punto 2: límites fijos; solo cambian con nueva aprobación.
DEMO_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
BUDGET_PER_ASSET = 1000.0  # USDT, presupuesto no reinvertible por activo
MAX_ORDERS_PER_SYMBOL_PER_DAY = 1
MAX_ORDERS_PER_DAY = 3
MAX_EXPOSURE_AT_COST = 3000.0  # USDT
# Formato documentado por Binance para FIX; se adopta también en REST (D030).
CLIENT_ORDER_ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]{1,36}")


class LimitExceeded(ValueError):
    """Las intenciones del día superan un límite de D030: no se envía nada."""


@dataclass(frozen=True)
class Holding:
    """Posición de un activo según el ledger."""

    cash: float
    quantity: float = 0.0
    cost: float = 0.0  # USDT gastados en la posición abierta (exposición a coste)


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: Signal
    signal_time: datetime  # cierre de la vela que generó la señal
    quote_amount: float | None = None  # BUY: USDT a gastar, comisión incluida
    quantity: float | None = None  # SELL: cantidad del activo

    @property
    def client_order_id(self) -> str:
        return client_order_id(self.symbol, self.signal_time, self.side)


def client_order_id(symbol: str, signal_time: datetime, side: Signal) -> str:
    """bt-<SÍMBOLO>-<AAAAMMDD de la señal>-<B|S>: un id por intención (D030)."""
    if side not in (Signal.BUY, Signal.SELL):
        raise ValueError(f"lado sin orden: {side!r}")
    value = f"bt-{symbol}-{signal_time:%Y%m%d}-{'B' if side is Signal.BUY else 'S'}"
    if not CLIENT_ORDER_ID_PATTERN.fullmatch(value):
        raise ValueError(f"clientOrderId fuera de formato: {value!r}")
    return value


def decide(symbol: str, signal: Signal, signal_time: datetime, holding: Holding,
           budget: float | None = None) -> OrderIntent | None:
    """Orden que corresponde a `signal` con la posición `holding`, o None.

    Misma semántica que el motor: BUY solo sin posición, SELL solo con
    posición, HOLD nunca. `budget` None invierte todo el efectivo (paper,
    D027); con presupuesto, min(efectivo, budget) sin reinvertir (D030).
    """
    if signal is Signal.BUY and holding.quantity == 0:
        spend = holding.cash if budget is None else min(holding.cash, budget)
        if spend <= 0:
            return None
        return OrderIntent(symbol, Signal.BUY, signal_time, quote_amount=spend)
    if signal is Signal.SELL and holding.quantity > 0:
        return OrderIntent(symbol, Signal.SELL, signal_time, quantity=holding.quantity)
    return None


def check_limits(intents: Sequence[OrderIntent], holdings: dict[str, Holding],
                 already_today: Sequence[OrderIntent] = ()) -> None:
    """Lanza LimitExceeded si las intenciones nuevas no caben en los límites.

    `holdings` refleja solo ejecuciones confirmadas; `already_today` son las
    órdenes ya registradas en el ledger para el mismo día, en cualquier
    estado. Los conteos son acumulados (revisión de Codex). Al superarse un
    límite no se reduce ninguna orden: no se envía nada ese día (D030).

    Conservador: una venta del mismo día NO libera exposición (no consta
    confirmada al decidir). Con 1000 por activo y 3 activos no hace falta.
    """
    every = [*already_today, *intents]
    days = {intent.signal_time.date() for intent in every}
    if len(days) > 1:
        raise LimitExceeded(f"intenciones de varios días: {sorted(days)}")
    unknown = sorted({i.symbol for i in every if i.symbol not in DEMO_SYMBOLS})
    if unknown:
        raise LimitExceeded(f"símbolos no permitidos: {unknown}")
    per_symbol = Counter(intent.symbol for intent in every)
    repeated = sorted(s for s, n in per_symbol.items() if n > MAX_ORDERS_PER_SYMBOL_PER_DAY)
    if repeated:
        raise LimitExceeded(f"más de {MAX_ORDERS_PER_SYMBOL_PER_DAY} orden por símbolo: {repeated}")
    if len(every) > MAX_ORDERS_PER_DAY:
        raise LimitExceeded(f"{len(every)} órdenes; máximo {MAX_ORDERS_PER_DAY} por día")
    for intent in intents:
        _check_against_holding(intent, holdings.get(intent.symbol, Holding(0.0)))
    exposure = sum(h.cost for h in holdings.values())
    exposure += sum(i.quote_amount for i in every if i.side is Signal.BUY
                    and holdings.get(i.symbol, Holding(0.0)).quantity == 0)
    if exposure > MAX_EXPOSURE_AT_COST:
        raise LimitExceeded(f"exposición a coste {exposure} USDT; máximo {MAX_EXPOSURE_AT_COST}")


def _check_against_holding(intent: OrderIntent, holding: Holding) -> None:
    """La intención debe ser coherente con la posición confirmada."""
    if intent.side is Signal.BUY:
        if intent.quote_amount is None or not 0 < intent.quote_amount <= BUDGET_PER_ASSET:
            raise LimitExceeded(f"{intent.symbol}: compra de {intent.quote_amount} USDT; "
                                f"máximo {BUDGET_PER_ASSET}")
        if holding.quantity != 0:
            raise LimitExceeded(f"{intent.symbol}: compra con posición abierta")
        if intent.quote_amount > holding.cash:
            raise LimitExceeded(f"{intent.symbol}: compra mayor que el efectivo del ledger")
    elif intent.side is Signal.SELL:
        if holding.quantity <= 0 or intent.quantity != holding.quantity:
            raise LimitExceeded(f"{intent.symbol}: venta de {intent.quantity} con posición "
                                f"{holding.quantity}")
    else:
        raise LimitExceeded(f"{intent.symbol}: intención sin lado de orden")


def fill_locally(config: BacktestConfig, intent: OrderIntent, holding: Holding,
                 candle: Candle) -> tuple[Trade, Holding]:
    """Ejecuta la intención a la apertura de `candle` con slippage y comisión (D014)."""
    if intent.side is Signal.BUY:
        trade = _buy(config, intent.quote_amount, intent.signal_time, candle)
        trade = replace(trade, cash_after=holding.cash - intent.quote_amount)
        return trade, Holding(trade.cash_after, trade.quantity, intent.quote_amount)
    trade = _sell(config, holding.cash, intent.quantity, intent.signal_time, candle)
    return trade, Holding(trade.cash_after)


@dataclass(frozen=True)
class LocalRun:
    symbol: str
    trades: list[Trade]
    holding: Holding  # posición tras la última vela
    pending: OrderIntent | None  # intención de la última señal, aún sin ejecutar


def run_local(
    symbol: str,
    candles: Sequence[Candle],
    start: int,
    end: int | None = None,
    config: BacktestConfig = CONFIG,
    budget: float | None = None,
    signal_function: Callable[[Sequence[float]], list[Signal]] = FROZEN_CANDIDATE.signals,
) -> LocalRun:
    """Simula [start, end) vela a vela mediante intenciones.

    Como evaluate_segment (D020): señales causales con todas las velas
    hasta `end` y herencia de la posición si la última señal anterior a
    `start` es BUY (se compra a la apertura de `start`). Sin `budget`
    (paper, D027) parte de config.initial_capital y reinvierte; con
    `budget` (D030) parte de ese presupuesto y no reinvierte ganancias.
    Velas y señales se validan como en run_backtest.
    """
    end = len(candles) if end is None else end
    if not 0 <= start < end <= len(candles):
        raise ValueError(f"segmento inválido [{start}, {end}) con {len(candles)} velas")
    if config.max_position_fraction != 1.0:
        raise ValueError("run_local requiere max_position_fraction = 1 (el tamaño lo fija budget)")
    history = candles[:end]
    signals = signal_function([candle.close for candle in history])
    _validate_inputs(history, signals, config)

    holding = Holding(float(config.initial_capital if budget is None else budget))
    pending = None
    for index in range(start - 1, -1, -1):
        if signals[index] is not Signal.HOLD:
            pending = decide(symbol, signals[index], history[index].timestamp, holding, budget)
            break

    trades = []
    for index in range(start, end):
        candle = history[index]
        if pending is not None:
            trade, holding = fill_locally(config, pending, holding, candle)
            trades.append(trade)
        pending = decide(symbol, signals[index], candle.timestamp, holding, budget)
    return LocalRun(symbol, trades, holding, pending)
