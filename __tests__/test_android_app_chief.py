"""Inside the Android app, Chief never sells our plans or add-ons (android_app.py).

Kevin, 2026-11-19 ("build it that way"): Google Play doesn't let an Android
app sell its own plans or add-ons outside Play billing, or push people to buy
them elsewhere. Inside the app Chief never brings up upgrading, buying,
credits, storage, logins or adding a card, and never links to them; it may
say which plan includes something; asked how to change the plan, the owner
hears where, in plain words with no link, and anyone else hears to ask the
owner. Outside the app Chief is exactly as before.

Pins:
  * the middleware: the flag comes from the user agent, is cleared when the
    request ends, never leaks into the next request or a concurrent one, and
    is seen by a streamed body and a task the route starts
  * the main turn: the rules sit at the END of the prompt (the uncached turn
    tail) only in the app; the three cached segments are byte-identical with
    and without them, as sent to the model
  * owner vs not: the owner gets the plain-words directions; anyone else is
    told the owner, by name, manages the plan
  * every other lane that writes Chief's words: the after-actions rewrite,
    the first track's opening and fast answer (and its answer cache), the
    headline, the voice preview, the backup brain, and the sample church's
    own Chief; and the server-written "Upgrade" / "add a card" lines Chief
    passes on (the texting number, the no-card trial, the message cap)
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import pathlib
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import android_app  # noqa: E402

UA_APP = ("Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP2A; wv) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Version/4.0 Chrome/131.0 Mobile Safari/537.36 SolutionistAndroid/1")
UA_WEB = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/131.0 Mobile Safari/537.36")

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
STAFF = "00000000-0000-4000-8000-000000000002"
CHURCH = {"id": BIZ, "owner_id": OWNER, "name": "Love City Church", "type": "ministry",
          "voice_profile": {}, "settings": {"practitioner_name": "Pastor Kevin"}}


@pytest.fixture(autouse=True)
def _switch_default(monkeypatch):
    monkeypatch.delenv(android_app.ENV, raising=False)


class in_app:
    """Serve the block as if from the Android app (what the middleware does)."""

    def __enter__(self):
        self.token = android_app.set_in_app(True)

    def __exit__(self, *exc):
        android_app.reset(self.token)


# ─── The middleware ───────────────────────────────────────────────────

def _probe_app():
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()

    @app.get("/probe")
    async def probe():
        seen_in_task = await asyncio.create_task(_ask_later())
        return {"in_app": android_app.in_android_app(), "in_task": seen_in_task}

    @app.get("/stream")
    async def stream():
        async def body():
            yield json.dumps({"in_app": android_app.in_android_app()})
        return StreamingResponse(body(), media_type="application/json")

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(0.05)
        return {"in_app": android_app.in_android_app()}

    app.add_middleware(android_app.AndroidAppMarker)
    return app


async def _ask_later():
    await asyncio.sleep(0)
    return android_app.in_android_app()


def test_the_user_agent_mark():
    assert android_app.is_app_user_agent(UA_APP)
    assert android_app.is_app_user_agent("SolutionistAndroid/2")
    for ua in (UA_WEB, "", None, "Solutionist", "solutionistandroid/1"):
        assert not android_app.is_app_user_agent(ua), ua


def test_the_middleware_sets_the_flag_from_the_user_agent_and_clears_it():
    from fastapi.testclient import TestClient
    client = TestClient(_probe_app())
    assert client.get("/probe", headers={"User-Agent": UA_APP}).json() == {"in_app": True, "in_task": True}
    # The next request (a browser) starts clean: nothing carried over.
    assert client.get("/probe", headers={"User-Agent": UA_WEB}).json() == {"in_app": False, "in_task": False}
    assert client.get("/probe", headers={"User-Agent": UA_APP}).json()["in_app"] is True
    assert client.get("/probe").json()["in_app"] is False
    # A streamed body (how Chief's stream answers) sees it too.
    assert client.get("/stream", headers={"User-Agent": UA_APP}).json() == {"in_app": True}
    assert client.get("/stream", headers={"User-Agent": UA_WEB}).json() == {"in_app": False}
    # And whoever called is left as they were.
    assert android_app.in_android_app() is False


def test_concurrent_requests_each_see_their_own():
    import httpx

    async def go():
        transport = httpx.ASGITransport(app=_probe_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            uas = [UA_APP, UA_WEB] * 4
            rs = await asyncio.gather(*(c.get("/slow", headers={"User-Agent": ua}) for ua in uas))
            return [(ua, r.json()["in_app"]) for ua, r in zip(uas, rs)]
    for ua, seen in asyncio.run(go()):
        assert seen is (ua == UA_APP)


def test_the_middleware_is_pure_asgi_and_registered():
    from starlette.middleware.base import BaseHTTPMiddleware
    assert not issubclass(android_app.AndroidAppMarker, BaseHTTPMiddleware)
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "from android_app import AndroidAppMarker" in src
    assert "app.add_middleware(AndroidAppMarker)" in src


def test_the_switch_turns_it_all_off(monkeypatch):
    monkeypatch.setenv(android_app.ENV, "off")
    with in_app():
        assert android_app.in_android_app() is False
        assert android_app.chief_block(is_owner=True) == ""
        assert android_app.wording("web", "app") == "web"


def test_outside_the_app_every_piece_is_empty():
    assert android_app.in_android_app() is False
    assert android_app.chief_block(is_owner=True, owner_name="Pastor Kevin") == ""
    assert android_app.rewrite_rule() == android_app.opener_rule() == ""
    assert android_app.defer_rule("NEED_MORE") == ""
    assert android_app.wording("web", "app") == "web"
    assert android_app.into_turn_tail("PROMPT", "") == "PROMPT"


# ─── What Chief is told ───────────────────────────────────────────────

def test_the_owner_hears_where_plans_change_in_plain_words():
    with in_app():
        text = android_app.chief_block(is_owner=True, owner_name="Pastor Kevin")
    assert text.startswith(android_app.HEADING)
    assert ("Plans are changed in Settings → Billing and plan. "
            "Sign in at mysolutionist.app in a browser to do it.") in text
    assert "never as a markdown link" in text and "https:// or www" in text
    assert "Never bring up upgrading" in text and "adding a card" in text
    assert "no action that starts a checkout" in text
    assert "That's part of the Growing plan. Your church is on Small right now." in text
    assert "giving, invoices" in text, "the church's own money keeps working"
    assert "](https://" not in text.replace("[words](https://…)", ""), "the block itself links nothing"


def test_anyone_else_is_told_to_ask_the_owner_by_name():
    with in_app():
        named = android_app.chief_block(is_owner=False, owner_name="Pastor  Kevin")
        nameless = android_app.chief_block(is_owner=False, owner_name="")
    assert "managed by Pastor Kevin, the account owner, and suggest they ask Pastor Kevin" in named
    assert "managed by the account owner, and suggest they ask the account owner" in nameless
    for text in (named, nameless):
        assert android_app.OWNER_ANSWER not in text and "mysolutionist.app" not in text
        assert "Don't tell them where plans are changed" in text


# ─── The main turn: the tail only, the cache untouched ────────────────

class _EmptyCtx(dict):
    def __missing__(self, key):
        return []


def _prompt():
    import chief_of_staff as cos
    return cos._build_system_prompt(_EmptyCtx(business=CHURCH), False, time_of_day="morning")


def test_the_rules_go_only_into_the_turn_tail_and_the_cached_segments_hold_still():
    import chief_of_staff as cos
    import chief_lean_brief
    base = _prompt()
    assert "[[CHIEF_TURN_SPLIT]]" in base and "[[CHIEF_GLOBAL_SPLIT]]" in base
    # Outside the app: the very same prompt.
    assert cos._with_android_app_rules(base, CHURCH, OWNER) == base
    with in_app():
        owner = cos._with_android_app_rules(base, CHURCH, OWNER)
        staff = cos._with_android_app_rules(base, CHURCH, STAFF)
    before = chief_lean_brief.segments(base)
    for p in (owner, staff):
        after = chief_lean_brief.segments(p)
        for cached in ("universal", "per_business", "state"):
            assert after[cached] == before[cached], f"the {cached} segment moved"
            assert android_app.HEADING not in after[cached]
        assert android_app.HEADING in after["tail"] and android_app.HEADING not in before["tail"]
        assert p.startswith(base.rstrip()), "nothing above the rules changed"
    assert android_app.OWNER_ANSWER in owner and android_app.OWNER_ANSWER not in staff
    assert "managed by Pastor Kevin, the account owner" in staff
    # No owner on the row reads as "not the owner": nobody is told where to pay.
    with in_app():
        unknown = cos._with_android_app_rules(base, {**CHURCH, "owner_id": None}, OWNER)
    assert android_app.OWNER_ANSWER not in unknown


def test_a_prompt_without_cache_markers_gets_them_at_its_end():
    """The coaching personas carry no markers: the whole prompt is uncached."""
    with in_app():
        out = android_app.into_turn_tail("COACH PROMPT", android_app.chief_block(is_owner=True))
    assert out.startswith("COACH PROMPT\n\n" + android_app.HEADING)


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"stop_reason": "end_turn", "usage": {}, "content": [{"type": "text", "text": "ok"}]}


def _sent_system(monkeypatch, system):
    import chief_of_staff as cos
    import llm_call
    sent = {}

    async def apost(client, payload, **kw):
        sent.update(json.loads(json.dumps(payload)))
        return _Resp()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "k")
    monkeypatch.setattr(cos, "log_api_usage", AsyncMock())
    asyncio.run(cos._call_claude(None, system, [{"role": "user", "content": "hi"}]))
    return sent["system"]


def test_as_sent_to_the_model_the_cached_blocks_are_byte_identical(monkeypatch):
    import chief_of_staff as cos
    base = _prompt()
    web = _sent_system(monkeypatch, cos._with_android_app_rules(base, CHURCH, OWNER))
    with in_app():
        app_prompt = cos._with_android_app_rules(base, CHURCH, OWNER)
    app = _sent_system(monkeypatch, app_prompt)
    assert len(web) == len(app) == 4, "the four-segment shape"
    cached = [i for i, b in enumerate(app) if "cache_control" in b]
    assert cached == [0, 1, 2]
    for i in cached:
        assert app[i] == web[i], f"cached block {i} differs"
        assert android_app.HEADING not in app[i]["text"]
    assert "cache_control" not in app[3]
    assert android_app.HEADING in app[3]["text"] and android_app.HEADING not in web[3]["text"]


def test_the_chat_turn_adds_them_after_the_prompt_is_built():
    import chief_of_staff as cos
    src = inspect.getsource(cos.chief_chat)
    built = src.index("system = _build_system_prompt(")
    added = src.index("system = _with_android_app_rules(system, biz, str(user_session.user.id))")
    assert added > built
    # The stream endpoint runs the same turn (its own prompt build would need its own line).
    assert "chief_chat(req, user_session)" in inspect.getsource(cos.chief_chat_stream)


# ─── The other lanes that write Chief's words ─────────────────────────

def test_the_rewrite_after_actions_keeps_the_rule(monkeypatch):
    import chief_of_staff as cos
    seen = []

    async def fake_call(client, system, messages, **kw):
        seen.append(system)
        return "Rewritten."
    monkeypatch.setattr(cos, "_call_claude", fake_call)
    taken = [{"type": "add_note", "result": "saved", "label": "Note saved"}]

    def run():
        return asyncio.run(cos._compose_post_action_reply(None, "add a note", "Saving it.", taken))
    run()
    with in_app():
        run()
    assert len(seen) == 2
    assert seen[0] == cos._POST_ACTION_REPLY_SYSTEM
    assert seen[1].startswith(cos._POST_ACTION_REPLY_SYSTEM) and "INSIDE THE ANDROID APP" in seen[1]
    assert "Leave out anything that tells them to upgrade" in seen[1]


def test_the_backup_brain_carries_the_rules_past_its_cut():
    import fallback_brain
    base = ("UNIVERSAL [[CHIEF_GLOBAL_SPLIT]] HOW WE SOUND [[CHIEF_CACHE_SPLIT]]"
            + "STATE " * 4000 + "[[CHIEF_TURN_SPLIT]] THIS TURN")
    assert android_app.HEADING not in fallback_brain._fallback_system(base)
    with in_app():
        block = android_app.chief_block(is_owner=True)
    out = fallback_brain._fallback_system(android_app.into_turn_tail(base, block))
    assert out.count(android_app.HEADING) == 1 and block.strip() in out
    short = android_app.into_turn_tail("A [[CHIEF_CACHE_SPLIT]] B [[CHIEF_TURN_SPLIT]] C", block)
    assert fallback_brain._fallback_system(short).count(android_app.HEADING) == 1


SESSION = SimpleNamespace(user=SimpleNamespace(id="22222222-2222-2222-2222-222222222222"), token="jwt")


@pytest.fixture
def _router(monkeypatch):
    import chief_fast_track as cft
    import chief_of_staff as cos
    import model_router as mr
    import route_ledger
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ROUTER_LOG_DB", "off")
    monkeypatch.setenv("ROUTER_KEEP_WARM", "off")
    monkeypatch.setenv("ROUTER_TTFT_BUDGET_MS", "500")
    monkeypatch.setattr(cft, "_fast_guards", lambda u, b: True)
    monkeypatch.setattr(route_ledger, "_page_owner", lambda alert: None)
    cft._KNOWN_GOOD.clear()
    cft._CONVO.clear()
    cft.CACHE = mr.SemanticCache()
    original = cos.chief_chat
    yield cft
    cos.chief_chat = original


def _two_track(cft, monkeypatch, message, reply):
    import chief_of_staff as cos
    calls = []

    async def stream_text(system, messages, *, model, max_tokens, rec, endpoint, units,
                          business_id, out, stop_sequences=None):
        calls.append({"system": system, "endpoint": endpoint})
        await asyncio.sleep(0.01)
        yield reply
        out["stop_reason"] = "end_turn"
    monkeypatch.setattr(cft, "stream_text", stream_text)

    async def fake_chat(r, session):
        await asyncio.sleep(0.05)
        return {"response": "The full answer.", "actions_taken": []}
    cos.chief_chat = fake_chat

    async def go():
        resp = await cos.chief_chat_stream(cos.ChatRequest(business_id=BIZ, message=message), SESSION)
        async for _ in resp.body_iterator:
            pass
    asyncio.run(go())
    return calls


def test_the_fast_answer_sends_plans_to_the_full_turn_in_the_app(_router, monkeypatch):
    cft = _router
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    web = _two_track(cft, monkeypatch, "What does ROI mean?", "ROI compares gain with cost.")
    cft._CONVO.clear()
    with in_app():
        app = _two_track(cft, monkeypatch, "What does ROI mean?", "ROI compares gain with cost.")
    fast_web = [c for c in web if c["endpoint"] == "/chief/backend"]
    fast_app = [c for c in app if c["endpoint"] == "/chief/backend"]
    assert fast_web and fast_app
    assert "Android app" not in fast_web[0]["system"]
    assert "If the message is about plans, prices" in fast_app[0]["system"]
    assert fast_app[0]["system"].rstrip().endswith("reply exactly NEED_RECORDS and nothing else.")


def test_the_opening_never_mentions_plans_in_the_app(_router, monkeypatch):
    cft = _router
    web = _two_track(cft, monkeypatch, "Did Maria pay?", "Let me check Maria's invoices.")
    with in_app():
        app = _two_track(cft, monkeypatch, "Did Maria pay?", "Let me check Maria's invoices.")
    op_web = [c for c in web if c["endpoint"] == "/chief/opener"]
    op_app = [c for c in app if c["endpoint"] == "/chief/opener"]
    assert op_web and op_app
    assert "Android app" not in op_web[0]["system"]
    assert "never mention upgrading, plans, prices" in op_app[0]["system"]


def test_an_answer_cached_in_a_browser_is_never_replayed_in_the_app(_router):
    cft = _router
    import chief_of_staff as cos
    cft.note_full_turn_ok(SESSION.user.id, BIZ)
    req = cos.ChatRequest(business_id=BIZ, message="What does ROI mean?")
    web = cft.plan(req, SESSION)
    cft.CACHE.put(web.cache_scope, req.message, "ROI compares gain with cost.")
    assert cft.plan(req, SESSION).cache_hit is not None, "the browser's cache still works"
    with in_app():
        app = cft.plan(req, SESSION)
    assert app.cache_scope != web.cache_scope and app.cache_hit is None


def test_the_headline_and_voice_preview_defer_plans_in_the_app():
    for mod in ("chief_headline", "chief_voice_bridge"):
        src = (ROOT / f"{mod}.py").read_text(encoding="utf-8")
        assert 'android_app.defer_rule("NEED_MORE")' in src, mod
    with in_app():
        line = android_app.defer_rule("NEED_MORE")
    assert line.rstrip().endswith("reply exactly NEED_MORE and nothing else.")
    assert line.lstrip().upper().startswith("THIS PERSON")


# ─── The sample church's Chief ────────────────────────────────────────

def test_the_sample_chief_never_points_to_a_plan_in_the_app():
    import sample_chief as sch
    web = sch.build_payload(model="m", digest="D", question="q", history=[], visitor="Pastor Kevin")
    with in_app():
        app = sch.build_payload(model="m", digest="D", question="q", history=[], visitor="Pastor Kevin")
        capped, back = sch.capped_line(10), sch.welcome_line(0, 10)
    # The cached head (the rules, then the digest on the one breakpoint) is the same bytes.
    assert app["system"][:2] == web["system"][:2]
    assert "cache_control" in app["system"][1] and "cache_control" not in app["system"][2]
    assert sch.APP_RULES in app["system"][2]["text"] and sch.APP_RULES not in web["system"][2]["text"]
    assert "Start your own church" in sch.APP_RULES and "never as a link" in sch.APP_RULES
    assert "Settings → Billing and plan" in sch.APP_RULES
    # A tail that was empty in a browser exists in the app.
    bare = sch.build_payload(model="m", digest="D", question="q", history=[])
    assert len(bare["system"]) == 2
    with in_app():
        assert sch.build_payload(model="m", digest="D", question="q", history=[])["system"][2]["text"] == sch.APP_RULES
    # The server's own lines drop "once you choose a plan".
    assert "plan" in sch.capped_line(10) and "plan" in sch.welcome_line(0, 10)
    assert "plan" not in capped and "plan" not in back
    assert capped == "That's all 10 of your questions in the sample church."
    assert back == "Welcome back to Grace Street Fellowship. You've asked your 10 questions here."


# ─── Server-written lines Chief passes on ─────────────────────────────

def test_the_texting_number_refusal_says_which_plan_not_upgrade(monkeypatch):
    import chief_sms_actions as csa
    import sms_numbers_router
    from fastapi import HTTPException

    async def locked(http, business_id, **kw):
        raise HTTPException(402, {"error": "feature_locked", "required_plan": "practice"})
    monkeypatch.setattr(sms_numbers_router, "provision_core", locked)

    def refuse():
        out = asyncio.run(csa.handle_provision_sms_number(None, {"id": BIZ}, {"area_code": "216"}))
        assert out.get("failed") and out.get("label") is not None
        return out["result"]
    web = refuse()
    with in_app():
        app = refuse()
    assert web.endswith("Upgrade and I'll set it up in a moment.")
    assert "comes with the" in app and "pgrade" not in app
    assert web.startswith(app)


def test_the_no_card_refusal_never_says_add_a_card_in_the_app():
    import no_card_trial as nct
    web = nct.card_message("texts", None)
    assert "add a card" in web.lower() and "Settings → Billing" in web
    with in_app():
        app = [nct.card_message(w, None) for w in (*nct._WHAT, "something new")]
        sample = nct.card_message("texts", {"is_sample": True})
    for line in app:
        assert "card" not in line.lower() and "Billing" not in line and "plan" not in line, line
    assert app[0] == "Texting isn't on for this account yet."
    import sample_church
    assert sample == sample_church.MESSAGE, "a sample row keeps its own words"
    src = inspect.getsource(__import__("chief_of_staff")._execute_actions)
    assert 'android_app.wording("Waits for a card", "Not on yet")' in src


def test_the_message_cap_lines_drop_upgrade_in_the_app(monkeypatch):
    import chief_llm
    monkeypatch.setattr(chief_llm, "llm_enabled", lambda: True)
    monkeypatch.setattr(chief_llm, "llm_capped", lambda biz: True)

    def ask():
        return asyncio.run(chief_llm.ask_transaction(BIZ, "ministry", "tx1", "what is this?"))["answer"]
    assert "Upgrade for unlimited Chief" in ask()
    with in_app():
        said = ask()
    assert "pgrade" not in said and said.endswith("I'll see you on the 1st.")
    src = (ROOT / "ai_proxy.py").read_text(encoding="utf-8")
    assert 'android_app.wording(\n                                used_up + " Upgrade for unlimited Chief.", used_up)' in src
