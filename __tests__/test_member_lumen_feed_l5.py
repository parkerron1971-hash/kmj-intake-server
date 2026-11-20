# __tests__/test_member_lumen_feed_l5.py
#
# Home's feed in Look 5.1 (member_lumen_feed, member_feed_more). Kevin,
# 2026-11-20: "this is awesome. much better design. lets build this including
# the new still to build!" Pins:
#   - your groups' prayer requests and Board posts ride in Home's feed by
#     time, under "Name in Group", with the group page's own rules: a word
#     for the leaders reaches leaders only, a post for later waits, a
#     pastor card and an answered request never show, nor another group's;
#     the request shows the asker by first name (the wall's promise);
#   - "I prayed" is the wall's own mark: JSON for the script, back to Home
#     without it, and the member's kept items are forgotten;
#   - the newest message rides while it is new (seven days), never twice,
#     never a sample; it is marked for the mini-player and its Share hands
#     over the PUBLIC page (contract 1); an event's Share only when the
#     church's events page and the event are public; members' posts and
#     prayer requests never get a Share;
#   - Save keeps a post on the member's own record (bounded, guarded by
#     updated_at, rate-limited, the owner's preview saves nothing) and Saved
#     posts (from Me) lists them;
#   - "Loved by" names the newest Love that isn't mine, from Home's own
#     people read;
#   - reads: the group items cost three reads cold (four with people on
#     them), none warm; today's look reads none of them.

import pathlib
import re
import sys
from collections import Counter
from datetime import date, timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_cache
import member_feed_more as fm
import member_lumen_feed as mlf
import member_portal_groups as mpg
import member_portal_news as mpn
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_feed import ELENA, FOOD, LUIS, NOW, P, _ago, _client, _post, church  # noqa: F401

JSON = {"accept": "application/json"}
GP1, GP2, GP3, GP4, GP5 = (tct.cid(2101 + i) for i in range(5))
GR1, GR2, GR3, GR4 = (tct.cid(2201 + i) for i in range(4))


def _groups(f):
    f.t.setdefault("group_posts", [])
    f.t.setdefault("group_prayers", [])
    f.t.setdefault("group_prayer_marks", [])
    f.add("group_members", group_id=tct.GROUP, business_id=tct.BIZ, contact_id=ELENA, role="member")
    f.add("group_members", group_id=tct.GROUP, business_id=tct.BIZ, contact_id=LUIS, role="member")

    def gpost(i, **k):
        row = {"id": i, "business_id": tct.BIZ, "group_id": tct.GROUP, "title": "", "body": "Words.", "pinned": False,
               "ask_ack": True, "posted_by": tct.CAL, "audience": "all", "publish_at": None, "created_at": _ago(hours=2),
               "removed_at": None}
        row.update(k)
        f.t["group_posts"].append(row)

    gpost(GP1, body="Game night was a win. Bring a snack and a friend!", created_at=_ago(minutes=40))
    gpost(GP2, body="Leaders: the key is under the mat.", audience="leaders", created_at=_ago(minutes=30))
    gpost(GP3, body="Next month's plan.", publish_at=_ago(days=-2), created_at=_ago(minutes=20))
    gpost(GP4, body="Choir robes are in.", group_id=tct.GROUP2, created_at=_ago(minutes=10))
    gpost(GP5, body="An old one.", created_at=_ago(days=20))

    def prayer(i, **k):
        row = {"id": i, "business_id": tct.BIZ, "group_id": tct.GROUP, "contact_id": ELENA, "body": "Pray for us.",
               "to_pastor": False, "answered_at": None, "praise": "", "removed_at": None, "created_at": _ago(minutes=50)}
        row.update(k)
        f.t["group_prayers"].append(row)

    prayer(GR1, body="My mom's surgery is Friday morning, and she's nervous.", created_at=_ago(minutes=5))
    prayer(GR2, body=None, to_pastor=True, created_at=_ago(minutes=4))
    prayer(GR3, body="Answered!", answered_at=_ago(minutes=1), created_at=_ago(minutes=3))
    prayer(GR4, body="A request in the choir.", group_id=tct.GROUP2, created_at=_ago(minutes=2))
    for who in (tct.BEN, LUIS):
        f.t["group_prayer_marks"].append({"prayer_id": GR1, "contact_id": who, "business_id": tct.BIZ,
                                          "kind": "praying", "created_at": _ago(minutes=3)})


def _feed(html):
    i = html.index('<section class="lm-feed"')
    return html[i:html.index("</section>", i)]


def _art(html, prefix):
    i = html.index(f'id="{prefix}')
    j = html.rindex("<article", 0, i)
    return html[j:html.index("</article>", i)]


# ─── your groups ─────────────────────────────────────────────────────


def test_your_groups_requests_and_posts_ride_in_the_feed(church, monkeypatch):
    _groups(church)
    feed = _feed(_client(church, monkeypatch).get("/my").text)
    ids = re.findall(r'<article class="lf-post[^"]*" id="([^"]+)"', feed)
    # The newest two group items, by time among the church's posts: Elena's
    # request (5 minutes ago), then the game-night post (40 minutes).
    assert ids[:3] == [f"p-{P['worship']}", f"gp-{GR1}", f"gpo-{GP1}"], ids
    for hidden in (GP2, GP3, GP4, GP5, GR2, GR3, GR4):
        assert hidden not in feed                                   # leaders-only, for later, another group, old…
    req = _art(feed, f"gp-{GR1}")
    assert "Elena <i>in</i> Tuesday Night Group" in req and "Elena Ruiz" not in req   # first names, as the wall says
    assert re.search(r"Prayer request · \d+m<", req) and "My mom&#x27;s surgery is Friday morning" in req
    assert (f'<form method="post" action="/my/groups/prayer/mark" class="lf-prayf"><input type="hidden" name="id" '
            f'value="{GR1}"><input type="hidden" name="kind" value="praying"><input type="hidden" name="back" value="/my">'
            '<button class="lf-pbtn" type="submit" aria-pressed="false">') in req
    assert '<span class="n0">2 people prayed</span><span class="n1">3 people prayed</span>' in req
    assert f'href="/my/groups/{tct.GROUP}/prayer"' in req and "lm-share" not in req
    post = _art(feed, f"gpo-{GP1}")
    assert "Cal Moss <i>in</i> Tuesday Night Group" in post and "Game night was a win." in post
    assert f'<a class="lf-pill" href="/my/groups/{tct.GROUP}/board">' in post and "lm-share" not in post


def test_a_leader_sees_the_word_for_leaders(church, monkeypatch):
    _groups(church)
    for m in church.t["group_members"]:
        if m["contact_id"] == tct.ANA and m["group_id"] == tct.GROUP:
            m["role"] = "leader"
    got, ok = fm.read(tct.BIZ, tct.ANA)
    assert ok and [p["id"] for p in got["posts"]] == [GP2, GP1]          # still not the one for later
    assert [p["id"] for p in got["prayers"]] == [GR1]


def test_my_own_request_has_no_button(church, monkeypatch):
    _groups(church)
    next(r for r in church.t["group_prayers"] if r["id"] == GR1)["contact_id"] = tct.ANA
    req = _art(_feed(_client(church, monkeypatch).get("/my").text), f"gp-{GR1}")
    assert "You <i>in</i> Tuesday Night Group" in req and "lf-prayf" not in req and "2 people prayed" in req


def test_name_display_first_names_a_groups_posts(church, monkeypatch):
    _groups(church)
    next(g for g in church.t["groups"] if g["id"] == tct.GROUP)["name_display"] = "first"
    post = _art(_feed(_client(church, monkeypatch).get("/my").text), f"gpo-{GP1}")
    assert "Cal <i>in</i> Tuesday Night Group" in post and "Cal Moss" not in post


def test_i_prayed_is_the_walls_own_mark(church, monkeypatch):
    _groups(church)
    c = _client(church, monkeypatch)
    c.app.include_router(mpg.router)
    c.get("/my")                                                                      # keeps the group items
    assert member_cache.feed.get((tct.BIZ, tct.ANA))[0]
    r = c.post("/my/groups/prayer/mark", data={"id": GR1, "kind": "praying", "back": "/my"}, headers=JSON)
    assert r.status_code == 200 and r.json() == {"ok": True, "code": "praying"}
    assert any(m["prayer_id"] == GR1 and m["contact_id"] == tct.ANA for m in church.t["group_prayer_marks"])
    assert not member_cache.feed.get((tct.BIZ, tct.ANA))[0]                          # forgotten: Home reads it again
    req = _art(_feed(c.get("/my").text), f"gp-{GR1}")
    assert 'aria-pressed="true"' in req
    assert c.post("/my/groups/prayer/mark", data={"id": GR1, "kind": "praying"}, headers=JSON).json()["code"] == "unmarked"
    # Without script: back to Home, at the request, read fresh.
    r = c.post("/my/groups/prayer/mark", data={"id": GR1, "kind": "praying", "back": "/my"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my?done=praying#gp-{GR1}"
    # Another group's request: refused, nothing saved.
    x = c.post("/my/groups/prayer/mark", data={"id": GR4, "kind": "praying"}, headers=JSON)
    assert x.status_code == 400 and x.json() == {"ok": False, "code": "not_in_group"}
    # The wall's own form still goes back to the wall.
    r = c.post("/my/groups/prayer/mark", data={"id": GR1, "kind": "praying"}, follow_redirects=False)
    assert r.headers["location"].startswith(f"/my/groups/{tct.GROUP}/prayer?")


def test_a_failed_group_read_leaves_the_items_out(church, monkeypatch):
    _groups(church)
    church.down.add("group_prayers")
    html = _client(church, monkeypatch).get("/my").text
    assert f"gpo-{GP1}" in html and f"gp-{GR1}" not in html                         # the posts still show
    assert not member_cache.feed.get((tct.BIZ, tct.ANA))[0]                          # a partial read isn't kept
    # The groups can't be read at all: Home still comes (the news needs that
    # read too, so it says nothing, as before), with no group items.
    church.down.add("group_members")
    member_cache.feed.clear()
    r = _client(church, monkeypatch).get("/my")
    assert r.status_code == 200 and f"gpo-{GP1}" not in r.text and f"gp-{GR1}" not in r.text


# ─── the newest message ──────────────────────────────────────────────

SER, S1, S2 = tct.cid(2301), tct.cid(2302), tct.cid(2303)


def _library(monkeypatch, days=2, **extra):
    import member_portal_sermons as mps
    lib = {"series": [{"id": SER, "title": "Light Has Come", "description": ""}],
           "sermons": [dict({"id": S1, "title": "Hope Has a Name", "series_id": SER, "speaker": "Pastor James",
                             "scripture": "Isaiah 9:6", "preached_on": (date.today() - timedelta(days=days)).isoformat(),
                             "video_url": "https://www.youtube.com/watch?v=x", "audio_url": "https://a.example/x.mp3",
                             "summary": "", "questions": "", "published": True}, **extra),
                       {"id": S2, "title": "A Light in the Dark", "series_id": SER, "speaker": "Pastor James",
                        "scripture": "", "preached_on": (date.today() - timedelta(days=days + 7)).isoformat(),
                        "video_url": "", "audio_url": "", "summary": "", "questions": "", "published": True}]}
    monkeypatch.setattr(mps, "load_library", lambda b: lib)
    return lib


def test_the_newest_message_rides_while_it_is_new(church, monkeypatch):
    _library(monkeypatch)
    feed = _feed(_client(church, monkeypatch).get("/my").text)
    card = _art(feed, f"msg-{S1}")
    assert "New message · " in card and "Light Has Come · Part 2 of 2" in card and ">Hope Has a Name</a></h3>" in card
    assert "Pastor James · Isaiah 9:6" in card
    # Marked for the mini-player (contract 4).
    assert (f'data-lm-media data-title="Hope Has a Name" data-sub="Pastor James · Isaiah 9:6" data-thumb="" '
            f'data-href="/my/sermons/{S1}"') in card
    # Watch · Listen · Share: the PUBLIC page to the share sheet (contract 1).
    assert f'<a class="lf-pill pri" href="/my/sermons/{S1}">' in card and f'href="/my/sermons/{S1}#listen"' in card
    assert (f'<a class="lm-share lf-pill" href="/sermons/{S1}" data-share-kind="message" data-share-title="Hope Has a Name" '
            f'data-share-sub="Pastor James · Isaiah 9:6" data-share-id="{S1}">') in card    # no picture shown: none named
    # Sermons keep no running time: no duration chip is made up.
    assert "lf-dur" not in card


def test_no_message_when_it_is_old_a_sample_or_already_carried(church, monkeypatch):
    _library(monkeypatch, days=9)
    assert "lf-pmsg" not in _client(church, monkeypatch).get("/my").text
    _library(monkeypatch, sample=True)
    assert "lf-pmsg" not in _client(church, monkeypatch).get("/my").text
    _library(monkeypatch)
    _post(church, "old1", kind="message", title="This week's message", attach={"sermon": S1}, created_at=_ago(minutes=5))
    church.t["sermons"].append({"id": S1, "business_id": tct.BIZ, "title": "Hope Has a Name", "speaker": "Pastor James",
                                "scripture": "Isaiah 9:6", "series_id": SER, "published": True})
    html = _client(church, monkeypatch).get("/my").text
    assert "lf-pmsg" not in html                                                    # the post carries it
    post = _art(html, f"p-{P['old1']}")
    assert f'href="/sermons/{S1}" data-share-kind="message"' in post and "data-lm-media" in post


# ─── Share: church content only ──────────────────────────────────────


def test_an_events_share_only_when_its_public(church, monkeypatch):
    import member_portal_church as mpc
    occ = mpc.upcoming_for(tct.BIZ, {"id": tct.ANA})
    feed = _feed(_client(church, monkeypatch).get("/my").text)
    assert "lm-share" not in feed                                                   # not public: no Share
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: [dict(o, public=True, time="09:00") for o in occ])
    feed = _feed(_client(church, monkeypatch).get("/my").text)
    assert "lm-share" not in feed                                                   # the events page is off
    church.biz[tct.BIZ]["settings"]["events_public"] = {"enabled": True}
    food = _art(_feed(_client(church, monkeypatch).get("/my").text), f"p-{P['food']}")
    assert ('<a class="lm-share lf-pill" href="/events" data-share-kind="event" data-share-title="Community Food Drive" '
            f'data-share-sub="Saturday, Nov 21 · 9 AM · Fellowship Hall" data-share-id="{FOOD}">') in food
    assert '<p class="lf-kick">Saturday, Nov 21 · 9 AM</p>' in food
    # Only church content: never a member's post or a prayer request.
    for key in ("worship", "noah", "denise"):
        assert "lm-share" not in _art(_feed(_client(church, monkeypatch).get("/my").text), f"p-{P[key]}")


# ─── Loved by ────────────────────────────────────────────────────────


def test_loved_by_names_the_newest_love_that_isnt_mine(church, monkeypatch):
    for r in church.t["church_post_reactions"]:
        if r["post_id"] == P["noah"] and r["contact_id"] == tct.CAL:
            r["created_at"] = _ago(minutes=1)
    noah = _art(_feed(_client(church, monkeypatch).get("/my").text), f"p-{P['noah']}")
    assert '<p class="lf-likes">Loved by <b>Cal</b> and <b>2 others</b></p>' in noah
    church.t["church_post_reactions"][:] = [r for r in church.t["church_post_reactions"]
                                            if not (r["post_id"] == P["noah"] and r["contact_id"] != tct.ANA)]
    noah = _art(_feed(_client(church, monkeypatch).get("/my").text), f"p-{P['noah']}")
    assert '<p class="lf-likes">Loved by <b>you</b></p>' in noah
    denise = _art(_feed(_client(church, monkeypatch).get("/my").text), f"p-{P['denise']}")
    assert "lf-likes" not in denise                                                # Prayers only says how many pray


# ─── double-tap ──────────────────────────────────────────────────────


def test_a_photo_loves_on_double_tap_and_the_heart_stays_the_control(church, monkeypatch):
    html = _client(church, monkeypatch).get("/my").text
    worship = _art(html, f"p-{P['worship']}")
    assert '<div class="lf-pic lf-dbl">' in worship and '<span class="lf-heart" aria-hidden="true">' in worship
    assert 'aria-label="Love"' in worship and "<a " not in worship[worship.index("lf-dbl"):worship.index("lf-acts")]
    assert "pointerup" in mlf.JS and "dblclick" in mlf.JS and "prefers-reduced-motion: reduce" in mlf.JS


# ─── Save ────────────────────────────────────────────────────────────


def _me(f):
    return next(c for c in f.t["contacts"] if c["id"] == tct.ANA)


def test_save_keeps_a_post_on_my_own_record(church, monkeypatch):
    c = _client(church, monkeypatch)
    _me(church)["updated_at"] = "2026-11-20T10:00:00+00:00"
    r = c.post("/my/news/save", data={"id": P["noah"], "back": "/my"}, headers=JSON)
    assert r.status_code == 200 and r.json() == {"ok": True, "saved": True}
    assert _me(church)["metadata"]["member_saved"] == [P["noah"]]
    patch = [w for w in church.writes if w[0] == "patch" and w[1] == "contacts"][-1]
    assert patch[2] and patch[2][0]["id"] == tct.ANA                               # only my row
    noah = _art(_feed(c.get("/my").text), f"p-{P['noah']}")
    assert 'class="lf-act sv" type="submit" aria-pressed="true" aria-label="Save"' in noah
    assert c.post("/my/news/save", data={"id": P["noah"]}, headers=JSON).json() == {"ok": True, "saved": False}
    assert _me(church)["metadata"]["member_saved"] == []
    # Without script: back where it came from, at the post.
    r = c.post("/my/news/save", data={"id": P["noah"], "back": "/my"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my#p-{P['noah']}"


def test_save_is_bounded_and_newest_first(church, monkeypatch):
    _me(church)["metadata"] = {"member_saved": [tct.cid(3000 + i) for i in range(fm.SAVED_MAX)], "member_photo": {"p": 1}}
    assert fm.toggle_saved(tct.BIZ, tct.ANA, P["noah"]) is True
    got = _me(church)["metadata"]
    assert got["member_saved"][0] == P["noah"] and len(got["member_saved"]) == fm.SAVED_MAX
    assert got["member_photo"] == {"p": 1}                                          # the rest of the record kept


def test_save_is_guarded_by_updated_at(church, monkeypatch):
    seen = []
    import sb_clients
    real = sb_clients.sb_patch_as_service
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body, **kw: seen.append(path) or real(path, body))
    _me(church)["updated_at"] = "2026-11-20T10:00:00+00:00"
    fm.toggle_saved(tct.BIZ, tct.ANA, P["noah"])
    assert seen and "updated_at=eq.2026-11-20T10%3A00%3A00%2B00%3A00" in seen[0]


def test_save_refuses_what_i_cant_see_and_the_preview(church, monkeypatch):
    import member_portal as mp
    import rate_limit
    c = _client(church, monkeypatch)
    _post(church, "old1", group_id=tct.GROUP2, created_at=_ago(minutes=1))           # another group's post
    r = c.post("/my/news/save", data={"id": P["old1"]}, headers=JSON)
    assert r.status_code == 404 and r.json()["code"] == "news_gone"
    assert not _me(church)["metadata"].get("member_saved")
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: False)
    assert c.post("/my/news/save", data={"id": P["noah"]}, headers=JSON).status_code == 429
    monkeypatch.setattr(mp, "_session_for", lambda request, church_: {"preview": True, "me": {"id": tct.ANA}})
    r = c.post("/my/news/save", data={"id": P["noah"]}, headers=JSON)
    assert r.status_code == 403 and r.json()["code"] == "preview" and not _me(church)["metadata"].get("member_saved")


def test_saved_posts_from_me(church, monkeypatch):
    c = _client(church, monkeypatch)
    _me(church)["metadata"] = {"member_saved": [P["denise"], P["noah"], tct.cid(3999)]}
    html = c.get("/my/news/saved").text
    assert "Saved <em>posts</em>" in html
    ids = re.findall(r'<article class="lf-post" id="p-([^"]+)"', html)
    assert ids == [P["denise"], P["noah"]]                                           # newest saved first; gone left out
    assert html.count('aria-pressed="true" aria-label="Save"') == 2 and 'name="back" value="/my/news/saved"' in html
    _me(church)["metadata"] = {}
    assert "Nothing saved yet." in c.get("/my/news/saved").text
    assert 'href="/my/news/saved"' in c.get("/my/me").text                          # Me's door
    # Today's look has no Save: the page goes to News, and Me has no door.
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    r = c.get("/my/news/saved", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/news"
    assert "/my/news/saved" not in c.get("/my/me").text and "lf-savef" not in c.get("/my").text


# ─── reads ───────────────────────────────────────────────────────────


def test_the_group_items_cost_three_reads_cold_and_none_warm(church, monkeypatch):
    c = _client(church, monkeypatch)
    base = lambda gets: Counter(g.split("?")[0] for g in gets)  # noqa: E731
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c.get("/my")
    church.gets.clear()
    c.get("/my")
    off = base(church.gets)
    assert not ({"/group_posts", "/group_prayers"} & set(off))                    # today's look reads none of them
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    member_cache.feed.clear()
    church.gets.clear()
    c.get("/my")
    cold = base(church.gets)
    church.gets.clear()
    c.get("/my")
    warm = base(church.gets)
    assert cold - warm == Counter({"/group_members": 1, "/group_posts": 1, "/group_prayers": 1})   # nobody on them
    _groups(church)
    member_cache.feed.clear()
    church.gets.clear()
    c.get("/my")
    cold = base(church.gets)
    church.gets.clear()
    c.get("/my")
    warm = base(church.gets)
    assert cold - warm == Counter({"/group_members": 1, "/group_posts": 1, "/group_prayers": 1, "/contacts": 1})
    # One read each, bounded, the marks embedded with the requests.
    member_cache.feed.clear()
    church.gets.clear()
    c.get("/my")
    posts = [g for g in church.gets if g.startswith("/group_posts?")]
    prayers = [g for g in church.gets if g.startswith("/group_prayers?")]
    assert len(posts) == 1 and f"&limit={fm.POSTS_READ}" in posts[0] and "removed_at=is.null" in posts[0]
    assert len(prayers) == 1 and "group_prayer_marks(contact_id,kind,created_at)" in prayers[0]
    assert "to_pastor=is.false" in prayers[0] and "answered_at=is.null" in prayers[0]


def test_the_feeds_new_css_reads_tokens_only():
    css = mlf.CSS.template
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    # The only fixed colours: the play disc and photo overlays, which sit on a picture in any look.
    allowed = {"#fff", "#111"}
    for m in re.finditer(r"#[0-9a-fA-F]{3,6}\b", body):
        assert m.group(0) in allowed, m.group(0)
    assert ".lm .lf-pray{" in css and "background:var(--s1)" in css
