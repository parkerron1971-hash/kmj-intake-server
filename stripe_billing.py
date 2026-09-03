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

    GET  /billing/success | /cancel | /done   (no auth, HTML)
        Where Stripe returns the customer's browser after checkout and
        after the Customer Portal. Real pages, because checkout runs in
        its own tab: without them the last thing a practitioner saw
        after paying was the catch-all's 404.

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

import ledger_unlock
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from auth_supabase import AuthedUser, require_user
from lead_admin import require_owner
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


def _stripe_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Headers for a Stripe call, pinning the API version when one is set.

    Deliberately OPT-IN (STRIPE_API_VERSION, unset by default = the
    account's own version, which is what every call has always used).
    A pinned version is the right end state, but a WRONG version string
    400s every call including checkout, and that is not a failure worth
    risking to fix a display field. Set it in Railway once, verify a
    checkout, and it is pinned from then on.

    Whether or not it is pinned, _period_end below reads both shapes."""
    headers = dict(extra or {})
    version = (os.environ.get("STRIPE_API_VERSION") or "").strip()
    if version:
        headers["Stripe-Version"] = version
    return headers


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
            headers=_stripe_headers(
                {"Content-Type": "application/x-www-form-urlencoded"}),
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


# ─── Founding-member seats (launch pricing, Kevin-ruled 2026-07-21) ───
# The founder price = Professional entitlements, lifetime-locked rate,
# capped at FOUNDER_SEAT_LIMIT seats. The cap is enforced at
# checkout-session creation, and the publicly shown seat count comes
# from REAL subscriptions in the DB — never a hand-typed number.

def _founder_seat_limit() -> int:
    try:
        return int(os.environ.get("FOUNDER_SEAT_LIMIT") or "50")
    except ValueError:
        return 50


def _founder_price_ids() -> list:
    return [pid for pid in (
        (os.environ.get("STRIPE_PRICE_ID_FOUNDER") or "").strip(),
        (os.environ.get("STRIPE_PRICE_ID_FOUNDER_ANNUAL") or "").strip(),
    ) if pid]


async def _founder_seats_taken() -> int:
    """Count businesses holding a founder price with a live (or
    recoverable — past_due keeps the seat) subscription."""
    ids = _founder_price_ids()
    if not ids:
        return 0
    headers = {**_service_headers(), "Prefer": "count=exact"}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(
                f"{SUPABASE_URL}/rest/v1/businesses",
                headers=headers,
                params={
                    "subscription_plan": f"in.({','.join(ids)})",
                    "subscription_status": "in.(active,trialing,past_due)",
                    "select": "id",
                    "limit": "1",
                },
            )
        if r.status_code >= 400:
            logger.warning(f"founder seat count failed: {r.status_code}")
            return 0
        content_range = r.headers.get("content-range") or ""
        return int(content_range.split("/")[-1])
    except (ValueError, httpx.HTTPError) as e:
        logger.warning(f"founder seat count failed: {e}")
        return 0


async def _founder_summary() -> Dict[str, Any]:
    """The founder offer's public shape (status + plans endpoints)."""
    ids = _founder_price_ids()
    out: Dict[str, Any] = {"configured": bool(ids)}
    if not ids:
        return out
    limit = _founder_seat_limit()
    taken = await _founder_seats_taken()
    out.update({
        "plan": "professional",
        "price_id": ids[0],
        "seat_limit": limit,
        "seats_taken": taken,
        "seats_left": max(0, limit - taken),
    })
    return out


async def _price_display(pid: str) -> Optional[Dict[str, Any]]:
    """Live display data for a Stripe price id, or None."""
    if not (pid and os.environ.get("STRIPE_SECRET_KEY")):
        return None
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(f"{STRIPE_API_BASE}/prices/{pid}",
                            auth=(_stripe_key(), ""),
                            headers=_stripe_headers())
        if r.status_code < 400:
            pr = r.json()
            return {
                "unit_amount": pr.get("unit_amount"),
                "currency": pr.get("currency"),
                "interval": ((pr.get("recurring") or {}).get("interval")),
            }
    except Exception as e:
        logger.warning(f"price fetch {pid} failed: {e}")
    return None


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
        "founder":            await _founder_summary(),
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
        # A trial ends on whichever runs out first, the calendar or the
        # tank. access_state is pure, so the tank half is read here.
        trial_spent = usage_metering.trial_credits_exhausted(
            business_id, business)
        state = feature_gates.access_state(business, grandfathered, trial_spent)
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
        display = await _price_display(pid)
        if display:
            entry.update(display)
        # Annual variant (2 months free) — display data only; checkout
        # takes plan='<tier>_annual'.
        annual_pid = (os.environ.get(f"STRIPE_PRICE_ID_{plan.upper()}_ANNUAL") or "").strip()
        if annual_pid:
            entry["annual_price_id"] = annual_pid
            annual_display = await _price_display(annual_pid)
            if annual_display:
                entry["annual_unit_amount"] = annual_display.get("unit_amount")
        out.append(entry)

    # Founding-member offer: Professional at the locked launch rate,
    # first FOUNDER_SEAT_LIMIT seats. Seat counts are real.
    founder = await _founder_summary()
    if founder.get("configured"):
        display = await _price_display(founder.get("price_id") or "")
        if display:
            founder.update(display)

    features_by_plan = {p: [f for f, mp in fg.FEATURE_MIN_PLAN.items()
                            if fg._PLAN_RANK[p] >= fg._PLAN_RANK[mp]]
                        for p in fg.PLANS}

    # The offer numbers per tier, for the plan cards. plan_limits() is
    # the single source of truth (env-dialed credits included); None on
    # a limit = unlimited. deep_analysis is the CUSTOMER wording
    # (Standard/Advanced/Maximum — vendor-neutral, 2026-08-19 ruling);
    # deep_model keeps the real model name for owner surfaces (Mission
    # Control). Both go None while a CHIEF_MODEL_DEEP override has the
    # tier ladder switched off — no surface may promise a difference
    # the override is currently denying.
    import chief_models
    limits = fg.plan_limits()
    plan_details = {p: {
        "credits_monthly": limits.get(p, {}).get("chief_messages_monthly"),
        "max_seats": limits.get(p, {}).get("max_seats"),
        "max_businesses": limits.get(p, {}).get("max_businesses"),
        "bank_connections": limits.get(p, {}).get("plaid_connections"),
        "deep_analysis": chief_models.deep_analysis_label(p),
        "deep_model": chief_models.tier_deep_model_label(p),
    } for p in fg.PLANS}

    any_configured = any(e["configured"] for e in out)
    return {"ok": True, "plans": out, "founder": founder,
            "features_by_plan": features_by_plan,
            "plan_details": plan_details,
            "enforce": fg.enforcement_on(),
            "note": (None if any_configured else
                     "All features are free for every practitioner until pricing is locked.")}


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
    # 7/30 tier arc — the frontend FeatureGate reads this one payload;
    # grandfather/comp must ride along or the gate would lie to the
    # exact accounts require_feature() waves through.
    try:
        import usage_metering
        out["grandfathered"] = usage_metering.is_grandfathered_business(
            biz, business)
    except Exception:
        out["grandfathered"] = False
    out["comp_tier"] = (business.get("comp_tier") or None)
    return out


# ─── Checkout (authed) ─────────────────────────────────────────────────

class CheckoutBody(BaseModel):
    business_id: str
    price_id: Optional[str] = None  # explicit price override
    plan: Optional[str] = None      # 'starter' | 'professional' | 'practice'


def _price_for_plan(plan):
    """Resolve a plan key -> Stripe price id from env. Accepts the tier
    names plus the variant keys in feature_gates.PRICE_ENV_TO_PLAN
    ('founder', 'professional_annual', …) — anything else falls through
    to the legacy single-plan default. The allow-list keeps arbitrary
    strings from probing env vars."""
    import feature_gates
    if plan:
        key = (plan or "").strip().upper()
        if key in feature_gates.PRICE_ENV_TO_PLAN:
            pid = (os.environ.get(f"STRIPE_PRICE_ID_{key}") or "").strip()
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

    # Founding-member cap: once the seats are gone, they're gone. Checked
    # against real subscriptions at session-creation time. (A race between
    # two simultaneous checkouts can momentarily oversell by one — accept
    # it; the founding member you'd have to claw back costs more in trust
    # than the seat.)
    plan_key = (body.plan or "").strip().lower()
    if plan_key.startswith("founder") or price_id in _founder_price_ids():
        limit = _founder_seat_limit()
        taken = await _founder_seats_taken()
        if taken >= limit:
            raise HTTPException(409, f"All {limit} founding seats are taken — "
                                     "the standard Professional plan is open.")

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
    # credit_packs() not the import-time CREDIT_PACKS snapshot: one
    # source of truth, so a repriced pack can never be sold at the old
    # unit count while the meter grants the new one.
    _packs = credit_ledger.credit_packs()
    p = _packs.get((body.pack or "").strip().lower())
    if not p:
        raise HTTPException(400, f"pack must be one of {sorted(_packs)}")
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


@router.get("/credits/{business_id}")
async def credits_overview_endpoint(business_id: str,
                                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Credits-surfacing (2026-08-01) — the CreditsCard read. MEMBER+
    (role-ranked seat access, unlike the owner-only /billing/usage):
    every seat that can spend AI actions may see the balance.

    Shape: { ok, monthly: {allowance, used, remaining, resets_at},
    packs: {granted, used, remaining}, total_remaining, low, catalog }.
    Consumption order (documented in usage_metering.credits_overview):
    monthly allowance first — packs only burn beyond it."""
    from business_users_router import require_role
    require_role(business_id, str(user.id), "member")
    import usage_metering
    return usage_metering.credits_overview(business_id)


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
    s["packs"] = credit_ledger.credit_packs()
    return s


def _subscription_data(biz, user):
    """Checkout subscription_data: metadata + a free trial for FIRST
    subscriptions only (re-subscribers do not get a second trial)."""
    data = {
        "metadata": {"business_id": biz["id"], "auth_user_id": user.id},
    }
    # 7, per Kevin, 2026-08-24. The marketing site quotes this same env
    # var (marketing_pages._trial_days), so the "N days free" on the page
    # and trial_period_days on the subscription cannot drift apart.
    try:
        trial_days = int(os.environ.get("BILLING_TRIAL_DAYS") or "7")
    except ValueError:
        trial_days = 7
    if trial_days > 0 and not biz.get("stripe_subscription_id"):
        data["trial_period_days"] = trial_days
    return data


# ─── Portal (authed) ───────────────────────────────────────────────────

class PortalBody(BaseModel):
    business_id: str


@router.post("/portal")
async def create_portal(body: PortalBody, request: Request,
                        user: AuthedUser = Depends(require_user)):
    """Mint a Stripe Customer Portal session URL for managing the
    existing subscription. 400 if the business has never had a customer."""
    # STEP-UP. Behind this door the card and the bank details change.
    # Stripe re-authenticates for some of it, but not all, and the URL
    # is a bearer link once minted.
    ledger_unlock.require_unlock(request, str(user.id), ledger_unlock.SCOPE_DANGER)
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


# ─── Where Stripe sends the browser back to ───────────────────────────
# Checkout returns the customer's tab to success_url / cancel_url, and
# the Customer Portal returns it to STRIPE_PORTAL_RETURN_URL. All three
# default to mysolutionist.app/billing/{success,cancel,done} — and
# NOTHING served those paths. They fell past public_site's catch-all and
# answered `{"detail":"Not found"}`.
#
# Checkout opens in a NEW TAB (AccessGate.checkout → window.open), so the
# last thing a practitioner saw after handing over a card was raw 404
# JSON. The subscription was real — the webhook wrote it, the app's
# focus-recheck cleared the wall — but nobody believes a payment that
# ends in "Not found". These three routes are that missing ending.
#
# They live on the billing router, which is registered well before
# public_site_router, so the catch-all can never shadow them again.

APP_HOME = "https://system.mysolutionist.app"


def _valid_session_id(sid: str) -> bool:
    """A Stripe Checkout Session id, and nothing else — this value comes
    off a query string and gets interpolated into an API path."""
    return (sid.startswith("cs_") and len(sid) <= 120
            and all(c.isalnum() or c == "_" for c in sid))


async def _peek_checkout_session(session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Read a finished Checkout Session back, fail-soft. None when Stripe
    isn't configured, the id isn't one, or the call fails — the page
    still renders, just without the specifics."""
    sid = (session_id or "").strip()
    if not _valid_session_id(sid) or not os.environ.get("STRIPE_SECRET_KEY", "").strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(f"{STRIPE_API_BASE}/checkout/sessions/{sid}",
                            auth=(_stripe_key(), ""),
                            headers=_stripe_headers())
        if r.status_code >= 400:
            logger.warning(f"session peek {sid} → {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        logger.warning(f"session peek {sid} failed: {e}")
        return None


def _billing_page(*, title: str, eyebrow: str, heading: str,
                  body_html: str, cta_label: str = "Open your workspace",
                  cta_href: str = APP_HOME) -> HTMLResponse:
    """Render one of the return pages in the marketing shell. Falls back
    to a plain, self-contained page if the shell can't be imported — a
    person who just paid must never see a stack trace or a 404."""
    content = f"""
<section class="page-hero">
  <span class="orb orb-1" aria-hidden></span>
  <div class="container" style="max-width:640px;">
    <span class="eyebrow reveal">{eyebrow}</span>
    <h1 class="reveal reveal-delay-1">{heading}</h1>
    <div class="lead reveal reveal-delay-2" style="margin:16px auto 0;">{body_html}</div>
    <p class="reveal reveal-delay-3" style="margin-top:26px;">
      <a class="btn-primary" href="{cta_href}">{cta_label} &rarr;</a>
    </p>
  </div>
</section>
"""
    try:
        import marketing_pages
        html = marketing_pages._render_shell(
            title=title, description=heading,
            content_html=content, path="/billing", active="")
    except Exception as e:
        logger.warning(f"billing return page shell failed: {e}")
        html = (f"<!doctype html><meta charset=utf-8>"
                f"<meta name=viewport content='width=device-width,initial-scale=1'>"
                f"<title>{title}</title>"
                f"<body style='font:16px/1.6 system-ui,sans-serif;background:#0c0d10;"
                f"color:#e8e9ec;margin:0;padding:64px 24px;text-align:center'>"
                f"<h1 style='font-size:28px'>{heading}</h1>{body_html}"
                f"<p><a style='color:#7aa2ff' href='{cta_href}'>{cta_label} &rarr;</a></p>")
    return HTMLResponse(html)


@router.get("/success", include_in_schema=False)
async def billing_success(session_id: Optional[str] = None,
                          credits: Optional[str] = None):
    """Stripe's success_url. Confirms what was actually bought (read back
    from the session when we can) and points the tab at the app."""
    sess = await _peek_checkout_session(session_id)
    mode = (sess or {}).get("mode") or ("payment" if credits else "subscription")
    paid = (sess or {}).get("payment_status") in ("paid", "no_payment_required")
    complete = (sess or {}).get("status") == "complete"

    if credits or mode == "payment":
        heading = "Your credits are on the way."
        body = ("<p>The pack is added to your balance as soon as Stripe confirms "
                "the payment &mdash; usually within a few seconds. Your monthly "
                "allowance is always spent first; packs never expire.</p>")
        eyebrow = "Payment received"
    else:
        heading = "You're in."
        # A checkout that opened a trial has no charge yet, and saying
        # "payment received" over a $0 trial start is a lie the first
        # invoice would expose.
        trialing = bool(((sess or {}).get("subscription") and
                         (sess or {}).get("amount_total") == 0))
        eyebrow = "Subscription started"
        opening = ("<p>Your subscription is active. Welcome to the "
                   "Solutionist System.</p>") if not trialing else (
                  "<p>Your trial has started and your subscription is set up. "
                  "You won't be charged until the trial ends.</p>")
        body = opening + (
            "<p style='font-size:14px;opacity:.75;margin-top:12px;'>"
            "This tab can be closed &mdash; your workspace is in the tab you "
            "came from, and it unlocks on its own the moment Stripe confirms. "
            "If it still shows the paywall, hit <em>Check again</em> there.</p>")

    if sess and not (complete or paid):
        # Bank debits and other delayed methods complete the session
        # before the money moves. Don't promise what hasn't cleared.
        eyebrow = "Payment processing"
        heading = "Almost there."
        body = ("<p>Your payment method takes a little longer to clear. We'll "
                "switch your account on the moment it does &mdash; no action "
                "needed from you.</p>")

    return _billing_page(title="Subscription started", eyebrow=eyebrow,
                         heading=heading, body_html=body)


@router.get("/cancel", include_in_schema=False)
async def billing_cancel():
    """Stripe's cancel_url — they backed out of checkout. Nothing was
    charged, and nothing about their account changed."""
    return _billing_page(
        title="Checkout canceled",
        eyebrow="Nothing was charged",
        heading="No card, no charge.",
        body_html=("<p>You closed the checkout before it finished, so nothing "
                   "moved. Your account is exactly where you left it, and you "
                   "can start again whenever you're ready.</p>"),
        cta_label="Back to your workspace")


@router.get("/done", include_in_schema=False)
async def billing_portal_done():
    """The Customer Portal's return_url — they finished managing the
    subscription and clicked back."""
    return _billing_page(
        title="Billing updated",
        eyebrow="Billing",
        heading="All set.",
        body_html=("<p>Any change you made in the billing portal is saved. "
                   "Plan and payment changes reach your workspace within a "
                   "few seconds.</p>"),
        cta_label="Back to your workspace")



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


def _period_end(sub_obj: Dict[str, Any]) -> Optional[int]:
    """When the current billing period ends, from either shape.

    THE BUG THIS FIXES: Stripe's Basil version (2025-03-31) REMOVED
    current_period_start/end from the Subscription object and moved them
    onto each subscription item, which each track their own period. We
    pin no API version, so live calls run at the account's version —
    Basil or later — and `sub_obj.get("current_period_end")` has been
    coming back None. businesses.current_period_end has been writing
    NULL, and /billing/entitlements has been serving that null to every
    surface that wants to say when a subscription renews.

    Item first (the current shape), subscription second (pre-Basil, or
    if STRIPE_API_VERSION pins an older one). Our subscriptions carry a
    single item, so item[0] IS the period; on a mixed-interval
    subscription the earliest end is the honest answer to "when does
    this renew", because that is when the customer is next charged."""
    ends = [it.get("current_period_end")
            for it in (((sub_obj.get("items") or {}).get("data")) or [])
            if it.get("current_period_end")]
    if ends:
        return min(ends)
    return sub_obj.get("current_period_end")


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
        "current_period_end":      _ts_to_iso(_period_end(sub_obj)),
        "cancel_at_period_end":    bool(sub_obj.get("cancel_at_period_end")),
    }
    # 7/30 tier arc — businesses.tier was DEAD DATA: written once as
    # 'starter' at onboarding and never touched by Stripe, so every
    # tier-chip and upsell-exemption read lied. Store the resolved plan
    # key alongside the raw price id (founder → professional). Canceled
    # subscriptions drop back to 'starter'. Requires the 2026-07-30
    # tier-vocab migration (the old CHECK only allowed starter|pro|
    # enterprise) — fails soft via retry-without-tier if unapplied.
    import feature_gates as fg
    plan_key = fg.price_to_plan().get(price_id or "")
    if status_value == "canceled":
        patch["tier"] = "starter"
    elif plan_key and status_value in ("trialing", "active"):
        patch["tier"] = plan_key
    try:
        await _patch_business(business_id, patch)
    except Exception:
        # Unknown column / stale CHECK — ship the billing truth without
        # the tier mirror rather than losing the webhook.
        patch.pop("tier", None)
        await _patch_business(business_id, patch)
    logger.info(f"Updated business {business_id} → {status_value} ({price_id})")

    # Day one starts HERE. A subscription entering `trialing` is the only
    # place the system learns a trial has begun, and until now nothing
    # reacted to it — the trial_ends_at above was written and that was
    # the end of it.
    #
    # Gated on the STATUS, not the event type: Stripe can deliver
    # `updated` ahead of `created`, and begin() is idempotent, so
    # whichever arrives first opens the arc and the other stands down.
    #
    # Best-effort, off the event loop, and swallowed. The patch above is
    # what this webhook exists for; losing a billing event over a day-one
    # nicety would be the wrong trade. first_run_arc is sync (sb_clients
    # uses a blocking client), so it must not run on the loop.
    if status_value == "trialing":
        try:
            import asyncio
            import first_run_arc
            await asyncio.to_thread(
                first_run_arc.begin, business_id,
                source="subscription",
                trial_ends_at=patch.get("trial_ends_at"))
        except Exception as e:
            logger.warning(f"[first-run] arc begin failed (non-fatal): {e}")


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


# ─── One-click catalog bootstrap (owner-only, 2026-07-21) ─────────────
# Creates the locked pricing catalog IN STRIPE using the server's own
# key — no dashboard clicking. Idempotent: every price carries a
# lookup_key, so re-runs find and reuse instead of duplicating. Env
# stays the source of truth for resolution — the response hands back
# the exact block to paste into Railway.

BOOTSTRAP_CATALOG = [
    # (env_key, lookup_key, product_name, unit_amount_cents, interval)
    ("STRIPE_PRICE_ID_STARTER",             "solutionist_starter_monthly",      "Solutionist Starter",       7900,   "month"),
    ("STRIPE_PRICE_ID_STARTER_ANNUAL",      "solutionist_starter_annual",       "Solutionist Starter",       79000,  "year"),
    ("STRIPE_PRICE_ID_PROFESSIONAL",        "solutionist_professional_monthly", "Solutionist Professional",  19900,  "month"),
    ("STRIPE_PRICE_ID_PROFESSIONAL_ANNUAL", "solutionist_professional_annual",  "Solutionist Professional",  199000, "year"),
    # Display name "The Solutionist" (Kevin's 2026-08-19 rename ruling:
    # the top tier is the brand's namesake) — plan key + lookup_key stay
    # `practice`; only what the checkout page shows changed.
    ("STRIPE_PRICE_ID_PRACTICE",            "solutionist_practice_monthly",     "The Solutionist",           39900,  "month"),
    ("STRIPE_PRICE_ID_PRACTICE_ANNUAL",     "solutionist_practice_annual",      "The Solutionist",           399000, "year"),
    ("STRIPE_PRICE_ID_FOUNDER",             "solutionist_founder_monthly",      "Solutionist Professional — Founding Member", 14900,  "month"),
    ("STRIPE_PRICE_ID_FOUNDER_ANNUAL",      "solutionist_founder_annual",       "Solutionist Professional — Founding Member", 149000, "year"),
]


async def _stripe_get(path: str, params: list) -> Dict[str, Any]:
    """GET from Stripe with repeated-key params (lookup_keys[] etc.)."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(f"{STRIPE_API_BASE}{path}",
                        auth=(_stripe_key(), ""), params=params,
                        headers=_stripe_headers())
    if r.status_code >= 400:
        logger.error(f"Stripe GET {path} {r.status_code}: {r.text[:300]}")
        raise HTTPException(status_code=r.status_code,
                            detail=f"Stripe error: {r.text[:200]}")
    return r.json()


@router.post("/bootstrap-prices")
async def bootstrap_prices(_owner=Depends(require_owner)):
    """Create the locked pricing catalog (4 products, 8 recurring
    prices, the MINISTRY20 promo) in Stripe. Owner-only; safe to
    re-run — existing lookup_keys are reused, never duplicated."""
    if not os.environ.get("STRIPE_SECRET_KEY", "").strip():
        raise HTTPException(409, "STRIPE_SECRET_KEY is not set on the server.")

    # 1. What already exists, by lookup key.
    existing: Dict[str, Dict[str, Any]] = {}
    params = [("lookup_keys[]", lk) for (_e, lk, _n, _a, _i) in BOOTSTRAP_CATALOG]
    params.append(("limit", "100"))
    for price in (await _stripe_get("/prices", params)).get("data", []):
        if price.get("lookup_key"):
            existing[price["lookup_key"]] = price

    # 2. Existing products by exact name, so a partial earlier run (or a
    #    hand-made product) is reused rather than duplicated.
    products_by_name: Dict[str, str] = {}
    products_name_by_id: Dict[str, str] = {}
    prods = await _stripe_get("/products", [("active", "true"), ("limit", "100")])
    for prod in prods.get("data", []):
        products_by_name.setdefault(prod.get("name") or "", prod["id"])
        products_name_by_id[prod["id"]] = prod.get("name") or ""

    env: Dict[str, str] = {}
    created: list = []
    reused: list = []
    renamed: list = []
    for env_key, lookup_key, product_name, amount, interval in BOOTSTRAP_CATALOG:
        price = existing.get(lookup_key)
        if price:
            env[env_key] = price["id"]
            reused.append(lookup_key)
            # A catalog rename must reach the LIVE product on re-run —
            # the checkout page shows this name. Price ids never change,
            # so reused prices would otherwise pin the old name forever.
            prod_id = str(price.get("product") or "")
            if prod_id and products_name_by_id.get(prod_id, product_name) != product_name:
                await _stripe_post(f"/products/{prod_id}", {"name": product_name})
                products_name_by_id[prod_id] = product_name
                renamed.append(product_name)
            continue
        product_id = products_by_name.get(product_name)
        if not product_id:
            prod = await _stripe_post("/products", {"name": product_name})
            product_id = prod["id"]
            products_by_name[product_name] = product_id
        price = await _stripe_post("/prices", {
            "product": product_id,
            "currency": "usd",
            "unit_amount": amount,
            "recurring": {"interval": interval},
            "lookup_key": lookup_key,
            "nickname": lookup_key,
        })
        env[env_key] = price["id"]
        created.append(lookup_key)

    # 3. MINISTRY20 — 20% off forever for churches/nonprofits. NON-FATAL:
    #    the catalog + env block must come back even if the promo step
    #    trips (2026-07-21: newer Stripe API versions renamed the
    #    promotion_codes `coupon` param to `promotion` — try modern
    #    shape first, fall back to legacy).
    promo_state = "reused"
    try:
        promos = await _stripe_get("/promotion_codes", [("code", "MINISTRY20"), ("limit", "1")])
        if not promos.get("data"):
            # Reuse an existing matching coupon (e.g. from a prior run
            # that failed at the promo-code step) before creating one.
            coupon_id = None
            for cp in (await _stripe_get("/coupons", [("limit", "100")])).get("data", []):
                if cp.get("name") == "Ministry & Nonprofit" and cp.get("percent_off") == 20:
                    coupon_id = cp["id"]
                    break
            if not coupon_id:
                coupon = await _stripe_post("/coupons", {
                    "percent_off": 20, "duration": "forever",
                    "name": "Ministry & Nonprofit",
                })
                coupon_id = coupon["id"]
            try:
                await _stripe_post("/promotion_codes", {
                    "code": "MINISTRY20",
                    "promotion": {"type": "coupon", "coupon": coupon_id},
                })
            except HTTPException:
                await _stripe_post("/promotion_codes", {
                    "code": "MINISTRY20", "coupon": coupon_id,
                })
            promo_state = "created"
    except HTTPException as e:
        promo_state = f"failed: {str(e.detail)[:140]}"

    env["STRIPE_PRICE_ID_DEFAULT"] = env.get("STRIPE_PRICE_ID_PROFESSIONAL", "")
    env["FOUNDER_SEAT_LIMIT"] = (os.environ.get("FOUNDER_SEAT_LIMIT") or "50").strip()
    railway_block = "\n".join(f"{k}={v}" for k, v in env.items() if v)
    # Which of these differ from the running env (i.e. still need Railway)?
    env_pending = [k for k, v in env.items()
                   if v and (os.environ.get(k) or "").strip() != v]
    return {"ok": True, "env": env, "railway_block": railway_block,
            "created": created, "reused": reused, "renamed": renamed,
            "ministry_promo": promo_state, "env_pending": env_pending}


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
            if business_id:
                import event_spine
                event_spine.emit("subscription_updated", business_id,
                                 {"stripe_event": event_type,
                                  "status": obj.get("status")},
                                 source="stripe_webhook")
        elif event_type == "invoice.payment_failed":
            await _handle_invoice_payment_failed(obj, business_id)
            if business_id:
                import event_spine
                event_spine.emit("subscription_updated", business_id,
                                 {"stripe_event": event_type,
                                  "status": "past_due"},
                                 source="stripe_webhook")
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
                    else:
                        import event_spine
                        event_spine.emit("credits_granted", business_id,
                                         {"credit_pack": meta.get("credit_pack") or ""},
                                         source="stripe_webhook")
                elif not business_id:
                    error_msg = "credit_pack session missing business_id"
            # Subscription checkouts: the subsequent
            # customer.subscription.created carries the real state —
            # this event stays audit-only for those, EXCEPT the Meta
            # Conversions signal: this is the one event carrying the
            # customer's email AND what the checkout charged, which is
            # exactly what ad optimization needs (growth arc Rung 2).
            elif obj.get("mode") == "subscription":
                try:
                    import asyncio
                    import meta_capi
                    if meta_capi.configured():
                        _cap_email = (obj.get("customer_details") or {}).get("email")
                        if _cap_email:
                            asyncio.create_task(meta_capi.send_event(
                                "Subscribe", email=_cap_email,
                                event_id=obj.get("id"),
                                value_cents=obj.get("amount_total") or 0,
                                currency=obj.get("currency") or "usd"))
                except Exception as _cap_e:
                    logger.warning(f"capi subscribe schedule failed: {_cap_e}")
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
                    import event_spine
                    event_spine.emit("credits_granted", business_id,
                                     {"credit_pack": meta.get("credit_pack") or ""},
                                     source="stripe_webhook")
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
