"""Intelligence Scheduler — Automatic nightly sync for all intelligence modules.

Schedule (Europe/Madrid timezone, UTC+1/+2):
  - BORME ingestion: Daily 03:00 Madrid (existing scheduler)
  - Sector Intelligence: Daily 04:00 Madrid (~02:00-03:00 UTC)
  - Geo Intelligence: Daily 04:05 Madrid
  - Cross Intelligence: Daily 04:10 Madrid
  - ECB risk-free snapshot: Daily after intelligence refresh

These modules are derived layers from BORME, INE and other sources.
They must recalculate every night after data updates.
"""

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_scheduler_running = False

# Schedule: Daily at 02:00 UTC ~ 04:00 Madrid (CET/CEST)
SYNC_HOUR_UTC = 2
CHECK_INTERVAL_SECONDS = 600  # Check every 10 minutes


async def start_intelligence_scheduler():
    """Start the daily intelligence sync scheduler."""
    global _scheduler_running
    if _scheduler_running:
        return
    _scheduler_running = True
    logger.info("Intelligence scheduler started (daily ~04:00 Madrid)")
    asyncio.create_task(_scheduler_loop())


async def _scheduler_loop():
    """Main loop — checks every 10 min if it's time to sync."""
    global _scheduler_running
    last_sync_date = None

    while _scheduler_running:
        try:
            now = datetime.now(timezone.utc)
            today_str = now.strftime("%Y%m%d")
            is_sync_hour = now.hour == SYNC_HOUR_UTC

            if is_sync_hour and last_sync_date != today_str:
                logger.info(f"Intelligence scheduler: starting nightly sync ({today_str})")
                await _run_full_sync()
                last_sync_date = today_str
                logger.info(f"Intelligence scheduler: nightly sync completed ({today_str})")

            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

        except Exception as e:
            logger.error(f"Intelligence scheduler error: {e}")
            await asyncio.sleep(300)


async def _run_full_sync():
    """Execute full intelligence recalculation pipeline.

    Each layer (sector/geo/cross/economic) is computed independently from base
    data (BORME/Iberinform/DIRCE) — none of them reads another's output, so
    there is no real dependency forcing sequential all-or-nothing execution.
    Fixed 2026-07-23: previously all 4 steps shared ONE try/except. If step 2
    (Geo) raised, the whole function jumped to the outer `except` and logged a
    single pseudo-module "intelligence_pipeline: failed" — steps 3/4 (Cross,
    Economic) never ran today AND never got a log entry for today either,
    leaving their `intelligence_sync_log` doc frozen at whatever it said the
    last time they succeeded (possibly days old). `GET /public/intelligence/
    sync-status` (routes/intelligence_status.py) reads that doc directly, so
    the UI would show Cross/Economic as green/"completed" with a stale
    timestamp while masking that today's run silently never reached them.
    Now each step has its own try/except and ALWAYS logs today's real outcome
    (completed or failed) regardless of what happened to the others."""
    from database import db

    # Step 1: Sector Intelligence
    try:
        from services.sector_intelligence_v2 import compute_sector_intelligence_v2
        si = await compute_sector_intelligence_v2()
        await _log_sync("sector_intelligence", "completed", si.get("total", 0))
        logger.info(f"  Sector Intelligence: {si['total']} entries")
    except Exception as e:
        logger.error(f"  Sector Intelligence failed: {e}")
        await _log_sync("sector_intelligence", "failed", 0, str(e))

    # Step 2: Geo Intelligence
    try:
        from services.geo_intelligence import compute_geo_intelligence
        gi = await compute_geo_intelligence()
        await _log_sync("geo_intelligence", "completed", gi.get("total", 0))
        logger.info(f"  Geo Intelligence: {gi['total']} entries")
    except Exception as e:
        logger.error(f"  Geo Intelligence failed: {e}")
        await _log_sync("geo_intelligence", "failed", 0, str(e))

    # Step 3: Cross Intelligence
    try:
        from services.sector_geo_cross import compute_sector_geo_cross
        cx = await compute_sector_geo_cross()
        await _log_sync("cross_intelligence", "completed", cx.get("combinations", 0))
        logger.info(f"  Cross Intelligence: {cx['combinations']} combinations")
    except Exception as e:
        logger.error(f"  Cross Intelligence failed: {e}")
        await _log_sync("cross_intelligence", "failed", 0, str(e))

    # Step 4: Economic Intelligence Layer
    try:
        from services.economic_intelligence import rebuild_economic_metrics, rebuild_economic_signals
        econ = await rebuild_economic_metrics()
        await _log_sync("economic_intelligence", "completed", econ.get("total_metrics", 0))
        logger.info(f"  Economic Intelligence: {econ['total_metrics']} metrics")

        esig = await rebuild_economic_signals()
        logger.info(f"  Economic Signals: {esig['signals_generated']} signals")
    except Exception as e:
        logger.error(f"  Economic Intelligence failed: {e}")
        await _log_sync("economic_intelligence", "failed", 0, str(e))

    # Step 5: BME Enrichment (daily, only stale/new companies) — kept isolated,
    # same as before: it already has its own health tracking via
    # bme_connector.get_bme_stats() (fixed in Actualización v5), separate from
    # intelligence_sync_log, so a BME hiccup was never masking these 4 modules
    # and vice versa.
    try:
        from services.bme_enrichment import run_full_enrichment
        bme = await run_full_enrichment(max_companies=50)
        logger.info(f"  BME Enrichment: {bme.get('enriched', 0)} companies enriched")
    except Exception as bme_err:
        logger.warning(f"  BME Enrichment skipped: {bme_err}")

    # Step 6: dated ECB EUR AAA 10-year spot rate for WACC.
    try:
        from services.engines.valuation.ecb_risk_free import refresh_ecb_risk_free
        ecb = await refresh_ecb_risk_free(db)
        await _log_sync("ecb_risk_free", "completed", 1)
        logger.info(f"  ECB risk-free: {ecb['observation_date']} {ecb['raw_percent']:.4f}%")
    except Exception as ecb_err:
        logger.error(f"  ECB risk-free refresh failed: {ecb_err}")
        await _log_sync("ecb_risk_free", "failed", 0, str(ecb_err))


async def _log_sync(module: str, status: str, entries: int, error: str = None):
    """Log sync event to database."""
    from database import db
    from models import now_iso

    doc = {
        "module": module,
        "status": status,
        "entries": entries,
        "synced_at": now_iso(),
        "trigger": "scheduler",
    }
    if error:
        doc["error"] = error

    await db.intelligence_sync_log.update_one(
        {"module": module},
        {"$set": doc},
        upsert=True,
    )


async def log_manual_sync(module: str, entries: int):
    """Log a manual sync trigger."""
    from database import db
    from models import now_iso

    await db.intelligence_sync_log.update_one(
        {"module": module},
        {"$set": {
            "module": module,
            "status": "completed",
            "entries": entries,
            "synced_at": now_iso(),
            "trigger": "manual",
        }},
        upsert=True,
    )


async def stop_intelligence_scheduler():
    global _scheduler_running
    _scheduler_running = False
    logger.info("Intelligence scheduler stopped")
