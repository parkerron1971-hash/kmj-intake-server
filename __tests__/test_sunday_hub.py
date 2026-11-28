"""The one Sunday hub's switch and roles (sunday_hub.py, mission M-7; Kevin's
decisions church-office-1, 2026-11-27).

Pins:
  * SUNDAY_HUB: off by default, owner only for the platform owner, on for
    every church; a typo reads as off; off adds nothing to /worship/status
  * the day-one roles, from what a church already gave each login, so
    nobody loses access: owner and Admin -> every role; Planner part or
    sunday_plan / production_schedule / churchsavvy_team -> planner; the
    Worship part -> leader of the church's worship team (planner where it has
    none); a person leading a Sunday team -> its team leader (their seat's
    person, or the one person with the login's email); Booth / Media part or
    the stream duty -> media & tech; ministry_ops -> ministry operations
  * a reader is anyone with a role, a Sunday duty or a team part; a care-only
    Manager and a viewer seat read no Sunday plan
  * /worship/status carries the roles, leads, approve, giving and the word
  * "This Sunday" or "Next service": worked out from when the plans fall, or
    the church's own choice (the setup part; null works it out again)
  * the new duty sits in the Sunday & Serving lane, so the lane's logins
    hold it from the first day
  * POST /planning/sundays keeps its rule: blank Sundays for whoever
    schedules either door (the Volunteers board's button), never a booth
    volunteer or a viewer"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import church_duties as cd
import sunday_hub as hub
from sunday_hub_fixture import BIZ, LEE, PEOPLE, PRODUCTION, WELCOME, WORSHIP, church  # noqa: F401


# ─── the switch ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value,owner,other", [
    (None, False, False), ("off", False, False), ("owner", True, False), ("on", True, True),
    ("ON ", True, True), ("onn", False, False)])
def test_the_switch(monkeypatch, value, owner, other):
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", PEOPLE["owner"].email)
    if value is None:
        monkeypatch.delenv("SUNDAY_HUB", raising=False)
    else:
        monkeypatch.setenv("SUNDAY_HUB", value)
    assert hub.open_to(PEOPLE["owner"]) is owner
    assert hub.open_to(PEOPLE["planner"]) is other


def test_off_adds_nothing_to_status(church, monkeypatch):
    monkeypatch.setenv("SUNDAY_HUB", "off")
    r = church.as_("owner").get("/worship/status", params={"business_id": BIZ}).json()
    assert "sunday_hub" not in r and "sunday" not in r
    assert r["enabled"] is True and "planner" in r["roles"]


# ─── the day-one roles ────────────────────────────────────────────────

ROLES_OF = {
    "owner": ["pastor", "planner", "team_leader", "media_tech", "ministry_ops"],
    "admin": ["pastor", "planner", "team_leader", "media_tech", "ministry_ops"],
    "planner": ["planner"],
    "csadmin": ["planner"],
    "worship": ["team_leader"],
    "booth": ["media_tech"],
    "streamer": ["media_tech"],
    "ministry": ["ministry_ops"],
    "volsched": [],
    "leader": ["team_leader"],
    "carer": [],
    "viewer": [],
}


@pytest.mark.parametrize("name", list(ROLES_OF))
def test_each_login_gets_its_day_one_roles(church, name):
    st = hub.standing(BIZ, PEOPLE[name])
    assert st["roles"] == ROLES_OF[name]
    assert st["approve"] is (name in ("owner", "admin"))
    assert st["reader"] is (name not in ("carer", "viewer"))


def test_leads(church):
    assert [t["group_id"] for t in hub.standing(BIZ, PEOPLE["worship"])["leads"]] == [WORSHIP]
    assert hub.standing(BIZ, PEOPLE["leader"])["leads"] == [{"group_id": WELCOME, "name": "Welcome",
                                                            "owner": "volunteers"}]
    assert hub.standing(BIZ, PEOPLE["planner"])["leads"] == []


def test_the_worship_part_plans_where_there_is_no_worship_team(church):
    church.db.t["serve_teams"] = [t for t in church.db.t["serve_teams"] if t["group_id"] != WORSHIP]
    st = hub.standing(BIZ, PEOPLE["worship"])
    assert st["roles"] == ["planner"] and st["leads"] == []


def test_a_leader_found_by_their_email_and_only_one(church):
    # The volsched login has no seat contact; its email names one person, who leads Production.
    lee = next(c for c in church.db.t["contacts"] if c["id"] == LEE)
    lee["email"] = "volsched@gracegrove.org"
    church.db.t["group_members"].append({"group_id": PRODUCTION, "business_id": BIZ, "contact_id": LEE,
                                         "role": "leader"})
    st = hub.standing(BIZ, PEOPLE["volsched"])
    assert st["roles"] == ["team_leader"]
    assert [t["name"] for t in st["leads"]] == ["Production", "Welcome"]
    # Two of the church's people with that email: nobody is guessed.
    church.db.t["contacts"].append({"id": "c0000000-0000-4000-8000-000000000077", "business_id": BIZ,
                                    "name": "Lee Two", "email": "VOLSCHED@gracegrove.org"})
    assert hub.standing(BIZ, PEOPLE["volsched"])["roles"] == []


def test_a_failed_read_is_never_no_role(church, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        hub.standing(BIZ, PEOPLE["worship"])
    assert e.value.status_code == 503


def test_require_reader(church, monkeypatch):
    for name in ("planner", "booth", "ministry", "volsched", "leader", "worship"):
        assert hub.require_reader(BIZ, PEOPLE[name])["reader"] is True
    for name in ("carer", "viewer"):
        with pytest.raises(HTTPException) as e:
            hub.require_reader(BIZ, PEOPLE[name])
        assert e.value.status_code == 403 and e.value.detail == hub.WALL
    monkeypatch.setenv("SUNDAY_HUB", "off")
    assert hub.require_reader(BIZ, PEOPLE["viewer"]) is None


# ─── /worship/status ──────────────────────────────────────────────────

def test_status_carries_the_roles(church):
    r = church.as_("owner").get("/worship/status", params={"business_id": BIZ}).json()
    assert r["sunday_hub"] is True
    s = r["sunday"]
    assert s["roles"] == ROLES_OF["owner"] and s["reader"] and s["approve"] and s["giving"]
    assert s["service_word"] == "Sunday" and s["service_word_set"] is False
    r = church.as_("leader").get("/worship/status", params={"business_id": BIZ}).json()["sunday"]
    assert r["roles"] == ["team_leader"] and r["approve"] is False and r["giving"] is False
    assert [t["name"] for t in r["leads"]] == ["Welcome"]
    # A care-only Manager: the status answers, and says there's no Sunday for them.
    r = church.as_("carer").get("/worship/status", params={"business_id": BIZ}).json()["sunday"]
    assert r == {"roles": [], "reader": False, "leads": [], "approve": False, "giving": False,
                 "service_word": "Sunday", "service_word_set": False}


def test_the_pastor_too_goes_through_the_giving_gate(church):
    # A church whose giving keeper holds the key back from the Admin login (or
    # where giving by service is off): the gate says no, and so does the status.
    church.state["giving"].discard("u-admin")
    s = church.as_("admin").get("/worship/status", params={"business_id": BIZ}).json()["sunday"]
    assert s["approve"] is True and s["giving"] is False
    church.state["giving"].discard("u-owner")
    assert church.as_("owner").get("/worship/status", params={"business_id": BIZ}).json()["sunday"]["giving"] is False


def test_status_never_503s_with_the_hub_on(church, monkeypatch):
    # The hub's own reads fail (the seat check before it answered as today).
    def broken(biz, user):
        raise HTTPException(503, "Who does what on Sunday couldn't be read just now. Try again.")
    monkeypatch.setattr(hub, "person_of", broken)
    r = church.as_("worship").get("/worship/status", params={"business_id": BIZ})
    assert r.status_code == 200
    s = r.json()["sunday"]
    assert r.json()["sunday_hub"] is True and s["unavailable"] is True
    assert s["roles"] == [] and s["reader"] is False and s["giving"] is False


def test_giving_follows_the_giving_gate(church):
    church.state["giving"].add("u-planner")
    assert church.as_("planner").get("/worship/status", params={"business_id": BIZ}).json()["sunday"]["giving"] is True
    church.state["giving"].discard("u-planner")
    assert church.as_("planner").get("/worship/status", params={"business_id": BIZ}).json()["sunday"]["giving"] is False


# ─── This Sunday or Next service ─────────────────────────────────────

def _plan(db, starts_at, template=False):
    db.t["worship_services"].append({"id": f"s-{len(db.t['worship_services'])}", "business_id": BIZ,
                                     "title": "Service", "starts_at": starts_at, "items": [], "archived_at": None,
                                     "is_template": template, "kind": "service"})


def test_the_word_is_worked_out_from_when_plans_fall(church):
    assert hub.worked_out_word(BIZ) == "Sunday"            # nothing planned yet
    for day in ("2026-11-28", "2026-12-05", "2026-12-12"):  # Saturday nights
        _plan(church.db, f"{day}T23:30:00Z")              # 5:30 PM Saturday in Chicago
    assert hub.worked_out_word(BIZ) == "service"
    for day in ("2026-11-29", "2026-12-06", "2026-12-13"):
        _plan(church.db, f"{day}T16:30:00Z")
    assert hub.worked_out_word(BIZ) == "Sunday"            # half and half reads as Sunday


def test_the_church_chooses_its_word(church):
    as_ = church.as_
    for who in ("planner", "booth", "ministry"):
        assert as_(who).put("/worship/service-word", json={"business_id": BIZ, "word": "service"}).status_code == 403
    assert as_("owner").put("/worship/service-word", json={"business_id": BIZ, "word": "Saturday"}).status_code == 400
    r = as_("owner").put("/worship/service-word", json={"business_id": BIZ, "word": "service"})
    assert r.status_code == 200 and r.json() == {"service_word": "service", "service_word_set": True}
    assert as_("leader").get("/worship/status", params={"business_id": BIZ}).json()["sunday"]["service_word"] == "service"
    r = as_("owner").put("/worship/service-word", json={"business_id": BIZ, "word": None})
    assert r.json() == {"service_word": "Sunday", "service_word_set": False}


def test_the_word_route_is_dark_while_the_switch_is_off(church, monkeypatch):
    monkeypatch.setenv("SUNDAY_HUB", "off")
    assert church.as_("owner").put("/worship/service-word", json={"business_id": BIZ, "word": "service"}).status_code == 404


# ─── the duty ─────────────────────────────────────────────────────────

def test_with_the_switch_off_the_duty_is_nowhere():
    # CI runs with SUNDAY_HUB unset: every duty list is exactly today's.
    assert "ministry_ops" not in cd.CATALOG and "ministry_ops" not in cd.ALL
    assert "ministry_ops" not in cd.STARTER["sunday_serving"] and len(cd.STARTER["sunday_serving"]) == 8
    import church_my_week
    assert "ministry_ops" not in church_my_week.DOOR
    assert "ministry_ops" not in cd._manager_duties({"sunday_serving"}, "u-1", {})


def test_with_the_hub_on_it_is_the_sunday_and_serving_lanes(monkeypatch):
    full = cd.with_ministry_ops(cd.CATALOG)
    assert list(full)[list(full).index("serve_schedule") + 1] == "ministry_ops"
    d = full["ministry_ops"]
    assert d["lanes"] == ["sunday_serving"] and d["area"] == "worship_media" and d["money"] is False
    lane = [k for k, v in full.items() if "sunday_serving" in v["lanes"]]
    assert set(hub.MINISTRY_OPS_DUTIES) == set(lane)
    assert "ministry_ops" in hub.SUNDAY_DUTIES
    monkeypatch.setattr(cd, "CATALOG", full)
    monkeypatch.setitem(cd.STARTER, "sunday_serving", lane)
    # The lane holds it, as long as it holds the lane's "Who serves when".
    assert "ministry_ops" in cd._manager_duties({"sunday_serving"}, "u-1", {})
    assert "ministry_ops" not in cd._manager_duties({"sunday_serving"}, "u-1", {"serve_schedule": ["u-2"]})
    # Moved to someone by name, it's theirs whatever else they hold.
    assert "ministry_ops" in cd._manager_duties(set(), "u-2", {"ministry_ops": ["u-2"], "serve_schedule": ["u-3"]})


# ─── POST /planning/sundays keeps its rule ────────────────────────────

def test_blank_sundays_for_whoever_schedules_either_door(church):
    as_ = church.as_
    # serve_schedule alone (the Volunteers board's "Add the next five Sundays").
    assert as_("volsched").post("/planning/sundays", json={"business_id": BIZ, "count": 1}).status_code == 200
    assert as_("planner").post("/planning/sundays", json={"business_id": BIZ, "count": 2}).status_code == 200
    for who in ("booth", "viewer", "carer"):
        assert as_(who).post("/planning/sundays", json={"business_id": BIZ, "count": 1}).status_code == 403, who
    assert as_("stranger").post("/planning/sundays", json={"business_id": BIZ, "count": 1}).status_code == 404


# ─── the helpers the hub's parts share ────────────────────────────────

def test_live_ok_reads_not_open_unless_a_mark_is_live(church):
    from datetime import datetime, timedelta, timezone
    sid = "s-live"
    church.db.t["worship_services"].append({"id": sid, "business_id": BIZ, "title": "Sunday", "items": []})
    assert hub.live_ok(BIZ, sid) == {"on": False, "until": None, "by": None}       # never marked (or no column)
    later = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    church.db.t["worship_services"][-1].update(live_ok_until=later, live_ok_by="u-owner")
    got = hub.live_ok(BIZ, sid)
    assert got["on"] is True and got["by"] == {"name": "The owner"} and got["until"]
    church.db.t["worship_services"][-1]["live_ok_by"] = "u-leader"
    assert hub.live_ok(BIZ, sid)["by"] == {"name": "Lee"}
    church.db.t["worship_services"][-1]["live_ok_by"] = "u-gone"
    assert hub.live_ok(BIZ, sid)["by"] == {"name": "The pastor"}
    earlier = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    church.db.t["worship_services"][-1]["live_ok_until"] = earlier
    assert hub.live_ok(BIZ, sid)["on"] is False


def test_team_areas_default_by_name_and_the_church_can_say(church):
    areas = hub.team_areas(BIZ)
    assert areas["song"] == WORSHIP
    assert all(areas[k] == PRODUCTION for k in ("announcement", "media", "countdown", "loop", "third"))
    assert areas["text"] is None and areas["scripture"] is None and areas["section"] is None
    church.db.t["worship_settings"].append({"business_id": BIZ, "team_areas": {"song": PRODUCTION, "text": WELCOME,
                                                                               "loop": "not-a-team"}})
    areas = hub.team_areas(BIZ)
    assert areas["song"] == PRODUCTION and areas["text"] == WELCOME and areas["loop"] is None
    assert hub.item_team({"kind": "song"}, areas) == PRODUCTION
    assert hub.item_team({"kind": "song", "team": WORSHIP}, areas) == WORSHIP


def test_open_to_ops_is_closed_unless_opened(church):
    assert hub.open_to_ops(BIZ) == set()
    church.db.t["serve_teams"][1]["open_to_ops"] = True
    assert hub.open_to_ops(BIZ) == {PRODUCTION}
