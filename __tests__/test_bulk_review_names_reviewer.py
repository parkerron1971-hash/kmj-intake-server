"""A sweep through the queue records who did it, like a single approval does.

Layer Two (2026-10-11) added agent_queue.reviewed_by so a lesson can be traced
to the person who approved or dismissed a draft. The single-row paths set it;
"approve all" and "dismiss all" did not, so a sweep left every row it touched
with nobody's name on it.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncio

import pytest

import chief_of_staff as cos
import turn_linkage

BIZ = {"id": "biz1", "name": "Test Co", "owner_id": "u1", "settings": {}}
ROWS = [{"id": "q1", "business_id": "biz1", "status": "draft", "subject": "One"},
        {"id": "q2", "business_id": "biz1", "status": "draft", "subject": "Two"}]


@pytest.fixture
def queue(monkeypatch):
    marked = _Marked()

    async def _query(client, biz_id, filter_str):
        return [dict(r) for r in ROWS]

    async def _sb(client, method, path, body=None):
        if method == "GET":
            return [dict(ROWS[0])]
        if method == "PATCH" and any(f"id=eq.{q}" in path for q in queue_failing):
            return None
        return [{"id": path.split("id=eq.")[-1]}]

    queue_failing = set()

    monkeypatch.setattr(cos, "_query_queue_by_filter", _query)
    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(turn_linkage, "mark_reviewed",
                        lambda qid, uid: marked.append((qid, uid)) or True)
    marked.failing = queue_failing
    return marked


class _Marked(list):
    pass


def _as_user(coro, uid="user-7"):
    async def go():
        token = cos._TURN_USER_ID.set(uid)
        try:
            return await coro
        finally:
            cos._TURN_USER_ID.reset(token)
    return asyncio.run(go())


def test_bulk_dismiss_names_the_reviewer_on_every_row(queue):
    res = _as_user(cos.handle_bulk_dismiss(None, BIZ, {"filter": "all"}))
    assert res["result"] == "dismissed 2 of 2"
    assert queue == [("q1", "user-7"), ("q2", "user-7")]


def test_bulk_approve_names_the_reviewer_only_on_rows_it_approved(queue, monkeypatch):
    async def _approve(client, biz, item, **kw):
        if item["id"] == "q2":
            return {"ok": False, "sent": False, "reason": "blocked"}
        return {"ok": True, "sent": True}

    monkeypatch.setattr(cos, "_do_approve_one", _approve)
    res = _as_user(cos.handle_bulk_approve(None, BIZ, {"filter": "all"}))
    assert "approved 1 of 2" in res["result"]
    assert queue == [("q1", "user-7")], "a held row was not reviewed"


def test_a_sweep_with_no_person_on_the_turn_names_nobody(queue):
    res = _as_user(cos.handle_bulk_dismiss(None, BIZ, {"filter": "all"}), uid=None)
    assert res["result"] == "dismissed 2 of 2"
    assert queue == []


def test_a_row_the_database_did_not_change_is_neither_counted_nor_marked(queue):
    queue.failing.add("q2")
    res = _as_user(cos.handle_bulk_dismiss(None, BIZ, {"filter": "all"}))
    assert res["result"] == "dismissed 1 of 2"
    assert queue == [("q1", "user-7")]


def test_a_single_dismiss_that_did_not_save_says_so(queue):
    queue.failing.add("q1")
    res = _as_user(cos.handle_dismiss_draft(None, BIZ, {"queue_id": "q1"}))
    assert res.get("failed") is True and "still waiting" in res["result"]
    assert queue == []


def test_a_single_dismiss_that_saved_names_the_reviewer(queue):
    res = _as_user(cos.handle_dismiss_draft(None, BIZ, {"queue_id": "q1"}))
    assert res["result"] == "dismissed"
    assert queue == [("q1", "user-7")]
