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
    TWILIO_PLATFORM_NUMBER        +1…   (the shared platform number, E.164.
                                         Every send PINS a from_ number;
                                         this is the default. Unset → the
                                         service picks from its pool, with
                                         a loud warning — see send_sms.)
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
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from lead_admin import require_owner
import pii_mask

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


def platform_number() -> str:
    """The shared platform number (E.164) — the sender every business
    texts from until it has a number of its own."""
    return (os.environ.get("TWILIO_PLATFORM_NUMBER") or "").strip()


_warned_unpinned = False


def send_sms(to: str, body: str, *, from_number: Optional[str] = None) -> str:
    """Send one SMS through the Messaging Service, PINNED to a sender.
    Returns the created Message SID. Blocking — call via
    run_in_threadpool from async handlers.

    Why pinned (2026-09-02, dedicated numbers phase A): a send through
    a Messaging Service with no from_ lets Twilio pick ANY number in
    the service's pool. That is fine while the pool holds one number.
    The moment a practitioner's own number joins the pool, an unpinned
    booking alert for Business A can go out from Business B's line. So
    every send names its sender — the business's own number when it
    has one, else the platform number — and Twilio honors from_ +
    messaging_service_sid together (the specific number is used; the
    service's opt-out handling and status callbacks still apply).

    TWILIO_PLATFORM_NUMBER unset → today's behavior (pool pick) with a
    warning, so a missing env var degrades to the old path rather than
    stopping texts; provisioning a dedicated number refuses to run in
    that state, which is what keeps the old path safe."""
    global _warned_unpinned
    messaging_service_sid = _require_env("TWILIO_MESSAGING_SERVICE_SID")
    sender = (from_number or "").strip() or platform_number()
    kwargs = dict(to=to, body=body, messaging_service_sid=messaging_service_sid)
    if sender:
        kwargs["from_"] = sender
    elif not _warned_unpinned:
        _warned_unpinned = True
        logger.warning(
            "TWILIO_PLATFORM_NUMBER is not set — sends are UNPINNED and the "
            "Messaging Service picks the sender. Set it before any dedicated "
            "number joins the pool.")
    message = _twilio_client().messages.create(**kwargs)
    logger.info(f"sent SMS to={to} from={sender or 'pool'} sid={message.sid}")
    return message.sid


# ─── Number lifecycle (dedicated numbers, phase C) ─────────────────────
# Blocking — call via run_in_threadpool. All on the platform account;
# every number bought here is attached to the one Messaging Service so
# it rides the registered 10DLC campaign. sms_numbers_router owns the
# order of operations and the rollback.

@lru_cache(maxsize=1)
def _twilio_admin_client():
    """The client for number LIFECYCLE calls (search, buy, attach,
    release). The platform's API key is a restricted one — it can send
    (messages.create) and that is all; proven 2026-09-02 against the
    live account: listing the sender pool with it returns 401 "required
    permission twilio/messaging/services.phonenumbers/list is missing",
    and active-numbers/list the same. The ACCOUNT auth token can do all
    of it, and it is already in Railway for inbound signature
    validation. So lifecycle uses the token when present, and the key
    otherwise — a key that has been granted the permissions works too.
    Sending stays on the key: least privilege for the hot path."""
    from twilio.rest import Client
    account_sid = _require_env("TWILIO_ACCOUNT_SID")
    token = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    if token:
        return Client(account_sid, token)
    return _twilio_client()


def search_numbers(area_code: Optional[str], limit: int = 10) -> list:
    """Local, SMS-capable US numbers in an area code."""
    kwargs = dict(sms_enabled=True, limit=max(1, min(int(limit), 20)))
    if area_code:
        kwargs["area_code"] = int(area_code)
    found = _twilio_admin_client().available_phone_numbers("US").local.list(**kwargs)
    return [{
        "phone_number": n.phone_number,
        "friendly_name": n.friendly_name,
        "locality": getattr(n, "locality", None),
        "region": getattr(n, "region", None),
    } for n in found]


def buy_number(phone_number: str) -> dict:
    pn = _twilio_admin_client().incoming_phone_numbers.create(
        phone_number=phone_number, friendly_name="Solutionist private line")
    logger.info(f"bought {pn.phone_number} sid={pn.sid}")
    return {"sid": pn.sid, "phone_number": pn.phone_number}


def attach_to_service(pn_sid: str) -> str:
    """Add a bought number to the Messaging Service's sender pool.
    Returns the service SID it joined."""
    mg = _require_env("TWILIO_MESSAGING_SERVICE_SID")
    _twilio_admin_client().messaging.v1.services(mg).phone_numbers.create(phone_number_sid=pn_sid)
    logger.info(f"attached {pn_sid} to {mg}")
    return mg


def detach_from_service(pn_sid: str) -> None:
    """Best effort — a number already out of the pool is fine."""
    mg = _require_env("TWILIO_MESSAGING_SERVICE_SID")
    try:
        _twilio_admin_client().messaging.v1.services(mg).phone_numbers(pn_sid).delete()
    except Exception as e:
        logger.warning(f"detach {pn_sid} from {mg}: {e}")


def release_number(pn_sid: str) -> None:
    _twilio_admin_client().incoming_phone_numbers(pn_sid).delete()
    logger.info(f"released {pn_sid}")


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
        # ACCOUNT auth token. An unvalidated inbound body reaches Chief's
        # prompt and Chief can send, so drop it rather than trust it.
        import webhook_guard
        if not webhook_guard.unsigned_allowed("twilio"):
            webhook_guard.reject_unsigned("twilio", "TWILIO_AUTH_TOKEN is not set")
            return Response(status_code=403)

    from_number = params.get("From", "")
    body = params.get("Body", "")
    logger.info(f"inbound SMS from={pii_mask.mask_phone(from_number)} len={len(body)}")

    # Routing (2026-07-04, Kevin's architecture; own numbers 2026-09-02):
    # a business's OWN number routes by To. Otherwise ONE platform number —
    # Chief routes every inbound BINDING FIRST, KEYWORD SECOND
    # (sms_routing.route_inbound: STOP/START/HELP → keyword bind +
    # connection/consent confirmation → binding route → disambiguate →
    # keyword prompt). Auto-replies go back as TwiML on this response —
    # same number, no extra API call.
    if from_number and body.strip():
        try:
            from sms_routing import route_inbound
            media = []
            n_media = int(params.get("NumMedia") or 0)
            for i in range(min(n_media, 10)):
                url = params.get(f"MediaUrl{i}")
                if url:
                    media.append({"url": url})
            result = await route_inbound(
                from_number=from_number,
                text=body,
                provider_id=params.get("MessageSid", ""),
                media=media,
                # The number the customer texted. A business's own
                # line routes straight to it; the platform number
                # takes the keyword/binding path.
                to_number=params.get("To", ""),
            )
            reply = result.get("reply")
            if reply:
                from xml.sax.saxutils import escape
                twiml = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    f"<Response><Message>{escape(reply)}</Message></Response>"
                )
                return Response(content=twiml, media_type="application/xml")
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
