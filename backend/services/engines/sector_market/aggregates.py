"""Agregados por sector (precomputados) para la home "Analizar sectores".

Ranking de sectores por Tamaño / Crecimiento / Margen EBITDA / Fragmentación, en
dos lentes: taxonomía ARROBA (11 sectores, `company_fingerprint.primary_sector`)
y CNAE (secciones, `classification.cnae_section`).

Patrón `category_valuations`: se PRECOMPUTA (`rebuild_sector_aggregates`) y se
persiste en `db.sector_aggregates`; el endpoint de ranking solo LEE (rápido). El
rebuild es la parte cara (recorre `master_companies`) y se lanza en el arranque /
nocturno, no en cada carga de página.

Fragmentación = (1 − HHI)·100 sobre la facturación de las empresas del sector
(0 = monopolio, 100 = muy fragmentado → candidato a roll-up). No depende de deals.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from typing import Any, Dict, List, Optional

from database import db

logger = logging.getLogger(__name__)
_rebuild_task: Optional[asyncio.Task] = None

try:
    from services.cnae_catalog import cpv_to_cnae_division
except Exception:  # pragma: no cover
    def cpv_to_cnae_division(cpv: str) -> Optional[str]:
        return None

CNAE_SECTION_LABELS = {
    "A": "Agricultura", "B": "Industrias extractivas", "C": "Industria manufacturera",
    "D": "Energía", "E": "Agua y residuos", "F": "Construcción", "G": "Comercio",
    "H": "Transporte y logística", "I": "Hostelería", "J": "Información y comunicaciones",
    "K": "Finanzas y seguros", "L": "Inmobiliario", "M": "Profesional y técnico",
    "N": "Servicios administrativos", "O": "Administración pública", "P": "Educación",
    "Q": "Sanidad", "R": "Arte y ocio", "S": "Otros servicios",
}


async def _sector_labels() -> Dict[str, str]:
    """S01..S11 -> etiqueta, desde el registry de taxonomía ARROBA."""
    try:
        from services.taxonomy import registry
        nodes = registry.build_nodes()
        return {n["id"]: n.get("label_es") for n in nodes if n.get("level") == "sector"}
    except Exception:
        return {}


def _median(xs: List[float]) -> Optional[float]:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs), 4) if xs else None


def _hhi_fragmentation(revenues: List[float]) -> Optional[float]:
    revs = [r for r in revenues if isinstance(r, (int, float)) and r > 0]
    total = sum(revs)
    if total <= 0 or len(revs) < 2:
        return None
    hhi = sum((r / total) ** 2 for r in revs)
    return round((1 - hhi) * 100, 1)


def _cagr(year_rev: Dict[int, float]) -> Optional[float]:
    years = sorted(y for y in year_rev if year_rev.get(y))
    if len(years) < 2:
        return None
    last = years[-1]
    base = years[-4] if len(years) >= 4 else years[0]
    n = last - base
    if n <= 0 or year_rev[base] <= 0:
        return None
    return round((year_rev[last] / year_rev[base]) ** (1 / n) - 1, 4)


def _new_bucket() -> Dict[str, Any]:
    return {"revs": [], "margins": [], "year_rev": {}, "companies": 0}


def _accumulate(bucket: Dict[str, Any], rev, margin, hist):
    bucket["companies"] += 1
    if isinstance(rev, (int, float)):
        bucket["revs"].append(rev)
    if isinstance(margin, (int, float)):
        bucket["margins"].append(margin)
    for h in (hist or []):
        y, r = h.get("year"), h.get("revenue")
        if isinstance(y, int) and isinstance(r, (int, float)):
            bucket["year_rev"][y] = bucket["year_rev"].get(y, 0) + r


def _finish(code: str, label: str, lens: str, level: str, b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "lens": lens, "level": level, "code": code, "label": label or code,
        "companies": b["companies"],
        "rev_total": round(sum(b["revs"]), 2),
        "margin_median": _median(b["margins"]),
        "fragmentation": _hhi_fragmentation(b["revs"]),
        "growth_cagr": _cagr(b["year_rev"]),
    }


async def rebuild_sector_aggregates() -> Dict[str, Any]:
    """Recorre master_companies + company_fingerprint y persiste db.sector_aggregates."""
    labels = await _sector_labels()

    # company_id -> primary_sector (S0x)
    fp: Dict[str, str] = {}
    async for r in db.company_fingerprint.find(
            {"primary_sector": {"$ne": None}}, {"_id": 0, "company_id": 1, "primary_sector": 1}):
        fp[r["company_id"]] = r["primary_sector"]

    arroba: Dict[str, Dict] = {}
    cnae: Dict[str, Dict] = {}
    proj = {"_id": 0, "master_id": 1, "status": 1,
            "financials.latest.revenue": 1, "financials.latest.ebitda_margin": 1,
            "financials.history": 1, "classification.cnae_section": 1}
    async for c in db.master_companies.find({"status": "active"}, proj):
        rev = ((c.get("financials") or {}).get("latest") or {}).get("revenue")
        margin = ((c.get("financials") or {}).get("latest") or {}).get("ebitda_margin")
        hist = (c.get("financials") or {}).get("history")
        # ARROBA
        sec = fp.get(c["master_id"])
        if sec:
            arroba.setdefault(sec, _new_bucket())
            _accumulate(arroba[sec], rev, margin, hist)
        # CNAE sección
        section = (c.get("classification") or {}).get("cnae_section")
        if section:
            cnae.setdefault(section, _new_bucket())
            _accumulate(cnae[section], rev, margin, hist)

    docs: List[Dict] = []
    for code, b in arroba.items():
        docs.append(_finish(code, labels.get(code, code), "arroba", "sector", b))
    for code, b in cnae.items():
        docs.append(_finish(code, CNAE_SECTION_LABELS.get(code, code), "cnae", "section", b))

    await db.sector_aggregates.delete_many({})
    if docs:
        await db.sector_aggregates.insert_many([dict(d) for d in docs])
    from models import now_iso
    await db.sector_aggregates_meta.delete_many({})
    # Precalcula compradores públicos por división. Este único trabajo caro se
    # ejecuta junto al rebuild; las fichas nunca agregan los contratos en vivo.
    buyer_rows = await db.public_procurement_contracts.aggregate([
        {"$match": {"buyer_name": {"$nin": [None, ""]}}},
        {"$group": {"_id": {"buyer": "$buyer_name", "cpv": "$cpv_code"},
                    "contracts": {"$sum": 1},
                    "amount_eur": {"$sum": {"$ifNull": ["$amount", 0]}}}},
    ], allowDiskUse=True).to_list(50000)
    buyers_by_division: Dict[str, Dict[str, Dict[str, float]]] = {}
    for row in buyer_rows:
        division = cpv_to_cnae_division((row.get("_id") or {}).get("cpv") or "")
        buyer = (row.get("_id") or {}).get("buyer")
        if not division or not buyer:
            continue
        item = buyers_by_division.setdefault(division, {}).setdefault(
            buyer, {"contracts": 0, "amount_eur": 0.0})
        item["contracts"] += row.get("contracts", 0)
        item["amount_eur"] += row.get("amount_eur", 0)

    buyer_docs = []
    for division, buyers in buyers_by_division.items():
        for buyer, values in sorted(
                buyers.items(), key=lambda pair: pair[1]["amount_eur"], reverse=True)[:50]:
            buyer_docs.append({"division": division, "buyer_name": buyer, **values})
    await db.sector_top_buyers.delete_many({})
    if buyer_docs:
        await db.sector_top_buyers.insert_many(buyer_docs)
    await db.sector_aggregates_meta.insert_one(
        {"computed_at": now_iso(), "count": len(docs), "companies_with_sector": len(fp),
         "sector_top_buyers": len(buyer_docs)})
    return {"rebuilt": len(docs), "companies_with_sector": len(fp),
            "sector_top_buyers": len(buyer_docs)}


_METRIC_FIELD = {"size": "rev_total", "growth": "growth_cagr",
                 "margin": "margin_median", "frag": "fragmentation"}


async def get_ranking(lens: str = "arroba", level: Optional[str] = None,
                      metric: str = "size", limit: int = 20) -> Dict[str, Any]:
    global _rebuild_task
    field = _METRIC_FIELD.get(metric, "rev_total")
    q: Dict[str, Any] = {"lens": lens if lens in ("arroba", "cnae") else "arroba"}
    if level:
        q["level"] = level
    rows = await db.sector_aggregates.find(q, {"_id": 0}).to_list(500)
    rows = [r for r in rows if r.get(field) is not None]
    rows.sort(key=lambda r: r[field], reverse=True)
    meta = await db.sector_aggregates_meta.find_one({}, {"_id": 0})
    building = False
    if not rows and meta is None:
        # Nunca se ha calculado: lanzar el rebuild en segundo plano (una sola vez a la vez)
        # en lugar de devolver un ranking vacío para siempre.
        if _rebuild_task is None or _rebuild_task.done():
            async def _run():
                try:
                    await rebuild_sector_aggregates()
                except Exception:
                    logger.exception("sector aggregates rebuild failed")
            _rebuild_task = asyncio.create_task(_run())
        building = True
    elif _rebuild_task is not None and not _rebuild_task.done():
        building = True
    return {"building": building, "lens": q["lens"], "metric": metric, "sectors": rows[:limit],
            "meta": meta, "coverage_note": "Agregados reales precomputados; cobertura = empresas activas con dato."}
