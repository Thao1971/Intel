"""Company Screener API — búsqueda multi-criterio de empresas con conteo y facetas.

Pantalla "Analizar empresas" (entrada previa a resultados). Auth JWT como el resto
de endpoints de usuario (igual que buyer-mandates). El motor vive en
`services/engines/screener/screener.py` — este fichero es solo el borde HTTP.

    POST /api/v2/company-intelligence/screen        -> página + total + facetas
    POST /api/v2/company-intelligence/screen/count  -> solo total + facetas (contador en vivo)
    GET  /api/v2/company-intelligence/screen/signals-> catálogo de señales filtrables
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from auth_utils import get_current_user
from services.engines.screener import screener as SC

router = APIRouter(prefix="/api/v2/company-intelligence", tags=["company_screener"])

# HARDENING-señales-es (2026-09-28 · Daniel): etiquetas en español de cada
# `signal_type` individual (distinto de `SC.SIGNAL_FILTER_MAP`, que agrupa
# varios `signal_type` bajo una etiqueta de FILTRO como "succession"). Viven
# aquí — el borde HTTP del screener — y no en
# `services/engines/signal/taxonomy.py`, porque esa taxonomía declara
# explícitamente "UI concepts are NEVER here" (D8): es el motor puro, agnóstico
# de interfaz, y no hay que romper esa regla para que arroba pinte un chip.
# Traducidas a partir de la descripción factual de cada `signal_type` en
# `taxonomy.SIGNAL_TYPES` (versión `tax-v1`) — no son una interpretación libre.
# Si se añade un `signal_type` nuevo a la taxonomía, añadir aquí su etiqueta;
# el consumidor (arroba) ya sabe degradar con gracia si un código no está.
SIGNAL_LABELS_ES: Dict[str, str] = {
    "financial.margin_strong": "Margen EBITDA fuerte",
    "financial.margin_weak": "Margen EBITDA débil",
    "financial.low_liquidity": "Liquidez baja",
    "financial.high_leverage": "Apalancamiento alto",
    "financial.negative_equity": "Patrimonio neto negativo",
    "financial.net_loss": "Pérdidas en el último ejercicio",
    "financial.quality_low": "Calidad financiera baja",
    "growth.revenue_surge": "Fuerte subida de facturación",
    "growth.ebitda_expansion": "Expansión de EBITDA",
    "growth.sustained": "Crecimiento sostenido",
    "risk.revenue_decline": "Caída de facturación",
    "risk.sustained_decline": "Caída sostenida (varios años)",
    "risk.revenue_anomaly": "Variación anómala de facturación",
    "risk.balance_inconsistency": "Inconsistencia en el balance",
    "risk.dissolution_signal": "Disolución, liquidación o insolvencia",
    "ownership.foreign_parent": "Matriz extranjera",
    "ownership.group_member": "Pertenece a un grupo",
    "ownership.consolidator": "Consolidador (tiene participadas)",
    "ownership.standalone": "Independiente (sin grupo)",
    "market.outperforms_peers": "Por encima de sus comparables",
    "market.underperforms_peers": "Por debajo de sus comparables",
    "market.fragmented_sector": "Sector fragmentado",
    "operational.productivity_high": "Alta productividad por empleado",
    "operational.productivity_low": "Baja productividad por empleado",
    "operational.capital_intensive": "Intensiva en capital",
    "corporate.officers_change": "Cambio de administradores",
    "corporate.capital_change": "Cambio de capital social",
    "corporate.group_change": "Cambio de grupo societario",
    "corporate.borme_event": "Evento registrado en BORME",
    "corporate.governance_change": "Cambio de gobierno (BORME)",
    "corporate.capital_movement": "Movimiento de capital (BORME)",
    "opportunity.succession_signal": "Posible sucesión o relevo",
    "transaction.ma_event": "Operación de M&A",
    "transaction.control_change": "Cambio de control",
}


class ScreenFilters(BaseModel):
    # Sector
    cnae_sections: Optional[List[str]] = None
    cnae_codes: Optional[List[str]] = None
    # Territorio
    provincias: Optional[List[str]] = None
    # Rangos financieros (€; margen en ratio 0-1)
    revenue_min: Optional[float] = None
    revenue_max: Optional[float] = None
    employees_min: Optional[float] = None
    employees_max: Optional[float] = None
    ebitda_min: Optional[float] = None
    ebitda_max: Optional[float] = None
    ebitda_margin_min: Optional[float] = None
    ebitda_margin_max: Optional[float] = None
    # Dinámica
    growth_yoy_min: Optional[float] = None
    growth_yoy_max: Optional[float] = None
    estado: Optional[str] = "active"          # active | distressed | all
    signals: Optional[List[str]] = None       # etiquetas (succession, consolidation, ...) o signal_type crudo
    # Contexto
    year: Optional[int] = None
    query: Optional[str] = None


class ScreenRequest(ScreenFilters):
    offset: int = Field(0, ge=0)
    limit: int = Field(25, ge=1, le=100)
    sort_by: Optional[str] = None             # revenue | ebitda | ebitda_margin | employees | name | growth
    sort_dir: Optional[str] = "desc"          # asc | desc


def _filters(req: ScreenFilters) -> dict:
    return req.model_dump(exclude={"offset", "limit", "sort_by", "sort_dir"}, exclude_none=False)


@router.post("/screen")
async def screen(req: ScreenRequest, user=Depends(get_current_user)):
    return await SC.screen(
        _filters(req), offset=req.offset, limit=req.limit,
        sort_by=req.sort_by, sort_dir=req.sort_dir,
    )


@router.post("/screen/count")
async def screen_count(req: ScreenFilters, user=Depends(get_current_user)):
    return await SC.count(_filters(req))


@router.get("/screen/signals")
async def screen_signals(user=Depends(get_current_user)):
    """Catálogo de señales: `signals` (etiqueta de filtro -> lista de signal_type,
    para los chips del constructor de criterios) y `labels_es` (signal_type ->
    etiqueta legible en español, para pintar cada señal individual de una fila
    — ver HARDENING-señales-es arriba)."""
    return {"signals": SC.SIGNAL_FILTER_MAP, "labels_es": SIGNAL_LABELS_ES}
