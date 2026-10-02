"""Territory Workspace API.

Composed territorial view for Beta's `/territorio/[level]/[code]` screen. The
route intentionally separates observed values from estimated/unavailable ones so
the UI can stay faithful to the mockup without pretending that every metric
exists in Intel yet.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from database import db
from models import now_iso
from services.cnae_catalog import section_label
from services.geo_catalog import CCAA, PROVINCES, get_ccaa_label, get_province_label, resolve_borme_province


router = APIRouter(prefix="/api/v1/public/territory-workspace", tags=["territory_workspace"])

CONTRACT_VERSION = "1.0"


def _ccaa(code: str) -> dict[str, Any] | None:
    return next((c for c in CCAA if c["code"] == code), None)


def _province_codes(level: str, code: str) -> list[str]:
    if level == "province":
        if code not in PROVINCES:
            raise HTTPException(404, f"Province {code} not found")
        return [code]
    ccaa = _ccaa(code)
    if not ccaa:
        raise HTTPException(404, f"CCAA {code} not found")
    return list(ccaa["provinces"])


def _territory_name(level: str, code: str) -> str:
    if level == "province":
        return get_province_label(code) or code
    return get_ccaa_label(code) or code


async def _matched_province_names(province_codes: list[str]) -> list[str]:
    """Find province spellings actually present in master_companies."""
    wanted = set(province_codes)
    rows = await db.master_companies.aggregate(
        [
            {"$match": {"location.provincia": {"$nin": [None, ""]}}},
            {"$group": {"_id": "$location.provincia"}},
            {"$limit": 5000},
        ]
    ).to_list(5000)
    names = []
    for row in rows:
        raw = row.get("_id")
        if raw and resolve_borme_province(str(raw)) in wanted:
            names.append(raw)
    if names:
        return sorted(set(names))
    return sorted({PROVINCES[c]["label"] for c in province_codes if c in PROVINCES})


def _company_match(province_names: list[str]) -> dict[str, Any]:
    return {
        "status": "active",
        "location.provincia": {"$in": province_names},
    }


def _money_field(path: str) -> dict[str, Any]:
    return {"$ifNull": [path, 0]}


def _nonnull_count(path: str) -> dict[str, Any]:
    return {"$sum": {"$cond": [{"$ne": [path, None]}, 1, 0]}}


async def _financial_aggregate(match: dict[str, Any]) -> dict[str, Any]:
    rows = await db.master_companies.aggregate(
        [
            {"$match": match},
            {
                "$group": {
                    "_id": None,
                    "companies": {"$sum": 1},
                    "revenue_companies": _nonnull_count("$financials.latest.revenue"),
                    "employment_companies": _nonnull_count("$size.employees_total"),
                    "ebitda_companies": _nonnull_count("$financials.latest.ebitda"),
                    "revenue": {"$sum": _money_field("$financials.latest.revenue")},
                    "employment": {"$sum": _money_field("$size.employees_total")},
                    "ebitda": {"$sum": _money_field("$financials.latest.ebitda")},
                }
            },
        ],
        allowDiskUse=True,
    ).to_list(1)
    row = rows[0] if rows else {}
    return {
        "status": "observed",
        "source": "master_companies.financials.latest",
        "companies": row.get("companies", 0),
        "revenue_companies": row.get("revenue_companies", 0),
        "employment_companies": row.get("employment_companies", 0),
        "ebitda_companies": row.get("ebitda_companies", 0),
        "revenue": row.get("revenue", 0),
        "employment": row.get("employment", 0),
        "ebitda": row.get("ebitda", 0),
    }


async def _revenue_yoy(match: dict[str, Any]) -> dict[str, Any]:
    rows = await db.master_companies.aggregate(
        [
            {"$match": match},
            {"$unwind": "$financials.history"},
            {
                "$match": {
                    "financials.history.year": {"$ne": None},
                    "financials.history.revenue": {"$ne": None},
                }
            },
            {
                "$group": {
                    "_id": "$financials.history.year",
                    "revenue": {"$sum": "$financials.history.revenue"},
                    "companies": {"$sum": 1},
                }
            },
            {"$sort": {"_id": -1}},
            {"$limit": 2},
        ],
        allowDiskUse=True,
    ).to_list(2)
    if len(rows) < 2 or not rows[1].get("revenue"):
        return {"status": "unavailable", "value": None, "reason": "No hay dos ejercicios comparables suficientes"}
    latest, previous = rows[0], rows[1]
    value = ((latest["revenue"] - previous["revenue"]) / previous["revenue"]) * 100
    return {
        "status": "observed",
        "value": value,
        "latest_year": latest["_id"],
        "previous_year": previous["_id"],
        "source": "master_companies.financials.history",
    }


async def _sector_leaders(match: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    rows = await db.master_companies.aggregate(
        [
            {"$match": {**match, "classification.cnae_section": {"$nin": [None, ""]}}},
            {
                "$group": {
                    "_id": "$classification.cnae_section",
                    "companies": {"$sum": 1},
                    "revenue": {"$sum": _money_field("$financials.latest.revenue")},
                    "employment": {"$sum": _money_field("$size.employees_total")},
                    "revenue_companies": _nonnull_count("$financials.latest.revenue"),
                }
            },
            {"$sort": {"revenue": -1, "companies": -1}},
            {"$limit": limit},
        ],
        allowDiskUse=True,
    ).to_list(limit)
    return [
        {
            "section": row["_id"],
            "label": section_label(row["_id"]) or row["_id"],
            "companies": row.get("companies", 0),
            "revenue_companies": row.get("revenue_companies", 0),
            "revenue": row.get("revenue", 0),
            "employment": row.get("employment", 0),
            "status": "observed",
        }
        for row in rows
    ]


async def _municipality_ranking(match: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    rows = await db.master_companies.aggregate(
        [
            {"$match": {**match, "location.municipio": {"$nin": [None, ""]}}},
            {
                "$group": {
                    "_id": "$location.municipio",
                    "companies": {"$sum": 1},
                    "revenue": {"$sum": _money_field("$financials.latest.revenue")},
                    "employment": {"$sum": _money_field("$size.employees_total")},
                    "revenue_companies": _nonnull_count("$financials.latest.revenue"),
                }
            },
            {"$sort": {"companies": -1, "revenue": -1}},
            {"$limit": limit},
        ],
        allowDiskUse=True,
    ).to_list(limit)
    return [
        {
            "municipality": row["_id"],
            "companies": row.get("companies", 0),
            "revenue_companies": row.get("revenue_companies", 0),
            "revenue": row.get("revenue", 0),
            "employment": row.get("employment", 0),
            "status": "observed",
        }
        for row in rows
    ]


async def _highlighted_companies(match: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    docs = await db.master_companies.find(
        {**match, "financials.latest.revenue": {"$ne": None}},
        {
            "_id": 0,
            "master_id": 1,
            "cif_normalized": 1,
            "identity.legal_name": 1,
            "classification.cnae_section": 1,
            "location.municipio": 1,
            "location.provincia": 1,
            "financials.latest.revenue": 1,
            "financials.latest.ebitda": 1,
            "size.employees_total": 1,
        },
    ).sort("financials.latest.revenue", -1).limit(limit).to_list(limit)
    return [
        {
            "master_id": d.get("master_id"),
            "cif": d.get("cif_normalized"),
            "name": (d.get("identity") or {}).get("legal_name") or d.get("master_id"),
            "sector": (d.get("classification") or {}).get("cnae_section"),
            "sector_label": section_label((d.get("classification") or {}).get("cnae_section")),
            "municipality": (d.get("location") or {}).get("municipio"),
            "province": (d.get("location") or {}).get("provincia"),
            "revenue": (((d.get("financials") or {}).get("latest") or {}).get("revenue")),
            "ebitda": (((d.get("financials") or {}).get("latest") or {}).get("ebitda")),
            "employees": ((d.get("size") or {}).get("employees_total")),
            "status": "observed",
        }
        for d in docs
    ]


async def _territory_signals(match: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    companies = await db.master_companies.find(
        match,
        {"_id": 0, "master_id": 1, "identity.legal_name": 1},
    ).limit(5000).to_list(5000)
    by_id = {c.get("master_id"): (c.get("identity") or {}).get("legal_name") for c in companies if c.get("master_id")}
    if not by_id:
        return []
    rows = await db.signals.find(
        {"master_id": {"$in": list(by_id)}, "status": {"$ne": "dismissed"}},
        {"_id": 0},
    ).sort([("score", -1), ("created_at", -1)]).limit(limit).to_list(limit)
    return [
        {
            "master_id": row.get("master_id"),
            "company_name": by_id.get(row.get("master_id")),
            "signal_type": row.get("signal_type") or row.get("type"),
            "category": row.get("category"),
            "severity": row.get("severity"),
            "title": row.get("title") or row.get("summary"),
            "explanation": row.get("explanation") or row.get("description"),
            "status": "observed",
        }
        for row in rows
    ]


async def _density_context(level: str, code: str, province_names: list[str]) -> dict[str, Any]:
    query: dict[str, Any]
    if level == "ccaa":
        query = {"ccaa": _territory_name(level, code)}
    else:
        query = {"province": {"$in": province_names + [_territory_name(level, code)]}}
    doc = await db.estadisticas_territoriales.find_one(query, {"_id": 0}, sort=[("year", -1)])
    if not doc:
        return {
            "status": "unavailable",
            "business_density": None,
            "reason": "No hay superficie territorial normalizada para calcular empresas/km2",
        }
    return {
        "status": "context",
        "business_density": None,
        "population_density": doc.get("population_density"),
        "average_income": doc.get("average_income"),
        "unemployment_rate": doc.get("unemployment_rate"),
        "economic_activity_index": doc.get("economic_activity_index"),
        "year": doc.get("year"),
        "reason": "La plataforma dispone de indicadores de contexto, no de una densidad empresarial normalizada",
    }


async def _macroeconomic_context(level: str, code: str, province_names: list[str]) -> dict[str, Any]:
    territory_query = {"territory_level": level, "territory_code": code}
    gdp_doc = await db.estadisticas_territoriales.find_one(
        territory_query, {"_id": 0}, sort=[("year", -1)],
    )
    income_doc = None
    if level == "province":
        income_doc = await db.estadisticas_territoriales.find_one(
            {"province": {"$in": province_names + [_territory_name(level, code)]}, "average_income": {"$ne": None}},
            {"_id": 0}, sort=[("year", -1)],
        )
    ccaa_code = code if level == "ccaa" else PROVINCES[code]["ccaa"]
    ccaa_name = get_ccaa_label(ccaa_code) or ""
    unemployment_doc = await db.estadisticas_empleo.find_one(
        {"ccaa": ccaa_name}, {"_id": 0}, sort=[("period", -1)],
    )
    return {
        "gdp": {
            "value_eur": (gdp_doc or {}).get("gdp_current_eur"),
            "year": (gdp_doc or {}).get("year"),
            "status": (gdp_doc or {}).get("gdp_status"),
            "source": (gdp_doc or {}).get("gdp_source"),
            "source_url": (gdp_doc or {}).get("gdp_source_url"),
        },
        "average_income": {
            "value_eur": (income_doc or {}).get("average_income"),
            "year": (income_doc or {}).get("year"),
            "source": (income_doc or {}).get("source"),
            "source_url": (income_doc or {}).get("source_url"),
        },
        "unemployment": {
            "value_pct": (unemployment_doc or {}).get("unemployment_rate"),
            "period": (unemployment_doc or {}).get("period"),
            "year": (unemployment_doc or {}).get("year"),
            "scope": ccaa_name,
            "source": (unemployment_doc or {}).get("source"),
            "source_url": (unemployment_doc or {}).get("source_url"),
        },
    }


async def _geo_ranking(level: str, code: str) -> dict[str, Any]:
    rows = await db.geo_intelligence.find(
        {"geo_level": level},
        {"_id": 0, "geo_id": 1, "dynamism_score": 1},
    ).sort([("dynamism_score", -1), ("geo_id", 1)]).to_list(100)
    for idx, row in enumerate(rows, start=1):
        if row.get("geo_id") == code:
            return {"status": "observed", "rank": idx, "total": len(rows), "metric": "dynamism_score"}
    return {"status": "unavailable", "rank": None, "total": len(rows), "reason": "No aparece en geo_intelligence"}


def _narratives(name: str, financials: dict[str, Any], leaders: list[dict[str, Any]], yoy: dict[str, Any]) -> list[dict[str, Any]]:
    signals = []
    if leaders:
        leader = leaders[0]
        signals.append({
            "type": "sector_leadership",
            "text": f"{leader['label']} lidera la facturación observada en {name}, con {leader['companies']} empresas en la muestra.",
            "status": "derived",
        })
    if yoy.get("status") == "observed" and yoy.get("value") is not None:
        direction = "crece" if yoy["value"] >= 0 else "retrocede"
        signals.append({
            "type": "revenue_trend",
            "text": f"La facturación agregada observada {direction} {abs(yoy['value']):.1f}% frente al ejercicio comparable anterior.",
            "status": "derived",
        })
    if financials.get("revenue_companies", 0) > 0:
        signals.append({
            "type": "coverage",
            "text": f"La capa financiera cubre {financials['revenue_companies']} empresas con facturación y {financials['employment_companies']} con empleo declarado.",
            "status": "derived",
        })
    return signals


@router.get("/{level}/{code}")
async def territory_workspace(
    level: str,
    code: str,
    companies_limit: int = Query(8, ge=1, le=25),
    municipalities_limit: int = Query(10, ge=1, le=50),
):
    if level not in {"ccaa", "province"}:
        raise HTTPException(400, "level must be ccaa or province")
    t0 = time.time()
    province_codes = _province_codes(level, code)
    province_names = await _matched_province_names(province_codes)
    match = _company_match(province_names)

    geo = await db.geo_intelligence.find_one({"geo_id": code, "geo_level": level}, {"_id": 0})
    financials = await _financial_aggregate(match)
    yoy = await _revenue_yoy(match)
    sector_leaders = await _sector_leaders(match, 8)
    municipalities = await _municipality_ranking(match, municipalities_limit)
    companies = await _highlighted_companies(match, companies_limit)
    signals = await _territory_signals(match, 8)
    density = await _density_context(level, code, province_names)
    macroeconomics = await _macroeconomic_context(level, code, province_names)
    ranking = await _geo_ranking(level, code)
    name = (geo or {}).get("geo_name") or _territory_name(level, code)

    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": now_iso(),
        "response_time_ms": round((time.time() - t0) * 1000, 1),
        "territory": {
            "level": level,
            "code": code,
            "name": name,
            "province_codes": province_codes,
            "matched_province_names": province_names,
        },
        "geo": geo,
        "aggregates": {
            "active_companies": (geo or {}).get("active_companies"),
            "revenue": financials,
            "employment": {
                "status": financials["status"],
                "source": "master_companies.size.employees_total",
                "value": financials["employment"],
                "companies": financials["employment_companies"],
            },
            "vab": {
                "status": "unavailable",
                "value": None,
                "reason": "Intel no tiene VAB territorial cargado",
            },
            "revenue_yoy": yoy,
            "density": density,
            "macroeconomics": macroeconomics,
        },
        "sector_leaders_by_revenue": sector_leaders,
        "municipality_ranking": municipalities,
        "highlighted_companies": companies,
        "signals": signals,
        "ma": {
            "operations": {"status": "unavailable", "items": [], "reason": "No hay operaciones M&A indexadas por territorio verificado"},
            "average_ebitda_multiple": {"status": "unavailable", "value": None, "reason": "Los múltiplos disponibles son sector/categoría, no territorio"},
            "trend": {"status": "unavailable", "value": None, "reason": "No hay serie territorial M&A fiable"},
        },
        "national_ranking": ranking,
        "narratives": _narratives(name, financials, sector_leaders, yoy),
        "quality_notes": [
            "Facturación, empleo, sectores, municipios y empresas destacadas son observados en master_companies y dependen de cobertura financiera.",
            "Densidad empresarial, VAB y M&A territorial quedan marcados como no disponibles cuando no existe fuente directa.",
            "El ranking nacional se deriva del ranking geo_intelligence cargado por dinamismo.",
        ],
    }
