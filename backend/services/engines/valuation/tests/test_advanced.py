from services.engines.valuation.advanced import calculate_advanced


def _profile():
    history=[]
    for year,revenue,ebitda,ebit,debt,cash in [
        (2024,12_400_000,3_200_000,2_800_000,2_400_000,1_300_000),
        (2023,11_600_000,2_800_000,2_420_000,None,None),
        (2022,10_800_000,2_400_000,2_040_000,None,None),
    ]:
        history.append({"year":year,"basis":"individual",
            "income_statement":{"revenue":revenue,"ebitda":ebitda,"ebit":ebit,
                                "operating_income":ebit,"depreciation":ebit-ebitda},
            "balance_sheet":{"financial_debt":debt,"cash":cash,"equity":4_700_000},
            "cashflow":{"cf_capex":-revenue*.04}})
    return {"master_id":"m1","cif_normalized":"B1","statements_history":history,
            "valuation":{"method":"ev_ebitda","multiple":6,
                "multiple_basis":"inferred_reference","range":{"low":15_000_000,
                "central":19_000_000,"high":23_000_000},"confidence":.6,
                "package":{"assumptions":{"sector_rule":{}},"sector_positioning":{}}}}


def test_advanced_run_applies_user_inputs_and_returns_canonical_package():
    result=calculate_advanced(_profile(),{
        "financial_overrides":{"2024.income_statement.revenue":13_000_000},
        "ebitda_adjustments":[{"concept":"gasto excepcional","amount":200_000,
                               "direction":"add","recurring":"no","evidence":"mayor"}],
        "projection_assumptions":{"revenue_growth":.08,"terminal_growth":.02,
            "tax_rate":.25,"ebit_margin":.22,"depreciation_pct_revenue":.03,
            "capex_pct_revenue":.04,"nwc_pct_revenue":.10},
        "wacc_inputs":{"risk_free_rate":.035,"equity_risk_premium":.043,
            "country_risk_premium":.015,"unlevered_beta":.8,"debt_weight":.3,
            "pre_tax_cost_of_debt":.06,"tax_rate":.25},
        "method_weights":{"dcf":1},
        "equity_bridge":{"financial_debt":2_000_000,"cash":1_000_000},
    },"2026-09-24T00:00:00Z")
    valuation=result["valuation"]
    assert result["engine_version"]=="arroba-advanced-valuation-v1"
    assert valuation["package"]["status"]=="available"
    assert valuation["dcf"]["assumptions"]["revenue_growth"]["source"]=="user_supplied"
    assert valuation["advanced_inputs"]["ebitda_bridge"]["normalized_ebitda"]==3_400_000
    assert valuation["enterprise_value"]==20_400_000
    assert valuation["range"]=={"low":16_105_263.16,"central":20_400_000.0,
                                "high":24_694_736.84}
    assert valuation["package"]["summary"]["equity_value"] is not None
