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

## Pendientes de decisión
- ¿Detectar huecos entre velas (intervalo irregular)? Afecta a la
  estimación de velas por año si los huecos son frecuentes.
