"""Resolve latest observed ECB, comparable and regional benchmark inputs."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any, Dict, Optional
from .sector_benchmarks import load_sector_benchmark, select_benchmark
from .comparable_snapshots import build_comparable_snapshots
from .wacc import MARKET_SNAPSHOT, beta_from_comparables


@lru_cache(maxsize=1)
def _bundled_sector_records():
    repo_root=Path(__file__).resolve().parents[4]
    folder=repo_root/"data"/"valuation"/"market"/"damodaran"
    files=[
        (folder/"Multiplos_Europa_Ampliado_2025.xlsx","europe"),
        (folder/"Multiplos_EEUU_Ampliado_2025.xlsx","united_states"),
    ]
    records=[]
    for path,region in files:
        if path.exists():
            records.extend(load_sector_benchmark(path,region,"2026-01-05")["records"])
    return records

async def resolve_market_inputs(db, archetype: str):
    market={key:(dict(value) if isinstance(value,dict) else value)
            for key,value in MARKET_SNAPSHOT.items()}
    ecb=await db.valuation_market_snapshots.find_one(
        {"series_key":"YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"},
        {"_id":0},sort=[("observation_date",-1)])
    if ecb:
        market["as_of"]=ecb["observation_date"]
        market["risk_free_rate"]={"value":ecb["value"],"source":"ECB",
                                  "status":"observed","series_key":ecb["series_key"],
                                  "observation_date":ecb["observation_date"],
                                  "source_url":ecb.get("source_url")}
    for series_key,field in (("ERP.MATURE_MARKET","equity_risk_premium"),
                             ("CRP.ESP","country_risk_premium")):
        snapshot=await db.valuation_market_snapshots.find_one(
            {"series_key":series_key},{"_id":0},sort=[("observation_date",-1)])
        if snapshot:
            market[field]={"value":snapshot["value"],"source":snapshot["source"],
                           "status":snapshot.get("status","external_reference"),
                           "series_key":series_key,
                           "observation_date":snapshot["observation_date"],
                           "source_url":snapshot.get("source_url")}
    peers=await db.valuation_public_comparables.find(
        {"archetype":archetype,"active":True,"quality.beta_ready":True},{"_id":0}).to_list(500)
    return market,beta_from_comparables(peers),peers

async def resolve_valuation_multiple(db, archetype: str, metric: str) -> Optional[Dict[str,Any]]:
    """Resolve observed multiples in Arroba priority order.

    Spanish company observations precede Europe, then the United States.
    Private transactions remain a separate, higher-priority source in the caller.
    """
    if metric not in {"ev_ebitda","ev_ebit","ev_revenue","per","price_to_book"}:
        raise ValueError(f"Unsupported valuation metric: {metric}")
    snapshot=await db.valuation_public_comparable_snapshots.find_one(
        {"provider":"marketscreener","region":"spain","archetype":archetype,
         "active":True,f"metrics.{metric}.publishable":True},{"_id":0},
        sort=[("as_of",-1)])
    if snapshot:
        stats=snapshot["metrics"][metric]
        return {"metric":metric,"multiple":stats["median"],"p25":stats["p25"],
                "median":stats["median"],"p75":stats["p75"],
                "sample_size":stats["sample_size"],"source_level":"spanish_listed_companies",
                "provider":"marketscreener","status":"observed_comparables",
                "as_of":snapshot["as_of"],"archetype":archetype,
                "included":stats.get("included",[]),"excluded":stats.get("excluded",[]),
                "snapshot_version":snapshot.get("snapshot_version")}
    spanish=await db.valuation_public_comparables.find(
        {"provider":"marketscreener","archetype":archetype,"active":True,
         f"{metric}":{"$gt":0}},{"_id":0}).to_list(500)
    if spanish:
        as_of=max(str(r.get("as_of") or "") for r in spanish)
        built=build_comparable_snapshots(
            spanish,provider="marketscreener",region="spain",as_of=as_of)
        item=next((row for row in built["snapshots"] if row["archetype"]==archetype),None)
        stats=((item or {}).get("metrics") or {}).get(metric) or {}
        if stats.get("publishable"):
            return {"metric":metric,"multiple":stats["median"],"p25":stats["p25"],
                    "median":stats["median"],"p75":stats["p75"],
                    "sample_size":stats["sample_size"],
                    "source_level":"spanish_listed_companies","provider":"marketscreener",
                    "status":"observed_comparables","as_of":as_of,"archetype":archetype,
                    "included":stats["included"],"excluded":stats["excluded"],
                    "snapshot_version":built["snapshot_version"]}
    regional=await db.valuation_sector_benchmarks.find(
        {"archetype":archetype,"active":True,
         f"metrics.{metric}":{"$gt":0}},{"_id":0}).to_list(500)
    if not regional:
        regional=[record for record in _bundled_sector_records()
                  if record.get("archetype")==archetype
                  and (record.get("metrics") or {}).get(metric)]
    for region in ("europe","united_states"):
        selected=select_benchmark(
            [record for record in regional if record.get("region")==region],
            archetype,metric)
        if selected:
            return {**selected,"source_level":"regional_sector_benchmark",
                    "preferred_region":region,"archetype":archetype}
    return None
