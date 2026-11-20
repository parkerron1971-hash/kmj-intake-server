"""My department: a department leader's week in the member app (church_week.
department_week and department_team, sunday_leading, member_portal_leading;
docs/CHURCH_SCHEDULE.md section 8.8). The pastor approved the mock and four
calls on 2026-11-20:
  1 it lives on the Sundays page they already know (/my/lead/sundays) as My
    department; the Lead tab gets no new entry; who sees it comes from the
    leaders map (each department's leader and its overseer); a team leader
    over no department keeps seeing their own team; a department leader who
    leads no team still reaches the Sundays page
  2 a department leader fills an open place on any team in their department
    through the same fair fill (sunday_leading), and that team's own leader
    is told
  3 hours and background checks stay in the office: none on the phone; an
    uncleared kids place reads "The office is handling this place"
  4 worship and production (ChurchSavvy's teams) are read only here

At New Hope (church_three: a made-up church of 500, every name in it made up),
on test_church_week's week of Nov 22 to 28 (read on Wednesday Nov 18), through
the real engine: church_week's own read, the leaders map, church_serving's
checks, sunday_planning's board and fill, sunday_leading's rules, member_push's
sender and the member app's routes. The map: Kids is led by Kara Bell, Youth by
Yusuf Grant, both overseen by Amara Stone; Worship is led by Wren Ellis and
overseen by Abel Ford. The Kids Check-in team's own leader is Gemma Holt; the
Parking Team (Felix Rowe's) hangs from no department.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_schedule_fake as fake  # noqa: E402
import church_three as c3  # noqa: E402
import church_week as cw  # noqa: E402
import member_portal_lead as mpl  # noqa: E402
import member_portal_leading as mplg  # noqa: E402
import sb_clients  # noqa: E402
import sunday_leading as sl  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from test_church_week import (BAND, CHECKIN, HOPE, KIDS, LOT, LOTS, NEXT_SUN, NURSERY, SUN, THU, VOCALS,  # noqa: E402,F401
                              assign, contact, db)

YOUTH = "7d000000-0000-4000-8000-0000000000d1"      # Youth Volunteers: the Volunteers', hangs from Youth by its name
ROOM = "7e000000-0000-4000-8000-0000000000d1"
MORE = {"n046": "Cora Finch", "n047": "Jude Marsh", "n049": "Nell Ashby"}     # made up, as every name here
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
KEYS = re.compile(r"\b[a-z]+_[a-z_]+\b")
TITLE_WORDS = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|overseers?|directors?|executive|"
                         r"treasurers?|secretary|owners?|trustees?|reverend|apostles?|prophets?)\b", re.I)
OFFICE_WORDS = re.compile(r"\b(login|logins|seat|seats|manager|admin|lane|lanes|duty|duties|who serves when)\b", re.I)
ROLE_KEYS = re.compile(r"\b(pastor|executive_pastor|associate_pastor|elders|deacons|ministers|youth_pastor|"
                       r"worship_leader|team_leader|director_of_operations|childrens_director)\b")
# Nothing of hours or checks, in any words, on the phone.
PRIVATE = re.compile(r"\b(hours?|minutes?|background|checks?(?!-in)|checked|cleared|kids yet|can't serve|on record)\b",
                     re.I)
OFFICE_LINE = "The office is handling this place"


@pytest.fixture
def hope(db, monkeypatch):
    """test_church_week's New Hope, plus: a Youth Volunteers team (the
    Volunteers'; hangs from Youth by its name; led by Cora Finch) with one
    place, Room helper, Jude Marsh on it Sunday (his check on record) and
    open Thursday; Nell Ashby on the Kids Check-in team, trained on the
    Nursery (Gemma Holt and Iris Crane too); member_push's real sender with
    phones faked, Serving notes switched on at New Hope; the person map and
    who heads a department kept fresh."""
    w = db.who[HOPE]
    for h, name in MORE.items():
        next(c for c in db.t["contacts"] if c["id"] == w[h])["name"] = name
    db.t["groups"].append({"id": YOUTH, "business_id": HOPE, "name": "Youth Volunteers", "kind": "team", "active": True})
    db.t["serve_teams"].append({"group_id": YOUTH, "business_id": HOPE, "call_time": None, "max_month": 4,
                                "owner": "volunteers", "swap_needs_ok": False, "families": True, "sort": 3})
    for h, role in (("n046", "leader"), ("n047", "member")):
        db.t["group_members"].append({"group_id": YOUTH, "business_id": HOPE, "contact_id": w[h], "role": role})
    db.t["group_members"].append({"group_id": KIDS, "business_id": HOPE, "contact_id": w["n049"], "role": "member"})
    db.t["serve_positions"].append({"id": ROOM, "business_id": HOPE, "group_id": YOUTH, "name": "Room helper",
                                    "needed": 1, "note": "", "sort": 0, "active": True,
                                    "created_at": "2026-10-01T00:00:00+00:00"})
    for pid, h in ((NURSERY, "n049"), (NURSERY, "n040"), (NURSERY, "n045"), (CHECKIN, "n049"), (ROOM, "n047"),
                   (LOTS, "n062")):
        db.t["serve_trained"].append({"business_id": HOPE, "position_id": pid, "contact_id": w[h], "level": "trained"})
    assign(db, SUN, ROOM, 1, w["n047"], "yes")
    contact(db, "n047")["metadata"] = {"serving": {"check_on": "2026-05-01"}}
    contact(db, "n049")["metadata"] = {"serving": {"check_on": "2026-05-01"}}
    # Notes: the real sender, phones faked; New Hope has Serving notes on.
    import church_threads
    import push_notifications
    monkeypatch.setenv("CHURCH_THREADS", "on")
    monkeypatch.delenv("MEMBER_QUIET_HOURS", raising=False)
    for t in ("church_thread_notes", "church_thread_reads", "member_push_subscriptions", "member_push_sends",
              "member_push_prefs", "member_push_held"):
        db.t[t] = []
    biz = next(b for b in db.t["businesses"] if b["id"] == HOPE)
    biz["settings"] = {**biz["settings"], "member_portal": {"notifications": {"serving": True}}}
    monkeypatch.setattr(church_threads, "_READY", {"at": 0.0, "ok": None})
    monkeypatch.setattr(push_notifications, "push_enabled", lambda: True)
    db.rang = []

    def send_one(sub, payload, table="push_subscriptions"):
        db.rang.append({"to": sub.get("contact_id"), **payload})
        return True
    monkeypatch.setattr(push_notifications, "_send_one", send_one)
    real_post = sb_clients.sb_post_as_service

    def post(path, body, prefer=None, **k):
        # member_push_sends is unique on (business_id, kind, ref_id): a note is claimed once.
        if path.startswith("/member_push_sends") and "ignore-duplicates" in (prefer or "") and any(
                all(r.get(x) == body.get(x) for x in ("business_id", "kind", "ref_id")) for r in db.t["member_push_sends"]):
            return []
        return real_post(path, body, prefer, **k)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    for h in ("n040", "kara", "amara", "n046"):
        phone(db, h)
    monkeypatch.setattr(cw, "_HEADS", {})
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a, **k: True)
    return db


def phone(db, handle):
    """This person has the church's app on a phone."""
    db.t["member_push_subscriptions"].append({
        "id": f"7c800000-0000-4000-8000-{len(db.t['member_push_subscriptions']):012d}", "business_id": HOPE,
        "contact_id": db.who[HOPE][handle], "endpoint": f"https://push.example/{handle}", "subscription": {}})


@pytest.fixture
def shell(monkeypatch):
    """member_portal's shell, keeping just the body, so the tests read what
    the page itself writes."""
    import member_portal
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **kw: body)


def member_row(db):
    """The church as the member app hands it over: no owner on it."""
    b = c3.church(db, HOPE)
    return {k: b[k] for k in ("id", "name", "type", "settings")}


def me(db, handle):
    cid = db.who[HOPE][handle]
    return {"id": cid, "name": next(x["name"] for x in db.t["contacts"] if x["id"] == cid), "email": ""}


def mine(db, handle, which="this"):
    """My department as this person reads it. Read on Wednesday Nov 18,
    this week is the coming Sunday's: Nov 22 to 28 (test_church_week's)."""
    return cw.department_week(member_row(db), db.who[HOPE][handle], which)


def page(db, handle, **q):
    """The Sundays page, through the Lead tab, as this person: (html, status)."""
    q = {k: v for k, v in q.items() if v is not None}
    return asyncio.run(mpl.serve(SimpleNamespace(query_params=q), member_row(db), {}, me(db, handle), "/my/lead/sundays"))


def text(html):
    """What's on the screen: no tags, no form addresses, no hidden values."""
    out = re.sub(r"<[^>]+>", " ", re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S))
    return re.sub(r"\s+", " ", out).replace("&#x27;", "'")


def rows_of(d, dept, team, words):
    t = next(t for x in d["departments"] if x["name"] == dept for t in x["teams"] if t["name"] == team)
    return next(s["rows"] for s in t["services"] if s["words"] == words)


@pytest.fixture
def app(hope, monkeypatch):
    """The Sundays page's own routes, signed in as `app.state["me"]` at New Hope."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import member_portal_church as mpc
    a = FastAPI()
    a.include_router(mplg.router)
    state = {"me": None, "unavailable": False}

    async def signed_in(request):
        if state["unavailable"]:
            return {"business": member_row(hope), "site": {}}, None, state["unavailable"]
        return {"business": member_row(hope), "site": {}}, state["me"], False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    c = TestClient(a)
    c.state, c.db = state, hope
    return c


def as_(app, handle):
    app.state.update(me=me(app.db, handle), unavailable=False)


def post(app, path, **form):
    r = app.post(path, data=form, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r.headers["location"]


def asks(db):
    return [r for r in db.t["serve_assignments"] if r["business_id"] == HOPE]


def told(db):
    """What landed in people's conversation with the church: (who, title,
    body, where it opens)."""
    return [(n["contact_id"], n["title"], n["body"], n["url"]) for n in db.t["church_thread_notes"]]


# ─── 1. Who sees it: the leaders map ──────────────────────────────────

def test_the_kids_leader_sees_kids_only(hope, shell):
    d = mine(hope, "kara")
    assert d["week"] == {"from": "2026-11-22", "to": "2026-11-28", "words": "Nov 22 to 28", "which": "this"}
    assert d["counts"] == {"on": 2, "open": 4, "away": 2}
    assert [(x["name"], x["led_by"]) for x in d["departments"]] == [("Kids", None)], "her own: no 'led by' herself"
    kids = d["departments"][0]
    assert [t["name"] for t in kids["teams"]] == ["Kids Check-in"]
    assert [s["words"] for s in kids["teams"][0]["services"]] == ["Sunday 10:30 AM", "Thursday 7 PM · Outreach night"]
    assert [(r["place"], r["who"], r["words"]) for r in rows_of(d, "Kids", "Kids Check-in", "Sunday 10:30 AM")] == [
        ("Nursery 1", "Lila Penn", OFFICE_LINE), ("Nursery 2", "Dara Quinn", "Away"),
        ("Check-in", "Toby Wells", "Asked, no answer yet")]
    assert kids["away"] == [{"name": "Dara Quinn", "days": "Nov 21 to 23"}, {"name": "Rory Vance", "days": "Sunday, Nov 22"}]
    assert [(x["title"], x["details"]) for x in d["look"]] == [
        ("Kids is short one on Sunday: Nursery.",
         ["Dara Quinn is away. Three people on the Kids Check-in team are free that morning."]),
        ("Kids: Toby Wells hasn't answered for Sunday.", ["Toby was asked on Monday."]),
        ("Kids is short three on Thursday: Nursery (2), Check-in.", [])]
    html, status = page(hope, "kara")
    assert status == 200
    shown = text(html)
    for words in ("My department", "Nov 22 to 28", "This week", "Next week", "On the schedule", "Open places",
                  "Look at first", "Kids Check-in", "Nursery 2", "Dara Quinn · Away", "Find someone",
                  "Away", "Rory Vance Sunday, Nov 22"):
        assert words in shown, words
    for other in ("Youth", "Worship", "Parking", "Room helper", "Keys", "Felix"):
        assert other not in shown, other


def test_an_overseer_of_two_departments_sees_both_one_after_the_other(hope, shell):
    d = mine(hope, "amara")
    assert [(x["name"], x["led_by"]) for x in d["departments"]] == [("Youth", "Yusuf Grant"), ("Kids", "Kara Bell")]
    assert d["counts"] == {"on": 3, "open": 5, "away": 2}, "the counts are across both"
    assert [(r["place"], r["who"], r["words"]) for r in rows_of(d, "Youth", "Youth Volunteers", "Sunday 10:30 AM")] == [
        ("Room helper", "Jude Marsh", "On")]
    html, _ = page(hope, "amara")
    shown = text(html)
    assert html.index("<h2>Youth</h2>") < html.index("Youth Volunteers") < html.index("<h2>Kids</h2>")
    for words in ("Youth and Kids", "Led by Yusuf Grant", "Led by Kara Bell", "Room helper"):
        assert words in shown, words
    assert "Worship" not in shown and "Parking" not in shown


def test_a_team_leader_over_no_department_sees_just_their_own_team(hope, shell):
    for handle, team in (("n060", "Parking Team"), ("n040", "Kids Check-in")):
        assert mine(hope, handle) is None and cw.entry(member_row(hope), hope.who[HOPE][handle]) is False
        html, status = page(hope, handle)
        assert status == 200
        shown = text(html)
        assert "Your team's Sundays" in shown and team in shown
        assert "My department" not in shown and "Look at first" not in shown


def test_a_team_leader_over_no_department_never_waits_on_a_department_read(hope, shell, monkeypatch):
    """Gemma leads Kids Check-in and heads nothing: My department's read is
    never asked for; once who heads a department is kept (any page in that
    minute), her page makes exactly the reads it made before this change
    (CHURCH_WEEK off); and with the leaders map's departments failing to
    read, her team's page still opens."""
    def never(*a, **k):
        raise AssertionError("a department read for someone who heads none")
    monkeypatch.setattr(cw, "department_week", never)
    monkeypatch.setenv("CHURCH_WEEK", "off")
    page(hope, "n040")                                                  # what other pages keep, kept
    hope.reads.clear()
    before = page(hope, "n040")
    reads_before = list(hope.reads)
    monkeypatch.setenv("CHURCH_WEEK", "on")
    cw.entry(member_row(hope), hope.who[HOPE]["kara"])                  # the minute's answer, kept
    hope.reads.clear()
    assert page(hope, "n040") == before and hope.reads == reads_before, "no extra read"
    cw._HEADS.clear()
    hope.fail = {"get": "/church_departments"}
    html, status = page(hope, "n040")
    hope.fail = {}
    assert status == 200 and "Your team's Sundays" in text(html) and "Kids Check-in" in text(html)
    # Someone with no team of their own, when who heads a department can't be read: plain words, never a 500.
    cw._HEADS.clear()
    hope.fail = {"get": "/church_departments"}
    html, status = page(hope, "kara")
    hope.fail = {}
    assert status == 503 and mplg.DEPT_UNREAD in html


def test_someone_else_gets_no_my_department(hope, shell):
    for handle in ("n041", "elena", "nathan"):       # a volunteer, an elder, the owner's own person: none heads one
        assert mine(hope, handle) is None
        assert cw.entry(member_row(hope), hope.who[HOPE][handle]) is False
        html, _ = page(hope, handle)
        assert "You don't lead a Sunday team right now" in text(html) and "My department" not in html
    assert mine(hope, "yusuf")["departments"][0]["name"] == "Youth"


def test_the_lead_tab_gets_no_new_entry_and_a_head_who_leads_no_team_reaches_sundays(hope, shell):
    """Kara leads no team: the switcher offers Sundays (the Lead tab's own
    entry), never a new one. Someone who heads a department and holds no
    role, leads no group and is on no schedule still gets the tab."""
    biz = member_row(hope)
    assert sl.led_teams(HOPE, hope.who[HOPE]["kara"]) == []

    async def switcher(handle):
        await mpl._context(SimpleNamespace(query_params={}), biz, me(hope, handle))
        return mpl.SUNDAYS.get(), mpl._seg("people", True, False, 0, 0)
    sundays, seg = asyncio.run(switcher("kara"))
    assert sundays is True
    assert 'href="/my/lead/sundays"' in seg and "department" not in seg.lower(), "Sundays, the entry it has"
    assert asyncio.run(switcher("n041"))[0] is False
    # Quinn Abbott holds no role and leads nothing: made Care's leader, the tab is his.
    import member_portal
    care = next(x for x in hope.t["church_departments"] if x["business_id"] == HOPE and x["name"] == "Care")
    quinn = hope.who[HOPE]["n100"]
    got, _known = asyncio.run(member_portal._read_leads(HOPE, quinn, biz, me(hope, "n100")))
    assert got is False
    care["leader_contact_id"] = quinn
    cw._HEADS.clear()
    got, _known = asyncio.run(member_portal._read_leads(HOPE, quinn, biz, me(hope, "n100")))
    assert got is True
    # Care has no Sunday team: My department says so in plain words, never the office page's name.
    html, status = page(hope, "n100")
    assert status == 200 and "No Sunday team is part of Care yet" in text(html)
    assert [x["title"] for x in mine(hope, "n100")["look"]] == ["None of your department's teams is on the schedule yet."]
    assert not OFFICE_WORDS.search(text(html))


def test_who_heads_a_department_is_kept_a_minute_and_costs_one_read(hope):
    biz = member_row(hope)
    hope.reads.clear()
    assert cw.entry(biz, hope.who[HOPE]["kara"]) is True
    first = [p for p in hope.reads if p.startswith("/church_departments")]
    assert len(first) == 1 and "status=eq.active" in first[0] and f"business_id=eq.{HOPE}" in first[0]
    hope.reads.clear()
    for h in ("amara", "abel", "n041", "n060"):
        cw.entry(biz, hope.who[HOPE][h])
    assert not [p for p in hope.reads if p.startswith("/church_departments")], "kept: no read on a page view"


# ─── 2. Find someone: the same fair fill, and the team's leader is told ─

def test_find_someone_on_a_team_in_their_department_goes_through_sunday_leading(app, shell):
    db = app.db
    w = db.who[HOPE]
    d = mine(db, "kara")
    sunday = rows_of(d, "Kids", "Kids Check-in", "Sunday 10:30 AM")
    assert [r["find"] for r in sunday] == [None, None, None], "on, away (a yes stays until the office takes it off), asked"
    thursday = rows_of(d, "Kids", "Kids Check-in", "Thursday 7 PM · Outreach night")
    assert [(r["place"], r["words"]) for r in thursday] == [("Nursery 1", "Open"), ("Nursery 2", "Open"),
                                                            ("Check-in", "Open")]
    assert thursday[0]["find"] == {"team": KIDS, "day": THU, "spot": f"{NURSERY}:1"}
    html, _ = page(db, "kara")
    assert f'href="/my/lead/sundays?team={KIDS}&amp;day={THU}&amp;spot={NURSERY}%3A1#spot"' in html
    # The link opens that team's day, with who could take it, most rested first.
    html, status = page(db, "kara", **thursday[0]["find"])
    shown = text(html)
    assert status == 200
    assert "This team's Sundays" in shown and "Whoever leads it is told" in shown and "Who could take Nursery" in shown
    assert 'class="sv-chip" href="/my/lead/sundays">My department</a>' in html
    cands = sl.candidates(member_row(db), w["kara"], THU, NURSERY)
    assert cands == sl.candidates(member_row(db), w["n040"], THU, NURSERY), "the team leader's own list, the same"
    assert [c["name"] for c in cands if c["ok"] and c["trained"] == "trained"] == ["Gemma Holt", "Iris Crane", "Nell Ashby"]
    # Ask through the page's own route: it's on the schedule as Kara's ask.
    as_(app, "kara")
    went = post(app, "/my/lead/sundays/ask", team=KIDS, day=THU, place=NURSERY, slot="1", person=w["n049"])
    assert went == f"/my/lead/sundays?team={KIDS}&day={THU}&done=asked"
    got = next(r for r in asks(db) if r["service_id"] == THU and r["position_id"] == NURSERY and r["slot"] == 1)
    assert (got["contact_id"], got["status"], got["asked_by"]) == (w["n049"], "asked", "Kara Bell")
    # Gemma, the team's own leader, is told once the write has landed; Kara isn't.
    assert db.rang == [] and len(db.later) == 1
    fake.later(db)
    assert told(db) == [(w["n040"], "Nell Ashby was asked for Nursery",
                         "Kara Bell asked for Kids Check-in, Thursday, Nov 26. You'll see it on your team's Sundays.",
                         f"/my/lead/sundays?team={KIDS}&day={THU}")]
    assert [(n["to"], n["title"], n["body"]) for n in db.rang] == [
        (w["n040"], "New Hope Church", "Nell Ashby was asked for Nursery — Kara Bell asked for Kids Check-in, "
                                       "Thursday, Nov 26. You'll see it on your team's Sundays.")], "reads like a text"
    assert [r["ref_id"][:9] for r in db.t["member_push_sends"]] == ["dept-ask-"]
    # Told once: the same note again claims nothing.
    sl.tell(member_row(db), me(db, "kara"), {"group_id": KIDS, "name": "Kids Check-in"}, "ask",
            {"service_id": THU, "place": "Nursery", "id": got["id"], "person_name": "Nell Ashby",
             "at": got["asked_at"]})
    assert len(db.rang) == 1
    # An away place is not Kara's to fill: Dara said yes, and a yes stays until the office takes her off.
    went = post(app, "/my/lead/sundays/ask", team=KIDS, day=SUN, place=NURSERY, slot="2", person=w["n049"])
    assert "err=said" in went and "Take+them+off+first" in went


def test_offer_and_fill_tell_the_teams_leader_and_a_take_back_tells_nobody(app, shell):
    db = app.db
    as_(app, "kara")
    post(app, "/my/lead/sundays/offer", team=KIDS, day=THU, place=CHECKIN, slot="1")
    went = post(app, "/my/lead/sundays/fill", team=KIDS)
    assert "filled=" in went and "ids=" in went
    fake.later(db)
    w = db.who[HOPE]
    notes = told(db)
    assert [(n[0], n[1], n[2]) for n in notes[:1]] == [
        (w["n040"], "Check-in was offered to Kids Check-in",
         "Kara Bell offered Check-in, Thursday, Nov 26, to the whole team. The first yes takes it.")]
    n = int(re.search(r"filled=(\d+)", went).group(1))
    assert n > 0 and [(x[0], x[1], x[2], x[3]) for x in notes[1:]] == [
        (w["n040"], f"Kids Check-in: {n} place{'' if n == 1 else 's'} asked for",
         "Kara Bell asked people for the next five Sundays. You'll see who on your team's Sundays.",
         f"/my/lead/sundays?team={KIDS}")]
    assert len(db.rang) == 2
    # Taking one back works (the same rule) and tells nobody.
    offered = next(r for r in asks(db) if r["status"] == "offered")
    went = post(app, "/my/lead/sundays/takeback", team=KIDS, day=THU, id=offered["id"])
    assert went.endswith("done=back") and not any(r["id"] == offered["id"] for r in asks(db))
    assert db.later == [] and len(db.rang) == 2


def test_no_note_reason_or_waiting_ask_reaches_a_department_leader(hope, shell):
    """Rory said no to Thursday's Check-in with a note; Dara is away with a
    note; Iris asked to be away and still waits. My department shows none of
    it, and on the team's own page a department leader reads "Rory can't"
    without his note (the team's own leader still reads it, as before)."""
    from test_church_week import SECRETS
    for handle in ("kara", "amara"):
        html = page(hope, handle)[0] + json.dumps(mine(hope, handle))
        assert not [s for s in SECRETS if s in html]
        assert "Iris Crane" not in html.split("Away</h3>")[-1], "a waiting ask is not away"
        team = text(page(hope, handle, team=KIDS, day=THU)[0])
        assert "Rory can't" in team and "SECRET" not in team
    assert "Rory can't · SECRET-NO-NOTE" in text(page(hope, "n040", team=KIDS, day=THU)[0])


def test_a_team_leader_doing_their_own_team_tells_nobody(app, shell):
    """Gemma leads Kids Check-in: nothing new for her, and nobody is told."""
    db = app.db
    as_(app, "n040")
    post(app, "/my/lead/sundays/ask", team=KIDS, day=THU, place=NURSERY, slot="1", person=db.who[HOPE]["n049"])
    assert db.later == []


def test_in_quiet_hours_the_note_waits_for_the_morning(app, shell, monkeypatch):
    import member_push
    monkeypatch.setattr(member_push, "quiet_hour", lambda business, now=None: True)
    db = app.db
    as_(app, "kara")
    post(app, "/my/lead/sundays/ask", team=KIDS, day=THU, place=NURSERY, slot="1", person=db.who[HOPE]["n049"])
    fake.later(db)
    assert db.rang == [], "no phone rang at night"
    assert [(h["contact_id"], h["kind"], h["body"][:32]) for h in db.t["member_push_held"]] == [
        (db.who[HOPE]["n040"], "serving", "Nell Ashby was asked for Nursery")], "it waits for the morning"
    assert [x[1] for x in told(db)] == ["Nell Ashby was asked for Nursery"], "the conversation has it, quietly"
    # Only this note waits: any other note of its kind goes as it always did.
    assert member_push.send(member_row(db), "serving", title="x", contact_ids=[db.who[HOPE]["n040"]]) == 1


def test_find_someone_on_a_team_outside_their_department_is_refused(app, shell):
    db = app.db
    w = db.who[HOPE]
    before = [dict(r) for r in asks(db)]
    for handle, team, place in (("kara", LOT, LOTS), ("kara", YOUTH, ROOM), ("amara", LOT, LOTS)):
        as_(app, handle)
        went = post(app, "/my/lead/sundays/ask", team=team, day=THU, place=place, slot="1", person=w["n062"])
        assert "err=said" in went and "lead+that+team" in went, (handle, went)
        assert "err=said" in post(app, "/my/lead/sundays/fill", team=team)
        assert "err=said" in post(app, "/my/lead/sundays/offer", team=team, day=THU, place=place, slot="1")
        with pytest.raises(HTTPException) as e:
            sl.team_view(member_row(db), w[handle], team)
        assert e.value.status_code == 404
    assert [dict(r) for r in asks(db)] == before and db.later == []
    # Asked for by address, another team's Sundays page is My department.
    html, _ = page(db, "kara", team=LOT)
    assert "My department" in text(html) and "Parking" not in text(html)


def test_take_back_unfill_and_who_could_take_it_outside_their_department_are_refused(app, shell):
    """Hazel Dunn's ask on the Parking Team's Lot is not Kara's to take back,
    its asks not hers to take back as a fill, and who could take the Lot is
    not hers to read."""
    db = app.db
    w = db.who[HOPE]
    hazel = next(r for r in asks(db) if r["position_id"] == LOTS and r["contact_id"] == w["n061"])
    before = [dict(r) for r in asks(db)]
    for fn in (lambda: sl.take_back(member_row(db), me(db, "kara"), hazel["id"]),
               lambda: sl.unfill(member_row(db), me(db, "kara"), LOT, [hazel["id"]]),
               lambda: sl.candidates(member_row(db), w["kara"], SUN, LOTS)):
        with pytest.raises(HTTPException) as e:
            fn()
        assert e.value.status_code == 404
    as_(app, "kara")
    assert "err=said" in post(app, "/my/lead/sundays/takeback", team=LOT, day=SUN, id=hazel["id"])
    assert "err=said" in post(app, "/my/lead/sundays/unfill", team=LOT, ids=hazel["id"])
    html, _ = page(db, "kara", team=LOT, day=SUN, spot=f"{LOTS}:2")
    assert "Who could take" not in html and "Hazel" not in text(html)
    assert [dict(r) for r in asks(db)] == before


def test_a_team_from_another_church_is_refused(app, shell):
    """A team at Grace with the very name of Kids' Serve option: New Hope's
    department reaches none of it."""
    db = app.db
    grace_team, grace_place = "7d000000-0000-4000-8000-0000000000e1", "7e000000-0000-4000-8000-0000000000e1"
    db.t["groups"].append({"id": grace_team, "business_id": c3.GRACE, "name": "Kids Check-in", "kind": "team",
                           "active": True})
    db.t["serve_teams"].append({"group_id": grace_team, "business_id": c3.GRACE, "call_time": None, "max_month": 4,
                                "owner": "volunteers", "swap_needs_ok": False, "families": True, "sort": 0})
    db.t["serve_positions"].append({"id": grace_place, "business_id": c3.GRACE, "group_id": grace_team,
                                    "name": "Nursery", "needed": 1, "note": "", "sort": 0, "active": True,
                                    "created_at": "2026-10-01T00:00:00+00:00"})
    w = db.who[HOPE]
    assert cw.department_team(member_row(db), w["kara"], grace_team) is None
    before = [dict(r) for r in db.t["serve_assignments"]]
    as_(app, "kara")
    assert "err=said" in post(app, "/my/lead/sundays/ask", team=grace_team, day=THU, place=grace_place, slot="1",
                              person=w["n049"])
    assert "err=said" in post(app, "/my/lead/sundays/fill", team=grace_team)
    assert [dict(r) for r in db.t["serve_assignments"]] == before and db.later == []


def test_a_former_head_is_refused_a_write_while_the_minutes_answer_is_warm(app, shell):
    """Kara is moved off Kids: the Sundays entry may lag a minute (kept),
    but every write reads the map fresh and is refused, and My department is
    gone at once."""
    db = app.db
    w = db.who[HOPE]
    assert cw.entry(member_row(db), w["kara"]) is True                  # kept for the minute
    kids = next(x for x in db.t["church_departments"] if x["business_id"] == HOPE and x["name"] == "Kids")
    kids["leader_contact_id"] = w["n100"]
    assert cw.entry(member_row(db), w["kara"]) is True, "the switcher's answer lags, as Dates' does"
    before = [dict(r) for r in asks(db)]
    as_(app, "kara")
    went = post(app, "/my/lead/sundays/ask", team=KIDS, day=THU, place=NURSERY, slot="1", person=w["n049"])
    assert "err=said" in went and "lead+that+team" in went
    assert [dict(r) for r in asks(db)] == before and db.later == []
    assert mine(db, "kara") is None
    assert "You don't lead a Sunday team right now" in text(page(db, "kara")[0])


def test_a_draft_department_gives_no_access(app, shell):
    db = app.db
    w = db.who[HOPE]
    kids = next(x for x in db.t["church_departments"] if x["business_id"] == HOPE and x["name"] == "Kids")
    kids["status"] = "draft"
    cw._HEADS.clear()
    assert cw.entry(member_row(db), w["kara"]) is False and mine(db, "kara") is None
    assert cw.department_team(member_row(db), w["kara"], KIDS) is None
    as_(app, "kara")
    before = [dict(r) for r in asks(db)]
    went = post(app, "/my/lead/sundays/ask", team=KIDS, day=THU, place=NURSERY, slot="1", person=w["n049"])
    assert "err=said" in went and [dict(r) for r in asks(db)] == before
    assert [x["name"] for x in mine(db, "amara")["departments"]] == ["Youth"], "her other one stays"


def test_whoever_leads_it_is_told_is_said_only_when_it_is_so(app, shell):
    """The church sends serving notes and the team has a leader besides
    them: the page says so. Serving notes off: it doesn't, and nothing is
    sent. A team with no leader of its own: it doesn't."""
    db = app.db
    told = "Whoever leads it is told"
    assert told in text(page(db, "kara", team=KIDS)[0])
    biz = next(b for b in db.t["businesses"] if b["id"] == HOPE)
    biz["settings"] = {**biz["settings"], "member_portal": {"notifications": {"serving": False}}}
    shown = text(page(db, "kara", team=KIDS)[0])
    assert told not in shown and "It's one of your department's teams." in shown
    as_(app, "kara")
    post(app, "/my/lead/sundays/ask", team=KIDS, day=THU, place=NURSERY, slot="1", person=db.who[HOPE]["n049"])
    fake.later(db)
    assert db.rang == [] and db.t["church_thread_notes"] == [], "the church keeps serving notes off: none goes"
    biz["settings"] = {**biz["settings"], "member_portal": {"notifications": {"serving": True}}}
    for m in db.t["group_members"]:
        if m["group_id"] == KIDS and m["role"] == "leader":
            m["role"] = "member"
    assert told not in text(page(db, "kara", team=KIDS)[0]), "nobody leads it but her department"


def test_a_place_the_office_is_handling_makes_no_hasnt_answered_line(hope, shell):
    """Toby was asked for Check-in and has no check on record: his place
    reads "The office is handling this place", and Look at first says
    nothing of him (the office's own week still has both lines)."""
    contact(hope, "n043")["metadata"] = {}
    d = mine(hope, "kara")
    toby = rows_of(d, "Kids", "Kids Check-in", "Sunday 10:30 AM")[2]
    assert (toby["who"], toby["words"]) == ("Toby Wells", OFFICE_LINE)
    assert not [x for x in d["look"] if "Toby" in x["title"] or any("Toby" in t for t in x["details"])]
    assert "Toby Wells hasn't answered" not in text(page(hope, "kara")[0])
    office = cw.week({"biz": c3.church(hope, HOPE), "role": "owner", "change": frozenset(), "hours": False,
                      "checks": True}, "2026-11-22")
    assert {"Kids: Toby Wells hasn't answered for Sunday.", "Kids: Toby Wells can't serve with kids yet."} <= {
        x["title"] for x in office["look"]}


def test_a_team_two_of_their_departments_name_says_where_it_is(hope, shell):
    """Youth names the Kids Check-in team too (Youth comes first in the
    map): Amara sees it under Youth, and Kids says where it is, never that
    it has no team. Kara, who leads Kids alone, sees it under Kids."""
    youth = next(x for x in hope.t["church_departments"] if x["business_id"] == HOPE and x["name"] == "Youth")
    hope.t["church_department_units"].append({"id": "7d900000-0000-4000-8000-000000000001", "business_id": HOPE,
                                              "department_id": youth["id"], "kind": "serve_option", "group_id": None,
                                              "role_id": None, "board_id": None, "worship_ministry_id": None,
                                              "label": "Kids Check-in"})
    d = mine(hope, "amara")
    assert [(x["name"], [t["name"] for t in x["teams"]], x["elsewhere"]) for x in d["departments"]] == [
        ("Youth", ["Kids Check-in", "Youth Volunteers"], []),           # Who serves when's team order
        ("Kids", [], [{"team": "Kids Check-in", "under": "Youth"}])]
    assert d["counts"] == {"on": 3, "open": 5, "away": 2}, "nothing counted twice"
    shown = text(page(hope, "amara")[0])
    assert "Kids Check-in is shown under Youth above." in shown and "No Sunday team is part of Kids" not in shown
    assert [t["name"] for t in mine(hope, "kara")["departments"][0]["teams"]] == ["Kids Check-in"]


# ─── 3. Hours and checks stay in the office ───────────────────────────

def test_no_hours_no_check_state_and_the_office_line_for_an_uncleared_kids_place(hope, shell):
    for handle in ("kara", "amara"):
        d = mine(hope, handle)
        blob = json.dumps(d)
        assert "minutes" not in blob and "hours" not in blob and "cant_serve" not in blob and "checks" not in blob
        html, _ = page(hope, handle)
        shown = text(html)
        assert OFFICE_LINE in shown
        assert not PRIVATE.search(shown), PRIVATE.search(shown)
    lila = rows_of(mine(hope, "kara"), "Kids", "Kids Check-in", "Sunday 10:30 AM")[0]
    assert (lila["state"], lila["words"], lila["find"]) == ("office", OFFICE_LINE, None)
    before = mine(hope, "kara")
    # With her check on record she is On, and nothing else on the page changes.
    contact(hope, "n041")["metadata"] = {"serving": {"check_on": "2026-03-01"}}
    after = mine(hope, "kara")
    assert rows_of(after, "Kids", "Kids Check-in", "Sunday 10:30 AM")[0]["words"] == "On"
    lila_row = lambda x: rows_of(x, "Kids", "Kids Check-in", "Sunday 10:30 AM")[0]  # noqa: E731
    lila_row(before).update(state="on", words="On")
    assert before == after, "the office's line is the only difference"


def test_with_serving_switched_off_nobody_is_said_to_be_with_the_office(hope, monkeypatch):
    monkeypatch.setenv("CHURCH_SERVING", "off")
    hope.reads.clear()
    lila = rows_of(mine(hope, "kara"), "Kids", "Kids Check-in", "Sunday 10:30 AM")[0]
    assert lila["words"] == "On"
    assert not [p for p in hope.reads if p.startswith(("/space_leaders", "/church_area_places"))], "no check read"


# ─── 4. Worship and production: read only ─────────────────────────────

def test_churchsavvys_teams_are_read_only(app, shell):
    db = app.db
    for handle in ("abel", "wren"):
        d = mine(db, handle)
        assert [x["name"] for x in d["departments"]] == ["Worship"]
        team = d["departments"][0]["teams"][0]
        assert (team["name"], team["churchsavvy"]) == ("Worship Team", True)
        rows = rows_of(d, "Worship", "Worship Team", "Sunday 10:30 AM")
        assert [(r["place"], r["who"], r["words"], r["find"]) for r in rows] == [
            ("Keys", "Joel Pratt", "On", None), ("Vocals 1", "Nora Pike", "On", None), ("Vocals 2", "Open place", "Open", None)]
        assert rows[2]["note"] == "The worship team fills this in ChurchSavvy."
        assert all(x["find"] is None for x in d["look"])
        html, _ = page(db, handle)
        shown = text(html)
        assert "Scheduled in ChurchSavvy" in shown and "Find someone" not in shown and "Joel Pratt · On" in shown
        assert cw.department_team(member_row(db), db.who[HOPE][handle], BAND) is None
    as_(app, "abel")
    before = [dict(r) for r in asks(db)]
    went = post(app, "/my/lead/sundays/ask", team=BAND, day=SUN, place=VOCALS, slot="2", person=db.who[HOPE]["n052"])
    assert "err=said" in went and [dict(r) for r in asks(db)] == before


# ─── The switch, the preview, another site ────────────────────────────

def test_the_switch(app, shell, monkeypatch):
    db = app.db
    w = db.who[HOPE]
    biz = member_row(db)
    assert mine(db, "kara") is not None
    for how in ("off", "maybe"):
        monkeypatch.setenv("CHURCH_WEEK", how)
        cw._HEADS.clear()
        assert mine(db, "kara") is None and cw.entry(biz, w["kara"]) is False
        assert cw.department_team(biz, w["kara"], KIDS) is None
        assert "You don't lead a Sunday team right now" in text(page(db, "kara")[0])
        as_(app, "kara")
        before = [dict(r) for r in asks(db)]
        went = post(app, "/my/lead/sundays/ask", team=KIDS, day=SUN, place=NURSERY, slot="2", person=w["n049"])
        assert "err=said" in went and [dict(r) for r in asks(db)] == before
    # Unset is owner: the platform owner's own church only (New Hope isn't).
    monkeypatch.delenv("CHURCH_WEEK")
    assert cw.mode() == "owner" and mine(db, "kara") is None
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", c3.OWNER_EMAIL[c3.NH_OWNER])
    import member_asks
    monkeypatch.setattr(member_asks, "_OWNER_CACHE", {})
    assert mine(db, "kara")["departments"][0]["name"] == "Kids"
    # Who serves when off: nothing here either.
    monkeypatch.setenv("SUNDAY_PLANNING", "off")
    cw._HEADS.clear()
    assert mine(db, "kara") is None and cw.entry(biz, w["kara"]) is False
    # The leaders map closed for the church: no department, no entry.
    monkeypatch.setenv("SUNDAY_PLANNING", "on")
    monkeypatch.setenv("CHURCH_MAP", "off")
    cw._HEADS.clear()
    assert mine(db, "kara") is None and cw.entry(biz, w["kara"]) is False


def test_the_owners_preview_never_writes(app):
    db = app.db
    before = [dict(r) for r in asks(db)]
    as_(app, "kara")
    app.state["unavailable"] = "preview"
    for path, form in (("/my/lead/sundays/ask", {"team": KIDS, "day": SUN, "place": NURSERY, "slot": "2",
                                                  "person": db.who[HOPE]["n049"]}),
                       ("/my/lead/sundays/offer", {"team": KIDS, "day": THU, "place": CHECKIN, "slot": "1"}),
                       ("/my/lead/sundays/fill", {"team": KIDS})):
        assert "err=preview" in post(app, path, **form)
    assert [dict(r) for r in asks(db)] == before and db.later == [] and db.rang == []


def test_a_cross_site_post_is_refused(hope, monkeypatch):
    """The routes take member_portal_church._signed_in's session, whose
    _church_or_404 refuses another site's POST and reads Origin: null by the
    browser's own Sec-Fetch-Site."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import member_portal
    import public_site
    a = FastAPI()
    a.include_router(mplg.router)
    c = TestClient(a, base_url="https://new-hope.example")
    monkeypatch.setattr(public_site, "public_host", lambda request: "new-hope.example")
    monkeypatch.setattr(member_portal, "_church_for_request", lambda request: {"business": member_row(hope), "site": {}})
    monkeypatch.setattr(member_portal, "portal_active", lambda b: True)
    monkeypatch.setattr(member_portal, "_session_for", lambda request, ch: {"me": me(hope, "kara")})
    form = {"team": KIDS, "day": THU, "place": NURSERY, "slot": "1", "person": hope.who[HOPE]["n049"]}
    before = [dict(r) for r in asks(hope)]
    for headers in ({"Origin": "https://evil.example"}, {"Origin": "null", "Sec-Fetch-Site": "cross-site"}):
        r = c.post("/my/lead/sundays/ask", data=form, headers=headers, follow_redirects=False)
        assert r.status_code == 403
    assert [dict(r) for r in asks(hope)] == before and hope.later == []
    r = c.post("/my/lead/sundays/ask", data=form, follow_redirects=False,
               headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 303 and r.headers["location"].endswith("done=asked")
    assert len(asks(hope)) == len(before) + 1


# ─── Bounded, plain, and never a 500 ──────────────────────────────────

def test_this_week_is_the_coming_sundays_and_next_week_the_one_after(hope, shell, monkeypatch):
    """As the office's week: read on Wednesday Nov 18, This week is the
    coming Sunday's (Nov 22 to 28), Next week the one after. On that Sunday
    afternoon This week is still Nov 22 to 28, its morning passed (no Find
    someone there). Nothing else is offered."""
    html, _ = page(hope, "kara")
    assert "Nov 22 to 28" in text(html) and '<a href="/my/lead/sundays" aria-current="page">This week</a>' in html
    d = mine(hope, "kara", "next")
    assert d["week"] == {"from": "2026-11-29", "to": "2026-12-05", "words": "Nov 29 to Dec 5", "which": "next"}
    assert [s["words"] for s in d["departments"][0]["teams"][0]["services"]] == ["Sunday 10:30 AM"]
    assert d["counts"] == {"on": 0, "open": 3, "away": 0}
    html, _ = page(hope, "kara", week="next")
    assert "Nov 29 to Dec 5" in text(html) and '<a href="/my/lead/sundays?week=next" aria-current="page">Next week</a>' in html
    assert mine(hope, "kara", "2027-01-03")["week"]["which"] == "this", "anything else is this week"
    # Sunday Nov 22, 3 PM at the church: the coming Sunday is today.
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(cw, "_now", lambda: datetime(2026, 11, 22, 15, tzinfo=ZoneInfo("America/New_York"))
                        .astimezone(timezone.utc))
    d = mine(hope, "kara")
    assert d["week"]["from"] == "2026-11-22"
    sunday = next(s for s in d["departments"][0]["teams"][0]["services"] if s["words"] == "Sunday 10:30 AM")
    assert sunday["past"] and all(r["find"] is None for r in sunday["rows"])
    assert "Sunday 10:30 AM · passed" in text(page(hope, "kara")[0])


def test_reads_are_the_churchs_own_bounded_and_counted(hope, shell):
    """The department's week costs about twenty reads (the PR says how many),
    the same reads the office's week makes for those teams, minus its gate's
    duty and area reads; the whole page, with the Lead tab's own, under
    sixty. Each is the church's own, quoted, and only the department's."""
    hope.reads.clear()
    mine(hope, "kara")
    reads = list(hope.reads)
    print(f"\nMy department, Kara (one department): {len(reads)} reads")
    hope.reads.clear()
    mine(hope, "amara")
    print(f"My department, Amara (two departments): {len(hope.reads)} reads")
    hope.reads.clear()
    page(hope, "kara")
    print(f"The whole Sundays page for Kara, the Lead tab's reads too: {len(hope.reads)} reads")
    assert len(hope.reads) < 60
    assert len(reads) <= 30, len(reads)
    for p in reads:
        if p.startswith(("/serve_", "/group_members", "/groups?", "/contacts", "/worship_services", "/church_departments")):
            assert f"business_id=eq.{HOPE}" in p and " " not in p and "+" not in p, p
    # Only the department's teams' places and people are read: never the Parking Team's or the Worship Team's.
    assert not [p for p in reads if p.startswith(("/serve_positions", "/group_members")) and (LOT in p or BAND in p)]
    assert not [p for p in reads if p.startswith("/church_away_asks")], "a waiting ask is never read"
    for p in reads:
        if p.startswith(("/serve_away", "/serve_assignments")):
            assert not re.search(r"select=[^&]*\bnote\b", p), p
    # Away dates: only the department's own people (and whoever holds its places), never another team's.
    w = hope.who[HOPE]
    away = [p for p in reads if p.startswith("/serve_away")]
    assert away and all(w["n040"] in p for p in away)
    others = [w[h] for h in ("n050", "n051", "n052", "n060", "n061", "n062")]          # worship and parking
    assert not [p for p in away for c in others if c in p], "no other department's people's away dates"
    # Every ask at this week's services is read (who is busy on any team is never counted free), and no other week's.
    said = [p for p in reads if p.startswith("/serve_assignments")]
    assert said and all("service_id=in." in p and SUN in p and NEXT_SUN not in p for p in said)


def test_a_read_that_fails_is_plain_words_never_a_500(hope, shell):
    for table, said in (("/serve_assignments", mplg.DEPT_UNREAD), ("/serve_away", mplg.DEPT_UNREAD),
                        ("/church_departments", mplg.DEPT_UNREAD), ("/group_members", mplg.UNREAD)):
        hope.fail = {"get": table}
        html, status = page(hope, "kara")
        assert status == 503 and said in html, table
    hope.fail = {}
    assert page(hope, "kara")[1] == 200


def test_every_word_on_the_page_is_plain(hope, shell):
    for handle in ("kara", "amara", "abel"):
        for q in ({}, {"week": "next"}):
            shown = text(page(hope, handle, **q)[0])
            for rule in (UUID, KEYS, TITLE_WORDS, OFFICE_WORDS):
                assert not rule.search(shown), (handle, rule.pattern[:30], rule.search(shown))
    shown = text(page(hope, "kara", team=KIDS, day=SUN, spot=f"{NURSERY}:2")[0])
    for rule in (UUID, KEYS, TITLE_WORDS, OFFICE_WORDS):
        assert not rule.search(shown), rule.search(shown)
    for w in sl.words("ask", "Kara Bell", "Kids Check-in", {"place": "Nursery", "day": "Sunday, Nov 22",
                                                            "person_name": "Nell Ashby"}).values():
        assert not TITLE_WORDS.search(w) and not KEYS.search(w) and not PRIVATE.search(w)


def test_no_title_word_or_role_key_decides_anything_here():
    titles = re.compile(r"\b(pastors?|elders?|deacons?|ministers?|bishops?|directors?|executive|treasurers?|"
                        r"secretary|trustees?|reverend|apostles?|prophets?)\b", re.I)
    for mod in (cw, sl, mplg):
        code = re.sub(r"#.*", "", re.sub(r'""".*?"""', "", inspect.getsource(mod), flags=re.S))
        assert not ROLE_KEYS.search(code) and not titles.search(code), (mod.__name__, ROLE_KEYS.search(code),
                                                                         titles.search(code))
