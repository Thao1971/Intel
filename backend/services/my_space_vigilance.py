"""«Mi espacio» · Vigilancia: alertas reales por usuario final.

Reutiliza `services/watchlist.py` (alertas generadas desde señales reales ya persistidas por el
Signal Engine). La lista de empresas seguidas vive en Beta (por CIF); aquí se replica por usuario final
para poder generar alertas. Nunca se calcula una señal nueva ni se inventa un aviso.
"""
from __future__ import annotations

from typing import Any, Dict, List

from services import watchlist as W
from services.my_space import ValidationError

MAX_CIFS = 500


def normalize_cifs(cifs: List[str]) -> List[str]:
    if len(cifs) > MAX_CIFS:
        raise ValidationError(f"máximo {MAX_CIFS} empresas")
    out: List[str] = []
    for c in cifs:
        n = str(c or "").upper().replace(" ", "").replace("-", "").strip()
        if n and n not in out:
            out.append(n)
    return out


async def sync_watches(owner_id: str, cifs: List[str], master_coll) -> Dict[str, Any]:
    """Deja el seguimiento del usuario igual a `cifs` (los que no existan en arroba se informan)."""
    wanted = normalize_cifs(cifs)
    masters = {}
    unresolved: List[str] = []
    for cif in wanted:
        m = await master_coll.find_one({"cif_normalized": cif}, {"_id": 0, "master_id": 1, "cif_normalized": 1})
        if m and m.get("master_id"):
            masters[m["master_id"]] = cif
        else:
            unresolved.append(cif)
    current = {w["master_id"] for w in await W.list_watches(owner_id)}
    for mid in masters:
        if mid not in current:
            await W.add_watch(owner_id, mid)
    for mid in current - set(masters):
        await W.remove_watch(owner_id, mid)
    created = (await W.sync_alerts_for_user(owner_id))["alerts_created"]
    return {"watching": len(masters), "unresolved": unresolved, "alerts_created": created}


async def list_alerts(owner_id: str, master_coll, unread_only: bool = False, limit: int = 50) -> Dict[str, Any]:
    rows = await W.list_alerts(owner_id, unread_only=unread_only, limit=limit)
    names: Dict[str, Dict[str, Any]] = {}
    for mid in {r["master_id"] for r in rows if r.get("master_id")}:
        m = await master_coll.find_one({"master_id": mid}, {"_id": 0, "master_id": 1, "cif_normalized": 1, "identity.legal_name": 1})
        if m:
            names[mid] = {"name": (m.get("identity") or {}).get("legal_name"), "cif": m.get("cif_normalized")}
    alerts = [{
        "alert_id": r["alert_id"], "master_id": r.get("master_id"),
        "company_name": names.get(r.get("master_id"), {}).get("name"), "cif": names.get(r.get("master_id"), {}).get("cif"),
        "signal_type": r.get("signal_type"), "category": r.get("category"),
        "explanation": r.get("explanation"), "detected_at": r.get("signal_detected_at"),
        "read": bool(r.get("read")),
    } for r in rows]
    return {"unread": await W.unread_count(owner_id), "count": len(alerts), "alerts": alerts,
            "basis": "Señales reales ya detectadas por arroba en las empresas que sigues. Solo dentro de la plataforma: no se envían correos ni notificaciones."}
