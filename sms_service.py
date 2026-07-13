"""
sms_service.py — Telnyx-backed SMS for the Solutionist System.

Routes:
  POST /sms/send                            send an SMS via Telnyx
  POST /sms/inbound                         Telnyx webhook for incoming SMS
  GET  /sms/conversation/{biz}/{contact}    fetch a conversation thread
  POST /sms/session-reminder                send a session reminder by SMS
  GET  /sms/health                          status check

Env:
  TELNYX_API_KEY        — required for sending. https://portal.telnyx.com
  TELNYX_PHONE_NUMBER   — the From number (E.164, e.g. +12315551234)
  TELNYX_PUBLIC_KEY     — optional, for webhook signature verification

Storage: sms_messages table (see supabase/sms-messages-migration.sql).
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pii_mask

router = APIRouter(tags=["sms"])
logger = logging.getLogger("sms_service")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] sms: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


TELNYX_API_URL = "https://api.telnyx.com/v2"
HTTP_TIMEOUT = 15.0

# ─── Supabase helpers (anon key, same pattern as the rest of railway/) ──

def _pq(value) -> str:
    """Percent-encode a value for a PostgREST query-string filter.

    E.164 phones start with '+', which URL query parsing decodes as a
    SPACE - so every `phone=eq.+1...` filter silently matched NOTHING
    (proven against prod: raw '+' -> 0 rows, '%2B' -> 1 row). That one
    character broke binding routing ("keeps asking for the keyword"),
    opt-out checks, consent checks, and exact contact matching. Route
    every phone value through this before it enters a URL.
    """
    import urllib.parse
    return urllib.parse.quote(str(value or ""), safe="")


def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_anon() -> str:
    # 2026-07-10 root-cause fix: this module (and sms_routing, which
    # imports these helpers) ran on the ANON key under the assumption
    # of permissive RLS — but sms_messages/sms_consents now ship with
    # owner-scoped RLS (text content must NOT be readable with the
    # public browser key). Server-initiated SMS writes are webhook- or
    # signature-validated, so the service role is the correct identity.
    # Anon fallback keeps a partially-configured env limping visibly
    # (warnings) instead of failing dark.
    return (os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            or os.environ.get("SUPABASE_ANON", ""))


def _sb_headers() -> Dict[str, str]:
    return {
        "apikey": _sb_anon(),
        "Authorization": f"Bearer {_sb_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _sb_get(client: httpx.AsyncClient, path: str) -> Optional[Any]:
    try:
        r = await client.get(f"{_sb_url()}/rest/v1{path}",
                              headers=_sb_headers(), timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"supabase GET {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"supabase GET {path} failed: {e}")
        return None


async def _sb_post(client: httpx.AsyncClient, path: str, body: Dict[str, Any]) -> Optional[Any]:
    try:
        r = await client.post(f"{_sb_url()}/rest/v1{path}",
                               headers=_sb_headers(),
                               content=json.dumps(body),
                               timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"supabase POST {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"supabase POST {path} failed: {e}")
        return None


async def _sb_patch(client: httpx.AsyncClient, path: str, body: Dict[str, Any]) -> None:
    try:
        await client.patch(f"{_sb_url()}/rest/v1{path}",
                            headers=_sb_headers(),
                            content=json.dumps(body),
                            timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        logger.warning(f"supabase PATCH {path} failed: {e}")


# ─── Phone number normalization ──────────────────────────────────────

def normalize_phone(phone: Optional[str]) -> str:
    """Coerce a phone string to E.164 (+1XXXXXXXXXX for US/CA).

    - Already-prefixed numbers pass through.
    - 10 digits get +1 prepended (US/CA assumption).
    - 11 digits starting with 1 get a + prepended.
    - Anything else returns "" — caller must handle invalid.
    """
    if not phone:
        return ""
    s = str(phone).strip()
    if s.startswith("+") and len(s) >= 8:
        return s
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return ""


# ─── Send ────────────────────────────────────────────────────────────

class SendSmsRequest(BaseModel):
    business_id: str
    contact_id: Optional[str] = None
    to: str
    message: str


async def _send_via_telnyx(
    client: httpx.AsyncClient,
    to_number: str,
    message: str,
) -> Dict[str, Any]:
    """Low-level Telnyx send. Returns the response JSON (which includes
    the Telnyx message id) or raises RuntimeError on a non-2xx.

    Uses the messages endpoint — Telnyx auto-segments long messages."""
    api_key = os.environ.get("TELNYX_API_KEY", "")
    from_number = os.environ.get("TELNYX_PHONE_NUMBER", "")
    if not api_key:
        raise RuntimeError("TELNYX_API_KEY not configured")
    if not from_number:
        raise RuntimeError("TELNYX_PHONE_NUMBER not configured")

    payload = {
        "from": from_number,
        "to": to_number,
        "text": message,
        "type": "SMS",
    }
    r = await client.post(
        f"{TELNYX_API_URL}/messages",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=HTTP_TIMEOUT,
    )
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"Telnyx {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


async def _store_sms(
    client: httpx.AsyncClient,
    business_id: str,
    contact_id: Optional[str],
    phone_number: str,
    message: str,
    direction: str,
    telnyx_id: str = "",
    status: Optional[str] = None,
    media: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Insert a row into sms_messages. Returns the new id."""
    row = {
        "business_id": business_id,
        "contact_id": contact_id,
        "phone_number": phone_number,
        "message": message,
        "direction": direction,
        "status": status or ("sent" if direction == "outbound" else "received"),
        "telnyx_id": telnyx_id,
        "media_urls": [m.get("url") for m in (media or []) if m.get("url")],
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Outbound messages count as "read" — only inbound is unread by default.
        "read": direction == "outbound",
    }
    inserted = await _sb_post(client, "/sms_messages", row)
    if isinstance(inserted, list) and inserted:
        return inserted[0].get("id")
    if isinstance(inserted, dict):
        return inserted.get("id")
    return None


async def _log_event(
    client: httpx.AsyncClient,
    business_id: str,
    contact_id: Optional[str],
    event_type: str,
    data: Dict[str, Any],
) -> None:
    await _sb_post(client, "/events", {
        "business_id": business_id,
        "contact_id": contact_id,
        "event_type": event_type,
        "data": data,
        "source": "sms_service",
    })


async def is_opted_out(client: httpx.AsyncClient, phone: str,
                       business_id: Optional[str] = None) -> bool:
    """Platform-wide STOP check (Direct model: one number → STOP
    suppresses everything). Checked before EVERY outbound send. Fails
    OPEN — a DB blip must not block transactional sends; carrier-level
    STOP still protects. business_id reserved for ISV per-pair use."""
    try:
        rows = await _sb_get(
            client,
            f"/sms_opt_outs?phone=eq.{_pq(phone)}&business_id=is.null&select=id&limit=1",
        ) or []
        return bool(rows)
    except Exception:
        return False


def _twilio_configured() -> bool:
    """Twilio is the primary rail when its env is present (2026-07-04 —
    Kevin's Messaging Service). Telnyx stays as the fallback."""
    return all(
        (os.environ.get(k) or "").strip()
        for k in ("TWILIO_ACCOUNT_SID", "TWILIO_API_KEY_SID",
                  "TWILIO_API_KEY_SECRET", "TWILIO_MESSAGING_SERVICE_SID")
    )


@router.post("/sms/send")
async def send_sms(req: SendSmsRequest):
    """Send an SMS (Twilio Messaging Service first; Telnyx fallback)
    and persist it as outbound."""
    to_clean = normalize_phone(req.to)
    if not to_clean:
        return JSONResponse({"error": f"Invalid phone number: {req.to}"}, 400)
    if not req.message.strip():
        return JSONResponse({"error": "Message body required"}, 400)

    use_twilio = _twilio_configured()
    if not use_twilio and not os.environ.get("TELNYX_API_KEY"):
        return JSONResponse(
            {"error": "SMS not configured. Set the TWILIO_* vars (or TELNYX_API_KEY) in Railway."},
            503,
        )

    async with httpx.AsyncClient() as client:
        # Consent gate — never send to a number that opted out.
        if await is_opted_out(client, to_clean):
            return JSONResponse(
                {"error": f"{to_clean} has opted out of texts (STOP). "
                          f"They can text START to opt back in."},
                422,
            )

        # Resolve contact by phone if caller didn't supply one.
        contact_id = req.contact_id
        if not contact_id and req.business_id:
            match = await _find_contact_by_phone(client, req.business_id, to_clean)
            if match:
                contact_id = match.get("id")

        if use_twilio:
            try:
                from starlette.concurrency import run_in_threadpool
                import twilio_sms
                # Provider message id lands in the telnyx_id column —
                # provider-agnostic in intent; the status callback
                # (/webhooks/twilio/status) PATCHes on it.
                telnyx_id = await run_in_threadpool(twilio_sms.send_sms, to_clean, req.message)
            except Exception as e:
                logger.warning(f"[SMS] twilio send failed: {e}")
                return JSONResponse({"error": str(e)[:300]}, 502)
        else:
            try:
                tx = await _send_via_telnyx(client, to_clean, req.message)
            except RuntimeError as e:
                logger.warning(f"[SMS] send failed: {e}")
                return JSONResponse({"error": str(e)}, 502)
            telnyx_id = (tx.get("data") or {}).get("id", "") if isinstance(tx, dict) else ""

        msg_id = await _store_sms(
            client,
            business_id=req.business_id,
            contact_id=contact_id,
            phone_number=to_clean,
            message=req.message,
            direction="outbound",
            telnyx_id=telnyx_id,
            status="sent",
        )

        await _log_event(client, req.business_id, contact_id, "sms_sent", {
            "to": to_clean,
            "preview": req.message[:200],
            "telnyx_id": telnyx_id,
            "sms_id": msg_id,
        })

        if contact_id:
            await _sb_patch(client, f"/contacts?id=eq.{contact_id}", {
                "last_interaction": datetime.now(timezone.utc).isoformat(),
            })

        logger.info(f"[SMS] sent biz={req.business_id[:8]} to={to_clean} len={len(req.message)} telnyx={telnyx_id}")
        return {"status": "sent", "id": msg_id, "telnyx_id": telnyx_id}


# ─── Contact lookup helpers ──────────────────────────────────────────

async def _find_contact_by_phone(
    client: httpx.AsyncClient,
    business_id: str,
    phone: str,
) -> Optional[Dict[str, Any]]:
    """Find a contact by phone number. Tries exact E.164 first, then a
    last-10-digits suffix match for tolerance against varied formats."""
    if not phone:
        return None
    rows = await _sb_get(client,
        f"/contacts?business_id=eq.{business_id}&phone=eq.{_pq(phone)}"
        f"&select=id,name,phone,health_score,status&limit=1")
    if rows:
        return rows[0]
    last10 = "".join(ch for ch in phone if ch.isdigit())[-10:]
    if not last10:
        return None
    rows = await _sb_get(client,
        f"/contacts?business_id=eq.{business_id}&phone=like.%25{last10}"
        f"&select=id,name,phone,health_score,status&limit=1")
    return rows[0] if rows else None


async def _find_contact_global(
    client: httpx.AsyncClient,
    phone: str,
) -> Optional[Dict[str, Any]]:
    """Find a contact across ALL businesses by phone. Used by the
    inbound webhook since Telnyx doesn't pass business routing info —
    we infer the business from whichever contact owns the number."""
    if not phone:
        return None
    rows = await _sb_get(client,
        f"/contacts?phone=eq.{_pq(phone)}"
        f"&select=id,name,phone,business_id,health_score,status&limit=1")
    if rows:
        return rows[0]
    last10 = "".join(ch for ch in phone if ch.isdigit())[-10:]
    if not last10:
        return None
    rows = await _sb_get(client,
        f"/contacts?phone=like.%25{last10}"
        f"&select=id,name,phone,business_id,health_score,status&limit=1")
    return rows[0] if rows else None


# ─── Inbound webhook ─────────────────────────────────────────────────

@router.post("/sms/inbound")
async def receive_sms(request: Request):
    """Telnyx webhook handler.

    Expected events:
      - message.received   inbound text from a recipient
      - message.sent       delivery status (we log + flip our row)
      - message.finalized  delivery final status
      - message.failed     delivery failure

    Always returns 200 so Telnyx doesn't retry; failures are logged.
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"status": "ignored", "reason": "non-json"}, 200)

    data = payload.get("data") or {}
    event_type = (data.get("event_type") or "").lower()
    msg_payload = data.get("payload") or {}

    async with httpx.AsyncClient() as client:
        # Delivery status updates — flip status on the matching row.
        if event_type in ("message.sent", "message.delivered", "message.finalized", "message.failed"):
            telnyx_id = msg_payload.get("id", "")
            status_map = {
                "message.sent":       "sent",
                "message.delivered":  "delivered",
                "message.finalized":  "delivered",
                "message.failed":     "failed",
            }
            new_status = status_map.get(event_type)
            if telnyx_id and new_status:
                await _sb_patch(client, f"/sms_messages?telnyx_id=eq.{telnyx_id}",
                                {"status": new_status})
                logger.info(f"[SMS] delivery {event_type} telnyx={telnyx_id}")
            return {"status": "ok", "event": event_type}

        if event_type != "message.received":
            return {"status": "ignored", "event": event_type or "unknown"}

        # Inbound text. Extract sender + recipient + body.
        from_obj = msg_payload.get("from") or {}
        from_number_raw = from_obj.get("phone_number") if isinstance(from_obj, dict) else str(from_obj)
        from_number = normalize_phone(from_number_raw or "")
        text = (msg_payload.get("text") or "").strip()
        telnyx_id = msg_payload.get("id", "")
        media = msg_payload.get("media") or []

        if not from_number or not text:
            logger.info(f"[SMS] dropped inbound — from={pii_mask.mask_phone(from_number_raw)} text_len={len(text)}")
            return {"status": "ignored", "reason": "missing_from_or_text"}

        # Consent keywords (compliance fix, 2026-07-10): the Twilio
        # webhook routes STOP/START through sms_routing.route_inbound,
        # but this legacy Telnyx path stored a STOP as a plain inbound
        # message WITHOUT recording the opt-out. Telnyx is currently
        # unconfigured in prod, but the path must be compliant if it
        # ever carries traffic again.
        import sms_routing as _routing
        first_word = text.split()[0].upper() if text.split() else ""
        if first_word in _routing.STOP_WORDS:
            await _sb_post(client, "/sms_opt_outs?on_conflict=phone,business_id",
                           {"phone": from_number, "business_id": None})
            logger.info(f"[SMS] STOP via Telnyx path from {pii_mask.mask_phone(from_number)} — opt-out recorded")
            return {"status": "ok", "action": "opt_out"}
        if first_word in _routing.START_WORDS:
            try:
                await client.delete(
                    f"{_sb_url()}/rest/v1/sms_opt_outs?phone=eq.{_pq(from_number)}",
                    headers=_sb_headers(), timeout=HTTP_TIMEOUT)
                logger.info(f"[SMS] START via Telnyx path from {pii_mask.mask_phone(from_number)} — opt-out cleared")
            except httpx.HTTPError as e:
                logger.warning(f"[SMS] opt-out clear failed: {e}")
            return {"status": "ok", "action": "opt_in"}

        return await record_inbound_sms(
            client, from_number=from_number, text=text,
            provider_id=telnyx_id, media=media,
        )


async def record_inbound_sms(
    client: httpx.AsyncClient,
    *,
    from_number: str,
    text: str,
    provider_id: str = "",
    media: Optional[List[Dict[str, Any]]] = None,
    business_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Shared inbound pipeline — used by the Telnyx webhook and by the
    Twilio routing layer (sms_routing.route_inbound). Resolves the
    contact, persists the row (read=false → drives the unread badge),
    logs the event, notifies Chief, and bumps contact health.

    Business resolution:
      • business_id given (Twilio path) — the BINDING decided it; the
        contact is looked up (or created) INSIDE that business only.
      • business_id None (legacy Telnyx path) — global contact match,
        else oldest business (single-tenant default)."""
    contact_id: Optional[str] = None
    contact_name: Optional[str] = None
    current_health = 50

    if business_id:
        contact = await _find_contact_by_phone(client, business_id, from_number)
        if not contact:
            created = await _sb_post(client, "/contacts", {
                "business_id": business_id,
                "name": from_number,      # practitioner renames later
                "phone": from_number,
                "status": "active",
            })
            contact = (created or [None])[0] if isinstance(created, list) else created
        if contact:
            contact_id = contact.get("id")
            contact_name = contact.get("name")
            current_health = int(contact.get("health_score") or 50)
    else:
        contact = await _find_contact_global(client, from_number)
        if contact:
            contact_id = contact.get("id")
            contact_name = contact.get("name")
            business_id = contact.get("business_id")
            current_health = int(contact.get("health_score") or 50)
        else:
            biz_rows = await _sb_get(client, "/businesses?select=id&order=created_at.asc&limit=1") or []
            if biz_rows:
                business_id = biz_rows[0]["id"]

    if not business_id:
        logger.info(f"[SMS] no business found for inbound from {pii_mask.mask_phone(from_number)}")
        return {"status": "unresolved", "from": from_number}

    # Persist
    msg_id = await _store_sms(
        client,
        business_id=business_id,
        contact_id=contact_id,
        phone_number=from_number,
        message=text,
        direction="inbound",
        telnyx_id=provider_id,
        status="received",
        media=media,
    )

    await _log_event(client, business_id, contact_id, "sms_received", {
        "from": from_number,
        "from_name": contact_name or "",
        "preview": text[:200],
        "telnyx_id": provider_id,
        "has_media": bool(media),
        "sms_id": msg_id,
    })

    await _sb_post(client, "/chief_notifications", {
        "business_id": business_id,
        "type": "info",
        "title": f"Text from {contact_name or from_number}",
        "body": text[:200],
        "suggested_action": f"Reply to {contact_name or from_number}",
        "status": "unread",
        "data": {
            "contact_id": contact_id,
            "sms_id": msg_id,
            "from_number": from_number,
            "preview": text[:200],
        },
    })

    if contact_id:
        await _sb_patch(client, f"/contacts?id=eq.{contact_id}", {
            "health_score": min(100, current_health + 5),
            "last_interaction": datetime.now(timezone.utc).isoformat(),
        })

    logger.info(
        f"[SMS] inbound from={from_number} biz={business_id[:8]} "
        f"contact={(contact_id or 'unknown')[:8]} len={len(text)}"
    )
    return {"status": "processed", "sms_id": msg_id}


# ─── Conversation thread ─────────────────────────────────────────────

@router.get("/sms/conversation/{business_id}/{contact_id}")
async def get_conversation(business_id: str, contact_id: str):
    """Return the full ordered SMS thread for a contact."""
    async with httpx.AsyncClient() as client:
        rows = await _sb_get(client,
            f"/sms_messages?business_id=eq.{business_id}&contact_id=eq.{contact_id}"
            f"&order=created_at.asc&limit=200"
            f"&select=id,direction,phone_number,message,status,telnyx_id,media_urls,created_at,read"
        ) or []
    return {"messages": rows}


# ─── Session reminder ────────────────────────────────────────────────

class SessionReminderRequest(BaseModel):
    business_id: str
    session_id: str


@router.post("/sms/session-reminder")
async def send_session_reminder(req: SessionReminderRequest):
    """Send a friendly SMS reminder for an upcoming session.

    Pulls the session + contact + business name, formats a short
    message, and routes through /sms/send so all the usual storage +
    event-logging fires.
    """
    async with httpx.AsyncClient() as client:
        sess_rows = await _sb_get(client,
            f"/sessions?id=eq.{req.session_id}&business_id=eq.{req.business_id}"
            f"&select=id,scheduled_for,session_type,contact_id&limit=1") or []
        if not sess_rows:
            return JSONResponse({"error": "Session not found"}, 404)
        session = sess_rows[0]

        contact_id = session.get("contact_id")
        if not contact_id:
            return JSONResponse({"error": "Session has no contact"}, 400)

        contact_rows = await _sb_get(client,
            f"/contacts?id=eq.{contact_id}&select=id,name,phone&limit=1") or []
        if not contact_rows:
            return JSONResponse({"error": "Contact not found"}, 404)
        contact = contact_rows[0]
        if not contact.get("phone"):
            return JSONResponse({"error": "Contact has no phone number"}, 400)

        biz_rows = await _sb_get(client,
            f"/businesses?id=eq.{req.business_id}&select=name&limit=1") or []
        biz_name = biz_rows[0].get("name") if biz_rows else "your practitioner"

        try:
            scheduled = datetime.fromisoformat(
                str(session["scheduled_for"]).replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            return JSONResponse({"error": "Invalid scheduled_for"}, 400)

        # Cross-platform-safe time/day formatting (no %-d on Windows).
        time_str = scheduled.strftime("%I:%M %p").lstrip("0")
        date_str = scheduled.strftime("%A, %B %d").replace(" 0", " ")
        session_type = (session.get("session_type") or "session").replace("_", " ")
        first_name = (contact.get("name") or "").split()[0] if contact.get("name") else ""

        greeting = f"Hi {first_name}! " if first_name else "Hi! "
        message = (
            f"{greeting}Reminder: your {session_type} with {biz_name} is "
            f"{date_str} at {time_str}. Reply Y to confirm or let me know if you need to reschedule."
        )

    return await send_sms(SendSmsRequest(
        business_id=req.business_id,
        contact_id=contact_id,
        to=contact["phone"],
        message=message,
    ))


@router.get("/sms/health")
async def sms_health():
    return {
        "status": "ok",
        "provider": "twilio" if _twilio_configured() else
                    ("telnyx" if os.environ.get("TELNYX_API_KEY") else "none"),
        "twilio_configured": _twilio_configured(),
        "telnyx_configured": bool(os.environ.get("TELNYX_API_KEY")),
        "telnyx_phone": os.environ.get("TELNYX_PHONE_NUMBER", ""),
    }
