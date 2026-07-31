# __tests__/test_invoice_checkout.py
#
# The per-invoice pay-link rail (POST /payments/invoice-checkout) — the
# replacement for the static-pasted-link + webhook amount-matching path.
# Pins:
#   1. the route exists and REQUIRES auth (require_user dependency)
#   2. 409 when the business has no stripe_account_id
#   3. 409 when the invoice is already paid
#   4. the Payment-Link form carries the source metadata the Connect
#      webhook resolves invoices by (session AND payment_intent mirror)
#   5. the seam: unimplemented providers answer 409, and the webhook's
#      _mark_invoice_paid stamps payment_method='stripe' so GL routes
#      the payment through 1150 Stripe Clearing, not 1000 Cash

import asyncio
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi import HTTPException

import payments_core
import stripe_payments_router
from stripe_payments_router import InvoiceCheckoutBody, invoice_checkout


_USER = SimpleNamespace(id="user-1", email="owner@example.com")

_INVOICE = {
    "id": "inv-1",
    "business_id": "biz-1",
    "contact_id": "c-1",
    "invoice_number": "INV-2026-007",
    "total": 500.0,
    "currency": "USD",
    "status": "draft",
    "stripe_payment_url": None,
}

_BIZ_CONNECTED = {
    "id": "biz-1",
    "name": "Test Biz",
    "owner_id": "user-1",
    "stripe_account_id": "acct_123",
    "settings": {},
}

_BIZ_NO_STRIPE = {**_BIZ_CONNECTED, "stripe_account_id": None}


def _sb_get(invoice=None, biz=None):
    def fake(path: str):
        if path.startswith("/invoices"):
            return [invoice] if invoice else []
        if path.startswith("/businesses"):
            return [biz] if biz else []
        return []
    return fake


def _run(body, invoice, biz, role="owner", link=None):
    """Drive the endpoint handler with everything external mocked."""
    patches = []
    calls = {"patched": []}

    def fake_patch(path, payload):
        calls["patched"].append((path, payload))

    async def fake_create(self, biz_row, **kwargs):
        calls["create_kwargs"] = kwargs
        return link or {"id": "plink_1", "url": "https://buy.stripe.com/test_x"}

    patches.append(mock.patch.object(
        stripe_payments_router.sb_clients, "sb_get_as_service",
        _sb_get(invoice, biz)))
    patches.append(mock.patch.object(
        stripe_payments_router.sb_clients, "sb_patch_as_service", fake_patch))
    import business_users_router
    patches.append(mock.patch.object(
        business_users_router, "require_role", lambda b, u, m: role))
    patches.append(mock.patch.object(
        payments_core.StripeAdapter, "create_invoice_checkout", fake_create))
    with patches[0], patches[1], patches[2], patches[3]:
        result = asyncio.run(invoice_checkout(body, user=_USER))
    return result, calls


def test_route_exists_and_requires_auth():
    from auth_supabase import require_user

    route = next(r for r in stripe_payments_router.router.routes
                 if r.path == "/payments/invoice-checkout")
    assert "POST" in route.methods
    deps = [d.call for d in route.dependant.dependencies]
    assert require_user in deps, "/payments/invoice-checkout must require auth"


def test_409_without_stripe_account_id():
    import business_users_router
    with mock.patch.object(stripe_payments_router.sb_clients,
                           "sb_get_as_service",
                           _sb_get(_INVOICE, _BIZ_NO_STRIPE)), \
         mock.patch.object(business_users_router, "require_role",
                           lambda b, u, m: "owner"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(invoice_checkout(
                InvoiceCheckoutBody(invoice_id="inv-1"), user=_USER))
    assert exc.value.status_code == 409
    assert "connect" in str(exc.value.detail).lower()


def test_409_when_already_paid():
    import business_users_router
    paid = {**_INVOICE, "status": "paid"}
    with mock.patch.object(stripe_payments_router.sb_clients,
                           "sb_get_as_service",
                           _sb_get(paid, _BIZ_CONNECTED)), \
         mock.patch.object(business_users_router, "require_role",
                           lambda b, u, m: "owner"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(invoice_checkout(
                InvoiceCheckoutBody(invoice_id="inv-1"), user=_USER))
    assert exc.value.status_code == 409


def test_404_when_invoice_missing():
    with mock.patch.object(stripe_payments_router.sb_clients,
                           "sb_get_as_service", _sb_get(None, None)):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(invoice_checkout(
                InvoiceCheckoutBody(invoice_id="nope"), user=_USER))
    assert exc.value.status_code == 404


def test_happy_path_creates_link_and_persists_url():
    result, calls = _run(InvoiceCheckoutBody(invoice_id="inv-1"),
                         _INVOICE, _BIZ_CONNECTED)
    assert result["ok"] is True
    assert result["url"] == "https://buy.stripe.com/test_x"
    assert result["reused"] is False
    # Amount derived server-side from the invoice row — cents, not caller input.
    assert calls["create_kwargs"]["amount_cents"] == 50000
    assert calls["create_kwargs"]["invoice_id"] == "inv-1"
    # URL persisted onto the invoice for the email + Payment Options row.
    patched_paths = [p for p, _ in calls["patched"]]
    assert any(p.startswith("/invoices?id=eq.inv-1") for p in patched_paths)
    patched_bodies = [b for _, b in calls["patched"]]
    assert {"stripe_payment_url": "https://buy.stripe.com/test_x"} in patched_bodies


def test_reuses_existing_per_invoice_link():
    inv = {**_INVOICE, "stripe_payment_url": "https://buy.stripe.com/existing"}
    result, calls = _run(InvoiceCheckoutBody(invoice_id="inv-1"),
                         inv, _BIZ_CONNECTED)
    assert result["reused"] is True
    assert result["url"] == "https://buy.stripe.com/existing"
    assert "create_kwargs" not in calls  # no new Stripe object minted


def test_static_pasted_link_does_not_block_generation():
    # An invoice created before Connect carries the business's shared
    # static link — that is NOT a per-invoice link and must be replaced.
    biz = {**_BIZ_CONNECTED,
           "settings": {"payments": {"stripe_link": "https://buy.stripe.com/static"}}}
    inv = {**_INVOICE, "stripe_payment_url": "https://buy.stripe.com/static"}
    result, calls = _run(InvoiceCheckoutBody(invoice_id="inv-1"), inv, biz)
    assert result["reused"] is False
    assert result["url"] == "https://buy.stripe.com/test_x"
    assert calls["create_kwargs"]["invoice_id"] == "inv-1"


def test_payment_link_form_metadata_contract():
    # The webhook resolves invoices from this metadata — session-level
    # AND the payment_intent mirror (refund events only see PI metadata).
    from stripe_checkout_helpers import _invoice_link_form

    form = _invoice_link_form(price_id="price_1", invoice_id="inv-1",
                              business_id="biz-1")
    assert form["metadata[source_type]"] == "invoice"
    assert form["metadata[source_id]"] == "inv-1"
    assert form["payment_intent_data[metadata][source_type]"] == "invoice"
    assert form["payment_intent_data[metadata][source_id]"] == "inv-1"
    assert form["metadata[business_id]"] == "biz-1"
    assert form["payment_intent_data[metadata][business_id]"] == "biz-1"
    assert form["line_items[0][price]"] == "price_1"


def test_unimplemented_provider_answers_409():
    square = payments_core.REGISTRY["square"]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(square.create_invoice_checkout({}, invoice_id="inv-1"))
    assert exc.value.status_code == 409
    assert "Square" in str(exc.value.detail)


def test_webhook_mark_paid_stamps_stripe_payment_method():
    # gl_engine._is_non_stripe_payment reads payment_method to route the
    # payment debit to 1150 Stripe Clearing instead of 1000 Cash.
    import stripe_connect_router

    calls = {"patches": [], "posts": []}

    def fake_get(path):
        if path.startswith("/invoices"):
            return [{"id": "inv-1", "status": "sent", "business_id": "biz-1",
                     "contact_id": None, "invoice_number": "INV-2026-007",
                     "total": 500.0}]
        return []

    def fake_patch(path, payload):
        calls["patches"].append((path, payload))

    def fake_post(path, payload):
        calls["posts"].append((path, payload))

    import event_spine
    with mock.patch.object(stripe_connect_router.sb_clients,
                           "sb_get_as_service", fake_get), \
         mock.patch.object(stripe_connect_router.sb_clients,
                           "sb_patch_as_service", fake_patch), \
         mock.patch.object(stripe_connect_router.sb_clients,
                           "sb_post_as_service", fake_post), \
         mock.patch.object(event_spine, "emit", lambda *a, **k: True):
        stripe_connect_router._mark_invoice_paid("inv-1")

    invoice_patches = [b for p, b in calls["patches"]
                       if p.startswith("/invoices?id=eq.inv-1")]
    assert invoice_patches, "invoice must be patched"
    assert invoice_patches[0]["status"] == "paid"
    assert invoice_patches[0]["payment_method"] == "stripe"
    assert invoice_patches[0].get("paid_at")


def test_gl_routes_stripe_paid_invoice_through_clearing():
    # End-of-rail truth: a webhook-marked invoice produces a payment
    # entry debiting 1150, mirroring the booking clearing pattern.
    import gl_engine

    inv = {"id": "inv-1", "total": 500.0, "status": "paid",
           "paid_at": "2026-07-31T00:00:00+00:00",
           "sent_at": "2026-07-30T00:00:00+00:00",
           "payment_method": "stripe", "stripe_payment_url": None}
    entries = gl_engine.desired_for_invoice(inv)
    payment = next(e for e in entries if e["source_type"] == "invoice_payment")
    debit_codes = [l["code"] for l in payment["lines"] if l["debit"] > 0]
    assert debit_codes == ["1150"]
