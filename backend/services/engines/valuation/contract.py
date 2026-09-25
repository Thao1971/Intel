"""Canonical Intel -> Beta valuation delivery contract."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .conventions import equity_bridge

CONTRACT_VERSION = "intel-beta-valuation-v1"


def _unique(values: List[Any]) -> List[Any]:
    output = []
    for value in values:
        if value not in (None, "", [], {}) and value not in output:
            output.append(value)
    return output


def build_valuation_package(valuation: Mapping[str, Any], latest: Mapping[str, Any],
                            sector_rule: Optional[Mapping[str, Any]] = None,
                            generated_at: Optional[str] = None,
                            sector_positioning: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Create the sole presentation-ready valuation object consumed by Beta.

    The function only rearranges Intel results. It performs no new valuation.
    """
    reconciliation = valuation.get("reconciliation") or {}
    dcf = valuation.get("dcf") or {}
    rec_available = reconciliation.get("status") == "available"
    legacy_range = valuation.get("range") or {}
    ev_range = reconciliation.get("enterprise_value_range") if rec_available else (
        legacy_range if legacy_range.get("central") is not None else None)
    bridge = reconciliation.get("equity_bridge") or valuation.get("equity_bridge") or equity_bridge(latest)
    equity_range = reconciliation.get("equity_value_range") if rec_available else None

    methods_applied = list(reconciliation.get("methods_applied") or [])
    methods_excluded = list(reconciliation.get("methods_excluded") or [])
    if not reconciliation:
        methods_excluded = [{
            "method": "valuation", "label": "Valoración", "status": "excluded",
            "reason": "reconciliation_unavailable",
            "explanation": "No existe información suficiente para ejecutar la conciliación.",
        }]

    warnings = _unique(list(valuation.get("warnings") or []) +
                       list(dcf.get("warnings") or []) +
                       list(reconciliation.get("warnings") or []))
    hypotheses = list(valuation.get("hypotheses") or [])
    narratives = _unique([
        reconciliation.get("narrative"), valuation.get("methodology"), *hypotheses])
    public_benchmark = valuation.get("multiple_benchmark")
    private_adjustment = valuation.get("private_company_adjustment")
    operating_benchmark = valuation.get("benchmark")

    status = "available" if rec_available else "unavailable"
    central_ev = reconciliation.get("enterprise_value") if rec_available else valuation.get("enterprise_value")
    central_equity = reconciliation.get("equity_value") if rec_available else valuation.get("equity_value")
    return {
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "summary": {
            "currency": dcf.get("currency") or latest.get("currency") or "EUR",
            "as_of": dcf.get("as_of") or latest.get("year"),
            "enterprise_value": central_ev,
            "enterprise_value_range": ev_range,
            "equity_value": central_equity,
            "equity_value_range": equity_range,
            "equity_value_available": central_equity is not None,
        },
        "methods": {"applied": methods_applied, "excluded": methods_excluded},
        "scenarios": {
            "reconciled": ev_range,
            "dcf": dcf.get("scenarios") or {},
            "market_multiple": valuation.get("scenarios") or [],
        },
        "assumptions": {
            "dcf": dcf.get("assumptions") or {},
            "wacc": dcf.get("wacc_analysis"),
            "sector_rule": dict(sector_rule or dcf.get("sector_rule") or {}),
            "equity_bridge": bridge,
        },
        "comparables": {
            "public_market": {
                "method": valuation.get("method"), "multiple": valuation.get("multiple"),
                "basis": valuation.get("multiple_basis"), "benchmark": public_benchmark,
                "private_company_adjustment": private_adjustment,
            },
            "operating_peers": operating_benchmark,
            "private_transactions": next(
                (item for item in methods_excluded if item.get("method") == "private_transactions"),
                next((item for item in methods_applied if item.get("method") == "private_transactions"), None)),
        },
        "sensitivity": dcf.get("sensitivity") or [],
        "sector_positioning": dict(sector_positioning or {}),
        "confidence": {
            "score": reconciliation.get("confidence", valuation.get("confidence", 0.0)),
            "grade": reconciliation.get("decision_readiness", "screen_grade"),
            "weighting_rule": reconciliation.get("weighting_rule"),
            "method_count": len(methods_applied),
        },
        "warnings": warnings,
        "methodology_narrative": narratives,
        "sources_and_versions": {
            "financial_source": "Iberinform",
            "market_sources": _unique([
                (public_benchmark or {}).get("provider"),
                (public_benchmark or {}).get("source"),
                (public_benchmark or {}).get("source_level"),
            ] if public_benchmark else []),
            "private_transactions_source": "TTR" if any(
                item.get("method") == "private_transactions" and item.get("status") == "applied"
                for item in methods_applied) else None,
            "dcf_engine": dcf.get("engine_version"),
            "reconciliation_engine": reconciliation.get("engine_version"),
            "sector_ruleset": (sector_rule or {}).get("ruleset_version"),
            "financial_conventions": dcf.get("financial_conventions"),
            "generated_at": generated_at,
            "lineage": {"valuation": valuation.get("lineage"), "dcf": dcf.get("lineage")},
        },
    }
