"""One business, one subscription (stripe_billing.create_checkout).

Checkout always makes a new subscription, so "Switch plan" sent there left a
business paying twice, with the row following whichever Stripe wrote last.

  1. A business with a running subscription gets no Checkout. The plan item
     moves to the new price, and any extra logins stay where they are.
  2. A trial stays a trial, and a cancel set for later comes off, because the
     person asked to stay on another plan.
  3. Asking for the plan they're on changes nothing.
  4. A failed payment is fixed first; nothing is written to Stripe.
  5. No subscription (or one that has ended, even if the row is behind) still
     goes to Checkout, so a no-card trial can add its card.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import feature_gates as fg  # noqa: E402
import stripe_billing as sb  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402

USER = AuthedUser(id="u-1", email="pastor@church.test", role="authenticated")
SMALL, GROWING, LOGINS = "price_small", "price_growing", "price_logins"
ITEM_LOGINS = {"id": "si_logins", "quantity": 2, "price": {"id": LOGINS}}
ITEM_SMALL = {"id": "si_plan", "quantity": 1, "price": {"id": SMALL}}
PLANS = {SMALL: "church_small", GROWING: "church_growing"}


def _sub(status="active", items=None):
    return {"id": "sub_1", "status": status,
            "items": {"data": [ITEM_SMALL] if items is None else items}}


@pytest.fixture()
def stripe(monkeypatch):
    world = {"biz": {"id": "biz-1", "owner_id": "u-1", "name": "Grace", "type": "ministry",
                     "stripe_customer_id": "cus_1", "stripe_subscription_id": "sub_1",
                     "subscription_status": "active", "settings": {}},
             "sub": _sub(), "posted": [], "applied": []}

    async def post(path, data):
        world["posted"].append((path, data))
        return {"id": "cs_1", "url": "https://checkout.stripe.test/x"}

    async def get(path, params):
        assert path == "/subscriptions/sub_1"
        return world["sub"]

    async def load(bid):
        return world["biz"]

    async def applied(event, sub, bid):
        world["applied"].append((event, bid))

    monkeypatch.setattr(sb, "_stripe_post", post)
    monkeypatch.setattr(sb, "_stripe_get", get)
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_apply_subscription_state", applied)
    monkeypatch.setattr(sb, "_price_for_plan", lambda plan: "")
    monkeypatch.setattr(fg, "price_to_plan", lambda: PLANS)
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_SMALL", SMALL)
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", GROWING)
    return world


def _checkout(**body):
    body.setdefault("plan", "church_growing")
    return asyncio.run(sb.create_checkout(sb.CheckoutBody(business_id="biz-1", **body), user=USER))


def _writes(world, path):
    return [d for p, d in world["posted"] if p == path]


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_a_running_subscription_moves_and_makes_no_second_one(stripe, status):
    stripe["biz"]["subscription_status"] = status
    stripe["sub"] = _sub(status)
    out = _checkout()
    assert out["switched"] is True and out["changed"] is True and out["plan"] == "church_growing"
    assert "url" not in out
    assert _writes(stripe, "/checkout/sessions") == []
    write = _writes(stripe, "/subscriptions/sub_1")[0]
    assert write["items"] == [{"id": "si_plan", "price": GROWING}]
    assert write["proration_behavior"] == "create_prorations"
    assert "trial_end" not in write
    assert stripe["applied"] == [("customer.subscription.updated", "biz-1")]


def test_extra_logins_stay_put_whichever_item_comes_first(stripe):
    stripe["sub"] = _sub(items=[ITEM_LOGINS, ITEM_SMALL])
    _checkout()
    assert _writes(stripe, "/subscriptions/sub_1")[0]["items"] == [{"id": "si_plan", "price": GROWING}]


def test_a_later_cancel_comes_off_because_they_chose_to_stay(stripe):
    _checkout()
    assert _writes(stripe, "/subscriptions/sub_1")[0]["cancel_at_period_end"] is False


def test_the_plan_they_are_on_changes_nothing(stripe):
    out = _checkout(plan="church_small")
    assert out["switched"] is True and out["changed"] is False
    assert stripe["posted"] == []


@pytest.mark.parametrize("status", ["past_due", "unpaid", "incomplete", "paused"])
def test_a_failed_payment_is_fixed_first(stripe, status):
    stripe["biz"]["subscription_status"] = status
    stripe["sub"] = _sub(status)
    with pytest.raises(HTTPException) as e:
        _checkout()
    assert e.value.status_code == 409 and "Manage Subscription" in e.value.detail
    assert stripe["posted"] == []


def test_a_subscription_with_no_plan_of_ours_is_not_touched(stripe):
    stripe["sub"] = _sub(items=[{"id": "si_x", "price": {"id": "price_other"}}])
    with pytest.raises(HTTPException) as e:
        _checkout()
    assert e.value.status_code == 409
    assert stripe["posted"] == []


def test_a_code_never_goes_quietly_missing(stripe, monkeypatch):
    monkeypatch.setattr(sb, "_price_for_plan", lambda plan: GROWING)
    with pytest.raises(HTTPException) as e:
        _checkout(plan="professional", promotion_code="SAVE")
    assert e.value.status_code == 409
    assert stripe["posted"] == []


@pytest.mark.parametrize("row", [
    {"stripe_subscription_id": None, "subscription_status": "trialing"},   # no-card trial
    {"stripe_subscription_id": "", "subscription_status": None},
    {"stripe_subscription_id": "sub_1", "subscription_status": "canceled"},
])
def test_without_a_running_subscription_checkout_is_still_the_door(stripe, row):
    stripe["biz"].update(row)
    out = _checkout()
    assert out["url"].startswith("https://checkout")
    assert len(_writes(stripe, "/checkout/sessions")) == 1
    assert _writes(stripe, "/subscriptions/sub_1") == []


def test_a_row_behind_stripe_goes_to_checkout(stripe):
    stripe["sub"] = _sub("canceled")
    out = _checkout()
    assert out["url"].startswith("https://checkout")
    assert _writes(stripe, "/subscriptions/sub_1") == []
