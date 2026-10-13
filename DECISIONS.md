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
- Ninguna otra combinación se evalúa en el holdout. Tras la revisión
  de Codex de T018, la CLI lo impone: solo acepta trend_filter(window=50),
  esquema diario y capital 10 000 (no hay opciones para cambiarlos).

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

## D025 — Protocolo de comprobación en otros activos (registrado ANTES)
Estado: Aprobada por el usuario ("tomo tu recomendación de la 2",
2026-10-13). Registrada y publicada antes de descargar ETH/SOL y de
ejecutar nada con ellos.

- Estrategia congelada: trend_filter(window=50) (D022), sin cambios.
  Referencia: buy-and-hold. Costes base (D014), capital 10 000.
- Activos: ETHUSDT y SOLUSDT (klines diarios públicos, D019), y
  BTCUSDT como CONTROL: sus resultados por tramo deben coincidir con
  D022 (validación) y D024 (holdout); si no, la herramienta está mal y
  el resto no se interpreta.
- Tramos: las mismas fechas de BTC (V1-V5 y holdout, D020); cada tramo
  con calentamiento causal y herencia de posición (D020). Se exigen
  velas diarias completas en cada tramo y >= 50 velas previas.
- Reglas por activo (src/bottrading/crossasset.py):
  - Protección: menor drawdown que buy-and-hold en >= 4 de 6 tramos.
  - Ventaja bajista: gana a buy-and-hold en TODOS los tramos bajistas
    (tramo bajista = buy-and-hold pierde en él); n/d si no hay.
  - Retraso alcista (informativo): tramos alcistas en que gana menos.
  - "Se repite el patrón de BTC" = protección y no fallar la ventaja
    bajista.
- Interpretación fijada: aunque se repita, son activos correlacionados
  con BTC en los mismos periodos; no es una prueba independiente ni
  demuestra una ventaja. Si no se repite, se publica igual y NO se
  ajusta la estrategia para que se repita.

## D026 — Resultado de la comprobación en otros activos (T020)
Estado: Registrado tal cual (protocolo D025, ejecutado una vez con el
código publicado en d840d76).

- Comando: `python -m bottrading.crossasset --asset data/BTCUSDT-1d
  --asset data/ETHUSDT-1d --asset data/SOLUSDT-1d`. Salida en
  reports/crossasset/ (SHA-256 crossasset.md fe3bfb22...,
  segments.csv 1963eed0...). Datos: ETH 81 meses, SOL 74 (cotiza desde
  2020-08), todos con checksum verificado.
- Control BTC: coincide con D022 (retornos y Sharpe por ventana) y con
  D024 (holdout +4,48 % frente a -23,51 %). La herramienta es fiable.
- Reglas de D025: el patrón se repite en BTC, ETH y SOL.
  - BTC: menor drawdown 6/6; gana en el único tramo bajista; se queda
    atrás en los 5 alcistas.
  - ETH: menor drawdown 6/6; gana en los 2 bajistas (V4 -0,2 % frente
    a -9,2 %; V5 +20,2 % frente a -25,5 %) y en el holdout (+94,3 %
    frente a +5,0 %, con drawdown 29,8 % frente a 67,6 %); atrás en 3.
  - SOL: menor drawdown solo 4/6 (justo el mínimo); gana en los 2
    bajistas pero en el holdout PIERDE dinero (-22,2 % frente a -33,0 %,
    Sharpe peor); en V4 -5,4 % frente a +38,7 %.
- Lectura honesta: el rasgo que se repite es la PROTECCIÓN (menor
  drawdown en 16 de 18 tramos) y ganar en tramos bajistas. En retorno
  supera a buy-and-hold solo en 6 de 18 tramos y queda atrás en 12. No
  es una prueba independiente (activos correlacionados, mismos
  periodos) ni demuestra una ventaja. No se ajusta nada a la vista de
  estos resultados.

## D027 — Protocolo del paper trading (T019, registrado ANTES de empezar)
Estado: Aprobada por el usuario ("sí al alcance de red de T019",
2026-10-13). Publicada antes de descargar datos diarios o simular nada.

Alcance de red (amplía D019 sin servidores nuevos):
- download.py podrá descargar también archivos DIARIOS públicos:
  https://data.binance.vision/data/spot/daily/klines/<SYM>/1d/... con su
  .CHECKSUM. Mismo host, mismas protecciones (HTTPS, redirecciones
  restringidas, checksum antes de escribir). Solo días cerrados.
- Sin API, sin claves, sin cuenta, sin órdenes. El simulador de paper
  trading NO accede a la red (la guarda estática de D019 se mantiene).

Qué se simula:
- trend_filter(window=50) congelada (D022), en BTCUSDT, ETHUSDT y
  SOLUSDT, frente a buy-and-hold; costes base (D014); capital 10 000
  por activo; velas diarias.
- Inicio: 2026-10-01 (primer día posterior al holdout). Historial hasta
  2026-09-30 de los archivos mensuales (solo calentamiento y herencia de
  posición, D020); desde 2026-10-01, solo archivos diarios. Se exigen
  todos los días, sin huecos.
- Diario de operaciones versionado en paper/ (no ignorado por Git). Cada
  ejecución recalcula todo de forma determinista y DEBE reproducir las
  filas ya registradas: si alguna cambia, error (diario solo de
  añadir). El historial de Git sirve de sello de tiempo.

Evaluación fijada de antemano:
- Puntos de control: 2027-03-31 (6 meses, preliminar) y 2027-09-30
  (12 meses, principal).
- En cada punto y activo: reglas de D023 (gana más que buy-and-hold,
  mejor Sharpe, menor riesgo) y protección (menor drawdown).
- Sin cambios de estrategia, parámetros ni costes durante la prueba. Un
  resultado malo se publica igual. Un año de un solo periodo sigue sin
  demostrar una ventaja estadística.

## D028 — Automatización diaria del paper trading
Estado: Aprobada por el usuario ("quisiera que fuera automático",
2026-10-13). Excepción explícita y acotada a la regla de AGENTS.md de no
hacer commits automáticos.

- scripts/paper_daily.ps1, ejecutado por el Programador de tareas de
  Windows ("BotTrading paper trading") cada día a las 08:00 hora local
  (UTC-5; el día UTC cierra a las 19:00 locales), o al encender el equipo
  si estaba apagado.
- Pasos: descarga de días cerrados (D027) -> `python -m bottrading.paper`
  -> comprobación de seguridad -> si paper/ cambió: commit SOLO de
  paper/ ("paper: datos hasta <día> (automatico, D028)") -> push normal
  a origin/main de lo pendiente. Nunca --force; nunca otros archivos.
- Comprobación de seguridad antes del commit (revisión de Codex): la
  rama debe ser main y todos los commits pendientes de publicar
  (origin/main..HEAD) deben ser automáticos (ese mensaje y solo
  archivos de paper/, sin merges) y la diferencia acumulada
  origin/main..HEAD solo puede tocar paper/ (cubre merges, revisión de
  Codex). Si no, el script se detiene sin hacer commit, para no publicar
  trabajo ajeno.
- Publicación con SHA fijado (revisión de Codex, carrera con otros
  procesos): tras el commit se fija el SHA, se revalida origin/main..SHA
  y se publica exactamente ese SHA (`git push origin <SHA>:refs/heads/main`).
  Un commit que otro proceso añada después no se publica; uno que se
  cuele por debajo hace fallar la validación.
- Pruebas: scripts/test_paper_daily_guard.ps1 (16 casos en un
  repositorio temporal con remoto local, incluidos merge y carrera). Códigos de
  `git diff --cached` distintos de 0 y 1 se tratan como error.
- Si falla un paso ANTERIOR al commit (día aún no publicado, datos con
  huecos, error de integridad, comprobación de seguridad), no hay
  commit. Si falla el PUSH, el commit automático queda local y se
  publica en la ejecución siguiente (la comprobación lo admite por ser
  automático). Errores en reports/automation/paper_<fecha>.log (ignorado
  por Git).
- Integridad del diario reforzada (revisión de Codex de T019):
  paper/ledger.state ancla último día, número de filas y SHA-256 del
  diario. Detecta truncamientos, ediciones, borrado del diario o del
  ancla, retrocesos de datos y filas nuevas con fecha ya simulada. Un
  diario existente sin ancla solo se ancla con --init-anchor si se
  reproduce exactamente (--init-anchor falla si no hay diario o ya tiene
  ancla).
- Límite reconocido: el ancla no está firmada; quien modifique a la vez
  datos, diario y ancla fuera de Git puede eludirla. La trazabilidad
  externa es el historial de Git en GitHub (un commit por día).
- Para pararlo: deshabilitar o borrar la tarea programada.

## D029 — Panel HTML del paper trading
Estado: Aprobada por el usuario ("sí, prepáralo", 2026-10-13).

- src/bottrading/dashboard.py genera paper/dashboard.html en cada
  ejecución de `python -m bottrading.paper` (y por tanto cada día con la
  tarea de D028, que lo versiona con el resto de paper/).
- Página autónoma: CSS y gráficos SVG en línea, sin scripts ni recursos
  externos (una prueba lo exige); modo claro y oscuro. Sin fecha de
  generación: reproducible byte a byte.
- Contenido: fecha de datos, días simulados, próximo punto de control;
  por activo, posición (dentro/fuera), retorno de estrategia y de
  buy-and-hold, caídas máximas, operaciones y curva de capital; tabla
  de operaciones simuladas; puntos de control cuando se alcancen.
- Actualización diaria (velas cerradas), no en tiempo real.

## D030 — Integración futura con Binance Spot Demo Mode (T021)
Estado: (a) lectura de la cuenta demo APROBADA por el usuario ("apruebo",
2026-10-13, tras revisar el plan v3 y la revisión de Codex). (b) envío de
órdenes demo NO aprobado: requiere una aprobación posterior y separada,
antes de F4. Ninguna configuración, flag ni variable amplía este alcance.

Qué cambia y qué no:
- Excepción acotada a D006 y a PROJECT_SPEC ("claves API"): solo claves
  de una cuenta Binance DEMO, creadas y guardadas por el usuario. Los
  agentes nunca las solicitan, ven, escriben ni imprimen.
- Producción sigue prohibida: no existirá ejecutor, host ni código para
  ella. Pasar a dinero real sería otra decisión de alcance.
- T019/D027 no cambia: paper/ sigue siendo la evaluación oficial, el
  simulador paper sigue sin red y la estrategia queda congelada
  (FROZEN_CANDIDATE, trend_filter 50, costes D014). Toda variante que se
  evaluara en demo se registraría aquí; no hay ninguna.
- Demo valida ejecución y reconciliación, NO rentabilidad. La propia
  documentación de Binance dice que sus precios son "realistas", no
  reales, y que lo que funciona en demo puede no funcionar en vivo.

Documentación oficial consultada (2026-10-13, developers.binance.com/docs/
binance-spot-api-docs: demo-mode/general-info, rest-api/request-security,
rest-api/trading-endpoints, rest-api/account-endpoints,
rest-api/general-api-information, errors, filters):
- Demo Mode disponible desde 2026-01-29. REST: https://demo-api.binance.com/api.
  Mismas funciones, límites de peticiones y filtros que el exchange real;
  saldo reiniciable desde la web; durante el mantenimiento no se pueden
  crear ni cancelar órdenes. Claves en demo.binance.com (API Management).
- Tipos de clave: HMAC, RSA y Ed25519. Se usará HMAC-SHA256 porque basta
  la biblioteca estándar (hmac); Ed25519 exigiría una dependencia.
  Vector oficial para las pruebas: payload
  "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
  -> c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71
  (con el secretKey de ejemplo de la documentación).
- recvWindow por defecto 5000 ms, máximo 60000; se usará <= 5000.
- newClientOrderId es "único entre las órdenes ABIERTAS" y un id repetido
  "solo se acepta cuando la anterior está llena". Consecuencia: en órdenes
  MARKET (que se llenan al instante) el servidor NO impide un duplicado
  con el mismo id. La deduplicación depende de la consulta previa y del
  ledger privado, no del servidor.
- El formato del id solo está documentado para FIX: ^[a-zA-Z0-9-_]{1,36}$.
  Se adopta ese formato, más restrictivo, también para REST.
- 5XX y -1007: estado de ejecución DESCONOCIDO; se consulta antes de
  cualquier otra acción. 429 y 418 traen Retry-After. -2010 "Duplicate
  order sent." indica un id en uso; -2013 indica que la orden no existe.
- allOrders y myTrades: límite de 1000 por página y ventana máxima de
  24 h entre startTime y endTime; se paginan con orderId y fromId.
  myTrades devuelve commission y commissionAsset por operación.
- Filtros de órdenes MARKET: MARKET_LOT_SIZE y LOT_SIZE (minQty, maxQty,
  stepSize) y NOTIONAL/MIN_NOTIONAL según applyMinToMarket/applyToMarket,
  con un precio estimado por avgPriceMins.
- No documentado y, por tanto, tratado como desconocido (diseño
  conservador): comisiones de demo, si una orden MARKET puede quedar en
  EXPIRED con llenado parcial, y el comportamiento de MARKET_LOT_SIZE
  con stepSize=0.

1. Barrera contra producción
- Cada petición pasa por una tabla cerrada en código: (método, ruta) ->
  parámetros obligatorios, parámetros opcionales y el patrón de cada
  valor. Entradas: GET /api/v3/time, GET /api/v3/exchangeInfo,
  GET /api/v3/account, GET /api/v3/order, GET /api/v3/openOrders,
  GET /api/v3/allOrders, GET /api/v3/myTrades y GET /api/v3/ticker/bookTicker.
  POST y DELETE /api/v3/order solo se añaden con la aprobación (b).
- La validación se hace sobre la petición ya construida y firmada: el
  esquema debe ser https, el host exactamente demo-api.binance.com y el
  puerto 443 o ninguno; sin userinfo ni fragmento; la ruta, sin
  codificación "%", debe estar en la tabla con su método. La query se
  analiza con parse_qsl estricto: no se admiten claves duplicadas ni
  claves fuera del esquema, y signature va siempre al final y debe ser
  hexadecimal de 64 caracteres. Si algo falla, se lanza un error ANTES
  de llamar al transporte.
- El host y la tabla son constantes; no se leen de config, CLI ni
  entorno. El opener usa ProxyHandler({}), con lo que se ignoran
  HTTPS_PROXY, HTTP_PROXY y ALL_PROXY, y rechaza cualquier 3xx. El URL
  final de la respuesta se recomprueba.
- La guarda estática (D019) se amplía a exactamente dos módulos con red
  (download.py y demo_client.py) y un test estático rechaza hosts de
  producción en src/. Ambas son defensa adicional, no aislamiento.
- --send-orders y BOTTRADING_DEMO_ORDERS=1 solo eligen entre dry-run y
  envío dentro de demo, y solo existirán tras la aprobación (b).
- Pruebas (transporte simulado que falla si se le llama): hosts de
  producción (api.binance.com, api1-4, api-gcp, testnet), mayúsculas,
  punto final, IP, puerto, userinfo, ruta codificada, ruta o método no
  permitido, parámetro extra, parámetro duplicado, query alterada
  después de firmar, signature con formato inválido, variables de proxy
  definidas, 301/302/307 hacia producción y configuración vacía o
  malformada.

2. Límites operativos (fijos; solo se cambian con nueva aprobación)
- Símbolos: BTCUSDT, ETHUSDT y SOLUSDT. Solo MARKET, solo BUY y SELL.
- Capital ficticio: 1000 USDT por activo (3000 en total), llevado como
  efectivo propio de cada activo en el ledger privado, como en paper.
- BUY: quoteOrderQty = efectivo del activo en el ledger, con un máximo
  de 1500 USDT por orden. SELL: exactamente la cantidad poseída según el
  ledger, redondeada hacia abajo a stepSize, y nunca más que el saldo
  real.
- Como máximo 1 orden por símbolo y día, y 3 órdenes por día en total.
  Exposición acumulada (valor de las posiciones a precio de referencia
  más órdenes en curso) no mayor que 4500 USDT.
- Al alcanzar un límite no se reduce la orden: se registra
  LIMIT_BLOCKED, no se envía nada ese día y se avisa en el log.
- Pruebas justo por debajo, en el límite y por encima, para cada límite.

3. Cuenta y reconciliación
- Cuenta demo DEDICADA, sin operaciones manuales ni otros bots. Lo
  garantiza el usuario. Reiniciar el saldo desde la web cuenta como
  actividad externa.
- Línea base en el primer arranque autorizado: saldos de todos los
  activos con saldo distinto de cero, cero órdenes abiertas y, para cada
  símbolo, allOrders (limit=1000) debe devolver menos de 1000 órdenes;
  se guarda el orderId máximo visto.
- Saldo esperado = línea base + efecto de cada operación propia según
  myTrades (cantidad, precio, commission y commissionAsset, sea cual sea
  el activo de la comisión, incluido BNB).
- Cobertura demostrable: en cada arranque se paginan allOrders y
  myTrades desde el último id conocido hasta recibir una página con
  menos elementos que el límite. Si una página falla, se trunca o hay
  ids no contiguos con el ledger, la reconciliación es INCOMPLETA: el
  proceso se detiene sin enviar.
- Toda orden con prefijo bt- que no esté en el ledger, toda orden ajena
  y toda diferencia de saldo fuera de la tolerancia (2 x stepSize en el
  activo base y 0,01 USDT) detienen el proceso.
- El bot no corrige nada por su cuenta. El usuario investiga, se
  registra el incidente en TASKS.md y una nueva línea base solo se fija
  con --rebaseline, aprobado explícitamente y registrado como evento.

4. Órdenes parciales y remanentes
- Tras cada orden se consultan su estado final, openOrders y myTrades.
- No se envía nada para un símbolo mientras haya una orden abierta o su
  última orden no esté en estado final (FILLED, CANCELED, EXPIRED,
  REJECTED). Un remanente abierto se cancela por origClientOrderId (solo
  si es del bot), se espera a confirmar el estado final y se adopta la
  cantidad ejecutada real.
- Pruebas: llenado parcial seguido de desconexión; reinicio con
  remanente abierto; cancelación que falla; EXPIRED con llenado
  parcial; señal contraria al día siguiente de un llenado parcial.

5. Deduplicación, persistencia y adjudicación manual
- clientOrderId = bt-<SÍMBOLO>-<AAAAMMDD de la señal>-<B|S>, siempre
  dentro de ^[a-zA-Z0-9-_]{1,36}$. Una intención tiene un solo id.
- Ledger privado de órdenes con ancla (hash, filas y último estado). Los
  estados INTENT -> SENT -> ACK|UNKNOWN -> FINAL se escriben de forma
  atómica ANTES de cada paso de red.
- Antes de cualquier POST, el id se consulta (GET order) además de
  revisar el ledger. Como el servidor acepta ids repetidos si la orden
  anterior está llena, la consulta es obligatoria.
- Timeout, 5XX, -1007 o un corte tras el POST pasan a UNKNOWN. Se hacen
  como máximo 5 consultas con 2 s de espera, y se exigen 3 respuestas
  consecutivas coherentes. Si la orden no aparece o las respuestas no
  coinciden, se detiene el día sin reenviar.
- Una respuesta que llegue tarde no cambia el estado: solo las
  consultas lo cambian. "Duplicate order sent." se trata como "la orden
  ya existe" y se consulta. Nunca se genera un id alternativo de forma
  automática.
- Si el ledger se pierde o su ancla no coincide, el proceso se detiene.
  --rebuild-from-exchange reconstruye desde allOrders y myTrades y
  muestra el resultado para que el usuario lo apruebe.
- Adjudicación manual de un INTENT o SENT cuya orden no aparece:
  --adjudicate <id> --not-sent solo se acepta si hay cobertura completa
  (punto 3) y 3 consultas coherentes de "no existe". Añade el evento
  ADJUDICATED_NOT_SENT con la aprobación del usuario, sin borrar el
  historial. Las señales de la estrategia son cruces, no estados, así
  que la señal perdida no se repite: la posición objetivo se toma de la
  simulación local (LocalExecutor) y cualquier orden de alineación usa
  un id nuevo con sufijo -R<n>, también con aprobación explícita. Nunca
  se convierte en un reintento automático.
- "Repetir envía 0" significa repetir la MISMA intención (mismo día y
  mismo clientOrderId). Una prueba lo verifica.

6. Secretos
- Almacenamiento: el Administrador de credenciales de Windows (credencial
  genérica "BotTrading-Demo", protegida por DPAPI con el usuario de
  Windows). La crea el usuario con
  `cmdkey /generic:BotTrading-Demo /user:bottrading /pass` y pega
  "APIKEY:SECRET" cuando se le pide, así que la clave no queda en el
  historial de la consola. No se usan .env ni variables de entorno.
- Lectura con ctypes (CredReadW, biblioteca estándar) solo en el momento
  de firmar. La clave no se pasa como argumento ni a procesos hijos, no
  se escribe en archivos temporales y no figura en ningún repr. En los
  tests se usa un lector falso inyectado.
- La tarea programada corre como el mismo usuario (thoma, logon
  interactivo, nivel limitado; comprobado el 2026-10-13), por lo que
  puede leer la credencial. Se verifica en F3 desde la propia tarea.
- Ni los logs ni las excepciones muestran cabeceras, query firmada ni
  cuerpo: solo método, ruta sin query, código HTTP y código de Binance.
  Prueba con claves falsas sobre caplog, str/repr de las excepciones,
  archivos de salida y salida de la tarea.
- Si una clave se filtra, se revoca en Binance; reescribir git no basta.

7. Publicación automática
- Estado privado FUERA del repositorio, en %LOCALAPPDATA%\BotTrading\demo\
  (ledger de órdenes, respuestas crudas, logs del cliente y archivo STOP
  del kill switch).
- paper/ no recibe nada de demo. Lista cerrada de rutas por publicador:
  paper (paper/ledger.csv, paper/ledger.state, paper/report.md,
  paper/equity.csv, paper/dashboard.html) y demo (demo/summary.csv,
  demo/report.md, demo/dashboard.html). La guarda de D028 se endurece:
  ni merges ni archivos fuera de la lista en ningún commit de
  origin/main..SHA ni en la diferencia acumulada.
- Contenido con esquema cerrado: demo/summary.csv tiene columnas fijas y
  cada valor debe cumplir su patrón (fecha ISO, símbolo de la lista,
  B/S, estado de la lista, decimales con formato fijo). report.md y
  dashboard.html se generan solo a partir de summary.csv ya validado,
  sin texto libre.
- Antes del push se vuelve a validar el contenido FINAL del SHA fijado
  (git show SHA:ruta) contra su esquema. Si algo falla, se aborta. La
  búsqueda de patrones de clave es solo defensa adicional.
- Nunca se publican orderId, ids de cuenta, saldos totales, respuestas
  crudas, cabeceras ni URLs.

8. Protección de T019 durante la implementación
- paper.py no se modifica. Los tests escriben solo en tmp_path; el test
  de paridad del LocalExecutor usa una copia de paper/ en un directorio
  temporal; una fixture bloquea sockets en los tests de backtest y paper.
- Comprobación de hashes de paper/ antes y después de la suite, con la
  tarea D028 deshabilitada mientras dura o fuera de la ventana de las
  08:00.
- El endurecimiento de la guarda (punto 7) debe pasar los 16 casos
  actuales de scripts/test_paper_daily_guard.ps1 y aceptar los 5
  archivos legítimos de paper/.

Fases (T021)
- F0: este documento. Aceptación: aprobación (a) del usuario (dada) y
  revisión de Codex.
- F1: sin red. Intención de orden, LocalExecutor y escritor de demo en
  un módulo nuevo (punto 8).
- F2a: sin red. Transporte, tabla de peticiones, proxies, redirecciones,
  firma, credenciales y redacción (puntos 1 y 6).
- F2b: sin red. Máquina de estados, ledger privado, reconciliación,
  remanentes, deduplicación, adjudicación y guarda de publicación
  (puntos 2 a 5 y 7).
- F3: primera red, SOLO LECTURA. El usuario crea la cuenta dedicada y la
  credencial; --check manual y desde la tarea programada; línea base.
- F4: solo tras la aprobación (b). Código de envío revisado por Codex;
  una orden manual; repetirla envía 0.
- F5: tarea separada a las 00:05 UTC; métricas por separado (precio
  previsto y ejecutado, latencia, spread, slippage frente al 0,05 % de
  D014, comisión real frente al 0,1 %, llenados parciales, rechazos).
  Aceptación: 30 días sin discrepancias ni duplicados. Mide operación,
  no rentabilidad.
- F6: informe de ejecución frente a D014. Ninguna fase lleva a
  producción.

## Pendientes de decisión
- Ninguna abierta para el MVP.
- Ninguna abierta para la fase 2 (particiones fijadas en D020).
