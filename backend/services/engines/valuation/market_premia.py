"""Versioned market and country equity-risk-premium snapshots."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict

SERIES = {
    "mature_market_erp": "ERP.MATURE_MARKET",
    "spain_country_risk_premium": "CRP.ESP",
}


def premium_snapshot(kind: str, value: float, observation_date: str,
                     source: str, source_url: str) -> Dict[str, Any]:
    if kind not in SERIES:
        raise ValueError(f"unsupported premium kind: {kind}")
    number=float(value)
    if not 0 <= number <= .20:
        raise ValueError("premium must be a decimal between 0 and 0.20")
    datetime.fromisoformat(observation_date)
    return {"series_key":SERIES[kind],"kind":kind,"value":number,
            "observation_date":observation_date,"source":source,
            "source_url":source_url,"status":"external_reference",
            "captured_at":datetime.now(timezone.utc).isoformat()}


async def store_premium(database, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    await database.valuation_market_snapshots.update_one(
        {"series_key":snapshot["series_key"],
         "observation_date":snapshot["observation_date"]},
        {"$setOnInsert":snapshot},upsert=True)
    return snapshot
