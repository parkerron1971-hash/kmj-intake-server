"""One more office login, and the move (Kevin, 2026-11-03; church_billing.py).

  1. Extra logins live on the church's subscription and in its settings, and
     add to the plan's logins wherever a seat is checked.
  2. The webhook finds the plan among a subscription's items (the extra
     logins are a second item) and keeps the extra-login count.
  3. Setting the count adds, changes or removes the subscription item.
  4. The move: free for the first five churches, then three months of the
     plan at Checkout; asking twice returns the first ask; a paid move is
     recorded once per session and reaches Mission Control as a ticket.
  5. A founding place waits for the first payment: a church on its trial is
     told so and takes the place by paying today, and a card that fails takes
     nothing.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import billing_limits  # noqa: E402
import church_billing as cb  # noqa: E402
import feature_gates as fg  # noqa: E402
import stripe_billing as sb  # noqa: E402
from auth_supabase import AuthedUser  # noqa: E402

USER = AuthedUser(id="u-1", email="pastor@church.test", role="authenticated")
BIZ = "b0000000-0000-4000-8000-000000000001"


# ─── 1. extra logins add to the plan's ────────────────────────────────

@pytest.mark.parametrize("settings,n", [({"extra_logins": 2}, 2), ({"extra_logins": "3"}, 3), ({}, 0),
                                        ({"extra_logins": "lots"}, 0), ({"extra_logins": -4}, 0), (None, 0)])
def test_extra_logins_reads_settings(settings, n):
    assert cb.extra_logins({"settings": settings}) == n


def test_a_seat_check_counts_the_logins_a_church_bought(monkeypatch):
    monkeypatch.setattr(billing_limits, "seat_count", lambda b: 8)
    monkeypatch.setattr(fg, "limit_for", lambda row, key: 8)
    row = {"id": BIZ, "comp_tier": "church_growing", "settings": {"extra_logins": 1}}
    out = billing_limits.can_add_seat(BIZ, row)
    assert out["limit"] == 9 and out["allowed"] is True


def test_a_row_without_settings_is_read_fresh(monkeypatch):
    import sb_clients
    monkeypatch.setattr(billing_limits, "seat_count", lambda b: 8)
    monkeypatch.setattr(fg, "limit_for", lambda row, key: 8)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{"settings": {"extra_logins": 2}}])
    assert billing_limits.can_add_seat(BIZ, {"id": BIZ})["limit"] == 10


def test_unlimited_stays_unlimited(monkeypatch):
    monkeypatch.setattr(billing_limits, "seat_count", lambda b: 50)
    monkeypatch.setattr(fg, "limit_for", lambda row, key: None)
    assert billing_limits.can_add_seat(BIZ, {"settings": {"extra_logins": 3}})["limit"] is None


# ─── 2. the webhook ───────────────────────────────────────────────────

def _webhook(monkeypatch, items, status="active"):
    patches, synced = [], []
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_grow")
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN", "price_login")

    async def patch(bid, body, match=None):
        patches.append(body)

    async def sync(bid, its, st):
        synced.append((bid, cb.extra_login_quantity(its), st))
    monkeypatch.setattr(sb, "_patch_business", patch)
    monkeypatch.setattr(cb, "sync_extra_logins", sync)
    asyncio.run(sb._apply_subscription_state("customer.subscription.updated",
                                             {"id": "sub_1", "status": status, "items": {"data": items}}, BIZ))
    return patches, synced


def test_the_plan_is_found_even_when_the_logins_come_first(monkeypatch):
    items = [{"price": {"id": "price_login"}, "quantity": 2}, {"price": {"id": "price_grow"}, "quantity": 1}]
    patches, synced = _webhook(monkeypatch, items)
    assert patches[0]["subscription_plan"] == "price_grow" and patches[0]["tier"] == "church_growing"
    assert synced == [(BIZ, 2, "active")]


def test_a_plain_subscription_reads_as_it_always_did(monkeypatch):
    patches, synced = _webhook(monkeypatch, [{"price": {"id": "price_other"}, "quantity": 1}])
    assert patches[0]["subscription_plan"] == "price_other" and synced == []


def test_sync_writes_only_a_change_and_zero_once_cancelled(monkeypatch):
    writes = []

    async def load(bid):
        return {"id": bid, "settings": {"extra_logins": 2, "other": "kept"}}

    async def patch(bid, body, match=None):
        writes.append(body)
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN", "price_login")
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_patch_business", patch)
    two = [{"price": {"id": "price_login"}, "quantity": 2}]
    asyncio.run(cb.sync_extra_logins(BIZ, two, "active"))
    assert writes == []
    asyncio.run(cb.sync_extra_logins(BIZ, two, "canceled"))
    assert writes == [{"settings": {"other": "kept"}}]


def test_the_webhook_routes_a_paid_move():
    src = inspect.getsource(sb)
    assert src.count('meta.get("kind") == "church_move"') == 2      # completed + async succeeded
    assert "church_billing.record_paid_move" in src


# ─── 3. setting the count ─────────────────────────────────────────────

@pytest.fixture
def stripe(monkeypatch):
    calls = []
    state = {"items": [], "biz": {"id": BIZ, "owner_id": "u-1", "type": "church", "comp_tier": None,
                                  "subscription_status": "active", "subscription_plan": "price_grow",
                                  "stripe_subscription_id": "sub_1", "stripe_customer_id": "cus_1",
                                  "name": "Grace Fellowship", "settings": {}}}
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_grow")
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN", "price_login")

    async def load(bid):
        return state["biz"]

    async def patch(bid, body, match=None):
        calls.append(("patch", body))
        state["biz"] = {**state["biz"], **body}

    async def get(path, params):
        calls.append(("get", path))
        return {"items": {"data": state["items"]}}

    async def post(path, data):
        calls.append(("post", path, data))
        return {"id": "cs_1", "url": "https://checkout.stripe.test/x"}

    async def delete(path):
        calls.append(("delete", path))
        return {}
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_patch_business", patch)
    monkeypatch.setattr(sb, "_stripe_get", get)
    monkeypatch.setattr(sb, "_stripe_post", post)
    monkeypatch.setattr(cb, "_stripe_delete", delete)
    return calls, state


def _set(n):
    return asyncio.run(cb.set_extra_logins(cb.ExtraLoginsBody(business_id=BIZ, count=n), user=USER))


def test_the_first_extra_login_adds_an_item(stripe):
    calls, state = stripe
    out = _set(1)
    assert ("post", "/subscription_items", {"subscription": "sub_1", "price": "price_login", "quantity": 1,
                                            "proration_behavior": "create_prorations"}) in calls
    assert out["max_seats"] == 9 and state["biz"]["settings"] == {"extra_logins": 1}


def test_more_changes_the_quantity_and_zero_removes_it(stripe):
    calls, state = stripe
    state["items"] = [{"id": "si_9", "price": {"id": "price_login"}, "quantity": 1}]
    _set(3)
    assert ("post", "/subscription_items/si_9", {"quantity": 3, "proration_behavior": "create_prorations"}) in calls
    _set(0)
    assert ("delete", "/subscription_items/si_9") in calls and state["biz"]["settings"] == {}


@pytest.mark.parametrize("change,detail", [
    ({"subscription_plan": "price_pro_x"}, "come with the church plans"),
    ({"stripe_subscription_id": None}, "paid church plan"),
])
def test_refused_off_a_church_plan_or_without_a_subscription(stripe, change, detail):
    _calls, state = stripe
    state["biz"] = {**state["biz"], **change}
    with pytest.raises(HTTPException) as e:
        _set(1)
    assert e.value.status_code == 409 and detail in e.value.detail


def test_refused_until_the_price_exists(stripe, monkeypatch):
    monkeypatch.delenv("STRIPE_PRICE_ID_EXTRA_LOGIN")
    with pytest.raises(HTTPException) as e:
        _set(1)
    assert e.value.status_code == 409


def test_only_the_owner_sets_it(stripe):
    with pytest.raises(HTTPException):
        asyncio.run(cb.set_extra_logins(cb.ExtraLoginsBody(business_id=BIZ, count=1),
                                        user=AuthedUser(id="someone-else", email="x@y.test", role="authenticated")))


# ─── 4. the move ──────────────────────────────────────────────────────

def _move(**kw):
    return asyncio.run(cb.request_move(cb.MoveBody(business_id=BIZ, **kw), user=USER))


def test_a_founding_church_is_moved_free(stripe, monkeypatch):
    calls, state = stripe
    tickets = []
    monkeypatch.setattr(cb, "_founding_taken", lambda: 4)
    monkeypatch.setattr(cb, "_ticket", lambda biz, rec: tickets.append(rec))
    out = _move(moving_from="Subsplash")
    assert out["founding"] is True
    rec = state["biz"]["settings"]["church_move"]
    assert rec["state"] == "requested" and rec["founding"] is True and rec["moving_from"] == "Subsplash"
    assert tickets == [rec] and not [c for c in calls if c[0] == "post"]


def test_after_five_the_move_is_three_months_of_the_plan(stripe, monkeypatch):
    calls, state = stripe
    monkeypatch.setattr(cb, "_founding_taken", lambda: 5)
    out = _move(moving_from="Planning Center")
    [(_, path, data)] = [c for c in calls if c[0] == "post"]
    assert path == "/checkout/sessions" and data["mode"] == "payment"
    # Three months of the plan at the price this church pays: the regular
    # price for a church that holds no founding place.
    assert data["line_items"][0]["price_data"]["unit_amount"] == 3 * 24900 == out["price_cents"]
    assert data["metadata"]["kind"] == "church_move" and data["metadata"]["plan"] == "church_growing"
    assert "church_move" not in state["biz"]["settings"]         # recorded only once it's paid


def test_asking_twice_returns_the_first_ask(stripe, monkeypatch):
    _calls, state = stripe
    first = {"state": "requested", "founding": True}
    state["biz"]["settings"] = {"church_move": first}
    monkeypatch.setattr(cb, "_founding_taken", lambda: 0)
    assert _move() == {"ok": True, "move": first, "already": True}


def test_an_unreadable_founding_count_is_a_503_never_free(stripe, monkeypatch):
    monkeypatch.setattr(cb, "_founding_taken", lambda: None)
    with pytest.raises(HTTPException) as e:
        _move()
    assert e.value.status_code == 503


def test_a_paid_move_is_recorded_once_per_session(stripe, monkeypatch):
    _calls, state = stripe
    tickets = []
    monkeypatch.setattr(cb, "_ticket", lambda biz, rec: tickets.append(rec))
    session = {"id": "cs_7", "payment_status": "paid", "amount_total": 44700,
               "metadata": {"plan": "church_growing", "moving_from": "Subsplash"}}
    assert asyncio.run(cb.record_paid_move(BIZ, session)) is None
    assert asyncio.run(cb.record_paid_move(BIZ, session)) is None
    assert len(tickets) == 1 and state["biz"]["settings"]["church_move"]["amount_cents"] == 44700
    unpaid = {**session, "id": "cs_8", "payment_status": "unpaid"}
    assert asyncio.run(cb.record_paid_move(BIZ, unpaid)) is None and len(tickets) == 1


def test_the_ticket_says_who_from_where_and_how(monkeypatch):
    import sb_clients
    posted = []
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda path, body, *a, **k: posted.append((path, body)))
    cb._ticket({"id": BIZ, "name": "Grace Fellowship", "comp_tier": "church_growing"},
               {"founding": False, "amount_cents": 59700, "moving_from": "Subsplash", "plan": "church_growing"})
    [(path, body)] = posted
    assert path == "/support_tickets" and body["category"] == "billing"
    assert body["subject"] == "MOVE: Grace Fellowship from Subsplash (paid $597)"
    assert "Growing Church" in body["message"] and body["context"]["kind"] == "church_move"


def test_the_move_and_logins_are_mounted():
    import kmj_intake_automation as app_mod
    paths = {getattr(r, "path", "") for r in app_mod.app.routes}
    assert {"/billing/church/move", "/billing/church/extra-logins"} <= paths


# ─── 5. a founding place waits for the first payment ──────────────────

@pytest.fixture
def trial(stripe, monkeypatch):
    calls, state = stripe
    state["biz"] = {**state["biz"], "subscription_status": "trialing"}
    state["tickets"] = []
    state["stripe_status"] = "trialing"
    state["after_charge"] = "active"

    async def get(path, params):
        calls.append(("get", path))
        return {"id": "sub_1", "status": state["stripe_status"], "items": {"data": []}}

    async def post(path, data):
        calls.append(("post", path, data))
        return {"id": "sub_1", "status": state["after_charge"], "items": {"data": []}}

    async def applied(event, sub_obj, bid):
        state["biz"] = {**state["biz"], "subscription_status": sub_obj["status"]}

    monkeypatch.setattr(sb, "_stripe_get", get)
    monkeypatch.setattr(sb, "_stripe_post", post)
    monkeypatch.setattr(sb, "_apply_subscription_state", applied)
    monkeypatch.setattr(cb, "_founding_taken", lambda: 2)
    monkeypatch.setattr(cb, "_ticket", lambda biz, rec: state["tickets"].append(rec))
    return calls, state


def _ended_a_trial(calls):
    return ("post", "/subscriptions/sub_1", {"trial_end": "now"}) in calls


def test_a_trial_takes_no_place_and_is_told_what_it_takes(trial):
    calls, state = trial
    out = _move(moving_from="Subsplash")
    assert out["pay_first"] is True and out["first_payment_cents"] == fg.pricing_config.church_price_cents()["church_growing"]
    assert "church_move" not in state["biz"]["settings"]
    assert state["tickets"] == [] and not _ended_a_trial(calls)


def test_paying_today_ends_the_trial_and_takes_the_place(trial):
    calls, state = trial
    out = _move(moving_from="Subsplash", pay_today=True)
    assert out["founding"] is True and _ended_a_trial(calls)
    assert state["biz"]["settings"]["church_move"]["founding"] is True
    assert len(state["tickets"]) == 1


@pytest.mark.parametrize("after", ["past_due", "incomplete"])
def test_a_card_that_fails_takes_no_place(trial, after):
    _calls, state = trial
    state["after_charge"] = after
    with pytest.raises(HTTPException) as e:
        _move(pay_today=True)
    assert e.value.status_code == 402
    assert "church_move" not in state["biz"]["settings"] and state["tickets"] == []


def test_a_trial_that_already_ended_at_stripe_is_not_charged_twice(trial):
    calls, state = trial
    state["stripe_status"] = "active"
    out = _move(pay_today=True)
    assert out["founding"] is True and not _ended_a_trial(calls)


def test_no_place_left_means_no_charge_for_one(trial, monkeypatch):
    calls, state = trial
    monkeypatch.setattr(cb, "_founding_taken", lambda: 5)
    out = _move(pay_today=True)
    assert "pay_first" not in out and not _ended_a_trial(calls)
    assert "church_move" not in state["biz"]["settings"]


def test_a_paying_church_is_asked_nothing_more(trial):
    calls, state = trial
    state["biz"] = {**state["biz"], "subscription_status": "active"}
    out = _move()
    assert out["founding"] is True and not _ended_a_trial(calls)


def test_a_comped_church_owes_no_first_payment(trial):
    calls, state = trial
    state["biz"] = {**state["biz"], "comp_tier": "church_growing"}
    out = _move()
    assert out["founding"] is True and not _ended_a_trial(calls)


def test_the_move_card_learns_what_is_due(trial):
    _calls, state = trial
    out = asyncio.run(cb.move_status(BIZ, user=USER))
    assert out["first_payment_due"] is True
    assert out["first_payment_cents"] == fg.pricing_config.church_price_cents()["church_growing"]
    state["biz"] = {**state["biz"], "subscription_status": "active"}
    assert asyncio.run(cb.move_status(BIZ, user=USER))["first_payment_due"] is False


# ─── 5. the owner hears about a move ─────────────────────────────────

@pytest.fixture
def mail(monkeypatch):
    import email_sender
    sent = []

    async def send(**kw):
        sent.append(kw)
        return {"id": "em_1"}
    monkeypatch.setattr(email_sender, "send_via_resend", send)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@example.test")
    monkeypatch.setattr(cb, "_ticket", lambda biz, rec: None)
    return sent


def test_a_founding_move_emails_the_owner_once(stripe, mail, monkeypatch):
    monkeypatch.setattr(cb, "_founding_taken", lambda: 0)
    assert _move(moving_from="Planning Center")["founding"] is True
    [m] = mail
    assert m["to_email"] == "owner@example.test" and "Grace Fellowship" in m["subject"]
    assert "Planning Center" in m["body"] and "Founding church" in m["body"] and "Mission Control" in m["body"]
    assert m["idempotency_key"] == f"church-move-{BIZ}-founding"
    _move()                                   # asking twice: the first ask stands, no second email
    assert len(mail) == 1


def test_a_paid_move_emails_the_owner_with_what_was_paid(stripe, mail):
    session = {"id": "cs_7", "payment_status": "paid", "amount_total": 59700,
               "metadata": {"plan": "church_growing", "moving_from": "Subsplash"}}
    assert asyncio.run(cb.record_paid_move(BIZ, session)) is None
    assert asyncio.run(cb.record_paid_move(BIZ, session)) is None      # Stripe redelivers
    [m] = mail
    assert "Paid $597" in m["body"] and m["idempotency_key"] == f"church-move-{BIZ}-cs_7"


def test_a_church_name_never_becomes_markup(stripe, mail, monkeypatch):
    _calls, state = stripe
    state["biz"]["name"] = "Grace <b>Fellowship</b>"
    monkeypatch.setattr(cb, "_founding_taken", lambda: 0)
    _move()
    assert "<b>" not in mail[0]["body"] and "&lt;b&gt;" in mail[0]["body"]


def test_a_failed_email_never_fails_the_move(stripe, monkeypatch):
    import email_sender
    _calls, state = stripe

    async def boom(**kw):
        raise RuntimeError("resend is down")
    monkeypatch.setattr(email_sender, "send_via_resend", boom)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@example.test")
    monkeypatch.setattr(cb, "_ticket", lambda biz, rec: None)
    monkeypatch.setattr(cb, "_founding_taken", lambda: 0)
    assert _move()["founding"] is True
    assert state["biz"]["settings"]["church_move"]["state"] == "requested"


def test_no_owner_address_means_no_email(stripe, mail, monkeypatch):
    monkeypatch.delenv("PLATFORM_OWNER_EMAIL")
    monkeypatch.setattr(cb, "_founding_taken", lambda: 0)
    _move()
    assert mail == []
