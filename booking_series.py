"""
booking_series.py — recurring weekly bookings (the standing slot).

THE GAP THIS CLOSES: a coach with a weekly client had to make 12 manual
bookings. The availability engine has understood weekly recurrence since
D.1.1 — but only for OFFERING hours, never for a client's standing
appointment. This module books the series in one pass.

OPERATOR-SIDE ONLY (this wave): the coach books their client's standing
slot from the internal calendar or through Chief. The public widget does
not offer recurrence.

ONE BOOKING PATH (same load-bearing decision as chief_booking_actions):
each occurrence is written through the widget's own helpers —
_bookings_module, _maybe_denormalize_offering, _check_slot_available,
_create_appointment — so every occurrence gets P5 denormalization, the
D.4 double-book guard, the ONE CALENDAR session mirror, and the Arc 20B
rules_engine event. No second implementation to drift.

SERIES SEMANTICS (state these anywhere the feature is described):
  • Occurrences are planned in the BUSINESS timezone with zoneinfo per
    occurrence — 9am weekly in America/Chicago stays 9am local across a
    DST transition (a fixed UTC delta would drift an hour).
  • Conflicting occurrences are SKIPPED, not fatal: the report says
    "12 booked, 2 skipped: Mar 3 (blocked), Mar 17 (conflict)".
    - "blocked"  → the date falls inside an availability BlockedRange
    - "closed"   → a date-specific override closed that day
    - "conflict" → an existing active booking overlaps the slot
    A weekly-closed weekday is deliberately NOT skipped: the operator
    chose that weekday for the whole series on purpose, and the single
    -booking path (create_booking) has never enforced weekly hours on
    the operator either.
  • Each created entry's data JSON carries series_id (uuid),
    series_index (1-based), series_weekday / series_time_local /
    series_timezone — the series is queryable via data->>series_id.
  • cancel_series(from_date) cancels FUTURE occurrences only; past
    entries are history and stay untouched.
  • Rescheduling ONE occurrence (via reschedule_booking) stamps
    series_detached=true on it: it keeps its series_id for provenance
    but series-level edits (cancel-from-here) no longer touch it.
  • Idempotency: POST with a series_id that already has entries is a
    no-op that reports the existing series instead of double-booking.

PostgREST timestamps: Z-form ALWAYS (feedback_postgrest_timestamp_class —
isoformat's +00:00 in a query string silently matches nothing).
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover — Python 3.9+ stdlib
    ZoneInfo = None  # type: ignore[assignment]

logger = logging.getLogger("booking_series")

router = APIRouter(prefix="/bookings", tags=["booking-series"])

# Hard cap on occurrences per series (~six months of weekly sessions).
SERIES_MAX_OCCURRENCES = 26
# Default when the caller gives neither count nor until_date (a quarter).
SERIES_DEFAULT_COUNT = 12

_WEEKDAY_LOOKUP: Dict[str, int] = {}
for _i, _names in enumerate([
    ("mon", "monday"), ("tue", "tues", "tuesday"), ("wed", "weds", "wednesday"),
    ("thu", "thur", "thurs", "thursday"), ("fri", "friday"),
    ("sat", "saturday"), ("sun", "sunday"),
]):
    for _n in _names:
        _WEEKDAY_LOOKUP[_n] = _i


def parse_weekday(raw: Any) -> Optional[int]:
    """Accept 0-6 (Monday=0, Python convention), or any usual name/abbrev.
    Returns None when unparseable."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 0 <= raw <= 6 else None
    s = str(raw or "").strip().lower()
    if not s:
        return None
    if s.isdigit():
        n = int(s)
        return n if 0 <= n <= 6 else None
    return _WEEKDAY_LOOKUP.get(s[:3] if s[:3] in _WEEKDAY_LOOKUP else s)


def parse_hhmm(raw: Any) -> Optional[time]:
    """"14:00", "9:00", "14:00:00" → time. None when unusable."""
    s = str(raw or "").strip()
    if not s or ":" not in s:
        return None
    try:
        parts = s.split(":")
        h, m = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return time(h, m)


def _z(dt: datetime) -> str:
    """Aware datetime → PostgREST-safe Z-form UTC string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pretty_date(d: date) -> str:
    return d.strftime("%b %d").replace(" 0", " ")


# ─── Occurrence planning (pure — no DB) ───────────────────────────────

def plan_occurrences(
    *,
    weekday: int,
    at: time,
    tz_name: str,
    start_from: Optional[date] = None,
    count: Optional[int] = None,
    until_date: Optional[date] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Plan the weekly occurrence datetimes.

    DST-correct by construction: each occurrence is built as a LOCAL
    datetime (date + at, in tz_name via zoneinfo) and converted to UTC
    per occurrence. Weekly stepping is calendar-date arithmetic, so the
    local wall time never drifts across a transition.

    Returns [{"date": date, "local": datetime, "utc": datetime,
              "utc_iso": "...Z", "index": 1-based}] — capped at
    SERIES_MAX_OCCURRENCES, future-only relative to `now`.
    """
    tz = None
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(tz_name or "UTC")
        except Exception:
            logger.warning(f"[series] unknown timezone {tz_name!r}; using UTC")
            tz = ZoneInfo("UTC")

    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    today_local = now_utc.astimezone(tz).date() if tz else now_utc.date()

    start = start_from or today_local
    if start < today_local:
        start = today_local
    # First date on/after `start` that lands on the requested weekday.
    d = start + timedelta(days=(weekday - start.weekday()) % 7)

    if count is not None:
        n = max(1, min(int(count), SERIES_MAX_OCCURRENCES))
    elif until_date is not None:
        n = SERIES_MAX_OCCURRENCES
    else:
        n = SERIES_DEFAULT_COUNT

    out: List[Dict[str, Any]] = []
    idx = 0
    # Bounded walk (cap + 2 candidate dates) — a same-day time already
    # past rolls to next week, so allow a couple of non-emitting steps.
    for _step in range(SERIES_MAX_OCCURRENCES + 2):
        if len(out) >= n:
            break
        if until_date is not None and d > until_date:
            break
        local = (datetime.combine(d, at, tzinfo=tz) if tz
                 else datetime.combine(d, at, tzinfo=timezone.utc))
        utc = local.astimezone(timezone.utc)
        if utc > now_utc:
            idx += 1
            out.append({"date": d, "local": local, "utc": utc,
                        "utc_iso": _z(utc), "index": idx})
        d = d + timedelta(days=7)
    return out


# ─── Availability: date-specific closures ─────────────────────────────

def _date_closure_reason(av: Any, d: date) -> Optional[str]:
    """"blocked" when d falls in a BlockedRange, "closed" when a
    date-specific override closes that day, else None. Weekly hours are
    NOT enforced here — see the module docstring."""
    for blk in getattr(av, "blocks", None) or []:
        try:
            if date.fromisoformat(blk.start) <= d <= date.fromisoformat(blk.end):
                return "blocked"
        except ValueError:
            continue
    d_iso = d.isoformat()
    for ov in getattr(av, "overrides", None) or []:
        if ov.date == d_iso and not ov.hours:
            return "closed"
    return None


def _business_availability(business_id: str) -> Any:
    """businesses.settings.availability → BusinessAvailability (open-default
    when unset), plus the resolved timezone chain."""
    from availability import BusinessAvailability
    from availability_engine import resolved_tz_name
    from availability_router import _practitioner_timezone

    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id,settings&limit=1") or []
    settings = (rows[0].get("settings") or {}) if rows else {}
    av = BusinessAvailability.from_settings_dict(settings.get("availability"))
    tz_name = resolved_tz_name(
        av, _practitioner_timezone(rows[0].get("owner_id")) if rows else None)
    return av, tz_name


# ─── create_series ────────────────────────────────────────────────────

def _series_entries(business_id: str, series_id: str, *,
                    active_only: bool = True,
                    from_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    q = (f"/module_entries?business_id=eq.{business_id}"
         f"&data->>series_id=eq.{series_id}")
    if active_only:
        q += "&status=eq.active"
    if from_iso:
        q += f"&appointment_at=gte.{from_iso}"
    q += "&select=id,data,status,appointment_at&order=appointment_at.asc&limit=100"
    rows = sb_clients.sb_get_as_service(q) or []
    return rows if isinstance(rows, list) else []


def create_series(
    business_id: str,
    *,
    offering: Dict[str, Any],
    contact: Optional[Dict[str, Any]],
    customer_name: str,
    customer_email: str = "",
    weekday: int,
    at: time,
    tz_name: Optional[str] = None,
    start_from: Optional[date] = None,
    count: Optional[int] = None,
    until_date: Optional[date] = None,
    notes: str = "",
    series_id: Optional[str] = None,
    booked_by: str = "operator",
) -> Dict[str, Any]:
    """Book a weekly series. Occurrences that pass the guards are created;
    conflicts are skipped and reported. Returns:

      {"ok": True, "series_id": ..., "booked": [iso...], "skipped":
       [{"date": "Mar 3", "reason": "blocked"}...], "summary": "...",
       "already_existed": bool, "timezone": tz}

    or {"ok": False, "error": msg}. Never raises for a planning problem —
    callers (Chief verb, router) decide how to surface errors."""
    from booking_widget_router import (
        _bookings_module, _check_slot_available, _create_appointment,
        _maybe_denormalize_offering,
    )

    module = _bookings_module(business_id)
    if not module:
        return {"ok": False,
                "error": "This business doesn't have a booking calendar yet — "
                         "add the Bookings module first."}

    av, resolved_tz = _business_availability(business_id)
    tz_name = (tz_name or "").strip() or resolved_tz

    sid = (series_id or "").strip() or str(uuid.uuid4())
    # Idempotency guard (dedupe on series_id): a retried POST must not
    # double-book the client's next six months.
    existing = _series_entries(business_id, sid, active_only=False)
    if existing:
        return {
            "ok": True, "series_id": sid, "already_existed": True,
            "booked": [e.get("appointment_at") for e in existing],
            "skipped": [], "timezone": tz_name,
            "summary": f"This series already exists ({len(existing)} "
                       f"session{'s' if len(existing) != 1 else ''} on the books) "
                       f"— nothing was double-booked.",
        }

    plan = plan_occurrences(weekday=weekday, at=at, tz_name=tz_name,
                            start_from=start_from, count=count,
                            until_date=until_date)
    if not plan:
        return {"ok": False,
                "error": "That schedule produces no upcoming sessions — "
                         "check the day, time, and end date."}

    pdf = (module.get("archetype_params") or {}).get("primary_date_field") or "appointment_at"
    booked: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []

    # Denormalize ONCE (price/name/duration are the same for every
    # occurrence booked in this pass), on a template dict; per-occurrence
    # copies get their own timestamps + series index.
    base: Dict[str, Any] = {"customer_name": customer_name, "booked_by": booked_by}
    if customer_email:
        base["customer_email"] = customer_email
    if contact:
        base["contact_id"] = contact.get("id")
    if notes:
        base["notes"] = str(notes)[:2000]
    try:
        base = _maybe_denormalize_offering(business_id, module, offering.get("id"),
                                           None, base)
    except HTTPException as e:
        return {"ok": False, "error": str(e.detail)}
    except Exception as e:
        logger.warning(f"[series] denormalize failed: {e}")
        return {"ok": False,
                "error": "I couldn't price that offering just now — try again "
                         "in a moment."}
    duration = int(base.get("duration_min_at_booking")
                   or offering.get("duration_min") or 60)

    # A one-occurrence plan is just a guarded single booking (the UI's
    # non-repeating path rides this same endpoint) — no series stamp, so
    # no phantom repeat indicator on a booking that doesn't repeat.
    is_series = len(plan) > 1

    for occ in plan:
        reason = _date_closure_reason(av, occ["date"])
        if reason:
            skipped.append({"date": _pretty_date(occ["date"]), "reason": reason})
            continue
        if not _check_slot_available(business_id, occ["utc_iso"], duration):
            skipped.append({"date": _pretty_date(occ["date"]), "reason": "conflict"})
            continue
        entry_data = dict(base)
        entry_data[pdf] = occ["utc_iso"]
        entry_data["appointment_at"] = occ["utc_iso"]
        if is_series:
            entry_data["series_id"] = sid
            entry_data["series_index"] = occ["index"]
            entry_data["series_weekday"] = weekday
            entry_data["series_time_local"] = at.strftime("%H:%M")
            entry_data["series_timezone"] = tz_name
        entry = _create_appointment(business_id, module["id"], entry_data,
                                    created_by=booked_by)
        if entry:
            booked.append({"id": entry.get("id"), "appointment_at": occ["utc_iso"]})
        else:
            skipped.append({"date": _pretty_date(occ["date"]), "reason": "error"})

    n_b, n_s = len(booked), len(skipped)
    summary = f"{n_b} booked"
    if n_s:
        summary += (f", {n_s} skipped: "
                    + ", ".join(f"{s['date']} ({s['reason']})" for s in skipped))
    return {"ok": True, "series_id": sid, "already_existed": False,
            "booked": booked, "skipped": skipped, "summary": summary,
            "timezone": tz_name}


# ─── cancel_series ────────────────────────────────────────────────────

def cancel_series(
    business_id: str,
    series_id: str,
    *,
    from_iso: Optional[str] = None,
    cancelled_by: str = "operator",
    reason: str = "",
) -> Dict[str, Any]:
    """Cancel FUTURE occurrences of a series from `from_iso` (default now).
    Past entries stay untouched — they are history. Occurrences that were
    individually rescheduled (series_detached) keep living their own life
    and are skipped here."""
    from_iso = from_iso or _z(datetime.now(timezone.utc))
    rows = _series_entries(business_id, series_id, active_only=True,
                           from_iso=from_iso)
    if not rows:
        return {"ok": True, "cancelled": 0, "skipped_detached": 0,
                "summary": "No upcoming sessions in that series — nothing to cancel."}

    now_iso = datetime.now(timezone.utc).isoformat()
    cancelled = 0
    detached = 0
    for r in rows:
        data = dict(r.get("data") or {})
        if data.get("series_detached"):
            detached += 1
            continue
        data["cancelled_by"] = cancelled_by
        data["cancelled_at"] = now_iso
        data["series_cancelled"] = True
        if reason:
            data["cancellation_reason"] = str(reason)[:500]
        updated = sb_clients.sb_patch_as_service(
            f"/module_entries?id=eq.{r['id']}&business_id=eq.{business_id}",
            {"status": "cancelled", "data": data})
        if not updated:
            continue
        cancelled += 1
        # Free the mirrored session immediately (the 10-min sync tick
        # backstops this, but the calendar is being looked at NOW).
        try:
            marker = f"[booking:{r['id']}]"
            sb_clients.sb_patch_as_service(
                f"/sessions?business_id=eq.{business_id}"
                f"&notes=like.*{marker}*&status=eq.scheduled",
                {"status": "cancelled"})
        except Exception as e:
            logger.warning(f"[series] session cancel failed soft: {e}")

    summary = (f"Cancelled {cancelled} upcoming "
               f"session{'s' if cancelled != 1 else ''}. Past sessions are untouched.")
    if detached:
        summary += (f" {detached} rescheduled one{'s' if detached != 1 else ''} "
                    f"kept their own time.")
    return {"ok": True, "cancelled": cancelled, "skipped_detached": detached,
            "summary": summary}


# ─── Router endpoints (operator-side, authed, member+) ────────────────

def _require_member_writer(business_id: str, user: AuthedUser) -> str:
    """The shared role ladder — member rank and above may write bookings
    (matches the seat-access arc's member-write posture on module_entries)."""
    from business_users_router import require_role
    return require_role(business_id, str(user.id), "member")


class SeriesBody(BaseModel):
    business_id: str
    weekday: Any = Field(..., description="0-6 (Mon=0) or a weekday name")
    time: str = Field(..., description='"HH:MM" local wall time')
    timezone: Optional[str] = None       # default: the business tz chain
    start_from: Optional[str] = None     # "YYYY-MM-DD"
    count: Optional[int] = None          # capped at SERIES_MAX_OCCURRENCES
    until_date: Optional[str] = None     # "YYYY-MM-DD" (inclusive)
    offering_id: Optional[str] = None
    offering_name: Optional[str] = None
    contact_id: Optional[str] = None
    contact_name: Optional[str] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    notes: Optional[str] = None
    series_id: Optional[str] = None      # client-supplied for idempotent retries


def _parse_iso_date(raw: Optional[str], label: str) -> Optional[date]:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, f"{label} must be YYYY-MM-DD")


@router.post("/series")
async def post_series(body: SeriesBody,
                      user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Book a weekly series. Skips conflicting occurrences and reports them."""
    import asyncio

    _require_member_writer(body.business_id, user)

    weekday = parse_weekday(body.weekday)
    if weekday is None:
        raise HTTPException(400, "weekday must be 0-6 (Mon=0) or a weekday name")
    at = parse_hhmm(body.time)
    if at is None:
        raise HTTPException(400, 'time must be "HH:MM"')
    start_from = _parse_iso_date(body.start_from, "start_from")
    until = _parse_iso_date(body.until_date, "until_date")
    if body.count is None and until is None:
        raise HTTPException(400, "give either count or until_date")

    def _resolve_and_create() -> Dict[str, Any]:
        # Same resolvers the Chief verbs use — id wins, fuzzy name asks.
        from chief_booking_actions import _resolve_contact, _resolve_offering
        action = {"offering_id": body.offering_id or "",
                  "offering_name": body.offering_name or "",
                  "contact_id": body.contact_id or "",
                  "contact_name": body.contact_name or ""}
        off = _resolve_offering(body.business_id, action)
        if off.get("error"):
            return {"ok": False, "error": off["error"], "status": 400}
        offering = off["offering"]
        if not offering.get("is_active"):
            return {"ok": False, "status": 400,
                    "error": f"{offering.get('name')} isn't active right now."}
        con = _resolve_contact(body.business_id, action)
        if con.get("error"):
            return {"ok": False, "error": con["error"], "status": 400}
        contact = con.get("contact")
        customer_name = ((body.customer_name or "").strip()
                         or (contact or {}).get("name") or "").strip()
        if not customer_name:
            return {"ok": False, "status": 400,
                    "error": "Who is this series for? Give a contact or a name."}
        return create_series(
            body.business_id,
            offering=offering, contact=contact,
            customer_name=customer_name,
            customer_email=(body.customer_email
                            or (contact or {}).get("email") or "").strip().lower(),
            weekday=weekday, at=at,
            tz_name=body.timezone, start_from=start_from,
            count=body.count, until_date=until,
            notes=body.notes or "", series_id=body.series_id,
            booked_by=f"operator:{user.id}",
        )

    result = await asyncio.to_thread(_resolve_and_create)
    if not result.get("ok"):
        raise HTTPException(result.get("status") or 422,
                            result.get("error") or "series creation failed")
    result.pop("status", None)
    return result


@router.delete("/series/{series_id}")
async def delete_series(series_id: str, business_id: str,
                        from_date: Optional[str] = None,
                        user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Cancel a series' FUTURE occurrences (from `from_date`, default now).
    Past sessions stay on the books; individually-rescheduled occurrences
    keep their own time."""
    import asyncio

    _require_member_writer(business_id, user)

    from_iso: Optional[str] = None
    s = (from_date or "").strip()
    if s:
        try:
            if len(s) == 10:
                from_iso = f"{s}T00:00:00Z"
            else:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                from_iso = _z(dt)
        except ValueError:
            raise HTTPException(400, "from_date must be YYYY-MM-DD or ISO datetime")

    return await asyncio.to_thread(
        cancel_series, business_id, series_id,
        from_iso=from_iso, cancelled_by=f"operator:{user.id}")
