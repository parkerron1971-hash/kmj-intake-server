"""Church assignments (church_assignments.py, church_startup.py,
church_work_checks.py; docs/CHURCH_ASSIGNMENTS.md, PR A). Kevin, 2026-11-11:
"we also need to allow for Jessica to be able to hand out assignments to each
of them as well", "allow for the admin to pick days for work load that works
for them", and "this needs to be a way for churches to set this up in a
general sense when they establish leaders over people."

Pins, at the test churches (church_three), through the real routes:
  * hand one out: Grace's pastor to its secretary's login; a department
    overseer (with a login) to that department's leader; to yourself; someone
    over no one, or over someone else, gets a 403; never a money job to a
    Manager; every write answers with what it saved
  * a first assignment: from the jobs a login does of its own (the
    Executive Pastor's lane is its own two, never the whole office it
    covers; a money lane has none) or a person's switches; made once per
    item, again makes only what's new; one at a time when the bulk insert is
    refused
  * checks: a passed check ticks its item off on read and in the sweep, done
    by no one; evidence only never ticks; a check that can't read changes
    nothing
  * stuck, sent up, told once by the sweep; un-stuck clears it; done and
    undone; the date only by whoever is over them; taken back
  * the board: each person under me with counts and n of m; nobody under
    me is an empty list; read in a few reads for the whole church
  * picked days: read by My week's rhythm and the team page; Sunday jobs and
    the first-Monday report don't move; the login or anyone over it
  * the grouped hand-off tell: one email and one push for a first
    assignment, to a login and to a person; closed, one a task as before
  * the switch; another church's task is a 404; the migration and templates
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_assignments as cas  # noqa: E402
import church_duties as cd  # noqa: E402
import church_leader_tasks as clt  # noqa: E402
import church_my_week as mw  # noqa: E402
import church_office_tasks as cot  # noqa: E402
import church_over as co  # noqa: E402
import church_startup as cs  # noqa: E402
import church_team_week as ctw  # noqa: E402
import church_three as c3  # noqa: E402
import church_work_checks as cw  # noqa: E402
import sb_clients  # noqa: E402
from church_three import GRACE, LOVE_CITY, NEW_HOPE  # noqa: E402

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)      # Thursday, 10 AM in Detroit
TODAY = date(2026, 11, 12)
MONEY = re.compile(r"amount|cents|fee|giving|gift|fund|deposit|bank|price|pledge|donat|payout|total")


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "on")
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "on")
    d = c3.build(monkeypatch)
    real_post = d.post

    def post(path, body, prefer=None, **kw):
        if path.startswith("/church_duty_days"):              # upsert on the primary key, as PostgREST does it
            have = d.t.setdefault("church_duty_days", [])
            old = next((r for r in have if all(r[k] == body[k] for k in ("business_id", "user_id", "duty"))), None)
            if old:
                old.update(body)
                return [dict(old)]
            have.append(dict(body))
            return [dict(body)]
        if path.startswith("/tasks"):                          # tasks_startup_once, as the index holds it
            rows = body if isinstance(body, list) else [body]
            for r in rows:
                if r.get("startup_key") and any(
                        t.get("startup_key") == r["startup_key"] and t["business_id"] == r["business_id"]
                        and (t.get("assigned_to") or t.get("assigned_contact_id"))
                        == (r.get("assigned_to") or r.get("assigned_contact_id")) for t in d.t["tasks"]):
                    return None
            rows = [dict(r, created_at=r.get("created_at") or NOW.isoformat()) for r in rows]
            body = rows if isinstance(body, list) else rows[0]
        return real_post(path, body, prefer, **kw)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    d.post = post
    monkeypatch.setattr(clt, "zone", lambda b: ZoneInfo(((b or {}).get("settings") or {}).get("timezone") or "UTC"))
    monkeypatch.setattr(cas, "_now", lambda: NOW)
    monkeypatch.setattr(mw, "_now", lambda: NOW)
    import chief_assignments
    monkeypatch.setattr(chief_assignments, "_tz_for", lambda b: ZoneInfo(
        next(x for x in d.t["businesses"] if x["id"] == b)["settings"]["timezone"]))
    d.sent, d.pushes, d.fail_to = [], [], set()

    def deliver(biz, to, name, subject, html, key, reply_to=None):
        if to in d.fail_to:
            raise RuntimeError("Resend said no")
        d.sent.append({"to": to, "name": name, "subject": subject, "html": html, "key": key})
    monkeypatch.setattr(clt, "deliver", deliver)
    import push_notifications
    monkeypatch.setattr(push_notifications, "send_to_user", lambda uid, **kw: d.pushes.append({"to": uid, **kw}) or 1)
    return d


@pytest.fixture
def app(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    a = FastAPI()
    a.include_router(cas.router)
    who = {"id": None, "email": None}
    a.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"], email=who["email"], user_metadata={})))
    c = TestClient(a)
    c.who, c.db = who, db
    return c


def uid(db, biz, handle):
    return c3.church(db, biz)["owner_id"] if handle == "owner" else db.who[biz][handle + "@"]


def as_(app, biz, handle):
    u = uid(app.db, biz, handle)
    seat = next((s for s in app.db.t["business_users"] if s["user_id"] == u), None)
    app.who.update(id=u, email=seat["invited_email"] if seat else c3.OWNER_EMAIL[u])


def give(app, biz, for_, **kw):
    return app.post("/church/assignments", json={"business_id": biz, "for": for_, **kw})


def start(app, biz, for_):
    return app.post("/church/assignments/start", json={"business_id": biz, "for": for_})


def login(db, biz, handle):
    return f"login:{uid(db, biz, handle)}"


def person(db, biz, handle):
    return f"person:{db.who[biz][handle]}"


def task(db, tid):
    return next(t for t in db.t["tasks"] if t["id"] == tid)


def mine(app, biz, for_=None):
    q = f"/church/assignments?business_id={biz}" + (f"&for={for_}" if for_ else "")
    r = app.get(q)
    assert r.status_code == 200, r.text
    return r.json()


# ─── Handing one out ──────────────────────────────────────────────────

def test_grace_the_pastor_hands_the_secretary_an_assignment(app, db):
    as_(app, GRACE, "owner")
    r = give(app, GRACE, login(db, GRACE, "sharon"), title="Order the new hymnals", due_date="2026-11-20",
             done_when="They're in the pews", duty="supplies")
    assert r.status_code == 200, r.text
    s = r.json()["saved"]
    assert (s["title"], s["due"], s["done_when"], s["duty"], s["duty_label"], s["from"], s["status"]) == (
        "Order the new hymnals", "2026-11-20", "They're in the pews", "supplies", "Supplies", "Pastor Gray", "open")
    row = task(db, s["id"])
    assert row["assigned_to"] == uid(db, GRACE, "sharon") and row["assigned_contact_id"] is None
    assert row["handed_by"] == c3.G_OWNER and row["business_id"] == GRACE
    as_(app, GRACE, "sharon")
    page = mine(app, GRACE)
    assert page["mine"] is True and page["can_change"] is False
    assert [i["title"] for i in page["open"]] == ["Order the new hymnals"] and page["open"][0]["from"] == "Pastor Gray"


def test_a_department_overseer_hands_that_departments_leader_one(app, db):
    daniel = "2a000000-0000-4000-8000-000000000077"
    db.t["business_users"].append({"business_id": GRACE, "user_id": daniel, "role": "manager",
                                   "invited_email": "daniel@gracebaptist.org", "lane": None, "areas": ["kids_youth"],
                                   "contact_id": db.who[GRACE]["daniel"], "name": "Daniel Moore", "status": "active"})
    app.who.update(id=daniel, email="daniel@gracebaptist.org")
    r = give(app, GRACE, person(db, GRACE, "yvette"), title="Plan the youth retreat", due_date="2026-12-01")
    assert r.status_code == 200, r.text
    row = task(db, r.json()["saved"]["id"])
    assert row["assigned_contact_id"] == db.who[GRACE]["yvette"] and row["handed_by"] == daniel
    board = app.get(f"/church/assignments/people?business_id={GRACE}").json()
    [yv] = board["people"]
    assert (yv["name"], yv["why"], yv["open"], yv["late"]) == ("Yvette Long", "Leads Youth", 2, 1)


def test_someone_over_no_one_or_over_someone_else_gets_a_403(app, db):
    as_(app, GRACE, "sharon")
    assert give(app, GRACE, login(db, GRACE, "thelma"), title="x").status_code == 403
    r = give(app, GRACE, person(db, GRACE, "yvette"), title="x")
    assert r.status_code == 403 and r.json()["detail"] == cas.NOT_OVER
    as_(app, LOVE_CITY, "naiya")
    assert give(app, LOVE_CITY, login(db, LOVE_CITY, "tiara"), title="x").status_code == 403
    as_(app, LOVE_CITY, "jessica")
    for target in (login(db, LOVE_CITY, "minnie"), login(db, LOVE_CITY, "owner"),
                   "login:a9000000-0000-4000-8000-000000000009", person(db, GRACE, "yvette")):
        assert give(app, LOVE_CITY, target, title="x").status_code == 403, target
    as_(app, GRACE, "owner")
    assert give(app, GRACE, person(db, LOVE_CITY, "yolanda"), title="x").status_code == 403, "another church's person"
    assert not [t for t in db.t["tasks"] if t.get("title") == "x"], "nothing saved on a refusal"


def test_you_can_hand_yourself_one(app, db):
    as_(app, LOVE_CITY, "naiya")
    r = give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="Count the chairs")
    assert r.status_code == 200 and r.json()["saved"]["from"] == "Naiya Clark"


def test_what_a_hand_out_refuses(app, db):
    as_(app, LOVE_CITY, "jessica")
    naiya = login(db, LOVE_CITY, "naiya")
    assert give(app, LOVE_CITY, naiya, title="").status_code == 400
    assert give(app, LOVE_CITY, naiya, title="x" * 201).status_code == 400
    assert give(app, LOVE_CITY, naiya, title="ok", due_date="next friday").status_code == 400
    assert give(app, LOVE_CITY, naiya, title="ok", duty="not_a_job").status_code == 400
    r = give(app, LOVE_CITY, naiya, title="ok", duty="deposit")
    assert r.status_code == 400 and "money job" in r.json()["detail"]
    assert give(app, LOVE_CITY, "naiya", title="ok").status_code == 400


def test_a_write_that_fails_is_a_503_never_a_200(app, db, monkeypatch):
    as_(app, LOVE_CITY, "jessica")
    real = sb_clients.sb_post_as_service
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, *a, **k: None if path.startswith("/tasks") else real(path, body, *a, **k))
    assert give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="ok").status_code == 503


# ─── A first assignment ───────────────────────────────────────────────

def test_a_first_assignment_is_made_from_the_jobs_they_hold_once(app, db):
    as_(app, LOVE_CITY, "jessica")
    r = start(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"))
    assert r.status_code == 200, r.text
    got = r.json()
    keys = [t["key"] for t in cs.TEMPLATES if t["duty"] in cd.STARTER["office_leadership"]]
    assert (got["of"], got["skipped"], len(got["made"])) == (len(keys), 0, len(keys)) and 5 <= len(keys) <= 9
    rows = [t for t in db.t["tasks"] if t.get("startup_key")]
    assert sorted(t["startup_key"] for t in rows) == sorted(keys)
    for t in rows:
        tpl = cs.BY_KEY[t["startup_key"]]
        assert t["assigned_to"] == uid(db, LOVE_CITY, "naiya") and t["handed_by"] == uid(db, LOVE_CITY, "jessica")
        assert t["due_date"] == (TODAY + timedelta(weeks=tpl["week"])).isoformat()
        assert (t["duty"], t["done_when"], t["check_key"]) == (tpl["duty"], tpl["done_when"], tpl["check"])
    again = start(app, LOVE_CITY, login(db, LOVE_CITY, "naiya")).json()
    assert (again["made"], again["skipped"], again["of"]) == ([], len(keys), len(keys))
    assert len([t for t in db.t["tasks"] if t.get("startup_key")]) == len(keys)


def test_the_executive_pastors_own_is_two_never_the_whole_office_and_a_money_lane_has_none(app, db):
    as_(app, LOVE_CITY, "owner")
    jess = start(app, LOVE_CITY, login(db, LOVE_CITY, "jessica")).json()
    assert sorted(t["title"] for t in jess["made"]) == ["A first one-on-one with each",
                                                         "Start each office login's first assignment"]
    minnie = start(app, LOVE_CITY, login(db, LOVE_CITY, "minnie")).json()
    assert minnie["of"] == 0 and minnie["made"] == []
    assert all(not cd.CATALOG[t["duty"]]["money"] for t in cs.TEMPLATES if t["duty"] in cd.CATALOG)


def test_grace_a_secretary_who_does_everything_gets_every_office_item(app, db):
    as_(app, GRACE, "owner")
    got = start(app, GRACE, login(db, GRACE, "sharon")).json()
    assert got["of"] == len([t for t in cs.TEMPLATES if t["duty"] in cd.CATALOG])


def test_a_persons_first_assignment_comes_from_their_switches(app, db):
    as_(app, LOVE_CITY, "owner")
    c = co.Church(c3.church(db, LOVE_CITY))
    got = start(app, LOVE_CITY, person(db, LOVE_CITY, "yolanda")).json()
    want = [t["key"] for t in cs.for_person(c, db.who[LOVE_CITY]["yolanda"])]
    assert "lead.people" in want and sorted(cs.BY_KEY[k]["key"] for k in want) == sorted(
        t["startup_key"] for t in db.t["tasks"] if t.get("startup_key"))
    assert len(got["made"]) == len(want)
    assert all(t["assigned_contact_id"] == db.who[LOVE_CITY]["yolanda"] and t["assigned_to"] is None
               for t in db.t["tasks"] if t.get("startup_key"))
    # A group leader with no role leads (her group), and oversees nothing.
    assert cs.switches(c, db.who[LOVE_CITY]["gloria"]) == ["lead"]


def test_only_someone_over_them_starts_them(app, db):
    as_(app, LOVE_CITY, "naiya")
    assert start(app, LOVE_CITY, login(db, LOVE_CITY, "tiara")).status_code == 403
    as_(app, LOVE_CITY, "jessica")
    assert start(app, LOVE_CITY, login(db, LOVE_CITY, "jessica")).status_code == 403, "not yourself"


def test_a_bulk_insert_refused_goes_one_at_a_time(app, db, monkeypatch):
    as_(app, LOVE_CITY, "jessica")
    real = sb_clients.sb_post_as_service
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, *a, **k: None if isinstance(body, list) else real(path, body, *a, **k))
    got = start(app, LOVE_CITY, login(db, LOVE_CITY, "naiya")).json()
    assert len(got["made"]) == got["of"] == 6


# ─── Checks ───────────────────────────────────────────────────────────

def test_a_passed_check_ticks_its_item_off_on_read_done_by_no_one(app, db):
    as_(app, LOVE_CITY, "jessica")
    start(app, LOVE_CITY, login(db, LOVE_CITY, "tiara"))
    page = mine(app, LOVE_CITY, login(db, LOVE_CITY, "tiara"))
    done = {i["title"]: i for i in page["done"]}
    # Love City: everyone in follow-up has someone; both groups have a leader.
    assert set(done) == {"Every first-time guest has a caller", "Every group has a leader"}
    assert all(i["checked"] and i["completed_at"] for i in done.values())
    assert page["first"] == {"done": 2, "of": 6, "to_make": 0} and page["can_change"] is True
    row = next(t for t in db.t["tasks"] if t.get("startup_key") == "groups.leaders")
    assert row["status"] == "done" and row["checked_at"] and not row.get("done_by_contact_id")


def test_evidence_only_never_ticks_and_an_unread_check_changes_nothing(app, db, monkeypatch):
    as_(app, LOVE_CITY, "jessica")
    start(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"))
    rooms = next(i for i in mine(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"))["open"] if i["title"].startswith("Every room"))
    assert rooms["check"] == {"done": None, "text": "No rooms listed yet"}
    db.t["church_spaces"] = [{"id": f"s{i}", "business_id": LOVE_CITY, "name": n, "kind": "room", "active": True}
                             for i, n in enumerate(("Sanctuary", "Fellowship Hall"))]
    rooms = next(i for i in mine(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"))["open"] if i["title"].startswith("Every room"))
    assert rooms["check"] == {"done": None, "text": "2 rooms listed"} and rooms["status"] == "open"
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("groups?") else real(path, **kw))
    start(app, LOVE_CITY, login(db, LOVE_CITY, "tiara"))
    page = mine(app, LOVE_CITY, login(db, LOVE_CITY, "tiara"))
    groups = next(i for i in page["open"] if i["title"] == "Every group has a leader")
    assert groups["check"] == {"done": None, "text": cw.UNREAD_TEXT} and groups["status"] == "open"


def test_the_sweep_ticks_what_passes(app, db):
    as_(app, LOVE_CITY, "jessica")
    start(app, LOVE_CITY, login(db, LOVE_CITY, "tiara"))
    stats = cas.sweep_tick(NOW)
    assert stats["ticked"] == 2
    assert {t["startup_key"] for t in db.t["tasks"] if t.get("checked_at")} == {"first_guests.callers", "groups.leaders"}
    assert cas.sweep_tick(NOW)["ticked"] == 0


def test_the_checks_count_what_the_church_keeps(db):
    ctx = lambda: cw.Ctx(c3.church(db, LOVE_CITY), NOW)  # noqa: E731
    assert cw.run(ctx(), "departments_led") == {"key": "departments_led", "done": True,
                                                "text": "3 of 3 departments have a leader"}
    assert cw.run(ctx(), "kids_checked") == {"key": "kids_checked", "done": None,
                                             "text": "No kids leaders approved yet"}
    # Every approved kids leader has a date by the table's own rule, and a youth
    # leader isn't a kids worker: it's evidence, never a tick (#1801 review).
    db.t["space_leaders"] = [{"business_id": LOVE_CITY, "contact_id": "k1", "space": "kids",
                              "background_check_on": "2026-01-01"},
                             {"business_id": LOVE_CITY, "contact_id": "k2", "space": "kids",
                              "background_check_on": "2026-09-01"},
                             {"business_id": LOVE_CITY, "contact_id": "y1", "space": "youth",
                              "background_check_on": "2026-09-01"},
                             {"business_id": GRACE, "contact_id": "g1", "space": "kids",
                              "background_check_on": "2026-09-01"}]
    assert cw.run(ctx(), "kids_checked") == {"key": "kids_checked", "done": None,
                                             "text": "2 kids leaders approved with a background check date"}
    assert cw.run(cw.Ctx(c3.church(db, GRACE), NOW), "kids_checked")["done"] is None
    assert "kids_checked" in cw.EVIDENCE and "rooms_listed" in cw.EVIDENCE and "kids_checked" not in cw.PASSABLE
    db.t["worship_team"] = [{"business_id": LOVE_CITY, "status": "active"}, {"business_id": LOVE_CITY, "status": "invited"}]
    assert cw.run(ctx(), "churchsavvy_joined")["text"] == "1 joined, 1 still invited"
    db.t["worship_team"][1]["status"] = "active"
    assert cw.run(ctx(), "churchsavvy_joined")["done"] is True
    sundays = [date(2026, 11, 8) - timedelta(weeks=i) for i in range(6)]
    db.t["sermons"] = [{"business_id": LOVE_CITY, "published": True, "preached_on": d.isoformat()} for d in sundays[:5]]
    assert cw.run(ctx(), "sermons_6") == {"key": "sermons_6", "done": False,
                                          "text": "5 of the last 6 Sundays have their sermon posted"}
    db.t["sermons"].append({"business_id": LOVE_CITY, "published": True, "preached_on": sundays[5].isoformat()})
    assert cw.run(ctx(), "sermons_6")["done"] is True
    youth = next(g["id"] for g in db.t["groups"] if g["business_id"] == LOVE_CITY and g["name"] == "Youth")
    db.t["serve_teams"] = [{"business_id": LOVE_CITY, "group_id": youth, "owner": "volunteers"},
                           {"business_id": LOVE_CITY, "group_id": "no-leader", "owner": "volunteers"},
                           {"business_id": LOVE_CITY, "group_id": "x", "owner": "churchsavvy"}]
    assert cw.run(ctx(), "serve_teams_led")["text"] == "1 of 2 volunteer teams have a leader"
    monday = date(2026, 11, 9)
    db.t["worship_services"] = [{"id": f"w{i}", "business_id": LOVE_CITY, "title": "Sunday", "archived_at": None,
                                 "is_template": False,
                                 "starts_at": datetime.combine(monday + timedelta(weeks=i, days=6), datetime.min.time(),
                                                               tzinfo=timezone.utc).replace(hour=15).isoformat()}
                                for i in range(3)]
    assert cw.run(ctx(), "calendar_8_weeks") == {"key": "calendar_8_weeks", "done": False,
                                                 "text": "3 of the next 8 weeks have something on the calendar"}
    db.t["worship_services"] += [dict(db.t["worship_services"][0], id=f"v{i}",
                                      starts_at=(datetime(2026, 11, 15, 15, tzinfo=timezone.utc)
                                                 + timedelta(weeks=i)).isoformat()) for i in range(8)]
    assert cw.run(ctx(), "calendar_8_weeks")["done"] is True
    db.t["events"] = [{"business_id": LOVE_CITY, "event_type": "sms_broadcast", "created_at": "2026-11-10T15:00:00+00:00",
                       "data": {"sent": 40}}]
    assert cw.run(ctx(), "weekly_text")["done"] is True
    assert cw.run(ctx(), "not_a_check") is None


# ─── Stuck, sent up, done ─────────────────────────────────────────────

def _rooms_item(app, db):
    as_(app, LOVE_CITY, "jessica")
    start(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"))
    return next(t for t in db.t["tasks"] if t.get("startup_key") == "rooms.listed")


def patch(app, tid, biz, **body):
    return app.patch(f"/church/assignments/{tid}", json={"business_id": biz, **body})


def test_stuck_and_sent_up_is_told_once(app, db):
    t = _rooms_item(app, db)
    as_(app, LOVE_CITY, "naiya")
    r = patch(app, t["id"], LOVE_CITY, stuck="Waiting on the floor plan")
    assert r.status_code == 200 and r.json()["saved"]["status"] == "stuck"
    assert r.json()["saved"]["stuck"]["note"] == "Waiting on the floor plan"
    assert patch(app, t["id"], LOVE_CITY, due_date="2026-12-01").status_code == 403, "only the one over her"
    assert app.post(f"/church/assignments/{t['id']}/raise", json={"business_id": LOVE_CITY}).status_code == 403
    as_(app, LOVE_CITY, "jessica")
    assert patch(app, t["id"], LOVE_CITY, due_date="2026-12-01").json()["saved"]["due"] == "2026-12-01"
    r = app.post(f"/church/assignments/{t['id']}/raise", json={"business_id": LOVE_CITY, "note": "Need the pastor's plan"})
    assert r.status_code == 200, r.text
    assert r.json()["to"] == {"kind": "login", "id": c3.LC_OWNER, "name": "Pastor Kevin"}
    assert r.json()["saved"]["raised"]["to"] == "Pastor Kevin" and r.json()["saved"]["stuck"]["note"] == "Need the pastor's plan"
    row = task(db, t["id"])
    assert row["raised_to"] == c3.LC_OWNER and row["raised_by"] == uid(db, LOVE_CITY, "jessica")
    stats = cas.sweep_tick(NOW)
    [mail] = [m for m in db.sent if m["key"].startswith("assignment-raised-")]
    assert stats["raised_told"] == 1 and mail["to"] == c3.PLATFORM
    assert "Jessica McCloud" in mail["html"] and "Naiya Clark" in mail["html"] and "the pastor" in mail["html"]
    assert [p["to"] for p in db.pushes] == [c3.LC_OWNER]
    cas.sweep_tick(NOW)
    assert len([m for m in db.sent if m["key"].startswith("assignment-raised-")]) == 1, "told once"
    as_(app, LOVE_CITY, "owner")
    up = mine(app, LOVE_CITY)["raised_to_you"]
    assert [(i["title"], i["whose"], i["resolved"], i["raised"]["to"]) for i in up] == [
        ("Every room in the system", "Naiya Clark", False, "Pastor Kevin")]
    r = app.post(f"/church/assignments/{t['id']}/raise", json={"business_id": LOVE_CITY})
    assert r.status_code == 409, "nobody is over the owner"


def _sent_up(app, db):
    t = _rooms_item(app, db)
    r = app.post(f"/church/assignments/{t['id']}/raise", json={"business_id": LOVE_CITY, "note": "Floor plan"})
    assert r.status_code == 200, r.text
    return t


def test_before_its_sent_up_the_assignee_marks_and_clears_stuck(app, db):
    t = _rooms_item(app, db)
    as_(app, LOVE_CITY, "naiya")
    assert patch(app, t["id"], LOVE_CITY, stuck="Waiting").json()["saved"]["status"] == "stuck"
    cleared = patch(app, t["id"], LOVE_CITY, stuck=None).json()["saved"]
    assert cleared["status"] == "open" and cleared["stuck"] is None
    assert patch(app, t["id"], LOVE_CITY, done="yes").status_code == 400


def test_once_its_sent_up_the_assignee_cant_clear_it_and_the_one_over_them_can(app, db):
    """Kevin's call (#1801 review): the person over them is in control."""
    t = _sent_up(app, db)
    as_(app, LOVE_CITY, "naiya")
    r = patch(app, t["id"], LOVE_CITY, stuck=None)
    assert r.status_code == 403 and r.json()["detail"] == cas.SENT_UP
    assert patch(app, t["id"], LOVE_CITY, stuck="It's fine now").status_code == 403, "nor rewrite the note"
    row = task(db, t["id"])
    assert row["stuck_at"] and row["raised_to"] == c3.LC_OWNER and row["stuck_note"] == "Floor plan"
    as_(app, LOVE_CITY, "jessica")                                   # sent it up, and over her
    cleared = patch(app, t["id"], LOVE_CITY, stuck=None).json()["saved"]
    assert cleared["status"] == "open" and cleared["raised"] is None and task(db, t["id"])["raised_at"] is None


def test_whoever_it_went_to_can_clear_it(app, db):
    t = _sent_up(app, db)
    as_(app, LOVE_CITY, "owner")
    assert patch(app, t["id"], LOVE_CITY, stuck=None).json()["saved"]["status"] == "open"


def test_done_still_works_for_the_assignee_and_whoever_it_went_to_sees_it_resolved(app, db):
    t = _sent_up(app, db)
    as_(app, LOVE_CITY, "naiya")
    assert patch(app, t["id"], LOVE_CITY, done=True).json()["saved"]["status"] == "done"
    row = task(db, t["id"])
    assert row["completed_at"] and row["raised_to"] == c3.LC_OWNER, "done closes it; the record stays"
    as_(app, LOVE_CITY, "owner")
    [up] = mine(app, LOVE_CITY)["raised_to_you"]
    assert (up["title"], up["status"], up["resolved"], up["whose"]) == (
        "Every room in the system", "done", True, "Naiya Clark")
    week = mw.build(c3.church(db, LOVE_CITY), c3.LC_OWNER, c3.PLATFORM, "owner")
    lines = [n for n in [week["next"]] + week["needs"] if n and n["kind"].startswith("raised")]
    assert [(n["kind"], n["title"]) for n in lines] == [
        ("raised_done", "“Every room in the system” was sent up to you, and it's done now.")]
    assert cas.sweep_tick(NOW)["raised_told"] == 0, "nothing to tell about a done one"
    as_(app, LOVE_CITY, "naiya")
    assert patch(app, t["id"], LOVE_CITY, done=False).json()["saved"]["status"] == "stuck", "reopened, still stuck"


def test_someone_who_isnt_them_over_them_or_on_its_way_up_changes_nothing(app, db):
    t = _sent_up(app, db)
    as_(app, LOVE_CITY, "tiara")
    for body in ({"done": True}, {"stuck": None}, {"title": "x"}):
        assert patch(app, t["id"], LOVE_CITY, **body).status_code == 403, body


def test_what_was_sent_up_shows_on_their_my_week(app, db):
    t = _rooms_item(app, db)
    app.post(f"/church/assignments/{t['id']}/raise", json={"business_id": LOVE_CITY, "note": "Floor plan"})
    week = mw.build(c3.church(db, LOVE_CITY), c3.LC_OWNER, c3.PLATFORM, "owner")
    raised = [n for n in [week["next"]] + week["needs"] if n and n["kind"] == "raised"]
    assert raised and raised[0]["title"] == "“Every room in the system” is stuck and was sent up to you."
    assert raised[0]["detail"] == "Floor plan"


def test_taking_one_back(app, db):
    as_(app, LOVE_CITY, "jessica")
    tid = give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="Book the hall").json()["saved"]["id"]
    as_(app, LOVE_CITY, "naiya")
    assert app.delete(f"/church/assignments/{tid}?business_id={LOVE_CITY}").status_code == 403
    as_(app, LOVE_CITY, "jessica")
    r = app.delete(f"/church/assignments/{tid}?business_id={LOVE_CITY}")
    assert r.status_code == 200 and r.json()["taken_back"]["title"] == "Book the hall"
    assert not [t for t in db.t["tasks"] if t["id"] == tid]
    tid = give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="Order paper").json()["saved"]["id"]
    as_(app, LOVE_CITY, "owner")
    assert app.delete(f"/church/assignments/{tid}?business_id={LOVE_CITY}").status_code == 200, "anyone over her"


def test_another_churchs_task_is_a_404_whoever_asks(app, db):
    grace_task = next(t["id"] for t in db.t["tasks"] if t["business_id"] == GRACE)
    as_(app, LOVE_CITY, "owner")
    assert patch(app, grace_task, LOVE_CITY, done=True).status_code == 404
    assert app.delete(f"/church/assignments/{grace_task}?business_id={LOVE_CITY}").status_code == 404
    assert patch(app, "not-an-id", LOVE_CITY, done=True).status_code == 400
    assert task(db, grace_task)["status"] != "done"


# ─── The board ────────────────────────────────────────────────────────

def test_the_board_counts_each_person_and_their_first_assignment(app, db):
    t = _rooms_item(app, db)
    as_(app, LOVE_CITY, "naiya")
    patch(app, t["id"], LOVE_CITY, stuck="Floor plan")
    as_(app, LOVE_CITY, "jessica")
    give(app, LOVE_CITY, login(db, LOVE_CITY, "tiara"), title="Late one", due_date="2026-11-01")
    r = app.get(f"/church/assignments/people?business_id={LOVE_CITY}")
    assert r.status_code == 200, r.text
    b = r.json()
    rows = {p["name"]: p for p in b["people"]}
    assert set(rows) == {"Naiya Clark", "Tiara Adams", "Laquesha Bailey-Smith", "Shapretta McClain", "Marcus Taylor"}
    n = rows["Naiya Clark"]
    # Love City's three departments each have a leader: that item ticked itself off.
    assert (n["for"], n["why"], n["open"], n["stuck"], n["late"], n["done_7d"]) == (
        login(db, LOVE_CITY, "naiya"), "Office · Office & Leadership", 5, 1, 0, 1)
    assert n["first"] == {"done": 1, "of": 6, "to_make": 0}
    assert n["stuck_items"][0]["title"] == "Every room in the system" and n["stuck_items"][0]["note"] == "Floor plan"
    assert len(n["next"]) == 3 and "Every room in the system" not in [x["title"] for x in n["next"]]
    ti = rows["Tiara Adams"]
    assert (ti["open"], ti["late"], ti["first"]) == (1, 1, {"done": 0, "of": 0, "to_make": 6})
    assert rows["Marcus Taylor"]["why"] == "Answers to you" and rows["Marcus Taylor"]["kind"] == "person"
    assert b["counts"] == {"people": 5, "late": 1, "stuck": 1}
    said = str(b)
    assert "@" not in said
    keys = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                keys.append(k)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(b)
    assert not [k for k in keys if MONEY.search(k)], "no money anywhere"
    as_(app, LOVE_CITY, "naiya")
    assert app.get(f"/church/assignments/people?business_id={LOVE_CITY}").json()["people"] == [], "nobody under her"


@pytest.mark.parametrize("biz,who,people", [(NEW_HOPE, "owner", 18), (LOVE_CITY, "jessica", 5),
                                             (LOVE_CITY, "owner", 19)])
def test_the_board_reads_each_table_a_few_times_for_the_whole_church(app, db, monkeypatch, biz, who, people):
    seen = []
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (seen.append(path), real(path, **kw))[1])
    as_(app, biz, who)
    b = app.get(f"/church/assignments/people?business_id={biz}").json()
    assert len(b["people"]) >= people
    count = lambda t: sum(1 for p in seen if p.lstrip("/").startswith(t + "?"))  # noqa: E731
    assert count("tasks") == 2, "every person's assignments in two reads"
    assert count("church_duty_holders") == 1 and count("church_leader_roles") <= 2
    assert count("contacts") <= 3 and count("church_departments") <= 1
    assert len(seen) <= 25, sorted(p.split("?")[0] for p in seen)


def test_a_failed_read_on_the_board_is_a_503(app, db, monkeypatch):
    as_(app, LOVE_CITY, "jessica")
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.lstrip("/").startswith("tasks?") else real(path, **kw))
    assert app.get(f"/church/assignments/people?business_id={LOVE_CITY}").status_code == 503


# ─── Picked days ──────────────────────────────────────────────────────

def put_day(app, biz, duty, day, user_id=None):
    body = {"business_id": biz, "duty": duty, "day": day}
    if user_id:
        body["user_id"] = user_id
    return app.put("/church/duty-days", json=body)


def test_a_login_picks_its_days_and_my_week_and_the_team_follow(app, db):
    as_(app, LOVE_CITY, "naiya")
    page = app.get(f"/church/duty-days?business_id={LOVE_CITY}").json()
    duties = {d["duty"]: d for d in page["duties"]}
    assert set(duties) == set(cd.STARTER["office_leadership"])
    assert (duties["weekly_text"]["catalog_day"], duties["weekly_text"]["picked"], duties["weekly_text"]["movable"]) == (
        "Wed", None, True)
    r = put_day(app, LOVE_CITY, "weekly_text", "Thu")
    assert r.status_code == 200 and r.json()["saved"]["picked"] == "Thu" and r.json()["saved"]["when"] == "Thursdays"
    rhythm = mw.rhythm(c3.church(db, LOVE_CITY), uid(db, LOVE_CITY, "naiya"), "manager", NOW)
    thu = next(d for d in rhythm["days"] if d["key"] == "Thu")
    item = next(i for i in thu["items"] if i["key"] == "weekly_text")
    assert item["picked"] == "Thu" and item["usual"] == "Wednesdays" and item["movable"] is True
    assert not [i for d in rhythm["days"] if d["key"] == "Wed" for i in d["items"] if i["key"] == "weekly_text"]
    assert put_day(app, LOVE_CITY, "records", "Tue").json()["saved"]["when"] == "Once a month, on a Tuesday"
    picks = cas.days_for(LOVE_CITY, [uid(db, LOVE_CITY, "naiya")])[uid(db, LOVE_CITY, "naiya")]
    week = ctw.due_this_week(cd.STARTER["office_leadership"], date(2026, 11, 9), picks)
    texts = [w["text"] for w in week]
    assert "Thu: The weekly text and email" in texts and "Wed: The weekly text and email" not in texts
    assert not [w for w in week if w["duty"] == "records"], "once a month stays out of the week"
    page = ctw.team(c3.church(db, LOVE_CITY), NOW)
    naiya = next(r for r in page["team"] if r["user_id"] == uid(db, LOVE_CITY, "naiya"))
    assert "Thu: The weekly text and email" in naiya["this_week_text"]
    assert put_day(app, LOVE_CITY, "weekly_text", None).json()["saved"]["picked"] is None
    assert app.get(f"/church/duty-days?business_id={LOVE_CITY}").json()["duties"][4]["picked"] is None


def test_sunday_jobs_and_the_first_monday_report_stay_put(app, db):
    as_(app, LOVE_CITY, "laquesha")
    r = put_day(app, LOVE_CITY, "attendance", "Mon")
    assert r.status_code == 400 and "stays on its day" in r.json()["detail"]
    assert put_day(app, LOVE_CITY, "kids", "Mon").status_code == 400, "not one of her jobs"
    assert put_day(app, LOVE_CITY, "serve_schedule", "Sunday").status_code == 400
    assert put_day(app, LOVE_CITY, "serve_schedule", "Tue").status_code == 200
    as_(app, LOVE_CITY, "jessica")
    assert put_day(app, LOVE_CITY, "monthly_report", "Tue").status_code == 400
    assert not cas.movable("stream") and not cas.movable("deposit") and cas.movable("building")


def test_whoever_is_over_a_login_can_pick_its_days_and_no_one_else(app, db):
    naiya = uid(db, LOVE_CITY, "naiya")
    as_(app, LOVE_CITY, "jessica")
    assert put_day(app, LOVE_CITY, "calendar", "Thu", naiya).status_code == 200
    assert app.get(f"/church/duty-days?business_id={LOVE_CITY}&user_id={naiya}").json()["over"] is True
    as_(app, LOVE_CITY, "tiara")
    assert put_day(app, LOVE_CITY, "calendar", "Mon", naiya).status_code == 403
    assert app.get(f"/church/duty-days?business_id={LOVE_CITY}&user_id={naiya}").status_code == 403


def test_closed_the_picked_days_are_never_read(app, db, monkeypatch):
    as_(app, LOVE_CITY, "naiya")
    put_day(app, LOVE_CITY, "weekly_text", "Thu")
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    seen = []
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (seen.append(path), real(path, **kw))[1])
    rhythm = mw.rhythm(c3.church(db, LOVE_CITY), uid(db, LOVE_CITY, "naiya"), "manager", NOW)
    wed = next(d for d in rhythm["days"] if d["key"] == "Wed")
    assert "weekly_text" in [i["key"] for i in wed["items"]] and "movable" not in wed["items"][0]
    ctw.team(c3.church(db, LOVE_CITY), NOW)
    assert not [p for p in seen if "church_duty_days" in p or "raised_to" in p]


# ─── The grouped hand-off tell ────────────────────────────────────────

def test_a_first_assignment_is_one_email_and_one_push_to_a_login(app, db):
    as_(app, LOVE_CITY, "jessica")
    start(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"))
    stats = cot.sweep_tick(NOW)
    [mail] = [m for m in db.sent if m["to"] == "naiya@lovecity.org"]
    assert stats["office_told"] == 6 and mail["key"].startswith("office-tasks-")
    assert mail["subject"] == "Love City Church: 6 things for your first four weeks"
    assert "jessica" in mail["html"].lower() and "Every room in the system" in mail["html"]
    [push] = [p for p in db.pushes if p["to"] == uid(db, LOVE_CITY, "naiya")]
    assert push["title"] == "Your first assignment" and push["nav"] == "operate:my-week"
    assert all(t.get("seat_told_at") for t in db.t["tasks"] if t.get("startup_key"))
    db.sent.clear()
    cot.sweep_tick(NOW)
    assert not [m for m in db.sent if m["to"] == "naiya@lovecity.org"], "told once"


def test_a_grouped_email_that_fails_lets_every_claim_go(app, db):
    as_(app, LOVE_CITY, "jessica")
    start(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"))
    db.fail_to.add("naiya@lovecity.org")
    stats = cot.sweep_tick(NOW)
    assert stats["office_unsent"] == 6
    assert not any(t.get("seat_told_at") for t in db.t["tasks"] if t.get("startup_key"))


def test_closed_each_hand_off_is_its_own_email_as_before(app, db, monkeypatch):
    as_(app, LOVE_CITY, "jessica")
    start(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"))
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    cot.sweep_tick(NOW)
    mails = [m for m in db.sent if m["to"] == "naiya@lovecity.org"]
    assert len(mails) == 6 and all(m["key"].startswith("office-task-") for m in mails)


def test_a_first_assignment_is_one_email_to_a_person(app, db):
    as_(app, LOVE_CITY, "owner")
    made = start(app, LOVE_CITY, person(db, LOVE_CITY, "yolanda")).json()["made"]
    clt.sweep_tick(NOW)
    mails = [m for m in db.sent if m["to"] == "yolanda@lovecity.org" and m["key"].startswith("leader-task")
             and "-late-" not in m["key"]]
    assert len(mails) == 1 and mails[0]["key"].startswith("leader-tasks-")
    assert f"{len(made)} things for your first" in mails[0]["subject"]


# ─── The switch, the migration, the templates ─────────────────────────

def test_the_switch_closes_every_route(app, db, monkeypatch):
    as_(app, LOVE_CITY, "jessica")
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "off")
    assert app.get(f"/church/assignments/people?business_id={LOVE_CITY}").status_code == 404
    assert give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="x").status_code == 404
    assert app.get(f"/church/duty-days?business_id={LOVE_CITY}").status_code == 404
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "owner")
    assert app.get(f"/church/assignments/people?business_id={LOVE_CITY}").status_code == 200, "the platform's church"
    as_(app, GRACE, "owner")
    assert app.get(f"/church/assignments/people?business_id={GRACE}").status_code == 404
    db.t["businesses"][0]["type"] = "salon"
    as_(app, LOVE_CITY, "owner")
    assert app.get(f"/church/assignments/people?business_id={LOVE_CITY}").status_code == 404


def test_the_migration_is_additive_and_says_what_each_column_is():
    sql = open(os.path.join(ROOT, "supabase", "APPLY-2026-11-12-church-assignments.sql"), encoding="utf-8").read()
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert body.strip().startswith("begin;") and body.rstrip().endswith("commit;")
    assert not re.search(r"\bdrop\s+(table|column)\b", body, re.I)
    for col in ("duty", "done_when", "check_key", "startup_key", "stuck_note", "stuck_at", "raised_at", "raised_to",
                "raised_to_contact_id", "raised_by", "raised_told_at", "checked_at"):
        assert f"add column if not exists {col} " in body, col
        assert f"comment on column public.tasks.{col} is" in body, col
    assert re.search(r"create unique index if not exists tasks_startup_once\s+on public\.tasks "
                     r"\(business_id, coalesce\(assigned_to, assigned_contact_id\), startup_key\)\s+"
                     r"where startup_key is not null", body)
    # Nothing old to check under the lock: the CHECKs and FKs are NOT VALID (#1801 review).
    assert not re.search(r"add column if not exists \w+ uuid references", body), "no inline (validated) foreign key"
    for name in ("tasks_raised_to_fkey", "tasks_raised_to_contact_id_fkey", "tasks_raised_by_fkey",
                 "tasks_raised_to_one", "tasks_assignment_lengths"):
        assert re.search(rf"add constraint {name}\b[^;]*\bnot valid;", body, re.S), name
    assert "create table if not exists public.church_duty_days" in body
    assert "enable row level security" in body and "create policy" not in body
    assert "revoke all on public.church_duty_days from anon, authenticated" in body
    for key in [t["key"] for t in cs.TEMPLATES]:
        assert re.fullmatch(r"[a-z][a-z0-9_.]{1,79}", key), key
    for key in cw.CHECKS:
        assert re.fullmatch(r"[a-z][a-z0-9_]{1,39}", key), key


def test_the_templates_read_right_at_any_church():
    lanes = {}
    for t in cs.TEMPLATES:
        assert 1 <= t["week"] <= 4 and t["title"] and t["done_when"] and len(t["done_when"]) <= 300
        assert t["check"] is None or t["check"] in cw.CHECKS, t["key"]
        if t["duty"] in cd.CATALOG:
            assert not cd.CATALOG[t["duty"]]["money"], t["key"]
            for ln in cd.CATALOG[t["duty"]]["lanes"]:
                lanes.setdefault(ln, []).append(t["key"])
        else:
            assert t["duty"] in cs.SWITCH_LABEL, t["key"]
        per_duty = [x for x in cs.TEMPLATES if x["duty"] == t["duty"]]
        assert 1 <= len(per_duty) <= 4, t["duty"]
    for ln in ("office_leadership", "people_care", "sunday_serving", "media_comms"):
        assert 5 <= len(lanes[ln]) <= 9, ln
    assert len(lanes[cd.EXEC]) == 2
    words = " ".join(t["title"] + " " + t["done_when"] for t in cs.TEMPLATES)
    for name in ("Love City", "Naiya", "Tiara", "Laquesha", "Shapretta", "Jessica", "Kevin", "Karim", "Devonta",
                 "Nicholas", "Minnie", "October", "December"):
        assert name not in words, name
    leaders = " ".join(t["title"] + " " + t["done_when"] for t in cs.TEMPLATES if t["duty"] in cs.SWITCH_LABEL)
    assert not re.search(r"pastor|elder|deacon|bishop|minister|director|overseer|executive", leaders, re.I)


# ─── The #1801 review: who can reach an Admin, the top, the sweep ─────

def _minnie_answers_to_jessica(db):
    db.t["church_leader_roles"].append({
        "id": db.nid("church_leader_roles"), "business_id": LOVE_CITY, "contact_id": db.who[LOVE_CITY]["minnie"],
        "role": "ministers", "scope": "", "status": "active", "invited_at": "2026-10-01T00:00:00+00:00",
        "answered_at": None, "answers_to_contact_id": db.who[LOVE_CITY]["jessica"]})


def test_a_manager_the_map_puts_over_an_admin_reaches_none_of_the_admins_work(app, db):
    _minnie_answers_to_jessica(db)
    as_(app, LOVE_CITY, "owner")
    r = give(app, LOVE_CITY, login(db, LOVE_CITY, "minnie"), title="Reconcile October",
             notes="Bank shows 12,400.00; books 12,150.00", duty="books")
    assert r.status_code == 200, r.text
    tid = r.json()["saved"]["id"]
    as_(app, LOVE_CITY, "jessica")
    minnie = login(db, LOVE_CITY, "minnie")
    assert app.get(f"/church/assignments?business_id={LOVE_CITY}&for={minnie}").status_code == 403
    assert patch(app, tid, LOVE_CITY, title="Never mind", due_date="2027-06-01").status_code == 403
    assert patch(app, tid, LOVE_CITY, done=True).status_code == 403
    assert app.delete(f"/church/assignments/{tid}?business_id={LOVE_CITY}").status_code == 403
    assert give(app, LOVE_CITY, minnie, title="x").status_code == 403
    assert start(app, LOVE_CITY, minnie).status_code == 403
    assert put_day(app, LOVE_CITY, "pay", "Sat", uid(db, LOVE_CITY, "minnie")).status_code == 403
    row = task(db, tid)
    assert (row["title"], row["status"]) == ("Reconcile October", "todo"), "nothing changed"
    board = app.get(f"/church/assignments/people?business_id={LOVE_CITY}").json()
    assert minnie not in {p["for"] for p in board["people"]}


def test_a_member_seat_department_leader_reaches_none_of_the_treasurers_work(app, db):
    nh = NEW_HOPE
    db.t["church_leader_roles"].append({
        "id": db.nid("church_leader_roles"), "business_id": nh, "contact_id": db.who[nh]["tessa"], "role": "deacons",
        "scope": "", "status": "active", "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None,
        "answers_to_contact_id": None})
    celia = "3a000000-0000-4000-8000-000000000099"
    db.t["business_users"].append({"business_id": nh, "user_id": celia, "role": "member",
                                   "invited_email": "celia@newhope.church", "lane": None, "areas": None,
                                   "contact_id": db.who[nh]["celia"], "name": "Celia Ward", "status": "active"})
    as_(app, nh, "owner")
    tid = give(app, nh, login(db, nh, "tessa"), title="Pay the roofer", notes="$8,450 by Friday").json()["saved"]["id"]
    app.who.update(id=celia, email="celia@newhope.church")
    assert app.get(f"/church/assignments?business_id={nh}&for={login(db, nh, 'tessa')}").status_code == 403
    assert put_day(app, nh, "books", "Fri", uid(db, nh, "tessa")).status_code == 403
    assert app.delete(f"/church/assignments/{tid}?business_id={nh}").status_code == 403
    assert task(db, tid)["title"] == "Pay the roofer"
    assert not [d for d in db.t.get("church_duty_days", []) if d["business_id"] == nh]


def test_a_money_jobs_day_is_the_owners_or_an_admins_to_pick(app, db):
    as_(app, LOVE_CITY, "owner")
    assert put_day(app, LOVE_CITY, "pay", "Thu", uid(db, LOVE_CITY, "minnie")).status_code == 200
    as_(app, LOVE_CITY, "minnie")
    assert put_day(app, LOVE_CITY, "books", "Tue").status_code == 200
    as_(app, LOVE_CITY, "jessica")
    r = put_day(app, LOVE_CITY, "pay", "Fri", uid(db, LOVE_CITY, "naiya"))
    assert r.status_code == 403 and "money job" in r.json()["detail"]


def test_the_pastor_under_another_email_is_never_started_or_handed_work_by_an_admin(app, db):
    kevin = next(c for c in db.t["contacts"] if c["id"] == db.who[LOVE_CITY]["kevin"])
    kevin["email"] = "pastor@lovecity.org"
    as_(app, LOVE_CITY, "minnie")
    assert start(app, LOVE_CITY, person(db, LOVE_CITY, "kevin")).status_code == 403
    assert give(app, LOVE_CITY, person(db, LOVE_CITY, "kevin"), title="x").status_code == 403
    assert not [t for t in db.t["tasks"] if t.get("startup_key")]
    names = {p["name"] for p in app.get(f"/church/assignments/people?business_id={LOVE_CITY}").json()["people"]}
    assert "Kevin McCloud" not in names


def test_a_failed_read_of_the_owners_email_is_a_503_on_the_board(app, db, monkeypatch):
    import messaging_router
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda u: None)
    as_(app, LOVE_CITY, "minnie")
    assert app.get(f"/church/assignments/people?business_id={LOVE_CITY}").status_code == 503


def test_a_failed_email_read_never_loses_a_raise(app, db, monkeypatch):
    import messaging_router
    t = _sent_up(app, db)
    co._OWNER_EMAIL.clear()
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda u: None)       # Auth blips
    s1 = cas.sweep_tick(NOW)
    assert s1["raised_unread"] == 1 and s1["raised_no_email"] == 0 and not db.sent
    assert task(db, t["id"]).get("raised_told_at") is None, "not claimed: the next sweep tries again"
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda u: c3.OWNER_EMAIL.get(str(u), ""))
    s2 = cas.sweep_tick(NOW)
    assert s2["raised_told"] == 1 and [m["to"] for m in db.sent] == [c3.PLATFORM]


def test_a_failed_read_of_the_people_never_loses_a_raise(app, db, monkeypatch):
    t = _sent_up(app, db)
    real = clt._contacts
    monkeypatch.setattr(clt, "_contacts", lambda b, ids: None)
    assert cas.sweep_tick(NOW)["raised_unread"] == 1 and task(db, t["id"]).get("raised_told_at") is None
    monkeypatch.setattr(clt, "_contacts", real)
    assert cas.sweep_tick(NOW)["raised_told"] == 1


def test_a_seat_with_no_email_is_told_with_nothing_sent(app, db):
    t = _sent_up(app, db)
    row = task(db, t["id"])
    row["raised_to"] = uid(db, LOVE_CITY, "minnie")
    next(s for s in db.t["business_users"] if s["user_id"] == row["raised_to"])["invited_email"] = ""
    stats = cas.sweep_tick(NOW)
    assert stats["raised_no_email"] == 1 and row["raised_told_at"], "claimed: on their page, nothing to send"


def test_the_sweep_reads_only_what_it_can_use_page_by_page(app, db, monkeypatch):
    as_(app, LOVE_CITY, "jessica")
    start(app, LOVE_CITY, login(db, LOVE_CITY, "tiara"))           # two of hers pass at Love City
    # 1,100 items no check will tick, all ahead of hers: they never crowd her out.
    for n in range(1100):
        db.t["tasks"].append({"id": f"00000000-0000-4000-8000-{n:012d}", "business_id": LOVE_CITY, "title": "x",
                              "status": "todo", "check_key": "calendar_8_weeks",
                              "assigned_to": uid(db, LOVE_CITY, "naiya"), "created_at": "2026-01-01T00:00:00+00:00"})
    db.t["tasks"].append({"id": "00000001-0000-4000-8000-000000000000", "business_id": GRACE, "title": "grace",
                          "status": "todo", "check_key": "groups_led", "assigned_to": uid(db, GRACE, "sharon"),
                          "created_at": "2026-01-01T00:00:00+00:00"})
    seen = []
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, **kw: (seen.append(path), real(path, **kw))[1])
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "owner")
    monkeypatch.setattr(cas, "_platform_owner_id", lambda: c3.LC_OWNER)
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda b: b == LOVE_CITY)
    stats = cas.sweep_tick(NOW)
    assert stats["ticked"] == 2 and stats["churches"] == 1
    reads = [p for p in seen if p.startswith("/tasks?check_key=")]
    assert len(reads) >= 2, "page by page"
    assert all(f"business_id=in.({LOVE_CITY})" in p and "rooms_listed" not in p and "kids_checked" not in p
               for p in reads), reads
    assert next(t for t in db.t["tasks"] if t["title"] == "grace")["status"] == "todo", "a closed church: never read"


def test_the_sweep_is_quiet_when_the_platforms_churches_cant_be_read(app, db, monkeypatch):
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "owner")
    monkeypatch.setattr(cas, "_platform_owner_id", lambda: c3.LC_OWNER)
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/businesses?owner_id") else real(path, **kw))
    assert cas.sweep_tick(NOW)["churches"] == 0


def test_a_grouped_tell_before_the_migration_still_goes_and_says_tasks(app, db, monkeypatch):
    """Owner is the default, so Love City's hand-offs group as soon as this
    deploys; before the migration every read naming a new column fails, and
    the grouped tell must still go, worded as tasks (#1801 review)."""
    naiya, jess = uid(db, LOVE_CITY, "naiya"), uid(db, LOVE_CITY, "jessica")
    for n, title in enumerate(("Book the hall", "Order the paper", "Print the bulletins")):
        db.t["tasks"].append({"id": f"7a000000-0000-4000-8000-00000000000{n}", "business_id": LOVE_CITY,
                              "title": title, "description": None, "status": "todo", "due_date": "2026-11-20",
                              "assigned_to": naiya, "handed_by": jess, "created_at": NOW.isoformat(),
                              "seat_told_at": None, "seat_late_told_at": None})
    new = re.compile(r"\b(duty|done_when|check_key|startup_key|stuck_note|stuck_at|raised_\w+|checked_at)\b")
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if new.search(path) else real(path, **kw))
    monkeypatch.setenv("CHURCH_ASSIGNMENTS", "owner")
    import member_asks
    monkeypatch.setattr(member_asks, "platform_church", lambda b: b == LOVE_CITY)
    stats = cot.sweep_tick(NOW)
    [mail] = [m for m in db.sent if m["to"] == "naiya@lovecity.org"]
    assert stats["office_told"] == 3 and mail["subject"] == "Love City Church: 3 tasks"
    assert all(t.get("seat_told_at") for t in db.t["tasks"] if t["id"].startswith("7a000000"))
    monkeypatch.setattr(cas, "_platform_owner_id", lambda: c3.LC_OWNER)
    quiet = cas.sweep_tick(NOW)
    assert quiet["churches"] == 0 and quiet["raised_told"] == 0 and quiet["ticked"] == 0, "quiet before the migration"


# ─── The #1801 review, round 2 ────────────────────────────────────────

def _self_handed_sent_up(app, db):
    as_(app, LOVE_CITY, "naiya")
    tid = give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="My own").json()["saved"]["id"]
    assert patch(app, tid, LOVE_CITY, stuck="blocked").status_code == 200
    as_(app, LOVE_CITY, "jessica")
    assert app.post(f"/church/assignments/{tid}/raise", json={"business_id": LOVE_CITY}).status_code == 200
    return tid


def test_once_its_sent_up_the_assignee_cant_take_back_even_what_she_handed_herself(app, db):
    tid = _self_handed_sent_up(app, db)
    as_(app, LOVE_CITY, "naiya")
    r = app.delete(f"/church/assignments/{tid}?business_id={LOVE_CITY}")
    assert r.status_code == 403 and r.json()["detail"] == cas.SENT_UP_STAYS
    as_(app, LOVE_CITY, "owner")
    assert [i["title"] for i in mine(app, LOVE_CITY)["raised_to_you"]] == ["My own"], "still on the receiver's list"
    as_(app, LOVE_CITY, "tiara")
    assert app.delete(f"/church/assignments/{tid}?business_id={LOVE_CITY}").status_code == 403
    as_(app, LOVE_CITY, "owner")                                         # whoever it went to
    assert app.delete(f"/church/assignments/{tid}?business_id={LOVE_CITY}").status_code == 200


def test_whoever_sent_it_up_can_take_it_back(app, db):
    tid = _self_handed_sent_up(app, db)
    as_(app, LOVE_CITY, "jessica")
    assert app.delete(f"/church/assignments/{tid}?business_id={LOVE_CITY}").status_code == 200


def test_before_its_sent_up_the_assignee_takes_back_what_she_handed_herself(app, db):
    as_(app, LOVE_CITY, "naiya")
    tid = give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="My own").json()["saved"]["id"]
    assert app.delete(f"/church/assignments/{tid}?business_id={LOVE_CITY}").status_code == 200


def test_a_take_back_that_races_a_send_up_loses_it(app, db, monkeypatch):
    """Read before it was sent up, deleted after: the database's own filter
    (raised_at is null) keeps it, and the answer is a 409."""
    as_(app, LOVE_CITY, "naiya")
    tid = give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="My own").json()["saved"]["id"]
    stale = dict(task(db, tid))
    task(db, tid).update(raised_at=NOW.isoformat(), raised_to=c3.LC_OWNER, stuck_at=NOW.isoformat())
    monkeypatch.setattr(cas, "_task", lambda ch, task_id: dict(stale))
    r = app.delete(f"/church/assignments/{tid}?business_id={LOVE_CITY}")
    assert r.status_code == 409 and task(db, tid)["title"] == "My own"


def test_the_assignees_unstuck_that_races_a_send_up_loses_it(app, db, monkeypatch):
    t = _rooms_item(app, db)
    as_(app, LOVE_CITY, "naiya")
    patch(app, t["id"], LOVE_CITY, stuck="Floor plan")
    stale = dict(task(db, t["id"]))
    task(db, t["id"]).update(raised_at=NOW.isoformat(), raised_to=c3.LC_OWNER,
                             raised_by=uid(db, LOVE_CITY, "jessica"))   # sent up after she read it
    monkeypatch.setattr(cas, "_task", lambda ch, task_id: dict(stale))
    r = patch(app, t["id"], LOVE_CITY, stuck=None)
    assert r.status_code == 409 and r.json()["detail"] == cas.JUST_SENT_UP
    row = task(db, t["id"])
    assert row["stuck_at"] and row["raised_to"] == c3.LC_OWNER, "the database held the rule"


def test_a_cold_auth_read_fails_before_the_write_never_after(app, db, monkeypatch):
    import messaging_router
    co._OWNER_EMAIL.clear()
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda u: None)
    as_(app, LOVE_CITY, "naiya")
    before = len(db.t["tasks"])
    for _ in range(2):                                             # a retry makes no second copy
        assert give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="Call the plumber").status_code == 503
    assert len(db.t["tasks"]) == before, "nothing saved on a 503"
    monkeypatch.setattr(messaging_router, "owner_email_read", lambda u: c3.OWNER_EMAIL.get(str(u), ""))
    assert give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="Call the plumber").status_code == 200
    assert len(db.t["tasks"]) == before + 1


def test_a_name_read_that_fails_after_a_saved_write_still_answers_with_what_it_saved(app, db, monkeypatch):
    from fastapi import HTTPException
    as_(app, LOVE_CITY, "jessica")

    def blip(*a, **k):
        raise HTTPException(503, "names unread")
    monkeypatch.setattr(cas, "_names_by_login", blip)
    r = give(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"), title="Book the hall")
    assert r.status_code == 200 and r.json()["saved"]["from"] == "the church office"
    assert len([t for t in db.t["tasks"] if t.get("title") == "Book the hall"]) == 1
    got = start(app, LOVE_CITY, login(db, LOVE_CITY, "naiya"))
    assert got.status_code == 200 and len(got.json()["made"]) == 6


def test_at_an_elders_church_the_owner_starts_an_elder_and_an_admin_cant(app, db):
    from test_church_over import _elders_church
    from church_three import RIVERSIDE
    bernice, _odell = _elders_church(db)
    henry = f"person:{db.who[RIVERSIDE]['henry']}"
    as_(app, RIVERSIDE, "owner")
    r = start(app, RIVERSIDE, henry)
    assert r.status_code == 200 and r.json()["made"], r.text
    assert give(app, RIVERSIDE, henry, title="Visit the Blands").status_code == 200
    app.who.update(id=bernice, email="bernice@riversideame.org")
    assert give(app, RIVERSIDE, henry, title="x").status_code == 403
    assert start(app, RIVERSIDE, f"person:{db.who[RIVERSIDE]['lois']}").status_code == 403
    assert app.get(f"/church/assignments?business_id={RIVERSIDE}&for={henry}").status_code == 403
