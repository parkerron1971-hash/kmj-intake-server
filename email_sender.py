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

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time as _time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

import webhook_guard
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from auth_supabase import require_user, AuthedUser
from pydantic import BaseModel
import pii_mask

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


class EmailAttachment(BaseModel):
    """Resend attachment — either inline content (base64-encoded) OR a
    `path` URL Resend will fetch. Most callers should use `content`."""
    filename: str
    content: Optional[str] = None       # base64-encoded file bytes
    path: Optional[str] = None          # alternative — a URL Resend fetches
    content_type: Optional[str] = None  # e.g. 'text/csv'


class SendEmailRequest(BaseModel):
    to_email: str
    to_name: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    subject: str
    body: str  # HTML or plain text
    reply_to: Optional[str] = None
    business_id: str
    # Optional file attachments — passed through to Resend's `attachments`
    # field. Resend accepts a list of {filename, content (base64), ...}.
    attachments: Optional[List[EmailAttachment]] = None


class SendEmailResponse(BaseModel):
    ok: bool
    id: Optional[str] = None
    provider_response: Optional[Dict[str, Any]] = None


def _unsub_secret() -> str:
    return (os.environ.get("EMAIL_UNSUB_SECRET")
            or os.environ.get("CUSTOMER_TOKEN_SECRET")
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "solutionist"))


def _unsub_sig(email: str) -> str:
    return hmac.new(_unsub_secret().encode(), (email or "").strip().lower().encode(),
                    hashlib.sha256).hexdigest()[:32]


def _unsubscribe_url(email: str) -> str:
    domain = os.environ.get("APP_DOMAIN", "https://mysolutionist.app").rstrip("/")
    addr = (email or "").strip().lower()
    return f"{domain}/email/unsubscribe?e={_urlq(addr)}&s={_unsub_sig(addr)}"


def _urlq(v: str) -> str:
    from urllib.parse import quote
    return quote(v, safe="")


# ─── Per-business email identity (S6) ────────────────────────────────
# Operators can send from their own domain. The domain lifecycle
# (connect → DNS → verify → active) lives in email_domains_router.py and
# stores its state in businesses.settings.email_domain (a settings blob,
# same pattern as settings.giving). THIS is the resolution seam: given a
# business row, return the (from_email, from_name) a business-originated
# send should use — the verified custom sender when one exists, else the
# platform default the caller supplied.
#
# Resolution NEVER takes sending down: any error falls back to the
# platform default. Reply routing is deliberately untouched — the routed
# reply-to (reply+{biz8}+{contact8}@INBOUND_EMAIL_DOMAIN) keeps pointing
# at the platform's inbound webhook regardless of the custom from, so
# replies keep landing in the app.

EMAIL_DOMAIN_SETTINGS_KEY = "email_domain"


def email_domain_settings(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """settings.email_domain sub-dict; tolerate missing/malformed."""
    raw = (settings or {}).get(EMAIL_DOMAIN_SETTINGS_KEY) or {}
    return raw if isinstance(raw, dict) else {}


def resolve_from_address(
    business: Optional[Dict[str, Any]],
    *,
    default_email: Optional[str] = None,
    default_name: Optional[str] = None,
) -> tuple:
    """(from_email, from_name) for a business-originated send.

    Returns the business's VERIFIED custom sender when one is fully
    configured; otherwise the platform default for this send type
    (`default_email`, falling back to RESEND_FROM_EMAIL / the global
    default). Partial config (no domain, no local part, not verified)
    always falls back — we never guess half an address.
    """
    platform_email = (default_email
                     or os.environ.get("RESEND_FROM_EMAIL")
                     or DEFAULT_FROM_EMAIL)
    try:
        cfg = email_domain_settings((business or {}).get("settings"))
        if (cfg.get("status") == "verified"):
            domain = str(cfg.get("domain") or "").strip().lower().rstrip(".")
            local = str(cfg.get("from_local_part") or "").strip()
            if domain and local and "@" not in local:
                name = (str(cfg.get("from_name") or "").strip()
                        or default_name
                        or (business or {}).get("name"))
                return f"{local}@{domain}", name
    except Exception:  # malformed settings must never block a send
        pass
    return platform_email, default_name


def _platform_from_addresses() -> set:
    """Platform from-addresses a business identity may override. An
    explicit custom from (e.g. a caller that already resolved one, or a
    platform stream like invites@/billing@) is never overridden."""
    addrs = {
        DEFAULT_FROM_EMAIL,
        "hello@mysolutionist.app",
        "receipts@mysolutionist.app",
        "reports@solutionist.studio",
        (os.environ.get("RESEND_FROM_EMAIL") or "").strip().lower(),
    }
    return {a for a in addrs if a}


def _routed_reply_biz_prefix(reply_to: Optional[str]) -> Optional[str]:
    """First-8 business-id prefix from a routed reply-to
    (reply+{biz8}+{contact8}@INBOUND_EMAIL_DOMAIN), else None. Lets
    business-originated sends that already carry the routed reply-to
    (Chief sends, campaigns) resolve their custom identity without every
    caller threading business_id through — the same prefix resolution
    the inbound webhook already trusts."""
    if not reply_to:
        return None
    domain = _inbound_domain()
    if not domain:
        return None
    addr = reply_to.strip().lower()
    if not addr.endswith(f"@{domain}"):
        return None
    local = addr.split("@", 1)[0]
    if not local.startswith("reply+"):
        return None
    parts = local[len("reply+"):].split("+")
    return parts[0] if parts and parts[0] else None


# 60s TTL cache so a campaign blast doesn't re-fetch the same business
# row per contact. Keyed by the lookup string; stores the row (or None).
_IDENTITY_CACHE: Dict[str, tuple] = {}
_IDENTITY_CACHE_TTL = 60.0


async def _business_identity_row(
    business_id: Optional[str] = None,
    biz_prefix: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch id+name+settings for identity resolution. Fails open (None)."""
    key = f"id:{business_id}" if business_id else f"pfx:{biz_prefix}"
    now = _time.monotonic()
    hit = _IDENTITY_CACHE.get(key)
    if hit and (now - hit[0]) < _IDENTITY_CACHE_TTL:
        return hit[1]
    if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return None
    params: Dict[str, str] = {"select": "id,name,settings", "limit": "1"}
    if business_id:
        params["id"] = f"eq.{business_id}"
    elif biz_prefix:
        params["id"] = f"like.{biz_prefix}*"
    else:
        return None
    row: Optional[Dict[str, Any]] = None
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(
                f"{os.environ.get('SUPABASE_URL', '')}/rest/v1/businesses",
                headers=_sb_service_headers(), params=params)
            if r.status_code < 400:
                rows = r.json() if r.text else []
                row = rows[0] if rows else None
    except Exception:
        row = None
    _IDENTITY_CACHE[key] = (now, row)
    return row


async def _business_row_for_send(business_id: Optional[str],
                                 reply_to: Optional[str]) -> Optional[Dict[str, Any]]:
    """The business a send belongs to, for the branded layout. Same
    attribution rule as the identity seam: an explicit business_id, or
    a routed reply-to we can parse a prefix out of. Fails open (None):
    a lookup problem means plain text, never a failed send."""
    try:
        if business_id:
            return await _business_identity_row(business_id=business_id)
        prefix = _routed_reply_biz_prefix(reply_to)
        if prefix:
            return await _business_identity_row(biz_prefix=prefix)
    except Exception:
        return None
    return None

async def _apply_business_identity(
    from_email: str,
    from_name: Optional[str],
    business_id: Optional[str],
    reply_to: Optional[str],
) -> tuple:
    """The in-funnel half of the seam: when the caller's from is a
    platform default and the send is attributable to a business (explicit
    business_id, or a routed reply-to), swap in that business's verified
    custom sender. Anything else passes through untouched."""
    try:
        if (from_email or "").strip().lower() not in _platform_from_addresses():
            return from_email, from_name
        biz = None
        if business_id:
            biz = await _business_identity_row(business_id=business_id)
        else:
            prefix = _routed_reply_biz_prefix(reply_to)
            if prefix:
                biz = await _business_identity_row(biz_prefix=prefix)
        if not biz:
            return from_email, from_name
        return resolve_from_address(
            biz, default_email=from_email, default_name=from_name)
    except Exception:  # resolution must never take sending down
        return from_email, from_name


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


# ─── Suppression list (hardening pass 1, 2026-07-03) ────────────────
# Resend tells us about hard bounces + spam complaints via the webhook
# below; we record them in email_suppressions (service-role-only table,
# supabase/email-suppressions-migration.sql) and refuse to send to those
# addresses again. Reads FAIL OPEN — a missing table or transient DB
# error must never take sending down.

_SUPPRESS_PATH = "/email_suppressions"


def _sb_service_headers() -> Dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


async def is_suppressed(email: str) -> Optional[Dict[str, Any]]:
    """Suppression row for this address, or None. Fails open."""
    addr = (email or "").strip().lower()
    if not addr or not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return None
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(
                f"{os.environ.get('SUPABASE_URL', '')}/rest/v1{_SUPPRESS_PATH}",
                headers=_sb_service_headers(),
                params={"email": f"eq.{addr}", "select": "email,reason,last_seen", "limit": "1"},
            )
            if r.status_code >= 400:
                return None  # migration not run / transient — fail open
            rows = r.json() if r.text else []
            return rows[0] if rows else None
    except Exception:
        return None


async def add_suppression(email: str, reason: str, event_type: str) -> None:
    addr = (email or "").strip().lower()
    if not addr or not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(
                f"{os.environ.get('SUPABASE_URL', '')}/rest/v1{_SUPPRESS_PATH}",
                headers={**_sb_service_headers(), "Prefer": "resolution=merge-duplicates"},
                content=json.dumps({
                    "email": addr,
                    "reason": reason,
                    "event_type": event_type,
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                }),
            )
            if r.status_code >= 400:
                logger.warning(f"suppression upsert failed {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"suppression upsert failed: {e}")


async def send_via_resend(
    *,
    to_email: str,
    to_name: Optional[str],
    from_email: str,
    from_name: Optional[str],
    subject: str,
    body: str,
    reply_to: Optional[str],
    attachments: Optional[List[Dict[str, Any]]] = None,
    business_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Low-level Resend client. Raises on API error.

    `attachments` is a list of {filename, content (base64) | path (url),
    content_type?} dicts. Passed through to Resend verbatim.

    `business_id` (optional) marks the send as business-originated: when
    the given from_email is a platform default and that business has a
    VERIFIED custom sending domain (settings.email_domain), the send goes
    out as the business's own identity. Sends whose reply_to is the
    routed inbound address resolve the same way without the param.
    Suppression, List-Unsubscribe, and reply routing are identical either
    way — identity only changes the from line.
    """
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        raise RuntimeError("RESEND_API_KEY is not configured")

    # Suppression check — every send path funnels through here, so one
    # gate protects invoices, reminders, booking confirmations, Chief
    # sends, everything.
    sup = await is_suppressed(to_email)
    if sup:
        why = "marked a previous email as spam" if sup.get("reason") == "complained" else "hard-bounced"
        logger.warning(f"send BLOCKED — {pii_mask.mask_email(to_email)} is suppressed ({sup.get('reason')})")
        raise RuntimeError(
            f"Not sent: {to_email} {why} previously. Verify the address is right; "
            f"a platform admin can clear it from email_suppressions if it was a mistake."
        )

    # Per-business identity (S6): after the suppression gate, before the
    # payload — a suppressed address never costs a settings lookup.
    from_email, from_name = await _apply_business_identity(
        from_email, from_name, business_id, reply_to)

    payload: Dict[str, Any] = {
        "from": _format_address(from_email, from_name),
        "to": [_format_address(to_email, to_name)],
        "subject": subject or "(no subject)",
        # CAN-SPAM / bulk-sender compliance (beta-readiness audit): every
        # send carries a one-click unsubscribe. The URL is signed so it
        # can't be forged; hitting it adds the address to the suppression
        # list that already gates all sends.
        "headers": {
            "List-Unsubscribe": (
                f"<{_unsubscribe_url(to_email)}>, "
                f"<mailto:{os.environ.get('UNSUBSCRIBE_EMAIL', 'unsubscribe@mysolutionist.app')}"
                f"?subject=unsubscribe>"),
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }
    if _body_is_html(body):
        # A caller that built its own markup keeps it.
        payload["html"] = body
    else:
        # Business-originated plain text leaves as a laid-out, branded
        # email (email_layout) with the composed text as the alternative.
        # Platform mail with no business behind it stays plain.
        biz_row = await _business_row_for_send(business_id, reply_to)
        rendered = None
        if biz_row:
            try:
                import email_layout
                rendered = email_layout.render_for_send(
                    body, biz_row, unsubscribe_url=_unsubscribe_url(to_email))
            except Exception as e:  # the layout must never cost a send
                logger.warning(f"email layout failed, sending plain text: {e}")
        if rendered:
            payload["html"], payload["text"] = rendered
        else:
            payload["text"] = body
    if reply_to:
        payload["reply_to"] = reply_to
    if attachments:
        cleaned = []
        for a in attachments:
            if not isinstance(a, dict):
                continue
            if not a.get("filename"):
                continue
            if not (a.get("content") or a.get("path")):
                continue
            cleaned.append(a)
        if cleaned:
            payload["attachments"] = cleaned

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
async def send_email(req: SendEmailRequest, user: AuthedUser = Depends(require_user)):
    # Any signed-in caller could send through the platform's Resend
    # account attributed to ANY business_id — the send is logged and
    # routed under that business, so it spends someone else's sending
    # reputation and appears in their trail.
    import business_access
    business_access.assert_access(str(req.business_id), user, "member")
    if not os.environ.get("RESEND_API_KEY"):
        raise HTTPException(500, "Resend API key not configured")

    if not req.to_email or "@" not in req.to_email:
        raise HTTPException(400, "Valid to_email is required")

    from_email = req.from_email or os.environ.get("RESEND_FROM_EMAIL") or DEFAULT_FROM_EMAIL
    from_name = req.from_name or DEFAULT_FROM_NAME

    try:
        # Convert attachment models to plain dicts; drop malformed
        # entries so a single bad attachment doesn't take the send down.
        attachments_list: Optional[List[Dict[str, Any]]] = None
        if req.attachments:
            attachments_list = [
                {
                    "filename": a.filename,
                    **({"content": a.content} if a.content else {}),
                    **({"path": a.path} if a.path else {}),
                    **({"content_type": a.content_type} if a.content_type else {}),
                }
                for a in req.attachments
                if a.filename and (a.content or a.path)
            ]

        data = await send_via_resend(
            to_email=req.to_email,
            to_name=req.to_name,
            from_email=from_email,
            from_name=from_name,
            subject=req.subject,
            body=req.body,
            reply_to=req.reply_to or from_email,
            attachments=attachments_list,
            business_id=req.business_id,
        )
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    logger.info(
        f"Email sent business={req.business_id} to={req.to_email} "
        f"subject_len={len(req.subject or '')} id={data.get('id')}"
    )
    return SendEmailResponse(ok=True, id=data.get("id"), provider_response=data)


class EmailPreviewRequest(BaseModel):
    business_id: str
    body: str
    subject: Optional[str] = None
    contact_name: Optional[str] = None


@router.post("/email/preview")
async def email_preview(req: EmailPreviewRequest, user: AuthedUser = Depends(require_user)):
    """What a business email will look like when it leaves: placeholders
    filled, closing line + signature + disclaimer appended the way a
    Chief send appends them, then the branded layout. Read-only; the
    compose sheet and the templates page render the result."""
    import business_access
    business_access.assert_access(str(req.business_id), user, "member")
    biz = await _business_identity_row(business_id=req.business_id)
    if not biz:
        raise HTTPException(404, "business not found")
    import email_layout
    values = email_layout.placeholder_values(biz, contact_name=req.contact_name)
    body = email_layout.fill_placeholders(req.body or "", values)
    subject = email_layout.fill_placeholders(req.subject or "", values)
    composed = email_layout.compose_trailers(body, biz.get("settings"))
    html_body, text_body = email_layout.render_for_send(composed, biz, unsubscribe_url=None)
    from_email, from_name = resolve_from_address(
        biz, default_email=os.environ.get("RESEND_FROM_EMAIL") or DEFAULT_FROM_EMAIL,
        default_name=biz.get("name"))
    return {"ok": True, "subject": subject, "html": html_body, "text": text_body,
            "from_email": from_email, "from_name": from_name}

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
        "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
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
        "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
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
        "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
        "Content-Type": "application/json",
    }
    try:
        await client.patch(url, headers=headers, content=json.dumps(body), timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as e:
        logger.warning(f"supabase PATCH {path} failed: {e}")


def _normalize_address_field(val: Any) -> List[str]:
    """Resend's `to` / `cc` fields can be a string or a list of strings or
    a list of {name, email} dicts. Return a flat list of plain email
    addresses (lower-cased), with any "Name <addr>" wrappers stripped."""
    out: List[str] = []
    if val is None:
        return out
    items = val if isinstance(val, list) else [val]
    for item in items:
        if isinstance(item, dict):
            addr = str(item.get("email") or item.get("address") or "")
        else:
            addr = str(item or "")
        addr = addr.strip()
        if "<" in addr and ">" in addr:
            addr = addr.split("<", 1)[1].rsplit(">", 1)[0]
        addr = addr.strip().lower()
        if addr:
            out.append(addr)
    return out


def _inbound_domain() -> str:
    """The MX-receiving domain for inbound replies. When unset, the
    routed reply-to feature is silently disabled — outbound emails fall
    back to the practitioner's signature email and inbound parsing
    skips the routed-address path."""
    return (os.environ.get("INBOUND_EMAIL_DOMAIN") or "").strip().lower()


def build_routed_reply_to(business_id: str, contact_id: Optional[str]) -> Optional[str]:
    """Encode (business, contact) into a Reply-To address so that when
    the recipient hits Reply, the message lands on our /email/inbound
    webhook and we can route it back to the right practitioner.

    Format: reply+{biz_first8}+{contact_first8}@<INBOUND_EMAIL_DOMAIN>

    Returns None when no inbound domain is configured (in which case
    callers should fall back to the practitioner's signature email).
    """
    domain = _inbound_domain()
    if not domain or not business_id:
        return None
    biz_short = (business_id or "")[:8]
    contact_short = (contact_id or "")[:8] if contact_id else "anon"
    return f"reply+{biz_short}+{contact_short}@{domain}"


# build_routed_reply_to emits the first 8 chars of a uuid, or the literal
# "anon" for the contact half. Anything else is not an address we wrote.
#
# This is load-bearing, not cosmetic: both halves are interpolated into a
# PostgREST query string, so an unvalidated value is a query injection —
# `reply+%+%@domain` turns `id=like.{biz}%` into a match-anything filter
# and binds a stranger's mail to an arbitrary business, and an `&` gets a
# whole extra PostgREST parameter. The sender chooses this address, so
# treat it as hostile and reject anything that isn't the exact shape we
# emit. (Values are percent-encoded at the call site as well — belt and
# braces, since the shape check is what actually makes them safe.)
_ROUTE_TOKEN_RE = re.compile(r"^[0-9a-f]{8}$")


def _valid_route_token(tok: str, *, allow_anon: bool = False) -> bool:
    if allow_anon and tok == "anon":
        return True
    return bool(_ROUTE_TOKEN_RE.match(tok or ""))


def _parse_routed_address(addr: str) -> Optional[Dict[str, str]]:
    """Reverse of build_routed_reply_to. Returns {biz_short, contact_short}
    when the address matches our inbound routing pattern, else None."""
    if not addr:
        return None
    domain = _inbound_domain()
    if not addr.lower().endswith(f"@{domain}") if domain else not "@inbound." in addr.lower():
        # If the env-configured domain is set, require an exact match.
        # If unset, accept any @inbound.* domain so a misconfigured
        # deploy still surfaces routing attempts in logs.
        if domain:
            return None
    local = addr.split("@", 1)[0]
    if not local.startswith("reply+"):
        return None
    parts = local[len("reply+"):].split("+")
    if len(parts) < 2:
        return None
    biz_short, contact_short = parts[0].lower(), parts[1].lower()
    if not _valid_route_token(biz_short):
        logger.warning("[INBOUND] routed address rejected — malformed business token")
        return None
    if not _valid_route_token(contact_short, allow_anon=True):
        logger.warning("[INBOUND] routed address rejected — malformed contact token")
        return None
    return {"biz_short": biz_short, "contact_short": contact_short}


# Local parts at INBOUND_EMAIL_DOMAIN that belong to the PLATFORM, not to
# any practitioner business. Mail to these lands in the Mission Control
# inbox (platform_emails) instead of the contact-reply pipeline.
PLATFORM_INBOX_DEFAULT_LOCALS = "kevin,support,hello,admin,info,billing,contact"


def _platform_local_parts() -> List[str]:
    raw = os.environ.get("PLATFORM_INBOX_ADDRESSES") or PLATFORM_INBOX_DEFAULT_LOCALS
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _match_platform_address(to_addresses: List[str]) -> Optional[str]:
    """First recipient that is a named platform address (kevin@<domain>,
    support@<domain>, ...). When INBOUND_EMAIL_DOMAIN is configured the
    domain must match exactly; when it isn't, match on local part alone
    so a misconfigured deploy still routes rather than drops."""
    domain = _inbound_domain()
    locals_ = set(_platform_local_parts())
    for addr in to_addresses:
        if "@" not in addr:
            continue
        local, _, dom = addr.partition("@")
        if domain and dom != domain:
            continue
        if local in locals_:
            return addr
    return None


async def _store_platform_email(
    client: httpx.AsyncClient,
    parsed: Dict[str, Any],
    to_address: str,
    catchall: bool,
) -> Optional[str]:
    """Persist an inbound message to the Mission Control inbox. Full HTML
    on purpose — verification links must survive intact."""
    row = {
        "to_address": to_address,
        "from_email": parsed["from_email"],
        "from_name": parsed.get("from_name") or "",
        "subject": parsed["subject"],
        "body_text": (parsed.get("raw_text") or parsed.get("body") or "")[:50000],
        "body_html": (parsed.get("raw_html_full") or "")[:500000] or None,
        "message_id": parsed["message_id"] or None,
        "in_reply_to": parsed["in_reply_to"] or None,
        "catchall": catchall,
    }
    inserted = await _sb_post(client, "/platform_emails", row)
    if isinstance(inserted, list) and inserted:
        return inserted[0].get("id")
    if isinstance(inserted, dict):
        return inserted.get("id")
    return None


def _extract_inbound(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Resend's inbound payload to a consistent shape.

    NOTE: Resend's `email.received` webhook does NOT include the body —
    only metadata (from/to/subject/email_id). The body must be fetched
    separately via /emails/{id} on the Resend API. _fetch_inbound_body
    below does that. _extract_inbound just returns whatever is in the
    payload (typically empty body).
    """
    # Resend wraps events in {"type": "email.received", "data": {...}}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    # from can be a string or a list of {name,email}
    from_val = data.get("from") or payload.get("from") or ""
    from_name = ""
    if isinstance(from_val, list) and from_val:
        from_val = from_val[0]
    if isinstance(from_val, dict):
        from_email = str(from_val.get("email") or "").strip().lower()
        from_name = str(from_val.get("name") or "").strip()
    else:
        # Strip "Name <email@x>" if present
        s = str(from_val).strip()
        if "<" in s and ">" in s:
            from_name = s.split("<", 1)[0].strip().strip('"')
            s = s.split("<", 1)[1].rsplit(">", 1)[0]
        from_email = s.strip().lower()

    # Recipient addresses — checked against the routed reply-to pattern.
    to_addresses = _normalize_address_field(data.get("to") or payload.get("to"))
    cc_addresses = _normalize_address_field(data.get("cc") or payload.get("cc"))

    subject = data.get("subject") or payload.get("subject") or ""
    text = (data.get("text") or payload.get("text") or "").strip()
    html = data.get("html") or payload.get("html") or ""
    body = text or _strip_html(html)
    in_reply_to = data.get("in_reply_to") or payload.get("in_reply_to") or ""
    # Resend uses different keys for the inbound message id depending on
    # webhook version: email_id (current), message_id, or id.
    message_id = (
        data.get("email_id")
        or data.get("message_id")
        or payload.get("message_id")
        or data.get("id")
        or ""
    )

    return {
        "from_email": from_email,
        "from_name": from_name,
        "to_addresses": to_addresses + cc_addresses,
        "subject": str(subject),
        "body": str(body),
        "raw_text": str(text),
        "raw_html": str(html)[:5000],
        # Untruncated HTML for the platform inbox — a verification email's
        # click-through link routinely lives past the 5 KB preview cap.
        "raw_html_full": str(html),
        "in_reply_to": str(in_reply_to),
        "message_id": str(message_id),
    }


async def _fetch_inbound_body(client: httpx.AsyncClient, email_id: str) -> Dict[str, str]:
    """Fetch the full email body from Resend's INBOUND endpoint.

    Resend's email.received webhook only includes metadata, not the
    body. The correct endpoint for received messages is
        GET /emails/receiving/{id}
    NOT /emails/{id} — the latter returns emails WE sent, not emails
    we received, and 404s for inbound message ids.

    Confirmed against Resend's SDK example:
        resend.emails.receiving.get(event.data.email_id)

    Returns {'text': ..., 'html': ...} (both possibly empty on failure).
    """
    if not email_id:
        return {"text": "", "html": ""}
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        logger.warning("[INBOUND] RESEND_API_KEY missing - can't fetch body")
        return {"text": "", "html": ""}
    url = f"https://api.resend.com/emails/receiving/{email_id}"
    try:
        r = await client.get(
            url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=HTTP_TIMEOUT,
        )
        logger.info(f"[INBOUND] receiving API status={r.status_code} email_id={email_id}")
        if r.status_code >= 400:
            logger.warning(f"[INBOUND] receiving API error: {r.status_code} {r.text[:300]}")
            return {"text": "", "html": ""}

        body = r.json() if r.text else {}
        if isinstance(body, dict):
            keys = list(body.keys())
            logger.info(f"[INBOUND] receiving API response keys: {keys}")
            # Resend's receiving response shape isn't fully documented at
            # the field level - try the standard names plus a couple of
            # alternatives so we don't lose the body if they rename one.
            text = (
                body.get("text")
                or body.get("body_text")
                or body.get("body")
                or body.get("content")
                or ""
            )
            html = (
                body.get("html")
                or body.get("body_html")
                or ""
            )
            text = str(text or "")
            html = str(html or "")
            if not text and not html:
                # Surface the full payload (capped) so an unfamiliar
                # field name shows up in Railway logs and we can adapt.
                logger.warning(f"[INBOUND] no text/html on receiving response (keys={list(body.keys()) if isinstance(body, dict) else type(body).__name__})")
            else:
                logger.info(
                    f"[INBOUND] fetched body via receiving API: "
                    f"text_len={len(text)} html_len={len(html)}"
                )
            return {"text": text, "html": html}
        logger.warning(f"[INBOUND] receiving API non-dict body (type={type(body).__name__})")
        return {"text": "", "html": ""}
    except httpx.HTTPError as e:
        logger.warning(f"[INBOUND] body fetch error: {e}")
        return {"text": "", "html": ""}


def _strip_quoted_reply(text: str) -> str:
    """Trim quoted previous-email content so the stored body is just
    the new reply. Stops at the first quote marker we recognize."""
    if not text:
        return ""
    lines = text.split("\n")
    out: List[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith(">"):
            break
        if s.startswith("On ") and " wrote:" in s:
            break
        if s.startswith("From:") and len(out) > 1:
            break
        if s in ("---", "___"):
            break
        if "Original Message" in s:
            break
        if s.startswith("Sent from my "):
            break
        out.append(line)
    return "\n".join(out).rstrip()


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


def _verify_resend_signature(raw_body: bytes, headers: Any) -> bool:
    """Arc 29 — verify the Resend (Svix) webhook signature.

    Resend signs webhooks with Svix: signed content is
    "{svix-id}.{svix-timestamp}.{body}", HMAC-SHA256'd with the
    base64-decoded secret (the part after the 'whsec_' prefix), and the
    svix-signature header is a space-separated list of 'v1,<b64sig>'.

    Fail-CLOSED when unconfigured: an inbound body reaches Chief's system
    prompt verbatim, and Chief can send, so an unverifiable payload is
    dropped rather than trusted. Set RESEND_WEBHOOK_SECRET on Railway. To
    knowingly run unverified while wiring the provider up, see
    webhook_guard.WEBHOOK_ALLOW_UNSIGNED.
    Replay window: 5 minutes on the svix timestamp."""
    secret = (os.environ.get("RESEND_WEBHOOK_SECRET") or "").strip()
    if not secret:
        if webhook_guard.unsigned_allowed("resend"):
            return True
        webhook_guard.reject_unsigned("resend", "RESEND_WEBHOOK_SECRET is not set")
        return False
    try:
        svix_id = headers.get("svix-id") or headers.get("webhook-id") or ""
        svix_ts = headers.get("svix-timestamp") or headers.get("webhook-timestamp") or ""
        svix_sig = headers.get("svix-signature") or headers.get("webhook-signature") or ""
        if not (svix_id and svix_ts and svix_sig):
            logger.warning("[INBOUND] missing svix headers — rejected")
            return False
        # Replay guard (5 min).
        try:
            if abs(_time.time() - int(svix_ts)) > 300:
                logger.warning("[INBOUND] svix timestamp outside tolerance — rejected")
                return False
        except (TypeError, ValueError):
            return False
        key = base64.b64decode(secret.split("_", 1)[1] if secret.startswith("whsec_") else secret)
        signed = f"{svix_id}.{svix_ts}.".encode() + raw_body
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
        # Header may carry multiple space-separated "v1,<sig>" entries.
        for part in svix_sig.split():
            _, _, sig = part.partition(",")
            if sig and hmac.compare_digest(sig, expected):
                return True
        logger.warning("[INBOUND] svix signature mismatch — rejected")
        return False
    except Exception as e:
        logger.warning(f"[INBOUND] signature verification error — rejected: {e}")
        return False


@router.post("/email/inbound")
async def inbound_email(request: Request):
    """Process inbound email replies from Resend.

    Resolution priority:
      1. Parse `reply+{biz}+{contact}@<INBOUND_EMAIL_DOMAIN>` from the
         To/Cc address — most reliable, scoped to the original send.
      2. Named platform addresses (kevin@/support@/... — see
         PLATFORM_INBOX_ADDRESSES) → platform_emails, read by Mission
         Control's /platform/inbox.
      3. Fall back to email-based match against the contacts table —
         catches replies sent to a static address (legacy / direct).
      4. Catch-all: anything still unresolved lands in platform_emails
         flagged catchall=true. Mail to the domain never dies silently.

    Always returns 200 so Resend doesn't retry; failures are logged.
    """
    raw_body = await request.body()
    if not _verify_resend_signature(raw_body, request.headers):
        # Forged or unverifiable — 200 so a real-but-misconfigured sender
        # doesn't hammer retries, but do nothing with the payload.
        return {"status": "ignored", "reason": "unverified_signature"}
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return {"status": "ignored", "reason": "non-json payload"}

    parsed = _extract_inbound(payload)
    from_email = parsed["from_email"]
    if not from_email:
        logger.info("[INBOUND] no from address in payload — ignored")
        return {"status": "ignored", "reason": "no_from"}

    business_id: Optional[str] = None
    contact_id: Optional[str] = None
    contact_name: Optional[str] = None
    current_health: int = 50
    routed = False

    async with httpx.AsyncClient() as client:
        # ── Fetch the actual body. Resend's email.received webhook
        #    only carries metadata; the body must be pulled via
        #    /emails/{id} on the Resend API. We fetch only when the
        #    payload didn't include text content (so legacy webhooks
        #    that DO include body still work without an extra round-trip).
        if not parsed["body"] and parsed["message_id"]:
            fetched = await _fetch_inbound_body(client, parsed["message_id"])
            if fetched["text"] or fetched["html"]:
                parsed["raw_text"] = fetched["text"]
                parsed["raw_html"] = (fetched["html"] or "")[:5000]
                parsed["raw_html_full"] = fetched["html"] or ""
                parsed["body"] = fetched["text"] or _strip_html(fetched["html"])
                logger.info(
                    f"[INBOUND] fetched body from Resend API: "
                    f"text_len={len(fetched['text'])} html_len={len(fetched['html'])}"
                )

        # ── 1. Try the routed reply-to address first ─────────────────
        # PostgREST `like` operator: % is the wildcard.
        for addr in parsed["to_addresses"]:
            parsed_addr = _parse_routed_address(addr)
            if not parsed_addr:
                continue
            biz_short = urllib.parse.quote(parsed_addr["biz_short"], safe="")
            contact_short = urllib.parse.quote(parsed_addr["contact_short"], safe="")
            biz_rows = await _sb_get(client,
                f"/businesses?id=like.{biz_short}%25&select=id&limit=1")
            if not biz_rows:
                continue
            business_id = biz_rows[0]["id"]
            if contact_short and contact_short != "anon":
                cid_rows = await _sb_get(client,
                    f"/contacts?id=like.{contact_short}%25&business_id=eq.{business_id}"
                    f"&select=id,name,health_score&limit=1")
                if cid_rows:
                    contact_id = cid_rows[0]["id"]
                    contact_name = cid_rows[0].get("name")
                    current_health = int(cid_rows[0].get("health_score") or 50)
            routed = True
            break

        # ── 2. Named platform addresses → Mission Control inbox ─────
        # kevin@/support@/... at the inbound domain is mail for the
        # PLATFORM, not for any practitioner business — route it there
        # even when the sender happens to match a contact.
        if not business_id:
            platform_addr = _match_platform_address(parsed["to_addresses"])
            if platform_addr:
                pid = await _store_platform_email(client, parsed, platform_addr, catchall=False)
                logger.info(
                    f"[INBOUND] platform inbox: to={platform_addr} "
                    f"from={pii_mask.mask_email(from_email)} id={pid}")
                return {"status": "platform_inbox", "to": platform_addr, "id": pid}

        # ── 3. Email-based fallback ──────────────────────────────────
        if not business_id:
            rows = await _sb_get(client,
                f"/contacts?email=eq.{from_email}&select=id,name,business_id,health_score&limit=1")
            if not rows:
                # Nothing claimed it — catch-all into the Mission Control
                # inbox instead of dropping. Mail to this domain must
                # never die silently again.
                addr = parsed["to_addresses"][0] if parsed["to_addresses"] else ""
                pid = await _store_platform_email(client, parsed, addr, catchall=True)
                logger.info(
                    f"[INBOUND] catch-all -> platform inbox: to={addr} "
                    f"from={pii_mask.mask_email(from_email)} id={pid}")
                return {"status": "platform_catchall", "id": pid}
            contact = rows[0]
            business_id = contact.get("business_id")
            contact_id = contact.get("id")
            contact_name = contact.get("name")
            current_health = int(contact.get("health_score") or 50)

        if not business_id:
            logger.info(f"[INBOUND] could not resolve business: from={pii_mask.mask_email(from_email)}")
            return {"status": "unresolved", "from": from_email}

        # Cleaned reply body (quoted-text stripped)
        clean_body = _strip_quoted_reply(parsed["body"])
        from_name = parsed.get("from_name") or contact_name or ""

        # ── 4. Persist to email_replies table ────────────────────────
        # The Email Hub UI reads from this table directly; the events
        # entry below remains for the contact timeline + activity feed.
        reply_row = {
            "business_id": business_id,
            "contact_id": contact_id,
            "from_email": from_email,
            "from_name": from_name,
            "subject": parsed["subject"],
            "body_text": clean_body[:20000],
            "body_html": (parsed.get("raw_html") or "")[:5000] or None,
            "raw_text": (parsed.get("raw_text") or "")[:20000] or None,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "read": False,
            "metadata": {
                "in_reply_to": parsed["in_reply_to"],
                "message_id": parsed["message_id"],
                "routed": routed,
                # Which pipe this arrived through. Everything reaching
                # this webhook came back through our own inbound path —
                # we mailed first, so the sender set is bounded. A
                # connected mailbox is not bounded that way and stamps
                # "mailbox" instead, which is what Chief's selection
                # policy filters on. Rows written before this key existed
                # default to "reply", which is true by construction:
                # there was no other way in.
                "source": "reply",
            },
        }
        inserted = await _sb_post(client, "/email_replies", reply_row)
        reply_id = None
        if isinstance(inserted, list) and inserted:
            reply_id = inserted[0].get("id")
        elif isinstance(inserted, dict):
            reply_id = inserted.get("id")

        # ── 5. Event on the contact's timeline ───────────────────────
        await _sb_post(client, "/events", {
            "business_id": business_id,
            "contact_id": contact_id,
            "event_type": "email_replied",
            "data": {
                "from": from_email,
                "from_name": from_name,
                "subject": parsed["subject"],
                "preview": clean_body[:200],
                "full_body": clean_body[:20000],
                "in_reply_to": parsed["in_reply_to"],
                "message_id": parsed["message_id"],
                "reply_id": reply_id,
            },
            "source": "resend_inbound",
        })

        # ── 6. Notification for the practitioner ─────────────────────
        await _sb_post(client, "/chief_notifications", {
            "business_id": business_id,
            "type": "info",
            "title": f"{from_name or from_email} replied",
            "body": f"Re: \"{parsed['subject']}\" — {clean_body[:200]}",
            "suggested_action": f"View reply from {from_name or 'contact'}",
            "status": "unread",
            "data": {
                "contact_id": contact_id,
                "reply_id": reply_id,
                "event_type": "email_replied",
                "subject": parsed["subject"],
            },
        })

        # ── 7. Bump contact health — they engaged ───────────────────
        if contact_id:
            await _sb_patch(client, f"/contacts?id=eq.{contact_id}", {
                "health_score": min(100, current_health + 5),
                "last_interaction": datetime.now(timezone.utc).isoformat(),
            })

        logger.info(
            f"[INBOUND] reply from {from_email} -> biz={business_id[:8]} "
            f"contact={contact_id[:8] if contact_id else 'unknown'} routed={routed}"
        )
        return {"status": "processed", "contact_id": contact_id, "reply_id": reply_id}


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
#   Events: email.opened, email.bounced, email.complained
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


async def _do_unsubscribe(email: str, sig: str) -> bool:
    """Verify the signed unsubscribe link and add the address to the
    suppression list (the same gate every send already checks)."""
    addr = (email or "").strip().lower()
    if not addr or not hmac.compare_digest(sig or "", _unsub_sig(addr)):
        return False
    await add_suppression(addr, "unsubscribed", "list-unsubscribe")
    _dom = addr.partition("@")[2]
    logger.info(f"[UNSUB] {addr[:1]}***@{_dom} unsubscribed")
    return True


@router.get("/email/unsubscribe")
async def unsubscribe_get(e: str = "", s: str = ""):
    """Browser-facing unsubscribe (the link in the List-Unsubscribe
    header + email footer)."""
    ok = await _do_unsubscribe(e, s)
    msg = ("You're unsubscribed. You won't receive further marketing emails."
           if ok else "That unsubscribe link is invalid or expired.")
    return HTMLResponse(
        f"<!doctype html><html><body style='font-family:system-ui;max-width:480px;"
        f"margin:80px auto;padding:0 24px;text-align:center;color:#1b2030'>"
        f"<h2 style='font-weight:700'>{'Unsubscribed' if ok else 'Link problem'}</h2>"
        f"<p style='color:#566079;line-height:1.6'>{msg}</p></body></html>",
        status_code=200 if ok else 400)


@router.post("/email/unsubscribe")
async def unsubscribe_post(e: str = "", s: str = ""):
    """One-click unsubscribe (List-Unsubscribe-Post) — mail providers
    POST this directly, no page render."""
    ok = await _do_unsubscribe(e, s)
    return {"ok": ok}


@router.post("/email/webhook")
async def resend_webhook(request: Request):
    # Beta-readiness audit (adversarial): this handler drives the
    # deliverability suppression list — a forged email.bounced /
    # email.complained could silently suppress a competitor's clients.
    # Verify the Resend (Svix) signature exactly like /email/inbound does;
    # unverified payloads are dropped (200 so a misconfigured-but-real
    # sender doesn't hammer retries).
    raw_body = await request.body()
    if not _verify_resend_signature(raw_body, request.headers):
        return {"status": "ignored", "reason": "unverified_signature"}
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return {"status": "ignored", "reason": "non-json payload"}

    evt = _extract_open_event(payload)

    # Deliverability signals → suppression list (hardening pass 1).
    # Enable email.bounced + email.complained on the Resend webhook.
    if evt["type"] in ("email.bounced", "email.complained"):
        if evt["to_email"]:
            reason = "complained" if evt["type"] == "email.complained" else "bounced"
            await add_suppression(evt["to_email"], reason, evt["type"])
            logger.warning(f"[SUPPRESS] {pii_mask.mask_email(evt['to_email'])} → {reason}")
            return {"status": "suppressed", "to": evt["to_email"], "reason": reason}
        return {"status": "ignored", "reason": "bounce event without recipient"}

    if evt["type"] != "email.opened":
        # Other event types (delivered, delayed, etc) — accept and ignore
        return {"status": "ignored", "reason": f"unsupported event {evt['type']}"}

    to_email = evt["to_email"]
    if not to_email:
        return {"status": "ignored", "reason": "no recipient"}

    async with httpx.AsyncClient() as client:
        rows = await _sb_get(client, f"/contacts?email=eq.{to_email}&select=id,name,business_id&limit=1")
        if not rows:
            logger.info(f"[OPEN] unknown recipient: {pii_mask.mask_email(to_email)}")
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
            logger.info(f"[OPEN] no matching sent invoice for {pii_mask.mask_email(to_email)}")
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
