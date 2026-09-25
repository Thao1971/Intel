"""Guardián de configuración de producción.

Con `ARROBA_ENV=production` el arranque FALLA si la configuración es insegura. En otros
entornos solo se avisa en el log. Así una variable olvidada en Emergent no deja el servicio
funcionando con `JWT_SECRET` por defecto ni con CORS abierto.
"""
from __future__ import annotations

import logging
import os
from typing import List, Mapping, Optional

logger = logging.getLogger(__name__)

DEFAULT_JWT_SECRET = "default-secret"
PRODUCTION_VALUES = ("production", "prod")


def is_production(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return env.get("ARROBA_ENV", "").strip().lower() in PRODUCTION_VALUES


def config_problems(env: Optional[Mapping[str, str]] = None) -> List[str]:
    env = os.environ if env is None else env
    problems: List[str] = []
    secret = env.get("JWT_SECRET", DEFAULT_JWT_SECRET)
    if secret == DEFAULT_JWT_SECRET or len(secret) < 32:
        problems.append("JWT_SECRET no definido, es el valor por defecto o tiene menos de 32 caracteres")
    origins = [o.strip() for o in env.get("CORS_ORIGINS", "*").split(",") if o.strip()]
    if not origins or "*" in origins:
        problems.append("CORS_ORIGINS vacío o '*' (con credenciales): indicar el origen exacto de Beta")
    if env.get("AUTO_BOOTSTRAP_DATA_LAYER", "0") in ("1", "true", "True"):
        problems.append("AUTO_BOOTSTRAP_DATA_LAYER activo: puede generar datos sintéticos en producción")
    return problems


def assert_production_config(env: Optional[Mapping[str, str]] = None) -> None:
    problems = config_problems(env)
    if not problems:
        return
    if is_production(env):
        raise RuntimeError("Configuración insegura en producción: " + "; ".join(problems))
    for p in problems:
        logger.warning("CONFIG (no producción, solo aviso): %s", p)
