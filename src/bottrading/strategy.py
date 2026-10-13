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


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)
