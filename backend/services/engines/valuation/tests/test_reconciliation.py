from services.engines.valuation.reconciliation import reconcile_valuation


def _dcf(confidence=.8):
    return {"status": "available", "confidence": confidence, "decision_readiness": "decision_grade",
            "scenarios": {"conservative": {"enterprise_value": 800},
                          "base": {"enterprise_value": 1000},
                          "optimistic": {"enterprise_value": 1200}}}


def test_combines_dcf_and_observed_listed_comparables():
    value = {"dcf": _dcf(), "method": "ev_ebitda", "multiple_basis": "observed_public_adjusted",
             "confidence": .7, "range": {"low": 900, "central": 1100, "high": 1300}}
    result = reconcile_valuation(value, {"financial_debt": 200, "cash": 50})
    assert result["status"] == "available"
    assert sum(x["weight"] for x in result["methods_applied"]) == 1
    assert 1000 < result["enterprise_value"] < 1100
    assert result["equity_value"] == round(result["enterprise_value"] - 150, 2)


def test_missing_debt_blocks_equity_value():
    result = reconcile_valuation({"dcf": _dcf()}, {"cash": 50})
    assert result["equity_value"] is None
    assert result["equity_value_range"] is None
    assert "financial_debt_missing_equity_value_not_calculated" in result["warnings"]


def test_inferred_multiple_and_missing_ttr_are_explicitly_excluded():
    value = {"dcf": _dcf(), "method": "ev_ebitda", "multiple_basis": "inferred_reference",
             "range": {"low": 800, "central": 1000, "high": 1200}}
    result = reconcile_valuation(value, {"financial_debt": 0, "cash": 0})
    reasons = {x["method"]: x["reason"] for x in result["methods_excluded"]}
    assert reasons["listed_comparables"] == "inferred_reference_not_observed"
    assert reasons["private_transactions"] == "private_transactions_not_connected"


def test_private_transactions_require_three_observations():
    result = reconcile_valuation(
        {"dcf": _dcf()}, {"financial_debt": 0, "cash": 0},
        private_transactions={"status": "available", "sample_size": 3, "confidence": .75,
                              "range": {"low": 950, "central": 1050, "high": 1250}})
    assert "private_transactions" in {x["method"] for x in result["methods_applied"]}


def test_real_estate_adds_asset_value_when_bridge_is_complete():
    result = reconcile_valuation({"dcf": _dcf()},
                                 {"equity": 700, "financial_debt": 200, "cash": 50},
                                 {"archetype": "real_estate"})
    assert "asset_value" in {x["method"] for x in result["methods_applied"]}


def test_no_methods_returns_unavailable():
    result = reconcile_valuation({"dcf": {"status": "unavailable"}}, {})
    assert result["status"] == "unavailable"
    assert result["enterprise_value_range"] is None


def test_user_weights_override_only_available_methods():
    value = {"dcf": _dcf(), "method": "ev_ebitda",
             "multiple_basis": "observed_public_adjusted", "confidence": .7,
             "range": {"low": 900, "central": 1100, "high": 1300}}
    result = reconcile_valuation(value, {"financial_debt": 0, "cash": 0},
                                 user_weights={"dcf": 25, "listed_comparables": 75,
                                               "private_transactions": 99})
    weights={item["method"]:item["weight"] for item in result["methods_applied"]}
    assert weights=={"dcf":.25,"listed_comparables":.75}
    assert result["weighting_rule"]=="user_supplied_available_methods_normalised"
