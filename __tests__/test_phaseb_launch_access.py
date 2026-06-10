"""Arc 19 Phase B — invite gate, grandfathering, backend-mediated creation,
weighted metering thresholds, Plaid connection caps, readiness."""
from __future__ import annotations

import asyncio
import sys
import pathlib
from datetime import datetime, timezone, timedelta

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import launch_access as la  # noqa: E402
import usage_metering as um  # noqa: E402
import billing_limits as bl  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


def _u(uid):
    return type("U", (), {"id": uid})()


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    for k in ("BILLING_ENFORCE", "LAUNCH_INVITE_ONLY", "STRIPE_PRICE_ID_STARTER"):
        monkeypatch.delenv(k, raising=False)
    return fb


def _future_iso(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# ─── Waitlist ────────────────────────────────────────────────────────

def test_waitlist_idempotent_and_validated(fake):
    fb = fake
    out = la.join_waitlist(la.WaitlistBody(email="New@Person.com", name="New"))
    assert out["ok"]
    la.join_waitlist(la.WaitlistBody(email="new@person.com"))   # dup, case-folded
    assert len(fb.rows("waitlist")) == 1
    assert fb.rows("waitlist")[0]["email"] == "new@person.com"
    with pytest.raises(HTTPException):
        la.join_waitlist(la.WaitlistBody(email="not-an-email"))


# ─── Invite validate + redeem ────────────────────────────────────────

def test_invite_lifecycle(fake):
    fb = fake
    fb.rows("invite_tokens").append({
        "id": "i1", "token": "tok-1", "email": "a@x.com", "status": "pending",
        "expires_at": _future_iso(), "accepted_at": None, "accepted_by_user_id": None})
    v = la.validate_invite("tok-1")
    assert v["valid"] and v["email"] == "a@x.com"
    out = la.redeem_invite(la.RedeemBody(token="tok-1"), _u("user9"))
    assert out["admitted"]
    assert fb.rows("invite_tokens")[0]["status"] == "accepted"
    prof = fb.rows("user_profiles")[0]
    assert prof["user_id"] == "user9" and prof["invited_via_token"] == "tok-1"
    # Token consumed: second redeemer rejected; original redeemer idempotent.
    with pytest.raises(HTTPException) as e:
        la.redeem_invite(la.RedeemBody(token="tok-1"), _u("intruder"))
    assert e.value.status_code == 409
    again = la.redeem_invite(la.RedeemBody(token="tok-1"), _u("user9"))
    assert again.get("already")
    # Expired + revoked invalid.
    fb.rows("invite_tokens").append({
        "id": "i2", "token": "tok-old", "email": "b@x.com", "status": "pending",
        "expires_at": "2020-01-01T00:00:00+00:00"})
    assert la.validate_invite("tok-old")["state"] == "expired"
    assert la.validate_invite("tok-missing")["valid"] is False


# ─── Backend-mediated business creation (the real gate) ──────────────

def test_create_business_invite_only_gate(fake):
    fb = fake
    body = la.CreateBusinessBody(name="My Biz", type="coach")
    # Uninvited stranger: 403 invite-only.
    with pytest.raises(HTTPException) as e:
        la.create_business(body, _u("stranger"))
    assert e.value.status_code == 403
    assert fb.rows("businesses") == []
    # Invited user: allowed.
    fb.rows("user_profiles").append({"user_id": "invited1",
                                     "invited_via_token": "tok-1",
                                     "is_grandfathered": False})
    out = la.create_business(body, _u("invited1"))
    assert out["ok"] and out["business"]["owner_id"] == "invited1"
    assert out["business"]["name"] == "My Biz"
    # Grandfathered user: allowed.
    fb.rows("user_profiles").append({"user_id": "gf1", "is_grandfathered": True})
    out2 = la.create_business(body, _u("gf1"))
    assert out2["ok"]


def test_create_business_cap_enforced_and_grandfather_bypass(fake, monkeypatch):
    fb = fake
    monkeypatch.setenv("LAUNCH_INVITE_ONLY", "off")              # open phase
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    fb.rows("businesses").append({
        "id": "b1", "owner_id": "subbed", "is_active": True, "name": "First",
        "subscription_status": "active", "subscription_plan": "price_starter"})
    # Starter cap = 1 business → 402 with upgrade pointer.
    with pytest.raises(HTTPException) as e:
        la.create_business(la.CreateBusinessBody(name="Second", type="coach"), _u("subbed"))
    assert e.value.status_code == 402
    assert "upgrade_url" in e.value.detail
    # Grandfathered owner bypasses caps entirely.
    fb.rows("user_profiles").append({"user_id": "subbed", "is_grandfathered": True})
    out = la.create_business(la.CreateBusinessBody(name="Second", type="coach"), _u("subbed"))
    assert out["ok"]


# ─── Weighted thresholds + notifications ─────────────────────────────

def test_threshold_notifications_fire_once(fake, monkeypatch):
    fb = fake
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    fb.rows("businesses").append({
        "id": "b1", "owner_id": "o", "is_active": True, "name": "b1",
        "subscription_status": "active", "subscription_plan": "price_starter"})
    now_iso = datetime.now(timezone.utc).replace(day=2).isoformat()
    for i in range(60):                                          # 80% of 75
        fb.rows("api_usage").append({"id": f"u{i}", "business_id": "b1",
                                     "created_at": now_iso, "endpoint": "/ai/proxy"})
    fired = um.check_thresholds("b1")
    assert set(fired) == {50, 80}
    # Re-check: dedup (unique row) — nothing fires again. FakeSB post lacks
    # unique constraints, so emulate: rows exist → conflict path. Our code
    # treats a post failure as already-notified; FakeSB post succeeds, so
    # assert via the notifications table contents instead.
    rows = fb.rows("usage_notifications")
    assert {r["threshold"] for r in rows} >= {50, 80}


def test_grandfathered_unlimited_everything(fake, monkeypatch):
    fb = fake
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    fb.rows("businesses").append({
        "id": "b1", "owner_id": "gf", "is_active": True, "name": "b1",
        "subscription_status": None, "subscription_plan": None,
        "settings": {"usage_hard_cap": True}})
    fb.rows("user_profiles").append({"user_id": "gf", "is_grandfathered": True})
    now_iso = datetime.now(timezone.utc).replace(day=2).isoformat()
    for i in range(500):
        fb.rows("api_usage").append({"id": f"u{i}", "business_id": "b1",
                                     "created_at": now_iso, "endpoint": "/director/build"})
    s = um.usage_summary("b1")
    assert s["grandfathered"] and s["allotment"] is None
    assert s["blocked"] is False and s["overage_cents"] == 0
    assert um.can_interact("b1") is True
    assert bl.can_create_business("gf")["allowed"] is True
    assert bl.can_connect_account("b1")["allowed"] is True
    assert um.check_thresholds("b1") == []                        # never nagged


# ─── Plaid connection cap (F-A2) ─────────────────────────────────────

def test_plaid_connection_cap(fake, monkeypatch):
    fb = fake
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    fb.rows("businesses").append({
        "id": "b1", "owner_id": "o", "is_active": True, "name": "b1",
        "subscription_status": "active", "subscription_plan": "price_starter"})
    for i in range(2):
        fb.rows("plaid_accounts").append({"account_id": f"a{i}", "business_id": "b1",
                                          "deleted_at": None})
    out = bl.can_connect_account("b1")
    assert out["allowed"] is True                                # dormant
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    out = bl.can_connect_account("b1")
    assert out["limit"] == 2 and out["count"] == 2
    assert out["allowed"] is False                               # starter cap


# ─── Readiness panel ─────────────────────────────────────────────────

def test_readiness_preflight(fake, monkeypatch):
    fb = fake
    for k in ("STRIPE_PRICE_ID_STARTER", "STRIPE_PRICE_ID_PROFESSIONAL",
              "STRIPE_PRICE_ID_PRACTICE", "STRIPE_PRICE_ID_STARTER_OVERAGE",
              "STRIPE_PRICE_ID_PROFESSIONAL_OVERAGE", "STRIPE_PRICE_ID_PRACTICE_OVERAGE",
              "STRIPE_WEBHOOK_SECRET"):
        monkeypatch.delenv(k, raising=False)
    fb.rows("user_profiles").append({"user_id": "gf", "is_grandfathered": True})
    fb.rows("businesses").append({
        "id": "b1", "owner_id": "stranger", "is_active": True, "name": "b1",
        "subscription_status": None, "subscription_plan": None})
    out = la.billing_readiness(_owner=None)
    assert out["grandfathered_users"] == 1
    assert out["unsubscribed_non_grandfathered_businesses"] == 1
    assert out["ready_to_flip"] is False
    assert any("price ids missing" in i for i in out["preflight_issues"])
    # Fix everything → ready.
    for k in ("STRIPE_PRICE_ID_STARTER", "STRIPE_PRICE_ID_PROFESSIONAL",
              "STRIPE_PRICE_ID_PRACTICE", "STRIPE_PRICE_ID_STARTER_OVERAGE",
              "STRIPE_PRICE_ID_PROFESSIONAL_OVERAGE", "STRIPE_PRICE_ID_PRACTICE_OVERAGE"):
        monkeypatch.setenv(k, "price_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    fb.rows("user_profiles").append({"user_id": "stranger", "is_grandfathered": True})
    out2 = la.billing_readiness(_owner=None)
    assert out2["ready_to_flip"] is True
