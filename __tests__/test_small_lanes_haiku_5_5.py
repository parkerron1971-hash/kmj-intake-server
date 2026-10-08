"""
test_small_lanes_haiku_5_5.py — Chief's `fast` and `background` lanes run on Haiku 5.5 (2026-10-07).

Kevin: "Switch to 5.5 because its cheaper." Measured side by side on every
job these lanes do (fast answers, headline, voice preview, invoice scope,
plan scope, quick plan, design intent, action reasoner, playbook, vertical
patterns): every check passed on both models, Haiku 5.5 about 7x cheaper,
right 8/8 on a grammar question Haiku 4.5 got wrong 4/8, and it handed no
easy answer to Sonnet where Haiku 4.5 did 7 times in 80.

Haiku 5.5 thinks by default and its thinking counts against max_tokens, so
every one of these calls turns thinking off (chief_models.quick_call_kwargs);
a 24-token classifier would otherwise stop inside its thinking with no
answer. Haiku 4.5 requests are sent exactly as before.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace as S
from unittest.mock import AsyncMock, Mock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_fast_track as fast
import chief_models

H55 = "claude-haiku-5-5"
H45 = "claude-haiku-4-5-20251001"


def test_all_four_small_lanes_run_on_haiku_5_5(monkeypatch):
    for lane in ("fast", "background", "opener", "route"):
        monkeypatch.delenv(f"CHIEF_MODEL_{lane.upper()}", raising=False)
        assert chief_models.model_for(lane) == H55


def test_quick_call_kwargs_turns_thinking_off_only_on_haiku_5():
    assert chief_models.quick_call_kwargs(H55) == {"thinking": {"type": "disabled"}}
    assert chief_models.quick_call_kwargs(H45) == {}
    # A lane overridden to a bigger model keeps the request its caller built.
    assert chief_models.quick_call_kwargs("claude-sonnet-5-5") == {}
    assert chief_models.quick_call_kwargs("") == {}


def _text(text):
    resp = Mock(status_code=200, text="")
    resp.raise_for_status = Mock()
    resp.json.return_value = {"stop_reason": "end_turn", "model": "m", "usage": {},
                              "content": [{"type": "text", "text": text}]}
    return resp


def _async_capture(monkeypatch, module, text):
    import spend_guard
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(module.llm_call, "api_key", lambda: "fixture")
    api = AsyncMock(return_value=_text(text))
    monkeypatch.setattr(module.llm_call, "apost", api)
    return api


def _invoice_scope(monkeypatch):
    import chief_invoice_scope as scope
    api = _async_capture(monkeypatch, scope, '{"filter":"all","form":"list"}')
    asyncio.run(scope._choose(None, S(), "biz", {"required_filter": "all", "required_form": "list"}))
    return api.await_args.args[1]


def _plan_context(monkeypatch):
    import chief_plan_context as pc
    api = _async_capture(monkeypatch, pc, pc._CLEAR)
    req = S(message="Show me a short plan for the next two days", business_id="biz",
            conversation_history=[S(role="user", content="Read my email")])
    asyncio.run(pc.allows_generic_plan(None, req, "biz"))
    return api.await_args.args[1]


def _quick_plan(monkeypatch):
    import chief_quick_plan as qp
    options = [{"id": f"o{i}", "step": f"Step {i}"} for i in range(6)]
    api = _async_capture(monkeypatch, qp, json.dumps({"steps": [
        {"id": "o0", "when": "Today"}, {"id": "o1", "when": "Today"},
        {"id": "o2", "when": "Tomorrow"}, {"id": "o3", "when": "Tomorrow"}]}))
    asyncio.run(qp._choose(None, S(conversation_history=[]), {"business": {"id": "biz"}}, options))
    return api.await_args.args[1]


def _sync_capture(monkeypatch, module, attr, text):
    sent = {}

    def post(*args, **kw):
        sent.update(next(a for a in args if isinstance(a, dict)))
        return _text(text)
    monkeypatch.setattr(module.llm_call, attr, post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture")
    return sent


def _action_reasoner(monkeypatch):
    import chief_action_reasoner as ar
    sent = _sync_capture(monkeypatch, ar, "post", '{"plan": []}')
    ar.reason_unknown_action("onboard_client", {"name": "Jane"})
    return sent


def _playbook(monkeypatch):
    import chief_playbook as pb
    monkeypatch.setattr(pb, "log_api_usage_sync", lambda **k: None)
    sent = _sync_capture(monkeypatch, pb, "post", "WHO THIS IS\nA shop.")
    pb._synthesize({"id": "biz", "name": "Shop", "type": "barbershop"},
                   {"memories": [{"category": "fact", "content": "Busy Saturdays."}], "insights": []})
    return sent


def _design_intent(monkeypatch):
    import design_intent as di
    sent = _sync_capture(monkeypatch, di, "post", '{"vibe":"warm","intensity":"confident","confidence":0.9}')
    di.interpret(["warm", "earthy"], "bakery")
    return sent


def _vertical_distill(monkeypatch):
    import vertical_distill as vd
    sent = _sync_capture(monkeypatch, vd, "post_with", '{"patterns": []}')
    vd._distil("barbershop", [{"signal": "Tuesdays are slow", "businesses": 5}])
    return sent


CALLERS = [("fast", _invoice_scope), ("fast", _plan_context), ("fast", _quick_plan),
           ("background", _action_reasoner), ("background", _playbook),
           ("background", _design_intent), ("background", _vertical_distill)]


@pytest.mark.parametrize("lane,call", CALLERS, ids=[c.__name__.strip("_") for _, c in CALLERS])
def test_every_helper_call_on_haiku_5_5_has_thinking_off(monkeypatch, lane, call):
    monkeypatch.delenv(f"CHIEF_MODEL_{lane.upper()}", raising=False)
    payload = call(monkeypatch)
    assert payload["model"] == H55
    assert payload["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize("lane,call", CALLERS, ids=[c.__name__.strip("_") for _, c in CALLERS])
def test_rolled_back_to_haiku_4_5_the_request_is_unchanged(monkeypatch, lane, call):
    monkeypatch.setenv(f"CHIEF_MODEL_{lane.upper()}", H45)
    payload = call(monkeypatch)
    assert payload["model"] == H45
    assert "thinking" not in payload


def test_the_fast_answer_holds_its_length():
    # Haiku 5.5 ran past "under 120 words" on open questions (182-210 words)
    # and once answered a spoken question with a bulleted list. With the limit
    # stated as a ceiling and the voice note given a size, its longest spoken
    # answer fell from 199 words to 118 and no answer carried markdown (30 runs).
    assert "at most 120 words" in fast._FAST_SYSTEM
    assert "about 70 words" in fast._VOICE_NOTE and "no markdown" in fast._VOICE_NOTE
