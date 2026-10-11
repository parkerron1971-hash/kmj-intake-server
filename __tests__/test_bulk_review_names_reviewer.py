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
    marked = []

    async def _query(client, biz_id, filter_str):
        return [dict(r) for r in ROWS]

    async def _sb(client, method, path, body=None):
        return []

    monkeypatch.setattr(cos, "_query_queue_by_filter", _query)
    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(turn_linkage, "mark_reviewed",
                        lambda qid, uid: marked.append((qid, uid)) or True)
    return marked


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
