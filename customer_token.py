"""
customer_token.py — HMAC-signed tokens for customer-facing widget access.

Phase C.1 introduces customer-facing widgets backed by signed URLs (no
Supabase auth account for customers). This module is the auth substrate:

  - issue_customer_token(business_id, customer_id) → opaque "<b64>.<sig>"
  - verify_customer_token(token) → dict claims, or None if invalid
  - require_customer_token FastAPI Depends — enforces the 4-step pattern:
      1. Signature + expiration valid
      2. claims['biz'] == path business_id (cross-tenant block)
      3. business_customers row still exists (revocation = row delete)
      4. Yields CustomerContext to the handler

Token format:
  <payload_b64>.<sig_b64>
where payload_b64 is urlsafe-b64 of the JSON {biz, cus, iat, exp} and
sig_b64 is urlsafe-b64 of HMAC-SHA256(secret, payload_b64).

Security defaults (per Phase C.1 security design, ruled by user):
  - TTL: 90 days. Customer links sticky-but-not-forever; expired
    tokens hit /widgets/request-fresh-link (rate-limited).
  - Constant-time signature comparison via hmac.compare_digest.
  - Single global secret from CUSTOMER_TOKEN_SECRET env var.
    TODO(phase-c-x): per-business token secrets before first real
    practitioner goes live. Rotation of the global secret invalidates
    all customer links across all businesses; per-business secrets
    contain the blast radius.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, Request

import billing_context
import sb_clients

logger = logging.getLogger("customer_token")

_SECRET_ENV_KEY = "CUSTOMER_TOKEN_SECRET"
TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days


def _secret() -> bytes:
    s = os.environ.get(_SECRET_ENV_KEY, "").strip()
    if not s:
        raise RuntimeError(
            f"{_SECRET_ENV_KEY} not configured — set in Railway env before "
            f"any customer-facing widget endpoint can run"
        )
    return s.encode("utf-8")


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def issue_customer_token(
    business_id: str,
    customer_id: str,
    ttl_seconds: int = TOKEN_TTL_SECONDS,
) -> str:
    """Mint an opaque signed token binding (business_id, customer_id).
    Caller is responsible for ensuring customer_id refers to a real
    business_customers row before issuing."""
    now = int(time.time())
    payload = {
        "biz": str(business_id),
        "cus": str(customer_id),
        "iat": now,
        "exp": now + int(ttl_seconds),
    }
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    sig = hmac.new(_secret(), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def verify_customer_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify signature + expiration. Returns claims dict on success, None
    on any failure (bad format, bad signature, expired). Does NOT verify
    the customer row still exists — that's step 3 of require_customer_token."""
    if not isinstance(token, str) or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError:
        return None
    expected_sig = hmac.new(_secret(), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(expected_sig, actual_sig):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None
    if not payload.get("biz") or not payload.get("cus"):
        return None
    return payload


# ─────────────────────────────────────────────────────────────────────
# FastAPI dependency: the 4-step verify pattern, single source of truth
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CustomerContext:
    """Yielded by require_customer_token. Handlers act on these fields
    instead of reading the raw token / claims dict."""
    business_id: str
    customer_id: str
    customer_row: Dict[str, Any]


def _extract_token(request: Request) -> Optional[str]:
    """Token may arrive in:
      - Authorization: Bearer <token>   (preferred for fetch/embed)
      - ?token=<token>                  (query param for hosted links)
      - {"token": "..."} in JSON body   (POST flows)
    Returns the first non-empty source."""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    q = request.query_params.get("token")
    if q:
        return q.strip()
    # Body is parsed by FastAPI separately; we rely on body-token through
    # query / header for the dependency. Endpoints that take token in JSON
    # body should accept it as a Pydantic field and validate explicitly.
    return None


def require_customer_token(business_id: str):
    """Returns a FastAPI dependency callable that enforces the 4-step
    pattern for endpoints scoped to /widgets/.../{business_id}/.... The
    factory captures the path business_id from the route signature, then
    the dependency verifies the token's biz claim matches it.

    Usage:
        @router.post("/widgets/booking/{business_id}/book")
        def book(business_id: str, ctx: CustomerContext = Depends(
            require_customer_token_factory  # see note below
        ), ...):
            # ctx.business_id, ctx.customer_id, ctx.customer_row available
            ...

    Note: FastAPI dependencies see path params via their function signature.
    The simpler shape is to make this a normal dependency that itself
    declares business_id as a path param. See require_customer_token_dep
    below for the actual callable.
    """
    raise NotImplementedError("use require_customer_token_dep instead")


def require_customer_token_dep(
    business_id: str,
    request: Request,
) -> CustomerContext:
    """FastAPI dependency — the 4-step pattern, single source of truth.

    Step 1: Verify token signature + expiration.
    Step 2: Cross-tenant check — claims.biz == path business_id.
    Step 3: Reload customer row to confirm it still exists (revocation = row delete).
    Step 4: Yield CustomerContext.

    Any failure raises HTTPException with the appropriate code. No way
    to bypass any step — handlers can't even see the raw token.
    """
    # Step 1
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="missing customer token")
    claims = verify_customer_token(token)
    if not claims:
        raise HTTPException(status_code=401, detail="invalid or expired customer token")

    # Step 2
    if str(claims.get("biz")) != str(business_id):
        # Don't echo claim contents in the error — would leak that the
        # token was valid for some other business.
        raise HTTPException(status_code=403, detail="token / business mismatch")

    # Step 3 — reload via service-role (bypasses RLS; we already verified
    # the binding cryptographically).
    customer_id = str(claims["cus"])
    rows = sb_clients.sb_get_as_service(
        f"/business_customers?id=eq.{customer_id}"
        f"&business_id=eq.{business_id}&limit=1&select=*"
    ) or []
    if not rows:
        raise HTTPException(status_code=403, detail="customer revoked")

    # Step 3b — WHOSE BILL THE AI SPEND ON THIS REQUEST LANDS ON.
    #
    # Until this line, billing_context.set_current() was called in four
    # places and not one of them was a client path. So any paid model
    # call reached through a client credential logged api_usage with
    # business_id NULL — and spend_guard is explicit about what that
    # means: unattributed spend "counts toward the platform ceiling
    # only; it cannot trip anyone's per-tenant one."
    #
    # That is the exact failure the two-ceiling design exists to
    # prevent. The per-business ceiling stops a runaway tenant and
    # leaves everyone else working; the platform ceiling going down
    # takes Chief out for every paying practitioner at once. A
    # client-facing surface whose spend the per-tenant guard structurally
    # cannot see is a hole straight through the middle of that, and it
    # is open today — the booking widgets already run.
    #
    # Placed AFTER step 3 and never before, matching business_access:
    # bookkeeping follows authorization, it does not grant it. A caller
    # who is refused at step 1, 2 or 3 must not be able to name the
    # tenant a later api_usage row is attributed to.
    #
    # Non-fatal by construction — set_current swallows its own errors,
    # because attribution failing must never fail the work being
    # attributed.
    billing_context.set_current(str(business_id))

    # Step 4
    return CustomerContext(
        business_id=str(business_id),
        customer_id=customer_id,
        customer_row=rows[0],
    )
