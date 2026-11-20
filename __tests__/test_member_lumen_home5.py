# __tests__/test_member_lumen_home5.py
#
# Look 5.1's Home (Kevin, 2026-11-20: "this is awesome. much better design.
# lets build this including the new still to build!"): the moments
# (member_lumen_stories), the four doors, This week, the composer, and the
# shell around every new-look page (the flat tab bar, the bell before the
# bubble). This week's own pins are in test_member_lumen_home.py. Pins:
#   - the moments are built only from records: the devotional's day (else a
#     pastor's post from the last three days), the next service, each group's
#     gathering within two days, the church's events this week that have a
#     picture; in that order; fewer than two and the row isn't drawn;
#   - each moment's controls: its record's own form or link; a reply only
#     where member messaging lets this member write (the pastor when member
#     messages allow it, else the church's conversation while it's open; the
#     group's chat while it's on); Love only on a post (its own reaction
#     form); Share only on the church's own content with a public page
#     (contract 1: Sunday's message, or the service or an event on the public
#     events page), never a group's gathering, a members' post nor a
#     devotional;
#   - whether the member may write to the pastor is read once, inside Home's
#     gather, and kept (no read on the next Home);
#   - the doors: Prayer's "N new" from the unread count Messages already read,
#     Events this week, Serve's next date, Kids only for someone with the
#     Kids space (never "Check in" as if a phone could check a child in);
#   - group RSVPs for several gatherings come in one read;
#   - the composer opens /my/post (the members' composer); the band sits before the feed;
#   - the sheet: every rule under .lm, the type block still last, the moves
#     only with the phone's yes to motion.

import pathlib
import re
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_gatherings as gg
import member_lumen_stories as mls
import member_lumen_ui as lm
import member_portal_lumen as mlp
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_home import EVENING, NY, TODAY, _client, _group, _occ, church  # noqa: F401

DEV = "00000000-0000-4000-8000-0000000009d1"
POST = "00000000-0000-4000-8000-000000000881"


def _devotional(monkeypatch, author="Pastor James Carter"):
    import devotionals as dv
    dev = {"id": DEV, "title": "Rooted", "day_count": 21, "status": "published", "author": author,
           "starts_on": TODAY - timedelta(days=3), "kind": ""}
    days = [{"title": f"Day {n}", "body": "word " * 300, "scripture": "", "pull": ""} for n in range(1, 22)]
    days[3].update(title="Planted by the Water", scripture="Jeremiah 17:8", pull="Roots go deep before the fruit comes.")
    monkeypatch.setattr(dv, "catalog", lambda b, published=True: [dict(dev)])
    monkeypatch.setattr(dv, "one", lambda b, i, published=True: (dict(dev, days=days), True))


def _post(monkeypatch, *, hours=2, pastor=True, title="Keep Sister Denise in prayer"):
    import church_news as cn
    at = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    post = {"id": POST, "kind": "announcement", "title": title, "body": "She asked the church to pray for rest.",
            "posted_by": tct.BEN, "created_at": at, "pastor": pastor, "author": {"id": tct.BEN, "name": "James Carter"},
            "my_rx": [], "rx": {}, "comment_n": 0, "attach": {}, "comments": "on"}
    monkeypatch.setattr(cn, "home_view", lambda b, me, **kw: ([dict(post)], 1))
    return post


def _moments(html):
    if 'id="lm-mos"' not in html:
        return [], {}
    row = html[html.index('id="lm-mos"'):]
    row = row[:row.index("</nav>")]
    ids = re.findall(r'data-mo="([^"]+)"', row)
    slides = re.findall(r'<section class="lm-mvs".*?</section>', html, re.S)
    return ids, dict(zip(ids, slides))


def _main(html):
    return html[html.index("<main"):html.index("</main>")]


# ─── the moments ─────────────────────────────────────────────────────


def test_the_moments_in_order(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    _devotional(monkeypatch)
    html = _client(fake, monkeypatch).get("/my").text
    ids, slides = _moments(html)
    sun = church["occ"][0]["date"]
    assert ids == [f"dv:{DEV}:4", f"sv:{sun}", f"gr:{tct.GROUP}:{TODAY.isoformat()}"]
    main = _main(html)
    assert main.index('id="lm-mos"') < main.index('class="lm-brief"')        # the row opens Home
    devo = slides[ids[0]]
    assert "Roots go deep before the fruit comes." in devo                 # the devotional's own line
    assert "Jeremiah 17:8" in devo and "Rooted, day 4 of 21" in devo
    assert f'href="/my/bible/plans/{DEV}/4">Read today' in devo
    assert '>Pastor James<' in html                                          # the author, short, under the circle
    sv = slides[ids[1]]
    assert "Sunday Worship" in sv and 'action="/my/rsvp"' in sv and "I&#x27;m coming" in sv
    gr = slides[ids[2]]
    assert 'action="/my/groups/meet/rsvp"' in gr and "11 going" in gr
    # One copy of the viewer, hidden; its script once.
    assert html.count('id="lm-mv"') == 1 and 'role="dialog" aria-modal="true" aria-label="Moments" hidden' in html
    assert html.count("lm-seen") == 1


def test_fewer_than_two_moments_draw_no_row(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    ids, _ = _moments(html)
    assert ids == [] and 'id="lm-mv"' not in html and "lm-seen" not in html  # only Sunday: no row


def test_share_only_on_the_churchs_own(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    _devotional(monkeypatch)
    html = _client(fake, monkeypatch).get("/my").text
    ids, slides = _moments(html)
    sv, gr, devo = slides[ids[1]], slides[ids[2]], slides[ids[0]]
    assert "/my/share." not in html                                          # no share control: no sheet script
    assert "lm-share" not in sv + gr + devo         # no public page: the service off the public events page, a
    assert "nw-rxf" not in sv + gr + devo           # group's gathering, a devotional; Love is a post's reaction only
    # The service on the public events page: shared as that event (contract 1, member_lumen_share).
    church["occ"][0]["public"] = True
    fake.biz[tct.BIZ]["settings"]["events_public"] = {"enabled": True}
    html = _client(fake, monkeypatch).get("/my").text
    ids, slides = _moments(html)
    sv = slides[ids[1]]
    assert ('<a class="lm-share lm-mvac" href="/events" data-share-kind="moment" data-share-title="Sunday Worship"'
            in sv)
    assert html.count('<script src="/my/share.') <= 1                         # the sheet's script (#1986), once
    assert f'data-share-id="event:{church["occ"][0]["entry_id"]}"' in sv and 'aria-label="Share"' in sv
    # Its message, when one is dated that day: shared as the message.
    import member_portal_sermons as mps
    sid = "00000000-0000-4000-8000-000000000611"
    monkeypatch.setattr(mps, "load_library", lambda b: {"series": [], "sermons": [
        {"id": sid, "title": "Hope Has a Name", "preached_on": church["occ"][0]["date"]}]})
    ids, slides = _moments(_client(fake, monkeypatch).get("/my").text)
    sv = slides[ids[1]]
    assert "Hope Has a Name" in sv and f'href="/sermons/{sid}" data-share-kind="moment"' in sv
    assert f'data-share-id="message:{sid}"' in sv
    assert "lm-share" not in slides[ids[2]] + slides[ids[0]]


def test_an_event_with_a_picture_is_a_moment(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    church["occ"].insert(0, _occ("Food Drive", TODAY + timedelta(days=2), n=12, tm="09:00",
                                 eid="00000000-0000-4000-8000-000000000303"))
    church["occ"].insert(0, _occ("Board meeting", TODAY + timedelta(days=1), tm="18:00",
                                 eid="00000000-0000-4000-8000-000000000304"))
    fake.biz[tct.BIZ]["settings"]["member_portal"]["pictures"] = {
        "event:food-drive": {"url": "https://example.org/food.jpg", "look": "colour"}}
    ids, slides = _moments(_client(fake, monkeypatch).get("/my").text)
    assert "ev:00000000-0000-4000-8000-000000000303" in ids
    assert "ev:00000000-0000-4000-8000-000000000304" not in ids             # no picture of its own: not a moment
    ev = slides["ev:00000000-0000-4000-8000-000000000303"]
    assert 'src="https://example.org/food.jpg"' in ev and "12 going" in ev
    assert "lm-share" not in ev                                              # not on the public events page
    church["occ"][1]["public"] = True
    fake.biz[tct.BIZ]["settings"]["events_public"] = {"enabled": True}
    ev = _moments(_client(fake, monkeypatch).get("/my").text)[1]["ev:00000000-0000-4000-8000-000000000303"]
    assert '<a class="lm-share lm-mvac" href="/events" data-share-kind="moment" data-share-title="Food Drive"' in ev
    assert 'data-share-id="event:00000000-0000-4000-8000-000000000303"' in ev
    assert "data-share-img" not in ev                    # its picture is only in the app, not on the website


def test_a_pastors_post_when_no_devotional_runs(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    _post(monkeypatch)
    asked = []

    def may_write(biz, me, other):
        asked.append(other)
        return False
    import member_pastor
    monkeypatch.setattr(member_pastor, "may_message", may_write)
    mlp._MAY_WRITE = None
    c = _client(fake, monkeypatch)
    html = c.get("/my").text
    ids, slides = _moments(html)
    assert ids[0] == f"po:{POST}"
    po = slides[ids[0]]
    assert "Keep Sister Denise in prayer" in po and "She asked the church to pray for rest." in po
    assert re.search(r"<small>\d+[mhd]</small>", po) and ">James Carter<" in po   # how long ago
    assert f'<input type="hidden" name="id" value="{POST}">' in po and 'action="/my/news/react"' in po   # Love
    assert "lm-share" not in po                                              # members only: never shared
    assert f'href="/my/news/{POST}">Read' in po
    assert asked == [tct.BEN]
    # Kept: the next Home asks nothing more.
    c.get("/my")
    assert asked == [tct.BEN]


def test_the_pastors_reply_follows_messaging_rules(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    _post(monkeypatch)
    import member_pastor
    monkeypatch.setattr(member_pastor, "may_message", lambda b, me, o: True)
    mlp._MAY_WRITE = None
    po = _moments(_client(fake, monkeypatch).get("/my").text)[1][f"po:{POST}"]
    assert f'<a class="lm-mvre" href="/my/messages/to/{tct.BEN}">Send James a note…</a>' in po
    monkeypatch.setattr(member_pastor, "may_message", lambda b, me, o: False)
    mlp._MAY_WRITE = None
    po = _moments(_client(fake, monkeypatch).get("/my").text)[1][f"po:{POST}"]
    assert "/my/messages/to/" not in po                                      # not allowed: no private reply


def test_an_old_post_or_a_members_post_is_no_word(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    now = datetime.now(timezone.utc)
    assert mls.pastor_post([{"id": "a", "pastor": True, "posted_by": "x", "title": "Hi", "created_at":
                             (now - timedelta(days=4)).isoformat()}], now) is None
    assert mls.pastor_post([{"id": "a", "pastor": False, "posted_by": "x", "title": "Hi", "created_at":
                             now.isoformat()}], now) is None
    new = {"id": "b", "pastor": True, "posted_by": "x", "title": "Hi", "created_at": (now - timedelta(hours=1)).isoformat()}
    old = {"id": "c", "pastor": True, "posted_by": "x", "title": "Hi", "created_at": (now - timedelta(days=2)).isoformat()}
    assert mls.pastor_post([old, new], now)["id"] == "b"


def test_the_church_conversation_reply_only_when_open(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    _devotional(monkeypatch)
    import member_portal_threads as mpt

    async def counts(biz, me):
        return {"notes": {}, "chat": 0, "total": 0}
    monkeypatch.setattr(mpt, "counts", counts)
    ids, slides = _moments(_client(fake, monkeypatch).get("/my").text)
    assert '<a class="lm-mvre" href="/my/inbox/church">Ask the church…</a>' in slides[ids[1]]

    async def closed(biz, me):
        return None
    monkeypatch.setattr(mpt, "counts", closed)
    ids, slides = _moments(_client(fake, monkeypatch).get("/my").text)
    assert "/my/inbox/church" not in slides[ids[1]] and "lm-mvre" not in slides[ids[0]]


def test_the_viewer_never_speaks_builder_words(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    _devotional(monkeypatch)
    html = _client(fake, monkeypatch).get("/my").text
    for w in ("GitHub", "Claude", "builder", "Solutionist System"):
        assert w not in html[html.index('id="lm-mos"'):html.index('class="lm-brief"')]


def test_the_row_escapes_and_draws_nothing_alone():
    m = mls.moment(mid="sv:1", label="<b>", ring="", bg="", face="", name="A & B", href="/my", kicker="K", line="<x>")
    assert mls.row([m]) == ""
    two = mls.row([m, dict(m, id="sv:2")])
    assert "&lt;x&gt;" in two and "<x>" not in two and "A &amp; B" in two
    assert mls.clip("one two three four", 9) == "one two…" and mls.short_name("Pastor James Carter") == "Pastor James"
    assert mls.ago((datetime(2026, 1, 1, 10, tzinfo=timezone.utc)).isoformat(),
                   datetime(2026, 1, 1, 12, tzinfo=timezone.utc)) == "2h"


# ─── the doors ───────────────────────────────────────────────────────


def _doors(html):
    d = html[html.index('class="lm-doors"'):]
    d = d[:d.index("</nav>")]
    return re.findall(r'<a class="lm-door" href="([^"]+)">.*?<b>([^<]+)</b><small( class=new)?>([^<]+)</small></a>', d)


def test_the_doors_read_the_records(church, fake, monkeypatch):  # noqa: F811
    sun = church["occ"][0]["date"]
    church["serving"] = {"coming": [{"id": "a1", "place": "Front doors", "team": "Greeters", "group_id": "",
                                     "call_time": "09:45", "with": [],
                                     "service": {"day": sun, "at": datetime.combine(date.fromisoformat(sun), time(10, 30), tzinfo=NY),
                                                 "title": "Sunday service"}}],
                         "asks": [], "teams": [{"name": "Greeters"}]}
    doors = _doors(_client(fake, monkeypatch).get("/my").text)
    n = sum(1 for o in church["occ"] if 0 <= (date.fromisoformat(o["date"]) - TODAY).days < 7)
    assert doors[0] == ("/my/connect#lm-pray-h", "Prayer", "", "Ask for prayer")
    assert doors[1] == ("/my/events", "Events", "", f"{n} this week")
    assert doors[2] == ("/my/connect#lm-sv-h", "Serve", "", f"Sun 9:45")
    assert len(doors) == 3                                                   # no Kids space: no Kids door


def test_prayer_new_from_the_count_messages_read(church, fake, monkeypatch):  # noqa: F811
    import member_portal_threads as mpt

    async def counts(biz, me):
        return {"notes": {f"group:{tct.GROUP}": {"last": None, "unread": 4, "prayer": 3},
                          "church": {"last": None, "unread": 1}}, "chat": 0, "total": 5}
    monkeypatch.setattr(mpt, "counts", counts)
    doors = _doors(_client(fake, monkeypatch).get("/my").text)
    assert doors[0] == (f"/my/inbox/group/{tct.GROUP}", "Prayer", " class=new", "3 new")
    assert mpt.prayer_new(None) == (0, [])


def test_the_kids_door_only_with_the_kids_space(church, fake, monkeypatch):  # noqa: F811
    c = _client(fake, monkeypatch)
    import member_spaces as msp

    async def resolve(b, me, wanted=""):
        return {"space": "church", "youth": False, "leader": {}, "kids_parent": True, "options": ["church", "kids"]}
    monkeypatch.setattr(msp, "resolve_async", resolve)
    doors = _doors(c.get("/my").text)
    assert doors[-1] == ("/my/space?to=kids", "Kids", "", "Your kids")
    html = c.get("/my").text
    assert "Check in<" not in html                                           # a phone never checks a child in


def test_the_summary_counts_prayer_wall_notes(monkeypatch):
    import church_threads as ct
    rows = [{"thread": f"group:{tct.GROUP}", "direction": "church", "created_at": "2026-11-20T10:00:00+00:00",
             "url": f"/my/groups/{tct.GROUP}/prayer"},
            {"thread": f"group:{tct.GROUP}", "direction": "church", "created_at": "2026-11-20T11:00:00+00:00",
             "url": f"/my/groups/{tct.GROUP}/board"},
            {"thread": "church", "direction": "church", "created_at": "2026-11-20T11:00:00+00:00",
             "url": f"/my/groups/{tct.GROUP}/prayer"}]
    monkeypatch.setattr(ct, "_rows", lambda path: rows if "contact_id=eq." in path else [])
    monkeypatch.setattr(ct, "reads", lambda b, c: {})
    got = ct.summary(tct.BIZ, tct.ANA, [tct.GROUP])
    assert got[f"group:{tct.GROUP}"]["unread"] == 2 and got[f"group:{tct.GROUP}"]["prayer"] == 1
    assert "prayer" not in got["church"]


# ─── the reads ───────────────────────────────────────────────────────


def test_rsvps_for_several_gatherings_in_one_read(church, fake, monkeypatch):  # noqa: F811
    _group(fake)
    g2 = tct.cid(1901)
    fake.add("groups", id=g2, business_id=tct.BIZ, name="Women of Grace", active=True, kind="small_group",
             meets="Saturdays", location="Room 104", chat_on=False, meet_day=(TODAY.weekday() + 1) % 7,
             meet_time="18:30:00", meet_every=1, meet_skips=[], meet_from=None, meet_nth=None, join_mode="open")
    fake.add("group_members", group_id=g2, business_id=tct.BIZ, contact_id=tct.ANA, role="member")
    for kept in (gg._ANSWERS,):
        kept.clear()
    c = _client(fake, monkeypatch)
    fake.gets.clear()
    html = c.get("/my").text
    assert len([g for g in fake.gets if g.startswith("/group_rsvps")]) == 1
    ids, slides = _moments(html)
    assert f"gr:{g2}:{(TODAY + timedelta(days=1)).isoformat()}" in ids     # tomorrow: within two days
    assert "lm-mvre" not in slides[f"gr:{g2}:{(TODAY + timedelta(days=1)).isoformat()}"]   # its chat is off
    fake.gets.clear()
    c.get("/my")
    assert not [g for g in fake.gets if g.startswith("/group_rsvps")]       # kept


def test_answers_many_one_gathering_reads_as_answers(fake, monkeypatch):  # noqa: F811
    gg._ANSWERS.clear()
    fake.gets.clear()
    gg.answers_many(tct.BIZ, [(tct.GROUP, TODAY)])
    assert len(fake.gets) == 1 and f"group_id=eq.{tct.GROUP}" in fake.gets[0]


# ─── the composer and the shell ──────────────────────────────────────


def test_the_composer(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    comp = html[html.index('<div class="lm-hcp">'):]
    comp = comp[:comp.index('<div class="lm-band"')]
    assert '<a class="lm-hcpin" href="/my/post">Share a praise or a prayer…</a>' in comp
    assert '<a class="lm-icb" href="/my/post" aria-label="Share a photo">' in comp
    assert '<span class="lm-hcpav" aria-hidden="true">AR</span>' in comp


def test_the_sheet():
    text = lm.css()
    parts = lm.templates()
    import member_lumen_fonts
    import member_lumen_stories
    assert parts[-1].template == member_lumen_fonts.template().template          # the type block last
    assert parts.index(member_lumen_stories.CSS) < len(parts) - 1
    with pytest.raises(ValueError):
        mls.share_link("/", "post", "x", "A member's post")                 # never anything but the church's own
    css = member_lumen_stories.CSS.template
    # The segments fill and the slides rise only with the phone's yes to motion.
    for anim in ("animation:lmMvFill", "animation:lmMvIn"):
        assert re.search(r"@media \(prefers-reduced-motion:no-preference\)\{[^@]*" + anim, css), anim
    assert "lm-ind" not in text and ".lm-nav" in text
