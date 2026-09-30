"""Emparejamiento de eventos BORME con empresas del Master. Funciones puras, sin base de datos.

Diseño por EVENTOS (no por empresa): el enlace anterior marcaba cada empresa como "revisada" una sola
vez (25.603 el 22-jul, un día ANTES de que llegara el primer evento de BORME) y desde entonces entran
3.000-4.000 eventos diarios que nunca se enlazaban. Aquí se parte de los eventos aún sin enlazar y se
busca su empresa por nombre normalizado (`master_companies.name_key`, indexado).

Honestidad del cruce: BORME no trae CIF, solo el nombre. Si dos empresas del Master comparten nombre, el
evento solo se enlaza si el CIF aparece en el texto o si la provincia desempata; en otro caso se descarta
por ambiguo (mejor no enlazar que enlazar mal).
"""

import unicodedata
from typing import Callable, Dict, List, Optional, Tuple

BASE_CONFIDENCE = 0.80
PROVINCE_BOOST = 0.08
CIF_CONFIDENCE = 0.95


def _norm_province(p: Optional[str]) -> set:
    """'ARABA/ÁLAVA' -> {'ARABA', 'ALAVA'}; sin acentos y en mayúsculas."""
    if not p:
        return set()
    s = "".join(c for c in unicodedata.normalize("NFD", p.upper()) if unicodedata.category(c) != "Mn")
    return {part.strip() for part in s.split("/") if part.strip()}


def _province_match(ev_province: Optional[str], master_province: Optional[str]) -> bool:
    return bool(_norm_province(ev_province) & _norm_province(master_province))


def match_events(events: List[Dict], masters_by_key: Dict[str, List[Dict]],
                 key_fn: Callable[[Optional[str]], Optional[str]]) -> Tuple[List[Dict], Dict[str, int]]:
    """Devuelve (enlaces, estadísticas). Cada enlace: idempotency_key, master_id, confidence, method.

    events: {idempotency_key, company_name_normalized, registry_province, event_text_raw}
    masters_by_key: {name_key: [{master_id, provincia, cif}]}
    """
    links: List[Dict] = []
    stats = {"examined": len(events), "linked": 0, "no_match": 0, "ambiguous": 0}
    for ev in events:
        key = key_fn(ev.get("company_name_normalized"))
        cands = masters_by_key.get(key) or []
        if not cands:
            stats["no_match"] += 1
            continue
        text = (ev.get("event_text_raw") or "").upper()
        by_cif = [m for m in cands if (m.get("cif") or "") and len(m["cif"]) >= 8 and m["cif"].upper() in text]
        by_prov = [m for m in cands if _province_match(ev.get("registry_province"), m.get("provincia"))]
        if len(by_cif) == 1:
            chosen, conf, method = by_cif[0], CIF_CONFIDENCE, "cif_exact"
        elif len(cands) == 1:
            chosen, method = cands[0], "name_exact"
            conf = min(BASE_CONFIDENCE + (PROVINCE_BOOST if by_prov else 0.0), 1.0)
        elif len(by_prov) == 1:
            chosen, method = by_prov[0], "name_province"
            conf = min(BASE_CONFIDENCE + PROVINCE_BOOST, 1.0)
        else:
            stats["ambiguous"] += 1
            continue
        links.append({"idempotency_key": ev["idempotency_key"], "master_id": chosen["master_id"],
                      "confidence": conf, "method": method})
        stats["linked"] += 1
    return links, stats
