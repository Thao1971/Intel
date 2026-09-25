"""Iberinform admin endpoints + Sector/Geo Intelligence post-import verification."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://data-factory-hub.preview.emergentagent.com").rstrip("/")
EMAIL = "daniel@wearebudadvisors.com"
PASSWORD = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")


# ---- Fixtures ----
@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def token(api):
    r = api.post(f"{BASE_URL}/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"Login failed: {r.status_code} {r.text[:200]}")
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="session")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---- Iberinform admin: stats ----
class TestIberinformStats:
    def test_stats_requires_auth(self, api):
        r = api.get(f"{BASE_URL}/api/v1/admin/iberinform/stats")
        assert r.status_code in (401, 403)

    def test_stats_returns_expected_counts(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/v1/admin/iberinform/stats", headers=auth_headers)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        ib = data["iberinform"]
        assert ib["total_companies"] == 5000, f"Expected 5000 companies, got {ib['total_companies']}"
        assert ib["total_fiscal_years"] == 11657, f"Expected 11657 fiscal years, got {ib['total_fiscal_years']}"
        assert ib["cnae_divisions_covered"] == 83, f"Expected 83 CNAE divisions, got {ib['cnae_divisions_covered']}"
        assert ib["provinces_covered"] == 52, f"Expected 52 provinces, got {ib['provinces_covered']}"
        # Years 2022-2024
        years = ib["years_covered"]
        assert set(years) >= {2022, 2023, 2024}, f"Years covered: {years}"

    def test_stats_companies_master_coverage(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/v1/admin/iberinform/stats", headers=auth_headers)
        assert r.status_code == 200
        m = r.json()["companies_master"]
        # 5000 imported + 265 existing agencies = 5265 entities
        assert m["total"] >= 5000
        assert m["cnae_coverage_pct"] >= 90.0, f"CNAE coverage {m['cnae_coverage_pct']}% < 90%"
        assert m["province_coverage_pct"] >= 90.0, f"Province coverage {m['province_coverage_pct']}% < 90%"


# ---- Iberinform admin: auth-gated mutations (do NOT actually invoke pipeline) ----
class TestIberinformAdminAuth:
    def test_full_pipeline_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/v1/admin/iberinform/full-pipeline")
        assert r.status_code in (401, 403), f"Expected auth rejection, got {r.status_code}"

    def test_recalc_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/v1/admin/iberinform/recalculate-intelligence")
        assert r.status_code in (401, 403)

    def test_generate_synthetic_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/v1/admin/iberinform/generate-synthetic")
        assert r.status_code in (401, 403)


# ---- Sector Intelligence: post-import sanity ----
class TestSectorIntelligencePostImport:
    def test_overview_commerce_leads(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/overview?level=section&limit=21")
        assert r.status_code == 200, r.text[:300]
        items = r.json().get("sectors", [])
        assert len(items) == 21
        # G = Commerce — should be top by dynamism
        # find G
        g = next((it for it in items if it.get("cnae_code") == "G"), None)
        assert g is not None, "Section G (Commerce) not found"
        # Dynamism around 89 expected
        assert g["dynamism_score"] >= 80, f"G dynamism={g['dynamism_score']}, expected >=80"
        # size_score should be > 0 now (was 0 before import)
        assert g["size_score"] > 0, f"G size_score={g['size_score']} — DIRCE distribution not applied"
        # G should have around ~530K companies (via size_score scaled count) — verify via national_company_count if exposed
        # Top dynamism overall: G should be #1 or close
        top_dyn = max(items, key=lambda x: x["dynamism_score"])
        assert top_dyn["cnae_code"] == "G", f"Top dynamism is {top_dyn['cnae_code']}, expected G"

    def test_size_score_positive_for_major_sections(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/overview?level=section&limit=21")
        assert r.status_code == 200
        items = {it["cnae_code"]: it for it in r.json().get("sectors", [])}
        for code in ["G", "F", "I", "M", "C"]:
            assert code in items, f"Section {code} missing"
            assert items[code]["size_score"] > 0, f"Section {code} size_score={items[code]['size_score']}, expected > 0"

    def test_largest_ranking_top_sections(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/largest?level=section&limit=10")
        assert r.status_code == 200, r.text[:300]
        items = r.json().get("sectors", [])
        assert len(items) >= 4
        top_codes = [it["cnae_code"] for it in items[:6]]
        # G, C, M, F should all be in top
        for code in ["G", "C", "M", "F"]:
            assert code in top_codes, f"Expected {code} in top 6 largest, got {top_codes}"

    def test_section_g_detail_has_divisions(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/section/G")
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # Expect divisions list within Commerce
        divisions = data.get("divisions") or data.get("items") or []
        assert len(divisions) > 0, f"No divisions found for section G: {list(data.keys())}"


# ---- Geo Intelligence: post-import sanity ----
class TestGeoIntelligencePostImport:
    def test_overview_madrid_cataluna_lead(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/geo-intelligence/overview?level=ccaa&limit=19")
        assert r.status_code == 200, r.text[:300]
        items = r.json().get("territories", [])
        assert len(items) >= 17
        # Madrid (13) and Cataluña (09) should be top by dynamism
        by_code = {it["geo_id"]: it for it in items}
        # CCAA codes may be string "13"
        madrid = by_code.get("13") or by_code.get(13)
        catalunya = by_code.get("09") or by_code.get(9)
        assert madrid is not None, f"Madrid CCAA not found. IDs: {list(by_code)[:5]}"
        assert catalunya is not None, f"Cataluña CCAA not found"
        assert madrid["dynamism_score"] >= 85, f"Madrid dyn={madrid['dynamism_score']}"
        assert catalunya["dynamism_score"] >= 85, f"Cataluña dyn={catalunya['dynamism_score']}"

    def test_top_dynamic_provinces_madrid_leads(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/geo-intelligence/top-dynamic?level=province&limit=5")
        assert r.status_code == 200
        items = r.json().get("territories", [])
        assert len(items) >= 1
        top = items[0]
        # Madrid province = 28
        assert str(top["geo_id"]) == "28", f"Top province is {top['geo_id']}, expected 28"
        assert top["dynamism_score"] >= 85, f"Madrid province dyn={top['dynamism_score']}"

    def test_ccaa_madrid_drilldown(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/geo-intelligence/ccaa/13")
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        # Should show Madrid CCAA with its provinces; companies ~536K
        ccaa = data.get("ccaa") or data
        active = ccaa.get("active_companies") or data.get("active_companies")
        assert active is not None, f"active_companies missing: keys={list(data.keys())}"
        # Tolerance: 400K-700K range
        assert 400_000 <= active <= 700_000, f"Madrid CCAA active_companies={active}, expected ~536K"

    def test_province_madrid_detail(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/geo-intelligence/province/28")
        assert r.status_code == 200
        data = r.json()
        prov = data.get("province") or data
        active = prov.get("active_companies") or data.get("active_companies")
        assert active is not None
        assert 400_000 <= active <= 700_000, f"Madrid province active_companies={active}, expected ~536K"
