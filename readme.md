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

### Datos históricos de Binance

Descargar los klines mensuales públicos (verificados con su `.CHECKSUM`)
a `data/BTCUSDT-1d/` (ignorada por Git):

    python -m bottrading.download --symbol BTCUSDT --interval 1d --start 2020-01

También se pueden descargar a mano desde data.binance.vision (Spot →
monthly → klines → símbolo → intervalo). Después:

    python -m bottrading --binance data/BTCUSDT-1d --fast 20 --slow 50

`--binance` acepta carpetas o archivos `.zip`/`.csv`. Se verifica el
`.CHECKSUM` de cada ZIP cuando existe. El backtest no usa red;
solo el descargador accede a data.binance.vision, sin claves API.

### Fase 2: selección y holdout final

    python -m bottrading.walkforward --binance data/BTCUSDT-1d --scheme daily
    python -m bottrading.holdout --binance data/BTCUSDT-1d --candidate trend_filter:window=50 --open-holdout

La selección solo usa ventanas de validación; el holdout final se abre
una vez, con el protocolo fijado de antemano (DECISIONS.md D020-D024).

### Paper trading (desde 2026-10-01, D027)

Sin dinero ni órdenes. Para actualizarlo, descargar los días cerrados y
volver a simular (el diario `paper/ledger.csv` solo admite añadir filas):

    python -m bottrading.download --symbol BTCUSDT --interval 1d --daily --start 2026-10-01
    python -m bottrading.download --symbol ETHUSDT --interval 1d --daily --start 2026-10-01
    python -m bottrading.download --symbol SOLUSDT --interval 1d --daily --start 2026-10-01
    python -m bottrading.paper

Después, hacer commit de `paper/` para que Git sirva de sello de tiempo.
La tarea programada de D028 lo hace sola cada día a las 08:00.

Panel visual: abrir `paper/dashboard.html` en el navegador (se regenera
en cada ejecución; funciona sin internet).
Puntos de control: 2027-03-31 y 2027-09-30.

### Cuenta demo de Binance (D030, solo lectura)
Fase experimental: valida la ejecución, no la rentabilidad. No envía
órdenes (requiere una aprobación posterior) ni toca `paper/`.

1. En Binance: *Demo Trading* -> *API Management*, crea una clave de
   **solo lectura** (sin permiso TRADE) en una cuenta demo **dedicada**.
2. Guárdala en Windows sin que quede en el historial de la consola:
   `cmdkey /generic:BotTrading-Demo /user:bottrading /pass` y pega
   `APIKEY:SECRET` cuando lo pida. No la compartas con nadie.
3. Comprobación: `python -m bottrading.demo_client check`
4. Línea base (pide escribir INICIALIZAR): `python -m bottrading.demo_client init`
5. Reconciliación: `python -m bottrading.demo_client reconcile`

El estado privado vive en `%USERPROFILE%\.bottrading\demo\`, fuera del
repositorio. Crear el archivo `STOP` en esa carpeta activa el kill switch.

## Arquitectura

Paquete `src/bottrading/`, un módulo por responsabilidad:

| Módulo | Función |
|---|---|
| `config.py` | `BacktestConfig`: capital, comisión, slippage, tamaño de posición |
| `data.py` | Carga y validación del CSV OHLCV, normalización a UTC |
| `binance.py` | Importación de klines de Binance (ZIP/CSV, checksum) |
| `download.py` | Descarga de klines públicos (único módulo con red) |
| `splits.py` | Particiones walk-forward y holdout final |
| `walkforward.py` | Selección de estrategia y parámetros en validación |
| `holdout.py` | Evaluación única del holdout final |
| `crossasset.py` | Estrategia congelada en otros activos |
| `paper.py` | Paper trading con diario solo de añadir |
| `dashboard.py` | Panel HTML del paper trading |
| `execution.py` | Intención de orden, límites de D030 y ejecutor local (sin red) |
| `demo_client.py` | Cliente de solo lectura para Binance Spot Demo (D030; aún sin uso real) |
| `demo_ledger.py` | Registro privado de órdenes demo y protocolo idempotente (sin envío real) |
| `demo_reconcile.py` | Línea base y reconciliación de la cuenta demo (solo lectura) |
| `publication.py` | Valida el contenido que la tarea diaria publica (lista cerrada) |
| `strategy.py` | Señales de cruce de medias y referencia buy-and-hold |
| `backtest.py` | Motor: ejecución en la apertura siguiente, costes, curva de capital |
| `metrics.py` | Retorno, drawdown, volatilidad, Sharpe, operaciones |
| `report.py` | Informe Markdown y CSV reproducibles |
| `__main__.py` | Línea de comandos |

Flujo: CSV → velas validadas → señales al cierre de cada vela →
ejecución simulada en la vela siguiente → métricas → informe.

Las reglas y supuestos están en `DECISIONS.md`; el estado de las
tareas, en `TASKS.md`.

## Supuestos y limitaciones

- Solo velas cerradas; los huecos entre velas se avisan, no se rellenan.
- Spot, solo largo, una posición a la vez; sin apalancamiento ni cortos.
- Fechas sin zona horaria se rechazan.
- Métricas sin datos suficientes se muestran como `n/d`.
- Parámetros no optimizados: un backtest no demuestra ventaja.

## Seguridad

No incluir claves API, contraseñas, archivos .env reales
ni información financiera privada en el repositorio.

Este proyecto no ejecuta órdenes reales y sus resultados
simulados no garantizan rendimientos futuros.