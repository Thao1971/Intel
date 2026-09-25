"""Shared fixtures + assertion helpers for Golden Contract Tests.

These tests are BLACK-BOX: they exercise only the public HTTP contract and freeze the
current observable behavior (status code, headers, JSON structure, types, computed
invariants, error handling). They must never assert on internal implementation.

Any future migration MUST keep these 100% green — the implementation may change, the
contract may NOT.
"""
import os
import sys
import time
import requests
import pytest

# Make helpers importable (`from conftest import ...`) AND backend modules
# (`from services...`) resolvable regardless of the pytest invocation CWD.
_GOLDEN_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_GOLDEN_DIR, "..", ".."))
for _p in (_GOLDEN_DIR, _BACKEND_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BASE_URL = os.environ.get("GOLDEN_BASE_URL",
                          os.environ.get("BASE_URL", "http://localhost:8001")).rstrip("/")
EMAIL = os.environ.get("SMOKE_TEST_EMAIL", "daniel@wearebudadvisors.com")
PASSWORD = os.environ.get("SMOKE_TEST_PASSWORD", "")

TIMEOUT = 60


def base() -> str:
    return BASE_URL


# ── Contract assertion helpers ──
def assert_json_200(r):
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:300]}"
    assert r.headers.get("content-type", "").startswith("application/json"), \
        f"expected JSON content-type, got {r.headers.get('content-type')}"
    return r.json()


def assert_status(r, code):
    assert r.status_code == code, f"expected {code}, got {r.status_code}: {r.text[:300]}"


def require_keys(obj: dict, keys):
    missing = [k for k in keys if k not in obj]
    assert not missing, f"contract regression — missing keys {missing}. present: {sorted(obj.keys())}"


def assert_type(obj: dict, field, types, allow_none=True):
    v = obj.get(field)
    if v is None and allow_none:
        return
    assert isinstance(v, types), f"field '{field}' expected {types}, got {type(v)} ({v!r})"


# ── Auth ──
@pytest.fixture(scope="session")
def jwt_token() -> str:
    r = requests.post(f"{BASE_URL}/api/v1/auth/login",
                      json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"Login failed {r.status_code}: {r.text[:200]}")
    data = r.json()
    token = data.get("token") or data.get("access_token")
    assert token, f"no token in login response: {data}"
    return token


@pytest.fixture(scope="session")
def auth_headers(jwt_token):
    return {"Authorization": f"Bearer {jwt_token}"}


# ── Data discovery (black-box, via the API itself) ──
@pytest.fixture(scope="session")
def any_master_id(auth_headers) -> str:
    r = requests.get(f"{BASE_URL}/api/v1/master?limit=10", headers=auth_headers, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"cannot list master companies: {r.status_code}")
    companies = r.json().get("companies", [])
    if not companies:
        pytest.skip("no master companies available")
    return companies[0]["master_company_id"]


@pytest.fixture(scope="session")
def publishable_master_id(auth_headers):
    for st in ("verified", "auto_merged"):
        r = requests.get(f"{BASE_URL}/api/v1/master?merge_status={st}&limit=5",
                         headers=auth_headers, timeout=30)
        if r.status_code == 200 and r.json().get("companies"):
            return r.json()["companies"][0]["master_company_id"]
    return None


@pytest.fixture(scope="session")
def discovered_master_id(auth_headers):
    r = requests.get(f"{BASE_URL}/api/v1/master?merge_status=discovered&limit=5",
                     headers=auth_headers, timeout=30)
    if r.status_code == 200 and r.json().get("companies"):
        return r.json()["companies"][0]["master_company_id"]
    return None


@pytest.fixture(scope="module")
def valuo_request(_unique_valuo_id):
    """Create a real Valuo update request (public contract) and return its response.

    Uses a synthetic valuo_company_id + CIF so a fresh 'discovered' master is created
    without disturbing existing data.
    """
    payload = {
        "valuo_company_id": _unique_valuo_id,
        "legal_name": "GOLDEN TEST SOCIEDAD SL",
        "cif": f"B{int(time.time()) % 100000000:08d}",
        "domain": f"golden-{_unique_valuo_id}.example",
        "requested_by": "golden_contract_tests",
        "request_reason": "golden contract characterization",
    }
    r = requests.post(f"{BASE_URL}/api/v1/valuo/request-update-from-valuo",
                      json=payload, timeout=TIMEOUT)
    return {"payload": payload, "response": r}


@pytest.fixture(scope="module")
def _unique_valuo_id():
    return f"golden_{int(time.time() * 1000)}"
