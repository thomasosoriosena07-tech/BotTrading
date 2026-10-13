# AGENTS.md — Trading Bot

## Objetivo
Construir un proyecto educativo de trading algorítmico en Python,
reproducible, testeable y seguro. El modo inicial y predeterminado
será exclusivamente backtesting y paper trading.

## Roles
- Claude Code: implementar tareas concretas y ejecutar pruebas.
- Codex: revisar cambios, detectar defectos y proponer pruebas.
- Usuario: aprobar decisiones importantes y cambios de alcance.
- No asumir que los agentes se comunican directamente entre sí.
- Compartir contexto mediante estos archivos y Git.

## Reglas de desarrollo
- Leer este archivo, PROJECT_SPEC.md y TASKS.md antes de trabajar.
- Implementar solo la tarea solicitada; evitar refactorizaciones ajenas.
- No duplicar módulos ni introducir abstracciones innecesarias.
- Preferir funciones pequeñas, tipado cuando aporte valor y nombres claros.
- Usar pathlib para rutas y logging para registrar eventos.
- Mantener las dependencias mínimas y documentar cada dependencia nueva.
- No ocultar errores ni usar excepciones genéricas sin necesidad.
- No afirmar que algo funciona sin haberlo comprobado.

## Seguridad financiera
- Prohibidas las órdenes reales y la conexión a cuentas de trading real.
- No implementar apalancamiento, préstamos ni futuros en el MVP.
- No solicitar, almacenar ni imprimir claves API o contraseñas.
  Única excepción (D030): el código podrá LEER, sin mostrarla, la
  credencial de una cuenta Binance DEMO que el usuario crea y guarda
  fuera del repositorio. Los agentes nunca la piden ni la ven.
- No desactivar las comprobaciones de riesgo para facilitar una prueba.
- La simulación debe indicar claramente que no representa resultados reales.
- Nunca presentar rentabilidad histórica como garantía de rentabilidad futura.

## Integridad del backtest
- No usar datos futuros para generar señales (look-ahead bias).
- Señales calculadas con datos disponibles al cierre de una vela:
  ejecutar como pronto en la siguiente vela.
- Modelar comisiones y slippage configurables.
- Evitar usar velas incompletas.
- Documentar supuestos, limitaciones y tratamiento de datos faltantes.
- Comparar contra una estrategia de referencia sencilla.
- Separar datos, señales, ejecución simulada y métricas.

## Calidad
- Escribir pruebas automatizadas para la lógica financiera.
- Ejecutar las pruebas relevantes después de cada cambio.
- Usar datos sintéticos deterministas para pruebas unitarias.
- No descargar datos durante las pruebas unitarias.
- No afirmar que las pruebas pasaron si no se ejecutaron.
- Informar de los comandos ejecutados y sus resultados.

## Git y colaboración
- No sobrescribir trabajo ajeno ni usar git reset --hard.
- No ejecutar git push --force.
- No hacer commits automáticamente salvo petición explícita.
- No editar el mismo módulo que está modificando el otro agente.
- Antes de terminar, resumir archivos cambiados, pruebas y riesgos.
- Actualizar TASKS.md y DECISIONS.md cuando corresponda.

## Eficiencia de tokens
- Leer solo los archivos relevantes para la tarea.
- No imprimir archivos completos si bastan fragmentos concretos.
- No repetir el contexto ya documentado.
- No investigar en la web salvo que sea necesario.
- No añadir dependencias, herramientas o servicios sin justificación.
- Entregar un resumen breve y una siguiente acción concreta.