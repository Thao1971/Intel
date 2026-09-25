"""Cartera del asesor (BD en memoria)."""
import asyncio
import os
from datetime import date, timedelta

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_portfolio")

from services import my_space_portfolio as P  # noqa: E402
from services.my_space import ValidationError  # noqa: E402
from tests.test_my_space import FakeColl  # noqa: E402
from tests.test_my_space_objects import FakeMaster  # noqa: E402


def run(c): return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)


def iso(delta): return (date.today() + timedelta(days=delta)).isoformat()


def test_alta_valida_y_resuelve_empresa():
    c, m = FakeColl(), FakeMaster()
    it = run(P.create_item(c, m, "u1", {"client_name": " Grupo X ", "kind": "venta", "cif": "b-86540112", "next_action": "Enviar teaser", "next_action_date": iso(3)}))
    assert it["client_name"] == "Grupo X" and it["stage"] == "prospecto" and it["company"]["master_id"] == "m-9"
    assert it["days_to_action"] == 3 and it["overdue"] is False
    it2 = run(P.create_item(c, m, "u1", {"client_name": "Y", "cif": "B000"}))
    assert it2["company"] is None


@pytest.mark.parametrize("bad", [{"client_name": ""}, {"client_name": "A", "kind": "x"}, {"client_name": "A", "stage": "x"},
                                 {"client_name": "A", "next_action_date": "mañana"}])
def test_validaciones(bad):
    with pytest.raises(ValidationError): run(P.create_item(FakeColl(), FakeMaster(), "u1", bad))


def test_retraso_solo_si_esta_abierto():
    c, m = FakeColl(), FakeMaster()
    a = run(P.create_item(c, m, "u1", {"client_name": "A", "next_action_date": iso(-2)}))
    assert a["overdue"] is True
    b = run(P.update_item(c, m, "u1", a["id"], {"stage": "cerrado"}))
    assert b["overdue"] is False and b["days_to_action"] is None


def test_actualizar_parcial_no_borra_otros_campos_y_aisla():
    c, m = FakeColl(), FakeMaster()
    a = run(P.create_item(c, m, "u1", {"client_name": "A", "notes": "n", "next_action_date": iso(1)}))
    b = run(P.update_item(c, m, "u1", a["id"], {"stage": "en_mercado"}))
    assert b["notes"] == "n" and b["stage"] == "en_mercado" and b["next_action_date"] == iso(1)
    with pytest.raises(ValidationError): run(P.update_item(c, m, "u1", a["id"], {"client_name": " "}))
    assert run(P.update_item(c, m, "u2", a["id"], {"notes": "x"})) is None
    assert run(P.delete_item(c, "u2", a["id"])) is False and run(P.delete_item(c, "u1", a["id"])) is True


def test_resumen_y_proximas_acciones_ordenadas():
    c, m = FakeColl(), FakeMaster()
    for n, d, st in (("Lejos", 40, "prospecto"), ("Pronto", 2, "en_mercado"), ("Tarde", -5, "negociacion"), ("Cerrada", 1, "cerrado"), ("Sin fecha", None, "prospecto")):
        run(P.create_item(c, m, "u1", {"client_name": n, "stage": st, "next_action": "x", "next_action_date": iso(d) if d is not None else None}))
    s = P.summarize(run(P.list_items(c, "u1")))
    assert (s["total"], s["open"], s["overdue"]) == (5, 4, 1)
    assert [u["client_name"] for u in s["upcoming"]] == ["Tarde", "Pronto"]
    assert s["by_stage"]["cerrado"] == 1


def test_rutas_http(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import my_space as R
    fake = type("DB", (), {"my_space_portfolio": FakeColl(), "master_companies": FakeMaster()})()
    monkeypatch.setattr(R, "db", fake)
    monkeypatch.setattr(R, "_user_id", lambda user, request=None: request.headers.get("x-arroba-user-id", "u1"))
    app = FastAPI(); app.include_router(R.router)
    app.dependency_overrides[R.get_current_user] = lambda: {"id": "svc"}
    c = TestClient(app)
    r = c.post("/api/v1/my-space/portfolio", json={"client_name": "Cliente A", "kind": "compra", "next_action_date": iso(5)})
    assert r.status_code == 201
    iid = r.json()["id"]
    assert c.post("/api/v1/my-space/portfolio", json={"client_name": "", "kind": "compra"}).status_code == 422
    assert c.patch(f"/api/v1/my-space/portfolio/{iid}", json={"stage": "en_mercado"}).json()["stage"] == "en_mercado"
    lst = c.get("/api/v1/my-space/portfolio").json()
    assert lst["summary"]["open"] == 1 and len(lst["summary"]["upcoming"]) == 1
    h = {"x-arroba-user-id": "u2"}
    assert c.get("/api/v1/my-space/portfolio", headers=h).json()["items"] == []
    assert c.patch(f"/api/v1/my-space/portfolio/{iid}", json={"notes": "z"}, headers=h).status_code == 404
    assert c.delete(f"/api/v1/my-space/portfolio/{iid}", headers=h).status_code == 404
    assert c.delete(f"/api/v1/my-space/portfolio/{iid}").status_code == 200
