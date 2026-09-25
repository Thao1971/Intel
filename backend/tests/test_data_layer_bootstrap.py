"""
Backend tests for Data Layer bootstrap (Track A + B) - Sprint V2.0.
Validates: JWT bootstrap endpoint, canonical set, full public engine chain,
and contract freeze endpoints.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://data-factory-hub.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "daniel@wearebudadvisors.com"
ADMIN_PASS = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")
API_KEY = "as_TGx2m4UaXc25lsYv_Ep5_w7niWJCA3q-SjU4I9mSmvk"


@pytest.fixture(scope="module")
def admin_token():
    # Try both email and username fields
    for path in ("/api/v1/auth/login", "/api/auth/login"):
        for payload in ({"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                        {"username": ADMIN_EMAIL, "password": ADMIN_PASS}):
            r = requests.post(f"{BASE_URL}{path}", json=payload, timeout=15)
            if r.status_code == 200:
                data = r.json()
                token = data.get("token") or data.get("access_token")
                if token:
                    return token
    pytest.fail(f"Admin login failed: {r.status_code} {r.text[:200]}")


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


class TestBootstrap:
    def test_start_bootstrap(self, auth_headers):
        r = requests.post(
            f"{BASE_URL}/api/v1/data-layer/bootstrap",
            json={"rebuild_intelligence": False, "canonical_n": 50},
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        assert "run_id" in data
        assert data.get("status") == "started"
        pytest.run_id = data["run_id"]

    def test_poll_bootstrap_status(self, auth_headers):
        assert hasattr(pytest, "run_id"), "run_id missing from previous test"
        run_id = pytest.run_id
        final = None
        deadline = time.time() + 120
        while time.time() < deadline:
            r = requests.get(
                f"{BASE_URL}/api/v1/data-layer/bootstrap/{run_id}",
                headers=auth_headers,
                timeout=15,
            )
            assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
            data = r.json()
            status = data.get("status")
            if status in ("completed", "completed_with_warnings", "failed"):
                final = data
                break
            time.sleep(4)
        assert final is not None, "Bootstrap did not finish in time"
        assert final.get("status") in ("completed", "completed_with_warnings"), \
            f"Bootstrap failed: {final}"

        verification = final.get("verification", {})
        assert verification.get("ok") is True, f"verification not ok: {verification}"
        counts = verification.get("counts", {})
        assert counts.get("master_companies", 0) > 0
        coverage = verification.get("coverage", {})
        assert coverage.get("with_financials", 0) > 0

        canonical = final.get("canonical_set", {})
        assert canonical.get("selected", 0) >= 1

        steps = {s.get("step"): s for s in final.get("steps", [])}
        for name in ("ingestion", "master_builder", "ownership_graph", "verification", "canonical_set"):
            assert name in steps, f"Missing step: {name}"
            assert steps[name].get("status") == "ok", f"Step {name} not ok: {steps[name]}"


class TestCanonicalSet:
    def test_canonical_set_endpoint(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/v1/data-layer/canonical-set", headers=auth_headers, timeout=20)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("count", 0) >= 1
        companies = data.get("companies", [])
        assert len(companies) >= 1
        first = companies[0]
        assert first.get("legal_name")
        assert first.get("cif")
        years = first.get("years", [])
        assert isinstance(years, list) and len(years) >= 2, f"years={years}"
        assert "latest_revenue" in first
        pytest.canonical_companies = companies


class TestPublicEngineChain:
    @pytest.fixture(scope="class")
    def target(self, auth_headers):
        if not hasattr(pytest, "canonical_companies"):
            r = requests.get(f"{BASE_URL}/api/v1/data-layer/canonical-set", headers=auth_headers, timeout=20)
            assert r.status_code == 200
            pytest.canonical_companies = r.json().get("companies", [])
        # Prefer A87803862 if present
        for c in pytest.canonical_companies:
            if c.get("cif") == "A87803862":
                return c
        return pytest.canonical_companies[0]

    @pytest.fixture(scope="class")
    def api_headers(self):
        return {"X-API-Key": API_KEY, "Content-Type": "application/json"}

    def test_identity(self, target, api_headers):
        r = requests.post(
            f"{BASE_URL}/api/v2/company-intelligence/identity",
            json={"identifier": target["cif"]},
            headers=api_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        d = r.json()
        assert d.get("legal_name")
        assert d.get("capital_social") is not None
        cnae = d.get("cnae_primary", {})
        assert cnae.get("code")

    def test_financial(self, target, api_headers):
        r = requests.post(
            f"{BASE_URL}/api/v1/financial-intelligence/analyze",
            json={"identifier": target["cif"]},
            headers=api_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        d = r.json()
        assert d.get("has_financials") is True, f"has_financials false: {d}"
        kpis = d.get("kpis", {})
        assert kpis.get("revenue", 0) > 0
        evo = d.get("evolution", {})
        assert evo.get("years", 0) >= 2
        points = evo.get("points", [])
        assert len(points) >= 2
        evo_years = sorted({p.get("year") for p in points if p.get("year")})
        canonical_years = sorted(target.get("years", []))
        # evolution years should be subset of canonical years (no interpolation)
        for y in evo_years:
            assert y in canonical_years, f"Year {y} in evolution not in canonical years {canonical_years}"

    def test_signals(self, target, api_headers):
        r = requests.post(
            f"{BASE_URL}/api/v1/signal-intelligence/analyze",
            json={"identifier": target["cif"]},
            headers=api_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        d = r.json()
        signals = d.get("signals", [])
        assert isinstance(signals, list) and len(signals) >= 1

    def test_semantic(self, target, api_headers):
        r = requests.post(
            f"{BASE_URL}/api/v1/semantic-intelligence/profile",
            json={"identifier": target["cif"]},
            headers=api_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        d = r.json()
        assert d.get("semantic_profile") is not None

    def test_strategy(self, target, api_headers):
        r = requests.post(
            f"{BASE_URL}/api/v1/strategy-intelligence/thesis",
            json={"identifier": target["cif"]},
            headers=api_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        d = r.json()
        assert d.get("thesis_id")


class TestOpenAPIFreeze:
    def test_arroba_v1_openapi(self):
        r = requests.get(f"{BASE_URL}/api/v1/openapi/arroba.v1.json", timeout=20)
        assert r.status_code == 200
        data = r.json()
        paths = data.get("paths", {})
        assert len(paths) == 53, f"Expected 53 paths, got {len(paths)}"

    def test_arroba_v2_openapi(self):
        r = requests.get(f"{BASE_URL}/api/v1/openapi/arroba.v2.json", timeout=20)
        assert r.status_code == 200
        data = r.json()
        paths = data.get("paths", {})
        assert len(paths) == 54, f"Expected 54 paths, got {len(paths)}"
