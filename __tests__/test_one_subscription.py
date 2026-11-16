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
  6. A dearer plan on the same billing term is paid for that day, and only
     happens if the card takes it. On a yearly plan Stripe's default left the
     difference for the renewal, up to a year away (2026-11-16).
  7. A change of term takes a church's extra office logins with it: Stripe
     holds one subscription to one billing term.
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
SMALL_YEAR, GROWING_YEAR, LOGINS_YEAR = "price_small_year", "price_growing_year", "price_logins_year"


def _a_price(pid, cents, interval="month", count=1):
    return {"id": pid, "unit_amount": cents, "recurring": {"interval": interval, "interval_count": count}}


# The prices as Stripe holds them: what each costs and how often it bills.
PRICES = {p["id"]: p for p in (
    _a_price(SMALL, 7900), _a_price(GROWING, 19900), _a_price(LOGINS, 1500),
    _a_price(SMALL_YEAR, 79000, "year"), _a_price(GROWING_YEAR, 199000, "year"),
    _a_price(LOGINS_YEAR, 15000, "year"))}
ITEM_LOGINS = {"id": "si_logins", "quantity": 2, "price": PRICES[LOGINS]}
ITEM_SMALL = {"id": "si_plan", "quantity": 1, "price": PRICES[SMALL]}
PLANS = {SMALL: "church_small", GROWING: "church_growing",
         SMALL_YEAR: "church_small", GROWING_YEAR: "church_growing"}


def _sub(status="active", items=None):
    return {"id": "sub_1", "status": status,
            "items": {"data": [ITEM_SMALL] if items is None else items}}


@pytest.fixture()
def stripe(monkeypatch):
    world = {"biz": {"id": "biz-1", "owner_id": "u-1", "name": "Grace", "type": "ministry",
                     "stripe_customer_id": "cus_1", "stripe_subscription_id": "sub_1",
                     "subscription_status": "active", "settings": {}},
             "sub": _sub(), "posted": [], "applied": [], "prices": dict(PRICES), "refuse": None}

    async def post(path, data):
        world["posted"].append((path, data))
        if world["refuse"]:
            raise HTTPException(world["refuse"], "Stripe error: card_declined")
        return {"id": "cs_1", "url": "https://checkout.stripe.test/x"}

    async def get(path, params):
        if path.startswith("/prices/"):
            return world["prices"][path.split("/")[-1]]      # KeyError: Stripe can't be read
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
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_ANNUAL", GROWING_YEAR)
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN", LOGINS)
    monkeypatch.delenv("STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL", raising=False)
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
    assert "trial_end" not in write
    assert stripe["applied"] == [("customer.subscription.updated", "biz-1")]


# ─── 6. a dearer plan is paid for the day it is taken ─────────────────

def _yearly(world, pid=SMALL_YEAR):
    world["sub"] = _sub(items=[{"id": "si_plan", "quantity": 1, "price": PRICES[pid]}])


def test_a_dearer_plan_on_the_same_term_is_charged_today(stripe):
    out = _checkout()
    write = _writes(stripe, "/subscriptions/sub_1")[0]
    assert write["proration_behavior"] == "always_invoice"
    assert write["payment_behavior"] == "error_if_incomplete"
    assert out["charged_today"] is True


def test_a_yearly_plan_no_longer_waits_a_year_for_the_difference(stripe):
    _yearly(stripe)
    out = _checkout(plan="church_growing_annual")
    write = _writes(stripe, "/subscriptions/sub_1")[0]
    assert write["items"] == [{"id": "si_plan", "price": GROWING_YEAR}]
    assert write["proration_behavior"] == "always_invoice" and out["charged_today"] is True


def test_a_trial_is_still_charged_nothing(stripe):
    stripe["biz"]["subscription_status"] = "trialing"
    stripe["sub"] = _sub("trialing")
    out = _checkout()
    write = _writes(stripe, "/subscriptions/sub_1")[0]
    assert write["proration_behavior"] == "create_prorations" and "payment_behavior" not in write
    assert out["charged_today"] is False


def test_a_cheaper_plan_leaves_its_credit_for_the_next_bill(stripe):
    stripe["sub"] = _sub(items=[{"id": "si_plan", "quantity": 1, "price": PRICES[GROWING]}])
    out = _checkout(plan="church_small")
    write = _writes(stripe, "/subscriptions/sub_1")[0]
    assert write["proration_behavior"] == "create_prorations" and "payment_behavior" not in write
    assert out["charged_today"] is False


def test_a_refused_card_changes_nothing_and_says_so(stripe):
    stripe["refuse"] = 402
    with pytest.raises(HTTPException) as e:
        _checkout()
    assert e.value.status_code == 402 and e.value.detail == sb.CARD_REFUSED
    assert "Stripe error" not in e.value.detail
    assert stripe["applied"] == []


def test_any_other_stripe_error_is_not_called_a_card_problem(stripe):
    stripe["refuse"] = 400
    with pytest.raises(HTTPException) as e:
        _checkout()
    assert e.value.status_code == 400 and e.value.detail != sb.CARD_REFUSED


def test_a_price_stripe_cannot_show_switches_as_it_always_did(stripe):
    del stripe["prices"][GROWING]
    out = _checkout()
    write = _writes(stripe, "/subscriptions/sub_1")[0]
    assert write["items"] == [{"id": "si_plan", "price": GROWING}]
    assert write["proration_behavior"] == "create_prorations" and out["charged_today"] is False


# ─── 7. a change of term takes the extra logins with it ───────────────

def test_monthly_to_yearly_is_left_to_stripe_which_charges_the_year(stripe):
    out = _checkout(plan="church_growing_annual")
    write = _writes(stripe, "/subscriptions/sub_1")[0]
    assert write["items"] == [{"id": "si_plan", "price": GROWING_YEAR}]
    assert write["proration_behavior"] == "create_prorations" and "payment_behavior" not in write
    assert out["charged_today"] is False


def test_extra_logins_move_to_the_yearly_login_price(stripe, monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL", LOGINS_YEAR)
    stripe["sub"] = _sub(items=[ITEM_LOGINS, ITEM_SMALL])
    _checkout(plan="church_growing_annual")
    assert _writes(stripe, "/subscriptions/sub_1")[0]["items"] == [
        {"id": "si_plan", "price": GROWING_YEAR}, {"id": "si_logins", "price": LOGINS_YEAR}]


def test_logins_with_no_yearly_price_are_refused_before_stripe_is_asked(stripe):
    stripe["sub"] = _sub(items=[ITEM_LOGINS, ITEM_SMALL])
    with pytest.raises(HTTPException) as e:
        _checkout(plan="church_growing_annual")
    assert e.value.status_code == 409 and "Write to us" in e.value.detail
    assert stripe["posted"] == []


def test_twelve_months_is_a_year():
    assert sb._term_of(_a_price("p", 1, "month", 12)) == ("year", 1) == sb._term_of(_a_price("p", 1, "year"))
    assert sb._term_of(_a_price("p", 1, "month", 3)) == ("month", 3)
    assert sb._term_of({"id": "p"}) == ("", 1) == sb._term_of(None)


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
