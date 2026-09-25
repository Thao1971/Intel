"""Shared fixtures for smoke tests."""
import os
import time
import pytest
import requests
from smoke_loop import run_async  # noqa: F401  (re-exported for convenience)

BASE_URL = os.environ.get(
    "SMOKE_BASE_URL",
    os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001"),
).rstrip("/")

EMAIL = os.environ.get("SMOKE_TEST_EMAIL", "daniel@wearebudadvisors.com")
PASSWORD = os.environ.get("SMOKE_TEST_PASSWORD", "")


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def auth_token() -> str:
    r = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"Login failed {r.status_code}: {r.text[:200]}")
    data = r.json()
    token = data.get("token") or data.get("access_token")
    assert token, f"No token returned: {data}"
    return token


@pytest.fixture(scope="session")
def known_master_with_scrape(base_url, auth_token) -> dict:
    """A master_company_id known to have a *real* linked agency_result (cache hit case).

    Prefers masters whose web block has substantive content (description+tags),
    skipping test fixtures created by other smoke runs.
    """
    headers = {"Authorization": f"Bearer {auth_token}"}
    r = requests.get(f"{base_url}/api/v1/master?limit=200", headers=headers, timeout=20)
    if r.status_code == 200:
        items = r.json().get("companies") or r.json().get("items") or []
        for m in items:
            web = (m.get("sources") or {}).get("web") or {}
            if web.get("description") and web.get("tags"):
                return {
                    "master_company_id": m.get("master_company_id"),
                    "legal_name": m.get("legal_name"),
                    "domain": m.get("domain") or m.get("website"),
                }
    # Fallback to a known seeded id (Ogilvy, linked during Phase 2 migration)
    return {"master_company_id": "mc_043746ab-3d6", "legal_name": "Ogilvy", "domain": "ogilvy.com"}


@pytest.fixture(scope="session")
def known_master_without_scrape() -> dict:
    """A master that will *not* have a web scrape (used for cache-miss case).
    Telefónica's master id (mc_24e7589c-545) — may have a scrape after Phase 2,
    so we generate a synthetic CIF instead so a fresh master is created.
    """
    return {
        "valuo_company_id": f"smoke_test_{int(time.time())}",
        "legal_name": "SMOKE TEST SOCIEDAD SL",
        "cif": f"B{int(time.time()) % 100000000:08d}",
        "domain": f"smoketest-{int(time.time())}.example",
    }


def poll_until(fn, predicate, timeout=10, interval=0.5):
    """Poll fn() every interval seconds until predicate(result) is true or timeout."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if predicate(last):
            return last
        time.sleep(interval)
    return last
