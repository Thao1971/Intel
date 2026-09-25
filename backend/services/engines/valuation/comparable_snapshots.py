"""Auditable percentile snapshots for listed-company comparable multiples."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

SNAPSHOT_VERSION="public-comparable-snapshots-v1"
METRICS=("ev_ebitda","ev_ebit","ev_revenue","per","price_to_book")
BOUNDS={"ev_ebitda":(0,60),"ev_ebit":(0,80),"ev_revenue":(0,20),
        "per":(0,100),"price_to_book":(0,20)}


def percentile(values: List[float], probability: float) -> Optional[float]:
    if not values:return None
    ordered=sorted(values); position=(len(ordered)-1)*probability
    lower=int(position); upper=min(lower+1,len(ordered)-1); fraction=position-lower
    return ordered[lower]+(ordered[upper]-ordered[lower])*fraction


def _identifier(record: Mapping[str,Any]) -> str:
    return str(record.get("isin") or record.get("ticker") or record.get("name") or "unknown")


def build_comparable_snapshots(records: Iterable[Mapping[str,Any]], *, provider: str,
                               region: str, as_of: str,
                               minimum_sample: int = 3) -> Dict[str,Any]:
    groups=defaultdict(list)
    for record in records:
        groups[str(record.get("archetype") or "general_business")].append(record)
    snapshots=[]
    for archetype,group in sorted(groups.items()):
        metrics={}
        for metric in METRICS:
            included=[]; excluded=[]; low,high=BOUNDS[metric]
            for record in group:
                value=record.get(metric); identifier=_identifier(record)
                if value is None:
                    excluded.append({"identifier":identifier,"reason":"missing_metric"});continue
                try:value=float(value)
                except (TypeError,ValueError):
                    excluded.append({"identifier":identifier,"reason":"invalid_metric"});continue
                if not low<value<=high:
                    excluded.append({"identifier":identifier,"reason":"non_positive_or_outlier","value":value});continue
                included.append({"identifier":identifier,"name":record.get("name"),"value":value,
                                 "source_url":record.get("source_url")})
            values=[item["value"] for item in included]
            metrics[metric]={
                "p25":round(percentile(values,.25),4) if len(values)>=minimum_sample else None,
                "median":round(percentile(values,.5),4) if len(values)>=minimum_sample else None,
                "p75":round(percentile(values,.75),4) if len(values)>=minimum_sample else None,
                "sample_size":len(values),"minimum_sample":minimum_sample,
                "publishable":len(values)>=minimum_sample,
                "included":included,"excluded":excluded,
            }
        snapshots.append({
            "snapshot_version":SNAPSHOT_VERSION,"provider":provider,"region":region,
            "as_of":as_of,"archetype":archetype,"company_count":len(group),
            "metrics":metrics,"status":"observed_comparables",
            "generated_at":datetime.now(timezone.utc).isoformat(),"active":True,
        })
    return {"snapshot_version":SNAPSHOT_VERSION,"provider":provider,"region":region,
            "as_of":as_of,"record_count":sum(len(v) for v in groups.values()),
            "snapshot_count":len(snapshots),"snapshots":snapshots}
