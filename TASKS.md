# Tasks

## Estado
- [x] T001 — Inspeccionar el repositorio y el entorno.
- [x] T002 — Crear estructura mínima del paquete Python.
- [x] T003 — Configurar dependencias y entorno de desarrollo.
- [x] T004 — Implementar carga y validación de CSV.
- [x] T005 — Implementar señales de medias móviles.
- [x] T006 — Implementar motor de backtesting.
- [x] T007 — Añadir comisiones, slippage y límites de posición.
- [x] T008 — Calcular métricas y comparación buy-and-hold.
- [x] T009 — Generar informe reproducible.
- [x] T010 — Añadir pruebas de integración y documentación.
- [x] T011 — Revisión independiente con Codex.
- [x] T012 — Ejecutar el MVP completo con datos de ejemplo.

## Reglas
- Marcar una tarea como completada solo después de verificarla.
- No saltar tareas bloqueadas sin documentar el motivo.
- Registrar nuevas tareas solo si aportan valor al MVP.
- Indicar archivos relevantes y criterios de aceptación.
- MVP completado (T001-T012). Siguiente fase: pendiente de aprobación del usuario.

## Registro T001 (Claude Code, 2026-10-13)
Comandos: git status/branch/remote/ls-files, git ls-remote origin,
git check-ignore, python --version, python -m pip --version,
comprobación de venv con python -c.
- Python 3.13.9 (Microsoft Store), pip 25.2, venv funciona,
  sin lanzador py. pytest/pandas/numpy no instalados (van en T003).
- Git 2.54, rama main. git ls-remote confirmó que origin/main en
  GitHub = c16715b (solo contenía .gitignore).
- src/, tests/, data/, reports/ vacíos. Sin archivos de credenciales.
- Corregido: nombre de la especificación (D007); datos de ejemplo
  en examples/ (D008).
- Riesgos abiertos: repositorio dentro de OneDrive (sincronización de
  .git/.venv); .gitignore usa "**pycache**/" (funciona, debería ser
  __pycache__/); sin .gitattributes (CRLF).

## Registro T002 (Claude Code, 2026-10-13)
Archivos: pyproject.toml, src/bottrading/__init__.py, tests/test_package.py.
- pyproject.toml sin dependencias todavía (se añaden en T003).
- Verificado: pyproject.toml se parsea con tomllib; el paquete se
  importa con src/ en sys.path y el test de humo pasa invocado a mano.
- NO verificado: pytest e instalación con `pip install -e .`
  (verificado después en T003).
- requires-python >=3.11 declarado; solo probado con 3.13.9.
- Módulos del MVP (config, data, strategy...) no creados: cada tarea
  creará el suyo para evitar archivos vacíos.

## Registro T003 (Claude Code, 2026-10-13)
Archivos: pyproject.toml (extra dev), .gitignore, readme.md, DECISIONS.md (D010).
Comandos y resultados:
- `python -m venv .venv` -> OK (Python 3.13.9).
- `.venv\Scripts\python -m pip install -e ".[dev]"` -> OK
  (bottrading 0.1.0 editable, pytest 9.1.1; requiere acceso a PyPI).
- `.venv\Scripts\python -m pytest -v` -> 1 passed.
- .gitignore: añadido *.egg-info/, build/, dist/; corregido
  "**pycache**/" -> "__pycache__/". Verificado con git status --ignored.
- Riesgo abierto: .venv dentro de OneDrive (sincronización).

## Registro T004 (Claude Code, 2026-10-13)
Archivos: src/bottrading/data.py, tests/test_data.py, DECISIONS.md (D011).
- API: load_ohlcv_csv(path, epoch_unit="ms") -> list[Candle];
  parse_timestamp(); DataValidationError (subclase de ValueError).
- Sin dependencias nuevas (biblioteca estándar).
- `.venv\Scripts\python -m pytest -q` -> 28 passed (primera versión).
- Revisión Codex: "requiere cambios". Corregido: campos sobrantes
  descartados en silencio, BOM UTF-8, líneas vacías entre datos,
  epoch con unidad equivocada aceptado, duplicados sin número de
  línea. Lectura cambiada de DictReader a csv.reader.
- Tras correcciones: `.venv\Scripts\python -m pytest -q` -> 38 passed.
- Pruebas con CSV sintéticos en tmp_path; sin descargas.
- No cubierto (documentado en D011): huecos entre velas y velas
  incompletas.
- Segunda revisión Codex: "listo con cambios menores". Aplicado: las
  columnas extra se registran en el log (INFO); D011 documenta el
  límite de epoch para datos anteriores a 1973. -> 38 passed.

## Registro T005 (Claude Code, 2026-10-13)
Archivos: src/bottrading/strategy.py, tests/test_strategy.py, DECISIONS.md (D012).
- API: crossover_signals(closes, fast, slow) -> list[Signal];
  simple_moving_average(); validate_windows(). Signal: BUY/SELL/HOLD.
- Prueba de no look-ahead: las señales de cada prefijo de la serie
  coinciden con las de la serie completa.
- Corregido durante la tarea: la primera versión daba una señal falsa
  cuando la rápida tocaba la lenta y volvía al mismo lado.
- `.venv\Scripts\python -m pytest -q` -> 62 passed.
- Revisión Codex: "listo con cambios menores". Aplicado: prueba de
  SELL tras empate inicial; D012 precisa slippage adverso -> 63 passed.
- Ejecución en la vela siguiente: pendiente de T006 (no implementada).

## Registro T006 (Claude Code, 2026-10-13)
Archivos: src/bottrading/backtest.py, tests/test_backtest.py, DECISIONS.md (D013).
- API: run_backtest(candles, signals, initial_capital) -> BacktestResult
  (trades, timestamps, equity, final_cash, final_quantity). Trade
  registra la vela de la señal y la de ejecución.
- Pruebas: ejecución a la apertura de i+1 (no al cierre de i), ida y
  vuelta, señal en la última vela, posición abierta al final, señales
  redundantes, sin saldo negativo, alterar velas futuras no cambia el
  capital pasado, validación de entradas.
- `.venv\Scripts\python -m pytest -q` -> 81 passed.
- Revisión Codex: "requiere cambios" (una vela con precio negativo
  producía cantidad negativa). Corregido: el motor rechaza velas con
  precios no positivos o no finitos (16 pruebas) -> 97 passed.
- Sin costes ni límite de posición: pendiente de T007.

## Registro T007 (Claude Code, 2026-10-13)
Archivos: src/bottrading/config.py (nuevo), src/bottrading/backtest.py,
tests/test_config.py (nuevo), tests/test_backtest.py, DECISIONS.md (D014).
- run_backtest(candles, signals, config: BacktestConfig): cambia la
  firma (antes initial_capital). Pruebas de mecánica usan costes 0.
- Slippage adverso en compra y venta; comisión sobre el nominal;
  límite de tamaño de posición; costes registrados por operación.
- Prueba exacta: con precio constante, capital final = inicial −
  comisiones − slippage.
- `.venv\Scripts\python -m pytest -q` -> 122 passed.
- Revisión Codex: "listo con cambios menores". Añadida prueba combinada
  de fracción < 1 con costes -> 123 passed. El valor neto de
  liquidación se hace en T008.

## Registro T008 (Claude Code, 2026-10-13)
Archivos: src/bottrading/metrics.py y tests/test_metrics.py (nuevos),
src/bottrading/backtest.py (final_liquidation_value),
src/bottrading/strategy.py (buy_and_hold_signals),
tests/test_backtest.py, DECISIONS.md (D015).
- compute_metrics(result, risk_free_rate=0.0) -> Metrics;
  compare_with_buy_and_hold(candles, signals, config) -> Comparison.
- Recomendación de Codex en T007 aplicada: se distingue valoración
  mark-to-market y valor neto de liquidación.
- Métricas sin datos suficientes -> None con nota explicativa.
- `.venv\Scripts\python -m pytest -q` -> 148 passed.
- Revisión Codex: "listo con cambios menores". Sus dos puntos
  (separar costes ejecutados de costes estimados de liquidación y
  mostrar la limitación de intervalos irregulares) se aplican en T009.

## Registro T009 (Claude Code, 2026-10-13)
Archivos: src/bottrading/report.py, src/bottrading/__main__.py,
tests/test_report.py, examples/generate_synthetic.py,
examples/synthetic_daily.csv, .gitattributes (nuevos);
src/bottrading/metrics.py (estimated_exit_costs, irregular_gaps),
tests/test_metrics.py, readme.md (Uso), DECISIONS.md (D016).
Eliminado examples/.gitkeep (la carpeta ya tiene archivos).
- `python -m bottrading --csv examples/synthetic_daily.csv` -> OK;
  dos ejecuciones dan los mismos SHA-256 en los tres archivos.
- Errores (archivo inexistente, fast >= slow) -> mensaje y código 2.
- Resultado del ejemplo (SMA 10/30, datos sintéticos): estrategia
  -8.93 % neto frente a -0.90 % de buy-and-hold. Sin valor predictivo.
- `.venv\Scripts\python -m pytest -q` -> 167 passed.
- Revisión Codex: "listo" (reproducibilidad verificada con hashes en
  directorios externos). Aplicada su sugerencia: examples/README.md
  identifica el CSV como sintético.

## Registro T010 (Claude Code, 2026-10-13)
Archivos: tests/test_integration.py (nuevo), readme.md (Arquitectura,
Supuestos y limitaciones).
- 9 pruebas de punta a punta con examples/synthetic_daily.csv: carga,
  alternancia compra/venta, ejecución en la vela siguiente, sin
  look-ahead al recortar los datos, contabilidad = suma de PnL, costes
  reducen el valor final, buy-and-hold sin costes sigue al precio,
  métricas disponibles con 2 años diarios, CLI completa.
- `.venv\Scripts\python -m pytest -q` -> 176 passed.

## Registro T011 (revisión de Codex, transmitida por el usuario)
- Codex: instalación en venv limpio fuera del repositorio con
  pip install -e ".[dev]" -> 176 passed; CLI reproducible; costes,
  ejecución en la vela siguiente y ausencia de look-ahead confirmados;
  sin red, claves ni órdenes reales en src/, tests/, examples/.
  Veredicto: "listo con cambios menores".
- Aplicado por Claude Code: el informe cita solo el nombre del CSV
  (prueba de informe idéntico desde otra carpeta); run_backtest valida
  volumen y coherencia high/low con validate_candle (4 pruebas).
- `.venv\Scripts\python -m pytest -q` -> 181 passed.

## Registro T012 (Claude Code, 2026-10-13)
Clon limpio del commit 5ea428f en un directorio temporal fuera del
repositorio y de OneDrive:
- `python -m venv .venv` + `pip install -e ".[dev]"` -> OK.
- `python -m pytest -q -p no:cacheprovider` -> 181 passed.
- `python -m bottrading --csv examples/synthetic_daily.csv` dos veces
  -> código 0, hashes idénticos; y también idénticos a la ejecución en
  la carpeta original (informe independiente de la ubicación):
  report.md  4b04ea3d524d8d1a37ff572a10f9c637d3a65da78a7baa73b7fd40fe65cc6447
  trades.csv 1130c2462d8ea44046ac02fa083e91a6aa02cfcf15a12d41182de48887a2a3b2
  equity.csv d6fc2c8719d6e0f19e041a7bcf589250dccb7ef1070be9e388879fbfc7c17a82
- CSV de ejemplo en el clon: SHA-256 e08955d1... (igual al original).
- Resultado (datos SINTÉTICOS, SMA 10/30, costes por defecto):
  estrategia -8.93 % neto, buy-and-hold -0.90 %; 28 operaciones,
  342.32 en costes. Sin valor predictivo sobre mercados reales.

Criterios de aceptación de PROJECT_SPEC.md:
- [x] Instalable en un entorno virtual limpio.
- [x] Las pruebas pasan (181).
- [x] El dataset de ejemplo produce resultados reproducibles.
- [x] Las operaciones incluyen comisiones y slippage.
- [x] Sin datos futuros (pruebas de prefijos y de recorte).
- [x] Se genera un informe documentado.
- [x] Ejecución simulada por defecto; sin red, claves ni órdenes reales.
