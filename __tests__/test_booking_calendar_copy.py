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
