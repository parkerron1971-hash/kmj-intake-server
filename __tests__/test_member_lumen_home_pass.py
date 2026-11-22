# __tests__/test_member_lumen_home_pass.py
#
# Kevin's Home plan (2026-11-21, "yes to everything"), part two: Sunday's
# card, the four doors' live words and the greeting's facts.
#   - check-in's closed state carries its settings (read in card() already),
#     so the service is named as the office named it ("Love City
#     Experience"), not after the church, all week;
#   - the service is This week's first card as a pass: a chip on the picture
#     (Today, Tomorrow, the weekday), I'll be there (the calendar entry's
#     own RSVP), Watch live (the live page) only where the church streams
#     (it has gone live in the app: one read, kept ten minutes; or it's live
#     now), Calendar (Watch's own .ics) only where the office set the
#     service's day and time; on the day, check-in as before, Watch live
#     only while live, no Calendar. No new route, no write;
#   - the doors: Prayer "N new" else "Ask or pray"; Events "N coming up"
#     (the calendar's upcoming occasions and the service when it isn't on
#     the calendar; a failed read says no number); Serve the member's next
#     time, else what waits, else "N teams" they can see; Give while the
#     church takes gifts, as the fourth door (with Kids already the fourth,
#     Give stays in the tab bar);
#   - the greeting names the service's time tomorrow, and, with no
#     gathering this week to lead with, the newest message and the next
#     event a week to three weeks out.

import pathlib
import re
import sys
from datetime import date, datetime, time, timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_checkin as cc
import member_portal_lumen as mlp
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_home import NY, TODAY, _client, _occ, _sunday_after, church  # noqa: F401
from test_member_lumen_home5 import _doors

SETTINGS = {"enabled": True, "weekday": 6, "start_time": "11:00", "timezone": "America/New_York",
            "title": "Love City Experience", "saved": True, "opens_before_min": 30, "closes_after_min": 180}


def _pass(html):
    m = re.search(r'<article class="lm-wk lm-pass">.*?</article>', html, re.S)
    return m.group(0) if m else ""


@pytest.fixture
def lovecity(church, fake, monkeypatch):  # noqa: F811
    """Love City's shape on a Saturday evening: the service set in check-in
    (Sunday 11:00, "Love City Experience"), not on the calendar; one event
    two weeks out; the church has gone live in the app before."""
    church["occ"] = [_occ("Oh Give Thanks", TODAY + timedelta(days=14), eid="00000000-0000-4000-8000-0000000003b1")]
    church["checkin"]["settings"] = dict(SETTINGS)
    church["checkin"]["w"]["start"] = datetime.combine(church["checkin"]["w"]["day"], time(11, 0), tzinfo=NY)
    fake.t["live_sessions"] = [{"id": "00000000-0000-4000-8000-0000000007f1", "business_id": tct.BIZ,
                                "status": "ended", "title": "Sunday"}]
    monkeypatch.setattr(mlp, "_STREAMS", None)
    monkeypatch.setattr(mlp, "_CLASS", None)
    return church


# ─── check-in's closed state ─────────────────────────────────────────


def test_the_closed_card_carries_its_settings(monkeypatch):
    st = dict(SETTINGS)
    monkeypatch.setattr(cc, "settings", lambda b: dict(st))
    sat = datetime(2026, 11, 21, 18, 45, tzinfo=NY)
    got = cc.card({"id": tct.BIZ}, {"id": tct.ANA}, sat)
    assert got["state"] == "closed" and got["settings"]["title"] == "Love City Experience"
    assert got["w"]["day"] == date(2026, 11, 22)
    monkeypatch.setattr(cc, "settings", lambda b: dict(st, enabled=False))
    assert cc.card({"id": tct.BIZ}, {"id": tct.ANA}, sat) == {"state": "off"}


def test_the_service_is_named_as_the_office_named_it(lovecity, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    card = _pass(html)
    assert ">Love City Experience</a></h3>" in card and ">Grace Fellowship</a></h3>" not in card
    assert "11:00 AM" in card


# ─── the pass ────────────────────────────────────────────────────────


def test_love_citys_pass(lovecity, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    card = _pass(html)
    n = (lovecity["checkin"]["w"]["day"] - TODAY).days
    chip = "Tomorrow" if n == 1 else "Sunday"
    assert f'<span class="lm-chip" aria-hidden="true">{chip}</span>' in card
    assert "In person, or watch live in the app" in card
    assert '<a class="lm-wkb o" href="/my/live">' in card and "Watch live</a>" in card
    assert ('<a class="lm-wkb o" href="/my/sermons/live.ics" download aria-label="Add to calendar">' in card
            and "Calendar</a>" in card)
    # Not on the calendar: no entry to answer, so no I'll be there.
    assert 'action="/my/rsvp"' not in card
    assert card.index("Watch live") < card.index("Calendar</a>")


def test_ill_be_there_is_the_calendar_entrys_rsvp(lovecity, fake, monkeypatch):  # noqa: F811
    sun = lovecity["checkin"]["w"]["day"]
    lovecity["occ"].insert(0, _occ("Love City Experience", sun, n=40, tm="11:00"))
    card = _pass(_client(fake, monkeypatch).get("/my").text)
    assert 'action="/my/rsvp"' in card and "I&#x27;ll be there</button>" in card
    assert 'name="action" value="coming"' in card and "<b>40</b> going" in card
    assert card.index("I&#x27;ll be there") < card.index("Watch live")


def test_watch_live_only_where_the_church_streams(lovecity, fake, monkeypatch):  # noqa: F811
    fake.t["live_sessions"] = []
    card = _pass(_client(fake, monkeypatch).get("/my").text)
    assert "Watch live" not in card and "watch live in the app" not in card
    assert "Calendar</a>" in card


def test_whether_the_church_streams_is_read_once_and_kept(lovecity, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.get("/my")
    fake.gets.clear()
    c.get("/my")
    assert not any(g.startswith("/live_sessions?business_id") and "select=id&limit=1" in g for g in fake.gets)


def test_a_failed_streams_read_leaves_watch_live_out_and_isnt_kept(lovecity, fake, monkeypatch):  # noqa: F811
    fake.down.add("live_sessions")
    c = _client(fake, monkeypatch)
    assert "Watch live" not in _pass(c.get("/my").text)
    fake.down.discard("live_sessions")
    assert "Watch live" in _pass(c.get("/my").text)


def test_live_now_streams_without_the_read(lovecity, fake, monkeypatch):  # noqa: F811
    fake.t["live_sessions"] = []
    lovecity["live"] = {"id": "l1", "title": "Love City Experience", "status": "live"}
    assert "Watch live" in _pass(_client(fake, monkeypatch).get("/my").text)


def test_no_calendar_without_the_offices_service_time(lovecity, fake, monkeypatch):  # noqa: F811
    lovecity["checkin"]["settings"]["saved"] = False                         # check-in's defaults: not a real time
    card = _pass(_client(fake, monkeypatch).get("/my").text)
    assert "live.ics" not in card and "Watch live" in card


def test_on_the_day_check_in_leads_and_calendar_goes(lovecity, fake, monkeypatch):  # noqa: F811
    sun = _sunday_after(TODAY - timedelta(days=1))
    lovecity["now"] = datetime.combine(sun, time(10, 40), tzinfo=NY)
    w = {"day": sun, "start": datetime.combine(sun, time(11, 0), tzinfo=NY), "open": True, "weekday": "Sunday"}
    lovecity["checkin"] = {"state": "open", "w": w, "settings": dict(SETTINGS),
                           "occasion": {"id": "occ", "title": "Love City Experience"},
                           "family": [{"id": tct.ANA, "name": "Ana Rivera", "me": True}], "marks": {}}
    card = _pass(_client(fake, monkeypatch).get("/my").text)
    assert '<span class="lm-chip" aria-hidden="true">Today</span>' in card
    assert 'action="/my/here"' in card and "I&#x27;m here" in card
    assert "live.ics" not in card and "Watch live" not in card               # not live yet: check-in carries it
    lovecity["live"] = {"id": "l1", "title": "Love City Experience", "status": "live"}
    assert "Watch live" in _pass(_client(fake, monkeypatch).get("/my").text)


# ─── the doors ───────────────────────────────────────────────────────


def test_love_citys_doors(lovecity, fake, monkeypatch):  # noqa: F811
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: True)
    g = next(r for r in fake.t["groups"] if r["id"] == tct.GROUP)
    g.update(kind="team", name="Ushers")
    for i, name in enumerate(("Greeters", "Media")):
        fake.add("groups", id=tct.cid(2400 + i), business_id=tct.BIZ, name=name, active=True, kind="team",
                 join_mode="open", open_to_join=True)
    doors = _doors(_client(fake, monkeypatch).get("/my").text)
    assert doors[0] == ("/my/connect#lm-pray-h", "Prayer", "", "Ask or pray")
    assert doors[1] == ("/my/events", "Events", "", "2 coming up")          # the event, and Sunday off the calendar
    assert doors[2] == ("/my/serving", "Serve", "", "4 teams")              # with the fake's own Choir
    assert doors[3] == ("/my/give", "Give", "", "Give online")


def test_a_failed_calendar_read_says_no_number(lovecity, fake, monkeypatch):  # noqa: F811
    import member_portal_church as mpc
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: None)
    doors = _doors(_client(fake, monkeypatch).get("/my").text)
    assert doors[1] == ("/my/events", "Events", "", "Calendar")


def test_kids_keeps_give_in_the_tab_bar(lovecity, fake, monkeypatch):  # noqa: F811
    import giving_router
    import member_spaces as msp
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: True)

    async def resolve(b, me, wanted=""):
        return {"space": "church", "youth": False, "leader": {}, "kids_parent": True, "options": ["church", "kids"]}
    c = _client(fake, monkeypatch)
    monkeypatch.setattr(msp, "resolve_async", resolve)
    doors = _doors(c.get("/my").text)
    assert [d[1] for d in doors] == ["Prayer", "Events", "Serve", "Kids"]   # at most four
    monkeypatch.setattr("sunday_serving.on", lambda: False)
    doors = _doors(c.get("/my").text)
    assert [d[1] for d in doors] == ["Prayer", "Events", "Kids", "Give"]


# ─── the greeting ────────────────────────────────────────────────────


def test_love_citys_greeting(lovecity, fake, monkeypatch):  # noqa: F811
    import member_portal_sermons as mps
    last_sun = TODAY - timedelta(days=(TODAY.weekday() + 1) % 7 or 7)
    monkeypatch.setattr(mps, "load_library", lambda b: {"series": [], "sermons": [
        {"id": "00000000-0000-4000-8000-000000000631", "title": "Sunday (Part 1)", "preached_on": last_sun.isoformat(),
         "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}]})
    html = _client(fake, monkeypatch).get("/my").text
    line = html[html.index("<p class=lm-line4>"):]
    line = line[:line.index("</p>")]
    n = (lovecity["checkin"]["w"]["day"] - TODAY).days
    if n == 1:
        assert "Sunday is <b>tomorrow at 11</b>." in line
    whose = "Last week&#x27;s" if (TODAY - last_sun).days > 1 else "Yesterday&#x27;s"
    assert f"{whose} message is <b>ready to watch</b>, and Oh Give Thanks is <b>two weeks out</b>." in line


def test_the_later_event_is_never_a_service():
    import member_lumen_home as lh
    now = datetime.combine(TODAY, time(18, 45), tzinfo=NY)
    occ = [{"title": "Sunday Worship", "date": (TODAY + timedelta(days=8)).isoformat()},
           {"title": "Prayer Night", "date": (TODAY + timedelta(days=9)).isoformat()}]
    parts = lh.line({"kind": "welcome"}, service=None, serving=None, new=False, first=None, now=now, occasions=occ)
    assert "".join(t for t, _ in parts) == "Prayer Night is a week out."
    far = [{"title": "Retreat", "date": (TODAY + timedelta(days=40)).isoformat()}]
    assert lh.line({"kind": "welcome"}, service=None, serving=None, new=False, first=None, now=now, occasions=far) == []


def test_todays_look_reads_no_streams(lovecity, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c = _client(fake, monkeypatch)
    fake.gets.clear()
    html = c.get("/my").text
    assert not any("select=id&limit=1" in g and g.startswith("/live_sessions") for g in fake.gets)
    assert "lm-pass" not in html
