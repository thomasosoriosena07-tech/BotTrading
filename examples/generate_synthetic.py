"""Genera examples/synthetic_daily.csv: datos OHLCV SINTÉTICOS.

No son datos de mercado reales. Paseo aleatorio geométrico con semilla
fija, para que el ejemplo sea reproducible y no requiera descargas.

Uso: python examples/generate_synthetic.py
"""

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 42
CANDLES = 800  # ~2,2 años de velas diarias
START = datetime(2022, 1, 1, tzinfo=timezone.utc)
START_PRICE = 100.0
DRIFT = 0.0003  # media diaria del log-rendimiento
VOLATILITY = 0.02  # desviación típica diaria del log-rendimiento
OUTPUT = Path(__file__).with_name("synthetic_daily.csv")


def generate(seed: int = SEED, candles: int = CANDLES) -> list[list[str]]:
    rng = random.Random(seed)
    rows = []
    previous_close = START_PRICE
    for i in range(candles):
        open_ = previous_close
        close = open_ * math.exp(rng.gauss(DRIFT, VOLATILITY))
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.005)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.005)))
        volume = rng.uniform(1_000, 5_000)
        open_, high, low, close = (round(v, 2) for v in (open_, high, low, close))
        # El redondeo no debe romper high >= max(open, close) >= ... >= low.
        high = max(high, open_, close)
        low = min(low, open_, close)
        timestamp = (START + timedelta(days=i)).isoformat().replace("+00:00", "Z")
        rows.append([timestamp, f"{open_:.2f}", f"{high:.2f}", f"{low:.2f}",
                     f"{close:.2f}", f"{volume:.2f}"])
        previous_close = close
    return rows


def main() -> None:
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        writer.writerows(generate())
    print(f"escrito {OUTPUT}")


if __name__ == "__main__":
    main()
