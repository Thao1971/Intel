"""Signal Intelligence Engine API — the engine's own public contract (signal-intelligence-v1).

Decoupled, UI-agnostic (D8). Any consumer (arroba, Copilot, Recommendation/Strategy/
Transaction engines, external APIs) obtains ALL signal intelligence here, never from
master_companies directly. Protected with the service API key (X-API-Key).
"""

import asyncio
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from database import db
from auth_utils import get_current_user
from services.engines.signal import engine as sig_engine
from services.engines.signal import taxonomy, thresholds, actions, composites
from services.engines.signal import persistence as P
from services.engines.signal import borme_bridge as BB
from services.engines.signal import baselines as BL
from services.engines.signal import succession_intelligence as SI
from services import opportunity_view as OV
from services import opportunity_criteria as CR
from services import signal_recompute as SR
from services.service_auth import require_service_key
from routes import engine_schemas as S

router = APIRouter(prefix="/api/v1/signal-intelligence", tags=["signal_intelligence"])


def _ok(model):
    return {200: {"model": model, "description": "Successful Response"}}


class AnalyzeRequest(BaseModel):
    identifier: str
    windows: Optional[List[str]] = None


class SectorRequest(BaseModel):
    cnae_section: Optional[str] = None
    cnae_code: Optional[str] = None
    limit: int = 25


class TerritoryRequest(BaseModel):
    provincia: Optional[str] = None
    municipio: Optional[str] = None
    limit: int = 25


class OpportunitiesRequest(BaseModel):
    cnae_section: Optional[str] = None
    provincia: Optional[str] = None
    signal_types: Optional[List[str]] = None
    sort_by_dimension: str = "impact"
    new_since_days: Optional[int] = None  # Q4 — only signals first detected in the last N days
    trend: Optional[str] = None           # Q4 — "improving" | "worsening" | "stable"
    limit: int = 20


class SignalsListRequest(BaseModel):
    category: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = "active"
    signal_types: Optional[List[str]] = None
    provincia: Optional[str] = None
    cnae_section: Optional[str] = None
    master_id: Optional[str] = None
    sort_by: str = "last_seen_at"  # "last_seen_at" | "first_detected_at" | impact/confidence/urgency/persistence
    limit: int = 50


class HistoryRequest(BaseModel):
    identifier: str
    signal_type: Optional[str] = None


class BormeLinkBackfillRequest(BaseModel):
    limit_companies: int = 500


class BaselinesComputeRequest(BaseModel):
    limit_sectors: int = 50


@router.post("/analyze", responses=_ok(S.SignalAnalyzeResponse))
async def analyze(req: AnalyzeRequest, _key=Depends(require_service_key)):
    result = await sig_engine.analyze(req.identifier, windows=req.windows)
    if result is None:
        raise HTTPException(404, "company not found in Master Layer")
    return result


async def _aggregate(query: dict, limit: int):
    counts: dict = {}
    type_counts: dict = {}
    top: list = []
    n = 0
    async for m in db.master_companies.find(query, {"_id": 0, "master_id": 1}).limit(limit):
        prof = await sig_engine.analyze(m["master_id"])
        if not prof:
            continue
        n += 1
        for cat, c in prof["counts_by_category"].items():
            counts[cat] = counts.get(cat, 0) + c
        for s in prof["signals"]:
            type_counts[s["signal_type"]] = type_counts.get(s["signal_type"], 0) + 1
            # severity=="opportunity" is the actual "this is a good M&A opportunity" tag
            # (growth.revenue_surge/growth.sustained/ownership.consolidator all carry it
            # under category "growth"/"ownership", not "opportunity" — see taxonomy.py).
            # category=="opportunity" only covers succession signals; using it here silently
            # dropped the other 3 opportunity types (2026-07-23 fix).
            if s.get("severity") == "opportunity":
                top.append({"master_id": prof["master_id"], "name": prof["identity"]["name"],
                            "signal_type": s["signal_type"], "dimensions": s["dimensions"]})
    top.sort(key=lambda x: x["dimensions"]["impact"], reverse=True)
    return {"companies_analyzed": n, "counts_by_category": counts,
            "counts_by_type": type_counts, "top_opportunities": top[:10]}


@router.post("/sector", responses=_ok(S.SignalAggregateResponse))
async def by_sector(req: SectorRequest, _key=Depends(require_service_key)):
    if not req.cnae_section and not req.cnae_code:
        raise HTTPException(400, "cnae_section or cnae_code required")
    q = {"financials.latest.revenue": {"$ne": None}}
    if req.cnae_code:
        q["classification.cnae_code"] = req.cnae_code
    else:
        q["classification.cnae_section"] = req.cnae_section
    agg = await _aggregate(q, req.limit)
    return {"criteria": {"cnae_section": req.cnae_section, "cnae_code": req.cnae_code}, **agg,
            "engine_version": sig_engine.ENGINE_VERSION}


@router.post("/territory", responses=_ok(S.SignalAggregateResponse))
async def by_territory(req: TerritoryRequest, _key=Depends(require_service_key)):
    if not req.provincia and not req.municipio:
        raise HTTPException(400, "provincia or municipio required")
    q = {"financials.latest.revenue": {"$ne": None}}
    if req.municipio:
        q["location.municipio"] = req.municipio
    else:
        q["location.provincia"] = req.provincia
    agg = await _aggregate(q, req.limit)
    return {"criteria": {"provincia": req.provincia, "municipio": req.municipio}, **agg,
            "engine_version": sig_engine.ENGINE_VERSION}


async def _signal_stats(status: Optional[str] = "active") -> Dict:
    """True counts, decoupled from any pagination limit — the '/opportunities' and
    '/signals' list endpoints cap their `count` field at the query's `limit`
    (20-100), which is NOT a real total. Added 2026-07-23 because that distinction
    matters the moment someone asks "how many opportunities/signals are there" —
    the list endpoints alone can't answer that honestly at real data scale."""
    base_q = {"status": status} if status else {}

    total_signals = await db.signals.count_documents(base_q)
    total_opportunities = await db.signals.count_documents({**base_q, "severity": "opportunity"})

    by_severity = {}
    for sev in ("opportunity", "positive", "info", "warning", "risk", "critical"):
        c = await db.signals.count_documents({**base_q, "severity": sev})
        if c:
            by_severity[sev] = c

    by_category = {}
    for cat in taxonomy.CATEGORIES:
        c = await db.signals.count_documents({**base_q, "category": cat})
        if c:
            by_category[cat] = c

    by_opportunity_type = {}
    async for s in db.signals.find({**base_q, "severity": "opportunity"}, {"_id": 0, "signal_type": 1}):
        by_opportunity_type[s["signal_type"]] = by_opportunity_type.get(s["signal_type"], 0) + 1

    return {
        "status_filter": status or "all",
        "total_signals": total_signals,
        "total_opportunities": total_opportunities,
        "by_severity": by_severity,
        "by_category": by_category,
        "opportunities_by_type": by_opportunity_type,
        "engine_version": sig_engine.ENGINE_VERSION,
    }


@router.post("/stats")
async def signal_stats(status: Optional[str] = "active", _key=Depends(require_service_key)):
    """Real, non-paginated counts of signals/opportunities — see _signal_stats()."""
    return await _signal_stats(status)


@router.get("/stats/view")
async def signal_stats_view(status: Optional[str] = "active", user=Depends(get_current_user)):
    """Same as POST /stats, JWT-gated for the app's own frontend."""
    return await _signal_stats(status)


async def _list_opportunities(cnae_section: Optional[str], provincia: Optional[str],
                               signal_types: Optional[List[str]], sort_by_dimension: str,
                               new_since_days: Optional[int], trend: Optional[str], limit: int) -> Dict:
    """Shared query logic behind POST /opportunities (X-API-Key) and GET /opportunities/view
    (JWT, for the app's own frontend) — same convention as
    routes/investment_intelligence.py's fragmentation/rollup-thesis /view endpoints."""
    # severity=="opportunity" (NOT category=="opportunity") is the real "this is an M&A
    # opportunity" tag — covers growth.revenue_surge, growth.sustained, ownership.consolidator
    # and opportunity.succession_signal. category=="opportunity" alone only matches the
    # succession signal, which is why this used to silently return just one result.
    q = {"severity": "opportunity", "status": "active"}
    if signal_types:
        q["signal_type"] = {"$in": signal_types}
    if trend:
        q["trend"] = trend
    if new_since_days is not None:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=new_since_days)).isoformat()
        q["first_detected_at"] = {"$gte": cutoff}
    dim = sort_by_dimension if sort_by_dimension in ("impact", "confidence", "urgency", "persistence") else "impact"
    rows = []
    async for s in db.signals.find(q, {"_id": 0}).sort(f"dimensions.{dim}", -1).limit(limit * 3):
        m = await db.master_companies.find_one({"master_id": s["master_id"]},
                                               {"_id": 0, "identity.legal_name": 1,
                                                "classification.cnae_section": 1, "location.provincia": 1})
        if not m:
            continue
        if cnae_section and (m.get("classification") or {}).get("cnae_section") != cnae_section:
            continue
        if provincia and (m.get("location") or {}).get("provincia") != provincia:
            continue
        rows.append({"signal_id": s.get("signal_id"), "master_id": s["master_id"],
                     "name": (m.get("identity") or {}).get("legal_name"),
                     "signal_type": s["signal_type"], "dimensions": s["dimensions"],
                     "recommended_actions": s.get("recommended_actions"),
                     "explanation": s.get("explanation"), "is_composite": s.get("is_composite", False),
                     "first_detected_at": s.get("first_detected_at"), "last_seen_at": s.get("last_seen_at"),
                     "trend": s.get("trend"), "occurrences": s.get("occurrences")})
        if len(rows) >= limit:
            break
    return {"sorted_by": dim, "count": len(rows), "opportunities": rows,
            "engine_version": sig_engine.ENGINE_VERSION}


_CNAE_LABELS: Optional[Dict[str, str]] = None


async def _cnae_label_map() -> Dict[str, str]:
    """Etiquetas de sector en español (cnae_catalog: secciones, divisiones y grupos). Se cargan una vez."""
    global _CNAE_LABELS
    if _CNAE_LABELS is None:
        _CNAE_LABELS = {d["code"]: d["label"]
                        async for d in db.cnae_catalog.find({}, {"_id": 0, "code": 1, "label": 1})
                        if d.get("code") and d.get("label")}
    return _CNAE_LABELS


def _sector_label(classification: Dict, labels: Dict[str, str]) -> Optional[str]:
    for code in (classification.get("cnae_code"), classification.get("cnae_division"),
                 classification.get("cnae_section")):
        if code and code in labels:
            return labels[code]
    return None


_SECTOR_GROWTH_CACHE: Dict = {"at": 0.0, "data": {}}
_SECTOR_GROWTH_TTL_S = 3600


async def _sector_growth_baselines() -> Dict[str, Dict]:
    """Respaldo de la comparativa: p50/p75 del crecimiento interanual de ingresos por SECCIÓN CNAE (sin
    distinguir tamaño), calculado al vuelo sobre `master_companies` con >=2 ejercicios de ingresos
    positivos. Solo secciones con muestra >= BL.MIN_SAMPLE_SIZE. Caché de 1 h en proceso; si falla, {} y
    la tarjeta se queda con la comparativa por sector y tamaño (o sin comparativa). Sin escrituras."""
    import time
    if time.time() - _SECTOR_GROWTH_CACHE["at"] < _SECTOR_GROWTH_TTL_S:
        return _SECTOR_GROWTH_CACHE["data"]
    data: Dict[str, Dict] = {}
    try:
        pipeline = [
            {"$match": {"financials.history.1": {"$exists": True}, "classification.cnae_section": {"$ne": None}}},
            {"$project": {"_id": 0, "sec": "$classification.cnae_section",
                          "h": {"$slice": [{"$sortArray": {"input": "$financials.history", "sortBy": {"year": -1}}}, 2]}}},
            {"$addFields": {"r0": {"$arrayElemAt": ["$h.revenue", 0]}, "r1": {"$arrayElemAt": ["$h.revenue", 1]}}},
            {"$match": {"r0": {"$gt": 0}, "r1": {"$gt": 0}}},
            {"$addFields": {"yoy": {"$divide": [{"$subtract": ["$r0", "$r1"]}, "$r1"]}}},
            {"$group": {"_id": "$sec", "n": {"$sum": 1},
                        "p": {"$percentile": {"input": "$yoy", "p": [0.5, 0.75], "method": "approximate"}}}},
        ]
        async for d in db.master_companies.aggregate(pipeline):
            if d["n"] >= BL.MIN_SAMPLE_SIZE and d.get("p") and len(d["p"]) == 2:
                data[d["_id"]] = {"p50": round(d["p"][0], 4), "p75": round(d["p"][1], 4), "sample_size": d["n"]}
    except Exception:
        data = {}
    _SECTOR_GROWTH_CACHE.update(at=time.time(), data=data)
    return data


async def _opportunities_enriched(level: str, sort: str, provincia: Optional[str],
                                  cnae_section: Optional[str], signal_types: Optional[List[str]],
                                  sort_by_dimension: str, limit: int,
                                  mandate: Optional[Dict] = None, offset: int = 0,
                                  min_revenue: Optional[float] = None) -> Dict:
    """Listado por EMPRESA (no por señal) con nivel, serie, comparativa y prosa CF: ver
    services/opportunity_view.py. Consultas por lotes (señales, empresas, riesgos, baselines):
    cuatro viajes a la base, sin N+1. Las señales de oportunidad activas son ~700 (cota 5000)."""
    from datetime import date
    # Suelo de ingresos: el del mandato si lo tiene; si no, el configurado / por defecto (opportunity_criteria).
    floor, floor_source = CR.effective_min_revenue(mandate, min_revenue)
    dim = sort_by_dimension if sort_by_dimension in ("impact", "confidence", "urgency", "persistence") else "impact"
    # Las situaciones especiales (potential_distress) llevan severity "risk": se incluyen por tipo.
    q = {"status": "active", "$or": [{"severity": "opportunity"},
                                     {"signal_type": "opportunity.potential_distress"}]}
    if signal_types:
        q["signal_type"] = {"$in": signal_types}
    by_master: Dict[str, List[Dict]] = {}
    for s in await db.signals.find(q, {"_id": 0}).to_list(5000):
        by_master.setdefault(s["master_id"], []).append(s)
    ids = list(by_master)

    masters: Dict[str, Dict] = {}
    async for m in db.master_companies.find(
            {"master_id": {"$in": ids}},
            {"_id": 0, "master_id": 1, "cif_normalized": 1, "identity.legal_name": 1, "classification": 1,
             "location": 1, "financials.latest": 1, "financials.history": 1}):
        masters[m["master_id"]] = m

    blocked = set(await db.signals.distinct("master_id", {
        "status": "active", "master_id": {"$in": ids},
        "$or": [{"severity": {"$in": ["risk", "critical"]}},
                {"signal_type": {"$in": list(OV.BLOCKING_SIGNAL_TYPES)}}]}))

    baselines: Dict = {}
    async for b in db.sector_size_baselines.find({"metric": "revenue_growth_yoy"}, {"_id": 0}).sort("computed_at", 1):
        baselines[(b.get("sector"), b.get("size_band"))] = b   # la última versión calculada sobrescribe

    labels = await _cnae_label_map()
    sector_baselines = await _sector_growth_baselines()
    expected_year = date.today().year - 1
    cards = []
    for mid, sigs in by_master.items():
        m = masters.get(mid)
        if not m:
            continue
        cls = m.get("classification") or {}
        if provincia and (m.get("location") or {}).get("provincia") != provincia:
            continue
        # Señal principal: compuesta primero; luego la dimensión pedida; a igualdad, la más persistente
        # (una lectura multianual pesa más que un pico de un año).
        # Las señales dependientes del tamaño (sucesión) no se muestran por debajo del suelo.
        revenue = ((m.get("financials") or {}).get("latest") or {}).get("revenue")
        if not CR.meets_size_floor(revenue, floor):
            sigs = [s for s in sigs if s["signal_type"] not in CR.SIZE_GATED_SIGNAL_TYPES]
            if not sigs:
                continue
        primary = max(sigs, key=lambda s: (bool(s.get("is_composite")) and s["signal_type"] != "opportunity.potential_distress",
                                           (s.get("dimensions") or {}).get(dim) or 0,
                                           (s.get("dimensions") or {}).get("persistence") or 0))
        band = BL.size_band_for(((m.get("financials") or {}).get("latest") or {}).get("revenue"))
        cards.append(OV.build_card(
            primary=primary, all_types=[s["signal_type"] for s in sigs], master=m, band=band,
            baseline=baselines.get((cls.get("cnae_section"), band)),
            sector_label=_sector_label(cls, labels), has_blocking_risk=mid in blocked,
            expected_year=expected_year, min_revenue=floor,
            sector_baseline=sector_baselines.get(cls.get("cnae_section"))))

    # Sectores disponibles (con el resto de filtros aplicados salvo el propio sector) para el desplegable.
    sec_counts: Dict[str, int] = {}
    for c in cards:
        if c.get("cnae_section"):
            sec_counts[c["cnae_section"]] = sec_counts.get(c["cnae_section"], 0) + 1
    sectors = sorted(({"code": k, "label": labels.get(k) or k, "count": v} for k, v in sec_counts.items()),
                     key=lambda x: (-x["count"], x["label"]))
    if cnae_section:
        cards = [c for c in cards if c.get("cnae_section") == cnae_section]
    counts = {lv: 0 for lv in OV.LEVEL_ORDER}
    for c in cards:
        counts[c["level"]] += 1
    if level in OV.LEVEL_ORDER:
        cards = [c for c in cards if c["level"] == level]
    if sort == "recent":
        cards.sort(key=lambda c: c["signal"].get("first_detected_at") or "", reverse=True)
    else:
        cards.sort(key=lambda c: (OV.LEVEL_ORDER[c["level"]],
                                  -((c["signal"].get("dimensions") or {}).get(dim) or 0), c["name"] or ""))
    page = cards[offset:offset + limit]
    return {"level_counts": counts, "sectors": sectors, "count": len(page), "matching": len(cards), "offset": offset,
            "sorted_by": "recent" if sort == "recent" else f"relevance/{dim}",
            "opportunities": page, "engine_version": sig_engine.ENGINE_VERSION,
            "criteria": {"min_revenue_eur": floor, "source": floor_source,
                         "mandate_id": (mandate or {}).get("mandate_id"),
                         "succession_min_tenure_years": CR.SUCCESSION_MIN_TENURE_YEARS}}


async def _opportunities_feed(days: int, limit: int, cnae_section: Optional[str],
                               provincia: Optional[str]) -> Dict:
    """Shared query logic behind GET /opportunities/feed (X-API-Key) and
    GET /opportunities/feed/view (JWT)."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    # severity=="opportunity" — same taxonomy fix as _list_opportunities() above.
    q = {"severity": "opportunity", "status": "active", "first_detected_at": {"$gte": cutoff}}
    rows = []
    async for s in db.signals.find(q, {"_id": 0}).sort("first_detected_at", -1).limit(limit * 3):
        m = await db.master_companies.find_one({"master_id": s["master_id"]},
                                               {"_id": 0, "identity.legal_name": 1,
                                                "classification.cnae_section": 1, "location.provincia": 1})
        if not m:
            continue
        if cnae_section and (m.get("classification") or {}).get("cnae_section") != cnae_section:
            continue
        if provincia and (m.get("location") or {}).get("provincia") != provincia:
            continue
        rows.append({"signal_id": s.get("signal_id"), "master_id": s["master_id"],
                     "name": (m.get("identity") or {}).get("legal_name"),
                     "signal_type": s["signal_type"], "dimensions": s["dimensions"],
                     "explanation": s.get("explanation"), "is_composite": s.get("is_composite", False),
                     "first_detected_at": s.get("first_detected_at"), "trend": s.get("trend")})
        if len(rows) >= limit:
            break
    return {"window_days": days, "since": cutoff, "count": len(rows), "opportunities": rows,
            "engine_version": sig_engine.ENGINE_VERSION}


async def _list_signals(category: Optional[str], severity: Optional[str], status: Optional[str],
                         signal_types: Optional[List[str]], provincia: Optional[str],
                         cnae_section: Optional[str], master_id: Optional[str],
                         sort_by: str, limit: int) -> Dict:
    """General-purpose signal listing across ALL categories/severities/status — powers the
    Señales screen (distinct from the curated Oportunidades screen, which only shows
    severity=='opportunity'). Same master_companies-join/filter pattern as
    _list_opportunities() above, without the opportunity-only restriction."""
    q: dict = {}
    if master_id:
        q["master_id"] = master_id
    if status:
        q["status"] = status
    if category:
        q["category"] = category
    if severity:
        q["severity"] = severity
    if signal_types:
        q["signal_type"] = {"$in": signal_types}
    if sort_by in ("impact", "confidence", "urgency", "persistence"):
        sort_field = f"dimensions.{sort_by}"
    elif sort_by == "first_detected_at":
        sort_field = "first_detected_at"
    else:
        sort_field = "last_seen_at"
    rows = []
    async for s in db.signals.find(q, {"_id": 0}).sort(sort_field, -1).limit(limit * 3):
        m = await db.master_companies.find_one({"master_id": s["master_id"]},
                                               {"_id": 0, "identity.legal_name": 1,
                                                "classification.cnae_section": 1, "location.provincia": 1})
        if not m:
            continue
        if cnae_section and (m.get("classification") or {}).get("cnae_section") != cnae_section:
            continue
        if provincia and (m.get("location") or {}).get("provincia") != provincia:
            continue
        rows.append({"signal_id": s["signal_id"], "master_id": s["master_id"],
                     "name": (m.get("identity") or {}).get("legal_name"),
                     "signal_type": s["signal_type"], "category": s.get("category"),
                     "severity": s.get("severity"), "polarity": s.get("polarity"),
                     "status": s.get("status"), "dimensions": s.get("dimensions"),
                     "recommended_actions": s.get("recommended_actions"),
                     "explanation": s.get("explanation"), "is_composite": s.get("is_composite", False),
                     "first_detected_at": s.get("first_detected_at"), "last_seen_at": s.get("last_seen_at"),
                     "trend": s.get("trend"), "occurrences": s.get("occurrences")})
        if len(rows) >= limit:
            break
    return {"sorted_by": sort_field, "count": len(rows), "signals": rows,
            "engine_version": sig_engine.ENGINE_VERSION}


@router.post("/signals")
async def signals_list(req: SignalsListRequest, _key=Depends(require_service_key)):
    """General-purpose signal listing — ALL categories/severities, not just opportunities.
    Powers the Señales screen. Complements /opportunities (curated severity=='opportunity'
    subset only)."""
    return await _list_signals(req.category, req.severity, req.status, req.signal_types,
                               req.provincia, req.cnae_section, req.master_id, req.sort_by, req.limit)


@router.get("/signals/view")
async def signals_list_view(category: Optional[str] = None, severity: Optional[str] = None,
                             status: Optional[str] = "active", signal_types: Optional[str] = None,
                             provincia: Optional[str] = None, cnae_section: Optional[str] = None,
                             master_id: Optional[str] = None, sort_by: str = "last_seen_at",
                             limit: int = 50, user=Depends(get_current_user)):
    """Same as POST /signals, JWT-gated for the app's own frontend (Señales screen).
    signal_types is a comma-separated string here (query params can't carry a list cleanly)."""
    types = [t.strip() for t in signal_types.split(",") if t.strip()] if signal_types else None
    return await _list_signals(category, severity, status, types, provincia, cnae_section,
                               master_id, sort_by, limit)


@router.post("/opportunities", responses=_ok(S.SignalOpportunitiesResponse))
async def opportunities(req: OpportunitiesRequest, _key=Depends(require_service_key)):
    """Q4 — Ranking of opportunities from persisted signals (populated at scale by
    `bootstrap.py::build_signals_canonical()`; run /bootstrap or /analyze/​/sector first).
    `new_since_days`/`trend` use the lifecycle fields `persistence.py::persist()` already
    tracks (`first_detected_at`, `trend`) — no new data, just exposing what was write-only."""
    return await _list_opportunities(req.cnae_section, req.provincia, req.signal_types,
                                     req.sort_by_dimension, req.new_since_days, req.trend, req.limit)


@router.get("/opportunities/feed")
async def opportunities_feed(days: int = 7, limit: int = 50, cnae_section: Optional[str] = None,
                              provincia: Optional[str] = None, _key=Depends(require_service_key)):
    """Q4 — chronological feed: opportunities FIRST DETECTED in the last N days, newest
    first. Complements /opportunities (ranked snapshot by impact) with the "what's new
    since I last checked" view the roadmap names — same underlying data, different sort."""
    return await _opportunities_feed(days, limit, cnae_section, provincia)


# ── JWT-friendly variants for the app's own frontend (same convention as
# routes/investment_intelligence.py wrapping fragmentation/rollup-thesis: the endpoints
# above use X-API-Key for external/service consumers, which a browser can never safely
# hold — these call the exact same query logic, just gated by the logged-in user's
# session instead). ──

@router.get("/opportunities/view", responses=_ok(S.SignalOpportunitiesResponse))
async def opportunities_view(cnae_section: Optional[str] = None, provincia: Optional[str] = None,
                              signal_types: Optional[str] = None, sort_by_dimension: str = "impact",
                              new_since_days: Optional[int] = None, trend: Optional[str] = None,
                              limit: int = 20, user=Depends(get_current_user)):
    """Same as POST /opportunities, JWT-gated for the app's own frontend.
    signal_types is a comma-separated string here (query params can't carry a list cleanly)."""
    types = [t.strip() for t in signal_types.split(",") if t.strip()] if signal_types else None
    return await _list_opportunities(cnae_section, provincia, types, sort_by_dimension,
                                     new_since_days, trend, limit)


@router.get("/opportunities/feed/view")
async def opportunities_feed_view(days: int = 7, limit: int = 50, cnae_section: Optional[str] = None,
                                   provincia: Optional[str] = None, user=Depends(get_current_user)):
    """Same as GET /opportunities/feed, JWT-gated for the app's own frontend."""
    return await _opportunities_feed(days, limit, cnae_section, provincia)


@router.get("/opportunities/enriched/view")
async def opportunities_enriched_view(level: str = "all", sort: str = "relevance",
                                      provincia: Optional[str] = None, cnae_section: Optional[str] = None,
                                      signal_types: Optional[str] = None, sort_by_dimension: str = "impact",
                                      limit: int = 30, offset: int = 0, mandate_id: Optional[str] = None,
                                      min_revenue: Optional[float] = None,
                                      user=Depends(get_current_user)):
    """Beta — listado por EMPRESA con nivel (opportunity | candidate | indicio | verify), serie de
    ingresos, comparativa con su sector y tamaño, cautelas y titular en prosa CF. Aditivo: no altera
    /opportunities ni /opportunities/view. `level_counts` cuenta empresas (tras provincia/sector).
    Suelo de ingresos (nivel Oportunidad y sucesión): 1 M€ por defecto, configurable con
    ARROBA_MIN_REVENUE_EUR, y sobrescrito por `mandate_id` (su `revenue_min`); ver `criteria` en la respuesta.
    Paginación: `limit` (máx. 100) y `offset`; `matching` es el total tras los filtros.
    `min_revenue` (euros) sobrescribe el suelo: es lo que envía el front de Beta con el mandato de compra del
    usuario (a través de la pasarela no se debe usar `mandate_id`, que no comprueba la propiedad del mandato)."""
    types = [t.strip() for t in signal_types.split(",") if t.strip()] if signal_types else None
    mandate = None
    if mandate_id:
        from services.engines.recommendation import mandates as M
        mandate = await M.get_mandate(mandate_id)
        if mandate is None:
            raise HTTPException(status_code=404, detail="mandate not found")
    return await _opportunities_enriched(level, sort, provincia, cnae_section, types,
                                         sort_by_dimension, max(1, min(limit, 100)), mandate, max(0, offset),
                                         min_revenue)


@router.get("/catalog/view", responses=_ok(S.SignalCatalogResponse))
async def catalog_view(user=Depends(get_current_user)):
    """Same as GET /catalog, JWT-gated — lets the frontend show human-readable signal
    type labels/categories/actions for the Opportunities screen's filters."""
    return await catalog()


@router.post("/migrate-dedupe")
async def migrate_dedupe(_key=Depends(require_service_key)):
    """One-time ops action (2026-07-23 signal-identity fix): merges duplicate signal
    documents left by deliveries that ran before source_version was removed from the
    signal key, then builds the new unique index. Safe to run once before the next
    delivery; a no-op if there's nothing left to merge. See P.migrate_dedupe_and_reindex()."""
    return await P.migrate_dedupe_and_reindex()


@router.get("/catalog", responses=_ok(S.SignalCatalogResponse))
async def catalog(_key=Depends(require_service_key)):
    return {"taxonomy_version": taxonomy.TAXONOMY_VERSION,
            "thresholds_version": thresholds.THRESHOLDS_VERSION,
            "actions_version": actions.ACTIONS_VERSION,
            "composites_version": composites.COMPOSITES_VERSION,
            "categories": taxonomy.CATEGORIES,
            "signal_types": taxonomy.catalog(),
            "canonical_actions": actions.CANONICAL_ACTIONS,
            "composites": [{"signal_type": k, **{kk: vv for kk, vv in v.items() if kk != "description"},
                            "description": v["description"]} for k, v in composites.COMPOSITES.items()]}


@router.get("/signal/{signal_id}", responses=_ok(S.SignalRecord))
async def get_signal(signal_id: str, _key=Depends(require_service_key)):
    s = await P.get_signal(signal_id)
    if not s:
        raise HTTPException(404, "signal not found")
    return s


@router.get("/signal/{signal_id}/view", responses=_ok(S.SignalRecord))
async def get_signal_view(signal_id: str, user=Depends(get_current_user)):
    """Same as GET /signal/{signal_id}, JWT-gated — lets Oportunidades/Watchlist/Señales
    link directly to a signal's own detail view."""
    s = await P.get_signal(signal_id)
    if not s:
        raise HTTPException(404, "signal not found")
    return s


@router.post("/recompute")
async def recompute_signals(limit: Optional[int] = None, cnae_section: Optional[str] = None,
                            only_with_financials: bool = False, min_revenue: Optional[float] = None,
                            workers: int = 1, dry_run: bool = False,
                            _key=Depends(require_service_key)):
    """Recalcula y persiste las señales (solo señales, sin el bootstrap completo). Acotable con `cnae_section`,
    `limit`, `only_with_financials` (solo empresas con cuentas en `norm_financials`) y `min_revenue` (ingresos
    máximos declarados >= ese valor; implica cuentas). `workers` analiza varias empresas a la vez (tope
    `MAX_WORKERS`). Con `dry_run=true` solo cuenta a quién se recalcularía, sin ejecutar nada.
    Devuelve un `run_id` para consultar el avance en GET /recompute/{run_id}. Cierra las señales que ya no se
    cumplen (`disappeared`)."""
    q: Dict = {"status": "active"}
    if cnae_section:
        q["classification.cnae_section"] = cnae_section
    if only_with_financials or min_revenue is not None:
        grp: List[Dict] = [{"$group": {"_id": "$cif_normalized", "maxrev": {"$max": "$revenue"}}}]
        if min_revenue is not None:
            grp.append({"$match": {"maxrev": {"$gte": float(min_revenue)}}})
        cifs = [d["_id"] async for d in db.norm_financials.aggregate(grp, allowDiskUse=True) if d.get("_id")]
        q["identity.cif"] = {"$in": cifs}
    ids = await db.master_companies.distinct("master_id", q)
    if limit and limit > 0:
        ids = ids[:limit]
    n_workers = SR.clamp_workers(workers)
    criteria = {"cnae_section": cnae_section, "only_with_financials": only_with_financials,
                "min_revenue": min_revenue, "limit": limit, "workers": n_workers}
    if dry_run:
        return {"dry_run": True, "companies": len(ids), "criteria": criteria}
    run_id = "sigrec_" + uuid.uuid4().hex[:12]
    asyncio.create_task(SR.run_recompute(run_id, ids, workers=n_workers))
    return {"run_id": run_id, "companies": len(ids), "status": "started", "criteria": criteria,
            "poll": f"/api/v1/signal-intelligence/recompute/{run_id}"}


@router.get("/recompute/{run_id}")
async def recompute_status(run_id: str, _key=Depends(require_service_key)):
    doc = await db.signal_recompute_runs.find_one({"run_id": run_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="run not found")
    return doc


@router.post("/borme/link-new-events")
async def borme_link_new_events(limit_events: int = 20000, recheck: bool = False,
                                _key=Depends(require_service_key)):
    """Enlace por EVENTOS de BORME con el Master (idempotente, diario). Sustituye en la práctica al enlace
    por empresa, cuya marca de "revisada" se puso antes de que llegaran los eventos."""
    return await BB.link_new_events(limit_events=max(1, min(limit_events, 100000)), recheck=recheck)


@router.post("/history", responses=_ok(S.SignalHistoryResponse))
async def history(req: HistoryRequest, _key=Depends(require_service_key)):
    master = await db.master_companies.find_one(
        {"$or": [{"master_id": req.identifier}, {"cif_normalized": req.identifier}]},
        {"_id": 0, "master_id": 1})
    if not master:
        raise HTTPException(404, "company not found in Master Layer")
    return {"master_id": master["master_id"],
            "signals": await P.get_history(master["master_id"], req.signal_type)}


@router.get("/history/view", responses=_ok(S.SignalHistoryResponse))
async def history_view(identifier: str, signal_type: Optional[str] = None,
                        user=Depends(get_current_user)):
    """Same as POST /history, JWT-gated — the signal detail view's timeline (used from
    Señales, and from Oportunidades/Watchlist once a signal reference is clicked through)."""
    master = await db.master_companies.find_one(
        {"$or": [{"master_id": identifier}, {"cif_normalized": identifier}]},
        {"_id": 0, "master_id": 1})
    if not master:
        raise HTTPException(404, "company not found in Master Layer")
    return {"master_id": master["master_id"],
            "signals": await P.get_history(master["master_id"], signal_type)}


@router.post("/borme-link-backfill")
async def borme_link_backfill(req: BormeLinkBackfillRequest, _key=Depends(require_service_key)):
    """Q1 admin trigger: batch-link BORME events to master_companies (idempotent,
    watermarked by `borme_link_checked_at`). Run repeatedly until `companies_remaining` is 0."""
    return await BB.link_events_to_master(limit_companies=req.limit_companies)


@router.post("/baselines/compute")
async def compute_baselines(req: BaselinesComputeRequest, _key=Depends(require_service_key)):
    """Q3 admin trigger: recompute sector x size_band percentile baselines from
    companies already analyzed by the Financial Intelligence Engine. Re-run periodically
    (e.g. monthly) as more companies/financials get ingested."""
    return await BL.compute_sector_size_baselines(limit_sectors=req.limit_sectors)


@router.get("/baselines/status")
async def baselines_status(_key=Depends(require_service_key)):
    """Coverage check: how many (sector, size_band, metric) buckets have a usable
    baseline (>= MIN_SAMPLE_SIZE), broken down by metric."""
    buckets = await db.sector_size_baselines.find(
        {"baselines_version": BL.BASELINES_VERSION}, {"_id": 0}).to_list(5000)
    by_metric: dict = {}
    for b in buckets:
        m = b["metric"]
        by_metric.setdefault(m, {"buckets": 0, "companies_covered": 0})
        by_metric[m]["buckets"] += 1
        by_metric[m]["companies_covered"] += b.get("sample_size", 0)
    return {"total_buckets": len(buckets), "min_sample_size": BL.MIN_SAMPLE_SIZE,
            "by_metric": by_metric, "baselines_version": BL.BASELINES_VERSION}


@router.get("/succession-profile/{identifier}")
async def succession_profile(identifier: str, _key=Depends(require_service_key)):
    """E2 — full Succession Intelligence profile for one company (master_id or CIF).
    Richer than the `opportunity.succession_signal` pass/fail: exposes admin_count,
    family-surname overlap (proxy, not confirmed kinship), a possible successor already
    appointed, company age (when a BORME constitution event is linked), and whether
    financial-stagnation signals are active — plus the 0-100 succession_risk_score and
    the human-readable reasons behind it. Returns null profile (not 404) when there's an
    administrator record but E2 has nothing further to add beyond Q1's own signal."""
    master = await db.master_companies.find_one(
        {"$or": [{"master_id": identifier}, {"cif_normalized": identifier}]}, {"_id": 0})
    if not master:
        raise HTTPException(404, "company not found in Master Layer")
    profile = await SI.build_profile(master)
    return {"master_id": master["master_id"], "profile": profile}
