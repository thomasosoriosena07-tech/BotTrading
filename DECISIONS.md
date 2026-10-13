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

## Pendientes de decisión
- Precio de ejecución: apertura de la vela siguiente + slippage.
- Detección de velas incompletas en CSV.
- Fechas sin zona horaria: rechazar o asumir UTC.
- Factor de anualización del Sharpe.
- Unidades fraccionarias permitidas o no.