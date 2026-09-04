"""
test_tool_loop.py — Chief reads mid-thought, and ONLY reads.

The Jarvis arc, step 1 (Kevin, 8/14: "anything that is requested in the
system, I want Chief to be able to do with no problem"). The ceiling was
architectural: a turn wrote its whole reply before any action ran, so
Chief could not look anything up while it thought — every gap became
"I don't have that loaded" or a web search over the practitioner's own
books, and every fix was one more table stuffed into the prompt.

Now _call_claude runs tool rounds: a stop_reason of tool_use executes
the reads and asks again, in both the streaming and non-streaming
branches. What this file holds down:

  1. THE TOOLBOX IS THE MCP READ SURFACE, DERIVED. One audited list —
     not a second, driftable one. show_view stays out (display is an
     action, one way to reach the screen).
  2. READS ONLY, ENFORCED AT DISPATCH. A tool_use naming a write, a ui
     verb, or an unknown verb is refused with a readable error — the
     model was shown a read-only list, but safety does not rest on what
     the model was shown.
  3. THE LOOP TERMINATES. Round cap, per-turn call budget, and a model
     that keeps asking past the cap gets text back, not an exception.
  4. BOTH BRANCHES WORK — streaming (which the app rides) and plain.
     The streamed text and the returned text stay identical.
  5. NOTHING CHANGES WHEN TOOLS ARE OFF. read_tools=None is byte-for-
     byte the old behavior — coaches and inner drafts stay clean.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from __tests__._chief_source import chief_source  # noqa: E402
import pytest

import action_registry
import chief_of_staff as cos
import chief_tool_loop as ctl
import llm_call


_BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "type": "coach",
        "owner_id": "user-1", "settings": {}}


# ─────────────────────────────────────────────────────────────────────
# 1. The toolbox
# ─────────────────────────────────────────────────────────────────────

def test_the_toolbox_is_the_mcp_read_surface_minus_display():
    import mcp_server
    names = {t["name"] for t in ctl.read_tool_definitions()}
    exposed = set(mcp_server.exposed_tools())
    assert "show_view" not in names, "display stays an action"
    assert names == (exposed - {"show_view"}), (
        "one audited list — the loop must not grow or shrink it on its own"
    )


def test_tool_definitions_are_anthropic_shaped():
    for t in ctl.read_tool_definitions():
        assert t["name"] and isinstance(t["description"], str)
        assert isinstance(t["input_schema"], dict)
        assert t["input_schema"].get("type") == "object"


# ─────────────────────────────────────────────────────────────────────
# 2. Reads only, enforced at dispatch
# ─────────────────────────────────────────────────────────────────────

def _exec(name, args=None):
    return asyncio.run(ctl.execute_tool_use(None, _BIZ, name, args or {}))


@pytest.mark.parametrize("verb", ["create_invoice", "delete_contact",
                                  "send_invoice", "approve_draft"])
def test_a_write_verb_is_refused_even_though_a_handler_exists(verb):
    assert verb in cos.ACTION_HANDLERS, "premise: the handler exists"
    is_error, text = _exec(verb)
    assert is_error, f"{verb} is a WRITE — the loop must refuse it"
    assert "ACTION" in text, "the refusal should point the model at tags"


def test_a_ui_verb_is_refused():
    is_error, _ = _exec("navigate", {"tab": "grow"})
    assert is_error


def test_an_unknown_verb_is_refused_not_guessed():
    is_error, _ = _exec("summon_unicorns")
    assert is_error


def test_a_read_verb_executes_its_handler(monkeypatch):
    seen = {}

    async def fake_handler(client, biz, action):
        seen["biz"] = biz["id"]
        seen["action"] = action
        return {"type": "check_goals", "result": "2 on track",
                "label": "Goals", "nav": {"tab": "grow"},
                "frontend_event": {"name": "x"}}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", fake_handler)
    is_error, text = _exec("check_goals", {"lens": "business"})
    assert not is_error
    assert seen["biz"] == "biz-1"
    assert seen["action"]["type"] == "check_goals"
    payload = json.loads(text)
    assert payload["result"] == "2 on track"
    assert "nav" not in payload and "frontend_event" not in payload, (
        "UI plumbing must not reach the model — it has no screen"
    )


def test_a_huge_result_is_truncated(monkeypatch):
    async def fat_handler(client, biz, action):
        return {"type": "check_goals", "result": "ok", "rows": ["x" * 100] * 500}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", fat_handler)
    _, text = _exec("check_goals")
    assert len(text) < ctl.MAX_RESULT_CHARS + 100
    assert "truncated" in text


def test_a_raising_handler_is_an_error_result_not_an_exception(monkeypatch):
    async def boom(client, biz, action):
        raise RuntimeError("db down")
    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", boom)
    is_error, text = _exec("check_goals")
    assert is_error and "failed" in text


# ─────────────────────────────────────────────────────────────────────
# 3. run_tool_round
# ─────────────────────────────────────────────────────────────────────

def test_no_tool_use_blocks_means_the_turn_is_done():
    out = asyncio.run(ctl.run_tool_round(None, _BIZ,
        [{"type": "text", "text": "plain reply"}], 0))
    assert out is None


def test_a_round_builds_the_two_messages(monkeypatch):
    async def fake_handler(client, biz, action):
        return {"type": "check_goals", "result": "fine", "label": "G"}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", fake_handler)
    content = [
        {"type": "text", "text": "Let me check."},
        {"type": "server_tool_use", "id": "srv1", "name": "web_search"},
        {"type": "tool_use", "id": "tu1", "name": "check_goals", "input": {}},
    ]
    assistant_msg, results_msg, n = asyncio.run(
        ctl.run_tool_round(None, _BIZ, content, 0))
    assert n == 1
    assert [b["type"] for b in assistant_msg["content"]] == ["text", "tool_use"], (
        "server-tool blocks must not be replayed — they are the API's own"
    )
    assert results_msg["role"] == "user"
    assert results_msg["content"][0]["tool_use_id"] == "tu1"


def test_the_call_budget_refuses_past_the_cap(monkeypatch):
    async def fake_handler(client, biz, action):
        return {"type": "check_goals", "result": "fine", "label": "G"}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", fake_handler)
    content = [{"type": "tool_use", "id": f"t{i}", "name": "check_goals", "input": {}}
               for i in range(3)]
    _, results_msg, _ = asyncio.run(
        ctl.run_tool_round(None, _BIZ, content, ctl.MAX_TOOL_CALLS - 1))
    flags = [bool(r.get("is_error")) for r in results_msg["content"]]
    assert flags == [False, True, True], (
        "one call left in the budget: the first runs, the rest refuse"
    )


# ─────────────────────────────────────────────────────────────────────
# 4. The loop end to end, both branches
# ─────────────────────────────────────────────────────────────────────

def _tooluse_response(text="Let me look."):
    return {
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "content": [
            {"type": "text", "text": text},
            {"type": "tool_use", "id": "tu1", "name": "check_goals", "input": {}},
        ],
    }


def _final_response(text="Two goals on track."):
    return {"stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [{"type": "text", "text": text}]}


class _FakeResp:
    def __init__(self, body):
        self.status_code = 200
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


@pytest.fixture
def plain_harness(monkeypatch):
    state = {"responses": [], "i": 0, "handler_runs": 0, "payloads": []}

    async def fake_apost(client, payload, timeout=None, key=None, extra_headers=None):
        state["payloads"].append(json.loads(json.dumps(payload)))
        r = state["responses"][min(state["i"], len(state["responses"]) - 1)]
        state["i"] += 1
        return _FakeResp(r)

    async def fake_handler(client, biz, action):
        state["handler_runs"] += 1
        return {"type": "check_goals", "result": "2 on track", "label": "G"}

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(llm_call, "apost", fake_apost)
    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", fake_handler)
    monkeypatch.setattr(cos, "log_api_usage", _noop)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "test-key")
    monkeypatch.setattr(cos.asyncio, "sleep", _noop)

    def run(*responses):
        state["responses"] = list(responses)
        out = asyncio.run(cos._call_claude(
            None, "SYSTEM", [{"role": "user", "content": "how are my goals?"}],
            enable_web_search=False,
            read_tools=ctl.read_tool_definitions(), tool_biz=_BIZ))
        return out, state

    return run


def test_plain_branch_runs_the_tool_and_answers(plain_harness):
    out, st = plain_harness(_tooluse_response(), _final_response())
    assert out == "Two goals on track."
    assert st["handler_runs"] == 1
    # Round 2's request must carry the tool exchange.
    msgs = st["payloads"][1]["messages"]
    assert msgs[-2]["role"] == "assistant"
    assert msgs[-1]["content"][0]["type"] == "tool_result"


def test_plain_branch_round_cap_holds(plain_harness):
    # The model asks for tools forever; the loop must still terminate
    # with text, not an exception or an infinite spend.
    out, st = plain_harness(*[_tooluse_response()] * 10)
    assert st["i"] == ctl.MAX_TOOL_ROUNDS, "one request per round, capped"
    assert isinstance(out, str)


def test_tools_off_means_no_tools_in_payload(plain_harness, monkeypatch):
    state_payloads = []

    async def spy_apost(client, payload, timeout=None, key=None, extra_headers=None):
        state_payloads.append(payload)
        return _FakeResp(_final_response("plain"))
    monkeypatch.setattr(llm_call, "apost", spy_apost)
    out = asyncio.run(cos._call_claude(
        None, "SYSTEM", [{"role": "user", "content": "hi"}],
        enable_web_search=False))
    assert out == "plain"
    assert "tools" not in state_payloads[0], (
        "read_tools=None must be byte-for-byte the old request"
    )


def _sse_tooluse(text="Checking."):
    return [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}',
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
        'data: ' + json.dumps({"type": "content_block_delta", "index": 0,
                               "delta": {"type": "text_delta", "text": text}}),
        'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu1","name":"check_goals"}}',
        'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{}"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":5}}',
    ]


def _sse_final(text="All good."):
    return [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":10}}}',
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
        'data: ' + json.dumps({"type": "content_block_delta", "index": 0,
                               "delta": {"type": "text_delta", "text": text}}),
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":5}}',
    ]


class _StreamResp:
    def __init__(self, lines):
        self.status_code = 200
        self._lines = lines

    async def aread(self):
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


@pytest.fixture
def stream_harness(monkeypatch):
    state = {"scripts": [], "i": 0, "handler_runs": 0, "sunk": []}

    @contextlib.asynccontextmanager
    async def fake_astream(client, payload, timeout=None, key=None, extra_headers=None):
        script = state["scripts"][min(state["i"], len(state["scripts"]) - 1)]
        state["i"] += 1
        yield _StreamResp(script)

    async def fake_handler(client, biz, action):
        state["handler_runs"] += 1
        return {"type": "check_goals", "result": "2 on track", "label": "G"}

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(llm_call, "astream", fake_astream)
    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", fake_handler)
    monkeypatch.setattr(cos, "log_api_usage", _noop)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "test-key")
    monkeypatch.setattr(cos.asyncio, "sleep", _noop)

    def run(*scripts):
        state["scripts"] = list(scripts)
        out = asyncio.run(cos._call_claude(
            None, "SYSTEM", [{"role": "user", "content": "goals?"}],
            enable_web_search=False, stream_sink=state["sunk"].append,
            read_tools=ctl.read_tool_definitions(), tool_biz=_BIZ))
        return out, state

    return run


def test_stream_branch_runs_the_tool_and_answers(stream_harness):
    out, st = stream_harness(_sse_tooluse("Checking."), _sse_final("All good."))
    assert st["handler_runs"] == 1
    assert out == "Checking.\n\nAll good."
    assert "".join(st["sunk"]) == out, (
        "what streamed to the client and what returned must be identical"
    )


def test_stream_round_cap_holds(stream_harness):
    out, st = stream_harness(*[_sse_tooluse()] * 10)
    assert st["i"] == ctl.MAX_TOOL_ROUNDS
    assert isinstance(out, str)


def test_stream_with_tools_but_no_tool_use_is_one_round(stream_harness):
    out, st = stream_harness(_sse_final("Plain answer."))
    assert out == "Plain answer."
    assert st["i"] == 1 and st["handler_runs"] == 0


# ─────────────────────────────────────────────────────────────────────
# 5. The prompt knows, and the timing line counts
# ─────────────────────────────────────────────────────────────────────

def test_the_prompt_documents_mid_turn_lookups():
    src = chief_source()
    assert "MID-TURN LOOKUPS" in src
    assert "never claim data is unavailable before trying the tool" in src


def test_the_timing_line_reports_tool_calls():
    clock = cos._TurnClock()
    clock.mark("model")
    clock.tools = 3
    import logging
    records = []
    handler = logging.Handler()
    handler.emit = lambda r: records.append(r.getMessage())
    cos.logger.addHandler(handler)
    try:
        clock.log(lane="chat", streamed=True)
    finally:
        cos.logger.removeHandler(handler)
    assert any("tools=3" in m for m in records)
