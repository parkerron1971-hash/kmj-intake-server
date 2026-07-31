"""
__tests__/test_arrival_windows.py — contractor scheduling: arrival windows
+ the work_pipeline location_field.

THE GAP: the availability engine emitted exact instants only. A contractor
quotes "we'll arrive between 9 and 12" — vertical_intelligence's contractor
voice says committing to a date without a window is taboo, and the
onboarding empty-state ("Set your arrival windows...") pointed at a feature
that did not exist.

THE MODEL: businesses.settings.availability.arrival_window_min (see
availability.BusinessAvailability for why business-level, not per-offering).
Slots CARRY the window; bookings DENORMALIZE it (arrival_window_min_at_
booking, like price_at_booking); the confirmation email says date + window,
never a precise time.

DOUBLE-BOOK SEMANTICS: a windowed booking still consumes duration_min in
overlap math — the window is customer communication, the internal schedule
blocks the real work duration. Guarded here by asserting the windowed and
plain engines emit the SAME slot starts.
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
            tue=[TimeRange(start="08:00", end="17:00")],
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


def _slots(av):
    return compute_slots(
        availability=av,
        offering_duration_min=60,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=_fixed_now(),
    )


# ─── engine: windowed vs plain ───────────────────────────────────────

def test_windowed_business_slots_carry_the_window():
    slots = _slots(_nyc_business(arrival_window_min=180))
    assert slots, "expected slots for an open Monday"
    assert all(s["arrival_window_min"] == 180 for s in slots)


def test_plain_business_slots_are_byte_identical():
    """No window configured → the slot payload must not change AT ALL:
    same starts, same keys. This is the vertical-neutrality guarantee —
    a coach's widget cannot tell this feature shipped."""
    plain = _slots(_nyc_business())
    assert plain, "expected slots for an open Monday"
    for s in plain:
        assert set(s.keys()) == {"start_utc", "start_local", "duration_min"}


def test_window_does_not_change_which_slots_exist():
    """The double-book decision, as engine behavior: the window is a
    communication span, so slot fit + overlap math run on duration_min
    exactly as before. Windowed and plain businesses emit identical
    slot STARTS."""
    plain = _slots(_nyc_business())
    windowed = _slots(_nyc_business(arrival_window_min=180))
    assert [s["start_utc"] for s in plain] == [s["start_utc"] for s in windowed]
    assert [s["duration_min"] for s in plain] == [s["duration_min"] for s in windowed]


def test_windowed_booking_still_blocks_its_duration():
    """An existing booking removes overlapping slots for a windowed
    business exactly as it does for a plain one."""
    booking = [{
        # 10:00 Eastern = 14:00 UTC on 2026-09-14 (EDT).
        "appointment_at": "2026-09-14T14:00:00+00:00",
        "duration_min_at_booking": 60,
    }]
    av = _nyc_business(arrival_window_min=180)
    slots = compute_slots(
        availability=av,
        existing_bookings=booking,
        offering_duration_min=60,
        from_date=date(2026, 9, 14),
        to_date=date(2026, 9, 14),
        now=_fixed_now(),
    )
    starts = [s["start_local"] for s in slots]
    assert "2026-09-14T10:00:00" not in starts
    assert "2026-09-14T09:00:00" in starts


def test_settings_dict_round_trip():
    av = BusinessAvailability.from_settings_dict({
        "timezone": "America/New_York",
        "arrival_window_min": 120,
    })
    assert av.arrival_window_min == 120


def test_unset_window_defaults_to_none():
    assert BusinessAvailability.from_settings_dict({}).arrival_window_min is None
    assert BusinessAvailability().arrival_window_min is None


# ─── booking denormalization ─────────────────────────────────────────

def _biz(settings):
    return {"id": "b1", "name": "Test Trades", "settings": settings}


def test_booked_entry_gets_the_window_denormalized():
    from booking_widget_router import _stamp_arrival_window
    biz = _biz({"availability": {"arrival_window_min": 180}})
    out = _stamp_arrival_window(biz, {"appointment_at": "2026-09-14T14:00:00Z"})
    assert out["arrival_window_min_at_booking"] == 180
    # Original payload untouched (helper copies).
    assert out["appointment_at"] == "2026-09-14T14:00:00Z"


def test_plain_business_entry_is_untouched():
    from booking_widget_router import _stamp_arrival_window
    entry = {"appointment_at": "2026-09-14T14:00:00Z"}
    out = _stamp_arrival_window(_biz({}), entry)
    assert out == entry
    assert "arrival_window_min_at_booking" not in out


@pytest.mark.parametrize("settings", [
    None,
    {"availability": None},
    {"availability": "junk"},
    {"availability": {"arrival_window_min": "nope"}},
    {"availability": {"arrival_window_min": 0}},
    {"availability": {"arrival_window_min": -30}},
])
def test_malformed_window_settings_fail_to_plain(settings):
    """A bad settings blob must degrade to exact-time behavior, never
    crash a booking."""
    from booking_widget_router import _arrival_window_min, _stamp_arrival_window
    biz = _biz(settings) if settings is not None else {"id": "b1"}
    assert _arrival_window_min(biz) is None
    entry = {"x": 1}
    assert _stamp_arrival_window(biz, entry) == entry


# ─── confirmation email when-line ────────────────────────────────────

def test_windowed_when_line_says_date_and_window_not_a_time():
    from booking_confirmation_emails import _fmt_when
    line = _fmt_when("2026-09-14T13:00:00Z", "America/New_York", 180)
    assert "arrival between" in line
    assert "1:00 PM" in line and "4:00 PM" in line
    # Never the exact-time framing.
    assert " at " not in line
    assert "America/New_York business time" in line


def test_plain_when_line_is_unchanged():
    from booking_confirmation_emails import _fmt_local, _fmt_when
    plain = _fmt_when("2026-09-14T13:00:00Z", "America/New_York", None)
    assert plain == _fmt_local("2026-09-14T13:00:00Z", "America/New_York")
    assert " at " in plain


def test_email_body_renders_the_window():
    from booking_confirmation_emails import _build_html_body
    body = _build_html_body(
        business_name="Test Trades",
        customer_name="Sam",
        service_name="Service Call",
        appointment_at_iso="2026-09-14T13:00:00Z",
        duration_min=60,
        price=150.0,
        tz_label="America/New_York",
        hosted_page_url=None,
        cancellation_policy="24 hours' notice.",
        business_type="contractor",
        arrival_window_min=180,
    )
    assert "arrival between" in body
    # The contractor intro (PR #347) composes with the window line.
    assert "within the window above" in body


def test_email_body_without_window_keeps_exact_time():
    from booking_confirmation_emails import _build_html_body
    body = _build_html_body(
        business_name="Coach Co",
        customer_name="Sam",
        service_name="Session",
        appointment_at_iso="2026-09-14T13:00:00Z",
        duration_min=60,
        price=100.0,
        tz_label=None,
        hosted_page_url=None,
        cancellation_policy="24 hours' notice.",
        business_type="coach",
    )
    assert "arrival between" not in body
    assert "1:00 PM" in body


# ─── work_pipeline location_field ────────────────────────────────────

def _job_pipeline_spec(**overrides):
    base = {
        "slug": "jobs", "name": "Jobs", "description": "Active jobs",
        "intake_excerpt": "track my jobs", "reasoning": "staged site work",
        "archetype": "work_pipeline",
        "archetype_params": {
            "stages": [
                {"id": "estimate", "label": "Estimate"},
                {"id": "scheduled", "label": "Scheduled"},
                {"id": "in_progress", "label": "In progress"},
                {"id": "invoiced", "label": "Invoiced", "done": True},
            ],
            "stage_field": "stage", "title_field": "title",
            "location_field": "site_address", "item_noun": "Job",
        },
        "schema": {"fields": [
            {"name": "title", "type": "text", "label": "Job", "required": True},
            {"name": "stage", "type": "select", "label": "Stage",
             "options": ["estimate", "scheduled", "in_progress", "invoiced"]},
            {"name": "site_address", "type": "text", "label": "Site address"},
        ], "default_view": "board", "views": ["list", "board"],
            "board_column": "stage"},
    }
    base.update(overrides)
    return base


def test_location_field_with_valid_ref_validates():
    import module_spec_generator as msg
    spec = msg.ModuleSpec.model_validate(_job_pipeline_spec())
    assert spec.archetype_params["location_field"] == "site_address"


def test_location_field_dangling_ref_is_rejected():
    """Same ref-discipline as every other *_field param: a specified
    location_field must name a real schema field."""
    import module_spec_generator as msg
    with pytest.raises(Exception, match="not in schema.fields"):
        msg.ModuleSpec.model_validate(_job_pipeline_spec(
            archetype_params={"location_field": "no_such_field"}))


def test_palette_teaches_location_for_site_work():
    """The LLM can only fill what the palette describes — location_field
    must be in the work_pipeline prompt text so contractor job modules
    get it suggested."""
    import module_spec_generator as msg
    assert "location_field" in msg._SYSTEM_PROMPT
