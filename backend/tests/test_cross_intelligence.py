"""Cross-Intelligence (Sector x Geo) backend tests - iteration 15.

Tests the new /api/v1/public/cross-intelligence/* endpoints,
plus the updated /api/v1/manual (v8.0.0) and /api/v1/docs-info (50 endpoints).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://data-factory-hub.preview.emergentagent.com").rstrip("/")

LOGIN_EMAIL = "daniel@wearebudadvisors.com"
LOGIN_PASSWORD = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")

# Required field sets (per review_request)
SECTORS_IN_FIELDS = {"cnae_section", "cnae_label", "estimated_companies", "borme_events", "concentration_index"}
TERRITORY_FOR_FIELDS = {"geo_id", "geo_name", "geo_level", "borme_events", "concentration_index"}


@pytest.fixture(scope="session")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/v1/auth/login",
                      json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text}")
    return r.json().get("access_token") or r.json().get("token")


# ── Sectors-in (territory → top sectors)
class TestSectorsIn:
    def test_sectors_in_madrid_ccaa_13(self):
        r = requests.get(f"{BASE_URL}/api/v1/public/cross-intelligence/sectors-in/ccaa/13", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["geo_level"] == "ccaa"
        assert data["geo_code"] == "13"
        sectors = data["sectors"]
        assert isinstance(sectors, list)
        assert len(sectors) >= 15, f"Expected ~20 sectors, got {len(sectors)}"
        # Field shape
        first = sectors[0]
        missing = SECTORS_IN_FIELDS - set(first.keys())
        assert not missing, f"Missing fields: {missing} in {first}"
        # Top sectors should include M (professional) and J (tech) in top 5
        top5 = {s["cnae_section"] for s in sectors[:5]}
        assert "M" in top5 or "J" in top5, f"Expected M and/or J in top 5, got {top5}"

    def test_sectors_in_barcelona_province_08(self):
        r = requests.get(f"{BASE_URL}/api/v1/public/cross-intelligence/sectors-in/province/08", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["geo_level"] == "province"
        assert data["geo_code"] == "08"
        assert len(data["sectors"]) >= 10
        assert data.get("geo_name")  # name should resolve

    def test_sectors_in_invalid_geo_level(self):
        r = requests.get(f"{BASE_URL}/api/v1/public/cross-intelligence/sectors-in/country/ES", timeout=15)
        assert r.status_code == 400


# ── Territory-for (sector → top territories)
class TestTerritoryFor:
    def test_territory_for_tech_J_ccaa(self):
        r = requests.get(f"{BASE_URL}/api/v1/public/cross-intelligence/territory-for/J?geo_level=ccaa", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["cnae_section"] == "J"
        territories = data["territories"]
        assert len(territories) >= 5
        # Field shape
        missing = TERRITORY_FOR_FIELDS - set(territories[0].keys())
        assert not missing, f"Missing fields: {missing}"
        # Madrid (13) + Cataluña (09) should lead in tech
        top3 = [t["geo_id"] for t in territories[:3]]
        assert "13" in top3 or "09" in top3, f"Expected Madrid/Cataluña in top3 for Tech, got {top3}"

    def test_territory_for_construction_F_province(self):
        r = requests.get(
            f"{BASE_URL}/api/v1/public/cross-intelligence/territory-for/F?geo_level=province&limit=10",
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["geo_level"] == "province"
        assert len(data["territories"]) <= 10
        assert all(t["geo_level"] == "province" for t in data["territories"])

    def test_tech_concentration_madrid_above_threshold(self):
        """Tech (J) concentration in Madrid should be > 4.0 (per review_request)."""
        r = requests.get(f"{BASE_URL}/api/v1/public/cross-intelligence/territory-for/J?geo_level=ccaa&limit=20", timeout=30)
        assert r.status_code == 200, r.text
        madrid = next((t for t in r.json()["territories"] if t["geo_id"] == "13"), None)
        assert madrid is not None, "Madrid (13) not found in Tech territories"
        ci = madrid["concentration_index"]
        assert ci > 4.0, f"Expected Madrid Tech concentration_index > 4.0, got {ci}"


# ── Heatmap
class TestHeatmap:
    def test_heatmap_all_cells(self):
        r = requests.get(f"{BASE_URL}/api/v1/public/cross-intelligence/heatmap", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        cells = data["cells"]
        # Should be approx 380 cells (20 sections x 19 CCAA)
        assert 300 <= len(cells) <= 420, f"Expected ~380 cells, got {len(cells)}"
        cell = cells[0]
        for f in ("cnae_section", "ccaa_code", "ccaa_name", "borme_events"):
            assert f in cell, f"Missing field {f} in heatmap cell"

    def test_heatmap_filtered_J(self):
        r = requests.get(f"{BASE_URL}/api/v1/public/cross-intelligence/heatmap?cnae_section=J", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["cnae_section_filter"] == "J"
        # Should be at most 19 (one per CCAA)
        assert 1 <= len(data["cells"]) <= 19
        assert all(c["cnae_section"] == "J" for c in data["cells"])


# ── Sync (requires auth)
class TestSync:
    def test_sync_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/v1/public/cross-intelligence/sync", timeout=15)
        assert r.status_code in (401, 403), f"Expected 401/403 without auth, got {r.status_code}"

    def test_sync_with_auth(self, auth_token):
        r = requests.post(
            f"{BASE_URL}/api/v1/public/cross-intelligence/sync",
            headers={"Authorization": f"Bearer {auth_token}"},
            timeout=180,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "completed"
        assert body.get("combinations", 0) > 500


# ── Manual + docs-info updates
class TestManualAndDocsInfo:
    def test_manual_returns_v8(self):
        r = requests.get(f"{BASE_URL}/api/v1/manual", timeout=15)
        assert r.status_code == 200, r.text
        body = r.text
        assert "8.0.0" in body, "Manual should reference version 8.0.0"
        # Some intelligence content should be present
        assert ("Intelligence" in body) or ("Inteligencia" in body)

    def test_docs_info_has_50_endpoints_incl_cross(self):
        r = requests.get(f"{BASE_URL}/api/v1/docs-info", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        endpoints = data.get("endpoints", [])
        assert len(endpoints) == 50, f"Expected 50 endpoints, got {len(endpoints)}"
        paths = [e["path"] for e in endpoints]
        # Cross-intelligence endpoints must be listed
        assert any("/cross-intelligence/sectors-in/" in p for p in paths)
        assert any("/cross-intelligence/territory-for/" in p for p in paths)
        assert any("/cross-intelligence/heatmap" in p for p in paths)
