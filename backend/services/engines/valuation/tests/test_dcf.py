from services.engines.valuation import calculate_dcf

SERIES = [
    {"year": 2025, "revenue": 1200, "operating_income": 144, "depreciation": 36, "cf_capex": 48, "working_capital": 180, "financial_debt": 250, "cash": 50},
    {"year": 2024, "revenue": 1100, "operating_income": 121, "depreciation": 33, "cf_capex": 44, "working_capital": 165},
    {"year": 2023, "revenue": 1000, "operating_income": 100, "depreciation": 30, "cf_capex": 40, "working_capital": 150},
]

def test_calculates_auditable_dcf():
    result = calculate_dcf(SERIES)
    assert result["status"] == "available"
    assert result["scenarios"]["base"]["enterprise_value"] > 0
    assert result["scenarios"]["base"]["equity_value"] == result["scenarios"]["base"]["enterprise_value"] - 200
    assert len(result["scenarios"]["base"]["projections"]) == 5
    assert len(result["sensitivity"]) == 3
    assert result["assumptions"]["revenue_growth"]["source"] == "iberinform_historical"
    assert result["lineage"]["calculation_engine"] == "Intel"

def test_does_not_assume_missing_debt_is_zero():
    rows = [{k: v for k, v in row.items() if k != "financial_debt"} for row in SERIES]
    result = calculate_dcf(rows)
    assert result["scenarios"]["base"]["equity_value"] is None
    assert "financial_debt_missing_equity_value_not_calculated" in result["warnings"]

def test_rejects_invalid_terminal_spread():
    result = calculate_dcf(SERIES, {"wacc": .02, "terminal_growth": .03})
    assert result["status"] == "unavailable"
    assert result["reason"] == "invalid_dcf_assumptions"

def test_requires_positive_revenue():
    assert calculate_dcf([{"year": 2025, "revenue": 0}])["reason"] == "positive_revenue_required"

def test_discloses_default_when_capex_is_missing():
    rows = [{k: v for k, v in row.items() if k != "cf_capex"} for row in SERIES]
    result = calculate_dcf(rows)
    assert result["assumptions"]["capex_pct_revenue"]["source"] == "arroba_default"

def test_normalizes_negative_capex_and_derives_working_capital():
    rows = [
        {**row, "cf_capex": -abs(row["cf_capex"]), "depreciation": -abs(row["depreciation"]), "current_assets": 400, "current_liabilities": 220}
        for row in SERIES
    ]
    for row in rows:
        row.pop("working_capital")
    result = calculate_dcf(rows)
    assert result["assumptions"]["capex_pct_revenue"]["value"] > 0
    assert result["assumptions"]["depreciation_pct_revenue"]["value"] > 0
    assert result["assumptions"]["nwc_pct_revenue"]["source"] == "iberinform_historical"

def test_applies_sector_rule_with_traceable_blend():
    from services.engines.valuation.sector_rules import resolve_sector_rule
    rule = resolve_sector_rule("5915", SERIES[0]["revenue"])
    result = calculate_dcf(SERIES, sector_rule=rule)
    assert result["sector_rule"]["archetype"] == "media_content"
    assert result["assumptions"]["wacc"]["source"] == "sector_policy_seed"
    assert result["assumptions"]["revenue_growth"]["source"] == "iberinform_historical_sector_blend"
    assert result["decision_readiness"] == "screen_grade"

def test_does_not_assume_missing_cash_is_zero():
    rows = [{k: v for k, v in row.items() if k != "cash"} for row in SERIES]
    result = calculate_dcf(rows)
    assert result["scenarios"]["base"]["equity_value"] is None
    assert "cash_missing_equity_value_not_calculated" in result["warnings"]
    assert result["equity_bridge"]["status"] == "incomplete"

def test_uses_source_aware_wacc_engine_result():
    from services.engines.valuation.wacc import calculate_wacc
    from services.engines.valuation.sector_rules import resolve_sector_rule
    rule = resolve_sector_rule("7311", SERIES[0]["revenue"])
    wacc = calculate_wacc(SERIES[0], rule)
    result = calculate_dcf(SERIES, sector_rule=rule, wacc_analysis=wacc)
    assert result["assumptions"]["wacc"]["source"] == "arroba_wacc_engine"
    assert result["assumptions"]["wacc"]["value"] == wacc["wacc"]
    assert result["wacc_analysis"]["engine_version"] == "arroba-wacc-v1"
