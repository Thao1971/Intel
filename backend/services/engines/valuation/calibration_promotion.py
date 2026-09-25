"""Explicit review and activation workflow for Iberinform calibration snapshots."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def review_run(database, run_id: str, *, approver: str,
                     notes: Optional[str] = None) -> Dict[str, Any]:
    run = await database.valuation_sector_calibration_runs.find_one(
        {"run_id": run_id}, {"_id": 0})
    if not run:
        raise ValueError("calibration run not found")
    if run.get("status") not in ("candidate", "reviewed"):
        raise ValueError(f"run status {run.get('status')!r} cannot be reviewed")
    review = {"status": "reviewed", "reviewed_at": _now(),
              "reviewed_by": approver, "review_notes": notes}
    await database.valuation_sector_calibration_runs.update_one(
        {"run_id": run_id}, {"$set": review})
    await database.valuation_sector_rule_candidates.update_many(
        {"run_id": run_id}, {"$set": {"calibration_status": "reviewed_iberinform",
                                        "decision_readiness": "reviewed",
                                        **{k: v for k, v in review.items() if k != "status"}}})
    return {"run_id": run_id, **review}


async def activate_run(database, run_id: str, *, approver: str,
                       notes: Optional[str] = None,
                       ruleset_version: Optional[str] = None) -> Dict[str, Any]:
    run = await database.valuation_sector_calibration_runs.find_one(
        {"run_id": run_id}, {"_id": 0})
    if not run:
        raise ValueError("calibration run not found")
    if run.get("status") != "reviewed":
        raise ValueError("run must be reviewed before activation")
    candidates = await database.valuation_sector_rule_candidates.find(
        {"run_id": run_id, "quality.eligible_for_review": True}, {"_id": 0}).to_list(None)
    usable = []
    for candidate in candidates:
        parameters = {
            key: value for key, value in (candidate.get("parameters") or {}).items()
            if all(value.get(q) is not None for q in ("p25", "median", "p75"))
        }
        if parameters:
            usable.append({**candidate, "parameters": parameters})
    if not usable:
        raise ValueError("run has no cohorts with publishable P25/median/P75")
    version = ruleset_version or f"sector-rules-{run['cutoff_date']}-v1"
    if await database.valuation_sector_rule_versions.find_one({"ruleset_version": version}):
        raise ValueError("ruleset_version already exists")
    activated_at = _now()
    documents = [{
        **candidate, "ruleset_version": version,
        "calibration_status": "calibrated_iberinform",
        "decision_readiness": "review_ready", "effective_from": activated_at[:10],
        "active": False, "activated_from_run": run_id,
        "approved_by": approver, "approval_notes": notes,
        "activated_at": activated_at,
    } for candidate in usable]
    await database.valuation_sector_rules.insert_many(documents, ordered=False)
    await database.valuation_sector_rules.update_many(
        {"active": True}, {"$set": {"active": False, "superseded_at": activated_at,
                                     "superseded_by": version}})
    await database.valuation_sector_rules.update_many(
        {"ruleset_version": version}, {"$set": {"active": True}})
    version_doc = {
        "ruleset_version": version, "run_id": run_id, "source": "Iberinform",
        "cutoff_date": run["cutoff_date"], "pipeline_version": run.get("pipeline_version"),
        "cohort_count": len(documents), "status": "active", "active": True,
        "approved_by": approver, "approval_notes": notes, "activated_at": activated_at,
    }
    await database.valuation_sector_rule_versions.update_many(
        {"active": True}, {"$set": {"active": False, "status": "superseded",
                                     "superseded_at": activated_at,
                                     "superseded_by": version}})
    await database.valuation_sector_rule_versions.insert_one(version_doc)
    await database.valuation_sector_calibration_runs.update_one(
        {"run_id": run_id}, {"$set": {"status": "calibrated", "active_version": version,
                                        "activated_at": activated_at,
                                        "activated_by": approver}})
    return version_doc
