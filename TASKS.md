# Tasks

## Estado
- [x] T001 — Inspeccionar el repositorio y el entorno.
- [x] T002 — Crear estructura mínima del paquete Python.
- [x] T003 — Configurar dependencias y entorno de desarrollo.
- [x] T004 — Implementar carga y validación de CSV.
- [x] T005 — Implementar señales de medias móviles.
- [x] T006 — Implementar motor de backtesting.
- [ ] T007 — Añadir comisiones, slippage y límites de posición.
- [ ] T008 — Calcular métricas y comparación buy-and-hold.
- [ ] T009 — Generar informe reproducible.
- [ ] T010 — Añadir pruebas de integración y documentación.
- [ ] T011 — Revisión independiente con Codex.
- [ ] T012 — Ejecutar el MVP completo con datos de ejemplo.

## Reglas
- Marcar una tarea como completada solo después de verificarla.
- No saltar tareas bloqueadas sin documentar el motivo.
- Registrar nuevas tareas solo si aportan valor al MVP.
- Indicar archivos relevantes y criterios de aceptación.
- El siguiente paso prioritario es T007.

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
