"""Backend tests for Economic Intelligence Layer and Taxonomy Intelligence Layer."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://data-factory-hub.preview.emergentagent.com").rstrip("/")
EMAIL = "daniel@wearebudadvisors.com"
PASSWORD = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")


@pytest.fixture(scope="session")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"Login failed {r.status_code}: {r.text}")
    data = r.json()
    return data.get("token") or data.get("access_token")


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


# ──────────────── Economic Intelligence ────────────────

class TestEconomicIntelligence:
    def test_cnae_62_profile(self):
        r = requests.get(f"{BASE_URL}/api/v1/economic-intelligence/cnae/62", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["cnae_code"] == "62"
        assert "cnae_label" in d
        # core fields exist (may be None depending on data, but key must be present)
        for key in ["revenue", "ebitda", "employment", "borme_events",
                    "procurement_contracts", "revenue_growth", "trend", "signals",
                    "sources_available", "total_metrics"]:
            assert key in d, f"missing key {key}"
        sources = set(d["sources_available"])
        # CNAE 62 should have 4 sources
        for s in ["iberinform", "ine", "borme", "procurement"]:
            assert s in sources, f"source {s} missing in {sources}"

    def test_cnae_62_revenue_growth_has_yoy(self):
        r = requests.get(f"{BASE_URL}/api/v1/economic-intelligence/cnae/62", timeout=30)
        d = r.json()
        rg = d.get("revenue_growth")
        assert rg is not None, "revenue_growth should not be None for CNAE 62"
        assert "yoy_pct" in rg

    def test_cnae_10_food_industry(self):
        r = requests.get(f"{BASE_URL}/api/v1/economic-intelligence/cnae/10", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        sources = set(d["sources_available"])
        assert "iberinform" in sources, f"iberinform missing for CNAE 10. Got {sources}"

    def test_cnae_68_borme_events(self):
        r = requests.get(f"{BASE_URL}/api/v1/economic-intelligence/cnae/68", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        be = d.get("borme_events")
        assert be is not None, "borme_events should be present for CNAE 68"
        assert be["value"] > 400, f"borme_events expected > 400, got {be['value']}"

    def test_cnae_nonexistent_returns_404(self):
        r = requests.get(f"{BASE_URL}/api/v1/economic-intelligence/cnae/XX", timeout=30)
        assert r.status_code == 404

    def test_overview_top_cnae(self):
        r = requests.get(f"{BASE_URL}/api/v1/economic-intelligence/overview?limit=20", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "cnae_divisions" in d
        assert d["count"] > 0
        # CNAE 62 should have 4 sources
        cnae_62 = next((c for c in d["cnae_divisions"] if c["cnae_code"] == "62"), None)
        assert cnae_62 is not None, "CNAE 62 should appear in overview top list"
        assert cnae_62["sources_count"] == 4, f"CNAE 62 expected 4 sources, got {cnae_62['sources_count']}"

    def test_signals_endpoint(self):
        r = requests.get(f"{BASE_URL}/api/v1/economic-intelligence/signals?limit=200", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        signals = d.get("signals", [])
        assert d["count"] >= 20, f"expected ~23 signals, got {d['count']}"
        # Validate signal structure
        assert all("signal_type" in s and "confidence" in s and "sources_used" in s for s in signals)
        # Required signal types
        signal_types = {s["signal_type"] for s in signals}
        for required in ["high_corporate_activity", "employment_growth", "public_demand"]:
            assert required in signal_types, f"missing signal type {required}. Got: {signal_types}"

    def test_stats_endpoint(self):
        r = requests.get(f"{BASE_URL}/api/v1/economic-intelligence/stats", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_metrics"] >= 1800, f"expected ~1924 metrics, got {d['total_metrics']}"
        assert d["cnae_codes_covered"] >= 80, f"expected ~88 CNAE, got {d['cnae_codes_covered']}"
        by_source = d.get("by_source", {})
        # 5 sources expected (iberinform, ine, borme, procurement, banco_espana)
        for s in ["iberinform", "ine", "borme", "procurement", "banco_espana"]:
            assert s in by_source, f"source {s} missing from by_source: {list(by_source.keys())}"
        assert len(by_source) >= 5

    def test_rebuild_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/v1/economic-intelligence/rebuild", timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_rebuild_with_auth(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/v1/economic-intelligence/rebuild", headers=auth_headers, timeout=180)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "completed"
        assert "metrics" in d and "signals" in d
        assert d["metrics"]["total_metrics"] > 0
        assert d["signals"]["signals_generated"] > 0


# ──────────────── Taxonomy Intelligence ────────────────

class TestTaxonomyIntelligence:
    def test_stats(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/v1/taxonomy-intelligence/stats", headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_mappings"] >= 140, f"expected ~143, got {d['total_mappings']}"
        assert d["auto_approved"] >= 80, f"expected ~83 auto-approved, got {d['auto_approved']}"

    def test_resolve_taric_87(self):
        r = requests.get(f"{BASE_URL}/api/v1/taxonomy-intelligence/resolve/taric/87", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["taxonomy"] == "taric"
        assert d["code"] == "87"
        mappings = d.get("cnae_mappings", [])
        assert len(mappings) >= 1
        m = next((x for x in mappings if x["cnae"] == "29"), None)
        assert m is not None, f"expected mapping to CNAE 29 for TARIC 87, got {mappings}"
        assert m["confidence"] >= 0.9
        assert m["status"] == "auto_approved"

    def test_audit_returns_only_pending_and_low(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/v1/taxonomy-intelligence/audit?limit=500", headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        statuses = {it["status"] for it in d["items"]}
        assert statuses.issubset({"pending_review", "low_confidence"}), f"unexpected statuses: {statuses}"
