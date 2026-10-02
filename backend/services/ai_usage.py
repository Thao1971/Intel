"""Consumo de IA de la plataforma (Intel + Copilot de Beta).

Un único registro para todas las llamadas de pago a modelos:

* Intel: `install()` envuelve `LlmChat.send_message` una sola vez al arrancar, así que cubre los ~12 sitios
  que llaman a un modelo (editorial, DocStudio, clasificación, taxonomía, skills, semántica…) y cualquiera
  que se añada después, sin tocar cada uno.
* Beta: el Copilot envía aquí cada llamada (anónima, sin usuario ni texto) por `POST /api/v2/ai-usage/ingest`.

Nunca se guarda el texto de un prompt ni de una respuesta. Los tokens son una ESTIMACIÓN por longitud
(`CHARS_PER_TOKEN`) salvo que quien envía el evento los dé reales (`estimated=False`).

Las tarifas son las públicas de cada proveedor, aproximadas y en USD por millón de tokens; se pueden
corregir desde la propia pantalla (colección `ai_usage_settings`). Un modelo sin tarifa se cuenta como
«sin precio» y se avisa; nunca se inventa un coste.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

CHARS_PER_TOKEN = 3.6  # texto de negocio en español con cifras; aproximación declarada

# Niveles: small = clasificar / extraer / traducir; medium = redactar con datos dados; large = razonar largo.
TIER_ORDER = {"small": 1, "medium": 2, "large": 3}

# USD por millón de tokens (entrada, salida). Tarifas públicas aproximadas; editables en la pantalla.
DEFAULT_PRICES: Dict[str, Dict[str, Any]] = {
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0, "tier": "small", "provider": "anthropic"},
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0, "tier": "small", "provider": "anthropic"},
    "claude-sonnet-4-5": {"in": 3.0, "out": 15.0, "tier": "medium", "provider": "anthropic"},
    "claude-sonnet-4-5-20250929": {"in": 3.0, "out": 15.0, "tier": "medium", "provider": "anthropic"},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0, "tier": "medium", "provider": "anthropic"},
    "claude-opus-4-5": {"in": 5.0, "out": 25.0, "tier": "large", "provider": "anthropic"},
    "claude-opus-4-1": {"in": 15.0, "out": 75.0, "tier": "large", "provider": "anthropic"},
    "gpt-5-nano": {"in": 0.05, "out": 0.40, "tier": "small", "provider": "openai"},
    "gpt-5-mini": {"in": 0.25, "out": 2.0, "tier": "small", "provider": "openai"},
    "gpt-5": {"in": 1.25, "out": 10.0, "tier": "medium", "provider": "openai"},
    "gpt-5.1": {"in": 1.25, "out": 10.0, "tier": "medium", "provider": "openai"},
    "gpt-5.2": {"in": 1.75, "out": 14.0, "tier": "large", "provider": "openai"},
    "gpt-5.5": {"in": 1.75, "out": 14.0, "tier": "large", "provider": "openai"},
    "gpt-4o": {"in": 2.5, "out": 10.0, "tier": "medium", "provider": "openai"},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60, "tier": "small", "provider": "openai"},
}

# Qué nivel necesita cada función como mínimo (editable en la pantalla de ajustes si hiciera falta).
FEATURES: Dict[str, Dict[str, str]] = {
    "editorial_classify": {"label": "Editorial · clasificar noticias", "needs": "small"},
    "editorial_compose": {"label": "Editorial · redactar viñetas", "needs": "small"},
    "editorial_translate": {"label": "Editorial · traducir titulares", "needs": "small"},
    "doc_generate": {"label": "Documentos · generar", "needs": "medium"},
    "doc_rewrite": {"label": "Documentos · reescribir", "needs": "small"},
    "docstudio": {"label": "Document Studio", "needs": "medium"},
    "transactions_classify": {"label": "Transacciones · clasificar", "needs": "small"},
    "company_classify": {"label": "Empresas · clasificar y extraer", "needs": "small"},
    "taxonomy_suggest": {"label": "Taxonomía · sugerir códigos", "needs": "small"},
    "skills_analyze": {"label": "Skills · análisis narrativo", "needs": "medium"},
    "semantic_extract": {"label": "Semántica · extraer capacidades", "needs": "small"},
    "ai_chat": {"label": "AI Chat", "needs": "medium"},
    "copilot_draft": {"label": "Copilot · redacción de respuestas", "needs": "medium"},
    "copilot_structure": {"label": "Copilot · estructura JSON", "needs": "small"},
    "copilot_summary": {"label": "Copilot · resumen de conversación", "needs": "small"},
    "copilot_interpreter": {"label": "Copilot · interpretación de la petición", "needs": "small"},
}

# Prefijo del session_id de LlmChat → función. Más largos primero.
_SESSION_FEATURES = [
    ("classify-tx-", "transactions_classify"), ("taxonomy-suggest-", "taxonomy_suggest"),
    ("editorial-", "editorial_classify"), ("compose-", "editorial_compose"), ("translate-", "editorial_translate"),
    ("docgen-", "doc_generate"), ("docrewrite-", "doc_rewrite"), ("docstudio_", "docstudio"),
    ("classify-", "company_classify"), ("analyze-", "skills_analyze"), ("sem-", "semantic_extract"),
]

class AIBudgetExceeded(RuntimeError):
    """Raised instead of calling the model when a «block» budget is exhausted."""


_blocked_features: set = set()
_PENDING_LIMIT = 5000
_main_loop: Optional[asyncio.AbstractEventLoop] = None
_installed = False


# ------------------------------------------------------------------ pure helpers
def estimate_tokens(text: Any) -> int:
    return math.ceil(len(text if isinstance(text, str) else str(text or "")) / CHARS_PER_TOKEN)


def feature_for_session(session_id: str, default: str = "other") -> str:
    sid = session_id or ""
    for prefix, feature in _SESSION_FEATURES:
        if sid.startswith(prefix):
            return feature
    return default


def cost_usd(model: Optional[str], tin: int, tout: int, prices: Dict[str, Dict[str, Any]]) -> Optional[float]:
    p = prices.get(model or "")
    if not p:
        return None
    return (tin * float(p["in"]) + tout * float(p["out"])) / 1_000_000


def recommend(feature: str, current_model: str, tin: int, tout: int, calls: int, error_rate: float,
              prices: Dict[str, Dict[str, Any]], needs: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Cheapest model that still meets the level the function needs. Never changes anything: it only suggests.

    The quality risk is read from what is measured (error rate) and from how far down the level goes; a
    function that already fails with the current model is not told to downgrade."""
    needs = needs or FEATURES.get(feature, {}).get("needs", "medium")
    cur = prices.get(current_model)
    if not cur or calls <= 0:
        return None
    candidates = [(m, p) for m, p in prices.items()
                  if TIER_ORDER.get(p.get("tier", "medium"), 2) >= TIER_ORDER[needs] and m != current_model
                  and not m.endswith("-20250929")
                  and (not cur.get("provider") or p.get("provider") == cur.get("provider"))]  # same provider: same key and terms
    if not candidates:
        return None

    def price_of(p):  # mix of in/out as the function really uses it
        return (tin * float(p["in"]) + tout * float(p["out"]))

    best_model, best = min(candidates, key=lambda mp: price_of(mp[1]))
    saving = (price_of(cur) - price_of(best)) / 1_000_000
    if saving <= 0:
        return None
    tier_gap = TIER_ORDER.get(cur.get("tier", "medium"), 2) - TIER_ORDER.get(best.get("tier", "medium"), 2)
    if error_rate > 0.05:
        risk, note = "high", "La función ya falla con el modelo actual: primero conviene estabilizarla."
    elif tier_gap >= 2 or (tier_gap == 1 and needs == "medium"):
        risk, note = "medium", "Cambio de nivel: pruébalo en sombra antes de aplicarlo."
    else:
        risk, note = "low", "La función solo necesita este nivel; el cambio no debería notarse."
    return {"feature": feature, "current_model": current_model, "suggested_model": best_model,
            "monthly_saving_usd": round(saving, 4), "saving_pct": round(100 * saving / (price_of(cur) / 1_000_000), 1),
            "risk": risk, "note": note, "needs": needs}


def _db():
    from database import db  # lazy: keeps the pure helpers importable without a database
    return db


# ------------------------------------------------------------------ recording
_indexed = False


async def _insert(event: Dict[str, Any]) -> None:
    global _indexed
    try:
        if not _indexed:
            _indexed = True  # once; the first insert pays for the indexes, startup does not wait for them
            await _db().ai_usage.create_index([("at", -1)])
            await _db().ai_usage.create_index([("app", 1), ("feature", 1)])
        await _db().ai_usage.insert_one(event)
        await refresh_blocked()
        await refresh_shadow()
    except Exception:  # noqa: BLE001 — metering must never break the call it measures
        pass


async def record(*, app: str, feature: str, model: Optional[str], provider: Optional[str] = None,
                 in_tokens: int = 0, out_tokens: int = 0, duration_ms: int = 0, status: str = "ok",
                 estimated: bool = True, kind: str = "llm_call", at: Optional[datetime] = None) -> None:
    await _insert({"at": at or datetime.now(timezone.utc), "app": app, "feature": feature, "model": model,
                   "provider": provider, "in_tokens": int(in_tokens), "out_tokens": int(out_tokens),
                   "duration_ms": int(duration_ms), "status": status, "estimated": bool(estimated), "kind": kind})


def _enqueue(event: Dict[str, Any]) -> None:
    """Schedule the insert on the main loop (the DocStudio worker runs its own loop in a thread)."""
    loop = _main_loop
    if loop is None or loop.is_closed():
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    coro = _insert(event)
    if running is loop:
        loop.create_task(coro)
    else:
        asyncio.run_coroutine_threadsafe(coro, loop)


def install() -> bool:
    """Wrap `LlmChat.send_message` once. Safe to call repeatedly; does nothing if the library is absent."""
    global _installed, _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    if _installed:
        return True
    try:
        from emergentintegrations.llm.chat import LlmChat
    except Exception:  # noqa: BLE001
        return False
    original = LlmChat.send_message

    async def metered(self, message, *args, **kwargs):
        started = time.monotonic()
        status, out = "ok", None
        feature = feature_for_session(str(getattr(self, "session_id", "")), "other")
        if feature in _blocked_features:  # a budget with action «block» is exhausted (cache, no I/O here)
            _enqueue({"at": datetime.now(timezone.utc), "app": "intel", "feature": feature, "model": getattr(self, "model", None),
                      "provider": getattr(self, "provider", None), "in_tokens": 0, "out_tokens": 0, "duration_ms": 0,
                      "status": "BudgetBlocked", "estimated": False, "kind": "llm_call"})
            raise AIBudgetExceeded(f"Presupuesto de IA agotado para «{feature}». Revisa Consumo de IA → Presupuestos.")
        try:
            out = await original(self, message, *args, **kwargs)
            _maybe_shadow(self, message, out, feature)
            return out
        except Exception as exc:
            status = type(exc).__name__
            raise
        finally:
            try:
                text_in = getattr(message, "text", message)
                tin = estimate_tokens(getattr(self, "system_message", "")) + estimate_tokens(text_in)
                tout = estimate_tokens(out if isinstance(out, str) else getattr(out, "content", out))
                _enqueue({"at": datetime.now(timezone.utc), "app": "intel",
                          "feature": feature,
                          "model": getattr(self, "model", None), "provider": getattr(self, "provider", None),
                          "in_tokens": tin, "out_tokens": tout, "duration_ms": int((time.monotonic() - started) * 1000),
                          "status": status, "estimated": True, "kind": "llm_call"})
            except Exception:  # noqa: BLE001
                pass

    LlmChat.send_message = metered
    _installed = True
    return True


# ------------------------------------------------------------------ prices (editable)
async def get_prices() -> Dict[str, Dict[str, Any]]:
    prices = {m: dict(p) for m, p in DEFAULT_PRICES.items()}
    try:
        doc = await _db().ai_usage_settings.find_one({"_id": "prices"}) or {}
    except Exception:  # noqa: BLE001
        doc = {}
    for model, p in (doc.get("prices") or {}).items():
        base = prices.get(model, {"tier": "medium", "provider": None})
        prices[model] = {**base, **{k: p[k] for k in ("in", "out", "tier", "provider") if k in p}}
    return prices


async def set_prices(prices: Dict[str, Dict[str, Any]]) -> None:
    clean = {}
    for model, p in prices.items():
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", model or ""):
            continue
        try:
            clean[model] = {"in": float(p["in"]), "out": float(p["out"]),
                            "tier": p.get("tier") if p.get("tier") in TIER_ORDER else "medium",
                            "provider": str(p.get("provider") or "")[:30] or None}
        except (KeyError, TypeError, ValueError):
            continue
    await _db().ai_usage_settings.update_one({"_id": "prices"}, {"$set": {"prices": clean}}, upsert=True)


# ------------------------------------------------------------------ reading
async def _rows(days: int, app: Optional[str]) -> List[Dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    q: Dict[str, Any] = {"at": {"$gte": since}}
    if app:
        q["app"] = app
    return [r async for r in _db().ai_usage.find(q, {"_id": 0})]


def _agg(rows: List[Dict[str, Any]], key: str, prices: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"calls": 0, "in_tokens": 0, "out_tokens": 0, "errors": 0,
                                                          "cost_usd": 0.0, "unpriced_calls": 0, "ms": 0})
    for r in rows:
        if r.get("kind") != "llm_call":
            continue
        a = agg[str(r.get(key))]
        a["calls"] += 1
        a["in_tokens"] += r.get("in_tokens", 0)
        a["out_tokens"] += r.get("out_tokens", 0)
        a["ms"] += r.get("duration_ms", 0)
        if r.get("status") != "ok":
            a["errors"] += 1
        c = cost_usd(r.get("model"), r.get("in_tokens", 0), r.get("out_tokens", 0), prices)
        if c is None:
            a["unpriced_calls"] += 1
        else:
            a["cost_usd"] += c
    out = []
    for k, a in agg.items():
        out.append({"key": k, "calls": a["calls"], "in_tokens": a["in_tokens"], "out_tokens": a["out_tokens"],
                    "errors": a["errors"], "error_rate": round(a["errors"] / a["calls"], 4) if a["calls"] else 0,
                    "avg_ms": round(a["ms"] / a["calls"]) if a["calls"] else 0,
                    "cost_usd": round(a["cost_usd"], 4), "unpriced_calls": a["unpriced_calls"]})
    return sorted(out, key=lambda x: -x["cost_usd"] if x["cost_usd"] else -x["in_tokens"] - x["out_tokens"])


async def summary(days: int = 30, app: Optional[str] = None) -> Dict[str, Any]:
    prices = await get_prices()
    rows = await _rows(days, app)
    calls = [r for r in rows if r.get("kind") == "llm_call"]
    skipped = [r for r in rows if r.get("kind") == "llm_skipped"]
    total = _agg(rows, "app", prices)
    cost = round(sum(t["cost_usd"] for t in total), 4)
    unpriced = sum(t["unpriced_calls"] for t in total)
    by_day: Dict[str, Dict[str, float]] = defaultdict(lambda: {"calls": 0, "tokens": 0, "cost_usd": 0.0})
    for r in calls:
        d = r["at"].astimezone(timezone.utc).strftime("%Y-%m-%d") if isinstance(r["at"], datetime) else str(r["at"])[:10]
        by_day[d]["calls"] += 1
        by_day[d]["tokens"] += r.get("in_tokens", 0) + r.get("out_tokens", 0)
        c = cost_usd(r.get("model"), r.get("in_tokens", 0), r.get("out_tokens", 0), prices)
        by_day[d]["cost_usd"] += c or 0.0
    errors = sum(1 for r in calls if r.get("status") != "ok")
    return {
        "window_days": days, "tokens_are_estimates": any(r.get("estimated", True) for r in calls),
        "chars_per_token": CHARS_PER_TOKEN, "currency": "USD", "prices_note": "Tarifas públicas aproximadas; editables.",
        "calls": len(calls), "errors": errors, "error_rate": round(errors / len(calls), 4) if calls else 0,
        "turns_without_model_call": len(skipped),
        "in_tokens": sum(r.get("in_tokens", 0) for r in calls), "out_tokens": sum(r.get("out_tokens", 0) for r in calls),
        "cost_usd": cost, "unpriced_calls": unpriced,
        "by_app": total, "by_feature": _agg(rows, "feature", prices), "by_model": _agg(rows, "model", prices),
        "by_day": [{"day": d, **{k: (round(v, 4) if k == "cost_usd" else v) for k, v in vals.items()}}
                   for d, vals in sorted(by_day.items())],
        "features": {k: v for k, v in FEATURES.items()},
    }


async def recommendations(days: int = 30) -> List[Dict[str, Any]]:
    """One suggestion per (function, model) pair that could be cheaper at the level the function needs."""
    prices = await get_prices()
    rows = [r for r in await _rows(days, None) if r.get("kind") == "llm_call"]
    pairs: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        pairs[(r.get("feature"), r.get("model"))].append(r)
    out = []
    scale = 30.0 / max(1, days)  # to a monthly figure
    for (feature, model), rs in pairs.items():
        tin, tout = sum(r.get("in_tokens", 0) for r in rs), sum(r.get("out_tokens", 0) for r in rs)
        err = sum(1 for r in rs if r.get("status") != "ok") / len(rs)
        rec = recommend(str(feature), str(model), tin, tout, len(rs), err, prices)
        if rec:
            rec["monthly_saving_usd"] = round(rec["monthly_saving_usd"] * scale, 4)
            rec["calls"] = len(rs)
            rec["label"] = FEATURES.get(str(feature), {}).get("label", str(feature))
            out.append(rec)
    return sorted(out, key=lambda r: -r["monthly_saving_usd"])


# =================================================================== Phase 3 · budgets and alerts
# Una partida: {"scope": "total|app|feature", "key": "...", "period": "day|month", "limit_usd": 5.0,
#               "action": "alert|block", "enabled": true}.  «alert» solo avisa (por defecto); «block» además
# deja de llamar al modelo en las funciones de Intel afectadas hasta que acabe el periodo. El Copilot de
# Beta solo recibe avisos: Intel no puede pararle desde aquí.
WARN_AT = 0.8
BUDGET_SCOPES = ("total", "app", "feature")
BUDGET_PERIODS = ("day", "month")
_BUDGET_TTL_S = 60.0
_budget_checked_at = 0.0


def clean_budget(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        scope, period = item.get("scope"), item.get("period")
        limit = float(item["limit_usd"])
        key = str(item.get("key") or "")[:60]
    except (KeyError, TypeError, ValueError):
        return None
    if scope not in BUDGET_SCOPES or period not in BUDGET_PERIODS or limit <= 0 or (scope != "total" and not key):
        return None
    return {"scope": scope, "key": "" if scope == "total" else key, "period": period, "limit_usd": round(limit, 2),
            "action": "block" if item.get("action") == "block" else "alert", "enabled": bool(item.get("enabled", True))}


def budget_state(spent: float, limit: float) -> str:
    ratio = spent / limit if limit else 0
    return "exceeded" if ratio >= 1 else "warning" if ratio >= WARN_AT else "ok"


def period_start(period: str, now: Optional[datetime] = None) -> datetime:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.replace(day=1) if period == "month" else start


def matches(row: Dict[str, Any], scope: str, key: str) -> bool:
    return scope == "total" or (scope == "app" and row.get("app") == key) or (scope == "feature" and row.get("feature") == key)


def spend_of(rows: List[Dict[str, Any]], scope: str, key: str, since: datetime, prices: Dict[str, Dict[str, Any]]) -> float:
    total = 0.0
    for r in rows:
        if r.get("kind") != "llm_call" or not matches(r, scope, key):
            continue
        at = r["at"] if isinstance(r["at"], datetime) else datetime.fromisoformat(str(r["at"]))
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at >= since:
            total += cost_usd(r.get("model"), r.get("in_tokens", 0), r.get("out_tokens", 0), prices) or 0.0
    return total


async def get_budgets() -> List[Dict[str, Any]]:
    doc = await _db().ai_usage_settings.find_one({"_id": "budgets"}) or {}
    return [b for b in (clean_budget(i) for i in doc.get("items", [])) if b]


async def set_budgets(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean = [b for b in (clean_budget(i) for i in items[:50]) if b]
    await _db().ai_usage_settings.update_one({"_id": "budgets"}, {"$set": {"items": clean}}, upsert=True)
    await refresh_blocked(force=True)
    return clean


async def budget_statuses() -> List[Dict[str, Any]]:
    budgets = await get_budgets()
    if not budgets:
        return []
    prices = await get_prices()
    rows = await _rows(31, None)
    out = []
    for b in budgets:
        spent = spend_of(rows, b["scope"], b["key"], period_start(b["period"]), prices)
        out.append({**b, "spent_usd": round(spent, 4), "ratio": round(spent / b["limit_usd"], 4),
                    "state": budget_state(spent, b["limit_usd"]) if b["enabled"] else "off"})
    return out


async def refresh_blocked(force: bool = False) -> None:
    """Recompute which Intel functions are blocked by an exhausted «block» budget (cached for 60 s)."""
    global _budget_checked_at
    now = time.monotonic()
    if not force and now - _budget_checked_at < _BUDGET_TTL_S:
        return
    _budget_checked_at = now
    try:
        blocked = set()
        statuses = await budget_statuses()
        features = [f for f in FEATURES if not f.startswith("copilot_")] + ["other"]
        for s in statuses:
            if s["state"] != "exceeded" or s["action"] != "block":
                continue
            if s["scope"] == "feature":
                blocked.add(s["key"])
            elif s["scope"] == "total" or (s["scope"] == "app" and s["key"] == "intel"):
                blocked.update(features)
        _blocked_features.clear()
        _blocked_features.update(blocked)
    except Exception:  # noqa: BLE001 — never block calls because the check failed
        pass


# =================================================================== Prueba en sombra
# Una prueba: {"feature", "candidate_model", "sample_pct", "max_runs", "enabled"}. Sobre una muestra de las
# llamadas reales de esa función se repite la misma petición con el modelo candidato, EN SEGUNDO PLANO y
# sin afectar a la respuesta real, y se comparan los resultados. Solo se guardan métricas, nunca texto.
MIN_RUNS_FOR_VERDICT = 30
SHADOW_MAX_PARALLEL = 2
JSON_AGREEMENT_MIN = 0.90
TEXT_SIMILARITY_MIN = 0.75
_shadow_active = 0
_shadow_cache: Dict[str, Dict[str, Any]] = {}
_shadow_checked_at = 0.0


def _json_of(text: Any) -> Optional[Any]:
    import json
    t = text if isinstance(text, str) else getattr(text, "content", str(text or ""))
    try:
        i, j = t.index("{"), t.rindex("}") + 1
        return json.loads(t[i:j])
    except (ValueError, TypeError):
        return None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() == b.strip().lower()
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= 1e-6 * max(1.0, abs(a))
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def compare_outputs(current: Any, candidate: Any) -> Dict[str, Any]:
    """Deterministic comparison; no judge model. JSON answers: share of fields with the same value.
    Text answers: word overlap (Jaccard). Also whether each side is valid JSON when the other is."""
    cj, kj = _json_of(current), _json_of(candidate)
    if isinstance(cj, dict):
        if not isinstance(kj, dict):
            return {"mode": "json", "valid_candidate": False, "agreement": 0.0}
        keys = set(cj) | set(kj)
        equal = sum(1 for k in keys if k in cj and k in kj and _same(cj[k], kj[k]))
        return {"mode": "json", "valid_candidate": True, "agreement": round(equal / len(keys), 4) if keys else 1.0}
    ct = current if isinstance(current, str) else str(current or "")
    kt = candidate if isinstance(candidate, str) else str(candidate or "")
    cw, kw = set(re.findall(r"\w+", ct.lower())), set(re.findall(r"\w+", kt.lower()))
    jac = len(cw & kw) / len(cw | kw) if (cw | kw) else 1.0
    return {"mode": "text", "valid_candidate": bool(kt.strip()), "agreement": round(jac, 4)}


def verdict(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """equivalent / not_recommended / insufficient_data, from stored metrics only."""
    n = len(results)
    if n < MIN_RUNS_FOR_VERDICT:
        return {"state": "insufficient_data", "runs": n, "needed": MIN_RUNS_FOR_VERDICT}
    ok = [r for r in results if r.get("status") == "ok"]
    err_rate = 1 - len(ok) / n
    valid = sum(1 for r in ok if r.get("valid_candidate")) / n
    agree = sum(r.get("agreement", 0) for r in ok) / len(ok) if ok else 0.0
    mode = results[-1].get("mode", "json")
    floor = JSON_AGREEMENT_MIN if mode == "json" else TEXT_SIMILARITY_MIN
    good = err_rate <= 0.02 and valid >= 0.98 and agree >= floor
    return {"state": "equivalent" if good else "not_recommended", "runs": n, "agreement": round(agree, 4),
            "valid_rate": round(valid, 4), "error_rate": round(err_rate, 4), "floor": floor, "mode": mode}


def clean_shadow(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        feature, model = str(item["feature"]), str(item["candidate_model"])
        pct = float(item.get("sample_pct", 10))
        max_runs = int(item.get("max_runs", 200))
    except (KeyError, TypeError, ValueError):
        return None
    if feature not in FEATURES or feature.startswith("copilot_") or not re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", model):
        return None
    return {"feature": feature, "candidate_model": model, "sample_pct": min(100.0, max(1.0, pct)),
            "max_runs": min(2000, max(MIN_RUNS_FOR_VERDICT, max_runs)), "enabled": bool(item.get("enabled", True))}


async def get_shadow_tests() -> List[Dict[str, Any]]:
    doc = await _db().ai_usage_settings.find_one({"_id": "shadow"}) or {}
    return [t for t in (clean_shadow(i) for i in doc.get("items", [])) if t]


async def set_shadow_tests(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean = [t for t in (clean_shadow(i) for i in items[:20]) if t]
    await _db().ai_usage_settings.update_one({"_id": "shadow"}, {"$set": {"items": clean}}, upsert=True)
    await refresh_shadow(force=True)
    return clean


async def refresh_shadow(force: bool = False) -> None:
    global _shadow_checked_at
    now = time.monotonic()
    if not force and now - _shadow_checked_at < _BUDGET_TTL_S:
        return
    _shadow_checked_at = now
    try:
        _shadow_cache.clear()
        for t in await get_shadow_tests():
            if t["enabled"]:
                _shadow_cache[t["feature"]] = t
    except Exception:  # noqa: BLE001
        pass


async def shadow_report() -> List[Dict[str, Any]]:
    out = []
    for t in await get_shadow_tests():
        rows = [r async for r in _db().ai_shadow.find({"feature": t["feature"], "candidate_model": t["candidate_model"]},
                                                      {"_id": 0}).sort("at", -1).limit(t["max_runs"])]
        out.append({**t, "result": verdict(list(reversed(rows)))})
    return out


def _maybe_shadow(chat: Any, message: Any, response: Any, feature: str) -> None:
    """Called after a real answer is in hand. Schedules the candidate run in the background; never raises."""
    global _shadow_active
    try:
        test = _shadow_cache.get(feature)
        if not test or _shadow_active >= SHADOW_MAX_PARALLEL:
            return
        import random
        if random.random() * 100 >= test["sample_pct"]:
            return
        loop = _main_loop
        if loop is None or loop.is_closed():
            return
        _shadow_active += 1
        data = {"api_key": getattr(chat, "api_key", None), "system": getattr(chat, "system_message", ""),
                "session": f"shadow-{getattr(chat, 'session_id', '')}", "text": getattr(message, "text", message),
                "current_model": getattr(chat, "model", None), "current_provider": getattr(chat, "provider", None),
                "response": response}

        def worker():
            global _shadow_active
            started = time.monotonic()
            status, cand = "ok", ""
            try:
                from emergentintegrations.llm.chat import LlmChat, UserMessage

                async def inner():
                    c = LlmChat(api_key=data["api_key"], session_id=data["session"], system_message=data["system"])
                    provider = (DEFAULT_PRICES.get(test["candidate_model"]) or {}).get("provider") or data["current_provider"]
                    c.with_model(provider, test["candidate_model"])
                    return await c.send_message(UserMessage(text=data["text"]))
                cand = asyncio.run(inner())
            except Exception as exc:  # noqa: BLE001
                status = type(exc).__name__
            finally:
                _shadow_active = max(0, _shadow_active - 1)
            cmp = compare_outputs(data["response"], cand) if status == "ok" else {"mode": "json", "valid_candidate": False, "agreement": 0.0}
            ev = {"at": datetime.now(timezone.utc), "feature": feature, "current_model": data["current_model"],
                  "candidate_model": test["candidate_model"], "status": status,
                  "duration_ms": int((time.monotonic() - started) * 1000),
                  "in_tokens": estimate_tokens(data["system"]) + estimate_tokens(data["text"]),
                  "out_tokens": estimate_tokens(cand), **cmp}
            asyncio.run_coroutine_threadsafe(_store_shadow(ev), loop)

        loop.run_in_executor(None, worker)
    except Exception:  # noqa: BLE001
        pass


async def _store_shadow(ev: Dict[str, Any]) -> None:
    try:
        await _db().ai_shadow.insert_one(dict(ev))
        # the candidate run is real spend: it shows as its own app so it never hides in the normal figures
        await record(app="intel-shadow", feature=ev["feature"], model=ev["candidate_model"], in_tokens=ev["in_tokens"],
                     out_tokens=ev["out_tokens"], duration_ms=ev["duration_ms"], status=ev["status"])
        test = _shadow_cache.get(ev["feature"])
        if test:
            n = await _db().ai_shadow.count_documents({"feature": ev["feature"], "candidate_model": ev["candidate_model"]})
            if n >= test["max_runs"]:  # enough: stop spending
                items = [t for t in await get_shadow_tests() if not (t["feature"] == ev["feature"] and t["candidate_model"] == ev["candidate_model"])]
                items += [{**test, "enabled": False}]
                await set_shadow_tests(items)
    except Exception:  # noqa: BLE001
        pass
