"""Lectura de cargos (`norm_officers`) y puerta de la señal de sucesión. Funciones puras, sin base de datos.

Por qué existe: Iberinform entrega los cargos con roles EN INGLÉS ("Sole Director", "Joint And Several
Director"…) y las fechas de nombramiento casi siempre como `27AUG2020` (solo unas pocas como `dd/mm/yyyy`).
El motor de sucesión buscaba "ADMINISTRADOR" y solo entendía `dd/mm/yyyy`, así que veía 4 de 88.122 filas
y generaba 1 señal en 25.603 empresas. La ficha ya lo corrigió en su día (`company_ficha.py`); esto es la
misma lectura, compartida.
"""

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_RE_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_RE_MON = re.compile(r"^(\d{2})([A-Za-z]{3})(\d{4})$")

# Rol de Iberinform (inglés) -> español. Fuente única; la ficha lo importa de aquí.
ROLE_ES = {
    "Representative": "Representante",
    "Sole Director": "Administrador único",
    "Joint And Several Director": "Administrador solidario",
    "Director": "Consejero",
    "Joint Director": "Administrador mancomunado",
    "Chairperson": "Presidente",
    "Secretary": "Secretario",
    "Auditor": "Auditor de cuentas",
    "Director Member": "Vocal del consejo",
    "Joint And Several Chief Executive Officer": "Consejero delegado solidario",
    "Chief Executive Officer": "Consejero delegado",
    "Delegate Joint Director": "Consejero delegado mancomunado",
    "Joint And Several Representative": "Representante solidario",
    "Controlling Committee Member": "Miembro de la comisión de control",
    "Member": "Vocal",
    "Member Of The Committee": "Miembro de la comisión",
    "Vice-Chairperson": "Vicepresidente",
    "Member Of The Controlling Committee": "Miembro de la comisión de control",
    "Accounts Auditor": "Auditor de cuentas",
    "Committee Member": "Miembro de la comisión",
    "Professional Partner": "Socio profesional",
    "Bankruptcy Administrator": "Administrador concursal",
    "Non-Director Secretary": "Secretario no consejero",
    "Representative Art. 143 Rrm": "Representante (art. 143 RRM)",
    "Partner": "Socio",
    "Joint Representative": "Representante mancomunado",
    "Depositary Entity": "Entidad depositaria",
    "Managing Entity": "Entidad gestora",
    "Alternate Auditor": "Auditor suplente",
    "Vice-Secretary": "Vicesecretario",
    "Liquidator": "Liquidador",
    "Manager": "Gerente",
    "Sole Shareholder": "Socio único",
    "Joint Accounts Auditor": "Auditor de cuentas conjunto",
    "Committee Chairperson": "Presidente de la comisión",
    "Joint And Joint And Several Delegate Director": "Consejero delegado mancomunado y solidario",
    "Member Of The Board": "Vocal del consejo",
    "Sole Chief Executive Officer": "Consejero delegado único",
    "Supervisor": "Supervisor",
    "Non-Director Vice-Secretary": "Vicesecretario no consejero",
    "Director Secretary": "Consejero secretario",
    "Alternate Director": "Consejero suplente",
    "Secretary To The Controlling Committee": "Secretario de la comisión de control",
    "Depositary": "Depositario",
    "Chairperson Of The Controlling Committee": "Presidente de la comisión de control",
    "Advisor": "Asesor",
    "Alternate": "Suplente",
    "Attorney": "Apoderado",
    "Vice-Chairperson Of The Board": "Vicepresidente del consejo",
    "Chairperson Of The Board": "Presidente del consejo",
    "Chairperson Of The Board Of Directors": "Presidente del consejo de administración",
    "Board Of Directors' Member": "Vocal del consejo de administración",
    "Board": "Consejo de administración",
    "Treasurer": "Tesorero",
    "Accountant": "Contador",

    # HARDENING · traducción 134 roles ingleses sin mapear (Daniel 2026-09-09):
    # de los 192 valores distintos de `role` en `norm_officers`, estos 134 no
    # tenían traducción y se mostraban en inglés crudo en la UI. R15: solo se
    # traduce un valor real ya existente, terminología de derecho societario
    # español — no se inventa ningún dato.
    "Member Of The Board Of Directors": "Miembro del Consejo de Dirección",
    "Committee Secretary": "Secretario del Comité",
    "Commissioner Member": "Miembro de la Comisión",
    "Member Of The Shareholders' Meeting": "Miembro de la Junta de Socios/Accionistas",
    "Alternate Accounts Auditor": "Auditor de Cuentas Suplente",
    "Joint And Several Liquidator": "Liquidador Solidario",
    "Secretary To The Committee": "Secretario del Comité",
    "Delegate": "Delegado",
    "Participants' Advocate": "Defensor del Partícipe",
    "Joint And Joint And Several Representative": "Representante Mancomunado y Solidario",
    "Accounting Register": "Registro Contable",
    "Suspension Of Payments Supervisor": "Interventor de la Suspensión de Pagos",
    "Developer": "Promotor",
    "Member Of The Executive Committee": "Miembro de la Comisión Ejecutiva",
    "Legal Counsel": "Asesor Jurídico",
    "Commissioner": "Comisionado",
    "Permanent Representative": "Representante Permanente",
    "Alternate Controlling Commissioner": "Interventor de Control Suplente",
    "Commission": "Comisión",
    "Officer": "Apoderado",
    "Group Accounts Auditor": "Auditor de Cuentas del Grupo",
    "Bankruptcy Administrator Representative": "Representante del Administrador Concursal",
    "Vice-Chairperson Of The Controlling Committee": "Vicepresidente del Comité de Control",
    "Member Of The Governing Council": "Miembro del Consejo Rector",
    "Creditor Commissioner": "Comisionado de Acreedores",
    "Delegate Commissioner Member": "Miembro Comisionado Delegado",
    "Judicial Director": "Administrador Judicial",
    "Principal Auditor": "Auditor Principal",
    "Member Of The Rector Committee": "Miembro del Comité Rector",
    "Vice-Chairperson Of The Board Of Directors": "Vicepresidente del Consejo de Administración",
    "Permanent Commissioner": "Comisionado Permanente",
    "Vice-Chairperson Of The Committee": "Vicepresidente del Comité",
    "Risk Committee Member": "Miembro del Comité de Riesgos",
    "Alternate Joint Director": "Administrador Mancomunado Suplente",
    "Secretary To The Board Of Directors": "Secretario del Consejo de Administración",
    "Secretary To The Board": "Secretario del Consejo",
    "Member Of The Audit Committee": "Miembro del Comité de Auditoría",
    "Executive Committee Member": "Miembro de la Comisión Ejecutiva",
    "Creditors? Commission": "Comisión de Acreedores",
    "Bankruptcy Liquidator": "Liquidador Concursal",
    "Sole Manager": "Gerente Único",
    "Joint Liquidator": "Liquidador Mancomunado",
    "Executive Commissioner": "Comisionado Ejecutivo",
    "Controlling Committee": "Comité de Control",
    "Vice-Secretary To The Board Of Directors": "Vicesecretario del Consejo de Administración",
    "Sole Liquidator": "Liquidador Único",
    "Member Of The Liquidation Committee": "Miembro de la Comisión Liquidadora",
    "Liquidation Commissioner": "Comisionado de Liquidación",
    "Judicial Supervisor": "Interventor Judicial",
    "General Director": "Director General",
    "Commissioner Secretary": "Secretario Comisionado",
    "Bankruptcy Commissioner": "Comisionado Concursal",
    "Second Vice-Chairperson": "Segundo Vicepresidente",
    "Salesperson": "Comercial",
    "Managing Director": "Director Gerente",
    "Founder": "Fundador",
    "Commissioner Chairperson": "Presidente Comisionado",
    "Chairperson Of The Shareholders' Meeting": "Presidente de la Junta de Socios/Accionistas",
    "Bankruptcy Depositary": "Depositario Concursal",
    "Vice-Secretary To The Board": "Vicesecretario del Consejo",
    "Unspecified Director": "Administrador sin Especificar",
    "Risk Commissioner": "Comisionado de Riesgos",
    "Rector Chief Executive Officer": "Director Ejecutivo del Consejo Rector",
    "Monitoring Commissioner": "Comisionado de Seguimiento",
    "First Vice-Chairperson": "Primer Vicepresidente",
    "Controlling Committee Chairperson": "Presidente del Comité de Control",
    "Controlling Commission": "Comisión de Control",
    "Branch Representative": "Representante de Sucursal",
    "Alternate Member": "Vocal Suplente",
    "Vice-Secretary To The Controlling Committee": "Vicesecretario del Comité de Control",
    "Vice-Commissioner": "Vicecomisionado",
    "Syndicated Bondholders Commissioner": "Comisario del Sindicato de Obligacionistas",
    "Secretary To The Shareholders' Meeting": "Secretario de la Junta de Socios/Accionistas",
    "Monitoring Commissioner Secretary": "Secretario de la Comisión de Seguimiento",
    "Member Of The Management Committee": "Miembro del Comité de Dirección",
    "Liquidation Commissioner Member": "Miembro Comisionado de Liquidación",
    "Legal Advisor": "Asesor Legal",
    "Executive Commissioner Member": "Miembro Comisionado Ejecutivo",
    "Executive Chairperson": "Presidente Ejecutivo",
    "Chairperson Of The Executive Committee": "Presidente de la Comisión Ejecutiva",
    "Board Of Directors' Treasurer": "Tesorero del Consejo de Administración",
    "Alternate Joint And Several Director": "Administrador Solidario Suplente",
    "Vice-Secretary To The Committee": "Vicesecretario del Comité",
    "Vice-Secretary Of The Controlling Committee": "Vicesecretario del Comité de Control",
    "Secretary To The Rector Committee": "Secretario del Comité Rector",
    "Secretary To The Governing Council": "Secretario del Consejo Rector",
    "Secretary To The Executive Committee": "Secretario de la Comisión Ejecutiva",
    "Rector Commission": "Comisión Rectora",
    "Recovery Committee": "Comité de Recuperación",
    "Oversight Commissioner": "Comisionado de Supervisión",
    "Non-Director Vice-Chairperson": "Vicepresidente No Consejero",
    "Monitoring Commissioner Chairperson": "Presidente de la Comisión de Seguimiento",
    "Managing Committee Member": "Miembro del Comité de Dirección",
    "Honorary Chairperson": "Presidente Honorario",
    "General Secretary": "Secretario General",
    "Committee": "Comité",
    "Board Of Directors' Accountant": "Contable del Consejo de Administración",
    "Alternate Rector Commission": "Comisión Rectora Suplente",
    "Alternate Joint Accounts Auditor": "Auditor de Cuentas Mancomunado Suplente",
    "Alternate Commissioner": "Comisionado Suplente",
    "Vice-Chairperson Of The Executive Committee": "Vicepresidente de la Comisión Ejecutiva",
    "Second Member": "Segundo Vocal",
    "General Chairperson": "Presidente General",
    "First Member": "Primer Vocal",
    "Chairperson Of The Governing Council": "Presidente del Consejo Rector",
    "Chairperson Of The Audit Committee": "Presidente del Comité de Auditoría",
    "Audit Committee Chairperson": "Presidente del Comité de Auditoría",
    "Audit Commission": "Comisión de Auditoría",
    "Assistant Senior Manager": "Subdirector",
    "Assistant Chief Executive Officer": "Consejero Delegado Adjunto",
    "Vice-Chairperson Of The Rector Committee": "Vicepresidente del Comité Rector",
    "Technical Personnel": "Personal Técnico",
    "Tax Representative": "Representante Fiscal",
    "Syndicated Bondholders Secretary": "Secretario del Sindicato de Obligacionistas",
    "Secretary To The Management Committee": "Secretario del Comité de Dirección",
    "Secretary To The Audit Committee": "Secretario del Comité de Auditoría",
    "Secretary Director": "Consejero Secretario",
    "Second Vice-Secretary": "Segundo Vicesecretario",
    "Provisional Director": "Administrador Provisional",
    "Principal Accounts Auditor": "Auditor de Cuentas Principal",
    "Manager Partner": "Socio Gerente",
    "Intervention Mediator": "Mediador de Intervención",
    "General Representative": "Representante General",
    "Executive Vice-Chairperson": "Vicepresidente Ejecutivo",
    "Executive Committee Chairperson": "Presidente de la Comisión Ejecutiva",
    "Director Chairperson": "Presidente Consejero",
    "Delegate Bankruptcy Assistant": "Auxiliar Delegado Concursal",
    "Chief Director": "Director Jefe",
    "Chairperson Of The Rector Committee": "Presidente del Comité Rector",
    "Chairperson Of The Managing Committee": "Presidente del Comité de Dirección",
    "Chairperson Of The Liquidation Committee": "Presidente de la Comisión Liquidadora",
    "Branch Officer": "Apoderado de Sucursal",
    "Bondholders Commissioner": "Comisario de Obligacionistas",
    "Alternate Representative": "Representante Suplente",
}


def role_es(role: Optional[str]) -> Optional[str]:
    """Rol en español (mapa compartido con la ficha); si no está mapeado, se devuelve tal cual."""
    if not role:
        return None
    return ROLE_ES.get(role) or ROLE_ES.get(role.strip()) or role


# Administradores en el sentido de "quién manda": único, solidario y mancomunado (no consejeros ni cargos).
_ENGLISH_ADMIN_ROLES = frozenset({"sole director", "joint and several director", "joint director"})
_ENGLISH_SOLE_ROLES = frozenset({"sole director"})

NON_PERSON_HINTS = ("SL", "SA", "SLU", "SCP", "SC", "SCOOP", "SL.", "SA.")


def _ymd(raw: Optional[str]) -> Optional[Tuple[int, int, int]]:
    """(año, mes, día) a partir de `dd/mm/yyyy` o `DDMONYYYY`; None si no se reconoce. Sin validar calendario."""
    if not raw:
        return None
    raw = raw.strip()
    m = _RE_SLASH.match(raw)
    if m:
        d, mo, y = m.groups()
        return int(y), int(mo), int(d)
    m = _RE_MON.match(raw)
    if m:
        d, mon, y = m.groups()
        month = _MONTHS.get(mon.upper())
        if month:
            return int(y), month, int(d)
    return None


def officer_date_iso(raw: Optional[str]) -> Optional[str]:
    """`YYYY-MM-DD` a partir de un valor real; None si el formato no se reconoce (no inventa nada)."""
    ymd = _ymd(raw)
    return f"{ymd[0]}-{ymd[1]:02d}-{ymd[2]:02d}" if ymd else None


def parse_officer_date(raw: Optional[str]) -> Optional[datetime]:
    """Fecha (UTC) o None si no se reconoce o no es una fecha de calendario válida."""
    ymd = _ymd(raw)
    if not ymd:
        return None
    try:
        return datetime(ymd[0], ymd[1], ymd[2], tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_borme_date(raw: Optional[str]) -> Optional[datetime]:
    """`publication_date` de los eventos BORME: el formato real es `YYYYMMDD` (p. ej. 20260723); también
    se acepta `YYYY-MM-DD`. Antes el motor solo leía el segundo y por eso la ventana de 24 meses, el
    refuerzo por recencia y la antigüedad de la empresa no funcionaban."""
    raw = (raw or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def is_administrator_role(role: Optional[str]) -> bool:
    r = (role or "").strip().lower()
    if r in _ENGLISH_ADMIN_ROLES:
        return True
    return "administrador" in r and "concursal" not in r   # el administrador concursal no gobierna la empresa


def is_sole_administrator_role(role: Optional[str]) -> bool:
    r = (role or "").strip().lower()
    if r in _ENGLISH_SOLE_ROLES:
        return True
    return "administrador" in r and ("único" in r or "unico" in r)


def looks_like_person(name: Optional[str]) -> bool:
    if not name:
        return False
    tokens = name.strip().split()
    if len(tokens) < 2:
        return False   # una sola palabra suele ser una sigla societaria, no una persona
    if any(t.rstrip(".").upper() in NON_PERSON_HINTS for t in tokens):
        return False
    return True


def admin_count(officers: List[Dict]) -> int:
    return len({o.get("person_name") for o in officers
                if is_administrator_role(o.get("role")) and o.get("person_name")})


def administrator_tenure(officers: List[Dict], now: Optional[datetime] = None) -> Optional[Dict]:
    """Administrador persona física con más antigüedad (fecha de nombramiento reconocible)."""
    now = now or datetime.now(timezone.utc)
    best = None
    for o in officers:
        if not (is_administrator_role(o.get("role")) and looks_like_person(o.get("person_name"))):
            continue
        d = parse_officer_date(o.get("appointment_date"))
        if not d:
            continue
        tenure_years = round((now - d).days / 365.25, 1)
        if best is None or tenure_years > best["tenure_years"]:
            best = {"person_name": o.get("person_name"), "person_role": o.get("role"),
                    "appointment_date": o.get("appointment_date"), "tenure_years": tenure_years,
                    "_appointment_dt": d}
    return best


def succession_gate(officers: List[Dict], revenue: Optional[float], *, min_revenue: float,
                    min_tenure_years: float, base_threshold: Optional[float] = None,
                    now: Optional[datetime] = None) -> Dict:
    """¿Genera la empresa una señal de sucesión? Todas las condiciones a la vez:
    tamaño >= suelo, administrador único (una sola persona con cargo de administrador) y antigüedad
    >= el mayor entre el umbral configurado y el mínimo de criterio. `reason` explica el descarte."""
    threshold = max(float(base_threshold or 0), float(min_tenure_years))
    if not isinstance(revenue, (int, float)) or isinstance(revenue, bool) or revenue < min_revenue:
        return {"passed": False, "reason": "below_size_floor", "admin": None, "threshold": threshold}
    admin = administrator_tenure(officers, now)
    if not admin:
        return {"passed": False, "reason": "no_administrator", "admin": None, "threshold": threshold}
    if admin_count(officers) != 1 or not is_sole_administrator_role(admin["person_role"]):
        return {"passed": False, "reason": "not_sole_administrator", "admin": admin, "threshold": threshold}
    if admin["tenure_years"] < threshold:
        return {"passed": False, "reason": "tenure_below_threshold", "admin": admin, "threshold": threshold}
    return {"passed": True, "reason": None, "admin": admin, "threshold": threshold}
