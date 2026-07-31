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

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Depends
from auth_supabase import require_user, AuthedUser
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
    *,
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    business_id: Optional[str] = None,
    connected_account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a one-off price + payment link. Returns {id, url}. Raises
    HTTPException on any Stripe error, propagating Stripe's actual status
    code + message so callers can surface it.

    Phase D.4 PR 3a — when source_type + source_id are passed, the
    Payment Link records them as metadata AND propagates them to the
    underlying PaymentIntent (via payment_intent_data[metadata]) so the
    resulting charge carries the unified-source pattern. The Charges
    tab uses this to render "from Invoice #INV-2026-001" lineage and
    webhook handlers use it to mark the originating row paid.

    Phase D.4 PR 3c — Universal Connect routing. When
    connected_account_id is supplied, the Price + Payment Link are
    BOTH created on the connected account (via Stripe's Stripe-Account
    header), so the resulting charge flows to the practitioner's
    connected balance — not the platform. This is the load-bearing
    change that makes the practitioner's OPERATE → Payments → Charges
    tab show the resulting paid invoices. business_id rides along in
    metadata so webhook handlers can resolve back to the originating
    Solutionist row even when querying cross-account.
    """
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(500, "Stripe not configured on server — set STRIPE_SECRET_KEY")

    if amount <= 0:
        raise HTTPException(400, "amount must be > 0")

    unit_amount = int(round(amount * 100))  # cents
    currency_norm = (currency or "usd").lower()
    product_name = (description or "Invoice Payment").strip() or "Invoice Payment"

    # PR 3c — when connected_account_id is set, every Stripe API call
    # below is scoped to the connected account via the Stripe-Account
    # header. Equivalent to the Stripe Python SDK's
    # stripe.<Resource>.create(..., stripe_account=acct_...).
    headers: Dict[str, str] = {}
    if connected_account_id:
        headers["Stripe-Account"] = connected_account_id

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        # Step 1 — create a one-off Price
        price_resp = await client.post(
            f"{STRIPE_API_BASE}/prices",
            auth=(key, ""),
            headers=headers,
            data={
                "unit_amount": str(unit_amount),
                "currency": currency_norm,
                "product_data[name]": product_name,
            },
        )
        if price_resp.status_code >= 400:
            body = price_resp.text[:500]
            logger.warning(
                f"Stripe price create failed: {price_resp.status_code} {body} "
                f"(connected_account={connected_account_id or 'PLATFORM'})"
            )
            raise HTTPException(price_resp.status_code, f"Stripe price error: {body}")

        price_json = price_resp.json()
        price_id = price_json.get("id")
        if not price_id:
            raise HTTPException(502, "Stripe returned no price id")

        # Step 2 — wrap it in a Payment Link.
        link_form: Dict[str, str] = {
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
        }
        # PR 3a unified-source metadata. Propagated to PaymentIntent so
        # charges + webhooks (which only see PI metadata) can resolve
        # back to the originating Solutionist row.
        if source_type and source_id:
            link_form["metadata[source_type]"] = source_type
            link_form["metadata[source_id]"] = source_id
            link_form["payment_intent_data[metadata][source_type]"] = source_type
            link_form["payment_intent_data[metadata][source_id]"] = source_id
        # PR 3c — business_id metadata for cross-account observability.
        # Webhook handlers that arrive on the platform's webhook
        # endpoint (Stripe routes ALL events to ONE configured URL,
        # platform OR connected) use this to resolve the Solutionist
        # business when the connected account's id matches multiple
        # rows or when we need to authorize cross-tenant access.
        if business_id:
            link_form["metadata[business_id]"] = business_id
            link_form["payment_intent_data[metadata][business_id]"] = business_id

        link_resp = await client.post(
            f"{STRIPE_API_BASE}/payment_links",
            auth=(key, ""),
            headers=headers,
            data=link_form,
        )
        if link_resp.status_code >= 400:
            body = link_resp.text[:500]
            logger.warning(
                f"Stripe payment-link create failed: {link_resp.status_code} {body} "
                f"(connected_account={connected_account_id or 'PLATFORM'})"
            )
            raise HTTPException(link_resp.status_code, f"Stripe link error: {body}")

        link_json = link_resp.json()
        return {"url": link_json.get("url", ""), "id": link_json.get("id", "")}


@router.post("/stripe/create-payment-link", response_model=PaymentLinkResponse)
async def create_payment_link(req: PaymentLinkRequest, user: AuthedUser = Depends(require_user)):
    """Public endpoint for ad-hoc Payment Link creation.

    Phase D.4 PR 3c — when business_id is supplied AND that business has
    a connected Stripe account, the Payment Link is created on the
    connected account so funds + the resulting charge land on the
    practitioner's books. Without business_id or without a Connect
    account, the link is created on the platform account (legacy path
    — kept for backward compatibility; do NOT use for new flows).
    """
    connected_account_id: Optional[str] = None
    if req.business_id:
        try:
            import sb_clients
            rows = sb_clients.sb_get_as_service(
                f"/businesses?id=eq.{req.business_id}&select=stripe_account_id&limit=1"
            ) or []
            if rows:
                acct = (rows[0].get("stripe_account_id") or "").strip()
                connected_account_id = acct or None
        except Exception as e:
            logger.warning(f"stripe link: business lookup failed: {e}")

    data = await _create_stripe_payment_link(
        amount=req.amount,
        currency=req.currency,
        description=req.description,
        business_id=req.business_id or None,
        connected_account_id=connected_account_id,
    )
    logger.info(
        f"stripe link ok business={req.business_id or '-'} "
        f"amount={req.amount} {req.currency} id={data.get('id')} "
        f"account={connected_account_id or 'PLATFORM'}"
    )
    return PaymentLinkResponse(url=data["url"], id=data["id"])


class ProductPaymentLinkRequest(BaseModel):
    business_id: str
    product_id: str
    # Optional override - normally read from the product row
    force_regenerate: bool = False


@router.post("/stripe/product-link")
async def create_product_payment_link(req: ProductPaymentLinkRequest, user: AuthedUser = Depends(require_user)):
    """Create a Stripe payment link for a product and persist the URL
    back onto the products row.

    Idempotent: if the product already has a stripe_payment_url and the
    caller didn't pass force_regenerate=true, returns the existing URL.

    The product must have type in (digital, physical, package) - services
    route to the booking page, so they don't get a Stripe link from this
    endpoint. Pricing types 'free' and 'custom' return 400 (no fixed
    price to charge against).
    """
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(500, "Stripe not configured on server - set STRIPE_SECRET_KEY")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        # Look up the product, scoped by business_id so a leaked id
        # can't be exploited cross-tenant.
        prod_rows = await _sb_get(
            client,
            f"/products?id=eq.{req.product_id}&business_id=eq.{req.business_id}"
            f"&select=*&limit=1",
        )
        if not prod_rows:
            raise HTTPException(404, "Product not found for this business")
        product = prod_rows[0]

        existing_url = (product.get("stripe_payment_url") or "").strip()
        if existing_url and not req.force_regenerate:
            return {
                "url": existing_url,
                "id": (product.get("metadata") or {}).get("stripe_link_id") or "",
                "regenerated": False,
            }

        try:
            price = float(product.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            raise HTTPException(400, "Product has no fixed price - cannot create a payment link")

        pricing_type = (product.get("pricing_type") or "fixed").lower()
        if pricing_type in ("free", "custom"):
            raise HTTPException(400, f"Product pricing_type='{pricing_type}' has no payable amount")

        ptype = (product.get("type") or "service").lower()
        if ptype == "service":
            raise HTTPException(
                400,
                "Services use the booking flow - generate the Stripe link via /stripe/create-payment-link "
                "during booking confirmation, not as a standalone product link",
            )

        currency = (product.get("currency") or "USD")
        description = product.get("name") or "Product"

        # Route payouts to the practitioner's connected account when one
        # exists (mirrors the auto-link path in handle_create_product).
        connected_account_id = None
        biz_rows = await _sb_get(
            client,
            f"/businesses?id=eq.{req.business_id}&select=stripe_account_id&limit=1",
        )
        if biz_rows:
            connected_account_id = (biz_rows[0].get("stripe_account_id") or "").strip() or None

        # Build the payment link via the existing helper. Source metadata
        # is LOAD-BEARING (Academy Phase 3): the webhook identifies the
        # purchased product from metadata[source_id] — without it,
        # checkout.session.completed hits the no-source guard and buyer
        # auto-enrollment (course-linked products) never fires.
        link = await _create_stripe_payment_link(
            amount=price,
            currency=currency,
            description=description,
            source_type="product",
            source_id=str(req.product_id),
            business_id=str(req.business_id),
            connected_account_id=connected_account_id,
        )
        url = link.get("url") or ""
        link_id = link.get("id") or ""
        if not url:
            raise HTTPException(502, "Stripe returned no payment link URL")

        # Persist on the product. Merge metadata so we keep any existing
        # paypal/shopify/square URLs the practitioner pasted in.
        existing_meta = product.get("metadata") or {}
        if not isinstance(existing_meta, dict):
            existing_meta = {}
        new_meta = {
            **existing_meta,
            "stripe_link_id": link_id,
        }
        await _sb_patch(
            client,
            f"/products?id=eq.{req.product_id}",
            {"stripe_payment_url": url, "metadata": new_meta},
        )

        logger.info(
            f"stripe product-link ok business={req.business_id} product={req.product_id} "
            f"amount={price} {currency} id={link_id}"
        )
        return {"url": url, "id": link_id, "regenerated": True}


@router.get("/stripe/status")
async def stripe_status():
    return {"configured": bool(os.environ.get("STRIPE_SECRET_KEY"))}


# ═══════════════════════════════════════════════════════════════════════
# WEBHOOK — checkout.session.completed
# ═══════════════════════════════════════════════════════════════════════
#
# Stripe POSTs here when a Payment Link checkout succeeds. We:
#   1. Match the session back to one of our invoices (by payment_link
#      ID, then by amount + recently-sent invoices).
#   2. Flip the invoice to status="paid" with paid_at + payment_method.
#   3. Log an `invoice_paid_auto` event on the contact's timeline.
#   4. Post a chief_notification surfacing the payment.
#   5. Bump the contact's health to 100.
#
# Always returns 200 — Stripe retries on non-2xx responses.
#
# Stripe dashboard:
#   stripe.com -> Developers -> Webhooks -> Add endpoint
#   URL:    https://<this-host>/stripe/webhook
#   Events: checkout.session.completed

SUPABASE_URL_DEFAULT = "https://brqjgbpzackdihgjsorf.supabase.co"


def _sb_headers() -> Dict[str, str]:
    # Beta-readiness audit (RLS tighten): these paths write /invoices from
    # the Stripe webhook (no user JWT) and MUST use the service role — the
    # canonical env name is SUPABASE_SERVICE_ROLE_KEY (the whole rest of
    # the codebase uses it; this file was the lone SUPABASE_SERVICE_KEY
    # holdout with an anon fallback that would break once the permissive
    # invoices policy is dropped).
    key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
           or os.environ.get("SUPABASE_SERVICE_KEY", ""))
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", SUPABASE_URL_DEFAULT).rstrip("/")


async def _sb_get(client: httpx.AsyncClient, path: str) -> Optional[Any]:
    url = f"{_sb_url()}/rest/v1{path}"
    try:
        r = await client.get(url, headers=_sb_headers(), timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"supabase GET {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"supabase GET {path} failed: {e}")
        return None


async def _sb_post(client: httpx.AsyncClient, path: str, body: Dict[str, Any]) -> Optional[Any]:
    url = f"{_sb_url()}/rest/v1{path}"
    try:
        r = await client.post(url, headers=_sb_headers(), content=json.dumps(body), timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"supabase POST {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"supabase POST {path} failed: {e}")
        return None


async def _sb_patch(client: httpx.AsyncClient, path: str, body: Dict[str, Any]) -> None:
    url = f"{_sb_url()}/rest/v1{path}"
    try:
        await client.patch(url, headers=_sb_headers(), content=json.dumps(body), timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        logger.warning(f"supabase PATCH {path} failed: {e}")


async def _match_digital_product_for_payment(
    client: httpx.AsyncClient,
    payment_link_id: str,
    amount: float,
) -> Optional[Dict[str, Any]]:
    """Find an auto-deliverable digital product whose stripe_payment_url
    contains the payment link id (or whose price matches the captured
    amount). Returns the first hit or None.
    """
    if payment_link_id:
        rows = await _sb_get(
            client,
            f"/products?stripe_payment_url=ilike.*{payment_link_id}*"
            f"&auto_deliver=eq.true&type=eq.digital&select=*&limit=1",
        )
        if rows:
            return rows[0]

    if amount > 0:
        # Allow a 1¢ wiggle room for rounding edges
        low = max(0, amount - 0.01)
        high = amount + 0.01
        rows = await _sb_get(
            client,
            f"/products?type=eq.digital&auto_deliver=eq.true"
            f"&price=gte.{low}&price=lte.{high}"
            f"&select=*&order=created_at.desc&limit=1",
        )
        if rows:
            return rows[0]
    return None


async def _deliver_digital_product(
    client: httpx.AsyncClient,
    product: Dict[str, Any],
    customer_email: str,
    customer_name: str,
    amount: float,
) -> bool:
    """Email the buyer their download link via Resend, log a product_sold
    event, and (best-effort) post a chief notification. Returns True if
    the email was sent."""
    file_url = product.get("digital_file_url") or ""
    if not customer_email or "@" not in customer_email:
        logger.warning("digital delivery: no valid customer email")
        return False
    if not file_url:
        logger.warning("digital delivery: product has no digital_file_url")
        return False

    business_id = product.get("business_id")
    biz_name = "The Solutionist System"
    biz_email = None
    closing = "Best,"
    practitioner_name = ""
    template = None
    # Brand kit - propagates to delivery emails so customers see the
    # practitioner's accent color rather than generic gold.
    brand_color = "#D4AF37"
    brand_font = "Inter,Arial,sans-serif"

    if business_id:
        biz_rows = await _sb_get(client, f"/businesses?id=eq.{business_id}&select=name,settings&limit=1")
        if biz_rows:
            biz = biz_rows[0]
            biz_name = biz.get("name") or biz_name
            settings = biz.get("settings") or {}
            biz_email = settings.get("contact_email")
            practitioner_name = settings.get("practitioner_name") or ""
            email_templates = settings.get("email_templates") or {}
            rules = email_templates.get("global_rules") or {}
            closing = rules.get("closing_line") or closing
            template = (email_templates.get("templates") or {}).get("product_delivery")
            # Brand Engine v1: route through bundle for canonical color/font.
            # Fallback to both-shapes inline read if bundle composition fails.
            try:
                from brand_engine import get_bundle as _be_get_bundle
                _bundle = _be_get_bundle(biz.get("id"))
                _bd = _bundle.get("design") or {}
                bc = (_bd.get("primary_color") or "").strip()
                if bc.startswith("#") and (len(bc) == 7 or len(bc) == 4):
                    brand_color = bc
                bf = (_bd.get("font_heading") or _bd.get("font_body") or "").strip()
                if bf:
                    brand_font = f"{bf},Inter,Arial,sans-serif"
            except Exception:
                brand_kit = settings.get("brand_kit") or {}
                if isinstance(brand_kit, dict):
                    _colors = (brand_kit.get("colors") or {})
                    bc = (_colors.get("primary") or brand_kit.get("primary_color") or "").strip()
                    if bc.startswith("#") and (len(bc) == 7 or len(bc) == 4):
                        brand_color = bc
                    _fp = (brand_kit.get("font_pair") or {})
                    bf = (_fp.get("heading") or _fp.get("body")
                          or brand_kit.get("font_heading") or brand_kit.get("font_body") or "").strip()
                    if bf:
                        brand_font = f"{bf},Inter,Arial,sans-serif"

    # Substitute variables
    name = product.get("name") or "your download"
    contact_first = (customer_name.split(" ")[0] if customer_name else "there") or "there"
    vars_ = {
        "contact_name": contact_first,
        "business_name": biz_name,
        "practitioner_name": practitioner_name,
        "product_name": name,
        "download_url": file_url,
        "closing_line": closing,
    }

    def apply(text: str) -> str:
        out = text or ""
        for k, v in vars_.items():
            out = out.replace("{" + k + "}", str(v))
        return out

    btn_style = (
        f"display:inline-block;padding:14px 32px;background:{brand_color};"
        f"color:#fff;text-decoration:none;border-radius:8px;font-size:16px;font-weight:bold;"
    )
    if template and template.get("subject") and template.get("body"):
        subject = apply(template["subject"])
        body_text = apply(template["body"])
        # Convert plain-text body to a minimal HTML if the template stored plain text
        body_html = (
            f"""<div style="font-family:{brand_font};font-size:14px;line-height:1.6;color:#222;">
{body_text.replace(chr(10), '<br>')}
<br><br>
<a href="{file_url}" style="{btn_style}">Download Now</a>
</div>"""
        )
    else:
        subject = f"Your download: {name}"
        body_html = f"""<div style="font-family:{brand_font};font-size:14px;line-height:1.6;color:#222;">
            <h2 style="margin-top:0;">Thank you for your purchase!</h2>
            <p>Here's your download link for <strong>{name}</strong>:</p>
            <p><a href="{file_url}" style="{btn_style}">Download Now</a></p>
            <p>This link will remain active. Save it for future reference.</p>
            <p>If you have any questions, just reply to this email.</p>
            <p>{closing}<br>{practitioner_name or biz_name}</p>
        </div>"""

    try:
        from email_sender import send_via_resend, DEFAULT_FROM_EMAIL
        from_email = os.environ.get("RESEND_FROM_EMAIL") or DEFAULT_FROM_EMAIL
        await send_via_resend(
            to_email=customer_email,
            to_name=customer_name or None,
            from_email=from_email,
            from_name=biz_name,
            subject=subject,
            body=body_html,
            reply_to=biz_email,
        )
    except Exception as e:
        logger.warning(f"digital delivery: resend send failed: {e}")
        return False

    # Log the sale
    if business_id:
        await _sb_post(client, "/events", {
            "business_id": business_id,
            "event_type": "product_sold",
            "data": {
                "product_id": product.get("id"),
                "product_name": name,
                "amount": amount,
                "currency": (product.get("currency") or "USD"),
                "customer_email": customer_email,
                "customer_name": customer_name,
                "auto_delivered": True,
            },
            "source": "stripe_webhook",
        })
        await _sb_post(client, "/chief_notifications", {
            "business_id": business_id,
            "type": "success",
            "title": f"💰 Sale — {name} (${amount:,.2f})",
            "body": f"{customer_email} purchased {name}. Download link delivered automatically.",
            "status": "unread",
            "data": {
                "kind": "product_sold",
                "product_id": product.get("id"),
                "product_name": name,
                "amount": amount,
                "customer_email": customer_email,
            },
        })
    logger.info(f"digital delivery: sent {name} to {customer_email}")
    return True


async def _match_invoice_for_payment(
    client: httpx.AsyncClient,
    payment_link_id: str,
    amount: float,
) -> Optional[Dict[str, Any]]:
    """Find the invoice this payment corresponds to. Strategy:
       1. If payment_link_id is non-empty, look for an invoice whose
          stripe_payment_url contains that id.
       2. Fall back to recently-sent invoices with a matching total.
       Returns the first matching row, or None.
    """
    if payment_link_id:
        rows = await _sb_get(
            client,
            f"/invoices?stripe_payment_url=ilike.*{payment_link_id}*"
            f"&select=id,invoice_number,business_id,contact_id,total,status&limit=1",
        )
        if rows:
            return rows[0]

    # Amount fallback — broaden the window a touch (1¢) to ride out
    # rounding inconsistencies between client display and Stripe totals.
    if amount > 0:
        amount_low = max(0, amount - 0.01)
        amount_high = amount + 0.01
        rows = await _sb_get(
            client,
            f"/invoices?status=in.(sent,viewed,overdue)"
            f"&total=gte.{amount_low}&total=lte.{amount_high}"
            f"&select=id,invoice_number,business_id,contact_id,total,status,sent_at"
            f"&order=sent_at.desc.nullslast,created_at.desc&limit=1",
        )
        if rows:
            return rows[0]
    return None


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook payloads (payment links / invoice matching).

    Signature verification is now MANDATORY (beta-readiness audit,
    adversarial): this handler flips invoices to paid and can trigger
    digital-product delivery, matching an invoice by amount when there's
    no link id. Processing unsigned POSTs let a forged
    checkout.session.completed mark any invoice paid with no money moved.
    Fail-closed like the subscription webhook in stripe_billing.py — set
    STRIPE_PAYMENTS_WEBHOOK_SECRET (or STRIPE_WEBHOOK_SECRET) on Railway."""
    body = await request.body()
    _wh_secret = (
        os.environ.get("STRIPE_PAYMENTS_WEBHOOK_SECRET")
        or os.environ.get("STRIPE_WEBHOOK_SECRET")
        or ""
    ).strip()
    if not _wh_secret:
        logger.error(
            "stripe webhook REJECTED: no STRIPE_PAYMENTS_WEBHOOK_SECRET / "
            "STRIPE_WEBHOOK_SECRET configured — refusing to process unsigned events"
        )
        raise HTTPException(500, "Stripe payments webhook not configured")
    from stripe_billing import _verify_stripe_signature
    _verify_stripe_signature(body, request.headers.get("stripe-signature", ""), _wh_secret)
    try:
        event = json.loads(body)
    except Exception:
        logger.warning("stripe webhook: invalid JSON payload")
        return {"status": "invalid"}

    # Idempotency: a signed event can still be replayed. Record-first
    # into stripe_webhook_events (id = Stripe event.id is the PK); a
    # replay collides on the UNIQUE PK and we skip before any state
    # mutation (notably digital-product re-delivery). Best-effort — a
    # bookkeeping hiccup never blocks a genuine first-delivery event.
    _evt_id = (event.get("id") or "").strip()
    if _evt_id:
        try:
            async with httpx.AsyncClient() as _c:
                _seen = await _sb_get(_c, f"/stripe_webhook_events?id=eq.{_evt_id}&select=id&limit=1")
                if _seen:
                    logger.info(f"stripe webhook: {_evt_id} already processed (dedupe)")
                    return {"status": "duplicate", "id": _evt_id}
                await _sb_post(_c, "/stripe_webhook_events", {
                    "id": _evt_id, "type": (event.get("type") or ""), "raw": event,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                })
        except Exception as _e:
            logger.warning(f"stripe webhook dedup skipped: {_e}")

    evt_type = (event.get("type") or "").strip()
    if evt_type != "checkout.session.completed":
        # Accept and ignore — many event types share the endpoint.
        logger.info(f"stripe webhook: ignoring {evt_type}")
        return {"status": "ignored", "reason": evt_type}

    session_obj = (event.get("data") or {}).get("object") or {}
    payment_link = session_obj.get("payment_link") or ""
    amount_total = session_obj.get("amount_total")
    customer_details = session_obj.get("customer_details") or {}
    customer_email = (customer_details.get("email") or "").strip().lower()

    try:
        amount_dollars = float(amount_total) / 100.0 if amount_total is not None else 0.0
    except (TypeError, ValueError):
        amount_dollars = 0.0

    logger.info(
        f"stripe webhook: checkout.session.completed link={payment_link} "
        f"amount=${amount_dollars:.2f} email={customer_email or '-'}"
    )

    async with httpx.AsyncClient() as client:
        invoice = await _match_invoice_for_payment(client, payment_link, amount_dollars)
        if not invoice:
            # Maybe this is a digital product purchase rather than an invoice payment.
            product = await _match_digital_product_for_payment(client, payment_link, amount_dollars)
            if product:
                customer_name = (customer_details.get("name") or "").strip()
                delivered = await _deliver_digital_product(
                    client, product, customer_email, customer_name, amount_dollars,
                )
                return {
                    "status": "product_delivered" if delivered else "product_match_no_send",
                    "product_id": product.get("id"),
                    "product_name": product.get("name"),
                    "amount": amount_dollars,
                }
            logger.warning(
                f"stripe webhook: no invoice or product matched (link={payment_link}, amount=${amount_dollars:.2f})"
            )
            # Still 200 so Stripe doesn't retry forever
            return {"status": "no_match", "amount": amount_dollars, "link": payment_link}

        invoice_id = invoice["id"]
        invoice_number = invoice.get("invoice_number")
        business_id = invoice.get("business_id")
        contact_id = invoice.get("contact_id")
        total = float(invoice.get("total") or amount_dollars)
        paid_at = datetime.now(timezone.utc).isoformat()

        # 1) Flip invoice to paid
        await _sb_patch(client, f"/invoices?id=eq.{invoice_id}", {
            "status": "paid",
            "paid_at": paid_at,
            "payment_method": "stripe",
        })

        # 2) Lookup contact for the timeline + notification text
        contact_name = "Client"
        if contact_id:
            rows = await _sb_get(client, f"/contacts?id=eq.{contact_id}&select=name,health_score")
            if rows:
                contact_name = rows[0].get("name") or contact_name

        # 3) Timeline event — via the spine (Rails Arc 3). Previously
        # gated on contact_id, which silently dropped the signal for
        # contact-less invoices; the spine emits regardless (contact
        # attaches when known).
        import event_spine
        event_spine.emit("invoice_paid_auto", business_id, {
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "total": total,
            "payment_method": "stripe",
            "stripe_payment_link": payment_link,
            "customer_email": customer_email or None,
        }, contact_id=contact_id, source="stripe_webhook")

        # 4) Notification
        await _sb_post(client, "/chief_notifications", {
            "business_id": business_id,
            "type": "success",
            "title": f"💰 Payment Received — ${total:,.2f}",
            "body": f"{contact_name} paid Invoice {invoice_number}.",
            "suggested_action": f"Thank {contact_name}",
            "status": "unread",
            "data": {
                "kind": "invoice_paid",
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "contact_id": contact_id,
                "contact_name": contact_name,
                "total": total,
            },
        })

        # 5) Bump contact health — paying clients are healthy
        if contact_id:
            await _sb_patch(client, f"/contacts?id=eq.{contact_id}", {
                "health_score": 100,
                "last_interaction": paid_at,
            })

        logger.info(
            f"stripe webhook: marked {invoice_number} paid (${total:,.2f}) for {contact_name}"
        )
        return {
            "status": "paid",
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
        }


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
SUPABASE_KEY = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
                or os.environ.get("SUPABASE_SERVICE_KEY", ""))


def _validate_provider(provider: str) -> str:
    p = (provider or "").strip().lower()
    if p not in SUPPORTED_PROVIDERS:
        raise HTTPException(400, f"Unsupported provider '{provider}'. Try one of: {', '.join(SUPPORTED_PROVIDERS)}")
    return p


@router.get("/payments/connect/{provider}")
async def payments_connect(provider: str, business_id: Optional[str] = None):
    """Adapter-seam version: answers from the payments_core registry
    instead of a hardcoded not_implemented. Stripe points at the real
    Connect flow; others say honestly that only manual links exist."""
    import payments_core
    p = _validate_provider(provider)
    adapter = payments_core.REGISTRY[p]
    if adapter.connectable:
        return {
            "status": "connect_available",
            "provider": p,
            "business_id": business_id or None,
            "message": f"Connect {adapter.display_name} from OPERATE → Payments "
                       f"(the Connect button walks the OAuth flow).",
        }
    return {
        "status": "not_available",
        "provider": p,
        "business_id": business_id or None,
        "connectable_providers": [a.id for a in payments_core.REGISTRY.values() if a.connectable],
        "message": f"{adapter.display_name} processing isn't wired yet — paste your "
                   f"{adapter.display_name} payment link in BUILD → Integrations → "
                   f"Payment Providers and it appears on invoices today.",
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
