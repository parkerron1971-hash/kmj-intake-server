"""
stripe_connect_router.py — Phase D.4 PR 1 endpoints.

Practitioner-facing Connect onboarding + the Stripe webhook receiver:

  POST /payments/stripe-connect/start
       Owner-gated. Issues a one-shot state CSRF token, persists it
       with business_id, returns the Stripe Connect OAuth URL the
       frontend should redirect to.

  GET  /payments/stripe-connect/callback
       Stripe-initiated. Exchanges code -> stripe_user_id, validates
       state, writes stripe_account_id onto businesses, redirects the
       practitioner back to the app's Payments tab.

  POST /payments/stripe-connect/disconnect
       Owner-gated. Deauthorizes the connected account + nulls the
       column.

  GET  /payments/stripe-connect/status?business_id=...
       Owner-gated. Returns connection state + Stripe-side account
       summary (charges_enabled, payouts_enabled, requirements).

  POST /payments/stripe/webhook
       Stripe-initiated. Verifies Stripe-Signature, dispatches the 9
       subscribed events. PR 1 lands signature verification + the
       account.* handlers; the payment_intent.* / checkout.session.* /
       invoice.* / charge.* event handlers ship in PR 2/3 as the
       data tabs and pre-pay flow land.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

import sb_clients
from auth_supabase import AuthedUser, require_user
from stripe_connect_helpers import (
    deauthorize_account,
    exchange_oauth_code,
    fetch_account,
    is_live_mode,
    oauth_url,
    verify_webhook_signature,
)

logger = logging.getLogger("stripe_connect_router")

router = APIRouter(prefix="/payments", tags=["payments"])

# ─── Two distinct URLs in the OAuth flow (don't conflate) ────────────
#
# STRIPE_CALLBACK_URL is the redirect_uri Stripe sees during the OAuth
#   handshake. It MUST exactly match a URI registered in the Stripe
#   Connect platform settings — Stripe validates this server-side and
#   rejects the request with "Invalid redirect URI" if it doesn't.
#   This is OUR backend's /payments/stripe-connect/callback endpoint
#   (where Stripe sends ?code=...&state=... after the practitioner
#   approves the connection).
#
# FRONTEND_SUCCESS_URL / FRONTEND_ERROR_URL are where OUR callback
#   handler bounces the practitioner AFTER it has exchanged the code +
#   persisted stripe_account_id. Stripe never sees these URLs — they
#   live entirely in the post-exchange redirect step.
#
# This separation was the PR 1 v1 bug: redirect_uri was set to the
# frontend URL, which Stripe rejected because that URL isn't (and
# shouldn't be) registered as a Connect OAuth callback.
STRIPE_CALLBACK_URL = os.environ.get(
    "STRIPE_CONNECT_CALLBACK_URL",
    "https://kmj-intake-server-production.up.railway.app/payments/stripe-connect/callback",
)
FRONTEND_SUCCESS_URL = os.environ.get(
    "STRIPE_CONNECT_RETURN_URL",  # env-var name kept for back-compat
    "https://app.solutionist.studio/?payments=connected",
)
FRONTEND_ERROR_URL = os.environ.get(
    "STRIPE_CONNECT_RETURN_URL_ERROR",
    "https://app.solutionist.studio/?payments=error",
)

# One-shot CSRF state cache. Memory-only — Stripe round-trips are
# seconds, not minutes; if Railway redeploys mid-flow we just ask the
# practitioner to retry. Kept tiny.
_STATE_TTL_SECONDS = 600
_state_cache: Dict[str, Dict[str, Any]] = {}


def _issue_state(business_id: str) -> str:
    """Generate + remember a CSRF state token tied to one business."""
    token = secrets.token_urlsafe(32)
    _state_cache[token] = {
        "business_id": business_id,
        "expires_at": time.time() + _STATE_TTL_SECONDS,
    }
    _gc_state()
    return token


def _consume_state(token: str) -> Optional[str]:
    """Validate + consume a state token. Returns the bound business_id
    or None on miss/expiry."""
    entry = _state_cache.pop(token, None)
    if not entry:
        return None
    if entry["expires_at"] < time.time():
        return None
    return entry["business_id"]


def _gc_state() -> None:
    """Drop expired entries."""
    now = time.time()
    expired = [k for k, v in _state_cache.items() if v["expires_at"] < now]
    for k in expired:
        _state_cache.pop(k, None)


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,owner_id,stripe_account_id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


# ─── OAuth start ─────────────────────────────────────────────────────


@router.post("/stripe-connect/start")
def stripe_connect_start(
    payload: Dict[str, Any],
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Begin the Stripe Connect OAuth flow for `business_id`.

    Body: { business_id: str }
    Returns: { url, state, live_mode }
    The frontend redirects the practitioner to `url`.
    """
    business_id = (payload or {}).get("business_id")
    if not business_id:
        raise HTTPException(400, "business_id required")
    biz = _require_owner(str(business_id), user)

    if biz.get("stripe_account_id"):
        # Already connected. Frontend should send to status, not start.
        raise HTTPException(409, "stripe account already connected")

    state = _issue_state(str(business_id))
    try:
        # The redirect_uri Stripe sees is OUR backend callback. After
        # Stripe redirects there, the callback handler bounces the
        # practitioner to FRONTEND_SUCCESS_URL.
        url = oauth_url(state=state, return_url=STRIPE_CALLBACK_URL)
    except RuntimeError as e:
        logger.warning(f"stripe-connect/start misconfig: {e}")
        raise HTTPException(503, "payments not configured")
    return {
        "ok": True,
        "url": url,
        "state": state,
        "live_mode": is_live_mode(),
    }


# ─── OAuth callback ──────────────────────────────────────────────────


@router.get("/stripe-connect/callback")
async def stripe_connect_callback(request: Request) -> RedirectResponse:
    """Stripe redirects here with ?code=...&state=... (success) or
    ?error=...&error_description=... (cancel / decline).

    We exchange the code, persist stripe_account_id, and redirect the
    practitioner back to the studio app's Payments tab. Errors land on
    a separate error URL with the message in the query string."""
    params = dict(request.query_params)
    if params.get("error"):
        # Practitioner cancelled or Stripe declined — bounce back with msg.
        err = params.get("error_description") or params.get("error") or "stripe error"
        return RedirectResponse(
            url=f"{FRONTEND_ERROR_URL}&msg={_url_escape(err)}",
            status_code=302,
        )

    code = params.get("code") or ""
    state = params.get("state") or ""
    if not code or not state:
        return RedirectResponse(
            url=f"{FRONTEND_ERROR_URL}&msg=missing_code_or_state",
            status_code=302,
        )

    business_id = _consume_state(state)
    if not business_id:
        return RedirectResponse(
            url=f"{FRONTEND_ERROR_URL}&msg=invalid_or_expired_state",
            status_code=302,
        )

    try:
        oauth_resp = await exchange_oauth_code(code)
    except Exception as e:
        logger.warning(f"oauth exchange failed for biz={business_id}: {e}")
        return RedirectResponse(
            url=f"{FRONTEND_ERROR_URL}&msg=oauth_exchange_failed",
            status_code=302,
        )

    stripe_account_id = (oauth_resp or {}).get("stripe_user_id")
    if not stripe_account_id:
        logger.warning(f"oauth resp missing stripe_user_id for biz={business_id}")
        return RedirectResponse(
            url=f"{FRONTEND_ERROR_URL}&msg=no_account_id",
            status_code=302,
        )

    # Persist to businesses.stripe_account_id.
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}",
        {"stripe_account_id": stripe_account_id},
    )
    logger.info(
        f"stripe connected: biz={business_id[:8]} acct={stripe_account_id} "
        f"livemode={oauth_resp.get('livemode')}"
    )
    return RedirectResponse(
        url=f"{FRONTEND_SUCCESS_URL}&biz={business_id}",
        status_code=302,
    )


# ─── Disconnect ──────────────────────────────────────────────────────


@router.post("/stripe-connect/disconnect")
async def stripe_connect_disconnect(
    payload: Dict[str, Any],
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    business_id = (payload or {}).get("business_id")
    if not business_id:
        raise HTTPException(400, "business_id required")
    biz = _require_owner(str(business_id), user)
    acct = biz.get("stripe_account_id")
    if not acct:
        return {"ok": True, "already_disconnected": True}

    # Best-effort revoke. We still null the local column even if Stripe
    # returns 404 — the practitioner asked to disconnect, and a
    # mismatch leaves them in a worse state.
    try:
        await deauthorize_account(acct)
    except Exception as e:
        logger.warning(
            f"stripe deauthorize failed for biz={business_id} acct={acct}: {e}"
        )

    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}",
        {"stripe_account_id": None},
    )
    return {"ok": True, "business_id": business_id, "disconnected": True}


# ─── Status ──────────────────────────────────────────────────────────


@router.get("/stripe-connect/status")
async def stripe_connect_status(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    biz = _require_owner(business_id, user)
    acct_id = biz.get("stripe_account_id")
    if not acct_id:
        return {
            "ok": True,
            "connected": False,
            "live_mode": is_live_mode(),
        }

    # Stripe-side state. Wrapped — if Stripe is down we still report
    # connected=True so the practitioner UI doesn't flap.
    account: Dict[str, Any] = {}
    try:
        account = await fetch_account(acct_id)
    except Exception as e:
        logger.warning(
            f"stripe account fetch failed for biz={business_id} acct={acct_id}: {e}"
        )

    return {
        "ok": True,
        "connected": True,
        "live_mode": is_live_mode(),
        "stripe_account_id": acct_id,
        "charges_enabled": account.get("charges_enabled"),
        "payouts_enabled": account.get("payouts_enabled"),
        "details_submitted": account.get("details_submitted"),
        "requirements_due": list(((account.get("requirements") or {}).get("currently_due") or [])),
        "email": account.get("email"),
        "country": account.get("country"),
        "default_currency": account.get("default_currency"),
    }


# ─── Webhook ─────────────────────────────────────────────────────────


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request) -> JSONResponse:
    """Stripe webhook receiver. Verifies signature, deduplicates via
    stripe_webhook_events, dispatches to the right handler.

    PR 3 events handled (in addition to PR 1's account.* pair):
      checkout.session.completed     — booking + invoice payment success
      payment_intent.succeeded       — second-channel success signal
      payment_intent.payment_failed  — surface failed payment
      invoice.paid                   — mirror Stripe invoice -> local
      invoice.payment_failed         — mirror Stripe invoice -> local
      charge.refunded                — record refund + flip flag
      charge.dispute.created         — populate stripe_disputes_cache

    Idempotency: each event lands as one row in stripe_webhook_events
    keyed by event.id. If the row already exists with processed_ok=true,
    we return 200 immediately without re-dispatching. Stripe retries
    are therefore cheap + safe."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature") or ""

    if not verify_webhook_signature(payload, sig_header):
        logger.warning("webhook signature verification failed")
        return JSONResponse({"error": "bad_signature"}, status_code=400)

    try:
        event = json.loads(payload.decode("utf-8"))
    except Exception as e:
        logger.warning(f"webhook payload not JSON: {e}")
        return JSONResponse({"error": "bad_payload"}, status_code=400)

    evt_type = event.get("type") or ""
    evt_id = event.get("id") or ""
    obj = (event.get("data") or {}).get("object") or {}
    account_id = event.get("account") or obj.get("account") or None
    livemode = bool(event.get("livemode"))
    logger.info(
        f"webhook {evt_type} id={evt_id} account={account_id} livemode={livemode}"
    )

    # ─── Idempotency check ─────────────────────────────────────────
    if evt_id:
        existing = sb_clients.sb_get_as_service(
            f"/stripe_webhook_events?id=eq.{evt_id}&select=id,processed_ok&limit=1"
        ) or []
        if existing and existing[0].get("processed_ok") is True:
            logger.info(f"webhook {evt_type} id={evt_id} already processed, skipping")
            return JSONResponse({"ok": True, "deduplicated": True})

        # Record receipt. Upsert-style: insert; if it already exists
        # (unprocessed retry) PostgREST returns 409 we tolerate.
        try:
            sb_clients.sb_post_as_service("/stripe_webhook_events", {
                "id": evt_id,
                "type": evt_type,
                "livemode": livemode,
                "account_id": account_id,
                "raw": event,
            })
        except Exception as e:
            # If unique-violation on retry, that's fine; we still dispatch.
            logger.info(f"webhook {evt_id} pre-insert {e!s}")

    # ─── Dispatch ──────────────────────────────────────────────────
    processed_ok = False
    processed_error: Optional[str] = None
    try:
        if evt_type == "account.updated":
            _handle_account_updated(obj)
        elif evt_type == "account.application.deauthorized":
            _handle_account_deauthorized(obj, account_id)
        elif evt_type == "checkout.session.completed":
            _handle_checkout_session_completed(obj)
        elif evt_type == "payment_intent.succeeded":
            _handle_payment_intent_succeeded(obj)
        elif evt_type == "payment_intent.payment_failed":
            _handle_payment_intent_failed(obj)
        elif evt_type == "invoice.paid":
            _handle_invoice_paid(obj)
        elif evt_type == "invoice.payment_failed":
            _handle_invoice_failed(obj)
        elif evt_type == "charge.refunded":
            _handle_charge_refunded(obj)
        elif evt_type == "charge.dispute.created":
            _handle_dispute_created(obj, account_id)
        else:
            # Unknown event types are still recorded in the
            # stripe_webhook_events table for replay; just no handler.
            pass
        processed_ok = True
    except Exception as e:
        processed_error = str(e)
        logger.warning(f"webhook handler error for {evt_type} id={evt_id}: {e}")

    # Record outcome.
    if evt_id:
        try:
            from datetime import datetime, timezone
            sb_clients.sb_patch_as_service(
                f"/stripe_webhook_events?id=eq.{evt_id}",
                {
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "processed_ok": processed_ok,
                    "processed_error": processed_error,
                },
            )
        except Exception as e:
            logger.warning(f"webhook outcome patch failed for {evt_id}: {e}")

    return JSONResponse({"ok": True, "received": evt_type})


def _handle_account_updated(account: Dict[str, Any]) -> None:
    """account.updated — typically fires when requirements / capability
    status changes. We persist a tiny status snapshot back to the
    business row so the Payments tab can reflect 'connected but
    requirements due' without a fresh API call every time the
    practitioner opens the surface."""
    stripe_acct_id = account.get("id")
    if not stripe_acct_id:
        return
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?stripe_account_id=eq.{stripe_acct_id}&select=id,settings&limit=1"
    ) or []
    if not biz_rows:
        return
    biz = biz_rows[0]
    settings = dict(biz.get("settings") or {})
    stripe_settings = dict(settings.get("stripe") or {})
    stripe_settings["last_account_event_at"] = int(time.time())
    stripe_settings["charges_enabled"] = account.get("charges_enabled")
    stripe_settings["payouts_enabled"] = account.get("payouts_enabled")
    stripe_settings["details_submitted"] = account.get("details_submitted")
    settings["stripe"] = stripe_settings
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{biz['id']}",
        {"settings": settings},
    )


def _handle_account_deauthorized(_obj: Dict[str, Any], account_id: Optional[str]) -> None:
    """Stripe-side disconnect — null our stripe_account_id so the
    Payments tab returns to the un-connected state."""
    if not account_id:
        return
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?stripe_account_id=eq.{account_id}&select=id&limit=1"
    ) or []
    if not biz_rows:
        return
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{biz_rows[0]['id']}",
        {"stripe_account_id": None},
    )


# ─── PR 3 event handlers (unified payment-source pattern) ──────────


def _metadata_source(obj: Dict[str, Any]) -> tuple:
    """Extract {source_type, source_id} from a Stripe object's metadata.
    Stripe propagates Checkout-Session metadata to payment_intent +
    charge when payment_intent_data.metadata is set at create-time."""
    md = obj.get("metadata") or {}
    return md.get("source_type"), md.get("source_id")


def _handle_checkout_session_completed(session: Dict[str, Any]) -> None:
    """A checkout session paid. Look up the source and mark it paid.
    For source_type='booking' → set module_entries.paid_at + ids.
    For source_type='invoice' → mark the existing-system invoices row paid."""
    if session.get("payment_status") != "paid":
        return
    source_type, source_id = _metadata_source(session)
    if not source_id:
        return
    pi_id = session.get("payment_intent")
    if source_type == "booking":
        # Barber-money: the session metadata carries payment_kind /
        # deposit_cents / tip_cents, and session.customer is the Stripe
        # Customer that setup_future_usage stored the card on — the
        # no-show charge path needs it recorded on the booking.
        _mark_booking_paid(
            source_id, payment_intent_id=pi_id, charge_id=None,
            metadata=session.get("metadata") or {},
            stripe_customer_id=session.get("customer"),
        )
    elif source_type == "invoice":
        _mark_invoice_paid(source_id)
    elif source_type == "order":
        # Arc 27 — store orders ride the same metadata pattern.
        from store_router import mark_order_paid
        mark_order_paid(source_id, payment_intent_id=pi_id, charge_id=None,
                        session=session)
        _emit_order_paid(source_id, pi_id)
    elif source_type == "product":
        # Academy Phase 3 — a payment-link purchase of a products row.
        # When the product is linked to a course, the buyer becomes a
        # contact (find-or-create on email) and is enrolled automatically.
        _handle_product_purchase(source_id, session)


def _handle_product_purchase(product_id: str, session: Dict[str, Any]) -> None:
    """Academy Phase 3 — auto-enrollment on course purchase.

    source_id == products.id. If one or more academy_courses rows link
    to this product, find-or-create the buyer as a contact from the
    checkout session's customer_details and insert enrollments. The
    unique (course_id, contact_id) constraint makes Stripe webhook
    retries idempotent — duplicate inserts fail cleanly and are logged
    at info. Non-course products keep today's behavior (no-op).
    Fail-soft throughout: a hiccup here must never 500 the webhook."""
    try:
        courses = sb_clients.sb_get_as_service(
            f"/academy_courses?product_id=eq.{product_id}"
            f"&select=id,business_id,title&limit=10"
        ) or []
        if not courses:
            return
        details = session.get("customer_details") or {}
        email = (details.get("email") or "").strip().lower()
        if not email:
            logger.warning(
                f"product purchase {product_id}: no buyer email on session — cannot enroll")
            return
        name = (details.get("name") or "").strip() or email.split("@")[0]
        from booking_widget_router import _find_or_create_contact
        for course in courses:
            biz_id = course.get("business_id")
            if not biz_id:
                continue
            try:
                contact_id = _find_or_create_contact(str(biz_id), name, email)
                sb_clients.sb_post_as_service("/academy_enrollments", {
                    "course_id": course["id"],
                    "business_id": biz_id,
                    "contact_id": contact_id,
                })
                logger.info(
                    f"academy: enrolled {email} in course '{course.get('title')}' "
                    f"({course['id']}) via product purchase {product_id}")
            except Exception as enroll_err:
                # Most common cause: already enrolled (unique constraint)
                # on a webhook retry — benign.
                logger.info(
                    f"academy: enrollment skipped for {email} on course "
                    f"{course.get('id')}: {enroll_err}")
    except Exception as e:
        logger.warning(f"product purchase handling failed (fail-soft): {e}")


def _handle_payment_intent_succeeded(pi: Dict[str, Any]) -> None:
    """Second-channel success signal. Stripe sometimes delivers this
    before checkout.session.completed; mark idempotently so whichever
    arrives first wins."""
    source_type, source_id = _metadata_source(pi)
    if not source_id or source_type not in ("booking", "order"):
        return
    md = pi.get("metadata") or {}
    if md.get("payment_kind") == "no_show_fee":
        # Barber-money: the no-show fee PI carries source_type='booking'
        # for the Charges tab, but it is NOT the service payment — it
        # must never flip paid_at. The charge endpoint already recorded
        # the fee state on the entry.
        logger.info(f"no-show fee PI succeeded for booking {source_id} (not a service payment)")
        return
    charges = ((pi.get("charges") or {}).get("data") or [])
    charge_id = charges[0].get("id") if charges else None
    if source_type == "order":
        from store_router import mark_order_paid
        mark_order_paid(source_id, payment_intent_id=pi.get("id"),
                        charge_id=charge_id, session=None)
        _emit_order_paid(source_id, pi.get("id"))
        return
    _mark_booking_paid(
        source_id, payment_intent_id=pi.get("id"), charge_id=charge_id,
        metadata=md,
        # The PI knows which payment method paid — recorded so the
        # no-show charge can reuse the exact card without a PM listing.
        payment_method_id=pi.get("payment_method"),
    )


def _emit_order_paid(order_id: str, payment_intent_id: Optional[str]) -> None:
    """Spine signal for a store-order payment. Stripe delivers success
    on two channels (checkout.session.completed AND
    payment_intent.succeeded) — dedupe against the events table so the
    order pays exactly one signal."""
    import event_spine
    already = sb_clients.sb_get_as_service(
        f"/events?event_type=eq.order_paid&data->>order_id=eq.{order_id}"
        f"&select=id&limit=1") or []
    if already:
        return
    rows = sb_clients.sb_get_as_service(
        f"/orders?id=eq.{order_id}&select=id,business_id,contact_id&limit=1") or []
    if not rows:
        return
    event_spine.emit("order_paid", rows[0].get("business_id"),
                     {"order_id": order_id, "payment_intent_id": payment_intent_id},
                     contact_id=rows[0].get("contact_id"), source="stripe_webhook")


def _handle_payment_intent_failed(pi: Dict[str, Any]) -> None:
    """For now: log only. Failed-payment UX comes in a later pass."""
    source_type, source_id = _metadata_source(pi)
    logger.info(
        f"payment_intent.payment_failed source={source_type}/{source_id}: "
        f"{((pi.get('last_payment_error') or {}).get('message')) or '(no error)'}"
    )


def _handle_invoice_paid(inv: Dict[str, Any]) -> None:
    """invoice.paid event from Stripe. PR 3a ruling: Solutionist's
    canonical invoicing path uses Payment Links via stripe_proxy,
    not Stripe-API Invoices. We don't expect this event in the
    current architecture; logged for visibility in case a future
    flow starts using it."""
    _, source_id = _metadata_source(inv)
    logger.info(
        f"invoice.paid id={inv.get('id')} source_id={source_id} "
        f"(not handled by PR 3a — Payment Link flow handles invoice "
        f"payment via checkout.session.completed metadata)"
    )


def _handle_invoice_failed(inv: Dict[str, Any]) -> None:
    """Log only — see _handle_invoice_paid for context."""
    logger.info(f"invoice.payment_failed id={inv.get('id')} (logged-only)")


def _mark_invoice_paid(invoice_id: str) -> None:
    """Mark an existing-system invoices row paid. Idempotent — only
    flips status when not already 'paid'.

    payment_method='stripe' is LOAD-BEARING for the books:
    gl_engine._is_non_stripe_payment() reads it to decide whether the
    payment debits 1150 Stripe Clearing (money in transit, cleared by
    the payout flow) or 1000 Cash. Without it, a Connect-checkout
    payment would post as direct cash and the clearing account would
    never see it — same pattern booking payments already follow."""
    rows = sb_clients.sb_get_as_service(
        f"/invoices?id=eq.{invoice_id}"
        f"&select=id,status,business_id,contact_id,invoice_number,total&limit=1"
    ) or []
    if not rows or rows[0].get("status") == "paid":
        return
    sb_clients.sb_patch_as_service(
        f"/invoices?id=eq.{invoice_id}",
        {"status": "paid", "paid_at": _now_iso(), "payment_method": "stripe"},
    )
    logger.info(f"invoice {invoice_id[:8]} marked paid via webhook")
    import event_spine
    inv = rows[0]
    event_spine.emit("invoice_paid_auto", inv.get("business_id"),
                     {"invoice_id": invoice_id,
                      "invoice_number": inv.get("invoice_number"),
                      "total": float(inv.get("total") or 0),
                      "payment_method": "stripe"},
                     contact_id=inv.get("contact_id"), source="stripe_webhook")

    # Practitioner-visible parity with the legacy payment-link rail
    # (stripe_proxy webhook): a payment notification + a contact-health
    # bump. Fail-soft — bookkeeping niceties never 500 the webhook.
    try:
        total = float(inv.get("total") or 0)
        contact_id = inv.get("contact_id")
        contact_name = "Client"
        if contact_id:
            crows = sb_clients.sb_get_as_service(
                f"/contacts?id=eq.{contact_id}&select=name&limit=1") or []
            if crows:
                contact_name = crows[0].get("name") or contact_name
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": inv.get("business_id"),
            "type": "success",
            "title": f"💰 Payment Received — ${total:,.2f}",
            "body": f"{contact_name} paid Invoice {inv.get('invoice_number')}.",
            "suggested_action": f"Thank {contact_name}",
            "status": "unread",
            "data": {
                "kind": "invoice_paid",
                "invoice_id": invoice_id,
                "invoice_number": inv.get("invoice_number"),
                "contact_id": contact_id,
                "contact_name": contact_name,
                "total": total,
            },
        })
        if contact_id:
            sb_clients.sb_patch_as_service(
                f"/contacts?id=eq.{contact_id}",
                {"health_score": 100, "last_interaction": _now_iso()},
            )
    except Exception as e:
        logger.warning(f"invoice-paid notification failed (fail-soft): {e}")


def _handle_charge_refunded(charge: Dict[str, Any]) -> None:
    """Charge was (partially or fully) refunded. Locate the linked
    source via metadata and record refund state.

    PR 3a ruling on invoice refund semantics: existing invoice keeps
    status='paid' (preserves the canonical lifecycle); refund details
    land in additive refund_amount_cents + refunded_at columns. Full
    refund vs partial is observable via amount_refunded == amount.
    """
    source_type, source_id = _metadata_source(charge)
    refunded_cents = int(charge.get("amount_refunded") or 0)
    refund_biz: Optional[str] = None

    if source_type == "booking" and source_id:
        # Mirror refunded total onto the booking row. We keep it in
        # data.refunded_amount_cents so we don't need another column.
        rows = sb_clients.sb_get_as_service(
            f"/module_entries?id=eq.{source_id}&select=data,business_id&limit=1"
        ) or []
        if not rows:
            return
        refund_biz = rows[0].get("business_id")
        data = dict(rows[0].get("data") or {})
        data["refunded_amount_cents"] = refunded_cents
        data["fully_refunded"] = bool(charge.get("refunded"))
        sb_clients.sb_patch_as_service(
            f"/module_entries?id=eq.{source_id}", {"data": data},
        )
    elif source_type == "invoice" and source_id:
        # PR 3a additive columns on existing invoices: status stays
        # 'paid'; refund_amount_cents + refunded_at carry the truth.
        rows = sb_clients.sb_get_as_service(
            f"/invoices?id=eq.{source_id}&select=business_id&limit=1") or []
        refund_biz = rows[0].get("business_id") if rows else None
        sb_clients.sb_patch_as_service(
            f"/invoices?id=eq.{source_id}",
            {
                "refund_amount_cents": refunded_cents,
                "refunded_at": _now_iso(),
            },
        )
    elif source_type == "order" and source_id:
        # Arc 27 — store orders: refund columns; status flips to
        # 'refunded' only on full refund (gl_engine reverses revenue).
        from store_router import record_order_refund
        rows = sb_clients.sb_get_as_service(
            f"/orders?id=eq.{source_id}&select=business_id&limit=1") or []
        refund_biz = rows[0].get("business_id") if rows else None
        record_order_refund(source_id, refunded_cents,
                            fully=bool(charge.get("refunded")))

    if refund_biz:
        import event_spine
        event_spine.emit("payment_refunded", refund_biz,
                         {"source_type": source_type, "source_id": source_id,
                          "refunded_cents": refunded_cents,
                          "fully_refunded": bool(charge.get("refunded"))},
                         source="stripe_webhook")


def _handle_dispute_created(dispute: Dict[str, Any], account_id: Optional[str]) -> None:
    """PR 3a: stripe_disputes_cache table dropped — disputes UI is
    deferred to PR 3b. Log only so the event still lands in
    stripe_webhook_events (the raw column preserves the full Stripe
    payload for replay when the disputes surface lands)."""
    logger.info(
        f"charge.dispute.created id={dispute.get('id')} "
        f"charge={dispute.get('charge')} reason={dispute.get('reason')} "
        f"account={account_id} (logged-only; UI in PR 3b)"
    )


def _int_or_none(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _mark_booking_paid(
    booking_id: str,
    *,
    payment_intent_id: Optional[str],
    charge_id: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
    stripe_customer_id: Optional[str] = None,
    payment_method_id: Optional[str] = None,
) -> None:
    """Idempotent: only sets paid_at if it's currently NULL.

    Barber-money: the two success channels each know something the other
    doesn't (session → customer id; PI → payment_method id), so the
    data-side facts (deposit state, tip, card-on-file refs) are merged
    EVEN when paid_at is already set — whichever event lands second
    still contributes its half."""
    rows = sb_clients.sb_get_as_service(
        f"/module_entries?id=eq.{booking_id}"
        f"&select=id,paid_at,business_id,contact_id,data&limit=1"
    ) or []
    if not rows:
        return
    row = rows[0]
    already_paid = bool(row.get("paid_at"))
    md = metadata or {}

    # ── Data-side facts (denormalized, like price_at_booking) ──
    data = dict(row.get("data") or {})
    updates: Dict[str, Any] = {}
    if stripe_customer_id and data.get("stripe_customer_id") != stripe_customer_id:
        updates["stripe_customer_id"] = stripe_customer_id
    if payment_method_id and data.get("stripe_payment_method_id") != payment_method_id:
        updates["stripe_payment_method_id"] = payment_method_id
    tip_cents = _int_or_none(md.get("tip_cents"))
    if tip_cents and not data.get("tip_cents"):
        updates["tip_cents"] = tip_cents
    if md.get("payment_kind") == "deposit" and not data.get("deposit_paid_at"):
        # Deposit-paid state; remainder_due derivable and denormalized.
        updates["deposit_paid_at"] = _now_iso()
        dep = _int_or_none(md.get("deposit_cents"))
        rem = _int_or_none(md.get("remainder_cents"))
        if dep is not None:
            updates["deposit_paid_cents"] = dep
        if rem is not None:
            updates["remainder_due_cents"] = rem
    if updates:
        sb_clients.sb_patch_as_service(
            f"/module_entries?id=eq.{booking_id}", {"data": {**data, **updates}})

    if already_paid:
        return
    patch: Dict[str, Any] = {"paid_at": _now_iso()}
    if charge_id:
        patch["stripe_charge_id"] = charge_id
    if payment_intent_id:
        patch["stripe_payment_intent_id"] = payment_intent_id
    sb_clients.sb_patch_as_service(
        f"/module_entries?id=eq.{booking_id}", patch,
    )
    kind = md.get("payment_kind") or "full"
    logger.info(f"booking {booking_id[:8]} marked paid via webhook (kind={kind})")
    import event_spine
    event_spine.emit("booking_paid", row.get("business_id"),
                     {"booking_id": booking_id, "payment_intent_id": payment_intent_id,
                      "payment_kind": kind,
                      **({"tip_cents": tip_cents} if tip_cents else {})},
                     contact_id=row.get("contact_id"), source="stripe_webhook")


# ─── Tiny helpers ────────────────────────────────────────────────────


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _from_unix(ts: Optional[int]) -> Optional[str]:
    if ts is None:
        return None
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _url_escape(s: str) -> str:
    from urllib.parse import quote
    return quote(s[:200], safe="")
