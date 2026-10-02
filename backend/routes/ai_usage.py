"""Consumo de IA · API de la pantalla «Consumo de IA» (solo administradores) y entrada de eventos de Beta.

    GET  /api/v2/ai-usage/summary?days=30[&app=intel|beta-copilot]
    GET  /api/v2/ai-usage/recommendations?days=30
    GET  /api/v2/ai-usage/export.csv?days=30
    GET  /api/v2/ai-usage/prices      PUT /api/v2/ai-usage/prices
    POST /api/v2/ai-usage/ingest      (la clave de servicio de Beta; eventos anónimos, sin texto)
"""
import csv
import io
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth_utils import get_current_user
from routes.auth import require_admin
from services import ai_usage

router = APIRouter(prefix="/api/v2/ai-usage", tags=["ai_usage"])

ALLOWED_APPS = {"intel", "beta-copilot"}
FILTER_APPS = ALLOWED_APPS | {"intel-shadow"}


class UsageEvent(BaseModel):
    app: str = "beta-copilot"
    feature: str = Field(max_length=60)
    model: Optional[str] = Field(default=None, max_length=80)
    provider: Optional[str] = Field(default=None, max_length=30)
    in_tokens: int = Field(0, ge=0, le=5_000_000)
    out_tokens: int = Field(0, ge=0, le=5_000_000)
    duration_ms: int = Field(0, ge=0, le=3_600_000)
    status: str = Field("ok", max_length=60)
    estimated: bool = True
    kind: str = "llm_call"  # llm_call | llm_skipped


class IngestRequest(BaseModel):
    events: List[UsageEvent] = Field(max_length=200)


@router.get("/summary")
async def summary(days: int = Query(30, ge=1, le=365), app: Optional[str] = None, _admin=Depends(require_admin)):
    if app and app not in FILTER_APPS:
        raise HTTPException(400, "app desconocida")
    return await ai_usage.summary(days, app)


@router.get("/recommendations")
async def recommendations(days: int = Query(30, ge=1, le=365), _admin=Depends(require_admin)):
    return {"window_days": days, "items": await ai_usage.recommendations(days),
            "note": "Solo sugerencias: nada se cambia solo. El ahorro se calcula con los tokens medidos y las tarifas de la tabla."}


@router.get("/prices")
async def prices(_admin=Depends(require_admin)):
    return {"currency": "USD", "per": "1M tokens", "prices": await ai_usage.get_prices()}


class PricesRequest(BaseModel):
    prices: Dict[str, Dict[str, object]]


@router.put("/prices")
async def put_prices(req: PricesRequest, _admin=Depends(require_admin)):
    await ai_usage.set_prices(req.prices)  # type: ignore[arg-type]
    return {"ok": True, "prices": await ai_usage.get_prices()}


@router.get("/export.csv")
async def export_csv(days: int = Query(30, ge=1, le=365), _admin=Depends(require_admin)):
    data = await ai_usage.summary(days, None)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["funcion", "llamadas", "tokens_entrada", "tokens_salida", "errores", "coste_usd", "llamadas_sin_precio"])
    for r in data["by_feature"]:
        w.writerow([r["key"], r["calls"], r["in_tokens"], r["out_tokens"], r["errors"], r["cost_usd"], r["unpriced_calls"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=consumo_ia_{days}d.csv"})


@router.post("/ingest")
async def ingest(req: IngestRequest, user=Depends(get_current_user)):
    """Eventos del Copilot de Beta. Anónimos por diseño: sin usuario, sin organización y sin texto."""
    n = 0
    for e in req.events:
        if e.app not in ALLOWED_APPS or e.kind not in ("llm_call", "llm_skipped"):
            continue
        await ai_usage.record(app=e.app, feature=e.feature, model=e.model, provider=e.provider, in_tokens=e.in_tokens,
                              out_tokens=e.out_tokens, duration_ms=e.duration_ms, status=e.status,
                              estimated=e.estimated, kind=e.kind, at=datetime.now(timezone.utc))
        n += 1
    return {"accepted": n}


# ------------------------------------------------------------ presupuestos y avisos
class BudgetsRequest(BaseModel):
    items: List[Dict[str, object]] = Field(max_length=50)


@router.get("/budgets")
async def budgets(_admin=Depends(require_admin)):
    statuses = await ai_usage.budget_statuses()
    return {"items": statuses, "warn_at": ai_usage.WARN_AT, "scopes": list(ai_usage.BUDGET_SCOPES),
            "features": {k: v["label"] for k, v in ai_usage.FEATURES.items()},
            "alerts": [b for b in statuses if b["state"] in ("warning", "exceeded")],
            "note": "«Avisar» solo avisa. «Bloquear» deja de llamar al modelo en las funciones de Intel afectadas hasta que acabe el periodo; el Copilot de Beta solo recibe avisos."}


@router.put("/budgets")
async def put_budgets(req: BudgetsRequest, _admin=Depends(require_admin)):
    await ai_usage.set_budgets(req.items)  # type: ignore[arg-type]
    return {"items": await ai_usage.budget_statuses()}


# ------------------------------------------------------------ prueba en sombra
class ShadowRequest(BaseModel):
    items: List[Dict[str, object]] = Field(max_length=20)


@router.get("/shadow")
async def shadow(_admin=Depends(require_admin)):
    return {"items": await ai_usage.shadow_report(), "min_runs": ai_usage.MIN_RUNS_FOR_VERDICT,
            "json_agreement_min": ai_usage.JSON_AGREEMENT_MIN, "text_similarity_min": ai_usage.TEXT_SIMILARITY_MIN,
            "note": "Se repite una muestra de las llamadas reales con el modelo candidato, en segundo plano y sin afectar a la respuesta. Solo se guardan métricas, nunca texto. Las llamadas de prueba cuestan y salen como «Intel · pruebas en sombra»."}


@router.put("/shadow")
async def put_shadow(req: ShadowRequest, _admin=Depends(require_admin)):
    await ai_usage.set_shadow_tests(req.items)  # type: ignore[arg-type]
    return {"items": await ai_usage.shadow_report()}
