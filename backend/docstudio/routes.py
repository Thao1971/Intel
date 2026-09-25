"""Document Intelligence Studio — API routes."""

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import Response
from database import db
from models import now_iso
from auth_utils import get_current_user
from docstudio.composer import compose_sector_report, compose_company_profile, compose_benchmark_report, compose_investment_memo, compose_teaser, compose_one_pager, compose_information_memorandum, compute_quality_score, compose_company_snapshot, compose_benchmark_advanced, compose_from_template, generate_template_preview, compose_opportunities_document, compose_ranking_document, compose_fragmentation_document, compose_rollup_document, compose_succession_document, compose_valuation_approx, compose_valuation_advanced, compose_strategic_analysis, compose_comparative_analysis
from docstudio.pdf_export import export_to_pdf
from docstudio.templates import TEMPLATES, BRANDS
import time

router = APIRouter(prefix="/api/v1/docstudio", tags=["docstudio"])


def _meta(t0):
    return {"contract_version": "1.0", "generated_at": now_iso(),
            "response_time_ms": round((time.time() - t0) * 1000, 1)}


async def _record_timing(doc_id: str, t0: float):
    """Record generation time in document metadata."""
    ms = round((time.time() - t0) * 1000, 1)
    await db.docstudio_documents.update_one(
        {"document_id": doc_id},
        {"$set": {"metadata.generation_time_ms": ms}}
    )
    return ms


# ══════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════

@router.get("/dashboard")
async def dashboard(user=Depends(get_current_user)):
    t0 = time.time()
    docs_total = await db.docstudio_documents.count_documents({})
    templates = await db.docstudio_templates.count_documents({})
    brands = await db.docstudio_brands.count_documents({})
    exports_total = await db.docstudio_exports.count_documents({})
    ai_calls = await db.docstudio_ai_audit.count_documents({})
    pdf_exports = await db.docstudio_exports.count_documents({"format": "pdf"})
    pptx_exports = await db.docstudio_exports.count_documents({"format": "pptx"})

    recent = await db.docstudio_documents.find(
        {}, {"_id": 0, "document_id": 1, "title": 1, "status": 1, "created_at": 1, "template_id": 1}
    ).sort("created_at", -1).limit(10).to_list(10)

    # Telemetry: by template
    tpl_pipeline = [
        {"$group": {"_id": "$template_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_template = {r["_id"]: r["count"] for r in await db.docstudio_documents.aggregate(tpl_pipeline).to_list(20)}

    # Telemetry: avg generation time
    time_pipeline = [
        {"$match": {"metadata.generation_time_ms": {"$exists": True}}},
        {"$group": {"_id": None, "avg_ms": {"$avg": "$metadata.generation_time_ms"}}},
    ]
    avg_time = await db.docstudio_documents.aggregate(time_pipeline).to_list(1)

    # Export ratio
    export_ratio = round(exports_total / max(docs_total, 1) * 100, 1)

    return {
        **_meta(t0),
        "kpis": {
            "documents": docs_total, "templates": templates, "brands": brands,
            "exports": exports_total, "ai_calls": ai_calls,
            "pdf_exports": pdf_exports, "pptx_exports": pptx_exports,
        },
        "telemetry": {
            "by_template": by_template,
            "export_ratio_pct": export_ratio,
            "avg_generation_ms": round(avg_time[0]["avg_ms"]) if avg_time else None,
        },
        "recent_documents": recent,
    }


# ══════════════════════════════════════════
# DOCUMENTS
# ══════════════════════════════════════════

@router.get("/documents")
async def list_documents(limit: int = Query(20, ge=1, le=100), user=Depends(get_current_user)):
    t0 = time.time()
    docs = await db.docstudio_documents.find(
        {}, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    total = await db.docstudio_documents.count_documents({})
    return {**_meta(t0), "documents": docs, "total": total}


@router.get("/documents/{document_id}")
async def get_document(document_id: str, user=Depends(get_current_user)):
    t0 = time.time()
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    return {**_meta(t0), "document": doc}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, user=Depends(get_current_user)):
    await db.docstudio_documents.delete_one({"document_id": document_id})
    return {"status": "deleted", "document_id": document_id}


@router.get("/documents/{document_id}/preview")
async def preview_document_html(document_id: str, user=Depends(get_current_user)):
    """Vista previa HTML del documento tal como quedará, con la marca real (base de
    plataforma + overlay de cliente). Se muestra en el editor en un iframe."""
    from fastapi.responses import HTMLResponse
    from docstudio.html_render import render_html, resolve_doc_brand
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    brand = resolve_doc_brand(doc)
    from docstudio.onepager_render import is_onepager, render_onepager_html
    if is_onepager(doc):
        return HTMLResponse(content=render_onepager_html(doc, brand))
    return HTMLResponse(content=render_html(doc, brand))


@router.post("/brands/preview-live")
async def brands_preview_live(body: dict, user=Depends(get_current_user)):
    """Vista previa EN TIEMPO REAL del editor de marca. Recibe la marca SIN GUARDAR (colores,
    tipografías, portada, logo) y devuelve el HTML de una diapositiva-muestra renderizada con
    esos tokens. No toca la BBDD — es instantáneo, para editar y ver el resultado al vuelo."""
    from fastapi.responses import HTMLResponse
    from docstudio.html_render import render_html
    from docstudio.brand_preview import brand_sample_doc
    from documents.brand_unified import compose_brand, PLATFORM_BRANDS, DEFAULT_PLATFORM_BRAND
    import copy
    brand = body.get("brand") or {}
    # Si llega una marca "rica" completa (con tokens), se usa tal cual; si viene parcial,
    # se compone sobre la base de plataforma correspondiente para no perder tokens.
    if not brand.get("tokens"):
        base = copy.deepcopy(PLATFORM_BRANDS.get(brand.get("brand_id"), PLATFORM_BRANDS[DEFAULT_PLATFORM_BRAND]))
        brand = compose_brand(base, brand)
    doc = brand_sample_doc(brand)
    return HTMLResponse(content=render_html(doc, brand))


# ══════════════════════════════════════════
# EDITOR — Save, update blocks, reorder, regenerate
# ══════════════════════════════════════════

from pydantic import BaseModel
from typing import Optional, List, Any


class BlockUpdate(BaseModel):
    block_id: str
    data: dict


class SectionUpdate(BaseModel):
    section_id: str
    title: Optional[str] = None
    blocks: Optional[List[dict]] = None


@router.put("/documents/{document_id}/save")
async def save_document(document_id: str, sections: List[SectionUpdate], user=Depends(get_current_user)):
    """Save full document (all sections with their blocks). Main editor save."""
    doc = await db.docstudio_documents.find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(404, "Document not found")

    # Rebuild sections from the editor payload
    now = now_iso()
    new_sections = []
    for su in sections:
        existing = next((s for s in doc.get("sections", []) if s["section_id"] == su.section_id), None)
        if existing:
            if su.title is not None:
                existing["title"] = su.title
            if su.blocks is not None:
                existing["blocks"] = su.blocks
            new_sections.append(existing)

    await db.docstudio_documents.update_one(
        {"document_id": document_id},
        {"$set": {
            "sections": new_sections,
            "version": doc.get("version", 1) + 1,
            "updated_at": now,
            "last_edited_by": user.get("email"),
        }}
    )

    return {"status": "saved", "version": doc.get("version", 1) + 1}


@router.put("/documents/{document_id}/block/{block_id}")
async def update_block(document_id: str, block_id: str, update: BlockUpdate, user=Depends(get_current_user)):
    """Update a single block's data."""
    doc = await db.docstudio_documents.find_one({"document_id": document_id})
    if not doc:
        raise HTTPException(404, "Document not found")

    now = now_iso()
    updated = False
    for section in doc.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("block_id") == block_id:
                block["data"] = update.data
                block["data_lineage"] = {
                    "source": "manual_edit",
                    "edited_by": user.get("email"),
                    "date": now,
                }
                updated = True
                break

    if not updated:
        raise HTTPException(404, "Block not found")

    await db.docstudio_documents.update_one(
        {"document_id": document_id},
        {"$set": {"sections": doc["sections"], "updated_at": now, "version": doc.get("version", 1) + 1}}
    )
    return {"status": "updated", "block_id": block_id}


@router.post("/documents/{document_id}/section/{section_id}/regenerate")
async def regenerate_section(document_id: str, section_id: str, user=Depends(get_current_user)):
    """Regenerate a section's AI content using current data context."""
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")

    section = next((s for s in doc.get("sections", []) if s["section_id"] == section_id), None)
    if not section:
        raise HTTPException(404, "Section not found")

    # Gather context from the document's metadata
    from docstudio.model_provider import generate_summary
    cnae = doc.get("metadata", {}).get("cnae_code")
    context = doc.get("metadata", {})

    if cnae:
        from services.economic_intelligence import get_cnae_economic_profile
        try:
            econ = await get_cnae_economic_profile(cnae)
            context.update({
                "revenue": econ.get("revenue"),
                "employment": econ.get("employment"),
                "exports": econ.get("exports_eur"),
                "trend": econ.get("trend"),
                "signals": [s.get("signal_type") for s in econ.get("signals", [])],
            })
        except Exception:
            pass

    doc_type = "sector_report" if "sector" in doc.get("template_id", "") else "company_profile"
    ai_result = await generate_summary(context, doc_type=doc_type, document_id=document_id)

    # Replace text/insight blocks in this section with new AI content
    from docstudio import text_block, insight_block
    now = now_iso()
    new_blocks = []

    if section["title"].lower() in ("resumen ejecutivo", "resumen"):
        if ai_result.get("executive_summary"):
            b = text_block(ai_result["executive_summary"], style="executive_summary")
            b["data_lineage"] = {"source": "ai", "model": "gpt-5.2", "task": "regenerated_summary", "date": now}
            new_blocks.append(b)
        for f in ai_result.get("key_findings", []):
            b = insight_block("Hallazgo clave", f, importance="high")
            b["data_lineage"] = {"source": "ai", "model": "gpt-5.2", "task": "regenerated_findings", "date": now}
            new_blocks.append(b)
    elif section["title"].lower() in ("conclusiones", "conclusion"):
        if ai_result.get("conclusion"):
            b = text_block(ai_result["conclusion"], style="conclusion")
            b["data_lineage"] = {"source": "ai", "model": "gpt-5.2", "task": "regenerated_conclusion", "date": now}
            new_blocks.append(b)
        for r in ai_result.get("recommendations", []):
            b = insight_block("Recomendacion", r, importance="medium")
            new_blocks.append(b)

    if new_blocks:
        section["blocks"] = new_blocks
        await db.docstudio_documents.update_one(
            {"document_id": document_id},
            {"$set": {"sections": doc["sections"], "updated_at": now, "version": doc.get("version", 1) + 1}}
        )

    return {"status": "regenerated", "section_id": section_id, "blocks": len(new_blocks)}


# ══════════════════════════════════════════
# LAYOUT CONTROL (maquetación: módulos, saltos de página, marca por documento)
# ══════════════════════════════════════════

from docstudio import layout as _layout, new_block as _new_block, new_section as _new_section


class AddBlockReq(BaseModel):
    section_id: str
    block_type: str
    data: dict = {}
    index: Optional[int] = None


class MoveBlockReq(BaseModel):
    to_section_id: str
    to_index: Optional[int] = None


class ReorderReq(BaseModel):
    ordered_ids: List[str]


class AddSectionReq(BaseModel):
    title: str
    index: Optional[int] = None


class PageBreakReq(BaseModel):
    section_id: str
    index: Optional[int] = None


class BrandOverlayReq(BaseModel):
    overlay: Optional[dict] = None


class ColorOverrideReq(BaseModel):
    colors: Optional[dict] = None


async def _load_doc_or_404(document_id: str) -> dict:
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


async def _save_layout(document_id: str, doc: dict, user) -> int:
    """Persist the document's layout (sections/blocks + per-doc brand) and bump version."""
    new_version = doc.get("version", 1) + 1
    await db.docstudio_documents.update_one(
        {"document_id": document_id},
        {"$set": {
            "sections": doc.get("sections", []),
            "brand_overlay": doc.get("brand_overlay"),
            "color_override": doc.get("color_override"),
            "version": new_version,
            "updated_at": now_iso(),
            "last_edited_by": user.get("email") if user else None,
        }},
    )
    return new_version


@router.post("/documents/{document_id}/blocks")
async def layout_add_block(document_id: str, req: AddBlockReq, user=Depends(get_current_user)):
    """Añadir un módulo (bloque) a una sección."""
    doc = await _load_doc_or_404(document_id)
    try:
        block = _new_block(req.block_type, data=req.data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        _layout.add_block(doc, req.section_id, block, req.index)
    except ValueError as e:
        raise HTTPException(404, str(e))
    v = await _save_layout(document_id, doc, user)
    return {"status": "added", "block_id": block["block_id"], "version": v}


@router.delete("/documents/{document_id}/blocks/{block_id}")
async def layout_remove_block(document_id: str, block_id: str, user=Depends(get_current_user)):
    """Eliminar un módulo."""
    doc = await _load_doc_or_404(document_id)
    try:
        _layout.remove_block(doc, block_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    v = await _save_layout(document_id, doc, user)
    return {"status": "removed", "block_id": block_id, "version": v}


@router.post("/documents/{document_id}/blocks/{block_id}/move")
async def layout_move_block(document_id: str, block_id: str, req: MoveBlockReq, user=Depends(get_current_user)):
    """Mover un módulo a otra sección / posición."""
    doc = await _load_doc_or_404(document_id)
    try:
        _layout.move_block(doc, block_id, req.to_section_id, req.to_index)
    except ValueError as e:
        raise HTTPException(404, str(e))
    v = await _save_layout(document_id, doc, user)
    return {"status": "moved", "block_id": block_id, "version": v}


@router.put("/documents/{document_id}/sections/{section_id}/blocks/reorder")
async def layout_reorder_blocks(document_id: str, section_id: str, req: ReorderReq, user=Depends(get_current_user)):
    """Reordenar los módulos de una sección."""
    doc = await _load_doc_or_404(document_id)
    try:
        _layout.reorder_blocks(doc, section_id, req.ordered_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    v = await _save_layout(document_id, doc, user)
    return {"status": "reordered", "version": v}


@router.post("/documents/{document_id}/sections")
async def layout_add_section(document_id: str, req: AddSectionReq, user=Depends(get_current_user)):
    """Añadir una sección (módulo de nivel superior)."""
    doc = await _load_doc_or_404(document_id)
    section = _new_section(req.title, order=len(doc.get("sections", [])) + 1, blocks=[])
    _layout.add_section(doc, section, req.index)
    v = await _save_layout(document_id, doc, user)
    return {"status": "added", "section_id": section["section_id"], "version": v}


@router.delete("/documents/{document_id}/sections/{section_id}")
async def layout_remove_section(document_id: str, section_id: str, user=Depends(get_current_user)):
    doc = await _load_doc_or_404(document_id)
    try:
        _layout.remove_section(doc, section_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    v = await _save_layout(document_id, doc, user)
    return {"status": "removed", "section_id": section_id, "version": v}


@router.put("/documents/{document_id}/sections/reorder")
async def layout_reorder_sections(document_id: str, req: ReorderReq, user=Depends(get_current_user)):
    doc = await _load_doc_or_404(document_id)
    try:
        _layout.reorder_sections(doc, req.ordered_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    v = await _save_layout(document_id, doc, user)
    return {"status": "reordered", "version": v}


@router.post("/documents/{document_id}/page-break")
async def layout_insert_page_break(document_id: str, req: PageBreakReq, user=Depends(get_current_user)):
    """Insertar un salto de página explícito en una sección."""
    doc = await _load_doc_or_404(document_id)
    try:
        _layout.insert_page_break(doc, req.section_id, req.index)
    except ValueError as e:
        raise HTTPException(404, str(e))
    v = await _save_layout(document_id, doc, user)
    return {"status": "page_break_inserted", "version": v}


@router.put("/documents/{document_id}/brand-overlay")
async def layout_set_brand_overlay(document_id: str, req: BrandOverlayReq, user=Depends(get_current_user)):
    """Fijar (o limpiar, con overlay=null) el overlay de marca del cliente para este documento."""
    doc = await _load_doc_or_404(document_id)
    _layout.set_brand_overlay(doc, req.overlay)
    v = await _save_layout(document_id, doc, user)
    return {"status": "brand_overlay_set" if req.overlay else "brand_overlay_cleared", "version": v}


@router.put("/documents/{document_id}/color-override")
async def layout_set_color_override(document_id: str, req: ColorOverrideReq, user=Depends(get_current_user)):
    """Fijar (o limpiar, con colors=null) los overrides de color por documento."""
    doc = await _load_doc_or_404(document_id)
    _layout.set_color_override(doc, req.colors)
    v = await _save_layout(document_id, doc, user)
    return {"status": "color_override_set" if req.colors else "color_override_cleared", "version": v}


# ══════════════════════════════════════════
# COMPOSE
# ══════════════════════════════════════════

@router.post("/compose/sector-report")
async def compose_sector(
    cnae_code: str = Query(...),
    brand_id: str = Query("brand_bud"),
    user=Depends(get_current_user),
):
    """Compose a sector intelligence report for a CNAE code."""
    t0 = time.time()
    doc = await compose_sector_report(cnae_code, brand_id, user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)

    return {
        **_meta(t0),
        "document_id": doc["document_id"],
        "title": doc["title"],
        "sections": len(doc["sections"]),
        "status": doc["status"],
        "generation_time_ms": gen_ms,
    }


@router.post("/compose/company-profile")
async def compose_company(
    company_id: str = Query(None),
    cif: str = Query(None),
    brand_id: str = Query("brand_bud"),
    user=Depends(get_current_user),
):
    """Compose a company profile document."""
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_company_profile(company_id, cif, brand_id, user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])

    return {
        **_meta(t0),
        "document_id": doc["document_id"],
        "title": doc["title"],
        "sections": len(doc["sections"]),
        "status": doc["status"],
    }


@router.post("/compose/benchmark")
async def compose_benchmark(
    cnae_code: str = Query(...),
    brand_id: str = Query("brand_bud"),
    user=Depends(get_current_user),
):
    """Compose a sector benchmark report with Financial Engine data."""
    t0 = time.time()
    doc = await compose_benchmark_report(cnae_code, brand_id, user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"]}


@router.post("/compose/investment-memo")
async def compose_invest_memo(
    company_id: str = Query(None), cif: str = Query(None),
    brand_id: str = Query("brand_bud"), user=Depends(get_current_user),
):
    """Compose an Investment Memo for a company."""
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_investment_memo(company_id, cif, brand_id, user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"]}


@router.post("/compose/teaser")
async def compose_teaser_endpoint(
    company_id: str = Query(None), cif: str = Query(None),
    brand_id: str = Query("brand_bud"), user=Depends(get_current_user),
):
    """Compose a Teaser (blind profile) for a company."""
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_teaser(company_id, cif, brand_id, user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"]}


@router.post("/compose/one-pager")
async def compose_one_pager_endpoint(
    company_id: str = Query(None), cif: str = Query(None),
    brand_id: str = Query("brand_bud"), user=Depends(get_current_user),
):
    """Compose an Investment One Pager (A4 vertical, blind) for a company."""
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_one_pager(company_id, cif, brand_id, user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"]}



@router.post("/compose/information-memorandum")
async def compose_im(
    company_id: str = Query(None), cif: str = Query(None),
    brand_id: str = Query("brand_bud"), user=Depends(get_current_user),
):
    """Compose a full Information Memorandum."""
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_information_memorandum(company_id, cif, brand_id, user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"]}


@router.get("/documents/{document_id}/quality")
async def document_quality(document_id: str, user=Depends(get_current_user)):
    """Compute quality score for a document."""
    t0 = time.time()
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    quality = compute_quality_score(doc)
    return {**_meta(t0), "document_id": document_id, "quality": quality}


@router.post("/compose/company-snapshot")
async def compose_snapshot(
    company_id: str = Query(None), cif: str = Query(None),
    brand_id: str = Query("brand_bud"), user=Depends(get_current_user),
):
    """Company Snapshot — minimal intelligence unit. <30 seconds."""
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_company_snapshot(company_id, cif, brand_id, user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"]}


@router.post("/compose/benchmark-advanced")
async def compose_bm_advanced(
    cnae_code: str = Query(...),
    company_id: str = Query(None),
    brand_id: str = Query("brand_bud"),
    user=Depends(get_current_user),
):
    """Advanced Benchmark with comparables, positioning, SWOT. <60 seconds."""
    t0 = time.time()
    doc = await compose_benchmark_advanced(cnae_code, company_id, brand_id, user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"]}


@router.post("/compose/opportunities")
async def compose_opportunities(
    cnae_section: str = Query(None),
    provincia: str = Query(None),
    signal_types: str = Query(None),
    mandate_id: str = Query(None),
    brand_id: str = Query("brand_bud"),
    limit: int = Query(40, ge=1, le=200),
    user=Depends(get_current_user),
):
    """Documento de Oportunidades — SIEMPRE acotado (por filtros o por mandato de comprador)."""
    t0 = time.time()
    types = [s.strip() for s in signal_types.split(",") if s.strip()] if signal_types else None
    doc = await compose_opportunities_document(
        cnae_section=cnae_section, provincia=provincia, signal_types=types,
        mandate_id=mandate_id, brand_id=brand_id, user=user.get("email"), limit=limit)
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"],
            "count": doc["metadata"].get("count", 0), "generation_time_ms": gen_ms}


@router.post("/compose/ranking")
async def compose_ranking(cnae_section: str = Query(None), cnae_code: str = Query(None),
                          provincia: str = Query(None), sort_by: str = Query("revenue"),
                          brand_id: str = Query("brand_bud"), limit: int = Query(25, ge=1, le=100),
                          user=Depends(get_current_user)):
    t0 = time.time()
    doc = await compose_ranking_document(cnae_section=cnae_section, cnae_code=cnae_code,
        provincia=provincia, sort_by=sort_by, brand_id=brand_id, user=user.get("email"), limit=limit)
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"], "generation_time_ms": gen_ms}


@router.post("/compose/fragmentation")
async def compose_fragmentation(cnae_section: str = Query(None), cnae_code: str = Query(None),
                                brand_id: str = Query("brand_bud"), user=Depends(get_current_user)):
    t0 = time.time()
    doc = await compose_fragmentation_document(cnae_section=cnae_section, cnae_code=cnae_code,
                                               brand_id=brand_id, user=user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"], "generation_time_ms": gen_ms}


@router.post("/compose/rollup")
async def compose_rollup(cnae_section: str = Query(None), cnae_code: str = Query(None),
                         brand_id: str = Query("brand_bud"), user=Depends(get_current_user)):
    t0 = time.time()
    doc = await compose_rollup_document(cnae_section=cnae_section, cnae_code=cnae_code,
                                        brand_id=brand_id, user=user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"], "generation_time_ms": gen_ms}


@router.post("/compose/succession")
async def compose_succession(company_id: str = Query(None), cif: str = Query(None),
                             brand_id: str = Query("brand_bud"), user=Depends(get_current_user)):
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_succession_document(company_id=company_id, cif=cif,
                                            brand_id=brand_id, user=user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"], "generation_time_ms": gen_ms}


@router.post("/compose/comparative")
async def compose_comparative(company_id: str = Query(None), cif: str = Query(None),
                              brand_id: str = Query("brand_bud"), user=Depends(get_current_user)):
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_comparative_analysis(company_id=company_id, cif=cif, brand_id=brand_id, user=user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"], "generation_time_ms": gen_ms}


@router.post("/admin/migrate-unified")
async def migrate_unified(user=Depends(get_current_user)):
    """Fase 6 — migración idempotente: marcas (docstudio_brands→document_brand_profiles rico)
    + plantillas (docstudio_templates/document_templates→unified_templates). No borra nada legacy."""
    from documents.brand_unified import migrate_brands_to_unified
    from documents.template_model import migrate_templates_to_unified
    brands = await migrate_brands_to_unified(db)
    templates = await migrate_templates_to_unified(db)
    return {"brands": brands, "templates": templates}


@router.post("/compose/valuation-approx")
async def compose_val_approx(company_id: str = Query(None), cif: str = Query(None),
                             brand_id: str = Query("brand_bud"), user=Depends(get_current_user)):
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_valuation_approx(company_id=company_id, cif=cif, brand_id=brand_id, user=user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"], "generation_time_ms": gen_ms}


@router.post("/compose/valuation-advanced")
async def compose_val_advanced(company_id: str = Query(None), cif: str = Query(None),
                               brand_id: str = Query("brand_bud"), user=Depends(get_current_user)):
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_valuation_advanced(company_id=company_id, cif=cif, brand_id=brand_id, user=user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"], "generation_time_ms": gen_ms}


@router.post("/compose/strategic-analysis")
async def compose_strategic(company_id: str = Query(None), cif: str = Query(None),
                            brand_id: str = Query("brand_bud"), user=Depends(get_current_user)):
    if not company_id and not cif:
        raise HTTPException(400, "Provide company_id or cif")
    t0 = time.time()
    doc = await compose_strategic_analysis(company_id=company_id, cif=cif, brand_id=brand_id, user=user.get("email"))
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"], "generation_time_ms": gen_ms}


# ══════════════════════════════════════════
# API EXTERNA (X-API-Key) — para arroba.com / Valuo / CIS (Modelo B: autoservicio)
# Mismo motor que la interfaz interna, pero autenticado por clave de servicio e
# identificado por CIF/master_id (identificador agnóstico del contrato arroba).
# ══════════════════════════════════════════

from services.service_auth import require_service_key


class ExtComposeRequest(BaseModel):
    doc_type: str
    cif: Optional[str] = None
    company_id: Optional[str] = None
    cnae_section: Optional[str] = None
    cnae_code: Optional[str] = None
    provincia: Optional[str] = None
    mandate_id: Optional[str] = None
    brand_id: str = "brand_arroba"
    consumer: Optional[str] = None       # arroba | valuo | cis (traza)
    manual_blocks: Optional[dict] = None  # contenido comercial que aporta el consumidor


@router.post("/ext/compose")
async def ext_compose(req: ExtComposeRequest, _key=Depends(require_service_key)):
    """Encola la generación de un documento para un consumidor externo (arroba.com).
    Devuelve job_id + ETA; el consumidor sondea /ext/jobs/{id}. No bloquea."""
    from docstudio.compose_worker import enqueue_compose
    params = {k: v for k, v in {
        "cif": req.cif, "company_id": req.company_id, "cnae_section": req.cnae_section,
        "cnae_code": req.cnae_code, "provincia": req.provincia, "mandate_id": req.mandate_id,
        "manual_blocks": req.manual_blocks,
    }.items() if v is not None}
    user = f"consumer:{req.consumer or 'external'}"
    return await enqueue_compose(req.doc_type, params, req.brand_id, user)


@router.get("/ext/jobs/{job_id}")
async def ext_job_status(job_id: str, _key=Depends(require_service_key)):
    job = await db.docstudio_compose_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    return {"job_id": job["job_id"], "status": job["status"], "document_id": job.get("document_id"),
            "error": job.get("error")}


@router.get("/ext/documents/{document_id}")
async def ext_get_document(document_id: str, _key=Depends(require_service_key)):
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("/ext/documents/{document_id}/preview")
async def ext_preview(document_id: str, _key=Depends(require_service_key)):
    from fastapi.responses import HTMLResponse
    from docstudio.html_render import render_html, resolve_doc_brand
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    return HTMLResponse(content=render_html(doc, resolve_doc_brand(doc)))


async def _render_document_pdf(doc: dict, brand: dict) -> bytes:
    """Use Intel's canonical valuation renderer inside Document Intelligence Studio."""
    metadata = doc.get("metadata") or {}
    payload = metadata.get("canonical_pdf_payload")
    if metadata.get("type") == "valuation_advanced" and payload:
        from documents.renderers.advanced_valuation_pdf import build_advanced_valuation_pdf
        return build_advanced_valuation_pdf(payload)
    return await export_to_pdf(doc, brand)


@router.get("/ext/documents/{document_id}/export/pdf")
async def ext_export_pdf(document_id: str, _key=Depends(require_service_key)):
    from fastapi.responses import Response
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    brand = await db.docstudio_brands.find_one({"brand_id": doc.get("brand_id", "brand_bud")}, {"_id": 0}) or BRANDS["bud_advisors"]
    pdf_bytes = await _render_document_pdf(doc, brand)
    fn = ''.join(ch for ch in (doc.get("title", "documento").replace(" ", "_")[:50]) if ch.isascii() and ch not in '<>:"/\\|?*')
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fn}.pdf"'})


# ══════════════════════════════════════════
# ASYNC COMPOSE + NOTIFICATIONS (Fase 4, decisión 9)
# ══════════════════════════════════════════

class ComposeAsyncRequest(BaseModel):
    doc_type: str
    params: dict = {}
    brand_id: str = "brand_bud"


@router.post("/compose-async")
async def compose_async(req: ComposeAsyncRequest, user=Depends(get_current_user)):
    """Encola la generación de un documento y devuelve job_id + ETA. El usuario no espera:
    recibirá una notificación en plataforma cuando esté listo."""
    from docstudio.compose_worker import enqueue_compose
    return await enqueue_compose(req.doc_type, req.params, req.brand_id, user.get("email"))


@router.get("/compose-jobs/{job_id}")
async def compose_job_status(job_id: str, user=Depends(get_current_user)):
    job = await db.docstudio_compose_jobs.find_one({"job_id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/eta")
async def compose_eta(doc_type: str = Query(...), user=Depends(get_current_user)):
    """Tiempo estimado de generación (ms) para un tipo de documento, a partir de la
    telemetría real. `null` si aún no hay historial (nunca un número inventado)."""
    from docstudio.compose_worker import estimate_ms
    return {"doc_type": doc_type, "eta_ms": await estimate_ms(doc_type)}


@router.get("/notifications")
async def list_notifications(unread_only: bool = Query(False), limit: int = Query(30, ge=1, le=100),
                             user=Depends(get_current_user)):
    q = {"user": user.get("email")}
    if unread_only:
        q["read"] = False
    items = await db.docstudio_notifications.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    unread = await db.docstudio_notifications.count_documents({"user": user.get("email"), "read": False})
    return {"notifications": items, "unread": unread}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, user=Depends(get_current_user)):
    await db.docstudio_notifications.update_one(
        {"notification_id": notification_id, "user": user.get("email")}, {"$set": {"read": True}})
    return {"status": "read"}


@router.post("/notifications/read-all")
async def mark_all_read(user=Depends(get_current_user)):
    res = await db.docstudio_notifications.update_many(
        {"user": user.get("email"), "read": False}, {"$set": {"read": True}})
    return {"status": "read", "count": res.modified_count}


@router.post("/compose/from-template")
async def compose_generic(
    template_id: str = Query(...),
    company_id: str = Query(None),
    cif: str = Query(None),
    cnae_code: str = Query(None),
    brand_id: str = Query(None),
    user=Depends(get_current_user),
):
    """Compose a document from ANY user-created template. Universal composer."""
    t0 = time.time()
    doc = await compose_from_template(
        template_id, company_id=company_id, cif=cif,
        cnae_code=cnae_code, brand_id=brand_id, user=user.get("email"),
    )
    if "error" in doc:
        raise HTTPException(400, doc["error"])
    gen_ms = await _record_timing(doc["document_id"], t0)
    return {**_meta(t0), "document_id": doc["document_id"], "title": doc["title"],
            "sections": len(doc["sections"]), "status": doc["status"], "generation_time_ms": gen_ms}


@router.post("/templates/{template_id}/preview")
async def preview_template(template_id: str, brand_id: str = Query("brand_bud"), user=Depends(get_current_user)):
    """Preview how a template will look with sample data. Instant, no AI, no DB writes."""
    t0 = time.time()
    template = await db.docstudio_templates.find_one({"template_id": template_id}, {"_id": 0})
    if not template:
        raise HTTPException(404, "Template not found")

    brand = await db.docstudio_brands.find_one({"brand_id": brand_id}, {"_id": 0})
    if not brand:
        brand = BRANDS.get("bud_advisors", {})

    preview_doc = generate_template_preview(template, brand)
    return {**_meta(t0), "document": preview_doc}


# ══════════════════════════════════════════
# TELEMETRY
# ══════════════════════════════════════════

@router.get("/telemetry")
async def telemetry(user=Depends(get_current_user)):
    """Business metrics for DIS."""
    t0 = time.time()

    # By document type
    type_pipeline = [
        {"$group": {
            "_id": "$metadata.type",
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
    ]
    by_type = await db.docstudio_documents.aggregate(type_pipeline).to_list(20)

    # By template
    tpl_pipeline = [
        {"$group": {"_id": "$template_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_template = await db.docstudio_documents.aggregate(tpl_pipeline).to_list(20)

    # Export stats
    export_pipeline = [
        {"$group": {"_id": "$format", "count": {"$sum": 1}, "total_bytes": {"$sum": "$size_bytes"}}},
    ]
    by_format = await db.docstudio_exports.aggregate(export_pipeline).to_list(10)

    # Quality scores
    all_docs = await db.docstudio_documents.find({}, {"_id": 0}).to_list(100)
    from docstudio.composer import compute_quality_score
    grades = {"A": 0, "B": 0, "C": 0, "D": 0}
    total_score = 0
    for d in all_docs:
        q = compute_quality_score(d)
        grades[q["grade"]] = grades.get(q["grade"], 0) + 1
        total_score += q["global_score"]

    avg_quality = round(total_score / max(len(all_docs), 1))

    # AI usage
    ai_pipeline = [
        {"$group": {"_id": "$task", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    ai_by_task = await db.docstudio_ai_audit.aggregate(ai_pipeline).to_list(20)

    total_docs = await db.docstudio_documents.count_documents({})
    total_exports = await db.docstudio_exports.count_documents({})

    return {
        **_meta(t0),
        "total_documents": total_docs,
        "total_exports": total_exports,
        "export_ratio_pct": round(total_exports / max(total_docs, 1) * 100, 1),
        "by_document_type": [{"type": r["_id"] or "unknown", "count": r["count"]} for r in by_type],
        "by_template": [{"template": r["_id"], "count": r["count"]} for r in by_template],
        "by_export_format": [{"format": r["_id"], "count": r["count"], "total_mb": round(r["total_bytes"] / 1024 / 1024, 2)} for r in by_format],
        "quality": {"avg_score": avg_quality, "grades": grades},
        "ai_usage": [{"task": r["_id"], "calls": r["count"]} for r in ai_by_task],
    }


# ══════════════════════════════════════════
# EXPORT
# ══════════════════════════════════════════

@router.get("/export/{document_id}/pdf")
async def export_pdf(document_id: str, user=Depends(get_current_user)):
    """Export document to PDF."""
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")

    brand = await db.docstudio_brands.find_one({"brand_id": doc.get("brand_id", "brand_bud")}, {"_id": 0})
    if not brand:
        brand = BRANDS["bud_advisors"]

    pdf_bytes = await _render_document_pdf(doc, brand)

    # Log export
    await db.docstudio_exports.insert_one({
        "export_id": now_iso(),
        "document_id": document_id,
        "format": "pdf",
        "size_bytes": len(pdf_bytes),
        "exported_at": now_iso(),
        "exported_by": user.get("email"),
    })

    filename = doc.get("title", "document").replace(" ", "_")[:50]
    filename = ''.join(c for c in filename if c.isascii() and c not in '<>:"/\\|?*')
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


@router.get("/export/{document_id}/pptx")
async def export_pptx(document_id: str, user=Depends(get_current_user)):
    """Export document to editable PowerPoint."""
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")

    brand = await db.docstudio_brands.find_one({"brand_id": doc.get("brand_id", "brand_bud")}, {"_id": 0})
    if not brand:
        brand = BRANDS["bud_advisors"]

    from docstudio.pptx_export import export_to_pptx
    pptx_bytes = await export_to_pptx(doc, brand)

    await db.docstudio_exports.insert_one({
        "export_id": now_iso(),
        "document_id": document_id,
        "format": "pptx",
        "size_bytes": len(pptx_bytes),
        "exported_at": now_iso(),
        "exported_by": user.get("email"),
    })

    filename = doc.get("title", "document").replace(" ", "_")[:50]
    filename = ''.join(c for c in filename if c.isascii() and c not in '<>:"/\\|?*')
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pptx"'},
    )


# ══════════════════════════════════════════
# TEMPLATES & BRANDS
# ══════════════════════════════════════════

@router.get("/templates")
async def list_templates(user=Depends(get_current_user)):
    t0 = time.time()
    templates = await db.docstudio_templates.find({}, {"_id": 0}).to_list(50)
    return {**_meta(t0), "templates": templates}


@router.get("/brands")
async def list_brands(user=Depends(get_current_user)):
    t0 = time.time()
    brands = await db.docstudio_brands.find({}, {"_id": 0}).to_list(20)
    return {**_meta(t0), "brands": brands}


# ══════════════════════════════════════════
# AI AUDIT
# ══════════════════════════════════════════

@router.get("/ai-audit")
async def ai_audit(limit: int = Query(20, ge=1, le=100), user=Depends(get_current_user)):
    t0 = time.time()
    audits = await db.docstudio_ai_audit.find(
        {}, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    total = await db.docstudio_ai_audit.count_documents({})
    return {**_meta(t0), "audits": audits, "total": total}


# ══════════════════════════════════════════
# TEMPLATE BUILDER
# ══════════════════════════════════════════

class TemplateSection(BaseModel):
    title: str
    order: int
    block_types: List[str] = []
    data_source: Optional[str] = None
    ai_prompt: Optional[str] = None
    fields: Optional[List[str]] = None


class TemplateCreate(BaseModel):
    name: str
    description: str = ""
    category: str = "intelligence"
    brand_id: Optional[str] = None
    analysis_model: str = "openai"
    narrative_model: str = "openai"
    sections: List[TemplateSection] = []


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    brand_id: Optional[str] = None
    analysis_model: Optional[str] = None
    narrative_model: Optional[str] = None
    sections: Optional[List[TemplateSection]] = None


@router.post("/templates")
async def create_template(tpl: TemplateCreate, user=Depends(get_current_user)):
    """Create a new template from scratch."""
    t0 = time.time()
    now = now_iso()
    template = {
        "template_id": f"tpl_{now_iso()[:10].replace('-', '')}_{now_iso()[11:19].replace(':', '')}",
        "name": tpl.name,
        "description": tpl.description,
        "category": tpl.category,
        "brand_id": tpl.brand_id,
        "version": 1,
        "analysis_model": tpl.analysis_model,
        "narrative_model": tpl.narrative_model,
        "sections": [s.dict() for s in tpl.sections],
        "provider": "custom",
        "owner": user.get("email"),
        "status": "active",
        "visibility": "private",
        "created_at": now,
        "updated_at": now,
    }
    await db.docstudio_templates.insert_one(template)
    return {**_meta(t0), "template_id": template["template_id"], "version": 1}


@router.put("/templates/{template_id}")
async def update_template(template_id: str, update: TemplateUpdate, user=Depends(get_current_user)):
    """Update a template. Increments version."""
    t0 = time.time()
    existing = await db.docstudio_templates.find_one({"template_id": template_id})
    if not existing:
        raise HTTPException(404, "Template not found")

    now = now_iso()
    new_version = existing.get("version", 1) + 1

    # Save version history
    await db.docstudio_template_versions.insert_one({
        "template_id": template_id,
        "version": existing.get("version", 1),
        "snapshot": {k: v for k, v in existing.items() if k != "_id"},
        "saved_at": now,
        "saved_by": user.get("email"),
    })

    # Apply updates
    changes = {"version": new_version, "updated_at": now}
    for field in ["name", "description", "category", "brand_id", "analysis_model", "narrative_model"]:
        val = getattr(update, field, None)
        if val is not None:
            changes[field] = val
    if update.sections is not None:
        changes["sections"] = [s.dict() for s in update.sections]

    await db.docstudio_templates.update_one(
        {"template_id": template_id}, {"$set": changes}
    )
    return {**_meta(t0), "template_id": template_id, "version": new_version}


@router.post("/templates/{template_id}/duplicate")
async def duplicate_template(template_id: str, new_name: str = Query(...), user=Depends(get_current_user)):
    """Duplicate a template."""
    t0 = time.time()
    existing = await db.docstudio_templates.find_one({"template_id": template_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Template not found")

    now = now_iso()
    new_tpl = {**existing}
    new_tpl["template_id"] = f"tpl_{now_iso()[:10].replace('-', '')}_{now_iso()[11:19].replace(':', '')}"
    new_tpl["name"] = new_name
    new_tpl["version"] = 1
    new_tpl["owner"] = user.get("email")
    new_tpl["provider"] = "custom"
    new_tpl["created_at"] = now
    new_tpl["updated_at"] = now

    await db.docstudio_templates.insert_one(new_tpl)
    return {**_meta(t0), "template_id": new_tpl["template_id"], "name": new_name}


@router.get("/templates/{template_id}")
async def get_template(template_id: str, user=Depends(get_current_user)):
    """Get a single template with full detail."""
    t0 = time.time()
    tpl = await db.docstudio_templates.find_one({"template_id": template_id}, {"_id": 0})
    if not tpl:
        raise HTTPException(404, "Template not found")
    return {**_meta(t0), "template": tpl}


@router.get("/templates/{template_id}/versions")
async def template_versions(template_id: str, user=Depends(get_current_user)):
    """Get version history of a template."""
    t0 = time.time()
    versions = await db.docstudio_template_versions.find(
        {"template_id": template_id}, {"_id": 0}
    ).sort("version", -1).to_list(50)
    return {**_meta(t0), "template_id": template_id, "versions": versions}


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, user=Depends(get_current_user)):
    """Delete a custom template (not built-in ones)."""
    tpl = await db.docstudio_templates.find_one({"template_id": template_id}, {"_id": 0})
    if not tpl:
        raise HTTPException(404, "Template not found")
    if tpl.get("provider") != "custom":
        raise HTTPException(400, "Cannot delete built-in templates")
    await db.docstudio_templates.delete_one({"template_id": template_id})
    return {"status": "deleted", "template_id": template_id}


@router.post("/documents/{document_id}/save-as-template")
async def save_document_as_template(
    document_id: str,
    name: str = Query(...),
    category: str = Query("intelligence"),
    user=Depends(get_current_user),
):
    """Save an existing document's structure as a reusable template."""
    t0 = time.time()
    doc = await db.docstudio_documents.find_one({"document_id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")

    now = now_iso()

    # Extract section structure from the document (block types, not data)
    sections = []
    for s in doc.get("sections", []):
        block_types = list(set(b.get("block_type") for b in s.get("blocks", [])))
        data_sources = list(set(b.get("data_lineage", {}).get("source", "manual") for b in s.get("blocks", [])))
        sections.append({
            "title": s.get("title", ""),
            "order": s.get("order", 0),
            "block_types": block_types,
            "data_source": data_sources[0] if len(data_sources) == 1 else "mixed",
        })

    template = {
        "template_id": f"tpl_{now[:10].replace('-', '')}_{now[11:19].replace(':', '')}",
        "name": name,
        "description": f"Plantilla creada desde documento: {doc.get('title', '')}",
        "category": category,
        "brand_id": doc.get("brand_id"),
        "version": 1,
        "analysis_model": "openai",
        "narrative_model": "openai",
        "sections": sections,
        "provider": "custom",
        "owner": user.get("email"),
        "source_document_id": document_id,
        "status": "active",
        "visibility": "private",
        "created_at": now,
        "updated_at": now,
    }

    await db.docstudio_templates.insert_one(template)
    return {**_meta(t0), "template_id": template["template_id"], "name": name, "sections": len(sections)}


# ══════════════════════════════════════════
# FINANCIAL ENGINE
# ══════════════════════════════════════════

@router.get("/financial/company/{company_id}")
async def financial_analysis_company(company_id: str, user=Depends(get_current_user)):
    """Run full financial analysis for a company (deterministic, no AI).

    Fase 1 (2026-09-01): deja de leer la colección legacy `iberinform_financials`
    y delega en el motor financiero canónico moderno (vía docstudio/data_access.py),
    el mismo que ya usa compose_company_profile(). `company_id` acepta master_id o
    cif_normalized. Sin caller conocido en Intel/Beta/tests (verificado por grep)."""
    t0 = time.time()
    from docstudio import data_access as DA

    company = await DA.resolve_company(identifier=company_id)
    if not company:
        raise HTTPException(404, "No financial data for this company")

    analysis = await DA.financial_profile(company_id)
    if not analysis:
        raise HTTPException(404, "No financial data for this company")

    return {**_meta(t0), "company_id": company_id, "analysis": analysis}


@router.get("/financial/sector-benchmark/{cnae_code}")
async def sector_benchmark(cnae_code: str, user=Depends(get_current_user)):
    """Sector benchmark: quartiles, percentiles, rankings (deterministic, no AI)."""
    t0 = time.time()
    from docstudio.financial_engine import analyze_sector_benchmark

    benchmark = await analyze_sector_benchmark(cnae_code)
    return {**_meta(t0), **benchmark}


@router.get("/financial/compare")
async def compare_company_to_sector(
    company_id: str = Query(...),
    cnae_code: str = Query(...),
    user=Depends(get_current_user),
):
    """Compare a company against its sector peers (deterministic, no AI).

    Fase 1 (2026-09-01): el dato de la empresa objetivo deja de venir de
    `iberinform_financials` (legacy) y pasa a leerse de `master_companies` (vía
    docstudio/data_access.py). Mismo shape de respuesta que la versión legacy."""
    t0 = time.time()
    from docstudio import data_access as DA
    from docstudio.financial_engine import (
        analyze_sector_benchmark, revenue_per_employee, gap_vs_benchmark,
    )

    company = await DA.resolve_company(identifier=company_id)
    latest = (company.get("financials") or {}).get("latest") if company else None
    if not latest:
        raise HTTPException(404, "No financial data")

    employees = (company.get("size") or {}).get("employees_total")
    benchmark = await analyze_sector_benchmark(cnae_code)

    company_metrics = {
        "revenue": latest.get("revenue"),
        "ebitda": latest.get("ebitda"),
        "employees": employees,
        "ebitda_margin": latest.get("ebitda_margin"),
    }
    rev = latest.get("revenue") or 0
    emp = employees or 0
    if rev and emp:
        company_metrics["revenue_per_employee"] = revenue_per_employee(rev, emp)

    # Build comparison against sector benchmarks
    if benchmark.get("peers", 0) > 0:
        # Use quartile data as proxy for comparison
        for metric in ["revenue", "ebitda", "ebitda_margin", "revenue_per_employee"]:
            q = benchmark.get(metric, {})
            if q and company_metrics.get(metric) is not None:
                company_metrics[f"{metric}_vs_median"] = gap_vs_benchmark(
                    company_metrics[metric], q.get("median", 0)
                )

    return {
        **_meta(t0),
        "company_id": company_id,
        "cnae_code": cnae_code,
        "company_metrics": company_metrics,
        "sector_benchmark": benchmark,
    }


# ══════════════════════════════════════════
# TEMPLATE REGISTRY
# ══════════════════════════════════════════

TEMPLATE_REGISTRY = [
    # Intelligence
    {"id": "tpl_sector_report", "name": "Informe Sectorial", "category": "intelligence", "status": "active"},
    {"id": "tpl_company_profile", "name": "Ficha de Compania", "category": "intelligence", "status": "active"},
    {"id": "tpl_benchmark", "name": "Benchmark Report", "category": "intelligence", "status": "planned"},
    {"id": "tpl_snapshot", "name": "Company Snapshot", "category": "intelligence", "status": "planned"},
    # M&A
    {"id": "tpl_teaser", "name": "Teaser", "category": "mna", "status": "planned"},
    {"id": "tpl_im", "name": "Information Memorandum", "category": "mna", "status": "planned"},
    {"id": "tpl_investment_memo", "name": "Investment Memo", "category": "mna", "status": "planned"},
    {"id": "tpl_vdd", "name": "Vendor Due Diligence", "category": "mna", "status": "planned"},
    {"id": "tpl_cdd", "name": "Commercial Due Diligence", "category": "mna", "status": "planned"},
    # Legal
    {"id": "tpl_nda", "name": "NDA", "category": "legal", "status": "planned"},
    {"id": "tpl_spa", "name": "SPA (Share Purchase Agreement)", "category": "legal", "status": "planned"},
    {"id": "tpl_sha", "name": "SHA (Shareholders Agreement)", "category": "legal", "status": "planned"},
    {"id": "tpl_loi", "name": "LOI (Letter of Intent)", "category": "legal", "status": "planned"},
]


@router.get("/registry")
async def template_registry(user=Depends(get_current_user)):
    """Full template registry with categories and status."""
    t0 = time.time()
    categories = {}
    for t in TEMPLATE_REGISTRY:
        cat = t["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(t)

    return {
        **_meta(t0),
        "registry": TEMPLATE_REGISTRY,
        "by_category": categories,
        "total": len(TEMPLATE_REGISTRY),
        "active": sum(1 for t in TEMPLATE_REGISTRY if t["status"] == "active"),
        "planned": sum(1 for t in TEMPLATE_REGISTRY if t["status"] == "planned"),
    }
