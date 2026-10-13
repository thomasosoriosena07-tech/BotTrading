# BotTrading

Proyecto educativo de trading algorítmico en Python.

## Objetivo

Desarrollar y evaluar estrategias con datos históricos,
costes de transacción y controles de riesgo.

## Estado

En desarrollo. El MVP utiliza exclusivamente simulación.

## Requisitos

- Python compatible con las dependencias del proyecto.
- Git.
- VS Code recomendado.

## Instalación en Windows

Desde la raíz del proyecto:

    python -m venv .venv
    .venv\Scripts\activate
    python -m pip install --upgrade pip

Instalar las dependencias documentadas en requirements.txt
cuando ese archivo esté disponible.

## Pruebas

Ejecutar las pruebas desde la raíz del proyecto:

    python -m pytest

## Seguridad

No incluir claves API, contraseñas, archivos .env reales
ni información financiera privada en el repositorio.

Este proyecto no ejecuta órdenes reales y sus resultados
simulados no garantizan rendimientos futuros.