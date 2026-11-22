# __tests__/test_member_lumen_home_feed_cards.py
#
# Kevin's Home plan (2026-11-21, "yes to everything"), part four: the feed's
# church cards, and the older sections gone.
#   - After the posts, the church's own records as cards, in the mock's
#     styles: its newest message ("New message" while it's new, else
#     "Latest message"; left out when a post carries it), with rows under it
#     for Meet the pastor (someone new), Pick up where you left off (Watch's
#     place on the member's own record: no read) and the class they're in;
#     its events after this week (This week has the rest), Going and, where
#     the public events page has it, Share; the verse of the day with Share
#     as a picture; the church's own tiles; then "You're all caught up" and
#     nothing below it.
#   - A failed news read still shows the church's cards, never "caught up";
#     when the feed already said it between new and seen, it isn't said twice.
#   - Share only on the church's own (a message, an event, the verse):
#     never on a member's post or a prayer request.
#   - Gone from the new-look Home: Also for you, Coming up, Today, the
#     message tile, Your group, prayer, and the foot cards; installing the
#     app moved to Me. Home stops reading the reading plan's days.

import pathlib
import re
import sys
import time as _time
from datetime import timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_portal_lumen as mlp
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_home import TODAY, _client, _main, _occ, church  # noqa: F401
from test_member_lumen_home_stories import MSG, OLD, _library, klass  # noqa: F401

FAR = "00000000-0000-4000-8000-0000000003c1"


def _church(html):
    i = html.index('<section class="lm-feed lf-church"')
    return html[i:html.index("</section>", i) + len("</section>")]


def _watched(fake, sid, pos=2700, dur=3720):
    ana = next(c for c in fake.t["contacts"] if c["id"] == tct.ANA)
    meta = dict(ana.get("metadata") or {})
    meta["member_watch"] = {"p": {sid: [pos, dur, int(_time.time()) - 60, "v"]}, "s": {}}
    ana["metadata"] = meta


@pytest.fixture
def quiet(church, fake, monkeypatch):  # noqa: F811
    """A church with no posts (Love City's shape): the newest message from
    last Sunday, one event two weeks out on the public events page."""
    monkeypatch.setattr(mlp, "_CLASS", None)
    monkeypatch.setattr(mlp, "_STREAMS", None)
    _library(monkeypatch)
    church["occ"].append(_occ("Oh Give Thanks", TODAY + timedelta(days=14), n=5, eid=FAR))
    church["occ"][-1]["public"] = True
    fake.biz[tct.BIZ]["settings"]["events_public"] = {"enabled": True}
    return church


def test_a_church_with_no_posts_has_a_feed(quiet, fake, monkeypatch, klass):  # noqa: F811
    _watched(fake, OLD)
    html = _client(fake, monkeypatch).get("/my").text
    main = _main(html)
    cards = _church(main)
    assert main.index('class="lm-hcp"') < main.index('<section class="lm-feed lf-church"')
    # The newest message, still new, with Pick up and the class under it.
    msg = re.search(r'<article class="lf-post lf-pmsg" id="msg-[^"]+".*?</article>', cards, re.S).group(0)
    assert f'id="msg-{MSG}"' in msg and "New message · " in msg and "Sunday, November 15 (Part 1)" in msg
    rows = re.findall(r'<a class="lf-crow" href="([^"]+)">(.*?)</a>', msg, re.S)
    assert [h for h, _ in rows] == [f"/my/sermons/{OLD}", "/my/classes"]
    assert "<b>Pick up where you left off</b><small>Sunday, November 8 · 17 min left</small>" in rows[0][1]
    assert "<b>The Making: Foundation</b><small>Lesson 1 of 4 · Continue</small>" in rows[1][1]
    assert '<i style="width:73%">' in rows[0][1]
    # The event two weeks out: its card, Going, and Share (it is on the public events page).
    ev = re.search(r'<article class="lf-post lf-pev" aria-label="Event: Oh Give Thanks".*?</article>', cards,
                   re.S).group(0)
    assert "Event · " in ev and ">Oh Give Thanks</a></h3>" in ev
    assert 'action="/my/rsvp"' in ev and 'name="action" value="coming"' in ev and ">Going</button>" in ev
    assert f'data-share-kind="event"' in ev and f'data-share-id="{FAR}"' in ev
    assert "Maybe" not in ev                                         # no route for it: left out
    # The verse of the day, with Share as a picture (its Your story picture).
    vod = re.search(r'<article class="lf-post lf-pvod">.*?</article>', cards, re.S).group(0)
    assert "Verse of the day" in vod and 'data-share-kind="verse"' in vod and "Share as a picture</a>" in vod
    assert re.search(r'data-share-id="[0-9A-Z]{3}\.\d+\.\d+', vod)
    # Then "You're all caught up", and nothing below it.
    assert cards.index('lf-pmsg') < cards.index('lf-pev') < cards.index('lf-pvod') < cards.index("all caught up")
    end = main[main.index("You&#x27;re all caught up"):]
    assert "<section" not in end and "<article" not in end


def test_the_feeds_order_with_posts(quiet, fake, monkeypatch):  # noqa: F811
    import church_news as cn
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(cn, "home_view", lambda b, me, **kw: ([{
        "id": "00000000-0000-4000-8000-000000000881", "kind": "announcement", "title": "Food Drive Saturday",
        "body": "Bring canned goods.", "created_at": now, "published_at": now, "reactions": {}, "mine": [],
        "comment_count": 0}], 1))
    html = _main(_client(fake, monkeypatch).get("/my").text)
    assert html.index("Food Drive Saturday") < html.index('<section class="lm-feed lf-church"')   # posts first


def test_pick_up_skips_the_message_on_the_card(quiet, fake, monkeypatch):  # noqa: F811
    _watched(fake, MSG)
    cards = _church(_client(fake, monkeypatch).get("/my").text)
    assert "Pick up where you left off" not in cards                 # its card's Watch picks it up
    _watched(fake, OLD, pos=3700, dur=3720)                          # watched to the end: nothing to pick up
    assert "Pick up where you left off" not in _church(_client(fake, monkeypatch).get("/my").text)


def test_an_old_message_is_the_latest_message(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setattr(mlp, "_CLASS", None)
    _library(monkeypatch, days_ago=20)
    cards = _church(_client(fake, monkeypatch).get("/my").text)
    assert f'id="msg-{MSG}"' in cards and "Latest message · " in cards and "New message" not in cards


def test_events_this_week_stay_in_this_week(quiet, fake, monkeypatch):  # noqa: F811
    quiet["occ"][1]["date"] = (TODAY + timedelta(days=1)).isoformat()      # Prayer Night: this week, whatever the day
    cards = _church(_client(fake, monkeypatch).get("/my").text)
    assert "Sunday Worship" not in cards and "Prayer Night" not in cards    # both this week: cards above
    titles = re.findall(r'aria-label="Event: ([^"]+)"', cards)
    assert titles == ["Oh Give Thanks"]
    for i in range(5):
        quiet["occ"].append(_occ(f"Later {i}", TODAY + timedelta(days=20 + i), eid=f"00000000-0000-4000-8000-0000000003d{i}"))
    titles = re.findall(r'aria-label="Event: ([^"]+)"', _church(_client(fake, monkeypatch).get("/my").text))
    assert titles == ["Oh Give Thanks", "Later 0", "Later 1"]          # three at most


def test_a_failed_news_read_keeps_the_cards_but_never_says_caught_up(quiet, fake, monkeypatch):  # noqa: F811
    import church_news as cn
    monkeypatch.setattr(cn, "home_view", lambda b, me, **kw: (None, 0))
    html = _client(fake, monkeypatch).get("/my").text
    cards = _church(html)
    assert f'id="msg-{MSG}"' in cards and "all caught up" not in html


def test_share_only_on_the_churchs_own(quiet, fake, monkeypatch):  # noqa: F811
    import church_news as cn
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(cn, "home_view", lambda b, me, **kw: ([{
        "id": "00000000-0000-4000-8000-000000000882", "kind": "praise", "title": "", "body": "God is good!",
        "posted_by": tct.BEN, "source": "member", "created_at": now, "published_at": now, "reactions": {},
        "mine": [], "comment_count": 0}], 1))
    html = _main(_client(fake, monkeypatch).get("/my").text)
    for art in re.findall(r"<article class=\"lf-post[^\"]*\".*?</article>", html, re.S):
        if "lm-share" in art:
            assert re.match(r'<article class="lf-post (lf-pmsg|lf-pev|lf-pvod)"', art), art[:120]


def test_the_older_sections_are_gone_and_install_is_on_me(quiet, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    main = _main(c.get("/my").text)
    for gone in ('class="lm-also"', 'id="lm-cu-h"', 'id="lm-today-h"', 'id="lm-grp-h"', 'id="lm-msg-h"',
                 'id="lm-pray-h"', 'id="mb-install"', 'id="np-card"', 'href="/my/ask"'):
        assert gone not in main, gone
    me = c.get("/my/me").text
    assert 'id="mb-install"' in me and "on your home screen" in me
    import member_push
    monkeypatch.setattr(member_push, "ready", lambda: True)
    fake.biz[tct.BIZ]["settings"]["member_portal"]["notifications"] = {k: True for k in member_push.KIND_KEYS}
    me = c.get("/my/me").text
    assert 'id="np-card"' in me and "Get notified" in me                 # the alerts nudge moved to Me too
    assert 'id="np-card"' not in _main(c.get("/my").text)
    # Today's look keeps its own Home and Me.
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    assert 'id="mb-install"' in c.get("/my").text


def test_home_no_longer_reads_the_reading_plans_days(quiet, fake, monkeypatch):  # noqa: F811
    fake.biz[tct.BIZ]["settings"]["reading_plan"] = {"key": "psalms-proverbs-31",
                                                     "start": (TODAY - timedelta(days=3)).isoformat()}
    c = _client(fake, monkeypatch)
    fake.gets.clear()
    c.get("/my")
    assert not any(g.startswith("/reading_progress") for g in fake.gets)
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    fake.gets.clear()
    c.get("/my")
    assert any(g.startswith("/reading_progress") for g in fake.gets)       # today's look still ticks it
