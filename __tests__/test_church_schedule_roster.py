"""The leaders schedule: the switch, and who is on it (church_schedule.py;
docs/CHURCH_SCHEDULE.md, PR S1-2). Kevin, 2026-11-18: "I want to be able to
build Leaders schedule ... there should volunteers one and one for
leadership", and on the five calls: "Yes build to all five" (core leaders are
whoever the church's own roles, groups, departments and seats say, the office
as its own group, and any name can be added or removed).

Pins, at the four test churches (church_three), through the real routes:
  * the switch: off | owner | on, owner when unset, a typo is off; closed,
    another church under `owner`, not a church, and before the migration are
    all a 404; conftest pins "before the migration" for every other suite
  * ready(): only "no such table" says the tables aren't there; a blip keeps
    the last answer
  * the roster is the leaders room split by who has an office login, read
    from the church's data: someone who leads and has a login counts in
    `leaders`; Riverside, with nobody set up, is empty
  * the church's own lists: add (to a group), remove, put back; only the
    owner and whoever oversees the office change them, never an Admin; the
    answer is the schedule as it stands after; a failed read or write is a
    503 with nothing saved
  * who an ask goes to: a department's leader, a group's leader with no
    role, a Manager, an Admin, the office overseer, a senior, the owner
  * the notice days: 14 until the church says; the same two set them
  * the member side's kept roster: a minute a replica, forgotten on a change,
    never kept from a failed read
  * every office handler here reaches a gate that raises
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_duties as cd  # noqa: E402
import church_over as co  # noqa: E402
import church_schedule as cs  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_three as c3  # noqa: E402
import member_portal_messaging as mpm  # noqa: E402
import sb_clients  # noqa: E402
from church_schedule_fake import as_  # noqa: E402
from church_three import FOUR, GRACE, LOVE_CITY, NEW_HOPE, RIVERSIDE  # noqa: E402


@pytest.fixture
def db(monkeypatch):
    return fake.build(monkeypatch)


@pytest.fixture
def app(db):
    return fake.client(db)


def church(db, biz):
    return co.Church(c3.church(db, biz))


def names(db, ids):
    return sorted(db.label[i] for i in ids)


def people(app, biz):
    r = app.get(f"/church/schedule/people?business_id={biz}")
    assert r.status_code == 200, r.text
    return r.json()


def listed(app, biz, handle, how, **kw):
    return app.put("/church/schedule/people", json={"business_id": biz, "contact_id": app.db.who[biz][handle],
                                                    "listed": how, **kw})


def group(got, key):
    return sorted(p["name"].split()[0] for p in got[key])


# ─── The switch ───────────────────────────────────────────────────────

def test_the_switch_is_owner_when_unset_and_a_typo_is_off(monkeypatch):
    monkeypatch.delenv("CHURCH_SCHEDULE", raising=False)
    assert cs.mode() == "owner"
    for said, want in (("on", "on"), (" OFF ", "off"), ("owner", "owner"), ("yes", "off"), ("", "owner")):
        monkeypatch.setenv("CHURCH_SCHEDULE", said)
        assert cs.mode() == want, said


def test_every_other_suite_starts_before_the_migration_and_gains_no_read(monkeypatch):
    """conftest's pin: without it, the default `owner` mode would add a
    platform-church lookup to every reader that asks church_schedule.on."""
    assert cs._FORCE is False and cs.ready() is False
    read = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: read.append(path) or [])
    monkeypatch.setenv("CHURCH_SCHEDULE", "on")
    assert cs.on(LOVE_CITY) is False and read == []


def test_ready_asks_the_database_and_only_no_such_table_says_no(monkeypatch):
    monkeypatch.setattr(cs, "_FORCE", None)
    monkeypatch.setattr(cs, "_STATE", {"yes": None, "at": 0.0})
    monkeypatch.setattr(sb_clients, "sb_url", lambda: "https://db.example")
    said = {"rows": None, "err": None, "asked": 0}

    def get(path, **k):
        said["asked"] += 1
        assert path == "/church_away_asks?select=id&limit=1"
        return said["rows"]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "last_error", lambda: said["err"])
    clock = {"t": 1000.0}
    monkeypatch.setattr(cs.clock, "monotonic", lambda: clock["t"])

    assert cs.ready() is False, "a blip with nothing known yet reads as not there"
    clock["t"] += 61
    said["err"] = {"status": 404, "code": "PGRST205", "message": "Could not find the table"}
    assert cs.ready() is False
    assert cs.ready() is False and said["asked"] == 2, "a no is kept a minute"
    clock["t"] += 61
    said["rows"], said["err"] = [], None
    assert cs.ready() is True
    clock["t"] += 599
    assert cs.ready() is True and said["asked"] == 3, "a yes is kept ten minutes"
    clock["t"] += 2
    said["rows"], said["err"] = None, {"status": 503, "code": "", "message": "upstream"}
    assert cs.ready() is True, "a blip keeps the last answer"
    clock["t"] += 601
    said["err"] = {"status": 404, "code": "42P01", "message": 'relation "church_away_asks" does not exist'}
    assert cs.ready() is False
    monkeypatch.setattr(sb_clients, "sb_url", lambda: "")
    monkeypatch.setattr(cs, "_STATE", {"yes": None, "at": 0.0})
    assert cs.ready() is False and said["asked"] == 5, "no database to ask (a script) is a no, unasked"


ROUTES = [("get", "/church/schedule/status?business_id={b}", None),
          ("get", "/church/schedule/people?business_id={b}", None),
          ("put", "/church/schedule/people", {"contact_id": "x", "listed": "add"}),
          ("get", "/church/schedule/leaders?business_id={b}", None),
          ("get", "/church/schedule/asks?business_id={b}", None),
          ("post", "/church/schedule/asks", {"starts_on": "2026-12-20", "ends_on": "2026-12-27", "kind": "time_off"}),
          ("post", "/church/schedule/asks/5e000000-0000-4000-8000-000000000001/answer", {"yes": True}),
          ("post", "/church/schedule/asks/5e000000-0000-4000-8000-000000000001/withdraw", {}),
          ("get", "/church/schedule/settings?business_id={b}", None),
          ("put", "/church/schedule/settings", {"notice_days": 7})]


def every_route(app, biz):
    out = []
    for verb, path, body in ROUTES:
        kw = {"json": {"business_id": biz, **body}} if body is not None else {}
        out.append((path, getattr(app, verb)(path.format(b=biz), **kw).status_code))
    return out


def test_closed_every_route_is_a_404_and_writes_nothing(app, db, monkeypatch):
    monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    as_(app, LOVE_CITY, "owner")
    assert {code for _p, code in every_route(app, LOVE_CITY)} == {404}
    assert not db.t["church_away_asks"] and not db.t["church_schedule_people"] and not db.t["church_schedule_settings"]


def test_before_the_migration_every_route_is_a_404(app, db, monkeypatch):
    monkeypatch.setattr(cs, "_FORCE", False)
    as_(app, LOVE_CITY, "owner")
    assert {code for _p, code in every_route(app, LOVE_CITY)} == {404}
    assert not [p for p in db.reads if "church_away_asks" in p or "church_schedule" in p], "nothing asks for its tables"


def test_with_owner_only_the_platform_owners_church_is_open(app, db, monkeypatch):
    monkeypatch.setenv("CHURCH_SCHEDULE", "owner")
    as_(app, LOVE_CITY, "owner")
    assert app.get(f"/church/schedule/status?business_id={LOVE_CITY}").status_code == 200
    as_(app, LOVE_CITY, "minnie")
    assert app.get(f"/church/schedule/status?business_id={LOVE_CITY}").status_code == 200, "the church is open, so its office is"
    for biz, handle in ((GRACE, "owner"), (GRACE, "thelma"), (NEW_HOPE, "owner"), (RIVERSIDE, "owner")):
        as_(app, biz, handle)
        assert {code for _p, code in every_route(app, biz)} == {404}, (biz, handle)


def test_a_business_that_isnt_a_church_and_a_login_with_no_seat_get_a_404(app, db):
    as_(app, LOVE_CITY, "owner")
    next(b for b in db.t["businesses"] if b["id"] == GRACE)["type"] = "coach"
    as_(app, GRACE, "owner")
    assert {code for _p, code in every_route(app, GRACE)} == {404}
    as_(app, GRACE, "owner")                                     # Grace's pastor has no seat at New Hope
    assert {code for _p, code in every_route(app, NEW_HOPE)} == {404}


def test_the_router_is_registered_well_before_the_public_sites_catch_all():
    with open(os.path.join(ROOT, "kmj_intake_automation.py"), encoding="utf-8") as f:
        src = f.read()
    mine = src.index("app.include_router(church_schedule_router)")
    assert src.index("app.include_router(church_handovers_router)") < mine < src.index(
        "app.include_router(public_site_router)")
    assert src.count("app.include_router(church_schedule_router)") == 1


def test_no_rule_here_reads_a_title_word_a_role_key_or_a_real_name():
    """Who is on the schedule, and who is over whom, come from the church's
    own data (docs/CHURCH_LEADERS_MAP.md's rule: words suggest, data decides)."""
    import re
    with open(os.path.join(ROOT, "church_schedule.py"), encoding="utf-8") as f:
        src = f.read()
    assert not re.search(r"pastor|elder|deacon|minister|bishop|executive|treasurer|secretary|love.city", src, re.I)


def test_every_office_handler_here_reaches_a_gate_that_raises():
    import ownership_sweep
    got = ownership_sweep.sweep()
    mine = [h for h in got["handlers"] if h["module"] == "church_schedule"]
    assert len(mine) >= 5, "the reads take a business id"
    assert not [h["fn"] for h in got["unguarded"] if h["module"] == "church_schedule"]


# ─── Who is on the schedule ───────────────────────────────────────────

@pytest.mark.parametrize("biz", FOUR)
def test_the_roster_is_the_leaders_room_split_by_who_has_an_office_login(db, biz):
    ch = church(db, biz)
    r = cs.roster(ch)
    room = {p["contact_id"] for p in mpm.leaders_room_people(biz)}
    assert r.people() == room and not (r.leaders & r.office)
    assert set(ch.person_login) == mpm.office_contacts(biz), "the same people, by church_over's own match"
    leads = mpm.leading_people(biz)
    assert r.leaders == leads and r.office == set(ch.person_login) - leads
    assert room == leads | mpm.office_contacts(biz), "the room is who leads, and the office"
    assert r.added == {} and r.removed == set()
    assert cs.office_overseers(ch) == sorted(cd.manager_holders(biz, co.OVERSEE)), "church_duties' own answer"


def test_love_city_by_name(db):
    r = cs.roster(church(db, LOVE_CITY))
    assert names(db, r.leaders) == ["Andre", "Angela", "Cora", "Eve", "Gloria", "Jessica", "Kevin", "Marcus", "Paul",
                                    "Ruth", "Tanya", "Tasha", "Tyrone", "Yolanda"]
    assert names(db, r.office) == ["Laquesha", "Minnie", "Naiya", "Shapretta", "Tiara"]
    w = db.who[LOVE_CITY]
    assert r.group_of(w["jessica"]) == "leaders", "she leads and has an office login: counted with the leaders"
    assert r.group_of(w["gloria"]) == "leaders", "a group's leader with no role"
    assert r.group_of(w["iris"]) is None, "holds a role that leads nothing"
    assert r.group_of(w["calvin"]) is None and r.group_of(None) is None


def test_grace_new_hope_and_riverside(db):
    r = cs.roster(church(db, GRACE))
    assert names(db, r.leaders) == ["Daniel", "Samuel", "Yvette"] and names(db, r.office) == ["Sharon", "Thelma"]
    r = cs.roster(church(db, NEW_HOPE))
    assert "Owen" in names(db, r.leaders) and "Owen" not in names(db, r.office), "the operations director leads"
    assert names(db, r.office) == ["Kira", "Mila", "Olive", "Paige", "Sunny", "Tessa"]
    r = cs.roster(church(db, RIVERSIDE))
    assert r.people() == set(), "nobody set up: nobody on it, the pastor included, until the church adds a name"


def test_with_the_map_closed_the_roster_still_comes_from_roles_and_groups(monkeypatch):
    d = fake.build(monkeypatch, map_on=False, filled=False)
    r = cs.roster(church(d, LOVE_CITY))
    assert {"Kevin", "Jessica", "Andre", "Yolanda", "Gloria"} <= set(names(d, r.leaders))
    assert names(d, r.office) == ["Laquesha", "Minnie", "Naiya", "Shapretta", "Tiara"]


def test_the_page_says_who_each_one_is_and_who_may_change_it(app, db):
    as_(app, LOVE_CITY, "owner")
    got = people(app, LOVE_CITY)
    assert set(got) == {"leaders", "office", "added", "removed", "can_change"} and got["can_change"] is True
    assert len(got["leaders"]) == 14 and len(got["office"]) == 5 and got["added"] == got["removed"] == []
    by = {p["name"].split()[0]: p for p in got["leaders"] + got["office"]}
    assert set(by["Yolanda"]) == {"contact_id", "name", "what", "department"}
    assert by["Yolanda"]["what"] == "Youth Pastor" and by["Yolanda"]["department"]["name"] == "Youth"
    assert by["Tyrone"]["what"] == "Youth Ministry (YWD) leader" and by["Tyrone"]["department"]["name"] == "Youth"
    assert by["Gloria"]["what"] == "Leads Sisters in the City" and by["Gloria"]["department"] is None
    assert by["Laquesha"]["what"] == "Office · Sunday & Serving" and by["Minnie"]["what"] == "Office · Treasurer"
    assert [p["name"] for p in got["leaders"]] == sorted(p["name"] for p in got["leaders"]), "by name"
    as_(app, LOVE_CITY, "jessica")
    assert people(app, LOVE_CITY)["can_change"] is True, "whoever oversees the office"
    for handle in ("minnie", "naiya", "laquesha"):
        as_(app, LOVE_CITY, handle)
        assert people(app, LOVE_CITY)["can_change"] is False, handle


def test_who_reads_the_page(app, db):
    fake.seat(db, LOVE_CITY, "yolanda")
    fake.seat(db, LOVE_CITY, "calvin")
    as_(app, LOVE_CITY, "yolanda")
    assert people(app, LOVE_CITY)["can_change"] is False, "a leader on a Member seat is on the schedule"
    as_(app, LOVE_CITY, "calvin")
    r = app.get(f"/church/schedule/people?business_id={LOVE_CITY}")
    assert r.status_code == 403 and r.json()["detail"] == cs.NOT_ON
    assert app.get(f"/church/schedule/settings?business_id={LOVE_CITY}").status_code == 403
    as_(app, LOVE_CITY, "owner")
    assert listed(app, LOVE_CITY, "minnie", "remove").status_code == 200
    as_(app, LOVE_CITY, "minnie")
    assert people(app, LOVE_CITY)["can_change"] is False, "an Admin reads it even when off it"


# ─── The church's own lists ───────────────────────────────────────────

def test_the_owner_adds_a_name_takes_one_off_and_puts_them_back(app, db):
    as_(app, LOVE_CITY, "owner")
    r = listed(app, LOVE_CITY, "calvin", "add")
    assert r.status_code == 200, r.text
    got = r.json()
    assert "Calvin" in group(got, "leaders"), "leaders unless it says the office"
    assert got["added"] == [{"contact_id": db.who[LOVE_CITY]["calvin"], "name": "Calvin Owens", "group": "leaders"}]
    assert got == people(app, LOVE_CITY), "the answer is the schedule as it stands after"
    row = db.t["church_schedule_people"][0]
    assert (row["listed"], row["grp"], row["set_by"]) == ("add", "leaders", c3.church(db, LOVE_CITY)["owner_id"])

    got = listed(app, LOVE_CITY, "calvin", "add", group="office").json()
    assert "Calvin" in group(got, "office") and "Calvin" not in group(got, "leaders")
    assert len(db.t["church_schedule_people"]) == 1, "one row a person"

    got = listed(app, LOVE_CITY, "gloria", "remove").json()
    assert "Gloria" not in group(got, "leaders") and group(got, "removed") == ["Gloria"]
    assert got == people(app, LOVE_CITY)

    got = listed(app, LOVE_CITY, "jessica", "add", group="office").json()
    assert "Jessica" in group(got, "office") and "Jessica" not in group(got, "leaders"), "an add says which group"

    for handle in ("calvin", "gloria", "jessica"):
        r = listed(app, LOVE_CITY, handle, None)
        assert r.status_code == 200, r.text
    got = r.json()
    assert got["added"] == got["removed"] == [] and db.t["church_schedule_people"] == []
    assert "Gloria" in group(got, "leaders") and "Jessica" in group(got, "leaders") and "Calvin" not in group(got, "leaders")
    assert not db.refused


def test_whoever_oversees_the_office_changes_it_and_an_admin_never_does(app, db):
    """Decision 7: the roster is the owner's and the office overseer's."""
    as_(app, LOVE_CITY, "jessica")
    assert listed(app, LOVE_CITY, "calvin", "add").status_code == 200
    fake.seat(db, LOVE_CITY, "yolanda")
    for handle in ("minnie", "naiya", "laquesha", "tiara", "yolanda"):
        as_(app, LOVE_CITY, handle)
        for how in ("add", "remove", None):
            r = listed(app, LOVE_CITY, "dana", how)
            assert r.status_code == 403 and r.json()["detail"] == cs.NOT_SETTER, (handle, how)
    assert len(db.t["church_schedule_people"]) == 1
    as_(app, GRACE, "thelma")
    assert listed(app, GRACE, "leon", "add").status_code == 403, "Grace's Admin"
    as_(app, GRACE, "sharon")
    assert listed(app, GRACE, "leon", "add").status_code == 200, "Grace's secretary oversees its office"


def test_what_a_change_refuses(app, db):
    as_(app, LOVE_CITY, "owner")
    r = app.put("/church/schedule/people", json={"business_id": LOVE_CITY, "contact_id": db.who[GRACE]["leon"],
                                                 "listed": "add"})
    assert r.status_code == 400 and r.json()["detail"] == cs.NOT_PERSON, "another church's person"
    assert listed(app, LOVE_CITY, "calvin", "maybe").status_code == 400
    assert listed(app, LOVE_CITY, "calvin", "add", group="volunteers").status_code == 400
    assert app.put("/church/schedule/people", json={"business_id": LOVE_CITY, "contact_id": "nobody",
                                                    "listed": "add"}).status_code == 400
    assert db.t["church_schedule_people"] == [] and not db.refused, "refused before the database was asked"


def test_a_failed_write_is_a_503_with_nothing_saved(app, db):
    as_(app, LOVE_CITY, "owner")
    db.fail = {"post": "/church_schedule_people"}
    r = listed(app, LOVE_CITY, "calvin", "add")
    assert r.status_code == 503 and r.json()["detail"] == cs.UNSAVED and db.t["church_schedule_people"] == []
    db.fail = {}
    assert listed(app, LOVE_CITY, "calvin", "add").status_code == 200
    db.fail = {"delete": "/church_schedule_people"}
    assert listed(app, LOVE_CITY, "calvin", None).status_code == 503 and len(db.t["church_schedule_people"]) == 1
    db.fail = {}
    assert "Calvin" in group(people(app, LOVE_CITY), "leaders")


@pytest.mark.parametrize("table", ["/group_members", "/church_leader_roles", "/church_schedule_people", "/contacts",
                                   "/business_users"])
def test_a_failed_read_is_a_503_never_an_empty_schedule(app, db, table):
    as_(app, LOVE_CITY, "owner")
    db.fail = {"get": table}
    # /business_users and /contacts are read by the access check too, which fails closed the same way.
    assert app.get(f"/church/schedule/people?business_id={LOVE_CITY}").status_code == 503
    assert listed(app, LOVE_CITY, "calvin", "add").status_code == 503
    assert db.t["church_schedule_people"] == [], "nothing was saved"


def test_the_lists_are_read_whole_past_a_thousand_names(db):
    """New Hope has 500 people; a remove list longer than a page is still
    all of it (a read never takes the first 1,000 rows for every row)."""
    extra = [c3.pid(3, n) for n in range(600, 1900)]
    db.t["contacts"] += [{"id": c, "business_id": NEW_HOPE, "name": "X Member", "email": "", "status": "active"}
                         for c in extra]
    db.t["church_schedule_people"] += [{"business_id": NEW_HOPE, "contact_id": c, "listed": "remove", "grp": None}
                                       for c in extra]
    w = db.who[NEW_HOPE]
    db.t["church_schedule_people"].append({"business_id": NEW_HOPE, "contact_id": w["yusuf"], "listed": "remove",
                                           "grp": None})
    r = cs.roster(church(db, NEW_HOPE))
    assert len(r.removed) == 1301 and r.group_of(w["yusuf"]) is None


# ─── Who an ask goes to ───────────────────────────────────────────────

def to(db, biz, handle):
    got = cs.goes_to(church(db, biz), db.who[biz][handle])
    return (got["kind"], db.label[got["id"]], got["name"]) if got else None


def test_who_an_ask_goes_to_at_love_city(db):
    assert to(db, LOVE_CITY, "yolanda") == ("person", "Andre", "Andre Wallace"), "a department's leader: its overseer"
    assert to(db, LOVE_CITY, "tyrone") == ("person", "Yolanda", "Yolanda Reed"), "a team's leader: the department's"
    assert to(db, LOVE_CITY, "gloria") == ("login", "owner", "Pastor Kevin"), "a group's leader with no role"
    assert to(db, LOVE_CITY, "naiya") == ("login", "Jessica", "Jessica McCloud"), "a Manager: whoever oversees the office"
    assert to(db, LOVE_CITY, "minnie") == ("login", "owner", "Pastor Kevin"), "an Admin"
    assert to(db, LOVE_CITY, "jessica") == ("login", "owner", "Pastor Kevin"), "the office overseer, routed as her login"
    assert to(db, LOVE_CITY, "marcus") == ("login", "Jessica", "Jessica McCloud"), "an elder who answers to her"
    assert to(db, LOVE_CITY, "kevin") is None, "the owner's own person: nobody is over them"


def test_a_senior_goes_to_the_owner_only(db):
    assert to(db, LOVE_CITY, "cora") == ("person", "Andre", "Andre Wallace")
    db.t["church_leader_roles"].append({
        "id": db.nid("church_leader_roles"), "business_id": LOVE_CITY, "contact_id": db.who[LOVE_CITY]["cora"],
        "role": "pastor", "scope": "", "status": "active", "invited_at": "2026-10-01T00:00:00+00:00",
        "answered_at": None, "answers_to_contact_id": None})
    assert to(db, LOVE_CITY, "cora") == ("login", "owner", "Pastor Kevin")


def test_who_an_ask_goes_to_at_the_other_churches(db):
    assert to(db, GRACE, "yvette") == ("person", "Daniel", "Daniel Moore")
    assert to(db, GRACE, "sharon") == ("login", "owner", "Pastor Gray"), "the secretary oversees the office: the owner"
    assert to(db, GRACE, "samuel") is None
    assert to(db, NEW_HOPE, "sunny") == ("login", "Owen", "Owen Diaz")
    assert to(db, NEW_HOPE, "owen") == ("login", "owner", "Pastor Nathan")
    assert to(db, NEW_HOPE, "elena") == ("person", "Amara", "Amara Stone"), "an elder who answers to a pastor"
    assert to(db, RIVERSIDE, "henry") == ("login", "owner", "Pastor Whitfield"), "nothing set up: the owner"


# ─── The status ───────────────────────────────────────────────────────

def status(app, biz):
    r = app.get(f"/church/schedule/status?business_id={biz}")
    assert r.status_code == 200, r.text
    return r.json()


def test_status_says_who_i_am_here(app, db):
    w = db.who[LOVE_CITY]
    as_(app, LOVE_CITY, "owner")
    got = status(app, LOVE_CITY)
    assert got == {"open": True, "owner_how": "email", "notice_days": 14,
                   "me": {"person": w["kevin"], "group": "leaders", "goes_to": None, "sees_all": True, "can_set": True}}
    as_(app, LOVE_CITY, "jessica")
    me = status(app, LOVE_CITY)["me"]
    assert me["group"] == "leaders" and me["sees_all"] is True and me["can_set"] is True
    assert me["goes_to"] == {"kind": "login", "id": c3.church(db, LOVE_CITY)["owner_id"], "name": "Pastor Kevin"}
    as_(app, LOVE_CITY, "minnie")
    me = status(app, LOVE_CITY)["me"]
    assert (me["person"], me["group"], me["sees_all"], me["can_set"]) == (w["minnie"], "office", False, False)
    as_(app, LOVE_CITY, "naiya")
    assert status(app, LOVE_CITY)["me"]["goes_to"]["name"] == "Jessica McCloud"


def test_a_login_matched_to_no_person_has_none(app, db):
    """Decision 3: `person` is null, so the screen asks them to pick their record."""
    seat = next(s for s in db.t["business_users"] if s["user_id"] == db.who[LOVE_CITY]["shapretta@"])
    seat.update(invited_email="media@lovecity.org", contact_id=None)
    as_(app, LOVE_CITY, "shapretta")
    me = status(app, LOVE_CITY)["me"]
    assert me == {"person": None, "group": None, "goes_to": None, "sees_all": False, "can_set": False}
    assert app.get(f"/church/schedule/people?business_id={LOVE_CITY}").status_code == 403
    as_(app, RIVERSIDE, "owner")
    me = status(app, RIVERSIDE)["me"]
    assert me["person"] == db.who[RIVERSIDE]["clara"] and me["group"] is None and me["can_set"] is True


# ─── The notice days ──────────────────────────────────────────────────

def test_notice_is_fourteen_days_until_the_church_says(app, db):
    as_(app, LOVE_CITY, "naiya")
    assert app.get(f"/church/schedule/settings?business_id={LOVE_CITY}").json() == {"notice_days": 14}
    for handle in ("minnie", "naiya", "laquesha"):
        as_(app, LOVE_CITY, handle)
        r = app.put("/church/schedule/settings", json={"business_id": LOVE_CITY, "notice_days": 7})
        assert r.status_code == 403 and r.json()["detail"] == cs.NOT_SETTER, handle
    assert db.t["church_schedule_settings"] == []
    as_(app, LOVE_CITY, "owner")
    r = app.put("/church/schedule/settings", json={"business_id": LOVE_CITY, "notice_days": 7})
    assert r.status_code == 200 and r.json() == {"notice_days": 7}
    as_(app, LOVE_CITY, "jessica")
    assert app.put("/church/schedule/settings", json={"business_id": LOVE_CITY, "notice_days": 0}).json() == {"notice_days": 0}
    assert len(db.t["church_schedule_settings"]) == 1, "one row a church"
    as_(app, LOVE_CITY, "naiya")
    assert app.get(f"/church/schedule/settings?business_id={LOVE_CITY}").json() == {"notice_days": 0}
    assert status(app, LOVE_CITY)["notice_days"] == 0
    assert cs.settings(church(db, GRACE)) == {"notice_days": 14}, "another church's is its own"


def test_what_the_notice_days_refuse_and_a_failed_write(app, db):
    as_(app, LOVE_CITY, "owner")
    for bad in (-1, 91, "7", None, 3.5, True):
        r = app.put("/church/schedule/settings", json={"business_id": LOVE_CITY, "notice_days": bad})
        assert r.status_code == 400, bad
    db.fail = {"post": "/church_schedule_settings"}
    r = app.put("/church/schedule/settings", json={"business_id": LOVE_CITY, "notice_days": 7})
    assert r.status_code == 503 and db.t["church_schedule_settings"] == []
    db.fail = {"get": "/church_schedule_settings"}
    assert app.get(f"/church/schedule/settings?business_id={LOVE_CITY}").status_code == 503, "never the default instead"
    assert app.get(f"/church/schedule/status?business_id={LOVE_CITY}").status_code == 503


# ─── The member side's kept roster ────────────────────────────────────

def test_the_kept_roster_is_read_once_a_minute_and_forgotten_on_a_change(app, db, monkeypatch):
    clock = {"t": 500.0}
    monkeypatch.setattr(cs.clock, "monotonic", lambda: clock["t"])
    biz = c3.church(db, LOVE_CITY)
    first = cs.roster_kept(biz)
    assert names(db, first.office) == ["Laquesha", "Minnie", "Naiya", "Shapretta", "Tiara"]
    n = len(db.reads)
    assert cs.roster_kept(LOVE_CITY) is first and len(db.reads) == n, "kept: no read"
    as_(app, LOVE_CITY, "owner")
    assert listed(app, LOVE_CITY, "calvin", "add").status_code == 200
    assert cs.roster_kept(LOVE_CITY).group_of(db.who[LOVE_CITY]["calvin"]) == "leaders", "a change is seen at once here"
    db.t["church_schedule_people"].clear()                       # another replica's change
    assert cs.roster_kept(LOVE_CITY).group_of(db.who[LOVE_CITY]["calvin"]) == "leaders", "up to a minute late"
    clock["t"] += 61
    assert cs.roster_kept(LOVE_CITY).group_of(db.who[LOVE_CITY]["calvin"]) is None


def test_a_kept_roster_that_couldnt_be_read_is_none_and_never_kept(db):
    db.fail = {"get": "/church_schedule_people"}
    assert cs.roster_kept(LOVE_CITY) is None
    db.fail = {}
    assert cs.roster_kept(LOVE_CITY) is not None
    assert cs.roster_kept("5b000000-0000-4000-8000-000000000000") is None, "no such church"
