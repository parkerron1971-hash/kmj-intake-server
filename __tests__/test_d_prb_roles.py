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
    out = asyncio.run(bu.invite("b1", bu.InviteBody(email="new@x.com", role="member"), _u("mg1")))
    assert out["ok"]
    with pytest.raises(HTTPException) as e:
        asyncio.run(bu.invite("b1", bu.InviteBody(email="boss@x.com", role="admin"), _u("mg1")))
    assert e.value.status_code == 403
    # Owner can invite admins; viewer roles are inviteable now too.
    out2 = asyncio.run(bu.invite("b1", bu.InviteBody(email="cpaview@x.com", role="viewer"), _u("owner1")))
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
