"""Company Screener API — búsqueda multi-criterio de empresas con conteo y facetas.

Pantalla "Analizar empresas" (entrada previa a resultados). Auth JWT como el resto
de endpoints de usuario (igual que buyer-mandates). El motor vive en
`services/engines/screener/screener.py` — este fichero es solo el borde HTTP.

    POST /api/v2/company-intelligence/screen        -> página + total + facetas
    POST /api/v2/company-intelligence/screen/count  -> solo total + facetas (contador en vivo)
    GET  /api/v2/company-intelligence/screen/signals-> catálogo de señales filtrables
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from auth_utils import get_current_user
from services.engines.screener import screener as SC

router = APIRouter(prefix="/api/v2/company-intelligence", tags=["company_screener"])


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
    """Catálogo de señales que el screener acepta como filtro (etiqueta -> signal_type)."""
    return {"signals": SC.SIGNAL_FILTER_MAP}
