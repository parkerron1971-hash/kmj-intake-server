"""A leader's assignments on the member app's Lead tab (member_portal_assign.py;
docs/CHURCH_ASSIGNMENTS.md, PR C2). Kevin, 2026-11-12, on the phone mock:
"phone view idea is good. we can move forward with that."

Pins, at the test churches (church_three), through the real engine
(church_assignments, church_over, church_handovers) and the member routes:
  * the page: Your people for a leader over others (n of m, stuck with Send
    up, next, Give an assignment, Start their first assignment); Your
    assignments (due, done when, from, Done / Stuck / Not stuck); Sent up to
    you (No longer stuck); From the office (Got it); no ids and no office
    words on the screen
  * the writes, as one of the church's people: done, stuck, not stuck until
    it's sent up (then only whoever it went to, or anyone over them), send up
    to whoever is over me, give, start; nobody else's, nobody not under me
  * a live session only: the owner's preview never writes, a cross-site POST
    is refused, and Origin: null from this very address is let through
  * the switch: closed, the tasks page as before and every write a 404
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_assignments as cas  # noqa: E402
import church_handovers as cho  # noqa: E402
import church_leader_tasks as clt  # noqa: E402
import church_three as c3  # noqa: E402
import member_portal_assign as mpa  # noqa: E402
import member_portal_lead as mpl  # noqa: E402
import sb_clients  # noqa: E402
from church_three import GRACE, LOVE_CITY, NEW_HOPE  # noqa: E402

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
OFFICE_WORDS = re.compile(r"\b(login|logins|seat|manager|admin|lane|lanes|duty|duties|check_key|startup)\b", re.I)


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "on")
    d = c3.build(monkeypatch)
    d.t["church_handovers"] = []
    for b in d.t["businesses"]:
        tz = (b.get("settings") or {}).get("timezone")
        if tz:
            b["settings"] = {**b["settings"], "availability": {"timezone": tz}}
    for mod in (cas, cho, mpa):
        monkeypatch.setattr(mod, "_now", lambda: NOW)
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
    """The member routes, signed in as `app.me` (a person) at their church."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import member_portal_church as mpc
    a = FastAPI()
    a.include_router(mpa.router)
    state = {"me": None, "biz": LOVE_CITY, "unavailable": False}

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


def page(db, biz, handle, **q):
    html, status = asyncio.run(mpl.serve(SimpleNamespace(query_params=q), c3.church(db, biz), {}, me(db, biz, handle),
                                         "/my/lead/tasks"))
    return html, status


def text(html):
    """What's on the screen: no tags, no form addresses, no hidden values."""
    out = re.sub(r"<[^>]+>", " ", re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S))
    return re.sub(r"\s+", " ", out)


def as_(app, biz, handle):
    app.state.update(biz=biz, me=me(app.db, biz, handle))


def post(app, path, **form):
    return app.post(path, data=form, follow_redirects=False)


def task(db, title):
    return next(t for t in db.t["tasks"] if t["title"] == title)


def hand(db, biz, handle, title, **kw):
    row = {"id": f"7b000000-0000-4000-8000-{len(db.t['tasks']):012d}", "business_id": biz, "status": "todo",
           "title": title, "description": None, "due_date": "2026-11-20", "assigned_contact_id": db.who[biz][handle],
           "assigned_to": None, "handed_by": c3.church(db, biz)["owner_id"], "created_at": NOW.isoformat(),
           "completed_at": None, "leader_told_at": NOW.isoformat(), "late_told_at": None, **kw}
    db.t["tasks"].append(row)
    return row


# ─── The page ─────────────────────────────────────────────────────────

def test_an_overseer_sees_their_people_as_on_the_phone_mock(db, shell):
    html, status = page(db, LOVE_CITY, "andre")
    assert status == 200 and shell["tab"] == "lead" and shell["wide"] is True
    words = text(html)
    assert "Your people" in words and "Yolanda Reed" in words and "Leads Youth" in words
    assert "Tyrone Banks" in words and "Youth Ministry (YWD) leader · under Yolanda" in words
    assert words.count("Give an assignment") == 2 and "Start their first assignment" in words
    assert "Your assignments" in words and "Nothing is handed to you right now." in words
    assert 'action="/my/lead/assignments/give"' in html
    assert not UUID.search(words), "no ids on the screen"
    assert not OFFICE_WORDS.search(words), OFFICE_WORDS.search(words)


def test_a_leader_sees_their_assignment_with_done_and_stuck(db, shell):
    hand(db, LOVE_CITY, "yolanda", "Book the gym", done_when="The church calendar shows it")
    html, status = page(db, LOVE_CITY, "yolanda")
    words = text(html)
    assert status == 200 and "Plan the youth lock-in" in words and "Book the gym" in words
    assert "Done when The church calendar shows it" in words and "From Pastor Kevin" in words
    assert "late" in words and "Mark it stuck" in words
    assert "Your people" in words and "Tyrone Banks" in words, "she leads Youth, so its team leader is under her"
    assert not UUID.search(words) and not OFFICE_WORDS.search(words)


def test_the_section_switcher_says_assignments_and_counts(db, shell):
    hand(db, LOVE_CITY, "ruth", "Order prayer cards")
    html, _ = page(db, LOVE_CITY, "ruth")
    assert re.search(r'<a href="/my/lead/tasks" aria-current="page">Assignments · 1</a>', html)


# ─── Stuck, sent up, sent up to you ───────────────────────────────────

def test_stuck_then_sent_up_by_the_one_over_them_then_only_whoever_it_went_to_clears_it(app, db, shell):
    t = task(db, "Plan the youth lock-in")
    as_(app, LOVE_CITY, "yolanda")
    r = post(app, f"/my/lead/assignments/{t['id']}/stuck", note="No room on the 20th")
    assert r.status_code == 303 and r.headers["location"] == "/my/lead/tasks?done=as_stuck"
    assert task(db, "Plan the youth lock-in")["stuck_note"] == "No room on the 20th"
    words = text(page(db, LOVE_CITY, "andre")[0])
    assert "Stuck · today" in words and "No room on the 20th" in words and "Send up to Pastor Kevin" in words
    as_(app, LOVE_CITY, "andre")
    r = post(app, f"/my/lead/assignments/{t['id']}/raise")
    assert r.headers["location"] == "/my/lead/tasks?done=as_raised"
    row = task(db, "Plan the youth lock-in")
    assert row["raised_to"] == c3.church(db, LOVE_CITY)["owner_id"] and row["raised_by"] is None
    words = text(page(db, LOVE_CITY, "yolanda")[0])
    assert "Sent up to Pastor Kevin. They’ll say when it’s no longer stuck." in words and "Not stuck" not in words
    as_(app, LOVE_CITY, "yolanda")
    r = post(app, f"/my/lead/assignments/{t['id']}/unstuck")
    assert r.headers["location"] == "/my/lead/tasks?err=as_sent_up"
    assert task(db, "Plan the youth lock-in")["stuck_at"], "still stuck"
    r = post(app, f"/my/lead/assignments/{t['id']}/done")
    assert r.headers["location"] == "/my/lead/tasks?done=as_done" and task(db, "Plan the youth lock-in")["status"] == "done"


def test_sent_up_to_a_person_shows_on_their_page_and_they_clear_it(app, db, shell):
    t = hand(db, LOVE_CITY, "iris", "Pray over the list", stuck_note="The list never came", stuck_at=NOW.isoformat())
    as_(app, LOVE_CITY, "ruth")                                 # Iris is under Ruth (the Prayer leader)
    assert post(app, f"/my/lead/assignments/{t['id']}/raise").headers["location"].endswith("done=as_raised")
    row = task(db, "Pray over the list")
    assert row["raised_to_contact_id"] == db.who[LOVE_CITY]["paul"], "Ruth answers to Prayer's overseer"
    words = text(page(db, LOVE_CITY, "paul")[0])
    assert "Sent up to you" in words and "Iris’s · Stuck · today" in words and "No longer stuck" in words
    assert "Sent up by Ruth Okafor" in words
    as_(app, LOVE_CITY, "paul")
    assert post(app, f"/my/lead/assignments/{t['id']}/unstuck").headers["location"].endswith("done=as_unstuck")
    assert task(db, "Pray over the list")["stuck_at"] is None


def test_a_stuck_one_of_your_own_is_not_stuck_again_until_its_sent_up(app, db):
    t = hand(db, LOVE_CITY, "ruth", "Order prayer cards", stuck_note="", stuck_at=NOW.isoformat())
    as_(app, LOVE_CITY, "ruth")
    assert post(app, f"/my/lead/assignments/{t['id']}/unstuck").headers["location"].endswith("done=as_unstuck")
    assert task(db, "Order prayer cards")["stuck_at"] is None


# ─── Give, start ──────────────────────────────────────────────────────

def test_an_overseer_gives_an_assignment_to_someone_under_them_and_no_one_else(app, db):
    as_(app, LOVE_CITY, "andre")
    yolanda = db.who[LOVE_CITY]["yolanda"]
    r = post(app, "/my/lead/assignments/give", **{"for": yolanda, "title": "Meet each team leader",
                                                  "due_date": "2026-11-22", "done_when": "All three met"})
    assert r.headers["location"] == "/my/lead/tasks?done=as_given"
    row = task(db, "Meet each team leader")
    assert row["assigned_contact_id"] == yolanda and row["handed_by"] is None and row["due_date"] == "2026-11-22"
    before = len(db.t["tasks"])
    r = post(app, "/my/lead/assignments/give", **{"for": db.who[LOVE_CITY]["ruth"], "title": "x"})
    assert r.headers["location"] == "/my/lead/tasks?err=as_gone" and len(db.t["tasks"]) == before
    r = post(app, "/my/lead/assignments/give", **{"for": yolanda, "title": ""})
    assert r.headers["location"] == "/my/lead/tasks?err=as_said" and len(db.t["tasks"]) == before
    r = post(app, "/my/lead/assignments/give", **{"for": "not-an-id", "title": "x"})
    assert r.headers["location"] == "/my/lead/tasks?err=as_said"


def test_an_overseer_starts_a_leaders_first_assignment_once(app, db, shell):
    as_(app, LOVE_CITY, "andre")
    yolanda = db.who[LOVE_CITY]["yolanda"]
    assert post(app, "/my/lead/assignments/start", **{"for": yolanda}).headers["location"].endswith("done=as_started")
    made = [t for t in db.t["tasks"] if t.get("assigned_contact_id") == yolanda and t.get("startup_key")]
    assert made and all(t["handed_by"] is None for t in made)
    post(app, "/my/lead/assignments/start", **{"for": yolanda})
    assert len([t for t in db.t["tasks"] if t.get("assigned_contact_id") == yolanda and t.get("startup_key")]) == len(made)
    words = text(page(db, LOVE_CITY, "andre")[0])
    assert f"First assignment 0 of {len(made)}" in words


def test_grace_a_deacon_overseer_and_new_hope_an_associate_pastor_see_their_people(db, shell):
    words = text(page(db, GRACE, "daniel")[0])
    assert "Your people" in words and "Yvette Long" in words
    words = text(page(db, NEW_HOPE, "amara")[0])
    for name in ("Elena Ruiz", "Yusuf Grant", "Kara Bell"):
        assert name in words, name
    assert "Answers to you" in words and "Leads Kids" in words


# ─── From the office ──────────────────────────────────────────────────

def _send(db, biz, sender, to, title, **kw):
    import church_over as co
    ch = co.Church(c3.church(db, biz))
    u = c3.church(db, biz)["owner_id"] if sender == "owner" else db.who[biz][sender + "@"]
    return cho.send(ch, u, {"contact_id": db.who[biz][to], "title": title, **kw})


def test_what_the_office_sent_an_elder_shows_with_got_it_and_then_seen(app, db, shell):
    got = _send(db, LOVE_CITY, "minnie", "marcus", "The retreat center’s address", note="Pine Lodge, 14 Lake Rd.",
                link="https://example.org/lodge", for_date="2026-11-21")
    html = page(db, LOVE_CITY, "marcus")[0]
    words = text(html)
    assert "From the office" in words and "The retreat center’s address" in words and "Pine Lodge, 14 Lake Rd." in words
    assert "Minnie Tatum · for Saturday, Nov 21" in words and "Got it" in words
    assert 'href="https://example.org/lodge" target="_blank" rel="noopener noreferrer"' in html
    as_(app, LOVE_CITY, "marcus")
    r = post(app, f"/my/lead/handovers/{got['id']}/seen")
    assert r.headers["location"] == "/my/lead/tasks?done=as_seen"
    assert db.t["church_handovers"][0]["seen_at"]
    assert "Seen" in text(page(db, LOVE_CITY, "marcus")[0])
    as_(app, LOVE_CITY, "tanya")
    assert post(app, f"/my/lead/handovers/{got['id']}/seen").headers["location"].endswith("err=as_gone")


def test_a_link_that_isnt_https_is_never_a_link(db, shell):
    db.t["church_handovers"].append({"id": "5d000000-0000-4000-8000-000000000001", "business_id": LOVE_CITY,
                                     "contact_id": db.who[LOVE_CITY]["marcus"], "sent_by": None,
                                     "title": "<b>Keys</b>", "note": "<script>x</script>",
                                     "link": "javascript:alert(1)", "for_date": None, "department_id": None,
                                     "created_at": NOW.isoformat(), "seen_at": None, "told_at": None})
    html = page(db, LOVE_CITY, "marcus")[0]
    assert "javascript:" not in html and "<script>x" not in html and "&lt;b&gt;Keys&lt;/b&gt;" in html
    assert "The church office" in text(html)


def test_the_page_stands_when_what_the_office_sent_cant_be_read(db, shell, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/church_handovers") else real(path, **kw))
    html, status = page(db, LOVE_CITY, "andre")
    assert status == 200 and "What the office sent couldn’t load just now." in text(html)


# ─── A live session only; the switch ──────────────────────────────────

def test_the_owners_preview_never_writes(app, db):
    t = task(db, "Plan the youth lock-in")
    app.state.update(unavailable="preview")
    r = post(app, f"/my/lead/assignments/{t['id']}/done")
    assert r.headers["location"] == "/my/lead/tasks?err=preview" and task(db, "Plan the youth lock-in")["status"] == "todo"


def test_nobody_elses_assignment_is_yours_to_mark(app, db):
    t = task(db, "Plan the youth lock-in")
    as_(app, LOVE_CITY, "ruth")
    assert post(app, f"/my/lead/assignments/{t['id']}/done").headers["location"].endswith("err=as_gone")
    assert post(app, "/my/lead/assignments/not-an-id/done").headers["location"].endswith("err=as_gone")
    as_(app, GRACE, "yvette")                                   # another church's person, by a real id
    assert post(app, f"/my/lead/assignments/{t['id']}/done").headers["location"].endswith("err=as_gone")
    assert task(db, "Plan the youth lock-in")["status"] == "todo"


def test_a_cross_site_post_is_refused_and_origin_null_from_this_address_is_let_through(db, monkeypatch):
    """The routes take member_portal_church._signed_in's session, whose
    _church_or_404 refuses another site's POST and reads Origin: null by the
    browser's own Sec-Fetch-Site (no-referrer-nulls-form-origin)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import member_portal
    import public_site
    a = FastAPI()
    a.include_router(mpa.router)
    c = TestClient(a, base_url="https://lovecityc.com")
    monkeypatch.setattr(public_site, "public_host", lambda request: "lovecityc.com")
    church = {"business": c3.church(db, LOVE_CITY), "site": {}}
    monkeypatch.setattr(member_portal, "_church_for_request", lambda request: church)
    monkeypatch.setattr(member_portal, "portal_active", lambda biz: True)
    monkeypatch.setattr(member_portal, "_session_for", lambda request, ch: {"me": me(db, LOVE_CITY, "yolanda")})
    t = task(db, "Plan the youth lock-in")
    r = c.post(f"/my/lead/assignments/{t['id']}/done", headers={"Origin": "https://evil.example"},
               follow_redirects=False)
    assert r.status_code == 403 and task(db, "Plan the youth lock-in")["status"] == "todo"
    r = c.post(f"/my/lead/assignments/{t['id']}/done", headers={"Origin": "null", "Sec-Fetch-Site": "cross-site"},
               follow_redirects=False)
    assert r.status_code == 403
    r = c.post(f"/my/lead/assignments/{t['id']}/done", headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"},
               follow_redirects=False)
    assert r.status_code == 303 and task(db, "Plan the youth lock-in")["status"] == "done"


def test_closed_the_tasks_page_is_as_before_and_every_write_is_a_404(app, db, shell, monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    html, status = page(db, LOVE_CITY, "yolanda")
    assert status == 200 and "My tasks" in text(html) and "Your people" not in text(html)
    t = task(db, "Plan the youth lock-in")
    as_(app, LOVE_CITY, "yolanda")
    assert post(app, f"/my/lead/assignments/{t['id']}/done").status_code == 404
    assert task(db, "Plan the youth lock-in")["status"] == "todo"


def test_one_sent_up_from_the_member_app_names_the_leader_who_sent_it(app, db, monkeypatch):
    sent = []
    monkeypatch.setattr(clt, "deliver", lambda biz, to, name, subject, html, key, reply_to=None:
                        sent.append({"to": to, "name": name, "html": html}))
    t = hand(db, LOVE_CITY, "iris", "Pray over the list", stuck_note="The list never came", stuck_at=NOW.isoformat())
    as_(app, LOVE_CITY, "ruth")
    post(app, f"/my/lead/assignments/{t['id']}/raise")
    cas.sweep_tick(NOW)
    paul = [m for m in sent if m["name"] == "Paul Mensah"]
    assert len(paul) == 1 and "Ruth Okafor sent up something that" in paul[0]["html"]
    assert task(db, "Pray over the list")["raised_by_contact_id"] == db.who[LOVE_CITY]["ruth"]


def test_what_a_leader_gives_or_starts_says_who_gave_it_on_the_page_and_in_the_email(app, db, shell, monkeypatch):
    sent = []
    monkeypatch.setattr(clt, "deliver", lambda biz, to, name, subject, html, key, reply_to=None:
                        sent.append({"name": name, "subject": subject, "html": html}))
    as_(app, LOVE_CITY, "andre")
    yolanda, tyrone = db.who[LOVE_CITY]["yolanda"], db.who[LOVE_CITY]["tyrone"]
    post(app, "/my/lead/assignments/give", **{"for": yolanda, "title": "Meet each team leader"})
    post(app, "/my/lead/assignments/start", **{"for": tyrone})
    row = task(db, "Meet each team leader")
    assert row["handed_by"] is None and row["handed_by_contact_id"] == db.who[LOVE_CITY]["andre"]
    made = [t for t in db.t["tasks"] if t.get("assigned_contact_id") == tyrone and t.get("startup_key")]
    assert made and all(t["handed_by_contact_id"] == db.who[LOVE_CITY]["andre"] for t in made)
    assert "From Andre Wallace" in text(page(db, LOVE_CITY, "yolanda")[0])
    titles = {t["title"] for t in made}
    assert {"Who's on your team or group", "When you meet: the day and time"} <= titles, "each reads alone"
    clt.sweep_tick(NOW)
    by = {m["name"]: m for m in sent}
    assert "Andre Wallace" in by["Yolanda Reed"]["html"] and "Andre Wallace gave you" in by["Tyrone Banks"]["html"]
    assert "under Assignments" in by["Tyrone Banks"]["html"]
