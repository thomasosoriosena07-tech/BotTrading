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

## Fase 2 (ver PROJECT_SPEC.md "Fase 2" y DECISIONS.md D017)
Reordenado tras la revisión de Codex del plan: todas las estrategias,
la rejilla y el criterio de selección se fijan ANTES de abrir el
holdout final, que se evalúa una sola vez (T017).
- [x] T013 — Importar klines de Binance (ZIP o CSV).
  Columnas: 0 open_time, 1 open, 2 high, 3 low, 4 close, 5 volume,
  6 close_time; 7-11 se ignoran. Sin cabecera (se tolera una cabecera
  con nombres). Unidad del open_time por magnitud: >= 1e14 µs (spot
  desde 2025), si no ms (>= 1e11); otro valor es error. Misma
  validación que load_ohlcv_csv; close_time > open_time; duplicados
  entre archivos con archivo:línea; verifica `.CHECKSUM` si existe.
  Pruebas con archivos sintéticos con ese formato (sin red).
- [x] T013b — Descargador de klines públicos (aprobado por el usuario, D019).
- [x] T014 — Particiones temporales.
  Aceptación: holdout final = último ~20 % (>= 1 año natural si se
  publican métricas anualizadas; si no alcanza, la muestra se declara
  insuficiente para ellas); el resto se divide en ventanas
  walk-forward (ajuste creciente + validación) sin solapamiento.
  Diseño inicial: diario, 2 años de ajuste inicial y 5 ventanas de
  6 meses; horario, 6 meses y 5 ventanas de 1 mes. Las medias se
  calientan con datos anteriores sin operar en ellos. Prueba de que
  alterar el holdout no cambia nada de la selección.
- [x] T015 — Hasta dos estrategias adicionales.
  Aceptación: misma interfaz de señales; prueba de prefijos (no
  look-ahead) para cada una; costes y ejecución idénticos.
- [x] T016 — Selección en walk-forward (sin tocar el holdout).
  Aceptación: rejilla explícita y pequeña para cada estrategia; criterio
  de selección fijado antes de ejecutar; se registran TODAS las
  combinaciones (estrategias × parámetros) con sus métricas por ventana
  y el número total de pruebas.
- [x] T017 — Evaluación final en el holdout e informe comparativo.
  Aceptación: el holdout se ejecuta una sola vez con la selección
  fijada; resultados por ventana walk-forward y del holdout por
  separado; número total de combinaciones y estrategias probadas;
  buy-and-hold en los mismos tramos; sensibilidad a costes (comisión
  0,1 % es un supuesto configurable, no el coste real garantizado);
  limitaciones: supervivencia (solo símbolos existentes hoy), cambios
  de régimen. Resultados desfavorables se publican igual.
- [x] T018 — Revisión independiente de la fase 2 con Codex.
- [x] T020 — Estrategia congelada en otros activos (D025).
  Aceptación: protocolo publicado antes de ejecutar; control BTC igual
  a D022/D024; ETH y SOL en los mismos tramos; reglas de D025 aplicadas
  sin cambios; informe reproducible.
- [~] T019 — Paper trading con datos públicos en tiempo real (EN CURSO hasta 2027-09-30).
  Compromiso del usuario (2026-10-13): hacerla después de T020 "con
  firmeza". Alcance de red aprobado ("sí al alcance de red de T019"):
  solo archivos diarios públicos de data.binance.vision (D027).
  BLOQUEADA hasta aprobar el acceso a red (D017): sin claves ni
  órdenes; las pruebas siguen sin red.
- [~] T021 — Integración futura con Binance Spot Demo Mode (D030).
  F0 (documento D030) y F1 (capa local) hechos y revisados. Siguiente:
  F2a (sin red). Lectura de
  cuenta demo aprobada (a); envío de órdenes NO aprobado (b). Fases
  F1-F6 en D030; F1, F2a y F2b sin red. No altera T019 ni paper/.

## Reglas
- Marcar una tarea como completada solo después de verificarla.
- No saltar tareas bloqueadas sin documentar el motivo.
- Registrar nuevas tareas solo si aportan valor al proyecto.
- Indicar archivos relevantes y criterios de aceptación.
- MVP completado (T001-T012). Fase 2 completada (T013-T018); T019
  bloqueada hasta aprobar el acceso a red. Siguiente fase: pendiente de
  decisión del usuario.

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

## Registro T013 (Claude Code, 2026-10-13)
Archivos: src/bottrading/binance.py y tests/test_binance.py (nuevos);
src/bottrading/__main__.py (--binance), src/bottrading/report.py
(varios archivos con SHA-256 y estado del checksum),
src/bottrading/data.py (parse_float público), tests/test_report.py,
readme.md, DECISIONS.md (D018). Plan de fase 2 reordenado según la
revisión de Codex (holdout final separado; D017 ampliada).
- Datos del usuario en data/: BTCUSDT 1h 2026-07, -08, -09 (2208
  velas, sin huecos, open_time en µs). Checksums de agosto y
  septiembre verificados; julio sin .CHECKSUM (en data/ está el de
  junio, cuyo ZIP falta).
- `python -m bottrading --binance data --fast 24 --slow 72` -> OK.
  Resultado (3 meses, no concluyente): estrategia +12.57 % neto,
  buy-and-hold +42.33 %.
- El informe del ejemplo sintético no cambia (SHA-256 4b04ea3d...).
- `.venv\Scripts\python -m pytest -q` -> 209 passed.
- Revisión Codex: "requiere cambios menores". Corregido: ZIP con CRC
  dañado y timestamps enormes ahora dan DataValidationError (4 pruebas);
  nota pendiente de DECISIONS actualizada -> 213 passed.
- Para T014 los datos no bastan: 3 meses horarios < 6 meses de ajuste
  inicial + 5 ventanas de 1 mes + holdout.

## Registro T013b (Claude Code, 2026-10-13)
Archivos: src/bottrading/download.py y tests/test_download.py (nuevos),
readme.md, DECISIONS.md (D017 actualizada, D019).
- 16 pruebas con servidor falso (sin red), incluida la guarda de que
  ningún otro módulo importa librerías de red.
- Descarga real: `python -m bottrading.download --symbol BTCUSDT
  --interval 1d --start 2020-01 --end 2026-09` -> 81 descargados,
  checksums verificados. Carga: 2465 velas diarias 2020-01-01 a
  2026-09-30, 0 huecos. Segunda ejecución: "ya presente".
- `.venv\Scripts\python -m pytest -q` -> 229 passed.
- Datos suficientes para el diseño diario de T014 (6,75 años).
- Revisión Codex: "requiere cambios menores". Corregido: redirecciones
  restringidas a HTTPS en data.binance.vision y URL final comprobada;
  guarda de red ampliada (más librerías, import del descargador,
  importación dinámica) y documentada como estática; la prueba de
  checksum incorrecto exige que no se cree nada. Descarga real de un
  mes a un directorio temporal tras el cambio -> OK.
  `.venv\Scripts\python -m pytest -q` -> 243 passed.

## Registro T014 (Claude Code, 2026-10-13)
Archivos: src/bottrading/splits.py y tests/test_splits.py (nuevos),
DECISIONS.md (D020).
- plan_splits(timestamps, DAILY|HOURLY) -> SplitPlan (ventanas y
  holdout); evaluate_segment(candles, start, end, signal_fn, config).
- Pruebas: estructura y no solapamiento, meses de calendario, ajuste
  mínimo, datos insuficientes, holdout no anualizable, calentamiento
  causal, segmento sin órdenes arrastradas, alterar precios del holdout
  no cambia ningún resultado de ajuste ni validación.
- Plan sobre datos reales calculado SOLO con fechas; no se ha ejecutado
  ningún backtest sobre BTCUSDT 1d.
- `.venv\Scripts\python -m pytest -q` -> 265 passed.
- Revisión Codex: "listo con cambios menores". Aplicado: herencia de
  posición por tramo (estrategia y buy-and-hold entran a la vez; nuevo
  initial_signal en run_backtest) y rechazo de fechas desordenadas en
  plan_splits -> 271 passed.

## Registro T015 (Claude Code, 2026-10-13)
Archivos: src/bottrading/strategy.py (trend_filter_signals,
donchian_signals), tests/test_strategy.py, DECISIONS.md (D021).
- Estrategias y criterio de selección aprobados por el usuario y
  registrados ANTES de ejecutar nada sobre datos reales.
- Pruebas: valores calculados a mano, empates, primera señal posible,
  validación de parámetros y prueba de prefijos (no look-ahead) para
  ambas estrategias.
- `.venv\Scripts\python -m pytest -q` -> 282 passed.
- Revisión Codex: "requiere cambios". Corregido: Donchian evaluaba
  ambas condiciones desde max(entry, exit) y retrasaba señales; ahora
  cada una tiene su calentamiento (pruebas con entry < exit y
  exit < entry). Añadidas pruebas de herencia de posición para las dos
  estrategias nuevas. D021: regla de "sin ventaja" si la mediana es
  <= 0 y rejillas registradas (22). -> 285 passed.

## Registro T016 (Claude Code, 2026-10-13)
Archivos: src/bottrading/walkforward.py y tests/test_walkforward.py
(nuevos); src/bottrading/report.py (write_selection_report),
DECISIONS.md (D022).
- run_selection recorta las velas en holdout_start; pruebas: alterar
  o eliminar el holdout no cambia el resultado; puntuaciones iguales a
  la evaluación directa; ranking; rejilla = D021 (22); informe y CSV
  reproducibles; datos insuficientes -> código 2.
- Ejecutado con datos reales (solo validación). Elegida
  trend_filter(window=50); ver D022 (gana en Sharpe, pierde en retorno
  frente a buy-and-hold en las 5 ventanas).
- `.venv\Scripts\python -m pytest -q` -> 302 passed.
- Revisión Codex: "listo con cambios menores". Aplicado: volatilidad y
  retorno por ventana en trials.csv y selection.md (la afirmación de
  D022 queda respaldada: 35,6 % frente a 48,8 %); protocolo del holdout
  (escenarios de costes e interpretación) registrado en D023 ANTES de
  abrirlo. Selección sin cambios. -> 302 passed.

## Registro T017 (Claude Code, 2026-10-13)
Orden seguido: protocolo D023 registrado y publicado (bc783bb) ->
código del holdout probado solo con datos sintéticos y publicado
(45afaa9) -> apertura única del holdout con autorización del usuario
("abre el holdout") -> resultado registrado en D024 sin cambios.
Archivos: src/bottrading/holdout.py, tests/test_holdout.py,
src/bottrading/report.py (write_holdout_report), DECISIONS.md (D023,
D024), readme.md (fase 2).
- Pruebas: escenarios = D023, solo velas del holdout, igualdad con la
  evaluación directa, costes mayores nunca ayudan, reglas del
  veredicto, confirmación --open-holdout obligatoria, candidata dentro
  de la rejilla, informe reproducible.
- Resultado: ver D024 (estrategia +4,48 %, buy-and-hold -23,51 %, en un
  holdout bajista; las 4 reglas de D023 se cumplen).
- `.venv\Scripts\python -m pytest -q` -> 317 passed.

## Registro T018 (revisión de Codex, transmitida por el usuario)
- Codex: orden Git correcto (bc783bb -> 45afaa9 -> b962e9d), selección
  aislada del holdout, veredicto conforme a D023, D024 prudente;
  317 passed. Veredicto: "requiere cambios": la CLI permitía evaluar
  otra combinación, esquema o capital en el holdout; faltaba probar la
  regla de menor riesgo. Codex no pudo reproducir los hashes (Python no
  arrancó en su entorno).
- Aplicado por Claude Code: CLI del holdout bloqueada al protocolo
  (FROZEN_CANDIDATE, esquema diario, capital 10 000; sin --scheme ni
  --capital); pruebas de rechazo y de lower_risk -> 320 passed.
- Reproducción por Claude Code con la CLI bloqueada (misma evaluación
  congelada, salida en directorio temporal): los 5 SHA-256 coinciden con
  D022 (be1dc696, a24b3cdf) y D024 (ba3781c0, 5cd321c2, 98b91cf2).
- Confirmación de Codex (transmitida por el usuario): correcciones
  aplicadas y probadas; 320 passed; "sí, se puede dar por cerrada la
  fase 2". Limitación declarada por Codex: no pudo reproducir los hashes
  en su entorno (no arrancó .venv\Scripts\python.exe); la
  reproducción de los 5 SHA-256 la hizo solo Claude Code.
- Fase 2 (T013-T018) cerrada. T019 sigue bloqueada (D017).

## Registro T020 (Claude Code, 2026-10-13)
Orden: protocolo D025 + código probado con datos sintéticos publicados
(d840d76) -> descarga de ETH y SOL (D019) -> ejecución única -> D026.
Archivos: src/bottrading/crossasset.py, tests/test_crossasset.py,
src/bottrading/report.py (write_crossasset_report), DECISIONS.md.
- Control BTC idéntico a D022/D024. Patrón de D025 repetido en los 3
  activos; ver D026 (protección sí; ganancia solo en tramos bajistas).
- `.venv\Scripts\python -m pytest -q` -> 334 passed.
- Revisión Codex (transmitida por el usuario): "listo". Codex reprodujo
  en su entorno el control BTC y los SHA-256 de D026 (crossasset.md
  fe3bfb22..., segments.csv 1963eed0...): primera reproducción
  independiente. 334 passed.

## Registro T019 (Claude Code, 2026-10-13)
Orden: protocolo D027 publicado (275ca18) -> código probado solo con
datos sintéticos y publicado (6b18e07) -> descarga de días cerrados
2026-10-01 a 2026-10-12 (BTC, ETH, SOL; checksums verificados) ->
primera simulación -> diario versionado en paper/.
Archivos: src/bottrading/download.py (--daily), src/bottrading/paper.py,
src/bottrading/report.py (write_paper_report), tests/test_paper.py,
tests/test_download.py, readme.md.
- Primera ejecución: 12 días; 4 operaciones (3 compras heredadas al
  abrir el 2026-10-01 y una venta de ETH el 2026-10-09). Segunda
  ejecución: 0 filas nuevas y diario reproducido (integridad correcta).
- Guarda de red intacta: paper.py no importa el descargador.
- `.venv\Scripts\python -m pytest -q` -> 354 passed.
- Seguimiento: repetir descarga diaria + `python -m bottrading.paper`
  y commit de paper/. Evaluaciones en 2027-03-31 y 2027-09-30 (D027).
- Revisión Codex (transmitida por el usuario): "listo con cambios
  menores"; Codex reprodujo paper/ledger.csv (SHA-256 be5e5d85...).
  Aplicado: ancla paper/ledger.state (último día, filas, SHA-256) que
  detecta truncamientos, ediciones, borrados, retrocesos y filas nuevas
  con fecha ya simulada (9 pruebas); --init-anchor ancló el diario real
  tras reproducirlo exactamente (mismo SHA-256 que obtuvo Codex).
- Automatización (D028, pedida por el usuario): scripts/paper_daily.ps1
  y tarea programada de Windows "BotTrading paper trading", diaria a las
  08:00 (UTC-5). Verificado: ejecución manual del script y ejecución
  desde el Programador de tareas (resultado 0, "sin cambios"). NO
  verificado aún: el camino de commit + push automático, que necesita un
  día nuevo cerrado; primera oportunidad 2026-10-14 08:00.
- `.venv\Scripts\python -m pytest -q` -> 360 passed.
- Revisión Codex de D028: "requiere cambios". Aplicado: comprobación
  antes del commit (rama main; solo commits automáticos de paper/
  pendientes de publicar), push de lo pendiente tras el commit (si falla
  se reintenta), códigos de git diff distintos de 0/1 = error,
  --init-anchor falla sin diario o con ancla; D028 corregida y límite del
  ancla sin firma documentado. Lógica de seguridad del script probada en
  un repositorio temporal con remoto local (9 casos: sin pendientes,
  automático, ajeno, mensaje automático con otro archivo, otra rama,
  git diff con y sin cambios). Ejecución real del script: "OK".
  `.venv\Scripts\python -m pytest -q` -> 361 passed.
- Confirmación Codex de D028: "requiere cambios": un merge con mensaje
  automático podía publicar archivos ajenos (diff-tree no lista cambios
  de merges; Codex lo demostró). Aplicado: los merges pendientes cuentan
  como ajenos y la diferencia acumulada origin/main..HEAD debe tocar
  solo paper/. Pruebas de la guarda versionadas en
  scripts/test_paper_daily_guard.ps1: 13/13 OK (incluido el merge).
  Script real: "OK".
- Segunda confirmación Codex de D028: merge corregido (Codex lo repitió;
  13 OK); "requiere cambios" por una carrera con otros procesos entre la
  comprobación y el push. Aplicado: SHA fijado y revalidado, push de
  ese SHA exacto. Pruebas de la guarda: 16/16 OK (carrera con commit
  ajeno encima y debajo). Script real: "OK". 361 passed.
- Tercera confirmación Codex de D028 (transmitida por el usuario):
  "listo". Codex ejecutó las pruebas de la guarda (16 OK, incluida la
  carrera) y la suite (361 passed); no encontró caminos para publicar
  commits no validados ni commits propios fuera de paper/. Pendiente:
  primera ejecución real con commit + push (2026-10-14 08:00).

## Registro D029: panel HTML (Claude Code, 2026-10-13)
Archivos: src/bottrading/dashboard.py (nuevo), src/bottrading/report.py,
tests/test_paper.py, readme.md, DECISIONS.md (D029), paper/dashboard.html.
- Pruebas: autónomo (sin <script> ni URL externas), un gráfico por
  activo, todas las operaciones listadas, reproducible, escala del
  gráfico con un solo día o serie plana. 365 passed.
- Revisión visual: renderizado con Edge sin ventana y captura revisada;
  corregido el orden de dibujo (la estrategia queda encima de
  buy-and-hold cuando coinciden).
- Revisión Codex (transmitida por el usuario): "listo". Codex verificó
  escape del contenido, página autónoma, coherencia con report.md,
  equity.csv y ledger.csv, escala del SVG y guarda de red; 365 passed.
  Observación sin acción: svg_line_chart presupone series no vacías y
  clases CSS internas (no hay entrada de usuario que llegue ahí).

## Registro T021 F0 (Claude Code, 2026-10-13)
Archivos: DECISIONS.md (D030), PROJECT_SPEC.md (excepción y fase 3),
AGENTS.md y CLAUDE.md (excepción acotada), TASKS.md. Sin código.
- Plan revisado por Codex en tres rondas (v1 no llegó; v2 y v3 con
  hallazgos). D030 incorpora los hallazgos abiertos de v3: tabla
  ejecutable de peticiones, límites operativos, cobertura de la
  reconciliación y comisiones en cualquier activo, almacenamiento de
  secretos, esquema cerrado del contenido publicado, adjudicación
  manual, definición de "repetir envía 0" y hashes de paper/ con la
  tarea pausada.
- Documentación oficial consultada (ver D030). Hallazgo relevante: el
  servidor acepta un newClientOrderId repetido si la orden anterior
  está llena, así que la deduplicación no puede depender de él.
- Aprobación del usuario: (a) lectura demo. Pendiente: aprobación (b)
  antes de F4.
- Revisión de Codex de D030 (transmitida por el usuario): se puede
  empezar F1. Corregido en D030: la cobertura se comprueba por claves y
  cursores inclusivos, no por ids consecutivos; el id repetido se
  condiciona a la orden anterior FILLED, con prueba de servidor que lo
  acepta; el capital pasa a presupuesto no reinvertible de 1000 USDT por
  activo (compra = min(efectivo, 1000), exposición a coste <= 3000);
  tolerancia de BNB y parada ante otros activos; clave de solo lectura
  (sin TRADE) para F3; eliminada la fecha de disponibilidad no
  corroborada.

## Registro T021 F1 (Claude Code, 2026-10-13)
Archivos: src/bottrading/execution.py (nuevo), tests/conftest.py (nuevo),
tests/test_execution.py (nuevo), readme.md. paper.py sin cambios. Sin red.
- execution.py: clientOrderId determinista (bt-SÍMBOLO-AAAAMMDD-B|S,
  formato ^[a-zA-Z0-9-_]{1,36}$); decide() puro con la semántica del
  motor y presupuesto opcional no reinvertible; check_limits() con los
  límites de D030 (sin reducir órdenes: LimitExceeded); run_local()
  ejecuta intenciones con el modelo de costes de D014 (reutiliza
  backtest._buy/_sell) y la herencia de posición de D020.
- conftest.py: red bloqueada en tiempo de ejecución en TODAS las pruebas
  (connect, connect_ex, create_connection, getaddrinfo) y hash de cada
  archivo de paper/ antes y después de la suite. Ejecutar la suite con
  la tarea D028 deshabilitada o fuera de las 08:00.
- Pruebas: paridad exacta (floats) de run_local con paper.simulate en
  12 series sintéticas y con fin de tramo; paridad byte a byte con una
  COPIA de paper/ledger.csv usando los datos reales hasta el día del
  ancla (se salta si no hay data/); límites justo por debajo, en y por
  encima; compra tras ganancia (1200 -> 1000) y tras pérdida (800).
  397 passed, 0 skipped; paper/ sin cambios (git status limpio).

- Revisión de Codex de F1 (transmitida por el usuario): no cerrar F1. Corregido:
  run_local con budget parte de 1000 (no del capital de paper) y recompra
  tras pérdida con lo que queda; check_limits acumula las órdenes ya
  registradas del día (already_today), exige coherencia con la posición
  confirmada (compra solo sin posición y sin superar el efectivo; venta
  exactamente de la cantidad poseída) y, de forma conservadora, una venta
  del mismo día no libera exposición; run_local valida velas y señales
  como run_backtest; la paridad real se compara byte a byte con el
  serializador del diario; el hash de paper/ es recursivo; el bloqueo de
  red impide además crear sockets, sendto/sendmsg y socketpair, y su
  alcance (no es aislamiento) queda escrito en conftest.py. Importar
  _buy/_sell/_validate_inputs se mantiene como provisional (aceptado por
  Codex) hasta una interfaz pública común. 404 passed, 0 skipped.

- Revisión de Codex de 7ba2381 (transmitida por el usuario): F1 CERRADO;
  se puede empezar F2a. 404 passed; paper/ intacto. Cautela para F2b:
  already_today y holdings deben salir del MISMO ledger reconciliado
  (una compra registrada con posición aún plana cuenta como exposición
  pendiente; si ledger y holdings discrepan, el llamador debe detenerse).
