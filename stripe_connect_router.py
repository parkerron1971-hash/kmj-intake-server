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
    """Stripe webhook receiver. Verifies signature first; only then
    parses + dispatches.

    PR 1 ships: signature verification, account.updated,
    account.application.deauthorized.

    PR 2/3 add the payment_intent.*, checkout.session.*, invoice.*,
    charge.* handlers (gated by the pre-pay flow and the
    Invoices/Refunds surfaces)."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature") or ""

    if not verify_webhook_signature(payload, sig_header):
        logger.warning("webhook signature verification failed")
        # Stripe expects 400 on signature failure so it'll retry with
        # backoff. A 4xx response prevents duplicate delivery via the
        # success-path retry queue.
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
    logger.info(
        f"webhook {evt_type} id={evt_id} account={account_id} "
        f"livemode={event.get('livemode')}"
    )

    try:
        if evt_type == "account.updated":
            _handle_account_updated(obj)
        elif evt_type == "account.application.deauthorized":
            # Stripe-side disconnect (practitioner revoked from Stripe
            # dashboard rather than our UI).
            _handle_account_deauthorized(obj, account_id)
        # All other event types are recorded in logs only at PR 1; the
        # specific handlers land alongside the surfaces in PR 2/3.
    except Exception as e:
        logger.warning(f"webhook handler error for {evt_type} id={evt_id}: {e}")
        # Still return 200 — Stripe will not retry a successful POST.
        # The event landed in our logs, so we can replay manually.
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


# ─── Tiny helpers ────────────────────────────────────────────────────


def _url_escape(s: str) -> str:
    from urllib.parse import quote
    return quote(s[:200], safe="")
