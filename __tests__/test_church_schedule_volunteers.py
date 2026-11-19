"""The leaders schedule, step 2: the volunteers' rules (church_schedule_
volunteers.py, and where it meets the Serve page, Dates, the notices and the
sweep; docs/CHURCH_SCHEDULE.md, PR S2-5). The platform owner's call 3,
approved 2026-11-18: "Volunteers need no yes to be away, unless the date is
full or they already agreed to serve it; then it goes to their team leader."

At New Hope (church_three: a made-up church of 500, every name in it made
up), on church_schedule_fake's tables with step 2's file applied, through the
real engine, the real scheduler and the member app's own routes. Pins:

  A FREE DATE IS SAVED AT ONCE, AS ALWAYS: the same write, the same page, byte
  for byte, at a church with departments and numbers set; nothing asked,
  nothing told
  A VOLUNTEER'S AWAY NEVER FAILS BECAUSE OF THIS: any read that fails, or
  anything at all going wrong, saves it at once, one line logged, never a 503
  FULL OR ALREADY SERVING: an ask to their team's leader (the chain: the
  team's own leaders, the department's by #1719's rule, its leader or
  overseer, whoever keeps Who serves when, the owner), never to themself,
  never to the leaders map's step over them, never instant
  THE TEAM'S LEADER ANSWERS on Dates (the entry is theirs while it waits,
  on the schedule or not): a plain yes, over the department's number too,
  that writes the away date and opens their places; not this one with a note
  PRIVATE: a reason and a note as shape() gives them; a member-app session is
  a person; another team's leader, an Admin and whoever keeps Who serves when
  never read either
  TOLD: who and which days and why it came, never a reason, a note or another
  name; claims in the database; quiet hours; the volunteer's notice opens My
  serving
  HELD: a waiting volunteer's ask holds them from being asked to serve, and
  the board says "away" in its own words; GET volunteers lists it
  THE SWEEP keeps it with the team, and moves it when the team's leader does
  BOUNDED, QUOTED, NO TITLE WORD, PLAIN WORDS
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
import os
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_leader_tasks as clt  # noqa: E402
import church_map  # noqa: E402
import church_over as co  # noqa: E402
import church_roles as cr  # noqa: E402
import church_schedule as cs  # noqa: E402
import church_schedule_fake as fake  # noqa: E402
import church_schedule_limits as csl  # noqa: E402
import church_schedule_tell as tell  # noqa: E402
import church_schedule_volunteers as csv  # noqa: E402
import church_three as c3  # noqa: E402
import member_portal_dates as mpd  # noqa: E402
import member_portal_lead as mpl  # noqa: E402
import member_portal_serving as mps  # noqa: E402
import sb_clients  # noqa: E402
import sunday_planning as sp  # noqa: E402
import sunday_serving as ss  # noqa: E402
from church_schedule_fake import NOW, day  # noqa: E402
from fastapi import HTTPException  # noqa: E402

HOPE = c3.NEW_HOPE                       # a made-up church of 500: every name in it is made up
NY = ZoneInfo("America/New_York")
SECRET = "Surgery for my mother that week"
NOTE = "We need you that week, sorry"
KIDS_TEAM = "5d000000-0000-4000-8000-0000000000a1"      # Kids Check-in: hangs from Kids by its name
CHECKIN = "5d000000-0000-4000-8000-0000000000a2"
BAND = "5d000000-0000-4000-8000-0000000000b1"           # Worship Team: no leader of its own
KEYS_PLACE = "5d000000-0000-4000-8000-0000000000b2"
LOT = "5d000000-0000-4000-8000-0000000000c1"            # Parking Team: no leader, no department
SUNDAYS = [date(2026, 11, 22) + timedelta(days=7 * i) for i in range(5)]      # ... Dec 13, Dec 20
S = [f"5e000000-0000-4000-8000-{i + 1:012d}" for i in range(5)]
DEC20 = "2026-12-20"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
OFFICE_WORDS = re.compile(r"\b(login|logins|seat|seats|manager|admin|lane|lanes|duty|duties|check_key|startup)\b", re.I)
TITLE_WORDS = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|overseers?|directors?|executive|"
                         r"treasurers?|secretary|owners?|trustees?|reverend|apostles?|prophets?)\b", re.I)
KEYS = re.compile(r"\b[a-z]+_[a-z_]+\b")
ROLE_KEYS = re.compile(r"\b(pastor|executive_pastor|associate_pastor|elders|deacons|ministers|youth_pastor|"
                       r"worship_leader|team_leader|director_of_operations|childrens_director)\b")


def _service(sid, d, hour=10, minute=30):
    at = datetime(d.year, d.month, d.day, hour, minute, tzinfo=NY).astimezone(timezone.utc)
    return {"id": sid, "business_id": HOPE, "title": "Sunday service", "starts_at": at.isoformat(), "archived_at": None,
            "is_template": False}


@pytest.fixture
def db(monkeypatch):
    """New Hope with step 2's file, five Sundays ahead, and three Sunday
    teams: Kids Check-in (hangs from Kids by name; its own leader N040; on
    it N041 to N044, who are on no leaders schedule), the Worship Team (hangs
    from Worship; no leader of its own; N045 on it) and the Parking Team (no
    leader, no department; N046 on it). Kids may have one away at once."""
    d = fake.build(monkeypatch, limits=True)
    for t in ("worship_services", "serve_teams", "serve_positions", "serve_trained", "serve_assignments", "serve_prefs",
              "church_thread_notes", "church_thread_reads", "member_push_subscriptions", "member_push_sends",
              "member_push_prefs", "member_push_held", "push_subscriptions"):
        d.t[t] = []
    monkeypatch.setenv("SUNDAY_PLANNING", "on")
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    monkeypatch.setenv("CHURCH_THREADS", "on")
    monkeypatch.delenv("MEMBER_QUIET_HOURS", raising=False)
    monkeypatch.setattr(sp, "_now", lambda: NOW)
    import rate_limit
    import church_threads
    import push_notifications
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **kw: True)
    monkeypatch.setattr(church_threads, "_READY", {"at": 0.0, "ok": None})
    monkeypatch.setattr(push_notifications, "push_enabled", lambda: True)
    for b in d.t["businesses"]:
        b["settings"] = {**b["settings"], "member_portal": {"notifications": {"serving": True}}}
    d.t["business_sites"].append({"business_id": HOPE, "slug": "new-hope", "site_config": {}})
    d.rang, d.mail = [], []

    def send_one(sub, payload, table="push_subscriptions"):
        staff = table == "push_subscriptions"
        d.rang.append({"to": sub.get("user_id") if staff else sub.get("contact_id"), "staff": staff, **payload})
        return True
    monkeypatch.setattr(push_notifications, "_send_one", send_one)
    monkeypatch.setattr(clt, "deliver", lambda biz, to, name, subject, html, key, reply_to=None: d.mail.append(
        {"to": to, "subject": subject, "html": html, "key": key}))
    w = d.who[HOPE]
    for gid, name, people in ((KIDS_TEAM, "Kids Check-in", (("n040", "leader"), ("n041", "member"), ("n042", "member"),
                                                            ("n043", "member"), ("n044", "member"))),
                              (BAND, "Worship Team", (("n045", "member"),)),
                              (LOT, "Parking Team", (("n046", "member"),))):
        d.t["groups"].append({"id": gid, "business_id": HOPE, "name": name, "kind": "team", "active": True})
        d.t["serve_teams"].append({"group_id": gid, "business_id": HOPE, "call_time": None, "max_month": 4,
                                   "owner": "volunteers", "swap_needs_ok": False, "families": True, "sort": 0})
        for h, role in people:
            d.t["group_members"].append({"group_id": gid, "business_id": HOPE, "contact_id": w[h], "role": role})
    for pid, gid, name, who in ((CHECKIN, KIDS_TEAM, "Check-in", ("n041", "n042", "n043", "n044")),
                                (KEYS_PLACE, BAND, "Keys", ("n045",))):
        d.t["serve_positions"].append({"id": pid, "business_id": HOPE, "group_id": gid, "name": name, "needed": 4,
                                       "note": "", "sort": 0, "active": True, "created_at": "2026-11-01T00:00:00+00:00"})
        for h in who:
            d.t["serve_trained"].append({"business_id": HOPE, "position_id": pid, "contact_id": w[h], "level": "trained"})
    d.t["worship_services"] += [_service(sid, on) for sid, on in zip(S, SUNDAYS)]
    d.t["church_schedule_department_limits"].append({"department_id": dept(d, "Kids"), "business_id": HOPE,
                                                     "at_most": 1, "set_by_user_id": None, "set_by_contact_id": None,
                                                     "updated_at": NOW.isoformat()})
    return d


@pytest.fixture
def shell(monkeypatch):
    import member_portal
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **kw: body)


@pytest.fixture
def app(db, monkeypatch):
    """The Serve page's and Dates' own routes, signed in as `app.state["me"]`."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import member_portal_church as mpc
    a = FastAPI()
    a.include_router(mps.router)
    a.include_router(mpd.router)
    state = {"me": None}

    async def signed_in(request):
        return {"business": member(db), "site": {}}, state["me"], False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    c = TestClient(a)
    c.state, c.db = state, db
    return c


# ─── helpers ──────────────────────────────────────────────────────────

def dept(db, name):
    return next(x["id"] for x in db.t["church_departments"] if x["business_id"] == HOPE and x["name"] == name)


def biz(db):
    return c3.church(db, HOPE)


def member(db):
    """The church as the member app has it: member_portal's site row embeds
    the business without its owner, and every page and route of the member
    app hands that row on."""
    return {k: v for k, v in c3.church(db, HOPE).items() if k != "owner_id"}


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


def away(db, handle, start=DEC20, end=None):
    """An away date that was agreed: a fact, however it got there."""
    r = {"id": str(uuid.uuid4()), "business_id": HOPE, "contact_id": cid(db, handle), "starts_on": start,
         "ends_on": end or start, "note": "", "ask_id": None, "kind": None, "created_at": NOW.isoformat()}
    db.t["serve_away"].append(r)
    return r


def on_for(db, handle, sid=S[4], pid=CHECKIN, status="yes"):
    """Ask them to a place through the scheduler, and a yes through their own page."""
    aid = sp.do_ask(HOPE, sid, pid, 1, cid(db, handle), "The office")["assignment"]["id"]
    if status == "yes":
        ss.answer(biz(db), cid(db, handle), aid, "yes")
    return aid


def place(db, aid):
    return next(r for r in db.t["serve_assignments"] if r["id"] == aid)


def as_(app, handle):
    app.state["me"] = me(app.db, handle)


def post(app, path, **form):
    r = app.post(path, data=form, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r.headers["location"]


def serving(db, handle, query=b""):
    """My serving, through its own route, as it renders."""
    from starlette.requests import Request
    req = Request({"type": "http", "query_string": query, "headers": []})
    out = asyncio.run(mps.serve(req, {"business": member(db), "site": {}}, me(db, handle), "/my/serving"))
    assert out.status_code == 200, out.status_code
    return out.body.decode()


def dates(db, handle, **q):
    html, status = asyncio.run(mpl.serve(SimpleNamespace(query_params=q), member(db), {}, me(db, handle),
                                         "/my/lead/dates"))
    return html, status


def text(html):
    out = re.sub(r"<[^>]+>", " ", re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S))
    return re.sub(r"\s+", " ", out.replace("&#x27;", "'"))


def calls(monkeypatch):
    """Every call to the database from here on: (verb, path, body)."""
    seen = []
    for verb in ("get", "post", "patch", "delete"):
        real = getattr(sb_clients, f"sb_{verb}_as_service")

        def spy(path, *a, _verb=verb, _real=real, **k):
            seen.append((_verb, path, copy.deepcopy(a[0]) if a else None))
            return _real(path, *a, **k)
        monkeypatch.setattr(sb_clients, f"sb_{verb}_as_service", spy)
    return seen


def said(db):
    return json.dumps([db.rang, db.mail, db.t["church_thread_notes"], db.t["member_push_sends"],
                       db.t["member_push_held"]], ensure_ascii=False)


def phone(db, handle):
    db.t["member_push_subscriptions"].append({"id": str(uuid.uuid4()), "business_id": HOPE,
                                              "contact_id": cid(db, handle),
                                              "endpoint": f"https://push.example/{handle}", "subscription": {}})


def vol_ask(db, handle="n041", start=day(30), end=day(37)):
    """A volunteer's Away through the Serve page's own function: its row."""
    got = ss.add_away(member(db), cid(db, handle), start, end)
    assert got.get("volunteer") is True, got
    return next(r for r in asks(db) if r["contact_id"] == cid(db, handle) and r["starts_on"] == start)


# ─── A free date is saved at once, as always ──────────────────────────

def test_a_free_date_is_saved_at_once_with_the_same_write_and_the_same_page(app, db, shell, monkeypatch):
    """Departments and numbers set (Kids: one at a time), and N041 on Kids
    Check-in serving nowhere those days, with nobody from Kids away: the
    same plain away date, the same words, the same page, as with the leaders
    schedule off. Nothing asked, nothing told, nothing else written."""
    on_for(db, "n041", S[0])                      # a Sunday outside the days they pick
    seen = calls(monkeypatch)
    as_(app, "n041")
    assert post(app, "/my/serving/away", start=day(30), end=day(37)) == "/my/serving?done=away"
    open_writes = [c for c in seen if c[0] != "get"]
    open_page = serving(db, "n041", b"done=away")
    assert asks(db) == [] and db.rpcs == [] and db.later == []
    [f] = facts(db)
    assert (f["contact_id"], f["starts_on"], f["ends_on"], f.get("ask_id"), f.get("kind")) == \
        (cid(db, "n041"), day(30), day(37), None, None)
    db.t["serve_away"].clear()
    monkeypatch.setenv("CHURCH_SCHEDULE", "off")
    seen.clear()
    assert post(app, "/my/serving/away", start=day(30), end=day(37)) == "/my/serving?done=away"
    off_writes = [c for c in seen if c[0] != "get"]
    off_page = serving(db, "n041", b"done=away")
    assert open_writes == off_writes and len(off_writes) == 1 and off_writes[0][0] == "post", "the same one write"
    assert off_writes[0][2] == {"business_id": HOPE, "contact_id": cid(db, "n041"), "starts_on": day(30),
                                "ends_on": day(37), "note": ""}
    assert open_page.count(f["id"]) == 1, "its own away date, with its own id"
    # Byte for byte, but for the id each insert is given.
    assert UUID.sub("<id>", open_page) == UUID.sub("<id>", off_page), "the same page, byte for byte"
    assert "Saved. Nobody asks you on those days." in text(open_page)


def test_a_waiting_ask_never_makes_a_day_full_only_an_away_date_that_was_agreed(db):
    """S2-3's count: N042 has a volunteer's ask waiting for Dec 20, so Kids
    isn't full that day; once N042 has an away date that was agreed, it is."""
    on_for(db, "n042")
    vol_ask(db, "n042", DEC20, DEC20)
    got = ss.add_away(member(db), cid(db, "n041"), DEC20, DEC20)
    assert got.get("id") and "asked" not in got, "free: saved at once"
    db.t["serve_away"].clear()
    away(db, "n043")
    got = ss.add_away(member(db), cid(db, "n041"), DEC20, DEC20)
    assert got.get("volunteer") is True and asks(db)[-1]["flags"] == ["over_limit"]


def test_closed_or_before_step_twos_tables_nothing_here_reads(db, monkeypatch):
    on_for(db, "n041")
    for off in ("off", "step1", "before"):
        monkeypatch.setenv("CHURCH_SCHEDULE", "off" if off == "off" else "on")
        monkeypatch.setattr(csl, "_FORCE", off != "step1")
        monkeypatch.setattr(cs, "_FORCE", off != "before")
        n = len(db.reads)
        assert csv.away(member(db), cid(db, "n041"), DEC20, DEC20) is None
        assert csv.mine(member(db), cid(db, "n041")) is None and mps._vol(member(db), cid(db, "n041")) is None
        assert len(db.reads) == n, off


# ─── A volunteer's Away never fails because of this ───────────────────

@pytest.mark.parametrize("table", ["/serve_teams", "/group_members", "/church_schedule_department_limits",
                                   f"/serve_away?business_id=eq.{HOPE}&contact_id=in.", "/worship_services",
                                   "/serve_assignments", "/church_departments", "/church_away_asks",
                                   "/church_schedule_people"])
def test_a_read_that_fails_saves_the_away_at_once_never_a_503(app, db, table, capsys):
    """Each read this needs (the teams, the numbers, the away dates it
    counts, the places, the map, the asks, who is on the leaders schedule).
    The Away's own reads and write are what they always were."""
    on_for(db, "n041")                            # serving that Sunday: it would be an ask
    away(db, "n042")                              # and Kids is full that day
    capsys.readouterr()
    db.fail = {"get": table}
    as_(app, "n041")
    assert post(app, "/my/serving/away", start=DEC20, end=DEC20) == "/my/serving?done=away", table
    assert asks(db) == [] and [f["contact_id"] for f in facts(db) if f.get("ask_id") is None][-1] == cid(db, "n041")
    lines = [x for x in capsys.readouterr().out.splitlines() if "saved at once" in x]
    assert len(lines) == 1 and HOPE[:8] in lines[0], lines
    for private in ("N041", "N040", cid(db, "n041"), HOPE, DEC20):
        assert private not in lines[0]


def test_anything_at_all_going_wrong_saves_the_away_at_once(app, db, monkeypatch):
    on_for(db, "n041")
    for broken in ("volunteer_plan", "ask", "leader_of"):
        db.t["serve_away"].clear()

        def down(*a, **k):
            raise RuntimeError("down")
        with monkeypatch.context() as m:
            m.setattr(csv, broken, down)
            as_(app, "n041")
            assert post(app, "/my/serving/away", start=DEC20, end=DEC20) == "/my/serving?done=away", broken
        assert asks(db) == [] and len(facts(db)) == 1
    db.t["serve_away"].clear()
    db.fail = {"post": "/church_away_asks"}          # the ask's own write
    assert post(app, "/my/serving/away", start=DEC20, end=DEC20) == "/my/serving?done=away"
    assert asks(db) == [] and len(facts(db)) == 1 and db.later == []


# ─── Full, or already serving: an ask to their team's leader ──────────

def test_already_serving_goes_to_the_team_leader_and_the_page_says_so(app, db, shell):
    aid = on_for(db, "n041")                      # Dec 20, Check-in
    as_(app, "n041")
    assert post(app, "/my/serving/away", start=day(30), end=day(37)) == "/my/serving?done=vol_asked"
    [a] = asks(db)
    assert (a["grp"], a["kind"], a["state"], a["flags"], a["reason"], a["made_by"]) == \
        ("volunteers", "time_off", "asked", ["serving"], None, None)
    assert (a["team_group_id"], a["department_id"], a["to_contact_id"], a["to_user_id"]) == \
        (KIDS_TEAM, dept(db, "Kids"), cid(db, "n040"), None), "to the team's own leader"
    assert a["to_contact_id"] != (cs.goes_to(church(db), cid(db, "n041")) or {}).get("id"), \
        "never the leaders map's step over them"
    assert facts(db) == [] and place(db, aid)["status"] == "yes", "never instant: nothing saved, nothing opened"
    assert len(db.later) == 1, "the team's leader is told, by the engine's own notice"
    html = serving(db, "n041", b"done=vol_asked")
    words = text(html)
    assert ("Sent to N040 Member, because you're on the schedule on one of those days. With a yes these days go on "
            "your away days. Find someone to cover Dec 20") in words
    assert f'href="/my/serving?sub={aid}"' in html
    assert "Dec 18 – 25 · waiting for N040 Member" in words, "beside their away dates, while it waits"
    assert f'name="id" value="{a["id"]}"' in html
    # A second press of the same days is the same ask, never a second.
    assert post(app, "/my/serving/away", start=day(30), end=day(37)) == "/my/serving?done=vol_asked"
    assert len(asks(db)) == 1


def test_a_full_day_goes_to_the_team_leader_and_says_which_department(app, db, shell):
    away(db, "n042")                              # one of Kids away on Dec 20, and Kids takes one
    as_(app, "n041")
    assert post(app, "/my/serving/away", start=DEC20, end=DEC20) == "/my/serving?done=vol_asked"
    [a] = asks(db)
    assert (a["flags"], a["to_contact_id"], a["team_group_id"], a["department_id"]) == \
        (["over_limit"], cid(db, "n040"), KIDS_TEAM, dept(db, "Kids"))
    words = text(serving(db, "n041", b"done=vol_asked"))
    assert "Sent to N040 Member, because that day is full for Kids. With a yes these days go on your away days." in words
    assert "Find someone to cover" not in words, "nothing of theirs to cover"
    # Full and serving both: one ask, both said.
    on_for(db, "n043")
    away(db, "n044", day(39))
    as_(app, "n043")
    post(app, "/my/serving/away", start=day(32), end=day(39))
    b = asks(db)[-1]
    assert b["flags"] == ["serving", "over_limit"] and b["to_contact_id"] == cid(db, "n040")
    assert ("because you're on the schedule on one of those days, and one of them is full for Kids"
            in text(serving(db, "n043", b"done=vol_asked")))


def test_a_team_with_no_leader_of_its_own_goes_up_its_own_chain(db, monkeypatch):
    """#1719's cases: the department's leader while they hold a role that
    leads, else its overseer while they hold one that oversees (as
    church_map.team_head says), else its leader, else its overseer; a team
    on no department goes to whoever keeps Who serves when, else the
    owner. Never the volunteer themself."""
    ch = church(db)
    with church_map.once():
        head = church_map.team_head(ch.map, ch.defs, cr.active_holders(ch.holders), "Worship Team")
        got = csv.team_step(ch, BAND, but=cid(db, "n045"))
    worship = next(d for d in ch.map.active() if d["name"] == "Worship")
    want = head[1]["contact_id"] if head else worship["leader_contact_id"]
    assert [s["id"] for s in got] == [want] and got[0]["kind"] == co.PERSON, "team_head's own answer"
    # Nobody at the department holds a role: its leader, as a person, whatever they hold.
    db.t["church_leader_roles"] = [h for h in db.t["church_leader_roles"]
                                   if h["contact_id"] not in (worship["leader_contact_id"], worship["overseer_contact_id"])]
    assert [s["id"] for s in csv.team_step(church(db), BAND, but=cid(db, "n045"))] == [worship["leader_contact_id"]]
    # No department: whoever keeps Who serves when (a Manager with that duty; never an Admin), else the owner.
    keep = csv.team_step(church(db), LOT, but=cid(db, "n046"))
    assert keep and all(s["kind"] == co.LOGIN for s in keep)
    assert all(church(db).role(s["id"]) == "manager" and csl.SERVE_DUTY in church(db).held(s["id"]) for s in keep)
    with monkeypatch.context() as m:
        m.setattr(csv, "_keepers", lambda ch, but: [])
        assert csv.team_step(church(db), LOT) == [{"kind": co.LOGIN, "id": c3.NH_OWNER, "name": "Pastor Nathan"}]
    # The team's only leader, taken off the leaders schedule, is a volunteer: never asked for their own.
    db.t["church_schedule_people"].append({"business_id": HOPE, "contact_id": cid(db, "n040"), "listed": "remove",
                                           "grp": None})
    step = csv.team_step(church(db), KIDS_TEAM, but=cid(db, "n040"))
    assert cid(db, "n040") not in [s["id"] for s in step] and step
    on_for(db, "n041")
    vol = csv.volunteer_plan(church(db), cid(db, "n041"), date(2026, 12, 20), date(2026, 12, 20))
    assert vol["to"]["id"] == cid(db, "n040") and vol["instant"] is False


def test_the_worship_volunteer_and_the_parking_volunteer_each_go_where_their_chain_says(app, db):
    on_for(db, "n045", S[4], KEYS_PLACE)
    a = vol_ask(db, "n045", DEC20, DEC20)
    want = csv.leader_of(church(db), BAND, but=cid(db, "n045"))
    assert (a["to_contact_id"] or a["to_user_id"]) == want["id"] and a["department_id"] == dept(db, "Worship")
    # The Parking Team's volunteer said yes to nothing and no department counts them: free, saved at once.
    got = ss.add_away(member(db), cid(db, "n046"), DEC20, DEC20)
    assert got.get("id") and "asked" not in got


def test_an_ask_that_went_to_the_owner_says_their_name_on_my_serving(app, db, shell, monkeypatch):
    """The chain's last step is the owner. The member app's church row has
    no owner on it, so My serving reads the whole row for its asks: the
    page names them by the church's own name for them. And Dates reads the
    whole row too (member_portal_dates._ch_me), so the owner's own person
    has it and answers it there: nobody else can, as a person."""
    lot_place = "5d000000-0000-4000-8000-0000000000c2"
    db.t["serve_positions"].append({"id": lot_place, "business_id": HOPE, "group_id": LOT, "name": "Lot", "needed": 2,
                                    "note": "", "sort": 0, "active": True, "created_at": "2026-11-01T00:00:00+00:00"})
    db.t["serve_trained"].append({"business_id": HOPE, "position_id": lot_place, "contact_id": cid(db, "n046"),
                                  "level": "trained"})
    on_for(db, "n046", S[4], lot_place)
    monkeypatch.setattr(csv, "_keepers", lambda ch, but: [])
    a = vol_ask(db, "n046", DEC20, DEC20)
    assert (a["to_user_id"], a["to_contact_id"], a["department_id"], a["team_group_id"]) == (c3.NH_OWNER, None, None, LOT)
    words = text(serving(db, "n046", b"done=vol_asked"))
    assert "Sent to Pastor Nathan, because you're on the schedule that day." in words
    assert "Dec 20 · waiting for Pastor Nathan" in words
    for h in ("owen", "kara", "n040"):
        as_(app, h)
        assert post(app, f"/my/lead/dates/{a['id']}/answer", ans="yes").endswith("err=dt_not_yours"), h
    html, status = dates(db, "nathan")
    assert status == 200 and f'/my/lead/dates/{a["id"]}/answer' in html and "Waiting for your yes" in text(html)
    as_(app, "nathan")
    assert post(app, f"/my/lead/dates/{a['id']}/answer", ans="yes").endswith("done=dt_yes")
    assert a["state"] == "yes" and a["decided_by_contact_id"] == cid(db, "nathan") and len(facts(db)) == 1


def test_an_away_for_today_is_saved_at_once_with_a_place_later_today_and_the_day_full(db):
    """Sick today (docs/CHURCH_SCHEDULE.md, the decision table): an away
    date for today stays instant, whatever they said yes to later today and
    however full the day is; they use Can't make it on the place itself.
    Found in review of S2-5."""
    tonight = "5e000000-0000-4000-8000-000000000099"
    db.t["worship_services"].append(_service(tonight, date(2026, 11, 18), hour=19, minute=0))
    on_for(db, "n041", tonight)
    away(db, "n042", day(0))                      # Kids is full today too
    got = ss.add_away(member(db), cid(db, "n041"), day(0), day(0))
    assert got.get("id") and "asked" not in got and asks(db) == []
    assert [(f["starts_on"], f.get("ask_id")) for f in facts(db) if f["contact_id"] == cid(db, "n041")] == [(day(0), None)]
    # Tomorrow on, it is looked at as ever: Sunday full for Kids is an ask.
    away(db, "n042", day(4))
    assert ss.add_away(member(db), cid(db, "n043"), day(4), day(4)).get("volunteer") is True


def test_a_stand_in_name_is_never_what_a_volunteer_reads():
    """No name to say (a church with no name for its owner, an office login
    with no person or seat name): My serving says "your team's leader",
    never "The owner" or "An office login". Found in review of S2-5."""
    for stand_in in ("", "Someone", "The owner", "An office login", cs.LEFT):
        assert mps._vol_to({"to": {"name": stand_in}}) == "", stand_in
    assert mps._vol_to({"to": {"name": "Pastor Nathan"}}) == "Pastor Nathan"
    said = mps._vol_lines({"vol": {"asks": [{"state": "no", "starts_on": DEC20, "ends_on": DEC20,
                                             "decided": {"by": "The owner", "note": ""}}]}})
    assert "The owner" not in said and "leader said not this one to Dec 20" in said


def test_someone_on_the_leaders_schedule_is_never_a_volunteer_here(db):
    """N040 leads Kids Check-in, so is on the leaders schedule: their Away is
    the leaders' ask (S1-6), whatever they serve; the leaders' rules hold."""
    db.t["group_members"].append({"group_id": KIDS_TEAM, "business_id": HOPE, "contact_id": cid(db, "elena"),
                                  "role": "member"})
    db.t["serve_trained"].append({"business_id": HOPE, "position_id": CHECKIN, "contact_id": cid(db, "elena"),
                                  "level": "trained"})
    on_for(db, "elena")
    got = ss.add_away(member(db), cid(db, "elena"), day(30), day(37))
    assert "volunteer" not in got and got["to"] == "Amara Stone"
    [a] = asks(db)
    assert a["grp"] == "leaders" and a["to_contact_id"] == cid(db, "amara") and "serving" in a["flags"]


# ─── The team's leader answers ────────────────────────────────────────

def test_the_team_leader_says_yes_on_dates_and_their_places_open(app, db, shell):
    aid = on_for(db, "n041")
    a = vol_ask(db)
    html, status = dates(db, "n040")
    words = text(html)
    assert status == 200 and "Waiting for your yes" in words and "N041 Member" in words
    assert "Why it came to you N041 is on the schedule to serve on one of these days. Your yes is all it needs." in words
    assert "N041 said yes to serve on one of these days. With your yes, that place opens again for their team." in words
    assert 'name="shown"' not in html, "a plain yes: nothing to except"
    as_(app, "n040")
    assert post(app, f"/my/lead/dates/{a['id']}/answer", ans="yes").endswith("done=dt_yes")
    assert a["state"] == "yes" and a["excepted"] == [] and a["decided_by_contact_id"] == cid(db, "n040")
    assert [sorted(r) for r in db.rpcs] == [["p_ask_id", "p_business_id", "p_by_contact", "p_by_user", "p_note",
                                            "p_state"]], "church_away_settle itself, no exception"
    [f] = facts(db)
    assert (f["ask_id"], f["starts_on"], f["ends_on"]) == (a["id"], day(30), day(37))
    assert (place(db, aid)["status"], place(db, aid)["note"]) == ("no", "Can't make it · Away"), "their place opened"
    assert "Dec 18 – 25" in text(serving(db, "n041")) and "waiting for" not in text(serving(db, "n041"))


def test_the_team_leader_says_yes_over_the_departments_number(app, db):
    """A plain yes for their own team, even with the day full: never sent
    up, never rechecked, no exception (docs/CHURCH_SCHEDULE.md 7.11)."""
    away(db, "n042")
    a = vol_ask(db, start=DEC20, end=DEC20)
    away(db, "n043")                              # and fuller still since it was asked
    assert cs.flagged(a) is False and cs.flagged({"flags": ["over_limit"], "grp": "leaders"}) is True
    got = cs.answer(church(db), person(db, "n040"), a["id"], True)
    assert got["state"] == "yes" and got.get("excepted") == [] and a["to_contact_id"] == cid(db, "n040")
    assert db.t["church_away_asks"][0]["flags"] == ["over_limit"], "never marked, never moved"
    # The days route shows Kids over its number now, from the facts, as it says it will.
    day_ = csl.days(church(db), co.who(co.LOGIN, c3.NH_OWNER), date(2026, 12, 20), date(2026, 12, 20))["days"][0]
    kids = next(x for x in day_["departments"] if x["name"] == "Kids")
    assert (kids["away"], kids["at_most"], kids["full"]) == (3, 1, True)


def test_not_this_one_with_a_note_is_theirs_and_the_team_leaders_only(app, db, shell):
    on_for(db, "n041")
    a = vol_ask(db)
    a["reason"] = SECRET                          # (a reason set by hand: the Serve page asks for none)
    as_(app, "n040")
    assert post(app, f"/my/lead/dates/{a['id']}/answer", ans="no", note=NOTE).endswith("done=dt_no")
    assert a["state"] == "no" and a["decided_note"] == NOTE and facts(db) == []
    words = text(serving(db, "n041"))
    assert f"N040 Member said not this one to Dec 18 – 25. N040's note: {NOTE}" in words
    # shape()'s rule: the volunteer, whoever it went to, the owner and whoever oversees the office.
    ch = church(db)
    names = cs._names(ch, [a])
    for who, sees in ((person(db, "n041"), True), (person(db, "n040"), True), (co.who(co.LOGIN, c3.NH_OWNER), True),
                      (co.who(co.LOGIN, db.who[HOPE]["owen@"]), True), (person(db, "kara"), False),
                      (person(db, "wren"), False), (co.who(co.LOGIN, db.who[HOPE]["tessa@"]), False),
                      (co.who(co.LOGIN, db.who[HOPE]["sunny@"]), False), (person(db, "nathan"), False),
                      (person(db, "owen"), False)):
        s = cs.shape(ch, who, a, names)
        assert (s["reason"] == SECRET, (s["decided"] or {}).get("note") == NOTE) == (sees, sees), who
    # Another team's leader, or the department's, never has it on their page.
    for h in ("kara", "wren", "amara"):
        html, _status = dates(db, h)
        assert NOTE not in html and SECRET not in html and "N041" not in html, h


def test_the_dates_entry_is_the_team_leaders_while_it_waits_on_the_schedule_or_not(db):
    db.t["church_schedule_people"].append({"business_id": HOPE, "contact_id": cid(db, "n040"), "listed": "remove",
                                           "grp": None})
    assert cs.section(member(db), cid(db, "n040")) is None, "off the schedule, nothing waiting: no entry"
    on_for(db, "n041")
    vol_ask(db)
    assert cs.section(member(db), cid(db, "n040")) == {"waiting": 1}
    html, status = dates(db, "n040")
    assert status == 200 and "Waiting for your yes" in text(html) and "Ask for time off" not in text(html)


def test_a_member_app_session_is_a_person_and_never_gets_an_across_the_board_view(app, db, shell):
    """The owner's own person and the person of whoever oversees the office
    read and answer only what went to them: a volunteer's ask to the team's
    leader is neither's."""
    on_for(db, "n041")
    a = vol_ask(db)
    for h in ("nathan", "owen", "sunny", "kara"):
        html, _status = dates(db, h)
        assert f'/my/lead/dates/{a["id"]}/answer' not in html, h
        as_(app, h)
        assert post(app, f"/my/lead/dates/{a['id']}/answer", ans="yes").endswith("err=dt_not_yours"), h
    assert a["state"] == "asked" and facts(db) == []
    # In the office app the owner, a login, may answer any (decision 6): not the member app.
    assert cs.may_decide(church(db), co.who(co.LOGIN, c3.NH_OWNER), a) is True
    assert cs.may_decide(church(db), person(db, "nathan"), a) is False


def test_cant_make_it_on_a_place_works_exactly_as_before(app, db):
    aid = on_for(db, "n041")
    as_(app, "n041")
    assert post(app, "/my/serving/cant", id=aid) == "/my/serving?done=told"
    assert (place(db, aid)["status"], place(db, aid)["note"]) == ("no", "Can't make it")
    assert asks(db) == [] and facts(db) == [] and db.rpcs == []


def test_taking_back_a_waiting_ask_from_my_serving(app, db):
    on_for(db, "n041")
    a = vol_ask(db)
    fake.later(db)                                # N040 is told of it
    as_(app, "n042")                              # somebody else's is never theirs to take back
    assert post(app, "/my/serving/away/remove", id=a["id"]) == "/my/serving?done=unaway"
    assert a["state"] == "asked"
    as_(app, "n041")
    assert post(app, "/my/serving/away/remove", id=a["id"]) == "/my/serving?done=unaway"
    assert a["state"] == "withdrawn" and facts(db) == []
    assert db.rpcs[-1]["p_state"] == "withdrawn" and len(db.later) == 1, "and whoever it went to hears"


# ─── Told ─────────────────────────────────────────────────────────────

def test_the_team_leader_is_told_who_which_days_and_why_and_nothing_else(db):
    phone(db, "n040")
    on_for(db, "n041")
    away(db, "n042")
    a = vol_ask(db, start=DEC20, end=DEC20)
    a["reason"] = SECRET
    assert fake.later(db) == 1
    [p] = db.rang
    assert (p["to"], p["body"]) == (cid(db, "n040"), "N041 asked for Dec 20 — They’re on the schedule to serve that "
                                                      "day, and it’s already full, so it came to you. Say yes or not "
                                                      "this one when you can.")
    assert a["told_at"], "claimed in the database"
    assert tell.tell_new(church(db), a) == "none", "told once"
    everything = said(db)
    for word in (SECRET, "Kids", "N042", "N040 Member", "Surgery"):
        assert word not in everything, word
    # The answer, to the volunteer, opens My serving; never the note.
    cs.answer(church(db), person(db, "n040"), a["id"], False, NOTE)
    assert fake.later(db) == 1
    [m] = db.mail                                 # no phone: by email
    assert m["to"] == "n041@newhope.church" and m["subject"] == "New Hope Church: an answer about Dec 20"
    assert "/my/serving" in m["html"] and "Open My serving" in m["html"] and NOTE not in said(db)
    assert a["answer_told_at"]


def test_quiet_hours_hold_it_and_the_sweep_sends_it_in_the_morning(db):
    night = datetime(2026, 11, 19, 4, 0, tzinfo=timezone.utc)          # 11 PM at the church
    phone(db, "n040")
    on_for(db, "n041")
    a = vol_ask(db)
    assert tell.tell_new(church(db), a, now=night) == "held" and db.rang == [] and not a["told_at"]
    db.later.clear()
    stats = tell.sweep_tick(night + timedelta(hours=9))
    assert stats["told"] == 1 and [p["to"] for p in db.rang] == [cid(db, "n040")]


def test_the_sweep_keeps_it_with_the_team_and_moves_it_when_the_team_leader_does(db):
    on_for(db, "n041")
    a = vol_ask(db)
    fake.later(db)
    assert tell.sweep_tick(NOW + timedelta(hours=1))["moved"] == 0
    assert a["to_contact_id"] == cid(db, "n040"), "never sent to the leaders map's step over them"
    # Read without its team (step 2 blipped on a replica's first look: the sweep doesn't name the column, and
    # PostgREST returns only what is named; the fake returns every column): left where it is, never sent on to
    # the department's head and back.
    assert csv.stale(church(db), {k: v for k, v in a.items() if k != "team_group_id"}) is None
    # The team has a new leader: it goes to them, and they hear.
    for r in db.t["group_members"]:
        if r["group_id"] == KIDS_TEAM and r["contact_id"] == cid(db, "n040"):
            r["role"] = "member"
    db.t["group_members"].append({"group_id": KIDS_TEAM, "business_id": HOPE, "contact_id": cid(db, "n047"),
                                  "role": "leader"})
    phone(db, "n047")
    stats = tell.sweep_tick(NOW + timedelta(hours=2))
    assert stats["moved"] == 1 and a["to_contact_id"] == cid(db, "n047") and a["told_at"]
    assert [p["to"] for p in db.rang][-1] == cid(db, "n047")


# ─── Held, and listed for whoever keeps Who serves when ───────────────

def test_a_waiting_ask_holds_them_and_the_board_says_away_in_its_own_words(db):
    away(db, "n043")                              # an away date, to hear the board's words for it
    db.t["group_members"].append({"group_id": KIDS_TEAM, "business_id": HOPE, "contact_id": cid(db, "n048"),
                                  "role": "member"})
    db.t["serve_trained"].append({"business_id": HOPE, "position_id": CHECKIN, "contact_id": cid(db, "n048"),
                                  "level": "trained"})
    on_for(db, "n041", S[3])                      # a yes on Dec 13, inside the days asked
    vol_ask(db, start=day(24), end=day(32))
    board = sp._service_board(HOPE, S[4])
    who = {c["name"]: c for c in board.candidates(S[4], CHECKIN)}
    assert who["N041 Member"]["away"] is True and who["N043 Member"]["away"] is True
    assert {k: who["N041 Member"][k] for k in ("away", "ok", "clash")} == \
        {k: who["N043 Member"][k] for k in ("away", "ok", "clash")}, "the same words as an away date's"
    assert who["N048 Member"]["away"] is False
    with pytest.raises(HTTPException) as e:
        sp.do_ask(HOPE, S[4], CHECKIN, 2, cid(db, "n041"), "The office")
    assert e.value.status_code == 409
    sched_away = [a for a in board.away if a.get("contact_id") == cid(db, "n041")]
    assert sched_away == [], "never in the schedule's list of who is away"


def test_get_volunteers_lists_it_under_its_department_and_never_a_reason(db):
    on_for(db, "n041")
    a = vol_ask(db)
    a["reason"] = SECRET
    got = csl.volunteers(church(db), co.who(co.LOGIN, db.who[HOPE]["sunny@"]), NOW.date(), NOW.date() + timedelta(days=60))
    kids = next(d for d in got["departments"] if d["name"] == "Kids")
    assert kids["waiting"] == [{"contact_id": cid(db, "n041"), "name": "N041 Member", "starts_on": day(30),
                                "ends_on": day(37), "flags": ["serving"]}]
    assert SECRET not in json.dumps(got)


# ─── Bounded, quoted, and the rule code's own words ───────────────────

def test_a_volunteer_in_a_thousand_and_three_groups_is_found_on_their_team(db):
    w = cid(db, "n041")
    db.t["group_members"] = [r for r in db.t["group_members"] if r["contact_id"] != w]
    for i in range(1003):
        db.t["group_members"].append({"group_id": f"00000000-0000-4000-8000-{i:012d}", "business_id": HOPE,
                                      "contact_id": w, "role": "member"})
    db.t["group_members"].append({"group_id": KIDS_TEAM, "business_id": HOPE, "contact_id": w, "role": "member"})
    assert csv.teams_of(church(db), w) == [KIDS_TEAM]
    assert [d["name"] for d in csv.departments_of(church(db), w)] == ["Kids"]


def test_every_value_in_an_address_is_quoted_and_every_read_is_this_churchs(db):
    on_for(db, "n041")
    away(db, "n042")
    db.reads.clear()
    vol_ask(db, start=DEC20, end=DEC20)
    csv.mine(member(db), cid(db, "n041"))
    mine = [p for p in db.reads if p.startswith(("/serve_", "/group_members", "/groups?", "/worship_services",
                                                 "/church_away_asks", "/church_schedule"))]
    assert len(mine) > 8
    for p in mine:
        assert "+" not in p and " " not in p and "'" not in p, p
        assert f"business_id=eq.{HOPE}" in p, p
    # A value never reaches an address as it was typed, whatever it holds.
    db.reads.clear()
    odd = f"x&business_id=eq.{c3.GRACE}"
    assert csv.teams_of(church(db), odd) == [] and csv.team_step(church(db), odd)
    assert all(f"&business_id=eq.{c3.GRACE}" not in p for p in db.reads), "never another church's filter"
    assert any(f"x%26business_id%3Deq.{c3.GRACE}" in p for p in db.reads), "quoted, as typed"


def test_no_title_word_or_role_key_decides_anything_here():
    titles = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|directors?|executive|treasurers?|"
                        r"secretary|trustees?|reverend|apostles?|prophets?)\b", re.I)
    code = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", inspect.getsource(csv), flags=re.S))
    assert not ROLE_KEYS.search(code) and not titles.search(code), (ROLE_KEYS.search(code), titles.search(code))
    for fn in (cs.volunteer, cs.flagged, cs.answer, cs.withdraw_fact, tell.volunteer_why, tell._page_for,
               tell._sweep_church, ss.add_away, mps._vol, mps._vol_flash, mps._vol_chips, mps._vol_lines, mps._vol_why,
               mpd._vol_line, mpd._limits):
        src = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", inspect.getsource(fn), flags=re.S))
        assert not ROLE_KEYS.search(src) and not titles.search(src), fn.__name__


def test_every_word_a_member_reads_is_plain(db, shell):
    on_for(db, "n041")
    away(db, "n042")
    vol_ask(db, start=DEC20, end=DEC20)
    pages = [text(serving(db, "n041", b"done=vol_asked")), text(dates(db, "n040")[0]).replace("Pastor Nathan", "")]
    for words in pages + [mps.VOL_SENT, mps.VOL_ALONE, *mps.VOL_WHY.values(),
                          tell.volunteer_why({"flags": ["serving", "over_limit"], "starts_on": DEC20, "ends_on": DEC20})]:
        for rule in (UUID, OFFICE_WORDS, TITLE_WORDS, KEYS):
            assert not rule.search(words.replace("{to}", "N040 Member").replace("{why}", "").replace("{dept}", "Kids")), \
                (rule.search(words), words[:120])
