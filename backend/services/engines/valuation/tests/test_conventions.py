from services.engines.valuation.conventions import (
    accounting_working_capital, calculated_ebitda, equity_bridge,
    normalized_capex, operating_working_capital, working_capital_value,
)

def test_normalizes_ebitda_and_capex_signs():
    assert calculated_ebitda(100, -20) == 120
    assert calculated_ebitda(100, 20) == 120
    assert normalized_capex(-30) == 30

def test_working_capital_prefers_operating_definition():
    row = {"trade_debtors": 100, "inventories": 40, "suppliers": 70,
           "current_assets": 300, "current_liabilities": 150}
    result = working_capital_value(row)
    assert result == {"value": 70.0, "definition": "trade_debtors_plus_inventories_minus_suppliers"}
    assert operating_working_capital(100, 40, 70) == 70
    assert accounting_working_capital(300, 150) == 150

def test_equity_bridge_requires_debt_and_cash():
    assert equity_bridge({"financial_debt": 250, "cash": 50}, 1000)["equity_value"] == 800
    missing_debt = equity_bridge({"cash": 50}, 1000)
    assert missing_debt["equity_value"] is None
    assert missing_debt["missing_fields"] == ["financial_debt"]
    missing_cash = equity_bridge({"financial_debt": 250}, 1000)
    assert missing_cash["equity_value"] is None
    assert missing_cash["missing_fields"] == ["cash"]

def test_zero_debt_and_zero_cash_are_known_values():
    bridge = equity_bridge({"financial_debt": 0, "cash": 0}, 1000)
    assert bridge["net_debt_known"] is True
    assert bridge["equity_value"] == 1000
