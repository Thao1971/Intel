"""Banco de España + Macro Intelligence — All endpoints.

Public (no auth): homepage, macro-indicators, signals, intelligence context
Admin (auth): refresh, status
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from database import db
from models import now_iso
from auth_utils import get_current_user
from services.banco_espana_service import refresh_all_indicators, INDICATOR_MAP
from services.macro_intelligence import compute_semantic_signal, compute_macro_context
import asyncio
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
_bg_tasks: set = set()

router = APIRouter(tags=["macro_intelligence"])

CONTRACT_VERSION = "2.0"


def _response_meta(start_time: float) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": now_iso(),
        "response_time_ms": round((time.time() - start_time) * 1000, 1),
        "source": "Banco de Espana",
        "source_attribution": "Datos oficiales del Banco de Espana. Series temporales publicas.",
    }


# ══════════════════════════════════════════
# PUBLIC — HOMEPAGE (Arroba consumption)
# ══════════════════════════════════════════

@router.get("/api/v1/public/homepage/macro")
async def homepage_macro():
    """Lightweight homepage-ready macro indicators. Only featured + secondary."""
    t0 = time.time()

    all_inds = await db.macro_indicators.find(
        {"source": "banco_espana", "status": "ok"}, {"_id": 0, "raw_payload": 0}
    ).sort("date", -1).to_list(50)

    # Deduplicate by key
    seen = {}
    for ind in all_inds:
        k = ind["indicator_key"]
        if k not in seen:
            seen[k] = ind

    featured = []
    secondary = []
    for key, ind in seen.items():
        config = INDICATOR_MAP.get(key, {})
        card = {
            "indicator_key": key,
            "indicator_name": ind.get("indicator_name") or config.get("name"),
            "value": ind.get("value"),
            "unit": ind.get("unit") or config.get("unit"),
            "yoy_change_pct": ind.get("yoy_change_pct"),
            "change_pct": ind.get("change_pct"),
            "trend_direction": ind.get("trend_direction"),
            "trend_strength": ind.get("trend_strength"),
            "sparkline_points": ind.get("sparkline_points", []),
            "date": ind.get("date"),
            "last_updated_at": ind.get("last_updated_at"),
        }
        if config.get("homepage"):
            featured.append(card)
        else:
            secondary.append(card)

    featured.sort(key=lambda x: INDICATOR_MAP.get(x["indicator_key"], {}).get("display_priority", 10))
    secondary.sort(key=lambda x: INDICATOR_MAP.get(x["indicator_key"], {}).get("display_priority", 10))

    return {**_response_meta(t0), "featured": featured, "secondary": secondary}


# ══════════════════════════════════════════
# PUBLIC — ALL INDICATORS
# ══════════════════════════════════════════

@router.get("/api/v1/public/macro-indicators")
async def get_macro_indicators():
    """Public: All latest macro indicators with semantic data."""
    t0 = time.time()

    all_inds = await db.macro_indicators.find(
        {"source": "banco_espana", "status": "ok"}, {"_id": 0, "raw_payload": 0}
    ).sort("date", -1).to_list(50)

    seen = {}
    for ind in all_inds:
        k = ind["indicator_key"]
        if k not in seen:
            config = INDICATOR_MAP.get(k, {})
            signal = compute_semantic_signal(
                k, ind.get("value", 0),
                yoy_pct=ind.get("yoy_change_pct"),
                trend_dir=ind.get("trend_direction"),
                trend_str=ind.get("trend_strength"),
            )
            seen[k] = {
                "indicator_key": k,
                "indicator_name": ind.get("indicator_name") or config.get("name"),
                "description": config.get("description"),
                "category": ind.get("category") or config.get("category"),
                "value": ind.get("value"),
                "unit": ind.get("unit") or config.get("unit"),
                "frequency": ind.get("frequency") or config.get("frequency"),
                "previous_value": ind.get("previous_value"),
                "change_pct": ind.get("change_pct"),
                "yoy_change_pct": ind.get("yoy_change_pct"),
                "trend_direction": ind.get("trend_direction"),
                "trend_strength": ind.get("trend_strength"),
                "sparkline_points": ind.get("sparkline_points", []),
                "display_priority": ind.get("display_priority") or config.get("display_priority", 10),
                "homepage": ind.get("homepage") or config.get("homepage", False),
                "date": ind.get("date"),
                "last_updated_at": ind.get("last_updated_at"),
                "semantic": signal,
            }

    return {**_response_meta(t0), "indicators": sorted(seen.values(), key=lambda x: x["display_priority"]), "count": len(seen)}


@router.get("/api/v1/public/macro-indicators/{indicator_key}/history")
async def get_indicator_history(indicator_key: str, limit: int = Query(24, ge=1, le=120)):
    """Public: Historical values for an indicator."""
    t0 = time.time()
    config = INDICATOR_MAP.get(indicator_key)
    if not config:
        return {**_response_meta(t0), "indicator_key": indicator_key, "status": "unknown_indicator", "history": []}

    history = await db.macro_indicators.find(
        {"indicator_key": indicator_key, "source": "banco_espana"},
        {"_id": 0, "raw_payload": 0}
    ).sort("date", -1).limit(limit).to_list(limit)

    return {
        **_response_meta(t0),
        "indicator_key": indicator_key,
        "indicator_name": config["name"],
        "description": config.get("description"),
        "category": config["category"],
        "unit": config["unit"],
        "frequency": config["frequency"],
        "history": history,
        "count": len(history),
    }


# ══════════════════════════════════════════
# PUBLIC — SEMANTIC SIGNALS
# ══════════════════════════════════════════

@router.get("/api/v1/public/macro/signals")
async def get_macro_signals():
    """Public: Semantic signals for all macro indicators."""
    t0 = time.time()

    all_inds = await db.macro_indicators.find(
        {"source": "banco_espana", "status": "ok"}, {"_id": 0}
    ).sort("date", -1).to_list(50)

    seen = {}
    for ind in all_inds:
        k = ind["indicator_key"]
        if k not in seen:
            seen[k] = ind

    signals = []
    for key, ind in seen.items():
        config = INDICATOR_MAP.get(key, {})
        sig = compute_semantic_signal(
            key, ind.get("value", 0),
            yoy_pct=ind.get("yoy_change_pct"),
            trend_dir=ind.get("trend_direction"),
            trend_str=ind.get("trend_strength"),
        )
        sig["value"] = ind.get("value")
        sig["unit"] = ind.get("unit") or config.get("unit")
        sig["indicator_name"] = ind.get("indicator_name") or config.get("name")
        sig["homepage_priority"] = config.get("display_priority", 10)
        sig["date"] = ind.get("date")
        signals.append(sig)

    # Aggregate macro context
    macro_ctx = compute_macro_context(signals)

    return {**_response_meta(t0), "signals": signals, "macro_context": macro_ctx, "count": len(signals)}


# ══════════════════════════════════════════
# INTERNAL — INTELLIGENCE (Valuo consumption)
# ══════════════════════════════════════════

@router.get("/api/v1/internal/intelligence/macro-context")
async def intelligence_macro_context():
    """Internal: Aggregated macro context for Valuo intelligence."""
    t0 = time.time()

    all_inds = await db.macro_indicators.find(
        {"source": "banco_espana", "status": "ok"}, {"_id": 0}
    ).sort("date", -1).to_list(50)

    seen = {}
    for ind in all_inds:
        k = ind["indicator_key"]
        if k not in seen:
            seen[k] = ind

    signals = [compute_semantic_signal(k, ind.get("value", 0), yoy_pct=ind.get("yoy_change_pct"), trend_dir=ind.get("trend_direction"), trend_str=ind.get("trend_strength")) for k, ind in seen.items()]
    macro_ctx = compute_macro_context(signals)

    return {**_response_meta(t0), "macro_context": macro_ctx, "signals_count": len(signals)}


@router.get("/api/v1/internal/intelligence/financing-context")
async def intelligence_financing_context():
    """Internal: Financing context for Valuo valuation/reporting."""
    t0 = time.time()

    euribor = await db.macro_indicators.find_one(
        {"indicator_key": "euribor_12m", "source": "banco_espana", "status": "ok"},
        {"_id": 0}, sort=[("date", -1)]
    )
    bce = await db.macro_indicators.find_one(
        {"indicator_key": "bce_main_rate", "source": "banco_espana", "status": "ok"},
        {"_id": 0}, sort=[("date", -1)]
    )
    credit = await db.macro_indicators.find_one(
        {"indicator_key": "credit_private_sector", "source": "banco_espana", "status": "ok"},
        {"_id": 0}, sort=[("date", -1)]
    )

    return {
        **_response_meta(t0),
        "euribor_12m": {"value": euribor.get("value") if euribor else None, "unit": "%", "yoy_pct": euribor.get("yoy_change_pct") if euribor else None, "trend": euribor.get("trend_direction") if euribor else None, "date": euribor.get("date") if euribor else None},
        "bce_rate": {"value": bce.get("value") if bce else None, "unit": "%", "yoy_pct": bce.get("yoy_change_pct") if bce else None, "trend": bce.get("trend_direction") if bce else None, "date": bce.get("date") if bce else None},
        "credit_volume": {"value": credit.get("value") if credit else None, "unit": "M EUR", "trend": credit.get("trend_direction") if credit else None, "date": credit.get("date") if credit else None},
        "financing_assessment": "improving" if euribor and euribor.get("trend_direction") == "down" else "tightening" if euribor and euribor.get("trend_direction") == "up" else "stable",
    }


# ══════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════

@router.post("/api/v1/admin/data-sources/banco-espana/refresh")
async def admin_refresh(user=Depends(get_current_user)):
    """Lanza el refresco en segundo plano (evita el Proxy Read Timeout de 120 s).

    El cliente consulta GET .../banco-espana/status hasta que status != "running".
    """
    email = user.get("email", user.get("id"))
    current = await db.data_provider_status.find_one({"provider": "banco_espana"}, {"_id": 0})
    if current and current.get("status") == "running" and current.get("started_at"):
        # Ignora un "running" huerfano de hace mas de 10 min (proceso reiniciado)
        started = current["started_at"]
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()
        except ValueError:
            age = 9999
        if age < 600:
            return {"status": "running", "started_at": started}

    started_at = now_iso()
    await db.data_provider_status.update_one(
        {"provider": "banco_espana"},
        {"$set": {"status": "running", "started_at": started_at, "last_error": None}},
        upsert=True,
    )
    task = asyncio.create_task(refresh_all_indicators(email))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"status": "running", "started_at": started_at}


@router.get("/api/v1/admin/data-sources/banco-espana/status")
async def admin_status(user=Depends(get_current_user)):
    status = await db.data_provider_status.find_one({"provider": "banco_espana"}, {"_id": 0})
    total = await db.macro_indicators.count_documents({"source": "banco_espana"})

    indicators = []
    for key, config in INDICATOR_MAP.items():
        latest = await db.macro_indicators.find_one(
            {"indicator_key": key, "source": "banco_espana"}, {"_id": 0},
            sort=[("date", -1)]
        )
        indicators.append({
            "indicator_key": key, "name": config["name"], "series_id": config["series_id"],
            "category": config["category"], "unit": config["unit"],
            "latest_value": latest.get("value") if latest else None,
            "latest_date": latest.get("date") if latest else None,
            "trend": latest.get("trend_direction") if latest else None,
            "homepage": config.get("homepage", False),
            "priority": config.get("display_priority", 10),
        })

    return {
        "provider": "banco_espana", "total_records": total,
        "status": status.get("status") if isinstance(status, dict) else "inactive",
        "last_sync_at": status.get("last_sync_at") if isinstance(status, dict) else None,
        "last_error": status.get("last_error") if isinstance(status, dict) else None,
        "indicators": indicators, "configured_series": len(INDICATOR_MAP),
    }
