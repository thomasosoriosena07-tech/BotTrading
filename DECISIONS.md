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

## Pendientes de decisión
- Precio de ejecución: apertura de la vela siguiente + slippage.
- ¿Detectar huecos entre velas (intervalo irregular)?
- Factor de anualización del Sharpe.
- Unidades fraccionarias permitidas o no.