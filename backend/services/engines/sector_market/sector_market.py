"""Sector Market — 4 motores de dato real por sector (CNAE).

Colecciones (verificadas en Intel-190926):
  master_companies            classification.cnae_code/cnae_division, financials.history[{year,revenue}]
  borme_events                publication_date, cnae_division, event_type
  transactions_normalized     date, year, cis_category_suggested, mapped_category_name,
                              sector_original, target_name, buyer_name, ev_eurm, ebitda_eurm,
                              revenue_eurm, ev_ebitda, ev_revenue, publish_status, deleted
  public_procurement_contracts buyer_name, amount, cpv_code
Helper: services.cnae_catalog.cpv_to_cnae_division (cpv -> división CNAE).
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

from database import db

try:
    from services.cnae_catalog import cpv_to_cnae_division  # type: ignore
except Exception:  # pragma: no cover - fallback defensivo
    def cpv_to_cnae_division(cpv: str) -> Optional[str]:
        return None


def _division(cnae: str) -> str:
    """División = 2 primeros dígitos del CNAE (sección tipo 'J' se deja tal cual)."""
    c = (cnae or "").strip()
    digits = "".join(ch for ch in c if ch.isdigit())
    return digits[:2] if digits else c


def _median(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs), 2) if xs else None


# ── 1) Crecimiento real por subsector ─────────────────────────────────────────
async def growth_by_sector(cnae: str) -> Dict[str, Any]:
    """Agrega revenue por año sobre las empresas del CNAE (match por prefijo de
    cnae_code, para que funcione a nivel sección/división/código)."""
    match: Dict[str, Any] = {"$or": [
        {"classification.cnae_code": {"$regex": f"^{cnae}"}},
        {"classification.cnae_division": _division(cnae)},
    ]}
    pipeline = [
        {"$match": match},
        {"$project": {"hist": {"$ifNull": ["$financials.history", []]}}},
        {"$unwind": "$hist"},
        {"$match": {"hist.year": {"$ne": None}, "hist.revenue": {"$ne": None}}},
        {"$group": {"_id": "$hist.year",
                    "revenue_total": {"$sum": "$hist.revenue"},
                    "companies": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    rows = await db.master_companies.aggregate(pipeline, allowDiskUse=True).to_list(50)
    series = [{"year": r["_id"], "revenue_total": round(r["revenue_total"], 2),
               "companies": r["companies"]} for r in rows if r.get("_id")]

    yoy = None
    cagr_3y = None
    if len(series) >= 2 and series[-2]["revenue_total"]:
        yoy = round((series[-1]["revenue_total"] / series[-2]["revenue_total"] - 1), 4)
    if len(series) >= 4 and series[-4]["revenue_total"] > 0:
        cagr_3y = round((series[-1]["revenue_total"] / series[-4]["revenue_total"]) ** (1 / 3) - 1, 4)

    return {"cnae": cnae, "series": series, "yoy_latest": yoy, "cagr_3y": cagr_3y,
            "coverage_note": "Agregado real de revenue por ejercicio; cobertura = empresas con financials.history."}


# ── 2) Serie mensual de BORME por CNAE ────────────────────────────────────────
async def borme_monthly(cnae: str, months: int = 24) -> Dict[str, Any]:
    """Cuenta eventos BORME por mes para la división del CNAE.
    Asume publication_date en ISO 'YYYY-MM-DD...' (string) o fecha; usa substr sobre string."""
    division = _division(cnae)
    pipeline = [
        {"$match": {"cnae_division": division, "publication_date": {"$ne": None}}},
        {"$project": {"month": {"$substrCP": [{"$toString": "$publication_date"}, 0, 7]}}},
        {"$group": {"_id": "$month", "count": {"$sum": 1}}},
        {"$sort": {"_id": -1}},
        {"$limit": max(1, min(months, 120))},
    ]
    rows = await db.borme_events.aggregate(pipeline).to_list(120)
    series = [{"month": r["_id"], "count": r["count"]} for r in rows if r.get("_id")]
    series.reverse()  # cronológico ascendente
    total = await db.borme_events.count_documents({"cnae_division": division})
    return {"cnae": cnae, "division": division, "series": series, "total": total,
            "coverage_note": "Serie mensual real por división CNAE; solo eventos BORME con cnae_division etiquetada."}


# ── 3) Operaciones M&A del sector ─────────────────────────────────────────────
async def ma_deals(cnae: str, category: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    """Operaciones reales de transactions_normalized para el sector.

    JOIN A VALIDAR: transactions_normalized se indexa por CATEGORÍA CIS
    (mapped_category_name / cis_category_suggested / sector_original), no por CNAE.
    - Si se pasa `category`, se filtra por esa categoría (recomendado desde la ficha).
    - Si no, se intenta casar por texto de la descripción CNAE contra sector_original.
    """
    base: Dict[str, Any] = {"deleted": {"$ne": True}, "publish_status": "approved_for_cis"}
    if category:
        base["$or"] = [{"mapped_category_name": category},
                       {"cis_category_suggested": category},
                       {"sector_original": category}]
    else:
        # Fallback best-effort por descripción CNAE
        doc = await db.master_companies.find_one(
            {"classification.cnae_code": {"$regex": f"^{cnae}"}},
            {"_id": 0, "classification.cnae_description": 1})
        desc = ((doc or {}).get("classification") or {}).get("cnae_description")
        if desc:
            base["sector_original"] = {"$regex": desc.split()[0], "$options": "i"}

    deals = await db.transactions_normalized.find(base, {"_id": 0}).sort("date", -1).to_list(500)
    ev_ebitda = [d.get("ev_ebitda") for d in deals if isinstance(d.get("ev_ebitda"), (int, float))]
    ev_revenue = [d.get("ev_revenue") for d in deals if isinstance(d.get("ev_revenue"), (int, float))]
    ev_total = sum(d.get("ev_eurm") or 0 for d in deals)

    recent = [{"target_name": d.get("target_name"), "buyer_name": d.get("buyer_name"),
               "date": d.get("date"), "year": d.get("year"),
               "ev_eurm": d.get("ev_eurm"), "ev_ebitda": d.get("ev_ebitda"),
               "ev_revenue": d.get("ev_revenue")} for d in deals[:limit]]

    return {"cnae": cnae, "category": category,
            "deals_count": len(deals),
            "ev_total_eurm": round(ev_total, 2) if ev_total else 0,
            "ev_ebitda_median": _median(ev_ebitda),
            "ev_revenue_median": _median(ev_revenue),
            "recent": recent,
            "coverage_note": "Operaciones reales (base CIS approved_for_cis). Join CNAE↔categoría CIS a validar; pasar `category` desde la ficha para exactitud."}


# ── 4) Top organismos (contratación pública) por sector ───────────────────────
async def top_buyers(cnae: str, limit: int = 10) -> Dict[str, Any]:
    """Lee compradores públicos precomputados; nunca agrega contratos en la petición."""
    division = _division(cnae)
    rows = await db.sector_top_buyers.find(
        {"division": division}, {"_id": 0}
    ).sort("amount_eur", -1).limit(limit).to_list(limit)
    return {"cnae": cnae, "division": division, "buyers": rows,
            "coverage_note": "Top organismos precomputado durante el rebuild sectorial (cpv→CNAE)."}
