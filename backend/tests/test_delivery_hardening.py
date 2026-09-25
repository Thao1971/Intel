"""Endurecimiento de la entrega: config de producción y propietario de valoraciones."""
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_hardening")

from config_guard import assert_production_config, config_problems, is_production

GOOD = {"ARROBA_ENV": "production", "JWT_SECRET": "x" * 40, "CORS_ORIGINS": "https://beta.example.com"}


def test_config_ok_en_produccion():
    assert config_problems(GOOD) == []
    assert_production_config(GOOD)


@pytest.mark.parametrize("patch", [
    {"JWT_SECRET": "default-secret"},
    {"JWT_SECRET": "corta"},
    {"CORS_ORIGINS": "*"},
    {"AUTO_BOOTSTRAP_DATA_LAYER": "1"},
])
def test_produccion_falla_con_config_insegura(patch):
    with pytest.raises(RuntimeError):
        assert_production_config({**GOOD, **patch})


def test_fuera_de_produccion_solo_avisa():
    env = {"JWT_SECRET": "default-secret"}
    assert not is_production(env)
    assert_production_config(env)


class _Req:
    def __init__(self, headers): self.headers = headers


def test_user_id_servicio_sin_cabecera_es_400(monkeypatch):
    from routes import valuations as v
    monkeypatch.setattr(v, "_caller_is_jwt_user", lambda r: False)
    with pytest.raises(HTTPException) as e:
        v._user_id({"id": "svc"}, _Req({}))
    assert e.value.status_code == 400


def test_user_id_servicio_usa_cabecera(monkeypatch):
    from routes import valuations as v
    monkeypatch.setattr(v, "_caller_is_jwt_user", lambda r: False)
    assert v._user_id({"id": "svc"}, _Req({"x-arroba-user-id": " u-7 "})) == "u-7"


def test_user_id_jwt_ignora_cabecera(monkeypatch):
    from routes import valuations as v
    monkeypatch.setattr(v, "_caller_is_jwt_user", lambda r: True)
    assert v._user_id({"id": "real"}, _Req({"x-arroba-user-id": "victima"})) == "real"
