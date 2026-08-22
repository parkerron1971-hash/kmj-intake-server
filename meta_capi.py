"""
meta_capi.py — Meta (Facebook) Conversions API: server-side conversion
events. GROWTH ARC Rung 2.

WHY SERVER-SIDE: Meta's ad delivery optimizes toward whoever it can see
converting. Browser pixels get blocked, links get opened in in-app
browsers, and the signup finishes days after the ad click on another
device — the server is the only place that reliably knows a Lead,
CompleteRegistration, or Subscribe actually happened. Better signal in,
cheaper customers out.

WHAT LEAVES THE PROCESS: the email is SHA-256-hashed after Meta's
required normalization (trim + lowercase) — the raw address never goes
to Meta. Everything else sent (client IP, user agent, _fbp/_fbc cookie
values) exists to let Meta match the event to the ad click; an event
with no matchable user data is dropped here rather than sent as noise.

FAIL-SOFT: unconfigured (no META_PIXEL_ID / META_CAPI_ACCESS_TOKEN) is
a silent no-op, and a Graph API failure is a log line, never an error a
practitioner or visitor can see. Events fire via BackgroundTasks /
create_task AFTER the response — a marketing beacon must never slow a
signup down.

Env (see .env.example + platform_console.API_REGISTRY):
  META_PIXEL_ID          — the pixel/dataset id (also renders the
                           browser pixel on the marketing shell)
  META_CAPI_ACCESS_TOKEN — Conversions API access token, generated in
                           Events Manager → the pixel → Settings
  META_CAPI_TEST_CODE    — optional; routes events to Events Manager's
                           Test Events tab while set
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("meta_capi")

# Same Graph version the OAuth/publishing integration pins.
FB_GRAPH = "https://graph.facebook.com/v21.0"
HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)


def pixel_id() -> str:
    return (os.environ.get("META_PIXEL_ID") or "").strip()


def _token() -> str:
    return (os.environ.get("META_CAPI_ACCESS_TOKEN") or "").strip()


def configured() -> bool:
    return bool(pixel_id() and _token())


def _hash_email(email: str) -> str:
    """Meta's required normalization, then SHA-256."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def request_context(request: Any) -> Dict[str, Optional[str]]:
    """Match signals off a same-origin request (the marketing site):
    _fbp/_fbc cookies the pixel set, plus client IP + user agent.
    Never raises; absent pieces are simply None."""
    out: Dict[str, Optional[str]] = {
        "client_ip": None, "user_agent": None, "fbp": None, "fbc": None,
    }
    try:
        headers = getattr(request, "headers", None) or {}
        out["user_agent"] = headers.get("user-agent") or None
        # Railway sits behind a proxy — the visitor is the first hop of
        # x-forwarded-for, not request.client.
        fwd = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if fwd:
            out["client_ip"] = fwd
        elif getattr(request, "client", None):
            out["client_ip"] = getattr(request.client, "host", None)
        cookies = getattr(request, "cookies", None) or {}
        out["fbp"] = cookies.get("_fbp") or None
        out["fbc"] = cookies.get("_fbc") or None
    except Exception:
        pass
    return out


async def send_event(event_name: str, *,
                     email: Optional[str] = None,
                     event_id: Optional[str] = None,
                     event_source_url: Optional[str] = None,
                     client_ip: Optional[str] = None,
                     user_agent: Optional[str] = None,
                     fbp: Optional[str] = None,
                     fbc: Optional[str] = None,
                     value_cents: Optional[int] = None,
                     currency: str = "usd") -> bool:
    """Send one conversion event. Returns whether it was accepted;
    never raises. `event_id` should be the stable id of the thing that
    converted (lead id, business id, checkout session id) so a retry or
    a paired browser event deduplicates instead of double-counting."""
    if not configured():
        return False

    user_data: Dict[str, Any] = {}
    if email and "@" in email:
        user_data["em"] = [_hash_email(email)]
    if client_ip:
        user_data["client_ip_address"] = client_ip
    if user_agent:
        user_data["client_user_agent"] = user_agent
    if fbp:
        user_data["fbp"] = fbp
    if fbc:
        user_data["fbc"] = fbc
    if not user_data:
        # Nothing for Meta to match on — noise, not signal.
        return False

    event: Dict[str, Any] = {
        "event_name": event_name,
        "event_time": int(time.time()),
        "action_source": "website",
        "user_data": user_data,
    }
    if event_id:
        event["event_id"] = str(event_id)
    if event_source_url:
        event["event_source_url"] = event_source_url
    if value_cents is not None:
        event["custom_data"] = {
            "value": round(int(value_cents) / 100.0, 2),
            "currency": (currency or "usd").lower(),
        }

    payload: Dict[str, Any] = {"data": [event]}
    test_code = (os.environ.get("META_CAPI_TEST_CODE") or "").strip()
    if test_code:
        payload["test_event_code"] = test_code

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.post(
                f"{FB_GRAPH}/{pixel_id()}/events",
                params={"access_token": _token()},
                json=payload,
            )
        if r.status_code >= 400:
            logger.warning("capi %s rejected %s: %s",
                           event_name, r.status_code, r.text[:200])
            return False
        logger.info("capi %s sent (event_id=%s)", event_name, event_id)
        return True
    except Exception as e:
        logger.warning("capi %s error: %s", event_name, e)
        return False
