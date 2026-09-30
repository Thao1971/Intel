"""BORME → Signal Intelligence bridge (Q1 — Intent signals desde BORME).

Closes the gap the Capability Map v1 documented as `corporate.borme_event` /
G3 ("Intent Signals"): BORME events were already fetched, parsed and classified
(`backend/borme/parser.py`, `backend/borme/routes.py`) but never linked to a
`master_id` nor consumed by the Signal Intelligence Engine — the taxonomy entry
was declared `pending=True` and stayed empty.

Two responsibilities, kept separate from `engine.py`'s numeric/threshold pipeline
(D1) and the composite pipeline (D7):

1. Linking (`link_events_to_master` / `_find_and_link`): BORME events carry a
   normalized company name (and free text that may contain the CIF) but no
   `master_id`. This module persists that link the first time a company is
   evaluated (or via the batch admin endpoint), so subsequent evaluations are a
   simple indexed query instead of re-matching.
2. Evaluation (`evaluate`): reads the linked events for one company within a
   lookback window and emits signals in EXACTLY the same explainable shape as
   `engine.py::_make` (dimensions, evidence, rule, recommended_actions), so
   consumers cannot tell a BORME-sourced signal from a numeric one.

No new engine, no new data source — this only activates infrastructure that
was already built (BORME ingestion) but disconnected (D-quote from the Roadmap:
"no requiere nuevos motores ni nuevas fuentes de datos").
"""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from pymongo import UpdateOne

from database import db
from models import now_iso
from borme.parser import normalize_company_name
from services.data_layer.normalize import name_key
from services import borme_matching as BM
from services.engines.signal import taxonomy as T
from services.engines.signal import thresholds as TH
from services.engines.signal import actions as A
from services.engines.signal import succession_intelligence as SI
from services import officer_utils as OU
from services import opportunity_criteria as CR

BRIDGE_VERSION = "borme-signal-bridge-v1"
LOOKBACK_MONTHS = 24

GOVERNANCE_SUBTYPES = {"appointment", "cessation", "reelection", "revocation", "governance_change"}
CAPITAL_SUBTYPES = {"capital_increase", "capital_decrease"}
DISSOLUTION_SUBTYPES = {"dissolution", "extinction", "liquidation", "insolvency"}

_INDEXED = False


async def ensure_indexes() -> None:
    global _INDEXED
    if _INDEXED:
        return
    await db.borme_events.create_index("company_name_normalized")
    await db.borme_events.create_index([("master_id", 1), ("publication_date", -1)])
    await db.master_companies.create_index("borme_link_checked_at")
    _INDEXED = True


def _clamp01(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 4)


def _recency_boost(publication_date: Optional[str]) -> float:
    """More recent events read as more urgent/impactful (bounded, D2-style)."""
    if not publication_date:
        return 0.0
    d = OU.parse_borme_date(publication_date)   # el formato real es YYYYMMDD
    if d is None:
        return 0.0
    days = (datetime.now(timezone.utc) - d).days
    if days <= 30:
        return 0.15
    if days <= 90:
        return 0.05
    return 0.0


def _cutoff_date() -> str:
    d = datetime.now(timezone.utc) - timedelta(days=30 * LOOKBACK_MONTHS)
    return d.strftime("%Y%m%d")   # mismo formato que `publication_date` de los eventos (YYYYMMDD)


ADMIN_ROLE_KEYWORDS = SI.ADMIN_ROLE_KEYWORDS  # covers "Administrador Único", "Administrador Solidario", etc.


async def _administrator_tenure(cif_normalized: Optional[str]) -> Optional[Dict]:
    """Real tenure proxy for succession risk (Iberinform `norm_officers.appointment_date`,
    format DD/MM/YYYY — confirmed field, see `iberinform_ingest.py::ingest_officers_file`).

    Age/birth date is NOT available in any connected source (BORME, Iberinform, PLACSP,
    CNMV/BME, INE/SEPE/BdE, DataComex — confirmed absent by direct grep of the ingestion
    code). Tenure of the sole/majority administrator is the closest real, defensible proxy:
    a long-serving single administrator at a family-owned (standalone) SME is the pattern
    the M&A literature associates with succession risk, even without a birth date.

    E2: the actual computation now lives in `succession_intelligence.administrator_tenure()`
    (single source of truth, also reused by the full profile) — this stays as a thin
    wrapper so nothing else in this module has to change shape.
    """
    if not cif_normalized:
        return None
    officers = await SI._officers_for(cif_normalized)
    best = SI.administrator_tenure(officers)
    if not best:
        return None
    return {"person_role": best["person_role"], "appointment_date": best["appointment_date"],
            "tenure_years": best["tenure_years"]}


async def _find_and_link(master: Dict) -> int:
    """Link unlinked BORME events to this master by exact normalized name,
    boosted by CIF-in-text or matching province (same precedence as
    `borme/matcher.py`, but persisted instead of computed on demand)."""
    legal_name = (master.get("identity") or {}).get("legal_name")
    name_norm = normalize_company_name(legal_name) if legal_name else ""
    if not name_norm:
        return 0

    cif = ((master.get("identity") or {}).get("cif") or "").strip().upper()
    provincia = ((master.get("location") or {}).get("provincia") or "").strip().upper()

    candidates = await db.borme_events.find(
        {"company_name_normalized": name_norm, "master_id": {"$exists": False}},
        {"_id": 0, "idempotency_key": 1, "event_text_raw": 1, "registry_province": 1},
    ).to_list(200)
    if not candidates:
        return 0

    ops = []
    for ev in candidates:
        confidence, method = 0.80, "name_exact"
        text = (ev.get("event_text_raw") or "").upper()
        ev_province = (ev.get("registry_province") or "").upper()
        if cif and len(cif) >= 8 and cif in text:
            confidence, method = 0.95, "cif_exact"
        elif provincia and ev_province == provincia:
            confidence = min(confidence + 0.08, 1.0)
        ops.append(UpdateOne(
            {"idempotency_key": ev["idempotency_key"]},
            {"$set": {"master_id": master["master_id"], "match_confidence": confidence,
                      "match_method": method, "linked_at": now_iso()}},
        ))
    if ops:
        await db.borme_events.bulk_write(ops, ordered=False)
    return len(ops)


async def link_events_to_master(limit_companies: int = 500) -> Dict:
    """Batch backfill entrypoint (admin endpoint / one-off job). Idempotent:
    only visits companies not yet checked (`borme_link_checked_at` watermark)."""
    await ensure_indexes()
    query = {"borme_link_checked_at": {"$exists": False}, "identity.legal_name": {"$ne": None}}
    companies_processed = 0
    events_linked = 0
    async for m in db.master_companies.find(query, {"_id": 0}).limit(limit_companies):
        events_linked += await _find_and_link(m)
        companies_processed += 1
        await db.master_companies.update_one(
            {"master_id": m["master_id"]}, {"$set": {"borme_link_checked_at": now_iso()}})
    remaining = await db.master_companies.count_documents(query)
    return {"companies_processed": companies_processed, "events_linked": events_linked,
            "companies_remaining": remaining, "bridge_version": BRIDGE_VERSION}


async def link_new_events(limit_events: int = 20000, recheck: bool = False) -> Dict:
    """Enlace POR EVENTOS: examina los eventos sin `master_id` que aún no se han mirado y los empareja con
    una empresa del Master por nombre normalizado (ver services/borme_matching.py). Idempotente y pensado
    para ejecutarse a diario: cada evento se examina una sola vez (`link_checked_at`). Con `recheck=True`
    se vuelven a examinar todos los no enlazados (p. ej. tras cargar empresas nuevas en el Master)."""
    await ensure_indexes()
    if recheck:
        await db.borme_events.update_many({"master_id": {"$exists": False}}, {"$unset": {"link_checked_at": 1}})
    events = await db.borme_events.find(
        {"master_id": {"$exists": False}, "link_checked_at": {"$exists": False}},
        {"_id": 0, "idempotency_key": 1, "company_name_normalized": 1, "registry_province": 1,
         "event_text_raw": 1},
    ).limit(limit_events).to_list(limit_events)
    keys = {name_key(e.get("company_name_normalized")) for e in events} - {None}
    masters_by_key: Dict[str, List[Dict]] = {}
    if keys:
        async for m in db.master_companies.find(
                {"name_key": {"$in": list(keys)}},
                {"_id": 0, "master_id": 1, "name_key": 1, "location.provincia": 1, "identity.cif": 1}):
            masters_by_key.setdefault(m["name_key"], []).append({
                "master_id": m["master_id"], "provincia": (m.get("location") or {}).get("provincia"),
                "cif": ((m.get("identity") or {}).get("cif") or "").strip()})
    links, stats = BM.match_events(events, masters_by_key, name_key)
    now = now_iso()
    ops = [UpdateOne({"idempotency_key": l["idempotency_key"]},
                     {"$set": {"master_id": l["master_id"], "match_confidence": l["confidence"],
                               "match_method": l["method"], "linked_at": now, "link_checked_at": now}})
           for l in links]
    linked_keys = {l["idempotency_key"] for l in links}
    ops += [UpdateOne({"idempotency_key": e["idempotency_key"]}, {"$set": {"link_checked_at": now}})
            for e in events if e["idempotency_key"] not in linked_keys]
    if ops:
        await db.borme_events.bulk_write(ops, ordered=False)
    remaining = await db.borme_events.count_documents(
        {"master_id": {"$exists": False}, "link_checked_at": {"$exists": False}})
    return {**stats, "events_remaining": remaining, "bridge_version": BRIDGE_VERSION}


async def recent_events_for_master(master_id: str) -> List[Dict]:
    return await db.borme_events.find(
        {"master_id": master_id, "publication_date": {"$gte": _cutoff_date()}}, {"_id": 0},
    ).sort("publication_date", -1).to_list(200)


def _signal(mid: str, stype: str, evidence_events: List[Dict], explanation: str,
            source_version: str, engine_version: str) -> Dict:
    meta = T.SIGNAL_TYPES[stype]
    best = max(evidence_events, key=lambda e: e.get("publication_date", ""))
    conf = _clamp01(sum(e.get("match_confidence", 0.7) for e in evidence_events) / len(evidence_events))
    persistence = _clamp01(0.3 + 0.1 * min(len(evidence_events), 5))
    boost = _recency_boost(best.get("publication_date"))
    impact = _clamp01(meta["base_impact"] + boost)
    urgency = _clamp01(meta["base_urgency"] + boost)
    raw = f"{mid}|{stype}|{source_version}|{engine_version}|{TH.THRESHOLDS_VERSION}"
    return {
        "signal_id": "sig_" + hashlib.sha256(raw.encode()).hexdigest()[:12],
        "master_id": mid, "signal_type": stype, "category": meta["category"],
        "severity": meta["severity"], "polarity": meta["polarity"],
        "dimensions": {"impact": impact, "confidence": conf, "urgency": urgency, "persistence": persistence},
        "confidence": conf, "detected_at": now_iso(), "is_composite": False,
        "source": {"engine": "borme", "fields": ["event_type", "event_subtype"],
                   "source_version": source_version, "bridge_version": BRIDGE_VERSION},
        "evidence": {"metric": "borme_event_count", "value": len(evidence_events),
                     "window": f"{LOOKBACK_MONTHS}m",
                     "events": [{"publication_date": e.get("publication_date"),
                                 "event_subtype": e.get("event_subtype"),
                                 "borme_number": e.get("borme_number"),
                                 "match_method": e.get("match_method")} for e in evidence_events[:5]]},
        "rule": {"id": stype, "expression": f"count({stype.split('.')[-1]} events, {LOOKBACK_MONTHS}m) >= 1",
                 "threshold": 1, "threshold_source": "default", "baseline": None,
                 "thresholds_version": TH.THRESHOLDS_VERSION, "passed": True},
        "recommended_actions": A.validate(meta["actions"]),
        "explanation": explanation,
        "engine_version": engine_version, "taxonomy_version": T.TAXONOMY_VERSION,
    }


def _succession_signal(mid: str, admin: Dict, threshold: float, threshold_source: str,
                        baseline: Optional[Dict], corroborating_cessations: List[Dict],
                        source_version: str, engine_version: str,
                        profile: Optional[Dict] = None) -> Dict:
    stype = "opportunity.succession_signal"
    meta = T.SIGNAL_TYPES[stype]
    exceedance = min(1.0, max(0.0, (admin["tenure_years"] - threshold) / max(threshold, 1)))
    corroborated = bool(corroborating_cessations)
    # E2: fold the richer profile into impact/confidence/urgency when available. The
    # tenure-only gate (Q1) still decides whether this signal fires at all — the profile
    # only refines the dimensions of a signal that already passed that gate.
    family = bool(profile and profile.get("family_business_probable"))
    sole_admin = bool(profile and profile.get("admin_count") == 1)
    successor = profile.get("successor_candidate") if profile else None
    stagnating = bool(profile and profile.get("financial_stagnation_signals_active"))

    impact = _clamp01(meta["base_impact"] + 0.15 * exceedance + (0.1 if corroborated else 0.0)
                       + (0.1 if stagnating else 0.0))
    # Confidence reflects real Iberinform officer-record quality (0.75) or higher if a BORME
    # cessation independently corroborates the same administrator leaving, or the wider
    # profile corroborates a family/sole-administrator structure.
    confidence = _clamp01((0.85 if corroborated else 0.75) + (0.05 if (family or sole_admin) else 0.0))
    urgency = _clamp01(meta["base_urgency"] + (0.25 if corroborated else 0.0)
                       + (0.1 if stagnating else 0.0) - (0.15 if successor else 0.0))
    raw = f"{mid}|{stype}|{source_version}|{engine_version}|{TH.THRESHOLDS_VERSION}"
    explanation = (f"{OU.role_es(admin['person_role'])} con {admin['tenure_years']} años de antigüedad "
                   f"(alta {admin['appointment_date']}, Iberinform) en empresa sin matriz ni grupo societario registrados.")
    if corroborated:
        explanation += f" Corroborado por {len(corroborating_cessations)} cese registrado en BORME."
    if profile:
        if sole_admin:
            explanation += " Administrador único (estructura no profesionalizada)."
        if family:
            explanation += f" Apellidos compartidos entre cargos (proxy): {profile['shared_surnames']}."
        if stagnating:
            explanation += " Señales financieras de estancamiento/declive activas."
        if successor:
            explanation += (f" Posible sucesor ya identificado: {successor['person_name']} "
                             f"({successor['role']}) — reduce la urgencia percibida.")
    evidence = {"metric": "administrator_tenure_years", "value": admin["tenure_years"],
                "window": "latest", "person_role": admin["person_role"],
                "appointment_date": admin["appointment_date"],
                "corroborating_borme_cessations": len(corroborating_cessations)}
    if profile:
        evidence["succession_profile"] = {
            "succession_risk_score": profile["succession_risk_score"],
            "admin_count": profile["admin_count"],
            "family_business_probable": family,
            "successor_candidate": successor,
            "company_age_years": profile.get("company_age_years"),
            "financial_stagnation_signals_active": stagnating,
            "profile_version": profile["profile_version"],
        }
    return {
        "signal_id": "sig_" + hashlib.sha256(raw.encode()).hexdigest()[:12],
        "master_id": mid, "signal_type": stype, "category": meta["category"],
        "severity": meta["severity"], "polarity": meta["polarity"],
        "dimensions": {"impact": impact, "confidence": confidence, "urgency": urgency,
                       "persistence": 0.8},
        "confidence": confidence, "detected_at": now_iso(), "is_composite": False,
        "source": {"engine": "iberinform-officers" + ("+borme" if corroborated else ""),
                   "fields": ["appointment_date", "role"],
                   "source_version": source_version, "bridge_version": BRIDGE_VERSION},
        "evidence": evidence,
        "rule": {"id": stype, "expression": "administrator_tenure_years >= threshold",
                 "threshold": threshold, "threshold_source": threshold_source, "baseline": baseline,
                 "thresholds_version": TH.THRESHOLDS_VERSION, "passed": True},
        "recommended_actions": A.validate(meta["actions"]),
        "explanation": explanation,
        "engine_version": engine_version, "taxonomy_version": T.TAXONOMY_VERSION,
    }


async def evaluate(master: Dict, source_version: str, engine_version: str) -> List[Dict]:
    """Called from `engine.py::analyze()`. Links (once) then emits BORME-sourced signals."""
    mid = master["master_id"]
    if not master.get("borme_link_checked_at"):
        await _find_and_link(master)
        await db.master_companies.update_one(
            {"master_id": mid}, {"$set": {"borme_link_checked_at": now_iso()}})

    events = await recent_events_for_master(mid)
    gov = [e for e in events if e.get("event_subtype") in GOVERNANCE_SUBTYPES]
    cap = [e for e in events if e.get("event_subtype") in CAPITAL_SUBTYPES]
    diss = [e for e in events if e.get("event_subtype") in DISSOLUTION_SUBTYPES]
    cessations = [e for e in gov if e.get("event_subtype") == "cessation"]

    out: List[Dict] = []
    if events:
        out.append(_signal(mid, "corporate.borme_event", events,
            f"{len(events)} evento(s) BORME en los últimos {LOOKBACK_MONTHS} meses.",
            source_version, engine_version))

    if gov:
        out.append(_signal(mid, "corporate.governance_change", gov,
            f"{len(gov)} cambio(s) de administradores/apoderados en BORME (altas, ceses o reelecciones).",
            source_version, engine_version))
    if cap:
        out.append(_signal(mid, "corporate.capital_movement", cap,
            f"{len(cap)} movimiento(s) de capital social en BORME.",
            source_version, engine_version))
    if diss:
        out.append(_signal(mid, "risk.dissolution_signal", diss,
            "Evento de disolución, liquidación, extinción o concurso registrado en BORME.",
            source_version, engine_version))
    own = master.get("ownership") or {}
    is_standalone = not (own.get("parents") or own.get("group_id"))
    if is_standalone:
        # Puerta endurecida (ver services/opportunity_criteria.py y officer_utils.succession_gate):
        # tamaño >= suelo de ingresos, administrador único y antigüedad >= 25 años (o el umbral
        # configurado si es mayor). Antes bastaba con 15 años, y ni roles en inglés ni fechas
        # DDMONYYYY se reconocían, por lo que casi nunca se activaba.
        officers = await SI._officers_for(master.get("cif_normalized"))
        thr, thr_src, thr_base = await TH.resolve("opportunity.succession_signal")
        revenue = ((master.get("financials") or {}).get("latest") or {}).get("revenue")
        gate = OU.succession_gate(officers, revenue,
                                  min_revenue=CR.configured_min_revenue()[0],
                                  min_tenure_years=CR.SUCCESSION_MIN_TENURE_YEARS,
                                  base_threshold=thr)
        if gate["passed"]:
            a = gate["admin"]
            admin = {"person_role": a["person_role"], "appointment_date": a["appointment_date"],
                     "tenure_years": a["tenure_years"]}
            # E2: enriquece con el perfil completo; nunca bloquea la señal.
            profile = await SI.build_profile(master)
            out.append(_succession_signal(mid, admin, gate["threshold"], thr_src, thr_base, cessations,
                                           source_version, engine_version, profile=profile))
    return out
