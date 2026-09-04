"""
Chief's writes as tool calls (2026-09-04).

The read loop (test_tool_loop.py) stays exactly what it was. These pin
the door that opened for writes — and, above all, that it is the SAME
door: every write tool call goes through chief_of_staff._execute_actions,
never a handler, so the gate, the policy engine, reference resolution
and the undo log run as they do for a tag.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import action_registry
import chief_of_staff as cos
import chief_tool_loop as ctl
import mcp_server

_BIZ = {"id": "biz-1", "name": "Test Co", "type": "coach", "settings": {}}


def _exec(name, args=None):
    return asyncio.run(ctl.execute_tool_use(None, _BIZ, name, args or {}))


def _turn(steps, writes_allowed=True):
    """Run several tool calls as ONE turn. asyncio.run copies the
    context per call, so per-turn contextvars set inside a call never
    flow back to the test — in production the loop and chief_chat share
    a task. This helper is that task."""
    async def main():
        ctl.reset_turn(writes_allowed=writes_allowed)
        outs = []
        for name, args in steps:
            outs.append(await ctl.execute_tool_use(None, _BIZ, name, args or {}))
        return outs, ctl.writes_this_turn(), ctl.calls_this_turn()
    return asyncio.run(main())


@pytest.fixture(autouse=True)
def _fresh_turn():
    ctl.reset_turn(writes_allowed=False)
    yield
    ctl.reset_turn(writes_allowed=False)


@pytest.fixture
def door(monkeypatch):
    """A spy on the door. Records every call to _execute_actions and
    returns a canned result with the UI plumbing a real handler carries."""
    calls = []

    async def _spy(client, biz, actions, user_id=None, prior_results=None):
        calls.append({"biz": biz["id"], "actions": actions, "user_id": user_id})
        a = actions[0]
        return [{"type": a["type"], "result": "added", "label": f"Added {a.get('name', '?')}",
                 "contact_id": "c-1", "nav": {"tab": "operate", "sub": "contacts"},
                 "frontend_event": {"name": "solutionist-contacts-changed"},
                 "_authorized_by": "chat:A"}]
    monkeypatch.setattr(cos, "_execute_actions", _spy)
    return calls


# ─── which tools ─────────────────────────────────────────────────────

def test_write_tools_are_the_reviewed_class_a_surface():
    names = {t["name"] for t in ctl.write_tool_definitions()}
    expected = {v for v in mcp_server.WRITE_TOOL_SCHEMAS
                if action_registry.may_expose_to_agent(v, allow_writes=True)
                and not action_registry.is_bulk(v)}
    assert names == expected and names
    for n in names:
        assert action_registry.reversibility(n) == "A", n
        assert not action_registry.is_sensitive(n), n


def test_write_tools_are_anthropic_shaped():
    for t in ctl.write_tool_definitions():
        assert set(t) == {"name", "description", "input_schema"}
        assert t["input_schema"]["type"] == "object"
        assert t["input_schema"].get("additionalProperties") is False


def test_reads_are_always_offered_and_writes_only_when_asked():
    reads = {t["name"] for t in ctl.read_tool_definitions()}
    off = {t["name"] for t in ctl.tool_definitions_for_turn(False)}
    on = {t["name"] for t in ctl.tool_definitions_for_turn(True)}
    assert off == reads
    assert reads < on
    assert "create_contact" in on and "create_contact" not in off


def test_no_class_c_verb_is_ever_a_tool():
    names = {t["name"] for t in ctl.tool_definitions_for_turn(True)}
    for v in action_registry.REGISTRY:
        if action_registry.reversibility(v) == "C":
            assert v not in names, f"{v} is class C and must stay a tag"


# ─── refusals ────────────────────────────────────────────────────────

def test_a_write_is_refused_when_the_turn_did_not_allow_it(door):
    is_error, text = _exec("create_contact", {"name": "Ada"})
    assert is_error and "ACTION" in text
    assert not door, "the door must not open"


@pytest.mark.parametrize("verb", ["create_invoice", "send_sms", "delete_contact", "approve_draft"])
def test_class_c_is_refused_even_when_writes_are_allowed(verb, door):
    ctl.reset_turn(writes_allowed=True)
    is_error, text = _exec(verb)
    assert is_error
    assert "not a tool" in text and "ACTION" in text
    assert not door


def test_bulk_and_unreviewed_class_a_are_refused(door):
    ctl.reset_turn(writes_allowed=True)
    assert action_registry.reversibility("bulk_dismiss") == "A"
    is_error, _ = _exec("bulk_dismiss")
    assert is_error
    unreviewed = next(v for v in action_registry.REGISTRY
                      if action_registry.may_expose_to_agent(v, allow_writes=True)
                      and action_registry.effect(v) == action_registry.WRITE
                      and v not in mcp_server.WRITE_TOOL_SCHEMAS
                      and not action_registry.is_bulk(v))
    is_error, _ = _exec(unreviewed)
    assert is_error
    assert not door


# ─── the door ────────────────────────────────────────────────────────

def test_a_write_goes_through_execute_actions_not_a_handler(door, monkeypatch):
    called = []

    async def _never(client, biz, action):
        called.append(action)
        return {"type": "create_contact", "result": "x", "label": "x"}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "create_contact", _never)
    ctl.reset_turn(writes_allowed=True)
    tok = cos._TURN_USER_ID.set("user-9")
    try:
        is_error, text = _exec("create_contact", {"name": "Ada", "email": "a@x.io"})
    finally:
        cos._TURN_USER_ID.reset(tok)
    assert not is_error
    assert not called, "the handler is reached only through _execute_actions"
    assert door[0]["biz"] == "biz-1"
    assert door[0]["user_id"] == "user-9", "the practitioner's id reaches the policy engine"
    assert door[0]["actions"] == [{"name": "Ada", "email": "a@x.io", "type": "create_contact"}]


def test_the_model_sees_the_shrunk_result_and_actions_taken_keeps_the_ui(door):
    outs, taken, _ = _turn([("create_contact", {"name": "Ada"})])
    _, text = outs[0]
    seen = json.loads(text)
    assert seen["result"] == "added" and seen["contact_id"] == "c-1"
    assert "nav" not in seen and "frontend_event" not in seen
    assert len(taken) == 1
    assert taken[0]["nav"] == {"tab": "operate", "sub": "contacts"}
    assert taken[0]["frontend_event"]["name"] == "solutionist-contacts-changed"
    assert taken[0]["_authorized_by"] == "chat:A"


def test_arguments_cannot_rewrite_the_verb(door):
    ctl.reset_turn(writes_allowed=True)
    _exec("create_contact", {"name": "Ada", "type": "send_sms"})
    assert door[0]["actions"][0]["type"] == "create_contact"


def test_reads_are_not_recorded_as_writes(monkeypatch):
    async def fake(client, biz, action):
        return {"type": "check_goals", "result": "ok", "label": "G"}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", fake)
    ctl.reset_turn(writes_allowed=True)
    is_error, _ = _exec("check_goals")
    assert not is_error
    assert ctl.writes_this_turn() == []


def test_a_declined_write_is_an_error_the_model_reads(monkeypatch):
    async def _declines(client, biz, actions, user_id=None, prior_results=None):
        return [cos._fail("create_note", "Contact c-9 not found")]
    monkeypatch.setattr(cos, "_execute_actions", _declines)
    outs, taken, _ = _turn([("create_note", {"contact_id": "c-9", "note": "hi"})])
    is_error, text = outs[0]
    assert is_error
    assert taken and cos._action_failed(taken[0])


def test_a_raising_door_is_an_error_not_an_exception(monkeypatch):
    async def _boom(client, biz, actions, user_id=None, prior_results=None):
        raise RuntimeError("db down")
    monkeypatch.setattr(cos, "_execute_actions", _boom)
    ctl.reset_turn(writes_allowed=True)
    is_error, text = _exec("create_task", {"title": "x"})
    assert is_error and "did not go through" in text


# ─── budgets and holds ───────────────────────────────────────────────

def test_the_write_budget_closes_after_max_write_calls(door):
    steps = [("create_task", {"title": f"t{i}"}) for i in range(ctl.MAX_WRITE_CALLS)]
    steps.append(("create_task", {"title": "one too many"}))
    outs, taken, _ = _turn(steps)
    for is_error, _ in outs[:-1]:
        assert not is_error
    is_error, text = outs[-1]
    assert is_error and "budget" in text
    assert len(door) == ctl.MAX_WRITE_CALLS
    assert len(taken) == ctl.MAX_WRITE_CALLS


def test_reads_do_not_spend_the_write_budget(door, monkeypatch):
    async def fake(client, biz, action):
        return {"type": "check_goals", "result": "ok", "label": "G"}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", fake)
    outs, taken, calls = _turn([("check_goals", {})] * 4
                               + [("create_task", {"title": "still allowed"})])
    assert not outs[-1][0]
    assert len(taken) == 1 and calls == 5


def test_a_held_verdict_closes_the_turn_to_further_writes(monkeypatch):
    """One HELD per turn. The model asks; the next turn re-issues."""
    async def _held(client, biz, actions, user_id=None, prior_results=None):
        return [{"type": actions[0]["type"], "failed": True,
                 "result": "HELD FOR A SPOKEN YES — say 'go ahead' and I'll do it.",
                 "label": "Held: create task", "nav": None}]
    monkeypatch.setattr(cos, "_execute_actions", _held)
    outs, taken, _ = _turn([("create_task", {"title": "x"})] * 2)
    is_error, text = outs[0]
    assert is_error and "HELD" in text
    is_error, text = outs[1]
    assert is_error and "HELD" in text.upper()
    assert len(taken) == 1, "the retry never reached the door"


def test_reset_turn_clears_everything(door):
    async def main():
        ctl.reset_turn(writes_allowed=True)
        await ctl.execute_tool_use(None, _BIZ, "create_task", {"title": "x"})
        assert ctl.writes_this_turn() and ctl.calls_this_turn() == 1
        ctl.reset_turn()
        return ctl.writes_this_turn(), ctl.writes_allowed(), ctl.calls_this_turn()
    assert asyncio.run(main()) == ([], False, 0)


# ─── the turn around it ──────────────────────────────────────────────

def test_chief_chat_wires_the_turn():
    src = inspect.getsource(cos.chief_chat)
    assert "chief_tool_loop.reset_turn(writes_allowed=_native_writes)" in src
    assert "chief_tool_loop.tool_definitions_for_turn(_native_writes)" in src
    assert "CHIEF_NATIVE_WRITES" in src, "the kill switch back to tags-only"
    assert "tool_taken = chief_tool_loop.writes_this_turn()" in src
    # Tool writes land in actions_taken, before the tag half.
    assert "taken = tool_taken + (await _execute_actions(" in src


def test_a_tool_turn_skips_the_correction_retry_and_the_recompose():
    src = inspect.getsource(cos.chief_chat)
    retry = src[src.index("SYSTEM CORRECTION") - 1200: src.index("SYSTEM CORRECTION")]
    assert "and not tool_taken" in retry, "a tool_use block is the evidence; nothing to correct"
    recompose = src[src.index("Option D two-pass reply"): src.index("Option D two-pass reply") + 1500]
    assert "if taken and actions:" in recompose, (
        "recompose only when a TAG action ran — a tool turn wrote its reply after the results")


def test_coaches_stay_tag_only():
    src = inspect.getsource(cos.chief_chat)
    i = src.index("_native_writes = (")
    assert "not is_coach_mode" in src[i:i + 200]


def test_the_prompt_teaches_tools_that_act():
    src = inspect.getsource(cos)
    assert "TOOLS THAT ACT" in src
    i = src.index("TOOLS THAT ACT")
    para = src[i:i + 1500]
    assert "Do NOT also emit an [ACTION:] tag for the same operation" in para
    assert "HELD is not done" in para


def test_the_voice_block_says_tool_calls_are_silent():
    import chief_models
    assert "a tool call is silent" in chief_models.VOICE_DELIVERY_BLOCK


def test_untrusted_text_states_the_new_boundary_honestly():
    import untrusted_text
    assert "ATTEMPT DETECTOR" in untrusted_text.__doc__
