"""
test_undo_create_task.py — "undo that task" takes the task back (2026-09-14).

create_task was refused an inverse because no delete verb existed. Kevin
asked to undo a task Chief had just created; undo said "nothing to
undo" and the model then told him the task had never been created while
it sat on his list. Now: delete_task exists (scoped to a fresh, open
task in this business), create_task maps to it, and an empty undo log
says plainly that it is not evidence of nothing having happened.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import action_inverse as ai
import action_registry
import chief_of_staff as cos
import chief_undo_actions as undo


def test_create_task_is_undoable_when_the_id_came_back():
    assert ai.can_undo("create_task")
    assert "create_task" in ai.undoable_verbs()
    inv = ai.build_inverse("create_task", {"title": "Call the bank"}, {"task_id": "t-1"})
    assert inv == {"type": "delete_task", "task_id": "t-1"}
    assert ai.build_inverse("create_task", {"title": "Call the bank"}, {}) is None
    assert "task" in ai.describe("create_task")


def test_delete_task_is_class_a_and_handled():
    assert action_registry.effect("delete_task") == action_registry.WRITE
    assert "delete_task" in cos.ACTION_HANDLERS


def _fake_sb(rows, calls):
    async def sb(client, method, path, body=None):
        calls.append((method, path))
        if method == "GET":
            return rows
        return []
    return sb


def test_delete_task_removes_a_fresh_open_task(monkeypatch):
    calls = []
    fresh = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    monkeypatch.setattr(cos, "_sb", _fake_sb([{"id": "t-1", "title": "Call the bank", "status": "todo", "created_at": fresh}], calls))
    res = asyncio.run(cos.handle_delete_task(None, {"id": "biz-1"}, {"task_id": "t-1"}))
    assert not cos._action_failed(res)
    assert "Call the bank" in res["label"]
    assert any(m == "DELETE" and "id=eq.t-1" in p and "business_id=eq.biz-1" in p for m, p in calls)


def test_delete_task_refuses_done_old_or_missing(monkeypatch):
    calls = []
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    monkeypatch.setattr(cos, "_sb", _fake_sb([{"id": "t-1", "title": "x", "status": "todo", "created_at": old}], calls))
    res = asyncio.run(cos.handle_delete_task(None, {"id": "biz-1"}, {"task_id": "t-1"}))
    assert cos._action_failed(res) and "older than a day" in res["result"]
    monkeypatch.setattr(cos, "_sb", _fake_sb([{"id": "t-1", "title": "x", "status": "done", "created_at": old}], calls))
    res = asyncio.run(cos.handle_delete_task(None, {"id": "biz-1"}, {"task_id": "t-1"}))
    assert cos._action_failed(res) and "already done" in res["result"]
    monkeypatch.setattr(cos, "_sb", _fake_sb([], calls))
    res = asyncio.run(cos.handle_delete_task(None, {"id": "biz-1"}, {"task_id": "t-9"}))
    assert cos._action_failed(res)
    res = asyncio.run(cos.handle_delete_task(None, {"id": "biz-1"}, {}))
    assert cos._action_failed(res)
    assert not any(m == "DELETE" for m, _ in calls), "no refusal deletes anything"


def test_the_door_records_a_created_task_as_undoable(monkeypatch):
    posted = []
    as_user = []

    async def sb(client, method, path, body=None):
        posted.append((method, path, body))
        return []

    async def user_sb(client, method, path, body=None):
        as_user.append((method, path))
        return None  # what RLS makes of a user-token INSERT on this table

    monkeypatch.setattr(cos, "_sb_service", sb)
    monkeypatch.setattr(cos, "_sb", user_sb)
    asyncio.run(cos._record_undoable(None, {"id": "biz-1", "owner_id": "u1"}, "create_task",
                                     {"title": "Call the bank"},
                                     {"type": "create_task", "result": "added", "task_id": "t-1"}))
    assert any(m == "POST" and p == "/chief_undo_log" and b["action_type"] == "create_task" for m, p, b in posted)
    # chief_undo_log has an owner SELECT policy and nothing else; a write
    # under the practitioner's token is refused and swallowed, which is how
    # the log stayed empty for six weeks. The row is the server's own
    # record and is written as the server.
    assert not as_user, "the undo log is never written under the user token"


def test_undo_log_writes_go_through_the_service_role(monkeypatch):
    import sb_clients
    seen = []

    async def as_service(client, method, path, body=None):
        seen.append((method, path))
        return [{"id": "u-1"}]

    monkeypatch.setattr(sb_clients, "sb_as_service", as_service)
    asyncio.run(cos._sb_service(None, "POST", "/chief_undo_log", {"x": 1}))
    assert seen == [("POST", "/chief_undo_log")]


def test_undo_row_marks_undone_as_the_server(monkeypatch):
    calls = []

    async def service_sb(client, method, path, body=None):
        calls.append(("service", method, path))
        return []

    async def user_sb(client, method, path, body=None):
        calls.append(("user", method, path))
        return None

    async def ok_inverse(client, biz, action):
        return {"type": "delete_task", "result": "removed", "nav": None}

    monkeypatch.setattr(cos, "_sb_service", service_sb)
    monkeypatch.setattr(cos, "_sb", user_sb)
    monkeypatch.setitem(cos.ACTION_HANDLERS, "delete_task", ok_inverse)
    row = {"id": "u1", "action_type": "create_task", "action_json": {"title": "x"},
           "result_json": {"task_id": "t1"}}
    res = asyncio.run(undo.undo_row(None, {"id": "biz-1"}, row))
    assert not res.get("failed")
    assert ("service", "PATCH", "/chief_undo_log?id=eq.u1") in calls
    assert not any(w == "user" and m == "PATCH" for w, m, _ in calls)


def test_the_prompt_forbids_it_never_happened():
    import chief_prompt
    src = pathlib.Path(chief_prompt.__file__).read_text(encoding="utf-8")
    assert "NEVER say an earlier action did not happen" in src


def test_an_empty_undo_log_does_not_read_as_nothing_happened(monkeypatch):
    async def none(client, biz):
        return None

    monkeypatch.setattr(undo, "_most_recent", none)
    res = asyncio.run(undo.handle_undo_last(None, {"id": "biz-1"}, {}))
    assert "not the same as nothing having happened" in res["result"]
    assert "Do not tell the practitioner an action did not happen" in res["result"]
    res = asyncio.run(undo.handle_what_undo(None, {"id": "biz-1"}, {}))
    assert "not the same as nothing having happened" in res["result"]
