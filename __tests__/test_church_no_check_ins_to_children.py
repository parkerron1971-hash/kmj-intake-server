"""No automated check-in goes to a church's children, and check-ins don't swamp Approvals.

The Renee run on the test church (2026-11-06) found 18 "Checking in" drafts for
about 20 people, one of them a 10-year-old: "I've been thinking about you".
It sent nothing only because the child had no email on file.

  1. A child by any sign (on a family as a child, under 18 by birthdate, or
     tagged so) gets no draft, from the sweep or from the weekly briefing.
  2. A failed read of who is a child stops the check-ins; it never reads as
     "no children".
  3. A church keeps at most five check-ins waiting, and asks nothing while
     Approvals is full.
  4. At a church, someone with no interaction on record hasn't gone quiet.
  5. Other businesses' sweeps are unchanged.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import church_families  # noqa: E402
import church_roll  # noqa: E402
import growth_engine  # noqa: E402
import nurture_agent  # noqa: E402

CHURCH = {"id": "biz1", "name": "Grace", "type": "church", "settings": {}}
SALON = {"id": "biz1", "name": "MaC Hair", "type": "personal_services", "settings": {}}


def _person(cid, **kw):
    return {"id": cid, "name": cid.title(), "metadata": {}, "tags": [], "birthdate": None, **kw}


ADULT = _person("adult")
ON_A_FAMILY = _person("jordan")
BY_BIRTHDATE = _person("kid", birthdate="2016-01-01")
TAGGED = _person("teen", tags=["Youth"])
GROWN = _person("grown", birthdate="1990-01-01")


# ─── the reads ────────────────────────────────────────────────────────

@pytest.mark.parametrize("row,want", [(ON_A_FAMILY, True), (BY_BIRTHDATE, True), (TAGGED, True),
                                      (ADULT, False), (GROWN, False)])
def test_a_child_by_any_sign(row, want):
    assert church_families.is_minor(row, {"jordan"}) is want


def test_an_unreadable_birthdate_or_odd_tags_are_not_a_crash():
    assert church_families.is_minor({"id": "x", "birthdate": "soon", "tags": None}, set()) is False


def test_the_roll_reads_the_same_tags():
    assert church_roll.MINOR_TAGS is church_families.MINOR_TAGS


def test_a_failed_children_read_is_unknown(monkeypatch):
    monkeypatch.setattr(church_families, "_rows", lambda path: None)
    assert church_families.minor_ids("biz1") is None


def test_the_children_read_lower_cases_ids(monkeypatch):
    monkeypatch.setattr(church_families, "_rows", lambda path: [{"contact_id": "ABC"}])
    assert church_families.minor_ids("biz1") == {"abc"}


# ─── the sweep ────────────────────────────────────────────────────────

def _sweep(monkeypatch, biz=CHURCH, people=(), waiting=0, minors=frozenset(), waiting_fails=False):
    drafted, reads = [], []

    async def _sb(client, method, path, body=None):
        reads.append(path)
        if method == "GET" and path.startswith("/contacts") and "status=in." in path:
            return [dict(p) for p in people]
        if method == "GET" and path.startswith("/agent_queue?business_id="):
            return None if waiting_fails else [{"id": f"q{i}"} for i in range(waiting)]
        return []

    async def one(client, business, contact, events, **kw):
        drafted.append(contact["id"])
        return {"ai_reasoning": "quiet for a while"}

    monkeypatch.setattr(nurture_agent, "_sb", _sb)
    monkeypatch.setattr(nurture_agent, "_nurture_one_contact", one)
    monkeypatch.setattr(church_families, "minor_ids", lambda biz: None if minors is None else set(minors))
    asyncio.run(nurture_agent._run_nurture(None, dict(biz)))
    return drafted, reads


def _quiet_read(reads):
    return next(p for p in reads if p.startswith("/contacts") and "status=in." in p)


def test_the_sweep_skips_every_child(monkeypatch):
    drafted, _ = _sweep(monkeypatch, people=[ON_A_FAMILY, BY_BIRTHDATE, TAGGED, ADULT, GROWN], minors={"jordan"})
    assert drafted == ["adult", "grown"]


def test_a_failed_read_of_children_drafts_nothing(monkeypatch):
    drafted, reads = _sweep(monkeypatch, people=[ADULT], minors=None)
    assert drafted == []
    assert not any("status=in." in p for p in reads)


def test_a_failed_read_of_what_is_waiting_drafts_nothing(monkeypatch):
    drafted, _ = _sweep(monkeypatch, people=[ADULT], waiting_fails=True)
    assert drafted == []


def test_five_wait_at_most(monkeypatch):
    people = [_person(f"p{i}") for i in range(12)]
    drafted, _ = _sweep(monkeypatch, people=people)
    assert len(drafted) == nurture_agent.CHURCH_WAITING_CHECK_INS == 5


def test_a_child_does_not_use_up_a_place(monkeypatch):
    people = [BY_BIRTHDATE, TAGGED] + [_person(f"p{i}") for i in range(6)]
    drafted, _ = _sweep(monkeypatch, people=people)
    assert drafted == ["p0", "p1", "p2", "p3", "p4"]


def test_only_the_room_left_is_filled(monkeypatch):
    drafted, _ = _sweep(monkeypatch, people=[_person(f"p{i}") for i in range(6)], waiting=3)
    assert drafted == ["p0", "p1"]


def test_a_full_table_asks_for_nobody(monkeypatch):
    drafted, reads = _sweep(monkeypatch, people=[ADULT], waiting=5)
    assert drafted == []
    assert not any("status=in." in p for p in reads)


def test_nobody_with_no_interaction_counts_as_quiet_at_a_church(monkeypatch):
    _, reads = _sweep(monkeypatch, people=[ADULT])
    read = _quiet_read(reads)
    assert "last_interaction=lt." in read and "last_interaction.is.null" not in read


def test_another_business_keeps_its_sweep(monkeypatch):
    people = [BY_BIRTHDATE] + [_person(f"p{i}") for i in range(7)]
    drafted, reads = _sweep(monkeypatch, biz=SALON, people=people, minors=None)
    assert len(drafted) == 8
    assert "last_interaction.is.null" in _quiet_read(reads)
    assert not any(p.startswith("/agent_queue?business_id=") for p in reads)


# ─── the weekly briefing ──────────────────────────────────────────────

def _briefing(monkeypatch, biz=CHURCH, people=(), minors=frozenset()):
    drafted, reads = [], []

    async def _sb(client, method, path, body=None):
        reads.append(path)
        if method == "GET" and path.startswith("/contacts?") and "health_score=lt.40" in path:
            return [dict(p, health_score=20) for p in people]
        if method == "POST" and path == "/agent_queue":
            drafted.append(body["contact_id"])
            return [{"id": "q1"}]
        return []

    async def draft(client, b, contact, kind):
        return {"subject": "Checking in", "body": "Hello", "reasoning": "quiet"}

    async def no_existing(*a, **k):
        return None

    monkeypatch.setattr(growth_engine, "_sb", _sb)
    monkeypatch.setattr(growth_engine, "_draft_nurture_check_in", draft)
    monkeypatch.setattr(growth_engine, "_existing_draft", no_existing)
    monkeypatch.setattr(church_families, "minor_ids", lambda biz: None if minors is None else set(minors))
    asyncio.run(growth_engine._generate_briefing_actions(None, dict(biz)))
    return drafted, reads


def test_the_briefing_skips_every_child(monkeypatch):
    drafted, reads = _briefing(monkeypatch, people=[ON_A_FAMILY, BY_BIRTHDATE, TAGGED, ADULT], minors={"jordan"})
    assert drafted == ["adult"]
    assert "birthdate,tags" in next(p for p in reads if "health_score=lt.40" in p)


def test_a_failed_read_stops_the_briefings_check_ins(monkeypatch):
    drafted, reads = _briefing(monkeypatch, people=[ADULT], minors=None)
    assert drafted == []
    assert not any("health_score=lt.40" in p for p in reads)


def test_another_businesss_briefing_is_unchanged(monkeypatch):
    drafted, _ = _briefing(monkeypatch, biz=SALON, people=[BY_BIRTHDATE, ADULT], minors=None)
    assert drafted == ["kid", "adult"]
