# __tests__/test_barber_money.py
#
# The barber/salon money model — deposits, tips, no-show fees.
# Pins:
#   1. compute_deposit_cents math (percent + flat + fail-soft on
#      missing columns + degrade-to-full-price edges)
#   2. the booking-checkout parts contract: deposit line item, tip as a
#      SEPARATE line item, metadata (payment_kind / deposit_cents /
#      remainder_cents / tip_cents), setup_future_usage for card storage
#   3. tip validation at the router
#   4. POST /payments/charge-no-show: auth required, manager+ role,
#      409s (no fee / no card / already charged), 404s, idempotency key,
#      decline surfacing, happy-path entry patch
#   5. webhook: deposit-paid state + card refs recorded by
#      _mark_booking_paid; the no-show fee PI never flips paid_at

import asyncio
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi import HTTPException

import payments_core
import stripe_payments_router
from payments_core import compute_deposit_cents
from stripe_checkout_helpers import _booking_checkout_parts, _checkout_session_form
from stripe_payments_router import (
    BookingCheckoutBody,
    ChargeNoShowBody,
    _validate_tip_cents,
    booking_checkout,
    charge_no_show,
)

_USER = SimpleNamespace(id="user-1", email="owner@example.com")


# ─── 1. Deposit math ─────────────────────────────────────────────────


def test_deposit_percent():
    off = {"requires_deposit": True, "deposit_type": "percent", "deposit_amount": 25}
    assert compute_deposit_cents(off, 6000) == 1500  # 25% of $60


def test_deposit_flat():
    off = {"requires_deposit": True, "deposit_type": "flat", "deposit_amount": 20}
    assert compute_deposit_cents(off, 6000) == 2000  # $20 of $60


def test_deposit_fail_soft_missing_columns():
    # Pre-migration offering rows simply lack the keys → full price.
    assert compute_deposit_cents({"id": "off-1", "current_price": 60}, 6000) is None
    assert compute_deposit_cents({}, 6000) is None
    assert compute_deposit_cents(None, 6000) is None


def test_deposit_degrades_to_full_price_on_bad_config():
    # flat deposit >= price → just prepay in full (no deposit framing)
    assert compute_deposit_cents(
        {"requires_deposit": True, "deposit_type": "flat", "deposit_amount": 60}, 6000) is None
    # 100%+ percent → same
    assert compute_deposit_cents(
        {"requires_deposit": True, "deposit_type": "percent", "deposit_amount": 100}, 6000) is None
    # zero / negative / junk amounts → no deposit
    assert compute_deposit_cents(
        {"requires_deposit": True, "deposit_type": "percent", "deposit_amount": 0}, 6000) is None
    assert compute_deposit_cents(
        {"requires_deposit": True, "deposit_type": "percent", "deposit_amount": "abc"}, 6000) is None
    # unknown type → no deposit
    assert compute_deposit_cents(
        {"requires_deposit": True, "deposit_type": "half", "deposit_amount": 50}, 6000) is None
    # requires_deposit false wins over a configured amount
    assert compute_deposit_cents(
        {"requires_deposit": False, "deposit_type": "flat", "deposit_amount": 20}, 6000) is None


def test_deposit_percent_rounds_to_the_cent():
    off = {"requires_deposit": True, "deposit_type": "percent", "deposit_amount": 33}
    assert compute_deposit_cents(off, 9999) == 3300  # round(3299.67)


# ─── 2. Checkout parts contract ──────────────────────────────────────


def test_full_price_checkout_unchanged():
    parts = _booking_checkout_parts(service_name="Haircut", amount_cents=6000)
    assert parts["line_items"] == [
        {"name": "Haircut", "amount_cents": 6000, "quantity": 1}]
    assert parts["extra_metadata"]["payment_kind"] == "full"
    assert "deposit_cents" not in parts["extra_metadata"]
    assert "tip_cents" not in parts["extra_metadata"]
    assert parts["setup_future_usage"] is None


def test_deposit_line_item_and_metadata():
    parts = _booking_checkout_parts(
        service_name="Haircut", amount_cents=6000, deposit_cents=1500)
    assert parts["line_items"][0] == {
        "name": "Deposit — Haircut", "amount_cents": 1500, "quantity": 1}
    md = parts["extra_metadata"]
    assert md["payment_kind"] == "deposit"
    assert md["deposit_cents"] == 1500
    assert md["remainder_cents"] == 4500
    assert md["service_cents"] == 6000


def test_tip_is_a_separate_line_item():
    parts = _booking_checkout_parts(
        service_name="Haircut", amount_cents=6000, deposit_cents=1500,
        tip_cents=1200)  # 20% of the FULL $60, riding the deposit payment
    assert {"name": "Tip", "amount_cents": 1200, "quantity": 1} in parts["line_items"]
    assert parts["extra_metadata"]["tip_cents"] == 1200
    # Tip rides in full — deposit math never splits it.
    assert parts["line_items"][0]["amount_cents"] == 1500


def test_store_payment_method_sets_off_session():
    parts = _booking_checkout_parts(
        service_name="Haircut", amount_cents=6000, store_payment_method=True)
    assert parts["setup_future_usage"] == "off_session"
    assert parts["extra_metadata"]["store_payment_method"] == "1"


def test_session_form_carries_extras_and_setup_future_usage():
    form = _checkout_session_form(
        line_items=[{"name": "Deposit — Haircut", "amount_cents": 1500, "quantity": 1},
                    {"name": "Tip", "amount_cents": 1200, "quantity": 1}],
        success_url="https://x/ok", cancel_url="https://x/no",
        source_type="booking", source_id="bk-1",
        extra_metadata={"payment_kind": "deposit", "deposit_cents": 1500,
                        "remainder_cents": 4500, "tip_cents": 1200},
        setup_future_usage="off_session",
    )
    # Metadata on session AND payment_intent mirror (webhook contract).
    assert form["metadata[payment_kind]"] == "deposit"
    assert form["payment_intent_data[metadata][payment_kind]"] == "deposit"
    assert form["metadata[tip_cents]"] == 1200
    assert form["payment_intent_data[metadata][deposit_cents]"] == 1500
    # Card storage for the no-show fee.
    assert form["payment_intent_data[setup_future_usage]"] == "off_session"
    # The routing contract can never be overwritten by extras.
    assert form["metadata[source_type]"] == "booking"
    assert form["metadata[source_id]"] == "bk-1"
    # Both line items encoded.
    assert form["line_items[0][price_data][unit_amount]"] == 1500
    assert form["line_items[1][price_data][product_data][name]"] == "Tip"
    assert form["line_items[1][price_data][unit_amount]"] == 1200


def test_extras_cannot_overwrite_source_routing():
    form = _checkout_session_form(
        line_items=[{"name": "X", "amount_cents": 100, "quantity": 1}],
        success_url="s", cancel_url="c",
        source_type="booking", source_id="bk-1",
        extra_metadata={"source_type": "invoice", "source_id": "evil"},
    )
    assert form["metadata[source_type]"] == "booking"
    assert form["metadata[source_id]"] == "bk-1"


# ─── 3. Tip validation ───────────────────────────────────────────────


def test_tip_validation():
    assert _validate_tip_cents(0, 6000) == 0
    assert _validate_tip_cents(1200, 6000) == 1200
    with pytest.raises(HTTPException) as exc:
        _validate_tip_cents(-1, 6000)
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        _validate_tip_cents(10_000_000, 6000)  # $100k "tip" = typo
    assert exc.value.status_code == 400


# ─── booking-checkout wiring (server-side amounts) ───────────────────


_BOOKING_ENTRY = {
    "id": "bk-1",
    "business_id": "biz-1",
    "paid_at": None,
    "status": "active",
    "data": {
        "price_at_booking": 60.0,
        "service_name_at_booking": "Haircut",
        "customer_email": "guest@example.com",
        "offering_id": "off-1",
    },
}

_BIZ = {"id": "biz-1", "name": "Fade Factory", "stripe_account_id": "acct_1",
        "settings": {}}

_OFFERING_DEPOSIT = {
    "id": "off-1", "business_id": "biz-1", "current_price": 60.0,
    "requires_deposit": True, "deposit_type": "percent", "deposit_amount": 25,
    "no_show_fee_cents": 2500,
}


def _run_booking_checkout(entry, offering, body=None):
    calls = {"patched": []}

    def fake_get(path):
        if path.startswith("/module_entries"):
            return [entry] if entry else []
        if path.startswith("/businesses"):
            return [_BIZ]
        if path.startswith("/offerings"):
            return [offering] if offering else []
        if path.startswith("/business_sites"):
            return []
        return []

    def fake_patch(path, payload):
        calls["patched"].append((path, payload))

    async def fake_create(self, biz_row, **kwargs):
        calls["create_kwargs"] = kwargs
        return {"id": "cs_1", "url": "https://checkout.stripe.com/x"}

    with mock.patch.object(stripe_payments_router.sb_clients,
                           "sb_get_as_service", fake_get), \
         mock.patch.object(stripe_payments_router.sb_clients,
                           "sb_patch_as_service", fake_patch), \
         mock.patch.object(payments_core.StripeAdapter,
                           "create_booking_checkout", fake_create):
        result = asyncio.run(booking_checkout(
            body or BookingCheckoutBody(booking_id="bk-1"),
            request=mock.Mock()))
    return result, calls


def test_checkout_passes_server_computed_deposit_and_stores_card():
    result, calls = _run_booking_checkout(_BOOKING_ENTRY, _OFFERING_DEPOSIT,
                                          BookingCheckoutBody(booking_id="bk-1",
                                                              tip_cents=1200))
    kw = calls["create_kwargs"]
    assert kw["amount_cents"] == 6000          # frozen price, server-derived
    assert kw["deposit_cents"] == 1500         # 25% server-side
    assert kw["tip_cents"] == 1200
    assert kw["store_payment_method"] is True  # no_show_fee_cents > 0
    assert result["deposit_cents"] == 1500
    # The DISCLOSED fee is frozen onto the entry (charge endpoint truth).
    frozen = [b for p, b in calls["patched"] if p.startswith("/module_entries")]
    assert frozen and frozen[0]["data"]["no_show_fee_cents"] == 2500


def test_checkout_without_offering_config_is_unchanged():
    entry = {**_BOOKING_ENTRY, "data": {**_BOOKING_ENTRY["data"]}}
    result, calls = _run_booking_checkout(entry, {"id": "off-1"})  # pre-migration shape
    kw = calls["create_kwargs"]
    assert kw["deposit_cents"] is None
    assert kw["store_payment_method"] is False
    assert kw["tip_cents"] == 0
    assert calls["patched"] == []  # nothing frozen, nothing touched


# ─── 4. charge-no-show endpoint ──────────────────────────────────────


def _noshow_entry(**data_over):
    return {
        "id": "bk-1", "business_id": "biz-1", "status": "no_show",
        "data": {
            "service_name_at_booking": "Haircut",
            "no_show_fee_cents": 2500,
            "stripe_customer_id": "cus_1",
            **data_over,
        },
    }


def _run_noshow(entry, *, role="manager", charge=None, charge_err=None):
    calls = {"patched": [], "role_args": None}

    def fake_get(path):
        if path.startswith("/module_entries"):
            return [entry] if entry else []
        if path.startswith("/businesses"):
            return [_BIZ]
        return []

    def fake_patch(path, payload):
        calls["patched"].append((path, payload))

    async def fake_charge(self, biz_row, **kwargs):
        calls["charge_kwargs"] = kwargs
        if charge_err:
            raise charge_err
        return charge or {"id": "pi_ns_1", "status": "succeeded"}

    def fake_role(biz, uid, min_role):
        calls["role_args"] = (biz, uid, min_role)
        return role

    import business_users_router
    with mock.patch.object(stripe_payments_router.sb_clients,
                           "sb_get_as_service", fake_get), \
         mock.patch.object(stripe_payments_router.sb_clients,
                           "sb_patch_as_service", fake_patch), \
         mock.patch.object(business_users_router, "require_role", fake_role), \
         mock.patch.object(payments_core.StripeAdapter,
                           "charge_saved_payment_method", fake_charge):
        result = asyncio.run(charge_no_show(
            ChargeNoShowBody(booking_id="bk-1"), user=_USER))
    return result, calls


def test_charge_no_show_route_requires_auth():
    from auth_supabase import require_user
    route = next(r for r in stripe_payments_router.router.routes
                 if r.path == "/payments/charge-no-show")
    assert "POST" in route.methods
    deps = [d.call for d in route.dependant.dependencies]
    assert require_user in deps, "/payments/charge-no-show must require auth"


def test_charge_no_show_gates_at_manager():
    _, calls = _run_noshow(_noshow_entry())
    assert calls["role_args"] == ("biz-1", "user-1", "manager")


def test_charge_no_show_404_when_booking_missing():
    with pytest.raises(HTTPException) as exc:
        _run_noshow(None)
    assert exc.value.status_code == 404


def test_charge_no_show_409_without_fee():
    with pytest.raises(HTTPException) as exc:
        _run_noshow(_noshow_entry(no_show_fee_cents=0))
    assert exc.value.status_code == 409


def test_charge_no_show_409_without_stored_card():
    with pytest.raises(HTTPException) as exc:
        _run_noshow(_noshow_entry(stripe_customer_id=None))
    assert exc.value.status_code == 409
    assert "card on file" in str(exc.value.detail)


def test_charge_no_show_409_when_already_charged():
    with pytest.raises(HTTPException) as exc:
        _run_noshow(_noshow_entry(no_show_fee_charged_at="2026-07-31T00:00:00Z"))
    assert exc.value.status_code == 409
    assert "already" in str(exc.value.detail)


def test_charge_no_show_surfaces_declines_as_402():
    with pytest.raises(HTTPException) as exc:
        _run_noshow(_noshow_entry(),
                    charge_err=RuntimeError("charge_failed:card_declined"))
    assert exc.value.status_code == 402
    assert "declined" in str(exc.value.detail)


def test_charge_no_show_happy_path_charges_and_records():
    result, calls = _run_noshow(_noshow_entry())
    kw = calls["charge_kwargs"]
    assert kw["amount_cents"] == 2500              # the frozen, disclosed fee
    assert kw["customer_id"] == "cus_1"
    assert kw["idempotency_key"] == "noshow-bk-1"  # double-click = one PI
    assert kw["metadata"]["payment_kind"] == "no_show_fee"
    assert result["ok"] is True and result["amount_cents"] == 2500
    patched = [b for p, b in calls["patched"] if p.startswith("/module_entries")]
    assert patched
    d = patched[0]["data"]
    assert d["no_show_fee_charged_cents"] == 2500
    assert d["no_show_fee_charged_at"]
    assert d["no_show_fee_payment_intent_id"] == "pi_ns_1"


def test_unimplemented_provider_answers_409_for_saved_card_charge():
    square = payments_core.REGISTRY["square"]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(square.charge_saved_payment_method({}, customer_id="cus_1"))
    assert exc.value.status_code == 409


# ─── 5. Webhook state recording ──────────────────────────────────────


def _run_mark_paid(entry, **kwargs):
    import stripe_connect_router
    calls = {"patched": []}

    def fake_get(path):
        if path.startswith("/module_entries"):
            return [entry] if entry else []
        return []

    def fake_patch(path, payload):
        calls["patched"].append((path, payload))

    import event_spine
    with mock.patch.object(stripe_connect_router.sb_clients,
                           "sb_get_as_service", fake_get), \
         mock.patch.object(stripe_connect_router.sb_clients,
                           "sb_patch_as_service", fake_patch), \
         mock.patch.object(event_spine, "emit", lambda *a, **k: True):
        stripe_connect_router._mark_booking_paid(
            "bk-1", payment_intent_id="pi_1", charge_id=None, **kwargs)
    return calls


def test_webhook_records_deposit_state_denormalized():
    entry = {"id": "bk-1", "paid_at": None, "business_id": "biz-1",
             "contact_id": None, "data": {"price_at_booking": 60.0}}
    calls = _run_mark_paid(
        entry,
        metadata={"payment_kind": "deposit", "deposit_cents": "1500",
                  "remainder_cents": "4500", "tip_cents": "1200"},
        stripe_customer_id="cus_1")
    data_patches = [b["data"] for _, b in calls["patched"] if "data" in b]
    assert data_patches, "deposit state must land on the entry"
    d = data_patches[0]
    assert d["deposit_paid_cents"] == 1500
    assert d["remainder_due_cents"] == 4500      # remainder-due derivable
    assert d["deposit_paid_at"]
    assert d["tip_cents"] == 1200
    assert d["stripe_customer_id"] == "cus_1"    # card-on-file ref
    # paid_at still flips (money was received).
    paid_patches = [b for _, b in calls["patched"] if b.get("paid_at")]
    assert paid_patches


def test_webhook_second_channel_merges_payment_method_after_paid():
    # checkout.session.completed already flipped paid_at; the later
    # payment_intent.succeeded still contributes the PM reference.
    entry = {"id": "bk-1", "paid_at": "2026-07-31T00:00:00Z",
             "business_id": "biz-1", "contact_id": None,
             "data": {"stripe_customer_id": "cus_1"}}
    calls = _run_mark_paid(entry, metadata={}, payment_method_id="pm_1")
    data_patches = [b["data"] for _, b in calls["patched"] if "data" in b]
    assert data_patches and data_patches[0]["stripe_payment_method_id"] == "pm_1"
    # …but never re-flips paid_at.
    assert not [b for _, b in calls["patched"] if b.get("paid_at")]


def test_no_show_fee_pi_never_flips_paid_at():
    import stripe_connect_router
    calls = {"get": 0}

    def fake_get(path):
        calls["get"] += 1
        raise AssertionError("no-show fee PI must not touch the booking")

    with mock.patch.object(stripe_connect_router.sb_clients,
                           "sb_get_as_service", fake_get):
        stripe_connect_router._handle_payment_intent_succeeded({
            "id": "pi_ns", "payment_method": "pm_1",
            "metadata": {"source_type": "booking", "source_id": "bk-1",
                         "payment_kind": "no_show_fee"},
        })
    assert calls["get"] == 0
