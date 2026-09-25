"""Company Screener engine (búsqueda multi-criterio + conteo + facetas).

Motor que faltaba para la pantalla "Analizar empresas": filtra el universo real
de `master_companies` por criterios estructurados (sector, territorio, tamaño,
rentabilidad, crecimiento, estado, señal) y devuelve página + total del universo
filtrado + facetas para el contador en vivo de la UI.

Reutiliza el mismo dato y las mismas rutas de campo que el matching de mandatos
(`services/engines/recommendation/mandates.py`) — no añade fuente de datos nueva.
"""
from services.engines.screener import screener  # noqa: F401
