"""Source-aware WACC engine for private Spanish companies."""
from __future__ import annotations
from datetime import date, datetime
from statistics import median
from typing import Any, Dict, Iterable, Mapping, Optional

from .conventions import number

WACC_VERSION = "arroba-wacc-v1"
MARKET_SNAPSHOT = {
    "as_of": "2026-09-17",
    "risk_free_rate": {
        "value": .034875063501, "source": "ECB", "status": "observed",
        "series_key": "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
        "observation_date": "2026-09-17",
        "source_url": "https://data.ecb.europa.eu/data/datasets/YC/YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"
    },
    "equity_risk_premium": {"value": .0423, "source": "Damodaran mature market ERP",
                            "status": "external_reference", "observation_date": "2026-01-05",
                            "source_url": "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ctryprem.html"},
    "country_risk_premium": {"value": .0155, "source": "Damodaran Spain country risk premium",
                             "status": "external_reference", "observation_date": "2026-01-05",
                             "source_url": "https://pages.stern.nyu.edu/adamodar/New_Home_Page/datafile/ctryprem.html"},
}
# Unlevered beta and target debt/value. Seeds remain screen-grade until replaced by
# a reviewed public-comparable cohort.
SECTOR_SEEDS = {
    "real_estate": (.70, .35), "construction": (1.00, .30), "media_content": (.95, .25),
    "advertising": (.98, .20), "software_data": (1.10, .15),
    "professional_services": (.95, .15), "industrial": (.95, .30),
    "wholesale": (.85, .30), "retail": (.90, .30), "hospitality": (1.05, .35),
    "transport_logistics": (.95, .40), "energy_utilities": (.65, .45),
    "healthcare": (.80, .20), "general_business": (1.00, .25),
}
SIZE_PREMIUM = {"micro": .025, "small": .015, "medium": .0075,
                "large": 0.0, "unknown": .015}
CREDIT_SPREAD = {"micro": .045, "small": .035, "medium": .025,
                 "large": .018, "unknown": .035}

def unlever_beta(levered_beta: float, debt_to_equity: float, tax_rate: float) -> float:
    return levered_beta / (1 + (1 - tax_rate) * debt_to_equity)

def relever_beta(unlevered_beta: float, debt_to_equity: float, tax_rate: float) -> float:
    return unlevered_beta * (1 + (1 - tax_rate) * debt_to_equity)

def beta_from_comparables(comparables: Iterable[Mapping[str, Any]],
                          tax_rate: float = .25) -> Dict[str, Any]:
    values, debt_weights = [], []
    included, excluded = [], []
    for comparable in comparables:
        beta = number(comparable.get("levered_beta"))
        debt = number(comparable.get("financial_debt"))
        equity = number(comparable.get("market_cap"))
        identifier = comparable.get("name") or comparable.get("ticker")
        if beta is None or debt is None or equity is None:
            excluded.append({"identifier": identifier, "reason": "missing_beta_debt_or_market_cap"})
            continue
        if not 0 < beta <= 4:
            excluded.append({"identifier": identifier, "reason": "beta_out_of_range"})
            continue
        if debt < 0 or equity <= 0:
            excluded.append({"identifier": identifier, "reason": "invalid_debt_or_market_cap"})
            continue
        debt_weight=debt/(debt+equity)
        if debt_weight>.90:
            excluded.append({"identifier": identifier, "reason": "debt_weight_out_of_range"})
            continue
        value = unlever_beta(beta, debt / equity, tax_rate)
        values.append(value)
        debt_weights.append(debt_weight)
        included.append({"identifier": identifier, "unlevered_beta": value,
                         "debt_weight": debt_weight})
    return {
        "unlevered_beta": median(values) if values else None,
        "target_debt_weight": median(debt_weights) if debt_weights else None,
        "sample_size": len(values), "included": included, "excluded": excluded,
        "status": "observed_comparables" if len(values) >= 5 else "insufficient_sample",
    }

def _age_days(component: Mapping[str, Any], as_of: Optional[str]) -> Optional[int]:
    raw=component.get("observation_date") or as_of
    try: return (date.today()-datetime.fromisoformat(str(raw)[:10]).date()).days
    except (TypeError,ValueError): return None

def calculate_wacc(latest: Mapping[str, Any], sector_rule: Mapping[str, Any],
                   market_snapshot: Optional[Mapping[str, Any]] = None,
                   comparable_beta: Optional[Mapping[str, Any]] = None,
                   tax_rate: float = .25) -> Dict[str, Any]:
    market = dict(market_snapshot or MARKET_SNAPSHOT)
    archetype = sector_rule.get("archetype") or "general_business"
    size = sector_rule.get("size_band") or "unknown"
    seed_beta, target_debt_weight = SECTOR_SEEDS.get(archetype, SECTOR_SEEDS["general_business"])
    comparable_ready=(comparable_beta or {}).get("status")=="observed_comparables"
    observed_beta = number((comparable_beta or {}).get("unlevered_beta")) if comparable_ready else None
    unlevered = observed_beta if observed_beta is not None else seed_beta
    beta_source = "public_comparables" if observed_beta is not None else "arroba_sector_seed"

    observed_debt_weight = (number((comparable_beta or {}).get("target_debt_weight"))
                            if comparable_ready else None)
    capital_source = "public_comparables" if observed_debt_weight is not None else "arroba_sector_seed"
    debt_weight = max(0.0, min(.80, observed_debt_weight if observed_debt_weight is not None
                              else target_debt_weight))
    equity_weight = 1 - debt_weight
    debt_to_equity = debt_weight / equity_weight if equity_weight else 0
    levered = relever_beta(unlevered, debt_to_equity, tax_rate)

    risk_free = float(market["risk_free_rate"]["value"])
    erp = float(market["equity_risk_premium"]["value"])
    country = float(market["country_risk_premium"]["value"])
    size_premium = SIZE_PREMIUM.get(size, SIZE_PREMIUM["unknown"])
    cost_of_equity = risk_free + levered * erp + country + size_premium

    debt = number(latest.get("financial_debt"))
    interest = number(latest.get("financial_expenses"))
    observed_cost = abs(interest) / debt if debt and debt > 0 and interest is not None else None
    if observed_cost is not None and 0 < observed_cost < .30:
        pre_tax_cost_debt, debt_source = observed_cost, "iberinform_observed_interest_over_debt"
    else:
        pre_tax_cost_debt = risk_free + CREDIT_SPREAD.get(size, CREDIT_SPREAD["unknown"])
        debt_source = "risk_free_plus_arroba_credit_spread_seed"
    after_tax_cost_debt = pre_tax_cost_debt * (1 - tax_rate)
    wacc = cost_of_equity * equity_weight + after_tax_cost_debt * debt_weight

    warnings=[]
    rf_age=_age_days(market["risk_free_rate"],market.get("as_of"))
    erp_age=_age_days(market["equity_risk_premium"],market.get("as_of"))
    crp_age=_age_days(market["country_risk_premium"],market.get("as_of"))
    if rf_age is None or rf_age>45: warnings.append("risk_free_rate_stale_or_undated")
    if erp_age is None or erp_age>550: warnings.append("equity_risk_premium_stale_or_undated")
    if crp_age is None or crp_age>550: warnings.append("country_risk_premium_stale_or_undated")
    provisional = any(
        component.get("status") == "provisional"
        for component in (market["risk_free_rate"], market["equity_risk_premium"],
                          market["country_risk_premium"])
    ) or beta_source != "public_comparables" or capital_source != "public_comparables" or debt_source.endswith("_seed")
    if provisional: warnings.insert(0,"wacc_contains_provisional_components")
    return {
        "status": "available", "engine_version": WACC_VERSION,
        "wacc": round(wacc, 6), "as_of": market.get("as_of"),
        "decision_readiness": "screen_grade" if provisional else "reviewed_market_inputs",
        "components": {
            "risk_free_rate": market["risk_free_rate"],
            "equity_risk_premium": market["equity_risk_premium"],
            "country_risk_premium": market["country_risk_premium"],
            "unlevered_beta": {"value": unlevered, "source": beta_source,
                               "sample_size": (comparable_beta or {}).get("sample_size")},
            "levered_beta": {"value": levered, "formula": "Bu × (1 + (1-T) × D/E)"},
            "size_premium": {"value": size_premium, "source": "arroba_size_policy_seed",
                             "size_band": size},
            "cost_of_equity": {"value": cost_of_equity,
                               "formula": "Rf + beta × ERP + CRP + size premium"},
            "pre_tax_cost_of_debt": {"value": pre_tax_cost_debt, "source": debt_source},
            "after_tax_cost_of_debt": {"value": after_tax_cost_debt},
            "tax_rate": {"value": tax_rate, "source": "arroba_normalized_tax_rate"},
            "target_capital_structure": {"debt_weight": debt_weight,
                                         "equity_weight": equity_weight,
                                         "source": capital_source},
        },
        "warnings": warnings,
        "lineage": {"archetype": archetype, "size_band": size,
                    "market_snapshot_date": market.get("as_of")},
    }
