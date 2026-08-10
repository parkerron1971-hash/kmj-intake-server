"""Credits-surfacing arc (2026-08-01) — the practitioner-facing credits
read (GET /billing/credits/{business_id}), the buy flow (pack checkout →
webhook → credit_ledger grant, idempotent), and the low-balance crossing
signal. Consumption order under test throughout: monthly allowance FIRST,
packs only beyond it (Pricing v2 accounting)."""
from __future__ import annotations

import asyncio
import json
import sys
import pathlib
from datetime import datetime, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import usage_metering as um  # noqa: E402
import credit_ledger as cl  # noqa: E402
import stripe_billing as sb  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402

@pytest.fixture(autouse=True)
def _pin_chat_price(monkeypatch):
    """These tests are about MECHANICS — thresholds firing once, drawdown
    order, weighted totals — and their expected numbers were written when
    a Chief turn cost 1 credit. It went to 8 on 2026-08-10, priced against
    measured cost.

    Pinning the dial keeps each assertion measuring the behaviour it
    names instead of re-encoding today's price list; a notification test
    should not change meaning because pricing moved. The price itself is
    covered by test_chat_repricing.py.
    """
    monkeypatch.setenv("PRICE_CHAT_PRICE", "1")




class _User:
    def __init__(self, uid, email="u@x.com"):
        self.id = uid
        self.email = email


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients

    # Emulate the credit_ledger UNIQUE(stripe_payment_id) index: a dup
    # insert returns None (the helper's non-2xx shape), like PostgREST 409.
    def post(path, body, prefer="rep"):
        table = path.split("?", 1)[0].lstrip("/")
        if table == "credit_ledger" and body.get("stripe_payment_id"):
            for r in fb.rows("credit_ledger"):
                if r.get("stripe_payment_id") == body["stripe_payment_id"]:
                    return None
        return fb.post(path, body, prefer)

    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    for k in ("BILLING_ENFORCE",):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    # The Starter grant became a DIAL on 2026-08-08 and its shipped
    # default moved 300 -> 3,000. Every case in this file is about the
    # allowance-then-packs draw-down ORDER and the low-credit crossing
    # EDGE, not about the tank size — so pin the old number here and
    # keep the arithmetic in each test readable, rather than generating
    # ten times the rows to say the same thing.
    monkeypatch.setenv("CREDITS_STARTER_CREDITS", "300")
    return fb


def _biz(fb, bid="b1", owner="o1", plan="price_starter", status="active"):
    fb.rows("businesses").append({
        "id": bid, "owner_id": owner, "is_active": True, "name": bid,
        "subscription_status": status, "subscription_plan": plan,
        "comp_tier": None, "settings": {}})


def _use(fb, n, bid="b1", endpoint="/ai/proxy"):
    now_iso = datetime.now(timezone.utc).isoformat()
    start = len(fb.rows("api_usage"))
    for i in range(n):
        fb.rows("api_usage").append({
            "id": f"u{start + i}", "business_id": bid,
            "created_at": now_iso, "endpoint": endpoint})


def _burn_rows(fb):
    return [r for r in fb.rows("credit_ledger") if r.get("kind") == "burn"]


# ═══ Balance math — allowance first, packs after ═════════════════════

def test_overview_allowance_first_then_packs(fake):
    fb = fake
    _biz(fb)
    fb.rows("credit_ledger").append({
        "id": "c1", "business_id": "b1", "delta_units": 100,
        "kind": "purchase", "source": "stripe:pack_small",
        "stripe_payment_id": "pi_seed"})

    # Inside the allowance: packs completely untouched.
    _use(fb, 100)
    ov = um.credits_overview("b1")
    assert ov["ok"] and ov["plan"] == "starter"
    assert ov["monthly"]["allowance"] == 300
    assert ov["monthly"]["used"] == 100
    assert ov["monthly"]["remaining"] == 200
    assert ov["packs"] == {"granted": 100, "used": 0, "remaining": 100}
    assert ov["total_remaining"] == 300
    assert _burn_rows(fb) == []          # consumption-order proof #1
    assert ov["monthly"]["resets_at"] > um._month_start_iso()

    # Past the allowance: ONLY the overage draws down the pack.
    _use(fb, 250)                        # 350 total → 50 beyond allowance
    ov = um.credits_overview("b1")
    assert ov["monthly"]["used"] == 300 and ov["monthly"]["remaining"] == 0
    assert ov["monthly"]["used_raw"] == 350
    assert ov["packs"] == {"granted": 100, "used": 50, "remaining": 50}
    assert ov["total_remaining"] == 50
    burns = _burn_rows(fb)               # consumption-order proof #2
    assert len(burns) == 1 and int(burns[0]["delta_units"]) == -50


def test_overview_monthly_grants_top_up_allowance(fake):
    fb = fake
    _biz(fb)
    fb.rows("usage_grants").append({
        "id": "g1", "business_id": "b1", "units": 100, "month": None})
    ov = um.credits_overview("b1")
    assert ov["monthly"]["allowance"] == 400   # 300 plan + 100 grant


def test_overview_grandfathered_and_no_plan(fake):
    fb = fake
    _biz(fb, bid="gfbiz", owner="gf", plan=None, status=None)
    fb.rows("user_profiles").append({"user_id": "gf", "is_grandfathered": True})
    ov = um.credits_overview("gfbiz")
    assert ov["grandfathered"] is True
    assert ov["monthly"]["allowance"] is None
    assert ov["total_remaining"] is None and ov["low"] is False

    _biz(fb, bid="freebiz", owner="o2", plan=None, status=None)
    fb.rows("credit_ledger").append({
        "id": "c2", "business_id": "freebiz", "delta_units": 40,
        "kind": "grant", "source": "beta"})
    ov2 = um.credits_overview("freebiz")
    assert ov2["monthly"]["allowance"] is None
    assert ov2["packs"]["remaining"] == 40
    assert ov2["total_remaining"] == 40


# ═══ Endpoint auth — member+ (role-ranked), never public ═════════════

def test_credits_endpoint_role_gate(fake):
    fb = fake
    _biz(fb)
    fb.rows("business_users").append({
        "id": "s1", "business_id": "b1", "user_id": "m1",
        "status": "active", "role": "member"})
    fb.rows("business_users").append({
        "id": "s2", "business_id": "b1", "user_id": "v1",
        "status": "active", "role": "viewer"})

    out = asyncio.run(sb.credits_overview_endpoint("b1", _User("o1")))
    assert out["ok"] and out["monthly"]["allowance"] == 300
    out2 = asyncio.run(sb.credits_overview_endpoint("b1", _User("m1")))
    assert out2["ok"]
    with pytest.raises(HTTPException) as e:
        asyncio.run(sb.credits_overview_endpoint("b1", _User("v1")))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        asyncio.run(sb.credits_overview_endpoint("b1", _User("stranger")))
    assert e.value.status_code == 403


# ═══ Buy flow — pack checkout session ════════════════════════════════

def test_credit_checkout_builds_pack_session(fake, monkeypatch):
    fb = fake
    _biz(fb)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")

    async def fake_load(bid):
        return {"id": bid, "owner_id": "o1", "name": "B",
                "stripe_customer_id": None}
    captured = {}

    async def fake_stripe_post(path, form):
        captured["path"], captured["form"] = path, form
        return {"url": "https://stripe.example/cs_1", "id": "cs_1"}

    monkeypatch.setattr(sb, "_load_business", fake_load)
    monkeypatch.setattr(sb, "_stripe_post", fake_stripe_post)

    out = asyncio.run(sb.create_credit_checkout(
        sb.CreditCheckoutBody(business_id="b1", pack="small"),
        _User("o1", "o1@x.com")))
    assert out["url"] and out["id"] == "cs_1"
    form = captured["form"]
    assert captured["path"] == "/checkout/sessions"
    assert form["mode"] == "payment"
    assert form["metadata"]["kind"] == "credit_pack"
    assert form["metadata"]["credit_pack"] == "small"
    assert form["metadata"]["business_id"] == "b1"
    pd = form["line_items"][0]["price_data"]
    assert pd["unit_amount"] == cl.CREDIT_PACKS["small"]["cents"]

    # Unknown pack → 400; non-owner → 403.
    with pytest.raises(HTTPException) as e:
        asyncio.run(sb.create_credit_checkout(
            sb.CreditCheckoutBody(business_id="b1", pack="mega"), _User("o1")))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        asyncio.run(sb.create_credit_checkout(
            sb.CreditCheckoutBody(business_id="b1", pack="small"),
            _User("intruder")))
    assert e.value.status_code == 403


# ═══ Webhook fulfillment — grant lands, retries are no-ops ═══════════

def _make_request(body: bytes):
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": [],
                    "path": "/billing/webhook", "query_string": b""}, receive)


def _pack_event(evt_id, session_id, pi, *, etype="checkout.session.completed",
                paid=True):
    obj = {"id": session_id, "payment_intent": pi,
           "metadata": {"kind": "credit_pack", "credit_pack": "small",
                        "credit_units": "100", "business_id": "b1"}}
    if etype == "checkout.session.completed":
        obj["payment_status"] = "paid" if paid else "unpaid"
    return {"id": evt_id, "type": etype, "livemode": False,
            "data": {"object": obj}}


@pytest.fixture
def webhook_env(fake, monkeypatch):
    recorded = []

    async def fake_record(event, business_id, error=None):
        recorded.append({"id": event.get("id"), "business_id": business_id,
                         "error": error})

    monkeypatch.setattr(sb, "_record_webhook", fake_record)
    monkeypatch.setattr(sb, "_verify_stripe_signature",
                        lambda payload, sig, secret: None)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    return fake, recorded


def test_webhook_grants_pack_idempotently(webhook_env):
    fb, recorded = webhook_env
    _biz(fb)
    event = _pack_event("evt_1", "cs_1", "pi_1")
    body = json.dumps(event).encode()

    # Pack units are a dial (rescaled 2026-08-08) — assert the grant
    # matches the configured pack, not a literal that repricing breaks.
    small = cl.credit_packs()["small"]["units"]
    out = asyncio.run(sb.stripe_webhook(_make_request(body), "t=1,v1=x"))
    assert out == {"received": True}
    assert cl.balance("b1") == small
    grants = [r for r in fb.rows("credit_ledger") if r.get("kind") == "purchase"]
    assert len(grants) == 1 and grants[0]["stripe_payment_id"] == "pi_1"

    # Stripe retry: same event replays — the UNIQUE payment id makes the
    # grant a recognized no-op, and the webhook still answers clean.
    out2 = asyncio.run(sb.stripe_webhook(_make_request(body), "t=1,v1=x"))
    assert out2 == {"received": True}
    assert cl.balance("b1") == small
    assert all(r["error"] is None for r in recorded)


def test_webhook_async_payment_and_unpaid_guard(webhook_env):
    fb, _recorded = webhook_env
    _biz(fb)
    # Unpaid completed session (async payment method): no grant yet.
    unpaid = json.dumps(_pack_event("evt_a", "cs_2", "pi_2", paid=False)).encode()
    asyncio.run(sb.stripe_webhook(_make_request(unpaid), "t=1,v1=x"))
    assert cl.balance("b1") == 0
    # The delayed success event fulfills.
    done = json.dumps(_pack_event(
        "evt_b", "cs_2", "pi_2",
        etype="checkout.session.async_payment_succeeded")).encode()
    asyncio.run(sb.stripe_webhook(_make_request(done), "t=1,v1=x"))
    assert cl.balance("b1") == cl.credit_packs()["small"]["units"]


# ═══ Low-balance signal — crossing edge, once per cycle ══════════════

def _low_notifs(fb):
    return [r for r in fb.rows("chief_notifications")
            if r.get("type") == "low_credits"]


def test_low_credit_crossing_fires_once_then_rearms_on_topup(fake):
    fb = fake
    _biz(fb)
    # Starter 300, no packs → capacity 300, 20% edge at 60 remaining.
    _use(fb, 239)                                  # remaining 61 — above
    assert um.check_low_credit("b1") is False
    assert _low_notifs(fb) == []

    _use(fb, 1)                                    # remaining 60 — the edge
    assert um.check_low_credit("b1") is True
    notifs = _low_notifs(fb)
    assert len(notifs) == 1
    assert "60 left" in notifs[0]["title"]

    # Same state re-checked (double hook / race): still exactly one.
    assert um.check_low_credit("b1") is False
    _use(fb, 1)                                    # now below the edge
    assert um.check_low_credit("b1") is False
    assert len(_low_notifs(fb)) == 1

    # A pack purchase raises capacity — a fresh dip legitimately re-alerts.
    fb.rows("credit_ledger").append({
        "id": "c9", "business_id": "b1", "delta_units": 100,
        "kind": "purchase", "source": "stripe:pack_small",
        "stripe_payment_id": "pi_topup"})
    _use(fb, 79)                                   # 320 used → remaining 80
    assert um.check_low_credit("b1") is True       # capacity 400, edge at 80
    assert len(_low_notifs(fb)) == 2


def test_low_credit_skips_grandfathered_and_rides_check_thresholds(fake):
    fb = fake
    _biz(fb, bid="gfbiz", owner="gf")
    fb.rows("user_profiles").append({"user_id": "gf", "is_grandfathered": True})
    _use(fb, 300, bid="gfbiz")
    assert um.check_low_credit("gfbiz") is False
    assert _low_notifs(fb) == []

    # The hook: check_thresholds (called after every metered action)
    # carries the low-credit check with it.
    _biz(fb, bid="b2", owner="o2")
    _use(fb, 240, bid="b2")                        # remaining 60 = the edge
    um.check_thresholds("b2")
    assert len([r for r in _low_notifs(fb)
                if r["business_id"] == "b2"]) == 1
