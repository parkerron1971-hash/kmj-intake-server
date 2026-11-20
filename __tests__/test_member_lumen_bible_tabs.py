# __tests__/test_member_lumen_bible_tabs.py
#
# The Bible tab in Look 5.1 (member_lumen_bible, member_portal_bible): tapping
# Bible opens straight into reading, with Read · Devotional · Plans · Saved on
# top and a search button. Kevin, 2026-11-20: "when someone click bible the
# bible should open directly with devotional tabs at the top". Pins:
#   - off: every tab address is today's Bible tab, byte for byte, and no dot
#     cookie is written;
#   - the segmented control: real addresses (no script needed), the tab
#     you're on marked, the dot on Devotional while today's day of the
#     devotional on top is unread (not on the Devotional tab itself), kept
#     for the day in a cookie so a chapter page reads nothing for it; a
#     devotional's day clears it;
#   - reads: each tab reads only what it shows, every read one today's Bible
#     tab makes; a chapter page reads what today's reader reads;
#   - Devotional: the green card, this week's days from real progress, the
#     verse of the day with Share (kind=verse), more devotionals (real ones,
#     not the one on top, not one still to come);
#   - Plans: the plans running as rings with today's reading and Read, the
#     plans to start through today's start route;
#   - Saved: highlights, notes and saved verses, newest first, each back to
#     its verse; an empty state; a failed read said so;
#   - Search: the field, recently read, the books; a miss and a busy search
#     land here;
#   - the scripts: tabs replace the page in the history; the verse bar's
#     Share carries its verse; Listen is the phone's own voice; nothing is
#     sent anywhere;
#   - the CSS lives in the Bible's block, under body.lm, before the type.

import pathlib
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_app_ui as ui
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_pages import church, _client, _body_class  # noqa: F401  (church is a fixture)
from test_member_lumen_bible import bible, _reads, D1, D2  # noqa: F401  (bible is a fixture)

TODAY = date.today()
TABS = ("/my/bible", "/my/bible?tab=devotional", "/my/bible?tab=plans", "/my/bible?tab=saved", "/my/bible?tab=search")


def _seg(html):
    s = html[html.index('<div class="lm-bseg">'):]
    return s[:s.index("</nav>")]


def _dot_cookie(resp):
    import member_lumen_bible as mlb
    for h in resp.headers.get_list("set-cookie"):
        if h.startswith(mlb.DEVO_COOKIE + "="):
            return h
    return None


# ─── off is today's ──────────────────────────────────────────────────


def test_off_every_tab_address_is_todays_bible_tab(bible, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c = _client(fake, monkeypatch)
    c.get("/my/bible")
    today = c.get("/my/bible")
    assert "lm" not in _body_class(today.text).split() and 'class="lm-' not in today.text
    for path in TABS[1:]:
        r = c.get(path)
        assert r.text == today.text, path                                              # byte for byte
        assert _dot_cookie(r) is None
    assert _dot_cookie(c.get("/my/bible/john/1")) is None


# ─── the segmented control ───────────────────────────────────────────


@pytest.mark.parametrize("path,active", [("/my/bible", "Read"), ("/my/bible?tab=devotional", "Devotional"),
                                         ("/my/bible?tab=plans", "Plans"), ("/my/bible?tab=saved", "Saved"),
                                         ("/my/bible?tab=nonsense", "Read")])
def test_each_tab_is_a_real_address_with_its_segment_marked(bible, fake, monkeypatch, path, active):  # noqa: F811
    html = _client(fake, monkeypatch).get(path).text
    assert _body_class(html).split()[:3] == ["lm", "lm-tab", "pg-bible"]
    seg = _seg(html)
    assert re.findall(r'aria-current="page">(\w+)', seg) == [active]
    assert '<nav class="lm-bsegs" aria-label="Bible">' in seg
    assert '<nav class="mb-nav' in html                                                # the tab bar stays
    assert 'class="mb-back"' not in html                                               # a main tab: no back bar


def test_the_devotional_dot_and_its_cookie(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    c = _client(fake, monkeypatch)
    r = c.get("/my/bible")
    seg = _seg(r.text)
    # day 3 of the church's devotional is today's, and it isn't read
    assert '<a class="lm-bsg" href="/my/bible?tab=devotional">Devotional<span class="lm-nd" aria-hidden="true"></span>' in seg
    assert "(today's day isn't read yet)" in seg
    kept = _dot_cookie(r)
    assert kept.startswith(f"{mlb.DEVO_COOKIE}={TODAY.isoformat()}.1;")
    assert "Path=/my" in kept and "HttpOnly" in kept and "Secure" in kept and "SameSite=lax" in kept
    # not on the Devotional tab itself
    devo = c.get("/my/bible?tab=devotional").text
    assert 'class="lm-nd"' not in _seg(devo)
    # a chapter page: the dot from the cookie, nothing read for it
    _, reads = _reads(fake, c, "/my/bible/john/3")
    assert reads == Counter({"/bible_marks": 1})
    assert 'class="lm-nd"' in _seg(c.get("/my/bible/john/3").text)
    # opening the devotional's day clears it; the next tab asks again
    day = c.get(f"/my/bible/plans/{D1}/3")
    assert any(h.startswith(f'{mlb.DEVO_COOKIE}=""') or (h.startswith(f"{mlb.DEVO_COOKIE}=") and "Max-Age=0" in h)
               for h in day.headers.get_list("set-cookie"))
    assert 'class="lm-nd"' not in _seg(c.get("/my/bible/john/3").text)
    # read today's day: no dot, and the cookie says so
    fake.add("devotional_progress", business_id=tct.BIZ, contact_id=tct.ANA, devotional_id=D1, day=3,
             done_at=datetime.now(timezone.utc).isoformat(), checks=[], journal="")
    r = c.get("/my/bible")
    assert 'class="lm-nd"' not in _seg(r.text) and _dot_cookie(r).startswith(f"{mlb.DEVO_COOKIE}={TODAY.isoformat()}.0;")


def test_the_dot_cookie_only_counts_today():
    import member_lumen_bible as mlb
    assert mlb.dot_cookie(f"{TODAY.isoformat()}.1", TODAY) is True
    assert mlb.dot_cookie(f"{TODAY.isoformat()}.0", TODAY) is False
    assert mlb.dot_cookie(f"{(TODAY - timedelta(days=1)).isoformat()}.1", TODAY) is None
    for junk in ("", None, "1", f"{TODAY.isoformat()}.x", "garbage.1"):
        assert mlb.dot_cookie(junk, TODAY) is None
    assert mlb.dot_value(True, TODAY) == f"{TODAY.isoformat()}.1"


def test_a_kept_chapter_that_isnt_there_starts_like_a_first_reader(bible, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.cookies.set("sol_bible", "kjv|jude/9", path="/my")                                 # Jude has one chapter
    html = c.get("/my/bible").text
    assert 'data-book="PSA" data-ch="54"' in html and "Your church is reading" in html


def test_with_the_dot_kept_reading_reads_only_the_chapters_marks(bible, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.get("/my/bible")                                                                   # keeps the dot for today
    _, reads = _reads(fake, c, "/my/bible")
    assert reads == Counter({"/bible_marks": 1})


# ─── reads ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", TABS)
def test_every_tab_reads_nothing_todays_bible_tab_doesnt(bible, fake, monkeypatch, path):  # noqa: F811
    import member_lumen_bible as mlb
    c = _client(fake, monkeypatch)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    _, today = _reads(fake, c, "/my/bible")
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    c.cookies.delete(mlb.DEVO_COOKIE)
    c.get(path)
    c.cookies.delete(mlb.DEVO_COOKIE)                                                    # the dot asked for again
    fake.gets.clear()
    c.get(path)
    got = Counter(r.split("?")[0] for r in fake.gets)
    assert not got - today, (path, got - today)
    assert sum(got.values()) < sum(today.values()), (path, got, today)                  # less than today's tab


def test_the_devotional_tab_reads_one_devotionals_days(bible, fake, monkeypatch):  # noqa: F811
    import devotionals as dv
    real = dv.catalog
    # the catalog carries no days (the fake hands back whole rows)
    monkeypatch.setattr(dv, "catalog", lambda bid, **k: [{x: v for x, v in r.items() if x != "days"} for r in real(bid, **k)])
    c = _client(fake, monkeypatch)
    c.get("/my/bible?tab=devotional")
    fake.gets.clear()
    html = c.get("/my/bible?tab=devotional").text
    days = [g for g in fake.gets if g.startswith("/devotionals?id=eq.")]
    assert len(days) == 1 and D1 in days[0]                                              # only the one on top
    assert "Today: Unhurried" in html                                                    # its day, from that read


# ─── Devotional ──────────────────────────────────────────────────────


def test_the_devotional_tab(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_devotional as mld
    html = _client(fake, monkeypatch).get("/my/bible?tab=devotional").text
    card = html[html.index('<section class="lm-devo"'):]
    card = card[:card.index("</section>")]
    assert "Devotional · Day 3 of 7" in card and "Seven Days of <em>Rest</em>" in card and "Today: Unhurried" in card
    assert html.index('class="lm-bseg"') < html.index('class="lm-devo"')
    # this week, Monday to Sunday, from real progress
    week = html[html.index('<ol class="lm-week"'):html.index("</ol>")]
    cells = re.findall(r'<li class="lm-wd ?([\w-]*)">(.*?)</li>', week)
    assert len(cells) == 7
    monday = TODAY - timedelta(days=TODAY.weekday())
    start = TODAY - timedelta(days=2)
    for i, (cls, inner) in enumerate(cells):
        d = monday + timedelta(days=i)
        n = (d - start).days + 1
        if not 1 <= n <= 7:
            assert cls == "is-none" and "<b aria-hidden=\"true\"></b>" in inner
            continue
        assert f"<b>{n}</b><span>{d.strftime('%a')}</span>" in inner
        want = "is-done" if n in (1, 2) else ("is-today" if d == TODAY else "is-ahead")
        assert cls == want, (d, cls)
        if n <= 3:
            assert f'href="/my/bible/plans/{D1}/{n}"' in inner                         # open days are links
        else:
            assert "href=" not in inner                                                  # not open yet
    assert 'aria-current="date"' in week
    # the verse of the day, with Share as the share sheet's verse
    vod = html[html.index('aria-labelledby="lm-vod-h"'):]
    vod = vod[:vod.index("</section>")]
    share = re.search(r'<a class="lm-share lm-more lm-vodshare" href="/" data-share-kind="verse" '
                      r'data-share-title="([^"]+) · KJV" data-share-sub="“([^"]+)”" data-share-id="([0-9A-Z]{3}\.\d+\.\d+(?:-\d+)?)" '
                      r'data-share-text="“([^"]+)” ([^"]+) \(KJV\)" data-share-tr="kjv" aria-label="Share the verse of the day">', vod)
    assert share and "<" not in share.group(4) and share.group(5) == share.group(1)
    assert '<a class="lm-vod" href="/my/bible/' in vod and "King James Version" in vod
    # more devotionals: the church's others, real ones
    more = html[html.index('class="lm-mcovs"'):]
    more = more[:more.index("</div>")]
    assert "Psalms at Night" in more and "Seven Days of Rest" not in more and "7 days" not in more
    assert 'href="/my/bible/plans"' in html                                              # All
    import member_lumen_share as mls
    assert html.count(mls.js_url()) == 1 and '<h1 class="mp-sr">Devotional</h1>' in html   # the share sheet's script
    assert "data-devo-listen" not in html or mld.CARD_JS in html


def test_more_devotionals_leaves_out_one_still_to_come(bible, fake, monkeypatch):  # noqa: F811
    dev = next(r for r in fake.t["devotionals"] if r["id"] == D2)
    dev["starts_on"] = (TODAY + timedelta(days=5)).isoformat()
    html = _client(fake, monkeypatch).get("/my/bible?tab=devotional").text
    assert 'class="lm-mcovs"' not in html and "Psalms at Night" not in html


def test_a_church_with_no_devotionals_says_so_quietly(bible, fake, monkeypatch):  # noqa: F811
    fake.t["devotionals"] = []
    c = _client(fake, monkeypatch)
    html = c.get("/my/bible?tab=devotional").text
    assert 'class="lm-devo"' not in html and 'class="lm-week"' not in html and 'class="lm-mcovs"' not in html
    assert "When Grace Fellowship shares a devotional, it opens here" in html and 'class="lm-vod"' in html
    assert 'class="lm-nd"' not in c.get("/my/bible").text                               # nothing to be unread


# ─── Plans ───────────────────────────────────────────────────────────


def test_the_plans_tab(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    import reading_plans as rp
    html = _client(fake, monkeypatch).get("/my/bible?tab=plans").text
    plans = re.findall(r'<div class="lm-aplan">(.*?)</div>', html)
    assert len(plans) == 2                                                               # the church's, then hers
    church, mine = plans
    assert '<b>12</b>' in church and "With your church · day 12" in church and "Today: Psalms 54–58; Proverbs 12" in church
    assert 'href="/my/reading"' in church and 'href="/my/bible/psalms/54"' in church
    mins = mlb.chapters_minutes(rp.schedule("psalms-proverbs-31")[11], "kjv")
    assert f"About {mins} minutes" in church
    assert "The Gospels · day 5" in mine and 'href="/my/bible/plans/gospels-30"' in mine and ">Read</a>" in mine
    # the plans she hasn't started, through today's start route
    starts = re.findall(r'<form class="lm-pstart" method="post" action="/my/bible/plans/start"><input type="hidden" '
                        r'name="plan" value="reading:([\w-]+)">', html)
    assert starts == ["bible-year", "nt-260", "psalms-proverbs-31"]
    assert re.search(r"365 days · \d+ min a day", html)
    assert 'href="/my/bible/plans"' in html


def test_a_failed_plans_read_still_offers_the_plans(bible, fake, monkeypatch):  # noqa: F811
    fake.down.add("member_plan_starts")
    html = _client(fake, monkeypatch).get("/my/bible?tab=plans").text
    assert "Your plans couldn't load just now" in html
    assert "With your church · day 12" in html and html.count('class="lm-pstart"') == 4


def test_minutes_are_the_words_at_reading_pace():
    import bible_text as bt
    import member_lumen_bible as mlb
    words = sum(t.count(" ") + 1 for _, t in bt.chapter("PSA", 23, "kjv"))
    assert mlb.chapters_minutes([("PSA", 23, 23)], "kjv") == max(1, round(words / mlb.WPM))
    assert mlb.plan_title("The Gospels in 30 days") == "The Gospels"
    assert mlb.plan_title("Psalms and Proverbs in a month") == "Psalms and Proverbs"


# ─── Saved ───────────────────────────────────────────────────────────


def test_the_saved_tab(bible, fake, monkeypatch):  # noqa: F811
    now = datetime.now(timezone.utc)
    fake.add("bible_marks", business_id=tct.BIZ, contact_id=tct.ANA, book="PSA", chapter=23, verse=1, colour=None,
             note="", bookmarked=True, updated_at=(now - timedelta(days=30)).isoformat())
    html = _client(fake, monkeypatch).get("/my/bible?tab=saved").text
    rows = re.findall(r'<li><a class="lm-hlr" href="([^"]+)">(.*?)</a></li>', html)
    assert [h for h, _ in rows] == ["/my/bible/john/1#v5", "/my/bible/psalms/23#v1"]   # newest first, to the verse
    first = rows[0][1]
    assert '<i class="sw-gold" aria-hidden="true"></i>' in first and "And the light shineth in darkness" in first
    assert '<span class="lm-hlr-n">The light wins.</span>' in first and "John 1:5 · highlighted today" in first
    old = rows[1][1]
    assert '<i class="is-plain" aria-hidden="true"></i>' in old and "Psalm 23:1 · saved " in old
    assert 'href="/my/bible/notes"' in html and "Only you can see these." in html


def test_saved_empty_and_failed(bible, fake, monkeypatch):  # noqa: F811
    fake.t["bible_marks"] = []
    html = _client(fake, monkeypatch).get("/my/bible?tab=saved").text
    assert "Nothing saved yet" in html and "Tap any verse while you read" in html and 'class="lm-hls"' not in html
    fake.down.add("bible_marks")
    html = _client(fake, monkeypatch).get("/my/bible?tab=saved").text
    assert "couldn't load just now" in html and "Nothing saved yet" not in html


def test_when_a_verse_was_saved():
    import member_lumen_bible as mlb
    d = datetime(2026, 11, 20, 15, tzinfo=timezone.utc)
    assert mlb._when(d.isoformat(), date(2026, 11, 20)) == "today"
    assert mlb._when(d.isoformat(), date(2026, 11, 21)) == "yesterday"
    assert mlb._when(d.isoformat(), date(2026, 11, 24)) == "Friday"
    assert mlb._when(d.isoformat(), date(2026, 12, 20)) == "Nov 20"
    assert mlb._when(d.isoformat(), date(2027, 1, 20)) == "Nov 20, 2026"
    assert mlb._when("not a date", date(2026, 11, 20)) == ""


# ─── Search ──────────────────────────────────────────────────────────


def test_the_search_button_and_its_page(bible, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.cookies.set("sol_bible", "kjv|romans/8~psalms/23", path="/my")
    _, reads = _reads(fake, c, "/my/bible?tab=search")
    assert not reads                                                                     # the dot from its cookie, nothing else
    html = c.get("/my/bible?tab=search").text
    assert 'href="/my/bible?tab=search" aria-label="Search the Bible" aria-current="page"' in html
    assert not re.findall(r'class="lm-bsg"[^>]*aria-current', html)                    # no tab marked
    assert '<form class="lm-field" method="get" action="/my/bible" role="search">' in html and " autofocus" in html
    recent = html[html.index('class="bb-recent"'):]
    assert re.findall(r'<a href="(/my/bible/[\w/-]+)">', recent[:recent.index("</nav>")]) == [
        "/my/bible/romans/8", "/my/bible/psalms/23"]
    assert 'href="/my/bible/books?t=ot"' in html and 'href="/my/bible/books?t=nt"' in html


def test_a_miss_and_a_busy_search_land_on_the_search_page(bible, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    miss = c.get("/my/bible?q=zzzzqqq").text
    assert "We couldn't find that passage or word" in miss and 'value="zzzzqqq"' in miss
    assert 'aria-label="Search the Bible" aria-current="page"' in miss
    assert c.get("/my/bible?q=John 3:16", follow_redirects=False).headers["location"] == "/my/bible/john/3?v=16#v16"
    hits = c.get("/my/bible?q=shepherd").text
    assert 'class="bb-hits lm-hits"' in hits                                            # today's results page
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow", lambda *a, **k: False)
    fake.gets.clear()
    slow = c.get("/my/bible?q=shepherd").text
    assert "That's a lot of searching at once" in slow and not fake.gets               # nothing read for it


# ─── the reader's Look 5.1 moments ───────────────────────────────────


def test_a_verse_share_is_the_share_contracts():
    """kind=verse, the church's own address, the story picture's id
    (BOOK.CH.V[-W]), the words for the message, the translation; escaped."""
    import member_lumen_bible as mlb
    assert mlb.VERSE_HREF == "/"
    assert mlb.verse_id("Lamentations 3:22-23", "kjv") == "LAM.3.22-23" and mlb.verse_id("1 John 4:19", "kjv") == "1JO.4.19"
    assert mlb.verse_id("Psalm 23", "kjv") == "" and mlb.verse_id("nothing", "kjv") == ""
    html = mlb.verse_share("John 3:16", 'He said "<b>"', "web", "JOH.3.16")
    assert html.startswith('<a class="lm-share" href="/" data-share-kind="verse" data-share-title="John 3:16 · WEB"')
    assert 'data-share-id="JOH.3.16"' in html and 'data-share-tr="web"' in html and "<b>" not in html
    assert 'data-share-text="“He said &quot;&lt;b&gt;&quot;” John 3:16 (WEB)"' in html
    long = mlb.verse_share("Esther 8:9", "word " * 60, "kjv")
    assert 'data-share-sub="“' in long and "…”" in long and "data-share-id" not in long


def test_the_scripts_send_nothing_and_keep_the_history_clean():
    import member_lumen_bible as mlb
    seg, read = mlb.SEG_JS, mlb.READ_JS
    assert "location.replace(a.href)" in seg and "prefers-reduced-motion: reduce" in seg
    assert "e.metaKey||e.ctrlKey" in seg                                                 # a new tab still opens one
    for js in (seg, read):
        assert "fetch(" not in js and "XMLHttpRequest" not in js and "sendBeacon" not in js
    # Listen: the phone's own voice, shown only where it can speak, verse by verse, stopped on leaving
    assert "window.speechSynthesis" in read and "SpeechSynthesisUtterance" in read and "say.hidden=false" in read
    assert "pagehide" in read and "ss.cancel()" in read
    # Share: the verse rides on the share link; the phone's own share only when no share sheet took it
    assert "data-share-title" in read and "data-share-id" in read and "data-share-text" in read and "MutationObserver" in read


def test_the_tabs_css_is_the_bibles_block_before_the_type():
    import member_lumen_bible as mlb
    import member_lumen_fonts as lmf
    css = mlb.CSS
    text = ui.sheet("lumen")[0]
    assert text.index(css.strip()) < text.index(lmf.css().strip()[:200])
    for cls in ("lm-bseg", "lm-bsg", "lm-nd", "lm-rbar", "lm-ver", "lm-verpop", "lm-rnav", "lm-week", "lm-wd", "lm-vod",
                "lm-mcovs", "lm-aplan", "lm-ringp", "lm-pstart", "lm-pc", "lm-hls", "lm-hlr", "lm-saved0"):
        assert f".{cls}" in css, cls
    assert "body.lm.lm-tab .bb-dock{bottom:calc(76px" in css                            # the verse bar over the tab bar
    assert "body.lm.lm-tab.lm-mini-pad .bb-dock{bottom:calc(158px" in css               # and over the mini player
    assert "querySelector('.lm-mini')" in mlb.READ_JS
    assert "body.lm.lm-dark{--lm-wk:#BDE3C2;" in css and "body.lm.lm-auto{--lm-wk:#BDE3C2;" in css
    motion = css[css.index("@media (prefers-reduced-motion:no-preference)"):]
    assert "body.lm .lm-bsg{transition:" in motion
    assert "$" not in css
