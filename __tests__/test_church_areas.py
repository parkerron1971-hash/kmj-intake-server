"""The map (church_areas.py): every part of a church's system in one area,
and who reaches each one today. Kevin, 2026-10-23: a Media team gets the
media part already set up for it; a treasurer oversees a section; the
artifact "Church Areas and Keys", step 1.

Pins:
  * words place a role or a Serve team ("Social media" is outreach, "Worship
    Pastor" is media, "Youth Ministry (YWD)" is kids); a job that works in
    one place stays there; the church's own pick beats the guess; nothing
    placed says so
  * each area lists the people who work it, from where they already live
    (ChurchSavvy's team, Lead tab roles, kids workers, group leaders, safety
    officers), and who reaches it through an office login
  * a media role whose holder isn't on ChurchSavvy's team is offered with
    parts filled in; one already on it isn't
  * giving says a named treasurer has no way in but an admin login, and
    only the owner, admins and the accountant reach it; member records
    reach every office login, and the map says so
  * a failed read is a 503, never an empty area
  * the switch, a manager to read, an admin to place

The tables are the role tests' in-memory PostgREST."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import sb_clients  # noqa: E402
from test_church_follow_up import (BIZ, OWNER, NAMES, PASTOR, TASHA, ROBERT, DANA, MARCUS, KEISHA,  # noqa: E402
                                   ANDRE, SERVE, _role)
from test_church_roles import FakeDB  # noqa: E402

GROUP_A = "a0000000-0000-0000-0000-00000000000a"
GROUP_B = "b0000000-0000-0000-0000-00000000000b"


def _def(key, title, job, teams=()):
    return {"id": f"def-{key}", "business_id": BIZ, "key": key, "title": title, "job": job, "status": "active",
            "oversees_teams": list(teams), "reports_to": None, "sort": 50, "source": "custom"}


@pytest.fixture
def db(monkeypatch):
    import church_roles as cr
    fake = FakeDB(
        contacts=[{"id": k, "business_id": BIZ, "name": v, "email": f"{v.split()[0].lower()}@example.com"}
                  for k, v in NAMES.items()],
        church_leader_roles=[_role(PASTOR, "pastor"), _role(TASHA, "team_leader", "Hospitality Team"),
                             _role(MARCUS, "team_leader", "Youth Ministry (YWD)"), _role(DANA, "media_director"),
                             _role(KEISHA, "treasurer"), _role(ROBERT, "welcome_lead", status="invited")],
        church_role_defs=[], church_role_settings=[], church_area_places=[],
        intake_forms=[dict(SERVE, business_id=BIZ)],
        businesses=[{"id": BIZ, "name": "Love City Church", "type": "ministry", "owner_id": OWNER,
                     "settings": {"practitioner_name": "Pastor Kevin"}}],
        business_sites=[{"business_id": BIZ, "slug": "love-city-church", "html_content": "<h1>Love City Church</h1>",
                         "site_config": {}}],
        worship_team=[{"business_id": BIZ, "name": "Sam Booth", "email": "sam@example.com", "roles": ["booth"],
                       "status": "active", "invited_at": "2026-10-20T00:00:00+00:00"},
                      {"business_id": BIZ, "name": "Jo Keys", "email": "jo@example.com", "roles": ["worship", "planner"],
                       "status": "invited", "invited_at": "2026-10-21T00:00:00+00:00"}],
        business_users=[{"business_id": BIZ, "user_id": "u-admin", "invited_email": "office@lovecity.org", "role": "admin", "status": "active"},
                        {"business_id": BIZ, "user_id": "u-view", "invited_email": "intern@lovecity.org", "role": "viewer", "status": "active"},
                        {"business_id": BIZ, "user_id": "u-mem", "invited_email": "web@lovecity.org", "role": "member", "status": "active"}],
        business_collaborators=[{"business_id": BIZ, "invited_email": "cpa@books.com", "role": "accountant", "status": "active"}],
        space_leaders=[{"business_id": BIZ, "contact_id": ANDRE, "space": "kids", "background_check_on": None}],
        groups=[{"id": GROUP_A, "business_id": BIZ, "name": "Sisters in the City", "active": True},
                {"id": GROUP_B, "business_id": BIZ, "name": "Men of Valor", "active": True}],
        group_members=[{"business_id": BIZ, "group_id": GROUP_A, "contact_id": ROBERT, "role": "leader"}],
        msg_safety_officers=[], msg_member_officers=[{"business_id": BIZ, "contact_id": PASTOR}],
    )
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fake.delete)
    cr.ensure_library(fake.t["businesses"][0])
    fake.t["church_role_defs"] += [_def("media_director", "Media Director", "ministry"),
                                   _def("treasurer", "Treasurer", "office"),
                                   _def("armor_bearer", "Armor Bearer", "team")]
    return fake


def _area(m, key):
    return next(a for a in m["areas"] if a["key"] == key)


def _names(a):
    return [p["name"] for p in a["people"]]


# ─── Places ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,area", [
    ("Media team", "worship_media"), ("Worship Pastor", "worship_media"), ("Minister of Music", "worship_media"),
    ("Sound and lights", "worship_media"), ("Social media", "website_outreach"),
    ("Graphic and web design", "website_outreach"), ("Events team", "website_outreach"),
    ("Youth Ministry (YWD)", "kids_youth"), ("Children's Church", "kids_youth"),
    ("Treasurer", "giving_money"), ("Trustee Board", "giving_money"), ("Counting team", "giving_money"),
    ("Sunday School", "groups_classes"), ("Small groups", "groups_classes"),
    ("Church Clerk", "office"), ("Hospitality Team", "people_care"), ("Usher Board", "people_care"),
    ("Deacons", "people_care"), ("Intercessors", "people_care"),
])
def test_words_place_a_title_or_a_team(text, area):
    assert ca.guess_area(text)[0] == area


@pytest.mark.parametrize("text", ["Armor Bearers", "Discount table", "Heart of the house", "Dance ministry"])
def test_words_that_say_nothing_place_nothing(text):
    assert ca.guess_area(text) is None


def test_a_job_that_works_in_one_place_stays_there_and_the_churchs_pick_wins():
    kids = {"key": "kids_worship", "title": "Kids Worship Leader", "job": "kids"}
    assert ca.place_role(kids, {})["area"] == "kids_youth"
    teach = {"key": "media_class", "title": "Media class teacher", "job": "teach"}
    assert ca.place_role(teach, {})["area"] == "groups_classes"
    office = {"key": "administrator", "title": "Church Administrator", "job": "office"}
    assert ca.place_role(office, {})["area"] == "office"
    treasurer = {"key": "treasurer", "title": "Treasurer", "job": "office"}
    assert ca.place_role(treasurer, {})["area"] == "giving_money", "the words beat the office job"
    armor = {"key": "armor_bearer", "title": "Armor Bearer", "job": "team"}
    assert ca.place_role(armor, {}) == {"area": None, "by": "", "why": "Nothing says where it belongs yet"}
    picked = ca.place_role(armor, {("role", "armor_bearer"): "people_care"})
    assert picked["area"] == "people_care" and picked["by"] == "church"
    assert ca.place_role(kids, {("role", "kids_worship"): "worship_media"})["area"] == "worship_media"


def test_a_media_role_starts_with_the_parts_its_title_names():
    assert ca.suggested_parts("Media Director") == ["admin"]
    assert ca.suggested_parts("Worship leader") == ["worship"]
    assert ca.suggested_parts("Sound tech") == ["booth"]
    assert ca.suggested_parts("Livestream team") == ["planner"]


# ─── The map ──────────────────────────────────────────────────────────

def test_every_area_is_there_in_order_with_what_it_holds(db):
    m = ca.build(db.t["businesses"][0])
    assert [a["key"] for a in m["areas"]] == list(ca.AREA_ORDER)
    media = _area(m, "worship_media")
    assert media["label"] == "Worship & media" and "Sermons" in media["holds"] and media["guarded"] == []
    assert _area(m, "giving_money")["guarded"] == ["Who gave what", "The bank", "Payouts"]


def test_each_area_lists_its_people_from_where_they_already_live(db):
    m = ca.build(db.t["businesses"][0])
    media = _area(m, "worship_media")
    hows = {p["name"]: p["how"] for p in media["people"]}
    assert hows["Sam Booth"] == "ChurchSavvy: Booth"
    assert hows["Jo Keys"] == "ChurchSavvy: Planner, Worship leader (invited)"
    assert hows["Dana Rivers"] == "Media Director"
    assert "Marcus Taylor" in _names(_area(m, "kids_youth")), "a team leader goes where their team goes"
    assert "Marcus Taylor" not in _names(media)
    care = _area(m, "people_care")
    assert {"Kevin McCloud", "Tasha Williams", "Robert Hayes"} <= set(_names(care))
    assert next(p for p in care["people"] if p["name"] == "Robert Hayes")["how"].endswith("(asked, not yet answered)")
    assert _names(_area(m, "kids_youth")).count("Andre Wallace") == 1
    assert [p["how"] for p in _area(m, "groups_classes")["people"]] == ["Leads Sisters in the City"]
    assert _names(_area(m, "messages_safety")) == ["Kevin McCloud"]


def test_a_media_role_not_on_the_team_is_offered_and_one_on_it_is_not(db):
    m = ca.build(db.t["businesses"][0])
    assert _area(m, "worship_media")["suggest"] == [{
        "contact_id": DANA, "name": "Dana Rivers", "email": "dana@example.com", "role": "Media Director", "parts": ["admin"]}]
    assert "suggest" not in _area(m, "people_care")
    db.t["worship_team"].append({"business_id": BIZ, "name": "Dana Rivers", "email": "dana@example.com",
                                 "roles": ["admin"], "status": "active", "invited_at": "2026-10-22T00:00:00+00:00"})
    assert _area(ca.build(db.t["businesses"][0]), "worship_media")["suggest"] == []


def test_giving_reaches_only_the_owner_admins_and_the_accountant_and_says_the_treasurer_cant_get_in(db):
    m = ca.build(db.t["businesses"][0])
    money = _area(m, "giving_money")
    assert [(p["name"], p["kind"]) for p in money["reach"]] == [
        ("Pastor Kevin", "owner"), ("office@lovecity.org", "seat"), ("cpa@books.com", "accountant")]
    assert "Keisha Morgan is the Treasurer, but the only way into Giving today is an admin login." in money["gaps"]
    assert "Keisha Morgan" not in [p["name"] for p in money["reach"]]


def test_member_records_reach_every_office_login_and_the_map_says_so(db):
    care = _area(ca.build(db.t["businesses"][0]), "people_care")
    assert {p["name"] for p in care["reach"]} == {"Pastor Kevin", "office@lovecity.org", "intern@lovecity.org",
                                                  "web@lovecity.org"}
    assert "Every office login (3) can read member records today." in care["gaps"]


def test_the_website_reaches_the_logins_that_write_and_the_office_only_admins(db):
    m = ca.build(db.t["businesses"][0])
    assert "intern@lovecity.org" not in {p["name"] for p in _area(m, "website_outreach")["reach"]}
    assert "web@lovecity.org" in {p["name"] for p in _area(m, "website_outreach")["reach"]}
    assert {p["name"] for p in _area(m, "office")["reach"]} == {"Pastor Kevin", "office@lovecity.org"}


def test_whats_missing_is_said_plainly(db):
    m = ca.build(db.t["businesses"][0])
    assert _area(m, "kids_youth")["gaps"] == ["1 kids worker has no background check date."]
    assert _area(m, "groups_classes")["gaps"] == ["1 group has no leader."]
    assert _area(m, "messages_safety")["gaps"] == ["Messaging needs two safety officers. It has 1."]
    assert _area(m, "worship_media")["gaps"] == []
    db.t["worship_team"] = [dict(r, status="invited") for r in db.t["worship_team"]]
    assert _area(ca.build(db.t["businesses"][0]), "worship_media")["gaps"] == ["No one has joined the ChurchSavvy team yet."]


def test_roles_and_teams_say_where_they_are_and_what_has_no_place(db):
    m = ca.build(db.t["businesses"][0])
    roles = {r["key"]: r for r in m["roles"]}
    assert roles["media_director"]["area"] == "worship_media" and roles["media_director"]["by"] == "words"
    assert roles["pastor"]["area"] == "people_care"
    teams = {t["name"]: t["area"] for t in m["teams"]}
    assert teams == {"Youth Ministry (YWD)": "kids_youth", "Hospitality Team": "people_care",
                     "Graphic and web design": "website_outreach"}
    assert {"kind": "role", "key": "armor_bearer", "name": "Armor Bearer"} in m["unplaced"]


def test_the_churchs_pick_moves_a_team_and_its_leader(db):
    db.t["church_area_places"].append({"business_id": BIZ, "kind": "team", "key": "youth ministry (ywd)",
                                       "area": "worship_media"})
    m = ca.build(db.t["businesses"][0])
    assert "Marcus Taylor" in _names(_area(m, "worship_media"))
    assert next(t for t in m["teams"] if t["name"] == "Youth Ministry (YWD)")["by"] == "church"


@pytest.mark.parametrize("table", ["worship_team", "space_leaders", "business_users", "church_area_places",
                                   "msg_member_officers", "group_members"])
def test_a_failed_read_is_a_503_never_an_empty_area(db, monkeypatch, table):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith(table + "?") else real(path, **kw))
    with pytest.raises(ca.HTTPException) as e:
        ca.build(db.t["businesses"][0])
    assert e.value.status_code == 503


# ─── The routes ───────────────────────────────────────────────────────

@pytest.fixture
def office(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import business_access
    who = {"role": "owner", "email": "kmjcreativesolution@gmail.com"}
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: who["role"])
    monkeypatch.setenv("CHURCH_AREAS", "owner")
    app = FastAPI()
    app.include_router(ca.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=OWNER, email=who["email"], user_metadata={})))
    client = TestClient(app)
    client.who = who
    return client


def test_the_map_is_for_a_manager_and_up(office):
    assert office.get(f"/church/areas?business_id={BIZ}").status_code == 200
    office.who["role"] = "manager"
    assert office.get(f"/church/areas?business_id={BIZ}").status_code == 200
    office.who["role"] = "member"
    assert office.get(f"/church/areas?business_id={BIZ}").status_code == 404
    office.who["role"] = None
    assert office.get(f"/church/areas?business_id={BIZ}").status_code == 404


def test_a_business_that_isnt_a_church_gets_no_map_and_no_church_roles(office, db):
    db.t["businesses"][0]["type"] = "salon"
    before = len(db.t["church_role_defs"])
    assert office.get(f"/church/areas?business_id={BIZ}").status_code == 404
    assert len(db.t["church_role_defs"]) == before


def test_the_status_says_where_the_map_opens_and_reads_nothing_else(office, db, monkeypatch):
    assert office.get(f"/church/areas/status?business_id={BIZ}").json() == {"enabled": True}
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: real(path, **kw) if path.lstrip("/").startswith("businesses?")
                        else pytest.fail(f"the status read {path}"))
    assert office.get(f"/church/areas/status?business_id={BIZ}").json() == {"enabled": True}
    db.t["businesses"][0]["type"] = "salon"
    assert office.get(f"/church/areas/status?business_id={BIZ}").json() == {"enabled": False}
    office.who["role"] = "member"
    assert office.get(f"/church/areas/status?business_id={BIZ}").status_code == 404
    office.who["role"] = "owner"
    monkeypatch.setenv("CHURCH_AREAS", "off")
    assert office.get(f"/church/areas/status?business_id={BIZ}").status_code == 404


def test_the_switch_keeps_it_to_the_platform_owner_then_everyone_or_no_one(office, monkeypatch):
    office.who["email"] = "pastor@lovecity.org"
    assert office.get(f"/church/areas?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_AREAS", "on")
    assert office.get(f"/church/areas?business_id={BIZ}").status_code == 200
    monkeypatch.setenv("CHURCH_AREAS", "off")
    assert office.get(f"/church/areas?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("CHURCH_AREAS", "sometimes")
    assert office.get(f"/church/areas?business_id={BIZ}").status_code == 404


def test_an_admin_places_a_role_and_puts_it_back(office, db):
    r = office.put("/church/areas/place", json={"business_id": BIZ, "kind": "role", "key": "armor_bearer",
                                                "area": "people_care"})
    assert r.status_code == 200 and r.json()["area"] == "people_care"
    m = office.get(f"/church/areas?business_id={BIZ}").json()
    assert next(x for x in m["roles"] if x["key"] == "armor_bearer")["why"] == "Your church placed it here"
    r = office.put("/church/areas/place", json={"business_id": BIZ, "kind": "role", "key": "armor_bearer", "area": None})
    assert r.status_code == 200 and db.t["church_area_places"] == []


def test_a_team_is_placed_by_its_name_however_it_is_spaced(office, db):
    r = office.put("/church/areas/place", json={"business_id": BIZ, "kind": "team", "key": "  Youth   Ministry (YWD) ",
                                                "area": "worship_media"})
    assert r.status_code == 200 and r.json()["key"] == "youth ministry (ywd)"
    assert db.t["church_area_places"][0]["key"] == "youth ministry (ywd)"


def test_placing_is_an_admins_and_takes_only_a_real_area_and_name(office, db):
    body = {"business_id": BIZ, "kind": "role", "key": "armor_bearer", "area": "people_care"}
    assert office.put("/church/areas/place", json={**body, "area": "the_moon"}).status_code == 400
    assert office.put("/church/areas/place", json={**body, "kind": "person"}).status_code == 400
    assert office.put("/church/areas/place", json={**body, "key": "Not A Key!"}).status_code == 400
    assert office.put("/church/areas/place", json={**body, "business_id": "nope"}).status_code == 400
    office.who["role"] = "manager"
    assert office.put("/church/areas/place", json=body).status_code == 404
    assert db.t["church_area_places"] == []
