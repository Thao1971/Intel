"""Pure, deterministic Iberinform cohort calibration for valuation drivers."""
from __future__ import annotations

import hashlib
import heapq
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .conventions import number, operating_working_capital
from .sector_rules import resolve_sector_rule, size_band

CALIBRATION_VERSION = "sector-calibration-v1"
MIN_MEDIAN_SAMPLE = 20
MIN_BAND_SAMPLE = 40
HIGH_CONFIDENCE_SAMPLE = 150
MAX_METRIC_SAMPLE = 20_000
METRICS = ("revenue_growth", "ebit_margin", "depreciation_pct_revenue",
           "capex_pct_revenue", "nwc_pct_revenue")

def percentile(values: List[float], probability: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = int(position), min(int(position) + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction

def winsorize(values: List[float], low: float = .05, high: float = .95) -> Tuple[List[float], Dict[str, Any]]:
    if not values:
        return [], {"lower_bound": None, "upper_bound": None, "adjusted": 0}
    lower, upper = percentile(values, low), percentile(values, high)
    adjusted = [max(lower, min(upper, value)) for value in values]
    changed = sum(original != new for original, new in zip(values, adjusted))
    return adjusted, {"lower_bound": lower, "upper_bound": upper, "adjusted": changed,
                      "adjusted_pct": changed / len(values)}

def _ratio(row: Mapping[str, Any], numerator: str, absolute: bool = False) -> Optional[float]:
    revenue, value = number(row.get("revenue")), number(row.get(numerator))
    if revenue is None or revenue <= 0 or value is None:
        return None
    return (abs(value) if absolute else value) / revenue

def _operating_nwc(row: Mapping[str, Any]) -> Optional[float]:
    direct=number(row.get("operating_working_capital"))
    if direct is not None:
        return direct
    return operating_working_capital(
        row.get("trade_debtors"),row.get("inventories"),row.get("suppliers"))

def _growth(series: List[Mapping[str, Any]]) -> Optional[float]:
    ordered = sorted(
        [(row.get("year"), number(row.get("revenue"))) for row in series
         if row.get("year") is not None and number(row.get("revenue")) not in (None, 0)],
        key=lambda item: item[0],
    )
    ordered = [(year, revenue) for year, revenue in ordered if revenue and revenue > 0]
    if len(ordered) < 2:
        return None
    first_year, first = ordered[0]
    last_year, last = ordered[-1]
    years = last_year - first_year
    if years <= 0:
        return None
    return (last / first) ** (1 / years) - 1

_COMPLETENESS_FIELDS = ("revenue", "operating_income", "depreciation", "cf_capex",
                        "trade_debtors", "inventories", "suppliers", "current_assets",
                        "current_liabilities")

def sanitize_series(raw_series: Iterable[Mapping[str, Any]]) -> Tuple[List[Mapping[str, Any]], Dict[str, int]]:
    """Choose one coherent basis and one most-complete observation per fiscal year."""
    rows=list(raw_series or [])
    invalid=sum(not isinstance(row.get("year"),int) for row in rows)
    rows=[row for row in rows if isinstance(row.get("year"),int)]
    bases=[row.get("basis") for row in rows if row.get("basis")]
    selected=("individual" if "individual" in bases else
              (max(set(bases),key=bases.count) if bases else None))
    mixed=sum(row.get("basis") not in (None,selected) for row in rows) if selected else 0
    if selected:
        rows=[row for row in rows if row.get("basis") in (None,selected)]
    by_year: Dict[int,Mapping[str,Any]]={}
    duplicates=0
    for row in rows:
        year=row["year"]
        if year in by_year:
            duplicates+=1
            old=by_year[year]
            old_score=sum(old.get(field) is not None for field in _COMPLETENESS_FIELDS)
            new_score=sum(row.get(field) is not None for field in _COMPLETENESS_FIELDS)
            if new_score>old_score:
                by_year[year]=row
        else:
            by_year[year]=row
    return (sorted(by_year.values(),key=lambda row:row["year"],reverse=True),
            {"invalid_year_rows":invalid,"mixed_basis_rows":mixed,
             "duplicate_financial_years":duplicates})

def company_observation(company: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    series, data_quality = sanitize_series(company.get("series") or [])
    if not series:
        return None
    latest = sorted(series, key=lambda row: row.get("year") or 0, reverse=True)[0]
    revenue = number(latest.get("revenue"))
    if revenue is None or revenue <= 0:
        return None
    cnae = company.get("cnae_code")
    rule = resolve_sector_rule(cnae, revenue)
    values: Dict[str, Optional[float]] = {
        "revenue_growth": _growth(series),
        "ebit_margin": median(v for row in series if (v := _ratio(row, "operating_income")) is not None)
                       if any(_ratio(row, "operating_income") is not None for row in series) else None,
        "depreciation_pct_revenue": median(v for row in series if (v := _ratio(row, "depreciation", True)) is not None)
                                    if any(_ratio(row, "depreciation", True) is not None for row in series) else None,
        "capex_pct_revenue": median(v for row in series if (v := _ratio(row, "cf_capex", True)) is not None)
                             if any(_ratio(row, "cf_capex", True) is not None for row in series) else None,
        "nwc_pct_revenue": median(v for row in series
                                  if (v := ((_operating_nwc(row) / number(row.get("revenue")))
                                            if _operating_nwc(row) is not None
                                            and number(row.get("revenue")) not in (None, 0) else None)) is not None)
                           if any(_operating_nwc(row) is not None
                                  and number(row.get("revenue")) not in (None, 0) for row in series) else None,
    }
    return {
        "company_id": company.get("cif_normalized") or company.get("master_id"),
        "cnae_division": rule["cnae_division"],
        "archetype": rule["archetype"],
        "size_band": size_band(revenue),
        "latest_year": latest.get("year"),
        "latest_revenue": revenue,
        "metrics": values,
        "data_quality": data_quality,
    }

@dataclass
class MetricSample:
    limit: int = MAX_METRIC_SAMPLE
    valid_count: int = 0
    heap: List[Tuple[int, float]] = field(default_factory=list)

    def add(self, company_id: str, metric: str, value: Optional[float]) -> None:
        if value is None:
            return
        self.valid_count += 1
        priority = int.from_bytes(
            hashlib.sha256(f"{company_id}|{metric}".encode()).digest()[:8], "big")
        item = (-priority, float(value))
        if len(self.heap) < self.limit:
            heapq.heappush(self.heap, item)
        elif priority < -self.heap[0][0]:
            heapq.heapreplace(self.heap, item)

    def values(self) -> List[float]:
        return [value for _, value in self.heap]

@dataclass
class Cohort:
    key: str
    scope: Dict[str, Any]
    companies: set = field(default_factory=set)
    years: set = field(default_factory=set)
    metrics: Dict[str, MetricSample] = field(
        default_factory=lambda: {metric: MetricSample() for metric in METRICS})

    def add(self, observation: Mapping[str, Any]) -> None:
        company_id = str(observation.get("company_id") or "")
        if not company_id:
            return
        self.companies.add(company_id)
        if observation.get("latest_year") is not None:
            self.years.add(observation["latest_year"])
        for metric, value in observation["metrics"].items():
            self.metrics[metric].add(company_id, metric, value)

def _cohort_keys(observation: Mapping[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    archetype, division, band = observation["archetype"], observation["cnae_division"], observation["size_band"]
    keys = [
        (f"archetype:{archetype}|size:{band}", {"level": "archetype_size", "archetype": archetype, "size_band": band}),
        (f"archetype:{archetype}|size:all", {"level": "archetype", "archetype": archetype, "size_band": "all"}),
    ]
    if division:
        keys += [
            (f"division:{division}|size:{band}", {"level": "division_size", "cnae_division": division, "size_band": band}),
            (f"division:{division}|size:all", {"level": "division", "cnae_division": division, "size_band": "all"}),
        ]
    return keys

class CalibrationAccumulator:
    def __init__(self, cutoff_date: Optional[str] = None,
                 sample_limit: int = MAX_METRIC_SAMPLE):
        self.cutoff_date = cutoff_date or date.today().isoformat()
        self.sample_limit = sample_limit
        self.cohorts: Dict[str, Cohort] = {}
        self.population_initial = 0
        self.population_eligible = 0
        self.exclusions = {"no_financials": 0, "non_positive_latest_revenue": 0}
        self.data_quality_adjustments = {"invalid_year_rows": 0, "mixed_basis_rows": 0,
                                         "duplicate_financial_years": 0}

    def add_company(self, company: Mapping[str, Any]) -> None:
        self.population_initial += 1
        observation = company_observation(company)
        if observation is None:
            if not company.get("series"):
                self.exclusions["no_financials"] += 1
            else:
                self.exclusions["non_positive_latest_revenue"] += 1
            return
        self.population_eligible += 1
        for key, value in observation.get("data_quality", {}).items():
            self.data_quality_adjustments[key] += value
        for key, scope in _cohort_keys(observation):
            cohort = self.cohorts.setdefault(key, Cohort(key, scope))
            for sample in cohort.metrics.values():
                sample.limit = self.sample_limit
            cohort.add(observation)

    def result(self) -> Dict[str, Any]:
        snapshots = []
        for key, cohort in sorted(self.cohorts.items()):
            parameters = {}
            for metric, sample in cohort.metrics.items():
                raw = sample.values()
                adjusted, treatment = winsorize(raw)
                n = sample.valid_count
                parameters[metric] = {
                    "p25": percentile(adjusted, .25) if n >= MIN_BAND_SAMPLE else None,
                    "median": percentile(adjusted, .50) if n >= MIN_MEDIAN_SAMPLE else None,
                    "p75": percentile(adjusted, .75) if n >= MIN_BAND_SAMPLE else None,
                    "sample_size": n,
                    "sampled_observations": len(raw),
                    "winsorization": treatment,
                    "publishable_median": n >= MIN_MEDIAN_SAMPLE,
                    "publishable_band": n >= MIN_BAND_SAMPLE,
                }
            sample_sizes = [value["sample_size"] for value in parameters.values()]
            min_sample = min(sample_sizes) if sample_sizes else 0
            snapshots.append({
                "cohort_key": key,
                "scope": cohort.scope,
                "calibration_status": "candidate_iberinform",
                "decision_readiness": "review_required",
                "parameters": parameters,
                "quality": {
                    "companies": len(cohort.companies),
                    "minimum_metric_sample": min_sample,
                    "eligible_for_review": any(v["publishable_median"] for v in parameters.values()),
                    "high_confidence_sample": min_sample >= HIGH_CONFIDENCE_SAMPLE,
                    "years": sorted(cohort.years),
                },
            })
        return {
            "pipeline_version": CALIBRATION_VERSION,
            "cutoff_date": self.cutoff_date,
            "source": "Iberinform",
            "status": "candidate",
            "population_initial": self.population_initial,
            "population_eligible": self.population_eligible,
            "exclusions": self.exclusions,
            "data_quality_adjustments": self.data_quality_adjustments,
            "cohorts": snapshots,
        }

def calibrate_companies(companies: Iterable[Mapping[str, Any]], cutoff_date: Optional[str] = None,
                        sample_limit: int = MAX_METRIC_SAMPLE) -> Dict[str, Any]:
    accumulator = CalibrationAccumulator(cutoff_date, sample_limit)
    for company in companies:
        accumulator.add_company(company)
    return accumulator.result()
