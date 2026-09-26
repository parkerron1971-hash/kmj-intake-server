"""Chief can read the task list back (2026-09-26).

Asked "what tasks are due this week?", Chief opened the Tasks tab and said
it had no way to read the list: its context carries no tasks and no read
existed. list_tasks is that read. No live services."""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

import action_registry
import chief_assignments
import chief_of_staff as cos
import chief_tool_loop as ctl

BIZ = {"id": "b-1", "name": "Test Coach"}
TODAY = date(2026, 9, 26)


@pytest.fixture
def records(monkeypatch):
    calls = []
    tasks = [
        {"id": "t1", "title": "Call Ada", "due_date": "2026-09-24", "priority": "high", "status": "todo", "contact_id": "c-ada"},
        {"id": "t2", "title": "Prep the room", "due_date": "2026-09-30", "priority": "medium", "status": "todo", "contact_id": None},
    ]

    async def sb(client, method, path, body=None):
        calls.append(path)
        if path.startswith("/tasks?"):
            return tasks
        if path.startswith("/contacts?"):
            return [{"id": "c-ada", "name": "Ada Lovelace"}]
        return []

    class Day(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 26, 15, 0, tzinfo=tz or timezone.utc)
    monkeypatch.setattr(cos, "_sb", sb)
    monkeypatch.setattr(cos, "datetime", Day)
    monkeypatch.setattr(chief_assignments, "_tz_for", lambda bid: timezone.utc)
    return calls


def test_this_week_reads_open_tasks_due_in_the_next_seven_days(records):
    out = asyncio.run(cos.handle_list_tasks(None, BIZ, {}))
    q = records[0]
    assert "status=neq.done" in q and f"due_date=lte.{(TODAY + timedelta(days=6)).isoformat()}" in q
    assert out["result"].startswith("2 tasks due in the next seven days or overdue")
    first = out["tasks"][0]
    assert first == {**first, "title": "Call Ada", "overdue": True, "contact": "Ada Lovelace", "priority": "high"}
    assert "- Call Ada: due 2026-09-24 (overdue), Ada Lovelace, high priority" in out["summary"]
    assert "+" not in q


@pytest.mark.parametrize("due,part", [("overdue", "due_date=lt.2026-09-26"), ("today", "due_date=eq.2026-09-26"),
                                      ("all", None), ("nonsense", "due_date=lte.2026-10-02")])
def test_each_window_asks_for_its_own_days(records, due, part):
    asyncio.run(cos.handle_list_tasks(None, BIZ, {"due": due}))
    q = records[0]
    assert (part in q) if part else ("due_date=" not in q)


def test_an_unreadable_list_is_a_failure_not_an_empty_week(monkeypatch):
    async def down(client, method, path, body=None):
        return None
    monkeypatch.setattr(cos, "_sb", down)
    monkeypatch.setattr(chief_assignments, "_tz_for", lambda bid: timezone.utc)
    out = asyncio.run(cos.handle_list_tasks(None, BIZ, {}))
    assert cos._action_failed(out) and "0 tasks" not in out["label"]


def test_chief_can_call_it_mid_turn_as_a_read():
    assert action_registry.is_read_only("list_tasks") and not action_registry.is_sensitive("list_tasks")
    names = {t["name"] for t in ctl.read_tool_definitions()}
    assert "list_tasks" in names
    assert cos.ACTION_HANDLERS["list_tasks"] is cos.handle_list_tasks
