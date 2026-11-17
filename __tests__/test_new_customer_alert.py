"""Kevin hears when a new customer subscribes and its payment goes through.

Kevin, 2026-11-16, the day the first church paid: "build notification
through mission control that will let me know when someone new subscribes
and payment went through." He had to ask whether the money arrived.

One alert per new subscription (invoice.paid): its first money, straight
away or when its free days end, or, with nothing charged yet, that it
started. Renewals never alert, and a redelivered Stripe event never alerts
twice. The alert is an owner alert (source "customers") that opens
Subscriptions, and Today shows it for three days.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import dev_alerts
import platform_today as pt
import stripe_billing as sb

GROWING = "price_growing_founding"
LOGIN = "price_extra_login"


def _sub(trial_end=None):
    return {"id": "sub_1", "status": "active", "trial_end": trial_end,
            "items": {"data": [
                {"price": {"id": LOGIN, "recurring": {"interval": "month", "interval_count": 1}}},
                {"price": {"id": GROWING, "recurring": {"interval": "month", "interval_count": 1}}},
            ]}}


@pytest.fixture
def world(monkeypatch):
    state = {"invoices": [], "sub": _sub(), "raised": [], "stripe_down": False,
             "biz": {"id": "b1", "name": "Elevation of Grace"}}

    async def fake_get(path, params):
        if state["stripe_down"]:
            raise HTTPException(502, "Stripe unreachable")
        if path == "/invoices":
            return {"data": state["invoices"]}
        if path.startswith("/subscriptions/"):
            return state["sub"]
        raise AssertionError(path)

    async def fake_business(business_id):
        return state["biz"]

    async def fake_settings(c):
        return dev_alerts.Settings()

    async def fake_raise(c, **kw):
        state["raised"].append(kw)
        return "pushed"

    import feature_gates
    monkeypatch.setattr(sb, "_stripe_get", fake_get)
    monkeypatch.setattr(sb, "_load_business", fake_business)
    monkeypatch.setattr(dev_alerts, "settings", fake_settings)
    monkeypatch.setattr(dev_alerts, "raise_alert", fake_raise)
    monkeypatch.setattr(feature_gates, "price_to_plan", lambda: {GROWING: "church_growing"})
    return state


def _inv(cents, reason, inv_id="in_new"):
    return {"id": inv_id, "amount_paid": cents, "billing_reason": reason,
            "customer_name": "Stripe Name", "subscription": "sub_1"}


def tell(inv, business_id="b1"):
    return asyncio.run(sb.tell_owner_new_customer(inv, business_id))


def test_a_church_that_pays_straight_away_tells_kevin(world):
    assert tell(_inv(19900, "subscription_create")) == "pushed"
    [a] = world["raised"]
    assert a["source"] == "customers" and a["kind"] == "paid"
    assert a["title"] == "New church: Elevation of Grace paid $199"
    assert a["body"].startswith("Growing Church plan, monthly.")
    assert "first payment went through" in a["body"]
    assert a["nav"] == "studio:platform-subscriptions"
    assert a["key"] == "invoice:in_new"


def test_a_renewal_never_alerts(world):
    world["invoices"] = [{"id": "in_old", "amount_paid": 19900}, {"id": "in_new", "amount_paid": 19900}]
    assert tell(_inv(19900, "subscription_cycle")) is None
    assert world["raised"] == []


def test_the_first_payment_after_free_days_alerts(world, monkeypatch):
    world["biz"] = {"id": "b1", "name": "Bright Barbers"}
    import feature_gates
    monkeypatch.setattr(feature_gates, "price_to_plan", lambda: {GROWING: "professional"})
    world["invoices"] = [{"id": "in_trial", "amount_paid": 0}, {"id": "in_new", "amount_paid": 14900}]
    assert tell(_inv(14900, "subscription_cycle")) == "pushed"
    [a] = world["raised"]
    assert a["kind"] == "first"
    assert a["title"] == "Bright Barbers's first payment went through: $149"
    assert a["body"].startswith("Professional plan, monthly.")


def test_stripe_unreadable_says_nothing_rather_than_call_a_renewal_new(world):
    world["stripe_down"] = True
    assert tell(_inv(19900, "subscription_cycle")) is None
    assert world["raised"] == []


def test_a_new_subscription_with_nothing_charged_says_when_the_first_charge_comes(world):
    world["sub"] = _sub(trial_end=1795500000)  # 2026-11-24 06:00 UTC, 1 AM in New York
    world["biz"] = {"id": "b1", "name": "Grace Chapel"}
    assert tell(_inv(0, "subscription_create")) == "pushed"
    [a] = world["raised"]
    assert a["kind"] == "started"
    assert a["title"] == "New church: Grace Chapel subscribed"
    assert a["body"].endswith("Nothing charged yet. The first charge is due Tue Nov 24.")


def test_a_full_discount_says_nothing_was_charged(world):
    assert tell(_inv(0, "subscription_create")) == "pushed"
    assert "Nothing was charged (a full discount)." in world["raised"][0]["body"]


def test_upgrades_and_one_off_invoices_never_alert(world):
    assert tell(_inv(0, "subscription_update")) is None
    one_off = {"id": "in_x", "amount_paid": 5000, "billing_reason": "manual"}
    assert tell(one_off) is None
    assert world["raised"] == []


def test_without_the_business_row_the_stripe_name_is_used(world, monkeypatch):
    async def gone(business_id):
        raise HTTPException(404, "Business not found")
    monkeypatch.setattr(sb, "_load_business", gone)
    tell(_inv(19900, "subscription_create"), business_id=None)
    assert "Stripe Name" in world["raised"][0]["title"]


def test_the_newer_invoice_shape_still_finds_the_subscription(world):
    inv = _inv(19900, "subscription_create")
    del inv["subscription"]
    inv["parent"] = {"subscription_details": {"subscription": "sub_1"}}
    assert tell(inv) == "pushed"


def test_words_fit_the_alert_limits():
    title, body = sb.new_customer_words(
        "paid", name="The Church of the Living God, Pillar and Ground of the Truth, Without Controversy",
        church=True, plan_label="Established Church", term="every 3 months", cents=74700,
        first_charge=None)
    assert len(title) <= 90 and len(body) <= 220
    assert "$747" in title
    assert sb._dollars(19950) == "$199.50" and sb._dollars(1500000) == "$15,000"


def test_terms_in_words():
    assert sb._term_words(("month", 1)) == "monthly"
    assert sb._term_words(("month", 3)) == "every 3 months"
    assert sb._term_words(("year", 1)) == "yearly"
    assert sb._term_words(("", 1)) == ""


# ─── The webhook: once per event, and never in Stripe's way ───────────

class _Req:
    def __init__(self, event):
        self._b = json.dumps(event).encode()

    async def body(self):
        return self._b


@pytest.fixture
def hook(monkeypatch):
    state = {"scheduled": [], "recorded": False}
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(sb, "_verify_stripe_signature", lambda *a: None)

    async def resolve(event):
        return "b1"

    async def nothing(*a, **k):
        return None

    async def recorded(event_id):
        return state["recorded"]

    monkeypatch.setattr(sb, "_resolve_business_id_async", resolve)
    monkeypatch.setattr(sb, "_apply_invoice_outcome", nothing)
    monkeypatch.setattr(sb, "_record_webhook", nothing)
    monkeypatch.setattr(sb, "_event_recorded", recorded)
    monkeypatch.setattr(sb, "_schedule_owner_alert", lambda inv, bid: state["scheduled"].append(inv["id"]))
    return state


def _paid_event():
    return {"id": "evt_1", "type": "invoice.paid", "livemode": True,
            "data": {"object": _inv(19900, "subscription_create")}}


def test_the_webhook_schedules_the_alert(hook):
    out = asyncio.run(sb.stripe_webhook(_Req(_paid_event()), "t=1,v1=x"))
    assert out == {"received": True}
    assert hook["scheduled"] == ["in_new"]


def test_a_redelivered_event_never_alerts_twice(hook):
    hook["recorded"] = True
    asyncio.run(sb.stripe_webhook(_Req(_paid_event()), "t=1,v1=x"))
    assert hook["scheduled"] == []


def test_a_failing_alert_never_reaches_the_webhook(monkeypatch):
    async def boom(inv, business_id):
        raise RuntimeError("push service down")
    monkeypatch.setattr(sb, "tell_owner_new_customer", boom)
    asyncio.run(sb._tell_owner_safely(_inv(19900, "subscription_create"), "b1"))


# ─── The alert inbox and Today ────────────────────────────────────────

def test_customers_is_a_server_source_that_pushes_by_default():
    assert dev_alerts.SOURCES["customers"] == "push"
    assert "customers" in dev_alerts.SERVER_SOURCES
    # A settings row saved before this source existed still validates.
    old = dev_alerts.Settings().model_dump()
    old["sources"].pop("customers")
    assert dev_alerts.Settings.model_validate(old).sources["customers"] == "push"


def test_the_alert_may_open_subscriptions_but_nowhere_else_outside_the_dev_desk():
    assert dev_alerts._nav("studio:platform-subscriptions") == "studio:platform-subscriptions"
    with pytest.raises(HTTPException):
        dev_alerts._nav("studio:platform-money")
    with pytest.raises(HTTPException):
        dev_alerts._nav("https://example.com")


def test_today_shows_the_new_customer_with_a_welcome_one_tap_away():
    item = pt.customer_item({"id": "a1", "created_at": "2026-11-16T21:53:00+00:00",
                             "title": "New church: Elevation of Grace paid $199",
                             "body": "Growing Church plan, monthly."})
    assert item["id"] == "customer:a1" and item["room"] == "customers"
    assert item["tone"] in pt.TONE_ORDER and item["lanes"][0] == "people"
    assert item["action"]["nav"] == "platform-subscriptions"
    assert "Elevation of Grace" in item["secondary"]["chief"]


def test_today_reads_new_customers_from_the_alert_inbox(monkeypatch):
    import platform_console as pc
    asked = {}

    async def subs(**k):
        return {"payment_issues": [], "trial_ending_soon": [], "by_status": {}, "mrr_cents": 0}

    async def nothing(*a, **k):
        return []

    async def get(c, table, params):
        if table == "dev_alerts":
            asked.update(params)
            return [{"id": "a1", "created_at": "2026-11-16T21:53:00+00:00", "kind": "paid",
                     "title": "New church: Elevation of Grace paid $199", "body": "Growing Church plan, monthly."}]
        return []

    async def zero(*a, **k):
        return 0

    async def none(*a, **k):
        return None

    monkeypatch.setattr(pc, "subscriptions_summary", subs)
    monkeypatch.setattr(pc, "_recent_merged_prs", nothing)
    monkeypatch.setattr(pt, "_practitioners", lambda c: none())
    monkeypatch.setattr(pt, "_count", zero)
    monkeypatch.setattr(pt, "_get", get)
    monkeypatch.setattr(pt, "_marketing", nothing)
    monkeypatch.setattr(pt, "_traffic", none)
    monkeypatch.setattr(pt, "_coupons", none)
    monkeypatch.setattr(pt, "_anchor_health", lambda: {"providers": []})
    monkeypatch.setattr(pt, "_spend", lambda: {"today_cents": 0, "cap_cents": 5000})

    class Owner:
        id = "00000000-0000-0000-0000-000000000001"

    out = asyncio.run(pt.build_today(Owner(), with_ops=False))
    assert asked["source"] == "eq.customers"
    assert asked["created_at"].startswith("gte.")
    [item] = [i for i in out["needs_you"] if i["kind"] == "new customer"]
    assert item["title"] == "New church: Elevation of Grace paid $199"
    assert "customers" not in out["sources_failed"]
