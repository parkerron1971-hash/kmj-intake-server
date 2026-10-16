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

# The real PATCH, kept before any test swaps it for the fake: the
# redaction tests send booking writes through sb_clients' own error handling.
_REAL_PATCH = sb_clients.sb_patch_as_service

BIZ = {"id": "biz1", "name": "Fade Lab"}
OLD = "2026-11-04T14:00:00Z"
NEW = "2026-11-06T16:00:00Z"
CLIENT = "Maria Lopez"

# Production's sessions_session_type_check (read 2026-10-16). 'booking' is
# not in it until APPLY-2026-10-16-booking-calendar-copies.sql.
SESSION_TYPES = {"coaching_session", "consultation", "pastoral_visit",
                 "mentorship", "discovery_call", "follow_up", "other"}
SESSION_STATUSES = {"scheduled", "completed", "cancelled", "no_show"}


def _instant(value: Any):
    from datetime import datetime, timezone
    try:
        d = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ─── a small PostgREST ────────────────────────────────────────────────

class FakeDB:
    def __init__(self) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {
            "module_entries": [], "sessions": [], "events": [],
            "custom_modules": [
                {"id": "mod1", "business_id": "biz1",
                 "archetype": "booking_calendar", "is_active": True},
                {"id": "events", "business_id": "biz1", "archetype": "events",
                 "is_active": True},
                {"id": "tasks", "business_id": "biz1", "archetype": "tasks",
                 "is_active": True}],
            "contacts": [{"id": "c1", "business_id": "biz1", "name": CLIENT,
                          "phone": "+13125550101"}],
            "businesses": [{"id": "biz1", "name": "Fade Lab", "settings": {}}],
        }
        # True: the APPLY file is in (booking copies allowed, the sync
        # function exists). False: production as it stood on 2026-10-16.
        self.applied = True
        self.fail: set = set()       # {("POST", "sessions"), ...} answer None
        self.calls: List[tuple] = []
        self._next = 0
        self._clock = 0
        self.before_insert = None    # hook(table, row) run before a POST lands
        self.before_patch = None     # hook(table, path, body), before a PATCH
        self.after_patch = None      # hook(table, rows), after a PATCH lands

    def new_id(self) -> str:
        self._next += 1
        return f"s{self._next:03d}"

    def tick(self) -> str:
        """created_at, in the order rows land."""
        self._clock += 1
        return f"t{self._clock:06d}"

    def refuses(self, table: str, row: Dict[str, Any]) -> bool:
        """The sessions constraints production enforces: the session_type
        check, contact_id NOT NULL and its foreign key, the status check."""
        if table != "sessions":
            return False
        allowed = SESSION_TYPES | ({"booking"} if self.applied else set())
        return (row.get("session_type", "other") not in allowed
                or row.get("status", "scheduled") not in SESSION_STATUSES
                or not row.get("contact_id")
                or not any(c["id"] == row["contact_id"]
                           for c in self.tables["contacts"]))

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
    def _value(row: Dict[str, Any], key: str) -> Any:
        if "->>" in key:
            col, _, field = key.partition("->>")
            return (row.get(col) or {}).get(field)
        return row.get(key)

    @staticmethod
    def _match(row: Dict[str, Any], filters) -> bool:
        for key, op, arg in filters:
            have = FakeDB._value(row, key)
            if isinstance(have, bool):
                have = "true" if have else "false"
            if op == "eq" and str(have) != arg:
                return False
            if op == "neq" and str(have) == arg:
                return False
            if op == "like":
                rx = "^" + re.escape(arg).replace(r"\*", ".*") + "$"
                if not re.match(rx, str(have or ""), re.S):
                    return False
            if op in ("gte", "lte"):
                a, b = _instant(have), _instant(arg)
                if a is None or b is None or (a < b if op == "gte" else a > b):
                    return False
            if op == "in" and str(have) not in arg.strip("()").split(","):
                return False
            if op == "not" and not (arg == "is.null" and have is not None):
                return False
            if op not in ("eq", "neq", "like", "gte", "lte", "in", "not"):
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
        table = path.strip("/").partition("?")[0]
        if self.before_patch:
            hook, self.before_patch = self.before_patch, None
            hook(table, path, body)
        table, rows = self._rows(path)
        self.calls.append(("PATCH", table, path, body))
        if ("PATCH", table) in self.fail:
            return None
        for r in rows:
            r.update(body)
            self._trigger(table, r)
        out = [dict(r) for r in rows]
        if self.after_patch:
            hook, self.after_patch = self.after_patch, None
            hook(table, out)
        return out

    def post(self, path: str, body: Dict[str, Any], *_a, **_k):
        table = path.strip("/").partition("?")[0]
        self.calls.append(("POST", table, body))
        if ("POST", table) in self.fail or self.refuses(table, body):
            return None
        row = {"id": self.new_id(), "created_at": self.tick(), **body}
        if self.before_insert:
            hook, self.before_insert = self.before_insert, None
            hook(table, row)
        self.tables.setdefault(table, []).append(row)
        self._trigger(table, row)
        return [dict(row)]

    def rpc(self, fn: str, args: Dict[str, Any], **_k):
        """sb_clients.sb_rpc_as_service: (result, None), or (None, code)."""
        self.calls.append(("RPC", fn, dict(args)))
        if not self.applied:
            return None, "PGRST202"          # PostgREST: no such function
        if ("RPC", fn) in self.fail:
            return None, "500"
        assert fn == "booking_session_sync", fn
        return self.booking_session_sync(**args), None

    def booking_session_sync(self, p_business_id: str, p_booking_id: str,
                             p_row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """The reference for public.booking_session_sync: what the SQL does,
        whole or not at all, one booking at a time (the SQL is run on these
        cases in test_booking_session_sync_sql.py)."""
        from availability_engine import booking_instant
        entry = next((e for e in self.tables["module_entries"]
                      if e["id"] == p_booking_id
                      and e.get("business_id") == p_business_id), None)
        if entry is None:
            return {"ok": True, "state": "not_found"}
        module = next((m for m in self.tables["custom_modules"]
                       if m["id"] == entry.get("module_id")), None)
        if not module or module.get("archetype") != "booking_calendar":
            return {"ok": True, "state": "not_booking"}
        marker = f"[booking:{p_booking_id}]"
        copies = sorted((s for s in self.tables["sessions"]
                         if s.get("business_id") == p_business_id
                         and marker in str(s.get("notes") or "")),
                        key=lambda s: (str(s.get("created_at") or ""), str(s["id"])))
        live = [s for s in copies if s.get("status") == "scheduled"]

        def cancel_live(keep_id: Optional[str]) -> int:
            n = 0
            for s in live:
                if s["id"] != keep_id:
                    s["status"] = "cancelled"
                    n += 1
            return n

        if entry.get("status") != "active":
            return {"ok": True, "state": "inactive", "cancelled": cancel_live(None)}
        d = entry.get("data") or {}
        text = next((str(d[k]).strip() for k in ("appointment_at", "starts_at", "scheduled_for")
                     if str(d.get(k) or "").strip()), None)
        target = booking_instant(text) if text is not None else _instant(entry.get("appointment_at"))
        if target is None:
            return {"ok": False, "state": "no_time"}
        keep = next((s for s in live if _instant(s.get("scheduled_for")) == target), None)
        state, created = "live", False
        if keep is None:
            latest = copies[-1] if copies else None
            if (latest and latest.get("status") != "scheduled"
                    and _instant(latest.get("scheduled_for")) == target):
                state = "kept_off"
            else:
                row = p_row or {}
                if booking_instant(row.get("scheduled_for")) != target:
                    return {"ok": False, "state": "stale"}
                contact = row.get("contact_id")
                if not any(c["id"] == contact and c.get("business_id") == p_business_id
                           for c in self.tables["contacts"]):
                    state = "no_contact"
                else:
                    notes = str((live[-1] if live else row).get("notes") or "")
                    if marker not in notes:
                        notes = f"{notes} {marker}".strip()
                    keep = {"id": self.new_id(), "created_at": self.tick(),
                            "business_id": p_business_id, "contact_id": contact,
                            "title": str(row.get("title") or "Booking")[:80],
                            "session_type": "booking", "status": "scheduled",
                            "scheduled_for": row["scheduled_for"],
                            "duration_minutes": max(5, int(row.get("duration_minutes") or 60)),
                            "notes": notes}
                    self.tables["sessions"].append(keep)
                    created = True
        cancelled = cancel_live(keep["id"] if keep else None)
        return {"ok": True, "state": "live" if keep else state,
                "session_id": keep["id"] if keep else None, "created": created,
                "cancelled": cancelled, "appointment_at": target.isoformat()}

    @staticmethod
    def _trigger(table: str, row: Dict[str, Any]) -> None:
        # booking_columns_from_data (APPLY-2026-10-08): the column follows data.
        if table == "module_entries":
            t = (row.get("data") or {}).get("appointment_at")
            if t:
                row["appointment_at"] = t

    # reading the result ---------------------------------------------------
    def copies(self, booking_id: str = "bk1", status: Optional[str] = None,
               business_id: str = "biz1"):
        marker = f"[booking:{booking_id}]"
        return [s for s in self.tables["sessions"]
                if marker in str(s.get("notes") or "")
                and s.get("business_id") == business_id
                and (status is None or s.get("status") == status)]


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_rpc_as_service", fake.rpc, raising=False)
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


# ═══ Codex's cross-review of #1465 (kai/reviews/core-reschedule-1465-review.md)
# Each finding, reproduced through the paths Chief and the scheduler run.

import asyncio  # noqa: E402

LATER = "2026-11-09T10:00:00Z"


def _soon(hours: int) -> str:
    """A time inside the reminder sweep's 22-26 hour window."""
    from datetime import datetime, timedelta, timezone
    t = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(hours=hours)
    return t.isoformat().replace("+00:00", "Z")


def _tick() -> None:
    asyncio.run(bwr.booking_session_sync_tick())


@pytest.fixture
def sweep(db, monkeypatch):
    """The real reminder sweep on the same fake, with the provider, consent
    and quiet hours stubbed. Returns a runner; each reminder sent is logged
    as the sms_reminder_sent event the sweep writes."""
    import sms_alerts

    async def _get(client, path):
        return db.get(path)

    async def _false(*a, **k):
        return False

    async def _true(*a, **k):
        return True

    async def _none(*a, **k):
        return None

    async def _send(phone, body, **k):
        return "provider-id"

    async def _store(client, **k):
        return "sms-id"

    async def _log(client, business_id, contact_id, event_type, data):
        db.tables["events"].append({"business_id": business_id,
                                    "event_type": event_type, "data": data})

    monkeypatch.setattr(sms_alerts, "_sb_get", _get)
    monkeypatch.setattr(sms_alerts, "alerts_enabled", lambda: True)
    monkeypatch.setattr(sms_alerts, "_in_send_window", lambda *a: True)
    monkeypatch.setattr(sms_alerts, "is_opted_out", _false)
    monkeypatch.setattr(sms_alerts, "_positive_consent", _true)
    monkeypatch.setattr(sms_alerts, "own_registration", _none)
    monkeypatch.setattr(sms_alerts, "_send_platform_sms", _send)
    monkeypatch.setattr(sms_alerts, "_store_sms", _store)
    monkeypatch.setattr(sms_alerts, "_log_event", _log)
    monkeypatch.setattr(sms_alerts, "SEND_PACING_SEC", 0)

    def run() -> List[str]:
        asyncio.run(sms_alerts.reminder_sweep())
        return [e["data"]["scheduled_for"] for e in db.tables["events"]
                if e["event_type"] == "sms_reminder_sent"]
    return run


def _same(a: str, b: str) -> bool:
    return _instant(a) == _instant(b)


# ─── P1-1: moves that overlap end on the booking's own time ───────────

def test_two_moves_to_different_times_end_with_one_copy_at_the_bookings_time(db):
    """A second move lands while the first is still syncing its copy. The
    booking ends at the second time; so must its one live copy."""
    _book(db)
    db.after_patch = lambda table, rows: _reschedule(LATER)
    _reschedule(NEW)
    assert db.tables["module_entries"][0]["data"]["appointment_at"] == LATER
    assert _live_times(db) == [LATER]


def test_a_cancel_that_lands_mid_move_leaves_no_copy(db):
    _book(db)
    db.after_patch = lambda table, rows: cba._cancel_booking_sync(BIZ, {"booking_id": "bk1"})
    _reschedule(NEW)
    assert db.tables["module_entries"][0]["status"] == "cancelled"
    assert _live_times(db) == []


def test_a_booking_cancelled_just_before_the_move_writes_is_not_moved(db):
    _book(db)
    db.before_patch = lambda table, path, body: cba._cancel_booking_sync(
        BIZ, {"booking_id": "bk1"})
    out = _reschedule(NEW)
    assert out.get("failed")
    entry = db.tables["module_entries"][0]
    assert entry["status"] == "cancelled"
    assert entry["data"]["appointment_at"] == OLD
    assert _live_times(db) == []


# ─── P1-2: a half-done move is never reminded for a stale time ────────

@pytest.mark.parametrize("broken", [
    {("PATCH", "sessions"), ("RPC", "booking_session_sync")},   # cleanup fails
    {("POST", "sessions"), ("RPC", "booking_session_sync")},    # the new copy fails
])
def test_a_half_moved_booking_is_reminded_once_and_only_for_its_time(db, sweep, broken):
    a, b = _soon(23), _soon(25)
    _book(db, when=a)
    db.fail |= broken
    out = _reschedule(b)
    assert out["calendar_updated"] is False

    # Before anything repairs it, no reminder goes out for a time the
    # booking no longer has (the old code sent one for each live copy).
    reminded = sweep()
    assert [t for t in reminded if not _same(t, b)] == []
    assert len(reminded) <= 1

    # The writes work again: the sync tick repairs it, and the client gets
    # exactly one reminder, for the time they're booked.
    db.fail.clear()
    _tick()
    assert [_same(t, b) for t in _live_times(db)] == [True]
    reminded = sweep()
    assert len(reminded) == 1 and _same(reminded[0], b)
    assert len(sweep()) == 1


def test_a_cancelled_bookings_leftover_copy_is_never_reminded(db, sweep):
    _book(db, when=_soon(24))
    db.fail.add(("PATCH", "sessions"))
    db.fail.add(("RPC", "booking_session_sync"))
    cba._cancel_booking_sync(BIZ, {"booking_id": "bk1"})
    assert sweep() == []


def test_a_plain_session_is_still_reminded(db, sweep):
    db.tables["sessions"].append({
        "id": "plain", "business_id": "biz1", "contact_id": "c1",
        "title": "Coaching call", "session_type": "coaching_session",
        "status": "scheduled", "scheduled_for": _soon(24), "notes": None,
        "created_at": db.tick()})
    assert len(sweep()) == 1


# ─── P1-3: only an active booking has a copy ──────────────────────────

@pytest.mark.parametrize("end", ["cancel_booking", "delete_module_entry", "archived"])
def test_editing_an_ended_bookings_time_never_puts_it_back_on_the_calendar(chief_sb, db, end):
    _book(db)
    if end == "cancel_booking":
        cba._cancel_booking_sync(BIZ, {"booking_id": "bk1"})
    elif end == "delete_module_entry":
        asyncio.run(chief_sb.handle_delete_module_entry(None, BIZ, {"entry_id": "bk1"}))
    else:
        db.tables["module_entries"][0]["status"] = "archived"
        _tick()
    assert _live_times(db) == []
    asyncio.run(chief_sb.handle_update_module_entry(
        None, BIZ, {"entry_id": "bk1", "data": {"appointment_at": NEW}}))
    assert db.tables["module_entries"][0]["status"] != "active"
    assert _live_times(db) == []


# ─── P2-4: asking again after a failure repairs the calendar ──────────

def test_repeating_a_booking_time_edit_after_a_calendar_failure_fixes_it(chief_sb, db):
    _book(db)
    db.fail |= {("POST", "sessions"), ("RPC", "booking_session_sync")}
    first = asyncio.run(chief_sb.handle_update_module_entry(
        None, BIZ, {"entry_id": "bk1", "data": {"appointment_at": NEW}}))
    assert first["result"] != "updated"          # the miss is said
    db.fail.clear()
    again = asyncio.run(chief_sb.handle_update_module_entry(
        None, BIZ, {"entry_id": "bk1", "data": {"appointment_at": NEW}}))
    assert again["result"] == "updated"
    assert _live_times(db) == [NEW]


# ─── should-fix: a long history never hides the live copy ─────────────

def test_a_long_history_never_hides_the_live_copy(db):
    """More than 50 old copies, all sorting first. Two identical moves still
    end with one live copy, and the second writes nothing new."""
    _book(db)
    for i in range(55):
        db.tables["sessions"].append({
            "id": f"a{i:03d}", "business_id": "biz1", "contact_id": "c1",
            "status": "cancelled", "session_type": "booking",
            "scheduled_for": "2026-01-01T09:00:00Z", "notes": "[booking:bk1]",
            "created_at": "t000000"})
    first = _reschedule(NEW)
    rows = len(db.tables["sessions"])
    second = _reschedule(NEW)
    assert first["calendar_updated"] is True and second["calendar_updated"] is True
    assert _live_times(db) == [NEW]
    assert len(db.tables["sessions"]) == rows


# ─── should-fix: a failed booking write never logs the client's name ──

class _ErrorEcho:
    """httpx.Client whose every request fails the way PostgREST does: a 400
    whose body echoes the failing row, client's name included."""
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, url, **k):
        class R:
            status_code = 400
            text = ('{"code":"23514","message":"new row violates check constraint",'
                    '"details":"Failing row contains (bk1, Maria Lopez, ...)."}')
        return R()


@pytest.fixture
def booking_writes_fail_loudly(db, monkeypatch):
    """Booking PATCHes go through sb_clients' real error handling."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
    monkeypatch.setattr(sb_clients.httpx, "Client", _ErrorEcho)

    def patch(path, body, **k):
        if path.startswith("/module_entries"):
            return _REAL_PATCH(path, body, **k)
        return db.patch(path, body, **k)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)


def _no_name_anywhere(capsys, caplog) -> None:
    printed = capsys.readouterr()
    for text in (printed.out, printed.err, caplog.text):
        assert "Maria" not in text and "Lopez" not in text


def test_a_failed_booking_write_never_logs_the_clients_name(
        db, booking_writes_fail_loudly, capsys, caplog):
    caplog.set_level("DEBUG")
    _book(db)
    assert _reschedule(NEW).get("failed")
    assert cba._cancel_booking_sync(BIZ, {"booking_id": "bk1"}).get("failed")
    _no_name_anywhere(capsys, caplog)


def _series(db: FakeDB, n: int = 2) -> None:
    for i in range(n):
        bid = f"sr{i}"
        entry = {"id": bid, "business_id": "biz1", "module_id": "mod1",
                 "status": "active",
                 "data": {"appointment_at": f"2026-11-1{i}T15:00:00Z",
                          "customer_name": CLIENT, "contact_id": "c1",
                          "series_id": "series1", "duration_min_at_booking": 30}}
        db.tables["module_entries"].append(entry)
        FakeDB._trigger("module_entries", entry)
        bwr._mirror_booking_session("biz1", dict(entry))


def test_a_failed_series_write_never_logs_the_clients_name(
        db, booking_writes_fail_loudly, capsys, caplog):
    import booking_series
    caplog.set_level("DEBUG")
    _series(db)
    out = booking_series.cancel_series("biz1", "series1", from_iso="2026-11-01T00:00:00Z")
    assert out["cancelled"] == 0
    _no_name_anywhere(capsys, caplog)


# ─── recurring cancel: a copy it couldn't clear is counted and said ───

def test_cancelling_a_series_says_how_many_copies_stayed(db, capsys):
    import booking_series
    _series(db, 2)
    db.fail |= {("PATCH", "sessions"), ("RPC", "booking_session_sync")}
    out = booking_series.cancel_series("biz1", "series1", from_iso="2026-11-01T00:00:00Z")
    assert out["cancelled"] == 2
    assert out["calendar_not_cleared"] == 2
    assert "2 may still show" in out["summary"]
    printed = capsys.readouterr().out
    assert printed.count("[series] calendar copy not cleared") == 2
    assert "Maria" not in printed


def test_cancelling_a_series_clears_every_copy(db):
    import booking_series
    _series(db, 2)
    out = booking_series.cancel_series("biz1", "series1", from_iso="2026-11-01T00:00:00Z")
    assert out["cancelled"] == 2 and out["calendar_not_cleared"] == 0
    assert _live_times(db, "sr0") == [] and _live_times(db, "sr1") == []


# ─── a second business is never touched ───────────────────────────────

@pytest.fixture
def two_tenants(db):
    """A second business with its own booking module, contact, booking and
    copy, plus a session of its own whose notes happen to carry biz1's
    marker. Nothing done for biz1 may change any of it."""
    db.tables["custom_modules"].append({"id": "mod2", "business_id": "biz2",
                                        "archetype": "booking_calendar", "is_active": True})
    db.tables["contacts"].append({"id": "c2", "business_id": "biz2", "name": "Other Client",
                                  "phone": "+13125550199"})
    db.tables["businesses"].append({"id": "biz2", "name": "Other Shop", "settings": {}})
    entry = {"id": "bk2", "business_id": "biz2", "module_id": "mod2", "status": "active",
             "data": {"appointment_at": OLD, "customer_name": "Other Client",
                      "contact_id": "c2", "duration_min_at_booking": 30}}
    db.tables["module_entries"].append(entry)
    FakeDB._trigger("module_entries", entry)
    bwr._mirror_booking_session("biz2", dict(entry))
    db.tables["sessions"].append({
        "id": "x-biz2", "business_id": "biz2", "contact_id": "c2",
        "session_type": "other", "status": "scheduled", "scheduled_for": OLD,
        "notes": "Pasted from an old note: [booking:bk1]", "created_at": db.tick()})

    def snapshot():
        import copy
        return copy.deepcopy([r for t in ("module_entries", "sessions")
                              for r in db.tables[t] if r.get("business_id") == "biz2"])
    return snapshot


def test_another_business_is_untouched_by_every_booking_verb(chief_sb, db, two_tenants):
    before = two_tenants()
    assert len([r for r in before if r.get("notes", "").endswith("[booking:bk2]")]) == 1
    _book(db)
    _reschedule(NEW)
    asyncio.run(chief_sb.handle_update_module_entry(
        None, BIZ, {"entry_id": "bk1", "data": {"appointment_at": LATER}}))
    cba._cancel_booking_sync(BIZ, {"booking_id": "bk1"})
    _tick()
    assert two_tenants() == before


def test_one_business_cannot_move_or_cancel_anothers_booking(chief_sb, db, two_tenants):
    before = two_tenants()
    assert _reschedule(NEW, booking_id="bk2").get("failed")
    assert cba._cancel_booking_sync(BIZ, {"booking_id": "bk2"}).get("failed")
    asyncio.run(chief_sb.handle_update_module_entry(
        None, BIZ, {"entry_id": "bk2", "data": {"appointment_at": NEW}}))
    assert two_tenants() == before


# ─── a booking with no client contact (KAI, 2026-10-16) ───────────────
# sessions.contact_id is NOT NULL, so a hand-made booking with no contact
# can't have a copy. Decision: no copy, said plainly; a contact is never
# made up for it.

def _hand_made(db: FakeDB, when: str = OLD) -> Dict[str, Any]:
    entry = {"id": "bk1", "business_id": "biz1", "module_id": "mod1",
             "status": "active", "created_by": "operator:someone",
             "data": {"appointment_at": when, "customer_name": CLIENT,
                      "duration_min_at_booking": 30}}
    db.tables["module_entries"].append(entry)
    FakeDB._trigger("module_entries", entry)
    return entry


def test_a_booking_with_no_client_gets_no_copy_and_chief_says_so(db):
    _hand_made(db)
    contacts = len(db.tables["contacts"])
    out = _reschedule(NEW)
    assert out["result"].startswith("moved to") and not out.get("failed")
    assert "no client contact" in out["result"]
    assert "couldn't" not in out["result"]
    assert db.tables["sessions"] == []
    assert len(db.tables["contacts"]) == contacts


def test_the_tick_makes_no_copy_and_no_contact_for_a_booking_with_no_client(db):
    _hand_made(db, when=_soon(30))
    contacts = len(db.tables["contacts"])
    _tick()
    assert db.tables["sessions"] == []
    assert len(db.tables["contacts"]) == contacts


# ─── before the APPLY file: nothing new happens, nothing false is said ─

def test_before_the_apply_file_nothing_is_written_and_nothing_false_is_said(db, capsys):
    """Production on 2026-10-16: sessions refuses session_type 'booking',
    so no booking has ever had a copy (the mirror's insert always failed).
    Until the APPLY file is in, a move must not claim the calendar failed:
    the practitioner's calendar reads the booking itself."""
    db.applied = False
    entry = _hand_made(db)
    entry["data"]["contact_id"] = "c1"
    bwr._mirror_booking_session("biz1", dict(entry))
    assert db.tables["sessions"] == []

    out = _reschedule(NEW)
    assert out["result"].startswith("moved to") and not out.get("failed")
    assert "couldn't" not in out["result"]
    assert out["calendar_updated"] is not False
    cancel = cba._cancel_booking_sync(BIZ, {"booking_id": "bk1"})
    assert "couldn't" not in cancel["result"]
    assert db.tables["sessions"] == []
    assert "calendar copy not updated" not in capsys.readouterr().out
