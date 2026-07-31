"""
stripe_payments_router.py — Phase D.4 PR 3 endpoints.

Practitioner + customer-initiated payment surfaces:

  POST /payments/booking-checkout   anon-rate-limited
       Customer's "Pay now" path from the wizard CheckoutStep.
       Body: { booking_id, success_url?, cancel_url? }
       Returns: { url, session_id } so the wizard can redirect.

  POST /payments/invoice-checkout   authed, seat-role gated (member+)
       Practitioner's "send this invoice with a real pay link" path.
       Body: { invoice_id, business_id?, force? }
       Returns: { url, id } — a per-invoice Payment Link on the
       business's connected account, metadata-tagged so the Connect
       webhook marks exactly this invoice paid (no amount matching).
       409 when the business has no connected payment account.

  POST /payments/charges/{charge_id}/refund    owner-gated
       Body: { amount_cents?, reason? }  amount=None means full refund

  GET  /payments/charges/{charge_id}/booking-url    owner-gated (optional)
       Resolve a Solutionist booking URL from a Stripe charge's metadata
       — used by the Charges-tab source-link to deep-link back.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import payments_core
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("stripe_payments_router")

router = APIRouter(prefix="/payments", tags=["payments"])


# ─── Booking pre-pay (customer-initiated, anon) ──────────────────────


class BookingCheckoutBody(BaseModel):
    booking_id: str
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


@router.post("/booking-checkout")
async def booking_checkout(
    body: BookingCheckoutBody,
    request: Request,
) -> Dict[str, Any]:
    """Create a Stripe Checkout Session for a booking.

    Anonymous: customer is paying from the wizard or from the email
    Pay Now button without a Solutionist account. We look up the
    booking + business + offering server-side to derive the amount —
    the caller can't influence it. Rate-limiting handled by the
    existing wizard rate-limit middleware.
    """
    booking_id = (body.booking_id or "").strip()
    if not booking_id:
        raise HTTPException(400, "booking_id required")

    # Load the booking + denormalized service info.
    rows = sb_clients.sb_get_as_service(
        f"/module_entries?id=eq.{booking_id}"
        f"&select=id,business_id,data,paid_at,status&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "booking not found")
    entry = rows[0]
    if entry.get("paid_at"):
        raise HTTPException(409, "booking already paid")
    if entry.get("status") != "active":
        raise HTTPException(409, "booking is not active")

    business_id = entry["business_id"]
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        f"&select=id,name,stripe_account_id,settings&limit=1"
    ) or []
    # Adapter seam: provider selection + connectivity come from
    # payments_core — this call site no longer knows it's Stripe.
    biz = biz_rows[0] if biz_rows else {}
    provider = payments_core.provider_for(biz)
    if not biz or not provider.is_connected(biz):
        raise HTTPException(409, "this business doesn't accept online payments")

    data = entry.get("data") or {}
    price = data.get("price_at_booking") or data.get("price")
    service_name = (
        data.get("service_name_at_booking")
        or data.get("service_name")
        or "Booking"
    )
    if price is None:
        raise HTTPException(409, "booking has no price — practitioner must set one")
    try:
        amount_cents = int(round(float(price) * 100))
    except Exception:
        raise HTTPException(409, "booking price is malformed")
    if amount_cents <= 0:
        raise HTTPException(409, "booking price is zero or negative")

    customer_email = data.get("customer_email") or data.get("email")

    # success/cancel URLs default to the hosted booking page with
    # query params the wizard can react to.
    public_default = _public_booking_url(business_id) or "https://mysolutionist.app/"
    success_url = body.success_url or f"{public_default}?paid=1"
    cancel_url = body.cancel_url or f"{public_default}?paid=0"

    try:
        session = await provider.create_booking_checkout(
            biz,
            booking_id=booking_id,
            service_name=service_name,
            amount_cents=amount_cents,
            customer_email=customer_email,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except RuntimeError as e:
        logger.warning(f"booking checkout failed: biz={business_id} booking={booking_id} err={e}")
        raise HTTPException(502, "couldn't create payment session — please try again")

    return {
        "ok": True,
        "url": session.get("url"),
        "session_id": session.get("id"),
    }


def _public_booking_url(business_id: str) -> Optional[str]:
    """Resolve the hosted booking URL for redirect targets. Best-effort."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/business_sites?business_id=eq.{business_id}&select=slug&limit=1"
        ) or []
        slug = rows[0].get("slug") if rows else None
        if not slug:
            return None
        return f"https://{slug}.mysolutionist.app/book"
    except Exception:
        return None


# ─── Invoice pay link (practitioner-initiated, authed) ───────────────


class InvoiceCheckoutBody(BaseModel):
    invoice_id: str
    # Optional cross-check: when the caller names a business, it must be
    # the invoice's business (mismatches read as not-found, no leaking).
    business_id: Optional[str] = None
    # Regenerate even when a per-invoice link already exists.
    force: bool = False


@router.post("/invoice-checkout")
async def invoice_checkout(
    body: InvoiceCheckoutBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Create (or reuse) a per-invoice pay link on the business's
    connected account.

    This replaces the pasted-static-link pattern for Connect businesses:
    the link carries {source_type: 'invoice', source_id} metadata, so
    when the customer pays, the Connect webhook flips exactly this
    invoice — the legacy webhook's match-by-amount fallback (which
    cross-matches two same-total invoices) never has to run.

    Seat-role gated at member+ (the same rank that can write invoices),
    resolved through the shared business_users role ladder."""
    invoice_id = (body.invoice_id or "").strip()
    if not invoice_id:
        raise HTTPException(400, "invoice_id required")

    rows = sb_clients.sb_get_as_service(
        f"/invoices?id=eq.{invoice_id}"
        f"&select=id,business_id,contact_id,invoice_number,total,currency,"
        f"status,stripe_payment_url&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "invoice not found")
    inv = rows[0]
    business_id = str(inv.get("business_id") or "")
    if body.business_id and str(body.business_id) != business_id:
        raise HTTPException(404, "invoice not found")

    from business_users_router import require_role
    require_role(business_id, str(user.id), "member")

    status = (inv.get("status") or "").lower()
    if status == "paid":
        raise HTTPException(409, "invoice is already paid")
    if status == "cancelled":
        raise HTTPException(409, "invoice is cancelled")

    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        f"&select=id,name,owner_id,stripe_account_id,settings&limit=1"
    ) or []
    biz = biz_rows[0] if biz_rows else {}
    provider = payments_core.provider_for(biz)
    if not biz or not provider.is_connected(biz):
        raise HTTPException(
            409, "this business has no connected payment account — "
                 "connect Stripe in OPERATE → Payments first")

    try:
        amount_cents = int(round(float(inv.get("total") or 0) * 100))
    except Exception:
        raise HTTPException(409, "invoice total is malformed")
    if amount_cents <= 0:
        raise HTTPException(409, "invoice total is zero or negative")

    # Idempotency: an invoice that already carries a link DIFFERENT from
    # the business's pasted static link already has its own pay link —
    # hand it back instead of minting a duplicate Stripe object.
    static_link = str(
        (((biz.get("settings") or {}).get("payments") or {}).get("stripe_link")) or ""
    ).strip()
    existing = str(inv.get("stripe_payment_url") or "").strip()
    if existing and existing != static_link and not body.force:
        return {"ok": True, "url": existing, "id": None, "reused": True}

    try:
        link = await provider.create_invoice_checkout(
            biz,
            invoice_id=invoice_id,
            invoice_number=str(inv.get("invoice_number") or ""),
            amount_cents=amount_cents,
            business_id=business_id,
            currency=str(inv.get("currency") or "usd").lower(),
        )
    except RuntimeError as e:
        logger.warning(
            f"invoice checkout failed: biz={business_id} invoice={invoice_id} err={e}")
        raise HTTPException(502, "couldn't create the payment link — please try again")

    url = (link or {}).get("url")
    if not url:
        raise HTTPException(502, "payment provider returned no link URL")

    # Persist so the emailed invoice + the Payment Options row use the
    # per-invoice link, and so GL routes the payment through 1150
    # Stripe Clearing (a Stripe-linked invoice is not direct cash).
    sb_clients.sb_patch_as_service(
        f"/invoices?id=eq.{invoice_id}",
        {"stripe_payment_url": url},
    )
    logger.info(
        f"invoice pay link ok: biz={business_id[:8]} invoice={invoice_id[:8]} "
        f"amount_cents={amount_cents} link={link.get('id')}")
    return {"ok": True, "url": url, "id": link.get("id"), "reused": False}


# ─── Refund (practitioner-initiated) ─────────────────────────────────


class RefundBody(BaseModel):
    business_id: str   # required so we can owner-gate
    amount_cents: Optional[int] = None
    reason: Optional[str] = None


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        f"&select=id,owner_id,stripe_account_id,settings&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    if not payments_core.provider_for(rows[0]).is_connected(rows[0]):
        raise HTTPException(409, "payment provider not connected")
    return rows[0]


@router.post("/charges/{charge_id}/refund")
async def refund_charge(
    charge_id: str,
    body: RefundBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    biz = _require_owner(body.business_id, user)
    try:
        refund = await payments_core.provider_for(biz).create_refund(
            biz,
            charge_id=charge_id,
            amount_cents=body.amount_cents,
            reason=body.reason,
        )
    except RuntimeError as e:
        logger.warning(f"refund failed: charge={charge_id} err={e}")
        raise HTTPException(502, f"refund failed: {e!s}")
    return {
        "ok": True,
        "refund": {
            "id": refund.get("id"),
            "amount": refund.get("amount"),
            "currency": refund.get("currency"),
            "status": refund.get("status"),
            "reason": refund.get("reason"),
        },
    }
