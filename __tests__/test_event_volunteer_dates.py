"""Event dates on Who serves when (serve_dates.py, sunday_planning.py,
supabase/APPLY-2026-11-17-event-volunteer-dates.sql). Kevin, 2026-11-17:
"build that", about Laquesha (the Sunday & Serving lane) being unable to
schedule greeters, ushers, parking, kids workers or hospitality for a
Thursday outreach night, a Saturday event or a Wednesday Bible study.

Pins:
  * the switch (CHURCH_EVENT_VOLUNTEERS, on when unset since 2026-11-21;
    owner is the platform owner's own church) and the migration: before
    either, nothing is offered
    and every route is a 404, never a 500; the schedule reads as before
  * who adds one: whoever changes the Volunteers' teams (Laquesha's
    serve_schedule, the owner, an Admin); ChurchSavvy's scheduler and a
    Manager with neither hear whose job it is; a booth volunteer and a viewer
    are refused as before
  * never a Sunday, never past, never too far ahead, never twice
  * picked from Services & Events (its title, day, time and place, once), or
    typed
  * only the Volunteers' teams serve it: ChurchSavvy's door doesn't list it,
    its teams are never asked, offered or filled for it, and it isn't one of
    a team's Sundays a month
  * the worship plan never sees it: ChurchSavvy's list, a service by id, a
    save, a delete, the order of service and the next service skip it
  * it comes off only while nobody was asked, and a Sunday never does
  * the member hears the real day: the ask, My serving, the .ics, the pack,
    the alerts and the email link say "Thursday", never "Sunday"
  * My week judges Sunday alone and says the week's event dates beside it

The duties each login holds are test_volunteers_door's (Love City once the
lanes split)."""
from __future__ import annotations

import os
import re
import sys
import types
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_marketing  # noqa: E402
import church_duties as cd  # noqa: E402
import church_work_checks as cwc  # noqa: E402
import member_asks  # noqa: E402
import member_portal_serving as mps  # noqa: E402
import sb_clients  # noqa: E402
import serve_dates as sd  # noqa: E402
import serve_links as sl  # noqa: E402
import sunday_order as so  # noqa: E402
import sunday_planning as sp  # noqa: E402
import sunday_serving as ss  # noqa: E402
import sunday_serving_alerts as ssa  # noqa: E402
import worship_show_router as wsr  # noqa: E402
import worship_team as wt  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from test_sunday_planning import (BIZ, JO, KENDRA, LEE, NOW, OTHER, OWNER_EMAIL, PRODUCTION, WELCOME, ZONE,  # noqa: E402
                                  FakeDb)
from test_volunteers_door import DUTIES, PEOPLE, SEATS  # noqa: E402

CHURCH = {"id": BIZ, "name": "Love City Church", "settings": {}}
MOD = "55555555-5555-4555-8555-555555555555"
# Services & Events at Love City (made up). NOW is Wednesday 21 October 2026,
# 10 AM in Chicago: the coming Sundays are 10/25 and 11/1.
E_THU, E_SAT, E_SUN, E_PAST, E_FAR, E_THEIRS = (f"e0000000-0000-4000-8000-{n:012d}" for n in range(1, 7))
ENTRIES = [
    (E_THU, BIZ, {"title": "Outreach night", "date": "2026-10-22T19:00", "location": "Fellowship hall"}),
    (E_SAT, BIZ, {"title": "Saturday clean-up", "date": "2026-10-24", "location": "The lot"}),
    (E_SUN, BIZ, {"title": "Sunday worship", "date": "2026-10-25T10:30"}),
    (E_PAST, BIZ, {"title": "Prayer walk", "date": "2026-10-20T18:00"}),
    (E_FAR, BIZ, {"title": "Summer picnic", "date": "2027-06-05T12:00"}),
    (E_THEIRS, OTHER, {"title": "Their night", "date": "2026-10-22T19:00"}),
]


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
    db.t["custom_modules"] = [{"id": MOD, "business_id": BIZ, "name": "Services & Events", "archetype": "event_roster",
                               "is_active": True, "archetype_params": {}}]
    db.t["module_entries"] = [{"id": i, "business_id": b, "module_id": MOD, "status": "active", "data": d,
                               "created_at": NOW.isoformat()} for i, b, d in ENTRIES]
    db.t["serve_notes"] = []
    db.t["worship_settings"] = []
    for name, fn in (("sb_get_as_service", db.get), ("sb_post_as_service", db.post),
                     ("sb_patch_as_service", db.patch), ("sb_delete_as_service", db.delete)):
        monkeypatch.setattr(sb_clients, name, fn)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.setenv("SUNDAY_PLANNING", "on")
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    monkeypatch.setenv("CHURCH_EVENT_VOLUNTEERS", "on")
    monkeypatch.delenv("CHURCHSAVVY_BILLING", raising=False)
    monkeypatch.setattr(sd, "_FORCE", True)
    monkeypatch.setattr(wt, "role_of", lambda biz, uid: SEATS.get(uid) if biz == BIZ else None)
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: ZONE)
    monkeypatch.setattr(sp, "_now", lambda: NOW)
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: False)

    def fake_standing(biz, uid):
        role = SEATS.get(str(uid))
        if role in ("owner", "admin"):
            return {"church": True, "role": role, "lanes": [], "duties": cd.ALL}
        held = DUTIES.get(str(uid), set()) if role == "manager" else set()
        return {"church": True, "role": role, "lanes": [], "duties": frozenset(held)}
    monkeypatch.setattr(cd, "standing", fake_standing)
    monkeypatch.setitem(sp._no_column, "at", 0.0)
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    for r in (sp.router, so.router, wsr.router):
        app.include_router(r)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client

    # Two Sundays; ChurchSavvy's Production (Sound: Kendra) and Volunteers'
    # Welcome (Greeter: Jo and Lee).
    assert as_("owner").post("/planning/sundays", json={"business_id": BIZ, "count": 2}).status_code == 200
    s1, s2 = (s["id"] for s in sorted(db.t["worship_services"], key=lambda s: s["starts_at"]))
    places = {}
    for gid, place, people in ((PRODUCTION, "Sound", [KENDRA]), (WELCOME, "Greeter", [JO, LEE])):
        r = as_("owner").post("/planning/teams", json={"business_id": BIZ, "group_id": gid, "places": [place]})
        assert r.status_code == 200, r.text
        pid = r.json()["team"]["places"][0]["id"]
        assert as_("owner").put(f"/planning/positions/{pid}/people", json={
            "business_id": BIZ, "people": [{"contact_id": c, "level": "trained"} for c in people]}).status_code == 200
        places[gid] = pid
    return types.SimpleNamespace(db=db, as_=as_, s1=s1, s2=s2, sound=places[PRODUCTION], greeter=places[WELCOME])


def seen(html):
    """What a member reads: the page without its stylesheet."""
    return re.sub(r"<style>.*?</style>", "", html, flags=re.S)


def add(c, who="laquesha", **body):
    fields = {"title": "Outreach night", "day": "2026-10-22", "time": "19:00", "place": "Fellowship hall"}
    return c.as_(who).post("/planning/dates", json={"business_id": BIZ, **(body or fields)})


def event(c, who="laquesha", **body):
    r = add(c, who, **body)
    assert r.status_code == 200, r.text
    return r.json()["date"]


def status(c, who="laquesha"):
    r = c.as_(who).get(f"/planning/status?business_id={BIZ}")
    assert r.status_code == 200, r.text
    return r.json()


def schedule(c, owner=None, who="laquesha"):
    r = c.as_(who).get(f"/planning/schedule?business_id={BIZ}&weeks=2" + (f"&owner={owner}" if owner else ""))
    assert r.status_code == 200, r.text
    return r.json()


def ask(c, sid, pid, cid, who="laquesha"):
    return c.as_(who).post("/planning/ask", json={"business_id": BIZ, "service_id": sid, "position_id": pid,
                                                   "contact_id": cid})


# ─── the switch and the migration ────────────────────────────────────


def test_the_switch(church, monkeypatch):
    c = church
    assert status(c)["event_dates"] is True
    monkeypatch.setenv("CHURCH_EVENT_VOLUNTEERS", "off")
    assert status(c)["event_dates"] is False and status(c, "owner")["event_dates"] is False
    assert add(c).status_code == 404
    assert c.as_("laquesha").get(f"/planning/events?business_id={BIZ}").status_code == 404
    # owner (the default until 2026-11-21): the platform owner's own church.
    monkeypatch.setenv("CHURCH_EVENT_VOLUNTEERS", "owner")
    assert sd.mode() == "owner"
    assert status(c, "owner")["event_dates"] is True, "the platform owner signed in is known at once"
    assert status(c)["event_dates"] is False and add(c).status_code == 404
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: biz == BIZ)
    assert status(c)["event_dates"] is True, "Laquesha, at the platform owner's church"
    assert add(c).status_code == 200
    # A word the switch doesn't know is off, never on.
    monkeypatch.setenv("CHURCH_EVENT_VOLUNTEERS", "yes please")
    assert sd.mode() == "off" and status(c, "owner")["event_dates"] is False


def test_unset_is_on_for_every_church_and_off_still_rolls_it_back(church, monkeypatch):
    """On for every church since 2026-11-21, with EVENT_VOLUNTEERS (Kevin:
    "switch on today"). Unset, whoever schedules the teams at a church that
    isn't the platform owner's adds an event date, with nobody asking whose
    church it is. off, the rollback, closes it again."""
    c = church
    monkeypatch.delenv("CHURCH_EVENT_VOLUNTEERS", raising=False)
    looked = []
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: looked.append(biz) or False)
    assert sd.mode() == "on" and sd.open_for(BIZ) is True
    assert status(c)["event_dates"] is True, "Laquesha, at a church that isn't the platform owner's"
    assert add(c).status_code == 200
    assert looked == [], "an unset switch is on: it never looks up the platform owner's church"
    monkeypatch.setenv("CHURCH_EVENT_VOLUNTEERS", "off")
    assert status(c)["event_dates"] is False and status(c, "owner")["event_dates"] is False
    assert c.as_("laquesha").get(f"/planning/events?business_id={BIZ}").status_code == 404


def test_before_the_migration_nothing_is_offered_and_nothing_breaks(church, monkeypatch):
    c = church
    monkeypatch.setattr(sd, "_FORCE", False)
    assert status(c, "owner")["event_dates"] is False
    assert add(c, "owner").status_code == 404
    assert c.as_("owner").get(f"/planning/events?business_id={BIZ}").status_code == 404
    assert c.as_("owner").delete(f"/planning/dates/{c.s1}?business_id={BIZ}").status_code == 404
    j = schedule(c, who="owner")
    assert [s["kind"] for s in j["services"]] == ["service", "service"] and j["event_dates"] is False
    assert c.as_("owner").get(f"/worship/services?business_id={BIZ}").status_code == 200
    # Nothing asks for the new columns or filters on them.
    seen = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: seen.append(path) or real(path))
    schedule(c, who="owner")
    c.as_("owner").get(f"/worship/services?business_id={BIZ}")
    assert seen and not [p for p in seen if "kind=neq" in p or ",kind" in p or "event_entry_id" in p]


def test_the_columns_are_asked_about_once(monkeypatch):
    calls = []
    monkeypatch.setattr(sd, "_FORCE", None)
    monkeypatch.setenv("SUPABASE_URL", "https://sb.test")
    monkeypatch.setattr(sd, "_STATE", {"yes": None, "at": 0.0})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: calls.append(path) or None)
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"status": 400, "code": "42703", "message": "no column"})
    assert sd.ready() is False and sd.plans_only() == "" and sd.fields() == ""
    assert len(calls) == 1, "kept for a minute"
    # Applied: the next look (after the minute) sees them, and keeps that.
    monkeypatch.setattr(sd, "_STATE", {"yes": None, "at": 0.0})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: calls.append(path) or [])
    assert sd.ready() is True and sd.plans_only() == "&kind=neq.event" and sd.fields() == ",kind,place,event_entry_id"
    # A blip later keeps what was known: never a sudden "not there".
    monkeypatch.setattr(sd, "_STATE", {"yes": True, "at": 0.0})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **k: None)
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"status": 503, "code": "", "message": "down"})
    assert sd.ready() is True


# ─── who adds one ────────────────────────────────────────────────────


def test_whoever_schedules_the_volunteers_adds_one(church):
    c = church
    d = event(c)
    assert d["kind"] == "event" and d["weekday"] == "Thursday" and d["title"] == "Outreach night"
    assert d["place"] == "Fellowship hall" and d["only"] == "volunteers" and d["day"] == "2026-10-22"
    assert d["time"] == "19:00" and d["event_entry_id"] is None
    row = next(s for s in c.db.t["worship_services"] if s["id"] == d["id"])
    assert row["kind"] == "event" and row["items"] == [] and row["starts_at"] == "2026-10-23T00:00:00+00:00"
    assert event(c, "owner", title="Bible study", day="2026-10-28", time="18:30")["weekday"] == "Wednesday"
    assert event(c, "admin", title="Fall festival", day="2026-10-31", time="16:00")["weekday"] == "Saturday"
    refused = cd.refusal(BIZ, "serve_schedule")
    for who in ("shapretta", "tiara"):
        r = add(c, who, title="Not mine", day="2026-10-29", time="19:00")
        assert r.status_code == 403 and r.json()["detail"] == refused, who
        assert status(c, who)["event_dates"] is False
        assert c.as_(who).get(f"/planning/events?business_id={BIZ}").status_code == 403
    for who in ("booth", "viewer"):
        r = add(c, who, title="Not mine", day="2026-10-29", time="19:00")
        assert r.status_code == 403 and r.json()["detail"] == wt.REFUSED["serve"], who
    assert status(c, "laquesha")["event_dates"] is True and status(c, "admin")["event_dates"] is True
    assert c.db.t["business_users"] == []


def test_never_a_sunday_never_past_never_twice(church):
    c = church
    def no(code, words, **body):
        r = add(c, **{"title": "Outreach night", "day": "2026-10-22", "time": "19:00", **body})
        assert r.status_code == code and words in r.json()["detail"], (body, r.text)
    no(400, "Add the next five Sundays", day="2026-10-25")
    no(400, "passed", day="2026-10-20")
    no(400, "passed", day="2026-10-21", time="08:00")
    no(400, "next 6 months", day="2027-06-05")
    no(400, "start time", time="")
    no(400, "start time", time="7pm")
    no(400, "the day", day="Thursday")
    no(400, "Give the event a name", title="  ")
    no(400, "120 letters", place="x" * 121)
    event(c)
    no(409, "already on Who serves when for Thursday, Oct 22", title="outreach NIGHT")
    # Another title the same night is its own date.
    assert add(c, title="Youth night", day="2026-10-22", time="19:00").status_code == 200
    # Nothing ChurchSavvy plans was made or moved.
    assert sorted(s.get("kind") or "service" for s in c.db.t["worship_services"]) == ["event", "event", "service", "service"]


def test_picked_from_services_and_events(church):
    c = church
    got = c.as_("laquesha").get(f"/planning/events?business_id={BIZ}").json()["events"]
    # Not the Sunday one, not the past one, not one months away, not another church's.
    assert [(e["title"], e["day"], e["weekday"], e["time"], e["place"]) for e in got] == [
        ("Outreach night", "2026-10-22", "Thursday", "19:00", "Fellowship hall"),
        ("Saturday clean-up", "2026-10-24", "Saturday", None, "The lot")]
    # An entry with no time asks for one; a time given wins.
    r = add(c, entry_id=E_SAT)
    assert r.status_code == 400 and "start time" in r.json()["detail"]
    sat = event(c, entry_id=E_SAT, time="09:00")
    assert (sat["title"], sat["place"], sat["time"], sat["event_entry_id"]) == ("Saturday clean-up", "The lot", "09:00", E_SAT)
    thu = event(c, entry_id=E_THU)
    assert (thu["time"], thu["weekday"], thu["event_entry_id"]) == ("19:00", "Thursday", E_THU)
    r = add(c, entry_id=E_THU)
    assert r.status_code == 409 and "already on Who serves when" in r.json()["detail"]
    assert c.as_("laquesha").get(f"/planning/events?business_id={BIZ}").json()["events"] == []
    for other in (E_SUN, E_PAST, E_FAR, E_THEIRS, "nope"):
        assert add(c, entry_id=other).status_code in (400, 404), other


# ─── only the volunteer teams ────────────────────────────────────────


def test_only_the_volunteer_teams_serve_it(church):
    c = church
    d = event(c)
    # This week's Thursday shows before its Sunday; the two Sundays still show.
    vol = schedule(c, "volunteers")
    assert [(s["day"], s["kind"]) for s in vol["services"]] == [
        ("2026-10-22", "event"), ("2026-10-25", "service"), ("2026-11-01", "service")]
    assert [t["name"] for t in vol["teams"]] == ["Welcome"]
    assert [s["kind"] for s in schedule(c, "churchsavvy", who="shapretta")["services"]] == ["service", "service"]
    assert [s["kind"] for s in schedule(c, who="viewer")["services"]] == ["event", "service", "service"]
    # ChurchSavvy's teams are never asked, offered or filled for it, by anyone.
    for who in ("owner", "shapretta"):
        r = ask(c, d["id"], c.sound, KENDRA, who)
        assert r.status_code == 409 and "Only the volunteer teams serve at Outreach night" in r.json()["detail"], who
        r = c.as_(who).post("/planning/offer", json={"business_id": BIZ, "service_id": d["id"], "position_id": c.sound})
        assert r.status_code == 409, who
    r = c.as_("owner").get(f"/planning/candidates?business_id={BIZ}&service_id={d['id']}&position_id={c.sound}")
    assert r.json()["candidates"] == []
    assert ask(c, d["id"], c.greeter, JO).status_code == 200
    filled = c.as_("owner").post("/planning/fill", json={"business_id": BIZ, "weeks": 2}).json()
    on_event = [r for r in c.db.t["serve_assignments"] if r["service_id"] == d["id"]]
    assert {r["position_id"] for r in on_event} == {c.greeter}, "no Production place on the event date"
    assert filled["asked"] == 4, "Sound twice, Greeter twice: the Sundays as before"
    # It isn't one of a team's Sundays a month: Jo is on the Thursday, and
    # at one Sunday a month Lee and Jo still take the two Sundays.
    assert c.as_("owner").patch(f"/planning/teams/{WELCOME}", json={"business_id": BIZ, "max_month": 1}).status_code == 200
    j = c.as_("owner").get(f"/planning/candidates?business_id={BIZ}&service_id={c.s2}&position_id={c.greeter}").json()
    jo = next(x for x in j["candidates"] if x["contact_id"] == JO)
    assert jo["load"] == 1, "the Sunday she was filled for, not the Thursday"
    t = c.as_("owner").get(f"/planning/candidates?business_id={BIZ}&service_id={d['id']}&position_id={c.greeter}").json()
    assert all(x["at_most"] == 0 for x in t["candidates"])


def test_a_team_leader_sees_only_the_dates_their_team_serves(church):
    import sunday_leading as sld
    c = church
    d = event(c)
    c.db.t["group_members"] += [{"business_id": BIZ, "group_id": PRODUCTION, "contact_id": KENDRA, "role": "leader"},
                                {"business_id": BIZ, "group_id": WELCOME, "contact_id": LEE, "role": "leader"}]
    assert d["id"] not in [s["id"] for s in sld.team_view(CHURCH, KENDRA, PRODUCTION)["services"]]
    assert d["id"] in [s["id"] for s in sld.team_view(CHURCH, LEE, WELCOME)["services"]]


# ─── the worship plan ────────────────────────────────────────────────


def test_the_worship_plan_never_sees_it(church):
    c = church
    d = event(c)
    sid = d["id"]
    listed = [s["id"] for s in c.as_("owner").get(f"/worship/services?business_id={BIZ}").json()["services"]]
    assert sid not in listed and {c.s1, c.s2} <= set(listed)
    for who in ("owner", "shapretta"):
        u = c.as_(who)
        assert u.get(f"/worship/services/{sid}?business_id={BIZ}").status_code == 404
        assert u.get(f"/worship/services/{sid}/show?business_id={BIZ}").status_code == 404
        r = u.put(f"/worship/services/{sid}", json={"business_id": BIZ, "items": [{"id": "a1", "kind": "text", "title": "Hi"}]})
        assert r.status_code == 404, who
        assert u.delete(f"/worship/services/{sid}?business_id={BIZ}").status_code == 404
        assert u.get(f"/planning/order?business_id={BIZ}&service_id={sid}").status_code == 404
    row = next(s for s in c.db.t["worship_services"] if s["id"] == sid)
    assert row["items"] == [] and row["archived_at"] is None
    # The next order of service is Sunday's, though the Thursday comes first.
    assert c.as_("owner").get(f"/planning/order?business_id={BIZ}").json()["service"]["id"] == c.s1
    assert sid not in [u["id"] for u in c.as_("owner").get(f"/planning/order?business_id={BIZ}").json()["upcoming"]]
    # Adding Sundays again leaves them, and the event date, as they are.
    assert c.as_("owner").post("/planning/sundays", json={"business_id": BIZ, "count": 2}).json() == {"added": 0}


def test_it_comes_off_only_while_nobody_was_asked(church, monkeypatch):
    c = church
    d = event(c)
    aid = ask(c, d["id"], c.greeter, JO).json()["assignment"]["id"]
    r = c.as_("laquesha").delete(f"/planning/dates/{d['id']}?business_id={BIZ}")
    assert r.status_code == 409 and "Take back its asks first" in r.json()["detail"]
    assert c.as_("shapretta").delete(f"/planning/dates/{d['id']}?business_id={BIZ}").status_code == 403
    assert c.as_("laquesha").delete(f"/planning/assignments/{aid}?business_id={BIZ}").status_code == 200
    # The switch off doesn't trap a date made while it was on.
    monkeypatch.setenv("CHURCH_EVENT_VOLUNTEERS", "off")
    assert c.as_("laquesha").delete(f"/planning/dates/{d['id']}?business_id={BIZ}").json() == {"ok": True}
    assert d["id"] not in [s["id"] for s in schedule(c, "volunteers")["services"]]
    # A Sunday never comes off here.
    assert c.as_("owner").delete(f"/planning/dates/{c.s1}?business_id={BIZ}").status_code == 404
    assert next(s for s in c.db.t["worship_services"] if s["id"] == c.s1)["archived_at"] is None


# ─── the member hears the real day ───────────────────────────────────


def test_the_member_hears_the_real_day(church, monkeypatch):
    import member_portal
    c = church
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **kw: f"<title>{title}</title>{body}")
    d = event(c)
    aid = ask(c, d["id"], c.greeter, JO).json()["assignment"]["id"]
    m = ss.mine(CHURCH, JO)
    a = m["asks"][0]
    assert a["service"]["weekday"] == "Thursday" and a["service"]["event"] is True
    assert "Greeter, Outreach night, Thursday" in mps._ask_row(a)
    v = ss.ask_view(CHURCH, JO, aid)
    assert (v["weekday"], v["event"], v["where"], v["can_do"]) == ("Thursday", True, "Fellowship hall", None)
    req = Request({"type": "http", "query_string": b"", "headers": []})
    html = mps.render_ask(CHURCH, None, req, {"id": JO, "name": "Jo Park"}, v)
    for words in ("Thursday · Outreach night", "Starts at 7:00 PM · Fellowship hall", "Can&#x27;t that day"):
        assert words in html, words
    assert "Sunday" not in seen(html) and "I can&#x27;t, but I can do" not in html
    # "I can't, but I can do …" has no other Sunday to offer for it.
    assert ss.answer(CHURCH, JO, aid, "other")["note"] == ""
    ss.answer(CHURCH, JO, aid, "yes")
    m = ss.mine(CHURCH, JO)
    assert m["soon_days"] == ["2026-10-22"] and m["next_day"] == "2026-10-25"
    row = mps._coming_row(m["coming"][0], m["next_day"], "", m["soon_days"])
    assert "Greeter · Outreach night this Thursday" in row and "Your Thursday" in row and "Sunday" not in seen(row)
    v = ss.ask_view(CHURCH, JO, aid)
    html = mps.render_ask(CHURCH, None, req, {"id": JO, "name": "Jo Park"}, v)
    assert "You&#x27;re on for Oct 22." in html or "You're on for Oct 22." in html
    assert "Your Thursday" in html and "Sunday" not in seen(html)
    cal = mps.ics(CHURCH, v)
    for words in ("SUMMARY:Greeter · Outreach night · Love City Church", "DESCRIPTION:Welcome. Starts at 7:00 PM.",
                  "LOCATION:Fellowship hall", "DTSTART:20261023T000000Z"):
        assert words in cal, words
    p = ss.pack(CHURCH, JO, aid)
    assert (p["weekday"], p["event"], p["where"], p["order"]) == ("Thursday", True, "Fellowship hall", [])
    html = mps.render_pack(CHURCH, None, req, {"id": JO, "name": "Jo Park"}, p)
    for words in ("<title>Your Thursday</title>", "Jo, here&#x27;s your Thursday", "It starts at 7:00",
                  "Greeter · Welcome · Fellowship hall", "Thursday, October 22 · 7:00 PM · Outreach night"):
        assert words in html, words
    assert "Sunday" not in seen(html)
    # A Sunday ask still reads as it always has.
    sun = ask(c, c.s1, c.greeter, LEE).json()["assignment"]["id"]
    assert "Greeter, Oct 25" in mps._ask_row(ss.mine(CHURCH, LEE)["asks"][0])
    assert "Service at 10:30 AM" in mps.render_ask(CHURCH, None, req, {"id": LEE, "name": "Lee Ford"},
                                                   ss.ask_view(CHURCH, LEE, sun))


def test_the_alerts_and_the_email_link_say_the_day(church, monkeypatch):
    c = church
    d = event(c)
    aid = ask(c, d["id"], c.greeter, JO).json()["assignment"]["id"]
    at = datetime(2026, 10, 22, 19, 0, tzinfo=ZONE)
    sunday = datetime(2026, 10, 25, 10, 30, tzinfo=ZONE)
    assert ssa._day(at) == "Thursday, Oct 22" and ssa._day(sunday) == "Oct 25"
    ctx = {"id": aid, "at": at, "place": "Greeter", "team": "Welcome", "title": "Outreach night",
           "day": ssa._day(at), "call": "", "time": "7:00", "asker": "Laquesha", "from": "Lee",
           "weekday": "Thursday", "for": ssa._for("Outreach night", at)}
    w = ssa.words("ask", ctx)
    assert w == {"title": "Can you serve on Greeter, Thursday, Oct 22?",
                 "body": "Laquesha asked for Outreach night. Tap Yes or Can't."}
    assert ssa.words("week", ctx)["title"] == "Next Thursday you're on Greeter"
    assert ssa.words("cover", ctx)["body"].startswith("Lee asked you to cover for them for Outreach night.")
    assert ssa._for("Sunday service", sunday) == "" and ssa._for("Easter", sunday) == ""
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    monkeypatch.setenv("APP_BASE_URL", "https://system.mysolutionist.app")
    monkeypatch.delenv("CHURCHSAVVY_APP_URL", raising=False)
    monkeypatch.setattr(sl, "time", types.SimpleNamespace(time=lambda: NOW.timestamp()))
    parts = ssa.email_parts({**CHURCH, "id": BIZ}, {"id": JO, "name": "Jo Park"}, "day", ssa.words("day", ctx), None, ctx)
    assert parts["cta"][0] == "See your Thursday"
    out = sl.view(sl.answer_token(BIZ, JO, aid, at))["ask"]
    assert (out["weekday"], out["event"], out["where"], out["day"], out["free"]) == (
        "Thursday", True, "Fellowship hall", "Thursday, Oct 22", [])


# ─── My week ─────────────────────────────────────────────────────────


def test_my_week_judges_sunday_and_says_the_event_beside_it(church, monkeypatch):
    c = church
    biz = next(b for b in c.db.t["businesses"] if b["id"] == BIZ)

    def job():
        return cwc.week_job(cwc.Ctx(biz, NOW, ZONE), "serve_schedule", NOW.astimezone(ZONE).date())

    assert job() == {"done": False, "text": "0 of 1 places on Sunday's volunteer teams have a yes"}
    d = event(c)
    assert job()["text"] == "0 of 1 places on Sunday's volunteer teams have a yes, and 0 of 1 for Thursday's Outreach night"
    aid = ask(c, d["id"], c.greeter, JO).json()["assignment"]["id"]
    c.as_("laquesha").post(f"/planning/assignments/{aid}/answer", json={"business_id": BIZ, "status": "yes"})
    got = job()
    assert got["done"] is False, "a full Thursday never makes Sunday look done"
    assert got["text"].endswith(", and 1 of 1 for Thursday's Outreach night")
    sun = ask(c, c.s1, c.greeter, LEE).json()["assignment"]["id"]
    c.as_("laquesha").post(f"/planning/assignments/{sun}/answer", json={"business_id": BIZ, "status": "yes"})
    assert job() == {"done": True, "text": "1 of 1 places on Sunday's volunteer teams have a yes, "
                                           "and 1 of 1 for Thursday's Outreach night"}
    # Before the migration it reads as it always has.
    monkeypatch.setattr(sd, "_FORCE", False)
    assert job() == {"done": True, "text": "1 of 1 places on Sunday's volunteer teams have a yes"}
