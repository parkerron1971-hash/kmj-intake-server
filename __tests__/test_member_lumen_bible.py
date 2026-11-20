# __tests__/test_member_lumen_bible.py
#
# The Bible (with its reader and plans) and Classes in the member app's new
# look (member_lumen_bible, member_lumen_classes), behind MEMBER_LUMEN.
# Pins:
#   - off: every Bible and Classes page is today's markup (no Lumen class);
#   - on (Look 5.1): the Bible tab opens straight into the reader, Read ·
#     Devotional · Plans · Saved on top (test_member_lumen_bible_tabs), at the
#     chapter read last or today's reading of the church's plan; it reads
#     less than today's tab and nothing it doesn't;
#   - the reader: the tab bar stays, the chapter and translation pills, Aa,
#     Listen, the moon, the chapter's number large, the highlighter (today's
#     reader script), the chapters around it at the end; same reads as today;
#   - plans, a reading plan, search, the book picker, highlights & notes;
#   - Classes: the next class night, the path, your classes, classes to join,
#     from the same read;
#   - Lumen Next: night reading (a cookie the server reads: the page arrives
#     dark, the phone's bar with it; today's reader ignores it), the line of
#     how far you've read, the ink sweep, Make a card (the church's photo and
#     logo, nothing sent), the certificate moment on a finished course; no
#     new reads;
#   - the CSS lives in its own blocks, in the served sheet, under body.lm.

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

TODAY = date.today()
D1, D2 = "00000000-0000-4000-8000-0000000009a1", "00000000-0000-4000-8000-0000000009a2"


@pytest.fixture
def bible(church, fake, monkeypatch):  # noqa: F811
    """Ana's Bible life at the made-up church: a devotional the church dated
    (day 3 of 7, two days done), one to start any time, a plan of her own,
    the church's reading plan, and a highlight with a note."""
    now = datetime.now(timezone.utc)
    for t in ("devotionals", "devotional_progress", "member_plan_starts", "bible_marks"):
        fake.t.setdefault(t, [])
    days = [{"title": t, "scripture": "Psalm 23:2", "body": "Rest. " * 200} for t in
            ("Come Away", "Still Waters", "Unhurried", "Sabbath", "Enough", "Breathe", "Home")]
    fake.add("devotionals", id=D1, business_id=tct.BIZ, title="Seven Days of Rest", kind="Devotional",
             author="Pastor James", about="", practices=[], day_count=7, voice="grace", status="published",
             starts_on=(TODAY - timedelta(days=2)).isoformat(), published_at=now.isoformat(),
             updated_at=now.isoformat(), days=days, audio=None)
    fake.add("devotionals", id=D2, business_id=tct.BIZ, title="Psalms at Night", kind="Evening psalms", author="",
             about="", practices=[], day_count=21, voice="grace", status="published", starts_on=None,
             published_at=(now - timedelta(days=9)).isoformat(), updated_at=now.isoformat(),
             days=[{"title": "Evening", "scripture": "Psalm 4:8", "body": "Sleep."}] * 21, audio=None)
    for d in (1, 2):
        fake.add("devotional_progress", business_id=tct.BIZ, contact_id=tct.ANA, devotional_id=D1, day=d,
                 done_at=now.isoformat(), checks=[], journal="")
    fake.add("member_plan_starts", business_id=tct.BIZ, contact_id=tct.ANA, plan="reading:gospels-30",
             started_on=(TODAY - timedelta(days=4)).isoformat())
    fake.add("bible_marks", business_id=tct.BIZ, contact_id=tct.ANA, book="JOH", chapter=1, verse=5, colour="gold",
             note="The light wins.", bookmarked=True, updated_at=now.isoformat())
    fake.biz[tct.BIZ]["settings"]["reading_plan"] = {"key": "psalms-proverbs-31",
                                                     "start": (TODAY - timedelta(days=11)).isoformat()}
    return church


def _reads(fake, c, path):  # noqa: F811
    c.get(path)                 # warm what's kept
    fake.gets.clear()
    html = c.get(path).text
    return html, Counter(r.split("?")[0] for r in fake.gets)


def _same_reads(fake, monkeypatch, path):  # noqa: F811
    c = _client(fake, monkeypatch)
    on, reads_on = _reads(fake, c, path)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    off, reads_off = _reads(fake, c, path)
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    assert reads_on == reads_off, (reads_on - reads_off, reads_off - reads_on)
    return on, off


# ─── off is today's look ─────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/my/bible", "/my/bible/john/1", "/my/bible/plans", "/my/bible/notes",
                                  "/my/bible/books", "/my/bible?q=shepherd", "/my/reading", "/my/classes",
                                  "/my/bible/plans/gospels-30"])
def test_off_every_bible_and_classes_page_is_todays(bible, fake, monkeypatch, path):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = _client(fake, monkeypatch).get(path).text
    assert "lm" not in _body_class(html).split()
    assert 'class="lm-' not in html and ui.sheet_url("lumen") not in html


# ─── the Bible tab ───────────────────────────────────────────────────


def test_the_bible_tab_opens_into_reading(bible, fake, monkeypatch):  # noqa: F811
    """Look 5.1: /my/bible is the reader (no "The Word" page in between),
    with Read · Devotional · Plans · Saved on top; it reads less than
    today's Bible tab, and nothing today's tab doesn't."""
    c = _client(fake, monkeypatch)
    on, reads_on = _reads(fake, c, "/my/bible")
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    _, reads_off = _reads(fake, c, "/my/bible")
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    assert not reads_on - reads_off, reads_on - reads_off
    assert _body_class(on).split()[:2] == ["lm", "lm-tab"]
    assert '<nav class="mb-nav' in on                                                  # the tab bar stays
    seg = on[on.index('<div class="lm-bseg">'):]
    seg = seg[:seg.index("</div>")]
    assert re.findall(r'<a class="lm-bsg" href="([^"]+)"', seg) == [
        "/my/bible", "/my/bible?tab=devotional", "/my/bible?tab=plans", "/my/bible?tab=saved"]
    assert '<a class="lm-bsg" href="/my/bible" aria-current="page">Read</a>' in seg
    assert 'href="/my/bible?tab=search" aria-label="Search the Bible"' in seg
    # nothing read yet, the church reading its plan: today's reading, said so (once: then it's where she left off)
    first = _client(fake, monkeypatch).get("/my/bible")
    assert 'class="bb-read lm-read" data-book="PSA" data-ch="54"' in first.text
    assert "Your church is reading Psalms 54–58; Proverbs 12 today." in first.text
    assert "kjv|psalms/54" in first.headers["set-cookie"]
    assert 'data-book="PSA" data-ch="54"' in on and "Your church is reading" not in on
    assert "The <em>Word</em>" not in on and 'class="lm-cont"' not in on


def test_the_bible_tab_picks_up_where_you_left_off(bible, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.cookies.set("sol_bible", "web|romans/8~psalms/23", path="/my")
    html = c.get("/my/bible").text
    assert 'class="bb-read lm-read" data-book="ROM" data-ch="8" data-tr="web"' in html
    assert '<a class="lm-pill lm-chpill" href="/my/bible/romans"' in html and "Romans 8" in html
    ver = html[html.index('<details class="lm-ver">'):html.index("</details>")]
    assert '<summary aria-label="Translation: World English Bible">WEB</summary>' in ver
    assert '<a href="/my/bible?t=web" aria-current="true">' in ver                     # back to the Bible tab itself
    assert "Your church is reading" not in html


def test_a_failed_devotionals_read_leaves_the_rest(bible, fake, monkeypatch):  # noqa: F811
    import devotionals as dv

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(dv, "catalog", boom)
    c = _client(fake, monkeypatch)
    read = c.get("/my/bible").text
    assert 'class="bb-read lm-read"' in read and 'class="lm-nd"' not in read          # reading still works, no dot
    devo = c.get("/my/bible?tab=devotional").text
    assert "devotionals couldn't load just now" in devo and 'class="lm-vod"' in devo   # the verse still shows
    plans = c.get("/my/bible?tab=plans").text
    assert "Today: Psalms 54–58; Proverbs 12" in plans and 'href="/my/reading"' in plans


# ─── the reader ──────────────────────────────────────────────────────


def test_the_reader_is_the_read_tab(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    import member_portal_bible as mpb
    on, off = _same_reads(fake, monkeypatch, "/my/bible/john/1")
    assert _body_class(on).split()[:2] == ["lm", "lm-tab"]
    assert '<nav class="mb-nav' in on                                                  # the tab bar stays while reading
    assert '<a class="lm-bsg" href="/my/bible" aria-current="page">Read</a>' in on
    bar = on[on.index('<div class="lm-rbar">'):on.index('<h1 class="lm-chap">')]
    assert '<a class="lm-pill lm-chpill" href="/my/bible/john"' in bar and "John 1" in bar   # opens the book picker
    assert '<summary aria-label="Translation: King James Version">KJV</summary>' in bar
    assert 'href="/my/bible/john/1?t=web"' in bar and 'href="/my/bible/john/1?t=asv"' in bar
    assert 'id="bb-aa"' in bar and 'aria-label="Text size and font"' in bar
    assert re.search(r'id="lm-say" aria-pressed="false" aria-label="Listen to this chapter" hidden>', bar)
    assert 'id="lm-moon"' in bar
    assert '<b aria-hidden="true">1</b><span aria-hidden="true">John</span>' in on
    # Today's reader: tap a verse, the bar, its marks.
    assert mpb.READER_JS in on and mlb.READ_JS in on and mlb.SEG_JS in on
    for act in ("note", "copy", "bookmark", "clear", "close", "save-note", "card"):
        assert f'data-act="{act}"' in on, act
    # Share opens the new look's share sheet with the tapped verse (member_lumen_share).
    assert 'class="lm-share" data-share-kind="verse" data-share-from="reader"' in on and 'data-act="share"' not in on
    assert 'class="bb-v hl-gold" data-v="5"' in on and "bb-nm" in on and "bb-bm" in on
    # Share is the shared share sheet's: a verse
    dock = on[on.index('id="bb-dock"'):on.index('id="bb-note"')]
    assert ('<a class="lm-share lm-selshare" href="/" data-share-kind="verse" data-share-from="reader" '
            'data-share-title="" data-share-sub="" data-share-id="" data-share-text="" data-share-tr="kjv">') in dock
    assert 'data-act="share"' not in on                                                # the sheet's, not the old dock's
    # Aa holds the size and the font; the translation is its own pill
    panel = on[on.index('id="bb-aa-panel"'):]
    panel = panel[:panel.index("</div></div>")]
    assert 'data-size="up"' in panel and 'data-font="sans"' in panel and "?t=" not in panel
    nav = on[on.index('class="lm-rnav"'):]
    nav = nav[:nav.index("</nav>")]
    assert 'href="/my/bible/luke/24"' in nav and 'href="/my/bible/john/2"' in nav
    assert "lm-chnav" not in on and "lm-mid" not in on


def test_the_preview_reader_keeps_the_translation_without_aa(bible, fake, monkeypatch):  # noqa: F811
    fake.down.add("bible_marks")
    html = _client(fake, monkeypatch).get("/my/bible/john/1").text
    assert 'id="bb-aa"' not in html and "couldn't load" in html and 'id="bb-dock"' not in html
    assert '<details class="lm-ver">' in html and 'href="/my/bible/john/1?t=asv"' in html
    assert 'id="lm-say"' in html                                                       # Listen reads it all the same


# ─── Lumen Next: the reader at night, the ink, Make a card ────────────


def test_night_reading_arrives_dark_from_its_cookie(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    c = _client(fake, monkeypatch)
    day = c.get("/my/bible/john/1").text
    assert "lm-dark" not in _body_class(day).split()
    assert '<meta name="theme-color" content="#ffffff">' in day
    bar = day[day.index('<div class="lm-rbar">'):day.index('<h1 class="lm-chap">')]
    assert 'id="lm-moon"' in bar and 'aria-pressed="false"' in bar and 'aria-label="Night reading"' in bar
    assert f'data-night="{mlb.NIGHT_BG}"' in bar and 'data-day="#ffffff"' in bar
    seg = day[day.index('<div class="lm-bseg">'):day.index('<div class="lm-rbar">')]
    assert '<span class="lm-rprog" aria-hidden="true"></span></div>' in seg            # how far you've read
    assert mlb.READER_MORE_JS in day and "lm_night=" in mlb.READER_MORE_JS and "Path=/my" in mlb.READER_MORE_JS
    c.cookies.set(mlb.NIGHT_COOKIE, "1")
    night = c.get("/my/bible/john/1").text
    assert _body_class(night).split()[:2] == ["lm", "lm-tab"] and "lm-dark" in _body_class(night).split()
    assert f'<meta name="theme-color" content="{mlb.NIGHT_BG}">' in night
    assert 'id="lm-moon" aria-pressed="true"' in night
    assert "lm-dark" in _body_class(c.get("/my/bible").text).split()                  # Read is the reader
    # only the reader reads it: the other tabs and Home stay white
    for p in ("/my/bible?tab=devotional", "/my/bible?tab=plans", "/my/bible?tab=saved", "/my/bible?tab=search", "/my"):
        assert "lm-dark" not in _body_class(c.get(p).text).split(), p
    # a reader that can't edit (a preview, marks down) keeps the moon
    fake.down.add("bible_marks")
    assert 'id="lm-moon"' in c.get("/my/bible/john/1").text


def test_night_reading_reads_nothing_new_and_today_ignores_it(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    c = _client(fake, monkeypatch)
    c.cookies.set(mlb.NIGHT_COOKIE, "1")
    _, reads_on = _reads(fake, c, "/my/bible/john/1")
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    off_night, reads_off = _reads(fake, c, "/my/bible/john/1")
    assert reads_on == reads_off
    c.cookies.clear()
    assert c.get("/my/bible/john/1").text == off_night                                 # byte for byte
    assert "lm-moon" not in off_night and "lm-vc" not in off_night and "lm-dark" not in off_night


def test_make_a_card_from_a_verse(bible, fake, monkeypatch):  # noqa: F811
    import member_app_photos as photos
    import member_lumen_bible as mlb
    monkeypatch.setattr(photos, "photos", lambda b, site, limit=None: ["/public/site-assets/grace/sanctuary.jpg"])
    html = _client(fake, monkeypatch).get("/my/bible/john/1").text
    dock = html[html.index('id="bb-dock"'):html.index('id="bb-note"')]
    assert 'data-act="card" aria-haspopup="dialog"' in dock and "Make a card" in dock
    sheet = html[html.index('<div class="lm-vc" id="lm-vc" hidden'):]
    sheet = sheet[:sheet.index('<script type="application/json" id="bb-marks">')]
    assert 'data-church="Grace Fellowship"' in sheet and 'data-mark="GF"' in sheet
    assert 'data-photo="/public/site-assets/grace/sanctuary.jpg"' in sheet
    assert 'role="dialog" aria-modal="true" aria-labelledby="lm-vc-t"' in sheet
    assert '<canvas class="lm-vc-cv" width="1080" height="1350"' in sheet
    assert re.findall(r'data-look="(\w+)"', sheet) == ["ivory", "photo", "night", "church"]
    assert 'aria-checked="true" data-look="ivory"' in sheet
    assert "Nothing is sent anywhere" in sheet and 'data-vc="share"' in sheet and 'data-vc="save"' in sheet
    # the card is drawn on the phone: no address to send it to, no form
    js = mlb.READER_MORE_JS
    assert "fetch(" not in js and "XMLHttpRequest" not in js and "navigator.share" in js and "toBlob" in js
    assert "crossOrigin='anonymous'" in js and "getImageData" in js                    # a picture that won't be read is left out
    # no church photo: no Photo look
    monkeypatch.setattr(photos, "photos", lambda b, site, limit=None: [])
    html = _client(fake, monkeypatch).get("/my/bible/john/1").text
    sheet = html[html.index('id="lm-vc"'):]
    assert 'data-photo=""' in sheet and 'data-look="photo"' not in sheet
    # a reader that can't edit has no verse to pick, so no card
    fake.down.add("bible_marks")
    assert 'id="lm-vc"' not in _client(fake, monkeypatch).get("/my/bible/john/1").text


def test_the_ink_sweeps_and_rests_when_motion_is_reduced():
    import member_lumen_bible as mlb
    css = mlb.CSS
    assert "body.lm .lm-read .bb-v{--hlc:transparent;" in css and "background-size:0% 100%;" in css
    assert "body.lm .lm-read .bb-v.hl-gold{--hlc:" in css
    motion = css[css.index("@media (prefers-reduced-motion:no-preference){\n  body.lm .lm-read .bb-v{"):]
    assert "transition:background-size .9s" in motion[:200]
    # the reader's warm night is the reader's (and a devotional's day's); the rest of a dark page is the look's
    assert "body.lm.lm-dark:has(.lm-read),body.lm.lm-dark:has(.lm-dd){" in css and "color-scheme:dark" in css
    assert "body.lm.lm-auto:has(.lm-read),body.lm.lm-auto:has(.lm-dd){" in css      # Same as my phone, at night


# ─── plans, a reading plan, search, books, notes ─────────────────────


def test_plans_and_devotionals(bible, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my/bible/plans").text
    assert "Plans &amp; <em>devotionals</em>" in html
    assert re.search(r'<nav class="lm-chips" aria-label="Show"><a href="/my/bible/plans\?show=all" aria-current=page>', html)
    assert "This week at Grace Fellowship" in html and "Read day 3" in html
    assert "Psalms at Night" in html
    assert html.count('action="/my/bible/plans/start"') == 3                         # the plans she hasn't started
    assert "Yours" in html and "Catch up" in html


def test_a_reading_plan_is_under_the_bible(bible, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my/reading").text
    assert _body_class(html).split()[:2] == ["lm", "lm-push"]
    top = html[html.index('<header class="mb-top">'):html.index("</header>")]
    assert 'class="mb-back" href="/my/bible"' in top
    assert "in a <em>month</em>" in html and "of 31 days read" in html
    assert html.count('class="lm-circle"') >= 7 and 'action="/my/reading"' in html
    assert "to catch up" in html
    own = _client(fake, monkeypatch).get("/my/bible/plans/gospels-30").text
    assert 'href="/my/bible/plans"' in own and "Stop this plan" in own and 'name="plan" value="gospels-30"' in own


def test_search_books_and_notes(bible, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    search = c.get("/my/bible?q=shepherd").text
    assert 'class="lm-field"' in search and 'class="bb-hits lm-hits"' in search and "verses with" in search
    books = c.get("/my/bible/books?t=nt").text
    assert "Choose a <em>book</em>" in books and 'id="bk-q"' in books and 'details class="bk"' in books
    notes = c.get("/my/bible/notes").text
    assert "Highlights &amp; <em>notes</em>" in notes and "The light wins." in notes


# ─── Classes ─────────────────────────────────────────────────────────


@pytest.fixture
def classes(church, monkeypatch):  # noqa: F811
    import member_portal_classes as mcl
    tue = TODAY + timedelta(days=(1 - TODAY.weekday()) % 7 or 7)
    data = {"tz": "UTC",
            "programs": [{"id": "p1", "title": "Foundations Path", "finish_title": "Commissioning night",
                          "finish_at": f"{(TODAY + timedelta(days=60)).isoformat()}T19:00:00+00:00",
                          "tracks": [{"course_id": "c0", "title": "Foundations Path: Welcome", "state": "done", "token": "t0"},
                                     {"course_id": "c1", "title": "Foundations Path: Belong", "state": "now", "token": "t1"},
                                     {"course_id": "c3", "title": "Foundations Path: Grow", "state": "open"},
                                     {"course_id": "c4", "title": "Foundations Path: Serve", "state": "later"}]}],
            "mine": [{"course_id": "c0", "title": "Foundations Path: Welcome", "program": "Foundations Path",
                      "status": "completed", "certificate": True, "total": 3, "done": 3, "token": "t0"},
                     {"course_id": "c1", "title": "Foundations Path: Belong", "program": "Foundations Path",
                      "status": "active", "total": 4, "done": 2, "token": "t1", "teacher": "Pastor James",
                      "next": {"starts_at": f"{tue.isoformat()}T19:00:00+00:00", "title": "Lesson 3: Life Together"}},
                     {"course_id": "c9", "title": "Marriage Matters", "status": "active", "total": 6, "done": 1,
                      "token": "t9"}],
            "open": [{"course_id": "00000000-0000-4000-8000-0000000009c2", "title": "Bible Basics", "lessons": 6,
                      "teacher": "Dana Wells"}]}
    monkeypatch.setattr(mcl, "classes_for", lambda b, me: data)
    return data


def test_classes_is_an_academy(classes, fake, monkeypatch):  # noqa: F811
    on, off = _same_reads(fake, monkeypatch, "/my/classes")
    assert _body_class(on).split()[:2] == ["lm", "lm-push"]
    assert "Keep <em>growing</em>" in on and "lm-crest" in on
    night = on[on.index('class="lm-night"'):]
    night = night[:night.index("</section>")]
    assert "Next class · " in night and "Lesson 3: Life Together" in night
    assert "Foundations Path · Belong · with Pastor James" in night and "Open the lesson" in night
    path = on[on.index('class="lm-path"'):]
    path = path[:path.index("</ol>")]
    states = re.findall(r'class="lm-step is-(\w+)"', path)
    assert states == ["done", "now", "open", "later", "finish"]
    assert "Finished · certificate earned" in path and "2 of 4 lessons" in path
    assert 'action="/my/classes/join"' in path and "Commissioning night" in path
    assert "Your path" in on and "Foundations Path" in on
    # Your classes: only the ones not on the path.
    mine = on[on.index('id="lm-mine-h"'):]
    mine = mine[:mine.index("</section>")]
    assert "Marriage Matters" in mine and "Belong" not in mine
    assert "Classes you can join" in on and "Bible Basics" in on
    assert "Joining puts the class here" in on
    assert "Academy" not in on                                                       # no name a church didn't choose


def test_classes_failed_and_empty(church, fake, monkeypatch):  # noqa: F811
    import member_portal_classes as mcl
    monkeypatch.setattr(mcl, "classes_for", lambda b, me: None)
    assert "Classes couldn't load just now" in _client(fake, monkeypatch).get("/my/classes").text
    monkeypatch.setattr(mcl, "classes_for", lambda b, me: {"tz": "UTC", "mine": [], "programs": [], "open": []})
    html = _client(fake, monkeypatch).get("/my/classes").text
    assert "No classes to join <em>right now</em>" in html
    assert 'id="lm-cert"' not in html and "lm-certs" not in html


def test_a_finished_course_has_its_certificate_moment(classes, fake, monkeypatch):  # noqa: F811
    import json
    import member_lumen_classes as mlc
    on, off = _same_reads(fake, monkeypatch, "/my/classes")
    # the finished course on the path keeps Open and gains Certificate
    path = on[on.index('class="lm-path"'):]
    path = path[:path.index("</ol>")]
    done = path[path.index('class="lm-step is-done"'):path.index('class="lm-step is-now"')]
    assert 'class="lm-stepacts"' in done and ">Open<" in done
    assert 'data-cert="c0" aria-haspopup="dialog" aria-describedby="lm-step-c0"' in done and "Certificate</button>" in done
    assert "data-cert=" not in path[path.index('class="lm-step is-now"'):]           # only finished ones
    # what the moment needs, from the same read
    data = json.loads(on.split('<script type="application/json" id="lm-certs">', 1)[1].split("</script>", 1)[0])
    assert data["done"] == [{"id": "c0", "title": "Foundations Path: Welcome", "total": 3, "code": ""}]
    assert data["active"] == ["c1", "c9"] and data["church"] == "Grace Fellowship" and data["who"]
    box = on[on.index('<div class="lm-cert" id="lm-cert" hidden>'):]
    assert 'role="dialog" aria-modal="true" aria-labelledby="lm-cert-t"' in box and "Course complete" in box
    assert 'href="#lm-copen-h" data-cert-x>Next course</a>' in box                     # there are classes to join
    assert mlc.CERT_JS in on and "localStorage" in mlc.CERT_JS and "Academy" not in on
    assert "lm-cert" not in off and "data-cert" not in off
    # a real certificate code shows; a course off the path gets the button in Your classes
    classes["mine"][0]["certificate"] = "GF-2026-0042"
    classes["mine"][2].update(status="completed", done=6)
    classes["open"] = []
    html = _client(fake, monkeypatch).get("/my/classes").text
    data = json.loads(html.split('id="lm-certs">', 1)[1].split("</script>", 1)[0])
    assert [c["code"] for c in data["done"]] == ["GF-2026-0042", ""] and data["active"] == ["c1"]
    mine = html[html.index('id="lm-mine-h"'):]
    assert 'data-cert="c9"' in mine[:mine.index("</section>")]
    assert '<button type="button" class="lm-btn" data-cert-x>Done</button>' in html  # nothing to join


# ─── the look ────────────────────────────────────────────────────────


def test_the_pages_css_is_in_the_served_sheet_in_its_own_blocks():
    import member_lumen_bible as mlb
    import member_lumen_classes as mlc
    import member_lumen_ui as lm
    text = ui.sheet("lumen")[0]
    assert mlb.CSS.strip() in text and mlc.CSS.strip() in text
    assert lm.css().startswith(lm._CSS.template)
    for block in (mlb.CSS, mlc.CSS):
        body = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
        # a motion's steps are named, not selected (lm- names, each block its own)
        names = re.findall(r"@keyframes\s+([\w-]+)", body)
        assert all(n.startswith("lm-") for n in names), names
        body = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", body)
        body = re.sub(r"@media[^{]*\{|@supports[^{]*\{", "", body)
        for sel in re.findall(r"(?:^|\})\s*([^{}]+)\{", body):
            for one in sel.split(","):
                assert one.strip().startswith("body.lm"), one
    assert "style=" not in mlb.CSS


def test_the_two_blocks_never_share_a_class():
    import member_lumen_bible as mlb
    import member_lumen_classes as mlc
    import member_lumen_ui as lm

    def classes(css):
        return set(re.findall(r"\.(lm-[a-z0-9-]+)", css))
    found = (classes(lm._CSS.template), classes(mlb.CSS), classes(mlc.CSS))
    # The page blocks may restyle the foundation's pieces they use, but a
    # class each block invents is its own.
    own_b = classes(mlb.CSS) - found[0]
    own_c = classes(mlc.CSS) - found[0]
    assert not own_b & own_c, own_b & own_c
