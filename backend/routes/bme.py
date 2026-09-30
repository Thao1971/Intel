"""BME Intelligence — Endpoints for BME Growth + Scaleup data."""

from fastapi import APIRouter, Depends, Query, HTTPException
from database import db
from models import now_iso
from auth_utils import get_current_user
from services.bme_connector import sync_bme, get_bme_stats
import asyncio
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
_bg_tasks: set = set()

router = APIRouter(prefix="/api/v1/bme-markets", tags=["bme"])


def _meta(t0):
    return {"contract_version": "1.0", "generated_at": now_iso(),
            "response_time_ms": round((time.time() - t0) * 1000, 1),
            "source": "BME — Bolsas y Mercados Espanoles"}


@router.get("/dashboard")
async def dashboard(user=Depends(get_current_user)):
    t0 = time.time()
    stats = await get_bme_stats()
    signals = await db.bme_signals.find({}, {"_id": 0}).to_list(20)

    from services.bme_enrichment import get_enrichment_stats
    enrichment = await get_enrichment_stats()

    return {**_meta(t0), "kpis": stats, "signals": signals, "enrichment": enrichment}


@router.get("/companies")
async def list_companies(
    market: str = Query(None, regex="^(growth|scaleup)$"),
    sector: str = Query(None),
    limit: int = Query(50, ge=1, le=500),
    page: int = Query(1, ge=1),
    user=Depends(get_current_user),
):
    t0 = time.time()
    query = {}
    if market:
        if market == "growth":
            query["listed_in_growth"] = True
        else:
            query["listed_in_scaleup"] = True
    if sector:
        query["sector"] = {"$regex": sector, "$options": "i"}

    skip = (page - 1) * limit
    companies = await db.bme_companies.find(query, {"_id": 0}).sort("market_cap", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.bme_companies.count_documents(query)
    return {**_meta(t0), "companies": companies, "total": total, "page": page}


@router.get("/company/{isin}")
async def company_detail(isin: str, user=Depends(get_current_user)):
    t0 = time.time()
    company = await db.bme_companies.find_one({"isin": isin}, {"_id": 0})
    if not company:
        from fastapi import HTTPException
        raise HTTPException(404, f"Company with ISIN {isin} not found")
    return {**_meta(t0), "company": company}


@router.get("/signals")
async def list_signals(user=Depends(get_current_user)):
    t0 = time.time()
    signals = await db.bme_signals.find({}, {"_id": 0}).to_list(20)
    return {**_meta(t0), "signals": signals, "count": len(signals)}


@router.get("/corporate-events")
async def list_events(
    event_type: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
):
    """Corporate events (dividends, capital increases, etc.)."""
    t0 = time.time()
    query = {}
    if event_type:
        query["event_type"] = event_type
    events = await db.corporate_events.find(query, {"_id": 0}).sort("publication_date", -1).limit(limit).to_list(limit)
    total = await db.corporate_events.count_documents(query)
    return {**_meta(t0), "events": events, "total": total}


@router.post("/enrich-details")
async def enrich(user=Depends(get_current_user)):
    """Run batch enrichment for all companies needing data."""
    from services.bme_enrichment import run_full_enrichment
    result = await run_full_enrichment(max_companies=300)
    if result.get("status") == "error":
        raise HTTPException(502, result.get("message", "Error en enriquecimiento BME"))
    return result


@router.get("/enrichment-stats")
async def enrichment_stats(user=Depends(get_current_user)):
    """Get enrichment progress and data completeness."""
    t0 = time.time()
    from services.bme_enrichment import get_enrichment_stats
    stats = await get_enrichment_stats()
    return {**_meta(t0), **stats}


@router.post("/sync")
async def sync(
    markets: str = Query(None, description="Comma-separated: growth,scaleup,principal"),
    user=Depends(get_current_user),
):
    """Lanza el sync de BME (Playwright + detalle + senales + match) en segundo plano.

    Evita el corte del proxy/Cloudflare en peticiones largas. Resultado:
    GET /bme-markets/sync-state (status: idle | running | done; `result` = respuesta de sync_bme).
    """
    market_list = [m.strip() for m in markets.split(",")] if markets else None

    current = await db.bme_sync_state.find_one({"_id": "current"})
    if current and current.get("status") == "running":
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(current["started_at"].replace("Z", "+00:00"))).total_seconds()
        except (KeyError, ValueError):
            age = 9999
        if age < 1800:  # un "running" de >30 min se considera huerfano
            return {"status": "running", "started_at": current["started_at"]}

    started_at = now_iso()
    await db.bme_sync_state.replace_one(
        {"_id": "current"}, {"_id": "current", "status": "running", "started_at": started_at}, upsert=True)
    task = asyncio.create_task(_run_sync(market_list, started_at))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"status": "running", "started_at": started_at}


async def _run_sync(market_list, started_at):
    try:
        result = await sync_bme(markets=market_list)
    except Exception as e:
        logger.error(f"BME sync failed: {e}")
        result = {"status": "error", "message": str(e)[:300]}
    await db.bme_sync_state.replace_one(
        {"_id": "current"},
        {"_id": "current", "status": "done", "started_at": started_at,
         "finished_at": now_iso(), "result": result},
        upsert=True,
    )


@router.get("/sync-state")
async def sync_state(user=Depends(get_current_user)):
    """Estado del ultimo sync lanzado con POST /sync."""
    doc = await db.bme_sync_state.find_one({"_id": "current"}, {"_id": 0})
    return doc or {"status": "idle"}


@router.get("/coverage")
async def coverage(user=Depends(get_current_user)):
    """Audit coverage: imported vs expected, missing companies, data quality."""
    t0 = time.time()

    growth_imported = await db.bme_companies.count_documents({"listed_in_growth": True})
    scaleup_imported = await db.bme_companies.count_documents({"listed_in_scaleup": True})
    total = await db.bme_companies.count_documents({})

    # Expected totals (from BME website)
    growth_expected = 113
    scaleup_expected = 45
    principal_expected = 121
    principal_imported = await db.bme_companies.count_documents({"listed_in_bme_principal": True})

    # Data quality
    without_isin = await db.bme_companies.count_documents({"isin": {"$regex": "^NOISIN"}})
    without_cap = await db.bme_companies.count_documents({"$or": [{"market_cap": None}, {"market_cap": 0}]})
    without_sector = await db.bme_companies.count_documents({"$or": [{"sector": None}, {"sector": ""}]})

    # Missing companies (NOISIN entries)
    noisin = await db.bme_companies.find(
        {"isin": {"$regex": "^NOISIN"}}, {"_id": 0, "company_name": 1, "market_segment": 1, "source_url": 1}
    ).to_list(20)

    return {
        **_meta(t0),
        "growth_expected": growth_expected,
        "growth_imported": growth_imported,
        "growth_coverage_pct": round(growth_imported / growth_expected * 100, 1),
        "scaleup_expected": scaleup_expected,
        "scaleup_imported": scaleup_imported,
        "scaleup_coverage_pct": round(scaleup_imported / scaleup_expected * 100, 1),
        "principal_expected": principal_expected,
        "principal_imported": principal_imported,
        "principal_coverage_pct": round(principal_imported / principal_expected * 100, 1) if principal_expected > 0 else 0,
        "total_imported": total,
        "total_expected": growth_expected + scaleup_expected + principal_expected,
        "total_coverage_pct": round(total / (growth_expected + scaleup_expected + principal_expected) * 100, 1),
        "data_quality": {
            "without_isin": without_isin,
            "without_market_cap": without_cap,
            "without_sector": without_sector,
        },
        "companies_without_standard_isin": noisin,
        "quality_score": {
            "coverage": round(total / max(growth_expected + scaleup_expected + principal_expected, 1) * 100),
            "isin_completeness": round((total - without_isin) / max(total, 1) * 100),
            "market_cap_completeness": round((total - without_cap) / max(total, 1) * 100),
            "sector_completeness": round((total - without_sector) / max(total, 1) * 100),
            "overall": round(((total / max(growth_expected + scaleup_expected + principal_expected, 1) * 100) * 0.4 +
                             ((total - without_isin) / max(total, 1) * 100) * 0.2 +
                             ((total - without_cap) / max(total, 1) * 100) * 0.2 +
                             ((total - without_sector) / max(total, 1) * 100) * 0.2)),
        },
    }



# ══════════════════════════════════════════
# INTELLIGENCE LAYER
# ══════════════════════════════════════════

@router.get("/comparables")
async def comparables(
    sector: str = Query(None),
    cnae_code: str = Query(None),
    isin: str = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    """Public comparables for valuation. Usable by Valuation Engine."""
    t0 = time.time()
    from services.bme_intelligence import get_comparables_for_company
    result = await get_comparables_for_company(isin=isin, cnae_code=cnae_code, limit=limit)
    return {**_meta(t0), **result}


@router.get("/sector-leaders")
async def sector_leaders(limit: int = Query(10, ge=1, le=30)):
    """Top companies by market cap. Public endpoint."""
    t0 = time.time()
    from services.bme_intelligence import get_sector_leaders
    leaders = await get_sector_leaders(limit)
    return {**_meta(t0), "leaders": leaders, "count": len(leaders)}


@router.get("/sector-multiples")
async def sector_multiples():
    """Aggregate multiples by BME sector. For Valuation Engine."""
    t0 = time.time()
    from services.bme_intelligence import get_sector_multiples
    multiples = await get_sector_multiples()
    return {**_meta(t0), "sectors": multiples, "count": len(multiples)}


@router.post("/generate-events")
async def generate_events(user=Depends(get_current_user)):
    """Generate corporate events from BME data."""
    from services.bme_intelligence import generate_corporate_events
    return await generate_corporate_events()


@router.post("/integrate-economic")
async def integrate_economic(user=Depends(get_current_user)):
    """Integrate BME data into Economic Intelligence Layer."""
    from services.bme_intelligence import integrate_bme_with_economic_intelligence
    return await integrate_bme_with_economic_intelligence()
