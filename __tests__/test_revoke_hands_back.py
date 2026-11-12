"""A login taken off the team leaves nothing with it (business_users_router.
revoke, Kevin 2026-11-11: "if a person is removed automatically the emails
etc is as well with no problems").

Pins:
  * the revoke ends the seat, and its open tasks and the care requests the
    owner handed it go back (the office's list, Prayer & care); done tasks,
    closed requests and another login's work stay as they were
  * a login read that failed is a 503, never an unranked revoke (it used to
    read as "no such login" and let a manager remove an admin)
  * a revoke that didn't save is a 503, never {"ok": true}
  * a manager still can't remove an admin
  * an invite never accepted has nothing to hand back

The tables are the follow-up tests' in-memory PostgREST."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import business_users_router as bur  # noqa: E402
import sb_clients  # noqa: E402
from test_church_follow_up import FakeDB  # noqa: E402

BIZ = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
OWNER = "22222222-2222-4222-8222-222222222222"
JESSICA, TIA, ADMIN = (f"44444444-4444-4444-8444-00000000000{i}" for i in range(1, 4))
SEAT_J, SEAT_T, SEAT_A, SEAT_INVITED = (f"55555555-5555-4555-8555-00000000000{i}" for i in range(1, 5))


def _seat(sid, uid, role):
    return {"id": sid, "business_id": BIZ, "user_id": uid, "role": role, "status": "active"}


def _task(n, who, status="todo"):
    return {"id": f"66666666-6666-4666-8666-00000000000{n}", "business_id": BIZ, "assigned_to": who, "status": status}


def _care(n, who, status="new"):
    return {"id": f"77777777-7777-4777-8777-00000000000{n}", "business_id": BIZ, "assigned_to": who,
            "assigned_at": "2026-11-10T12:00:00+00:00", "status": status}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(
        business_users=[_seat(SEAT_J, JESSICA, "manager"), _seat(SEAT_T, TIA, "manager"),
                        _seat(SEAT_A, ADMIN, "admin"),
                        {"id": SEAT_INVITED, "business_id": BIZ, "user_id": None, "role": "manager", "status": "invited"}],
        tasks=[_task(1, JESSICA), _task(2, JESSICA), _task(3, JESSICA, "done"), _task(4, TIA)],
        ministry_care_requests=[_care(1, JESSICA), _care(2, JESSICA, "closed"), _care(3, TIA)],
    )
    for name in ("get", "post", "patch", "delete"):
        monkeypatch.setattr(sb_clients, f"sb_{name}_as_service", getattr(fake, name))
    return fake


def _as(monkeypatch, rank):
    monkeypatch.setattr(bur, "require_role", lambda biz, uid, min_role: rank)
    return SimpleNamespace(id=OWNER)


def _row(db, table, rid):
    return next(r for r in db.t[table] if r["id"] == rid)


def test_a_removed_login_takes_nothing_with_it(db, monkeypatch):
    out = bur.revoke(SEAT_J, BIZ, user=_as(monkeypatch, "owner"))
    assert out == {"ok": True, "tasks_returned": 2, "care_returned": 1, "failed": 0}
    assert _row(db, "business_users", SEAT_J)["status"] == "revoked"
    assert [t["assigned_to"] for t in db.t["tasks"]] == [None, None, JESSICA, TIA], "done stays her record; Tia's stays Tia's"
    care = db.t["ministry_care_requests"]
    assert care[0]["assigned_to"] is None and care[0]["assigned_at"] is None
    assert care[1]["assigned_to"] == JESSICA and care[2]["assigned_to"] == TIA


def test_an_invite_never_accepted_has_nothing_to_hand_back(db, monkeypatch):
    assert bur.revoke(SEAT_INVITED, BIZ, user=_as(monkeypatch, "owner")) == {
        "ok": True, "tasks_returned": 0, "care_returned": 0, "failed": 0}


def test_a_failed_login_read_is_a_503_never_an_unranked_revoke(db, monkeypatch):
    real = db.get
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **kw: None if path.startswith("/business_users") else real(path, **kw))
    with pytest.raises(HTTPException) as e:
        bur.revoke(SEAT_A, BIZ, user=_as(monkeypatch, "manager"))
    assert e.value.status_code == 503 and _row(db, "business_users", SEAT_A)["status"] == "active"


def test_a_manager_still_cannot_remove_an_admin(db, monkeypatch):
    with pytest.raises(HTTPException) as e:
        bur.revoke(SEAT_A, BIZ, user=_as(monkeypatch, "manager"))
    assert e.value.status_code == 403 and _row(db, "business_users", SEAT_A)["status"] == "active"


def test_a_revoke_that_didnt_save_is_a_503_and_hands_nothing_back(db, monkeypatch):
    real = db.patch
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, **kw: None if path.startswith("/business_users") else real(path, body, **kw))
    with pytest.raises(HTTPException) as e:
        bur.revoke(SEAT_J, BIZ, user=_as(monkeypatch, "owner"))
    assert e.value.status_code == 503
    assert _row(db, "tasks", _task(1, JESSICA)["id"])["assigned_to"] == JESSICA


def test_a_login_that_isnt_here_is_a_404(db, monkeypatch):
    with pytest.raises(HTTPException) as e:
        bur.revoke("55555555-5555-4555-8555-000000000009", BIZ, user=_as(monkeypatch, "owner"))
    assert e.value.status_code == 404
