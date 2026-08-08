"""
availability.py — Phase D.1.1 backend foundation.

Pydantic models for business-level availability config that lives at
businesses.settings.availability (per D.1 audit D1 ruling: γ).

Shape (stored as JSON on the businesses row):

    {
      "timezone": "America/New_York",
      "weekly": {
        "mon": [{"start": "09:00", "end": "17:00"}],
        ...
      },
      "overrides": [
        {"date": "2026-08-01", "hours": [{"start": "09:00", "end": "12:00"}]},
        {"date": "2026-12-25", "hours": []}     ← closed override
      ],
      "blocks": [
        {"start": "2026-08-15", "end": "2026-08-22", "reason": "vacation"}
      ],
      "slot_granularity_min": 30,
      "lead_time_min": 0
    }

Open-default (D.1 audit D8 ruling: α): when a business has no
availability set, the compute engine treats every day as bookable
24/7 with the default slot_granularity_min (30) and zero lead-time.
Practitioner can tighten via the BUILD-side editor (PR 2) when ready.

Single-business / single-booking-module scope per C.1.5 Plan A.
Per-service availability + multi-staff are explicitly deferred to v2
per D.1 audit D5/D6 rulings.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

try:
    from zoneinfo import ZoneInfo
except Exception:                                    # pragma: no cover
    ZoneInfo = None                                  # type: ignore

logger = logging.getLogger(__name__)


# Day-of-week keys used in WeeklyAvailability. Keep lowercase 3-letter
# canonical so we can match by `now.strftime("%a").lower()` in the engine.
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def tz_resolves(name: str) -> bool:
    """True when zoneinfo can load `name`. When zoneinfo is unavailable
    we cannot disprove anything, so everything 'resolves' — the engine
    already degrades to naive times in that environment."""
    if ZoneInfo is None:                             # pragma: no cover
        return True
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def normalize_tz(value: Optional[str]) -> Optional[str]:
    """Best-effort repair of a stored IANA name; None when unusable.

    Found live on a real business (2026-08-08): a timezone stored as
    "America/New York" — a space where the IANA name has an underscore.
    `availability_engine._resolve_tz` logs the unknown zone and falls
    back to UTC, so that shop's 09:00-17:00 was being served to guests
    as 9am-5pm UTC, i.e. 5am-1pm Eastern. The 9-to-5-as-UTC bug of
    2026-07-10, back from a malformed value instead of a missing one.

    Underscoring the spaces is the one repair that is unambiguous, so it
    is applied. Anything still unresolvable becomes None RATHER THAN
    RAISING, and that choice is load-bearing: `from_settings_dict`
    catches validation errors and returns the OPEN-DEFAULT config, so a
    raising validator would turn a shop with a typo'd zone into one
    bookable 24/7 — hours gone entirely, which is worse than the UTC
    fallback it replaces. None instead lets the documented chain
    (practitioner_profiles.timezone → PLATFORM_DEFAULT_TZ → UTC) do its
    job. The loud rejection belongs on the WRITE path, where a human is
    present to fix it — see availability_router.patch_availability.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if tz_resolves(s):
        return s
    underscored = s.replace(" ", "_")
    if underscored != s and tz_resolves(underscored):
        logger.warning("availability timezone %r repaired to %r", s, underscored)
        return underscored
    logger.warning("availability timezone %r is unresolvable; falling back to the tz chain", s)
    return None


class TimeRange(BaseModel):
    """An interval within a single day. Both start and end are
    HH:MM strings in the business timezone. end > start (engine
    rejects zero/negative ranges)."""
    start: str = Field(..., description='"HH:MM" 24-hour clock')
    end: str = Field(..., description='"HH:MM" 24-hour clock')

    @field_validator("start", "end")
    @classmethod
    def _hhmm_shape(cls, v: str) -> str:
        # Accept "9:00" → normalize to "09:00" for stable comparisons.
        v = (v or "").strip()
        if not v or ":" not in v:
            raise ValueError(f"time must be HH:MM, got {v!r}")
        try:
            hh, mm = v.split(":", 1)
            h, m = int(hh), int(mm)
        except ValueError:
            raise ValueError(f"time must be HH:MM, got {v!r}")
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"time out of range, got {v!r}")
        return f"{h:02d}:{m:02d}"


class DateOverride(BaseModel):
    """A specific date overrides the weekly schedule for that day.
    `hours=[]` means closed on that date even if the weekday would
    normally be open. `hours=[{...}]` means open exactly during those
    intervals on that date (replaces the weekly entry entirely)."""
    date: str = Field(..., description='"YYYY-MM-DD"')
    hours: List[TimeRange] = Field(default_factory=list)

    @field_validator("date")
    @classmethod
    def _date_shape(cls, v: str) -> str:
        v = (v or "").strip()
        # Minimal validation — the engine does the heavy lifting via
        # datetime.fromisoformat. Reject obviously malformed shapes.
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError(f"date must be YYYY-MM-DD, got {v!r}")
        return v


class BlockedRange(BaseModel):
    """A multi-day block (vacation, holiday week, etc.). Inclusive of
    both start and end dates. Supersedes weekly + overrides for those
    dates — no slots produced on blocked dates regardless of other
    config. `reason` is optional metadata for the practitioner UI."""
    start: str = Field(..., description='"YYYY-MM-DD"')
    end: str = Field(..., description='"YYYY-MM-DD"')
    reason: Optional[str] = None

    @field_validator("start", "end")
    @classmethod
    def _date_shape(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError(f"date must be YYYY-MM-DD, got {v!r}")
        return v


class WeeklyAvailability(BaseModel):
    """Recurring weekly schedule. Each weekday holds a list of
    TimeRange entries (empty list = closed). Multiple ranges per day
    allowed (e.g. split shift: 9-12, 13-17)."""
    mon: List[TimeRange] = Field(default_factory=list)
    tue: List[TimeRange] = Field(default_factory=list)
    wed: List[TimeRange] = Field(default_factory=list)
    thu: List[TimeRange] = Field(default_factory=list)
    fri: List[TimeRange] = Field(default_factory=list)
    sat: List[TimeRange] = Field(default_factory=list)
    sun: List[TimeRange] = Field(default_factory=list)


class BusinessAvailability(BaseModel):
    """Top-level availability config stored at
    businesses.settings.availability. All fields optional with sensible
    defaults so partial configs round-trip cleanly through the
    practitioner editor."""
    timezone: Optional[str] = Field(
        default=None,
        description="IANA tz e.g. 'America/New_York'. Falls back to "
                    "practitioner_profiles.timezone then 'UTC'.",
    )

    @field_validator("timezone")
    @classmethod
    def _tz_usable(cls, v: Optional[str]) -> Optional[str]:
        """Never raise — see normalize_tz for why None beats an error."""
        return normalize_tz(v)
    weekly: WeeklyAvailability = Field(default_factory=WeeklyAvailability)
    overrides: List[DateOverride] = Field(default_factory=list)
    blocks: List[BlockedRange] = Field(default_factory=list)
    slot_granularity_min: int = Field(default=30, ge=5, le=240)
    lead_time_min: int = Field(default=0, ge=0)
    # ─── Arrival windows (contractor scheduling) ─────────────────────
    # When set, this business quotes ARRIVAL WINDOWS rather than exact
    # times — "we'll arrive between 9:00 and 12:00", the dispatch model
    # every trade runs on (see vertical_intelligence contractor voice:
    # "committing to a date without a window" is taboo).
    #
    # Why it lives HERE and not on offerings: the window is a
    # scheduling-communication policy of the business's dispatch model,
    # not a property of one service — a contractor's whole calendar
    # works in windows. The availability blob is the scheduling-policy
    # home, already round-trips through GET/PATCH /availability with
    # validation for free, and needs no SQL (offerings has no jsonb
    # column). Bookings denormalize arrival_window_min_at_booking at
    # create time (like price_at_booking), so per-offering granularity
    # can be layered later without touching downstream surfaces.
    #
    # DOUBLE-BOOK SEMANTICS (load-bearing, decided with the feature):
    # a windowed booking still consumes its offering's duration_min
    # against availability overlap. The window is what the CUSTOMER is
    # told about arrival; the internal schedule blocks the real work
    # duration from the slot start. The engine's slot math is therefore
    # unchanged — windows are carried on slots and bookings, never
    # substituted into the overlap rule.
    #
    # None (the default) = exact-time scheduling — byte-identical
    # behavior for every existing business.
    arrival_window_min: Optional[int] = Field(
        default=None, ge=15, le=720,
        description="minutes in the quoted arrival window (e.g. 180 = "
                    "'between 9:00 and 12:00'); None = exact times",
    )
    # ─── Concurrent capacity (multi-chair v1) ────────────────────────
    # How many bookings may OVERLAP the same time. A 3-chair barbershop
    # sets 3 and three walk-ins can hold the same slot; the engine keeps
    # a slot available while overlapping bookings < capacity, and the
    # submit-side race guard COUNTS overlaps against the same number.
    #
    # Why it lives HERE and not per-chair/per-staff: full multi-staff
    # (per-chair assignment, per-provider calendars) is explicitly
    # deferred to v2 per the D5/D6 rulings above. v1 is pure CAPACITY —
    # the shop floor as one pool of N seats. Business-level, same home
    # as arrival_window_min, so it round-trips through GET/PATCH
    # /availability with validation for free and needs no SQL.
    #
    # Default 1 = single-occupancy: byte-identical behavior for every
    # existing business (count >= 1 is exactly the old "any overlap"
    # rule). Malformed values degrade to 1, never crash a booking.
    concurrent_capacity: int = Field(
        default=1, ge=1, le=20,
        description="bookings allowed to overlap the same time "
                    "(chairs/stations); 1 = one customer at a time",
    )

    @field_validator("concurrent_capacity", mode="before")
    @classmethod
    def _capacity_degrade(cls, v: object) -> int:
        """Malformed / out-of-range capacity degrades to 1 (single
        occupancy) instead of failing the whole availability blob — a
        junk capacity value must never collapse a valid weekly schedule
        to the open default."""
        try:
            n = int(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1
        return n if 1 <= n <= 20 else 1

    @classmethod
    def from_settings_dict(cls, raw: Optional[dict]) -> "BusinessAvailability":
        """Parse the raw settings.availability JSON if present, else
        return the open-default config (no weekly schedule, no overrides,
        no blocks; engine treats as bookable 24/7 per D8-α)."""
        if not raw or not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except Exception:
            # Defensive: malformed JSON in production → open default
            # rather than crashing the widget. The practitioner-facing
            # editor (PR 2) will surface the real shape.
            return cls()


def is_open_default(av: BusinessAvailability) -> bool:
    """True when no weekly hours, no overrides, no blocks are
    configured. Engine treats this as 24/7 open (D8-α). Used by the
    widget surface to optionally surface a "no availability configured
    yet" hint."""
    weekly_empty = all(
        not getattr(av.weekly, k) for k in WEEKDAY_KEYS
    )
    return weekly_empty and not av.overrides and not av.blocks
