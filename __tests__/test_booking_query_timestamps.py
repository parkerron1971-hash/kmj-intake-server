"""Booking queries send timestamps PostgREST can read.

A '+' in a URL query decodes to a space, so '...T14:00:00+00:00' reaches
Postgres as '...T14:00:00 00:00' and 400s (22007). sb_get_as_service turns
the 400 into None, and the booking code read None as "no bookings": the
double-book guard passed every slot and the booking session sync did
nothing (Sentry, 2026-10-01). The old tests stubbed a database that
accepted any URL, so the fake below answers the way PostgREST does.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import booking_widget_router as bwr
import sb_clients


def _postgrest_like(rows_for_module_entries):
    seen = []

    def fake_get(path):
        seen.append(path)
        if "+" in path.split("?", 1)[-1]:
            return None  # what a 22007 400 looks like to the caller
        if path.startswith("/module_entries"):
            return list(rows_for_module_entries)
        if path.startswith("/custom_modules"):
            return [{"id": "m1", "business_id": "b1"}]
        return []
    return fake_get, seen


def test_pg_ts_never_carries_a_plus():
    aware = datetime(2026, 10, 1, 2, 27, 47, 655243, tzinfo=timezone.utc)
    assert bwr._pg_ts(aware) == "2026-10-01T02:27:47.655243Z"
    eastern = aware.astimezone(timezone(timedelta(hours=-4)))
    assert bwr._pg_ts(eastern) == "2026-10-01T02:27:47.655243Z"
    assert "+" not in bwr._pg_ts(aware + timedelta(hours=5))
    assert bwr._pg_ts(datetime(2026, 10, 1, 9, 0)) == "2026-10-01T09:00:00"


def test_double_book_guard_refuses_a_taken_slot(monkeypatch):
    taken = [{"appointment_at": "2026-09-14T14:00:00+00:00",
              "duration_min_at_booking": 60, "duration_min": 60}]
    fake, seen = _postgrest_like(taken)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake)
    business = {"id": "b1", "settings": {"availability": {}}}
    ok = bwr._check_slot_available("b1", "2026-09-14T14:00:00Z", 60, business=business)
    assert ok is False, "the slot is taken; the guard must refuse it"
    assert all("+" not in p.split("?", 1)[-1] for p in seen)


def test_booking_session_sync_queries_are_readable(monkeypatch):
    monkeypatch.setenv("BOOKING_SESSION_SYNC", "on")
    fake, seen = _postgrest_like([])
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda *a, **k: None)
    asyncio.run(bwr.booking_session_sync_tick())
    entry_reads = [p for p in seen if p.startswith("/module_entries")]
    assert len(entry_reads) == 2, entry_reads
    assert all("+" not in p.split("?", 1)[-1] for p in entry_reads)
