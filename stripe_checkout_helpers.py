"""
stripe_checkout_helpers.py — Phase D.4 PR 3.

Unified payment-source pattern: every Stripe Checkout Session or
Payment Intent we create carries metadata:
  { source_type, source_id }
where source_type ∈ {'booking', 'consultation', 'invoice', 'manual'}
and source_id is the corresponding Solutionist entity UUID. Webhook
handlers parse this back to link Stripe events to local rows; the
Charges tab renders "from Booking #abc123" / "from Invoice #..." inline.

This module is the single seam through which all checkout sessions
are created so the metadata convention is enforced.

Functions:
  create_checkout_session(...)  — generic; returns Stripe session dict
  create_booking_checkout(...)  — booking pre-pay wrapper
  create_invoice_checkout(...)  — invoice pay-link wrapper (PR 3b)
  create_refund(...)            — issue refund on a charge
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("stripe_checkout_helpers")

STRIPE_API_BASE = "https://api.stripe.com/v1"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)

# Closed enum for source_type. Enforced at this seam so misspellings
# can't reach Stripe.
ALLOWED_SOURCE_TYPES = {"booking", "consultation", "invoice", "manual", "order"}


def _secret_key() -> str:
    k = os.environ.get("STRIPE_SECRET_KEY") or ""
    if not k:
        raise RuntimeError("STRIPE_SECRET_KEY not configured")
    return k


async def create_checkout_session(
    *,
    stripe_account_id: str,
    line_items: List[Dict[str, Any]],
    success_url: str,
    cancel_url: str,
    source_type: str,
    source_id: str,
    customer_email: Optional[str] = None,
    application_fee_amount_cents: int = 0,
    currency: str = "usd",
    collect_shipping: bool = False,
) -> Dict[str, Any]:
    """Create a Stripe Checkout Session on the connected account.

    Args:
      stripe_account_id   — practitioner's connected acct_… (Stripe-Account header)
      line_items          — list of {name, amount_cents, quantity}; mapped
                            to Stripe's line_items[][price_data] shape
      success_url         — where Stripe sends the customer after pay
      cancel_url          — where Stripe sends the customer on cancel
      source_type         — enum from ALLOWED_SOURCE_TYPES
      source_id           — Solutionist UUID this payment is "from"
      customer_email      — optional prefill on the Stripe-hosted page
      application_fee_amount_cents — platform fee (v1 = 0)

    Returns the Stripe Checkout Session dict (key fields: id, url).
    Raises RuntimeError on Stripe error so the caller can translate
    to an HTTPException.
    """
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ValueError(
            f"source_type must be one of {sorted(ALLOWED_SOURCE_TYPES)}, got {source_type!r}"
        )
    if not stripe_account_id:
        raise ValueError("stripe_account_id required")
    if not source_id:
        raise ValueError("source_id required")
    if not line_items:
        raise ValueError("line_items required")

    form: Dict[str, Any] = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        # Closed-enum metadata that webhook handlers + Charges tab parse.
        "metadata[source_type]": source_type,
        "metadata[source_id]": source_id,
        # Mirror on the underlying payment_intent so charge-level events
        # also carry the link (Stripe propagates checkout session
        # metadata to PI only when payment_intent_data is set).
        "payment_intent_data[metadata][source_type]": source_type,
        "payment_intent_data[metadata][source_id]": source_id,
    }
    if customer_email:
        form["customer_email"] = customer_email
    if application_fee_amount_cents and application_fee_amount_cents > 0:
        form["payment_intent_data[application_fee_amount]"] = application_fee_amount_cents
    if collect_shipping:
        # Arc 27 — physical goods: Stripe collects the address on the
        # hosted page; the webhook copies it onto the order row.
        form["shipping_address_collection[allowed_countries][0]"] = "US"

    # Encode line_items[] with indexed keys: line_items[0][price_data]...
    for i, item in enumerate(line_items):
        name = (item.get("name") or "Service").strip()
        amount_cents = int(item.get("amount_cents") or 0)
        quantity = int(item.get("quantity") or 1)
        if amount_cents <= 0 or quantity <= 0:
            raise ValueError(f"line_items[{i}] needs positive amount + quantity")
        form[f"line_items[{i}][quantity]"] = quantity
        form[f"line_items[{i}][price_data][currency]"] = currency
        form[f"line_items[{i}][price_data][product_data][name]"] = name
        form[f"line_items[{i}][price_data][unit_amount]"] = amount_cents

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{STRIPE_API_BASE}/checkout/sessions",
            auth=(_secret_key(), ""),
            headers={"Stripe-Account": stripe_account_id},
            data=form,
        )
    if resp.status_code >= 400:
        logger.warning(
            f"create_checkout_session failed: {resp.status_code} {resp.text[:300]}"
        )
        raise RuntimeError(
            f"stripe checkout session create failed ({resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()


async def create_booking_checkout(
    *,
    stripe_account_id: str,
    booking_id: str,
    service_name: str,
    amount_cents: int,
    customer_email: Optional[str],
    success_url: str,
    cancel_url: str,
) -> Dict[str, Any]:
    """Wrapper for the wizard CheckoutStep + the post-booking email."""
    return await create_checkout_session(
        stripe_account_id=stripe_account_id,
        line_items=[{
            "name": service_name or "Booking",
            "amount_cents": amount_cents,
            "quantity": 1,
        }],
        success_url=success_url,
        cancel_url=cancel_url,
        source_type="booking",
        source_id=booking_id,
        customer_email=customer_email,
    )


def _invoice_link_form(
    *,
    price_id: str,
    invoice_id: str,
    business_id: Optional[str],
) -> Dict[str, Any]:
    """The Payment-Link form for an invoice pay link. Pure so tests can
    pin the metadata contract without touching Stripe: the webhook's
    _mark_invoice_paid resolves the invoice from metadata[source_id] —
    lose these keys and payments fall back to amount-matching."""
    form: Dict[str, Any] = {
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": 1,
        "metadata[source_type]": "invoice",
        "metadata[source_id]": invoice_id,
        # Stripe copies Payment-Link metadata onto every Checkout Session
        # it spawns, and payment_intent_data mirrors it onto the PI so
        # charge-level events (refunds) carry the link too.
        "payment_intent_data[metadata][source_type]": "invoice",
        "payment_intent_data[metadata][source_id]": invoice_id,
    }
    if business_id:
        form["metadata[business_id]"] = business_id
        form["payment_intent_data[metadata][business_id]"] = business_id
    return form


async def create_invoice_checkout(
    *,
    stripe_account_id: str,
    invoice_id: str,
    amount_cents: int,
    invoice_number: str = "",
    business_id: Optional[str] = None,
    currency: str = "usd",
) -> Dict[str, Any]:
    """Per-invoice pay link on the connected account (PR 3b, revived).

    Deliberately a Payment Link, NOT a Checkout Session: sessions expire
    within 24 hours and an emailed invoice is routinely paid days later.
    Payment Links never expire, and when a customer pays one Stripe
    emits checkout.session.completed with the link's metadata copied
    onto the session — so the Connect webhook receives
    {source_type: 'invoice', source_id: <invoice_id>} and marks exactly
    this invoice paid. No amount-matching, no cross-matched $500s.

    Returns the Stripe Payment Link dict (key fields: id, url).
    Raises RuntimeError on Stripe error so the caller can translate to
    an HTTPException (same contract as create_checkout_session)."""
    if not stripe_account_id:
        raise ValueError("stripe_account_id required")
    if not invoice_id:
        raise ValueError("invoice_id required")
    amount_cents = int(amount_cents or 0)
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")

    name = f"Invoice {invoice_number}".strip() if invoice_number else "Invoice Payment"
    headers = {"Stripe-Account": stripe_account_id}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        # Step 1 — a one-off Price on the connected account.
        price_resp = await client.post(
            f"{STRIPE_API_BASE}/prices",
            auth=(_secret_key(), ""),
            headers=headers,
            data={
                "unit_amount": amount_cents,
                "currency": (currency or "usd").lower(),
                "product_data[name]": name,
            },
        )
        if price_resp.status_code >= 400:
            logger.warning(
                f"create_invoice_checkout price failed: {price_resp.status_code} "
                f"{price_resp.text[:300]}"
            )
            raise RuntimeError(
                f"stripe price create failed ({price_resp.status_code}): "
                f"{price_resp.text[:200]}"
            )
        price_id = (price_resp.json() or {}).get("id")
        if not price_id:
            raise RuntimeError("stripe returned no price id")

        # Step 2 — wrap it in a Payment Link carrying the source metadata.
        link_resp = await client.post(
            f"{STRIPE_API_BASE}/payment_links",
            auth=(_secret_key(), ""),
            headers=headers,
            data=_invoice_link_form(
                price_id=price_id, invoice_id=invoice_id, business_id=business_id,
            ),
        )
    if link_resp.status_code >= 400:
        logger.warning(
            f"create_invoice_checkout link failed: {link_resp.status_code} "
            f"{link_resp.text[:300]}"
        )
        raise RuntimeError(
            f"stripe payment link create failed ({link_resp.status_code}): "
            f"{link_resp.text[:200]}"
        )
    return link_resp.json()


async def create_refund(
    *,
    stripe_account_id: str,
    charge_id: str,
    amount_cents: Optional[int] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Issue a refund against a charge on the connected account.

    Stripe-supported reasons: duplicate, fraudulent, requested_by_customer.
    Other values are passed as-is but Stripe will reject unknown ones.
    `amount_cents=None` → full refund."""
    form: Dict[str, Any] = {"charge": charge_id}
    if amount_cents is not None and amount_cents > 0:
        form["amount"] = int(amount_cents)
    if reason:
        form["reason"] = reason

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{STRIPE_API_BASE}/refunds",
            auth=(_secret_key(), ""),
            headers={"Stripe-Account": stripe_account_id},
            data=form,
        )
    if resp.status_code >= 400:
        logger.warning(
            f"create_refund failed: charge={charge_id} {resp.status_code} {resp.text[:300]}"
        )
        raise RuntimeError(
            f"stripe refund failed ({resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()
