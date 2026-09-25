"""Financial Intelligence Engine API — the engine's own public contract.

Decoupled service: depends on nothing from arroba/Copilot/UI. Consumers obtain ALL
financial intelligence through this API, never from master_companies directly.
Protected with the existing service API key (X-API-Key).
"""

from fastapi import APIRouter, HTTPException, Depends, Response
from pydantic import BaseModel, Field
from typing import Literal, Optional

from services.engines.financial import engine as fin_engine
from services.engines.financial import ratios_library
from services.engines.valuation.company_inputs import get_company_inputs, save_company_inputs
from services.service_auth import require_service_key
from routes import engine_schemas as S

router = APIRouter(prefix="/api/v1/financial-intelligence", tags=["financial_intelligence"])
inputs_router = APIRouter(prefix="/api/v2/financial-intelligence", tags=["financial_intelligence_v2"])


def _ok(model):
    return {200: {"model": model, "description": "Successful Response"}}


class AnalyzeRequest(BaseModel):
    identifier: str   # master_id or cif_normalized


@router.post("/analyze", responses=_ok(S.FinancialAnalyzeResponse))
async def analyze(req: AnalyzeRequest, _key=Depends(require_service_key)):
    """Full financial intelligence profile (statements, KPIs, ratios, evolution, quality,
    comparables, valuation, assessment, explainability)."""
    result = await fin_engine.analyze(req.identifier)
    if result is None:
        raise HTTPException(404, "company not found in Master Layer")
    return result


@router.post("/valuation", responses=_ok(S.FinancialValuationResponse))
async def valuation(req: AnalyzeRequest, _key=Depends(require_service_key)):
    """Valuation capability only (parity surface with the legacy Value Engine)."""
    profile = await fin_engine.analyze(req.identifier)
    if profile is None:
        raise HTTPException(404, "company not found in Master Layer")
    return {"master_id": profile["master_id"], "cif_normalized": profile["cif_normalized"],
            "valuation": profile["valuation"], "engine_version": profile["engine_version"],
            "generated_at": profile["generated_at"]}


@router.get("/ratios/catalog", responses=_ok(S.RatiosCatalogResponse))
async def ratios_catalog(_key=Depends(require_service_key)):
    """The reusable ratio library: formula + explanation + category for each ratio."""
    return {"ratios": ratios_library.definitions(), "source": ratios_library.SOURCE}


class ValuationInputsRequest(BaseModel):
    recurring_revenue_pct: Optional[float] = Field(None, ge=0, le=1)
    largest_customer_pct: Optional[float] = Field(None, ge=0, le=1)
    key_person_dependency: Optional[bool] = None
    source_type: Literal["due_diligence", "management_interview", "data_room",
                         "advisor_review"] = "due_diligence"
    source_reference: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=2000)


@inputs_router.post("/valuation", include_in_schema=False)
async def valuation_package(req: AnalyzeRequest, _key=Depends(require_service_key)):
    """Canonical Intel valuation package. Beta renders this object without recalculation."""
    profile = await fin_engine.analyze(req.identifier)
    if profile is None:
        raise HTTPException(404, "company not found in Master Layer")
    return {"master_id": profile["master_id"], "cif_normalized": profile["cif_normalized"],
            "valuation": profile["valuation"]["package"],
            "engine_version": profile["engine_version"], "generated_at": profile["generated_at"]}


@inputs_router.post("/valuation/pdf", include_in_schema=False)
async def valuation_pdf(req: AnalyzeRequest, _key=Depends(require_service_key)):
    """Generate the advanced valuation PDF from Intel's canonical package."""
    profile = await fin_engine.analyze(req.identifier)
    if profile is None:
        raise HTTPException(404, "company not found in Master Layer")
    package = (profile.get("valuation") or {}).get("package") or {}
    if package.get("status") != "available":
        raise HTTPException(422, "valuation package is not available")
    from documents.renderers.advanced_valuation_pdf import (
        build_advanced_valuation_pdf, build_advanced_valuation_payload,
    )
    payload = build_advanced_valuation_payload(profile)
    content = build_advanced_valuation_pdf(payload)
    filename = f"valoracion-{profile.get('cif_normalized') or 'empresa'}.pdf"
    return Response(content=content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    })


@inputs_router.get("/valuation-inputs/{identifier}")
async def read_valuation_inputs(identifier: str, _key=Depends(require_service_key)):
    """Current private-company evidence used by the valuation engine."""
    result = await get_company_inputs(fin_engine.db, identifier)
    if result is None:
        raise HTTPException(404, "company not found in Master Layer")
    return result


@inputs_router.put("/valuation-inputs/{identifier}")
async def write_valuation_inputs(identifier: str, req: ValuationInputsRequest,
                                 _key=Depends(require_service_key)):
    """Capture audited due-diligence inputs; null explicitly clears a prior value."""
    payload = req.model_dump(exclude_unset=True)
    metadata = {key: payload.pop(key, None) for key in
                ("source_type", "source_reference", "notes")}
    if not payload:
        raise HTTPException(422, "at least one valuation input is required")
    try:
        result = await save_company_inputs(
            fin_engine.db, identifier, payload,
            source_type=metadata["source_type"] or "due_diligence",
            source_reference=metadata["source_reference"], notes=metadata["notes"],
            actor=(_key or {}).get("service_name", "service"),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "company not found in Master Layer")
    return result
