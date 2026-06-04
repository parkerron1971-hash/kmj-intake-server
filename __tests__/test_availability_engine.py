"""
__tests__/test_availability_engine.py — Phase D.1.1 backend foundation.

Pure-function tests for the slot-computation engine. No DB, no
fixtures — every test calls compute_slots() with explicit inputs and
asserts on the output shape.

Coverage per the D.1 audit phase plan kill criterion:
  1. Weekly schedule — slot grid matches business hours
  2. Date override — specific date replaces weekly schedule
  3. Blocked range — full-day block produces no slots regardless
  4. Lead-time filter — slots before now+lead are dropped
  5. DST boundary — slots straddling DST transition remain correct
  6. Open-default — no availability config = bookable in the default
     window (the engine's open_default_window param)
  7. Existing bookings — overlapping booking removes the affected slot

Run via:  python -m pytest __tests__/test_availability_engine.py -v
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from datetime import date, datetime, timedelta

import pytest

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

from availability import (
    BlockedRange,
    BusinessAvailability,
    DateOverride,
    TimeRange,
    WeeklyAvailability,
)
from availability_engine import compute_slots


# Reference business: NYC barber, Mon-Fri 9-5, Wed off.
def _nyc_business() -> BusinessAvailability:
    return BusinessAvailability(
        timezone="America/New_York",
        weekly=WeeklyAvailability(
            mon=[TimeRange(start="09:00", end="17:00")],
            tue=[TimeRange(start="09:00", end="17:00")],
            wed=[],
            thu=[TimeRange(start="09:00", end="17:00")],
            fri=[TimeRange(start="09:00", end="17:00")],
            sat=[],
            sun=[],
        ),
        slot_granularity_min=30,
        lead_time_min=0,
    )


# Fixed "now" — Mon Sep 14, 2026 8:00 AM EDT (one hour before opening)
# Sep 14 2026 is a Monday — confirmed via Python date.
def _fixed_now_nyc():
    if ZoneInfo is None:
        return datetime(2026, 9, 14, 8, 0, 0)
    return datetime(2026, 9, 14, 8, 0, 0, tzinfo=ZoneInfo("America/New_York"))


# ─── 1. Weekly schedule ─────────────────────────────────────────────

def test_weekly_schedule_emits_slots_only_on_open_days():
    av = _nyc_business()
    now = _fixed_now_nyc()
    slots = compute_slots(
        availability=av,
        offering_duration_min=30,
        from_date=date(2026, 9, 14),  # Mon
        to_date=date(2026, 9, 20),    # Sun
        now=now,
    )
    # Mon, Tue, Thu, Fri open (4 days × 16 slots = 64); Wed/Sat/Sun closed.
    assert len(slots) == 64, f"expected 64 slots, got {len(slots)}"
    # Spot-check first slot of Monday
    assert slots[0]["start_local"].startswith("2026-09-14T09:00")
    assert slots[0]["duration_min"] == 30
    # No Wednesday slots
    wed_slots = [s for s in slots if "2026-09-16" in s["start_local"]]
    assert wed_slots == []


def test_weekly_schedule_granularity_15min():
    av = BusinessAvailability(
        timezone="America/New_York",
        weekly=WeeklyAvailability(mon=[TimeRange(start="09:00", end="10:00")]),
        slot_granularity_min=15,
    )
    now = _fixed_now_nyc()
    slots = compute_slots(
        availability=av,
        offering_duration_min=30,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=now,
    )
    # 1-hour window, 15-min granularity, 30-min slots:
    # 9:00, 9:15, 9:30 — that's 3 slots (9:30+30 = 10:00 fits)
    assert len(slots) == 3, f"expected 3 slots, got {len(slots)}"
    assert slots[0]["start_local"].startswith("2026-09-14T09:00")
    assert slots[2]["start_local"].startswith("2026-09-14T09:30")


# ─── 2. Date override ───────────────────────────────────────────────

def test_date_override_replaces_weekly():
    av = _nyc_business()
    # Override Mon Sep 14 to close at 12:00
    av.overrides = [
        DateOverride(date="2026-09-14", hours=[
            TimeRange(start="09:00", end="12:00"),
        ]),
    ]
    now = _fixed_now_nyc()
    slots = compute_slots(
        availability=av,
        offering_duration_min=30,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=now,
    )
    # 3-hour window, 30-min granularity → 6 slots (9, 9:30, 10, 10:30, 11, 11:30)
    assert len(slots) == 6, f"expected 6 slots, got {len(slots)}"
    assert slots[-1]["start_local"].startswith("2026-09-14T11:30")


def test_date_override_can_close_a_normally_open_day():
    av = _nyc_business()
    av.overrides = [
        DateOverride(date="2026-09-14", hours=[]),   # closed override
    ]
    now = _fixed_now_nyc()
    slots = compute_slots(
        availability=av,
        offering_duration_min=30,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=now,
    )
    assert slots == [], f"expected no slots on overridden-closed day"


# ─── 3. Blocked range ───────────────────────────────────────────────

def test_blocked_range_supersedes_weekly_and_overrides():
    av = _nyc_business()
    av.blocks = [
        BlockedRange(start="2026-09-14", end="2026-09-20", reason="vacation"),
    ]
    # Add an override that says "open 9-12 on Mon" — block should win.
    av.overrides = [
        DateOverride(date="2026-09-14", hours=[
            TimeRange(start="09:00", end="12:00"),
        ]),
    ]
    now = _fixed_now_nyc()
    slots = compute_slots(
        availability=av,
        offering_duration_min=30,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 20),
        now=now,
    )
    assert slots == [], f"blocked range should produce zero slots"


# ─── 4. Lead-time filter ────────────────────────────────────────────

def test_lead_time_drops_near_term_slots():
    av = _nyc_business()
    av.lead_time_min = 120  # 2-hour lead time
    # now = Mon 8am EDT, lead = +2h → earliest bookable = 10am EDT
    now = _fixed_now_nyc()
    slots = compute_slots(
        availability=av,
        offering_duration_min=30,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=now,
    )
    # Mon 9-5 minus 9:00 / 9:30 (before 10am) = 14 slots
    assert len(slots) == 14, f"expected 14 slots after lead-time filter, got {len(slots)}"
    assert slots[0]["start_local"].startswith("2026-09-14T10:00")


# ─── 5. DST boundary ────────────────────────────────────────────────

def test_dst_fall_back_produces_correct_utc_offsets():
    """Nov 1 2026 is the US fall-back date (3am EDT → 2am EST).
    Mon-Fri schedule means Mon Nov 2 (after the transition) is EST,
    Mon Oct 26 was EDT. Slots on those days have different UTC offsets."""
    if ZoneInfo is None:
        pytest.skip("zoneinfo not available")
    av = _nyc_business()
    now = datetime(2026, 10, 26, 0, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    slots = compute_slots(
        availability=av,
        offering_duration_min=30,
        from_date=date(2026, 10, 26),  # Mon EDT
        to_date=date(2026, 11, 2),     # Mon EST
        now=now,
    )
    # Find the 9am slot on each Monday and compare UTC offsets.
    mon_oct26 = next(s for s in slots if s["start_local"].startswith("2026-10-26T09:00"))
    mon_nov2 = next(s for s in slots if s["start_local"].startswith("2026-11-02T09:00"))
    # Oct 26 EDT 9am = 13:00 UTC
    assert mon_oct26["start_utc"].startswith("2026-10-26T13:00")
    # Nov 2 EST 9am = 14:00 UTC
    assert mon_nov2["start_utc"].startswith("2026-11-02T14:00")


# ─── 6. Open-default ────────────────────────────────────────────────

def test_open_default_no_availability_config_emits_slots():
    # No availability passed → engine treats as 24/7 open by default.
    # Constrain via open_default_window so the test isn't enormous.
    slots = compute_slots(
        availability=None,
        offering_duration_min=60,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=datetime(2026, 9, 14, 0, 0, 0),
        open_default_window=(9, 17),
    )
    # 9-17 = 8 hours, 60-min slots, default 30-min granularity:
    # 9, 9:30, 10, 10:30, ..., 16, 16:30 → but slot needs +60 to fit
    # So last slot is 16:00 (ends 17:00). Count: 9:00 ... 16:00 stepping 30 = 15 slots
    assert len(slots) == 15, f"expected 15 slots from open-default, got {len(slots)}"


# ─── 7. Existing bookings subtract ──────────────────────────────────

def test_existing_booking_removes_overlapping_slot():
    av = _nyc_business()
    now = _fixed_now_nyc()
    # Existing booking 10:00 EDT Mon Sep 14, 30 min.
    # 10:00 EDT = 14:00 UTC.
    bookings = [{
        "appointment_at": "2026-09-14T14:00:00Z",
        "duration_min_at_booking": 30,
    }]
    slots = compute_slots(
        availability=av,
        offering_duration_min=30,
        existing_bookings=bookings,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=now,
    )
    # Mon 9-5 = 16 slots, minus 1 booked = 15 expected.
    assert len(slots) == 15, f"expected 15 slots after subtracting booking, got {len(slots)}"
    # The 10:00 slot should be missing
    has_10 = any(s["start_local"].startswith("2026-09-14T10:00") for s in slots)
    assert not has_10, "10:00 slot should be removed by overlapping booking"


def test_existing_booking_partial_overlap_removes_affected_slots():
    """A 45-min booking starting at 10:15 should block the 10:00, 10:30, 11:00 slots
    (any slot whose interval overlaps the booked range)."""
    av = _nyc_business()
    now = _fixed_now_nyc()
    # 10:15 EDT = 14:15 UTC, 45 min → ends 15:00 UTC = 11:00 EDT
    bookings = [{
        "appointment_at": "2026-09-14T14:15:00Z",
        "duration_min_at_booking": 45,
    }]
    slots = compute_slots(
        availability=av,
        offering_duration_min=30,
        existing_bookings=bookings,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=now,
    )
    # 10:00 slot (10:00-10:30) overlaps booking start
    # 10:30 slot (10:30-11:00) overlaps booking middle/end
    # 11:00 slot (11:00-11:30) starts exactly when booking ends — no overlap
    # So expect 16 - 2 = 14 slots
    assert len(slots) == 14, f"expected 14 slots, got {len(slots)}"
    has_10 = any(s["start_local"].startswith("2026-09-14T10:00") for s in slots)
    has_1030 = any(s["start_local"].startswith("2026-09-14T10:30") for s in slots)
    has_11 = any(s["start_local"].startswith("2026-09-14T11:00") for s in slots)
    assert not has_10
    assert not has_1030
    assert has_11, "11:00 slot starts exactly when booking ends — should be available"


# ─── Defensive / edge ──────────────────────────────────────────────

def test_zero_duration_returns_empty():
    av = _nyc_business()
    slots = compute_slots(
        availability=av,
        offering_duration_min=0,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=_fixed_now_nyc(),
    )
    assert slots == []


def test_to_before_from_returns_empty():
    av = _nyc_business()
    slots = compute_slots(
        availability=av,
        offering_duration_min=30,
        from_date=date(2026, 9, 20),
        to_date=date(2026, 9, 14),
        now=_fixed_now_nyc(),
    )
    assert slots == []
