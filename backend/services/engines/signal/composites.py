"""Composite Signals (D7) — signals built FROM already-detected signals.

Declarative & versioned. Each composite declares required component signal types
(and optional reinforcers). Composites REUSE base signals as evidence (component
signal_ids), keep full traceability/explainability, and derive their dimensions from
their components. Adding composites = extend this config, never touch the contract.
"""

from typing import Dict, List

COMPOSITES_VERSION = "comp-v1"

# requires = ALL must be present (passed) · optional = reinforce if present ·
# excludes = (optional key, additive within comp-v1) if ANY is present the composite does NOT fire
COMPOSITES = {
    "opportunity.consolidation_candidate": dict(
        requires=["growth.sustained", "financial.margin_strong", "ownership.consolidator"],
        optional=["transaction.ma_event"], severity="opportunity", polarity="positive",
        actions=["analyze", "compare", "contact", "add_to_watchlist"],
        description="Sustained growth + strong margins + holds investees -> consolidation actor."),
    "opportunity.hidden_gem": dict(
        requires=["financial.margin_strong", "growth.sustained", "market.outperforms_peers"],
        optional=["market.fragmented_sector"], severity="opportunity", polarity="positive",
        actions=["analyze", "contact", "add_to_watchlist"],
        description="Strong margins + sustained growth + outperforms peers -> undervalued gem."),
    "opportunity.potential_distress": dict(
        requires=["financial.net_loss", "financial.high_leverage"],
        optional=["risk.sustained_decline", "financial.low_liquidity", "corporate.group_change"],
        severity="risk", polarity="negative",
        actions=["investigate", "request_due_diligence", "consult_advisor"],
        description="Net loss + high leverage -> potential distress / turnaround target."),
    # Beta (2026-09): tesis adicionales, aditivas dentro de comp-v1 (ver `excludes`).
    "opportunity.operational_turnaround": dict(
        requires=["financial.margin_weak", "operational.productivity_low"],
        optional=["market.underperforms_peers"],
        excludes=["financial.net_loss", "financial.negative_equity"],
        severity="opportunity", polarity="neutral",
        actions=["analyze", "compare", "value", "add_to_watchlist"],
        description="Weak margin + low productivity, without net loss or negative equity -> operational-improvement target."),
    "opportunity.group_subsidiary": dict(
        requires=["ownership.group_member"],
        optional=["ownership.foreign_parent", "corporate.group_change"],
        severity="opportunity", polarity="neutral",
        actions=["analyze", "investigate", "add_to_watchlist"],
        description="Member of a corporate group -> possible carve-out / reorganisation target."),
    "opportunity.expansion_opportunity": dict(
        requires=["growth.revenue_surge", "operational.productivity_high"],
        optional=["growth.ebitda_expansion"], severity="opportunity", polarity="positive",
        actions=["analyze", "contact", "add_to_watchlist"],
        description="Revenue surge + high productivity -> expansion opportunity."),
}


def _agg_dims(components: List[Dict]) -> Dict:
    dims = [c["dimensions"] for c in components]
    return {
        "impact": round(max(d["impact"] for d in dims), 4),
        "confidence": round(min(d["confidence"] for d in dims), 4),
        "urgency": round(max(d["urgency"] for d in dims), 4),
        "persistence": round(sum(d["persistence"] for d in dims) / len(dims), 4),
    }


def build(base_signals: List[Dict]) -> List[Dict]:
    """Return composite signals derived from the detected base signals."""
    by_type = {s["signal_type"]: s for s in base_signals}
    out = []
    for ctype, spec in COMPOSITES.items():
        if not all(req in by_type for req in spec["requires"]):
            continue
        if any(x in by_type for x in spec.get("excludes", [])):
            continue
        components = [by_type[t] for t in spec["requires"]] + \
                     [by_type[t] for t in spec.get("optional", []) if t in by_type]
        dims = _agg_dims(components)
        comp_ids = [c["signal_id"] for c in components]
        comp_types = [c["signal_type"] for c in components]
        out.append({
            "signal_type": ctype, "category": "opportunity",
            "severity": spec["severity"], "polarity": spec["polarity"],
            "dimensions": dims, "confidence": dims["confidence"],
            "is_composite": True,
            "source": {"engine": "signal-intelligence-v1", "fields": comp_types,
                       "composites_version": COMPOSITES_VERSION},
            "evidence": {"components": comp_ids, "component_types": comp_types},
            "rule": {"id": ctype, "expression": "ALL(requires) present",
                     "requires": spec["requires"], "optional": spec.get("optional", []),
                     "excludes": spec.get("excludes", []),
                     "composites_version": COMPOSITES_VERSION, "passed": True},
            "recommended_actions": spec["actions"],
            "explanation": spec["description"] + " Evidencia: " + ", ".join(comp_types) + ".",
        })
    return out
