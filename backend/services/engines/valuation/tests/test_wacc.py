from services.engines.valuation.wacc import (
    beta_from_comparables, calculate_wacc, relever_beta, unlever_beta,
)

RULE = {"archetype": "advertising", "size_band": "small"}

def test_beta_unlevering_and_relevering_round_trip():
    beta = 1.2
    unlevered = unlever_beta(beta, .5, .25)
    assert round(relever_beta(unlevered, .5, .25), 8) == beta

def test_beta_from_comparables_uses_median_and_discloses_exclusions():
    peers = [
        {"name": f"P{i}", "levered_beta": 1 + i * .05,
         "financial_debt": 20, "market_cap": 100}
        for i in range(5)
    ] + [{"name": "Missing"}]
    result = beta_from_comparables(peers)
    assert result["status"] == "observed_comparables"
    assert result["sample_size"] == 5
    assert result["target_debt_weight"] is not None
    assert len(result["excluded"]) == 1

def test_wacc_is_fully_decomposed_and_screen_grade_with_seeds():
    result = calculate_wacc(
        {"financial_debt": 100, "financial_expenses": -6}, RULE)
    assert .05 < result["wacc"] < .25
    assert result["components"]["pre_tax_cost_of_debt"]["value"] == .06
    assert result["components"]["pre_tax_cost_of_debt"]["source"].startswith("iberinform")
    assert result["decision_readiness"] == "screen_grade"
    assert "wacc_contains_provisional_components" in result["warnings"]

def test_missing_observed_cost_uses_explicit_credit_spread_seed():
    result = calculate_wacc({}, RULE)
    component = result["components"]["pre_tax_cost_of_debt"]
    assert component["source"] == "risk_free_plus_arroba_credit_spread_seed"
    assert component["value"] > result["components"]["risk_free_rate"]["value"]

def test_size_premium_increases_small_company_wacc():
    small = calculate_wacc({}, RULE)["wacc"]
    large = calculate_wacc({}, {**RULE, "size_band": "large"})["wacc"]
    assert small > large

def test_beta_pipeline_rejects_outliers_and_high_leverage():
    peers=[
      {"name":"Bad beta","levered_beta":5,"financial_debt":20,"market_cap":100},
      {"name":"Negative debt","levered_beta":1,"financial_debt":-1,"market_cap":100},
      {"name":"Extreme leverage","levered_beta":1,"financial_debt":1000,"market_cap":10},
    ]
    result=beta_from_comparables(peers)
    assert result["sample_size"]==0
    assert {x["reason"] for x in result["excluded"]}=={
      "beta_out_of_range","invalid_debt_or_market_cap","debt_weight_out_of_range"}


def test_insufficient_comparable_sample_does_not_override_seed():
    peers=[{"name":f"P{i}","levered_beta":1.2,"financial_debt":20,"market_cap":100}
           for i in range(4)]
    beta=beta_from_comparables(peers)
    assert beta["status"]=="insufficient_sample"
    result=calculate_wacc({},RULE,comparable_beta=beta)
    assert result["components"]["unlevered_beta"]["source"]=="arroba_sector_seed"


def test_default_market_premia_are_separate_and_dated():
    result=calculate_wacc({},RULE)
    erp=result["components"]["equity_risk_premium"]
    crp=result["components"]["country_risk_premium"]
    assert erp["value"]==.0423
    assert crp["value"]==.0155
    assert erp["observation_date"]=="2026-01-05"
