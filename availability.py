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

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# Day-of-week keys used in WeeklyAvailability. Keep lowercase 3-letter
# canonical so we can match by `now.strftime("%a").lower()` in the engine.
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


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
    weekly: WeeklyAvailability = Field(default_factory=WeeklyAvailability)
    overrides: List[DateOverride] = Field(default_factory=list)
    blocks: List[BlockedRange] = Field(default_factory=list)
    slot_granularity_min: int = Field(default=30, ge=5, le=240)
    lead_time_min: int = Field(default=0, ge=0)

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
