"""The bookings reads see the bookings, and a failed read never says "free".

Found 2026-10-07 while building B11 (#1330). module_entries has the
columns appointment_at and duration_min_at_booking and NO duration_min.
Three reads asked for duration_min anyway (the widget's open times, the
double-book guard, GET /availability/{id}/slots), so PostgREST answered
400, sb_get_as_service returned None, and `or []` read that as "no
bookings": the widget offered taken times and the guard let a second
customer book them.

Under that, the production check found the appointment_at COLUMN empty
on every row: the widget, Chief and weekly series write the time and the
booked length into `data`. So the reads match the column OR data, and a
read that fails (or hits its row limit) refuses instead of guessing.

The fake below answers the way PostgREST does: an unknown column in the
select is a 400 (None), the time lives in data, and the projection of
`alias:data->>key` is text.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import availability_engine as ae
import booking_series as bs
import booking_widget_router as bwr
import chief_booking_actions as cba
import sb_clients

BIZ = "b1"
MODULE_ENTRY_COLUMNS = {
    "*", "id", "business_id", "module_id", "data", "status", "created_by",
    "created_at", "updated_at", "appointment_at", "duration_min_at_booking",
}


def _entry(start, minutes=60, *, id="e1", status="active", column=False, business_id=BIZ):
    """A booking stored the way production stores it: time and length in
    data, columns empty (column=True puts them in the columns instead)."""
    data = {"appointment_at": start, "customer_name": "Someone"}
    if minutes is not None:
        data["duration_min_at_booking"] = minutes
    row = {"id": id, "business_id": business_id, "status": status, "data": data,
           "appointment_at": None, "duration_min_at_booking": None}
    if column:
        row["appointment_at"], row["duration_min_at_booking"] = start, minutes
        row["data"] = {"customer_name": "Someone"}
    return row


class FakePostgrest:
    def __init__(self, entries=(), *, fail=False, settings=None):
        self.entries = list(entries)
        self.fail = fail
        self.settings = settings or {}
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if path.startswith("/module_entries"):
            if self.fail:
                return None                      # a 5xx / transport error
            params = dict(p.split("=", 1) for p in path.split("?", 1)[1].split("&") if "=" in p)
            cols = []
            for col in params.get("select", "*").split(","):
                alias, _, expr = col.rpartition(":")
                base, _, key = expr.partition("->>")
                if base not in MODULE_ENTRY_COLUMNS:
                    return None                  # PostgREST 400: no such column
                cols.append((alias or expr, base, key))
            rows = [e for e in self.entries
                    if params.get("business_id", f"eq.{e['business_id']}") == f"eq.{e['business_id']}"
                    and (params.get("status") != "eq.active" or e["status"] == "active")
                    and params.get("id") != f"neq.{e['id']}"]
            rows = rows[: int(params.get("limit", "1000"))]
            out = []
            for e in rows:
                if cols == [("*", "*", "")]:
                    out.append(dict(e))
                    continue
                r = {}
                for name, base, key in cols:
                    if key:
                        v = (e.get(base) or {}).get(key)
                        r[name] = None if v is None else str(v)
                    else:
                        r[name] = e.get(base)
                out.append(r)
            return out
        if path.startswith("/businesses"):
            return [{"id": BIZ, "owner_id": "o1", "settings": self.settings}]
        if path.startswith("/offerings"):
            return [{"id": "off-1", "duration_min": 60}]
        return []


@pytest.fixture
def no_outside_calendar(monkeypatch):
    import outside_calendar
    monkeypatch.setattr(outside_calendar, "busy_overlap", lambda *a, **k: False)
    monkeypatch.setattr(outside_calendar, "busy_blocks_for_dates", lambda *a, **k: [])


def _use(monkeypatch, fake):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    return fake


# ─── 1. No read asks module_entries for a column it does not have ─────

# agent_site.py had the same select and is fixed in its own PR (#1330);
# once that lands this skip can go.
_SKIP = {"agent_site.py"}


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "{}" for v in node.values)
    return None


def _bad_module_entries_selects(source: str):
    bad = []
    for node in ast.walk(ast.parse(source)):
        text = _literal(node)
        if not text or "/module_entries" not in text:
            continue
        m = re.search(r"select=([^&]*)", text)
        if not m:
            continue
        for col in m.group(1).split(","):
            if re.fullmatch(r"(\w+:)?duration_min", col.strip()):
                bad.append((node.lineno, m.group(1)))
    return bad


def test_the_scan_catches_the_old_select_and_passes_the_new_one():
    old = ('x = (f"/module_entries?business_id=eq.{b}"\n'
           '     f"&select=appointment_at,duration_min_at_booking,duration_min"\n'
           '     f"&limit=2000")\n')
    assert _bad_module_entries_selects(old)
    new = 'x = f"/module_entries?business_id=eq.{b}&select={ae.BOOKING_SELECT}"\n'
    assert not _bad_module_entries_selects(new)
    assert not _bad_module_entries_selects(
        'x = "/module_entries?select=appointment_at,duration_min_at_booking"')
    assert not _bad_module_entries_selects('x = "/offerings?select=id,duration_min"')


def test_no_module_entries_select_names_duration_min():
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {"__tests__", "node_modules"} or rel.parts[0].startswith("."):
            continue
        if str(rel) in _SKIP:
            continue
        try:
            source = path.read_text(encoding="utf-8-sig")
            hits = _bad_module_entries_selects(source)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        offenders += [f"{rel}:{line}: {sel}" for line, sel in hits]
    assert not offenders, ("module_entries has no duration_min column — use "
                           "availability_engine.BOOKING_SELECT:\n" + "\n".join(offenders))


def test_the_three_reads_use_the_shared_select():
    import inspect
    import availability_router as ar
    for fn in (bwr._read_bookings,):
        assert "BOOKING_SELECT" in inspect.getsource(fn)
    for fn in (bwr._slots_per_offering, bwr._check_slot_available, ar._bookings_in_window):
        assert "_read_bookings(" in inspect.getsource(fn), fn.__name__


def test_the_window_filter_matches_column_or_data_and_carries_no_plus():
    f = ae.booking_window_filter(date(2026, 10, 6), date(2026, 10, 9))
    assert f == ("or=(and(appointment_at.gte.2026-10-06,appointment_at.lt.2026-10-09),"
                 "and(data->>appointment_at.gte.2026-10-06,data->>appointment_at.lt.2026-10-09))")
    assert "+" not in f


# ─── 2. Booked rows: the time from data, the length from column / data / 60 ─

def test_booked_rows_reads_column_else_data_and_defaults_the_length():
    rows = ae.booked_rows([
        {"appointment_at": None, "duration_min_at_booking": None,
         "booked_at": "2026-10-08T14:00:00Z", "booked_min": "45"},
        {"appointment_at": "2026-10-08T16:00:00+00:00", "duration_min_at_booking": 30,
         "booked_at": None, "booked_min": None},
        {"appointment_at": None, "duration_min_at_booking": None,
         "booked_at": "2026-10-08", "booked_min": None},
        {"appointment_at": None, "booked_at": None},          # no time: skipped
        "junk",
    ])
    assert rows == [
        {"appointment_at": "2026-10-08T14:00:00Z", "duration_min_at_booking": 45},
        {"appointment_at": "2026-10-08T16:00:00+00:00", "duration_min_at_booking": 30},
        {"appointment_at": "2026-10-08", "duration_min_at_booking": ae.DEFAULT_BOOKED_MIN},
    ]


def test_a_rescheduled_time_in_data_wins_over_a_stale_column():
    rows = ae.booked_rows([{"appointment_at": "2026-10-08T09:00:00Z",
                            "booked_at": "2026-10-08T15:00:00Z",
                            "duration_min_at_booking": 60}])
    assert rows[0]["appointment_at"] == "2026-10-08T15:00:00Z"


# ─── 3. The double-book guard ────────────────────────────────────────

def test_guard_refuses_a_booking_stored_only_in_data(monkeypatch):
    """The production shape: the columns empty, the time in data."""
    _use(monkeypatch, FakePostgrest([_entry("2026-09-14T14:00:00Z", 60)]))
    assert bwr._check_slot_available(BIZ, "2026-09-14T14:30:00Z", 30) is False
    assert bwr._check_slot_available(BIZ, "2026-09-14T15:00:00Z", 30) is True


def test_guard_refuses_a_booking_stored_in_the_columns(monkeypatch):
    _use(monkeypatch, FakePostgrest([_entry("2026-09-14T14:00:00+00:00", 60, column=True)]))
    assert bwr._check_slot_available(BIZ, "2026-09-14T14:00:00Z", 60) is False


def test_guard_counts_a_booking_with_no_length_as_an_hour(monkeypatch):
    _use(monkeypatch, FakePostgrest([_entry("2026-09-14T14:00:00Z", None)]))
    assert bwr._check_slot_available(BIZ, "2026-09-14T14:45:00Z", 30) is False
    assert bwr._check_slot_available(BIZ, "2026-09-14T15:00:00Z", 30) is True


def test_guard_checks_a_request_with_no_length_instead_of_waving_it_through(monkeypatch):
    _use(monkeypatch, FakePostgrest([_entry("2026-09-14T14:00:00Z", 60)]))
    assert bwr._check_slot_available(BIZ, "2026-09-14T14:00:00Z", 0) is False


def test_guard_reads_a_naive_request_as_utc(monkeypatch):
    _use(monkeypatch, FakePostgrest([_entry("2026-09-14T14:00:00Z", 60)]))
    assert bwr._check_slot_available(BIZ, "2026-09-14T14:00:00", 60) is False


def test_guard_with_zero_bookings_still_allows(monkeypatch):
    fake = _use(monkeypatch, FakePostgrest([]))
    assert bwr._check_slot_available(BIZ, "2026-09-14T14:00:00Z", 60) is True
    read = [p for p in fake.paths if p.startswith("/module_entries")][0]
    assert "status=eq.active" in read and "+" not in read.split("?", 1)[1]


def test_guard_ignores_cancelled_bookings(monkeypatch):
    _use(monkeypatch, FakePostgrest([_entry("2026-09-14T14:00:00Z", 60, status="cancelled")]))
    assert bwr._check_slot_available(BIZ, "2026-09-14T14:00:00Z", 60) is True


def test_guard_on_a_failed_read_raises_instead_of_saying_free(monkeypatch):
    _use(monkeypatch, FakePostgrest(fail=True))
    with pytest.raises(bwr.SlotCheckFailed) as e:
        bwr._check_slot_available(BIZ, "2026-09-14T14:00:00Z", 60)
    assert e.value.status_code == 503
    assert e.value.detail == bwr.SLOT_CHECK_FAILED_MSG


def test_guard_at_the_row_limit_raises(monkeypatch):
    many = [_entry("2026-09-13T01:00:00Z", 5, id=f"e{i}") for i in range(bwr.BOOKING_READ_LIMIT)]
    _use(monkeypatch, FakePostgrest(many))
    with pytest.raises(bwr.SlotCheckFailed):
        bwr._check_slot_available(BIZ, "2026-09-14T14:00:00Z", 60)


def test_guard_leaves_out_the_booking_being_moved(monkeypatch):
    fake = _use(monkeypatch, FakePostgrest([_entry("2026-09-14T14:00:00Z", 60, id="bk1")]))
    assert bwr._check_slot_available(BIZ, "2026-09-14T14:30:00Z", 60, exclude_id="bk1") is True
    assert any("id=neq.bk1" in p for p in fake.paths)
    assert bwr._check_slot_available(BIZ, "2026-09-14T14:30:00Z", 60) is False


def test_the_public_guard_raises_on_a_failed_read_too(monkeypatch, no_outside_calendar):
    _use(monkeypatch, FakePostgrest(fail=True))
    with pytest.raises(bwr.SlotCheckFailed):
        bwr._check_public_slot_available(BIZ, "2026-09-14T14:00:00Z", 60)


# ─── 4. The widget's create paths ────────────────────────────────────

MODULE = {"id": "mod1", "archetype_params": {"primary_date_field": "appointment_at"},
          "schema": {"fields": []}}


@pytest.fixture
def widget(monkeypatch, no_outside_calendar):
    created = []
    monkeypatch.setattr(bwr, "_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(bwr, "_business_basics",
                        lambda b: {"id": b, "name": "Shop", "settings": {}})
    monkeypatch.setattr(bwr, "_bookings_module", lambda b: MODULE)
    monkeypatch.setattr(bwr, "_find_or_create_contact", lambda *a, **k: "c1")
    monkeypatch.setattr(bwr, "_find_or_create_customer", lambda *a, **k: "cust1")
    monkeypatch.setattr(bwr, "issue_customer_token", lambda *a, **k: "tok")
    monkeypatch.setattr(bwr, "_schedule_confirmation_sms", lambda *a, **k: None)
    monkeypatch.setattr(bwr, "_create_appointment",
                        lambda b, m, data, created_by="booking_widget":
                        created.append(data) or {"id": "bk-new", "data": data})
    import booking_confirmation_emails

    async def _no_email(**k):
        return None
    monkeypatch.setattr(booking_confirmation_emails, "send_confirmation_email", _no_email)
    app = FastAPI()
    app.include_router(bwr.router)
    from customer_token import CustomerContext, require_customer_token_dep
    app.dependency_overrides[require_customer_token_dep] = lambda: CustomerContext(
        business_id=BIZ, customer_id="cust1",
        customer_row={"contact_id": "c1", "name": "Ann", "email": "ann@example.com"})
    return TestClient(app), created


ANON = {"name": "Ann", "email": "ann@example.com",
        "data": {"appointment_at": "2027-03-01T14:00:00Z", "duration_min_at_booking": 60}}
KNOWN = {"data": {"appointment_at": "2027-03-01T14:00:00Z", "duration_min_at_booking": 60}}


@pytest.mark.parametrize("path,body", [
    (f"/widgets/booking/{BIZ}/book-anon", ANON),
    (f"/widgets/booking/{BIZ}/book", KNOWN),
])
def test_a_failed_read_refuses_the_booking_with_a_retryable_503(widget, monkeypatch, path, body):
    client, created = widget
    _use(monkeypatch, FakePostgrest(fail=True))
    r = client.post(path, json=body)
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == bwr.SLOT_CHECK_FAILED_MSG
    assert created == [], "nothing is booked on a guess"


@pytest.mark.parametrize("path,body", [
    (f"/widgets/booking/{BIZ}/book-anon", ANON),
    (f"/widgets/booking/{BIZ}/book", KNOWN),
])
def test_an_overlapping_booking_refuses_with_409(widget, monkeypatch, path, body):
    client, created = widget
    _use(monkeypatch, FakePostgrest([_entry("2027-03-01T14:30:00Z", 60)]))
    r = client.post(path, json=body)
    assert r.status_code == 409, r.text
    assert created == []


@pytest.mark.parametrize("path,body", [
    (f"/widgets/booking/{BIZ}/book-anon", ANON),
    (f"/widgets/booking/{BIZ}/book", KNOWN),
])
def test_zero_bookings_still_books(widget, monkeypatch, path, body):
    client, created = widget
    _use(monkeypatch, FakePostgrest([]))
    r = client.post(path, json=body)
    assert r.status_code == 200, r.text
    assert len(created) == 1


# ─── 5. Chief's booking verbs ────────────────────────────────────────

def _chief(monkeypatch, fake):
    created = []
    _use(monkeypatch, fake)
    monkeypatch.setattr(bwr, "_bookings_module", lambda b: MODULE)
    monkeypatch.setattr(bwr, "_maybe_denormalize_offering",
                        lambda b, m, oid, qp, data: {**data, "duration_min_at_booking": 60})
    monkeypatch.setattr(bwr, "_create_appointment",
                        lambda b, m, data, created_by="x": created.append(data) or {"id": "bk9"})
    monkeypatch.setattr(cba, "_resolve_offering", lambda b, a: {"offering": {
        "id": "off-1", "name": "Cut", "duration_min": 60, "is_active": True}})
    monkeypatch.setattr(cba, "_resolve_contact", lambda b, a: {"contact": {"id": "c1", "name": "Jane"}})
    return created


def test_chief_create_on_a_failed_read_books_nothing_and_says_so(monkeypatch, no_outside_calendar):
    created = _chief(monkeypatch, FakePostgrest(fail=True))
    out = cba._create_booking_sync({"id": BIZ}, {"appointment_at": "2027-03-01T14:00:00Z",
                                                 "contact_name": "Jane"})
    assert out["failed"] is True and out["result"] == cba._CALENDAR_UNREAD and out["label"]
    assert created == []


def test_chief_create_refuses_a_booking_stored_in_data(monkeypatch, no_outside_calendar):
    created = _chief(monkeypatch, FakePostgrest([_entry("2027-03-01T14:00:00Z", 60)]))
    monkeypatch.setattr(cba, "_suggest_slots", lambda *a, **k: [])
    out = cba._create_booking_sync({"id": BIZ}, {"appointment_at": "2027-03-01T14:30:00Z",
                                                 "contact_name": "Jane"})
    assert out["failed"] is True and "already booked" in out["result"]
    assert created == []


def _reschedule(monkeypatch, fake):
    patches = []
    _use(monkeypatch, fake)
    monkeypatch.setattr(bwr, "_mirror_booking_session", lambda *a, **k: None)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: patches.append((p, b)) or [{"id": "bk1"}])
    monkeypatch.setattr(cba, "_find_booking", lambda b, a: {"booking": {
        "id": "bk1", "status": "active",
        "data": {"appointment_at": "2027-03-01T14:00:00Z", "duration_min_at_booking": 60,
                 "customer_name": "Maria"}}})
    return patches


def test_chief_reschedule_on_a_failed_read_moves_nothing(monkeypatch, no_outside_calendar):
    patches = _reschedule(monkeypatch, FakePostgrest(fail=True))
    out = cba._reschedule_booking_sync({"id": BIZ}, {"booking_id": "bk1",
                                                     "new_appointment_at": "2027-03-01T14:30:00Z"})
    assert out["failed"] is True and out["result"] == cba._CALENDAR_UNREAD_MOVE
    assert patches == []


def test_chief_reschedule_by_half_an_hour_does_not_collide_with_itself(monkeypatch, no_outside_calendar):
    patches = _reschedule(monkeypatch, FakePostgrest([_entry("2027-03-01T14:00:00Z", 60, id="bk1")]))
    out = cba._reschedule_booking_sync({"id": BIZ}, {"booking_id": "bk1",
                                                     "new_appointment_at": "2027-03-01T14:30:00Z"})
    assert not out.get("failed"), out
    assert any("module_entries" in p for p, _ in patches)


def test_chief_reschedule_onto_someone_else_is_refused(monkeypatch, no_outside_calendar):
    patches = _reschedule(monkeypatch, FakePostgrest([
        _entry("2027-03-01T14:00:00Z", 60, id="bk1"),
        _entry("2027-03-01T15:00:00Z", 60, id="bk2")]))
    out = cba._reschedule_booking_sync({"id": BIZ}, {"booking_id": "bk1",
                                                     "new_appointment_at": "2027-03-01T15:30:00Z"})
    assert out["failed"] is True and "already booked" in out["result"]
    assert patches == []


# ─── 6. Weekly series ────────────────────────────────────────────────

def _series(monkeypatch, fake):
    created = []
    _use(monkeypatch, fake)
    monkeypatch.setattr(bwr, "_bookings_module", lambda b: MODULE)
    monkeypatch.setattr(bwr, "_maybe_denormalize_offering",
                        lambda b, m, oid, qp, data: {**data, "duration_min_at_booking": 60})
    monkeypatch.setattr(bwr, "_create_appointment",
                        lambda b, m, data, created_by="x":
                        created.append(data) or {"id": f"bk{len(created)}", "data": data})
    from availability import BusinessAvailability
    av = BusinessAvailability.from_settings_dict(None)
    monkeypatch.setattr(bs, "_business_availability", lambda b: (av, "UTC"))
    monkeypatch.setattr(bs, "_series_entries", lambda *a, **k: [])
    return created


def _book_three():
    from datetime import time
    return bs.create_series(BIZ, offering={"id": "off-1", "name": "Cut", "duration_min": 60},
                            contact=None, customer_name="Jane", weekday=0, at=time(14, 0),
                            tz_name="UTC", start_from=date(2027, 3, 1), count=3)


def test_series_on_a_failed_read_books_no_week_and_says_why(monkeypatch, no_outside_calendar):
    created = _series(monkeypatch, FakePostgrest(fail=True))
    res = _book_three()
    assert res["ok"] and created == []
    assert [s["reason"] for s in res["skipped"]] == [bs.UNCHECKED_REASON] * 3
    assert "0 booked, 3 skipped" in res["summary"]
    assert "couldn't be checked" in res["summary"]


def test_series_skips_only_the_week_that_is_taken(monkeypatch, no_outside_calendar):
    created = _series(monkeypatch, FakePostgrest([_entry("2027-03-08T14:00:00Z", 60)]))
    res = _book_three()
    assert len(created) == 2
    assert res["skipped"] == [{"date": res["skipped"][0]["date"], "reason": "conflict"}]
    assert "couldn't" not in res["summary"]


def test_series_with_an_empty_calendar_books_every_week(monkeypatch, no_outside_calendar):
    created = _series(monkeypatch, FakePostgrest([]))
    res = _book_three()
    assert len(created) == 3 and res["summary"] == "3 booked"


# ─── 7. The slot lists ───────────────────────────────────────────────

_HOURS = {"timezone": "UTC", "slot_granularity_min": 60,
          "weekly": {d: [{"start": "09:00", "end": "17:00"}]
                     for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}}


def _day_after_tomorrow():
    return date.today() + timedelta(days=2)


def _starts(slots):
    return {s["start_utc"][:16] for s in slots}


def test_widget_slots_leave_out_a_time_booked_in_data(monkeypatch, no_outside_calendar):
    d = _day_after_tomorrow().isoformat()
    business = {"id": BIZ, "owner_id": "o1", "settings": {"availability": _HOURS}}
    offerings = [{"id": "off-1", "duration_min": 60}]
    _use(monkeypatch, FakePostgrest([]))
    free = bwr._slots_per_offering(business, offerings)["off-1"]
    assert f"{d}T14:00" in _starts(free)
    _use(monkeypatch, FakePostgrest([_entry(f"{d}T14:00:00Z", 60)]))
    booked = bwr._slots_per_offering(business, offerings)["off-1"]
    assert f"{d}T14:00" not in _starts(booked)
    assert f"{d}T15:00" in _starts(booked)


def test_widget_config_on_a_failed_read_offers_no_times_and_says_so(monkeypatch, no_outside_calendar):
    business = {"id": BIZ, "owner_id": "o1", "name": "Shop", "settings": {"availability": _HOURS}}
    monkeypatch.setattr(bwr, "_offerings_for_widget_fields",
                        lambda b, f: [{"id": "off-1", "name": "Cut", "duration_min": 60}])
    _use(monkeypatch, FakePostgrest(fail=True))
    payload = bwr._config_payload(business, MODULE)
    assert payload["available_slots"] == {"off-1": []}
    assert payload["slots_unavailable"] is True
    assert payload["slots_message"] == bwr.SLOTS_UNAVAILABLE_MSG


def test_widget_config_on_a_good_read_carries_no_failure_keys(monkeypatch, no_outside_calendar):
    business = {"id": BIZ, "owner_id": "o1", "name": "Shop", "settings": {"availability": _HOURS}}
    monkeypatch.setattr(bwr, "_offerings_for_widget_fields",
                        lambda b, f: [{"id": "off-1", "name": "Cut", "duration_min": 60}])
    _use(monkeypatch, FakePostgrest([]))
    payload = bwr._config_payload(business, MODULE)
    assert payload["available_slots"]["off-1"]
    assert "slots_unavailable" not in payload and "slots_message" not in payload


def _slots_client(monkeypatch):
    import availability_router as ar
    monkeypatch.setattr(ar, "_rate_limit", lambda *a: None)
    monkeypatch.setattr(ar, "_outside_busy", lambda *a: [])
    app = FastAPI()
    app.include_router(ar.router)
    return TestClient(app)


def test_slots_endpoint_leaves_out_a_time_booked_in_data(monkeypatch):
    d = _day_after_tomorrow().isoformat()
    client = _slots_client(monkeypatch)
    _use(monkeypatch, FakePostgrest([_entry(f"{d}T14:00:00Z", 60),
                                     _entry(f"{d}T16:00:00Z", 60, id="e2", status="cancelled")],
                                    settings={"availability": _HOURS}))
    r = client.get(f"/availability/{BIZ}/slots", params={"offering_id": "off-1", "from": d, "to": d})
    assert r.status_code == 200, r.text
    starts = _starts(r.json()["slots"])
    assert f"{d}T14:00" not in starts
    assert f"{d}T16:00" in starts, "a cancelled booking holds nothing"


def test_slots_endpoint_on_a_failed_read_is_503_not_every_slot_open(monkeypatch):
    d = _day_after_tomorrow().isoformat()
    client = _slots_client(monkeypatch)
    fake = FakePostgrest(settings={"availability": _HOURS})

    def get(path):
        if path.startswith("/module_entries"):
            return None
        return fake.get(path)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    r = client.get(f"/availability/{BIZ}/slots", params={"offering_id": "off-1", "from": d, "to": d})
    assert r.status_code == 503
    assert r.json()["detail"] == bwr.SLOTS_UNAVAILABLE_MSG


def test_chief_suggestions_on_a_failed_read_suggest_nothing(monkeypatch):
    _use(monkeypatch, FakePostgrest(fail=True, settings={"availability": _HOURS}))
    monkeypatch.setattr("availability_router._outside_busy", lambda *a: [])
    assert cba._suggest_slots(BIZ, {"duration_min": 60},
                              f"{_day_after_tomorrow().isoformat()}T14:00:00Z") == []
