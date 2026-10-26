# __tests__/test_worship_announce_import.py
#
# "Bring in from the calendar" (ChurchSavvy round 5, canvas board 18; idea A4;
# worship_announce_import.py). Pins:
#   * a calendar file's events from today on: title, the day and its time on
#     the church's clock, where, a few words only when short; a weekly series
#     once (its next date, keyed with the date); cancelled ones left out; a
#     file that isn't a calendar refused
#   * the church's own Solutionist events: public, dated ones only
#   * over HTTP (the plan's part): the link must open before it's kept, and is
#     never shown whole; the list marks what's already on the board; bringing
#     in puts them on in the big-date design, two weeks ahead until the day,
#     room and lobby, from the calendar, once; forgetting the link; a link
#     that stops opening says why without losing the rest

import pathlib
import sys
from datetime import date
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import outside_calendar as oc
import test_worship_show_router as base
import worship_announce_import as wi
from test_worship_show_router import BIZ, api  # noqa: E402,F401  (api is the fixture)

NY = ZoneInfo("America/New_York")
ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:community-day@lc
DTSTART;TZID=America/New_York:20261107T110000
DTEND;TZID=America/New_York:20261107T150000
SUMMARY:Community Day
LOCATION:The church lawn
DESCRIPTION:Food, games and free school supplies.
END:VEVENT
BEGIN:VEVENT
UID:bible-study@lc
DTSTART;TZID=America/New_York:20261104T190000
DTEND;TZID=America/New_York:20261104T203000
RRULE:FREQ=WEEKLY;BYDAY=WE
SUMMARY:Bible study
DESCRIPTION:""" + b"A long description that goes on " * 10 + b"""
END:VEVENT
BEGIN:VEVENT
UID:gone@lc
DTSTART;VALUE=DATE:20261110
SUMMARY:Cancelled thing
STATUS:CANCELLED
END:VEVENT
BEGIN:VEVENT
UID:old@lc
DTSTART;VALUE=DATE:20261020
SUMMARY:Already over
END:VEVENT
BEGIN:VEVENT
UID:thanks@lc
DTSTART;VALUE=DATE:20261125
SUMMARY:Thanksgiving service
END:VEVENT
END:VCALENDAR
"""
LINK = "https://calendar.google.com/calendar/ical/lovecity%40group.calendar.google.com/private-0123456789abcdef/basic.ics"


def test_a_calendar_files_events():
    got = wi.events_from_ics(ICS, NY, date(2026, 11, 1))
    assert [(e["title"], e["event_on"], e["when"]) for e in got] == [
        ("Bible study", "2026-11-04", "7 PM"), ("Community Day", "2026-11-07", "11 AM"), ("Thanksgiving service", "2026-11-25", "")]
    day = {e["title"]: e for e in got}
    assert day["Community Day"]["where"] == "The church lawn" and day["Community Day"]["body"] == "Food, games and free school supplies."
    assert day["Bible study"]["body"] == ""                                  # too long to show: left for the office
    assert day["Bible study"]["key"].endswith(":2026-11-04")                 # next week's is its own
    nxt = {e["title"]: e for e in wi.events_from_ics(ICS, NY, date(2026, 11, 5))}
    assert nxt["Bible study"]["event_on"] == "2026-11-11" and nxt["Bible study"]["key"] != day["Bible study"]["key"]
    with pytest.raises(oc.FeedError):
        wi.events_from_ics(b"<html>not a calendar</html>", NY, date(2026, 11, 1))


@pytest.fixture
def church(api, monkeypatch):
    db, as_, client = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    for t in ("worship_announcements", "worship_calendar", "module_entries"):
        db.t[t] = []
    db.KEYS = {**db.KEYS, "worship_calendar": "business_id"}
    import worship_announce_router as war
    client.app.include_router(war.router)
    client.app.include_router(wi.router)
    monkeypatch.setattr(war, "church_zone", lambda biz: NY)
    monkeypatch.setattr(war, "church_today", lambda biz: date(2026, 11, 1))
    fetched = {"ics": ICS, "urls": []}

    def fetch_feed(url):
        fetched["urls"].append(url)
        if isinstance(fetched["ics"], Exception):
            raise fetched["ics"]
        return fetched["ics"]

    monkeypatch.setattr(oc, "fetch_feed", fetch_feed)
    import events_rsvp_router as er
    monkeypatch.setattr(er, "roster_modules_for", lambda biz: [])
    deleted = []

    def delete(path):
        table, _f = base.FakeDb._split(path)
        keep = [r for r in db.t[table] if not base.FakeDb._match(r, _f)]
        deleted.append(len(db.t[table]) - len(keep))
        db.t[table] = keep
        return True

    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)
    return db, as_, fetched


def test_the_link_opens_before_its_kept_and_is_never_shown_whole(church):
    db, as_, fetched = church
    r = as_("owner").put("/worship/announcements/import/calendar", json={"business_id": BIZ, "url": LINK.replace("https://", "webcal://")})
    assert r.status_code == 200, r.text
    assert r.json()["found"] == 3 and "private-0123456789abcdef" not in r.text and r.json()["shown_as"].startswith("calendar.google.com")
    assert db.t["worship_calendar"][0]["url"] == LINK and db.t["worship_calendar"][0]["provider"] == "google"
    assert as_("member").put("/worship/announcements/import/calendar", json={"business_id": BIZ, "url": LINK}).status_code == 403
    assert as_("owner").put("/worship/announcements/import/calendar", json={"business_id": BIZ, "url": "http://calendar.example/a.ics"}).status_code == 400
    fetched["ics"] = oc.FeedError(oc.MSG_UNREADABLE)
    bad = as_("owner").put("/worship/announcements/import/calendar", json={"business_id": BIZ, "url": "https://other.example/x.ics"})
    assert bad.status_code == 400 and db.t["worship_calendar"][0]["url"] == LINK      # the good one is kept
    # A link that stops opening says why, and the list still answers.
    page = as_("owner").get(f"/worship/announcements/import?business_id={BIZ}").json()
    assert page["calendar"]["connected"] and page["calendar"]["error"] and page["items"] == [] and LINK not in str(page)


def test_bringing_events_in(church):
    db, as_, _ = church
    as_("owner").put("/worship/announcements/import/calendar", json={"business_id": BIZ, "url": LINK})
    page = as_("owner").get(f"/worship/announcements/import?business_id={BIZ}").json()
    assert [i["title"] for i in page["items"]] == ["Bible study", "Community Day", "Thanksgiving service"]
    assert not any(i["already"] for i in page["items"]) and page["events"] is False
    keys = [i["key"] for i in page["items"] if i["title"] in ("Community Day", "Thanksgiving service")]
    r = as_("owner").post("/worship/announcements/import", json={"business_id": BIZ, "keys": keys})
    assert r.status_code == 200 and r.json()["brought"] == 2
    day = {a["title"]: a for a in db.t["worship_announcements"]}
    cd = day["Community Day"]
    assert (cd["design"], cd["event_on"], cd["show_from"], cd["show_until"]) == ("date", "2026-11-07", "2026-11-01", "2026-11-07")
    assert (cd["when_text"], cd["where_text"], cd["status"], cd["source"]) == ("11 AM", "The church lawn", "on", "calendar")
    assert cd["shows"] == {"room": True, "lobby": True, "online": False, "phones": False}
    assert day["Thanksgiving service"]["show_from"] == "2026-11-11"            # two weeks before
    again = as_("owner").get(f"/worship/announcements/import?business_id={BIZ}").json()
    assert [i["already"] for i in again["items"]] == [False, True, True]
    assert as_("owner").post("/worship/announcements/import", json={"business_id": BIZ, "keys": keys}).json()["brought"] == 0
    assert as_("owner").post("/worship/announcements/import", json={"business_id": BIZ, "keys": []}).status_code == 400
    assert as_("member").post("/worship/announcements/import", json={"business_id": BIZ, "keys": keys}).status_code == 403
    # Forget the link: nothing is fetched, the board keeps what came in.
    assert as_("owner").delete(f"/worship/announcements/import/calendar?business_id={BIZ}").status_code == 200
    gone = as_("owner").get(f"/worship/announcements/import?business_id={BIZ}").json()
    assert gone["calendar"]["connected"] is False and gone["items"] == [] and len(db.t["worship_announcements"]) == 2


def test_the_churchs_own_events(church, monkeypatch):
    db, as_, _ = church
    import events_rsvp_router as er
    monkeypatch.setattr(er, "roster_modules_for", lambda biz: [{"id": "mod-1", "name": "Events", "archetype_params": {}}])
    db.t["module_entries"] = [
        {"id": "e-1", "module_id": "mod-1", "business_id": BIZ, "status": "active",
         "data": {"title": "Youth lock-in", "date": "2026-11-13", "location": "The youth room"}},
        {"id": "e-2", "module_id": "mod-1", "business_id": BIZ, "status": "active",
         "data": {"title": "Elders' retreat", "date": "2026-11-14", "_visibility": "private"}},
        {"id": "e-3", "module_id": "mod-1", "business_id": BIZ, "status": "active", "data": {"title": "Someday"}},
    ]
    page = as_("owner").get(f"/worship/announcements/import?business_id={BIZ}").json()
    assert page["events"] is True and [(i["title"], i["source"], i["where"]) for i in page["items"]] == [("Youth lock-in", "events", "The youth room")]
    r = as_("owner").post("/worship/announcements/import", json={"business_id": BIZ, "keys": ["ev:e-1"]})
    assert r.json()["brought"] == 1 and db.t["worship_announcements"][-1]["source_ref"] == "ev:e-1"


def test_review_fixes(church, monkeypatch):
    """PR review: the link's write and read never log the row; a long title is cut, not
    dropped; once is the database's too (a lost race counts as already there); a link that
    won't open says why on Bring in."""
    db, as_, fetched = church
    import sb_clients
    calls = []
    real_post, real_get = sb_clients.sb_post_as_service, sb_clients.sb_get_as_service

    def post(path, body, prefer=None, **kw):
        calls.append(("POST", path.split("?")[0], kw.get("redact")))
        return real_post(path, body, prefer=prefer, **kw)

    def get(path, **kw):
        calls.append(("GET", path.split("?")[0], kw.get("redact")))
        return real_get(path, **kw)

    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    long_title = ("The Annual Love City Community Thanksgiving Dinner and Family Celebration Night "
                  "for Everyone in the Neighborhood")
    fetched["ics"] = ICS.replace(b"SUMMARY:Thanksgiving service", b"SUMMARY:" + long_title.encode())
    as_("owner").put("/worship/announcements/import/calendar", json={"business_id": BIZ, "url": LINK})
    assert ("POST", "/worship_calendar", True) in calls and all(r for m, p, r in calls if p == "/worship_calendar")
    page = as_("owner").get(f"/worship/announcements/import?business_id={BIZ}").json()
    long = [i for i in page["items"] if i["title"].startswith("The Annual")][0]
    assert len(long["title"]) <= 80 and long["title"].endswith("…") and " " not in long["title"][-2:]
    # Someone else brought Community Day in a moment ago: the database refuses the second, and it counts as there.
    cd = [i for i in page["items"] if i["title"] == "Community Day"][0]
    db.t["worship_announcements"].append({"id": "x1", "business_id": BIZ, "source": "calendar", "source_ref": cd["key"],
                                          "archived_at": None, "title": "Community Day"})

    def race_post(path, body, prefer=None, **kw):
        if path.startswith("/worship_announcements") and isinstance(body, dict) and body.get("source_ref") == cd["key"]:
            return None
        return real_post(path, body, prefer=prefer, **kw)

    monkeypatch.setattr(sb_clients, "sb_post_as_service", race_post)
    import worship_announce_import as wimp
    monkeypatch.setattr(wimp, "_items", lambda biz: {**page, "items": [{**i, "already": False} for i in page["items"]]})
    r = as_("owner").post("/worship/announcements/import", json={"business_id": BIZ, "keys": [cd["key"], long["key"]]})
    assert r.status_code == 200 and r.json() == {"ok": True, "brought": 1, "skipped": 1}
    monkeypatch.undo()


def test_bring_in_says_why_when_the_link_wont_open(church):
    db, as_, fetched = church
    as_("owner").put("/worship/announcements/import/calendar", json={"business_id": BIZ, "url": LINK})
    key = as_("owner").get(f"/worship/announcements/import?business_id={BIZ}").json()["items"][0]["key"]
    fetched["ics"] = oc.FeedError(oc.MSG_UNREADABLE)
    r = as_("owner").post("/worship/announcements/import", json={"business_id": BIZ, "keys": [key]})
    assert r.status_code == 502 and "didn't open just now" in r.json()["detail"]


def test_mounted_before_the_public_site_catch_all():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert src.index("include_router(worship_announce_import_router)") < src.index("include_router(public_site_router)")
