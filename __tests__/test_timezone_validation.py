"""
__tests__/test_timezone_validation.py — the malformed-IANA class.

THE GAP: `BusinessAvailability.timezone` was an unvalidated Optional[str].
Found live on a real business (2026-08-08), stored as "America/New York"
— a space where the IANA name has an underscore. Nothing in either repo
writes that, so it arrived by hand or by dictation.

WHY IT MATTERED: `availability_engine._resolve_tz` logs an unknown zone
and falls back to UTC, so that shop's weekly 09:00-17:00 was served to
guests as 9am-5pm UTC — 5am to 1pm Eastern. This is the 9-to-5-as-UTC
bug of 2026-07-10 returning through a malformed value rather than a
missing one, and it is silent: the config looks populated and correct.

THE SHAPE OF THE FIX, which these tests pin:
  - READ never raises. `from_settings_dict` turns any validation error
    into the OPEN-DEFAULT config, so a raising validator would promote a
    typo'd zone into "bookable 24/7" — hours gone entirely, strictly
    worse than the UTC fallback. Unresolvable → None, and the documented
    chain (practitioner tz → PLATFORM_DEFAULT_TZ → UTC) takes over.
  - An unambiguous repair IS applied: spaces → underscores.
  - WRITE rejects loudly, because that is the one moment a human is
    present to fix it (covered in the router; the helper's contract is
    pinned here).
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from availability import (
    BusinessAvailability,
    normalize_tz,
    tz_resolves,
)


# ── the helper's contract ────────────────────────────────────────────

def test_valid_zone_passes_through_untouched():
    assert normalize_tz("America/New_York") == "America/New_York"
    assert normalize_tz("UTC") == "UTC"
    assert normalize_tz("Europe/London") == "Europe/London"


def test_the_live_bug_is_repaired():
    """The exact value found in production."""
    assert normalize_tz("America/New York") == "America/New_York"


def test_multi_space_zones_repair_too():
    assert normalize_tz("America/Los Angeles") == "America/Los_Angeles"
    assert normalize_tz("America/Argentina/Buenos Aires") == \
        "America/Argentina/Buenos_Aires"


def test_surrounding_whitespace_is_stripped():
    assert normalize_tz("  America/New_York  ") == "America/New_York"


def test_unrepairable_becomes_none_not_an_error():
    """None, never a raise — see the module docstring."""
    assert normalize_tz("Mars/Olympus") is None
    assert normalize_tz("Not a timezone at all") is None
    assert normalize_tz("EST5EDT_nonsense") is None


def test_empty_and_missing_are_none():
    assert normalize_tz(None) is None
    assert normalize_tz("") is None
    assert normalize_tz("   ") is None


def test_tz_resolves_agrees_with_normalize():
    assert tz_resolves("America/New_York") is True
    assert tz_resolves("America/New York") is False
    assert tz_resolves("Mars/Olympus") is False


# ── the model, which is what every read path goes through ────────────

def test_model_repairs_on_validate():
    av = BusinessAvailability.model_validate({"timezone": "America/New York"})
    assert av.timezone == "America/New_York"


def test_model_drops_unusable_zone_without_raising():
    av = BusinessAvailability.model_validate({"timezone": "Mars/Olympus"})
    assert av.timezone is None


def test_from_settings_dict_keeps_the_hours_when_the_zone_is_junk():
    """THE REGRESSION THIS EXISTS TO PREVENT.

    If the validator ever raises, from_settings_dict swallows it and
    returns the open-default — no weekly hours at all, which the engine
    reads as bookable 24/7. A shop with a typo in one field would have
    its whole schedule silently deleted. The hours must survive.
    """
    av = BusinessAvailability.from_settings_dict({
        "timezone": "Mars/Olympus",
        "weekly": {"mon": [{"start": "09:00", "end": "17:00"}]},
        "slot_granularity_min": 30,
    })
    assert av.timezone is None
    assert len(av.weekly.mon) == 1
    assert av.weekly.mon[0].start == "09:00"
    assert av.weekly.mon[0].end == "17:00"
    assert av.slot_granularity_min == 30


def test_a_good_config_round_trips_byte_identical():
    """Businesses with a valid zone must be untouched by any of this."""
    raw = {
        "timezone": "America/Chicago",
        "weekly": {"tue": [{"start": "08:00", "end": "12:00"}]},
        "slot_granularity_min": 15,
        "lead_time_min": 60,
        "concurrent_capacity": 3,
    }
    av = BusinessAvailability.model_validate(raw)
    dumped = av.model_dump()
    assert dumped["timezone"] == "America/Chicago"
    assert dumped["slot_granularity_min"] == 15
    assert dumped["lead_time_min"] == 60
    assert dumped["concurrent_capacity"] == 3


def test_none_timezone_still_allowed():
    """Open-default and un-stamped configs are legitimate — the fallback
    chain exists precisely for them."""
    av = BusinessAvailability.model_validate({})
    assert av.timezone is None
