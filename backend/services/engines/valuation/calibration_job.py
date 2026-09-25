"""Streaming Mongo calibration job. Publishing creates candidates, never active rules."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from database import db
from services.engines.financial.metrics import build_series
from .calibration import CalibrationAccumulator, CALIBRATION_VERSION

MASTER_PROJECTION = {
    "_id": 0, "master_id": 1, "cif_normalized": 1,
    "classification.cnae_code": 1,
}
FINANCIAL_PROJECTION = {"_id": 0, "cif_normalized": 1, "year": 1, "basis": 1,
                        "fiscal_close_date": 1, "accounts": 1}

async def run_calibration(*, cutoff_date: Optional[str] = None, max_companies: Optional[int] = None,
                          batch_size: int = 1000, publish: bool = False) -> Dict[str, Any]:
    cutoff = cutoff_date or date.today().isoformat()
    cutoff_year = int(cutoff[:4])
    accumulator = CalibrationAccumulator(cutoff)
    cursor = db.master_companies.find(
        {"cif_normalized": {"$exists": True, "$ne": None}}, MASTER_PROJECTION
    ).sort("cif_normalized", 1)
    processed = 0
    batch = []
    async for master in cursor:
        batch.append(master)
        reached_limit = max_companies and processed + len(batch) >= max_companies
        if len(batch) >= batch_size or reached_limit:
            if max_companies:
                batch = batch[:max(0, max_companies - processed)]
            processed += await _process_batch(batch, cutoff_year, accumulator)
            batch = []
            if max_companies and processed >= max_companies:
                break
    if batch and (not max_companies or processed < max_companies):
        if max_companies:
            batch = batch[:max(0, max_companies - processed)]
        processed += await _process_batch(batch, cutoff_year, accumulator)

    result = accumulator.result()
    generated_at = datetime.now(timezone.utc).isoformat()
    run_id = f"valuation-calibration-{cutoff}-{uuid4().hex[:10]}"
    result.update({"run_id": run_id, "generated_at": generated_at,
                   "published": False, "processed": processed})
    if publish:
        await _publish_candidates(result)
        result["published"] = True
    return result

async def _process_batch(masters, cutoff_year: int, accumulator: CalibrationAccumulator) -> int:
    cifs = [master["cif_normalized"] for master in masters]
    financials: Dict[str, list] = {}
    query = {"cif_normalized": {"$in": cifs}, "year": {"$lte": cutoff_year}}
    async for document in db.norm_financials.find(query, FINANCIAL_PROJECTION):
        financials.setdefault(document["cif_normalized"], []).append(document)
    for master in masters:
        classification = master.get("classification") or {}
        accumulator.add_company({
            "master_id": master.get("master_id"),
            "cif_normalized": master.get("cif_normalized"),
            "cnae_code": classification.get("cnae_code"),
            "series": build_series(financials.get(master["cif_normalized"], [])),
        })
    return len(masters)

async def _publish_candidates(result: Dict[str, Any]) -> None:
    await db.valuation_sector_calibration_runs.create_index("run_id", unique=True)
    await db.valuation_sector_rule_candidates.create_index(
        [("run_id", 1), ("cohort_key", 1)], unique=True)
    run_doc = {key: value for key, value in result.items() if key != "cohorts"}
    run_doc["cohort_count"] = len(result["cohorts"])
    await db.valuation_sector_calibration_runs.insert_one(run_doc)
    if result["cohorts"]:
        documents = []
        for cohort in result["cohorts"]:
            documents.append({
                **cohort,
                "run_id": result["run_id"],
                "pipeline_version": CALIBRATION_VERSION,
                "cutoff_date": result["cutoff_date"],
                "generated_at": result["generated_at"],
                "source": "Iberinform",
                "active": False,
            })
        await db.valuation_sector_rule_candidates.insert_many(documents, ordered=False)
