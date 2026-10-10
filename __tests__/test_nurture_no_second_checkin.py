"""
test_nurture_no_second_checkin.py — a client with a check-in waiting does not get another (2026-10-08).

A salon's Approvals held 40 "Checking in" drafts: the nurture sweep drafted
one for each of 20 quiet clients on 2026-09-16 and, with all 20 still
waiting, a second for each on 09-30. Its only guard was "nothing drafted in
the last 7 days". Chief read the first 10 rows, told her to review "the 10
check-in drafts", and the answer check held that answer back three times.

The growth engine's guard had the same window and never ran at all: its
cutoff went into the query as '+00:00', which PostgREST reads as a space,
and every check came back 400 and found nothing.

A nurture draft still waiting, of any age, now blocks a new one; the
cooldown after a sent check-in is unchanged.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import growth_engine  # noqa: E402
import nurture_agent  # noqa: E402

BIZ = {"id": "biz1", "name": "MaC Hair", "type": "personal_services", "settings": {}}
KENDRICK = {"id": "c-kendrick", "name": "Kendrick", "phone": "+15555550101", "metadata": {}}
SHERYL = {"id": "c-sheryl", "name": "Sheryl", "phone": "+15555550102", "metadata": {}}


def _sweep(monkeypatch, waiting):
    """Run the nurture sweep where `waiting` holds the contact ids that
    already have a nurture draft in Approvals. Returns (drafted, guards)."""
    drafted, guards = [], []

    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/contacts") and "status=in." in path:
            return [dict(KENDRICK), dict(SHERYL)]
        if method == "GET" and path.startswith("/agent_queue?contact_id=eq."):
            guards.append(path)
            cid = path.split("contact_id=eq.", 1)[1].split("&", 1)[0]
            return [{"id": "q-old"}] if cid in waiting else []
        return []

    async def one(client, business, contact, events, **kw):
        drafted.append(contact["id"])
        return {"ai_reasoning": "quiet for a while"}

    monkeypatch.setattr(nurture_agent, "_sb", _sb)
    monkeypatch.setattr(nurture_agent, "_nurture_one_contact", one)
    asyncio.run(nurture_agent._run_nurture(None, dict(BIZ)))
    return drafted, guards


def test_a_waiting_check_in_blocks_a_second(monkeypatch):
    drafted, _ = _sweep(monkeypatch, waiting={"c-kendrick"})
    assert drafted == ["c-sheryl"]


def test_the_guard_asks_for_a_waiting_draft_of_any_age(monkeypatch):
    _, guards = _sweep(monkeypatch, waiting=set())
    assert len(guards) == 2
    for path in guards:
        assert "agent=eq.nurture" in path
        assert "or=(status.eq.draft,created_at.gte." in path
        # The Z form: '+' would read as a space and the guard would 400.
        assert "+00:00" not in path and path.split("created_at.gte.", 1)[1].split(")", 1)[0].endswith("Z")


def test_the_growth_engine_guard_runs_and_counts_waiting_drafts():
    seen = []

    async def _sb(client, method, path, body=None):
        seen.append(path)
        return [{"id": "q-old", "created_at": "2026-09-16T11:00:49Z"}]

    original = growth_engine._sb
    growth_engine._sb = _sb
    try:
        row = asyncio.run(growth_engine._existing_draft(
            None, "biz1", "c-kendrick", "nurture", "check_in", "2026-10-01T11:00:00.123456+00:00"))
    finally:
        growth_engine._sb = original
    assert row == {"id": "q-old", "created_at": "2026-09-16T11:00:49Z"}
    (path,) = seen
    assert "or=(status.eq.draft,and(status.eq.approved,created_at.gte.2026-10-01T11:00:00.123456Z))" in path
    assert "+" not in path
