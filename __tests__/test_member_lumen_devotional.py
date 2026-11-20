# __tests__/test_member_lumen_devotional.py
#
# The devotional in the member app's new look (member_lumen_devotional),
# behind MEMBER_LUMEN. Pins:
#   - off: a devotional's day is today's markup, byte for byte, with or
#     without the night cookie;
#   - the Bible tab's Devotional tab (Look 5.1): today's devotional on top
#     (its day, title, a dot a day, Read today, Listen only when Listen can
#     work), More devotionals below without it; with nothing running, what's
#     next, the last one again, or one to start; nothing made up;
#   - a day: the church's picture (only when it chose one or a photo is
#     named for it), the green plate (Day N of M, the title, who and how
#     long, the days as dots, Listen, Share), the scripture, the words, the
#     line to hold, Reflect with the private journal, Pray, Do today,
#     Together, the checklist, Mark as read, the days before and after, Aa,
#     no tab bar; a preview and a failed read save nothing;
#   - night reading: the reader's moon and cookie, the page arrives dark,
#     the green bar stays green;
#   - no new reads, off, on or at night;
#   - the CSS lives in its own block in the served sheet, under body.lm,
#     before the type.

import pathlib
import re
import sys
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
DAY3 = f"/my/bible/plans/{D1}/3"


@pytest.fixture
def full(bible, fake):  # noqa: F811
    """Day 3 of the church's devotional with everything a day can have."""
    dev = next(r for r in fake.t["devotionals"] if r["id"] == D1)
    dev["practices"] = [{"key": "first-look", "title": "First look", "sub": "Scripture before your phone"},
                        {"key": "kind-word", "title": "One kind word"}]
    dev["days"][2] = {"title": "Planted by the Water", "scripture": "Jeremiah 17:7-8",
                      "body": "There is a difference between a plant that is placed and a tree that is planted.\n\n"
                              "Roots grow in hidden places.",
                      "pull": "Roots are ordinary work.", "pray": "Lord, plant me deeper.",
                      "act": "Take ten quiet minutes.", "together": "Text one person the verse.",
                      "journal": "Where is the heat right now?"}
    return bible


def _speak(monkeypatch, on):
    import devotional_voice as dvv
    monkeypatch.setattr(dvv, "can_speak", lambda: on)


# ─── off is today's day ──────────────────────────────────────────────


def test_off_the_day_is_todays_with_or_without_the_night_cookie(full, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c = _client(fake, monkeypatch)
    day = c.get(DAY3).text
    assert "lm" not in _body_class(day).split()
    assert 'class="lm-' not in day and ui.sheet_url("lumen") not in day and 'class="dv-day"' in day
    c.cookies.set(mlb.NIGHT_COOKIE, "1")
    assert c.get(DAY3).text == day                                                     # byte for byte
    bible_tab = c.get("/my/bible").text
    assert "lm-devo" not in bible_tab and "data-devo-listen" not in bible_tab


# ─── the Bible tab: today's devotional on top ────────────────────────


def test_the_bible_tab_has_todays_devotional_on_top(full, fake, monkeypatch):  # noqa: F811
    import member_lumen_devotional as mld
    _speak(monkeypatch, False)
    c = _client(fake, monkeypatch)
    on, reads_on = _reads(fake, c, "/my/bible?tab=devotional")
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    _, reads_off = _reads(fake, c, "/my/bible")
    assert not reads_on - reads_off, reads_on - reads_off                               # nothing new read
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    card = on[on.index('<section class="lm-devo"'):]
    card = card[:card.index("</section>")]
    assert on.index('class="lm-bseg"') < on.index('class="lm-devo"') < on.index('class="lm-week"')
    assert "Devotional · Day 3 of 7" in card
    assert 'id="lm-devo-h">Seven Days of <em>Rest</em></h2>' in card
    assert "Today: Planted by the Water · 2 min" in card
    dots = re.search(r'<span class="lm-devo-dots" role="img" aria-label="([^"]+)">(.*?)</span>', card)
    assert dots.group(1) == "Day 3 of 7. 2 days read."
    assert re.findall(r'<i(?: class="(\w)")?></i>', dots.group(2)) == ["d", "d", "t", "", "", "", ""]
    assert f'<a class="lm-devo-go" href="/my/bible/plans/{D1}/3">Read today</a>' in card
    assert "data-devo-listen" not in on and mld.CARD_JS not in on                       # Listen can't work here
    # More devotionals keeps the church's others
    more = on[on.index('class="lm-mcovs"'):]
    more = more[:more.index("</div>")]
    assert "Psalms at Night" in more and "Seven Days of Rest" not in more


def test_the_bible_tabs_listen_plays_the_day_where_it_is(full, fake, monkeypatch):  # noqa: F811
    import member_lumen_devotional as mld
    _speak(monkeypatch, True)
    on = _client(fake, monkeypatch).get("/my/bible?tab=devotional").text
    card = on[on.index('<section class="lm-devo"'):]
    card = card[:card.index("</section>")]
    assert f'data-devo-listen data-dev="{D1}" data-day="3"' in card and "<span>Listen</span>" in card
    assert '<audio id="lm-devo-audio" preload="none"></audio>' in card and "data-devo-say hidden" in card
    assert mld.CARD_JS in on and "/my/bible/plans/listen" in mld.CARD_JS
    # read today: Read again
    fake.add("devotional_progress", business_id=tct.BIZ, contact_id=tct.ANA, devotional_id=D1, day=3,
             done_at=datetime.now(timezone.utc).isoformat(), checks=[], journal="")
    on = _client(fake, monkeypatch).get("/my/bible?tab=devotional").text
    assert ">Read again</a>" in on and "Day 3 of 7. 3 days read." in on


def _st(count, kind, *, start=None, now=None, done=(), nxt=None):
    return {"kind": kind, "start": start, "upto": count, "now": now, "done": set(done), "count": count,
            "next": nxt, "preview": False}


def test_with_nothing_running_the_card_says_whats_next_or_offers_the_last_again():
    import member_lumen_devotional as mld
    biz = {"name": "Grace Fellowship"}
    fast = {"id": D1, "title": "Fasting Week", "starts_on": TODAY - timedelta(days=10), "author": ""}
    advent = {"id": D2, "title": "Advent: Make Room", "starts_on": TODAY + timedelta(days=10), "author": "Pastor James"}
    ended = _st(7, "over", start=TODAY - timedelta(days=10), done={1, 2, 3}, nxt=4)
    coming = _st(25, "upcoming", start=TODAY + timedelta(days=10))
    html, shown = mld.card(biz, [(fast, ended), (advent, coming)], listen=True)
    start = TODAY + timedelta(days=10)
    assert shown is advent
    assert f"Next devotional · starts {start.strftime('%A')}, {start.strftime('%b')} {start.day}" in html
    assert "Advent: Make <em>Room</em>" in html
    end = TODAY - timedelta(days=4)
    assert f"Until then, read Fasting Week again (7 days, ended {end.strftime('%b')} {end.day})." in html
    assert f'href="/my/bible/plans/{D1}/4">Read Fasting Week</a>' in html
    assert "Remind me" not in html and "data-devo-listen" not in html                   # no reminder to keep
    # nothing coming: the last one again, how far you got
    html, shown = mld.card(biz, [(fast, ended)], listen=True)
    assert shown is fast and "Devotional · 7 days · ended" in html
    assert "3 of 7 days read. Every day is still open." in html and "Pick up at day 4" in html
    assert re.findall(r'<i(?: class="(\w)")?></i>', html) == ["d", "d", "d", "", "", "", ""]   # no ring
    done = _st(7, "finished", start=TODAY - timedelta(days=10), done=set(range(1, 8)))
    html, _ = mld.card(biz, [(fast, done)])
    assert "You finished it." in html and f'href="/my/bible/plans/{D1}/1">Read it again</a>' in html
    # only one to start on your own day
    rest = {"id": D2, "title": "Psalms at Night", "starts_on": None}
    html, shown = mld.card(biz, [(rest, _st(21, "new"))])
    assert shown is rest and "Devotional · 21 days" in html and "Start any time." in html
    assert f'href="/my/bible/plans/{D2}">See the days</a>' in html
    # none: no card
    assert mld.card(biz, []) == ("", None)


def test_a_running_devotional_wins_and_the_church_comes_first():
    import member_lumen_devotional as mld
    mine = {"id": D2, "title": "Psalms at Night", "starts_on": None, "days": []}
    church = {"id": D1, "title": "Seven Days of Rest", "starts_on": TODAY - timedelta(days=2), "days": []}
    later = {"id": "00000000-0000-4000-8000-0000000009a3", "title": "Advent", "starts_on": TODAY + timedelta(days=3)}
    sts = [(later, _st(25, "upcoming", start=TODAY + timedelta(days=3))),
           (mine, _st(21, "running", start=TODAY - timedelta(days=1), now=2)),
           (church, _st(7, "running", start=TODAY - timedelta(days=2), now=3))]
    assert mld.pick(sts)[:2] == ("today", church)
    html, _ = mld.card({}, sts[:2])
    assert "Day 2 today" in html and "Psalms at <em>Night</em>" in html                 # no days read: no title made up
    # finished on its last day is still today's
    last = _st(7, "finished", start=TODAY - timedelta(days=6), now=7, done=set(range(1, 8)))
    assert mld.pick([(church, last)])[0] == "today"


# ─── a day ───────────────────────────────────────────────────────────


def test_a_day_reads_like_a_book(full, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    import member_lumen_devotional as mld
    _speak(monkeypatch, True)
    c = _client(fake, monkeypatch)
    on, reads_on = _reads(fake, c, DAY3)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    _, reads_off = _reads(fake, c, DAY3)
    assert reads_on == reads_off
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    assert _body_class(on).split()[:2] == ["lm", "lm-push"] and "lm-dark" not in _body_class(on).split()
    assert '<nav class="mb-nav' not in on                                               # no tab bar while reading
    assert f'<meta name="theme-color" content="{mld.GREEN}">' in on
    top = on[on.index('<header class="mb-top lm-mid">'):on.index("</header>")]
    assert f'class="mb-back" href="/my/bible/plans/{D1}"' in top and "Seven Days of Rest" in top
    assert '<span class="lm-dd-bt">Seven Days of Rest · Day 3</span>' in top
    assert 'id="lm-dd-aa"' in top and 'id="lm-moon" aria-pressed="false"' in top and 'class="lm-rprog"' in top
    assert f'data-day="{mld.GREEN}" data-night="{mld.GREEN}"' in top
    # the green plate
    hero = on[on.index('<section class="lm-dd-hero'):]
    hero = hero[:hero.index("</section>")]
    assert "Seven Days of Rest · Day 3 of 7" in hero
    assert '<h1 class="lm-dd-t" id="dv-h">Planted by the <em>Water</em></h1>' in hero
    assert "Pastor James · about 2 minutes" in hero
    track = re.findall(r'<(a|span) class="([^"]*)"(?: href="([^"]+)")? aria-label="([^"]+)"', hero)
    assert [t[3] for t in track] == ["Day 1, read", "Day 2, read", "Day 3", "Day 4, not open yet", "Day 5, not open yet",
                                     "Day 6, not open yet", "Day 7, not open yet"]
    assert [t[0] for t in track] == ["a", "a", "a", "span", "span", "span", "span"]
    assert 'aria-label="Day 3" aria-current="page" data-here' in hero
    assert 'id="dv-listen"' in hero and 'id="dv-share"' in hero and "Planted by the Water: Jeremiah 17:7-8" in hero
    assert "lm-dd-ph" not in hero                                                      # no picture chosen or named
    # the scripture, the words, the line to hold
    scrip = on[on.index('<section class="lm-dd-scrip"'):]
    scrip = scrip[:scrip.index("</section>")]
    assert "Jeremiah 17:7-8 · KJV" in scrip and "Blessed <i>is</i> the man that trusteth in the LORD" in scrip                # the supplied word upright
    assert "“" not in scrip and 'href="/my/bible/jeremiah/17?v=7-8#v7">Read Jeremiah 17' in scrip
    body = on[on.index('<div class="lm-dd-body">'):]
    assert body.index("a plant that is placed") < body.index("Roots grow in hidden places") < body.index("</div>")
    assert '<p class="lm-dd-pull">Roots are ordinary work.</p>' in on
    # Reflect, Pray, Do today, Together
    assert on.index(">Reflect</h2>") < on.index(">Pray</h2>") < on.index(">Do today</h2>") < on.index(">Together</h2>")
    assert '<p class="lm-dd-qn" id="lm-dd-qn">Where is the heat right now?</p>' in on
    ta = re.search(r"<textarea [^>]*>", on).group(0)
    assert 'data-journal maxlength="4000"' in ta and "disabled" not in ta
    assert "Private to you. Only you can read it." in on
    # the checklist, Mark as read, the days around it
    assert re.findall(r'class="lm-dd-ci" type="button" data-key="([\w-]+)" aria-pressed="(\w+)"', on) == [
        ("first-look", "false"), ("kind-word", "false")]
    assert '<span class="lm-dd-n" data-count>0 of 2</span>' in on
    assert '<button class="lm-dd-mark" type="button" data-act="done">Mark day 3 as read</button>' in on
    assert '<div class="lm-dd-card" data-donecard hidden>' in on and 'data-act="undo"' in on
    assert "Day 4, “Sabbath”, opens tomorrow morning." in on
    nav = on[on.index('<nav class="lm-dd-nav"'):]
    nav = nav[:nav.index("</nav>")]
    assert f'class="lm-dd-step prev" href="/my/bible/plans/{D1}/2"' in nav and "Still Waters" in nav
    assert 'class="lm-dd-step next is-shut"' in nav and "Day 4 · tomorrow" in nav and "Sabbath" in nav
    assert mld.DAY_JS in on and mlb.NIGHT_JS in on and "lm-vc" not in mlb.NIGHT_JS      # the moon, not the card


def test_a_day_done_says_so_and_how_many_in_a_row(full, fake, monkeypatch):  # noqa: F811
    on = _client(fake, monkeypatch).get(f"/my/bible/plans/{D1}/2").text
    assert '<button class="lm-dd-mark" type="button" data-act="done" hidden>' in on
    assert '<div class="lm-dd-card" data-donecard>' in on
    assert "Day 2 is done.<span data-streak> Two in a row.</span>" in on
    assert "Day 3, “Planted by the Water”, is ready when you are." in on
    assert f'class="lm-dd-step next" href="/my/bible/plans/{D1}/3"' in on


def test_the_churchs_picture_heads_the_day(full, fake, monkeypatch):  # noqa: F811
    biz = fake.biz[tct.BIZ]
    biz["settings"]["member_portal"]["pictures"] = {f"devotional:{D1}": {"url": "https://cdn.example.test/rest.jpg",
                                                                          "look": "bw"}}
    on = _client(fake, monkeypatch).get(DAY3).text
    hero = on[on.index('<section class="lm-dd-hero'):]
    assert hero.startswith('<section class="lm-dd-hero has-ph"')
    assert '<span class="lm-dd-ph"><span class="mb-ph is-bw ' in hero and 'src="https://cdn.example.test/rest.jpg"' in hero
    assert 'fetchpriority="high"' in hero[:hero.index("</span></span>")]
    # a photo named for it, in colour
    biz["settings"]["member_portal"]["pictures"] = {}
    import member_app_photos as photos
    monkeypatch.setattr(photos, "photos", lambda b, site, limit=None: ["/public/site-assets/grace/seven-days-rest.jpg"])
    on = _client(fake, monkeypatch).get(DAY3).text
    assert 'class="mb-ph is-colour ' in on and "seven-days-rest.jpg" in on


def test_without_listen_and_when_the_day_cant_save(full, fake, monkeypatch):  # noqa: F811
    _speak(monkeypatch, False)
    on = _client(fake, monkeypatch).get(DAY3).text
    assert 'id="dv-listen"' not in on and 'id="dv-share"' in on
    # the member's day can't be read: the page says so (today's 503 page), as before
    fake.down.add("devotional_progress")
    r = _client(fake, monkeypatch).get(DAY3)
    assert r.status_code == 503 and "couldn't load" in r.text


def test_a_preview_saves_nothing(full, fake):  # noqa: F811
    import devotionals as dv
    import member_lumen_devotional as mld
    import member_portal_devotionals as mpd
    dev, _ = dv.one(tct.BIZ, D1)
    st = mpd.state(dev, None, set(), preview=True)
    html = mld.render_day(fake.biz[tct.BIZ], {}, {"id": tct.ANA, "name": "Ana Rivera"}, dev, 3, st, {})
    assert "This is a preview" in html and 'data-live="0"' in html
    assert re.search(r'<button class="lm-dd-mark" type="button" data-act="done" disabled>', html)
    assert "disabled>" in re.search(r"<textarea [^>]*>", html).group(0)
    assert all("disabled" in b for b in re.findall(r'<button class="lm-dd-ci"[^>]*>', html))
    # a preview sees every day: each one is a link
    assert html.count('href="/my/bible/plans/' + D1 + '/') >= 7


# ─── night reading ───────────────────────────────────────────────────


def test_night_reading_arrives_dark_and_reads_nothing_new(full, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    import member_lumen_devotional as mld
    c = _client(fake, monkeypatch)
    c.cookies.set(mlb.NIGHT_COOKIE, "1")
    night, reads_night = _reads(fake, c, DAY3)
    c.cookies.clear()
    _, reads_day = _reads(fake, c, DAY3)
    assert reads_night == reads_day
    assert _body_class(night).split()[:2] == ["lm", "lm-push"] and "lm-dark" in _body_class(night).split()
    assert 'id="lm-moon" aria-pressed="true"' in night
    assert f'<meta name="theme-color" content="{mld.GREEN}">' in night                   # the green bar stays green
    # only the reader and the day read it: the Devotional tab stays white
    c.cookies.set(mlb.NIGHT_COOKIE, "1")
    assert "lm-dark" not in _body_class(c.get("/my/bible?tab=devotional").text).split()


def test_the_readers_script_is_the_moon_and_the_card_unchanged():
    import member_lumen_bible as mlb
    assert mlb.READER_MORE_JS == "<script>(function(){" + mlb._NIGHT + mlb._CARD + "})();</script>"
    assert mlb.NIGHT_JS == "<script>(function(){" + mlb._NIGHT + "})();</script>"
    assert "lm_night=" in mlb._NIGHT and "lm-rprog" in mlb._NIGHT and "lm-vc" in mlb._CARD


def test_in_a_row_in_words():
    import member_lumen_devotional as mld
    assert mld.in_a_row(1) == "" and mld.in_a_row(3) == "Three in a row." and mld.in_a_row(14) == "14 in a row."
    assert "'Twelve'" in mld.DAY_JS                                                     # the script says it the same way


# ─── the look ────────────────────────────────────────────────────────


def test_the_css_is_its_own_block_in_the_served_sheet_before_the_type():
    import member_lumen_bible as mlb
    import member_lumen_devotional as mld
    import member_lumen_fonts as lmf
    import member_lumen_ui as lm
    text = ui.sheet("lumen")[0]
    assert mld.CSS.strip() in text
    assert text.index(mld.CSS.strip()) < text.index(lmf.css().strip()[:200])            # the type stays last
    body = re.sub(r"/\*.*?\*/", "", mld.CSS, flags=re.S)
    names = re.findall(r"@keyframes\s+([\w-]+)", body)
    assert names and all(n.startswith("lm-") for n in names), names
    body = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", body)
    body = re.sub(r"@media[^{]*\{|@supports[^{]*\{", "", body)
    for sel in re.findall(r"(?:^|\})\s*([^{}]+)\{", body):
        for one in sel.split(","):
            assert one.strip().startswith("body.lm"), one
    assert "style=" not in mld.CSS and "$" not in mld.CSS
    # motion only when the phone allows it
    motion = mld.CSS[mld.CSS.index("@media (prefers-reduced-motion:no-preference)"):]
    assert "lm-ddarrive" in motion and "animation:" not in mld.CSS[:mld.CSS.index("prefers-reduced-motion")]
    # the classes it invents are its own
    own = set(re.findall(r"\.(lm-[a-z0-9-]+)", mld.CSS)) - set(re.findall(r"\.(lm-[a-z0-9-]+)", lm._CSS.template)) \
        - set(re.findall(r"\.(lm-[a-z0-9-]+)", mlb.CSS))
    assert own and all(c.startswith(("lm-dd", "lm-devo")) for c in own), own
