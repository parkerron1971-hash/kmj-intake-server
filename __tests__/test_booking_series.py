"""Recurring weekly bookings — the series engine + Chief verbs.

The contract these tests defend:
  • occurrences are planned per-occurrence with zoneinfo — 9am weekly in
    America/Chicago stays 9am LOCAL across a DST transition (a fixed UTC
    delta would drift an hour),
  • conflicting occurrences are SKIPPED and NAMED, never silently eaten
    and never fatal to the rest of the series,
  • every created entry carries the series stamp (series_id + index) in
    its data JSON, through the SAME widget write path as single bookings,
  • cancel-from-date touches only FUTURE occurrences; past entries are
    history; individually-rescheduled (detached) ones keep their own time,
  • a re-POST with the same series_id is a no-op (idempotency guard),
  • every Chief-verb return path carries result + label, and failures
    carry the machine-readable "failed": True flag (#345 seam).
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncio
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

import booking_series as bs
import chief_booking_actions as cba

BIZ = {"id": "biz1", "name": "Test Co"}
MODULE = {"id": "mod1", "archetype_params": {}}
OFFERING = {"id": "off1", "name": "Weekly Coaching", "duration_min": 60,
            "is_active": True}
CONTACT = {"id": "c1", "name": "Maria Lopez", "email": "m@x.com"}

# A fixed "now" so the suite never goes stale: everything is planned
# relative to this instant, not the wall clock.
NOW = datetime(2027, 3, 1, 12, 0, tzinfo=timezone.utc)


# ─── plan_occurrences (pure) ──────────────────────────────────────────

def test_plan_weekly_spacing_and_z_form():
    plan = bs.plan_occurrences(weekday=1, at=time(14, 0), tz_name="UTC",
                               start_from=date(2027, 4, 1), count=3, now=NOW)
    assert [p["index"] for p in plan] == [1, 2, 3]
    assert [p["date"].weekday() for p in plan] == [1, 1, 1]
    assert [(b["date"] - a["date"]).days
            for a, b in zip(plan, plan[1:])] == [7, 7]
    for p in plan:
        assert p["utc_iso"].endswith("Z"), "PostgREST timestamps: Z-form ALWAYS"
        assert "+00:00" not in p["utc_iso"]


def test_plan_respects_until_date_and_the_cap():
    plan = bs.plan_occurrences(weekday=1, at=time(9, 0), tz_name="UTC",
                               start_from=date(2027, 4, 6),
                               until_date=date(2027, 4, 20), now=NOW)
    assert [p["date"].isoformat() for p in plan] == [
        "2027-04-06", "2027-04-13", "2027-04-20"]  # inclusive end

    capped = bs.plan_occurrences(weekday=1, at=time(9, 0), tz_name="UTC",
                                 start_from=date(2027, 4, 6), count=999, now=NOW)
    assert len(capped) == bs.SERIES_MAX_OCCURRENCES


def test_plan_dst_spring_forward_keeps_local_time():
    """THE DST test. US spring-forward 2027 is Sunday Mar 14. A 9am
    Tuesday series in America/Chicago must stay 9am LOCAL on both sides:
    Mar 9 is CST (UTC-6 → 15:00Z), Mar 16 is CDT (UTC-5 → 14:00Z). A
    fixed UTC delta would put Mar 16 at 10am local — the exact bug
    zoneinfo-per-occurrence exists to prevent."""
    plan = bs.plan_occurrences(weekday=1, at=time(9, 0),
                               tz_name="America/Chicago",
                               start_from=date(2027, 3, 9), count=2, now=NOW)
    assert [p["date"].isoformat() for p in plan] == ["2027-03-09", "2027-03-16"]
    chi = ZoneInfo("America/Chicago")
    for p in plan:
        assert p["utc"].astimezone(chi).hour == 9, "local wall time must hold"
    assert plan[0]["utc_iso"] == "2027-03-09T15:00:00Z"   # CST, UTC-6
    assert plan[1]["utc_iso"] == "2027-03-16T14:00:00Z"   # CDT, UTC-5
    assert plan[0]["utc"].hour != plan[1]["utc"].hour, (
        "identical UTC hours would mean a fixed delta, not local-time recurrence")


def test_plan_same_day_past_time_rolls_to_next_week():
    # NOW is Monday Mar 1 2027, 12:00Z. A Monday 09:00 UTC series
    # "starting today" has already missed today's slot.
    plan = bs.plan_occurrences(weekday=0, at=time(9, 0), tz_name="UTC",
                               start_from=date(2027, 3, 1), count=1, now=NOW)
    assert plan[0]["date"] == date(2027, 3, 8)


def test_parse_weekday_and_time_shapes():
    assert bs.parse_weekday("tuesday") == 1
    assert bs.parse_weekday("Tue") == 1
    assert bs.parse_weekday(3) == 3
    assert bs.parse_weekday("9") is None or bs.parse_weekday("9") != 9  # out of range
    assert bs.parse_weekday("noday") is None
    assert bs.parse_hhmm("14:00") == time(14, 0)
    assert bs.parse_hhmm("9:30") == time(9, 30)
    assert bs.parse_hhmm("25:00") is None
    assert bs.parse_hhmm("") is None


# ─── create_series ────────────────────────────────────────────────────

def _patch_series(monkeypatch, *, conflicts=frozenset(), availability=None,
                  existing=None):
    """Wire the widget helpers + availability. `conflicts` is a set of
    YYYY-MM-DD strings whose slot check reports taken."""
    import booking_widget_router as bwr

    monkeypatch.setattr(bwr, "_bookings_module", lambda b: MODULE)
    monkeypatch.setattr(bwr, "_maybe_denormalize_offering",
                        lambda b, m, oid, qp, data: {**data,
                                                     "offering_id": oid,
                                                     "duration_min_at_booking": 60})
    monkeypatch.setattr(bwr, "_check_slot_available",
                        lambda b, when, dur: when[:10] not in conflicts)
    created = []

    def _create(business_id, module_id, data, created_by="booking_widget"):
        created.append({"business_id": business_id, "module_id": module_id,
                        "data": data, "created_by": created_by})
        return {"id": f"bk{len(created)}", "data": data}

    monkeypatch.setattr(bwr, "_create_appointment", _create)

    from availability import BusinessAvailability
    av = BusinessAvailability.from_settings_dict(availability)
    monkeypatch.setattr(bs, "_business_availability",
                        lambda b: (av, "America/Chicago"))
    monkeypatch.setattr(bs, "_series_entries",
                        lambda b, s, active_only=True, from_iso=None: existing or [])
    return created


def test_create_series_happy_path_stamps_every_entry(monkeypatch):
    created = _patch_series(monkeypatch)
    res = bs.create_series(
        "biz1", offering=OFFERING, contact=CONTACT,
        customer_name="Maria Lopez", weekday=1, at=time(9, 0),
        tz_name="UTC", start_from=date(2027, 4, 6), count=3,
        booked_by="chief_of_staff")

    assert res["ok"] and not res["already_existed"]
    assert res["summary"] == "3 booked"
    assert len(created) == 3
    sid = created[0]["data"]["series_id"]
    assert sid == res["series_id"]
    for i, c in enumerate(created, start=1):
        d = c["data"]
        assert d["series_id"] == sid, "one series_id across the whole series"
        assert d["series_index"] == i
        assert d["appointment_at"].endswith("Z")
        assert d["contact_id"] == "c1"
        assert d["duration_min_at_booking"] == 60, "P5 denormalization rode along"
        assert c["created_by"] == "chief_of_staff"


def test_create_series_skips_conflicts_and_reports_them(monkeypatch):
    created = _patch_series(monkeypatch, conflicts={"2027-04-13"})
    res = bs.create_series(
        "biz1", offering=OFFERING, contact=None, customer_name="Maria",
        weekday=1, at=time(9, 0), tz_name="UTC",
        start_from=date(2027, 4, 6), count=3)

    assert res["ok"]
    assert len(created) == 2, "the conflicting week must not be written"
    assert res["skipped"] == [{"date": "Apr 13", "reason": "conflict"}]
    assert res["summary"] == "2 booked, 1 skipped: Apr 13 (conflict)"


def test_create_series_skips_blocked_and_closed_dates(monkeypatch):
    availability = {
        "weekly": {"tue": [{"start": "09:00", "end": "17:00"}]},
        "blocks": [{"start": "2027-04-12", "end": "2027-04-18"}],   # vacation
        "overrides": [{"date": "2027-04-20", "hours": []}],          # closed day
    }
    created = _patch_series(monkeypatch, availability=availability)
    res = bs.create_series(
        "biz1", offering=OFFERING, contact=None, customer_name="Maria",
        weekday=1, at=time(9, 0), tz_name="UTC",
        start_from=date(2027, 4, 6), count=4)

    assert [c["data"]["appointment_at"][:10] for c in created] == [
        "2027-04-06", "2027-04-27"]
    assert res["skipped"] == [
        {"date": "Apr 13", "reason": "blocked"},
        {"date": "Apr 20", "reason": "closed"},
    ]
    assert "Apr 13 (blocked)" in res["summary"]
    assert "Apr 20 (closed)" in res["summary"]


def test_create_series_repost_is_idempotent(monkeypatch):
    """Dedupe on series_id: a retried POST reports the existing series and
    books NOTHING new."""
    created = _patch_series(monkeypatch, existing=[
        {"id": "bk1", "appointment_at": "2027-04-06T09:00:00", "data": {}}])
    res = bs.create_series(
        "biz1", offering=OFFERING, contact=None, customer_name="Maria",
        weekday=1, at=time(9, 0), tz_name="UTC",
        start_from=date(2027, 4, 6), count=3, series_id="sid-1")

    assert res["ok"] and res["already_existed"]
    assert created == [], "idempotent re-POST must not double-book"
    assert "already exists" in res["summary"]


def test_create_series_single_occurrence_gets_no_series_stamp(monkeypatch):
    """count=1 is the UI's NON-repeating path riding the same guarded
    endpoint — it must not stamp series metadata, or every plain booking
    grows a phantom repeat indicator."""
    created = _patch_series(monkeypatch)
    res = bs.create_series("biz1", offering=OFFERING, contact=None,
                           customer_name="Maria", weekday=1, at=time(9, 0),
                           tz_name="UTC", start_from=date(2027, 4, 6), count=1)
    assert res["ok"] and len(created) == 1
    assert "series_id" not in created[0]["data"]
    assert "series_index" not in created[0]["data"]


def test_create_series_without_a_bookings_module_reports_it(monkeypatch):
    import booking_widget_router as bwr
    monkeypatch.setattr(bwr, "_bookings_module", lambda b: None)
    res = bs.create_series("biz1", offering=OFFERING, contact=None,
                           customer_name="X", weekday=1, at=time(9, 0))
    assert not res["ok"] and "booking calendar" in res["error"]


# ─── cancel_series ────────────────────────────────────────────────────

def test_cancel_series_future_only_and_detached_survive(monkeypatch):
    """The query itself is the past-guard (appointment_at=gte.<from>), so
    assert the filter shape AND that detached rows returned by it are
    left alone."""
    queries = []
    patches = []

    def _get(path):
        queries.append(path)
        return [
            {"id": "bk2", "appointment_at": "2027-04-13T09:00:00",
             "data": {"series_id": "sid-1"}},
            {"id": "bk3", "appointment_at": "2027-04-20T09:00:00",
             "data": {"series_id": "sid-1", "series_detached": True}},
        ]

    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: patches.append((p, b)) or [{"id": "x"}])

    res = bs.cancel_series("biz1", "sid-1", from_iso="2027-04-10T00:00:00Z")

    assert res["ok"] and res["cancelled"] == 1 and res["skipped_detached"] == 1
    # Future-only lives in the query: from-date filter, Z-form, series key.
    q = queries[0]
    assert "appointment_at=gte.2027-04-10T00:00:00Z" in q
    assert "data->>series_id=eq.sid-1" in q
    assert "status=eq.active" in q
    # Only the attached row was cancelled; its mirrored session freed too.
    entry_patches = [p for p, b in patches if "module_entries" in p]
    assert entry_patches == ["/module_entries?id=eq.bk2&business_id=eq.biz1"]
    assert any("sessions" in p and "bk2" in p for p, b in patches)
    assert "Past sessions are untouched" in res["summary"]


def test_cancel_series_with_nothing_upcoming_is_calm(monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [])
    res = bs.cancel_series("biz1", "sid-404")
    assert res["ok"] and res["cancelled"] == 0
    assert "nothing to cancel" in res["summary"].lower()


# ─── reschedule detaches an occurrence ────────────────────────────────

def test_reschedule_detaches_a_series_occurrence_but_keeps_the_stamp(monkeypatch):
    import booking_widget_router as bwr
    import sb_clients
    monkeypatch.setattr(bwr, "_check_slot_available", lambda b, w, d: True)
    monkeypatch.setattr(bwr, "_mirror_booking_session", lambda b, e: None)
    monkeypatch.setattr(cba, "_find_booking", lambda b, a: {"booking": {
        "id": "bk2", "status": "active", "module_id": "mod1",
        "data": {"appointment_at": "2027-04-13T09:00:00Z", "customer_name": "Maria",
                 "series_id": "sid-1", "series_index": 2,
                 "duration_min_at_booking": 60}}})
    patches = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: patches.append((p, b)) or [{"id": "bk2"}])
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p: [{"id": "bk2", "data": {}}])

    out = cba._reschedule_booking_sync(BIZ, {
        "booking_id": "bk2", "new_appointment_at": "2027-04-14T10:00:00Z"})

    entry_patch = next(b for p, b in patches if "module_entries" in p)
    assert entry_patch["data"]["series_detached"] is True
    assert entry_patch["data"]["series_id"] == "sid-1", "stamp survives detach"
    assert "stands on its own" in out["result"]


# ─── Chief verbs: shape discipline on every path ──────────────────────

def _patch_chief_create(monkeypatch, series_result):
    monkeypatch.setattr(cba, "_resolve_offering",
                        lambda b, a: {"offering": OFFERING})
    monkeypatch.setattr(cba, "_resolve_contact",
                        lambda b, a: {"contact": CONTACT})
    calls = []

    def _create(business_id, **kw):
        calls.append(kw)
        return series_result

    monkeypatch.setattr(bs, "create_series", _create)
    return calls


def test_chief_create_recurring_happy_summary(monkeypatch):
    calls = _patch_chief_create(monkeypatch, {
        "ok": True, "series_id": "sid-1", "already_existed": False,
        "booked": [{"id": "bk1"}] * 12,
        "skipped": [{"date": "Mar 3", "reason": "blocked"},
                    {"date": "Mar 17", "reason": "conflict"}],
        "summary": "12 booked, 2 skipped: Mar 3 (blocked), Mar 17 (conflict)",
        "timezone": "America/Chicago"})

    out = cba._create_recurring_booking_sync(BIZ, {
        "contact_id": "c1", "offering_id": "off1",
        "weekday": "tuesday", "time": "14:00", "count": 14})

    assert out["type"] == "create_recurring_booking"
    assert out["result"] == ("12 booked, 2 skipped: Mar 3 (blocked), "
                             "Mar 17 (conflict)"), "the label must be honest"
    assert out["label"] == "Weekly Coaching — Maria Lopez · weekly"
    assert out["series_id"] == "sid-1"
    assert out["booked_count"] == 12
    assert calls[0]["weekday"] == 1 and calls[0]["booked_by"] == "chief_of_staff"


def test_chief_create_recurring_every_failure_path_has_shape(monkeypatch):
    """result + label + failed on EVERY refusal — the missing-key crash
    class from feedback_chief_action_shape, plus the #345 failure flag."""
    cases = [
        {},                                             # no weekday
        {"weekday": "tuesday"},                         # no time
        {"weekday": "tuesday", "time": "14:00",
         "until": "not-a-date", "contact_id": "c1"},    # bad until
    ]
    monkeypatch.setattr(cba, "_resolve_offering", lambda b, a: {"offering": OFFERING})
    monkeypatch.setattr(cba, "_resolve_contact", lambda b, a: {"contact": CONTACT})
    for action in cases:
        out = cba._create_recurring_booking_sync(BIZ, action)
        assert out["result"] and out["label"], f"shape broken for {action}"
        assert out.get("failed") is True, f"failure not flagged for {action}"


def test_chief_create_recurring_surfaces_engine_refusal(monkeypatch):
    _patch_chief_create(monkeypatch, {"ok": False, "error": "no calendar"})
    out = cba._create_recurring_booking_sync(BIZ, {
        "contact_id": "c1", "weekday": "tue", "time": "09:00"})
    assert out.get("failed") is True and out["result"] and out["label"]


def test_chief_cancel_recurring_by_name_finds_the_series(monkeypatch):
    import sb_clients
    monkeypatch.setattr(cba, "_bookings_module_id", lambda b: "mod1")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [
        {"id": "bk9", "appointment_at": "2027-04-13T09:00:00",
         "data": {"customer_name": "Maria Lopez", "series_id": "sid-1"}}])
    cancels = []
    monkeypatch.setattr(bs, "cancel_series",
                        lambda b, s, from_iso=None, cancelled_by="", reason="":
                        cancels.append((b, s, from_iso)) or
                        {"ok": True, "cancelled": 3, "skipped_detached": 0,
                         "summary": "Cancelled 3 upcoming sessions. "
                                    "Past sessions are untouched."})

    out = cba._cancel_recurring_booking_sync(BIZ, {"contact_name": "Maria"})

    assert cancels == [("biz1", "sid-1", None)]
    assert out["type"] == "cancel_recurring_booking"
    assert out["cancelled_count"] == 3
    assert out["result"] and out["label"] == "Maria"


def test_chief_cancel_recurring_from_bare_date_means_start_of_day(monkeypatch):
    cancels = []
    monkeypatch.setattr(cba, "_find_series_id", lambda b, a: {"series_id": "sid-1"})
    monkeypatch.setattr(bs, "cancel_series",
                        lambda b, s, from_iso=None, cancelled_by="", reason="":
                        cancels.append(from_iso) or
                        {"ok": True, "cancelled": 1, "skipped_detached": 0,
                         "summary": "Cancelled 1 upcoming session. "
                                    "Past sessions are untouched."})
    out = cba._cancel_recurring_booking_sync(BIZ, {
        "series_id": "sid-1", "from_date": "2027-04-10"})
    assert cancels == ["2027-04-10T00:00:00Z"]
    assert out["result"] and out["label"]


def test_chief_cancel_recurring_unknown_series_fails_with_shape(monkeypatch):
    monkeypatch.setattr(cba, "_bookings_module_id", lambda b: "mod1")
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [])
    out = cba._cancel_recurring_booking_sync(BIZ, {"contact_name": "Nobody"})
    assert out.get("failed") is True and out["result"] and out["label"]


def test_booking_fail_helper_carries_the_345_flag():
    """chief_booking_actions._fail messages ("I couldn't find that booking")
    never matched _action_failed's string sniffing — the flag is what makes
    these failures detectable. Regression guard on the seam repair."""
    out = cba._fail("create_recurring_booking", "nope")
    assert out.get("failed") is True
    assert out["result"] and out["label"]


# ─── registry + handler wiring ────────────────────────────────────────

def test_recurring_verbs_are_registered_and_classified():
    import inspect

    import action_registry as reg
    import chief_of_staff as cos
    for verb in ("create_recurring_booking", "cancel_recurring_booking"):
        assert verb in cos.ACTION_HANDLERS, f"{verb} not registered"
        assert inspect.iscoroutinefunction(cos.ACTION_HANDLERS[verb])
        assert reg.reversibility(verb) == "C", f"{verb} must be class C"
        assert not reg.is_bulk(verb), f"{verb} is single-series-target, not bulk"
        assert not reg.may_expose_to_agent(verb, allow_writes=True), (
            f"{verb} must never reach an agent surface")


def test_recurring_verbs_stay_off_the_mcp_read_surface():
    """test_mcp_server hardcodes the read-verb count as a tripwire; these
    are writes and must not appear there. Asserted directly so a future
    refactor can't quietly expose them."""
    import mcp_server
    for verb in ("create_recurring_booking", "cancel_recurring_booking"):
        assert verb not in getattr(mcp_server, "TOOL_SCHEMAS", {})


def test_async_wrappers_return_the_sync_result(monkeypatch):
    monkeypatch.setattr(cba, "_create_recurring_booking_sync",
                        lambda b, a: {"type": "create_recurring_booking",
                                      "result": "ok", "label": "X", "nav": None})
    out = asyncio.run(cba.handle_create_recurring_booking(None, BIZ, {}))
    assert out["result"] == "ok"
