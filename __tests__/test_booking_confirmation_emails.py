"""Unit tests for Phase D.4 booking confirmation emails (.ics generator)."""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from booking_confirmation_emails import (
    build_ics,
    _ics_escape,
    _ics_fold,
    _ics_dt,
    _parse_iso,
)


def _unfold(ics_text: str) -> str:
    """Undo RFC 5545 §3.1 line folding so substring assertions work."""
    return ics_text.replace("\r\n ", "")


# ─── escaping / folding helpers ─────────────────────────────────────

def test_escape_basic():
    assert _ics_escape("Hello, world") == "Hello\\, world"
    assert _ics_escape("Line 1\nLine 2") == "Line 1\\nLine 2"
    assert _ics_escape("a;b;c") == "a\\;b\\;c"
    assert _ics_escape("path\\to") == "path\\\\to"


def test_escape_none():
    assert _ics_escape(None) == ""
    assert _ics_escape("") == ""


def test_escape_carriage_return_stripped():
    # \r should be dropped (not escaped to '\r' literal).
    assert _ics_escape("a\rb") == "ab"


def test_fold_under_75_bytes_unchanged():
    line = "SUMMARY:Hello"
    assert _ics_fold(line) == line


def test_fold_long_line_inserts_CRLF_SPACE():
    line = "DESCRIPTION:" + ("x" * 200)
    folded = _ics_fold(line)
    assert "\r\n " in folded
    # No single line exceeds 75 octets
    for piece in folded.split("\r\n"):
        # First char of continuation pieces is the leading space, which
        # is part of the protocol — fine.
        assert len(piece.encode("utf-8")) <= 75 + 1  # +1 for the space


def test_dt_formats_as_utc_zulu():
    from datetime import datetime, timezone
    dt = datetime(2026, 6, 8, 13, 30, 0, tzinfo=timezone.utc)
    assert _ics_dt(dt) == "20260608T133000Z"


def test_dt_naive_assumed_utc():
    from datetime import datetime
    dt = datetime(2026, 6, 8, 13, 30, 0)
    assert _ics_dt(dt) == "20260608T133000Z"


def test_parse_iso_z_suffix():
    dt = _parse_iso("2026-06-08T09:00:00Z")
    assert dt is not None and dt.year == 2026 and dt.hour == 9


def test_parse_iso_explicit_offset():
    dt = _parse_iso("2026-06-08T09:00:00+00:00")
    assert dt is not None and dt.year == 2026


# ─── build_ics: structure ────────────────────────────────────────────


def _sample_kwargs(**overrides):
    base = dict(
        booking_id="bb111111-2222-3333-4444-555555555555",
        appointment_at_utc="2026-06-08T13:30:00+00:00",
        duration_min=30,
        business_name="Royal Barbers",
        service_name="Haircut",
        description="Standard cut + style",
        location="123 Main St, City",
        organizer_email="noreply@mysolutionist.app",
        attendee_email="customer@example.com",
        attendee_name="Sarah Lee",
    )
    base.update(overrides)
    return base


def test_build_ics_has_required_envelope():
    ics = build_ics(**_sample_kwargs()).decode("utf-8")
    assert "BEGIN:VCALENDAR" in ics
    assert "END:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics
    assert "END:VEVENT" in ics
    assert "VERSION:2.0" in ics
    assert "PRODID:" in ics


def test_build_ics_uid_uses_booking_id():
    ics = build_ics(**_sample_kwargs()).decode("utf-8")
    assert "UID:bb111111-2222-3333-4444-555555555555@mysolutionist.app" in ics


def test_build_ics_dtstart_dtend_are_utc():
    ics = build_ics(**_sample_kwargs(
        appointment_at_utc="2026-06-08T13:30:00Z",
        duration_min=45,
    )).decode("utf-8")
    assert "DTSTART:20260608T133000Z" in ics
    assert "DTEND:20260608T141500Z" in ics


def test_build_ics_summary_has_service_and_business():
    ics = build_ics(**_sample_kwargs()).decode("utf-8")
    assert "SUMMARY:Haircut at Royal Barbers" in ics


def test_build_ics_summary_without_service():
    ics = build_ics(**_sample_kwargs(service_name=None)).decode("utf-8")
    assert "SUMMARY:Appointment with Royal Barbers" in ics


def test_build_ics_escapes_commas_in_text():
    ics = build_ics(**_sample_kwargs(
        service_name="Premium Cut, Beard Trim, Style",
    )).decode("utf-8")
    # Commas inside TEXT values must be backslash-escaped per RFC 5545.
    assert "Premium Cut\\, Beard Trim\\, Style" in ics


def test_build_ics_escapes_semicolons_and_backslash():
    ics = build_ics(**_sample_kwargs(
        description="path\\to;file",
    )).decode("utf-8")
    assert "DESCRIPTION:path\\\\to\\;file" in ics


def test_build_ics_attendee_block():
    ics = _unfold(build_ics(**_sample_kwargs()).decode("utf-8"))
    assert "ATTENDEE" in ics
    assert "customer@example.com" in ics
    assert "CN=Sarah Lee" in ics  # name applied


def test_build_ics_organizer_block():
    ics = _unfold(build_ics(**_sample_kwargs()).decode("utf-8"))
    assert "ORGANIZER" in ics
    assert "mailto:noreply@mysolutionist.app" in ics


def test_build_ics_omits_optional_blocks_when_missing():
    ics = build_ics(**_sample_kwargs(
        location=None,
        description=None,
        organizer_email=None,
    )).decode("utf-8")
    assert "LOCATION:" not in ics
    assert "DESCRIPTION:" not in ics
    assert "ORGANIZER" not in ics


def test_build_ics_status_confirmed():
    ics = build_ics(**_sample_kwargs()).decode("utf-8")
    assert "STATUS:CONFIRMED" in ics


def test_build_ics_crlf_line_endings():
    ics = build_ics(**_sample_kwargs())
    assert b"\r\n" in ics  # Required by RFC 5545
    # And every line ends CRLF (no bare LF inside event body)
    text = ics.decode("utf-8")
    for line in text.split("\r\n"):
        assert "\n" not in line  # no bare LF anywhere


def test_build_ics_handles_invalid_appointment_at():
    # Defensive: malformed appointment_at_utc should NOT raise; the
    # builder returns an .ics with a fallback time so the file parses.
    ics = build_ics(**_sample_kwargs(appointment_at_utc="not-a-date"))
    assert b"BEGIN:VEVENT" in ics
    assert b"DTSTART:" in ics


def test_build_ics_duration_zero_dtend_equals_dtstart():
    ics = build_ics(**_sample_kwargs(
        appointment_at_utc="2026-06-08T09:00:00+00:00",
        duration_min=0,
    )).decode("utf-8")
    assert "DTSTART:20260608T090000Z" in ics
    assert "DTEND:20260608T090000Z" in ics
