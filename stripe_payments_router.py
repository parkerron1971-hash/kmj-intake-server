"""
stripe_payments_router.py — Phase D.4 PR 3 endpoints.

Practitioner + customer-initiated payment surfaces:

  POST /payments/booking-checkout   anon-rate-limited
       Customer's "Pay now" path from the wizard CheckoutStep.
       Body: { booking_id, success_url?, cancel_url? }
       Returns: { url, session_id } so the wizard can redirect.

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
