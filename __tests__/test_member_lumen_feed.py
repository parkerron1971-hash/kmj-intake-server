# __tests__/test_member_lumen_feed.py
#
# Home's feed in the member app's new look ("Look 4.1", restyled to Look 5.1
# by member_lumen_feed): each post edge to edge with its comments under it.
# Kevin: "make sure the people can comment under news feed. i know who ever
# make the post can allow whether people can comment or not." Pins:
#   - the newest one or two comments, one reply in (church_news.preview_of);
#   - each card: Love · Praying · Comment (News' react forms) and Save,
#     "Loved by", View all N comments and the newest comment, the write pill
#     on the same /my/news/comment route, the shield line;
#   - the poster's choice holds: Prayers only (I'm praying, no box), Off (a
#     lock line), and no box before the church has its two safety officers;
#   - the post's own photos; an event's date leaf over its picture spot;
#   - You're all caught up between what's new and what was opened;
#   - no read of its own: Home reads the same tables, as many times, in the
#     new look as in today's; today's Home and its reads are untouched;
#   - a comment from Home answers JSON: posted, held, crisis words (988),
#     refused; the preview saves nothing; the form post is unchanged;
#   - the CSS is in the Lumen file, moves only with motion allowed.

import pathlib
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_news as cn
import member_lumen_feed as mlf
import member_portal_church as mpc
import member_portal_news as mpn
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)

TODAY = date.today()
NOW = datetime.now(timezone.utc)
FOOD = "00000000-0000-4000-8000-000000000302"
P = {k: tct.cid(1700 + i) for i, k in enumerate(("worship", "noah", "food", "denise", "old1", "old2"))}
ELENA, LUIS, PASTOR = tct.cid(1602), tct.cid(1603), tct.cid(1601)


def _ago(**kw):
    return (NOW - timedelta(**kw)).isoformat()


def _post(f, key, **k):
    row = {"id": P[key], "business_id": tct.BIZ, "kind": "announcement", "title": key.title(), "body": "Words.",
           "group_id": None, "posted_by": None, "office_user": "u1", "author_label": "", "source": "office",
           "status": "posted", "pinned_until": None, "important": False, "comments": "on", "publish_at": None,
           "attach": {}, "person_id": None, "created_at": _ago(hours=1), "removed_at": None, "celebrate_on": None,
           "partner_id": None}
    row.update(k)
    f.t["church_posts"].append(row)
    return row


def _cm(f, key, who, body, hours, reply_to=None, status="shown", n=None):
    row = {"id": tct.cid(1800 + (n if n is not None else len(f.t["church_post_comments"]))), "business_id": tct.BIZ,
           "post_id": P[key], "contact_id": who, "body": body, "status": status, "reply_to": reply_to,
           "created_at": _ago(hours=hours)}
    f.t["church_post_comments"].append(row)
    return row


@pytest.fixture
def church(fake, monkeypatch):  # noqa: F811
    """Ana at Grace Fellowship with four posts on Home: a pinned one with a
    photo, a celebration with comments and a reply, an event (comments
    off), a prayer request (prayers only)."""
    for t in ("church_posts", "church_post_reactions", "church_post_seen", "church_post_comments",
              "church_post_comment_loves", "church_post_reports", "church_news_posters", "sermons"):
        fake.t[t] = []
    biz = fake.biz[tct.BIZ]
    biz["name"] = "Grace Fellowship"
    biz["settings"]["brand_kit"] = {"accent": "#D6246E"}
    fake.person(ELENA, "Elena Ruiz")
    fake.person(LUIS, "Luis Ortega")
    fake.person(PASTOR, "James Carter")
    occ = [{"entry_id": FOOD, "module_id": "m", "title": "Community Food Drive", "date": "2026-11-21",
            "date_label": "Saturday, November 21", "location": "Fellowship Hall", "capacity": None, "attending": 12,
            "spots_left": None, "full": False, "occasion_noun": "event", "roles": [], "mine": None}]
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: [dict(o) for o in occ])
    import member_portal_sermons as mps
    monkeypatch.setattr(mps, "load_library", lambda b: {"sermons": [], "series": []})
    import live_router as lr
    monkeypatch.setattr(lr, "current", lambda b: {})
    import church_checkin as cc
    monkeypatch.setattr(cc, "card", lambda b, me, now=None: {"state": "off"})
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    import member_portal_classes as mcl
    monkeypatch.setattr(mcl, "tab_on", lambda b, me: False)
    import messaging_router as mr
    fake.officers = 2
    monkeypatch.setattr(mr, "officer_count", lambda b: fake.officers)
    monkeypatch.setattr(cn, "is_pastoral", lambda b, c: c == PASTOR)
    import member_portal_messaging as mpm
    fake.care = []
    monkeypatch.setattr(mpm, "care_alert", lambda b, me: fake.care.append(me["id"]))
    import member_push
    monkeypatch.setattr(member_push, "_later", lambda fn, *a, **k: None)
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    _post(fake, "worship", title="Sunday Worship", pinned_until=_ago(days=-3), created_at=_ago(days=2),
          attach={"photos": ["https://example.org/hero.jpg"]})
    _post(fake, "noah", kind="celebration", title="Welcome, baby Noah", created_at=_ago(hours=20))
    _post(fake, "food", kind="event", title="Food Drive", comments="off", created_at=_ago(hours=26),
          attach={"event": FOOD, "signup": True})
    _post(fake, "denise", title="Keep Sister Denise in prayer", posted_by=PASTOR, comments="prayers",
          created_at=_ago(hours=30))
    _cm(fake, "noah", LUIS, "Praying over him this week.", 6)
    _cm(fake, "noah", tct.BEN, "What a gift.", 5)
    maya = _cm(fake, "noah", tct.CAL, "He is beautiful.", 2)
    _cm(fake, "noah", ELENA, "Those cheeks!", 1, reply_to=maya["id"])
    _cm(fake, "noah", tct.BEN, "something unkind", 0.5, status="held")
    for who in (tct.ANA, tct.BEN, tct.CAL):
        fake.t["church_post_reactions"].append({"post_id": P["noah"], "contact_id": who, "business_id": tct.BIZ,
                                                "kind": "love", "created_at": _ago(hours=1)})
    fake.t["church_post_reactions"].append({"post_id": P["denise"], "contact_id": tct.BEN, "business_id": tct.BIZ,
                                            "kind": "pray", "created_at": _ago(hours=1)})
    return fake


def _client(fake, monkeypatch):  # noqa: F811
    c = tct._app(fake, monkeypatch, tct.ANA)
    c.app.include_router(mpn.router)
    return c


def _feed(html):
    i = html.index('<section class="lm-feed"')
    return html[i:html.index("</section>", i)]


def _card(html, key):
    i = html.index(f'<article class="lf-post" id="p-{P[key]}"')
    return html[i:html.index("</article>", i)]


# ─── the newest comments ─────────────────────────────────────────────


def _c(i, at, reply_to=None):
    return {"id": f"c{i}", "created_at": f"2026-11-19T{at}:00+00:00", "reply_to": reply_to}


def test_the_preview_is_the_newest_thread_one_reply_in():
    rows = [_c(1, "08:00"), _c(2, "09:00"), _c(3, "10:00"), _c(4, "11:00", reply_to="c2")]
    got = cn.preview_of(list(reversed(rows)))
    assert [r["id"] for r in got] == ["c2", "c4"] and got[1]["is_reply"] and not got[0].get("is_reply")
    # No reply on the newest: the two newest comments, oldest first.
    assert [r["id"] for r in cn.preview_of(rows[:3])] == ["c2", "c3"]
    assert [r["id"] for r in cn.preview_of(rows[:1])] == ["c1"] and cn.preview_of([]) == []
    # A reply whose comment is gone stands on its own.
    assert [r["id"] for r in cn.preview_of([_c(5, "12:00", reply_to="gone")])] == ["c5"]


# ─── the card ────────────────────────────────────────────────────────


def test_home_is_the_feed_with_comments_under_each_post(church, monkeypatch):
    html = _client(church, monkeypatch).get("/my").text
    feed = _feed(html)
    assert '<h2 class="mp-sr" id="lm-feed-h">What&#x27;s happening at Grace Fellowship</h2>' in feed
    assert '<a class="lf-comp-in" href="/my/post">Share a praise or a prayer…</a>' in feed   # contract 2: members post
    order = re.findall(r'<article class="lf-post" id="p-([^"]+)"', feed)
    assert order == [P["worship"], P["noah"], P["food"], P["denise"]]           # pinned first, then newest
    noah = _card(html, "noah")
    # Loved by: the newest Love that isn't Ana's, by first name, and how many more.
    assert '<p class="lf-likes">Loved by <b>Ben</b> and <b>2 others</b></p>' in noah
    # Love · Praying: News' react forms, answered in place (RX_JS), back to Home; Save at the right.
    forms = re.findall(r'<form method="post" action="/my/news/react" class="nw-rxf">.*?name="kind" value="(\w+)">'
                       r'<input type="hidden" name="back" value="/my">', noah)
    assert forms == ["love", "pray"]
    assert re.search(r'class="lf-act lv" type="submit" aria-pressed="true" aria-label="Love"', noah)   # Ana loves it
    assert f'<label class="lf-act" for="cwt-{P["noah"]}">' in noah                    # Comment opens the box
    assert 'action="/my/news/save" class="lf-savef"' in noah and 'aria-label="Save"' in noah
    # The newest comment (Elena's reply to Maya); the held one never.
    lines = re.findall(r'<div class="(lf-cm[^"]*)" id="fc-[^"]+"><p><b>([^<]+)</b> <span>([^<]+)</span></p>', noah)
    assert lines == [("lf-cm rep", "Elena Ruiz", "Those cheeks!")]
    assert "something unkind" not in html
    assert f'<a class="lf-vall" href="/my/news/{P["noah"]}#comments">View all 4 comments</a>' in noah
    assert noah.index("lf-vall") < noah.index("lf-cms")                             # View all, then the newest
    # The write pill: the same route, the post's id, the member's initials, the shield line.
    assert (f'<form class="lf-cw" method="post" action="/my/news/comment"><input type="hidden" name="id" '
            f'value="{P["noah"]}"><span class="lf-cw-me" aria-hidden="true">AR</span>') in noah
    assert 'placeholder="Add a comment…"' in noah and 'maxlength="1000" required' in noah
    assert "Every comment is checked before the church sees it" in noah
    assert mlf.JS in html and mpn.RX_JS in html


def test_the_posters_choice_holds(church, monkeypatch):
    html = _client(church, monkeypatch).get("/my").text
    food, denise = _card(html, "food"), _card(html, "denise")
    assert "Comments are off for this post." in food
    assert 'class="lf-cw"' not in food and 'class="lf-act" for=' not in food and "lf-vall" not in food
    # Prayers only: the post on the soft panel, I'm praying is the pray reaction; no box, no Praying in the row.
    assert 'name="kind" value="pray"><input type="hidden" name="back" value="/my"><button class="lf-pbtn"' in denise
    assert '<div class="lf-pray lf-cpr"><p class="lf-kick">Please pray</p><b class=lf-pt>Keep Sister Denise in prayer</b>' in denise
    assert "I&#x27;m praying" in denise or "I'm praying" in denise
    assert "Comments are off for this one. Tap Praying to let them know." in denise
    assert 'class="lf-cw"' not in denise and 'aria-label="Praying"' not in denise
    assert '<span class="n0">1 praying</span><span class="n1">2 praying</span>' in denise
    assert "James Carter" in denise and "Pastor" in denise


def test_no_box_before_the_church_has_its_safety_officers(church, monkeypatch):
    church.officers = 1
    html = _client(church, monkeypatch).get("/my").text
    noah = _card(html, "noah")
    assert "Comments aren't open at Grace Fellowship yet. You can still react." in noah
    assert 'class="lf-cw"' not in noah and "lf-cm " not in noah and 'aria-label="Love"' in noah
    assert "Comments are off for this one" in _card(html, "denise")               # prayers needs no officers


def test_pictures_are_the_posts_own_and_an_events_leaf(church, monkeypatch):
    html = _client(church, monkeypatch).get("/my").text
    assert '<div class="lf-pic lf-dbl"><img src="https://example.org/hero.jpg"' in _card(html, "worship")
    food = _card(html, "food")
    # No picture on that spot: the date leaf alone.
    assert '<span class="lf-evbare" aria-hidden="true"><span class="lf-leaf" aria-hidden="true"><small>SAT</small><b>21</b></span>' in food
    assert "Community Food Drive" in food and "Fellowship Hall · 12 going" in food
    assert 'action="/my/news/signup"' in food and 'name="back" value="/my"' in food
    # The church put a picture on the event's spot: it shows under the leaf.
    church.biz[tct.BIZ]["settings"]["member_portal"]["pictures"] = {
        "event:community-food-drive": {"url": "https://example.org/pantry.jpg", "look": "colour"}}
    food = _card(_client(church, monkeypatch).get("/my").text, "food")
    assert (f'<a class="lf-evimg" href="/my/events#mp-occ-{FOOD}" tabindex="-1" aria-hidden="true">'
            f'<img src="https://example.org/pantry.jpg"') in food and "<small>SAT</small>" in food


def test_an_album_shows_three_and_how_many_more():
    p = {"id": P["noah"], "attach": {"photos": [f"https://example.org/{i}.jpg" for i in range(5)]}}
    html = mlf._picture(p)
    assert html.startswith('<div class="lf-alb lf-dbl">') and html.count("<img") == 3 and '<span class="lf-plus">+2</span>' in html
    assert '<div class="lf-alb lf-dbl two">' in mlf._picture({"id": "x", "attach": {"photos": ["https://a/1.jpg", "https://a/2.jpg"]}})
    tall = mlf._picture({"id": "x", "attach": {"pics": [{"path": "p", "w": 600, "h": 900}]}})
    assert 'class="lf-pic lf-dbl tall"' in tall and 'src="/my/news/x/photo/0"' in tall


def test_caught_up_sits_between_new_and_opened(church, monkeypatch):
    church.t["church_post_seen"] += [{"post_id": P["food"], "contact_id": tct.ANA, "business_id": tct.BIZ},
                                     {"post_id": P["denise"], "contact_id": tct.ANA, "business_id": tct.BIZ}]
    feed = _feed(_client(church, monkeypatch).get("/my").text)
    assert "You&#x27;re all caught up" in feed or "You're all caught up" in feed
    at = feed.index("lf-done")
    assert feed.index(f'id="p-{P["noah"]}"') < at < feed.index('<p class="lf-older">Earlier</p>') < feed.index(f'id="p-{P["food"]}"')
    # Nothing opened yet: no line.
    church.t["church_post_seen"].clear()
    assert "lf-done" not in _feed(_client(church, monkeypatch).get("/my").text)
    # The seen read failed: no line either.
    church.t["church_post_seen"] += [{"post_id": P["food"], "contact_id": tct.ANA, "business_id": tct.BIZ}]
    church.down.add("church_post_seen")
    assert "lf-done" not in _feed(_client(church, monkeypatch).get("/my").text)


# ─── reads ───────────────────────────────────────────────────────────


def test_the_feed_costs_no_read_of_its_own(church, monkeypatch):
    c = _client(church, monkeypatch)
    got = {}
    for mode in ("on", "off"):
        monkeypatch.setenv("MEMBER_LUMEN", mode)
        c.get("/my")
        church.gets.clear()
        html = c.get("/my").text
        got[mode] = Counter(r.split("?")[0] for r in church.gets)
        assert ("lm-feed" in html) == (mode == "on")
    # Nothing read more often (the church's clock, a read today's cards make
    # once per label, is looked up once for the whole feed), nothing new.
    assert not (got["on"] - got["off"]), got["on"] - got["off"]
    assert set(got["on"]) == set(got["off"])
    assert got["on"]["/church_post_comments"] == got["off"]["/church_post_comments"] == 1
    assert got["on"]["/contacts"] == got["off"]["/contacts"]
    # Today's look asks for the comment count exactly as before; the new look
    # brings the words in that same read.
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    church.gets.clear()
    c.get("/my")
    assert any(r.startswith("/church_post_comments?") and r.endswith("&status=eq.shown&select=post_id&limit=50000")
               for r in church.gets)


def test_todays_home_keeps_from_the_church(church, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = _client(church, monkeypatch).get("/my").text
    assert "From the church" in html and 'class="nw-post' in html and "lm-feed" not in html
    posts, _n = cn.home_view(tct.BIZ, tct.ANA)
    assert all("preview" not in p and "seen" not in p and "rx_people" not in p for p in posts)


def test_a_poster_with_no_news_yet_sees_where_it_goes(church, monkeypatch):
    church.t["church_posts"].clear()
    church.t["church_news_posters"].append({"business_id": tct.BIZ, "contact_id": tct.ANA})
    feed = _feed(_client(church, monkeypatch).get("/my").text)
    assert 'href="/my/news/write"' in feed and "Post the church&#x27;s first news" in feed
    church.t["church_news_posters"].clear()
    assert "lm-feed" not in _client(church, monkeypatch).get("/my").text          # a member: nothing


# ─── a comment from Home ─────────────────────────────────────────────

JSON = {"accept": "application/json"}


def _screen(monkeypatch, verdict):
    import msg_screen

    async def screen(biz, text):
        if verdict == "down":
            raise msg_screen.ScreenUnavailable("down")
        return verdict
    monkeypatch.setattr(msg_screen, "screen", screen)


def _say(c, key, body, **extra):
    return c.post("/my/news/comment", data={"id": P[key], "body": body, **extra}, headers=JSON)


def test_a_comment_from_home_posts_in_place(church, monkeypatch):
    _screen(monkeypatch, "ok")
    r = _say(_client(church, monkeypatch), "noah", "So happy for you all.")
    x = r.json()
    assert r.status_code == 200 and x["ok"] and x["code"] == "commented" and x["pid"] == P["noah"]
    assert x["notice"] == "" and "So happy for you all." in x["html"] and "<b>You</b>" in x["html"]
    assert '<div class="lf-cm mine" id="fc-' in x["html"] and "Just now" in x["html"]
    saved = [c for c in church.t["church_post_comments"] if c["body"] == "So happy for you all."]
    assert len(saved) == 1 and saved[0]["status"] == "shown" and saved[0]["contact_id"] == tct.ANA


def test_a_reply_from_home_goes_under_its_comment(church, monkeypatch):
    _screen(monkeypatch, "ok")
    x = _say(_client(church, monkeypatch), "noah", "Amen.", reply_to=tct.cid(1803)).json()   # a reply to a reply
    saved = next(c for c in church.t["church_post_comments"] if c["body"] == "Amen.")
    assert saved["reply_to"] == tct.cid(1802) and 'class="lf-cm rep mine"' in x["html"]


def test_held_and_crisis_words_answer_with_the_pages_own_words(church, monkeypatch):
    c = _client(church, monkeypatch)
    _screen(monkeypatch, "harm")
    x = _say(c, "noah", "something unkind").json()
    assert x["ok"] and x["code"] == "comment_held" and x["notice"] == mpn.DONE["comment_held"]
    assert "Only you see this until a safety officer looks at it." in x["html"] and "lf-cm mine held" in x["html"]
    _screen(monkeypatch, "self_harm")
    x = _say(c, "noah", "I can't go on").json()
    assert x["ok"] and x["code"] == "care" and "988" in x["notice"] and x["notice"] == mpn.DONE["care"]
    assert church.care == [tct.ANA]
    assert [c_["status"] for c_ in church.t["church_post_comments"] if c_["contact_id"] == tct.ANA] == ["held", "held"]


def test_a_refused_comment_says_why_and_saves_nothing(church, monkeypatch):
    c = _client(church, monkeypatch)
    n = len(church.t["church_post_comments"])
    _screen(monkeypatch, "down")
    r = _say(c, "noah", "See you Sunday")
    assert r.status_code == 400 and r.json() == {"ok": False, "code": "comment_busy", "error": mpn.ERRORS["comment_busy"]}
    _screen(monkeypatch, "ok")
    assert _say(c, "food", "Hi").json()["error"] == mpn.ERRORS["comments_off"]
    assert _say(c, "denise", "Hi").json()["code"] == "comments_off"
    assert _say(c, "noah", "   ").json()["code"] == "comment_empty"
    church.officers = 0
    assert _say(c, "noah", "Hi").json()["code"] == "comments_closed"
    assert len(church.t["church_post_comments"]) == n


def test_the_owners_preview_saves_nothing(church, monkeypatch):
    import member_portal as mp
    c = _client(church, monkeypatch)
    monkeypatch.setattr(mp, "_session_for", lambda request, church_: {"preview": True, "me": {"id": tct.ANA}})
    n = len(church.t["church_post_comments"])
    r = _say(c, "noah", "Hello")
    assert r.status_code == 403 and r.json()["code"] == "preview" and r.json()["error"] == mpn.ERRORS["preview"]
    assert len(church.t["church_post_comments"]) == n


def test_the_form_post_is_unchanged(church, monkeypatch):
    _screen(monkeypatch, "ok")
    r = _client(church, monkeypatch).post("/my/news/comment", data={"id": P["noah"], "body": "Plain post"},
                                          follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my/news/{P['noah']}?done=commented#comments"


# ─── the sheet ───────────────────────────────────────────────────────


def test_the_feeds_css_is_in_the_lumen_file_before_the_type():
    import member_lumen_ui as lm
    parts = lm.templates()
    import member_lumen_fonts
    assert mlf.CSS in parts and parts.index(mlf.CSS) < len(parts) - 1               # before the type block,
    assert parts[-1].template == member_lumen_fonts.template().template            # which stays last
    css = mlf.CSS.template
    assert "$" not in css
    # It moves only when the phone allows it.
    still = re.sub(r"@media \(prefers-reduced-motion:no-preference\)\{.*?\n\}", "", css, flags=re.S)
    # With reduced motion the double-tap heart only fades (no scale): that rule alone.
    reduce = re.findall(r"@media \(prefers-reduced-motion:reduce\)\{(.*?)\}\}", still, flags=re.S)
    assert reduce == [".lm .lf-heart.calm{animation:lffade .7s ease both;"]
    still = re.sub(r"@media \(prefers-reduced-motion:reduce\)\{.*?\}\}", "", still, flags=re.S)
    assert "animation:" not in still and "transition:" not in still
    assert ".lm .wr-seg input:checked+span" in css                                  # posting from a phone
