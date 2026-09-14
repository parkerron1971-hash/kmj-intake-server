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

    async def sb(client, method, path, body=None):
        posted.append((method, path, body))
        return []

    monkeypatch.setattr(cos, "_sb", sb)
    asyncio.run(cos._record_undoable(None, {"id": "biz-1", "owner_id": "u1"}, "create_task",
                                     {"title": "Call the bank"},
                                     {"type": "create_task", "result": "added", "task_id": "t-1"}))
    assert any(m == "POST" and p == "/chief_undo_log" and b["action_type"] == "create_task" for m, p, b in posted)


def test_an_empty_undo_log_does_not_read_as_nothing_happened(monkeypatch):
    async def none(client, biz):
        return None

    monkeypatch.setattr(undo, "_most_recent", none)
    res = asyncio.run(undo.handle_undo_last(None, {"id": "biz-1"}, {}))
    assert "not the same as nothing having happened" in res["result"]
    assert "Do not tell the practitioner an action did not happen" in res["result"]
    res = asyncio.run(undo.handle_what_undo(None, {"id": "biz-1"}, {}))
    assert "not the same as nothing having happened" in res["result"]
