"""Línea de comandos: python -m bottrading (--csv <archivo> | --binance <rutas>).

Carga los datos, calcula señales de cruce de medias, simula la estrategia
y buy-and-hold con los mismos costes y escribe un informe reproducible.
Solo simulación: no conecta con exchanges ni envía órdenes.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from bottrading.backtest import run_backtest
from bottrading.binance import expand_paths, load_binance_klines
from bottrading.config import BacktestConfig
from bottrading.data import DataValidationError, load_ohlcv_csv
from bottrading.report import write_report
from bottrading.strategy import buy_and_hold_signals, crossover_signals, validate_windows

logger = logging.getLogger("bottrading")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bottrading",
        description="Backtest educativo de cruce de medias (solo simulación).",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, help="CSV OHLCV con cabecera")
    source.add_argument("--binance", type=Path, nargs="+", metavar="RUTA",
                        help="klines de Binance: archivos .zip/.csv o carpetas")
    parser.add_argument("--fast", type=int, default=10, help="media rápida (velas)")
    parser.add_argument("--slow", type=int, default=30, help="media lenta (velas)")
    parser.add_argument("--capital", type=float, default=10_000.0, help="capital inicial")
    parser.add_argument("--commission", type=float, default=0.001, help="comisión (0.001 = 0,1 %%)")
    parser.add_argument("--slippage", type=float, default=0.0005, help="slippage adverso")
    parser.add_argument("--position-fraction", type=float, default=1.0,
                        help="fracción máxima del efectivo por compra, en (0, 1]")
    parser.add_argument("--risk-free", type=float, default=0.0,
                        help="tasa libre de riesgo anual para el Sharpe")
    parser.add_argument("--epoch-unit", choices=("ms", "s"), default="ms",
                        help="unidad de los timestamps numéricos (solo --csv)")
    parser.add_argument("--out", type=Path, default=None,
                        help="directorio de salida (por defecto reports/<datos>_sma<fast>-<slow>)")
    parser.add_argument("-v", "--verbose", action="store_true", help="registro detallado")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        validate_windows(args.fast, args.slow)
        config = BacktestConfig(
            initial_capital=args.capital,
            commission_rate=args.commission,
            slippage_rate=args.slippage,
            max_position_fraction=args.position_fraction,
        )
        if args.csv is not None:
            data_paths = [args.csv]
            candles = load_ohlcv_csv(args.csv, epoch_unit=args.epoch_unit)
        else:
            data_paths = expand_paths(args.binance)
            candles = load_binance_klines(data_paths)
        out_dir = args.out or Path("reports") / (
            f"{_data_label(data_paths)}_sma{args.fast}-{args.slow}"
        )
        closes = [candle.close for candle in candles]
        strategy = run_backtest(candles, crossover_signals(closes, args.fast, args.slow), config)
        benchmark = run_backtest(candles, buy_and_hold_signals(len(candles)), config)
        paths = write_report(
            out_dir, data_paths=data_paths, candles=candles, fast=args.fast,
            slow=args.slow, strategy=strategy, benchmark=benchmark,
            risk_free_rate=args.risk_free,
        )
    except (DataValidationError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("Simulación educativa: no son resultados reales.")
    for path in paths.values():
        print(f"escrito {path}")
    return 0


def _data_label(paths: Sequence[Path]) -> str:
    first, last = paths[0].stem, paths[-1].stem
    return first if first == last else f"{first}_a_{last}"


if __name__ == "__main__":
    sys.exit(main())
