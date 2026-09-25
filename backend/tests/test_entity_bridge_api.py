"""API tests for /api/v1/master/bridge/* endpoints (M3 Fase 2)."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
CREDS = {"email": "daniel@wearebudadvisors.com", "password": __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")}


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/v1/auth/login", json=CREDS, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("access_token") or j["token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_run_requires_jwt():
    r = requests.post(f"{BASE_URL}/api/v1/master/bridge/run", json={"dry_run": True}, timeout=30)
    assert r.status_code in (401, 403), r.status_code


def test_runs_list_requires_jwt():
    r = requests.get(f"{BASE_URL}/api/v1/master/bridge/runs", timeout=30)
    assert r.status_code in (401, 403), r.status_code


def test_run_dry_run_returns_metrics(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/v1/master/bridge/run",
        json={"dry_run": True},
        headers=auth_headers,
        timeout=120,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    metrics = data.get("metrics") or data
    required = [
        "processed", "linked", "coverage_pct", "conflicts", "ambiguous",
        "orphans", "potential_duplicate_groups", "potential_duplicate_records",
        "pending_manual_review",
    ]
    for k in required:
        assert k in metrics, f"missing metric {k}: {metrics}"
    # coverage expected 0.0 (datasets disjuntos)
    assert metrics["processed"] == metrics["orphans"] or metrics["orphans"] > 0
    print("METRICS:", metrics)


def test_runs_history_and_detail(auth_headers):
    r = requests.get(f"{BASE_URL}/api/v1/master/bridge/runs", headers=auth_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    runs = body.get("runs", body if isinstance(body, list) else [])
    # after at least one dry_run there may be a persisted run or not (dry-run doesn't persist)
    assert isinstance(runs, list)


def test_run_persist_and_rollback(auth_headers):
    # Real run (persisted)
    r = requests.post(
        f"{BASE_URL}/api/v1/master/bridge/run",
        json={"dry_run": False},
        headers=auth_headers,
        timeout=180,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    run_id = data.get("run_id") or data.get("id") or (data.get("run") or {}).get("run_id")
    assert run_id, f"no run_id in response: {data}"

    # detail
    r2 = requests.get(f"{BASE_URL}/api/v1/master/bridge/runs/{run_id}", headers=auth_headers, timeout=30)
    assert r2.status_code == 200, r2.text

    # rollback
    r3 = requests.post(
        f"{BASE_URL}/api/v1/master/bridge/runs/{run_id}/rollback",
        headers=auth_headers,
        timeout=60,
    )
    assert r3.status_code == 200, r3.text
    body = r3.json()
    assert body.get("status") in ("rolled_back", "ok", "success") or body.get("rolled_back") is True, body
