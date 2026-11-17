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
  6. A login added is paid for that day and only added if the card takes it;
     a church paying by the year buys its logins by the year, because Stripe
     holds one subscription to one billing term (2026-11-16).
  7. Extra storage, 100 GB for $5 a month (2026-11-17), the same way: an item
     on the subscription (quantity = blocks), per term, paid today, kept by
     the webhook; an unreadable count is None, never 0; fewer blocks that put
     the church over are allowed and the answer says the 14-day rule.
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

def _webhook(monkeypatch, items, status="active", stored=None):
    patches, synced = [], []
    stored = [] if stored is None else stored
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_grow")
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN", "price_login")
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_STORAGE", "price_store")

    async def patch(bid, body, match=None):
        patches.append(body)

    async def sync(bid, its, st):
        synced.append((bid, cb.extra_login_quantity(its), st))

    async def sync_storage(bid, its, st):
        stored.append((bid, cb.extra_storage_quantity(its), st))
    monkeypatch.setattr(sb, "_patch_business", patch)
    monkeypatch.setattr(cb, "sync_extra_logins", sync)
    monkeypatch.setattr(cb, "sync_extra_storage", sync_storage)
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
    from settings_merge_fake import install
    row = {"id": BIZ, "settings": {"extra_logins": 2, "other": "kept"}}

    async def load(bid):
        return {"id": bid, "settings": dict(row["settings"])}

    async def patch(bid, body, match=None):
        raise AssertionError("extra logins are never a whole-row patch")
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN", "price_login")
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_patch_business", patch)
    writes = install(monkeypatch, lambda bid: row)
    two = [{"price": {"id": "price_login"}, "quantity": 2}]
    asyncio.run(cb.sync_extra_logins(BIZ, two, "active"))
    assert writes == []
    asyncio.run(cb.sync_extra_logins(BIZ, two, "canceled"))
    assert writes == [{"id": BIZ, "set": {}, "drop": ["extra_logins"], "under": []}]   # the key, and only it
    assert row["settings"] == {"other": "kept"}


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
        return {"status": state.get("status"), "items": {"data": state["items"]}}

    async def post(path, data):
        calls.append(("post", path, data))
        if state.get("refuse"):
            raise HTTPException(state["refuse"], "Stripe error: card_declined")
        return {"id": "cs_1", "url": "https://checkout.stripe.test/x"}

    async def delete(path):
        calls.append(("delete", path))
        return {}
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_patch_business", patch)
    monkeypatch.setattr(sb, "_stripe_get", get)
    monkeypatch.setattr(sb, "_stripe_post", post)
    monkeypatch.setattr(cb, "_stripe_delete", delete)
    # Settings keys go through business_settings.merge (one key, never the
    # whole object): logged here as ("settings", call), applied to the row.
    from settings_merge_fake import install
    install(monkeypatch, lambda bid: state["biz"], into=calls)
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
    assert {"/billing/church/move", "/billing/church/extra-logins", "/billing/church/extra-storage"} <= paths


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


# ─── 6. paid today, and by the year ───────────────────────────────────

PAID_TODAY = {"proration_behavior": "always_invoice", "payment_behavior": "error_if_incomplete"}
YEAR_PLAN = {"id": "si_plan", "quantity": 1,
             "price": {"id": "price_grow_year", "unit_amount": 199000, "recurring": {"interval": "year"}}}


@pytest.fixture
def yearly(stripe, monkeypatch):
    """A church on its plan by the year, with the yearly login price set."""
    calls, state = stripe
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_ANNUAL", "price_grow_year")
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL", "price_login_year")
    state["status"] = "active"
    state["items"] = [YEAR_PLAN]
    state["biz"]["subscription_plan"] = "price_grow_year"
    return calls, state


def test_a_login_added_to_a_running_plan_is_paid_for_today(stripe):
    calls, state = stripe
    state["status"] = "active"
    out = _set(1)
    assert ("post", "/subscription_items", {"subscription": "sub_1", "price": "price_login", "quantity": 1,
                                            **PAID_TODAY}) in calls
    assert out["charged_today"] is True and out["cents_each"] == 1500 and out["every"] == "month"


def test_more_logins_are_paid_today_and_fewer_leave_a_credit(stripe):
    calls, state = stripe
    state["status"] = "active"
    state["items"] = [{"id": "si_9", "price": {"id": "price_login"}, "quantity": 2}]
    assert _set(3)["charged_today"] is True
    assert ("post", "/subscription_items/si_9", {"quantity": 3, **PAID_TODAY}) in calls
    assert _set(1)["charged_today"] is False
    assert ("post", "/subscription_items/si_9", {"quantity": 1, "proration_behavior": "create_prorations"}) in calls


def test_a_trial_adds_a_login_with_nothing_charged(stripe):
    calls, state = stripe
    state["status"] = "trialing"
    assert _set(1)["charged_today"] is False
    assert ("post", "/subscription_items", {"subscription": "sub_1", "price": "price_login", "quantity": 1,
                                            "proration_behavior": "create_prorations"}) in calls


def test_a_refused_card_adds_no_login(stripe):
    calls, state = stripe
    state["status"], state["refuse"] = "active", 402
    with pytest.raises(HTTPException) as e:
        _set(1)
    assert e.value.status_code == 402 and e.value.detail == sb.CARD_REFUSED
    assert state["biz"]["settings"] == {} and not [c for c in calls if c[0] in ("patch", "settings")]


def test_a_yearly_church_buys_its_logins_by_the_year(yearly):
    calls, state = yearly
    out = _set(2)
    assert ("post", "/subscription_items", {"subscription": "sub_1", "price": "price_login_year", "quantity": 2,
                                            **PAID_TODAY}) in calls
    assert out["cents_each"] == 15000 and out["every"] == "year" and out["max_seats"] == 10
    assert state["biz"]["settings"] == {"extra_logins": 2}


def test_a_yearly_church_is_told_to_write_in_until_the_yearly_price_exists(yearly, monkeypatch):
    calls, state = yearly
    monkeypatch.delenv("STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL")
    with pytest.raises(HTTPException) as e:
        _set(1)
    assert e.value.status_code == 409 and "Write to us" in e.value.detail
    assert not [c for c in calls if c[0] in ("post", "delete", "patch", "settings")]


def test_yearly_logins_are_counted_and_can_be_taken_off(yearly):
    calls, state = yearly
    login = {"id": "si_9", "price": {"id": "price_login_year"}, "quantity": 2}
    state["items"] = [YEAR_PLAN, login]
    assert cb.extra_login_quantity(state["items"]) == 2
    _set(0)
    assert ("delete", "/subscription_items/si_9") in calls


def test_the_plans_term_is_read_from_its_own_item(yearly):
    _calls, state = yearly
    monthly_login = {"id": "si_9", "price": {"id": "price_login", "recurring": {"interval": "month"}}, "quantity": 1}
    assert cb.plan_term([monthly_login, YEAR_PLAN]) == cb.YEARLY
    assert cb.plan_term([monthly_login]) == cb.MONTHLY == cb.plan_term([])


def test_the_yearly_login_is_ten_months_like_the_plans():
    import marketing_pages as mp
    cat = {env: (cents, interval) for env, _lk, _n, cents, interval in sb.BOOTSTRAP_CATALOG}
    assert cat["STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL"] == (cat["STRIPE_PRICE_ID_EXTRA_LOGIN"][0] * mp.ANNUAL_MONTHS, "year")
    assert cb.extra_login_cents(cb.YEARLY) == cb.extra_login_cents() * mp.ANNUAL_MONTHS


def test_logins_follow_a_change_of_term_or_refuse_it(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN", "price_login")
    monkeypatch.delenv("STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL", raising=False)
    held = [{"id": "si_9", "price": {"id": "price_login"}, "quantity": 2}]
    assert cb.logins_for_term([], cb.YEARLY) == []
    assert cb.logins_for_term(held, cb.MONTHLY) == []                 # already there
    with pytest.raises(HTTPException) as e:
        cb.logins_for_term(held, cb.YEARLY)
    assert e.value.status_code == 409
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN_ANNUAL", "price_login_year")
    assert cb.logins_for_term(held, cb.YEARLY) == [{"id": "si_9", "price": "price_login_year"}]


def test_the_app_is_told_the_yearly_login_price(monkeypatch):
    monkeypatch.setenv("PLAN_CHURCH_OFFERED", "1")

    async def no_display(pid):
        return None
    monkeypatch.setattr(sb, "_price_display", no_display)
    offer = asyncio.run(sb.billing_plans(for_type="church"))["church_offer"]
    assert offer["extra_login_cents"] == 1500 and offer["extra_login_year_cents"] == 15000


def test_a_church_paying_every_three_months_buys_its_logins_that_way(stripe, monkeypatch):
    calls, state = stripe
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_QUARTERLY", "price_grow_q")
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_LOGIN_QUARTERLY", "price_login_q")
    state["status"] = "active"
    state["items"] = [{"id": "si_plan", "quantity": 1,
                       "price": {"id": "price_grow_q", "recurring": {"interval": "month", "interval_count": 3}}}]
    state["biz"]["subscription_plan"] = "price_grow_q"
    assert cb.plan_term(state["items"]) == cb.QUARTERLY
    out = _set(1)
    assert ("post", "/subscription_items", {"subscription": "sub_1", "price": "price_login_q", "quantity": 1,
                                            **PAID_TODAY}) in calls
    assert out["cents_each"] == 4500 and out["every"] == "quarter"
    assert cb.extra_login_cents(cb.QUARTERLY) == cb.extra_login_cents() * 3


# ─── 7. extra storage: 100 GB for $5 a month ──────────────────────────

GIB = 1024 ** 3


@pytest.mark.parametrize("settings,n", [({"extra_storage": 2}, 2), ({"extra_storage": "3"}, 3), ({}, 0),
                                        (None, 0), ({"extra_storage": 0}, 0), ({"extra_storage": 4.0}, 4)])
def test_extra_storage_reads_settings(settings, n):
    assert cb.extra_storage_blocks({"settings": settings}) == n


@pytest.mark.parametrize("biz", [{"settings": {"extra_storage": "lots"}}, {"settings": {"extra_storage": -4}},
                                 {"settings": {"extra_storage": True}}, {"settings": {"extra_storage": 1.5}},
                                 {"settings": {"extra_storage": [1]}}, {"settings": "broken"},
                                 {"id": BIZ}, None])
def test_an_unreadable_storage_count_is_none_never_zero(biz):
    # Unlike a login (read as 0), 0 here would make the church look fuller
    # than it is, and the storage rules hold and remove recordings on that.
    assert cb.extra_storage_blocks(biz) is None


def test_the_webhook_keeps_the_storage_count_whichever_item_comes_first(monkeypatch):
    stored = []
    items = [{"price": {"id": "price_store"}, "quantity": 3}, {"price": {"id": "price_login"}, "quantity": 1},
             {"price": {"id": "price_grow"}, "quantity": 1}]
    patches, synced = _webhook(monkeypatch, items, stored=stored)
    assert patches[0]["subscription_plan"] == "price_grow" and patches[0]["tier"] == "church_growing"
    assert synced == [(BIZ, 1, "active")] and stored == [(BIZ, 3, "active")]


def test_storage_off_a_church_plan_is_still_synced_when_the_subscription_carries_it(monkeypatch):
    stored = []
    _webhook(monkeypatch, [{"price": {"id": "price_other"}, "quantity": 1},
                           {"price": {"id": "price_store"}, "quantity": 1}], stored=stored)
    assert stored == [(BIZ, 1, "active")]
    stored.clear()
    _webhook(monkeypatch, [{"price": {"id": "price_other"}, "quantity": 1}], stored=stored)
    assert stored == []


def test_storage_sync_writes_only_a_change_and_zero_once_cancelled(monkeypatch):
    from settings_merge_fake import install
    row = {"id": BIZ, "settings": {"extra_storage": 2, "other": "kept"}}

    async def load(bid):
        return {"id": bid, "settings": dict(row["settings"])}

    async def patch(bid, body, match=None):
        raise AssertionError("extra storage is never a whole-row patch")
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_STORAGE", "price_store")
    monkeypatch.setattr(sb, "_load_business", load)
    monkeypatch.setattr(sb, "_patch_business", patch)
    writes = install(monkeypatch, lambda bid: row)
    two = [{"price": {"id": "price_store"}, "quantity": 2}]
    asyncio.run(cb.sync_extra_storage(BIZ, two, "active"))
    assert writes == []
    asyncio.run(cb.sync_extra_storage(BIZ, two, "canceled"))
    assert writes == [{"id": BIZ, "set": {}, "drop": ["extra_storage"], "under": []}]   # the key, and only it
    assert row["settings"] == {"other": "kept"}
    # A stored value that isn't a count is written over with what Stripe holds.
    row["settings"] = {"extra_storage": "lots"}
    asyncio.run(cb.sync_extra_storage(BIZ, two, "active"))
    assert row["settings"] == {"extra_storage": 2}


@pytest.fixture
def storage(stripe, monkeypatch):
    """A church on Growing, monthly, with storage sold and switched on. What
    the meter reads after a change is the test's to say (state["meter"])."""
    import church_storage as cs
    calls, state = stripe
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_STORAGE", "price_store")
    monkeypatch.delenv("STRIPE_PRICE_ID_EXTRA_STORAGE_ANNUAL", raising=False)
    monkeypatch.delenv("STRIPE_PRICE_ID_EXTRA_STORAGE_QUARTERLY", raising=False)
    monkeypatch.setenv("CHURCH_STORAGE", "on")
    state["meter"] = {"allowance_bytes": 250 * GIB, "extra_bytes": 0, "used_bytes": 100 * GIB, "complete": True}
    monkeypatch.setattr(cs, "used", lambda bid: state["meter"])
    return calls, state


def _store(n, user=USER):
    return asyncio.run(cb.set_extra_storage(cb.ExtraStorageBody(business_id=BIZ, blocks=n), user=user))


def test_the_first_block_adds_an_item(storage):
    calls, state = storage
    out = _store(1)
    assert ("post", "/subscription_items", {"subscription": "sub_1", "price": "price_store", "quantity": 1,
                                            "proration_behavior": "create_prorations"}) in calls
    assert state["biz"]["settings"] == {"extra_storage": 1}
    assert out["extra_storage"] == 1 and out["extra_bytes"] == 100 * GIB and out["gb_each"] == 100
    assert out["cents_each"] == 500 and out["every"] == "month" and out["over"] is None and out["note"] is None


def test_more_blocks_change_the_quantity_and_zero_removes_it(storage):
    calls, state = storage
    state["items"] = [{"id": "si_9", "price": {"id": "price_store"}, "quantity": 1}]
    _store(3)
    assert ("post", "/subscription_items/si_9", {"quantity": 3, "proration_behavior": "create_prorations"}) in calls
    _store(0)
    assert ("delete", "/subscription_items/si_9") in calls and state["biz"]["settings"] == {}


def test_the_login_and_the_storage_items_never_mix(storage):
    calls, state = storage
    state["items"] = [{"id": "si_log", "price": {"id": "price_login"}, "quantity": 2},
                      {"id": "si_sto", "price": {"id": "price_store"}, "quantity": 1}]
    _store(2)
    assert ("post", "/subscription_items/si_sto", {"quantity": 2, "proration_behavior": "create_prorations"}) in calls
    assert not [c for c in calls if c[0] in ("post", "delete") and "si_log" in c[1]]
    assert cb.extra_login_quantity(state["items"]) == 2 and cb.extra_storage_quantity(state["items"]) == 1


@pytest.mark.parametrize("change,detail", [
    ({"subscription_plan": "price_pro_x"}, "Extra storage comes with the church plans."),
    ({"stripe_subscription_id": None}, "Extra storage is added to a paid church plan."),
])
def test_storage_refused_off_a_church_plan_or_without_a_subscription(storage, change, detail):
    _calls, state = storage
    state["biz"] = {**state["biz"], **change}
    with pytest.raises(HTTPException) as e:
        _store(1)
    assert e.value.status_code == 409 and e.value.detail == detail


def test_storage_refused_until_the_price_exists(storage, monkeypatch):
    calls, _state = storage
    monkeypatch.delenv("STRIPE_PRICE_ID_EXTRA_STORAGE")
    with pytest.raises(HTTPException) as e:
        _store(1)
    assert e.value.status_code == 409 and e.value.detail == "Extra storage isn't open yet."
    assert calls == []


def test_more_storage_waits_for_the_switch_but_fewer_never_does(storage, monkeypatch):
    calls, state = storage
    monkeypatch.setenv("CHURCH_STORAGE", "off")
    with pytest.raises(HTTPException) as e:
        _store(1)
    assert e.value.status_code == 409 and not [c for c in calls if c[0] in ("post", "delete", "settings")]
    state["items"] = [{"id": "si_9", "price": {"id": "price_store"}, "quantity": 2}]
    out = _store(0)
    assert ("delete", "/subscription_items/si_9") in calls
    assert out["over"] is None and out["note"] is None          # switched off: no rule to tell about


def test_only_the_owner_buys_storage(storage):
    calls, _state = storage
    with pytest.raises(HTTPException) as e:
        _store(1, user=AuthedUser(id="someone-else", email="x@y.test", role="authenticated"))
    assert e.value.status_code == 403 and calls == []


def test_a_block_added_to_a_running_plan_is_paid_for_today(storage):
    calls, state = storage
    state["status"] = "active"
    out = _store(1)
    assert ("post", "/subscription_items", {"subscription": "sub_1", "price": "price_store", "quantity": 1,
                                            **PAID_TODAY}) in calls
    assert out["charged_today"] is True


def test_fewer_blocks_leave_a_credit(storage):
    calls, state = storage
    state["status"] = "active"
    state["items"] = [{"id": "si_9", "price": {"id": "price_store"}, "quantity": 3}]
    assert _store(1)["charged_today"] is False
    assert ("post", "/subscription_items/si_9", {"quantity": 1, "proration_behavior": "create_prorations"}) in calls


def test_a_refused_card_adds_no_storage(storage):
    calls, state = storage
    state["status"], state["refuse"] = "active", 402
    with pytest.raises(HTTPException) as e:
        _store(1)
    assert e.value.status_code == 402 and e.value.detail == sb.CARD_REFUSED
    assert state["biz"]["settings"] == {} and not [c for c in calls if c[0] in ("patch", "settings")]


def test_a_stripe_failure_reads_as_plain_words(storage):
    _calls, state = storage
    state["refuse"] = 400
    with pytest.raises(HTTPException) as e:
        _store(1)
    assert e.value.status_code == 400
    assert e.value.detail == "Your storage didn't change. Try again in a minute, or write to us."
    assert state["biz"]["settings"] == {}


def test_a_settings_write_that_fails_after_stripe_changed_is_not_a_failure(storage, monkeypatch):
    calls, state = storage
    from settings_merge_fake import install
    install(monkeypatch, lambda bid: state["biz"], fail=lambda: True)
    out = _store(1)
    assert out["ok"] is True and out["extra_storage"] == 1      # the webhook writes the count
    assert ("post", "/subscription_items", {"subscription": "sub_1", "price": "price_store", "quantity": 1,
                                            "proration_behavior": "create_prorations"}) in calls


def test_fewer_blocks_that_put_the_church_over_are_allowed_and_said(storage):
    import church_storage as cs
    calls, state = storage
    state["items"] = [{"id": "si_9", "price": {"id": "price_store"}, "quantity": 2}]
    state["meter"] = {"allowance_bytes": 250 * GIB, "extra_bytes": 0, "used_bytes": 300 * GIB, "complete": True}
    out = _store(0)                                              # 300 GB used, 250 GB room
    assert ("delete", "/subscription_items/si_9") in calls
    assert out["over"] is True and out["note"] == cs.fewer_blocks_words(True)
    assert "kept 14 days" in out["note"] and "Nothing is deleted now." in out["note"]
    assert "Published sermons are never deleted." in out["note"]
    state["items"] = [{"id": "si_9", "price": {"id": "price_store"}, "quantity": 2}]
    out = _store(1)                                              # 350 GB of room: under it
    assert out["over"] is False and out["note"] is None


@pytest.mark.parametrize("meter", [None, {"allowance_bytes": 250 * GIB, "used_bytes": 1, "complete": False}])
def test_fewer_blocks_unmeasured_say_the_rule_as_an_if(storage, meter):
    import church_storage as cs
    _calls, state = storage
    state["items"] = [{"id": "si_9", "price": {"id": "price_store"}, "quantity": 2}]
    state["meter"] = meter
    out = _store(1)
    assert out["over"] is None and out["note"] == cs.fewer_blocks_words(None)
    assert out["note"].startswith("If your church now uses more storage than it has")


def test_more_blocks_never_measure(storage, monkeypatch):
    import church_storage as cs

    def never(bid):
        raise AssertionError("not asked")
    monkeypatch.setattr(cs, "used", never)
    out = _store(2)
    assert out["over"] is None and out["note"] is None


def test_a_yearly_church_buys_its_storage_by_the_year(yearly, storage, monkeypatch):
    calls, state = storage
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_STORAGE_ANNUAL", "price_store_year")
    out = _store(2)
    assert ("post", "/subscription_items", {"subscription": "sub_1", "price": "price_store_year", "quantity": 2,
                                            **PAID_TODAY}) in calls
    assert out["cents_each"] == 5000 and out["every"] == "year"
    assert state["biz"]["settings"] == {"extra_storage": 2}


def test_a_yearly_church_is_told_to_write_in_until_the_yearly_storage_price_exists(yearly, storage):
    calls, _state = storage
    with pytest.raises(HTTPException) as e:
        _store(1)
    assert e.value.status_code == 409 and "Write to us" in e.value.detail
    assert not [c for c in calls if c[0] in ("post", "delete", "patch", "settings")]


def test_yearly_storage_is_counted_and_can_be_taken_off(yearly, storage, monkeypatch):
    calls, state = storage
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_STORAGE_ANNUAL", "price_store_year")
    block = {"id": "si_9", "price": {"id": "price_store_year"}, "quantity": 2}
    state["items"] = [YEAR_PLAN, block]
    assert cb.extra_storage_quantity(state["items"]) == 2
    _store(0)
    assert ("delete", "/subscription_items/si_9") in calls


def test_a_church_paying_every_three_months_buys_its_storage_that_way(storage, monkeypatch):
    calls, state = storage
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_QUARTERLY", "price_grow_q")
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_STORAGE_QUARTERLY", "price_store_q")
    state["status"] = "active"
    state["items"] = [{"id": "si_plan", "quantity": 1,
                       "price": {"id": "price_grow_q", "recurring": {"interval": "month", "interval_count": 3}}}]
    state["biz"]["subscription_plan"] = "price_grow_q"
    out = _store(1)
    assert ("post", "/subscription_items", {"subscription": "sub_1", "price": "price_store_q", "quantity": 1,
                                            **PAID_TODAY}) in calls
    assert out["cents_each"] == 1500 and out["every"] == "quarter"


def test_the_storage_prices_follow_the_plans_terms():
    import marketing_pages as mp
    import pricing_config
    cat = {env: (cents, interval) for env, _lk, _n, cents, interval in sb.BOOTSTRAP_CATALOG}
    month = pricing_config.extra_storage_offer()["cents"]
    assert cat["STRIPE_PRICE_ID_EXTRA_STORAGE"] == (month, "month") == (500, "month")
    assert cat["STRIPE_PRICE_ID_EXTRA_STORAGE_ANNUAL"] == (month * mp.ANNUAL_MONTHS, "year")
    assert cat["STRIPE_PRICE_ID_EXTRA_STORAGE_QUARTERLY"] == (month * 3, "quarter")
    assert cb.extra_storage_cents(cb.YEARLY) == 5000 and cb.extra_storage_cents(cb.QUARTERLY) == 1500
    names = {n for env, _lk, n, _c, _i in sb.BOOTSTRAP_CATALOG if env.startswith("STRIPE_PRICE_ID_EXTRA_STORAGE")}
    assert names == {"Solutionist extra storage, 100 GB"}
    assert set(cb.STORAGE_PRICE_ENVS.values()) == {e for e in cat if e.startswith("STRIPE_PRICE_ID_EXTRA_STORAGE")}


def test_storage_follows_a_change_of_term_or_refuses_it(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_STORAGE", "price_store")
    monkeypatch.delenv("STRIPE_PRICE_ID_EXTRA_STORAGE_ANNUAL", raising=False)
    held = [{"id": "si_9", "price": {"id": "price_store"}, "quantity": 2}]
    assert cb.storage_for_term([], cb.YEARLY) == []
    assert cb.storage_for_term(held, cb.MONTHLY) == []
    with pytest.raises(HTTPException) as e:
        cb.storage_for_term(held, cb.YEARLY)
    assert e.value.status_code == 409 and "extra storage" in e.value.detail
    monkeypatch.setenv("STRIPE_PRICE_ID_EXTRA_STORAGE_ANNUAL", "price_store_year")
    assert cb.storage_for_term(held, cb.YEARLY) == [{"id": "si_9", "price": "price_store_year"}]


def test_a_rows_term_is_read_without_asking_stripe(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING", "price_grow")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_ANNUAL", "price_grow_year")
    monkeypatch.setenv("STRIPE_PRICE_ID_CHURCH_GROWING_QUARTERLY", "price_grow_q")
    assert cb.row_term({"subscription_plan": "price_grow"}) == cb.MONTHLY
    assert cb.row_term({"subscription_plan": "price_grow_year"}) == cb.YEARLY
    assert cb.row_term({"subscription_plan": "price_grow_q"}) == cb.QUARTERLY
    assert cb.row_term({"subscription_plan": "price_unknown"}) == cb.MONTHLY == cb.row_term(None)
