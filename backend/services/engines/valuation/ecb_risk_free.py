"""Automatic dated ECB EUR AAA 10-year spot-rate capture."""
from __future__ import annotations
import csv, io
from datetime import datetime, timezone
from typing import Any, Dict, Optional

SERIES_KEY = "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"
API_URL = f"https://data-api.ecb.europa.eu/service/data/YC/{SERIES_KEY.split('.',1)[1]}"
SOURCE_URL = f"https://data.ecb.europa.eu/data/datasets/YC/{SERIES_KEY}"

def parse_ecb_csv(payload: str) -> Dict[str, Any]:
    rows = list(csv.DictReader(io.StringIO(payload)))
    valid = []
    for row in rows:
        period = row.get("TIME_PERIOD") or row.get("TIME PERIOD")
        raw = row.get("OBS_VALUE") or row.get("OBS VALUE")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if period:
            valid.append((period, value))
    if not valid:
        raise ValueError("ECB response contains no dated observations")
    period, percent = max(valid, key=lambda item: item[0])
    return {
        "series_key": SERIES_KEY, "observation_date": period,
        "value": percent / 100, "raw_percent": percent,
        "unit": "percent_per_annum", "source": "ECB",
        "source_url": SOURCE_URL, "status": "observed",
    }

async def fetch_ecb_risk_free(start_period: Optional[str] = None) -> Dict[str, Any]:
    import httpx
    params = {"format": "csvdata"}
    if start_period:
        params["startPeriod"] = start_period
    async with httpx.AsyncClient(timeout=30, headers={"Accept": "text/csv"}) as client:
        response = await client.get(API_URL, params=params)
        response.raise_for_status()
    result = parse_ecb_csv(response.text)
    result["captured_at"] = datetime.now(timezone.utc).isoformat()
    return result

async def refresh_ecb_risk_free(db, start_period: Optional[str] = None) -> Dict[str, Any]:
    snapshot = await fetch_ecb_risk_free(start_period)
    await db.valuation_market_snapshots.create_index(
        [("series_key", 1), ("observation_date", 1)], unique=True)
    await db.valuation_market_snapshots.update_one(
        {"series_key": snapshot["series_key"],
         "observation_date": snapshot["observation_date"]},
        {"$setOnInsert": snapshot}, upsert=True)
    return snapshot
