# CLAUDE.md — Claude Code

@AGENTS.md

## Forma de trabajo
1. Leer PROJECT_SPEC.md y TASKS.md.
2. Identificar la primera tarea pendiente relacionada con la petición.
3. Proponer un plan breve antes de cambios que afecten varios módulos.
4. Implementar la tarea más pequeña que produzca un resultado verificable.
5. Ejecutar pruebas y corregir errores relacionados con el cambio.
6. Actualizar TASKS.md si la tarea cambió de estado.
7. Resumir archivos modificados, pruebas ejecutadas y limitaciones.

## Coordinación con Codex
Codex es un revisor independiente, no un proceso al que debas
suponer que puedes enviar mensajes directamente.

Al terminar una tarea:
- No afirmes que Codex aprobó el cambio.
- Deja el código y las pruebas listos para revisión.
- No implementes preventivamente todas las sugerencias hipotéticas.
- Espera las observaciones concretas del usuario o del revisor.

## Restricciones
No implementar trading en vivo, conexiones a cuentas reales,
órdenes reales ni gestión de credenciales de trading.
No cambiar el alcance del proyecto sin aprobación.