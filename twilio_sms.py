"""
twilio_sms.py — Twilio SMS: outbound send + inbound webhook.

Built to Kevin's spec (2026-07-04). Coexists with the Telnyx-backed
sms_service.py — this module is the Twilio rail; nothing else changes
until the routing layer decides which provider owns which traffic.

═══════════════════════════════════════════════════════════════════════
ENV (Railway) — never hardcoded, never sent to any client
═══════════════════════════════════════════════════════════════════════

    TWILIO_ACCOUNT_SID            AC…   (account)
    TWILIO_API_KEY_SID            SK…   (API key)
    TWILIO_API_KEY_SECRET               (API key secret)
    TWILIO_MESSAGING_SERVICE_SID  MG…   (Messaging Service — sender pool)
    TEST_SMS_TO                   +1…   (verified cell, E.164, test sends)
    TWILIO_AUTH_TOKEN                   (OPTIONAL but strongly recommended:
                                         inbound signature validation needs
                                         the ACCOUNT auth token — an API-key
                                         secret cannot validate webhooks.
                                         Until it's set, inbound requests are
                                         processed with a LOUD warning.)

═══════════════════════════════════════════════════════════════════════
ENDPOINTS
═══════════════════════════════════════════════════════════════════════

    POST /twilio/test-send        (platform owner only)
        → { status, message_sid } — one SMS to TEST_SMS_TO.

    POST /webhooks/twilio/sms     (Twilio → us; form-encoded)
        Validates X-Twilio-Signature (when TWILIO_AUTH_TOKEN is set),
        honoring Railway's proxy headers when reconstructing the public
        URL. Valid → logs From/Body, returns empty TwiML. Invalid → 403.

Twilio Messaging Service → Integration → "Send a webhook":
    https://kmj-intake-server-production.up.railway.app/webhooks/twilio/sms
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from lead_admin import require_owner

logger = logging.getLogger("twilio_sms")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] twilio: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

router = APIRouter(tags=["twilio-sms"])

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


# ─── Service layer ─────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    val = (os.environ.get(name) or "").strip()
    if not val:
        raise RuntimeError(
            f"Twilio SMS is not configured — the {name} environment variable is missing"
        )
    return val


@lru_cache(maxsize=1)
def _twilio_client():
    """Lazily-initialized Twilio client — API Key SID + Secret + Account
    SID, per Twilio's API-key auth pattern. Cached for the process
    lifetime; env problems surface as loud RuntimeErrors on first use,
    never at import (so a missing var can't block app boot)."""
    from twilio.rest import Client  # import here so the dep is only needed when used
    account_sid = _require_env("TWILIO_ACCOUNT_SID")
    api_key_sid = _require_env("TWILIO_API_KEY_SID")
    api_key_secret = _require_env("TWILIO_API_KEY_SECRET")
    return Client(api_key_sid, api_key_secret, account_sid)


def send_sms(to: str, body: str) -> str:
    """Send one SMS through the Messaging Service (no from_ number —
    Twilio picks the sender from the service's pool). Returns the
    created Message SID. Blocking — call via run_in_threadpool from
    async handlers."""
    messaging_service_sid = _require_env("TWILIO_MESSAGING_SERVICE_SID")
    message = _twilio_client().messages.create(
        to=to,
        body=body,
        messaging_service_sid=messaging_service_sid,
    )
    logger.info(f"sent SMS to={to} sid={message.sid}")
    return message.sid


# ─── Test send ─────────────────────────────────────────────────────────

@router.post("/twilio/test-send")
async def twilio_test_send(_owner=Depends(require_owner)):
    """One SMS to TEST_SMS_TO — confirms auth + Messaging Service wiring.
    Owner-gated: it's an operator probe, not a public surface."""
    try:
        to = _require_env("TEST_SMS_TO")
        sid = await run_in_threadpool(
            send_sms, to,
            "The Solutionist System: Twilio SMS is wired up correctly. ✔",
        )
        return {"status": "sent", "message_sid": sid}
    except Exception as e:
        # Clear error JSON — the message never includes credentials.
        logger.error(f"test-send failed: {e}")
        return JSONResponse(status_code=502, content={"status": "error", "detail": str(e)[:300]})


# ─── Inbound webhook ───────────────────────────────────────────────────

def _public_url(request: Request) -> str:
    """The exact URL Twilio signed. Railway terminates TLS at its proxy,
    so request.url says http://… — honor X-Forwarded-Proto/-Host, which
    Railway sets to the values the outside world (and Twilio) used."""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    url = f"{proto}://{host}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    return url


@router.post("/webhooks/twilio/sms")
async def twilio_inbound_sms(request: Request):
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}

    auth_token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    if auth_token:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(auth_token)
        signature = request.headers.get("x-twilio-signature", "")
        if not validator.validate(_public_url(request), params, signature):
            logger.warning("inbound SMS REJECTED — invalid X-Twilio-Signature")
            return Response(status_code=403)
    else:
        # API-key setups can't validate signatures — that needs the
        # ACCOUNT auth token. Process anyway (don't break inbound), but
        # say so on every request until TWILIO_AUTH_TOKEN is set.
        logger.warning(
            "inbound SMS accepted UNVALIDATED — set TWILIO_AUTH_TOKEN on "
            "Railway to enable X-Twilio-Signature verification"
        )

    from_number = params.get("From", "")
    body = params.get("Body", "")
    logger.info(f"inbound SMS from={from_number} body={body[:500]}")

    # Routing (2026-07-04): inbound texts flow into the SAME pipeline
    # the Telnyx webhook uses — sms_messages row (read=false → unread
    # badge), events, chief_notifications, contact health bump. So a
    # reply shows up in the SMS Hub thread the moment Twilio delivers
    # it. Media rides along (MediaUrl0..N). Future: match business by
    # the To number once per-business numbers exist.
    if from_number and body.strip():
        try:
            import httpx
            from sms_service import record_inbound_sms, normalize_phone
            media = []
            n_media = int(params.get("NumMedia") or 0)
            for i in range(min(n_media, 10)):
                url = params.get(f"MediaUrl{i}")
                if url:
                    media.append({"url": url})
            async with httpx.AsyncClient() as client:
                await record_inbound_sms(
                    client,
                    from_number=normalize_phone(from_number) or from_number,
                    text=body,
                    provider_id=params.get("MessageSid", ""),
                    media=media,
                )
        except Exception as e:
            # Never bounce Twilio — a failed insert would trigger
            # retries and double-processing. Log loudly instead.
            logger.error(f"inbound SMS processing failed: {e}")

    return Response(content=EMPTY_TWIML, media_type="application/xml")


# ─── Delivery status callback ──────────────────────────────────────────
# Twilio Messaging Service → Integration → "Delivery Status Callback":
#   https://<this-host>/webhooks/twilio/status
# Maps Twilio statuses onto the strings the SMS Hub renders as ticks
# (sent ✓ / delivered ✓✓ / failed ✗).

_STATUS_MAP = {
    "queued": "sent", "accepted": "sent", "sending": "sent", "sent": "sent",
    "delivered": "delivered",
    "undelivered": "failed", "failed": "failed",
}


@router.post("/webhooks/twilio/status")
async def twilio_status_callback(request: Request):
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}

    auth_token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    if auth_token:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(auth_token)
        if not validator.validate(_public_url(request), params,
                                  request.headers.get("x-twilio-signature", "")):
            return Response(status_code=403)

    sid = params.get("MessageSid", "")
    status = _STATUS_MAP.get((params.get("MessageStatus") or "").lower())
    if sid and status:
        try:
            import httpx
            from sms_service import _sb_patch
            async with httpx.AsyncClient() as client:
                await _sb_patch(client, f"/sms_messages?telnyx_id=eq.{sid}", {"status": status})
            if status == "failed":
                logger.warning(f"delivery FAILED sid={sid} code={params.get('ErrorCode', '')}")
        except Exception as e:
            logger.warning(f"status update failed: {e}")

    return Response(status_code=204)
