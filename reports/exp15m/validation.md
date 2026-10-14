# EXP-15M-001 — Informe de validación (walk-forward)

> Simulación histórica con costes modelados. **No es un resultado real ni una garantía de rentabilidad futura.** La validación sirve para ELEGIR una configuración (A.6); el veredicto del experimento solo lo da el holdout prospectivo 2026-11-01 → 2027-01-31, que se abrirá una vez a partir del 2027-02-01.

- Protocolo EXPERIMENT_15M.md, SHA-256 5618253be395b3e719a04aba023d5684654e9417cf900a931bdd32ce45d5f0a6
- Manifiesto 15m 06095c4a1e9dd8452ad62959daae10f3a19e4af8efbc38ebeac65e756fd3d0e0; manifiesto diario 706bb46266c2c4bfdc1fc3205ab334df563bd35b894b8502ceaac74170365310
- Capital 10 000 USDT; escenario principal: base (comisión 0,1 %, slippage 0,05 % por lado); 4 configuraciones × 11 trimestres × 4 escenarios = 176 evaluaciones de validación.

## Selección (regla única de A.6, escenario base)

| Configuración | Mediana del Sharpe diario | Mediana del drawdown intradía |
|---|---:|---:|
| donchian(48,24) | -2.62 | 23,87 % |
| donchian(48,48) | -2.06 | 22,14 % |
| donchian(96,24) | -2.31 | 22,47 % |
| donchian(96,48) **(elegida)** | -1.87 | 20,20 % |

- Elegida: **donchian(96,48)**. Es la única que se evaluará en el holdout.
- C7 (mediana del Sharpe de la elegida > 0): **no**. Es optimista: se mide en los mismos trimestres que la eligieron (condición necesaria, no prueba).

## Retorno neto por trimestre (escenario base)

| Trimestre | donchian(48,24) | donchian(48,48) | donchian(96,24) | donchian(96,48) | Buy-and-hold | Baseline T019 | Efectivo |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2024T1 (alcista) | -4,66 % | +5,16 % | -4,52 % | +0,45 % | +68,07 % | +54,97 % | 0,00 % |
| 2024T2 (bajista) | -25,56 % | -17,34 % | -20,87 % | -17,35 % | -12,20 % | -12,24 % | 0,00 % |
| 2024T3 (alcista) | -14,61 % | -8,82 % | -8,72 % | -6,87 % | +0,58 % | -10,61 % | 0,00 % |
| 2024T4 (alcista) | -17,20 % | +2,97 % | -10,19 % | +8,79 % | +47,32 % | +43,51 % | 0,00 % |
| 2025T1 (bajista) | -20,29 % | -24,12 % | -15,13 % | -16,75 % | -12,05 % | -7,07 % | 0,00 % |
| 2025T2 (alcista) | -19,83 % | -5,26 % | -20,87 % | -14,31 % | +29,41 % | +18,70 % | 0,00 % |
| 2025T3 (alcista) | -13,86 % | -16,38 % | -13,66 % | -16,31 % | +6,12 % | -3,20 % | 0,00 % |
| 2025T4 (bajista) | -20,49 % | -23,60 % | -18,07 % | -21,50 % | -23,38 % | -4,03 % | 0,00 % |
| 2026T1 (bajista) | -19,58 % | -22,62 % | -2,08 % | -11,10 % | -22,33 % | -11,55 % | 0,00 % |
| 2026T2 (bajista) | -28,35 % | -21,60 % | -22,73 % | -13,62 % | -14,40 % | +7,60 % | 0,00 % |
| 2026T3 (alcista) | -7,28 % | +9,39 % | -2,30 % | +4,96 % | +42,21 % | +22,57 % | 0,00 % |

## Sharpe diario por trimestre (escenario base)

| Trimestre | donchian(48,24) | donchian(48,48) | donchian(96,24) | donchian(96,48) | Buy-and-hold | Baseline T019 |
|---|---:|---:|---:|---:|---:|---:|
| 2024T1 | -0.24 | 0.66 | -0.24 | 0.28 | 3.76 | 3.33 |
| 2024T2 | -3.99 | -2.06 | -3.47 | -2.39 | -0.85 | -1.47 |
| 2024T3 | -1.75 | -0.80 | -1.07 | -0.64 | 0.32 | -1.60 |
| 2024T4 | -1.62 | 0.48 | -0.92 | 1.02 | 3.38 | 3.20 |
| 2025T1 | -2.46 | -2.34 | -2.31 | -1.87 | -0.75 | -1.16 |
| 2025T2 | -3.37 | -0.61 | -3.58 | -2.16 | 2.70 | 2.41 |
| 2025T3 | -3.09 | -3.27 | -3.83 | -3.98 | 0.97 | -0.46 |
| 2025T4 | -4.00 | -3.87 | -3.49 | -3.57 | -2.32 | -0.76 |
| 2026T1 | -2.62 | -2.61 | -0.28 | -1.78 | -1.43 | -2.26 |
| 2026T2 | -6.23 | -4.10 | -5.45 | -2.91 | -1.50 | 1.32 |
| 2026T3 | -0.68 | 1.18 | -0.12 | 0.75 | 3.82 | 2.42 |

## Sensibilidad a costes (mediana del retorno neto trimestral)

| Estrategia | sin costes | bajo | base | alto |
|---|---:|---:|---:|---:|
| donchian(48,24) | +3,46 % | -11,97 % | -19,58 % | -36,60 % |
| donchian(48,48) | +1,62 % | -10,19 % | -16,38 % | -31,20 % |
| donchian(96,24) | +4,31 % | -7,46 % | -13,66 % | -27,17 % |
| donchian(96,48) | -1,04 % | -9,63 % | -13,62 % | -23,61 % |
| buy-and-hold | +0,89 % | +0,69 % | +0,58 % | +0,28 % |
| baseline T019 | -1,73 % | -2,66 % | -3,20 % | -4,64 % |

## Actividad y costes (escenario base, suma de los 11 trimestres)

| Configuración | Operaciones | Idas y vueltas | Exposición media | Comisiones | Slippage | Tras hueco | Vela truncada | Liquidez dudosa |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| donchian(48,24) | 1847 | 926 | 37,63 % | 16 899 | 8 450 | 0 | 0 | 1 |
| donchian(48,48) | 1334 | 670 | 51,55 % | 12 847 | 6 424 | 0 | 0 | 1 |
| donchian(96,24) | 1272 | 638 | 26,39 % | 11 893 | 5 946 | 0 | 0 | 0 |
| donchian(96,48) | 953 | 479 | 37,99 % | 9 257 | 4 628 | 0 | 0 | 0 |

## Desarrollo 2020-2023 (información; no entra en la selección)

| Estrategia | sin costes | bajo | base | alto | Drawdown (base) |
|---|---:|---:|---:|---:|---:|
| donchian(48,24) | +184,81 % | -76,23 % | -94,35 % | -99,89 % | 95,43 % |
| donchian(48,48) | +166,48 % | -56,34 % | -84,68 % | -99,12 % | 89,69 % |
| donchian(96,24) | +151,34 % | -55,14 % | -83,46 % | -98,91 % | 87,28 % |
| donchian(96,48) | +93,69 % | -47,69 % | -75,49 % | -96,90 % | 85,49 % |
| buy-and-hold | +488,83 % | +487,71 % | +487,06 % | +485,31 % | 77,23 % |
| baseline T019 | +905,72 % | +846,39 % | +813,66 % | +730,03 % | 58,47 % |

## Tramos

| Tramo | Primera vela | Última vela | Velas |
|---|---|---|---:|
| desarrollo | 2020-01-01 00:00 | 2023-12-31 23:45 | 140091 |
| 2024T1 | 2024-01-01 00:00 | 2024-03-31 23:45 | 8736 |
| 2024T2 | 2024-04-01 00:00 | 2024-06-30 23:45 | 8736 |
| 2024T3 | 2024-07-01 00:00 | 2024-09-30 23:45 | 8832 |
| 2024T4 | 2024-10-01 00:00 | 2024-12-31 23:45 | 8832 |
| 2025T1 | 2025-01-01 00:00 | 2025-03-31 23:45 | 8640 |
| 2025T2 | 2025-04-01 00:00 | 2025-06-30 23:45 | 8736 |
| 2025T3 | 2025-07-01 00:00 | 2025-09-30 23:45 | 8832 |
| 2025T4 | 2025-10-01 00:00 | 2025-12-31 23:45 | 8832 |
| 2026T1 | 2026-01-01 00:00 | 2026-03-31 23:45 | 8640 |
| 2026T2 | 2026-04-01 00:00 | 2026-06-30 23:45 | 8736 |
| 2026T3 | 2026-07-01 00:00 | 2026-09-30 23:45 | 8832 |

Lectura: esto es validación de un solo activo y un periodo concreto. Un buen resultado aquí no demuestra ventaja estadística; el holdout lo juzga con C1-C9.
