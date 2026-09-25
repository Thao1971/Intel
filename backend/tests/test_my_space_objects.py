"""Objeto central de Vendedor y Busca capital (sin Mongo ni motores reales)."""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_my_space_objects")

from services import my_space_objects as O  # noqa: E402
from services.my_space import ValidationError  # noqa: E402
from tests.test_my_space import FakeColl  # noqa: E402


def run(c): return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)


class FakeMaster(FakeColl):
    def __init__(self):
        super().__init__()
        self.docs = [{"master_id": "m-9", "cif_normalized": "B86540112", "identity": {"legal_name": "Kitchen Studio, S.L."},
                      "classification": {"cnae_code": "5610", "cnae_section": "I"}, "location": {"provincia": "Madrid"},
                      "financials": {"latest": {"revenue": 3400000}}}]


def test_valida_vendedor():
    o = O.validate_object("vendedor", {"company_name": " Kitchen ", "cif": "b-86 540 112", "asking_price_eur": "2500000"})
    assert o["company_name"] == "Kitchen" and o["cif"] == "B86540112"
    assert o["sale_type"] == "por_definir" and o["teaser_status"] == "sin_teaser" and o["asking_price_eur"] == 2500000
    for bad in ({"company_name": ""}, {"company_name": "A", "sale_type": "x"}, {"company_name": "A", "asking_price_eur": -1},
                {"company_name": "A", "asking_price_eur": "abc"}, {"company_name": "A", "teaser_status": "publicado"}):
        with pytest.raises(ValidationError): O.validate_object("vendedor", bad)


def test_valida_busca_capital():
    o = O.validate_object("busca_capital", {"company_name": "Clarion", "amount_min_eur": 1e6, "amount_max_eur": 3e6, "instrument": "minoritario"})
    assert o["instrument"] == "minoritario" and "sale_type" not in o
    with pytest.raises(ValidationError): O.validate_object("busca_capital", {"company_name": "C", "amount_min_eur": 5, "amount_max_eur": 1})
    with pytest.raises(ValidationError): O.validate_object("comprador", {"company_name": "C"})


def test_guardar_resuelve_empresa_real_o_none():
    objs, master = FakeColl(), FakeMaster()
    d = run(O.save_object(objs, master, "u1", "vendedor", {"company_name": "Kitchen", "cif": "B86540112"}))
    assert d["company"]["master_id"] == "m-9" and d["company"]["cnae_code"] == "5610"
    d2 = run(O.save_object(objs, master, "u1", "vendedor", {"company_name": "Otra", "cif": "B00000000"}))
    assert d2["company"] is None                 # no existe: no se inventa
    assert len(objs.docs) == 1                   # upsert por (owner, role)
    assert run(O.get_object(objs, "u2", "vendedor")) is None   # aislamiento


CNMV = {"specialist_funds": [{"name": "Fondo Hosteleria", "entity_type": "fcr", "sector_score": 80}],
        "specialist_managers": [{"name": "Gestora H", "entity_type": "sgeic", "sector_score": 70}],
        "generalist_funds": [{"name": "G1"}, {"name": "G2"}], "generalist_managers": [{"name": "G3"}]}
PROV = {
    "cnmv": lambda cnae: _aw(CNMV),
    "buyers": lambda mid, n: _aw({"recommendations": [{"candidate": {"master_id": "c1", "name": "Grupo Olmedo"},
                                                        "recommendation_role_label": "Comprador estratégico", "score": 0.81, "explanation": "x"}]}),
    "mandates": lambda mid: _aw({"mandates_scanned": 40, "mandates": [{"score": 0.7, "mandate_name": "SECRETO"}, {"score": 0.4}]}),
}


async def _aw(v): return v


def test_matches_vendedor_sin_filtrar_nombres_de_mandatos():
    obj = {"company": {"master_id": "m-9", "cnae_code": "5610"}}
    r = run(O.build_matches("vendedor", obj, PROV))
    assert r["buyers"]["items"][0]["name"] == "Grupo Olmedo"
    assert r["financial_buyers"]["funds"][0]["name"] == "Fondo Hosteleria" and r["financial_buyers"]["generalists_count"] == 3
    assert r["interested_mandates"] == {"evaluated": 40, "with_fit": 2, "best_score": 0.7, "basis": r["interested_mandates"]["basis"]}
    assert "SECRETO" not in str(r)               # privacidad de otros compradores


def test_matches_busca_capital_declara_limite_y_casos_sin_datos():
    obj = {"company": {"master_id": "m-9", "cnae_code": "5610"}}
    r = run(O.build_matches("busca_capital", obj, PROV))
    assert r["investors"]["funds"] and "buyers" not in r and any("todavía" in n for n in r["notes"])
    assert run(O.build_matches("vendedor", None, PROV)) == {"available": False, "reason": "no_object"}
    assert run(O.build_matches("vendedor", {"company": None}, PROV))["reason"] == "company_not_found"
    sin_cnae = run(O.build_matches("busca_capital", {"company": {"master_id": "m", "cnae_code": None}}, PROV))
    assert sin_cnae["investors"]["funds"] == [] and sin_cnae["investors"]["managers"] == []


def test_rutas_http(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import my_space as R

    fake = type("DB", (), {"my_space_objects": FakeColl(), "master_companies": FakeMaster(),
                           "my_space_pipeline": FakeColl(), "my_space_profiles": FakeColl()})()
    monkeypatch.setattr(R, "db", fake)
    monkeypatch.setattr(R, "_user_id", lambda user, request=None: request.headers.get("x-arroba-user-id", "u1"))
    async def prov(): return PROV
    monkeypatch.setattr(R, "_providers", prov)
    app = FastAPI(); app.include_router(R.router)
    app.dependency_overrides[R.get_current_user] = lambda: {"id": "svc"}
    c = TestClient(app)
    assert c.get("/api/v1/my-space/object", params={"role": "vendedor"}).json()["object"] is None
    assert c.get("/api/v1/my-space/object", params={"role": "comprador"}).status_code == 422
    assert c.put("/api/v1/my-space/object", json={"role": "vendedor", "company_name": ""}).status_code == 422
    r = c.put("/api/v1/my-space/object", json={"role": "vendedor", "company_name": "Kitchen", "cif": "B86540112"})
    assert r.status_code == 200 and r.json()["company"]["master_id"] == "m-9"
    assert c.get("/api/v1/my-space/object/matches", params={"role": "vendedor"}).json()["available"] is True
    h = {"x-arroba-user-id": "u2"}
    assert c.get("/api/v1/my-space/object", params={"role": "vendedor"}, headers=h).json()["object"] is None
    assert c.get("/api/v1/my-space/object/matches", params={"role": "vendedor"}, headers=h).json()["reason"] == "no_object"
