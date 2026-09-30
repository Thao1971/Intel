"""Intelligence Sync Status — Public endpoint for sync metadata.

100% dynamic. The source list comes exclusively from the Intelligence Engine
(`engine_info.get_all_sources()`) and every per-source metric is computed at
runtime from each source module's own `META` descriptor + its MongoDB collection
+ `er_audit_logs` + `economic_signals`.

ZERO hardcoded source arrays/dicts. Adding a new source module (with its META and
a profile entry) makes it appear here automatically — no changes to this file.
"""

import asyncio
import time

from fastapi import APIRouter

from database import db
from models import now_iso
from services.intelligence_engine import engine_info

router = APIRouter(prefix="/api/v1/public/intelligence", tags=["intelligence_status"])


async def _source_status(name: str) -> dict:
    """Compute the live status row for a single engine source from its META."""
    meta = engine_info.get_source_meta(name)

    coll = meta["collection"]
    records = await db[coll].count_documents({}) if coll else 0

    signals_count = 0
    if meta["signal_source"]:
        tag = meta["signal_source"]
        signals_count = await db.economic_signals.count_documents(
            {"$or": [{"signal_source": tag}, {"sources_used": tag}]}
        )

    audit = None
    if meta["audit_action"]:
        audit = await db.er_audit_logs.find_one(
            {"action": meta["audit_action"]}, {"_id": 0}, sort=[("started_at", -1)]
        )

    # Product-facing status (backward-compatible labels consumed by the UI).
    if meta["phase"] == "stub":
        status = "pending"
    elif records > 0:
        status = "active"
    else:
        status = "empty"

    # ── "Última actualización" — uniform across every source ─────────────────
    # Priority: audited engine ingestion → source sync-log → freshest document.
    last_run = last_status = duration_ms = inserted_count = updated_count = error_count = None

    if audit:
        last_run = audit.get("started_at")
        last_status = audit.get("status")
        duration_ms = audit.get("duration_ms")
        inserted_count = audit.get("inserted_count")
        updated_count = audit.get("updated_count")
        error_count = audit.get("error_count")

    if not last_run and meta.get("sync_log"):
        sl = meta["sync_log"]
        try:
            doc = await db[sl["collection"]].find_one({}, {"_id": 0}, sort=[(sl["time_field"], -1)])
        except Exception:
            doc = None
        if doc:
            last_run = doc.get(sl["time_field"])
            last_status = doc.get("status")
            inserted_count = (doc.get("total_imported") or doc.get("records_imported")
                              or doc.get("observations_inserted") or doc.get("events_extracted")
                              or doc.get("processed"))
            error_count = doc.get("errors") if isinstance(doc.get("errors"), int) else None

    if not last_run and records > 0:
        # Fallback: newest document timestamp (only small/derived collections reach here).
        ts_field = meta.get("timestamp_field")
        candidates = [ts_field] if ts_field else ["ingested_at", "imported_at", "synced_at", "last_edited_at", "last_updated", "created_at"]
        for f in candidates:
            if not f:
                continue
            try:
                doc = await db[coll].find_one({f: {"$exists": True}}, {f: 1, "_id": 0}, sort=[(f, -1)])
            except Exception:
                doc = None
            if doc and doc.get(f):
                last_run = doc[f]
                last_status = last_status or "data"
                break

    # Normalize status label for the UI (green when healthy).
    if last_status in ("completed", "success", "ok", "data"):
        last_status = "ok"
    elif last_status:
        last_status = "error" if last_status in ("failed", "error") else last_status

    return {
        "name": meta["display_name"],
        "source": name,
        "phase": meta["phase"],
        "frequency": meta["frequency"],
        "records": records,
        "signals_count": signals_count,
        "supports_manual_ingestion": meta["supports_manual_ingestion"],
        "supports_sample": meta["supports_sample"],
        "queryable": meta["queryable"],
        "actions": meta["actions"],
        "display_fields": meta["display_fields"],
        "hidden_fields": meta["hidden_fields"],
        "field_labels": meta["field_labels"],
        # Última actualización (uniforme): audit → sync-log → timestamp del dato.
        "last_run": last_run,
        "last_status": last_status,
        "duration_ms": duration_ms,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "error_count": error_count,
        # Backward-compat fields kept for legacy consumers.
        "last_update": last_run,
        "status": status,
        "signals": signals_count,
    }


@router.get("/sync-status")
async def sync_status():
    """Dynamic sync status for every Intelligence Engine source + legacy modules."""
    t0 = time.time()

    # ── Legacy intelligence modules (sector/geo/cross) — backward compat ─────
    modules = ["sector_intelligence", "geo_intelligence", "cross_intelligence", "economic_intelligence"]
    status = {}
    for mod in modules:
        doc = await db.intelligence_sync_log.find_one({"module": mod}, {"_id": 0})
        status[mod] = {
            "last_synced_at": doc.get("synced_at") if doc else None,
            "status": doc.get("status") if doc else "never",
            "entries": doc.get("entries", 0) if doc else 0,
            "trigger": doc.get("trigger") if doc else None,
        }
    status["sector_intelligence"]["current_count"] = await db.sector_intelligence.count_documents({})
    status["geo_intelligence"]["current_count"] = await db.geo_intelligence.count_documents({})
    status["cross_intelligence"]["current_count"] = await db.sector_geo_cross.count_documents({})
    status["economic_intelligence"]["current_count"] = await db.economic_metrics.count_documents({})

    # ── Dynamic source breakdown — derived from the engine, never hardcoded ──
    source_names = engine_info.get_all_sources()
    rows = await asyncio.gather(*[_source_status(n) for n in source_names])
    sources = {row["source"]: row for row in rows}

    response = {
        "generated_at": now_iso(),
        "response_time_ms": round((time.time() - t0) * 1000, 1),
        "engine": engine_info.get_engine_identity(),
        "source_count": len(sources),
        "modules": status,
        "schedule": {
            "sector_intelligence": "Diario — 04:00 Madrid",
            "geo_intelligence": "Diario — 04:05 Madrid",
            "cross_intelligence": "Diario — 04:10 Madrid",
            "economic_intelligence": "Diario — 04:15 Madrid",
        },
        "sources": sources,
    }

    # DataComex sync health + stale alert.
    try:
        from services.datacomex_playwright import get_sync_health
        dcx_health = await get_sync_health()
        response["datacomex_health"] = dcx_health
        if dcx_health.get("stale"):
            response.setdefault("alerts", []).append({
                "type": "stale_source",
                "source": "DataComex",
                "message": f"DataComex lleva {dcx_health['days_since_sync']} dias sin actualizarse (limite: 45)",
                "severity": "warning",
            })
    except Exception:
        pass

    return response


@router.get("/data-updated")
async def data_updated():
    """For Arroba — returns only 'Datos actualizados: DD/MM/YYYY'. No technical info."""
    t0 = time.time()

    latest = await db.intelligence_sync_log.find(
        {"status": "completed"}, {"_id": 0, "synced_at": 1}
    ).sort("synced_at", -1).limit(1).to_list(1)

    if latest and latest[0].get("synced_at"):
        from datetime import datetime as dt
        iso = latest[0]["synced_at"]
        try:
            d = dt.fromisoformat(iso.replace("Z", "+00:00"))
            date_str = d.strftime("%d/%m/%Y")
        except Exception:
            date_str = iso[:10]
    else:
        date_str = None

    return {
        "datos_actualizados": date_str,
        "response_time_ms": round((time.time() - t0) * 1000, 1),
    }
