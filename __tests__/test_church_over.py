"""Who is over whom (church_over.py, docs/CHURCH_ASSIGNMENTS.md). Kevin,
2026-11-11: "this needs to be a way for churches to set this up in a general
sense when they establish leaders over people."

Pins, at the four test churches (church_three: Love City, Grace Baptist, New
Hope, Riverside), so the rule is the church's data and never Love City's
shape:
  * the office: the owner and every Admin over every office login but their
    own; whoever is over the lanes (the Executive Pastor's role at Love City,
    the church's own office_overseer_roles at New Hope) over every other
    Manager, never an Admin or the owner; a Manager over no one else
  * the ministry, on an open map: answers-to, a department's overseer over
    its leader, its leader over what hangs from it, walked down each person
    once; someone over others only while their role has the switch; a
    person with an office login is their login
  * closed or not ready: the owner, the Admins and whoever is over the lanes
    are over everyone, as tasks for leaders work today
  * above: the lanes' overseer, the owner at the top, the same steps a late
    task climbs for a person; never yourself
  * a loop ends; a failed read is a 503; each login's duties are
    church_duties' own answer
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_duties as cd  # noqa: E402
import church_over as co  # noqa: E402
import church_three as c3  # noqa: E402
import sb_clients  # noqa: E402
from church_three import FOUR, GRACE, LOVE_CITY, NEW_HOPE, RIVERSIDE  # noqa: E402


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    return c3.build(monkeypatch)


def ch(db, biz):
    return co.Church(c3.church(db, biz))


def login(db, biz, handle):
    return co.who(co.LOGIN, db.who[biz][handle + "@"] if handle != "owner" else c3.church(db, biz)["owner_id"])


def person(db, biz, handle):
    return co.who(co.PERSON, db.who[biz][handle])


def under(db, biz, me):
    return co.under(ch(db, biz), me)


def firsts(db, rows):
    return sorted(db.label[r["id"]] for r in rows)


# ─── The office ───────────────────────────────────────────────────────

def test_love_city_the_executive_pastor_is_over_the_lane_logins_never_an_admin_or_the_owner(db):
    rows = under(db, LOVE_CITY, login(db, LOVE_CITY, "jessica"))
    logins = [r for r in rows if r["kind"] == co.LOGIN]
    assert firsts(db, logins) == ["Laquesha", "Naiya", "Shapretta", "Tiara"]
    assert c3.church(db, LOVE_CITY)["owner_id"] not in {r["id"] for r in rows}
    assert db.who[LOVE_CITY]["minnie@"] not in {r["id"] for r in rows}, "never an Admin"
    naiya = next(r for r in logins if db.label[r["id"]] == "Naiya")
    assert naiya["why"] == "Office · Office & Leadership" and naiya["name"] == "Naiya Clark"


def test_the_owner_and_an_admin_are_over_every_office_login_but_their_own(db):
    owner = under(db, LOVE_CITY, login(db, LOVE_CITY, "owner"))
    assert firsts(db, [r for r in owner if r["kind"] == co.LOGIN]) == [
        "Jessica", "Laquesha", "Minnie", "Naiya", "Shapretta", "Tiara"]
    minnie = under(db, LOVE_CITY, login(db, LOVE_CITY, "minnie"))
    assert firsts(db, [r for r in minnie if r["kind"] == co.LOGIN]) == [
        "Jessica", "Laquesha", "Naiya", "Shapretta", "Tiara"]


def test_a_lane_manager_is_over_no_one(db):
    for h in ("naiya", "tiara", "laquesha", "shapretta"):
        assert under(db, LOVE_CITY, login(db, LOVE_CITY, h)) == [], h


def test_new_hope_the_role_the_church_named_to_oversee_the_office_is_over_its_logins(db):
    owen = under(db, NEW_HOPE, login(db, NEW_HOPE, "owen"))
    assert firsts(db, owen) == ["Kira", "Mila", "Olive", "Paige", "Sunny"]
    assert db.who[NEW_HOPE]["tessa@"] not in {r["id"] for r in owen}


def test_grace_the_pastor_is_over_the_secretary_and_the_secretary_over_no_one(db):
    owner = under(db, GRACE, login(db, GRACE, "owner"))
    assert {db.label[r["id"]] for r in owner if r["kind"] == co.LOGIN} == {"Sharon", "Thelma"}
    # Sharon holds every duty (moved to her), oversee_lanes too, but there's
    # no other Manager to be over, and her person leads nothing on the map.
    assert under(db, GRACE, login(db, GRACE, "sharon")) == []
    thelma = under(db, GRACE, login(db, GRACE, "thelma"))
    assert {db.label[r["id"]] for r in thelma if r["kind"] == co.LOGIN} == {"Sharon"}


def test_riverside_with_nobody_set_up_is_an_empty_list_not_an_error(db):
    assert under(db, RIVERSIDE, login(db, RIVERSIDE, "owner")) == []


# ─── The ministry ─────────────────────────────────────────────────────

def test_an_overseer_is_over_the_departments_leader_and_down_from_there(db):
    andre = under(db, LOVE_CITY, person(db, LOVE_CITY, "andre"))
    assert [(db.label[r["id"]], r["why"]) for r in andre] == [
        ("Yolanda", "Leads Youth"), ("Tyrone", "Youth Ministry (YWD) leader · under Yolanda")]
    paul = under(db, LOVE_CITY, person(db, LOVE_CITY, "paul"))
    assert firsts(db, paul) == ["Iris", "Ivy", "Ruth"]
    ruth = under(db, LOVE_CITY, person(db, LOVE_CITY, "ruth"))
    assert [(db.label[r["id"]], r["why"]) for r in ruth] == [("Iris", "Intercessors · Prayer"),
                                                              ("Ivy", "Intercessors · Prayer")]
    daniel = under(db, GRACE, person(db, GRACE, "daniel"))
    assert [(db.label[r["id"]], r["why"]) for r in daniel] == [("Yvette", "Leads Youth")]


def test_new_hope_answers_to_and_two_departments(db):
    amara = under(db, NEW_HOPE, person(db, NEW_HOPE, "amara"))
    assert [(db.label[r["id"]], r["why"]) for r in amara] == [
        ("Elena", "Answers to you"), ("Yusuf", "Leads Youth"), ("Kara", "Leads Kids")]
    abel = under(db, NEW_HOPE, person(db, NEW_HOPE, "abel"))
    assert firsts(db, abel) == ["Elliot", "Ezra", "Wren"]


def test_someone_is_over_others_only_while_their_role_has_the_switch(db):
    # Kara leads Kids, but her role (children's director, a kids job) doesn't
    # lead: she's under Amara, and over no one, as the late-task chain passes her over.
    assert under(db, NEW_HOPE, person(db, NEW_HOPE, "kara")) == []
    # Take Andre's role's oversee switch away and he's over no one.
    defs = {d["key"]: d for d in db.t["church_role_defs"] if d["business_id"] == LOVE_CITY}
    import church_roles as cr
    cr.update_role(LOVE_CITY, defs["associate_pastor"]["id"], {"can_oversee": False})
    assert under(db, LOVE_CITY, person(db, LOVE_CITY, "andre")) == []


def test_a_login_is_over_people_through_its_person(db):
    jess = under(db, LOVE_CITY, login(db, LOVE_CITY, "jessica"))
    marcus = next(r for r in jess if r["kind"] == co.PERSON)
    assert db.label[marcus["id"]] == "Marcus" and marcus["why"] == "Answers to you"


def test_a_person_with_an_office_login_is_their_login(db):
    yolanda = db.who[LOVE_CITY]["yolanda"]
    uid = "1a000000-0000-4000-8000-000000000099"
    db.t["business_users"].append({"business_id": LOVE_CITY, "user_id": uid, "role": "manager",
                                   "invited_email": "yolanda@lovecity.org", "lane": None, "areas": ["kids_youth"],
                                   "contact_id": yolanda, "name": "Yolanda Reed", "status": "active"})
    db.label[uid] = "Yolanda"
    # Her overseer on the map is over the people under her, but never her
    # login: an office login is the office rule's alone (#1801 review).
    andre = under(db, LOVE_CITY, person(db, LOVE_CITY, "andre"))
    assert [(r["kind"], db.label[r["id"]], r["why"]) for r in andre] == [
        (co.PERSON, "Tyrone", "Youth Ministry (YWD) leader · under Yolanda")]
    owner = under(db, LOVE_CITY, login(db, LOVE_CITY, "owner"))
    assert (co.PERSON, yolanda) not in {(r["kind"], r["id"]) for r in owner}
    assert (co.LOGIN, uid) in {(r["kind"], r["id"]) for r in owner}
    jess = under(db, LOVE_CITY, login(db, LOVE_CITY, "jessica"))
    assert (co.LOGIN, uid) in {(r["kind"], r["id"]) for r in jess}, "over the lanes: every Manager login"


def test_the_map_never_hands_a_manager_an_admins_login(db):
    """Minnie (the Admin treasurer) holds a role that answers to Jessica's
    person: on the map Jessica is over her, but an Admin's login is only the
    owner's and the other Admins' (#1801 review, the reviewer's repro)."""
    db.t["church_leader_roles"].append({
        "id": db.nid("church_leader_roles"), "business_id": LOVE_CITY, "contact_id": db.who[LOVE_CITY]["minnie"],
        "role": "ministers", "scope": "", "status": "active", "invited_at": "2026-10-01T00:00:00+00:00",
        "answered_at": None, "answers_to_contact_id": db.who[LOVE_CITY]["jessica"]})
    jess, minnie = login(db, LOVE_CITY, "jessica"), login(db, LOVE_CITY, "minnie")
    ids = {r["id"] for r in under(db, LOVE_CITY, jess)}
    assert minnie["id"] not in ids and db.who[LOVE_CITY]["minnie"] not in ids
    assert not co.is_over(ch(db, LOVE_CITY), jess, minnie)


def test_a_member_seat_department_leader_is_never_over_the_treasurer(db):
    """New Hope: Tessa (Admin, treasurer) serves as a deacon; Celia leads
    Care, whose units hold the deacons' role, and has only a Member seat."""
    nh, w = NEW_HOPE, db.who[NEW_HOPE]
    db.t["church_leader_roles"].append({
        "id": db.nid("church_leader_roles"), "business_id": nh, "contact_id": w["tessa"], "role": "deacons",
        "scope": "", "status": "active", "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None,
        "answers_to_contact_id": None})
    celia = "3a000000-0000-4000-8000-000000000099"
    db.t["business_users"].append({"business_id": nh, "user_id": celia, "role": "member",
                                   "invited_email": "celia@newhope.church", "lane": None, "areas": None,
                                   "contact_id": w["celia"], "name": "Celia Ward", "status": "active"})
    ids = {r["id"] for r in under(db, nh, co.who(co.LOGIN, celia))}
    assert login(db, nh, "tessa")["id"] not in ids and w["tessa"] not in ids
    assert under(db, nh, person(db, nh, "celia")) == []


def test_the_senior_pastor_is_never_under_anyone_even_under_another_email(db):
    """The owner signs in with one address and his record carries another
    (#1801 review): he holds the senior role, the top of every chain."""
    kevin = next(c for c in db.t["contacts"] if c["id"] == db.who[LOVE_CITY]["kevin"])
    kevin["email"] = "pastor@lovecity.org"
    for h in ("owner", "minnie", "jessica"):
        assert db.who[LOVE_CITY]["kevin"] not in {r["id"] for r in under(db, LOVE_CITY, login(db, LOVE_CITY, h))}, h
    assert db.who[LOVE_CITY]["kevin"] in ch(db, LOVE_CITY).top
    up = co.above(ch(db, LOVE_CITY), person(db, LOVE_CITY, "andre"))
    assert [(r["kind"], r["id"]) for r in up] == [(co.LOGIN, c3.LC_OWNER)], "the top is the owner's login"
    assert co.above(ch(db, LOVE_CITY), person(db, LOVE_CITY, "kevin")) == []


def test_the_senior_pastor_is_never_under_the_lanes_overseer_with_the_map_closed(monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    db = c3.build(monkeypatch, map_on=False)
    kevin = next(c for c in db.t["contacts"] if c["id"] == db.who[LOVE_CITY]["kevin"])
    kevin["email"] = "pastor@lovecity.org"
    for h in ("minnie", "jessica"):
        assert db.who[LOVE_CITY]["kevin"] not in {r["id"] for r in under(db, LOVE_CITY, login(db, LOVE_CITY, h))}, h


def test_everyone_with_the_owners_email_is_at_the_top(db):
    """A family address the owner shares: whoever carries it is never under
    anyone, whichever of them the owner is."""
    junior = "1c000000-0000-4000-8000-000000000098"
    db.t["contacts"].append({"id": junior, "business_id": LOVE_CITY, "name": "Kevin McCloud Jr", "status": "active",
                             "metadata": {}, "phone": "", "email": c3.PLATFORM, "birthdate": None})
    db.t["church_leader_roles"].append({
        "id": db.nid("church_leader_roles"), "business_id": LOVE_CITY, "contact_id": junior, "role": "ministers",
        "scope": "", "status": "active", "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None,
        "answers_to_contact_id": None})
    assert {junior, db.who[LOVE_CITY]["kevin"]} <= ch(db, LOVE_CITY).top
    assert junior not in {r["id"] for r in under(db, LOVE_CITY, login(db, LOVE_CITY, "minnie"))}


def test_a_failed_read_of_the_owners_email_is_a_503_never_nobody(db, monkeypatch):
    import messaging_router
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda u: None)
    with pytest.raises(HTTPException) as e:
        under(db, LOVE_CITY, login(db, LOVE_CITY, "minnie"))
    assert e.value.status_code == 503
    assert c3.church(db, LOVE_CITY)["owner_id"] not in co._OWNER_EMAIL, "a failed read is never kept"


def test_a_loop_ends_and_names_each_person_once(db):
    w = db.who[NEW_HOPE]
    for h in db.t["church_leader_roles"]:
        if h["business_id"] == NEW_HOPE and h["contact_id"] == w["amara"]:
            h["answers_to_contact_id"] = w["elena"]        # Elena answers to Amara, and Amara to Elena
    amara = under(db, NEW_HOPE, person(db, NEW_HOPE, "amara"))
    ids = [r["id"] for r in amara]
    assert len(ids) == len(set(ids)) and w["amara"] not in ids
    elena = under(db, NEW_HOPE, person(db, NEW_HOPE, "elena"))
    assert w["elena"] not in [r["id"] for r in elena] and w["amara"] in [r["id"] for r in elena]


def test_closed_the_owner_admins_and_the_lanes_overseer_are_over_every_leader(monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    db = c3.build(monkeypatch, map_on=False)
    assert under(db, LOVE_CITY, person(db, LOVE_CITY, "andre")) == [], "the map decides nothing while it's closed"
    jess = under(db, LOVE_CITY, login(db, LOVE_CITY, "jessica"))
    people = {db.label[r["id"]] for r in jess if r["kind"] == co.PERSON}
    assert {"Andre", "Yolanda", "Tyrone", "Ruth", "Marcus"} <= people
    assert "Kevin" not in people, "never the owner's own person"
    assert not {"Naiya", "Jessica", "Minnie"} & people, "an office login is its login"
    assert under(db, LOVE_CITY, login(db, LOVE_CITY, "naiya")) == []


# ─── is_over, above ───────────────────────────────────────────────────

def test_is_over_never_yourself_never_up(db):
    c = ch(db, LOVE_CITY)
    jess, naiya = login(db, LOVE_CITY, "jessica"), login(db, LOVE_CITY, "naiya")
    assert co.is_over(c, jess, naiya) and not co.is_over(c, naiya, jess)
    assert not co.is_over(c, jess, jess)
    assert not co.is_over(c, jess, login(db, LOVE_CITY, "owner"))
    assert not co.is_over(c, jess, co.who(co.LOGIN, "a9000000-0000-4000-8000-000000000009")), "not on this church"
    # Another church's person, by a real id, is nobody here.
    assert not co.is_over(c, login(db, LOVE_CITY, "owner"), person(db, GRACE, "yvette"))


def test_above_climbs_the_same_steps_and_ends_at_the_owner(db):
    def up(biz, w):
        return [(r["kind"], db.label.get(r["id"], r["id"])) for r in co.above(ch(db, biz), w)]
    assert up(LOVE_CITY, login(db, LOVE_CITY, "naiya")) == [(co.LOGIN, "Jessica")]
    assert up(LOVE_CITY, login(db, LOVE_CITY, "jessica")) == [(co.LOGIN, "owner")]
    assert up(LOVE_CITY, login(db, LOVE_CITY, "minnie")) == [(co.LOGIN, "owner")]
    assert up(LOVE_CITY, login(db, LOVE_CITY, "owner")) == []
    assert up(LOVE_CITY, person(db, LOVE_CITY, "ruth")) == [(co.PERSON, "Paul")]
    assert up(LOVE_CITY, person(db, LOVE_CITY, "yolanda")) == [(co.PERSON, "Andre")]
    assert up(LOVE_CITY, person(db, LOVE_CITY, "marcus")) == [(co.LOGIN, "Jessica")], "her person is her login"
    assert up(LOVE_CITY, person(db, LOVE_CITY, "andre")) == [(co.LOGIN, "owner")], "the senior role is the owner"
    assert up(GRACE, login(db, GRACE, "sharon")) == [(co.LOGIN, "owner")]
    assert up(NEW_HOPE, login(db, NEW_HOPE, "kira")) == [(co.LOGIN, "Owen")]
    assert up(NEW_HOPE, person(db, NEW_HOPE, "kara")) == [(co.PERSON, "Amara")]


# ─── Reads ────────────────────────────────────────────────────────────

def test_each_logins_duties_are_church_duties_own_answer(db):
    for biz in FOUR:
        c = ch(db, biz)
        for uid, role, _email in c3.logins(db, biz):
            assert c.held(uid) == cd.standing(biz, uid)["duties"], (c3.NAMES[biz], db.label.get(uid))


@pytest.mark.parametrize("table", ["business_users", "church_leader_roles", "church_departments", "contacts"])
def test_a_failed_read_is_a_503_never_nobody(db, monkeypatch, table):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith(table + "?") else real(path, **kw))
    with pytest.raises(HTTPException) as e:
        under(db, LOVE_CITY, login(db, LOVE_CITY, "jessica"))
    assert e.value.status_code == 503


def test_the_switch(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", c3.PLATFORM)
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    assert co.mode() == "off" and not co.church_open(LOVE_CITY)
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "bogus")
    assert co.mode() == "off"
    monkeypatch.delenv("CHURCH_ASSIGNMENTS")
    assert co.mode() == "owner"
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda b: b == LOVE_CITY)
    assert co.church_open(LOVE_CITY) and not co.church_open(GRACE)
    from types import SimpleNamespace
    assert co.office_open(SimpleNamespace(email=c3.PLATFORM), GRACE), "the platform owner's own login"
    assert not co.office_open(SimpleNamespace(email="pastor@gracebaptist.org"), GRACE)
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    assert co.church_open(GRACE)
