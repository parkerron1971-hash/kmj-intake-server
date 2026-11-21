# __tests__/test_member_lumen_plan_page.py
#
# A plan's page in the member app's new look (member_lumen_plans, screen 2 of
# Kevin's approved Plans design): a church devotional's page, and Start over
# for every kind of plan. Pins:
#   - off: a devotional's page is today's;
#   - the devotional's page: its cover (the church's picture in its colour,
#     or a cover of that colour), the church and what kind it is, how many
#     days and about how long, what it's about, Start / Continue day N /
#     when the church starts it / You finished it, and every day with its
#     scripture and whether it's read (open days link to the day);
#   - Start over: shown only where it means something, never in the
#     preview; it only touches the member's own rows (a devotional's marks
#     cleared, its journal kept; a plan of their own runs again from today),
#     refuses another site's form, says when it's too much at once, and
#     gives the phone a new plans version.

import pathlib
import re
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_pages import church, _client, _body_class  # noqa: F401  (church is a fixture)
from test_member_lumen_bible import bible, D1, D2  # noqa: F401  (bible is a fixture)

TODAY = date.today()


def _app(fake, monkeypatch):  # noqa: F811
    import member_portal_devotionals as mpd
    import member_portal_reading as mpr
    c = _client(fake, monkeypatch)
    c.app.include_router(mpd.router)
    c.app.include_router(mpr.router)
    return c


def _dev(fake, i):
    return next(r for r in fake.t["devotionals"] if r["id"] == i)


def _rows(html):
    return re.findall(r'<li class="lm-pp-d( [^"]*)?">(.*?)</li>', html)


# ─── off ─────────────────────────────────────────────────────────────


def test_off_a_devotionals_page_is_todays(bible, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = _client(fake, monkeypatch).get(f"/my/bible/plans/{D1}").text
    assert "lm-pp-" not in html and 'class="dv-hero"' in html and "lm" not in _body_class(html).split()


# ─── a devotional's page ─────────────────────────────────────────────


def test_the_church_devotional_running(bible, fake, monkeypatch):  # noqa: F811
    _dev(fake, D1)["about"] = "A week to slow down.\n\nCome as you are."
    html = _client(fake, monkeypatch).get(f"/my/bible/plans/{D1}").text
    assert _body_class(html).split()[:2] == ["lm", "lm-push"]
    top = html[html.index('<header class="mb-top">'):html.index("</header>")]
    assert 'href="/my/bible?tab=plans"' in top
    assert '<section class="lm-pp-top is-made" aria-labelledby="lm-pp-h"><div class="lm-pp-tt">' in html   # no picture
    assert "<small>Grace Fellowship · Devotional</small>" in html and '<h1 id="lm-pp-h">Seven Days of Rest</h1>' in html
    assert re.search(r"<small>7 days · about \d+ minutes? a day</small>", html)
    assert '<div class="lm-pp-about"><p>A week to slow down.</p><p>Come as you are.</p></div>' in html
    assert f'<a class="lm-btn" href="/my/bible/plans/{D1}/3">Continue day 3</a>' in html
    over = html[html.index('<details class="lm-pp-over">'):html.index("</details>")]
    assert f'name="plan" value="devotional:{D1}"' in over and "on the church&#x27;s days" in over
    rows = _rows(html)
    assert [r[0] for r in rows] == [" is-done", " is-done", " is-now", " is-shut", " is-shut", " is-shut", " is-shut"]
    assert (f'<span class="lm-pp-c ok" aria-hidden="true">1</span><a class="lm-pp-dt" href="/my/bible/plans/{D1}/1" '
            f'aria-label="Day 1, read: Come Away"><b>Come Away</b><small>Psalm 23:2</small></a>') == rows[0][1]
    assert "<small>Psalm 23:2 · today</small>" in rows[2][1]
    tomorrow = TODAY + timedelta(days=1)
    assert f"opens {tomorrow.strftime('%a')}, {tomorrow.strftime('%b')} {tomorrow.day}" in rows[3][1]
    assert "<a " not in rows[3][1]                                                       # not open yet: no link


def test_the_church_picture_drawn_in_its_colour(bible, fake, monkeypatch):  # noqa: F811
    import member_app_photos as photos
    real = photos.assigned
    monkeypatch.setattr(photos, "assigned", lambda biz, key: (
        {"url": "https://example.test/rest.jpg", "look": "bw"} if key == f"devotional:{D1}" else real(biz, key)))
    html = _client(fake, monkeypatch).get(f"/my/bible/plans/{D1}").text
    assert '<section class="lm-pp-top has-ph" aria-labelledby="lm-pp-h"><span class="mb-ph is-church "' in html
    assert "rest.jpg" in html


def test_a_devotional_to_start_on_your_own_day(bible, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get(f"/my/bible/plans/{D2}").text
    assert "<small>Grace Fellowship · Evening psalms</small>" in html
    assert (f'<form method="post" action="/my/bible/plans/start"><input type="hidden" name="plan" value="devotional:{D2}">'
            f'<button class="lm-btn" type="submit">Start</button></form>') in html
    assert "A day opens each day from the day you start: 21 days." in html
    assert "lm-pp-over" not in html                                                      # nothing to start over
    rows = _rows(html)
    assert len(rows) == 21 and all(r[0] == " is-shut" for r in rows) and "opens after you start" in rows[0][1]


def test_a_devotional_the_church_starts_later(bible, fake, monkeypatch):  # noqa: F811
    start = TODAY + timedelta(days=4)
    _dev(fake, D1)["starts_on"] = start.isoformat()
    fake.t["devotional_progress"] = []
    html = _client(fake, monkeypatch).get(f"/my/bible/plans/{D1}").text
    assert f"Grace Fellowship starts it together on {start.strftime('%a')}, {start.strftime('%b')} {start.day}." in html
    assert 'class="lm-btn"' not in html and "lm-pp-over" not in html


def test_a_finished_devotional(bible, fake, monkeypatch):  # noqa: F811
    now = datetime.now(timezone.utc).isoformat()
    for d in range(3, 8):
        fake.add("devotional_progress", business_id=tct.BIZ, contact_id=tct.ANA, devotional_id=D1, day=d,
                 done_at=now, checks=[], journal="")
    html = _client(fake, monkeypatch).get(f"/my/bible/plans/{D1}").text
    assert "<b>You finished it</b>" in html and f'href="/my/bible/plans/{D1}/1">Read it again</a>' in html
    assert "lm-pp-over" in html


def test_the_preview_offers_no_start_over(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_plans as mlp
    import member_portal_devotionals as mpd
    import devotionals as dv

    class R:
        cookies, query_params = {}, {}
    dev = dv._dated(_dev(fake, D1))
    st = mpd.state(dev, None, {1, 2}, TODAY, preview=True)
    html = mlp.render_devotional(fake.business(), {}, R(), {"id": tct.ANA, "name": "Ana"}, dev, st)
    assert "lm-pp-over" not in html
    dev2 = dv._dated(_dev(fake, D2))
    html = mlp.render_devotional(fake.business(), {}, R(), {"id": tct.ANA, "name": "Ana"}, dev2,
                                 mpd.state(dev2, None, set(), TODAY, preview=True))
    assert '<button class="lm-btn" type="submit" disabled>Start</button>' in html


# ─── Start over ──────────────────────────────────────────────────────


def test_start_over_a_church_devotional_clears_only_her_marks(bible, fake, monkeypatch):  # noqa: F811
    import member_lumen_plans as mlp
    now = datetime.now(timezone.utc).isoformat()
    fake.t["devotional_progress"][0]["journal"] = "Rest is trust."
    fake.add("devotional_progress", business_id=tct.BIZ, contact_id=tct.BEN, devotional_id=D1, day=1, done_at=now,
             checks=[], journal="")
    c = _app(fake, monkeypatch)
    r = c.post("/my/bible/plans/over", data={"plan": f"devotional:{D1}"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/my/bible/plans/{D1}?done=over"
    assert f"{mlp.VERSION_COOKIE}=" in r.headers["set-cookie"]
    hers = [x for x in fake.t["devotional_progress"] if x["contact_id"] == tct.ANA]
    assert all(x["done_at"] is None for x in hers) and hers[0]["journal"] == "Rest is trust."
    assert next(x for x in fake.t["devotional_progress"] if x["contact_id"] == tct.BEN)["done_at"] == now
    assert not [x for x in fake.t["member_plan_starts"] if x["plan"] == f"devotional:{D1}"]   # the church's dates stand
    html = c.get(f"/my/bible/plans/{D1}?done=over").text
    assert "Started over." in html
    assert f'href="/my/bible/plans/{D1}/3">Read day 3</a>' in html                    # today's day, on the church's days


def test_start_over_a_devotional_started_on_her_own_day(bible, fake, monkeypatch):  # noqa: F811
    fake.add("member_plan_starts", business_id=tct.BIZ, contact_id=tct.ANA, plan=f"devotional:{D2}",
             started_on=(TODAY - timedelta(days=5)).isoformat())
    fake.add("devotional_progress", business_id=tct.BIZ, contact_id=tct.ANA, devotional_id=D2, day=2,
             done_at=datetime.now(timezone.utc).isoformat(), checks=[], journal="")
    c = _app(fake, monkeypatch)
    page = c.get(f"/my/bible/plans/{D2}").text
    assert "Day 1 opens again today, and the days you marked read are cleared." in page
    r = c.post("/my/bible/plans/over", data={"plan": f"devotional:{D2}"}, follow_redirects=False)
    assert r.headers["location"] == f"/my/bible/plans/{D2}?done=over"
    assert next(x for x in fake.t["member_plan_starts"] if x["plan"] == f"devotional:{D2}")["started_on"] == TODAY.isoformat()
    assert all(x["done_at"] is None for x in fake.t["devotional_progress"] if x["devotional_id"] == D2)


def test_start_over_a_reading_plan_runs_it_again_from_today(bible, fake, monkeypatch):  # noqa: F811
    c = _app(fake, monkeypatch)
    page = c.get("/my/bible/plans/gospels-30").text
    over = page[page.index('<details class="lm-pp-over">'):page.index("</details>")]
    assert 'name="plan" value="reading:gospels-30"' in over and "Day 1 opens again today" in over
    r = c.post("/my/bible/plans/over", data={"plan": "reading:gospels-30"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/gospels-30?done=over"
    assert next(x for x in fake.t["member_plan_starts"] if x["plan"] == "reading:gospels-30")["started_on"] == TODAY.isoformat()
    page = c.get("/my/bible/plans/gospels-30?done=over").text
    assert "Started over." in page and "Read day 1" in page and "lm-pp-over" not in page   # started today: nothing to redo


def test_start_over_refuses_what_isnt_hers_to_redo(bible, fake, monkeypatch):  # noqa: F811
    import member_portal_church as mpc
    c = _app(fake, monkeypatch)
    before = [dict(x) for x in fake.t["member_plan_starts"]]
    # a plan she never started: nothing written
    r = c.post("/my/bible/plans/over", data={"plan": "reading:bible-year"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/bible-year"
    # something that isn't a plan: back to Plans
    r = c.post("/my/bible/plans/over", data={"plan": "reading:nope"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible?tab=plans"
    # another site's form
    r = c.post("/my/bible/plans/over", data={"plan": "reading:gospels-30"}, headers={"origin": "https://evil.example"},
               follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/gospels-30?err=error"
    # too much at once
    monkeypatch.setattr(mpc, "_allowed", lambda church, me: False)
    r = c.post("/my/bible/plans/over", data={"plan": "reading:gospels-30"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/gospels-30?err=slow"
    assert fake.t["member_plan_starts"] == before


def test_start_over_in_the_preview_saves_nothing(bible, fake, monkeypatch):  # noqa: F811
    import member_portal_church as mpc

    async def preview(request):
        return {"business": fake.business()}, None, "preview"
    monkeypatch.setattr(mpc, "_signed_in", preview)
    c = _app(fake, monkeypatch)
    before = [dict(x) for x in fake.t["devotional_progress"]]
    r = c.post("/my/bible/plans/over", data={"plan": f"devotional:{D1}"}, follow_redirects=False)
    assert r.headers["location"] == f"/my/bible/plans/{D1}?err=preview"
    assert fake.t["devotional_progress"] == before
