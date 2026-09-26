"""The 47-second voice turn of 2026-09-25.

[Chief timing] total=47241ms ... model=7265 actions=33038 review=2269: the
first draft read as a completed action with no tag, so the turn retried —
at the model's default effort and with the tool list unpinned. Effort is
part of the prompt-cache key, so the retry re-wrote the 111k-token prompt
from cold (chief cache: read=0 write=111105) and thought at full depth
through four tool rounds, then answered "I couldn't start that operation".
78 cents. And the first track waited 898ms behind synchronous database
gates at the top of the turn.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos


def test_the_retry_rides_the_turns_own_effort_and_tools(monkeypatch):
    seen = {}

    async def fake_call(client, system, messages, **kw):
        seen.update(kw)
        return "[ACTION:{\"type\":\"create_task\",\"title\":\"x\"}] Done."
    monkeypatch.setattr(cos, "_call_claude", fake_call)
    asyncio.run(cos._retry_missing_actions(
        None, "system", [{"role": "user", "content": "hi"}], "add a task", 1400, "claude-sonnet-5",
        effort="low", enable_web_search=False, stable_tools=True))
    assert seen["effort"] == "low"
    assert seen["stable_tools"] is True and seen["enable_web_search"] is False


def test_the_turn_passes_its_settings_to_the_retry():
    src = inspect.getsource(cos.chief_chat)
    call = src[src.index("await _retry_missing_actions("):][:600]
    assert "effort=chief_models.effort_for(lane)" in call
    assert "stable_tools=True" in call
    assert "enable_web_search=_web_search_allowed(" in call


def test_the_post_action_rewrite_thinks_briefly(monkeypatch):
    seen = {}

    async def fake_call(client, system, messages, **kw):
        seen.update(kw)
        return "The invoice went out."
    monkeypatch.setattr(cos, "_call_claude", fake_call)
    asyncio.run(cos._compose_post_action_reply(
        None, original_message="send it", first_pass_clean="Sending now.",
        taken=[{"type": "send_invoice", "result": "sent", "label": "Sent"}], business_id=None))
    assert seen.get("effort") == "low"


def test_the_database_gates_run_off_the_event_loop():
    src = inspect.getsource(cos.chief_chat)
    assert "await asyncio.to_thread(rate_limit.allow," in src
    assert "await asyncio.to_thread(billing_limits.require_chat_fair_use," in src
    assert "await asyncio.to_thread(billing_limits.require_units," in src


def test_the_retry_log_names_what_fired_and_never_the_reply():
    assert cos._completed_action_trigger("Sure. I'll take you to the invoices page now.") \
        in ("navigation_promise",) or cos._completed_action_trigger(
            "Sure. I'll take you to the invoices page now.").startswith("phrase:")
    assert cos._completed_action_trigger("Here is what I found.") == "none"


def test_a_calls_own_opener_is_the_first_word_at_arrival(monkeypatch):
    import chief_fast_track as cft
    import route_ledger
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    req = SimpleNamespace(business_id="b", message="Did Maria pay?", conversation_history=[],
                          client_surface="voice", spoken_opener="Let me take a look.", mode=None,
                          image_ids=[], conversation_id=None, request_id=None)
    session = SimpleNamespace(user=SimpleNamespace(id="u"))
    track = cft.plan(req, session)
    assert track.rec.opener_source == "client"
    assert track.rec.ttft_ms is not None and track.rec.ttft_ms < 50
    route_ledger.WINDOW = route_ledger.SloWindow()
