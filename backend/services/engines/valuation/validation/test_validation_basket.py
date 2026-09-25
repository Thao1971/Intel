from .validation_runner import REQUIRED_SECTORS, run_validation


def test_stable_real_company_basket_matches_manual_ranges_and_baseline():
    report = run_validation()
    assert report["status"] == "passed"
    assert set(report["sector_coverage"]) == REQUIRED_SECTORS
    assert len(report["cases"]) == 6
    assert all(row["manual_match"] for row in report["cases"])
    assert all(row["regression_ok"] for row in report["cases"])


def test_extreme_financial_cases_remain_coherent():
    assert all(run_validation()["extreme_checks"].values())
