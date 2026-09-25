"""Deterministic discounted cash-flow valuation for the Intel engine layer."""
from __future__ import annotations
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .conventions import equity_bridge, working_capital_value

ENGINE_VERSION = "arroba-dcf-v1"
DEFAULTS = {"projection_years": 5, "tax_rate": .25, "wacc": .10, "terminal_growth": .02,
            "revenue_growth": .02, "ebit_margin": .08, "depreciation_pct_revenue": .02,
            "capex_pct_revenue": .02, "nwc_pct_revenue": .05}

def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None

def _values(series: Iterable[Mapping[str, Any]], key: str) -> List[float]:
    return [number for row in series if (number := _number(row.get(key))) is not None]

def _ratio_median(series: Iterable[Mapping[str, Any]], numerator: str, denominator: str) -> Optional[float]:
    ratios = []
    for row in series:
        num, den = _number(row.get(numerator)), _number(row.get(denominator))
        if num is not None and den and den > 0:
            ratios.append(num / den)
    return median(ratios) if ratios else None

def _absolute_ratio(series: Iterable[Mapping[str, Any]], field: str) -> Optional[float]:
    ratios = []
    for row in series:
        capex, revenue = _number(row.get(field)), _number(row.get("revenue"))
        if capex is not None and revenue and revenue > 0:
            ratios.append(abs(capex) / revenue)
    return median(ratios) if ratios else None

def _nwc_ratio(series: Iterable[Mapping[str, Any]]) -> Optional[float]:
    ratios = []
    for row in series:
        revenue = _number(row.get("revenue"))
        nwc = working_capital_value(row)["value"]
        if nwc is not None and revenue and revenue > 0:
            ratios.append(nwc / revenue)
    return median(ratios) if ratios else None

def _historical_growth(series: List[Mapping[str, Any]]) -> Optional[float]:
    revenues = [value for value in _values(reversed(series), "revenue") if value > 0]
    if len(revenues) < 2:
        return None
    return (revenues[-1] / revenues[0]) ** (1 / (len(revenues) - 1)) - 1

def _assumption(name: str, supplied: Mapping[str, Any], historical: Optional[float], default: float) -> Dict[str, Any]:
    if _number(supplied.get(name)) is not None:
        return {"value": float(supplied[name]), "source": "user_supplied"}
    if historical is not None:
        return {"value": float(historical), "source": "iberinform_historical"}
    return {"value": default, "source": "arroba_default"}

def _sectorized_assumption(name: str, supplied: Mapping[str, Any], historical: Optional[float],
                           default: float, sector_rule: Optional[Mapping[str, Any]],
                           company_weight: float = .70) -> Dict[str, Any]:
    if _number(supplied.get(name)) is not None:
        return {"value": float(supplied[name]), "source": "user_supplied"}
    sector = ((sector_rule or {}).get("parameters") or {}).get(name)
    if sector:
        sector_median = float(sector["median"])
        if historical is not None:
            blended = historical * company_weight + sector_median * (1 - company_weight)
            value = max(float(sector["p25"]), min(float(sector["p75"]), blended))
            return {"value": value, "source": "iberinform_historical_sector_blend",
                    "company_value": historical, "sector_median": sector_median,
                    "company_weight": company_weight, "sector_band": [sector["p25"], sector["p75"]]}
        return {"value": sector_median, "source": "sector_policy_seed",
                "sector_median": sector_median, "sector_band": [sector["p25"], sector["p75"]]}
    return _assumption(name, supplied, historical, default)

def _wacc_assumption(supplied: Mapping[str, Any],
                     wacc_analysis: Optional[Mapping[str, Any]],
                     sector_rule: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if _number(supplied.get("wacc")) is not None:
        return {"value": float(supplied["wacc"]), "source": "user_supplied"}
    engine_value = _number((wacc_analysis or {}).get("wacc"))
    if engine_value is not None:
        return {"value": engine_value, "source": "arroba_wacc_engine",
                "engine_version": wacc_analysis.get("engine_version"),
                "decision_readiness": wacc_analysis.get("decision_readiness"),
                "as_of": wacc_analysis.get("as_of")}
    return _sectorized_assumption("wacc", supplied, None, DEFAULTS["wacc"], sector_rule)

def _enterprise_value(revenue: float, a: Mapping[str, float]) -> Dict[str, Any]:
    years, previous, pv_sum, projections = int(a["projection_years"]), revenue, 0.0, []
    for year in range(1, years + 1):
        projected = previous * (1 + a["revenue_growth"])
        ebit = projected * a["ebit_margin"]
        depreciation = projected * a["depreciation_pct_revenue"]
        capex = projected * a["capex_pct_revenue"]
        delta_nwc = (projected - previous) * a["nwc_pct_revenue"]
        fcff = ebit * (1 - a["tax_rate"]) + depreciation - capex - delta_nwc
        pv_fcff = fcff / ((1 + a["wacc"]) ** year)
        pv_sum += pv_fcff
        projections.append({"year": year, "revenue": round(projected, 2), "ebit": round(ebit, 2),
                            "fcff": round(fcff, 2), "present_value": round(pv_fcff, 2)})
        previous = projected
    terminal_fcff = projections[-1]["fcff"] * (1 + a["terminal_growth"])
    terminal_value = terminal_fcff / (a["wacc"] - a["terminal_growth"])
    pv_terminal = terminal_value / ((1 + a["wacc"]) ** years)
    return {"enterprise_value": round(pv_sum + pv_terminal, 2), "pv_explicit_period": round(pv_sum, 2),
            "terminal_value": round(terminal_value, 2), "pv_terminal_value": round(pv_terminal, 2),
            "projections": projections}

def calculate_dcf(series: List[Mapping[str, Any]], assumptions: Optional[Mapping[str, Any]] = None,
                  sector_rule: Optional[Mapping[str, Any]] = None,
                  wacc_analysis: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Return an auditable FCFF DCF from a newest-first canonical series."""
    supplied, latest = assumptions or {}, series[0] if series else {}
    revenue = _number(latest.get("revenue"))
    if revenue is None or revenue <= 0:
        return {"status": "unavailable", "engine_version": ENGINE_VERSION, "reason": "positive_revenue_required"}
    derived = {
        "projection_years": _assumption("projection_years", supplied, None, DEFAULTS["projection_years"]),
        "tax_rate": _assumption("tax_rate", supplied, None, DEFAULTS["tax_rate"]),
        "wacc": _wacc_assumption(supplied, wacc_analysis, sector_rule),
        "terminal_growth": _sectorized_assumption("terminal_growth", supplied, None, DEFAULTS["terminal_growth"], sector_rule),
        "revenue_growth": _sectorized_assumption("revenue_growth", supplied, _historical_growth(series), DEFAULTS["revenue_growth"], sector_rule),
        "ebit_margin": _sectorized_assumption("ebit_margin", supplied, _ratio_median(series, "operating_income", "revenue"), DEFAULTS["ebit_margin"], sector_rule),
        "depreciation_pct_revenue": _sectorized_assumption("depreciation_pct_revenue", supplied, _absolute_ratio(series, "depreciation"), DEFAULTS["depreciation_pct_revenue"], sector_rule),
        "capex_pct_revenue": _sectorized_assumption("capex_pct_revenue", supplied, _absolute_ratio(series, "cf_capex"), DEFAULTS["capex_pct_revenue"], sector_rule),
        "nwc_pct_revenue": _sectorized_assumption("nwc_pct_revenue", supplied, _nwc_ratio(series), DEFAULTS["nwc_pct_revenue"], sector_rule),
    }
    values = {key: item["value"] for key, item in derived.items()}
    values["projection_years"] = int(values["projection_years"])
    values["revenue_growth"] = max(-.10, min(.25, values["revenue_growth"]))
    values["ebit_margin"] = max(-.25, min(.60, values["ebit_margin"]))
    if values["projection_years"] < 1 or values["wacc"] <= values["terminal_growth"]:
        return {"status": "unavailable", "engine_version": ENGINE_VERSION,
                "reason": "invalid_dcf_assumptions", "assumptions": derived}
    cases = {
        "conservative": {**values, "revenue_growth": values["revenue_growth"] - .02,
                         "ebit_margin": values["ebit_margin"] - .02, "wacc": values["wacc"] + .02,
                         "terminal_growth": max(0., values["terminal_growth"] - .01)},
        "base": values,
        "optimistic": {**values, "revenue_growth": values["revenue_growth"] + .02,
                       "ebit_margin": values["ebit_margin"] + .02, "wacc": values["wacc"] - .01,
                       "terminal_growth": values["terminal_growth"] + .005},
    }
    scenarios = {name: _enterprise_value(revenue, case) for name, case in cases.items()}
    warnings = []
    bridges = {}
    for name, result in scenarios.items():
        bridge = equity_bridge(latest, result["enterprise_value"])
        result["equity_value"] = bridge["equity_value"]
        result["equity_bridge"] = bridge
        bridges[name] = bridge
        for warning in bridge["warnings"]:
            if warning not in warnings:
                warnings.append(warning)
    sensitivity = []
    for wacc in [values["wacc"] - .01, values["wacc"], values["wacc"] + .01]:
        cells = []
        for growth in [values["terminal_growth"] - .005, values["terminal_growth"], values["terminal_growth"] + .005]:
            ev = None if wacc <= growth else _enterprise_value(revenue, {**values, "wacc": wacc, "terminal_growth": growth})["enterprise_value"]
            cells.append({"terminal_growth": round(growth, 4), "enterprise_value": ev})
        sensitivity.append({"wacc": round(wacc, 4), "values": cells})
    defaults_used = sum(item["source"] == "arroba_default" for item in derived.values())
    provisional_penalty = .10 if (sector_rule or {}).get("calibration_status") == "provisional_policy_seed" else 0
    wacc_penalty = .05 if (wacc_analysis or {}).get("decision_readiness") == "screen_grade" else 0
    confidence = max(.2, .9 - defaults_used * .08 - (.12 if not bridges["base"]["net_debt_known"] else 0) - (.08 if len(series) < 3 else 0) - provisional_penalty - wacc_penalty)
    return {"status": "available", "engine_version": ENGINE_VERSION, "method": "FCFF_Gordon_growth",
            "currency": latest.get("currency") or "EUR", "as_of": latest.get("year"),
            "assumptions": derived, "scenarios": scenarios, "sensitivity": sensitivity,
            "confidence": round(confidence, 2), "warnings": warnings,
            "equity_bridge": bridges["base"],
            "financial_conventions": bridges["base"]["conventions_version"],
            "wacc_analysis": dict(wacc_analysis) if wacc_analysis else None,
            "sector_rule": dict(sector_rule) if sector_rule else None,
            "decision_readiness": (sector_rule or {}).get("decision_readiness", "screen_grade"),
            "lineage": {"financial_source": "Iberinform", "calculation_engine": "Intel",
                        "input_years": [row.get("year") for row in series if row.get("year") is not None]}}
