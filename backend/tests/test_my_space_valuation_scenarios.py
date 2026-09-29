"""Escenarios de valoración editados a mano, privados por usuario (BD en memoria)."""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_valuation_scenarios")

from services import my_space_valuation_scenarios as VS  # noqa: E402
from services.my_space import ValidationError  # noqa: E402
from tests.test_my_space import FakeColl as _BaseFakeColl  # noqa: E402


class FakeColl(_BaseFakeColl):
    async def count_documents(self, q):
        return sum(1 for d in self.docs if self._match(d, q))


def run(c): return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)


SAMPLE = {
    "cif": "b-28031458",
    "company_name": "NCR España",
    "run_id": "avr_x1",
    "label": "Con WACC 12%",
    "inputs": {"rf": 5.0, "wacc": 0.12},
    "outputs": {"enterprise_value": 30.1, "equity_value": 28.0, "conservative": 25.0, "optimistic": 34.0},
    "reference": {"enterprise_value": 19.9, "equity_value": 17.6},
}


def test_alta_normaliza_cif_y_defaults():
    it = run(VS.create_scenario(FakeColl(), "u1", SAMPLE))
    assert it["cif"] == "B28031458" and it["owner_id"] == "u1"
    assert it["label"] == "Con WACC 12%"
    assert it["outputs"]["enterprise_value"] == 30.1
    assert "id" in it and "created_at" in it


def test_label_por_defecto_si_no_se_da():
    it = run(VS.create_scenario(FakeColl(), "u1", {**SAMPLE, "label": None}))
    assert it["label"] == "Escenario editado"


@pytest.mark.parametrize("bad", [{**SAMPLE, "cif": ""}, {**SAMPLE, "inputs": {}}, {**SAMPLE, "inputs": None}])
def test_validaciones(bad):
    with pytest.raises(ValidationError):
        run(VS.create_scenario(FakeColl(), "u1", bad))


def test_limite_por_propietario():
    c = FakeColl()
    for i in range(VS.MAX_ITEMS_PER_OWNER):
        run(VS.create_scenario(c, "u1", {**SAMPLE, "label": f"e{i}"}))
    with pytest.raises(ValidationError):
        run(VS.create_scenario(c, "u1", SAMPLE))
    # otro propietario no cuenta para el límite de u1
    run(VS.create_scenario(c, "u2", SAMPLE))


def test_aislamiento_por_propietario():
    c = FakeColl()
    a = run(VS.create_scenario(c, "u1", SAMPLE))
    run(VS.create_scenario(c, "u2", SAMPLE))
    assert len(run(VS.list_scenarios(c, "u1"))) == 1
    assert len(run(VS.list_scenarios(c, "u2"))) == 1
    assert run(VS.get_scenario(c, "u2", a["id"])) is None
    assert run(VS.delete_scenario(c, "u2", a["id"])) is False
    assert run(VS.get_scenario(c, "u1", a["id"]))["id"] == a["id"]
    assert run(VS.delete_scenario(c, "u1", a["id"])) is True


def test_filtro_por_cif():
    c = FakeColl()
    run(VS.create_scenario(c, "u1", {**SAMPLE, "cif": "B28031458"}))
    run(VS.create_scenario(c, "u1", {**SAMPLE, "cif": "A87803862"}))
    items = run(VS.list_scenarios(c, "u1", cif="b28031458"))
    assert len(items) == 1 and items[0]["cif"] == "B28031458"


def test_rutas_http(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import my_space as R
    fake = type("DB", (), {"my_space_valuation_scenarios": FakeColl()})()
    monkeypatch.setattr(R, "db", fake)
    monkeypatch.setattr(R, "_user_id", lambda user, request=None: request.headers.get("x-arroba-user-id", "u1"))
    app = FastAPI(); app.include_router(R.router)
    app.dependency_overrides[R.get_current_user] = lambda: {"id": "svc"}
    c = TestClient(app)

    r = c.post("/api/v1/my-space/valuation-scenarios", json=SAMPLE)
    assert r.status_code == 201
    sid = r.json()["id"]

    assert c.post("/api/v1/my-space/valuation-scenarios", json={**SAMPLE, "inputs": {}}).status_code == 422

    lst = c.get("/api/v1/my-space/valuation-scenarios").json()
    assert len(lst["items"]) == 1 and lst["items"][0]["id"] == sid

    h = {"x-arroba-user-id": "u2"}
    assert c.get("/api/v1/my-space/valuation-scenarios", headers=h).json()["items"] == []
    assert c.get(f"/api/v1/my-space/valuation-scenarios/{sid}", headers=h).status_code == 404
    assert c.delete(f"/api/v1/my-space/valuation-scenarios/{sid}", headers=h).status_code == 404

    assert c.get(f"/api/v1/my-space/valuation-scenarios/{sid}").json()["cif"] == "B28031458"
    assert c.delete(f"/api/v1/my-space/valuation-scenarios/{sid}").status_code == 200
    assert c.get(f"/api/v1/my-space/valuation-scenarios/{sid}").status_code == 404
