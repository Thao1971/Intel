from fastapi import FastAPI, Response, Depends, Query
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone
from models import new_id

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from database import db, client
from auth_utils import get_current_user
from services.storage import init_storage, get_object
from services.worker import start_worker, stop_worker, get_worker_status
from documents.routes import router as documents_router
from documents.worker import start_doc_worker, stop_doc_worker
from borme.routes import router as borme_router
from borme.scheduler import start_borme_scheduler, stop_borme_scheduler
from services.intelligence_scheduler import start_intelligence_scheduler, stop_intelligence_scheduler
from services.watchlist_scheduler import start_watchlist_scheduler, stop_watchlist_scheduler
from services.datacomex_scheduler import start_datacomex_scheduler, stop_datacomex_scheduler
from services.ine_demography_scheduler import start_ine_demography_scheduler, stop_ine_demography_scheduler
from services.cnmv_bme_scheduler import start_cnmv_bme_scheduler, stop_cnmv_bme_scheduler
from services.placsp_scheduler import start_placsp_scheduler, stop_placsp_scheduler
from editorial.routes import router as editorial_router
from editorial.worker import start_editorial_worker, stop_editorial_worker
from transactions.routes import router as transactions_router
from routes.auth import router as auth_router
from routes.scrape import router as scrape_router
from routes.results import router as results_router
from routes.taxonomy import router as taxonomy_router
from routes.providers import router as providers_router
from routes.master import router as master_router
from routes.valuo_integration import router as valuo_router
from routes.intelligence_engine import router as intelligence_engine_router
from routes.engine_info import router as engine_info_router
from routes.enriched_company import router as enriched_company_router
from routes.data_providers import router as data_providers_router
from routes.publication import router as publication_router
from routes.market_context import router as market_context_router
from routes.registry import router as registry_router
from routes.procurement import router as procurement_router
from routes.banco_espana import router as banco_espana_router
from routes.business_demography import router as business_demography_router
from routes.sector_intelligence import router as sector_intelligence_router, admin_router as sector_intel_admin_router
from routes.cnae_catalog import router as cnae_catalog_router
from routes.geo_intelligence import router as geo_intelligence_router
from routes.iberinform_admin import router as iberinform_admin_router
from routes.cache_admin import router as cache_admin_router
from routes.cross_intelligence import router as cross_intelligence_router
from routes.intelligence_status import router as intelligence_status_router
from routes.datacomex import router as datacomex_router
from routes.taxonomy_intelligence import router as taxonomy_intelligence_router
from routes.platform_stats import router as platform_stats_router
from routes.skills import router as skills_router
from routes.data_layer import router as data_layer_router
from routes.financial_intelligence import router as financial_intelligence_router
from routes.company_ficha import router as company_ficha_router
from routes.cron_prewarm import router as cron_prewarm_router
from routes.investment_intelligence import router as investment_intelligence_router
from routes.signal_intelligence import router as signal_intelligence_router
from routes.semantic_intelligence import router as semantic_intelligence_router
from routes.recommendation_intelligence import router as recommendation_intelligence_router
from routes.buyer_mandates import router as buyer_mandates_router
from routes.investment_decision import router as investment_decision_router
from routes.copilot import router as copilot_router
from routes.copilot_ui import router as copilot_ui_router
from routes.company_taxonomy import router as company_taxonomy_router
from routes.company_taxonomy_ui import router as company_taxonomy_ui_router
from routes.watchlist import router as watchlist_router
from routes.strategy_intelligence import router as strategy_intelligence_router
from routes.transaction_intelligence import router as transaction_intelligence_router
from routes.company_intelligence import router as company_intelligence_router
from routes.entity_bridge import router as entity_bridge_router
from routes.enrich_company import router as enrich_company_router
from routes.economic_intelligence import router as economic_intelligence_router
from routes.cnmv import router as cnmv_router
from docstudio.routes import router as docstudio_router
from routes.bme import router as bme_router
from routes.valuations import router as valuations_router
from routes.jobs import router as jobs_router
from routes.config import router as config_router
from routes.stats import router as stats_router
from routes.enrichment import router as enrichment_router, lookup_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agency Scraper API",
    version="1.0.0",
    description="API-first microservice for analyzing agency websites",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware — captures ALL incoming requests with timestamps
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import time

class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        path = request.url.path
        method = request.method
        has_auth = "Authorization" in request.headers
        auth_prefix = request.headers.get("Authorization", "")[:30] if has_auth else "NONE"

        # Log enrichment and key API calls
        if "/enrichment" in path or "/scrape" in path or "/health" in path:
            logger.info(f"REQ_IN  | {method} {path} | auth={auth_prefix}... | from={request.client.host if request.client else '?'}")

        response = await call_next(request)
        elapsed = round((time.time() - start) * 1000)

        if "/enrichment" in path or "/scrape" in path:
            logger.info(f"REQ_OUT | {method} {path} | HTTP {response.status_code} | {elapsed}ms | auth={'YES' if has_auth else 'NO'}")

        return response

app.add_middleware(RequestLogMiddleware)

# Include routers
app.include_router(auth_router)
app.include_router(scrape_router)
app.include_router(results_router)
app.include_router(taxonomy_router)
app.include_router(providers_router)
app.include_router(master_router)
app.include_router(valuo_router)
app.include_router(intelligence_engine_router)
app.include_router(engine_info_router)
app.include_router(enriched_company_router)
app.include_router(data_providers_router)
app.include_router(publication_router)
app.include_router(market_context_router)
app.include_router(registry_router)
app.include_router(procurement_router)
app.include_router(banco_espana_router)
app.include_router(business_demography_router)
app.include_router(sector_intelligence_router)
app.include_router(sector_intel_admin_router)
app.include_router(cnae_catalog_router)
app.include_router(geo_intelligence_router)
app.include_router(iberinform_admin_router)
app.include_router(cache_admin_router)
app.include_router(cross_intelligence_router)
app.include_router(intelligence_status_router)
app.include_router(datacomex_router)
app.include_router(taxonomy_intelligence_router)
app.include_router(platform_stats_router)
app.include_router(skills_router)
app.include_router(data_layer_router)
app.include_router(financial_intelligence_router)
app.include_router(company_ficha_router)
app.include_router(cron_prewarm_router)
app.include_router(investment_intelligence_router)
app.include_router(signal_intelligence_router)
app.include_router(semantic_intelligence_router)
app.include_router(recommendation_intelligence_router)
app.include_router(buyer_mandates_router)
app.include_router(investment_decision_router)
app.include_router(copilot_router)
app.include_router(copilot_ui_router)
app.include_router(company_taxonomy_router)
app.include_router(company_taxonomy_ui_router)
app.include_router(watchlist_router)
app.include_router(strategy_intelligence_router)
app.include_router(transaction_intelligence_router)
app.include_router(company_intelligence_router)
app.include_router(entity_bridge_router)
app.include_router(enrich_company_router)
app.include_router(economic_intelligence_router)
app.include_router(cnmv_router)
app.include_router(docstudio_router)
app.include_router(bme_router)
app.include_router(valuations_router)
app.include_router(jobs_router)
app.include_router(config_router)
app.include_router(stats_router)
app.include_router(enrichment_router)
app.include_router(lookup_router)
app.include_router(documents_router)
app.include_router(borme_router)
app.include_router(editorial_router)
app.include_router(transactions_router)
from routes.ai_chat import router as ai_chat_router
app.include_router(ai_chat_router)
from routes.companies import router as companies_router
app.include_router(companies_router)


# Hub endpoint
@app.get("/api/v1/hub/tools")
async def hub_tools():
    return {"tools": [
        {"id": "scraper", "name": "Agency Scraper", "description": "Web scraping, classification and agency enrichment", "path": "/analysis", "status": "active", "icon": "radar"},
        {"id": "documents", "name": "Document Generator", "description": "PDF reports with AI content and multi-brand templates", "path": "/documents", "status": "active", "icon": "file-text"},
        {"id": "assets", "name": "Assets Manager", "description": "Logos, brand profiles and design tokens", "path": "/brands", "status": "active", "icon": "palette"},
        {"id": "borme", "name": "BORME", "description": "Corporate events from official Spanish registry", "path": "/borme", "status": "active", "icon": "landmark"},
        {"id": "editorial", "name": "Editorial Intelligence", "description": "Sectoral news curation and weekly digest builder", "path": "/editorial", "status": "active", "icon": "newspaper"},
        {"id": "transactions", "name": "M&A Radar", "description": "Gestiona operaciones corporativas, fuentes, revision editorial y publicacion en CIS", "path": "/transactions", "status": "active", "icon": "activity"},
    ]}

@app.get("/api/v1/hub/health")
async def hub_health():
    return {"status": "healthy", "service": "agency-tools-hub", "version": "2.0.0", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── arroba.com public integration contract (filtered OpenAPI) ────────────────
# Full internal spec stays at /api/v1/openapi.json (all routes). This exposes ONLY
# the 6 public Intelligence Engines that arroba.com consumes, so the external
# contract is decoupled from internal admin/Valuo routes. Config/derived only —
# no engine endpoint or schema is changed.
from fastapi.openapi.utils import get_openapi as _get_openapi
from fastapi.openapi.docs import get_swagger_ui_html as _swagger_ui_html

ARROBA_ENGINE_PREFIXES = (
    "/api/v1/financial-intelligence",
    "/api/v1/signal-intelligence",
    "/api/v1/semantic-intelligence",
    "/api/v1/recommendation-intelligence",
    "/api/v1/strategy-intelligence",
    "/api/v1/transaction-intelligence",
)

# arroba.v2 = the six v1 engines (now with typed response DTOs) + the new public
# Company/Identity capability. v1 stays frozen byte-identical (responses stripped below);
# v2 is the typed superset for SDK generation.
ARROBA_V2_PREFIXES = ARROBA_ENGINE_PREFIXES + ("/api/v2/company-intelligence",)

import copy as _copy
import json as _json
_V1_SNAPSHOT_PATH = ROOT_DIR / "contracts" / "arroba.v1.json"


def _frozen_v1_schema_names() -> set:
    """Component schema names present in the frozen v1 snapshot (source of the freeze)."""
    try:
        snap = _json.loads(_V1_SNAPSHOT_PATH.read_text())
        return set(snap.get("components", {}).get("schemas", {}).keys())
    except Exception:
        return set()


def _collect_ref_names(node, acc: set):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str) and v.startswith("#/components/schemas/"):
                acc.add(v.rsplit("/", 1)[-1])
            else:
                _collect_ref_names(v, acc)
    elif isinstance(node, list):
        for it in node:
            _collect_ref_names(it, acc)


def _build_arroba_openapi() -> dict:
    """Frozen v1 public contract. Byte-identical to contracts/arroba.v1.json: response
    bodies are intentionally left untyped (schema={}) and components filtered to the frozen
    set, so adding v2 response DTOs to the engines never drifts v1."""
    full = app.openapi()
    paths = {p: _copy.deepcopy(item) for p, item in full.get("paths", {}).items()
             if any(p.startswith(pref) for pref in ARROBA_ENGINE_PREFIXES)}
    # Strip 200 response schemas to match the frozen (untyped) v1 surface.
    for item in paths.values():
        for op in item.values():
            if not isinstance(op, dict):
                continue
            ok = (op.get("responses") or {}).get("200")
            if ok and isinstance(ok.get("content"), dict):
                for media in ok["content"].values():
                    media["schema"] = {}
    spec = {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {
            "title": "Agency Tool — Intelligence API (arroba.com)",
            "version": "arroba-integration-contract-v1",
            "description": (
                "Contrato público de integración para arroba.com. Expone únicamente los 6 "
                "motores de inteligencia (Financial, Signal, Semantic, Recommendation, Strategy, "
                "Transaction). Auth: cabecera X-API-Key. Identidad por master_id. "
                "Fuente de verdad: ARROBA_INTEGRATION_CONTRACT_v1.md."
            ),
        },
        "paths": paths,
    }
    if "components" in full:
        comps = _copy.deepcopy(full["components"])
        frozen = _frozen_v1_schema_names()
        if frozen and "schemas" in comps:
            comps["schemas"] = {k: v for k, v in comps["schemas"].items() if k in frozen}
        spec["components"] = comps
    if "servers" in full:
        spec["servers"] = full["servers"]
    return spec


def _build_arroba_v2_openapi() -> dict:
    """Typed v2 public contract: the six engines (typed response DTOs) + Company/Identity.
    Components pruned to the schemas actually referenced by the v2 surface (no internal leak)."""
    full = app.openapi()
    paths = {p: _copy.deepcopy(item) for p, item in full.get("paths", {}).items()
             if any(p.startswith(pref) for pref in ARROBA_V2_PREFIXES)}
    refs: set = set()
    _collect_ref_names(paths, refs)
    all_schemas = (full.get("components") or {}).get("schemas", {})
    # transitive closure of referenced schemas
    seen: set = set()
    frontier = set(refs)
    while frontier:
        name = frontier.pop()
        if name in seen or name not in all_schemas:
            continue
        seen.add(name)
        sub: set = set()
        _collect_ref_names(all_schemas[name], sub)
        frontier |= (sub - seen)
    spec = {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {
            "title": "Agency Tool — Intelligence API (arroba.com) — v2",
            "version": "arroba-integration-contract-v2",
            "description": (
                "Contrato público v2 para arroba.com. Superset TIPADO de v1: los 6 motores de "
                "inteligencia con DTO de respuesta explícitos + la capacidad pública "
                "Company/Identity (/api/v2/company-intelligence). Auth: cabecera X-API-Key. "
                "Runtime idéntico a v1 (los DTO documentan, no filtran). Permite generar SDK tipado."
            ),
        },
        "paths": paths,
    }
    comps = _copy.deepcopy(full.get("components") or {})
    comps["schemas"] = {k: v for k, v in all_schemas.items() if k in seen}
    spec["components"] = comps
    if "servers" in full:
        spec["servers"] = full["servers"]
    return spec


@app.get("/api/v1/openapi/arroba.json", include_in_schema=False)
async def arroba_openapi():
    return JSONResponse(_build_arroba_openapi())


@app.get("/api/v1/openapi/arroba.v1.json", include_in_schema=False)
async def arroba_openapi_v1():
    """Frozen v1 alias of the arroba public contract (stable URL for client generation)."""
    return JSONResponse(_build_arroba_openapi())


@app.get("/api/v1/openapi/arroba.v2.json", include_in_schema=False)
async def arroba_openapi_v2():
    """Typed v2 public contract (six engines + Company/Identity), for SDK generation."""
    return JSONResponse(_build_arroba_v2_openapi())


@app.get("/api/docs/arroba/v2", include_in_schema=False)
async def arroba_docs_v2():
    return _swagger_ui_html(
        openapi_url="/api/v1/openapi/arroba.v2.json",
        title="Agency Tool — Intelligence API (arroba.com) — v2",
    )


@app.get("/api/docs/arroba", include_in_schema=False)
async def arroba_docs():
    return _swagger_ui_html(
        openapi_url="/api/v1/openapi/arroba.json",
        title="Agency Tool — Intelligence API (arroba.com)",
    )



# Health endpoint (shallow / liveness — no DB, never fails on Mongo issues)
@app.get("/api/v1/health")
async def health():
    return {
        "status": "healthy",
        "service": "agency-scraper",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# Deep health / readiness — pings MongoDB. Use for readiness probes & monitoring,
# NOT as a liveness probe (a DB blip must not trigger pod restart loops).
async def _health_deep():
    started = datetime.now(timezone.utc)
    payload = {
        "status": "ok",
        "service": "agency-scraper",
        "version": "2.0.0",
        "checks": {},
        "timestamp": started.isoformat(),
    }
    try:
        await client.admin.command("ping")
        latency_ms = round((datetime.now(timezone.utc) - started).total_seconds() * 1000, 1)
        payload["checks"]["mongo"] = {"status": "ok", "db": os.environ.get("DB_NAME"), "latency_ms": latency_ms}
        return JSONResponse(status_code=200, content=payload)
    except Exception as e:
        payload["status"] = "unavailable"
        payload["checks"]["mongo"] = {"status": "fail", "error": type(e).__name__}
        return JSONResponse(status_code=503, content=payload)


@app.get("/api/v1/health/deep")
async def health_deep():
    return await _health_deep()


@app.get("/api/v1/readyz")
async def readyz():
    return await _health_deep()


# Capacity endpoint — stable contract for consumers
@app.get("/api/v1/capacity")
async def capacity():
    """Returns current processing capacity. Consumers check this before sending jobs."""
    return await get_worker_status()


# Memory cleanup endpoint
@app.post("/api/v1/admin/cleanup")
async def admin_cleanup(user=Depends(get_current_user)):
    """Force garbage collection and kill orphan chromium processes."""
    import gc
    from services.worker import _kill_orphan_chromium, _active_jobs

    if _active_jobs > 0:
        return {"status": "skipped", "reason": f"{_active_jobs} active jobs, cleanup unsafe"}

    _kill_orphan_chromium()
    gc.collect()

    mem = await get_worker_status()
    return {
        "status": "cleaned",
        "container_memory_pct": mem["container_memory_pct"],
        "container_used_mb": mem["container_used_mb"],
        "process_memory_mb": mem["process_memory_mb"],
        "accepting_new_jobs": mem["accepting_new_jobs"]
    }


# Operational controls
@app.post("/api/v1/admin/pause")
async def admin_pause(user=Depends(get_current_user)):
    """Pause intake — stop accepting new jobs."""
    import services.worker as w
    w._accepting_new_jobs = False
    w._backpressure_reason = "manual_pause"
    w._effective_concurrent = 0
    return {"status": "paused", "accepting_new_jobs": False}

@app.post("/api/v1/admin/resume")
async def admin_resume(user=Depends(get_current_user)):
    """Resume intake — start accepting new jobs again."""
    import services.worker as w
    w._accepting_new_jobs = True
    w._backpressure_reason = None
    w._effective_concurrent = w.MAX_CONCURRENT
    return {"status": "resumed", "accepting_new_jobs": True, "effective_concurrent": w.MAX_CONCURRENT}

@app.post("/api/v1/admin/drain")
async def admin_drain(user=Depends(get_current_user)):
    """Drain mode — finish current jobs but don't accept new ones."""
    import services.worker as w
    w._accepting_new_jobs = False
    w._backpressure_reason = "drain_mode"
    # Keep effective_concurrent so current jobs finish
    return {"status": "draining", "accepting_new_jobs": False, "active_jobs": w._active_jobs}

@app.post("/api/v1/admin/set-concurrent")
async def admin_set_concurrent(max_concurrent: int = Query(3, ge=1, le=5), user=Depends(get_current_user)):
    """Adjust max concurrent workers."""
    import services.worker as w
    w.MAX_CONCURRENT = max_concurrent
    w._update_backpressure()
    return {"status": "updated", "max_concurrent": max_concurrent, "effective_concurrent": w._effective_concurrent}


# Screenshot serving
@app.get("/api/v1/screenshots/{path:path}")
async def serve_screenshot(path: str):
    try:
        data, content_type = get_object(path)
        return Response(content=data, media_type=content_type)
    except Exception as e:
        return JSONResponse(status_code=404, content={"detail": f"Screenshot not found: {str(e)}"})


# Manual download
@app.get("/api/v1/manual")
async def download_manual():
    manual_path = ROOT_DIR.parent / "MANUAL_DE_APLICACION_AGENCIAS.md"
    if not manual_path.exists():
        return JSONResponse(status_code=404, content={"detail": "Manual not found"})
    content = manual_path.read_text(encoding="utf-8")
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=MANUAL_DE_APLICACION_AGENCIAS.md"}
    )

# API documentation endpoint
@app.get("/api/v1/docs-info")
async def api_docs_info():
    return {
        "service": "Intelligence Engine",
        "version": "13.0.0",
        "base_url": "/api/v1",
        "documentation": "/api/v1/manual",
        "endpoints": [
            # ── Intelligence Engine — Core ─────────────────────────────────
            {"method": "GET", "path": "/api/v1/engine/version", "description": "Engine identity card: version, git_commit, build_timestamp, environment, profiles, sources, health", "auth": False},
            {"method": "GET", "path": "/api/v1/engine/capabilities", "description": "Declarative capabilities: profiles, sources, modules", "auth": False},
            {"method": "GET", "path": "/api/v1/intelligence/profiles", "description": "List all enrichment profiles (basic, valuo, arroba)", "auth": False},
            {"method": "GET", "path": "/api/v1/intelligence/profile/{name}", "description": "Profile detail (sources it runs)", "auth": False},
            {"method": "POST", "path": "/api/v1/intelligence/enrich", "description": "Run enrichment over a master_company_id using a profile. Cache-first for web source.", "auth": False,
             "body": {"master_company_id": "mc_xxx", "profile": "valuo", "force_refresh": False}},
            {"method": "GET", "path": "/api/v1/intelligence/scrape-queue", "description": "Web scrape queue counts and recent jobs", "auth": False},
            {"method": "POST", "path": "/api/v1/intelligence/migrate-agency-results", "description": "Migrate historical agency_results to master companies by domain (idempotent). ?dry_run=true to preview", "auth": False},

            # ── Enriched Company API (Canonical contract for Valuo / arroba)
            {"method": "GET", "path": "/api/v1/company/{master_company_id}/enriched", "description": "Canonical enriched-company payload. PUBLIC. Consumed by Valuo/arroba after request reaches status=completed. Flat top-level fields (description, tags, logo_url, ...) + nested sources block per origin.", "auth": False},
            {"method": "GET", "path": "/api/v1/company/by-valuo-id/{valuo_company_id}/enriched", "description": "Resolve Valuo's external ID → return canonical enriched payload (same shape)", "auth": False},

            # ── Valuo Integration (request/poll flow) ──────────────────────
            {"method": "POST", "path": "/api/v1/valuo/request-update-from-valuo", "description": "Valuo entry-point: request enrichment for a company.", "auth": False,
             "body": {"valuo_company_id": "valuo_xxx", "legal_name": "...", "cif": "...", "domain": "...", "requested_by": "..."}},
            {"method": "GET", "path": "/api/v1/valuo/request-status/{request_id}", "description": "Polling endpoint. When status=completed, dereference enriched_company_url for the canonical payload.", "auth": False},
            {"method": "GET", "path": "/api/v1/valuo/health", "description": "Pipeline health: verdict, counts by status, timeline last hour, p50/p95, oldest stuck", "auth": False},

            # ── Auth ───────────────────────────────────────────────────────
            {"method": "POST", "path": "/api/v1/auth/login", "description": "Login → JWT token", "auth": False, "body": {"email": "...", "password": "..."}},
            {"method": "POST", "path": "/api/v1/auth/register", "description": "Register new user", "auth": False},
            {"method": "POST", "path": "/api/v1/auth/api-keys", "description": "Create API key", "auth": True},
            {"method": "GET", "path": "/api/v1/auth/api-keys", "description": "List API keys", "auth": True},

            # ── Web Source (legacy /scrape, now under the engine) ──────────
            {"method": "GET", "path": "/api/v1/health", "description": "Backend liveness check", "auth": False},
            {"method": "POST", "path": "/api/v1/scrape", "description": "Launch URL scrape (used internally by the engine web source cache-miss path)", "auth": True},
            {"method": "POST", "path": "/api/v1/scrape/bulk", "description": "Bulk scrape", "auth": True},
            {"method": "GET", "path": "/api/v1/jobs/{job_id}", "description": "Analysis job status", "auth": True},
            {"method": "GET", "path": "/api/v1/results", "description": "List agency_results", "auth": True},
            {"method": "GET", "path": "/api/v1/results/{result_id}", "description": "Get single result + evidence", "auth": True},

            # ── Companies Master ───────────────────────────────────────────
            {"method": "GET", "path": "/api/v1/master", "description": "List master companies", "auth": True},
            {"method": "GET", "path": "/api/v1/master/{mc_id}", "description": "Master detail + linked agency_results + audit history", "auth": True},
            {"method": "GET", "path": "/api/v1/master/stats", "description": "Master stats by merge_status", "auth": True},

            # ── Intelligence layers ────────────────────────────────────────
            {"method": "GET", "path": "/api/v1/public/sector-intelligence/overview", "description": "Sector ranking by CNAE (level=section|division|group)", "auth": False},
            {"method": "GET", "path": "/api/v1/public/geo-intelligence/overview", "description": "Territory ranking (level=ccaa|province)", "auth": False},
            {"method": "GET", "path": "/api/v1/public/cross-intelligence/heatmap", "description": "Sector × CCAA heatmap", "auth": False},
            {"method": "GET", "path": "/api/v1/public/cnae/catalog", "description": "Full CNAE-2009 hierarchy", "auth": False},

            # ── Economic Intelligence Layer ────────────────────────────────
            {"method": "GET", "path": "/api/v1/economic-intelligence/cnae/{code}", "description": "Complete economic profile for a CNAE code (aggregates 7 sources)", "auth": False},
            {"method": "GET", "path": "/api/v1/economic-intelligence/overview", "description": "Top CNAE by data richness", "auth": False},
            {"method": "GET", "path": "/api/v1/economic-intelligence/signals", "description": "All economic signals", "auth": False},
            {"method": "GET", "path": "/api/v1/economic-intelligence/stats", "description": "4200+ metrics across 88 CNAE codes", "auth": False},

            # ── Taxonomy Intelligence ──────────────────────────────────────
            {"method": "GET", "path": "/api/v1/taxonomy-intelligence/resolve/{taxonomy}/{code}", "description": "Resolve external code to CNAE", "auth": False},

            # ── Data sources ───────────────────────────────────────────────
            {"method": "POST", "path": "/api/v1/datacomex/sync", "description": "Sync REAL DataComex via Playwright", "auth": True},
            {"method": "GET", "path": "/api/v1/datacomex/dashboard", "description": "DataComex KPIs", "auth": True},
            {"method": "POST", "path": "/api/v1/public-procurement/sync-placsp", "description": "Sync REAL PLACSP (CODICE 2.07, 183K+ contracts)", "auth": True},
            {"method": "GET", "path": "/api/v1/public-procurement/contracts", "description": "List public contracts", "auth": True},
            {"method": "GET", "path": "/api/v1/bme-markets/dashboard", "description": "BME KPIs: 254 companies, 1.4T EUR", "auth": True},
            {"method": "GET", "path": "/api/v1/bme-markets/comparables", "description": "Public comparables by CNAE/sector", "auth": False},
            {"method": "GET", "path": "/api/v1/public/intelligence/sync-status", "description": "All sources sync status + alerts", "auth": False},

            # ── Document Intelligence Studio ───────────────────────────────
            {"method": "POST", "path": "/api/v1/docstudio/compose/sector-report", "description": "Generate sector report from CNAE", "auth": True},
            {"method": "POST", "path": "/api/v1/docstudio/compose/company-snapshot", "description": "Company Snapshot", "auth": True},
            {"method": "POST", "path": "/api/v1/docstudio/compose/teaser", "description": "Blind teaser", "auth": True},
            {"method": "POST", "path": "/api/v1/docstudio/compose/information-memorandum", "description": "Full IM", "auth": True},
            {"method": "POST", "path": "/api/v1/docstudio/compose/from-template", "description": "Compose from custom template", "auth": True},
            {"method": "GET", "path": "/api/v1/docstudio/export/{id}/pdf", "description": "Export to PDF", "auth": True},
            {"method": "GET", "path": "/api/v1/docstudio/export/{id}/pptx", "description": "Export to editable PPTX", "auth": True},
        ]
    }


# Seed taxonomy on startup
INITIAL_TAXONOMY = [
    {"name": "Estrategia, Marca y Diseno", "subs": ["Brand strategy", "Naming y arquitectura de marca", "Identidad visual y diseno", "Research & Consumer Insights"]},
    {"name": "Creatividad y Produccion", "subs": ["Agencia creativa (ATL / TTL)", "Content studio", "Produccion audiovisual", "Motion / 3D / craft", "Experiencias inmersivas (AR/VR)"]},
    {"name": "Comunicacion, PR y Reputacion", "subs": ["PR corporativo", "Comunicacion digital", "Public affairs", "Comunicacion interna", "Crisis & issues management"]},
    {"name": "Experiencias y Activacion (BTL)", "subs": ["Eventos y produccion", "Experiential marketing", "Trade marketing", "Field marketing", "Retail activation"]},
    {"name": "Influencer & Creator Economy", "subs": ["Influencer marketing (campanas)", "Talent management", "Creator production", "Social amplification"]},
    {"name": "Medios, Performance y Programmatic", "subs": ["Agencia de medios", "Performance / Paid media", "Programmatic / Trading desk", "Retail media buying"]},
    {"name": "Digital, Growth y Commerce", "subs": ["Desarrollo web y plataformas", "Producto digital / UX-UI", "SEO", "GEO (Generative Engine Optimization)", "CRM y automation", "CRO", "Ecommerce y marketplaces"]},
    {"name": "Data, AdTech y MarTech", "subs": ["DSP", "SSP", "Ad Exchange", "CDP / DMP", "Data Clean Rooms", "Medicion / Attribution", "Ad verification / Brand safety", "Anti-fraud", "MMP"]},
    {"name": "Consultoria de Transformacion", "subs": ["Consultoria tecnologica", "Data strategy & privacy", "Consultoria de IA", "Innovacion", "Estrategia de crecimiento"]},
    {"name": "Soportes y Media Owners", "subs": ["OOH tradicional", "DOOH", "Transporte", "Indoor advertising", "Retail media owner", "CTV owner", "Audio network"]},
]


@app.on_event("startup")
async def startup():
    # Defer ALL heavy initialization (index creation, seeds, warmups, schedulers)
    # to a background task so uvicorn starts accepting traffic immediately.
    # This prevents the temporary 520/502 window on redeploys, which was caused by
    # ~200 sequential create_index round-trips against remote MongoDB Atlas blocking
    # the startup event before the server became ready. The body is fully idempotent.
    import asyncio as _boot_aio

    async def _boot():
        try:
            await _run_startup_init()
        except Exception as e:
            logger.error(f"Deferred startup init failed: {e}", exc_info=True)

    _boot_aio.create_task(_boot())
    logger.info("Startup handler returned immediately; initialization running in background")


async def _run_startup_init():
    # Initialize storage
    try:
        init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.warning(f"Object storage init failed (non-blocking): {e}")

    # Ensure the arroba service API key (X-API-Key) exists for enrich_company
    try:
        from services.service_auth import ensure_service_key
        await ensure_service_key()
    except Exception as e:
        logger.warning(f"Service key bootstrap failed (non-blocking): {e}")

    # ARROBA Copilot indexes (non-blocking)
    try:
        from services.copilot import indexes as _cop_idx
        await _cop_idx.ensure_indexes()
    except Exception as e:
        logger.warning(f"Copilot indexes bootstrap failed (non-blocking): {e}")

    # ARROBA Company Taxonomy registry seed (non-blocking)
    try:
        from services.taxonomy import registry as _cab_reg
        await _cab_reg.build_registry_v1()
    except Exception as e:
        logger.warning(f"Taxonomy registry bootstrap failed (non-blocking): {e}")

    # Seed Signal Engine threshold config (thr-v1) + signals indexes
    try:
        from services.engines.signal import thresholds as _sig_thr
        from services.engines.signal import persistence as _sig_persist
        from services.engines.signal import borme_bridge as _sig_borme
        from services.engines.signal import baselines as _sig_baselines
        from services.engines.recommendation import mandates as _rec_mandates
        await _sig_thr.ensure_thresholds()
        await _sig_persist.ensure_indexes()
        await _sig_borme.ensure_indexes()
        await _sig_baselines.ensure_indexes()
        await _rec_mandates.ensure_indexes()
        from services.engines.semantic import persistence as _sem_persist
        await _sem_persist.ensure_indexes()
        from services.engines.recommendation import memory as _rec_mem
        await _rec_mem.ensure_indexes()
        from services.transaction_os import store as _tx_os
        await _tx_os.ensure_indexes()
    except Exception as e:
        logger.warning(f"Signal engine bootstrap failed (non-blocking): {e}")

    # Warm the semantic vector backend in the background: probe Atlas $vectorSearch
    # (preferred, no in-memory load); fall back to a memory-safe in-memory index only
    # where $vectorSearch is unavailable (e.g. local MongoDB in preview).
    try:
        from services.engines.semantic import vector_search as _sem_vs
        info = await _sem_vs.warm()
        logger.info(f"Semantic vector backend ready: {info}")
    except Exception as e:
        logger.warning(f"Semantic vector backend warm-up failed (non-blocking): {e}")

    # Ensure the job queue indexes exist (API only enqueues; the worker processes)
    try:
        from services.jobs import queue as _job_queue
        await _job_queue.ensure_indexes()
    except Exception as e:
        logger.warning(f"Job queue index init failed (non-blocking): {e}")

    # Seed taxonomy if empty
    count = await db.taxonomy_categories.count_documents({})
    if count == 0:
        logger.info("Seeding initial taxonomy...")
        now = datetime.now(timezone.utc).isoformat()
        for i, cat_data in enumerate(INITIAL_TAXONOMY):
            cat_id = str(uuid.uuid4())
            cat = {
                "id": cat_id,
                "name": cat_data["name"],
                "order": i + 1,
                "active": True,
                "source": "seed",
                "external_id": None,
                "taxonomy_version": "v2.0-2026",
                "created_at": now,
                "updated_at": now
            }
            await db.taxonomy_categories.insert_one({**cat})

            for j, sub_name in enumerate(cat_data["subs"]):
                sub = {
                    "id": str(uuid.uuid4()),
                    "category_id": cat_id,
                    "name": sub_name,
                    "order": j + 1,
                    "active": True,
                    "source": "seed",
                    "external_id": None,
                    "taxonomy_version": "v2.0-2026",
                    "created_at": now,
                    "updated_at": now
                }
                await db.taxonomy_subcategories.insert_one({**sub})

        logger.info("Taxonomy seeded successfully")

    # Seed "Otras" category if missing
    otras_cat = await db.taxonomy_categories.find_one({"name": "Otras"})
    if not otras_cat:
        logger.info("Seeding 'Otras' category...")
        now_o = datetime.now(timezone.utc).isoformat()
        max_order = await db.taxonomy_categories.count_documents({})
        otras_id = str(uuid.uuid4())
        await db.taxonomy_categories.insert_one({
            "id": otras_id, "name": "Otras", "description": "Categoría genérica para servicios no clasificados en las categorías principales",
            "order": max_order + 1, "active": True, "source": "seed",
            "external_id": None, "taxonomy_version": "v2.1-2026",
            "created_at": now_o, "updated_at": now_o, "updated_by": "system",
        })
        await db.taxonomy_subcategories.insert_one({
            "id": str(uuid.uuid4()), "category_id": otras_id,
            "name": "Otros servicios", "definition": "Servicios profesionales no clasificados en subcategorías específicas",
            "order": 1, "active": True, "source": "seed",
            "external_id": None, "taxonomy_version": "v2.1-2026",
            "created_at": now_o, "updated_at": now_o, "updated_by": "system",
        })
        logger.info("'Otras' + 'Otros servicios' seeded")

    # Seed Iberinform provider if not exists (key stable — never regenerated)
    ib_provider = await db.data_providers.find_one({"provider_id": "iberinform"})
    if not ib_provider:
        import secrets
        # Use env var if set, otherwise generate once and store
        api_key = os.environ.get("IBERINFORM_UPLOAD_API_KEY") or f"ib_{secrets.token_hex(20)}"
        await db.data_providers.insert_one({
            "provider_id": "iberinform",
            "name": "Iberinform",
            "description": "Dataset semanal de inteligencia corporativa",
            "frequency": "weekly",
            "api_key": api_key,
            "active": True,
            "total_uploads": 0,
            "last_upload_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Iberinform provider seeded with key: {api_key[:12]}...")
    else:
        # If env var set and different from stored, update stored key
        env_key = os.environ.get("IBERINFORM_UPLOAD_API_KEY")
        if env_key and ib_provider.get("api_key") != env_key:
            await db.data_providers.update_one(
                {"provider_id": "iberinform"},
                {"$set": {"api_key": env_key}}
            )
            logger.info("Iberinform API key updated from env var")

    # Indexes for providers
    await db.data_providers.create_index("provider_id", unique=True)
    await db.data_providers.create_index("api_key", unique=True)
    await db.provider_files.create_index("file_id", unique=True)
    await db.provider_files.create_index("provider_id")

    # Seed default document template if empty
    doc_tpl_count = await db.document_templates.count_documents({})
    if doc_tpl_count == 0:
        logger.info("Seeding default document template...")
        now = datetime.now(timezone.utc).isoformat()
        default_tpl = {
            "template_id": "tpl_agency_report",
            "name": "Agency Report",
            "document_type": "report",
            "supported_formats": ["pdf", "pptx"],
            "description": "Standard agency profile report with AI-generated content blocks",
            "status": "published",
            "version": 1,
            "schema_version": "1.0",
            "allowed_components": ["executive_summary", "company_overview", "top_strengths", "top_risks", "financial_highlights", "market_position", "next_steps"],
            "default_brand_id": "brand_bud",
            "legal_disclaimer": "This document is confidential and intended solely for the use of BUD Advisors and its authorized recipients.",
            "html_template": None,
            "css_template": None,
            "sections": [
                {"id": "executive_summary", "title": "Executive Summary", "type": "ai_block"},
                {"id": "company_overview", "title": "Company Overview", "type": "ai_block"},
                {"id": "top_strengths", "title": "Key Strengths", "type": "ai_list"},
                {"id": "top_risks", "title": "Key Risks", "type": "ai_list"},
                {"id": "financial_highlights", "title": "Financial Highlights", "type": "ai_block"},
                {"id": "market_position", "title": "Market Position", "type": "ai_block"},
                {"id": "next_steps", "title": "Next Steps", "type": "ai_list"}
            ],
            "created_by": "system",
            "created_at": now,
            "updated_at": now
        }
        await db.document_templates.insert_one({**default_tpl})
        await db.document_template_versions.insert_one({
            "id": new_id(), "template_id": "tpl_agency_report", "version": 1,
            "html_template": None, "css_template": None, "sections": default_tpl["sections"],
            "created_by": "system", "created_at": now
        })
        # Default brand
        await db.document_brand_profiles.insert_one({
            "brand_id": "brand_bud",
            "name": "BUD Advisors",
            "primary_color": "#1a1a2e",
            "secondary_color": "#3b82f6",
            "accent_color": "#10b981",
            "font_heading": "Manrope",
            "font_body": "IBM Plex Sans",
            "logo_asset_id": None,
            "legal_entity": "BUD Advisors SL",
            "created_at": now
        })
        logger.info("Default document template and brand seeded")

    # Seed valuation template if missing
    val_tpl = await db.document_templates.find_one({"template_id": "tpl_valuation_report"})
    if not val_tpl:
        logger.info("Seeding valuation report template...")
        now_v = datetime.now(timezone.utc).isoformat()
        await db.document_templates.insert_one({
            "template_id": "tpl_valuation_report",
            "name": "Valuation Report",
            "document_type": "valuation",
            "supported_formats": ["pdf"],
            "description": "Company valuation report with quality scoring, EV scenarios, benchmark and financial analysis",
            "status": "published",
            "version": 1,
            "schema_version": "1.0",
            "allowed_components": ["executive_summary", "valuation", "quality", "benchmark", "financial_history", "cost_structure", "methodology"],
            "default_brand_id": "brand_cis",
            "legal_disclaimer": None,
            "html_template": None,
            "css_template": None,
            "sections": [
                {"id": "executive_summary", "title": "Executive Summary", "type": "structured"},
                {"id": "valuation", "title": "Market Valuation", "type": "structured"},
                {"id": "quality", "title": "Quality & Positioning", "type": "structured"},
                {"id": "benchmark", "title": "Benchmark vs Category", "type": "structured"},
                {"id": "financial_history", "title": "Financial Evolution", "type": "structured"},
                {"id": "cost_structure", "title": "Cost Structure", "type": "structured"},
                {"id": "methodology", "title": "Methodology", "type": "structured"},
                {"id": "legal", "title": "Legal Disclaimer", "type": "fixed"}
            ],
            "created_by": "system",
            "created_at": now_v,
            "updated_at": now_v
        })
        logger.info("Valuation report template seeded")

    # Create indexes
    await db.analysis_jobs.create_index("id", unique=True)
    await db.agency_results.create_index("id", unique=True)
    await db.agency_results.create_index("job_id")
    await db.agency_results.create_index("input_url")
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.agency_results.create_index("cis_company_id", sparse=True)
    await db.agency_results.create_index("cif_normalized", sparse=True)
    await db.agency_results.create_index("cif", sparse=True)
    await db.enrichment_metadata.create_index("job_id")
    await db.enrichment_metadata.create_index("cis_company_id")
    await db.consumers.create_index("consumer_id", unique=True)
    await db.consumers.create_index("api_key_user_ids")
    await db.borme_events.create_index("idempotency_key", unique=True)
    await db.borme_events.create_index("publication_date")
    await db.borme_events.create_index("company_name_normalized")
    await db.borme_events.create_index("event_type")
    await db.borme_summaries.create_index("publication_date", unique=True)
    await db.borme_raw_items.create_index("official_identifier", unique=True)
    await db.borme_events.create_index("cnae_code", sparse=True)
    await db.borme_events.create_index("cnae_division", sparse=True)
    await db.borme_events.create_index("sector_status", sparse=True)
    await db.company_activity_profiles.create_index("company_key", unique=True)
    await db.transactions_normalized.create_index("transaction_id", unique=True)
    await db.transactions_normalized.create_index("target_name_normalized")
    await db.transactions_normalized.create_index("announcement_date")
    await db.transactions_normalized.create_index("year")
    await db.transactions_normalized.create_index("publish_status")
    await db.transactions_normalized.create_index("dedupe_status")
    await db.transaction_imports.create_index("import_id", unique=True)
    await db.transaction_dedupe_candidates.create_index("candidate_id", unique=True)
    await db.transaction_audit_logs.create_index("transaction_id")
    await db.transaction_company_links.create_index("link_id", unique=True)
    await db.transaction_company_links.create_index("transaction_id")
    await db.transaction_company_links.create_index("match_status")
    await db.transaction_classification_suggestions.create_index("suggestion_id", unique=True)
    await db.transaction_classification_suggestions.create_index("transaction_id")
    await db.transaction_sources.create_index("source_id", unique=True)
    await db.transaction_sources.create_index("transaction_id")
    await db.taxonomy_aliases.create_index("alias_id", unique=True)
    await db.taxonomy_aliases.create_index("alias")
    await db.taxonomy_audit_logs.create_index("entity_id")
    await db.companies_master.create_index("master_company_id", unique=True)
    await db.companies_master.create_index("cif_normalized")
    await db.companies_master.create_index("domain")
    await db.companies_master.create_index("normalized_name")
    await db.companies_master.create_index("merge_status")
    await db.er_audit_logs.create_index("master_company_id")
    await db.valuo_update_requests.create_index("request_id", unique=True)
    await db.valuo_update_requests.create_index("valuo_company_id")
    await db.valuo_update_requests.create_index("master_company_id")
    await db.ine_observations.create_index([("table_id", 1), ("series_code", 1), ("year", 1), ("period", 1)])
    await db.ine_observations.create_index("cnae_code")
    await db.ine_tables.create_index("table_id", unique=True)
    await db.ine_sync_logs.create_index("synced_at")
    await db.data_provider_status.create_index("provider", unique=True)
    await db.provider_exclusions.create_index("exclusion_id", unique=True)
    await db.provider_exclusions.create_index([("provider", 1), ("source_record_id", 1)])
    await db.provider_exclusions.create_index("action")
    await db.publication_events.create_index("event_id", unique=True)
    await db.publication_events.create_index("entity_id")
    await db.publication_events.create_index("timestamp")
    await db.provider_datasets.create_index("dataset_id", unique=True)
    await db.provider_cnaes.create_index("cnae", unique=True)
    await db.registry_audit_logs.create_index("entity_id")
    await db.public_procurement_contracts.create_index("contract_id", unique=True)
    await db.public_procurement_contracts.create_index("expediente")
    await db.public_procurement_contracts.create_index("matched_company_id")
    await db.public_procurement_contracts.create_index("cpv_code")
    await db.public_procurement_contracts.create_index("awardee_tax_id")
    await db.procurement_cpv_scope.create_index("cpv", unique=True)
    await db.macro_indicators.create_index([("indicator_key", 1), ("date", 1), ("source", 1)], unique=True)
    await db.macro_indicators.create_index("source")
    await db.business_demography.create_index([("indicator_key", 1), ("date", 1)], unique=True)
    await db.sector_intelligence.create_index([("cnae_code", 1), ("taxonomy_type", 1)], unique=True)
    await db.sector_intelligence.create_index("dynamism_score")
    await db.sector_intelligence.create_index("cnae_level")
    await db.sector_intelligence.create_index("size_score")
    await db.sector_intelligence.create_index("growth_score")
    await db.sector_intelligence.create_index("activity_score")
    await db.sector_intelligence.create_index("signal")
    await db.sector_intelligence.create_index("parent_section")
    await db.sector_intelligence.create_index("parent_division")
    await db.cnae_catalog.create_index("code", unique=True)
    await db.cnae_catalog.create_index("level")
    await db.business_archetypes.create_index("archetype_id", unique=True)
    await db.geo_intelligence.create_index([("geo_id", 1), ("geo_level", 1)], unique=True)
    await db.geo_intelligence.create_index("dynamism_score")
    await db.geo_intelligence.create_index("geo_level")
    await db.geo_intelligence.create_index("size_score")
    await db.geo_intelligence.create_index("growth_score")
    await db.geo_intelligence.create_index("activity_score")
    await db.geo_intelligence.create_index("signal")
    await db.geo_intelligence.create_index("parent_ccaa")
    await db.sector_geo_cross.create_index([("cnae_section", 1), ("province_code", 1)])
    await db.sector_geo_cross.create_index([("province_code", 1), ("borme_events", -1)])
    await db.sector_geo_cross.create_index([("ccaa_code", 1), ("borme_events", -1)])
    await db.sector_geo_cross.create_index("cnae_section")
    await db.sector_geo_cross.create_index("borme_events")
    await db.intelligence_sync_log.create_index("module", unique=True)
    await db.datacomex_raw_data.create_index("record_id", unique=True)
    await db.datacomex_raw_data.create_index([("taric_code", 1), ("year", 1), ("flow", 1)])
    await db.datacomex_trade_metrics.create_index("metric_id", unique=True)
    await db.datacomex_trade_metrics.create_index([("taric_code", 1), ("year", 1)])
    await db.datacomex_trade_metrics.create_index("exports_eur")
    await db.datacomex_signals.create_index("signal_id", unique=True)
    await db.datacomex_signals.create_index("signal_type")
    await db.datacomex_cnae_mapping.create_index([("taric_code", 1), ("cnae_code", 1)], unique=True)
    await db.datacomex_sync_logs.create_index("log_id", unique=True)
    await db.taxonomy_mappings.create_index("mapping_id", unique=True)
    await db.taxonomy_mappings.create_index([("source_taxonomy", 1), ("source_code", 1), ("cnae_code", 1)], unique=True)
    await db.taxonomy_mappings.create_index("status")
    await db.taxonomy_mappings.create_index("origin")
    await db.taxonomy_mappings.create_index([("source_taxonomy", 1), ("source_code", 1)])
    await db.taxonomy_suggestions.create_index("suggestion_id", unique=True)
    await db.taxonomy_suggestions.create_index([("source_taxonomy", 1), ("source_code", 1), ("suggested_cnae", 1)], unique=True)
    await db.taxonomy_suggestions.create_index("status")
    await db.taxonomy_suggestions.create_index("target_type")
    await db.economic_metrics.create_index("metric_id", unique=True)
    await db.economic_metrics.create_index([("cnae_code", 1), ("source", 1), ("metric", 1), ("period", 1)])
    await db.economic_metrics.create_index("cnae_code")
    await db.economic_signals.create_index("signal_id", unique=True)
    await db.economic_signals.create_index("cnae_code")
    await db.cnmv_entities.create_index("entity_id", unique=True)
    await db.cnmv_entities.create_index("nif", unique=True)
    await db.cnmv_entities.create_index("entity_type")
    await db.cnmv_entities.create_index("name")
    await db.cnmv_signals.create_index("signal_id", unique=True)
    await db.cnmv_sync_logs.create_index("log_id", unique=True)
    await db.cnmv_metrics.create_index("metric_id", unique=True)
    await db.docstudio_documents.create_index("document_id", unique=True)
    await db.docstudio_templates.create_index("template_id", unique=True)
    await db.docstudio_brands.create_index("brand_id", unique=True)
    await db.docstudio_ai_audit.create_index("audit_id", unique=True)
    await db.docstudio_exports.create_index("export_id")
    await db.docstudio_template_versions.create_index([("template_id", 1), ("version", 1)])
    await db.bme_companies.create_index("bme_id", unique=True)
    await db.bme_companies.create_index("isin", unique=True)
    await db.bme_companies.create_index("company_name")
    await db.bme_companies.create_index("market_segment")
    await db.bme_companies.create_index("sector")
    await db.bme_companies.create_index("market_cap")
    await db.bme_signals.create_index("signal_id", unique=True)
    await db.bme_sync_logs.create_index("log_id", unique=True)
    await db.corporate_events.create_index("company_id")
    await db.corporate_events.create_index("event_type")
    await db.corporate_events.create_index("publication_date")
    await db.category_valuations.create_index("category")
    await db.category_valuations_meta.create_index("last_rebuilt")
    await db.valuation_rebuild_logs.create_index("log_id", unique=True)
    # Ranking (arroba.v2 company relative position) — support indexes
    await db.master_companies.create_index([("classification.cnae_section", 1), ("financials.latest.revenue", 1)])
    await db.master_companies.create_index([("location.municipio", 1), ("classification.cnae_section", 1), ("financials.latest.revenue", 1)])
    await db.master_companies.create_index([("location.provincia", 1), ("classification.cnae_section", 1), ("financials.latest.revenue", 1)])
    logger.info("Database indexes created")

    # Seed CNAE catalog if empty
    cnae_count = await db.cnae_catalog.count_documents({})
    if cnae_count == 0:
        from services.cnae_catalog import CNAE_SECTIONS, CNAE_DIVISIONS, CNAE_GROUPS, BUSINESS_ARCHETYPES
        logger.info("Seeding CNAE catalog...")
        now_c = datetime.now(timezone.utc).isoformat()
        docs = []
        for sec in CNAE_SECTIONS:
            docs.append({"code": sec["code"], "label": sec["label"], "level": "section",
                         "parent": None, "created_at": now_c})
        for div_code, div_info in CNAE_DIVISIONS.items():
            docs.append({"code": div_code, "label": div_info["label"], "level": "division",
                         "parent": div_info["section"], "created_at": now_c})
        for grp_code, grp_info in CNAE_GROUPS.items():
            docs.append({"code": grp_code, "label": grp_info["label"], "level": "group",
                         "parent": grp_info["division"], "created_at": now_c})
        if docs:
            await db.cnae_catalog.insert_many(docs)
        logger.info(f"CNAE catalog seeded: {len(docs)} entries")

        # Seed business archetypes
        for arch in BUSINESS_ARCHETYPES:
            await db.business_archetypes.update_one(
                {"archetype_id": arch["archetype_id"]},
                {"$set": {**arch, "active": True, "created_at": now_c}},
                upsert=True,
            )
        logger.info(f"Business archetypes seeded: {len(BUSINESS_ARCHETYPES)}")

    # Seed/migrate DataComex TARIC→CNAE mappings via centralized taxonomy layer (v2)
    from services.taxonomy_intelligence import ensure_taxonomy_v2
    tax_result = await ensure_taxonomy_v2()
    logger.info(f"Taxonomy Intelligence v2: {tax_result}")

    # Warm the embedding index cache (Fase C) so first hybrid search avoids cold-load
    try:
        from services.taxonomy_embeddings import warm_cache
        warmed = await warm_cache()
        logger.info(f"Embedding index warm: {warmed}")
    except Exception as e:
        logger.warning(f"Embedding warm skipped: {e}")

    # Seed DocStudio templates and brands
    ds_tpl = await db.docstudio_templates.count_documents({})
    if ds_tpl == 0:
        from docstudio.templates import seed_templates_and_brands
        ds_result = await seed_templates_and_brands(db)
        logger.info(f"DocStudio seeded: {ds_result}")

    # Seed default consumers if empty
    consumer_count = await db.consumers.count_documents({})
    if consumer_count == 0:
        logger.info("Seeding default consumers...")
        default_consumers = [
            {
                "consumer_id": "cis",
                "name": "Centro de Inteligencia Sectorial",
                "api_key_user_ids": [],
                "environments": {
                    "production": {
                        "allowed_callback_domains": ["cis.wearebudadvisors.com"],
                        "callback_secret": None
                    },
                    "staging": {
                        "allowed_callback_domains": [
                            "sector-intel-1.emergent.host",
                            "portal-analytics-hub.preview.emergentagent.com",
                            "manual-review-beta.preview.emergentagent.com"
                        ],
                        "callback_secret": None
                    }
                },
                "active": True,
                "created_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "consumer_id": "arroba",
                "name": "Arroba Platform",
                "api_key_user_ids": [],
                "environments": {
                    "production": {"allowed_callback_domains": [], "callback_secret": None},
                    "staging": {"allowed_callback_domains": [], "callback_secret": None}
                },
                "active": True,
                "created_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "consumer_id": "default",
                "name": "Default / Direct",
                "api_key_user_ids": [],
                "environments": {
                    "production": {"allowed_callback_domains": [], "callback_secret": None},
                    "staging": {"allowed_callback_domains": [], "callback_secret": None}
                },
                "active": True,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ]
        for c in default_consumers:
            await db.consumers.insert_one({**c})
        logger.info(f"Seeded {len(default_consumers)} consumers")

    # Recovery: fix jobs stuck from previous server restart
    await _recover_stuck_jobs()
    await _recover_stuck_valuo_requests()

    # Auto-populate intelligence (core layers — fast, <5 sec)
    await _auto_populate_intelligence_core()

    # Strategic sources (CNMV, DataComex, PLACSP) — background, can take minutes
    import asyncio as _aio
    _aio.create_task(_auto_populate_strategic_sources_bg())

    # Self-healing Data Layer: reconstruct the canonical Master Layer from official sources
    # if it is empty (e.g. a fresh deployment). Guarded + background, never blocks startup.
    _aio.create_task(_auto_bootstrap_data_layer_if_empty())

    # Start persistent job worker
    await start_worker()
    await start_doc_worker()
    await start_borme_scheduler()
    await start_editorial_worker()
    await start_intelligence_scheduler()
    await start_datacomex_scheduler()
    await start_ine_demography_scheduler()
    await start_watchlist_scheduler()
    await start_cnmv_bme_scheduler()
    await start_placsp_scheduler()

    # DocStudio async compose worker (Fase 4 — generación asíncrona + notificaciones)
    from docstudio.compose_worker import start_compose_worker
    await start_compose_worker()

    # Public-data sources scheduler (BDNS / INE / SEPE)
    from services.intelligence_engine.scheduler import start_public_sources_scheduler
    await start_public_sources_scheduler()


async def _recover_stuck_jobs():
    """Recover jobs stuck from previous server restart. Runs with limited concurrency."""
    import asyncio
    from services.orchestrator import run_analysis

    # 1. Mark stuck "processing" and "claimed" jobs as pending (they died with the previous process)
    stuck_count = await db.analysis_jobs.count_documents({"status": {"$in": ["processing", "claimed"]}})
    if stuck_count > 0:
        await db.analysis_jobs.update_many(
            {"status": {"$in": ["processing", "claimed"]}},
            {"$set": {
                "status": "pending",
                "phase": None,
                "started_at": None
            }}
        )
        logger.warning(f"Recovery: reset {stuck_count} stuck jobs back to pending (worker will pick them up)")

    # 2. Log pending count — worker will pick them up automatically
    pending_count = await db.analysis_jobs.count_documents({"status": "pending"})
    if pending_count > 0:
        logger.info(f"Recovery: {pending_count} pending jobs in queue. Worker will process them.")


async def _recover_stuck_valuo_requests():
    """Process any Valuo enrichment request stuck in 'pending' or 'processing' from a previous restart.

    Background tasks die when Uvicorn restarts. On boot we sweep the queue so requests
    don't sit forever in 'pending'. Runs in background to avoid delaying startup.
    """
    import asyncio
    try:
        stuck = await db.valuo_update_requests.count_documents(
            {"enrichment_status": {"$in": ["pending", "processing"]}}
        )
        if stuck == 0:
            return
        logger.warning(f"Valuo recovery: found {stuck} stuck enrichment requests — processing in background")

        async def _drain():
            try:
                from services.valuo_enrichment import process_all_pending
                # Also reset any "processing" requests back to pending
                await db.valuo_update_requests.update_many(
                    {"enrichment_status": "processing"},
                    {"$set": {"enrichment_status": "pending"}}
                )
                result = await process_all_pending()
                logger.info(f"Valuo recovery completed: {result}")
            except Exception as e:
                logger.error(f"Valuo recovery failed: {e}")

        asyncio.create_task(_drain())
    except Exception as e:
        logger.error(f"Valuo recovery check failed: {e}")


async def _auto_bootstrap_data_layer_if_empty():
    """Reconstruct the canonical Master Layer from official sources if empty (self-healing).

    Enabled by default; set AUTO_BOOTSTRAP_DATA_LAYER=0 to disable. Runs the full reproducible
    bootstrap (ingestion→master→ownership→signals→semantic→verify→canonical set) in background.
    """
    try:
        if os.environ.get("AUTO_BOOTSTRAP_DATA_LAYER", "1") not in ("1", "true", "True"):
            return
        if await db.master_companies.count_documents({}) > 0:
            return
        logger.info("Master Layer empty → launching reproducible Data Layer bootstrap")
        from services.data_layer.bootstrap import run_bootstrap
        result = await run_bootstrap()
        logger.info(f"Data Layer bootstrap {result['status']}: {result['verification']['counts']}")
    except Exception as e:
        logger.error(f"Auto data-layer bootstrap failed: {e}")



async def _auto_populate_intelligence_core():
    """Fast core population — runs blocking at startup (<5 sec).
    
    Seeds: Iberinform, Sector/Geo/Cross Intelligence, Economic Intelligence.
    Does NOT include slow sources (CNMV, DataComex Playwright, PLACSP).
    """
    si_count = await db.sector_intelligence.count_documents({})
    gi_count = await db.geo_intelligence.count_documents({})
    cx_count = await db.sector_geo_cross.count_documents({})
    econ_count = await db.economic_metrics.count_documents({})

    if si_count > 0 and gi_count > 0 and cx_count > 0 and econ_count > 0:
        logger.info(f"Core intelligence populated: sector={si_count}, geo={gi_count}, cross={cx_count}, econ={econ_count}")
        return

    logger.info(f"Auto-populating core intelligence (sector={si_count}, geo={gi_count}, cross={cx_count}, econ={econ_count})...")

    try:
        # Step 1: Ensure Iberinform data exists (for size_score)
        ib_count = await db.iberinform_companies.count_documents({})
        if ib_count == 0:
            from services.iberinform_processor import generate_synthetic_dataset
            result = await generate_synthetic_dataset(count=5000)
            logger.info(f"Iberinform synthetic: {result['companies_imported']} companies, {result['fiscal_years_imported']} FY")

        # Step 2: Sector Intelligence
        if si_count == 0:
            from services.sector_intelligence_v2 import compute_sector_intelligence_v2
            si_result = await compute_sector_intelligence_v2()
            logger.info(f"Sector Intelligence: {si_result['total']} entries computed")
            from services.intelligence_scheduler import log_manual_sync
            await log_manual_sync("sector_intelligence", si_result["total"])

        # Step 3: Geo Intelligence
        if gi_count == 0:
            from services.geo_intelligence import compute_geo_intelligence
            gi_result = await compute_geo_intelligence()
            logger.info(f"Geo Intelligence: {gi_result['total']} entries computed")
            from services.intelligence_scheduler import log_manual_sync as _log2
            await _log2("geo_intelligence", gi_result["total"])

        # Step 4: Cross Intelligence
        if cx_count == 0:
            from services.sector_geo_cross import compute_sector_geo_cross
            cx_result = await compute_sector_geo_cross()
            logger.info(f"Cross Intelligence: {cx_result['combinations']} combinations computed")
            from services.intelligence_scheduler import log_manual_sync as _log3
            await _log3("cross_intelligence", cx_result["combinations"])

        # Step 5: Economic Intelligence Layer
        econ_count = await db.economic_metrics.count_documents({})
        if econ_count == 0:
            # Seed DataComex trade data as development/emergency fallback (if empty)
            dcx_count = await db.datacomex_raw_data.count_documents({})
            if dcx_count == 0:
                logger.info("DataComex: no real data found. Using seed as fallback (production should run /datacomex/sync)")
                from services.datacomex_connector import generate_seed_trade_data, rebuild_trade_metrics, rebuild_signals
                seed = await generate_seed_trade_data()
                logger.info(f"DataComex seed fallback: {seed['records']} records")
                metrics = await rebuild_trade_metrics()
                logger.info(f"DataComex metrics: {metrics['metrics_computed']}")
                signals = await rebuild_signals()
                logger.info(f"DataComex signals: {signals['signals_generated']}")
            else:
                logger.info(f"DataComex: {dcx_count} raw records found, rebuilding metrics")
                from services.datacomex_connector import rebuild_trade_metrics, rebuild_signals
                await rebuild_trade_metrics()
                await rebuild_signals()

            from services.economic_intelligence import rebuild_economic_metrics, rebuild_economic_signals
            econ_result = await rebuild_economic_metrics()
            logger.info(f"Economic Intelligence: {econ_result['total_metrics']} metrics")
            sig_result = await rebuild_economic_signals()
            logger.info(f"Economic Signals: {sig_result['signals_generated']} signals")

        logger.info("Core intelligence auto-population completed")

        # Rebuild category valuations (persistent cache)
        try:
            from services.category_valuations import auto_rebuild_if_stale
            await auto_rebuild_if_stale()
            logger.info("Category valuations checked/rebuilt")
        except Exception as val_err:
            logger.warning(f"Category valuations rebuild skipped: {val_err}")

    except Exception as e:
        logger.error(f"Core intelligence auto-population failed: {e}")


async def _auto_populate_strategic_sources_bg():
    """Background task: populate CNMV, DataComex real, PLACSP if empty.
    
    Runs AFTER server is accepting requests. Can take 5-8 minutes.
    Server is fully functional during this time (with partial data).
    """
    cnmv_count = await db.cnmv_entities.count_documents({})
    placsp_count = await db.public_procurement_contracts.count_documents({})
    dcx_real = await db.datacomex_raw_data.count_documents({"source": "datacomex_real"})

    if cnmv_count > 0 and placsp_count > 1000 and dcx_real > 0:
        logger.info(f"Strategic sources populated: cnmv={cnmv_count}, placsp={placsp_count}, dcx_real={dcx_real}")
        return

    logger.info(f"Background: populating strategic sources (cnmv={cnmv_count}, placsp={placsp_count}, dcx_real={dcx_real})...")

    try:
        await _auto_populate_strategic_sources()
    except Exception as e:
        logger.error(f"Strategic sources background population failed: {e}")


async def _auto_populate_strategic_sources():
    """Auto-populate CNMV, DataComex (real), and PLACSP if empty.
    
    These are strategic data sources that must exist in production.
    Each runs only if its collection is empty.
    """
    # CNMV (httpx scraping, ~30 sec, no Playwright needed)
    cnmv_count = await db.cnmv_entities.count_documents({})
    if cnmv_count == 0:
        logger.info("CNMV: empty, starting auto-sync...")
        try:
            import httpx
            import re
            from models import now_iso
            now = now_iso()
            all_entities = []

            ENTITY_IDS = [
                (1, "fcr"), (0, "scr"), (19, "scr_pyme"), (20, "fcr_pyme"),
                (21, "fcr_europeo"), (22, "fese"), (23, "sicc"), (24, "ficc"), (28, "filpe"),
            ]
            MANAGER_URLS = [
                ("sgeic", "https://www.cnmv.es/portal/consultas/listadoentidad?id=4&tipoent=0&lang=es"),
                ("sgiic", "https://www.cnmv.es/portal/consultas/listadoentidad?id=2&tipoent=0&lang=es"),
                ("esi", "https://www.cnmv.es/portal/consultas/listadoentidad?id=1&tipoent=0&lang=es"),
            ]
            EAF_IDS = [(5, "eaf"), (6, "eafn")]

            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, verify=False) as client:
                # Paginated listings (funds/vehicles)
                for entity_id, etype in ENTITY_IDS:
                    page = 1
                    while page <= 100:
                        url = f"https://www.cnmv.es/portal/consultas/mostrarlistados?id={entity_id}&page={page}&lang=es"
                        try:
                            resp = await client.get(url)
                            entries = re.findall(r'nif=([^&"]+)"[^>]*title="([^"]*)"', resp.text)
                            if not entries:
                                entries_raw = re.findall(r'nif=([^&"]+)', resp.text)
                                names = re.findall(r'class="tit[^"]*"[^>]*>([^<]+)</span>', resp.text)
                                entries = list(zip(entries_raw, names)) if len(entries_raw) == len(names) else []
                            if not entries:
                                break
                            for nif, name in entries:
                                all_entities.append({"nif": nif, "name": name.strip(), "entity_type": etype})
                            page += 1
                        except Exception:
                            break

                # Manager listings (single page each)
                for etype, url in MANAGER_URLS:
                    try:
                        resp = await client.get(url)
                        nif_positions = list(re.finditer(r'nif=([A-Z0-9]+)', resp.text))
                        for m in nif_positions:
                            nif = m.group(1)
                            block = resp.text[max(0, m.start()-300):m.start()+300]
                            names = re.findall(r'>([^<]{4,})<', block)
                            clean = [n.strip() for n in names if n.strip() and len(n.strip()) > 5
                                     and 'cookie' not in n.lower() and 'Denominaci' not in n]
                            name = clean[0] if clean else nif
                            all_entities.append({"nif": nif, "name": name, "entity_type": etype, "is_manager": True})
                    except Exception:
                        pass

                # EAF (paginated)
                for entity_id, etype in EAF_IDS:
                    page = 1
                    while page <= 30:
                        url = f"https://www.cnmv.es/portal/consultas/mostrarlistados?id={entity_id}&page={page}&lang=es"
                        try:
                            resp = await client.get(url)
                            entries = re.findall(r'nif=([^&"]+)"[^>]*title="([^"]*)"', resp.text)
                            if not entries:
                                break
                            for nif, name in entries:
                                all_entities.append({"nif": nif, "name": name.strip(), "entity_type": etype, "is_manager": True})
                            page += 1
                        except Exception:
                            break

            # Store
            import uuid
            from services.cnmv_connector import ENTITY_TYPES
            imported = 0
            for e in all_entities:
                etype = e["entity_type"]
                config = ENTITY_TYPES.get(etype, {})
                result = await db.cnmv_entities.update_one(
                    {"nif": e["nif"]},
                    {"$set": {
                        "name": e["name"], "nif": e["nif"],
                        "entity_type": etype,
                        "entity_type_label": config.get("label", etype),
                        "is_manager": e.get("is_manager", config.get("is_manager", False)),
                        "source": "cnmv", "updated_at": now,
                    },
                    "$setOnInsert": {
                        "entity_id": f"cnmv_{uuid.uuid4().hex[:12]}",
                        "status": "registered", "cnae_codes": [], "created_at": now,
                    }},
                    upsert=True,
                )
                if result.upserted_id:
                    imported += 1

            logger.info(f"CNMV auto-sync: {imported} new of {len(all_entities)} total")

            # Generate signals
            from services.cnmv_connector import generate_cnmv_signals
            await generate_cnmv_signals()

            # Map sectors
            from services.cnmv_investor_intelligence import build_investor_sector_map
            await build_investor_sector_map()

        except Exception as e:
            logger.error(f"CNMV auto-sync failed: {e}")

    # DataComex real (Playwright, ~2 min)
    dcx_real = await db.datacomex_raw_data.count_documents({"source": "datacomex_real"})
    if dcx_real == 0:
        logger.info("DataComex: no real data, attempting Playwright sync...")
        try:
            from services.datacomex_playwright import sync_via_playwright, post_sync_rebuild
            result = await sync_via_playwright()
            if result["status"] == "completed":
                await post_sync_rebuild()
                logger.info(f"DataComex real: {result['records']} records synced")
            else:
                logger.warning(f"DataComex Playwright: {result.get('status')} - falling back to seed")
        except Exception as e:
            logger.warning(f"DataComex Playwright failed ({e}), seed already in place")

    # PLACSP (download ZIP ~120MB + parse, ~3-5 min)
    placsp_count = await db.public_procurement_contracts.count_documents({})
    if placsp_count < 1000:
        logger.info(f"PLACSP: only {placsp_count} contracts, starting auto-sync...")
        try:
            from services.placsp_connector import sync_placsp
            result = await sync_placsp(years=None, dataset="menores", max_files=None)
            logger.info(f"PLACSP auto-sync: {result.get('imported', 0)} contracts imported")
        except Exception as e:
            logger.error(f"PLACSP auto-sync failed: {e}")

    # Rebuild Economic Intelligence if any new sources were added
    new_placsp = await db.public_procurement_contracts.count_documents({})
    new_cnmv = await db.cnmv_entities.count_documents({})
    if new_placsp > placsp_count or new_cnmv > cnmv_count:
        logger.info("Rebuilding Economic Intelligence after strategic source sync...")
        try:
            from services.economic_intelligence import rebuild_economic_metrics, rebuild_economic_signals
            econ = await rebuild_economic_metrics()
            esig = await rebuild_economic_signals()
            logger.info(f"Economic Intelligence rebuilt: {econ['total_metrics']} metrics, {esig['signals_generated']} signals")
        except Exception as e:
            logger.error(f"Economic rebuild failed: {e}")


@app.post("/api/v1/jobs/recover")
async def recover_pending_jobs(
    limit: int = 5,
    user=Depends(get_current_user)
):
    """Manually trigger recovery of pending jobs with controlled concurrency."""
    import asyncio
    from services.orchestrator import run_analysis

    pending = await db.analysis_jobs.find(
        {"status": "pending"},
        {"_id": 0}
    ).sort("created_at", 1).limit(limit).to_list(limit)

    total_pending = await db.analysis_jobs.count_documents({"status": "pending"})

    if not pending:
        return {"status": "no_pending_jobs", "total_pending": 0}

    # Process with semaphore (max 2 concurrent)
    sem = asyncio.Semaphore(2)
    started = []

    for job in pending:
        meta = await db.enrichment_metadata.find_one({"job_id": job["id"]}, {"_id": 0})
        callback_url = meta.get("callback_url") if meta else None

        async def _run(j_id, j_url, cb_url):
            async with sem:
                try:
                    result = await run_analysis(j_id, j_url)
                    if cb_url and result:
                        await db.agency_results.update_one(
                            {"id": result["id"]},
                            {"$set": {
                                "callback_url": cb_url,
                                "callback_status": "pending",
                                "cis_company_id": (await db.enrichment_metadata.find_one({"job_id": j_id}, {"_id": 0}) or {}).get("cis_company_id"),
                                "enrichment_source": "cis"
                            }}
                        )
                        from services.enrichment_helpers import fire_enrichment_callback
                        await fire_enrichment_callback(result["id"])
                except Exception as e:
                    logger.error(f"Recovery job {j_id} failed: {e}")

        asyncio.create_task(_run(job["id"], job["url"], callback_url))
        started.append({"job_id": job["id"], "url": job["url"]})

    return {
        "status": "recovering",
        "started": len(started),
        "total_pending": total_pending,
        "jobs": started
    }


@app.on_event("shutdown")
async def shutdown():
    await stop_worker()
    await stop_doc_worker()
    await stop_borme_scheduler()
    await stop_editorial_worker()
    await stop_intelligence_scheduler()
    await stop_datacomex_scheduler()
    await stop_ine_demography_scheduler()
    await stop_watchlist_scheduler()
    await stop_cnmv_bme_scheduler()
    from docstudio.compose_worker import stop_compose_worker
    await stop_compose_worker()
    await stop_placsp_scheduler()
    client.close()
