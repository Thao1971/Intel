"""Vista enriquecida de oportunidades (Beta): nivel, serie, comparativa y prosa CF.

Convierte una señal cruda del motor (`signals`) en la tarjeta que ve el usuario: qué nivel de
madurez tiene, qué dicen sus tres últimos ejercicios, cómo se compara con empresas similares y
qué cautelas conviene tener presentes. Todo es DETERMINISTA y sale de datos reales (serie
financiera, baselines sectoriales, señales activas): ninguna frase inventa un hecho.

Funciones puras, sin acceso a base de datos: la orquestación (consultas por lotes) vive en
`routes/signal_intelligence.py::_opportunities_enriched`. Redacción según
`CANON_NARRATIVA_CF_FICHA.md` (prosa, sin enums ni jerga de máquina, cifra dentro de la frase).
"""

from contextvars import ContextVar
from typing import Dict, List, Optional

from services import officer_utils as OU
from services import opportunity_criteria as CR

# Niveles de madurez (de más a menos sólido). "special" = tesis de situaciones especiales (perfil de
# riesgo, para compradores oportunistas); "verify" queda aparte: dato no fiable.
# Idioma de la redacción ("es" por defecto). Los campos conservan su nombre (`*_es`) para no romper
# el contrato; con lang="en" su contenido sale en inglés. Lo fija la ruta con `use_lang()`.
_LANG: ContextVar[str] = ContextVar("opportunity_view_lang", default="es")


def use_lang(lang: Optional[str]):
    """Fija el idioma de la redacción en el contexto actual; devuelve el token para `reset_lang`."""
    return _LANG.set("en" if (lang or "").lower().startswith("en") else "es")


def reset_lang(token) -> None:
    _LANG.reset(token)


def _en() -> bool:
    return _LANG.get() == "en"


def L(es: str, en: str) -> str:
    return en if _en() else es


LEVEL_ORDER = {"opportunity": 0, "candidate": 1, "indicio": 2, "special": 3, "verify": 4}
LEVEL_LABEL_ES = {
    "opportunity": "Oportunidad potencial",
    "candidate": "Candidata",
    "indicio": "Indicio",
    "special": "Situación especial",
    "verify": "Datos a verificar",
}
LEVEL_LABEL_EN = {
    "opportunity": "Potential opportunity",
    "candidate": "Candidate",
    "indicio": "Early signal",
    "special": "Special situation",
    "verify": "Data to verify",
}

SERIES_YEARS = 3               # ejercicios que se muestran en la mini-serie
SMALL_BASE_EUR = 100_000       # por debajo de esto, un salto grande puede ser ruido de base pequeña
SMALL_BASE_MIN_MULTIPLE = 3    # ... y solo se avisa si la serie se multiplica al menos por esto
FRESHNESS_MAX_GAP_YEARS = 1    # para ser Oportunidad, el último ejercicio no puede ser anterior a (esperado - 1)
CONSOLIDATOR_PLATFORM_MIN = 5  # participadas a partir de las cuales se habla de 'plataforma de consolidación'
MIN_RELIABLE_SAMPLE = 20       # comparativa con menos comparables se marca como orientativa

# Palabras para confianza / urgencia / persistencia (0-1). Umbrales provisionales, pendientes de validar.
WORD_BANDS = ((0.9, "Muy alta"), (0.75, "Alta"), (0.5, "Media"), (0.0, "Baja"))
_WORD_EN = {"Muy alta": "Very high", "Alta": "High", "Media": "Medium", "Baja": "Low"}

# Señales que, si están activas en la empresa, impiden llamarla "Oportunidad" (además de severity risk/critical).
BLOCKING_SIGNAL_TYPES = ("risk.balance_inconsistency", "risk.revenue_anomaly")

# Señales cuya lectura depende de la serie de ingresos: solo a ellas se les aplican la comprobación de
# dato erróneo, las cautelas de la serie y la comparativa de sector. Una sociedad holding puede tener
# ingresos nulos con toda normalidad; marcarla "a verificar" por eso sería un falso positivo.
REVENUE_DEPENDENT = frozenset({
    "growth.revenue_surge", "growth.sustained", "opportunity.expansion_opportunity",
    "opportunity.hidden_gem", "opportunity.consolidation_candidate",
})
# Perspectiva de la tarjeta: "acquirer" = la empresa es potencial COMPRADORA/plataforma; "target" = objetivo.
ACQUIRER_TYPES = frozenset({"ownership.consolidator", "opportunity.consolidation_candidate"})


def word_es(value: Optional[float]) -> Optional[str]:
    if not isinstance(value, (int, float)):
        return None
    for floor, word in WORD_BANDS:
        if value >= floor:
            return _WORD_EN[word] if _en() else word
    return L("Baja", "Low")


# ── formato en prosa española ──

def pct_es(x: Optional[float], signed: bool = False) -> Optional[str]:
    """0.448 -> '44,8%'. Coma decimal, sin espacio; negativos con '−' (U+2212), como en el sistema de
    diseño (`−3,1%`). Con signed=True antepone '+' a los positivos."""
    if not isinstance(x, (int, float)):
        return None
    s = f"{abs(x) * 100:.1f}"
    if not _en():
        s = s.replace(".", ",")
    if s in ("0,0", "0.0"):             # un valor que redondea a cero no lleva signo (nada de "−0,0%")
        return s + "%"
    if x < 0:
        s = "−" + s
    elif signed:
        s = "+" + s
    return s + "%"


def eur_es(v: Optional[float]) -> Optional[str]:
    """Magnitudes según el sistema de diseño: < 1.000.000 € -> 'XXX k€' (515 k€); >= 1 M€ -> 'X.XXX M€'
    (41.200 M€), con un decimal por debajo de 10 M€ (2,6 M€). Punto de miles, coma decimal, negativos '−97 k€'."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    sign = "−" if v < 0 else ""
    a = abs(v)
    if _en():                           # inglés: €515k, €2.6M, €41,200M
        if a >= 1_000_000:
            m = a / 1e6
            body = f"{m:,.0f}" if m >= 10 else f"{m:.1f}"
            body = body[:-2] if body.endswith(".0") else body
            return f"{sign}€{body}M"
        if a >= 1_000:
            return f"{sign}€{round(a / 1e3)}k"
        return f"{sign}€{round(a)}"
    if a >= 1_000_000:
        m = a / 1e6
        if m >= 10:
            body = f"{m:,.0f}".replace(",", ".")
        else:
            body = f"{m:.1f}".replace(".", ",")
            body = body[:-2] if body.endswith(",0") else body
        return f"{sign}{body} M€"
    if a >= 1_000:
        return f"{sign}{round(a / 1e3)} k€"
    return f"{sign}{round(a)} €"


def multiple_es(x: float) -> str:
    s = f"{x:.1f}"
    return s if _en() else s.replace(".", ",")


# ── serie financiera ──

def revenue_series(history: Optional[List[Dict]], years: int = SERIES_YEARS) -> List[Dict]:
    """Últimos `years` ejercicios con ingresos informados, de más antiguo a más reciente."""
    pts = [{"year": h.get("year"), "revenue": h.get("revenue")}
           for h in (history or [])
           if h.get("year") is not None and h.get("revenue") is not None]
    pts.sort(key=lambda p: p["year"])
    return pts[-years:]


def data_issue(series: List[Dict]) -> Optional[Dict]:
    """Ingresos <= 0 en algún ejercicio de la serie: dato no fiable, las tasas no significan nada
    (misma regla que el motor: ver financial/engine.py::_revenue_growth / _revenue_cagr)."""
    bad = [p for p in series if p["revenue"] <= 0]
    if not bad:
        return None
    negative = any(p["revenue"] < 0 for p in bad)
    years = ", ".join(str(p["year"]) for p in bad)
    what = L("constan como negativos" if negative else "constan como nulos",
             "are negative" if negative else "are zero")
    return {"code": "non_positive_revenue", "years": [p["year"] for p in bad],
            "text_es": L(f"Los ingresos de {years} {what}: las tasas de crecimiento calculadas no son fiables.",
                         f"Revenue for {years} {what}: the growth rates calculated are not reliable.")}


def yoy(series: List[Dict], back: int = 0) -> Optional[float]:
    """Crecimiento interanual del ejercicio más reciente (back=0) o de uno anterior (back=1...).
    None si falta dato o si alguno de los dos ingresos es <= 0."""
    if len(series) < 2 + back:
        return None
    a, b = series[-2 - back], series[-1 - back]
    if b["year"] - a["year"] != 1:      # con un hueco entre ejercicios no es una tasa interanual
        return None
    new, old = b["revenue"], a["revenue"]
    if new < 0 or old <= 0:
        return None
    return round((new - old) / old, 4)


# ── nivel ──

def level_for(is_composite: bool, issue: Optional[Dict], comparison: Optional[Dict],
              has_blocking_risk: bool, signal_type: Optional[str] = None,
              meets_size_floor: bool = True, fresh: bool = True) -> str:
    """verify: dato no fiable. special: situación especial (potential_distress). opportunity:
    composición + comparables + sin alerta activa + tamaño >= suelo de ingresos (opportunity_criteria).
    candidate: composición. indicio: señal aislada."""
    if issue:
        return "verify"
    if signal_type == "opportunity.potential_distress":
        return "special"
    comparable = (bool(comparison) and comparison.get("scope", "sector_size") == "sector_size"
                  and comparison.get("position") != "below_p50")   # crecer por debajo de la mediana no confirma nada
    if is_composite and comparable and not has_blocking_risk and meets_size_floor and fresh:
        return "opportunity"
    return "candidate" if is_composite else "indicio"


# ── comparativa con empresas similares ──

def compare_to_baseline(growth: Optional[float], baseline: Optional[Dict],
                        scope: str = "sector_size") -> Optional[Dict]:
    """Crecimiento interanual frente a p50/p75 de empresas similares.
    scope='sector_size': comparables de su sector Y banda de tamaño (sector_size_baselines): es la única
    comparativa que cuenta para el nivel Oportunidad. scope='sector': respaldo con todo el sector, sin
    distinguir tamaño; se muestra, pero es más débil y no califica."""
    if growth is None or not baseline:
        return None
    p50, p75, n = baseline.get("p50"), baseline.get("p75"), baseline.get("sample_size")
    if p50 is None or p75 is None:
        return None
    if _en():
        who = "similar companies in its sector and size" if scope == "sector_size" else "companies in its sector"
    else:
        who = "empresas similares de su sector y tamaño" if scope == "sector_size" else "empresas de su sector"
    if growth > p75:
        position = "above_p75"
        text = L(f"Crece por encima del cuarto superior de {who} (más del {pct_es(p75)}) y de su mediana ({pct_es(p50)}).",
                 f"Grows above the top quarter of {who} (more than {pct_es(p75)}) and above their median ({pct_es(p50)}).")
    elif growth > p50:
        position = "above_p50"
        text = L(f"Crece por encima de la mediana de {who} ({pct_es(p50)}), "
                 f"sin llegar al cuarto superior ({pct_es(p75)}).",
                 f"Grows above the median of {who} ({pct_es(p50)}), "
                 f"without reaching the top quarter ({pct_es(p75)}).")
    else:
        position = "below_p50"
        text = L(f"Crece por debajo de la mediana de {who} ({pct_es(p50)}).",
                 f"Grows below the median of {who} ({pct_es(p50)}).")
    indicative = not (isinstance(n, int) and n >= MIN_RELIABLE_SAMPLE)
    if scope == "sector_size":
        note = (L(f"Comparativa orientativa: {n} empresas comparables.", f"Indicative comparison: {n} comparable companies.") if indicative
                else L(f"Comparativa sobre {n} empresas comparables.", f"Comparison based on {n} comparable companies."))
    else:
        note = L(f"Comparativa con todo el sector, sin distinguir tamaño: {n} empresas.",
                 f"Comparison with the whole sector, regardless of size: {n} companies.")
    return {"metric": "revenue_growth_yoy", "value": growth, "p50": p50, "p75": p75, "scope": scope,
            "sample_size": n, "position": position, "indicative": indicative or scope == "sector",
            "text_es": text, "sample_note_es": note}


# ── cautelas derivadas de la propia serie ──

def caveats(series: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    if len(series) < 2:
        return out
    cur = yoy(series)
    prev = yoy(series, back=1)
    last_year = series[-1]["year"]

    if any(b["year"] - a["year"] != 1 for a, b in zip(series, series[1:])):
        out.append({"code": "series_gap",
                    "text_es": L("Faltan ejercicios intermedios en la serie: las variaciones no son interanuales.",
                                 "Intermediate years are missing from the series: the changes are not year on year.")})
    if cur is not None and cur <= -0.10:
        out.append({"code": "latest_decline",
                    "text_es": L(f"Los ingresos del último ejercicio caen un {pct_es(abs(cur))}: contrasta con la lectura de crecimiento.",
                                 f"Revenue in the latest year falls {pct_es(abs(cur))}: this contrasts with the growth reading.")})
    elif cur is not None and cur > 0 and prev is not None and prev < -0.10:
        span = series[-1]["year"] - series[-3]["year"] if len(series) >= 3 else None
        net = (series[-1]["revenue"] / series[-3]["revenue"] - 1) if len(series) >= 3 and series[-3]["revenue"] > 0 else None
        text = L(f"Llega tras un ejercicio a la baja ({pct_es(prev)})", f"Comes after a year of decline ({pct_es(prev)})")
        if net is not None and span:
            text += L(f"; en {span} años el avance neto es de {pct_es(net, signed=True)}",
                      f"; over {span} years the net gain is {pct_es(net, signed=True)}")
        out.append({"code": "rebound", "text_es": text + "."})
    elif cur is not None and prev is not None and prev >= 0.5 and cur <= prev / 2 and cur > -0.10:
        out.append({"code": "decelerating",
                    "text_es": L(f"Casi todo el salto se concentró en {series[-2]['year']}: "
                                 f"en {last_year} el ritmo baja a {pct_es(cur, signed=True)}.",
                                 f"Almost all of the jump came in {series[-2]['year']}: "
                                 f"in {last_year} the pace slows to {pct_es(cur, signed=True)}.")})

    revs = [p["revenue"] for p in series if p["revenue"] > 0]
    if revs and min(revs) < SMALL_BASE_EUR and max(revs) / min(revs) >= SMALL_BASE_MIN_MULTIPLE:
        out.append({"code": "small_base",
                    "text_es": L(f"Parte de una base muy pequeña ({eur_es(min(revs))}): "
                                 "conviene contrastarla antes de darle peso.",
                                 f"Starts from a very small base ({eur_es(min(revs))}): "
                                 "it should be cross-checked before giving it weight.")})
    return out


# ── titular ──

def _years_es(v: float) -> str:
    s = f"{v:.1f}"
    return s if _en() else s.replace(".", ",")


def _sentence_case(text: str) -> str:
    t = (text or "").strip().lower()
    return t[:1].upper() + t[1:]


def headline(signal_type: str, evidence: Optional[Dict], series: List[Dict],
             caveat_list: List[Dict], extra: Optional[Dict] = None) -> Optional[str]:
    """Titular en prosa CF por tipo de señal. Solo afirma lo que la evidencia sostiene: las compuestas
    se describen por los tipos de señal que las componen (evidence.component_types), sin inventar cifras.
    None solo para tipos sin plantilla (el front usa entonces un texto neutro)."""
    ev = evidence or {}
    extra = extra or {}
    comps = set(ev.get("component_types") or [])
    codes = {c["code"] for c in caveat_list}
    last_year = series[-1]["year"] if series else None

    # ── crecimiento (necesitan la serie) ──
    if signal_type == "growth.revenue_surge" and series and isinstance(ev.get("value"), (int, float)):
        base = L(f"Los ingresos suben un {pct_es(ev['value'])} en {last_year}",
                 f"Revenue rises {pct_es(ev['value'])} in {last_year}")
        prev = yoy(series, back=1)
        if "rebound" in codes and prev is not None:
            base += L(f", tras haber caído un {pct_es(abs(prev))} el año anterior",
                      f", after falling {pct_es(abs(prev))} the year before")
        return base + "."

    if signal_type == "growth.sustained" and len(series) >= 2 and isinstance(ev.get("value"), (int, float)):
        span = series[-1]["year"] - series[0]["year"]
        mult = series[-1]["revenue"] / series[0]["revenue"] if series[0]["revenue"] > 0 else None
        if span > 0 and mult and mult >= 2:
            text = L(f"Los ingresos se multiplican por {multiple_es(mult)} en {span} años "
                     f"({pct_es(ev['value'], signed=True)} anual compuesto)",
                     f"Revenue is multiplied by {multiple_es(mult)} in {span} years "
                     f"({pct_es(ev['value'], signed=True)} compound annual)")
            if "decelerating" in codes:
                text += L(", aunque el último año se moderó", ", although the last year slowed")
            return text + "."
        if span > 0:
            return L(f"Los ingresos crecen a un ritmo compuesto del {pct_es(ev['value'])} anual en {span} años.",
                     f"Revenue grows at a compound rate of {pct_es(ev['value'])} a year over {span} years.")

    if signal_type == "opportunity.expansion_opportunity":
        g = yoy(series)
        if g is not None:
            return L(f"Los ingresos suben un {pct_es(g)} en {last_year}, y ese avance coincide con "
                     "una productividad por encima de lo habitual.",
                     f"Revenue rises {pct_es(g)} in {last_year}, and that increase coincides with "
                     "above-usual productivity.")
        return L("Crecimiento de ingresos con productividad por encima de lo habitual.",
                 "Revenue growth with above-usual productivity.")

    # ── composiciones con lectura de calidad ──
    if signal_type == "opportunity.hidden_gem":
        # market.outperforms_peers = margen EBITDA en el cuarto superior frente a sus pares (no "rendimiento" en general).
        margin = extra.get("ebitda_margin")
        lead = (L(f"Combina un margen EBITDA del {pct_es(margin)}, en el cuarto superior de sus comparables,",
                  f"Combines an EBITDA margin of {pct_es(margin)}, in the top quarter of its comparables,")
                if isinstance(margin, (int, float)) and margin > 0
                else L("Combina un margen en el cuarto superior de sus comparables",
                       "Combines a margin in the top quarter of its comparables"))
        text = L(f"{lead} y un crecimiento sostenido", f"{lead} and sustained growth")
        if "market.fragmented_sector" in comps:
            text += L(", en un sector fragmentado", ", in a fragmented sector")
        return text + "."

    if signal_type == "opportunity.consolidation_candidate":
        text = L("Combina un crecimiento sostenido, márgenes sólidos y participaciones en otras sociedades: "
                 "perfil de actor consolidador",
                 "Combines sustained growth, solid margins and holdings in other companies: "
                 "the profile of a consolidating player")
        if "transaction.ma_event" in comps:
            text += L(", con al menos una operación de M&A registrada", ", with at least one recorded M&A transaction")
        return text + "."

    if signal_type == "opportunity.potential_distress":
        extras = []
        if "risk.sustained_decline" in comps:
            extras.append(L("ingresos a la baja durante varios ejercicios", "revenue declining over several years"))
        if "financial.low_liquidity" in comps:
            extras.append(L("liquidez ajustada", "tight liquidity"))
        if "corporate.group_change" in comps:
            extras.append(L("un cambio reciente en su grupo societario", "a recent change in its corporate group"))
        text = L("Cierra con pérdidas netas y un endeudamiento elevado", "Closes with net losses and high debt")
        if extras:
            text += L(", con ", ", with ") + L(" y ", " and ").join(extras)
        return text + L(": posible situación especial o de reestructuración.", ": possible special or restructuring situation.")

    if signal_type == "opportunity.operational_turnaround":
        margin = extra.get("ebitda_margin")
        lead = (L(f"Margen EBITDA del {pct_es(margin)}", f"EBITDA margin of {pct_es(margin)}")
                if isinstance(margin, (int, float)) else L("Márgenes débiles", "Weak margins"))
        text = L(f"{lead} y productividad por debajo de lo habitual, sin pérdidas netas ni patrimonio neto negativo",
                 f"{lead} and below-usual productivity, with no net losses or negative equity")
        if "market.underperforms_peers" in comps:
            text += L(", y por debajo de sus comparables", ", and below its comparables")
        return text + L(": margen de mejora operativa.", ": room for operational improvement.")

    if signal_type == "opportunity.group_subsidiary":
        text = L("Forma parte de un grupo societario", "Part of a corporate group")
        if "ownership.foreign_parent" in comps:
            text += L(" con matriz extranjera", " with a foreign parent")
        return text + L(": posible desinversión o reorganización.", ": possible divestment or reorganisation.")

    # ── señales que no dependen de la serie ──
    if signal_type == "ownership.consolidator" and isinstance(ev.get("value"), (int, float)):
        n = int(ev["value"])
        who = L("una sociedad" if n == 1 else f"{n} sociedades", "one company" if n == 1 else f"{n} companies")
        if n >= CONSOLIDATOR_PLATFORM_MIN:
            return L(f"Participa en {who}: perfil compatible con una plataforma de consolidación.",
                     f"Holds a stake in {who}: a profile compatible with a consolidation platform.")
        return L(f"Participa en {who}: posible matriz de un pequeño grupo de participadas.",
                 f"Holds a stake in {who}: possibly the parent of a small group of investees.")

    if signal_type == "opportunity.succession_signal" and isinstance(ev.get("value"), (int, float)):
        if _en():
            role = _sentence_case(ev.get("person_role") or "Director")
            since = (ev.get("appointment_date") or "")[-4:]
            text = f"{role} with {_years_es(ev['value'])} years in the post"
            if since.isdigit():
                text += f" (since {since})"
            text += ": possible generational handover."
            if (ev.get("succession_profile") or {}).get("family_business_probable"):
                text += " With traits of a family business."
            return text
        role = _sentence_case(OU.role_es(ev.get("person_role")) or "Administrador")
        since = (ev.get("appointment_date") or "")[-4:]
        text = f"{role} con {_years_es(ev['value'])} años en el cargo"
        if since.isdigit():
            text += f" (desde {since})"
        text += ": posible relevo generacional."
        if (ev.get("succession_profile") or {}).get("family_business_probable"):
            text += " Con rasgos de empresa familiar."
        return text
    return None


def signal_caveats(signal_type: str, evidence: Optional[Dict]) -> List[Dict]:
    """Cautelas propias del tipo de señal (las de la serie están en `caveats`). No se nombra a personas."""
    out: List[Dict] = []
    ev = evidence or {}
    if signal_type == "opportunity.succession_signal":
        succ = ((ev.get("succession_profile") or {}).get("successor_candidate")) or {}
        if succ:
            role = ((succ.get("role") or "") if _en() else (OU.role_es(succ.get("role")) or "")).strip().lower()
            who = f"({role}) " if role else ""
            out.append({"code": "successor_identified",
                        "text_es": L(f"Ya hay una persona {who}identificada como posible sucesora en la propia sociedad, "
                                     "lo que reduce la urgencia.",
                                     f"A person {who}has already been identified as a possible successor within the company, "
                                     "which reduces the urgency.")})
    if signal_type == "ownership.consolidator":
        out.append({"code": "holding_or_acquirer",
                    "text_es": L("Tener participadas no implica que compre activamente: puede tratarse de una "
                                 "tenedora patrimonial.",
                                 "Holding stakes does not mean it is actively buying: it may be an asset-holding company.")})
    return out


# ── lo que falta para ser oportunidad ──

_STATIC_MISSING = {
    "ownership.consolidator": [
        ("Confirmar si actúa como compradora o solo como tenedora de participaciones",
         "Confirm whether it acts as a buyer or just as a holder of stakes"),
        ("Revisar qué participadas siguen activas y su peso en el grupo",
         "Review which investees are still active and their weight in the group"),
    ],
    "opportunity.succession_signal": [
        ("Contrastar la antigüedad del cargo con el registro mercantil",
         "Cross-check the length of tenure with the commercial registry"),
        ("Confirmar la intención de los socios sobre un relevo",
         "Confirm the partners' intentions regarding a handover"),
    ],
    "opportunity.potential_distress": [
        ("Revisar la deuda financiera y su calendario de vencimientos",
         "Review the financial debt and its maturity schedule"),
    ],
    "opportunity.operational_turnaround": [
        ("Analizar la causa del bajo margen (precios, costes o estructura)",
         "Analyse the cause of the low margin (prices, costs or structure)"),
        ("Comparar su margen y productividad con empresas similares de su sector y tamaño",
         "Compare its margin and productivity with similar companies in its sector and size"),
    ],
    "opportunity.group_subsidiary": [
        ("Confirmar la estructura del grupo y el peso de la filial en él",
         "Confirm the group structure and the subsidiary's weight within it"),
        ("Identificar quién decide sobre la filial dentro del grupo",
         "Identify who decides on the subsidiary within the group"),
    ],
}


def missing_for_opportunity(level: str, comparison: Optional[Dict], series: List[Dict],
                            caveat_list: List[Dict], expected_year: int,
                            signal_type: Optional[str] = None,
                            size_gap: Optional[Dict] = None) -> List[str]:
    """Tareas concretas para pasar de Candidata/Indicio a Oportunidad. Vacío si ya lo es o hay dato dudoso."""
    if level in ("opportunity", "verify"):
        return []
    if signal_type in _STATIC_MISSING:
        return [L(es, en) for es, en in _STATIC_MISSING[signal_type]]
    out = []
    if size_gap:
        out.append(L(f"Su tamaño ({eur_es(size_gap['revenue']) or 'sin dato'}) queda por debajo del mínimo de "
                     f"{eur_es(size_gap['floor'])} de ingresos",
                     f"Its size ({eur_es(size_gap['revenue']) or 'no data'}) is below the minimum of "
                     f"{eur_es(size_gap['floor'])} in revenue"))
    if not comparison:
        out.append(L("Comparar el crecimiento con empresas similares de su sector y tamaño",
                     "Compare its growth with similar companies in its sector and size"))
    elif comparison.get("scope") == "sector":
        out.append(L("Contrastar el crecimiento con empresas de su mismo tamaño (solo hay comparativa con todo el sector)",
                     "Cross-check its growth with companies of its own size (there is only a comparison with the whole sector)"))
    if any(c["code"] == "small_base" for c in caveat_list):
        out.append(L("Confirmar que la cifra no viene de una base muy pequeña",
                     "Confirm that the figure does not come from a very small base"))
    if series and series[-1]["year"] < expected_year - FRESHNESS_MAX_GAP_YEARS:
        out.append(L(f"Los últimos ingresos disponibles son de {series[-1]['year']}: hace falta un ejercicio más reciente",
                     f"The latest revenue available is from {series[-1]['year']}: a more recent year is needed"))
    elif series and series[-1]["year"] < expected_year:
        out.append(L(f"Confirmar el ejercicio {series[-1]['year'] + 1}, todavía no disponible",
                     f"Confirm year {series[-1]['year'] + 1}, not yet available"))
    return out


def thesis_chips(signal_types: List[str]) -> List[Dict]:
    """Tesis derivadas SOLO de señales activas de la empresa (cada chip cita su origen en `basis`).
    Subconjunto de services/company_summary.py::opportunity_chips; 'Entrada de socio' exige el grafo
    de control y no se calcula aquí."""
    t = set(signal_types)
    chips = []

    def add(enum, label, basis):
        chips.append({"enum": enum, "label_es": label, "basis": basis})

    if "ownership.consolidator" in t:
        add("buy_and_build", "Buy & Build", "ownership.consolidator")
    if any(x.startswith("growth.") for x in t):
        add("growth", L("Crecimiento", "Growth"), "growth.*")
    if "opportunity.expansion_opportunity" in t:
        add("expansion", L("Expansión", "Expansion"), "opportunity.expansion_opportunity")
    if "opportunity.hidden_gem" in t:
        add("quality_growth", L("Calidad y crecimiento", "Quality and growth"), "opportunity.hidden_gem")
    if "opportunity.consolidation_candidate" in t:
        add("consolidator_platform", L("Plataforma consolidadora", "Consolidation platform"), "opportunity.consolidation_candidate")
    if "opportunity.succession_signal" in t:
        add("succession", L("Relevo generacional", "Generational handover"), "opportunity.succession_signal")
    if "opportunity.potential_distress" in t:
        add("special_situation", L("Situación especial", "Special situation"), "opportunity.potential_distress")
    if "opportunity.operational_turnaround" in t:
        add("turnaround", L("Mejora operativa", "Operational improvement"), "opportunity.operational_turnaround")
    if "opportunity.group_subsidiary" in t:
        add("carve_out", L("Filial de grupo", "Group subsidiary"), "opportunity.group_subsidiary")
    return chips


def size_label_es(band: Optional[str]) -> Optional[str]:
    if _en():
        return {"micro": "Micro", "small": "Small", "medium": "Medium", "large": "Large"}.get(band)
    return {"micro": "Micro", "small": "Pequeña", "medium": "Mediana", "large": "Grande"}.get(band)


def build_card(*, primary: Dict, all_types: List[str], master: Dict, band: Optional[str],
               baseline: Optional[Dict], sector_label: Optional[str], has_blocking_risk: bool,
               expected_year: int, min_revenue: Optional[float] = None,
               sector_baseline: Optional[Dict] = None) -> Dict:
    """Tarjeta completa de una empresa. `primary` = señal principal (compuesta si la hay)."""
    fin = master.get("financials") or {}
    latest = (fin.get("latest") or {})
    stype = primary.get("signal_type")
    revenue_dep = stype in REVENUE_DEPENDENT
    series = revenue_series(fin.get("history"))
    # Dato erróneo, comparativa y cautelas de la serie solo cuando la señal depende de los ingresos.
    issue = data_issue(series) if revenue_dep else None
    growth = yoy(series) if (revenue_dep and not issue) else None
    comparison = (compare_to_baseline(growth, baseline, "sector_size")
                  or compare_to_baseline(growth, sector_baseline, "sector"))
    floor = CR.configured_min_revenue()[0] if min_revenue is None else min_revenue
    meets = CR.meets_size_floor(latest.get("revenue"), floor)
    fresh = (not revenue_dep) or (bool(series) and series[-1]["year"] >= expected_year - FRESHNESS_MAX_GAP_YEARS)
    level = level_for(bool(primary.get("is_composite")), issue, comparison, has_blocking_risk, stype, meets, fresh)
    cav = (caveats(series) if (revenue_dep and not issue) else []) + signal_caveats(stype, primary.get("evidence"))
    dims = primary.get("dimensions") or {}
    loc = master.get("location") or {}
    return {
        "master_id": master.get("master_id"),
        "name": (master.get("identity") or {}).get("legal_name"),
        "level": level,
        "level_label_es": (LEVEL_LABEL_EN if _en() else LEVEL_LABEL_ES)[level],
        "perspective": "acquirer" if (set(all_types) & ACQUIRER_TYPES) else "target",
        "sector_label_es": sector_label,
        "cif": master.get("cif_normalized"),
        "cnae_section": (master.get("classification") or {}).get("cnae_section"),
        "provincia": loc.get("provincia"),
        "municipio": loc.get("municipio"),
        "size_band": band,
        "size_label_es": size_label_es(band),
        "latest_revenue": latest.get("revenue"),
        "latest_year": latest.get("year"),
        "series": series,
        "data_issue": issue,
        "headline_es": None if issue else headline(stype, primary.get("evidence"), series, cav,
                                                    {"ebitda_margin": latest.get("ebitda_margin")}),
        "caveats": cav,
        "comparison": comparison,
        "missing_es": missing_for_opportunity(
            level, comparison, series, cav, expected_year, stype,
            None if meets else {"revenue": latest.get("revenue"), "floor": floor}),
        "size_floor": {"min_revenue_eur": floor, "meets": meets},
        "chips": thesis_chips(all_types),
        "dimension_words": {k: word_es(dims.get(k)) for k in ("confidence", "urgency", "persistence")},
        "signal": {
            "signal_id": primary.get("signal_id"), "signal_type": stype,
            "is_composite": bool(primary.get("is_composite")), "dimensions": dims,
            "first_detected_at": primary.get("first_detected_at"), "last_seen_at": primary.get("last_seen_at"),
            "trend": primary.get("trend"), "occurrences": primary.get("occurrences"),
            "signal_types": sorted(set(all_types)),
        },
    }
