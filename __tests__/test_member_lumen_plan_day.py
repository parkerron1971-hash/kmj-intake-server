# __tests__/test_member_lumen_plan_day.py
#
# The day in steps (member_lumen_plan_day), screen 3 of Kevin's approved Plans
# design. Pins:
#   - off: a devotional's day is today's; a plan's day address goes where it
#     went;
#   - a devotional's day: close, "Day N of M" and share in the bar, no tab
#     bar; the steps from the day's own words (an empty one left out); a
#     strip of the days around it; one step at a time, each its own address,
#     Back and Next as links; the scripture from the app's Bible in the
#     member's translation; Listen in the church's reading voice when it can
#     be made, else the phone's own; the journal (private), the group's
#     question, the checklist and Mark done on the last step;
#   - saving without script: the day's form marks done or not done and keeps
#     the journal and the checklist, only the member's own day, an open day
#     only, rate limited, back to the last step saying so;
#   - a plan's day: its passages, Mark done on the reading plans' own route
#     back to the day, a day not open yet goes back to the plan;
#   - no reads of its own; the CSS is its own block under body.lm.

import pathlib
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_pages import church, _client, _body_class  # noqa: F401  (church is a fixture)
from test_member_lumen_bible import bible, _reads, D1, D2  # noqa: F401  (bible is a fixture)

TODAY = date.today()
DAY3 = f"/my/bible/plans/{D1}/3"


@pytest.fixture
def full(bible, fake):  # noqa: F811
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


def _app(fake, monkeypatch):  # noqa: F811
    import member_portal_devotionals as mpd
    import member_portal_reading as mpr
    c = _client(fake, monkeypatch)
    c.app.include_router(mpd.router)
    c.app.include_router(mpr.router)
    return c


def _speak(monkeypatch, on):
    import devotional_voice as dvv
    monkeypatch.setattr(dvv, "can_speak", lambda: on)


def _panel(html, step):
    s = html[html.index(f'<section class="lm-dy-p" data-step="{step}"'):]
    return s[:s.index("</section>")]


# ─── off ─────────────────────────────────────────────────────────────


def test_off_the_day_is_todays(full, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c = _client(fake, monkeypatch)
    html = c.get(DAY3 + "?step=pray").text
    assert "lm-dy" not in html and 'id="dv-day" class="dv-day"' in html
    r = c.get("/my/bible/plans/gospels-30/2", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/bible/plans"


# ─── a devotional's day ──────────────────────────────────────────────


def test_a_day_in_steps(full, fake, monkeypatch):  # noqa: F811
    _speak(monkeypatch, True)
    c = _client(fake, monkeypatch)
    on, reads_on = _reads(fake, c, DAY3)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    _, reads_off = _reads(fake, c, DAY3)
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    assert reads_on == reads_off                                                         # no reads of its own
    assert _body_class(on).split()[:2] == ["lm", "lm-push"] and '<nav class="mb-nav' not in on
    top = on[on.index('<header class="mb-top'):on.index("</header>")]
    assert f'class="mb-back" href="/my/bible/plans/{D1}"' in top and "Close" in top
    assert '<span class="lm-dy-bt">Day 3 of 7</span>' in top and 'id="dv-share"' in top
    assert "Planted by the Water: Jeremiah 17:7-8 · Seven Days of Rest, Grace Fellowship" in top
    steps = on[on.index('<nav class="lm-dy-steps"'):]
    steps = steps[:steps.index("</nav>")]
    assert re.findall(r'href="([^"]+)" data-go="(\w+)"', steps) == [
        (f"{DAY3}?step=read", "read"), (f"{DAY3}?step=scripture", "scripture"), (f"{DAY3}?step=act", "act"),
        (f"{DAY3}?step=pray", "pray"), (f"{DAY3}?step=journal", "journal")]
    assert '<a class="on" href="' + DAY3 + '?step=read" data-go="read" aria-current="step">Read</a>' in steps
    strip = on[on.index('<nav class="lm-dy-strip"'):]
    strip = strip[:strip.index("</nav>")]
    assert re.findall(r">Day (\d)<", strip) == ["1", "2", "3", "4", "5"]
    assert f'<a class="ok" href="/my/bible/plans/{D1}/1"' in strip and '<span class="on" aria-current="page"' in strip
    assert '<span class="shut" aria-label="Day 4, not open yet">Day 4</span>' in strip
    # one step at a time: the first shows, the rest wait (the script switches them; each is its own address too)
    assert re.findall(r'<section class="lm-dy-p" data-step="(\w+)" aria-label="\w+"( hidden)?>', on) == [
        ("read", ""), ("scripture", " hidden"), ("act", " hidden"), ("pray", " hidden"), ("journal", " hidden")]
    read = _panel(on, "read")
    assert read.index('id="dv-listen"') < read.index("Roots are ordinary work.") < read.index("a plant that is placed")
    assert 'data-kind="voice"' in read and "Today&#x27;s reading, read aloud" in read and "pastor" not in on.lower()
    assert f'<a class="lm-dy-b" href="/my/bible/plans/{D1}">Back</a>' in read
    assert f'<a class="lm-dy-b is-go" href="{DAY3}?step=scripture" data-go="scripture">Next: Scripture</a>' in read
    scrip = _panel(on, "scripture")
    assert "Jeremiah 17:7-8 · KJV" in scrip and "Blessed <i>is</i> the man that trusteth in the LORD" in scrip
    assert '<span class="lm-dy-v"><sup>7</sup>' in scrip and '<sup>8</sup>' in scrip
    assert "Today's step" in _panel(on, "act") and "Take ten quiet minutes." in _panel(on, "act")
    assert "Lord, plant me deeper." in _panel(on, "pray")
    last = _panel(on, "journal")
    assert '<p class="lm-dy-q" id="lm-dy-qn">Where is the heat right now?</p>' in last
    assert re.search(r'<textarea class="lm-dy-ta" id="dv-j" name="journal" data-journal maxlength="4000"', last)
    assert "Private to you. Only you can read it." in last
    assert "For your group" in last and "Text one person the verse." in last
    assert re.findall(r'name="checks" value="([\w-]+)"', last) == ["first-look", "kind-word"]
    assert '<form class="lm-dy-form" method="post" action="/my/bible/plans/day">' in last
    assert '<button class="lm-dy-b is-go lm-dy-mark" type="submit" name="done" value="1" data-act="done">Mark day 3 done</button>' in last
    assert "Day 4, “Sabbath”, opens tomorrow." in last


def test_each_step_is_its_own_address(full, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get(DAY3 + "?step=pray").text
    assert re.findall(r'data-step="(\w+)" aria-label="\w+">', html) == ["pray"]           # the one shown
    pray = _panel(html, "pray")
    assert f'href="{DAY3}?step=act" data-go="act">Back</a>' in pray and "Next: Journal" in pray
    steps = html[html.index('<nav class="lm-dy-steps"'):html.index("</nav>")]
    assert ('<a class="ok" href="' + DAY3 + '?step=read"') in steps and 'class="on"' in steps
    nonsense = _client(fake, monkeypatch).get(DAY3 + "?step=dance").text
    assert re.findall(r'data-step="(\w+)" aria-label="\w+">', nonsense) == ["read"]


def test_an_empty_step_is_left_out(full, fake, monkeypatch):  # noqa: F811
    dev = next(r for r in fake.t["devotionals"] if r["id"] == D1)
    dev["days"][2].update(act="", pray="  ", journal="")
    html = _client(fake, monkeypatch).get(DAY3).text
    assert re.findall(r'data-step="(\w+)"', html) == ["read", "scripture"]
    last = _panel(html, "scripture")
    assert "lm-dy-form" in last and "Mark day 3 done" in last and "<textarea" not in last  # no journal step: no box


def test_listen_in_the_phones_voice_when_the_church_voice_cant_be_made(full, fake, monkeypatch):  # noqa: F811
    _speak(monkeypatch, False)
    html = _client(fake, monkeypatch).get(DAY3).text
    lis = re.search(r'<button class="lm-dy-lis" id="dv-listen" type="button" data-kind="phone"[^>]*>', html).group(0)
    assert "hidden" in lis and 'id="dv-audio"' not in html                              # the script shows it where it can
    assert "Read aloud by your phone" in html


def test_a_day_done_and_the_days_in_a_row(full, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get(f"/my/bible/plans/{D1}/2").text
    assert '<div class="lm-dy-done" data-donecard>' in html and "Day 2 is done.<span data-streak> Two in a row.</span>" in html
    assert 'data-act="done" hidden>' in html
    assert f'<a href="/my/bible/plans/{D1}/3">Day 3, “Planted by the Water”, is ready</a>' in html


def test_the_preview_and_a_failed_read_save_nothing(full, fake, monkeypatch):  # noqa: F811
    import devotionals as dv
    import member_lumen_plan_day as mlpd
    import member_portal_devotionals as mpd
    import member_lumen
    monkeypatch.setattr(member_lumen, "page", lambda: True)
    dev, _ = dv.one(tct.BIZ, D1)
    html = mlpd.render_day(fake.biz[tct.BIZ], {}, {"id": tct.ANA, "name": "Ana"}, dev, 3,
                           mpd.state(dev, None, set(), preview=True), {}, step="journal")
    assert "This is a preview" in html and 'data-live="0"' in html
    assert "disabled>" in re.search(r"<textarea [^>]*>", html).group(0)
    assert 'data-act="done" disabled>' in html and "<noscript>" not in html
    fake.down.add("devotional_progress")
    r = _client(fake, monkeypatch).get(DAY3)
    assert r.status_code == 503 and "couldn't load" in r.text


def test_night_reading_still_arrives_dark(full, fake, monkeypatch):  # noqa: F811
    import member_lumen_bible as mlb
    c = _client(fake, monkeypatch)
    c.cookies.set(mlb.NIGHT_COOKIE, "1")
    assert "lm-dark" in _body_class(c.get(DAY3).text).split()


# ─── saving without script ───────────────────────────────────────────


def test_the_days_form_marks_done_and_keeps_the_journal_and_checklist(full, fake, monkeypatch):  # noqa: F811
    import member_lumen_plans as mlp
    c = _app(fake, monkeypatch)
    r = c.post("/my/bible/plans/day", data={"devotional": D1, "day": "3", "step": "journal", "journal": "The heat is work.",
                                            "checks_in": "1", "checks": ["kind-word"], "done": "1"},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"{DAY3}?step=journal&done=done"
    assert f"{mlp.VERSION_COOKIE}=" in r.headers["set-cookie"]
    row = next(x for x in fake.t["devotional_progress"] if x["devotional_id"] == D1 and x["day"] == 3)
    assert row["contact_id"] == tct.ANA and row["done_at"] and row["journal"] == "The heat is work."
    assert row["checks"] == ["kind-word"]
    html = c.get(f"{DAY3}?step=journal&done=done").text
    assert "Marked done. Well done." in html and '<div class="lm-dy-done" data-donecard>' in html
    assert 'value="kind-word" data-key="kind-word" checked' in html and ">The heat is work.</textarea>" in html
    # Not done yet, and the checklist emptied
    r = c.post("/my/bible/plans/day", data={"devotional": D1, "day": "3", "step": "journal", "checks_in": "1", "done": "0"},
               follow_redirects=False)
    assert r.headers["location"] == f"{DAY3}?step=journal&done=undone"
    row = next(x for x in fake.t["devotional_progress"] if x["devotional_id"] == D1 and x["day"] == 3)
    assert row["done_at"] is None and row["checks"] == [] and row["journal"] == "The heat is work."


def test_the_days_form_refuses_a_day_not_open_and_another_site(full, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    r = c.post("/my/bible/plans/day", data={"devotional": D1, "day": "5", "done": "1"}, follow_redirects=False)
    assert r.headers["location"] == f"/my/bible/plans/{D1}/5?err=day"
    r = c.post("/my/bible/plans/day", data={"devotional": D1, "day": "3", "done": "1"},
               headers={"origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow", lambda *a, **k: False)
    r = c.post("/my/bible/plans/day", data={"devotional": D1, "day": "3", "done": "1"}, follow_redirects=False)
    assert r.headers["location"] == f"{DAY3}?err=slow"
    assert not [x for x in fake.t["devotional_progress"] if x["day"] in (3, 5)]


def test_the_json_route_is_as_it_was(full, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    r = c.post("/my/bible/plans/day", json={"devotional": D1, "day": 3, "done": True})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["done"] is True


# ─── a plan's day ────────────────────────────────────────────────────


def test_a_topic_plans_day(bible, fake, monkeypatch):  # noqa: F811
    fake.t.setdefault("reading_progress", [])
    fake.add("member_plan_starts", business_id=tct.BIZ, contact_id=tct.ANA, plan="reading:topic-anxiety",
             started_on=(TODAY - timedelta(days=1)).isoformat())
    c = _app(fake, monkeypatch)
    html = c.get("/my/bible/plans/topic-anxiety/2").text
    assert _body_class(html).split()[:2] == ["lm", "lm-push"]
    assert '<span class="lm-dy-bt">Day 2 of 7</span>' in html and '<h1 class="lm-dy-t">Do not worry about tomorrow</h1>' in html
    assert "Matthew 6:25-34 · KJV" in html and "Take no thought for your life" in html
    assert 'data-kind="phone"' in html
    assert ('<input type="hidden" name="back" value="/my/bible/plans/topic-anxiety/2"><input type="hidden" name="plan" '
            'value="topic-anxiety"><button class="lm-dy-b is-go lm-dy-mark" type="submit">Mark day 2 done</button>') in html
    r = c.post("/my/reading", data={"day": "2", "read": "yes", "back": "/my/bible/plans/topic-anxiety/2",
                                    "plan": "topic-anxiety"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-anxiety/2?done=read"
    html = c.get("/my/bible/plans/topic-anxiety/2?done=read").text
    assert "Day 2 is done." in html and "Not done yet" in html and "Marked as read" in html
    # a day not open yet goes back to the plan; a back to anywhere else is today's plan page
    r = c.get("/my/bible/plans/topic-anxiety/3", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/bible/plans/topic-anxiety"
    r = c.post("/my/reading", data={"day": "1", "read": "yes", "back": "https://evil.example/x", "plan": "topic-anxiety"},
               follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-anxiety?done=read"


def test_a_reading_plans_day_and_its_page_link_to_it(bible, fake, monkeypatch):  # noqa: F811
    fake.t.setdefault("reading_progress", [])
    c = _client(fake, monkeypatch)
    html = c.get("/my/bible/plans/gospels-30/5").text
    assert "Matthew 13 · KJV" in html and "Matthew 15 · KJV" in html and "The same day went Jesus out of the house" in html
    page = c.get("/my/bible/plans/gospels-30").text
    assert 'href="/my/bible/plans/gospels-30/5"><b>Matthew 13–15</b>' in page
    r = c.get("/my/bible/plans/nt-260/1", follow_redirects=False)                       # not started
    assert r.status_code == 303 and r.headers["location"] == "/my/bible/plans/nt-260"


# ─── the CSS ─────────────────────────────────────────────────────────


def test_the_css_is_its_own_block_under_body_lm():
    import member_lumen_plan_day as mlpd
    import member_lumen_plans as mlp
    import member_lumen_ui as lm
    parts = [t.template for t in lm.templates()]
    assert parts.index(mlpd.CSS) == parts.index(mlp.CSS) + 1 and parts.index(mlpd.CSS) < len(parts) - 3
    rules = re.sub(r"/\*.*?\*/", "", mlpd.CSS, flags=re.S)
    rules = re.sub(r"@media[^{]+\{|@keyframes[^{]+\{", "", rules)
    for sel in re.findall(r"([^{}]+)\{[^{}]*\}", rules):
        for one in sel.split(","):
            one = one.strip()
            if one and one not in ("from", "to"):
                assert one.startswith("body.lm"), one
