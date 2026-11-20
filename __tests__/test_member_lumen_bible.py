# __tests__/test_member_lumen_bible.py
#
# The Bible (with its reader and plans) and Classes in the member app's new
# look (member_lumen_bible, member_lumen_classes), behind MEMBER_LUMEN.
# Pins:
#   - off: every Bible and Classes page is today's markup (no Lumen class);
#   - on: the Bible tab is "The Word" with the translation switcher beside
#     the heading, find, pick up where you left off, the ivory verse card, the
#     church's devotionals with progress dots, the reading plans, your
#     highlights and notes, the books, from the same reads as today's tab;
#   - the reader: no tab bar, the chapter and Aa in the bar, the chapter's
#     number large, the highlighter (today's reader script), the chapters
#     around it; same reads as today; no "Listen to this chapter";
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


def test_the_bible_tab_is_the_word(bible, fake, monkeypatch):  # noqa: F811
    on, off = _same_reads(fake, monkeypatch, "/my/bible")
    assert _body_class(on).split()[:2] == ["lm", "lm-tab"]
    mast = on[on.index('class="lm-mast lm-bmast"'):]
    mast = mast[:mast.index("</header>")]
    assert "The <em>Word</em>" in mast
    trs = re.findall(r'<a href="/my/bible\?t=(\w+)"( aria-current="true")?', mast)
    assert [t for t, _ in trs] == ["kjv", "web", "bsb", "asv"] and trs[0][1]          # the switcher, KJV on
    assert 'action="/my/bible" role="search"' in on and 'name="q"' in on             # find a passage or a word
    assert 'class="lm-cont" href="/my/bible/john/1"' in on and "Start here" in on   # nothing read yet: John 1
    assert 'class="lm-page"' in on and "Verse of the day" in on                       # the ivory card
    # Lumen Next: the running devotional on top with its days as dots
    # (test_member_lumen_devotional); the rail keeps the church's others.
    devo = on[on.index('<section class="lm-devo"'):]
    devo = devo[:devo.index("</section>")]
    assert "Seven Days of <em>Rest</em>" in devo and "Today: Unhurried" in devo
    assert devo.count('<i class="d"></i>') == 2 and devo.count("<i") == 7
    rail = on[on.index('class="lm-rail lm-devs"'):]
    rail = rail[:rail.index("</div>")]
    assert "Seven Days of Rest" not in rail and "Psalms at Night" in rail and "Start any time" in rail
    assert "From Grace Fellowship" in on
    # Reading plans: the church's, hers, then the four to start.
    assert "The church is reading" in on and "Your plan" in on
    assert re.findall(r'<a class="lm-plan" href="[^"]+"><b>(\d+)</b>', on) == ["365", "260", "30", "31"]
    assert "Yours · day 5" in on
    # Highlights & notes, and the books.
    marks = on[on.index('class="lm-marks"'):]
    assert "1 highlight<" in marks and "1 note<" in marks and "1 saved" in marks
    assert 'href="/my/bible/books?t=ot"' in on and 'href="/my/bible/books?t=nt"' in on
    assert "Listen to this chapter" not in on                                         # the devotional's Listen only


def test_the_bible_tab_picks_up_where_you_left_off(bible, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    c.cookies.set("sol_bible", "web|romans/8~psalms/23", path="/my")
    html = c.get("/my/bible").text
    cont = html[html.index('class="lm-cont"'):]
    cont = cont[:cont.index("</a>")]
    assert 'href="/my/bible/romans/8"' in cont and "Romans 8" in cont and "Pick up where you left off" in cont
    assert '<a href="/my/bible?t=web" aria-current="true"' in html


def test_a_failed_plans_read_leaves_the_church_plan_alone(bible, fake, monkeypatch):  # noqa: F811
    import devotionals as dv

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(dv, "catalog", boom)
    html = _client(fake, monkeypatch).get("/my/bible").text
    assert 'class="lm-rail lm-devs"' not in html and 'class="lm-plans"' not in html
    assert "The church is reading" in html and 'href="/my/reading"' in html


# ─── the reader ──────────────────────────────────────────────────────


def test_the_reader_is_calm(bible, fake, monkeypatch):  # noqa: F811
    import member_portal_bible as mpb
    on, off = _same_reads(fake, monkeypatch, "/my/bible/john/1")
    assert _body_class(on).split()[:2] == ["lm", "lm-push"]
    assert '<nav class="mb-nav' not in on                                            # no tab bar while reading
    top = on[on.index('<header class="mb-top lm-mid">'):on.index("</header>")]
    assert 'class="mb-back" href="/my/bible"' in top and "Bible" in top
    assert '<a class="lm-pill" href="/my/bible/john">John 1' in top                   # opens the book picker
    assert 'id="bb-aa"' in top and ">Aa</button>" in top
    assert '<b aria-hidden="true">1</b>' in on and "John · KJV" in on
    # Today's reader: tap a verse, the dock, its marks.
    assert mpb.READER_JS in on
    for act in ("note", "copy", "share", "bookmark", "clear", "close", "save-note"):
        assert f'data-act="{act}"' in on, act
    assert 'class="bb-v hl-gold" data-v="5"' in on and "bb-nm" in on and "bb-bm" in on
    # Aa holds the size, the font and the translation.
    panel = on[on.index('id="bb-aa-panel"'):]
    panel = panel[:panel.index('class="lm-chap"')]
    assert 'data-size="up"' in panel and 'data-font="sans"' in panel and 'href="/my/bible/john/1?t=web"' in panel
    nav = on[on.index('class="lm-chnav"'):]
    assert 'href="/my/bible/luke/24"' in nav and 'href="/my/bible/john/2"' in nav
    assert "Listen to this chapter" not in on and ">Listen<" not in on


def test_the_preview_reader_keeps_the_translation_without_aa(bible, fake, monkeypatch):  # noqa: F811
    fake.down.add("bible_marks")
    html = _client(fake, monkeypatch).get("/my/bible/john/1").text
    assert 'id="bb-aa"' not in html and "couldn't load" in html
    assert 'class="lm-trfoot"' in html and 'href="/my/bible/john/1?t=asv"' in html


# ─── Lumen Next: the reader at night, the ink, Make a card ────────────


def test_night_reading_arrives_dark_from_its_cookie(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    c = _client(fake, monkeypatch)
    day = c.get("/my/bible/john/1").text
    assert "lm-dark" not in _body_class(day).split()
    assert '<meta name="theme-color" content="#ffffff">' in day
    top = day[day.index('<header class="mb-top lm-mid">'):day.index("</header>")]
    assert 'id="lm-moon"' in top and 'aria-pressed="false"' in top and 'aria-label="Night reading"' in top
    assert f'data-night="{mlb.NIGHT_BG}"' in top and 'data-day="#ffffff"' in top
    assert '<span class="lm-rprog" aria-hidden="true"></span>' in top                 # how far you've read
    assert mlb.READER_MORE_JS in day and "lm_night=" in mlb.READER_MORE_JS and "Path=/my" in mlb.READER_MORE_JS
    c.cookies.set(mlb.NIGHT_COOKIE, "1")
    night = c.get("/my/bible/john/1").text
    assert _body_class(night).split()[:2] == ["lm", "lm-push"] and "lm-dark" in _body_class(night).split()
    assert f'<meta name="theme-color" content="{mlb.NIGHT_BG}">' in night
    assert 'id="lm-moon" aria-pressed="true"' in night
    # only the reader reads it: the Bible tab and Home stay white
    assert "lm-dark" not in _body_class(c.get("/my/bible").text).split()
    assert "lm-dark" not in _body_class(c.get("/my").text).split()
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
