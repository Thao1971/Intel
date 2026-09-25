"""«Mi espacio» · Solicitudes de acceso y NDA entre usuarios (sin chat).

Flujo (todo explícito y auditable, nada inferido):
  1. El vendedor PUBLICA su empresa en venta: se crea un anuncio anónimo (sin nombre, CIF, precio ni cifras).
  2. Un comprador SOLICITA acceso a ese anuncio.
  3. El vendedor ACEPTA o RECHAZA. Al aceptar queda registrada su aceptación del NDA.
  4. El comprador ACEPTA el NDA. Con ambas aceptaciones el estado pasa a `nda_signed` y solo entonces se
     revela la identidad de la empresa.
Cada paso actualiza automáticamente el pipeline de las dos partes (estado y turno dejan de ser manuales
en lo que pasa por la plataforma).

El texto del NDA es un MODELO sin validar jurídicamente. Aceptación en plataforma ≠ firma electrónica
cualificada. Se registra quién, cuándo y la versión/huella del texto aceptado.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import DuplicateKeyError

from services.my_space import STATUS_CFG, ValidationError, validate_create

NDA_VERSION = "nda-modelo-v1"
NDA_TEXT = (
    "ACUERDO DE CONFIDENCIALIDAD (MODELO — pendiente de validación jurídica)\n\n"
    "1. La parte receptora tratará como confidencial toda la información sobre la empresa que reciba a través "
    "de arroba y la usará únicamente para evaluar una posible operación con la parte reveladora.\n"
    "2. No la divulgará a terceros salvo a sus asesores, que quedarán obligados a la misma confidencialidad.\n"
    "3. No contactará con empleados, clientes ni proveedores de la empresa sin autorización expresa.\n"
    "4. La obligación se mantiene durante dos años desde la aceptación y sobrevive a la terminación de las conversaciones.\n"
    "5. Al finalizar, devolverá o destruirá la información si se le solicita.\n"
    "La aceptación en la plataforma queda registrada con fecha, usuario y versión del texto. No constituye firma "
    "electrónica cualificada."
)
NDA_HASH = hashlib.sha256(NDA_TEXT.encode("utf-8")).hexdigest()

BUYER_ROLES = ("comprador", "corporativo", "asesor")
STATUSES = ("pending", "rejected", "awaiting_buyer_nda", "nda_signed", "withdrawn")
OPEN = ("pending", "awaiting_buyer_nda")

# estado de la solicitud -> (estado de pipeline, turno del comprador, turno del vendedor)
PIPELINE_MAP = {
    "pending": ("contactado", "their", "mine"),
    "awaiting_buyer_nda": ("nda_enviado", "mine", "their"),
    "nda_signed": ("nda_firmado", "mine", "mine"),
    "rejected": ("descartada", None, None),
    "withdrawn": ("descartada", None, None),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def nda_template() -> Dict[str, str]:
    return {"version": NDA_VERSION, "hash": NDA_HASH, "text": NDA_TEXT,
            "notice": "Modelo sin validación jurídica. La aceptación en plataforma no es firma electrónica cualificada."}


# ---------------------------------------------------------------- anuncio (publicación)
def public_listing(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Vista ANÓNIMA de un anuncio: sin nombre, CIF, precio ni cifras."""
    c = obj.get("company") or {}
    f = obj.get("fields") or {}
    return {"listing_id": obj.get("listing_id"), "headline": f.get("headline"), "cnae_code": c.get("cnae_code"),
            "cnae_section": c.get("cnae_section"), "provincia": c.get("provincia"),
            "sale_type": f.get("sale_type"), "published_at": obj.get("published_at")}


async def set_published(objects, owner_id: str, published: bool) -> Dict[str, Any]:
    obj = await objects.find_one({"owner_id": owner_id, "role": "vendedor"}, {"_id": 0})
    if not obj:
        raise ValidationError("Primero guarda tu empresa en venta")
    if published:
        if not obj.get("company"):
            raise ValidationError("Para publicar, la empresa debe existir en arroba (CIF válido)")
        if not ((obj.get("fields") or {}).get("headline") or "").strip():
            raise ValidationError("Para publicar necesitas un titular: es lo único que verán los compradores")
    upd: Dict[str, Any] = {"published": published, "updated_at": _now()}
    if published:
        upd["listing_id"] = obj.get("listing_id") or uuid.uuid4().hex
        upd["published_at"] = _now()
    await objects.update_one({"owner_id": owner_id, "role": "vendedor"}, {"$set": upd})
    return {**obj, **upd}


async def list_marketplace(objects, viewer_id: str, requests, limit: int = 100) -> List[Dict[str, Any]]:
    rows = await objects.find({"role": "vendedor", "published": True}, {"_id": 0}).sort("published_at", -1).to_list(limit)
    mine = {r["listing_id"]: r for r in await requests.find({"buyer_id": viewer_id}, {"_id": 0}).to_list(500)}
    out = []
    for o in rows:
        if o.get("owner_id") == viewer_id:
            continue
        item = public_listing(o)
        r = mine.get(o.get("listing_id"))
        item["my_request"] = {"id": r["id"], "status": r["status"]} if r else None
        out.append(item)
    return out


# ---------------------------------------------------------------- pipeline enlazado
async def _sync_pipeline(pipeline, req: Dict[str, Any], seller_headline: str, seller_company: Optional[Dict[str, Any]]) -> None:
    status, buyer_turn, seller_turn = PIPELINE_MAP[req["status"]]
    disclosed = req["status"] == "nda_signed"
    buyer_label = (seller_company or {}).get("name") if disclosed and seller_company else None
    buyer_label = buyer_label or f"Empresa en venta: {seller_headline}"
    sides = (
        (req["buyer_id"], req["as_role"], buyer_label, "empresa", buyer_turn),
        (req["seller_id"], "vendedor", req.get("buyer_name") or "Comprador", "comprador", seller_turn),
    )
    for owner, role, name, ctype, turn in sides:
        turn = turn if STATUS_CFG[status]["has_turn"] else None
        existing = await pipeline.find_one({"owner_id": owner, "request_id": req["id"]}, {"_id": 0})
        if existing:
            await pipeline.update_one({"owner_id": owner, "request_id": req["id"]},
                                      {"$set": {"status": status, "turn": turn, "counterpart_name": name[:200],
                                                "updated_at": _now(), "last_activity_at": _now()}})
        else:
            doc = validate_create({"counterpart_name": name, "counterpart_type": ctype, "status": status, "turn": turn}, role)
            doc.update({"owner_id": owner, "request_id": req["id"]})
            await pipeline.insert_one(doc)


# ---------------------------------------------------------------- solicitudes
async def create_request(colls, buyer_id: str, buyer_name: Optional[str], listing_id: str, as_role: str,
                         message: Optional[str], org_name: Optional[str]) -> Dict[str, Any]:
    if as_role not in BUYER_ROLES:
        raise ValidationError(f"as_role debe ser uno de {', '.join(BUYER_ROLES)}")
    obj = await colls["objects"].find_one({"listing_id": listing_id, "published": True}, {"_id": 0})
    if not obj:
        raise LookupError("anuncio no encontrado")
    if obj["owner_id"] == buyer_id:
        raise ValidationError("No puedes solicitar acceso a tu propio anuncio")
    dup = await colls["requests"].find_one({"listing_id": listing_id, "buyer_id": buyer_id}, {"_id": 0})
    if dup and dup["status"] in OPEN + ("nda_signed",):
        raise ValidationError("Ya tienes una solicitud activa para este anuncio")
    now = _now()
    req = {"id": uuid.uuid4().hex, "listing_id": listing_id, "seller_id": obj["owner_id"], "buyer_id": buyer_id,
           "buyer_name": (buyer_name or "").strip()[:200] or None, "buyer_org_declared": (org_name or "").strip()[:200] or None,
           "as_role": as_role, "message": (message or "").strip()[:1000] or None, "status": "pending",
           "nda": {"template_version": NDA_VERSION, "text_hash": NDA_HASH, "seller_accepted_at": None, "buyer_accepted_at": None},
           "events": [{"at": now, "by": buyer_id, "type": "requested"}], "created_at": now, "updated_at": now}
    if dup:  # solicitud anterior rechazada/retirada: se sustituye por la nueva
        await colls["requests"].delete_one({"id": dup["id"]})
        for owner in (dup["buyer_id"], dup["seller_id"]):  # sin restos de la solicitud anterior en los pipelines
            await colls["pipeline"].delete_one({"owner_id": owner, "request_id": dup["id"]})
    try:
        await colls["requests"].insert_one(dict(req))
    except DuplicateKeyError as exc:
        raise ValidationError("Ya existe una solicitud para este anuncio") from exc
    await _sync_pipeline(colls["pipeline"], req, (obj.get("fields") or {}).get("headline") or "", obj.get("company"))
    return req


async def _load(colls, req_id: str, user_id: str) -> Dict[str, Any]:
    req = await colls["requests"].find_one({"id": req_id}, {"_id": 0})
    if not req or user_id not in (req["buyer_id"], req["seller_id"]):
        raise LookupError("solicitud no encontrada")  # inexistente o ajena: mismo resultado
    return req


async def _save(
    colls,
    req: Dict[str, Any],
    event_by: str,
    event_type: str,
    *,
    expected_status: str,
    **fields,
) -> Dict[str, Any]:
    now = _now()
    updated = {**req, **fields, "updated_at": now,
               "events": req["events"] + [{"at": now, "by": event_by, "type": event_type}]}
    result = await colls["requests"].update_one(
        {"id": req["id"], "status": expected_status},
        {"$set": {k: updated[k] for k in ("status", "nda", "updated_at", "events")}},
    )
    # Motor devuelve UpdateResult; los dobles de test antiguos pueden devolver None.
    if result is not None and getattr(result, "modified_count", 1) != 1:
        raise ValidationError("La solicitud ha cambiado; actualiza la página antes de continuar")
    obj = await colls["objects"].find_one({"listing_id": updated["listing_id"]}, {"_id": 0}) or {}
    await _sync_pipeline(colls["pipeline"], updated, (obj.get("fields") or {}).get("headline") or "", obj.get("company"))
    return updated


async def decide(colls, seller_id: str, req_id: str, decision: str) -> Dict[str, Any]:
    if decision not in ("accept", "reject"):
        raise ValidationError("decision debe ser 'accept' o 'reject'")
    req = await _load(colls, req_id, seller_id)
    if req["seller_id"] != seller_id:
        raise LookupError("solicitud no encontrada")
    if req["status"] != "pending":
        raise ValidationError(f"La solicitud ya no está pendiente ({req['status']})")
    if decision == "reject":
        return await _save(colls, req, seller_id, "rejected", expected_status="pending", status="rejected")
    nda = {**req["nda"], "seller_accepted_at": _now()}
    return await _save(colls, req, seller_id, "accepted_by_seller", expected_status="pending",
                       status="awaiting_buyer_nda", nda=nda)


async def accept_nda(colls, buyer_id: str, req_id: str, text_hash: str) -> Dict[str, Any]:
    req = await _load(colls, req_id, buyer_id)
    if req["buyer_id"] != buyer_id:
        raise LookupError("solicitud no encontrada")
    if req["status"] != "awaiting_buyer_nda":
        raise ValidationError("El vendedor todavía no ha aceptado tu solicitud, o ya está resuelta")
    if text_hash != NDA_HASH:
        raise ValidationError("El texto del NDA ha cambiado: vuelve a leerlo antes de aceptar")
    nda = {**req["nda"], "buyer_accepted_at": _now()}
    return await _save(colls, req, buyer_id, "nda_accepted_by_buyer",
                       expected_status="awaiting_buyer_nda", status="nda_signed", nda=nda)


async def withdraw(colls, buyer_id: str, req_id: str) -> Dict[str, Any]:
    req = await _load(colls, req_id, buyer_id)
    if req["buyer_id"] != buyer_id:
        raise LookupError("solicitud no encontrada")
    if req["status"] not in OPEN:
        raise ValidationError("Solo puedes retirar una solicitud abierta")
    return await _save(colls, req, buyer_id, "withdrawn", expected_status=req["status"], status="withdrawn")


async def view_for(colls, user_id: str, req: Dict[str, Any]) -> Dict[str, Any]:
    """Proyección según quién mira. La identidad de la empresa solo se revela al comprador con NDA firmado."""
    obj = await colls["objects"].find_one({"listing_id": req["listing_id"]}, {"_id": 0}) or {}
    out = {"id": req["id"], "status": req["status"], "role": "buyer" if user_id == req["buyer_id"] else "seller",
           "as_role": req["as_role"], "message": req.get("message"), "created_at": req["created_at"],
           "updated_at": req["updated_at"], "nda": req["nda"], "listing": public_listing(obj) if obj else None}
    if user_id == req["seller_id"]:
        out["buyer"] = {"name": req.get("buyer_name"), "org_declared": req.get("buyer_org_declared")}
    if user_id == req["buyer_id"] and req["status"] == "nda_signed" and obj:
        f, c = obj.get("fields") or {}, obj.get("company") or {}
        out["disclosed"] = {"company_name": c.get("name") or f.get("company_name"), "cif": f.get("cif"),
                            "asking_price_eur": f.get("asking_price_eur"), "sale_type": f.get("sale_type"),
                            "headline": f.get("headline"), "revenue": c.get("revenue")}
    return out


async def list_requests(colls, user_id: str, box: str) -> List[Dict[str, Any]]:
    if box not in ("incoming", "outgoing"):
        raise ValidationError("box debe ser 'incoming' o 'outgoing'")
    key = "seller_id" if box == "incoming" else "buyer_id"
    rows = await colls["requests"].find({key: user_id}, {"_id": 0}).sort("updated_at", -1).to_list(200)
    return [await view_for(colls, user_id, r) for r in rows]


async def get_request(colls, user_id: str, req_id: str) -> Dict[str, Any]:
    return await view_for(colls, user_id, await _load(colls, req_id, user_id))


async def summary(colls, user_id: str) -> Dict[str, int]:
    inc = await colls["requests"].find({"seller_id": user_id}, {"_id": 0}).to_list(500)
    out = await colls["requests"].find({"buyer_id": user_id}, {"_id": 0}).to_list(500)
    return {"incoming_pending": sum(1 for r in inc if r["status"] == "pending"),
            "awaiting_my_nda": sum(1 for r in out if r["status"] == "awaiting_buyer_nda"),
            "nda_signed": sum(1 for r in inc + out if r["status"] == "nda_signed")}
