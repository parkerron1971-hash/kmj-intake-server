"""The devotional a day at a time before sign-in (devotional_daily.py;
Kevin 2026-10-25, Love City's 21 days of Focus, Finances and Food: "how
can we make this devotional available where people can get them daily
before i reveal the app?"). Pins:
  · the day by date across three back-to-back weeks; tomorrow opens the
    evening before, later days don't;
  · /daily answers only on the address of a church it's on for;
  · someone on the list (t=1 in every texted link, or just signed up)
    isn't asked to sign up again;
  · signing up needs a real mobile number and the box ticked, keeps the
    words agreed to, never moves last_key, and a bot that fills the
    hidden box saves nothing;
  · the evening text goes from 7:30 to 8 PM Eastern, tomorrow's day, once
    a person; STOP wins; a text that didn't go is put back for the next
    tick;
  · DAILY on the church's own number signs up only while there's
    something to send.
"""
import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import devotional_daily as dd
import devotionals as dv

ET = ZoneInfo("America/New_York")
BIZ = {"id": dd.FIRST_CHURCH, "name": "Love City Church", "type": "ministry", "settings": {}}
CHURCH = {"business": BIZ, "site": {"slug": "love-city-church", "business_id": BIZ["id"],
                                    "site_config": {"custom_domain": "lovecityc.com"}}}
W1, W2, W3 = ("11111111-1111-4111-8111-11111111111" + str(i) for i in (1, 2, 3))


def _day(title, scripture):
    return {"title": title, "scripture": scripture, "body": "First fruits were never the leftovers.\n\nMidweek drifts.",
            "pull": "The first of it says who you trust with the rest of it.", "pray": "Lord, You get my first.",
            "act": "Set aside your first-fruits gift.", "together": "Wednesday service.", "journal": ""}


def _week(dev_id, title, kind, start):
    days = [_day(f"{kind} day {n}", "Psalm 24:1") for n in range(1, 8)]
    if dev_id == W2:
        days[2] = _day("First Fruits", "Proverbs 3:9-10")
    return {"id": dev_id, "business_id": BIZ["id"], "title": title, "kind": kind, "about": f"Welcome to {kind}.",
            "practices": [{"key": "a1", "title": "First Look", "sub": "Before my phone"},
                          {"key": "b2", "title": "Open Hand", "sub": "Every dollar written down"}],
            "days": days, "day_count": 7, "starts_on": start, "status": "published"}


FULL = {W1: _week(W1, "Consecrate Your Focus", "Focus Week", date(2026, 10, 19)),
        W2: _week(W2, "Consecrate Your Finances", "Finance Week", date(2026, 10, 26)),
        W3: _week(W3, "Consecrate Your Food", "Fasting Week", date(2026, 11, 2))}
DEVS = [{k: v for k, v in d.items() if k != "days"} for d in FULL.values()]


def _at(y, m, d, hh=10, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


@pytest.fixture
def world(monkeypatch):
    """Love City on /daily with three weeks; the clock and every outside
    call are in the test's hands."""
    state = {"now": _at(2026, 10, 28), "church": CHURCH, "devs": DEVS, "saved": [], "texts": [],
             "opted_out": set(), "allow": True, "contacts": []}
    monkeypatch.setattr(dd, "now_local", lambda: state["now"])
    monkeypatch.setattr(dd, "_church", lambda request: state["church"])
    monkeypatch.setattr(dd, "dated", lambda biz: state["devs"])
    monkeypatch.setattr(dv, "one", lambda biz, dev_id, published=True: (FULL.get(dev_id), True))
    monkeypatch.setattr(dd, "own_number", lambda biz: "+12316254974")
    monkeypatch.setattr(dd, "page_link", lambda biz, on=None: "https://lovecityc.com/daily?"
                        + (f"date={on.isoformat()}&" if on else "") + "t=1")

    def save(biz, phone, *, name, source, consent):
        state["saved"].append({"biz": biz, "phone": phone, "name": name, "source": source, "consent": consent})
        return True
    monkeypatch.setattr(dd, "_save", save)

    import rate_limit
    import sms_alerts
    import sms_routing
    import sms_service
    monkeypatch.setattr(rate_limit, "allow_strict", lambda bucket, key, **kw: state["allow"])
    monkeypatch.setattr(sms_alerts, "alerts_enabled", lambda: True)

    async def opted_out(client, phone, business_id=None):
        return phone in state["opted_out"]

    async def send(phone, body, *, business_id, client=None):
        if phone in state.get("fail", ()):
            raise RuntimeError("Twilio said no")
        state["texts"].append((phone, body))
        return f"SM{len(state['texts'])}"

    async def ensure(client, business_id, phone):
        state["contacts"].append(phone)

    async def nothing(*a, **kw):
        return None
    monkeypatch.setattr(sms_service, "is_opted_out", opted_out)
    monkeypatch.setattr(sms_routing, "_send_platform_sms", send)
    monkeypatch.setattr(sms_routing, "_ensure_contact", ensure)
    monkeypatch.setattr(sms_service, "_store_sms", nothing)
    monkeypatch.setattr(sms_service, "_find_contact_by_phone", nothing)
    return state


@pytest.fixture
def client(world):
    app = FastAPI()
    app.include_router(dd.router)
    return TestClient(app, base_url="https://lovecityc.com")


# ─── which day ───────────────────────────────────────────────────────


def test_the_day_follows_the_date_across_the_three_weeks():
    assert dd.place(DEVS, date(2026, 10, 25))[0]["id"] == W1 and dd.place(DEVS, date(2026, 10, 25))[1] == 7
    assert [(d["id"], n) for d, n in [dd.place(DEVS, date(2026, 10, 26)), dd.place(DEVS, date(2026, 11, 4))]] == [
        (W2, 1), (W3, 3)]
    assert dd.place(DEVS, date(2026, 10, 18)) is None and dd.place(DEVS, date(2026, 11, 9)) is None
    assert [d["id"] for d in dd.still_coming(DEVS, date(2026, 10, 28))] == [W2, W3]
    assert dd.label(DEVS[1], 3) == "Finance Week, day 3" and dd.label({"kind": ""}, 2) == "Day 2"


def test_which_churches_it_is_on_for(monkeypatch):
    monkeypatch.delenv("DEVOTIONAL_DAILY_BUSINESSES", raising=False)
    assert dd.enabled_for(dd.FIRST_CHURCH) and not dd.enabled_for("someone-else")
    monkeypatch.setenv("DEVOTIONAL_DAILY_BUSINESSES", "*")
    assert dd.enabled_for("someone-else")
    monkeypatch.setenv("DEVOTIONAL_DAILY_BUSINESSES", "off")
    assert not dd.enabled_for(dd.FIRST_CHURCH)
    monkeypatch.setenv("DEVOTIONAL_DAILY_BUSINESSES", f"x, {dd.FIRST_CHURCH}")
    assert dd.enabled_for(dd.FIRST_CHURCH) and not dd.enabled_for(None)


# ─── the page ────────────────────────────────────────────────────────


def test_today_reads_the_whole_day_with_its_scripture(client):
    r = client.get("/daily")
    assert r.status_code == 200 and "s-maxage" in r.headers["cache-control"]
    page = r.text
    assert "First Fruits" in page and "Finance Week · Day 3 of 7" in page and "Wednesday, October 28" in page
    assert "Honour the" in page and "Proverbs 3:9-10 · KJV" in page          # the verses themselves, from the Bible here
    for words in ("The first of it says who you trust", "Lord, You get my first.", "Wednesday service.",
                  "Open Hand"):
        assert words in page
    # the sign-up: the words agreed to, and the church's own number for DAILY
    assert 'action="/daily/join"' in page and "Love City Church: one text each evening" in page
    assert "Or text <b>DAILY</b>" in page and "(231) 625-4974" in page
    assert "app" not in page.lower().replace("apply", "").replace("application", "").replace("apple", "")
    # read, not heard: the phone's reading voice didn't sound natural (Kevin, 10-25)
    assert ">Listen<" not in page and "speechSynthesis" not in page


def test_tomorrow_opens_the_evening_before_and_later_days_stay_shut(client):
    assert "Finance Week day 4" in client.get("/daily?date=2026-10-29").text
    later = client.get("/daily?date=2026-10-30").text
    assert "First Fruits" in later and "Finance Week day 5</h1>" not in later     # back to today
    assert 'title="Opens Fri, Oct 30"' in later
    assert "Focus Week day 2" in client.get("/daily?date=2026-10-20").text           # last week stays open
    assert "First Fruits" in client.get("/daily?date=not-a-date").text


def test_before_the_first_day_it_welcomes_and_after_the_last_it_keeps_every_day(client, world):
    world["now"] = _at(2026, 10, 17)
    early = client.get("/daily").text
    assert "Starts Monday, October 19" in early and "Welcome to Focus Week." in early and 'id="join"' in early
    world["now"] = _at(2026, 11, 12)
    late = client.get("/daily").text
    assert "That was Nov 2–8" in late and 'id="join"' not in late
    assert late.count('class="day"') == 7                                         # every day a link


def test_every_link_we_text_says_on_the_list(monkeypatch):
    import church_follow_up
    monkeypatch.setattr(church_follow_up, "site_origin", lambda biz: "https://lovecityc.com")
    assert dd.page_link(BIZ["id"]) == "https://lovecityc.com/daily?t=1"
    assert dd.page_link(BIZ["id"], date(2026, 10, 26)) == "https://lovecityc.com/daily?date=2026-10-26&t=1"


def test_someone_on_the_list_isnt_asked_to_sign_up_again(client):
    """Kevin, the first evening: after reading the day, the page asked people
    to sign up again. The phone remembers (t=1 from a text, or joined=1),
    the form steps aside, and another number is one tap away."""
    page = client.get("/daily?t=1").text
    assert "localStorage.setItem('daily-listed','1')" in page.split("</head>")[0]    # before anything paints
    assert "You’re on the text list" in page and "No need to sign up again." in page
    assert "Not on the list yet? Sign up here" in page and 'action="/daily/join"' in page
    assert 'class="card join" id="join"' in page                                    # the phone decides
    done = client.get("/daily?joined=1").text
    assert 'class="card join done" id="join"' in done
    assert done.index("this evening at 7:30") < done.index('class="ask"')            # the thanks sits in the list box
    oops = client.get("/daily?why=phone").text
    assert 'class="card join open" id="join"' in oops                               # a problem always shows the form
    assert oops.index('class="ask"') < oops.index('class="flash bad"')


def test_it_answers_only_where_it_is_on(client, world):
    world["church"] = None                       # the API host, an unknown host, or a church it's off for
    assert client.get("/daily").status_code == 404
    assert client.post("/daily/join", data={"phone": "2315550123", "consent": "yes"}).status_code == 404
    world["church"] = CHURCH
    world["devs"] = []
    assert client.get("/daily").status_code == 404
    world["devs"] = None
    assert client.get("/daily").status_code == 503


# ─── joining ─────────────────────────────────────────────────────────


def _join(client, **form):
    return client.post("/daily/join", data={"phone": "(231) 555-0123", "consent": "yes", **form},
                       follow_redirects=False)


def test_signing_up_saves_the_words_and_sends_a_welcome(client, world):
    r = _join(client, name="  Jasmine   Carter ")
    assert r.status_code == 303 and r.headers["location"] == "/daily?joined=1#join"
    (row,) = world["saved"]
    assert (row["phone"], row["name"], row["source"]) == ("+12315550123", "Jasmine Carter", "web")
    assert row["consent"].startswith("Text me the daily devotional from Love City Church")
    assert world["contacts"] == ["+12315550123"]
    (phone, body), = world["texts"]
    assert body.startswith("Love City Church: You're signed up") and body.endswith("Reply HELP for help. Reply STOP to opt out.")
    assert "1 text each evening at 7:30" in body and "Msg & data rates may apply" in body and len(body) <= 320
    assert "https://lovecityc.com/daily" in body
    assert "this evening at 7:30" in client.get("/daily?joined=1").text


def test_after_quiet_hours_begin_the_welcome_waits(client, world):
    world["now"] = _at(2026, 10, 28, 20, 15)
    assert _join(client).headers["location"] == "/daily?joined=1#join"
    assert world["saved"] and world["texts"] == []
    assert "tomorrow evening at 7:30" in client.get("/daily?joined=1").text


@pytest.mark.parametrize("form,why", [
    ({"consent": ""}, "consent"), ({"phone": "12345"}, "phone"), ({"phone": "+44 20 7946 0958"}, "phone")])
def test_a_sign_up_needs_a_mobile_and_a_yes(client, world, form, why):
    assert _join(client, **form).headers["location"] == f"/daily?why={why}#join"
    assert world["saved"] == [] and world["texts"] == []
    assert "class=\"flash bad\"" in client.get(f"/daily?why={why}").text


def test_the_ones_that_save_nothing(client, world):
    assert _join(client, website="http://spam").headers["location"] == "/daily?joined=1#join"   # the hidden box
    world["opted_out"].add("+12315550123")
    assert _join(client).headers["location"] == "/daily?why=stopped#join"
    world["opted_out"].clear()
    world["allow"] = False
    assert _join(client).headers["location"] == "/daily?why=busy#join"
    world["allow"] = True
    world["now"] = _at(2026, 11, 12)
    assert _join(client).headers["location"] == "/daily?why=none#join"
    assert world["saved"] == [] and world["texts"] == []


def test_the_row_comes_back_live_and_keeps_what_was_sent(monkeypatch):
    import sb_clients
    seen = {}

    def post(path, row, prefer=None, **kw):
        seen.update(path=path, row=row, prefer=prefer)
        return [row]
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    assert dd._save(BIZ["id"], "+12315550123", name="", source="text", consent="Texted DAILY")
    assert seen["path"] == "/devotional_texts?on_conflict=business_id,phone"
    assert "merge-duplicates" in seen["prefer"]
    assert seen["row"]["stopped_at"] is None and "last_key" not in seen["row"] and "name" not in seen["row"]


def test_daily_by_text_only_while_there_is_something_to_send(world, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{"name": "Love City Church"}])
    assert dd.join_by_text(BIZ["id"], "+12315550123") == {"name": "Love City Church",
                                                          "url": "https://lovecityc.com/daily?t=1"}
    assert world["saved"][-1]["source"] == "text"
    world["now"] = _at(2026, 11, 12)
    assert dd.join_by_text(BIZ["id"], "+12315550124") is None
    world["now"] = _at(2026, 10, 28)
    assert dd.join_by_text("someone-else", "+12315550125") is None
    assert [dd.is_daily_word(w) for w in ("DAILY", "daily!", " Devotional. ", "daily bread", "")] == [
        True, True, True, False, False]


# ─── the evening text ────────────────────────────────────────────────


@pytest.fixture
def signups(world, monkeypatch):
    """Three people signed up at Love City, one at a church it's off for."""
    import sb_clients
    rows = [{"id": "r1", "business_id": BIZ["id"], "phone": "+12315550001", "last_key": None, "stopped_at": None},
            {"id": "r2", "business_id": BIZ["id"], "phone": "+12315550002", "last_key": f"{W2}_2", "stopped_at": None},
            {"id": "r3", "business_id": BIZ["id"], "phone": "+12315550003", "last_key": None, "stopped_at": None},
            {"id": "r4", "business_id": "someone-else", "phone": "+12315550004", "last_key": None, "stopped_at": None}]

    def get(path):
        if path.startswith("/devotional_texts?"):
            return [dict(r) for r in rows if r["stopped_at"] is None]
        if path.startswith("/businesses?"):
            return [{"name": "Love City Church"}]
        return []

    def patch(path, body):
        rid = path.split("id=eq.")[1].split("&")[0]
        row = next(r for r in rows if r["id"] == rid)
        if "or=(last_key.is.null,last_key.neq." in path:                    # the claim
            key = path.split("last_key.neq.")[1].rstrip(")")
            if row["last_key"] == key or row["stopped_at"] is not None:
                return []
        elif "&last_key=eq." in path:                                       # putting it back
            if row["last_key"] != path.split("&last_key=eq.")[1]:
                return []
        row.update(body)
        return [dict(row)]
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)

    async def no_wait(s):
        return None
    monkeypatch.setattr(dd.asyncio, "sleep", no_wait)
    return rows


def _sweep(when):
    return asyncio.run(dd.sweep_tick(when))


def test_the_evening_text_is_tomorrows_day_once_a_person(world, signups):
    world["opted_out"].add("+12315550003")
    counts = _sweep(_at(2026, 10, 27, 19, 35))
    assert counts == {"sent": 2, "skipped": 1, "failed": 0}
    assert [p for p, _ in world["texts"]] == ["+12315550001", "+12315550002"]      # never the church it's off for
    body = world["texts"][0][1]
    assert body == ("Love City Church: Tomorrow's devotional (Finance Week, day 3): First Fruits, Proverbs 3:9-10. "
                    "Read it tonight: https://lovecityc.com/daily?date=2026-10-28&t=1 Reply STOP to opt out.")
    assert len(body) <= 320 and body.isascii()
    assert signups[0]["last_key"] == f"{W2}_3" and signups[2]["last_key"] is None
    # the next tick that evening, and a second replica, send nothing again
    assert _sweep(_at(2026, 10, 27, 19, 45))["sent"] == 0 and len(world["texts"]) == 2


def test_only_from_half_past_seven_until_quiet_hours(world, signups, monkeypatch):
    for when in (_at(2026, 10, 27, 19, 29), _at(2026, 10, 27, 19, 58), _at(2026, 10, 27, 20, 0),
                 _at(2026, 10, 27, 9, 0)):
        assert _sweep(when)["sent"] == 0
    monkeypatch.setenv("DEVOTIONAL_DAILY", "off")
    assert _sweep(_at(2026, 10, 27, 19, 35))["sent"] == 0
    assert world["texts"] == []


def test_after_the_last_day_nobody_is_texted(world, signups):
    assert _sweep(_at(2026, 11, 8, 19, 35))["sent"] == 0                      # tomorrow is past week 3
    assert _sweep(_at(2026, 11, 1, 19, 35))["sent"] == 3                      # week 3's first day, the evening before
    assert "(Fasting Week, day 1)" in world["texts"][0][1]


def test_a_text_that_did_not_go_is_tried_again(world, signups):
    world["fail"] = {"+12315550002"}
    assert _sweep(_at(2026, 10, 27, 19, 35)) == {"sent": 2, "skipped": 0, "failed": 1}
    assert signups[1]["last_key"] == f"{W2}_2"                               # put back as it was
    world["fail"] = set()
    assert _sweep(_at(2026, 10, 27, 19, 45))["sent"] == 1
    assert signups[1]["last_key"] == f"{W2}_3"
