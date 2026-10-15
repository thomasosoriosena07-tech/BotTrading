"""Informe de ejecución de la cuenta demo (D030, F5). Sin red.

Compara cada orden ejecutada en Binance Demo con lo que asume el modelo de
paper (D014): ejecución a la APERTURA del día con 0,05 % de deslizamiento
adverso y 0,1 % de comisión. Mide aparte, nunca como un único "resultado":

- precio medio real frente a la apertura y frente al precio modelado (pb);
- (opción 1 de la revisión del 2026-10-15) SLIPPAGE REAL frente a la mejor
  cotización justo antes del envío (ask al comprar, bid al vender) y, aparte,
  el DESFASE HORARIO: cuánto se movió el mercado entre la apertura del modelo
  y el momento del envío. La demo corre cuando el PC está disponible, así que
  el desfase horario no mide la calidad de la ejecución; el slippage real sí;
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
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from bottrading.crossasset import CONFIG
from bottrading.data import Candle
from bottrading.demo_ledger import OrderRecord, write_private_file

QUOTE_ASSET = "USDT"
# Mismo criterio que Hide-Secrets (scripts/demo_daily.ps1): toda secuencia
# alfanumérica de 16 o más caracteres se tapa al mostrar texto libre.
SECRET_LIKE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{16,}(?![A-Za-z0-9])")


def redact(text: str) -> str:
    """Tapa lo que podría ser una credencial en texto libre (revisión de Codex)."""
    text = re.sub(r"(?i)signature=[^&\s]*", "signature=[oculto]", text)
    return SECRET_LIKE.sub("[oculto]", text)
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
    send_quote: "SendQuote | None" = None  # mejor bid/ask justo antes del envío

    @property
    def send_reference(self) -> Decimal | None:
        """Mejor precio disponible al enviar: ask al comprar, bid al vender."""
        if self.send_quote is None:
            return None
        return self.send_quote.ask if self.side == "BUY" else self.send_quote.bid

    @property
    def slippage_bps(self) -> Decimal | None:
        """Slippage real: precio medio frente a la mejor cotización del envío (positivo = peor)."""
        return _adverse_bps(self.side, self.average_price, self.send_reference)

    @property
    def timing_bps(self) -> Decimal | None:
        """Desfase horario: cotización del envío frente a la apertura del modelo (positivo = peor)."""
        if self.send_reference is None:
            return None
        return _adverse_bps(self.side, self.send_reference, self.open_price)

    @property
    def spread_bps(self) -> Decimal | None:
        if self.send_quote is None:
            return None
        bid, ask = self.send_quote.bid, self.send_quote.ask
        return (ask - bid) / ((ask + bid) / 2) * 10_000

    @property
    def latency_seconds(self) -> Decimal | None:
        """Segundos entre la cotización y la primera ejecución."""
        if self.send_quote is None or self.executed_at is None:
            return None
        return Decimal((self.executed_at - self.send_quote.captured_at).total_seconds())

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
                  base_assets: Mapping[str, str],
                  quotes: Mapping[str, "SendQuote"] | None = None) -> list[FillMetrics]:
    """Una entrada por orden del bot con ejecución (> 0) en el historial reconciliado.

    `quotes`: cotización del envío por clientOrderId (sin ella, "n/d")."""
    quotes = quotes or {}
    fills = []
    for symbol, symbol_orders in orders.items():
        opens = {c.timestamp.date(): Decimal(repr(c.open)) for c in candles.get(symbol, ())}
        for order in symbol_orders:
            record = records.get(order.get("clientOrderId"))
            own = [t for t in trades.get(symbol, ()) if t.get("orderId") == order.get("orderId")]
            if record is None or not own or Decimal(order.get("executedQty", "0")) == 0:
                continue
            fill = fill_metrics(record, order, own, opens, base_assets[symbol])
            quote = quotes.get(fill.client_order_id)
            fills.append(replace(fill, send_quote=quote) if quote else fill)
    return sorted(fills, key=lambda f: (f.executed_at or datetime.min.replace(tzinfo=timezone.utc),
                                        f.client_order_id))


def _csv_rows(path: Path) -> list[list[str]]:
    """Filas de un CSV privado. Cualquier error de formato (también csv.Error, p. ej.
    un campo enorme) se convierte en ValueError, que quien llama trata como aviso
    sin detener run (revisión de Codex)."""
    try:
        return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    except csv.Error:
        raise ValueError(f"{path.name}: CSV no válido") from None


# --- cotizaciones del envío -------------------------------------------------------------

QUOTE_COLUMNS = ["client_order_id", "captured_at", "bid", "ask"]


@dataclass(frozen=True)
class SendQuote:
    """Mejor bid/ask de la cuenta demo justo antes de enviar una orden nueva."""

    client_order_id: str
    captured_at: datetime
    bid: Decimal
    ask: Decimal


def valid_quote(bid: Decimal, ask: Decimal) -> bool:
    return bid.is_finite() and ask.is_finite() and 0 < bid <= ask


def append_quote(path: Path, quote: SendQuote) -> None:
    """Añade una cotización al registro privado (solo de añadir; sin seguir enlaces)."""
    if not valid_quote(quote.bid, quote.ask):
        raise ValueError("cotización no válida")
    previous = path.read_bytes() if path.exists() else b""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if not previous:
        writer.writerow(QUOTE_COLUMNS)
    writer.writerow([quote.client_order_id, quote.captured_at.isoformat(timespec="milliseconds"),
                     f"{quote.bid:f}", f"{quote.ask:f}"])
    write_private_file(path, previous + buffer.getvalue().encode("utf-8"))


def read_quotes(path: Path) -> dict[str, SendQuote]:
    """Última cotización registrada de cada orden: la tomada justo antes de su envío
    (una orden ya registrada no vuelve a cotizarse)."""
    if not path.exists():
        return {}
    rows = _csv_rows(path)
    if not rows or rows[0] != QUOTE_COLUMNS:
        raise ValueError(f"{path.name}: cabecera inesperada")
    quotes = {}
    for row in rows[1:]:
        if len(row) != len(QUOTE_COLUMNS):
            raise ValueError(f"{path.name}: fila no válida")
        quote = SendQuote(row[0], datetime.fromisoformat(row[1]), Decimal(row[2]), Decimal(row[3]))
        if quote.captured_at.tzinfo is None or not valid_quote(quote.bid, quote.ask):
            raise ValueError(f"{path.name}: fila no válida")
        quotes[quote.client_order_id] = quote
    return quotes


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
    """Añade una línea al diario privado de ejecuciones (solo de añadir).

    Se reescribe el archivo completo con write_private_file: nunca se escribe a
    través de un enlace existente (revisión de Codex)."""
    previous = path.read_bytes() if path.exists() else b""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if not previous:
        writer.writerow(RUN_COLUMNS)
    writer.writerow([day.isoformat(), at.isoformat(timespec="seconds"), outcome,
                     "" if orders is None else orders,
                     detail.replace("\n", " ")[:300]])
    write_private_file(path, previous + buffer.getvalue().encode("utf-8"))


def read_runs(path: Path) -> list[RunEntry]:
    if not path.exists():
        return []
    rows = _csv_rows(path)
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


def _quality_section(fills: Sequence[FillMetrics]) -> list[str]:
    """Slippage real (frente a la cotización del envío) separado del desfase horario."""
    quoted = [f for f in fills if f.send_quote is not None]
    lines = [
        "## Calidad de ejecución (frente a la cotización del envío)",
        "",
        "La demo corre cuando el PC está disponible, no a la apertura del modelo. Por eso",
        "\"vs apertura\" mezcla dos cosas que aquí se separan:",
        "- **Slippage real**: precio medio frente a la mejor cotización justo antes de",
        "  enviar (ask al comprar, bid al vender). Mide la calidad de la ejecución.",
        "- **Desfase horario**: esa cotización frente a la apertura del modelo. Es",
        "  movimiento del mercado por la hora de ejecución, no un coste de la ejecución.",
        "",
    ]
    if quoted:
        mean = sum((f.slippage_bps for f in quoted), Decimal(0)) / len(quoted)
        lines.append(f"Slippage real medio: {_fmt(mean, 1)} pb en {len(quoted)} órdenes "
                     "con cotización.")
        lines.append("")
    lines += [
        "| Orden | Cotización (UTC) | Bid | Ask | Diferencial (pb) | Precio medio | "
        "Slippage real (pb) | Desfase horario (pb) | Latencia (s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for f in fills:
        q = f.send_quote
        if q is None:
            lines.append(f"| {f.client_order_id} | sin cotización (orden anterior al registro "
                         f"o lectura fallida) | | | | {_fmt(f.average_price, 4)} | n/d | n/d | n/d |")
            continue
        lines.append(
            f"| {f.client_order_id} | {q.captured_at.strftime('%Y-%m-%d %H:%M:%S')} | "
            f"{_fmt(q.bid, 4)} | {_fmt(q.ask, 4)} | {_fmt(f.spread_bps, 2)} | "
            f"{_fmt(f.average_price, 4)} | {_fmt(f.slippage_bps, 1)} | "
            f"{_fmt(f.timing_bps, 1) if f.open_price is not None else 'vela pendiente'} | "
            f"{_fmt(f.latency_seconds, 1)} |")
    if not fills:
        lines.append("| (ninguna) | | | | | | | | |")
    return lines + [""]


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
              "referencia; la apertura se completa al descargar la vela del día.", ""]
    lines += _quality_section(fills)
    lines += ["## Incidencias (ejecuciones detenidas)", ""]
    lines += [f"- {r.at}: {redact(r.detail)}" for r in stops[-20:]] or ["- (ninguna)"]
    return "\n".join(lines) + "\n"
