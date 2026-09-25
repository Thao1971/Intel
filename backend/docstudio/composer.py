"""Document Composer — Assembles documents from the MODERN intelligence layer + AI.

Fase 2 (DOCUMENT_STUDIO_UNIFICATION_PLAN): company documents are composed from
`docstudio/data_access.py` (real Financial + Signal engines over `master_companies`),
NOT the legacy `companies_master`/`iberinform_financials`. Sector context still comes
from Economic/Sector Intelligence. Narrative = Claude. Valuation = the real engine's
honest `valuation()` (market_observed vs inferred_reference), never a heuristic.
"""

import logging
from typing import Dict, Optional
from database import db
from models import now_iso
from docstudio import (
    new_document, new_section, cover_block, text_block, kpi_block,
    table_block, chart_block, insight_block, divider_block, ownership_block, orgchart_block,
    deal_snapshot_block,
)
from docstudio.model_provider import generate_summary
from docstudio import data_access as DA
from docstudio import financial_enrich as FE
from services.cnae_catalog import resolve_cnae_label


async def _enriched_financial_blocks(bundle: Dict) -> list:
    """Curated financial detail (ratios table + multi-year + quality/percentile KPIs)
    followed by the sector positioning table (our own percentiles). Honest: each helper
    returns nothing when its data isn't available."""
    blocks = FE.financial_detail_blocks(bundle)
    sector = await FE.sector_positioning_block(db, bundle)
    if sector:
        blocks.append(sector)
    return blocks

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════
# BLOCK HELPERS from the modern intelligence bundle (Fase 2)
# Build blocks from data_access.company_intelligence() — real Financial + Signal
# engines over master_companies. No legacy companies_master / financial_engine.py.
# ══════════════════════════════════════════

_FIN = "financial-intelligence-v1"

# Display label of the advisor = the active platform brand (2-layer brand model).
_ADVISOR_LABELS = {"brand_bud": "bud Advisors", "brand_arroba": "arroba.com",
                   "brand_cis": "CIS", "brand_valuo": "Valuo.pro"}


def _advisor_label(brand_id: str) -> str:
    return _ADVISOR_LABELS.get(brand_id or "brand_bud", "bud Advisors")


def _es(s: str) -> str:
    """Formato contable español: cambia una cadena numérica inglesa (1,234.5) a española (1.234,5)."""
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _eur(n) -> str:
    """Importe en formato español (separador de miles con punto): 7.734.205 €."""
    if n is None:
        return "N/D"
    return f"{n:,.0f}".replace(",", ".") + " €"


def _pct(v, dec: int = 1, signed: bool = False) -> str:
    """Porcentaje en formato español (decimal con coma): 14,6 % · +31,9 %."""
    if v is None:
        return "N/D"
    fmt = f"{{:+.{dec}f}}" if signed else f"{{:.{dec}f}}"
    return fmt.format(v * 100).replace(".", ",") + " %"


def _pp(v) -> str:
    """Diferencia en puntos porcentuales: +1,4 pp."""
    return f"{v*100:+.1f}".replace(".", ",") + " pp"


def _smart_case(text: str, mid_sentence: bool = False) -> str:
    """Normaliza texto que Iberinform guarda en MAYÚSCULAS a caja de frase legible.
    (No restaura tildes ausentes en la fuente; eso no se inventa.)"""
    if not text:
        return text
    letters = [c for c in text if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7:
        t = text.lower()
        return t if mid_sentence else (t[:1].upper() + t[1:])
    return text


async def _semantic_profile(master_id: str):
    """Perfil semántico (objeto social -> actividad/capacidades/propuesta de valor).
    Devuelve (semantic_profile, summary_text). Nunca lanza: ({}, None) si falla."""
    try:
        from services.engines.semantic import engine as _sem
        sem = await _sem.build_profile(master_id, enrich=False, persist=False)
        return (sem or {}).get("semantic_profile") or {}, (sem or {}).get("semantic_summary", {}).get("text")
    except Exception:
        return {}, None


def _exec_description(ident: Dict, prof: Dict, bundle: Dict, ai_summary: str, web_desc: str = None) -> str:
    """Descripción de la compañía para el resumen ejecutivo: combina la narrativa de la IA
    (si hay) con la web corporativa (scraper) / el objeto social del Motor Semántico y una
    foto financiera. Multi-frase, todo desde dato real."""
    kpis = bundle.get("kpis", {}) or {}
    year = (bundle.get("statements") or {}).get("year")
    emp = (bundle.get("statements") or {}).get("employees")
    sents = []
    if ai_summary and ai_summary.strip():
        sents.append(ai_summary.strip())
    # Actividad: prioridad web corporativa > actividades del objeto social > objeto social
    caps = [_smart_case(c.get("value"), mid_sentence=True) for c in (prof.get("capabilities") or [])
            if isinstance(c, dict) and c.get("value")]
    obj = ident.get("objeto_social")
    if web_desc and web_desc.strip():
        w = web_desc.strip()
        sents.append(w if w.endswith((".", "…")) else w + ".")
    elif caps:
        if len(caps) > 1:
            sents.append(f"Su actividad abarca {', '.join(caps[:-1])} y {caps[-1]}.")
        else:
            sents.append(f"Su actividad se centra en {caps[0]}.")
    elif obj:
        oc = _smart_case(obj.strip())
        sents.append(oc if oc.endswith(".") else oc + ".")
    loc = ident.get("municipio") or ident.get("provincia")
    bits = []
    if loc:
        bits.append(f"con sede en {loc}")
    if emp:
        bits.append(f"un equipo de {emp} personas")
    if bits:
        sents.append("La compañía opera " + " y ".join(bits) + ".")
    rev, m, g = kpis.get("revenue"), kpis.get("ebitda_margin"), kpis.get("revenue_growth_yoy")
    if rev:
        fin = f"En {year} registró una facturación de {_eur(rev)}" if year else f"Registró una facturación de {_eur(rev)}"
        if m is not None:
            fin += f", con un margen EBITDA del {_pct(m)}"
        if g is not None:
            fin += f" y un crecimiento del {_pct(g, 1, signed=True)} interanual"
        sents.append(fin + ".")
    return " ".join(sents)


_MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _month_year_es() -> str:
    import datetime
    n = datetime.datetime.now()
    return f"{_MESES_ES[n.month - 1].capitalize()} {n.year}"


def _disclaimer_paragraphs(advisor: str, company: str) -> list:
    """Cláusula de confidencialidad estándar (plantilla real BUD), con el nombre del
    Asesor y de la Compañía sustituidos. Editable por el asesor en el editor."""
    a, c = advisor, company
    return [
        f"{a}, S.L. (en adelante, «{a}» o «el Asesor Financiero») ha sido contratado con carácter "
        f"exclusivo como asesor financiero para el análisis de diferentes alternativas estratégicas "
        f"relacionadas con la evolución futura de {c} (en adelante, «la Compañía»). Dicho análisis "
        f"podría derivar, entre otras opciones, en la entrada de un posible comprador en el accionariado "
        f"mediante la adquisición total o parcial de las participaciones sociales (en adelante, la "
        f"«Transacción») por parte de los actuales accionistas (en adelante, los «Accionistas»).",
        f"La información contenida en este documento (en adelante, el «Documento» o «Information "
        f"Memorandum») ha sido facilitada por la dirección de la Compañía. Su única finalidad es permitir "
        f"al posible comprador evaluar, de manera preliminar, la situación operativa, financiera y "
        f"estratégica de la Compañía. {a} no ha auditado ni verificado de manera independiente dicha "
        f"información, por lo que no asume responsabilidad alguna respecto a su exactitud, integridad o veracidad.",
        f"Ni los Accionistas, ni la Compañía, ni {a} realizan manifestación o garantía, expresa o "
        f"implícita, sobre la información contenida en este Documento. Ninguno de ellos garantiza que la "
        f"información esté completa o que no existan errores, omisiones o inexactitudes. Las únicas "
        f"manifestaciones o garantías con efectos legales serán aquellas que, en su caso, se recojan "
        f"expresamente en la documentación contractual que pudiera firmarse en el marco de la Transacción.",
        f"El Documento puede incluir proyecciones, estimaciones o información de carácter prospectivo. "
        f"Dichas previsiones se basan en hipótesis y criterios proporcionados por la Compañía, que pueden "
        f"variar en función de circunstancias futuras. Ni los Accionistas, ni la Compañía, ni {a}, ni sus "
        f"directivos o empleados serán responsables en ningún caso de la precisión o cumplimiento de tales "
        f"previsiones, ni de cualquier decisión tomada en base a ellas.",
        f"El presente Documento no constituye una recomendación de inversión, ni pretende servir de base "
        f"única para la toma de decisiones. Cada receptor deberá realizar su propio análisis independiente "
        f"de la Compañía y de la Transacción, incluyendo los riesgos asociados, usando para ello sus propios "
        f"asesores legales, fiscales, financieros y técnicos.",
        f"Los Accionistas y {a} se reservan expresamente el derecho, en cualquier momento y a su sola "
        f"discreción, sin necesidad de previo aviso: (i) a modificar el contenido del Documento, (ii) a "
        f"interrumpir el proceso de venta, (iii) a restringir o cesar la entrega de información a uno o varios "
        f"potenciales compradores, y (iv) a negociar con uno o más terceros en relación con la Compañía, sin "
        f"que ello genere responsabilidad alguna.",
        f"En ningún caso la Compañía, los Accionistas o {a} serán responsables de los costes, gastos o "
        f"inversiones incurridos por cualquier posible comprador en el análisis de la Compañía, incluyendo, "
        f"entre otros, honorarios de asesores, informes de valoración, auditorías, o cualquier otro gasto "
        f"derivado del proceso.",
        f"Este Documento no constituye compromiso u obligación contractual alguna respecto a la Transacción. "
        f"Cualquier compromiso solo existirá si así se formaliza mediante un acuerdo definitivo debidamente "
        f"suscrito entre las partes.",
        f"La información aquí contenida es confidencial y se entrega con la condición de que no sea "
        f"reproducida, distribuida ni comunicada total o parcialmente a terceros sin el consentimiento previo "
        f"y por escrito de {a}. La recepción del Documento implica que el destinatario acepta íntegramente los "
        f"términos del presente descargo de responsabilidad.",
    ]


def _company_kpi_blocks(bundle: Dict) -> list:
    """KPI blocks from the real Financial Engine bundle. Cards carry the fiscal year and
    a short semantic detail (commentary) so they read as insight, not raw numbers."""
    kpis = bundle.get("kpis", {}) or {}
    year = (bundle.get("statements") or {}).get("year")
    out = []
    rev = kpis.get("revenue")
    if rev:
        g0 = kpis.get("revenue_growth_yoy")
        comm = (f"{g0*100:+.1f}% vs ejercicio anterior" if g0 is not None else "cifra de negocio del último ejercicio")
        b = kpi_block(f"Facturación {year}" if year else "Facturación", _es(f"{rev:,.0f}"), "€", commentary=comm)
        b["data_lineage"] = {"source": _FIN, "calculation": "revenue", "date": now_iso()}
        out.append(b)
    m = kpis.get("ebitda_margin")
    if m is not None:
        b = kpi_block("Margen EBITDA", _es(f"{m*100:.1f}") + " %", "", commentary="rentabilidad operativa sobre ingresos")
        b["data_lineage"] = {"source": _FIN, "calculation": "ebitda_margin", "date": now_iso()}
        out.append(b)
    emp = (bundle.get("statements") or {}).get("employees")
    if emp:
        out.append(kpi_block("Plantilla", str(emp), "empleados", commentary="equipo a cierre de ejercicio"))
    g = kpis.get("revenue_growth_yoy")
    if g is not None:
        b = kpi_block("Crecimiento YoY", f"{g*100:+.1f}%", "", commentary="variación de ingresos interanual")
        b["data_lineage"] = {"source": _FIN, "calculation": "revenue_growth_yoy", "date": now_iso()}
        out.append(b)
    cagr = kpis.get("revenue_cagr")
    if cagr is not None:
        b = kpi_block("CAGR ingresos", f"{cagr*100:+.1f}%", "", commentary="crecimiento medio anual del periodo")
        b["data_lineage"] = {"source": _FIN, "calculation": "revenue_cagr", "date": now_iso()}
        out.append(b)
    rpe = kpis.get("revenue_per_employee")
    if rpe:
        b = kpi_block("Ingresos/empleado", _es(f"{rpe:,.0f}"), "€", commentary="productividad operativa")
        b["data_lineage"] = {"source": _FIN, "calculation": "revenue_per_employee", "date": now_iso()}
        out.append(b)
    return out


def _investment_highlights_blocks(bundle: Dict) -> list:
    """'Investment Highlights' de un cuaderno de venta, generados desde los motores reales.
    Cada highlight = tesis + la cifra real que la sostiene. Solo se incluyen los que tienen
    dato (honesto, nunca inventado)."""
    kpis = bundle.get("kpis", {}) or {}
    pts = [p for p in ((bundle.get("evolution") or {}).get("points") or []) if p.get("revenue") is not None]
    comp = bundle.get("comparables", {}) or {}
    cf = (bundle.get("statements") or {}).get("cashflow") or {}
    out = []

    def hl(title, summary):
        b = insight_block(title=title, summary=summary, importance="high")
        b["data_lineage"] = {"source": _FIN, "task": "investment_highlight", "date": now_iso()}
        return b

    cagr = kpis.get("revenue_cagr")
    if cagr is not None and len(pts) >= 2:
        old = pts[-1]["revenue"] / 1e6
        new = pts[0]["revenue"] / 1e6
        out.append(hl("Crecimiento sólido y sostenido",
                      f"Los ingresos han crecido a un CAGR del {cagr*100:.0f} %, pasando de {old:.1f} M€ a "
                      f"{new:.1f} M€, lo que evidencia un crecimiento estructural y no coyuntural."))
    m = kpis.get("ebitda_margin")
    if m is not None:
        g = kpis.get("ebitda_growth_yoy")
        exp = (f", con el EBITDA creciendo un {g*100:.0f} % interanual, más rápido que los ingresos"
               if g is not None and g > 0 else "")
        out.append(hl("Rentabilidad probada y en expansión",
                      f"La compañía alcanza un margen EBITDA del {m*100:.1f} %{exp}, reflejando una "
                      f"rentabilidad operativa sólida y un claro apalancamiento del modelo."))
    rpe = kpis.get("revenue_per_employee")
    if rpe:
        pct = comp.get("subject_ebitda_margin_percentile")
        tail = (f", con un margen superior al del {round(pct*100)} % de las compañías del sector"
                if pct is not None else "")
        out.append(hl("Alta productividad por empleado",
                      f"{rpe:,.0f} € de ingresos por empleado, reflejando una elevada productividad "
                      f"operativa{tail}."))
    fcf = cf.get("free_cash_flow")
    ci = kpis.get("capital_intensity")
    if fcf is not None or ci is not None:
        parts = []
        if ci is not None:
            parts.append(f"una intensidad de capital de solo {ci:.2f}x (activo sobre ingresos)")
        if fcf is not None:
            parts.append(f"un flujo de caja libre de {fcf:,.0f} €")
        out.append(hl("Modelo escalable y ligero en capital",
                      "El negocio es poco intensivo en activos, con " + " y ".join(parts) +
                      ", lo que permite escalar la operación sin grandes inversiones y sostener la generación de caja."))
    opps = [s for s in (bundle.get("signals") or []) if s.get("severity") == "opportunity"]
    if opps:
        types = ", ".join(sorted({s.get("signal_type", "") for s in opps})[:3])
        out.append(hl("Señales de oportunidad activas",
                      f"El motor de inteligencia ha detectado {len(opps)} señal(es) de oportunidad activas "
                      f"({types}), que refuerzan el atractivo y la oportunidad de la operación."))
    return out


def _hero_kpi_blocks(bundle: Dict) -> list:
    """4 KPIs principales del cuaderno con su evolución vs ejercicio anterior:
    Facturación, Margen bruto, EBITDA, Nº de empleados."""
    kpis = bundle.get("kpis", {}) or {}
    year = (bundle.get("statements") or {}).get("year")
    pts = [p for p in ((bundle.get("evolution") or {}).get("points") or []) if p.get("year") is not None]
    latest = pts[0] if pts else {}
    prev = pts[1] if len(pts) > 1 else {}
    py = prev.get("year")
    out = []

    def card(title, value, unit, comm):
        b = kpi_block(title, value, unit, commentary=comm)
        b["data_lineage"] = {"source": _FIN, "task": "hero_kpi", "date": now_iso()}
        return b

    rev = kpis.get("revenue")
    if rev:
        g = kpis.get("revenue_growth_yoy")
        out.append(card(f"Facturación {year}" if year else "Facturación", f"{rev:,.0f}".replace(",", "."), "€",
                        f"{_pct(g, 1, signed=True)} vs {py}" if (g is not None and py) else "último ejercicio"))
    gm = latest.get("gross_margin")
    if gm is not None:
        gmp = prev.get("gross_margin")
        comm = (f"{_pp(gm-gmp)} vs {py}" if (gmp is not None and py) else "sobre ingresos")
        out.append(card("Margen bruto", _pct(gm), "", comm))
    eb = kpis.get("ebitda")
    if eb is not None:
        ge = kpis.get("ebitda_growth_yoy")
        out.append(card("EBITDA", f"{eb:,.0f}".replace(",", "."), "€",
                        f"{_pct(ge, 1, signed=True)} vs {py}" if (ge is not None and py) else "resultado operativo"))
    emp = (bundle.get("statements") or {}).get("employees")
    if emp:
        out.append(card("Empleados", str(emp), "", "plantilla a cierre de ejercicio"))
    return out


def _positive_signal_cards(bundle: Dict) -> list:
    """Tarjetas narrativas de igual tamaño con las señales POSITIVAS de la compañía, por eje:
    facturación, rentabilidad, operativa, balance, comparativa sectorial y señales del motor.
    Cada tarjeta lleva la cifra integrada en una frase con interpretación (no dato escueto)."""
    kpis = bundle.get("kpis", {}) or {}
    comp = bundle.get("comparables", {}) or {}
    cf = (bundle.get("statements") or {}).get("cashflow") or {}
    ratios = bundle.get("ratios", {}) or {}
    pts = [p for p in ((bundle.get("evolution") or {}).get("points") or []) if p.get("revenue") is not None]
    out = []

    def card(title, summary, cat):
        b = insight_block(title=title, summary=summary, importance="high")
        b["data_lineage"] = {"source": _FIN, "signal_axis": cat, "date": now_iso()}
        return b

    cagr = kpis.get("revenue_cagr")
    if cagr is not None and cagr > 0 and len(pts) >= 2:
        old, new = pts[-1]["revenue"] / 1e6, pts[0]["revenue"] / 1e6
        out.append(card("Crecimiento sostenido",
                        f"Los ingresos han crecido a un CAGR del {_pct(cagr, 0)}, pasando de {old:.1f} a "
                        f"{new:.1f} M€, lo que evidencia un crecimiento estructural y no coyuntural.", "facturación"))
    m = kpis.get("ebitda_margin")
    if m is not None:
        ge = kpis.get("ebitda_growth_yoy")
        exp = (" con el EBITDA creciendo más rápido que los ingresos" if ge is not None and ge > 0 else "")
        out.append(card("Rentabilidad probada",
                        f"La compañía alcanza un margen EBITDA del {_pct(m)}, reflejando una rentabilidad "
                        f"operativa sólida y un claro apalancamiento del modelo{exp}.", "rentabilidad"))
    rpe = kpis.get("revenue_per_employee")
    if rpe:
        pct = comp.get("subject_ebitda_margin_percentile")
        tail = (f", con un margen superior al del {round(pct*100)} % de las compañías del sector"
                if pct is not None else "")
        out.append(card("Alta productividad",
                        f"{_eur(rpe)} de ingresos por empleado, reflejando una elevada productividad "
                        f"operativa{tail}.", "operativa"))
    ccc = (ratios.get("cash_conversion_cycle") or {}).get("value")
    if ccc is not None:
        out.append(card("Circulante eficiente",
                        f"El ciclo de conversión de caja es de {ccc:.0f} días, lo que refleja una gestión "
                        f"eficiente del capital circulante y una rápida recuperación de la inversión operativa.", "operativa"))
    sol = kpis.get("solvency")
    fcf = cf.get("free_cash_flow")
    if sol is not None or fcf is not None:
        parts = []
        if sol is not None:
            parts.append(f"una autonomía financiera del {_pct(sol, 0)} (patrimonio neto sobre activo)")
        if fcf is not None:
            parts.append(f"un flujo de caja libre de {_eur(fcf)}")
        out.append(card("Balance sólido",
                        "La compañía presenta " + " y ".join(parts) +
                        ", que respaldan la solidez del balance y la capacidad de generación de caja.", "balance"))
    pct = comp.get("subject_ebitda_margin_percentile")
    if pct is not None:
        out.append(card("Mejor que el sector",
                        f"El margen de la compañía se sitúa por encima del {round(pct*100)} % de las empresas "
                        f"comparables de su sector (frente a {comp.get('count', 0)} peers de tamaño y geografía similares).", "sector"))
    for s in [x for x in (bundle.get("signals") or []) if x.get("severity") == "opportunity"][:2]:
        out.append(card("Señal de oportunidad",
                        (s.get("explanation") or s.get("signal_type") or "").strip(), "señal"))
    return out


def _legal_form(name: str) -> str:
    """Forma jurídica a partir del sufijo de la razón social (honesto: '' si no se reconoce)."""
    n = (name or "").upper().replace(".", "").replace(",", "")
    if " SLU" in f" {n}" or n.endswith("SLU"):
        return "Sociedad Limitada Unipersonal (S.L.U.)"
    if n.endswith("SL") or " SL " in f" {n} ":
        return "Sociedad Limitada (S.L.)"
    if n.endswith("SAU"):
        return "Sociedad Anónima Unipersonal (S.A.U.)"
    if n.endswith("SA") or " SA " in f" {n} ":
        return "Sociedad Anónima (S.A.)"
    if n.endswith("SLL"):
        return "Sociedad Limitada Laboral (S.L.L.)"
    if "COOP" in n:
        return "Sociedad Cooperativa"
    return ""


async def _company_description_blocks(master_id: str, ident: Dict, prof: Dict = None,
                                     summary_txt: str = None) -> list:
    """Descripción ampliada de la compañía desde el Motor Semántico (objeto social ->
    actividad, capacidades, productos/servicios, propuesta de valor) + datos societarios
    del Master. Todo honesto: se omite lo que no hay; la historia queda como bloque manual.
    Acepta un perfil semántico ya calculado para no repetir la llamada."""
    blocks = []
    if prof is None:
        prof, summary_txt = await _semantic_profile(master_id)
    prof = prof or {}

    # Propiedad (matriz + accionistas) desde el Master (dato real)
    try:
        mdoc = await db.master_companies.find_one({"master_id": master_id}, {"_id": 0, "ownership": 1})
        own = (mdoc or {}).get("ownership") or {}
    except Exception:
        own = {}
    parents = [p for p in (own.get("parents") or []) if p.get("name")]
    shareholders = [s for s in (own.get("shareholders") or []) if s.get("name")]

    # 1. Relato de actividad (propuesta de valor / resumen semántico)
    vp = (prof.get("value_proposition") or {}).get("value")
    lead = vp or summary_txt
    if lead:
        b = text_block(lead, style="executive_summary")
        b["data_lineage"] = {"source": "semantic-intelligence-v1", "task": "activity_narrative", "date": now_iso()}
        blocks.append(b)

    # 2. Datos societarios (Master) — incluye matriz si la tiene
    rows = []
    if ident.get("cif"):
        rows.append(["CIF", ident["cif"]])
    lf = _legal_form(ident.get("name"))
    if lf:
        rows.append(["Forma jurídica", lf])
    if ident.get("commercial_name"):
        rows.append(["Nombre comercial", ident["commercial_name"]])
    sede = ", ".join([x for x in [ident.get("municipio"), ident.get("provincia")] if x])
    if sede:
        rows.append(["Sede", sede])
    if ident.get("pais"):
        rows.append(["País", ident["pais"]])
    if parents:
        rows.append(["Matriz", _smart_case(parents[0]["name"])])
    if ident.get("web"):
        rows.append(["Web", ident["web"]])
    cap0 = ident.get("capital_social")
    if cap0:
        rows.append(["Capital social", _es(f"{cap0:,.0f}") + " €"])
    if ident.get("cnae_code"):
        rows.append(["CNAE", f"{ident['cnae_code']} — {ident.get('cnae_description') or ''}".strip(" —")])
    if rows:
        blocks.append(table_block("Datos societarios", ["Campo", "Valor"], rows))

    # 3. Objeto social literal (dato real de Iberinform, normalizado a caja de frase)
    obj = ident.get("objeto_social")
    if obj:
        if rows:  # separación extra respecto a la tabla de datos societarios
            blocks.append(text_block("18", style="spacer"))
        ob = text_block(f"Objeto social: {_smart_case(obj.strip())}", style="conclusion")
        ob["data_lineage"] = {"source": "master", "field": "objeto_social", "date": now_iso()}
        blocks.append(ob)

    # 4. Líneas de actividad / productos y servicios (capacidades del objeto social)
    caps = [c.get("value") for c in (prof.get("capabilities") or []) if isinstance(c, dict) and c.get("value")]
    ps = [p.get("value") for p in (prof.get("products_services") or []) if isinstance(p, dict) and p.get("value")]
    items, seen = [], set()
    for x in ps + caps:
        k = (x or "").strip().lower()
        if x and k not in seen:
            seen.add(k); items.append(_smart_case(x.strip()))
    for it in items[:8]:
        blocks.append(text_block(it, style="bullet"))

    # (La estructura accionarial y la Historia van en sus propias diapositivas.)
    return blocks


# Ancho de columna estándar para gráficos en fila con explicación (igual en todo el deck).
_CHART_COL = "52%"


def _evolution_charts(bundle: Dict) -> list:
    """Gráficos de evolución (barras ingresos + línea EBITDA) en columna estándar (52%),
    cada uno con una explicación a su derecha — mismo patrón que Contexto de Mercado."""
    out = []
    ev = bundle.get("evolution") or {}
    pts = sorted([p for p in (ev.get("points") or []) if p.get("year") is not None], key=lambda p: p["year"])
    pair_cfg = {"pair": True, "pair_width": _CHART_COL, "pair_align": "flex-start", "max_width": "100%"}

    bars = [{"label": str(p["year"]), "value": p.get("revenue")} for p in pts if p.get("revenue") is not None]
    if len(bars) >= 2:
        cb = chart_block("Evolución de ingresos", "bar", {"bars": bars, "fmt": "millions"}, dict(pair_cfg))
        cb["data_lineage"] = {"source": _FIN, "calculation": "evolution.revenue", "date": now_iso()}
        out.append(cb)
        rev0, rev1 = bars[0]["value"], bars[-1]["value"]
        yoy = ev.get("revenue_growth_yoy")
        n = len(bars) - 1
        cagr = ((rev1 / rev0) ** (1 / n) - 1) if (rev0 and rev1 and n > 0 and rev0 > 0) else None
        parts = [f"Los ingresos pasaron de {_es(f'{rev0/1e6:,.1f}')} a {_es(f'{rev1/1e6:,.1f}')} M€ "
                 f"entre {bars[0]['label']} y {bars[-1]['label']}"]
        if cagr is not None:
            parts.append(f"un CAGR del {_pct(cagr, 1, signed=True)}")
        if yoy is not None:
            parts.append(f"con una variación interanual del {_pct(yoy, 1, signed=True)} en el último ejercicio")
        out.append(insight_block("Evolución de ingresos", ", ".join(parts) + ".", importance="low"))

    line_pts = [{"label": str(p["year"]), "value": p.get("ebitda")} for p in pts if p.get("ebitda") is not None]
    if len(line_pts) >= 2:
        cl = chart_block("Evolución de EBITDA", "line",
                         {"points": line_pts, "value_key": "value", "fmt": "millions"}, dict(pair_cfg))
        cl["data_lineage"] = {"source": _FIN, "calculation": "evolution.ebitda", "date": now_iso()}
        out.append(cl)
        eb0, eb1 = line_pts[0]["value"], line_pts[-1]["value"]
        m1 = (pts[-1].get("ebitda_margin") if pts else None)
        parts = [f"El EBITDA evolucionó de {_es(f'{eb0/1e6:,.1f}')} a {_es(f'{eb1/1e6:,.1f}')} M€"]
        if m1 is not None:
            parts.append(f"con un margen del {_pct(m1)} en {line_pts[-1]['label']}")
        egr = ev.get("ebitda_growth_yoy")
        if egr is not None:
            parts.append(f"y una variación interanual del {_pct(egr, 1, signed=True)}")
        out.append(insight_block("Evolución de EBITDA", ", ".join(parts) + ".", importance="low"))
    return out


async def _load_peers(bundle: Dict) -> list:
    """Consulta ÚNICA de peers del sector (revenue, margen EBITDA, empleados, ingresos/empleado).
    Reutilizada por los gráficos de sector y por el scatter de productividad — evita escanear
    dos veces master_companies (rendimiento)."""
    section = (bundle.get("identity") or {}).get("cnae_section")
    peers = []
    if not section:
        return peers
    q = {"classification.cnae_section": section, "financials.latest.revenue": {"$ne": None}}
    if bundle.get("master_id"):
        q["master_id"] = {"$ne": bundle["master_id"]}
    async for m in db.master_companies.find(
            q, {"_id": 0, "financials.latest": 1, "size.employees_total": 1, "identity.legal_name": 1}).limit(4000):
        fl = (m.get("financials") or {}).get("latest") or {}
        rev = fl.get("revenue"); mar = fl.get("ebitda_margin")
        if mar is None and fl.get("ebitda") and rev:
            mar = fl["ebitda"] / rev
        if rev and mar is not None:
            emp = (m.get("size") or {}).get("employees_total")
            eq, ta = fl.get("equity"), fl.get("total_assets")
            sol = (eq / ta) if (eq is not None and ta) else None
            peers.append({"revenue": rev, "margin": mar,
                          "rpe": (rev / emp if emp else None),
                          "solvency": sol,
                          "name": (m.get("identity") or {}).get("legal_name")})
    return peers


async def _sector_charts(bundle: Dict, peers: list = None) -> Dict:
    """Gráficos de sector con datos reales. Devuelve {distribution, donut, scatter}
    para repartirlos por las secciones del documento."""
    import statistics
    res = {}
    kp = bundle.get("kpis", {}) or {}
    if peers is None:
        peers = await _load_peers(bundle)

    # 1. Distribución (histograma) del margen EBITDA del sector, con mediana y media
    if len(peers) >= 8:
        edges = [(-99, 0, "<0%"), (0, .05, "0-5%"), (.05, .10, "5-10%"), (.10, .15, "10-15%"),
                 (.15, .20, "15-20%"), (.20, .30, "20-30%"), (.30, 99, ">30%")]
        margins = [p["margin"] for p in peers]
        bars = [{"label": lbl, "value": sum(1 for m in margins if lo <= m < hi)} for lo, hi, lbl in edges]
        med = statistics.median(margins)
        mean = sum(margins) / len(margins)
        def _binfrac(v):
            for idx, (lo, hi, _l) in enumerate(edges):
                if lo <= v < hi:
                    return (idx + 0.5) / len(edges)
            return 0.5
        refs = [{"value_x_frac": _binfrac(med), "label": f"Mediana: {_pct(med, 0)}", "dashed": False},
                {"value_x_frac": _binfrac(mean), "label": f"Media: {_pct(mean, 0)}", "dashed": True}]
        cdist = chart_block(f"Distribución del margen EBITDA ({len(peers)} empresas)", "bar",
                            {"bars": bars, "ref_lines": refs})
        cdist["data_lineage"] = {"source": "master_companies", "calculation": "histograma margen EBITDA", "date": now_iso()}
        res["distribution"] = cdist

    # Donut — perfil de rentabilidad del sector (Alta/Media/Baja)
    if len(peers) >= 8:
        alta = sum(1 for p in peers if p["margin"] > 0.15)
        media = sum(1 for p in peers if 0.05 <= p["margin"] <= 0.15)
        baja = sum(1 for p in peers if p["margin"] < 0.05)
        segs = [{"label": "Alta (>15%)", "value": alta, "color": "#1D9E75"},
                {"label": "Media (5-15%)", "value": media, "color": "#EF9F27"},
                {"label": "Baja (<5%)", "value": baja, "color": "#E24B4A"}]
        cd = chart_block("Perfil de rentabilidad del sector", "donut", {"segments": segs})
        cd["data_lineage"] = {"source": "master_companies", "calculation": "distribución margen EBITDA", "date": now_iso()}
        res["donut"] = cd

    # Scatter — mapa sectorial: ingresos vs margen EBITDA (empresa destacada, cuadrantes)
    if len(peers) >= 8:
        # Etiquetar SOLO las principales (mayores por ingresos) + la empresa destacada, para no
        # solapar nombres en el mapa. El resto se dibuja como punto sin etiqueta.
        _top_names = {p.get("name") for p in sorted(peers, key=lambda p: -(p.get("revenue") or 0))[:6]}
        spts = [{"x": p["revenue"], "y": p["margin"],
                 "label": (p.get("name") if p.get("name") in _top_names else None)} for p in peers]
        if kp.get("revenue") and kp.get("ebitda_margin") is not None:
            spts.append({"x": kp["revenue"], "y": kp["ebitda_margin"], "highlight": True,
                         "label": (bundle.get("identity") or {}).get("name")})
        med_x = statistics.median([p["revenue"] for p in peers])
        med_y = statistics.median([p["margin"] for p in peers])
        cs = chart_block("Mapa sectorial: ingresos vs margen EBITDA", "scatter",
                         {"points": spts, "x_label": "Ingresos (€)", "y_label": "Margen EBITDA",
                          "x_fmt": "eur", "y_fmt": "pct", "med_x": med_x, "med_y": med_y})
        cs["data_lineage"] = {"source": "master_companies", "calculation": "peers ingresos×margen", "date": now_iso()}
        res["scatter"] = cs
    return res


async def _team_org_blocks(bundle: Dict, master_id: str, cif_norm: str, peers: list = None) -> dict:
    """Bloques de 'Equipo y Organización' al estilo de la referencia, agrupados para
    repartirlos en dos diapositivas (evita el recorte por alto fijo de la slide):
    leadership, orgchart, costs, productivity."""
    import statistics
    ident = bundle.get("identity") or {}
    name = ident.get("name") or "La compañía"
    kp = bundle.get("kpis", {}) or {}
    wf = ident.get("workforce") or {}
    plantilla = wf.get("total") or (bundle.get("statements") or {}).get("employees")
    g = {"leadership": [], "orgchart": [], "costs": [], "productivity": []}

    # (1) Equipo directivo y liderazgo — texto editable con datos reales
    g["leadership"].append(text_block("Equipo directivo y liderazgo", "subhead"))
    g["leadership"].append(text_block(f"{name} cuenta con un equipo directivo con implicación directa en la "
                                      f"gestión diaria del negocio.", "bullet"))
    g["leadership"].append(text_block("El liderazgo ha aportado continuidad y estabilidad a la estrategia de "
                                      "la compañía a lo largo de su desarrollo.", "bullet"))
    if plantilla:
        g["leadership"].append(text_block(f"Una plantilla de {_es(f'{int(plantilla):,}')} profesionales se "
                                          f"organiza en áreas funcionales especializadas.", "bullet"))
    g["leadership"].append(text_block("El equipo directivo reporta al órgano de administración de la sociedad.", "bullet"))

    # (2) Estructura operativa — organigrama desde administradores reales
    officers = await db.norm_officers.find({"cif_normalized": cif_norm}, {"_id": 0}).to_list(20)
    officers = [o for o in officers if o.get("person_name")]
    if officers:
        g["orgchart"].append(text_block("Estructura operativa", "subhead"))
        root = {"name": "Consejo de Administración", "role": name}
        groups = [{"lead": {"name": o.get("person_name"), "role": o.get("person_role") or "Administrador"},
                   "members": []} for o in officers[:8]]
        ob = orgchart_block(root, groups, title="Organigrama de gobierno")
        ob["data_lineage"] = {"source": "master-v1 (norm_officers)", "date": now_iso()}
        g["orgchart"].append(ob)

    # (3) Evolución de los costes de personal — tabla real
    pts = [p for p in ((bundle.get("evolution") or {}).get("points") or [])
           if p.get("personnel_costs") is not None and p.get("revenue")]
    if pts:
        rows = []
        for p in sorted(pts, key=lambda x: x.get("year") or 0):
            pc = abs(p["personnel_costs"]); pp = p.get("personnel_pct")
            rows.append([str(p.get("year")), _es(f"{p['revenue']:,.0f}") + " €",
                         _es(f"{pc:,.0f}") + " €",
                         _pct(abs(pp) if pp is not None else None)])
        g["costs"].append(text_block("Evolución de los costes de personal", "subhead"))
        tb = table_block("", ["Año", "Ingresos (€)", "Costes de personal (€)", "% sobre ventas"], rows)
        tb["data_lineage"] = {"source": "Iberinform (cuenta 40600)", "date": now_iso()}
        g["costs"].append(tb)

    # (4) Productividad y rentabilidad por empleado — scatter Revenue/FTE vs EBITDA
    if peers is None:
        peers = await _load_peers(bundle)
    ppe = [p for p in peers if p.get("rpe")]
    if len(ppe) >= 8:
        # Etiquetar SOLO las 6 mayores por ingresos + la empresa destacada, para que no se
        # solapen los nombres; el resto se dibujan como puntos sin etiqueta.
        _top_names = {p.get("name") for p in sorted(ppe, key=lambda p: -(p.get("revenue") or 0))[:6]}
        spts = [{"x": p["margin"], "y": p["rpe"],
                 "label": (p.get("name") if p.get("name") in _top_names else None)} for p in ppe]
        rpe_self = kp.get("revenue_per_employee")
        mar_self = kp.get("ebitda_margin")
        if rpe_self and mar_self is not None:
            spts.append({"x": mar_self, "y": rpe_self, "highlight": True, "label": name})
        med_x = statistics.median([p["margin"] for p in ppe])
        med_y = statistics.median([p["rpe"] for p in ppe])
        g["productivity"].append(text_block("Productividad y rentabilidad por empleado (Revenue/FTE vs EBITDA)", "subhead"))
        cs = chart_block("", "scatter",
                         {"points": spts, "x_label": "Margen EBITDA", "y_label": "Ingresos por empleado (€)",
                          "x_fmt": "pct", "y_fmt": "eur", "med_x": med_x, "med_y": med_y},
                         {"pair": True, "pair_width": "460px", "pair_align": "flex-start"})
        cs["data_lineage"] = {"source": "master_companies", "calculation": "peers ingresos/empleado × margen", "date": now_iso()}
        g["productivity"].append(cs)
        if rpe_self and mar_self is not None:
            quad = ("superior de productividad y rentabilidad" if (rpe_self >= med_y and mar_self >= med_x)
                    else "de su sector")
            g["productivity"].append(insight_block(
                "Posicionamiento por eficiencia",
                f"Con una facturación por empleado cercana a {_es(f'{rpe_self:,.0f}')} € y un margen EBITDA "
                f"del {_pct(mar_self)}, {name} se sitúa en el cuadrante {quad}, reflejando un modelo "
                f"operativo eficiente y escalable.", importance="medium"))
    return g


async def _market_competition_blocks(bundle: Dict, peers: list, econ: Dict) -> dict:
    """Bloques de 'Mercado y competencia' con datos reales:
      context     -> tamaño/dinámica del mercado + estructura (HHI/fragmentación E7) + síntesis.
      competition -> competidores más cercanos del sector + posición competitiva de la empresa.
    Todo determinista sobre motores existentes; la síntesis es una lectura reglada de las
    cifras (el LLM ya integrado puede sustituirla/enriquecerla con fact-lock)."""
    import statistics
    g = {"context": [], "competition": []}
    ident = bundle.get("identity") or {}
    name = ident.get("name") or "La compañía"
    kp = bundle.get("kpis", {}) or {}
    section = ident.get("cnae_section")
    cnae_code = ident.get("cnae_code")
    comp_rev = kp.get("revenue")
    comp_mar = kp.get("ebitda_margin")

    # ── Estructura del mercado (fragmentación E7, HHI real) ──
    frag = {}
    try:
        from services.engines.investment.fragmentation import compute_fragmentation
        if section:
            frag = await compute_fragmentation("cnae_section", section, limit_companies=800) or {}
    except Exception:
        frag = {}

    # ── CONTEXTO DE MERCADO ──
    size_kpis = []
    if econ.get("active_companies_national"):
        size_kpis.append(kpi_block("Empresas activas (sector)",
                                   _es(f"{econ['active_companies_national']['value']:,.0f}"), "empresas",
                                   commentary="universo nacional del CNAE"))
    if econ.get("revenue"):
        size_kpis.append(kpi_block("Facturación media sector",
                                   _es(f"{econ['revenue']['value']:,.0f}"), "€",
                                   commentary="por empresa (DIRCE/Economic Intelligence)"))
    if econ.get("exports_eur"):
        size_kpis.append(kpi_block("Exportaciones del sector",
                                   _es(f"{econ['exports_eur']['value']:,.0f}"), "€"))
    if econ.get("procurement_contracts"):
        size_kpis.append(kpi_block("Contratos públicos",
                                   _es(f"{econ['procurement_contracts']['value']:,.0f}"), "contratos"))
    if size_kpis:
        g["context"].append(text_block("Tamaño y dinámica del mercado", "subhead"))
        g["context"].extend(size_kpis)

    if frag.get("hhi") is not None or frag.get("market_actors_count"):
        g["context"].append(text_block("Estructura competitiva del mercado", "subhead"))
        # Fila 1 — concentración HHI como termómetro 0–10.000 + lectura de la escala
        if frag.get("hhi") is not None:
            hhi = frag["hhi"]
            hhi_txt = _es(f"{hhi:,.0f}")
            label_es = _hhi_label_es(frag.get("concentration_label")) or "moderadamente concentrado"
            gb = chart_block("", "gauge", {
                "value": hhi, "min": 0, "max": 10000,
                "value_label": f"HHI {hhi_txt}",
                "ticks": [0, 1500, 2500, 5000, 10000],
                "zones": [
                    {"to": 1500, "label": "No concentrado"},
                    {"to": 2500, "label": "Moderado"},
                    {"to": 10000, "label": "Concentrado"},
                ]})
            gb["data_lineage"] = {"source": "fragmentation-v1 (HHI)", "date": now_iso()}
            g["context"].append(gb)
            _ins_hhi = insight_block(
                "Concentración del mercado (HHI)",
                f"Con un HHI de {hhi_txt}, el mercado es {label_es} en la escala DOJ/FTC (0–10.000): "
                f"por debajo de 1.500 se considera no concentrado, entre 1.500 y 2.500 moderadamente "
                f"concentrado, y por encima de 2.500 altamente concentrado. El HHI es la suma de los "
                f"cuadrados de las cuotas de mercado y mide cuánto se reparte el sector entre pocos o "
                f"muchos actores.", importance="medium")
            _ins_hhi["data"]["full_width"] = True
            g["context"].append(_ins_hhi)
        # Fila 2 — actores de mercado + objetivos independientes, a todo el ancho
        parts2 = []
        if frag.get("market_actors_count"):
            _ac = _es(f"{frag['market_actors_count']:,.0f}")
            parts2.append(f"{_ac} actores de mercado (grupos reales de propiedad, no empresas sueltas)")
        if frag.get("standalone_targets_count"):
            _st = _es(f"{frag['standalone_targets_count']:,.0f}")
            parts2.append(f"{_st} objetivos independientes (empresas sin grupo, candidatas a consolidación)")
        if parts2:
            _ins_act = insight_block("Actores y objetivos de consolidación",
                                     " · ".join(parts2) + ".", importance="low")
            _ins_act["data"]["full_width"] = True
            g["context"].append(_ins_act)

    # Síntesis reglada: cómo compite y qué debería hacer (fact-lock sobre cifras reales)
    synth = _market_synthesis(name, kp, peers, frag)
    if synth:
        ins = insight_block("Lectura de mercado y posición competitiva", synth, importance="high")
        ins["data"]["full_width"] = True
        ins["data_lineage"] = {"source": "fragmentation-v1 + financial-intelligence + master_companies",
                               "note": "síntesis reglada; ampliable por LLM con fact-lock", "date": now_iso()}
        g["context"].append(ins)

    # ── COMPETENCIA: competidores más cercanos por ingresos ──
    withrev = [p for p in peers if p.get("revenue")]
    if withrev and comp_rev:
        nearest = sorted(withrev, key=lambda p: abs((p["revenue"] or 0) - comp_rev))[:6]
        rows = []
        for p in nearest:
            rows.append([_clip_name(p.get("name")), _es(f"{p['revenue']:,.0f}") + " €",
                         _pct(p["margin"]) if p.get("margin") is not None else "n/d",
                         _es(f"{p['rpe']:,.0f}") + " €" if p.get("rpe") else "n/d"])
        g["competition"].append(text_block("Competidores más cercanos por tamaño", "subhead"))
        tbc = table_block("", ["Empresa", "Ingresos (€)", "Margen EBITDA", "Ingresos/empleado"], rows)
        tbc["data_lineage"] = {"source": "master_companies (mismo CNAE sección)", "date": now_iso()}
        g["competition"].append(tbc)

    # Posición competitiva: percentil de ingresos y de margen + cuota estimada
    if withrev and comp_rev:
        revs = sorted(p["revenue"] for p in withrev)
        pctl_rev = sum(1 for r in revs if r < comp_rev) / len(revs)
        tot_rev = sum(revs) + comp_rev
        share = comp_rev / tot_rev if tot_rev else None
        mars = [p["margin"] for p in withrev if p.get("margin") is not None]
        pctl_mar = (sum(1 for x in mars if x < comp_mar) / len(mars)) if (mars and comp_mar is not None) else None
        parts = [f"{name} se sitúa en el percentil {_es(f'{pctl_rev*100:.0f}')} por ingresos del sector"]
        if share is not None:
            parts.append(f"con una cuota estimada del {_pct(share)} sobre la muestra sectorial analizada")
        if pctl_mar is not None:
            comp = "por encima" if comp_mar >= statistics.median(mars) else "por debajo"
            parts.append(f"y un margen EBITDA {comp} de la mediana (percentil {_es(f'{pctl_mar*100:.0f}')})")
        ins2 = insight_block("Posición competitiva de la compañía", ", ".join(parts) + ".", importance="medium")
        ins2["data_lineage"] = {"source": "financial-intelligence + master_companies", "date": now_iso()}
        g["competition"].append(ins2)
    return g


def _clip_name(s, n: int = 34) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


_HHI_ES = {
    "not_concentrated": "no concentrado", "unconcentrated": "no concentrado",
    "moderately_concentrated": "moderadamente concentrado",
    "highly_concentrated": "altamente concentrado", "concentrated": "concentrado",
}


def _hhi_label_es(label) -> str:
    if not label:
        return ""
    return _HHI_ES.get(str(label).lower(), str(label).replace("_", " "))


def _distribution_note(bundle: Dict, peers: list):
    """Explicación (insight) de lo que muestra el histograma de márgenes del sector."""
    import statistics
    ident = bundle.get("identity") or {}
    name = ident.get("name") or "La compañía"
    mars = [p["margin"] for p in (peers or []) if p.get("margin") is not None]
    comp_mar = (bundle.get("kpis") or {}).get("ebitda_margin")
    if not mars:
        return insight_block("Cómo leer el gráfico",
                             "Cada barra agrupa las empresas del sector por su margen EBITDA; "
                             "las líneas marcan la mediana y la media sectorial.", importance="low")
    med = statistics.median(mars); mean = sum(mars) / len(mars)
    alta = sum(1 for x in mars if x > 0.15)
    parts = [f"El histograma reparte las {_es(f'{len(mars):,.0f}')} empresas del sector por su margen "
             f"EBITDA. La mediana se sitúa en {_pct(med)} y la media en {_pct(mean)}"]
    if alta:
        parts.append(f"{_es(f'{alta:,.0f}')} superan el 15 % de margen (alta rentabilidad)")
    if comp_mar is not None:
        rel = "por encima" if comp_mar >= med else "por debajo"
        parts.append(f"{name}, con un {_pct(comp_mar)}, se sitúa {rel} de la mediana del sector")
    return insight_block("Qué muestra el gráfico", ". ".join(parts) + ".", importance="medium")


def _financial_position_blocks(bundle: Dict) -> list:
    """Fondo de maniobra + Posición Financiera Neta (deuda financiera − tesorería) con
    serie temporal real (gráfico de barras agrupadas con eje cero) + KPIs + explicación."""
    ident = bundle.get("identity") or {}
    name = ident.get("name") or "La compañía"
    pts = [p for p in ((bundle.get("evolution") or {}).get("points") or [])
           if (p.get("working_capital") is not None or p.get("net_financial_position") is not None)]
    if not pts:
        return []
    pts = sorted(pts, key=lambda x: x.get("year") or 0)
    years = [str(p.get("year")) for p in pts]
    wc = [p.get("working_capital") for p in pts]
    nfp = [p.get("net_financial_position") for p in pts]
    out = []
    last = pts[-1]
    # KPIs último ejercicio
    if last.get("working_capital") is not None:
        out.append(kpi_block(f"Fondo de maniobra {last.get('year')}",
                             _es(f"{last['working_capital']:,.0f}") + " €", "",
                             commentary="activo corriente − pasivo corriente"))
    if last.get("net_financial_position") is not None:
        npf = last["net_financial_position"]
        etiqueta = "deuda financiera neta" if npf >= 0 else "caja neta"
        out.append(kpi_block(f"Posición financiera neta {last.get('year')}",
                             _es(f"{npf:,.0f}") + " €", "",
                             commentary=f"{etiqueta} = deuda financiera − tesorería"))
        eb = last.get("ebitda")
        if eb and eb > 0:
            out.append(kpi_block("Deuda financiera neta / EBITDA", _es(f"{npf/eb:,.1f}") + "x", "",
                                 commentary="apalancamiento sobre resultado operativo"))
    # Gráfico de barras agrupadas (fondo de maniobra + PFN) con eje cero
    out.append(text_block("Evolución del fondo de maniobra y la posición financiera neta", "subhead"))
    cb = chart_block("", "grouped_bar",
                     {"categories": years,
                      "series": [{"name": "Fondo de maniobra", "color": "#2E6BB0", "values": wc},
                                 {"name": "Posición financiera neta", "color": "#BA7517", "values": nfp}],
                      "fmt": "millions"},
                     {"pair": True, "pair_width": _CHART_COL, "pair_align": "flex-start", "max_width": "100%"})
    cb["data_lineage"] = {"source": "Iberinform (balance: 12000/32000/31200/32300/12700)", "date": now_iso()}
    out.append(cb)
    # Explicación (fila con el gráfico)
    out.append(_financial_position_note(name, pts))
    return out


def _projection_tables(bundle: Dict) -> list:
    """Tres tablas de escenarios (Conservador · Base · Optimista) proyectando Revenue,
    margen bruto y EBITDA a 3 años sobre el último ejercicio real. Supuestos deterministas,
    claramente etiquetados como ilustrativos (no previsiones auditadas)."""
    pts = sorted([p for p in ((bundle.get("evolution") or {}).get("points") or []) if p.get("year")],
                 key=lambda p: p["year"])
    if not pts:
        return []
    last = pts[-1]
    rev0 = last.get("revenue")
    gm0 = last.get("gross_margin")
    em0 = last.get("ebitda_margin")
    if not rev0 or em0 is None:
        return []
    base_year = last.get("year")
    # Crecimiento base: CAGR histórico si hay ≥2 años, con cota razonable; si no, YoY o 3%.
    if len(pts) >= 2 and pts[0].get("revenue"):
        n = len(pts) - 1
        cagr = (rev0 / pts[0]["revenue"]) ** (1 / n) - 1 if pts[0]["revenue"] > 0 else 0.03
    else:
        cagr = (bundle.get("evolution") or {}).get("revenue_growth_yoy") or 0.03
    base_g = max(-0.05, min(cagr, 0.12))  # acotar a rango sensato
    scenarios = [
        ("Escenario conservador", base_g - 0.03, (gm0 - 0.02) if gm0 is not None else None, em0 - 0.015),
        ("Escenario base", base_g, gm0, em0),
        ("Escenario optimista", base_g + 0.03, (gm0 + 0.02) if gm0 is not None else None, em0 + 0.015),
    ]
    out = []
    out.append(text_block(
        f"Escenarios ilustrativos a 3 años sobre el último ejercicio real ({base_year}). "
        f"Supuestos de crecimiento y margen; no constituyen previsiones auditadas.", style="body"))
    years = [base_year + k for k in (1, 2, 3)]
    for title, g, gm, em in scenarios:
        rev_row, gm_row, eb_row = ["Revenue"], ["Margen bruto"], ["EBITDA"]
        r = rev0
        for _ in years:
            r = r * (1 + g)
            rev_row.append(_es(f"{r:,.0f}") + " €")
            gm_row.append(_pct(gm) if gm is not None else "n/d")
            eb_row.append(_es(f"{r*em:,.0f}") + " €")
        out.append(text_block(f"{title} · crecimiento {_pct(g, 1, signed=True)}", "subhead"))
        tb = table_block("", ["Concepto"] + [str(y) for y in years], [rev_row, gm_row, eb_row])
        tb["data_lineage"] = {"source": "proyección ilustrativa (base: último ejercicio real)", "date": now_iso()}
        out.append(tb)
    # Nota metodológica — cómo se calculan los escenarios de forma automática
    out.append(text_block("18", style="spacer"))
    nota = (
        f"Metodología (cálculo automático): la base es el último ejercicio real ({base_year}). "
        f"El crecimiento del escenario base es el CAGR histórico de ingresos ({_pct(base_g, 1, signed=True)}), "
        f"acotado al rango −5 % / +12 % para evitar extrapolaciones extremas; el conservador aplica −3 p.p. "
        f"y el optimista +3 p.p. sobre esa tasa. Los ingresos se proyectan componiendo la tasa anual sobre el "
        f"año anterior. El margen bruto parte del último real ({_pct(gm0) if gm0 is not None else 'n/d'}) y se "
        f"ajusta ±2 p.p. por escenario; el margen EBITDA parte del último real ({_pct(em0)}) y se ajusta "
        f"±1,5 p.p. El EBITDA de cada año se obtiene como Revenue × margen EBITDA. "
        f"Son escenarios ilustrativos generados automáticamente a partir de datos reales de Iberinform; "
        f"no constituyen previsiones auditadas ni un plan de negocio del vendedor.")
    nb = text_block(nota, style="legal")
    nb["data_lineage"] = {"source": "metodología de proyección (composer)", "date": now_iso()}
    out.append(nb)
    return out


def _ebitda_bridge_blocks(bundle: Dict) -> list:
    """EBITDA bridge (puente de EBITDA reportado → ajustado) con LAYOUT DEFINITIVO listo
    para que el asesor rellene los ajustes. Parte del EBITDA reportado real; los add-backs
    quedan como placeholders (cascada punteada + tabla '[por determinar]')."""
    pts = sorted([p for p in ((bundle.get("evolution") or {}).get("points") or []) if p.get("year")],
                 key=lambda p: p["year"])
    last = pts[-1] if pts else {}
    eb = last.get("ebitda")
    if eb is None:
        eb = (bundle.get("kpis") or {}).get("ebitda")
    if eb is None:
        return []
    yr = last.get("year") or ""
    out = [text_block("Puente de EBITDA (reportado → ajustado)", "subhead")]
    # Cascada: start real + ajustes placeholder + total (=reportado hasta que se rellenen)
    items = [
        {"label": f"EBITDA reportado {yr}", "value": eb, "type": "start"},
        {"label": "Gastos no recurrentes", "value": 0, "type": "delta"},
        {"label": "Ajuste retribución propietarios", "value": 0, "type": "delta"},
        {"label": "Operaciones vinculadas", "value": 0, "type": "delta"},
        {"label": "Otros ajustes", "value": 0, "type": "delta"},
        {"label": "EBITDA ajustado", "value": eb, "type": "total"},
    ]
    cb = chart_block("", "waterfall", {"items": items, "fmt": "millions"},
                     {"pair": True, "pair_width": _CHART_COL, "pair_align": "flex-start", "max_width": "100%"})
    cb["data_lineage"] = {"source": "Iberinform (EBITDA real) + ajustes del asesor", "date": now_iso()}
    out.append(cb)
    out.append(insight_block(
        "Cómo se completa",
        "El puente parte del EBITDA reportado real. El asesor cuantifica los add-backs "
        "(gastos no recurrentes, ajuste de retribución de propietarios a mercado, resultado de "
        "operaciones vinculadas y otros ajustes) para llegar al EBITDA ajustado, base habitual "
        "de la valoración por múltiplo.", importance="medium"))
    # Tabla de ajustes (placeholder para el asesor)
    rows = [["EBITDA reportado " + str(yr), _es(f"{eb:,.0f}") + " €"],
            ["(+) Gastos no recurrentes", "[por determinar]"],
            ["(+) Ajuste retribución propietarios", "[por determinar]"],
            ["(+/−) Operaciones vinculadas", "[por determinar]"],
            ["(+) Otros ajustes", "[por determinar]"],
            ["EBITDA ajustado", "[por determinar]"]]
    tb = table_block("Detalle de ajustes", ["Concepto", "Importe"], rows)
    tb["data_lineage"] = {"source": "plantilla de ajustes (a completar por el asesor)", "date": now_iso()}
    out.append(tb)
    return out


def _financial_position_note(name: str, pts: list):
    wc0, wc1 = pts[0].get("working_capital"), pts[-1].get("working_capital")
    nfp0, nfp1 = pts[0].get("net_financial_position"), pts[-1].get("net_financial_position")
    eb1 = pts[-1].get("ebitda")
    frases = []
    if wc1 is not None:
        signo = "negativo" if wc1 < 0 else "positivo"
        tend = ""
        if wc0 is not None and wc1 is not None:
            tend = " y se ha reducido" if wc1 < wc0 else " y ha mejorado"
        extra = (" — habitual en negocios de cobro anticipado, donde el cliente paga antes de "
                 "incurrir en el coste") if wc1 < 0 else ""
        frases.append(f"El fondo de maniobra es {signo} ({_es(f'{wc1/1e6:,.1f}')} M€){tend}{extra}")
    if nfp1 is not None:
        tipo = "deuda financiera neta" if nfp1 >= 0 else "caja neta"
        lev = f", equivalente a {_es(f'{nfp1/eb1:,.1f}')}× EBITDA" if (eb1 and eb1 > 0 and nfp1 >= 0) else ""
        tend2 = ""
        if nfp0 is not None:
            tend2 = " al alza" if nfp1 > nfp0 else " a la baja"
        frases.append(f"La compañía mantiene una posición de {tipo} de {_es(f'{nfp1/1e6:,.1f}')} M€{tend2}{lev}")
    return insight_block("Lectura de la posición financiera", ". ".join(frases) + "." if frases else "",
                         importance="medium")


def _market_synthesis(name: str, kp: Dict, peers: list, frag: Dict) -> str:
    """Lectura reglada de mercado: concentración + posición + implicación estratégica."""
    import statistics
    comp_rev = kp.get("revenue"); comp_mar = kp.get("ebitda_margin")
    withrev = [p for p in (peers or []) if p.get("revenue")]
    label_raw = (frag.get("concentration_label") or "").lower()
    label_es = _hhi_label_es(frag.get("concentration_label"))
    hhi = frag.get("hhi")
    sents = []
    if label_es and hhi is not None:
        sents.append(f"El mercado está {label_es} (HHI {_es(f'{hhi:,.0f}')})")
    # posición de la empresa (tamaño + margen en una sola frase)
    if withrev and comp_rev:
        revs = sorted(p["revenue"] for p in withrev)
        pctl = sum(1 for r in revs if r < comp_rev) / len(revs)
        band = ("una posición de liderazgo" if pctl >= 0.8 else
                "una posición destacada" if pctl >= 0.6 else
                "una posición intermedia" if pctl >= 0.4 else "una posición de nicho")
        frase = f"{name} ocupa {band} por tamaño (percentil {_es(f'{pctl*100:.0f}')})"
        mars = [p["margin"] for p in withrev if p.get("margin") is not None]
        if mars and comp_mar is not None:
            rel = "superior" if comp_mar >= statistics.median(mars) else "inferior"
            frase += f", con una rentabilidad {rel} a la mediana sectorial"
        sents.append(frase)
    # implicación estratégica según fragmentación
    targets = frag.get("standalone_targets_count") or 0
    concentrado = "altamente concentrado" in label_es or "concentrado" == label_es
    if concentrado:
        sents.append("En un mercado concentrado, la prioridad es defender cuota, reforzar la "
                     "diferenciación y crecer de forma orgánica o mediante adquisiciones selectivas de alto encaje")
    elif targets:
        sents.append(f"Con {_es(f'{targets:,.0f}')} objetivos independientes en el sector, la compañía "
                     f"dispone de recorrido para liderar una estrategia de consolidación (buy-and-build)")
    return ". ".join(sents) + "." if sents else ""


async def _captable_blocks(master_id: str) -> list:
    """Diagrama de estructura societaria (accionistas · sociedad · participadas) desde datos
    reales de propiedad (norm_ownership) + identidad del Master."""
    try:
        mdoc = await db.master_companies.find_one(
            {"master_id": master_id},
            {"_id": 0, "ownership": 1, "identity": 1, "classification": 1, "location": 1, "cif_normalized": 1})
    except Exception:
        mdoc = None
    if not mdoc:
        return []
    own = mdoc.get("ownership") or {}
    shareholders = sorted([s for s in (own.get("shareholders") or []) if s.get("name")],
                          key=lambda s: (s.get("pct") or 0), reverse=True)
    shareholders = [{"name": _smart_case(s["name"]), "cif": s.get("cif"), "pct": s.get("pct")} for s in shareholders[:8]]
    investees_raw = [i for i in (own.get("investees") or []) if i.get("name")]
    investees = []
    for iv in investees_raw[:8]:
        sub = None
        if iv.get("cif"):
            sub = await db.master_companies.find_one({"cif_normalized": iv["cif"]},
                                                     {"_id": 0, "classification.cnae_description": 1, "location.provincia": 1})
        investees.append({"name": _smart_case(iv["name"]), "pct": iv.get("pct"),
                          "sector": _smart_case((sub or {}).get("classification", {}).get("cnae_description") or "") or None,
                          "location": (sub or {}).get("location", {}).get("provincia")})
    if not shareholders and not investees:
        return []
    ident = mdoc.get("identity") or {}
    parent = own.get("ultimate_parent") or next(iter(own.get("parents") or []), None)
    company = {
        "name": ident.get("legal_name"),
        "cif": mdoc.get("cif_normalized"),
        "type": "Holding" if investees else (_legal_form(ident.get("legal_name")) or "Sociedad"),
        "location": (mdoc.get("location") or {}).get("provincia"),
        "parent": _smart_case(parent["name"]) if (parent and parent.get("name")) else None,
    }
    b = ownership_block(company, shareholders, investees)
    b["data_lineage"] = {"source": "master:ownership", "date": now_iso()}
    return [b]


def _signal_insight_blocks(bundle: Dict, limit: int = 6) -> list:
    """Insight blocks from the company's real active signals (Signal Engine)."""
    out = []
    for sig in (bundle.get("signals") or [])[:limit]:
        sev = sig.get("severity", "")
        importance = "high" if sev in ("opportunity", "risk") else "medium"
        b = insight_block(
            title=sig.get("signal_type", ""),
            summary=sig.get("explanation", ""),
            importance=importance,
        )
        b["data_lineage"] = {"source": "signal-intelligence-v1",
                             "signal_id": sig.get("signal_id"), "date": now_iso()}
        out.append(b)
    return out


def _valuation_block(bundle: Dict):
    """A KPI block with the REAL, honest valuation (market_observed vs inferred_reference).
    Returns None when the engine reports insufficient data — never fabricates a number."""
    val = bundle.get("valuation", {}) or {}
    method = val.get("method")
    if not method or method == "insufficient_data":
        return None
    ev = val.get("enterprise_value") or val.get("equity_value") or val.get("ev")
    if not ev:
        return None
    basis = val.get("multiple_basis", "")
    basis_label = "múltiplo de mercado real" if basis == "market_observed" else "múltiplo de referencia inferido"
    b = kpi_block("Valoración orientativa (EV)", _es(f"{ev:,.0f}"), "€",
                  commentary=f"Método: {method} · {basis_label}")
    b["data_lineage"] = {"source": _FIN, "calculation": "valuation",
                         "multiple_basis": basis, "confidence": val.get("confidence"), "date": now_iso()}
    return b


def _pctile(sorted_vals: list, x: float) -> Optional[float]:
    """Percentil (0-1) de x dentro de sorted_vals (fracción de la muestra por debajo)."""
    if not sorted_vals or x is None:
        return None
    below = sum(1 for v in sorted_vals if v is not None and v < x)
    return below / len(sorted_vals)


def _valuation_scenarios_blocks(bundle: Dict, peers: list) -> dict:
    """Valoración orientativa al estilo del front de arroba (Valuo): Quality Score con
    percentiles de posicionamiento (margen EBITDA 50 % · ingresos/empleado 35 % · salud de
    balance 15 %), múltiplo = 4x + (quality/100)·(8x−4x), factor de comprador, y escenarios
    Bajo/Medio/Alto con Enterprise Value y Equity Value. Todo determinista sobre datos reales;
    el asesor puede ajustar múltiplo, EBITDA base (reportado/ajustado) y tipo de comprador.

    Devuelve {'score': [...], 'scenarios': [...], 'benchmark': [...]} para repartir en slides.
    Devuelve {} cuando no hay EBITDA ni comparables suficientes."""
    import statistics
    ident = bundle.get("identity") or {}
    name = ident.get("name") or "La compañía"
    kp = bundle.get("kpis", {}) or {}
    pts = sorted([p for p in ((bundle.get("evolution") or {}).get("points") or []) if p.get("year")],
                 key=lambda x: x["year"])
    last = pts[-1] if pts else {}

    # ── EBITDA base (reportado) + media 3 años ──
    ebitda = kp.get("ebitda")
    if ebitda is None:
        ebitda = last.get("ebitda")
    if not ebitda or ebitda <= 0:
        return {}
    ebitdas = [p.get("ebitda") for p in pts if p.get("ebitda") is not None]
    ebitda_avg = (sum(ebitdas[-3:]) / len(ebitdas[-3:])) if ebitdas else None

    # ── Deuda financiera neta (para el puente EV → Equity) ──
    net_debt = last.get("net_financial_position")

    # ── Percentiles de posicionamiento vs comparables del sector ──
    peers = peers or []
    n_comp = len(peers)
    margins = sorted([p["margin"] for p in peers if p.get("margin") is not None])
    rpes = sorted([p["rpe"] for p in peers if p.get("rpe") is not None])
    sols = sorted([p["solvency"] for p in peers if p.get("solvency") is not None])

    subj_margin = kp.get("ebitda_margin")
    subj_rpe = kp.get("revenue_per_employee")
    subj_sol = kp.get("solvency")
    if subj_sol is None and last.get("equity") and last.get("total_assets"):
        subj_sol = last["equity"] / last["total_assets"]

    p_margin = _pctile(margins, subj_margin) if (margins and subj_margin is not None) else None
    p_rpe = _pctile(rpes, subj_rpe) if (rpes and subj_rpe is not None) else None
    p_sol = _pctile(sols, subj_sol) if (sols and subj_sol is not None) else None

    # ── Quality Score ponderado (renormaliza pesos con los ejes disponibles) ──
    axes_w = [(p_margin, 0.50), (p_rpe, 0.35), (p_sol, 0.15)]
    avail = [(p, w) for p, w in axes_w if p is not None]
    if avail:
        wsum = sum(w for _p, w in avail)
        quality = sum(p * w for p, w in avail) / wsum * 100
    else:
        quality = 50.0  # sin comparables: neutro

    # ── Múltiplo por calidad (4x–8x) + factor de comprador (Financiero = 1.00x) ──
    buyer_factor = 1.00
    base_mult = (4 + (quality / 100) * (8 - 4)) * buyer_factor
    lo_mult = max(4.0, base_mult - 1.0)
    hi_mult = min(8.0, base_mult + 1.0)

    def _ev(mult):
        return mult * ebitda

    def _eq(ev):
        return (ev - net_debt) if net_debt is not None else None

    scen = [("Bajo", lo_mult), ("Medio", base_mult), ("Alto", hi_mult)]

    # ── Bloque 1: Quality Score + percentiles de posicionamiento ──
    score = [text_block("Posicionamiento y calidad (Quality Score)", "subhead")]
    qb = kpi_block("Quality Score", _es(f"{quality:.0f}"), "/100",
                   commentary=f"percentil ponderado · {n_comp} comparables del sector")
    qb["data_lineage"] = {"source": "master_companies (percentiles) + financial-intelligence",
                          "calculation": "0,50·P(margen)+0,35·P(ingresos/emp)+0,15·P(salud balance)",
                          "date": now_iso()}
    score.append(qb)
    for lbl, pv, comm in [
        ("Margen EBITDA", p_margin, "rentabilidad operativa vs sector"),
        ("Ingresos / empleado", p_rpe, "productividad vs sector"),
        ("Salud de balance", p_sol, "autonomía financiera (PN/activo) vs sector")]:
        if pv is not None:
            score.append(kpi_block(lbl, "P" + _es(f"{pv*100:.0f}"), "", commentary=comm))
    # Cómo se lee la puntuación
    score.append(insight_block(
        "Cómo se interpreta",
        f"El Quality Score (0–100) es el percentil ponderado de {name} dentro de sus comparables "
        f"de sector: 50 % margen EBITDA, 35 % ingresos por empleado y 15 % salud de balance. "
        f"Un valor de {quality:.0f} indica que la compañía supera aproximadamente a ese porcentaje "
        f"de las empresas del sector en calidad conjunta.", importance="medium"))

    # ── Bloque 2: escenarios (tabla) + gráfico EV ──
    scenarios = [text_block("Escenarios de valoración (EV/EBITDA)", "subhead")]
    base_lbl = "reportado"
    note = (f"EBITDA base: {_es(f'{ebitda:,.0f}')} € ({base_lbl}"
            + (f"; media 3 ej.: {_es(f'{ebitda_avg:,.0f}')} €" if ebitda_avg else "") + "). "
            f"Tipo de comprador: financiero (factor 1,00x). Múltiplo sugerido {_es(f'{base_mult:,.1f}')}x "
            f"(rango {_es(f'{lo_mult:,.1f}')}x–{_es(f'{hi_mult:,.1f}')}x). El asesor puede ajustar el "
            f"EBITDA base (reportado/ajustado), el múltiplo y el tipo de comprador.")
    scenarios.append(text_block(note, style="body"))
    rows = []
    for lbl, mult in scen:
        ev = _ev(mult); eq = _eq(ev)
        rows.append([lbl, _es(f"{mult:,.1f}") + "x", _es(f"{ev:,.0f}") + " €",
                     (_es(f"{eq:,.0f}") + " €") if eq is not None else "n/d"])
    tb = table_block("Resumen de escenarios",
                     ["Escenario", "Múltiplo", "Enterprise Value", "Equity Value (aprox.)"], rows)
    tb["data_lineage"] = {"source": "financial-intelligence + comparables",
                          "calculation": "EV = múltiplo × EBITDA; Equity = EV − deuda financiera neta",
                          "date": now_iso()}
    scenarios.append(tb)
    # Gráfico de barras Enterprise Value por escenario (par con explicación)
    ev_bars = [{"label": lbl, "value": _ev(mult)} for lbl, mult in scen]
    cev = chart_block("Enterprise Value por escenario", "bar", {"bars": ev_bars, "fmt": "millions"},
                      {"pair": True, "pair_width": _CHART_COL, "pair_align": "flex-start", "max_width": "100%"})
    cev["data_lineage"] = {"source": "financial-intelligence", "calculation": "EV = múltiplo × EBITDA", "date": now_iso()}
    scenarios.append(cev)
    ev_mid = _ev(base_mult); eq_mid = _eq(ev_mid)
    exp_parts = [f"En el escenario medio ({_es(f'{base_mult:,.1f}')}x) el Enterprise Value orientativo es "
                 f"{_es(f'{ev_mid:,.0f}')} €"]
    if eq_mid is not None:
        etiqueta = "deuda financiera neta" if (net_debt or 0) >= 0 else "caja neta"
        exp_parts.append(f"que, descontada la {etiqueta} de {_es(f'{abs(net_debt):,.0f}')} €, "
                         f"equivale a un Equity Value aproximado de {_es(f'{eq_mid:,.0f}')} €")
    scenarios.append(insight_block("Lectura de la valoración", ", ".join(exp_parts) + ".", importance="high"))

    # ── Bloque 3: radar vs mediana de categoría + metodología ──
    benchmark = [text_block("Benchmark vs. mediana de la categoría", "subhead")]
    axes = ["Quality Score", "Margen EBITDA", "Ingresos/empleado", "Salud balance"]
    emp_vals = [quality,
                (p_margin * 100 if p_margin is not None else 50),
                (p_rpe * 100 if p_rpe is not None else 50),
                (p_sol * 100 if p_sol is not None else 50)]
    med_vals = [50, 50, 50, 50]
    cr = chart_block("", "radar",
                     {"axes": axes,
                      "series": [{"name": "Empresa", "color": "#378ADD", "values": emp_vals},
                                 {"name": "Mediana categoría", "color": "#EF9F27", "values": med_vals}],
                      "max_value": 100},
                     {"pair": True, "pair_width": "440px", "pair_align": "flex-start"})
    cr["data_lineage"] = {"source": "master_companies (percentiles de sector)", "date": now_iso()}
    benchmark.append(cr)
    benchmark.append(insight_block(
        "Posición relativa",
        f"El radar compara a {name} (percentiles) con la mediana de su categoría (P50 en cada eje). "
        f"El área que sobresale de la línea naranja marca las dimensiones en las que la compañía bate "
        f"a la mediana del sector.", importance="medium"))
    metod = (
        "Metodología (cálculo automático). Quality Score (0–100): percentil ponderado en la categoría — "
        "50 % margen EBITDA, 35 % ingresos por empleado, 15 % salud de balance (patrimonio neto/activo). "
        "Múltiplo: 4x + (quality/100)·(8x−4x), ajustado por el factor de tipo de comprador (financiero 1,00x; "
        "estratégico >1,00x). Escenarios: múltiplo base ±1,0x, acotado al rango 4x–8x. Enterprise Value = "
        "múltiplo × EBITDA base; Equity Value ≈ Enterprise Value − deuda financiera neta. Son referencias "
        "orientativas sobre datos reales de Iberinform y comparables de sector; no constituyen una fairness "
        "opinion ni sustituyen una due diligence de valoración.")
    mb = text_block(metod, style="legal")
    mb["data_lineage"] = {"source": "metodología de valoración (composer)", "date": now_iso()}
    benchmark.append(mb)
    # Contraste con el motor honesto (si aporta múltiplo de mercado observado)
    vb = _valuation_block(bundle)
    if vb:
        benchmark.append(vb)

    return {"score": score, "scenarios": scenarios, "benchmark": benchmark,
            "quality": quality, "base_mult": base_mult, "ev_mid": ev_mid, "eq_mid": eq_mid}


async def compose_sector_report(cnae_code: str, brand_id: str = "brand_bud",
                                user: str = None) -> Dict:
    """Compose a full sector report from platform data."""
    from services.cnae_catalog import CNAE_DIVISIONS, get_section_for_division

    cnae_label = resolve_cnae_label(cnae_code, fallback=cnae_code)
    section_code = get_section_for_division(cnae_code)

    # Gather data from all sources
    econ = await _get_economic_profile(cnae_code)
    await _get_sector_intelligence(cnae_code)  # warm cache
    brand = await _get_brand(brand_id)

    doc = new_document(
        title=f"Informe Sectorial — CNAE {cnae_code}: {cnae_label}",
        template_id="tpl_sector_report",
        brand_id=brand_id,
        created_by=user,
        description=f"Informe de inteligencia sectorial para CNAE {cnae_code}",
    )

    # Section 1: Cover
    s1 = new_section("Portada", 1, [
        cover_block(
            title=cnae_label,
            subtitle=f"Informe Sectorial CNAE {cnae_code} — Seccion {section_code}",
            logo=brand.get("logo"),
        ),
    ])

    # Section 2: KPIs
    kpis = []
    if econ.get("revenue"):
        kpis.append(kpi_block("Revenue medio", f"{econ['revenue']['value']:,.0f}", "EUR",
                              variation=f"{econ.get('revenue_growth',{}).get('yoy_pct','')}% YoY" if econ.get('revenue_growth') else None))
    if econ.get("employment"):
        kpis.append(kpi_block("Empleados medio", f"{econ['employment']['value']:.0f}", "personas"))
    if econ.get("active_companies_national"):
        kpis.append(kpi_block("Empresas activas", f"{econ['active_companies_national']['value']:,.0f}", "empresas"))
    if econ.get("exports_eur"):
        kpis.append(kpi_block("Exportaciones", f"{econ['exports_eur']['value']:,.0f}", "EUR"))
    if econ.get("borme_events"):
        kpis.append(kpi_block("Eventos BORME", f"{econ['borme_events']['value']}", "actos mercantiles"))
    if econ.get("procurement_contracts"):
        kpis.append(kpi_block("Contratos publicos", f"{econ['procurement_contracts']['value']}", "contratos"))

    s3 = new_section("KPIs del Sector", 3, kpis)

    # Section 3: Trade
    trade_kpis = []
    if econ.get("exports_eur"):
        trade_kpis.append(kpi_block("Exportaciones", f"{econ['exports_eur']['value']:,.0f}", "EUR"))
    if econ.get("imports_eur"):
        trade_kpis.append(kpi_block("Importaciones", f"{econ['imports_eur']['value']:,.0f}", "EUR"))
    if econ.get("trade_balance_eur"):
        val = econ['trade_balance_eur']['value']
        trade_kpis.append(kpi_block("Saldo comercial", f"{val:,.0f}", "EUR",
                                    commentary="Superavit" if val > 0 else "Deficit"))
    s6 = new_section("Comercio Exterior", 6, trade_kpis) if trade_kpis else None

    # Section 4: Procurement
    proc_blocks = []
    if econ.get("procurement_contracts"):
        proc_blocks.append(kpi_block("Contratos adjudicados", f"{econ['procurement_contracts']['value']}", "contratos"))
    if econ.get("procurement_amount_eur"):
        proc_blocks.append(kpi_block("Importe adjudicado", f"{econ['procurement_amount_eur']['value']:,.0f}", "EUR"))
    s7 = new_section("Contratacion Publica", 7, proc_blocks) if proc_blocks else None

    # Section 5: Signals
    signal_blocks = []
    for sig in econ.get("signals", []):
        signal_blocks.append(insight_block(
            title=sig.get("signal_type", ""),
            summary=sig.get("description", ""),
            importance="high" if sig.get("confidence", 0) > 0.85 else "medium",
            source_ref=", ".join(sig.get("sources_used", [])),
        ))
    s8 = new_section("Tendencias y Senales", 8, signal_blocks) if signal_blocks else None

    # Section 6: AI-generated Executive Summary + Conclusions
    ai_context = {
        "cnae_code": cnae_code, "cnae_label": cnae_label,
        "revenue": econ.get("revenue"), "employment": econ.get("employment"),
        "exports": econ.get("exports_eur"), "imports": econ.get("imports_eur"),
        "active_companies": econ.get("active_companies_national"),
        "trend": econ.get("trend"), "signals": [s.get("signal_type") for s in econ.get("signals", [])],
    }

    ai_result = await generate_summary(ai_context, doc_type="sector_report", document_id=doc["document_id"])

    exec_summary = ai_result.get("executive_summary", "")
    key_findings = ai_result.get("key_findings", [])
    conclusion = ai_result.get("conclusion", "")

    s2_blocks = []
    if exec_summary:
        s2_blocks.append(text_block(exec_summary, style="executive_summary"))
        s2_blocks[-1]["data_lineage"] = {"source": "ai", "model": "gpt-5.2", "task": "executive_summary", "date": now_iso()}
    for finding in key_findings:
        s2_blocks.append(insight_block("Hallazgo clave", finding, importance="high"))
        s2_blocks[-1]["data_lineage"] = {"source": "ai", "model": "gpt-5.2", "task": "key_findings", "date": now_iso()}
    s2 = new_section("Resumen Ejecutivo", 2, s2_blocks)

    s9_blocks = []
    if conclusion:
        s9_blocks.append(text_block(conclusion, style="conclusion"))
        s9_blocks[-1]["data_lineage"] = {"source": "ai", "model": "gpt-5.2", "task": "conclusion", "date": now_iso()}
    for rec in ai_result.get("recommendations", []):
        s9_blocks.append(insight_block("Recomendacion", rec, importance="medium"))
    s9 = new_section("Conclusiones", 9, s9_blocks)

    # Assemble
    doc["sections"] = [s for s in [s1, s2, s3, s6, s7, s8, s9] if s]
    doc["metadata"] = {
        "cnae_code": cnae_code, "cnae_label": cnae_label, "section": section_code,
        "sources_used": econ.get("sources_available", []),
        "ai_models_used": ["gpt-5.2"],
    }
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()

    # Persist
    await db.docstudio_documents.insert_one(doc)

    return doc


async def compose_company_profile(company_id: str = None, cif: str = None,
                                  brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Compose a full company profile document. Fase 2: modern schema + real engines."""
    from services.cnae_catalog import CNAE_DIVISIONS

    bundle = await DA.company_intelligence(company_id or cif)
    if not bundle.get("found"):
        return {"error": "Company not found"}

    ident = bundle["identity"]
    name = ident.get("name", "Empresa")
    cnae = ident.get("cnae_code", "")
    cif_norm = bundle.get("cif_normalized", "—")

    # Sector economic context (already modern via economic_intelligence)
    econ = await _get_economic_profile(cnae) if cnae else {}

    doc = new_document(
        title=f"Ficha de Compañía — {name}",
        template_id="tpl_company_profile",
        brand_id=brand_id,
        created_by=user,
        description=f"Perfil de {name}",
    )

    # Cover
    s1 = new_section("Portada", 1, [
        cover_block(title=name, subtitle=f"CIF: {cif_norm} — CNAE {cnae}"),
    ])

    # Company KPIs from the real Financial Engine
    company_kpis = _company_kpi_blocks(bundle)
    if cnae:
        company_kpis.append(kpi_block("Sector", resolve_cnae_label(cnae, fallback=cnae), f"CNAE {cnae}"))
    if ident.get("provincia"):
        company_kpis.append(kpi_block("Provincia", ident["provincia"], ""))
    s3 = new_section("Datos Generales", 3, company_kpis)

    # General info table
    info_rows = [["CIF", cif_norm], ["Razón social", name]]
    if cnae:
        info_rows.append(["Sector CNAE", f"{cnae} — {resolve_cnae_label(cnae, fallback='')}"])
    if ident.get("provincia"):
        info_rows.append(["Provincia", ident["provincia"]])
    s3["blocks"].append(table_block("Información general", ["Campo", "Valor"], info_rows))

    # Curated financial detail: ratios table + multi-year evolution + sector percentiles
    fin_detail = await _enriched_financial_blocks(bundle)
    s_fin = new_section("Análisis Financiero", 5, fin_detail) if fin_detail else None

    # Active signals (Signal Engine) — real, not sector-generic
    signal_blocks = _signal_insight_blocks(bundle)
    s4 = new_section("Señales Activas", 4, signal_blocks) if signal_blocks else None

    # AI summary (Claude)
    kpis = bundle.get("kpis", {})
    ai_context = {
        "company_name": name, "cif": cif_norm, "cnae": cnae,
        "revenue": kpis.get("revenue"), "employees": (bundle.get("statements") or {}).get("employees"),
        "ebitda_margin": kpis.get("ebitda_margin"), "growth": kpis.get("revenue_growth_yoy"),
        "assessment": bundle.get("assessment"),
        "sector_trend": econ.get("trend"),
        "active_signals": [s.get("signal_type") for s in bundle.get("signals", [])],
    }
    ai_result = await generate_summary(ai_context, doc_type="company_profile", document_id=doc["document_id"])

    s2_blocks = []
    if ai_result.get("executive_summary"):
        b = text_block(ai_result["executive_summary"], style="executive_summary")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "company_summary", "date": now_iso()}
        s2_blocks.append(b)
    s2 = new_section("Resumen", 2, s2_blocks)

    s7_blocks = []
    if ai_result.get("conclusion"):
        s7_blocks.append(text_block(ai_result["conclusion"], style="conclusion"))
    s7 = new_section("Conclusión", 7, s7_blocks)

    doc["sections"] = [s for s in [s1, s2, s3, s_fin, s4, s7] if s]
    doc["metadata"] = {
        "master_id": bundle["master_id"], "cif": cif_norm, "cnae": cnae,
        "type": "company_profile", "financial_engine_used": True, "fact_locked": True, "schema": "modern",
    }
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()

    await db.docstudio_documents.insert_one(doc)
    return doc


# ══════════════════════════════════════════
# DATA FETCHERS
# ══════════════════════════════════════════

async def _get_economic_profile(cnae_code: str) -> Dict:
    from services.economic_intelligence import get_cnae_economic_profile
    try:
        return await get_cnae_economic_profile(cnae_code)
    except Exception:
        return {}


async def _get_sector_intelligence(cnae_code: str) -> Dict:
    sector = await db.sector_intelligence.find_one(
        {"cnae_code": cnae_code}, {"_id": 0}
    )
    return sector or {}


async def _get_brand(brand_id: str) -> Dict:
    brand = await db.docstudio_brands.find_one({"brand_id": brand_id}, {"_id": 0})
    if brand:
        return brand
    from docstudio.templates import BRANDS
    return BRANDS.get("bud_advisors", {})


async def compose_benchmark_report(cnae_code: str, brand_id: str = "brand_bud",
                                   user: str = None) -> Dict:
    """Compose a sector benchmark report with Financial Engine data."""
    from services.cnae_catalog import CNAE_DIVISIONS
    from docstudio.financial_engine import analyze_sector_benchmark

    cnae_label = resolve_cnae_label(cnae_code, fallback=cnae_code)
    econ = await _get_economic_profile(cnae_code)
    benchmark = await analyze_sector_benchmark(cnae_code)

    doc = new_document(
        title=f"Benchmark Report — CNAE {cnae_code}: {cnae_label}",
        template_id="tpl_benchmark", brand_id=brand_id, created_by=user,
    )

    s1 = new_section("Portada", 1, [
        cover_block(title="Benchmark Sectorial", subtitle=f"CNAE {cnae_code}: {cnae_label}"),
    ])

    # Benchmark KPIs from Financial Engine (deterministic)
    bm_kpis = []
    bm_kpis.append(kpi_block("Empresas comparables", str(benchmark.get("peers", 0)), "peers"))
    for metric, label, unit in [
        ("revenue", "Revenue mediana", "EUR"),
        ("ebitda", "EBITDA mediana", "EUR"),
        ("ebitda_margin", "Margen EBITDA mediana", "%"),
        ("employees", "Empleados mediana", "personas"),
        ("revenue_per_employee", "Revenue/empleado mediana", "EUR"),
    ]:
        q = benchmark.get(metric, {})
        if q and q.get("median") is not None:
            val = q["median"]
            display = f"{val:,.0f}" if unit == "EUR" else f"{val*100:.1f}" if metric == "ebitda_margin" else f"{val:,.0f}"
            b = kpi_block(label, display, unit)
            b["data_lineage"] = {"source": "financial_engine", "calculation": f"percentile_50({metric})", "date": now_iso()}
            bm_kpis.append(b)
    s3 = new_section("Benchmark del Sector", 3, bm_kpis)

    # Quartiles table
    quartile_rows = []
    for metric, label in [("revenue", "Revenue"), ("ebitda", "EBITDA"), ("ebitda_margin", "Margen EBITDA"), ("employees", "Empleados")]:
        q = benchmark.get(metric, {})
        if q:
            def fmt_val(v, m=metric):
                return f"{v*100:.1f}%" if m == "ebitda_margin" else f"{v:,.0f}"
            quartile_rows.append([label, fmt_val(q.get("min", 0)), fmt_val(q.get("q1", 0)), fmt_val(q.get("median", 0)), fmt_val(q.get("q3", 0)), fmt_val(q.get("max", 0))])
    s4 = new_section("Distribucion Estadistica", 4, [
        table_block("Cuartiles sectoriales", ["Metrica", "Min", "Q1", "Mediana", "Q3", "Max"], quartile_rows),
    ]) if quartile_rows else None

    # AI summary
    ai_context = {"cnae_code": cnae_code, "cnae_label": cnae_label, "benchmark": benchmark,
                  "trend": econ.get("trend"), "sources": econ.get("sources_available", [])}
    ai_result = await generate_summary(ai_context, doc_type="sector_report", document_id=doc["document_id"])

    s2 = new_section("Resumen Ejecutivo", 2, [])
    if ai_result.get("executive_summary"):
        b = text_block(ai_result["executive_summary"], style="executive_summary")
        b["data_lineage"] = {"source": "ai", "model": "gpt-5.2", "task": "benchmark_summary", "date": now_iso()}
        s2["blocks"].append(b)

    s5 = new_section("Conclusiones", 5, [])
    if ai_result.get("conclusion"):
        b = text_block(ai_result["conclusion"], style="conclusion")
        b["data_lineage"] = {"source": "ai", "model": "gpt-5.2", "task": "benchmark_conclusion", "date": now_iso()}
        s5["blocks"].append(b)

    doc["sections"] = [s for s in [s1, s2, s3, s4, s5] if s]
    doc["metadata"] = {"cnae_code": cnae_code, "type": "benchmark", "peers": benchmark.get("peers", 0)}
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


def _investment_thesis_text(name: str, bundle: Dict) -> str:
    """Tesis de inversión reglada (fallback sin IA) a partir de cifras reales."""
    import statistics
    kp = bundle.get("kpis", {}) or {}
    parts = [f"{name} presenta un perfil de inversión atractivo"]
    cagr = kp.get("revenue_cagr")
    if cagr and cagr > 0:
        parts.append(f"apoyado en un crecimiento sostenido (CAGR de ingresos del {_pct(cagr, 0)})")
    mar = kp.get("ebitda_margin")
    if mar is not None:
        parts.append(f"y una rentabilidad probada (margen EBITDA del {_pct(mar)})")
    frase = " ".join(parts) + "."
    rpe = kp.get("revenue_per_employee")
    if rpe:
        frase += (f" La productividad ({_es(f'{rpe:,.0f}')} € por empleado) y la posición en su sector "
                  f"refuerzan la calidad del modelo de negocio.")
    frase += (" La operación permitiría a un inversor capturar valor mediante crecimiento orgánico, "
              "mejora operativa y adquisiciones selectivas. [Editable por el analista.]")
    return frase


def _financial_kpis_blocks(bundle: Dict) -> list:
    """Cuadro de KPIs financieros (estilo dashboard) con valor real + referencia saludable.
    Usa las métricas que el motor ya calcula (sin inventar): crecimiento, márgenes, Rule of 40,
    apalancamiento, autonomía financiera, productividad y circulante."""
    kp = bundle.get("kpis", {}) or {}
    ratios = bundle.get("ratios", {}) or {}
    pts = sorted([p for p in ((bundle.get("evolution") or {}).get("points") or []) if p.get("year")],
                 key=lambda x: x["year"])
    last = pts[-1] if pts else {}
    rows = []

    def add(k, val, ref):
        if val not in (None, ""):
            rows.append([k, val, ref])

    rev = kp.get("revenue")
    add("Ingresos", (_es(f"{rev:,.0f}") + " €") if rev else None, "escala y tendencia (ver crecimiento)")
    g = kp.get("revenue_growth_yoy")
    add("Crecimiento de ingresos (YoY)", _pct(g, 1, signed=True) if g is not None else None,
        "sostenido y positivo; >10 % se lee como dinámico")
    cagr = kp.get("revenue_cagr")
    add("CAGR de ingresos", _pct(cagr, 1) if cagr is not None else None, "crecimiento estructural a medio plazo")
    gm = last.get("gross_margin")
    add("Margen bruto", _pct(gm) if gm is not None else None, "cuanto mayor, más valor por venta")
    m = kp.get("ebitda_margin")
    add("Margen EBITDA", _pct(m) if m is not None else None, "rentabilidad operativa; comparar con el sector")
    eb = kp.get("ebitda")
    add("EBITDA", (_es(f"{eb:,.0f}") + " €") if eb is not None else None, "base de la valoración por múltiplo")
    growth40 = g if g is not None else cagr
    if growth40 is not None and m is not None:
        r40 = (growth40 + m) * 100
        add("Rule of 40 (crecimiento % + margen EBITDA %)", _es(f"{r40:,.0f}") + " %",
            "≥ 40 es el filtro rápido estándar")
    nd = last.get("net_financial_position")
    if nd is not None and eb:
        add("Deuda financiera neta / EBITDA", _es(f"{nd/eb:,.1f}") + "x",
            "<3x cómodo; negativo = caja neta")
    sol = kp.get("solvency")
    add("Autonomía financiera (PN/activo)", _pct(sol, 0) if sol is not None else None,
        "cuanto mayor, más solidez de balance")
    rpe = kp.get("revenue_per_employee")
    add("Ingresos por empleado", (_es(f"{rpe:,.0f}") + " €") if rpe else None,
        "productividad; comparar con el sector")
    ccc = (ratios.get("cash_conversion_cycle") or {}).get("value")
    add("Ciclo de conversión de caja", (_es(f"{ccc:,.0f}") + " días") if ccc is not None else None,
        "cuanto menor, mejor gestión del circulante")

    out = [text_block("KPIs financieros", "subhead")]
    if rows:
        tb = table_block("", ["KPI", "Valor", "Referencia saludable"], rows)
        tb["data_lineage"] = {"source": _FIN, "calculation": "KPIs financieros", "date": now_iso()}
        out.append(tb)
    else:
        out.append(text_block("[A completar por el usuario: KPIs financieros del negocio.]", "body"))
    out.append(text_block("Referencias orientativas; deben leerse junto al sector y el momento de la "
                          "compañía. [El usuario puede añadir KPIs propios del modelo — p. ej. MRR, ARR, "
                          "LTV/CAC, NRR o Magic Number si el negocio es recurrente.]", "legal"))
    return out


def _business_model_blocks(bundle: Dict, prof: Dict = None) -> list:
    """Modelo de negocio y problema que resuelve, dentro de 'Compañía'. Usa el perfil semántico
    (propuesta de valor / objeto social) para el relato y deja editable lo que no consta."""
    prof = prof or {}
    ident = bundle.get("identity") or {}
    name = ident.get("name") or "La compañía"
    vp = (prof.get("value_proposition") or {}).get("value")
    obj = ident.get("objeto_social")
    out = [text_block("Modelo de negocio y problema que resuelve", "subhead")]
    # Problema que resuelve
    out.append(text_block("Problema que resuelve", "subhead"))
    out.append(text_block(
        (f"{name} atiende una necesidad concreta de su mercado en {ident.get('cnae_description') or 'su sector'}. "
         "[A completar por el usuario: dolor del cliente y por qué existe la compañía.]"), style="body"))
    # Solución / propuesta de valor
    out.append(text_block("Cómo lo resuelve (propuesta de valor)", "subhead"))
    if vp:
        b = text_block(vp, style="executive_summary")
        b["data_lineage"] = {"source": "semantic-intelligence-v1", "task": "value_proposition", "date": now_iso()}
        out.append(b)
    elif obj:
        out.append(text_block(f"Actividad (objeto social): {_smart_case(obj.strip())}", style="conclusion"))
    else:
        out.append(text_block("[A completar por el usuario: propuesta de valor y solución que ofrece.]", "body"))
    # Modelo de negocio / ingresos
    out.append(text_block("Modelo de negocio e ingresos", "subhead"))
    caps = [c.get("value") for c in (prof.get("capabilities") or []) if isinstance(c, dict) and c.get("value")]
    for c in caps[:4]:
        out.append(text_block(_smart_case(c), "bullet"))
    out.append(text_block("[A completar por el usuario: cómo genera ingresos (recurrente/proyecto/mixto), "
                          "clientes objetivo y palancas de escalabilidad del modelo.]", "body"))
    return out


def _deal_snapshot(bundle: Dict) -> Dict:
    """Deal Snapshot — estándar bud advisors (6 elementos), idéntico en todos los documentos.
    Opportunity se rellena con dato real; el resto son campos de operación editables por el asesor."""
    kp = bundle.get("kpis", {}) or {}
    cagr = kp.get("revenue_cagr"); m = kp.get("ebitda_margin")
    bits = []
    if cagr is not None and cagr > 0:
        bits.append(f"CAGR +{_pct(cagr, 0)}")
    if m is not None:
        bits.append(f"margen EBITDA {_pct(m)}")
    opp = "Compañía rentable y en crecimiento" + (f" ({', '.join(bits)})" if bits else "") + "."
    succ = any(("suces" in (s.get("signal_type") or "").lower()) or (s.get("severity") == "succession")
               for s in (bundle.get("signals") or []))
    seller = ("Relevo generacional / búsqueda de un socio que dé continuidad al proyecto."
              if succ else "Cristalización del valor y entrada de un socio para acelerar el crecimiento.")
    items = [
        {"label": "Opportunity", "text": opp},
        {"label": "Transaction", "text": "[Definir: venta 100 % · mayoría · minoría · ampliación de capital.]"},
        {"label": "Seller", "text": seller + " [Ajustar al mandato real.]"},
        {"label": "Buyer Fit", "text": "Comprador estratégico, private equity o family office con capacidad de crecimiento."},
        {"label": "Management", "text": "[Definir: rol y continuidad del equipo directivo tras la operación.]"},
        {"label": "Process", "text": "[Definir: fase actual del proceso y próximos hitos.]"},
    ]
    b = deal_snapshot_block(items, title="Deal Snapshot")
    b["data_lineage"] = {"source": "bud advisors — Deal Snapshot estándar", "date": now_iso()}
    return b


def _transaction_overview_sections(bundle: Dict, benchmark: Dict, start_order: int = 30) -> list:
    """Capítulo Transaction Overview completo (5.1–5.6). Devuelve una lista de secciones ya
    numeradas. Contenido de operación editable por el asesor, con ganchos de dato real."""
    kp = bundle.get("kpis", {}) or {}
    name = (bundle.get("identity") or {}).get("name") or "La compañía"
    cagr = kp.get("revenue_cagr"); m = kp.get("ebitda_margin")
    o = start_order

    # 5.1 Transaction Summary
    s51 = new_section("Transaction Overview · 5.1 Transaction Summary", o, [
        text_block("5.1 Resumen de la transacción", "subhead"),
        text_block("Tipo de operación: [venta 100 % · mayoría · minoría · ampliación de capital — a definir].", "bullet"),
        text_block("Alcance de la transacción: [porcentaje ofrecido y control resultante — a definir].", "bullet"),
        text_block("Activos incluidos: [negocio, marcas, inmuebles, filiales — a definir].", "bullet"),
        text_block("Perímetro: [sociedades y actividades dentro/fuera del perímetro — a definir].", "bullet"),
    ]); o += 1

    # 5.2 Investment Opportunity (real hooks)
    s52_blocks = [text_block("5.2 Oportunidad de inversión", "subhead")]
    for c in _positive_signal_cards(bundle)[:3]:
        s52_blocks.append(c)
    fit = "Encaje estratégico: plataforma consolidada en su sector con recorrido de crecimiento orgánico e inorgánico."
    s52_blocks.append(insight_block("Encaje estratégico", fit, importance="medium"))
    s52 = new_section("Transaction Overview · 5.2 Investment Opportunity", o, s52_blocks); o += 1

    # 5.3 Seller Objectives
    succ = any(("suces" in (s.get("signal_type") or "").lower()) or (s.get("severity") == "succession")
               for s in (bundle.get("signals") or []))
    mot = ("Relevo generacional / sucesión ordenada de la propiedad." if succ
           else "Cristalización del valor construido e incorporación de un socio para crecer.")
    s53 = new_section("Transaction Overview · 5.3 Seller Objectives", o, [
        text_block("5.3 Objetivos del vendedor", "subhead"),
        text_block(f"Motivación de la operación: {mot}", "bullet"),
        text_block("Objetivos del accionista: [liquidez, crecimiento, diversificación, sucesión — a definir].", "bullet"),
        text_block("Continuidad prevista: [permanencia o salida progresiva de los actuales propietarios — a definir].", "bullet"),
    ]); o += 1

    # 5.4 Ideal Buyer Profile
    s54 = new_section("Transaction Overview · 5.4 Ideal Buyer Profile", o, [
        text_block("5.4 Perfil de comprador ideal", "subhead"),
        insight_block("Comprador estratégico", "Industrial del sector o adyacente que busque escala, "
                      "capacidades o acceso a mercado.", importance="low"),
        insight_block("Private Equity", "Fondo con tesis de buy & build y capacidad de acompañar el crecimiento.",
                      importance="low"),
        insight_block("Family Office", "Inversor de largo plazo orientado a compañías rentables y estables.",
                      importance="low"),
        text_block("Perfil internacional y capacidades deseadas: [red comercial, I+D, capacidad financiera — a definir].", "bullet"),
    ]); o += 1

    # 5.5 Indicative Deal Structure
    s55 = new_section("Transaction Overview · 5.5 Indicative Deal Structure", o, [
        text_block("5.5 Estructura indicativa de la operación", "subhead"),
        text_block("Venta total o parcial: [porcentaje objetivo — a definir].", "bullet"),
        text_block("Reinversión (rollover) de los vendedores: [importe o % — a definir].", "bullet"),
        text_block("Earn-out: [si aplica, importe y métricas — a definir].", "bullet"),
        text_block("Exclusividad: [periodo y condiciones — a definir].", "bullet"),
        text_block("Otros aspectos relevantes: [garantías, condiciones suspensivas, tratamiento de la deuda — a definir].", "bullet"),
    ]); o += 1

    # 5.6 Transaction Process
    s56 = new_section("Transaction Overview · 5.6 Transaction Process", o,
                      _process_timeline_blocks(bundle)); o += 1

    return [s51, s52, s53, s54, s55, s56]


def _equity_story_blocks(bundle: Dict) -> list:
    """Equity story sell-side: por qué esta compañía es una buena adquisición (dato real + editable)."""
    kp = bundle.get("kpis", {}) or {}
    out = [text_block("Por qué esta compañía (equity story)", "subhead")]
    cagr = kp.get("revenue_cagr"); m = kp.get("ebitda_margin"); rpe = kp.get("revenue_per_employee")
    if cagr is not None and cagr > 0:
        out.append(text_block(f"Crecimiento sostenido: CAGR de ingresos del {_pct(cagr, 0)}.", "bullet"))
    if m is not None:
        out.append(text_block(f"Rentabilidad probada: margen EBITDA del {_pct(m)}.", "bullet"))
    if rpe:
        out.append(text_block(f"Productividad elevada: {_es(f'{rpe:,.0f}')} € de ingresos por empleado.", "bullet"))
    out.append(text_block("Posición consolidada en su sector y base de clientes con recurrencia.", "bullet"))
    out.append(text_block("Plataforma con recorrido de crecimiento orgánico e inorgánico (buy & build).", "bullet"))
    out.append(text_block("[A completar por el usuario: relato de la oportunidad — por qué ahora y por qué "
                          "esta compañía es única para el comprador adecuado.]", "body"))
    return out


def _internal_sources_annex() -> tuple:
    """Anexo INTERNO (no para el inversor): fuente y cálculo de cada métrica/ratio del documento.
    Devuelve dos listas de bloques (financieros de la compañía · sector, mercado y valoración),
    cada una con su aviso de uso interno."""
    def _warn():
        b = insight_block("USO INTERNO — no entregar al inversor",
                          "Página de trabajo del asesor. Documenta el origen y el cálculo de cada dato. "
                          "Eliminar antes de compartir el documento con el inversor.", importance="high")
        return b

    fin_rows = [
        ["Ingresos (cifra de negocios)", "Iberinform · Cuenta de PyG", "Importe neto de la cifra de negocios del ejercicio"],
        ["EBITDA", "Iberinform · PyG", "Resultado de explotación + amortizaciones"],
        ["Margen EBITDA", "Derivado", "EBITDA / Ingresos"],
        ["Margen bruto", "Derivado", "(Ingresos − Aprovisionamientos) / Ingresos"],
        ["Margen neto", "Derivado", "Resultado del ejercicio / Ingresos"],
        ["Crecimiento de ingresos (YoY)", "Derivado", "(Ingresos_t / Ingresos_t-1) − 1"],
        ["CAGR de ingresos", "Derivado", "(Ingresos_final / Ingresos_inicial)^(1/n) − 1"],
        ["Empleados", "Iberinform", "Plantilla del ejercicio"],
        ["Ingresos por empleado", "Derivado", "Ingresos / Empleados"],
        ["Patrimonio neto · Activo total", "Iberinform · Balance", "Partidas de balance del ejercicio"],
        ["Autonomía financiera (solvencia)", "Derivado", "Patrimonio neto / Activo total"],
        ["Fondo de maniobra", "Derivado", "Activo corriente − Pasivo corriente"],
        ["Deuda financiera neta (PFN)", "Derivado", "Deuda financiera (L/P + C/P) − Tesorería"],
        ["Deuda neta / EBITDA", "Derivado", "PFN / EBITDA"],
        ["ROE", "Derivado", "Resultado del ejercicio / Patrimonio neto"],
        ["Ciclo de conversión de caja", "Derivado", "DSO + DIO − DPO (días)"],
        ["Rule of 40", "Derivado", "Crecimiento ingresos % + Margen EBITDA %"],
        ["Tabla de ratios", "Iberinform (Datos_RATIOS) + cálculo", "Ratios entregados + derivados de balance/PyG"],
        ["Plan de negocio (proyecciones)", "Derivado", "Último ejercicio real × tasa (CAGR acotado ±3 p.p. por escenario)"],
    ]
    sec_rows = [
        ["Comparables (peers)", "master_companies (mismo CNAE sección)", "Empresas del sector con datos financieros"],
        ["Percentiles (margen, ing./empleado, salud balance)", "Derivado", "Rank de la métrica de la compañía frente a los peers"],
        ["Quality Score (0–100)", "Derivado", "0,50·P(margen) + 0,35·P(ing./empleado) + 0,15·P(salud balance)"],
        ["Benchmark Q1 · Mediana · Q3", "master_companies", "Cuartiles de la distribución del sector"],
        ["HHI / fragmentación", "Motor de fragmentación (E7)", "Índice Herfindahl-Hirschman sobre cuotas del sector"],
        ["Múltiplo EV/EBITDA", "Derivado", "4x + (Quality/100)·(8x − 4x) × factor de comprador"],
        ["Enterprise Value (EV)", "Derivado", "Múltiplo × EBITDA base"],
        ["Equity Value", "Derivado", "EV − Deuda financiera neta"],
        ["TAM (proxy)", "Economic Intelligence / DIRCE", "Empresas activas del sector × facturación media"],
        ["Contexto de mercado (exportaciones, contratos…)", "Economic Intelligence (DataComex, PLACSP, DIRCE)", "Agregados sectoriales del CNAE"],
    ]
    a = [_warn(), text_block("Anexo interno · Fuente y cálculo de los ratios (compañía)", "subhead"),
         table_block("", ["Métrica", "Fuente", "Cálculo"], fin_rows),
         text_block("Todos los importes financieros proceden de las cuentas de la compañía objetivo "
                    "(Iberinform); los marcados como «Derivado» se calculan a partir de esas partidas.", "legal")]
    b = [_warn(), text_block("Anexo interno · Fuente y cálculo (sector, mercado y valoración)", "subhead"),
         table_block("", ["Métrica", "Fuente", "Cálculo"], sec_rows),
         text_block("Los elementos comparativos (percentiles, benchmark, HHI) posicionan a la compañía "
                    "dentro de su sector; la valoración aplica el múltiplo calibrado por calidad sobre el "
                    "EBITDA propio de la compañía.", "legal")]
    return a, b


def _tam_sam_som_blocks(bundle: Dict, econ: Dict) -> list:
    """Estructura del mercado con marco TAM / SAM / SOM (círculos concéntricos, estilo pitch).
    Siembra el TAM con un proxy sectorial real (empresas activas × facturación media) cuando
    existe; SAM y SOM quedan como campos editables por el usuario."""
    ident = bundle.get("identity") or {}
    name = ident.get("name") or "La compañía"
    tam_val = None
    try:
        ac = (econ.get("active_companies_national") or {}).get("value")
        rv = (econ.get("revenue") or {}).get("value")
        if ac and rv:
            tam_val = ac * rv
    except Exception:
        tam_val = None
    tam_lbl = ("TAM ≈ " + _es(f"{tam_val/1e6:,.0f}") + " M€") if tam_val else "TAM = [€ ...]"
    items = [
        {"label": tam_lbl, "sublabel": "mercado total (proxy sectorial)", "frac": 1.0, "dashed": True},
        {"label": "SAM = [€ ...]", "sublabel": "mercado servible", "frac": 0.46},
        {"label": "SOM = [€ ...]", "sublabel": "mercado objetivo", "frac": 0.18},
    ]
    out = [text_block("Estructura del mercado (TAM · SAM · SOM)", "subhead")]
    ch = chart_block("", "nested_circles", {"items": items},
                     {"pair": True, "pair_width": "440px", "pair_align": "flex-start"})
    ch["data_lineage"] = {"source": "Economic Intelligence (proxy TAM) + campos editables", "date": now_iso()}
    out.append(ch)
    _tamtxt = (f"un mercado total (TAM) de referencia de {_es(f'{tam_val/1e6:,.0f}')} M€ (empresas activas del "
               f"sector × facturación media)" if tam_val else "un mercado total (TAM) a cuantificar")
    out.append(insight_block(
        "Marco de mercado",
        f"El diagrama sitúa a {name} en su mercado: TAM (total), SAM (segmento al que puede servir con su "
        f"propuesta actual) y SOM (cuota realista a capturar en el horizonte del plan). El motor estima "
        f"{_tamtxt}; el usuario define el SAM y el SOM con los criterios del proceso (geografía, segmento, "
        f"capacidad).", importance="medium"))
    out.append(text_block("[A completar por el usuario: importe de SAM y SOM, criterios de segmentación y "
                          "supuestos de cuota de mercado.]", "body"))
    return out


async def _team_structure_blocks(bundle: Dict, cif_norm: str) -> list:
    """Estructura del equipo: roster real (administradores/cargos) + composición de plantilla
    (si consta) + áreas funcionales editables."""
    ident = bundle.get("identity") or {}
    name = ident.get("name") or "La compañía"
    out = [text_block("Estructura del equipo", "subhead")]
    officers = await db.norm_officers.find({"cif_normalized": cif_norm}, {"_id": 0}).to_list(20)
    officers = [o for o in officers if o.get("person_name")]
    if officers:
        rows = [[_smart_case(o.get("person_name")), _smart_case(o.get("person_role") or "Administrador")]
                for o in officers[:10]]
        tb = table_block("Órgano de administración y cargos", ["Persona", "Cargo"], rows)
        tb["data_lineage"] = {"source": "master-v1 (norm_officers)", "date": now_iso()}
        out.append(tb)
    # Composición de plantilla (si consta)
    wf = ident.get("workforce") or {}
    plantilla = wf.get("total") or (bundle.get("statements") or {}).get("employees")
    comp_bits = []
    for k, lbl in [("men", "hombres"), ("women", "mujeres"), ("permanent", "fijos"), ("temporary", "temporales")]:
        if wf.get(k) is not None:
            comp_bits.append(f"{_es(f'{int(wf[k]):,}')} {lbl}")
    if plantilla:
        base = f"La plantilla asciende a {_es(f'{int(plantilla):,}')} profesionales"
        if comp_bits:
            base += " (" + ", ".join(comp_bits) + ")"
        out.append(text_block(base + ".", "bullet"))
    # Áreas funcionales (editable)
    out.append(text_block("Áreas funcionales", "subhead"))
    for a in ["Dirección General", "Financiera y Administración", "Comercial y Marketing",
              "Operaciones", "Tecnología / Producto"]:
        out.append(text_block(f"{a}: [responsable y dimensionamiento — a completar por el usuario].", "bullet"))
    out.append(text_block("[A completar por el usuario: organigrama por áreas, headcount por función y "
                          "plan de contratación asociado a la operación.]", "body"))
    return out


async def _captable_table_blocks(bundle: Dict, master_id: str) -> list:
    """Cap table (tabla accionistas + donut + post-operación) para el investment memo."""
    try:
        mdoc = await db.master_companies.find_one({"master_id": master_id}, {"_id": 0, "ownership": 1})
        own = (mdoc or {}).get("ownership") or {}
    except Exception:
        own = {}
    sh = [s for s in (own.get("shareholders") or []) if s.get("name")]
    parents = [p for p in (own.get("parents") or []) if p.get("name")]
    out = [text_block("Estructura de propiedad (cap table)", "subhead")]
    rows, segs = [], []
    for s in sh:
        pct = s.get("pct")
        rows.append([_smart_case(s["name"]), (_es(f"{pct:,.1f}") + " %") if pct is not None else "n/d"])
        if pct:
            segs.append({"label": _clip_name(s["name"], 22), "value": pct})
    if parents:
        for p in parents:
            if _smart_case(p["name"]) not in [r[0] for r in rows]:
                rows.append([_smart_case(p["name"]), "matriz"])
    if rows:
        tb = table_block("Accionariado actual", ["Accionista", "Participación"], rows)
        tb["data_lineage"] = {"source": "master-v1 (ownership)", "date": now_iso()}
        out.append(tb)
    _post = insight_block("Estructura post-operación",
                          "[A completar por el usuario: cap table resultante tras la entrada del inversor "
                          "(% de fundadores, inversor entrante y pool de empleados).]", importance="low")
    if len(segs) >= 1 and sum(x["value"] for x in segs) > 0:
        cd = chart_block("Distribución del capital", "donut", {"segments": segs},
                         {"pair": True, "pair_width": "420px", "pair_align": "flex-start"})
        cd["data_lineage"] = {"source": "master-v1 (ownership)", "date": now_iso()}
        out.append(cd)
        out.append(_post)  # emparejado a la derecha del donut → compacto
    else:
        if not rows:
            out.append(text_block("[A completar por el usuario: accionariado actual y % de cada socio.]", "body"))
        out.append(_post)
    return out


def _traction_blocks(bundle: Dict) -> list:
    """Tracción e hitos: evolución real (ingresos) + hitos (editables, con datos reales de apoyo)."""
    ident = bundle.get("identity") or {}
    name = ident.get("name") or "La compañía"
    kp = bundle.get("kpis", {}) or {}
    pts = sorted([p for p in ((bundle.get("evolution") or {}).get("points") or []) if p.get("year")],
                 key=lambda x: x["year"])
    out = [text_block("Tracción e hitos", "subhead")]
    bars = [{"label": str(p["year"]), "value": p.get("revenue")} for p in pts if p.get("revenue") is not None]
    if len(bars) >= 2:
        cb = chart_block("Evolución de ingresos", "bar", {"bars": bars, "fmt": "millions"},
                         {"pair": True, "pair_width": _CHART_COL, "pair_align": "flex-start", "max_width": "100%"})
        cb["data_lineage"] = {"source": _FIN, "calculation": "evolution.revenue", "date": now_iso()}
        out.append(cb)
        cagr = kp.get("revenue_cagr")
        parts = [f"{name} ha demostrado tracción con ingresos"]
        if cagr is not None:
            parts.append(f"creciendo a un CAGR del {_pct(cagr, 0)}")
        _r0 = _es(f"{bars[0]['value']/1e6:,.1f}"); _r1 = _es(f"{bars[-1]['value']/1e6:,.1f}")
        _y0 = bars[0]["label"]; _y1 = bars[-1]["label"]
        parts.append(f"pasando de {_r0} a {_r1} M€ entre {_y0} y {_y1}")
        out.append(insight_block("Prueba de progreso", ", ".join(parts) + ".", importance="high"))
    out.append(text_block("Hitos", "subhead"))
    out.append(text_block("Trayectoria y consolidación del negocio desde su constitución.", "bullet"))
    if kp.get("ebitda_margin") is not None:
        out.append(text_block(f"Rentabilidad probada con margen EBITDA del {_pct(kp['ebitda_margin'])}.", "bullet"))
    out.append(text_block("[A completar por el usuario: hitos comerciales, de producto, contrataciones clave, "
                          "premios o rondas anteriores, con su fecha.]", "body"))
    return out


async def _transaction_comps_blocks(bundle: Dict) -> list:
    """Múltiplos y transacciones comparables: referencia de sector (EV/EBITDA, EV/Revenue) +
    múltiplo observado de mercado (M&A Radar) si existe + EV implícito. Honesto: etiqueta
    'referencia inferida' vs 'observado'."""
    ident = bundle.get("identity") or {}
    section = ident.get("cnae_section")
    cnae = ident.get("cnae_code")
    kp = bundle.get("kpis", {}) or {}
    eb = kp.get("ebitda"); rev = kp.get("revenue")
    try:
        from services.skills_valuation import _resolve_multiples
        mult = _resolve_multiples(section)
    except Exception:
        mult = {"ev_ebitda": (6.0, 10.0), "ev_revenue": (0.8, 1.6)}
    ee = mult["ev_ebitda"]; er = mult["ev_revenue"]

    def impl(metric, lo, hi):
        if not metric:
            return "n/d"
        return _es(f"{metric*lo/1e6:,.1f}") + " – " + _es(f"{metric*hi/1e6:,.1f}") + " M€"

    rows = [
        ["EV/EBITDA — referencia del sector", f"{ee[0]:.1f}x – {ee[1]:.1f}x", impl(eb, *ee)],
        ["EV/Revenue — referencia del sector", f"{er[0]:.1f}x – {er[1]:.1f}x", impl(rev, *er)],
    ]
    observed = None
    try:
        from services.engines.financial import market_multiples as MM
        real = await MM.real_multiple_for_company(cnae)
        if real:
            for k in ("ev_ebitda_median", "ev_ebitda_aggregate", "ev_ebitda", "multiple"):
                if real.get(k):
                    observed = real[k]; break
    except Exception:
        observed = None
    if observed:
        rows.append(["EV/EBITDA — observado (M&A Radar)", f"{observed:.1f}x", impl(eb, observed, observed)])

    out = [text_block("Múltiplos y transacciones comparables", "subhead"),
           table_block("", ["Referencia", "Múltiplo", "EV implícito"], rows)]
    # Contexto M&A Radar (transacciones reales por categoría), si hay datos
    try:
        from services.category_valuations import get_cached_valuations
        cached = await get_cached_valuations()
        cats = [c for c in (cached.get("categories") or []) if c.get("ev_ebitda_aggregate")][:4]
        if cats:
            crows = [[_clip_name(c.get("category"), 34), f"{c['ev_ebitda_aggregate']:.1f}x",
                      str(c.get("deals_with_financials", 0))] for c in cats]
            out.append(text_block("Múltiplos observados en operaciones recientes (M&A Radar)", "subhead"))
            out.append(table_block("", ["Categoría", "EV/EBITDA", "Operaciones"], crows))
    except Exception:
        pass
    basis = "inferida" if not observed else "inferida + un múltiplo observado del M&A Radar"
    out.append(text_block(
        f"Los múltiplos de referencia del sector son una base {basis} (rango orientativo), no una tasación. "
        "[A completar por el usuario: transacciones precedentes concretas y comparables cotizadas relevantes "
        "para la operación.]", style="legal"))
    return out


def _exit_returns_blocks(bundle: Dict) -> list:
    """Retorno para el inversor y estrategia de salida (plantilla editable con apoyo del sector)."""
    out = [text_block("Retorno para el inversor y estrategia de salida", "subhead"),
           text_block("Vías de salida (exit)", "subhead"),
           text_block("Venta a un comprador estratégico (trade sale) del sector o adyacente.", "bullet"),
           text_block("Entrada de un socio financiero / secundario (private equity).", "bullet"),
           text_block("Recompra por los fundadores / management buy-out (MBO).", "bullet"),
           text_block("Posibles compradores", "subhead"),
           text_block("Consolidadores e industriales del sector y fondos con tesis de buy & build. "
                      "[A completar por el usuario con nombres concretos.]", "bullet"),
           text_block("Retorno esperado", "subhead"),
           text_block("[A completar por el usuario: horizonte de inversión, múltiplo esperado sobre capital "
                      "(MOIC) y TIR objetivo bajo escenarios conservador/base/optimista, con los supuestos de "
                      "crecimiento y múltiplo de salida.]", "body")]
    return out


def _gtm_blocks(bundle: Dict) -> list:
    """Go-to-market y unit economics (plantilla editable + dato real de productividad)."""
    kp = bundle.get("kpis", {}) or {}
    out = [text_block("Go-to-market y unit economics", "subhead"),
           text_block("Estrategia comercial", "subhead"),
           text_block("Canales de adquisición y proceso de venta (directo, partners, inbound…).", "bullet"),
           text_block("Segmentos y perfil de cliente objetivo.", "bullet"),
           text_block("Unit economics", "subhead")]
    rpe = kp.get("revenue_per_employee")
    if rpe:
        out.append(text_block(f"Productividad actual: {_es(f'{rpe:,.0f}')} € de ingresos por empleado (dato real).", "bullet"))
    out.append(text_block("[A completar por el usuario: CAC, LTV, ratio LTV/CAC, periodo de recuperación "
                          "(payback) del CAC y embudo de conversión.]", "body"))
    return out


def _moat_blocks(bundle: Dict, benchmark: Dict) -> list:
    """Ventaja competitiva / foso defensivo (plantilla editable + apoyo del posicionamiento)."""
    kp = bundle.get("kpis", {}) or {}
    out = [text_block("Ventaja competitiva y foso defensivo", "subhead")]
    m = kp.get("ebitda_margin")
    try:
        q = benchmark.get("ebitda_margin", {})
        if m is not None and q and q.get("median") is not None and m > q["median"]:
            out.append(insight_block("Rentabilidad superior al sector",
                f"El margen EBITDA ({_pct(m)}) supera la mediana del sector ({_pct(q['median'])}), señal de "
                f"poder de fijación de precios o eficiencia estructural.", importance="high"))
    except Exception:
        pass
    for t in ["Marca y reputación en el sector.",
              "Relaciones y contratos con clientes (costes de cambio).",
              "Know-how, tecnología o propiedad intelectual.",
              "Escala y eficiencia operativa."]:
        out.append(text_block(t + " [validar/ampliar por el usuario].", "bullet"))
    out.append(text_block("[A completar por el usuario: por qué la ventaja es sostenible y difícil de replicar.]", "body"))
    return out


def _roadmap_blocks(bundle: Dict) -> list:
    """Roadmap de producto / desarrollo (plantilla editable Now·Next·Later)."""
    return [
        text_block("Roadmap de producto y desarrollo", "subhead"),
        text_block("Ahora (0–12 meses)", "subhead"),
        text_block("[A completar por el usuario: iniciativas en curso y próximos lanzamientos.]", "body"),
        text_block("Siguiente (12–24 meses)", "subhead"),
        text_block("[A completar por el usuario: nuevas líneas, integraciones o mercados.]", "body"),
        text_block("Más adelante (24 meses+)", "subhead"),
        text_block("[A completar por el usuario: visión de producto a largo plazo.]", "body"),
    ]


def _cases_blocks(bundle: Dict) -> list:
    """Casos de cliente y prueba social (plantilla editable)."""
    return [
        text_block("Casos de cliente y prueba social", "subhead"),
        text_block("Clientes de referencia y logos.", "bullet"),
        text_block("Casos de éxito con resultados cuantificados.", "bullet"),
        text_block("Testimonios y menciones.", "bullet"),
        text_block("[A completar por el usuario: 2–3 casos con reto, solución y resultado, y logos con permiso.]", "body"),
    ]


def _process_timeline_blocks(bundle: Dict) -> list:
    """Calendario del proceso de la operación (plantilla editable)."""
    return [
        text_block("Calendario del proceso", "subhead"),
        text_block("Fase 1 — Contacto y NDA.", "bullet"),
        text_block("Fase 2 — Acceso a información y Q&A / data room.", "bullet"),
        text_block("Fase 3 — Ofertas no vinculantes (NBO).", "bullet"),
        text_block("Fase 4 — Due diligence y oferta vinculante.", "bullet"),
        text_block("Fase 5 — Negociación, SPA y cierre.", "bullet"),
        text_block("[A completar por el usuario: fechas objetivo de cada fase y responsables del proceso.]", "body"),
    ]


async def compose_investment_memo(company_id: str = None, cif: str = None,
                                  brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Investment Memorandum (buy-side) con la misma calidad que el infomemo: tesis, descripción,
    análisis financiero con gráficos, posición financiera, posicionamiento sectorial, valoración,
    riesgos y catalizadores, y recomendación. Datos reales + marca; layout de slides."""
    from docstudio.financial_engine import analyze_sector_benchmark
    from services.cnae_catalog import CNAE_DIVISIONS

    bundle = await DA.company_intelligence(company_id or cif)
    if not bundle.get("found"):
        return {"error": "Company not found"}

    ident = bundle["identity"]
    name = ident.get("name", "Empresa")
    cnae = ident.get("cnae_code", "")
    cnae_label = resolve_cnae_label(cnae, fallback="")
    cif_norm = bundle.get("cif_normalized", "—")
    kpis = bundle.get("kpis", {})
    assessment = bundle.get("assessment", {}) or {}
    benchmark = await analyze_sector_benchmark(cnae) if cnae else {}

    econ = await _get_economic_profile(cnae) if cnae else {}
    _peers = await _load_peers(bundle)

    doc = new_document(title=f"Investment Memorandum — {name}",
                       template_id="tpl_investment_memo", brand_id=brand_id, created_by=user)

    # Portada
    s1 = new_section("Portada", 1, [cover_block(title=name,
                                               subtitle=f"Investment Memorandum · {cnae_label}")])
    s1["blocks"][0]["data"]["date"] = _month_year_es()
    s1["blocks"][0]["data"]["advisor"] = _advisor_label(brand_id)

    # Disclaimer / confidencialidad
    s_disc = new_section("Aviso legal y confidencialidad", 2, [
        text_block("Aviso legal y confidencialidad", "subhead"),
        text_block(
            f"Este Investment Memorandum ha sido preparado por {_advisor_label(brand_id)} con carácter "
            f"estrictamente confidencial y para uso exclusivo del destinatario en el marco de la evaluación "
            f"de una potencial operación sobre {name}. La información procede de fuentes propias y de terceros "
            f"(Iberinform, registros mercantiles y fuentes públicas) y se ha elaborado de buena fe; no "
            f"constituye asesoramiento de inversión, fiscal o legal, ni una fairness opinion, y no sustituye "
            f"una due diligence. Las proyecciones y valoraciones son orientativas. Queda prohibida su "
            f"reproducción o distribución sin autorización expresa.", style="legal"),
    ])

    # IA narrativa (fact-lock) — usada en Executive Summary / Tesis
    ai = await generate_summary({
        "company_name": name, "cnae_label": cnae_label, "revenue": kpis.get("revenue"),
        "ebitda_margin": kpis.get("ebitda_margin"), "cagr": kpis.get("revenue_cagr"),
        "valuation": bundle.get("valuation"), "assessment": assessment,
    }, doc_type="investment_memo", document_id=doc["document_id"]) or {}

    # Valoración rica (estilo arroba) — calculada una vez, repartida en tres slides
    _val = _valuation_scenarios_blocks(bundle, _peers)

    # ═══════════ EXECUTIVE SUMMARY ═══════════
    s_exec_blocks = list(_hero_kpi_blocks(bundle))
    thesis = ai.get("executive_summary") or _investment_thesis_text(name, bundle)
    s_exec_blocks.append(text_block(thesis, style="executive_summary"))
    if _val.get("ev_mid"):
        _evtxt = _es(f"{_val['ev_mid']:,.0f}")
        _q = _val.get("quality")
        _bmtxt = _es(f"{_val.get('base_mult', 0):,.1f}")
        s_exec_blocks.append(insight_block(
            "Síntesis de la oportunidad",
            f"Quality Score de {(_q or 0):.0f}/100 y un Enterprise Value orientativo de {_evtxt} € en el "
            f"escenario medio ({_bmtxt}x EBITDA). El detalle metodológico se "
            f"desarrolla en la sección de valoración.", importance="high"))
    s_exec = new_section("Executive Summary", 3, s_exec_blocks)

    # ═══════════ 1. INVESTMENT HIGHLIGHTS ═══════════
    s_high_blocks = [text_block("Aspectos clave de la inversión", "subhead")]
    for c in _positive_signal_cards(bundle)[:5]:
        s_high_blocks.append(c)
    for stg in (assessment.get("strengths") or [])[:2]:
        s_high_blocks.append(insight_block("Fortaleza", stg, importance="medium"))
    s_high = new_section("Investment Highlights", 10, s_high_blocks)

    # ═══════════ 2. TESIS DE INVERSIÓN ═══════════
    s_tesis_blocks = [text_block("Tesis de inversión", "subhead"),
                      text_block(thesis, style="executive_summary")]
    for f in (ai.get("key_findings") or [])[:3]:
        s_tesis_blocks.append(insight_block("Punto clave", f, importance="high"))
    if not (ai.get("key_findings")):
        s_tesis_blocks.append(insight_block(
            "Ángulos de creación de valor",
            "Crecimiento orgánico apoyado en la posición sectorial, mejora de margen hacia el primer cuartil "
            "del sector y crecimiento inorgánico selectivo (buy & build) en un mercado fragmentado. "
            "[El analista puede matizar la tesis con la información del proceso.]", importance="medium"))
    s_tesis = new_section("Tesis de Inversión", 11, s_tesis_blocks)

    # ═══════════ TRANSACTION OVERVIEW (Deal Snapshot + capítulo 5.1–5.6) ═══════════
    s_snapshot = new_section("Deal Snapshot", 12, [
        text_block("Resumen de la operación en un vistazo", "subhead"),
        _deal_snapshot(bundle),
    ])
    _tx_sections = _transaction_overview_sections(bundle, benchmark, start_order=30)

    # ═══════════ 4. COMPAÑÍA ═══════════
    sem_prof, sem_summary = await _semantic_profile(bundle["master_id"])
    _desc = await _company_description_blocks(bundle["master_id"], {**ident, "cif": cif_norm},
                                             prof=sem_prof, summary_txt=sem_summary)
    s_comp = new_section("Compañía", 13, _desc)

    # ═══════════ 5. MERCADO Y POSICIONAMIENTO COMPETITIVO ═══════════
    _mc = await _market_competition_blocks(bundle, _peers, econ)
    _sec = await _sector_charts(bundle, _peers)
    s_mkt = new_section("Mercado y Posicionamiento Competitivo", 14,
                        _mc.get("context", []) or [text_block(
                            "[A completar por el usuario: tamaño y dinámica del mercado objetivo.]", "body")])
    s_mkt2_blocks = list(_mc.get("competition", []))
    # Benchmark sectorial (Q1/mediana/Q3) + mapa sectorial
    bm_rows = []
    for metric, label in [("revenue", "Revenue"), ("ebitda", "EBITDA"),
                          ("ebitda_margin", "Margen EBITDA"), ("employees", "Empleados")]:
        q = benchmark.get(metric, {})
        if q and q.get("median") is not None:
            def _fv(v, mm=metric):
                return _es(f"{v*100:.1f}") + " %" if mm == "ebitda_margin" else _es(f"{v:,.0f}")
            bm_rows.append([label, _fv(q.get("q1", 0)), _fv(q["median"]), _fv(q.get("q3", 0)),
                            str(benchmark.get("peers", 0))])
    if bm_rows:
        s_mkt2_blocks.append(table_block("Benchmark sectorial", ["Métrica", "Q1", "Mediana", "Q3", "Peers"], bm_rows))
    s_mkt2 = new_section("Posicionamiento Sectorial", 15, s_mkt2_blocks) if s_mkt2_blocks else None
    # Gráficos de sector (donut + mapa) en diapositiva propia a 2 columnas (evita el desborde)
    _mkt_charts = [_sec[_k] for _k in ("donut", "scatter") if _sec.get(_k)]
    s_mkt3 = new_section("Posicionamiento Sectorial · Mapa del sector", 15, _mkt_charts) if _mkt_charts else None

    # ═══════════ 6. PRODUCTOS Y SERVICIOS ═══════════
    prof = sem_prof or {}
    ps = [p.get("value") for p in (prof.get("products_services") or []) if isinstance(p, dict) and p.get("value")]
    caps = [c.get("value") for c in (prof.get("capabilities") or []) if isinstance(c, dict) and c.get("value")]
    s_prod_blocks = [text_block("Productos y servicios", "subhead")]
    _seen = set()
    for it in (ps + caps):
        k = (it or "").strip().lower()
        if it and k not in _seen:
            _seen.add(k); s_prod_blocks.append(text_block(_smart_case(it.strip()), "bullet"))
    if len(s_prod_blocks) == 1:
        obj = ident.get("objeto_social")
        if obj:
            s_prod_blocks.append(text_block(f"Actividad (objeto social): {_smart_case(obj.strip())}", style="conclusion"))
        s_prod_blocks.append(text_block(
            "[A completar por el usuario: catálogo de productos/servicios, peso de cada línea sobre ingresos, "
            "márgenes por línea y propuesta de valor diferencial.]", "body"))
    else:
        s_prod_blocks.append(text_block(
            "[El usuario puede añadir el peso de cada línea sobre ingresos y el margen por línea.]", "body"))
    s_prod = new_section("Productos y Servicios", 16, s_prod_blocks)

    # ═══════════ 7. CLIENTES Y RECURRENCIA ═══════════
    s_cli = new_section("Clientes y Recurrencia", 17, [
        text_block("Clientes y recurrencia", "subhead"),
        text_block("Base de clientes y modelo de relación (a documentar con datos del proceso).", "bullet"),
        text_block("[A completar por el usuario: número de clientes activos, concentración (top-5 / top-10 "
                   "sobre ingresos), tasa de recurrencia o contratos recurrentes, antigüedad media y "
                   "churn, y pipeline comercial.]", "body"),
        insight_block("Por qué importa",
                      "La recurrencia y la baja concentración de clientes reducen el riesgo del negocio y "
                      "sostienen múltiplos más altos; es una de las palancas de valor que el comprador "
                      "examinará en due diligence.", importance="medium"),
    ])

    # ═══════════ 8. EQUIPO DIRECTIVO ═══════════
    _org = await _team_org_blocks(bundle, bundle["master_id"], cif_norm, _peers)
    s_team_blocks = list(_org.get("leadership", [])) + list(_org.get("orgchart", []))
    if not any(b.get("block_type") == "orgchart" for b in s_team_blocks):
        s_team_blocks.append(text_block(
            "[A completar por el usuario: organigrama del equipo directivo, roles clave, trayectoria y "
            "plan de continuidad tras la operación.]", "body"))
    s_team = new_section("Equipo Directivo", 18, s_team_blocks)

    # ═══════════ 9. INFORMACIÓN FINANCIERA (histórico + calidad del beneficio) ═══════════
    s_fin_blocks = list(_hero_kpi_blocks(bundle))
    s_fin_blocks.extend(_evolution_charts(bundle))
    for _fb in (FE.margin_percentile_kpi_block(bundle), FE.ratios_table_block(bundle)):
        if _fb:
            s_fin_blocks.append(_fb)
    s_fin = new_section("Información Financiera", 19, s_fin_blocks)
    s_kpis = new_section("KPIs Financieros", 20, _financial_kpis_blocks(bundle))
    _plan = _projection_tables(bundle)
    s_plan = new_section("Plan de Negocio", 21, _plan) if _plan else None

    # ═══════════ 10. VALORACIÓN ORIENTATIVA ═══════════
    s_val = s_val3 = None
    if _val:
        # Diapositiva única: Quality Score + percentiles + escenarios (tabla + gráfico EV).
        # Se compacta (nota breve en vez del párrafo largo) para que quepa entera en la slide.
        _kpis_val = [b for b in _val["score"] if b.get("block_type") == "kpi"]
        _scn = _val["scenarios"]  # [subhead, nota_larga, tabla, gráfico(pair), insight]
        _bm = _es(f"{_val.get('base_mult', 0):,.1f}")
        _short_note = text_block(
            f"EBITDA base reportado · múltiplo sugerido {_bm}x (rango 4x–8x) · comprador financiero (1,00x). "
            f"Ajustable por el asesor (EBITDA base, múltiplo y tipo de comprador).", style="body")
        _merged = [text_block("Valoración orientativa por múltiplo", "subhead")] + _kpis_val
        _merged.append(_short_note)
        _merged += _scn[2:]  # tabla + gráfico EV + lectura
        s_val = new_section("Valoración Orientativa", 22, _merged)
        s_val3 = new_section("Valoración · Benchmark y Metodología", 24, _val["benchmark"])
    else:
        s_val = new_section("Valoración Orientativa", 22, [
            text_block("Valoración orientativa", "subhead"),
            text_block("[No hay EBITDA o comparables suficientes para una valoración por múltiplos. "
                       "El usuario puede aportar el EBITDA ajustado y el múltiplo de referencia.]", "body")])

    # ═══════════ 11. RIESGOS IDENTIFICADOS Y MITIGANTES ═══════════
    s_risk_blocks = [text_block("Riesgos identificados y mitigantes", "subhead")]
    _risks = (assessment.get("risks", []) + assessment.get("weaknesses", []))[:5]
    if _risks:
        for r in _risks:
            s_risk_blocks.append(insight_block("Riesgo", r, importance="high"))
            s_risk_blocks.append(insight_block("Mitigante", "[A completar por el usuario: medida de "
                                               "mitigación / plan de acción.]", importance="low"))
    else:
        for r, m in [("Concentración de clientes o proveedores",
                      "Diversificación de la cartera y contratos plurianuales."),
                     ("Dependencia de personas clave",
                      "Plan de retención, documentación de procesos y sucesión."),
                     ("Exposición al ciclo del sector",
                      "Diversificación de líneas y flexibilidad de la estructura de costes.")]:
            s_risk_blocks.append(insight_block("Riesgo", r + " [validar en el proceso].", importance="high"))
            s_risk_blocks.append(insight_block("Mitigante", m + " [a completar por el usuario].", importance="low"))
    s_risk = new_section("Riesgos y Mitigantes", 25, s_risk_blocks)

    # ═══════════ 12. PALANCAS DE CREACIÓN DE VALOR (100 días · 3 años · 5 años) ═══════════
    _mar_gap = ""
    try:
        _q = benchmark.get("ebitda_margin", {})
        _mar = kpis.get("ebitda_margin")
        if _q and _q.get("q3") is not None and _mar is not None and _mar < _q["q3"]:
            _mar_gap = (f" El margen EBITDA actual ({_pct(_mar)}) está por debajo del tercer cuartil del sector "
                        f"({_pct(_q['q3'])}), lo que sugiere recorrido de mejora operativa.")
    except Exception:
        _mar_gap = ""
    s_lev = new_section("Palancas de Creación de Valor", 26, [
        text_block("Plan de creación de valor", "subhead"),
        text_block("Primeros 100 días", "subhead"),
        text_block("Gobierno y reporting: cuadro de mando, KPIs y cadencia de seguimiento.", "bullet"),
        text_block("Quick wins de margen: precios, compras y eficiencia operativa." + _mar_gap, "bullet"),
        text_block("Retención del equipo clave e incentivos alineados.", "bullet"),
        text_block("Horizonte 3 años", "subhead"),
        text_block("Crecimiento orgánico (nuevos clientes, cross-selling, expansión geográfica).", "bullet"),
        text_block("Mejora de margen hacia el primer cuartil del sector.", "bullet"),
        text_block("Inversión en digitalización y sistemas.", "bullet"),
        text_block("Horizonte 5 años", "subhead"),
        text_block("Buy & build: adquisiciones selectivas en un mercado fragmentado.", "bullet"),
        text_block("Salto de escala y preparación para la salida (trade sale / secundario).", "bullet"),
        text_block("[A completar por el usuario: cuantificación de cada palanca e impacto esperado en EBITDA.]", "body"),
    ])

    # ═══════════ 13. SINERGIAS POTENCIALES PARA COMPRADORES ESTRATÉGICOS ═══════════
    s_syn_blocks = [text_block("Sinergias para compradores estratégicos", "subhead")]
    frag = {}
    try:
        from services.engines.investment.fragmentation import compute_fragmentation
        _sec_code = (bundle.get("identity") or {}).get("cnae_section")
        if _sec_code:
            frag = await compute_fragmentation("cnae_section", _sec_code, limit_companies=800) or {}
    except Exception:
        frag = {}
    if frag.get("hhi") is not None or frag.get("standalone_targets_count"):
        _fr = []
        if frag.get("hhi") is not None:
            _hhitxt = _es(f"{frag['hhi']:,.0f}")
            _fr.append(f"mercado {_hhi_label_es(frag.get('concentration_label'))} (HHI {_hhitxt})")
        if frag.get("standalone_targets_count"):
            _sttxt = _es(f"{frag['standalone_targets_count']:,.0f}")
            _fr.append(f"{_sttxt} objetivos independientes candidatos a consolidación")
        s_syn_blocks.append(insight_block("Contexto de consolidación",
                                          "Estructura del sector: " + ", ".join(_fr) + ".", importance="medium"))
    for t, d in [("Ingresos", "cross-selling a la base de clientes del comprador, acceso a nuevos canales y geografías."),
                 ("Costes", "compras conjuntas, consolidación de estructura y economías de escala."),
                 ("Capacidades", "integración de tecnología, talento y know-how sectorial.")]:
        s_syn_blocks.append(insight_block(f"Sinergias de {t.lower()}", f"{t}: {d}", importance="low"))
    s_syn_blocks.append(text_block("[A completar por el usuario: cuantificación de sinergias por tipo de comprador estratégico.]", "body"))
    s_syn = new_section("Sinergias Potenciales", 27, s_syn_blocks)

    # ═══════════ 14. ANEXOS ═══════════
    s_annex = new_section("Anexos", 28, [
        text_block("Anexos", "subhead"),
        text_block("Fuentes de información", "subhead"),
        text_block("Iberinform (estados financieros, balance, ratios y datos societarios); registros "
                   "mercantiles (BORME); comparables de sector de la base de datos propia; y datos "
                   "económicos sectoriales (DIRCE / Economic Intelligence).", "body"),
        text_block("Definiciones", "subhead"),
        text_block("EBITDA: resultado operativo antes de amortizaciones. Quality Score: percentil ponderado "
                   "de calidad frente al sector. Enterprise Value (EV): valor de la compañía; Equity Value = "
                   "EV − deuda financiera neta. CAGR: tasa de crecimiento anual compuesta.", "body"),
        text_block("Documentación pendiente de aportar", "subhead"),
        text_block("[A completar por el usuario: cuentas anuales auditadas, contratos relevantes, detalle de "
                   "clientes y proveedores, plantilla y organigrama, litigios y contingencias, y plan de "
                   "negocio del vendedor.]", "body"),
    ])

    # Estructura del mercado (TAM/SAM/SOM) · Estructura del equipo
    s_tam = new_section("Estructura del Mercado · TAM/SAM/SOM", 145, _tam_sam_som_blocks(bundle, econ))
    s_teamstruct = new_section("Estructura del Equipo", 185, await _team_structure_blocks(bundle, cif_norm))

    # Modelo de negocio y problema que resuelve (dentro de Compañía)
    s_bizmodel = new_section("Modelo de Negocio y Problema que Resuelve", 135,
                             _business_model_blocks(bundle, sem_prof))

    # Nuevas secciones para un deck de inversión completo
    s_traction = new_section("Tracción e Hitos", 105, _traction_blocks(bundle))
    s_captable = new_section("Estructura de Propiedad · Cap Table", 128,
                             await _captable_table_blocks(bundle, bundle["master_id"]))
    s_moat = new_section("Ventaja Competitiva y Foso", 141, _moat_blocks(bundle, benchmark))
    s_gtm = new_section("Go-to-Market y Unit Economics", 165, _gtm_blocks(bundle))
    s_roadmap = new_section("Roadmap de Producto", 167, _roadmap_blocks(bundle))
    s_cases = new_section("Casos de Cliente y Prueba Social", 172, _cases_blocks(bundle))
    s_comps = new_section("Múltiplos y Transacciones Comparables", 235, await _transaction_comps_blocks(bundle))
    s_exit = new_section("Retorno para el Inversor y Salida", 245, _exit_returns_blocks(bundle))

    # Anexo interno (no para el inversor): fuente y cálculo de cada ratio
    _int_a, _int_b = _internal_sources_annex()
    s_intern1 = new_section("Anexo Interno · Ratios de la compañía", 300, _int_a)
    s_intern2 = new_section("Anexo Interno · Sector y valoración", 301, _int_b)

    # ── Índice + separadores de sección (negro, estilo del cuaderno) ──
    def _sep(num, title):
        s = new_section(title, 0, [])
        s["slide_kind"] = "separator"; s["section_number"] = num
        return s

    parts = [
        ("00", "Executive Summary", [s_exec]),
        ("01", "Tesis de Inversión", [s_high, s_traction, s_tesis]),
        ("02", "Compañía, Mercado y Negocio",
         [s_comp, s_bizmodel, s_mkt, s_tam, s_mkt2, s_mkt3, s_moat, s_prod, s_roadmap,
          s_cli, s_cases, s_gtm, s_team, s_teamstruct]),
        ("03", "Información Financiera", [s_fin, s_kpis, s_plan]),
        ("04", "Valoración", [s_val, s_comps, s_val3, s_exit]),
        ("05", "Transaction Overview", [s_snapshot, s_captable] + _tx_sections),
        ("06", "Riesgos, Valor y Anexos", [s_risk, s_lev, s_syn, s_annex, s_intern1, s_intern2]),
    ]
    _idx_rows = [
        ["ES", "Executive Summary"],
        ["01", "Investment Highlights · tracción e hitos"],
        ["02", "Tesis de inversión"],
        ["03", "Compañía y modelo de negocio"],
        ["04", "Mercado, posicionamiento y ventaja competitiva"],
        ["05", "Productos, servicios y roadmap"],
        ["06", "Clientes, casos y go-to-market"],
        ["07", "Equipo directivo y estructura"],
        ["08", "Información financiera (histórico · KPIs · plan)"],
        ["09", "Valoración, comparables y retorno/salida"],
        ["10", "Transaction Overview · Deal Snapshot"],
        ["", "5.1 Summary · 5.2 Opportunity · 5.3 Seller · 5.4 Buyer · 5.5 Structure · 5.6 Process"],
        ["11", "Riesgos identificados y mitigantes"],
        ["12", "Palancas de creación de valor (100 días · 3 · 5 años)"],
        ["13", "Sinergias para compradores estratégicos"],
        ["14", "Anexos"],
        ["·", "Anexo interno · fuentes y cálculo (no para el inversor)"],
    ]
    s_index = new_section("Índice", 4, [
        text_block("Contenido del memorando", "subhead"),
        table_block("", ["Sección", "Contenido"], _idx_rows),
    ])

    _close = cover_block(title="Gracias", subtitle="Documento estrictamente confidencial")
    _close["data"]["advisor"] = _advisor_label(brand_id)
    s_close = new_section("Contacto", 99, [_close]); s_close["slide_kind"] = "closing"

    ordered = [s1, s_disc, s_index]
    for num, title, secs in parts:
        ordered.append(_sep(num, title))
        ordered.extend([s for s in secs if s])
    ordered.append(s_close)

    doc["sections"] = [s for s in ordered if s]
    doc["metadata"] = {
        "master_id": bundle["master_id"], "cif": cif_norm, "type": "investment_memo",
        "financial_engine_used": True, "fact_locked": True, "schema": "modern",
    }
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


def _nda_blocks() -> list:
    """Acuerdo de Confidencialidad recíproco (NDA) — plantilla adaptada del estándar de bud
    advisors, lista para firmar. La Parte Receptora (potencial inversor/comprador) se rellena
    al firmar; la contraparte es el asesor (bud advisors). Texto editable por el asesor."""
    out = [text_block("Acuerdo recíproco de confidencialidad", "subhead")]
    out.append(text_block("En __________________, a ______ de ____________________ de 20____.", "legal"))
    out.append(text_block("De una parte, la «Parte Receptora»: D./Dª. ____________________________, "
                          "con NIF ____________, actuando en su propio nombre o en representación de "
                          "____________________________ (el potencial inversor/comprador).", "legal"))
    out.append(text_block("De otra parte, D. Daniel Casal González-Outón, con DNI 52.364.372-L, en "
                          "representación de bud advisors, S.L., con CIF B-70821400 y domicilio social en "
                          "Paseo de la Castellana 178, 6I, 28046 Madrid.", "legal"))
    out.append(text_block("Declaran las partes:", "legal"))
    for d in [
        "Que han decidido transmitirse mutuamente cierta información confidencial (la «Información "
        "Confidencial»), relacionada con el análisis de una potencial operación corporativa sobre la "
        "compañía objeto de este proceso (la «Operación»).",
        "Que cualquiera de ellas, por la naturaleza de este contrato, podrá constituirse como parte "
        "receptora o parte divulgadora.",
        "Que se reconocen mutuamente la personalidad con la que comparecen y manifiestan su libre "
        "voluntad para obligarse en los términos de las siguientes:"]:
        out.append(text_block(d, "legal"))
    out.append(text_block("Cláusulas", "subhead"))
    clausulas = [
        "PRIMERA. Las partes se obligan a no divulgar a terceros la «Información Confidencial» que "
        "reciban de la otra, y a darle el mismo tratamiento que a la información confidencial de su "
        "propiedad. Asimismo, se obligan a no divulgar el hecho de haberse iniciado conversaciones en "
        "relación con la potencial Operación. La «Información Confidencial» comprende toda la información "
        "divulgada por cualquiera de las partes, en forma oral, visual, escrita, grabada o en cualquier "
        "otra forma tangible.",
        "SEGUNDA. La parte receptora mantendrá confidencial la «Información Confidencial» y no la "
        "entregará a terceros distintos de sus abogados y asesores con necesidad de conocerla para los "
        "fines de la Cláusula Sexta, quienes deberán obligarse igualmente a mantenerla confidencial.",
        "TERCERA. La parte receptora no divulgará la «Información Confidencial» a terceros sin el previo "
        "consentimiento por escrito de la parte divulgadora.",
        "CUARTA. La parte receptora tomará las precauciones necesarias y apropiadas para mantener la "
        "confidencialidad, incluyendo informar a sus empleados que la manejen de su carácter confidencial.",
        "QUINTA. La «Información Confidencial» es y seguirá siendo propiedad de la parte divulgadora; se "
        "usará únicamente para los fines de la Cláusula Sexta y este instrumento no otorga derecho de "
        "propiedad intelectual ni licencia alguna sobre ella.",
        "SEXTA. La parte receptora utilizará la «Información Confidencial» únicamente para el análisis y "
        "eventual ejecución de la Operación.",
        "SÉPTIMA. El incumplimiento parcial o total de estas obligaciones hará responsable a la parte "
        "receptora de los daños y perjuicios que ocasione a la parte divulgadora.",
        "OCTAVA. Las partes se comprometen a no contratar personal de la otra parte durante veinticuatro "
        "(24) meses desde la firma del presente acuerdo.",
        "NOVENA. No existirá obligación de confidencialidad sobre información que: (i) fuese ya conocida por "
        "la parte receptora libre de obligación de confidencialidad; (ii) sea desarrollada de forma "
        "independiente o recibida legalmente de otra fuente con derecho a divulgarla; (iii) sea o llegue a "
        "ser de dominio público sin incumplimiento de este convenio; o (iv) se reciba de un tercero sin "
        "quebrantar una obligación de confidencialidad.",
        "DÉCIMA. Las obligaciones de este acuerdo permanecerán vigentes durante treinta y seis (36) meses "
        "desde su firma.",
        "DÉCIMO PRIMERA. Este convenio constituye el acuerdo total entre las partes respecto a dicha "
        "información y sustituye cualquier entendimiento previo, oral o escrito.",
        "DÉCIMO SEGUNDA. Ninguna de las partes podrá ceder sus derechos y obligaciones derivados del "
        "presente contrato.",
        "DÉCIMO TERCERA. Este convenio solo podrá modificarse por consentimiento de las partes otorgado "
        "por escrito.",
        "DÉCIMO CUARTA. Para la interpretación y cumplimiento del presente contrato, las partes se someten "
        "a la jurisdicción de los juzgados y tribunales de Madrid, renunciando a cualquier otro fuero que "
        "pudiera corresponderles.",
    ]
    for c in clausulas:
        out.append(text_block(c, "legal"))
    out.append(text_block("En prueba de conformidad, las partes firman el presente acuerdo:", "legal"))
    out.append(text_block("28", style="spacer"))
    out.append(text_block("_______________________________     ", style="body"))
    out.append(text_block("La Parte Receptora — Nombre y NIF", style="legal"))
    out.append(text_block("18", style="spacer"))
    out.append(text_block("_______________________________     ", style="body"))
    out.append(text_block("D. Daniel Casal González-Outón — Managing Partner, bud advisors, S.L.", style="legal"))
    return out


def _size_band(rev, emp) -> str:
    """Banda de tamaño anónima (no revela cifra exacta como identificador)."""
    if rev is not None:
        if rev < 10e6:
            return "pequeña empresa"
        if rev < 50e6:
            return "empresa mediana"
        if rev < 300e6:
            return "gran empresa"
        return "gran corporación"
    if emp:
        return "empresa mediana" if emp < 250 else "gran empresa"
    return "compañía"


async def compose_teaser(company_id: str = None, cif: str = None,
                         brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Teaser CIEGO (perfil anónimo) para primer contacto con compradores: muestra sector,
    región, tamaño y magnitudes financieras + aspectos destacados de inversión, SIN revelar
    identidad (nombre/CIF/web/municipio). Mismo layout de slides y marca que el infomemo."""
    from services.cnae_catalog import CNAE_DIVISIONS

    bundle = await DA.company_intelligence(company_id or cif)
    if not bundle.get("found"):
        return {"error": "Company not found"}

    ident = bundle["identity"]
    kpis = bundle.get("kpis", {}) or {}
    cnae = ident.get("cnae_code", "")
    cnae_label = resolve_cnae_label(cnae, fallback=(ident.get("cnae_description") or "su sector"))
    provincia = ident.get("provincia")
    rev = kpis.get("revenue")
    emp = (bundle.get("statements") or {}).get("employees")
    band = _size_band(rev, emp)

    doc = new_document(title="Teaser — Proyecto Confidencial", template_id="tpl_teaser",
                       brand_id=brand_id, created_by=user)

    # 1. Portada (negra) — sin nombre; nombre en clave.
    s1 = new_section("Portada", 1, [cover_block(title="Oportunidad de Inversión",
                                                subtitle=f"Proyecto Confidencial · {cnae_label}")])
    s1["blocks"][0]["data"]["date"] = _month_year_es()
    s1["blocks"][0]["data"]["advisor"] = _advisor_label(brand_id)

    # 2. La Oportunidad — perfil anónimo + KPIs financieros + lectura reglada.
    # (El título de sección ya lo pinta el renderizador A4; no repetir subtítulo.)
    s2_blocks = []
    perfil = [f"{band.capitalize()} del sector {cnae_label} (CNAE {cnae})."]
    if provincia:
        perfil.append(f"Con sede en la provincia de {provincia}.")
    perfil.append("Se estudia la entrada de un socio mediante la adquisición total o parcial del capital.")
    for p in perfil:
        s2_blocks.append(text_block(p, "bullet"))
    s2_blocks.extend(_hero_kpi_blocks(bundle))
    s2 = new_section("La Oportunidad", 2, s2_blocks)

    # 3. Aspectos destacados — highlights de inversión + evolución financiera (anónima).
    s3_blocks = []
    s3_blocks.extend(_positive_signal_cards(bundle)[:4])
    # Gráficos de evolución en DOS COLUMNAS (igual que las tarjetas de Aspectos destacados):
    # solo los bloques 'chart', consecutivos y sin fila emparejada, para que el renderizador
    # los agrupe 2 por fila.
    ev_charts = [b for b in _evolution_charts(bundle) if b.get("block_type") == "chart"]
    for c in ev_charts:
        c["data"]["config"] = {}
    s3_blocks.extend(ev_charts)
    s3 = new_section("Aspectos Destacados", 3, s3_blocks)

    # 4. Motivo de la Operación — objetivos (a marcar por el asesor) + racional estratégico.
    s4_blocks = [text_block("Objetivos de la operación", "subhead")]
    for obj in ["Venta del 100 % / mayoría / minoría", "Entrada de socio financiero",
                "Entrada de socio industrial", "Ampliación de capital",
                "Búsqueda de comprador estratégico", "Roll-up sectorial", "MBO / MBI", "Otros"]:
        s4_blocks.append(text_block(obj, "bullet"))
    s4_blocks.append(text_block("[Marcar el/los objetivos aplicables a esta operación.]", "body"))
    s4_blocks.append(text_block("Racional estratégico", "subhead"))
    # Racional reglado (3–5 líneas) anónimo, apoyado en cifras reales cuando existen.
    cagr = kpis.get("revenue_cagr"); mar = kpis.get("ebitda_margin")
    frases = ["La compañía ha consolidado una posición sólida en su nicho de mercado"]
    if cagr and cagr > 0:
        frases[0] += f", con un crecimiento sostenido (CAGR de ingresos del {_pct(cagr, 0)})"
    if mar is not None:
        frases.append(f"y una rentabilidad probada (margen EBITDA del {_pct(mar)})")
    frases.append("sobre un modelo de negocio escalable")
    racional = (". ".join([" ".join(frases)]) + ". "
                "Los accionistas consideran que la incorporación de un socio estratégico permitirá "
                "acelerar el crecimiento, ejecutar adquisiciones selectivas y maximizar la creación "
                "de valor en la siguiente etapa. [Editable por el asesor según el caso.]")
    rb = text_block(racional, style="executive_summary")
    rb["data_lineage"] = {"source": "plantilla editable (racional de la operación)", "date": now_iso()}
    s4_blocks.append(rb)
    s_deal = new_section("Motivo de la Operación", 4, s4_blocks)

    # 4a bis. Deal Snapshot — estándar bud advisors (mismo bloque en One Pager, Teaser e Infomemo).
    s_snapshot = new_section("Deal Snapshot", 4, [
        text_block("La operación en un vistazo", "subhead"), _deal_snapshot(bundle)])

    # 4b. NDA — acuerdo de confidencialidad recíproco, listo para firmar.
    s_nda = new_section("Acuerdo de Confidencialidad", 5, _nda_blocks())

    # 5. Cierre (negro) — siguiente paso / confidencialidad.
    _close = cover_block(title="¿Interesado?",
                         subtitle="Firme el NDA para acceder al cuaderno de venta completo")
    _close["data"]["advisor"] = _advisor_label(brand_id)
    s_close = new_section("Contacto", 9, [_close])
    s_close["slide_kind"] = "closing"

    # "¿Interesado?" (llamada a la acción) va ANTES del NDA; el NDA cierra el documento para firmar.
    doc["sections"] = [s1, s2, s3, s_snapshot, s_deal, s_close, s_nda]
    doc["metadata"] = {
        "master_id": bundle["master_id"], "cif": bundle["cif_normalized"], "type": "teaser",
        "financial_engine_used": True, "fact_locked": True, "schema": "modern", "blind": True,
    }
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_information_memorandum(company_id: str = None, cif: str = None,
                                         brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Full Information Memorandum. Fase 2: modern schema + real engines + REAL valuation.

    The old 'valoración preliminar' was a heuristic (sector_revenue_median * 1.5). It is
    replaced by the real Financial Intelligence Engine `valuation()` (honest: market_observed
    vs inferred_reference, or nothing when insufficient). Risks/opportunities now come from
    the engine's real assessment + active signals, not a blind AI call.
    """
    from docstudio.financial_engine import analyze_sector_benchmark
    from services.cnae_catalog import CNAE_DIVISIONS

    bundle = await DA.company_intelligence(company_id or cif)
    if not bundle.get("found"):
        return {"error": "Company not found"}

    ident = bundle["identity"]
    name = ident.get("name", "Empresa")
    cnae = ident.get("cnae_code", "")
    cnae_label = resolve_cnae_label(cnae, fallback="")
    cif_norm = bundle.get("cif_normalized", "—")
    kpis = bundle.get("kpis", {})
    assessment = bundle.get("assessment", {}) or {}
    benchmark = await analyze_sector_benchmark(cnae) if cnae else {}
    econ = await _get_economic_profile(cnae) if cnae else {}

    doc = new_document(
        title=f"Information Memorandum — {name}",
        template_id="tpl_im", brand_id=brand_id, created_by=user,
        description=f"Memorándum informativo completo de {name}",
    )

    # 1. Cover — advisor line from the active platform brand (decisión Daniel 2026-07-24)
    _cover = cover_block(title=name, subtitle="Information Memorandum")
    _cover["data"]["date"] = _month_year_es()
    _cover["data"]["advisor"] = f"Asesor financiero: {_advisor_label(brand_id)}"
    s1 = new_section("Portada", 1, [_cover])

    # 1b. Disclaimer / confidentiality slide (plantilla legal completa, editable) — texto real BUD
    _disc_paras = _disclaimer_paragraphs(_advisor_label(brand_id), name)
    s_disclaimer = new_section("Confidencialidad", 2,
                               [text_block(p, style="legal") for p in _disc_paras])
    for _b in s_disclaimer["blocks"]:
        _b["data_lineage"] = {"source": "template", "task": "confidentiality", "date": now_iso()}

    # 2. Executive Summary (Claude, fact-locked over real data)
    ai_context = {
        "company_name": name, "cnae": cnae, "cnae_label": cnae_label,
        "revenue": kpis.get("revenue"), "ebitda_margin": kpis.get("ebitda_margin"),
        "revenue_yoy": kpis.get("revenue_growth_yoy"), "cagr": kpis.get("revenue_cagr"),
        "valuation": bundle.get("valuation"), "assessment": assessment,
        "sector_peers": benchmark.get("peers", 0),
        "sector_revenue_median": benchmark.get("revenue", {}).get("median"),
        "active_signals": [s.get("signal_type") for s in bundle.get("signals", [])],
    }
    ai_result = await generate_summary(ai_context, doc_type="company_profile", document_id=doc["document_id"])

    # Perfil semántico (objeto social -> actividad/capacidades); se reutiliza en la descripción.
    sem_prof, sem_summary = await _semantic_profile(bundle["master_id"])
    # Web corporativa (scraper, best-effort, cacheada) para enriquecer la descripción.
    web_desc = None
    try:
        from services.web_scraper import get_web_description
        web_desc = await get_web_description(bundle["master_id"])
    except Exception:
        web_desc = None

    # Resumen ejecutivo = escaparate para el comprador:
    # 1) 4 KPIs principales con evolución  2) descripción de la compañía (semántica+IA)  3) tarjetas de señales positivas
    s2 = new_section("Resumen Ejecutivo", 2, [])
    for _kb in _hero_kpi_blocks(bundle):
        s2["blocks"].append(_kb)
    _desc_txt = _exec_description(ident, sem_prof, bundle, ai_result.get("executive_summary"), web_desc=web_desc)
    if _desc_txt:
        b = text_block(_desc_txt, style="executive_summary")
        b["data_lineage"] = {"source": "semantic-intelligence-v1+ai", "task": "im_company_description", "date": now_iso()}
        s2["blocks"].append(b)
    for _cb in _positive_signal_cards(bundle):
        s2["blocks"].append(_cb)

    # 3. Company Overview — descripción ampliada (Motor Semántico + objeto social + societario)
    _desc = await _company_description_blocks(bundle["master_id"], {**ident, "cif": cif_norm},
                                             prof=sem_prof, summary_txt=sem_summary)
    s3 = new_section("Descripción de la Compañía", 3, _desc)
    # Accionariado (estructura societaria)
    _cap_blocks = await _captable_blocks(bundle["master_id"])
    s_cap = new_section("Accionariado", 4, _cap_blocks) if _cap_blocks else None
    # Historia y orígenes (manual, editable por el asesor)
    _hist_intro = text_block("[Completar: orígenes de la compañía, hitos clave (fundación, cambios de "
                             "marca, expansión, operaciones relevantes) y evolución hasta la actualidad.]", style="body")
    _hist_intro["data_lineage"] = {"source": "manual", "placeholder": True, "date": now_iso()}
    s_history = new_section("Historia y Orígenes", 5, [_hist_intro])
    # Peers del sector — consulta ÚNICA reutilizada por gráficos de sector y scatter de productividad
    _peers = await _load_peers(bundle)
    # Gráficos de sector (donut/scatter/distribución) — se reparten por las secciones del documento
    _sec_charts = await _sector_charts(bundle, _peers)

    # 4. Financial Highlights (real Financial Engine) + evolution charts + history table
    s4_blocks = _company_kpi_blocks(bundle)
    points = (bundle.get("evolution", {}) or {}).get("points", [])
    # Gráficos de evolución (barras ingresos + línea EBITDA) con la librería SVG
    for _c in _evolution_charts(bundle):
        s4_blocks.append(_c)
    if points:
        rev_rows = [[str(p.get("year", "")), _es(f"{(p.get('revenue') or 0):,.0f}"), _es(f"{(p.get('ebitda') or 0):,.0f}")]
                    for p in sorted(points, key=lambda p: p.get("year") or 0)]
        s4_blocks.append(table_block("Evolución histórica", ["Año", "Ingresos (€)", "EBITDA (€)"], rev_rows))
    # Curated ratios + percentile KPI (se omite el score de calidad 100/100: no aporta al comprador)
    for _fb in (FE.margin_percentile_kpi_block(bundle), FE.ratios_table_block(bundle)):
        if _fb:
            s4_blocks.append(_fb)
    s4 = new_section("Análisis Financiero", 4, s4_blocks)

    # 4b. Posición financiera — fondo de maniobra + PFN (tras Análisis Financiero)
    _fp_blocks = _financial_position_blocks(bundle)
    s_finpos = new_section("Posición Financiera · Fondo de maniobra y deuda neta", 4, _fp_blocks) if _fp_blocks else None
    # 4c. EBITDA bridge — layout definitivo listo para que el asesor complete los ajustes
    _eb_blocks = _ebitda_bridge_blocks(bundle)
    s_ebitda = new_section("EBITDA Bridge · Puente a EBITDA ajustado", 4, _eb_blocks) if _eb_blocks else None

    # 5. Sector & Benchmark (modern benchmark)
    bm_rows = []
    for metric, label in [("revenue", "Revenue"), ("ebitda", "EBITDA"),
                          ("ebitda_margin", "Margen EBITDA"), ("employees", "Empleados")]:
        q = benchmark.get(metric, {})
        if q and q.get("median") is not None:
            def fmt_val(v, m=metric):
                return _es(f"{v*100:.1f}") + " %" if m == "ebitda_margin" else _es(f"{v:,.0f}")
            bm_rows.append([label, fmt_val(q.get("q1", 0)), fmt_val(q["median"]),
                           fmt_val(q.get("q3", 0)), str(benchmark.get("peers", 0))])
    s5_blocks = [table_block("Benchmark sectorial", ["Métrica", "Q1", "Mediana", "Q3", "Peers"], bm_rows)] if bm_rows else []
    _sector_pos = await FE.sector_positioning_block(db, bundle)
    if _sector_pos:
        s5_blocks.append(_sector_pos)
    s5 = new_section("Posicionamiento Sectorial", 5, s5_blocks) if s5_blocks else None
    # Gráficos de sector (donut de rentabilidad + mapa sectorial) en diapositiva propia a 2 columnas
    _s5c = [_sec_charts[_k] for _k in ("donut", "scatter") if _sec_charts.get(_k)]
    s5_charts = new_section("Posicionamiento Sectorial · Mapa del sector", 5, _s5c) if _s5c else None

    # 6. Mercado y Competencia — bloque real: tamaño/estructura (E7) + competidores + síntesis
    _mc = await _market_competition_blocks(bundle, _peers, econ)
    s6_market = new_section("Contexto de Mercado", 6, list(_mc["context"]))
    _dist = _sec_charts.get("distribution")
    if _dist:
        # Histograma reducido (~45%) con una explicación a su derecha (fila emparejada).
        _dist.setdefault("data", {}).setdefault("config", {})
        _dist["data"]["config"].update({"pair": True, "pair_width": _CHART_COL, "pair_align": "flex-start", "max_width": "100%"})
        _dist["data"]["title"] = ""  # el subtítulo de la sección ya titula el bloque
        s6_market["blocks"].append(text_block("Distribución de la rentabilidad del sector", "subhead"))
        s6_market["blocks"].append(_dist)
        s6_market["blocks"].append(_distribution_note(bundle, _peers))
    s_competition = (new_section("Mercado y Competencia · Competidores", 6, list(_mc["competition"]))
                     if _mc.get("competition") else None)

    # 7. Risks & Opportunities — REAL assessment + active signals (no blind AI)
    s7_risks = new_section("Riesgos y Oportunidades", 7, [])
    for risk in (assessment.get("risks", []) + assessment.get("weaknesses", []))[:4]:
        b = insight_block("Riesgo", risk, importance="high")
        b["data_lineage"] = {"source": _FIN, "task": "assessment_risk", "date": now_iso()}
        s7_risks["blocks"].append(b)
    for sig in bundle.get("signals", []):
        if sig.get("severity") == "opportunity":
            b = insight_block("Oportunidad", sig.get("explanation", sig.get("signal_type", "")), importance="medium")
            b["data_lineage"] = {"source": "signal-intelligence-v1", "signal_id": sig.get("signal_id"), "date": now_iso()}
            s7_risks["blocks"].append(b)
    for strength in assessment.get("strengths", [])[:3]:
        s7_risks["blocks"].append(insight_block("Fortaleza", strength, importance="medium"))

    # 8. Valuation — REAL Financial Engine valuation (honest), not a heuristic
    s8_val = new_section("Valoración", 8, [])
    vb = _valuation_block(bundle)
    if vb:
        s8_val["blocks"].append(vb)
        val = bundle.get("valuation", {})
        rng = val.get("range") or {}
        if rng.get("low") and rng.get("high"):
            _conf = val.get("confidence")
            _confs = _es(f"{_conf}") if _conf is not None else "—"
            s8_val["blocks"].append(text_block(
                f"Rango orientativo: {_eur(rng['low'])} – {_eur(rng['high'])} "
                f"(confianza {_confs}). "
                + " ".join(val.get("hypotheses", [])), style="body"))
    else:
        s8_val["blocks"].append(text_block(
            "Datos insuficientes para una valoración fiable. Se requiere información financiera adicional.", style="body"))

    # 9. Key Findings (Claude)
    s9 = new_section("Hallazgos Clave", 9, [])
    for f in ai_result.get("key_findings", []):
        b = insight_block("Hallazgo", f, importance="high")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "im_findings", "date": now_iso()}
        s9["blocks"].append(b)

    # 10. Conclusion & Recommendations (Claude)
    s10 = new_section("Conclusión y Recomendaciones", 10, [])
    if ai_result.get("conclusion"):
        b = text_block(ai_result["conclusion"], style="conclusion")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "im_conclusion", "date": now_iso()}
        s10["blocks"].append(b)
    for rec in ai_result.get("recommendations", []):
        s10["blocks"].append(insight_block("Recomendación", rec, importance="medium"))

    # Productos y Servicios + Clientes — comerciales (Manual): hueco a completar
    def _ph(hint):
        b = text_block(hint, style="body")
        b["data_lineage"] = {"source": "manual", "placeholder": True, "date": now_iso()}
        return b
    s_prod = new_section("Modelo de Negocio, Productos y Servicios", 4,
                         _business_model_blocks(bundle, sem_prof))
    s_cli = new_section("Clientes y Cartera", 4, [
        _ph("[Completar: descripción de la cartera, recurrencia y sectores de cliente.]"),
        insight_block("Por qué importa",
                      "La recurrencia y la baja concentración de clientes reducen el riesgo del negocio "
                      "y sostienen múltiplos más altos.", importance="medium")])

    # Módulos añadidos (dato real + editables) para elevar el cuaderno
    s_kpis = new_section("KPIs Financieros", 4, _financial_kpis_blocks(bundle))
    s_tam = new_section("Estructura del Mercado · TAM/SAM/SOM", 6, _tam_sam_som_blocks(bundle, econ))
    s_moat = new_section("Ventaja Competitiva y Foso", 6, _moat_blocks(bundle, benchmark))
    s_teamstruct = new_section("Estructura del Equipo", 6, await _team_structure_blocks(bundle, cif_norm))
    s_timeline = new_section("Calendario del Proceso", 12, _process_timeline_blocks(bundle))

    # Equipo y Organización — Mixto: base real de administradores + plantilla, editable
    emp = (bundle.get("statements") or {}).get("employees")
    wf = (bundle.get("identity") or {}).get("workforce") or {}
    wf_total = wf.get("total") or emp
    _tog = await _team_org_blocks(bundle, bundle["master_id"], cif_norm, _peers)

    # Slide 1 (medidas estándar): 1) Estructura operativa, 2) Equipo directivo y liderazgo,
    # 3) fila con el donut de sexo (compacto ~25%) + la diversidad de la plantilla.
    s_team_blocks = []
    s_team_blocks.extend(_tog["orgchart"])
    s_team_blocks.extend(_tog["leadership"])
    h, m = wf.get("hombres"), wf.get("mujeres")
    if (h is not None and m is not None) and (h or m):
        base = (h + m) or 1
        segs = [{"label": "Hombres", "value": h, "color": "#2E6BB0"},
                {"label": "Mujeres", "value": m, "color": "#C9569A"}]
        s_team_blocks.append(text_block("Diversidad de la plantilla", "subhead"))
        cd = chart_block("", "donut", {"segments": segs}, {"pair": True, "pair_width": "25%"})
        cd["data_lineage"] = {"source": "Iberinform (norm_companies.workforce)", "date": now_iso()}
        s_team_blocks.append(cd)
        s_team_blocks.append(insight_block(
            "Composición por sexo",
            f"El equipo está compuesto por {_es(f'{int(h):,}')} hombres ({_pct(h/base)}) y "
            f"{_es(f'{int(m):,}')} mujeres ({_pct(m/base)}) sobre un total de {_es(f'{int(base):,}')} personas.",
            importance="low"))
    s_team = new_section("Equipo y Organización", 6, s_team_blocks)

    # Slide 2: plantilla (KPIs total/fijos/temporales) + costes de personal + productividad
    s_team2_blocks = []
    if wf_total:
        s_team2_blocks.append(kpi_block("Plantilla total", _es(f"{int(wf_total):,}"), "empleados",
                                        commentary="equipo a cierre de ejercicio"))
    fij, tmp = wf.get("fijos"), wf.get("temporales")
    if fij is not None or tmp is not None:
        base_c = ((fij or 0) + (tmp or 0)) or 1
        if fij is not None:
            s_team2_blocks.append(kpi_block("Contratos fijos", _es(f"{int(fij):,}"), "empleados",
                                            commentary=f"{_pct((fij or 0)/base_c)} de la plantilla — estabilidad del empleo"))
        if tmp is not None:
            s_team2_blocks.append(kpi_block("Contratos temporales", _es(f"{int(tmp):,}"), "empleados",
                                            commentary=f"{_pct((tmp or 0)/base_c)} de la plantilla"))
    s_team2_blocks += _tog["costs"] + _tog["productivity"]
    s_team2 = new_section("Equipo y Organización · Costes y productividad", 6, s_team2_blocks) if s_team2_blocks else None

    # Proyecciones / Plan de Negocio — tres tablas de escenarios (Revenue, margen bruto, EBITDA a 3 años).
    s_proj_blocks = _projection_tables(bundle)
    if not s_proj_blocks:
        s_proj_blocks.append(_ph("[Completar: proyecciones financieras del plan de negocio.]"))
    s_proj = new_section("Proyecciones / Plan de Negocio", 11, s_proj_blocks)

    # Motivo de la operación — por qué la empresa quiere vender (narrativa editable + señal real si existe)
    s_why_blocks = [text_block("Motivación de la operación", "subhead")]
    _succession = any(("suces" in (str(sg.get("signal_type", "")) + str(sg.get("category", ""))).lower())
                      for sg in bundle.get("signals", []))
    if _succession:
        s_why_blocks.append(text_block("Existe una señal de relevo generacional / sucesión detectada en la "
                                       "compañía, coherente con un proceso de venta ordenada.", "bullet"))
    else:
        s_why_blocks.append(text_block("Relevo generacional o sucesión en la propiedad, buscando dar "
                                       "continuidad al proyecto con un socio solvente.", "bullet"))
    s_why_blocks += [
        text_block("Cristalización del valor construido tras años de crecimiento y consolidación de la posición "
                   "de mercado.", "bullet"),
        text_block("Incorporación de un socio que aporte capital y capacidades para acelerar el crecimiento "
                   "(expansión, internacionalización o nuevas líneas).", "bullet"),
        text_block("Foco estratégico de los actuales propietarios en otras actividades o desinversión ordenada "
                   "de una participación no estratégica.", "bullet"),
        text_block("[Completar con la motivación real del vendedor durante el proceso.]", "body"),
    ]
    s_why = new_section("Motivo de la Operación", 12, s_why_blocks)

    # Índice + separadores de sección (negro, estilo del cuaderno)
    def _sep(num, title):
        s = new_section(title, 0, [])
        s["slide_kind"] = "separator"; s["section_number"] = num
        return s

    parts = [
        ("01", "Resumen y Compañía", [s2, s3, s_cap, s_history]),
        ("02", "Negocio y Operativa", [s_prod, s_cli, s_moat, s_team, s_team2, s_teamstruct]),
        ("03", "Mercado y Competencia", [s6_market, s_tam, s_competition, s5, s5_charts]),
        ("04", "Rendimiento Financiero y Plan de Negocio", [s4, s_kpis, s_finpos, s_ebitda, s_proj]),
        ("05", "La Operación", [s_why, s_timeline, s7_risks]),
    ]
    _idx_rows = [[num, title] for num, title, _ in parts]
    s_index = new_section("Índice", 1, [
        text_block("Contenido del cuaderno de venta", "subhead"),
        table_block("", ["Sección", "Contenido"], _idx_rows),
    ])

    # Cierre en negro (como el cuaderno real): agradecimiento + confidencialidad + asesor.
    _close = cover_block(title="Gracias", subtitle="Documento estrictamente confidencial")
    _close["data"]["advisor"] = _advisor_label(brand_id)
    s_closing = new_section("Contacto", 99, [_close])
    s_closing["slide_kind"] = "closing"

    ordered = [s1, s_disclaimer, s_index]
    for num, title, secs in parts:
        ordered.append(_sep(num, title))
        ordered.extend(secs)
    ordered.append(s_closing)
    doc["sections"] = [s for s in ordered if s]
    doc["metadata"] = {
        "master_id": bundle["master_id"], "cif": cif_norm,
        "cnae_code": cnae, "type": "information_memorandum",
        "financial_engine_used": True, "fact_locked": True, "schema": "modern",
    }
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_company_snapshot(company_id: str = None, cif: str = None,
                                    brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Company Snapshot — minimal intelligence unit. Fase 2: modern schema + real engines."""
    from docstudio.financial_engine import analyze_sector_benchmark, compute_sector_positioning
    from services.cnae_catalog import CNAE_DIVISIONS

    bundle = await DA.company_intelligence(company_id or cif)
    if not bundle.get("found"):
        return {"error": "Company not found"}

    ident = bundle["identity"]
    name = ident.get("name", "Empresa")
    cnae = ident.get("cnae_code", "")
    cnae_label = resolve_cnae_label(cnae, fallback="")
    kpis = bundle.get("kpis", {})
    benchmark = await analyze_sector_benchmark(cnae) if cnae else {}

    # Comparables come REAL from the Financial Engine bundle (sector+size+geo)
    comparables = (bundle.get("comparables", {}) or {}).get("peers", [])

    # Sector positioning (deterministic percentiles) over real KPIs
    company_metrics = {
        "revenue": kpis.get("revenue"), "ebitda": kpis.get("ebitda"),
        "employees": (bundle.get("statements") or {}).get("employees"),
        "ebitda_margin": kpis.get("ebitda_margin"),
    }
    positioning = compute_sector_positioning(company_metrics, benchmark) if benchmark.get("peers") else {}

    doc = new_document(
        title=f"Company Snapshot — {name}",
        template_id="tpl_snapshot", brand_id=brand_id, created_by=user,
    )

    s1 = new_section("Portada", 1, [
        cover_block(title=name, subtitle=f"Company Snapshot — CNAE {cnae}: {cnae_label}"),
    ])

    # 2. KPIs (real Financial Engine)
    s2 = new_section("KPIs", 2, _company_kpi_blocks(bundle))

    # 3. Positioning (deterministic percentiles)
    pos_blocks = []
    if positioning:
        pos_rows = []
        for metric, data in positioning.items():
            v = data["value"]
            v_str = f"{v*100:.1f}%" if (v and abs(v) < 1) else f"{v:,.0f}"
            pos_rows.append([data["label"], v_str, f"P{data['percentile']:.0f}",
                             data["position"].replace("_", " ").title()])
        b = table_block("Posicionamiento sectorial", ["Métrica", "Valor", "Percentil", "Posición"], pos_rows)
        b["data_lineage"] = {"source": _FIN, "calculation": "sector_positioning", "date": now_iso()}
        pos_blocks.append(b)
    s3 = new_section("Posicionamiento", 3, pos_blocks) if pos_blocks else None

    # 4. Comparables (real, from Financial Engine)
    comp_blocks = []
    if comparables:
        comp_rows = []
        for c in comparables[:5]:
            m = c.get("ebitda_margin")
            comp_rows.append([
                (c.get("name") or "")[:35],
                f"{c['revenue']:,.0f}" if c.get("revenue") else "—",
                f"{m*100:.1f}%" if m is not None else "—",
                c.get("provincia", "—"),
            ])
        b = table_block("Comparables (sector+tamaño+geografía)", ["Empresa", "Revenue (EUR)", "Margen", "Provincia"], comp_rows)
        b["data_lineage"] = {"source": _FIN, "calculation": "financial_comparables", "date": now_iso()}
        comp_blocks.append(b)
    s4 = new_section("Comparables", 4, comp_blocks) if comp_blocks else None

    # 5. AI Conclusion (Claude, fact-locked, short)
    ai_context = {
        "company_name": name, "cnae": cnae, "cnae_label": cnae_label,
        "revenue": kpis.get("revenue"), "ebitda_margin": kpis.get("ebitda_margin"),
        "cagr": kpis.get("revenue_cagr"), "yoy": kpis.get("revenue_growth_yoy"),
        "positioning": positioning, "comparables_count": len(comparables),
        "active_signals": [s.get("signal_type") for s in bundle.get("signals", [])],
    }
    ai_result = await generate_summary(ai_context, doc_type="company_profile", document_id=doc["document_id"])

    s5 = new_section("Conclusión", 5, [])
    conclusion_text = ai_result.get("conclusion", ai_result.get("executive_summary", ""))
    if conclusion_text:
        sentences = conclusion_text.split(". ")
        short = ". ".join(sentences[:5]) + ("." if sentences and not sentences[-1].endswith(".") else "")
        b = text_block(short, style="conclusion")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "snapshot_conclusion", "date": now_iso()}
        s5["blocks"].append(b)

    doc["sections"] = [s for s in [s1, s2, s3, s4, s5] if s]
    doc["metadata"] = {
        "master_id": bundle["master_id"], "cnae_code": cnae, "type": "company_snapshot",
        "financial_engine_used": True, "fact_locked": True, "schema": "modern",
        "comparables_found": len(comparables), "sector_peers": benchmark.get("peers", 0),
    }
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_benchmark_advanced(cnae_code: str, company_id: str = None,
                                      brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Advanced Benchmark Report with comparables, positioning, and SWOT. <60 seconds."""
    from docstudio.financial_engine import analyze_sector_benchmark, compute_sector_positioning
    from services.cnae_catalog import CNAE_DIVISIONS

    cnae_label = resolve_cnae_label(cnae_code, fallback=cnae_code)
    await _get_economic_profile(cnae_code)  # available for AI context
    benchmark = await analyze_sector_benchmark(cnae_code)

    # If company provided, compute positioning + comparables from the real engine
    bundle = None
    company_name = None
    positioning = {}
    comparables = []
    if company_id:
        bundle = await DA.company_intelligence(company_id)
        if bundle.get("found"):
            company_name = bundle["identity"].get("name")
            kpis = bundle.get("kpis", {})
            company_metrics = {
                "revenue": kpis.get("revenue"), "ebitda": kpis.get("ebitda"),
                "employees": (bundle.get("statements") or {}).get("employees"),
                "ebitda_margin": kpis.get("ebitda_margin"),
            }
            positioning = compute_sector_positioning(company_metrics, benchmark)
            comparables = (bundle.get("comparables", {}) or {}).get("peers", [])

    doc = new_document(
        title=f"Benchmark Report — CNAE {cnae_code}: {cnae_label}",
        template_id="tpl_bud_benchmark", brand_id=brand_id, created_by=user,
    )

    # 1. Cover
    title_suffix = f" vs {company_name}" if company_name else ""
    s1 = new_section("Portada", 1, [
        cover_block(title=f"Benchmark Sectorial{title_suffix}", subtitle=f"CNAE {cnae_code}: {cnae_label}"),
    ])

    # 2. Sector KPIs (Financial Engine)
    bm_kpis = []
    bm_kpis.append(kpi_block("Empresas analizadas", str(benchmark.get("peers", 0)), "peers"))
    for metric, label, unit in [
        ("revenue", "Revenue mediana", "EUR"), ("ebitda", "EBITDA mediana", "EUR"),
        ("ebitda_margin", "Margen EBITDA med.", "%"), ("employees", "Empleados mediana", ""),
        ("revenue_per_employee", "Rev/empleado med.", "EUR"),
    ]:
        q = benchmark.get(metric, {})
        if q and q.get("median") is not None:
            val = q["median"]
            display = f"{val*100:.1f}" if metric == "ebitda_margin" else f"{val:,.0f}"
            b = kpi_block(label, display, unit)
            b["data_lineage"] = {"source": "financial_engine", "calculation": f"percentile_50({metric})", "date": now_iso()}
            bm_kpis.append(b)
    s3 = new_section("Benchmark del Sector", 3, bm_kpis)

    # 3. Distribution table (quartiles)
    quartile_rows = []
    for metric, label in [("revenue", "Revenue"), ("ebitda", "EBITDA"),
                          ("ebitda_margin", "Margen EBITDA"), ("employees", "Empleados"),
                          ("revenue_per_employee", "Rev/empleado")]:
        q = benchmark.get(metric, {})
        if q:
            def fmt_val(v, m=metric):
                return f"{v*100:.1f}%" if m == "ebitda_margin" else f"{v:,.0f}"
            quartile_rows.append([label, fmt_val(q.get("min", 0)), fmt_val(q.get("q1", 0)),
                                 fmt_val(q["median"]), fmt_val(q.get("q3", 0)), fmt_val(q.get("max", 0))])
    s4 = new_section("Distribucion Estadistica", 4, [
        table_block("Cuartiles sectoriales", ["Metrica", "Min", "Q1", "Mediana", "Q3", "Max"], quartile_rows),
    ]) if quartile_rows else None

    # 4. Company positioning (if company provided)
    s5 = None
    if positioning:
        pos_rows = []
        for metric, data in positioning.items():
            val_str = f"{data['value']*100:.1f}%" if metric == "ebitda_margin" else f"{data['value']:,.0f}"
            med_str = f"{data['median']*100:.1f}%" if metric == "ebitda_margin" else f"{data['median']:,.0f}"
            gap = data.get("gap_vs_median_pct")
            gap_str = f"{gap:+.1f}%" if gap is not None else "—"
            pos_rows.append([data["label"], val_str, med_str, gap_str,
                           f"P{data['percentile']:.0f}", data["position"].replace("_", " ").title()])
        b = table_block("Empresa vs Sector", ["Metrica", "Empresa", "Mediana", "Gap", "Percentil", "Posicion"], pos_rows)
        b["data_lineage"] = {"source": "financial_engine", "calculation": "sector_positioning", "date": now_iso()}
        s5 = new_section("Posicionamiento Competitivo", 5, [b])

    # 5. Comparables (real, from Financial Engine bundle)
    s6 = None
    if comparables:
        comp_rows = []
        for c in comparables[:8]:
            m = c.get("ebitda_margin")
            comp_rows.append([(c.get("name") or "")[:30], f"{c.get('revenue', 0):,.0f}",
                              f"{m*100:.1f}%" if m is not None else "—", c.get("provincia", "—")])
        b = table_block("Comparables (sector+tamaño+geografía)", ["Empresa", "Revenue", "Margen", "Provincia"], comp_rows)
        b["data_lineage"] = {"source": _FIN, "calculation": "financial_comparables", "date": now_iso()}
        s6 = new_section("Comparables", 6, [b])

    # 6. AI SWOT (Claude, fact-locked)
    ai_context = {
        "cnae_code": cnae_code, "cnae_label": cnae_label,
        "benchmark_peers": benchmark.get("peers", 0),
        "revenue_median": benchmark.get("revenue", {}).get("median"),
        "ebitda_margin_median": benchmark.get("ebitda_margin", {}).get("median"),
        "positioning": positioning if positioning else None,
        "comparables_count": len(comparables),
    }
    if bundle and bundle.get("found"):
        ai_context["company_name"] = company_name
        ai_context["company_revenue"] = bundle.get("kpis", {}).get("revenue")
        ai_context["company_margin"] = bundle.get("kpis", {}).get("ebitda_margin")

    ai_result = await generate_summary(ai_context, doc_type="sector_report", document_id=doc["document_id"])

    s2 = new_section("Resumen Ejecutivo", 2, [])
    if ai_result.get("executive_summary"):
        b = text_block(ai_result["executive_summary"], style="executive_summary")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "benchmark_summary", "date": now_iso()}
        s2["blocks"].append(b)

    s7_blocks = []
    for f in ai_result.get("key_findings", []):
        s7_blocks.append(insight_block("Hallazgo", f, importance="high"))
    if ai_result.get("conclusion"):
        b = text_block(ai_result["conclusion"], style="conclusion")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "benchmark_conclusion", "date": now_iso()}
        s7_blocks.append(b)
    s7 = new_section("Conclusiones", 7, s7_blocks) if s7_blocks else None

    doc["sections"] = [s for s in [s1, s2, s3, s4, s5, s6, s7] if s]
    doc["metadata"] = {
        "cnae_code": cnae_code, "type": "benchmark_advanced",
        "master_id": bundle["master_id"] if (bundle and bundle.get("found")) else None,
        "financial_engine_used": True, "fact_locked": True, "schema": "modern",
        "comparables_found": len(comparables), "sector_peers": benchmark.get("peers", 0),
    }
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc

async def compose_opportunities_document(cnae_section: str = None, provincia: str = None,
                                         signal_types: list = None, mandate_id: str = None,
                                         brand_id: str = "brand_bud", user: str = None,
                                         limit: int = 40) -> Dict:
    """Documento de Oportunidades (Fase 3, B3). SIEMPRE acotado (decisión 6): por filtros
    (sector/provincia/tipo) o por un mandato de comprador — NUNCA un volcado del universo.
    Consume Signal Intelligence (oportunidades reales) y, en modo mandato, el motor de
    Buyer Mandate (E1). Datos 100% reales; nada inventado.
    """
    from services.cnae_catalog import CNAE_SECTIONS

    # ── Modo mandato de comprador (E1) ──
    if mandate_id:
        from services.engines.recommendation.mandates import find_targets_for_mandate
        res = await find_targets_for_mandate(mandate_id, limit=limit)
        if not res:
            return {"error": "Mandate not found"}
        scope = f"Mandato: {res.get('mandate_name', mandate_id)}"
        doc = new_document(title=f"Documento de Oportunidades — {res.get('mandate_name', 'Mandato')}",
                           template_id="tpl_opportunities", brand_id=brand_id, created_by=user)
        s1 = new_section("Portada", 1, [cover_block(title="Documento de Oportunidades",
                         subtitle=f"{scope} — Confidencial")])
        s2 = new_section("Resumen", 2, [
            kpi_block("Targets identificados", str(res.get("count", 0)), "empresas"),
            kpi_block("Universo analizado", str(res.get("candidates_scanned", 0)), "candidatos"),
        ])
        rows = []
        for t in res.get("targets", []):
            rows.append([(t.get("name") or t.get("legal_name") or t.get("master_id") or "")[:40],
                         f"{round((t.get('score') or 0) * 100)}%",
                         t.get("provincia") or t.get("location", {}).get("provincia", "—")])
        s3 = new_section("Targets para el mandato", 3, [
            table_block("Empresas que encajan con el mandato", ["Empresa", "Encaje", "Provincia"], rows),
        ]) if rows else new_section("Targets para el mandato", 3, [
            text_block("No se han encontrado empresas que encajen con los criterios del mandato.", style="body")])
        doc["sections"] = [s1, s2, s3]
        doc["metadata"] = {"type": "opportunities", "mode": "mandate", "mandate_id": mandate_id,
                           "scope": scope, "count": res.get("count", 0), "schema": "modern"}
        doc["status"] = "generated"
        doc["updated_at"] = now_iso()
        await db.docstudio_documents.insert_one(doc)
        return doc

    # ── Modo filtros (sector/provincia/tipo) ──
    opps = await DA.scoped_opportunities(cnae_section=cnae_section, provincia=provincia,
                                         signal_types=signal_types, limit=limit)
    _sec_labels = {s["code"]: s["label"] for s in CNAE_SECTIONS}
    sec_label = _sec_labels.get(cnae_section, cnae_section) if cnae_section else None
    scope_parts = []
    if sec_label:
        scope_parts.append(f"Sector {cnae_section} — {sec_label}")
    if provincia:
        scope_parts.append(provincia)
    if signal_types:
        scope_parts.append(", ".join(signal_types))
    scope = " · ".join(scope_parts) if scope_parts else "Todas las oportunidades activas"

    doc = new_document(title=f"Documento de Oportunidades — {scope}",
                       template_id="tpl_opportunities", brand_id=brand_id, created_by=user)

    s1 = new_section("Portada", 1, [cover_block(title="Documento de Oportunidades",
                     subtitle=f"{scope} — Confidencial")])

    # Resumen: conteo + desglose por tipo
    by_type = {}
    for o in opps:
        by_type[o["signal_type"]] = by_type.get(o["signal_type"], 0) + 1
    s2_blocks = [kpi_block("Oportunidades", str(len(opps)), "activas")]
    for st, n in sorted(by_type.items(), key=lambda x: -x[1])[:4]:
        s2_blocks.append(kpi_block(st, str(n), ""))
    s2 = new_section("Resumen", 2, s2_blocks)

    # Tabla de oportunidades
    rows = []
    for o in opps:
        impact = (o.get("dimensions") or {}).get("impact")
        rows.append([(o.get("name") or "")[:40], o.get("signal_type", ""),
                     f"{round(impact * 100)}%" if impact is not None else "—",
                     (o.get("trend") or "—"), o.get("provincia") or "—"])
    s3 = new_section("Oportunidades detectadas", 3, [
        table_block("Empresas con señales de oportunidad activas",
                    ["Empresa", "Tipo de señal", "Impacto", "Tendencia", "Provincia"], rows),
    ]) if rows else new_section("Oportunidades detectadas", 3, [
        text_block("No hay oportunidades activas para este alcance.", style="body")])

    # Detalle de las más relevantes (top 5) como insights reales
    s4_blocks = []
    for o in opps[:5]:
        b = insight_block(o.get("name") or o.get("signal_type", ""), o.get("explanation", ""), importance="high")
        b["data_lineage"] = {"source": "signal-intelligence-v1", "signal_id": o.get("signal_id"), "date": now_iso()}
        s4_blocks.append(b)
    s4 = new_section("Oportunidades destacadas", 4, s4_blocks) if s4_blocks else None

    # Narrativa (Claude, fact-locked sobre el conjunto acotado)
    ai_context = {"scope": scope, "total": len(opps), "by_type": by_type,
                  "top": [{"name": o.get("name"), "type": o.get("signal_type"),
                           "explanation": o.get("explanation")} for o in opps[:8]]}
    ai_result = await generate_summary(ai_context, doc_type="sector_report", document_id=doc["document_id"])
    s5 = new_section("Lectura del analista", 5, [])
    if ai_result.get("executive_summary"):
        b = text_block(ai_result["executive_summary"], style="executive_summary")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "opportunities_narrative", "date": now_iso()}
        s5["blocks"].append(b)

    doc["sections"] = [s for s in [s1, s2, s3, s4, s5] if s]
    doc["metadata"] = {"type": "opportunities", "mode": "filters", "scope": scope,
                       "cnae_section": cnae_section, "provincia": provincia,
                       "count": len(opps), "fact_locked": True, "schema": "modern"}
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_ranking_document(cnae_section: str = None, cnae_code: str = None,
                                   provincia: str = None, sort_by: str = "revenue",
                                   brand_id: str = "brand_bud", user: str = None, limit: int = 25) -> Dict:
    """Ranking sectorial / de empresas (B4). Rankea empresas reales por facturación (o nº
    de señales) sobre `master_companies`. Nunca estima; empresas sin el dato se descartan."""
    from services.cnae_catalog import CNAE_SECTIONS, CNAE_DIVISIONS
    rows = await DA.rank_companies(cnae_section=cnae_section, cnae_code=cnae_code,
                                   provincia=provincia, sort_by=sort_by, limit=limit)
    sec_labels = {s["code"]: s["label"] for s in CNAE_SECTIONS}
    scope = None
    if cnae_code:
        scope = f"CNAE {cnae_code} — {resolve_cnae_label(cnae_code, fallback='')}"
    elif cnae_section:
        scope = f"Sección {cnae_section} — {sec_labels.get(cnae_section, '')}"
    if provincia:
        scope = f"{scope} · {provincia}" if scope else provincia
    scope = scope or "Universo completo"
    metric_label = "nº de señales activas" if sort_by == "signals" else "facturación"

    doc = new_document(title=f"Ranking — {scope}", template_id="tpl_ranking", brand_id=brand_id, created_by=user)
    s1 = new_section("Portada", 1, [cover_block(title="Ranking de Empresas", subtitle=f"{scope} · por {metric_label}")])
    s2 = new_section("Resumen", 2, [kpi_block("Empresas en el ranking", str(len(rows)), ""),
                                    kpi_block("Ordenado por", metric_label, "")])
    trows = []
    for i, r in enumerate(rows, start=1):
        m = r.get("ebitda_margin")
        trows.append([str(i), (r.get("name") or "")[:38],
                      f"{r['revenue']:,.0f}" if r.get("revenue") else "—",
                      f"{m*100:.1f}%" if m is not None else "—",
                      str(r.get("active_signals", 0)), r.get("provincia") or "—"])
    s3 = new_section("Ranking", 3, [table_block("Empresas ordenadas",
        ["#", "Empresa", "Facturación (EUR)", "Margen", "Señales", "Provincia"], trows)]) if trows else \
        new_section("Ranking", 3, [text_block("No hay empresas con datos suficientes para este alcance.", style="body")])
    doc["sections"] = [s1, s2, s3]
    doc["metadata"] = {"type": "ranking", "scope": scope, "sort_by": sort_by, "count": len(rows), "schema": "modern"}
    doc["status"] = "generated"; doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_fragmentation_document(cnae_section: str = None, cnae_code: str = None,
                                         brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Mapa de fragmentación sectorial (B6). Consume E7 `compute_fragmentation` (HHI real
    sobre grupos de propiedad, targets standalone, dispersión de múltiplos honesta)."""
    from services.engines.investment.fragmentation import compute_fragmentation
    from services.cnae_catalog import CNAE_SECTIONS, CNAE_DIVISIONS
    field = "cnae_code" if cnae_code else "cnae_section"
    value = cnae_code or cnae_section
    if not value:
        return {"error": "Indica cnae_section o cnae_code"}
    frag = await compute_fragmentation(field, value)
    sec_labels = {s["code"]: s["label"] for s in CNAE_SECTIONS}
    label = resolve_cnae_label(cnae_code or cnae_section, fallback="")
    scope = f"{value} — {label}"

    doc = new_document(title=f"Fragmentación sectorial — {scope}", template_id="tpl_fragmentation",
                       brand_id=brand_id, created_by=user)
    s1 = new_section("Portada", 1, [cover_block(title="Mapa de Fragmentación Sectorial", subtitle=scope)])
    hhi = frag.get("hhi")
    kpis = [kpi_block("Empresas en el universo", str(frag.get("total_companies_in_arroba_universe", 0)), ""),
            kpi_block("Actores de mercado (grupos)", str(frag.get("market_actors_count", 0)), ""),
            kpi_block("Targets standalone", str(frag.get("standalone_targets_count", 0)), "add-on viables")]
    if hhi is not None:
        kpis.insert(0, kpi_block("HHI", f"{hhi:,.0f}", frag.get("concentration_label", ""),
                                 commentary="Índice Herfindahl-Hirschman (DOJ/FTC, 0-10000)"))
    s2 = new_section("Concentración del sector", 2, kpis)
    disp = frag.get("multiple_dispersion")
    s3_blocks = [text_block(frag.get("hhi_methodology", ""), style="body")]
    if disp is None and frag.get("multiple_dispersion_caveat"):
        s3_blocks.append(insight_block("Dispersión de múltiplos", frag["multiple_dispersion_caveat"], importance="medium"))
    s3 = new_section("Metodología y caveats", 3, s3_blocks)

    ai_context = {"scope": scope, "hhi": hhi, "concentration": frag.get("concentration_label"),
                  "standalone_targets": frag.get("standalone_targets_count"),
                  "market_actors": frag.get("market_actors_count")}
    ai_result = await generate_summary(ai_context, doc_type="sector_report", document_id=doc["document_id"])
    s4 = new_section("Lectura del analista", 4, [])
    if ai_result.get("executive_summary"):
        b = text_block(ai_result["executive_summary"], style="executive_summary")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "fragmentation_narrative", "date": now_iso()}
        s4["blocks"].append(b)

    doc["sections"] = [s1, s2, s3, s4]
    doc["metadata"] = {"type": "fragmentation", "scope": scope, "hhi": hhi,
                       "engine": frag.get("engine_version"), "schema": "modern"}
    doc["status"] = "generated"; doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_rollup_document(cnae_section: str = None, cnae_code: str = None,
                                  brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Tesis de roll-up / consolidación (B5). Consume E6 `compute_rollup_thesis`."""
    from services.engines.investment.rollup_thesis import compute_rollup_thesis
    from services.cnae_catalog import CNAE_SECTIONS, CNAE_DIVISIONS
    field = "cnae_code" if cnae_code else "cnae_section"
    value = cnae_code or cnae_section
    if not value:
        return {"error": "Indica cnae_section o cnae_code"}
    thesis = await compute_rollup_thesis(field, value)
    sec_labels = {s["code"]: s["label"] for s in CNAE_SECTIONS}
    label = resolve_cnae_label(cnae_code or cnae_section, fallback="")
    scope = f"{value} — {label}"
    viable = thesis.get("rollup_viable")
    plat = thesis.get("platform_candidate") or {}

    doc = new_document(title=f"Tesis de Roll-up — {scope}", template_id="tpl_rollup", brand_id=brand_id, created_by=user)
    s1 = new_section("Portada", 1, [cover_block(title="Tesis de Roll-up / Consolidación", subtitle=scope)])
    viab_txt = "Viable" if viable is True else "No viable" if viable is False else "Datos insuficientes"
    s2 = new_section("Viabilidad", 2, [
        kpi_block("Viabilidad del roll-up", viab_txt, ""),
        kpi_block("Targets add-on", str(thesis.get("addon_targets_count", 0)), "empresas"),
    ] + [insight_block("Motivo", r, importance="medium") for r in thesis.get("viability_reasons", [])[:3]])
    plat_blocks = []
    if plat:
        plat_blocks.append(kpi_block("Candidato a plataforma", (plat.get("name") or "—"),
                                     f"cuota {round((plat.get('market_share') or 0)*100)}%"))
        plat_blocks.append(insight_block("Tipo de plataforma",
            "Existe un actor con escala suficiente" if plat.get("platform_type") == "existing"
            else "Se necesitaría una plataforma externa (ningún actor tiene escala dominante)", importance="high"))
    s3 = new_section("Candidato a plataforma", 3, plat_blocks) if plat_blocks else None
    trows = []
    for t in thesis.get("addon_targets_ranked", [])[:15]:
        trows.append([(t.get("name") or "")[:38],
                      f"{t['revenue']:,.0f}" if t.get("revenue") else "—",
                      f"{round((t.get('addon_score') or 0)*100)}%"])
    s4 = new_section("Ranking de add-ons", 4, [table_block("Targets add-on ordenados por encaje",
        ["Empresa", "Facturación (EUR)", "Encaje"], trows)]) if trows else None

    ai_context = {"scope": scope, "viable": viable, "platform": plat.get("name"),
                  "addon_count": thesis.get("addon_targets_count")}
    ai_result = await generate_summary(ai_context, doc_type="sector_report", document_id=doc["document_id"])
    s5 = new_section("Lectura del analista", 5, [])
    if ai_result.get("executive_summary"):
        b = text_block(ai_result["executive_summary"], style="executive_summary")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "rollup_narrative", "date": now_iso()}
        s5["blocks"].append(b)

    doc["sections"] = [s for s in [s1, s2, s3, s4, s5] if s]
    doc["metadata"] = {"type": "rollup", "scope": scope, "rollup_viable": viable,
                       "engine": thesis.get("engine_version"), "schema": "modern"}
    doc["status"] = "generated"; doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_succession_document(company_id: str = None, cif: str = None,
                                      brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Perfil de sucesión (A7). Consume E2 `build_profile` — proxy honesto por tenure del
    administrador y apellidos compartidos (nunca confirma parentesco; caveat explícito)."""
    from services.engines.signal.succession_intelligence import build_profile
    from services.cnae_catalog import CNAE_DIVISIONS
    master = await DA.resolve_company(company_id or cif)
    if not master:
        return {"error": "Company not found"}
    profile = await build_profile(master)
    name = (master.get("identity") or {}).get("legal_name", "Empresa")
    cnae = (master.get("classification") or {}).get("cnae_code", "")

    doc = new_document(title=f"Perfil de Sucesión — {name}", template_id="tpl_succession",
                       brand_id=brand_id, created_by=user)
    s1 = new_section("Portada", 1, [cover_block(title="Perfil de Sucesión", subtitle=f"{name} — CNAE {cnae}: {resolve_cnae_label(cnae, fallback='')}")])

    if not profile:
        doc["sections"] = [s1, new_section("Sin perfil", 2, [text_block(
            "No hay datos de administrador suficientes para construir un perfil de sucesión enriquecido.", style="body")])]
        doc["metadata"] = {"type": "succession", "master_id": master.get("master_id"), "has_profile": False, "schema": "modern"}
        doc["status"] = "generated"; doc["updated_at"] = now_iso()
        await db.docstudio_documents.insert_one(doc)
        return doc

    admin = profile.get("administrator", {})
    kpis = [kpi_block("Riesgo de sucesión", str(profile.get("succession_risk_score", "—")), "/100"),
            kpi_block("Antigüedad del administrador", f"{admin.get('tenure_years', '—')}", "años"),
            kpi_block("Nº de administradores", str(profile.get("admin_count", "—")), ""),
            kpi_block("Empresa familiar (probable)", "Sí" if profile.get("family_business_probable") else "No", "")]
    if profile.get("company_age_years") is not None:
        kpis.append(kpi_block("Antigüedad de la empresa", f"{profile['company_age_years']}", "años"))
    s2 = new_section("Indicadores", 2, kpis)

    reason_blocks = [insight_block("Factor", r, importance="high") for r in profile.get("reasons", [])[:6]]
    if profile.get("successor_candidate"):
        reason_blocks.append(insight_block("Posible sucesor ya nombrado",
            "Se ha detectado un cargo nombrado con posterioridad que podría actuar como sucesor.", importance="medium"))
    s3 = new_section("Factores de la valoración", 3, reason_blocks) if reason_blocks else None

    s4 = new_section("Advertencia de datos", 4, [text_block(profile.get("data_caveat", ""), style="body")])

    doc["sections"] = [s for s in [s1, s2, s3, s4] if s]
    doc["metadata"] = {"type": "succession", "master_id": master.get("master_id"), "has_profile": True,
                       "succession_risk_score": profile.get("succession_risk_score"),
                       "profile_version": profile.get("profile_version"), "schema": "modern"}
    doc["status"] = "generated"; doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_valuation_approx(company_id: str = None, cif: str = None,
                                   brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Aproximación de valor (A5). Documento corto: la valoración REAL del motor financiero
    (honesta: market_observed vs inferred_reference, o nada si insuficiente) + su método."""
    from services.cnae_catalog import CNAE_DIVISIONS
    bundle = await DA.company_intelligence(company_id or cif, include_signals=False)
    if not bundle.get("found"):
        return {"error": "Company not found"}
    ident = bundle["identity"]; name = ident.get("name", "Empresa"); cnae = ident.get("cnae_code", "")
    val = bundle.get("valuation", {}) or {}

    doc = new_document(title=f"Aproximación de Valor — {name}", template_id="tpl_valuation_approx",
                       brand_id=brand_id, created_by=user)
    s1 = new_section("Portada", 1, [cover_block(title="Aproximación de Valor",
                     subtitle=f"{name} — CNAE {cnae}: {resolve_cnae_label(cnae, fallback='')}")])
    s2_blocks = _company_kpi_blocks(bundle)[:3]
    vb = _valuation_block(bundle)
    if vb:
        s2_blocks.insert(0, vb)
    s2 = new_section("Valoración orientativa", 2, s2_blocks)

    s3_blocks = []
    rng = val.get("range") or {}
    if rng.get("low") and rng.get("high"):
        s3_blocks.append(text_block(f"Rango orientativo: {rng['low']:,.0f} € – {rng['high']:,.0f} € "
                                    f"(confianza {val.get('confidence', '—')}).", style="body"))
    for h in val.get("hypotheses", []):
        s3_blocks.append(insight_block("Supuesto", h, importance="medium"))
    if not s3_blocks:
        s3_blocks.append(text_block("Datos insuficientes para una valoración fiable.", style="body"))
    s3 = new_section("Método y supuestos", 3, s3_blocks)

    # Ratios + posicionamiento sectorial propio (contexto de la valoración)
    s4_blocks = []
    _rt = FE.ratios_table_block(bundle)
    if _rt:
        s4_blocks.append(_rt)
    _sp = await FE.sector_positioning_block(db, bundle)
    if _sp:
        s4_blocks.append(_sp)
    s4 = new_section("Indicadores y sector", 4, s4_blocks) if s4_blocks else None

    doc["sections"] = [s for s in [s1, s2, s3, s4] if s]
    doc["metadata"] = {"type": "valuation_approx", "master_id": bundle["master_id"],
                       "valuation_method": val.get("method"), "fact_locked": True, "schema": "modern"}
    doc["status"] = "generated"; doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_valuation_advanced(company_id: str = None, cif: str = None,
                                     brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Valoración avanzada (A6). Valoración real + comparables reales + escenarios
    (conservador/base/agresivo) del Strategy Engine + narrativa."""
    from services.engines.strategy import engine as strat
    from services.cnae_catalog import CNAE_DIVISIONS
    bundle = await DA.company_intelligence(company_id or cif)
    if not bundle.get("found"):
        return {"error": "Company not found"}
    ident = bundle["identity"]; name = ident.get("name", "Empresa"); cnae = ident.get("cnae_code", "")
    val = bundle.get("valuation", {}) or {}
    scen = await strat.scenarios(bundle["master_id"]) or {}

    doc = new_document(title=f"Valoración Avanzada — {name}", template_id="tpl_valuation_advanced",
                       brand_id=brand_id, created_by=user)
    s1 = new_section("Portada", 1, [cover_block(title="Valoración Avanzada",
                     subtitle=f"{name} — CNAE {cnae}: {resolve_cnae_label(cnae, fallback='')}")])

    s2_blocks = _company_kpi_blocks(bundle)[:3]
    vb = _valuation_block(bundle)
    if vb:
        s2_blocks.insert(0, vb)
    rng = val.get("range") or {}
    if rng.get("low") and rng.get("high"):
        s2_blocks.append(kpi_block("Rango de valoración", f"{rng['low']:,.0f} – {rng['high']:,.0f}", "EUR"))
    for _fb in FE.financial_detail_blocks(bundle):
        s2_blocks.append(_fb)
    _sp = await FE.sector_positioning_block(db, bundle)
    if _sp:
        s2_blocks.append(_sp)
    s2 = new_section("Valoración", 2, s2_blocks)

    # Comparables reales (del motor financiero)
    comps = (bundle.get("comparables", {}) or {}).get("peers", [])
    crows = []
    for c in comps[:8]:
        m = c.get("ebitda_margin")
        crows.append([(c.get("name") or "")[:34], f"{c['revenue']:,.0f}" if c.get("revenue") else "—",
                      f"{m*100:.1f}%" if m is not None else "—", c.get("provincia", "—")])
    s3 = new_section("Comparables", 3, [table_block("Empresas comparables (sector+tamaño+geografía)",
        ["Empresa", "Revenue (EUR)", "Margen", "Provincia"], crows)]) if crows else None

    # Escenarios (Strategy Engine)
    srows = []
    for sc in scen.get("scenarios", []):
        srows.append([sc.get("scenario", ""), f"{round((sc.get('score') or 0)*100)}%",
                      (sc.get("narrative") or "")[:80]])
    s4 = new_section("Escenarios", 4, [table_block("Escenarios estratégicos",
        ["Escenario", "Atractivo", "Descripción"], srows)]) if srows else None

    ai_context = {"company_name": name, "valuation": val, "scenarios": scen.get("decision_support"),
                  "comparables_count": len(comps)}
    ai_result = await generate_summary(ai_context, doc_type="company_profile", document_id=doc["document_id"])
    s5 = new_section("Lectura del analista", 5, [])
    if ai_result.get("executive_summary"):
        b = text_block(ai_result["executive_summary"], style="executive_summary")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "valuation_narrative", "date": now_iso()}
        s5["blocks"].append(b)

    doc["sections"] = [s for s in [s1, s2, s3, s4, s5] if s]
    from documents.renderers.advanced_valuation_pdf import build_advanced_valuation_payload
    canonical_pdf_payload = build_advanced_valuation_payload(bundle)
    doc["metadata"] = {"type": "valuation_advanced", "master_id": bundle["master_id"],
                       "valuation_method": val.get("method"), "fact_locked": True,
                       "schema": "modern", "pdf_renderer": "advanced_valuation_pdf_v1",
                       "canonical_pdf_payload": canonical_pdf_payload}
    doc["status"] = "generated"; doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_strategic_analysis(company_id: str = None, cif: str = None,
                                     brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Análisis estratégico de empresa (A3). El más compuesto: Financial + Signal +
    Strategy (tesis estratégica con dimensiones, tipo recomendado y alternativa)."""
    from services.engines.strategy import engine as strat
    from services.cnae_catalog import CNAE_DIVISIONS
    bundle = await DA.company_intelligence(company_id or cif)
    if not bundle.get("found"):
        return {"error": "Company not found"}
    ident = bundle["identity"]; name = ident.get("name", "Empresa"); cnae = ident.get("cnae_code", "")
    th = await strat.thesis(bundle["master_id"]) or {}

    doc = new_document(title=f"Análisis Estratégico — {name}", template_id="tpl_strategic",
                       brand_id=brand_id, created_by=user)
    s1 = new_section("Portada", 1, [cover_block(title="Análisis Estratégico de Empresa",
                     subtitle=f"{name} — CNAE {cnae}: {resolve_cnae_label(cnae, fallback='')}")])
    s2_blocks = _company_kpi_blocks(bundle)
    for _fb in FE.financial_detail_blocks(bundle):
        s2_blocks.append(_fb)
    _sp = await FE.sector_positioning_block(db, bundle)
    if _sp:
        s2_blocks.append(_sp)
    s2 = new_section("Indicadores", 2, s2_blocks)

    sig_blocks = _signal_insight_blocks(bundle)
    s3 = new_section("Señales Activas", 3, sig_blocks) if sig_blocks else None

    # Tesis estratégica
    s4_blocks = []
    if th:
        if th.get("statement"):
            s4_blocks.append(text_block(th["statement"], style="executive_summary"))
        s4_blocks.append(kpi_block("Tesis recomendada", th.get("thesis_type", "—"),
                                   f"score {th.get('score', '—')}"))
        if th.get("preferred_rationale"):
            s4_blocks.append(insight_block("Por qué esta tesis", th["preferred_rationale"], importance="high"))
        for alt in th.get("alternatives", [])[:2]:
            s4_blocks.append(insight_block(f"Alternativa: {alt.get('thesis_type', '')}",
                                           alt.get("why_not_preferred", ""), importance="medium"))
    s4 = new_section("Tesis Estratégica", 4, s4_blocks) if s4_blocks else None

    ai_context = {"company_name": name, "kpis": bundle.get("kpis"),
                  "assessment": bundle.get("assessment"),
                  "thesis": {"type": th.get("thesis_type"), "statement": th.get("statement")},
                  "active_signals": [s.get("signal_type") for s in bundle.get("signals", [])]}
    ai_result = await generate_summary(ai_context, doc_type="company_profile", document_id=doc["document_id"])
    s5 = new_section("Conclusión", 5, [])
    if ai_result.get("conclusion") or ai_result.get("executive_summary"):
        b = text_block(ai_result.get("conclusion") or ai_result["executive_summary"], style="conclusion")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "strategic_narrative", "date": now_iso()}
        s5["blocks"].append(b)

    doc["sections"] = [s for s in [s1, s2, s3, s4, s5] if s]
    doc["metadata"] = {"type": "strategic_analysis", "master_id": bundle["master_id"],
                       "thesis_type": th.get("thesis_type"), "fact_locked": True, "schema": "modern"}
    doc["status"] = "generated"; doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


async def compose_comparative_analysis(company_id: str = None, cif: str = None,
                                       brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Análisis comparativo (A4). Empresa frente a sus comparables reales (sector+tamaño+
    geografía, del Financial Engine), lado a lado por métrica. Datos reales, sin inventar."""
    from services.cnae_catalog import CNAE_DIVISIONS
    bundle = await DA.company_intelligence(company_id or cif, include_signals=False)
    if not bundle.get("found"):
        return {"error": "Company not found"}
    ident = bundle["identity"]; name = ident.get("name", "Empresa"); cnae = ident.get("cnae_code", "")
    kpis = bundle.get("kpis", {})
    peers = (bundle.get("comparables", {}) or {}).get("peers", [])

    doc = new_document(title=f"Análisis Comparativo — {name}", template_id="tpl_comparative",
                       brand_id=brand_id, created_by=user)
    s1 = new_section("Portada", 1, [cover_block(title="Análisis Comparativo",
                     subtitle=f"{name} — CNAE {cnae}: {resolve_cnae_label(cnae, fallback='')}")])
    s2 = new_section("La empresa", 2, _company_kpi_blocks(bundle))

    # Tabla lado a lado: empresa (primera fila destacada) + comparables
    def _row(label, rev, mar, emp, prov):
        return [label, f"{rev:,.0f}" if rev else "—",
                f"{mar*100:.1f}%" if mar is not None else "—",
                str(emp) if emp else "—", prov or "—"]
    rows = [_row(f"» {name}", kpis.get("revenue"), kpis.get("ebitda_margin"),
                 (bundle.get("statements") or {}).get("employees"), ident.get("provincia"))]
    for c in peers[:8]:
        rows.append(_row((c.get("name") or "")[:34], c.get("revenue"), c.get("ebitda_margin"), None, c.get("provincia")))
    s3 = new_section("Comparación lado a lado", 3, [table_block("Empresa vs comparables",
        ["Empresa", "Revenue (EUR)", "Margen EBITDA", "Empleados", "Provincia"], rows)])

    # Posición relativa (percentil de margen ya calculado por el motor)
    pct = (bundle.get("comparables", {}) or {}).get("subject_ebitda_margin_percentile")
    s4_blocks = []
    if pct is not None:
        s4_blocks.append(kpi_block("Percentil de margen EBITDA", f"P{round(pct*100)}", "vs comparables"))
    _sp = await FE.sector_positioning_block(db, bundle)
    if _sp:
        s4_blocks.append(_sp)
    s4 = new_section("Posición relativa", 4, s4_blocks) if s4_blocks else None

    ai_context = {"company_name": name, "kpis": kpis, "peers_count": len(peers),
                  "margin_percentile": pct}
    ai_result = await generate_summary(ai_context, doc_type="company_profile", document_id=doc["document_id"])
    s5 = new_section("Lectura del analista", 5, [])
    if ai_result.get("executive_summary"):
        b = text_block(ai_result["executive_summary"], style="executive_summary")
        b["data_lineage"] = {"source": "ai", "model": "claude", "task": "comparative_narrative", "date": now_iso()}
        s5["blocks"].append(b)

    doc["sections"] = [s for s in [s1, s2, s3, s4, s5] if s]
    doc["metadata"] = {"type": "comparative", "master_id": bundle["master_id"],
                       "peers": len(peers), "fact_locked": True, "schema": "modern"}
    doc["status"] = "generated"; doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


def build_manual_sections(manual_blocks, start_order: int = 100) -> list:
    """Convierte el contenido comercial que aporta el consumidor/asesor (`manual_blocks`)
    en secciones de bloques reales. Formato flexible:

      { "Servicios": ["Eventos", "Marketing ferial", ...],      # lista -> bullets
        "Descripción de la compañía": "texto…",                 # str -> párrafo
        "Sectores de clientes": {"columns": [...], "rows": [...]} }  # dict -> tabla

    Los bloques quedan marcados con lineage 'manual' y son editables desde el editor.
    """
    if not manual_blocks or not isinstance(manual_blocks, dict):
        return []
    sections = []
    order = start_order
    for title, value in manual_blocks.items():
        blocks = []
        if isinstance(value, str):
            b = text_block(value, style="body")
            b["data_lineage"] = {"source": "manual", "date": now_iso()}
            blocks.append(b)
        elif isinstance(value, list):
            for item in value:
                b = text_block(f"• {item}", style="body")
                b["data_lineage"] = {"source": "manual", "date": now_iso()}
                blocks.append(b)
        elif isinstance(value, dict) and value.get("columns"):
            b = table_block(value.get("title", ""), value.get("columns", []), value.get("rows", []))
            b["data_lineage"] = {"source": "manual", "date": now_iso()}
            blocks.append(b)
        elif isinstance(value, dict) and value.get("text"):
            b = text_block(value["text"], style="body")
            b["data_lineage"] = {"source": "manual", "date": now_iso()}
            blocks.append(b)
        if blocks:
            sections.append(new_section(title, order, blocks))
            order += 1
    return sections


async def apply_manual_blocks(document_id: str, manual_blocks) -> Dict:
    """Añade las secciones manuales al documento ya compuesto y lo persiste. Idempotente
    por título: no duplica una sección manual que ya exista con el mismo título."""
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found"}
    existing_titles = {s.get("title") for s in doc.get("sections", [])}
    new_secs = [s for s in build_manual_sections(manual_blocks) if s["title"] not in existing_titles]
    if not new_secs:
        return doc
    doc["sections"] = doc.get("sections", []) + new_secs
    doc["metadata"] = {**doc.get("metadata", {}), "has_manual_blocks": True}
    await db.docstudio_documents.update_one(
        {"document_id": document_id},
        {"$set": {"sections": doc["sections"], "metadata": doc["metadata"], "updated_at": now_iso()}})
    return doc


def compute_quality_score(doc: Dict) -> Dict:
    """Compute a quality score for a document. Deterministic, no AI."""
    scores = {}
    sections = doc.get("sections", [])
    all_blocks = [b for s in sections for b in s.get("blocks", [])]

    # 1. Data completeness (are sections populated?)
    total_sections = len(sections)
    populated = sum(1 for s in sections if s.get("blocks"))
    scores["data_completeness"] = round(populated / max(total_sections, 1) * 100)

    # 2. Financial coverage (KPI blocks with Financial Engine lineage)
    kpi_blocks = [b for b in all_blocks if b.get("block_type") == "kpi"]
    _fin_sources = {"financial_engine", "financial-intelligence-v1"}
    fin_engine_blocks = [b for b in all_blocks if b.get("data_lineage", {}).get("source") in _fin_sources]
    scores["financial_coverage"] = round(len(fin_engine_blocks) / max(len(kpi_blocks), 1) * 100)

    # 3. Missing sections
    expected_types = {"cover", "text", "kpi", "insight"}
    present_types = set(b.get("block_type") for b in all_blocks)
    scores["block_variety"] = round(len(present_types & expected_types) / len(expected_types) * 100)

    # 4. AI confidence (check if AI blocks exist and have lineage)
    ai_blocks = [b for b in all_blocks if b.get("data_lineage", {}).get("source") == "ai"]
    scores["ai_coverage"] = min(100, len(ai_blocks) * 20)  # 5+ AI blocks = 100%

    # 5. Fact-lock compliance
    fact_locked = doc.get("metadata", {}).get("fact_locked", False)
    no_untraced = all(b.get("data_lineage") for b in all_blocks if b.get("block_type") not in ("divider", "cover"))
    scores["fact_lock_compliance"] = 100 if fact_locked and no_untraced else 60 if no_untraced else 30

    # Global score
    weights = {"data_completeness": 0.25, "financial_coverage": 0.20, "block_variety": 0.15,
               "ai_coverage": 0.15, "fact_lock_compliance": 0.25}
    global_score = round(sum(scores[k] * weights[k] for k in weights))

    return {
        "global_score": global_score,
        "scores": scores,
        "total_blocks": len(all_blocks),
        "total_sections": total_sections,
        "ai_blocks": len(ai_blocks),
        "financial_engine_blocks": len(fin_engine_blocks),
        "grade": "A" if global_score >= 85 else "B" if global_score >= 70 else "C" if global_score >= 50 else "D",
    }


# ══════════════════════════════════════════
# GENERIC TEMPLATE COMPOSER
# ══════════════════════════════════════════

async def compose_from_template(template_id: str, company_id: str = None, cif: str = None,
                                 cnae_code: str = None, brand_id: str = "brand_bud",
                                 user: str = None) -> Dict:
    """Compose a document from ANY user-created template. No hardcoded logic per template.
    
    Reads the template's section definitions, resolves data sources, and populates blocks.
    """
    from docstudio.financial_engine import analyze_sector_benchmark
    from services.cnae_catalog import CNAE_DIVISIONS

    template = await db.docstudio_templates.find_one({"template_id": template_id}, {"_id": 0})
    if not template:
        return {"error": f"Template {template_id} not found"}

    # Resolve company (modern schema + real engines) if provided
    bundle = None
    company_name = None
    kpis = {}
    if company_id or cif:
        bundle = await DA.company_intelligence(company_id or cif)
        if bundle.get("found"):
            company_name = bundle["identity"].get("name")
            cnae_code = cnae_code or bundle["identity"].get("cnae_code")
            kpis = bundle.get("kpis", {})

    cnae_label = resolve_cnae_label(cnae_code, fallback="")
    benchmark = await analyze_sector_benchmark(cnae_code) if cnae_code else {}
    econ = await _get_economic_profile(cnae_code) if cnae_code else {}

    # Build document
    title_entity = company_name or cnae_label
    doc = new_document(
        title=f"{template.get('name', 'Documento')} — {title_entity}",
        template_id=template_id,
        brand_id=brand_id or template.get("brand_id", "brand_bud"),
        created_by=user,
    )

    sections = []
    now = now_iso()

    for tpl_section in template.get("sections", []):
        blocks = []
        title = tpl_section.get("title", "")
        block_types = tpl_section.get("block_types", [])
        data_source = tpl_section.get("data_source", "")

        # Cover block
        if "cover" in block_types:
            blocks.append(cover_block(
                title=title_entity,
                subtitle=f"{template.get('name', '')} — CNAE {cnae_code}: {cnae_label}" if cnae_code else template.get("name", ""),
            ))

        # KPI blocks from data sources
        if "kpi" in block_types:
            if data_source in ("financial_engine", "") and bundle and bundle.get("found"):
                blocks.extend(_company_kpi_blocks(bundle))
            elif data_source == "economic_intelligence" and econ:
                if econ.get("active_companies_national"):
                    blocks.append(kpi_block("Empresas activas", f"{econ['active_companies_national']['value']:,.0f}", ""))
                if econ.get("exports_eur"):
                    blocks.append(kpi_block("Exportaciones", f"{econ['exports_eur']['value']:,.0f}", "EUR"))

        # Table blocks
        if "table" in block_types:
            if bundle and bundle.get("found"):
                ident = bundle["identity"]
                info_rows = [["Razón social", company_name or ""], ["CIF", bundle.get("cif_normalized", "—")]]
                if ident.get("provincia"):
                    info_rows.append(["Provincia", ident["provincia"]])
                if cnae_label:
                    info_rows.append(["Sector", f"CNAE {cnae_code}: {cnae_label}"])
                blocks.append(table_block("Información", ["Campo", "Valor"], info_rows))

            if benchmark.get("peers"):
                bm_rows = []
                for m, label in [("revenue", "Revenue"), ("ebitda", "EBITDA"), ("ebitda_margin", "Margen")]:
                    q = benchmark.get(m, {})
                    if q and q.get("median") is not None:
                        def fmt(v, metric=m):
                            return f"{v*100:.1f}%" if metric == "ebitda_margin" else f"{v:,.0f}"
                        bm_rows.append([label, fmt(q.get("q1", 0)), fmt(q["median"]), fmt(q.get("q3", 0))])
                if bm_rows:
                    b = table_block("Benchmark", ["Métrica", "Q1", "Mediana", "Q3"], bm_rows)
                    b["data_lineage"] = {"source": _FIN, "calculation": "quartiles", "date": now}
                    blocks.append(b)

        # Signal insight blocks (real) when the section wants insights and we have a company
        if "insight" in block_types and data_source in ("signal", "signals") and bundle and bundle.get("found"):
            blocks.extend(_signal_insight_blocks(bundle))

        # AI text/insight blocks — data_source 'ai' OR text/insight without another source
        needs_ai = data_source == "ai" or (("text" in block_types or "insight" in block_types)
                    and data_source not in ("financial_engine", "economic_intelligence", "signal", "signals"))
        if needs_ai:
            ai_context = {
                "section_title": title, "company_name": company_name,
                "cnae": cnae_code, "cnae_label": cnae_label,
                "revenue": kpis.get("revenue"), "ebitda_margin": kpis.get("ebitda_margin"),
                "growth": kpis.get("revenue_growth_yoy"), "sector_peers": benchmark.get("peers", 0),
                "active_signals": [s.get("signal_type") for s in (bundle.get("signals", []) if bundle else [])],
            }
            ai_result = await generate_summary(ai_context, document_id=doc["document_id"])

            if "text" in block_types and ai_result.get("executive_summary"):
                b = text_block(ai_result["executive_summary"], style="executive_summary")
                b["data_lineage"] = {"source": "ai", "model": "claude", "task": f"generic_{title[:20]}", "date": now}
                blocks.append(b)
            if "insight" in block_types:
                for finding in ai_result.get("key_findings", [])[:3]:
                    b = insight_block("Hallazgo", finding, importance="high")
                    b["data_lineage"] = {"source": "ai", "model": "claude", "task": "findings", "date": now}
                    blocks.append(b)

        sections.append(new_section(title, tpl_section.get("order", len(sections) + 1), blocks))

    doc["sections"] = sections
    doc["metadata"] = {
        "template_id": template_id, "template_name": template.get("name"),
        "master_id": bundle["master_id"] if (bundle and bundle.get("found")) else None,
        "cnae_code": cnae_code, "type": "custom_template",
        "financial_engine_used": True, "fact_locked": True, "schema": "modern",
    }
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc


def generate_template_preview(template: Dict, brand: Dict) -> Dict:
    """Generate a preview document with sample data. No DB, no AI, instant."""
    now = now_iso()

    doc = {
        "document_id": "preview",
        "title": f"Preview — {template.get('name', 'Plantilla')}",
        "template_id": template.get("template_id"),
        "brand_id": brand.get("brand_id", "brand_bud"),
        "version": 0,
        "status": "preview",
        "sections": [],
        "metadata": {"preview": True},
        "created_at": now,
    }

    SAMPLE = {
        "company": "Empresa Ejemplo SL",
        "revenue": "1.250.000",
        "ebitda_margin": "14.2%",
        "employees": "42",
        "cagr": "+8.3%",
        "yoy": "+5.1%",
        "rev_per_emp": "29.762",
        "sector": "Tecnologia y Software",
    }

    for tpl_section in template.get("sections", []):
        blocks = []
        block_types = tpl_section.get("block_types", [])

        if "cover" in block_types:
            blocks.append(cover_block(title=SAMPLE["company"], subtitle=f"Preview — {template.get('name', '')}"))

        if "kpi" in block_types:
            blocks.append(kpi_block("Facturacion", SAMPLE["revenue"], "EUR"))
            blocks.append(kpi_block("Margen EBITDA", SAMPLE["ebitda_margin"], ""))
            blocks.append(kpi_block("Empleados", SAMPLE["employees"], ""))
            blocks.append(kpi_block("CAGR", SAMPLE["cagr"], ""))

        if "table" in block_types:
            blocks.append(table_block("Datos ejemplo", ["Campo", "Valor"], [
                ["Empresa", SAMPLE["company"]], ["Sector", SAMPLE["sector"]],
                ["Revenue", SAMPLE["revenue"]], ["Empleados", SAMPLE["employees"]],
            ]))

        if "text" in block_types:
            blocks.append(text_block(
                "Esta seccion contendra texto narrativo generado automaticamente por IA. "
                "El contenido se basara en los datos reales de la empresa y del sector.",
                style="executive_summary" if "resumen" in tpl_section.get("title", "").lower() else "body",
            ))

        if "insight" in block_types:
            blocks.append(insight_block("Hallazgo ejemplo", "Este bloque contendra insights generados por IA basados en datos reales.", importance="high"))
            blocks.append(insight_block("Recomendacion ejemplo", "Las recomendaciones se generaran automaticamente.", importance="medium"))

        if "chart" in block_types:
            blocks.append(text_block("[Grafico: se generara con datos reales]", style="body"))

        doc["sections"].append(new_section(
            tpl_section.get("title", "Seccion"),
            tpl_section.get("order", len(doc["sections"]) + 1),
            blocks,
        ))

    return doc


async def compose_one_pager(company_id: str = None, cif: str = None,
                            brand_id: str = "brand_bud", user: str = None) -> Dict:
    """Investment One Pager — A4 vertical, CIEGO (perfil anónimo). Una sola página pensada para
    leerse en <3 min y despertar interés: la TESIS DE INVERSIÓN es el bloque protagonista
    ("¿por qué merece la pena?"), seguida de KPIs clave, aspectos destacados y el Deal Snapshot
    estándar de bud advisors. Sin identidad (nombre/CIF/web/municipio) y SIN valoración (esa vive
    en el Infomemo / Informe de Valoración). Render dedicado A4 (HTML→Chromium) para HTML/PDF/PPTX."""
    from services.cnae_catalog import CNAE_DIVISIONS, resolve_cnae_label

    bundle = await DA.company_intelligence(company_id or cif)
    if not bundle.get("found"):
        return {"error": "Company not found"}

    ident = bundle["identity"]
    kpis = bundle.get("kpis", {}) or {}
    cnae = ident.get("cnae_code", "")
    cnae_label = resolve_cnae_label(cnae) or (ident.get("cnae_description") or "su sector")
    provincia = ident.get("provincia")
    rev = kpis.get("revenue")
    emp = (bundle.get("statements") or {}).get("employees")
    band = _size_band(rev, emp)

    # Perfil anónimo (misma lógica ciega que el teaser).
    perfil = f"{band.capitalize()} del sector {cnae_label} (CNAE {cnae})."
    if provincia:
        perfil += f" Con sede en la provincia de {provincia}."
    perfil += " Se estudia la entrada de un socio mediante la adquisición total o parcial del capital."

    # TESIS DE INVERSIÓN (protagonista). IA fact-locked con contexto CIEGO (sin nombre); si falla,
    # fallback determinista igualmente ciego. La IA solo redacta, no introduce cifras nuevas.
    blind_ctx = {
        "perfil": perfil, "sector": cnae_label, "cnae": cnae, "provincia": provincia,
        "banda_tamano": band,
        "kpis": {k: kpis.get(k) for k in ("revenue", "revenue_cagr", "revenue_growth_yoy",
                                           "ebitda", "ebitda_margin", "revenue_per_employee", "solvency")
                 if kpis.get(k) is not None},
        "instruccion_ciega": ("Documento CIEGO: NO menciones el nombre, CIF, web ni municipio de la "
                              "empresa. Refiérete siempre a 'la compañía'. Redacta una tesis de "
                              "inversión de 3-4 frases que responda '¿por qué merece la pena esta "
                              "oportunidad?', apoyándote solo en las cifras dadas. NO incluyas valoración."),
    }
    thesis = _investment_thesis_text("La compañía", bundle)
    try:
        ai = await generate_summary(blind_ctx, doc_type="company_profile", document_id=None) or {}
        cand = (ai.get("executive_summary") or "").strip()
        low = cand.lower()
        name_l = (ident.get("name") or "").lower()
        # Solo si la IA respetó la regla ciega (no filtró el nombre) y devolvió algo sustancial.
        if cand and len(cand) > 60 and (not name_l or name_l not in low) and "valorac" not in low:
            thesis = cand
    except Exception as e:
        logging.getLogger(__name__).warning("One pager thesis AI failed: %s", e)

    # KPIs (de _hero_kpi_blocks: title/value/unit/commentary) → strip compacto.
    kpi_items = []
    for b in _hero_kpi_blocks(bundle):
        d = b.get("data", {})
        kpi_items.append({"label": d.get("title"), "value": d.get("value"),
                          "unit": d.get("unit"), "note": d.get("commentary")})
    # CAGR como 4º KPI si hay hueco y existe.
    if kpis.get("revenue_cagr") is not None and len(kpi_items) < 4:
        kpi_items.append({"label": "CAGR de ingresos", "value": _pct(kpis["revenue_cagr"], 1),
                          "unit": "", "note": "crecimiento estructural"})

    # Aspectos destacados (de _positive_signal_cards: title/summary).
    highlights = []
    for b in _positive_signal_cards(bundle)[:4]:
        d = b.get("data", {})
        highlights.append({"title": d.get("title"), "summary": d.get("summary")})

    # Deal Snapshot estándar (items).
    ds = _deal_snapshot(bundle).get("data", {}).get("items", [])

    doc = new_document(title="Investment One Pager — Proyecto Confidencial",
                       template_id="tpl_one_pager", brand_id=brand_id, created_by=user)
    doc["orientation"] = "portrait"
    doc["onepager"] = {
        "header": "CONFIDENTIAL · Investment Opportunity · Executive One Pager",
        "title": "Oportunidad de Inversión",
        "subtitle": f"Proyecto Confidencial · {cnae_label}",
        "profile": perfil,
        "thesis_title": "¿Por qué merece la pena esta oportunidad?",
        "thesis": thesis,
        "kpis": kpi_items[:4],
        "highlights": highlights,
        "deal_snapshot": ds,
        "advisor": _advisor_label(brand_id),
        "date": _month_year_es(),
        "cta": "Firme el NDA para acceder al Information Memorandum completo",
        "confidentiality": ("Documento confidencial y ciego. Perfil anónimo elaborado por el asesor a "
                            "efectos de primer contacto; no constituye oferta ni recomendación de inversión."),
    }
    # Secciones mínimas para que el documento se liste/edite con gracia (el render usa 'onepager').
    doc["sections"] = [new_section("Investment One Pager", 1, [
        text_block(thesis, "executive_summary"),
    ])]
    doc["metadata"] = {
        "master_id": bundle["master_id"], "cif": bundle["cif_normalized"], "type": "one_pager",
        "financial_engine_used": True, "fact_locked": True, "schema": "modern", "blind": True,
    }
    doc["status"] = "generated"
    doc["updated_at"] = now_iso()
    await db.docstudio_documents.insert_one(doc)
    return doc
