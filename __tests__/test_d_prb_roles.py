"""Category D PR-B — multi-role v2 + accountant overview/access."""
from __future__ import annotations

import asyncio
import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import business_users_router as bu  # noqa: E402
import business_collaborators_router as bc  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

# Invite is STEP-UP gated (grants access). These tests exercise the
# authorisation logic BEHIND that gate, so they present a valid
# access-scoped unlock. test_step_up_scopes.py is what proves the gate
# itself refuses when the unlock is missing, wrong-scoped or expired.
import os as _os
_os.environ.setdefault("AUDITOR_LINK_SECRET", "test-secret-for-step-up")
import ledger_unlock as _lu


def _stepup(user_id):
    tok = _lu.mint(str(user_id), _lu.SCOPE_ACCESS)["token"]
    return type("R", (), {"headers": {_lu.UNLOCK_HEADER: tok}})()



@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "b1", "owner_id": "owner1", "name": "Biz",
                                  "subscription_status": None, "subscription_plan": None})
    return fb


def _member(fb, uid, role, status="active"):
    fb.rows("business_users").append({
        "id": f"m_{uid}", "business_id": "b1", "user_id": uid,
        "invited_email": f"{uid}@x.com", "role": role, "status": status})


def _u(uid):
    return type("U", (), {"id": uid})()


def test_role_of_ladder(fake):
    fb = fake
    _member(fb, "v1", "viewer")
    _member(fb, "mg1", "manager")
    _member(fb, "rv1", "manager", status="revoked")
    assert bu.role_of("b1", "owner1") == "owner"
    assert bu.role_of("b1", "v1") == "viewer"
    assert bu.role_of("b1", "mg1") == "manager"
    assert bu.role_of("b1", "rv1") is None                  # revoked = no role
    assert bu.role_of("b1", "stranger") is None
    assert bu.require_role("b1", "mg1", "manager") == "manager"
    with pytest.raises(HTTPException) as e:
        bu.require_role("b1", "v1", "member")
    assert e.value.status_code == 403


def test_manager_can_invite_members_not_admins(fake):
    fb = fake
    _member(fb, "mg1", "manager")
    out = asyncio.run(bu.invite("b1", bu.InviteBody(email="new@x.com", role="member"), _stepup("mg1"), _u("mg1")))
    assert out["ok"]
    with pytest.raises(HTTPException) as e:
        asyncio.run(bu.invite("b1", bu.InviteBody(email="boss@x.com", role="admin"), _stepup("mg1"), _u("mg1")))
    assert e.value.status_code == 403
    # Owner can invite admins; viewer roles are inviteable now too.
    out2 = asyncio.run(bu.invite("b1", bu.InviteBody(email="cpaview@x.com", role="viewer"), _stepup("owner1"), _u("owner1")))
    assert out2["member"]["role"] == "viewer"


def test_manager_cannot_revoke_admin(fake):
    fb = fake
    _member(fb, "mg1", "manager")
    _member(fb, "ad1", "admin")
    with pytest.raises(HTTPException) as e:
        bu.revoke("m_ad1", "b1", _u("mg1"))
    assert e.value.status_code == 403
    out = bu.revoke("m_ad1", "b1", _u("owner1"))            # owner can
    assert out["ok"]


def test_accountant_overview_access_and_shape(fake):
    fb = fake
    fb.rows("business_collaborators").append({
        "id": "c1", "business_id": "b1", "user_id": "cpa1",
        "role": "accountant", "status": "active"})
    fb.rows("accounting_periods").append({
        "id": "p1", "business_id": "b1", "period_type": "month",
        "period_start": "2026-06-01", "period_end": "2026-06-30", "status": "open"})
    fb.rows("plaid_transactions").append({
        "transaction_id": "t1", "business_id": "b1", "amount": -100,
        "pending": False, "excluded_from_books": False,
        "reconciliation_status": "unmatched", "business_category": None})
    out = bc.accountant_overview("b1", _u("cpa1"))
    assert out["ok"] and out["is_owner"] is False
    assert out["reconciliation_queue"] == 1
    assert out["uncategorized"] == 1
    assert len(out["periods"]) == 1
    owner_view = bc.accountant_overview("b1", _u("owner1"))
    assert owner_view["is_owner"] is True
    with pytest.raises(HTTPException) as e:
        bc.accountant_overview("b1", _u("stranger"))
    assert e.value.status_code == 403


def test_an_invite_can_carry_a_churchs_office_lane(fake):
    """Kevin 2026-10-28: "make these roles for admin so all i have to do is
    assign them to the person": a lane sets the login's role and areas, so
    it's set up the moment they accept (church_areas.LANES)."""
    fb = fake
    fb.rows("businesses")[0]["type"] = "ministry"
    out = asyncio.run(bu.invite("b1", bu.InviteBody(email="ruth@x.com", lane="people_care"), _stepup("owner1"), _u("owner1")))
    assert out["lane"] == "people_care" and out["member"]["role"] == "manager"
    assert out["member"]["areas"] == ["people_care", "kids_youth", "groups_classes"]
    t = asyncio.run(bu.invite("b1", bu.InviteBody(email="minnie@x.com", role="viewer", lane="treasurer"),
                              _stepup("owner1"), _u("owner1")))
    assert t["member"]["role"] == "admin" and "areas" not in t["member"], "the lane sets the role; an admin keeps all"
    plain = asyncio.run(bu.invite("b1", bu.InviteBody(email="plain@x.com", role="member"), _stepup("owner1"), _u("owner1")))
    assert plain["lane"] is None and "areas" not in plain["member"], "no lane: as before"
    _member(fb, "mg1", "manager")
    with pytest.raises(HTTPException) as e:
        asyncio.run(bu.invite("b1", bu.InviteBody(email="x@x.com", lane="treasurer"), _stepup("mg1"), _u("mg1")))
    assert e.value.status_code == 403, "the treasurer is an admin: a manager can't invite one"
    with pytest.raises(HTTPException) as e:
        asyncio.run(bu.invite("b1", bu.InviteBody(email="y@x.com", lane="the_moon"), _stepup("owner1"), _u("owner1")))
    assert e.value.status_code == 400
    fb.rows("businesses")[0]["type"] = "salon"
    with pytest.raises(HTTPException) as e:
        asyncio.run(bu.invite("b1", bu.InviteBody(email="z@x.com", lane="people_care"), _stepup("owner1"), _u("owner1")))
    assert e.value.status_code == 400, "lanes are a church's"
    assert not any(r.get("invited_email") in ("x@x.com", "y@x.com", "z@x.com") for r in fb.rows("business_users"))
