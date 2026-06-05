"""
stripe_connect_helpers.py — Phase D.4 PR 1.

Thin httpx layer over Stripe's Connect + webhook API. Follows the same
no-SDK-dependency pattern as stripe_proxy.py (raw HTTP, platform-key
auth, Stripe-Account header for connected-account scoping).

Functions:
  oauth_url(state, return_url)              -> Stripe Connect OAuth URL
  exchange_oauth_code(code)                 -> {stripe_user_id, livemode, ...}
  fetch_account(stripe_account_id)          -> /v1/accounts/{id}
  deauthorize_account(stripe_account_id)    -> /v1/oauth/deauthorize
  verify_webhook_signature(payload, sig)    -> bool (HMAC)
  is_live_mode()                            -> derived from sk_live_ prefix

All raise RuntimeError on misconfig (missing env vars) and let HTTP
errors propagate so the calling router can translate to FastAPI
HTTPException with the right status.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("stripe_connect_helpers")

STRIPE_API_BASE = "https://api.stripe.com/v1"
STRIPE_CONNECT_AUTH_URL = "https://connect.stripe.com/oauth/authorize"

# Stripe webhook signature window — Stripe recommends 5 minutes.
WEBHOOK_TOLERANCE_SECONDS = 300

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)


# ─── Env accessors ───────────────────────────────────────────────────


def _secret_key() -> str:
    k = os.environ.get("STRIPE_SECRET_KEY") or ""
    if not k:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    return k


def _client_id() -> str:
    cid = os.environ.get("STRIPE_CONNECT_CLIENT_ID") or ""
    if not cid:
        raise RuntimeError("STRIPE_CONNECT_CLIENT_ID is not configured")
    return cid


def _webhook_secret() -> str:
    ws = os.environ.get("STRIPE_WEBHOOK_SECRET") or ""
    if not ws:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured")
    return ws


def is_live_mode() -> bool:
    """Derive test/live mode from the secret-key prefix. Brief is
    explicit: no separate STRIPE_ENVIRONMENT env var."""
    return (os.environ.get("STRIPE_SECRET_KEY") or "").startswith("sk_live_")


# ─── OAuth flow ──────────────────────────────────────────────────────


def oauth_url(state: str, return_url: Optional[str] = None) -> str:
    """Build the Stripe Connect OAuth authorization URL.

    `state` is a CSRF token the caller generated + stored server-side
    (see stripe_connect_router._issue_state). `return_url` is optional;
    Stripe ignores it if redirect_uri is set in the platform Connect
    settings (which it is — the brief lists the callback URL as
    pre-registered). We still pass redirect_uri here so test-mode env
    variations don't drift."""
    params = {
        "response_type": "code",
        "client_id": _client_id(),
        "scope": "read_write",
        "state": state,
    }
    if return_url:
        params["redirect_uri"] = return_url
    return f"{STRIPE_CONNECT_AUTH_URL}?{urlencode(params)}"


async def exchange_oauth_code(code: str) -> Dict[str, Any]:
    """Exchange an OAuth `code` from the callback for connected-account
    credentials. Returns Stripe's full response dict; key field is
    `stripe_user_id` (the acct_... id)."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{STRIPE_API_BASE}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
            },
            auth=(_secret_key(), ""),
        )
    if resp.status_code >= 400:
        logger.warning(
            f"oauth/token failed: {resp.status_code} {resp.text[:300]}"
        )
        raise RuntimeError(
            f"stripe oauth exchange failed: {resp.status_code} {resp.text[:200]}"
        )
    return resp.json()


# ─── Connected-account ops ───────────────────────────────────────────


async def fetch_account(stripe_account_id: str) -> Dict[str, Any]:
    """GET /v1/accounts/{id} using the platform key. Returns the
    account dict so callers can surface charges_enabled,
    payouts_enabled, requirements, etc."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(
            f"{STRIPE_API_BASE}/accounts/{stripe_account_id}",
            auth=(_secret_key(), ""),
        )
    if resp.status_code == 404:
        return {}
    if resp.status_code >= 400:
        logger.warning(
            f"accounts/{stripe_account_id} fetch failed: "
            f"{resp.status_code} {resp.text[:300]}"
        )
        raise RuntimeError(
            f"stripe account fetch failed: {resp.status_code} {resp.text[:200]}"
        )
    return resp.json()


async def deauthorize_account(stripe_account_id: str) -> Dict[str, Any]:
    """POST /v1/oauth/deauthorize — revokes the platform's access to
    the connected account. Returns Stripe's response (which contains
    the same stripe_user_id we passed in)."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{STRIPE_API_BASE}/oauth/deauthorize",
            data={
                "client_id": _client_id(),
                "stripe_user_id": stripe_account_id,
            },
            auth=(_secret_key(), ""),
        )
    if resp.status_code == 404:
        # Already deauthorized or never linked. Idempotent in our DB.
        return {"stripe_user_id": stripe_account_id, "already_deauthorized": True}
    if resp.status_code >= 400:
        logger.warning(
            f"deauthorize {stripe_account_id} failed: "
            f"{resp.status_code} {resp.text[:300]}"
        )
        raise RuntimeError(
            f"stripe deauthorize failed: {resp.status_code} {resp.text[:200]}"
        )
    return resp.json()


# ─── Webhook signature verification ──────────────────────────────────


def verify_webhook_signature(
    payload: bytes,
    sig_header: str,
    secret: Optional[str] = None,
    tolerance: int = WEBHOOK_TOLERANCE_SECONDS,
    now: Optional[int] = None,
) -> bool:
    """Verify a Stripe-Signature header per Stripe's spec.

    The header looks like: `t=1614270000,v1=abc...,v0=...`. We compute
    HMAC-SHA256 over `{t}.{payload}` using the webhook secret and
    compare to the v1 signature with constant-time equality.

    Returns True when signature is valid AND within the tolerance
    window. Returns False on any failure (malformed header, mismatch,
    stale timestamp, missing config) — never raises."""
    if not sig_header or not payload:
        return False
    try:
        ws_secret = secret or _webhook_secret()
    except RuntimeError:
        return False

    try:
        parts = dict(
            kv.split("=", 1) for kv in sig_header.split(",") if "=" in kv
        )
    except Exception:
        return False

    t_raw = parts.get("t")
    v1 = parts.get("v1")
    if not t_raw or not v1:
        return False
    try:
        t = int(t_raw)
    except ValueError:
        return False

    current_now = int(now if now is not None else time.time())
    if abs(current_now - t) > tolerance:
        return False

    signed_payload = f"{t}.".encode("utf-8") + payload
    expected = hmac.new(
        ws_secret.encode("utf-8"),
        msg=signed_payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, v1)
