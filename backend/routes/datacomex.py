"""DataComex Intelligence — API endpoints for trade data.

Namespace: /api/v1/datacomex
"""

from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File
from database import db
from models import now_iso
from auth_utils import get_current_user
from services.datacomex_connector import (
    sync_datacomex, process_csv_upload, rebuild_trade_metrics,
    rebuild_signals, rebuild_cnae_mappings, generate_seed_trade_data,
)
from services.taric_cnae_mapping import TARIC_CHAPTERS
import asyncio
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
_bg_tasks: set = set()

router = APIRouter(prefix="/api/v1/datacomex", tags=["datacomex"])

CONTRACT_VERSION = "1.0"


def _meta(t0):
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": now_iso(),
        "response_time_ms": round((time.time() - t0) * 1000, 1),
        "source": "DataComex — Ministerio de Industria, Comercio y Turismo",
    }


# ══════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════

@router.get("/dashboard")
async def dashboard(user=Depends(get_current_user)):
    """KPIs and summary for DataComex Intelligence."""
    t0 = time.time()

    raw_count = await db.datacomex_raw_data.count_documents({})
    metrics_count = await db.datacomex_trade_metrics.count_documents({})
    signals_count = await db.datacomex_signals.count_documents({})
    mappings_count = await db.taxonomy_mappings.count_documents({"source_taxonomy": "taric"})

    # Latest year metrics
    latest_metrics = await db.datacomex_trade_metrics.find(
        {"year": {"$ne": None}}, {"_id": 0}
    ).sort("year", -1).limit(100).to_list(100)

    latest_year = latest_metrics[0]["year"] if latest_metrics else None
    year_metrics = [m for m in latest_metrics if m.get("year") == latest_year]

    total_exports = sum(m.get("exports_eur", 0) for m in year_metrics)
    total_imports = sum(m.get("imports_eur", 0) for m in year_metrics)
    trade_balance = total_exports - total_imports

    # Top growing / declining
    with_yoy = [m for m in year_metrics if m.get("export_yoy_pct") is not None]
    top_growing = sorted(with_yoy, key=lambda x: x["export_yoy_pct"], reverse=True)[:5]
    top_declining = sorted(with_yoy, key=lambda x: x["export_yoy_pct"])[:5]

    # Last sync
    last_sync = await db.datacomex_sync_logs.find_one({}, {"_id": 0}, sort=[("synced_at", -1)])

    # Signals
    signals = await db.datacomex_signals.find({}, {"_id": 0}).sort("generated_at", -1).to_list(20)

    return {
        **_meta(t0),
        "kpis": {
            "latest_year": latest_year,
            "total_exports_eur": round(total_exports, 2),
            "total_imports_eur": round(total_imports, 2),
            "trade_balance_eur": round(trade_balance, 2),
            "raw_records": raw_count,
            "trade_metrics": metrics_count,
            "signals_active": signals_count,
            "cnae_mappings": mappings_count,
        },
        "top_growing_cnae": [{
            "taric_code": m["taric_code"],
            "taric_label": m.get("taric_label", ""),
            "export_yoy_pct": m["export_yoy_pct"],
            "exports_eur": m["exports_eur"],
        } for m in top_growing],
        "top_declining_cnae": [{
            "taric_code": m["taric_code"],
            "taric_label": m.get("taric_label", ""),
            "export_yoy_pct": m["export_yoy_pct"],
            "exports_eur": m["exports_eur"],
        } for m in top_declining],
        "signals": signals[:10],
        "last_sync": {
            "synced_at": last_sync.get("synced_at") if last_sync else None,
            "records_imported": last_sync.get("records_imported", 0) if last_sync else 0,
            "status": last_sync.get("status") if last_sync else "never",
            "trigger": last_sync.get("trigger") if last_sync else None,
        },
    }


# ══════════════════════════════════════════
# EXPORTS / IMPORTS / BALANCE
# ══════════════════════════════════════════

@router.get("/exports")
async def exports(
    year: int = Query(None),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(get_current_user),
):
    """Export data by TARIC chapter."""
    t0 = time.time()
    query = {}
    if year:
        query["year"] = year
    metrics = await db.datacomex_trade_metrics.find(
        query, {"_id": 0}
    ).sort([("exports_eur", -1)]).limit(limit).to_list(limit)

    return {**_meta(t0), "exports": metrics, "count": len(metrics)}


@router.get("/imports")
async def imports_data(
    year: int = Query(None),
    limit: int = Query(50, ge=1, le=100),
    user=Depends(get_current_user),
):
    """Import data by TARIC chapter."""
    t0 = time.time()
    query = {}
    if year:
        query["year"] = year
    metrics = await db.datacomex_trade_metrics.find(
        query, {"_id": 0}
    ).sort([("imports_eur", -1)]).limit(limit).to_list(limit)

    return {**_meta(t0), "imports": metrics, "count": len(metrics)}


@router.get("/trade-balance")
async def trade_balance(
    year: int = Query(None),
    user=Depends(get_current_user),
):
    """Trade balance by TARIC chapter."""
    t0 = time.time()
    query = {}
    if year:
        query["year"] = year
    metrics = await db.datacomex_trade_metrics.find(
        query, {"_id": 0}
    ).sort([("trade_balance_eur", -1)]).to_list(100)

    total_exports = sum(m.get("exports_eur", 0) for m in metrics)
    total_imports = sum(m.get("imports_eur", 0) for m in metrics)

    return {
        **_meta(t0),
        "year": year,
        "total_exports_eur": round(total_exports, 2),
        "total_imports_eur": round(total_imports, 2),
        "trade_balance_eur": round(total_exports - total_imports, 2),
        "coverage_ratio": round(total_exports / total_imports, 4) if total_imports > 0 else None,
        "by_chapter": metrics,
        "count": len(metrics),
    }


@router.get("/signals")
async def signals(user=Depends(get_current_user)):
    """Active trade signals."""
    t0 = time.time()
    sigs = await db.datacomex_signals.find({}, {"_id": 0}).sort("generated_at", -1).to_list(50)
    return {**_meta(t0), "signals": sigs, "count": len(sigs)}


@router.get("/history/{taric_code}")
async def taric_history(taric_code: str, user=Depends(get_current_user)):
    """Historical trade data for a specific TARIC chapter."""
    t0 = time.time()
    metrics = await db.datacomex_trade_metrics.find(
        {"taric_code": taric_code}, {"_id": 0}
    ).sort("year", 1).to_list(30)

    if not metrics:
        raise HTTPException(404, f"No data for TARIC {taric_code}")

    return {
        **_meta(t0),
        "taric_code": taric_code,
        "taric_label": TARIC_CHAPTERS.get(taric_code, ""),
        "history": metrics,
        "years": len(metrics),
    }


# ══════════════════════════════════════════
# CNAE MAPPINGS
# ══════════════════════════════════════════

@router.get("/mappings")
async def list_mappings(
    validated: bool = Query(None),
    user=Depends(get_current_user),
):
    """List TARIC → CNAE mappings."""
    t0 = time.time()
    query = {}
    if validated is not None:
        query["validated_by_human"] = validated

    mappings = await db.datacomex_cnae_mapping.find(
        query, {"_id": 0}
    ).sort([("taric_code", 1), ("cnae_code", 1)]).to_list(500)

    return {**_meta(t0), "mappings": mappings, "count": len(mappings)}


@router.post("/mappings/{taric_code}/{cnae_code}/approve")
async def approve_mapping(taric_code: str, cnae_code: str, user=Depends(get_current_user)):
    """Approve a TARIC→CNAE mapping."""
    r = await db.datacomex_cnae_mapping.update_one(
        {"taric_code": taric_code, "cnae_code": cnae_code},
        {"$set": {"validated_by_human": True, "validated_by": user.get("email"), "updated_at": now_iso()}}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Mapping not found")
    return {"status": "approved", "taric": taric_code, "cnae": cnae_code}


@router.post("/mappings/{taric_code}/{cnae_code}/reject")
async def reject_mapping(taric_code: str, cnae_code: str, user=Depends(get_current_user)):
    """Reject a TARIC→CNAE mapping."""
    await db.datacomex_cnae_mapping.delete_one(
        {"taric_code": taric_code, "cnae_code": cnae_code}
    )
    return {"status": "rejected", "taric": taric_code, "cnae": cnae_code}


from pydantic import BaseModel
from typing import Optional


class MappingEdit(BaseModel):
    confidence_score: Optional[float] = None
    cnae_code_new: Optional[str] = None


@router.put("/mappings/{taric_code}/{cnae_code}")
async def edit_mapping(taric_code: str, cnae_code: str, req: MappingEdit, user=Depends(get_current_user)):
    """Edit a TARIC→CNAE mapping."""
    update = {"updated_at": now_iso(), "validated_by": user.get("email")}
    if req.confidence_score is not None:
        update["confidence_score"] = req.confidence_score
    if req.cnae_code_new:
        update["cnae_code"] = req.cnae_code_new

    r = await db.datacomex_cnae_mapping.update_one(
        {"taric_code": taric_code, "cnae_code": cnae_code},
        {"$set": update}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Mapping not found")
    return {"status": "updated"}


# ══════════════════════════════════════════
# SYNC & ADMIN
# ══════════════════════════════════════════

@router.post("/sync")
async def sync(
    years: str = Query(None, description="Comma-separated years, e.g. '2023,2024,2025'"),
    user=Depends(get_current_user),
):
    """Lanza el sync REAL de DataComex (Playwright + rebuild) en segundo plano.

    Evita el Proxy Read Timeout de 120 s. Resultado: GET /datacomex/sync-state
    (status: running | done) con el mismo formato {sync, rebuild} que devolvia antes este endpoint.
    """
    year_list = [int(y.strip()) for y in years.split(",")] if years else None

    current = await db.datacomex_sync_state.find_one({"_id": "current"})
    if current and current.get("status") == "running":
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(current["started_at"].replace("Z", "+00:00"))).total_seconds()
        except (KeyError, ValueError):
            age = 9999
        if age < 1200:  # un "running" de >20 min se considera huerfano
            return {"status": "running", "started_at": current["started_at"]}

    started_at = now_iso()
    await db.datacomex_sync_state.replace_one(
        {"_id": "current"}, {"_id": "current", "status": "running", "started_at": started_at}, upsert=True)
    task = asyncio.create_task(_run_sync(year_list, started_at))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"status": "running", "started_at": started_at}


async def _run_sync(year_list, started_at):
    from services.datacomex_playwright import sync_via_playwright, post_sync_rebuild
    try:
        sync_result = await sync_via_playwright(years=year_list)
        rebuild_result = None
        if sync_result["status"] == "completed":
            rebuild_result = await post_sync_rebuild()
        result = {"sync": sync_result, "rebuild": rebuild_result}
    except Exception as e:
        logger.error(f"DataComex sync failed: {e}")
        result = {"sync": {"status": "error", "error": str(e)[:200]}, "rebuild": None}
    await db.datacomex_sync_state.replace_one(
        {"_id": "current"},
        {"_id": "current", "status": "done", "started_at": started_at,
         "finished_at": now_iso(), "result": result},
        upsert=True,
    )


@router.get("/sync-state")
async def sync_state(user=Depends(get_current_user)):
    """Estado del ultimo sync lanzado con POST /sync."""
    doc = await db.datacomex_sync_state.find_one({"_id": "current"}, {"_id": 0})
    return doc or {"status": "idle"}


@router.get("/sync-health")
async def sync_health(user=Depends(get_current_user)):
    """DataComex sync health: last sync, staleness, data origin."""
    from services.datacomex_playwright import get_sync_health
    return await get_sync_health()


@router.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...), user=Depends(get_current_user)):
    """Upload a DataComex CSV file manually."""
    content = await file.read()
    return await process_csv_upload(content, file.filename)


@router.post("/rebuild-metrics")
async def rebuild_metrics_endpoint(user=Depends(get_current_user)):
    """Rebuild trade metrics from raw data."""
    return await rebuild_trade_metrics()


@router.post("/rebuild-signals")
async def rebuild_signals_endpoint(user=Depends(get_current_user)):
    """Rebuild trade signals from metrics."""
    return await rebuild_signals()


@router.post("/rebuild-mappings")
async def rebuild_mappings_endpoint(user=Depends(get_current_user)):
    """Rebuild TARIC→CNAE mappings from defaults."""
    return await rebuild_cnae_mappings()


@router.post("/seed")
async def seed_data(user=Depends(get_current_user)):
    """Seed realistic trade data from official Spanish totals, then rebuild metrics + signals."""
    seed_result = await generate_seed_trade_data()
    metrics_result = await rebuild_trade_metrics()
    signals_result = await rebuild_signals()

    # Rebuild Economic Intelligence to include trade data
    from services.economic_intelligence import rebuild_economic_metrics, rebuild_economic_signals
    econ = await rebuild_economic_metrics()
    esig = await rebuild_economic_signals()

    return {
        "status": "completed",
        "seed": seed_result,
        "metrics": {"computed": metrics_result.get("metrics_computed", 0)},
        "signals": {"generated": signals_result.get("signals_generated", 0)},
        "economic_intelligence": {"metrics": econ.get("total_metrics", 0), "signals": esig.get("signals_generated", 0)},
    }
