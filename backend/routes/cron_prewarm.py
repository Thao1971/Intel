"""Cron: precalentamiento de descripciones IA de compañías por lotes.

La plataforma dispara POST /api/cron/prewarm-descriptions según .emergent/crons.yml.
El endpoint ACK 2xx al instante y procesa el lote en segundo plano (asyncio.create_task).
Reanudable e idempotente (la caché excluye lo ya generado); lock por lease en Mongo
evita solapamiento entre disparos; se autolimita en tiempo y se queda en no-op cuando
no quedan pendientes.
"""
import asyncio
import hmac
import os
from collections import Counter
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from database import db
from services.company_summary import resolve_description
from services.cnae_es import cnae_label_es
from scripts.prewarm_company_descriptions import _candidates
from docstudio.model_provider import COMPANY_DESCRIPTION_PROMPT_VERSION

router = APIRouter(prefix="/api/cron", tags=["cron"])

_LOCK = "prewarm_cron_lock"
_RUNS = "prewarm_cron_runs"
_LOCK_ID = "prewarm-descriptions"
BATCH = int(os.environ.get("PREWARM_CRON_BATCH", "40"))
DELAY = float(os.environ.get("PREWARM_CRON_DELAY", "2"))
SEED = int(os.environ.get("PREWARM_CRON_SEED", "150926"))
LEASE_MIN = 14
SOFT_STOP_MIN = 12  # corta el lote antes de que expire el lease para no solapar


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


async def _acquire_lock(run_id: str) -> bool:
    now_iso = _iso(_now())
    lease_iso = _iso(_now() + timedelta(minutes=LEASE_MIN))
    doc = await db[_LOCK].find_one_and_update(
        {"_id": _LOCK_ID, "locked_until": {"$lt": now_iso}},
        {"$set": {"locked_until": lease_iso, "run_id": run_id, "acquired_at": now_iso}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is not None:
        return True
    try:
        await db[_LOCK].insert_one(
            {"_id": _LOCK_ID, "locked_until": lease_iso, "run_id": run_id, "acquired_at": now_iso})
        return True
    except DuplicateKeyError:
        return False  # existe y está tomado (locked_until en el futuro)


async def _release_lock():
    await db[_LOCK].update_one({"_id": _LOCK_ID}, {"$set": {"locked_until": _iso(_now())}})


async def _run_batch(run_id: str):
    if not await _acquire_lock(run_id):
        return  # otra tanda en curso; este disparo no hace nada
    started = _now()
    soft_deadline = started + timedelta(minutes=SOFT_STOP_MIN)
    ok = fail = attempted = 0
    models = Counter()
    fb = 0
    motivos = Counter()
    remaining = None
    try:
        pending = await _candidates(SEED, [])
        chunk = pending[:BATCH]
        remaining = max(len(pending) - len(chunk), 0)
        for row in chunk:
            if _now() >= soft_deadline:
                break
            mid = row["master_id"]
            attempted += 1
            try:
                objeto = (row.get("objeto_social") or "").strip()
                wd = row.get("web_description")
                web_text = wd.get("description") if isinstance(wd, dict) else wd
                identity = {"objeto_social": objeto, "description": web_text,
                            "legal_name": (row.get("identity") or {}).get("legal_name")}
                cnae = cnae_label_es((row.get("classification") or {}).get("cnae_code"))
                res = await resolve_description(mid, identity, cnae, generate_if_missing=True)
                if res.get("description_source") == "ai":
                    ok += 1
                    doc = await db.company_descriptions.find_one(
                        {"master_id": mid, "prompt_version": COMPANY_DESCRIPTION_PROMPT_VERSION},
                        {"_id": 0, "model": 1, "fallback_used": 1}) or {}
                    models[doc.get("model")] += 1
                    if doc.get("fallback_used"):
                        fb += 1
                else:
                    fail += 1
                    motivos[res.get("description_source") or "none"] += 1
            except Exception as e:
                fail += 1
                motivos["exception:" + type(e).__name__] += 1
            await asyncio.sleep(DELAY)
    finally:
        await _release_lock()
    await db[_RUNS].insert_one({
        "run_id": run_id,
        "started_at": _iso(started),
        "finished_at": _iso(_now()),
        "attempted": attempted,
        "generadas": ok,
        "fallidas": fail,
        "reparto_por_modelo": dict(models),
        "fallback_used": fb,
        "motivos": dict(motivos),
        "batch": BATCH,
        "pendientes_restantes": remaining,
        "cache_total": await db.company_descriptions.count_documents({}),
    })


@router.post("/prewarm-descriptions")
async def prewarm_descriptions_cron(request: Request):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    secret = os.environ.get("WEBHOOK_CRON_SECRET")
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    if not secret or not token or not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="unauthorized")
    run_id = request.headers.get("X-Webhook-Id") or _iso(_now())
    asyncio.create_task(_run_batch(run_id))
    return {"status": "accepted", "run_id": run_id, "batch": BATCH}
