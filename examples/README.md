# Datos de ejemplo

`synthetic_daily.csv` contiene **datos SINTÉTICOS, no datos de mercado**.

- 800 velas diarias desde 2022-01-01 (UTC).
- Paseo aleatorio geométrico con semilla fija (42), generado por
  `generate_synthetic.py`.
- Sirve para probar el flujo de forma reproducible. Por construcción no
  contiene ninguna ventaja aprovechable: los resultados obtenidos con
  él no dicen nada sobre ningún mercado real.

Si copias el CSV fuera del repositorio, conserva esta nota junto a él.
