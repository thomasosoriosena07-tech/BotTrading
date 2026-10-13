"""Configuración del backtest (ver DECISIONS.md D014).

Una configuración inválida se rechaza al crearla, nunca se corrige.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float
    commission_rate: float = 0.001  # 0,1 % por operación, sobre el nominal
    slippage_rate: float = 0.0005  # 0,05 %, siempre adverso
    max_position_fraction: float = 1.0  # fracción del efectivo por compra

    def __post_init__(self) -> None:
        _require_number("initial_capital", self.initial_capital)
        if self.initial_capital <= 0:
            raise ValueError(f"initial_capital debe ser > 0, no {self.initial_capital}")
        for name in ("commission_rate", "slippage_rate"):
            value = getattr(self, name)
            _require_number(name, value)
            if not 0 <= value < 1:
                raise ValueError(f"{name} debe estar en [0, 1), no {value}")
        _require_number("max_position_fraction", self.max_position_fraction)
        if not 0 < self.max_position_fraction <= 1:
            raise ValueError(
                f"max_position_fraction debe estar en (0, 1], no {self.max_position_fraction}"
            )


def _require_number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} debe ser numérico, no {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{name} debe ser finito, no {value}")
