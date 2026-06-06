"""
stripe_data_proxy.py — Phase D.4 PR 2.

Read-only proxy for the practitioner-facing Charges / Payouts /
Customers tabs. Every request hits Stripe with:
  - Auth: platform secret key (basic-auth username, empty password)
  - Stripe-Account: <connected account id> header
…so the data returned is scoped to ONE practitioner. The practitioner's
connected key/secret is never required and never leaves Stripe.

Endpoints (all owner-gated):
  GET /payments/charges?biz=...    list charges
  GET /payments/payouts?biz=...    list payouts
  GET /payments/customers?biz=...  list customers
  GET /payments/customers/{customer_id}/charges?biz=...
                                   per-customer charge history

Pagination follows Stripe's cursor model: caller passes `starting_after`
from the previous page's last id; response carries `has_more` + the
last id so the frontend can request the next page.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("stripe_data_proxy")

router = APIRouter(prefix="/payments", tags=["payments"])

STRIPE_API_BASE = "https://api.stripe.com/v1"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)

# Stripe caps `limit` at 100; we default to 25 because it fills a
# practitioner screen without overwhelming + keeps the round-trip
# under a half-second for accounts with thousands of charges.
DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def _secret_key() -> str:
    k = os.environ.get("STRIPE_SECRET_KEY") or ""
    if not k:
        raise HTTPException(503, "payments not configured")
    return k


def _require_owner_with_acct(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    """Owner gate + ensure the business has a connected Stripe account.
    Returns the business row so callers reuse the stripe_account_id."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,owner_id,stripe_account_id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    biz = rows[0]
    if str(biz.get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    if not biz.get("stripe_account_id"):
        raise HTTPException(409, "stripe account not connected")
    return biz


async def _stripe_get(
    path: str,
    *,
    stripe_account_id: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Thin GET against Stripe with Stripe-Account header. Raises
    HTTPException with the upstream status on Stripe errors so the
    frontend's existing j.detail surface treats them sanely."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(
            f"{STRIPE_API_BASE}{path}",
            auth=(_secret_key(), ""),
            headers={"Stripe-Account": stripe_account_id},
            params={k: v for k, v in (params or {}).items() if v is not None and v != ""},
        )
    if resp.status_code >= 400:
        logger.warning(
            f"stripe GET {path} (acct={stripe_account_id}) -> "
            f"{resp.status_code} {resp.text[:300]}"
        )
        # Map Stripe's body to our detail field for frontend display.
        try:
            err = resp.json().get("error") or {}
        except Exception:
            err = {}
        msg = err.get("message") or f"stripe error {resp.status_code}"
        raise HTTPException(status_code=resp.status_code, detail=msg)
    return resp.json()


def _clamp_limit(limit: Optional[int]) -> int:
    if not limit or limit <= 0:
        return DEFAULT_LIMIT
    return min(int(limit), MAX_LIMIT)


def _built_in_pagination(
    stripe_response: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract cursor + has_more from a Stripe list response."""
    data = stripe_response.get("data") or []
    has_more = bool(stripe_response.get("has_more"))
    last_id = data[-1].get("id") if data else None
    return {
        "data": data,
        "has_more": has_more,
        "next_starting_after": last_id if has_more else None,
    }


# ─── Charges ─────────────────────────────────────────────────────────


@router.get("/charges")
async def list_charges(
    biz: str,
    limit: Optional[int] = None,
    starting_after: Optional[str] = None,
    created_gte: Optional[int] = None,  # unix seconds
    created_lte: Optional[int] = None,
    customer: Optional[str] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """List charges on the connected account.

    Stripe filter shape: created[gte] / created[lte] / customer.
    Query-string carries them as flat ints + the cursor."""
    biz_row = _require_owner_with_acct(biz, user)

    params: Dict[str, Any] = {
        "limit": _clamp_limit(limit),
    }
    if starting_after:
        params["starting_after"] = starting_after
    if customer:
        params["customer"] = customer
    if created_gte is not None:
        params["created[gte]"] = created_gte
    if created_lte is not None:
        params["created[lte]"] = created_lte

    stripe_resp = await _stripe_get(
        "/charges",
        stripe_account_id=biz_row["stripe_account_id"],
        params=params,
    )
    return {
        "ok": True,
        **_built_in_pagination(stripe_resp),
    }


# ─── Payouts ─────────────────────────────────────────────────────────


@router.get("/payouts")
async def list_payouts(
    biz: str,
    limit: Optional[int] = None,
    starting_after: Optional[str] = None,
    arrival_date_gte: Optional[int] = None,
    arrival_date_lte: Optional[int] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    biz_row = _require_owner_with_acct(biz, user)

    params: Dict[str, Any] = {
        "limit": _clamp_limit(limit),
    }
    if starting_after:
        params["starting_after"] = starting_after
    if arrival_date_gte is not None:
        params["arrival_date[gte]"] = arrival_date_gte
    if arrival_date_lte is not None:
        params["arrival_date[lte]"] = arrival_date_lte

    stripe_resp = await _stripe_get(
        "/payouts",
        stripe_account_id=biz_row["stripe_account_id"],
        params=params,
    )
    return {
        "ok": True,
        **_built_in_pagination(stripe_resp),
    }


# ─── Customers ───────────────────────────────────────────────────────


@router.get("/customers")
async def list_customers(
    biz: str,
    limit: Optional[int] = None,
    starting_after: Optional[str] = None,
    email: Optional[str] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """List customers on the connected account. Optional `email`
    filter delegates to Stripe's customer search index when provided."""
    biz_row = _require_owner_with_acct(biz, user)

    params: Dict[str, Any] = {
        "limit": _clamp_limit(limit),
    }
    if starting_after:
        params["starting_after"] = starting_after
    if email:
        params["email"] = email

    stripe_resp = await _stripe_get(
        "/customers",
        stripe_account_id=biz_row["stripe_account_id"],
        params=params,
    )
    return {
        "ok": True,
        **_built_in_pagination(stripe_resp),
    }


# ─── Refunds (PR 3d) ─────────────────────────────────────────────────


@router.get("/refunds")
async def list_refunds(
    biz: str,
    limit: Optional[int] = None,
    starting_after: Optional[str] = None,
    created_gte: Optional[int] = None,  # unix seconds
    created_lte: Optional[int] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """List refunds on the connected account.

    Phase D.4 PR 3d — populates the RefundsTab in PaymentsPanel.
    Expands the linked `charge` so the frontend renders source
    metadata (Invoice #X / Booking #X) + customer info inline
    without a second round-trip per row.

    Filter shape mirrors /charges: created[gte] / created[lte] +
    cursor pagination. Stripe caps limit at 100; we clamp to
    DEFAULT_LIMIT=25 to match the other tabs.
    """
    biz_row = _require_owner_with_acct(biz, user)

    params: Dict[str, Any] = {
        "limit": _clamp_limit(limit),
        # Expand the underlying charge so we get billing_details +
        # metadata in one round trip. Stripe accepts repeated keys
        # via "expand[]" syntax which httpx serializes from a list.
        "expand[]": "data.charge",
    }
    if starting_after:
        params["starting_after"] = starting_after
    if created_gte is not None:
        params["created[gte]"] = created_gte
    if created_lte is not None:
        params["created[lte]"] = created_lte

    stripe_resp = await _stripe_get(
        "/refunds",
        stripe_account_id=biz_row["stripe_account_id"],
        params=params,
    )
    return {
        "ok": True,
        **_built_in_pagination(stripe_resp),
    }


@router.get("/customers/{customer_id}/charges")
async def list_customer_charges(
    customer_id: str,
    biz: str,
    limit: Optional[int] = None,
    starting_after: Optional[str] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Per-customer charge history. Same shape as /charges but
    pre-filtered by customer for the customer-detail panel."""
    biz_row = _require_owner_with_acct(biz, user)

    params: Dict[str, Any] = {
        "customer": customer_id,
        "limit": _clamp_limit(limit),
    }
    if starting_after:
        params["starting_after"] = starting_after

    stripe_resp = await _stripe_get(
        "/charges",
        stripe_account_id=biz_row["stripe_account_id"],
        params=params,
    )
    return {
        "ok": True,
        **_built_in_pagination(stripe_resp),
    }


# ─── Health (debug aid, no auth) ─────────────────────────────────────


@router.get("/health")
def payments_health() -> Dict[str, Any]:
    """Tiny status probe so the frontend can preflight a 'configured'
    badge without a real auth round-trip. Reports presence of the
    server-side env vars only — never the values."""
    return {
        "ok": True,
        "configured": bool(os.environ.get("STRIPE_SECRET_KEY")),
        "connect_configured": bool(os.environ.get("STRIPE_CONNECT_CLIENT_ID")),
        "webhook_configured": bool(os.environ.get("STRIPE_WEBHOOK_SECRET")),
        "live_mode": (os.environ.get("STRIPE_SECRET_KEY") or "").startswith("sk_live_"),
        "timestamp": int(time.time()),
    }
