"""7/31 seat-access arc — the routers honor the multi-role ladder
(viewer < member < manager < admin < owner) instead of owner-only.
Matrix (Kevin-approved): viewer reads; member does everyday work
(compose, budgets, statements, Chief); manager escalations (GL verify,
period close, contractor onboarding, campaign launch/pause); admin
money-moving/destructive (GL backfill/reverse, contractor pay,
collaborator management); TIN surfaces stay owner-only."""
from __future__ import annotations

import asyncio
import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402


def _user(uid: str):
    return type("U", (), {"id": uid, "email": f"{uid}@x.com"})()


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.delenv("BILLING_ENFORCE", raising=False)
    fb.rows("businesses").append({
        "id": "b1", "owner_id": "owner1", "is_active": True, "name": "b1",
        "type": "coach", "settings": {}, "subscription_status": None,
        "subscription_plan": None, "comp_tier": None})
    for uid, role in (("v1", "viewer"), ("m1", "member"),
                      ("g1", "manager"), ("a1", "admin")):
        fb.rows("business_users").append({
            "id": f"seat_{uid}", "business_id": "b1", "user_id": uid,
            "role": role, "status": "active"})
    # An INVITED (not yet active) seat must count for nothing.
    fb.rows("business_users").append({
        "id": "seat_p1", "business_id": "b1", "user_id": "p1",
        "role": "admin", "status": "invited"})
    return fb


def test_gl_access_ladder(fake):
    import gl_router as gl
    assert gl._access("b1", _user("owner1"), "admin")["id"] == "b1"
    assert gl._access("b1", _user("v1"), "viewer")["id"] == "b1"
    with pytest.raises(HTTPException) as e:
        gl._access("b1", _user("v1"), "admin")           # viewer can't rebuild
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        gl._access("b1", _user("g1"), "admin")           # manager can't either
    assert e.value.status_code == 403
    assert gl._access("b1", _user("g1"), "manager")["id"] == "b1"
    assert gl._access("b1", _user("a1"), "admin")["id"] == "b1"
    with pytest.raises(HTTPException) as e:
        gl._access("b1", _user("p1"), "viewer")          # invited ≠ active
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        gl._access("b1", _user("stranger"), "viewer")
    assert e.value.status_code == 403


def test_periods_and_contractors_ladder(fake):
    import accounting_periods_router as ap
    import contractors_router as ct
    assert ap._access("b1", _user("m1"), "viewer")["id"] == "b1"
    with pytest.raises(HTTPException):
        ap._access("b1", _user("m1"), "manager")         # member can't close
    assert ap._access("b1", _user("g1"), "manager")["id"] == "b1"

    fake.rows("contractors").append({
        "id": "c1", "business_id": "b1", "name": "Sub"})
    assert ct._owner_for_contractor("c1", _user("v1"))["id"] == "c1"   # read
    with pytest.raises(HTTPException):
        ct._owner_for_contractor("c1", _user("g1"), min_role="admin")  # pay
    assert ct._owner_for_contractor("c1", _user("a1"),
                                    min_role="admin")["id"] == "c1"
    with pytest.raises(HTTPException):
        ct._owner_for_contractor("c1", _user("a1"), min_role="owner")  # TIN
    assert ct._owner_for_contractor("c1", _user("owner1"),
                                    min_role="owner")["id"] == "c1"


def test_campaign_pause_by_manager_but_not_member(fake):
    import campaigns_router as cr
    fake.rows("campaigns").append({
        "id": "camp1", "business_id": "b1", "status": "running",
        "touches": [], "audience": {}})
    with pytest.raises(HTTPException) as e:
        asyncio.run(cr.pause_campaign("camp1", _user("m1")))
    assert e.value.status_code == 403
    out = asyncio.run(cr.pause_campaign("camp1", _user("g1")))
    assert out["ok"] is True
    assert fake.rows("campaigns")[0]["status"] == "paused"


def test_collaborator_management_is_admin(fake):
    import business_collaborators_router as bc
    with pytest.raises(HTTPException) as e:
        bc._owner("b1", _user("g1"))
    assert e.value.status_code == 403
    assert bc._owner("b1", _user("a1"))["id"] == "b1"
    assert bc._owner("b1", _user("owner1"))["id"] == "b1"


def test_composer_gate_is_member(fake):
    import site_composer as sc
    with pytest.raises(HTTPException) as e:
        sc._require_owner("b1", "v1")                    # viewer can't build
    assert e.value.status_code == 403
    sc._require_owner("b1", "m1")                        # member builds
    sc._require_owner("b1", "owner1")
    with pytest.raises(HTTPException):
        sc._require_owner("b1", "stranger")
