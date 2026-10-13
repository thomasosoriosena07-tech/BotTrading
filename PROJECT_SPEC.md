# Project Specification — BotTrading

## Objetivo
Desarrollar un bot educativo de trading algorítmico en Python.
El primer objetivo es aprender, medir resultados y verificar
la corrección del sistema; no prometer ni asumir rentabilidad.

## Alcance del MVP
1. Cargar datos OHLCV históricos desde archivos CSV.
2. Validar columnas, fechas, duplicados y valores inválidos.
3. Implementar una estrategia de cruce de medias móviles.
4. Ejecutar un backtest sin utilizar información futura.
5. Simular posiciones spot largas, sin apalancamiento.
6. Incluir comisiones y slippage configurables.
7. Calcular métricas de rendimiento y riesgo.
8. Comparar con una estrategia buy-and-hold.
9. Generar un informe reproducible.
10. Implementar pruebas automatizadas.
11. Permitir paper trading con datos históricos o simulados,
    sin conexión a una cuenta real.

## Datos
Formato mínimo:
timestamp, open, high, low, close, volume

Las fechas deben ordenarse cronológicamente y usar una
zona horaria explícita o estar normalizadas a UTC.
No asumir que un CSV está limpio: validarlo primero.
Las pruebas unitarias usarán datos sintéticos.

## Estrategia de referencia
- Media móvil rápida y media móvil lenta.
- Señal de compra cuando la rápida cruza por encima de la lenta.
- Señal de salida cuando cruza por debajo.
- Calcular señales solo con datos disponibles en ese momento.
- Ejecutar la operación simulada en la siguiente vela.
- No usar cortos, margen ni apalancamiento.

Los parámetros serán configurables, no elegidos para garantizar
un resultado positivo.

## Métricas
- Retorno acumulado y anualizado cuando sea apropiado.
- Drawdown máximo.
- Volatilidad, si puede estimarse correctamente.
- Sharpe, documentando tasa libre de riesgo y periodicidad.
- Número de operaciones, porcentaje de ganadoras y costes.
- Comparación con buy-and-hold.
- Resultados netos de comisiones y slippage.

No calcular métricas engañosas cuando falten datos suficientes.

## Gestión del riesgo
- Capital inicial configurable.
- Tamaño de posición limitado por configuración.
- Sin apalancamiento ni saldo negativo.
- Rechazar operaciones que excedan el capital disponible.
- Registrar cada operación simulada.
- Detener o rechazar configuraciones inválidas.

## Arquitectura
Separar:
- configuración,
- carga y validación de datos,
- estrategia,
- motor de backtesting,
- métricas,
- informes,
- pruebas.

Evitar complejidad prematura y dependencias innecesarias.

## Fuera de alcance
- Trading en vivo.
- Claves API de Binance u otros exchanges.
- Órdenes reales.
- Apalancamiento, futuros y margen.
- Promesas de rentabilidad.
- Optimización masiva de parámetros sin control de sobreajuste.

## Criterios de aceptación
El MVP estará listo cuando:
- se pueda instalar en un entorno virtual limpio;
- las pruebas pasen;
- un conjunto de datos de ejemplo produzca resultados reproducibles;
- las operaciones tengan costes incluidos;
- no se utilicen datos futuros;
- se genere un informe documentado;
- la ejecución sea simulada por defecto.

## Fase 2 — Búsqueda de ventaja con validación (aprobada 2026-10-13)
Objetivo del usuario: encontrar estrategias con mejores resultados netos.
Se persigue sin relajar la integridad: una mejora solo cuenta si se
mantiene fuera de la muestra usada para elegirla.

Alcance:
1. Importar CSV históricos públicos de Binance descargados manualmente
   por el usuario (formato klines). Sin claves API ni descargas en las
   pruebas.
2. Dividir los datos en tramos temporales: ajuste (in-sample) y prueba
   (out-of-sample), y evaluación walk-forward.
3. Búsqueda acotada de parámetros solo en el tramo de ajuste,
   registrando todas las combinaciones probadas.
4. Como máximo dos estrategias adicionales, con las mismas reglas de
   ejecución, costes y pruebas de no look-ahead.
5. Informe comparativo out-of-sample frente a buy-and-hold.
6. Paper trading con datos públicos en tiempo real: solo tras una
   aprobación específica del acceso a red (D017).

Sigue fuera de alcance: órdenes reales, claves API, apalancamiento,
cortos, margen y promesas de rentabilidad.

Criterios de aceptación de la fase 2:
- los parámetros se eligen sin ver el tramo de prueba;
- el informe muestra resultados in-sample y out-of-sample por separado,
  el número de combinaciones probadas y la comparación con buy-and-hold;
- un resultado out-of-sample peor que buy-and-hold se informa igual;
- las pruebas pasan sin red.