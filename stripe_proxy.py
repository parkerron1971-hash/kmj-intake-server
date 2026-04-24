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
