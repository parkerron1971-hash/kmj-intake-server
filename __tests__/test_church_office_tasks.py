"""A task handed to an office login reaches them (church_office_tasks.py;
Love City's office checkup, Kevin 2026-11-01).

Pins:
  * a task newly handed to a login is told once, by email (to their sign-in
    address, from the church, naming who handed it) and a push; two sweeps,
    one email
  * handed to yourself, or to a login that has left: marked told, nothing sent
  * an email that fails lets the claim go, and the next sweep sends
  * a done task is never told
  * late, in the church's morning: once, to whoever handed it and the
    Executive Pastor (a login whose record holds the role), one email each,
    the same person told once; a church with no Executive Pastor: the owner;
    the Executive Pastor's own late task: the owner
  * never before the due date, never outside the church's morning
  * quiet with the switch off or before the migration

The tables are the leader tasks tests' in-memory PostgREST."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import church_leader_tasks as clt  # noqa: E402
import church_office_tasks as cot  # noqa: E402
import sb_clients  # noqa: E402
from test_church_leader_tasks import BIZ, NOW, OWNER, _def, _role, _task, db  # noqa: E402,F401

NAIYA, JESSICA, TIARA = ("u0000000-0000-4000-8000-0000000000n1", "u0000000-0000-4000-8000-0000000000j1",
                         "u0000000-0000-4000-8000-0000000000t1")
C_NAIYA, C_JESSICA, C_TIARA = ("c0000000-0000-4000-8000-0000000000a1", "c0000000-0000-4000-8000-0000000000a2",
                               "c0000000-0000-4000-8000-0000000000a3")
T1, T2, T3 = (f"73000000-0000-4000-8000-00000000000{i}" for i in range(1, 4))


@pytest.fixture
def office(db, monkeypatch):
    t = db.t
    for task in t["tasks"]:                       # the migration's backfill: what's handed already counts as told
        if task.get("assigned_to"):
            task["seat_told_at"] = "2026-10-20T12:00:00+00:00"
        task.setdefault("seat_late_told_at", None)
        task.setdefault("handed_by", None)
    t["business_users"] += [
        {"business_id": BIZ, "user_id": NAIYA, "role": "manager", "status": "active", "invited_email": "naiya@lovecity.org"},
        {"business_id": BIZ, "user_id": JESSICA, "role": "manager", "status": "active", "invited_email": "jessica@lovecity.org"},
        {"business_id": BIZ, "user_id": TIARA, "role": "manager", "status": "revoked", "invited_email": "tiara@lovecity.org"}]
    t["contacts"] += [
        {"id": C_NAIYA, "business_id": BIZ, "name": "Naiya Clark", "email": "naiya@lovecity.org"},
        {"id": C_JESSICA, "business_id": BIZ, "name": "Jessica McCloud", "email": "jessica@lovecity.org"},
        {"id": C_TIARA, "business_id": BIZ, "name": "Tiara Adams", "email": "tiara@lovecity.org"}]
    t["church_role_defs"].append(_def("executive_pastor", "Executive Pastor", "pastoral", "def-pastor"))
    t["church_leader_roles"].append(_role(C_JESSICA, "executive_pastor"))
    db.pushes = []
    import push_notifications
    monkeypatch.setattr(push_notifications, "send_to_user",
                        lambda uid, **kw: db.pushes.append({"to": uid, **kw}) or 1)
    import messaging_router
    monkeypatch.setattr(messaging_router, "_owner_email", lambda uid: "pastor@lovecity.org" if uid == OWNER else "")
    return db


def _hand(db, tid, to, title, by=None, due=None, told=None, status="todo"):
    db.t["tasks"].append({**_task(tid, None, title, due, status=status), "assigned_to": to, "handed_by": by,
                          "seat_told_at": told, "seat_late_told_at": None})


def _t(db, tid):
    return next(t for t in db.t["tasks"] if t["id"] == tid)


def _mail(db, word):
    return [m for m in db.sent if word in m["subject"]]


# ─── Told ─────────────────────────────────────────────────────────────

def test_a_task_handed_to_an_office_login_is_told_once_by_email_and_push(office):
    _hand(office, T1, NAIYA, "Book the fellowship hall", by=JESSICA, due="2026-11-04")
    first = cot.sweep_tick(NOW)
    again = cot.sweep_tick(NOW)
    sent = _mail(office, "a task for you")
    assert first["office_told"] == 1 and again["office_told"] == 0 and len(sent) == 1
    m = sent[0]
    assert m["to"] == "naiya@lovecity.org" and m["subject"] == "Love City Church: a task for you"
    assert "Hi Naiya" in m["html"] and "Jessica McCloud handed you a task: Book the fellowship hall" in m["html"]
    assert "Wednesday, November 4" in m["html"] and "office" in m["html"]
    assert _t(office, T1)["seat_told_at"] == "2026-10-28T14:00:00+00:00"
    assert [p["to"] for p in office.pushes] == [NAIYA] and office.pushes[0]["nav"] == "operate:tasks"
    assert office.pushes[0]["business_id"] == BIZ


def test_what_was_handed_before_the_migration_is_never_told(office):
    assert cot.sweep_tick(NOW)["office_told"] == 0 and not _mail(office, "a task for you")


def test_handed_to_yourself_or_to_a_login_that_left_sends_nothing(office):
    _hand(office, T1, NAIYA, "Note to self", by=NAIYA)
    _hand(office, T2, TIARA, "Call the hospital", by=JESSICA)
    stats = cot.sweep_tick(NOW)
    assert stats["office_self"] == 1 and stats["office_no_email"] == 1 and not _mail(office, "a task for you")
    assert _t(office, T1)["seat_told_at"] and _t(office, T2)["seat_told_at"], "told, never asked again"


def test_an_email_that_fails_lets_the_claim_go_and_the_next_sweep_sends(office):
    _hand(office, T1, NAIYA, "Order the paper", by=JESSICA)
    office.fail_to = {"naiya@lovecity.org"}
    assert cot.sweep_tick(NOW)["office_unsent"] == 1 and _t(office, T1)["seat_told_at"] is None
    assert not office.pushes, "no push for a hand-off that wasn't told"
    office.fail_to = set()
    assert cot.sweep_tick(NOW)["office_told"] == 1


def test_a_done_task_is_never_told(office):
    _hand(office, T1, NAIYA, "Already done", by=JESSICA, status="done")
    assert cot.sweep_tick(NOW)["office_told"] == 0


# ─── Late ─────────────────────────────────────────────────────────────

def test_a_late_task_goes_once_to_whoever_handed_it_and_the_executive_pastor(office):
    _hand(office, T1, NAIYA, "Send the weekly text", by=OWNER, due="2026-10-26", told="2026-10-21T12:00:00+00:00")
    stats = cot.sweep_tick(NOW)
    late = _mail(office, "past due")
    assert stats["office_late"] == 1 and sorted(m["to"] for m in late) == ["jessica@lovecity.org", "pastor@lovecity.org"]
    by_to = {m["to"]: m for m in late}
    assert by_to["jessica@lovecity.org"]["subject"] == "Naiya Clark has a task past due"
    assert "office team you oversee" in by_to["jessica@lovecity.org"]["html"]
    assert "you handed it to Naiya" in by_to["pastor@lovecity.org"]["html"]
    assert "Send the weekly text" in by_to["jessica@lovecity.org"]["html"]
    assert _t(office, T1)["seat_late_told_at"] == "2026-10-28T14:00:00+00:00"
    assert sorted(p["to"] for p in office.pushes) == sorted([JESSICA, OWNER])
    cot.sweep_tick(NOW)
    assert len(_mail(office, "past due")) == 2, "once"


def test_the_executive_pastor_who_handed_it_hears_once(office):
    _hand(office, T1, NAIYA, "Book the van", by=JESSICA, due="2026-10-26", told="2026-10-21T12:00:00+00:00")
    _hand(office, T2, NAIYA, "Order the cups", by=JESSICA, due="2026-10-27", told="2026-10-21T12:00:00+00:00")
    cot.sweep_tick(NOW)
    late = _mail(office, "past due")
    assert [m["to"] for m in late] == ["jessica@lovecity.org"]
    assert late[0]["subject"] == "Naiya Clark has 2 tasks past due"


def test_with_no_executive_pastor_it_goes_to_the_owner(office):
    office.t["church_leader_roles"] = [r for r in office.t["church_leader_roles"] if r["role"] != "executive_pastor"]
    _hand(office, T1, NAIYA, "Order the cups", due="2026-10-26", told="2026-10-21T12:00:00+00:00")
    cot.sweep_tick(NOW)
    assert [m["to"] for m in _mail(office, "past due")] == ["pastor@lovecity.org"]


def test_the_executive_pastors_own_late_task_goes_to_the_owner(office):
    _hand(office, T1, JESSICA, "Plan the staff retreat", due="2026-10-26", told="2026-10-21T12:00:00+00:00")
    cot.sweep_tick(NOW)
    assert [m["to"] for m in _mail(office, "past due")] == ["pastor@lovecity.org"]


def test_never_before_the_due_date_or_outside_the_churchs_morning(office):
    _hand(office, T1, NAIYA, "Due Friday", by=OWNER, due="2026-10-30", told="2026-10-21T12:00:00+00:00")
    _hand(office, T2, NAIYA, "Due Monday", by=OWNER, due="2026-10-26", told="2026-10-21T12:00:00+00:00")
    evening = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)     # 6 PM in Chicago
    assert cot.sweep_tick(evening)["office_late"] == 0
    cot.sweep_tick(NOW)
    assert _t(office, T1)["seat_late_told_at"] is None and _t(office, T2)["seat_late_told_at"]


def test_a_task_told_today_is_not_late_yet(office):
    _hand(office, T1, NAIYA, "Just handed", by=OWNER, due="2026-10-26", told="2026-10-28T13:00:00+00:00")
    assert cot.sweep_tick(NOW)["office_late"] == 0


# ─── Quiet ────────────────────────────────────────────────────────────

def test_quiet_with_the_switch_off(office, monkeypatch):
    _hand(office, T1, NAIYA, "Book the hall", by=JESSICA)
    monkeypatch.setenv("CHURCH_LEADER_TASKS", "off")
    assert cot.sweep_tick(NOW)["churches"] == 0 and not office.sent


def test_quiet_before_the_migration(office, monkeypatch):
    _hand(office, T1, NAIYA, "Book the hall", by=JESSICA)
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if "seat_told_at" in path else real(path, *a, **k))
    assert cot.sweep_tick(NOW)["churches"] == 0 and not office.sent
