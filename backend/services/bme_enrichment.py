"""BME Batch Enrichment Engine — Processes all companies, resumable, idempotent.

Resolves detail URLs for all markets, fetches financial data, tracks progress.
Designed to run as background job or scheduled daily.
"""

import logging
import asyncio
from typing import Dict
from database import db
from models import new_id, now_iso
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

from services.playwright_runtime import launch_chromium

# URL patterns for detail pages
GROWTH_DETAIL = "https://www.bmegrowth.es/esp/Ficha/{name}_{isin}.aspx"
SCALEUP_DETAIL = "https://www.bolsasymercados.es/MTF_Equity/bme-scaleup/esp/Ficha/{name}_{isin}.aspx"
PRINCIPAL_DETAIL = "https://www.bolsasymercados.es/es/bme-exchange/mercados-y-cotizaciones/acciones/ficha-valor.html?isin={isin}"

STALE_DAYS = 30


def _resolve_detail_url(company: Dict) -> str | None:
    """Resolve the correct detail page URL for any BME company."""
    # First: use existing source_url if it looks valid
    existing = company.get("source_url", "")
    if existing and existing.startswith("http") and "Ficha" in existing and "ES0" in existing:
        return existing

    isin = company.get("isin", "")

    # Skip synthetic ISINs
    if not isin or isin.startswith("BME_") or isin.startswith("NOISIN") or len(isin) < 12:
        if company.get("listed_in_bme_principal"):
            return None
        return None

    name = company.get("company_name", "")
    name_clean = name.replace(" ", "_").replace(",", "").replace(".", "").replace("'", "")

    if company.get("listed_in_growth"):
        return GROWTH_DETAIL.format(name=name_clean, isin=isin)
    elif company.get("listed_in_scaleup"):
        return SCALEUP_DETAIL.format(name=name_clean, isin=isin)
    elif company.get("listed_in_bme_principal"):
        return PRINCIPAL_DETAIL.format(isin=isin)
    return None


async def run_full_enrichment(max_companies: int = 300, batch_size: int = 5) -> Dict:
    """Process all companies that need enrichment. Resumable and idempotent."""
    now = now_iso()
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)).isoformat()

    # Find companies needing enrichment
    query = {"$or": [
        {"detail_enriched": {"$ne": True}},
        {"last_update": {"$lt": stale_cutoff}},
    ]}
    companies = await db.bme_companies.find(
        query, {"_id": 0, "isin": 1, "company_name": 1, "source_url": 1,
                "listed_in_growth": 1, "listed_in_scaleup": 1, "listed_in_bme_principal": 1}
    ).limit(max_companies).to_list(max_companies)

    if not companies:
        return {"status": "completed", "message": "All companies enriched", "processed": 0}

    logger.info(f"BME enrichment: {len(companies)} companies to process")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        await db.bme_sync_logs.insert_one({
            "log_id": new_id(), "synced_at": now, "type": "enrichment",
            "total_candidates": len(companies), "processed": 0, "enriched": 0,
            "errors": 0, "skipped": 0, "fatal_error": "Playwright no instalado",
            "status": "error",
        })
        return {"status": "error", "message": "Playwright not installed"}

    processed = 0
    enriched = 0
    errors = 0
    skipped = 0
    fatal_error = None

    try:
        async with async_playwright() as p:
            browser = await launch_chromium(p)
            page = await browser.new_page()

            for i, company in enumerate(companies):
                isin = company["isin"]

                # Resolve URL
                detail_url = _resolve_detail_url(company)
                if not detail_url:
                    skipped += 1
                    await db.bme_companies.update_one(
                        {"isin": isin},
                        {"$set": {"enrichment_status": "skipped", "enrichment_error": "no_detail_url"}}
                    )
                    continue

                # Update source_url if we have a better one
                await db.bme_companies.update_one(
                    {"isin": isin},
                    {"$set": {"source_url": detail_url}}
                )

                try:
                    data = await _fetch_detail_data(page, detail_url, company)

                    if data:
                        data["last_update"] = now
                        data["detail_enriched"] = True
                        data["enrichment_status"] = "completed"
                        data["enrichment_error"] = None
                        data["source_url"] = detail_url
                        await db.bme_companies.update_one({"isin": isin}, {"$set": data})
                        enriched += 1
                    else:
                        await db.bme_companies.update_one(
                            {"isin": isin},
                            {"$set": {"enrichment_status": "no_data", "enrichment_error": "detail_page_empty"}}
                        )

                except Exception as e:
                    errors += 1
                    await db.bme_companies.update_one(
                        {"isin": isin},
                        {"$set": {"enrichment_status": "error", "enrichment_error": str(e)[:100]}}
                    )

                processed += 1

                if (processed % 10) == 0:
                    logger.info(f"  Progress: {processed}/{len(companies)} ({enriched} enriched, {errors} errors)")

            await browser.close()

    except Exception as e:
        # This used to be swallowed here and then logged as "status": "completed"
        # below unconditionally — even with processed=0, enriched=0, the log (and
        # the BME dashboard's "last_sync") reported success every night.
        fatal_error = str(e)[:300]
        logger.error(f"Enrichment engine error: {fatal_error}")

    status = "error" if fatal_error else "completed"

    # Log — status now reflects what actually happened.
    await db.bme_sync_logs.insert_one({
        "log_id": new_id(),
        "synced_at": now,
        "type": "enrichment",
        "total_candidates": len(companies),
        "processed": processed,
        "enriched": enriched,
        "errors": errors,
        "skipped": skipped,
        "fatal_error": fatal_error,
        "status": status,
    })

    result = {
        "status": status,
        "candidates": len(companies),
        "processed": processed,
        "enriched": enriched,
        "errors": errors,
        "skipped": skipped,
    }
    if fatal_error:
        result["message"] = fatal_error
    return result


async def _fetch_detail_data(page, url: str, company: Dict) -> Dict | None:
    """Fetch and parse a single company detail page."""
    try:
        await page.goto(url, wait_until="networkidle", timeout=12000)
        await page.wait_for_timeout(2000)
    except Exception:
        return None

    raw = await page.evaluate('''() => {
        var result = {};
        var text = document.body.innerText;
        var lines = text.split("\\n").filter(function(l) { return l.trim().length > 0; });
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim();
            if (line.length > 2 && line.length < 35 && i + 1 < lines.length) {
                result[line] = lines[i+1].trim();
            }
        }
        return result;
    }''')

    if not raw or len(raw) < 3:
        return None

    data = {}

    # Ticker
    for key in ["Ticker", "Código", "Nemotécnico"]:
        val = raw.get(key, "")
        if val and len(val) < 12:
            data["ticker"] = val
            break

    # NIF
    for key in ["NIF", "CIF"]:
        val = raw.get(key, "")
        if val and len(val) > 5:
            data["company_nif"] = val.replace("-", "").strip()
            break

    # Shares outstanding
    for key in ["Acciones en circulación", "Nº Acciones", "Acciones"]:
        val = raw.get(key, "")
        if val:
            clean = val.replace(".", "").replace(",", ".").strip()
            try:
                data["shares_outstanding"] = int(float(clean))
                break
            except ValueError:
                pass

    # Share price
    for key in ["Ref.", "Últ.", "Último", "Precio", "Cierre"]:
        val = raw.get(key, "")
        if val:
            clean = val.replace(".", "").replace(",", ".").strip()
            try:
                v = float(clean)
                if 0 < v < 100000:
                    data["share_price"] = v
                    break
            except ValueError:
                pass

    # Daily change
    for key in ["Dif.(%)", "Variación (%)", "Var.(%)"]:
        val = raw.get(key, "")
        if val:
            clean = val.replace(",", ".").replace("%", "").strip()
            try:
                data["daily_change"] = float(clean)
                break
            except ValueError:
                pass

    # Market cap from text
    for key in ["Capitalización", "Últ. precio", "Cap. Bursátil"]:
        val = raw.get(key, "")
        if "mill" in val.lower():
            clean = val.lower().replace("mill.", "").replace("€", "").replace(".", "").replace(",", ".").strip()
            try:
                data["market_cap"] = float(clean) * 1_000_000
                break
            except ValueError:
                pass

    # Annual high/low
    for key in ["Máx. año", "Máximo año", "Máximo Año"]:
        val = raw.get(key, "")
        if val:
            clean = val.replace(".", "").replace(",", ".").strip()
            try:
                data["annual_high"] = float(clean)
                break
            except ValueError:
                pass

    for key in ["Mín. año", "Mínimo año", "Mínimo Año"]:
        val = raw.get(key, "")
        if val:
            clean = val.replace(".", "").replace(",", ".").strip()
            try:
                data["annual_low"] = float(clean)
                break
            except ValueError:
                pass

    # Dividend yield
    for key in ["Rent. Dividendo", "Dividend Yield", "Rentabilidad por dividendo"]:
        val = raw.get(key, "")
        if val:
            clean = val.replace(",", ".").replace("%", "").strip()
            try:
                data["dividend_yield"] = float(clean)
                break
            except ValueError:
                pass

    # Auditor
    val = raw.get("Auditor", "")
    if val and len(val) > 3 and len(val) < 100:
        data["auditor"] = val

    # Listing date
    for key in ["Fecha de admisión", "Admisión", "Fecha admisión"]:
        val = raw.get(key, "")
        if val and len(val) > 5:
            data["listing_date"] = val
            break

    # Sector (override if better)
    for key in ["Sector", "Subsector"]:
        val = raw.get(key, "")
        if val and len(val) > 3 and len(val) < 60:
            data["sector_detail"] = val
            break

    return data if data else None


async def get_enrichment_stats() -> Dict:
    """Get enrichment progress stats."""
    total = await db.bme_companies.count_documents({})
    enriched = await db.bme_companies.count_documents({"detail_enriched": True})
    pending = await db.bme_companies.count_documents({"detail_enriched": {"$ne": True}})
    errors = await db.bme_companies.count_documents({"enrichment_status": "error"})
    skipped = await db.bme_companies.count_documents({"enrichment_status": "skipped"})

    with_price = await db.bme_companies.count_documents({"share_price": {"$ne": None}})
    with_ticker = await db.bme_companies.count_documents({"ticker": {"$ne": None}})
    with_nif = await db.bme_companies.count_documents({"company_nif": {"$ne": None}})
    with_shares = await db.bme_companies.count_documents({"shares_outstanding": {"$ne": None}})

    last_log = await db.bme_sync_logs.find_one(
        {"type": "enrichment"}, {"_id": 0}, sort=[("synced_at", -1)]
    )

    return {
        "total": total,
        "enriched": enriched,
        "pending": pending,
        "errors": errors,
        "skipped": skipped,
        "enrichment_pct": round(enriched / max(total, 1) * 100, 1),
        "with_price": with_price,
        "with_ticker": with_ticker,
        "with_nif": with_nif,
        "with_shares": with_shares,
        "last_enrichment": last_log,
    }
