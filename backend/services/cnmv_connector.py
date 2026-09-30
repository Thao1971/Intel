"""CNMV Connector — Scrapes official CNMV registers for investor intelligence.

Entity types scraped:
  id=0: Sociedades capital-riesgo (SCR)
  id=1: Fondos capital-riesgo (FCR)
  id=19: SCR pyme
  id=20: FCR pyme
  id=21: FCR europeos
  id=22: Fondos emprendimiento social europeos
  id=23: SICC
  id=24: FICC
  id=28: FILPE
  Gestoras: id=4 (separate URL pattern)

Source: cnmv.es/portal/consultas/mostrarlistados
"""

import logging
import re
from typing import Dict, List
from database import db
from models import new_id, now_iso
from services.text_normalize import normalize_strings

logger = logging.getLogger(__name__)

CNMV_BASE = "https://www.cnmv.es/portal/consultas"

ENTITY_TYPES = {
    # Investment vehicles
    "scr": {"id": 0, "label": "Sociedades capital-riesgo", "detail_path": "ecr/sociedad"},
    "fcr": {"id": 1, "label": "Fondos capital-riesgo", "detail_path": "ecr/fondo"},
    "scr_pyme": {"id": 19, "label": "SCR pyme", "detail_path": "ecr/sociedad"},
    "fcr_pyme": {"id": 20, "label": "FCR pyme", "detail_path": "ecr/fondo"},
    "fcr_europeo": {"id": 21, "label": "FCR europeos", "detail_path": "ecr/fondo"},
    "fese": {"id": 22, "label": "Fondos emprendimiento social europeos", "detail_path": "ecr/fondo"},
    "sicc": {"id": 23, "label": "SICC", "detail_path": "ecr/sociedad"},
    "ficc": {"id": 24, "label": "FICC", "detail_path": "ecr/fondo"},
    "filpe": {"id": 28, "label": "FILPE", "detail_path": "ecr/fondo"},
    # Managers & investment services
    "sgeic": {"id": None, "label": "Sociedad Gestora ECR (SGEIC)", "detail_path": "ecr/gestora", "is_manager": True},
    "sgiic": {"id": None, "label": "Sociedad Gestora IIC (SGIIC)", "detail_path": "iic/sgiic", "is_manager": True},
    "esi": {"id": None, "label": "Empresa Servicios Inversion (ESI)", "detail_path": "esi/entidad", "is_manager": True},
    "eaf": {"id": 5, "label": "Empresa Asesoramiento Financiero (EAF)", "detail_path": "eaf/entidad", "is_manager": True},
    "eafn": {"id": None, "label": "EAF Nacimiento", "detail_path": "eaf/entidad", "is_manager": True},
}


async def sync_cnmv_entities(entity_types: List[str] = None, max_pages_per_type: int = 100) -> Dict:
    """Scrape all CNMV entity listings via Playwright.

    Always writes a sync log entry — success, partial, or fatal failure — so
    `last_sync` never silently freezes. Previously a fatal error (e.g. Chromium
    binary missing) returned before the log write, leaving no record the sync
    was even attempted.
    """
    now = now_iso()

    if not entity_types:
        entity_types = list(ENTITY_TYPES.keys())

    total_imported = 0
    total_by_type = {}
    errors = []
    fatal_error = None

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        fatal_error = "Playwright no instalado (falta el paquete pip)"

    if not fatal_error:
        try:
            async with async_playwright() as p:
                for etype in entity_types:
                    if etype not in ENTITY_TYPES:
                        continue

                    config = ENTITY_TYPES[etype]
                    logger.info(f"CNMV: scraping {config['label']} (id={config['id']})...")

                    try:
                        # _scrape_listing manages its own browser lifecycle (see its
                        # docstring) — no shared browser/page across entity types here.
                        entities = await _scrape_listing(p, config["id"], max_pages_per_type)
                        if entities:
                            imported = await _store_entities(entities, etype, config, now)
                            total_imported += imported
                            total_by_type[etype] = imported
                            logger.info(f"  {config['label']}: {imported} entities")
                    except Exception as e:
                        err = f"{etype}: {str(e)[:200]}"
                        errors.append(err)
                        logger.error(f"CNMV error: {err}")

        except Exception as e:
            # Typically Chromium binary missing/failed to launch. This used to
            # `return` immediately, skipping the log write below entirely.
            fatal_error = str(e)[:300]
            logger.error(f"CNMV sync fatal error: {fatal_error}")

    # Si NO se importo nada y hubo errores, es un fallo total, no un "partial"
    # (antes el toast decia "0 entidades (con avisos)" como si fuera un exito).
    if fatal_error or (errors and total_imported == 0):
        status = "error"
    else:
        status = "completed" if not errors else "partial"

    await db.cnmv_sync_logs.insert_one({
        "log_id": new_id(),
        "synced_at": now,
        "entity_types": entity_types,
        "total_imported": total_imported,
        "by_type": total_by_type,
        "errors": errors,
        "fatal_error": fatal_error,
        "status": status,
    })

    result = {
        "status": status,
        "total_imported": total_imported,
        "by_type": total_by_type,
        "errors": errors,
        "synced_at": now,
    }
    if fatal_error:
        result["message"] = fatal_error
    elif status == "error":
        result["message"] = "; ".join(errors)[:300]
    return result


from services.playwright_runtime import launch_chromium
from pymongo import UpdateOne

CNMV_LAUNCH_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
CNMV_BROWSER_RECYCLE_EVERY = 30


async def _scrape_listing(p, entity_id: int, max_pages: int) -> List[Dict]:
    """Scrape all pages of a CNMV entity listing.

    Manages its own browser instance and recycles it every 30 navigations.
    Root cause (found 2026-07 via the Emergent testing agent): a single headless
    Chromium instance was previously reused across the ENTIRE sync (all 14 entity
    types, potentially 100 pages each) — the browser process degrades and dies
    with "Target page/browser has been closed" after ~50 consecutive navigations
    against cnmv.es. It was not an OOM or a missing-Chromium issue. Recycling the
    browser here — closing and relaunching every 30 page loads — keeps each
    instance well under the point where it degrades. Launch flags match the ones
    already used elsewhere in this codebase (services/scraper.py).
    """
    all_entities = []
    pg = 1
    nav_count = 0

    browser = await launch_chromium(p, CNMV_LAUNCH_ARGS)
    page = await browser.new_page()

    try:
        while pg <= max_pages:
            if nav_count > 0 and nav_count % CNMV_BROWSER_RECYCLE_EVERY == 0:
                await page.close()
                await browser.close()
                browser = await launch_chromium(p, CNMV_LAUNCH_ARGS)
                page = await browser.new_page()

            url = f"{CNMV_BASE}/mostrarlistados?id={entity_id}&page={pg}&lang=es"
            await page.goto(url, wait_until="networkidle", timeout=20000)
            nav_count += 1
            await page.wait_for_timeout(1500)

            entities = await page.evaluate('''() => {
                const links = document.querySelectorAll('a[href*="nif="]');
                const result = [];
                links.forEach(a => {
                    const href = a.getAttribute('href') || '';
                    const nifMatch = href.match(/nif=([^&]+)/);
                    const name = a.textContent.trim();
                    if (nifMatch && name && name.length > 2) {
                        result.push({ name: name, nif: nifMatch[1], href: href });
                    }
                });
                return result;
            }''')

            if not entities:
                break

            all_entities.extend(entities)
            pg += 1
    finally:
        await browser.close()

    return all_entities


async def _store_entities(entities: List[Dict], etype: str, config: Dict, now: str) -> int:
    """Store scraped entities into cnmv_entities."""
    imported = 0

    for e in entities:
        e = normalize_strings(e)
        result = await db.cnmv_entities.update_one(
            {"nif": e["nif"]},
            {"$set": {
                "name": e["name"],
                "nif": e["nif"],
                "entity_type": etype,
                "entity_type_label": config["label"],
                "cnmv_list_id": config["id"],
                "detail_url": f"{CNMV_BASE}/{config['detail_path']}?nif={e['nif']}&lang=es",
                "source": "cnmv",
                "updated_at": now,
            },
            "$setOnInsert": {
                "entity_id": new_id(),
                "registration_date": None,
                "fund_manager_name": None,
                "fund_manager_nif": None,
                "status": "registered",
                "cnae_codes": [],
                "created_at": now,
            }},
            upsert=True,
        )
        if result.upserted_id:
            imported += 1

    return imported


async def generate_cnmv_signals() -> Dict:
    """Generate investor intelligence signals and metrics from CNMV data."""
    now = now_iso()
    signals = []

    # Count by type
    pipeline = [
        {"$group": {"_id": "$entity_type", "count": {"$sum": 1}}},
    ]
    by_type = {r["_id"]: r["count"] for r in await db.cnmv_entities.aggregate(pipeline).to_list(20)}

    total = sum(by_type.values())
    managers = await db.cnmv_entities.count_documents({"is_manager": True})
    funds = total - managers

    # Signal: active investor ecosystem
    if total > 500:
        signals.append({
            "signal_id": new_id(),
            "signal_type": "active_investor_ecosystem",
            "description": f"{total} entidades de inversion registradas en CNMV ({funds} vehiculos, {managers} gestoras)",
            "value": total,
            "confidence": 0.95,
            "sources_used": ["cnmv"],
            "generated_at": now,
        })

    # Per entity type signals
    for etype, count in by_type.items():
        config = ENTITY_TYPES.get(etype, {})
        label = config.get("label", etype)
        if count >= 10:
            signals.append({
                "signal_id": new_id(),
                "signal_type": "investor_category_active",
                "entity_type": etype,
                "description": f"{count} {label} registradas",
                "value": count,
                "confidence": 0.9,
                "sources_used": ["cnmv"],
                "generated_at": now,
            })

    # Market concentration: top manager types
    if managers > 100:
        signals.append({
            "signal_id": new_id(),
            "signal_type": "manager_ecosystem",
            "description": f"{managers} gestoras y ESI registradas gestionando {funds} vehiculos de inversion",
            "value": managers,
            "confidence": 0.9,
            "sources_used": ["cnmv"],
            "generated_at": now,
        })

    # Persist signals
    await db.cnmv_signals.delete_many({})
    if signals:
        await db.cnmv_signals.insert_many(signals)

    # Generate metrics
    metrics = []

    # Overall metrics
    metrics.append({"metric_id": new_id(), "metric": "total_entities", "value": total, "source": "cnmv", "generated_at": now})
    metrics.append({"metric_id": new_id(), "metric": "total_funds_vehicles", "value": funds, "source": "cnmv", "generated_at": now})
    metrics.append({"metric_id": new_id(), "metric": "total_managers", "value": managers, "source": "cnmv", "generated_at": now})

    for etype, count in by_type.items():
        metrics.append({"metric_id": new_id(), "metric": f"count_{etype}", "value": count, "source": "cnmv", "generated_at": now})

    # Concentration: ratio vehicles/managers
    if managers > 0:
        ratio = round(funds / managers, 2)
        metrics.append({"metric_id": new_id(), "metric": "vehicles_per_manager", "value": ratio, "source": "cnmv", "generated_at": now})

    await db.cnmv_metrics.delete_many({})
    if metrics:
        await db.cnmv_metrics.insert_many(metrics)

    return {
        "status": "completed",
        "signals_generated": len(signals),
        "metrics_generated": len(metrics),
        "total_entities": total,
        "managers": managers,
        "funds": funds,
        "vehicles_per_manager": round(funds / managers, 2) if managers > 0 else 0,
        "by_type": by_type,
        "generated_at": now,
    }


async def get_cnmv_stats() -> Dict:
    """Get CNMV intelligence stats."""
    total = await db.cnmv_entities.count_documents({})
    managers = await db.cnmv_entities.count_documents({"is_manager": True})
    funds = total - managers
    signals = await db.cnmv_signals.count_documents({})
    metrics = await db.cnmv_metrics.count_documents({})

    pipeline = [
        {"$group": {"_id": "$entity_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_type = {r["_id"]: r["count"] for r in await db.cnmv_entities.aggregate(pipeline).to_list(20)}

    last_sync = await db.cnmv_sync_logs.find_one({}, {"_id": 0}, sort=[("synced_at", -1)])

    return {
        "total_entities": total,
        "managers": managers,
        "funds_vehicles": funds,
        "vehicles_per_manager": round(funds / managers, 2) if managers > 0 else 0,
        "signals": signals,
        "metrics": metrics,
        "by_type": by_type,
        "last_sync": last_sync,
    }


async def match_cnmv_to_companies() -> Dict:
    """Match CNMV entities against companies_master by NIF.

    Antes: por cada entidad (2160) un find_one con $or sobre companies_master
    (sin indice = escaneo completo de la coleccion cada vez) + un update_one, todo
    secuencial -> minutos y error/timeout. Ahora: 1 consulta con $in para traer las
    empresas candidatas, match en memoria y 1 bulk_write.
    """
    now = now_iso()
    entities = await db.cnmv_entities.find({}, {"_id": 0, "nif": 1, "entity_id": 1}).to_list(20000)
    total = len(entities)

    def _norm(v):
        return (v or "").strip().upper()

    nifs = {_norm(e.get("nif")) for e in entities if _norm(e.get("nif"))}
    nif_list = list(nifs | {e["nif"] for e in entities if e.get("nif")})

    by_nif = {}
    if nif_list:
        cursor = db.companies_master.find(
            {"$or": [{"cif": {"$in": nif_list}}, {"cif_normalized": {"$in": nif_list}}]},
            {"_id": 0, "master_company_id": 1, "legal_name": 1, "cif": 1, "cif_normalized": 1},
        )
        async for c in cursor:
            for k in (_norm(c.get("cif")), _norm(c.get("cif_normalized"))):
                if k and k not in by_nif:
                    by_nif[k] = c

    ops = []
    matched = 0
    for e in entities:
        nif = e.get("nif") or ""
        company = by_nif.get(_norm(nif))
        if not company:
            continue
        ops.append(UpdateOne(
            {"nif": nif},
            {"$set": {
                "matched_company_id": company["master_company_id"],
                "matched_company_name": company.get("legal_name"),
                "match_source": "nif_exact",
                "matched_at": now,
            }},
        ))
        matched += 1
    if ops:
        await db.cnmv_entities.bulk_write(ops, ordered=False)

    return {
        "status": "completed",
        "total_checked": total,
        "matched": matched,
        "match_rate_pct": round(matched / total * 100, 1) if total > 0 else 0,
    }


async def get_managers_with_funds() -> List[Dict]:
    """Get all managers with their managed entity counts."""
    pipeline = [
        {"$match": {"is_manager": True}},
        {"$project": {"_id": 0, "entity_id": 1, "nif": 1, "name": 1, "entity_type": 1,
                       "entity_type_label": 1, "matched_company_id": 1}},
        {"$sort": {"name": 1}},
    ]
    managers = await db.cnmv_entities.aggregate(pipeline).to_list(1000)

    # For now, we don't have the fund→manager link in the data
    # (would require scraping individual fund detail pages)
    # But we can still return the managers list
    for m in managers:
        from services.cnmv_catalog import get_entity_info
        info = get_entity_info(m.get("entity_type", ""))
        m["catalog"] = info

    return managers


async def get_entity_detail(entity_id: str) -> Dict | None:
    """Get full detail for a CNMV entity."""
    entity = await db.cnmv_entities.find_one(
        {"$or": [{"entity_id": entity_id}, {"nif": entity_id}]},
        {"_id": 0}
    )
    if not entity:
        return None

    from services.cnmv_catalog import get_entity_info
    entity["catalog"] = get_entity_info(entity.get("entity_type", ""))

    return entity
