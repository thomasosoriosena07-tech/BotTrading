"""Informe de ejecución de la cuenta demo (D030, F5). Sin red.

Compara cada orden ejecutada en Binance Demo con lo que asume el modelo de
paper (D014): ejecución a la APERTURA del día con 0,05 % de deslizamiento
adverso y 0,1 % de comisión. Mide aparte, nunca como un único "resultado":

- precio medio real frente a la apertura y frente al precio modelado (pb);
- comisión real en % (si se cobra en BNB se indica sin convertir);
- retraso desde las 00:00 UTC del día de ejecución;
- rechazos y órdenes sin resolver;
- diario de ejecuciones de `run` y racha de días seguidos sin incidencias
  (criterio de D030: 30 días sin discrepancias ni duplicados).

El informe es PRIVADO (carpeta de estado demo): no se publica en GitHub.
Valida la ejecución, no la rentabilidad de la estrategia.
"""

import csv
import io
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from bottrading.crossasset import CONFIG
from bottrading.data import Candle
from bottrading.demo_ledger import OrderRecord

QUOTE_ASSET = "USDT"
RUN_COLUMNS = ["date", "at", "outcome", "orders", "detail"]


@dataclass(frozen=True)
class FillMetrics:
    client_order_id: str
    symbol: str
    side: str
    signal_day: date
    executed_at: datetime | None
    quantity: Decimal
    quote: Decimal
    average_price: Decimal
    open_price: Decimal | None  # apertura del día de ejecución (None: vela pendiente)
    fee_rate: Decimal | None  # comisión / nominal (None: cobrada en otro activo)
    fee_asset: str
    fee_amount: Decimal = Decimal(0)  # importe cobrado en fee_asset (revisión de Codex)

    @property
    def modeled_price(self) -> Decimal | None:
        if self.open_price is None:
            return None
        slip = Decimal(repr(CONFIG.slippage_rate))
        return self.open_price * (1 + slip if self.side == "BUY" else 1 - slip)

    @property
    def vs_open_bps(self) -> Decimal | None:
        """Coste frente a la apertura en puntos básicos (positivo = peor)."""
        return _adverse_bps(self.side, self.average_price, self.open_price)

    @property
    def vs_model_bps(self) -> Decimal | None:
        """Coste frente al precio modelado (apertura ± 0,05 %); positivo = peor que el modelo."""
        return _adverse_bps(self.side, self.average_price, self.modeled_price)

    @property
    def delay_hours(self) -> Decimal | None:
        if self.executed_at is None:
            return None
        midnight = datetime.combine(self.executed_at.date(), datetime.min.time(), timezone.utc)
        return Decimal((self.executed_at - midnight).total_seconds()) / 3600


def _adverse_bps(side: str, price: Decimal, reference: Decimal | None) -> Decimal | None:
    if reference is None or reference == 0:
        return None
    sign = 1 if side == "BUY" else -1
    return sign * (price - reference) / reference * 10_000


def fill_metrics(record: OrderRecord, order: Mapping, trades: Sequence[Mapping],
                 opens: Mapping[date, Decimal], base_asset: str) -> FillMetrics:
    """Métricas de una orden ejecutada a partir de sus fills reales."""
    quantity = sum((Decimal(t["qty"]) for t in trades), Decimal(0))
    quote = sum((Decimal(t["quoteQty"]) for t in trades), Decimal(0))
    average = quote / quantity if quantity else Decimal(0)
    times = [t["time"] for t in trades if isinstance(t.get("time"), int)]
    executed_at = (datetime.fromtimestamp(min(times) / 1000, timezone.utc) if times else None)
    assets = {t.get("commissionAsset") for t in trades}
    fee_asset = assets.pop() if len(assets) == 1 else "varios"
    fee = sum((Decimal(t["commission"]) for t in trades), Decimal(0))
    fee_rate = None
    if quote and fee_asset == QUOTE_ASSET:
        fee_rate = fee / quote
    elif quote and fee_asset == base_asset:
        fee_rate = fee * average / quote
    day = executed_at.date() if executed_at else None
    return FillMetrics(record.intent.client_order_id, record.intent.symbol,
                       order.get("side", record.intent.side.value.upper()),
                       record.intent.signal_time.date(), executed_at, quantity, quote,
                       average, opens.get(day) if day else None, fee_rate, fee_asset or "?",
                       fee)


def collect_fills(records: Mapping[str, OrderRecord], orders: Mapping[str, Sequence[Mapping]],
                  trades: Mapping[str, Sequence[Mapping]],
                  candles: Mapping[str, Sequence[Candle]],
                  base_assets: Mapping[str, str]) -> list[FillMetrics]:
    """Una entrada por orden del bot con ejecución (> 0) en el historial reconciliado."""
    fills = []
    for symbol, symbol_orders in orders.items():
        opens = {c.timestamp.date(): Decimal(repr(c.open)) for c in candles.get(symbol, ())}
        for order in symbol_orders:
            record = records.get(order.get("clientOrderId"))
            own = [t for t in trades.get(symbol, ()) if t.get("orderId") == order.get("orderId")]
            if record is None or not own or Decimal(order.get("executedQty", "0")) == 0:
                continue
            fills.append(fill_metrics(record, order, own, opens, base_assets[symbol]))
    return sorted(fills, key=lambda f: (f.executed_at or datetime.min.replace(tzinfo=timezone.utc),
                                        f.client_order_id))


# --- diario de ejecuciones de run -----------------------------------------------------


@dataclass(frozen=True)
class RunEntry:
    day: date
    at: str
    outcome: str  # "ok", "incidencia" (rechazo o sin resolver) o "detenido"
    orders: int | None  # envíos reales; None = desconocido (registro ilegible)
    detail: str


def append_run(path: Path, day: date, at: datetime, outcome: str, orders: int | None,
               detail: str) -> None:
    """Añade una línea al diario privado de ejecuciones (solo de añadir)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if new:
        writer.writerow(RUN_COLUMNS)
    writer.writerow([day.isoformat(), at.isoformat(timespec="seconds"), outcome,
                     "" if orders is None else orders,
                     detail.replace("\n", " ")[:300]])
    with open(path, "a", encoding="utf-8", newline="") as handle:
        handle.write(buffer.getvalue())
        handle.flush()
        os.fsync(handle.fileno())


def read_runs(path: Path) -> list[RunEntry]:
    if not path.exists():
        return []
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    if not rows or rows[0] != RUN_COLUMNS:
        raise ValueError(f"{path.name}: cabecera inesperada")
    return [RunEntry(date.fromisoformat(r[0]), r[1], r[2], int(r[3]) if r[3] else None, r[4])
            for r in rows[1:]]


def clean_streak(runs: Sequence[RunEntry], today: date) -> int:
    """Días seguidos hasta hoy (o ayer, si hoy aún no hay ejecución) en los que
    hubo al menos una ejecución y ninguna terminó detenida."""
    by_day: dict[date, list[str]] = {}
    for run in runs:
        by_day.setdefault(run.day, []).append(run.outcome)
    day = today if today in by_day else today - timedelta(days=1)
    streak = 0
    while day in by_day and all(outcome == "ok" for outcome in by_day[day]):
        streak += 1
        day -= timedelta(days=1)
    return streak


# --- informe --------------------------------------------------------------------------


def _fmt(value: Decimal | None, digits: int = 2, suffix: str = "") -> str:
    return "n/d" if value is None else f"{value:.{digits}f}{suffix}"


def render_report(fills: Sequence[FillMetrics], records: Mapping[str, OrderRecord],
                  runs: Sequence[RunEntry], today: date) -> str:
    rejected = [r for r in records.values() if r.status == "REJECTED"]
    unresolved = [r for r in records.values() if not r.final]
    streak = clean_streak(runs, today)
    stops = [r for r in runs if r.outcome != "ok"]
    model_fee = Decimal(repr(CONFIG.commission_rate)) * 100
    lines = [
        f"# Informe de ejecución demo ({today.isoformat()})",
        "",
        "Cuenta Binance Spot DEMO (dinero ficticio). Mide la EJECUCIÓN frente al",
        "modelo de paper (D014: apertura del día, 0,05 % de deslizamiento, 0,1 % de",
        "comisión). No mide la rentabilidad de la estrategia (eso es T019).",
        "",
        "## Resumen",
        f"- Órdenes ejecutadas: {len(fills)}; rechazadas: {len(rejected)}; "
        f"sin resolver: {len(unresolved)}",
        f"- Días seguidos sin incidencias: {streak} de 30 (criterio de D030)",
        f"- Ejecuciones registradas: {len(runs)}; detenidas: {len(stops)}",
        "",
        "## Órdenes ejecutadas",
        "",
        "| Orden | Lado | Ejecución (UTC) | Retraso (h) | Precio medio | Apertura | "
        "Modelo | vs apertura (pb) | vs modelo (pb) | Comisión |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for f in fills:
        fee = (_fmt(f.fee_rate * 100, 3, " %") if f.fee_rate is not None
               else f"{f.fee_amount.normalize():f} {f.fee_asset} (sin convertir)")
        lines.append(
            f"| {f.client_order_id} | {f.side} | "
            f"{f.executed_at.strftime('%Y-%m-%d %H:%M') if f.executed_at else 'n/d'} | "
            f"{_fmt(f.delay_hours, 1)} | {_fmt(f.average_price, 4)} | "
            f"{_fmt(f.open_price, 4) if f.open_price is not None else 'vela pendiente'} | "
            f"{_fmt(f.modeled_price, 4)} | {_fmt(f.vs_open_bps, 1)} | "
            f"{_fmt(f.vs_model_bps, 1)} | {fee} |")
    if not fills:
        lines.append("| (ninguna) | | | | | | | | | |")
    lines += ["", f"Comisión del modelo: {model_fee:.3f} %. Positivo en pb = peor que la "
              "referencia; la apertura se completa al descargar la vela del día.", "",
              "## Incidencias (ejecuciones detenidas)", ""]
    lines += [f"- {r.at}: {r.detail}" for r in stops[-20:]] or ["- (ninguna)"]
    return "\n".join(lines) + "\n"
