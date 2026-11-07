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


# ─── A card or a first kids check-in is a guest too ───────────────────
# Neither writes attendance.first_time, so someone who filled out a card
# used to be missing here while their follow-up sat waiting.

def _follow_up(id_, contact, at, *, answers=(), card_key="web:connect_card",
               card_name="Connect card", kind="connect"):
    return {"id": id_, "contact_id": contact, "card_key": card_key, "card_name": card_name,
            "path_kind": kind, "answers": list(answers), "created_at": _iso(at)}


def _person(id_, made):
    return dict(_people(id_)[0], created_at=_iso(made))


FIRST_TIME = [{"q": "How many times have you visited?", "a": "This is my first time"}]
A_FEW = [{"q": "How many times have you visited?", "a": "A few times"}]


def test_a_card_that_says_first_time_is_a_guest(db):
    db(church_follow_ups=[_follow_up("fu-1", ANNA, SUNDAY, answers=FIRST_TIME)],
       contacts=[_person(ANNA, SUNDAY)])
    rows = C.first_time_guests(BIZ, now=NOW)
    assert [r["name"] for r in rows] == ["Anna Reed"]
    assert rows[0]["id"] == "fu-1" and rows[0]["contact_id"] == ANNA
    assert rows[0]["occasion"] == "Connect card" and rows[0]["detail"].startswith("Connect card, Oct 4")
    assert rows[0]["has_phone"] is True


def test_a_first_check_in_at_the_kids_desk_is_a_guest(db):
    old = NOW - timedelta(days=400)
    db(church_follow_ups=[_follow_up("fu-1", ANNA, SUNDAY, card_key="checkin:first", card_name="First check-in",
                                     answers=[{"q": "First visit", "a": "Sunday Service, Oct 4"}])],
       contacts=[_person(ANNA, old)])
    assert [r["occasion"] for r in C.first_time_guests(BIZ, now=NOW)] == ["First check-in"]


def test_a_card_that_says_a_few_times_is_not(db):
    db(church_follow_ups=[_follow_up("fu-1", ANNA, SUNDAY, answers=A_FEW)],
       contacts=[_person(ANNA, SUNDAY)])
    assert C.first_time_guests(BIZ, now=NOW) == []


def test_a_card_that_never_asked_goes_by_whether_the_record_is_new(db):
    made = [_follow_up("fu-1", ANNA, SUNDAY), _follow_up("fu-2", BEN, SUNDAY)]
    db(church_follow_ups=made, contacts=[_person(ANNA, SUNDAY), _person(BEN, NOW - timedelta(days=400))])
    assert [r["name"] for r in C.first_time_guests(BIZ, now=NOW)] == ["Anna Reed"]


def test_a_yes_to_a_first_visit_question_counts(db):
    yes = [{"q": "Is this your first visit?", "a": "Yes"}]
    no = [{"q": "Is this your first visit?", "a": "No"}]
    db(church_follow_ups=[_follow_up("fu-1", ANNA, SUNDAY, answers=yes), _follow_up("fu-2", BEN, SUNDAY, answers=no)],
       contacts=[_person(ANNA, SUNDAY), _person(BEN, SUNDAY)])
    assert [r["name"] for r in C.first_time_guests(BIZ, now=NOW)] == ["Anna Reed"]


def test_a_no_to_been_here_before_counts(db):
    no = [{"q": "Have you been here before?", "a": "No"}]
    yes = [{"q": "Have you been here before?", "a": "Yes"}]
    db(church_follow_ups=[_follow_up("fu-1", ANNA, SUNDAY, answers=no), _follow_up("fu-2", BEN, SUNDAY, answers=yes)],
       contacts=[_person(ANNA, SUNDAY), _person(BEN, SUNDAY)])
    assert [r["name"] for r in C.first_time_guests(BIZ, now=NOW)] == ["Anna Reed"]


def test_a_card_someone_is_answering_about_something_else_is_not(db):
    db(church_follow_ups=[_follow_up("fu-1", ANNA, SUNDAY, card_name="Baptism", kind="baptism", answers=FIRST_TIME)],
       contacts=[_person(ANNA, SUNDAY)])
    assert C.first_time_guests(BIZ, now=NOW) == []


def test_a_marked_first_visit_keeps_its_service_and_shows_once(db):
    db(attendance_first=[_visit("v1", ANNA, SUNDAY)],
       church_follow_ups=[_follow_up("fu-1", ANNA, SUNDAY + timedelta(hours=1), answers=FIRST_TIME)],
       contacts=[_person(ANNA, SUNDAY)])
    rows = C.first_time_guests(BIZ, now=NOW)
    assert len(rows) == 1 and rows[0]["id"] == "v1" and rows[0]["occasion"] == "Sunday Service"


def test_a_card_guest_drops_off_once_someone_reaches_out(db):
    db(church_follow_ups=[_follow_up("fu-1", ANNA, SUNDAY, answers=FIRST_TIME)],
       contacts=[_person(ANNA, SUNDAY)],
       sms_messages=[{"contact_id": ANNA, "created_at": _iso(SUNDAY + timedelta(days=1))}])
    assert C.first_time_guests(BIZ, now=NOW) == []


def test_only_open_follow_ups_still_on_reach_out_are_read(db):
    fake = db()
    C.first_time_guests(BIZ, now=NOW)
    read = next(c for c in fake.calls if c.startswith("/church_follow_ups"))
    assert "status=in.(open,handed_back)" in read and "step=eq.0" in read


def test_follow_ups_unreadable_is_unknown_never_nobody(db):
    db(church_follow_ups=None)
    assert C.first_time_guests(BIZ, now=NOW) is None
