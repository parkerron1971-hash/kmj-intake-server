"""
test_sonnet_5_5_compat.py — Chief's lanes can run on Claude Sonnet 5.5 (2026-09-28).

Sonnet 5.5 costs the same per token as Sonnet 5 and ran the Chief turn
eval faster (median turn 8.5-9.1 s vs 11.2 s, same score), but it rejects
three request shapes Sonnet 5 accepts, and it declines in more categories:

  1. thinking {"type": "disabled"} is a 400 -> the answer check's "no
     thinking" becomes {"type": "between_tools"} there, and only there
     (no other model accepts between_tools).
  2. a forced tool_choice ("tool" / "any") is a 400 -> creative_director's
     structured call, which rides the review lane, falls back to "auto"
     with the tool named in the prompt.
  3. a decline is a 200 with stop_reason "refusal" and no text. The stream
     used to read that as "returned empty", ask the same model twice more
     and then go to the backup brain on another provider. Now it is asked
     once on the previous Sonnet, and never re-asked on the same model.
"""
from __future__ import annotations

import asyncio
import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos
import llm_call
import model_ladder


# ─── 1. thinking off ────────────────────────────────────────────────

def test_thinking_off_is_between_tools_on_sonnet_5_5_only():
    assert model_ladder.thinking_off_kwargs("claude-sonnet-5-5") == {"thinking": {"type": "between_tools"}}
    assert model_ladder.thinking_off_kwargs("claude-sonnet-5") == {"thinking": {"type": "disabled"}}
    # Models that cannot turn thinking off get nothing; the caller bounds effort instead.
    assert model_ladder.thinking_off_kwargs("claude-opus-5-5") == {}
    assert model_ladder.thinking_off_kwargs("claude-fable-5-1") == {}


def test_the_answer_check_turns_thinking_off_the_way_sonnet_5_5_accepts(monkeypatch):
    import chief_models
    import chief_truth as truth
    import spend_guard
    sent = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"content": [{"type": "text", "text": '{"verdict":"supported","claims":[]}'}]}

    async def apost(client, payload, **kw):
        sent.update(payload)
        return _Resp()
    monkeypatch.delenv("CHIEF_REVIEW_THINKING", raising=False)
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(llm_call, "api_key", lambda: "k")
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(chief_models, "model_for", lambda lane, plan=None: "claude-sonnet-5-5")
    asyncio.run(truth.review_reply(None, "sys", [{"role": "user", "content": "x"}], max_tokens=100))
    assert sent["thinking"] == {"type": "between_tools"}
    assert "effort" not in sent.get("output_config", {})


# ─── 2. forced tool use ─────────────────────────────────────────────

def test_sonnet_5_5_is_marked_as_rejecting_forced_tool_choice():
    assert not model_ladder.supports_forced_tool_choice("claude-sonnet-5-5")
    assert model_ladder.supports_forced_tool_choice("claude-sonnet-5")


def _structured_payload(monkeypatch, model):
    import chief_models
    import creative_director as cd
    from pydantic import BaseModel

    class Out(BaseModel):
        note: str

    sent = {}

    class _Resp:
        is_success = True

        def json(self):
            return {"stop_reason": "tool_use", "content": [
                {"type": "tool_use", "name": "return_result", "input": {"note": "ok"}}]}

    async def apost(client, payload, **kw):
        sent.update(payload)
        return _Resp()

    async def guard(_bid, _scope='platform'):
        return None
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(cd, "guard", guard)
    monkeypatch.setattr(chief_models, "model_for", lambda lane, plan=None: model)
    out = asyncio.run(cd.structured(None, {"business_id": "b"}, Out, "Plan it.", "content"))
    assert out.note == "ok"
    return sent


def test_structured_design_call_does_not_force_the_tool_on_sonnet_5_5(monkeypatch):
    sent = _structured_payload(monkeypatch, "claude-sonnet-5-5")
    assert sent["tool_choice"] == {"type": "auto"}
    assert "return_result tool exactly once" in sent["system"]


def test_structured_design_call_still_forces_the_tool_where_allowed(monkeypatch):
    sent = _structured_payload(monkeypatch, "claude-sonnet-5")
    assert sent["tool_choice"] == {"type": "tool", "name": "return_result"}
    assert sent["system"] == "Plan it."


# ─── 3. a decline ───────────────────────────────────────────────────

def _refusal_sse():
    return [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"refusal",'
        '"stop_details":{"type":"refusal","category":"general_harms"}},"usage":{"output_tokens":1}}',
    ]


def _text_sse(text):
    return [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}',
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"' + text + '"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":5}}',
    ]


class _Resp:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def aread(self):
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


@pytest.fixture
def stream(monkeypatch):
    state = {"models": [], "fallbacks": 0}

    @contextlib.asynccontextmanager
    async def fake_astream(client, payload, timeout=None, key=None, extra_headers=None, task=None):
        state["models"].append(payload["model"])
        yield _Resp(_refusal_sse() if payload["model"] == "claude-sonnet-5-5"
                    else _text_sse("Here is the answer."))

    async def fake_fallback(*a, **k):
        state["fallbacks"] += 1
        return "backup brain"

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(llm_call, "astream", fake_astream)
    monkeypatch.setattr(cos.fallback_brain, "call_fallback", fake_fallback)
    monkeypatch.setattr(cos, "log_api_usage", _noop)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "test-key")
    monkeypatch.setattr(cos.asyncio, "sleep", _noop)

    def run():
        sunk = []
        out = asyncio.run(cos._call_claude(
            None, "SYSTEM", [{"role": "user", "content": "hi"}],
            model="claude-sonnet-5-5", stream_sink=sunk.append))
        return out, state, sunk
    return run


def test_a_declined_turn_is_asked_once_on_the_previous_sonnet(stream, monkeypatch):
    monkeypatch.delenv("CHIEF_REFUSAL_FALLBACK_MODEL", raising=False)
    out, state, sunk = stream()
    assert out == "Here is the answer."
    assert state["models"] == ["claude-sonnet-5-5", "claude-sonnet-5"], (
        "one ask on the declining model, one on the fallback -- never a retry "
        "of the same request on the model that just declined it")
    assert state["fallbacks"] == 0
    assert "".join(sunk) == "Here is the answer."


def test_the_switch_off_goes_straight_to_the_old_path_without_retrying(stream, monkeypatch):
    monkeypatch.setenv("CHIEF_REFUSAL_FALLBACK_MODEL", "off")
    out, state, _ = stream()
    assert state["models"] == ["claude-sonnet-5-5"]
    assert state["fallbacks"] == 1 and out == "backup brain"


def test_no_fallback_to_the_model_that_declined():
    assert cos._refusal_fallback_model("claude-sonnet-5") is None


# ─── 4. "I checked your records" is a read, not a write ─────────────
# Sonnet 5.5 opens advice by saying it looked. The reviewer files that as
# an action claim, and with no write receipt it withheld the whole answer
# ("No action ran in this request. I couldn't verify my proposed answer.")
# on 3 of 15 advice turns in the 2026-09-28 bench.

import json  # noqa: E402

import chief_truth as truth  # noqa: E402

_READ_SOURCES = {"tool:list_offerings": {"kind": "record", "text": "[]", "complete": True}}


def _unsupported(*claims):
    return json.dumps({"verdict": "unsupported", "claims": list(claims)})


def _action(text):
    return {"text": text, "kind": "action", "source_id": "", "quote": "", "gap": "no write receipt"}


def test_read_narration_is_recognised():
    for text in ("I checked your records first.", "I pulled your records and found this:",
                 "I've looked through your calendar.", "Okay, I just reviewed your offerings."):
        assert truth.is_read_narration(text), text
    for text in ("I checked and sent the invoice.", "I checked with Marcus.",
                 "I've booked the session.", "I pulled up the draft and emailed it to Ada.",
                 "Your records show nothing."):
        assert not truth.is_read_narration(text), text


def test_a_read_narration_is_proved_by_the_turns_reads():
    reply = "I checked your records first."
    verdict, _, _ = truth.assess_review(_unsupported(_action(reply)), reply, _READ_SOURCES)
    assert verdict == "supported"


def test_a_read_narration_on_a_turn_that_read_nothing_still_fails():
    reply = "I checked your records first."
    verdict, _, reason = truth.assess_review(_unsupported(_action(reply)), reply, {})
    assert verdict == "unsupported" and reason.startswith(truth.ACTION_WITHOUT_RECEIPT)


def test_a_write_hidden_in_a_read_narration_still_needs_its_receipt():
    reply = "I checked your records and sent the reminder."
    verdict, _, reason = truth.assess_review(_unsupported(_action(reply)), reply, _READ_SOURCES)
    assert verdict == "unsupported" and reason.startswith(truth.ACTION_WITHOUT_RECEIPT)
