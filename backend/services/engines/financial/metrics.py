"""Financial metrics extraction + normalized statements (from the Data Layer).

The engine is the boundary: it reads norm_financials (statement detail) + master_companies
(canonical summary). Consumers never read those directly. Verified Iberinform Valu8 codes.
"""

from typing import Dict, List, Optional

from services.engines.valuation.conventions import (
    accounting_working_capital, calculated_ebitda, operating_working_capital,
)

# Iberinform Valu8 account codes → canonical line.
CODES = {
    "revenue": "40100", "operating_income": "49100", "depreciation": "40800",
    "net_income": "49500", "supplies": "40400", "personnel_costs": "40600",
    "financial_expenses": "41500",
    "total_assets": "10000", "equity": "20000",
    "non_current_assets": "11000", "current_assets": "12000", "cash": "12700",
    "non_current_liabilities": "31000", "current_liabilities": "32000",
    "lt_debt": "31200", "st_debt": "32300",
    # Working-capital line items (now stored with the full EAV) -> cash-cycle ratios.
    "trade_debtors": "12300", "inventories": "12200", "suppliers": "32510",
    # Cash-flow statement (EFE, PGC codes 61xxx-65xxx). Present only when the company
    # files full — not abbreviated/PYME — accounts; absent -> cashflow stays None (honest).
    "cf_operating": "61500", "cf_investing": "62300", "cf_financing": "63400",
    "cf_capex": "62100", "cf_net_change": "65000",
    "cash_start": "65100", "cash_end": "65200",
}


def _g(acc: Dict, key: str) -> Optional[float]:
    return acc.get(CODES[key])


def _year_metrics(acc: Dict) -> Dict[str, Optional[float]]:
    """Canonical figures for one fiscal year from its account map."""
    op = _g(acc, "operating_income")
    dep = _g(acc, "depreciation")
    ebitda = calculated_ebitda(op, dep)
    lt, st = _g(acc, "lt_debt"), _g(acc, "st_debt")
    fin_debt = None
    if lt is not None or st is not None:
        fin_debt = round((lt or 0) + (st or 0), 2)
    eq, ta = _g(acc, "equity"), _g(acc, "total_assets")
    total_liabilities = round(ta - eq, 2) if (ta is not None and eq is not None) else None
    # Cash flow (only present for full-account filers). FCF = operating + investing
    # (investing is stored negative). Cash conversion = operating CF / EBITDA.
    cf_op, cf_inv = _g(acc, "cf_operating"), _g(acc, "cf_investing")
    fcf = round(cf_op + cf_inv, 2) if (cf_op is not None and cf_inv is not None) else None
    cash_conv = round(cf_op / ebitda, 4) if (cf_op is not None and ebitda not in (None, 0)) else None
    accounting_nwc = accounting_working_capital(_g(acc, "current_assets"), _g(acc, "current_liabilities"))
    operating_nwc = operating_working_capital(
        _g(acc, "trade_debtors"), _g(acc, "inventories"), _g(acc, "suppliers"))
    return {
        "revenue": _g(acc, "revenue"), "supplies": _g(acc, "supplies"),
        "personnel_costs": _g(acc, "personnel_costs"),
        "operating_income": op, "ebit": op, "depreciation": dep, "ebitda": ebitda,
        "financial_expenses": _g(acc, "financial_expenses"), "net_income": _g(acc, "net_income"),
        "total_assets": ta, "equity": eq,
        "non_current_assets": _g(acc, "non_current_assets"),
        "current_assets": _g(acc, "current_assets"), "cash": _g(acc, "cash"),
        "non_current_liabilities": _g(acc, "non_current_liabilities"),
        "current_liabilities": _g(acc, "current_liabilities"),
        "financial_debt": fin_debt, "total_liabilities": total_liabilities,
        "st_debt": st, "lt_debt": lt,
        "cf_operating": cf_op, "cf_investing": cf_inv, "cf_financing": _g(acc, "cf_financing"),
        "cf_capex": _g(acc, "cf_capex"), "cf_net_change": _g(acc, "cf_net_change"),
        "cash_start": _g(acc, "cash_start"), "cash_end": _g(acc, "cash_end"),
        "free_cash_flow": fcf, "cash_conversion": cash_conv,
        "trade_debtors": _g(acc, "trade_debtors"), "inventories": _g(acc, "inventories"),
        "suppliers": _g(acc, "suppliers"),
        "operating_working_capital": operating_nwc,
        "working_capital": operating_nwc if operating_nwc is not None else accounting_nwc,
        "working_capital_definition": ("trade_debtors_plus_inventories_minus_suppliers"
                                       if operating_nwc is not None
                                       else ("current_assets_minus_current_liabilities"
                                             if accounting_nwc is not None else "unavailable")),
    }


def build_series(norm_fin_docs: List[Dict], basis: str = "individual") -> List[Dict]:
    """Per-year metrics, newest first. Prefers individual accounts, falls back to any."""
    docs = [f for f in norm_fin_docs if f.get("basis") == basis] or norm_fin_docs
    docs = sorted(docs, key=lambda f: (f.get("year") or 0), reverse=True)
    out = []
    for f in docs:
        m = _year_metrics(f.get("accounts") or {})
        m["year"] = f.get("year")
        m["basis"] = f.get("basis")
        m["fiscal_close_date"] = f.get("fiscal_close_date")
        out.append(m)
    return out


def build_series_strict(norm_fin_docs: List[Dict], basis: str) -> List[Dict]:
    """Fase 6 (2026-09-01) · Igual que `build_series()` pero SIN el fallback a
    cualquier otro basis: devuelve `[]` si no hay ningún documento con ese `basis`
    exacto. Uso: exponer explícitamente las cuentas consolidadas de grupo como
    bloque aparte, sin heredar individual por error."""
    docs = [f for f in norm_fin_docs if f.get("basis") == basis]
    docs = sorted(docs, key=lambda f: (f.get("year") or 0), reverse=True)
    out = []
    for f in docs:
        m = _year_metrics(f.get("accounts") or {})
        m["year"] = f.get("year")
        m["basis"] = f.get("basis")
        m["fiscal_close_date"] = f.get("fiscal_close_date")
        out.append(m)
    return out


def statements(latest: Dict, employees: Optional[int]) -> Dict:
    """Structured income statement + balance sheet for the latest year. Cashflow N/A (individual)."""
    return {
        "year": latest.get("year"), "basis": latest.get("basis"),
        "income_statement": {k: latest.get(k) for k in
                             ("revenue", "supplies", "personnel_costs", "operating_income",
                              "depreciation", "ebitda", "ebit", "financial_expenses", "net_income")},
        "balance_sheet": {k: latest.get(k) for k in
                          ("non_current_assets", "current_assets", "cash", "total_assets",
                           "equity", "non_current_liabilities", "current_liabilities",
                           "st_debt", "lt_debt", "financial_debt", "total_liabilities")},
        # Cash flow only when the company filed it (full accounts). None otherwise — honest.
        "cashflow": ({k: latest.get(k) for k in
                      ("cf_operating", "cf_investing", "cf_financing", "cf_capex",
                       "cf_net_change", "cash_start", "cash_end", "free_cash_flow", "cash_conversion")}
                     if latest.get("cf_operating") is not None else None),
        "employees": employees,
    }


# Multi-year cash-flow statement rows (arroba.v2 FinancialSection shape). Minimal set
# requested by Beta: OCF, capex, financing flow, net change in cash, FCF + cash conversion.
_CASHFLOW_ROWS = [
    ("cf_operating", "Flujo de caja de explotación (OCF)", "operating", "currency"),
    ("cf_capex", "Inversiones (Capex)", "investing", "currency"),
    ("cf_financing", "Flujo de caja de financiación", "financing", "currency"),
    ("cf_net_change", "Variación neta de tesorería", "net_change", "currency"),
    ("free_cash_flow", "Flujo de caja libre (FCF)", "summary", "currency"),
    ("cash_conversion", "Conversión de caja (OCF/EBITDA)", "summary", "percent"),
]

# ES label batch (canon): legend for the flat `statements.cashflow` keys + category labels.
_CASHFLOW_LABELS_ES = {
    "cf_operating": "Flujo de caja de explotación (OCF)",
    "cf_investing": "Flujo de caja de inversión",
    "cf_financing": "Flujo de caja de financiación",
    "cf_capex": "Inversiones (Capex)",
    "cf_net_change": "Variación neta de tesorería",
    "cash_start": "Tesorería inicial",
    "cash_end": "Tesorería final",
    "free_cash_flow": "Flujo de caja libre (FCF)",
    "cash_conversion": "Conversión de caja (OCF/EBITDA)",
}
_CASHFLOW_CATEGORY_ES = {
    "operating": "Explotación", "investing": "Inversión", "financing": "Financiación",
    "net_change": "Variación neta", "summary": "Resumen",
}


def cashflow_statement(series: List[Dict]) -> Optional[Dict]:
    """Structured multi-year cash-flow table, SAME shape as Beta's profit_loss/balance:
    `{years, rows[{key,label,category,values[{value,format}]}]}`. Real-data-only:
    only years/rows with genuine EAV cash-flow values are included; returns None when
    the company filed no cash-flow statement (abbreviated/PYME accounts) → Beta shows
    "Pendiente". Consumes ONLY figures already produced by `build_series` from the full EAV."""
    if not series:
        return None
    cf_years = [s for s in series if any(s.get(k) is not None for k, _, _, _ in _CASHFLOW_ROWS)]
    if not cf_years:
        return None
    years = [s.get("year") for s in cf_years]
    rows = []
    for key, label, category, fmt in _CASHFLOW_ROWS:
        vals = [s.get(key) for s in cf_years]
        if all(v is None for v in vals):
            continue
        rows.append({"key": key, "label": label, "category": category,
                     "category_label": _CASHFLOW_CATEGORY_ES.get(category),
                     "values": [{"value": v, "format": fmt} for v in vals]})
    return {"years": years, "rows": rows,
            "cash_flow_labels_es": _CASHFLOW_LABELS_ES,
            "category_labels_es": _CASHFLOW_CATEGORY_ES} if rows else None
