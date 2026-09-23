"""The Founding Charter on /billing/success.

A founder-seat checkout is marked founder_seat=1 at session creation, and
when that session comes back finished the success page hands the new
holder their charter: their business name, their seat number, the locked
price. Every other return (plans, credits, processing, nothing readable)
keeps the plain page, and any failure building the charter falls back to
it. The charter claims nothing that did not happen: no Hedera anchor.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import founder_charter  # noqa: E402
import pricing_config  # noqa: E402
import stripe_billing as sb  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402

FOUNDER_PRICE = "price_founder_test"


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(sb.router)
    return TestClient(app)


def _session(**over):
    s = {
        "id": "cs_test_founder",
        "mode": "subscription",
        "status": "complete",
        "payment_status": "paid",
        "subscription": "sub_123",
        "amount_total": 9900,
        "metadata": {"business_id": "biz-1", "auth_user_id": "u-1", "founder_seat": "1"},
    }
    s.update(over)
    return s


@pytest.fixture()
def wire(monkeypatch):
    """Patch every network helper the success page reaches for. Returns a
    dict the test edits: the session, the business row, the seat count."""
    state = {
        "session": _session(),
        "biz": {"id": "biz-1", "name": "Bright Path Coaching", "subscription_plan": FOUNDER_PRICE},
        "taken": 7,
    }
    monkeypatch.setenv("STRIPE_PRICE_ID_FOUNDER", FOUNDER_PRICE)
    monkeypatch.delenv("FOUNDER_SEAT_LIMIT", raising=False)

    async def peek(sid):
        return state["session"]

    async def load(bid):
        assert bid == "biz-1"
        return state["biz"]

    async def taken():
        return state["taken"]

    monkeypatch.setattr(sb, "_peek_checkout_session", peek)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_founder_seats_taken", taken)
    return state


def _get(client, q="?session_id=cs_test_founder"):
    r = client.get("/billing/success" + q)
    assert r.status_code == 200, r.text[:300]
    assert "text/html" in r.headers.get("content-type", "")
    return r.text


def test_founder_session_shows_the_charter(client, wire):
    html = _get(client)
    assert "Founding Charter" in html
    assert "Bright Path Coaching" in html
    assert "N&ordm; 07 / 50" in html
    assert "Seat 07 of fifty" in html
    price = pricing_config.tier_price_cents()["founder"] // 100
    assert f"${price} a month" in html
    assert f"{pricing_config.founder_credits():,} AI actions / month" in html
    assert "The Solutionist System</text>" in html  # the signature
    assert "Issued by" in html
    assert "payment confirmed" in html
    assert sb.APP_HOME in html
    assert "This tab can be closed" in html
    assert "Hedera" not in html
    assert "draft" not in html.lower()
    assert "You're in." not in html


def test_business_name_is_escaped(client, wire):
    wire["biz"]["name"] = "<script>alert(1)</script> & Co"
    html = _get(client)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; Co" in html


def test_webhook_lag_counts_this_seat_as_the_next_one(client, wire):
    """The redirect can beat the webhook: the business is not on the
    founder price yet, so it is not in the count yet."""
    wire["biz"]["subscription_plan"] = None
    wire["taken"] = 7
    assert "N&ordm; 08 / 50" in _get(client)


def test_seat_number_is_clamped(client, wire):
    wire["taken"] = 0
    assert "N&ordm; 01 / 50" in _get(client)
    wire["taken"] = 50
    wire["biz"]["subscription_plan"] = None
    assert "N&ordm; 50 / 50" in _get(client)


def test_trial_start_is_not_called_a_payment(client, wire):
    wire["session"] = _session(amount_total=0, payment_status="no_payment_required")
    html = _get(client)
    assert "Founding Charter" in html
    assert "your trial has started" in html
    assert "payment confirmed" not in html


def test_non_founder_subscription_is_unchanged(client, wire):
    wire["session"] = _session(metadata={"business_id": "biz-1", "auth_user_id": "u-1"})
    html = _get(client)
    assert "You're in." in html
    assert "Founding Charter" not in html


def test_annual_founder_keeps_the_plain_page(client, wire):
    """The charter quotes a monthly price; an annual seat is not given a
    charter that says the wrong cadence."""
    meta = dict(_session()["metadata"], founder_interval="year")
    wire["session"] = _session(metadata=meta)
    assert "Founding Charter" not in _get(client)


def test_credits_are_unchanged(client, wire):
    wire["session"] = _session(mode="payment")
    html = _get(client, "?credits=1&session_id=cs_test_founder")
    assert "Your credits are on the way." in html
    assert "Founding Charter" not in html


def test_processing_founder_session_is_unchanged(client, wire):
    wire["session"] = _session(status="open", payment_status="unpaid")
    html = _get(client)
    assert "Almost there." in html
    assert "Founding Charter" not in html


def test_missing_or_invalid_session_is_unchanged(client, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    for q in ("", "?session_id=cs_test_unreadable", "?session_id=../../x"):
        html = _get(client, q)
        assert "You're in." in html
        assert "Founding Charter" not in html


def test_a_failure_building_the_charter_falls_back(client, wire, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("render failed")

    monkeypatch.setattr(founder_charter, "render_page", boom)
    html = _get(client)
    assert "You're in." in html
    assert "Founding Charter" not in html


def test_a_missing_business_falls_back(client, wire, monkeypatch):
    async def gone(bid):
        raise sb.HTTPException(404, "Business not found")

    monkeypatch.setattr(sb, "_load_business", gone)
    assert "You're in." in _get(client)


def test_issued_date_and_seat_label():
    import datetime
    assert founder_charter.issued_date(datetime.date(2026, 9, 2)) == "September 2, 2026"
    assert founder_charter.seat_label(7) == "07"
    assert founder_charter.seat_label(50) == "50"


# ─── create_checkout marks the founder session ───────────────────────

def _run_checkout(monkeypatch, plan):
    posted = []

    async def stripe_post(path, data):
        posted.append((path, data))
        return {"id": "cs_test_x", "url": "https://checkout.stripe.test/x"}

    async def load(bid):
        return {"id": bid, "owner_id": "u-1", "name": "Biz", "stripe_customer_id": "cus_1"}

    async def taken():
        return 3

    monkeypatch.setattr(sb, "_stripe_post", stripe_post)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_founder_seats_taken", taken)
    monkeypatch.setenv("STRIPE_PRICE_ID_FOUNDER", FOUNDER_PRICE)
    monkeypatch.setenv("STRIPE_PRICE_ID_PROFESSIONAL", "price_pro_test")
    user = AuthedUser(id="u-1", email="a@b.test", role="authenticated")
    asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id="biz-1", plan=plan), user=user))
    sessions = [d for p, d in posted if p == "/checkout/sessions"]
    assert len(sessions) == 1
    return sessions[0]["metadata"]


def test_founder_checkout_carries_founder_seat(monkeypatch):
    meta = _run_checkout(monkeypatch, "founder")
    assert meta["founder_seat"] == "1"
    assert meta["business_id"] == "biz-1"
    assert meta["auth_user_id"] == "u-1"
    assert "founder_interval" not in meta


def test_normal_plan_checkout_does_not(monkeypatch):
    meta = _run_checkout(monkeypatch, "professional")
    assert "founder_seat" not in meta
    assert meta == {"business_id": "biz-1", "auth_user_id": "u-1"}
