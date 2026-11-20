"""The week (church_week.py; docs/CHURCH_SCHEDULE.md, "Step 4: The week"): the
office's read-only page of every department's volunteers for one week, with
hours. The pastor approved the mock on 2026-11-19 ("go").

At New Hope (church_three: a made-up church of 500, every name in it made
up), on church_schedule_fake's tables, through the real gate, the real duty
and area rules, the real leaders map and church_serving's own hours and
checks. The week shown is Sunday Nov 22 to Saturday Nov 28, 2026, read on
Wednesday Nov 18: a Sunday service at 10:30 and an outreach night (an event
date) on Thursday at 7. Pins, one rule each, every one broken once on
purpose to see its test go red:

  1 WHO: require_user, a seat here, a church; the owner, an Admin and a
    Manager who keeps either door of Who serves when read every department,
    both doors; anyone else with a seat is a 403, a stranger a 404. Every read
    is this church's, every value quoted
  2 PAGED: no read stops at 1,000 rows (a team of 1,150 people)
  3 CHECKS: "Can't serve with kids yet" only for whoever may read who's
    cleared (church_serving's rule); for anyone else the page is byte for
    byte what it would be if the person had a check. Hours the same way
  4 PRIVATE: no away note, no ask, no reason, no answer's note, no phone, no
    email; names only of the church's own people on its teams and leaders
  5 PLAIN WORDS: no ids, keys or title words in anything the page shows
  6 THE SWITCH: CHURCH_WEEK off | owner | on, owner when unset
  7 BOUNDED: one week a call; a bad start is this week; a year back to six
    months ahead
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_schedule_fake as fake  # noqa: E402
import church_serving  # noqa: E402
import church_three as c3  # noqa: E402
import church_week as cw  # noqa: E402
import sb_clients  # noqa: E402
import serve_dates as sd  # noqa: E402
import sunday_planning as sp  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from church_schedule_fake import NOW  # noqa: E402

HOPE = c3.NEW_HOPE
NY = ZoneInfo("America/New_York")
KIDS = "7d000000-0000-4000-8000-0000000000a1"       # Kids Check-in: hangs from Kids by its name
BAND = "7d000000-0000-4000-8000-0000000000b1"       # Worship Team: ChurchSavvy's, hangs from Worship
LOT = "7d000000-0000-4000-8000-0000000000c1"        # Parking Team: the Volunteers', hangs from no department
NURSERY = "7e000000-0000-4000-8000-0000000000a1"
CHECKIN = "7e000000-0000-4000-8000-0000000000a2"
KEYS = "7e000000-0000-4000-8000-0000000000b1"
VOCALS = "7e000000-0000-4000-8000-0000000000b2"
LOTS = "7e000000-0000-4000-8000-0000000000c1"
P1, P2, P3, SUN, THU, NEXT_SUN = (f"7f000000-0000-4000-8000-{i:012d}" for i in range(1, 7))
WEEK = "2026-11-22"
SECRETS = ("SECRET-AWAY-NOTE", "SECRET-REASON", "SECRET-NO-NOTE", "SECRET-HOURS-NOTE")
# Made-up names for the made-up church's volunteers (its N0xx members renamed).
NAMES = {"n040": "Gemma Holt", "n041": "Lila Penn", "n042": "Dara Quinn", "n043": "Toby Wells", "n044": "Rory Vance",
         "n045": "Iris Crane", "n050": "Joel Pratt", "n051": "Nora Pike", "n052": "Ada Brooks", "n060": "Felix Rowe",
         "n061": "Hazel Dunn", "n062": "Cyril Ames", "n100": "Quinn Abbott"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
SNAKE = re.compile(r"\b[a-z]+_[a-z_]+\b")
TITLE_WORDS = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|overseers?|directors?|executive|"
                         r"treasurers?|secretary|owners?|trustees?|reverend|apostles?|prophets?)\b", re.I)
ROLE_KEYS = re.compile(r"\b(pastor|executive_pastor|associate_pastor|elders|deacons|ministers|youth_pastor|"
                       r"worship_leader|team_leader|director_of_operations|childrens_director)\b")


def _at(d, hour, minute=0):
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=NY).astimezone(timezone.utc).isoformat()


def _service(sid, d, hour=10, minute=30, kind="service", title="Sunday service", biz=HOPE):
    return {"id": sid, "business_id": biz, "title": title, "starts_at": _at(d, hour, minute), "archived_at": None,
            "is_template": False, "kind": kind, "place": "", "event_entry_id": None, "items": []}


def _contains(have, want) -> bool:
    if isinstance(want, dict):
        return isinstance(have, dict) and all(k in have and _contains(have[k], v) for k, v in want.items())
    return have == want


def _serving_reads(d, monkeypatch):
    """church_serving pages by offset and finds its records by JSON
    containment (metadata=cs.{...}); church_three's PostgREST does neither,
    so this layer does, the server's 1,000-row cap kept."""
    inner = sb_clients.sb_get_as_service

    def get(path, **kw):
        table, _, qs = path.partition("?")
        parts = [p for p in qs.split("&") if p]
        offset = next((int(p[7:]) for p in parts if p.startswith("offset=")), None)
        has = [p for p in parts if re.match(r"^[a-z_]+=cs\.", p)]
        if offset is None and not has:
            return inner(path, **kw)
        limit = next((int(p[6:]) for p in parts if p.startswith("limit=")), c3.ThreeDB.MAX_ROWS)
        rest = [p for p in parts if not p.startswith(("offset=", "limit=")) and p not in has]
        d.MAX_ROWS = 10 ** 9
        try:
            rows = inner(f"{table}?{'&'.join(rest)}", **kw)
        finally:
            del d.MAX_ROWS
        if rows is None:
            return None
        for p in has:
            col, _, raw = p.partition("=cs.")
            want = json.loads(unquote(raw))
            rows = [r for r in rows if _contains(r.get(col), want)]
        return rows[offset or 0:][:min(limit, c3.ThreeDB.MAX_ROWS)]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)


@pytest.fixture
def db(monkeypatch):
    """New Hope with three Sunday teams and one week of places:

    Kids Check-in (the Volunteers'; hangs from Kids, led by Kara Bell; its own
    leader Gemma Holt): Nursery (2) and Check-in (1). Sunday: Lila Penn said
    yes to the Nursery and has no check on record; Dara Quinn said yes to the
    Nursery and is away Nov 21 to 23; Toby Wells was asked for Check-in on
    Monday and hasn't answered (his check is on record). Rory Vance is away
    on Sunday; Iris Crane has asked to be away and still waits. Thursday's
    outreach night: every place open (Rory said no to Check-in).
    Worship Team (ChurchSavvy's; hangs from Worship, led by Wren Ellis): Keys
    (1) and Vocals (2). Sunday: Joel Pratt on Keys, Nora Pike on Vocals, one
    Vocals place open. It never serves the event date.
    Parking Team (the Volunteers'; no department; led by Felix Rowe): Lot (2).
    Sunday: Felix said yes, Hazel Dunn was asked on Monday. Thursday: open.

    Hours this year: Lila 3 (two Sundays), Dara 1.5, Joel 1.5, Felix 1.5,
    Hazel 2 (added by the office), Toby and Nora none: 9.5 in all."""
    d = fake.build(monkeypatch)
    for t in ("worship_services", "serve_teams", "serve_positions", "serve_trained", "serve_assignments",
              "serve_prefs", "group_meetings", "group_meeting_attendance"):
        d.t[t] = []
    for k in ("CHURCH_SERVING", "SUNDAY_PLANNING"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CHURCH_WEEK", "on")
    monkeypatch.setattr(sd, "_FORCE", True)
    for mod in (cw, church_serving, sp):
        monkeypatch.setattr(mod, "_now", lambda: NOW)
    _serving_reads(d, monkeypatch)
    w = d.who[HOPE]
    for h, name in NAMES.items():
        next(c for c in d.t["contacts"] if c["id"] == w[h])["name"] = name
    for gid, name, owner, sort, people in (
            (KIDS, "Kids Check-in", "volunteers", 0, (("n040", "leader"), ("n041", "member"), ("n042", "member"),
                                                     ("n043", "member"), ("n044", "member"), ("n045", "member"))),
            (BAND, "Worship Team", "churchsavvy", 1, (("n050", "member"), ("n051", "member"), ("n052", "member"))),
            (LOT, "Parking Team", "volunteers", 2, (("n060", "leader"), ("n061", "member"), ("n062", "member")))):
        d.t["groups"].append({"id": gid, "business_id": HOPE, "name": name, "kind": "team", "active": True})
        d.t["serve_teams"].append({"group_id": gid, "business_id": HOPE, "call_time": None, "max_month": 4,
                                   "owner": owner, "swap_needs_ok": False, "families": True, "sort": sort})
        for h, role in people:
            d.t["group_members"].append({"group_id": gid, "business_id": HOPE, "contact_id": w[h], "role": role})
    for pid, gid, name, needed, sort in ((NURSERY, KIDS, "Nursery", 2, 0), (CHECKIN, KIDS, "Check-in", 1, 1),
                                         (KEYS, BAND, "Keys", 1, 0), (VOCALS, BAND, "Vocals", 2, 1),
                                         (LOTS, LOT, "Lot", 2, 0)):
        d.t["serve_positions"].append({"id": pid, "business_id": HOPE, "group_id": gid, "name": name, "needed": needed,
                                       "note": "", "sort": sort, "active": True,
                                       "created_at": "2026-10-01T00:00:00+00:00"})
    d.t["worship_services"] += [
        _service(P1, date(2026, 11, 1)), _service(P2, date(2026, 11, 8)), _service(P3, date(2026, 11, 15)),
        _service(SUN, date(2026, 11, 22)),
        _service(THU, date(2026, 11, 26), 19, 0, kind="event", title="Outreach night"),
        _service(NEXT_SUN, date(2026, 11, 29))]
    monday = _at(date(2026, 11, 16), 9)
    for sid, pid, slot, h, status, extra in (
            (P1, NURSERY, 1, "n041", "yes", {}), (P1, KEYS, 1, "n050", "yes", {}),
            (P2, NURSERY, 1, "n041", "yes", {}), (P2, NURSERY, 2, "n042", "yes", {}),
            (P3, LOTS, 1, "n060", "yes", {}),
            (SUN, NURSERY, 1, "n041", "yes", {}), (SUN, NURSERY, 2, "n042", "yes", {}),
            (SUN, CHECKIN, 1, "n043", "asked", {"asked_at": monday}),
            (SUN, KEYS, 1, "n050", "yes", {}), (SUN, VOCALS, 1, "n051", "yes", {}),
            (SUN, LOTS, 1, "n060", "yes", {}), (SUN, LOTS, 2, "n061", "asked", {"asked_at": monday}),
            (THU, CHECKIN, 1, "n044", "no", {"note": "SECRET-NO-NOTE"})):
        assign(d, sid, pid, slot, w[h], status, **extra)
    d.t["serve_away"] += [
        {"id": "7a000000-0000-4000-8000-000000000001", "business_id": HOPE, "contact_id": w["n042"],
         "starts_on": "2026-11-21", "ends_on": "2026-11-23", "note": "SECRET-AWAY-NOTE", "ask_id": None, "kind": None},
        {"id": "7a000000-0000-4000-8000-000000000002", "business_id": HOPE, "contact_id": w["n044"],
         "starts_on": "2026-11-22", "ends_on": "2026-11-22", "note": "", "ask_id": None, "kind": None},
        # Someone on no team, away: not one of the week's.
        {"id": "7a000000-0000-4000-8000-000000000003", "business_id": HOPE, "contact_id": w["n100"],
         "starts_on": "2026-11-22", "ends_on": "2026-11-28", "note": "", "ask_id": None, "kind": None}]
    # Iris asked to be away on Sunday and still waits: never counted, never shown.
    d.t["church_away_asks"].append({
        "id": "7b000000-0000-4000-8000-000000000001", "business_id": HOPE, "contact_id": w["n045"],
        "made_by": None, "grp": "volunteers", "kind": "time_off", "starts_on": "2026-11-22", "ends_on": "2026-11-22",
        "reason": "SECRET-REASON", "state": "asked", "flags": [], "department_id": None,
        "to_user_id": None, "to_contact_id": w["n040"], "created_at": NOW.isoformat()})
    contact(d, "n043")["metadata"] = {"serving": {"check_on": "2026-06-01"}}
    contact(d, "n061")["metadata"] = {"serving": {"hours": [
        {"id": "7c000000-0000-4000-8000-000000000001", "on": "2026-10-03", "minutes": 120,
         "note": "SECRET-HOURS-NOTE", "by_name": "office"}]}}
    # Another church's rows that name New Hope's own places, days and people:
    # a read that forgot whose church it is would pick them up.
    d.t["serve_assignments"].append({"id": "00000000-0000-4000-8000-000000000001", "business_id": c3.GRACE,
                                     "service_id": SUN, "position_id": NURSERY, "slot": 2,
                                     "contact_id": w["n100"], "status": "yes", "asked_at": None, "note": ""})
    d.t["serve_away"].append({"id": "00000000-0000-4000-8000-000000000002", "business_id": c3.GRACE,
                              "contact_id": w["n041"], "starts_on": "2026-11-20", "ends_on": "2026-11-30",
                              "note": "", "ask_id": None, "kind": None})
    return d


def assign(d, sid, pid, slot, cid, status, **kw):
    d.t["serve_assignments"].append({"id": f"7f100000-0000-4000-8000-{len(d.t['serve_assignments']):012d}",
                                     "business_id": HOPE, "service_id": sid, "position_id": pid, "slot": slot,
                                     "contact_id": cid, "status": status, "asked_at": kw.get("asked_at"),
                                     "note": kw.get("note", ""), "swap_to": None, "notified_at": None})


def contact(d, handle):
    return next(c for c in d.t["contacts"] if c["id"] == d.who[HOPE][handle])


@pytest.fixture
def app(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    a = FastAPI()
    a.include_router(cw.router)
    who = {"id": None, "email": None}
    a.dependency_overrides[require_user] = lambda: AuthedUser(id=who["id"], email=who["email"], role="authenticated")
    c = TestClient(a)
    c.who, c.db = who, db
    return c


def get(app, handle, start=WEEK, biz=HOPE, path=""):
    fake.as_(app, HOPE, handle)
    params = {"business_id": biz}
    if start is not None:
        params["start"] = start
    return app.get(f"/church/week{path}", params=params)


def week(app, handle="sunny", start=WEEK):
    r = get(app, handle, start)
    assert r.status_code == 200, r.text
    return r.json()


def card(body, name):
    return next(c for c in body["departments"] if c["name"] == name)


def row(body, card_name, service_id, place, slot=1):
    svc = next(s for s in card(body, card_name)["services"] if s["service_id"] == service_id)
    return next(r for r in svc["rows"] if r["place"] == place and r["slot"] == slot)


def stranger_seat(db, handle, role, areas=None, lane=None):
    """A login at New Hope for one of its people, on any seat."""
    u = fake.seat(db, HOPE, handle, role=role)
    s = next(x for x in db.t["business_users"] if x["user_id"] == u)
    s.update(areas=areas, lane=lane)
    return u


# ─── The page ─────────────────────────────────────────────────────────

def test_the_week_as_whoever_keeps_the_volunteers_reads_it(app):
    """The Sunday & Serving lane's Manager: every department, both doors,
    the hours, and who can't serve with kids yet (church_serving gives that
    lane the background checks duty)."""
    body = week(app, "sunny")
    assert body["week"] == {"from": "2026-11-22", "to": "2026-11-28", "words": "Nov 22 to 28", "this_week": False,
                            "prev": "2026-11-15", "next": "2026-11-29"}
    assert body["counts"] == {"on": 6, "open": 7, "away": 2, "hours": 9.5}
    assert body["can"] == {"hours": True, "checks": True, "change": ["volunteers"]}
    assert [c["name"] for c in body["departments"]] == ["Worship", "Kids", "Parking Team"]
    worship, kids, lot = body["departments"]
    assert (worship["led_by"], worship["churchsavvy"], worship["open"], worship["label"]) == \
        ("Wren Ellis", True, 1, "1 open")
    assert [s["words"] for s in worship["services"]] == ["Sunday 10:30 AM"], "ChurchSavvy never serves an event date"
    assert (kids["led_by"], kids["churchsavvy"], kids["open"], kids["label"]) == ("Kara Bell", False, 4, "4 open")
    assert [s["words"] for s in kids["services"]] == ["Sunday 10:30 AM", "Thursday 7 PM · Outreach night"]
    assert (lot["led_by"], lot["group_id"], lot["department_id"], lot["label"]) == ("Felix Rowe", LOT, None, "2 open")
    assert kids["teams"] == [{"group_id": KIDS, "name": "Kids Check-in", "door": "volunteers", "churchsavvy": False}]

    lila = row(body, "Kids", SUN, "Nursery", 1)
    assert (lila["who"], lila["state"], lila["state_words"], lila["minutes"], lila["hours_words"]) == \
        ("Lila Penn", "cant_serve_kids", "Can't serve with kids yet", 180, "3 hours")
    dara = row(body, "Kids", SUN, "Nursery", 2)
    assert (dara["who"], dara["state"], dara["state_words"]) == ("Dara Quinn", "away", "Away")
    assert dara["find"] == {"group_id": KIDS, "service_id": SUN, "day": "2026-11-22"} and dara["note"] is None
    toby = row(body, "Kids", SUN, "Check-in")
    assert (toby["state_words"], toby["minutes"], toby["hours_words"], toby["find"]) == \
        ("No answer yet", 0, "No hours yet", None)
    rory = row(body, "Kids", THU, "Check-in")
    assert (rory["person"], rory["who"], rory["state"]) == (None, "Open place", "open"), "a no is an open place"
    assert rory["find"] == {"group_id": KIDS, "service_id": THU, "day": "2026-11-26"}
    vocals = row(body, "Worship", SUN, "Vocals", 2)
    assert (vocals["who"], vocals["find"], vocals["note"]) == \
        ("Open place", None, "The worship team fills this in ChurchSavvy.")
    assert row(body, "Worship", SUN, "Keys")["hours_words"] == "1.5 hours"

    assert [(x["kind"], x["title"], x["details"]) for x in body["look"]] == [
        ("short", "Kids is short one on Sunday: Nursery.",
         ["Dara Quinn is away. Two people on the Kids Check-in team are free that morning."]),
        ("short", "Worship is short one on Sunday: Vocals.", ["The worship team fills this in ChurchSavvy."]),
        ("no_answer", "Kids: Toby Wells hasn't answered for Sunday.", ["Toby was asked on Monday."]),
        ("no_answer", "Parking Team: Hazel Dunn hasn't answered for Sunday.", ["Hazel was asked on Monday."]),
        ("cant_serve_kids", "Kids: Lila Penn can't serve with kids yet.",
         ["Lila's background check isn't on record. Lila is on for Sunday."]),
        ("short", "Kids is short three on Thursday: Nursery (2), Check-in.", []),
        ("short", "Parking Team is short two on Thursday: Lot (2).", [])]
    assert body["look"][0]["find"] == {"group_id": KIDS, "service_id": SUN, "day": "2026-11-22"}
    assert body["look"][1]["find"] is None


def test_counts_and_free_read_the_facts_and_never_a_waiting_ask(app, db):
    """Iris has asked to be away on Sunday and still waits: she isn't away in
    the count, and she is one of the two free; nothing reads the asks."""
    db.reads.clear()
    body = week(app, "sunny")
    assert body["counts"]["away"] == 2
    assert "Two people on the Kids Check-in team" in body["look"][0]["details"][0]
    assert not [p for p in db.reads if p.startswith("/church_away_asks")]
    # Once her time away is a yes (a fact), she is away, and one fewer is free.
    db.t["serve_away"].append({"id": "7a000000-0000-4000-8000-000000000009", "business_id": HOPE,
                               "contact_id": db.who[HOPE]["n045"], "starts_on": "2026-11-22",
                               "ends_on": "2026-11-22", "note": "", "ask_id": None, "kind": None})
    body = week(app, "sunny")
    assert body["counts"]["away"] == 3
    assert body["look"][0]["details"] == ["Dara Quinn is away. One person on the Kids Check-in team is free that morning."]


def test_a_full_week_says_so_and_a_past_week_says_it_passed(app, db):
    w = db.who[HOPE]
    for pid, slot, h in ((NURSERY, 1, "n043"), (NURSERY, 2, "n040"), (CHECKIN, 1, "n045"), (KEYS, 1, "n050"),
                         (VOCALS, 1, "n051"), (VOCALS, 2, "n052"), (LOTS, 1, "n060"), (LOTS, 2, "n062")):
        assign(db, NEXT_SUN, pid, slot, w[h], "yes")
    contact(db, "n040")["metadata"] = {"serving": {"check_on": "2026-01-10"}}
    contact(db, "n045")["metadata"] = {"serving": {"check_on": "2026-02-10"}}
    body = week(app, "sunny", "2026-11-29")
    assert body["counts"] == {"on": 8, "open": 0, "away": 0, "hours": body["counts"]["hours"]}
    assert [x["title"] for x in body["look"]] == ["Everything is filled for Sunday."]
    assert {c["label"] for c in body["departments"]} == {"Filled"}
    # The week we're in (Nov 15 to 21) had only Sunday the 15th: it has passed.
    now = week(app, "sunny", None)
    assert now["week"]["from"] == "2026-11-15" and now["week"]["this_week"] is True
    assert [x["title"] for x in now["look"]] == ["This week's services have passed."]
    assert all(s["past"] for c in now["departments"] for s in c["services"])
    assert all(r["find"] is None for c in now["departments"] for s in c["services"] for r in s["rows"])
    # A week with nothing on it.
    empty = week(app, "sunny", "2026-12-06")
    assert [x["title"] for x in empty["look"]] == ["Nothing is on the schedule this week."]
    assert {c["label"] for c in empty["departments"]} == {"Nothing this week"}


def test_filled_is_said_only_of_days_a_team_has_places(app, db):
    """No team has a place: the services are there, but nothing is said to
    be filled. Only ChurchSavvy's teams have places, all of them taken:
    Sunday is filled, and the outreach night (the Volunteers' alone) is
    never named."""
    places = list(db.t["serve_positions"])
    db.t["serve_positions"] = []
    body = week(app, "sunny")
    assert [x["title"] for x in body["look"]] == ["Nothing is on the schedule this week."]
    assert body["counts"]["on"] == body["counts"]["open"] == 0
    db.t["serve_positions"] = [p for p in places if p["group_id"] == BAND]
    assign(db, SUN, VOCALS, 2, db.who[HOPE]["n052"], "yes")
    body = week(app, "sunny")
    assert [x["title"] for x in body["look"]] == ["Everything is filled for Sunday."]
    assert body["counts"]["open"] == 0


def test_teams_with_no_department_still_show_and_a_closed_map_shows_every_team(app, db, monkeypatch):
    monkeypatch.setenv("CHURCH_MAP", "off")
    body = week(app, "sunny")
    assert [(c["name"], c["department_id"], c["group_id"]) for c in body["departments"]] == [
        ("Kids Check-in", None, KIDS), ("Worship Team", None, BAND), ("Parking Team", None, LOT)]
    assert body["counts"] == {"on": 6, "open": 7, "away": 2, "hours": 9.5}, "nothing lost, nothing twice"
    assert card(body, "Kids Check-in")["led_by"] == "Gemma Holt", "a team's card: its own leader"


def test_a_team_two_departments_name_is_on_the_first_card_only(app, db):
    youth = next(x for x in db.t["church_departments"] if x["business_id"] == HOPE and x["name"] == "Youth")
    db.t["church_department_units"].append({"id": "7d900000-0000-4000-8000-000000000001", "business_id": HOPE,
                                            "department_id": youth["id"], "kind": "serve_option", "group_id": None,
                                            "role_id": None, "board_id": None, "worship_ministry_id": None,
                                            "label": "Kids Check-in"})
    body = week(app, "sunny")
    assert [c["name"] for c in body["departments"]] == ["Worship", "Youth", "Parking Team"]
    assert body["counts"]["open"] == 7


# ─── 1. Who reads it ──────────────────────────────────────────────────

@pytest.mark.parametrize("handle,checks,change", [
    ("owner", True, ["volunteers", "churchsavvy"]),
    ("tessa", True, ["volunteers", "churchsavvy"]),       # an Admin (the Treasurer's seat)
    ("sunny", True, ["volunteers"]),                       # the Sunday & Serving lane: keeps the volunteers
    ("mila", False, ["churchsavvy"]),                      # Media & Communications: keeps ChurchSavvy's door
    ("kira", True, []),                                    # Kids & youth: does the background checks
])
def test_whoever_keeps_either_door_reads_every_department(app, handle, checks, change):
    body = week(app, handle)
    assert [c["name"] for c in body["departments"]] == ["Worship", "Kids", "Parking Team"]
    assert body["can"] == {"hours": True, "checks": checks, "change": change}
    assert body["counts"] == {"on": 6, "open": 7, "away": 2, "hours": 9.5}


def test_anyone_else_is_refused_and_a_stranger_finds_no_church(app, db):
    for handle in ("olive", "paige"):                     # office logins that keep neither door
        assert get(app, handle).status_code == 403
    stranger_seat(db, "n070", "member")
    stranger_seat(db, "n071", "viewer")
    for handle in ("n070", "n071"):
        r = get(app, handle)
        assert r.status_code == 403 and r.json()["detail"] == cw.NOT_READER
    app.who.update(id=c3.church(db, c3.GRACE)["owner_id"], email=c3.OWNER_EMAIL[c3.church(db, c3.GRACE)["owner_id"]])
    r = app.get("/church/week", params={"business_id": HOPE, "start": WEEK})
    assert r.status_code == 404
    app.who.update(id="9f000000-0000-4000-8000-000000000001", email="nobody@example.com")
    assert app.get("/church/week", params={"business_id": HOPE}).status_code == 404
    assert app.get("/church/week", params={"business_id": "not-a-church"}).status_code == 400


def test_a_business_that_isnt_a_church_or_is_on_churchsavvy_alone_has_no_week(app, db):
    row_ = next(b for b in db.t["businesses"] if b["id"] == HOPE)
    row_["type"] = "coaching"
    assert get(app, "owner").status_code == 404
    assert get(app, "owner", path="/status").json() == {"enabled": False, "hours": False, "checks": False}
    row_["type"] = "ministry"
    row_["settings"] = {**row_["settings"], "churchsavvy_only": True}
    assert get(app, "owner").status_code == 404


def test_every_read_is_this_churchs_and_every_value_is_quoted(app, db):
    db.reads.clear()
    body = week(app, "sunny")
    mine = [p for p in db.reads if p.startswith(("/worship_services", "/serve_", "/group_members", "/groups?",
                                                 "/contacts", "/space_leaders", "/church_departments"))]
    assert len(mine) > 15
    for p in mine:
        assert "+" not in p and " " not in p and "'" not in p, p
        assert f"business_id=eq.{HOPE}" in p, p
    assert [p for p in mine if p.startswith("/worship_services") and "%2B00%3A00" in p], "a moment, quoted"
    # Another church's rows that name New Hope's places and people change nothing.
    assert row(body, "Kids", SUN, "Nursery", 2)["who"] == "Dara Quinn"
    assert row(body, "Kids", SUN, "Nursery", 1)["state"] == "cant_serve_kids", "Grace's away date isn't hers here"
    # What a caller types never reaches an address.
    db.reads.clear()
    r = get(app, "sunny", f"{WEEK}&business_id=eq.{c3.GRACE}")
    assert r.status_code == 200 and r.json()["week"]["from"] == "2026-11-15"
    assert all(c3.GRACE not in p for p in db.reads)


# ─── 2. Paged ─────────────────────────────────────────────────────────

def test_a_team_of_more_than_a_thousand_is_read_whole(app, db):
    """The biggest read: a team's people (one read a team, paged by person).
    The last of 1,150 on the Parking Team is away on Tuesday."""
    for i in range(1150):
        db.t["group_members"].append({"group_id": LOT, "business_id": HOPE, "role": "member",
                                      "contact_id": f"7c900000-0000-4000-8000-{i:012d}"})
    db.t["serve_away"].append({"id": "7a000000-0000-4000-8000-000000000099", "business_id": HOPE,
                               "contact_id": "7c900000-0000-4000-8000-000000001149", "starts_on": "2026-11-24",
                               "ends_on": "2026-11-24", "note": "", "ask_id": None, "kind": None})
    body = week(app, "sunny")
    assert body["counts"]["away"] == 3
    assert any(p.startswith("/group_members") and "contact_id=gt." in p for p in db.reads), "paged"


# ─── 3. Checks and hours only for those who may read them ─────────────

def test_cant_serve_with_kids_yet_is_never_given_away(app, db):
    """For a login church_serving doesn't let read who's cleared (Media &
    Communications keeps ChurchSavvy's door), Lila reads as On, no line says
    otherwise, and the page is byte for byte the page it would be if her
    check were on record."""
    before = get(app, "mila").text
    body = json.loads(before)
    lila = row(body, "Kids", SUN, "Nursery", 1)
    assert (lila["state"], lila["state_words"]) == ("on", "On")
    assert "kids yet" not in before and "background check" not in before and "cant_serve" not in before
    assert body["counts"] == week(app, "sunny")["counts"]
    contact(db, "n041")["metadata"] = {"serving": {"check_on": "2026-03-01"}}
    assert get(app, "mila").text == before
    assert "cant_serve_kids" not in get(app, "sunny").text, "and with her check on record, nobody sees it"


def test_a_full_sunday_with_someone_unchecked_reads_full_to_whoever_cant_see_checks(app, db):
    w = db.who[HOPE]
    for pid, slot, h in ((NURSERY, 1, "n041"), (NURSERY, 2, "n040"), (CHECKIN, 1, "n045"), (KEYS, 1, "n050"),
                         (VOCALS, 1, "n051"), (VOCALS, 2, "n052"), (LOTS, 1, "n060"), (LOTS, 2, "n062")):
        assign(db, NEXT_SUN, pid, slot, w[h], "yes")
    contact(db, "n040")["metadata"] = {"serving": {"check_on": "2026-01-10"}}
    contact(db, "n045")["metadata"] = {"serving": {"check_on": "2026-02-10"}}
    assert [x["title"] for x in week(app, "mila", "2026-11-29")["look"]] == ["Everything is filled for Sunday."]
    assert [x["title"] for x in week(app, "sunny", "2026-11-29")["look"]] == [
        "Kids: Lila Penn can't serve with kids yet."]


def test_the_volunteers_keeper_reads_checks_by_the_background_checks_duty(app, db):
    """What grants it at the Sunday & Serving lane is the background_checks
    duty (church_serving's `record`): moved to someone else, that Manager
    reads Lila as On."""
    assert week(app, "sunny")["can"]["checks"] is True
    db.t["church_duty_holders"].append({"business_id": HOPE, "duty": "background_checks",
                                        "user_id": db.who[HOPE]["kira@"]})
    import church_duties
    church_duties._CACHE.clear()                         # the duties are kept a minute a replica
    body = week(app, "sunny")
    assert body["can"]["checks"] is False
    assert row(body, "Kids", SUN, "Nursery", 1)["state"] == "on"


def test_hours_follow_church_servings_rule(app, db, monkeypatch):
    """A Manager who keeps the volunteer teams (serve_teams moved to them)
    but works only Website & outreach: church_serving turns them away, so no
    hours at all, and the page doesn't change when anyone's hours do."""
    u = stranger_seat(db, "n072", "manager", areas=["website_outreach"])
    db.t["church_duty_holders"].append({"business_id": HOPE, "duty": "serve_teams", "user_id": u})
    before = get(app, "n072").text
    body = json.loads(before)
    assert body["can"] == {"hours": False, "checks": False, "change": []}
    assert body["counts"]["hours"] is None
    assert all(r["minutes"] is None and r["hours_words"] is None
               for c in body["departments"] for s in c["services"] for r in s["rows"])
    contact(db, "n061")["metadata"] = {}
    assert get(app, "n072").text == before
    # Serving switched off: nobody gets hours or checks here.
    monkeypatch.setenv("CHURCH_SERVING", "off")
    body = week(app, "sunny")
    assert body["can"] == {"hours": False, "checks": False, "change": ["volunteers"]}
    assert body["counts"]["hours"] is None and "kids yet" not in json.dumps(body)


def test_hours_and_checks_are_church_servings_own_numbers(app, db):
    """minutes_of and checks_of give the week's people exactly what the
    Serving page gives them (the whole church's read)."""
    biz = c3.church(db, HOPE)
    w = db.who[HOPE]
    people = [w[h] for h in ("n041", "n042", "n043", "n050", "n051", "n060", "n061")]
    page = church_serving.overview({"biz": biz, "checks": False, "record": False, "write": False, "role": "owner",
                                    "uid": ""})
    whole = {p["contact_id"]: p["minutes"] for p in page["people"]}
    assert church_serving.minutes_of(biz, people, NY) == {c: whole.get(c, 0) for c in people}
    assert sum(church_serving.minutes_of(biz, people, NY).values()) == 570
    every = {c["contact_id"]: c["status"] for c in church_serving.checks(
        biz, church_serving._settings(biz), NOW.astimezone(NY).date(), NY)}
    nexts = {w["n041"]: {"day": "2026-11-22"}, w["n043"]: {"day": "2026-11-22"}}
    got = church_serving.checks_of(biz, nexts, NOW.astimezone(NY).date(), nexts)
    assert {c: s["status"] for c, s in got.items()} == {w["n041"]: "blocked", w["n043"]: "ok"}
    assert {c: every[c] for c in got} == {c: s["status"] for c, s in got.items()}


# ─── 3. "Can't serve with kids yet", for whoever may see it ───────────

def _leader_date(db, handle, on):
    db.t["space_leaders"].append({"business_id": HOPE, "contact_id": db.who[HOPE][handle], "space": "kids",
                                  "background_check_on": on})


@pytest.mark.parametrize("set_up,status", [
    (lambda db: contact(db, "n041").update(metadata={"serving": {"check_on": "2020-03-01"}}), "overdue"),
    (lambda db: contact(db, "n041").update(metadata={"serving": {"check_on": "2024-12-01"}}), "due"),
    (lambda db: contact(db, "n041").update(metadata={"serving": {"check_on": "2026-03-01"}}), "ok"),
    (lambda db: _leader_date(db, "n041", "2026-05-01"), "ok"),             # the Kids leaders page's date
    (lambda db: contact(db, "n041").update(birthdate="2012-01-01"), "teen"),
    (lambda db: None, "blocked"),
], ids=["ran_out", "runs_out_soon", "recorded", "leader_approval", "under_18", "none_on_record"])
def test_only_no_check_on_record_reads_cant_serve_with_kids_yet(app, db, set_up, status):
    """For whoever may read who's cleared: a check that ran out, or runs out
    within the month, or one on record either way, is On; so is someone
    under 18. Only none on record is "Can't serve with kids yet"."""
    set_up(db)
    biz = c3.church(db, HOPE)
    lila = db.who[HOPE]["n041"]
    got = church_serving.checks_of(biz, [lila], NOW.astimezone(NY).date(), {lila: {"day": "2026-11-22"}})
    assert got[lila]["status"] == status
    body = week(app, "sunny")
    state = row(body, "Kids", SUN, "Nursery", 1)["state"]
    assert state == ("cant_serve_kids" if status == "blocked" else "on"), status
    assert ("Kids: Lila Penn can't serve with kids yet." in [x["title"] for x in body["look"]]) == (status == "blocked")


def test_the_latest_check_date_is_the_one_that_counts(app, db):
    """A leader approval that ran out and a newer check recorded on Serving:
    the newer one counts (check_on), so the check is good."""
    _leader_date(db, "n041", "2020-01-01")
    contact(db, "n041")["metadata"] = {"serving": {"check_on": "2026-03-01"}}
    assert church_serving.check_on([date(2020, 1, 1)], contact(db, "n041")) == date(2026, 3, 1)
    assert church_serving.check_on([date(2026, 4, 1), date(2020, 1, 1)], {}) == date(2026, 4, 1)
    biz = c3.church(db, HOPE)
    lila = db.who[HOPE]["n041"]
    got = church_serving.checks_of(biz, [lila], NOW.astimezone(NY).date(), {lila: {"day": "2026-11-22"}})
    assert (got[lila]["status"], got[lila]["on"]) == ("ok", "2026-03-01")


def test_a_past_service_never_says_cant_serve_with_kids_yet(app, db):
    """This week (Nov 15 to 21): Lila, unchecked, served the Nursery on
    Sunday the 15th (past) and is on it again at Saturday's event (to come).
    Only Saturday says it."""
    sat = "7f000000-0000-4000-8000-000000000021"
    db.t["worship_services"].append(_service(sat, date(2026, 11, 21), 10, 0, kind="event", title="Fall festival"))
    w = db.who[HOPE]
    assign(db, P3, NURSERY, 1, w["n041"], "yes")
    assign(db, sat, NURSERY, 1, w["n041"], "yes")
    body = week(app, "sunny", None)
    assert row(body, "Kids", P3, "Nursery", 1)["state"] == "on", "a past day is what happened"
    assert row(body, "Kids", sat, "Nursery", 1)["state"] == "cant_serve_kids"
    assert [x["title"] for x in body["look"] if x["kind"] == "cant_serve_kids"] == [
        "Kids: Lila Penn can't serve with kids yet."]


def test_a_reader_cleared_by_their_areas_sees_it_without_the_checks_duty(app, db):
    """Reading who's cleared is Kids & youth's and People & care's as well as
    the background checks duty's (church_serving: `checks`, not `record`). A
    Manager with no lane working Worship & media and Kids & youth keeps the
    Volunteers' door; with the checks duty moved to the volunteers keeper,
    it doesn't record checks, and still reads who's cleared."""
    u = stranger_seat(db, "n074", "manager", areas=["worship_media", "kids_youth"])
    db.t["church_duty_holders"].append({"business_id": HOPE, "duty": "background_checks",
                                        "user_id": db.who[HOPE]["sunny@"]})
    me = church_serving._access(HOPE, AuthedUser(id=u, email=contact(db, "n074")["email"], role="authenticated"))
    assert (me["checks"], me["record"]) == (True, False)
    body = week(app, "n074")
    assert body["can"]["checks"] is True
    assert row(body, "Kids", SUN, "Nursery", 1)["state"] == "cant_serve_kids"


def test_no_check_is_read_for_a_reader_who_cant_see_them(app, db):
    """Who can't serve with kids yet is worked out only for those who may
    see it: for anyone else not one check is read (the leaders' dates, the
    Kids & youth teams' places)."""
    checks = ("/space_leaders", "/church_area_places")
    db.reads.clear()
    week(app, "sunny")
    assert {t for t in checks if any(p.startswith(t) for p in db.reads)} == set(checks), "the reader who may"
    db.reads.clear()
    week(app, "mila")
    assert not [p for p in db.reads if p.startswith(checks)]


# ─── 3. Hours: church_serving's own, for the week's people ────────────

def test_hours_are_the_serving_pages_with_every_kind_of_credit(app, db):
    """A gathering Lila led and was marked at (90 minutes), Dara away on the
    one Sunday this year she said yes to (none), Hazel on two places at one
    Sunday (their shared time once) and the office's two hours."""
    w = db.who[HOPE]
    gid = "7d500000-0000-4000-8000-000000000001"
    db.t["groups"].append({"id": gid, "business_id": HOPE, "name": "Tuesday Moms", "kind": "group", "active": True})
    db.t["group_members"] += [{"group_id": gid, "business_id": HOPE, "contact_id": w["n041"], "role": "leader"},
                              {"group_id": gid, "business_id": HOPE, "contact_id": w["n042"], "role": "member"}]
    mid = "7d600000-0000-4000-8000-000000000001"
    db.t["group_meetings"].append({"id": mid, "business_id": HOPE, "group_id": gid, "met_on": "2026-10-06"})
    db.t["group_meeting_attendance"] += [{"business_id": HOPE, "meeting_id": mid, "contact_id": w[h]}
                                         for h in ("n041", "n042")]
    db.t["serve_away"].append({"id": "7a000000-0000-4000-8000-000000000077", "business_id": HOPE,
                               "contact_id": w["n042"], "starts_on": "2026-11-08", "ends_on": "2026-11-08",
                               "note": "", "ask_id": None, "kind": None})
    assign(db, P1, LOTS, 1, w["n061"], "yes")
    assign(db, P1, CHECKIN, 1, w["n061"], "yes")
    biz = c3.church(db, HOPE)
    people = [w[h] for h in ("n041", "n042", "n043", "n050", "n051", "n060", "n061")]
    page = church_serving.overview({"biz": biz, "checks": False, "record": False, "write": False, "role": "owner",
                                    "uid": ""})
    whole = {p["contact_id"]: p["minutes"] for p in page["people"]}
    got = church_serving.minutes_of(biz, people, NY)
    assert got == {c: whole.get(c, 0) for c in people}
    assert (got[w["n041"]], got[w["n042"]], got[w["n061"]]) == (180 + 90, 0, 90 + 120)
    body = week(app, "sunny")
    assert row(body, "Kids", SUN, "Nursery", 1)["minutes"] == 270
    assert row(body, "Kids", SUN, "Nursery", 2)["hours_words"] == "No hours yet", "away the day she said yes"
    assert body["counts"]["hours"] == round((270 + 0 + 0 + 90 + 0 + 90 + 210) / 60, 1)


def test_hours_read_only_this_years_yeses(app, db):
    """Three years of Sundays the week's people said yes to: the week reads
    their yeses at this year's services only (every assignments read names
    the services), and the hours are this year's."""
    w = db.who[HOPE]
    for i in range(156):
        sid = f"7f300000-0000-4000-8000-{i:012d}"
        db.t["worship_services"].append(_service(sid, date(2023, 1, 1) + timedelta(weeks=i)))
        for h in ("n041", "n050", "n060"):
            assign(db, sid, NURSERY, 1, w[h], "yes")
    db.reads.clear()
    body = week(app, "sunny")
    assert body["counts"]["hours"] == 9.5
    said = [p for p in db.reads if p.startswith("/serve_assignments")]
    assert said and all("service_id=in." in p for p in said), said


# ─── 4. Private ───────────────────────────────────────────────────────

def test_no_note_no_ask_no_reason_no_phone_no_email_and_only_the_churchs_own_names(app, db):
    db.reads.clear()
    for handle in ("owner", "sunny", "mila"):
        text = get(app, handle).text
        for secret in SECRETS:
            assert secret not in text
        assert "@" not in text
        body = json.loads(text)
        shown = {r["person"]["name"] for c in body["departments"] for s in c["services"] for r in s["rows"]
                 if r["person"]}
        leaders = {c["led_by"] for c in body["departments"] if c["led_by"]}
        on_teams = {c["name"] for c in db.t["contacts"] if any(
            m["contact_id"] == c["id"] and m["business_id"] == HOPE for m in db.t["group_members"])}
        assert shown <= on_teams and leaders <= on_teams | {"Kara Bell", "Wren Ellis"}
        assert "Quinn Abbott" not in text, "away, but on no team"
    assert not [p for p in db.reads if p.startswith("/church_away_asks")]
    for p in db.reads:
        if p.startswith(("/serve_away", "/serve_assignments")):
            assert not re.search(r"select=[^&]*\bnote\b", p), p
        if p.startswith("/contacts") and "id=in." in p:       # the names read (the sign-in's own match aside)
            assert not re.search(r"select=[^&]*\b(email|phone)\b", p), p


# ─── 5. Plain words ───────────────────────────────────────────────────

def _shown(body):
    """Every string the page shows."""
    out = [body["week"]["words"]]
    for x in body["look"]:
        out += [x["title"], *x["details"]]
    for c in body["departments"]:
        out += [c["name"], c["label"], c["led_by"] or ""] + [t["name"] for t in c["teams"]]
        for s in c["services"]:
            out += [s["words"], s["title"]]
            for r in s["rows"]:
                out += [r["team"], r["place"], r["who"], r["state_words"], r["hours_words"] or "", r["note"] or ""]
    return [w for w in out if w]


def test_every_word_the_page_shows_is_plain(app, db):
    for handle in ("sunny", "mila"):
        for words in _shown(week(app, handle)) + [cw.NOT_READER, cw.NOT_CHURCH, cw.BAD_WEEK, cw.UNREAD]:
            for rule in (UUID, SNAKE, TITLE_WORDS):
                assert not rule.search(words), (rule.pattern[:30], words)


def test_no_title_word_or_role_key_decides_anything_here():
    titles = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|directors?|executive|treasurers?|"
                        r"secretary|trustees?|reverend|apostles?|prophets?)\b", re.I)
    code = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", inspect.getsource(cw), flags=re.S))
    assert not ROLE_KEYS.search(code) and not titles.search(code), (ROLE_KEYS.search(code), titles.search(code))


# ─── 6. The switch ────────────────────────────────────────────────────

def test_the_switch(app, db, monkeypatch):
    monkeypatch.setenv("CHURCH_WEEK", "off")
    assert get(app, "owner").status_code == 404
    assert get(app, "owner", path="/status").json() == {"enabled": False, "hours": False, "checks": False}
    monkeypatch.setenv("CHURCH_WEEK", "maybe")
    assert get(app, "owner").status_code == 404, "a typo reads as off"
    # Unset is owner: the platform owner's own church (another church here).
    monkeypatch.delenv("CHURCH_WEEK")
    assert cw.mode() == "owner"
    assert get(app, "sunny").status_code == 404
    assert get(app, "sunny", path="/status").json()["enabled"] is False
    # New Hope as the platform owner's own church: open to its office.
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", c3.OWNER_EMAIL[c3.NH_OWNER])
    import member_asks
    monkeypatch.setattr(member_asks, "_OWNER_CACHE", {})
    assert get(app, "sunny").status_code == 200
    assert get(app, "sunny", path="/status").json() == {"enabled": True, "hours": True, "checks": True}
    assert get(app, "olive", path="/status").json()["enabled"] is False, "open, and still not hers"


def test_status_says_what_the_page_will(app, db):
    assert get(app, "sunny", path="/status").json() == {"enabled": True, "hours": True, "checks": True}
    assert get(app, "mila", path="/status").json() == {"enabled": True, "hours": True, "checks": False}
    assert get(app, "olive", path="/status").json() == {"enabled": False, "hours": False, "checks": False}
    app.who.update(id="9f000000-0000-4000-8000-000000000001", email="nobody@example.com")
    assert app.get("/church/week/status", params={"business_id": HOPE}).status_code == 404


# ─── 7. Bounded ───────────────────────────────────────────────────────

def test_one_week_a_call_and_a_bad_start_is_this_week(app):
    assert week(app, "sunny", "2026-11-25")["week"]["from"] == "2026-11-22", "any day: its week"
    assert week(app, "sunny", "2026-11-28")["week"]["to"] == "2026-11-28"
    for bad in ("", "soon", "2026-02-30", "2026-11-22T00:00"):
        assert week(app, "sunny", bad)["week"]["from"] == "2026-11-15", bad
    this = date(2026, 11, 15)
    far = week(app, "sunny", (this + timedelta(weeks=cw.WEEKS_AHEAD)).isoformat())["week"]
    assert far["next"] is None and far["prev"]
    back = week(app, "sunny", (this - timedelta(weeks=cw.WEEKS_BACK)).isoformat())["week"]
    assert back["prev"] is None and back["next"]
    for out in (this + timedelta(weeks=cw.WEEKS_AHEAD + 1), this - timedelta(weeks=cw.WEEKS_BACK + 1),
                date(1, 1, 1), date(9999, 12, 31)):
        r = get(app, "sunny", out.isoformat())
        assert r.status_code == 400 and r.json()["detail"] == cw.BAD_WEEK, out


def test_a_read_that_fails_is_a_503_never_an_empty_week(app, db):
    for table in ("/serve_assignments", "/group_members", "/serve_away", "/worship_services"):
        db.fail = {"get": table}
        r = get(app, "sunny")
        assert r.status_code == 503 and r.json()["detail"] == cw.UNREAD, table
    db.fail = {}


def test_it_is_mounted_before_the_public_catch_all():
    src = open(os.path.join(ROOT, "kmj_intake_automation.py"), encoding="utf-8").read()
    assert src.index("app.include_router(church_week_router)") < src.index("app.include_router(public_site_router)")
