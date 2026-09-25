"""Professional valuation PDF generated exclusively from Intel's valuation package."""
from __future__ import annotations

from io import BytesIO
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle, PolyLine

PAGE_W, PAGE_H = A4

# Arroba design system: Space Grotesk is the sole interface/report typeface; JetBrains Mono is reserved for numeric data.
_ASSET_DIR = Path(__file__).with_name("assets")
_FONT_DIR = _ASSET_DIR / "fonts"
_BRAND_DIR = _ASSET_DIR / "brand"
_LOGO_PRIMARY = _BRAND_DIR / "arroba-logo-primary.png"
_FONT_FILES = {
    "ArrobaBody": "DMSans-Regular.ttf", "ArrobaBodyMedium": "DMSans-Medium.ttf",
    "ArrobaBodySemiBold": "DMSans-SemiBold.ttf", "ArrobaBodyBold": "DMSans-Bold.ttf",
    "ArrobaDisplay": "SpaceGrotesk-Regular.ttf", "ArrobaDisplayMedium": "SpaceGrotesk-Medium.ttf",
    "ArrobaDisplaySemiBold": "SpaceGrotesk-SemiBold.ttf", "ArrobaDisplayBold": "SpaceGrotesk-Bold.ttf",
    "ArrobaMono": "JetBrainsMono-Regular.ttf", "ArrobaMonoMedium": "JetBrainsMono-Medium.ttf",
    "ArrobaMonoSemiBold": "JetBrainsMono-SemiBold.ttf", "ArrobaMonoBold": "JetBrainsMono-Bold.ttf",
}
for _font_name, _font_file in _FONT_FILES.items():
    if _font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_font_name, str(_FONT_DIR / _font_file)))

DISPLAY = "ArrobaDisplay"
DISPLAY_SEMIBOLD = "ArrobaDisplaySemiBold"
DISPLAY_BOLD = "ArrobaDisplayBold"
BODY = DISPLAY
BODY_MEDIUM = "ArrobaDisplayMedium"
BODY_SEMIBOLD = DISPLAY_SEMIBOLD
BODY_BOLD = DISPLAY_BOLD
MONO = "ArrobaMono"
MONO_SEMIBOLD = "ArrobaMonoSemiBold"
MONO_BOLD = "ArrobaMonoBold"

RED = colors.HexColor("#E8001D")
INK = colors.HexColor("#0C0C0E")
MUTED = colors.HexColor("#636360")
SUBTLE = colors.HexColor("#ADADAA")
PAPER = colors.HexColor("#FAFAF8")
SURFACE = colors.HexColor("#FFFFFF")
SOFT = colors.HexColor("#F4F4F0")
BORDER = colors.HexColor("#E8E8E2")
BORDER_STRONG = colors.HexColor("#D4D4CC")
BLUE = colors.HexColor("#2164E3")
GREEN = colors.HexColor("#1A8A4A")
AMBER = colors.HexColor("#D97708")


def _money(value: Any, currency: str = "EUR") -> str:
    if not isinstance(value, (int, float)):
        return "-"
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    if absolute >= 1_000_000:
        unit = "M€" if currency == "EUR" else f"M {currency}"
        return f"{sign}{absolute / 1_000_000:,.2f} {unit}".replace(",", "X").replace(".", ",").replace("X", ".")
    unit = "€" if currency == "EUR" else currency
    return f"{sign}{absolute:,.0f} {unit}".replace(",", ".")


def _pct(value: Any) -> str:
    return f"{value * 100:.1f}%".replace(".", ",") if isinstance(value, (int, float)) else "-"


def _text(value: Any, fallback: str = "-") -> str:
    return str(value) if value not in (None, "") else fallback


def _styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("Title", parent=styles["Title"], fontName=DISPLAY_BOLD, fontSize=27,
                                leading=31, textColor=colors.white, alignment=TA_LEFT, spaceAfter=8),
        "cover_meta": ParagraphStyle("CoverMeta", parent=styles["Normal"], fontName=BODY, fontSize=10, leading=15,
                                     textColor=colors.HexColor("#C9C9C5")),
        "h1": ParagraphStyle("H1", parent=styles["Heading1"], fontName=DISPLAY_BOLD, fontSize=19,
                             leading=23, textColor=INK, spaceBefore=3, spaceAfter=12),
        "h2": ParagraphStyle("H2", parent=styles["Heading2"], fontName=DISPLAY_SEMIBOLD, fontSize=12,
                             leading=15, textColor=INK, spaceBefore=8, spaceAfter=7),
        "body": ParagraphStyle("Body", parent=styles["BodyText"], fontName=BODY, fontSize=9.3, leading=14, textColor=MUTED,
                               spaceAfter=7),
        "small": ParagraphStyle("Small", parent=styles["BodyText"], fontName=BODY, fontSize=7.8, leading=11, textColor=SUBTLE),
        "kpi_label": ParagraphStyle("KpiLabel", parent=styles["Normal"], fontName=BODY_BOLD, fontSize=7.2,
                                    leading=9, textColor=SUBTLE, uppercase=True),
        "kpi_value": ParagraphStyle("KpiValue", parent=styles["Normal"], fontName=MONO_SEMIBOLD, fontSize=14,
                                    leading=17, textColor=INK),
        "white_small": ParagraphStyle("WhiteSmall", parent=styles["Normal"], fontName=BODY_SEMIBOLD, fontSize=8, textColor=colors.white),
    }


class ValuationDocTemplate(BaseDocTemplate):
    def __init__(self, target, company_name: str, **kwargs):
        super().__init__(target, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                         topMargin=19*mm, bottomMargin=17*mm, **kwargs)
        self.company_name = company_name
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        self.addPageTemplates(PageTemplate(id="report", frames=[frame], onPage=self._page))

    def _page(self, canvas, doc):
        canvas.saveState()
        if doc.page == 1:
            canvas.setFillColor(INK)
            canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
            canvas.setFillColor(colors.HexColor("#20202A"))
            canvas.rect(PAGE_W * .72, 0, PAGE_W * .28, PAGE_H, fill=1, stroke=0)
            canvas.setFillColor(RED)
            canvas.rect(0, PAGE_H - 4*mm, PAGE_W, 4*mm, fill=1, stroke=0)
            # Official Arroba wordmark from the canonical design system.
            canvas.drawImage(str(_LOGO_PRIMARY), 18*mm, PAGE_H - 25*mm,
                             width=42*mm, height=16.5*mm, preserveAspectRatio=True,
                             anchor="sw", mask="auto")
        else:
            canvas.setFillColor(PAPER)
            canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
            canvas.setStrokeColor(BORDER)
            canvas.line(18*mm, PAGE_H-12*mm, PAGE_W-18*mm, PAGE_H-12*mm)
            canvas.drawImage(str(_LOGO_PRIMARY), 18*mm, PAGE_H - 12*mm,
                             width=20*mm, height=7.8*mm, preserveAspectRatio=True,
                             anchor="sw", mask="auto")
            canvas.setFont(BODY_SEMIBOLD, 7)
            canvas.setFillColor(MUTED)
            canvas.drawString(42*mm, PAGE_H-9*mm, "VALORACIÓN AVANZADA")
            canvas.setFont(BODY, 7.5)
            canvas.setFillColor(SUBTLE)
            canvas.drawRightString(PAGE_W-18*mm, PAGE_H-9*mm, self.company_name)
        canvas.setFont(BODY, 7)
        canvas.setFillColor(SUBTLE)
        canvas.drawString(18*mm, 9*mm, "Estimación financiera basada en la información disponible")
        canvas.setFont(MONO, 7)
        canvas.drawRightString(PAGE_W-18*mm, 9*mm, f"{doc.page:02d}")
        canvas.restoreState()


def _section(title: str, number: str, styles) -> list:
    badge = Table([[Paragraph(number, styles["white_small"])]], colWidths=[8*mm], rowHeights=[8*mm])
    badge.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), RED), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                               ("ALIGN", (0,0), (-1,-1), "CENTER"), ("BOX", (0,0), (-1,-1), 0, RED)]))
    table = Table([[badge, Paragraph(title, styles["h1"])]], colWidths=[11*mm, 160*mm])
    table.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 0),
                               ("RIGHTPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 4)]))
    return [table, Spacer(1, 3*mm)]


def _kpi_strip(items: Iterable[tuple], styles, columns: int = 4) -> Table:
    cells = []
    for label, value in items:
        cells.append(Table([[Paragraph(str(label).upper(), styles["kpi_label"])],
                            [Paragraph(str(value), styles["kpi_value"])]], colWidths=[39*mm]))
    rows = [cells[i:i+columns] for i in range(0, len(cells), columns)]
    while rows and len(rows[-1]) < columns:
        rows[-1].append("")
    table = Table(rows, colWidths=[43*mm]*columns, hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), SOFT), ("BOX", (0,0), (-1,-1), .5, BORDER),
                               ("INNERGRID", (0,0), (-1,-1), .5, BORDER), ("VALIGN", (0,0), (-1,-1), "TOP"),
                               ("LEFTPADDING", (0,0), (-1,-1), 3*mm), ("RIGHTPADDING", (0,0), (-1,-1), 2*mm),
                               ("TOPPADDING", (0,0), (-1,-1), 3*mm), ("BOTTOMPADDING", (0,0), (-1,-1), 3*mm)]))
    return table


def _range_chart(value_range: Mapping[str, Any], currency: str) -> Drawing:
    width, height = 480, 85
    d = Drawing(width, height)
    low, central, high = (value_range.get(k) for k in ("low", "central", "high"))
    if not all(isinstance(v, (int, float)) for v in (low, central, high)):
        return d
    x0, x1, y = 35, width-35, 37
    d.add(Line(x0, y, x1, y, strokeColor=BORDER, strokeWidth=8))
    position = lambda value: x0 + (value-low)/(high-low or 1)*(x1-x0)
    d.add(Line(position(low), y, position(high), y, strokeColor=BLUE, strokeWidth=8))
    d.add(Circle(position(central), y, 7, fillColor=RED, strokeColor=colors.white, strokeWidth=2))
    for label, value, anchor in (("Conservador", low, "start"), ("Valor central", central, "middle"), ("Optimista", high, "end")):
        x = position(value)
        d.add(String(x, 62, label, fontName=BODY, fontSize=7.5, textAnchor=anchor, fillColor=SUBTLE))
        d.add(String(x, 12, _money(value, currency), fontName=MONO_SEMIBOLD, fontSize=9, textAnchor=anchor, fillColor=INK))
    return d


def _methods_chart(methods: Iterable[Mapping[str, Any]], currency: str) -> Drawing:
    methods = list(methods)
    d = Drawing(480, max(80, 38*len(methods)+18))
    for index, method in enumerate(methods):
        y = d.height - 30 - index*38
        weight = float(method.get("weight") or 0)
        d.add(String(0, y+9, _text(method.get("label"), _text(method.get("method"))), fontName=BODY_SEMIBOLD, fontSize=8, fillColor=INK))
        d.add(String(480, y+9, f"{weight*100:.0f}%", fontName=MONO_SEMIBOLD, fontSize=8, textAnchor="end", fillColor=INK))
        d.add(Rect(0, y-2, 480, 7, fillColor=BORDER, strokeColor=None))
        d.add(Rect(0, y-2, 480*weight, 7, fillColor=[BLUE, GREEN, RED, AMBER][index % 4], strokeColor=None))
        central = (method.get("enterprise_value_range") or {}).get("central")
        d.add(String(480, y-14, _money(central, currency), fontName=MONO, fontSize=7, textAnchor="end", fillColor=SUBTLE))
    return d


def _history_chart(history: Iterable[Mapping[str, Any]]) -> Drawing:
    history = list(history)
    d = Drawing(480, 155)
    values = [float(row.get("revenue") or 0) for row in history]
    if not values or max(values) <= 0:
        return d
    max_value = max(values) * 1.12
    x0, y0, chart_w, chart_h = 30, 25, 430, 105
    d.add(Line(x0, y0, x0+chart_w, y0, strokeColor=BORDER))
    points = []
    for index, row in enumerate(history):
        x = x0 + index * chart_w / max(1, len(history)-1)
        revenue = float(row.get("revenue") or 0)
        y = y0 + revenue/max_value*chart_h
        points.extend([x, y])
        d.add(Circle(x, y, 3, fillColor=BLUE, strokeColor=colors.white))
        d.add(String(x, 8, _text(row.get("year")), fontName=BODY, fontSize=7, textAnchor="middle", fillColor=SUBTLE))
        ebitda = float(row.get("ebitda") or 0)
        d.add(Rect(x-5, y0, 10, ebitda/max_value*chart_h, fillColor=RED, strokeColor=None))
    if len(points) >= 4:
        d.add(PolyLine(points, strokeColor=BLUE, strokeWidth=2))
    d.add(String(330, 143, "Ingresos", fontName=BODY, fontSize=7, fillColor=BLUE))
    d.add(String(390, 143, "EBITDA", fontName=BODY, fontSize=7, fillColor=RED))
    return d



def _sector_position_chart(metrics: Iterable[Mapping[str, Any]]) -> Drawing:
    metrics = list(metrics)[:7]
    height = max(55, 31 * len(metrics) + 12)
    d = Drawing(480, height)
    for index, metric in enumerate(metrics):
        y = height - 25 - index * 31
        percentile = max(0, min(100, float(metric.get("percentile") or 0)))
        d.add(String(0, y + 8, _text(metric.get("label"), _text(metric.get("metric"))),
                     fontName=BODY_SEMIBOLD, fontSize=7.5, fillColor=INK))
        d.add(Rect(210, y, 235, 7, fillColor=BORDER, strokeColor=None))
        d.add(Rect(210, y, 235 * percentile / 100, 7, fillColor=BLUE, strokeColor=None))
        d.add(Circle(210 + 235 * percentile / 100, y + 3.5, 4.5,
                     fillColor=RED, strokeColor=colors.white, strokeWidth=1))
        d.add(String(480, y + 1, f"P{percentile:.0f}", fontName=MONO_SEMIBOLD,
                     fontSize=7.5, textAnchor="end", fillColor=INK))
    return d


def _data_table(headers, rows, widths=None, align_right_from=1) -> Table:
    header_left = ParagraphStyle("TableHeaderLeft", fontName=BODY_BOLD, fontSize=7.2,
                                 leading=9, textColor=colors.white, alignment=TA_LEFT)
    header_right = ParagraphStyle("TableHeaderRight", parent=header_left, alignment=TA_RIGHT)
    body_left = ParagraphStyle("TableBodyLeft", fontName=BODY, fontSize=7.2,
                               leading=9.2, textColor=INK, alignment=TA_LEFT)
    body_right = ParagraphStyle("TableBodyRight", parent=body_left, fontName=MONO, alignment=TA_RIGHT)

    def make_row(values, header=False):
        rendered = []
        for index, value in enumerate(values):
            right = align_right_from is not None and index >= align_right_from
            style = (header_right if right else header_left) if header else (body_right if right else body_left)
            rendered.append(Paragraph(escape(str(value if value is not None else "-")), style))
        return rendered

    data = [make_row(headers, header=True)] + [make_row(row) for row in rows]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), INK),
        ("GRID", (0,0), (-1,-1), .4, BORDER),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, SOFT]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 5),
        ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    return table


def build_advanced_valuation_payload(profile: Mapping[str, Any]) -> Dict[str, Any]:
    """Create the single PDF payload used by Intel API and Document Intelligence Studio."""
    identity = profile.get("identity") or {}
    assessment = profile.get("assessment") or {}
    valuation = profile.get("valuation") or {}
    package = valuation.get("package") or valuation
    return {
        "company": {"name": identity.get("name"), "activity": identity.get("activity"),
                    "description": identity.get("description") or identity.get("business_description"),
                    "country": identity.get("country") or "España",
                    "cif": profile.get("cif_normalized")},
        "valuation": package,
        "financial_history": list(reversed((profile.get("evolution") or {}).get("points") or [])),
        "ebitda_adjustments": profile.get("ebitda_adjustments") or [],
        "value_factors": {"positive": assessment.get("strengths") or [],
                          "risks": assessment.get("risks") or []},
        "generated_at": profile.get("generated_at"),
        "engine_version": profile.get("engine_version"),
    }

def build_advanced_valuation_pdf(payload: Mapping[str, Any]) -> bytes:
    """Render a complete financial report from Intel's canonical valuation package."""
    company = payload.get("company") or {}
    package = payload.get("valuation") or {}
    summary = package.get("summary") or {}
    currency = summary.get("currency") or "EUR"
    styles = _styles()
    output = BytesIO()
    company_name = _text(company.get("name"), "Empresa analizada")
    valuation_date = _text(summary.get("as_of"), _text(payload.get("generated_at")))
    doc = ValuationDocTemplate(output, company_name, title="Valoración avanzada")
    story = []

    methods = (package.get("methods") or {}).get("applied") or []
    excluded = (package.get("methods") or {}).get("excluded") or []
    method_names = ", ".join(_text(m.get("label"), _text(m.get("method"))) for m in methods) or "los métodos permitidos por la información disponible"
    value_range = summary.get("enterprise_value_range") or {}
    equity_available = bool(summary.get("equity_value_available", summary.get("equity_value") is not None))

    story += [Spacer(1, 48*mm), Paragraph("VALORACIÓN AVANZADA", styles["cover_meta"]),
              Spacer(1, 5*mm), Paragraph(company_name, styles["title"]),
              Paragraph(" | ".join(filter(None, [_text(company.get("activity"), ""), _text(company.get("country"), ""),
                                                   f"Fecha de valoración: {valuation_date}"])), styles["cover_meta"]),
              Spacer(1, 25*mm), Paragraph("VALOR DEL ACCIONISTA" if equity_available else "VALOR DEL NEGOCIO", styles["cover_meta"]),
              Paragraph(_money(summary.get("equity_value") if equity_available else summary.get("enterprise_value"), currency),
                        ParagraphStyle("CoverValue", parent=styles["title"], fontName=MONO_SEMIBOLD, fontSize=35, leading=40, textColor=colors.white)),
              Spacer(1, 40*mm), Paragraph("Informe financiero confidencial", styles["cover_meta"]), PageBreak()]

    story += _section("Resumen ejecutivo", "01", styles)
    company_description = _text(
        company.get("description"),
        f"{company_name} desarrolla su actividad en el ámbito de {_text(company.get('activity'), 'su sector')}. "
        "El análisis considera su evolución financiera, posición sectorial, capacidad de generación de caja "
        "y referencias de mercado comparables a la fecha de valoración."
    )
    story += [Paragraph("Descripción de la compañía", styles["h2"]),
              Paragraph(company_description, styles["body"]),
              _kpi_strip([
        ("Enterprise Value", _money(summary.get("enterprise_value"), currency)),
        ("Equity Value", _money(summary.get("equity_value"), currency) if equity_available else "No concluyente"),
        ("Confianza", _pct((package.get("confidence") or {}).get("score"))),
        ("Métodos", _text((package.get("confidence") or {}).get("method_count"), str(len(methods)))),
    ], styles), Spacer(1, 4*mm), _range_chart(value_range, currency), Spacer(1, 2*mm),
    Paragraph("Cómo se ha calculado el valor", styles["h2"]),
    Paragraph(f"Se ha estimado el valor del negocio de <b>{company_name}</b> mediante {method_names}. El análisis parte de las cuentas históricas, contrasta el crecimiento y la rentabilidad con referencias sectoriales y evalúa la capacidad futura de generar caja. El resultado se presenta como un rango porque depende de la evolución del negocio, del riesgo y de las condiciones de mercado.", styles["body"]),
    Paragraph("La valoración responde a dos preguntas. Primero, cuánto vale la actividad por la caja que puede generar y por cómo valora el mercado negocios semejantes. Segundo, cuánto de ese valor corresponde a los accionistas después de considerar deuda financiera, caja y otros ajustes aplicables.", styles["body"])]
    if all(isinstance(value_range.get(k), (int, float)) for k in ("low", "central", "high")):
        story.append(Paragraph(f"A fecha de {valuation_date}, el rango estimado de Enterprise Value se sitúa entre <b>{_money(value_range['low'], currency)}</b> y <b>{_money(value_range['high'], currency)}</b>, con una referencia central de <b>{_money(value_range['central'], currency)}</b>. El extremo inferior representa una ejecución más prudente y el superior una evolución favorable dentro de parámetros razonables.", styles["body"]))
    for narrative in (package.get("methodology_narrative") or [])[:2]:
        story.append(Paragraph(_text(narrative), styles["body"]))

    history = payload.get("financial_history") or []
    story += [PageBreak()] + _section("Información financiera y normalización", "02", styles)
    story.append(Paragraph("La valoración utiliza magnitudes operativas normalizadas. Los resultados históricos permiten identificar la trayectoria del negocio, pero no se extrapolan de forma automática: se revisan su estabilidad, los ejercicios anómalos y las partidas que no representan la capacidad recurrente de generación de resultados.", styles["body"]))
    if history:
        story += [_history_chart(history), Spacer(1, 3*mm)]
        rows = [[_text(row.get("year")), _money(row.get("revenue"), currency), _money(row.get("ebitda"), currency),
                 _pct(row.get("ebitda_margin"))] for row in history]
        story.append(_data_table(["Ejercicio", "Ingresos", "EBITDA", "Margen EBITDA"], rows,
                                 widths=[28*mm, 47*mm, 47*mm, 45*mm]))
    else:
        story.append(Paragraph("No hay una serie histórica suficiente para representar la evolución financiera.", styles["body"]))
    adjustments = payload.get("ebitda_adjustments") or []
    story += [Spacer(1, 6*mm), Paragraph("Normalización del EBITDA", styles["h2"])]
    story.append(Paragraph("El EBITDA normalizado pretende representar el resultado operativo sostenible. Se eliminan, cuando existe evidencia, partidas extraordinarias, no recurrentes o ajenas a la actividad ordinaria. Cada ajuste debe quedar identificado y documentado; una partida sin evidencia permanece sin ajustar.", styles["body"]))
    if adjustments:
        rows = [[_text(item.get("label")), _money(item.get("amount"), currency), _text(item.get("evidence"))] for item in adjustments]
        story.append(_data_table(["Concepto", "Importe", "Evidencia"], rows, widths=[68*mm, 38*mm, 61*mm]))

    sector_positioning = package.get("sector_positioning") or {}
    if sector_positioning.get("status") == "available":
        cohort = sector_positioning.get("cohort") or {}
        sector_metrics = sector_positioning.get("metrics") or []
        peer_groups = sector_positioning.get("peer_groups") or []
        rankings = sector_positioning.get("rankings") or {}
        story += [PageBreak()] + _section("Posicionamiento y comparables sectoriales", "03", styles)
        story += [Paragraph(
            "Esta sección compara la compañía con empresas de actividad y tamaño semejantes. "
            "Los percentiles describen su posición dentro de la cohorte: P50 es la mediana; "
            "P25 y P75 delimitan el rango central. Un percentil elevado no siempre es favorable, "
            "por lo que cada indicador conserva su dirección económica.", styles["body"]),
            _kpi_strip([
                ("Cohorte", _text(cohort.get("label"))),
                ("Muestra", _text(cohort.get("sample_size"))),
                ("Ámbito", _text(cohort.get("cnae_scope"))),
                ("Fecha", _text(cohort.get("as_of"))),
            ], styles), Spacer(1, 4*mm)]
        if sector_metrics:
            story += [_sector_position_chart(sector_metrics), Spacer(1, 3*mm)]
            ratio_like = {"current_ratio", "interest_coverage", "debt_to_equity", "capital_intensity"}
            money_like = {"revenue_per_employee"}
            def _sector_render(metric, value):
                if value is None:
                    return "-"
                key = metric.get("metric")
                if key in money_like:
                    return _money(value, currency)
                if key in ratio_like:
                    return f"{value:.2f}x" if isinstance(value, (int, float)) else _text(value)
                return _pct(value)
            metric_rows = [[
                _text(metric.get("label")), _sector_render(metric, metric.get("company_value")),
                _sector_render(metric, metric.get("p25")), _sector_render(metric, metric.get("median")),
                _sector_render(metric, metric.get("p75")), f"P{metric.get('percentile')}",
            ] for metric in sector_metrics[:7]]
            story.append(_data_table(["Indicador", "Empresa", "P25", "Mediana", "P75", "Posición"],
                                     metric_rows, widths=[49*mm, 25*mm, 22*mm, 27*mm, 22*mm, 22*mm]))
        ranking_notes = []
        if rankings.get("market_position"):
            item = rankings["market_position"]
            ranking_notes.append(f"Por ingresos, la compañía ocupa la posición {item.get('rank')} de {item.get('total')} dentro de las compañías comparables por sector y tamaño.")
        if rankings.get("sector_revenue_percentile") is not None:
            ranking_notes.append(f"Sus ingresos se sitúan en el percentil {rankings.get('sector_revenue_percentile')} del ámbito sectorial disponible.")
        if ranking_notes:
            story += [Spacer(1, 4*mm), Paragraph("Lectura de la posición", styles["h2"]),
                      Paragraph(" ".join(ranking_notes), styles["body"])]
        peers = ((peer_groups[0] if peer_groups else {}).get("peers") or [])[:6]
        if peers:
            story += [PageBreak()] + _section("Grupo de pares sectoriales", "04", styles)
            story += [Paragraph("Los pares se seleccionan por actividad, banda de tamaño y proximidad geográfica. Su función es aportar contexto operativo; no constituyen por sí solos una muestra de valoración.", styles["body"])]
            peer_rows = [[_text(peer.get("name")), _text(peer.get("provincia")),
                          _money(peer.get("revenue"), currency), _money(peer.get("ebitda"), currency),
                          _pct(peer.get("ebitda_margin"))] for peer in peers]
            story.append(_data_table(["Compañía", "Provincia", "Ingresos", "EBITDA", "Margen"],
                                     peer_rows, widths=[61*mm, 29*mm, 29*mm, 27*mm, 21*mm]))
        story.append(Paragraph("La muestra, sus exclusiones y su fecha de corte quedan versionadas en Intel. Si la cobertura no permite una comparación fiable, el indicador o ranking se omite en lugar de estimarse.", styles["small"]))

    story += [PageBreak()] + _section("Metodología financiera", "05", styles)
    story += [Paragraph("Qué se está valorando", styles["h2"]),
              Paragraph("El <b>Enterprise Value</b> representa el valor del negocio operativo con independencia de cómo está financiado. El <b>Equity Value</b> representa el valor atribuible a los accionistas después de restar la deuda financiera, sumar la caja y considerar, cuando proceda, otros ajustes del balance. Esta distinción evita confundir el valor de la actividad con el importe que recibirían sus propietarios.", styles["body"]),
              _data_table(["Relación fundamental", "Cálculo"], [["Valor del accionista", "Enterprise Value - deuda financiera + caja +/- otros ajustes"]], widths=[58*mm, 109*mm], align_right_from=None),
              Spacer(1, 5*mm), Paragraph("Principio de valoración", styles["h2"]),
              Paragraph("No se obtiene el valor mediante una única fórmula. Se aplican los enfoques que permiten los datos disponibles y se concilian atendiendo a la calidad, actualidad, comparabilidad y suficiencia de la evidencia. Un método débil puede servir como contraste, pero no debe recibir el mismo peso que una referencia sólida.", styles["body"]),
              Paragraph("Descuento de flujos de caja", styles["h2"]),
              Paragraph("El DCF estima cuánto vale hoy la caja que el negocio puede generar en el futuro. El flujo libre para la empresa parte del resultado operativo después de impuestos, suma las amortizaciones y resta la inversión y el aumento de capital circulante. Es la caja disponible para remunerar conjuntamente a acreedores y accionistas.", styles["body"]),
              _data_table(["Flujo libre para la empresa", "Componentes"], [["FCFF", "EBIT después de impuestos + amortizaciones - capex - variacion de circulante"]], widths=[58*mm, 109*mm], align_right_from=None),
              Spacer(1, 5*mm), Paragraph("Referencias de mercado", styles["h2"]),
              Paragraph("Las compañías cotizadas muestran cómo valora el mercado negocios semejantes. Las operaciones privadas, cuando existe una muestra suficiente y trazable, muestran precios pagados por el control. El valor patrimonial puede aportar una referencia adicional en negocios intensivos en activos. Cada enfoque responde a una pregunta distinta y se interpreta dentro de sus limitaciones.", styles["body"]),
              Paragraph("Rango y nivel de confianza", styles["h2"]),
              Paragraph("El rango no es un intervalo estadístico ni garantiza un precio de transacción. Expresa resultados coherentes bajo hipótesis conservadoras, centrales y favorables. La confianza mide la solidez de la evidencia utilizada; no es la probabilidad matemática de alcanzar el valor indicado.", styles["body"])]

    story += [PageBreak()] + _section("Métodos aplicados y conciliación", "06", styles)
    story.append(Paragraph("Los métodos ofrecen perspectivas complementarias. El DCF refleja la capacidad futura de generar caja; las cotizadas reflejan valoraciones observables del mercado público; y las operaciones privadas, cuando están disponibles, reflejan precios pagados en transacciones. La ponderación se determina por la calidad de los datos y la adecuación de cada enfoque a la compañía.", styles["body"]))
    if methods:
        story += [_methods_chart(methods, currency), Spacer(1, 3*mm)]
        rows = [[_text(m.get("label"), _text(m.get("method"))), _money((m.get("enterprise_value_range") or {}).get("central"), currency),
                 _pct(m.get("weight")), _pct(m.get("confidence")), _text(m.get("explanation"))] for m in methods]
        story.append(_data_table(["Método", "Valor central", "Peso", "Confianza", "Justificación"], rows,
                                 widths=[38*mm, 29*mm, 18*mm, 21*mm, 61*mm]))
    if excluded:
        story += [Spacer(1, 5*mm), Paragraph("Métodos no aplicados", styles["h2"])]
        rows = [[_text(m.get("label"), _text(m.get("method"))), "No aplicado", _text(m.get("explanation"), "No existe evidencia suficiente, homogenea y trazable.")] for m in excluded]
        story.append(_data_table(["Método", "Estado", "Motivo"], rows, widths=[45*mm, 30*mm, 92*mm], align_right_from=None))
    story.append(Paragraph("Un método no disponible se excluye expresamente y no influye en el rango final. La conciliación evita una media mecánica cuando la calidad de las referencias es desigual.", styles["body"]))

    story += [PageBreak()] + _section("DCF, supuestos y sensibilidad", "07", styles)
    assumptions = ((package.get("assumptions") or {}).get("dcf") or {})
    story += [Paragraph("La proyección combina la trayectoria de la compañía con referencias correspondientes a su actividad y tamaño. Los datos propios tienen prioridad; las referencias sectoriales sirven para normalizar hipótesis y evitar extrapolaciones indefinidas de crecimientos o márgenes excepcionales.", styles["body"]),
              Paragraph("Los flujos se descuentan mediante el WACC, que representa el coste medio de los recursos financieros y el riesgo del negocio. Combina el coste de los fondos propios, el coste de la deuda después de impuestos y una estructura financiera objetivo. Tras el período explícito se calcula un valor terminal con un crecimiento sostenible inferior al WACC.", styles["body"]),
              Paragraph("Los escenarios conservador, base y optimista no son previsiones cerradas. Permiten observar cómo cambia el resultado ante combinaciones coherentes de crecimiento, rentabilidad, inversión y riesgo. La sensibilidad WACC-crecimiento terminal es especialmente relevante porque el valor terminal puede representar una parte significativa del DCF.", styles["body"])]
    assumption_rows = []
    for key, item in assumptions.items():
        if isinstance(item, Mapping):
            value = item.get("value")
            rendered = _pct(value) if isinstance(value, (int, float)) and abs(value) <= 1 else _text(value)
            source = _text(item.get("source")).replace("_", " ")
            reason = _text(item.get("reason"), _text(item.get("explanation"), "Referencia histórica, sectorial o de mercado contrastada"))
            assumption_rows.append([key.replace("_", " ").title(), rendered, source, reason])
    if assumption_rows:
        story.append(_data_table(["Supuesto", "Valor", "Base", "Justificación"], assumption_rows,
                                 widths=[42*mm, 24*mm, 39*mm, 62*mm]))
    sensitivity = package.get("sensitivity") or []
    if sensitivity:
        story += [Spacer(1, 6*mm), Paragraph("Sensibilidad WACC - crecimiento terminal", styles["h2"])]
        growths = [cell.get("terminal_growth") for cell in sensitivity[0].get("values", [])]
        rows = [[_pct(row.get("wacc"))] + [_money(cell.get("enterprise_value"), currency) for cell in row.get("values", [])] for row in sensitivity]
        story.append(_data_table(["WACC / g"] + [_pct(g) for g in growths], rows, widths=[35*mm] + [44*mm]*len(growths)))

    story += [PageBreak()] + _section("Cotizadas, ajustes y puente al accionista", "08", styles)
    comparable = ((package.get("comparables") or {}).get("public_market") or {})
    benchmark = comparable.get("benchmark") or {}
    story += [Paragraph("El método de compañías cotizadas comparables contrasta la empresa con negocios de actividad semejante y valoración observable. La selección considera actividad, geografía, tamaño, crecimiento, márgenes, intensidad de capital y estructura financiera. La mediana reduce la influencia de observaciones extremas.", styles["body"]),
              Paragraph("Una empresa privada difiere de una cotizada en escala, liquidez, acceso al capital y transparencia. Por ello, el múltiplo público se interpreta como referencia de mercado y se adapta a las características de la compañía. No se aplica un descuento genérico por falta de liquidez al Enterprise Value. Si se valorase una participación minoritaria, cualquier ajuste de liquidez se analizaría por separado sobre el Equity Value.", styles["body"]),
              _kpi_strip([
        ("Múltiplo", f"{comparable.get('multiple'):.2f}x" if isinstance(comparable.get("multiple"), (int,float)) else "-"),
        ("Muestra cotizadas", _text(benchmark.get("sample_size"))),
        ("Base", _text(comparable.get("basis")).replace("_", " ")),
        ("Geografía", _text(benchmark.get("source_level")).replace("_", " ")),
    ], styles), Spacer(1, 6*mm)]
    bridge = (package.get("assumptions") or {}).get("equity_bridge") or {}
    if bridge.get("net_debt_known"):
        rows = [["Enterprise Value", _money(summary.get("enterprise_value"), currency)],
                ["Menos: deuda financiera", _money(-(bridge.get("financial_debt") or 0), currency)],
                ["Más: caja", _money(bridge.get("cash"), currency)],
                ["Equity Value", _money(summary.get("equity_value"), currency)]]
        story += [Paragraph("Puente Enterprise Value - Equity Value", styles["h2"]),
                  Paragraph("El valor del negocio se convierte en valor para los accionistas restando la deuda financiera y sumando la caja disponible en la fecha de valoración. Otros ajustes solo se incorporan cuando están identificados y suficientemente soportados.", styles["body"]),
                  _data_table(["Concepto", "Importe"], rows, widths=[105*mm, 62*mm])]
    else:
        story.append(Paragraph("No se dispone de información completa y fiable sobre deuda financiera y caja. En consecuencia, el informe mantiene el Enterprise Value como referencia del negocio operativo y no presenta un Equity Value concluyente.", styles["body"]))

    story += [PageBreak()] + _section("Riesgos, trazabilidad y fuentes", "09", styles)
    factors = payload.get("value_factors") or {}
    positives = factors.get("positive") or []
    risks = factors.get("risks") or []
    factor_table = Table([
        [Paragraph("INCREMENTAN EL VALOR", styles["kpi_label"]), Paragraph("RIESGOS A VALIDAR", styles["kpi_label"])],
        [Paragraph("<br/>".join(f"- {_text(item)}" for item in positives) or "-", styles["body"]),
         Paragraph("<br/>".join(f"- {_text(item)}" for item in risks) or "-", styles["body"])],
    ], colWidths=[83.5*mm, 83.5*mm])
    factor_table.setStyle(TableStyle([("BACKGROUND", (0,0), (0,-1), colors.HexColor("#EDF7F0")),
                                      ("BACKGROUND", (1,0), (1,-1), colors.HexColor("#FFF4F5")),
                                      ("BOX", (0,0), (-1,-1), .5, BORDER), ("INNERGRID", (0,0), (-1,-1), .5, BORDER),
                                      ("VALIGN", (0,0), (-1,-1), "TOP"), ("PADDING", (0,0), (-1,-1), 8)]))
    story += [factor_table, Spacer(1, 6*mm), Paragraph("Fuentes por categoría", styles["h2"])]
    sources = [["Cuentas y universo empresarial", "Históricos, balance, clasificación y magnitudes normalizadas"],
               ["Tipo sin riesgo y primas", "Parámetros fechados para el coste de capital"],
               ["Cotizadas", "Muestra, multiples, percentiles y exclusiones"],
               ["Operaciones privadas", "Transacciones comparables cuando existe muestra suficiente"]]
    story += [_data_table(["Categoría", "Uso en la valoración"], sources, widths=[67*mm, 100*mm], align_right_from=None), Spacer(1, 5*mm),
              Paragraph("Cada cifra del informe debe poder clasificarse como dato histórico, supuesto, cálculo o referencia de mercado. Las fuentes se capturan con fecha; las muestras conservan sus exclusiones; y las reglas del motor se versionan para que el resultado pueda reproducirse y compararse entre fechas.", styles["body"]),
              Paragraph("Los parámetros sectoriales se utilizan para contrastar crecimiento, márgenes, inversión, circulante, riesgo y estructura financiera. La trayectoria de la empresa tiene prioridad. Cuando una regla sectorial sea provisional, el nivel de confianza debe reflejarlo; cuando proceda de una cohorte calibrada, se mostrarán fecha de corte, tamaño de muestra y percentiles utilizados.", styles["body"]),
              Paragraph(f"Contrato de datos: {_text(package.get('contract_version'))}. Motor: {_text(payload.get('engine_version'), _text(package.get('engine_version')))}. Fecha de generación: {_text(payload.get('generated_at'))}.", styles["small"])]

    story += [PageBreak()] + _section("Alcance, uso y aviso legal", "10", styles)
    legal_paragraphs = [
        "Este informe constituye una estimación financiera basada en la información disponible, en referencias de mercado y en hipótesis consideradas razonables a la fecha del análisis. Su finalidad es facilitar una evalúacion económica preliminar de la compañía y de sus principales inductores de valor.",
        "El informe no representa una oferta de compra o venta, un precio garantizado, una recomendación de inversión, una auditoría, una due diligence completa, una opinión legal o fiscal, una opinión de razonabilidad financiera ni una certificación independiente del valor. No debe utilizarse como única base para adoptar una decisión de inversión, financiación o desinversión.",
        "Las cifras históricas dependen de la información suministrada por las categorías de fuentes identificadas. Se aplican controles de coherencia, normalización y tratamiento de extremos, pero estos controles no sustituyen la verificación independiente de las cuentas, de la deuda financiera, de la caja ni de la documentación contractual, fiscal, laboral y legal.",
        "Las proyecciones y escenarios contienen información prospectiva y se apoyan en supuestos sobre crecimiento, márgenes, inversión, circulante, fiscalidad, coste de capital y valor terminal. Los resultados reales pueden diferir de forma material. Ninguna hipótesis constituye un compromiso de cumplimiento por parte de la compañía o de sus accionistas.",
        "El precio finalmente alcanzado en una transacción puede diferir del rango estimado por primas de control, sinergias, estructura y calendario de pago, financiación, fiscalidad, garantias, contingencias, competencia entre compradores, evolución del mercado y hechos posteriores a la fecha de valoración.",
        "El destinatario debe realizar su propio análisis independiente y, cuando corresponda, recurrir a asesores financieros, contables, legales, fiscales y técnicos. La responsabilidad sobre cualquier decisión adoptada a partir de este informe corresponde al destinatario y a sus asesores.",
        "Este documento es confidencial y se facilita exclusivamente a su destinatario. No puede reproducirse, distribuirse, comunicarse ni citarse, total o parcialmente, sin autorización previa y por escrito, salvo cuando lo exija una obligación legal o regulatoria.",
        "La valoración es válida exclusivamente para la fecha indicada. Cambios en la información financiera, en la estructura de deuda y caja, en las condiciones de mercado o en las perspectivas del negocio pueden requerir su actualización.",
    ]
    story += [Paragraph("Naturaleza y finalidad del informe", styles["h2"])]
    for paragraph in legal_paragraphs:
        story.append(Paragraph(paragraph, styles["body"]))
    story += [Spacer(1, 4*mm), Paragraph("Confirmacion de lectura", styles["h2"]),
              Paragraph("La recepción y utilización de este informe implica el conocimiento de su alcance, sus supuestos y sus limitaciones. Las conclusiones deben interpretarse conjuntamente con todas las secciones, anexos y advertencias, y no de forma aislada.", styles["body"])]

    doc.build(story)
    return output.getvalue()
