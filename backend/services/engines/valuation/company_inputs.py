"""Durable, audited capture of private-company valuation evidence."""
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional

from models import new_id, now_iso

INPUT_VERSION = "valuation-company-inputs-v1"
ALLOWED_FIELDS = {
    "recurring_revenue_pct",
    "largest_customer_pct",
    "key_person_dependency",
}


def normalize_patch(values: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the engine contract independently from the HTTP layer."""
    unknown = set(values) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"unsupported valuation inputs: {', '.join(sorted(unknown))}")
    out: Dict[str, Any] = {}
    for field, value in values.items():
        if value is None:
            out[field] = None
            continue
        if field == "key_person_dependency":
            if not isinstance(value, bool):
                raise ValueError("key_person_dependency must be boolean")
            out[field] = value
            continue
        if isinstance(value, bool):
            raise ValueError(f"{field} must be a number between 0 and 1")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a number between 0 and 1") from exc
        if not 0 <= number <= 1:
            raise ValueError(f"{field} must be between 0 and 1")
        out[field] = number
    if not out:
        raise ValueError("at least one valuation input is required")
    return out


async def get_company_inputs(database, identifier: str) -> Optional[Dict[str, Any]]:
    master = await database.master_companies.find_one(
        {"$or": [{"master_id": identifier}, {"cif_normalized": identifier}]},
        {"_id": 0, "master_id": 1, "cif_normalized": 1, "valuation_inputs": 1,
         "valuation_inputs_meta": 1},
    )
    if not master:
        return None
    stored = await database.valuation_company_inputs.find_one(
        {"master_id": master["master_id"]}, {"_id": 0})
    values = (stored or {}).get("values") or master.get("valuation_inputs") or {}
    evidence = (stored or {}).get("evidence") or {}
    return {
        "master_id": master["master_id"],
        "cif_normalized": master.get("cif_normalized"),
        "values": values,
        "evidence": evidence,
        "input_version": (stored or {}).get("input_version", INPUT_VERSION),
        "updated_at": (stored or {}).get("updated_at") or
                      (master.get("valuation_inputs_meta") or {}).get("updated_at"),
    }


async def save_company_inputs(database, identifier: str, patch: Mapping[str, Any],
                              *, source_type: str, source_reference: Optional[str],
                              notes: Optional[str], actor: str) -> Optional[Dict[str, Any]]:
    clean = normalize_patch(patch)
    master = await database.master_companies.find_one(
        {"$or": [{"master_id": identifier}, {"cif_normalized": identifier}]},
        {"_id": 0, "master_id": 1, "cif_normalized": 1, "valuation_inputs": 1},
    )
    if not master:
        return None
    master_id = master["master_id"]
    previous_doc = await database.valuation_company_inputs.find_one(
        {"master_id": master_id}, {"_id": 0})
    previous = dict((previous_doc or {}).get("values") or master.get("valuation_inputs") or {})
    current = dict(previous)
    evidence = dict((previous_doc or {}).get("evidence") or {})
    now = now_iso()
    for field, value in clean.items():
        if value is None:
            current.pop(field, None)
            evidence.pop(field, None)
        else:
            current[field] = value
            evidence[field] = {
                "source_type": source_type,
                "source_reference": source_reference,
                "notes": notes,
                "actor": actor,
                "observed_at": now,
                "status": "observed",
            }
    stored = {
        "master_id": master_id,
        "cif_normalized": master.get("cif_normalized"),
        "values": current,
        "evidence": evidence,
        "input_version": INPUT_VERSION,
        "updated_at": now,
        "updated_by": actor,
    }
    await database.valuation_company_inputs.update_one(
        {"master_id": master_id},
        {"$set": stored, "$setOnInsert": {"created_at": now}}, upsert=True)
    await database.master_companies.update_one(
        {"master_id": master_id},
        {"$set": {"valuation_inputs": current,
                  "valuation_inputs_evidence": evidence,
                  "valuation_inputs_meta": {"input_version": INPUT_VERSION,
                                             "updated_at": now, "updated_by": actor}}})
    await database.valuation_input_audit.insert_one({
        "audit_id": new_id(), "master_id": master_id,
        "cif_normalized": master.get("cif_normalized"),
        "previous_values": previous, "new_values": current,
        "changed_fields": sorted(clean), "source_type": source_type,
        "source_reference": source_reference, "notes": notes,
        "actor": actor, "created_at": now, "input_version": INPUT_VERSION,
    })
    return stored
