from services.engines.valuation.private_company_adjustments import adjust_public_multiple

def test_unknown_qualitative_inputs_are_not_invented():
    result=adjust_public_multiple(10,"small")
    assert result["adjusted_multiple"]==9
    assert result["total_adjustment"]==-.10
    assert "largest_customer_pct" in result["unavailable_evidence"]
    assert result["liquidity_discount_applied"] is False
    assert result["decision_readiness"]=="screen_grade"

def test_observed_risks_and_quality_adjust_multiple():
    result=adjust_public_multiple(10,"medium",{
        "recurring_revenue_pct":.80,
        "largest_customer_pct":.45,
        "key_person_dependency":True,
        "audited_accounts":True,
    })
    assert result["total_adjustment"]==-.125
    assert result["adjusted_multiple"]==8.75
    assert result["decision_readiness"]=="review_ready"

def test_adjustment_caps_protect_from_extremes():
    result=adjust_public_multiple(10,"micro",{
        "recurring_revenue_pct":0,
        "largest_customer_pct":.90,
        "key_person_dependency":True,
        "audited_accounts":False,
    })
    assert result["total_adjustment"]>=-.35
