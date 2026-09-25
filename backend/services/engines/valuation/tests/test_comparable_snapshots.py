from services.engines.valuation.comparable_snapshots import build_comparable_snapshots

def test_snapshot_calculates_percentiles_and_discloses_exclusions():
    rows=[
      {"name":"A","isin":"A","archetype":"media_content","ev_ebitda":6},
      {"name":"B","isin":"B","archetype":"media_content","ev_ebitda":8},
      {"name":"C","isin":"C","archetype":"media_content","ev_ebitda":10},
      {"name":"D","isin":"D","archetype":"media_content","ev_ebitda":-2},
      {"name":"E","isin":"E","archetype":"media_content"},
    ]
    result=build_comparable_snapshots(rows,provider="marketscreener",region="spain",as_of="2025-12-31")
    metric=result["snapshots"][0]["metrics"]["ev_ebitda"]
    assert metric["p25"]==7 and metric["median"]==8 and metric["p75"]==9
    assert metric["sample_size"]==3 and metric["publishable"] is True
    assert {x["reason"] for x in metric["excluded"]}=={"non_positive_or_outlier","missing_metric"}

def test_sparse_metric_is_not_publishable():
    result=build_comparable_snapshots(
      [{"name":"A","archetype":"retail","ev_ebit":10}],
      provider="marketscreener",region="spain",as_of="2025-12-31")
    assert result["snapshots"][0]["metrics"]["ev_ebit"]["publishable"] is False
