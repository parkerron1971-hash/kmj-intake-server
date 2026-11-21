"""church_tells_rooms: a room request, its answer and a leader's yes reach the right person."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

import church_tells as ct
import church_tells_rooms as ctr

NOW = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)
BIZ = "biz 1&x"          # a value that must be quoted wherever it goes
CHURCH = {"id": BIZ, "name": "Grace Church", "owner_id": "owner", "settings": {"practitioner_name": "Pastor Kevin"}}
SEATS = [{"user_id": "naiya", "contact_id": "c-naiya", "name": "", "invited_email": "naiya@x.org"},
         {"user_id": "jess", "contact_id": None, "name": "Jess Long", "invited_email": "jess@x.org"}]
CONTACTS = [{"id": "c-naiya", "name": "Naiya Brooks"}]
SPACES = [{"id": "hall", "name": "Fellowship Hall"}, {"id": "chapel", "name": "Chapel"}]


def _b(id_, **kw):
    row = {"id": id_, "space_id": "hall", "start_at": "2026-12-05T23:00:00+00:00", "end_at": "2026-12-06T02:00:00+00:00",
           "booked_by": "naiya", "status": "requested", "series_id": None, "decided_by": None, "decided_at": None,
           "created_at": "2026-11-22T15:00:00+00:00", "notes": "PRIVATE NOTE"}
    row.update(kw)
    return row


@pytest.fixture
def db(monkeypatch):
    """Every read faked by table; records each path; a table set to None fails."""
    world = {"paths": [], "church_space_bookings": [], "business_users": SEATS, "contacts": CONTACTS,
             "church_spaces": SPACES, "church_leader_roles": [], "space_leaders": []}

    def get(path):
        world["paths"].append(path)
        got = world[path.split("?")[0].strip("/")]
        if got is None:
            return None
        return [dict(r) for r in got]
    monkeypatch.setattr(ct.sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(ctr, "_zone", lambda church: ZoneInfo("America/Chicago"))
    import church_roles
    monkeypatch.setattr(church_roles, "defs", lambda biz, **kw: [{"key": "youth_pastor", "title": "Youth Pastor"}])
    return world


def _paths(db, table):
    return [p for p in db["paths"] if p.startswith(f"/{table}?")]


def _quoted(path):
    """Every filter's business_id is the quoted church id, never raw."""
    assert f"business_id=eq.{ct.q(BIZ)}" in path
    assert BIZ not in path
    assert '"' not in path and "%22" not in path


# ─── room_asked ───────────────────────────────────────────────────────

def test_room_asked_tells_rooms_and_never_the_asker(db):
    db["church_space_bookings"] = [_b("b1")]
    items = ctr.room_asked(dict(CHURCH), NOW)
    assert len(items) == 1
    it = items[0]
    assert it.key == "room-ask:b1" and it.duty == "rooms" and it.actor == "naiya" and not it.to
    assert it.line.startswith("Naiya asked for Fellowship Hall, Sat Dec 5, 5:00 PM–8:00 PM")
    assert "PRIVATE" not in it.line + it.title
    (p,) = _paths(db, "church_space_bookings")
    _quoted(p)
    assert "status=eq.requested" in p and "booked_by=not.is.null" in p
    assert f"created_at=gte.{ct.since(NOW, 3)}" in p and f"end_at=gt.{ct.since(NOW, 0)}" in p
    assert "notes" not in p.split("&select=")[1]
    for t in ("business_users", "church_spaces", "contacts"):
        for q in _paths(db, t):
            _quoted(q)


def test_room_asked_leaves_member_app_asks_to_member_asks(db):
    # A member's ask from the app has no login (booked_by null): the read
    # filters it out, and a row that slips through is still skipped.
    db["church_space_bookings"] = [_b("m1", booked_by=None, contact_id="c-member")]
    assert ctr.room_asked(dict(CHURCH), NOW) == []
    assert "booked_by=not.is.null" in _paths(db, "church_space_bookings")[0]


def test_room_asked_a_weekly_repeat_is_one_tell(db):
    db["church_space_bookings"] = [_b("b2", series_id="s1", start_at="2026-12-12T23:00:00+00:00",
                                      end_at="2026-12-13T02:00:00+00:00"),
                                   _b("b1", series_id="s1"), _b("b3", space_id="chapel", booked_by="jess")]
    items = sorted(ctr.room_asked(dict(CHURCH), NOW), key=lambda i: i.key)
    assert [i.key for i in items] == ["room-ask:b3", "room-ask:s1"]
    assert items[1].line.startswith("Naiya asked for Fellowship Hall, Sat Dec 5, 5:00 PM–8:00 PM, and 1 more week.")
    assert items[0].line.startswith("Jess asked for Chapel") and items[0].actor == "jess"


def test_room_asked_owner_by_the_churchs_name(db):
    db["church_space_bookings"] = [_b("b1", booked_by="owner")]
    (it,) = ctr.room_asked(dict(CHURCH), NOW)
    assert it.line.startswith("Pastor Kevin asked for") and it.actor == "owner"


@pytest.mark.parametrize("broken", ["business_users", "church_spaces", "contacts"])
def test_room_asked_waits_when_its_words_cant_be_read(db, broken):
    db["church_space_bookings"] = [_b("b1")]
    db[broken] = None
    assert ctr.room_asked(dict(CHURCH), NOW) == []


def test_room_asked_a_failed_read_is_nothing(db):
    db["church_space_bookings"] = None
    assert ctr.room_asked(dict(CHURCH), NOW) == []


# ─── room_answered ────────────────────────────────────────────────────

def test_room_answered_tells_the_login_who_asked(db):
    db["church_space_bookings"] = [_b("b1", status="booked", decided_by="jess", decided_at="2026-11-22T16:00:00+00:00"),
                                   _b("b2", space_id="chapel", status="declined", decided_by="owner",
                                      decided_at="2026-11-22T16:00:00+00:00")]
    items = {i.key: i for i in ctr.room_answered(dict(CHURCH), NOW)}
    yes, no = items["room-answer:b1"], items["room-answer:b2"]
    assert yes.title == "Your room request was booked" and yes.to == ["naiya"] and yes.duty is None
    assert yes.line == "Fellowship Hall, Sat Dec 5, 5:00 PM–8:00 PM."
    assert no.title == "Your room request wasn't approved" and no.line.startswith("Chapel, Sat Dec 5")
    assert all("PRIVATE" not in i.line for i in items.values())
    (p,) = _paths(db, "church_space_bookings")
    _quoted(p)
    assert "status=in.(booked,declined)" in p and "booked_by=not.is.null" in p
    assert f"decided_at=gte.{ct.since(NOW, 3)}" in p


def test_room_answered_skips_own_bookings_members_and_gone_logins(db):
    db["church_space_bookings"] = [
        _b("own", status="booked", decided_by="naiya", decided_at="2026-11-22T16:00:00+00:00"),   # booked it straight away
        _b("member", booked_by=None, status="booked", decided_by="jess", decided_at="2026-11-22T16:00:00+00:00"),
        _b("gone", booked_by="left-church", status="booked", decided_by="jess", decided_at="2026-11-22T16:00:00+00:00"),
        _b("waiting", status="booked", decided_by=None)]
    assert ctr.room_answered(dict(CHURCH), NOW) == []


def test_room_answered_one_decision_on_a_repeat_is_one_tell(db):
    at = "2026-11-22T16:00:00+00:00"
    db["church_space_bookings"] = [_b("b1", series_id="s1", status="booked", decided_by="jess", decided_at=at),
                                   _b("b2", series_id="s1", status="booked", decided_by="jess", decided_at=at,
                                      start_at="2026-12-12T23:00:00+00:00", end_at="2026-12-13T02:00:00+00:00")]
    (it,) = ctr.room_answered(dict(CHURCH), NOW)
    assert it.key == f"room-answer:s1:booked:{at}"
    assert it.line == "Fellowship Hall, Sat Dec 5, 5:00 PM–8:00 PM, and 1 more week."


def test_room_answered_waits_when_logins_cant_be_read(db):
    db["church_space_bookings"] = [_b("b1", status="booked", decided_by="jess", decided_at="2026-11-22T16:00:00+00:00")]
    db["business_users"] = None
    assert ctr.room_answered(dict(CHURCH), NOW) == []


# ─── leader_said_yes ──────────────────────────────────────────────────

def _role(id_, cid, **kw):
    return {"id": id_, "contact_id": cid, "role": "youth_pastor", "scope": "", "answered_at": "2026-11-20T12:00:00+00:00",
            **kw}


def test_leader_yes_without_a_check_tells_background_checks(db):
    db["church_leader_roles"] = [_role("r1", "c1"), _role("r2", "c2", role="team_leader", scope="Greeters")]
    db["contacts"] = [{"id": "c1", "name": "Marcus Hill", "birthdate": "1990-01-01", "metadata": {}},
                      {"id": "c2", "name": "Ann Lee", "birthdate": None, "metadata": None}]
    items = {i.key: i for i in ctr.leader_said_yes(dict(CHURCH), NOW)}
    assert items["leader-yes:r1"].line == "Marcus said yes to Youth Pastor. Their background check is next."
    assert items["leader-yes:r2"].line == "Ann said yes to Team leader (Greeters). Their background check is next."
    assert all(i.duty == "background_checks" and not i.to for i in items.values())
    (p,) = _paths(db, "church_leader_roles")
    _quoted(p)
    assert "status=eq.active" in p and f"answered_at=gte.{ct.since(NOW, 7)}" in p
    for t in ("contacts", "space_leaders"):
        (q,) = _paths(db, t)
        _quoted(q)
        assert "in.(c1,c2)" in q


def test_leader_yes_skips_a_check_on_file_and_under_18s(db):
    db["church_leader_roles"] = [_role("r1", "c1"), _role("r2", "c2"), _role("r3", "c3"), _role("r4", "gone")]
    db["contacts"] = [{"id": "c1", "name": "Kids Leader", "metadata": {}},
                      {"id": "c2", "name": "Recorded Here", "metadata": {"serving": {"check_on": "2025-06-01"}}},
                      {"id": "c3", "name": "Teen Helper", "birthdate": "2011-05-05", "metadata": {}}]
    db["space_leaders"] = [{"contact_id": "c1", "background_check_on": "2026-01-10"}]
    assert ctr.leader_said_yes(dict(CHURCH), NOW) == []


@pytest.mark.parametrize("broken", ["contacts", "space_leaders"])
def test_leader_yes_never_guesses_no_check_when_a_read_fails(db, broken):
    db["church_leader_roles"] = [_role("r1", "c1")]
    db["contacts"] = [{"id": "c1", "name": "Marcus Hill", "metadata": {}}]
    db[broken] = None
    assert ctr.leader_said_yes(dict(CHURCH), NOW) == []


def test_leader_yes_waits_when_roles_cant_be_read(db, monkeypatch):
    import church_roles
    db["church_leader_roles"] = [_role("r1", "c1")]
    db["contacts"] = [{"id": "c1", "name": "Marcus Hill", "metadata": {}}]
    monkeypatch.setattr(church_roles, "defs", lambda biz, **kw: None)
    assert ctr.leader_said_yes(dict(CHURCH), NOW) == []


def test_the_finders_are_the_ones_the_sweep_lists():
    for name in ("room_asked", "room_answered", "leader_said_yes"):
        assert f"church_tells_rooms:{name}" in ct.FINDERS
        assert ct._finder(f"church_tells_rooms:{name}") is getattr(ctr, name)
