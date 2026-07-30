"""7/30 tier arc — require_units / require_live_access: the expensive
surfaces (compose, director, Chief backend, campaigns, MCP) finally
consult the allowance and the subscription state. Dormant behind
BILLING_ENFORCE like every gate in billing_limits."""
from __future__ import annotations

import asyncio
import sys
import pathlib
from datetime import datetime, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import billing_limits as bl  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


class _User:
    id = "owner1"
    email = "owner1@x.com"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    for k in ("BILLING_ENFORCE", "STRIPE_PRICE_ID_STARTER"):
        monkeypatch.delenv(k, raising=False)
    return fb


def _biz(fb, bid, *, plan=None, status="active"):
    fb.rows("businesses").append({
        "id": bid, "owner_id": "owner1", "is_active": True, "name": bid,
        "subscription_status": status, "subscription_plan": plan,
        "comp_tier": None, "settings": {}})


def _enforce(monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")


def test_require_units_dormant_and_enforced(fake, monkeypatch):
    fb = fake
    _biz(fb, "b1", plan="price_starter")
    now_iso = datetime.now(timezone.utc).replace(day=2).isoformat()
    for i in range(305):                       # past the 300 starter allowance
        fb.rows("api_usage").append({"id": f"u{i}", "business_id": "b1",
                                     "created_at": now_iso,
                                     "endpoint": "/ai/proxy"})
    bl.require_units("b1")                     # dormant: no raise
    _enforce(monkeypatch)
    with pytest.raises(HTTPException) as e:
        bl.require_units("b1")
    assert e.value.status_code == 402
    assert e.value.detail["error"] == "out_of_units"
    # Banked credits unblock without any other change.
    fb.rows("credit_ledger").append({"id": "c1", "business_id": "b1",
                                     "delta_units": 100, "kind": "purchase",
                                     "source": "pack:test"})
    bl.require_units("b1")                     # draws down instead of blocking


def test_require_live_access_states(fake, monkeypatch):
    fb = fake
    _biz(fb, "dead", plan=None, status="canceled")
    _biz(fb, "grace", plan="price_starter", status="past_due")
    _biz(fb, "comp", plan=None, status=None)
    fb.rows("businesses")[-1]["comp_tier"] = "professional"
    bl.require_live_access("dead")             # dormant: no raise
    _enforce(monkeypatch)
    with pytest.raises(HTTPException) as e:
        bl.require_live_access("dead")
    assert e.value.status_code == 402
    assert e.value.detail["error"] == "subscription_locked"
    bl.require_live_access("grace")            # grace warns, never blocks
    bl.require_live_access("comp")             # comp accounts never lock


def test_campaign_launch_blocked_when_locked(fake, monkeypatch):
    import campaigns_router as cr
    fb = fake
    _biz(fb, "b1", plan=None, status="canceled")
    fb.rows("campaigns").append({
        "id": "camp1", "business_id": "b1", "status": "draft",
        "touches": [{"kind": "sms", "body": "hi", "day": 0}],
        "audience": {"kind": "silent", "days_silent": 30}})
    _enforce(monkeypatch)
    with pytest.raises(HTTPException) as e:
        asyncio.run(cr.launch_campaign("camp1", cr.LaunchBody(), _User()))
    assert e.value.status_code == 402
    assert e.value.detail["error"] == "subscription_locked"


def test_director_refine_gated_on_units(fake, monkeypatch):
    from agents.director_agent import router as dr
    monkeypatch.setattr(bl, "chief_can_send", lambda bid: False)
    with pytest.raises(HTTPException) as e:
        dr.refine(dr.RefineRequest(business_id="b1", user_text="fix it"))
    assert e.value.status_code == 402
    assert e.value.detail["error"] == "out_of_units"
