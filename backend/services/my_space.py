"""«Mi espacio»: perfil de rol y pipeline de contactos/NDAs.

Principio de honestidad (igual que el mockup «Comprador - Pipeline»): arroba NO tiene
mensajería humano-humano ni seguimiento automático de NDAs. El estado de cada contacto y
«de quién es el turno» los declara el usuario. Aquí solo se persisten y se derivan
urgencia y próximo paso con reglas simples. Nada se infiere ni se inventa.

Este módulo es lógica pura + acceso a una colección Mongo pasada por parámetro
(testeable sin base de datos real).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ROLES = ("comprador", "vendedor", "asesor", "corporativo", "busca_capital")
COUNTERPART_TYPES = ("empresa", "comprador", "inversor", "cliente")
TURNS = ("mine", "their")
URGENT_AFTER_DAYS = 10

# hasTurn: el estado admite «de quién es el turno»; turn_default: turno propuesto al entrar.
STATUS_CFG: Dict[str, Dict[str, Any]] = {
    "sin_contactar":   {"has_turn": False, "turn_default": None,    "next": "Contactar / iniciar aproximación"},
    "contactado":      {"has_turn": True,  "turn_default": "their", "mine_next": "Responder / seguir la conversación"},
    "en_conversacion": {"has_turn": True,  "turn_default": "mine",  "mine_next": "Seguir la conversación"},
    "nda_enviado":     {"has_turn": True,  "turn_default": "their", "mine_next": "Reenviar / recordar el NDA"},
    "nda_firmado":     {"has_turn": True,  "turn_default": "mine",  "mine_next": "Compartir información · dar acceso al data room"},
    "descartada":      {"has_turn": False, "turn_default": None,    "next": None},
}
CLOSED = ("descartada",)

DEFAULT_COUNTERPART = {
    "comprador": "empresa", "vendedor": "comprador", "asesor": "cliente",
    "corporativo": "empresa", "busca_capital": "inversor",
}


class ValidationError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------- perfil
def normalize_profile(roles: List[str], active_role: Optional[str]) -> Dict[str, Any]:
    clean = []
    for r in roles or []:
        if r not in ROLES:
            raise ValidationError(f"rol no válido: {r}")
        if r not in clean:
            clean.append(r)
    if not clean:
        raise ValidationError("indica al menos un rol")
    active = active_role or clean[0]
    if active not in clean:
        raise ValidationError("el rol activo debe estar entre tus roles")
    return {"roles": clean, "active_role": active}


async def get_profile(coll, owner_id: str) -> Optional[Dict[str, Any]]:
    doc = await coll.find_one({"owner_id": owner_id}, {"_id": 0})
    return doc


async def set_profile(coll, owner_id: str, roles: List[str], active_role: Optional[str]) -> Dict[str, Any]:
    prof = normalize_profile(roles, active_role)
    doc = {**prof, "owner_id": owner_id, "updated_at": _iso(_now())}
    await coll.update_one({"owner_id": owner_id}, {"$set": doc}, upsert=True)
    return doc


# ---------------------------------------------------------------- pipeline
def _resolve_turn(status: str, turn: Optional[str], previous_status: Optional[str] = None,
                  previous_turn: Optional[str] = None) -> Optional[str]:
    cfg = STATUS_CFG[status]
    if not cfg["has_turn"]:
        return None
    if turn is not None:
        if turn not in TURNS:
            raise ValidationError("turn debe ser 'mine' o 'their'")
        return turn
    if previous_status == status and previous_turn in TURNS:
        return previous_turn
    return cfg["turn_default"]


def derive(item: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Añade campos derivados (no persistidos): días sin actividad, urgencia y próximo paso."""
    now = now or _now()
    last = _parse(item.get("last_activity_at")) or _parse(item.get("created_at")) or now
    idle = max(0, (now - last).days)
    status = item.get("status", "sin_contactar")
    cfg = STATUS_CFG.get(status, STATUS_CFG["sin_contactar"])
    if not cfg["has_turn"]:
        next_step = cfg.get("next")
    elif item.get("turn") == "their":
        next_step = "Esperando respuesta del otro lado"
    else:
        next_step = cfg.get("mine_next")
    return {**item, "days_idle": idle,
            "urgent": status not in CLOSED and idle >= URGENT_AFTER_DAYS,
            "next_step": next_step}


def validate_create(data: Dict[str, Any], role: str) -> Dict[str, Any]:
    if role not in ROLES:
        raise ValidationError(f"rol no válido: {role}")
    name = (data.get("counterpart_name") or "").strip()
    if not name:
        raise ValidationError("counterpart_name es obligatorio")
    status = data.get("status") or "sin_contactar"
    if status not in STATUS_CFG:
        raise ValidationError(f"status no válido: {status}")
    ctype = data.get("counterpart_type") or DEFAULT_COUNTERPART[role]
    if ctype not in COUNTERPART_TYPES:
        raise ValidationError(f"counterpart_type no válido: {ctype}")
    now = _iso(_now())
    return {
        "id": uuid.uuid4().hex, "role": role,
        "counterpart_name": name[:200], "counterpart_type": ctype,
        "cif": (data.get("cif") or None), "master_id": data.get("master_id") or None,
        "sector": data.get("sector") or None, "provincia": data.get("provincia") or None,
        "mandate_id": data.get("mandate_id") or None,
        "status": status, "turn": _resolve_turn(status, data.get("turn")),
        "notes": (data.get("notes") or "")[:2000],
        "created_at": now, "updated_at": now, "last_activity_at": now,
    }


async def create_item(coll, owner_id: str, role: str, data: Dict[str, Any]) -> Dict[str, Any]:
    doc = validate_create(data, role)
    doc["owner_id"] = owner_id
    await coll.insert_one(dict(doc))
    return derive(doc)


async def list_items(coll, owner_id: str, role: Optional[str] = None, status: Optional[str] = None,
                     turn: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"owner_id": owner_id}
    if role:
        if role not in ROLES:
            raise ValidationError(f"rol no válido: {role}")
        q["role"] = role
    if status:
        if status not in STATUS_CFG:
            raise ValidationError(f"status no válido: {status}")
        q["status"] = status
    if turn:
        if turn not in TURNS:
            raise ValidationError("turn debe ser 'mine' o 'their'")
        q["turn"] = turn
    rows = await coll.find(q, {"_id": 0}).sort("last_activity_at", -1).to_list(limit)
    return [derive(r) for r in rows]


async def update_item(coll, owner_id: str, item_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cur = await coll.find_one({"id": item_id, "owner_id": owner_id}, {"_id": 0})
    if not cur:
        return None  # inexistente o de otro usuario: mismo resultado (no filtra existencia)
    if cur.get("request_id") and ("status" in patch or "turn" in patch):
        raise ValidationError("El estado y el turno de esta solicitud los gestiona arroba (solicitud de acceso/NDA)")
    upd: Dict[str, Any] = {}
    status = patch.get("status", cur["status"])
    if status not in STATUS_CFG:
        raise ValidationError(f"status no válido: {status}")
    if "status" in patch or "turn" in patch:
        upd["status"] = status
        upd["turn"] = _resolve_turn(status, patch.get("turn"), cur["status"], cur.get("turn"))
    for f, n in (("counterpart_name", 200), ("notes", 2000), ("sector", 100), ("provincia", 100)):
        if f in patch and patch[f] is not None:
            v = str(patch[f]).strip()[:n]
            if f == "counterpart_name" and not v:
                raise ValidationError("counterpart_name no puede quedar vacío")
            upd[f] = v
    now = _iso(_now())
    upd["updated_at"] = now
    upd["last_activity_at"] = now  # cualquier edición del usuario cuenta como actividad
    await coll.update_one({"id": item_id, "owner_id": owner_id}, {"$set": upd})
    return derive({**cur, **upd})


async def delete_item(coll, owner_id: str, item_id: str) -> bool:
    res = await coll.delete_one({"id": item_id, "owner_id": owner_id})
    return bool(getattr(res, "deleted_count", 0))


def summarize(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Resumen sobre items ya derivados."""
    open_ = [i for i in items if i["status"] not in CLOSED]
    return {
        "total": len(items), "open": len(open_),
        "my_turn": sum(1 for i in open_ if i.get("turn") == "mine"),
        "waiting_other": sum(1 for i in open_ if i.get("turn") == "their"),
        "urgent": sum(1 for i in open_ if i["urgent"]),
        "not_contacted": sum(1 for i in open_ if i["status"] == "sin_contactar"),
        "nda_pending": sum(1 for i in open_ if i["status"] == "nda_enviado"),
        "nda_signed": sum(1 for i in open_ if i["status"] == "nda_firmado"),
        "discarded": len(items) - len(open_),
    }
