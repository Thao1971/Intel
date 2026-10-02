"""Consumo de IA: funciones puras (tarifas, funciones por sesión, recomendaciones)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import ai_usage as au  # noqa: E402

P = au.DEFAULT_PRICES


def test_feature_is_inferred_from_the_session_prefix():
    assert au.feature_for_session("classify-tx-1234") == "transactions_classify"
    assert au.feature_for_session("classify-abc") == "company_classify"
    assert au.feature_for_session("translate-9") == "editorial_translate"
    assert au.feature_for_session("docstudio_ab12") == "docstudio"
    assert au.feature_for_session("0f8c-uuid", "other") == "other"


def test_cost_uses_public_prices_and_never_invents_one():
    assert round(au.cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000, P), 4) == 18.0
    assert round(au.cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000, P), 4) == 6.0
    assert au.cost_usd("modelo-desconocido", 10, 10, P) is None


def test_a_mechanical_function_on_a_large_model_gets_a_low_risk_cheaper_suggestion():
    r = au.recommend("editorial_classify", "gpt-5.2", 2_000_000, 200_000, 500, 0.0, P)
    assert r and r["suggested_model"] in ("gpt-5-nano", "gpt-5-mini")  # same provider as the current model
    assert r["monthly_saving_usd"] > 0 and r["risk"] in ("low", "medium")
    assert r["needs"] == "small"


def test_a_function_that_needs_medium_is_never_sent_below_medium():
    r = au.recommend("doc_generate", "gpt-5.2", 1_000_000, 100_000, 100, 0.0, P)
    assert r and P[r["suggested_model"]]["tier"] in ("medium", "large")


def test_a_failing_function_is_not_told_to_downgrade_lightly():
    r = au.recommend("editorial_classify", "gpt-5.2", 2_000_000, 200_000, 500, 0.2, P)
    assert r and r["risk"] == "high"


def test_nothing_is_suggested_when_already_the_cheapest_or_unpriced():
    assert au.recommend("editorial_classify", "gpt-5-nano", 1_000_000, 100_000, 10, 0.0, P) is None
    assert au.recommend("editorial_classify", "otro-modelo", 1_000_000, 100_000, 10, 0.0, P) is None
    assert au.recommend("editorial_classify", "gpt-5.2", 0, 0, 0, 0.0, P) is None


def test_tokens_are_estimated_from_length():
    assert au.estimate_tokens("a" * 36) == 10
    assert au.estimate_tokens(None) == 0


def test_suggestions_stay_with_the_same_provider():
    r = au.recommend("copilot_draft", "claude-sonnet-4-6", 50_000_000, 3_000_000, 1000, 0.0, P)
    assert r is None or P[r["suggested_model"]]["provider"] == "anthropic"
    r2 = au.recommend("copilot_structure", "claude-sonnet-4-6", 5_000_000, 300_000, 1000, 0.0, P)
    assert r2 and r2["suggested_model"].startswith("claude-haiku")


# ---------------------------------------------------------------- budgets
def test_budget_items_are_validated():
    ok = au.clean_budget({"scope": "feature", "key": "docstudio", "period": "day", "limit_usd": "5", "action": "block"})
    assert ok == {"scope": "feature", "key": "docstudio", "period": "day", "limit_usd": 5.0, "action": "block", "enabled": True}
    assert au.clean_budget({"scope": "total", "key": "x", "period": "month", "limit_usd": 100})["key"] == ""
    assert au.clean_budget({"scope": "total", "period": "month", "limit_usd": 100})["action"] == "alert"  # alert by default
    for bad in ({"scope": "feature", "period": "day", "limit_usd": 5}, {"scope": "nope", "period": "day", "limit_usd": 5},
                {"scope": "total", "period": "week", "limit_usd": 5}, {"scope": "total", "period": "day", "limit_usd": 0},
                {"scope": "total", "period": "day", "limit_usd": "x"}):
        assert au.clean_budget(bad) is None


def test_budget_state_warns_at_80_and_exceeds_at_100():
    assert au.budget_state(7.9, 10) == "ok" and au.budget_state(8, 10) == "warning" and au.budget_state(10, 10) == "exceeded"


def test_spend_counts_only_the_period_and_the_scope():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    rows = [
        {"at": now, "kind": "llm_call", "app": "intel", "feature": "docstudio", "model": "claude-sonnet-4-6", "in_tokens": 1_000_000, "out_tokens": 0},
        {"at": now - timedelta(days=3), "kind": "llm_call", "app": "intel", "feature": "docstudio", "model": "claude-sonnet-4-6", "in_tokens": 1_000_000, "out_tokens": 0},
        {"at": now, "kind": "llm_call", "app": "beta-copilot", "feature": "copilot_draft", "model": "claude-sonnet-4-6", "in_tokens": 1_000_000, "out_tokens": 0},
        {"at": now, "kind": "llm_skipped", "app": "beta-copilot", "feature": "copilot_skipped", "model": None, "in_tokens": 0, "out_tokens": 0},
    ]
    day, month = au.period_start("day", now), au.period_start("month", now)
    assert day.day == 15 and month.day == 1
    assert round(au.spend_of(rows, "feature", "docstudio", day, P), 2) == 3.0
    assert round(au.spend_of(rows, "feature", "docstudio", month, P), 2) == 6.0
    assert round(au.spend_of(rows, "app", "beta-copilot", month, P), 2) == 3.0
    assert round(au.spend_of(rows, "total", "", day, P), 2) == 6.0


# ---------------------------------------------------------------- shadow test
def test_json_outputs_are_compared_field_by_field():
    cur = '{"type": "Acquisition", "confidence": 0.9, "tags": ["a", "b"]}'
    assert au.compare_outputs(cur, '```json\n{"type": "acquisition", "confidence": 0.9, "tags": ["a", "b"]}\n```')["agreement"] == 1.0
    r = au.compare_outputs(cur, '{"type": "launch", "confidence": 0.9, "tags": ["a", "b"]}')
    assert r["mode"] == "json" and r["valid_candidate"] and round(r["agreement"], 2) == 0.67
    assert au.compare_outputs(cur, "no json here") == {"mode": "json", "valid_candidate": False, "agreement": 0.0}


def test_text_outputs_use_word_overlap():
    assert au.compare_outputs("El gobierno aprueba la ley", "El gobierno aprueba la ley")["agreement"] == 1.0
    r = au.compare_outputs("El gobierno aprueba la ley", "Una receta de cocina")
    assert r["mode"] == "text" and r["agreement"] < 0.2
    assert au.compare_outputs("hola", "")["valid_candidate"] is False


def _runs(n, **kw):
    return [{"status": "ok", "valid_candidate": True, "agreement": 0.97, "mode": "json", **kw} for _ in range(n)]


def test_verdict_needs_enough_runs_and_clear_agreement():
    assert au.verdict(_runs(10))["state"] == "insufficient_data"
    assert au.verdict(_runs(40))["state"] == "equivalent"
    assert au.verdict(_runs(40, agreement=0.7))["state"] == "not_recommended"
    assert au.verdict(_runs(40, valid_candidate=False))["state"] == "not_recommended"
    errs = _runs(30) + [{"status": "TimeoutError", "agreement": 0.0, "mode": "json"}] * 5
    assert au.verdict(errs)["state"] == "not_recommended"
    assert au.verdict(_runs(40, mode="text", agreement=0.8))["state"] == "equivalent"


def test_shadow_tests_are_validated_and_never_target_the_copilot():
    ok = au.clean_shadow({"feature": "editorial_classify", "candidate_model": "gpt-5-mini", "sample_pct": 500, "max_runs": 5})
    assert ok["sample_pct"] == 100.0 and ok["max_runs"] == au.MIN_RUNS_FOR_VERDICT and ok["enabled"] is True
    assert au.clean_shadow({"feature": "copilot_draft", "candidate_model": "gpt-5-mini"}) is None
    assert au.clean_shadow({"feature": "nope", "candidate_model": "gpt-5-mini"}) is None
    assert au.clean_shadow({"feature": "docstudio", "candidate_model": "bad model!"}) is None


def test_an_exhausted_block_budget_stops_the_call_but_never_other_functions():
    import asyncio
    asyncio.run(_check_block())


async def _check_block():
    import sys, types
    from mongomock_motor import AsyncMongoMockClient
    fake = types.ModuleType("database")
    fake.db = AsyncMongoMockClient()["t"]
    sys.modules["database"] = fake
    await au.set_budgets([{"scope": "feature", "key": "docstudio", "period": "day", "limit_usd": 1, "action": "block"},
                          {"scope": "feature", "key": "editorial_translate", "period": "day", "limit_usd": 1, "action": "alert"}])
    await au.record(app="intel", feature="docstudio", model="claude-sonnet-4-6", in_tokens=1_000_000, out_tokens=0)
    await au.record(app="intel", feature="editorial_translate", model="claude-sonnet-4-6", in_tokens=1_000_000, out_tokens=0)
    await au.refresh_blocked(force=True)
    assert "docstudio" in au._blocked_features and "editorial_translate" not in au._blocked_features
    states = {b["key"]: b["state"] for b in await au.budget_statuses()}
    assert states == {"docstudio": "exceeded", "editorial_translate": "exceeded"}
    await au.set_budgets([])
    assert not au._blocked_features


def test_the_wrapper_meters_every_call_blocks_when_told_and_runs_the_shadow_test():
    import asyncio
    asyncio.run(_check_wrapper())


async def _check_wrapper():
    import asyncio
    import sys, types
    from mongomock_motor import AsyncMongoMockClient
    fake_db = types.ModuleType("database")
    fake_db.db = AsyncMongoMockClient()["w"]
    sys.modules["database"] = fake_db

    class UserMessage:
        def __init__(self, text): self.text = text

    class LlmChat:
        def __init__(self, api_key=None, session_id="", system_message=""):
            self.api_key, self.session_id, self.system_message = api_key, session_id, system_message
            self.provider = self.model = None

        def with_model(self, provider, model):
            self.provider, self.model = provider, model
            return self

        async def send_message(self, message):
            return '{"type": "launch", "confidence": 0.9}'

    mod = types.ModuleType("emergentintegrations.llm.chat")
    mod.LlmChat, mod.UserMessage = LlmChat, UserMessage
    for name in ("emergentintegrations", "emergentintegrations.llm"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["emergentintegrations.llm.chat"] = mod
    au._installed = False
    assert au.install()

    chat = LlmChat(api_key="k", session_id="editorial-1", system_message="Editorial classifier. JSON only.").with_model("openai", "gpt-5.2")
    assert await chat.send_message(UserMessage("titular")) == '{"type": "launch", "confidence": 0.9}'
    await asyncio.sleep(0.05)
    rows = [r async for r in fake_db.db.ai_usage.find({}, {"_id": 0})]
    assert len(rows) == 1 and rows[0]["feature"] == "editorial_classify" and rows[0]["model"] == "gpt-5.2" and rows[0]["app"] == "intel"
    assert "titular" not in str(rows[0])  # never the text

    # shadow: every call (100 %), the candidate runs in the background and only metrics are stored
    await au.set_shadow_tests([{"feature": "editorial_classify", "candidate_model": "gpt-5-mini", "sample_pct": 100, "max_runs": 30}])
    await chat.send_message(UserMessage("otro titular"))
    for _ in range(40):
        await asyncio.sleep(0.05)
        if await fake_db.db.ai_shadow.count_documents({}):
            break
    shadow = [r async for r in fake_db.db.ai_shadow.find({}, {"_id": 0})]
    assert len(shadow) == 1 and shadow[0]["candidate_model"] == "gpt-5-mini" and shadow[0]["agreement"] == 1.0
    assert "titular" not in str(shadow[0])
    await au.set_shadow_tests([])

    # block: an exhausted «block» budget stops the call before the model is reached
    await au.set_budgets([{"scope": "feature", "key": "editorial_classify", "period": "day", "limit_usd": 0.01, "action": "block"}])
    await au.record(app="intel", feature="editorial_classify", model="gpt-5.2", in_tokens=5_000_000, out_tokens=0)
    await au.refresh_blocked(force=True)
    with __import__("pytest").raises(au.AIBudgetExceeded):
        await chat.send_message(UserMessage("bloqueado"))
    await au.set_budgets([])
    assert await chat.send_message(UserMessage("libre"))
