"""Stripe event order never decides a business's subscription state.

Creative Genius (2026-09-18): the last payment failed and Stripe cancelled
the subscription in the same second. `customer.subscription.deleted` set
the row to canceled, then `invoice.payment_failed` blindly set it back to
past_due, and the business kept its seat for two weeks after Stripe ended
it. Billing events now apply the subscription as Stripe holds it now.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import stripe_billing as sb


@pytest.fixture
def world(monkeypatch):
    state = {"stripe": {}, "patches": []}

    async def fake_get(path, params):
        sub_id = path.rsplit("/", 1)[-1]
        if sub_id not in state["stripe"]:
            raise RuntimeError("Stripe unreachable")
        return state["stripe"][sub_id]

    async def fake_patch(business_id, body, match=None):
        state["patches"].append({"body": dict(body), "match": match})

    monkeypatch.setattr(sb, "_stripe_get", fake_get)
    monkeypatch.setattr(sb, "_patch_business", fake_patch)
    import feature_gates
    monkeypatch.setattr(feature_gates, "price_to_plan", lambda: {"price_pro": "professional"})
    return state


def _sub(status):
    return {"id": "sub_1", "status": status, "items": {"data": [{"price": {"id": "price_pro"}}]}}


def last_status(state):
    return state["patches"][-1]["body"]["subscription_status"]


def test_payment_failed_after_cancel_keeps_it_canceled(world):
    world["stripe"]["sub_1"] = _sub("canceled")
    asyncio.run(sb._apply_subscription_state("customer.subscription.deleted", _sub("canceled"), "b1"))
    asyncio.run(sb._handle_invoice_payment_failed({"subscription": "sub_1"}, "b1"))
    assert last_status(world) == "canceled"


def test_payment_failed_on_a_live_subscription_is_past_due(world):
    world["stripe"]["sub_1"] = _sub("past_due")
    asyncio.run(sb._handle_invoice_payment_failed({"subscription": "sub_1"}, "b1"))
    assert last_status(world) == "past_due"


def test_newer_invoice_shape_finds_the_subscription(world):
    world["stripe"]["sub_1"] = _sub("canceled")
    inv = {"parent": {"subscription_details": {"subscription": "sub_1"}}}
    asyncio.run(sb._handle_invoice_payment_failed(inv, "b1"))
    assert last_status(world) == "canceled"


def test_stripe_unreachable_falls_back_but_never_undoes_a_cancellation(world):
    asyncio.run(sb._handle_invoice_payment_failed({"subscription": "sub_gone"}, "b1"))
    [p] = world["patches"]
    assert p["body"] == {"subscription_status": "past_due"}
    assert p["match"] == sb._NOT_CANCELED


def test_late_payment_does_not_reactivate_a_cancelled_subscription(world):
    world["stripe"]["sub_1"] = _sub("canceled")
    asyncio.run(sb._apply_invoice_outcome({"subscription": "sub_1"}, "b1", "active"))
    assert last_status(world) == "canceled"


def test_one_off_invoice_changes_nothing(world):
    asyncio.run(sb._apply_invoice_outcome({"id": "in_1"}, "b1", "active"))
    asyncio.run(sb._handle_invoice_payment_failed({"id": "in_2"}, "b1"))
    assert world["patches"] == []


def test_no_business_changes_nothing(world):
    world["stripe"]["sub_1"] = _sub("past_due")
    asyncio.run(sb._handle_invoice_payment_failed({"subscription": "sub_1"}, None))
    assert world["patches"] == []
