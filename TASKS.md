# Tasks

## Estado
- [x] T001 — Inspeccionar el repositorio y el entorno.
- [ ] T002 — Crear estructura mínima del paquete Python.
- [ ] T003 — Configurar dependencias y entorno de desarrollo.
- [ ] T004 — Implementar carga y validación de CSV.
- [ ] T005 — Implementar señales de medias móviles.
- [ ] T006 — Implementar motor de backtesting.
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
- El siguiente paso prioritario es T002.

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