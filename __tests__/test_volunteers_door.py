"""Sunday's teams belong to ChurchSavvy or to Volunteers (sunday_planning.py,
supabase/APPLY-2026-11-02-serve-team-owner.sql). Kevin, 2026-11-02:
"churchsavvy is shapretta because that has to do with the service projection
and order of service for production team and partnering with worship team.
volunteers and roles laquesha is doing is her assignment", then "yes
churchsavvy for worship team, announcements to shapretta. go".

Pins:
  * the parts table: serve_schedule makes a scheduler, who schedules and
    never plans, sings, runs the screens or sets up; never an invite
  * in a church, every write on a team (its turns, places, who's trained,
    an ask, an offer, an answer, taking an ask back, filling, stopping it)
    by each persona on each kind of team: the owner and an Admin any; a
    production_schedule or churchsavvy_team holder (Shapretta) ChurchSavvy's;
    a serve_schedule holder (Laquesha) Volunteers'; ChurchSavvy's own team
    (the worship pastor) ChurchSavvy's; a Manager with neither is told whose
    job it is; a booth volunteer and a viewer seat are refused as before
  * reads stay whole: everyone who opens Planning sees every team and every
    ask; owner= shows one door's teams
  * a new team's owner: the one asked for, else its maker's one door, else
    its name
  * filling and taking a fill back keep to your own teams, and the whole
    Sunday still keeps anyone from being asked twice the same hour
  * a business that isn't a church, and a church on ChurchSavvy alone, are
    unchanged and read no duties
  * before the migration every team is Volunteers' and nothing is a 500
  * a duties read that fails is a 503, never a yes

The duties each login holds are the test's (church_duties.standing, as the
split lanes give them); the refusals are church_duties.refusal's own words."""
from __future__ import annotations

import os
import sys
import uuid as uuidlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_marketing  # noqa: E402
import church_duties as cd  # noqa: E402
import sb_clients  # noqa: E402
import sunday_planning as sp  # noqa: E402
import worship_team as wt  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_sunday_planning import (BIZ, JO, KENDRA, LEE, NOW, OWNER_EMAIL, PRODUCTION, WELCOME, ZONE,  # noqa: E402
                                  FakeDb)

WHO = ("owner", "admin", "laquesha", "shapretta", "tiara", "pastor", "booth", "viewer")
PEOPLE = {name: AuthedUser(id=f"u-{name}", email=f"{name}@lovecity.org", role="authenticated") for name in WHO}
PEOPLE["owner"] = AuthedUser(id="u-owner", email=OWNER_EMAIL, role="authenticated")
SEATS = {"u-owner": "owner", "u-admin": "admin", "u-laquesha": "manager", "u-shapretta": "manager",
         "u-tiara": "manager", "u-viewer": "viewer"}
# What each login does at Love City once the duties split (the catalog may
# not have production_schedule yet: standing is the test's).
DUTIES = {
    "u-laquesha": {"serve_schedule", "serve_teams", "background_checks", "rooms", "events", "attendance"},
    "u-shapretta": {"production_schedule", "churchsavvy_team", "sunday_plan", "stream", "posts", "clips"},
    "u-tiara": {"care_board", "shepherding", "kids"},
}
VOL, CS = sp.VOLUNTEERS, sp.CHURCHSAVVY


def _cs_duty():
    return "production_schedule" if "production_schedule" in cd.CATALOG else "churchsavvy_team"


def refused(owner):
    """What a login that doesn't change this owner's teams is told."""
    return cd.refusal(BIZ, _cs_duty() if owner == CS else "serve_schedule")


@pytest.fixture
def church(monkeypatch):
    db = FakeDb()
    db.t["businesses"][0]["type"] = "ministry"
    db.t["worship_team"] = [
        {"id": str(uuidlib.uuid4()), "business_id": BIZ, "user_id": "u-pastor", "name": "Pastor Dee",
         "roles": ["planner"], "status": "active"},
        {"id": str(uuidlib.uuid4()), "business_id": BIZ, "user_id": "u-booth", "name": "Sam",
         "roles": ["booth"], "status": "active"},
    ]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", db.delete)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("SUNDAY_PLANNING", "on")
    monkeypatch.delenv("CHURCHSAVVY_BILLING", raising=False)
    monkeypatch.setattr(wt, "role_of", lambda biz, uid: SEATS.get(uid))
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: ZONE)
    monkeypatch.setattr(sp, "_now", lambda: NOW)
    standing = {"duties": dict(DUTIES), "calls": 0, "broken": False}

    def fake_standing(biz, uid):
        standing["calls"] += 1
        if standing["broken"]:
            raise HTTPException(503, "Who does what couldn't be read just now. Try again.")
        role = SEATS.get(str(uid))
        if role in ("owner", "admin"):
            return {"church": True, "role": role, "lanes": [], "duties": cd.ALL}
        held = standing["duties"].get(str(uid), set()) if role == "manager" else set()
        return {"church": True, "role": role, "lanes": [], "duties": frozenset(held)}
    monkeypatch.setattr(cd, "standing", fake_standing)
    monkeypatch.setitem(sp._no_column, "at", 0.0)
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    app.include_router(sp.router)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client

    # Two Sundays; ChurchSavvy's Production (Sound) and Volunteers' Welcome
    # (Greeter), each with someone trained and asked for the second Sunday.
    assert as_("owner").post("/planning/sundays", json={"business_id": BIZ, "count": 2}).status_code == 200
    s1, s2 = (s["id"] for s in sorted(db.t["worship_services"], key=lambda s: s["starts_at"]))
    places = {}
    for gid, place, person in ((PRODUCTION, "Sound", KENDRA), (WELCOME, "Greeter", JO)):
        r = as_("owner").post("/planning/teams", json={"business_id": BIZ, "group_id": gid, "places": [place]})
        assert r.status_code == 200, r.text
        pid = r.json()["team"]["places"][0]["id"]
        assert as_("owner").put(f"/planning/positions/{pid}/people", json={
            "business_id": BIZ, "people": [{"contact_id": person, "level": "trained"}]}).status_code == 200
        r = as_("owner").post("/planning/ask", json={"business_id": BIZ, "service_id": s2, "position_id": pid,
                                                     "contact_id": person})
        assert r.status_code == 200, r.text
        places[gid] = {"place": pid, "person": person, "asked": r.json()["assignment"]["id"]}
    yield SimpleNamespace(db=db, as_=as_, s1=s1, s2=s2, places=places, standing=standing)


def _owner_of(db, gid):
    return next(t for t in db.t["serve_teams"] if t["group_id"] == gid).get("owner")


# ─── the parts ────────────────────────────────────────────────────────

def test_the_parts_table():
    assert wt.PARTS_FROM_DUTIES == {
        "churchsavvy_team": ("admin",),
        "sunday_plan": ("planner",),
        "production_schedule": ("planner",),
        "serve_schedule": ("scheduler",),
        "stream": ("media", "booth"),
    }
    assert wt.CAN["serve"] == {"admin", "planner", "scheduler"}


def test_a_scheduler_schedules_and_never_plans():
    assert wt.can({"scheduler"}, "serve")
    assert [k for k in wt.CAN if wt.can({"scheduler"}, k)] == ["serve"], "no plan, songs, screens or setup"
    assert wt.PART_OF["serve"] == "planning"
    # A duty's part only: the team never invites someone as a scheduler.
    assert "scheduler" not in wt.ROLES and "scheduler" in wt.PARTS
    with pytest.raises(HTTPException) as no:
        wt._clean_roles(["scheduler"])
    assert no.value.status_code == 400


def test_laquesha_schedules_but_never_changes_the_order_of_service(church):
    user = PEOPLE["laquesha"]
    assert wt.roles_of(BIZ, user, part=None) == {"scheduler"}
    assert wt.require(BIZ, user, "serve") == {"scheduler"}
    for what in ("plan", "songs", "run", "setup"):
        with pytest.raises(HTTPException) as no:
            wt.require(BIZ, user, what)
        assert no.value.status_code == 403 and no.value.detail == wt.REFUSED[what], what
    assert wt.roles_of(BIZ, PEOPLE["shapretta"], part=None) == {"admin", "planner", "media", "booth"}


# ─── each write, by each persona, on each team ───────────────────────

ALLOWED = {
    "owner": {CS, VOL}, "admin": {CS, VOL}, "laquesha": {VOL}, "shapretta": {CS}, "pastor": {CS},
    "tiara": set(), "booth": set(), "viewer": set(),
}


def _writes(c, team, x, s1):
    """Every change to one team, in an order that works for whoever may make them."""
    b = {"business_id": BIZ}
    place, person, asked = x["place"], x["person"], x["asked"]
    out = {}
    out["turns"] = c.patch(f"/planning/teams/{team}", json={**b, "max_month": 3})
    out["add a place"] = r = c.post("/planning/positions", json={**b, "group_id": team, "name": "Extra"})
    extra = r.json()["place"]["id"] if r.status_code == 200 else place
    out["change a place"] = c.patch(f"/planning/positions/{place}", json={**b, "note": "Back row"})
    out["who's trained"] = c.put(f"/planning/positions/{place}/people",
                                 json={**b, "people": [{"contact_id": person, "level": "trained"}]})
    out["ask"] = c.post("/planning/ask", json={**b, "service_id": s1, "position_id": place, "contact_id": person})
    out["offer"] = c.post("/planning/offer", json={**b, "service_id": s1, "position_id": place, "slot": 1})
    out["answer"] = c.post(f"/planning/assignments/{asked}/answer", json={**b, "status": "no"})
    out["take back"] = c.delete(f"/planning/assignments/{asked}?business_id={BIZ}")
    out["fill"] = r = c.post("/planning/fill", json={**b, "weeks": 2, "group_id": team})
    out["retire a place"] = c.delete(f"/planning/positions/{extra}?business_id={BIZ}")
    out["stop the team"] = c.delete(f"/planning/teams/{team}?business_id={BIZ}")
    return out


@pytest.mark.parametrize("who", WHO)
def test_each_write_by_each_persona_on_each_team(church, who):
    for team, owner in ((PRODUCTION, CS), (WELCOME, VOL)):
        before = {k: [dict(r) for r in v] for k, v in church.db.t.items()}
        got = _writes(church.as_(who), team, church.places[team], church.s1)
        if owner in ALLOWED[who]:
            for op, r in got.items():
                # Stopping a team someone was asked for is refused for everyone (the offer stands).
                assert r.status_code == (409 if op == "stop the team" else 200), (who, team, op, r.text)
            assert got["fill"].json()["asked"] == 1
        else:
            want = refused(owner) if SEATS.get(f"u-{who}") == "manager" or who == "pastor" else wt.REFUSED["serve"]
            for op, r in got.items():
                assert (r.status_code, r.json()["detail"]) == (403, want), (who, team, op)
            assert church.db.t == before, f"{who} changed nothing on {team}"


def test_a_manager_with_neither_hears_whose_job_each_team_is(church):
    c = church.as_("tiara")
    r = c.patch(f"/planning/teams/{PRODUCTION}", json={"business_id": BIZ, "max_month": 1})
    assert r.status_code == 403 and r.json()["detail"] == refused(CS)
    r = c.patch(f"/planning/teams/{WELCOME}", json={"business_id": BIZ, "max_month": 1})
    assert r.status_code == 403 and r.json()["detail"] == refused(VOL)
    assert "Logins & areas" in r.json()["detail"]
    for path in ("/planning/fill", "/planning/unfill"):
        r = c.post(path, json={"business_id": BIZ, "weeks": 2, "ids": [church.places[WELCOME]["asked"]]})
        assert r.status_code == 403 and r.json()["detail"] == refused(VOL), path


def test_churchsavvy_team_alone_opens_churchsavvys_teams_and_a_moved_duty_moves_them(church):
    """A login given churchsavvy_team (without production_schedule) changes
    ChurchSavvy's teams, and serve_schedule moved to it Volunteers' too; with
    neither, it's told whose job they are."""
    church.standing["duties"]["u-shapretta"] = {"churchsavvy_team", "serve_schedule", "stream"}
    c = church.as_("shapretta")
    for team in (PRODUCTION, WELCOME):
        assert c.patch(f"/planning/teams/{team}", json={"business_id": BIZ, "max_month": 1}).status_code == 200
    church.standing["duties"]["u-shapretta"] = {"stream"}
    r = c.patch(f"/planning/teams/{PRODUCTION}", json={"business_id": BIZ, "max_month": 2})
    assert r.status_code == 403 and r.json()["detail"] == refused(CS)


# ─── reads stay whole ─────────────────────────────────────────────────

CHANGE = {"owner": [CS, VOL], "admin": [CS, VOL], "laquesha": [VOL], "shapretta": [CS], "pastor": [CS],
          "tiara": [], "booth": [], "viewer": []}


@pytest.mark.parametrize("who", WHO)
def test_everyone_reads_the_whole_sunday(church, who):
    c = church.as_(who)
    j = c.get(f"/planning/teams?business_id={BIZ}").json()
    assert [(t["name"], t["owner"]) for t in j["teams"]] == [("Production", CS), ("Welcome", VOL)]
    assert (j["two_doors"], j["change"]) == (True, CHANGE[who])
    assert j["new_team_owner"] == (CHANGE[who][0] if len(CHANGE[who]) == 1 else None)
    assert j["owner_words"] == list(sp.CHURCHSAVVY_WORDS)
    s = c.get(f"/planning/schedule?business_id={BIZ}").json()
    assert [t["name"] for t in s["teams"]] == ["Production", "Welcome"]
    assert {a["id"] for a in s["assignments"]} == {x["asked"] for x in church.places.values()}
    assert s["change"] == CHANGE[who]
    status = c.get(f"/planning/status?business_id={BIZ}").json()
    assert (status["two_doors"], status["change"]) == (True, CHANGE[who])


def test_one_doors_teams(church):
    c = church.as_("laquesha")
    j = c.get(f"/planning/teams?business_id={BIZ}&owner=volunteers").json()
    assert [t["name"] for t in j["teams"]] == ["Welcome"] and j["owner"] == VOL
    j = c.get(f"/planning/teams?business_id={BIZ}&owner=churchsavvy").json()
    assert [t["name"] for t in j["teams"]] == ["Production"]
    s = c.get(f"/planning/schedule?business_id={BIZ}&owner=volunteers").json()
    assert [t["name"] for t in s["teams"]] == ["Welcome"]
    assert [a["id"] for a in s["assignments"]] == [church.places[WELCOME]["asked"]]
    assert len(s["services"]) == 2 and s["owner"] == VOL
    assert c.get(f"/planning/teams?business_id={BIZ}&owner=production").status_code == 400
    assert c.get(f"/planning/schedule?business_id={BIZ}&owner=band").status_code == 400
    # Who could take a ChurchSavvy place is read as before: the whole Sunday.
    x = church.places[PRODUCTION]
    r = c.get(f"/planning/candidates?business_id={BIZ}&service_id={church.s1}&position_id={x['place']}")
    assert r.status_code == 200 and [p["name"] for p in r.json()["candidates"]] == ["Kendra Lane"]


# ─── a new team's owner ───────────────────────────────────────────────

def _add(c, **team):
    return c.post("/planning/teams", json={"business_id": BIZ, **team})


def test_a_new_team_belongs_to_its_makers_door_else_its_name(church):
    db = church.db
    # Laquesha schedules Volunteers only: her teams are Volunteers', whatever they're called.
    r = _add(church.as_("laquesha"), name="Hospitality")
    assert r.status_code == 200 and r.json()["team"]["owner"] == VOL
    r = _add(church.as_("laquesha"), name="Kids Worship")
    assert r.status_code == 200 and r.json()["team"]["owner"] == VOL
    # Shapretta's are ChurchSavvy's.
    r = _add(church.as_("shapretta"), name="Lights")
    assert r.status_code == 200 and r.json()["team"]["owner"] == CS
    # Neither may make the other's.
    groups = len(db.t["groups"])
    r = _add(church.as_("laquesha"), name="Choir", owner=CS)
    assert r.status_code == 403 and r.json()["detail"] == refused(CS)
    r = _add(church.as_("shapretta"), name="Parking", owner=VOL)
    assert r.status_code == 403 and r.json()["detail"] == refused(VOL)
    assert len(db.t["groups"]) == groups, "a refused team makes no group"
    # The owner chooses, or its name does.
    assert _add(church.as_("owner"), name="Praise Team").json()["team"]["owner"] == CS
    assert _add(church.as_("owner"), name="Parking").json()["team"]["owner"] == VOL
    assert _add(church.as_("owner"), name="Choir", owner=VOL).json()["team"]["owner"] == VOL
    assert _add(church.as_("admin"), name="Coffee", owner=CS).json()["team"]["owner"] == CS
    assert _add(church.as_("owner"), name="Ushers", owner="band").status_code == 400
    # A serving team the church has: by its name too, and the name the list suggests.
    media = {"id": str(uuidlib.uuid4()), "business_id": BIZ, "name": "Media Team", "kind": "team", "active": True}
    db.t["groups"].append(media)
    others = church.as_("owner").get(f"/planning/teams?business_id={BIZ}").json()["other_teams"]
    assert {"group_id": media["id"], "name": "Media Team", "owner": CS} in others
    assert _add(church.as_("owner"), group_id=media["id"]).json()["team"]["owner"] == CS
    assert _owner_of(db, media["id"]) == CS


def test_the_owner_or_an_admin_moves_a_team_to_the_other_door(church):
    r = church.as_("laquesha").patch(f"/planning/teams/{WELCOME}", json={"business_id": BIZ, "owner": CS})
    assert r.status_code == 403 and r.json()["detail"] == refused(CS)
    r = church.as_("shapretta").patch(f"/planning/teams/{PRODUCTION}", json={"business_id": BIZ, "owner": VOL})
    assert r.status_code == 403 and r.json()["detail"] == refused(VOL)
    assert church.as_("owner").patch(f"/planning/teams/{PRODUCTION}", json={"business_id": BIZ, "owner": "x"}).status_code == 400
    r = church.as_("admin").patch(f"/planning/teams/{PRODUCTION}", json={"business_id": BIZ, "owner": VOL})
    assert r.status_code == 200 and r.json()["team"]["owner"] == VOL
    # Now it's Laquesha's.
    assert church.as_("laquesha").patch(f"/planning/teams/{PRODUCTION}",
                                        json={"business_id": BIZ, "max_month": 1}).status_code == 200
    assert church.as_("shapretta").patch(f"/planning/teams/{PRODUCTION}",
                                         json={"business_id": BIZ, "max_month": 2}).status_code == 403


# ─── filling keeps to your own teams ──────────────────────────────────

def test_filling_the_month_fills_only_your_teams_and_still_sees_the_whole_sunday(church):
    db = church.db
    # Lee is on both teams, trained for Sound and for Greeter; the owner asked
    # him for Sound on the first Sunday.
    sound, greeter = church.places[PRODUCTION]["place"], church.places[WELCOME]["place"]
    owner = church.as_("owner")
    for pid, person in ((sound, KENDRA), (greeter, JO)):
        assert owner.put(f"/planning/positions/{pid}/people", json={
            "business_id": BIZ, "people": [{"contact_id": LEE, "level": "trained"},
                                           {"contact_id": person, "level": "trained"}]}).status_code == 200
    assert owner.post("/planning/ask", json={"business_id": BIZ, "service_id": church.s1, "position_id": sound,
                                             "contact_id": LEE}).status_code == 200
    # Jo is away the first Sunday, so only Lee could greet then: he's on Sound that hour.
    db.t["serve_away"].append({"id": str(uuidlib.uuid4()), "business_id": BIZ, "contact_id": JO,
                               "starts_on": "2026-10-25", "ends_on": "2026-10-25", "note": ""})
    before = {r["id"] for r in db.t["serve_assignments"]}
    r = church.as_("laquesha").post("/planning/fill", json={"business_id": BIZ, "weeks": 2})
    assert r.status_code == 200, r.text
    j = r.json()
    new = [x for x in db.t["serve_assignments"] if x["id"] not in before]
    assert j["asked"] == 0 and j["still_open"] == 1 and new == [], "Lee is never asked twice the same hour"
    # Shapretta's fill is Production's alone.
    j = church.as_("shapretta").post("/planning/fill", json={"business_id": BIZ, "weeks": 2}).json()
    assert j["asked"] == 0 and j["still_open"] == 0
    # Taking asks back: only the ones on your own teams.
    ids = [x["asked"] for x in church.places.values()]
    r = church.as_("laquesha").post("/planning/unfill", json={"business_id": BIZ, "ids": ids})
    assert r.status_code == 200 and r.json() == {"taken_back": 1}
    left = {x["id"] for x in db.t["serve_assignments"]}
    assert church.places[PRODUCTION]["asked"] in left and church.places[WELCOME]["asked"] not in left
    # The owner's fill is every team's.
    db.t["serve_away"].clear()
    j = church.as_("owner").post("/planning/fill", json={"business_id": BIZ, "weeks": 2}).json()
    assert j["asked"] == 2


# ─── not a church, ChurchSavvy alone ──────────────────────────────────

@pytest.mark.parametrize("kind", ["not a church", "ChurchSavvy alone"])
def test_outside_a_churchs_office_nothing_changes(church, kind):
    biz = church.db.t["businesses"][0]
    if kind == "not a church":
        biz["type"] = "barber"
    else:
        biz["settings"] = {**biz["settings"], "churchsavvy_only": True}
    church.standing["calls"] = 0
    church.standing["broken"] = True
    # Whoever schedules changes every team; a booth volunteer still reads only.
    for team in (PRODUCTION, WELCOME):
        r = church.as_("pastor").patch(f"/planning/teams/{team}", json={"business_id": BIZ, "max_month": 1})
        assert r.status_code == 200, (kind, team, r.text)
        assert church.as_("booth").patch(f"/planning/teams/{team}", json={"business_id": BIZ,
                                                                          "max_month": 1}).status_code == 403
    j = church.as_("pastor").get(f"/planning/teams?business_id={BIZ}").json()
    assert (j["two_doors"], j["change"], j["new_team_owner"]) == (False, [CS, VOL], None)
    assert [t["owner"] for t in j["teams"]] == [CS, VOL], "teams still say whose they'd be"
    assert church.as_("booth").get(f"/planning/teams?business_id={BIZ}").json()["change"] == []
    r = _add(church.as_("pastor"), name="Ushers")
    assert r.status_code == 200 and r.json()["team"]["owner"] == VOL
    assert church.standing["calls"] == 0, "no duties are read outside a church's office"


# ─── before the migration ─────────────────────────────────────────────

def _before_the_migration(church, monkeypatch, missing=True):
    """serve_teams has no owner column: PostgREST refuses any read naming it."""
    real = church.db.get

    def get(path, **kw):
        if path.lstrip("/").startswith("serve_teams") and "owner" in path:
            return None
        return real(path, **kw)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sp, "_column_missing", lambda: missing)
    for row in church.db.t["serve_teams"]:
        row.pop("owner", None)


def test_before_the_migration_every_team_is_volunteers_and_nothing_breaks(church, monkeypatch):
    _before_the_migration(church, monkeypatch)
    j = church.as_("owner").get(f"/planning/teams?business_id={BIZ}")
    assert j.status_code == 200 and [t["owner"] for t in j.json()["teams"]] == [VOL, VOL]
    assert church.as_("owner").get(f"/planning/schedule?business_id={BIZ}&owner=churchsavvy").json()["teams"] == []
    assert church.as_("laquesha").patch(f"/planning/teams/{PRODUCTION}",
                                        json={"business_id": BIZ, "max_month": 1}).status_code == 200
    assert church.as_("shapretta").patch(f"/planning/teams/{PRODUCTION}",
                                         json={"business_id": BIZ, "max_month": 1}).status_code == 403
    # A new team is saved without the column; moving one waits for it.
    r = _add(church.as_("owner"), name="Worship", owner=CS)
    assert r.status_code == 200, r.text
    made = next(t for t in church.db.t["serve_teams"] if t["group_id"] == r.json()["team"]["group_id"])
    assert "owner" not in made
    r = church.as_("owner").patch(f"/planning/teams/{WELCOME}", json={"business_id": BIZ, "owner": CS})
    assert r.status_code == 409 and "just yet" in r.json()["detail"]
    assert church.as_("owner").get(f"/planning/status?business_id={BIZ}").status_code == 200
    # Within the minute it doesn't ask again; after it, it does.
    calls = []
    monkeypatch.setattr(sp, "_column_missing", lambda: calls.append(1) or True)
    church.as_("owner").get(f"/planning/teams?business_id={BIZ}")
    assert calls == []
    monkeypatch.setitem(sp._no_column, "at", sp._no_column["at"] - sp.NO_COLUMN_SECONDS - 1)
    church.as_("owner").get(f"/planning/teams?business_id={BIZ}")
    assert calls == [1]


def test_a_blip_is_never_read_as_no_column(church, monkeypatch):
    _before_the_migration(church, monkeypatch, missing=None)
    r = church.as_("owner").get(f"/planning/teams?business_id={BIZ}")
    assert r.status_code == 503 and sp._no_column["at"] == 0.0


def test_the_column_probe(monkeypatch):
    import httpx
    monkeypatch.setenv("SUPABASE_URL", "https://db.example")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    seen = []
    answers = iter([SimpleNamespace(status_code=200, text="[]"),
                    SimpleNamespace(status_code=400, text='{"code":"42703","message":"column serve_teams.owner does not exist"}'),
                    SimpleNamespace(status_code=400, text='{"code":"PGRST100"}'),
                    SimpleNamespace(status_code=503, text="")])
    monkeypatch.setattr(httpx, "get", lambda url, **kw: seen.append(url) or next(answers))
    assert [sp._column_missing() for _ in range(4)] == [False, True, None, None]
    assert seen[0] == "https://db.example/rest/v1/serve_teams?select=owner&limit=1"

    def down(*a, **kw):
        raise httpx.ConnectError("no route")
    monkeypatch.setattr(httpx, "get", down)
    assert sp._column_missing() is None


# ─── a failed read ────────────────────────────────────────────────────

def test_a_failed_duties_read_is_a_503_never_a_yes(church):
    church.standing["broken"] = True
    before = {k: [dict(r) for r in v] for k, v in church.db.t.items()}
    for who in ("laquesha", "shapretta", "pastor"):
        c = church.as_(who)
        for team in (PRODUCTION, WELCOME):
            r = c.patch(f"/planning/teams/{team}", json={"business_id": BIZ, "max_month": 1})
            assert r.status_code == 503, (who, team, r.text)
        assert _add(c, name="Ushers").status_code == 503
        assert c.post("/planning/fill", json={"business_id": BIZ, "weeks": 2}).status_code == 503
    assert church.db.t == before
    # A page that reads it shows nothing as theirs to change; the write asks again.
    j = church.as_("pastor").get(f"/planning/teams?business_id={BIZ}").json()
    assert j["change"] == [] and j["two_doors"] is True


# ─── order-of-service notes follow their team ─────────────────────────

def test_an_order_note_follows_its_team_and_every_teams_note_is_churchsavvys(church):
    """The order of service is ChurchSavvy's (Kevin, 2026-11-02): a note for
    a Volunteers team is whoever schedules the volunteers'; a ChurchSavvy
    team's, and a note for every team, is ChurchSavvy's."""
    import sunday_order as so
    svc = next(s for s in church.db.t["worship_services"] if s["id"] == church.s1)
    svc["items"] = [{"id": "ff", "kind": "song", "title": "Firm Foundation", "minutes": 4}]
    church.db.KEYS = {**church.db.KEYS, "serve_notes": ("service_id", "item_id", "team")}
    church.db.t["serve_notes"] = []
    app = FastAPI()
    app.include_router(so.router)
    who = {"user": PEOPLE["owner"]}
    app.dependency_overrides[require_user] = lambda: who["user"]
    c = TestClient(app)

    def note(name, team):
        who["user"] = PEOPLE[name]
        return c.put("/planning/order/notes", json={"business_id": BIZ, "service_id": church.s1, "item_id": "ff",
                                                    "team": team, "note": "Doors open at 9:40"})
    assert note("laquesha", WELCOME).status_code == 200
    assert note("laquesha", PRODUCTION).status_code == 403
    assert note("laquesha", "all").status_code == 403
    assert note("shapretta", PRODUCTION).status_code == 200
    assert note("shapretta", "all").status_code == 200
    assert note("shapretta", WELCOME).status_code == 403
    assert note("owner", WELCOME).status_code == 200 and note("admin", "all").status_code == 200
