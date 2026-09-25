"""Smoke tests — Sprint 2 Financial Intelligence Engine.

Builds master from the sample, then validates the full engine profile + API (service key).
"""
import os
import subprocess
import requests
import pytest
from smoke_loop import run_async as _run

SAMPLE_DIR = "/app/backend/tests/fixtures/iberinform_sample"
FI = "/api/v1/financial-intelligence"
SVC = {"X-API-Key": os.environ.get("ARROBA_SERVICE_API_KEY",
                                   "as_TGx2m4UaXc25lsYv_Ep5_w7niWJCA3q-SjU4I9mSmvk")}

pytestmark = pytest.mark.skipif(
    not os.path.isdir(SAMPLE_DIR), reason="Iberinform sample fixture not present")


@pytest.fixture(scope="module", autouse=True)
def _setup():
    subprocess.run(["sudo", "supervisorctl", "stop", "data_layer_worker"], capture_output=True)

    async def go():
        from database import db
        from services.data_layer.ingestion.iberinform_ingest import ingest_directory
        from services.data_layer.master.master_builder import rebuild_master
        if await db.master_companies.count_documents({"financials.latest.revenue": {"$ne": None}}) < 50:
            await ingest_directory(SAMPLE_DIR, source_version="20260519")
            await rebuild_master(scope="full")
    _run(go())
    yield
    subprocess.run(["sudo", "supervisorctl", "start", "data_layer_worker"], capture_output=True)


def _a_master_id():
    async def go():
        from database import db
        d = await db.master_companies.find_one({"financials.latest.revenue": {"$ne": None}},
                                               {"_id": 0, "master_id": 1})
        return d["master_id"]
    return _run(go())


def test_engine_profile_complete():
    from services.engines.financial.engine import analyze
    p = _run(analyze(_a_master_id()))
    for k in ("statements", "kpis", "ratios", "evolution", "financial_quality",
              "comparables", "valuation", "assessment", "explainability"):
        assert k in p, f"missing {k}"
    assert p["engine_version"] == "financial-intelligence-v1"
    assert p["financial_quality"]["ai_used"] is False
    assert p["explainability"]["ai_used"] is False


def test_kpis_and_ratios_coherent():
    from services.engines.financial.engine import analyze
    p = _run(analyze(_a_master_id()))
    k = p["kpis"]
    assert k["revenue"] and k["revenue"] > 0
    # ebitda_margin == ebitda/revenue (internal consistency)
    if k["ebitda"] and k["ebitda_margin"] is not None:
        assert abs(k["ebitda_margin"] - k["ebitda"] / k["revenue"]) < 0.001
    # every ratio carries full explainability
    for key, r in p["ratios"].items():
        assert {"value", "name", "formula", "explanation", "source", "available"} <= set(r.keys())


def test_quality_score_rules_based():
    from services.engines.financial.engine import analyze
    p = _run(analyze(_a_master_id()))
    q = p["financial_quality"]
    assert 0 <= q["score"] <= 100
    assert q["method"] == "rules_based"
    assert sum(r["points"] for r in q["rules"]) == q["score"]   # score == sum of passed rules


def test_valuation_traceable():
    from services.engines.financial.engine import analyze
    p = _run(analyze(_a_master_id()))
    v = p["valuation"]
    assert v["method"] in ("ev_ebitda", "ev_revenue", "book_value", "insufficient_data")
    assert "hypotheses" in v and "confidence" in v and "lineage" in v
    if v["method"] == "ev_ebitda":
        assert v["multiple_basis"] in ("market_observed", "observed_public_adjusted",
                                         "inferred_reference")
        if v["multiple_basis"] == "observed_public_adjusted":
            assert v["multiple_benchmark"]["multiple"] == v["unadjusted_multiple"]
            assert v["private_company_adjustment"]["adjusted_multiple"] == v["multiple"]
            assert "unavailable_evidence" in v["private_company_adjustment"]


def test_comparables_structural_no_embeddings():
    from services.engines.financial.engine import analyze
    p = _run(analyze(_a_master_id()))
    assert p["comparables"]["embeddings_used"] is False
    assert "cnae_section" in p["comparables"]["criteria"]


# ── API contract (own engine API, service-key auth) ──
def test_api_requires_service_key(base_url):
    r = requests.post(f"{base_url}{FI}/analyze", json={"identifier": "x"}, timeout=20)
    assert r.status_code == 401


def test_api_analyze_and_valuation(base_url):
    mid = _a_master_id()
    r = requests.post(f"{base_url}{FI}/analyze", headers=SVC, json={"identifier": mid}, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["master_id"] == mid and "kpis" in d and "valuation" in d

    v = requests.post(f"{base_url}{FI}/valuation", headers=SVC, json={"identifier": mid}, timeout=30)
    assert v.status_code == 200 and "valuation" in v.json()

    c = requests.get(f"{base_url}{FI}/ratios/catalog", headers=SVC, timeout=20)
    assert c.status_code == 200 and len(c.json()["ratios"]) >= 10

    nf = requests.post(f"{base_url}{FI}/analyze", headers=SVC, json={"identifier": "nope"}, timeout=20)
    assert nf.status_code == 404
