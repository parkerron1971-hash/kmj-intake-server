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


def _checkout_session_form(
    *,
    line_items: List[Dict[str, Any]],
    success_url: str,
    cancel_url: str,
    source_type: str,
    source_id: str,
    customer_email: Optional[str] = None,
    application_fee_amount_cents: int = 0,
    currency: str = "usd",
    collect_shipping: bool = False,
    extra_metadata: Optional[Dict[str, Any]] = None,
    setup_future_usage: Optional[str] = None,
) -> Dict[str, Any]:
    """The Checkout-Session form. Pure so tests can pin the metadata +
    line-item contract without touching Stripe (same reason
    _invoice_link_form exists).

    Barber-money additions:
      extra_metadata     — merged onto BOTH the session metadata and the
                           payment_intent_data mirror (deposit_cents,
                           tip_cents, payment_kind, …). source_type /
                           source_id keys always win — extras can't
                           overwrite the routing contract.
      setup_future_usage — 'off_session' stores the card on the
                           connected account for the operator-triggered
                           no-show fee. Stripe auto-creates a Customer
                           on the session when this is set; the webhook
                           records session.customer onto the booking.
    """
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ValueError(
            f"source_type must be one of {sorted(ALLOWED_SOURCE_TYPES)}, got {source_type!r}"
        )
    if not source_id:
        raise ValueError("source_id required")
    if not line_items:
        raise ValueError("line_items required")

    form: Dict[str, Any] = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    # Extras first so the closed-enum routing keys below always win.
    for k, v in (extra_metadata or {}).items():
        if v is None:
            continue
        form[f"metadata[{k}]"] = v
        form[f"payment_intent_data[metadata][{k}]"] = v
    # Closed-enum metadata that webhook handlers + Charges tab parse.
    form["metadata[source_type]"] = source_type
    form["metadata[source_id]"] = source_id
    # Mirror on the underlying payment_intent so charge-level events
    # also carry the link (Stripe propagates checkout session
    # metadata to PI only when payment_intent_data is set).
    form["payment_intent_data[metadata][source_type]"] = source_type
    form["payment_intent_data[metadata][source_id]"] = source_id
    if customer_email:
        form["customer_email"] = customer_email
    if application_fee_amount_cents and application_fee_amount_cents > 0:
        form["payment_intent_data[application_fee_amount]"] = application_fee_amount_cents
    if collect_shipping:
        # Arc 27 — physical goods: Stripe collects the address on the
        # hosted page; the webhook copies it onto the order row.
        form["shipping_address_collection[allowed_countries][0]"] = "US"
    if setup_future_usage:
        form["payment_intent_data[setup_future_usage]"] = setup_future_usage

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
    return form


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
    extra_metadata: Optional[Dict[str, Any]] = None,
    setup_future_usage: Optional[str] = None,
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
      extra_metadata      — extra metadata merged onto session + PI
      setup_future_usage  — e.g. 'off_session' to store the card

    Returns the Stripe Checkout Session dict (key fields: id, url).
    Raises RuntimeError on Stripe error so the caller can translate
    to an HTTPException.
    """
    if not stripe_account_id:
        raise ValueError("stripe_account_id required")
    form = _checkout_session_form(
        line_items=line_items,
        success_url=success_url,
        cancel_url=cancel_url,
        source_type=source_type,
        source_id=source_id,
        customer_email=customer_email,
        application_fee_amount_cents=application_fee_amount_cents,
        currency=currency,
        collect_shipping=collect_shipping,
        extra_metadata=extra_metadata,
        setup_future_usage=setup_future_usage,
    )

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


def _booking_checkout_parts(
    *,
    service_name: str,
    amount_cents: int,
    deposit_cents: Optional[int] = None,
    tip_cents: int = 0,
    store_payment_method: bool = False,
) -> Dict[str, Any]:
    """Line items + metadata for a booking checkout. Pure (tested).

    Barber-money contract:
      * deposit_cents set → the FIRST line item charges the deposit
        ("Deposit — <service>"), metadata carries payment_kind='deposit'
        + deposit_cents + remainder_cents (+ service_cents so the full
        price survives on the payment object).
      * tip_cents > 0 → a separate "Tip" line item so the tip is visible
        in Stripe and separable in the books; metadata carries tip_cents.
        The tip ALWAYS rides in full — it is never split by the deposit.
      * store_payment_method → setup_future_usage='off_session' (card
        kept on file for the operator-triggered no-show fee; the
        CheckoutStep shows the disclosure line whenever a fee is
        configured).
    """
    amount_cents = int(amount_cents or 0)
    tip_cents = int(tip_cents or 0)
    if tip_cents < 0:
        raise ValueError("tip_cents must be >= 0")
    charge_cents = int(deposit_cents) if deposit_cents else amount_cents
    is_deposit = bool(deposit_cents) and charge_cents < amount_cents

    name = (service_name or "Booking").strip() or "Booking"
    line_items: List[Dict[str, Any]] = [{
        "name": f"Deposit — {name}" if is_deposit else name,
        "amount_cents": charge_cents,
        "quantity": 1,
    }]
    if tip_cents > 0:
        line_items.append({"name": "Tip", "amount_cents": tip_cents, "quantity": 1})

    metadata: Dict[str, Any] = {
        "payment_kind": "deposit" if is_deposit else "full",
        "service_cents": amount_cents,
    }
    if is_deposit:
        metadata["deposit_cents"] = charge_cents
        metadata["remainder_cents"] = amount_cents - charge_cents
    if tip_cents > 0:
        metadata["tip_cents"] = tip_cents
    if store_payment_method:
        metadata["store_payment_method"] = "1"

    return {
        "line_items": line_items,
        "extra_metadata": metadata,
        "setup_future_usage": "off_session" if store_payment_method else None,
    }


async def create_booking_checkout(
    *,
    stripe_account_id: str,
    booking_id: str,
    service_name: str,
    amount_cents: int,
    customer_email: Optional[str],
    success_url: str,
    cancel_url: str,
    deposit_cents: Optional[int] = None,
    tip_cents: int = 0,
    store_payment_method: bool = False,
) -> Dict[str, Any]:
    """Wrapper for the wizard CheckoutStep + the post-booking email.

    Pre-barber-money callers (booking_confirmation_emails Pay-Now link)
    pass only the original kwargs and get the original full-price
    session — the new params are keyword-optional by design."""
    parts = _booking_checkout_parts(
        service_name=service_name,
        amount_cents=amount_cents,
        deposit_cents=deposit_cents,
        tip_cents=tip_cents,
        store_payment_method=store_payment_method,
    )
    return await create_checkout_session(
        stripe_account_id=stripe_account_id,
        line_items=parts["line_items"],
        success_url=success_url,
        cancel_url=cancel_url,
        source_type="booking",
        source_id=booking_id,
        customer_email=customer_email,
        extra_metadata=parts["extra_metadata"],
        setup_future_usage=parts["setup_future_usage"],
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


async def charge_saved_payment_method(
    *,
    stripe_account_id: str,
    customer_id: str,
    amount_cents: int,
    description: str,
    statement_suffix: str = "NO-SHOW FEE",
    metadata: Optional[Dict[str, Any]] = None,
    payment_method_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    currency: str = "usd",
) -> Dict[str, Any]:
    """Off-session charge against a card stored on the connected account
    (the barber-money no-show fee; operator-triggered, never automatic).

    payment_method_id may be omitted — we then use the customer's first
    stored card (the one Checkout saved via setup_future_usage). Raises
    RuntimeError('no_stored_payment_method') when the customer has none,
    so the router can translate to a clean 409.

    idempotency_key rides Stripe's Idempotency-Key header: two racing
    charge attempts for the same booking create ONE PaymentIntent."""
    if not stripe_account_id:
        raise ValueError("stripe_account_id required")
    if not customer_id:
        raise ValueError("customer_id required")
    amount_cents = int(amount_cents or 0)
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")

    headers: Dict[str, str] = {"Stripe-Account": stripe_account_id}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        pm_id = payment_method_id
        if not pm_id:
            pm_resp = await client.get(
                f"{STRIPE_API_BASE}/payment_methods",
                auth=(_secret_key(), ""),
                headers=headers,
                params={"customer": customer_id, "type": "card", "limit": 1},
            )
            if pm_resp.status_code >= 400:
                raise RuntimeError(
                    f"stripe payment_methods list failed ({pm_resp.status_code}): "
                    f"{pm_resp.text[:200]}")
            pms = (pm_resp.json() or {}).get("data") or []
            if not pms:
                raise RuntimeError("no_stored_payment_method")
            pm_id = pms[0].get("id")

        form: Dict[str, Any] = {
            "amount": amount_cents,
            "currency": (currency or "usd").lower(),
            "customer": customer_id,
            "payment_method": pm_id,
            "off_session": "true",
            "confirm": "true",
            "description": description[:500],
            # Card-network statement line: "<account prefix>* NO-SHOW FEE"
            # so the guest recognizes the charge (max 22 chars, no
            # <>\\'"* characters).
            "statement_descriptor_suffix": statement_suffix[:22],
        }
        for k, v in (metadata or {}).items():
            if v is not None:
                form[f"metadata[{k}]"] = v

        pi_headers = dict(headers)
        if idempotency_key:
            pi_headers["Idempotency-Key"] = idempotency_key
        resp = await client.post(
            f"{STRIPE_API_BASE}/payment_intents",
            auth=(_secret_key(), ""),
            headers=pi_headers,
            data=form,
        )
    if resp.status_code >= 400:
        # Declines come back 402 with error.code=card_declined /
        # authentication_required — surface the code so the router can
        # tell the operator WHY instead of a generic failure.
        try:
            err = (resp.json() or {}).get("error") or {}
        except Exception:
            err = {}
        code = err.get("code") or err.get("decline_code") or "stripe_error"
        logger.warning(
            f"charge_saved_payment_method failed: customer={customer_id} "
            f"{resp.status_code} {resp.text[:300]}")
        raise RuntimeError(f"charge_failed:{code}")
    return resp.json()


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
