"""Versioned sector valuation policy.

Seed rules provide guarded screen-grade priors until the Iberinform calibration job
replaces them with observed Spanish cohort percentiles.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

RULESET_VERSION = "sector-valuation-seed-v1"
EFFECTIVE_FROM = "2026-09-20"

# p25 / median / p75 are policy seeds, not observed Iberinform statistics.
# Values are decimals. WACC and terminal growth remain market-sensitive inputs.
_ARCHETYPES = {
    "real_estate":       {"divisions": {"68"},       "wacc": (.085,.10,.12), "g": (.010,.015,.020), "growth": (-.02,.03,.08), "margin": (.08,.18,.35), "capex": (.01,.03,.07), "nwc": (.00,.08,.25)},
    "construction":      {"divisions": {"41","42","43"},"wacc": (.09,.11,.135),"g": (.010,.015,.020), "growth": (-.03,.03,.09), "margin": (.02,.06,.11), "capex": (.01,.025,.05),"nwc": (.08,.18,.35)},
    "media_content":     {"divisions": {"58","59","60"},"wacc": (.09,.105,.13),"g": (.010,.020,.025), "growth": (-.03,.025,.08),"margin": (.04,.11,.20), "capex": (.015,.04,.09),"nwc": (.03,.10,.20)},
    "advertising":       {"divisions": {"73"},       "wacc": (.095,.115,.14),"g": (.010,.020,.025), "growth": (-.02,.04,.10),"margin": (.04,.10,.18), "capex": (.005,.015,.035),"nwc": (.05,.12,.22)},
    "software_data":     {"divisions": {"62","63"},  "wacc": (.09,.11,.14), "g": (.015,.025,.030), "growth": (.00,.07,.16), "margin": (.05,.15,.28), "capex": (.01,.03,.07), "nwc": (-.05,.02,.10)},
    "professional_services":{"divisions":{"69","70","71","72","74"},"wacc":(.09,.11,.135),"g":(.010,.020,.025),"growth":(-.01,.04,.10),"margin":(.05,.12,.20),"capex":(.005,.02,.04),"nwc":(.03,.10,.20)},
    "industrial":        {"divisions": {str(x) for x in range(10,34)},"wacc":(.085,.105,.13),"g":(.010,.018,.025),"growth":(-.02,.035,.09),"margin":(.05,.11,.18),"capex":(.025,.055,.10),"nwc":(.10,.22,.38)},
    "wholesale":         {"divisions": {"46"},       "wacc": (.085,.105,.13),"g": (.010,.015,.020), "growth": (-.02,.03,.08), "margin": (.015,.04,.08), "capex": (.005,.015,.035),"nwc": (.10,.22,.38)},
    "retail":            {"divisions": {"47"},       "wacc": (.085,.105,.13),"g": (.010,.015,.020), "growth": (-.03,.025,.07),"margin": (.02,.06,.12), "capex": (.015,.035,.07),"nwc": (-.03,.04,.15)},
    "hospitality":       {"divisions": {"55","56"},  "wacc": (.09,.115,.145),"g": (.010,.020,.025), "growth": (-.04,.04,.11), "margin": (.04,.12,.22), "capex": (.025,.06,.12),"nwc": (-.05,.00,.06)},
    "transport_logistics":{"divisions":{"49","50","51","52","53"},"wacc":(.085,.105,.135),"g":(.010,.018,.025),"growth":(-.03,.035,.09),"margin":(.04,.10,.18),"capex":(.03,.07,.14),"nwc":(.00,.07,.18)},
    "energy_utilities":  {"divisions": {"35"},       "wacc": (.07,.085,.105),"g": (.010,.018,.025), "growth": (-.02,.03,.08), "margin": (.08,.18,.32), "capex": (.06,.13,.25),"nwc":(-.05,.02,.10)},
    "healthcare":        {"divisions": {"86","87","88"},"wacc":(.08,.10,.125),"g":(.010,.020,.025),"growth":(.00,.045,.10),"margin":(.05,.12,.22),"capex":(.015,.04,.08),"nwc":(.03,.10,.20)},
}
_GENERIC = {"wacc": (.09,.11,.14), "g": (.010,.018,.025), "growth": (-.03,.03,.09),
            "margin": (.03,.09,.18), "capex": (.01,.035,.08), "nwc": (.02,.12,.28)}

def size_band(revenue: Optional[float]) -> str:
    if revenue is None:
        return "unknown"
    if revenue < 2_000_000:
        return "micro"
    if revenue < 10_000_000:
        return "small"
    if revenue < 50_000_000:
        return "medium"
    return "large"

def _division(cnae_code: Any) -> Optional[str]:
    digits = "".join(ch for ch in str(cnae_code or "") if ch.isdigit())
    return digits[:2] if len(digits) >= 2 else None

def resolve_sector_rule(cnae_code: Any, revenue: Optional[float]) -> Dict[str, Any]:
    division = _division(cnae_code)
    archetype, raw = "general_business", _GENERIC
    for name, candidate in _ARCHETYPES.items():
        if division in candidate["divisions"]:
            archetype, raw = name, candidate
            break
    band = size_band(revenue)
    size_wacc_addon = {"micro": .025, "small": .015, "medium": .0075, "large": 0., "unknown": .015}[band]
    params = {}
    mapping = {"wacc": "wacc", "terminal_growth": "g", "revenue_growth": "growth",
               "ebit_margin": "margin", "capex_pct_revenue": "capex", "nwc_pct_revenue": "nwc"}
    for output_name, raw_name in mapping.items():
        p25, med, p75 = raw[raw_name]
        if output_name == "wacc":
            p25, med, p75 = p25 + size_wacc_addon, med + size_wacc_addon, p75 + size_wacc_addon
        params[output_name] = {"p25": p25, "median": med, "p75": p75}
    return {
        "ruleset_version": RULESET_VERSION, "effective_from": EFFECTIVE_FROM,
        "archetype": archetype, "cnae_division": division, "size_band": band,
        "calibration_status": "provisional_policy_seed",
        "decision_readiness": "screen_grade",
        "parameters": params,
        "lineage": {
            "classification_source": "Iberinform/CNAE",
            "calibration_source": "Arroba policy seed; pending Iberinform cohort calibration",
            "sample_size": None,
        },
    }
