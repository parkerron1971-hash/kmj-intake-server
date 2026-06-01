"""
booking_widget_router.py — customer-facing endpoints for the BookingForm
widget (Phase C.1).

Endpoints:
  GET  /widgets/booking/{business_id}/config?token=...    [token-required, dep]
       Returns brand kit + business info + bookings module schema slice for
       the form to render. Authed via require_customer_token_dep.

  POST /widgets/booking/{business_id}/book                [token-required, dep]
       Books an appointment for the known customer. Authed via dep.

  POST /widgets/booking/{business_id}/book-anon           [anon, rate-limited]
       First-time walk-in. No token. Creates a business_customers row,
       links/creates a contact (deduped by email), creates the appointment,
       issues a token, returns it. Rate-limited 10/IP/hour.

  GET  /widgets/booking/{business_id}/config-anon         [anon, rate-limited]
       Public config for the anon form (brand kit + bookings schema slice,
       NO customer-specific data). Rate-limited 10/IP/hour to gate
       enumeration.

  POST /widgets/request-fresh-link                        [anon, rate-limited]
       For an expired-token recovery flow. Takes {business_id, email},
       looks up business_customers, issues a new token, returns/emails it.
       Rate-limited 10/IP/hour.

Cross-tenant isolation: every token-required endpoint uses
require_customer_token_dep. That dependency enforces the 4-step pattern
(signature → expiration → biz match → customer row exists) before any
handler code runs. Handlers receive a CustomerContext and never see the
raw token. No handler can skip a step.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

import sb_clients
from customer_token import (
    CustomerContext,
    TOKEN_TTL_SECONDS,
    issue_customer_token,
    require_customer_token_dep,
)

logger = logging.getLogger("booking_widget_router")
router = APIRouter(tags=["widgets-booking"])

_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0)


# ─────────────────────────────────────────────────────────────────────
# In-memory IP rate limiter — sufficient for spike on a single Railway
# dyno. Buckets per (endpoint, ip), sliding 1-hour window.
# TODO(phase-c-x): move to Redis or postgres-backed limiter when we
# scale beyond a single dyno.
# ─────────────────────────────────────────────────────────────────────

_RATE_WINDOW_SEC = 60 * 60
_RATE_LIMIT = 10
_rate_lock = threading.Lock()
_rate_buckets: Dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def _rate_limit(bucket_key: str, request: Request) -> None:
    """Raises HTTPException(429) if the bucket exceeded _RATE_LIMIT in
    the past _RATE_WINDOW_SEC seconds."""
    ip = _client_ip(request)
    key = f"{bucket_key}::{ip}"
    now = time.time()
    cutoff = now - _RATE_WINDOW_SEC
    with _rate_lock:
        bucket = _rate_buckets[key]
        # Drop expired
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _RATE_LIMIT:
            raise HTTPException(status_code=429, detail="rate limit exceeded — try again later")
        bucket.append(now)


# ─────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────


def _business_basics(business_id: str) -> Optional[Dict[str, Any]]:
    """Loads minimal business info — name, settings (which carries
    brand_kit + theme nested), voice_profile. Used by both anon and
    authed config endpoints. Returns None if not found.

    Note: brand_kit is NOT a top-level column on businesses — it lives
    at settings.brand_kit. See agents/composer/creative_expression.py
    line 336 for the canonical read pattern."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&limit=1"
        f"&select=id,name,settings,voice_profile"
    ) or []
    return rows[0] if rows else None


def _bookings_module(business_id: str) -> Optional[Dict[str, Any]]:
    """Finds the booking_calendar archetype module for this business.
    There is at most one per business (the LLM's proposal flow is the
    only path to one).

    Phase C.1.1 removed the slug='bookings' spike-compat fallback —
    a fallback_generic module is NOT a working customer surface and
    must NOT be reachable to the widget. Practitioners with legacy
    bookings modules upgrade via the Chief `upgrade_module_archetype`
    action."""
    rows = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{business_id}"
        f"&archetype=eq.booking_calendar&is_active=eq.true&limit=1&select=*"
    ) or []
    return rows[0] if rows else None


def _theme_tokens(business: Dict[str, Any]) -> Dict[str, str]:
    """Extract the brand-kit CSS variables the widget shadow-root needs.
    Read order matches existing app convention: settings.brand_kit (the
    canonical home of practitioner-customized colors / fonts — see
    agents/composer/creative_expression.py) > settings.theme > defaults.

    Keep the surface small — the widget renders one form, not the whole
    app. Five tokens cover the kill criterion ('brand kit visible')."""
    settings = business.get("settings") or {}
    brand = settings.get("brand_kit") or {}
    theme = settings.get("theme") or {}
    return {
        "--accent":         brand.get("accent")          or theme.get("accent")         or "#a78bfa",
        "--accent-hover":   brand.get("accent_hover")    or theme.get("accent_hover")   or "#818cf8",
        "--surface":        brand.get("surface")         or theme.get("surface")        or "#ffffff",
        "--text-primary":   brand.get("text_primary")    or theme.get("text_primary")   or "#0f172a",
        "--text-secondary": brand.get("text_secondary")  or theme.get("text_secondary") or "#475569",
        "--border":         brand.get("border")          or theme.get("border")         or "rgba(15,23,42,0.12)",
        "--font-heading":   brand.get("font_heading")    or theme.get("font_heading")   or "system-ui, sans-serif",
        "--font-body":      brand.get("font_body")       or theme.get("font_body")      or "system-ui, sans-serif",
    }


def _customer_visible_fields(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Phase C.1.1 — return only the fields the widget should know about:
    customer_facing (user-typed in the form) OR system_set (widget-computed
    + included in the submission payload but hidden from the form). All
    other fields are practitioner-only and MUST NOT travel to the widget.

    Fail-closed: a field with neither flag is treated as practitioner-only."""
    out = []
    for f in fields or []:
        if not isinstance(f, dict):
            continue
        if f.get("customer_facing") is True or f.get("system_set") is True:
            out.append(f)
    return out


def _config_payload(business: Dict[str, Any], module: Dict[str, Any]) -> Dict[str, Any]:
    """Shared shape for config-anon + config endpoints. Customer-identifying
    data lives ONLY in the authed response; this shape is safe for anon.

    Phase C.1.1: schema.fields is filtered to customer-visible only
    (customer_facing OR system_set). agent_config.services travels through
    when the archetype declares a service catalog."""
    archetype_params = module.get("archetype_params") or {}
    schema = module.get("schema") or {}
    agent_config = module.get("agent_config") or {}
    visible_fields = _customer_visible_fields(schema.get("fields") or [])
    services = agent_config.get("services") or []
    return {
        "business": {
            "id": business["id"],
            "name": business.get("name"),
        },
        "module": {
            "id": module["id"],
            "name": module.get("name"),
            "icon": module.get("icon"),
            "archetype": module.get("archetype") or "fallback_generic",
        },
        "schema": {"fields": visible_fields},
        "archetype_params": archetype_params,
        "services": services,
        "theme_tokens": _theme_tokens(business),
    }


# ─────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────


# ─── ANON: config (rate-limited, no token) ────────────────────────────

@router.get("/widgets/booking/{business_id}/config-anon")
async def booking_config_anon(business_id: str, request: Request) -> Dict[str, Any]:
    _rate_limit("config-anon", request)
    biz = _business_basics(business_id)
    if not biz:
        raise HTTPException(status_code=404, detail="business not found")
    module = _bookings_module(business_id)
    if not module:
        raise HTTPException(status_code=404, detail="no bookings module for this business")
    return {"ok": True, **_config_payload(biz, module)}


# ─── AUTHED: config (token + cross-tenant via dep) ────────────────────

@router.get("/widgets/booking/{business_id}/config")
async def booking_config(
    business_id: str,
    ctx: CustomerContext = Depends(require_customer_token_dep),
) -> Dict[str, Any]:
    biz = _business_basics(business_id)
    if not biz:
        raise HTTPException(status_code=404, detail="business not found")
    module = _bookings_module(business_id)
    if not module:
        raise HTTPException(status_code=404, detail="no bookings module for this business")
    payload = _config_payload(biz, module)
    # Authed shape includes the customer's identity so the form can
    # prefill name/email and show "your upcoming bookings".
    payload["customer"] = {
        "id": ctx.customer_id,
        "email": ctx.customer_row.get("email"),
        "name": ctx.customer_row.get("name"),
    }
    return {"ok": True, **payload}


# ─── ANON: walk-in book (rate-limited, creates customer + token) ──────

def _validate_email_shape(v: str) -> str:
    """Lightweight email shape check. We don't depend on the email_validator
    package (not in the prod requirements set) — the SQL CHECK on
    business_customers.email also enforces the @ shape server-side."""
    if not isinstance(v, str):
        raise ValueError("email must be a string")
    v = v.strip()
    if "@" not in v or len(v) < 3 or v.startswith("@") or v.endswith("@"):
        raise ValueError("invalid email shape")
    return v


class BookAnonBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=320)
    data: Dict[str, Any]  # field values for the appointment (date, service, etc.)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        return _validate_email_shape(v)


@router.post("/widgets/booking/{business_id}/book-anon")
async def book_anon(
    business_id: str,
    body: BookAnonBody,
    request: Request,
) -> Dict[str, Any]:
    _rate_limit("book-anon", request)

    biz = _business_basics(business_id)
    if not biz:
        raise HTTPException(status_code=404, detail="business not found")
    module = _bookings_module(business_id)
    if not module:
        raise HTTPException(status_code=404, detail="no bookings module for this business")

    email_norm = body.email.strip().lower()

    # 1. Dedupe-on-email: find or create a contact for the business first.
    #    Per the ruling: walk-in flow MUST check for existing contact and
    #    link instead of creating a duplicate.
    contact_id = _find_or_create_contact(business_id, body.name, email_norm)

    # 2. Find or create a business_customers row (unique on biz + lower(email)).
    customer_id = _find_or_create_customer(business_id, contact_id, email_norm, body.name)

    # 3. Create the appointment as a module_entry. data.contact_id wires it
    #    to the practitioner-side contact, which surfaces it in ContactDetail.
    entry_data = dict(body.data)
    entry_data["contact_id"] = contact_id
    entry_data.setdefault("customer_name", body.name)
    entry_data.setdefault("customer_email", email_norm)

    entry = _create_appointment(business_id, module["id"], entry_data)
    if not entry:
        raise HTTPException(status_code=500, detail="Something went wrong on our end — please try again.")

    # 4. Mint a token so the customer can return to view/manage.
    token = issue_customer_token(business_id, customer_id)

    return {
        "ok": True,
        "appointment_id": entry["id"],
        "customer_id": customer_id,
        "contact_id": contact_id,
        "token": token,
        "token_expires_in_seconds": TOKEN_TTL_SECONDS,
    }


# ─── AUTHED: known-customer book ──────────────────────────────────────

class BookBody(BaseModel):
    data: Dict[str, Any]


@router.post("/widgets/booking/{business_id}/book")
async def book(
    business_id: str,
    body: BookBody,
    ctx: CustomerContext = Depends(require_customer_token_dep),
) -> Dict[str, Any]:
    module = _bookings_module(business_id)
    if not module:
        raise HTTPException(status_code=404, detail="no bookings module for this business")

    contact_id = ctx.customer_row.get("contact_id")
    entry_data = dict(body.data)
    if contact_id:
        entry_data["contact_id"] = contact_id
    entry_data.setdefault("customer_name", ctx.customer_row.get("name"))
    entry_data.setdefault("customer_email", ctx.customer_row.get("email"))

    entry = _create_appointment(business_id, module["id"], entry_data)
    if not entry:
        raise HTTPException(status_code=500, detail="Something went wrong on our end — please try again.")

    return {"ok": True, "appointment_id": entry["id"]}


# ─── ANON: request a fresh link (rate-limited) ────────────────────────

class FreshLinkBody(BaseModel):
    business_id: str
    email: str = Field(..., min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        return _validate_email_shape(v)


@router.post("/widgets/request-fresh-link")
async def request_fresh_link(body: FreshLinkBody, request: Request) -> Dict[str, Any]:
    _rate_limit("request-fresh-link", request)
    email_norm = body.email.strip().lower()
    rows = sb_clients.sb_get_as_service(
        f"/business_customers?business_id=eq.{body.business_id}"
        f"&email=eq.{email_norm}&limit=1&select=id,business_id"
    ) or []
    # Don't leak existence: always return ok=True, even if the row is
    # missing. The customer's email client sees nothing if there's no
    # match. (Anti-enumeration discipline for the email-based vector.)
    if rows:
        customer_id = rows[0]["id"]
        token = issue_customer_token(body.business_id, customer_id)
        _send_fresh_link_email(body.business_id, email_norm, token)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────
# Helpers (private)
# ─────────────────────────────────────────────────────────────────────


def _find_or_create_contact(business_id: str, name: str, email_lower: str) -> str:
    """Per ruling: walk-in flow MUST check for existing contact on the
    business with the same email and link instead of creating a duplicate.
    Returns contact_id.

    TODO(contacts-hardening): the (business_id, lower(email)) dedupe here
    is application-level — the contacts table has no UNIQUE index covering
    it (only business_customers does, via the Phase C.1 migration). Two
    concurrent walk-ins with the same email could race and create two
    rows. The existing public_site booking flow has the same gap. Address
    in a future contacts-hardening sweep.

    TODO(contacts-hardening): the contact insert + business_customer
    insert + module_entry insert downstream are not transactional — a
    failure after this step leaves an orphan contact. PostgREST doesn't
    natively cover multi-statement transactions; needs a Postgres RPC.
    Same hardening sweep.
    """
    existing = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{business_id}&email=eq.{email_lower}"
        f"&limit=1&select=id"
    ) or []
    if existing:
        return existing[0]["id"]
    # status='lead' matches the in-tree convention (chief_of_staff.handle_create_contact,
    # public_site booking flow). 'lifecycle_stage' is NOT a real column on contacts —
    # the prior typo caused PGRST204 and a 500 on the widget submission.
    payload = {
        "business_id": business_id,
        "name": name,
        "email": email_lower,
        "status": "lead",
        "source": "booking_widget",
    }
    created = sb_clients.sb_post_as_service("/contacts", payload)
    if not isinstance(created, list) or not created:
        # The underlying PostgREST error is already logged by sb_clients
        # ("sb_clients sync POST /contacts: <code> <body>"). This warning
        # adds business / email / code-path context so future drift is
        # one log search away instead of ten minutes of tracing.
        logger.warning(
            f"booking_widget contact create failed for biz={business_id} "
            f"email={email_lower!r} — see preceding sb_clients log line for detail"
        )
        raise HTTPException(
            status_code=500,
            detail="Something went wrong on our end — please try again.",
        )
    return created[0]["id"]


def _find_or_create_customer(
    business_id: str,
    contact_id: str,
    email_lower: str,
    name: str,
) -> str:
    """Idempotent on (business_id, lower(email)) via the unique index.
    Returns business_customers.id."""
    existing = sb_clients.sb_get_as_service(
        f"/business_customers?business_id=eq.{business_id}"
        f"&email=eq.{email_lower}&limit=1&select=id,contact_id"
    ) or []
    if existing:
        # Backfill contact_id if it was previously null.
        if not existing[0].get("contact_id"):
            sb_clients.sb_patch_as_service(
                f"/business_customers?id=eq.{existing[0]['id']}",
                {"contact_id": contact_id},
            )
        return existing[0]["id"]
    created = sb_clients.sb_post_as_service("/business_customers", {
        "business_id": business_id,
        "contact_id": contact_id,
        "email": email_lower,
        "name": name,
    })
    if not isinstance(created, list) or not created:
        # C22 polish — match the contact-create pattern: log context, raise
        # a user-friendly message. The underlying PostgREST error is in the
        # preceding sb_clients log line.
        logger.warning(
            f"booking_widget customer create failed for biz={business_id} "
            f"email={email_lower!r} contact={contact_id} — see preceding "
            f"sb_clients log line for detail"
        )
        raise HTTPException(
            status_code=500,
            detail="Something went wrong on our end — please try again.",
        )
    return created[0]["id"]


def _create_appointment(
    business_id: str,
    module_id: str,
    data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    created = sb_clients.sb_post_as_service("/module_entries", {
        "business_id": business_id,
        "module_id": module_id,
        "data": data,
        "status": "active",
        "created_by": "booking_widget",
    })
    if isinstance(created, list) and created:
        return created[0]
    # C22 polish — same friendly-error treatment as contact + customer
    # create. The caller's existing `if not entry: raise HTTPException(500,
    # "appointment create failed")` covered the unhappy path with a
    # backend-y string; this widens the log + sanitizes the user-visible
    # message. NOTE the caller still does the raise; we just log here so
    # the diagnostic context is preserved even if a future caller forgets.
    logger.warning(
        f"booking_widget appointment create failed for biz={business_id} "
        f"module={module_id} — see preceding sb_clients log line for detail"
    )
    return None


def _send_fresh_link_email(business_id: str, email: str, token: str) -> None:
    """Send the fresh booking-management link via the existing email_sender.
    Quiet on failure — we already returned ok=True to avoid existence leak."""
    try:
        from email_sender import send_via_resend  # local import: keep router cheap
        biz = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=name,settings&limit=1"
        ) or []
        biz_name = biz[0].get("name", "Your booking") if biz else "Your booking"
        link_base = os.environ.get("WIDGET_LINK_BASE", "https://app.solutionist.studio")
        link = f"{link_base}/booking/{business_id}?token={token}"
        send_via_resend(
            to=email,
            subject=f"{biz_name} — your booking link",
            html=(
                f"<p>Here's your fresh link to manage your booking with "
                f"<strong>{biz_name}</strong>:</p>"
                f"<p><a href=\"{link}\">{link}</a></p>"
                f"<p>This link is good for 90 days. If you didn't request it, "
                f"you can ignore this email.</p>"
            ),
        )
    except Exception as e:
        logger.warning(f"fresh-link email failed for {email}: {e}")
