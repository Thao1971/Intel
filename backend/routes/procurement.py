"""Public Procurement — Routes for contract ingestion, CPV scope, and company matching."""

import asyncio
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File
from typing import Optional, Dict
from database import db
from models import new_id, now_iso
from auth_utils import get_current_user
from services.procurement_connector import parse_and_ingest_csv, INITIAL_CPV_SCOPE
import logging

logger = logging.getLogger(__name__)
_bg_tasks: set = set()

router = APIRouter(prefix="/api/v1/public-procurement", tags=["public_procurement"])

# 2026-09-02: alerta Atlas "Query Targeting" (scanned/returned ~7.100) — /status, /overview
# y /validation-report reconstruian sus cifras desde cero en cada llamada, cada una con un
# count_documents({}) (COLLSCAN completo de las 659k+ contratos) mas, en /overview y
# /validation-report, una docena larga de aggregates/counts adicionales sobre toda la
# coleccion. Mismo patron ya usado y aprobado en services/platform_stats.py: cache en memoria
# con TTL + estimated_document_count() (metadatos de la coleccion, no escanea) para la cifra
# de "total". Los datos de contratacion solo cambian con el re-sync (semanal, ver
# placsp_scheduler.py), asi que un TTL de minutos no oculta nada relevante; se invalida ademas
# al terminar un sync manual o automatico (ver _invalidate_procurement_caches()).
_STATUS_CACHE: Dict = {"data": None, "expires": 0.0}
_OVERVIEW_CACHE: Dict = {"data": None, "expires": 0.0}
_VALIDATION_CACHE: Dict = {"data": None, "expires": 0.0}

STATUS_CACHE_TTL_SECONDS = 60
OVERVIEW_CACHE_TTL_SECONDS = 600
VALIDATION_CACHE_TTL_SECONDS = 600


async def _total_contracts() -> int:
    """Estimacion rapida (metadatos de la coleccion, sin COLLSCAN) para la cifra de cabecera
    'total_contracts'. Mismo criterio que platform_stats._count(): no necesitamos precision
    absoluta en un contador de cabecera, y esto evita el escaneo completo que disparo la
    alerta de Atlas."""
    try:
        return await db.public_procurement_contracts.estimated_document_count()
    except Exception:
        return await db.public_procurement_contracts.count_documents({}, hint="_id_")


def _invalidate_procurement_caches():
    """Fuerza a recalcular /status, /overview y /validation-report en su proxima llamada.
    Se llama tras cada sync (manual o PLACSP) para que la cache corta no oculte datos nuevos."""
    _STATUS_CACHE["expires"] = 0.0
    _OVERVIEW_CACHE["expires"] = 0.0
    _VALIDATION_CACHE["expires"] = 0.0


# ══════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════

@router.get("/status")
async def procurement_status(user=Depends(get_current_user)):
    now = time.time()
    if _STATUS_CACHE["data"] is not None and _STATUS_CACHE["expires"] > now:
        return _STATUS_CACHE["data"]

    total = await _total_contracts()
    matched = await db.public_procurement_contracts.count_documents({"matched_company_id": {"$ne": None}})
    pending = await db.public_procurement_contracts.count_documents({"review_status": "pending_review"})
    visible = await db.public_procurement_contracts.count_documents({"visible_in_valuo": True})
    cpv_active = await db.procurement_cpv_scope.count_documents({"enabled": True})

    total_amount = 0
    pipeline = [{"$match": {"amount": {"$ne": None}}}, {"$group": {"_id": None, "total": {"$sum": "$amount"}}}]
    agg = await db.public_procurement_contracts.aggregate(pipeline).to_list(1)
    if agg:
        total_amount = round(agg[0]["total"], 2)

    last_sync = await db.procurement_sync_logs.find_one({}, {"_id": 0, "synced_at": 1}, sort=[("synced_at", -1)])
    last_log = await db.procurement_sync_logs.find_one({}, {"_id": 0}, sort=[("synced_at", -1)])

    data = {
        "provider": "public_procurement",
        "name": "Contratacion Publica",
        "total_contracts": total,
        "matched_companies": matched,
        "pending_review": pending,
        "visible_in_valuo": visible,
        "total_amount_eur": total_amount,
        "cpv_codes_active": cpv_active,
        "last_sync_at": last_sync.get("synced_at") if last_sync else None,
        "last_sync_stats": last_log,
    }
    _STATUS_CACHE["data"] = data
    _STATUS_CACHE["expires"] = now + STATUS_CACHE_TTL_SECONDS
    return data


@router.get("/overview")
async def procurement_overview():
    """Comprehensive overview for the Contratacion Publica page. Public endpoint.

    2026-09-06 - Daniel (520 intermitentes en financial-intelligence/analyze): las ~15
    count_documents/aggregate/distinct de aqui abajo son independientes entre si (cada
    una filtra o agrupa por su cuenta la coleccion completa de 659k+ contratos) pero se
    lanzaban en serie, una detras de otra. En cada cache-miss (una vez cada
    OVERVIEW_CACHE_TTL_SECONDS = 600s) eso mantenia ~12 COLLSCANs seguidos activos varios
    segundos en el cluster Arroba-pro. El performance advisor de Atlas + el slow query log
    (COLLSCAN de 659.486 docs, repetido) muestran picos de carga en ese cluster que
    coinciden con los 520 intermitentes reportados en financial-intelligence/analyze (mismo
    cluster, distinto endpoint). Lanzar estas llamadas con asyncio.gather no reduce el
    volumen escaneado (eso ya lo resuelve el cacheo con TTL de arriba) pero si comprime la
    ventana de varios segundos de carga simultanea a la duracion de la mas lenta de todas,
    bajando la presion punta sobre el cluster durante ese refresco. No cambia ni un solo
    resultado devuelto: mismos filtros, mismas agregaciones, solo se piden en paralelo.
    """
    now = time.time()
    if _OVERVIEW_CACHE["data"] is not None and _OVERVIEW_CACHE["expires"] > now:
        return _OVERVIEW_CACHE["data"]

    total = await _total_contracts()
    if total == 0:
        return {"total_contracts": 0}

    field_names = ["expediente", "cpv_code", "contract_type", "award_date", "publication_date",
                   "buyer_name", "buyer_nif", "buyer_city", "awardee_name"]

    (
        amount_agg,
        with_nif,
        unique_nif_list,
        unique_buyer_list,
        type_agg,
        cpv_agg,
        empresas_ab,
        personas,
        field_counts,
        amount_gt0,
        econ_metrics,
        econ_signals,
        last_sync,
    ) = await asyncio.gather(
        db.public_procurement_contracts.aggregate([
            {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$amount", 0]}},
                        "avg": {"$avg": {"$ifNull": ["$amount", 0]}},
                        "max": {"$max": "$amount"}}}
        ]).to_list(1),
        db.public_procurement_contracts.count_documents({"awardee_tax_id": {"$nin": [None, ""]}}),
        db.public_procurement_contracts.distinct("awardee_tax_id", {"awardee_tax_id": {"$nin": [None, ""]}}),
        db.public_procurement_contracts.distinct("buyer_name", {"buyer_name": {"$nin": [None, ""]}}),
        db.public_procurement_contracts.aggregate([
            {"$group": {"_id": "$contract_type", "count": {"$sum": 1}, "amount": {"$sum": {"$ifNull": ["$amount", 0]}}}},
            {"$sort": {"count": -1}},
        ]).to_list(10),
        db.public_procurement_contracts.aggregate([
            {"$match": {"cpv_code": {"$nin": [None, ""]}}},
            {"$group": {"_id": {"$substr": ["$cpv_code", 0, 2]}, "count": {"$sum": 1},
                        "amount": {"$sum": {"$ifNull": ["$amount", 0]}}}},
            {"$sort": {"count": -1}},
            {"$limit": 12},
        ]).to_list(12),
        # NIF type breakdown (count contracts, not unique NIFs — faster and no substr issue)
        db.public_procurement_contracts.count_documents({"awardee_tax_id": {"$regex": "^[AB]"}}),
        db.public_procurement_contracts.count_documents({"awardee_tax_id": {"$regex": "^[0-9XYZ]"}}),
        asyncio.gather(*[
            db.public_procurement_contracts.count_documents({f: {"$nin": [None, ""]}})
            for f in field_names
        ]),
        db.public_procurement_contracts.count_documents({"amount": {"$gt": 0}}),
        db.economic_metrics.count_documents({"source": "procurement"}),
        db.economic_signals.count_documents({"signal_type": "public_demand"}),
        db.procurement_sync_logs.find_one({}, {"_id": 0}, sort=[("synced_at", -1)]),
    )

    amount = amount_agg[0] if amount_agg else {}
    unique_nifs = len(unique_nif_list)
    unique_buyers = len(unique_buyer_list)

    # Field coverage
    fields = dict(zip(field_names, field_counts))
    fields["awardee_tax_id"] = with_nif
    fields["amount"] = amount_gt0

    data = {
        "total_contracts": total,
        "total_amount_eur": round(amount.get("total", 0), 2),
        "avg_amount_eur": round(amount.get("avg", 0), 2),
        "max_amount_eur": amount.get("max", 0),
        "unique_adjudicatarios": unique_nifs,
        "unique_compradores": unique_buyers,
        "contracts_with_nif": with_nif,
        "contracts_with_nif_pct": round(with_nif / total * 100, 1) if total > 0 else 0,
        "empresas_sa_sl": empresas_ab,
        "personas_fisicas": personas,
        "contract_types": [{"type": t["_id"] or "sin_tipo", "count": t["count"],
                            "amount": round(t["amount"], 2)} for t in type_agg],
        "top_cpv": [{"cpv": c["_id"], "count": c["count"],
                     "amount": round(c["amount"], 2)} for c in cpv_agg],
        "field_coverage": {k: {"count": v, "pct": round(v / total * 100, 1)} for k, v in fields.items()},
        "economic_intelligence": {"metrics": econ_metrics, "signals": econ_signals},
        "last_sync": last_sync,
    }
    _OVERVIEW_CACHE["data"] = data
    _OVERVIEW_CACHE["expires"] = now + OVERVIEW_CACHE_TTL_SECONDS
    return data


# ══════════════════════════════════════════
# CONTRACTS
# ══════════════════════════════════════════

@router.get("/contracts")
async def list_contracts(
    search: Optional[str] = None,
    matched: Optional[bool] = None,
    company_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user)
):
    query = {}
    if search:
        query["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"awardee_name": {"$regex": search, "$options": "i"}},
            {"buyer_name": {"$regex": search, "$options": "i"}},
        ]
    if matched is True:
        query["matched_company_id"] = {"$ne": None}
    elif matched is False:
        query["matched_company_id"] = None
    if company_id:
        query["matched_company_id"] = company_id

    # Empty searches still require an exact total. Use the existing covering
    # index; filtered searches retain the planner's choice of index.
    total = await db.public_procurement_contracts.count_documents(
        query, **({"hint": "_id_"} if not query else {})
    )
    contracts = await db.public_procurement_contracts.find(query, {"_id": 0}).sort("award_date", -1).skip(offset).limit(limit).to_list(limit)
    return {"contracts": contracts, "total": total}


@router.get("/contracts/{contract_id}")
async def get_contract(contract_id: str, user=Depends(get_current_user)):
    c = await db.public_procurement_contracts.find_one({"contract_id": contract_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Contrato no encontrado")
    return c


@router.get("/company/{company_id}")
async def company_procurement(company_id: str, user=Depends(get_current_user)):
    """Get procurement summary for a company."""
    contracts = await db.public_procurement_contracts.find(
        {"matched_company_id": company_id}, {"_id": 0}
    ).sort("award_date", -1).to_list(100)

    total_amount = sum(c.get("amount", 0) or 0 for c in contracts)
    buyers = {}
    cpvs = {}
    for c in contracts:
        b = c.get("buyer_name", "Desconocido")
        buyers[b] = buyers.get(b, 0) + 1
        cpv = c.get("cpv_code", "?")
        cpvs[cpv] = cpvs.get(cpv, 0) + 1

    return {
        "company_id": company_id,
        "total_contracts": len(contracts),
        "total_amount_eur": round(total_amount, 2),
        "top_buyers": sorted(buyers.items(), key=lambda x: x[1], reverse=True)[:5],
        "top_cpvs": sorted(cpvs.items(), key=lambda x: x[1], reverse=True)[:5],
        "last_award": contracts[0].get("award_date") if contracts else None,
        "contracts": contracts[:20],
    }


# ══════════════════════════════════════════
# CPV SCOPE
# ══════════════════════════════════════════

@router.get("/cpv-scope")
async def list_cpv_scope(user=Depends(get_current_user)):
    scope = await db.procurement_cpv_scope.find({}, {"_id": 0}).sort("cpv", 1).to_list(100)
    if not scope:
        await _seed_cpv_scope()
        scope = await db.procurement_cpv_scope.find({}, {"_id": 0}).sort("cpv", 1).to_list(100)
    return {"cpv_scope": scope, "total": len(scope)}


@router.post("/cpv-scope/{cpv}/enable")
async def enable_cpv(cpv: str, user=Depends(get_current_user)):
    await db.procurement_cpv_scope.update_one({"cpv": cpv}, {"$set": {"enabled": True, "updated_at": now_iso()}})
    return {"status": "enabled", "cpv": cpv}


@router.post("/cpv-scope/{cpv}/disable")
async def disable_cpv(cpv: str, user=Depends(get_current_user)):
    await db.procurement_cpv_scope.update_one({"cpv": cpv}, {"$set": {"enabled": False, "updated_at": now_iso()}})
    return {"status": "disabled", "cpv": cpv}


# ══════════════════════════════════════════
# SYNC
# ══════════════════════════════════════════

@router.post("/sync")
async def sync_procurement(file: UploadFile = File(...), user=Depends(get_current_user)):
    """Upload a CSV dataset from datos.gob.es for ingestion."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Solo se aceptan ficheros CSV")

    content = await file.read()
    try:
        csv_text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            csv_text = content.decode("latin-1")
        except Exception:
            raise HTTPException(400, "No se puede leer el fichero. Encoding no soportado.")

    email = user.get("email", user.get("id"))
    source_url = f"upload:{file.filename}"

    result = await parse_and_ingest_csv(csv_text, source_url, email)
    _invalidate_procurement_caches()
    return result


@router.get("/sync-logs")
async def list_sync_logs(limit: int = Query(20, ge=1, le=100), user=Depends(get_current_user)):
    logs = await db.procurement_sync_logs.find({}, {"_id": 0}).sort("synced_at", -1).limit(limit).to_list(limit)
    return {"logs": logs}


@router.post("/sync-placsp")
async def sync_placsp_endpoint(
    years: str = Query(None, description="Comma-separated years, e.g. '2025,2026'"),
    dataset: str = Query("menores", description="menores, licitaciones, or agregadas"),
    max_files: int = Query(None, description="Limit atom files per ZIP (for testing)"),
    user=Depends(get_current_user),
):
    """Lanza el sync REAL de PLACSP (ZIPs oficiales, Atom XML CODICE 2.07) en segundo plano.

    Evita el Proxy Read Timeout de 120 s. Resultado: GET /public-procurement/sync-placsp-state
    (status: idle | running | done; `result` = respuesta de sync_placsp).
    """
    year_list = [int(y.strip()) for y in years.split(",")] if years else None

    current = await db.placsp_sync_state.find_one({"_id": "current"})
    if current and current.get("status") == "running":
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(current["started_at"].replace("Z", "+00:00"))).total_seconds()
        except (KeyError, ValueError):
            age = 9999
        if age < 3600:  # un "running" de >1 h se considera huerfano
            return {"status": "running", "started_at": current["started_at"]}

    started_at = now_iso()
    await db.placsp_sync_state.replace_one(
        {"_id": "current"}, {"_id": "current", "status": "running", "started_at": started_at}, upsert=True)
    task = asyncio.create_task(_run_placsp_sync(year_list, dataset, max_files, started_at))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"status": "running", "started_at": started_at}


async def _run_placsp_sync(year_list, dataset, max_files, started_at):
    from services.placsp_connector import sync_placsp
    try:
        result = await sync_placsp(years=year_list, dataset=dataset, max_files=max_files)
        _invalidate_procurement_caches()
    except Exception as e:
        logger.error(f"PLACSP sync failed: {e}")
        result = {"status": "error", "message": str(e)[:200], "errors": [str(e)[:200]]}
    await db.placsp_sync_state.replace_one(
        {"_id": "current"},
        {"_id": "current", "status": "done", "started_at": started_at,
         "finished_at": now_iso(), "result": result},
        upsert=True,
    )


@router.get("/sync-placsp-state")
async def sync_placsp_state(user=Depends(get_current_user)):
    """Estado del ultimo sync lanzado con POST /sync-placsp."""
    doc = await db.placsp_sync_state.find_one({"_id": "current"}, {"_id": 0})
    return doc or {"status": "idle"}


# ══════════════════════════════════════════
# VALIDATION REPORT
# ══════════════════════════════════════════

@router.get("/validation-report")
async def validation_report(user=Depends(get_current_user)):
    """Full validation report for procurement data quality."""
    now = time.time()
    if _VALIDATION_CACHE["data"] is not None and _VALIDATION_CACHE["expires"] > now:
        return _VALIDATION_CACHE["data"]

    total = await _total_contracts()
    matched = await db.public_procurement_contracts.count_documents({"matched_company_id": {"$ne": None}})
    pending = await db.public_procurement_contracts.count_documents({"review_status": "pending_review"})
    unmatched = await db.public_procurement_contracts.count_documents({"review_status": "unmatched"})
    auto_matched = await db.public_procurement_contracts.count_documents({"review_status": "auto_matched"})

    # Amount stats
    amt_pipeline = [
        {"$match": {"amount": {"$ne": None}}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}, "avg": {"$avg": "$amount"}, "count": {"$sum": 1}}}
    ]
    amt = await db.public_procurement_contracts.aggregate(amt_pipeline).to_list(1)
    amt = amt[0] if amt else {"total": 0, "avg": 0, "count": 0}

    matched_amt_pipeline = [
        {"$match": {"amount": {"$ne": None}, "matched_company_id": {"$ne": None}}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]
    matched_amt = await db.public_procurement_contracts.aggregate(matched_amt_pipeline).to_list(1)
    matched_amount = matched_amt[0]["total"] if matched_amt else 0

    # Top adjudicatarios
    awardee_pipeline = [
        {"$group": {"_id": "$awardee_name", "count": {"$sum": 1}, "total": {"$sum": {"$ifNull": ["$amount", 0]}}, "matched": {"$first": "$matched_company_id"}}},
        {"$sort": {"total": -1}}, {"$limit": 10}
    ]
    top_awardees = await db.public_procurement_contracts.aggregate(awardee_pipeline).to_list(10)

    # Top compradores
    buyer_pipeline = [
        {"$group": {"_id": "$buyer_name", "count": {"$sum": 1}, "total": {"$sum": {"$ifNull": ["$amount", 0]}}}},
        {"$sort": {"total": -1}}, {"$limit": 10}
    ]
    top_buyers = await db.public_procurement_contracts.aggregate(buyer_pipeline).to_list(10)

    # Top CPVs
    cpv_pipeline = [
        {"$group": {"_id": "$cpv_code", "count": {"$sum": 1}, "total": {"$sum": {"$ifNull": ["$amount", 0]}}}},
        {"$sort": {"count": -1}}, {"$limit": 10}
    ]
    top_cpvs = await db.public_procurement_contracts.aggregate(cpv_pipeline).to_list(10)

    # Match quality
    cif_matches = await db.public_procurement_contracts.count_documents({
        "match_confidence": {"$gte": 95}, "matched_company_id": {"$ne": None}
    })
    name_matches = await db.public_procurement_contracts.count_documents({
        "match_confidence": {"$gte": 70, "$lt": 95}, "matched_company_id": {"$ne": None}
    })

    # Companies with procurement
    companies_pipeline = [
        {"$match": {"matched_company_id": {"$ne": None}}},
        {"$group": {"_id": "$matched_company_id"}},
        {"$count": "total"}
    ]
    companies_with = await db.public_procurement_contracts.aggregate(companies_pipeline).to_list(1)
    companies_count = companies_with[0]["total"] if companies_with else 0

    data = {
        "summary": {
            "total_contracts": total,
            "matched": matched,
            "auto_matched": auto_matched,
            "pending_review": pending,
            "unmatched": unmatched,
            "match_rate_pct": round(matched / max(total, 1) * 100, 1),
        },
        "amounts": {
            "total_eur": round(amt.get("total", 0), 2),
            "matched_eur": round(matched_amount, 2),
            "average_eur": round(amt.get("avg", 0), 2),
            "with_amount": amt.get("count", 0),
        },
        "match_quality": {
            "cif_exact_matches": cif_matches,
            "name_matches": name_matches,
            "companies_with_procurement": companies_count,
        },
        "top_awardees": [{"name": a["_id"], "contracts": a["count"], "amount": round(a["total"], 2), "matched": a.get("matched") is not None} for a in top_awardees],
        "top_buyers": [{"name": b["_id"], "contracts": b["count"], "amount": round(b["total"], 2)} for b in top_buyers],
        "top_cpvs": [{"cpv": c["_id"], "contracts": c["count"], "amount": round(c["total"], 2)} for c in top_cpvs],
    }
    _VALIDATION_CACHE["data"] = data
    _VALIDATION_CACHE["expires"] = now + VALIDATION_CACHE_TTL_SECONDS
    return data


# ══════════════════════════════════════════
# INTERNAL
# ══════════════════════════════════════════

async def _seed_cpv_scope():
    now = now_iso()
    for cpv in INITIAL_CPV_SCOPE:
        existing = await db.procurement_cpv_scope.find_one({"cpv": cpv["cpv"]})
        if not existing:
            await db.procurement_cpv_scope.insert_one({
                **cpv, "enabled": True, "category_mapping": None,
                "created_at": now, "updated_at": now,
            })
