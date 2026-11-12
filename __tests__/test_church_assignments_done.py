"""Weekly jobs know when they're done, the team page and the Monday roll-up
say done / not yet / late, and the one-on-one (docs/CHURCH_ASSIGNMENTS.md,
PR B).

Pins, at the test churches (church_three), on Thursday November 12 (10 AM in
Detroit; the week of November 9):
  * each of the six weekly jobs counts what the doc says it counts:
    first-time guests (nobody in follow-up by the job's day with no one),
    who serves when (every place on the volunteers' teams has a yes for this
    Sunday), the calendar (next week has something, and every occasion names
    its place), sermon up (last Sunday's sermon is posted), attendance (this
    Sunday has a count that day), shepherding (every drifting family reached
    since Monday)
  * done / not yet / late by the login's picked day, else the catalog's; a
    read that fails claims nothing; nothing to count claims nothing
  * the team page and the roll-up carry the states, read once a table for
    the church however many logins; closed, nothing of it is read
  * the one-on-one: finished, stuck (how long, sent up), late, next five,
    this week's jobs; plain lines; for anyone over them; nothing recorded
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_assignments as cas  # noqa: E402
import church_my_week as mw  # noqa: E402
import church_team_week as ctw  # noqa: E402
import church_three as c3  # noqa: E402
import church_work_checks as cw  # noqa: E402
import sb_clients  # noqa: E402
from church_three import LOVE_CITY  # noqa: E402
from test_church_assignments import (NOW, TODAY, app, as_, db, give, login, patch, person, start,  # noqa: E402,F401
                                     task, uid)

MONDAY = date(2026, 11, 9)
SUNDAY = date(2026, 11, 15)
LAST_SUNDAY = date(2026, 11, 8)


def ctx(db, now=NOW):
    return cw.Ctx(c3.church(db, LOVE_CITY), now)


def job(db, duty, due, now=NOW):
    return cw.week_job(ctx(db, now), duty, due)


def at(d: date, hour: int = 15) -> str:
    return datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc).isoformat()


def _service(db, d: date, n: int = 0):
    sid = f"5d000000-0000-4000-8000-{d.toordinal():08d}{n:04d}"
    db.t.setdefault("worship_services", []).append({
        "id": sid, "business_id": LOVE_CITY, "title": "Sunday service", "starts_at": at(d), "archived_at": None,
        "is_template": False})
    return sid


def _volunteer_team(db, needed=2, owner="volunteers", name="Greeters"):
    gid = f"6d000000-0000-4000-8000-{len(db.t.get('serve_positions', [])):012d}"
    db.t["groups"].append({"id": gid, "business_id": LOVE_CITY, "name": name, "active": True, "kind": "team"})
    db.t.setdefault("serve_teams", []).append({"business_id": LOVE_CITY, "group_id": gid, "owner": owner})
    pid = gid.replace("6d", "7d", 1)
    db.t.setdefault("serve_positions", []).append({"id": pid, "business_id": LOVE_CITY, "group_id": gid,
                                                   "needed": needed, "active": True})
    return pid


# ─── The six jobs ─────────────────────────────────────────────────────

def test_first_guests_counts_who_came_in_by_the_jobs_day_with_no_one(db):
    assert job(db, "first_guests", MONDAY) == {"done": True, "text": "Everyone in follow-up by Monday has someone"}
    db.t["church_follow_ups"].append({"id": "fu-tue", "business_id": LOVE_CITY, "status": "open",
                                      "leader_contact_id": None, "created_at": at(date(2026, 11, 10))})
    assert job(db, "first_guests", MONDAY)["done"] is True, "Tuesday's is next week's job"
    wed = job(db, "first_guests", date(2026, 11, 11))
    assert wed == {"done": False, "text": "1 person in follow-up by Wednesday has no one"}
    db.t["church_follow_ups"].append({"id": "fu-back", "business_id": LOVE_CITY, "status": "handed_back",
                                      "leader_contact_id": db.who[LOVE_CITY]["tasha"], "created_at": at(MONDAY, 13)})
    assert job(db, "first_guests", MONDAY)["text"] == "1 person in follow-up by Monday has no one"


def test_who_serves_when_counts_this_sundays_volunteer_places_with_a_yes(db):
    assert job(db, "serve_schedule", date(2026, 11, 11)) == {"done": None, "text": "Nothing planned to fill this Sunday"}
    svc = _service(db, SUNDAY)
    assert job(db, "serve_schedule", date(2026, 11, 11))["done"] is None, "no volunteer places: nothing to count"
    pid = _volunteer_team(db, needed=2)
    _volunteer_team(db, needed=3, owner="churchsavvy", name="Band")          # ChurchSavvy's, never counted
    rows = db.t.setdefault("serve_assignments", [])
    rows += [{"business_id": LOVE_CITY, "service_id": svc, "position_id": pid, "slot": 1, "status": "yes"},
             {"business_id": LOVE_CITY, "service_id": svc, "position_id": pid, "slot": 2, "status": "asked"}]
    assert job(db, "serve_schedule", date(2026, 11, 11)) == {
        "done": False, "text": "1 of 2 places on Sunday's volunteer teams have a yes"}
    rows[1]["status"] = "yes"
    assert job(db, "serve_schedule", date(2026, 11, 11))["done"] is True


def test_the_calendar_counts_next_week_and_each_occasions_place(db):
    assert job(db, "calendar", date(2026, 11, 13)) == {"done": False, "text": "Nothing on next week's calendar yet"}
    _service(db, date(2026, 11, 22))
    assert job(db, "calendar", date(2026, 11, 13)) == {"done": True, "text": "1 thing on next week's calendar"}
    db.t.setdefault("custom_modules", []).append({"id": "mod-1", "business_id": LOVE_CITY, "name": "Services & Events",
                                                  "archetype": "event_roster", "is_active": True,
                                                  "archetype_params": {}})
    db.t.setdefault("module_entries", []).append({"id": "ev-1", "business_id": LOVE_CITY, "module_id": "mod-1",
                                                  "status": "active", "data": {"title": "Men's breakfast",
                                                                               "date": "2026-11-21", "location": ""}})
    assert job(db, "calendar", date(2026, 11, 13)) == {
        "done": False, "text": "2 things on next week's calendar, 1 without a place"}
    db.t["module_entries"][-1]["data"]["location"] = "Fellowship Hall"
    assert job(db, "calendar", date(2026, 11, 13))["done"] is True


def test_sermon_up_counts_last_sundays_published_sermon(db):
    assert job(db, "sermons", MONDAY) == {"done": False, "text": "Sunday's sermon isn't posted yet"}
    db.t["sermons"] = [{"business_id": LOVE_CITY, "published": False, "preached_on": LAST_SUNDAY.isoformat()}]
    assert job(db, "sermons", MONDAY)["done"] is False, "a draft isn't posted"
    db.t["sermons"][0]["published"] = True
    assert job(db, "sermons", MONDAY) == {"done": True, "text": "Sunday's sermon is posted"}


def test_attendance_counts_this_sunday_on_the_day_and_reads_nothing_before_it(db, monkeypatch):
    seen = []
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (seen.append(path), real(path, **kw))[1])
    assert job(db, "attendance", SUNDAY) == {"done": False, "text": "Sunday's count isn't in yet"}
    assert not [p for p in seen if p.startswith(("/attendance", "/attendance_headcounts"))]
    sunday_night = datetime(2026, 11, 16, 1, tzinfo=timezone.utc)                 # 8 PM Sunday in Detroit
    assert job(db, "attendance", SUNDAY, sunday_night)["done"] is False
    db.t["attendance"].append({"id": "a-1", "business_id": LOVE_CITY, "contact_id": db.who[LOVE_CITY]["kevin"],
                               "entry_id": "e-1", "method": "self", "checked_in_at": at(SUNDAY, 16)})
    assert job(db, "attendance", SUNDAY, sunday_night) == {"done": True, "text": "Sunday's count is in"}


def test_shepherding_counts_the_drifting_families_reached_since_monday(db):
    assert job(db, "shepherding", date(2026, 11, 12)) == {"done": True, "text": "No family is drifting"}
    fam = db.who[LOVE_CITY]["family"]
    db.t["church_shepherd_signals"].append({"id": "sig-1", "business_id": LOVE_CITY, "household_id": fam,
                                            "kind": "drift", "resolved_at": None})
    db.t["church_shepherd_touches"].append({"id": "t-old", "business_id": LOVE_CITY, "household_id": fam,
                                            "kind": "call", "created_at": at(date(2026, 11, 6))})
    assert job(db, "shepherding", date(2026, 11, 12)) == {
        "done": False, "text": "0 of 1 drifting family reached this week"}
    db.t["church_shepherd_touches"].append({"id": "t-new", "business_id": LOVE_CITY, "household_id": fam,
                                            "kind": "visit", "created_at": at(date(2026, 11, 10))})
    assert job(db, "shepherding", date(2026, 11, 12))["done"] is True


@pytest.mark.parametrize("duty,table", [("first_guests", "church_follow_ups"), ("sermons", "sermons"),
                                        ("shepherding", "church_shepherd_signals"), ("calendar", "worship_services")])
def test_a_read_that_fails_claims_nothing(db, monkeypatch, duty, table):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith(table + "?") else real(path, **kw))
    got = job(db, duty, MONDAY)
    assert got["done"] is None and got.get("unread"), got
    judged = mw._done_full(c3.church(db, LOVE_CITY), frozenset({duty}), TODAY, NOW, ctx(db).tz)
    assert duty not in judged, "never done, never late"


# ─── done / not yet / late ────────────────────────────────────────────

def test_late_is_after_the_jobs_day_and_the_picked_day_moves_it():
    assert mw.job_state(True, MONDAY, TODAY) == "done"
    assert mw.job_state(False, MONDAY, TODAY) == "late"
    assert mw.job_state(False, TODAY, TODAY) == "not_yet", "until the day is out"
    assert mw.job_state(False, date(2026, 11, 13), TODAY) == "not_yet"
    assert mw.job_state(None, MONDAY, TODAY) is None
    assert mw.due_day("first_guests", MONDAY) == MONDAY
    assert mw.due_day("first_guests", MONDAY, "Fri") == date(2026, 11, 13)
    assert mw.due_day("attendance", MONDAY, "Tue") == SUNDAY, "a Sunday job doesn't move"
    assert mw.due_day("stream", MONDAY) == SUNDAY, "Sat, Sun: the last of them"
    assert mw.due_day("monthly_report", MONDAY, today=TODAY) == date(2026, 11, 2)
    assert mw.due_day("building", MONDAY) is None, "weekly names no day"


def test_judged_jobs_carry_their_state_on_my_weeks_rhythm(app, db):
    db.t["church_follow_ups"].append({"id": "fu-1", "business_id": LOVE_CITY, "status": "open",
                                      "leader_contact_id": None, "created_at": at(MONDAY, 13)})
    r = mw.rhythm(c3.church(db, LOVE_CITY), uid(db, LOVE_CITY, "tiara"), "manager", NOW)
    items = {i["key"]: i for d in r["days"] for i in d["items"]}
    assert (items["first_guests"]["done"], items["first_guests"]["state"], items["first_guests"]["detail"]) == (
        False, "late", "1 person in follow-up by Monday has no one")
    assert (items["shepherding"]["state"], items["shepherding"]["state_text"]) == ("done", "Done")
    assert "state" not in items["care_visits"], "no check judges it"
    as_(app, LOVE_CITY, "tiara")
    assert app.put("/church/duty-days", json={"business_id": LOVE_CITY, "duty": "first_guests",
                                              "day": "Fri"}).status_code == 200
    r = mw.rhythm(c3.church(db, LOVE_CITY), uid(db, LOVE_CITY, "tiara"), "manager", NOW)
    fg = next(i for d in r["days"] for i in d["items"] if i["key"] == "first_guests")
    assert fg["state"] == "not_yet" and fg["picked"] == "Fri", "judged by her day"


# ─── The team page and the roll-up ────────────────────────────────────

def test_the_team_page_says_done_not_yet_late_and_reads_each_table_once(db, monkeypatch):
    db.t["church_follow_ups"].append({"id": "fu-1", "business_id": LOVE_CITY, "status": "open",
                                      "leader_contact_id": None, "created_at": at(MONDAY, 13)})
    db.t["sermons"] = [{"business_id": LOVE_CITY, "published": True, "preached_on": LAST_SUNDAY.isoformat()}]
    seen = []
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (seen.append(path), real(path, **kw))[1])
    page = ctw.team(c3.church(db, LOVE_CITY), NOW)
    rows = {r["user_id"]: r for r in page["team"]}
    tiara = {w["duty"]: w for w in rows[uid(db, LOVE_CITY, "tiara")]["this_week"]}
    assert (tiara["first_guests"]["state"], tiara["first_guests"]["state_text"], tiara["first_guests"]["due"]) == (
        "late", "Late", "2026-11-09")
    assert tiara["first_guests"]["detail"] == "1 person in follow-up by Monday has no one"
    assert tiara["shepherding"]["state"] == "done" and "state" not in tiara["care_visits"]
    shap = {w["duty"]: w for w in rows[uid(db, LOVE_CITY, "shapretta")]["this_week"]}
    assert shap["sermons"]["state"] == "done"
    naiya = {w["duty"]: w for w in rows[uid(db, LOVE_CITY, "naiya")]["this_week"]}
    assert naiya["calendar"]["state"] == "not_yet" and naiya["leaders_note"]["state"] == "late"
    assert rows[uid(db, LOVE_CITY, "tiara")]["this_week_counts"]["late"] == 1
    assert page["counts"]["late_jobs"] >= 2
    once = lambda t: sum(1 for p in seen if p.lstrip("/").startswith(t))  # noqa: E731
    # Each reader the jobs use, once for the church (a row's own counts read per login, as before).
    for table in (f"church_follow_ups?business_id=eq.{LOVE_CITY}&status=in.(open,handed_back)", "sermons?",
                  "church_shepherd_signals?", "church_shepherd_touches?", "worship_services?", "custom_modules?",
                  "events?"):
        assert once(table) <= 1, (table, once(table))
    # The text a login's week says by day only stays as it was.
    assert rows[uid(db, LOVE_CITY, "tiara")]["this_week_text"].startswith("Mon: First-time guests and welcome calls")


def test_the_monday_roll_up_says_each_jobs_state(db):
    db.t["church_follow_ups"].append({"id": "fu-1", "business_id": LOVE_CITY, "status": "open",
                                      "leader_contact_id": None, "created_at": at(MONDAY, 13)})
    page = ctw.team(c3.church(db, LOVE_CITY), NOW)
    tiara = next(r for r in page["team"] if r["user_id"] == uid(db, LOVE_CITY, "tiara"))
    line = ctw._line(tiara)
    assert "Late on the week: First-time guests and welcome calls." in line
    assert "Mon: First-time guests and welcome calls (late)" in line and "Thu: Shepherding (done)" in line
    assert "Tue: Care and visits ·" in line or line.rstrip().endswith("Tue: Care and visits"), "no state: its day only"


def test_closed_the_team_page_judges_nothing_and_reads_none_of_it(db, monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    seen = []
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (seen.append(path), real(path, **kw))[1])
    page = ctw.team(c3.church(db, LOVE_CITY), NOW)
    assert not [w for r in page["team"] for w in r.get("this_week", []) if "state" in w]
    assert "late_jobs" not in page["counts"] and not [r for r in page["team"] if "this_week_counts" in r]
    assert not [p for p in seen if p.lstrip("/").startswith(("church_shepherd", "sermons?", "worship_services"))
                or "status=in.(open,handed_back)" in p]


# ─── The one-on-one ───────────────────────────────────────────────────

def one_on_one(app, for_, biz=LOVE_CITY):
    return app.get(f"/church/assignments/one-on-one?business_id={biz}&for={for_}")


def test_the_one_on_one_says_finished_stuck_late_next_and_the_weeks_jobs(app, db):
    as_(app, LOVE_CITY, "jessica")
    start(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"))
    rooms = next(t for t in db.t["tasks"] if t.get("startup_key") == "rooms.listed")
    meet = next(t for t in db.t["tasks"] if t.get("startup_key") == "meetings.set_up")
    late = give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="Order the bulletins",
                due_date="2026-11-10").json()["saved"]["id"]
    as_(app, LOVE_CITY, "naiya")
    patch(app, rooms["id"], LOVE_CITY, stuck="Waiting on the floor plan")
    patch(app, meet["id"], LOVE_CITY, done=True)
    task(db, rooms["id"])["stuck_at"] = at(date(2026, 11, 6))                    # stuck since last Friday
    as_(app, LOVE_CITY, "jessica")
    app.post(f"/church/assignments/{rooms['id']}/raise", json={"business_id": LOVE_CITY})
    writes = len(db.writes)
    r = one_on_one(app, login(db, LOVE_CITY, "naiya"))
    assert r.status_code == 200, r.text
    o = r.json()
    assert len(db.writes) == writes, "nothing recorded"
    assert (o["for"], o["kind"], o["name"], o["today"]) == (login(db, LOVE_CITY, "naiya"), "login", "Naiya Clark",
                                                           "2026-11-12")
    # Nothing ticks here (nothing recorded): what she marked done is what's finished.
    assert [f["title"] for f in o["finished"]] == ["The staff huddle and the leaders meeting set up"]
    [s] = o["stuck"]
    assert (s["title"], s["days"], s["sent_up"], s["sent_up_to"], s["note"]) == (
        "Every room in the system", 6, True, "Pastor Kevin", "Waiting on the floor plan")
    assert [(i["title"], i["due_text"]) for i in o["late"]] == [("Order the bulletins", "2 days late")]
    assert [i["title"] for i in o["next"]] == ["The next 8 weeks on the calendar",
                                               "The church's policies in Files & policies",
                                               "Every department has a leader",
                                               "The week's news list and the first weekly text"]
    jobs = {w["duty"]: w for w in o["jobs"]}
    assert jobs["leaders_note"]["state"] == "late" and jobs["calendar"]["state"] == "not_yet"
    lines = o["lines"]
    assert lines[0].startswith("Finished in the last week: ")
    assert lines[1] == "Stuck: “Every room in the system” for 6 days, sent up to Pastor Kevin."
    assert lines[2] == "Late: “Order the bulletins”, 2 days late."
    assert lines[3].startswith("Next: “") and "due " in lines[3]
    assert lines[4].startswith("This week's jobs: The front desk, Mon; The Monday leaders note, late;")
    assert late


def test_the_one_on_one_for_a_person_has_no_jobs(app, db):
    as_(app, LOVE_CITY, "owner")
    o = one_on_one(app, person(db, LOVE_CITY, "yolanda")).json()
    assert o["kind"] == "person" and o["jobs"] == []
    assert [i["title"] for i in o["late"]] == ["Plan the youth lock-in"]
    assert o["lines"] == ["Nothing finished in the last week.", "Nothing stuck.",
                          "Late: “Plan the youth lock-in”, 17 days late.", "Nothing else is due."]


def test_the_one_on_one_is_gated_like_every_assignment_route(app, db, monkeypatch):
    as_(app, LOVE_CITY, "naiya")
    assert one_on_one(app, login(db, LOVE_CITY, "tiara")).status_code == 403
    assert one_on_one(app, login(db, LOVE_CITY, "naiya")).status_code == 403, "not with yourself"
    as_(app, LOVE_CITY, "jessica")
    assert one_on_one(app, login(db, LOVE_CITY, "minnie")).status_code == 403
    assert one_on_one(app, "nobody").status_code == 400
    assert app.get(f"/church/assignments/one-on-one?business_id={LOVE_CITY}").status_code == 422
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    assert one_on_one(app, login(db, LOVE_CITY, "naiya")).status_code == 404
