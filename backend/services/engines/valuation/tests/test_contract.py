from services.engines.valuation.contract import build_valuation_package


def _valuation():
    return {
        "method": "ev_ebitda", "multiple": 7.5, "multiple_basis": "observed_public_adjusted",
        "methodology": "Método de cotizadas.", "hypotheses": ["Hipótesis trazable."],
        "dcf": {"status": "available", "engine_version": "dcf-v1", "currency": "EUR",
                "as_of": 2025, "assumptions": {"wacc": {"value": .09}},
                "scenarios": {"base": {"enterprise_value": 1000}}, "sensitivity": [{"wacc": .09}]},
        "reconciliation": {"status": "available", "engine_version": "rec-v1",
                           "enterprise_value": 1050, "equity_value": 900,
                           "enterprise_value_range": {"low": 900, "central": 1050, "high": 1200},
                           "equity_value_range": {"low": 750, "central": 900, "high": 1050},
                           "methods_applied": [{"method": "dcf", "status": "applied", "weight": 1}],
                           "methods_excluded": [{"method": "private_transactions", "status": "excluded",
                                                 "reason": "private_transactions_not_connected"}],
                           "confidence": .78, "decision_readiness": "screen_grade",
                           "narrative": "Conciliación trazable.", "warnings": []},
    }


def test_contract_has_every_intel_beta_section():
    result = build_valuation_package(_valuation(), {"year": 2025, "financial_debt": 200, "cash": 50})
    assert set(result) == {"contract_version", "status", "summary", "methods", "scenarios",
                           "assumptions", "comparables", "sensitivity", "sector_positioning",
                           "confidence", "warnings", "methodology_narrative", "sources_and_versions"}
    assert result["summary"]["enterprise_value"] == 1050
    assert result["summary"]["equity_value"] == 900
    assert result["comparables"]["private_transactions"]["reason"] == "private_transactions_not_connected"


def test_contract_never_calculates_missing_equity_bridge():
    valuation = _valuation()
    valuation["reconciliation"]["equity_value"] = None
    valuation["reconciliation"]["equity_value_range"] = None
    result = build_valuation_package(valuation, {"cash": 50})
    assert result["summary"]["equity_value"] is None
    assert result["summary"]["equity_value_available"] is False


def test_unavailable_contract_is_complete_and_stable():
    result = build_valuation_package({"method": "insufficient_data", "confidence": 0}, {})
    assert result["status"] == "unavailable"
    assert result["methods"]["applied"] == []
    assert result["methods"]["excluded"][0]["reason"] == "reconciliation_unavailable"


def test_contract_carries_sector_positioning_without_beta_recalculation():
    positioning = {
        "status": "available",
        "cohort": {"sample_size": 214, "as_of": 2025},
        "metrics": [{"metric": "ebitda_margin", "percentile": 69}],
    }
    result = build_valuation_package(
        _valuation(), {"year": 2025, "financial_debt": 200, "cash": 50},
        sector_positioning=positioning,
    )
    assert result["sector_positioning"] == positioning
