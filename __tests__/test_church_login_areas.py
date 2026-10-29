"""Who sees what (church_areas.py, Kevin 2026-10-26): a church's office login
sees the areas it works in, not the whole church.

Pins:
  * the owner and admins see the whole church, whatever a pick says
  * the church's own pick wins, in the areas' order
  * else Chief's guess from what the login's person already holds, matched
    by email: a Lead tab role (a team leader goes where the team goes),
    ChurchSavvy's team, kids check-in, leading a group, safety officer;
    only roles they've said yes to
  * nothing places them: the whole church, as before, and the map says so
  * /team/my-role carries it only for a church with the switch on, and a
    failed read shows what was shown before
  * an admin picks a login's areas; never an admin's, never Giving, never
    none; null goes back to the guess
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import sb_clients  # noqa: E402
from test_church_follow_up import BIZ  # noqa: E402
from test_church_areas import db, office  # noqa: E402,F401

MARCUS_SEAT = "11111111-1111-1111-1111-111111111111"
SAM_SEAT = "22222222-2222-2222-2222-222222222222"
ANDRE_SEAT = "33333333-3333-3333-3333-333333333333"
NEW_SEAT = "44444444-4444-4444-4444-444444444444"
KEISHA_SEAT = "55555555-5555-5555-5555-555555555555"


@pytest.fixture(autouse=True)
def _fresh_cache():
    ca._MY_CACHE.clear()
    yield
    ca._MY_CACHE.clear()


def _seat(uid, email, role="manager", areas=None):
    return {"business_id": BIZ, "user_id": uid, "invited_email": email, "role": role, "status": "active",
            "areas": areas}


@pytest.fixture
def seats(db):
    db.t["business_users"] += [
        _seat(MARCUS_SEAT, "Marcus@Example.com"),           # leads the Youth Ministry (YWD) team
        _seat(SAM_SEAT, "sam@example.com", "member"),       # on ChurchSavvy's team
        _seat(ANDRE_SEAT, "andre@example.com", "viewer"),   # a kids worker
        _seat(NEW_SEAT, "new@lovecity.org", "member", ["office", "people_care"]),
        _seat(KEISHA_SEAT, "keisha@example.com"),           # the treasurer
    ]
    return db


def _login(m, uid):
    return next(x for x in m["logins"] if x["user_id"] == uid)


# ─── What a login is shown ────────────────────────────────────────────

def test_the_owner_and_admins_see_the_whole_church_whatever_a_pick_says():
    for role in ("owner", "admin"):
        assert ca.login_view(role, ["office"], {"kids_youth": "Kids check-in"}) == {
            "areas": None, "by": "all", "why": "Sees the whole church"}


def test_the_churchs_pick_wins_in_the_areas_order():
    v = ca.login_view("member", ["office", "people_care", "the_moon"], {"kids_youth": "Kids check-in"})
    assert v == {"areas": ["people_care", "office"], "by": "picked", "why": "Picked by your church"}


def test_chiefs_guess_says_what_placed_it_and_nothing_placed_is_the_whole_church():
    v = ca.login_view("viewer", None, {"kids_youth": "Kids check-in", "worship_media": "ChurchSavvy's team"})
    assert v["areas"] == ["worship_media", "kids_youth"] and v["by"] == "guess"
    assert v["why"] == "Chief's guess, from ChurchSavvy's team, Kids check-in"
    assert ca.login_view("member", [], {}) == {"areas": None, "by": "none", "why": "No role or team places them yet"}


def test_the_map_lists_each_office_login_with_what_it_is_shown(seats):
    m = ca.build(seats.t["businesses"][0])
    admin = next(x for x in m["logins"] if x["email"] == "office@lovecity.org")
    assert admin["by"] == "all" and admin["areas"] is None and m["logins"][0] is admin, "admins first"
    marcus = _login(m, MARCUS_SEAT)
    assert marcus["areas"] == ["kids_youth"] and marcus["by"] == "guess", "a team leader goes where the team goes"
    assert "Youth Ministry (YWD)" in marcus["why"] and marcus["name"] == "Marcus Taylor"
    assert _login(m, SAM_SEAT)["areas"] == ["worship_media"]
    assert _login(m, SAM_SEAT)["why"] == "Chief's guess, from ChurchSavvy's team"
    assert _login(m, ANDRE_SEAT)["areas"] == ["kids_youth"]
    picked = _login(m, NEW_SEAT)
    assert picked["areas"] == ["people_care", "office"] and picked["by"] == "picked" and picked["guess"] == []
    intern = next(x for x in m["logins"] if x["email"] == "intern@lovecity.org")
    assert intern["areas"] is None and intern["by"] == "none"
    keisha = _login(m, KEISHA_SEAT)
    assert keisha["areas"] == ["giving_money"], "her area, though Giving opens only with an admin login"


def test_a_role_only_asked_and_not_yet_answered_places_nothing(seats):
    robert = _seat("66666666-6666-6666-6666-666666666666", "robert@example.com")
    seats.t["business_users"].append(robert)
    seats.t["group_members"] = []
    assert _login(ca.build(seats.t["businesses"][0]), robert["user_id"])["by"] == "none"


# ─── /team/my-role ────────────────────────────────────────────────────

def test_my_areas_is_for_a_church_with_the_switch_on(seats, monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "owner")
    assert ca.my_areas(BIZ, MARCUS_SEAT, "manager") is None
    monkeypatch.setenv("CHURCH_AREAS", "on")
    assert ca.my_areas(BIZ, MARCUS_SEAT, "manager")["areas"] == ["kids_youth"]
    assert ca.my_areas(BIZ, "u-admin", "admin") == {"areas": None, "by": "all", "why": "Sees the whole church"}
    assert ca.my_areas(BIZ, NEW_SEAT, "member")["areas"] == ["people_care", "office"]
    assert ca.my_areas(BIZ, MARCUS_SEAT, None) is None
    seats.t["businesses"][0]["type"] = "salon"
    assert ca.my_areas(BIZ, MARCUS_SEAT, "manager") is None


def test_my_areas_matches_the_guess_on_the_map(seats, monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "on")
    m = ca.build(seats.t["businesses"][0])
    for uid, role in ((MARCUS_SEAT, "manager"), (SAM_SEAT, "member"), (ANDRE_SEAT, "viewer"), (KEISHA_SEAT, "manager")):
        mine = ca.my_areas(BIZ, uid, role)
        assert (mine["areas"], mine["by"], mine["why"]) == (
            _login(m, uid)["areas"], _login(m, uid)["by"], _login(m, uid)["why"]), uid


def test_a_failed_read_shows_what_was_shown_before(seats, monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "on")
    real = seats.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("church_leader_roles") else real(path, **kw))
    assert ca.my_areas(BIZ, MARCUS_SEAT, "manager") is None


def test_my_role_carries_the_areas_only_when_they_apply(seats, monkeypatch):
    import business_users_router as bur
    from types import SimpleNamespace
    monkeypatch.setattr(bur, "role_of", lambda b, u: "manager")
    user = SimpleNamespace(id=MARCUS_SEAT, email="marcus@example.com")
    monkeypatch.setenv("CHURCH_AREAS", "on")
    out = bur.my_role(BIZ, user)
    assert out["areas"] == ["kids_youth"] and out["areas_by"] == "guess" and out["role"] == "manager"
    monkeypatch.setenv("CHURCH_AREAS", "owner")
    assert "areas" not in bur.my_role(BIZ, user)


# ─── Picking a login's areas ──────────────────────────────────────────

def test_an_admin_picks_a_logins_areas_and_puts_them_back(office, seats):
    r = office.put("/church/areas/login", json={"business_id": BIZ, "user_id": MARCUS_SEAT,
                                                "areas": ["office", "kids_youth"]})
    assert r.status_code == 200 and r.json()["areas"] == ["kids_youth", "office"]
    row = next(s for s in seats.t["business_users"] if s["user_id"] == MARCUS_SEAT)
    assert row["areas"] == ["kids_youth", "office"]
    assert _login(office.get(f"/church/areas?business_id={BIZ}").json(), MARCUS_SEAT)["by"] == "picked"
    r = office.put("/church/areas/login", json={"business_id": BIZ, "user_id": MARCUS_SEAT, "areas": None})
    assert r.status_code == 200 and row["areas"] is None
    assert _login(office.get(f"/church/areas?business_id={BIZ}").json(), MARCUS_SEAT)["by"] == "guess"


def test_picking_never_places_an_admin_never_offers_giving_and_never_none(office, seats):
    admin = "77777777-7777-7777-7777-777777777777"
    seats.t["business_users"].append(_seat(admin, "boss@lovecity.org", "admin"))
    body = {"business_id": BIZ, "user_id": MARCUS_SEAT, "areas": ["office"]}
    assert office.put("/church/areas/login", json={**body, "user_id": admin}).status_code == 400
    assert office.put("/church/areas/login", json={**body, "areas": ["giving_money"]}).status_code == 400
    assert office.put("/church/areas/login", json={**body, "areas": []}).status_code == 400
    assert office.put("/church/areas/login", json={**body, "areas": ["the_moon"]}).status_code == 400
    assert office.put("/church/areas/login", json={**body, "areas": "office"}).status_code == 400
    assert office.put("/church/areas/login", json={**body, "user_id": "nope"}).status_code == 400
    assert office.put("/church/areas/login", json={**body, "user_id": NEW_SEAT.replace("4", "9")}).status_code == 404
    office.who["role"] = "manager"
    assert office.put("/church/areas/login", json=body).status_code == 404
    assert next(s for s in seats.t["business_users"] if s["user_id"] == MARCUS_SEAT)["areas"] is None


def test_before_the_column_exists_the_map_and_my_areas_still_answer(seats, monkeypatch):
    """The picks are read on their own: before the migration (or on a blip)
    a login shows Chief's guess, never a broken map."""
    monkeypatch.setenv("CHURCH_AREAS", "on")
    real = seats.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if "select=user_id,areas" in path else real(path, **kw))
    m = ca.build(seats.t["businesses"][0])
    assert _login(m, NEW_SEAT)["by"] == "none", "its pick can't be read, and nothing else places it"
    assert _login(m, MARCUS_SEAT)["by"] == "guess"
    assert ca.my_areas(BIZ, MARCUS_SEAT, "manager")["areas"] == ["kids_youth"]


def test_a_logins_view_is_kept_a_minute_and_a_saved_pick_clears_it(office, seats, monkeypatch):
    monkeypatch.setenv("CHURCH_AREAS", "on")
    assert ca.my_areas(BIZ, MARCUS_SEAT, "manager")["areas"] == ["kids_youth"]
    reads = []
    real = seats.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (reads.append(path), real(path, **kw))[1])
    assert ca.my_areas(BIZ, MARCUS_SEAT, "manager")["areas"] == ["kids_youth"]
    assert [p for p in reads if not p.startswith("/businesses")] == [], "the second ask reads only the church"
    r = office.put("/church/areas/login", json={"business_id": BIZ, "user_id": MARCUS_SEAT, "areas": ["office"]})
    assert r.status_code == 200
    assert ca.my_areas(BIZ, MARCUS_SEAT, "manager")["areas"] == ["office"]


# ─── The office's lanes (Kevin 2026-10-28) ────────────────────────────

def test_the_offices_lanes_are_each_a_login_and_its_areas():
    assert [x["key"] for x in ca.lanes_view()] == [
        "office_leadership", "people_care", "sunday_serving", "media_comms", "treasurer"]
    for x in ca.lanes_view():
        if x["role"] == "manager":
            assert x["areas"] and ca.FINANCE_ONLY not in x["areas"], x["key"]
            assert x["areas"] == [a for a in ca.AREA_ORDER if a in x["areas"]], "in the areas' order"
    assert ca.LANES["treasurer"]["role"] == "admin" and ca.LANES["treasurer"]["areas"] is None
    assert ca.lane_of("manager", ["office", "messages_safety"]) == "office_leadership"
    assert ca.lane_of("member", ["worship_media"]) == "sunday_serving"
    assert ca.lane_of("manager", ["worship_media", "office"]) is None, "a pick that's no lane"
    assert ca.lane_of("admin", ["office", "messages_safety"]) is None, "an admin keeps everything"


def test_an_admin_gives_a_login_its_lane(office, seats):
    body = {"business_id": BIZ, "user_id": MARCUS_SEAT}
    r = office.put("/church/areas/login", json={**body, "lane": "media_comms"})
    assert r.status_code == 200 and r.json()["areas"] == ["worship_media", "website_outreach"]
    assert r.json()["lane"] == "media_comms"
    m = office.get(f"/church/areas?business_id={BIZ}").json()
    assert _login(m, MARCUS_SEAT)["lane"] == "media_comms" and _login(m, MARCUS_SEAT)["by"] == "picked"
    assert _login(m, SAM_SEAT)["lane"] is None, "a guess is no lane"
    assert _login(m, NEW_SEAT)["lane"] is None, "a pick that's no lane"
    assert [x["key"] for x in m["lanes"]][0] == "office_leadership"
    assert office.put("/church/areas/login", json={**body, "lane": "treasurer"}).status_code == 400, "an admin login"
    assert office.put("/church/areas/login", json={**body, "lane": "the_moon"}).status_code == 400
    assert office.get(f"/church/lanes?business_id={BIZ}").json()["lanes"][-1]["role"] == "admin"
    assert next(s for s in seats.t["business_users"] if s["user_id"] == MARCUS_SEAT)["areas"] == [
        "worship_media", "website_outreach"]
