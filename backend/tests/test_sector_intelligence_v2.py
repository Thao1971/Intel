"""Sector Intelligence V2 — Backend API Test Suite

Tests:
- CNAE catalog endpoints (catalog, archetypes)
- Sector intelligence V2 endpoints (overview, rankings, drill-down, emerging/contracting)
- Multi-score validation (size_score, growth_score, activity_score, dynamism_score)
- Hierarchy (Section → Division → Group)
- Auth-gated sync endpoint
- Contract version v2.0
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://data-factory-hub.preview.emergentagent.com").rstrip("/")
LOGIN_EMAIL = "daniel@wearebudadvisors.com"
LOGIN_PASSWORD = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")

REQUIRED_CARD_FIELDS = [
    "cnae_code", "cnae_level", "cnae_label",
    "size_score", "growth_score", "activity_score", "dynamism_score",
    "trend_direction", "signal",
]


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def auth_token(api):
    """Try to fetch a JWT token. Multiple login route names tried."""
    candidates = [
        "/api/auth/login",
        "/api/v1/auth/login",
        "/api/login",
    ]
    payload = {"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD}
    for path in candidates:
        try:
            r = api.post(f"{BASE_URL}{path}", json=payload, timeout=15)
            if r.status_code == 200:
                data = r.json()
                token = data.get("token") or data.get("access_token") or (data.get("data") or {}).get("token")
                if token:
                    return token
        except Exception:
            continue
    return None


# ───────────────────────── CNAE CATALOG ─────────────────────────

class TestCnaeCatalog:
    def test_catalog_counts(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/cnae/catalog", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_sections"] == 21
        assert d["total_divisions"] == 88
        assert d["total_groups"] == 176
        assert isinstance(d["catalog"], list) and len(d["catalog"]) == 21
        # hierarchical structure check
        s = d["catalog"][0]
        assert "code" in s and "label" in s and "divisions" in s

    def test_archetypes(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/cnae/archetypes", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert isinstance(d["archetypes"], list)
        assert len(d["archetypes"]) == 13, f"expected 13 archetypes, got {len(d['archetypes'])}"
        assert isinstance(d["taxonomy_types"], list)
        assert len(d["taxonomy_types"]) == 4, f"expected 4 taxonomy types, got {len(d['taxonomy_types'])}"


# ───────────────────────── OVERVIEW ─────────────────────────

class TestOverview:
    def test_default_section_level(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/overview", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["contract_version"] == "2.0"
        assert d["level"] == "section"
        assert d["count"] == 21, f"expected 21 sections, got {d['count']}"
        # Sorted desc by dynamism_score
        scores = [s["dynamism_score"] for s in d["sectors"]]
        assert scores == sorted(scores, reverse=True)
        # All cards have required fields
        for s in d["sectors"]:
            for f in REQUIRED_CARD_FIELDS:
                assert f in s, f"missing {f} in card {s.get('cnae_code')}"

    def test_division_level(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/overview?level=division", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["level"] == "division"
        assert d["count"] == 88, f"expected 88 divisions, got {d['count']}"

    def test_group_level(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/overview?level=group", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["level"] == "group"
        assert d["count"] == 176, f"expected 176 groups, got {d['count']}"


# ───────────────────────── RANKINGS ─────────────────────────

class TestRankings:
    def _check_sorted_desc(self, items, key):
        scores = [s[key] for s in items]
        assert scores == sorted(scores, reverse=True), f"not sorted desc by {key}: {scores}"

    def test_top_dynamic(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/top-dynamic?limit=5", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ranking_by"] == "dynamism_score"
        assert d["contract_version"] == "2.0"
        assert len(d["sectors"]) <= 5
        # All returned have dynamism_score > 0 (per endpoint filter)
        for s in d["sectors"]:
            assert s["dynamism_score"] > 0
        self._check_sorted_desc(d["sectors"], "dynamism_score")

    def test_largest(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/largest?limit=5", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["ranking_by"] == "size_score"
        assert len(d["sectors"]) == 5
        self._check_sorted_desc(d["sectors"], "size_score")

    def test_fastest_growing(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/fastest-growing?limit=5", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["ranking_by"] == "growth_score"
        assert len(d["sectors"]) == 5
        self._check_sorted_desc(d["sectors"], "growth_score")

    def test_most_active(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/most-active?limit=5", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["ranking_by"] == "activity_score"
        assert len(d["sectors"]) == 5
        self._check_sorted_desc(d["sectors"], "activity_score")


# ───────────────────────── SIGNALS ─────────────────────────

class TestSignals:
    def test_emerging(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/emerging", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["contract_version"] == "2.0"
        assert "sectors" in d
        for s in d["sectors"]:
            assert s["signal"] in ("sector_expansion", "emerging_sector", "high_public_demand")

    def test_contracting(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/contracting", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for s in d["sectors"]:
            assert s["signal"] == "sector_contraction"


# ───────────────────────── DRILL-DOWN ─────────────────────────

class TestDrillDown:
    def test_section_J(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/section/J", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["section"]["cnae_code"] == "J"
        assert d["section"]["cnae_level"] == "section"
        assert d["divisions_count"] >= 1
        for div in d["divisions"]:
            assert div["cnae_level"] == "division"

    def test_section_M(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/section/M", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["section"]["cnae_code"] == "M"
        assert d["divisions_count"] >= 1

    def test_section_not_found(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/section/Z", timeout=15)
        assert r.status_code == 404

    def test_detail_division_62(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/detail/62", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["sector"]["cnae_code"] == "62"
        assert d["sector"]["cnae_level"] == "division"
        # division should have group children
        assert d["children_count"] >= 1
        for c in d["children"]:
            assert c["cnae_level"] == "group"
            assert c["cnae_code"].startswith("62")

    def test_detail_section_J(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/detail/J", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["sector"]["cnae_code"] == "J"
        assert d["sector"]["cnae_level"] == "section"
        assert d["children_count"] >= 1
        for c in d["children"]:
            assert c["cnae_level"] == "division"

    def test_hierarchy_chain_J_62_6201(self, api):
        """Verify drill-down chain Section J → Division 62 → Group 6201"""
        # Section J should contain Division 62
        rJ = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/section/J", timeout=15).json()
        codes_J = {d["cnae_code"] for d in rJ["divisions"]}
        assert "62" in codes_J, f"Division 62 not under Section J: {codes_J}"

        # Division 62 should contain Group 6201
        r62 = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/detail/62", timeout=15).json()
        codes_62 = {c["cnae_code"] for c in r62["children"]}
        assert "6201" in codes_62, f"Group 6201 not under Division 62: {codes_62}"

    def test_detail_not_found(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/detail/9999", timeout=15)
        assert r.status_code == 404


# ───────────────────────── TAXONOMIES ─────────────────────────

class TestTaxonomies:
    def test_taxonomies(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/sector-intelligence/taxonomies", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["contract_version"] == "2.0"
        assert d["active"] == "official_cnae"
        assert len(d["taxonomy_types"]) == 4
        assert len(d["archetypes"]) == 13


# ───────────────────────── SYNC (AUTH) ─────────────────────────

class TestSync:
    def test_sync_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/v1/public/sector-intelligence/sync", timeout=15)
        assert r.status_code in (401, 403), f"sync should require auth, got {r.status_code}"

    def test_sync_with_auth(self, api, auth_token):
        if not auth_token:
            pytest.skip("No auth token obtainable; skipping authenticated sync test")
        headers = {"Authorization": f"Bearer {auth_token}"}
        r = api.post(
            f"{BASE_URL}/api/v1/public/sector-intelligence/sync",
            headers=headers,
            timeout=120,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        # Expecting counts: 21 sections, 88 divisions, 176 groups
        sections = d.get("sections") or d.get("section_count")
        divisions = d.get("divisions") or d.get("division_count")
        groups = d.get("groups") or d.get("group_count")
        assert sections == 21, f"expected 21 sections from sync, got {sections} (resp={d})"
        assert divisions == 88, f"expected 88 divisions from sync, got {divisions}"
        assert groups == 176, f"expected 176 groups from sync, got {groups}"
