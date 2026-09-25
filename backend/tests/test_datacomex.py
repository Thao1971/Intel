"""DataComex Intelligence backend tests."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://data-factory-hub.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api/v1/datacomex"

EMAIL = "daniel@wearebudadvisors.com"
PASSWORD = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE_URL}/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    return data.get("token") or data.get("access_token")


@pytest.fixture(scope="session")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# Dashboard
class TestDashboard:
    def test_dashboard_returns_kpis(self, headers):
        r = requests.get(f"{API}/dashboard", headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "kpis" in data
        k = data["kpis"]
        for key in ["raw_records", "trade_metrics", "signals_active", "cnae_mappings",
                    "total_exports_eur", "total_imports_eur", "trade_balance_eur"]:
            assert key in k, f"Missing KPI {key}"
        assert "top_growing_cnae" in data
        assert "top_declining_cnae" in data
        assert "signals" in data
        assert "last_sync" in data
        assert k["cnae_mappings"] >= 100, f"Expected >=100 mappings, got {k['cnae_mappings']}"


# Mappings list
class TestMappings:
    def test_list_returns_mappings(self, headers):
        r = requests.get(f"{API}/mappings", headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "mappings" in data
        assert "count" in data
        assert data["count"] >= 100, f"Expected >=100, got {data['count']}"
        sample = data["mappings"][0]
        for k in ["taric_code", "cnae_code", "confidence_score", "validated_by_human"]:
            assert k in sample, f"Missing key {k} in mapping"

    def test_taric_03_has_n_to_m(self, headers):
        r = requests.get(f"{API}/mappings", headers=headers, timeout=30)
        assert r.status_code == 200
        ms = [m for m in r.json()["mappings"] if m["taric_code"] == "03"]
        assert len(ms) == 2, f"TARIC 03 should map to 2 CNAEs, got {len(ms)}: {ms}"
        cnaes = sorted([m["cnae_code"] for m in ms])
        assert cnaes == ["03", "10"], f"Expected ['03','10'], got {cnaes}"

    def test_approve_mapping(self, headers):
        r = requests.post(f"{API}/mappings/01/01/approve", headers=headers, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"
        # Verify validated_by_human is True
        r2 = requests.get(f"{API}/mappings?validated=true", headers=headers, timeout=20)
        assert r2.status_code == 200
        approved = [m for m in r2.json()["mappings"] if m["taric_code"] == "01" and m["cnae_code"] == "01"]
        assert len(approved) == 1, "Approved mapping not found in validated=true filter"
        assert approved[0]["validated_by_human"] is True

    def test_reject_then_rebuild(self, headers):
        # Reject 99/32
        r = requests.post(f"{API}/mappings/99/32/reject", headers=headers, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "rejected"
        # Confirm deletion
        r2 = requests.get(f"{API}/mappings", headers=headers, timeout=30)
        rejected = [m for m in r2.json()["mappings"] if m["taric_code"] == "99" and m["cnae_code"] == "32"]
        assert len(rejected) == 0, "Mapping not deleted"
        # Rebuild restores
        r3 = requests.post(f"{API}/rebuild-mappings", headers=headers, timeout=60)
        assert r3.status_code == 200, r3.text
        assert r3.json()["status"] == "completed"
        assert r3.json()["mappings"] >= 100
        # Verify 99/32 restored
        r4 = requests.get(f"{API}/mappings", headers=headers, timeout=30)
        restored = [m for m in r4.json()["mappings"] if m["taric_code"] == "99" and m["cnae_code"] == "32"]
        assert len(restored) == 1, "Mapping not restored after rebuild"

    def test_reject_returns_404_after(self, headers):
        # Reject endpoint always returns success even if not found (idempotent)
        r = requests.post(f"{API}/mappings/XX/YY/reject", headers=headers, timeout=20)
        assert r.status_code == 200


# Trade data endpoints
class TestTradeData:
    def test_exports(self, headers):
        r = requests.get(f"{API}/exports", headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "exports" in data
        assert "count" in data

    def test_imports(self, headers):
        r = requests.get(f"{API}/imports", headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        assert "imports" in r.json()

    def test_trade_balance(self, headers):
        r = requests.get(f"{API}/trade-balance", headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ["total_exports_eur", "total_imports_eur", "trade_balance_eur", "by_chapter"]:
            assert k in data, f"Missing {k}"

    def test_signals(self, headers):
        r = requests.get(f"{API}/signals", headers=headers, timeout=30)
        assert r.status_code == 200
        assert "signals" in r.json()


# Auth requirement
class TestAuth:
    def test_dashboard_requires_auth(self):
        r = requests.get(f"{API}/dashboard", timeout=20)
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"

    def test_sync_requires_auth(self):
        r = requests.post(f"{API}/sync", timeout=20)
        assert r.status_code in (401, 403)

    def test_rebuild_metrics_requires_auth(self):
        r = requests.post(f"{API}/rebuild-metrics", timeout=20)
        assert r.status_code in (401, 403)


# Admin endpoints  
class TestAdminEndpoints:
    def test_rebuild_metrics(self, headers):
        r = requests.post(f"{API}/rebuild-metrics", headers=headers, timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"

    def test_rebuild_signals(self, headers):
        r = requests.post(f"{API}/rebuild-signals", headers=headers, timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "completed"
