# __tests__/test_member_lumen_all_posts.py
#
# See all posts (the member app's new look, member_lumen_feed). Kevin,
# 2026-11-20: "show 4 post and a show more tab where people can see other
# post from another page." Pins:
#   - Home keeps four posts; under the fourth, See all posts, with how many
#     there are when Home's own read can tell (none when the read was full,
#     none when Home already shows them all);
#   - /my/news in the new look is the all-posts page: the same cards as Home
#     (reactions, the newest comments, the write pill, the poster's choice,
#     an event's date leaf), ten at a time, Show more a plain link to the
#     next ten, the filter kept, Back to Home, today's birthdays on the first
#     page only, a page past the end says so;
#   - a form on page 2 comes back to page 2 (no JavaScript);
#   - reads stay bounded: one read of the posts, the decorations for this
#     page only, whose authors are pastors in two reads however many there
#     are (church_news.pastors_among); Home's reads are unchanged;
#   - with the switch off, News and Home are today's pages (?page ignored);
#   - the scripts ride once; the CSS is in the Lumen file, before the type.

import pathlib
import re
import sys
from collections import Counter
from datetime import timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import church_news as cn
import member_lumen_feed as mlf
import member_portal_news as mpn
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_feed import P, PASTOR, _ago, _client, _post, church  # noqa: F401  (the fixture)

OLD = [tct.cid(1900 + i) for i in range(17)]


def _older(f, n=17, **k):
    """n older posts, a day apart, after the fixture's four."""
    for i in range(n):
        row = {"id": OLD[i], "business_id": tct.BIZ, "kind": "announcement", "title": f"Older {i}", "body": "Words.",
               "group_id": None, "posted_by": None, "office_user": "u1", "author_label": "", "source": "office",
               "status": "posted", "pinned_until": None, "important": False, "comments": "on", "publish_at": None,
               "attach": {}, "person_id": None, "created_at": _ago(days=3 + i), "removed_at": None,
               "celebrate_on": None, "partner_id": None}
        row.update(k)
        f.t["church_posts"].append(row)


def _pastor_role(f, *who):
    f.t.setdefault("church_role_defs", []).append(
        {"id": "d1", "business_id": tct.BIZ, "key": "pastor", "title": "Lead Pastor", "job": "senior", "status": "active",
         "sort": 0, "created_at": _ago(days=90), "reports_to": None})
    for c in who:
        f.t.setdefault("church_leader_roles", []).append(
            {"id": f"r-{c}", "business_id": tct.BIZ, "contact_id": c, "role": "pastor", "status": "active"})


def _ids(html):
    return re.findall(r'<article class="lf-post" id="p-([^"]+)"', html)


def _see(html):
    m = re.search(r'<a class="lf-see"[^>]*>.*?</a>', html, re.S)
    return m.group(0) if m else ""


# ─── Home: four posts, then See all posts ─────────────────────────────


def test_home_keeps_four_posts_then_see_all_posts_with_the_count(church, monkeypatch):
    _older(church)
    html = _client(church, monkeypatch).get("/my").text
    feed = html[html.index('<section class="lm-feed"'):html.index("</section>", html.index('<section class="lm-feed"'))]
    assert _ids(feed) == [P["worship"], P["noah"], P["food"], P["denise"]]
    see = _see(feed)
    assert see.startswith('<a class="lf-see" href="/my/news" aria-label="See all 21 posts"><span>See all posts</span>')
    assert '<small aria-hidden="true">21</small>' in see
    # Under the fourth post, at the foot of the feed; the old All news is gone.
    assert feed.rindex("</article>") < feed.index('class="lf-see"') and "All news" not in html
    # The scripts ride once (two copies of RX_JS cancel each other out).
    assert html.count(mpn.RX_JS) == 1 and html.count(mlf.JS) == 1


def test_see_all_posts_has_no_number_when_home_already_shows_them_all(church, monkeypatch):
    see = _see(_client(church, monkeypatch).get("/my").text)
    assert see.startswith('<a class="lf-see" href="/my/news" aria-label="See all posts">') and "<small" not in see


def test_the_count_is_none_when_homes_read_came_back_full(church):
    _older(church)
    got = {}
    cn.home_view(tct.BIZ, tct.ANA, previews=True, count=got)
    assert got == {"n": 21}
    church.t["church_posts"] += [dict(r, id=tct.cid(2000 + i), created_at=_ago(days=40 + i))
                                 for i, r in enumerate(church.t["church_posts"][:20])]
    got = {}
    cn.home_view(tct.BIZ, tct.ANA, previews=True, count=got)
    assert got == {"n": None}                                                       # 40 read: more may be there
    assert "<small" not in mlf.see_all(None) and "<small" not in mlf.see_all(4) and "<small" in mlf.see_all(5)


def test_the_count_counts_what_the_page_lists(church):
    """Home leaves milestones and good news about a person to Celebrating
    today; the all-posts page lists them, so the count does too. A group's
    post for a group Ana isn't in is in neither."""
    _post(church, "old1", kind="milestone", person_id=tct.BEN, created_at=_ago(days=5))
    _post(church, "old2", group_id="00000000-0000-4000-8000-00000000dead", created_at=_ago(days=6))
    got = {}
    posts, _n = cn.home_view(tct.BIZ, tct.ANA, previews=True, count=got)
    assert len(posts) == 4 and got == {"n": 5}
    page = cn.feed_page(tct.BIZ, tct.ANA)
    assert page["total"] == 5 and P["old1"] in [p["id"] for p in page["posts"]]


def test_homes_reads_are_unchanged(church, monkeypatch):
    _older(church)
    c = _client(church, monkeypatch)
    c.get("/my")
    church.gets.clear()
    c.get("/my")
    on = Counter(r.split("?")[0] for r in church.gets)
    assert "/church_leader_roles" not in on                     # Home asks is_pastoral (stubbed here) as before
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c.get("/my")
    church.gets.clear()
    c.get("/my")
    off = Counter(r.split("?")[0] for r in church.gets)
    # Nothing more often than today's Home (which reads the church's clock per label), nothing new.
    assert not (on - off) and set(on) == set(off), on - off


# ─── the all-posts page ──────────────────────────────────────────────


def test_the_all_posts_page_is_home_s_cards_ten_at_a_time(church, monkeypatch):
    _older(church)
    c = _client(church, monkeypatch)
    html = c.get("/my/news").text
    ids = _ids(html)
    assert ids == [P["worship"], P["noah"], P["food"], P["denise"]] + OLD[:6]          # pinned first, then newest
    assert '<div class="lm-nwpage">' in html and "What&#x27;s <em>happening</em>" in html
    # Home's cards: Loved by, the react row (and Save) back to this page, the comments, the write pill.
    noah = html[html.index(f'id="p-{P["noah"]}"'):]
    noah = noah[:noah.index("</article>")]
    assert '<p class="lf-likes">Loved by <b>Ben</b> and <b>2 others</b></p>' in noah and "View all 4 comments" in noah
    assert noah.count('name="back" value="/my/news"') == 3                                    # Love · Praying · Save
    assert '<form class="lf-cw" method="post" action="/my/news/comment">' in noah
    # The poster's choice: prayers only, comments off; the event's date leaf and Sign me up.
    assert "I'm praying" in html and "Comments are off for this post." in html
    food = html[html.index(f'id="p-{P["food"]}"'):]
    food = food[:food.index("</article>")]
    assert '<span class="lf-leaf" aria-hidden="true"><small>SAT</small><b>21</b></span>' in food
    assert 'action="/my/news/signup"' in food and 'name="back" value="/my/news"' in food
    # Show more: a plain link to the next ten; no Earlier line on the first page.
    assert ('<a class="lf-see lf-next" href="/my/news?page=2"><span>Show more</span>' in html
            and "Earlier posts" not in html)
    # Back goes Home (the page's own link, in the bar).
    assert re.search(r'<a class="mb-back" href="/my">.*?Home</a>', html, re.S)
    # The scripts once each.
    assert html.count(mpn.RX_JS) == 1 and html.count(mlf.JS) == 1


def test_page_two_and_the_end(church, monkeypatch):
    _older(church)
    c = _client(church, monkeypatch)
    two = c.get("/my/news?page=2").text
    assert _ids(two) == OLD[6:16]
    assert '<p class="lf-page"><span>Earlier posts</span><a href="/my/news">Back to the newest</a></p>' in two
    assert 'href="/my/news?page=3"' in two and 'name="back" value="/my/news?page=2"' in two
    assert "<title>News, page 2" in two
    three = c.get("/my/news?page=3").text
    assert _ids(three) == OLD[16:] and "lf-next" not in three
    past = c.get("/my/news?page=9").text
    assert _ids(past) == [] and "That&#x27;s every post." in past and "lf-next" not in past
    # Nonsense is the first page.
    assert _ids(c.get("/my/news?page=abc").text) == _ids(c.get("/my/news").text)
    assert _ids(c.get("/my/news?page=-4").text) == _ids(c.get("/my/news").text)


def test_the_filter_rides_along(church, monkeypatch):
    _older(church, kind="event")
    c = _client(church, monkeypatch)
    html = c.get("/my/news?f=events").text
    assert _ids(html) == [P["food"]] + OLD[:9]
    assert 'href="/my/news?f=events&amp;page=2"' in html
    two = c.get("/my/news?f=events&page=2").text
    assert _ids(two) == OLD[9:] and '<a href="/my/news?f=events">Back to the newest</a>' in two
    assert 'name="back" value="/my/news?f=events&amp;page=2"' in two
    assert '<a class="nw-fp" href="/my/news?f=events" aria-current=page>Events</a>' in two


def test_todays_birthday_is_on_the_first_page_only(church, monkeypatch):
    import celebrations as cel
    _older(church)
    today = cel.local_now(church.business()).date().isoformat()
    _post(church, "old1", kind="celebration", person_id=tct.BEN, celebrate_on=today, attach={"sub": "birthday"},
          created_at=_ago(hours=2))
    c = _client(church, monkeypatch)
    one = c.get("/my/news").text
    assert '<article class="lf-post lf-today" aria-label="Today we celebrate">' in one
    assert f'<a class="lf-prow-p" href="/my/news/{P["old1"]}">' in one and "Wish them well" in one
    # After what's pinned, and it isn't one of the ten.
    assert one.index(f'id="p-{P["worship"]}"') < one.index("lf-today") < one.index(f'id="p-{P["noah"]}"')
    assert P["old1"] not in _ids(one) and len(_ids(one)) == 10
    assert "lf-today" not in c.get("/my/news?page=2").text


def test_the_page_marks_what_it_showed_as_opened(church, monkeypatch):
    _older(church)
    _client(church, monkeypatch).get("/my/news?page=2")
    seen = {r["post_id"] for r in church.t["church_post_seen"] if r["contact_id"] == tct.ANA}
    assert set(OLD[6:16]) <= seen and not (set(OLD[:6]) & seen) and not (set(OLD[16:]) & seen)


def test_no_news_yet_and_a_failed_read(church, monkeypatch):
    church.t["church_posts"].clear()
    c = _client(church, monkeypatch)
    html = c.get("/my/news").text
    assert "Nothing from your church yet. When your pastors post, it shows here." in html and "lf-next" not in html
    church.down.add("church_posts")
    r = c.get("/my/news")
    assert r.status_code == 503 and "The news couldn't load just now" in r.text


def test_a_form_on_page_two_comes_back_to_page_two(church, monkeypatch):
    _older(church)
    c = _client(church, monkeypatch)
    r = c.post("/my/news/react", data={"id": OLD[8], "kind": "love", "back": "/my/news?page=2"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my/news?page=2#p-{OLD[8]}"
    r = c.post("/my/news/react", data={"id": OLD[8], "kind": "amen", "back": "/my/news?f=events&page=2"},
               follow_redirects=False)
    assert r.headers["location"] == f"/my/news?f=events&page=2#p-{OLD[8]}"
    # Only a page number rides along.
    r = c.post("/my/news/react", data={"id": OLD[8], "kind": "pray", "back": "/my/news?page=2x&evil=1"},
               follow_redirects=False)
    assert r.headers["location"] == f"/my/news#p-{OLD[8]}"


# ─── reads ───────────────────────────────────────────────────────────


def test_reads_stay_bounded_and_pastors_are_read_together(church, monkeypatch):
    _older(church)
    authors = [tct.BEN, tct.CAL, tct.cid(1602), tct.cid(1603), PASTOR]
    for i, r in enumerate(church.t["church_posts"]):
        r["posted_by"] = authors[i % len(authors)]
    _pastor_role(church, PASTOR)
    c = _client(church, monkeypatch)
    got = {}
    for path in ("/my/news", "/my/news?page=2"):
        c.get(path)
        church.gets.clear()
        html = c.get(path).text
        got[path] = Counter(r.split("?")[0] for r in church.gets)
        assert got[path]["/church_posts"] == 1                       # one read of the posts
        assert got[path]["/church_leader_roles"] <= 2                # pastors together (and can_post's own)
        assert got[path]["/church_post_comments"] == 1 and got[path]["/church_post_reactions"] == 1
    # Page two costs what page one costs: whose authors are pastors isn't a read per author.
    assert got["/my/news"] == got["/my/news?page=2"]
    # The pastor's post says Pastor; the others don't.
    html = c.get("/my/news").text
    assert html.count("<small>Pastor · ") == sum(1 for r in church.t["church_posts"][:10] if r["posted_by"] == PASTOR)


def test_feed_page_reads_a_window_that_grows_with_the_page(church):
    assert cn.page_window(1) == cn.page_window(2) == cn.FEED_READ and cn.page_window(5) == 200
    assert cn.page_window(99) == cn.PAGE_READ_MAX and cn.page_count(0) == 1 and cn.page_count(999) == 40
    church.gets.clear()
    cn.feed_page(tct.BIZ, tct.ANA, page=5)
    assert any(g.startswith("/church_posts?") and g.endswith("&limit=200") for g in church.gets)
    church.down.add("church_posts")
    assert cn.feed_page(tct.BIZ, tct.ANA) is None


def test_pastors_among_reads_twice_however_many(church):
    _pastor_role(church, PASTOR)
    church.gets.clear()
    assert cn.pastors_among(tct.BIZ, [tct.BEN, PASTOR, tct.CAL, None]) == {PASTOR}
    assert [g.split("?")[0] for g in church.gets] == ["/church_leader_roles", "/church_role_defs"]
    church.gets.clear()
    assert cn.pastors_among(tct.BIZ, []) == set() and church.gets == []
    church.down.add("church_leader_roles")
    assert cn.pastors_among(tct.BIZ, [PASTOR]) is None


# ─── the switch off ──────────────────────────────────────────────────


def test_switch_off_news_and_home_are_todays(church, monkeypatch):
    _older(church)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c = _client(church, monkeypatch)
    news = c.get("/my/news").text
    assert 'class="nw-post' in news and "lf-post" not in news and "lf-next" not in news
    assert len(re.findall(r'<article class="nw-post', news)) == 21                 # every post, as today
    assert c.get("/my/news?page=2").text == news
    home = c.get("/my").text
    assert "All news" in home and "lf-see" not in home


# ─── the look ────────────────────────────────────────────────────────


def test_the_rows_css_is_in_the_lumen_file_with_tokens_only():
    import member_lumen_ui as lm
    parts = lm.templates()
    assert mlf.CSS in parts and parts.index(mlf.CSS) < len(parts) - 1
    css = mlf.CSS.template
    block = css[css.index("/* See all posts"):css.index("@media (prefers-reduced-motion")]
    assert ".lm .lf-see{" in block and ".lm .lf-next{" in block and ".lm .lf-today" in block
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b|rgba?\(", block)                    # tokens only, for dark mode
    still = re.sub(r"@media \(prefers-reduced-motion:no-preference\)\{.*?\n\}", "", css, flags=re.S)
    # (the double-tap heart's still fade is for reduced motion only)
    still = re.sub(r"@media \(prefers-reduced-motion:reduce\)\{.*?\}\}", "", still, flags=re.S)
    assert "transition:" not in still and "animation:" not in still
