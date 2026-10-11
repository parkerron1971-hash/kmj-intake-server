"""Unattended class C runs only on an owner instruction (Kevin, 2026-10-11).

policy_engine used to record an unattended irreversible action and let it
run. These tests pin the callers: the paths the owner set up (a schedule, a
confirmed workflow step, a Trust Track grant, a smart/full autopilot) keep
running and name that act on the ledger; the paths where Chief decides by
itself (the standing agent, assignments, plans, the connector) are refused
by the rails, with a result the app can show.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import policy_engine as pe  # noqa: E402
import workflow_engine as we  # noqa: E402


def _biz(btype="coach", autopilot=None):
    settings = {}
    if autopilot is not None:
        settings["autopilot"] = {"overall": autopilot}
    return {"id": "b1", "type": btype, "owner_id": "owner1", "settings": settings}


@pytest.fixture(autouse=True)
def _refuse_mode(monkeypatch):
    monkeypatch.delenv("POLICY_UNATTENDED_C", raising=False)
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda *a, **k: [])


# ─── Workflows: an irreversible step waits for the owner's confirmation ─

def _handler_spy(monkeypatch, verb):
    calls = []

    async def _handler(client, biz, action):
        calls.append(action)
        return {"result": "sent", "label": "Sent"}
    from chief_of_staff import ACTION_HANDLERS
    monkeypatch.setitem(ACTION_HANDLERS, verb, _handler)
    import audit_log
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: True)
    return calls


def test_an_unconfirmed_irreversible_workflow_step_pauses(monkeypatch):
    calls = _handler_spy(monkeypatch, "send_sms")
    res = asyncio.run(we.execute_step(None, {"step_cursor": 0}, _biz(),
                                      {"action": "send_sms", "params": {"message": "hi"}}, {}))
    assert res == {"pause": True, "reason": "awaiting_confirmation"}
    assert calls == []


def test_a_confirmed_irreversible_step_runs_on_the_confirmation(monkeypatch):
    calls = _handler_spy(monkeypatch, "send_sms")
    rules = []
    real = pe.evaluate

    def _spy(*a, **k):
        v = real(*a, **k)
        rules.append(v.rule)
        return v
    monkeypatch.setattr(pe, "evaluate", _spy)
    res = asyncio.run(we.execute_step(None, {"step_cursor": 0}, _biz(),
                                      {"action": "send_sms", "params": {"message": "hi"}},
                                      {"_confirmed_steps": [0]}))
    assert res.get("ok") is True
    assert len(calls) == 1
    assert rules == ["workflow:C:confirmed_step"]


def test_a_reversible_workflow_step_does_not_pause(monkeypatch):
    calls = _handler_spy(monkeypatch, "create_task")
    res = asyncio.run(we.execute_step(None, {"step_cursor": 0}, _biz(),
                                      {"action": "create_task", "params": {"title": "x"}}, {}))
    assert res.get("ok") is True and len(calls) == 1


def test_a_bulk_step_is_refused_not_paused(monkeypatch):
    """Bulk is never unattended, confirmed or not: pausing it would only
    hide the refusal behind a confirmation that cannot help."""
    _handler_spy(monkeypatch, "batch_email")
    res = asyncio.run(we.execute_step(None, {"step_cursor": 0}, _biz(),
                                      {"action": "batch_email", "params": {}}, {}))
    assert res.get("ok") is False
    assert res["policy"]["rule"] == "bulk:never-unattended"


def test_record_only_switch_skips_the_workflow_pause(monkeypatch):
    monkeypatch.setenv("POLICY_UNATTENDED_C", "allow")
    calls = _handler_spy(monkeypatch, "send_sms")
    res = asyncio.run(we.execute_step(None, {"step_cursor": 0}, _biz(),
                                      {"action": "send_sms", "params": {"message": "hi"}}, {}))
    assert res.get("ok") is True and len(calls) == 1


# ─── Autopilot: the owner's level is the authority ───────────────────

def test_manual_autopilot_still_reads_as_manual_mode():
    import chief_of_staff as cos
    ok, reason = asyncio.run(cos._should_auto_approve(None, _biz(autopilot="manual"), "nurture", {}, None))
    assert (ok, reason) == (False, "manual_mode")


def test_full_autopilot_runs_on_the_owners_setting():
    import chief_of_staff as cos
    ok, reason = asyncio.run(cos._should_auto_approve(None, _biz(autopilot="full"), "nurture", {}, None))
    assert (ok, reason) == (True, "full_auto")


def test_regulated_full_autopilot_keeps_its_own_refusal():
    import chief_of_staff as cos
    ok, reason = asyncio.run(cos._should_auto_approve(None, _biz("therapist", autopilot="full"),
                                                      "nurture", {}, None))
    assert (ok, reason) == (False, "vertical:client_facing_disabled")


# ─── The door: an autonomous surface asking for class C ──────────────

@pytest.mark.parametrize("surface", ["agent", "assignment", "plan"])
def test_the_door_refuses_class_c_for_an_autonomous_surface(monkeypatch, surface):
    """The agent and assignment loops never offer class C, so this is the
    second wall: if a class-C action ever reached the door from one of
    them, the rails refuse it, and the refusal still carries result and
    label so the app never blanks."""
    import chief_of_staff as cos
    sent = []

    async def _handler(client, biz, action):
        sent.append(action)
        return {"result": "sent", "label": "Sent"}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "send_sms", _handler)
    results = asyncio.run(cos._execute_actions(
        None, _biz(), [{"type": "send_sms", "contact_name": "Maria", "message": "hi"}],
        surface=surface, prompted=False))
    assert sent == []
    assert len(results) == 1
    r = results[0]
    assert r.get("result") and r.get("label")
    assert cos._action_failed(r)
