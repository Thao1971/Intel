"""Deterministic point-9 validation runner for Arroba's valuation engine."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Iterable
from services.engines.valuation.reconciliation import reconcile_valuation

HERE = Path(__file__).resolve().parent
BASKET = HERE / "validation_basket.v1.json"
REQUIRED_SECTORS = {"inmobiliario", "medios", "industria", "distribucion", "servicios", "software"}


def _valuation(case: Dict[str, Any]) -> Dict[str, Any]:
    listed_central = case["ebitda"] * case["observed_ev_ebitda"] * case["private_adjustment"]
    dcf_central = case["dcf_central"]
    return {
        "dcf": {"status": "available", "confidence": .80, "decision_readiness": "decision_grade",
                "scenarios": {"conservative": {"enterprise_value": dcf_central * .88},
                              "base": {"enterprise_value": dcf_central},
                              "optimistic": {"enterprise_value": dcf_central * 1.12}}},
        "method": "ev_ebitda", "multiple_basis": "observed_public_adjusted", "confidence": .75,
        "range": {"low": listed_central * .85, "central": listed_central, "high": listed_central * 1.15},
    }


def run_validation(path: Path = BASKET) -> Dict[str, Any]:
    basket = json.loads(path.read_text())
    sectors = {case["sector"] for case in basket["cases"]}
    rows = []
    for case in basket["cases"]:
        result = reconcile_valuation(_valuation(case),
                                     {"financial_debt": 0, "cash": 0},
                                     {"archetype": case["archetype"]})
        actual = result["enterprise_value"]
        manual = case["manual_ev_range"]
        regression = abs(actual - case["baseline_ev"]) / max(case["baseline_ev"], 1)
        rows.append({"id": case["id"], "company": case["company"], "sector": case["sector"],
                     "enterprise_value": actual, "manual_low": manual["low"],
                     "manual_high": manual["high"], "manual_match": manual["low"] <= actual <= manual["high"],
                     "baseline_ev": case["baseline_ev"], "regression_pct": round(regression, 6),
                     "regression_ok": regression <= .005, "methods": len(result["methods_applied"])})

    # Extreme cases are assertions on financial coherence, not valuation targets.
    missing_debt = reconcile_valuation(_valuation(basket["cases"][0]), {"cash": 10})
    negative_ranges = reconcile_valuation({"dcf": {"status": "available", "scenarios": {
        "conservative": {"enterprise_value": -1}, "base": {"enterprise_value": 0},
        "optimistic": {"enterprise_value": 1}}}}, {})
    extreme_checks = {
        "missing_debt_blocks_equity": missing_debt.get("equity_value") is None,
        "negative_range_is_rejected": negative_ranges.get("status") == "unavailable",
        "weights_sum_to_one": all(abs(sum(m["weight"] for m in reconcile_valuation(
            _valuation(case), {"financial_debt": 0, "cash": 0})["methods_applied"]) - 1) < 1e-9
            for case in basket["cases"]),
    }
    passed = sectors == REQUIRED_SECTORS and all(r["manual_match"] and r["regression_ok"] for r in rows) and all(extreme_checks.values())
    return {"status": "passed" if passed else "failed", "basket_version": basket["version"],
            "as_of": basket["as_of"], "sector_coverage": sorted(sectors), "cases": rows,
            "extreme_checks": extreme_checks}


def write_report(output: Path) -> Dict[str, Any]:
    report = run_validation(); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    report = write_report(HERE / "validation_report.latest.json")
    print(json.dumps({"status": report["status"], "cases": len(report["cases"]),
                      "sectors": report["sector_coverage"], "extreme_checks": report["extreme_checks"]}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "passed" else 1)
