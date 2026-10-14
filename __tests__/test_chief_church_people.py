"""
test_chief_church_people.py — Chief can read a church's people.

Before this Chief read sermons and giving statements and nothing else a
church records, so "who's drifting from their group?" got a guess. These
pin the readers (group drift, services) and the one gate that matters:
care and children's numbers only for the owner or a manager, and never
for a caller nobody signed in as.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import action_registry
import chief_church_actions as A
import church_reads as C
import mcp_server

BIZ = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
G1 = "99999999-0000-0000-0000-000000000001"
ANNA, BEN, CARA = ("aaaaaaaa-0000-0000-0000-00000000000a",
                   "bbbbbbbb-0000-0000-0000-00000000000b",
                   "cccccccc-0000-0000-0000-00000000000c")


class FakeDB:
    def __init__(self, tables):
        self.tables = tables
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        table = path.split("?", 1)[0].strip("/")
        rows = self.tables.get(table, [])
        return None if rows is None else list(rows)


@pytest.fixture
def db(monkeypatch):
    def install(**tables):
        fake = FakeDB(tables)
        import sb_clients
        monkeypatch.setattr(sb_clients, "sb_get_as_service", fake)
        return fake
    return install


def _meeting(n, day):
    return {"id": f"m{n}", "group_id": G1, "met_on": day}


# Newest first, as the query orders them.
MEETINGS = [_meeting(4, "2026-10-12"), _meeting(3, "2026-10-05"),
            _meeting(2, "2026-09-28"), _meeting(1, "2026-09-21")]


def _group_tables(**over):
    t = dict(
        groups=[{"id": G1, "name": "Tuesday Women"}],
        group_members=[{"group_id": G1, "contact_id": ANNA, "joined_on": "2026-08-01"},
                       {"group_id": G1, "contact_id": BEN, "joined_on": "2026-08-01"},
                       {"group_id": G1, "contact_id": CARA, "joined_on": "2026-10-01"}],
        group_meetings=MEETINGS,
        # Anna came to everything; Ben came only to the first; Cara joined
        # during the run and missed some.
        group_meeting_attendance=[{"meeting_id": m, "contact_id": ANNA} for m in ("m1", "m2", "m3", "m4")]
        + [{"meeting_id": "m1", "contact_id": BEN}],
        contacts=[{"id": BEN, "name": "Ben Ortiz"}],
    )
    t.update(over)
    return t


def test_a_member_who_missed_the_last_three_meetings_is_drifting(db):
    db(**_group_tables())
    g = C.group_drift(BIZ, now=NOW)
    assert [d["name"] for d in g["drifting"]] == ["Ben Ortiz"]
    assert g["drifting"][0]["last_came"] == "2026-09-21"
    assert g["groups"][0]["members"] == 3 and g["groups"][0]["meetings"] == 4


def test_someone_who_joined_during_the_run_is_not_drifting(db):
    db(**_group_tables())
    assert CARA not in {d["contact_id"] for d in C.group_drift(BIZ, now=NOW)["drifting"]}


def test_a_group_with_too_few_meetings_flags_nobody(db):
    db(**_group_tables(group_meetings=MEETINGS[:2]))
    assert C.group_drift(BIZ, now=NOW)["drifting"] == []


def test_group_reads_are_pinned_and_a_failure_is_none(db):
    fake = db(**_group_tables())
    C.group_drift(BIZ, now=NOW)
    assert all(f"business_id=eq.{BIZ}" in c for c in fake.calls)
    db(**_group_tables(group_members=None))
    assert C.group_drift(BIZ, now=NOW) is None


def test_services_split_in_person_online_and_counted(db):
    at = (NOW - timedelta(days=3)).isoformat()
    db(attendance=[{"entry_id": "e1", "method": "staff", "first_time": True, "checked_in_at": at},
                   {"entry_id": "e1", "method": "online", "first_time": False, "checked_in_at": at},
                   {"entry_id": "e1", "method": "station", "first_time": False, "checked_in_at": at}],
       attendance_headcounts=[{"entry_id": "e1", "area": "Main service", "count": 80, "updated_at": at},
                              {"entry_id": "e1", "area": "Online", "count": 25, "updated_at": at}],
       module_entries=[{"id": "e1", "data": {"title": "Sunday Service"}}])
    s = C.services(BIZ, now=NOW)
    assert s == [{"entry_id": "e1", "in_person": 2, "online": 1, "first_time": 1,
                  "headcount": 105, "areas": {"Main service": 80, "Online": 25},
                  "title": "Sunday Service", "date": "2026-10-11"}]


def test_care_counts_are_numbers_only(db):
    db(ministry_care_requests=[
        {"status": "new", "created_at": (NOW - timedelta(days=5)).isoformat(), "prayed_at": None},
        {"status": "reviewed", "created_at": (NOW - timedelta(days=9)).isoformat(),
         "prayed_at": NOW.isoformat()}],
       child_checkins=[{"entry_id": "e1", "checked_in_at": (NOW - timedelta(days=3)).isoformat()}])
    fake_calls = C.care_counts(BIZ, now=NOW)
    assert fake_calls["care"] == {"new": 1, "reviewed": 1, "closed": 0, "prayed": 1,
                                  "oldest_new_days": 5}
    assert fake_calls["children_checked_in"] == [{"date": "2026-10-11", "children": 1}]


def test_care_never_selects_words_or_names(db):
    fake = db(ministry_care_requests=[], child_checkins=[])
    C.care_counts(BIZ, now=NOW)
    for c in fake.calls:
        sel = c.split("select=", 1)[1]
        for private in ("submission", "child_id", "name", "notes"):
            assert private not in sel


# ─── Chief's verb ────────────────────────────────────────────────────

def _run(action, monkeypatch, role=None, uid="user-1"):
    import chief_of_staff
    token = chief_of_staff._TURN_USER_ID.set(uid)
    monkeypatch.setattr(A, "_caller_role", lambda biz: role)
    try:
        return asyncio.run(A.handle_church_people(None, {"id": BIZ}, action))
    finally:
        chief_of_staff._TURN_USER_ID.reset(token)


@pytest.mark.parametrize("role", [None, "viewer", "member"])
def test_care_is_refused_below_manager(role, monkeypatch, db):
    fake = db(ministry_care_requests=[], child_checkins=[])
    out = _run({"section": "care"}, monkeypatch, role=role)
    assert out["result"].startswith("refused")
    assert out["label"]
    assert not fake.calls  # nothing was even read


@pytest.mark.parametrize("role", ["owner", "admin", "manager"])
def test_care_is_counts_for_owner_and_managers(role, monkeypatch, db):
    db(ministry_care_requests=[], child_checkins=[])
    out = _run({"section": "care"}, monkeypatch, role=role)
    assert "0 new" in out["result"] and out["label"]


def test_no_signed_in_caller_means_no_role(monkeypatch):
    import chief_of_staff
    token = chief_of_staff._TURN_USER_ID.set("")
    try:
        assert A._caller_role(BIZ) is None
    finally:
        chief_of_staff._TURN_USER_ID.reset(token)


def test_overview_answers_all_three_questions(monkeypatch, db):
    db(**_group_tables(), attendance=[], attendance_headcounts=[])
    out = _run({}, monkeypatch, role="member")
    text = out["result"]
    assert "First-time guests" in text and "Drifting" in text and "Ben Ortiz" in text
    assert "Attendance" in text
    assert out["label"] == "Church people"


def test_a_failed_read_is_a_failure_not_a_zero(monkeypatch, db):
    db(attendance=None)
    out = _run({"section": "first_time"}, monkeypatch)
    assert out["result"].startswith("failed")


def test_an_unknown_section_fails(monkeypatch, db):
    db()
    assert _run({"section": "kids"}, monkeypatch)["result"].startswith("failed")


# ─── registration ────────────────────────────────────────────────────

def test_registered_as_a_read_chief_can_call_mid_turn():
    import chief_of_staff
    assert chief_of_staff.ACTION_HANDLERS["church_people"] is A.handle_church_people
    assert action_registry.effect("church_people") == action_registry.READ
    assert "church_people" in mcp_server.TOOL_SCHEMAS
    import chief_tool_loop
    assert "church_people" in {t["name"] for t in chief_tool_loop.read_tool_definitions()}
