"""Canonical financial definitions shared by every Intel valuation method."""
from __future__ import annotations
from typing import Any, Dict, List, Mapping, Optional

CONVENTIONS_VERSION = "valuation-conventions-v1"

def number(value: Any) -> Optional[float]:
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None

def normalized_depreciation(value: Any) -> Optional[float]:
    parsed = number(value)
    return abs(parsed) if parsed is not None else None

def normalized_capex(value: Any) -> Optional[float]:
    parsed = number(value)
    return abs(parsed) if parsed is not None else None

def calculated_ebitda(ebit: Any, depreciation: Any) -> Optional[float]:
    operating_income = number(ebit)
    depreciation_value = normalized_depreciation(depreciation)
    if operating_income is None or depreciation_value is None:
        return None
    return round(operating_income + depreciation_value, 2)

def accounting_working_capital(current_assets: Any, current_liabilities: Any) -> Optional[float]:
    assets, liabilities = number(current_assets), number(current_liabilities)
    if assets is None or liabilities is None:
        return None
    return round(assets - liabilities, 2)

def operating_working_capital(trade_debtors: Any, inventories: Any, suppliers: Any) -> Optional[float]:
    debtors, stock, trade_creditors = number(trade_debtors), number(inventories), number(suppliers)
    if debtors is None or stock is None or trade_creditors is None:
        return None
    return round(debtors + stock - trade_creditors, 2)

def working_capital_value(row: Mapping[str, Any]) -> Dict[str, Any]:
    direct = number(row.get("working_capital"))
    if direct is not None:
        return {"value": direct, "definition": "reported_working_capital"}
    operating = operating_working_capital(
        row.get("trade_debtors"), row.get("inventories"), row.get("suppliers"))
    if operating is not None:
        return {"value": operating, "definition": "trade_debtors_plus_inventories_minus_suppliers"}
    accounting = accounting_working_capital(row.get("current_assets"), row.get("current_liabilities"))
    if accounting is not None:
        return {"value": accounting, "definition": "current_assets_minus_current_liabilities"}
    return {"value": None, "definition": "unavailable"}

def equity_bridge(row: Mapping[str, Any], enterprise_value: Any = None) -> Dict[str, Any]:
    debt, cash, ev = number(row.get("financial_debt")), number(row.get("cash")), number(enterprise_value)
    missing = []
    if debt is None:
        missing.append("financial_debt")
    if cash is None:
        missing.append("cash")
    known = not missing
    net_debt = round(debt - cash, 2) if known else None
    equity = round(ev - net_debt, 2) if known and ev is not None else None
    warnings = [f"{field}_missing_equity_value_not_calculated" for field in missing]
    return {
        "status": "complete" if known else "incomplete",
        "net_debt_known": known,
        "financial_debt": debt,
        "cash": cash,
        "net_debt": net_debt,
        "enterprise_value": ev,
        "equity_value": equity,
        "missing_fields": missing,
        "warnings": warnings,
        "definition": "equity_value_equals_enterprise_value_minus_financial_debt_plus_cash",
        "conventions_version": CONVENTIONS_VERSION,
    }


def apply_equity_bridge_to_scenarios(
    scenarios: List[Dict[str, Any]], row: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    output = []
    for scenario in scenarios:
        enriched = dict(scenario)
        bridge = equity_bridge(row, enriched.get("enterprise_value"))
        enriched["equity_value"] = bridge["equity_value"]
        enriched["equity_bridge"] = bridge
        output.append(enriched)
    return output

FINANCIAL_DEFINITIONS = {
    "ebitda": "EBIT + absolute depreciation and amortisation",
    "capex": "absolute reported capex cash outflow",
    "operating_working_capital": "trade debtors + inventories - suppliers",
    "accounting_working_capital": "current assets - current liabilities",
    "net_debt": "financial debt - cash",
    "equity_value": "enterprise value - financial debt + cash",
}
