from services.engines.valuation.private_company_adjustments import (
    adjust_public_multiple, extract_private_company_evidence,
)


def test_iberinform_audited_indicator_is_observed_evidence():
    result = extract_private_company_evidence({"registry": {"audited": "Sí"}})
    assert result["values"]["audited_accounts"] is True
    assert result["lineage"]["audited_accounts"]["source"] == "Iberinform"
    adjusted = adjust_public_multiple(10, "large", result["values"])
    assert adjusted["adjusted_multiple"] == 10.25


def test_only_explicit_due_diligence_inputs_are_used():
    result = extract_private_company_evidence({
        "valuation_inputs": {
            "recurring_revenue_pct": .80,
            "largest_customer_pct": .45,
            "key_person_dependency": "No",
        }
    })
    assert result["values"] == {
        "recurring_revenue_pct": .80,
        "largest_customer_pct": .45,
        "key_person_dependency": False,
    }
    assert result["unavailable"] == ["audited_accounts"]


def test_unknown_inputs_remain_unavailable():
    result = extract_private_company_evidence({"shareholders": [{"name": "Founder"}]})
    assert result["values"] == {}
    assert "key_person_dependency" in result["unavailable"]
