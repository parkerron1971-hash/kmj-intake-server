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
       RESEND_FROM_EMAIL        — optional. Defaults to noreply@solutionist.app.
                                  Must be on a verified Resend domain, OR use
                                  `onboarding@resend.dev` for pre-verification testing.

Until a domain is verified, Resend only accepts sends to the account's
own address. Add the SPF/DKIM/DMARC records Resend surfaces in its
dashboard to unlock general sends.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

RESEND_URL = "https://api.resend.com/emails"
DEFAULT_FROM_EMAIL = "noreply@solutionist.app"
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
