"""Señales de cruce de medias móviles simples (ver DECISIONS.md D012).

La señal de la vela i usa solo cierres hasta i (inclusive): se conoce
al cierre de esa vela. Ejecutarla corresponde al motor de backtesting,
como pronto en la apertura de la vela i + 1.
"""

import math
from collections.abc import Sequence
from enum import Enum


class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


def validate_windows(fast: int, slow: int) -> None:
    """Rechaza ventanas inválidas: enteros con 1 <= fast < slow."""
    for name, value in (("fast", fast), ("slow", slow)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} debe ser un entero, no {value!r}")
        if value < 1:
            raise ValueError(f"{name} debe ser >= 1, no {value}")
    if fast >= slow:
        raise ValueError(f"fast ({fast}) debe ser menor que slow ({slow})")


def simple_moving_average(values: Sequence[float], window: int) -> list[float | None]:
    """Media de los últimos `window` valores; None mientras no hay suficientes."""
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError(f"window debe ser un entero >= 1, no {window!r}")
    return [
        math.fsum(values[i + 1 - window : i + 1]) / window if i + 1 >= window else None
        for i in range(len(values))
    ]


def crossover_signals(closes: Sequence[float], fast: int, slow: int) -> list[Signal]:
    """Una señal por vela.

    Se compara la media rápida con la lenta y se recuerda el último lado
    no empatado (arriba/abajo). Un empate no es un cruce por sí mismo:
    BUY: la rápida queda por encima y antes no lo estaba (abajo o empate
    desde el inicio). SELL: simétrico. Tocar la lenta y volver al mismo
    lado no genera señal.
    HOLD: en cualquier otro caso, incluido el calentamiento. La primera
    señal posible está en el índice `slow` (se necesita la vela anterior
    con ambas medias calculadas).
    """
    validate_windows(fast, slow)
    fast_ma = simple_moving_average(closes, fast)
    slow_ma = simple_moving_average(closes, slow)

    signals = [Signal.HOLD] * len(closes)
    if len(closes) < slow:
        return signals
    side = _sign(fast_ma[slow - 1] - slow_ma[slow - 1])
    for i in range(slow, len(closes)):
        current = _sign(fast_ma[i] - slow_ma[i])
        if current > 0 and side <= 0:
            signals[i] = Signal.BUY
        elif current < 0 and side >= 0:
            signals[i] = Signal.SELL
        if current != 0:
            side = current
    return signals


def trend_filter_signals(closes: Sequence[float], window: int) -> list[Signal]:
    """Filtro de tendencia: dentro si el cierre supera su media de `window`.

    Es un cruce del precio (media de 1 vela) con su media, así que hereda
    la semántica de crossover_signals: BUY al cruzar hacia arriba, SELL al
    cruzar hacia abajo, los empates no son cruces.
    """
    return crossover_signals(closes, 1, window)


def donchian_signals(closes: Sequence[float], entry: int, exit: int) -> list[Signal]:
    """Ruptura de canal sobre cierres.

    BUY en i si closes[i] > máximo de los `entry` cierres anteriores
    (evaluable desde i = entry). SELL en i si closes[i] < mínimo de los
    `exit` cierres anteriores (evaluable desde i = exit). Cada condición
    tiene su propio calentamiento; cuando ambas son evaluables no pueden
    darse a la vez. Solo usa cierres hasta i.
    """
    for name, value in (("entry", entry), ("exit", exit)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} debe ser un entero >= 1, no {value!r}")
    signals = [Signal.HOLD] * len(closes)
    for i in range(min(entry, exit), len(closes)):
        if i >= entry and closes[i] > max(closes[i - entry : i]):
            signals[i] = Signal.BUY
        elif i >= exit and closes[i] < min(closes[i - exit : i]):
            signals[i] = Signal.SELL
    return signals


def buy_and_hold_signals(length: int) -> list[Signal]:
    """Referencia: comprar al cierre de la primera vela y no vender.

    Con las reglas del motor, la compra se ejecuta en la apertura de la
    segunda vela, igual que cualquier otra señal.
    """
    if length <= 0:
        return []
    return [Signal.BUY] + [Signal.HOLD] * (length - 1)


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)
