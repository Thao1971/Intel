"""BME Connector — Scrapes BME Growth + BME Scaleup listings.

Architecture: designed for full BME ecosystem (Growth, Scaleup, Principal, Detail, Documents).
Phase 1: listings with full pagination.
Phase 2: detail pages, documents, BME Principal.

Idempotent: upsert by ISIN. Daily-updatable.
Traceable: every record has source_url + last_update.
"""

import logging
import re
from typing import Dict, List
from database import db
from models import new_id, now_iso

logger = logging.getLogger(__name__)

from services.playwright_runtime import launch_chromium

BME_GROWTH_URL = "https://www.bmegrowth.es/esp/Listado.aspx"
BME_SCALEUP_URL = "https://www.bolsasymercados.es/MTF_Equity/bme-scaleup/esp/Listado.aspx"
BME_GROWTH_DETAIL_BASE = "https://www.bmegrowth.es/esp"
BME_SCALEUP_DETAIL_BASE = "https://www.bolsasymercados.es/MTF_Equity/bme-scaleup/esp"


def _count_pages(companies):
    """Estimate pages scraped from company count."""
    return max(1, (len(companies) + 29) // 30)


async def sync_bme(markets: List[str] = None) -> Dict:
    """Sync BME Growth and/or Scaleup listings.

    Always writes a sync log entry — success, partial, or fatal failure — so
    `last_sync` never silently freezes. Previously a fatal error (e.g. Chromium
    binary missing) returned before the log write, leaving no record the sync
    was even attempted (same bug already fixed in services/cnmv_connector.py).
    """
    now = now_iso()
    if not markets:
        markets = ["growth", "scaleup", "principal"]

    total_imported = 0
    total_updated = 0
    by_market = {}
    errors = []
    detail_count = 0
    fatal_error = None

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        fatal_error = "Playwright no instalado (falta el paquete pip)"

    if not fatal_error:
        try:
            async with async_playwright() as p:
                browser = await launch_chromium(p)
                page = await browser.new_page()

                for market in markets:
                    try:
                        if market == "growth":
                            companies = await _scrape_listing(page, BME_GROWTH_URL, "growth")
                        elif market == "scaleup":
                            companies = await _scrape_listing(page, BME_SCALEUP_URL, "scaleup")
                        elif market == "principal":
                            companies = await _scrape_principal(page)
                        else:
                            continue

                        imported, updated = await _store_companies(companies, market, now)
                        total_imported += imported
                        total_updated += updated
                        by_market[market] = {"imported": imported, "updated": updated, "total": len(companies), "pages": _count_pages(companies)}
                        logger.info(f"BME {market}: {len(companies)} companies ({imported} new, {updated} updated)")

                    except Exception as e:
                        err = f"{market}: {str(e)[:150]}"
                        errors.append(err)
                        logger.error(f"BME {market} error: {e}")

                # Try to fetch detail pages for companies without full data
                detail_count = await _enrich_details(page, now)

                await browser.close()

        except Exception as e:
            # Typically Chromium binary missing/failed to launch. This used to
            # `return` immediately, skipping the log write below entirely.
            fatal_error = str(e)[:300]
            logger.error(f"BME sync fatal error: {fatal_error}")

    status = "error" if fatal_error else ("completed" if not errors else "partial")

    # Log sync
    await db.bme_sync_logs.insert_one({
        "log_id": new_id(),
        "type": "full_sync",
        "synced_at": now,
        "markets": markets,
        "total_imported": total_imported,
        "total_updated": total_updated,
        "details_enriched": detail_count,
        "by_market": by_market,
        "errors": errors,
        "fatal_error": fatal_error,
        "status": status,
    })

    match_result = None
    if not fatal_error:
        # Generate signals
        await _generate_signals(now)
        # Match against companies_master
        match_result = await _match_companies(now)

    result = {
        "status": status,
        "total_imported": total_imported,
        "total_updated": total_updated,
        "details_enriched": detail_count,
        "by_market": by_market,
        "matches": match_result,
        "errors": errors,
        "synced_at": now,
    }
    if fatal_error:
        result["message"] = fatal_error
    return result


async def _scrape_listing(page, url: str, market: str) -> List[Dict]:
    """Scrape full listing with ASP.NET postback pagination (Siguiente →).

    BME esta migrando estas paginas legacy (ASP.NET, /esp/Listado.aspx o
    /MTF_Equity/.../Listado.aspx) a un sitio nuevo (Adobe AEM, bolsasymercados.es/es/...).
    Confirmado 2026-07: la URL legacy de Growth (bmegrowth.es/esp/Listado.aspx) ya
    redirige de forma permanente a la pagina nueva, que no tiene tabla en absoluto
    (solo un aviso de "contactar con BME Market Data"). Scaleup, a esta fecha, todavia
    sirve la tabla legacy en la URL base -- pero anadir cualquier query string ya
    redirige tambien a la pagina nueva, senal de que la migracion esta en curso y
    puede completarse en cualquier momento.

    Por eso esta funcion ya NO asume que "pagina cargada sin excepcion" == "tabla
    presente": comprueba explicitamente que seguimos en una URL con el patron
    Listado.aspx tras el goto(), y que la primera pagina trae al menos una fila.
    Si BME nos ha movido a la pagina nueva (sin tabla), esto ahora es un error
    explicito -- antes se devolvia una lista vacia sin fallo, que sync_bme()
    registraba como "completed, 0 importados" (indistinguible de un mercado
    genuinamente vacio, el bug que reporto el testing agent)."""
    all_companies = []
    seen_isins = set()

    logger.info(f"BME {market}: loading {url}")
    await page.goto(url, wait_until="networkidle", timeout=20000)
    await page.wait_for_timeout(3000)

    current_url = page.url
    if "Listado.aspx" not in current_url:
        raise RuntimeError(
            f"la pagina redirigio a {current_url} (la URL legacy con la tabla de "
            f"empresas ya no esta disponible ahi -- probable migracion de sitio de "
            f"BME en curso, no un fallo transitorio de red)"
        )

    page_num = 0
    max_pages = 20

    while page_num < max_pages:
        page_num += 1

        companies = await page.evaluate('''() => {
            const rows = document.querySelectorAll('#Contenido_Tbl tr, table tr');
            const result = [];
            rows.forEach(tr => {
                const cells = tr.querySelectorAll('td');
                if (cells.length >= 4) {
                    const link = tr.querySelector('a[href*="Ficha"]');
                    const href = link ? link.getAttribute('href') : '';
                    const isinMatch = href.match(/((?:ES|MX|PT|FR|DE|GB|NL|LU|IE|IT)\\w{10})/);
                    const name = cells[0]?.textContent?.trim() || '';
                    if (name && !name.includes('Total') && !name.includes('Anterior') && !name.includes('Siguiente') && name.length > 2) {
                        let sector = '';
                        let web = '';
                        if (cells.length >= 6) {
                            sector = cells[4]?.textContent?.trim() || '';
                            web = cells[5]?.textContent?.trim() || '';
                        } else if (cells.length >= 5) {
                            const val4 = cells[4]?.textContent?.trim() || '';
                            if (val4.includes('http') || val4.includes('.com') || val4.includes('.es')) {
                                web = val4;
                            } else {
                                sector = val4;
                            }
                        } else if (cells.length >= 4) {
                            sector = cells[3]?.textContent?.trim() || '';
                        }
                        result.push({
                            name: name,
                            capitalization: cells[1]?.textContent?.trim() || '',
                            pct_year: cells[2]?.textContent?.trim() || '',
                            sector: sector,
                            web: web,
                            isin: isinMatch ? isinMatch[1] : '',
                            detail_path: href,
                        });
                    }
                }
            });
            return result;
        }''')

        new_count = 0
        for c in companies:
            if c["isin"] and c["isin"] not in seen_isins:
                seen_isins.add(c["isin"])
                all_companies.append(c)
                new_count += 1

        logger.info(f"  Page {page_num}: {len(companies)} rows, {new_count} new (total: {len(all_companies)})")

        if page_num == 1 and len(companies) == 0:
            # A real BME listing always has at least one company on its first page.
            # Zero rows here (with the URL check above already passed) means the
            # table structure/selectors no longer match what's on the page -- e.g.
            # a cookie-consent overlay, a partial site redesign short of a full
            # redirect, or a further stage of BME's ongoing site migration. Raising
            # here (instead of returning an empty list) makes sync_bme() log this
            # as a real failure instead of "completed, 0 importados".
            raise RuntimeError(
                "la primera pagina no devolvio ninguna fila -- la tabla esperada "
                "no esta donde el scraper la busca (selectores desactualizados o "
                "pagina distinta a la que se probo originalmente)"
            )

        if new_count == 0 and page_num > 1:
            break

        # ASP.NET pagination: click "Siguiente →" via __doPostBack
        has_next = await page.evaluate('''() => {
            const links = document.querySelectorAll('a');
            for (const a of links) {
                const text = a.textContent.trim();
                const href = a.getAttribute('href') || '';
                if ((text.includes('Siguiente') || text === '>') && href.includes('__doPostBack')) {
                    // Extract the postback target
                    const match = href.match(/__doPostBack\\('([^']+)'/);
                    if (match) {
                        __doPostBack(match[1], '');
                        return true;
                    }
                }
            }
            return false;
        }''')

        if not has_next:
            logger.info("  No more pages (no 'Siguiente' link found)")
            break

        await page.wait_for_timeout(3000)

    return all_companies


BME_PRINCIPAL_URL = "https://www.bolsasymercados.es/es/bme-exchange/mercados-y-cotizaciones/acciones/empresas-cotizadas.html"


async def _scrape_principal(page) -> List[Dict]:
    """Scrape BME Principal (mercado continuo) — Angular pagination."""
    all_companies = []
    seen = set()

    logger.info("BME principal: loading...")
    await page.goto(BME_PRINCIPAL_URL, wait_until="networkidle", timeout=25000)
    await page.wait_for_timeout(5000)

    for pg in range(10):
        companies = await page.evaluate('''() => {
            const rows = document.querySelectorAll('table tbody tr');
            const result = [];
            rows.forEach(tr => {
                const cells = tr.querySelectorAll('td');
                if (cells.length >= 3) {
                    const name = cells[0]?.textContent?.trim() || '';
                    if (name && name.length > 2) {
                        const link = tr.querySelector('a');
                        const href = link ? link.getAttribute('href') : '';
                        result.push({
                            name: name,
                            sector: cells[1]?.textContent?.trim() || '',
                            capitalization: '',
                            pct_year: '',
                            web: '',
                            isin: '',
                            detail_path: href,
                        });
                    }
                }
            });
            return result;
        }''')

        new_count = 0
        for c in companies:
            if c['name'] not in seen:
                seen.add(c['name'])
                # Generate a stable key from company name
                c['isin'] = f"BME_{c['name'][:20].upper().replace(' ', '_').replace(',', '').replace('.', '')}"
                all_companies.append(c)
                new_count += 1

        logger.info(f"  Principal page {pg+1}: {len(companies)} rows, {new_count} new (total: {len(all_companies)})")

        if new_count == 0 and pg > 0:
            break

        # Angular pagination: click next
        has_next = await page.evaluate('''() => {
            const btns = document.querySelectorAll('[class*="next"], [aria-label*="Next"], [aria-label*="next"], button, a');
            for (const b of btns) {
                const label = b.getAttribute('aria-label') || '';
                const cls = b.className || '';
                if (label.toLowerCase().includes('next') || label.toLowerCase().includes('siguiente') || cls.includes('next')) {
                    if (!b.disabled && !b.classList.contains('disabled')) {
                        b.click();
                        return true;
                    }
                }
            }
            const pageLinks = document.querySelectorAll('[class*="page-link"], [class*="pagination"] a');
            let currentPage = 0;
            let nextBtn = null;
            pageLinks.forEach(a => {
                const num = parseInt(a.textContent.trim());
                if (a.parentElement?.classList?.contains('active')) currentPage = num;
                if (num === currentPage + 1) nextBtn = a;
            });
            if (nextBtn) { nextBtn.click(); return true; }
            return false;
        }''')

        if not has_next:
            break
        await page.wait_for_timeout(3000)

    return all_companies



async def _store_companies(companies: List[Dict], market: str, now: str) -> tuple:
    """Store companies. Upsert by ISIN (idempotent)."""
    imported = 0
    updated = 0

    for c in companies:
        isin = c.get("isin", "")
        # If no ISIN from regex, try to extract from detail_path
        if not isin and c.get("detail_path"):
            import re as _re
            isin_match = _re.search(r'([A-Z]{2}\w{10})', c["detail_path"])
            if isin_match:
                isin = isin_match.group(1)
        # Fallback: use company name as unique key
        if not isin:
            isin = f"NOISIN_{c['name'][:30].upper().replace(' ', '_')}"

        # Parse capitalization
        cap_str = c.get("capitalization", "").replace(".", "").replace(",", ".")
        try:
            market_cap = float(cap_str) if cap_str else None
        except ValueError:
            market_cap = None

        # Parse annual performance
        pct_str = c.get("pct_year", "").replace(",", ".").replace("%", "").strip()
        try:
            annual_perf = float(pct_str) if pct_str else None
        except ValueError:
            annual_perf = None

        detail_base = BME_GROWTH_DETAIL_BASE if market == "growth" else BME_SCALEUP_DETAIL_BASE
        detail_path = c.get("detail_path", "")
        # Fix double /esp/ — the href from the page may already include the path
        if detail_path.startswith("Ficha"):
            detail_url = f"{detail_base}/{detail_path}"
        elif detail_path.startswith("/"):
            detail_url = f"https://www.bmegrowth.es{detail_path}" if market == "growth" else f"https://www.bolsasymercados.es{detail_path}"
        elif detail_path:
            detail_url = detail_path if detail_path.startswith("http") else f"{detail_base}/{detail_path}"
        else:
            detail_url = None

        doc = {
            "company_name": c["name"],
            "isin": isin,
            "market": "bme",
            "market_segment": market,
            "sector": c.get("sector", ""),
            "market_cap": market_cap,
            "annual_performance": annual_perf,
            "website": c.get("web", ""),
            "is_public_company": True,
            "listed_in_growth": True if market == "growth" else False,
            "listed_in_scaleup": True if market == "scaleup" else False,
            "listed_in_bme_principal": True if market == "principal" else False,
            "source_url": detail_url,
            "last_update": now,
        }

        result = await db.bme_companies.update_one(
            {"isin": isin},
            {"$set": doc,
             "$setOnInsert": {
                 "bme_id": new_id(),
                 "ticker": None,
                 "listing_date": None,
                 "share_price": None,
                 "shares_outstanding": None,
                 "daily_change": None,
                 "annual_high": None,
                 "annual_low": None,
                 "dividend_yield": None,
                 "matched_company_id": None,
                 "matched_company_cif": None,
                 "match_method": None,
                 "created_at": now,
             }},
            upsert=True,
        )

        if result.upserted_id:
            imported += 1
        elif result.modified_count > 0:
            updated += 1

    return imported, updated


async def _enrich_details(page, now: str) -> int:
    """Fetch detail pages for companies and extract financial data."""
    companies = await db.bme_companies.find(
        {"source_url": {"$ne": None}, "share_price": None, "isin": {"$not": {"$regex": "^BME_|^NOISIN"}}},
        {"_id": 0, "isin": 1, "source_url": 1, "company_name": 1}
    ).limit(20).to_list(20)

    enriched = 0
    for c in companies:
        url = c.get("source_url", "")
        if not url or not url.startswith("http"):
            continue
        try:
            await page.goto(url, wait_until="networkidle", timeout=12000)
            await page.wait_for_timeout(2000)

            detail = await page.evaluate('''() => {
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

            if not detail:
                continue

            update = {}

            # Ticker
            ticker = detail.get("Ticker")
            if ticker and len(ticker) < 10:
                update["ticker"] = ticker

            # NIF
            nif = detail.get("NIF")
            if nif and len(nif) > 5:
                update["company_nif"] = nif

            # Shares outstanding
            shares = detail.get("Acciones en circulación", "")
            if shares:
                shares_clean = shares.replace(".", "").replace(",", ".").strip()
                try:
                    update["shares_outstanding"] = int(float(shares_clean))
                except ValueError:
                    pass

            # Price (Ref. or Últ.)
            for price_key in ["Ref.", "Últ."]:
                price = detail.get(price_key, "")
                if price:
                    price_clean = price.replace(".", "").replace(",", ".").strip()
                    try:
                        val = float(price_clean)
                        if 0 < val < 100000:
                            update["share_price"] = val
                            break
                    except ValueError:
                        pass

            # Daily change
            dif = detail.get("Dif.(%)", "")
            if dif:
                dif_clean = dif.replace(",", ".").replace("%", "").strip()
                try:
                    update["daily_change"] = float(dif_clean)
                except ValueError:
                    pass

            # Market cap from text "X,XX mill. €"
            cap_text = detail.get("Últ. precio", "")
            if "mill" in cap_text:
                cap_clean = cap_text.replace("mill.", "").replace("€", "").replace(".", "").replace(",", ".").strip()
                try:
                    update["market_cap"] = float(cap_clean) * 1_000_000
                except ValueError:
                    pass

            # Auditor
            auditor = detail.get("Auditor")
            if auditor and len(auditor) > 3:
                update["auditor"] = auditor

            if update:
                update["last_update"] = now
                update["detail_enriched"] = True
                await db.bme_companies.update_one({"isin": c["isin"]}, {"$set": update})
                enriched += 1
                logger.info(f"  Enriched {c['company_name'][:25]}: {list(update.keys())}")

        except Exception as e:
            logger.debug(f"Detail failed for {c.get('company_name','?')}: {e}")

    return enriched

    return enriched


async def _generate_signals(now: str):
    """Generate BME intelligence signals."""
    total = await db.bme_companies.count_documents({})
    growth = await db.bme_companies.count_documents({"listed_in_growth": True})
    scaleup = await db.bme_companies.count_documents({"listed_in_scaleup": True})
    principal = await db.bme_companies.count_documents({"listed_in_bme_principal": True})

    signals = [
        {"signal_id": new_id(), "signal_type": "bme_listed_companies", "value": total,
         "description": f"{total} companias cotizadas en BME (Principal {principal} + Growth {growth} + Scaleup {scaleup})",
         "confidence": 0.95, "sources_used": ["bme"], "generated_at": now},
    ]
    if principal > 0:
        signals.append({"signal_id": new_id(), "signal_type": "listed_in_bme_principal", "value": principal,
                        "description": f"{principal} companias en BME Principal (Mercado Continuo)",
                        "confidence": 0.95, "sources_used": ["bme"], "generated_at": now})
    if growth > 0:
        signals.append({"signal_id": new_id(), "signal_type": "listed_in_growth", "value": growth,
                        "description": f"{growth} companias en BME Growth",
                        "confidence": 0.95, "sources_used": ["bme"], "generated_at": now})
    if scaleup > 0:
        signals.append({"signal_id": new_id(), "signal_type": "listed_in_scaleup", "value": scaleup,
                        "description": f"{scaleup} companias en BME Scaleup",
                        "confidence": 0.95, "sources_used": ["bme"], "generated_at": now})

    # High cap companies
    high_cap_100m = await db.bme_companies.count_documents({"market_cap": {"$gte": 100_000_000}})
    if high_cap_100m:
        signals.append({"signal_id": new_id(), "signal_type": "market_cap_above_100m", "value": high_cap_100m,
                        "description": f"{high_cap_100m} companias con capitalizacion > 100M EUR",
                        "confidence": 0.9, "sources_used": ["bme"], "generated_at": now})

    high_cap_500m = await db.bme_companies.count_documents({"market_cap": {"$gte": 500_000_000}})
    if high_cap_500m:
        signals.append({"signal_id": new_id(), "signal_type": "market_cap_above_500m", "value": high_cap_500m,
                        "description": f"{high_cap_500m} companias con capitalizacion > 500M EUR",
                        "confidence": 0.9, "sources_used": ["bme"], "generated_at": now})

    # High dividend companies
    high_div = await db.bme_companies.count_documents({"dividend_yield": {"$gte": 5}})
    if high_div:
        signals.append({"signal_id": new_id(), "signal_type": "high_dividend_company", "value": high_div,
                        "description": f"{high_div} companias con rentabilidad por dividendo >= 5%",
                        "confidence": 0.85, "sources_used": ["bme"], "generated_at": now})

    # High annual performance (proxy for market_cap_growth)
    high_growth = await db.bme_companies.count_documents({"annual_performance": {"$gte": 30}})
    if high_growth:
        signals.append({"signal_id": new_id(), "signal_type": "high_market_cap_growth", "value": high_growth,
                        "description": f"{high_growth} companias con revalorizacion anual >= 30%",
                        "confidence": 0.85, "sources_used": ["bme"], "generated_at": now})

    # Capital increases (from corporate_events when available — placeholder for now)
    cap_increases = await db.corporate_events.count_documents(
        {"event_type": "capital_increase"}
    ) if "corporate_events" in await db.list_collection_names() else 0
    if cap_increases:
        signals.append({"signal_id": new_id(), "signal_type": "capital_increase_last_12m", "value": cap_increases,
                        "description": f"{cap_increases} ampliaciones de capital registradas",
                        "confidence": 0.9, "sources_used": ["bme"], "generated_at": now})

    await db.bme_signals.delete_many({})
    if signals:
        await db.bme_signals.insert_many(signals)


async def _match_companies(now: str) -> Dict:
    """Match BME companies against companies_master by name."""
    matched = 0
    total = 0

    companies = await db.bme_companies.find(
        {"matched_company_id": None}, {"_id": 0, "isin": 1, "company_name": 1}
    ).to_list(500)

    for c in companies:
        total += 1
        name = c.get("company_name", "")
        if not name:
            continue

        # Try exact name match
        normalized = name.upper().replace(",", "").replace(".", "").replace("  ", " ").strip()
        master = await db.companies_master.find_one(
            {"normalized_name": {"$regex": f"^{re.escape(normalized[:20])}", "$options": "i"}},
            {"_id": 0, "master_company_id": 1, "cif": 1}
        )

        if master:
            await db.bme_companies.update_one(
                {"isin": c["isin"]},
                {"$set": {
                    "matched_company_id": master["master_company_id"],
                    "matched_company_cif": master.get("cif"),
                    "match_method": "name_prefix",
                    "matched_at": now,
                }}
            )
            matched += 1

    return {"checked": total, "matched": matched}


async def get_bme_stats() -> Dict:
    """Get BME intelligence stats."""
    total = await db.bme_companies.count_documents({})
    growth = await db.bme_companies.count_documents({"listed_in_growth": True})
    scaleup = await db.bme_companies.count_documents({"listed_in_scaleup": True})
    principal = await db.bme_companies.count_documents({"listed_in_bme_principal": True})
    matched = await db.bme_companies.count_documents({"matched_company_id": {"$ne": None}})
    signals = await db.bme_signals.count_documents({})

    cap_pipeline = [
        {"$match": {"market_cap": {"$ne": None}}},
        {"$group": {"_id": None, "total": {"$sum": "$market_cap"}, "avg": {"$avg": "$market_cap"},
                    "max": {"$max": "$market_cap"}}},
    ]
    cap = await db.bme_companies.aggregate(cap_pipeline).to_list(1)

    sector_pipeline = [
        {"$group": {"_id": "$sector", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    by_sector = await db.bme_companies.aggregate(sector_pipeline).to_list(10)

    # Only look at full-listing syncs here — the nightly "enrichment" job (which only
    # fills in missing detail fields for up to 50 already-known companies) writes to
    # the same collection and used to be indistinguishable, making a failed real sync
    # look "fresh" because enrichment quietly ran (or tried to) every night.
    last_sync = await db.bme_sync_logs.find_one({"type": "full_sync"}, {"_id": 0}, sort=[("synced_at", -1)])

    return {
        "total": total,
        "growth": growth,
        "scaleup": scaleup,
        "principal": principal,
        "matched_to_master": matched,
        "signals": signals,
        "market_cap": cap[0] if cap else {},
        "by_sector": [{"sector": s["_id"], "count": s["count"]} for s in by_sector],
        "last_sync": last_sync,
    }
