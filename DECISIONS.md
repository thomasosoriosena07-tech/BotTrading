# Technical Decisions

## D001 — Simulación primero
Estado: Aprobada

El MVP se limita a backtesting y paper trading.
Motivo: validar la lógica antes de considerar otros usos.

## D002 — Python
Estado: Aprobada

Python es el lenguaje principal por sus herramientas para
procesamiento de datos, pruebas y análisis cuantitativo.

## D003 — CSV como entrada inicial
Estado: Aprobada

Los primeros datos históricos se cargarán desde CSV.
Motivo: reducir dependencias y hacer las pruebas reproducibles.

## D004 — Estrategia de referencia simple
Estado: Aprobada

Se utilizará un cruce de medias móviles como estrategia educativa,
no como afirmación de ventaja estadística.

## D005 — Costes incluidos
Estado: Aprobada

Las simulaciones modelarán comisiones y slippage configurables.

## D006 — Sin conexión a trading real
Estado: Aprobada

No se utilizarán claves API ni órdenes reales en el MVP.

## D007 — Nombre de la especificación
Estado: Aprobada

proyect_spec.md se renombra a PROJECT_SPEC.md, el nombre que
citan AGENTS.md y CLAUDE.md.

## D008 — Datos de ejemplo en examples/
Estado: Aprobada

Los datos de ejemplo versionados irán en examples/.
data/ y reports/ siguen ignorados por Git (datos locales y salidas).

## D009 — pyproject.toml y estructura src/
Estado: Aprobada

Paquete en src/bottrading/, configurado con pyproject.toml.
Motivo: `pip install -e .` hace el paquete importable sin manipular
rutas y permite verificar la instalación en un entorno limpio.

## D010 — Dependencias mínimas
Estado: Aprobada

Única dependencia por ahora: pytest>=8, como extra de desarrollo
(`pip install -e ".[dev]"`). El uso de pandas se decidirá en T004,
cuando la carga de CSV lo justifique o no.

## D011 — Carga de CSV con biblioteca estándar
Estado: Aprobada

T004 usa solo csv, datetime y math; sin pandas. Se reconsiderará
si T005-T008 lo justifican.
- timestamp: ISO 8601 con zona horaria (se convierte a UTC) o epoch
  numérico en ms por defecto (`epoch_unit="s"` para segundos).
- Fechas sin zona horaria: se rechazan; nunca se asume UTC.
- Filas vacías, no numéricas, no finitas, precios <= 0, volumen < 0,
  high/low incoherentes o timestamps duplicados: DataValidationError
  con número de línea. No se corrige ni descarta nada en silencio.
- Filas desordenadas: se ordenan y se registra un aviso.
- Filas con más o menos campos que la cabecera, columnas repetidas y
  líneas vacías entre datos: error. Líneas vacías al final: se ignoran.
- Unidad del epoch: valores < 1e11 con unidad ms (o >= 1e11 con s) se
  rechazan por unidad probablemente equivocada.
- Se acepta UTF-8 con BOM.
- Columnas extra de la cabecera (no OHLCV): se ignoran a propósito y
  se registran en el log con nivel INFO.
- Datos anteriores a 1973-03-03: usar timestamps ISO 8601; el epoch
  en ms no los admite por la regla de unidad anterior.
Limitaciones: no se detectan huecos entre velas ni velas incompletas;
el CSV debe contener solo velas cerradas.

## D012 — Señales de cruce y momento de ejecución
Estado: Aprobada

- Medias móviles simples sobre el cierre; `1 <= fast < slow`, enteros.
- La señal de la vela i usa solo cierres hasta i (se conoce al cierre).
- BUY/SELL solo cuando la rápida cambia de lado respecto a la lenta.
  Los empates no son cruces: tocar y volver al mismo lado no genera
  señal. Si la rápida ya está por encima al terminar el calentamiento,
  no hay BUY hasta un cruce real.
- Ejecución (T006): al precio de apertura de la vela i + 1. Una señal
  en la última vela no se ejecuta.
- Slippage (T007): siempre adverso. Compra = apertura × (1 + slippage);
  venta = apertura × (1 − slippage).
- Empate al final del calentamiento: la primera divergencia da BUY o
  SELL según el lado (regla simétrica).
- Media con math.fsum sobre la ventana: O(n·ventana), suficiente para
  el MVP; optimizar solo si un dataset real lo exige.

## D013 — Motor de backtesting
Estado: Aprobada (fracciones: recomendación aceptada por defecto;
revisar si se opera con activos indivisibles)

- Cantidades fraccionarias (float), como en spot de criptomonedas.
- Spot, solo largo: una posición abierta como máximo; BUY con
  posición o SELL sin posición se ignoran (log DEBUG).
- Por vela: ejecutar la orden pendiente a la apertura, valorar al
  cierre, dejar pendiente la nueva señal.
- La posición abierta al final no se cierra: se valora al último cierre.
- run_backtest valida cada vela por sí mismo (precios y volumen finitos,
  validate_candle de data.py): no depende de que vengan del cargador.
- T006 invierte todo el efectivo y no aplica costes; comisiones,
  slippage y límite de tamaño de posición llegan en T007.

## D014 — Costes y tamaño de posición
Estado: Aprobada (valores por defecto aprobados por el usuario)

Configuración en `BacktestConfig` (src/bottrading/config.py); valores
inválidos se rechazan al crearla.
- commission_rate = 0,001 (0,1 %, tarifa base spot de Binance) sobre
  el nominal de cada compra y venta.
- slippage_rate = 0,0005 (0,05 %), adverso: compra a apertura × (1 + s),
  venta a apertura × (1 − s).
- max_position_fraction = 1,0: fracción del efectivo usada por compra;
  la comisión está incluida en ella, así que el coste nunca supera el
  efectivo disponible.
- Cada Trade registra comisión y coste de slippage; el resultado expone
  total_fees y total_slippage.
- La curva de capital valora la posición al cierre sin descontar los
  costes de una venta futura.

## D015 — Métricas
Estado: Aprobada (propuesta aceptada por defecto por el usuario)

- total_return sobre el valor neto de liquidación (descuenta slippage
  y comisión de vender una posición abierta al último cierre). La
  curva de capital sigue siendo mark-to-market (final_equity_mtm).
- Anualización: año de 365 días (mercado 24/7). Velas por año =
  365 días / mediana del intervalo entre velas.
- annualized_return solo si el periodo cubre >= 365 días.
- volatility y sharpe: rendimientos por vela de la curva de capital,
  desviación típica muestral, anualizados con sqrt(velas por año);
  requieren >= 30 rendimientos. Tasa libre de riesgo anual
  configurable, 0 por defecto. Sin sharpe si la volatilidad es cero.
- max_drawdown sobre la curva mark-to-market.
- win_rate solo sobre idas y vueltas cerradas; PnL incluye costes.
- Referencia buy-and-hold: misma ejecución, costes y límite de
  posición (compra en la apertura de la segunda vela).
- Métrica no disponible = None, con la razón en `notes`.

## D016 — Informe reproducible y dataset de ejemplo
Estado: Aprobada (propuesta aceptada por defecto por el usuario)

- `python -m bottrading --csv <archivo>` escribe report.md, trades.csv
  y equity.csv en reports/<csv>_sma<fast>-<slow>/ (ignorado por Git).
- Reproducible byte a byte: sin fecha de ejecución; el informe cita el
  nombre y el SHA-256 del CSV, no su ruta, para que no cambie al mover
  el proyecto (T011). .gitattributes fija LF en los CSV para
  que el hash coincida entre sistemas.
- Costes ejecutados y costes estimados de liquidación se muestran por
  separado (recomendación de Codex en T008).
- Huecos entre velas: se cuentan los intervalos > 1.5 × mediana y se
  avisa en las notas y el informe; no se rechazan ni se rellenan.
- Dataset de ejemplo: examples/synthetic_daily.csv, 800 velas diarias
  SINTÉTICAS (paseo aleatorio geométrico, semilla 42), generado por
  examples/generate_synthetic.py. No son datos de mercado.
- Errores de configuración o de datos en la CLI: mensaje en stderr y
  código de salida 2, sin traza.

## D017 — Fase 2: búsqueda de ventaja con validación fuera de muestra
Estado: Aprobada por el usuario (2026-10-13); plan pendiente de
revisión de Codex.

- Objetivo del usuario: mejores resultados netos. Se acepta con una
  condición: toda mejora se mide fuera de la muestra usada para
  elegirla, con costes y frente a buy-and-hold.
- Se mantienen D001 y D006: sin órdenes reales ni claves API.
- Datos reales: CSV públicos de Binance descargados a mano por el
  usuario; no se versionan (data/ sigue ignorado).
- Acceso a red: solo el descargador de datos históricos públicos
  (D019, aprobado por el usuario) y, en el futuro, T019 (requiere otra
  aprobación específica).
- Riesgo asumido: aunque un resultado out-of-sample sea bueno, no
  garantiza rentabilidad futura; se informará siempre así.
- Tras la revisión de Codex: el walk-forward usado para elegir es
  validación, no prueba final. Un holdout final separado se abre una
  sola vez, cuando estrategias, rejilla y criterio estén fijados. El
  recuento de pruebas múltiples incluye estrategias y parámetros.
- La comisión de 0,1 % (D014) es un supuesto configurable; el coste
  real en Binance depende del tipo de cuenta y de orden.

## D018 — Importación de klines de Binance
Estado: Aprobada (diseño revisado por Codex en el plan de la fase 2)

- src/bottrading/binance.py lee ZIP (un único CSV dentro) o CSV
  extraído; sin red. CLI: `--binance <archivos o carpetas>`, excluyente
  con `--csv`.
- Columnas por posición: open_time, open, high, low, close, volume,
  close_time; las 5 restantes se ignoran. Se exigen 12 columnas.
- Unidad por magnitud: >= 1e14 µs, >= 1e11 ms, otro valor es error.
  Conversión exacta con enteros (sin coma flotante).
- Misma validación de velas que el cargador CSV (validate_candle);
  close_time > open_time; duplicados entre archivos con archivo:línea.
- `.CHECKSUM` junto al archivo: si existe y no coincide, error; si
  falta en un ZIP, aviso en el log y "sin .CHECKSUM" en el informe.
- La vela usa open_time como timestamp (inicio de la vela).

## D019 — Descargador de datos públicos de Binance
Estado: Aprobada por el usuario ("sí al script de descarga", 2026-10-13)

- src/bottrading/download.py es el ÚNICO módulo con acceso a red. Una
  guarda ESTÁTICA (prueba) falla si otro módulo importa librerías de
  red, el descargador o usa importación dinámica. No es un límite de
  seguridad: no cubre todas las formas posibles de acceder a la red.
- Solo GET HTTPS a data.binance.vision/data/spot/monthly/klines/...
  (URL base fija). Las redirecciones solo se siguen si el destino es
  HTTPS en data.binance.vision (puerto 443, sin credenciales en el
  URL); la URL final de la respuesta se vuelve a comprobar. Sin cuenta,
  claves API ni órdenes.
- Cada ZIP se verifica con su .CHECKSUM antes de guardarse; si no
  coincide, no se guarda y el proceso termina con error. Escritura
  atómica (.part + rename). Archivos ya verificados no se vuelven a
  descargar. Pausa de 0,2 s entre meses.
- Solo meses cerrados. Meses inexistentes (404) se informan como
  "no disponible", sin error.
- Destino por defecto data/<SYMBOL>-<interval>/ (ignorado por Git).
- Las pruebas usan un servidor falso en memoria: ninguna usa la red.

## D020 — Particiones temporales (walk-forward + holdout final)
Estado: Aprobada (diseño propuesto por Codex en la revisión del plan)

- src/bottrading/splits.py. Las particiones dependen solo de las fechas.
- Holdout final: último 20 % de las velas. Si dura < 365 días se marca
  como no anualizable (sin métricas anualizadas del holdout).
- N ventanas de validación consecutivas de M meses de calendario que
  terminan justo antes del holdout (se valida con lo más reciente).
  Ajuste de cada ventana: todas las velas anteriores (crece). Error si
  el ajuste inicial cubre menos de los meses exigidos.
- Esquemas: DAILY = 24 meses de ajuste mínimo + 5 × 6 meses;
  HOURLY = 6 meses + 5 × 1 mes.
- evaluate_segment: señales calculadas con todo el historial hasta el
  fin del segmento (calentamiento causal) y recortadas.
- Herencia de posición (tras la revisión de Codex de T014, fijada antes
  de ver resultados): cada tramo hereda la posición que la estrategia
  tendría al llegar a él. Si su última señal anterior al tramo es BUY,
  compra a la apertura de la primera vela del tramo, pagando costes;
  si es SELL o no hay, empieza sin posición. Buy-and-hold sigue la
  misma regla, así que ambos entran a la vez. El modo sin herencia
  existe (inherit_position=False) pero no se usa para comparar.
- plan_splits rechaza fechas no ordenadas estrictamente.
- Datos reales BTCUSDT 1d (2020-01-01 a 2026-09-30, plan calculado sin
  backtests): validaciones del 2022-11-26 al 2025-05-25; holdout del
  2025-05-26 al 2026-09-30 (493 velas, anualizable).

## D021 — Estrategias adicionales y criterio de selección
Estado: Aprobada por el usuario (2026-10-13), fijada ANTES de ver
resultados con datos reales.

Estrategias (src/bottrading/strategy.py), todas causales y con la misma
interfaz (cierres -> una señal por vela):
- Cruce de medias (D012): fast < slow.
- Filtro de tendencia: cierre frente a su media de N velas; equivale a
  crossover_signals(closes, 1, N), con la misma regla de empates.
- Ruptura de canal (Donchian) sobre CIERRES: BUY si el cierre supera el
  máximo de los N cierres anteriores; SELL si cae bajo el mínimo de los
  M anteriores; cada condición con su propio calentamiento (corregido
  tras la revisión de Codex). Usa cierres porque la interfaz de señales
  solo recibe cierres; no es el Donchian clásico de máximos y mínimos.

Criterio de selección para T016 (fijado de antemano): para cada
combinación (estrategia × parámetros), mediana del Sharpe de las 5
ventanas de validación; gana la mediana más alta; desempate por menor
mediana de drawdown máximo. Si el Sharpe de una ventana no está
disponible (p. ej. volatilidad cero: todo el tramo en efectivo), cuenta
como 0. Si la ganadora tiene mediana <= 0, el informe dirá que ninguna
combinación mostró ventaja en validación (observación de Codex: el 0 de
quedarse en efectivo no demuestra ventaja). Se publican los resultados
de cada ventana, no solo la mediana.

Rejillas (registradas antes de ejecutar; 22 combinaciones en total):
- Cruce: fast {10, 20, 50} × slow {50, 100, 200}, fast < slow (8).
- Filtro de tendencia: N {20, 50, 100, 150, 200} (5).
- Donchian: entrada {20, 55, 100} × salida {10, 20, 50} (9).
Costes por defecto de D014; capital 10 000; posición 100 %.

## D022 — Selección congelada antes de abrir el holdout
Estado: Registrada (T016, 2026-10-13). NO se modifica tras ver el holdout.

- Ejecución: `python -m bottrading.walkforward --binance data/BTCUSDT-1d
  --scheme daily` (costes D014, capital 10 000). Solo ventanas de
  validación 2022-11-26 a 2025-05-25; holdout 2025-05-26 a 2026-09-30
  sin usar. Informe: reports/seleccion_BTCUSDT-1d/ (SHA-256 selection.md
  be1dc696..., trials.csv a24b3cdf...; reproducible; incluye volatilidad
  y retorno por ventana tras la revisión de Codex).
- Elegida por el criterio de D021: **trend_filter(window=50)**, mediana
  del Sharpe 2,26 (por ventana 2,34 / 2,44 / 2,26 / 1,23 / 1,22), mediana
  de drawdown 15,2 %. Buy-and-hold: mediana del Sharpe 1,96, drawdown
  20,1 %. 22 combinaciones probadas; solo 4 superan la mediana del
  Sharpe de buy-and-hold.
- Lectura honesta: la elegida ganó MENOS que buy-and-hold en las 5
  ventanas (retorno +51,8 / +40,0 / +62,3 / +19,0 / +16,0 % frente a
  +59,8 / +42,3 / +82,9 / +33,8 / +16,8 %). Su ventaja es de riesgo:
  mediana de volatilidad anualizada 35,6 % frente a 48,8 % y mediana de
  drawdown 15,2 % frente a 20,1 %; no de ganancia. Validación en un
  periodo mayoritariamente alcista de BTC.
- T017 evaluará en el holdout, UNA sola vez, solo la elegida y
  buy-and-hold (más su sensibilidad a costes). No se evaluarán las
  otras 21 combinaciones en el holdout, para no volver a elegir.

## D023 — Protocolo del holdout final (registrado ANTES de abrirlo)
Estado: Aprobada por el usuario ("abre el holdout"); fijada tras la
revisión de Codex de T016 y antes de ejecutar nada sobre el holdout.

Qué se evalúa (una sola vez):
- trend_filter(window=50) (D022) y buy-and-hold, en el holdout
  2025-05-26 a 2026-09-30, con evaluate_segment (calentamiento con todo
  el historial previo y herencia de posición, D020). Capital 10 000,
  posición 100 %, tasa libre de riesgo 0.
- Ninguna otra combinación se evalúa en el holdout.

Escenarios de costes (iguales para estrategia y buy-and-hold):
- sin costes: comisión 0, slippage 0 (solo referencia).
- bajo: comisión 0,075 %, slippage 0,02 %.
- base: comisión 0,1 %, slippage 0,05 % (D014; resultado principal).
- alto: comisión 0,2 %, slippage 0,1 %.

Interpretación fijada de antemano (escenario base salvo que se diga):
- "Gana más que buy-and-hold" si su retorno total neto es mayor.
- "Mejor ajustada al riesgo" si su Sharpe es mayor.
- "Menor riesgo" si su drawdown máximo y su volatilidad son menores.
- "Robusta a costes" si la comparación de retorno con buy-and-hold
  tiene el mismo signo en los escenarios bajo, base y alto.
- Sea cual sea el resultado: un holdout de 16 meses de un solo activo
  no demuestra una ventaja estadística; se publica tal cual. No se
  cambiará estrategia, parámetros ni criterio a la vista del holdout;
  una nueva evaluación exigirá datos nuevos (meses posteriores a
  2026-09) como nuevo holdout.

## D024 — Resultado del holdout final (abierto una vez, 2026-10-13)
Estado: Registrado. No se modifica la estrategia a la vista de este
resultado (D023).

- Comando: `python -m bottrading.holdout --binance data/BTCUSDT-1d
  --candidate trend_filter:window=50 --open-holdout`, con el código del
  commit 45afaa9 (publicado antes de ejecutar). Salida en
  reports/holdout_BTCUSDT-1d/ (SHA-256 holdout.md ba3781c0...,
  trades.csv 5cd321c2..., equity.csv 98b91cf2...).
- Holdout 2025-05-26 a 2026-09-30 (493 velas diarias), escenario base:
  estrategia +4,48 % neto (anualizado +3,30 %), buy-and-hold -23,51 %
  (anualizado -18,03 %). Drawdown 26,2 % frente a 53,0 %; volatilidad
  25,4 % frente a 41,5 %; Sharpe 0,25 frente a -0,27. 35 operaciones,
  17,6 % de idas y vueltas ganadoras, costes ejecutados 464,58.
- Reglas de D023: gana más que buy-and-hold: sí; mejor Sharpe: sí;
  menor riesgo: sí; robusta a costes (bajo/base/alto): sí.
- Sensibilidad: sin costes +10,27 %; bajo +6,57 %; base +4,48 %;
  alto -1,02 % (la diferencia con buy-and-hold sigue siendo positiva).
- Lectura honesta: el holdout fue un periodo bajista de BTC. La
  estrategia ganó a buy-and-hold sobre todo por estar fuera del mercado
  en las caídas, como cabe esperar de un filtro de tendencia; en la
  validación alcista (D022) ganó menos que buy-and-hold. Es un cambio de
  rentabilidad por protección que depende del régimen, no una máquina de
  ganancias. Su ganancia absoluta (+3,3 % anual) es pequeña y los costes
  se comen más de la mitad de la ganancia bruta. Un holdout de un solo
  activo no demuestra ventaja estadística.

## Pendientes de decisión
- Ninguna abierta para el MVP.
- Ninguna abierta para la fase 2 (particiones fijadas en D020).
