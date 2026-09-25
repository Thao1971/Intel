"""Resolve reviewed Iberinform cohort rules with explicit seed fallback."""
from __future__ import annotations
from typing import Any, Dict, Optional

from .sector_rules import resolve_sector_rule

CALIBRATED_PARAMETERS = (
    "revenue_growth", "ebit_margin", "depreciation_pct_revenue",
    "capex_pct_revenue", "nwc_pct_revenue",
)


async def resolve_calibrated_sector_rule(database, cnae_code: Any,
                                         revenue: Optional[float]) -> Dict[str, Any]:
    base = resolve_sector_rule(cnae_code, revenue)
    division, archetype, band = (base["cnae_division"], base["archetype"],
                                 base["size_band"])
    keys = []
    if division:
        keys.extend((f"division:{division}|size:{band}",
                     f"division:{division}|size:all"))
    keys.extend((f"archetype:{archetype}|size:{band}",
                 f"archetype:{archetype}|size:all"))
    rows = await database.valuation_sector_rules.find(
        {"active": True, "cohort_key": {"$in": keys}}, {"_id": 0}).to_list(20)
    by_key = {row["cohort_key"]: row for row in rows}
    parameters = {key: dict(value) for key, value in base["parameters"].items()}
    calibrated, sources = [], {}
    for parameter in CALIBRATED_PARAMETERS:
        for key in keys:
            row = by_key.get(key)
            stats = ((row or {}).get("parameters") or {}).get(parameter) or {}
            if all(stats.get(q) is not None for q in ("p25", "median", "p75")):
                parameters[parameter] = {
                    "p25": float(stats["p25"]), "median": float(stats["median"]),
                    "p75": float(stats["p75"]), "source": "calibrated_iberinform",
                    "sample_size": stats.get("sample_size"),
                    "cohort_key": key, "ruleset_version": row.get("ruleset_version"),
                }
                calibrated.append(parameter)
                sources[parameter] = key
                break
    if not calibrated:
        return base
    versions = sorted({row.get("ruleset_version") for row in rows if row.get("ruleset_version")})
    return {
        **base,
        "ruleset_version": versions[-1] if versions else base["ruleset_version"],
        "effective_from": max((str(row.get("effective_from") or "") for row in rows),
                              default=base["effective_from"]),
        "calibration_status": ("calibrated_iberinform" if len(calibrated) == len(CALIBRATED_PARAMETERS)
                               else "calibrated_iberinform_partial"),
        "decision_readiness": "review_ready",
        "parameters": parameters,
        "lineage": {
            **base["lineage"], "calibration_source": "Iberinform reviewed cohort snapshot",
            "calibrated_parameters": calibrated, "parameter_cohorts": sources,
            "fallback_parameters": [key for key in parameters if key not in calibrated],
        },
    }
