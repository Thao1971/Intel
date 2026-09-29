"""«Mi espacio» · escenarios de valoración editados a mano.

Cuando un usuario toca un supuesto (WACC, crecimiento, múltiplo...) en la
pantalla de valoración avanzada, el resultado deja de ser la valoración de
arroba/Intel para esa empresa — es una simulación suya. Este módulo solo
guarda esa simulación como una instantánea, ligada estrictamente a su
`owner_id`: nunca se lee desde el motor de valoración, nunca se agrega ni se
promedia con las de otros usuarios, y no hay ninguna ruta que la exponga sin
filtrar por el propietario. Es lo contrario de `master_companies`/
`norm_financials`: esos son datos compartidos que alimentan la valoración
real; esto es un cuaderno privado que nunca vuelve a alimentar nada.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.my_space import ValidationError

MAX_LABEL = 120
MAX_ITEMS_PER_OWNER = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(v: Any, n: int) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s[:n] or None


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _clean(data: Dict[str, Any]) -> Dict[str, Any]:
    cif = (_text(data.get("cif"), 20) or "").upper().replace(" ", "").replace("-", "")
    if not cif:
        raise ValidationError("cif es obligatorio")
    inputs = data.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise ValidationError("inputs es obligatorio")
    outputs = data.get("outputs") or {}
    reference = data.get("reference") or {}
    return {
        "cif": cif,
        "company_name": _text(data.get("company_name"), 200),
        "run_id": _text(data.get("run_id"), 80),
        "label": _text(data.get("label"), MAX_LABEL) or "Escenario editado",
        "inputs": inputs,
        "outputs": {
            "enterprise_value": _num(outputs.get("enterprise_value")),
            "equity_value": _num(outputs.get("equity_value")),
            "conservative": _num(outputs.get("conservative")),
            "optimistic": _num(outputs.get("optimistic")),
        },
        "reference": {
            "enterprise_value": _num(reference.get("enterprise_value")),
            "equity_value": _num(reference.get("equity_value")),
        },
    }


async def create_scenario(coll, owner_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    existing = await coll.count_documents({"owner_id": owner_id})
    if existing >= MAX_ITEMS_PER_OWNER:
        raise ValidationError(f"Límite de {MAX_ITEMS_PER_OWNER} escenarios guardados alcanzado")
    f = _clean(data)
    doc = {"id": uuid.uuid4().hex, "owner_id": owner_id, **f, "created_at": _now()}
    await coll.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def list_scenarios(coll, owner_id: str, cif: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {"owner_id": owner_id}
    if cif:
        query["cif"] = cif.upper().replace(" ", "").replace("-", "")
    rows = await coll.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return rows


async def get_scenario(coll, owner_id: str, scenario_id: str) -> Optional[Dict[str, Any]]:
    return await coll.find_one({"id": scenario_id, "owner_id": owner_id}, {"_id": 0})


async def delete_scenario(coll, owner_id: str, scenario_id: str) -> bool:
    res = await coll.delete_one({"id": scenario_id, "owner_id": owner_id})
    return bool(getattr(res, "deleted_count", 0))
