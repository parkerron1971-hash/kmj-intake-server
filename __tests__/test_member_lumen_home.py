# __tests__/test_member_lumen_home.py
#
# The top half of the member app's new Home, "Look 4.1" then "Look 5.1"
# (member_lumen_home, member_portal_lumen.render_home), behind MEMBER_LUMEN.
# Kevin approved the 4.1 mock on 2026-11-19 and Look 5.1 on 2026-11-20 (its
# own pins, the moments, the doors and the composer, are
# test_member_lumen_home5.py). Pins:
#   - the greeting by the church's clock (moon or sun, the date, Good
#     evening / It's Sunday / Welcome) and a sentence made only of what the
#     records say, its facts in heavier ink, no chips;
#   - This week (Look 5.1, in place of 4.1's Up next card): the service,
#     each group's next gathering and the church's events this week, each a
#     card with the date leaf, how many are going (a number, never faces) and
#     its own action (check-in on the day, someone new's Your path); the
#     sentence still names what lh.pick picks;
#   - the group's I'll be there is today's group RSVP, coming back to Home;
#     who's answered is kept 30 s, forgotten by their own answer, read fresh
#     on the page that comes back;
#   - Also for you: picture tiles from the church's own picture spots (the
#     devotional, prayer, serving, the latest message, groups to join), the
#     frosted Change on each in edit mode; "prayer" is a spot only where the
#     new look shows;
#   - nothing a member can do on Home is lost: check-in, the news block,
#     then Also for you, Today, the message, groups, prayer, the foot cards;
#   - the reads: warm, the same as today's Home; cold, only the two kept
#     reads (what a new person told us, who's coming to the gathering);
#   - the sheet: every rule under body.lm, the type block still last, the
#     moves only with the phone's yes to motion.

import pathlib
import re
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_gatherings as gg
import member_im_new as mim
import member_lumen_home as lh
import member_lumen_ui as lm
import member_portal_church as mpc
import member_portal_lumen as mlp
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)

NY = ZoneInfo("America/New_York")
TODAY = date.today()
EVENING = datetime.combine(TODAY, time(18, 45), tzinfo=NY)


def _occ(title, d, n=0, mine=None, eid="00000000-0000-4000-8000-000000000301", tm=""):
    return {"entry_id": eid, "module_id": "m", "title": title, "date": d.isoformat(),
            "date_label": f"{d.strftime('%A, %B')} {d.day}", "location": "Sanctuary", "capacity": None,
            "attending": n, "spots_left": None, "full": False, "occasion_noun": "event", "roles": [], "mine": mine,
            "time": tm}


def _sunday_after(d):
    return d + timedelta(days=(6 - d.weekday()) % 7 or 7)


@pytest.fixture
def church(fake, monkeypatch):  # noqa: F811
    """Ana at Grace Fellowship (New York), on a weekday evening: the next
    Sunday's service on the calendar, check-in set for 10:30 (not open)."""
    fake.person(tct.ANA, "Ana Rivera")
    biz = fake.biz[tct.BIZ]
    biz["name"] = "Grace Fellowship"
    biz["settings"]["brand_kit"] = {"accent": "#D6246E"}
    biz["settings"]["availability"] = {"timezone": "America/New_York"}
    sun = _sunday_after(TODAY)
    scene = {"now": EVENING, "occ": [_occ("Sunday Worship", sun, n=40, tm="10:30"),
                                     _occ("Prayer Night", sun + timedelta(days=3), eid="00000000-0000-4000-8000-000000000302")],
             "live": {}, "serving": None, "told": {}}
    w = {"day": sun, "start": datetime.combine(sun, time(10, 30), tzinfo=NY), "open": False, "weekday": "Sunday"}
    scene["checkin"] = {"state": "closed", "w": w}
    monkeypatch.setattr(mlp, "church_now", lambda b: scene["now"])
    monkeypatch.setattr(gg, "_now", lambda: scene["now"].astimezone(timezone.utc))
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: [dict(o) for o in scene["occ"]])
    import member_portal_sermons as mps
    monkeypatch.setattr(mps, "load_library", lambda b: {"sermons": [], "series": []})
    import live_router as lr
    monkeypatch.setattr(lr, "current", lambda b: scene["live"])
    import church_checkin as cc
    monkeypatch.setattr(cc, "card", lambda b, me, now=None: scene["checkin"])
    import sunday_serving as ssv
    monkeypatch.setattr(ssv, "on", lambda: True)
    monkeypatch.setattr(ssv, "mine", lambda b, c: scene["serving"])
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    import member_portal_classes as mcl
    monkeypatch.setattr(mcl, "tab_on", lambda b, me: False)

    def read_app(b, c):
        fake.gets.append(f"/contacts?id=eq.{c}&select=id,app:metadata->new_here->app")
        mim.remember(b, c, dict(scene["told"]))
        return dict(scene["told"])
    monkeypatch.setattr(mim, "read_app", read_app)
    for kept in (gg._ANSWERS, mim._TOLD, mim._NOT_YET):
        kept.clear()
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    return scene


def _client(fake, monkeypatch):  # noqa: F811
    c = tct._app(fake, monkeypatch, tct.ANA)
    import member_portal_groups as mpg
    c.app.include_router(mpg.router)
    return c


def _group(fake, *, meets_today=True, at="19:00:00"):  # noqa: F811
    """Ana's group (the fake's, which she's in) as Young Adults, on a
    schedule tonight, with eleven going."""
    g = next(r for r in fake.t["groups"] if r["id"] == tct.GROUP)
    g.update(name="Young Adults", meets="Thursdays, 7:00 PM", location="The Johnsons' home", chat_on=True,
             meet_day=TODAY.weekday() if meets_today else (TODAY.weekday() + 2) % 7, meet_time=at, meet_skips=[],
             meet_every=1, meet_from=None, meet_nth=None, meet_address="412 Maple Ave")
    fake.t.setdefault("group_rsvps", [])
    for i in range(11):
        c = tct.cid(1600 + i)
        fake.person(c, f"Member {i}")
        fake.add("group_members", group_id=tct.GROUP, business_id=tct.BIZ, contact_id=c, role="member")
        fake.add("group_rsvps", business_id=tct.BIZ, group_id=tct.GROUP, met_on=TODAY.isoformat(), contact_id=c,
                 answer="going")
    # Someone no longer in the group answered too: not counted.
    fake.add("group_rsvps", business_id=tct.BIZ, group_id=tct.GROUP, met_on=TODAY.isoformat(), contact_id=tct.cid(1699),
             answer="going")


def _main(html):
    return html[html.index("<main"):html.index("</main>")]


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&#x27;", "'")


def _week(html):
    m = html[html.index('class="lm-wk5"'):]
    return m[:m.index("</section>") + 10]


# ─── the greeting ────────────────────────────────────────────────────


def test_the_greeting_by_the_churchs_clock(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    brief = html[html.index('<header class="lm-brief">'):html.index("</header>", html.index('<header class="lm-brief">'))]
    assert lh.MOON in brief and lh.SUN not in brief                          # evening
    assert f"{TODAY:%A} · {TODAY:%B} {TODAY.day}" in brief
    assert '<h1 class="lm-disp lm-hi4">Good evening, <em>Ana.</em></h1>' in brief
    church["now"] = datetime.combine(TODAY, time(9, 15), tzinfo=NY)
    html = _client(fake, monkeypatch).get("/my").text
    assert lh.SUN in html and "Good morning, <em>Ana.</em>" in html


def test_on_sunday_its_sunday():
    sun = datetime.combine(_sunday_after(TODAY), time(9, 20), tzinfo=NY)
    assert lh.hello("Ana", sun, new=False) == "It&#x27;s Sunday, <em>Ana.</em>"
    assert lh.hello("Ana", sun, new=True) == "Welcome, <em>Ana.</em>"
    assert lh.hello("", EVENING, new=False) == "Good evening."


def test_the_sentence_says_only_what_the_records_say(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    sun = _sunday_after(TODAY)
    church["serving"] = {"coming": [{"id": "a1", "place": "Front doors", "team": "Greeters", "group_id": "",
                                     "call_time": "09:45", "with": ["Luis Ortega"],
                                     "service": {"day": sun.isoformat(), "at": datetime.combine(sun, time(10, 30), tzinfo=NY),
                                                 "title": "Sunday service"}}],
                         "asks": [], "next_at": datetime.combine(sun, time(10, 30), tzinfo=NY)}
    html = _client(fake, monkeypatch).get("/my").text
    line = html[html.index('<p class=lm-line4>'):]
    line = line[:line.index("</p>")]
    n = (sun - TODAY).days
    soon = "tomorrow at 10:30" if n == 1 else f"in {n} days"                # the service's time, tomorrow
    assert _text(line).strip() == (f"Young Adults is tonight at 7 at The Johnsons' home. Sunday is {soon} , "
                                   f"and you're on Greeters at 9:45 .")
    assert "<b>tonight at 7</b>" in line and "<b>on Greeters at 9:45</b>" in line and f"<b>{soon}</b>" in line
    assert "lm-chip" not in line                                             # no chips in sentences


def test_no_sentence_without_records(church, fake, monkeypatch):  # noqa: F811
    church["occ"] = []
    church["checkin"] = {"state": "off"}
    html = _client(fake, monkeypatch).get("/my").text
    assert "lm-line4" not in html
    assert 'class="lm-wk5"' not in html and "This week" not in html          # nothing this week: no section
    assert 'class="lm-doors"' in html                                        # the doors stay, with quiet lines


def test_the_line_parts():
    sun = _sunday_after(TODAY)
    service = {"day": sun, "time": time(10, 30), "title": "Sunday Worship", "where": ""}
    # A Sunday morning: the service's time and where they serve today.
    morning = datetime.combine(sun, time(9, 0), tzinfo=NY)
    serving = {"coming": [{"team": "Greeters", "call_time": "09:45", "service": {"day": sun.isoformat()}}]}
    parts = lh.line({"kind": "service"}, service=service, serving=serving, new=False, first=None, now=morning)
    assert "".join(t for t, _ in parts) == "Service starts at 10:30. You're on Greeters at 9:45."
    assert [t for t, b in parts if b] == ["10:30", "on Greeters at 9:45"]
    # Someone new: their first Sunday.
    parts = lh.line({"kind": "first"}, service=service, serving=None, new=True, first=service, now=EVENING)
    assert "".join(t for t, _ in parts) == f"We're so glad you found us. Your first Sunday is {sun:%A} at 10:30."
    # Nothing known: nothing said.
    assert lh.line({"kind": "welcome"}, service=None, serving=None, new=False, first=None, now=EVENING) == []


# ─── Up next ─────────────────────────────────────────────────────────


def test_which_card_is_featured():
    # The pick names what the greeting's sentence talks about (Look 5.1 has no featured card).
    sun = _sunday_after(TODAY)
    occ = [_occ("Food Drive", TODAY + timedelta(days=1), tm="09:00")]
    g_today = {"group": {"id": "g"}, "day": TODAY, "time": time(19, 0)}
    g_later = {"group": {"id": "g"}, "day": TODAY + timedelta(days=3), "time": time(19, 0)}
    ck_open = {"state": "open"}
    first = {"day": sun, "time": time(10, 30)}
    pick = lambda **k: lh.pick(**{"live": None, "ck": None, "gnext": None, "occasions": occ, "first": None,
                                  "now": EVENING, **k})["kind"]
    assert pick(live={"id": "l"}) == "live"
    assert pick(live={"id": "l"}, ck=ck_open) == "service"                  # the bar carries Join then
    assert pick(ck=ck_open, first=first) == "service"
    assert pick(first=first, gnext=g_today) == "first"
    assert pick(gnext=g_today) == "group"
    assert pick(gnext=g_later) == "event"                                    # the sooner wins
    assert pick(gnext=g_later, occasions=[]) == "group"
    assert pick(occasions=[]) == "welcome"


def test_the_group_card(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    fake.biz[tct.BIZ]["settings"]["messaging"] = {"enabled": True}
    html = _client(fake, monkeypatch).get("/my").text
    up = _week(html)
    assert '<h2 id="lm-wk-h">This week</h2><a href="/my/events">See all</a>' in up
    card = up[up.index('<article class="lm-wk">'):]
    card = card[:card.index("</article>")]
    assert f'<span class="lm-wkl" aria-hidden="true"><small>{TODAY:%a}</small><b>{TODAY.day}</b></span>' in card
    assert '<p class="lm-wkk">Tonight · 7:00 PM</p>' in card                 # soonest first
    assert f'<h3 class="lm-wkt"><a href="/my/groups/{tct.GROUP}">Young Adults</a></h3>' in card
    assert "The Johnsons&#x27; home" in card
    assert "<b>11</b> going" in card                                         # members only; never faces
    assert "<img" not in card.split('class="lm-wkbd')[1]                     # no faces anywhere on the card
    form = card[card.index('<form method="post" action="/my/groups/meet/rsvp">'):]
    form = form[:form.index("</form>")]
    for field in (f'name="group_id" value="{tct.GROUP}"', 'name="answer" value="going"', 'name="back" value="/my"'):
        assert field in form
    assert "I&#x27;ll be there" in form
    # The group's chat is its moment's reply (member_lumen_stories).
    assert f'<a class="lm-mvre" href="/my/groups/{tct.GROUP}/chat">Message the group…</a>' in html
    # The church's own picture for the group, through its spot.
    fake.biz[tct.BIZ]["settings"]["member_portal"]["pictures"] = {
        f"group:{tct.GROUP}": {"url": "https://example.org/ya.jpg", "look": "colour"}}
    up = _week(_client(fake, monkeypatch).get("/my").text)
    assert 'src="https://example.org/ya.jpg"' in up and "mb-ph is-colour" in up


def test_ill_be_there_comes_back_to_home_and_is_read_fresh(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    c = _client(fake, monkeypatch)
    c.get("/my")
    fake.gets.clear()
    c.get("/my")
    assert not [g for g in fake.gets if g.startswith("/group_rsvps")]       # kept
    r = c.post("/my/groups/meet/rsvp", data={"group_id": tct.GROUP, "answer": "going", "back": "/my"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my?done=rsvp_going"
    assert any(x["contact_id"] == tct.ANA and x["answer"] == "going" for x in fake.t["group_rsvps"])
    fake.gets.clear()
    html = c.get("/my?done=rsvp_going").text
    assert [g for g in fake.gets if g.startswith("/group_rsvps")]            # read fresh
    up = _week(html)
    assert "You&#x27;re going" in up and "You and 11 others" in up and "/my/groups/meet/rsvp" not in up
    assert "You&#x27;re going. See you there!" in html                       # the flash
    # From the group's own page, the answer still goes back to its Meet tab.
    r = c.post("/my/groups/meet/rsvp", data={"group_id": tct.GROUP, "answer": "maybe"}, follow_redirects=False)
    assert r.headers["location"] == f"/my/groups/{tct.GROUP}/meet?done=rsvp_maybe"


def test_the_sooner_event_is_featured_with_im_coming(church, fake, monkeypatch):  # noqa: F811
    _group(fake, meets_today=False)
    church["occ"].insert(0, _occ("Food Drive", TODAY + timedelta(days=1), n=12, tm="09:00",
                                 eid="00000000-0000-4000-8000-000000000303"))
    church["occ"][-1] = _occ("Prayer Night", TODAY + timedelta(days=12), eid="00000000-0000-4000-8000-000000000302")
    html = _client(fake, monkeypatch).get("/my").text
    up = _week(html)
    cards = re.findall(r'<article class="lm-wk">.*?</article>', up, re.S)
    food = next(c for c in cards if "Food Drive" in c)
    assert cards.index(food) == 0                                            # tomorrow comes first
    assert '<p class="lm-wkk">Tomorrow · 9:00 AM</p>' in food and "<b>12</b> going" in food
    assert 'action="/my/rsvp"' in food and 'name="back" value="/my"' in food and "I&#x27;m coming" in food
    church_cards = html[html.index('<section class="lm-feed lf-church"'):]
    assert "Food Drive" not in church_cards                                  # not twice
    assert 'aria-label="Event: Prayer Night"' in church_cards               # past this week: an event card


def test_sunday_morning_carries_check_in(church, fake, monkeypatch):  # noqa: F811
    sun = _sunday_after(TODAY)
    church["now"] = datetime.combine(sun, time(9, 20), tzinfo=NY)
    church["occ"] = [_occ("Sunday Worship", sun, n=40, tm="10:30")]
    w = {"day": sun, "start": datetime.combine(sun, time(10, 30), tzinfo=NY), "open": True, "weekday": "Sunday"}
    church["checkin"] = {"state": "open", "w": w, "occasion": {"id": "o", "title": "Sunday Worship"}, "marks": {},
                         "settings": {}, "family": [{"id": tct.ANA, "name": "Ana Rivera", "me": True},
                                                    {"id": tct.BEN, "name": "Ben Rivera", "me": False}]}
    c = _client(fake, monkeypatch)
    html = c.get("/my").text
    assert "It&#x27;s Sunday, <em>Ana.</em>" in html and "Service starts at <b>10:30</b>." in html
    up = _week(html)
    assert '<p class="lm-wkk">Today · 10:30 AM</p>' in up and "Sunday Worship" in up and "Sanctuary" in up
    assert up.count('action="/my/here"') == 2
    assert 'name="where" value="in"' in up and 'name="where" value="online"' in up
    assert f'name="people" value="{tct.ANA}"' in up and f'name="people" value="{tct.BEN}"' in up
    assert 'href="/my/here?from=home">Choose who' in up and "One tap counts you and your family" in up
    assert 'class="lm-ck"' not in html                                       # the card is the check-in
    # Checked in: Welcome home, and Change it.
    church["checkin"]["marks"] = {tct.ANA: {"method": "self"}}
    up = _week(c.get("/my").text)
    assert "Welcome home." in up and 'href="/my/here?change=1&amp;from=home"' in up and 'action="/my/here"' not in up
    # A check-in that didn't go through: the full card under This week, as today.
    church["checkin"]["marks"] = {}
    html = c.get("/my?ck=closed").text
    assert 'class="lm-ck"' in html and "Check-in has closed for today" in html


def test_live(church, fake, monkeypatch):  # noqa: F811
    church["live"] = {"id": "l1", "title": "Sunday Worship"}
    html = _client(fake, monkeypatch).get("/my").text
    bar = html[html.index('<a class="lm-lv4"'):]
    assert bar.startswith('<a class="lm-lv4" href="/my/live">') and "Live now · Sunday Worship" in bar[:200]
    # While check-in is open too: the slim bar carries Join, This week check-in.
    sun = _sunday_after(TODAY)
    church["now"] = datetime.combine(sun, time(10, 40), tzinfo=NY)
    church["checkin"] = {"state": "open", "w": {"day": sun, "start": datetime.combine(sun, time(10, 30), tzinfo=NY)},
                         "occasion": {"title": "Sunday Worship"}, "marks": {}, "settings": {},
                         "family": [{"id": tct.ANA, "name": "Ana Rivera", "me": True}]}
    html = _client(fake, monkeypatch).get("/my").text
    bar = html[html.index('<a class="lm-lv4"'):]
    assert bar.startswith('<a class="lm-lv4" href="/my/live">') and "Live now · Sunday Worship" in bar[:200]
    assert 'action="/my/here"' in _week(html)


def test_someone_new_sees_their_first_sunday(church, fake, monkeypatch):  # noqa: F811
    church["told"] = {"at": (EVENING - timedelta(days=1)).isoformat(), "first_time": True}
    fake.add("groups", id=tct.cid(33), business_id=tct.BIZ, name="Women of Grace", active=True, kind="small_group",
             join_mode="open", meets="Tuesdays")
    html = _client(fake, monkeypatch).get("/my").text
    assert "Welcome, <em>Ana.</em>" in html
    assert "We&#x27;re so glad you found us. Your first Sunday is <b>Sunday at 10:30</b>." in html
    up = _week(html)
    assert '<p class="lm-wkk">Your first Sunday · 10:30 AM</p>' in up and "Sunday Worship" in up
    assert '<a class="lm-wkb" href="/my/new">Your path</a>' in up
    assert 'class="lm-also"' not in html                                     # Also for you is gone (Connect has groups)
    # Someone who's been coming a while: not new.
    church["told"] = {"at": (EVENING - timedelta(days=1)).isoformat(), "first_time": False}
    for kept in (mim._TOLD, mim._NOT_YET):
        kept.clear()
    assert "Welcome, <em>Ana.</em>" not in _client(fake, monkeypatch).get("/my").text


# ─── Also for you ────────────────────────────────────────────────────


def test_also_for_you_and_today_are_gone(church, fake, monkeypatch):  # noqa: F811
    # Kevin's Home plan (2026-11-21): the devotional is a moment, prayer a
    # door, the verse a card in the feed, the plan in Bible.
    import devotionals as dv
    dev = {"id": "00000000-0000-4000-8000-0000000009d1", "title": "Rooted", "day_count": 21, "status": "published",
           "starts_on": TODAY - timedelta(days=3), "kind": ""}
    days = [{"title": f"Day {n}", "body": "word " * 900} for n in range(1, 22)]
    days[3]["title"] = "Planted by the Water"
    monkeypatch.setattr(dv, "catalog", lambda b, published=True: [dict(dev)])
    monkeypatch.setattr(dv, "one", lambda b, i, published=True: (dict(dev, days=days), True))
    fake.biz[tct.BIZ]["settings"]["member_portal"]["pictures"] = {
        f"devotional:{dev['id']}": {"url": "https://example.org/trees.jpg", "look": "colour"},
        "prayer": {"url": "https://example.org/pray.jpg", "look": "colour"}}
    html = _client(fake, monkeypatch).get("/my").text
    for gone in ('class="lm-also"', 'class="lm-t4"', 'id="lm-today-h"', 'id="lm-cu-h"', "dv-trow",
                 'class="lm-pray" href="/my/prayer"', "How can we pray for you?"):
        assert gone not in html, gone
    assert f'data-mo="dv:{dev["id"]}:4"' in html                             # the devotional: a moment
    assert 'class="lm-page lf-vod"' in html and "Verse of the day" in html   # the verse: a card in the feed


def test_edit_mode_puts_change_on_every_picture(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    fake.biz[tct.BIZ]["settings"]["member_portal"]["photo_editors"] = [tct.ANA]
    html = _client(fake, monkeypatch).get("/my?edit=pictures").text
    assert "Changing pictures" in html
    up = _week(html)
    assert f'<a class="mb-pin" href="/my/pictures/spot?key=group:{tct.GROUP}&amp;back=home">' in up
    # Not in edit mode: no Change anywhere.
    assert "mb-pin" not in _main(_client(fake, monkeypatch).get("/my").text)


def test_the_prayer_spot_only_where_the_new_look_shows(church, fake, monkeypatch):  # noqa: F811
    fake.biz[tct.BIZ]["settings"]["member_portal"]["photo_editors"] = [tct.ANA]
    c = _client(fake, monkeypatch)
    assert "Prayer on Home" in c.get("/my/pictures").text
    assert c.get("/my/pictures/spot?key=prayer").status_code == 200
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    assert "Prayer on Home" not in c.get("/my/pictures").text
    import member_app_pictures as mapic
    assert mapic.KEY_RE.fullmatch("prayer")


def test_nothing_on_home_is_lost(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    import member_portal_sermons as mps
    monkeypatch.setattr(mps, "load_library", lambda b: {"series": [], "sermons": [
        {"id": "00000000-0000-4000-8000-000000000601", "title": "Hope Has a Name", "speaker": "Pastor James",
         "preached_on": (TODAY - timedelta(days=4)).isoformat()}]})
    fake.add("group_members", group_id=tct.GROUP2, business_id=tct.BIZ, contact_id=tct.ANA, role="member")
    fake.biz[tct.BIZ]["settings"]["member_portal"]["tiles"] = [{"title": "Food pantry", "href": "/my/events"}]
    church["occ"][-1] = _occ("Prayer Night", TODAY + timedelta(days=12), eid="00000000-0000-4000-8000-000000000302")
    import church_news as cn
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(cn, "home_view", lambda b, me, **kw: ([{
        "id": "00000000-0000-4000-8000-000000000801", "kind": "announcement", "title": "Food Drive Saturday",
        "body": "Bring canned goods.", "created_at": now, "published_at": now, "reactions": {}, "mine": [],
        "comment_count": 0}], 1))
    html = _client(fake, monkeypatch).get("/my").text
    main = _main(html)
    # Kevin's Home plan (2026-11-21): the posts, then the church's own cards
    # (the message, the events after this week, the verse), the church's own
    # tiles, and "You're all caught up". Nothing below it.
    order = [main.index(s) for s in ('class="lm-brief"', 'class="lm-doors"', 'id="lm-wk-h"', 'class="lm-hcp"',
                                     '<section class="lm-feed"', "Food Drive Saturday",
                                     '<section class="lm-feed lf-church"', 'id="msg-00000000-0000-4000-8000-000000000601"',
                                     'aria-label="Event: Prayer Night"', "Verse of the day", "Food pantry",
                                     "You&#x27;re all caught up")]
    assert order == sorted(order)
    end = main[main.index("You&#x27;re all caught up"):]
    assert "<section" not in end and "<article" not in end and "lm-cards" not in end    # nothing below it
    for gone in ('class="lm-also"', 'id="lm-cu-h"', 'id="lm-today-h"', 'id="lm-grp-h"', ">Choir<",
                 "on your home screen", "Get notified"):
        assert gone not in main, gone


# ─── reads and the sheet ─────────────────────────────────────────────


def test_the_reads(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    c = _client(fake, monkeypatch)
    base = lambda gets: Counter(g.split("?")[0] for g in gets)
    c.get("/my")
    fake.gets.clear()
    c.get("/my")
    warm_on = base(fake.gets)
    for kept in (gg._ANSWERS, mim._TOLD, mim._NOT_YET):
        kept.clear()
    import member_cache
    member_cache.feed.clear()                   # Look 5.1's group items (member_feed_more), kept 30 s
    fake.gets.clear()
    c.get("/my")
    cold_on = base(fake.gets)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c.get("/my")
    fake.gets.clear()
    c.get("/my")
    off = base(fake.gets)
    assert warm_on == off, warm_on - off                                    # warm: today's Home's reads
    # cold: the two kept reads, and the feed's group items (the member's
    # groups, their Board posts, their prayer walls: member_feed_more)
    assert cold_on - off == Counter({"/group_rsvps": 1, "/contacts": 1, "/group_members": 1, "/group_posts": 1,
                                     "/group_prayers": 1})


def test_the_sheet():
    css = lm.css()
    home = lh.CSS.template
    assert home in css and css.index(home) < css.index("/* type (member_lumen_fonts)")   # type still last
    text = re.sub(r"/\*.*?\*/", "", home, flags=re.S)
    rules = re.findall(r"(?:^|\})\s*([^{}@]+)\{", re.sub(r"@media[^{]*\{|@supports[^{]*\{", "", text))
    for sel in rules:
        for one in sel.split(","):
            one = one.strip()
            if one:
                assert one.startswith((".lm", "body.lm", "html:has(>body.lm")), one
    # Moves only with the phone's yes to motion.
    outside = re.sub(r"@media \(prefers-reduced-motion:no-preference\)\{.*?\n\}", "", home, flags=re.S)
    assert "transition" not in outside and "animation" not in outside and "@keyframes" not in outside
    # The church colour only where the mock puts it; no gradients, no left borders.
    assert "gradient" not in home and "border-left" not in home


def test_clock_of_and_the_occasions_time():
    assert mpc.clock_of("2026-11-22T10:30") == "10:30"
    assert mpc.clock_of("2026-11-22 19:05:00") == "19:05"
    assert mpc.clock_of("2026-11-22") == "" and mpc.clock_of("2026-11-22T10:30:00Z") == ""
    assert mpc.clock_of(None) == "" and mpc.clock_of("soon") == ""


def test_serving_home_is_mine_and_waiting_its_asks(monkeypatch):
    import sunday_serving as ssv
    got = {"asks": [{"id": "x"}], "coming": []}
    monkeypatch.setattr(ssv, "on", lambda: True)
    monkeypatch.setattr(ssv, "mine", lambda b, c: got)
    assert ssv.home({"id": "b"}, "c") is got and ssv.waiting({"id": "b"}, "c") == [{"id": "x"}]
    monkeypatch.setattr(ssv, "on", lambda: False)
    assert ssv.home({"id": "b"}, "c") is None and ssv.waiting({"id": "b"}, "c") == []
