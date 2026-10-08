"""Bookings fill their own columns (2026-10-08, the follow-up of #1335).

module_entries.appointment_at / .duration_min_at_booking were empty on every
production row: the widget, Chief and weekly series write the time and the
length into `data`. supabase/APPLY-2026-10-08-booking-columns.sql makes the
columns follow data (checked on a real Postgres by
__tests__/booking_columns_db.mjs); this file checks the backend side, which
must work BEFORE that file is applied as well as after:

  * the reads that filtered on the column alone now use the shared read
    (availability_engine.BOOKING_SELECT / booking_window_filter /
    booked_rows / booked_start): agent_site.slots_for (the agent site, the
    Site Concierge picker, B11's open chairs), the open-chairs booking
    history, and B7's bookings signal;
  * the backend reads a stored time the way the database does
    (__tests__/booking_time_cases.json, shared with the database check).

The fake is #1335's FakePostgrest, which parses and applies every filter in
the query string (a column compares as a timestamp, data->>key as text),
answers 400/None for a column module_entries does not have, and projects
`alias:data->>key` as text. No live calls.
"""
from __future__ import annotations

import inspect
import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import agent_site  # noqa: E402
import availability_engine as ae  # noqa: E402
import business_marketing_openings as op  # noqa: E402
import marketing_signals as sig  # noqa: E402
from test_booking_read_fix import BIZ, FakePostgrest, _entry, _use  # noqa: E402

UTC = timezone.utc
CASES = json.loads((_here / "booking_time_cases.json").read_text(encoding="utf-8"))


# ─── 1. The backend reads a stored time the way the database does ─────

@pytest.mark.parametrize("raw,want", CASES["times"])
def test_booking_instant_matches_the_database_cases(raw, want):
    got = ae.booking_instant(raw)
    if want is None:
        assert got is None
    else:
        assert got == datetime.fromisoformat(want.replace("Z", "+00:00"))
        assert got.tzinfo is not None and got.utcoffset() == timedelta(0)


@pytest.mark.parametrize("raw,want", CASES["lengths"])
def test_the_length_reader_matches_the_database_cases(raw, want):
    assert ae._minutes(raw) == want


def test_booked_start_takes_data_then_the_column():
    assert ae.booked_start({"booked_at": "2026-10-08T15:00:00Z",
                            "appointment_at": "2026-10-08T09:00:00+00:00"}) == datetime(2026, 10, 8, 15, tzinfo=UTC)
    assert ae.booked_start({"booked_at": None,
                            "appointment_at": "2026-10-08T09:00:00+00:00"}) == datetime(2026, 10, 8, 9, tzinfo=UTC)
    assert ae.booked_start({"booked_at": "2026-10-06"}) == datetime(2026, 10, 6, tzinfo=UTC)
    assert ae.booked_start({"booked_at": None, "appointment_at": None}) is None
    assert ae.booked_start("junk") is None


# ─── 2. agent_site.slots_for sees the bookings ─────────────────────────

THU = date(2026, 10, 15)                               # a Thursday
NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
HOURS = {"timezone": "UTC", "slot_granularity_min": 30,
         "weekly": {"thu": [{"start": "14:00", "end": "17:00"}]}}
BUNDLE = {"facts": {"id": BIZ, "availability": HOURS, "timezone": "UTC"}}
HALF_HOUR = {"id": "off-1", "duration_min": 30}
ALL_STARTS = ["14:00", "14:30", "15:00", "15:30", "16:00", "16:30"]


@pytest.fixture
def no_outside_calendar(monkeypatch):
    import outside_calendar
    monkeypatch.setattr(outside_calendar, "busy_blocks_for_dates", lambda *a, **k: [])


def _starts(slots):
    return [s["start_local"][11:16] for s in slots]


def test_slots_for_blocks_a_booking_stored_only_in_data(monkeypatch, no_outside_calendar):
    """The production shape: columns empty, time and length in data."""
    fake = _use(monkeypatch, FakePostgrest([_entry("2026-10-15T15:00:00Z", 60)]))
    slots = agent_site.slots_for(BUNDLE, HALF_HOUR, THU, THU, now=NOW)
    assert _starts(slots) == ["14:00", "14:30", "16:00", "16:30"]
    read = [p for p in fake.paths if p.startswith("/module_entries")][0]
    assert f"select={ae.BOOKING_SELECT}" in read
    assert ae.booking_window_filter(date(2026, 10, 14), date(2026, 10, 17)) in read
    assert "status=eq.active" in read and "+" not in read.split("?", 1)[1]


def test_slots_for_counts_a_booking_with_no_length_as_an_hour(monkeypatch, no_outside_calendar):
    """It used to count as 0 minutes there, which blocks nothing at all."""
    _use(monkeypatch, FakePostgrest([_entry("2026-10-15T15:00:00Z", None)]))
    slots = agent_site.slots_for(BUNDLE, HALF_HOUR, THU, THU, now=NOW)
    assert _starts(slots) == ["14:00", "14:30", "16:00", "16:30"]


@pytest.mark.parametrize("stored", ["2026-10-15T15:00:00Z", "2026-10-15T15:00:00+00:00"])
def test_slots_for_reads_both_production_offsets(monkeypatch, no_outside_calendar, stored):
    _use(monkeypatch, FakePostgrest([_entry(stored, 30)]))
    assert _starts(agent_site.slots_for(BUNDLE, HALF_HOUR, THU, THU, now=NOW)) == \
        ["14:00", "14:30", "15:30", "16:00", "16:30"]


def test_slots_for_still_sees_a_booking_once_the_column_is_filled(monkeypatch, no_outside_calendar):
    """After the migration: the column set and data still carrying the time."""
    row = _entry("2026-10-15T15:00:00Z", 60)
    row["appointment_at"], row["duration_min_at_booking"] = "2026-10-15T15:00:00+00:00", 60
    _use(monkeypatch, FakePostgrest([row]))
    assert _starts(agent_site.slots_for(BUNDLE, HALF_HOUR, THU, THU, now=NOW)) == \
        ["14:00", "14:30", "16:00", "16:30"]


def test_slots_for_blocks_a_booking_the_day_before_that_spills_in(monkeypatch, no_outside_calendar):
    _use(monkeypatch, FakePostgrest([_entry("2026-10-14T23:00:00Z", 16 * 60)]))      # until 15:00 Thursday
    assert _starts(agent_site.slots_for(BUNDLE, HALF_HOUR, THU, THU, now=NOW)) == \
        ["15:00", "15:30", "16:00", "16:30"]


def test_slots_for_leaves_out_cancelled_and_other_businesses(monkeypatch, no_outside_calendar):
    _use(monkeypatch, FakePostgrest([
        _entry("2026-10-15T15:00:00Z", 60, id="gone", status="cancelled"),
        _entry("2026-10-15T15:00:00Z", 60, id="theirs", business_id="b2"),
        _entry("2026-10-22T15:00:00Z", 60, id="next-week"),
    ]))
    assert _starts(agent_site.slots_for(BUNDLE, HALF_HOUR, THU, THU, now=NOW)) == ALL_STARTS


def test_slots_for_strict_still_raises_on_a_failed_or_full_read(monkeypatch, no_outside_calendar):
    """#1330's strict mode (B11's open chairs): a read that fails, or comes
    back at its row limit, is never "nothing booked"."""
    _use(monkeypatch, FakePostgrest(fail=True))
    with pytest.raises(HTTPException) as err:
        agent_site.slots_for(BUNDLE, HALF_HOUR, THU, THU, strict=True, now=NOW)
    assert err.value.status_code == 503
    # Not strict (the agent site, the concierge): unchanged, the read failing still answers.
    assert _starts(agent_site.slots_for(BUNDLE, HALF_HOUR, THU, THU, now=NOW)) == ALL_STARTS

    full = [_entry("2026-10-15T09:00:00Z", 5, id=f"e{i}") for i in range(agent_site.BOOKING_ROWS)]
    _use(monkeypatch, FakePostgrest(full))
    with pytest.raises(HTTPException) as err:
        agent_site.slots_for(BUNDLE, HALF_HOUR, THU, THU, strict=True, now=NOW)
    assert err.value.status_code == 503


# ─── 3. The open chairs' booking history (B11) ─────────────────────────

CUT, BEARD = "off-cut", "off-beard"
AT = datetime(2026, 10, 8, 15, tzinfo=UTC)


def _booked(start, offering, **kw):
    row = _entry(start, 30, **kw)
    row["data"]["offering_id"] = offering
    return row


def test_history_counts_data_only_bookings_by_their_data_offering(monkeypatch):
    fake = _use(monkeypatch, FakePostgrest([
        _booked("2026-09-01T19:00:00Z", CUT, id="a"),
        _booked("2026-09-08T19:00:00+00:00", CUT, id="b"),
        _booked("2026-09-15", CUT, id="c"),                               # date-only: midnight UTC
        _booked("2026-09-20T17:00:00Z", BEARD, id="d"),
        _booked("2026-10-08T14:59:00Z", BEARD, id="e"),                   # a minute before `at`: in
        _booked("2026-10-08T15:00:00Z", BEARD, id="now"),                 # `at` itself: out
        _booked("2026-08-09T14:00:00Z", BEARD, id="61-days"),             # before the 60 days: out
        _booked("2026-09-02T19:00:00Z", BEARD, id="x", status="cancelled"),
        _booked("2026-09-02T19:00:00Z", BEARD, id="y", business_id="b2"),
    ]))
    history = op.read_history(BIZ, AT)
    assert [h["appointment_at"] for h in history] == [
        "2026-10-08T14:59:00Z", "2026-09-20T17:00:00Z", "2026-09-15T00:00:00Z",
        "2026-09-08T19:00:00Z", "2026-09-01T19:00:00Z"]                   # newest first, all Z
    assert op.booked_counts(history) == {CUT: 3, BEARD: 2}
    read = [p for p in fake.paths if p.startswith("/module_entries")][0]
    assert f"select={ae.BOOKING_SELECT},offering_id:data->>offering_id" in read
    assert "+" not in read.split("?", 1)[1]
    # The weekday counts read the date-only booking (a Tuesday) too.
    assert op.weekday_counts(history, ZoneInfo("UTC"))[1] == 3            # Sep 1, 8, 15 are Tuesdays

    offerings = [
        {"id": CUT, "name": "Classic cut", "category": "service", "duration_min": 30, "is_active": True},
        {"id": BEARD, "name": "Beard trim", "category": "service", "duration_min": 15, "is_active": True},
    ]
    assert op.choose_offering(offerings, history) == (offerings[0], "most_booked")


def test_history_reads_the_column_once_it_is_filled(monkeypatch):
    row = _booked("2026-09-01T19:00:00Z", CUT)
    row["appointment_at"] = "2026-09-01T19:00:00+00:00"
    _use(monkeypatch, FakePostgrest([row]))
    assert op.read_history(BIZ, AT) == [{"appointment_at": "2026-09-01T19:00:00Z", "offering_id": CUT}]


def test_history_on_a_failed_read_is_unknown_not_empty(monkeypatch):
    _use(monkeypatch, FakePostgrest(fail=True))
    assert op.read_history(BIZ, AT) is None


# ─── 4. B7's bookings signal, like for like ────────────────────────────

SIG_NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)


def _made(start, created_at, **kw):
    row = _entry(start, 60, **kw)
    row["created_at"] = created_at
    return row


def test_signals_count_data_only_bookings_like_for_like(monkeypatch):
    """The next 7 days against what was already booked at the same point in
    each of the 4 weeks before (a booking made later does not count there)."""
    fake = _use(monkeypatch, FakePostgrest([
        _made("2026-10-10T15:00:00Z", "2026-10-01T09:00:00+00:00", id="ahead"),
        _made("2026-10-12", "2026-10-05T09:00:00+00:00", id="ahead-date-only"),
        _made("2026-10-15T11:59:00Z", "2026-10-05T09:00:00+00:00", id="ahead-last-minute"),
        _made("2026-10-15T12:00:00Z", "2026-10-05T09:00:00+00:00", id="beyond-the-week"),
        _made("2026-10-10T16:00:00Z", "2026-10-01T09:00:00+00:00", id="cancelled", status="cancelled"),
        # Week 1 before: [Oct 1 12:00, Oct 8 12:00). Booked by Oct 1 12:00 counts; later does not.
        _made("2026-10-03T15:00:00+00:00", "2026-09-20T09:00:00+00:00", id="w1-early"),
        _made("2026-10-03T16:00:00Z", "2026-10-02T09:00:00+00:00", id="w1-late"),
        # Week 3 before: [Sep 17 12:00, Sep 24 12:00).
        _made("2026-09-20", "2026-09-01T09:00:00+00:00", id="w3-date-only"),
        # Before the 4 weeks: not counted anywhere.
        _made("2026-09-09T15:00:00Z", "2026-09-01T09:00:00+00:00", id="too-old"),
    ]))
    assert sig._bookings(BIZ, SIG_NOW) == {"next_7_days": 3, "weekly_before": sig._average(2)}
    read = [p for p in fake.paths if p.startswith("/module_entries")][0]
    assert f"select={ae.BOOKING_SELECT},created_at" in read
    assert ae.booking_window_filter(date(2026, 9, 10), date(2026, 10, 16)) in read
    assert "+" not in read.split("?", 1)[1]


def test_signals_bookings_unread_on_a_failed_or_full_read(monkeypatch):
    _use(monkeypatch, FakePostgrest(fail=True))
    with pytest.raises(sig.Unread):
        sig._bookings(BIZ, SIG_NOW)
    monkeypatch.setattr(sig, "BOOKING_ROWS", 3)
    _use(monkeypatch, FakePostgrest([_made(f"2026-10-0{d}T15:00:00Z", "2026-09-01T00:00:00Z", id=f"r{d}")
                                     for d in (2, 3, 4)]))
    with pytest.raises(sig.Unread):
        sig._bookings(BIZ, SIG_NOW)


# ─── 5. The readers use the shared read ────────────────────────────────

def test_the_column_only_readers_moved_to_the_shared_read():
    for fn, names in ((agent_site.slots_for, ("BOOKING_SELECT", "booking_window_filter", "booked_rows")),
                      (op.read_history, ("BOOKING_SELECT", "booking_window_filter", "booked_start")),
                      (sig._bookings, ("BOOKING_SELECT", "booking_window_filter", "booked_start"))):
        src = inspect.getsource(fn)
        for name in names:
            assert name in src, f"{fn.__module__}.{fn.__name__} does not use {name}"
        assert "&appointment_at=gte." not in src, f"{fn.__module__}.{fn.__name__} filters on the column alone"
