"""Sector Market API — motores de dato real por sector.

Incluye los 4 motores de la ficha sectorial (growth, borme-monthly, ma-deals,
top-buyers) MÁS el ranking de sectores para la home "Analizar sectores"
(agregados precomputados: tamaño, crecimiento, margen, fragmentación · lente
ARROBA/CNAE). Prefijo PÚBLICO + sin get_current_user (como sector-intelligence)
salvo el rebuild, que es admin.

Este fichero SUSTITUYE al del paquete SectorMarket-INTEL anterior (le añade
/ranking y /aggregates/rebuild). El motor vive en services/engines/sector_market/.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth_utils import get_current_user
from services.engines.sector_market import sector_market as SM
from services.engines.sector_market import aggregates as AGG

router = APIRouter(prefix="/api/v1/public/sector-market", tags=["sector_market"])


# ── Ficha sectorial (4 motores) ──
@router.get("/{cnae}/growth")
async def growth(cnae: str):
    return await SM.growth_by_sector(cnae)


@router.get("/{cnae}/borme-monthly")
async def borme_monthly(cnae: str, months: int = Query(24, ge=1, le=120)):
    return await SM.borme_monthly(cnae, months=months)


@router.get("/{cnae}/ma-deals")
async def ma_deals(cnae: str, category: Optional[str] = None, limit: int = Query(10, ge=1, le=50)):
    return await SM.ma_deals(cnae, category=category, limit=limit)


@router.get("/{cnae}/top-buyers")
async def top_buyers(cnae: str, limit: int = Query(10, ge=1, le=50)):
    return await SM.top_buyers(cnae, limit=limit)


# ── Home "Analizar sectores": ranking de agregados (precomputados) ──
@router.get("/ranking")
async def ranking(lens: str = Query("arroba"), level: Optional[str] = None,
                  metric: str = Query("size"), limit: int = Query(20, ge=1, le=100)):
    """Ranking de sectores por métrica. Lee db.sector_aggregates (rápido).
    lens: arroba|cnae · metric: size|growth|margin|frag."""
    return await AGG.get_ranking(lens=lens, level=level, metric=metric, limit=limit)


@router.post("/aggregates/rebuild")
async def aggregates_rebuild(user=Depends(get_current_user)):
    """Recalcula db.sector_aggregates (caro: recorre master_companies). Admin.
    Ejecutar tras desplegar y de forma nocturna."""
    return await AGG.rebuild_sector_aggregates()
