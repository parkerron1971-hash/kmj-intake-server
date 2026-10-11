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


# ─── A paused run is never silent ────────────────────────────────────

class _FakeSB:
    """Records workflow_engine._sb calls and answers from a small table."""

    def __init__(self, steps, existing_notice=False, name="New client welcome"):
        self.steps, self.existing, self.name = steps, existing_notice, name
        self.calls = []

    async def __call__(self, client, method, path, body=None, prefer=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("/workflow_definitions"):
            return 200, [{"name": self.name, "steps": self.steps}]
        if method == "GET" and path.startswith("/businesses"):
            return 200, [_biz()]
        if method == "GET" and path.startswith("/chief_notifications"):
            return 200, ([{"id": "n0"}] if self.existing else [])
        if method == "POST" and path == "/chief_notifications":
            return 201, None
        return 200, None

    def notices(self):
        return [b for m, p, b in self.calls if m == "POST" and p == "/chief_notifications"]


def _run():
    return {"id": "run-1", "workflow_id": "wf-1", "business_id": "b1",
            "step_cursor": 0, "context": {}, "log": []}


def test_a_pause_files_one_notice_with_a_yes_button_and_a_push(monkeypatch):
    fake = _FakeSB([{"action": "send_sms", "params": {"message": "Welcome!"}}])
    monkeypatch.setattr(we, "_sb", fake)
    import push_notifications
    pushed = []
    monkeypatch.setattr(push_notifications, "push_enabled", lambda: True)
    monkeypatch.setattr(push_notifications, "send_to_user",
                        lambda uid, **k: pushed.append((uid, k)) or 1)
    res = asyncio.run(we.advance_run(None, _run()))
    assert res["status"] == "awaiting_confirmation"
    [notice] = fake.notices()
    assert notice["title"] == "Your \u2018New client welcome\u2019 automation is waiting for your OK"
    assert "before it sends the text" in notice["body"]
    assert notice["action_payload"] == {"type": "confirm_workflow_step", "run_id": "run-1",
                                        "dedup_key": "workflow_confirm:run-1:0"}
    assert notice["suggested_action"]
    assert pushed and pushed[0][0] == "owner1"
    assert pushed[0][1]["title"] == notice["title"] and pushed[0][1]["tag"] == "workflow-run-1"


def test_the_notice_is_deduped_per_run_and_step(monkeypatch):
    fake = _FakeSB([{"action": "send_sms", "params": {}}], existing_notice=True)
    monkeypatch.setattr(we, "_sb", fake)
    import push_notifications
    monkeypatch.setattr(push_notifications, "push_enabled", lambda: True)
    monkeypatch.setattr(push_notifications, "send_to_user",
                        lambda *a, **k: pytest.fail("a deduped notice must not push again"))
    asyncio.run(we.advance_run(None, _run()))
    assert fake.notices() == []


def test_no_push_when_push_is_off(monkeypatch):
    fake = _FakeSB([{"action": "send_sms", "params": {}}])
    monkeypatch.setattr(we, "_sb", fake)
    import push_notifications
    monkeypatch.setattr(push_notifications, "push_enabled", lambda: False)
    monkeypatch.setattr(push_notifications, "send_to_user",
                        lambda *a, **k: pytest.fail("push is off"))
    asyncio.run(we.advance_run(None, _run()))
    assert len(fake.notices()) == 1


def test_an_explicit_confirmation_step_also_announces(monkeypatch):
    fake = _FakeSB([{"action": "create_module_entry", "label": "Add them to the roster",
                     "requires_confirmation": True}], name="")
    monkeypatch.setattr(we, "_sb", fake)
    import push_notifications
    monkeypatch.setattr(push_notifications, "push_enabled", lambda: False)
    asyncio.run(we.advance_run(None, _run()))
    [notice] = fake.notices()
    assert notice["title"] == "One of your automations is waiting for your OK"
    assert "\u201cAdd them to the roster\u201d" in notice["body"]


def test_a_failed_notice_does_not_fail_the_pause(monkeypatch):
    fake = _FakeSB([{"action": "send_sms", "params": {}}])

    async def _broken(client, method, path, body=None, prefer=None):
        if path.startswith("/chief_notifications"):
            raise RuntimeError("supabase down")
        return await fake(client, method, path, body, prefer)
    monkeypatch.setattr(we, "_sb", _broken)
    res = asyncio.run(we.advance_run(None, _run()))
    assert res["status"] == "awaiting_confirmation"


# ─── The Yes button: confirm_workflow_step ───────────────────────────

class _RunsSB:
    def __init__(self, rows):
        self.rows, self.paths = rows, []

    async def __call__(self, client, method, path, body=None, prefer=None):
        self.paths.append(path)
        if path.startswith("/workflow_runs"):
            return 200, self.rows
        if path.startswith("/workflow_definitions"):
            return 200, [{"name": "New client welcome"}]
        return 200, None


def test_confirm_releases_the_owners_waiting_run(monkeypatch):
    fake = _RunsSB([{"id": "run-1", "workflow_id": "wf-1", "status": "awaiting_confirmation"}])
    monkeypatch.setattr(we, "_sb", fake)
    released = []

    async def _confirm(run_id, confirmed_by):
        released.append((run_id, confirmed_by))
        return {"ok": True}
    monkeypatch.setattr(we, "confirm_run", _confirm)
    res = asyncio.run(we.handle_confirm_workflow_step(None, _biz(), {"run_id": "run-1"}))
    assert released == [("run-1", "owner:owner1")]
    assert res["result"].startswith("Released") and res["label"]
    assert not res.get("failed")
    # Scoped to this business: another tenant's run id cannot be released.
    assert "business_id=eq.b1" in fake.paths[0]


def test_confirm_latest_picks_the_newest_waiting_run(monkeypatch):
    fake = _RunsSB([{"id": "run-9", "workflow_id": "wf-1", "status": "awaiting_confirmation"}])
    monkeypatch.setattr(we, "_sb", fake)

    async def _confirm(run_id, confirmed_by):
        return {"ok": True}
    monkeypatch.setattr(we, "confirm_run", _confirm)
    res = asyncio.run(we.handle_confirm_workflow_step(None, _biz(), {}))
    assert not res.get("failed")
    assert "status=eq.awaiting_confirmation" in fake.paths[0]


@pytest.mark.parametrize("rows", [[], [{"id": "run-1", "workflow_id": "wf-1", "status": "done"}]])
def test_confirm_with_nothing_waiting_fails_politely(monkeypatch, rows):
    monkeypatch.setattr(we, "_sb", _RunsSB(rows))
    monkeypatch.setattr(we, "confirm_run",
                        lambda *a, **k: pytest.fail("nothing to release"))
    res = asyncio.run(we.handle_confirm_workflow_step(None, _biz(), {"run_id": "run-1"}))
    assert res.get("failed") and res["result"].startswith("Failed:") and res["label"]


def test_confirm_is_class_c_and_reachable_from_a_notification():
    import action_registry
    import chief_of_staff as cos
    assert action_registry.reversibility("confirm_workflow_step") == "C"
    assert not action_registry.is_bulk("confirm_workflow_step")
    assert cos.ACTION_HANDLERS["confirm_workflow_step"] is we.handle_confirm_workflow_step
