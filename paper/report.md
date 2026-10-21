# Paper trading: `trend_filter(window=50)` desde 2026-10-01

**Simulación sin dinero.** No se envían órdenes ni se usan cuentas o claves. Los resultados simulados no garantizan rentabilidades futuras.

Protocolo fijado antes de empezar (DECISIONS.md D027): estrategia congelada, costes base, capital 10 000 por activo, velas diarias cerradas, sin cambios durante la prueba.

- Datos hasta: **2026-10-20** (20 días simulados)
- Próximo punto de control: 6 meses (preliminar) el 2027-03-31 (faltan 162 días)

## Situación actual

| Activo | Posición | Retorno estrategia | Retorno buy-and-hold | Drawdown estrategia | Drawdown buy-and-hold | Operaciones |
|---|---|---:|---:|---:|---:|---:|
| BTCUSDT | dentro | -1.01 % | -1.01 % | 5.82 % | 5.82 % | 1 |
| ETHUSDT | fuera | -8.14 % | -9.09 % | 9.38 % | 11.89 % | 2 |
| SOLUSDT | fuera | -10.74 % | -10.07 % | 13.16 % | 14.91 % | 2 |

Retornos netos de costes, con la posición abierta valorada a su liquidación. Con pocos días, las métricas anualizadas y el Sharpe no están disponibles o no son representativos.

## Diario

Las operaciones simuladas están en `ledger.csv` (solo se añaden filas; el historial de Git sirve de sello de tiempo) y la curva de capital diaria en `equity.csv`.
