"""DataComex Playwright Sync — Robust connector for real trade data.

Primary sync mechanism: Playwright fetches from datacomex.comercio.es
Fallback: CSV upload via /upload-csv endpoint

Features:
  - Retries with backoff on failure
  - Preserves last valid dataset (never deletes before new data is confirmed)
  - Audit metadata: sync date, origin, checksum, version
  - Logs all sync attempts to datacomex_sync_logs
"""

import logging
import hashlib
import json
import re
from typing import Dict, List
from datetime import datetime, timezone
from database import db
from models import new_id, now_iso

logger = logging.getLogger(__name__)

DATACOMEX_URL = "https://datacomex.comercio.es/data"
YEARS_TO_FETCH = 6  # Last 6 years
MAX_RETRIES = 2


async def _install_chromium() -> str:
    """Instala el Chromium de Playwright (el binario no viaja con `pip install`)."""
    import asyncio, sys
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "playwright", "install", "chromium",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("playwright install chromium: timeout 300 s")
    if proc.returncode != 0:
        raise RuntimeError(f"playwright install chromium fallo: {out.decode(errors='ignore')[-300:]}")
    return out.decode(errors="ignore")[-200:]


async def _launch_browser(p):
    """Lanza Chromium; si el binario no existe (contenedor redesplegado sin
    `playwright install`), lo instala una vez y reintenta."""
    args = ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
    try:
        return await p.chromium.launch(headless=True, args=args)
    except Exception as e:
        if "Executable doesn't exist" not in str(e):
            raise
        logger.warning("DataComex: Chromium no instalado, ejecutando 'playwright install chromium'...")
        await _install_chromium()
        return await p.chromium.launch(headless=True, args=args)



async def sync_via_playwright(years: List[int] = None) -> Dict:
    """Fetch real trade data from DataComex via Playwright.
    
    Preserves last valid dataset — only replaces after new data is confirmed.
    """
    now = now_iso()
    current_year = datetime.now(timezone.utc).year

    if not years:
        years = list(range(current_year - YEARS_TO_FETCH + 1, current_year + 1))

    log_id = new_id()

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return await _log_and_return(log_id, now, "error",
            "Playwright not installed", years, 0)

    all_rows = []
    errors = []

    try:
        async with async_playwright() as p:
            browser = await _launch_browser(p)
            page = await browser.new_page()

            logger.info("DataComex sync: loading page...")
            await page.goto(DATACOMEX_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)

            for year in years:
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        rows = await _fetch_year(page, year)
                        if rows:
                            all_rows.extend(rows)
                            logger.info(f"DataComex {year}: {len(rows)} rows")
                            break
                        else:
                            logger.warning(f"DataComex {year}: 0 rows (attempt {attempt+1})")
                    except Exception as e:
                        if attempt == MAX_RETRIES:
                            err = f"{year}: {str(e)[:100]}"
                            errors.append(err)
                            logger.error(f"DataComex {year} failed: {e}")
                        else:
                            await page.wait_for_timeout(2000)

            await browser.close()

    except Exception as e:
        return await _log_and_return(log_id, now, "error",
            f"Browser error: {str(e)[:200]}", years, 0, errors)

    if not all_rows:
        return await _log_and_return(log_id, now, "error",
            "No data fetched from any year", years, 0, errors)

    # Build documents
    docs = _build_docs(all_rows, now)
    checksum = _compute_checksum(docs)

    # Check if data actually changed
    last_sync = await db.datacomex_sync_logs.find_one(
        {"status": "completed", "checksum": {"$exists": True}},
        {"_id": 0}, sort=[("synced_at", -1)]
    )
    if last_sync and last_sync.get("checksum") == checksum:
        return await _log_and_return(log_id, now, "unchanged",
            "Data identical to last sync", years, len(docs), [],
            checksum=checksum)

    # Persist: swap atomically (insert new, then delete old)
    if docs:
        # Tag with version
        version = now[:10].replace("-", "")
        for d in docs:
            d["dataset_version"] = version

        await db.datacomex_raw_data.insert_many(docs)
        # Now delete old data (everything without the new version tag)
        await db.datacomex_raw_data.delete_many({"dataset_version": {"$ne": version}})

    return await _log_and_return(log_id, now, "completed",
        None, years, len(docs), errors,
        checksum=checksum, origin="playwright_live")


async def _fetch_year(page, year: int) -> List[Dict]:
    """Fetch export+import data for a single year using jQuery AJAX."""
    await page.evaluate(f'''() => {{
        document.querySelectorAll('input[type="checkbox"]').forEach(el => el.checked = false);
        document.getElementById('chk_export').checked = true;
        document.getElementById('chk_import').checked = true;
        var yearEl = document.getElementById('tw_period{year}');
        if (yearEl) yearEl.checked = true;
        document.querySelectorAll('.taricArbol').forEach(el => el.checked = true);
        var pais = document.querySelector('input[name="[Pais].&[Total Mundo]"]');
        if (pais) pais.checked = true;
    }}''')
    await page.wait_for_timeout(300)

    result_html = await page.evaluate('''() => {
        return new Promise((resolve) => {
            $.ajax({
                type: 'POST', url: "/Data/ResultQueryData",
                data: $("#formularioBusqueda").serialize(),
                dataType: 'html', cache: false, timeout: 60000,
                success: function(r) { resolve(r); },
                error: function(e) { resolve("ERROR:" + e.status); }
            });
        });
    }''')

    if result_html.startswith("ERROR"):
        raise Exception(f"AJAX error: {result_html}")

    await page.evaluate('(html) => { document.getElementById("tablaResultados").innerHTML = html; }', result_html)
    await page.wait_for_timeout(500)

    rows = await page.evaluate('''() => {
        var trs = document.querySelectorAll('#lstResults tbody tr');
        var result = [];
        trs.forEach(function(tr) {
            var cells = tr.querySelectorAll('td');
            if (cells.length >= 6) {
                var euros = cells[4].textContent.trim();
                if (euros) result.push({
                    flujo: cells[0].textContent.trim(),
                    periodo: cells[1].textContent.trim(),
                    taric: cells[3].textContent.trim(),
                    euros: euros,
                    kilos: cells[5].textContent.trim()
                });
            }
        });
        return result;
    }''')

    # Filter: keep only chapter-level (not "Total Taric")
    return [r for r in rows if r['taric'] != 'Total Taric' and r['euros']]


def _build_docs(rows: List[Dict], now: str) -> List[Dict]:
    """Convert raw Playwright rows to DB documents."""
    docs = []
    for r in rows:
        taric = _extract_taric(r['taric'])
        if not taric:
            continue
        euros = _parse_number(r['euros'])
        if euros <= 0:
            continue

        year_match = re.search(r'(\d{4})', r.get('periodo', ''))
        year = int(year_match.group(1)) if year_match else None

        docs.append({
            "record_id": new_id(),
            "flow": "export" if "xport" in r['flujo'] else "import",
            "year": year,
            "month": None,
            "period": r.get('periodo', ''),
            "country": "Total Mundo",
            "taric_code": taric,
            "taric_description": r['taric'],
            "euros": euros,
            "kilos": _parse_number(r.get('kilos', '0')),
            "source": "datacomex_real",
            "imported_at": now,
        })
    return docs


def _extract_taric(s: str) -> str | None:
    m = re.match(r'^(\d{2})', s.strip())
    return m.group(1) if m else None


def _parse_number(s: str) -> float:
    if not s:
        return 0
    cleaned = s.replace('.', '').replace(',', '.').strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0


def _compute_checksum(docs: List[Dict]) -> str:
    """Compute a checksum of the dataset for change detection."""
    key_data = sorted(
        f"{d['flow']}:{d['year']}:{d['taric_code']}:{d['euros']}"
        for d in docs if d.get('year')
    )
    return hashlib.sha256("|".join(key_data).encode()).hexdigest()[:16]


async def _log_and_return(log_id, now, status, error, years, records,
                          errors=None, checksum=None, origin="playwright_live"):
    doc = {
        "log_id": log_id,
        "synced_at": now,
        "status": status,
        "trigger": "auto" if not error else "auto",
        "origin": origin,
        "years": years,
        "records_imported": records,
        "checksum": checksum,
        "errors": errors or [],
    }
    if error:
        doc["error"] = error

    await db.datacomex_sync_logs.insert_one(doc)

    result = {
        "status": status,
        "records": records,
        "years": years,
        "checksum": checksum,
        "synced_at": now,
    }
    if error:
        result["error"] = error
    if errors:
        result["errors"] = errors
    return result


async def post_sync_rebuild() -> Dict:
    """After importing new data, rebuild metrics + signals + Economic Intelligence."""
    from services.datacomex_connector import rebuild_trade_metrics, rebuild_signals
    from services.economic_intelligence import rebuild_economic_metrics, rebuild_economic_signals

    metrics = await rebuild_trade_metrics()
    signals = await rebuild_signals()
    econ = await rebuild_economic_metrics()
    esig = await rebuild_economic_signals()

    return {
        "trade_metrics": metrics.get("metrics_computed", 0),
        "trade_signals": signals.get("signals_generated", 0),
        "economic_metrics": econ.get("total_metrics", 0),
        "economic_signals": esig.get("signals_generated", 0),
    }


async def get_sync_health() -> Dict:
    """Check DataComex sync health for alerting."""
    last_success = await db.datacomex_sync_logs.find_one(
        {"status": "completed"}, {"_id": 0}, sort=[("synced_at", -1)]
    )

    raw_count = await db.datacomex_raw_data.count_documents({})
    real_count = await db.datacomex_raw_data.count_documents({"source": "datacomex_real"})
    seed_count = await db.datacomex_raw_data.count_documents({"source": "datacomex_seed"})

    days_since_sync = None
    if last_success and last_success.get("synced_at"):
        try:
            last_dt = datetime.fromisoformat(last_success["synced_at"].replace("Z", "+00:00"))
            days_since_sync = (datetime.now(timezone.utc) - last_dt).days
        except Exception:
            pass

    stale = days_since_sync is not None and days_since_sync > 45

    return {
        "last_sync": last_success,
        "days_since_sync": days_since_sync,
        "stale": stale,
        "stale_threshold_days": 45,
        "raw_records": raw_count,
        "real_records": real_count,
        "seed_records": seed_count,
        "data_origin": "real" if real_count > 0 else ("seed" if seed_count > 0 else "empty"),
    }
