"""
email_sender.py — Resend-backed transactional email for the Solutionist System.

Exposes POST /email/send. Callers (the ApprovalQueue UI, Chief of Staff,
any agent) hit this to actually deliver a queued-and-approved message.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway alongside the other agent files.

2. In main.py (or whichever file mounts the FastAPI app):
       from email_sender import router as email_router
       app.include_router(email_router)

3. Env vars on Railway:
       RESEND_API_KEY           — required. https://resend.com/api-keys
       RESEND_FROM_EMAIL        — optional. Defaults to noreply@mysolutionist.app.
                                  Must be on a verified Resend domain, OR use
                                  `onboarding@resend.dev` for pre-verification testing.

Until a domain is verified, Resend only accepts sends to the account's
own address. Add the SPF/DKIM/DMARC records Resend surfaces in its
dashboard to unlock general sends.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

RESEND_URL = "https://api.resend.com/emails"
DEFAULT_FROM_EMAIL = "noreply@mysolutionist.app"
DEFAULT_FROM_NAME = "The Solutionist System"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)

logger = logging.getLogger("email_sender")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] email: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

router = APIRouter(tags=["email"])


class SendEmailRequest(BaseModel):
    to_email: str
    to_name: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    subject: str
    body: str  # HTML or plain text
    reply_to: Optional[str] = None
    business_id: str


class SendEmailResponse(BaseModel):
    ok: bool
    id: Optional[str] = None
    provider_response: Optional[Dict[str, Any]] = None


def _format_address(email: str, name: Optional[str]) -> str:
    """Return RFC 5322 `Name <email>` when a name is supplied; otherwise bare email."""
    if not name:
        return email
    # Strip any stray angle brackets or commas from the name — Resend rejects them
    safe_name = name.replace("<", "").replace(">", "").replace(",", "").strip()
    return f"{safe_name} <{email}>" if safe_name else email


def _body_is_html(body: str) -> bool:
    """Rough heuristic — we let the caller send plain text OR html and pick the
    right Resend field. Resend requires at least one of `html` or `text`."""
    b = (body or "").lstrip().lower()
    return b.startswith("<!doctype") or b.startswith("<html") or "<p" in b or "<div" in b or "<br" in b


async def send_via_resend(
    *,
    to_email: str,
    to_name: Optional[str],
    from_email: str,
    from_name: Optional[str],
    subject: str,
    body: str,
    reply_to: Optional[str],
) -> Dict[str, Any]:
    """Low-level Resend client. Raises on API error."""
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        raise RuntimeError("RESEND_API_KEY is not configured")

    payload: Dict[str, Any] = {
        "from": _format_address(from_email, from_name),
        "to": [_format_address(to_email, to_name)],
        "subject": subject or "(no subject)",
    }
    if _body_is_html(body):
        payload["html"] = body
    else:
        payload["text"] = body
    if reply_to:
        payload["reply_to"] = reply_to

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if resp.status_code >= 400:
        # Log the Resend error verbatim — helps debug domain / API-key issues
        logger.error(f"Resend error {resp.status_code}: {resp.text[:500]}")
        raise RuntimeError(f"Resend {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


@router.post("/email/send", response_model=SendEmailResponse)
async def send_email(req: SendEmailRequest):
    if not os.environ.get("RESEND_API_KEY"):
        raise HTTPException(500, "Resend API key not configured")

    if not req.to_email or "@" not in req.to_email:
        raise HTTPException(400, "Valid to_email is required")

    from_email = req.from_email or os.environ.get("RESEND_FROM_EMAIL") or DEFAULT_FROM_EMAIL
    from_name = req.from_name or DEFAULT_FROM_NAME

    try:
        data = await send_via_resend(
            to_email=req.to_email,
            to_name=req.to_name,
            from_email=from_email,
            from_name=from_name,
            subject=req.subject,
            body=req.body,
            reply_to=req.reply_to or from_email,
        )
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    logger.info(
        f"Email sent business={req.business_id} to={req.to_email} "
        f"subject_len={len(req.subject or '')} id={data.get('id')}"
    )
    return SendEmailResponse(ok=True, id=data.get("id"), provider_response=data)


@router.get("/email/health")
async def email_health():
    return {
        "status": "ok",
        "resend_configured": bool(os.environ.get("RESEND_API_KEY")),
        "from_email": os.environ.get("RESEND_FROM_EMAIL") or DEFAULT_FROM_EMAIL,
    }


# ═══════════════════════════════════════════════════════════════════════
# INBOUND EMAIL WEBHOOK
# ═══════════════════════════════════════════════════════════════════════
#
# Resend forwards incoming replies via a webhook to this endpoint. Resend's
# payload shape for inbound (and for their unified event webhook) varies
# across versions, so the parsing below is permissive — it tries multiple
# common keys before giving up.
#
# Configure in the Resend dashboard:
#   Webhooks → Add webhook → URL = https://<this-host>/email/inbound
#   Events = "email.received" (or the inbound topic)
#
# Inbound email requires MX records on the sending domain to point at
# Resend. See: https://resend.com/docs/inbound. This is a DNS-side task.
#
# The handler always returns 200 — failing loudly would cause Resend to
# retry forever. Errors are logged and a failure flag is returned in the
# body so operators can see them in the Resend dashboard.


async def _sb_get(client: httpx.AsyncClient, path: str):
    url = f"{os.environ.get('SUPABASE_URL', '')}/rest/v1{path}"
    headers = {
        "apikey": os.environ.get("SUPABASE_ANON", ""),
        "Authorization": f"Bearer {os.environ.get('SUPABASE_ANON', '')}",
        "Content-Type": "application/json",
    }
    try:
        r = await client.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"supabase GET {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"supabase GET {path} failed: {e}")
        return None


async def _sb_post(client: httpx.AsyncClient, path: str, body: Dict[str, Any]):
    url = f"{os.environ.get('SUPABASE_URL', '')}/rest/v1{path}"
    headers = {
        "apikey": os.environ.get("SUPABASE_ANON", ""),
        "Authorization": f"Bearer {os.environ.get('SUPABASE_ANON', '')}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    try:
        r = await client.post(url, headers=headers, content=json.dumps(body), timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            logger.warning(f"supabase POST {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"supabase POST {path} failed: {e}")
        return None


async def _sb_patch(client: httpx.AsyncClient, path: str, body: Dict[str, Any]):
    url = f"{os.environ.get('SUPABASE_URL', '')}/rest/v1{path}"
    headers = {
        "apikey": os.environ.get("SUPABASE_ANON", ""),
        "Authorization": f"Bearer {os.environ.get('SUPABASE_ANON', '')}",
        "Content-Type": "application/json",
    }
    try:
        await client.patch(url, headers=headers, content=json.dumps(body), timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        logger.warning(f"supabase PATCH {path} failed: {e}")


def _extract_inbound(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Resend's inbound payload to a consistent shape."""
    # Resend wraps events in {"type": "email.received", "data": {...}}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    # from can be a string or a list of {name,email}
    from_val = data.get("from") or payload.get("from") or ""
    if isinstance(from_val, list) and from_val:
        from_val = from_val[0]
    if isinstance(from_val, dict):
        from_email = str(from_val.get("email") or "").strip().lower()
    else:
        # Strip "Name <email@x>" if present
        s = str(from_val).strip()
        if "<" in s and ">" in s:
            s = s.split("<", 1)[1].rsplit(">", 1)[0]
        from_email = s.strip().lower()

    subject = data.get("subject") or payload.get("subject") or ""
    text = (data.get("text") or payload.get("text") or "").strip()
    html = data.get("html") or payload.get("html") or ""
    body = text or _strip_html(html)
    in_reply_to = data.get("in_reply_to") or payload.get("in_reply_to") or ""
    message_id = data.get("message_id") or payload.get("message_id") or data.get("id") or ""

    return {
        "from_email": from_email,
        "subject": str(subject),
        "body": str(body),
        "in_reply_to": str(in_reply_to),
        "message_id": str(message_id),
    }


def _strip_html(html: str) -> str:
    """Ultra-simple HTML-to-text fallback. Sufficient for preview bodies."""
    if not html:
        return ""
    import re as _re
    s = _re.sub(r"<script[\s\S]*?</script>", " ", html, flags=_re.IGNORECASE)
    s = _re.sub(r"<style[\s\S]*?</style>", " ", s, flags=_re.IGNORECASE)
    s = _re.sub(r"<br\s*/?>", "\n", s, flags=_re.IGNORECASE)
    s = _re.sub(r"</p>", "\n\n", s, flags=_re.IGNORECASE)
    s = _re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return s.strip()


@router.post("/email/inbound")
async def inbound_email(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored", "reason": "non-json payload"}

    parsed = _extract_inbound(payload)
    from_email = parsed["from_email"]
    if not from_email:
        logger.info("[INBOUND] no from address in payload — ignored")
        return {"status": "ignored", "reason": "no_from"}

    async with httpx.AsyncClient() as client:
        # Match by email — business ambiguity handled by taking the first
        # contact found. Resend doesn't pass business routing info.
        rows = await _sb_get(client, f"/contacts?email=eq.{from_email}&select=id,name,business_id,health_score&limit=1")
        if not rows:
            logger.info(f"[INBOUND] unknown sender: {from_email}")
            return {"status": "unknown_sender", "from": from_email}

        contact = rows[0]
        business_id = contact.get("business_id")
        contact_id = contact.get("id")

        # 1. Event on the contact's timeline
        await _sb_post(client, "/events", {
            "business_id": business_id,
            "contact_id": contact_id,
            "event_type": "email_reply_received",
            "data": {
                "from": from_email,
                "subject": parsed["subject"],
                "body_preview": parsed["body"][:500],
                "full_body": parsed["body"][:20000],
                "in_reply_to": parsed["in_reply_to"],
                "message_id": parsed["message_id"],
            },
            "source": "resend_inbound",
        })

        # 2. Notification for the practitioner
        await _sb_post(client, "/chief_notifications", {
            "business_id": business_id,
            "type": "urgent",
            "title": f"Reply from {contact.get('name') or from_email}",
            "body": f"Re: {parsed['subject']}\n\n{parsed['body'][:200]}",
            "suggested_action": f"View reply from {contact.get('name') or 'contact'}",
            "status": "unread",
            "data": {
                "contact_id": contact_id,
                "event_type": "email_reply_received",
                "subject": parsed["subject"],
            },
        })

        # 3. Bump contact health — they engaged
        current = contact.get("health_score") or 50
        await _sb_patch(client, f"/contacts?id=eq.{contact_id}", {
            "health_score": min(100, int(current) + 10),
            "last_interaction": datetime.now(timezone.utc).isoformat(),
        })

        logger.info(f"[INBOUND] processed reply from {from_email} -> contact={contact_id}")
        return {"status": "processed", "contact_id": contact_id}


# ═══════════════════════════════════════════════════════════════════════
# WEBHOOK — email.opened (open tracking)
# ═══════════════════════════════════════════════════════════════════════
#
# When Resend reports an email.opened event, we look the recipient up by
# email, find their most recent invoice that we sent, and flip the
# invoice from "sent" -> "viewed". We post an `invoice_viewed` timeline
# event and a chief_notification so the practitioner sees the open in
# real time.
#
# Resend dashboard:
#   resend.com -> Webhooks -> Add webhook
#   URL:    https://<this-host>/email/webhook
#   Events: email.opened
#
# We always return 200 so Resend doesn't retry — failures are logged.

def _extract_open_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Resend wraps webhook payloads as {type, created_at, data: {...}}.
    Pull out a normalized {type, to_email, subject, opened_at} shape."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    evt_type = (payload.get("type") or "").strip().lower()
    to_field = data.get("to") or data.get("to_email") or ""
    if isinstance(to_field, list):
        to_email = ""
        for item in to_field:
            if isinstance(item, str):
                to_email = item; break
            if isinstance(item, dict):
                to_email = item.get("email") or ""
                if to_email:
                    break
    else:
        to_email = str(to_field)
    return {
        "type": evt_type,
        "to_email": (to_email or "").strip().lower(),
        "subject": (data.get("subject") or "").strip(),
        "opened_at": payload.get("created_at") or data.get("opened_at") or datetime.now(timezone.utc).isoformat(),
    }


@router.post("/email/webhook")
async def resend_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored", "reason": "non-json payload"}

    evt = _extract_open_event(payload)
    if evt["type"] != "email.opened":
        # Other event types (delivered, bounced, etc) — accept and ignore
        return {"status": "ignored", "reason": f"unsupported event {evt['type']}"}

    to_email = evt["to_email"]
    if not to_email:
        return {"status": "ignored", "reason": "no recipient"}

    async with httpx.AsyncClient() as client:
        rows = await _sb_get(client, f"/contacts?email=eq.{to_email}&select=id,name,business_id&limit=1")
        if not rows:
            logger.info(f"[OPEN] unknown recipient: {to_email}")
            return {"status": "unknown_recipient", "to": to_email}
        contact = rows[0]
        contact_id = contact.get("id")
        contact_name = contact.get("name") or to_email
        business_id = contact.get("business_id")

        # Find the most recent sent invoice for this contact that hasn't
        # already been flipped to viewed/paid. We don't try to subject-
        # match because Resend's open event doesn't always carry the
        # original subject reliably.
        invoices = await _sb_get(
            client,
            f"/invoices?contact_id=eq.{contact_id}&business_id=eq.{business_id}"
            f"&status=eq.sent&select=id,invoice_number,total,sent_at"
            f"&order=sent_at.desc.nullslast,created_at.desc&limit=1",
        )
        if not invoices:
            # Maybe already-viewed: skip silently
            logger.info(f"[OPEN] no matching sent invoice for {to_email}")
            return {"status": "no_match"}

        inv = invoices[0]
        invoice_id = inv.get("id")
        invoice_number = inv.get("invoice_number")
        total = float(inv.get("total") or 0)
        opened_at = evt["opened_at"]

        await _sb_patch(client, f"/invoices?id=eq.{invoice_id}", {
            "status": "viewed",
            "viewed_at": opened_at,
        })

        await _sb_post(client, "/events", {
            "business_id": business_id,
            "contact_id": contact_id,
            "event_type": "invoice_viewed",
            "data": {
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "total": total,
                "to_email": to_email,
                "opened_at": opened_at,
            },
            "source": "resend_webhook",
        })

        await _sb_post(client, "/chief_notifications", {
            "business_id": business_id,
            "type": "info",
            "title": f"👁️ {contact_name} opened {invoice_number}",
            "body": f"{contact_name} viewed Invoice {invoice_number} (${total:,.2f}) — they haven't paid yet.",
            "suggested_action": "Send a friendly nudge?",
            "status": "unread",
            "data": {
                "kind": "invoice_viewed",
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "contact_id": contact_id,
                "contact_name": contact_name,
                "total": total,
            },
        })

        logger.info(f"[OPEN] {contact_name} opened {invoice_number}")
        return {"status": "viewed", "invoice_id": invoice_id, "contact_id": contact_id}
