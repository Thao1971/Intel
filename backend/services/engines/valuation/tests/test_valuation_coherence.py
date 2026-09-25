from services.engines.financial.metrics import _year_metrics
from services.engines.valuation.conventions import (
    apply_equity_bridge_to_scenarios, equity_bridge,
)

def test_canonical_metrics_use_shared_definitions():
    accounts = {
        "49100": 100, "40800": -20, "12000": 300, "32000": 150,
        "12300": 100, "12200": 40, "32510": 70,
    }
    metrics = _year_metrics(accounts)
    assert metrics["ebitda"] == 120
    assert metrics["working_capital"] == 70
    assert metrics["working_capital_definition"] == "trade_debtors_plus_inventories_minus_suppliers"

def test_net_debt_requires_debt_and_cash():
    assert equity_bridge({"financial_debt": 250, "cash": 50})["net_debt"] == 200
    assert equity_bridge({"financial_debt": 250})["net_debt"] is None
    assert equity_bridge({"cash": 50})["net_debt"] is None

def test_multiple_scenarios_do_not_publish_equity_when_bridge_is_incomplete():
    scenarios = [{"name": "low", "enterprise_value": 500},
                 {"name": "base", "enterprise_value": 600},
                 {"name": "high", "enterprise_value": 700}]
    result = apply_equity_bridge_to_scenarios(scenarios, {"financial_debt": 100})
    assert all(case["equity_value"] is None for case in result)
    assert all(case["equity_bridge"]["status"] == "incomplete" for case in result)

def test_multiple_scenarios_bridge_to_equity_when_complete():
    scenarios = [{"name": "low", "enterprise_value": 500},
                 {"name": "base", "enterprise_value": 600},
                 {"name": "high", "enterprise_value": 700}]
    result = apply_equity_bridge_to_scenarios(
        scenarios, {"financial_debt": 100, "cash": 20})
    assert [case["equity_value"] for case in result] == [420, 520, 620]
