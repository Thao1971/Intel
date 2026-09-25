"""Vigilancia por usuario: seguimiento por CIF -> alertas reales (BD en memoria)."""
import asyncio
import os

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_vigilance")

from services import my_space_vigilance as V  # noqa: E402
from services import watchlist as W  # noqa: E402
from services.my_space import ValidationError  # noqa: E402


def run(c): return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)


def _get(d, path):
    for p in path.split("."):
        d = (d or {}).get(p) if isinstance(d, dict) else None
    return d


class Cur:
    def __init__(self, rows): self.rows = rows
    def sort(self, key, direction=-1):
        self.rows = sorted(self.rows, key=lambda r: r.get(key) or "", reverse=direction == -1); return self
    async def to_list(self, n): return [dict(r) for r in self.rows[:n]]
    def __aiter__(self):
        self._it = iter([dict(r) for r in self.rows]); return self
    async def __anext__(self):
        try: return next(self._it)
        except StopIteration: raise StopAsyncIteration


class Coll:
    def __init__(self, docs=None, unique=None): self.docs = list(docs or []); self.unique = unique
    def _m(self, d, q):
        for k, v in q.items():
            got = _get(d, k) if "." in k else d.get(k)
            if isinstance(v, dict) and "$in" in v:
                if got not in v["$in"]: return False
            elif got != v: return False
        return True
    async def create_index(self, *a, **k): return None
    async def find_one(self, q, proj=None):
        for d in self.docs:
            if self._m(d, q): return dict(d)
    async def insert_one(self, doc):
        if self.unique and any(all(d.get(k) == doc.get(k) for k in self.unique) for d in self.docs):
            raise RuntimeError("duplicate key")
        self.docs.append(dict(doc))
    def find(self, q, proj=None): return Cur([d for d in self.docs if self._m(d, q)])
    async def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if self._m(d, q):
                self.docs.pop(i); return type("R", (), {"deleted_count": 1})()
        return type("R", (), {"deleted_count": 0})()
    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._m(d, q):
                d.update(upd["$set"]); return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()
    async def count_documents(self, q): return sum(1 for d in self.docs if self._m(d, q))
    async def distinct(self, k): return list({d[k] for d in self.docs})


@pytest.fixture
def fake(monkeypatch):
    db = type("DB", (), {})()
    db.watchlist = Coll(unique=("user_id", "master_id"))
    db.watchlist_alerts = Coll(unique=("user_id", "signal_id"))
    db.signals = Coll([{"signal_id": "s1", "master_id": "m1", "status": "active", "signal_type": "succession", "category": "risk",
                        "first_detected_at": "2026-09-01", "explanation": "Administrador de 72 años"},
                       {"signal_id": "s2", "master_id": "m2", "status": "active", "signal_type": "growth", "category": "opp"},
                       {"signal_id": "s3", "master_id": "m1", "status": "closed"}])
    master = Coll([{"master_id": "m1", "cif_normalized": "B111", "identity": {"legal_name": "Uno SL"}},
                   {"master_id": "m2", "cif_normalized": "B222", "identity": {"legal_name": "Dos SL"}}])
    monkeypatch.setattr(W, "db", db)
    W._INDEXED = True
    return db, master


def test_sync_crea_alertas_solo_de_senales_reales_activas(fake):
    db, master = fake
    r = run(V.sync_watches("u1", ["b-111", "B999"], master))
    assert r == {"watching": 1, "unresolved": ["B999"], "alerts_created": 1}
    out = run(V.list_alerts("u1", master))
    assert out["unread"] == 1 and out["alerts"][0]["company_name"] == "Uno SL" and out["alerts"][0]["explanation"] == "Administrador de 72 años"
    assert run(V.sync_watches("u1", ["B111"], master))["alerts_created"] == 0   # idempotente


def test_sync_refleja_altas_y_bajas_y_aisla_usuarios(fake):
    db, master = fake
    run(V.sync_watches("u1", ["B111", "B222"], master))
    run(V.sync_watches("u2", ["B222"], master))
    assert len(run(V.list_alerts("u1", master))["alerts"]) == 2
    assert len(run(V.list_alerts("u2", master))["alerts"]) == 1
    run(V.sync_watches("u1", ["B222"], master))                                  # deja de seguir Uno
    assert {w["master_id"] for w in db.watchlist.docs if w["user_id"] == "u1"} == {"m2"}


def test_marcar_leida_solo_la_propia(fake):
    db, master = fake
    run(V.sync_watches("u1", ["B111"], master))
    aid = run(V.list_alerts("u1", master))["alerts"][0]["alert_id"]
    assert run(W.mark_alert_read("u2", aid)) is False
    assert run(W.mark_alert_read("u1", aid)) is True
    assert run(V.list_alerts("u1", master))["unread"] == 0


def test_limite_de_empresas():
    with pytest.raises(ValidationError): V.normalize_cifs(["B%d" % i for i in range(501)])
    assert V.normalize_cifs(["b-1", "B1", " ", "b 2"]) == ["B1", "B2"]


def test_rutas_http(fake, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import my_space as R
    db, master = fake
    db.master_companies = master
    monkeypatch.setattr(R, "db", db)
    monkeypatch.setattr(R, "_user_id", lambda user, request=None: request.headers.get("x-arroba-user-id", "u1"))
    app = FastAPI(); app.include_router(R.router)
    app.dependency_overrides[R.get_current_user] = lambda: {"id": "svc"}
    c = TestClient(app)
    assert c.post("/api/v1/my-space/vigilance/sync", json={"cifs": ["B111"]}).json()["alerts_created"] == 1
    lst = c.get("/api/v1/my-space/vigilance").json()
    assert lst["unread"] == 1
    aid = lst["alerts"][0]["alert_id"]
    assert c.post(f"/api/v1/my-space/vigilance/alerts/{aid}/read", headers={"x-arroba-user-id": "u2"}).status_code == 404
    assert c.post(f"/api/v1/my-space/vigilance/alerts/{aid}/read").status_code == 200
    assert c.get("/api/v1/my-space/vigilance").json()["unread"] == 0
    assert c.post("/api/v1/my-space/vigilance/sync", json={"cifs": ["B%d" % i for i in range(501)]}).status_code == 422
