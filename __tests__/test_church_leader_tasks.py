"""My tasks for leaders (church_leader_tasks.py, Kevin 2026-10-27: "yes build
my tasks for leaders").

Pins:
  * the office's Hand to list gains the church's leaders (the All group
    leaders room), by name and role title, never an email, only while the
    switch is open to the login (off / owner / on) and the migration is in
  * a leader's Lead tab Tasks: only the tasks handed to them, late first,
    then by due date, in the church's words; another leader's task and
    another church's are 404, read or done
  * Done marks the task done, when, and who
  * the sweep emails a newly handed task once (two runs, one email), marks
    a leader with no email told without sending, and lets the claim go when
    the send fails; a done task is never told about
  * late: told once, in the church's morning, to whoever the leader answers
    to (a vacant role passed over); never for a done task; never before the
    due date on the church's own clock; a group leader with no role above
    them: back to whoever handed it out (handed_by), else no one to tell
  * the leader's page and email name who handed it, else "the church office"
  * the Board's "Make tasks" hands a no-login member's follow-up to them as
    a leader
  * before the migration everything is quiet: no Leaders, no Tasks, no
    sweep, never a 500

The tables are the role tests' in-memory PostgREST."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_leader_tasks as clt  # noqa: E402
import church_my_week as mw  # noqa: E402
import member_asks  # noqa: E402
import member_portal_church as mpc  # noqa: E402
import member_portal_lead as mpl  # noqa: E402
import sb_clients  # noqa: E402
from test_church_roles import FakeDB  # noqa: E402

BIZ = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
OTHER = "22222222-2222-4222-8222-222222222222"
OWNER = "33333333-3333-4333-8333-333333333333"
PLATFORM = "kmjcreativesolution@gmail.com"
KEVIN, RAY, TASHA, DANA, GRACE = (f"c0000000-0000-4000-8000-00000000000{i}" for i in range(1, 6))
GROUP = "a0000000-0000-4000-8000-00000000000a"
T_LATE, T_SOON, T_NODATE, T_TASHA, T_OTHER, T_DONE, T_LOGIN = (
    f"70000000-0000-4000-8000-00000000000{i}" for i in range(1, 8))
NOW = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)        # Wednesday, 9:00 AM in Chicago
CHURCH = {"id": BIZ, "name": "Love City Church", "type": "ministry",
          "settings": {"timezone": "America/Chicago", "availability": {"timezone": "America/Chicago"}}}


def _task(tid, who, title, due=None, biz=BIZ, **kw):
    return {"id": tid, "business_id": biz, "title": title, "description": kw.pop("description", None),
            "status": kw.pop("status", "todo"), "priority": "medium", "due_date": due, "assigned_to": None,
            "assigned_contact_id": who, "leader_told_at": kw.pop("told", "2026-10-20T12:00:00+00:00"),
            "late_told_at": None, "done_by_contact_id": None, "completed_at": None,
            "created_at": kw.pop("created_at", "2026-10-20T12:00:00+00:00"), **kw}


def _def(key, title, job, reports_to=None):
    return {"id": f"def-{key}", "business_id": BIZ, "key": key, "title": title, "job": job, "status": "active",
            "covers": "church", "oversees_teams": [], "handles": [], "sees": [], "reports_to": reports_to,
            "sort": 0, "created_at": "2026-10-01T00:00:00+00:00"}


def _role(contact, role, biz=BIZ):
    return {"id": f"r-{contact[-2:]}-{role}", "business_id": biz, "contact_id": contact, "role": role, "scope": "",
            "status": "active", "invited_at": "2026-10-01T00:00:00+00:00"}


class TasksDB(FakeDB):
    """Before the migration, PostgREST refuses any read or write naming the
    new columns (a 400: the helpers' None)."""
    migrated = True

    def _old(self, path, body=None):
        if self.migrated or not path.lstrip("/").startswith("tasks"):
            return False
        return any(c in path or c in (body or {}) for c in clt.NEW_COLUMNS.split(","))

    def get(self, path, **kw):
        return None if self._old(path) else super().get(path, **kw)

    def patch(self, path, body, **kw):
        return None if self._old(path, body) else super().patch(path, body, **kw)

    def post(self, path, body, prefer=None, **kw):
        return None if self._old(path, body) else super().post(path, body, prefer=prefer, **kw)


@pytest.fixture
def db(monkeypatch):
    fake = TasksDB(
        businesses=[{**CHURCH, "owner_id": OWNER,
                     "settings": {**CHURCH["settings"], "contact_email": "office@lovecity.org"}},
                    {"id": OTHER, "name": "Grace Chapel", "type": "ministry", "owner_id": "someone", "settings": {}}],
        business_sites=[{"business_id": BIZ, "slug": "love-city-church", "site_config": {}}],
        business_users=[],
        contacts=[{"id": KEVIN, "business_id": BIZ, "name": "Kevin McCloud", "email": "kevin@lovecity.org"},
                  {"id": RAY, "business_id": BIZ, "name": "Ray Dunn", "email": "ray@example.com"},
                  {"id": TASHA, "business_id": BIZ, "name": "Tasha Williams", "email": None},
                  {"id": DANA, "business_id": BIZ, "name": "Dana Rivers", "email": "dana@example.com"},
                  {"id": GRACE, "business_id": OTHER, "name": "Grace Member", "email": "grace@example.com"}],
        church_role_defs=[_def("pastor", "Lead Pastor", "senior"),
                          _def("associate", "Associate Pastor", "pastoral", "def-pastor"),
                          _def("youth_pastor", "Youth Pastor", "pastoral", "def-associate")],
        church_leader_roles=[_role(KEVIN, "pastor"), _role(RAY, "youth_pastor")],
        groups=[{"id": GROUP, "business_id": BIZ, "name": "Sisters in the City", "active": True}],
        group_members=[{"business_id": BIZ, "group_id": GROUP, "contact_id": TASHA, "role": "leader"}],
        tasks=[_task(T_LATE, RAY, "Plan the fall retreat", "2026-10-26", description="Book the lodge.\nAsk about the bus."),
               _task(T_SOON, RAY, "Order the youth shirts", "2026-11-13"),
               _task(T_NODATE, RAY, "Draft the winter calendar"),
               _task(T_TASHA, TASHA, "Call the caterer", "2026-10-30"),
               _task(T_OTHER, RAY, "Another church's task", "2026-10-26", biz=OTHER),
               _task(T_DONE, RAY, "Count the chairs", "2026-10-25", status="done",
                     completed_at="2026-10-27T15:00:00+00:00", done_by_contact_id=RAY),
               {**_task(T_LOGIN, None, "Print the bulletins", "2026-10-29"), "assigned_to": OWNER}],
    )
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "on")
    monkeypatch.delenv("PLATFORM_OWNER_EMAIL", raising=False)
    monkeypatch.setattr(clt, "_now", lambda: NOW)
    monkeypatch.setattr(member_asks, "platform_church", lambda b: str(b) == BIZ)
    fake.sent = []

    def deliver(biz, to, name, subject, html, key, reply_to=None):
        if fake.fail_to and to in fake.fail_to:
            raise RuntimeError("Resend said no")
        fake.sent.append({"biz": biz["id"], "to": to, "name": name, "subject": subject, "html": html, "key": key,
                          "reply_to": reply_to})
    fake.fail_to = set()
    monkeypatch.setattr(clt, "deliver", deliver)
    return fake


def _t(db, tid):
    return next(t for t in db.t["tasks"] if t["id"] == tid)


# ─── The office's Hand to list ────────────────────────────────────────

@pytest.fixture
def office(db, monkeypatch):
    import business_access
    who = {"role": "owner", "id": OWNER, "email": PLATFORM}
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: who["role"])
    monkeypatch.setenv("CHURCH_AREAS", "on")
    app = FastAPI()
    app.include_router(mw.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email=who["email"], user_metadata={})))
    c = TestClient(app)
    c.who = who
    return c


def _people(office):
    r = office.get(f"/church/my-week/people?business_id={BIZ}")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_hand_to_list_gains_the_churchs_leaders_by_name_and_title_never_an_email(office, monkeypatch):
    got = _people(office)
    assert got["leaders"] == [
        {"contact_id": KEVIN, "name": "Kevin McCloud", "title": "Lead Pastor"},
        {"contact_id": RAY, "name": "Ray Dunn", "title": "Youth Pastor"},
        {"contact_id": TASHA, "name": "Tasha Williams", "title": "Group leader"},
    ], "the leaders room: roles that lead and group leaders; Dana leads nothing"
    assert "@" not in str(got["leaders"]) and got["people"][0]["user_id"] == OWNER, "the logins stand as they were"


def test_the_switch_decides_who_sees_the_leaders(office, monkeypatch):
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "owner")
    assert "leaders" in _people(office), "owner: the platform owner"
    office.who["email"] = "pastor@lovecity.org"
    assert "leaders" not in _people(office), "owner: nobody else"
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "on")
    assert "leaders" in _people(office), "on: every login that can change tasks"
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "off")
    office.who["email"] = PLATFORM
    assert "leaders" not in _people(office), "off: no one"
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "sideways")
    assert clt.mode() == "off"
    monkeypatch.delenv("CHURCH_LEADER_TASKS")
    assert clt.mode() == "owner"


def test_a_room_that_cant_be_read_drops_the_leaders_and_keeps_the_logins(office, db, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/group_members") else real(path, **kw))
    got = _people(office)
    assert "leaders" not in got and got["people"]


# ─── The leader's Tasks ───────────────────────────────────────────────

def _me(cid, name):
    return {"id": cid, "name": name}


def _req(**q):
    return SimpleNamespace(query_params=q, cookies={}, headers={})


@pytest.fixture
def shell(monkeypatch):
    import member_portal
    seen = {}

    def fake_shell(biz, site, title, body, **kw):
        seen.update(kw, title=title)
        return body
    monkeypatch.setattr(member_portal, "_shell", fake_shell)
    return seen


def _page(me, sub="/my/lead/tasks", **q):
    return asyncio.run(mpl.serve(_req(**q), CHURCH, {}, me, sub))


def test_a_leader_sees_only_their_own_tasks_late_first_in_the_churchs_words(db, shell):
    html, status = _page(_me(RAY, "Ray Dunn"))
    assert status == 200 and shell["title"] == "My tasks" and shell["tab"] == "lead"
    assert html.index("Plan the fall retreat") < html.index("Order the youth shirts") < html.index("Draft the winter calendar")
    assert "2 days late" in html and "Due Friday, Nov 13" in html and "No due date" in html
    assert "Book the lodge.\nAsk about the bus." in html, "the office's notes, as written"
    assert "From the church office" in html
    assert f'action="/my/lead/tasks/{T_LATE}/done"' in html
    assert "Call the caterer" not in html, "another leader's"
    assert "Another church" not in html, "another church's"
    assert "Print the bulletins" not in html, "a login's"
    assert "Done lately · 1" in html and "Count the chairs" in html and "Done by you" in html
    assert "“Plan the fall retreat” is 2 days late." in html, "Chief names the late one"
    assert 'href="/my/lead/tasks" aria-current="page">Tasks · 3<' in html and 'href="/my/lead">People<' in html


def test_due_words_say_it_the_way_the_church_would():
    today = datetime(2026, 10, 28).date()
    assert clt.due_words("2026-10-27", today) == {"text": "1 day late", "state": "late"}
    assert clt.due_words("2026-10-28", today)["text"] == "Due today"
    assert clt.due_words("2026-10-29", today)["text"] == "Due tomorrow"
    assert clt.due_words("2026-11-13", today) == {"text": "Due Friday, Nov 13", "state": ""}
    assert clt.due_words(None, today)["text"] == "No due date"


def test_the_switcher_offers_tasks_on_every_lead_page(db, shell):
    html, _ = _page(_me(RAY, "Ray Dunn"), "/my/lead")
    assert 'href="/my/lead/tasks">Tasks · 3<' in html


def test_someone_with_only_a_task_opens_on_it_and_gets_the_tab(db, shell):
    import member_portal
    assert asyncio.run(member_portal._leads(BIZ, DANA, CHURCH, _me(DANA, "Dana Rivers"))) is False
    db.t["tasks"].append(_task("70000000-0000-4000-8000-0000000000aa", DANA, "Bring the projector", "2026-11-01"))
    assert asyncio.run(member_portal._leads(BIZ, DANA, CHURCH, _me(DANA, "Dana Rivers"))) is True
    html, status = _page(_me(DANA, "Dana Rivers"), "/my/lead")
    assert status == 200 and "Bring the projector" in html and shell["title"] == "My tasks"


@pytest.fixture
def lead(db, monkeypatch):
    who = {"me": _me(RAY, "Ray Dunn"), "unavailable": False}

    async def signed_in(request):
        return {"business": CHURCH, "site": {}}, who["me"], who["unavailable"]
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a: True)
    import member_portal
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **kw: body)
    app = FastAPI()
    app.include_router(mpl.router)
    c = TestClient(app)
    c.who = who
    return c


def _done(c, tid):
    return c.post(f"/my/lead/tasks/{tid}/done", follow_redirects=False)


def test_done_marks_it_done_and_records_who(lead, db):
    r = _done(lead, T_LATE)
    assert r.status_code == 303 and r.headers["location"] == "/my/lead/tasks?done=task_done"
    t = _t(db, T_LATE)
    assert t["status"] == "done" and t["done_by_contact_id"] == RAY and t["completed_at"] == "2026-10-28T14:00:00+00:00"
    assert _done(lead, T_LATE).headers["location"] == "/my/lead/tasks?done=task_done", "twice is done once"


@pytest.mark.parametrize("tid", [T_TASHA, T_OTHER, T_LOGIN, "70000000-0000-4000-8000-0000000000ff", "nope"])
def test_anyone_elses_task_is_a_404_and_stays_as_it_was(lead, db, tid):
    r = _done(lead, tid)
    assert r.status_code == 404 and "That task isn’t handed to you anymore." in r.text
    assert "Plan the fall retreat" in r.text, "their own list, saying so"
    assert all(t["status"] != "done" for t in db.t["tasks"] if t["id"] != T_DONE)


def test_the_owners_preview_never_marks_anything(lead, db):
    lead.who.update(me=None, unavailable="preview")
    assert _done(lead, T_LATE).headers["location"] == "/my/lead/tasks?err=preview"
    assert _t(db, T_LATE)["status"] == "todo"


def test_a_church_the_switch_hasnt_reached_has_no_tasks(lead, db, shell, monkeypatch):
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: False)
    assert _done(lead, T_LATE).status_code == 404 and _t(db, T_LATE)["status"] == "todo"
    html, status = _page(_me(RAY, "Ray Dunn"))
    assert status == 404 and "Plan the fall retreat" not in html
    html, _ = _page(_me(RAY, "Ray Dunn"), "/my/lead")
    assert "/my/lead/tasks" not in html


# ─── Telling the leader ───────────────────────────────────────────────

def _fresh(db, tid, who, title, **kw):
    db.t["tasks"].append(_task(tid, who, title, told=None, **kw))


def _handed_mail(db):
    return [m for m in db.sent if m["subject"].endswith("a task for you")]


def test_a_newly_handed_task_is_emailed_to_its_leader_once(db):
    _fresh(db, "71000000-0000-4000-8000-000000000001", RAY, "Lead the youth retreat", due="2026-11-15",
           description="Two nights at Camp Hope.")
    first = clt.sweep_tick(NOW)
    again = clt.sweep_tick(NOW)
    assert first["told"] == 1 and again["told"] == 0 and len(_handed_mail(db)) == 1
    m = _handed_mail(db)[0]
    assert m["to"] == "ray@example.com" and m["subject"] == "Love City Church: a task for you"
    assert "Lead the youth retreat" in m["html"] and "Sunday, November 15" in m["html"] and "Camp Hope" in m["html"]
    assert "https://love-city-church.mysolutionist.app/my/lead/tasks" in m["html"]
    assert m["key"] == f"leader-task-71000000-0000-4000-8000-000000000001-{RAY}"
    assert m["reply_to"] == "office@lovecity.org", "a reply goes to the church office"
    assert _t(db, "71000000-0000-4000-8000-000000000001")["leader_told_at"] == "2026-10-28T14:00:00+00:00"


def test_a_leader_with_no_email_is_marked_told_and_nothing_is_sent(db):
    _fresh(db, "71000000-0000-4000-8000-000000000002", TASHA, "Call the caterer again")
    stats = clt.sweep_tick(NOW)
    assert stats["no_email"] == 1 and not _handed_mail(db)
    assert _t(db, "71000000-0000-4000-8000-000000000002")["leader_told_at"]
    assert clt.sweep_tick(NOW)["no_email"] == 0, "asked once"


def test_a_send_that_fails_lets_the_claim_go_and_the_next_sweep_sends(db):
    tid = "71000000-0000-4000-8000-000000000003"
    _fresh(db, tid, RAY, "Lead the youth retreat")
    db.fail_to = {"ray@example.com"}
    assert clt.sweep_tick(NOW)["unsent"] == 1 and _t(db, tid)["leader_told_at"] is None
    db.fail_to = set()
    assert clt.sweep_tick(NOW)["told"] == 1 and len(_handed_mail(db)) == 1


def test_a_done_task_and_another_churchs_closed_switch_are_never_told(db, monkeypatch):
    _fresh(db, "71000000-0000-4000-8000-000000000004", RAY, "Already done", status="done")
    assert clt.sweep_tick(NOW)["told"] == 0 and not _handed_mail(db)
    _fresh(db, "71000000-0000-4000-8000-000000000005", RAY, "Lead the youth retreat")
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: False)
    db.sent.clear()
    assert clt.sweep_tick(NOW)["told"] == 0 and not db.sent, "nothing at all for a church the switch hasn't reached"
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "off")
    assert clt.sweep_tick(NOW) == {"churches": 0, "told": 0, "no_email": 0, "unsent": 0, "late": 0,
                                   "late_no_one": 0, "late_no_email": 0, "late_unsent": 0}


def test_two_sweeps_at_once_send_once(db, monkeypatch):
    """The claim is the guard: the second sweep's claim finds it taken."""
    tid = "71000000-0000-4000-8000-000000000006"
    _fresh(db, tid, RAY, "Lead the youth retreat")
    real = db.get
    # Both sweeps read the task before either claims it.
    snapshot = [dict(r) for r in real(f"/tasks?id=eq.{tid}")]
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: [dict(r) for r in snapshot] if "leader_told_at=is.null" in path else real(path, **kw))
    clt.sweep_tick(NOW)
    clt.sweep_tick(NOW)
    assert len(_handed_mail(db)) == 1


# ─── Late goes up ─────────────────────────────────────────────────────

def _late_mail(db):
    return [m for m in db.sent if "past due" in m["subject"]]


def test_a_late_task_goes_up_once_to_whoever_the_leader_answers_to(db):
    stats = clt.sweep_tick(NOW)
    late = _late_mail(db)
    assert stats["late"] == 1 and len(late) == 1, "Plan the fall retreat: due Monday, told last week"
    m = late[0]
    assert m["to"] == "kevin@lovecity.org", "the Associate Pastor's role is empty: passed over to the Lead Pastor"
    assert m["subject"] == "Ray Dunn has a task past due"
    assert "Plan the fall retreat" in m["html"] and "Monday, October 26" in m["html"] and "answers to you" in m["html"]
    assert _t(db, T_LATE)["late_told_at"] == "2026-10-28T14:00:00+00:00"
    assert _t(db, T_TASHA)["late_told_at"] is None and _t(db, T_SOON)["late_told_at"] is None, "not yet due"
    clt.sweep_tick(NOW)
    assert len(_late_mail(db)) == 1, "once"


def test_several_late_tasks_go_up_in_one_email(db):
    db.t["tasks"].append(_task("72000000-0000-4000-8000-000000000001", RAY, "Return the van keys", "2026-10-27"))
    clt.sweep_tick(NOW)
    late = _late_mail(db)
    assert len(late) == 1 and late[0]["subject"] == "Ray Dunn has 2 tasks past due"
    assert "Return the van keys" in late[0]["html"] and "Plan the fall retreat" in late[0]["html"]


def test_a_done_task_is_never_told_late(db):
    _t(db, T_LATE)["status"] = "done"
    clt.sweep_tick(NOW)
    assert not _late_mail(db)


def test_late_is_the_churchs_own_day_and_its_morning(db):
    # 10 PM on Tuesday in Chicago (Wednesday in UTC): nothing goes up at night.
    clt.sweep_tick(datetime(2026, 10, 28, 3, 0, tzinfo=timezone.utc))
    assert not _late_mail(db)
    # Wednesday 9 AM: a task due today isn't late; one due yesterday is.
    _t(db, T_LATE)["due_date"] = "2026-10-28"
    clt.sweep_tick(NOW)
    assert not _late_mail(db)
    _t(db, T_LATE)["due_date"] = "2026-10-27"
    clt.sweep_tick(NOW)
    assert len(_late_mail(db)) == 1


def test_a_church_ahead_of_utc_is_late_on_its_own_date(db):
    # Auckland: 9 AM Thursday the 29th there is still Wednesday the 28th in UTC.
    for b in db.t["businesses"]:
        if b["id"] == BIZ:
            b["settings"] = {**b["settings"], "availability": {"timezone": "Pacific/Auckland"}}
    _t(db, T_LATE)["due_date"] = "2026-10-28"
    clt.sweep_tick(datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc))
    assert len(_late_mail(db)) == 1


def test_a_leader_told_today_hears_first(db):
    _t(db, T_LATE)["leader_told_at"] = "2026-10-28T13:00:00+00:00"    # 8 AM today, Chicago
    clt.sweep_tick(NOW)
    assert not _late_mail(db) and _t(db, T_LATE)["late_told_at"] is None


def test_a_group_leader_with_no_role_above_has_no_one_to_tell(db):
    _t(db, T_TASHA)["due_date"] = "2026-10-26"
    stats = clt.sweep_tick(NOW)
    assert stats["late_no_one"] == 1 and not [m for m in _late_mail(db) if "Tasha" in m["subject"]]
    assert _t(db, T_TASHA)["late_told_at"], "set, so it's never asked again"


def test_a_late_email_that_fails_lets_the_claim_go(db):
    db.fail_to = {"kevin@lovecity.org"}
    assert clt.sweep_tick(NOW)["late_unsent"] == 1 and _t(db, T_LATE)["late_told_at"] is None
    db.fail_to = set()
    assert clt.sweep_tick(NOW)["late"] == 1


def test_the_overseer_is_the_nearest_held_role_above(db):
    import church_follow_up as cfu
    import church_roles as cr
    roles = cfu.roles(BIZ)
    defs = cfu._effective_defs(cr.defs(BIZ), roles)
    role, people = clt.overseer(RAY, roles, defs)
    assert role["title"] == "Lead Pastor" and [p["contact_id"] for p in people] == [KEVIN]
    db.t["church_leader_roles"].append(_role(DANA, "associate"))
    roles = cfu.roles(BIZ)
    role, people = clt.overseer(RAY, roles, defs)
    assert role["title"] == "Associate Pastor" and [p["contact_id"] for p in people] == [DANA]
    assert clt.overseer(KEVIN, roles, defs) == (None, []), "the Lead Pastor answers to no one here"
    assert clt.overseer(TASHA, roles, defs) == (None, []), "a group leader with no role"


# ─── The Board's "Make tasks" ─────────────────────────────────────────

@pytest.fixture
def board(monkeypatch):
    """The Board tests' church and in-memory tables (test_church_board's
    own fixture, set up here: a module's fixtures are its own)."""
    from zoneinfo import ZoneInfo
    import church_board as cb
    import test_church_board as tb
    fake = tb.BoardDB(
        businesses=[{"id": tb.BIZ, "name": "Love City Church", "type": "ministry", "owner_id": tb.ID["owner"],
                     "settings": {}}],
        business_users=[{"business_id": tb.BIZ, "user_id": tb.ID["deacon"], "role": "member", "status": "active",
                         "invited_email": "deacon@lovecity.org"}],
        contacts=[{"id": tb.HAYES, "business_id": tb.BIZ, "name": "Darnell Hayes", "email": "deacon@lovecity.org"},
                  {"id": tb.MOORE, "business_id": tb.BIZ, "name": "Dana Moore", "email": "dana.moore@example.com"},
                  {"id": tb.PRICE, "business_id": tb.BIZ, "name": "Noah Price", "email": None}],
        church_boards=[], church_board_members=[], church_board_meetings=[], church_board_items=[],
        church_board_attendance=[], church_board_decisions=[], tasks=[],
    )
    fake.missing = False
    fake.tasks_fail = False
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    monkeypatch.setenv("CHURCH_BOARD", "on")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@lovecity.org")
    monkeypatch.setattr(cb, "_now", lambda: tb.T0)
    monkeypatch.setattr(cb, "_tz", lambda biz: ZoneInfo("America/New_York"))
    monkeypatch.setattr(cb, "owner_email", lambda uid: "owner@lovecity.org")
    return fake


def _make_tasks(board):
    import test_church_board as tb
    b, ids = tb._deacons()
    m = tb._meeting(b["id"])["meeting"]
    van = tb._item(m["id"], "Van insurance")
    bids = tb._item(m["id"], "Get a third roof bid")
    tb.ok(tb._patch_item(van["id"], status="follow_up", follow_up_member=ids["hayes"], follow_up_due="2026-11-05"))
    tb.ok(tb._patch_item(bids["id"], status="follow_up", follow_up_member=ids["moore"], follow_up_due="2026-11-15"))
    assert tb.ok(tb.client("owner").post(f"/church/board/meetings/{m['id']}/tasks", json={"business_id": tb.BIZ}))["made"] == 2
    return {t["title"]: t for t in board.t["tasks"]}


@pytest.mark.parametrize("switch", ["on", "owner"])
def test_the_boards_follow_up_goes_to_a_no_login_member_as_a_leader(board, monkeypatch, switch):
    import test_church_board as tb
    monkeypatch.setenv("CHURCH_LEADER_TASKS", switch)      # owner: owner@lovecity.org is the platform owner here
    by = _make_tasks(board)
    roof = by["Get a third roof bid"]
    assert roof["assigned_contact_id"] == tb.MOORE and roof["assigned_to"] is None and roof["due_date"] == "2026-11-15"
    assert roof["handed_by"] == tb.ID["owner"], "late, with no one above them, it comes back to who made it"
    van = by["Van insurance"]
    assert van["assigned_to"] == tb.ID["deacon"] and "assigned_contact_id" not in van, "a login stays a login"


@pytest.mark.parametrize("closed", ["off", "not migrated"])
def test_with_the_switch_off_or_no_migration_the_board_makes_tasks_as_before(board, monkeypatch, closed):
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "on")
    if closed == "off":
        monkeypatch.setenv("CHURCH_LEADER_TASKS", "off")
    else:
        monkeypatch.setattr(clt, "ready", lambda b: False)
    by = _make_tasks(board)
    roof = by["Get a third roof bid (Dana Moore)"]
    assert roof["assigned_to"] is None and "assigned_contact_id" not in roof


# ─── Before the migration ─────────────────────────────────────────────

def test_before_the_migration_everything_is_quiet(db, office, shell):
    db.migrated = False
    assert "leaders" not in _people(office), "no Leaders group"
    html, status = _page(_me(RAY, "Ray Dunn"), "/my/lead")
    assert status == 200 and "/my/lead/tasks" not in html, "no Tasks in the switcher"
    html, status = _page(_me(RAY, "Ray Dunn"))
    assert status == 503 and "couldn’t load" in html, "the page itself says so, never a 500"
    assert clt.sweep_tick(NOW)["told"] == 0 and not db.sent
    assert clt.section(CHURCH, RAY) is None and not clt.ready(BIZ)


# ─── Who handed it (APPLY-2026-10-27-task-handed-by.sql) ─────────────

SARAH = "44444444-4444-4444-8444-444444444444"
LEFT = "55555555-5555-4555-8555-555555555555"


def _office_login(db):
    """Sarah, the church administrator: an office login, on the church's list
    by her sign-in email."""
    db.t["business_users"].append({"business_id": BIZ, "user_id": SARAH, "role": "manager", "status": "active",
                                   "invited_email": "sarah@lovecity.org"})
    db.t["contacts"].append({"id": "c0000000-0000-4000-8000-000000000009", "business_id": BIZ,
                             "name": "Sarah Office", "email": "sarah@lovecity.org"})


def test_a_late_task_with_no_one_above_goes_back_to_whoever_handed_it(db):
    _office_login(db)
    _t(db, T_TASHA).update(due_date="2026-10-26", handed_by=SARAH)
    stats = clt.sweep_tick(NOW)
    back = [m for m in _late_mail(db) if "Tasha" in m["subject"]]
    assert stats["late_no_one"] == 0 and len(back) == 1
    m = back[0]
    assert m["to"] == "sarah@lovecity.org" and m["subject"] == "Tasha Williams has a task past due"
    assert "Hi Sarah" in m["html"] and "you handed it to Tasha" in m["html"] and "Call the caterer" in m["html"]
    assert _t(db, T_TASHA)["late_told_at"] == "2026-10-28T14:00:00+00:00"
    clt.sweep_tick(NOW)
    assert len([m for m in _late_mail(db) if "Tasha" in m["subject"]]) == 1, "once"


def test_the_owner_who_handed_it_hears_at_their_sign_in_email(db, monkeypatch):
    import messaging_router
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: "pastor@lovecity.org" if uid == OWNER else "")
    _t(db, T_TASHA).update(due_date="2026-10-26", handed_by=OWNER)
    clt.sweep_tick(NOW)
    back = [m for m in _late_mail(db) if "Tasha" in m["subject"]]
    assert [m["to"] for m in back] == ["pastor@lovecity.org"]
    assert "Hi friend" in back[0]["html"], "the owner with no name on the list"


def test_a_leader_with_someone_above_still_goes_up_not_back(db):
    _office_login(db)
    _t(db, T_LATE)["handed_by"] = SARAH
    clt.sweep_tick(NOW)
    assert [m["to"] for m in _late_mail(db)] == ["kevin@lovecity.org"]


def test_whoever_handed_it_has_left_so_no_one_is_told(db):
    _t(db, T_TASHA).update(due_date="2026-10-26", handed_by=LEFT)
    stats = clt.sweep_tick(NOW)
    assert stats["late_no_one"] == 1 and not [m for m in _late_mail(db) if "Tasha" in m["subject"]]
    assert _t(db, T_TASHA)["late_told_at"], "set, so it's never asked again"


def test_the_leader_sees_and_hears_who_handed_it(db):
    _office_login(db)
    _t(db, T_SOON)["handed_by"] = SARAH
    by = {i["title"]: i["from"] for i in clt.mine(CHURCH, RAY, NOW)["open"]}
    assert by["Order the youth shirts"] == "Sarah Office"
    assert by["Plan the fall retreat"] == "the church office", "no hander recorded"
    _fresh(db, "71000000-0000-4000-8000-000000000009", RAY, "Lead the youth retreat", handed_by=SARAH)
    clt.sweep_tick(NOW)
    assert "Sarah Office handed you a task: Lead the youth retreat." in _handed_mail(db)[0]["html"]


def test_names_that_cant_be_read_fall_back_to_the_church_office(db, monkeypatch):
    import church_my_week
    from fastapi import HTTPException

    def down(*a, **kw):
        raise HTTPException(503, "Your week couldn't be read just now. Try again.")
    monkeypatch.setattr(church_my_week, "people", down)
    _t(db, T_SOON)["handed_by"] = SARAH
    assert {i["from"] for i in clt.mine(CHURCH, RAY, NOW)["open"]} == {"the church office"}
