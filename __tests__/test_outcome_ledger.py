"""
test_outcome_ledger.py — what came of Chief's moves, and what it teaches.

What must hold:
  1. A RUN'S ROWS ARE RIGHT: a proposal waits on its queue row, a task
     on its task, an assignment move on its assignment; a note is done
     the moment it is made; failures and navigation are not moves.
  2. THE RECONCILER ASKS PLAIN QUESTIONS and never guesses: approved /
     dismissed / expired from the queue, completed / ignored from the
     task, met / missed from the assignment, replied from an inbound
     event after an approval, no_signal only after the window.
  3. THE RETIRE RULE needs no model: three negatives in a row inside
     the window retire a verb; one approval among the last three ends
     it; pending rows do not count; outside the window nothing counts.
  4. THE LOOP OBEYS: a retired verb is refused before the budget is
     spent.
  5. THE DIGEST READS LIKE A SENTENCE and is empty when there is
     nothing to say; without a database it is empty and cheap.
  6. BOTH TRACES WRITE THE LEDGER; the event run now writes its plan
     before the act call.
House rules: sync tests + asyncio.run.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos
import chief_tool_loop as ctl
import outcome_ledger as ol
import sb_clients

NOW = datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc)
BIZ = {"id": "biz-1", "name": "Bloom Studio", "type": "salon", "owner_id": "own-1",
       "settings": {"autonomy": {"agent_enabled": True}}}


def _run(coro):
    return asyncio.run(coro)


def _at(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


# ─── 1. recording ────────────────────────────────────────────────────

def test_a_runs_rows_wait_on_the_right_thing():
    taken = [
        {"type": "propose_send_sms", "result": "proposed", "label": "x", "queue_id": "q-1", "proposed": True, "contact_id": "c-1"},
        {"type": "create_task", "result": "added", "label": "x", "task_id": "t-1"},
        {"type": "create_note", "result": "saved", "label": "x", "contact_id": "c-1"},
        {"type": "navigate", "result": "ok", "label": "x"},
        {"type": "update_contact", "error": "boom", "result": "failed: boom", "label": "x"},
        "junk",
    ]
    rows = ol.rows_for("biz-1", "agent", taken, now=NOW)
    assert [r["verb"] for r in rows] == ["propose_send_sms", "create_task", "create_note"]
    prop, task, note = rows
    assert prop["queue_id"] == "q-1" and prop["outcome"] == "pending" and prop["contact_id"] == "c-1"
    assert task["target_type"] == "task" and task["target_id"] == "t-1" and task["outcome"] == "pending"
    assert note["outcome"] == "done" and note["outcome_at"] and note["target_type"] == "contact"
    a_rows = ol.rows_for("biz-1", "assignment", [{"type": "create_note", "result": "saved", "label": "x"}],
                         assignment_id="a-1", now=NOW)
    assert a_rows[0]["outcome"] == "pending" and a_rows[0]["assignment_id"] == "a-1"


def test_record_is_best_effort(monkeypatch):
    posts = []
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer=None: posts.append((p, b)) or [])
    n = ol.record_moves("biz-1", "agent", [{"type": "create_note", "result": "ok", "label": "x"}])
    assert n == 1 and posts[0][0] == "/chief_moves" and isinstance(posts[0][1], list)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer=None: None)
    assert ol.record_moves("biz-1", "agent", [{"type": "create_note", "result": "ok", "label": "x"}]) == 0
    monkeypatch.setenv("OUTCOME_LEDGER", "off")
    assert ol.record_moves("biz-1", "agent", [{"type": "create_note", "result": "ok", "label": "x"}]) == 0


# ─── 2. reconciling ──────────────────────────────────────────────────

@pytest.fixture
def world(monkeypatch):
    state = {"moves": [], "queue": {}, "tasks": {}, "assignments": {}, "events": [], "set": []}

    def _get(path):
        if path.startswith("/chief_moves?outcome=eq.pending"):
            return [m for m in state["moves"] if m["outcome"] == "pending"]
        if path.startswith("/chief_moves?outcome=eq.approved"):
            return [m for m in state["moves"] if m["outcome"] == "approved" and m.get("contact_id")]
        if path.startswith("/agent_queue?id=in."):
            return list(state["queue"].values())
        if path.startswith("/tasks?id=in."):
            return list(state["tasks"].values())
        if path.startswith("/chief_assignments?id=in."):
            return list(state["assignments"].values())
        if path.startswith("/events?"):
            return list(state["events"])
        return []

    def _patch(path, body):
        mid = path.split("id=eq.")[1]
        state["set"].append((mid, body["outcome"]))
        for m in state["moves"]:
            if m["id"] == mid:
                m.update(body)
        return [{"id": mid}]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", _patch)
    return state


def _move(i, **over):
    base = {"id": f"m-{i}", "business_id": "biz-1", "surface": "agent", "verb": "create_note",
            "assignment_id": None, "queue_id": None, "target_type": None, "target_id": None,
            "contact_id": None, "outcome": "pending", "outcome_at": None, "made_at": _at(0.5)}
    base.update(over)
    return base


def test_the_reconciler_asks_plain_questions(world):
    world["moves"] = [
        _move(1, verb="send_sms", queue_id="q-ok", contact_id="c-1"),
        _move(2, verb="send_sms", queue_id="q-no"),
        _move(3, verb="send_invoice", queue_id="q-old", made_at=_at(9)),
        _move(4, verb="send_sms", queue_id="q-wait"),
        _move(5, verb="create_task", target_type="task", target_id="t-done"),
        _move(6, verb="create_task", target_type="task", target_id="t-late"),
        _move(7, verb="create_task", target_type="task", target_id="t-open"),
        _move(8, verb="create_note", assignment_id="a-met"),
        _move(9, verb="create_note", assignment_id="a-miss"),
        _move(10, verb="create_note", assignment_id="a-live"),
    ]
    world["queue"] = {"q-ok": {"id": "q-ok", "status": "sent"}, "q-no": {"id": "q-no", "status": "dismissed"},
                      "q-old": {"id": "q-old", "status": "draft"}, "q-wait": {"id": "q-wait", "status": "draft"}}
    world["tasks"] = {"t-done": {"id": "t-done", "status": "done"},
                      "t-late": {"id": "t-late", "status": "todo", "due_date": "2026-09-01"},
                      "t-open": {"id": "t-open", "status": "todo", "due_date": "2026-09-20"}}
    world["assignments"] = {"a-met": {"id": "a-met", "status": "completed"},
                            "a-miss": {"id": "a-miss", "status": "expired"},
                            "a-live": {"id": "a-live", "status": "active"}}
    world["events"] = [{"id": "e-1"}]
    tally = ol.resolve_pending(NOW)
    got = dict(world["set"])
    assert got["m-1"] == "replied", "approved, then the contact wrote back"
    assert got["m-2"] == "dismissed" and got["m-3"] == "no_signal" and "m-4" not in got
    assert got["m-5"] == "completed" and got["m-6"] == "ignored" and "m-7" not in got
    assert got["m-8"] == "met" and got["m-9"] == "missed" and "m-10" not in got
    assert tally["approved"] == 1 and tally["replied"] == 1 and tally["dismissed"] == 1


def test_no_reply_event_means_approved_stays_approved(world):
    world["moves"] = [_move(1, verb="send_sms", queue_id="q-ok", contact_id="c-1")]
    world["queue"] = {"q-ok": {"id": "q-ok", "status": "approved"}}
    ol.resolve_pending(NOW)
    assert dict(world["set"]) == {"m-1": "approved"}


# ─── 3. the retire rule ──────────────────────────────────────────────

def test_three_negatives_in_a_row_retire_a_verb_and_one_approval_ends_it():
    neg = [_move(i, verb="send_invoice", queue_id=f"q{i}", outcome="dismissed", made_at=_at(i)) for i in (1, 2, 3)]
    assert ol.retired_verbs(neg, NOW) == ["send_invoice"]
    mixed = [_move(1, verb="send_invoice", queue_id="q1", outcome="expired", made_at=_at(1)),
             _move(2, verb="send_invoice", queue_id="q2", outcome="approved", made_at=_at(2)),
             _move(3, verb="send_invoice", queue_id="q3", outcome="dismissed", made_at=_at(3)),
             _move(4, verb="send_invoice", queue_id="q4", outcome="dismissed", made_at=_at(4))]
    assert ol.retired_verbs(mixed, NOW) == []
    pending_between = neg + [_move(9, verb="send_invoice", queue_id="q9", outcome="pending", made_at=_at(0.1))]
    assert ol.retired_verbs(pending_between, NOW) == ["send_invoice"], "pending does not count either way"
    old = [_move(i, verb="send_invoice", queue_id=f"q{i}", outcome="dismissed", made_at=_at(20 + i)) for i in (1, 2, 3)]
    assert ol.retired_verbs(old, NOW) == [], "outside the window nothing counts"
    two = neg[:2]
    assert ol.retired_verbs(two, NOW) == []
    tasks = [_move(i, verb="create_task", target_type="task", outcome="ignored", made_at=_at(i)) for i in (1, 2, 3)]
    assert ol.retired_verbs(tasks, NOW) == [], "only proposals retire"


def test_retired_for_is_empty_without_a_database(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    calls = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: calls.append(p) or [])
    assert ol.retired_for("biz-1") == [] and not calls
    assert ol.digest_for("biz-1") == [] and not calls


# ─── 4. the loop obeys ───────────────────────────────────────────────

def test_a_retired_verb_is_refused_before_the_budget_is_spent(monkeypatch):
    import action_proposals as ap
    filed = []
    monkeypatch.setattr(ap, "file", lambda biz, action, **k: filed.append(action) or "q-1")
    monkeypatch.setattr(ol, "retired_for", lambda bid: ["send_invoice"])

    async def turn():
        ctl.reset_turn(True, surface="agent", prompted=False)
        err, text = await ctl.execute_tool_use(None, BIZ, "propose_send_invoice", {"invoice_id": "inv-1"})
        calls = ctl.calls_this_turn()
        err2, text2 = await ctl.execute_tool_use(None, BIZ, "propose_send_sms",
                                                 {"contact_name": "Ada", "message": "hi"})
        return err, text, calls, err2, text2
    err, text, calls, err2, text2 = _run(turn())
    assert err and "retired" in text and "last 3" in text and not filed[:0]
    assert calls == 0, "a refusal spends nothing"
    assert not err2 and len(filed) == 1, "other verbs are untouched"
    ctl.reset_turn(False)


# ─── 5. the digest ───────────────────────────────────────────────────

def test_the_digest_reads_like_a_sentence():
    moves = [
        _move(1, verb="send_sms", queue_id="q1", outcome="approved", made_at=_at(1)),
        _move(2, verb="send_sms", queue_id="q2", outcome="replied", made_at=_at(2)),
        _move(3, verb="send_sms", queue_id="q3", outcome="dismissed", made_at=_at(3)),
        _move(4, verb="send_invoice", queue_id="q4", outcome="dismissed", made_at=_at(1)),
        _move(5, verb="send_invoice", queue_id="q5", outcome="expired", made_at=_at(2)),
        _move(6, verb="send_invoice", queue_id="q6", outcome="dismissed", made_at=_at(3)),
        _move(7, verb="create_task", target_type="task", outcome="completed", made_at=_at(1)),
        _move(8, verb="create_task", target_type="task", outcome="ignored", made_at=_at(2)),
        _move(9, verb="create_task", target_type="task", outcome="pending", made_at=_at(0.2)),
        _move(10, verb="create_note", assignment_id="a-1", outcome="met", made_at=_at(1)),
    ]
    lines = ol.digest_lines(moves, NOW)
    assert lines[0].startswith("WHAT LANDS WITH THIS PRACTITIONER")
    body = "\n".join(lines[1:])
    assert "texts you proposed: 2 approved, 1 dismissed, 1 got a reply" in body
    assert "invoice sends you proposed: 2 dismissed, 1 expired unapproved — RETIRED for two weeks" in body
    assert "tasks you set: 1 completed, 1 ignored past due, 1 open" in body
    assert "1 toward outcomes that were met" in body
    assert len(lines) <= 6
    assert ol.digest_lines([], NOW) == []
    assert ol.digest_lines([_move(1, outcome="done")], NOW) == [], "notes alone say nothing"


# ─── 6. both traces write the ledger; the event run plans first ─────

def test_the_event_run_writes_its_plan_before_the_act_call(monkeypatch):
    import chief_agent as ag
    order, door = [], []

    async def _door(client, biz, actions, user_id=None, prior_results=None, surface="chat", prompted=True):
        order.append("door")
        door.append(actions[0]["type"])
        return [{"type": actions[0]["type"], "result": "saved", "label": "Note"}]
    monkeypatch.setattr(cos, "_execute_actions", _door)

    async def _digest(bid):
        return ["WHAT LANDS WITH THIS PRACTITIONER (last 30 days, from what came of your moves):",
                "  - texts you proposed: 3 approved"]
    monkeypatch.setattr(ol, "digest_async", _digest)

    async def fake_claude(client, system, messages, **kw):
        if not kw.get("read_tools"):
            order.append("plan")
            assert "before you touch" in system.lower() and "3 approved" in messages[0]["content"]
            return "Ada booked Thursday. I will note it on her record and set no task; nothing else is needed."
        order.append("act")
        assert "YOUR PLAN FOR THIS LOOK" in messages[0]["content"]
        await ctl.execute_tool_use(None, BIZ, "create_note", {"contact_id": "c1", "note": "Booked Thursday"})
        return "You have a new booking from Ada; I noted it."
    monkeypatch.setattr(cos, "_call_claude", fake_claude)
    traces = []

    async def _trace(client, biz, taken, record):
        traces.append(record)
    monkeypatch.setattr(ag, "_leave_trace", _trace)
    record = _run(ag.run(BIZ, [{"id": "e1", "event_type": "booking_created", "contact_id": "c1",
                                "created_at": "2026-09-04T10:00:00Z", "data": {}}]))
    assert order == ["plan", "act", "door"], "the plan is written before any action"
    assert record["reasoning"].startswith("Ada booked Thursday") and record["idle"] is False
    assert record["actions"] == ["create_note"]


def test_a_plan_that_says_nothing_skips_the_act_call(monkeypatch):
    import chief_agent as ag
    calls = []

    async def fake_claude(client, system, messages, **kw):
        calls.append(bool(kw.get("read_tools")))
        return "Nothing to do: the payment is already recorded and the client has no open items."
    monkeypatch.setattr(cos, "_call_claude", fake_claude)

    async def _digest(bid):
        return []
    monkeypatch.setattr(ol, "digest_async", _digest)

    async def _trace(*a, **k):
        return None
    monkeypatch.setattr(ag, "_leave_trace", _trace)
    record = _run(ag.run(BIZ, [{"id": "e1", "event_type": "payment_received", "data": {}}]))
    assert calls == [False] and record["idle"] is True and record["actions"] == []
    assert record["recap"].startswith("Nothing to do")


def test_both_traces_write_the_ledger(monkeypatch):
    import chief_agent as ag
    import chief_assignments as ca
    written = []
    monkeypatch.setattr(ol, "record_moves", lambda bid, surface, taken, assignment_id=None:
                        written.append((bid, surface, [t["type"] for t in taken], assignment_id)) or len(taken))

    async def _act(client, **kw):
        return None
    monkeypatch.setattr(cos, "_log_chief_activity", _act)

    async def _sb(client, method, path, body=None):
        return [{}]
    monkeypatch.setattr(cos, "_sb", _sb)
    import audit_log
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: True)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer=None: [])
    taken = [{"type": "create_task", "result": "added", "label": "Task", "task_id": "t-1"}]
    _run(ag._leave_trace(None, BIZ, taken, {
        "business_id": "biz-1", "events": ["booking_created"], "actions": ["create_task"], "failed": [],
        "recap": "r", "reasoning": "plan", "idle": False, "tags_ignored": 0, "duration_ms": 1}))
    _run(ca._leave_trace(None, BIZ, taken, {
        "business_id": "biz-1", "assignment_id": "a-1", "title": "Fill Thursday", "reasoning": "plan",
        "idle": False, "actions": ["create_task"], "proposed": [], "failed": [], "recap": "r",
        "tags_ignored": 0, "duration_ms": 1}))
    assert written == [("biz-1", "agent", ["create_task"], None),
                       ("biz-1", "assignment", ["create_task"], "a-1")]


def test_the_door_is_owner_only(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"id": "biz-1", "owner_id": "own-1"}])

    class U:
        id = "stranger"
    with pytest.raises(HTTPException) as e:
        ol.outcomes("biz-1", 30, U())
    assert e.value.status_code == 403
