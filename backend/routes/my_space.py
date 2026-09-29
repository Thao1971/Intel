"""API de «Mi espacio»: perfil de rol y pipeline. Ver services/my_space.py.

Autenticación como el resto de rutas de usuario (get_current_user). El propietario es el
usuario final: JWT propio, o `X-Arroba-User-Id` inyectada por la pasarela de Beta (fail-closed,
misma regla que valoración avanzada).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from auth_utils import get_current_user
from database import db
from routes.valuations import _caller_is_jwt_user, _user_id
from services import my_space as S
from services import my_space_objects as O
from services import my_space_vigilance as V
from services import my_space_portfolio as P
from services import my_space_requests as Q
from services import my_space_valuation_scenarios as VS
from services import watchlist as W

router = APIRouter(prefix="/api/v1/my-space", tags=["my_space"])


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    roles: List[str]
    active_role: Optional[str] = None


class PipelineIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Optional[str] = None
    counterpart_name: str
    counterpart_type: Optional[str] = None
    cif: Optional[str] = None
    master_id: Optional[str] = None
    sector: Optional[str] = None
    provincia: Optional[str] = None
    mandate_id: Optional[str] = None
    status: Optional[str] = None
    turn: Optional[str] = None
    notes: Optional[str] = None


class PipelinePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    counterpart_name: Optional[str] = None
    sector: Optional[str] = None
    provincia: Optional[str] = None
    status: Optional[str] = None
    turn: Optional[str] = None
    notes: Optional[str] = None


def _bad(e: S.ValidationError):
    return HTTPException(422, str(e))


@router.get("/profile")
async def get_profile(request: Request, user=Depends(get_current_user)):
    prof = await S.get_profile(db.my_space_profiles, _user_id(user, request))
    # Sin perfil aún: no se adivina el rol, la UI debe pedirlo.
    return {"profile": prof, "available_roles": list(S.ROLES)}


@router.put("/profile")
async def put_profile(body: ProfileIn, request: Request, user=Depends(get_current_user)):
    try:
        return await S.set_profile(db.my_space_profiles, _user_id(user, request), body.roles, body.active_role)
    except S.ValidationError as e:
        raise _bad(e)


async def _active_role(owner: str, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    prof = await S.get_profile(db.my_space_profiles, owner)
    if not prof:
        raise HTTPException(409, "Define primero tu rol en /api/v1/my-space/profile")
    return prof["active_role"]


@router.get("/pipeline")
async def list_pipeline(request: Request, role: Optional[str] = None, status: Optional[str] = None,
                        turn: Optional[str] = None, user=Depends(get_current_user)):
    owner = _user_id(user, request)
    try:
        role = await _active_role(owner, role)
        items = await S.list_items(db.my_space_pipeline, owner, role, status, turn)
    except S.ValidationError as e:
        raise _bad(e)
    return {"role": role, "items": items, "summary": S.summarize(items),
            "statuses": {k: {"has_turn": v["has_turn"]} for k, v in S.STATUS_CFG.items()}}


@router.post("/pipeline", status_code=201)
async def create_pipeline_item(body: PipelineIn, request: Request, user=Depends(get_current_user)):
    owner = _user_id(user, request)
    try:
        role = await _active_role(owner, body.role)
        return await S.create_item(db.my_space_pipeline, owner, role, body.model_dump())
    except S.ValidationError as e:
        raise _bad(e)


@router.patch("/pipeline/{item_id}")
async def patch_pipeline_item(item_id: str, body: PipelinePatch, request: Request, user=Depends(get_current_user)):
    try:
        out = await S.update_item(db.my_space_pipeline, _user_id(user, request), item_id,
                                  body.model_dump(exclude_unset=True))
    except S.ValidationError as e:
        raise _bad(e)
    if out is None:
        raise HTTPException(404, "elemento no encontrado")
    return out


@router.delete("/pipeline/{item_id}")
async def delete_pipeline_item(item_id: str, request: Request, user=Depends(get_current_user)):
    if not await S.delete_item(db.my_space_pipeline, _user_id(user, request), item_id):
        raise HTTPException(404, "elemento no encontrado")
    return {"deleted": item_id}


# ------------------------------------------------------------------ objeto central (vendedor / busca capital)
class ObjectIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str
    company_name: str
    cif: Optional[str] = None
    headline: Optional[str] = None
    notes: Optional[str] = None
    # vendedor
    sale_type: Optional[str] = None
    asking_price_eur: Optional[float] = None
    teaser_status: Optional[str] = None
    timeline: Optional[str] = None
    # busca capital
    amount_min_eur: Optional[float] = None
    amount_max_eur: Optional[float] = None
    instrument: Optional[str] = None
    use_of_funds: Optional[str] = None


@router.get("/object")
async def get_object(role: str, request: Request, user=Depends(get_current_user)):
    if role not in O.OBJECT_ROLES:
        raise HTTPException(422, f"el rol {role} no tiene objeto central editable")
    return {"role": role, "object": await O.get_object(db.my_space_objects, _user_id(user, request), role)}


@router.put("/object")
async def put_object(body: ObjectIn, request: Request, user=Depends(get_current_user)):
    try:
        data = body.model_dump()
        role = data.pop("role")
        return await O.save_object(db.my_space_objects, db.master_companies, _user_id(user, request), role, data)
    except S.ValidationError as e:
        raise _bad(e)


async def _providers() -> Dict[str, Any]:
    # Import diferido: estos módulos cargan el motor completo.
    from services.engines.recommendation import engine as rec_engine
    from services.engines.recommendation import mandates as M
    from services.cnmv_investor_intelligence import get_buyers_for_cnae
    return {"buyers": rec_engine.buyers, "cnmv": get_buyers_for_cnae, "mandates": M.find_mandates_for_target}


@router.get("/object/matches")
async def object_matches(role: str, request: Request, user=Depends(get_current_user)):
    owner = _user_id(user, request)
    try:
        obj = await O.get_object(db.my_space_objects, owner, role)
        return await O.build_matches(role, obj, await _providers())
    except S.ValidationError as e:
        raise _bad(e)


# ------------------------------------------------------------------ vigilancia (alertas por usuario)
class WatchSyncIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cifs: List[str]


@router.post("/vigilance/sync")
async def vigilance_sync(body: WatchSyncIn, request: Request, user=Depends(get_current_user)):
    try:
        return await V.sync_watches(_user_id(user, request), body.cifs, db.master_companies)
    except S.ValidationError as e:
        raise _bad(e)


@router.get("/vigilance")
async def vigilance_list(request: Request, unread_only: bool = False, user=Depends(get_current_user)):
    return await V.list_alerts(_user_id(user, request), db.master_companies, unread_only=unread_only)


@router.post("/vigilance/alerts/{alert_id}/read")
async def vigilance_mark_read(alert_id: str, request: Request, user=Depends(get_current_user)):
    if not await W.mark_alert_read(_user_id(user, request), alert_id):
        raise HTTPException(404, "alerta no encontrada")
    return {"status": "read", "alert_id": alert_id}


# ------------------------------------------------------------------ cartera del asesor
class PortfolioIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    client_name: str
    kind: Optional[str] = None
    company_name: Optional[str] = None
    cif: Optional[str] = None
    stage: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[str] = None
    notes: Optional[str] = None


class PortfolioPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    client_name: Optional[str] = None
    kind: Optional[str] = None
    company_name: Optional[str] = None
    cif: Optional[str] = None
    stage: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[str] = None
    notes: Optional[str] = None


@router.get("/portfolio")
async def portfolio_list(request: Request, user=Depends(get_current_user)):
    items = await P.list_items(db.my_space_portfolio, _user_id(user, request))
    return {"items": items, "summary": P.summarize(items), "kinds": list(P.KINDS), "stages": list(P.STAGES)}


@router.post("/portfolio", status_code=201)
async def portfolio_create(body: PortfolioIn, request: Request, user=Depends(get_current_user)):
    try:
        return await P.create_item(db.my_space_portfolio, db.master_companies, _user_id(user, request), body.model_dump())
    except S.ValidationError as e:
        raise _bad(e)


@router.patch("/portfolio/{item_id}")
async def portfolio_patch(item_id: str, body: PortfolioPatch, request: Request, user=Depends(get_current_user)):
    try:
        out = await P.update_item(db.my_space_portfolio, db.master_companies, _user_id(user, request), item_id,
                                  body.model_dump(exclude_unset=True))
    except S.ValidationError as e:
        raise _bad(e)
    if out is None:
        raise HTTPException(404, "elemento no encontrado")
    return out


@router.delete("/portfolio/{item_id}")
async def portfolio_delete(item_id: str, request: Request, user=Depends(get_current_user)):
    if not await P.delete_item(db.my_space_portfolio, _user_id(user, request), item_id):
        raise HTTPException(404, "elemento no encontrado")
    return {"deleted": item_id}


# ------------------------------------------------------------------ escenarios de valoración editados (privados)
class ValuationScenarioIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cif: str
    company_name: Optional[str] = None
    run_id: Optional[str] = None
    label: Optional[str] = None
    inputs: Dict[str, Any]
    outputs: Optional[Dict[str, Any]] = None
    reference: Optional[Dict[str, Any]] = None


@router.get("/valuation-scenarios")
async def valuation_scenarios_list(request: Request, cif: Optional[str] = None, user=Depends(get_current_user)):
    items = await VS.list_scenarios(db.my_space_valuation_scenarios, _user_id(user, request), cif)
    return {"items": items}


@router.post("/valuation-scenarios", status_code=201)
async def valuation_scenarios_create(body: ValuationScenarioIn, request: Request, user=Depends(get_current_user)):
    try:
        return await VS.create_scenario(db.my_space_valuation_scenarios, _user_id(user, request), body.model_dump())
    except S.ValidationError as e:
        raise _bad(e)


@router.get("/valuation-scenarios/{scenario_id}")
async def valuation_scenarios_get(scenario_id: str, request: Request, user=Depends(get_current_user)):
    item = await VS.get_scenario(db.my_space_valuation_scenarios, _user_id(user, request), scenario_id)
    if item is None:
        raise HTTPException(404, "escenario no encontrado")
    return item


@router.delete("/valuation-scenarios/{scenario_id}")
async def valuation_scenarios_delete(scenario_id: str, request: Request, user=Depends(get_current_user)):
    if not await VS.delete_scenario(db.my_space_valuation_scenarios, _user_id(user, request), scenario_id):
        raise HTTPException(404, "escenario no encontrado")
    return {"deleted": scenario_id}


# ------------------------------------------------------------------ solicitudes de acceso y NDA (sin chat)
def _user_name(user, request: Request) -> Optional[str]:
    """Nombre del usuario final: el de su JWT, o el que inyecta la pasarela tras validar la sesión."""
    if _caller_is_jwt_user(request):
        return (user.get("full_name") or user.get("name") or user.get("email")) if isinstance(user, dict) else None
    from urllib.parse import unquote  # la pasarela lo envía percent-encoded (las cabeceras son Latin-1)
    return unquote(request.headers.get("x-arroba-user-name", "")).strip() or None


def _req_colls() -> Dict[str, Any]:
    return {"objects": db.my_space_objects, "requests": db.my_space_requests, "pipeline": db.my_space_pipeline}


def _http(e: Exception):
    if isinstance(e, LookupError):
        return HTTPException(404, str(e))
    return HTTPException(422, str(e))


class PublishIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    published: bool


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    listing_id: str
    as_role: str
    message: Optional[str] = None
    org_name: Optional[str] = None


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    decision: str


class AcceptNdaIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text_hash: str


@router.put("/object/publish")
async def publish_listing(body: PublishIn, request: Request, user=Depends(get_current_user)):
    try:
        obj = await Q.set_published(db.my_space_objects, _user_id(user, request), body.published)
    except S.ValidationError as e:
        raise _bad(e)
    return {"published": bool(obj.get("published")), "listing": Q.public_listing(obj) if obj.get("published") else None}


@router.get("/marketplace")
async def marketplace(request: Request, user=Depends(get_current_user)):
    items = await Q.list_marketplace(db.my_space_objects, _user_id(user, request), db.my_space_requests)
    return {"count": len(items), "listings": items,
            "basis": "Anuncios publicados por sus propietarios. Son anónimos: no incluyen nombre, CIF, precio ni cifras hasta que hay NDA."}


@router.get("/nda-template")
async def nda_template(user=Depends(get_current_user)):
    return Q.nda_template()


@router.get("/requests/summary")
async def requests_summary(request: Request, user=Depends(get_current_user)):
    return await Q.summary(_req_colls(), _user_id(user, request))


@router.get("/requests")
async def requests_list(box: str, request: Request, user=Depends(get_current_user)):
    try:
        return {"box": box, "requests": await Q.list_requests(_req_colls(), _user_id(user, request), box)}
    except S.ValidationError as e:
        raise _bad(e)


@router.post("/requests", status_code=201)
async def requests_create(body: RequestIn, request: Request, user=Depends(get_current_user)):
    try:
        req = await Q.create_request(_req_colls(), _user_id(user, request), _user_name(user, request),
                                     body.listing_id, body.as_role, body.message, body.org_name)
        return await Q.view_for(_req_colls(), req["buyer_id"], req)
    except (S.ValidationError, LookupError) as e:
        raise _http(e)


@router.get("/requests/{req_id}")
async def requests_get(req_id: str, request: Request, user=Depends(get_current_user)):
    try:
        return await Q.get_request(_req_colls(), _user_id(user, request), req_id)
    except LookupError as e:
        raise _http(e)


async def _act(fn, request: Request, user, req_id: str, *args):
    uid = _user_id(user, request)
    try:
        req = await fn(_req_colls(), uid, req_id, *args)
        return await Q.view_for(_req_colls(), uid, req)
    except (S.ValidationError, LookupError) as e:
        raise _http(e)


@router.post("/requests/{req_id}/decision")
async def requests_decide(req_id: str, body: DecisionIn, request: Request, user=Depends(get_current_user)):
    return await _act(Q.decide, request, user, req_id, body.decision)


@router.post("/requests/{req_id}/accept-nda")
async def requests_accept_nda(req_id: str, body: AcceptNdaIn, request: Request, user=Depends(get_current_user)):
    return await _act(Q.accept_nda, request, user, req_id, body.text_hash)


@router.post("/requests/{req_id}/withdraw")
async def requests_withdraw(req_id: str, request: Request, user=Depends(get_current_user)):
    return await _act(Q.withdraw, request, user, req_id)
