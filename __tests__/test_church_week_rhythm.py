"""How your week goes (church_my_week.rhythm; docs/CHURCH_DUTIES.md step 7):
My week's `rhythm`, the duties a church login holds, by day.

Kevin, 2026-11-01: "a way for some sort of video or training or something
that can be given so they know how there week will go so they can see what
they suppose to do with no problem."

Pins:
  * every duty in the catalog has a door (a new duty with no page fails here)
  * the owner and the admins: every duty, `every_job`; a Manager its lane's,
    in the catalog's order; a login that works only the kids, Kids check-in
  * by day, Monday to Sunday, then Once a month ("monthly", "first Monday",
    never every Tuesday), then Any day ("as needed"); only days with
    something on them; a duty on two days is on both
  * today is the church's own day, not UTC's; the first Monday is the
    monthly report's day
  * `done` only where a read tells: the leaders note sent this week, last
    month's report sent, an announcement that reached someone since Monday;
    every other duty leaves it out
  * a `done` read that fails leaves that duty's `done` out, and the week is
    a 200; a duties read that fails leaves `rhythm` out, and the week stands
  * See as: the seen login's rhythm
  * a business that isn't a church gets no rhythm
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_duties as cd  # noqa: E402
import church_my_week as mw  # noqa: E402
import sb_clients  # noqa: E402
from test_church_follow_up import BIZ, OWNER  # noqa: E402
from test_church_areas import db  # noqa: E402,F401
from test_church_my_week import MARCUS_SEAT, client, week  # noqa: E402,F401

CHICAGO = ZoneInfo("America/Chicago")
# Monday, November 2, 2026, 9 AM in Chicago: the month's first Monday.
MONDAY_9AM = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """Each test reads its own duties (standing keeps a login's a minute),
    on Chicago's clock, on the first Monday of November."""
    cd._CACHE.clear()
    cd._FAILED.clear()
    import chief_assignments
    import church_leaders_note
    monkeypatch.setattr(chief_assignments, "_tz_for", lambda biz: CHICAGO)
    monkeypatch.setattr(church_leaders_note, "_zone", lambda biz: CHICAGO)
    monkeypatch.setattr(mw, "_now", lambda: MONDAY_9AM)
    yield
    cd._CACHE.clear()
    cd._FAILED.clear()


def _rhythm(client, as_user=None):
    r = client.get(f"/church/my-week?business_id={BIZ}" + (f"&as_user={as_user}" if as_user else ""))
    assert r.status_code == 200, r.text
    return r.json().get("rhythm")


def _keys(r):
    """Each duty once, in the order the days give them."""
    return list(dict.fromkeys(i["key"] for d in r["days"] for i in d["items"]))


def _day(r, key):
    return next((d for d in r["days"] if d["key"] == key), None)


def _item(r, key):
    return next(i for d in r["days"] for i in d["items"] if i["key"] == key)


def _as_manager(client, week, lane=None, areas=None):
    seat = next(s for s in week.t["business_users"] if s["user_id"] == MARCUS_SEAT)
    seat.update(lane=lane, areas=areas)
    client.who.update(role="manager", id=MARCUS_SEAT, email="marcus@example.com")


# ─── Doors ────────────────────────────────────────────────────────────

def test_every_duty_in_the_catalog_has_a_door():
    missing = [k for k in cd.CATALOG if k not in mw.DOOR]
    assert not missing, f"a duty with no page to open: {missing}"
    for k in cd.CATALOG:
        door = mw.DOOR[k]
        assert door["area"] in ("operate", "grow", "build") and door["id"], k
        assert door["label"].startswith("Open "), k


def test_the_doors_open_the_pages_the_jobs_are_done_on():
    ids = {k: mw.DOOR[k]["id"] for k in cd.CATALOG}
    assert ids["weekly_text"] == "sms" and ids["leaders_note"] == "leaders-note" and ids["meetings"] == "board"
    assert ids["rooms"] == "spaces" and ids["chat_rules"] == "messaging" and ids["website"] == "my-site"
    assert ids["monthly_report"] == "monthly-report" and ids["oversee_lanes"] == "team"
    assert mw.DOOR["posts"] == {"area": "grow", "id": "marketing", "label": "Open the marketing desk"}
    assert mw.DOOR["clips"]["area"] == "grow" and ids["clips"] == "video-clips"
    assert {ids[k] for k in ("deposit", "books", "pay", "store")} == {"bookkeeping", "checks", "offerings-manager"}


# ─── Who gets what ────────────────────────────────────────────────────

def test_the_owner_does_every_job_by_day(client):
    r = _rhythm(client)
    assert r["every_job"] is True and r["count"] == len(cd.CATALOG)
    assert set(_keys(r)) == set(cd.CATALOG)
    order = [d["key"] for d in r["days"]]
    assert order == [g for g in mw.GROUP_ORDER if g in order], "Monday to Sunday, then the month, then any day"
    assert order[-2:] == ["month", "any"] and [d["label"] for d in r["days"]][-2:] == ["Once a month", "Any day"]
    # Within a day, the catalog's order.
    mon = [i["key"] for i in _day(r, "Mon")["items"]]
    assert mon == [k for k in cd.CATALOG if k in mon]
    assert mon == ["leaders_note", "care_board", "clips", "oversee_lanes", "deposit"]
    # A duty on two days is on both; said as the catalog says it.
    assert "stream" in [i["key"] for i in _day(r, "Sat")["items"]] and "stream" in [i["key"] for i in _day(r, "Sun")["items"]]
    assert _item(r, "deposit")["when"] == "Sundays and Mondays" and _item(r, "deposit")["days"] == ["Sun", "Mon"]
    # Once a month: monthly, the first Monday, never every Tuesday.
    month = [i["key"] for i in _day(r, "month")["items"]]
    assert month == ["meetings", "monthly_report", "books"]
    assert "meetings" not in [i["key"] for i in _day(r, "Tue")["items"]]
    assert _item(r, "meetings")["when"] == "Once a month, on a Tuesday"
    assert _item(r, "monthly_report")["when"] == "The first Monday of the month"
    assert [i["key"] for i in _day(r, "any")["items"]] == ["chat_rules", "leaders_list", "website", "churchsavvy_team", "store"]
    one = _item(r, "rooms")
    assert one["label"] == "Rooms" and one["does"] == cd.CATALOG["rooms"]["does"] and one["door"]["id"] == "spaces"


def test_an_admin_does_every_job_too(client):
    client.who.update(role="admin", id="u-admin", email="office@lovecity.org")
    r = _rhythm(client)
    assert r["every_job"] is True and set(_keys(r)) == set(cd.CATALOG)


def test_a_manager_gets_its_lanes_duties_and_nothing_else(client, week):
    _as_manager(client, week, lane="media_comms")
    r = _rhythm(client)
    assert r["every_job"] is False
    assert sorted(_keys(r)) == sorted(cd.STARTER["media_comms"]) and r["count"] == len(cd.STARTER["media_comms"])
    assert [d["key"] for d in r["days"]] == ["Mon", "Wed", "Thu", "Sat", "Sun", "any"], "only the days with a job"
    assert [i["key"] for i in _day(r, "Thu")["items"]] == ["events", "posts"]
    assert not any(cd.CATALOG[k]["money"] for k in _keys(r))


def test_a_login_that_works_only_the_kids_does_kids_check_in_on_sunday(client, week):
    _as_manager(client, week)                    # no lane, its areas guessed: Kids & youth
    r = _rhythm(client)
    assert _keys(r) == ["kids"] and [d["key"] for d in r["days"]] == ["Sun"]


def test_a_viewer_holds_no_duties(client):
    client.who.update(role="viewer", id="u-view", email="intern@lovecity.org")
    r = _rhythm(client)
    assert r["count"] == 0 and r["days"] == [] and r["every_job"] is False


def test_seeing_as_a_login_is_that_logins_rhythm(client, week):
    seat = next(s for s in week.t["business_users"] if s["user_id"] == MARCUS_SEAT)
    seat.update(lane="people_care")
    r = _rhythm(client, as_user=MARCUS_SEAT)
    assert r["every_job"] is False and sorted(_keys(r)) == sorted(cd.STARTER["people_care"])


# ─── Today ────────────────────────────────────────────────────────────

def test_today_is_the_churchs_own_day(client, monkeypatch):
    # 9 PM Sunday in Chicago is already Monday in UTC.
    monkeypatch.setattr(mw, "_now", lambda: datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc))
    r = _rhythm(client)
    assert r["today"] == {"key": "Sun", "label": "Sunday", "date": "2026-11-01"}
    assert _day(r, "Sun")["today"] is True and _day(r, "Mon")["today"] is False
    assert _item(r, "kids")["today"] is True and _item(r, "leaders_note")["today"] is False
    assert _item(r, "monthly_report")["today"] is False, "the first Monday is tomorrow"


def test_the_first_monday_is_the_monthly_reports_day(client):
    r = _rhythm(client)                          # Monday, November 2: the month's first Monday
    assert r["today"]["key"] == "Mon" and _day(r, "Mon")["today"] is True
    assert _item(r, "monthly_report")["today"] is True and _day(r, "month")["today"] is True
    assert _item(r, "meetings")["today"] is False, "a Tuesday once a month: which one isn't said"
    assert _item(r, "chat_rules")["today"] is False


def test_a_monday_that_isnt_the_first_isnt_the_reports(client, monkeypatch):
    monkeypatch.setattr(mw, "_now", lambda: datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc))
    r = _rhythm(client)
    assert r["today"]["key"] == "Mon" and _item(r, "monthly_report")["today"] is False
    assert _day(r, "month")["today"] is False and _item(r, "clips")["today"] is True


# ─── Done ─────────────────────────────────────────────────────────────

def _sent(week, *, leaders_week=None, report=None, texts=()):
    biz = week.t["businesses"][0]
    biz.setdefault("settings", {})
    if leaders_week:
        biz["settings"]["church_leaders_note"] = {"id": "n1", "week": leaders_week, "state": "sent",
                                                  "sent_at": "2026-11-02T14:00:00+00:00"}
    week.t["church_monthly_reports"] = [{"business_id": BIZ, "month": report, "send_id": "s1", "send_state": "sent"}] if report else []
    week.t["events"] = [{"business_id": BIZ, "event_type": "sms_broadcast", "created_at": at, "data": {"sent": n}}
                        for at, n in texts]


def test_done_where_a_read_tells_and_nowhere_else(client, week):
    _sent(week, leaders_week="2026-11-02", report="2026-10", texts=[("2026-11-02T14:30:00+00:00", 41)])
    r = _rhythm(client)
    assert _item(r, "leaders_note")["done"] is True
    assert _item(r, "monthly_report")["done"] is True
    assert _item(r, "weekly_text")["done"] is True
    told = {i["key"] for d in r["days"] for i in d["items"] if "done" in i}
    assert told == {"leaders_note", "monthly_report", "weekly_text"}, "never a guess for the rest"


def test_not_done_this_week_is_to_do(client, week):
    # Last week's note, September's report, an announcement before Monday and
    # one this week that reached no one.
    _sent(week, leaders_week="2026-10-26", report="2026-09",
          texts=[("2026-11-01T20:00:00+00:00", 30), ("2026-11-02T14:30:00+00:00", 0)])
    r = _rhythm(client)
    assert _item(r, "leaders_note")["done"] is False
    assert _item(r, "monthly_report")["done"] is False
    assert _item(r, "weekly_text")["done"] is False


def test_a_manager_without_the_duty_reads_nothing_for_it(client, week, monkeypatch):
    _as_manager(client, week, lane="media_comms")
    seen = []
    real = week.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (seen.append(path), real(path, **kw))[1])
    r = _rhythm(client)
    assert "leaders_note" not in _keys(r)
    assert not any(p.lstrip("/").startswith(("church_monthly_reports", "events?")) for p in seen)


@pytest.mark.parametrize("table", ["events", "church_monthly_reports"])
def test_a_done_read_that_fails_leaves_done_out_and_the_week_stands(client, week, monkeypatch, table):
    _sent(week, leaders_week="2026-11-02", report="2026-10", texts=[("2026-11-02T14:30:00+00:00", 41)])
    real = week.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith(table + "?") else real(path, **kw))
    r = _rhythm(client)
    key = {"events": "weekly_text", "church_monthly_reports": "monthly_report"}[table]
    assert "done" not in _item(r, key), "unread is never To do"
    assert _item(r, "leaders_note")["done"] is True, "the other reads still answer"


def test_the_leaders_notes_clock_failing_leaves_its_done_out(client, week, monkeypatch):
    import church_leaders_note
    from fastapi import HTTPException

    def no_clock(biz):
        raise HTTPException(503, "The church's clock couldn't be read just now. Try again.")
    monkeypatch.setattr(church_leaders_note, "_zone", no_clock)
    _sent(week, leaders_week="2026-11-02")
    assert "done" not in _item(_rhythm(client), "leaders_note")


def test_a_duties_read_that_fails_leaves_the_rhythm_out_and_the_week_stands(client, week, monkeypatch):
    _as_manager(client, week, lane="media_comms")
    real = week.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("church_duty_holders") else real(path, **kw))
    r = client.get(f"/church/my-week?business_id={BIZ}")
    assert r.status_code == 200, r.text
    assert "rhythm" not in r.json() and "areas" in r.json()


# ─── Not a church ─────────────────────────────────────────────────────

def test_a_business_that_isnt_a_church_gets_no_rhythm(client, week):
    salon = {**week.t["businesses"][0], "type": "salon"}
    assert mw.rhythm(salon, OWNER, "owner") is None
    church = week.t["businesses"][0]
    assert mw.rhythm(church, OWNER, "owner")["every_job"] is True
    week.t["businesses"][0]["type"] = "salon"
    assert client.get(f"/church/my-week?business_id={BIZ}").status_code == 404
