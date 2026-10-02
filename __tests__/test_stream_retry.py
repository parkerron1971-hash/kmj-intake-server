"""
test_stream_retry.py — the streaming model call survives the hiccups the
plain one already survived.

Kevin, 8/14: "it had trouble connecting. can we make sure that is good."

The history is the point. The 2026-07-17 fix for this EXACT symptom gave
the non-streaming branch a 3-attempt backoff retry on 408/429/5xx — the
comment on that loop cites Kevin's live repro of back-to-back "trouble
connecting" turns. The streaming branch was built later for the voice
arc and never inherited it, and the app rides the STREAMING path on
every turn. So one 529 while Anthropic was busy skipped every retry,
rolled the dice on the fallback brain, and a fallback stumble became
"I'm having trouble connecting right now".

What must hold:

  1. A transient error (529/429/5xx, transport drop, empty 200) is
     RETRIED, and a success on attempt two or three delivers the reply
     with no fallback involved.
  2. NEVER retry after text has reached the sink — the client already
     heard it; a retry would speak the reply twice. A partial IS the
     reply.
  3. Hard client errors (400) fail fast — they are our bugs, and
     retrying them is three chances to log the same mistake.
  4. Only after three failed attempts does the backup brain get its one
     shot — same contract as the non-streaming path.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from __tests__._chief_source import chief_source  # noqa: E402
import pytest

import chief_of_staff as cos
import llm_call


def _sse(text):
    """Minimal Anthropic SSE for one text reply."""
    return [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"' + text + '"}}',
        'data: {"type":"message_delta","usage":{"output_tokens":5}}',
    ]


class _Resp:
    def __init__(self, status=200, lines=None, drop_after=None):
        self.status_code = status
        self._lines = lines if lines is not None else []
        self._drop_after = drop_after

    async def aread(self):
        return b"upstream says no"

    async def aiter_lines(self):
        import httpx
        for i, line in enumerate(self._lines):
            if self._drop_after is not None and i >= self._drop_after:
                raise httpx.ReadError("connection dropped mid-stream")
            yield line


@pytest.fixture
def harness(monkeypatch):
    """Drive the REAL _call_claude streaming branch with a scripted
    sequence of upstream responses."""
    state = {"responses": [], "attempts": 0, "fallbacks": 0, "sunk": [],
             "payloads": [], "sleeps": []}

    @contextlib.asynccontextmanager
    async def fake_astream(client, payload, timeout=None, key=None, extra_headers=None, task=None):
        idx = min(state["attempts"], len(state["responses"]) - 1)
        state["attempts"] += 1
        state["payloads"].append(copy.deepcopy(payload))
        yield state["responses"][idx]

    async def fake_fallback(client, system, messages, max_tokens, business_id, reason=""):
        state["fallbacks"] += 1
        state["fallback_reason"] = reason
        return "fallback reply"

    async def _noop(*a, **k):
        return None

    async def _sleep(delay):
        state["sleeps"].append(delay)

    monkeypatch.setattr(llm_call, "astream", fake_astream)
    monkeypatch.setattr(cos.fallback_brain, "call_fallback", fake_fallback)
    monkeypatch.setattr(cos, "log_api_usage", _noop)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "test-key")
    # No real sleeping between attempts — the schedule is not under test.
    monkeypatch.setattr(cos.asyncio, "sleep", _sleep)

    def run(*responses, **kwargs):
        state["responses"] = list(responses)
        out = asyncio.run(cos._call_claude(
            None, "SYSTEM", [{"role": "user", "content": "hi"}],
            stream_sink=state["sunk"].append, **kwargs))
        return out, state

    return run


# ─────────────────────────────────────────────────────────────────────
# 1. Transient failures are retried
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 529])
def test_a_transient_error_then_success_delivers_the_reply(harness, status):
    out, st = harness(_Resp(status=status), _Resp(lines=_sse("All good.")))
    assert out == "All good."
    assert st["attempts"] == 2, "the second attempt should have been made"
    assert st["fallbacks"] == 0, (
        "a hiccup that clears on retry must never roll the dice on the "
        "fallback brain — that is the 07-17 contract, now for streaming"
    )
    assert st["sunk"] == ["All good."], "the reply reached the sink once"


def test_two_failures_then_success_still_delivers(harness):
    out, st = harness(_Resp(status=529), _Resp(status=529),
                      _Resp(lines=_sse("Third time.")))
    assert out == "Third time."
    assert st["attempts"] == 3 and st["fallbacks"] == 0


def test_a_dropped_stream_with_no_text_is_retried(harness):
    out, st = harness(_Resp(lines=_sse("never seen"), drop_after=0),
                      _Resp(lines=_sse("Recovered.")))
    assert out == "Recovered."
    assert st["fallbacks"] == 0


def test_an_empty_200_is_treated_as_transient(harness):
    out, st = harness(_Resp(lines=[]), _Resp(lines=_sse("Filled in.")))
    assert out == "Filled in."
    assert st["attempts"] == 2


def _ended_stream(reason="max_tokens", block_type="thinking", text=""):
    block = {"type": block_type}
    if block_type == "tool_use":
        block.update(id="write-1", name="create_contact")
    events = [
        {"type": "content_block_start", "index": 0, "content_block": block},
    ]
    if block_type == "tool_use":
        events.append({"type": "content_block_delta", "index": 0,
                       "delta": {"type": "input_json_delta", "partial_json": '{"name":"Ada"}'}})
    if text:
        events.append({"type": "content_block_delta", "index": 1,
                       "delta": {"type": "text_delta", "text": text}})
    events.extend([
        {"type": "message_delta", "delta": {"stop_reason": reason},
         "usage": {"output_tokens": 1400}},
        {"type": "message_stop"},
    ])
    return ["data: " + json.dumps(event) for event in events]


def test_empty_exhausted_budget_recovers_once_on_same_model_without_backoff(harness):
    out, st = harness(_Resp(lines=_ended_stream()), _Resp(lines=_sse("Try a fixed monthly price.")),
                      model="claude-sonnet-5-5", effort="medium", max_tokens=1400)
    first, recovery = st["payloads"]
    assert out == "Try a fixed monthly price."
    assert st["attempts"] == 2 and st["fallbacks"] == 0 and not st["sleeps"]
    assert recovery["thinking"] == {"type": "between_tools"}
    assert recovery["output_config"] == {"effort": "low"}
    for key in ("model", "max_tokens", "system", "messages"):
        assert recovery[key] == first[key]


def test_repeated_budget_exhaustion_does_not_make_third_identical_request(harness):
    out, st = harness(_Resp(lines=_ended_stream()), model="claude-sonnet-5-5")
    assert st["attempts"] == 2 and st["fallbacks"] == 1
    assert st["fallback_reason"] == "stream empty at max_tokens"
    assert out == "fallback reply" and st["sunk"] == [out]


@pytest.mark.parametrize("block_type", ["tool_use", "server_tool_use"])
def test_truncated_tool_blocks_are_never_executed_or_blindly_retried(harness, monkeypatch, block_type):
    async def forbidden(*args):
        pytest.fail("a max_tokens tool block must not execute")
    monkeypatch.setattr(cos.chief_tool_loop, "run_tool_round", forbidden)
    out, st = harness(_Resp(lines=_ended_stream(block_type=block_type)),
                      model="claude-sonnet-5-5", read_tools=[{"name": "create_contact"}],
                      tool_biz={"id": "fictional"})
    assert st["attempts"] == 1 and st["fallbacks"] == 1


def test_token_exhaustion_after_text_never_replays_it(harness):
    out, st = harness(_Resp(lines=_ended_stream(text="Start at a fixed monthly price.")),
                      model="claude-sonnet-5-5")
    assert out == "Start at a fixed monthly price."
    assert st["attempts"] == 1 and st["fallbacks"] == 0


def test_recovery_preserves_completed_tool_receipt_without_repeating_write(harness, monkeypatch):
    writes = []
    async def run_tool_round(client, biz, content, count):
        writes.append(content)
        return ({"role": "assistant", "content": content},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "write-1",
                                               "content": "Contact created: c-1"}]}, 1)
    monkeypatch.setattr(cos.chief_tool_loop, "run_tool_round", run_tool_round)
    out, st = harness(_Resp(lines=_ended_stream(reason="tool_use", block_type="tool_use")),
                      _Resp(lines=_ended_stream()), _Resp(lines=_sse("Ada is saved.")),
                      model="claude-sonnet-5-5", read_tools=[{"name": "create_contact"}],
                      tool_biz={"id": "fictional"})
    assert out == "Ada is saved." and len(writes) == 1
    assert st["attempts"] == 3 and st["fallbacks"] == 0
    assert st["payloads"][1]["messages"] == st["payloads"][2]["messages"]
    assert st["payloads"][2]["messages"][-1]["content"][0]["tool_use_id"] == "write-1"
    assert st["payloads"][1]["tools"] == st["payloads"][2]["tools"]


def test_stream_result_log_contains_bounded_diagnostics_not_content(harness, caplog):
    import chief_request_timing as timing
    import time
    token = timing.CURRENT.set(timing.Trace(time.perf_counter(), "synthetic-turn"))
    try:
        with caplog.at_level("INFO", logger=cos.logger.name):
            harness(_Resp(lines=_ended_stream(text="PRIVATE SENTENCE")), model="claude-sonnet-5-5")
    finally:
        timing.CURRENT.reset(token)
    logs = [r.message for r in caplog.records if r.message.startswith("[chief stream result]")]
    assert len(logs) == 1 and "PRIVATE SENTENCE" not in logs[0]
    record = json.loads(logs[0].split("] ", 1)[1])
    assert record["request_id"] == "synthetic-turn"
    assert record["stop_reason"] == "max_tokens" and record["output_tokens"] == 1400
    assert record["blocks"]["thinking"] == 1 and record["text_chars"] == len("PRIVATE SENTENCE")


# ─────────────────────────────────────────────────────────────────────
# 2. Never retry once the client has heard text
# ─────────────────────────────────────────────────────────────────────

def test_a_partial_stream_is_the_reply_not_a_retry(harness):
    # Drop after the first delta: "Hello " already reached the sink.
    lines = _sse("Hello ")
    out, st = harness(_Resp(lines=lines, drop_after=2),
                      _Resp(lines=_sse("should never run")))
    assert out == "Hello"
    assert st["attempts"] == 1, (
        "text reached the client — a retry here would speak the reply twice"
    )
    assert st["fallbacks"] == 0


# ─────────────────────────────────────────────────────────────────────
# 3. Hard errors fail fast
# ─────────────────────────────────────────────────────────────────────

def test_a_400_is_never_retried(harness):
    out, st = harness(_Resp(status=400))
    assert st["attempts"] == 1, "a 400 is OUR bug — retrying logs it thrice"
    assert st["fallbacks"] == 1
    assert out == "fallback reply"


# ─────────────────────────────────────────────────────────────────────
# 4. The fallback gets exactly one shot, after exhaustion
# ─────────────────────────────────────────────────────────────────────

def test_three_transient_failures_then_one_fallback(harness):
    out, st = harness(_Resp(status=529), _Resp(status=529), _Resp(status=529))
    assert st["attempts"] == 3
    assert st["fallbacks"] == 1
    assert out == "fallback reply"
    assert st["sunk"] == ["fallback reply"], (
        "the fallback reply must reach the stream sink so a voice turn "
        "still speaks"
    )


# ─────────────────────────────────────────────────────────────────────
# close_view — "if I ask it to close anything out"
# ─────────────────────────────────────────────────────────────────────

def test_close_view_returns_the_house_contract():
    r = asyncio.run(cos.handle_close_view(None, {"id": "biz-1"}, {"type": "close_view"}))
    assert r["type"] == "close_view"
    assert r.get("result") and r.get("label")


def test_close_view_is_documented_in_the_prompt():
    """The prompt is the capability surface — a handler the prompt never
    names is a word Chief doesn't have."""
    src = chief_source()
    assert '"type":"close_view"' in src.replace(" ", "").replace("{{", "{")
    assert "close it out" in src, "Kevin's own phrasing should route to it"


def test_goodbyes_close_the_room_in_any_mode():
    """Kevin, 8/14: "when it gives the goodbyes, it closes the chat
    behind itself as well." The rule existed but was gated on 'while
    voice is active' — a TYPED goodbye left the window up. The prompt
    is the capability surface; the words must say any-mode."""
    src = chief_source()
    assert "GOODBYES CLOSE THE ROOM BEHIND YOU" in src
    assert "voice OR text" in src
    assert "wraps up while voice is active" not in src, (
        "the voice-only gate is the bug — it must not survive"
    )
