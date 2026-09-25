"""Transparent policy for adjusting listed-company multiples to private companies."""
from __future__ import annotations
import unicodedata
from typing import Any, Dict, Mapping, Optional

ADJUSTMENT_VERSION = "private-company-adjustments-v1"
SIZE_ADJUSTMENT = {"micro": -.15, "small": -.10, "medium": -.05, "large": 0., "unknown": 0.}
MAX_DISCOUNT = -.35
MAX_PREMIUM = .25

def _observed_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value,bool) else None

def _observed_float(value: Any) -> Optional[float]:
    if isinstance(value,bool) or value is None:
        return None
    try: return float(value)
    except (TypeError,ValueError): return None

def _normalized_text(value: Any) -> str:
    text=unicodedata.normalize("NFKD",str(value or "")).encode("ascii","ignore").decode()
    return text.strip().lower()

def _reported_bool(value: Any) -> Optional[bool]:
    if isinstance(value,bool):
        return value
    text=_normalized_text(value)
    if text in {"si","s","yes","y","true","1","auditado","audited"}:
        return True
    if text in {"no","n","false","0","no auditado","not audited"}:
        return False
    return None

def extract_private_company_evidence(master: Mapping[str,Any],
                                     latest: Optional[Mapping[str,Any]] = None) -> Dict[str,Any]:
    """Read only explicit adjustment evidence; never infer qualitative facts."""
    registry=master.get("registry") if isinstance(master.get("registry"),Mapping) else {}
    valuation_inputs=(master.get("valuation_inputs")
                      if isinstance(master.get("valuation_inputs"),Mapping) else {})
    commercial=(master.get("commercial_profile")
                if isinstance(master.get("commercial_profile"),Mapping) else {})
    stored_evidence=(master.get("valuation_inputs_evidence")
                     if isinstance(master.get("valuation_inputs_evidence"),Mapping) else {})
    values: Dict[str,Any]={}
    lineage: Dict[str,Dict[str,str]]={}
    audited_raw=registry.get("audited",master.get("audited"))
    audited=_reported_bool(audited_raw)
    if audited is not None:
        values["audited_accounts"]=audited
        lineage["audited_accounts"]={"source":"Iberinform","path":"master.registry.audited","status":"observed"}
    for field in ("recurring_revenue_pct","largest_customer_pct","key_person_dependency"):
        if field in valuation_inputs:
            raw=valuation_inputs[field]; path=f"master.valuation_inputs.{field}"
        elif field in commercial:
            raw=commercial[field]; path=f"master.commercial_profile.{field}"
        else:
            continue
        parsed=(_reported_bool(raw) if field=="key_person_dependency" else _observed_float(raw))
        if parsed is not None:
            values[field]=parsed
            metadata=stored_evidence.get(field) if isinstance(stored_evidence.get(field),Mapping) else {}
            lineage[field]={"source":metadata.get("source_type","due_diligence"),
                            "path":path,"status":"observed"}
            for key in ("source_reference","observed_at"):
                if metadata.get(key):
                    lineage[field][key]=metadata[key]
    expected=("recurring_revenue_pct","largest_customer_pct","key_person_dependency","audited_accounts")
    return {"values":values,"lineage":lineage,
            "unavailable":[field for field in expected if field not in values]}

def adjust_public_multiple(public_multiple: float, size_band: str,
                           evidence: Optional[Mapping[str,Any]] = None) -> Dict[str,Any]:
    """Apply only evidence-supported EV multiple adjustments.

    Liquidity/DLOM is excluded: it belongs to minority equity valuation, not EV.
    Unknown qualitative inputs remain neutral and are disclosed as unavailable.
    """
    if public_multiple <= 0:
        raise ValueError("public_multiple must be positive")
    evidence=dict(evidence or {})
    components=[{"factor":"size","adjustment":SIZE_ADJUSTMENT.get(size_band,0.),
                 "status":"policy","basis":size_band}]
    unavailable=[]
    recurring=_observed_float(evidence.get("recurring_revenue_pct"))
    if recurring is None:
        unavailable.append("recurring_revenue_pct")
    elif recurring >= .75:
        components.append({"factor":"recurring_revenue","adjustment":.05,"status":"observed","basis":recurring})
    elif recurring < .25:
        components.append({"factor":"recurring_revenue","adjustment":-.05,"status":"observed","basis":recurring})
    concentration=_observed_float(evidence.get("largest_customer_pct"))
    if concentration is None:
        unavailable.append("largest_customer_pct")
    elif concentration >= .40:
        components.append({"factor":"customer_concentration","adjustment":-.10,"status":"observed","basis":concentration})
    elif concentration >= .25:
        components.append({"factor":"customer_concentration","adjustment":-.05,"status":"observed","basis":concentration})
    key_person=_observed_bool(evidence.get("key_person_dependency"))
    if key_person is None:
        unavailable.append("key_person_dependency")
    elif key_person:
        components.append({"factor":"key_person_dependency","adjustment":-.05,"status":"observed","basis":True})
    audited=_observed_bool(evidence.get("audited_accounts"))
    if audited is None:
        unavailable.append("audited_accounts")
    elif audited:
        components.append({"factor":"audited_accounts","adjustment":.025,"status":"observed","basis":True})
    raw=sum(item["adjustment"] for item in components)
    total=max(MAX_DISCOUNT,min(MAX_PREMIUM,raw))
    return {
        "adjustment_version":ADJUSTMENT_VERSION,
        "public_multiple":public_multiple,
        "total_adjustment":total,
        "adjusted_multiple":round(public_multiple*(1+total),4),
        "components":components,
        "unavailable_evidence":unavailable,
        "caps":{"maximum_discount":MAX_DISCOUNT,"maximum_premium":MAX_PREMIUM},
        "liquidity_discount_applied":False,
        "liquidity_note":"DLOM is reserved for minority equity interests and is not applied to enterprise value.",
        "decision_readiness":"screen_grade" if unavailable else "review_ready",
    }
