"""Where the leaders schedule meets Who serves when (docs/CHURCH_SCHEDULE.md,
PR S1-6): the scheduler's hold, the Serving Away form, taking an away date
off, and a yes that opens the places they had agreed to serve.

At New Hope (church_three: a made-up church, every name in it made up), on
church_schedule_fake's tables, through the real engine (church_schedule), the
real scheduler (sunday_planning, sunday_leading) and the member app's own
routes (member_portal_serving). Pins:

  THE VOLUNTEER SCHEDULE IS NEVER BROKEN OR SLOWED BY THIS
    * off, before the migration, or closed for the church: the board makes
      exactly the reads it makes today, and answers what it answers today
    * open: one more read, a page at a time, bounded
    * a read that fails, or anything else going wrong in the hold, costs
      nobody a 503: nobody is held, and the board is what it was

  NOTHING ABOUT AN ASK REACHES WHOEVER SCHEDULES
    * a waiting ask reads as "away" for those days: in `candidates`, a 409
      from an ask, skipped by a fill; for the office, a team's own leader,
      a teammate looking for a sub, and an event date
    * the board's words are the same for a waiting ask as for an away date,
      and the reason, the kind, who it went to and the ask itself are in
      nothing the scheduler says. A waiting ask is never in the schedule's
      `away` list: that list is what was agreed

  THE SERVING AWAY FORM
    * a volunteer's Away is what it always was: the same reads, the same
      write, the same page, byte for byte (and against the commit this was
      cut from, where that commit is in the clone)
    * someone on the leaders schedule can't get an away date at once from
      that form: it is asked for through the engine, with its rules, and the
      page says so in plain words with a way to their Dates page
    * "Can't make it" on a place they agreed to works as before for everyone

  TAKING AN AWAY DATE OFF
    * one that came from an ask takes the ask back with it, in one
      transaction: no ask left a yes with nothing behind it, no date left
      without its ask being settled; whoever it went to is told as for any
      take-back. A plain away date comes off as it always did

  A YES OPENS THE PLACES THEY HAD AGREED TO SERVE
    * the way sunday_serving.cant_make_it opens one, after the write and
      never inside it; a failure there never fails the yes; the ask carries
      `serving`; the team sees the board's own words, never why
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
import os
import re
import subprocess
import sys
import types
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
import member_portal_serving as mps  # noqa: E402
import sb_clients  # noqa: E402
import serve_dates as sd  # noqa: E402
import sunday_leading as sl  # noqa: E402
import sunday_planning as sp  # noqa: E402
import sunday_serving as ss  # noqa: E402
from auth_supabase import AuthedUser, require_user  # noqa: E402
from church_schedule_fake import day  # noqa: E402
from fastapi import HTTPException  # noqa: E402

HOPE = c3.NEW_HOPE                       # a made-up church of 500: every name in it is made up
GRACE = c3.GRACE
NY = ZoneInfo("America/New_York")
# origin/main when S1-6 was cut: what "exactly as before" is measured against.
BASE = "4ee7e90a4e91630a54f725dd73689d58b63bfa5e"
TEAM = "5d000000-0000-4000-8000-000000000001"
DOOR = "5d000000-0000-4000-8000-000000000002"
LOBBY = "5d000000-0000-4000-8000-000000000003"
# The coming Sundays from Wednesday 18 November 2026: 11/22, 11/29, 12/6, 12/13, 12/20.
SUNDAYS = [date(2026, 11, 22) + timedelta(days=7 * i) for i in range(5)]
S = [f"5e000000-0000-4000-8000-{i + 1:012d}" for i in range(5)]
EVENT = "5e000000-0000-4000-8000-000000000099"     # an outreach night, Thursday 24 December
SECRET = "Surgery for my mother that week"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
OFFICE_WORDS = re.compile(r"\b(login|logins|seat|seats|manager|admin|lane|lanes|duty|duties|check_key|startup)\b", re.I)
TITLE_WORDS = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|overseers?|directors?|executive|"
                         r"treasurers?|secretary|owners?|trustees?|reverend|apostles?|prophets?)\b", re.I)
KEYS = re.compile(r"\b[a-z]+_[a-z_]+\b")                 # time_off, short_notice, a role key
# What the ask is, in every word the engine or the notices have for it.
ASK_WORDS = ("time_off", "commitment", "cant", "short_notice", "ask_id", "reason", "held", "waiting", "to_contact_id",
             "to_user_id", "decided", "Amara")
LINE = ('<p class="sv-lede" style="padding:0 0 12px">You&#x27;re on the leaders schedule, so away days you add here '
        'go through your <a href="/my/lead/dates" style="color:inherit;font-weight:600;text-decoration:underline">'
        'Dates</a> page. That&#x27;s where you see the answer, take one back, or say you can&#x27;t make it.</p>')


def _service(sid, d, hour=10, minute=30, **more):
    at = datetime(d.year, d.month, d.day, hour, minute, tzinfo=NY).astimezone(timezone.utc)
    return {"id": sid, "business_id": HOPE, "title": "Sunday service", "starts_at": at.isoformat(), "archived_at": None,
            "is_template": False, **more}


@pytest.fixture
def db(monkeypatch):
    """New Hope with one Sunday team, the Welcome Team (the volunteers'):
    two places, Door and Lobby; its own leader; Elena, who is on the leaders
    schedule (her asks go to Amara) and also serves at the Door; and two
    volunteers who are on no leaders schedule. Five Sundays ahead."""
    d = fake.build(monkeypatch)
    for t in ("worship_services", "serve_teams", "serve_positions", "serve_trained", "serve_assignments", "serve_prefs"):
        d.t[t] = []
    monkeypatch.setenv("SUNDAY_PLANNING", "on")
    monkeypatch.setattr(sp, "_now", lambda: fake.NOW)
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **kw: True)
    w = d.who[HOPE]
    d.t["groups"].append({"id": TEAM, "business_id": HOPE, "name": "Welcome Team", "kind": "team", "active": True})
    d.t["serve_teams"].append({"group_id": TEAM, "business_id": HOPE, "call_time": None, "max_month": 4,
                               "owner": "volunteers", "swap_needs_ok": False, "families": True, "sort": 0})
    for h, role in (("n026", "leader"), ("elena", "member"), ("n024", "member"), ("n025", "member")):
        d.t["group_members"].append({"group_id": TEAM, "business_id": HOPE, "contact_id": w[h], "role": role})
    for n, (pid, name) in enumerate(((DOOR, "Door"), (LOBBY, "Lobby"))):
        d.t["serve_positions"].append({"id": pid, "business_id": HOPE, "group_id": TEAM, "name": name, "needed": 1,
                                       "note": "", "sort": n, "active": True, "created_at": "2026-11-01T00:00:00+00:00"})
        for h in ("elena", "n024", "n025"):
            d.t["serve_trained"].append({"business_id": HOPE, "position_id": pid, "contact_id": w[h], "level": "trained"})
    d.t["worship_services"] += [_service(sid, on) for sid, on in zip(S, SUNDAYS)]
    d.deletes, d.patches = [], []
    real_delete, real_patch = d.delete, sb_clients.sb_patch_as_service

    def delete(path, **k):
        d.deletes.append(path)
        return real_delete(path, **k)

    def patch(path, body, **k):
        d.patches.append((path, dict(body)))
        if d.fail.get("patch") and path.startswith(d.fail["patch"]):
            return None
        return real_patch(path, body, **k)

    monkeypatch.setattr(sb_clients, "sb_delete_as_service", delete)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    return d


@pytest.fixture
def shell(monkeypatch):
    """member_portal's shell, keeping just the body, so the tests read what
    the page itself writes."""
    import member_portal
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **kw: body)


@pytest.fixture
def app(db, monkeypatch):
    """The Serve page's own routes, signed in as `app.state["me"]` at New Hope."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import member_portal_church as mpc
    a = FastAPI()
    a.include_router(mps.router)
    state = {"me": None, "unavailable": False}

    async def signed_in(request):
        biz = c3.church(db, HOPE)
        if state["unavailable"]:
            return {"business": biz, "site": {}}, None, state["unavailable"]
        return {"business": biz, "site": {}}, state["me"], False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    c = TestClient(a)
    c.state, c.db = state, db
    return c


@pytest.fixture
def office(db):
    """Who serves when, as the church's own owner signs in to it."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    a = FastAPI()
    a.include_router(sp.router)
    a.dependency_overrides[require_user] = lambda: AuthedUser(
        id=c3.NH_OWNER, email=c3.OWNER_EMAIL[c3.NH_OWNER], role="authenticated")
    return TestClient(a)


# ─── helpers ──────────────────────────────────────────────────────────

def biz(db):
    return c3.church(db, HOPE)


def church(db):
    return co.Church(biz(db))


def cid(db, handle):
    return db.who[HOPE][handle]


def person(db, handle):
    return co.who(co.PERSON, cid(db, handle))


def me(db, handle):
    c = cid(db, handle)
    return {"id": c, "name": next(x["name"] for x in db.t["contacts"] if x["id"] == c), "email": ""}


def asks(db):
    return [r for r in db.t["church_away_asks"] if r["business_id"] == HOPE]


def facts(db):
    return [s for s in db.t["serve_away"] if s["business_id"] == HOPE]


def asked(db, who="elena", start=30, end=37, **more):
    """A planned ask through the engine, as that person; answers with its row."""
    got = cs.ask(church(db), person(db, who), {"starts_on": day(start), "ends_on": day(end), "kind": "time_off", **more})
    return next(r for r in asks(db) if r["id"] == got["id"])


def said_yes(db, row, by="amara"):
    cs.answer(church(db), person(db, by), row["id"], True)


def away(db, handle, start, end):
    """A plain away date, the way it has always been made."""
    row = {"id": db.nid("serve_away"), "business_id": HOPE, "contact_id": cid(db, handle), "starts_on": start,
           "ends_on": end, "note": ""}
    db.t["serve_away"].append(row)
    return row


def on_for(db, handle, sid, pid=DOOR, status="yes"):
    """Ask them to a place through the scheduler; a yes through their own
    page's function. Answers with the assignment's id."""
    aid = sp.do_ask(HOPE, sid, pid, 1, cid(db, handle), "The office")["assignment"]["id"]
    if status == "yes":
        ss.answer(biz(db), cid(db, handle), aid, "yes")
    return aid


def place(db, aid):
    return next(r for r in db.t["serve_assignments"] if r["id"] == aid)


def cands(db, sid, pid=DOOR):
    return {c["name"]: c for c in sp._service_board(HOPE, sid).candidates(sid, pid)}


def board(db, sid=S[4]):
    """One board, and the reads it made."""
    n = len(db.reads)
    b = sp._service_board(HOPE, sid)
    return b, db.reads[n:]


def page(db, handle, query=b"", mod=mps):
    from starlette.requests import Request
    req = Request({"type": "http", "query_string": query, "headers": []})
    out = asyncio.run(mod.serve(req, {"business": biz(db), "site": {}}, me(db, handle), "/my/serving"))
    assert out.status_code == 200, out.status_code
    return out.body.decode()


def text(html):
    """What's on the screen: no tags, no styles, no form addresses."""
    out = re.sub(r"<[^>]+>", " ", re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S))
    return re.sub(r"\s+", " ", out.replace("&#x27;", "'"))


def as_(app, handle):
    app.state.update(me=me(app.db, handle), unavailable=False)


def post(app, path, **form):
    r = app.post(path, data=form, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r.headers["location"]


# ─── The volunteer schedule is never broken or slowed ─────────────────

def test_off_before_the_migration_or_closed_the_board_reads_exactly_what_it_reads_today(db, monkeypatch):
    asked(db, reason=SECRET)                     # there is something to hold, if anything looked
    monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    b0, today = board(db)
    assert not any("church_away_asks" in r for r in today) and b0.held == []
    was = b0.candidates(S[4], DOOR)
    assert [c["away"] for c in was] == [False] * 4, "with the switch off nobody is held"

    # Before the migration, whatever the switch says: the tables are asked about FIRST (kept), so not even the
    # church is looked up.
    monkeypatch.setattr(cs, "_FORCE", False)
    for mode in ("on", "owner"):
        monkeypatch.setenv("CHURCH_SCHEDULE", mode)
        b, reads = board(db)
        assert reads == today and b.held == [] and b.candidates(S[4], DOOR) == was, mode

    # Its tables there, the switch on `owner`, and this is not the platform owner's church: closed. Whose church it
    # is is looked up once and kept (member_asks.platform_church); after that, nothing.
    monkeypatch.setattr(cs, "_FORCE", True)
    monkeypatch.setenv("CHURCH_SCHEDULE", "owner")
    b, first = board(db)
    extra = [r for r in first if r not in today]
    assert len(first) == len(today) + 1 and len(extra) == 1 and extra[0].startswith("/businesses?id=eq."), extra
    assert "select=owner_id" in extra[0] and b.held == []
    b, again = board(db)
    assert again == today and b.held == [] and b.candidates(S[4], DOOR) == was

    # Off, with nothing pinned about its tables (as production runs): the switch is read first, so the tables
    # aren't even asked about.
    monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    monkeypatch.setattr(cs, "_FORCE", None)
    monkeypatch.setattr(cs, "_STATE", {"yes": None, "at": 0.0})
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    b, reads = board(db)
    assert reads == today and b.held == []
    n = len(db.reads)
    assert cs.on_schedule(biz(db), cid(db, "elena")) is False and cs.takes(biz(db), cid(db, "elena")) is False
    assert cs.withdraw_fact(biz(db), cid(db, "elena"), S[0]) is False and len(db.reads) == n


def test_on_owner_whose_church_it_is_is_asked_once_a_minute_even_when_it_cant_be_read(db, monkeypatch):
    """Under `owner`, whose church this is comes from the sign-in service,
    and a lookup that fails there is slow and is never kept by
    member_asks.platform_church. The scheduler asks once and keeps the
    answer a minute, whatever it was: three boards, one lookup."""
    import messaging_router
    monkeypatch.setenv("CHURCH_SCHEDULE", "owner")
    asked_for = []
    monkeypatch.setattr(messaging_router, "_owner_email", lambda u: asked_for.append(u) or "")     # it couldn't be read
    held = [board(db)[0].held for _ in range(3)]
    assert held == [[], [], []] and len(asked_for) == 1, "closed, as far as can be told, and not asked again"
    n = len(asked_for)
    assert cs.on_schedule(biz(db), cid(db, "elena")) is False and cs.takes(biz(db), cid(db, "n024")) is False
    assert cs.withdraw_fact(biz(db), cid(db, "elena"), S[0]) is False and len(asked_for) == n
    # The platform owner's own church is the one `owner` opens: there, the hold is read.
    monkeypatch.setattr(messaging_router, "_owner_email", lambda u: c3.OWNER_EMAIL.get(str(u), ""))
    n = len(db.reads)
    cs.holds(c3.LOVE_CITY, date(2026, 12, 20), date(2026, 12, 26))
    assert [r for r in db.reads[n:] if r.startswith("/church_away_asks")], "open there"
    n = len(db.reads)
    cs.holds(HOPE, date(2026, 12, 20), date(2026, 12, 26))
    assert db.reads[n:] == [], "and still closed here, with nothing read"


def test_open_the_board_makes_one_more_read_and_never_selects_what_is_private(db):
    asked(db, reason=SECRET)
    db.fail = {"get": "/church_away_asks"}       # (a failed read: the same reads, nobody held)
    _b, failed = board(db)
    db.fail = {}
    b, reads = board(db)
    hold = [r for r in reads if r.startswith("/church_away_asks")]
    assert len(hold) == 1 and len(reads) == len(failed), "one read, and a failed one is not tried again"
    assert [r for r in reads if not r.startswith("/church_away_asks")] == \
        [r for r in failed if not r.startswith("/church_away_asks")]
    select = hold[0].split("select=")[1].split("&")[0]
    assert select == "id,business_id,contact_id,starts_on,ends_on,state", "who and which days, and nothing of the ask"
    assert "state=eq.asked" in hold[0] and f"business_id=eq.{HOPE}" in hold[0]
    assert "starts_on=lte.2026-12-26" in hold[0] and "ends_on=gte.2026-12-20" in hold[0], "only the board's own days"
    assert b.held == [{"contact_id": cid(db, "elena"), "starts_on": day(30), "ends_on": day(37)}]


def test_a_read_that_fails_holds_nobody_and_costs_nobody_a_503(db, office, monkeypatch):
    asked(db)
    assert cands(db, S[4])["Elena Ruiz"]["away"] is True
    db.fail = {"get": "/church_away_asks"}
    assert cs.holds(HOPE, date(2026, 12, 20), date(2026, 12, 26)) == []
    r = office.get(f"/planning/candidates?business_id={HOPE}&service_id={S[4]}&position_id={DOOR}")
    assert r.status_code == 200 and {c["name"]: c["away"] for c in r.json()["candidates"]}["Elena Ruiz"] is False
    assert office.get(f"/planning/schedule?business_id={HOPE}&weeks=5").status_code == 200
    assert sp.do_fill(HOPE, 1, "2026-12-20", None)["asked"] == 2, "the fill goes ahead as it does today"
    db.fail = {}

    # Anything else going wrong in there is the same: never an error for whoever schedules.
    real = sb_clients.sb_get_as_service

    def broken(path, **k):
        if path.startswith("/church_away_asks"):
            raise RuntimeError("the connection dropped")
        return real(path, **k)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", broken)
    assert cs.holds(HOPE, date(2026, 12, 20), date(2026, 12, 26)) == []
    assert sp._service_board(HOPE, S[4]).held == []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", real)
    for lo, hi in (("someday", "2026-12-26"), (None, None), ("2026-12-26", "2026-12-20")):
        assert cs.holds(HOPE, lo, hi) == [], "days that aren't days hold nobody"
    assert cs.holds("not-a-church", date(2026, 12, 20), date(2026, 12, 26)) == []
    assert cs.holds(GRACE, date(2026, 12, 20), date(2026, 12, 26)) == [], "another church's asks are never held here"


def test_the_hold_is_read_a_page_at_a_time_and_is_bounded(db, monkeypatch):
    """1,003 asks waiting in the window (PostgREST gives 1,000 rows a read
    here): every one is held, and it took two reads. Past HOLD_PAGES pages
    the scheduler stops reading and holds the ones it has."""
    people = [c["id"] for c in db.t["contacts"] if c["business_id"] == HOPE][:300]
    for n in range(1003):
        db.t["church_away_asks"].append({
            "id": f"9a000000-0000-4000-8000-{n:012d}", "business_id": HOPE, "contact_id": people[n % 300],
            "grp": "leaders", "kind": "time_off", "starts_on": "2026-12-19", "ends_on": "2026-12-21", "state": "asked",
            "reason": SECRET, "flags": [], "to_user_id": None, "to_contact_id": None})
    n0 = len(db.reads)
    got = cs.holds(HOPE, date(2026, 12, 20), date(2026, 12, 26))
    reads = db.reads[n0:]
    assert len(got) == 1003 and len(reads) == 2, "no first 1,000 taken for all of them"
    assert all("order=id.asc" in r and "limit=1000" in r for r in reads) and "id=gt." in reads[1]
    assert all(set(h) == {"contact_id", "starts_on", "ends_on"} for h in got)
    monkeypatch.setattr(cs, "HOLD_PAGE", 100)
    monkeypatch.setattr(cs, "HOLD_PAGES", 3)
    n0 = len(db.reads)
    assert len(cs.holds(HOPE, date(2026, 12, 20), date(2026, 12, 26))) == 300 and len(db.reads) - n0 == 3


# ─── Nothing about an ask reaches whoever schedules ───────────────────

def test_a_waiting_ask_reads_as_away_and_they_are_not_asked_to_serve(db, office):
    assert cands(db, S[4])["Elena Ruiz"]["ok"] is True
    row = asked(db, reason=SECRET)                                    # Dec 18 to 25: the Sunday of Dec 20
    held = cands(db, S[4])["Elena Ruiz"]
    assert (held["away"], held["ok"]) == (True, False)
    assert cands(db, S[3])["Elena Ruiz"]["ok"] is True, "only the days she asked for"
    assert cands(db, S[4])["N024 Member"]["ok"] is True, "and only her"
    # The office asking her by name: the board's own refusal, in its own words.
    r = office.post("/planning/ask", json={"business_id": HOPE, "service_id": S[4], "position_id": DOOR,
                                           "contact_id": cid(db, "elena")})
    assert (r.status_code, r.json()["detail"]) == (409, "Elena Ruiz is away that Sunday")
    assert office.post("/planning/ask", json={"business_id": HOPE, "service_id": S[3], "position_id": DOOR,
                                              "contact_id": cid(db, "elena")}).status_code == 200
    # Filling that Sunday: she would be first (the most rested, by name), and is skipped.
    got = sp.do_fill(HOPE, 1, "2026-12-20", None)
    on = {r["position_id"]: r["contact_id"] for r in db.t["serve_assignments"] if r["service_id"] == S[4]}
    assert got["asked"] == 2 and cid(db, "elena") not in on.values() and on[DOOR] == cid(db, "n024")
    # Once it is answered "not this one", or taken back, the hold ends.
    cs.answer(church(db), person(db, "amara"), row["id"], False)
    assert cands(db, S[4])["Elena Ruiz"]["away"] is False


def test_without_a_waiting_ask_the_fill_picks_her_as_it_always_did(db):
    """The control for the test above: nothing else keeps her off that Sunday."""
    sp.do_fill(HOPE, 1, "2026-12-20", None)
    on = {r["position_id"]: r["contact_id"] for r in db.t["serve_assignments"] if r["service_id"] == S[4]}
    assert on[DOOR] == cid(db, "elena")


def test_a_teams_own_leader_a_teammate_and_an_event_date_all_get_the_same_hold(db, monkeypatch):
    asked(db, reason=SECRET)
    lead = me(db, "n026")
    # A team's own leader (sunday_leading): who could take the Door, an ask, a fill.
    got = {c["name"]: c for c in sl.candidates(biz(db), lead["id"], S[4], DOOR)}
    assert (got["Elena Ruiz"]["away"], got["Elena Ruiz"]["ok"]) == (True, False)
    with pytest.raises(HTTPException) as e:
        sl.ask(biz(db), lead, S[4], DOOR, 1, cid(db, "elena"))
    assert (e.value.status_code, e.value.detail) == (409, "Elena Ruiz is away that Sunday")
    sl.fill(biz(db), lead, TEAM)
    assert not [r for r in db.t["serve_assignments"] if r["service_id"] == S[4] and r["contact_id"] == cid(db, "elena")]
    assert [r for r in db.t["serve_assignments"] if r["service_id"] == S[3] and r["contact_id"] == cid(db, "elena")], \
        "she is still asked for a Sunday she didn't ask off"
    v = sl.team_view(biz(db), lead["id"], TEAM)
    assert v["board"].is_away(cid(db, "elena"), S[4]) and not v["board"].is_away(cid(db, "elena"), S[2])
    # A teammate looking for someone to cover (My serving): she isn't free that day.
    db.t["serve_assignments"] = [r for r in db.t["serve_assignments"] if r["service_id"] != S[4]]
    aid = on_for(db, "n024", S[4])
    subs = {c["name"]: c for c in ss.subs(biz(db), cid(db, "n024"), aid)}
    assert subs["Elena Ruiz"]["ok"] is False and subs["N025 Member"]["ok"] is True
    with pytest.raises(HTTPException) as e:
        ss.ask_sub(biz(db), cid(db, "n024"), aid, cid(db, "elena"))
    assert e.value.status_code == 409
    # An event date (serve_dates): an outreach night inside the days she asked for.
    monkeypatch.setattr(sd, "_FORCE", True)
    for s in db.t["worship_services"]:
        s.update(kind="service", place=None, event_entry_id=None)
    db.t["worship_services"].append(_service(EVENT, date(2026, 12, 24), 19, 0, title="Outreach night", kind="event",
                                             place="Fellowship hall", event_entry_id=None))
    night = cands(db, EVENT)
    assert night["Elena Ruiz"]["away"] is True and night["N025 Member"]["ok"] is True


def test_the_board_says_away_in_its_own_words_and_nothing_of_the_ask(db, office, shell):
    """A waiting ask and a plain away date read the same to whoever
    schedules, word for word; and the reason, the kind, who it went to and
    the ask itself are in nothing the scheduler answers."""
    lead = me(db, "n026")

    def said():
        out = {"candidates": office.get(f"/planning/candidates?business_id={HOPE}&service_id={S[4]}&position_id={DOOR}").json(),
               "leader": sl.candidates(biz(db), lead["id"], S[4], DOOR),
               "ask": office.post("/planning/ask", json={"business_id": HOPE, "service_id": S[4], "position_id": DOOR,
                                                         "contact_id": cid(db, "elena")}).json()}
        import member_portal_leading as lead_page
        out["page"] = lead_page._candidates(TEAM, "2026-12-20", {"id": DOOR, "name": "Door"}, 1, out["leader"])
        return out

    plain = away(db, "elena", day(30), day(37))
    as_a_date = said()
    listed = office.get(f"/planning/schedule?business_id={HOPE}&weeks=5").json()
    assert [a["name"] for a in listed["away"]] == ["Elena Ruiz"], "an away date is listed, as it always was"
    db.t["serve_away"].remove(plain)
    asked(db, reason=SECRET, cover_name="Esther Moss")
    as_an_ask = said()
    assert as_an_ask == as_a_date, "the same words for both: nobody can tell which it is"
    assert "away that day" in as_an_ask["page"] and as_an_ask["ask"] == {"detail": "Elena Ruiz is away that Sunday"}
    sched = office.get(f"/planning/schedule?business_id={HOPE}&weeks=5").json()
    assert sched["away"] == [], "a waiting ask is never in the list of who is away: that list is what was agreed"
    everything = json.dumps([as_an_ask, sched, sl.team_view(biz(db), lead["id"], TEAM)["assignments"]])
    for word in (SECRET, "Esther", *ASK_WORDS):
        assert word not in everything, word
    b = sp._service_board(HOPE, S[4])
    assert b.away == [] and [set(h) for h in b.held] == [{"contact_id", "starts_on", "ends_on"}]
    # A yes makes it an away date, and then it is listed like any other.
    said_yes(db, asks(db)[0])
    sched = office.get(f"/planning/schedule?business_id={HOPE}&weeks=5").json()
    assert [(a["name"], a["starts_on"], a["ends_on"]) for a in sched["away"]] == [("Elena Ruiz", day(30), day(37))]
    assert set(sched["away"][0]) == {"contact_id", "name", "starts_on", "ends_on"} and SECRET not in json.dumps(sched)
    assert sp._service_board(HOPE, S[4]).held == [], "the hold became the fact"


# ─── The Serving Away form: a volunteer ───────────────────────────────

def _calls(monkeypatch):
    """Every call to the database from here on: (verb, path, body)."""
    seen = []
    for verb in ("get", "post", "patch", "delete"):
        real = getattr(sb_clients, f"sb_{verb}_as_service")

        def spy(path, *a, _verb=verb, _real=real, **k):
            seen.append((_verb, re.sub(UUID, "<id>", path) if _verb == "delete" else path,
                         copy.deepcopy(a[0]) if a else None))
            return _real(path, *a, **k)
        monkeypatch.setattr(sb_clients, f"sb_{verb}_as_service", spy)
    return seen


def test_a_volunteers_away_is_saved_at_once_with_the_reads_and_the_write_it_always_made(db, app, monkeypatch):
    """Switch open, a volunteer who is on no leaders schedule: once the
    roster is kept, adding and taking off an away date makes exactly the
    calls it makes with the leaders schedule off (taking one off reads the
    row first: the one read this adds for them)."""
    v, b = cid(db, "n024"), biz(db)
    assert cs.takes(b, v) is False and cs.takes(b, cid(db, "elena")) is True     # (the roster is kept from here)
    seen = _calls(monkeypatch)
    got = ss.add_away(b, v, "2026-12-01", "2026-12-03")
    open_add = list(seen)
    assert got.get("id") and "asked" not in got, "the saved row, as it always answered"
    seen.clear()
    ss.drop_away(b, v, got["id"])
    open_drop = list(seen)
    assert facts(db) == [] and asks(db) == [] and db.rpcs == [] and db.later == []

    monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    seen.clear()
    got = ss.add_away(b, v, "2026-12-01", "2026-12-03")
    off_add = list(seen)
    seen.clear()
    ss.drop_away(b, v, got["id"])
    off_drop = list(seen)
    assert open_add == off_add, "the same reads and the same write"
    assert [c[0] for c in off_add] == ["get", "get", "post"]
    assert off_add[-1][2] == {"business_id": HOPE, "contact_id": v, "starts_on": "2026-12-01", "ends_on": "2026-12-03",
                              "note": ""}, "no ask, no kind: a plain away date"
    assert [c[0] for c in off_drop] == ["delete"] and open_drop[1:] == off_drop
    assert open_drop[0][0] == "get" and open_drop[0][1].startswith("/serve_away?id=eq.") and len(open_drop) == 2

    # Through the page's own route, switch open: saved at once, and told so in the words it always used.
    monkeypatch.setenv("CHURCH_SCHEDULE", "on")
    as_(app, "n024")
    assert post(app, "/my/serving/away", start="2026-12-01", end="2026-12-03") == "/my/serving?done=away"
    assert [(f["contact_id"], f["starts_on"], f["ends_on"], f.get("ask_id")) for f in facts(db)] == \
        [(v, "2026-12-01", "2026-12-03", None)]
    assert post(app, "/my/serving/away/remove", id=facts(db)[0]["id"]) == "/my/serving?done=unaway"
    assert facts(db) == [] and asks(db) == [] and db.rpcs == []


def _rich(db):
    """Something in every part of a volunteer's My serving: an ask to
    answer, a Sunday coming up, an open spot, an away date."""
    on_for(db, "n024", S[0], status="asked")
    on_for(db, "n024", S[1])
    sp.do_offer(HOPE, S[2], DOOR, 1, "The office")
    away(db, "n024", "2026-12-12", "2026-12-14")
    asked(db, reason=SECRET)                     # and, beside them, a leader's ask waiting


def test_a_volunteers_my_serving_is_the_same_page_open_or_closed_byte_for_byte(db, shell, monkeypatch):
    _rich(db)
    open_ = page(db, "n024")
    assert "Add away dates" in open_ and "Nobody asks you on these days." in open_ and "Dec 12" in open_
    assert "/my/lead/dates" not in open_ and "leaders schedule" not in open_
    typed = page(db, "n024", b"done=asked")      # the address typed by hand says nothing to them
    assert typed == open_, "a flash that isn't theirs is no flash"
    leader_open = page(db, "elena")
    monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    assert page(db, "n024") == open_, "off: the same bytes"
    leader_off = page(db, "elena")
    monkeypatch.setenv("CHURCH_SCHEDULE", "on")
    monkeypatch.setattr(cs, "_FORCE", False)
    assert page(db, "n024") == open_, "before the migration: the same bytes"
    # Someone on the leaders schedule: the same page with one line put in under Away, and nothing else moved.
    assert LINE in leader_open and leader_open.replace(LINE, "") == leader_off


def _at_base(name):
    """One module as it was on origin/main when this was cut, or None where
    that commit isn't in the clone (CI checks out a single commit)."""
    try:
        got = subprocess.run(["git", "-C", ROOT, "show", f"{BASE}:{name}.py"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if got.returncode != 0:
        return None
    mod = types.ModuleType(f"{name}_at_base")
    mod.__file__ = os.path.join(ROOT, f"{name}.py")
    exec(compile(got.stdout.decode("utf-8"), f"{name}@{BASE[:8]}", "exec"), mod.__dict__)
    return mod


def test_a_volunteers_my_serving_and_away_are_what_they_were_on_main_byte_for_byte(db, shell, monkeypatch):
    """Renders both: My serving as origin/main built it when S1-6 was cut
    (its own member_portal_serving and sunday_serving, read out of git), and
    as it is built now with the leaders schedule open, for a volunteer. The
    same bytes; and adding an away date makes the same calls.

    This measures S1-6 against the commit it was cut from. When My serving
    is changed on purpose for everyone, this test has done its work: delete
    it. The lasting rule is the test above (open or closed, the same page).
    Skipped where that commit isn't in the clone."""
    was_ss, was_mps = _at_base("sunday_serving"), _at_base("member_portal_serving")
    if not was_ss or not was_mps:
        pytest.skip(f"{BASE[:8]} isn't in this clone, so main's own page can't be rendered here")
    was_mps.ss = was_ss
    _rich(db)
    assert cs.takes(biz(db), cid(db, "n024")) is False
    for query in (b"", b"done=away", b"done=unaway", b"err=said&msg=Pick+the+days", b"done=asked"):
        now_, then = page(db, "n024", query), page(db, "n024", query, mod=was_mps)
        assert now_ == then, f"a volunteer's My serving changed ({query.decode() or 'plain'})"
    assert len(page(db, "n024")) > 5000 and "Add away dates" in page(db, "n024")
    seen = _calls(monkeypatch)
    then = was_ss.add_away(biz(db), cid(db, "n024"), "2026-12-01", "2026-12-03")
    then_calls = list(seen)
    db.t["serve_away"] = [f for f in db.t["serve_away"] if f["id"] != then["id"]]
    seen.clear()
    ss.add_away(biz(db), cid(db, "n024"), "2026-12-01", "2026-12-03")
    assert list(seen) == then_calls and len(then_calls) == 3


# ─── The Serving Away form: someone on the leaders schedule ───────────

def test_a_leaders_away_is_asked_for_through_the_engine_never_saved_at_once(db, app, shell):
    as_(app, "elena")
    went = post(app, "/my/serving/away", start=day(30), end=day(37))
    assert went == "/my/serving?done=asked", "only a short code rides in the address"
    assert facts(db) == [], "nothing is on her away days: nobody has said yes"
    [a] = asks(db)
    assert (a["kind"], a["state"], a["reason"], a["flags"]) == ("time_off", "asked", None, [])
    assert (a["contact_id"], a["to_contact_id"], a["made_by"]) == (cid(db, "elena"), cid(db, "amara"), None), \
        "it went to whoever is over her, asked as herself"
    assert len(db.later) == 1, "and whoever it went to is told, by the engine's own notice"
    assert ("/church_away_asks", True) in db.posts and db.rpcs == []
    # The page says so, by name, with a way to her Dates page; and one line under Away says why.
    html = page(db, "elena", b"done=asked")
    words = text(html)
    assert ("Asked. Amara Stone will say yes or not this one, and with a yes these days go on your away days. "
            "See it under Dates") in words
    assert 'href="/my/lead/dates"' in html and LINE in html
    assert "You're on the leaders schedule, so away days you add here go through your Dates page." in words
    assert "Nobody asks you on these days." in words and "Dec 18" not in words, "not an away day yet"
    new = text(mps._asked_flash(_req(b"done=asked"), {"dates": {"to": "Amara Stone"}}) + mps._dates_line({"dates": {}}))
    for rule in (UUID, OFFICE_WORDS, TITLE_WORDS, KEYS):
        assert not rule.search(new), rule.search(new)
    # The engine's rules, each one: the same days again, short notice, a day that has passed.
    again = post(app, "/my/serving/away", start=day(30), end=day(37))
    assert again.startswith("/my/serving?err=said&msg=Those+days+are+already+waiting") and len(asks(db)) == 1
    assert post(app, "/my/serving/away", start=day(3), end=day(3)) == "/my/serving?done=asked_short"
    short = asks(db)[-1]
    assert (short["kind"], short["state"], short["flags"]) == ("time_off", "asked", ["short_notice"]), \
        "tomorrow or this week is still asked for here: can't make it is its own button, under Dates"
    assert "It's short notice, so Amara Stone may need a little time with it." in text(page(db, "elena", b"done=asked_short"))
    assert post(app, "/my/serving/away", start="2026-10-01", end="2026-10-02").startswith("/my/serving?err=said&msg=Pick+the+days")
    assert facts(db) == [] and len(asks(db)) == 2
    # A yes puts it on her away days, where it has always shown.
    said_yes(db, a)
    assert "Dec 18 – 25" in text(page(db, "elena"))


def _req(query=b""):
    from starlette.requests import Request
    return Request({"type": "http", "query_string": query, "headers": []})


def test_the_function_itself_asks_so_no_caller_of_it_saves_a_leaders_date_at_once(db):
    got = ss.add_away(biz(db), cid(db, "elena"), day(30), day(37))
    assert got == {"asked": True, "state": "asked", "to": "Amara Stone", "short": False}
    assert facts(db) == [] and len(asks(db)) == 1
    # Twenty already waiting: the engine's own limit, not the away list's.
    for n in range(19):
        ss.add_away(biz(db), cid(db, "elena"), day(60 + 3 * n), day(61 + 3 * n))
    with pytest.raises(HTTPException) as e:
        ss.add_away(biz(db), cid(db, "elena"), day(200), day(201))
    assert (e.value.status_code, e.value.detail) == (400, cs.TOO_MANY) and facts(db) == []


def test_the_one_person_nobody_is_over_is_set_at_once_by_the_engines_own_rule(db, app, shell):
    """The one person the church's owner is needs nobody's yes: the engine
    says so, not the form. It still goes through the engine (the date names
    its ask), and the page says "Saved" as it does for anyone's."""
    db.t["group_members"].append({"group_id": TEAM, "business_id": HOPE, "contact_id": cid(db, "nathan"), "role": "member"})
    as_(app, "nathan")
    assert post(app, "/my/serving/away", start=day(30), end=day(31)) == "/my/serving?done=away"
    [a], [f] = asks(db), facts(db)
    assert (a["state"], a["decided_by_user_id"], a["decided_by_contact_id"]) == ("yes", None, None)
    assert f["ask_id"] == a["id"] and db.rpcs[-1]["p_state"] == "yes"
    assert "Saved. Nobody asks you on those days." in text(page(db, "nathan", b"done=away"))


def test_a_roster_that_cant_be_read_saves_nothing_and_someone_just_taken_off_is_a_volunteer(db, app):
    """Open, and who is on the schedule couldn't be read: it can't be told
    whether this is a leader, so nothing is saved and they are asked to try
    again (never a guess that hands a leader a date nobody said yes to)."""
    db.fail = {"get": "/church_schedule_people"}
    assert cs.on_schedule(biz(db), cid(db, "elena")) is None
    for who in ("elena", "n024"):
        as_(app, who)
        assert post(app, "/my/serving/away", start=day(30), end=day(31)) == "/my/serving?err=error"
    assert facts(db) == [] and asks(db) == []
    db.fail = {}
    # That is only a replica that has never read this church's roster. One that has read it once answers from
    # the last one it read when the minute is up and it can't be read again: a blip never stands between a
    # volunteer and their Away, and a leader's still isn't saved at once (the engine reads fresh, and can't).
    assert cs.takes(biz(db), cid(db, "elena")) is True and cs.takes(biz(db), cid(db, "n024")) is False
    cs._KEPT.clear()                             # (the minute is up)
    db.fail = {"get": "/church_schedule_people"}
    as_(app, "n024")
    assert post(app, "/my/serving/away", start=day(40), end=day(41)) == "/my/serving?done=away"
    [f] = facts(db)
    assert (f["contact_id"], f.get("ask_id")) == (cid(db, "n024"), None) and asks(db) == []
    as_(app, "elena")
    assert post(app, "/my/serving/away", start=day(30), end=day(31)) == "/my/serving?err=error"
    assert facts(db) == [f] and asks(db) == []
    db.fail = {}
    db.t["serve_away"].clear()
    # Kept as on the schedule, but taken off it within the minute: the engine says she isn't on it, and her
    # Away is saved as anyone's is.
    assert cs.takes(biz(db), cid(db, "elena")) is True
    db.t["church_schedule_people"].append({"business_id": HOPE, "contact_id": cid(db, "elena"), "listed": "remove",
                                           "grp": None})
    as_(app, "elena")
    assert post(app, "/my/serving/away", start=day(30), end=day(31)) == "/my/serving?done=away"
    assert asks(db) == [] and [(f["contact_id"], f.get("ask_id")) for f in facts(db)] == [(cid(db, "elena"), None)]


def test_cant_make_it_on_a_place_they_agreed_to_works_as_before_for_everyone(db, app):
    for who, sid in (("elena", S[0]), ("n024", S[1])):
        aid = on_for(db, who, sid)
        as_(app, who)
        assert post(app, "/my/serving/cant", id=aid) == "/my/serving?done=told"
        assert (place(db, aid)["status"], place(db, aid)["note"]) == ("no", "Can't make it")
    assert asks(db) == [] and facts(db) == [] and db.rpcs == [], "that button was never an ask, for anyone"


def test_the_leaders_part_of_the_page_never_breaks_it(db, shell, monkeypatch):
    on_for(db, "elena", S[0])

    def down(*a, **k):
        raise RuntimeError("down")
    with monkeypatch.context() as m:
        m.setattr(cs, "roster_kept", down)
        assert cs.on_schedule(biz(db), cid(db, "elena")) is None, "it couldn't tell, and says so without raising"
        html = page(db, "elena", b"done=asked")
        assert "Add away dates" in html and LINE not in html and "Asked." not in html
    with monkeypatch.context() as m:
        m.setattr(cs, "on_schedule", down)
        html = page(db, "elena", b"done=asked")
        assert "Add away dates" in html and LINE not in html and "Asked." not in html
    with monkeypatch.context() as m:
        m.setattr(cs, "mine", down)              # the name for the flash can't be read: the words stand without it
        words = text(page(db, "elena", b"done=asked"))
        assert "Asked. It's waiting for a yes, and with a yes these days go on your away days. See it under Dates" in words


# ─── Taking an away date off ──────────────────────────────────────────

def test_taking_off_a_date_that_came_from_an_ask_takes_the_ask_back(db, app, monkeypatch):
    row = asked(db, reason=SECRET)
    fake.later(db)                               # Amara is told of the ask
    said_yes(db, row)
    [f] = facts(db)
    assert f["ask_id"] == row["id"] and row["state"] == "yes"
    told = []
    monkeypatch.setattr(tell, "tell_withdrawn", lambda ch, ask, *, by: told.append((ask["id"], by)) or "told")
    db.later.clear()
    db.deletes.clear()
    as_(app, "elena")
    assert post(app, "/my/serving/away/remove", id=f["id"]) == "/my/serving?done=unaway"
    assert facts(db) == [] and row["state"] == "withdrawn" and row["withdrawn_at"], \
        "no ask left a yes with nothing behind it"
    assert db.rpcs[-1] == {"p_business_id": HOPE, "p_ask_id": row["id"], "p_state": "withdrawn", "p_by_user": None,
                           "p_by_contact": None, "p_note": None}
    assert db.deletes == [], "the date went with its ask, in the one transaction: never deleted by itself"
    assert fake.later(db) == 1 and told == [(row["id"], person(db, "elena"))], \
        "and whoever it went to hears, by the rule for any take-back"


def test_a_take_back_that_fails_leaves_the_date_and_its_ask_as_they_were(db, app):
    row = asked(db)
    said_yes(db, row)
    [f] = facts(db)
    as_(app, "elena")
    for broken in ({"post": "/rpc/church_away_settle"}, {"get": "/serve_away?id="}, {"get": "/church_away_asks?id="}):
        db.fail = broken
        assert post(app, "/my/serving/away/remove", id=f["id"]) == "/my/serving?err=error", broken
        assert facts(db) == [f] and row["state"] == "yes", "never the date without its ask, nor the ask without it"
    db.fail = {}
    # Somebody else's date is never theirs to take off, ask or no ask.
    as_(app, "n024")
    post(app, "/my/serving/away/remove", id=f["id"])
    assert facts(db) == [f] and row["state"] == "yes"


def test_a_plain_away_date_comes_off_exactly_as_it_always_did(db, app):
    old = away(db, "elena", "2026-12-01", "2026-12-02")     # hers from before the leaders schedule: no ask behind it
    mine_ = away(db, "n024", "2026-12-05", "2026-12-06")
    for who, f in (("elena", old), ("n024", mine_)):
        db.deletes.clear()
        as_(app, who)
        assert post(app, "/my/serving/away/remove", id=f["id"]) == "/my/serving?done=unaway"
        assert db.deletes == [f"/serve_away?id=eq.{f['id']}&business_id=eq.{HOPE}&contact_id=eq.{f['contact_id']}"]
    assert facts(db) == [] and db.rpcs == [] and db.later == []
    # A date whose ask was already settled some other way is a plain date now: it comes off, and nothing is
    # settled twice.
    row = asked(db)
    said_yes(db, row)
    row.update(state="withdrawn", withdrawn_at=fake.NOW.isoformat())     # (as a row left behind by hand would be)
    [f] = facts(db)
    n = len(db.rpcs)
    as_(app, "elena")
    assert post(app, "/my/serving/away/remove", id=f["id"]) == "/my/serving?done=unaway"
    assert facts(db) == [] and len(db.rpcs) == n


def test_closed_or_before_its_tables_taking_a_date_off_reads_nothing_new(db, monkeypatch):
    f = away(db, "n024", "2026-12-05", "2026-12-06")
    for off in ("off", "before"):
        monkeypatch.setenv("CHURCH_SCHEDULE", "off" if off == "off" else "on")
        monkeypatch.setattr(cs, "_FORCE", off != "before")
        n = len(db.reads)
        assert cs.withdraw_fact(biz(db), cid(db, "n024"), f["id"]) is False and len(db.reads) == n
        assert cs.takes(biz(db), cid(db, "elena")) is False and cs.on_schedule(biz(db), cid(db, "elena")) is False
        assert len(db.reads) == n, "and nobody's Away is asked about"


# ─── A yes opens the places they had agreed to serve ──────────────────

def test_a_yes_opens_the_places_they_agreed_to_the_way_cant_make_it_does(db, office):
    said = on_for(db, "elena", S[4])                       # Dec 20: she said yes to the Door
    before = on_for(db, "elena", S[2])                     # Dec 6: a yes outside the days she asks for
    waiting = on_for(db, "elena", S[3], status="asked")    # Dec 13: asked, never answered
    other = on_for(db, "n024", S[4], LOBBY)                # someone else's yes that same Sunday
    ss.ask_sub(biz(db), cid(db, "elena"), said, cid(db, "n025"))     # and she had asked someone to cover
    assert ss.yes_places(HOPE, cid(db, "elena"), day(23), day(37), now=fake.NOW) == [{"id": said, "service_id": S[4]}], \
        "only a yes, only inside the days: not the one she was asked for and never answered"
    row = asked(db, start=23, end=37, reason=SECRET)       # Dec 11 to 25
    assert row["flags"] == ["serving"], "the ask says she is down to serve one of those days"
    assert place(db, said)["status"] == "yes", "asking opens nothing: only a yes does"

    at_settle = []
    db.before_settle = lambda: at_settle.append(place(db, said)["status"])
    db.patches.clear()
    said_yes(db, row)
    assert at_settle == ["yes"], "after the write, never inside it"
    p = place(db, said)
    assert (p["status"], p["note"], p["swap_to"], p["swap_asked_at"]) == ("no", "Can't make it · Away", None, None)
    assert p["answered_at"] == fake.NOW.isoformat() and p["contact_id"] == cid(db, "elena")
    # Exactly what pressing "Can't make it" writes (with "Away" for why), key for key.
    twin = on_for(db, "n025", S[1])
    ss.cant_make_it(biz(db), cid(db, "n025"), twin, "Away")
    same = ("status", "note", "answered_at", "swap_to", "swap_asked_at", "swap_told_at")
    assert {k: p[k] for k in same} == {k: place(db, twin)[k] for k in same}
    [(path, body)] = [x for x in db.patches if x[0].startswith("/serve_assignments") and x[1].get("status") == "no"][:1]
    assert set(body) == set(same) and "status=eq.yes" in path and f"contact_id=eq.{cid(db, 'elena')}" in path, \
        "one write, the same keys for every place, only ones still hers and still a yes"
    # Only her yes inside the days: not the Sunday before, not one she never answered, not anyone else's.
    assert [place(db, a)["status"] for a in (before, waiting, other)] == ["yes", "asked", "yes"]
    # Whoever schedules sees the gap in the board's own words, and nothing of why.
    sched = office.get(f"/planning/schedule?business_id={HOPE}&weeks=5").json()
    seen = next(a for a in sched["assignments"] if a["id"] == said)
    assert (seen["status"], seen["note"], seen["swap_to"]) == ("no", "Can't make it · Away", None)
    assert SECRET not in json.dumps(sched) and "time_off" not in json.dumps(sched)
    # Doing it again changes nothing (a place already open is left alone).
    assert ss.open_places(HOPE, cid(db, "elena"), day(23), day(37), now=fake.NOW) == 0


def test_dates_says_before_the_yes_that_a_place_will_open(db, shell):
    """Whoever says yes, and the one who asked, read it while it waits: a
    yes changes Who serves when, and nobody should find that out after."""
    import member_portal_lead as mpl
    from types import SimpleNamespace

    def dates(handle):
        html, status = asyncio.run(mpl.serve(SimpleNamespace(query_params={}), biz(db), {}, me(db, handle),
                                             "/my/lead/dates"))
        assert status == 200
        return text(html)

    plain = asked(db, "yusuf", start=40, end=41)
    assert "opens again" not in dates("amara") and "opens again" not in dates("yusuf"), "nothing to open, nothing said"
    on_for(db, "elena", S[4])
    row = asked(db, reason=SECRET)
    theirs = "Elena said yes to serve on one of these days. With your yes, that place opens again for their team."
    mine_ = "You said yes to serve on one of these days. With a yes here, that place opens again for your team."
    assert theirs in dates("amara") and mine_ in dates("elena")
    for words in (theirs, mine_):
        for rule in (UUID, OFFICE_WORDS, TITLE_WORDS, KEYS):
            assert not rule.search(words), rule.search(words)
    said_yes(db, row)
    said_yes(db, plain)
    assert "opens again" not in dates("amara") and "opens again" not in dates("elena"), "said while it waits, only"


def test_cant_make_it_settles_at_once_and_opens_their_places_at_once(db):
    said = on_for(db, "elena", S[0])                       # this Sunday, Nov 22
    got = cs.ask(church(db), person(db, "elena"), {"starts_on": day(4), "ends_on": day(4), "kind": "cant"})
    assert got["state"] == "yes" and "serving" in got["flags"]
    assert (place(db, said)["status"], place(db, said)["note"]) == ("no", "Can't make it · Away")
    # Someone with no place to open: no flag, nothing touched, and no harm.
    plain = asked(db, "yusuf")
    assert plain["flags"] == []
    said_yes(db, plain)
    assert [r["status"] for r in db.t["serve_assignments"]] == ["no"]


def test_opening_their_places_can_fail_and_the_yes_still_stands(db, capsys):
    said = on_for(db, "elena", S[4])
    row = asked(db, reason=SECRET)
    for broken in ({"patch": "/serve_assignments"}, {"get": "/worship_services"}, {"get": "/serve_assignments"}):
        db.fail = dict(broken)
        row = asked(db, start=30, end=37) if row["state"] != "asked" else row
        got = cs.answer(church(db), person(db, "amara"), row["id"], True)
        assert got["state"] == "yes" and [f["ask_id"] for f in facts(db)] == [row["id"]], broken
        assert place(db, said)["status"] == "yes", "it couldn't be opened, and that is logged, not raised"
        logged = capsys.readouterr().out
        assert "weren't opened" in logged and SECRET not in logged and "Elena" not in logged and "Amara" not in logged
        db.fail = {}
        cs.withdraw(church(db), person(db, "elena"), row["id"])
    # And a read that fails while asking costs nobody their ask: no flag, nothing more.
    db.fail = {"get": "/worship_services"}
    assert asked(db, start=30, end=37)["flags"] == []


def test_a_year_of_services_is_read_a_page_at_a_time(db):
    """1,003 services inside the days (PostgREST gives 1,000 rows a read
    here), and the one she said yes to sorts last: it is found and opened."""
    last = "5f000000-0000-4000-8000-999999999999"
    for n in range(1002):
        d = date(2026, 12, 1) + timedelta(days=n % 300)
        db.t["worship_services"].append(_service(f"5f000000-0000-4000-8000-{n:012d}", d, 7 + n % 3, 0, title="Morning prayer"))
    db.t["worship_services"].append(_service(last, date(2027, 9, 26)))
    said = on_for(db, "elena", last)
    got = ss.yes_places(HOPE, cid(db, "elena"), "2026-12-01", "2027-10-01", now=fake.NOW)
    assert got == [{"id": said, "service_id": last}]
    assert ss.open_places(HOPE, cid(db, "elena"), "2026-12-01", "2027-10-01", now=fake.NOW) == 1
    assert place(db, said)["status"] == "no"


# ─── The rule code reads the church's data, never a title ─────────────

def test_no_title_word_or_role_key_decides_anything_here():
    keys = re.compile(r"\b(pastor|executive_pastor|associate_pastor|elders|deacons|ministers|youth_pastor|"
                      r"worship_leader|team_leader|director_of_operations|childrens_director)\b")
    for fn in (cs.holds, cs.on_schedule, cs.takes, cs.withdraw_fact, cs._open_places, cs._serving, ss.yes_places,
               ss.open_places, ss._ask_away, ss.add_away, ss.drop_away, sp._Board.is_away, mps._dates,
               mps._asked_flash, mps._dates_line):
        src = inspect.getsource(fn)
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        assert not keys.search(code), (fn.__name__, keys.search(code))
        assert not TITLE_WORDS.search(re.sub(r"#.*", "", code).replace("the church's owner", "")), fn.__name__
    for words in (*mps.ASKED.values(), *mps.ASKED_ALONE.values(), text(LINE)):
        for rule in (OFFICE_WORDS, TITLE_WORDS, KEYS, UUID):
            assert not rule.search(words.replace("{to}", "Amara Stone")), (words, rule.search(words))
