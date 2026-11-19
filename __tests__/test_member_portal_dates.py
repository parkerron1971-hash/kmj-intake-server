"""Dates on the member app's Lead tab (member_portal_dates.py;
docs/CHURCH_SCHEDULE.md, PR S1-5). Kevin, 2026-11-18: "this is for when
leaders are planning time off and have certain obiligations so that we as a
church can plan around meeting".

Pins, at New Hope (church_three: a made-up church, every name in it made up),
through the real engine (church_schedule, church_over) and the member routes,
on test_member_portal_assign's harness:
  * the page, in its order: Waiting for your yes (only with some), Ask for
    time off, I can't make it, My dates, Who else is away; for a leader, for
    someone over people, for someone in the office who leads nothing else,
    for the owner's own person
  * A MEMBER-APP SESSION IS A PERSON: the owner's own person and the person of
    whoever oversees the office get no across-the-board view. They read a
    reason and answer only what went to them; every call into the engine is
    made as a person
  * a reason and an answer's note only where shape() allows; "Who else is
    away" never has either; no id, no office word, no title word and no key
    on the screen
  * every write: ask, can't make it, yes, not this one with a note, take
    back; the preview never writes; a cross-site POST is refused and Origin:
    null from this address is let through; closed, or before its tables, is
    a 404 and the Dates entry is gone; a refusal comes back as plain words
  * who covers: the people on the schedule at this church, never the asker,
    a bounded list
  * days in the church's own clock, said plainly; short notice said gently
    and never blocked
  * the Lead tab's switcher and who gets the tab, from what is kept a minute
    (church_schedule.section), never a fresh read on every page
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_over as co  # noqa: E402
import church_schedule as cs  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_schedule_tell as tell  # noqa: E402
import church_three as c3  # noqa: E402
import member_portal_dates as mpd  # noqa: E402
import member_portal_lead as mpl  # noqa: E402
import sb_clients  # noqa: E402
from church_schedule_fake import day  # noqa: E402
from church_three import GRACE  # noqa: E402

HOPE = c3.NEW_HOPE                       # a made-up church of 500: every name in it is made up
SECRET = "Surgery for my mother that week"
OTHER = "A family matter out of town"
NOTE = "Praying for her and for you"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
OFFICE_WORDS = re.compile(r"\b(login|logins|seat|seats|manager|admin|lane|lanes|duty|duties|check_key|startup)\b", re.I)
TITLE_WORDS = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|overseers?|directors?|executive|"
                         r"treasurers?|secretary|owners?|trustees?|reverend|apostles?|prophets?)\b", re.I)
KEYS = re.compile(r"\b[a-z]+_[a-z_]+\b")                 # time_off, short_notice, a role key
OWNER_CALLED = "Pastor Nathan"           # the church's own name for its owner: the one title on any page, as a name
ROUTES = ("/my/lead/dates/ask", "/my/lead/dates/cant", "/my/lead/dates/{id}/answer", "/my/lead/dates/{id}/withdraw")


@pytest.fixture
def db(monkeypatch, request):
    """A database with step 1's file alone; `db` asked for with True
    (indirect) has step 2's file too."""
    d = fake.build(monkeypatch, limits=bool(getattr(request, "param", False)))
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **kw: True)
    return d


@pytest.fixture
def shell(monkeypatch):
    """member_portal's shell, keeping just the body and its arguments, so
    the tests read what the page itself writes."""
    import member_portal
    seen = {}

    def fake_shell(biz, site, title, body, **kw):
        seen.update(kw, title=title)
        return body
    monkeypatch.setattr(member_portal, "_shell", fake_shell)
    return seen


@pytest.fixture
def app(db, monkeypatch):
    """The member routes, signed in as `app.state["me"]` (a person) at their church."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import member_portal_church as mpc
    a = FastAPI()
    a.include_router(mpd.router)
    state = {"me": None, "biz": HOPE, "unavailable": False}

    async def signed_in(request):
        biz = c3.church(db, state["biz"])
        if state["unavailable"]:
            return {"business": biz, "site": {}}, None, state["unavailable"]
        return {"business": biz, "site": {}}, state["me"], False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    c = TestClient(a)
    c.state, c.db = state, db
    return c


def me(db, biz, handle):
    cid = db.who[biz][handle]
    name = next(x["name"] for x in db.t["contacts"] if x["id"] == cid)
    return {"id": cid, "name": name, "email": ""}


def page(db, handle, sub="/my/lead/dates", biz=HOPE, **q):
    return asyncio.run(mpl.serve(SimpleNamespace(query_params=q), c3.church(db, biz), {}, me(db, biz, handle), sub))


def text(html):
    """What's on the screen: no tags, no form addresses, no hidden values."""
    out = re.sub(r"<[^>]+>", " ", re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S))
    return re.sub(r"\s+", " ", out)


def as_(app, handle, biz=HOPE):
    app.state.update(biz=biz, me=me(app.db, biz, handle), unavailable=False)


def post(app, path, **form):
    return app.post(path, data=form, follow_redirects=False)


def went(r):
    """Where a write sent the browser back to: the page, with one short code."""
    assert r.status_code == 303, r.text
    return r.headers["location"]


def asks(db, biz=HOPE):
    return [r for r in db.t["church_away_asks"] if r["business_id"] == biz]


def facts(db, biz=HOPE):
    return [s for s in db.t["serve_away"] if s["business_id"] == biz]


def ask(app, who="elena", **form):
    """A planned ask through the page's own route; answers with its row."""
    as_(app, who)
    form = {"start": day(30), "end": day(37), "kind": "time_off", **form}
    r = post(app, "/my/lead/dates/ask", **form)
    assert went(r).startswith("/my/lead/dates?done="), r.headers["location"]
    return asks(app.db)[-1]


def church(db, biz=HOPE):
    return co.Church(c3.church(db, biz))


def person(db, handle, biz=HOPE):
    return co.who(co.PERSON, db.who[biz][handle])


def wrote(db):
    """Every write to the schedule's tables so far."""
    return ([p for p, _r in db.posts if p.startswith(("/church_away_asks", "/rpc/church_away_settle"))],
            [dict(r) for r in db.t["church_away_asks"]], [dict(r) for r in db.t["serve_away"]])


# ─── The page ─────────────────────────────────────────────────────────

def test_a_leader_sees_ask_cant_their_own_dates_and_who_else_is_away_in_that_order(app, db, shell):
    waiting = ask(app, reason=SECRET, cover=db.who[HOPE]["esther"])
    yes = ask(app, start=day(50), end=day(51))
    as_(app, "amara")
    assert went(post(app, f"/my/lead/dates/{yes['id']}/answer", ans="yes")).endswith("done=dt_yes")
    ask(app, "yusuf", start=day(20), end=day(22))
    as_(app, "amara")
    post(app, f"/my/lead/dates/{asks(db)[-1]['id']}/answer", ans="yes")
    html, status = page(db, "elena")
    assert status == 200 and shell["tab"] == "lead" and shell["wide"] is True and shell["title"] == "Dates"
    words = text(html)
    order = [words.index(h) for h in ("Ask for time off", "I can’t make it", "My dates", "Who else is away")]
    assert order == sorted(order) and "Waiting for your yes" not in words, "nothing waits on her, so no such part"
    assert "Fri, Dec 18 to Fri, Dec 25" in words and "Waiting for Amara Stone’s yes." in words
    assert "Your reason · private " + SECRET in words and "Covering Esther Moss" in words
    assert "Amara Stone said yes on Wed, Nov 18. It’s on the calendar." in words
    assert "Yusuf Grant Tue, Dec 8 to Thu, Dec 10" in words, "someone else away: a name and the days"
    assert f'action="/my/lead/dates/{waiting["id"]}/withdraw"' in html, "ids ride in form addresses"
    assert "Things that repeat" not in words, "that part comes with its own PR"
    assert not UUID.search(words), "no ids on the screen"
    for rule in (OFFICE_WORDS, TITLE_WORDS, KEYS):
        assert not rule.search(words), rule.search(words)


def test_someone_over_people_sees_what_waits_for_their_yes_first(app, db, shell):
    one = ask(app, reason=SECRET, cover_name="A friend from the choir")
    two = ask(app, "yusuf", start=day(3), end=day(3), kind="commitment")
    html, status = page(db, "amara")
    words = text(html)
    assert status == 200 and words.index("Waiting for your yes") < words.index("Ask for time off")
    assert "Waiting for your yes 2 waiting" in words
    assert "Yusuf Grant Another commitment Sat, Nov 21 Short notice" in words
    assert "Elena Ruiz Time off Fri, Dec 18 to Fri, Dec 25 Their reason · private " + SECRET in words
    assert "Covering A friend from the choir" in words and "Nobody is covering yet." in words
    for a in (one, two):
        assert html.count(f'action="/my/lead/dates/{a["id"]}/answer"') == 2, "Yes, and Not this one with a note"
    assert 'name="note" maxlength="300"' in html
    assert re.search(r'<a href="/my/lead/dates" aria-current="page">Dates · 2</a>', html)
    assert "From Chief Yusuf asked to be away Sat, Nov 21. It’s waiting for your yes" in words
    assert not UUID.search(words) and not OFFICE_WORDS.search(words) and not KEYS.search(words)
    assert not TITLE_WORDS.search(words.replace(OWNER_CALLED, "")), TITLE_WORDS.search(words.replace(OWNER_CALLED, ""))


def test_someone_in_the_office_who_leads_nothing_else_gets_the_tab_and_lands_on_dates(db, shell, monkeypatch):
    import member_portal
    biz, tessa, hugo = c3.church(db, HOPE), me(db, HOPE, "tessa"), me(db, HOPE, "hugo")
    assert cs.roster(church(db)).group_of(tessa["id"]) == "office" and cs.section(biz, hugo["id"]) is None
    assert asyncio.run(member_portal._leads(HOPE, tessa["id"], biz, tessa)) is True
    assert asyncio.run(member_portal._leads(HOPE, hugo["id"], biz, hugo)) is False, "not on it: no change at all"
    html, status = page(db, "tessa", sub="/my/lead")
    words = text(html)
    assert status == 200 and "Ask for time off" in words and "It goes to " + OWNER_CALLED in words
    assert not OFFICE_WORDS.search(words) and not UUID.search(words)
    monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    assert asyncio.run(member_portal._leads(HOPE, tessa["id"], biz, tessa)) is False, "closed: as before"


def test_the_owners_own_person_needs_no_yes_and_the_page_says_so(app, db, shell):
    words = text(page(db, "nathan")[0])
    assert "Nobody is over you here, so your time away goes straight on the calendar." in words
    assert "Put it on the calendar" in words and "short notice" not in words.lower()
    as_(app, "nathan")
    assert went(post(app, "/my/lead/dates/ask", start=day(5), end=day(6), kind="time_off")).endswith("done=dt_set")
    [row] = asks(db)
    assert (row["state"], row["to_user_id"], row["to_contact_id"], row["flags"]) == ("yes", None, None, [])
    assert len(facts(db)) == 1
    words = text(page(db, "nathan", done="dt_set")[0])
    assert "It’s on the calendar." in words and "On the calendar. It needed no yes." in words


def test_someone_with_nothing_here_gets_a_few_plain_words_and_no_page(db, shell):
    html, status = page(db, "hugo")
    assert status == 404 and "Dates is for the people on the leaders schedule" in text(html)
    assert "Ask for time off" not in html and "<form" not in html


def test_taken_off_the_schedule_but_still_over_someone_they_see_only_what_waits_for_their_yes(app, db, shell):
    got = ask(app, reason=SECRET)
    db.t["church_schedule_people"].append({"business_id": HOPE, "contact_id": db.who[HOPE]["amara"],
                                           "listed": "remove", "grp": None})
    cs.forget(HOPE)
    assert cs.section(c3.church(db, HOPE), db.who[HOPE]["amara"]) == {"waiting": 1}
    html, status = page(db, "amara")
    words = text(html)
    assert status == 200 and "Waiting for your yes" in words and SECRET in words
    assert "Ask for time off" not in words and "Who else is away" not in words and "I can’t make it" not in words
    assert "You aren’t on the leaders schedule yourself" in words
    as_(app, "amara")
    assert went(post(app, "/my/lead/dates/ask", start=day(30), kind="time_off")).endswith("err=dt_not_on")
    assert went(post(app, f"/my/lead/dates/{got['id']}/answer", ans="yes")).endswith("done=dt_yes")


# ─── A member-app session is a person, never a login ──────────────────

def test_the_owners_person_and_the_office_overseers_person_get_no_across_the_board_view(app, db, shell):
    """Decision 6. Nathan is the one person the owner is; Owen is the person
    of the login that oversees the office. In the office app each reads
    every ask and may answer any. Here they are people: this ask went to
    Amara, so neither reads its reason, sees it waiting, or answers it."""
    got = ask(app, reason=SECRET, cover=db.who[HOPE]["esther"])
    ch = church(db)
    assert got["to_contact_id"] == db.who[HOPE]["amara"]
    assert ch.owner_person == db.who[HOPE]["nathan"] and db.who[HOPE]["owen@"] in cs.office_overseers(ch)
    for login in (ch.owner, db.who[HOPE]["owen@"]):
        assert cs.sees_reason(ch, co.who(co.LOGIN, login), got), "the office app would show it to them"
    for handle in ("nathan", "owen"):
        html, status = page(db, handle)
        assert status == 200 and SECRET not in html, handle
        assert "Waiting for your yes" not in text(html) and got["id"] not in html, handle
        assert "Elena Ruiz Fri" not in text(html), "a waiting ask that isn't theirs is not on their page at all"
        as_(app, handle)
        assert went(post(app, f"/my/lead/dates/{got['id']}/answer", ans="yes")).endswith("err=dt_not_yours"), handle
        assert went(post(app, f"/my/lead/dates/{got['id']}/answer", ans="no", note="x")).endswith("err=dt_not_yours")
        assert went(post(app, f"/my/lead/dates/{got['id']}/withdraw")).endswith("err=dt_not_asker"), handle
        assert cs.section(c3.church(db, HOPE), db.who[HOPE][handle]) == {"waiting": 0}, handle
    assert asks(db)[0]["state"] == "asked" and asks(db)[0]["decided_note"] is None and facts(db) == []
    as_(app, "amara")
    assert went(post(app, f"/my/lead/dates/{got['id']}/answer", ans="yes")).endswith("done=dt_yes")
    for handle in ("nathan", "owen"):
        html = page(db, handle)[0]
        assert "Elena Ruiz Fri, Dec 18 to Fri, Dec 25 Covering: Esther Moss" in text(html), "the away date, as anyone"
        assert SECRET not in html, handle


def test_what_went_to_the_login_tied_to_exactly_them_is_theirs_and_nothing_else_is(app, db, shell):
    """Sunny's ask goes to the login that oversees the office, and that login
    is Owen: in the member app it is his to read and answer. Amara's goes to
    the owner's login, and the owner is Nathan."""
    to_owen, to_nathan = ask(app, "sunny", reason=SECRET), ask(app, "amara", reason=OTHER, start=day(40), end=day(41))
    assert to_owen["to_user_id"] == db.who[HOPE]["owen@"] and to_nathan["to_user_id"] == church(db).owner
    owen, nathan = page(db, "owen")[0], page(db, "nathan")[0]
    assert SECRET in owen and OTHER not in owen and SECRET not in nathan and OTHER in nathan
    as_(app, "owen")
    assert went(post(app, f"/my/lead/dates/{to_nathan['id']}/answer", ans="yes")).endswith("err=dt_not_yours")
    assert went(post(app, f"/my/lead/dates/{to_owen['id']}/answer", ans="yes")).endswith("done=dt_yes")
    row = next(r for r in asks(db) if r["id"] == to_owen["id"])
    assert row["decided_by_contact_id"] == db.who[HOPE]["owen"] and row["decided_by_user_id"] is None, "as a person"


def test_every_call_into_the_engine_is_made_as_a_person(app, db, shell, monkeypatch):
    """Whoever is signed in, the owner's own person and the office
    overseer's included: the page and its writes hand the engine a person."""
    seen = []
    for name in ("ask", "answer", "withdraw", "mine", "waiting", "calendar"):
        real = getattr(cs, name)

        def spy(ch, who, *a, _real=real, _name=name, **k):
            seen.append((_name, dict(who)))
            return _real(ch, who, *a, **k)
        monkeypatch.setattr(cs, name, spy)
    got = ask(app, "sunny")
    mine = ask(app, "nathan", start=day(9), end=day(9))
    for handle in ("nathan", "owen", "tessa", "amara"):
        page(db, handle)
        as_(app, handle)
        post(app, f"/my/lead/dates/{got['id']}/answer", ans="no", note="x")
        post(app, f"/my/lead/dates/{mine['id']}/withdraw")
        post(app, "/my/lead/dates/cant", start=day(0))
    assert {n for n, _w in seen} == {"ask", "answer", "withdraw", "mine", "waiting", "calendar"}
    people = {c["id"] for c in db.t["contacts"] if c["business_id"] == HOPE}
    for name, who in seen:
        assert who["kind"] == co.PERSON and who["id"] in people, (name, who)
    assert all(r["made_by"] is None and r["decided_by_user_id"] is None for r in asks(db))


# ─── A reason and a note, only where they may be read ─────────────────

def test_a_reason_and_an_answers_note_show_only_where_they_may_be_read(app, db, shell):
    no = ask(app, reason=SECRET)
    yes = ask(app, reason=OTHER, start=day(44), end=day(45), cover=db.who[HOPE]["esther"])
    before = page(db, "amara")[0]
    assert SECRET in before and OTHER in before, "they went to her: she reads why before she answers"
    as_(app, "amara")
    assert went(post(app, f"/my/lead/dates/{no['id']}/answer", ans="no", note=NOTE)).endswith("done=dt_no")
    assert went(post(app, f"/my/lead/dates/{yes['id']}/answer", ans="yes", note="never kept")).endswith("done=dt_yes")
    rows = {r["id"]: r for r in asks(db)}
    assert rows[no["id"]]["decided_note"] == NOTE and rows[yes["id"]]["decided_note"] is None, "a note goes with a no"
    mine = text(page(db, "elena")[0])
    assert "Amara Stone said not this one on Wed, Nov 18." in mine and "Amara’s note · private " + NOTE in mine
    assert SECRET in mine and OTHER in mine, "her own reasons"
    for handle in ("yusuf", "esther", "nathan", "owen", "tessa"):
        html = page(db, handle)[0]
        assert "Elena Ruiz Fri, Jan 1, 2027 to Sat, Jan 2, 2027 Covering: Esther Moss" in text(html), handle
        assert SECRET not in html and OTHER not in html and NOTE not in html, handle
    after = page(db, "amara")[0]
    assert "Elena Ruiz Fri, Jan 1, 2027 to Sat, Jan 2, 2027" in text(after)
    assert SECRET not in after and OTHER not in after and NOTE not in after, \
        "once answered it is only an away date: who else is away never says why, even to one who may read it"


def test_who_else_is_away_is_made_of_a_name_the_days_and_who_covers_and_nothing_else(app, db):
    got = ask(app, reason=SECRET, cover=db.who[HOPE]["esther"])
    v = mpd.view(c3.church(db, HOPE), db.who[HOPE]["amara"])
    assert v["away"] == [{"name": "Elena Ruiz", "starts_on": day(30), "ends_on": day(37), "cover": "Esther Moss",
                          "waiting": True}], "the reason she may read is not carried into this part at all"
    as_(app, "amara")
    post(app, f"/my/lead/dates/{got['id']}/answer", ans="yes")
    for handle in ("amara", "yusuf"):
        assert mpd.view(c3.church(db, HOPE), db.who[HOPE][handle])["away"] == [
            {"name": "Elena Ruiz", "starts_on": day(30), "ends_on": day(37), "cover": "Esther Moss", "waiting": False}]
    assert mpd.view(c3.church(db, HOPE), db.who[HOPE]["elena"])["away"] == [], "her own are under My dates"


def test_a_waiting_ask_is_on_nobodys_page_but_the_askers_and_the_one_it_went_to(app, db, shell):
    ask(app, reason=SECRET)
    for handle in ("yusuf", "esther", "nathan", "owen", "tessa"):
        html = page(db, handle)[0]
        assert "Elena Ruiz Fri" not in text(html) and SECRET not in html, handle
        assert "Nobody else is away in the next two months." in text(html), handle


def test_a_yes_whose_away_date_was_taken_off_since_is_never_called_on_the_calendar(app, db, shell):
    """The page reads the fact (serve_away), not the ask's state."""
    got = ask(app)
    as_(app, "amara")
    post(app, f"/my/lead/dates/{got['id']}/answer", ans="yes")
    assert "It’s on the calendar." in text(page(db, "elena")[0])
    db.t["serve_away"].clear()                                   # taken off the old way (Serving, Away)
    html = page(db, "elena")[0]
    words = text(html)
    assert "Off the calendar" in words and "these days were taken off your away dates since" in words
    assert "It’s on the calendar." not in words and f'/my/lead/dates/{got["id"]}/withdraw' not in html
    assert "Nobody else is away in the next two months." in text(page(db, "yusuf")[0])


# ─── The writes ───────────────────────────────────────────────────────

def test_asking_for_time_off_saves_it_for_this_person_and_says_who_it_waits_for(app, db, shell):
    w = db.who[HOPE]
    as_(app, "elena")
    r = post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", reason=SECRET, cover=w["esther"],
             cover_name="ignored beside a pick")
    assert went(r) == "/my/lead/dates?done=dt_asked"
    [row] = asks(db)
    assert (row["contact_id"], row["kind"], row["starts_on"], row["ends_on"]) == (
        w["elena"], "time_off", day(30), day(37))
    assert (row["reason"], row["cover_contact_id"], row["cover_name"]) == (SECRET, w["esther"], None)
    assert (row["to_contact_id"], row["state"], row["flags"], row["made_by"]) == (w["amara"], "asked", [], None)
    assert facts(db) == [], "nothing is an away date until someone says yes"
    assert "Asked. It’s waiting for Amara Stone’s yes." in text(page(db, "elena", done="dt_asked")[0])
    r = post(app, "/my/lead/dates/ask", start=day(60), kind="commitment", cover_name="  A friend from the choir ")
    assert went(r).endswith("done=dt_asked")
    row = asks(db)[-1]
    assert (row["kind"], row["ends_on"], row["cover_contact_id"], row["cover_name"]) == (
        "commitment", day(60), None, "A friend from the choir")
    assert went(post(app, "/my/lead/dates/ask", start=day(70), kind="cant")).endswith("err=dt_said"), \
        "can't make it has its own form"
    assert len(asks(db)) == 2


def test_a_short_notice_ask_is_said_gently_before_and_after_and_never_blocked(app, db, shell):
    before = text(page(db, "elena")[0])
    assert "Planned time away works best with 14 days’ notice. Sooner is fine: it just says short notice." in before
    as_(app, "elena")
    assert went(post(app, "/my/lead/dates/ask", start=day(3), kind="time_off")) == "/my/lead/dates?done=dt_asked_short"
    [row] = asks(db)
    assert (row["state"], row["flags"], row["to_contact_id"]) == ("asked", ["short_notice"], db.who[HOPE]["amara"])
    after = text(page(db, "elena", done="dt_asked_short")[0])
    assert "Asked. It’s short notice, so Amara Stone may need a little time with it." in after
    assert "Sat, Nov 21 Waiting Time off Short notice Waiting for Amara Stone’s yes." in after


def test_cant_make_it_is_on_the_calendar_at_once_and_the_page_says_it_needs_no_yes(app, db, shell):
    words = text(page(db, "elena")[0])
    assert ("For the next two weeks: sick, or something came up. It goes straight on the calendar and needs no yes. "
            "Amara Stone is let know.") in words
    as_(app, "elena")
    r = post(app, "/my/lead/dates/cant", start=day(1), end=day(2), reason=SECRET)
    assert went(r) == "/my/lead/dates?done=dt_cant"
    [row] = asks(db)
    assert (row["kind"], row["state"], row["reason"], row["decided_by_contact_id"]) == ("cant", "yes", SECRET, None)
    assert [(f["starts_on"], f["ends_on"], f["note"], f["kind"]) for f in facts(db)] == [(day(1), day(2), "", "cant")]
    words = text(page(db, "elena", done="dt_cant")[0])
    assert "Got it. It’s on the calendar." in words
    assert "Thu, Nov 19 to Fri, Nov 20 On the calendar Can’t make it On the calendar. It needed no yes." in words
    assert went(post(app, "/my/lead/dates/cant", start=day(20))).endswith("err=dt_far")
    assert "Can’t make it is for the next 14 days. For days farther out, ask for time off instead" in text(
        page(db, "elena", err="dt_far")[0])
    assert len(asks(db)) == 1
    db.t["church_schedule_settings"].append({"business_id": HOPE, "notice_days": 21})
    assert "For the next three weeks:" in text(page(db, "elena")[0])


def test_yes_writes_the_away_date_and_not_this_one_keeps_a_short_note(app, db):
    one, two = ask(app), ask(app, "yusuf", start=day(40), end=day(41))
    as_(app, "amara")
    assert went(post(app, f"/my/lead/dates/{one['id']}/answer", ans="yes")) == "/my/lead/dates?done=dt_yes"
    assert went(post(app, f"/my/lead/dates/{two['id']}/answer", ans="no", note=NOTE)) == "/my/lead/dates?done=dt_no"
    a, b = asks(db)
    assert (a["state"], a["decided_by_contact_id"], a["decided_by_user_id"]) == ("yes", db.who[HOPE]["amara"], None)
    assert (b["state"], b["decided_note"]) == ("no", NOTE)
    assert [(f["ask_id"], f["contact_id"], f["note"]) for f in facts(db)] == [(one["id"], db.who[HOPE]["elena"], "")]
    assert went(post(app, f"/my/lead/dates/{one['id']}/answer", ans="maybe")).endswith("err=dt_said")
    assert went(post(app, f"/my/lead/dates/{one['id']}/answer", ans="no")).endswith("err=dt_already")


def test_taking_one_back_takes_its_away_date_with_it(app, db, shell):
    got = ask(app)
    as_(app, "amara")
    post(app, f"/my/lead/dates/{got['id']}/answer", ans="yes")
    assert len(facts(db)) == 1 and "Take it back" in text(page(db, "elena")[0])
    as_(app, "yusuf")
    assert went(post(app, f"/my/lead/dates/{got['id']}/withdraw")).endswith("err=dt_not_asker"), "nobody else's"
    as_(app, "elena")
    assert went(post(app, f"/my/lead/dates/{got['id']}/withdraw")) == "/my/lead/dates?done=dt_back"
    assert asks(db)[0]["state"] == "withdrawn" and facts(db) == []
    words = text(page(db, "elena", done="dt_back")[0])
    assert "Taken back." in words and "Earlier · 1" in words
    assert went(post(app, f"/my/lead/dates/{got['id']}/withdraw")).endswith("err=dt_closed")


# ─── A live session only; the switch; refusals in plain words ─────────

def each_route(ask_id):
    return [(r.format(id=ask_id), f) for r, f in zip(ROUTES, (
        {"start": day(50), "kind": "time_off"}, {"start": day(1)}, {"ans": "yes"}, {}))]


def test_the_owners_preview_never_writes(app, db):
    got = ask(app)
    before = wrote(db)
    for handle in ("elena", "amara"):
        as_(app, handle)
        app.state.update(unavailable="preview")
        for path, form in each_route(got["id"]):
            assert went(post(app, path, **form)) == "/my/lead/dates?err=preview", path
    assert wrote(db) == before, "not one write"
    app.state.update(unavailable=True)
    assert went(post(app, "/my/lead/dates/cant", start=day(1))) == "/my/lead/dates?err=error"
    app.state.update(unavailable=False, me=None)
    assert went(post(app, "/my/lead/dates/cant", start=day(1))) == "/my", "no session: back to sign in"
    assert wrote(db) == before


def test_a_cross_site_post_is_refused_and_origin_null_from_this_address_is_let_through(db, monkeypatch):
    """The routes take member_portal_church._signed_in's session, whose
    _church_or_404 refuses another site's POST and reads Origin: null by the
    browser's own Sec-Fetch-Site (no-referrer-nulls-form-origin)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import member_portal
    import public_site
    a = FastAPI()
    a.include_router(mpd.router)
    c = TestClient(a, base_url="https://new-hope.example")
    monkeypatch.setattr(public_site, "public_host", lambda request: "new-hope.example")
    biz = {"business": c3.church(db, HOPE), "site": {}}
    monkeypatch.setattr(member_portal, "_church_for_request", lambda request: biz)
    monkeypatch.setattr(member_portal, "portal_active", lambda b: True)
    who = {"me": me(db, HOPE, "elena")}
    monkeypatch.setattr(member_portal, "_session_for", lambda request, ch: {"me": who["me"]})
    r = c.post("/my/lead/dates/ask", data={"start": day(30), "kind": "time_off"}, follow_redirects=False,
               headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 303 and r.headers["location"].endswith("done=dt_asked") and len(asks(db)) == 1
    got, before = asks(db)[0], wrote(db)
    for handle in ("elena", "amara"):
        who["me"] = me(db, HOPE, handle)
        for path, form in each_route(got["id"]):
            r = c.post(path, data=form, headers={"Origin": "https://evil.example"}, follow_redirects=False)
            assert r.status_code == 403, path
            r = c.post(path, data=form, headers={"Origin": "null", "Sec-Fetch-Site": "cross-site"},
                       follow_redirects=False)
            assert r.status_code == 403, path
    assert wrote(db) == before, "another site wrote nothing"
    r = c.post(f"/my/lead/dates/{got['id']}/answer", data={"ans": "yes"}, follow_redirects=False,
               headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 303 and asks(db)[0]["state"] == "yes"


@pytest.mark.parametrize("how", ["off", "another church on owner", "before its tables"])
def test_closed_or_before_its_tables_every_write_is_a_404_and_the_dates_entry_is_gone(app, db, shell, monkeypatch, how):
    got = ask(app)
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    assert ">Dates · 1</a>" in page(db, "amara", sub="/my/lead/tasks")[0]
    before = wrote(db)
    if how == "off":
        monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    elif how == "another church on owner":
        monkeypatch.setenv("CHURCH_SCHEDULE", "owner")       # the platform owner's own church only
    else:
        monkeypatch.setattr(cs, "_FORCE", False)
    for handle in ("elena", "amara"):
        as_(app, handle)
        for path, form in each_route(got["id"]):
            assert post(app, path, **form).status_code == 404, (how, path)
        assert cs.section(c3.church(db, HOPE), db.who[HOPE][handle]) is None
        html, status = page(db, handle)
        assert status == 404 and "Ask for time off" not in html and "Waiting for your yes" not in html
        tasks = page(db, handle, sub="/my/lead/tasks")[0]
        assert "Dates" not in text(tasks) and 'class="ld-seg"' in tasks, "the switcher is as it was"
    assert wrote(db) == before


def test_too_fast_is_said_and_nothing_is_written(app, db, monkeypatch):
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **kw: False)
    as_(app, "elena")
    assert went(post(app, "/my/lead/dates/ask", start=day(30), kind="time_off")) == "/my/lead/dates?err=slow"
    assert asks(db) == []


def stuck_cant(db):
    """A "can't make it" a failed settle left waiting: it needs no yes."""
    w = db.who[HOPE]
    row = {"id": "9d000000-0000-4000-8000-000000000001", "business_id": HOPE, "contact_id": w["elena"],
           "made_by": None, "grp": "leaders", "department_id": None, "kind": "cant", "starts_on": day(1),
           "ends_on": day(1), "reason": None, "cover_contact_id": None, "cover_name": None, "to_user_id": None,
           "to_contact_id": w["amara"], "state": "asked", "flags": [], "decided_by_user_id": None,
           "decided_by_contact_id": None, "decided_at": None, "decided_note": None, "withdrawn_at": None,
           "told_at": None, "answer_told_at": None, "nudged_at": None, "created_at": fake.NOW.isoformat()}
    db.t["church_away_asks"].append(row)
    return row


def test_every_refusal_comes_back_to_the_page_as_plain_words_never_a_raw_error(app, db, shell):
    w = db.who[HOPE]
    got = ask(app)
    as_(app, "elena")
    said = {}

    def refused(code, path, **form):
        before = wrote(db)
        r = post(app, path, **form)
        assert went(r) == f"/my/lead/dates?err={code}", (code, r.headers.get("location"))
        assert wrote(db)[1:] == before[1:], f"{code}: nothing saved"
        said[code] = text(page(db, "elena", err=code)[0])
        assert mpd.ERRORS[code].replace("{n}", "14") in said[code], code

    ask_ = "/my/lead/dates/ask"
    refused("dt_days", ask_, start=day(30), end=day(20), kind="time_off")                    # 400
    refused("dt_days", ask_, start=day(-9), end=day(-2), kind="time_off")
    refused("dt_days", ask_, start="soon", kind="time_off")
    refused("dt_far", "/my/lead/dates/cant", start=day(14))                                   # 400, with the days
    refused("dt_waiting", ask_, start=day(30), end=day(37), kind="commitment")                # 409
    refused("dt_cover", ask_, start=day(60), kind="time_off", cover=w["elena"])               # 400: herself
    refused("dt_cover_who", ask_, start=day(60), kind="time_off", cover=db.who[GRACE]["daniel"])
    refused("dt_cover_who", ask_, start=day(60), kind="time_off", cover=w["hugo"])            # not on the list
    refused("dt_cover_who", ask_, start=day(60), kind="time_off", cover="not-an-id")
    refused("dt_long", ask_, start=day(60), kind="time_off", reason="x" * 501)
    refused("dt_long", ask_, start=day(60), kind="time_off", cover_name="x" * 81)
    refused("dt_said", ask_, start=day(60), kind="holiday")
    refused("dt_gone", "/my/lead/dates/not-an-id/withdraw")                                   # 404
    refused("dt_gone", "/my/lead/dates/9d000000-0000-4000-8000-00000000ffff/answer", ans="yes")
    refused("dt_not_yours", f"/my/lead/dates/{got['id']}/answer", ans="yes")                  # 403: her own ask
    as_(app, "amara")
    refused("dt_long", f"/my/lead/dates/{got['id']}/answer", ans="no", note="x" * 301)
    refused("dt_not_asker", f"/my/lead/dates/{got['id']}/withdraw")                           # 403
    refused("dt_no_yes", f"/my/lead/dates/{stuck_cant(db)['id']}/answer", ans="yes")          # 409
    db.fail = {"post": "/rpc/church_away_settle"}
    refused("error", f"/my/lead/dates/{got['id']}/answer", ans="yes")                         # 503: the write
    db.fail = {"get": "/church_away_asks"}
    refused("error", f"/my/lead/dates/{got['id']}/answer", ans="yes")                         # 503: a read
    db.fail = {}
    assert went(post(app, f"/my/lead/dates/{got['id']}/answer", ans="yes")).endswith("done=dt_yes")
    refused("dt_already", f"/my/lead/dates/{got['id']}/answer", ans="no")                     # 409
    as_(app, "hugo")
    refused("dt_not_on", ask_, start=day(60), kind="time_off")                                # 403
    refused("dt_not_on", "/my/lead/dates/cant", start=day(1))
    as_(app, "yvette", GRACE)                                    # another church's person, by a real id
    assert post(app, f"/my/lead/dates/{got['id']}/withdraw").headers["location"].endswith("err=dt_gone")
    for words in said.values():
        assert "{" not in words and "HTTP" not in words and "Traceback" not in words
        assert not re.search(r"\b(4\d\d|503)\b", words) and not UUID.search(words)


def test_too_many_waiting_is_said_plainly_and_cant_make_it_is_still_never_blocked(app, db, shell):
    for n in range(cs.MAX_OPEN):
        ask(app, start=day(40 + 3 * n), end=day(41 + 3 * n))
    as_(app, "elena")
    assert went(post(app, "/my/lead/dates/ask", start=day(200), kind="time_off")).endswith("err=dt_many")
    assert "That’s a lot of asks still waiting. Take one back first." in text(page(db, "elena", err="dt_many")[0])
    assert went(post(app, "/my/lead/dates/cant", start=day(0))).endswith("done=dt_cant")


def test_every_code_a_write_can_send_back_has_plain_words_on_the_page(db, shell):
    for code, words in {**mpd.ERRORS, **mpl.ERRORS}.items():
        shown = text(page(db, "elena", err=code)[0])
        assert (mpd.ERRORS.get(code) or words).replace("{n}", "14") in shown, code
    for code in mpd.DONE:
        shown = text(page(db, "elena", done=code)[0])
        assert mpd.DONE[code].replace("{to}", "Amara Stone") in shown and "{" not in shown, code
        alone = text(page(db, "nathan", done=code)[0])           # nobody is over him: never "waiting for ’s yes"
        assert "{" not in alone and "for ’s" not in alone and " so may" not in alone, code
    for e, code in ((400, "dt_said"), (403, "dt_gone"), (404, "dt_gone"), (409, "dt_changed"), (503, "error"),
                    (500, "error"), (422, "error")):
        from fastapi import HTTPException
        assert mpd._code(HTTPException(e, "words nobody planned for")) == code


# ─── Who covers ───────────────────────────────────────────────────────

class Fields(HTMLParser):
    """Every field on the page, with whether a label wraps it, and every
    option of every list."""

    def __init__(self):
        super().__init__()
        self.depth, self.fields, self.options, self.buttons = 0, [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label":
            self.depth += 1
        elif tag in ("input", "select", "textarea") and a.get("type") != "hidden":
            self.fields.append((tag, a.get("name"), self.depth > 0))
        elif tag == "option":
            self.options.append(a.get("value") or "")
        elif tag in ("button", "summary"):
            self.buttons.append(a.get("class") or "")

    def handle_endtag(self, tag):
        if tag == "label":
            self.depth -= 1


def fields(html):
    f = Fields()
    f.feed(html)
    return f


def test_who_covers_lists_the_people_on_the_schedule_here_and_never_the_asker(app, db, shell):
    w = db.who[HOPE]
    picked = [o for o in fields(page(db, "elena")[0]).options if o]
    on_it = cs.roster(church(db)).people()
    assert set(picked) == on_it - {w["elena"]} and w["elena"] not in picked and len(picked) == len(set(picked))
    mine = {c["id"] for c in db.t["contacts"] if c["business_id"] == HOPE}
    assert set(picked) <= mine and w["hugo"] not in picked, "this church's people, and only those on the schedule"
    words = text(page(db, "elena")[0])
    assert "Who covers for you Nobody yet Abel Ford Amara Stone" in words and "Or type their name" in words


def test_the_list_of_who_covers_is_bounded_and_no_read_takes_a_thousand_people_at_once(app, db, shell):
    extra = [c["id"] for c in db.t["contacts"] if c["business_id"] == HOPE and c["name"].endswith(" Member")][:300]
    db.t["church_schedule_people"] += [{"business_id": HOPE, "contact_id": c, "listed": "add", "grp": "leaders"}
                                       for c in extra]
    cs.forget(HOPE)
    db.reads.clear()
    html, status = page(db, "elena")
    picked = [o for o in fields(html).options if o]
    assert status == 200 and len(picked) == mpd.PICK_MAX and len(cs.roster(church(db)).people()) > 300
    named = [r for r in db.reads if r.startswith("/contacts?") and "select=id,name&" in r]      # Church.names
    assert len(named) >= 4, "the names of 300 people, a hundred at a time"
    for r in named:
        ids = r.split("id=in.(")[1].split(")")[0].split(",")
        assert len(ids) <= co.IDS_PER_READ and f"business_id=eq.{HOPE}" in r and "limit=" in r, r
    for r in db.reads:
        if r.startswith("/contacts?") and "id=in.(" in r:
            assert len(r.split("id=in.(")[1].split(")")[0].split(",")) <= co.IDS_PER_READ, r
    assert not [r for r in db.reads if r.startswith("/contacts?") and "id=" not in r and "email" not in r], \
        "never the church's whole list of people"


# ─── The church's own clock, and plain days ───────────────────────────

def test_days_are_the_churchs_own_and_said_plainly(app, db, shell, monkeypatch):
    """11:30 PM on Wednesday the 18th in New York is already Thursday in
    UTC: today is the church's Wednesday."""
    got = ask(app)
    as_(app, "amara")
    post(app, f"/my/lead/dates/{got['id']}/answer", ans="yes")
    asks(db)[0]["decided_at"] = "2026-11-19T04:10:00+00:00"      # 11:10 PM on the 18th at the church
    late = datetime(2026, 11, 19, 4, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(cs, "_now", lambda: late)
    html = page(db, "elena")[0]
    assert 'name="start" value="2026-11-18" min="2026-11-18" max="2026-12-01"' in html, "today, and two weeks of days"
    assert 'name="end" min="2026-11-18"' in html
    assert "Amara Stone said yes on Wed, Nov 18." in text(html)
    as_(app, "yusuf")
    assert went(post(app, "/my/lead/dates/cant")).endswith("done=dt_cant"), "no day named is today"
    assert (asks(db)[-1]["starts_on"], asks(db)[-1]["ends_on"]) == ("2026-11-18", "2026-11-18")
    words = text(page(db, "yusuf")[0])
    assert "Wed, Nov 18 On the calendar Can’t make it" in words
    assert "Elena Ruiz Fri, Dec 18 to Fri, Dec 25" in words and not re.search(r"\b20\d\d-\d\d-\d\d\b", words)


# ─── A phone: real labels, and buttons a thumb can hit ────────────────

def test_every_field_has_a_real_label_and_every_button_is_a_full_size_one(app, db, shell):
    ask(app, reason=SECRET)
    ask(app, "amara", start=day(40), end=day(41))
    for handle in ("elena", "amara", "nathan"):
        f = fields(page(db, handle)[0])
        assert f.fields and all(labelled for _t, _n, labelled in f.fields), [x for x in f.fields if not x[2]]
        assert f.buttons and all(re.search(r"\bld-(btn|ghost)\b", c) for c in f.buttons), f.buttons
    names = {n for _t, n, _l in fields(page(db, "elena")[0]).fields}
    assert names == {"start", "end", "kind", "reason", "cover", "cover_name"}
    assert re.search(r"\.ld-btn\{[^}]*min-height:50px", mpl.LEAD_CSS) and re.search(
        r"\.ld-ghost\{[^}]*min-height:48px", mpl.LEAD_CSS), "a thumb can hit them"
    assert re.search(r"\.dt-f input,\.dt-f select\{min-height:48px[^}]*font-size:16px[^}]*width:100%;min-width:0;",
                     mpd.DATES_CSS), "fields fill the width they have and never push the page sideways"
    assert not re.search(r"(?<![-\w])(min-)?width:\s*(3[7-9]\d|[4-9]\d\d|\d{4,})px", mpd.DATES_CSS), \
        "nothing wider than a phone"


# ─── The Lead tab: the switcher, and who gets the tab ─────────────────

def test_the_switcher_offers_dates_with_how_many_wait_on_every_lead_page(app, db, shell, monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    ask(app, reason=SECRET)
    html = page(db, "amara", sub="/my/lead/tasks")[0]
    assert re.search(r'<nav class="ld-seg fit" [^>]*>.*<a href="/my/lead/dates">Dates · 1</a>', html)
    assert SECRET not in html
    html = page(db, "elena", sub="/my/lead/tasks")[0]
    assert '<a href="/my/lead/dates">Dates</a>' in html, "nothing waits on her: no number"
    assert "Dates" not in text(page(db, "hugo", sub="/my/lead/tasks")[0])
    assert re.search(r"\.ld-seg\.fit\{[^}]*overflow-x:auto", mpl.LEAD_CSS), "six entries scroll inside the row"


def test_the_entry_comes_from_what_is_kept_a_minute_never_a_fresh_read_on_every_page(app, db, monkeypatch):
    ask(app, reason=SECRET)
    biz, w = c3.church(db, HOPE), db.who[HOPE]
    assert cs.section(biz, w["amara"]) == {"waiting": 1} and cs.section(biz, w["elena"]) == {"waiting": 0}
    db.reads.clear()
    for _ in range(5):
        assert cs.section(biz, w["amara"]) == {"waiting": 1} and cs.section(biz, w["elena"]) == {"waiting": 0}
        assert cs.section(biz, w["hugo"]) is None
    assert db.reads == [], "five more pages, and not one read"
    assert SECRET not in str(cs._WAITING) and SECRET not in str(vars(cs._KEPT[HOPE][1]) if hasattr(
        cs._KEPT[HOPE][1], "__dict__") else "")
    as_(app, "amara")
    post(app, f"/my/lead/dates/{asks(db)[0]['id']}/answer", ans="yes")
    assert cs.section(biz, w["amara"]) == {"waiting": 0}, "a write here is counted at once"
    db.reads.clear()
    cs.section(biz, w["amara"])
    assert db.reads == []
    for kept in (cs._KEPT, cs._WAITING):                         # a minute goes by
        at, got = kept[HOPE]
        kept[HOPE] = (at - cs.ROSTER_SECONDS - 1, got)
    assert cs.section(biz, w["amara"]) == {"waiting": 0}
    assert [r for r in db.reads if r.startswith("/church_away_asks")] and [
        r for r in db.reads if r.startswith("/church_schedule_people")], "a minute on, both are read again"


def test_the_kept_count_never_reads_a_reason_or_a_note(app, db):
    ask(app, reason=SECRET)
    db.reads.clear()
    cs.forget_waiting(HOPE)
    assert cs.waiting_kept(c3.church(db, HOPE)) == {db.who[HOPE]["amara"]: 1}
    [read] = [r for r in db.reads if r.startswith("/church_away_asks?")]
    select = dict(part.partition("=")[::2] for part in read.partition("?")[2].split("&"))["select"].split(",")
    assert "reason" not in select and "decided_note" not in select and "state=eq.asked" in read and "limit=1000" in read


def test_the_count_is_exactly_what_waits_for_that_person_on_their_page(app, db):
    """The same rule as church_schedule.waiting: it names them, or the login
    tied to exactly them; never their own, never one that needs no yes."""
    ask(app, reason=SECRET)
    ask(app, "yusuf", start=day(40), end=day(41))
    ask(app, "sunny")                                            # goes to the login Owen is
    ask(app, "amara", start=day(50), end=day(51))                # goes to the owner's login: Nathan
    as_(app, "esther")
    post(app, "/my/lead/dates/cant", start=day(1))               # needs no yes: waits on nobody
    stuck_cant(db)                                               # nor does one a failed settle left waiting
    ch, biz = church(db), c3.church(db, HOPE)
    cs.forget_waiting(HOPE)
    kept = cs.waiting_kept(biz)
    assert kept == {db.who[HOPE]["amara"]: 2, db.who[HOPE]["owen"]: 1, db.who[HOPE]["nathan"]: 1}
    for cid in cs.roster(ch).people():
        assert kept.get(cid, 0) == len(cs.waiting(ch, co.who(co.PERSON, cid))), cid
        assert cs.section(biz, cid) == {"waiting": kept.get(cid, 0)}


def test_a_count_that_cant_be_read_still_shows_the_entry_and_a_roster_that_cant_be_read_is_never_kept(app, db):
    biz, w = c3.church(db, HOPE), db.who[HOPE]
    db.fail = {"get": "/church_away_asks"}
    assert cs.section(biz, w["elena"]) == {"waiting": 0} and HOPE not in cs._WAITING
    cs.forget(HOPE)
    db.fail = {"get": "/church_schedule_people"}
    assert cs.section(biz, w["elena"]) is None and HOPE not in cs._KEPT
    db.fail = {}
    assert cs.section(biz, w["elena"]) == {"waiting": 0}


def test_asking_for_the_entry_never_breaks_a_page(db, monkeypatch, capsys):
    """member_portal._leads asks on every page of the app: whatever goes
    wrong is no entry and one line in the log, never an error."""
    import member_portal
    biz, tessa = c3.church(db, HOPE), me(db, HOPE, "tessa")

    def boom(*a, **k):
        raise RuntimeError("something nobody planned for, about " + SECRET)
    monkeypatch.setattr(cs, "waiting_kept", boom)
    assert cs.section(biz, tessa["id"]) is None
    assert asyncio.run(member_portal._leads(HOPE, tessa["id"], biz, tessa)) is False
    out = capsys.readouterr().out
    assert "the Dates entry couldn't be worked out (RuntimeError)" in out and SECRET not in out


def test_before_its_tables_asking_for_the_entry_reads_nothing(db, monkeypatch):
    monkeypatch.setattr(cs, "_FORCE", False)
    monkeypatch.setenv("CHURCH_SCHEDULE", "owner")
    db.reads.clear()
    assert cs.section(c3.church(db, HOPE), db.who[HOPE]["elena"]) is None and db.reads == []


def test_only_dates_and_the_tab_opens_on_it(db, shell):
    """Tessa leads nothing: no people, no group, no assignments. Her Lead tab
    is her dates, and with one entry there is no switcher to draw."""
    html, status = page(db, "tessa", sub="/my/lead")
    assert status == 200 and "Ask for time off" in text(html) and "ld-seg" not in html.split("</style>")[-1]


# ─── Where a notice points ────────────────────────────────────────────

def test_a_persons_notice_points_at_this_page():
    assert tell.MEMBER_PAGE == mpd.HERE == "/my/lead/dates"
    src = open(os.path.join(ROOT, "kmj_intake_automation.py"), encoding="utf-8").read()
    assert src.index("member_portal_dates_router") < src.index("app.include_router(public_site_router)"), \
        "before the public site's catch-all"


# ─── Step 2: the limit, on the page ───────────────────────────────────
#
# These run on a database with step 2's file applied (the `db` fixture with
# limits=True); every test above runs on step 1's alone, and passes unchanged.

LIMITS = pytest.mark.parametrize("db", [True], indirect=True)
SUNDAY = day(32)                         # Sunday 20 December 2026: inside day(30)..day(37)


def away(db, handle, on=SUNDAY):
    """An away date that was agreed: a fact in serve_away."""
    db.t["serve_away"].append({"id": db.nid("serve_away"), "business_id": HOPE, "contact_id": db.who[HOPE][handle],
                               "starts_on": on, "ends_on": on, "note": "", "ask_id": None, "kind": None,
                               "created_at": fake.NOW.isoformat()})


def shown_on(db, who, ask_id):
    """What the Yes on this person's card for that ask carries: the flags
    the card showed as being in the way ('' when it carries none)."""
    html = page(db, who)[0]
    form = html.split(f'action="/my/lead/dates/{ask_id}/answer"><input type="hidden" name="ans" value="yes">')[1]
    form = form.split("</form>")[0]
    m = re.search(r'<input type="hidden" name="shown" value="([^"]*)">', form)
    return m.group(1) if m else ""


def full(db, on=SUNDAY):
    """The leaders number at two, and two leaders away that Sunday."""
    db.t["church_schedule_settings"].append({"business_id": HOPE, "notice_days": 14, "leaders_limit": 2,
                                             "office_limit": None, "service_weekdays": None})
    away(db, "wren", on)
    away(db, "kara", on)


@LIMITS
def test_before_sending_a_leader_sees_the_day_is_full_and_nothing_is_sent(app, db, shell):
    full(db)
    as_(app, "yusuf")
    before = wrote(db)
    r = post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="commitment", reason=SECRET,
             cover=db.who[HOPE]["esther"], cover_name="")
    assert r.status_code == 200, "the page itself, not a redirect: nothing was sent"
    assert wrote(db) == before and asks(db) == [] and db.later == [], "not one write, nobody told"
    assert r.headers["cache-control"].startswith("no-store"), "what they typed is never kept by a browser"
    words = text(r.text)
    assert ("Not sent yet Sun, Dec 20 is full: two of the leaders are already away, and that’s as many as can be away "
            "at once. The nearest open days are Sun, Dec 13 and Sun, Dec 27. You can still ask for these days. It "
            "goes to Owen Diaz, who can make an exception.") in words
    assert "Ask anyway" in words and "I changed the days. Ask for those" in words
    # What they typed is still in the form: the days, the kind, their own reason, who covers.
    assert f'name="start" value="{day(30)}"' in r.text and f'name="end" value="{day(37)}"' in r.text
    assert 'value="commitment" checked' in r.text and 'value="time_off" checked' not in r.text
    assert f'maxlength="500">{SECRET}</textarea>' in r.text
    assert f'<option value="{db.who[HOPE]["esther"]}" selected>' in r.text
    assert '<button class="ld-btn" type="submit" name="sure" value="yes">Ask anyway</button>' in r.text
    block = words.split("Not sent yet")[1].split("What kind")[0]
    assert "Wren" not in block and "Kara" not in block, "a count, never who"
    seen = words.replace(SECRET, "")
    assert not UUID.search(seen) and not OFFICE_WORDS.search(seen) and not KEYS.search(seen)
    assert not TITLE_WORDS.search(seen.replace(OWNER_CALLED, "")), TITLE_WORDS.search(seen.replace(OWNER_CALLED, ""))
    assert "Asked." not in words, "nothing happened"
    assert words.strip().startswith(mpd.NOT_SENT), "the top of the page says so: the form may be far down"


@LIMITS
def test_ask_anyway_sends_it_to_the_one_who_can_make_an_exception_and_the_card_says_so(app, db, shell):
    full(db)
    as_(app, "yusuf")
    r = post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", reason=SECRET, sure="yes")
    assert went(r) == "/my/lead/dates?done=dt_asked_up"
    [row] = asks(db)
    assert (row["state"], row["flags"], row["to_user_id"], row["to_contact_id"]) == (
        "asked", ["over_limit"], db.who[HOPE]["owen@"], None)
    words = text(page(db, "yusuf", done="dt_asked_up")[0])
    assert "Asked. It went to Owen Diaz, who can make an exception." in words
    assert ("Fri, Dec 18 to Fri, Dec 25 Waiting Time off Waiting for Owen Diaz’s yes. Needs an exception Sun, Dec 20 "
            "is full: two of the leaders are already away, and that’s as many as can be away at once. Owen Diaz can "
            "make an exception.") in words
    assert "Your reason · private " + SECRET in words
    seen = words.replace(SECRET, "")
    assert not UUID.search(seen) and not OFFICE_WORDS.search(seen) and not KEYS.search(seen)
    assert not TITLE_WORDS.search(seen.replace(OWNER_CALLED, ""))
    # The one over him is not asked, and reads nothing of it.
    amara = text(page(db, "amara")[0])
    assert "Waiting for your yes" not in amara and SECRET not in amara and "Yusuf Grant Time off" not in amara


@LIMITS
def test_whoever_it_went_up_to_sees_why_it_came_to_them_and_their_yes_is_an_exception(app, db, shell):
    full(db)
    as_(app, "yusuf")
    post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", reason=SECRET, sure="yes")
    [row] = asks(db)
    html, status = page(db, "owen")
    words = text(html)
    assert status == 200 and "Waiting for your yes 1 waiting" in words
    assert ("Yusuf Grant Time off Fri, Dec 18 to Fri, Dec 25 Why it came to you Sun, Dec 20 is full: two of the "
            "leaders are already away, and that’s as many as can be away at once. Your yes makes an exception. "
            "Their reason · private " + SECRET) in words
    card = words.split("Waiting for your yes")[1].split("Ask for time off")[0]
    assert "Wren" not in card and "Kara" not in card, "why it came says how many, never who"
    assert "Kara Bell Sun, Dec 20" in words.split("Who else is away")[1], "who is away is on the calendar he may see"
    seen = words.replace(SECRET, "")
    assert not UUID.search(seen) and not OFFICE_WORDS.search(seen) and not KEYS.search(seen)
    assert not TITLE_WORDS.search(seen.replace(OWNER_CALLED, ""))
    assert shown_on(db, "owen", row["id"]) == "over_limit", "his Yes carries what the box showed him"
    as_(app, "owen")
    assert went(post(app, f"/my/lead/dates/{row['id']}/answer", ans="yes", shown="over_limit")) == \
        "/my/lead/dates?done=dt_yes_x"
    assert (row["state"], row["excepted"], row["decided_by_contact_id"]) == ("yes", ["over_limit"],
                                                                             db.who[HOPE]["owen"])
    assert "You said yes, as an exception. It’s on the calendar now." in text(page(db, "owen", done="dt_yes_x")[0])
    mine = text(page(db, "yusuf")[0])
    assert "Owen Diaz said yes on Wed, Nov 18, as an exception. It’s on the calendar." in mine
    assert "Needs an exception" not in mine, "answered: the card is its answer"


@LIMITS
def test_a_protected_day_is_named_before_sending_and_a_guarded_leaders_goes_to_the_owner(app, db, shell):
    db.t["church_protected_days"].append({"id": db.nid("church_protected_days"), "business_id": HOPE, "day": day(36),
                                          "name": "Christmas Eve", "created_by": None,
                                          "created_at": fake.NOW.isoformat()})
    as_(app, "elena")
    r = post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off")
    assert r.status_code == 200 and asks(db) == []
    words = text(r.text)
    assert ("Not sent yet Thu, Dec 24 is a protected day (Christmas Eve). The nearest open days are Sun, Dec 13 and "
            "Sun, Dec 27. You can still ask for these days. It goes to Pastor Nathan, who can make an exception.") in words
    assert went(post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", sure="yes")).endswith(
        "done=dt_asked_up")
    [row] = asks(db)
    assert (row["flags"], row["to_user_id"]) == (["protected_day"], c3.NH_OWNER)
    assert "Thu, Dec 24 is a protected day (Christmas Eve). Pastor Nathan can make an exception." in text(
        page(db, "elena")[0])
    nathan = text(page(db, "nathan")[0])
    assert "Why it came to you Thu, Dec 24 is a protected day (Christmas Eve). Your yes makes an exception." in nathan
    assert "Waiting for your yes" not in text(page(db, "owen")[0]), "whoever oversees the office is not asked"


@LIMITS
def test_days_with_room_go_straight_through_and_changed_days_are_looked_at_again(app, db, shell):
    full(db)
    as_(app, "yusuf")
    assert post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off").status_code == 200
    assert asks(db) == []
    # The other button: the days changed to ones with room. Sent at once, to the one over him.
    assert went(post(app, "/my/lead/dates/ask", start=day(40), end=day(44), kind="time_off")) == \
        "/my/lead/dates?done=dt_asked"
    [row] = asks(db)
    assert (row["flags"], row["to_contact_id"]) == ([], db.who[HOPE]["amara"])
    words = text(page(db, "yusuf")[0])
    assert "Needs an exception" not in words and "Not sent yet" not in words
    # Sure of days that turn out to have room: a plain ask, no exception asked for.
    db.t["church_away_asks"].clear()
    db.t["serve_away"].clear()
    assert went(post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", sure="yes")).endswith(
        "done=dt_asked")
    assert asks(db)[0]["flags"] == []


@LIMITS
def test_the_look_before_sending_writes_nothing_in_the_preview_and_refuses_what_the_ask_refuses(app, db, shell):
    full(db)
    before = wrote(db)
    as_(app, "yusuf")
    app.state.update(unavailable="preview")
    assert went(post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off")) == \
        "/my/lead/dates?err=preview"
    app.state.update(unavailable=False)
    assert went(post(app, "/my/lead/dates/ask", start=day(37), end=day(30), kind="time_off")).endswith("err=dt_days")
    as_(app, "hugo")                                    # not on the leaders schedule
    assert went(post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off")).endswith("err=dt_not_on")
    as_(app, "nathan")                                  # the one person the church's owner is: never looked at
    assert went(post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off")).endswith("done=dt_set")
    assert len(asks(db)) == 1 and asks(db)[0]["flags"] == [] and len(wrote(db)[0]) == len(before[0]) + 2
    as_(app, "yusuf")
    db.fail = {"get": "/church_protected_days"}         # the look can't be read: nothing is sent, try again
    assert went(post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off")).endswith("err=error")
    assert len(asks(db)) == 1


@LIMITS
def test_cant_make_it_is_never_looked_at_on_a_full_day(app, db, shell):
    full(db, on=day(4))
    as_(app, "yusuf")
    assert went(post(app, "/my/lead/dates/cant", start=day(4))) == "/my/lead/dates?done=dt_cant"
    [row] = asks(db)
    assert (row["state"], row["flags"]) == ("yes", ["short_notice"])
    assert "Needs an exception" not in text(page(db, "yusuf")[0])


@LIMITS
def test_a_yes_from_the_page_that_no_longer_lands_says_so_in_plain_words(app, db, shell):
    db.t["church_schedule_settings"].append({"business_id": HOPE, "notice_days": 14, "leaders_limit": 2,
                                             "office_limit": None, "service_weekdays": None})
    got = ask(app, "yusuf", reason=SECRET)              # room when he asked: it went to Amara
    away(db, "wren")
    away(db, "kara")                                    # and then the Sunday filled
    as_(app, "amara")
    assert went(post(app, f"/my/lead/dates/{got['id']}/answer", ans="yes")) == "/my/lead/dates?err=dt_up"
    assert (got["state"], got["flags"], got["to_user_id"]) == ("asked", ["over_limit"], db.who[HOPE]["owen@"])
    words = text(page(db, "amara", err="dt_up")[0])
    assert ("Those days have changed since this was asked: one of them is full now, or is a protected day. Your yes "
            "didn’t go through, and it has gone on to the one who can make an exception.") in words
    assert "Waiting for your yes" not in words and SECRET not in words, "it has left her"
    # The owner's own person, on one that went to him and has filled since: marked, and a second yes is the exception.
    db.t["church_away_asks"].clear()
    db.t["serve_away"].clear()
    mine = ask(app, "amara", start=day(30), end=day(37))
    assert mine["flags"] == [] and mine["to_user_id"] == c3.NH_OWNER
    away(db, "wren")
    away(db, "kara")
    as_(app, "nathan")
    assert went(post(app, f"/my/lead/dates/{mine['id']}/answer", ans="yes")) == "/my/lead/dates?err=dt_yours"
    words = text(page(db, "nathan", err="dt_yours")[0])
    assert "It’s marked below. Say yes again to make an exception." in words and "Why it came to you" in words
    # The second press of the same Yes (a double tap) carried nothing, and lands nothing.
    assert went(post(app, f"/my/lead/dates/{mine['id']}/answer", ans="yes")) == "/my/lead/dates?err=dt_yours"
    assert (mine["state"], mine["excepted"]) == ("asked", []) and db.rpcs == []
    # The page he came back to shows why, and its Yes carries it.
    assert shown_on(db, "nathan", mine["id"]) == "over_limit"
    assert went(post(app, f"/my/lead/dates/{mine['id']}/answer", ans="yes", shown="over_limit")) == \
        "/my/lead/dates?done=dt_yes_x"
    assert mine["excepted"] == ["over_limit"]


@LIMITS
def test_on_the_page_nobody_gets_the_owners_or_the_office_overseers_view_of_a_flagged_ask(app, db, shell):
    """A member-app session is a person: an exception only on an ask that
    went up to that very person."""
    full(db)
    as_(app, "yusuf")
    post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", reason=SECRET, sure="yes")
    as_(app, "elena")
    post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", reason=OTHER, sure="yes")
    his, hers = asks(db)
    assert (his["to_user_id"], hers["to_user_id"]) == (db.who[HOPE]["owen@"], c3.NH_OWNER)
    nathan, owen = text(page(db, "nathan")[0]), text(page(db, "owen")[0])
    assert OTHER in nathan and SECRET not in nathan and "Yusuf Grant Time off" not in nathan
    assert SECRET in owen and OTHER not in owen and "Elena Ruiz Time off" not in owen
    for who, ask_id in (("nathan", his["id"]), ("owen", hers["id"]), ("amara", his["id"]), ("amara", hers["id"])):
        as_(app, who)
        assert went(post(app, f"/my/lead/dates/{ask_id}/answer", ans="yes")).endswith("err=dt_not_yours"), who
    assert (his["state"], hers["state"]) == ("asked", "asked") and db.rpcs == []


@LIMITS
def test_a_flagged_card_whose_days_have_cleared_says_there_is_room_now(app, db, shell):
    full(db)
    as_(app, "yusuf")
    post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", sure="yes")
    db.t["serve_away"].clear()
    assert ("Needs an exception These days were full or protected when you asked, so it went up. There’s room now. "
            "Owen Diaz can make an exception.") in text(page(db, "yusuf")[0])
    assert ("Why it came to you These days were full or protected when it was asked. There’s room now, so your yes "
            "is a plain yes.") in text(page(db, "owen")[0])
    assert shown_on(db, "owen", asks(db)[0]["id"]) == "", "shown as a plain yes: the Yes carries no flag"
    away(db, "wren")
    away(db, "kara")                                    # it fills again before he presses
    as_(app, "owen")
    assert went(post(app, f"/my/lead/dates/{asks(db)[0]['id']}/answer", ans="yes")).endswith("err=dt_yours"), \
        "he was shown room: no exception lands unseen"
    assert asks(db)[0]["state"] == "asked"
    db.t["serve_away"].clear()
    assert went(post(app, f"/my/lead/dates/{asks(db)[0]['id']}/answer", ans="yes")) == "/my/lead/dates?done=dt_yes"


# ─── Pairs (S2-4): two people who can't be away together ──────────────

def pair_up(db, a, b):
    """A pair as it sits in the table (the smaller id first)."""
    x, y = sorted((db.who[HOPE][a], db.who[HOPE][b]))
    db.t["church_away_pairs"].append({"id": db.nid("church_away_pairs"), "business_id": HOPE, "a_contact_id": x,
                                      "b_contact_id": y, "note": "Both carry the youth trip", "created_by": None,
                                      "created_at": fake.NOW.isoformat()})


def look_block(html):
    return html.split('<div class="dt-it dt-full" role="alert">')[1].split("</div>")[0]


@LIMITS
def test_before_sending_a_pair_is_said_without_a_name_or_the_others_days(app, db, shell):
    pair_up(db, "yusuf", "esther")
    away(db, "esther", day(34))                         # Tuesday, Dec 22: no service, and one of the same days
    as_(app, "yusuf")
    before = wrote(db)
    r = post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", reason=SECRET)
    assert r.status_code == 200 and wrote(db) == before and db.later == [], "nothing sent"
    words = text(r.text)
    assert words.strip().startswith(mpd.NOT_SENT_PAIR)
    assert ("Not sent yet This overlaps with someone you can’t be away with at the same time. You can still ask for "
            "these days. It goes to Owen Diaz, who can make an exception.") in words
    block = text(look_block(r.text))
    for x in ("Esther", "Moss", "Dec 22", "Tue", "nearest", "youth trip"):
        assert x not in block, x
    assert went(post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", reason=SECRET,
                     sure="yes")) == "/my/lead/dates?done=dt_asked_up"
    [row] = asks(db)
    assert (row["flags"], row["to_user_id"]) == (["pair"], db.who[HOPE]["owen@"])
    card = text(page(db, "yusuf")[0]).split("My dates")[1].split("Who else is away")[0]
    assert ("Waiting for Owen Diaz’s yes. Needs an exception This overlaps with someone you can’t be away with at the "
            "same time. Owen Diaz can make an exception.") in card
    assert "Esther" not in card and "Dec 22" not in card
    # Said from the ask's own flag: it never changes as the other's time away does.
    db.t["serve_away"] = [f for f in db.t["serve_away"] if f["contact_id"] != db.who[HOPE]["esther"]]
    assert text(page(db, "yusuf")[0]).split("My dates")[1].split("Who else is away")[0] == card


@LIMITS
def test_whoever_may_give_the_exception_reads_who_it_overlaps_with_and_their_yes_carries_it(app, db, shell):
    pair_up(db, "yusuf", "esther")
    away(db, "esther", day(34))
    as_(app, "yusuf")
    post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off", reason=SECRET, sure="yes")
    [row] = asks(db)
    words = text(page(db, "owen")[0])
    assert ("Yusuf Grant Time off Fri, Dec 18 to Fri, Dec 25 Why it came to you It overlaps with time away for "
            "Esther Moss, someone they can’t be away with at the same time. Your yes makes an exception.") in words
    assert "youth trip" not in words, "the pair's note is for the office, not a card"
    assert shown_on(db, "owen", row["id"]) == "pair"
    # The one over him: not his to answer, and nothing of it is on her page.
    amara = text(page(db, "amara")[0])
    assert "Yusuf Grant Time off" not in amara and "away with" not in amara and SECRET not in amara
    as_(app, "owen")
    assert went(post(app, f"/my/lead/dates/{row['id']}/answer", ans="yes")) == "/my/lead/dates?err=dt_yours_now", \
        "a Yes that carried nothing lands nothing"
    assert row["state"] == "asked"
    assert went(post(app, f"/my/lead/dates/{row['id']}/answer", ans="yes", shown="pair")) == \
        "/my/lead/dates?done=dt_yes_x"
    assert (row["state"], row["excepted"]) == ("yes", ["pair"])


@LIMITS
def test_anyone_else_with_a_pairs_card_reads_it_without_a_name(app, db, shell):
    """A guarded leader's ask that sits with whoever oversees the office (as
    it would until the sweep sends it on): he has the card and may not give
    the exception, so he reads that it overlaps with someone, and not who."""
    pair_up(db, "elena", "esther")
    away(db, "esther", day(34))
    db.t["church_away_asks"].append({
        "id": db.nid("church_away_asks"), "business_id": HOPE, "contact_id": db.who[HOPE]["elena"], "made_by": None,
        "grp": "leaders", "department_id": None, "kind": "time_off", "starts_on": day(30), "ends_on": day(37),
        "reason": None, "cover_contact_id": None, "cover_name": None, "to_user_id": db.who[HOPE]["owen@"],
        "to_contact_id": None, "state": "asked", "flags": ["pair"], "decided_by_user_id": None,
        "decided_by_contact_id": None, "decided_at": None, "decided_note": None, "withdrawn_at": None,
        "told_at": None, "answer_told_at": None, "nudged_at": None, "excepted": [], "team_group_id": None,
        "created_at": fake.NOW.isoformat()})
    words = text(page(db, "owen")[0])
    card = words.split("Waiting for your yes")[1].split("Ask for time off")[0]
    assert ("Why it came to you It overlaps with someone they can’t be away with at the same time. Your yes makes an "
            "exception.") in card
    assert "Esther" not in card and "Dec 22" not in card


@LIMITS
def test_a_yes_from_the_page_that_no_longer_lands_for_a_pair_alone_never_says_pair(app, db, shell):
    got = ask(app, "yusuf", reason=SECRET)              # nothing in the way when he asked: it went to Amara
    pair_up(db, "yusuf", "esther")
    away(db, "esther", day(34))
    as_(app, "amara")
    assert went(post(app, f"/my/lead/dates/{got['id']}/answer", ans="yes")) == "/my/lead/dates?err=dt_up_now"
    assert (got["state"], got["flags"], got["to_user_id"]) == ("asked", ["pair"], db.who[HOPE]["owen@"])
    words = text(page(db, "amara", err="dt_up_now")[0])
    assert mpd.ERRORS["dt_up_now"] in words
    assert "can’t be away with" not in words and "Esther" not in words.split("Ask for time off")[0], \
        "never said to her (Esther is only in who can cover, and under Who else is away)"


def test_the_words_for_a_pair_have_no_ids_office_words_or_title_words():
    today = fake.TODAY
    said = [mpd.PAIR_YOU, mpd.PAIR_THEY, mpd.NOT_SENT_PAIR, mpd.ERRORS["dt_up_now"], mpd.ERRORS["dt_yours_now"],
            mpd._why_said({"flag": "pair", "with": ["Esther Moss"]}, today),
            mpd._why_said({"flag": "pair", "with": ["Esther Moss", "Abel Ford", "Kara Bell"]}, today),
            *mpd._why_lines([{"flag": "pair"}, {"flag": "protected_day", "day": day(36), "name": ""}], today, True)]
    assert said[5] == "It overlaps with time away for Esther Moss, someone they can’t be away with at the same time."
    assert said[6] == ("It overlaps with time away for Esther Moss, Abel Ford and Kara Bell, people they can’t be away "
                       "with at the same time.")
    assert said[7:] == ["Thu, Dec 24 is a protected day.", mpd.PAIR_YOU], "the days first, then the pair, once"
    for words in said:
        for rule in (UUID, OFFICE_WORDS, TITLE_WORDS, KEYS):
            assert not rule.search(words), (words, rule.search(words))
        assert "pair" not in words.lower(), "a pair is never called one on a screen"


def test_with_step_one_alone_the_page_never_looks_and_reads_nothing_of_step_two(app, db, shell, monkeypatch):
    """The default fixture is a database with step 1's file alone."""
    import church_schedule_limits as csl

    def never(*a, **k):
        raise AssertionError("the limit was asked about on a database without it")
    monkeypatch.setattr(mpd, "_look", never)
    monkeypatch.setattr(mpd, "_limits", never)
    for name in ("picture", "look", "flags_for"):
        monkeypatch.setattr(csl, name, never)
    for h in ("wren", "kara", "celia", "esther"):
        db.t["serve_away"].append({"id": db.nid("serve_away"), "business_id": HOPE, "contact_id": db.who[HOPE][h],
                                   "starts_on": SUNDAY, "ends_on": SUNDAY, "note": "", "ask_id": None, "kind": None})
    as_(app, "yusuf")
    assert went(post(app, "/my/lead/dates/ask", start=day(30), end=day(37), kind="time_off")).endswith("done=dt_asked")
    assert asks(db)[0]["flags"] == [] and asks(db)[0]["to_contact_id"] == db.who[HOPE]["amara"]
    words = text(page(db, "yusuf", done="dt_asked")[0])
    assert "Asked. It’s waiting for Amara Stone’s yes." in words and "exception" not in words
    assert not [p for p in db.reads if fake.STEP2_NEW.search(p)] and "absent: step 2" not in db.refused


def test_the_words_for_a_full_or_protected_day_have_no_ids_office_words_or_title_words():
    today = fake.TODAY
    said = [mpd._why_said({"flag": "over_limit", "day": SUNDAY, "of": of, "name": name, "away": n, "at_most": n}, today)
            for of, name, n in (("leaders", "", 1), ("leaders", "", 3), ("office", "", 2), ("department", "Worship", 14))]
    assert said == [
        "Sun, Dec 20 is full: one of the leaders is already away, and that’s as many as can be away at once.",
        "Sun, Dec 20 is full: three of the leaders are already away, and that’s as many as can be away at once.",
        "Sun, Dec 20 is full: two from the office are already away, and that’s as many as can be away at once.",
        "Sun, Dec 20 is full: 14 from Worship are already away, and that’s as many as can be away at once."]
    said += [mpd._why_said({"flag": "protected_day", "day": day(36), "name": ""}, today),
             mpd._open_said({"before": day(25), "after": None}, today), mpd._open_said({}, today),
             *mpd._why_lines([{"flag": "protected_day", "day": day(n), "name": ""} for n in range(30, 36)], today),
             *mpd.DONE_UP.values(), *mpd.DONE_ALONE.values(), mpd.ERRORS["dt_up"], mpd.ERRORS["dt_yours"],
             mpd.NOT_SENT]
    assert "Thu, Dec 24 is a protected day." in said and "The nearest open day is Sun, Dec 13." in said and "" in said
    assert "And 3 more days like these." in said
    for words in said:
        for rule in (UUID, OFFICE_WORDS, TITLE_WORDS, KEYS):
            assert not rule.search(words.replace("{up}", "Owen Diaz")), (words, rule.search(words))
    # A volunteer's card: the day and the department, never a count, however many days.
    vol = mpd._vol_full_lines([{"flag": "over_limit", "of": "department", "name": "Kids", "away": 3, "day": day(n)}
                               for n in range(32, 39)], today, "their team")
    assert vol[0] == "Sun, Dec 20 is full for Kids." and vol[-1] == "And 4 more days like these."
    assert not any(re.search(r"\d+ (?:from|of)|already away|three", v) for v in vol), vol


# ─── A volunteer's ask (S2-5) ─────────────────────────────────────────

@pytest.mark.parametrize("db", [True], indirect=True)
def test_a_volunteers_ask_waits_for_their_teams_leader_with_why_it_came(app, db, shell):
    """A volunteer on Kids Check-in asked from My serving for a Sunday that
    is full for Kids (church_schedule_volunteers): it waits on the Dates
    page of the team's own leader, whose card says why it came to them (a
    count and the day, never who), whose Yes is a plain yes (nothing shown
    to except), and whose yes lands with no exception. The volunteer, who
    followed a link to Dates, reads their own card and that it is on My
    serving too."""
    import church_schedule_volunteers as csv
    from datetime import date
    w = db.who[HOPE]
    kids = next(d["id"] for d in db.t["church_departments"] if d["business_id"] == HOPE and d["name"] == "Kids")
    team = "5d000000-0000-4000-8000-0000000000a1"
    db.t["groups"].append({"id": team, "business_id": HOPE, "name": "Kids Check-in", "kind": "team", "active": True})
    db.t.setdefault("serve_teams", []).append({"group_id": team, "business_id": HOPE, "owner": "volunteers", "sort": 0})
    for h, role in (("n040", "leader"), ("n041", "member"), ("n042", "member")):
        db.t["group_members"].append({"group_id": team, "business_id": HOPE, "contact_id": w[h], "role": role})
    db.t["church_schedule_department_limits"].append({"department_id": kids, "business_id": HOPE, "at_most": 1,
                                                      "set_by_user_id": None, "set_by_contact_id": None,
                                                      "updated_at": fake.NOW.isoformat()})
    db.t["serve_away"].append({"id": db.nid("serve_away"), "business_id": HOPE, "contact_id": w["n042"],
                               "starts_on": SUNDAY, "ends_on": SUNDAY, "note": "", "ask_id": None, "kind": None})
    a = csv.ask(church(db), w["n041"], date(2026, 12, 20), date(2026, 12, 20),
                {"flags": ["over_limit"], "to": {"kind": co.PERSON, "id": w["n040"], "name": "N040 Member"},
                 "team_group_id": team, "department_id": kids})
    html, status = page(db, "n040")
    words = text(html)
    assert status == 200 and "Waiting for your yes" in words
    assert "Why it came to you Sun, Dec 20 is full for Kids. Your yes is all it needs." in words
    assert "N042" not in words, "never who"
    assert "already away" not in words and "one from" not in words, "never a count: a department's numbers are the office's"
    assert 'name="shown"' not in html, "a plain yes: nothing to except"
    for rule in (UUID, OFFICE_WORDS, KEYS):
        assert not rule.search(words), rule.search(words)
    mine_, _status = page(db, "n041")
    mine_words = text(mine_)
    assert "Why it went to N040 Member Sun, Dec 20 is full for Kids. With a yes" in mine_words
    assert "already away" not in mine_words, "never a count, to the volunteer either"
    assert "These are the away days you asked your team’s leader for. They’re on My serving too." in mine_words
    as_(app, "n040")
    assert went(post(app, f"/my/lead/dates/{a['id']}/answer", ans="yes")).endswith("done=dt_yes")
    row = asks(db)[-1]
    assert row["state"] == "yes" and row["excepted"] == [] and db.rpcs[-1]["p_by_contact"] == w["n040"]
    assert [p for p, _r in db.posts if p.startswith("/rpc/")] == ["/rpc/church_away_settle"], "no exception"
