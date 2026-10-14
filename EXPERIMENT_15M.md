# EXPERIMENT_15M.md

## 1. Información general

- **Proyecto:** BotTrading
- **Experimento:** EXP-15M-001
- **Estado:** PLANNING
- **Mercado:** Binance Spot
- **Activo inicial:** BTCUSDT
- **Temporalidad candidata:** 15 minutos
- **Apalancamiento:** No permitido
- **Entorno inicial:** Backtesting histórico
- **Entorno posterior:** Binance Spot Demo, previa aprobación
- **Responsable de implementación:** Claude Code
- **Responsable de revisión independiente:** OpenAI Codex
- **Responsable de decisiones y aprobación:** Usuario
- **Documento de referencia:** Este archivo
- **Baseline:** Estrategia diaria existente, que debe permanecer intacta

Este documento define el protocolo experimental. Ningún agente puede cambiar silenciosamente las reglas, los criterios de aceptación o las restricciones de seguridad.

## 2. Objetivo

Investigar si una estrategia de trading Spot basada en velas de 15 minutos puede generar una ventaja neta suficientemente robusta después de costes, sin asumir apalancamiento ni comprometer capital real.

El objetivo no es maximizar el número de operaciones, es encontrar la mayor rentabilidad neta fuera de muestra (decisión del usuario, A.12-1).

Se busca evaluar el equilibrio entre:

- Frecuencia de oportunidades.
- Rentabilidad neta.
- Costes de transacción.
- Drawdown y riesgo de pérdidas.
- Estabilidad fuera de muestra.
- Robustez ante diferentes condiciones de mercado.
- Fiabilidad de la implementación.

El resultado del experimento puede ser positivo, negativo o inconcluso. No se garantiza rentabilidad.

## 3. Hipótesis experimental

### Hipótesis principal

Existe la posibilidad de que una estrategia intradía sencilla, con reglas explícitas y costes realistas, obtenga resultados netos competitivos frente a las alternativas de referencia.

Esta hipótesis debe ser contrastada, no asumida como verdadera.

### Hipótesis secundaria

Un aumento de la frecuencia de operaciones solo es útil si la ventaja neta compensa las comisiones, el spread, el deslizamiento y el riesgo adicional.

### Hipótesis nula operativa

Si la estrategia no muestra resultados netos suficientemente sólidos, estables y reproducibles fuera de muestra, no se considerará validada y no avanzará a ejecución demo automática.

## 4. Baseline inmutable

La estrategia original se conserva como referencia.

Según la auditoría inicial, su configuración es:

- Estrategia: `trend_filter(window=50)`.
- Temporalidad: diaria.
- Activos: BTCUSDT, ETHUSDT y SOLUSDT.
- Señales basadas en velas diarias cerradas.
- Ejecución Spot, sin apalancamiento.

Esta descripción es provisional hasta comprobarla en el código actual.

### Reglas del baseline

1. No modificar la lógica original para favorecer el experimento.
2. No cambiar sus parámetros, configuración ni resultados históricos de referencia.
3. No reemplazar sus métricas anteriores por resultados recalculados sin documentar la diferencia.
4. Ejecutar la estrategia candidata de forma separada.
5. Comparar resultados usando supuestos y períodos compatibles cuando sea metodológicamente válido.

Cualquier corrección necesaria en el baseline deberá proponerse y aprobarse como una tarea independiente.

## 5. Alcance inicial

El primer experimento utilizará BTCUSDT Spot y velas de 15 minutos.

La estrategia candidata será sencilla, interpretable y con un número limitado de parámetros.

Un breakout de máximos y mínimos recientes es una hipótesis candidata, no una decisión definitiva. Antes de implementarlo, se deben revisar la arquitectura existente y los componentes reutilizables.

No se añadirán inicialmente:

- Apalancamiento.
- Futuros.
- Venta en corto.
- Martingala.
- Grid trading.
- Promediado de pérdidas.
- Reinversión automática de capital por encima de los límites aprobados.
- Modelos de machine learning innecesarios para el objetivo inicial.
- Optimización masiva de parámetros.

No se incorporarán otros activos hasta que el experimento inicial haya sido evaluado.

## 6. Reglas metodológicas obligatorias

### 6.1 Integridad temporal

- Las señales solo pueden utilizar información disponible en el momento de decisión.
- Las velas deben estar cerradas antes de calcular señales definitivas.
- No se puede utilizar el cierre de una vela para simular una ejecución al mismo cierre si esa ejecución no era posible en la práctica.
- Deben documentarse la zona horaria, los límites temporales y el tratamiento de velas incompletas.
- Los datos deben comprobarse para detectar duplicados, huecos, desorden temporal y valores inválidos.

### 6.2 Prevención de lookahead bias

- Las características y señales deben calcularse únicamente con datos pasados y disponibles.
- La ejecución simulada debe respetar el orden temporal.
- Los indicadores no pueden acceder accidentalmente a datos futuros.
- Las transformaciones y normalizaciones no pueden ajustarse con datos del holdout.
- Las pruebas deben incluir casos que detecten el uso accidental de información futura.

### 6.3 Ejecución realista

El backtest debe documentar:

- Momento en que se genera una señal.
- Momento y precio teórico de ejecución.
- Tratamiento de órdenes MARKET.
- Disponibilidad de efectivo y activos.
- Cantidad y precisión permitidas por el mercado.
- Reglas de redondeo y mínimos de operación.
- Comportamiento cuando una orden no puede ejecutarse.
- Tratamiento de ejecuciones parciales, si corresponde.

No se debe asumir que toda orden se ejecuta al precio ideal.

## 7. Modelo de costes

Los costes deben aplicarse de forma coherente a entradas y salidas.

El modelo debe considerar por separado:

1. Comisiones de compra y venta.
2. Spread entre bid y ask.
3. Deslizamiento de ejecución.
4. Otros costes que sean relevantes y estén documentados.

Los siguientes valores son escenarios iniciales ilustrativos, no tarifas verificadas ni parámetros definitivos:

| Escenario | Comisión por lado | Deslizamiento por lado |
|---|---:|---:|
| Favorable | 0,075 % | 0,01 % |
| Base | 0,10 % | 0,05 % |
| Estrés | 0,10 % | 0,10 % |

El spread debe modelarse por separado si los datos permiten estimarlo. Si ya está incorporado en el precio de ejecución, no debe cobrarse otra vez de forma duplicada.

Antes de ejecutar el experimento se debe verificar la tarifa aplicable a la cuenta o utilizar supuestos explícitos y conservadores.

Se informará tanto de los costes estimados como de su efecto sobre el resultado neto.

## 8. Diseño de la estrategia candidata

Antes de escribir código se debe aprobar una especificación que incluya:

- Indicadores utilizados.
- Parámetros iniciales y su justificación.
- Condiciones exactas de entrada.
- Condiciones exactas de salida.
- Tamaño de posición.
- Tratamiento de efectivo y activos.
- Frecuencia máxima de operaciones.
- Reglas de gestión de riesgo.
- Supuestos de ejecución.
- Condiciones que invalidan una señal.

La primera versión debe mantener un número reducido de parámetros.

Los parámetros no deben elegirse mirando repetidamente el holdout.

Si se propone una estrategia breakout, deben definirse con precisión la ventana de ruptura, los filtros, la salida y el tratamiento de señales consecutivas antes de la implementación.

No se presume que exista stop-loss o take-profit hasta que esté expresamente definido en la especificación.

## 9. Validación temporal

La evaluación debe utilizar períodos cronológicos separados.

### Etapa A: desarrollo

Se utiliza para implementar, depurar y definir la estrategia.

### Etapa B: validación

Se utiliza para comparar un conjunto limitado de variantes y detectar señales de sobreajuste.

### Etapa C: walk-forward

Se evalúa el comportamiento al repetir el proceso en ventanas temporales sucesivas, sin utilizar datos futuros para decidir parámetros pasados.

### Etapa D: holdout final

Es un período reservado que no se utiliza para elegir parámetros, reglas o variantes.

El período exacto, las fechas y la cantidad de datos deben documentarse antes de ejecutar la evaluación final.

No se aprobará una estrategia únicamente por obtener buenos resultados en el período de desarrollo.

Si el holdout se consulta repetidamente para modificar la estrategia, dejará de considerarse una evaluación final independiente. Se deberá reservar un período nuevo para una futura evaluación confirmatoria.

## 10. Estrategias de referencia

Siempre que los datos y las métricas sean comparables, se evaluarán:

1. Estrategia candidata de 15 minutos.
2. Estrategia diaria original.
3. Comprar y mantener BTC.
4. Mantener efectivo en USDT, sin operaciones.

Se debe explicar cualquier diferencia en exposición al mercado, capital inicial, períodos evaluados o costes que pueda afectar la comparación.

No se afirmará que una estrategia es superior únicamente porque pierde menos durante un período bajista.

## 11. Métricas obligatorias

### Rentabilidad

- Rentabilidad acumulada neta.
- Rentabilidad anualizada, si el período permite interpretarla.
- Rentabilidad por operación.
- Beneficio o pérdida netos después de costes.

### Riesgo

- Drawdown máximo.
- Volatilidad de los rendimientos.
- Sharpe con metodología documentada.
- Exposición al mercado.
- Peor operación y peor período relevante.

### Actividad y costes

- Número de operaciones cerradas.
- Frecuencia media de operaciones.
- Tiempo en posición.
- Comisiones acumuladas.
- Spread y deslizamiento estimados.
- Porcentaje de la rentabilidad bruta consumido por costes.

### Calidad de evidencia

- Resultados por ventana temporal.
- Resultados por escenario de costes.
- Sensibilidad a variaciones razonables de parámetros.
- Consistencia entre desarrollo, validación y holdout.
- Incertidumbre estadística y limitaciones del tamaño de muestra.

No se interpretará una métrica aislada como prueba suficiente de rentabilidad futura.

## 12. Criterios de aceptación

Antes de observar los resultados del holdout, el usuario debe aprobar criterios de aceptación documentados.

Como mínimo, la evaluación debe responder:

- ¿El resultado neto es positivo en el período reservado?
- ¿La estrategia conserva resultados razonables bajo el escenario de costes de estrés?
- ¿El drawdown es aceptable para el objetivo del experimento?
- ¿Los resultados dependen de unos pocos trades atípicos?
- ¿El comportamiento es razonablemente estable entre ventanas temporales?
- ¿Existe suficiente actividad para interpretar las métricas?
- ¿La estrategia aporta algo frente a las referencias?
- ¿La implementación supera las pruebas de integridad temporal y ejecución?

No se aprobará la estrategia si presenta defectos críticos de datos, ejecución o contabilidad.

No se inventarán umbrales numéricos para justificar resultados observados. Los valores definitivos deberán estar motivados y registrados antes de la evaluación final.

Un resultado negativo o inconcluso es un resultado válido del experimento.

## 13. Pruebas de software requeridas

Antes de utilizar el bot candidato en demo deben existir pruebas apropiadas para:

- Cálculo de señales.
- Uso exclusivo de velas cerradas.
- Ausencia de lookahead.
- Contabilidad de efectivo, activos y comisiones.
- Aplicación de costes.
- Cantidades y precisión.
- Límites de posición.
- Prevención de órdenes duplicadas.
- Órdenes rechazadas o de resultado incierto.
- Reconciliación de posiciones.
- Reinicio del proceso y recuperación del estado.
- Manejo de datos faltantes o inválidos.
- Separación entre simulación, demo y producción.

Las pruebas deben ejecutarse realmente y registrar sus resultados. No basta con afirmar que existen.

## 14. Salvaguardas operativas

- Spot únicamente.
- Apalancamiento deshabilitado.
- Sin claves de producción en el experimento.
- Sin envío de órdenes reales.
- El bot original no se modifica como parte de esta tarea.
- El candidato no se activa automáticamente en demo sin autorización explícita.
- Se respetan los límites de capital, exposición y frecuencia aprobados.
- Las discrepancias de reconciliación detienen la ejecución.
- Las órdenes con resultado incierto deben investigarse antes de cualquier reintento.
- Debe existir un procedimiento claro para detener el proceso.
- Los secretos nunca se registran en logs, commits o documentación.

Las condiciones exactas de envío de órdenes y los controles existentes deben verificarse en el código, no asumirse por documentación.

## 15. Protocolo de colaboración entre agentes

### Claude Code

Responsable de implementación una vez aprobado el diseño.

Debe:

- Consultar este documento antes de comenzar.
- Trabajar en una rama separada para el experimento.
- Limitar cada tarea a un alcance explícito.
- No modificar el baseline.
- Añadir o actualizar pruebas relevantes.
- Informar los archivos modificados.
- Indicar los comandos ejecutados y sus resultados.
- No afirmar que una prueba pasó si no la ejecutó.

### OpenAI Codex

Responsable de revisión independiente.

Debe:

- Inspeccionar el código y las pruebas por su cuenta.
- No asumir que la documentación de Claude demuestra que el código funciona.
- Buscar defectos de metodología, costes, lookahead, ejecución y seguridad.
- Documentar hallazgos con referencias verificables.
- No modificar los archivos durante una tarea de auditoría.
- Verificar las correcciones después de que Claude las implemente.

### Resolución de discrepancias

Todo hallazgo se clasifica como:

- **VERIFICADO:** respaldado por evidencia observable.
- **INFERIDO:** plausible, pero no demostrado.
- **DESCONOCIDO:** requiere información o comprobación adicional.

Si los agentes discrepan:

1. Se registra la afirmación exacta de cada uno.
2. Se identifica la evidencia necesaria para resolverla.
3. Se comprueba el código, la documentación o la prueba pertinente.
4. Se documenta la resolución.
5. No se avanza si la discrepancia afecta a la seguridad o la validez del experimento.

La opinión de un agente no sustituye la evidencia.

## 16. Registro de resultados

Cada ejecución experimental debe poder asociarse a:

- Identificador del experimento.
- Versión del código o commit.
- Configuración de parámetros.
- Datos y período evaluados.
- Supuestos de costes.
- Comando ejecutado.
- Resultados y métricas.
- Estado de las pruebas.
- Incidencias conocidas.

No se deben mezclar resultados de configuraciones distintas como si procedieran del mismo experimento.

Los datos sensibles y las credenciales no deben incluirse en los registros compartidos.

## 17. Condiciones para pasar a demo

Solo se podrá proponer una prueba demo cuando:

1. El diseño esté aprobado.
2. Las pruebas críticas pasen.
3. La evaluación fuera de muestra esté documentada.
4. El modelo de costes sea suficientemente realista.
5. No existan hallazgos críticos abiertos.
6. Los límites operativos estén definidos.
7. El usuario apruebe explícitamente la activación.

La aprobación para demo no constituye autorización para operar con dinero real.

## 18. Condiciones para considerar dinero real

El paso a dinero real requiere una revisión separada.

Se necesitarán evidencias suficientes de robustez histórica, validación operativa en demo, control de riesgos, comprensión de los costes y capacidad para soportar pérdidas.

La duración de la prueba demo no garantiza una muestra estadística suficiente. El número de operaciones, su independencia aproximada y la diversidad de condiciones de mercado deben evaluarse antes de tomar una decisión.

No se utilizará dinero prestado ni capital necesario para gastos esenciales.

No existe garantía de rentabilidad futura.

## 19. Estado actual y registro de cambios

### Estado actual

PLANNING — pendiente de auditoría de arquitectura y aprobación de especificación.

No se autoriza todavía la implementación de la estrategia candidata.

### Registro de cambios

| Fecha | Cambio | Responsable | Evidencia o motivo |
|---|---|---|---|
| 2026-10-14 | Creación inicial del protocolo experimental | Usuario / asistencia | Definir controles antes de implementar |

Este registro debe actualizarse únicamente cuando exista un cambio real y verificable.


## 20. PROTECCIÓN DEL BASELINE Y AISLAMIENTO DEL EXPERIMENTO

### Regla obligatoria

El bot actual es el baseline de referencia y no debe modificarse para desarrollar, probar o ejecutar la estrategia experimental de 15 minutos.

### Separación mediante Git

- La rama principal (`main`, o la rama que se confirme como baseline) debe permanecer intacta.
- Antes de implementar cambios de código, se debe crear una rama independiente, por ejemplo `experiment/15m-strategy`.
- No se permite desarrollar la estrategia experimental directamente sobre la rama principal.
- Antes de crear la rama, verificar el estado de Git y preservar cualquier cambio local del usuario. Nunca descartar cambios existentes.
- No fusionar la rama experimental con la principal sin autorización explícita del usuario.

### Aislamiento operativo

Una rama Git no garantiza el aislamiento de datos ni de procesos. Antes de ejecutar el experimento, verificar que:

- No comparte archivos de estado, registros de órdenes, bases de datos mutables ni archivos de salida con el bot original.
- No modifica la configuración utilizada por la tarea programada de Windows.
- No inicia, detiene ni altera el proceso automatizado del baseline.
- No puede enviar órdenes reales ni utilizar credenciales de producción.
- Las pruebas y los backtests se ejecutan en modo aislado y reproducible.

Si no puede garantizarse el aislamiento, detenerse y documentar el problema antes de ejecutar.

### Autorización por fases

1. Planificación: inspeccionar y documentar; no modificar código.
2. Preparación: crear y verificar la rama experimental después de la aprobación del usuario.
3. Implementación: modificar únicamente los archivos autorizados dentro de la rama experimental.
4. Auditoría: revisión independiente de código, pruebas, costes y aislamiento.
5. Integración: únicamente con autorización explícita del usuario y después de superar los criterios de aceptación.

### Responsabilidades de los agentes

- Claude Code: implementar exclusivamente dentro del alcance aprobado y en la rama experimental.
- Codex: auditar de forma independiente; no modificar el baseline ni realizar fusiones.
- Ambos agentes deben informar la rama actual, el estado de Git y los archivos modificados en sus informes.

Esta sección prevalece ante cualquier instrucción contradictoria sobre la modificación del baseline.

---

## Anexo A — Especificación propuesta de EXP-15M-001 (Claude Code, T022, 2026-10-14)

**Estado: CONGELADO el 2026-10-14 (versión 4.1).** Las decisiones de A.12 las aprobó el
usuario. Incorpora las revisiones T022-R a T022-R4 de Codex; el último punto pendiente de
T022-R4, la fórmula de "liquidez dudosa", quedó resuelto en A.5. El SHA-256 de este archivo
congelado está en DECISIONS.md D031. Sustituye a los "a definir" de las secciones 7 a 12, y
al estado PLANNING de las secciones 1 y 19 en lo que respecta al protocolo. La
implementación sigue necesitando una aprobación explícita aparte. Cambios en el texto del usuario: su segunda sección "12" se renumeró como 20, y la frase
del objetivo de la sección 2 se cambió por decisión del usuario (A.12-1).

Marcas: **VERIFICADO** (comprobado en código, Git o archivos), **INFERIDO** (razonado, no
comprobado), **DESCONOCIDO** (falta información) y **CONVENCIÓN** (valor elegido por regla
o costumbre, no derivado de los datos; necesita aprobación).

### A.1 Baseline operativo T019: comprobado en el código

- VERIFICADO: el **baseline operativo T019** es `trend_filter(window=50)` sobre velas diarias
  (src/bottrading/crossasset.py:32 y src/bottrading/holdout.py:50). El paper trading lo usa
  vía `FROZEN_CANDIDATE` (src/bottrading/paper.py:31 y :106), con comisión de 0,1 % y slippage
  de 0,05 % (crossasset.py:33).
- VERIFICADO: no es la estrategia de referencia original del MVP. Esa era el cruce de medias
  (PROJECT_SPEC.md:31-32). El experimento se compara con el baseline operativo T019.
- VERIFICADO: los límites de la demo T021 son 1000 USDT por activo, 1 orden por símbolo y
  día, 3 órdenes al día y 3000 USDT de exposición (src/bottrading/execution.py:30-33).

### A.2 Componentes reutilizables (VERIFICADO salvo indicación)

| Necesidad | Existe | Referencia | Limitación para 15m |
|---|---|---|---|
| Descarga de velas 15m | Sí | download.py:30 (`INTERVALS` incluye `15m`) | Aún no hay datos 15m en `data/`. Solo descarga meses cerrados (D019) |
| Lectura de klines (ms y µs) | Sí | binance.py:27-28, :65 | Rechaza duplicados y ordena (binance.py:80-85), pero **no exige la rejilla de 15 min**. Solo OHLCV, sin bid/ask |
| Motor de backtest | Sí | backtest.py:59-110 | Señal al cierre de la vela i y ejecución a la apertura de la **siguiente vela existente** (backtest.py:81-97). Solo largo, todo el efectivo, cantidades float, sin stops |
| Costes | Sí | config.py:11-15; backtest.py:121-160 | Comisión y slippage porcentuales sobre la apertura de ejecución. Sin spread histórico |
| Breakout | Sí, sobre cierres | strategy.py:81-100 (`donchian_signals`) | Canal de cierres, no de máximos y mínimos (D021) |
| Interfaz de señales | Sí | walkforward.py:40-57 | Recibe solo cierres |
| Tramos y herencia de posición | Sí | splits.py:109-139 (`evaluate_segment`) | Los esquemas son solo diario y horario (splits.py:42-43) |
| CLI de holdout | Sí, bloqueada | holdout.py:50-52 | Solo acepta el candidato diario de D023: **no se usará para 15m** |
| Métricas | Parcial | metrics.py:70-117 | Ver la nota bajo esta tabla |
| Pruebas de causalidad | Sí, para las estrategias actuales | tests/test_strategy.py:107, :187; tests/test_backtest.py:93 | No cubren datos 15m ni la tubería nueva (A.10) |

**Métricas (metrics.py):**
- Anualiza por intervalo entre velas (metrics.py:153-158) y solo anota los huecos, sin detenerse (metrics.py:88).
- No calcula exposición, retorno por operación, peso de los costes ni dependencia de las mejores operaciones.

### A.3 Aislamiento (bloqueante)

1. **Worktree aparte, nunca `git checkout` aquí.**
   - VERIFICADO: la tarea de las 08:00 ejecuta el paper trading con el código de esta copia (scripts/paper_daily.ps1:149).
   - VERIFICADO: solo después comprueba la rama (llamada en paper_daily.ps1:151; función en :59-62).
   - Todo el trabajo se hará en un `git worktree` de la rama `experiment/15m`, en `C:/Users/thoma/bottrading-exp15m`, fuera de OneDrive y fuera de la ruta de la tarea.
2. **`.venv` propio en el worktree.**
   - VERIFICADO: el `.venv` actual tiene una instalación editable cuyo `.pth` apunta a la carpeta `src` de esta copia; desde otro worktree importaría el código de `main`.
   - Comprobación obligatoria antes de cada ejecución: `bottrading.__file__` debe estar dentro del worktree.
3. **Datos y salidas propios.**
   - `data/` está ignorado por Git (VERIFICADO); las velas van a `data/BTCUSDT-15m/` del worktree.
   - Los informes van a `reports/exp15m/` del worktree.
   - Nada escribe en `paper/`, en `reports/automation/` ni en la carpeta privada de la demo (`%USERPROFILE%/.bottrading/demo`, demo_ledger.py:62).
4. **Sin red salvo el descargador.**
   - El experimento no importa `demo_client` ni ningún módulo de la demo.
   - La guarda estática de red existente (D019) debe seguir pasando en la rama.
5. **Demo NO autorizada.**
   - VERIFICADO: la aprobación de órdenes demo de D030 es solo para el baseline diario congelado; toda variante en demo se registraría en D030 y no hay ninguna (DECISIONS.md:548-551).
   - VERIFICADO: además choca con 1 orden por símbolo y día (execution.py:31) y con el clientOrderId por fecha de señal (execution.py:64-68).
   - INFERIDO: operar 15m en la misma cuenta demo rompería la reconciliación y la racha de T021.
   - Cualquier demo de la candidata exige un protocolo y una aprobación nuevos, otra cuenta demo y otra carpeta privada. Queda **fuera de EXP-15M-001**.
6. **Fusión.** La rama no se fusiona con `main` sin aprobación explícita (sección 20).

### A.4 Datos y huecos

- **Fuente:** `data.binance.vision`, klines Spot mensuales de BTCUSDT 15m, de 2020-01 a 2027-01, con el descargador existente. Cada ZIP se verifica con su `.CHECKSUM`.
- **Hora y marca temporal:** UTC. La marca temporal es el `open_time` (D018). La vela con `open_time` D 23:45 cierra a las 00:00 del día D+1.
- **Manifiesto:**
  - Antes de cualquier backtest se guarda `reports/exp15m/data_manifest.csv` con nombre, tamaño y SHA-256 de cada ZIP.
  - El manifiesto se versiona en la rama.
  - Los datos del holdout (2026-11 a 2027-01) se descargan y se añaden al manifiesto solo al abrirlo (A.7).
- **Validación 15m nueva:**
  - Cada `open_time` es múltiplo de 15 min en UTC y las velas están estrictamente ordenadas, sin duplicados.
  - El `close_time` corresponde a su vela.
  - Si falta alguna vela, se cuenta y se lista. No se rellena.
- **Tratamiento causal de los huecos** (sustituye a la "orden anulada" de la v2, que dependía de saber de antemano que faltaba la vela):
  - La orden pendiente se ejecuta a la apertura de la **siguiente vela existente**. Es el comportamiento actual del motor (backtest.py:81-97).
  - Es causal: la señal solo usa cierres pasados, y la orden espera a que vuelva a haber mercado. Así se comportaría una orden MARKET enviada en cuanto el mercado reabre; nunca se mira una vela futura para decidir si la orden existe.
  - INFERIDO: un hueco en los klines oficiales corresponde a un periodo sin negociación (mantenimiento o caída) y no a una pérdida de datos.
  - Cada operación ejecutada tras un hueco se marca como "tras hueco". El informe da su número y su resultado.
  - La premisa anterior es INFERIDA: si el hueco fue una pérdida de datos con el mercado abierto, esa apertura posterior no representa el fill real. Por eso estas operaciones pasan por la **prueba de exclusión** de A.9, que fija su efecto en el veredicto.
  - Las ventanas de la ruptura cuentan velas, no tiempo; es una limitación documentada.
  - **Todos los tramos cuentan.** No se excluye ningún trimestre por tener huecos: no queda criterio de exclusión que decidir después. Se informa del número de huecos de cada tramo.
- **Velas incompletas:** no existen en los ZIP mensuales, porque solo hay meses cerrados (D019). Un archivo de un mes en curso se rechaza.
- **Enmienda 1 (2026-10-14, antes de ver el holdout).**
  - **Motivo (VERIFICADO al validar los datos reales):** de 236 488 velas de 2020-01 a 2026-09 hay:
    - 13 velas sin negociación (0 operaciones y volumen 0) en tres paradas: 2020-12-21, 2021-02-11 y 2023-03-24. Una de ellas tiene un `close_time` anterior a su `open_time`.
    - 5 velas "truncadas", con operaciones pero cerradas antes de los 15 min: 2020-02-19, 2020-03-04, 2021-04-25, 2021-08-13 y 2021-12-24.
    - Ninguna de estas velas está en la validación (2024-01 a 2026-09).
    - Con la regla anterior ("el `close_time` corresponde a su vela"), toda la serie sería un defecto crítico.
  - **Vela sin negociación:** se descarta y cuenta como hueco. Una orden enviada durante una parada espera a que se vuelva a negociar, así que se aplica la regla causal de huecos de arriba. Si solo uno de los dos (operaciones o volumen) es 0, es un error de datos.
  - **Vela truncada:** se conserva y se marca. Las operaciones ejecutadas en su apertura cuentan como "tras hueco" en la prueba de exclusión de A.9.
  - **Cualquier otro `close_time` irregular** sigue siendo un error de datos (defecto crítico 2).

### A.5 Ejecución y costes

**Convención de ejecución:**
- MARKET a la apertura de la siguiente vela existente después de la señal.
- Es una aproximación reproducible, no una prueba de que el fill fuera posible a ese precio.
- El salto entre el cierre de la señal y la apertura de ejecución es **movimiento de mercado**: entra en el resultado (PnL), no en el coste de slippage. El slippage se aplica, adverso, sobre la apertura de ejecución (backtest.py:121-160).

**Escenarios:** reutilizo los cuatro de D023 (holdout.py:41-46), por comparabilidad con D024. Sustituyen la tabla ilustrativa de la sección 7.

| Escenario | Comisión por lado | Slippage por lado (incluye medio spread) | Ida y vuelta |
|---|---:|---:|---:|
| sin costes (solo referencia) | 0 | 0 | 0 |
| bajo | 0,075 % | 0,02 % | ~0,19 % |
| **base (principal)** | **0,1 %** | **0,05 %** | **~0,30 %** |
| alto (estrés) | 0,2 % | 0,1 % | ~0,60 % |

**Cada coste, por separado:**
- **Comisión:** 0,1 % por lado. VERIFICADO: la cuenta demo cobró 0,1 % en la primera orden (TASKS.md:936). DESCONOCIDO: la tarifa de una cuenta real.
- **Spread:**
  - DESCONOCIDO: no hay spread histórico en estos klines, y el experimento no usará ninguna otra fuente.
  - Supuesto explícito: el medio spread va **dentro** del slippage. No se cobra aparte, así que no hay doble cobro.
  - INFERIDO, no demostrado: en BTCUSDT el spread habitual es de 1 tick.
  - El escenario alto existe para cubrir un spread y un impacto mucho mayores.
- **Liquidez y fills parciales:** se asume fill completo.
  - **Diagnóstico causal, no prueba de fill:** el nominal de cada orden simulada se compara con el volumen en USDT de la **vela anterior** a la ejecución, que ya era conocido al decidir.
  - Si alguna orden supera el 1 % de ese volumen, se marca como "liquidez dudosa" (CONVENCIÓN aprobada). Su efecto en el veredicto lo fija la **prueba de exclusión** de A.9.
  - **Fórmula exacta (T022-R4):**
    - Sea p la vela existente inmediatamente anterior a la vela de ejecución, que es la vela cuya señal se ejecuta.
    - Volumen de referencia: `V = volume[p] × close[p]`. `volume` es la columna 6 del kline (índice 5, volumen en BTC), la única que conserva el importador (binance.py:150-156, VERIFICADO).
    - El volumen en USDT del kline (índice 7) no se usa, porque el importador lo descarta.
    - Nominal de la orden: `N = quantity × price` de la operación simulada; es el precio de ejecución, con slippage.
    - Se marca "liquidez dudosa" si `N > 0,01 × V` (desigualdad estricta). Si `V = 0`, cualquier orden queda marcada.
    - Se calcula en cada escenario de coste con sus propias operaciones. La prueba de exclusión del holdout usa las del escenario base.
- **Redondeo:**
  - El motor usa cantidades float, sin redondeo ni polvo (D013), y no se modifica.
  - Se calcula una **cota acumulada** del efecto del redondeo: la suma, en todas las operaciones, de 0,00001 BTC (paso de cantidad, INFERIDO, a confirmar con el exchangeInfo antes del holdout) × precio de ejecución.
  - **C2 y C3 usan el retorno neto menos esa cota acumulada**, que es la peor dirección. Así el error acumulado queda acotado y nunca favorece a la candidata.
- **Barrera principal (INFERIDO):** cada operación debe moverse en promedio más del 0,30 % solo para quedar en cero. Es el obstáculo más probable del experimento.

### A.6 Estrategia candidata y selección (una sola interpretación)

- **Señal:** `donchian_signals(closes, entry, exit)` existente (strategy.py:81-100), sobre los **cierres** de velas 15m de BTCUSDT. No usa máximos ni mínimos: es un canal de cierres.
  - BUY en la vela i si `close[i] > max(close[i-entry .. i-1])`.
  - SELL en la vela i si `close[i] < min(close[i-exit .. i-1])`.
  - En otro caso, HOLD. Un empate produce HOLD.
- **Calentamiento:** cada condición empieza cuando hay `entry` o `exit` velas previas. Las señales de cada tramo se calculan con todo el historial anterior y se recortan (`evaluate_segment`). Cada tramo hereda la posición (D020).
- **Posición:**
  - Solo largo, una posición como máximo y el 100 % del efectivo de la estrategia, con capital inicial de 10 000 USDT.
  - BUY con posición abierta, o SELL sin ella, se ignora (backtest.py:91-93).
  - Sin stop-loss, take-profit, piramidación ni reinversión ajena.
- **Frecuencia:** no hay límite aparte. Con una sola posición y ejecución en la vela siguiente hay como máximo 1 orden cada 15 min. Se informa de la frecuencia real.
- **Configuraciones (exactamente 4):** `entry` {48, 96} × `exit` {24, 48}. 96 velas son 24 h y 48 son 12 h; la salida no es más larga que la entrada. Cualquier variante nueva es otro experimento (EXP-15M-002 o posterior), con aprobación y datos no vistos propios.
- **Evaluaciones registradas:** 4 configuraciones × 11 trimestres × 4 escenarios de coste = 176 backtests de validación. La **selección solo usa el escenario base**; los demás escenarios son de sensibilidad. Todas las evaluaciones se publican, no solo la ganadora.
- **Regla de selección (ÚNICA, global, precedente D021/D022):**
  - Cada una de las 4 configuraciones se evalúa en cada uno de los 11 trimestres de validación, con calentamiento causal y herencia de posición.
  - Se elige UNA configuración para todo el experimento: la de mayor mediana del Sharpe diario en esos 11 trimestres (escenario base).
  - Desempate: la menor mediana de drawdown intradía (A.8). Un Sharpe no disponible cuenta como 0.
  - Esa configuración, y solo esa, se evalúa en el holdout.
  - No hay reselección trimestre a trimestre: la estrategia no tiene parámetros estimados con datos; la "ventana creciente" de la v2 era solo calentamiento y se elimina.
- **Desarrollo (2020-2023):** depuración, validación de datos y calentamiento. Su rendimiento se publica como información, pero **no entra en la selección**.

### A.7 Particiones temporales (fechas fijas, UTC)

**Contaminación (VERIFICADO, D024).** El periodo 2025-05-26 a 2026-09-30 ya fue holdout del baseline diario y se abrió. Aquí se usa solo como validación, nunca como holdout.

| Etapa | Periodo | Uso |
|---|---|---|
| A. Desarrollo | 2020-01-01 00:00 → 2023-12-31 23:45 | Depuración y datos; no entra en la selección |
| B. Validación | 2024-01-01 00:00 → 2026-09-30 23:45, en 11 trimestres naturales | Selección global (A.6) y C7 |
| — Separación | 2026-10-01 → 2026-10-31 | No se evalúa. Solo sirve de calentamiento causal del holdout |
| C. Holdout final prospectivo | 2026-11-01 00:00 → 2027-01-31 23:45 | Datos que aún no existen. Se descargan y se abren **una vez**, a partir de 2027-02-01 |

- **Garantías del holdout:**
  - El código de evaluación se publica en la rama ANTES de descargar esos datos.
  - Un comando con una opción explícita de apertura deja constancia: commit, SHA-256 del protocolo y del manifiesto, y fecha.
  - Abrirlo dos veces o cambiar las reglas lo invalida. Una nueva evaluación exigiría datos posteriores a 2027-01 (regla de D023).
- **Exposición al mercado (INFERIDO):** durante el holdout la automatización T019 seguirá mostrando BTC diario. El periodo no es ciego al mercado. Regla: **las reglas, criterios y configuración congelados no cambian por nada que se observe del mercado ni del baseline antes de abrir el holdout**. Cualquier cambio invalida el holdout y obliga a reservar otro posterior.
- **Límite asumido:** 3 meses de un solo activo es una muestra corta y de un solo régimen. El veredicto se interpreta con C6 y C9.

### A.8 Comparación y métricas

- **Las cuatro referencias, en el mismo periodo, con el mismo capital (10 000) y el mismo escenario de costes:**
  - (1) candidata 15m;
  - (2) baseline operativo T019 sobre velas diarias, con `evaluate_segment` y el candidato congelado, sin reimplementarlo;
  - (3) buy-and-hold BTC sobre las mismas velas 15m;
  - (4) efectivo: 0 %, tasa libre de riesgo 0, como D023.
- **Muestreo diario (convención exacta):**
  - El valor del día D es la valoración al cierre de la vela 15m con `open_time` D 23:45, que cierra a las 00:00 de D+1. Coincide con el cierre de la vela diaria de D (`open_time` D 00:00).
  - Si esa vela falta por un hueco, se usa la valoración al cierre de la última vela existente anterior.
  - Si un día natural UTC entero no tiene ninguna vela, su valor se arrastra del día anterior: rendimiento 0 ese día, y el movimiento se concentra en el día siguiente con datos.
    - Ese día se marca como "día arrastrado" y el informe da su número por tramo.
    - En el holdout, C9 se calcula además sin esos días (A.9).
  - Con esos valores diarios se calculan los rendimientos, la volatilidad y el Sharpe, anualizando con 365 días como en metrics.py:19.
- **Drawdown, dos medidas:**
  - **Intradía:** sobre la curva completa de 15m. Se informa siempre y es el que usa C5.
  - **Diario:** sobre la curva muestreada. Sirve para compararse con el baseline diario.
- **Métricas:** retorno neto, retorno anualizado (solo si hay ≥ 365 días), los dos drawdowns, volatilidad, Sharpe, exposición, operaciones e idas y vueltas, frecuencia, tiempo en posición, comisiones y slippage, peso de los costes sobre la ganancia bruta, retorno por operación, peor operación, peor trimestre, resultado por trimestre, operaciones "tras hueco" y "liquidez dudosa", y cota de redondeo.
- **Régimen:** cada trimestre se etiqueta por el signo del buy-and-hold, sin umbrales.

### A.9 Criterios de aceptación propuestos (se congelan ANTES del holdout)

Se miden en el holdout C, escenario base, salvo que se indique otra cosa. "Retorno neto" incluye la liquidación final con costes; en C2 y C3 se resta además la cota de redondeo (A.5).

| # | Criterio | Justificación |
|---|---|---|
| C1 | Integridad: pasan todas las pruebas de A.10, el manifiesto coincide y A.3 se cumple | Requisito de validez. Sin umbral |
| C2 | Retorno neto > 0 | Supera al efectivo (0 %) |
| C3 | Retorno neto > retorno neto del baseline operativo T019 | El objetivo es ganar más; si no lo supera, no aporta frente a una estrategia más simple y barata |
| C4 | El signo de (candidata − baseline) se mantiene en bajo, base y alto, **y** el retorno neto de la candidata es > 0 en el escenario alto | Regla de robustez de D023 más el requisito absoluto aprobado (A.12-4): debe ganar dinero incluso con 0,60 % por ida y vuelta |
| C5 | Drawdown intradía 15m de la candidata ≤ drawdown intradía 15m del buy-and-hold | Misma curva y misma resolución. No aceptar más riesgo que mantener BTC (referencia de D024) |
| C6 | Al menos 30 idas y vueltas cerradas | CONVENCIÓN estadística habitual para aproximar una media, **no derivada del código** (metrics.py:21 se refiere a rendimientos de velas, no a operaciones). Con menos, INCONCLUSO |
| C7 | Mediana del Sharpe diario de la configuración elegida en sus 11 trimestres > 0 | Regla de D021. Es optimista, porque se mide en los mismos trimestres de la selección: es condición necesaria, no prueba |
| C8 | Concentración: ver la definición bajo esta tabla | Detecta resultados que dependen de pocas operaciones. El 5 % es una CONVENCIÓN |
| C9 | Inferencia: ver la definición bajo esta tabla | Bloques para respetar la dependencia temporal; longitud de bloque por regla, no elegida |

**C8, concentración (definición exacta):**
- Se ordenan las idas y vueltas por su PnL neto en USDT, de mayor a menor. La posición abierta al final cuenta como ida y vuelta, valorada con su liquidación con costes.
- Se quitan las k mejores, con k = techo(0,05 × N) y como mínimo 1.
- Se cumple si (PnL neto total − suma del PnL de esas k) > 0.
- Es una resta aditiva en USDT, sin recomponer el capital. La aproximación queda documentada.

**C9, inferencia (definición exacta y algoritmo reproducible):**
- **Datos:** `r[0..n-1]`, los rendimientos diarios netos de la candidata en el holdout (A.8), en orden cronológico.
- **Estadístico:** la media aritmética de `r`.
- **Parámetros:** longitud de bloque L = techo(n^(1/3)), es decir 5 para n = 92; B = 10 000 remuestreos; semilla 20261101.
- **Algoritmo** (Python estándar, `random.Random(20261101)`, un único generador para todo el cálculo):
  - Para cada remuestreo b = 1..B, en ese orden, se construye una lista vacía.
  - Mientras su longitud sea < n, se toma `s = rng.randrange(n)` y se añaden `r[(s + j) % n]` para j = 0..L−1.
  - La lista se recorta a sus n primeros elementos y se guarda su media.
- **Límite inferior:** se ordenan las B medias de menor a mayor y se toma la de índice 249 (base 0), es decir el rango techo(0,025 × B) = 250. Es el percentil 2,5 por rango más cercano.
- **Se cumple** si ese límite es > 0. Si hubo "días arrastrados" (A.8), el cálculo se repite con la serie sin esos días (otro n y otra L, la misma semilla) y **ambos** límites deben ser > 0.
- **Información adicional, no criterio:** el mismo cálculo sobre el PnL por operación.

**Prueba de exclusión (operaciones "tras hueco" y "liquidez dudosa" del holdout):**
- Se repiten C2 y C3 restando, de forma aditiva en USDT, el PnL neto de las idas y vueltas que contengan alguna de esas operaciones.
- Si C2 o C3 dejan de cumplirse, el veredicto **máximo es INCONCLUSO**.
- Si no hay operaciones marcadas, la prueba se da por superada.

**Defecto crítico (lista cerrada).** Cualquiera de estos hechos da RECHAZADO y el holdout queda **consumido**: no se puede volver a usar tras corregir.
1. Falla alguna prueba de A.10, o la suite del baseline, en el commit de evaluación.
2. Algún SHA-256 de datos no coincide con el manifiesto, o el validador 15m rechaza los datos (rejilla, orden, duplicados, `close_time`, mes en curso).
3. Falla una identidad contable en alguna vela:
   - el efectivo o la cantidad son negativos; o
   - el capital no es igual a efectivo + cantidad × cierre (tolerancia 1e-6 USDT); o
   - alguna comisión o slippage no coincide con la fórmula de su escenario (tolerancia 1e-9 relativa).
   - *Aclaración 1 (2026-10-14, I2; no cambia ningún criterio):* la comprobación también cubre:
     - el precio con slippage y el efectivo tras cada operación, con tolerancia relativa 1e-9. Para el efectivo, la base es max(|esperado|, efectivo previo + nominal): al invertir todo el capital el esperado es ~0, y una tolerancia relativa a 0 confundiría el redondeo de coma flotante con un defecto;
     - la conservación de la cantidad: solo se compra sin posición y se vende exactamente lo que se tiene;
     - que el lado de cada operación sea BUY o SELL, y que su precio de referencia sea la apertura de su vela;
     - que la señal sea la de la vela anterior;
     - el estado final: efectivo, cantidad y liquidación.
4. Hay evidencia de lookahead: alguna prueba de prefijos falla con los datos reales del holdout.
5. Se viola el protocolo de apertura: el holdout se abre más de una vez, o se ejecuta con un commit o protocolo distinto del registrado, o los datos se descargaron antes de publicar el código.
6. Se viola el aislamiento: `bottrading.__file__` está fuera del worktree, hay escritura fuera de las rutas de A.3, o se usa un módulo de la demo.

No es defecto crítico, porque está tratado arriba: huecos, días arrastrados y liquidez dudosa.

**Veredictos (fijados de antemano):**
- **VALIDADO:** se cumplen C1–C9 y se supera la prueba de exclusión.
- **INCONCLUSO:** se cumplen C1–C5, C7 y C8, pero falla C6 o C9, o no se supera la prueba de exclusión. No autoriza dinero real; una demo exigiría su propia aprobación (A.3-5).
- **RECHAZADO:** cualquier otro caso, o cualquier defecto crítico de la lista cerrada.

Un resultado RECHAZADO o INCONCLUSO es válido y se publica tal cual.

### A.10 Pruebas obligatorias antes de cualquier evaluación

- **Validador 15m:** rejilla, orden, duplicados, `close_time` y mes en curso rechazado.
- **Secuencia causal de huecos:**
  - Con una señal al cierre de la vela anterior a un hueco, la orden se ejecuta a la apertura de la primera vela tras el hueco y se marca "tras hueco".
  - Las señales no cambian si se añaden o quitan velas posteriores a la decisión.
- **Prefijos de la tubería completa con datos 15m sintéticos:** añadir velas futuras no cambia las señales, las operaciones ni la curva pasada.
- **Ejecución en la apertura siguiente**, con el salto cierre→apertura fuera del coste de slippage.
- **Calentamiento y límites de tramo** (herencia de posición).
- **Costes:** por escenario, sin doble cobro; cota de redondeo.
- **Muestreo diario:** la vela de las 23:45 da el valor del día y el hueco se resuelve con la vela anterior. Drawdown intradía frente al diario.
- **Métricas nuevas:** exposición, retorno por operación, peso de los costes, diagnóstico de liquidez con la vela anterior y C8 con k redondeado hacia arriba.
- **C9:** algoritmo exacto de A.9: un generador, orden de llamadas, recorte a n e índice 249. Vector de prueba fijo con resultado conocido. Repetición sin "días arrastrados".
- **Prueba de exclusión e identidades contables** de la lista de defectos críticos.
- **Día natural sin velas:** su valor se arrastra del día anterior y se marca como "día arrastrado".
- **Selección:** la configuración elegida es la de mayor mediana de Sharpe en el escenario base. Desempate. Sharpe no disponible = 0.
- **Guarda de apertura única del holdout.**
- **Aislamiento:** guarda de red, ningún import de módulos de la demo y rutas de salida dentro del worktree.
- **Suite completa del baseline en la rama**, sin cambios en los módulos del baseline salvo aprobación.

### A.11 Congelación del protocolo

- Al aprobarlo, el usuario fija los puntos de A.12 y el anexo pasa a "CONGELADO".
- Se registra en el repositorio, en commit aparte: T022 en TASKS.md y D031 en DECISIONS.md.
- El commit y el SHA-256 de este archivo quedan anotados en D031.
- Cualquier cambio posterior de las reglas antes del holdout se registra con fecha y motivo, y solo puede hacerse **sin haber visto el holdout**. Después del holdout, ninguno.

### A.12 Decisiones del usuario (APROBADAS el 2026-10-14: "si apruebo tu recomendacion")

1. **Objetivo de la sección 2:** "la mayor rentabilidad neta **fuera de muestra**" en lugar de "la mejor rentabilidad histórica". Aplicado en la sección 2.
2. **Escenarios de coste** de D023, que sustituyen a la tabla ilustrativa de la sección 7.
3. **Holdout prospectivo** 2026-11-01 → 2027-01-31, abierto una sola vez desde el 2027-02-01.
4. **C4 ampliado:** retorno propio > 0 también en el escenario alto. Ya incorporado en C4.
5. **Convenciones:** 1 % del volumen (A.5), 30 idas y vueltas (C6) y 5 % (C8).
6. **Worktree y `.venv` propios** en `C:/Users/thoma/bottrading-exp15m`. Se crearán solo cuando se apruebe implementar.
7. **Corrección de readme.md:148**, en un cambio aparte del experimento.

### A.13 Registro de cambios del anexo

| Fecha | Cambio | Responsable |
|---|---|---|
| 2026-10-14 | v1: auditoría y propuesta | Claude Code |
| 2026-10-14 | v2: revisión T022-R de Codex. Fechas fijas, recuento de pruebas, regla de selección, manifiesto, validación 15m, liquidez y redondeo, D030 no cubre la candidata, criterios numéricos, pruebas obligatorias y congelación. Segunda sección "12" renumerada como 20 | Claude Code |
| 2026-10-14 | v3: revisión T022-R2 de Codex. Selección global única (se elimina la reselección por trimestre). Huecos tratados de forma causal con la siguiente vela existente y sin excluir tramos. C6 justificado como convención. C8 y C9 exactos (bootstrap de bloques, semilla y percentil). C4 ampliado como decisión del usuario. Salto cierre→apertura distinto del slippage. Liquidez con la vela anterior. Cota de redondeo acumulada. Muestreo diario exacto y drawdown intradía. Regla ante la exposición al mercado. Referencias corregidas | Claude Code |
| 2026-10-14 | v4: el usuario aprueba las decisiones de A.12. Revisión T022-R3 de Codex: algoritmo exacto de C9, prueba de exclusión para operaciones "tras hueco" y "liquidez dudosa", lista cerrada de defectos críticos, días naturales sin velas ("día arrastrado") y C4 con retorno > 0 en alto | Claude Code |
| 2026-10-14 | v4.1: revisión T022-R4 de Codex: fórmula exacta del volumen para "liquidez dudosa" (A.5) | Claude Code |
| 2026-10-14 | Enmienda 1 (A.4): velas sin negociación como hueco y velas truncadas marcadas. Motivo: paradas del exchange halladas al validar los datos reales de 2020-2023, antes de ver el holdout. Registrada en D031 | Claude Code |
| 2026-10-14 | Aclaración 1 (A.9, defecto crítico 3): alcance de las identidades contables y tolerancia del efectivo tras cada operación. Revisión de Codex de I2; no cambia ningún criterio | Claude Code |
