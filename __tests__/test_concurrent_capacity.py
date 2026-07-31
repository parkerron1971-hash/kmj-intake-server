"""
__tests__/test_concurrent_capacity.py — multi-chair capacity v1.

THE GAP: the engine enforced single-occupancy — one booking killed the
slot for everyone (compute_slots' any-overlap removal + the D.4 race
guard's exists-check). A 3-chair barbershop could book one guest at a
time.

THE MODEL: businesses.settings.availability.concurrent_capacity (1-20,
default 1) — same business-level home as arrival_window_min, same
no-SQL settings discipline. A slot stays available while OVERLAPPING
bookings < capacity, in BOTH places that decide availability:
compute_slots' overlap removal AND _check_slot_available (which must
COUNT, not exists-check). Full per-chair assignment stays deferred to
v2 per the D5/D6 rulings in availability.py.

BYTE-IDENTICAL GUARANTEE: capacity=1 is exactly the old rule
(count >= 1 ≡ "any overlap") — pinned below the same way the
arrival-window tests pinned plain businesses.
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from datetime import date, datetime

import pytest

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

from availability import (
    BusinessAvailability,
    TimeRange,
    WeeklyAvailability,
)
from availability_engine import compute_slots


def _nyc_business(**overrides) -> BusinessAvailability:
    kwargs = dict(
        timezone="America/New_York",
        weekly=WeeklyAvailability(
            mon=[TimeRange(start="08:00", end="17:00")],
        ),
        slot_granularity_min=60,
        lead_time_min=0,
    )
    kwargs.update(overrides)
    return BusinessAvailability(**kwargs)


def _fixed_now():
    # Mon Sep 14 2026, 6:00 AM Eastern — before opening.
    if ZoneInfo is None:
        return datetime(2026, 9, 14, 6, 0, 0)
    return datetime(2026, 9, 14, 6, 0, 0, tzinfo=ZoneInfo("America/New_York"))


def _booking_at_10am_eastern():
    # 10:00 Eastern = 14:00 UTC on 2026-09-14 (EDT).
    return {"appointment_at": "2026-09-14T14:00:00+00:00",
            "duration_min_at_booking": 60}


def _slots(av, bookings=None):
    return compute_slots(
        availability=av,
        existing_bookings=bookings or [],
        offering_duration_min=60,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=_fixed_now(),
    )


# ─── engine: capacity counting ───────────────────────────────────────

def test_capacity_2_slot_stays_open_after_one_booking():
    av = _nyc_business(concurrent_capacity=2)
    starts = [s["start_local"] for s in _slots(av, [_booking_at_10am_eastern()])]
    assert "2026-09-14T10:00:00" in starts


def test_capacity_2_slot_closes_after_two_bookings():
    av = _nyc_business(concurrent_capacity=2)
    bookings = [_booking_at_10am_eastern(), _booking_at_10am_eastern()]
    starts = [s["start_local"] for s in _slots(av, bookings)]
    assert "2026-09-14T10:00:00" not in starts
    # Neighboring slots unaffected.
    assert "2026-09-14T09:00:00" in starts
    assert "2026-09-14T11:00:00" in starts


def test_capacity_counts_partial_overlaps_too():
    """A booking that merely OVERLAPS the slot (not exactly aligned)
    consumes a seat — the counting rule runs on the same interval math
    as the old any-overlap rule."""
    av = _nyc_business(concurrent_capacity=2, slot_granularity_min=30)
    bookings = [
        _booking_at_10am_eastern(),
        # 10:30 Eastern, 60 min — overlaps the 10:00-11:00 hour too.
        {"appointment_at": "2026-09-14T14:30:00+00:00",
         "duration_min_at_booking": 60},
    ]
    starts = [s["start_local"] for s in _slots(av, bookings)]
    assert "2026-09-14T10:30:00" not in starts   # both overlap → full
    assert "2026-09-14T10:00:00" not in starts   # both overlap → full
    assert "2026-09-14T09:00:00" in starts


# ─── capacity=1 businesses byte-identical ────────────────────────────

def test_capacity_1_single_booking_still_kills_the_slot():
    av = _nyc_business()  # default capacity 1
    starts = [s["start_local"] for s in _slots(av, [_booking_at_10am_eastern()])]
    assert "2026-09-14T10:00:00" not in starts
    assert "2026-09-14T09:00:00" in starts


def test_capacity_1_slot_payload_is_byte_identical():
    """Default-capacity businesses' slot payloads must not change AT
    ALL: same starts, same keys. Same vertical-neutrality pin as the
    arrival-window tests."""
    plain = _slots(_nyc_business())
    assert plain, "expected slots for an open Monday"
    for s in plain:
        assert set(s.keys()) == {"start_utc", "start_local", "duration_min"}
    explicit = _slots(_nyc_business(concurrent_capacity=1))
    assert plain == explicit


def test_default_capacity_is_1():
    assert BusinessAvailability().concurrent_capacity == 1
    assert BusinessAvailability.from_settings_dict({}).concurrent_capacity == 1


def test_settings_dict_round_trip():
    av = BusinessAvailability.from_settings_dict({
        "timezone": "America/New_York",
        "concurrent_capacity": 3,
    })
    assert av.concurrent_capacity == 3
    assert av.model_dump()["concurrent_capacity"] == 3


# ─── malformed settings degrade to 1 ─────────────────────────────────

@pytest.mark.parametrize("raw", ["nope", None, 0, -3, 999, "12.5"])
def test_malformed_capacity_degrades_to_1(raw):
    av = BusinessAvailability.from_settings_dict({
        "weekly": {"mon": [{"start": "08:00", "end": "17:00"}]},
        "concurrent_capacity": raw,
    })
    assert av.concurrent_capacity == 1
    # Load-bearing: junk capacity must NOT collapse the schedule to the
    # open default — the weekly hours survive.
    assert av.weekly.mon, "weekly schedule lost to a junk capacity value"


@pytest.mark.parametrize("settings", [
    None,
    {"availability": None},
    {"availability": "junk"},
    {"availability": {"concurrent_capacity": "nope"}},
    {"availability": {"concurrent_capacity": 0}},
    {"availability": {"concurrent_capacity": 50}},
])
def test_router_capacity_reader_fails_to_1(settings):
    from booking_widget_router import _concurrent_capacity
    biz = {"id": "b1", "settings": settings} if settings is not None else {"id": "b1"}
    assert _concurrent_capacity(biz) == 1


def test_router_capacity_reader_reads_the_value():
    from booking_widget_router import _concurrent_capacity
    biz = {"id": "b1", "settings": {"availability": {"concurrent_capacity": 3}}}
    assert _concurrent_capacity(biz) == 3
    assert _concurrent_capacity(None) == 1


# ─── race guard: COUNT, not exists-check ─────────────────────────────

def _guard(monkeypatch, *, existing_rows, settings_capacity=None,
           pass_business=True):
    """Run _check_slot_available for the 14:00Z slot against a stubbed
    DB. Returns the guard's verdict."""
    import booking_widget_router as bwr

    fetched_paths = []

    def _fake_get(path):
        fetched_paths.append(path)
        if path.startswith("/module_entries"):
            return list(existing_rows)
        if path.startswith("/businesses"):
            av = ({"concurrent_capacity": settings_capacity}
                  if settings_capacity is not None else {})
            return [{"id": "b1", "settings": {"availability": av}}]
        return []

    monkeypatch.setattr(bwr.sb_clients, "sb_get_as_service", _fake_get)

    business = None
    if pass_business:
        av = ({"concurrent_capacity": settings_capacity}
              if settings_capacity is not None else {})
        business = {"id": "b1", "settings": {"availability": av}}
    ok = bwr._check_slot_available(
        "b1", "2026-09-14T14:00:00Z", 60, business=business)
    return ok, fetched_paths


def test_guard_capacity_2_allows_the_second_booking(monkeypatch):
    ok, _ = _guard(monkeypatch,
                   existing_rows=[_booking_at_10am_eastern()],
                   settings_capacity=2)
    assert ok is True


def test_guard_capacity_2_refuses_the_third_booking(monkeypatch):
    """The 409-on-loss behavior survives at the NEW boundary: when the
    count fills between the customer's snapshot and their submit, the
    guard returns False and the caller's 409 fires."""
    ok, _ = _guard(monkeypatch,
                   existing_rows=[_booking_at_10am_eastern(),
                                  _booking_at_10am_eastern()],
                   settings_capacity=2)
    assert ok is False


def test_guard_capacity_1_unchanged(monkeypatch):
    ok, _ = _guard(monkeypatch,
                   existing_rows=[_booking_at_10am_eastern()])
    assert ok is False
    ok, _ = _guard(monkeypatch, existing_rows=[])
    assert ok is True


def test_guard_counts_only_overlapping_rows(monkeypatch):
    """Rows in the query window that do NOT overlap the requested slot
    consume no seat."""
    ok, _ = _guard(monkeypatch,
                   existing_rows=[
                       _booking_at_10am_eastern(),
                       # 12:00 Eastern — same window fetch, no overlap.
                       {"appointment_at": "2026-09-14T16:00:00+00:00",
                        "duration_min_at_booking": 60},
                   ],
                   settings_capacity=2)
    assert ok is True


def test_guard_fetches_settings_when_business_not_passed(monkeypatch):
    """booking_series + chief_booking_actions call the guard without a
    business row — capacity must be inherited via the internal settings
    fetch, not silently defaulted."""
    ok, paths = _guard(monkeypatch,
                       existing_rows=[_booking_at_10am_eastern()],
                       settings_capacity=2,
                       pass_business=False)
    assert ok is True
    assert any(p.startswith("/businesses") for p in paths)


def test_guard_malformed_settings_degrade_to_1(monkeypatch):
    import booking_widget_router as bwr

    def _fake_get(path):
        if path.startswith("/module_entries"):
            return [_booking_at_10am_eastern()]
        if path.startswith("/businesses"):
            return [{"id": "b1", "settings": {"availability": "junk"}}]
        return []

    monkeypatch.setattr(bwr.sb_clients, "sb_get_as_service", _fake_get)
    assert bwr._check_slot_available("b1", "2026-09-14T14:00:00Z", 60) is False
