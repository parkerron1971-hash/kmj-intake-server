"""
stripe_billing.py — subscription billing (Phase 5b of BILLING_PLAN).

Adds three endpoints:

    POST /billing/checkout      (authed)
        Body: { business_id }
        → { url } — a Stripe Checkout Session URL to start a subscription.
        Creates a Stripe Customer for the business on first use and
        persists stripe_customer_id back to the businesses row.

    POST /billing/portal        (authed)
        Body: { business_id }
        → { url } — a Stripe Customer Portal session for managing the
        payment method, switching plans, or canceling. Requires the
        business to already have a stripe_customer_id.

    POST /billing/webhook       (Stripe → us; signature-verified)
        Body: raw Stripe event JSON
        Header: Stripe-Signature
        Handles customer.subscription.{created,updated,deleted} and
        invoice.payment_failed. Persists subscription state onto the
        owning businesses row and logs every event to the
        stripe_webhook_events table (dedupe via the stripe_id UNIQUE
        constraint).

    GET  /billing/status        (no auth)
        → { configured: bool, has_price_id: bool, has_webhook_secret: bool }
        Frontend uses this to decide whether to show the Start
        Subscription CTA at all.

═══════════════════════════════════════════════════════════════════════
ENV
═══════════════════════════════════════════════════════════════════════

    STRIPE_SECRET_KEY            — sk_live_… or sk_test_…
    STRIPE_WEBHOOK_SECRET        — whsec_… (from dashboard → Webhooks)
    STRIPE_PRICE_ID_DEFAULT      — price_… (the default subscription plan)
    STRIPE_SUCCESS_URL           — defaults to mysolutionist.app/billing/success
    STRIPE_CANCEL_URL            — defaults to mysolutionist.app/billing/cancel
    STRIPE_PORTAL_RETURN_URL     — defaults to mysolutionist.app/billing/done
    SUPABASE_URL                 — same as elsewhere
    SUPABASE_SERVICE_ROLE_KEY    — same as elsewhere

═══════════════════════════════════════════════════════════════════════
NOTES
═══════════════════════════════════════════════════════════════════════

  • Uses httpx + form-encoded calls (matching stripe_proxy.py), no new
    pip dependency.
  • Tenant authorization on /checkout + /portal: the JWT-verified user
    must own the business (businesses.owner_id == auth.uid()). The
    service role does the actual DB read.
  • Webhook signature: we verify the `t=…,v1=…` header using HMAC-SHA256
    of "<timestamp>.<body>" against STRIPE_WEBHOOK_SECRET. Rejects
    events older than 5 minutes (Stripe's recommended tolerance).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from auth_supabase import AuthedUser, require_user
from lead_admin import _service_headers, SUPABASE_URL


STRIPE_API_BASE = "https://api.stripe.com/v1"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)
SIGNATURE_TOLERANCE_S = 300  # 5 minutes; Stripe's recommended max skew


logger = logging.getLogger("stripe_billing")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] billing: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


router = APIRouter(prefix="/billing", tags=["billing"])


def _stripe_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not key:
        raise HTTPException(500, "Stripe not configured (STRIPE_SECRET_KEY missing)")
    return key


def _success_url() -> str:
    return os.environ.get("STRIPE_SUCCESS_URL", "https://mysolutionist.app/billing/success")


def _cancel_url() -> str:
    return os.environ.get("STRIPE_CANCEL_URL", "https://mysolutionist.app/billing/cancel")


def _portal_return_url() -> str:
    return os.environ.get("STRIPE_PORTAL_RETURN_URL", "https://mysolutionist.app/billing/done")


async def _stripe_post(path: str, form: Dict[str, Any]) -> Dict[str, Any]:
    """POST form-encoded body to Stripe; return parsed JSON or raise."""
    # Flatten nested dicts to Stripe's bracket notation (e.g.
    # metadata[business_id]=…). Lists become indexed brackets too.
    flat: Dict[str, str] = {}
    for k, v in form.items():
        _flatten(flat, k, v)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.post(
            f"{STRIPE_API_BASE}{path}",
            auth=(_stripe_key(), ""),
            data=flat,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if r.status_code >= 400:
        logger.error(f"Stripe {path} {r.status_code}: {r.text[:300]}")
        raise HTTPException(status_code=r.status_code, detail=f"Stripe error: {r.text[:200]}")
    return r.json()


def _flatten(out: Dict[str, str], key: str, value: Any) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(out, f"{key}[{k}]", v)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flatten(out, f"{key}[{i}]", v)
    elif value is None:
        return
    elif isinstance(value, bool):
        out[key] = "true" if value else "false"
    else:
        out[key] = str(value)


async def _load_business(business_id: str) -> Dict[str, Any]:
    """Fetch a single businesses row by id via the service role. 404
    if missing."""
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/businesses",
            headers=headers,
            params={"id": f"eq.{business_id}", "select": "*", "limit": "1"},
        )
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail="Failed to load business")
    rows = r.json()
    if not rows:
        raise HTTPException(status_code=404, detail="Business not found")
    return rows[0]


async def _patch_business(business_id: str, body: Dict[str, Any]) -> None:
    """PATCH a businesses row via the service role. Fire and check."""
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.patch(
            f"{SUPABASE_URL}/rest/v1/businesses",
            headers=headers,
            params={"id": f"eq.{business_id}"},
            json=body,
        )
    if r.status_code >= 400:
        logger.error(f"patch business {business_id} {r.status_code}: {r.text[:200]}")
        raise HTTPException(status_code=r.status_code, detail="Failed to update business")


def _require_owner_of(user: AuthedUser, business: Dict[str, Any]) -> None:
    """Authorize: the JWT-verified user must own this business."""
    if business.get("owner_id") != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't own this business.",
        )


# ─── Status (no auth) ──────────────────────────────────────────────────

@router.get("/status")
async def billing_status_endpoint():
    """Lets the frontend gate the Start Subscription button without
    needing to call /checkout speculatively."""
    import feature_gates
    return {
        "configured":         bool(os.environ.get("STRIPE_SECRET_KEY")),
        "has_price_id":       bool(os.environ.get("STRIPE_PRICE_ID_DEFAULT")),
        "has_webhook_secret": bool(os.environ.get("STRIPE_WEBHOOK_SECRET")),
        "tiers_configured":   {p: bool((os.environ.get(f"STRIPE_PRICE_ID_{p.upper()}") or "").strip())
                               for p in feature_gates.PLANS},
        "enforce":            feature_gates.enforcement_on(),
    }


@router.get("/access")
async def billing_access(business_id: str, user: AuthedUser = Depends(require_user)):
    """The app-shell gate: is this business allowed in? (2026-07-03,
    Kevin's ruling: no payment → lose access to the subscription.)

    Any authed user may ask (team members need the answer too — the
    state itself isn't sensitive). Frontend shows the paywall on
    'locked' and a warning banner on 'grace'. Fails OPEN ('full') on
    any internal error — a billing read must never brick the app."""
    import feature_gates
    try:
        import usage_metering
        business = await _load_business(business_id)
        grandfathered = usage_metering.is_grandfathered_user(
            str(business.get("owner_id") or ""))
        state = feature_gates.access_state(business, grandfathered)
        return {
            "ok": True,
            **state,
            "subscription_status": business.get("subscription_status"),
            "trial_ends_at": business.get("trial_ends_at"),
            "plan": feature_gates.plan_of(business),
            "enforce": feature_gates.enforcement_on(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"/billing/access failed open: {e}")
        return {"ok": True, "state": "full", "reason": "error_fail_open"}


@router.get("/plans")
async def billing_plans():
    """The configured tiers with live price display data from Stripe.
    Unconfigured tiers are listed with configured=false (pricing TBD)."""
    import feature_gates as fg
    out = []
    for plan in fg.PLANS:
        pid = (os.environ.get(f"STRIPE_PRICE_ID_{plan.upper()}") or "").strip()
        entry = {"plan": plan, "configured": bool(pid), "price_id": pid or None}
        if pid and os.environ.get("STRIPE_SECRET_KEY"):
            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
                    r = await c.get(f"{STRIPE_API_BASE}/prices/{pid}",
                                    auth=(_stripe_key(), ""))
                if r.status_code < 400:
                    pr = r.json()
                    entry["unit_amount"] = pr.get("unit_amount")
                    entry["currency"] = pr.get("currency")
                    entry["interval"] = ((pr.get("recurring") or {}).get("interval"))
            except Exception as e:
                logger.warning(f"price fetch {pid} failed: {e}")
        out.append(entry)
    features_by_plan = {p: [f for f, mp in fg.FEATURE_MIN_PLAN.items()
                            if fg._PLAN_RANK[p] >= fg._PLAN_RANK[mp]]
                        for p in fg.PLANS}
    return {"ok": True, "plans": out, "features_by_plan": features_by_plan,
            "enforce": fg.enforcement_on(),
            "note": "All features are free for every practitioner until pricing is locked."}


@router.get("/entitlements")
async def billing_entitlements(biz: str, user: AuthedUser = Depends(require_user)):
    """Phase E gate-ready entitlements for a business (unenforced today)."""
    import feature_gates
    business = await _load_business(biz)
    _require_owner_of(user, business)
    out = feature_gates.entitlements(business)
    out["ok"] = True
    out["trial_ends_at"] = business.get("trial_ends_at")
    out["current_period_end"] = business.get("current_period_end")
    out["cancel_at_period_end"] = business.get("cancel_at_period_end")
    return out


# ─── Checkout (authed) ─────────────────────────────────────────────────

class CheckoutBody(BaseModel):
    business_id: str
    price_id: Optional[str] = None  # explicit price override
    plan: Optional[str] = None      # 'starter' | 'professional' | 'practice'


def _price_for_plan(plan):
    """Resolve a tier name -> Stripe price id from env. Falls back to the
    legacy single-plan default."""
    if plan:
        pid = (os.environ.get(f"STRIPE_PRICE_ID_{plan.upper()}") or "").strip()
        if pid:
            return pid
    return (os.environ.get("STRIPE_PRICE_ID_DEFAULT") or "").strip()


@router.post("/checkout")
async def create_checkout(body: CheckoutBody, user: AuthedUser = Depends(require_user)):
    """Mint a Stripe Customer (if needed) + Checkout Session for a
    subscription. Returns the Checkout URL the frontend opens."""
    price_id = (body.price_id or _price_for_plan(body.plan)).strip()
    if not price_id:
        raise HTTPException(409, "Pricing is not configured yet (no Stripe price ids set). "
                                 "Everything stays free until pricing is locked.")

    biz = await _load_business(body.business_id)
    _require_owner_of(user, biz)

    customer_id = biz.get("stripe_customer_id")
    if not customer_id:
        # Create a Customer keyed back to this business + auth user.
        cust = await _stripe_post("/customers", {
            "email": user.email,
            "name":  biz.get("name") or "Solutionist user",
            "metadata": {
                "business_id":   biz["id"],
                "auth_user_id":  user.id,
                "business_name": biz.get("name") or "",
            },
        })
        customer_id = cust["id"]
        await _patch_business(biz["id"], {"stripe_customer_id": customer_id})
        logger.info(f"Created Stripe customer {customer_id} for business {biz['id']}")

    # Mint the Checkout Session. (Pricing v2, 2026-07-12: the metered
    # PAYG overage line item is GONE — usage beyond the allowance draws
    # down prepaid credit packs instead. See /billing/credits/checkout.)
    line_items: list = [{"price": price_id, "quantity": 1}]
    session = await _stripe_post("/checkout/sessions", {
        "mode": "subscription",
        "customer": customer_id,
        "line_items": line_items,
        "success_url": _success_url() + "?session_id={CHECKOUT_SESSION_ID}",
        "cancel_url":  _cancel_url(),
        # Echo business_id in metadata so the webhook can resolve back
        # even if the customer object's metadata is missing it.
        "subscription_data": _subscription_data(biz, user),
        "metadata": {
            "business_id":  biz["id"],
            "auth_user_id": user.id,
        },
    })
    return {"url": session.get("url"), "id": session.get("id")}


# ─── Prepaid credit packs (Pricing v2 Phase C, 2026-07-12) ────────────
# One-time payments via inline price_data — no dashboard products to
# configure. The webhook (checkout.session.completed with
# metadata.kind=credit_pack) grants the units; credit_ledger's UNIQUE
# stripe_payment_id makes retries harmless.

class CreditCheckoutBody(BaseModel):
    business_id: str
    pack: str  # 'small' | 'medium' | 'large'


@router.post("/credits/checkout")
async def create_credit_checkout(body: CreditCheckoutBody,
                                 user: AuthedUser = Depends(require_user)):
    """Mint a one-time-payment Checkout Session for a credit pack."""
    import credit_ledger
    p = credit_ledger.CREDIT_PACKS.get((body.pack or "").strip().lower())
    if not p:
        raise HTTPException(400, f"pack must be one of {sorted(credit_ledger.CREDIT_PACKS)}")
    if not os.environ.get("STRIPE_SECRET_KEY", "").strip():
        raise HTTPException(409, "Payments aren't configured yet — credits can't be "
                                 "purchased until Stripe is connected.")

    biz = await _load_business(body.business_id)
    _require_owner_of(user, biz)

    pack = (body.pack or "").strip().lower()
    payload: Dict[str, Any] = {
        "mode": "payment",
        "line_items": [{
            "quantity": 1,
            "price_data": {
                "currency": "usd",
                "unit_amount": p["cents"],
                "product_data": {
                    "name": f"Solutionist credits — {p['units']} units",
                    "description": ("Prepaid AI-action credits. They never expire; "
                                    "your monthly plan allowance is always used first."),
                },
            },
        }],
        "success_url": _success_url() + "?credits=1&session_id={CHECKOUT_SESSION_ID}",
        "cancel_url":  _cancel_url(),
        "metadata": {
            "kind":         "credit_pack",
            "credit_pack":  pack,
            "credit_units": str(p["units"]),
            "business_id":  biz["id"],
            "auth_user_id": user.id,
        },
    }
    # Attach the existing Stripe customer when there is one (unified
    # billing history); packs work fine without a customer too.
    if biz.get("stripe_customer_id"):
        payload["customer"] = biz["stripe_customer_id"]
    else:
        payload["customer_email"] = user.email

    session = await _stripe_post("/checkout/sessions", payload)
    return {"url": session.get("url"), "id": session.get("id")}


@router.get("/usage")
async def billing_usage(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The Plan & Usage meter's one read: weighted usage vs allowance,
    prepaid credit balance, and the pack catalog."""
    import credit_ledger
    import usage_metering
    biz_row = await _load_business(biz)
    _require_owner_of(user, biz_row)
    s = usage_metering.usage_summary(biz, biz_row)
    s["credits"] = credit_ledger.summary(biz)
    s["packs"] = credit_ledger.CREDIT_PACKS
    return s


def _subscription_data(biz, user):
    """Checkout subscription_data: metadata + a free trial for FIRST
    subscriptions only (re-subscribers do not get a second trial)."""
    data = {
        "metadata": {"business_id": biz["id"], "auth_user_id": user.id},
    }
    try:
        trial_days = int(os.environ.get("BILLING_TRIAL_DAYS") or "14")
    except ValueError:
        trial_days = 14
    if trial_days > 0 and not biz.get("stripe_subscription_id"):
        data["trial_period_days"] = trial_days
    return data


# ─── Portal (authed) ───────────────────────────────────────────────────

class PortalBody(BaseModel):
    business_id: str


@router.post("/portal")
async def create_portal(body: PortalBody, user: AuthedUser = Depends(require_user)):
    """Mint a Stripe Customer Portal session URL for managing the
    existing subscription. 400 if the business has never had a customer."""
    biz = await _load_business(body.business_id)
    _require_owner_of(user, biz)
    customer_id = biz.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(
            status_code=400,
            detail="This business has no Stripe customer yet. Start a subscription first.",
        )
    session = await _stripe_post("/billing_portal/sessions", {
        "customer": customer_id,
        "return_url": _portal_return_url(),
    })
    return {"url": session.get("url")}


# ─── Webhook (Stripe → us) ─────────────────────────────────────────────

def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> None:
    """Validate Stripe's `Stripe-Signature` header. Raises 400 on
    any mismatch (missing parts, bad HMAC, stale timestamp)."""
    if not sig_header:
        raise HTTPException(400, "Missing Stripe-Signature header")
    parts: Dict[str, str] = {}
    for chunk in sig_header.split(","):
        if "=" in chunk:
            k, v = chunk.strip().split("=", 1)
            parts.setdefault(k, v)
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        raise HTTPException(400, "Malformed Stripe-Signature header")
    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(400, "Stripe-Signature timestamp not an int")
    if abs(time.time() - ts) > SIGNATURE_TOLERANCE_S:
        raise HTTPException(400, "Stripe-Signature timestamp outside tolerance window")
    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(400, "Invalid Stripe signature")


async def _record_webhook(event: Dict[str, Any], business_id: Optional[str], error: Optional[str] = None) -> None:
    """Insert the event into stripe_webhook_events. The UNIQUE constraint
    on stripe_id dedupes — if Stripe retries, we get a 409 and just
    swallow it (we already processed)."""
    from datetime import datetime, timezone
    headers = _service_headers()
    # PRODUCTION stripe_webhook_events shape (PR3): id = Stripe event.id is
    # the PK (dedupes via 409), payload lives in `raw`, errors in
    # `processed_error`. (The old drafted billing-migration.sql shape is
    # superseded — see 2026_06_09_phasee_billing.sql.)
    body = {
        "id":            event.get("id"),
        "type":          event.get("type"),
        "livemode":      bool(event.get("livemode")),
        "business_id":   business_id,
        "raw":           event,
        "processed_at":  None if error else datetime.now(timezone.utc).isoformat(),
        "processed_error": error,
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.post(
            f"{SUPABASE_URL}/rest/v1/stripe_webhook_events",
            headers={**headers, "Prefer": "return=minimal"},
            json=body,
        )
    if r.status_code == 409:
        logger.info(f"webhook {event.get('id')} already recorded (dedupe)")
        return
    if r.status_code >= 400:
        logger.error(f"record webhook {r.status_code}: {r.text[:200]}")
        # Don't raise — we'd rather lose the audit row than 500 the webhook
        # and trigger Stripe retry storms over a logging issue.


def _resolve_business_id(event: Dict[str, Any]) -> Optional[str]:
    """Pull business_id out of the event payload. Tries the subscription's
    metadata first, then the customer's metadata."""
    obj = (event.get("data") or {}).get("object") or {}
    meta = obj.get("metadata") or {}
    bid = meta.get("business_id")
    if bid:
        return bid
    return None


async def _resolve_business_id_async(event):
    """Metadata first; else look the business up by Stripe customer id
    (covers invoice.* events, which carry no subscription metadata)."""
    bid = _resolve_business_id(event)
    if bid:
        return bid
    obj = (event.get("data") or {}).get("object") or {}
    customer = obj.get("customer")
    if not customer:
        return None
    headers = _service_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/businesses",
            headers=headers,
            params={"stripe_customer_id": f"eq.{customer}", "select": "id", "limit": "1"},
        )
    rows = r.json() if r.status_code < 400 else []
    return rows[0]["id"] if rows else None


def _ts_to_iso(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


async def _apply_subscription_state(event_type: str, sub_obj: Dict[str, Any], business_id: Optional[str]) -> None:
    """Map a Stripe subscription object onto our businesses row."""
    if not business_id:
        logger.warning(f"{event_type}: no business_id resolvable; skipping DB update")
        return

    status_value = sub_obj.get("status")
    if event_type == "customer.subscription.deleted":
        status_value = "canceled"

    # Plan: subscription.items.data[0].price.id (and product nickname,
    # if available). We just store the price id as the "plan" string;
    # frontend can map to a human-friendly name later.
    items = ((sub_obj.get("items") or {}).get("data")) or []
    price_id = ((items[0].get("price") or {}).get("id")) if items else None

    patch = {
        "stripe_subscription_id":  sub_obj.get("id"),
        "subscription_status":     status_value,
        "subscription_plan":       price_id,
        "trial_ends_at":           _ts_to_iso(sub_obj.get("trial_end")),
        "current_period_end":      _ts_to_iso(sub_obj.get("current_period_end")),
        "cancel_at_period_end":    bool(sub_obj.get("cancel_at_period_end")),
    }
    await _patch_business(business_id, patch)
    logger.info(f"Updated business {business_id} → {status_value} ({price_id})")


async def _handle_invoice_payment_failed(inv: Dict[str, Any], business_id: Optional[str]) -> None:
    """Bump status to past_due. Stripe will also fire
    customer.subscription.updated which would do the same thing, but
    we set it here too to be defensive."""
    if not business_id:
        return
    await _patch_business(business_id, {"subscription_status": "past_due"})
    logger.info(f"invoice.payment_failed: business {business_id} → past_due")


# ─── Phase E v1.1 — numeric-limit surfaces (gate-ready, dormant) ─────

@router.get("/chief-usage")
async def chief_usage_endpoint(biz: str,
                               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Arc 19 — WEIGHTED usage summary (allotment, overage estimate,
    2x-cap state, grandfather). BillingPanel + Chief drawer read this."""
    biz_row = await _load_business(biz)
    _require_owner_of(user, biz_row)
    import usage_metering
    return usage_metering.usage_summary(biz, biz_row)


@router.get("/can-create-business")
def can_create_business_endpoint(user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Business-cap check for onboarding another business. Advisory until
    creation moves behind the backend (creation is a direct PostgREST
    insert today — surfaced in the E v1.1 ship report)."""
    import billing_limits
    return billing_limits.can_create_business(str(user.id))


@router.get("/seats")
async def seats_endpoint(biz: str,
                         user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = await _load_business(biz)
    _require_owner_of(user, biz_row)
    import billing_limits
    return billing_limits.can_add_seat(biz, biz_row)


@router.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature")):
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(500, "Stripe webhook not configured (STRIPE_WEBHOOK_SECRET missing)")

    payload = await request.body()
    _verify_stripe_signature(payload, stripe_signature or "", secret)

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON payload")

    event_type = event.get("type") or ""
    obj = (event.get("data") or {}).get("object") or {}
    business_id = await _resolve_business_id_async(event)
    error_msg: Optional[str] = None

    try:
        if event_type in ("customer.subscription.created",
                          "customer.subscription.updated",
                          "customer.subscription.deleted"):
            await _apply_subscription_state(event_type, obj, business_id)
        elif event_type == "invoice.payment_failed":
            await _handle_invoice_payment_failed(obj, business_id)
        elif event_type in ("invoice.payment_succeeded", "invoice.paid"):
            # Recovery: a successful payment clears past_due. (The
            # subscription.updated event also lands; this is defensive.)
            if business_id:
                await _patch_business(business_id, {"subscription_status": "active"})
        elif event_type == "checkout.session.completed":
            meta = obj.get("metadata") or {}
            if meta.get("kind") == "credit_pack":
                # Prepaid credit pack (Pricing v2): grant the units.
                # Guard on paid status — async payment methods complete
                # the session before money moves.
                if obj.get("payment_status") == "paid" and business_id:
                    import credit_ledger
                    ok = credit_ledger.grant_pack(
                        business_id, meta.get("credit_pack") or "",
                        obj.get("payment_intent") or obj.get("id") or "")
                    if not ok:
                        error_msg = f"credit grant failed for session {obj.get('id')}"
                elif not business_id:
                    error_msg = "credit_pack session missing business_id"
            # Subscription checkouts: the subsequent
            # customer.subscription.created carries the real state —
            # this event is audit-only for those.
        elif event_type == "checkout.session.async_payment_succeeded":
            # Delayed payment methods (bank debits) land here instead.
            meta = obj.get("metadata") or {}
            if meta.get("kind") == "credit_pack" and business_id:
                import credit_ledger
                ok = credit_ledger.grant_pack(
                    business_id, meta.get("credit_pack") or "",
                    obj.get("payment_intent") or obj.get("id") or "")
                if not ok:
                    error_msg = f"credit grant failed for session {obj.get('id')}"
        else:
            logger.info(f"Ignoring unhandled event type: {event_type}")
    except HTTPException as e:
        error_msg = f"{e.status_code}: {e.detail}"
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Error handling {event_type}")

    await _record_webhook(event, business_id, error=error_msg)

    # Always 200 unless signature failed (raised earlier). Returning
    # non-200 makes Stripe retry, which would re-trigger an error path.
    if error_msg:
        # 200 + body so Stripe stops retrying, but the row in
        # stripe_webhook_events is left with processed_at NULL + error
        # populated for triage.
        return {"received": True, "error": error_msg}
    return {"received": True}
