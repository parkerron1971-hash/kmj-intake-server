"""P0.1 — Chief booking verbs.

Pure in-process logic; Supabase and the booking_widget_router helpers are
mocked (same philosophy as the Phase G / F.2 suites).

The contract these tests defend:
  • every handler returns result + label (a missing key blanks the app),
  • the slot guard is honored — Chief never books over an existing client,
  • ambiguity is surfaced as a question, never resolved by guessing,
  • reschedule writes the time into `data` (appointment_at is DB-maintained),
  • cancel frees the mirrored session immediately.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncio

import pytest

import chief_booking_actions as cba

BIZ = {"id": "biz1", "name": "Test Co"}
MODULE = {"id": "mod1", "archetype_params": {}}


# ─── pure helpers ─────────────────────────────────────────────────────

def test_normalize_iso_accepts_the_shapes_practitioners_say():
    assert cba._normalize_iso("2026-08-04") == "2026-08-04T09:00:00Z"
    assert cba._normalize_iso("2026-08-04T14:00") == "2026-08-04T14:00:00Z"
    assert cba._normalize_iso("2026-08-04T14:00:00Z") == "2026-08-04T14:00:00Z"
    assert cba._normalize_iso("2026-08-04T14:00:00+00:00") == "2026-08-04T14:00:00+00:00"
    assert cba._normalize_iso("") is None
    assert cba._normalize_iso(None) is None


def test_every_failure_carries_result_and_label():
    """The frontend action card calls .toLowerCase() on both. A handler that
    omits either blanks the whole app — this is the crash class from
    feedback_chief_action_shape."""
    out = cba._fail("create_booking", "nope")
    assert out["result"] and out["label"]
    assert out["type"] == "create_booking"


# ─── create_booking ───────────────────────────────────────────────────

def _patch_common(monkeypatch, *, slot_free=True, created=None):
    import booking_widget_router as bwr
    monkeypatch.setattr(bwr, "_bookings_module", lambda b: MODULE)
    monkeypatch.setattr(bwr, "_check_slot_available",
                        lambda b, when, dur: slot_free)
    monkeypatch.setattr(bwr, "_maybe_denormalize_offering",
                        lambda b, m, oid, qp, data: {**data,
                                                     "duration_min_at_booking": 60})
    calls = []

    def _create(business_id, module_id, data, created_by="booking_widget"):
        calls.append({"business_id": business_id, "module_id": module_id,
                      "data": data, "created_by": created_by})
        return created if created is not None else {"id": "bk1", "data": data}

    monkeypatch.setattr(bwr, "_create_appointment", _create)
    return calls


def test_create_booking_happy_path(monkeypatch):
    calls = _patch_common(monkeypatch)
    monkeypatch.setattr(cba, "_resolve_offering",
                        lambda b, a: {"offering": {"id": "off1", "name": "Color + Cut",
                                                   "duration_min": 60, "is_active": True}})
    monkeypatch.setattr(cba, "_resolve_contact",
                        lambda b, a: {"contact": {"id": "c1", "name": "Maria",
                                                  "email": "m@x.com"}})

    out = cba._create_booking_sync(BIZ, {
        "contact_id": "c1", "offering_id": "off1",
        "appointment_at": "2026-08-04T14:00:00Z",
    })

    assert out["type"] == "create_booking"
    assert out["result"] and out["label"]
    assert out["booking_id"] == "bk1"
    # Provenance: a Chief booking is distinguishable from a widget booking.
    assert calls[0]["created_by"] == "chief_of_staff"
    # The time is written INTO data — appointment_at is DB-maintained from it.
    assert calls[0]["data"]["appointment_at"] == "2026-08-04T14:00:00Z"
    assert calls[0]["data"]["contact_id"] == "c1"


def test_create_booking_refuses_to_double_book(monkeypatch):
    """The load-bearing guard. Chief must never book over an existing client."""
    calls = _patch_common(monkeypatch, slot_free=False)
    monkeypatch.setattr(cba, "_resolve_offering",
                        lambda b, a: {"offering": {"id": "off1", "name": "Cut",
                                                   "duration_min": 60, "is_active": True}})
    monkeypatch.setattr(cba, "_resolve_contact", lambda b, a: {"contact": None})
    monkeypatch.setattr(cba, "_suggest_slots", lambda b, o, w: ["Aug 4, 3:00 PM"])

    out = cba._create_booking_sync(BIZ, {
        "customer_name": "Walk In", "offering_id": "off1",
        "appointment_at": "2026-08-04T14:00:00Z",
    })

    assert not calls, "must not write an entry when the slot is taken"
    assert "already booked" in out["result"]
    # The alternative is offered so the practitioner can pick immediately.
    assert "Aug 4, 3:00 PM" in out["result"]


def test_create_booking_needs_a_time(monkeypatch):
    _patch_common(monkeypatch)
    out = cba._create_booking_sync(BIZ, {"customer_name": "X", "offering_id": "off1"})
    assert "date and time" in out["result"].lower()


def test_create_booking_needs_someone_to_book(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(cba, "_resolve_offering",
                        lambda b, a: {"offering": {"id": "off1", "name": "Cut",
                                                   "duration_min": 60, "is_active": True}})
    monkeypatch.setattr(cba, "_resolve_contact", lambda b, a: {"contact": None})
    out = cba._create_booking_sync(BIZ, {"offering_id": "off1",
                                         "appointment_at": "2026-08-04T14:00:00Z"})
    assert "who is this booking for" in out["result"].lower()


def test_create_booking_without_a_bookings_module_explains_itself(monkeypatch):
    import booking_widget_router as bwr
    monkeypatch.setattr(bwr, "_bookings_module", lambda b: None)
    out = cba._create_booking_sync(BIZ, {"customer_name": "X",
                                         "appointment_at": "2026-08-04T14:00:00Z"})
    assert "booking calendar" in out["result"].lower()
    assert out["label"]


def test_create_booking_rejects_an_inactive_offering(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(cba, "_resolve_offering",
                        lambda b, a: {"offering": {"id": "off1", "name": "Retired Service",
                                                   "duration_min": 60, "is_active": False}})
    out = cba._create_booking_sync(BIZ, {"customer_name": "X", "offering_id": "off1",
                                         "appointment_at": "2026-08-04T14:00:00Z"})
    assert "isn't active" in out["result"]


# ─── resolution: ask, don't guess ─────────────────────────────────────

def test_ambiguous_offering_asks_instead_of_guessing(monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [
        {"id": "o1", "name": "Cut — Short", "duration_min": 30, "is_active": True},
        {"id": "o2", "name": "Cut — Long", "duration_min": 60, "is_active": True},
    ])
    out = cba._resolve_offering("biz1", {"offering_name": "Cut"})
    assert "error" in out and "Multiple offerings" in out["error"]


def test_single_active_offering_needs_no_naming(monkeypatch):
    """A solo practitioner with one service shouldn't have to name it."""
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [
        {"id": "o1", "name": "The Only Thing", "duration_min": 60, "is_active": True},
    ])
    out = cba._resolve_offering("biz1", {})
    assert out.get("offering", {}).get("id") == "o1"


def test_ambiguous_contact_asks_instead_of_guessing(monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [
        {"id": "c1", "name": "Maria Lopez"}, {"id": "c2", "name": "Maria Chen"},
    ])
    out = cba._resolve_contact("biz1", {"contact_name": "Maria"})
    assert "error" in out and "Multiple contacts" in out["error"]


def test_unknown_contact_name_is_not_fatal(monkeypatch):
    """A walk-in with just a name is a legitimate booking."""
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [])
    out = cba._resolve_contact("biz1", {"contact_name": "Brand New"})
    assert out == {"contact": None}


# ─── reschedule_booking ───────────────────────────────────────────────

def test_reschedule_writes_time_into_data_not_the_column(monkeypatch):
    import booking_widget_router as bwr
    import sb_clients

    monkeypatch.setattr(bwr, "_check_slot_available", lambda b, w, d: True)
    monkeypatch.setattr(bwr, "_mirror_booking_session", lambda b, e: None)
    monkeypatch.setattr(cba, "_find_booking", lambda b, a: {"booking": {
        "id": "bk1", "status": "active", "module_id": "mod1",
        "data": {"appointment_at": "2026-08-04T14:00:00Z", "customer_name": "Maria",
                 "duration_min_at_booking": 60},
    }})
    patches = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: patches.append((p, b)) or [{"id": "bk1"}])
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"id": "bk1", "data": {}}])

    out = cba._reschedule_booking_sync(BIZ, {
        "booking_id": "bk1", "new_appointment_at": "2026-08-06T16:00:00Z"})

    assert out["result"] and out["label"] == "Maria"
    entry_patch = next(b for p, b in patches if "module_entries" in p)
    # The write goes to the jsonb; the generated column follows. Patching the
    # top-level column directly would be rejected by Postgres.
    assert entry_patch["data"]["appointment_at"] == "2026-08-06T16:00:00Z"
    assert set(entry_patch.keys()) == {"data"}


def test_reschedule_reports_failure_when_nothing_matched(monkeypatch):
    """PostgREST returns [] when the filter matches no rows — a stale id, or a
    booking owned by another business. That is NOT a successful move."""
    import booking_widget_router as bwr
    import sb_clients
    monkeypatch.setattr(bwr, "_check_slot_available", lambda b, w, d: True)
    monkeypatch.setattr(cba, "_find_booking", lambda b, a: {"booking": {
        "id": "bk1", "status": "active", "data": {"customer_name": "Maria"}}})
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: [])

    out = cba._reschedule_booking_sync(BIZ, {
        "booking_id": "bk1", "new_appointment_at": "2026-08-06T16:00:00Z"})
    assert "couldn't move" in out["result"]


def test_cancel_reports_failure_when_nothing_matched(monkeypatch):
    import sb_clients
    monkeypatch.setattr(cba, "_find_booking", lambda b, a: {"booking": {
        "id": "bk1", "status": "active", "data": {}}})
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: [])

    out = cba._cancel_booking_sync(BIZ, {"booking_id": "bk1"})
    assert "couldn't cancel" in out["result"]


def test_reschedule_refuses_a_taken_slot(monkeypatch):
    import booking_widget_router as bwr
    import sb_clients
    monkeypatch.setattr(bwr, "_check_slot_available", lambda b, w, d: False)
    monkeypatch.setattr(cba, "_find_booking", lambda b, a: {"booking": {
        "id": "bk1", "status": "active", "data": {"customer_name": "Maria"}}})
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: pytest.fail("must not write when the slot is taken"))

    out = cba._reschedule_booking_sync(BIZ, {
        "booking_id": "bk1", "new_appointment_at": "2026-08-06T16:00:00Z"})
    assert "already booked" in out["result"]


def test_reschedule_needs_a_new_time():
    out = cba._reschedule_booking_sync(BIZ, {"booking_id": "bk1"})
    assert "new date and time" in out["result"].lower()


# ─── cancel_booking ───────────────────────────────────────────────────

def test_cancel_sets_status_and_frees_the_session(monkeypatch):
    import sb_clients
    monkeypatch.setattr(cba, "_find_booking", lambda b, a: {"booking": {
        "id": "bk1", "status": "active",
        "data": {"appointment_at": "2026-08-04T14:00:00Z", "customer_name": "Maria"},
    }})
    patches = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: patches.append((p, b)) or [{"id": "bk1"}])

    out = cba._cancel_booking_sync(BIZ, {"booking_id": "bk1", "reason": "travelling"})

    assert out["result"] and out["label"] == "Maria"
    entry_patch = next(b for p, b in patches if "module_entries" in p)
    assert entry_patch["status"] == "cancelled"
    assert entry_patch["data"]["cancellation_reason"] == "travelling"
    # The mirrored session is cancelled in the same breath — the sync tick
    # backstops it, but the practitioner is looking at the calendar now.
    assert any("sessions" in p and b.get("status") == "cancelled" for p, b in patches)


def test_cancel_is_idempotent(monkeypatch):
    import sb_clients
    monkeypatch.setattr(cba, "_find_booking", lambda b, a: {"booking": {
        "id": "bk1", "status": "cancelled", "data": {}}})
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: pytest.fail("must not re-cancel"))
    out = cba._cancel_booking_sync(BIZ, {"booking_id": "bk1"})
    assert "already cancelled" in out["result"]


# ─── registry wiring ──────────────────────────────────────────────────

def test_verbs_are_registered_and_async():
    import inspect

    import chief_of_staff as cos
    for verb in ("create_booking", "reschedule_booking", "cancel_booking"):
        assert verb in cos.ACTION_HANDLERS, f"{verb} not registered"
        assert inspect.iscoroutinefunction(cos.ACTION_HANDLERS[verb])


def test_verbs_are_documented_in_the_prompt():
    """A handler Chief has never been told about is dead code."""
    import chief_of_staff as cos

    src = pathlib.Path(cos.__file__).read_text(encoding="utf-8")
    for verb in ("create_booking", "reschedule_booking", "cancel_booking"):
        assert f'"type":"{verb}"' in src, f"{verb} missing from the action catalog"


def test_async_wrappers_return_the_sync_result(monkeypatch):
    monkeypatch.setattr(cba, "_cancel_booking_sync",
                        lambda b, a: {"type": "cancel_booking", "result": "ok",
                                      "label": "X", "nav": None})
    out = asyncio.run(cba.handle_cancel_booking(None, BIZ, {"booking_id": "bk1"}))
    assert out["result"] == "ok"
