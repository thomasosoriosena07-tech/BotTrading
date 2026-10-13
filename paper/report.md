# Paper trading: `trend_filter(window=50)` desde 2026-10-01

**Simulación sin dinero.** No se envían órdenes ni se usan cuentas o claves. Los resultados simulados no garantizan rentabilidades futuras.

Protocolo fijado antes de empezar (DECISIONS.md D027): estrategia congelada, costes base, capital 10 000 por activo, velas diarias cerradas, sin cambios durante la prueba.

- Datos hasta: **2026-10-12** (12 días simulados)
- Próximo punto de control: 6 meses (preliminar) el 2027-03-31 (faltan 170 días)

## Situación actual

| Activo | Posición | Retorno estrategia | Retorno buy-and-hold | Drawdown estrategia | Drawdown buy-and-hold | Operaciones |
|---|---|---:|---:|---:|---:|---:|
| BTCUSDT | dentro | -2.41 % | -2.41 % | 5.52 % | 5.52 % | 1 |
| ETHUSDT | fuera | -8.14 % | -9.16 % | 9.38 % | 10.26 % | 2 |
| SOLUSDT | dentro | -10.73 % | -10.73 % | 13.03 % | 13.03 % | 1 |

Retornos netos de costes, con la posición abierta valorada a su liquidación. Con pocos días, las métricas anualizadas y el Sharpe no están disponibles o no son representativos.

## Diario

Las operaciones simuladas están en `ledger.csv` (solo se añaden filas; el historial de Git sirve de sello de tiempo) y la curva de capital diaria en `equity.csv`.
