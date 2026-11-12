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
    # Jessica's person is the Executive Pastor, who shepherds: an Admin's
    # office standing never reaches her login (Kevin, 2026-11-12).
    assert firsts(db, [r for r in minnie if r["kind"] == co.LOGIN]) == [
        "Laquesha", "Naiya", "Shapretta", "Tiara"]


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


def test_the_senior_pastor_is_never_under_an_admin_even_under_another_email(db):
    """The owner signs in with one address and his record carries another
    (#1801 review): he holds the senior role, so only the owner is over him
    (round 2: the senior role's holders are under the owner only; here the
    owner can't tell that person is himself)."""
    kevin = db.who[LOVE_CITY]["kevin"]
    next(c for c in db.t["contacts"] if c["id"] == kevin)["email"] = "pastor@lovecity.org"
    for h in ("minnie", "jessica"):
        assert kevin not in {r["id"] for r in under(db, LOVE_CITY, login(db, LOVE_CITY, h))}, h
    assert kevin in {r["id"] for r in under(db, LOVE_CITY, login(db, LOVE_CITY, "owner"))}
    c = ch(db, LOVE_CITY)
    assert kevin in c.seniors and kevin not in c.top
    up = co.above(ch(db, LOVE_CITY), person(db, LOVE_CITY, "andre"))
    assert [(r["kind"], r["id"]) for r in up] == [(co.PERSON, kevin)], "the chain's own top step"
    assert [(r["kind"], r["id"]) for r in co.above(ch(db, LOVE_CITY), person(db, LOVE_CITY, "kevin"))] == [
        (co.LOGIN, c3.LC_OWNER)], "a senior holder is under the owner only"


def test_the_owners_own_person_is_never_under_anyone_not_even_the_owner(db):
    kevin = db.who[LOVE_CITY]["kevin"]                      # his record carries his sign-in email
    c = ch(db, LOVE_CITY)
    assert kevin in c.top and kevin not in c.seniors
    for h in ("owner", "minnie", "jessica"):
        assert kevin not in {r["id"] for r in under(db, LOVE_CITY, login(db, LOVE_CITY, h))}, h
    assert co.above(ch(db, LOVE_CITY), person(db, LOVE_CITY, "kevin")) == []


def _elders_church(db):
    """Riverside, as a Church of Christ: the library's senior role is
    "Elders (Shepherds)" and three people share it. The owner (Clara, its
    secretary) holds the preaching minister's role; Bernice is an Admin
    login; Odell a Manager login who serves as a deacon, and one elder's row
    (wrongly) says he answers to Odell."""
    import church_roles as cr
    biz = next(b for b in db.t["businesses"] if b["id"] == RIVERSIDE)
    biz["name"] = "Westside Church of Christ"
    assert cr.ensure_library(biz)["church_type"] == "coc"
    elders = next(d for d in db.t["church_role_defs"] if d["business_id"] == RIVERSIDE and d["job"] == "senior")
    assert elders["title"] == "Elders (Shepherds)"
    c = c3._Church(db, RIVERSIDE, 4, "riversideame.org")
    c.hold(elders["key"], "henry", "lois", "walter")
    c.hold("preaching_minister", "clara")
    c.hold("deacons", "odell")
    bernice = c.login(1, "bernice", "admin")
    odell = c.login(2, "odell", "manager", tie=True)
    for h in db.t["church_leader_roles"]:
        if h["business_id"] == RIVERSIDE and h["contact_id"] == db.who[RIVERSIDE]["henry"]:
            h["answers_to_contact_id"] = db.who[RIVERSIDE]["odell"]
    return bernice, odell


def test_at_an_elders_church_the_owner_is_over_the_elders_and_no_one_else_is(db):
    bernice, odell = _elders_church(db)
    w = db.who[RIVERSIDE]
    elders = {w["henry"], w["lois"], w["walter"]}
    owner = under(db, RIVERSIDE, login(db, RIVERSIDE, "owner"))
    assert elders <= {r["id"] for r in owner}
    assert {r["why"] for r in owner if r["id"] in elders} == {"Elders (Shepherds)"}
    assert w["clara"] not in {r["id"] for r in owner}, "never the owner's own person"
    for uid in (bernice, odell):
        assert not elders & {r["id"] for r in under(db, RIVERSIDE, co.who(co.LOGIN, uid))}, uid
    assert not elders & {r["id"] for r in under(db, RIVERSIDE, person(db, RIVERSIDE, "odell"))}, "answers-to or not"
    c = ch(db, RIVERSIDE)
    assert elders == c.seniors and co.is_over(c, login(db, RIVERSIDE, "owner"), person(db, RIVERSIDE, "henry"))
    assert [(r["kind"], r["id"]) for r in co.above(ch(db, RIVERSIDE), person(db, RIVERSIDE, "lois"))] == [
        (co.LOGIN, c3.R_OWNER)]


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
    assert {"Yolanda", "Tyrone", "Ruth", "Paul", "Eve"} <= people
    assert not {"Andre", "Marcus", "Tanya"} & people, "the pastors and elders: the owner's alone, closed"
    owner = under(db, LOVE_CITY, login(db, LOVE_CITY, "owner"))
    assert {"Andre", "Marcus", "Tanya"} <= {db.label[r["id"]] for r in owner}
    assert "Kevin" not in people, "never the owner's own person"
    assert not {"Naiya", "Jessica", "Minnie"} & people, "an office login is its login"
    assert under(db, LOVE_CITY, login(db, LOVE_CITY, "naiya")) == []



# ─── Pastors and elders: no office standing over them ─────────────────
# Kevin, 2026-11-12: "admins can not give work to elders and pastors but
# they can give them things that is related to their area that they need for
# them to have." Who shepherds is each role's own switch, never a title.

def _labels(db, rows, kind=co.PERSON):
    return {db.label[r["id"]] for r in rows if r["kind"] == kind}


def test_love_city_an_admin_is_over_no_pastor_or_elder_and_every_other_leader_as_before(db):
    c = ch(db, LOVE_CITY)
    w = db.who[LOVE_CITY]
    assert c.shepherds == {w[h] for h in ("jessica", "andre", "marcus", "tanya")}, \
        "the Prophets' switch is off and the Ministers setting is off"
    minnie = under(db, LOVE_CITY, login(db, LOVE_CITY, "minnie"))
    assert not {"Andre", "Marcus", "Tanya", "Jessica", "Kevin"} & _labels(db, minnie)
    assert {"Yolanda", "Tyrone", "Ruth", "Iris", "Ivy", "Paul", "Eve", "Tasha", "Cora", "Angela"} <= _labels(db, minnie)
    assert not co.is_over(c, login(db, LOVE_CITY, "minnie"), person(db, LOVE_CITY, "marcus"))
    owner = under(db, LOVE_CITY, login(db, LOVE_CITY, "owner"))
    assert {"Andre", "Marcus", "Tanya"} <= _labels(db, owner) and "Jessica" in _labels(db, owner, co.LOGIN)


def test_love_city_the_map_still_counts_through_a_seats_own_person(db):
    """Marcus (an elder) answers to Jessica on the map: her login is over him
    through her person, not through her seat."""
    jess = under(db, LOVE_CITY, login(db, LOVE_CITY, "jessica"))
    assert [(db.label[r["id"]], r["why"]) for r in jess if r["kind"] == co.PERSON] == [("Marcus", "Answers to you")]
    # An Admin whose own person an elder answers to is over that elder, the
    # same way, and still over no other.
    w = db.who[LOVE_CITY]
    db.t["church_leader_roles"].append({
        "id": db.nid("church_leader_roles"), "business_id": LOVE_CITY, "contact_id": w["minnie"], "role": "ministers",
        "scope": "", "status": "active", "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None,
        "answers_to_contact_id": None})
    for h in db.t["church_leader_roles"]:
        if h["business_id"] == LOVE_CITY and h["contact_id"] == w["tanya"]:
            h["answers_to_contact_id"] = w["minnie"]
    minnie = under(db, LOVE_CITY, login(db, LOVE_CITY, "minnie"))
    assert ("Tanya", "Answers to you") in [(db.label[r["id"]], r["why"]) for r in minnie]
    assert not {"Andre", "Marcus"} & _labels(db, minnie)


def test_love_city_a_role_that_follows_the_ministers_setting_shepherds_by_it(db):
    assert "Angela" in _labels(db, under(db, LOVE_CITY, login(db, LOVE_CITY, "minnie")))
    db.t.setdefault("church_shepherd_settings", []).append({"business_id": LOVE_CITY, "ministers": True})
    assert "Angela" not in _labels(db, under(db, LOVE_CITY, login(db, LOVE_CITY, "minnie")))


def test_grace_its_deacons_shepherd_by_their_switch_so_the_admin_is_over_its_youth_minister_only(db):
    c = ch(db, GRACE)
    w = db.who[GRACE]
    deacons = {w[h] for h in ("daniel", "doris", "dwight", "della")}
    assert c.shepherds == deacons, "a care job whose switch the church turned on"
    thelma = under(db, GRACE, login(db, GRACE, "thelma"))
    assert not deacons & {r["id"] for r in thelma} and "Yvette" in _labels(db, thelma)
    assert deacons <= {r["id"] for r in under(db, GRACE, login(db, GRACE, "owner"))}


def test_grace_with_the_map_closed_the_lanes_overseer_is_over_its_leaders_but_no_deacon(monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    db = c3.build(monkeypatch, map_on=False)
    sharon = under(db, GRACE, login(db, GRACE, "sharon"))
    assert "Yvette" in _labels(db, sharon)
    assert not {"Daniel", "Doris", "Dwight", "Della", "Samuel"} & _labels(db, sharon)


def test_new_hope_an_admin_is_over_no_associate_pastor_or_elder_nor_an_elders_login(db):
    nh, w = NEW_HOPE, db.who[NEW_HOPE]
    pastors = {w[h] for h in ("abel", "amara", "asher", "elena", "elliot", "esther", "ezra", "eden")}
    assert ch(db, nh).shepherds == pastors
    tessa = under(db, nh, login(db, nh, "tessa"))
    assert not pastors & {r["id"] for r in tessa}
    assert {"Yusuf", "Wren", "Kara", "Celia"} <= _labels(db, tessa) and "Owen" in _labels(db, tessa, co.LOGIN)
    # The ministry chain is as it was: Amara is over the elder who answers to her.
    amara = under(db, nh, person(db, nh, "amara"))
    assert ("Elena", "Answers to you") in [(db.label[r["id"]], r["why"]) for r in amara]
    # An elder with a Manager seat: no Admin's or lanes overseer's office
    # standing reaches it; the owner's does.
    elena = "3a000000-0000-4000-8000-000000000098"
    db.t["business_users"].append({"business_id": nh, "user_id": elena, "role": "manager",
                                   "invited_email": "elena@newhope.church", "lane": None, "areas": ["people_care"],
                                   "contact_id": w["elena"], "name": "Elena Ruiz", "status": "active"})
    db.label[elena] = "Elena"
    for h in ("tessa", "owen"):
        assert elena not in {r["id"] for r in under(db, nh, login(db, nh, h))}, h
    assert elena in {r["id"] for r in under(db, nh, login(db, nh, "owner"))}


def test_riverside_with_nobody_set_up_guards_no_one_and_an_admin_is_over_no_one(db):
    c = ch(db, RIVERSIDE)
    assert c.guarded == set()
    clerk = "4a000000-0000-4000-8000-000000000097"
    db.t["business_users"].append({"business_id": RIVERSIDE, "user_id": clerk, "role": "admin",
                                   "invited_email": "clerk@riversideame.org", "lane": None, "areas": None,
                                   "contact_id": None, "name": "Church Clerk", "status": "active"})
    assert under(db, RIVERSIDE, co.who(co.LOGIN, clerk)) == []


def test_a_failed_read_of_the_ministers_setting_is_a_503_never_a_yes(db, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_shepherd_settings") else real(path, **kw))
    with pytest.raises(HTTPException) as e:
        under(db, LOVE_CITY, login(db, LOVE_CITY, "minnie"))
    assert e.value.status_code == 503
    # The owner's standing needs no guard, so it never reads it.
    assert "Andre" in _labels(db, under(db, LOVE_CITY, login(db, LOVE_CITY, "owner")))


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
