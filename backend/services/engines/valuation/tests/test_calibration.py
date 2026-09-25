from services.engines.valuation.calibration import (
    CalibrationAccumulator, calibrate_companies, company_observation,
    percentile, sanitize_series, winsorize,
)

def _company(index, cnae="5915", revenue=5_000_000, margin=.10, capex=.03):
    return {
        "cif_normalized": f"A{index:08d}",
        "cnae_code": cnae,
        "series": [
            {"year": 2025, "revenue": revenue, "operating_income": revenue * margin,
             "depreciation": -revenue * .02, "cf_capex": -revenue * capex,
             "trade_debtors": revenue * .12, "inventories": revenue * .01,
             "suppliers": revenue * .05},
            {"year": 2024, "revenue": revenue / 1.04, "operating_income": revenue / 1.04 * margin,
             "depreciation": -revenue / 1.04 * .02, "cf_capex": -revenue / 1.04 * capex,
             "trade_debtors": revenue / 1.04 * .12, "inventories": revenue / 1.04 * .01,
             "suppliers": revenue / 1.04 * .05},
        ],
    }

def test_percentile_and_winsorization():
    values = list(range(1, 101)) + [10_000]
    adjusted, treatment = winsorize(values)
    assert percentile([1, 2, 3, 4], .5) == 2.5
    assert max(adjusted) < 10_000
    assert treatment["adjusted"] > 0

def test_company_observation_uses_canonical_metrics():
    observation = company_observation(_company(1))
    assert observation["archetype"] == "media_content"
    assert observation["size_band"] == "small"
    assert round(observation["metrics"]["revenue_growth"], 4) == .04
    assert round(observation["metrics"]["ebit_margin"], 4) == .10
    assert round(observation["metrics"]["nwc_pct_revenue"], 4) == .08

def test_calibrates_publishable_candidate_bands():
    companies = [_company(i, margin=.08 + i * .001) for i in range(50)]
    result = calibrate_companies(companies, "2026-09-20")
    cohort = next(c for c in result["cohorts"]
                  if c["cohort_key"] == "archetype:media_content|size:small")
    margin = cohort["parameters"]["ebit_margin"]
    assert result["population_initial"] == 50
    assert result["population_eligible"] == 50
    assert cohort["calibration_status"] == "candidate_iberinform"
    assert margin["sample_size"] == 50
    assert margin["publishable_median"] is True
    assert margin["publishable_band"] is True
    assert margin["p25"] < margin["median"] < margin["p75"]
    assert cohort["decision_readiness"] == "review_required"

def test_small_cohort_does_not_publish_statistics():
    result = calibrate_companies([_company(i) for i in range(10)])
    cohort = next(c for c in result["cohorts"]
                  if c["cohort_key"] == "archetype:media_content|size:small")
    assert cohort["parameters"]["ebit_margin"]["median"] is None
    assert cohort["parameters"]["ebit_margin"]["p25"] is None
    assert cohort["quality"]["eligible_for_review"] is False

def test_exclusions_are_explicit():
    result = calibrate_companies([
        {"cif_normalized": "NOFIN", "cnae_code": "5915", "series": []},
        {"cif_normalized": "ZEROREV", "cnae_code": "5915",
         "series": [{"year": 2025, "revenue": 0}]},
    ])
    assert result["population_initial"] == 2
    assert result["population_eligible"] == 0
    assert result["exclusions"] == {
        "no_financials": 1, "non_positive_latest_revenue": 1}

def test_streaming_accumulator_is_deterministic():
    companies = [_company(i, margin=.05 + i * .002) for i in range(60)]
    first = CalibrationAccumulator("2026-09-20", sample_limit=25)
    second = CalibrationAccumulator("2026-09-20", sample_limit=25)
    for company in companies:
        first.add_company(company)
    for company in reversed(companies):
        second.add_company(company)
    assert first.result()["cohorts"] == second.result()["cohorts"]


def test_series_sanitizer_controls_basis_duplicates_and_invalid_years():
    rows=[
        {"year":2025,"basis":"individual","revenue":100},
        {"year":2025,"basis":"individual","revenue":100,"operating_income":10},
        {"year":2025,"basis":"consolidated","revenue":500},
        {"year":None,"basis":"individual","revenue":90},
    ]
    clean,quality=sanitize_series(rows)
    assert len(clean)==1
    assert clean[0]["operating_income"]==10
    assert quality=={"invalid_year_rows":1,"mixed_basis_rows":1,
                     "duplicate_financial_years":1}


def test_calibration_never_uses_accounting_working_capital_as_operating_nwc():
    company=_company(999)
    for row in company["series"]:
        row.pop("trade_debtors"); row.pop("inventories"); row.pop("suppliers")
        row["working_capital"]=999999
        row["working_capital_definition"]="current_assets_minus_current_liabilities"
    observation=company_observation(company)
    assert observation["metrics"]["nwc_pct_revenue"] is None
