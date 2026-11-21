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
#   - a day: since the Plans design (2026-11-21) the new look's day is the
#     day in steps (member_lumen_plan_day, test_member_lumen_plan_day); this
#     module's own day (render_day) still saves nothing in a preview;
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
