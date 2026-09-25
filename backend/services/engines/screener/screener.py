"""Company Screener — filtro multi-criterio sobre `master_companies`.

Rutas de campo (idénticas a las que ya usa `recommendation/mandates.py`, verificadas
contra `services/data_layer/master/master_builder.py`):

    identity.legal_name            -> nombre
    classification.cnae_section    -> sección CNAE (INDEXADO)
    classification.cnae_code       -> CNAE 4 dígitos
    location.provincia             -> provincia
    financials.latest.revenue      -> facturación (€)
    financials.latest.ebitda       -> EBITDA (€)
    financials.latest.ebitda_margin-> margen EBITDA (ratio 0-1, YA almacenado)
    financials.latest.employees    -> empleados
    financials.latest.year         -> ejercicio
    financials.history[]           -> {year, revenue, ebitda}  (para crecimiento)
    status                         -> "active" | ...
    db.signals                     -> señales por empresa {master_id, signal_type, category, status}

CRECIMIENTO: se deriva de los dos primeros ejercicios de `financials.history`, colección
que el Master Builder conserva en orden descendente. Así funciona con MongoDB anterior a
5.2 y el stage solo se añade cuando hace falta filtrar, ordenar o mostrar crecimiento.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import re

from database import db

# ── Catálogo de señales expuestas como filtro (signal_type reales del motor) ──
# Mapea etiqueta de negocio -> signal_type(s) reales en db.signals.
SIGNAL_FILTER_MAP: Dict[str, List[str]] = {
    "succession": ["opportunity.succession_signal"],
    "consolidation": ["opportunity.consolidation_candidate", "market.fragmented_sector"],
    "growth": ["growth.revenue_surge", "growth.sustained", "growth.ebitda_expansion"],
    "outperformer": ["market.outperforms_peers"],
    "hidden_gem": ["opportunity.hidden_gem"],
    "expansion": ["opportunity.expansion_opportunity"],
    "distress": ["opportunity.potential_distress", "risk.sustained_decline",
                 "risk.revenue_decline", "risk.dissolution_signal"],
}
# Señales que definen el estado "en dificultad".
DISTRESS_SIGNALS: List[str] = SIGNAL_FILTER_MAP["distress"]

SORTABLE = {
    "revenue": "financials.latest.revenue",
    "ebitda": "financials.latest.ebitda",
    "ebitda_margin": "financials.latest.ebitda_margin",
    "employees": "size.employees_total",
    "name": "identity.legal_name",
    "growth": "growth_yoy",  # requiere el stage de crecimiento
}

REVENUE_BUCKETS = [0, 1_000_000, 5_000_000, 10_000_000, 50_000_000, 1e12]
REVENUE_BUCKET_LABELS = ["<1M", "1-5M", "5-10M", "10-50M", ">50M"]

_INDEXED = False


async def ensure_indexes() -> None:
    """Índices para que el screener y sus facetas rindan. `cnae_section` ya está
    indexado por el master_builder; añadimos el resto de campos filtrables."""
    global _INDEXED
    if _INDEXED:
        return
    await db.master_companies.create_index("location.provincia")
    await db.master_companies.create_index("financials.latest.revenue")
    await db.master_companies.create_index("size.employees_total")
    await db.master_companies.create_index("financials.latest.ebitda")
    await db.master_companies.create_index("financials.latest.ebitda_margin")
    await db.master_companies.create_index("classification.cnae_code")
    await db.master_companies.create_index("status")
    await db.signals.create_index([("signal_type", 1), ("status", 1)])
    _INDEXED = True


def _range(field: str, lo: Optional[float], hi: Optional[float]) -> Optional[Dict]:
    r: Dict[str, float] = {}
    if lo is not None:
        r["$gte"] = lo
    if hi is not None:
        r["$lte"] = hi
    return {field: r} if r else None


def _build_match(f: Dict[str, Any]) -> Tuple[Dict[str, Any], List[List[str]]]:
    """Construye el `$match` nativo y los grupos de señales requeridos.

    Las señales se resuelven posteriormente con `$lookup`; nunca se materializan millones
    de `master_id` dentro de un `$in`, que podría superar el límite BSON de MongoDB.
    """
    m: Dict[str, Any] = {}
    and_clauses: List[Dict] = []

    # Sector
    if f.get("cnae_codes"):
        m["classification.cnae_code"] = {"$in": f["cnae_codes"]}
    elif f.get("cnae_sections"):
        m["classification.cnae_section"] = {"$in": f["cnae_sections"]}

    # Territorio
    if f.get("provincias"):
        m["location.provincia"] = {"$in": f["provincias"]}

    # Rangos financieros
    for field, lo, hi in [
        ("financials.latest.revenue", f.get("revenue_min"), f.get("revenue_max")),
        ("size.employees_total", f.get("employees_min"), f.get("employees_max")),
        ("financials.latest.ebitda", f.get("ebitda_min"), f.get("ebitda_max")),
        ("financials.latest.ebitda_margin", f.get("ebitda_margin_min"), f.get("ebitda_margin_max")),
    ]:
        rng = _range(field, lo, hi)
        if rng:
            m.update(rng)

    # Año
    if f.get("year") is not None:
        m["financials.latest.year"] = f["year"]

    # Texto (nombre / CIF / razón social)
    if f.get("query"):
        q = str(f["query"]).strip()
        if q:
            safe_q = re.escape(q)
            and_clauses.append({"$or": [
                {"identity.legal_name": {"$regex": safe_q, "$options": "i"}},
                {"identity.commercial_name": {"$regex": safe_q, "$options": "i"}},
                {"identity.aliases": {"$regex": safe_q, "$options": "i"}},
                {"identity.cif": {"$regex": f"^{safe_q}", "$options": "i"}},
            ]})

    # Estado
    estado = f.get("estado") or "active"
    signal_id_sets: List[List[str]] = []
    if estado == "active":
        m["status"] = "active"
    elif estado == "distressed":
        signal_id_sets.append(DISTRESS_SIGNALS)
    # "all" -> sin filtro de estado

    # Señal de mercado (filtro explícito)
    if f.get("signals"):
        types: List[str] = []
        for s in f["signals"]:
            types.extend(SIGNAL_FILTER_MAP.get(s, [s]))  # acepta etiqueta o signal_type crudo
        signal_id_sets.append(list(set(types)))

    if and_clauses:
        m["$and"] = and_clauses
    return m, signal_id_sets


def _growth_stages(gmin: Optional[float], gmax: Optional[float], for_filter: bool) -> List[Dict]:
    """Deriva growth_yoy de `financials.history`, ya ordenado newest-first."""
    stages: List[Dict] = [
        {"$addFields": {
            "_rev0": {"$arrayElemAt": [{"$ifNull": ["$financials.history.revenue", []]}, 0]},
            "_rev1": {"$arrayElemAt": [{"$ifNull": ["$financials.history.revenue", []]}, 1]},
        }},
        {"$addFields": {"growth_yoy": {"$cond": [
            {"$and": [{"$gt": ["$_rev1", 0]}, {"$ne": ["$_rev0", None]}]},
            {"$divide": [{"$subtract": ["$_rev0", "$_rev1"]}, "$_rev1"]},
            None]}}},
    ]
    if for_filter:
        gr = _range("growth_yoy", gmin, gmax)
        if gr:
            stages.append({"$match": gr})
    return stages


def _sort_spec(sort_by: Optional[str], sort_dir: Optional[str]) -> Dict[str, int]:
    field = SORTABLE.get(sort_by or "revenue", "financials.latest.revenue")
    direction = -1 if (sort_dir or "desc") == "desc" else 1
    return {field: direction}


def _row_project() -> Dict[str, Any]:
    return {"$project": {
        "_id": 0,
        "master_id": 1,
        "cif": "$identity.cif",
        "name": "$identity.legal_name",
        "cnae_section": "$classification.cnae_section",
        "cnae_code": "$classification.cnae_code",
        "provincia": "$location.provincia",
        "revenue": "$financials.latest.revenue",
        "ebitda": "$financials.latest.ebitda",
        "ebitda_margin": "$financials.latest.ebitda_margin",
        "employees": "$size.employees_total",
        "year": "$financials.latest.year",
        "growth_yoy": {"$ifNull": ["$growth_yoy", None]},
        "status": 1,
        "signals": {"$map": {"input": {"$ifNull": ["$_signals", []]},
                             "as": "s", "in": "$$s.signal_type"}},
    }}


def _facet_stages() -> Dict[str, List[Dict]]:
    return {
        "by_cnae_section": [
            {"$group": {"_id": "$classification.cnae_section", "count": {"$sum": 1}}},
            {"$match": {"_id": {"$ne": None}}},
            {"$sort": {"count": -1}},
            {"$project": {"_id": 0, "key": "$_id", "count": 1}},
        ],
        "by_provincia": [
            {"$group": {"_id": "$location.provincia", "count": {"$sum": 1}}},
            {"$match": {"_id": {"$ne": None}}},
            {"$sort": {"count": -1}},
            {"$limit": 30},
            {"$project": {"_id": 0, "key": "$_id", "count": 1}},
        ],
        "by_revenue_bucket": [
            {"$bucket": {
                "groupBy": "$financials.latest.revenue",
                "boundaries": REVENUE_BUCKETS,
                "default": "unknown",
                "output": {"count": {"$sum": 1}},
            }},
        ],
    }


def _signal_filter_stages(groups: List[List[str]]) -> List[Dict]:
    if not groups:
        return []
    wanted = sorted({signal for group in groups for signal in group})
    requirements = []
    for group in groups:
        requirements.append({"$gt": [{"$size": {"$filter": {
            "input": "$_filter_signals", "as": "signal",
            "cond": {"$in": ["$$signal.signal_type", group]},
        }}}, 0]})
    return [
        {"$lookup": {
            "from": "signals", "let": {"mid": "$master_id"},
            "pipeline": [{"$match": {"$expr": {"$and": [
                {"$eq": ["$master_id", "$$mid"]}, {"$eq": ["$status", "active"]},
                {"$in": ["$signal_type", wanted]},
            ]}}}, {"$project": {"_id": 0, "signal_type": 1}}],
            "as": "_filter_signals",
        }},
        {"$match": {"$expr": {"$and": requirements}}},
    ]


async def _base_pipeline(f: Dict[str, Any], needs_growth: bool) -> List[Dict]:
    match, signal_groups = _build_match(f)
    pipeline: List[Dict] = [{"$match": match}]
    pipeline += _signal_filter_stages(signal_groups)
    if needs_growth:
        pipeline += _growth_stages(f.get("growth_yoy_min"), f.get("growth_yoy_max"), for_filter=True)
    return pipeline


async def screen(f: Dict[str, Any], offset: int = 0, limit: int = 25,
                 sort_by: Optional[str] = None, sort_dir: Optional[str] = None) -> Dict[str, Any]:
    await ensure_indexes()
    growth_filter = f.get("growth_yoy_min") is not None or f.get("growth_yoy_max") is not None
    sort_growth = (sort_by == "growth")
    base = await _base_pipeline(f, needs_growth=growth_filter)

    # Sub-pipeline de filas (paginado + señales por empresa + crecimiento para display)
    rows_stages: List[Dict] = [{"$sort": _sort_spec(sort_by, sort_dir)}]
    # Si se ordena por crecimiento pero no se filtró por él, hay que derivarlo antes del sort
    if sort_growth and not growth_filter:
        rows_stages = _growth_stages(None, None, for_filter=False) + rows_stages
    rows_stages += [
        {"$skip": max(0, offset)},
        {"$limit": max(1, min(limit, 100))},
    ]
    # crecimiento para display cuando no se derivó ya
    if not growth_filter and not sort_growth:
        rows_stages += _growth_stages(None, None, for_filter=False)
    rows_stages += [
        {"$lookup": {
            "from": "signals",
            "let": {"mid": "$master_id"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$master_id", "$$mid"]},
                    {"$eq": ["$status", "active"]},
                ]}}},
                {"$project": {"_id": 0, "signal_type": 1}},
                {"$limit": 12},
            ],
            "as": "_signals",
        }},
        _row_project(),
    ]

    facets = _facet_stages()
    pipeline = base + [{"$facet": {
        "rows": rows_stages,
        "total": [{"$count": "n"}],
        **facets,
    }}]

    agg = await db.master_companies.aggregate(pipeline, allowDiskUse=True).to_list(1)
    out = agg[0] if agg else {}
    total = (out.get("total") or [{}])[0].get("n", 0)
    return {
        "total": total,
        "results": out.get("rows", []),
        "facets": _shape_facets(out),
        "applied_filters": {k: v for k, v in f.items() if v not in (None, [], "")},
        "offset": offset,
        "limit": limit,
        "engine_version": "screener-v1",
    }


async def count(f: Dict[str, Any]) -> Dict[str, Any]:
    """Variante ligera: solo total + facetas (para el contador en vivo)."""
    await ensure_indexes()
    growth_filter = f.get("growth_yoy_min") is not None or f.get("growth_yoy_max") is not None
    base = await _base_pipeline(f, needs_growth=growth_filter)
    facets = _facet_stages()
    pipeline = base + [{"$facet": {"total": [{"$count": "n"}], **facets}}]
    agg = await db.master_companies.aggregate(pipeline, allowDiskUse=True).to_list(1)
    out = agg[0] if agg else {}
    total = (out.get("total") or [{}])[0].get("n", 0)
    return {"total": total, "facets": _shape_facets(out), "engine_version": "screener-v1"}


def _shape_facets(out: Dict[str, Any]) -> Dict[str, Any]:
    buckets = out.get("by_revenue_bucket", []) or []
    rev_facet = []
    for b in buckets:
        bid = b.get("_id")
        if isinstance(bid, (int, float)) and bid in REVENUE_BUCKETS:
            idx = REVENUE_BUCKETS.index(bid)
            label = REVENUE_BUCKET_LABELS[idx] if idx < len(REVENUE_BUCKET_LABELS) else str(bid)
        else:
            label = "sin dato"
        rev_facet.append({"key": label, "count": b.get("count", 0)})
    return {
        "cnae_section": out.get("by_cnae_section", []),
        "provincia": out.get("by_provincia", []),
        "revenue_bucket": rev_facet,
    }
