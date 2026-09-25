"""«Mi espacio» · Asesor: cartera de mandatos y clientes.

Todo lo declara el asesor (cliente, tipo de mandato, fase, próxima acción y fecha). No hay CRM ni
seguimiento automático: solo se persiste y se derivan retrasos y próximas acciones con reglas simples.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from services.my_space import ValidationError
from services.my_space_objects import resolve_company

KINDS = ("venta", "compra", "capital")
STAGES = ("prospecto", "mandato_firmado", "en_preparacion", "en_mercado", "negociacion", "cerrado", "perdido")
CLOSED = ("cerrado", "perdido")
UPCOMING_DAYS = 14


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(v: Any, n: int) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s[:n] or None


def _date(v: Any) -> Optional[str]:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise ValidationError("next_action_date debe ser una fecha AAAA-MM-DD")


def _clean(data: Dict[str, Any], partial: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not partial or "client_name" in data:
        name = _text(data.get("client_name"), 200)
        if not name:
            raise ValidationError("client_name es obligatorio")
        out["client_name"] = name
    if not partial or "kind" in data:
        k = data.get("kind") or "venta"
        if k not in KINDS:
            raise ValidationError(f"kind no válido: {k}")
        out["kind"] = k
    if not partial or "stage" in data:
        s = data.get("stage") or "prospecto"
        if s not in STAGES:
            raise ValidationError(f"stage no válido: {s}")
        out["stage"] = s
    for f, n in (("company_name", 200), ("next_action", 300), ("notes", 2000)):
        if not partial or f in data:
            out[f] = _text(data.get(f), n)
    if not partial or "cif" in data:
        out["cif"] = (_text(data.get("cif"), 20) or "").upper().replace(" ", "").replace("-", "") or None
    if not partial or "next_action_date" in data:
        out["next_action_date"] = _date(data.get("next_action_date"))
    return out


def derive(item: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    d = item.get("next_action_date")
    days = None
    if d and item.get("stage") not in CLOSED:
        days = (date.fromisoformat(d) - today).days
    return {**item, "days_to_action": days, "overdue": days is not None and days < 0}


async def create_item(coll, master_coll, owner_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    f = _clean(data, partial=False)
    company = await resolve_company(master_coll, f.get("cif"))
    now = _now()
    doc = {"id": uuid.uuid4().hex, "owner_id": owner_id, **f, "company": company, "created_at": now, "updated_at": now}
    await coll.insert_one(dict(doc))
    return derive(doc)


async def list_items(coll, owner_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    rows = await coll.find({"owner_id": owner_id}, {"_id": 0}).sort("updated_at", -1).to_list(limit)
    return [derive(r) for r in rows]


async def update_item(coll, master_coll, owner_id: str, item_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cur = await coll.find_one({"id": item_id, "owner_id": owner_id}, {"_id": 0})
    if not cur:
        return None
    upd = _clean(patch, partial=True)
    if "cif" in upd:
        upd["company"] = await resolve_company(master_coll, upd["cif"])
    upd["updated_at"] = _now()
    await coll.update_one({"id": item_id, "owner_id": owner_id}, {"$set": upd})
    return derive({**cur, **upd})


async def delete_item(coll, owner_id: str, item_id: str) -> bool:
    res = await coll.delete_one({"id": item_id, "owner_id": owner_id})
    return bool(getattr(res, "deleted_count", 0))


def summarize(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    open_ = [i for i in items if i["stage"] not in CLOSED]
    by_stage = {s: sum(1 for i in items if i["stage"] == s) for s in STAGES}
    upcoming = sorted(
        [i for i in open_ if i.get("days_to_action") is not None and i["days_to_action"] <= UPCOMING_DAYS],
        key=lambda i: i["days_to_action"])
    return {"total": len(items), "open": len(open_), "overdue": sum(1 for i in open_ if i["overdue"]),
            "by_stage": by_stage, "upcoming_days": UPCOMING_DAYS,
            "upcoming": [{"id": i["id"], "client_name": i["client_name"], "next_action": i.get("next_action"),
                          "next_action_date": i.get("next_action_date"), "days_to_action": i["days_to_action"],
                          "overdue": i["overdue"]} for i in upcoming]}
