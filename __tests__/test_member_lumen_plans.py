# __tests__/test_member_lumen_plans.py
#
# Plans in the member app's new look (member_lumen_plans, topic_plans): Kevin
# approved "Plans built from what Love City already writes" (2026-11-21).
# Pins:
#   - the topic plans: six, five to seven days each, one to three passages a
#     day, every passage a real one in every translation, keys that fit the
#     tables' checks (no migration);
#   - off: the Bible tab's Plans is today's Bible tab, a topic plan's address
#     goes where any unknown plan goes today, a reading plan's page is
#     today's;
#   - the Plans tab: Continue (a running devotional the church dated first,
#     else one the member started, else their own latest plan, else the
#     church's), its day row from real progress and "N days in a row" only
#     where the days could be read; the church's devotionals as covers
#     drawn in its colour (a made cover with no picture); the six topics;
#     the four whole-Bible plans;
#   - failed reads leave their piece out (no made-up numbers, no "nothing
#     here");
#   - reads: tapping back to Plans reads nothing (everything kept), and a
#     write (start, a tick, stop) gives the phone a new plans version, so the
#     next page reads afresh even on another server copy;
#   - a topic plan's and a reading plan's page: Start, a day a day from the
#     day you start, ticks on the reading plans' own route, You finished it,
#     the two weeks around today on a long plan, Stop back to Plans;
#   - the CSS: one block in the Lumen sheet, before the share sheet, the mini
#     player and the type; every rule under body.lm.

import pathlib
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_pages import church, _client, _body_class  # noqa: F401  (church is a fixture)
from test_member_lumen_bible import bible, D1, D2  # noqa: F401  (bible is a fixture)

TODAY = date.today()


def _app(fake, monkeypatch):  # noqa: F811
    """The member pages with the plans' write routes."""
    import member_portal_devotionals as mpd
    import member_portal_reading as mpr
    c = _client(fake, monkeypatch)
    c.app.include_router(mpd.router)
    c.app.include_router(mpr.router)
    return c


def _hero(html):
    s = html[html.index('<section class="lm-pl-hero'):]
    return s[:s.index("</section>")]


def _section(html, hid):
    s = html[html.index(f'id="{hid}"'):]
    return s[:s.index("</section>")]


def _end_d1(fake):
    fake.t.setdefault("reading_progress", [])
    for r in fake.t["devotionals"]:
        if r["id"] == D1:
            r["starts_on"] = (TODAY - timedelta(days=30)).isoformat()


# ─── the topic plans ─────────────────────────────────────────────────


def test_the_topic_plans_are_short_real_scripture():
    import bible_text as bt
    import topic_plans as tp
    assert [t["title"] for t in tp.TOPICS.values()] == ["Anxiety", "Healing", "Purpose", "Marriage", "Money", "Grief"]
    for key, t in tp.TOPICS.items():
        assert re.fullmatch(r"[a-z0-9-]{1,40}", key)                                   # reading_progress.plan_key
        assert re.fullmatch(r"reading:[a-z0-9-]{1,40}", f"reading:{key}")              # member_plan_starts.plan
        assert 5 <= len(t["days"]) <= 7, key
        assert t["about"] and t["name"] and t["hue"] in "abcdef"
        for title, passages in t["days"]:
            assert title and title == title.strip() and not re.search(r"[\"“”]", title)
            assert 1 <= len(passages) <= 3
    for key, n, passage in tp.all_refs():
        refs = bt.find_refs(passage)
        assert len(refs) == 1, passage
        for tr in bt.TRANSLATIONS:
            assert bt.verses(refs[0][2], tr), (passage, tr)
    assert tp.label("topic-anxiety", 1) == "1 Peter 5:6-7 · Psalm 55:22"
    assert tp.href("topic-anxiety", 1) == "/my/bible/1-peter/5?v=6-7"
    assert tp.day("topic-anxiety", 8) == {} and tp.plan("topic-anxiety", None) is None
    assert tp.plan("topic-grief", TODAY) == {"key": "topic-grief", "title": "Comfort in grief", "start": TODAY,
                                              "days": 7, "own": True}


# ─── off is today's ──────────────────────────────────────────────────


def test_off_a_topic_plan_goes_where_any_unknown_plan_goes(bible, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c = _client(fake, monkeypatch)
    r = c.get("/my/bible/plans/topic-anxiety", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/bible/plans"
    old = c.get("/my/bible/plans/gospels-30").text
    assert 'class="lm-' not in old and "Stop this plan" in old
    r = c.get("/my/bible/plans/bible-year", follow_redirects=False)                    # not started: today's redirect
    assert r.status_code == 303 and r.headers["location"] == "/my/bible/plans?show=reading"


def test_off_a_write_gives_no_plans_cookie(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_plans as mlp
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c = _app(fake, monkeypatch)
    r = c.post("/my/bible/plans/start", data={"plan": "reading:nt-260"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/bible/plans/nt-260"
    assert mlp.VERSION_COOKIE not in r.headers.get("set-cookie", "")


# ─── the tab ─────────────────────────────────────────────────────────


def test_continue_is_the_devotional_the_church_is_reading(bible, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my/bible?tab=plans").text
    assert _body_class(html).split()[:3] == ["lm", "lm-tab", "pg-bible"]
    assert re.findall(r'aria-current="page">(\w+)', html[html.index('<div class="lm-bseg">'):])[0] == "Plans"
    hero = _hero(html)
    assert '<p class="lm-pl-k">Continue · Day 3 of 7</p>' in hero
    assert '<h2 class="lm-pl-ht" id="lm-pl-hh">Seven Days of Rest</h2>' in hero
    assert '<p class="lm-pl-hs">Unhurried · Psalm 23:2</p>' in hero                    # today's title and scripture
    assert ('<span class="lm-pl-dots" role="img" aria-label="Day 3 of 7. 2 days read."><i class="ok">1</i>'
            '<i class="ok">2</i><i class="now">3</i><i>4</i><i>5</i><i>6</i><i>7</i></span>') in hero
    assert f'<a class="lm-pl-go" href="/my/bible/plans/{D1}/3">Read day 3</a>' in hero
    assert "2 days in a row" in hero


def test_continue_reads_on_from_the_first_day_not_read(bible, fake, monkeypatch):  # noqa: F811
    now = datetime.now(timezone.utc).isoformat()
    fake.add("devotional_progress", business_id=tct.BIZ, contact_id=tct.ANA, devotional_id=D1, day=3, done_at=now,
             checks=[], journal="")
    fake.t["devotional_progress"] = [r for r in fake.t["devotional_progress"] if not (r["devotional_id"] == D1 and r["day"] == 1)]
    hero = _hero(_client(fake, monkeypatch).get("/my/bible?tab=plans").text)
    assert f'href="/my/bible/plans/{D1}/1">Read day 1</a>' in hero                       # today's is read: day 1 isn't
    assert '<i>1</i><i class="ok">2</i><i class="ok now">3</i>' in hero
    assert "2 days in a row" in hero


def test_continue_falls_to_the_members_own_latest_plan(bible, fake, monkeypatch):  # noqa: F811
    _end_d1(fake)
    for d in (3, 4):
        fake.add("reading_progress", business_id=tct.BIZ, contact_id=tct.ANA, plan_key="gospels-30",
                 start_date=(TODAY - timedelta(days=4)).isoformat(), day=d)
    c = _client(fake, monkeypatch)
    hero = _hero(c.get("/my/bible?tab=plans").text)
    assert "Continue · Day 5 of 30" in hero and "The Gospels in 30 days" in hero and "Today: Matthew 13–15" in hero
    assert ('<i>1</i><i>2</i><i class="ok">3</i><i class="ok">4</i><i class="now">5</i><i>6</i><i>7</i>') in hero
    assert 'href="/my/bible/matthew/13">Read day 5</a>' in hero and "2 days in a row" in hero
    # a topic plan started today is the latest
    fake.add("member_plan_starts", business_id=tct.BIZ, contact_id=tct.ANA, plan="reading:topic-anxiety",
             started_on=TODAY.isoformat())
    import member_lumen_plans as mlp
    mlp.forget_everything()
    html = c.get("/my/bible?tab=plans").text
    hero = _hero(html)
    assert hero.startswith('<section class="lm-pl-hero tp-a"') and "When you&#x27;re anxious" in hero
    assert "Cast your cares on Him · 1 Peter 5:6-7 · Psalm 55:22" in hero
    assert 'href="/my/bible/1-peter/5?v=6-7">Read day 1</a>' in hero and "in a row" not in hero
    assert '<b>Anxiety</b><small>Day 1 of 7</small>' in _section(html, "lm-pl-th")


def test_continue_is_the_churchs_plan_when_nothing_else_runs(bible, fake, monkeypatch):  # noqa: F811
    _end_d1(fake)
    fake.t["member_plan_starts"] = []
    hero = _hero(_client(fake, monkeypatch).get("/my/bible?tab=plans").text)
    assert "Continue · Day 12 of 31" in hero and "With your church · Psalms 54–58; Proverbs 12" in hero
    assert 'href="/my/bible/psalms/54">Read day 12</a>' in hero


def test_no_plan_running_means_no_continue(bible, fake, monkeypatch):  # noqa: F811
    _end_d1(fake)
    fake.t["member_plan_starts"] = []
    fake.biz[tct.BIZ]["settings"].pop("reading_plan")
    html = _client(fake, monkeypatch).get("/my/bible?tab=plans").text
    assert "lm-pl-hero" not in html and "Continue" not in html
    assert "From Grace Fellowship" in html and 'id="lm-pl-th"' in html and 'id="lm-pl-bh"' in html


def test_the_churchs_devotionals_as_covers(bible, fake, monkeypatch):  # noqa: F811
    import member_app_photos as photos
    real = photos.assigned
    monkeypatch.setattr(photos, "assigned", lambda biz, key: (
        {"url": "https://example.test/rest.jpg", "look": "colour"} if key == f"devotional:{D1}" else real(biz, key)))
    html = _client(fake, monkeypatch).get("/my/bible?tab=plans").text
    sec = _section(html, "lm-pl-fh")
    assert 'id="lm-pl-fh">From Grace Fellowship</h2><a class="lm-more" href="/my/bible/plans?show=church">' in sec
    covers = re.findall(r'<a class="lm-pl-cv" href="([^"]+)">(.*?)</a>', sec)
    assert [h for h, _ in covers] == [f"/my/bible/plans/{D1}/3", f"/my/bible/plans/{D2}"]
    first, second = covers[0][1], covers[1][1]
    # the church's picture, drawn in its colour whatever look the spot keeps, the title in serif over it
    assert '<span class="lm-pl-art has-ph"><span class="mb-ph is-church "' in first and "rest.jpg" in first
    assert "<b>Seven Days of Rest</b>" in first and "<small>7 days · Devotional</small>" in first
    # no picture: a cover made of the church's colour, no stock art
    assert second.startswith('<span class="lm-pl-art is-made"><b>Psalms at Night</b></span>') and "<img" not in second
    assert "<small>21 days · Evening psalms</small>" in second


def test_the_topics_and_the_whole_bible(bible, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my/bible?tab=plans").text
    topics = _section(html, "lm-pl-th")
    assert "What are you walking through?" in topics
    tiles = re.findall(r'<a class="lm-pl-tp tp-(\w)" href="/my/bible/plans/(topic-\w+)">.*?<b>(\w+)</b>', topics)
    assert tiles == [("a", "topic-anxiety", "Anxiety"), ("b", "topic-healing", "Healing"), ("c", "topic-purpose", "Purpose"),
                     ("d", "topic-marriage", "Marriage"), ("e", "topic-money", "Money"), ("f", "topic-grief", "Grief")]
    assert "<img" not in topics                                                           # colour and an icon, no photos
    shelf = _section(html, "lm-pl-bh")
    covers = re.findall(r'<a class="lm-pl-cv" href="([^"]+)"><span class="lm-pl-art is-len"><b>(\d+)</b><small>days</small>'
                        r'</span><small>([^<]+)</small>', shelf)
    assert covers == [("/my/bible/plans/bible-year", "365", "The whole Bible"), ("/my/bible/plans/nt-260", "260", "The New Testament"),
                      ("/my/bible/plans/gospels-30", "30", "The Gospels"), ("/my/reading", "31", "Psalms and Proverbs")]
    assert '<small class="lm-pl-on">Day 5 of 30</small>' in shelf
    assert '<small class="lm-pl-on">With your church · day 12</small>' in shelf


# ─── failed reads ────────────────────────────────────────────────────


def test_a_failed_progress_read_leaves_its_pieces_out(bible, fake, monkeypatch):  # noqa: F811
    fake.down.add("devotional_progress")
    html = _client(fake, monkeypatch).get("/my/bible?tab=plans").text
    # no devotional with made-up days: Continue is her own plan, and the covers wait
    assert "Seven Days of Rest" not in html and "Continue · Day 5 of 30" in html
    assert 'id="lm-pl-fh"' not in html and "Nothing here" not in html


def test_failed_ticks_keep_continue_without_its_row(bible, fake, monkeypatch):  # noqa: F811
    _end_d1(fake)
    fake.down.add("reading_progress")
    hero = _hero(_client(fake, monkeypatch).get("/my/bible?tab=plans").text)
    assert "Continue · Day 5 of 30" in hero and "lm-pl-dots" not in hero and "in a row" not in hero


def test_a_failed_catalog_leaves_the_covers_out(bible, fake, monkeypatch):  # noqa: F811
    fake.down.add("devotionals")
    html = _client(fake, monkeypatch).get("/my/bible?tab=plans").text
    assert 'id="lm-pl-fh"' not in html and "Continue · Day 5 of 30" in html and 'id="lm-pl-th"' in html


# ─── reads ───────────────────────────────────────────────────────────

PLAN_TABLES = {"/devotionals", "/devotional_progress", "/member_plan_starts", "/reading_progress"}


def _gets(fake, c, path):
    fake.gets.clear()
    html = c.get(path).text
    return html, Counter(r.split("?")[0] for r in fake.gets)


def test_tapping_back_to_plans_reads_nothing(bible, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    _, first = _gets(fake, c, "/my/bible?tab=plans")
    assert {"/devotionals", "/devotional_progress", "/member_plan_starts"} <= set(first)
    _, again = _gets(fake, c, "/my/bible?tab=plans")
    assert not set(again) & PLAN_TABLES, again                                          # every plan read kept


def test_a_write_reads_afresh_on_any_server_copy(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_plans as mlp
    c = _app(fake, monkeypatch)
    c.get("/my/bible?tab=plans")
    # another server copy: its kept rows aren't forgotten by this write...
    monkeypatch.setattr(mlp, "forget", lambda *a: None)
    r = c.post("/my/bible/plans/start", data={"plan": "reading:topic-grief"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/bible/plans/topic-grief"
    assert f"{mlp.VERSION_COOKIE}=" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    # ...but the phone's new version passes them over
    html, reads = _gets(fake, c, "/my/bible?tab=plans")
    assert reads["/member_plan_starts"] == 1
    assert '<b>Grief</b><small>Day 1 of 7</small>' in _section(html, "lm-pl-th")


def test_the_owners_preview_reads_none_of_the_members_rows(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_plans as mlp
    assert mlp.starts("b", "c", preview=True) == {} and mlp.done_days("b", "c", preview=True) == {}
    assert mlp.read_days("b", "c", {"key": "gospels-30", "start": TODAY}, preview=True) == set()
    assert not fake.gets


# ─── a plan's page ───────────────────────────────────────────────────


def test_a_topic_plan_page_before_it_starts(bible, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my/bible/plans/topic-anxiety").text
    assert _body_class(html).split()[:2] == ["lm", "lm-push"]
    top = html[html.index('<header class="mb-top">'):html.index("</header>")]
    assert 'href="/my/bible?tab=plans"' in top                                          # back to Plans
    assert '<section class="lm-pp-top tp-a"' in html and "<small>Topic · Anxiety</small>" in html
    assert '<h1 id="lm-pp-h">When you&#x27;re anxious</h1>' in html and "7 days · about 1 minute a day" in html
    assert "Seven days in the passages people turn to" in html
    assert ('<form method="post" action="/my/bible/plans/start"><input type="hidden" name="plan" value="reading:topic-anxiety">'
            '<button class="lm-btn" type="submit">Start</button></form>') in html
    rows = re.findall(r'<li class="lm-pp-d">(.*?)</li>', html)
    assert len(rows) == 7 and 'action="/my/reading"' not in html                         # nothing to tick yet
    assert ('<a class="lm-pp-dt" href="/my/bible/1-peter/5?v=6-7"><b>Cast your cares on Him</b>'
            '<small>1 Peter 5:6-7 · Psalm 55:22</small></a>') in rows[0]


def test_start_tick_and_finish_a_topic_plan(bible, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    r = c.post("/my/bible/plans/start", data={"plan": "reading:topic-healing"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-healing"
    assert {"plan": "reading:topic-healing", "started_on": TODAY.isoformat()}.items() <= next(
        x for x in fake.t["member_plan_starts"] if x["plan"] == "reading:topic-healing").items()
    html = c.get("/my/bible/plans/topic-healing").text
    assert '<a class="lm-btn" href="/my/bible/psalms/147?v=3">Read day 1</a>' in html
    first = re.search(r'<li class="lm-pp-d is-now">(.*?)</li>', html).group(1)
    assert ('<input type="hidden" name="back" value="/my/bible/plans/topic-healing"><input type="hidden" name="plan" '
            'value="topic-healing"><button class="lm-pp-c" type="submit" aria-label="Day 1: mark as read" '
            'aria-pressed="false">1</button>') in first and "· today" in first
    shut = re.findall(r'<li class="lm-pp-d is-shut">(.*?)</li>', html)
    assert len(shut) == 6 and "opens " in shut[0] and "<form" not in "".join(shut)
    r = c.post("/my/reading", data={"day": "1", "read": "yes", "back": "/my/bible/plans/topic-healing",
                                    "plan": "topic-healing"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-healing?done=read"
    tick = next(x for x in fake.t["reading_progress"] if x["plan_key"] == "topic-healing")
    assert tick["day"] == 1 and tick["start_date"] == TODAY.isoformat() and tick["contact_id"] == tct.ANA
    html = c.get("/my/bible/plans/topic-healing?done=read").text
    assert 'class="lm-pp-c ok" type="submit" aria-label="Day 1: mark as not read" aria-pressed="true"' in html
    assert "Marked as read" in html
    # a day that isn't open can't be ticked
    r = c.post("/my/reading", data={"day": "2", "read": "yes", "plan": "topic-healing"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-healing?err=day"
    # every day read: finished
    for row in fake.t["member_plan_starts"]:
        if row["plan"] == "reading:topic-healing":
            row["started_on"] = (TODAY - timedelta(days=9)).isoformat()
    fake.t["reading_progress"] = [x for x in fake.t["reading_progress"] if x["plan_key"] != "topic-healing"]
    for d in range(1, 8):
        fake.add("reading_progress", business_id=tct.BIZ, contact_id=tct.ANA, plan_key="topic-healing",
                 start_date=(TODAY - timedelta(days=9)).isoformat(), day=d)
    import member_lumen_plans as mlp
    mlp.forget_everything()
    html = c.get("/my/bible/plans/topic-healing").text
    assert "<b>You finished it</b>" in html and "Read day" not in html
    # Stop goes back to the Bible tab's Plans
    r = c.post("/my/bible/plans/stop", data={"plan": "reading:topic-healing", "back": "tab"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible?tab=plans"
    assert not [x for x in fake.t["member_plan_starts"] if x["plan"] == "reading:topic-healing"]


def test_a_long_plan_lists_the_two_weeks_around_today(bible, fake, monkeypatch):  # noqa: F811
    start = TODAY - timedelta(days=99)
    fake.t.setdefault("reading_progress", [])
    fake.add("member_plan_starts", business_id=tct.BIZ, contact_id=tct.ANA, plan="reading:bible-year",
             started_on=start.isoformat())
    for d in (1, 2, 99):
        fake.add("reading_progress", business_id=tct.BIZ, contact_id=tct.ANA, plan_key="bible-year",
                 start_date=start.isoformat(), day=d)
    html = _client(fake, monkeypatch).get("/my/bible/plans/bible-year").text
    days = [int(n) for n in re.findall(r'aria-label="Day (\d+): mark as', html.split("<details")[0])]
    assert days == list(range(94, 101))                                                  # the week to today
    assert re.findall(r'<li class="lm-pp-d is-shut"><span class="lm-pp-c" aria-hidden="true">(\d+)</span>', html) == \
        [str(n) for n in range(101, 108)]                                                # the week ahead, shut
    assert '<a class="lm-btn" href="' in html and "Continue day 100" in html
    assert "14 days to catch up" in html.split("<details")[1]


def test_a_reading_plan_not_started_has_its_page(bible, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my/bible/plans/nt-260").text
    assert '<section class="lm-pp-top is-len"' in html and '<span class="lm-pp-n" aria-hidden="true">260</span>' in html
    assert "<small>Read the whole Bible</small>" in html and '<h1 id="lm-pp-h">The New Testament</h1>' in html
    assert 'name="plan" value="reading:nt-260"' in html
    assert len(re.findall(r'<li class="lm-pp-d">', html)) == 31 and "And on, a day at a time, to day 260." in html


def test_the_preview_saves_nothing_on_a_plans_page(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_plans as mlp

    class R:
        cookies, query_params = {}, {}
    import member_lumen
    monkeypatch.setattr(member_lumen, "page", lambda: True)
    html = mlp.render_plan(fake.business(), {}, R(), {"id": tct.ANA, "name": "Ana"}, "topic-money", None, None,
                           preview=True)
    assert '<button class="lm-btn" type="submit" disabled>Start</button>' in html and "Stop this plan" not in html


def test_a_failed_starts_read_saves_nothing_on_a_plans_page(bible, fake, monkeypatch):  # noqa: F811
    fake.down.add("member_plan_starts")
    r = _client(fake, monkeypatch).get("/my/bible/plans/topic-grief")
    assert r.status_code == 503 and "Your plan couldn't load just now, so nothing here will save." in r.text
    assert 'action="/my/bible/plans/start"' not in r.text and "Stop this plan" not in r.text


# ─── the CSS ─────────────────────────────────────────────────────────


def test_the_css_is_its_own_block_under_body_lm():
    import member_lumen_plans as mlp
    import member_lumen_ui as lm
    import member_lumen_fonts
    import member_mini
    parts = [t.template for t in lm.templates()]
    assert mlp.CSS in parts
    assert parts[-1] == member_lumen_fonts.template().template and parts[-2] == member_mini.CSS.template
    assert parts.index(mlp.CSS) < len(parts) - 3                                          # before share, mini, type
    rules = re.sub(r"/\*.*?\*/", "", mlp.CSS, flags=re.S)
    rules = re.sub(r"@media[^{]+\{", "", rules).replace("@supports", "")
    for sel in re.findall(r"([^{}]+)\{[^{}]*\}", rules):
        for one in sel.split(","):
            one = one.strip()
            if one and not one.startswith(("from", "to", "@keyframes")):
                assert one.startswith("body.lm"), one
    assert "#" not in re.sub(r"--pl-[ab]:#[0-9A-F]{6}|#fff\b|#FFE1A6|#141414|#2F7A4E|#3C8A5C", "", mlp.CSS)


def test_a_saved_write_never_fails_on_forgetting(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_plans as mlp

    def boom(*a):
        raise RuntimeError("kept rows")
    monkeypatch.setattr(mlp, "forget", boom)
    c = _app(fake, monkeypatch)
    r = c.post("/my/bible/plans/start", data={"plan": "reading:topic-money"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/bible/plans/topic-money"
    assert f"{mlp.VERSION_COOKIE}=" in r.headers["set-cookie"]
