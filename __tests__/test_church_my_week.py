"""My week (church_my_week.py, Kevin 2026-10-26, "Who sees what"): a church
login's first page.

Pins:
  * the owner and admins see the whole church: every area, a line each, in
    the areas' order; follow-ups with no one, late ones, and office logins
    that still see everything are theirs
  * a follow-up handed to the person (by their sign-in email) comes first,
    late before new
  * Prayer & care handed to their login is one line with nothing of what
    was asked
  * a login that works some areas sees only those (never Giving), what's
    missing in them is theirs, and Kids & youth sees only first check-ins
    in what was handed across
  * a failed read is a 503, never an empty week; the switch and churches
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import church_my_week as mw  # noqa: E402
import sb_clients  # noqa: E402
from test_church_follow_up import BIZ, OWNER, PASTOR, TASHA, ROBERT, ANDRE  # noqa: E402
from test_church_areas import db  # noqa: E402,F401

MARCUS_SEAT = "11111111-1111-1111-1111-111111111111"
NOW = datetime.now(timezone.utc)
iso = lambda d: d.isoformat()  # noqa: E731


def _fu(fid, contact, leader, *, status="open", due_days=2, created_days=1, card="Connect card", key="connect",
        role="pastor"):
    return {"id": fid, "business_id": BIZ, "contact_id": contact, "leader_contact_id": leader, "leader_role": role,
            "card_key": key, "card_name": card, "status": status,
            "due_at": iso(NOW + timedelta(days=due_days)), "created_at": iso(NOW - timedelta(days=created_days)),
            "done_at": iso(NOW - timedelta(hours=3)) if status == "done" else None}


@pytest.fixture
def week(db, monkeypatch):
    db.t["church_follow_ups"] = [
        _fu("f-late", ROBERT, PASTOR, due_days=-2, created_days=4),          # Kevin's, late
        _fu("f-new", TASHA, PASTOR),                                          # Kevin's, new
        _fu("f-none", ANDRE, None, role="pastor"),                            # with no one
        _fu("f-first", ROBERT, TASHA, card="First check-in", key="checkin:first", role="team_leader", status="done"),
    ]
    db.t["ministry_care_requests"] = [
        {"id": "c1", "business_id": BIZ, "assigned_to": OWNER, "status": "new",
         "submission": {"text": "My mother is in the hospital"}},
        {"id": "c2", "business_id": BIZ, "assigned_to": "someone-else", "status": "new", "submission": {}},
    ]
    db.t["business_users"].append({"business_id": BIZ, "user_id": MARCUS_SEAT, "invited_email": "marcus@example.com",
                                   "role": "manager", "status": "active", "areas": None})
    return db


@pytest.fixture
def client(week, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import business_access
    who = {"role": "owner", "id": OWNER, "email": "kmjcreativesolution@gmail.com"}
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: who["role"])
    monkeypatch.setenv("CHURCH_AREAS", "on")
    app = FastAPI()
    app.include_router(mw.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email=who["email"], user_metadata={})))
    c = TestClient(app)
    c.who = who
    return c


def _get(client):
    r = client.get(f"/church/my-week?business_id={BIZ}")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_owner_sees_the_whole_church_an_area_to_a_line(client):
    w = _get(client)
    assert [a["key"] for a in w["areas"]] == list(ca.AREA_ORDER)
    kids = next(a for a in w["areas"] if a["key"] == "kids_youth")
    assert kids["state"] == "watch" and "background check" in kids["line"] and kids["door"]["id"] == "kids"
    assert w["me"] == {"role": "owner", "areas": None, "by": "all", "why": "Sees the whole church"}
    titles = [w["next"]["title"]] + [n["title"] for n in w["needs"]]
    assert "1 person in follow-up has no one." in titles
    assert any(t.endswith("office logins still see everything.") for t in titles)


def test_a_follow_up_handed_to_you_comes_first_late_before_new(client):
    client.who["email"] = "Kevin@Example.com"          # the pastor's contact, by sign-in email
    w = _get(client)
    assert w["next"]["title"] == "Robert Hayes is waiting to hear from you."
    assert w["next"]["late"] and w["next"]["door"]["id"] == "follow-up"
    assert "Tasha Williams was handed to you." in [n["title"] for n in w["needs"]]


def test_care_handed_to_your_login_is_one_line_with_nothing_of_what_was_asked(client):
    w = _get(client)
    care = [n for n in [w["next"]] + w["needs"] if n["kind"] == "care"]
    assert care and care[0]["title"] == "A prayer or care request was handed to you."
    assert "hospital" not in str(w)


def test_what_was_handed_across_this_week_says_where_it_went_and_where_it_is(client):
    w = _get(client)
    first = next(h for h in w["handed"] if h["id"] == "f-first")
    assert first["from"] == "Kids check-in" and first["title"] == "Robert Hayes, first time"
    assert first["state"] == "reached" and "Tasha reached them" in first["detail"]
    none = next(h for h in w["handed"] if h["id"] == "f-none")
    assert none["state"] == "no_one"


def test_a_login_that_works_kids_sees_only_kids_and_its_first_check_ins(client):
    client.who.update(role="manager", id=MARCUS_SEAT, email="marcus@example.com")
    w = _get(client)
    assert [a["key"] for a in w["areas"]] == ["kids_youth"]
    assert w["me"]["areas"] == ["kids_youth"] and w["me"]["by"] == "guess"
    assert w["next"]["kind"] == "gap" and "background check" in w["next"]["title"]
    assert [h["id"] for h in w["handed"]] == ["f-first"], "only first check-ins cross from the kids desk"
    assert not any(n["kind"] in ("no_one", "late", "logins") for n in [w["next"]] + w["needs"])


def test_giving_shows_only_to_the_owner_and_admins(client, week):
    week.t["business_users"][-1]["areas"] = ["giving_money", "office"]
    client.who.update(role="manager", id=MARCUS_SEAT, email="marcus@example.com")
    assert [a["key"] for a in _get(client)["areas"]] == ["office"]


@pytest.mark.parametrize("table", ["church_follow_ups", "contacts", "ministry_care_requests", "church_role_defs",
                                   "business_users", "church_leader_roles", "worship_team", "space_leaders"])
def test_a_failed_read_is_a_503_never_an_empty_week(client, week, monkeypatch, table):
    client.who.update(role="manager", id=MARCUS_SEAT, email="marcus@example.com")
    real = week.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith(table) else real(path, **kw))
    # A seat: every read on its path runs (its own seat, its guess, its follow-ups).
    if table in ("church_follow_ups", "contacts", "church_role_defs"):
        client.who.update(email="robert@example.com")      # someone with follow-ups and roles to name
    assert client.get(f"/church/my-week?business_id={BIZ}").status_code == 503, table


def test_the_switch_a_church_and_a_seat(client, week, monkeypatch):
    assert client.get(f"/church/my-week/status?business_id={BIZ}").json() == {"enabled": True}
    monkeypatch.setenv("CHURCH_AREAS", "owner")
    client.who["email"] = "pastor@lovecity.org"
    assert client.get(f"/church/my-week?business_id={BIZ}").status_code == 404
    assert client.get(f"/church/my-week/status?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_AREAS", "on")
    week.t["businesses"][0]["type"] = "salon"
    assert client.get(f"/church/my-week?business_id={BIZ}").status_code == 404
    assert client.get(f"/church/my-week/status?business_id={BIZ}").json() == {"enabled": False}


def test_the_owner_seeing_as_a_login_gets_that_logins_week_and_no_one_else_can(client, week):
    w = client.get(f"/church/my-week?business_id={BIZ}&as_user={MARCUS_SEAT}").json()
    assert [a["key"] for a in w["areas"]] == ["kids_youth"] and w["me"]["role"] == "manager"
    client.who.update(role="manager", id=MARCUS_SEAT, email="marcus@example.com")
    other = "44444444-4444-4444-4444-444444444444"
    assert client.get(f"/church/my-week?business_id={BIZ}&as_user={other}").status_code == 403
    assert client.get(f"/church/my-week?business_id={BIZ}&as_user={MARCUS_SEAT}").status_code == 200, "yourself is fine"
    client.who.update(role="owner", id=OWNER)
    assert client.get(f"/church/my-week?business_id={BIZ}&as_user=nope").status_code == 400
    assert client.get(f"/church/my-week?business_id={BIZ}&as_user={other}").status_code == 404
