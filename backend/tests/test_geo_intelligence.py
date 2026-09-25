"""Geo Intelligence — Backend API Test Suite

Tests:
- Catalog endpoints (19 CCAA, 52 provinces)
- Overview / rankings (top-dynamic, largest, fastest-growing, most-active)
- Drill-down (CCAA → provinces, province detail)
- Card structure validation
- Auth-gated sync endpoint
- Contract version 1.0
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://data-factory-hub.preview.emergentagent.com").rstrip("/")
LOGIN_EMAIL = "daniel@wearebudadvisors.com"
LOGIN_PASSWORD = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")
GEO = f"{BASE_URL}/api/v1/public/geo-intelligence"

REQUIRED_CARD_FIELDS = [
    "geo_id", "geo_level", "geo_name",
    "size_score", "growth_score", "activity_score", "dynamism_score",
    "trend_direction", "signal", "active_companies", "borme_activity_count",
]


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def auth_token(api):
    payload = {"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD}
    for path in ["/api/auth/login", "/api/v1/auth/login", "/api/login"]:
        try:
            r = api.post(f"{BASE_URL}{path}", json=payload, timeout=15)
            if r.status_code == 200:
                d = r.json()
                token = d.get("token") or d.get("access_token") or (d.get("data") or {}).get("token")
                if token:
                    return token
        except Exception:
            continue
    return None


# ───────────────────────── CATALOG ─────────────────────────
class TestCatalog:
    def test_catalog(self, api):
        r = api.get(f"{GEO}/catalog", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("contract_version") == "1.0"
        assert d.get("total_ccaa") == 19, f"Expected 19 CCAA, got {d.get('total_ccaa')}"
        assert d.get("total_provinces") == 52, f"Expected 52 provinces, got {d.get('total_provinces')}"
        catalog = d.get("catalog", [])
        assert len(catalog) == 19
        # Each CCAA has provinces
        for c in catalog:
            assert "provinces" in c
        total_provs = sum(len(c["provinces"]) for c in catalog)
        assert total_provs == 52


# ───────────────────────── OVERVIEW ─────────────────────────
class TestOverview:
    def test_overview_default_ccaa(self, api):
        r = api.get(f"{GEO}/overview", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("contract_version") == "1.0"
        assert d.get("level") == "ccaa"
        territories = d.get("territories", [])
        assert d.get("count") == 19, f"Expected 19 CCAA, got {d.get('count')}"
        assert len(territories) == 19
        # Sorted desc by dynamism_score
        scores = [t["dynamism_score"] for t in territories]
        assert scores == sorted(scores, reverse=True), "Not sorted by dynamism_score desc"
        # Madrid (CCAA 13) should be at the top
        assert territories[0]["geo_id"] == "13", f"Expected Madrid (13) at top, got {territories[0]['geo_id']}"
        # Card fields
        for field in REQUIRED_CARD_FIELDS:
            assert field in territories[0], f"Missing card field: {field}"
        assert territories[0]["geo_level"] == "ccaa"

    def test_overview_province(self, api):
        r = api.get(f"{GEO}/overview?level=province", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("level") == "province"
        assert d.get("count") == 52, f"Expected 52 provinces, got {d.get('count')}"
        territories = d.get("territories", [])
        assert len(territories) == 52
        for field in REQUIRED_CARD_FIELDS:
            assert field in territories[0]
        assert territories[0]["geo_level"] == "province"


# ───────────────────────── RANKINGS ─────────────────────────
class TestRankings:
    def test_top_dynamic_ccaa(self, api):
        r = api.get(f"{GEO}/top-dynamic?limit=5", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ranking_by") == "dynamism_score"
        assert d.get("level") == "ccaa"
        t = d.get("territories", [])
        assert len(t) == 5
        scores = [x["dynamism_score"] for x in t]
        assert scores == sorted(scores, reverse=True)
        assert all(s > 0 for s in scores)

    def test_top_dynamic_province(self, api):
        r = api.get(f"{GEO}/top-dynamic?level=province&limit=5", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("level") == "province"
        t = d.get("territories", [])
        assert len(t) == 5
        scores = [x["dynamism_score"] for x in t]
        assert scores == sorted(scores, reverse=True)

    def test_largest_ccaa(self, api):
        r = api.get(f"{GEO}/largest?limit=5", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ranking_by") == "size_score"
        t = d.get("territories", [])
        assert len(t) == 5
        scores = [x["size_score"] for x in t]
        assert scores == sorted(scores, reverse=True)

    def test_fastest_growing_ccaa(self, api):
        r = api.get(f"{GEO}/fastest-growing?limit=5", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ranking_by") == "growth_score"
        t = d.get("territories", [])
        assert len(t) == 5
        scores = [x["growth_score"] for x in t]
        assert scores == sorted(scores, reverse=True)

    def test_most_active_province(self, api):
        r = api.get(f"{GEO}/most-active?level=province&limit=5", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ranking_by") == "activity_score"
        assert d.get("level") == "province"
        t = d.get("territories", [])
        assert len(t) == 5
        scores = [x["activity_score"] for x in t]
        assert scores == sorted(scores, reverse=True)


# ───────────────────────── DRILL-DOWN ─────────────────────────
class TestDrillDown:
    def test_ccaa_madrid(self, api):
        r = api.get(f"{GEO}/ccaa/13", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        ccaa = d.get("ccaa", {})
        assert ccaa.get("geo_id") == "13"
        assert ccaa.get("geo_level") == "ccaa"
        provinces = d.get("provinces", [])
        assert d.get("provinces_count") == 1, f"Madrid CCAA should have 1 province, got {d.get('provinces_count')}"
        assert len(provinces) == 1
        assert provinces[0]["geo_id"] == "28", f"Madrid province should be 28, got {provinces[0]['geo_id']}"

    def test_ccaa_andalucia(self, api):
        r = api.get(f"{GEO}/ccaa/01", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("provinces_count") == 8, f"Andalucía should have 8 provinces, got {d.get('provinces_count')}"
        assert len(d.get("provinces", [])) == 8

    def test_province_madrid(self, api):
        r = api.get(f"{GEO}/province/28", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        p = d.get("province", {})
        assert p.get("geo_id") == "28"
        assert p.get("geo_level") == "province"
        # Madrid should have highest BORME activity (11704)
        assert p.get("borme_activity_count", 0) == 11704, f"Madrid BORME should be 11704, got {p.get('borme_activity_count')}"

    def test_province_barcelona(self, api):
        r = api.get(f"{GEO}/province/08", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        p = d.get("province", {})
        assert p.get("geo_id") == "08"
        assert p.get("geo_level") == "province"

    def test_ccaa_invalid_404(self, api):
        r = api.get(f"{GEO}/ccaa/99", timeout=15)
        assert r.status_code == 404, f"Expected 404, got {r.status_code}"

    def test_province_invalid_404(self, api):
        r = api.get(f"{GEO}/province/99", timeout=15)
        assert r.status_code == 404, f"Expected 404, got {r.status_code}"


# ───────────────────────── BORME ACTIVITY ─────────────────────────
class TestBormeMapping:
    def test_madrid_highest_borme_among_provinces(self, api):
        r = api.get(f"{GEO}/overview?level=province", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        territories = d.get("territories", [])
        # Madrid (28) should have the highest borme_activity_count
        max_borme = max(territories, key=lambda x: x.get("borme_activity_count", 0))
        assert max_borme["geo_id"] == "28", f"Expected Madrid (28) to have highest BORME, got {max_borme['geo_id']} with {max_borme.get('borme_activity_count')}"
        assert max_borme["borme_activity_count"] == 11704


# ───────────────────────── SYNC (AUTH) ─────────────────────────
class TestSync:
    def test_sync_requires_auth(self, api):
        r = api.post(f"{GEO}/sync", timeout=15)
        assert r.status_code in (401, 403), f"Expected 401/403 without auth, got {r.status_code}"

    def test_sync_with_auth(self, api, auth_token):
        if not auth_token:
            pytest.skip("No auth token available")
        h = {"Authorization": f"Bearer {auth_token}"}
        r = api.post(f"{GEO}/sync", headers=h, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ccaa") == 19, f"Expected ccaa=19, got {d.get('ccaa')}"
        assert d.get("provinces") == 52, f"Expected provinces=52, got {d.get('provinces')}"
