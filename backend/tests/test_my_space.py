"""Mi espacio: perfil de rol y pipeline (sin Mongo real: colección en memoria)."""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_my_space")

from services import my_space as S  # noqa: E402


class FakeCursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, key, direction=-1):
        self.rows = sorted(self.rows, key=lambda r: r.get(key) or "", reverse=direction == -1); return self
    async def to_list(self, n): return [dict(r) for r in self.rows[:n]]


class FakeColl:
    def __init__(self): self.docs = []
    def _match(self, d, q): return all(d.get(k) == v for k, v in q.items())
    async def find_one(self, q, proj=None):
        for d in self.docs:
            if self._match(d, q): return dict(d)
    async def insert_one(self, doc): self.docs.append(dict(doc))
    def find(self, q, proj=None): return FakeCursor([d for d in self.docs if self._match(d, q)])
    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._match(d, q): d.update(upd["$set"]); return
        if upsert: self.docs.append({**q, **upd["$set"]})
    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if self._match(d, q):
                self.docs.pop(i)
                return type("R", (), {"deleted_count": 1})()
        return type("R", (), {"deleted_count": 0})()


def run(c): return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)


def test_perfil_valida_roles():
    assert S.normalize_profile(["comprador", "asesor"], "asesor")["active_role"] == "asesor"
    with pytest.raises(S.ValidationError): S.normalize_profile(["dios"], None)
    with pytest.raises(S.ValidationError): S.normalize_profile([], None)
    with pytest.raises(S.ValidationError): S.normalize_profile(["comprador"], "vendedor")


def test_turno_por_defecto_y_estado_sin_turno():
    c = FakeColl()
    it = run(S.create_item(c, "u1", "comprador", {"counterpart_name": "Delta", "status": "nda_enviado"}))
    assert it["turn"] == "their" and it["next_step"] == "Esperando respuesta del otro lado"
    it2 = run(S.create_item(c, "u1", "comprador", {"counterpart_name": "Rosell"}))
    assert it2["status"] == "sin_contactar" and it2["turn"] is None
    # turno explícito en un estado sin turno se descarta
    it3 = run(S.create_item(c, "u1", "comprador", {"counterpart_name": "X", "turn": "mine"}))
    assert it3["turn"] is None


def test_validaciones():
    c = FakeColl()
    with pytest.raises(S.ValidationError): run(S.create_item(c, "u1", "comprador", {"counterpart_name": " "}))
    with pytest.raises(S.ValidationError): run(S.create_item(c, "u1", "comprador", {"counterpart_name": "A", "status": "raro"}))
    with pytest.raises(S.ValidationError): run(S.create_item(c, "u1", "comprador", {"counterpart_name": "A", "status": "contactado", "turn": "nadie"}))
    with pytest.raises(S.ValidationError): run(S.create_item(c, "u1", "rol_falso", {"counterpart_name": "A"}))


def test_actualizar_cambia_turno_y_actividad():
    c = FakeColl()
    it = run(S.create_item(c, "u1", "vendedor", {"counterpart_name": "Fondo A", "status": "contactado"}))
    assert it["counterpart_type"] == "comprador"
    up = run(S.update_item(c, "u1", it["id"], {"status": "nda_firmado"}))
    assert up["turn"] == "mine" and up["next_step"].startswith("Compartir")
    up2 = run(S.update_item(c, "u1", it["id"], {"turn": "their"}))
    assert up2["turn"] == "their"
    up3 = run(S.update_item(c, "u1", it["id"], {"status": "descartada"}))
    assert up3["turn"] is None and up3["urgent"] is False


def test_aislamiento_entre_usuarios():
    c = FakeColl()
    it = run(S.create_item(c, "u1", "comprador", {"counterpart_name": "Privada"}))
    assert run(S.update_item(c, "u2", it["id"], {"notes": "x"})) is None
    assert run(S.delete_item(c, "u2", it["id"])) is False
    assert run(S.list_items(c, "u2", "comprador")) == []
    assert len(run(S.list_items(c, "u1", "comprador"))) == 1


def test_urgencia_y_resumen():
    old = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    base = {"status": "contactado", "turn": "their", "last_activity_at": old, "created_at": old}
    d = S.derive(base)
    assert d["urgent"] and d["days_idle"] >= 14
    assert not S.derive({**base, "status": "descartada", "turn": None})["urgent"]
    items = [S.derive(base), S.derive({"status": "nda_firmado", "turn": "mine", "created_at": old, "last_activity_at": datetime.now(timezone.utc).isoformat()}),
             S.derive({"status": "descartada", "turn": None, "created_at": old, "last_activity_at": old})]
    s = S.summarize(items)
    assert (s["total"], s["open"], s["my_turn"], s["waiting_other"], s["urgent"], s["discarded"]) == (3, 2, 1, 1, 1, 1)


def test_rutas_http_con_bd_falsa(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import my_space as R

    fake = type("DB", (), {"my_space_pipeline": FakeColl(), "my_space_profiles": FakeColl()})()
    monkeypatch.setattr(R, "db", fake)
    monkeypatch.setattr(R, "_user_id", lambda user, request=None: request.headers.get("x-arroba-user-id", "u1"))
    app = FastAPI(); app.include_router(R.router)
    app.dependency_overrides[R.get_current_user] = lambda: {"id": "svc"}
    c = TestClient(app)
    assert c.get("/api/v1/my-space/profile").json()["profile"] is None
    assert c.get("/api/v1/my-space/pipeline").status_code == 409  # sin rol no se adivina
    assert c.put("/api/v1/my-space/profile", json={"roles": ["comprador"]}).status_code == 200
    r = c.post("/api/v1/my-space/pipeline", json={"counterpart_name": "Kitchen", "status": "contactado"})
    assert r.status_code == 201
    lst = c.get("/api/v1/my-space/pipeline").json()
    assert lst["summary"]["waiting_other"] == 1 and lst["role"] == "comprador"
    assert c.post("/api/v1/my-space/pipeline", json={"counterpart_name": "", "status": "contactado"}).status_code == 422
    # otro usuario no ve ni toca lo ajeno
    h = {"x-arroba-user-id": "u2"}
    assert c.patch(f"/api/v1/my-space/pipeline/{r.json()['id']}", json={"notes": "z"}, headers=h).status_code == 404
    assert c.delete(f"/api/v1/my-space/pipeline/{r.json()['id']}", headers=h).status_code == 404
    assert c.delete(f"/api/v1/my-space/pipeline/{r.json()['id']}").status_code == 200
