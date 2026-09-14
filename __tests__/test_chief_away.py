"""
test_chief_away.py — while you were away (2026-09-13).

The Chat Mode rest screen shows what Chief did since the practitioner
last looked, each with a way back where one exists. Nothing new is
stored: chief_activity's unseen recap is joined to chief_undo_log by
verb and moment. Tested as arithmetic (the join), as a contract (the
routes exist and are gated), and as behaviour (undo_row keeps a row
undoable when the inverse fails).
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import chief_undo_actions as undo


def test_undo_pointers_attach_by_verb_and_moment_once():
    activity = [
        {"id": "a1", "action_type": "create_task", "created_at": "2026-09-13T20:00:00Z"},
        {"id": "a2", "action_type": "create_task", "created_at": "2026-09-13T20:00:03Z"},
        {"id": "a3", "action_type": "send_sms", "created_at": "2026-09-13T20:01:00Z"},
        {"id": "a4", "action_type": "navigate", "created_at": "2026-09-13T20:02:00Z"},
    ]
    undo_rows = [
        {"id": "u1", "action_type": "create_task", "created_at": "2026-09-13T20:00:01Z", "status": "undoable"},
        {"id": "u2", "action_type": "create_task", "created_at": "2026-09-13T20:00:04Z", "status": "undoable"},
        {"id": "u3", "action_type": "send_sms", "created_at": "2026-09-13T20:00:10Z", "status": "undoable"},   # 50s off
        {"id": "u4", "action_type": "create_task", "created_at": "2026-09-13T19:00:00Z", "status": "undone"},
    ]
    out = cos.attach_undo_pointers(activity, undo_rows)
    by = {o["id"]: o for o in out}
    assert by["a1"]["undo_id"] == "u1" and by["a1"]["undo_describe"]
    assert by["a2"]["undo_id"] == "u2"
    assert "undo_id" not in by["a3"], "a text recorded 50s away is not this one"
    assert "undo_id" not in by["a4"]
    # the activity rows come back whole and in order
    assert [o["id"] for o in out] == ["a1", "a2", "a3", "a4"]
    # bad timestamps never raise
    assert cos.attach_undo_pointers([{"id": "x", "action_type": "create_task", "created_at": "nope"}], undo_rows)[0]["id"] == "x"


def test_within_window_reads_the_row_clock():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 9, 13, 22, 0, tzinfo=timezone.utc)
    assert undo.within_window({"created_at": "2026-09-13T20:00:00Z"}, now)
    assert not undo.within_window({"created_at": (now - timedelta(hours=25)).isoformat()}, now)
    assert not undo.within_window({"created_at": ""}, now)


def test_undo_row_keeps_the_row_undoable_when_the_inverse_fails(monkeypatch):
    calls = []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path, body))
        return []

    async def failing_inverse(client, biz, action):
        return {"type": "delete_task", "result": "Failed: no such task", "failed": True}

    monkeypatch.setattr(cos, "_sb", fake_sb)
    monkeypatch.setattr(cos, "_sb_service", fake_sb)
    monkeypatch.setitem(cos.ACTION_HANDLERS, "delete_task", failing_inverse)
    import action_inverse
    monkeypatch.setattr(action_inverse, "build_inverse",
                        lambda verb, a, r: {"type": "delete_task", "task_id": "t1"})
    row = {"id": "u1", "action_type": "create_task", "action_json": {}, "result_json": {"task_id": "t1"}}
    res = asyncio.run(undo.undo_row(None, {"id": "biz-1"}, row))
    assert res["failed"] is True
    assert not any(m == "PATCH" for m, _, _ in calls), "a failed undo must not mark the row undone"


def test_undo_row_marks_the_row_undone_after_the_inverse_ran(monkeypatch):
    calls = []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path, body))
        return []

    async def ok_inverse(client, biz, action):
        return {"type": "delete_task", "result": "removed task t1", "nav": None}

    monkeypatch.setattr(cos, "_sb", fake_sb)
    monkeypatch.setattr(cos, "_sb_service", fake_sb)
    monkeypatch.setitem(cos.ACTION_HANDLERS, "delete_task", ok_inverse)
    import action_inverse
    monkeypatch.setattr(action_inverse, "build_inverse",
                        lambda verb, a, r: {"type": "delete_task", "task_id": "t1"})
    row = {"id": "u1", "action_type": "create_task", "action_json": {}, "result_json": {"task_id": "t1"}}
    res = asyncio.run(undo.undo_row(None, {"id": "biz-1"}, row))
    assert not res.get("failed")
    patches = [(p, b) for m, p, b in calls if m == "PATCH"]
    assert patches and "chief_undo_log?id=eq.u1" in patches[0][0]
    assert patches[0][1]["status"] == "undone"


def test_away_routes_exist_and_need_a_session():
    by_path = {}
    for r in cos.router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "GET" in by_path.get("/agents/chief/away", set())
    assert "POST" in by_path.get("/agents/chief/undo/{undo_id}", set())
    from auth_supabase import require_user_session
    for r in cos.router.routes:
        if r.path in ("/agents/chief/away", "/agents/chief/undo/{undo_id}"):
            deps = [d.call for d in r.dependant.dependencies]
            assert require_user_session in deps, f"{r.path} is missing require_user_session"


def test_undo_route_rejects_a_bad_id_before_touching_the_database():
    from fastapi import HTTPException
    import pytest

    class S:
        token = "t"

        class user:
            id = "u"

    with pytest.raises(HTTPException) as e:
        asyncio.run(cos.chief_undo_row("not-a-uuid", cos._UndoRowRequest(business_id="b"), S()))
    assert e.value.status_code == 400
