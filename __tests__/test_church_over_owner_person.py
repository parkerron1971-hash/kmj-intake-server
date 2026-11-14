"""Which of the church's people its owner is (church_over.Church.owner_pick /
owner_person / owner_how; GET and PUT /church/owner-person in
church_assignments; docs/CHURCH_ASSIGNMENTS.md).

Until 2026-11-14 the owner's own person was found only by matching the
owner's sign-in email to a record's email. A pastor whose record carries
another email than he signs in with wasn't found: the owner read as no pastor
(owner_guarded false), the office's Hand to list offered him, and an office
seat could hand the owner work. The church can now say which person the owner
is (businesses.settings.church_owner_contact_id), read first, with the email
match exactly as before when nothing is picked or the pick no longer points
at one of the church's people.

Pins, at Love City (church_three):
  * picked beats the email; the picked person is at the top, the owner reads
    as a pastor again, and no office seat hands him work
  * a pick that is stale (gone, another church's, not an id) falls back to the
    email match; nothing picked is exactly as before
  * a read that fails is a 503, never "the owner is nobody"; a church read
    without its settings reads them once
  * the routes: the owner and an Admin read it, any other seat is a 403, a
    stranger a 404; the owner picks, changes and clears; an Admin fills it
    only while no one is found and never moves it after; the person is this
    church's and an adult's record; a failed write is a 503 with nothing
    changed; the other settings are kept; the switch closes both
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_assignments as cas  # noqa: E402
import church_my_week as mw  # noqa: E402
import church_over as co  # noqa: E402
import church_three as c3  # noqa: E402
import sb_clients  # noqa: E402
from church_three import GRACE, LOVE_CITY  # noqa: E402
from test_church_assignments import app, as_, db, uid  # noqa: E402,F401  (app and db are fixtures)

OTHER_EMAIL = "pastor@lovecity.org"


def biz_row(db):
    return next(b for b in db.t["businesses"] if b["id"] == LOVE_CITY)


def pick(db, cid):
    """Write the pick as the route does: one key in the church's settings."""
    row = biz_row(db)
    row["settings"] = {**row["settings"], co.OWNER_PERSON_KEY: cid}


def record(db, handle="kevin"):
    return next(c for c in db.t["contacts"] if c["id"] == db.who[LOVE_CITY][handle])


def church(db):
    return co.Church(c3.church(db, LOVE_CITY))


def login(db, handle):
    return co.who(co.LOGIN, uid(db, LOVE_CITY, handle))


def under_ids(db, handle):
    return {r["id"] for r in co.under(church(db), login(db, handle))}


# ─── church_over ──────────────────────────────────────────────────────

def test_nothing_picked_is_exactly_as_before(db):
    kevin = db.who[LOVE_CITY]["kevin"]                      # his record carries his sign-in email
    c = church(db)
    assert c.owner_pick is None and (c.owner_person, c.owner_how) == (kevin, co.BY_EMAIL)
    assert c.top == {kevin} and c.owner_guarded is True


def test_a_pastor_under_another_email_is_found_by_the_pick(db):
    """The gap: his record has one email, he signs in with another."""
    kevin = db.who[LOVE_CITY]["kevin"]
    record(db)["email"] = OTHER_EMAIL
    before = church(db)
    assert (before.owner_person, before.owner_how) == (None, co.NOT_FOUND)
    assert before.owner_guarded is False and kevin in before.seniors and kevin not in before.top
    assert kevin in under_ids(db, "owner"), "the owner was over his own person"
    assert co.may_hand(before, login(db, "minnie"), login(db, "owner")), "and an Admin could hand the owner work"

    pick(db, kevin)
    c = church(db)
    assert (c.owner_pick, c.owner_person, c.owner_how) == (kevin, kevin, co.PICKED)
    assert c.login_person[c3.LC_OWNER] == kevin and c.persons_of(login(db, "owner")) == {kevin}
    assert kevin in c.top and kevin not in c.seniors, "at the top: never under anyone, not even the owner"
    assert c.owner_guarded is True, "the owner's own person is the senior pastor again"
    for h in ("owner", "minnie", "jessica"):
        assert kevin not in under_ids(db, h), h
    assert co.above(church(db), co.who(co.PERSON, kevin)) == []
    assert co.is_guarded(c, login(db, "owner")) and co.is_guarded(c, co.who(co.PERSON, kevin))
    for h in ("minnie", "naiya", "jessica"):
        assert not co.may_hand(c, login(db, h), login(db, "owner"), co.who(co.PERSON, kevin)), h
    assert co.may_hand(c, login(db, "owner"), co.who(co.PERSON, db.who[LOVE_CITY]["marcus"])), "the owner as before"


def test_the_hand_to_list_follows_the_pick(db):
    kevin = db.who[LOVE_CITY]["kevin"]
    record(db)["email"] = OTHER_EMAIL
    minnie = uid(db, LOVE_CITY, "minnie")
    shown = {"people": [{"user_id": c3.LC_OWNER, "role": "owner", "you": False},
                        {"user_id": minnie, "role": "admin", "you": True}]}
    listed = mw.without_guarded(c3.church(db, LOVE_CITY), minnie, shown)
    assert [p["role"] for p in listed["people"]] == ["owner", "admin"], "not found: the list offered the owner"
    pick(db, kevin)
    listed = mw.without_guarded(c3.church(db, LOVE_CITY), minnie, shown)
    assert [p["role"] for p in listed["people"]] == ["admin"], "picked: an office seat isn't offered the pastor"


def test_picked_beats_the_email(db):
    """One of the family carries the owner's sign-in email; the church says
    the owner is someone else. The pick answers; whoever carries the email
    stays at the top, as before."""
    kevin = db.who[LOVE_CITY]["kevin"]
    junior = "1c000000-0000-4000-8000-000000000098"
    record(db)["email"] = OTHER_EMAIL
    db.t["contacts"].append({"id": junior, "business_id": LOVE_CITY, "name": "Kevin McCloud Jr", "status": "active",
                             "metadata": {}, "phone": "", "email": c3.PLATFORM, "birthdate": None})
    c = church(db)
    assert (c.owner_person, c.owner_how) == (junior, co.BY_EMAIL), "the email named the wrong one"
    pick(db, kevin)
    c = church(db)
    assert (c.owner_person, c.owner_how) == (kevin, co.PICKED)
    assert c.top == {kevin, junior} and c.owner_guarded is True


@pytest.mark.parametrize("stale", ["1c000000-0000-4000-8000-00000000dead",     # no such record (taken off the list)
                                   "another church",                            # Grace's person
                                   "not an id", 7, ""])
def test_a_stale_pick_falls_back_to_the_email(db, stale):
    kevin = db.who[LOVE_CITY]["kevin"]
    pick(db, db.who[GRACE]["daniel"] if stale == "another church" else stale)
    c = church(db)
    assert c.owner_pick is None
    assert (c.owner_person, c.owner_how) == (kevin, co.BY_EMAIL) and c.top == {kevin}
    record(db)["email"] = OTHER_EMAIL                        # and with no email match either: no one, as before
    c = church(db)
    assert (c.owner_person, c.owner_how) == (None, co.NOT_FOUND)


def test_a_pick_that_cant_be_read_is_a_503_never_nobody(db, monkeypatch):
    kevin = db.who[LOVE_CITY]["kevin"]
    pick(db, kevin)
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (
        None if path.startswith("/contacts?") and f"id=eq.{kevin}" in path else real(path, **kw)))
    with pytest.raises(HTTPException) as e:
        church(db).owner_person
    assert e.value.status_code == 503
    with pytest.raises(HTTPException) as e:
        co.under(church(db), login(db, "minnie"))
    assert e.value.status_code == 503


def test_a_church_read_without_its_settings_reads_them_once(db, monkeypatch):
    kevin = db.who[LOVE_CITY]["kevin"]
    record(db)["email"] = OTHER_EMAIL
    pick(db, kevin)
    row = {k: v for k, v in c3.church(db, LOVE_CITY).items() if k != "settings"}
    reads = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (reads.append(path), real(path, **kw))[1])
    c = co.Church(row)
    assert c.owner_person == kevin and c.owner_how == co.PICKED and c.owner_guarded
    assert len([p for p in reads if p.startswith("/businesses?")]) == 1
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (
        None if path.startswith("/businesses?") else real(path, **kw)))
    with pytest.raises(HTTPException) as e:
        co.Church(row).owner_person
    assert e.value.status_code == 503, "settings that can't be read are never 'nothing picked'"


def test_nothing_picked_reads_nothing_more(db, monkeypatch):
    reads = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (reads.append(path), real(path, **kw))[1])
    c = church(db)
    assert c.owner_person and not [p for p in reads if "&id=eq." in p and p.startswith("/contacts?")]
    assert not [p for p in reads if p.startswith("/businesses?")]


# ─── The routes ───────────────────────────────────────────────────────

def get(app):
    return app.get(f"/church/owner-person?business_id={LOVE_CITY}")


def put(app, contact_id, **more):
    return app.put("/church/owner-person", json={"business_id": LOVE_CITY, "contact_id": contact_id, **more})


def test_the_owner_and_an_admin_read_it_and_no_one_else(app, db):
    kevin = db.who[LOVE_CITY]["kevin"]
    as_(app, LOVE_CITY, "owner")
    r = get(app)
    assert r.status_code == 200, r.text
    assert r.json() == {"contact_id": kevin, "name": "Kevin McCloud", "how": "email", "can_change": True}
    as_(app, LOVE_CITY, "minnie")
    assert get(app).json() == {"contact_id": kevin, "name": "Kevin McCloud", "how": "email", "can_change": False}
    for h in ("jessica", "naiya"):
        as_(app, LOVE_CITY, h)
        r = get(app)
        assert r.status_code == 403 and r.json()["detail"] == cas.OWNER_PERSON_WHO, h
        r = put(app, kevin)
        assert r.status_code == 403 and r.json()["detail"] == cas.OWNER_PERSON_WHO, h
    as_(app, GRACE, "owner")                                 # another church's owner: no seat here
    assert get(app).status_code == 404 and put(app, kevin).status_code == 404
    assert co.OWNER_PERSON_KEY not in biz_row(db)["settings"]


def test_the_owner_picks_changes_and_clears(app, db):
    w = db.who[LOVE_CITY]
    record(db)["email"] = OTHER_EMAIL
    as_(app, LOVE_CITY, "owner")
    assert get(app).json() == {"contact_id": None, "name": None, "how": "none", "can_change": True}
    r = put(app, w["kevin"])
    assert r.status_code == 200, r.text
    assert r.json() == {"contact_id": w["kevin"], "name": "Kevin McCloud", "how": "picked", "can_change": True}
    kept = biz_row(db)["settings"]
    assert kept[co.OWNER_PERSON_KEY] == w["kevin"]
    assert kept["practitioner_name"] == "Pastor Kevin" and kept["timezone"] == "America/Detroit", "the rest is kept"
    assert get(app).json()["how"] == "picked" and church(db).owner_guarded
    r = put(app, w["andre"])                                 # the owner may move it
    assert r.status_code == 200 and r.json()["contact_id"] == w["andre"] and r.json()["name"] == "Andre Wallace"
    r = put(app, None)                                       # and take it away: back to the sign-in email
    assert r.status_code == 200 and r.json() == {"contact_id": None, "name": None, "how": "none", "can_change": True}
    assert co.OWNER_PERSON_KEY not in biz_row(db)["settings"]
    assert biz_row(db)["settings"]["practitioner_name"] == "Pastor Kevin"


def test_what_a_pick_refuses(app, db):
    w = db.who[LOVE_CITY]
    as_(app, LOVE_CITY, "owner")
    r = put(app, db.who[GRACE]["daniel"])
    assert r.status_code == 404 and r.json()["detail"] == cas.OWNER_PERSON_GONE, "another church's person"
    r = put(app, w["jaylen"])
    assert r.status_code == 400 and r.json()["detail"] == cas.OWNER_PERSON_CHILD, "a child on a family"
    assert put(app, "kevin").status_code == 400, "not an id"
    assert app.put("/church/owner-person", json={"business_id": LOVE_CITY}).status_code == 400, "say who, or null"
    assert co.OWNER_PERSON_KEY not in biz_row(db)["settings"], "nothing saved on a refusal"


def test_an_admin_fills_it_only_while_no_one_is_found(app, db):
    """An Admin can set it up before the pastor signs in. An Admin can never
    move the owner off the person the church already has: that would take a
    pastor out from under the rule that no office seat hands him work."""
    w = db.who[LOVE_CITY]
    as_(app, LOVE_CITY, "minnie")
    r = put(app, w["tasha"])                                 # found by email: not an Admin's to move
    assert r.status_code == 403 and r.json()["detail"] == cas.OWNER_PERSON_SET
    assert put(app, None).status_code == 403
    record(db)["email"] = OTHER_EMAIL                        # no one found: an Admin fills it
    assert get(app).json() == {"contact_id": None, "name": None, "how": "none", "can_change": True}
    r = put(app, w["kevin"])
    assert r.status_code == 200, r.text
    assert r.json() == {"contact_id": w["kevin"], "name": "Kevin McCloud", "how": "picked", "can_change": False}
    for cid in (w["tasha"], None):                           # picked: the owner's to change from here
        r = put(app, cid)
        assert r.status_code == 403 and r.json()["detail"] == cas.OWNER_PERSON_SET
    assert biz_row(db)["settings"][co.OWNER_PERSON_KEY] == w["kevin"]


def test_a_write_that_fails_is_a_503_with_nothing_changed(app, db, monkeypatch):
    record(db)["email"] = OTHER_EMAIL
    as_(app, LOVE_CITY, "owner")
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **kw: None)
    assert put(app, db.who[LOVE_CITY]["kevin"]).status_code == 503
    assert co.OWNER_PERSON_KEY not in biz_row(db)["settings"]
    real = sb_clients.sb_get_as_service                      # who is a child that can't be read: nothing saved
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (
        None if path.startswith("/children?") else real(path, **kw)))
    assert put(app, db.who[LOVE_CITY]["kevin"]).status_code == 503


def test_the_switch_closes_both_routes(app, db, monkeypatch):
    as_(app, LOVE_CITY, "owner")
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    assert get(app).status_code == 404 and put(app, db.who[LOVE_CITY]["kevin"]).status_code == 404
    assert co.OWNER_PERSON_KEY not in biz_row(db)["settings"]
