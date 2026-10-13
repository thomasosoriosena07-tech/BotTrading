# BotTrading

Proyecto educativo de trading algorítmico en Python.

## Objetivo

Desarrollar y evaluar estrategias con datos históricos,
costes de transacción y controles de riesgo.

## Estado

En desarrollo. El MVP utiliza exclusivamente simulación.

## Requisitos

- Python compatible con las dependencias del proyecto.
- Git.
- VS Code recomendado.

## Instalación en Windows

Desde la raíz del proyecto, en PowerShell:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"

En CMD, activar con `.venv\Scripts\activate.bat`.

Las dependencias se declaran en pyproject.toml. El extra `dev`
añade las herramientas de prueba (pytest).

## Pruebas

Ejecutar las pruebas desde la raíz del proyecto:

    python -m pytest

## Uso

Ejecutar un backtest con el dataset de ejemplo (sintético, no real):

    python -m bottrading --csv examples/synthetic_daily.csv --fast 10 --slow 30

Genera en `reports/synthetic_daily_sma10-30/`:

- `report.md`: datos, parámetros, métricas frente a buy-and-hold,
  notas y limitaciones.
- `trades.csv`: operaciones simuladas con sus costes.
- `equity.csv`: curva de capital de la estrategia y de buy-and-hold.

Opciones: `--capital`, `--commission`, `--slippage`,
`--position-fraction`, `--risk-free`, `--epoch-unit`, `--out`, `-v`.
Ver `python -m bottrading --help`.

El CSV debe tener las columnas `timestamp,open,high,low,close,volume`,
con fechas ISO 8601 con zona horaria o epoch en milisegundos
(`--epoch-unit s` para segundos). El dataset de ejemplo se regenera con
`python examples/generate_synthetic.py`.

## Seguridad

No incluir claves API, contraseñas, archivos .env reales
ni información financiera privada en el repositorio.

Este proyecto no ejecuta órdenes reales y sus resultados
simulados no garantizan rendimientos futuros.