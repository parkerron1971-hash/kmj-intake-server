"""
availability_router.py — Phase D.1.1 backend foundation.

Public read endpoint for the booking widget. Anonymous (customer-facing)
— no auth required to compute available slots, mirroring the
config-anon pattern. Rate-limited via the same _rate_limit hook used
by booking_widget_router.

Endpoints:
  GET /availability/{business_id}/slots
      ?from=YYYY-MM-DD
      ?to=YYYY-MM-DD
      &offering_id=<uuid>
      Returns available slot starts for an offering in the window.

Practitioner-side PATCH /businesses/{id}/availability ships in PR 2.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

import sb_clients
from auth_supabase import AuthedUser, require_user
from availability import BusinessAvailability
from availability_engine import (
    DEFAULT_LOOKAHEAD_DAYS,
    MAX_LOOKAHEAD_DAYS,
    compute_slots,
    resolved_tz_name,
)

logger = logging.getLogger("availability_router")

router = APIRouter(prefix="/availability", tags=["availability"])


# Reuse the booking widget's rate limiter — same anon-traffic shape.
try:
    from booking_widget_router import _rate_limit
except Exception:  # pragma: no cover
    def _rate_limit(_label: str, _req) -> None:
        pass


def _business_basics(business_id: str) -> Optional[Dict[str, Any]]:
    """Load minimal business row — settings + owner_id (for
    practitioner_profiles.timezone lookup)."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&limit=1"
        f"&select=id,owner_id,settings"
    ) or []
    return rows[0] if rows else None


def _practitioner_timezone(owner_id: Optional[str]) -> Optional[str]:
    """Read practitioner_profiles.timezone for the business owner.
    Returns None when missing — the engine then falls back to UTC."""
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


def _offering(offering_id: str, business_id: str) -> Optional[Dict[str, Any]]:
    """Load the offering for slot-length lookup. Scoped to the business
    so a customer can't query slot lengths for offerings on other
    businesses (defensive — would only matter if offering IDs leaked
    cross-business)."""
    rows = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}"
        f"&is_active=eq.true&select=id,duration_min&limit=1"
    ) or []
    return rows[0] if rows else None


def _bookings_in_window(
    business_id: str, start_date: date, end_date: date
) -> list:
    """Load existing module_entries with appointment_at in [start, end+1]
    to cover edge slots that span midnight. Only reads what the engine
    needs (appointment_at + duration). PostgREST query."""
    # Pad +1 day to cover bookings that started just before the window.
    from datetime import timedelta
    lo = (start_date - timedelta(days=1)).isoformat()
    hi = (end_date + timedelta(days=1)).isoformat()
    rows = sb_clients.sb_get_as_service(
        f"/module_entries?business_id=eq.{business_id}"
        f"&appointment_at=gte.{lo}&appointment_at=lte.{hi}"
        f"&select=appointment_at,duration_min_at_booking,duration_min"
        f"&limit=2000"
    ) or []
    return rows if isinstance(rows, list) else []


@router.get("/{business_id}/slots")
def get_available_slots(
    business_id: str,
    request: Request,
    offering_id: str = Query(..., description="offering whose duration drives slot length"),
    from_date: Optional[str] = Query(
        default=None, alias="from",
        description='Window start (YYYY-MM-DD). Default: today in business tz',
    ),
    to_date: Optional[str] = Query(
        default=None, alias="to",
        description=f'Window end (YYYY-MM-DD). Default: from+{DEFAULT_LOOKAHEAD_DAYS}d',
    ),
) -> Dict[str, Any]:
    """Compute available slots for an offering in a date window.

    Anonymous: customers can hit this from the embed widget without
    auth. Rate-limited via the booking-widget pattern.

    Returns:
      {
        "ok": true,
        "business_id": "...",
        "offering_id": "...",
        "duration_min": 30,
        "timezone": "America/New_York",
        "open_default": false,
        "from": "2026-09-14",
        "to": "2026-10-14",
        "slots": [
          {"start_utc": "...", "start_local": "...", "duration_min": 30},
          ...
        ]
      }
    """
    _rate_limit("availability/slots", request)

    biz = _business_basics(business_id)
    if not biz:
        raise HTTPException(404, "business not found")

    offering = _offering(offering_id, business_id)
    if not offering:
        raise HTTPException(404, "offering not found")

    duration_min = offering.get("duration_min")
    if not duration_min:
        raise HTTPException(
            400,
            "offering has no duration_min set — slot length cannot be computed. "
            "Edit the offering in OPERATE → Catalog → Offerings.",
        )

    # Parse window
    def _parse_iso_date(s: Optional[str], default: date) -> date:
        if not s:
            return default
        try:
            return date.fromisoformat(s)
        except ValueError:
            raise HTTPException(400, f"invalid date: {s!r} (expect YYYY-MM-DD)")

    # Compute business-tz "today" cheaply: use the engine's tz resolver via
    # constructing the availability config first.
    settings = biz.get("settings") or {}
    av = BusinessAvailability.from_settings_dict(settings.get("availability"))
    practitioner_tz = _practitioner_timezone(biz.get("owner_id"))

    # For default from_date we use server-side today (which is fine for
    # widget calls — minor TZ drift on edge would just shift the first
    # day by ≤1; window padding in _bookings_in_window covers it).
    today = date.today()
    fd = _parse_iso_date(from_date, today)
    td = _parse_iso_date(to_date, None) if to_date else None
    if td is None:
        from datetime import timedelta
        td = fd + timedelta(days=DEFAULT_LOOKAHEAD_DAYS)
    if (td - fd).days > MAX_LOOKAHEAD_DAYS:
        raise HTTPException(
            400,
            f"window too large; max {MAX_LOOKAHEAD_DAYS} days",
        )
    if td < fd:
        raise HTTPException(400, "to_date must be >= from_date")

    bookings = _bookings_in_window(business_id, fd, td)

    slots = compute_slots(
        availability=av,
        practitioner_tz=practitioner_tz,
        existing_bookings=bookings,
        offering_duration_min=int(duration_min),
        from_date=fd,
        to_date=td,
    )

    return {
        "ok": True,
        "business_id": business_id,
        "offering_id": offering_id,
        "duration_min": int(duration_min),
        "timezone": resolved_tz_name(av, practitioner_tz),
        "open_default": _is_open_default_dict(settings.get("availability")),
        "from": fd.isoformat(),
        "to": td.isoformat(),
        "slots": slots,
    }


def _is_open_default_dict(raw: Optional[dict]) -> bool:
    """Helper for the response shape — tells the widget whether the
    business has any availability config at all so it can render a
    "practitioner hasn't set hours yet" hint (PR 3 UX)."""
    if not raw or not isinstance(raw, dict):
        return True
    av = BusinessAvailability.from_settings_dict(raw)
    from availability import is_open_default
    return is_open_default(av)


# ─────────────────────────────────────────────────────────────────────
# Phase D.1.2 — practitioner-facing availability config (authed)
# ─────────────────────────────────────────────────────────────────────


def _require_owner(business_id: str, user: AuthedUser) -> None:
    """Same shape as offerings_router's owner gate."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1"
    ) or []
    if not rows or str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized")


@router.get("/{business_id}")
def get_availability(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Return the current availability config (or the open-default shape
    when none is set). Practitioner-facing — owner-gated."""
    _require_owner(business_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    settings = (rows[0].get("settings") or {})
    av = BusinessAvailability.from_settings_dict(settings.get("availability"))
    return {
        "ok": True,
        "business_id": business_id,
        "availability": av.model_dump(),
        "open_default": _is_open_default_dict(settings.get("availability")),
    }


@router.patch("/{business_id}")
def patch_availability(
    business_id: str,
    body: Dict[str, Any],
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Replace the business's availability config with the posted shape.

    Body MUST validate against BusinessAvailability. Practitioner-facing —
    owner-gated. Writes to businesses.settings.availability (preserves
    other settings keys via merge)."""
    _require_owner(business_id, user)
    try:
        av = BusinessAvailability.model_validate(body or {})
    except Exception as e:
        raise HTTPException(400, f"invalid availability config: {e}")

    # Merge into existing settings to preserve brand_kit, theme, etc.
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    settings = dict(rows[0].get("settings") or {})
    settings["availability"] = av.model_dump()

    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{business_id}", {"settings": settings},
    )
    return {
        "ok": True,
        "business_id": business_id,
        "availability": av.model_dump(),
    }

