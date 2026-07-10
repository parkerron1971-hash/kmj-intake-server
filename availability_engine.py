"""
availability_engine.py — Phase D.1.1 backend foundation.

Pure slot-computation logic. No DB. Tests-friendly. Takes already-loaded
availability + bookings + offering duration and produces the list of
available slot starts in the requested window.

Per D.1 audit rulings:
- D2 α — real-time compute (no caching here; the caller decides)
- D7 γ — slot starts emitted as both UTC ISO and business-TZ local ISO
- D8 α — open-default treats no-availability-config as 24/7 bookable

Slot length per slot equals the picked offering's duration_min.
Slot starts are aligned to availability.slot_granularity_min increments
from midnight in the business timezone.

Edge cases handled:
- DST boundaries (via zoneinfo)
- Blocked ranges supersede weekly + overrides
- Date-specific overrides supersede weekly
- Existing bookings remove any slot whose [start, start+duration) interval
  overlaps the booking's interval
- Lead-time filter: slots with start < now + lead_time are removed
- Past slots: slots with start < now are removed
- Window clamp: only slots within [from, to] in business-TZ days
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover — Python 3.9+ stdlib
    ZoneInfo = None  # type: ignore[assignment]

from availability import (
    BusinessAvailability,
    DateOverride,
    TimeRange,
    WEEKDAY_KEYS,
    is_open_default,
)

logger = logging.getLogger("availability_engine")


# Default look-ahead window when caller doesn't specify. 30 days matches
# the customer-facing widget's "next 30 days" UX.
DEFAULT_LOOKAHEAD_DAYS = 30

# Hard cap to prevent abuse / accidental huge queries.
MAX_LOOKAHEAD_DAYS = 90


def resolved_tz_name(av: BusinessAvailability,
                     practitioner_tz: Optional[str]) -> str:
    """The ONE timezone chain (2026-07-10, the 9-to-5-as-UTC bug):
       1. availability.timezone (stamped by the editor on save)
       2. practitioner_profiles.timezone (onboarding)
       3. PLATFORM_DEFAULT_TZ env — the platform backstop: every
          un-stamped config used to fall to UTC, serving a 9am-5pm
          schedule as 5am-1pm Eastern. Set to e.g. America/New_York
          on Railway while the beta is single-region.
       4. UTC (last resort).
    Routers use this for the response's timezone label too — one chain,
    no drift."""
    import os as _os
    return ((av.timezone or practitioner_tz
             or _os.environ.get("PLATFORM_DEFAULT_TZ", "").strip()
             or "UTC").strip() or "UTC")


def _resolve_tz(av: BusinessAvailability, practitioner_tz: Optional[str]) -> Any:
    """resolved_tz_name → ZoneInfo instance (or None when zoneinfo is
    unavailable — callers then treat the times as naive in business-tz
    semantics, which is correct enough for slot math but doesn't
    survive DST)."""
    tz_name = resolved_tz_name(av, practitioner_tz)
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning(f"unknown timezone {tz_name!r}; falling back to UTC")
        try:
            return ZoneInfo("UTC")
        except Exception:
            return None


def _date_iter(start: date, end: date):
    """Yield each date in [start, end] inclusive."""
    d = start
    while d <= end:
        yield d
        d = d + timedelta(days=1)


def _parse_hhmm(hhmm: str) -> time:
    """Parse HH:MM string into a time object. Caller ensures the value
    passed pydantic validation in availability.py."""
    h, m = hhmm.split(":", 1)
    return time(int(h), int(m))


def _hours_for_date(
    av: BusinessAvailability, d: date
) -> List[TimeRange]:
    """Resolve the open hours for a specific date in priority order:
       1. If date is inside any BlockedRange → closed (empty list)
       2. If date matches a DateOverride → use the override's hours
          (which may be empty = closed)
       3. Otherwise → use the weekly schedule for that weekday
       4. Open-default (no config at all) → return None marker, caller
          treats as 24/7

    Returns a list of TimeRange entries. Empty list means closed on
    that date. None means "no config at all — caller decides default"."""
    # 1. Block check
    for blk in av.blocks:
        try:
            bstart = date.fromisoformat(blk.start)
            bend = date.fromisoformat(blk.end)
        except ValueError:
            continue
        if bstart <= d <= bend:
            return []

    # 2. Override check
    date_iso = d.isoformat()
    for ov in av.overrides:
        if ov.date == date_iso:
            return list(ov.hours)

    # 3. Weekly schedule — open-default returns None so caller treats as 24/7
    if is_open_default(av):
        return None  # type: ignore[return-value]

    weekday_key = WEEKDAY_KEYS[d.weekday()]
    return list(getattr(av.weekly, weekday_key))


def _booking_intervals(
    bookings: List[Dict[str, Any]],
) -> List[tuple]:
    """Project existing bookings into (start_utc, end_utc) tuples for
    overlap math. Reads appointment_at + duration_min_at_booking from
    each row; falls back to 0 minutes if duration missing so we at
    least block the start instant.

    bookings is a list of dicts as returned by Supabase. Tolerant of
    missing/malformed rows."""
    out = []
    for b in bookings or []:
        appt = b.get("appointment_at")
        if not appt:
            continue
        try:
            # Supabase returns either bare ISO (no tz) or with +00:00.
            # Coerce to aware UTC.
            s = appt
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                # Assume the bare timestamp is already UTC (matches
                # storage convention from the existing book-anon path).
                if ZoneInfo is not None:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        except Exception:
            continue
        dur_min = b.get("duration_min_at_booking") or b.get("duration_min") or 0
        try:
            dur_min = int(dur_min)
        except (TypeError, ValueError):
            dur_min = 0
        end = dt + timedelta(minutes=max(dur_min, 0))
        out.append((dt, end))
    return out


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    """Inclusive overlap test: returns True iff the two intervals
    share any time (treating both as half-open [start, end))."""
    return a_start < b_end and b_start < a_end


def _aligned_slot_starts(
    open_ranges: List[TimeRange],
    granularity_min: int,
    tz,
    target_date: date,
    duration_min: int,
) -> List[datetime]:
    """Generate slot start datetimes (timezone-aware in business tz)
    for the open intervals on a single date. Slots step by granularity
    from each range's start. A slot is included only if [start,
    start+duration) fits inside the open range."""
    out: List[datetime] = []
    if duration_min <= 0:
        return out
    for r in open_ranges:
        rstart = _parse_hhmm(r.start)
        rend = _parse_hhmm(r.end)
        if rend <= rstart:
            continue
        # Build aware datetimes for this date + range
        if tz is not None:
            s_dt = datetime.combine(target_date, rstart, tzinfo=tz)
            e_dt = datetime.combine(target_date, rend, tzinfo=tz)
        else:
            s_dt = datetime.combine(target_date, rstart)
            e_dt = datetime.combine(target_date, rend)
        cur = s_dt
        step = timedelta(minutes=granularity_min)
        dur = timedelta(minutes=duration_min)
        while cur + dur <= e_dt:
            out.append(cur)
            cur = cur + step
    return out


def compute_slots(
    *,
    availability: Optional[Any] = None,
    practitioner_tz: Optional[str] = None,
    existing_bookings: Optional[List[Dict[str, Any]]] = None,
    offering_duration_min: int,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    now: Optional[datetime] = None,
    open_default_window: Optional[tuple] = None,
) -> List[Dict[str, Any]]:
    """Compute available slots for an offering in a date window.

    Args:
      availability — BusinessAvailability instance OR raw dict OR None
                     (None / open-default → treated as 24/7 bookable
                     per D8-α; engine uses open_default_window for
                     bounded slot output).
      practitioner_tz — IANA tz string fallback when availability has
                        no timezone set (typically from
                        practitioner_profiles.timezone).
      existing_bookings — list of module_entries rows with appointment_at
                          + duration_min_at_booking. Engine subtracts any
                          slot overlapping a booking's [start, end)
                          interval.
      offering_duration_min — duration of the offering being booked,
                              drives slot length.
      from_date / to_date — window in business-tz calendar days
                            (inclusive). Defaults to [today,
                            today+30].
      now — current time (override for testing). Defaults to
            datetime.now(tz=business_tz).
      open_default_window — when availability is open-default, the
                            (start_hour, end_hour) tuple within which
                            to emit slots. Default (0, 24) = full 24h.

    Returns list of dicts:
        [
          {
            "start_utc": "2026-09-14T13:00:00+00:00",
            "start_local": "2026-09-14T09:00:00",
            "duration_min": 30,
          },
          ...
        ]

    Pure function — no DB, no side effects."""
    if offering_duration_min <= 0:
        return []

    # Normalize availability
    if isinstance(availability, dict):
        av = BusinessAvailability.from_settings_dict(availability)
    elif isinstance(availability, BusinessAvailability):
        av = availability
    elif availability is None:
        av = BusinessAvailability()
    else:
        # Unknown shape → open-default
        av = BusinessAvailability()

    tz = _resolve_tz(av, practitioner_tz)

    # Resolve `now` in business tz
    if now is None:
        now = datetime.now(tz=tz) if tz is not None else datetime.utcnow()
    elif now.tzinfo is None and tz is not None:
        now = now.replace(tzinfo=tz)

    # Resolve window
    if from_date is None:
        from_date = now.date() if hasattr(now, "date") else date.today()
    if to_date is None:
        to_date = from_date + timedelta(days=DEFAULT_LOOKAHEAD_DAYS)
    # Hard cap
    if (to_date - from_date).days > MAX_LOOKAHEAD_DAYS:
        to_date = from_date + timedelta(days=MAX_LOOKAHEAD_DAYS)
    if to_date < from_date:
        return []

    # Lead-time threshold
    lead = timedelta(minutes=max(av.lead_time_min, 0))
    earliest = now + lead

    # Booking intervals (already aware UTC)
    booked = _booking_intervals(existing_bookings or [])

    # Open-default window for emission
    open_start_hr, open_end_hr = (open_default_window or (0, 24))
    is_open = is_open_default(av)
    open_default_ranges = (
        [TimeRange(start=f"{open_start_hr:02d}:00", end=f"{open_end_hr:02d}:00")]
        if is_open
        else None
    )

    out: List[Dict[str, Any]] = []
    for d in _date_iter(from_date, to_date):
        hours = _hours_for_date(av, d)
        if hours is None:
            # Open-default
            hours = open_default_ranges or []
        if not hours:
            continue

        candidates = _aligned_slot_starts(
            hours,
            av.slot_granularity_min,
            tz,
            d,
            offering_duration_min,
        )
        for slot_start in candidates:
            slot_end = slot_start + timedelta(minutes=offering_duration_min)

            # Convert to UTC for comparison + emission
            if tz is not None and slot_start.tzinfo is not None:
                slot_start_utc = slot_start.astimezone(_utc_zone())
                slot_end_utc = slot_end.astimezone(_utc_zone())
            else:
                slot_start_utc = slot_start
                slot_end_utc = slot_end

            # Future-only (relative to now in business tz)
            if slot_start < earliest:
                continue

            # Subtract existing bookings
            conflict = False
            for b_start, b_end in booked:
                if _overlaps(slot_start_utc, slot_end_utc, b_start, b_end):
                    conflict = True
                    break
            if conflict:
                continue

            out.append({
                "start_utc": slot_start_utc.isoformat(),
                "start_local": slot_start.replace(tzinfo=None).isoformat(),
                "duration_min": offering_duration_min,
            })

    return out


def _utc_zone():
    """Lazy UTC zone — fall back to None if zoneinfo isn't available
    so the engine still produces naive timestamps in that environment."""
    if ZoneInfo is not None:
        try:
            return ZoneInfo("UTC")
        except Exception:
            return None
    return None
