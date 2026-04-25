"""
stripe_proxy.py — server-side Stripe Payment Link generator

Creates one-shot Stripe Payment Links for a given amount using the
server's STRIPE_SECRET_KEY. Lets the client request payment links
without ever handling the Stripe key.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway alongside the other agent files.

2. In main.py (or whichever file mounts the FastAPI app):
       from stripe_proxy import router as stripe_router
       app.include_router(stripe_router)
   Register BEFORE public_site_router (the catch-all must stay last).

3. Env vars on Railway:
       STRIPE_SECRET_KEY  — required. https://dashboard.stripe.com/apikeys
                            Use a restricted key if possible
                            (write access on Prices + Payment Links only).

Endpoints:
  POST /stripe/create-payment-link
       body: { amount: number, currency?: str, description?: str, business_id?: str }
       → { url, id }
  GET  /stripe/status
       → { configured: bool }
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

STRIPE_API_BASE = "https://api.stripe.com/v1"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)

logger = logging.getLogger("stripe_proxy")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] stripe: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

router = APIRouter(tags=["stripe"])


class PaymentLinkRequest(BaseModel):
    amount: float
    currency: str = "usd"
    description: str = ""
    business_id: Optional[str] = ""


class PaymentLinkResponse(BaseModel):
    url: str
    id: str


async def _create_stripe_payment_link(
    amount: float,
    currency: str,
    description: str,
) -> Dict[str, Any]:
    """Create a one-off price + payment link. Returns {id, url}. Raises
    HTTPException on any Stripe error, propagating Stripe's actual status
    code + message so callers can surface it."""
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(500, "Stripe not configured on server — set STRIPE_SECRET_KEY")

    if amount <= 0:
        raise HTTPException(400, "amount must be > 0")

    unit_amount = int(round(amount * 100))  # cents
    currency_norm = (currency or "usd").lower()
    product_name = (description or "Invoice Payment").strip() or "Invoice Payment"

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        # Step 1 — create a one-off Price
        price_resp = await client.post(
            f"{STRIPE_API_BASE}/prices",
            auth=(key, ""),
            data={
                "unit_amount": str(unit_amount),
                "currency": currency_norm,
                "product_data[name]": product_name,
            },
        )
        if price_resp.status_code >= 400:
            body = price_resp.text[:500]
            logger.warning(f"Stripe price create failed: {price_resp.status_code} {body}")
            raise HTTPException(price_resp.status_code, f"Stripe price error: {body}")

        price_json = price_resp.json()
        price_id = price_json.get("id")
        if not price_id:
            raise HTTPException(502, "Stripe returned no price id")

        # Step 2 — wrap it in a Payment Link
        link_resp = await client.post(
            f"{STRIPE_API_BASE}/payment_links",
            auth=(key, ""),
            data={
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
            },
        )
        if link_resp.status_code >= 400:
            body = link_resp.text[:500]
            logger.warning(f"Stripe payment-link create failed: {link_resp.status_code} {body}")
            raise HTTPException(link_resp.status_code, f"Stripe link error: {body}")

        link_json = link_resp.json()
        return {"url": link_json.get("url", ""), "id": link_json.get("id", "")}


@router.post("/stripe/create-payment-link", response_model=PaymentLinkResponse)
async def create_payment_link(req: PaymentLinkRequest):
    data = await _create_stripe_payment_link(
        amount=req.amount,
        currency=req.currency,
        description=req.description,
    )
    logger.info(
        f"stripe link ok business={req.business_id or '-'} "
        f"amount={req.amount} {req.currency} id={data.get('id')}"
    )
    return PaymentLinkResponse(url=data["url"], id=data["id"])


@router.get("/stripe/status")
async def stripe_status():
    return {"configured": bool(os.environ.get("STRIPE_SECRET_KEY"))}


# ═══════════════════════════════════════════════════════════════════════
# MULTI-PROVIDER OAUTH PLACEHOLDERS (Stripe Connect / Square / PayPal)
# ═══════════════════════════════════════════════════════════════════════
#
# These endpoints are placeholders for the upcoming "one-click Connect"
# flow that will replace today's manual paste-a-payment-link experience.
# They return a not_implemented payload so frontends can light up the
# Connect button and the system can surface a friendly "coming soon"
# message instead of a 404.
#
# When real OAuth is wired:
#   /payments/connect/{provider}     — kicks off the OAuth dance and 302s
#                                       the practitioner to the provider's
#                                       authorization page.
#   /payments/callback/{provider}    — receives the auth code, exchanges
#                                       for an access token, persists onto
#                                       businesses.settings.payment_providers.
#   /payments/providers/{biz_id}     — returns the saved provider config
#                                       for a business (post-migration).

SUPPORTED_PROVIDERS = ("stripe", "square", "paypal")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://brqjgbpzackdihgjsorf.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")


def _validate_provider(provider: str) -> str:
    p = (provider or "").strip().lower()
    if p not in SUPPORTED_PROVIDERS:
        raise HTTPException(400, f"Unsupported provider '{provider}'. Try one of: {', '.join(SUPPORTED_PROVIDERS)}")
    return p


@router.get("/payments/connect/{provider}")
async def payments_connect(provider: str, business_id: Optional[str] = None):
    """Kick off OAuth for a provider. Today: returns not_implemented."""
    p = _validate_provider(provider)
    return {
        "status": "not_implemented",
        "provider": p,
        "business_id": business_id or None,
        "message": f"{p.capitalize()} Connect is coming soon. For now, paste your payment link in BUILD → Integrations → Payment Providers.",
    }


@router.get("/payments/callback/{provider}")
async def payments_callback(provider: str, code: Optional[str] = None, state: Optional[str] = None):
    """OAuth redirect target. Today: returns not_implemented."""
    p = _validate_provider(provider)
    return {
        "status": "not_implemented",
        "provider": p,
        "received_code": bool(code),
        "received_state": bool(state),
        "message": f"{p.capitalize()} OAuth callback is coming soon.",
    }


@router.get("/payments/providers/{business_id}")
async def payments_providers(business_id: str):
    """Read the saved payment_providers config for a business.

    Returns a normalized record showing which providers are enabled and
    whether each has a link configured. Used by clients that want to
    know what to render before fetching the full business settings.
    Falls back to legacy settings.payments.stripe_link if the new shape
    isn't present yet.
    """
    if not SUPABASE_KEY:
        raise HTTPException(500, "Supabase key not configured on server")
    if not business_id or len(business_id) < 8:
        raise HTTPException(400, "business_id is required")

    url = f"{SUPABASE_URL}/rest/v1/businesses?id=eq.{business_id}&select=settings"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(url, headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        })
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, f"Supabase error: {resp.text[:200]}")
        rows = resp.json() or []
        if not rows:
            raise HTTPException(404, "Business not found")

    settings = (rows[0].get("settings") or {}) if isinstance(rows[0], dict) else {}
    incoming = settings.get("payment_providers") or {}
    legacy_stripe = (settings.get("payments") or {}).get("stripe_link") or ""

    out: Dict[str, Dict[str, Any]] = {}
    for pid in SUPPORTED_PROVIDERS:
        slot = incoming.get(pid) or {}
        link = (slot.get("manual_link") or "").strip()
        if pid == "stripe" and not link and legacy_stripe:
            link = legacy_stripe
        out[pid] = {
            "enabled": bool(slot.get("enabled")) or (pid == "stripe" and bool(legacy_stripe) and not incoming),
            "type": slot.get("type") or "manual",
            "has_link": bool(link),
            "label": slot.get("label") or "",
            "connect_account_id": slot.get("connect_account_id"),
            "oauth_merchant_id": slot.get("oauth_merchant_id"),
        }

    return {
        "business_id": business_id,
        "providers": out,
        "any_enabled": any(v["enabled"] and v["has_link"] for v in out.values()),
    }
