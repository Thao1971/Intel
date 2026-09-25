"""Valuation Report renderer — builds HTML from canonical CIS payload with charts."""

import logging
from html import escape
from typing import Dict, Optional
from datetime import datetime
from pathlib import Path
from documents.renderers import load_template, render_pdf, _is_dark_color

logger = logging.getLogger(__name__)


def build_valuation_report(payload: Dict, brand: Optional[Dict] = None) -> tuple:
    """Build valuation report HTML+CSS from canonical payload."""
    html_tpl, css_tpl = load_template("valuation_report")

    company = payload.get("company", {})
    kpis = payload.get("kpis", {})
    valuation = dict(payload.get("valuation", {}) or {})
    # Accept the Financial Intelligence Engine contract directly.
    val_range = valuation.get("range") or {}
    valuation.setdefault("ev_low", val_range.get("low"))
    valuation.setdefault("ev_mid", val_range.get("central") or valuation.get("enterprise_value"))
    valuation.setdefault("ev_high", val_range.get("high"))
    valuation.setdefault("equity_mid", valuation.get("equity_value"))
    valuation.setdefault("multiple_mid", valuation.get("multiple"))
    if valuation.get("multiple"):
        valuation.setdefault("multiple_low", round(valuation["multiple"] * .85, 2))
        valuation.setdefault("multiple_high", round(valuation["multiple"] * 1.15, 2))
    quality = payload.get("quality_breakdown", {})
    benchmark = payload.get("benchmark", {})
    fin_history = payload.get("financial_history", [])
    cost_structure = payload.get("cost_structure", {})
    methodology = payload.get("methodology", {})

    # Resolve brand
    from documents.design_system import generate_css_tokens, get_brand_or_default
    brand_id = brand.get("brand_id") if brand and isinstance(brand, dict) else None
    brand_data = get_brand_or_default(brand_id)
    accent = brand_data.get("tokens", {}).get("colors", {}).get("accent", "#6D5E00")

    # Generate charts
    from documents.renderers.charts import (
        chart_ev_scenarios, chart_ev_to_equity, chart_quality_breakdown,
        chart_financial_history, chart_cost_structure, chart_benchmark_percentiles
    )

    # ─── Cover meta ───
    cover_parts = []
    if company.get("cif"): cover_parts.append(f"CIF: {company['cif']}")
    if company.get("category"): cover_parts.append(company["category"])
    if company.get("subcategory"): cover_parts.append(company["subcategory"])
    if kpis.get("fiscal_year"): cover_parts.append(f"FY {kpis['fiscal_year']}")
    cover_meta = " | ".join(cover_parts) if cover_parts else ""

    # ─── Section 01: Executive Summary ───
    exec_block = '<div class="exec-kpi-strip">'
    exec_kpis = [
        ("Quality Score", f"{payload.get('quality_score', kpis.get('quality_score', 0)):.0f}", "/100"),
        ("Revenue", _fmt_money(kpis.get("revenue")), ""),
        ("EBITDA", _fmt_money(kpis.get("ebitda")), ""),
        ("EBITDA Margin", f"{kpis.get('ebitda_margin', 0):.1f}%" if kpis.get('ebitda_margin') else "—", ""),
        ("Employees", str(kpis.get("employees", "—")), ""),
        ("Rev/Employee", _fmt_money(kpis.get("revenue_per_employee")), ""),
        ("EV (Base)", _fmt_money(valuation.get("ev_mid")), ""),
        ("Buyer Type", (valuation.get("buyer_type") or "—").title(), ""),
    ]
    for label, value, suffix in exec_kpis:
        if value and value != "—" and value != "0":
            exec_block += f'<div class="exec-kpi"><div class="exec-kpi-value">{value}</div><div class="exec-kpi-label">{label}</div></div>'
    exec_block += '</div>'

    # Narrative
    narrative = payload.get("executive_narrative") or payload.get("generated_blocks", {}).get("executive_summary", {})
    if isinstance(narrative, dict):
        narrative = narrative.get("content", "")
    if not narrative:
        qs = payload.get('quality_score', kpis.get('quality_score', 0))
        rev = kpis.get('revenue', 0)
        ev = valuation.get('ev_mid', 0)
        narrative = f"{company.get('name', 'The company')} presents a quality score of {qs:.0f}/100. "
        if rev: narrative += f"With revenue of {_fmt_money(rev)} and "
        if kpis.get('ebitda'): narrative += f"EBITDA of {_fmt_money(kpis['ebitda'])}, "
        if ev: narrative += f"the estimated enterprise value in the base scenario is {_fmt_money(ev)}."
    exec_block += f'<div class="exec-narrative">{narrative}</div>'

    # ─── Section 02: Market Valuation ───
    val_block = ""
    ev_low = valuation.get("ev_low", 0)
    ev_mid = valuation.get("ev_mid", 0)
    ev_high = valuation.get("ev_high", 0)

    if ev_mid:
        # EV chart
        ev_chart = chart_ev_scenarios(ev_low, ev_mid, ev_high, accent=accent)
        if ev_chart:
            val_block += f'<div class="chart-container"><img src="data:image/png;base64,{ev_chart}" alt="EV Scenarios" /><p class="chart-caption">Enterprise Value — Scenario Analysis</p></div>'

        # Valuation table
        val_block += '<table class="val-table"><thead><tr><th>Metric</th><th>Conservative</th><th>Base Case</th><th>Optimistic</th></tr></thead><tbody>'
        val_block += f'<tr><td>Multiple</td><td class="number">{valuation.get("multiple_low", "—")}x</td><td class="number">{valuation.get("multiple_mid", "—")}x</td><td class="number">{valuation.get("multiple_high", "—")}x</td></tr>'
        val_block += f'<tr class="highlight"><td>Enterprise Value</td><td class="number">{_fmt_money(ev_low)}</td><td class="number">{_fmt_money(ev_mid)}</td><td class="number">{_fmt_money(ev_high)}</td></tr>'

        eq_low = valuation.get("equity_low")
        eq_mid = valuation.get("equity_mid")
        eq_high = valuation.get("equity_high")
        if eq_mid:
            val_block += f'<tr><td>Equity Value</td><td class="number">{_fmt_money(eq_low)}</td><td class="number">{_fmt_money(eq_mid)}</td><td class="number">{_fmt_money(eq_high)}</td></tr>'

        net_debt = valuation.get("net_debt")
        if net_debt:
            val_block += f'<tr><td>Net Debt</td><td class="number" colspan="3">{_fmt_money(net_debt)}</td></tr>'
        val_block += '</tbody></table>'

        val_block += f'<div class="body-text"><p><strong>Buyer type:</strong> {(valuation.get("buyer_type") or "Not specified").title()}</p>'
        ebitda_used = valuation.get("ebitda_used") or kpis.get("ebitda")
        if ebitda_used:
            val_block += f'<p><strong>EBITDA used:</strong> {_fmt_money(ebitda_used)}</p>'
        val_block += '</div>'

        trace = _valuation_trace_block(valuation)
        if trace:
            val_block += trace

        # EV to Equity bridge
        if net_debt and eq_mid:
            bridge_chart = chart_ev_to_equity(ev_mid, abs(net_debt), eq_mid, accent=accent)
            if bridge_chart:
                val_block += f'<div class="chart-container"><img src="data:image/png;base64,{bridge_chart}" alt="EV to Equity Bridge" /><p class="chart-caption">Enterprise Value to Equity Bridge</p></div>'
    else:
        val_block = '<p class="no-data-msg">Valuation data not available for this company.</p>'

    # ─── Section 03: Quality & Positioning ───
    quality_block = ""
    qs = payload.get('quality_score', quality.get('total', 0))
    if qs:
        quality_block += f'<div class="quality-badge">{qs:.0f}</div>'
        quality_block += f'<p class="body-text">Quality Score: {qs:.0f} / 100</p>'

    breakdown = {}
    for k, v in quality.items():
        if k != 'total' and isinstance(v, (int, float)) and v > 0:
            breakdown[k] = v

    if breakdown:
        qb_chart = chart_quality_breakdown(breakdown, accent=accent)
        if qb_chart:
            quality_block += f'<div class="chart-container"><img src="data:image/png;base64,{qb_chart}" alt="Quality Breakdown" /><p class="chart-caption">Quality Score Breakdown</p></div>'

    # Percentiles
    percentiles = {}
    for k in ['margin_percentile', 'revenue_employee_percentile', 'balance_health_percentile']:
        v = quality.get(k) or benchmark.get(k)
        if v: percentiles[k] = v

    if percentiles:
        perc_chart = chart_benchmark_percentiles(percentiles, accent=accent)
        if perc_chart:
            quality_block += f'<div class="chart-container"><img src="data:image/png;base64,{perc_chart}" alt="Percentile Positioning" /><p class="chart-caption">Percentile Positioning vs Category</p></div>'

    if not quality_block:
        quality_block = '<p class="no-data-msg">Quality assessment data not available.</p>'

    # ─── Section 04: Benchmark ───
    benchmark_section = ""
    if benchmark and (benchmark.get("suggested_multiple") or benchmark.get("comparables_count")):
        benchmark_section = '<div class="section-sep"><div class="section-sep-num">Section 04</div><div class="section-sep-title">Benchmark vs Category</div></div>'
        benchmark_section += '<div class="content-page"><div class="page-header"><span class="page-header-title">Benchmark</span>'
        benchmark_section += f'<img class="logo-img page-header-logo-img" src="{{{{logo_url}}}}" alt="" /><span class="logo-text page-header-logo">{{{{brand_logo_text}}}}</span></div>'

        benchmark_section += '<div class="subsection-heading">Category Benchmark</div>'
        bench_items = []
        if benchmark.get("suggested_multiple"):
            bench_items.append(f'<p><strong>Suggested multiple:</strong> {benchmark["suggested_multiple"]:.1f}x</p>')
        if benchmark.get("category_range_low") and benchmark.get("category_range_high"):
            bench_items.append(f'<p><strong>Category range:</strong> {benchmark["category_range_low"]:.1f}x — {benchmark["category_range_high"]:.1f}x</p>')
        if benchmark.get("comparables_count"):
            bench_items.append(f'<p><strong>Comparables used:</strong> {benchmark["comparables_count"]}</p>')
        benchmark_section += '<div class="body-text">' + ''.join(bench_items) + '</div>'
        benchmark_section += '</div>'
    # else: omit section entirely

    # ─── Section 05: Financial History ───
    fin_section = ""
    if fin_history and len(fin_history) >= 2:
        fin_section = '<div class="section-sep"><div class="section-sep-num">Section 05</div><div class="section-sep-title">Financial Evolution</div></div>'
        fin_section += '<div class="content-page"><div class="page-header"><span class="page-header-title">Financial Evolution</span>'
        fin_section += f'<img class="logo-img page-header-logo-img" src="{{{{logo_url}}}}" alt="" /><span class="logo-text page-header-logo">{{{{brand_logo_text}}}}</span></div>'

        fin_chart = chart_financial_history(fin_history, accent=accent)
        if fin_chart:
            fin_section += f'<div class="chart-container"><img src="data:image/png;base64,{fin_chart}" alt="Financial Evolution" /><p class="chart-caption">Revenue & EBITDA Evolution</p></div>'

        # Table
        fin_section += '<table class="val-table"><thead><tr><th>Year</th><th>Revenue</th><th>EBITDA</th><th>Margin</th><th>Employees</th></tr></thead><tbody>'
        for h in fin_history:
            margin = f"{h.get('ebitda_margin', 0):.1f}%" if h.get('ebitda_margin') else "—"
            fin_section += f'<tr><td>{h.get("year", "—")}</td><td class="number">{_fmt_money(h.get("revenue"))}</td><td class="number">{_fmt_money(h.get("ebitda"))}</td><td class="number">{margin}</td><td class="number">{h.get("employees", "—")}</td></tr>'
        fin_section += '</tbody></table>'
        fin_section += '</div>'

    # ─── Section 06: Cost Structure ───
    cost_section = ""
    if cost_structure and any(v for v in cost_structure.values() if v):
        cost_section = '<div class="section-sep"><div class="section-sep-num">Section 06</div><div class="section-sep-title">Cost Structure</div></div>'
        cost_section += '<div class="content-page"><div class="page-header"><span class="page-header-title">Cost Structure</span>'
        cost_section += f'<img class="logo-img page-header-logo-img" src="{{{{logo_url}}}}" alt="" /><span class="logo-text page-header-logo">{{{{brand_logo_text}}}}</span></div>'

        cost_chart = chart_cost_structure(cost_structure, accent=accent)
        if cost_chart:
            cost_section += f'<div class="chart-container"><img src="data:image/png;base64,{cost_chart}" alt="Cost Structure" /><p class="chart-caption">Operational Cost Breakdown</p></div>'

        cost_section += '<table class="val-table"><thead><tr><th>Item</th><th>Amount</th></tr></thead><tbody>'
        for k, v in cost_structure.items():
            if v:
                label = k.replace('_', ' ').title()
                cost_section += f'<tr><td>{label}</td><td class="number">{_fmt_money(v)}</td></tr>'
        cost_section += '</tbody></table>'
        cost_section += '</div>'

    # ─── Section 07: Methodology ───
    meth_block = '<div class="subsection-heading">Valuation Approach</div>'
    meth_block += '<div class="body-text">'
    meth_block += f'<p><strong>Method:</strong> {methodology.get("method", "EV/EBITDA multiples")}</p>'
    if methodology.get("weights"):
        meth_block += '<p><strong>Quality score weights:</strong></p><ul>'
        for k, v in methodology["weights"].items():
            meth_block += f'<li>{k.replace("_", " ").title()}: {v*100:.0f}%</li>'
        meth_block += '</ul>'
    if methodology.get("scenarios"):
        meth_block += '<p><strong>Scenario logic:</strong></p><ul>'
        for k, v in methodology["scenarios"].items():
            meth_block += f'<li>{k.title()}: {v}</li>'
        meth_block += '</ul>'
    if methodology.get("limitations"):
        meth_block += '<p><strong>Limitations:</strong></p><ul>'
        for lim in methodology["limitations"]:
            meth_block += f'<li>{lim}</li>'
        meth_block += '</ul>'
    meth_block += '</div>'

    # ─── Assemble HTML ───
    html = html_tpl
    html = html.replace("{{company_name}}", company.get("name", "Company"))
    html = html.replace("{{cover_meta_line}}", cover_meta)
    html = html.replace("{{executive_summary_block}}", exec_block)
    html = html.replace("{{valuation_block}}", val_block)
    html = html.replace("{{quality_block}}", quality_block)
    html = html.replace("{{benchmark_section}}", benchmark_section)
    html = html.replace("{{financial_history_section}}", fin_section)
    html = html.replace("{{cost_structure_section}}", cost_section)
    html = html.replace("{{methodology_block}}", meth_block)

    # Brand injection
    logo_text = brand_data.get("logo_text", "CIS")
    brand_name = brand_data.get("name", "CIS")
    cover_bg = brand_data.get("tokens", {}).get("cover", {}).get("bg", "#6D5E00")
    is_dark = _is_dark_color(cover_bg)
    logo_url = brand_data.get("logo_light") if is_dark else brand_data.get("logo_dark")
    if not logo_url:
        logo_url = brand_data.get("logo_light") or brand_data.get("logo_dark") or ""

    html = html.replace("{{brand_logo_text}}", logo_text)
    html = html.replace("{{brand_name_upper}}", brand_name.upper())
    html = html.replace("{{logo_url}}", logo_url)
    html = html.replace("{{generated_at}}", datetime.utcnow().strftime("%B %Y"))
    html = html.replace("{{locale}}", payload.get("locale", "es"))

    # Clean remaining placeholders
    import re
    html = re.sub(r'\{\{[a-z_]+\}\}', '', html)

    # CSS: tokens + template + brand overrides
    tokens_css = generate_css_tokens(brand_id, brand_data)
    css = tokens_css + "\n\n" + css_tpl

    # CIS brand overrides
    if brand_id == "brand_cis":
        css += """
.cover { background: linear-gradient(135deg, #6D5E00 0%, #E1C422 100%) !important; }
.cover-line { background: rgba(255,255,255,0.35) !important; }
.section-sep { background: linear-gradient(135deg, #6D5E00 0%, #E1C422 100%) !important; }
.section-sep-num { color: rgba(255,255,255,0.7) !important; }
.section-sep-title { color: #FFFFFF !important; font-family: 'Playfair Display', Georgia, serif !important; }
.section-heading { font-family: 'Playfair Display', Georgia, serif !important; }
.cover-title { font-family: 'Playfair Display', Georgia, serif !important; }
.kpi-card, .exec-kpi { border: none !important; box-shadow: 0 12px 40px rgba(27,28,28,0.04); border-radius: 0.375rem; }
.closing-page { background: var(--bg-primary) !important; }
.closing-line { background: #E1C422 !important; }
.body-text { color: #44474A !important; }
.subsection-heading { color: #6D5E00 !important; }
.page-header, .section-header { border-bottom-color: rgba(195,198,203,0.10) !important; }
.val-table td { border-bottom-color: rgba(195,198,203,0.08) !important; }
"""

    return html, css


def _fmt_money(value, suffix="M") -> str:
    if value is None or value == 0:
        return "—"
    if isinstance(value, str):
        return value
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}{suffix}"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"


_FACTOR_LABELS = {
    "size": "Tamaño de la empresa",
    "recurring_revenue": "Ingresos recurrentes",
    "customer_concentration": "Concentración de clientes",
    "key_person_dependency": "Dependencia de persona clave",
    "audited_accounts": "Cuentas auditadas",
}
_FIELD_LABELS = {
    "recurring_revenue_pct": "porcentaje de ingresos recurrentes",
    "largest_customer_pct": "peso del principal cliente",
    "key_person_dependency": "dependencia de persona clave",
    "audited_accounts": "situación de auditoría de las cuentas",
}

def _fmt_basis(value) -> str:
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, (int, float)) and 0 <= value <= 1:
        return f"{value * 100:.1f}%".replace(".", ",")
    return escape(str(value if value is not None else "—"))

def _valuation_trace_block(valuation: Dict) -> str:
    """Financially readable audit trail for public-comparable adjustments."""
    adjustment=valuation.get("private_company_adjustment") or {}
    benchmark=valuation.get("multiple_benchmark") or {}
    if not adjustment:
        return ""
    metric=(benchmark.get("metric") or valuation.get("method") or "múltiplo").replace("_", "/").upper()
    public_multiple=adjustment.get("public_multiple")
    adjusted=adjustment.get("adjusted_multiple")
    source_level=benchmark.get("source_level") or benchmark.get("status") or "cotizadas comparables"
    providers=", ".join(benchmark.get("providers") or [])
    regions=", ".join(benchmark.get("regions") or [])
    industries=", ".join(benchmark.get("industries") or [])
    rows=[]
    for item in adjustment.get("components") or []:
        label=_FACTOR_LABELS.get(item.get("factor"),str(item.get("factor","")).replace("_"," ").title())
        pct=float(item.get("adjustment") or 0)*100
        rows.append(f'<tr><td>{escape(label)}</td><td>{_fmt_basis(item.get("basis"))}</td><td class="number">{pct:+.1f}%</td></tr>')
    block='<div class="subsection-heading">Trazabilidad del múltiplo</div>'
    block+='<div class="body-text"><p>La valoración parte de un múltiplo de cotizadas comparables y lo adapta a las características observadas de la empresa privada. Los datos no disponibles no generan ajustes.</p></div>'
    block+='<table class="val-table"><thead><tr><th>Concepto</th><th>Base observada</th><th>Ajuste</th></tr></thead><tbody>'
    block+=f'<tr><td>Múltiplo público de referencia ({escape(metric)})</td><td>{public_multiple:.2f}x</td><td class="number">—</td></tr>' if isinstance(public_multiple,(int,float)) else ''
    block+=''.join(rows)
    total=float(adjustment.get("total_adjustment") or 0)*100
    block+=f'<tr class="highlight"><td>Múltiplo ajustado de empresa privada</td><td>{adjusted:.2f}x</td><td class="number">{total:+.1f}%</td></tr>' if isinstance(adjusted,(int,float)) else ''
    block+='</tbody></table>'
    details=[]
    if source_level: details.append(f'nivel de fuente: {escape(str(source_level))}')
    if providers: details.append(f'proveedor: {escape(providers)}')
    if regions: details.append(f'región: {escape(regions)}')
    if benchmark.get("company_count"): details.append(f'muestra: {int(benchmark["company_count"])} compañías')
    if benchmark.get("as_of"): details.append(f'fecha de referencia: {escape(str(benchmark["as_of"]))}')
    if industries: details.append(f'sectores comparables: {escape(industries)}')
    if details: block+='<div class="body-text"><p><strong>Fuente del benchmark:</strong> '+ '; '.join(details)+'.</p></div>'
    missing=[_FIELD_LABELS.get(x,x) for x in adjustment.get("unavailable_evidence") or []]
    if missing:
        block+='<div class="body-text"><p><strong>Información no disponible:</strong> '+escape(', '.join(missing))+'. Estos factores se mantienen neutrales.</p></div>'
    block+='<div class="body-text"><p><strong>Liquidez:</strong> no se aplica descuento por falta de liquidez al Enterprise Value. Solo se estudiaría, de forma separada, para una participación minoritaria.</p></div>'
    return block
