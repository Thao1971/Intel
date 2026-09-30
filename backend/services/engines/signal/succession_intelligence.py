"""Succession Intelligence (E2 — full capability, builds on Q1's single tenure signal).

Q1 (`borme_bridge.py`) already emits `opportunity.succession_signal` from ONE real proxy:
administrator tenure (Iberinform `norm_officers.appointment_date`). That gate is left
UNCHANGED here — still calibration-pending, still the thing that decides whether the
signal fires at all. E2 adds a richer, read-only PROFILE around that gate, built only
from data confirmed to exist by direct inspection of the ingestion code before writing
this module. It still does NOT use officer age/birth date — that field does not exist
in BORME, Iberinform, PLACSP, CNMV/BME, INE/SEPE/BdE or DataComex.

Four real, additive dimensions, all reusing already-ingested fields/collections:

1. Governance concentration (`admin_count`): distinct people holding an
   "Administrador*" role (`norm_officers.role`, free text) — a sole administrator is
   the classic non-professionalized family-SME structure; a board is not.
2. Family-surname overlap (`family_business_probable`): a cautious heuristic over
   `norm_officers.person_name` (Spanish two-surname convention). Explicitly reported
   as a PROXY, never as confirmed kinship — denylisted for obvious non-person entries
   (e.g. "ESTYOFI") and requires >=2 tokens so it doesn't fire on corporate shorthand.
3. Successor-candidate detection (`successor_candidate`): a non-administrator officer
   appointed materially (>=2y) later than the administrator. Read as "someone may
   already be stepping in" — this REDUCES urgency, it doesn't disqualify the lead;
   a structured succession already in motion is often an easier deal to originate
   than an unplanned one.
4. Company age (`company_age_years`, optional): from a linked BORME `constitution`
   event (`event_subtype="constitution"`, already parsed/classified by
   `borme/parser.py`, never previously used for anything). Many companies predate
   digitized BORME coverage, so its absence is not penalized.

Financial trajectory is READ, never recomputed: `db.signals` already holds the Signal
Engine's own `risk.sustained_decline` / `financial.margin_weak` output, so correlating
"aging administrator + declining business" here just cross-references that, instead of
re-deriving financial math this module has no business owning.

Output is a `succession_risk_score` (0-100), rules-based and fully explainable (no ML,
same convention as every other engine in this codebase) — provisional weights, tagged
`succession-v1`, calibration deferred exactly like `thresholds.THRESHOLDS_VERSION`.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from database import db
from services import officer_utils as OU

SUCCESSION_PROFILE_VERSION = "succession-v1"

ADMIN_ROLE_KEYWORDS = ("ADMINISTRADOR",)  # same convention as borme_bridge.py
NON_PERSON_HINTS = ("SL", "SA", "SLU", "SCP", "SC", "SCOOP", "SL.", "SA.")
PARTICLES = {"DE", "DEL", "LA", "LOS", "LAS", "Y"}
MIN_SUCCESSOR_GAP_YEARS = 2.0


def _parse_date(raw: Optional[str]) -> Optional[datetime]:
    # Antes solo entendía dd/mm/yyyy (4 de 88.122 filas): ahora también DDMONYYYY, el formato real.
    return OU.parse_officer_date(raw)


async def _officers_for(cif_normalized: Optional[str]) -> List[Dict]:
    if not cif_normalized:
        return []
    return await db.norm_officers.find(
        {"cif_normalized": cif_normalized}, {"_id": 0, "person_name": 1, "role": 1, "appointment_date": 1},
    ).to_list(100)


def administrator_tenure(officers: List[Dict]) -> Optional[Dict]:
    """Antigüedad del administrador persona física más antiguo. Lógica en `officer_utils` (roles en
    inglés y español, fechas dd/mm/yyyy y DDMONYYYY); se mantiene aquí como punto de entrada estable."""
    return OU.administrator_tenure(officers)


def _admin_count(officers: List[Dict]) -> int:
    return OU.admin_count(officers)


def _looks_like_person(name: Optional[str]) -> bool:
    return OU.looks_like_person(name)


def _surname_tokens(name: str) -> List[str]:
    """Best-effort Spanish surname extraction: last one or two non-particle tokens.
    Spanish full names are typically "Nombre Apellido1 Apellido2" (>=3 tokens once a
    given name is present) -> take the last TWO tokens as the two surnames. Only a
    bare 2-token name ("Nombre Apellido") yields a single surname. Deliberately
    conservative — under-matching is safer than over-claiming kinship."""
    tokens = [t for t in name.strip().split() if t.upper() not in PARTICLES]
    if len(tokens) < 2:
        return []
    return [tokens[-1]] if len(tokens) == 2 else tokens[-2:]


def _family_overlap(officers: List[Dict]) -> Tuple[bool, List[str]]:
    persons = {o.get("person_name") for o in officers if _looks_like_person(o.get("person_name"))}
    surname_map: Dict[str, set] = {}
    for p in persons:
        for s in _surname_tokens(p):
            surname_map.setdefault(s, set()).add(p)
    shared = sorted(s for s, people in surname_map.items() if len(people) >= 2)
    return bool(shared), shared


def _successor_candidate(officers: List[Dict], admin_appointment: Optional[datetime]) -> Optional[Dict]:
    if not admin_appointment:
        return None
    best = None
    for o in officers:
        role = (o.get("role") or "").upper()
        if OU.is_administrator_role(o.get("role")):
            continue  # only a non-administrator role counts as a "successor candidate"
        d = _parse_date(o.get("appointment_date"))
        if not d or d <= admin_appointment:
            continue
        years_after = (d - admin_appointment).days / 365.25
        if years_after < MIN_SUCCESSOR_GAP_YEARS:
            continue
        if best is None or d > best["_d"]:
            best = {"person_name": o.get("person_name"), "role": o.get("role"),
                    "appointment_date": o.get("appointment_date"), "_d": d}
    if best:
        best.pop("_d")
    return best


async def _company_age_years(master_id: Optional[str]) -> Optional[float]:
    if not master_id:
        return None
    ev = await db.borme_events.find_one(
        {"master_id": master_id, "event_subtype": "constitution"},
        {"_id": 0, "publication_date": 1}, sort=[("publication_date", 1)],
    )
    if not ev or not ev.get("publication_date"):
        return None
    d = OU.parse_borme_date(ev["publication_date"])   # YYYYMMDD real (antes solo se leía YYYY-MM-DD)
    if d is None:
        return None
    return round((datetime.now(timezone.utc) - d).days / 365.25, 1)


async def _financial_stagnation(master_id: Optional[str]) -> bool:
    if not master_id:
        return False
    sig = await db.signals.find_one(
        {"master_id": master_id,
         "signal_type": {"$in": ["risk.sustained_decline", "financial.margin_weak"]},
         "status": "active"}, {"_id": 0, "signal_type": 1},
    )
    return bool(sig)


async def build_profile(master: Dict) -> Optional[Dict]:
    """Full Succession Intelligence profile — richer than Q1's pass/fail signal.
    Returns None if there's no administrator with a parseable appointment date
    (nothing real to assess, never fabricated)."""
    cif = master.get("cif_normalized")
    officers = await _officers_for(cif)
    if not officers:
        return None

    admin = administrator_tenure(officers)
    if not admin:
        return None

    admin_count = _admin_count(officers)
    family_overlap, shared_surnames = _family_overlap(officers)
    successor = _successor_candidate(officers, admin["_appointment_dt"])
    age_years = await _company_age_years(master.get("master_id"))
    stagnating = await _financial_stagnation(master.get("master_id"))
    own = master.get("ownership") or {}
    standalone = not (own.get("parents") or own.get("group_id"))
    tenure_years = admin["tenure_years"]

    score = 0
    reasons: List[str] = []
    if tenure_years >= 15:
        score += 30
        reasons.append(f"administrador con {tenure_years} años de antigüedad (>=15)")
    elif tenure_years >= 8:
        score += 15
        reasons.append(f"administrador con {tenure_years} años de antigüedad (>=8)")
    if admin_count == 1:
        score += 20
        reasons.append("administrador único (estructura no profesionalizada)")
    if standalone:
        score += 15
        reasons.append("empresa sin matriz ni grupo societario registrados (Q2)")
    if family_overlap:
        score += 15
        reasons.append(f"apellidos compartidos entre cargos (proxy, no confirma parentesco): {shared_surnames}")
    if stagnating:
        score += 10
        reasons.append("señales financieras de estancamiento/declive activas (Signal Engine)")
    if age_years is not None and tenure_years > 0 and age_years >= tenure_years * 0.9:
        score += 10
        reasons.append(f"antigüedad de empresa ({age_years} años, evento BORME de constitución) "
                        f"próxima a la del administrador")
    if successor:
        score -= 20
        reasons.append(f"posible sucesor ya identificado: {successor['person_name']} "
                        f"({successor['role']}, alta {successor['appointment_date']}) — reduce urgencia")
    score = max(0, min(100, score))

    return {
        "master_id": master.get("master_id"), "cif_normalized": cif,
        "administrator": {"person_name": admin.get("person_name"), "role": admin.get("person_role"),
                           "appointment_date": admin.get("appointment_date"), "tenure_years": tenure_years},
        "admin_count": admin_count,
        "family_business_probable": family_overlap, "shared_surnames": shared_surnames,
        "successor_candidate": successor,
        "company_age_years": age_years,
        "financial_stagnation_signals_active": stagnating,
        "standalone": standalone,
        "succession_risk_score": score,
        "reasons": reasons,
        "profile_version": SUCCESSION_PROFILE_VERSION,
        "data_caveat": ("Proxy basado en antigüedad de administrador (Iberinform) y apellidos "
                        "compartidos entre cargos (heurística, no confirma parentesco real). "
                        "No existe edad ni fecha de nacimiento en ninguna fuente conectada "
                        "(BORME, Iberinform, PLACSP, CNMV/BME, INE/SEPE/BdE, DataComex)."),
    }
