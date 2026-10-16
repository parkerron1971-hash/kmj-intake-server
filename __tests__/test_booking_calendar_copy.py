"""A booking's calendar copy follows the booking.

Every booking has one calendar copy: a `sessions` row whose notes carry
[booking:{id}]. The calendar, Chief's upcoming-sessions context and the SMS
reminder sweep all read sessions, not bookings, so a booking without a live
copy is gone from the calendar and is never reminded.

The bug (live on main until 2026-10-16): Chief's reschedule_booking
cancelled the old copy and asked _mirror_booking_session for a new one. The
mirror's "already mirrored?" check counted the copy it had just cancelled,
so it wrote nothing. The moved booking was left with no live copy, and the
10-minute sync tick could never put one back, because it asks the same
mirror.

These tests run the real booking helpers against a small in-memory
PostgREST (the filters these paths use: eq, neq, like, order, limit),
including the database trigger that keeps module_entries.appointment_at
in step with data.
"""
from __future__ import annotations

import pathlib
import re
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import booking_widget_router as bwr  # noqa: E402
import chief_booking_actions as cba  # noqa: E402
import sb_clients  # noqa: E402

BIZ = {"id": "biz1", "name": "Fade Lab"}
OLD = "2026-11-04T14:00:00Z"
NEW = "2026-11-06T16:00:00Z"
CLIENT = "Maria Lopez"


# ─── a small PostgREST ────────────────────────────────────────────────

class FakeDB:
    def __init__(self) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {
            "module_entries": [], "sessions": []}
        self.fail: set = set()       # {("POST", "sessions"), ...} answer None
        self.calls: List[tuple] = []
        self._next = 0
        self.before_insert = None    # hook(table, row) run before a POST lands

    def new_id(self) -> str:
        self._next += 1
        return f"s{self._next:03d}"

    # parsing ------------------------------------------------------------
    @staticmethod
    def _split(path: str):
        base, _, query = path.partition("?")
        table = base.strip("/")
        filters, order, limit = [], [], None
        for part in [p for p in query.split("&") if p]:
            key, _, value = part.partition("=")
            if key == "select" or key == "offset":
                continue
            if key == "order":
                order = [o.split(".") for o in value.split(",")]
                continue
            if key == "limit":
                limit = int(value)
                continue
            op, _, arg = value.partition(".")
            filters.append((key, op, arg))
        return table, filters, order, limit

    @staticmethod
    def _match(row: Dict[str, Any], filters) -> bool:
        for key, op, arg in filters:
            have = row.get(key)
            if op == "eq" and str(have) != arg:
                return False
            if op == "neq" and str(have) == arg:
                return False
            if op == "like":
                rx = "^" + re.escape(arg).replace(r"\*", ".*") + "$"
                if not re.match(rx, str(have or ""), re.S):
                    return False
            if op not in ("eq", "neq", "like"):
                raise AssertionError(f"FakeDB: unsupported operator {op}")
        return True

    def _rows(self, path: str):
        table, filters, order, limit = self._split(path)
        rows = [r for r in self.tables.setdefault(table, []) if self._match(r, filters)]
        for col, *direction in reversed(order):
            rows.sort(key=lambda r: str(r.get(col) or ""),
                      reverse=bool(direction and direction[0] == "desc"))
        return table, (rows[:limit] if limit else rows)

    # the sb_clients surface ----------------------------------------------
    def get(self, path: str, **_k) -> Optional[List[Dict[str, Any]]]:
        table, rows = self._rows(path)
        self.calls.append(("GET", table, path))
        if ("GET", table) in self.fail:
            return None
        return [dict(r) for r in rows]

    def patch(self, path: str, body: Dict[str, Any], **_k):
        table, rows = self._rows(path)
        self.calls.append(("PATCH", table, path, body))
        if ("PATCH", table) in self.fail:
            return None
        for r in rows:
            r.update(body)
            self._trigger(table, r)
        return [dict(r) for r in rows]

    def post(self, path: str, body: Dict[str, Any], *_a, **_k):
        table = path.strip("/").partition("?")[0]
        self.calls.append(("POST", table, body))
        if ("POST", table) in self.fail:
            return None
        row = {"id": self.new_id(), **body}
        if self.before_insert:
            hook, self.before_insert = self.before_insert, None
            hook(table, row)
        self.tables.setdefault(table, []).append(row)
        self._trigger(table, row)
        return [dict(row)]

    @staticmethod
    def _trigger(table: str, row: Dict[str, Any]) -> None:
        # booking_columns_from_data (APPLY-2026-10-08): the column follows data.
        if table == "module_entries":
            t = (row.get("data") or {}).get("appointment_at")
            if t:
                row["appointment_at"] = t

    # reading the result ---------------------------------------------------
    def copies(self, booking_id: str = "bk1", status: Optional[str] = None):
        marker = f"[booking:{booking_id}]"
        return [s for s in self.tables["sessions"]
                if marker in str(s.get("notes") or "")
                and (status is None or s.get("status") == status)]


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    # The double-book guard has its own suites; here the time is free.
    monkeypatch.setattr(bwr, "_check_slot_available", lambda *a, **k: True)
    monkeypatch.setattr(cba, "_outside_busy_at", lambda *a, **k: False)
    return fake


def _book(db: FakeDB, when: str = OLD, booking_id: str = "bk1") -> Dict[str, Any]:
    """A booking made the normal way: the row, then its mirrored copy."""
    entry = {"id": booking_id, "business_id": "biz1", "module_id": "mod1",
             "status": "active",
             "data": {"appointment_at": when, "customer_name": CLIENT,
                      "offering_name": "Skin Fade", "contact_id": "c1",
                      "duration_min_at_booking": 45}}
    db.tables["module_entries"].append(entry)
    FakeDB._trigger("module_entries", entry)
    bwr._mirror_booking_session("biz1", dict(entry))
    assert len(db.copies(booking_id, "scheduled")) == 1
    return entry


def _reschedule(to: str = NEW, booking_id: str = "bk1") -> Dict[str, Any]:
    return cba._reschedule_booking_sync(
        BIZ, {"booking_id": booking_id, "new_appointment_at": to})


def _live_times(db: FakeDB, booking_id: str = "bk1") -> List[str]:
    return [s["scheduled_for"] for s in db.copies(booking_id, "scheduled")]


# ─── the bug: a Chief reschedule loses the copy ───────────────────────

def test_chief_reschedule_leaves_exactly_one_copy_at_the_new_time(db):
    _book(db)
    out = _reschedule()
    assert out["result"].startswith("moved to")
    assert db.tables["module_entries"][0]["data"]["appointment_at"] == NEW
    assert _live_times(db) == [NEW]


def test_a_retried_reschedule_makes_no_second_copy(db):
    _book(db)
    _reschedule()
    _reschedule()
    assert _live_times(db) == [NEW]


def test_the_sync_tick_gives_a_moved_booking_its_copy_back(db):
    """Bookings the bug already hit: active, moved, and holding only the
    cancelled copy at the old time. The tick's mirror puts the copy back."""
    entry = _book(db)
    db.copies()[0]["status"] = "cancelled"
    entry["data"]["appointment_at"] = NEW
    FakeDB._trigger("module_entries", entry)

    bwr._mirror_booking_session("biz1", dict(entry))
    assert _live_times(db) == [NEW]


def test_a_failed_read_never_writes_a_copy(db):
    """A failed read is not "no copy": writing one then is how duplicates
    start."""
    entry = _book(db)
    db.fail.add(("GET", "sessions"))
    before = len(db.tables["sessions"])
    bwr._mirror_booking_session("biz1", dict(entry))
    assert len(db.tables["sessions"]) == before


def test_a_cancelled_copy_at_the_bookings_own_time_stays_cancelled(db):
    """Someone cancelled the copy itself. The mirror doesn't put it back."""
    entry = _book(db)
    db.copies()[0]["status"] = "cancelled"
    bwr._mirror_booking_session("biz1", dict(entry))
    assert _live_times(db) == []


# ─── the move: one copy, every time ───────────────────────────────────

def test_moving_again_moves_the_copy_again(db):
    _book(db)
    _reschedule(NEW)
    _reschedule("2026-11-09T10:00:00Z")
    assert _live_times(db) == ["2026-11-09T10:00:00Z"]


def test_moving_back_to_the_old_time(db):
    _book(db)
    _reschedule(NEW)
    _reschedule(OLD)
    assert _live_times(db) == [OLD]


def test_the_same_moment_written_another_way_is_not_a_move(db):
    """A session's time comes back as +00:00; the booking's is often Z."""
    _book(db)
    db.copies()[0]["scheduled_for"] = "2026-11-06T16:00:00+00:00"
    db.tables["module_entries"][0]["data"]["appointment_at"] = NEW
    before = len(db.tables["sessions"])
    assert bwr.sync_booking_session("biz1", db.tables["module_entries"][0])
    assert len(db.tables["sessions"]) == before


def test_a_copy_whose_time_cant_be_read_is_never_taken_for_the_new_time(db):
    _book(db)
    db.copies()[0]["scheduled_for"] = "sometime soon"
    _reschedule()
    assert _live_times(db) == [NEW]


def test_the_mirror_writes_nothing_on_a_time_it_cant_read(db):
    entry = _book(db)
    db.copies()[0].update(status="cancelled", scheduled_for="sometime soon")
    bwr._mirror_booking_session("biz1", dict(entry))
    assert _live_times(db) == []


def test_the_new_copy_keeps_the_practitioners_notes(db):
    _book(db)
    db.copies()[0]["notes"] = "Wants a skin fade, no beard. [booking:bk1]"
    _reschedule()
    (live,) = db.copies(status="scheduled")
    assert live["notes"] == "Wants a skin fade, no beard. [booking:bk1]"
    assert live["duration_minutes"] == 45


def test_a_moved_booking_gets_a_new_copy_so_it_is_reminded_again(db):
    """Reminders are de-duplicated per session id. Moving the old row in
    place would leave a client reminded for the old time and never for the
    new one."""
    _book(db)
    old_id = db.copies()[0]["id"]
    _reschedule()
    (live,) = db.copies(status="scheduled")
    assert live["id"] != old_id


def test_completed_and_no_show_copies_are_history(db):
    _book(db)
    db.copies()[0]["status"] = "no_show"
    _reschedule()
    assert [s["status"] for s in db.copies()] == ["no_show", "scheduled"]
    assert _live_times(db) == [NEW]


def test_old_duplicate_copies_collapse_to_one(db):
    entry = _book(db)
    db.tables["sessions"].append({**db.copies()[0], "id": db.new_id()})
    assert len(db.copies(status="scheduled")) == 2
    _reschedule()
    assert _live_times(db) == [NEW]
    assert entry["data"]["appointment_at"] == NEW


def test_two_moves_at_once_still_leave_one_copy(db):
    """Two runs that both find no copy at the new time both write one; each
    re-reads afterwards and keeps the same one (the lowest id)."""
    entry = _book(db)
    moved = {**entry, "data": {**entry["data"], "appointment_at": NEW}}

    def other_run_lands_first(table, row):
        if table == "sessions":
            assert bwr.sync_booking_session("biz1", dict(moved))

    db.before_insert = other_run_lands_first
    assert bwr.sync_booking_session("biz1", dict(moved))
    assert _live_times(db) == [NEW]


# ─── when the calendar can't be written: said, logged, never lost ─────

def _assert_no_names(capsys, caplog):
    printed = capsys.readouterr().out
    assert "calendar copy not updated" in printed
    for text in (printed, caplog.text):
        assert "Maria" not in text and "Lopez" not in text


def test_a_failed_calendar_write_is_said_and_logged_without_names(db, capsys, caplog):
    caplog.set_level("DEBUG")
    _book(db)
    db.fail.add(("POST", "sessions"))
    out = _reschedule()

    # The booking moved, and Chief says the calendar didn't follow.
    assert db.tables["module_entries"][0]["data"]["appointment_at"] == NEW
    assert not out.get("failed")
    assert out["calendar_updated"] is False
    assert "couldn't move it on your calendar" in out["result"]
    # The old copy is left live rather than none at all.
    assert _live_times(db) == [OLD]
    _assert_no_names(capsys, caplog)


def test_a_failed_calendar_read_writes_nothing_and_is_said(db, capsys, caplog):
    caplog.set_level("DEBUG")
    _book(db)
    db.fail.add(("GET", "sessions"))
    posts = len([c for c in db.calls if c[0] == "POST"])
    out = _reschedule()
    assert out["calendar_updated"] is False
    assert "couldn't move it on your calendar" in out["result"]
    assert len([c for c in db.calls if c[0] == "POST"]) == posts
    _assert_no_names(capsys, caplog)


def test_asking_again_after_a_failure_fixes_the_calendar(db):
    _book(db)
    db.fail.add(("POST", "sessions"))
    _reschedule()
    db.fail.clear()
    out = _reschedule()
    assert out["calendar_updated"] is True
    assert _live_times(db) == [NEW]


def test_a_failed_action_does_not_log_the_clients_name(db, monkeypatch, caplog):
    caplog.set_level("DEBUG")
    monkeypatch.setattr(cba, "_bookings_module_id", lambda b: "mod1")
    out = cba._reschedule_booking_sync(
        BIZ, {"contact_name": "Nobody Here", "new_appointment_at": NEW})
    assert out.get("failed") and "Nobody Here" in out["result"]
    assert "Nobody" not in caplog.text


# ─── cancel_booking ───────────────────────────────────────────────────

def test_cancel_takes_the_copy_off_the_calendar(db):
    _book(db)
    out = cba._cancel_booking_sync(BIZ, {"booking_id": "bk1"})
    assert out["calendar_updated"] is True
    assert db.tables["module_entries"][0]["status"] == "cancelled"
    assert _live_times(db) == []


def test_cancel_says_when_the_copy_is_still_on_the_calendar(db, capsys, caplog):
    caplog.set_level("DEBUG")
    _book(db)
    db.fail.add(("PATCH", "sessions"))
    out = cba._cancel_booking_sync(BIZ, {"booking_id": "bk1"})
    assert db.tables["module_entries"][0]["status"] == "cancelled"
    assert not out.get("failed")
    assert out["calendar_updated"] is False
    assert "couldn't take it off your calendar" in out["result"]
    _assert_no_names(capsys, caplog)


# ─── update_session on a booking's copy ───────────────────────────────

def _edit_session(session_id: str, patch: Dict[str, Any]):
    return cba._session_edit_sync(BIZ, session_id, patch)


def test_moving_a_bookings_copy_moves_the_booking(db):
    _book(db)
    copy_id = db.copies()[0]["id"]
    out = _edit_session(copy_id, {"scheduled_for": NEW,
                                  "notes": "Running late. [booking:bk1]"})
    assert out["type"] == "update_session" and out["result"].startswith("moved to")
    assert db.tables["module_entries"][0]["data"]["appointment_at"] == NEW
    (live,) = db.copies(status="scheduled")
    assert live["scheduled_for"] == NEW
    assert live["notes"] == "Running late. [booking:bk1]"
    assert out["session_id"] == live["id"]


def test_moving_a_copy_onto_a_taken_time_is_refused(db, monkeypatch):
    _book(db)
    monkeypatch.setattr(bwr, "_check_slot_available", lambda *a, **k: False)
    out = _edit_session(db.copies()[0]["id"], {"scheduled_for": NEW})
    assert out["failed"] and "already booked" in out["result"]
    assert db.tables["module_entries"][0]["data"]["appointment_at"] == OLD
    assert _live_times(db) == [OLD]


def test_cancelling_a_bookings_copy_cancels_the_booking(db):
    _book(db)
    out = _edit_session(db.copies()[0]["id"], {"status": "cancelled"})
    assert out["type"] == "update_session"
    assert db.tables["module_entries"][0]["status"] == "cancelled"
    assert _live_times(db) == []


def test_other_session_edits_are_left_to_update_session(db):
    _book(db)
    copy_id = db.copies()[0]["id"]
    assert _edit_session(copy_id, {"status": "completed"}) is None
    db.tables["sessions"].append({"id": "plain", "business_id": "biz1",
                                  "status": "scheduled", "notes": "Coaching call"})
    assert _edit_session("plain", {"scheduled_for": NEW}) is None


def test_a_copy_whose_booking_is_cancelled_or_gone_is_edited_on_its_own(db):
    """No active booking behind it: update_session edits the copy itself, as
    it always did (cancelling an orphaned copy must still work)."""
    _book(db)
    copy_id = db.copies()[0]["id"]
    db.tables["module_entries"][0]["status"] = "cancelled"
    assert _edit_session(copy_id, {"status": "cancelled"}) is None
    db.tables["module_entries"].clear()
    assert _edit_session(copy_id, {"scheduled_for": NEW}) is None


def test_a_booking_that_cant_be_read_is_not_moved(db):
    _book(db)
    copy_id = db.copies()[0]["id"]
    db.fail.add(("GET", "module_entries"))
    out = _edit_session(copy_id, {"scheduled_for": NEW})
    assert out["failed"]
    assert _live_times(db) == [OLD]


def test_a_session_that_cant_be_read_is_not_moved(db):
    _book(db)
    copy_id = db.copies()[0]["id"]
    db.fail.add(("GET", "sessions"))
    out = _edit_session(copy_id, {"scheduled_for": NEW})
    assert out["failed"]
    assert db.tables["module_entries"][0]["data"]["appointment_at"] == OLD


# ─── update_module_entry / delete_module_entry on a booking ───────────

@pytest.fixture
def chief_sb(db, monkeypatch):
    """chief_of_staff's _sb, on the same fake."""
    import chief_of_staff as cos

    async def _sb(client, method, path, body=None):
        if method == "GET":
            return db.get(path)
        if method == "PATCH":
            return db.patch(path, body)
        return db.post(path, body)

    monkeypatch.setattr(cos, "_sb", _sb)
    return cos


def _session_writes(db: FakeDB) -> int:
    return len([c for c in db.calls if c[0] in ("POST", "PATCH") and c[1] == "sessions"])


def test_editing_a_bookings_time_moves_its_copy(chief_sb, db):
    import asyncio
    _book(db)
    out = asyncio.run(chief_sb.handle_update_module_entry(
        None, BIZ, {"entry_id": "bk1", "data": {"appointment_at": NEW}}))
    assert out["result"] == "updated"
    assert _live_times(db) == [NEW]


def test_editing_another_field_leaves_the_calendar_alone(chief_sb, db):
    import asyncio
    _book(db)
    writes = _session_writes(db)
    asyncio.run(chief_sb.handle_update_module_entry(
        None, BIZ, {"entry_id": "bk1", "data": {"notes": "prefers mornings"}}))
    assert _session_writes(db) == writes
    assert _live_times(db) == [OLD]


def test_editing_a_row_that_is_not_a_booking_writes_no_copy(chief_sb, db):
    import asyncio
    db.tables["module_entries"].append({"id": "ev1", "business_id": "biz1",
                                        "module_id": "events", "status": "active",
                                        "data": {"starts_at": OLD, "title": "Open house"}})
    out = asyncio.run(chief_sb.handle_update_module_entry(
        None, BIZ, {"entry_id": "ev1", "data": {"starts_at": NEW}}))
    assert out["result"] == "updated"
    assert db.tables["sessions"] == []


def test_removing_a_booking_takes_its_copy_off_the_calendar(chief_sb, db):
    import asyncio
    _book(db)
    out = asyncio.run(chief_sb.handle_delete_module_entry(None, BIZ, {"entry_id": "bk1"}))
    assert out["result"] == "deleted"
    assert _live_times(db) == []


def test_removing_a_booking_says_when_the_copy_stays(chief_sb, db, capsys, caplog):
    import asyncio
    caplog.set_level("DEBUG")
    _book(db)
    db.fail.add(("PATCH", "sessions"))
    out = asyncio.run(chief_sb.handle_delete_module_entry(None, BIZ, {"entry_id": "bk1"}))
    assert out["result"].startswith("deleted")
    assert "couldn't take it off your calendar" in out["result"]
    _assert_no_names(capsys, caplog)


def test_chiefs_update_session_moves_a_booking_through_the_booking_path(chief_sb, db):
    import asyncio
    _book(db)
    out = asyncio.run(chief_sb.handle_update_session(
        None, BIZ, {"session_id": db.copies()[0]["id"], "scheduled_for": NEW}))
    assert out["type"] == "update_session" and out["result"].startswith("moved to")
    assert db.tables["module_entries"][0]["data"]["appointment_at"] == NEW
    assert _live_times(db) == [NEW]


def test_chiefs_update_session_still_moves_a_plain_session(chief_sb, db):
    import asyncio
    db.tables["sessions"].append({"id": "plain", "business_id": "biz1",
                                  "status": "scheduled", "scheduled_for": OLD,
                                  "notes": "Coaching call"})
    out = asyncio.run(chief_sb.handle_update_session(
        None, BIZ, {"session_id": "plain", "scheduled_for": NEW}))
    assert out["result"] == "updated"
    assert db.tables["sessions"][0]["scheduled_for"] == NEW


def test_removing_another_row_never_touches_the_calendar(chief_sb, db):
    import asyncio
    db.tables["module_entries"].append({"id": "t1", "business_id": "biz1",
                                        "module_id": "tasks", "status": "active",
                                        "data": {"title": "Order clippers"}})
    asyncio.run(chief_sb.handle_delete_module_entry(None, BIZ, {"entry_id": "t1"}))
    assert _session_writes(db) == 0
