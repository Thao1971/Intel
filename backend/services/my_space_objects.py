"""«Mi espacio»: objeto central de Vendedor (mi empresa en venta) y Busca capital (mi tesis de captación).

Solo se guarda lo que el usuario declara. Las coincidencias se calculan con fuentes reales de Intel
(motor de recomendación de compradores, fondos/gestoras de la CNMV por sector, mandatos activos) y
siempre indican su base. No hay visitas, descargas ni «interés» inventado: esos datos no existen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.my_space import ValidationError

OBJECT_ROLES = ("vendedor", "busca_capital")
SALE_TYPES = ("por_definir", "venta_total", "venta_parcial")
TEASER_STATUS = ("sin_teaser", "borrador", "listo", "compartido")
INSTRUMENTS = ("por_definir", "minoritario", "mayoritario", "deuda", "mixto")
MAX_MONEY = 1e12


def _text(v: Any, n: int) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s[:n] or None


def _money(v: Any, name: str) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} debe ser un número")
    if f < 0 or f > MAX_MONEY:
        raise ValidationError(f"{name} fuera de rango")
    return f


def _choice(v: Any, allowed, name: str, default: str) -> str:
    v = v or default
    if v not in allowed:
        raise ValidationError(f"{name} no válido: {v}")
    return v


def validate_object(role: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if role not in OBJECT_ROLES:
        raise ValidationError(f"el rol {role} no tiene objeto central editable")
    name = _text(data.get("company_name"), 200)
    if not name:
        raise ValidationError("company_name es obligatorio")
    out: Dict[str, Any] = {
        "company_name": name,
        "cif": (_text(data.get("cif"), 20) or "").upper().replace(" ", "").replace("-", "") or None,
        "headline": _text(data.get("headline"), 200),
        "notes": _text(data.get("notes"), 2000),
    }
    if role == "vendedor":
        out["sale_type"] = _choice(data.get("sale_type"), SALE_TYPES, "sale_type", "por_definir")
        out["asking_price_eur"] = _money(data.get("asking_price_eur"), "asking_price_eur")
        out["teaser_status"] = _choice(data.get("teaser_status"), TEASER_STATUS, "teaser_status", "sin_teaser")
        out["timeline"] = _text(data.get("timeline"), 200)
    else:
        lo, hi = _money(data.get("amount_min_eur"), "amount_min_eur"), _money(data.get("amount_max_eur"), "amount_max_eur")
        if lo is not None and hi is not None and lo > hi:
            raise ValidationError("amount_min_eur no puede superar amount_max_eur")
        out["amount_min_eur"], out["amount_max_eur"] = lo, hi
        out["instrument"] = _choice(data.get("instrument"), INSTRUMENTS, "instrument", "por_definir")
        out["use_of_funds"] = _text(data.get("use_of_funds"), 500)
    return out


async def resolve_company(master_coll, cif: Optional[str]) -> Optional[Dict[str, Any]]:
    """Empresa real en el Master Layer por CIF; None si no existe (no se inventa)."""
    if not cif:
        return None
    m = await master_coll.find_one({"cif_normalized": cif}, {"_id": 0})
    if not m:
        return None
    cls = m.get("classification") or {}
    return {
        "master_id": m.get("master_id"),
        "name": (m.get("identity") or {}).get("legal_name"),
        "cnae_code": cls.get("cnae_code"),
        "cnae_section": cls.get("cnae_section"),
        "provincia": (m.get("location") or {}).get("provincia"),
        "revenue": ((m.get("financials") or {}).get("latest") or {}).get("revenue"),
    }


async def get_object(coll, owner_id: str, role: str) -> Optional[Dict[str, Any]]:
    return await coll.find_one({"owner_id": owner_id, "role": role}, {"_id": 0})


async def save_object(coll, master_coll, owner_id: str, role: str, data: Dict[str, Any]) -> Dict[str, Any]:
    fields = validate_object(role, data)
    company = await resolve_company(master_coll, fields.get("cif"))
    doc = {"owner_id": owner_id, "role": role, "fields": fields, "company": company,
           "updated_at": datetime.now(timezone.utc).isoformat()}
    await coll.update_one({"owner_id": owner_id, "role": role}, {"$set": doc}, upsert=True)
    return doc


Provider = Callable[..., Awaitable[Any]]


def _fund_row(e: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": e.get("name"), "entity_type": e.get("entity_type"), "label": e.get("mna_label") or None,
            "sector_score": e.get("sector_score")}


async def build_matches(role: str, obj: Optional[Dict[str, Any]], providers: Dict[str, Provider],
                        limit: int = 8) -> Dict[str, Any]:
    """Coincidencias reales para el objeto guardado. Cada bloque indica su base."""
    if role not in OBJECT_ROLES:
        raise ValidationError(f"el rol {role} no tiene coincidencias")
    if not obj:
        return {"available": False, "reason": "no_object"}
    company = obj.get("company")
    if not company:
        return {"available": False, "reason": "company_not_found",
                "message": "No encontramos esa empresa por CIF en arroba; sin ella no podemos calcular coincidencias."}
    cnae = company.get("cnae_code")
    cnmv = await providers["cnmv"](cnae) if cnae else None
    funds: List[Dict[str, Any]] = []
    generalists = 0
    if cnmv:
        funds = [_fund_row(e) for e in (cnmv.get("specialist_funds") or [])[:limit]]
        managers = [_fund_row(e) for e in (cnmv.get("specialist_managers") or [])[:limit]]
        generalists = len(cnmv.get("generalist_funds") or []) + len(cnmv.get("generalist_managers") or [])
    else:
        managers = []

    fund_block = {"funds": funds, "managers": managers, "generalists_count": generalists,
                  "basis": "Fondos y gestoras de la CNMV clasificados por coincidencia de palabras clave sectoriales en su denominación oficial. Es una clasificación orientativa, no un interés declarado."}
    if role == "busca_capital":
        return {"available": True, "role": role, "company": company, "investors": fund_block,
                "notes": ["El motor de recomendación de inversores todavía no tiene fuente de datos: aquí solo se muestran fondos y gestoras de la CNMV por sector."]}

    rec = await providers["buyers"](company["master_id"], limit)
    buyers = []
    for r in (rec or {}).get("recommendations", []):
        cand = r.get("candidate") or {}
        buyers.append({"master_id": cand.get("master_id"), "name": cand.get("name"),
                       "role_label": r.get("recommendation_role_label"), "score": r.get("score"),
                       "explanation": r.get("explanation")})
    mand = await providers["mandates"](company["master_id"])
    interested = None
    if mand:
        scores = [m.get("score") for m in mand.get("mandates", []) if m.get("score") is not None]
        interested = {"evaluated": mand.get("mandates_scanned", 0), "with_fit": len(scores),
                      "best_score": max(scores) if scores else None,
                      "basis": "Mandatos de compra activos en arroba evaluados contra tu empresa. Por privacidad no se muestran nombres."}
    return {"available": True, "role": role, "company": company,
            "buyers": {"items": buyers, "basis": "Empresas más grandes del universo con semejanza sectorial, financiera y estratégica (motor de recomendación de arroba)."},
            "financial_buyers": fund_block, "interested_mandates": interested}
