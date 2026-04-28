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
from fastapi import APIRouter, HTTPException, Request
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
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON", "")
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

    if template and template.get("subject") and template.get("body"):
        subject = apply(template["subject"])
        body_text = apply(template["body"])
        # Convert plain-text body to a minimal HTML if the template stored plain text
        body_html = (
            f"""<div style="font-family:Inter,Arial,sans-serif;font-size:14px;line-height:1.6;color:#222;">
{body_text.replace(chr(10), '<br>')}
<br><br>
<a href="{file_url}" style="display:inline-block;padding:14px 32px;background:#D4AF37;color:#fff;text-decoration:none;border-radius:8px;font-size:16px;font-weight:bold;">Download Now</a>
</div>"""
        )
    else:
        subject = f"Your download: {name}"
        body_html = f"""<div style="font-family:Inter,Arial,sans-serif;font-size:14px;line-height:1.6;color:#222;">
            <h2 style="margin-top:0;">Thank you for your purchase!</h2>
            <p>Here's your download link for <strong>{name}</strong>:</p>
            <p><a href="{file_url}" style="display:inline-block;padding:14px 32px;background:#D4AF37;color:#fff;text-decoration:none;border-radius:8px;font-size:16px;font-weight:bold;">Download Now</a></p>
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
    """Handle Stripe webhook payloads. Signature verification is
    intentionally skipped here — STRIPE_WEBHOOK_SECRET is not yet wired
    in env. Add `stripe.Webhook.construct_event` checks once the secret
    is provisioned. Until then, we accept any POST and rely on the
    matching logic to filter spurious traffic."""
    body = await request.body()
    try:
        event = json.loads(body)
    except Exception:
        logger.warning("stripe webhook: invalid JSON payload")
        return {"status": "invalid"}

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

        # 3) Timeline event
        if contact_id:
            await _sb_post(client, "/events", {
                "business_id": business_id,
                "contact_id": contact_id,
                "event_type": "invoice_paid_auto",
                "data": {
                    "invoice_id": invoice_id,
                    "invoice_number": invoice_number,
                    "total": total,
                    "payment_method": "stripe",
                    "stripe_payment_link": payment_link,
                    "customer_email": customer_email or None,
                },
                "source": "stripe_webhook",
            })

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
