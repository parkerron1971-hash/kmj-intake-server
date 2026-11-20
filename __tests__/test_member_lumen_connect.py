# __tests__/test_member_lumen_connect.py
#
# Connect and a group's page in the member app's new look, "Look 5.1"
# (member_lumen_connect; Kevin, 2026-11-20). Pins:
#   - Connect: "Connect" and "Your people at <church>"; your groups with the
#     next gathering on the church's clock (soonest first) and the chat's real
#     unread count (member_portal_threads.counts' per-group count: notes plus
#     chat); serving's I'll be there / Can't make it through My serving's own
#     routes; Lesson n of m and Sign up; this week's prayer requests from the
#     member's groups (never their own; kept: no read on the second visit);
#     Find your people with Join / Ask to join and how many are in each; More
#     only where each feature is on. Nothing is shown that the records don't say.
#   - A group's page: the cover with Back (Connect) and More, the serif name,
#     Members only · N people · when, Joined / Chat, Posts · Events · Prayer ·
#     Members; the next gathering with I'll be there (back to the group) and
#     Directions only with a street address; the box to write goes where this
#     member can write today (a leader: the Board; a member: the chat); the
#     Board's posts as feed cards; someone outside sees Join / Ask to join.
#   - Off is today's look (test_member_lumen_people / _pages pin the pages).

import pathlib
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_prayer
import member_lumen_connect as lc
import member_portal_threads as mpt
import test_church_threads as tct
import test_member_messaging as tmm
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_group_chat import _page as group_page, church as gchurch  # noqa: F401  (fixture)
from test_member_lumen_pages import church, _client  # noqa: F401  (fixture)
from test_member_messaging import env  # noqa: F401  (fixture)

NY = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _fresh():
    if group_prayer._RECENT is not None:
        group_prayer._RECENT.clear()
    mpt._COUNTS.clear()
    yield
    if group_prayer._RECENT is not None:
        group_prayer._RECENT.clear()
    mpt._COUNTS.clear()


def _section(html, hid):
    at = html.index(f'aria-labelledby="{hid}"')
    return html[at:html.index("</section>", at)]


# ─── Connect: the page ───────────────────────────────────────────────


def test_connect_title_groups_and_more(church, fake, monkeypatch):  # noqa: F811
    fake.add("groups", id=tct.GROUP, business_id=tct.BIZ, name="Young Adults", active=True, kind="small_group",
             meets="Thursdays, 7:00 PM", location="The Johnsons' home", join_mode="ask")
    fake.add("group_members", group_id=tct.GROUP, business_id=tct.BIZ, contact_id=tct.ANA, role="member")
    html = _client(fake, monkeypatch).get("/my/connect").text
    assert '<h1 class="lm-ctt">Connect</h1><p class="lm-ctsub">Your people at Grace Fellowship</p>' in html
    groups = _section(html, "lm-grp-h")
    assert 'href="/my/groups">Find a group</a>' in groups
    assert '<a class="lm-grow" href="/my/groups/' in groups and "<b>Young Adults</b>" in groups
    assert "Thursdays, 7:00 PM · The Johnsons&#x27; home" in groups      # no regular time: its own words
    assert 'class="lm-gnew"' not in groups                              # nothing unread, no count
    more = _section(html, "lm-more-h")
    assert "<b>Events</b>" in more and "2 this week" in more            # the two events in the coming week
    assert "Church directory" not in more                               # the directory is off
    assert "/my/news" not in more


def test_connect_without_the_switch_is_groups(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    r = _client(fake, monkeypatch).get("/my/connect", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/groups"


def test_this_weeks_prayer_from_my_groups_never_my_own(church, fake, monkeypatch):  # noqa: F811
    fake.t.setdefault("group_prayers", [])
    fake.add("groups", id=tct.GROUP, business_id=tct.BIZ, name="Young Adults", active=True, kind="small_group",
             meets="", location="", join_mode="ask")
    fake.add("group_members", group_id=tct.GROUP, business_id=tct.BIZ, contact_id=tct.ANA, role="member")
    fake.person(tct.BEN, "Ben Stone")
    now = datetime.now(timezone.utc)

    def ask(i, who, body, **kw):
        fake.add("group_prayers", **{"id": tct.cid(1500 + i), "business_id": tct.BIZ, "group_id": tct.GROUP,
                                     "contact_id": who, "body": body, "to_pastor": False, "answered_at": None,
                                     "removed_at": None, "praise": None,
                                     "created_at": (now - timedelta(hours=i)).isoformat(), **kw})
    ask(1, tct.BEN, "My mom's surgery on Friday.")
    ask(2, tct.ANA, "My own request, which I never see read back to me.")
    ask(3, tct.BEN, "An answered one.", answered_at=now.isoformat())
    ask(4, tct.BEN, "Taken down.", removed_at=now.isoformat())
    ask(5, tct.BEN, "Last month.", created_at=(now - timedelta(days=20)).isoformat())
    c = _client(fake, monkeypatch)
    html = c.get("/my/connect").text
    card = _section(html, "lm-pray-h")
    assert "1 new this week from your group" in card
    assert "<b>Ben</b>" in card and "My mom&#x27;s surgery on Friday." in card
    for gone in ("My own request", "An answered one", "Taken down", "Last month"):
        assert gone not in card
    assert f'href="/my/groups/{tct.GROUP}/prayer">' in card and "Pray for them" in card
    assert 'href="/my/prayer">Ask for prayer</a>' in card
    # Kept: the second visit reads no prayer request and no name for them.
    fake.gets.clear()
    c.get("/my/connect")
    assert not [g for g in fake.gets if g.startswith("/group_prayers")]


def test_no_prayer_requests_is_the_private_ask(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my/connect").text
    card = _section(html, "lm-pray-h")
    assert "How can we pray for you?" in card and "It goes privately to the pastors." in card
    assert "Pray for them" not in card and "new this week" not in card


# ─── Connect: the pieces ─────────────────────────────────────────────


def _g(gid, name, **kw):
    return {"id": gid, "name": name, "kind": "Small group", "meets": "", "location": "", "role": "member",
            "live": None, "sched": {}, **kw}


def test_your_groups_soonest_first_with_real_unread_counts():
    now = datetime(2026, 11, 19, 18, 0, tzinfo=NY)           # a Thursday, 6 PM
    thu = {"meet_day": 3, "meet_time": "19:00:00", "meet_every": 1}
    sat = {"meet_day": 5, "meet_time": "08:00:00", "meet_every": 1}
    a, b, c = (tct.cid(1), tct.cid(2), tct.cid(3))
    html = lc.group_rows({"id": tct.BIZ, "settings": {}},
                         [_g(a, "Alpha"), _g(b, "Men's Breakfast", sched=sat), _g(c, "Young Adults", sched=thu,
                                                                                     location="The Johnsons' home")],
                         {c.lower(): 3}, [], set(), now)
    names = re.findall(r"<span class=\"lm-wt\"><b>([^<]+)</b>", html)
    assert names == ["Young Adults", "Men&#x27;s Breakfast", "Alpha"]
    assert "Tonight at 7 PM · The Johnsons&#x27; home" in html and "Saturday at 8 AM" in html
    assert '<span class="lm-gnew" aria-label="3 new">3</span>' in html and html.count("lm-gnew") == 1


def test_when_local_reads_the_same_clock():
    now = datetime(2026, 11, 19, 12, 0, tzinfo=NY)
    assert lc.when_local(datetime(2026, 11, 19, 19, 0, tzinfo=NY), now) == "Tonight at 7 PM"
    assert lc.when_local(datetime(2026, 11, 19, 10, 30, tzinfo=NY), now) == "Today at 10:30 AM"
    assert lc.when_local(datetime(2026, 11, 20, 19, 0, tzinfo=NY), now) == "Tomorrow at 7 PM"
    assert lc.when_local(datetime(2026, 11, 23, 9, 0, tzinfo=NY), now) == "Monday at 9 AM"
    assert lc.when_local(datetime(2026, 12, 4, 19, 0, tzinfo=NY), now) == "Fri, Dec 4 at 7 PM"


def _svc(status="yes", **kw):
    at = datetime(2026, 11, 22, 10, 30, tzinfo=NY)
    return {"id": "00000000-0000-4000-8000-000000000702", "place": "Front doors", "team": "Greeters",
            "call_time": "09:45", "status": status, "swap_to": None, "swap_name": None,
            "service": {"id": "s", "title": "Sunday service", "event": False, "day": at.date().isoformat(), "at": at},
            **kw}


def test_serving_said_yes_is_youre_on_and_cant_make_it():
    html = lc.serving_card({"teams": [], "asks": [], "coming": [_svc(**{"with": ["Luis Ortega", "Renee Park"]})]})
    assert "<b>Greeters · 9:45 AM</b>" in html and "Front doors with Luis and Renee" in html
    assert '<small>SUN</small><b>22</b>' in html
    assert 'href="/my/serving">' in html and "You're on" in html
    assert 'href="/my/serving?sub=00000000-0000-4000-8000-000000000702#sv-00000000-0000-4000-8000-000000000702">Can' in html


def test_serving_an_ask_answers_through_my_servings_own_routes():
    html = lc.serving_card({"teams": [], "asks": [_svc("asked", asked_by="Luis Ortega")], "coming": []})
    assert '<form method="post" action="/my/serving/answer">' in html and 'name="ans" value="yes"' in html
    assert "I'll be there" in html and "Luis Ortega asked you" in html
    assert 'href="/my/serving/00000000-0000-4000-8000-000000000702">Can' in html


def test_no_serving_no_section():
    assert lc.serving_card(None) == "" and lc.serving_card({"teams": [], "asks": [], "coming": []}) == ""


def test_classes_lesson_n_of_m_and_sign_up():
    html = lc.classes_list({"tz": "UTC", "programs": [], "mine": [
        {"course_id": "c1", "title": "Belong", "program": "Growth Track", "status": "active", "total": 6, "done": 2,
         "next": {"lesson": "Finding your gifts", "starts_at": "2026-11-24T19:00:00+00:00"}}],
        "open": [{"course_id": "00000000-0000-4000-8000-0000000000c2", "title": "Baptism class",
                  "starts_at": "2026-12-06T16:00:00+00:00", "teacher": "Pastor James"}]})
    assert "<b>Growth Track</b>" in html and "Lesson 3 of 6 · Finding your gifts" in html
    assert 'aria-valuenow="2"' in html and "width:33%" in html
    assert "<b id=" in html and "Baptism class" in html and "Starts Dec 6 · with Pastor James" in html
    assert '<form method="post" action="/my/classes/join">' in html and ">Sign up</button>" in html
    assert "signed up" not in html                                      # no count the records don't keep


def test_find_your_people_join_or_ask_with_how_many():
    open_ = [{"id": tct.cid(41), "name": "Men's Breakfast", "meets": "Saturdays, 8:00 AM", "mode": "open", "count": 24},
             {"id": tct.cid(42), "name": "Moms & Tots", "meets": "Wednesdays, 10:00 AM", "mode": "ask", "count": 31},
             {"id": tct.cid(43), "name": "Choir", "meets": "", "mode": "ask", "count": 9, "asked": True}]
    html = lc.discover({"id": tct.BIZ, "settings": {}}, open_, [], set(), alone=False)
    assert html.count('class="lm-dc"') == 2                             # two for someone already in a group
    assert "Saturdays, 8:00 AM · 24 members" in html
    assert re.search(r'action="/my/groups/ask"><input type="hidden" name="group_id" value="[^"]+41">.*?>Join</button>', html)
    assert ">Ask to join</button>" in html
    alone = lc.discover({"id": tct.BIZ, "settings": {}}, open_, [], set(), alone=True)
    assert alone.count('class="lm-dc"') == 3 and "Asked" in alone and alone.count("/my/groups/ask") == 2


def test_more_shows_only_whats_on():
    assert lc.more_rows({"id": tct.BIZ}, pastor=None, week_events=None, directory=False) == ""
    html = lc.more_rows({"id": tct.BIZ}, pastor=None, week_events=0, directory=True)
    assert "What&#x27;s coming up" in html and "Church directory" in html and "Your pastor" not in html


def test_week_count_counts_the_coming_seven_days():
    today = date(2026, 11, 20)
    occ = [{"date": "2026-11-20"}, {"date": "2026-11-26"}, {"date": "2026-11-27"}, {"date": "2026-11-19"}]
    assert lc.week_count(occ, today) == 2 and lc.week_count(None, today) is None


# ─── the reads behind it ─────────────────────────────────────────────


def test_recent_prayer_is_kept_and_skips_what_the_wall_hides(fake):  # noqa: F811
    fake.t.setdefault("group_prayers", [])
    fake.person(tct.BEN, "Ben Stone")
    now = datetime.now(timezone.utc)
    fake.add("group_prayers", id=tct.cid(1), business_id=tct.BIZ, group_id=tct.GROUP, contact_id=tct.BEN,
             body="Pray for my exams.", to_pastor=False, answered_at=None, removed_at=None,
             created_at=now.isoformat())
    fake.add("group_prayers", id=tct.cid(2), business_id=tct.BIZ, group_id=tct.GROUP, contact_id=None,
             body=None, to_pastor=True, answered_at=None, removed_at=None, created_at=now.isoformat())
    fake.add("group_prayers", id=tct.cid(3), business_id=tct.BIZ, group_id=tct.cid(99), contact_id=tct.BEN,
             body="Another group's.", to_pastor=False, answered_at=None, removed_at=None, created_at=now.isoformat())
    got = group_prayer.recent(tct.BIZ, [tct.GROUP])
    assert [(p["first"], p["body"]) for p in got] == [("Ben", "Pray for my exams.")]
    fake.gets.clear()
    assert group_prayer.recent(tct.BIZ, [tct.GROUP]) == got and fake.gets == []
    assert group_prayer.recent(tct.BIZ, []) == []


def test_each_group_chats_own_unread_count(fake):  # noqa: F811
    now = datetime.now(timezone.utc)
    t1, t2 = tct.cid(901), tct.cid(902)
    fake.add("msg_threads", id=t1, business_id=tct.BIZ, kind="group", group_id=tct.GROUP)
    fake.add("msg_threads", id=t2, business_id=tct.BIZ, kind="group", group_id=tct.cid(77))
    fake.add("msg_participants", business_id=tct.BIZ, thread_id=t1, contact_id=tct.ANA, state="active",
             last_read_at=(now - timedelta(hours=1)).isoformat())
    for i, (t, ago) in enumerate(((t1, 10), (t1, 20), (t1, 120), (t2, 5))):
        fake.add("msg_messages", id=tct.cid(1000 + i), business_id=tct.BIZ, thread_id=t, sender_contact_id=tct.BEN,
                 status="delivered", created_at=(now - timedelta(minutes=ago)).isoformat())
    per = {}
    total = mpt.chat_unread(tct.BIZ, tct.ANA, [tct.GROUP, tct.cid(77)], per)
    assert total == 3 and per == {tct.GROUP.lower(): 2, tct.cid(77).lower(): 1}
    assert mpt.chat_unread(tct.BIZ, tct.ANA, [tct.GROUP, tct.cid(77)]) == 3     # the count alone, as before


# ─── a group's page ──────────────────────────────────────────────────


def _schedule(env, **kw):
    for g in env.t["groups"]:
        if g["id"] == tmm.GRP:
            g.update(kw)
    for t in ("group_rsvps", "group_meetings", "group_meeting_attendance", "group_bring", "group_meeting_guests",
              "group_studies", "group_prayers", "group_prayer_marks", "group_posts", "group_post_seen"):
        env.t.setdefault(t, [])


def test_a_groups_page_head_buttons_and_tabs(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}").text
    assert '<header class="mb-top' not in html                         # the cover carries Back
    assert '<a class="lm-fab l" href="/my/connect" data-back aria-label="Back">' in html
    assert '<summary class="lm-fab r" aria-label="More">' in html and "Leave this group" in html
    assert re.search(r'Members only · \d+ (person|people)', html)
    btns = html[html.index('<div class="lm-gbtns">'):]
    btns = btns[:btns.index("</div>")]
    assert "Joined</a>" in btns and f'href="/my/groups/{tmm.GRP}/chat">' in btns and "Invite" not in btns
    tabs = html[html.index('<nav class="lm-gtabs"'):]
    tabs = tabs[:tabs.index("</nav>")]
    assert re.findall(r">(Posts|Events|Prayer|Members)<", tabs) == ["Posts", "Events", "Prayer", "Members"]


def test_the_box_to_write_goes_where_this_member_writes(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}").text
    assert f'<a class="lm-gin" href="/my/groups/{tmm.GRP}/chat">Write something to the group…</a>' in html
    leader = next(m for m in gchurch.t["group_members"] if m["group_id"] == tmm.GRP and m.get("role") == "leader")
    html = group_page(gchurch, leader["contact_id"], f"/my/groups/{tmm.GRP}").text
    assert f'<a class="lm-gin" href="/my/groups/{tmm.GRP}/board#post">' in html and "You lead" in html


def test_board_posts_are_feed_cards(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    _schedule(gchurch)
    leader = next(m for m in gchurch.t["group_members"] if m["group_id"] == tmm.GRP and m.get("role") == "leader")
    gchurch.t["group_posts"].append({"id": "00000000-0000-4000-8000-0000000000f1", "business_id": tmm.BIZ,
                                     "group_id": tmm.GRP, "title": "", "body": "Game night was a win.",
                                     "pinned": False, "ask_ack": True, "posted_by": leader["contact_id"],
                                     "after_hours": False, "emailed": 0, "audience": None, "publish_at": None,
                                     "created_at": datetime.now(timezone.utc).isoformat(), "removed_at": None})
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}").text
    card = html[html.index('<article class="lm-fc lm-gpost"'):]
    card = card[:card.index("</article>")]
    assert "Game night was a win." in card and "Leader · " in card and 'action="/my/groups/post/ack"' in card


def test_the_next_gathering_answers_back_to_the_group(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    today = datetime.now(timezone.utc).astimezone(NY).date()
    _schedule(gchurch, meet_day=(today + timedelta(days=2)).weekday(), meet_time="19:00:00", meet_every=1,
              meet_address="412 Maple Ave", meet_skips=[], meet_from=None, meet_nth=None)
    import church_checkin as cc
    import group_gatherings as gg
    monkeypatch.setattr(gg, "zone", lambda b: NY)
    monkeypatch.setattr(cc, "church_zone_name", lambda b: "America/New_York")
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}").text
    meet = html[html.index('<section class="lm-meet"'):]
    meet = meet[:meet.index("</section>")]
    assert "at 7 PM</b>" in meet and '<span class="lm-cleaf"' in meet
    assert f'<input type="hidden" name="back" value="/my/groups/{tmm.GRP}">' in meet and 'value="going"' in meet
    assert "https://www.google.com/maps/search/?api=1&amp;query=412%20Maple%20Ave" in meet
    # The answer comes back to the group's own page.
    import member_portal_groups as mpg
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    monkeypatch.setattr(gg, "rsvp", lambda biz, me, gid, ans: (True, "rsvp_" + ans))
    gchurch.who["id"] = tmm.ANA
    app = FastAPI()
    app.include_router(mpg.router)
    r = TestClient(app, base_url=f"https://{tmm.HOST}").post(
        "/my/groups/meet/rsvp", data={"group_id": tmm.GRP, "answer": "going", "back": f"/my/groups/{tmm.GRP}"},
        headers=tmm.ORIGIN, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my/groups/{tmm.GRP}?done=rsvp_going"
    r = TestClient(app, base_url=f"https://{tmm.HOST}").post(
        "/my/groups/meet/rsvp", data={"group_id": tmm.GRP, "answer": "going"}, headers=tmm.ORIGIN,
        follow_redirects=False)
    assert r.headers["location"] == f"/my/groups/{tmm.GRP}/meet?done=rsvp_going"     # today's way, unchanged


def test_no_street_address_no_directions(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    today = datetime.now(timezone.utc).astimezone(NY).date()
    _schedule(gchurch, meet_day=(today + timedelta(days=2)).weekday(), meet_time="19:00:00", meet_every=1,
              meet_address=None, meet_skips=[], meet_from=None, meet_nth=None)
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}").text
    assert '<section class="lm-meet"' in html and "Directions" not in html


def test_someone_outside_sees_join_and_no_tabs(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    for g in gchurch.t["groups"]:
        if g["id"] == tmm.GRP:
            g["join_mode"] = "open"
    gchurch.t["group_members"][:] = [m for m in gchurch.t["group_members"]
                                     if not (m["group_id"] == tmm.GRP and m["contact_id"] == tmm.ANA)]
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}").text
    assert '<div class="lm-gcov' in html and '<nav class="lm-gtabs"' not in html
    assert 'action="/my/groups/ask"' in html and ">Join</button>" in html
    assert "Members only" not in html and "Open to join" in html
    assert 'aria-label="More"' not in html


def test_off_a_groups_page_and_connect_are_todays(gchurch, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}").text
    assert 'class="lm-' not in html and '<section class="gs-hero' in html


def test_the_sheet_carries_the_block_before_the_type():
    import member_lumen_fonts
    import member_lumen_ui
    parts = member_lumen_ui.templates()
    assert lc.CSS in parts and parts[-1].template == member_lumen_fonts.template().template
    assert parts.index(lc.CSS) < len(parts) - 1
    css = lc.CSS.template
    assert "#fff;" not in css.replace("rgba(255,255,255,.92)", "")      # tokens, not hard-coded colours (the
    for line in css.splitlines():                                     # floating Back keeps its white plate)
        assert not line.strip() or line.startswith((".lm ", "/*", "@media", "@supports", "  ")), line
