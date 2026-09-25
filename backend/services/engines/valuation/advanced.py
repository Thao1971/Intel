"""Advanced valuation orchestration.

Intel remains the sole calculator. Beta sends reviewed evidence and assumptions;
this module applies them to the canonical series, reruns DCF and reconciliation,
and returns the normal Intel -> Beta valuation package.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional

from .contract import build_valuation_package
from .conventions import equity_bridge
from .dcf import calculate_dcf
from .reconciliation import reconcile_valuation

ADVANCED_ENGINE_VERSION = "arroba-advanced-valuation-v1"


def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        parsed = float(value)
        return parsed if parsed == parsed else default
    except (TypeError, ValueError):
        return default


def _series(profile: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for statement in profile.get("statements_history") or []:
        row = {"year": statement.get("year"), "basis": statement.get("basis")}
        row.update(statement.get("income_statement") or {})
        row.update(statement.get("balance_sheet") or {})
        row.update(statement.get("cashflow") or {})
        if row.get("operating_income") is None:
            row["operating_income"] = row.get("ebit")
        rows.append(row)
    return rows


def _apply_financial_overrides(series: List[Dict[str, Any]], overrides: Mapping[str, Any]) -> None:
    by_year = {str(row.get("year")): row for row in series}
    for path, raw in overrides.items():
        parts = str(path).split(".")
        if len(parts) != 3 or parts[0] not in by_year:
            continue
        key = parts[2]
        value = _number(raw)
        if value is None:
            continue
        by_year[parts[0]][key] = value
        if key == "ebit":
            by_year[parts[0]]["operating_income"] = value


def _apply_ebitda_bridge(series: List[Dict[str, Any]], adjustments: List[Mapping[str, Any]]) -> Dict[str, Any]:
    latest = series[0]
    reported = _number(latest.get("ebitda"), 0) or 0
    total = 0.0
    accepted = []
    for item in adjustments:
        amount = _number(item.get("amount"))
        concept = str(item.get("concept") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        if not concept or amount is None or amount < 0:
            continue
        signed = amount if item.get("direction") == "add" else -amount
        total += signed
        accepted.append({"concept": concept, "amount": amount, "signed_amount": signed,
                         "direction": item.get("direction"), "recurring": item.get("recurring"),
                         "evidence": evidence or None})
    latest["ebitda"] = reported + total
    if latest.get("operating_income") is not None:
        latest["operating_income"] = float(latest["operating_income"]) + total
        latest["ebit"] = latest["operating_income"]
    return {"reported_ebitda": reported, "adjustments": accepted,
            "net_adjustment": total, "normalized_ebitda": latest["ebitda"]}


def _wacc_from_inputs(values: Mapping[str, Any]) -> Dict[str, Any]:
    risk_free = (_number(values.get("risk_free_rate"), .034875) or 0)
    equity_premium = (_number(values.get("equity_risk_premium"), .0423) or 0)
    country = (_number(values.get("country_risk_premium"), .0155) or 0)
    unlevered = (_number(values.get("unlevered_beta"), 1.0) or 1.0)
    size = (_number(values.get("size_premium"), 0) or 0)
    debt_weight = max(0.0, min(.80, _number(values.get("debt_weight"), .25) or 0))
    equity_weight = 1 - debt_weight
    tax = max(0.0, min(.60, _number(values.get("tax_rate"), .25) or 0))
    pre_tax_debt = max(0.0, _number(values.get("pre_tax_cost_of_debt"), .06) or 0)
    debt_to_equity = debt_weight / equity_weight if equity_weight else 0
    levered = unlevered * (1 + (1 - tax) * debt_to_equity)
    cost_of_equity = risk_free + levered * equity_premium + country + size
    after_tax_debt = pre_tax_debt * (1 - tax)
    wacc = cost_of_equity * equity_weight + after_tax_debt * debt_weight
    return {"status": "available", "engine_version": "arroba-wacc-v1",
            "decision_readiness": "user_reviewed", "wacc": round(wacc, 6),
            "components": {"risk_free_rate": {"value": risk_free, "source": "user_reviewed"},
                "equity_risk_premium": {"value": equity_premium, "source": "user_reviewed"},
                "country_risk_premium": {"value": country, "source": "user_reviewed"},
                "unlevered_beta": {"value": unlevered, "source": "user_reviewed"},
                "levered_beta": {"value": levered}, "size_premium": {"value": size},
                "cost_of_equity": {"value": cost_of_equity},
                "pre_tax_cost_of_debt": {"value": pre_tax_debt},
                "after_tax_cost_of_debt": {"value": after_tax_debt},
                "tax_rate": {"value": tax},
                "target_capital_structure": {"debt_weight": debt_weight,
                                               "equity_weight": equity_weight,
                                               "source": "user_reviewed"}},
            "warnings": [], "lineage": {"source": "advanced_valuation_input"}}


def _refresh_market_method(valuation: Dict[str, Any], latest: Mapping[str, Any]) -> None:
    """Reapply the canonical market multiple to the user-reviewed financials."""
    method = valuation.get("method")
    multiple = _number(valuation.get("multiple"))
    if multiple is None or multiple <= 0:
        return
    if method == "ev_ebitda":
        metric, low_factor, high_factor = _number(latest.get("ebitda")), .85, 1.15
    elif method == "ev_revenue":
        metric, low_factor, high_factor = _number(latest.get("revenue")), .70, 1.30
    else:
        return
    if metric is None or metric <= 0:
        return
    previous_range = valuation.get("range") or {}
    previous_central = _number(previous_range.get("central"))
    previous_low = _number(previous_range.get("low"))
    previous_high = _number(previous_range.get("high"))
    if previous_central and previous_central > 0:
        if previous_low is not None and previous_low >= 0:
            low_factor = previous_low / previous_central
        if previous_high is not None and previous_high >= 0:
            high_factor = previous_high / previous_central
    enterprise_value = metric * multiple
    valuation["enterprise_value"] = round(enterprise_value, 2)
    valuation["equity_value"] = equity_bridge(latest, enterprise_value)["equity_value"]
    valuation["range"] = {
        "low": round(enterprise_value * low_factor, 2),
        "central": round(enterprise_value, 2),
        "high": round(enterprise_value * high_factor, 2),
    }


def calculate_advanced(profile: Mapping[str, Any], payload: Mapping[str, Any], generated_at: str) -> Dict[str, Any]:
    series = _series(profile)
    if not series:
        raise ValueError("financial_statements_required")
    _apply_financial_overrides(series, payload.get("financial_overrides") or {})
    bridge = payload.get("equity_bridge") or {}
    for key in ("financial_debt", "cash"):
        value = _number(bridge.get(key))
        if value is not None:
            series[0][key] = value
    ebitda_bridge = _apply_ebitda_bridge(series, payload.get("ebitda_adjustments") or [])

    assumptions = dict(payload.get("projection_assumptions") or {})
    wacc_analysis = _wacc_from_inputs(payload.get("wacc_inputs") or {})
    assumptions["wacc"] = wacc_analysis["wacc"]
    base_valuation = deepcopy(profile.get("valuation") or {})
    _refresh_market_method(base_valuation, series[0])
    sector_rule = ((base_valuation.get("package") or {}).get("assumptions") or {}).get("sector_rule") or {}
    base_valuation["dcf"] = calculate_dcf(
        series, assumptions=assumptions, sector_rule=sector_rule,
        wacc_analysis=wacc_analysis)
    base_valuation["reconciliation"] = reconcile_valuation(
        base_valuation, series[0], sector_rule=sector_rule,
        private_transactions=payload.get("private_transactions"),
        user_weights=payload.get("method_weights"))
    base_valuation["package"] = build_valuation_package(
        base_valuation, series[0], sector_rule=sector_rule, generated_at=generated_at,
        sector_positioning=(base_valuation.get("package") or {}).get("sector_positioning"))
    base_valuation["advanced_inputs"] = {
        "objective": payload.get("objective"), "valuation_date": payload.get("valuation_date"),
        "perimeter": payload.get("perimeter"), "ebitda_bridge": ebitda_bridge,
        "quality_context": payload.get("quality_context") or {},
        "projection_assumptions": assumptions, "wacc": wacc_analysis,
        "method_weights": payload.get("method_weights") or {},
    }
    return {**deepcopy(profile), "valuation": base_valuation,
            "engine_version": ADVANCED_ENGINE_VERSION, "generated_at": generated_at}
