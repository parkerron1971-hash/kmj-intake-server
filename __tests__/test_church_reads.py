"""
test_church_reads.py — first-time guests nobody has reached.

The panel this feeds was empty for its whole life: it filtered
contacts.status = "first_time", which nothing ever writes. These tests pin
the replacement to the facts that DO get written (attendance.first_time,
outbound texts, logged activity) and to the one trap that hid guests from
every other list: the check-in itself stamps last_interaction, so "seen"
must never count as "reached".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import church_reads as C
import workspace_layouts
import workspace_resolver as R

BIZ = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
SUNDAY = NOW - timedelta(days=10)          # Oct 4
ANNA, BEN, CARA = ("aaaaaaaa-0000-0000-0000-00000000000a",
                   "bbbbbbbb-0000-0000-0000-00000000000b",
                   "cccccccc-0000-0000-0000-00000000000c")
SERVICE = "eeeeeeee-0000-0000-0000-00000000000e"


def _iso(dt):
    return dt.isoformat()


class FakeDB:
    def __init__(self, **tables):
        self.tables = tables
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        table = path.split("?", 1)[0].strip("/")
        if table == "attendance" and "first_time=is.true" in path:
            table = "attendance_first"
        rows = self.tables.get(table, [])
        return None if rows is None else list(rows)


def _visit(id_, contact, at, name="Guest", first=True):
    return {"id": id_, "entry_id": SERVICE, "contact_id": contact, "name": name,
            "checked_in_at": _iso(at), "first_time": first}


@pytest.fixture
def db(monkeypatch):
    def install(**tables):
        tables.setdefault("module_entries", [{"id": SERVICE, "data": {"title": "Sunday Service"}}])
        fake = FakeDB(**tables)
        import sb_clients
        monkeypatch.setattr(sb_clients, "sb_get_as_service", fake)
        return fake
    return install


def _people(*ids):
    names = {ANNA: "Anna Reed", BEN: "Ben Ortiz", CARA: "Cara Lee"}
    return [{"id": i, "name": names[i], "phone": "+12165550100", "email": None,
             "status": "lead"} for i in ids]


def test_a_guest_nobody_reached_is_listed(db):
    db(attendance_first=[_visit("v1", ANNA, SUNDAY)],
       contacts=_people(ANNA), attendance=[{"contact_id": ANNA, "checked_in_at": _iso(SUNDAY)}])
    rows = C.first_time_guests(BIZ, now=NOW)
    assert [r["name"] for r in rows] == ["Anna Reed"]
    assert rows[0]["detail"] == "Sunday Service, Oct 4"
    assert rows[0]["has_phone"] is True


def test_an_outbound_text_after_the_visit_takes_them_off(db):
    db(attendance_first=[_visit("v1", ANNA, SUNDAY)], contacts=_people(ANNA),
       sms_messages=[{"contact_id": ANNA, "created_at": _iso(SUNDAY + timedelta(days=2))}])
    assert C.first_time_guests(BIZ, now=NOW) == []


def test_a_logged_call_after_the_visit_takes_them_off(db):
    db(attendance_first=[_visit("v1", ANNA, SUNDAY)], contacts=_people(ANNA),
       events=[{"contact_id": ANNA, "created_at": _iso(SUNDAY + timedelta(hours=30))}])
    assert C.first_time_guests(BIZ, now=NOW) == []


def test_reaching_out_BEFORE_the_visit_does_not_count(db):
    """An invitation text the week before is not a follow-up."""
    db(attendance_first=[_visit("v1", ANNA, SUNDAY)], contacts=_people(ANNA),
       sms_messages=[{"contact_id": ANNA, "created_at": _iso(SUNDAY - timedelta(days=3))}])
    assert [r["name"] for r in C.first_time_guests(BIZ, now=NOW)] == ["Anna Reed"]


def test_the_check_in_stamping_last_interaction_never_counts_as_reached(db):
    """The trap that hid them: the attendance screen writes
    contacts.last_interaction on check-in. That column is not read here."""
    fake = db(attendance_first=[_visit("v1", ANNA, SUNDAY)],
              contacts=[dict(_people(ANNA)[0], last_interaction=_iso(SUNDAY))])
    assert len(C.first_time_guests(BIZ, now=NOW)) == 1
    assert not any("last_interaction" in c for c in fake.calls)


def test_only_real_reach_outs_are_counted(db):
    fake = db(attendance_first=[_visit("v1", ANNA, SUNDAY)], contacts=_people(ANNA))
    C.first_time_guests(BIZ, now=NOW)
    sms = next(c for c in fake.calls if c.startswith("/sms_messages"))
    ev = next(c for c in fake.calls if c.startswith("/events"))
    assert "direction=eq.outbound" in sms and "status=neq.failed" in sms
    for kind in C.REACH_OUT_EVENTS:
        assert kind in ev
    assert "contact_note" not in ev  # a note about someone is not a call to them


def test_coming_back_is_shown_but_does_not_count_as_reached(db):
    db(attendance_first=[_visit("v1", ANNA, SUNDAY)], contacts=_people(ANNA),
       attendance=[{"contact_id": ANNA, "checked_in_at": _iso(SUNDAY)},
                   {"contact_id": ANNA, "checked_in_at": _iso(SUNDAY + timedelta(days=7))}])
    rows = C.first_time_guests(BIZ, now=NOW)
    assert rows[0]["came_back"] == 1
    assert rows[0]["detail"].endswith("came back once")


def test_longest_waiting_first_and_one_row_per_person(db):
    db(attendance_first=[_visit("v1", BEN, SUNDAY - timedelta(days=7)),
                         _visit("v2", ANNA, SUNDAY),
                         _visit("v3", BEN, SUNDAY)],  # marked first-time twice
       contacts=_people(ANNA, BEN))
    rows = C.first_time_guests(BIZ, now=NOW)
    assert [r["name"] for r in rows] == ["Ben Ortiz", "Anna Reed"]
    assert rows[0]["id"] == "v1"


def test_a_name_only_guest_is_listed_with_no_way_to_reach_them(db):
    fake = db(attendance_first=[_visit("v1", None, SUNDAY, name="Dee  Walker")])
    rows = C.first_time_guests(BIZ, now=NOW)
    assert rows[0]["name"] == "Dee Walker" and rows[0]["contact_id"] is None
    assert "no phone or email on file" in rows[0]["detail"]
    assert not any(c.startswith("/sms_messages") for c in fake.calls)


def test_removed_or_inactive_records_are_left_off(db):
    db(attendance_first=[_visit("v1", ANNA, SUNDAY), _visit("v2", BEN, SUNDAY)],
       contacts=[dict(_people(BEN)[0], status="inactive")])
    assert C.first_time_guests(BIZ, now=NOW) == []


def test_the_window_is_in_the_query_without_a_raw_plus(db):
    fake = db(attendance_first=[])
    assert C.first_time_guests(BIZ, now=NOW) == []
    first = fake.calls[0]
    assert "checked_in_at=gte.2026-09-14T15:00:00Z" in first
    assert "+" not in first


def test_every_query_is_pinned_to_the_business(db):
    fake = db(attendance_first=[_visit("v1", ANNA, SUNDAY)], contacts=_people(ANNA))
    C.first_time_guests(BIZ, now=NOW)
    assert len(fake.calls) >= 5
    for c in fake.calls:
        assert f"business_id=eq.{BIZ}" in c


def test_a_failed_read_is_none_not_an_empty_list(db):
    db(attendance_first=None)
    assert C.first_time_guests(BIZ, now=NOW) is None
    db(attendance_first=[_visit("v1", ANNA, SUNDAY)], contacts=_people(ANNA), sms_messages=None)
    assert C.first_time_guests(BIZ, now=NOW) is None


# ─── the desk layout ─────────────────────────────────────────────────

def test_the_ministry_panel_no_longer_reads_a_status_nothing_sets():
    layout = workspace_layouts.get_preset("ministry")
    panel = next(s for s in layout["surfaces"] if s["id"] == "first_time_guests")
    items = panel["bindings"]["items"]
    assert items["source"] == "first_time_guests"
    assert "first_time" not in str(items.get("filter") or {})


def test_the_ministry_panel_resolves_through_church_reads(db):
    db(attendance_first=[_visit("v1", ANNA, datetime.now(timezone.utc) - timedelta(days=3))],
       contacts=_people(ANNA))
    layout = workspace_layouts.get_preset("ministry")
    data = R.resolve(layout, BIZ)
    items = data["first_time_guests"]["items"]
    assert items[0]["id"] == "v1"
    assert items[0]["title"] == "Anna Reed"
    assert items[0]["subtitle"].startswith("Sunday Service")
    assert isinstance(items[0]["age_days"], int)


# ─── the endpoint ────────────────────────────────────────────────────

def test_the_endpoint_is_mounted_before_the_catch_all_and_needs_a_sign_in():
    import os
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    from fastapi.testclient import TestClient
    import kmj_intake_automation

    paths = [getattr(r, "path", "") for r in kmj_intake_automation.app.routes]
    assert "/church/first-time-guests" in paths
    assert paths.index("/church/first-time-guests") < paths.index("/{path:path}")
    r = TestClient(kmj_intake_automation.app).get(
        f"/church/first-time-guests?business_id={BIZ}")
    assert r.status_code in (401, 403)
