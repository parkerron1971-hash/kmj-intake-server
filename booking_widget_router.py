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
    # Phase D.1.1 added owner_id to the select so the slot engine can
    # fall back to practitioner_profiles.timezone via the owner key.
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&limit=1"
        f"&select=id,name,settings,voice_profile,owner_id,stripe_account_id"
    ) or []
    return rows[0] if rows else None


def _bookings_module(business_id: str) -> Optional[Dict[str, Any]]:
    """Finds the booking_calendar archetype module for this business.

    C.1.5 Plan A — single-instance is an ENFORCED constraint (was
    aspirational pre-C.1.5). materialize_spec at
    `module_spec_generator._SINGLE_INSTANCE_ARCHETYPES` refuses to
    create a second active booking_calendar row on any business. The
    `limit=1` below is therefore correct AND no longer needs a
    docstring-only warning about silent drops — the second row cannot
    exist. If a real multi-module practitioner need surfaces, re-open
    the C.1.5 audit (see CLAUDE memory `project_c15_deferred.md`).

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


def booking_is_live(business_id: str,
                    settings: Optional[Dict[str, Any]] = None) -> bool:
    """THE booking-detection truth (2026-07-10, Kevin's 'booking says
    set up later' bug): the modern system is an ACTIVE booking_calendar
    module + settings.booking_page.published (the Embed tab's Publish
    toggle). The composer, the interview's connect chips, and offering
    readiness were all reading settings.booking.enabled — a legacy key
    NOTHING in the current flow writes — so a fully published booking
    setup was invisible to every one of them. Legacy flag still counts
    for old configurations."""
    s = settings if isinstance(settings, dict) else {}
    legacy = (s.get("booking") if isinstance(s.get("booking"), dict) else {})
    if legacy.get("enabled"):
        return True
    page = (s.get("booking_page")
            if isinstance(s.get("booking_page"), dict) else {})
    if not page.get("published"):
        return False
    return _bookings_module(business_id) is not None


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


# ─────────────────────────────────────────────────────────────────────
# Phase C.1.2 — canonical offerings resolution + price denormalization
# ─────────────────────────────────────────────────────────────────────

# P5a — drift tolerance gate for the cart-in-progress price-change race.
# Customer was quoted a price at config-anon time; submits with that price.
# If practitioner edited mid-session, we accept up to TOLERANCE_PCT drift
# OR up to TOLERANCE_WINDOW_SEC since the customer-visible quote ages.
PRICE_TOLERANCE_PCT = 0.10           # 10 %
PRICE_TOLERANCE_WINDOW_SEC = 300      # 5 minutes


def _offerings_for_categories(business_id: str, categories: List[str]) -> List[Dict[str, Any]]:
    """Fetch active offerings for a business, filtered to the requested
    categories. Returns the customer-safe shape (no internal flags)."""
    if not categories:
        return []
    cats = ",".join(c.strip() for c in categories if c)
    if not cats:
        return []
    rows = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}"
        f"&category=in.({cats})&is_active=eq.true"
        f"&order=name.asc&select=id,name,slug,description,category,"
        f"current_price,currency,duration_min,show_price_to_customer"
    ) or []
    return rows


def _offerings_for_widget_fields(business_id: str, fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For every offering_ref field on the spec, union the categories
    it wants; fetch once. Customer side gets a flat de-duplicated list
    of offerings the widget can resolve any offering_ref field against."""
    wanted_cats: List[str] = []
    seen = set()
    for f in fields or []:
        if (f or {}).get("type") == "offering_ref":
            for c in (f.get("offering_categories") or []):
                if c not in seen:
                    seen.add(c)
                    wanted_cats.append(c)
    return _offerings_for_categories(business_id, wanted_cats)


def _resolve_offering_for_book(
    business_id: str,
    offering_id: str,
    quoted_price: Optional[float],
) -> Dict[str, Any]:
    """At book time, look up the offering and return the canonical
    denormalization payload (price_at_booking + service_name_at_booking +
    duration_min_at_booking) under P5 ruling. Applies P5a tolerance gate
    on quoted_price drift + emits telemetry on any drift inside or outside
    the tolerance window."""
    rows = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}"
        f"&select=id,name,current_price,currency,duration_min,show_price_to_customer,is_active&limit=1"
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="offering not found")
    off = rows[0]
    if not off.get("is_active"):
        raise HTTPException(status_code=410, detail="offering no longer available")

    current_price = off.get("current_price")
    captured_price = current_price

    # P5a — quoted-price tolerance gate. If the customer's widget reported
    # a price different from the current live price, decide whether to
    # accept the quoted price (within tolerance) or reject the book.
    if quoted_price is not None and current_price is not None:
        delta_pct = abs(quoted_price - current_price) / max(current_price, 0.01)
        if delta_pct > 0:
            # P5a telemetry — log EVERY drift, in-tolerance or not, so we
            # learn real-world patterns over time.
            within = delta_pct <= PRICE_TOLERANCE_PCT
            logger.warning(
                f"booking_widget price drift detected: "
                f"biz={business_id} offering={offering_id} "
                f"quoted={quoted_price} current={current_price} "
                f"delta_pct={delta_pct:.3f} within_tolerance={within}"
            )
            if within:
                # Honor the price the customer saw.
                captured_price = quoted_price
            else:
                # Outside the band — reject with a recoverable error so
                # the widget can re-fetch the config and re-quote.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "The price changed since this form loaded. "
                        "Please refresh and try again."
                    ),
                )

    return {
        "price_at_booking": captured_price,
        "service_name_at_booking": off.get("name"),
        "duration_min_at_booking": off.get("duration_min"),
        # The live identifier survives an archive — historical denormalized
        # fields still display, but the link is preserved for traceability.
        "offering_id": offering_id,
    }


def _config_payload(business: Dict[str, Any], module: Dict[str, Any]) -> Dict[str, Any]:
    """Shared shape for config-anon + config endpoints. Customer-identifying
    data lives ONLY in the authed response; this shape is safe for anon.

    Phase C.1.1: schema.fields filtered to customer-visible only.
    Phase C.1.2: offerings resolved from the canonical offerings table for
    each offering_ref field. Legacy agent_config.services included as
    fallback ONLY for pre-C.1.2 modules (detected via the absence of any
    offering_ref field). The new C.1.2 widget prefers offerings + ignores
    services when offerings is present; pre-upgrade widgets see services
    as before."""
    archetype_params = module.get("archetype_params") or {}
    schema = module.get("schema") or {}
    agent_config = module.get("agent_config") or {}
    visible_fields = _customer_visible_fields(schema.get("fields") or [])

    # Canonical offerings (C.1.2). If any visible field is offering_ref,
    # resolve the dropdown from the offerings table.
    offerings = _offerings_for_widget_fields(business["id"], visible_fields)

    # Pre-C.1.2 fallback: a module with NO offering_ref field still ships
    # legacy services for the older widget bundle. Once the widget code
    # is C.1.2 it ignores services when offerings is non-empty.
    has_offering_ref = any(
        (f or {}).get("type") == "offering_ref" for f in visible_fields
    )
    legacy_services = [] if has_offering_ref else (agent_config.get("services") or [])

    # Phase D.1.1 — per-offering available slots for the next
    # DEFAULT_LOOKAHEAD_DAYS in business tz. Keyed by offering id so the
    # widget can render the calendar/slot picker (PR 3) based on the
    # service the customer picks. Open-default (no availability config
    # yet) treats every day as bookable 24/7 — practitioner can tighten
    # via the BUILD-side editor (PR 2).
    available_slots = _slots_per_offering(business, offerings)
    # Phase D.1.3 — business timezone for the widget's "Business hours: X"
    # label. Reads availability.timezone if set, else falls back to the
    # practitioner profile timezone, else UTC. Same resolution as the
    # engine's _resolve_tz.
    business_tz = _business_timezone(business)

    return {
        "business": {
            "id": business["id"],
            "name": business.get("name"),
            # Phase C.1.4 — customer-facing wizard reads this for the
            # vertical-aware terminology lookup (F11 ruling). Generic
            # fallback in the dictionary handles unmapped types.
            "type": business.get("type"),
        },
        "module": {
            "id": module["id"],
            "name": module.get("name"),
            "icon": module.get("icon"),
            "archetype": module.get("archetype") or "fallback_generic",
        },
        "schema": {"fields": visible_fields},
        "archetype_params": archetype_params,
        "offerings": offerings,
        "services": legacy_services,
        "theme_tokens": _theme_tokens(business),
        # Phase D.1.1 — keyed by offering_id; empty dict when no
        # offerings are available (e.g. legacy modules with no
        # offering_ref field).
        "available_slots": available_slots,
        # Phase D.1.3 — business timezone for the widget label.
        "timezone": business_tz,
        # Phase D.4 PR 3 — whether the customer-side wizard should
        # show the "Pay now" toggle in the checkout step. Boolean
        # only; the stripe_account_id itself stays server-side.
        "payments_enabled": bool(business.get("stripe_account_id")),
        # Quote anchor — the widget echoes this on submit; we use it for
        # the P5a freshness window check.
        "quoted_at": int(time.time()),
    }


def _business_timezone(business: Dict[str, Any]) -> Optional[str]:
    """Phase D.1.3 — resolve the business's canonical timezone for the
    widget's "Business hours: X" label. Same priority as the engine:
    availability.timezone > practitioner_profiles.timezone > None
    (widget treats None as UTC for display)."""
    settings = business.get("settings") or {}
    av = settings.get("availability") or {}
    tz = (av.get("timezone") or "").strip()
    if tz:
        return tz
    owner_id = business.get("owner_id")
    if not owner_id:
        return None
    rows = sb_clients.sb_get_as_service(
        f"/practitioner_profiles?owner_id=eq.{owner_id}"
        f"&select=timezone&limit=1"
    ) or []
    if not rows:
        return None
    tz = (rows[0].get("timezone") or "").strip()
    return tz or None


def _slots_per_offering(
    business: Dict[str, Any],
    offerings: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Phase D.1.1 — compute available slots per offering for the
    config-anon payload. Real-time compute per D2-α.

    Reads business.settings.availability + practitioner_profiles.timezone
    + existing module_entries; runs the engine for each offering's
    duration. Returns dict keyed by offering id."""
    try:
        from datetime import date as _date, timedelta as _td
        from availability import BusinessAvailability
        from availability_engine import (
            DEFAULT_LOOKAHEAD_DAYS,
            compute_slots,
        )
    except Exception as e:  # pragma: no cover
        logger.warning(f"availability engine unavailable: {e}")
        return {}

    settings = business.get("settings") or {}
    av = BusinessAvailability.from_settings_dict(settings.get("availability"))

    # Practitioner timezone fallback
    owner_id = business.get("owner_id")
    practitioner_tz: Optional[str] = None
    if owner_id:
        rows = sb_clients.sb_get_as_service(
            f"/practitioner_profiles?owner_id=eq.{owner_id}"
            f"&select=timezone&limit=1"
        ) or []
        if rows:
            tz_v = (rows[0].get("timezone") or "").strip()
            practitioner_tz = tz_v or None

    today = _date.today()
    horizon = today + _td(days=DEFAULT_LOOKAHEAD_DAYS)

    # Load existing bookings once for the window — engine subtracts overlaps
    # per offering. Pad ±1 day for edge bookings.
    lo = (today - _td(days=1)).isoformat()
    hi = (horizon + _td(days=1)).isoformat()
    bookings = sb_clients.sb_get_as_service(
        f"/module_entries?business_id=eq.{business['id']}"
        f"&appointment_at=gte.{lo}&appointment_at=lte.{hi}"
        f"&status=eq.active"
        f"&select=appointment_at,duration_min_at_booking,duration_min"
        f"&limit=2000"
    ) or []
    if not isinstance(bookings, list):
        bookings = []

    out: Dict[str, List[Dict[str, Any]]] = {}
    for off in offerings or []:
        oid = off.get("id")
        dur = off.get("duration_min")
        if not oid or not dur:
            continue
        try:
            slots = compute_slots(
                availability=av,
                practitioner_tz=practitioner_tz,
                existing_bookings=bookings,
                offering_duration_min=int(dur),
                from_date=today,
                to_date=horizon,
            )
            out[oid] = slots
        except Exception as e:  # pragma: no cover — never break widget
            logger.warning(
                f"slot compute failed for biz={business['id']} "
                f"offering={oid}: {e}"
            )
            out[oid] = []
    return out


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
    # SMS consent (2026-07-04, A2P architecture): the booking form shows
    # an UNCHECKED optional checkbox; true = customer agreed to receive
    # texts (confirmations/reminders). Recorded in sms_consents — the
    # audit trail. Wired automatically for EVERY business + every
    # custom booking module, because they all book through here.
    sms_consent: bool = False
    # Phase C.1.2 — optional canonical-pricing fields.
    # When the schema's service field is type='offering_ref', the widget
    # sends the offering_id directly + the price the customer was quoted.
    # Server denormalizes price_at_booking + service_name_at_booking +
    # duration_min_at_booking from the offerings table at create-time
    # (P5 ruling), with P5a tolerance gate on quoted_price.
    offering_id: Optional[str] = None
    quoted_price: Optional[float] = None

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        return _validate_email_shape(v)


def _maybe_denormalize_offering(
    business_id: str,
    module: Dict[str, Any],
    offering_id: Optional[str],
    quoted_price: Optional[float],
    entry_data: Dict[str, Any],
) -> Dict[str, Any]:
    """If the bookings module has an offering_ref field AND the request
    carries an offering_id, resolve + denormalize per P5/P5a. Returns the
    (possibly augmented) entry_data dict. Mutates a copy, not the input."""
    schema = module.get("schema") or {}
    fields = schema.get("fields") or []
    ref_field = next(
        (f for f in fields if (f or {}).get("type") == "offering_ref"),
        None,
    )
    if not ref_field:
        return entry_data  # pre-C.1.2 module; nothing to denormalize

    if not offering_id:
        # The widget didn't send an offering_id but the spec requires one.
        # The form's required-validation should have caught this; surface
        # as a friendly 400 if it didn't.
        raise HTTPException(
            status_code=400,
            detail=f"Please choose a {ref_field.get('label') or 'service'}.",
        )

    canon = _resolve_offering_for_book(business_id, offering_id, quoted_price)
    out = dict(entry_data)
    # Store the offering_id on the field name the spec declared (so the
    # BookingCalendar internal can resolve it consistently with how the
    # widget reads it back).
    out[ref_field["name"]] = offering_id
    out["offering_id"] = canon["offering_id"]
    out["price_at_booking"] = canon["price_at_booking"]
    out["service_name_at_booking"] = canon["service_name_at_booking"]
    # If the module has a duration_minutes_field, populate it from the
    # canon — overrides whatever the widget might have sent (it shouldn't
    # send one for an offering_ref module, but be defensive).
    duration_field = (module.get("archetype_params") or {}).get("duration_minutes_field")
    if duration_field and canon["duration_min_at_booking"] is not None:
        out[duration_field] = canon["duration_min_at_booking"]
        out["duration_min_at_booking"] = canon["duration_min_at_booking"]
    return out


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

    # Phase C.1.2 — denormalize offering price + name + duration at this
    # moment (P5). Raises 409 on out-of-tolerance drift (P5a).
    entry_data = _maybe_denormalize_offering(
        business_id, module, body.offering_id, body.quoted_price, entry_data,
    )

    # Phase D.4 — submit-side double-book guard. The customer's UI
    # showed slots that were free at config-anon time, but two
    # customers can race the same slot. Re-verify before insert.
    pdf = (module.get("archetype_params") or {}).get("primary_date_field") or "appointment_at"
    appt_iso = entry_data.get(pdf) or entry_data.get("appointment_at")
    dur_min = entry_data.get("duration_min_at_booking") or entry_data.get("duration_min") or 0
    if not _check_slot_available(business_id, str(appt_iso or ""), int(dur_min or 0)):
        raise HTTPException(
            status_code=409,
            detail="Sorry — that time was just booked. Please pick another.",
        )

    entry = _create_appointment(business_id, module["id"], entry_data)
    if not entry:
        raise HTTPException(status_code=500, detail="Something went wrong on our end — please try again.")

    # 4. Mint a token so the customer can return to view/manage.
    token = issue_customer_token(business_id, customer_id)

    # Phase D.4 — fire confirmation email + .ics attachment (best-effort).
    # Errors do NOT roll back the booking; booking is the load-bearing
    # entity. Logged for triage.
    try:
        from booking_confirmation_emails import send_confirmation_email
        import asyncio
        asyncio.create_task(send_confirmation_email(
            booking=entry,
            business=biz,
            customer_email=email_norm,
            customer_name=body.name,
            offering_id=body.offering_id,
        ))
    except Exception as e:
        logger.warning(f"confirmation email scheduling failed: {e}")

    # SMS consent audit (best-effort, never blocks the booking): the
    # customer checked the optional box → record who/when/where so the
    # platform can text them (and prove consent to carriers).
    if body.sms_consent:
        _record_booking_sms_consent(business_id, entry_data, body.name)

    # A2P alert #1 — booking-confirmation text (2026-07-07, campaign
    # approved). Fire-and-forget: sms_alerts owns the consent rule +
    # kill-switch + per-business toggle and never raises; a text
    # failure must never fail the booking.
    _schedule_confirmation_sms(biz, entry_data, body.name, str(appt_iso or ""))

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
    # Phase C.1.2 — same canonical-pricing fields as BookAnonBody.
    offering_id: Optional[str] = None
    quoted_price: Optional[float] = None
    # SMS consent — same contract as BookAnonBody.
    sms_consent: bool = False


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

    entry_data = _maybe_denormalize_offering(
        business_id, module, body.offering_id, body.quoted_price, entry_data,
    )

    # Phase D.4 — same submit-side double-book guard as the anon path.
    pdf = (module.get("archetype_params") or {}).get("primary_date_field") or "appointment_at"
    appt_iso = entry_data.get(pdf) or entry_data.get("appointment_at")
    dur_min = entry_data.get("duration_min_at_booking") or entry_data.get("duration_min") or 0
    if not _check_slot_available(business_id, str(appt_iso or ""), int(dur_min or 0)):
        raise HTTPException(
            status_code=409,
            detail="Sorry — that time was just booked. Please pick another.",
        )

    entry = _create_appointment(business_id, module["id"], entry_data)
    if not entry:
        raise HTTPException(status_code=500, detail="Something went wrong on our end — please try again.")

    # Phase D.4 — confirmation email + .ics for the authed path too.
    try:
        from booking_confirmation_emails import send_confirmation_email
        import asyncio
        biz = _business_basics(business_id)
        if biz:
            asyncio.create_task(send_confirmation_email(
                booking=entry,
                business=biz,
                customer_email=ctx.customer_row.get("email") or "",
                customer_name=ctx.customer_row.get("name") or "",
                offering_id=body.offering_id,
            ))
    except Exception as e:
        logger.warning(f"confirmation email scheduling failed: {e}")

    # SMS consent audit — same contract as the walk-in path.
    if body.sms_consent:
        _record_booking_sms_consent(
            business_id, entry_data, ctx.customer_row.get("name") or "")

    # A2P alert #1 — booking-confirmation text, same contract as the
    # walk-in path. (biz may be unset if the email block failed; fetch
    # independently so the two best-effort paths can't couple.)
    _schedule_confirmation_sms(
        _business_basics(business_id), entry_data,
        ctx.customer_row.get("name") or "", str(appt_iso or ""))

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


def _record_booking_sms_consent(business_id: str, entry_data: Dict[str, Any],
                                name: str) -> None:
    """SMS consent audit row for a booking-form opt-in (2026-07-04).
    Best-effort — never blocks or fails a booking. The phone comes from
    whatever phone-ish field the module schema collected."""
    try:
        from sms_service import normalize_phone
        raw = (entry_data.get("phone") or entry_data.get("customer_phone")
               or entry_data.get("mobile") or "")
        phone = normalize_phone(str(raw))
        if not phone:
            logger.info("[consent] sms_consent checked but no usable phone on booking")
            return
        sb_clients.sb_post_as_service("/sms_consents", {
            "phone": phone,
            "name": (name or "").strip()[:120] or None,
            "source": "booking",
            "business_id": business_id,
        })
        logger.info(f"[consent] booking SMS consent recorded {phone} biz={business_id[:8]}")
    except Exception as e:
        logger.warning(f"[consent] booking consent record failed: {e}")


def _schedule_confirmation_sms(biz: Optional[Dict[str, Any]],
                               entry_data: Dict[str, Any],
                               customer_name: str,
                               appointment_iso: str) -> None:
    """A2P alert #1 hook (2026-07-07). Schedules the booking-confirmation
    text as a background task so the booking response never waits on a
    carrier. All policy (SMS_ALERTS_ENABLED kill-switch, per-business
    settings.sms_alerts.confirmations toggle, the consent rule, opt-outs)
    lives in sms_alerts.send_booking_confirmation, which never raises.
    Best-effort by contract — mirrors the confirmation-email pattern."""
    if not biz:
        return
    try:
        import asyncio
        from sms_alerts import send_booking_confirmation
        asyncio.create_task(send_booking_confirmation(
            business=biz,
            entry_data=entry_data,
            customer_name=customer_name,
            appointment_iso=appointment_iso,
        ))
    except Exception as e:
        logger.warning(f"confirmation sms scheduling failed: {e}")


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


def _check_slot_available(
    business_id: str,
    appointment_at_iso: str,
    duration_min: int,
) -> bool:
    """Phase D.4 — submit-side double-book guard.

    The customer's UI shows slots that were free at config-anon snapshot
    time, but two customers can race the same slot. This re-verifies at
    submit-time by querying module_entries for any active booking that
    overlaps [appointment_at, appointment_at + duration_min).

    Returns True when the slot is still free. False on any overlap.
    Tolerant of malformed timestamps — treats unknown as a conflict (fail
    closed) only when the input itself is malformed.

    The engine's _booking_intervals + _overlaps helpers are the canonical
    overlap math; we reuse them here so the submit path and the
    config-anon snapshot can never disagree on the overlap rule."""
    if not appointment_at_iso or duration_min <= 0:
        # Without a usable interval we can't reason about overlap; let
        # the create proceed (no false 409s on malformed inputs — they'll
        # surface elsewhere).
        return True

    # Pad ±duration so any booking whose start is within the requested
    # interval is caught regardless of how the timestamp comparison
    # rounds at the boundary.
    try:
        from datetime import datetime, timedelta
        from availability_engine import _overlaps, _booking_intervals
        s = appointment_at_iso
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        slot_start = datetime.fromisoformat(s)
        slot_end = slot_start + timedelta(minutes=int(duration_min))
        # Pad the query window by 4h either side so we don't miss a
        # long booking whose appointment_at lands outside the immediate
        # window but whose end-time spills in.
        lo = (slot_start - timedelta(hours=4)).isoformat()
        hi = (slot_start + timedelta(hours=4)).isoformat()
    except Exception:
        # If we can't parse the slot, don't block the booking; the
        # check is opportunistic.
        return True

    rows = sb_clients.sb_get_as_service(
        f"/module_entries?business_id=eq.{business_id}"
        f"&appointment_at=gte.{lo}&appointment_at=lte.{hi}"
        f"&status=eq.active"
        f"&select=appointment_at,duration_min_at_booking,duration_min"
        f"&limit=200"
    ) or []
    if not isinstance(rows, list) or not rows:
        return True

    intervals = _booking_intervals(rows)
    for b_start, b_end in intervals:
        if _overlaps(slot_start, slot_end, b_start, b_end):
            return False
    return True


def _mirror_booking_session(business_id: str, entry: Dict[str, Any]) -> None:
    """ONE CALENDAR (Kevin's ruling, 2026-07-10): every booking mirrors
    into sessions — the calendar spine that CalendarView, Chief's
    upcoming-sessions context, AND the SMS reminder sweep all read.
    Before this, widget bookings lived only in module_entries: invisible
    on the calendar, never SMS-reminded (the Arc 11 'sessions linkage'
    queue item, finally built). A [booking:{entry_id}] marker in notes
    links the pair — idempotent, and the sync tick uses it to cancel
    the session when the booking is cancelled. Fail-soft: a mirror
    hiccup never breaks the booking itself."""
    try:
        d = entry.get("data") if isinstance(entry.get("data"), dict) else {}
        appt = (entry.get("appointment_at") or d.get("appointment_at")
                or d.get("starts_at") or d.get("scheduled_for"))
        eid = entry.get("id")
        if not appt or not eid:
            return
        marker = f"[booking:{eid}]"
        dupes = sb_clients.sb_get_as_service(
            f"/sessions?business_id=eq.{business_id}"
            f"&notes=like.*{marker}*&select=id&limit=1")
        if dupes:
            return
        title = str(d.get("offering_name") or d.get("offering")
                    or d.get("service") or "Booking").strip()[:80]
        dur_raw = (entry.get("duration_min_at_booking")
                   or entry.get("duration_min")
                   or d.get("duration_minutes") or 60)
        try:
            dur = max(5, int(dur_raw))
        except (TypeError, ValueError):
            dur = 60
        sb_clients.sb_post_as_service("/sessions", {
            "business_id": business_id,
            "contact_id": d.get("contact_id"),
            "title": title,
            "session_type": "booking",
            "status": "scheduled",
            "scheduled_for": appt,
            "duration_minutes": dur,
            "notes": f"Booked online. {marker}",
        })
    except Exception as e:  # pragma: no cover
        logger.warning(f"booking->session mirror failed soft: {e}")


async def booking_session_sync_tick() -> None:
    """One-calendar reconciler (leader-gated, every 10 min; kill switch
    BOOKING_SESSION_SYNC=off). Backstops every booking-creation path the
    inline mirror doesn't see (Chief's create_module_entry, the module
    UI, imports): future active bookings get their session; cancelled
    bookings cancel their mirrored session by marker."""
    import asyncio as _asyncio
    import os as _os
    if (_os.environ.get("BOOKING_SESSION_SYNC") or "on").lower() == "off":
        return

    def _sync() -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        mods = sb_clients.sb_get_as_service(
            "/custom_modules?archetype=eq.booking_calendar&is_active=eq.true"
            "&select=id,business_id&limit=500") or []
        for m in mods:
            mid, biz_id = m.get("id"), m.get("business_id")
            if not mid or not biz_id:
                continue
            # Forward mirror: future active bookings.
            rows = sb_clients.sb_get_as_service(
                f"/module_entries?module_id=eq.{mid}&status=eq.active"
                f"&appointment_at=gte.{now}&select=*&limit=100") or []
            for entry in rows:
                _mirror_booking_session(biz_id, entry)
            # Cancel sync: non-active future bookings whose mirrored
            # session is still scheduled.
            gone = sb_clients.sb_get_as_service(
                f"/module_entries?module_id=eq.{mid}&status=neq.active"
                f"&appointment_at=gte.{now}&select=id&limit=100") or []
            for entry in gone:
                marker = f"[booking:{entry.get('id')}]"
                sb_clients.sb_patch_as_service(
                    f"/sessions?business_id=eq.{biz_id}"
                    f"&notes=like.*{marker}*&status=eq.scheduled",
                    {"status": "cancelled"})

    try:
        await _asyncio.to_thread(_sync)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[booking-sync] tick failed: {e}")


def _create_appointment(
    business_id: str,
    module_id: str,
    data: Dict[str, Any],
    created_by: str = "booking_widget",
) -> Optional[Dict[str, Any]]:
    """`created_by` defaults to the widget so every existing caller is
    unchanged. chief_booking_actions passes "chief_of_staff" so a booking the
    practitioner made through Chief is distinguishable from one a customer
    made themselves — they are different events for reporting and for the
    confirmation-email decision."""
    created = sb_clients.sb_post_as_service("/module_entries", {
        "business_id": business_id,
        "module_id": module_id,
        "data": data,
        "status": "active",
        "created_by": created_by,
    })
    if isinstance(created, list) and created:
        # One calendar — mirror immediately so the booking hits the
        # practitioner's calendar (and becomes reminder-eligible) in the
        # same request; the sync tick backstops every other path.
        _mirror_booking_session(business_id, created[0])
        # Arc 20B — Tier 1 rules: booking_created event (fail-soft; the
        # booking itself must never depend on the rules engine).
        try:
            import rules_engine
            d = data or {}
            rules_engine.on_event(business_id, "booking_created", {
                "booking_id": created[0].get("id"),
                "contact_name": d.get("name") or d.get("customer_name"),
                "contact_email": d.get("email") or d.get("customer_email"),
                "contact_id": d.get("contact_id"),
                "offering": d.get("offering_name") or d.get("offering"),
                "starts_at": d.get("starts_at") or d.get("time") or d.get("slot"),
                "notes": d.get("notes"),
            })
        except Exception as _re_err:
            logger.warning(f"rules emit booking_created failed soft: {_re_err}")
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
