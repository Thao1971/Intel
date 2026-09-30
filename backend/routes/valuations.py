"""Category Valuations — Persistent, auto-rebuilding endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4
from database import db
from models import now_iso
from auth_utils import get_current_user, decode_token
from services.engines.valuation.market_reference_catalog import market_reference_catalog
from services.engines.financial import engine as financial_engine
from services.engines.valuation.advanced import calculate_advanced
from services.engines.valuation.company_inputs import save_company_inputs
from services.category_valuations import (
    rebuild_valuations, get_cached_valuations, get_valuation_summary,
)
import time

router = APIRouter(prefix="/api/v1/valuations", tags=["valuations"])


class AdvancedValuationRequest(BaseModel):
    identifier: str
    objective: Optional[str] = None
    valuation_date: Optional[str] = None
    perimeter: Literal["company", "group"] = "company"
    financial_overrides: Dict[str, float] = Field(default_factory=dict)
    ebitda_adjustments: List[Dict[str, Any]] = Field(default_factory=list)
    quality_inputs: Dict[str, Any] = Field(default_factory=dict)
    quality_context: Dict[str, Any] = Field(default_factory=dict)
    projection_assumptions: Dict[str, float] = Field(default_factory=dict)
    wacc_inputs: Dict[str, float] = Field(default_factory=dict)
    method_weights: Dict[str, float] = Field(default_factory=dict)
    equity_bridge: Dict[str, float] = Field(default_factory=dict)
    private_transactions: Optional[Dict[str, Any]] = None


def _caller_is_jwt_user(request: Optional[Request]) -> bool:
    """True si el llamante se autenticó con un JWT de usuario de Intel.

    Un JWT de usuario NO puede elegir a quién representa: siempre actúa como sí mismo.
    Solo una clave de servicio (API key), que es lo que usa la pasarela de Beta, puede
    indicar el usuario final con `X-Arroba-User-Id`.
    """
    if request is None:
        return False
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not token:
        return False
    try:
        decode_token(token)
        return True
    except Exception:
        return False


def _user_id(user, request: Optional[Request] = None) -> str:
    """Identificador del propietario de una ejecución avanzada.

    - JWT de usuario: su propio id; la cabecera `X-Arroba-User-Id` se IGNORA
      (evita suplantar a otro usuario).
    - Clave de servicio (pasarela): la cabecera es OBLIGATORIA. Sin ella se responde 400
      en lugar de agrupar a todos los usuarios bajo la cuenta de servicio (fail-closed).
    """
    if request is not None and not _caller_is_jwt_user(request):
        forwarded_user_id = request.headers.get("x-arroba-user-id", "").strip()
        if not forwarded_user_id:
            raise HTTPException(
                400,
                "Falta X-Arroba-User-Id: la pasarela debe indicar el usuario autenticado.",
            )
        return forwarded_user_id[:200]
    if isinstance(user, dict):
        return str(user.get("id") or user.get("sub") or user.get("_id") or "authenticated")
    return str(getattr(user, "id", None) or "authenticated")


def _meta(t0):
    return {"contract_version": "1.0", "generated_at": now_iso(),
            "response_time_ms": round((time.time() - t0) * 1000, 1)}


@router.get("/intake/{identifier}")
async def valuation_intake(identifier: str, user=Depends(get_current_user)):
    """Canonical company accounts used by the valuation start screen.

    Intel owns retrieval and normalization. The client only renders these
    fields and never reconstructs statements or financial metrics.
    """
    t0 = time.time()
    profile = await financial_engine.analyze(identifier)
    if profile is None:
        raise HTTPException(404, "Empresa no encontrada")
    return {
        **_meta(t0),
        "master_id": profile.get("master_id"),
        "cif": profile.get("cif_normalized") or identifier.upper(),
        "identity": profile.get("identity") or {},
        "has_financials": bool(profile.get("has_financials")),
        "statements": profile.get("statements"),
        "statements_history": profile.get("statements_history") or [],
        "kpis": profile.get("kpis") or {},
        "evolution": profile.get("evolution") or {},
        "financial_quality": profile.get("financial_quality") or {},
        "iberinform_ratios": profile.get("iberinform_ratios") or {},
        "comparables": profile.get("comparables") or {},
        "valuation": profile.get("valuation") or {},
        "assessment": profile.get("assessment") or {},
        "explainability": profile.get("explainability") or {},
        "engine_version": profile.get("engine_version"),
    }


@router.post("/advanced/calculate")
async def advanced_valuation_calculate(req: AdvancedValuationRequest, request: Request,
                                       user=Depends(get_current_user)):
    """Calculate and persist one user-reviewed advanced valuation run."""
    t0 = time.time()
    owner_id = _user_id(user, request)
    quality = {key: value for key, value in req.quality_inputs.items()
               if key in {"recurring_revenue_pct", "largest_customer_pct",
                          "key_person_dependency"}}
    if quality:
        try:
            await save_company_inputs(
                db, req.identifier, quality, source_type="advisor_review",
                notes="Advanced valuation intake", actor=owner_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    profile = await financial_engine.analyze(req.identifier)
    if profile is None:
        raise HTTPException(404, "Empresa no encontrada")
    generated_at = now_iso()
    try:
        result = calculate_advanced(profile, req.model_dump(), generated_at)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    run_id = f"avr_{uuid4().hex}"
    await db.valuation_advanced_runs.insert_one({
        "_id": run_id, "run_id": run_id, "user_id": owner_id,
        "identifier": req.identifier, "created_at": generated_at,
        "request": req.model_dump(), "profile": result,
    })
    return {**_meta(t0), "run_id": run_id, "profile": result}


@router.get("/advanced/{run_id}")
async def advanced_valuation_result(run_id: str, request: Request,
                                    user=Depends(get_current_user)):
    doc = await db.valuation_advanced_runs.find_one({"_id": run_id}, {"_id": 0})
    if not doc or doc.get("user_id") != _user_id(user, request):
        raise HTTPException(404, "Valoración avanzada no encontrada")
    return {"run_id": run_id, "profile": doc.get("profile"),
            "created_at": doc.get("created_at")}


@router.get("/advanced/{run_id}/pdf")
async def advanced_valuation_pdf(run_id: str, request: Request,
                                 user=Depends(get_current_user)):
    doc = await db.valuation_advanced_runs.find_one({"_id": run_id}, {"_id": 0})
    if not doc or doc.get("user_id") != _user_id(user, request):
        raise HTTPException(404, "Valoración avanzada no encontrada")
    profile = doc.get("profile") or {}
    package = (profile.get("valuation") or {}).get("package") or {}
    if package.get("status") != "available":
        raise HTTPException(422, "Valoración no disponible")
    from documents.renderers.advanced_valuation_pdf import (
        build_advanced_valuation_pdf, build_advanced_valuation_payload,
    )
    content = build_advanced_valuation_pdf(build_advanced_valuation_payload(profile))
    cif = profile.get("cif_normalized") or doc.get("identifier") or "empresa"
    return Response(content=content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="valoracion-{cif}-{run_id}.pdf"',
        "Cache-Control": "no-store",
    })


@router.get("/company/{identifier}/pdf")
async def valuation_report_pdf(identifier: str, user=Depends(get_current_user)):
    """Generate the canonical advanced valuation report inside Intel."""
    profile = await financial_engine.analyze(identifier)
    if profile is None:
        raise HTTPException(404, "Empresa no encontrada")
    package = (profile.get("valuation") or {}).get("package") or {}
    if package.get("status") != "available":
        raise HTTPException(422, "Valoración no disponible")
    from documents.renderers.advanced_valuation_pdf import (
        build_advanced_valuation_pdf, build_advanced_valuation_payload,
    )
    content = build_advanced_valuation_pdf(build_advanced_valuation_payload(profile))
    cif = profile.get("cif_normalized") or identifier
    return Response(content=content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="valoracion-{cif}.pdf"',
        "Cache-Control": "no-store",
    })


@router.get("/market-references")
async def market_references(
    category: str = Query(None),
    region: str = Query(None),
    include_history: bool = Query(True),
    user=Depends(get_current_user),
):
    """Canonical versioned public/private market-reference catalogue."""
    t0 = time.time()
    return {**_meta(t0), **market_reference_catalog(
        category=category, region=region, include_history=include_history
    )}


@router.get("/by-category")
async def valuations_by_category(user=Depends(get_current_user)):
    """Valuation multiples by category. Reads from persistent cache."""
    t0 = time.time()
    result = await get_cached_valuations()
    return {**_meta(t0), **result}


@router.get("/summary")
async def valuation_summary(user=Depends(get_current_user)):
    """Quick summary of valuation data availability."""
    t0 = time.time()
    summary = await get_valuation_summary()
    return {**_meta(t0), **summary}


@router.post("/rebuild")
async def rebuild(
    year: int = Query(None),
    buyer_type: str = Query(None),
    country: str = Query(None),
    only_observed: bool = Query(False),
    user=Depends(get_current_user),
):
    """Rebuild all category valuations from M&A transactions. Persists results."""
    t0 = time.time()
    result = await rebuild_valuations(year, buyer_type, country, only_observed, trigger="manual")
    return {**_meta(t0), **result}


@router.get("/rebuild-logs")
async def rebuild_logs(limit: int = Query(10, ge=1, le=50), user=Depends(get_current_user)):
    """Rebuild history logs."""
    t0 = time.time()
    logs = await db.valuation_rebuild_logs.find({}, {"_id": 0}).sort("rebuilt_at", -1).limit(limit).to_list(limit)
    return {**_meta(t0), "logs": logs}


@router.get("/category/{category_name}")
async def category_detail(category_name: str, user=Depends(get_current_user)):
    """Detailed valuation for a specific category from cache."""
    t0 = time.time()
    category = await db.category_valuations.find_one(
        {"category": {"$regex": category_name, "$options": "i"}}, {"_id": 0}
    )
    if not category:
        from fastapi import HTTPException
        raise HTTPException(404, f"Category '{category_name}' not found")
    return {**_meta(t0), "category": category}
