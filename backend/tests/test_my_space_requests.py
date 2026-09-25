"""Solicitudes de acceso y NDA entre usuarios (BD en memoria)."""
import asyncio
import json
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_requests")

from services import my_space_requests as Q  # noqa: E402
from services.my_space import ValidationError  # noqa: E402
from tests.test_my_space import FakeColl  # noqa: E402


def run(c): return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)


SECRET_NAME, SECRET_CIF = "Kitchen Studio, S.L.", "B86540112"


def world():
    objects = FakeColl()
    objects.docs.append({
        "owner_id": "seller", "role": "vendedor",
        "fields": {"company_name": SECRET_NAME, "cif": SECRET_CIF, "headline": "Estudio de cocinas profesionales",
                   "sale_type": "venta_total", "asking_price_eur": 3500000.0},
        "company": {"master_id": "m1", "name": SECRET_NAME, "cnae_code": "5610", "cnae_section": "I",
                    "provincia": "Madrid", "revenue": 3400000.0}})
    return {"objects": objects, "requests": FakeColl(), "pipeline": FakeColl()}


def publish(c): return run(Q.set_published(c["objects"], "seller", True))


def test_plantilla_nda_versionada_y_sin_validez_juridica_declarada():
    t = Q.nda_template()
    assert t["version"] == Q.NDA_VERSION and len(t["hash"]) == 64 and "pendiente de validación jurídica" in t["text"]


def test_publicar_exige_objeto_empresa_real_y_titular():
    c = world()
    with pytest.raises(ValidationError): run(Q.set_published(FakeColl(), "seller", True))
    c["objects"].docs[0]["company"] = None
    with pytest.raises(ValidationError): run(Q.set_published(c["objects"], "seller", True))
    c["objects"].docs[0]["company"] = {"master_id": "m1"}
    c["objects"].docs[0]["fields"]["headline"] = " "
    with pytest.raises(ValidationError): run(Q.set_published(c["objects"], "seller", True))


def test_anuncio_es_anonimo():
    c = world(); o = publish(c)
    txt = json.dumps(Q.public_listing(o))
    for secret in (SECRET_NAME, SECRET_CIF, "3500000", "3400000", "Kitchen"):
        assert secret not in txt
    assert Q.public_listing(o)["cnae_code"] == "5610"


def test_marketplace_solo_publicados_y_no_los_propios():
    c = world(); publish(c)
    assert run(Q.list_marketplace(c["objects"], "buyer", c["requests"]))[0]["my_request"] is None
    assert run(Q.list_marketplace(c["objects"], "seller", c["requests"])) == []
    run(Q.set_published(c["objects"], "seller", False))
    assert run(Q.list_marketplace(c["objects"], "buyer", c["requests"])) == []


def flow_until_request(c):
    o = publish(c)
    return o, run(Q.create_request(c, "buyer", "Ana Compradora", o["listing_id"], "comprador", "Nos interesa", "Meridia"))


def pipe(c, owner):
    return [d for d in c["pipeline"].docs if d["owner_id"] == owner]


def test_flujo_completo_estado_turno_y_revelacion():
    c = world(); o, r = flow_until_request(c)
    assert r["status"] == "pending"
    b, s = pipe(c, "buyer")[0], pipe(c, "seller")[0]
    assert (b["status"], b["turn"], b["role"]) == ("contactado", "their", "comprador")
    assert (s["status"], s["turn"], s["counterpart_name"]) == ("contactado", "mine", "Ana Compradora")
    assert SECRET_NAME not in json.dumps(run(Q.get_request(c, "buyer", r["id"])))       # antes del NDA: nada
    assert "buyer" in run(Q.get_request(c, "seller", r["id"])) and "disclosed" not in run(Q.get_request(c, "seller", r["id"]))

    d = run(Q.decide(c, "seller", r["id"], "accept"))
    assert d["status"] == "awaiting_buyer_nda" and d["nda"]["seller_accepted_at"]
    assert (pipe(c, "buyer")[0]["status"], pipe(c, "buyer")[0]["turn"]) == ("nda_enviado", "mine")
    assert (pipe(c, "seller")[0]["status"], pipe(c, "seller")[0]["turn"]) == ("nda_enviado", "their")
    assert SECRET_NAME not in json.dumps(run(Q.get_request(c, "buyer", r["id"])))       # aún sin revelar

    with pytest.raises(ValidationError): run(Q.accept_nda(c, "buyer", r["id"], "hash-viejo"))
    done = run(Q.accept_nda(c, "buyer", r["id"], Q.NDA_HASH))
    assert done["status"] == "nda_signed" and done["nda"]["buyer_accepted_at"] and done["nda"]["text_hash"] == Q.NDA_HASH
    view = run(Q.get_request(c, "buyer", r["id"]))
    assert view["disclosed"]["company_name"] == SECRET_NAME and view["disclosed"]["cif"] == SECRET_CIF
    assert pipe(c, "buyer")[0]["counterpart_name"] == SECRET_NAME and pipe(c, "buyer")[0]["status"] == "nda_firmado"
    assert "disclosed" not in run(Q.get_request(c, "seller", r["id"]))
    assert [e["type"] for e in done["events"]] == ["requested", "accepted_by_seller", "nda_accepted_by_buyer"]
    assert run(Q.summary(c, "seller"))["nda_signed"] == 1


def test_rechazo_retirada_y_nueva_solicitud():
    c = world(); o, r = flow_until_request(c)
    assert run(Q.decide(c, "seller", r["id"], "reject"))["status"] == "rejected"
    assert pipe(c, "buyer")[0]["status"] == "descartada" and pipe(c, "buyer")[0]["turn"] is None
    with pytest.raises(ValidationError): run(Q.decide(c, "seller", r["id"], "accept"))          # ya resuelta
    r2 = run(Q.create_request(c, "buyer", "Ana", o["listing_id"], "comprador", None, None))     # puede volver a pedir
    assert r2["status"] == "pending" and len(c["requests"].docs) == 1
    assert len(pipe(c, "buyer")) == 1 and len(pipe(c, "seller")) == 1                          # sin duplicados en pipelines
    assert run(Q.withdraw(c, "buyer", r2["id"]))["status"] == "withdrawn"
    with pytest.raises(ValidationError): run(Q.withdraw(c, "buyer", r2["id"]))


def test_reglas_de_alta():
    c = world(); o = publish(c)
    with pytest.raises(ValidationError): run(Q.create_request(c, "seller", "S", o["listing_id"], "comprador", None, None))   # propio
    with pytest.raises(ValidationError): run(Q.create_request(c, "buyer", "B", o["listing_id"], "vendedor", None, None))     # rol
    with pytest.raises(LookupError): run(Q.create_request(c, "buyer", "B", "no-existe", "comprador", None, None))
    run(Q.create_request(c, "buyer", "B", o["listing_id"], "asesor", None, None))
    with pytest.raises(ValidationError): run(Q.create_request(c, "buyer", "B", o["listing_id"], "comprador", None, None))    # duplicada
    run(Q.set_published(c["objects"], "seller", False))
    with pytest.raises(LookupError): run(Q.create_request(c, "otro", "O", o["listing_id"], "comprador", None, None))         # despublicado


def test_permisos_entre_partes_y_terceros():
    c = world(); o, r = flow_until_request(c)
    for who in ("tercero", "otro"):
        with pytest.raises(LookupError): run(Q.get_request(c, who, r["id"]))
        with pytest.raises(LookupError): run(Q.decide(c, who, r["id"], "accept"))
        with pytest.raises(LookupError): run(Q.withdraw(c, who, r["id"]))
    with pytest.raises(LookupError): run(Q.decide(c, "buyer", r["id"], "accept"))               # el comprador no decide
    run(Q.decide(c, "seller", r["id"], "accept"))
    with pytest.raises(LookupError): run(Q.accept_nda(c, "seller", r["id"], Q.NDA_HASH))         # el vendedor no acepta por el comprador
    with pytest.raises(ValidationError): run(Q.decide(c, "seller", r["id"], "quizas"))
    assert run(Q.list_requests(c, "tercero", "incoming")) == [] and len(run(Q.list_requests(c, "seller", "incoming"))) == 1
    with pytest.raises(ValidationError): run(Q.list_requests(c, "seller", "todas"))


def test_pipeline_enlazado_no_se_edita_a_mano():
    from services import my_space as S
    c = world(); o, r = flow_until_request(c)
    item = pipe(c, "buyer")[0]
    with pytest.raises(ValidationError): run(S.update_item(c["pipeline"], "buyer", item["id"], {"status": "nda_firmado"}))
    with pytest.raises(ValidationError): run(S.update_item(c["pipeline"], "buyer", item["id"], {"turn": "mine"}))
    ok = run(S.update_item(c["pipeline"], "buyer", item["id"], {"notes": "Llamar el lunes"}))
    assert ok["notes"] == "Llamar el lunes" and ok["status"] == "contactado"


def test_no_se_puede_firmar_saltandose_al_vendedor():
    c = world(); o, r = flow_until_request(c)
    with pytest.raises(ValidationError): run(Q.accept_nda(c, "buyer", r["id"], Q.NDA_HASH))     # aún pending


def test_rutas_http(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import my_space as R

    c = world()
    fake = type("DB", (), {"my_space_objects": c["objects"], "my_space_requests": c["requests"], "my_space_pipeline": c["pipeline"]})()
    monkeypatch.setattr(R, "db", fake)
    monkeypatch.setattr(R, "_user_id", lambda user, request=None: request.headers.get("x-arroba-user-id", "buyer"))
    monkeypatch.setattr(R, "_caller_is_jwt_user", lambda r: False)
    app = FastAPI(); app.include_router(R.router)
    app.dependency_overrides[R.get_current_user] = lambda: {"id": "svc"}
    cl = TestClient(app)
    S = {"x-arroba-user-id": "seller"}
    assert cl.put("/api/v1/my-space/object/publish", json={"published": True}, headers=S).json()["listing"]["cnae_code"] == "5610"
    mk = cl.get("/api/v1/my-space/marketplace").json()
    assert mk["count"] == 1 and SECRET_NAME not in json.dumps(mk)
    lid = mk["listings"][0]["listing_id"]
    r = cl.post("/api/v1/my-space/requests", json={"listing_id": lid, "as_role": "comprador"}, headers={"x-arroba-user-name": "Ana%20N%C3%BA%C3%B1ez"})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    rid = r.json()["id"]
    assert cl.get("/api/v1/my-space/requests", params={"box": "incoming"}, headers=S).json()["requests"][0]["buyer"]["name"] == "Ana Núñez"
    assert cl.post(f"/api/v1/my-space/requests/{rid}/decision", json={"decision": "accept"}).status_code == 404       # el comprador no decide
    assert cl.post(f"/api/v1/my-space/requests/{rid}/decision", json={"decision": "accept"}, headers=S).json()["status"] == "awaiting_buyer_nda"
    tpl = cl.get("/api/v1/my-space/nda-template").json()
    assert cl.post(f"/api/v1/my-space/requests/{rid}/accept-nda", json={"text_hash": "x"}).status_code == 422
    ok = cl.post(f"/api/v1/my-space/requests/{rid}/accept-nda", json={"text_hash": tpl["hash"]}).json()
    assert ok["status"] == "nda_signed" and ok["disclosed"]["cif"] == SECRET_CIF
    assert cl.get(f"/api/v1/my-space/requests/{rid}", headers={"x-arroba-user-id": "intruso"}).status_code == 404
    assert cl.get("/api/v1/my-space/requests/summary").json()["nda_signed"] == 1
