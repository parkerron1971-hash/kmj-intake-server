"""The leaders schedule, step 2: how many can be away at once
(church_schedule_limits.py and the step 2 parts of church_schedule.py;
docs/CHURCH_SCHEDULE.md, PRs S2-2 and S2-3). The platform owner, 2026-11-18:
"making sure that everyone is not gone at the same time on our services.
allowing only so many people off at the same time."

At New Hope (church_three: a made-up church of 500, every name in it made
up), on church_schedule_fake's tables with step 2's file applied
(build(limits=True)), through the real engine and the office routes. Pins:

  THE NUMBERS AND THE DAYS (S2-2)
    * the worked-out number is one in four, one at least; the church's own
      replaces it; a department has one only when a row says so
    * who sets what: the leaders number, the office number and the usual
      service days are the owner's and whoever oversees the office's, never
      an Admin's; a department's number is its leader's, its overseer's,
      theirs, and whoever keeps Who serves when
    * which days count: the church's own planned services, else its usual
      weekdays (set, else worked out from its plans: a Saturday church), else
      Sunday; every protected day; an event date for departments only
    * who is away is counted from the facts, each person once, never from an
      ask's state: a waiting ask is not counted and not shown
    * every read is paged or bounded (1,003 rows), every value in an address
      is quoted
    * a database with step 1's file alone: every route here is a 404, and the
      engine reads nothing of step 2 and behaves exactly as step 1

  THE LIMIT AND PROTECTED DAYS (S2-3)
    * an ask past the number, or on a protected day, is never refused: it is
      flagged and goes up; from a guarded person, to the owner alone
    * only someone who may give the exception says yes to it, and the yes is
      saved with its exception in one transaction; a member-app session
      gives one only on an ask that went up to that very person
    * the recheck: a yes on an ask that has run into something new since it
      was asked does not land; the ask is flagged, sent up, and the one who
      pressed yes reads a 409 in plain words
    * "can't make it" and the owner's own are never flagged or blocked, and
      still count for the next person who asks
    * nobody answers their own; nobody but the owner answers one they entered
    * a failed read is a 503 with nothing saved; a yes that fails never
      leaves half an exception; two answers at once land one after the other
    * no title word or role key decides anything
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_over as co  # noqa: E402
import church_schedule as cs  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_schedule_limits as csl  # noqa: E402
import church_schedule_tell as tell  # noqa: E402
import church_three as c3  # noqa: E402
import serve_dates as sd  # noqa: E402
from church_schedule_fake import NOW, as_, day  # noqa: E402
from fastapi import HTTPException  # noqa: E402

HOPE = c3.NEW_HOPE                       # a made-up church of 500: every name in it is made up
GRACE = c3.GRACE
NY = ZoneInfo("America/New_York")
SECRET = "Surgery for my mother that week"
SUN = day(32)                            # Sunday 20 December 2026; an ask for day(30)..day(37) holds it
NEXT_SUN, LAST_SUN = day(39), day(25)    # 27 December, 13 December
EVE = day(36)                            # Thursday 24 December
SEATED = ("elena", "yusuf", "wren", "kara", "celia", "amara", "abel", "esther")   # leaders with a Member login
TEAM = "5d000000-0000-4000-8000-000000000001"
BAND = "5d000000-0000-4000-8000-000000000002"


@pytest.fixture
def db(monkeypatch):
    d = fake.build(monkeypatch, limits=True)
    for h in SEATED:
        fake.seat(d, HOPE, h)
    for t in ("worship_services", "serve_teams", "serve_assignments"):
        d.t[t] = []
    return d


@pytest.fixture
def app(db):
    return fake.client(db)


@pytest.fixture
def bare(monkeypatch):
    """A database with step 1's file alone."""
    d = fake.build(monkeypatch)
    for h in SEATED:
        fake.seat(d, HOPE, h)
    return d


# ─── helpers ──────────────────────────────────────────────────────────

def church(db, biz=HOPE):
    return co.Church(c3.church(db, biz))


def cid(db, handle, biz=HOPE):
    return db.who[biz][handle]


def person(db, handle, biz=HOPE):
    return co.who(co.PERSON, cid(db, handle, biz))


def login(db, handle, biz=HOPE):
    return co.who(co.LOGIN, fake.uid(db, biz, handle))


def asks(db, biz=HOPE):
    return [r for r in db.t["church_away_asks"] if r["business_id"] == biz]


def row(db, ask_id):
    return next(r for r in db.t["church_away_asks"] if r["id"] == ask_id)


def facts(db, biz=HOPE):
    return [s for s in db.t["serve_away"] if s["business_id"] == biz]


def away(db, handle, start=SUN, end=None, biz=HOPE, id_=None):
    """An away date as it sits in serve_away: a fact, however it got there."""
    r = {"id": id_ or str(uuid.uuid4()), "business_id": biz, "contact_id": cid(db, handle, biz), "starts_on": start,
         "ends_on": end or start, "note": "", "ask_id": None, "kind": None, "created_at": NOW.isoformat()}
    db.t["serve_away"].append(r)
    return r


def get(app, who, path, biz=HOPE, **q):
    as_(app, biz, who)
    return app.get(f"/church/schedule/{path}", params={"business_id": biz, **q})


def put(app, who, biz=HOPE, **body):
    as_(app, biz, who)
    return app.put("/church/schedule/limits", json={"business_id": biz, **body})


def two(app):
    """The leaders number set to two, by the owner."""
    r = put(app, "owner", group="leaders", at_most=2)
    assert r.status_code == 200, r.text
    return r.json()


def full(app, db, on=SUN):
    """A Sunday with as many leaders away as may be: two, with the number at two."""
    two(app)
    away(db, "wren", on)
    away(db, "kara", on)


def ask(app, who, biz=HOPE, status=200, **kw):
    as_(app, biz, who)
    r = app.post("/church/schedule/asks", json={"business_id": biz, "starts_on": day(30), "ends_on": day(37),
                                                 "kind": "time_off", **kw})
    assert r.status_code == status, r.text
    return r.json().get("saved") if status == 200 else r.json()


def answer(app, who, ask_id, yes=True, biz=HOPE, status=200, **kw):
    as_(app, biz, who)
    r = app.post(f"/church/schedule/asks/{ask_id}/answer", json={"business_id": biz, "yes": yes, **kw})
    assert r.status_code == status, r.text
    return r.json().get("saved") if status == 200 else r.json()["detail"]


def protect(app, who="owner", on=EVE, name="Christmas Eve", status=200, biz=HOPE):
    as_(app, biz, who)
    r = app.post("/church/schedule/protected-days", json={"business_id": biz, "day": on, "name": name})
    assert r.status_code == status, r.text
    return r.json().get("saved") if status == 200 else r.json()["detail"]


def service(db, on, kind=None, hour=10, biz=HOPE, id_=None, **more):
    d = date.fromisoformat(on)
    at = datetime(d.year, d.month, d.day, hour, 30, tzinfo=NY).astimezone(timezone.utc)
    r = {"id": id_ or str(uuid.uuid4()), "business_id": biz, "title": "Worship", "starts_at": at.isoformat(),
         "archived_at": None, "is_template": False, **({"kind": kind} if kind else {}), **more}
    db.t["worship_services"].append(r)
    return r


def team(db, gid, name, dept, *members, owner="volunteers"):
    """A Sunday team hung from a department by name (a Serve option)."""
    db.t["groups"].append({"id": gid, "business_id": HOPE, "name": name, "kind": "team", "active": True})
    db.t["serve_teams"].append({"group_id": gid, "business_id": HOPE, "owner": owner, "sort": 0})
    for h in members:
        db.t["group_members"].append({"group_id": gid, "business_id": HOPE, "contact_id": cid(db, h), "role": "member"})
    d = next(x for x in db.t["church_departments"] if x["business_id"] == HOPE and x["name"] == dept)
    return d["id"]


def dept(db, name):
    return next(x["id"] for x in db.t["church_departments"] if x["business_id"] == HOPE and x["name"] == name)


def step2_reads(db):
    return [p for p in db.reads if fake.STEP2_NEW.search(p)]


def looked(db):
    """The reads only the limit makes: the protected days, the church's
    numbers, and the plans with their titles."""
    return [p for p in db.reads if p.startswith("/church_protected_days") or "leaders_limit" in p
            or (p.startswith("/worship_services") and "select=id,title," in p)]


# ─── The numbers ──────────────────────────────────────────────────────

def test_the_worked_out_number_is_one_in_four_and_one_at_least(app, db):
    assert [csl.default_limit(n) for n in (0, 1, 3, 4, 7, 8, 14, 400)] == [1, 1, 1, 1, 1, 2, 3, 100]
    got = get(app, "owner", "limits").json()
    assert got["leaders"] == {"at_most": 3, "set": None, "people": 14}, "fourteen leaders: three at once"
    assert got["office"] == {"at_most": 1, "set": None, "people": 6}
    assert got["service_weekdays"] == [7] and got["worked_out"] is True and got["can_set"] is True
    assert [(d["name"], d["at_most"]) for d in got["departments"]] == [
        ("Worship", None), ("Youth", None), ("Kids", None), ("Care", None)], "no row, no limit"
    ch = church(db)
    assert csl.limit_for(ch, "leaders") == 3 and csl.limit_for(ch, "office") == 1
    assert csl.limit_for(ch, "leaders", dept(db, "Worship")) is None


def test_the_churchs_own_number_replaces_the_worked_out_one_and_null_puts_it_back(app, db):
    got = put(app, "owner", group="leaders", at_most=5).json()
    assert got["leaders"] == {"at_most": 5, "set": 5, "people": 14}
    assert get(app, "owner", "limits").json()["leaders"] == {"at_most": 5, "set": 5, "people": 14}
    [st] = [s for s in db.t["church_schedule_settings"] if s["business_id"] == HOPE]
    assert (st["leaders_limit"], st["office_limit"], st["notice_days"]) == (5, None, 14)
    as_(app, HOPE, "owner")
    assert app.put("/church/schedule/settings", json={"business_id": HOPE, "notice_days": 21}).status_code == 200
    assert st["leaders_limit"] == 5, "saving the notice days leaves the number alone"
    assert put(app, "owner", group="leaders", at_most=None).json()["leaders"] == {"at_most": 3, "set": None, "people": 14}
    assert st["leaders_limit"] is None and st["notice_days"] == 21
    assert put(app, "owner", group="office", at_most=2).json()["office"]["at_most"] == 2


@pytest.mark.parametrize("bad", [0, 100, -1, "3", 2.5, True])
def test_a_number_is_one_to_ninety_nine(app, db, bad):
    assert put(app, "owner", group="leaders", at_most=bad).status_code == 400
    assert put(app, "owner", department_id=dept(db, "Worship"), at_most=bad).status_code == 400
    assert db.t["church_schedule_settings"] == [] and db.t["church_schedule_department_limits"] == []


def test_one_thing_is_set_at_a_time(app, db):
    assert put(app, "owner").status_code == 400
    assert put(app, "owner", group="leaders", at_most=2, service_weekdays=[6]).status_code == 400
    assert put(app, "owner", group="volunteers", at_most=2).status_code == 400
    assert put(app, "owner", group="leaders").status_code == 400, "no number said: only an explicit null puts it back"
    assert put(app, "owner", department_id=dept(db, "Worship")).status_code == 400
    assert put(app, "owner", department_id="not-an-id", at_most=2).status_code == 400
    assert put(app, "owner", department_id=str(uuid.uuid4()), at_most=2).status_code == 404
    grace = next(x["id"] for x in db.t["church_departments"] if x["business_id"] == GRACE)
    assert put(app, "owner", department_id=grace, at_most=2).status_code == 404, "another church's department"
    assert db.t["church_schedule_department_limits"] == []


def test_an_admin_sets_no_church_wide_number_and_no_usual_days(app, db):
    """Decision 7: the leaders number, the office number and the usual
    service days are the owner's and whoever oversees the office's."""
    for who in ("tessa", "olive", "sunny", "wren", "amara"):         # an Admin, two Managers, two leaders
        for body in ({"group": "leaders", "at_most": 2}, {"group": "office", "at_most": 2},
                     {"service_weekdays": [6]}, {"service_weekdays": None}):
            r = put(app, who, **body)
            assert r.status_code == 403 and r.json()["detail"] == cs.NOT_SETTER, (who, body)
    assert db.t["church_schedule_settings"] == []
    assert get(app, "tessa", "limits").json()["can_set"] is False
    for who in ("owner", "owen"):                                    # the owner, and whoever oversees the office
        assert put(app, who, group="leaders", at_most=4).status_code == 200
        assert put(app, who, service_weekdays=[6, 7]).status_code == 200
    assert not csl.may_set_limit(church(db), person(db, "nathan")), "a member-app session is a person: never"
    assert not csl.may_set_limit(church(db), person(db, "owen"))


def test_a_departments_number_is_set_by_those_who_run_it_and_whoever_keeps_who_serves_when(app, db):
    worship = dept(db, "Worship")               # led by Wren, with Abel over it
    for who in ("wren", "abel", "owner", "owen", "sunny", "tessa"):
        r = put(app, who, department_id=worship, at_most=2)
        assert r.status_code == 200, (who, r.text)
        assert next(d for d in r.json()["departments"] if d["id"] == worship)["at_most"] == 2
    for who in ("kara", "amara", "olive", "paige", "esther"):        # another department's, and people with no part in it
        r = put(app, who, department_id=worship, at_most=3)
        assert r.status_code == 403 and r.json()["detail"] == csl.NOT_DEPT_SETTER, who
    [saved] = db.t["church_schedule_department_limits"]
    assert (saved["department_id"], saved["at_most"], saved["set_by_user_id"]) == (
        worship, 2, fake.uid(db, HOPE, "tessa")) and saved["set_by_contact_id"] is None
    got = {d["name"]: d["can_set"] for d in get(app, "wren", "limits").json()["departments"]}
    assert got == {"Worship": True, "Youth": False, "Kids": False, "Care": False}
    assert put(app, "wren", department_id=worship, at_most=None).status_code == 200
    assert db.t["church_schedule_department_limits"] == [], "nothing: no limit again"
    assert not csl.may_set_limit(church(db), person(db, "wren"), worship), "from the member app comes later"


def test_who_reads_the_numbers(app, db):
    whole = get(app, "elena", "limits").json()                       # on the leaders schedule
    assert whole["leaders"]["people"] == 14 and whole["can_set"] is False
    assert get(app, "tessa", "limits").json()["office"]["people"] == 6, "in the office group"
    fake.seat(db, HOPE, "hugo")
    r = get(app, "hugo", "limits")
    assert r.status_code == 403 and r.json()["detail"] == csl.NOT_READER
    assert get(app, "hugo", "days").status_code == 403 and get(app, "hugo", "protected-days").status_code == 403
    # Whoever keeps Who serves when, taken off the leaders schedule: the departments, and no more.
    db.t["church_schedule_people"].append({"business_id": HOPE, "contact_id": cid(db, "sunny"), "listed": "remove",
                                           "grp": None})
    got = get(app, "sunny", "limits").json()
    assert got["leaders"] is None and got["office"] is None and len(got["departments"]) == 4
    away(db, "wren")
    [d] = [x for x in get(app, "sunny", "days", **{"from": SUN, "to": SUN}).json()["days"]]
    assert d["leaders"] is None and d["office"] is None, "no count of the leaders for them"


# ─── Which days count ─────────────────────────────────────────────────

def test_with_nothing_planned_the_days_that_count_are_sundays(app, db):
    ch = church(db)
    assert csl.usual_weekdays(ch) == [7]
    got = csl.service_days(ch, date(2026, 12, 14), date(2026, 12, 27))
    assert [(d["day"].isoformat(), d["kind"]) for d in got] == [("2026-12-20", "service"), ("2026-12-27", "service")]


def test_a_saturday_churchs_days_are_worked_out_from_its_own_plans(app, db):
    for n in (3, 10, 17):                       # three Saturdays ahead, in the church's own evening
        service(db, day(n), hour=18)
    ch = church(db)
    assert csl.usual_weekdays(ch) == [6], "a weekday its plans hold on two days or more"
    days = [d["day"].isoformat() for d in csl.service_days(ch, date(2026, 12, 14), date(2026, 12, 27))]
    assert days == ["2026-12-19", "2026-12-26"], "Saturdays, planned or not; no Sunday"
    got = get(app, "owner", "limits").json()
    assert got["service_weekdays"] == [6] and got["worked_out"] is True


def test_one_service_on_a_weekday_counts_that_day_and_not_the_weekday(app, db):
    service(db, day(1))                         # one Thursday night
    ch = church(db)
    assert csl.usual_weekdays(ch) == [7], "once is not usual"
    days = {d["day"].isoformat(): d["kind"] for d in csl.service_days(ch, date(2026, 11, 18), date(2026, 11, 29))}
    assert days == {day(1): "service", "2026-11-22": "service", "2026-11-29": "service"}


def test_a_service_late_in_the_evening_is_counted_on_the_churchs_own_day(app, db):
    """11:30 PM on Saturday in New York is already Sunday in UTC."""
    service(db, day(3), hour=23)
    got = csl.service_days(church(db), date(2026, 11, 21), date(2026, 11, 21))
    assert [d["day"].isoformat() for d in got] == [day(3)]


def test_the_churchs_own_usual_days_replace_what_is_worked_out(app, db):
    for n in (3, 10, 17):
        service(db, day(n))
    assert put(app, "owner", service_weekdays=[3, 7, 7]).status_code == 400, "a day named twice"
    for bad in ([], [0], [8], ["7"], "7", [True], [1, 2, 3, 4, 5, 6, 7, 1]):
        assert put(app, "owner", service_weekdays=bad).status_code == 400, bad
    got = put(app, "owner", service_weekdays=[7, 3]).json()
    assert got["service_weekdays"] == [3, 7] and got["worked_out"] is False
    assert csl.usual_weekdays(church(db)) == [3, 7]
    days = [d["day"].isoformat() for d in csl.service_days(church(db), date(2026, 12, 14), date(2026, 12, 20))]
    assert days == ["2026-12-16", "2026-12-20"], "Wednesday and Sunday; the Saturday plans are past this window"
    got = put(app, "owner", service_weekdays=None).json()
    assert got["service_weekdays"] == [6] and got["worked_out"] is True, "back to what its plans say"


def test_an_archived_plan_and_a_template_are_not_services(app, db):
    for n in (3, 10, 17):
        service(db, day(n), archived_at=NOW.isoformat())
        service(db, day(n), is_template=True)
    assert csl.usual_weekdays(church(db)) == [7]


def test_a_protected_day_counts_and_says_its_name(app, db):
    protect(app)
    got = csl.service_days(church(db), date(2026, 12, 21), date(2026, 12, 27))
    assert [(d["day"].isoformat(), d["kind"], d["name"]) for d in got] == [
        (EVE, "protected", "Christmas Eve"), ("2026-12-27", "service", "")]


def test_an_event_date_counts_for_a_department_only(app, db, monkeypatch):
    """Only the volunteers' teams serve an event date."""
    monkeypatch.setattr(sd, "_FORCE", True)
    service(db, day(36), kind="event", title="Outreach night")
    worship = team(db, TEAM, "Worship Team", "Worship", "wren", "n030", "n031")
    assert put(app, "wren", department_id=worship, at_most=1).status_code == 200
    two(app)
    away(db, "kara", day(36))
    away(db, "celia", day(36))                  # two leaders away that Thursday
    away(db, "n030", day(36))                   # and one of Worship's people
    [d] = get(app, "owner", "days", **{"from": day(36), "to": day(36)}).json()["days"]
    assert (d["kind"], d["name"], d["leaders"], d["office"]) == ("event", "Outreach night", None, None)
    assert d["departments"] == [{"id": worship, "name": "Worship", "away": 1, "at_most": 1, "full": True}]
    ch = church(db)
    got = csl.flags_for(ch, cid(db, "yusuf"), date.fromisoformat(day(36)), date.fromisoformat(day(36)))
    assert got == {"flags": [], "why": []}, "the leaders number is not asked about on an event date"
    got = csl.flags_for(ch, cid(db, "wren"), date.fromisoformat(day(36)), date.fromisoformat(day(36)),
                        department_id=worship)
    assert got["flags"] == ["over_limit"] and got["why"][0]["of"] == "department", "she is on that team"
    # Before the event-date columns every plan is a service, and nothing names the column.
    monkeypatch.setattr(sd, "_FORCE", False)
    db.reads.clear()
    assert csl.service_days(church(db), date.fromisoformat(day(36)), date.fromisoformat(day(36)))[0]["kind"] == "service"
    assert not [p for p in db.reads if p.startswith("/worship_services") and "kind" in p]


# ─── Counting who is away ─────────────────────────────────────────────

def test_who_is_away_is_counted_from_the_facts_each_person_once(app, db):
    two(app)
    away(db, "wren", day(30), day(34))
    away(db, "wren", SUN)                       # a second date over the same Sunday: still one person
    away(db, "tessa", SUN)                      # the office is its own group
    away(db, "hugo", SUN)                       # not on the leaders schedule: not counted at all
    ch = church(db)
    assert csl.away_on(ch, date.fromisoformat(SUN), "leaders") == {cid(db, "wren")}
    assert csl.away_on(ch, date.fromisoformat(SUN), "office") == {cid(db, "tessa")}
    [d] = get(app, "elena", "days", **{"from": SUN, "to": SUN}).json()["days"]
    assert d["leaders"] == {"away": 1, "at_most": 2, "full": False,
                            "who": [{"contact_id": cid(db, "wren"), "name": "Wren Ellis"}]}
    assert d["office"] == {"away": 1, "at_most": 1, "full": True,
                           "who": [{"contact_id": cid(db, "tessa"), "name": "Tessa Hale"}]}
    away(db, "kara", SUN)
    [d] = get(app, "elena", "days", **{"from": SUN, "to": SUN}).json()["days"]
    assert d["leaders"]["away"] == 2 and d["leaders"]["full"] is True


def test_a_waiting_ask_is_never_counted_and_never_shown(app, db):
    """Privacy: a count never tells anyone that someone has asked. Only an
    away date that was agreed is counted or named."""
    two(app)
    got = ask(app, "yusuf", reason=SECRET)
    other = ask(app, "celia")
    assert (got["state"], other["state"]) == ("asked", "asked")
    ch = church(db)
    assert csl.away_on(ch, date.fromisoformat(SUN), "leaders") == set()
    for who in ("elena", "wren", "tessa", "owner", "owen"):
        r = get(app, who, "days", **{"from": day(28), "to": day(40)})
        assert r.status_code == 200
        text = r.text
        assert "Yusuf" not in text and "Celia" not in text and SECRET not in text and "waiting" not in text, who
        assert all(d["leaders"]["away"] == 0 for d in r.json()["days"])
    third = ask(app, "esther")
    assert "over_limit" not in third["flags"], "two are waiting; nobody is away yet"
    answer(app, "amara", got["id"])
    [d] = get(app, "elena", "days", **{"from": SUN, "to": SUN}).json()["days"]
    assert d["leaders"]["who"] == [{"contact_id": cid(db, "yusuf"), "name": "Yusuf Grant"}], "agreed: now it counts"
    assert SECRET not in json.dumps(d)


def test_the_window_is_three_months_at_most(app, db):
    assert get(app, "owner", "days", **{"from": day(0), "to": day(93)}).status_code == 200
    assert get(app, "owner", "days", **{"from": day(0), "to": day(94)}).status_code == 400
    assert get(app, "owner", "days", **{"from": day(5), "to": day(4)}).status_code == 400
    assert get(app, "owner", "days", **{"from": "soon"}).status_code == 400
    assert get(app, "owner", "days", **{"from": "9999-12-30"}).status_code == 400, "the very end of the calendar"
    assert get(app, "owner", "volunteers", **{"from": day(0), "to": day(94)}).status_code == 400
    got = get(app, "owner", "days").json()
    assert (got["from"], got["to"]) == (day(0), day(62)), "from today for two months when unnamed"


# ─── Paged, bounded, quoted ───────────────────────────────────────────

def test_a_thousand_and_three_away_dates_are_all_read(app, db):
    """The project's max-rows is 1,000: a read that stops there would miss
    the one away date that fills the Sunday."""
    two(app)
    for i in range(1002):                       # a Monday nobody counts, sorted first
        away(db, "elliot", day(33), id_=f"00000000-0000-4000-8000-{i:012d}")
    away(db, "wren", SUN, id_="ffffffff-0000-4000-8000-000000000001")
    away(db, "kara", SUN, id_="ffffffff-0000-4000-8000-000000000002")
    db.reads.clear()
    [d] = get(app, "owner", "days", **{"from": SUN, "to": day(33)}).json()["days"]
    assert d["leaders"]["away"] == 2 and d["leaders"]["full"] is True
    pages = [p for p in db.reads if p.startswith("/serve_away?")]
    assert len(pages) >= 2 and any("id=gt." in p for p in pages), "a second page was asked for"
    assert ask(app, "yusuf")["flags"] == ["over_limit"]


def test_a_thousand_and_three_plans_are_all_read(app, db):
    for i in range(1002):                       # a great many on one Sunday, sorted first
        service(db, day(18), id_=f"00000000-0000-4000-8000-{i:012d}")
    service(db, day(17), id_="ffffffff-0000-4000-8000-000000000001")
    service(db, day(24), id_="ffffffff-0000-4000-8000-000000000002")
    assert csl.usual_weekdays(church(db)) == [6], "the two Saturdays were on the second page"


def test_a_team_of_a_thousand_and_three_is_counted_whole(app, db):
    worship = team(db, TEAM, "Worship Team", "Worship")
    for i in range(1003):
        db.t["group_members"].append({"group_id": TEAM, "business_id": HOPE, "role": "member",
                                      "contact_id": f"7c000000-0000-4000-8000-{i:012d}"})
    assert len(csl.department_people(church(db), worship)) == 1003
    assert next(d for d in get(app, "owner", "limits").json()["departments"] if d["id"] == worship)["people"] == 1003


def test_a_window_that_is_too_wide_is_refused_before_anything_is_read(app, db):
    db.reads.clear()
    with pytest.raises(HTTPException) as e:
        csl.picture(church(db), date(2026, 1, 1), date(2028, 1, 1))
    assert e.value.status_code == 400 and db.reads == []
    assert csl.PICTURE_DAYS < 500, "at most a year and eight weeks either side"


def test_every_value_in_an_address_is_quoted(app, db, monkeypatch):
    monkeypatch.setattr(sd, "_FORCE", True)
    worship = team(db, TEAM, "Worship Team", "Worship", "wren")
    put(app, "owner", department_id=worship, at_most=1)
    full(app, db)
    protect(app)
    db.reads.clear()
    get(app, "owner", "days")
    get(app, "owner", "limits")
    get(app, "owner", "volunteers")
    get(app, "owner", "protected-days")
    got = ask(app, "yusuf")
    answer(app, "owen", got["id"])
    mine = [p for p in db.reads if p.startswith(("/worship_services", "/serve_away", "/church_protected_days",
                                                 "/church_schedule", "/serve_teams", "/group_members", "/groups?"))]
    assert len(mine) > 12
    for p in mine:
        assert "+" not in p and " " not in p and "'" not in p, p
        assert f"business_id=eq.{HOPE}" in p, p
    assert [p for p in mine if p.startswith("/worship_services") and "%2B00%3A00" in p], "a moment, quoted"
    # What a caller types never reaches an address as it was typed.
    r = get(app, "owner", "days", **{"from": f"{SUN}&business_id=eq.{GRACE}"})
    assert r.status_code == 200 and all(GRACE not in p for p in db.reads)
    as_(app, HOPE, "owner")
    r = app.delete(f"/church/schedule/protected-days/x&business_id=eq.{GRACE}", params={"business_id": HOPE})
    assert r.status_code == 400


# ─── A database with step 1's file alone ──────────────────────────────

def test_before_step_twos_file_every_route_here_is_a_404(bare):
    app = fake.client(bare)
    assert get(app, "owner", "status").status_code == 200, "step 1 is there"
    for path in ("limits", "days", "protected-days", "volunteers"):
        assert get(app, "owner", path).status_code == 404, path
    assert put(app, "owner", group="leaders", at_most=2).status_code == 404
    as_(app, HOPE, "owner")
    assert app.post("/church/schedule/protected-days",
                    json={"business_id": HOPE, "day": EVE, "name": "Christmas Eve"}).status_code == 404
    assert app.delete(f"/church/schedule/protected-days/{uuid.uuid4()}", params={"business_id": HOPE}).status_code == 404
    assert step2_reads(bare) == [] and "absent: step 2" not in bare.refused


def test_before_step_twos_file_the_engine_is_exactly_step_one_and_reads_nothing_of_step_two(bare, monkeypatch):
    """Twenty leaders could be away that Sunday: nothing looks."""
    def never(*a, **k):
        raise AssertionError("step 2 was asked about on a database without it")
    for name in ("picture", "flags_for", "flags_of", "look", "_said", "_services", "_department_limits"):
        monkeypatch.setattr(csl, name, never)
    assert cs.step2() is False
    app = fake.client(bare)
    for h in ("wren", "kara", "celia", "esther", "abel"):
        away(bare, h)
    got = ask(app, "yusuf", reason=SECRET)
    assert got["flags"] == [] and got["to"]["name"] == "Amara Stone" and "excepted" not in got
    assert set(got) == {"id", "contact_id", "name", "group", "department", "kind", "starts_on", "ends_on", "state",
                        "flags", "to", "cover", "decided", "reason", "reason_hidden", "mine", "can_answer",
                        "can_withdraw", "created_at"}, "step 1's shape, key for key"
    said = answer(app, "amara", got["id"])
    assert said["state"] == "yes" and "excepted" not in said
    assert [sorted(r) for r in bare.rpcs] == [["p_ask_id", "p_business_id", "p_by_contact", "p_by_user", "p_note",
                                               "p_state"]], "step 1's function, with step 1's six names"
    assert [p for p, _r in bare.posts if p.startswith("/rpc/")] == ["/rpc/church_away_settle"]
    cant = ask(app, "elena", kind="cant", starts_on=day(1), ends_on=day(1))
    assert cant["state"] == "yes"
    get(app, "owner", "leaders")
    get(app, "owner", "asks", box="all")
    tell.sweep_tick(NOW + timedelta(hours=1))
    assert step2_reads(bare) == [] and "absent: step 2" not in bare.refused, "nothing of step 2 was named"
    assert "excepted" not in cs._fields() and cs._fields() == cs.FIELDS


def test_step_twos_own_check_is_asked_once_and_kept(bare, monkeypatch):
    import sb_clients
    monkeypatch.setattr(csl, "_FORCE", None)
    monkeypatch.setattr(csl, "_STATE", {"yes": None, "at": 0.0})
    monkeypatch.setattr(sb_clients, "sb_url", lambda: "https://db.example.test")
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"code": "PGRST205", "status": 404})
    bare.reads.clear()
    assert csl.ready() is False and csl.ready() is False
    assert bare.reads == ["/church_protected_days?select=id&limit=1"], "one cheap read, then kept"
    bare.limits = True
    bare.t["church_protected_days"] = []
    monkeypatch.setattr(csl, "_STATE", {"yes": None, "at": 0.0})
    assert csl.ready() is True and csl.ready() is True and len(bare.reads) == 2
    monkeypatch.setattr(csl, "_STATE", {"yes": True, "at": -10_000.0})          # ten minutes on, a blip
    bare.fail = {"get": "/church_protected_days"}
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"code": "", "status": 503})
    assert csl.ready() is True, "a blip keeps the last answer"


def test_no_other_suite_gains_a_read_the_tables_are_pinned_absent():
    """conftest's autouse pin, as it is for step 1."""
    assert csl._FORCE is False and csl.ready() is False and cs.step2() is False


# ─── Past the number: flagged, never refused, and it goes up ──────────

def test_an_ask_past_the_number_is_never_refused_it_is_flagged_and_goes_up(app, db):
    full(app, db)
    got = ask(app, "yusuf", reason=SECRET)
    assert got["state"] == "asked" and got["flags"] == ["over_limit"], "asked, not refused"
    assert got["to"] == {"kind": "login", "id": fake.uid(db, HOPE, "owen"), "name": "Owen Diaz"}, \
        "to whoever oversees the office, not the one over him"
    r = row(db, got["id"])
    assert (r["to_user_id"], r["to_contact_id"], r["excepted"]) == (fake.uid(db, HOPE, "owen"), None, [])
    assert facts(db) and not any(f.get("ask_id") for f in facts(db)), "no away date yet"
    # The same days with room: to the one over him, as step 1 does.
    db.t["serve_away"].clear()
    db.t["church_away_asks"].clear()
    got = ask(app, "yusuf")
    assert got["flags"] == [] and got["to"]["name"] == "Amara Stone"


def test_at_the_number_is_full_one_under_is_not(app, db):
    two(app)
    away(db, "wren")
    assert ask(app, "yusuf")["flags"] == [], "one away of two: room for one more"
    db.t["church_away_asks"].clear()
    away(db, "kara")
    assert ask(app, "yusuf")["flags"] == ["over_limit"]


def test_days_with_no_service_and_no_protected_day_are_never_past_the_number(app, db):
    """A Monday to Thursday trip, with every leader away all week."""
    two(app)
    for h in ("wren", "kara", "celia", "esther"):
        away(db, h, day(33), day(36))
    got = ask(app, "yusuf", starts_on=day(33), ends_on=day(36))
    assert got["flags"] == [] and got["to"]["name"] == "Amara Stone"


def test_their_own_away_dates_never_count_against_them(app, db):
    two(app)
    away(db, "wren")
    away(db, "yusuf")                           # already away that Sunday himself
    assert ask(app, "yusuf")["flags"] == []


def test_the_office_has_its_own_number(app, db):
    away(db, "tessa")                           # one of six in the office: the worked-out number is one
    got = ask(app, "paige")
    assert got["flags"] == ["over_limit"] and got["to"]["name"] == "Owen Diaz"
    assert ask(app, "yusuf")["flags"] == [], "the leaders are not full"


def test_a_guarded_persons_flagged_ask_goes_to_the_owner_alone(app, db):
    """Decision 8: no office standing is over a shepherd or a senior."""
    full(app, db)
    assert co.is_guarded(church(db), person(db, "elena")) and not co.is_guarded(church(db), person(db, "yusuf"))
    got = ask(app, "elena", reason=SECRET)
    assert got["flags"] == ["over_limit"]
    assert got["to"] == {"kind": "login", "id": c3.NH_OWNER, "name": "Pastor Nathan"}
    assert answer(app, "owen", got["id"], status=403) == cs.NOT_TO_YOU, "whoever oversees the office can't"
    assert answer(app, "amara", got["id"], status=403) == cs.NOT_TO_YOU
    assert row(db, got["id"])["state"] == "asked"
    said = answer(app, "owner", got["id"])
    assert said["state"] == "yes" and said["excepted"] == ["over_limit"]


def test_whoever_oversees_the_offices_own_flagged_ask_goes_to_the_owner(app, db):
    full(app, db)
    got = ask(app, "owen")
    assert got["flags"] == ["over_limit"] and got["to"]["name"] == "Pastor Nathan"
    assert answer(app, "owen", got["id"], status=403) == cs.NOT_TO_YOU, "nobody answers their own"
    assert answer(app, "owner", got["id"])["excepted"] == ["over_limit"]
    # Asked from the member app (no login entered it), then answered from the office app as the login he is.
    mine = cs.ask(church(db), person(db, "owen"), {"starts_on": day(31), "ends_on": day(33), "kind": "time_off"})
    assert mine["flags"] == ["over_limit"] and mine["to"]["name"] == "Pastor Nathan" and mine["can_answer"] is False
    assert row(db, mine["id"])["made_by"] is None
    assert cs.gives_exception(church(db), fake.uid(db, HOPE, "owen"), cid(db, "yusuf")), "he gives them to others"
    assert answer(app, "owen", mine["id"], status=403) == cs.NOT_TO_YOU, "never his own, whatever his standing"
    with pytest.raises(HTTPException) as e:
        cs.answer(church(db), person(db, "owen"), mine["id"], True)
    assert e.value.status_code == 403 and row(db, mine["id"])["state"] == "asked"


def test_a_department_past_its_number_flags_one_of_its_own_people(app, db):
    worship = team(db, TEAM, "Worship Team", "Worship", "wren", "n030", "n031")
    assert put(app, "wren", department_id=worship, at_most=1).status_code == 200
    away(db, "n030")
    got = ask(app, "wren")                      # she leads Worship and is on its team
    assert got["flags"] == ["over_limit"] and got["department"]["name"] == "Worship"
    assert got["to"]["name"] == "Owen Diaz"
    # Kara leads Kids: Worship's number is nothing to do with her, and Kids has none.
    assert ask(app, "kara")["flags"] == []
    # Abel is over Worship and on none of its teams: its number doesn't count him.
    assert ask(app, "abel")["flags"] == []


def test_a_team_hung_from_a_department_as_a_group_counts_too(app, db):
    worship = team(db, BAND, "The Band", "Worship", "wren", "n030")
    db.t["church_department_units"].append({
        "id": str(uuid.uuid4()), "business_id": HOPE, "department_id": worship, "kind": "group", "group_id": BAND,
        "role_id": None, "board_id": None, "worship_ministry_id": None, "label": ""})
    assert csl.department_people(church(db), worship) == {cid(db, "wren"), cid(db, "n030")}
    db.t["groups"].append({"id": TEAM, "business_id": HOPE, "name": "Youth Volunteers", "kind": "ministry",
                           "active": True})
    db.t["group_members"].append({"group_id": TEAM, "business_id": HOPE, "contact_id": cid(db, "n031"),
                                  "role": "member"})
    assert csl.department_people(church(db), dept(db, "Youth")) == set(), "a group with no Sunday team row is no team"


# ─── A protected day ──────────────────────────────────────────────────

def test_an_ask_on_a_protected_day_is_flagged_and_goes_up(app, db):
    protect(app)
    got = ask(app, "yusuf")
    assert got["state"] == "asked" and got["flags"] == ["protected_day"] and got["to"]["name"] == "Owen Diaz"
    both = None
    full(app, db)
    both = ask(app, "celia")
    assert both["flags"] == ["over_limit", "protected_day"]
    said = answer(app, "owen", both["id"])
    assert said["excepted"] == ["over_limit", "protected_day"], "each flag once, in order"
    assert ask(app, "kara", starts_on=day(40), ends_on=day(44))["flags"] == [], "days that miss it"


def test_protected_days_are_listed_added_renamed_and_removed(app, db):
    saved = protect(app)
    assert set(saved) == {"id", "day", "name"} and saved["day"] == EVE
    again = protect(app, "owen", name="Christmas Eve service")
    assert again["id"] == saved["id"] and len(db.t["church_protected_days"]) == 1, "one row a date: renamed"
    protect(app, on=day(60), name="Vision Sunday")
    got = get(app, "elena", "protected-days").json()
    assert got == {"days": [{"id": saved["id"], "day": EVE, "name": "Christmas Eve service"},
                            {"id": got["days"][1]["id"], "day": day(60), "name": "Vision Sunday"}], "can_change": False}
    assert get(app, "owner", "protected-days").json()["can_change"] is True
    assert get(app, "owner", "protected-days", **{"from": day(50), "to": day(70)}).json()["days"][0]["day"] == day(60)
    as_(app, HOPE, "owen")
    r = app.delete(f"/church/schedule/protected-days/{saved['id']}", params={"business_id": HOPE})
    assert r.status_code == 200 and r.json() == {"removed": {"id": saved["id"], "day": EVE,
                                                             "name": "Christmas Eve service"}}
    assert [d["day"] for d in db.t["church_protected_days"]] == [day(60)]
    assert app.delete(f"/church/schedule/protected-days/{saved['id']}", params={"business_id": HOPE}).status_code == 404


def test_only_the_owner_and_whoever_oversees_the_office_name_a_protected_day(app, db):
    for who in ("tessa", "olive", "sunny", "wren", "amara"):
        assert protect(app, who, status=403) == cs.NOT_SETTER, who
    assert db.t["church_protected_days"] == []
    saved = protect(app, "owen")
    for who in ("tessa", "wren"):
        as_(app, HOPE, who)
        r = app.delete(f"/church/schedule/protected-days/{saved['id']}", params={"business_id": HOPE})
        assert r.status_code == 403, who
    assert len(db.t["church_protected_days"]) == 1
    assert protect(app, on=day(-1), status=400) == csl.PAST_DAY
    assert protect(app, on="someday", status=400) == csl.BAD_DAY
    assert protect(app, name="  ", status=400) == csl.BAD_NAME
    assert protect(app, name="x" * 81, status=400) == csl.BAD_NAME
    assert protect(app, on=day(0), name="Tonight")["day"] == day(0), "today is still to come"


def test_another_churchs_protected_day_is_not_found_and_not_removed(app, db):
    saved = protect(app)
    as_(app, GRACE, "owner")
    r = app.delete(f"/church/schedule/protected-days/{saved['id']}", params={"business_id": GRACE})
    assert r.status_code == 404 and len(db.t["church_protected_days"]) == 1
    assert get(app, "owner", "protected-days", biz=GRACE).json()["days"] == []
    assert ask(app, "yusuf")["flags"] == ["protected_day"]
    got = cs.ask(church(db, GRACE), login(db, "owner", GRACE), {
        "starts_on": day(30), "ends_on": day(37), "kind": "time_off", "for": f"person:{cid(db, 'yvette', GRACE)}"})
    assert got["flags"] == [], "New Hope's day is nothing to Grace"


# ─── Who says yes to a flagged ask, and the exception ─────────────────

def test_only_the_owner_or_whoever_oversees_the_office_says_yes_to_a_flagged_ask(app, db):
    full(app, db)
    got = ask(app, "yusuf", reason=SECRET)
    for who in ("amara", "tessa", "olive", "sunny", "wren", "abel"):   # the one over him, an Admin, Managers, leaders
        assert answer(app, who, got["id"], status=403) == cs.NOT_TO_YOU, who
        assert answer(app, who, got["id"], yes=False, status=403) == cs.NOT_TO_YOU, who
    assert row(db, got["id"])["state"] == "asked" and db.rpcs == []
    shown = {a["id"]: a for a in get(app, "amara", "asks", box="to_me").json()["asks"]}
    assert got["id"] not in shown, "it is no longer hers"
    [mine] = get(app, "owen", "asks", box="to_me").json()["asks"]
    assert mine["can_answer"] is True and mine["reason"] == SECRET and mine["flags"] == ["over_limit"]
    said = answer(app, "owen", got["id"])
    assert said["state"] == "yes" and said["excepted"] == ["over_limit"] and said["decided"]["by"] == "Owen Diaz"


def test_a_yes_to_a_flagged_ask_is_saved_as_an_exception_in_one_transaction(app, db):
    full(app, db)
    got = ask(app, "yusuf")
    answer(app, "owen", got["id"])
    [call] = db.rpcs
    assert sorted(call) == ["p_ask_id", "p_business_id", "p_by_contact", "p_by_user", "p_excepted", "p_note",
                            "p_state"], "the seven-name function"
    assert call["p_excepted"] == ["over_limit"] and call["p_by_user"] == fake.uid(db, HOPE, "owen")
    assert [p for p, redact in db.posts if p.startswith("/rpc/")] == ["/rpc/church_away_settle_excepted"]
    assert all(redact for p, redact in db.posts if p.startswith("/rpc/"))
    r = row(db, got["id"])
    assert (r["state"], r["excepted"], r["decided_by_user_id"]) == ("yes", ["over_limit"], fake.uid(db, HOPE, "owen"))
    [fact] = [f for f in facts(db) if f.get("ask_id") == got["id"]]
    assert (fact["starts_on"], fact["ends_on"], fact["note"]) == (day(30), day(37), "")
    [seen] = [a for a in get(app, "yusuf", "asks", box="mine").json()["asks"]]
    assert seen["excepted"] == ["over_limit"], "the one who asked can see it was an exception"
    assert cs.withdraw(church(db), person(db, "yusuf"), got["id"])["state"] == "withdrawn"
    assert row(db, got["id"])["excepted"] == ["over_limit"], "a yes taken back keeps the exception it was given"


def test_not_this_one_to_a_flagged_ask_records_no_exception(app, db):
    full(app, db)
    got = ask(app, "yusuf")
    said = answer(app, "owen", got["id"], yes=False, note="Not that Sunday")
    assert said["state"] == "no" and said["excepted"] == []
    assert [p for p, _r in db.posts if p.startswith("/rpc/")] == ["/rpc/church_away_settle"]
    assert not [f for f in facts(db) if f.get("ask_id")]


def test_a_flagged_ask_whose_days_have_cleared_is_a_plain_yes(app, db):
    """The exception is the flags still true at the yes."""
    full(app, db)
    got = ask(app, "yusuf")
    db.t["serve_away"].clear()                  # the two who were away took theirs back
    said = answer(app, "owen", got["id"])
    assert said["state"] == "yes" and said["excepted"] == [] and said["flags"] == ["over_limit"]
    assert [p for p, _r in db.posts if p.startswith("/rpc/")] == ["/rpc/church_away_settle"], "step 1's own function"
    assert answer(app, "owner", got["id"], status=409) == cs.ALREADY


def test_only_the_flags_still_true_are_excepted(app, db):
    protect(app)
    full(app, db)
    got = ask(app, "yusuf")
    assert got["flags"] == ["over_limit", "protected_day"]
    db.t["church_protected_days"].clear()       # the day is no longer protected
    assert answer(app, "owen", got["id"])["excepted"] == ["over_limit"]


# ─── The recheck at yes ───────────────────────────────────────────────

def test_a_yes_on_an_ask_that_has_since_gone_past_the_number_does_not_land(app, db):
    two(app)
    got = ask(app, "yusuf", reason=SECRET)
    assert got["flags"] == [] and got["to"]["name"] == "Amara Stone"
    row(db, got["id"])["told_at"] = NOW.isoformat()                 # Amara had been told
    away(db, "wren")
    away(db, "kara")                                                # and then the Sunday filled
    db.later.clear()
    said = answer(app, "amara", got["id"], status=409)
    assert said == cs.WENT_UP.format(name="Owen Diaz")
    assert "full now" in said and "didn't go through" in said and "Owen Diaz" in said, "plain words"
    r = row(db, got["id"])
    assert r["state"] == "asked" and r["decided_at"] is None and r["excepted"] == [], "nothing was decided"
    assert r["flags"] == ["over_limit"] and (r["to_user_id"], r["to_contact_id"]) == (fake.uid(db, HOPE, "owen"), None)
    assert r["told_at"] is None, "so whoever it went up to is told"
    assert db.rpcs == [] and not [f for f in facts(db) if f.get("ask_id")], "no yes, no away date, no exception"
    assert len(db.later) == 1, "one notice handed on, for the new person"
    assert answer(app, "amara", got["id"], status=403) == cs.NOT_TO_YOU, "it is no longer hers"
    said = answer(app, "owen", got["id"])
    assert said["state"] == "yes" and said["excepted"] == ["over_limit"]


def test_a_yes_on_an_ask_that_now_touches_a_protected_day_does_not_land(app, db):
    got = ask(app, "elena")
    protect(app)                                # named after she asked
    said = answer(app, "amara", got["id"], status=409)
    assert said == cs.WENT_UP.format(name="Pastor Nathan"), "she is guarded: the owner alone"
    r = row(db, got["id"])
    assert (r["state"], r["flags"], r["to_user_id"]) == ("asked", ["protected_day"], c3.NH_OWNER)
    assert answer(app, "owen", got["id"], status=403) == cs.NOT_TO_YOU
    assert answer(app, "owner", got["id"])["excepted"] == ["protected_day"]


def test_someone_who_may_give_the_exception_is_told_to_say_yes_again(app, db):
    """The owner says yes to an ask that has filled since: it doesn't land
    the first time either. It is marked, and a second yes is the exception."""
    two(app)
    got = ask(app, "yusuf")
    away(db, "wren")
    away(db, "kara")
    said = answer(app, "owen", got["id"], status=409)
    assert said == cs.YOURS_NOW and "Say yes again" in said
    r = row(db, got["id"])
    assert (r["state"], r["flags"], r["to_user_id"]) == ("asked", ["over_limit"], fake.uid(db, HOPE, "owen"))
    assert db.rpcs == []
    assert answer(app, "owen", got["id"])["excepted"] == ["over_limit"]


def test_a_flagged_ask_that_runs_into_something_more_is_marked_before_anyone_says_yes(app, db):
    full(app, db)
    got = ask(app, "yusuf")
    row(db, got["id"])["told_at"] = NOW.isoformat()
    protect(app)
    db.later.clear()
    assert answer(app, "owen", got["id"], status=409) == cs.YOURS_NOW
    r = row(db, got["id"])
    assert r["flags"] == ["over_limit", "protected_day"] and r["to_user_id"] == fake.uid(db, HOPE, "owen")
    assert r["told_at"] == NOW.isoformat() and db.later == [], "it stayed where it was: nobody new to tell"
    assert answer(app, "owen", got["id"])["excepted"] == ["over_limit", "protected_day"]


def test_not_this_one_is_never_rechecked(app, db):
    two(app)
    got = ask(app, "yusuf")
    away(db, "wren")
    away(db, "kara")
    db.reads.clear()
    assert answer(app, "amara", got["id"], yes=False)["state"] == "no"
    assert looked(db) == []
    db.t["church_away_asks"].clear()
    ask(app, "celia")
    assert len(looked(db)) >= 3, "a planned ask does look"


def test_an_ask_entered_for_someone_never_goes_up_to_the_one_who_entered_it(app, db):
    """Nobody but the owner answers an ask they entered."""
    full(app, db)
    got = ask(app, "owen", **{"for": f"person:{cid(db, 'yusuf')}"})
    assert got["flags"] == ["over_limit"] and got["to"]["name"] == "Pastor Nathan"
    assert answer(app, "owen", got["id"], status=403) == cs.NOT_TO_YOU
    assert answer(app, "owner", got["id"])["excepted"] == ["over_limit"]
    mine = ask(app, "owner", starts_on=day(31), ends_on=day(33), **{"for": f"person:{cid(db, 'celia')}"})
    assert mine["to"]["name"] == "Owen Diaz"
    assert answer(app, "owner", mine["id"])["excepted"] == ["over_limit"], "the owner aside"


# ─── Never flagged, never blocked ─────────────────────────────────────

def test_cant_make_it_is_never_flagged_never_blocked_and_still_counts(app, db):
    two(app)
    protect(app, on=day(4), name="Harvest Sunday")
    away(db, "wren", day(4))
    away(db, "kara", day(4))                    # this coming Sunday is full, and protected
    db.reads.clear()
    got = ask(app, "celia", kind="cant", starts_on=day(4), ends_on=day(4), reason=SECRET)
    assert got["state"] == "yes" and got["flags"] == ["short_notice"] and got["excepted"] == []
    assert got["to"]["name"] == "Asher Lyle", "the one over her, told at once: it never went up"
    assert looked(db) == [], "nothing looked"
    assert [p for p, _r in db.posts if p.startswith("/rpc/")] == ["/rpc/church_away_settle"]
    [d] = get(app, "owner", "days", **{"from": day(4), "to": day(4)}).json()["days"]
    assert d["leaders"]["away"] == 3 and d["kind"] == "protected", "three away of two: nothing stopped her"
    db.t["church_protected_days"].clear()
    db.t["serve_away"][:] = [f for f in db.t["serve_away"] if f.get("ask_id")]      # only hers is left
    away(db, "wren", day(4))
    nxt = ask(app, "yusuf", starts_on=day(4), ends_on=day(4))
    assert "over_limit" in nxt["flags"], "her day counts for the next person who asks"


def test_the_owners_own_time_away_is_never_flagged_and_still_counts(app, db):
    full(app, db)
    protect(app, on=SUN, name="Christmas Sunday")
    as_(app, HOPE, "owner")
    r = app.post("/church/schedule/asks", json={"business_id": HOPE, "starts_on": day(30), "ends_on": day(37),
                                                 "kind": "time_off"})
    got = r.json()["saved"]
    assert got["state"] == "yes" and got["flags"] == [] and got["to"] is None and got["excepted"] == []
    [d] = get(app, "owner", "days", **{"from": SUN, "to": SUN}).json()["days"]
    assert d["leaders"]["away"] == 3 and cid(db, "nathan") in [w["contact_id"] for w in d["leaders"]["who"]]


# ─── A member-app session is a person ─────────────────────────────────

def test_a_member_app_session_gives_an_exception_only_on_an_ask_that_went_up_to_that_very_person(app, db):
    full(app, db)
    ch = church(db)
    his = ask(app, "yusuf", reason=SECRET)              # went up to Owen's login
    hers = ask(app, "elena", reason=SECRET)             # guarded: went up to the owner's login
    owen, nathan, amara = person(db, "owen"), person(db, "nathan"), person(db, "amara")
    # Each sees, and may answer, only the one that went up to them.
    assert [a["id"] for a in cs.waiting(ch, owen)] == [his["id"]]
    assert [a["id"] for a in cs.waiting(ch, nathan)] == [hers["id"]]
    assert cs.waiting(ch, amara) == []
    for me, ask_id in ((owen, hers["id"]), (nathan, his["id"]), (amara, his["id"]), (amara, hers["id"])):
        with pytest.raises(HTTPException) as e:
            cs.answer(church(db), me, ask_id, True)
        assert e.value.status_code == 403 and e.value.detail == cs.NOT_TO_YOU
        shaped = cs.shape(ch, me, row(db, ask_id), cs._names(ch, [row(db, ask_id)]))
        assert shaped["can_answer"] is False and shaped["reason"] is None and shaped["reason_hidden"] is True
    assert db.rpcs == []
    # In the office app the owner's login could answer Yusuf's; as a person in the member app he can't.
    assert cs.may_decide(ch, login(db, "owner"), row(db, his["id"])) is True
    assert cs.may_decide(ch, nathan, row(db, his["id"])) is False
    assert cs.answer(church(db), owen, his["id"], True)["excepted"] == ["over_limit"]
    said = cs.answer(church(db), nathan, hers["id"], True)
    assert said["excepted"] == ["over_limit"]
    r = row(db, hers["id"])
    assert (r["decided_by_contact_id"], r["decided_by_user_id"]) == (cid(db, "nathan"), None), "as a person"


def test_an_ask_that_names_a_person_and_carries_a_flag_is_nobodys_in_the_member_app(app, db):
    """A flagged ask always names a login. One that names a person (a row no
    route makes) gives that person no exception to hand out."""
    full(app, db)
    got = ask(app, "yusuf")
    r = row(db, got["id"])
    r.update(to_user_id=None, to_contact_id=cid(db, "amara"))
    assert cs.may_decide(church(db), person(db, "amara"), r) is False
    assert cs.may_decide(church(db), login(db, "amara"), r) is False
    assert cs.may_decide(church(db), login(db, "owen"), r) is True


def test_an_admin_never_gives_an_exception(app, db):
    full(app, db)
    got = ask(app, "yusuf")
    ch = church(db)
    assert not cs.gives_exception(ch, fake.uid(db, HOPE, "tessa"), cid(db, "yusuf"))
    assert cs.gives_exception(ch, fake.uid(db, HOPE, "owen"), cid(db, "yusuf"))
    assert not cs.gives_exception(ch, fake.uid(db, HOPE, "owen"), cid(db, "elena")), "guarded: the owner alone"
    assert cs.gives_exception(ch, c3.NH_OWNER, cid(db, "elena"))
    row(db, got["id"]).update(to_user_id=fake.uid(db, HOPE, "tessa"))       # even one that names her
    assert answer(app, "tessa", got["id"], status=403) == cs.NOT_TO_YOU
    assert not cs.held_right(ch, row(db, got["id"]))


# ─── Reads first; failures leave nothing half done ────────────────────

@pytest.mark.parametrize("table", ["/church_protected_days", "/worship_services", "/serve_away",
                                   "/church_schedule_settings?business_id=eq." + HOPE + "&select=leaders_limit"])
def test_a_failed_read_while_asking_is_a_503_with_nothing_saved(app, db, table):
    full(app, db)
    db.fail = {"get": table}
    assert ask(app, "yusuf", status=503)["detail"] == cs.UNREAD
    assert asks(db) == [] and db.later == [] and not [p for p, _r in db.posts if p.startswith("/church_away_asks")]


@pytest.mark.parametrize("table", ["/church_protected_days", "/worship_services", "/serve_away"])
def test_a_failed_read_at_the_yes_is_a_503_with_nothing_decided(app, db, table):
    full(app, db)
    got = ask(app, "yusuf")
    before = dict(row(db, got["id"]))
    db.fail = {"get": table}
    assert answer(app, "owen", got["id"], status=503) == cs.UNREAD
    assert row(db, got["id"]) == before and db.rpcs == [] and not [f for f in facts(db) if f.get("ask_id")]


def test_a_yes_whose_exception_fails_leaves_no_half_made_exception(app, db):
    full(app, db)
    got = ask(app, "yusuf")
    before = dict(row(db, got["id"]))
    db.fail = {"post": "/rpc/church_away_settle_excepted"}
    assert answer(app, "owen", got["id"], status=503) == cs.UNSAVED
    assert row(db, got["id"]) == before and not [f for f in facts(db) if f.get("ask_id")]
    db.fail = {}
    # The database refusing the exception undoes the yes with it (one statement).
    assert fake.settle_excepted(db, {"p_business_id": HOPE, "p_ask_id": got["id"], "p_state": "yes",
                                     "p_by_user": c3.NH_OWNER, "p_excepted": ["protected_day"]}) is None
    assert row(db, got["id"]) == before and not [f for f in facts(db) if f.get("ask_id")]
    assert answer(app, "owen", got["id"])["excepted"] == ["over_limit"]


def test_a_recheck_that_cannot_be_saved_is_a_503_and_the_ask_is_as_it_was(app, db):
    two(app)
    got = ask(app, "yusuf")
    away(db, "wren")
    away(db, "kara")
    before = dict(row(db, got["id"]))
    db.later.clear()
    db.fail = {"patch": "/church_away_asks"}
    assert answer(app, "amara", got["id"], status=503) == cs.UNSAVED
    assert row(db, got["id"]) == before and db.rpcs == [] and db.later == []
    db.fail = {}
    assert answer(app, "amara", got["id"], status=409).startswith(cs.FULL_NOW)


def test_two_answers_at_once_land_one_after_the_other(app, db):
    """The database decides: the second finds it settled and writes nothing."""
    full(app, db)
    got = ask(app, "yusuf")
    db.before_settle = lambda: fake.settle(db, {"p_business_id": HOPE, "p_ask_id": got["id"], "p_state": "no",
                                                "p_by_user": c3.NH_OWNER, "p_note": None})
    assert answer(app, "owen", got["id"], status=409) == cs.ALREADY
    r = row(db, got["id"])
    assert (r["state"], r["excepted"], r["decided_by_user_id"]) == ("no", [], c3.NH_OWNER), "no exception on a no"
    assert not [f for f in facts(db) if f.get("ask_id")]


def test_a_recheck_and_another_answer_at_once_never_both_land(app, db, monkeypatch):
    """The ask was answered in the moment between the look and the update:
    the update names the state and who it went to, so it changes nothing."""
    two(app)
    got = ask(app, "yusuf")
    away(db, "wren")
    away(db, "kara")
    real = cs._recheck

    def recheck(ch, me, r):
        out = real(ch, me, r)
        fake.settle(db, {"p_business_id": HOPE, "p_ask_id": got["id"], "p_state": "no", "p_by_user": c3.NH_OWNER})
        return out
    monkeypatch.setattr(cs, "_recheck", recheck)
    assert answer(app, "amara", got["id"], status=409) == cs.MOVED
    r = row(db, got["id"])
    assert (r["state"], r["flags"], r["to_contact_id"]) == ("no", [], cid(db, "amara")), "the no stands, untouched"


def test_a_failed_write_of_a_number_or_a_day_is_a_503_with_nothing_saved(app, db):
    db.fail = {"post": "/church_schedule_settings"}
    assert put(app, "owner", group="leaders", at_most=2).status_code == 503
    db.fail = {"post": "/church_schedule_department_limits"}
    assert put(app, "owner", department_id=dept(db, "Worship"), at_most=2).status_code == 503
    db.fail = {"post": "/church_protected_days"}
    assert protect(app, status=503) == cs.UNSAVED
    assert db.t["church_schedule_settings"] == [] and db.t["church_schedule_department_limits"] == [] \
        and db.t["church_protected_days"] == []
    db.fail = {"get": "/church_schedule_settings"}
    assert put(app, "owner", group="leaders", at_most=2).status_code == 503, "a read that fails: nothing is written"
    assert not [p for p, _r in db.posts if p.startswith("/church_schedule_settings")][2:]
    db.fail = {}
    saved = protect(app)
    db.fail = {"delete": "/church_protected_days"}
    as_(app, HOPE, "owner")
    assert app.delete(f"/church/schedule/protected-days/{saved['id']}", params={"business_id": HOPE}).status_code == 503
    assert len(db.t["church_protected_days"]) == 1


def test_a_failed_read_of_the_days_is_a_503_never_an_empty_page(app, db):
    for table in ("/worship_services", "/serve_away", "/church_protected_days", "/church_schedule_department_limits"):
        db.fail = {"get": table}
        assert get(app, "owner", "days").status_code == 503, table
    db.fail = {"get": "/serve_teams"}
    assert get(app, "owner", "limits").status_code == 503


# ─── By department: who of its people is away ─────────────────────────

def test_volunteers_by_department_is_read_only_and_never_holds_a_leaders_ask_or_a_reason(app, db):
    worship = team(db, TEAM, "Worship Team", "Worship", "wren", "n030", "n031")
    put(app, "wren", department_id=worship, at_most=2)
    away(db, "n030", day(30), day(34))
    away(db, "hugo", day(30), day(34))          # not Worship's
    mine = ask(app, "wren", reason=SECRET)      # a leader's ask, still waiting
    db.t["church_away_asks"].append({**row(db, mine["id"]), "id": str(uuid.uuid4()), "contact_id": cid(db, "n031"),
                                     "grp": "volunteers", "department_id": worship, "reason": SECRET,
                                     "flags": ["over_limit"]})
    writes = (len(db.posts), [dict(r) for r in db.t["church_away_asks"]])
    got = get(app, "sunny", "volunteers").json()            # whoever keeps Who serves when
    assert [d["name"] for d in got["departments"]] == ["Worship", "Youth", "Kids", "Care"]
    w = got["departments"][0]
    assert (w["at_most"], w["people"]) == (2, 3)
    assert w["away"] == [{"contact_id": cid(db, "n030"), "name": "N030 Member", "starts_on": day(30),
                          "ends_on": day(34)}]
    assert w["waiting"] == [{"contact_id": cid(db, "n031"), "name": "N031 Member", "starts_on": day(30),
                             "ends_on": day(37), "flags": ["over_limit"]}], "a volunteer's, and only theirs"
    text = json.dumps(got)
    assert SECRET not in text and "Wren" not in text and "reason" not in text and "Hugo" not in text
    assert (len(db.posts), [dict(r) for r in db.t["church_away_asks"]]) == writes, "it wrote nothing"
    assert not [p for p in db.reads if p.startswith("/church_away_asks") and "grp=eq.volunteers" in p
                and "reason" in p], "the reason isn't even read"
    # Those who run a department see their own; everyone else is refused.
    assert [d["name"] for d in get(app, "wren", "volunteers").json()["departments"]] == ["Worship"]
    assert [d["name"] for d in get(app, "abel", "volunteers").json()["departments"]] == ["Worship"]
    assert [d["name"] for d in get(app, "amara", "volunteers").json()["departments"]] == ["Youth", "Kids"]
    for who in ("owner", "owen", "tessa"):
        assert len(get(app, who, "volunteers").json()["departments"]) == 4, who
    for who in ("olive", "paige", "elena", "esther"):
        assert get(app, who, "volunteers").status_code == 403, who


# ─── The rule code reads the church's data, never a title ─────────────

def test_no_title_word_or_role_key_decides_anything_here():
    keys = re.compile(r"\b(pastor|executive_pastor|associate_pastor|elders|deacons|ministers|youth_pastor|"
                      r"worship_leader|team_leader|director_of_operations|childrens_director)\b")
    titles = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|directors?|executive|treasurers?|"
                        r"secretary|trustees?|reverend|apostles?|prophets?)\b", re.I)
    src = inspect.getsource(csl)
    code = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", src, flags=re.S))
    assert not keys.search(code) and not titles.search(code), (keys.search(code), titles.search(code))
    for fn in (cs.flagged, cs.gives_exception, cs.goes_up, cs.held_right, cs._may_except, cs.may_decide, cs._recheck,
               cs._send_up, cs.answer, cs.ask, cs.step2, cs._fields, tell.up_words, tell._sweep_church):
        code = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", inspect.getsource(fn), flags=re.S))
        assert not keys.search(code) and not titles.search(code), (fn.__name__, keys.search(code), titles.search(code))
