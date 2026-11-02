# __tests__/test_office_logins_in_the_loop.py
#
# Love City's office checkup (Kevin, 2026-11-01): the four admins held no
# church role, so none was in the All group leaders room. The Church
# Administrator sent the Monday leaders note and never got it. Pins:
#   1. an office login (an active Admin or Manager seat) is in the leaders
#      room as its own member record: the one it's tied to, else the one its
#      email names; never a member or viewer seat, an invited or removed
#      one, or a family address that names nobody
#   2. a failed read of the logins leaves the room as the leaders alone,
#      never empty, never None
#   3. the Monday leaders note goes to them (it goes to the room)
#   4. the Hand to list keeps them as logins, not a second time as leaders
#   5. a seat its email matched keeps that record from then on (seat_person)

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import business_users_router as bur
import church_leader_tasks as clt
import member_portal_messaging as mpm
import sb_clients
from test_member_messaging import ANA, BIZ, env  # noqa: F401
from test_member_safety_officers import STAFFER, church  # noqa: F401

NAIYA = "00000000-0000-4000-8000-0000000001a1"     # the Church Administrator: no role, no group
TIARA = "00000000-0000-4000-8000-0000000001a2"     # People & Care: tied by contact_id
TWIN1 = "00000000-0000-4000-8000-0000000001a3"     # two people on one family address
TWIN2 = "00000000-0000-4000-8000-0000000001a4"


@pytest.fixture
def office(church):
    t = church.t
    # First in the table: the fake reads `email=ilike.` as any row and
    # keeps match_contact's limit of 10, so the office's people lead.
    t["contacts"][:0] = [
        {"id": NAIYA, "business_id": BIZ, "name": "Naiya Clark", "birthdate": "1990-01-01", "email": "naiya@example.com"},
        {"id": TIARA, "business_id": BIZ, "name": "Tiara Adams", "birthdate": "1991-01-01", "email": "tiara@example.com"},
        {"id": TWIN1, "business_id": BIZ, "name": "Lee Moss", "birthdate": "1980-01-01", "email": "moss@example.com"},
        {"id": TWIN2, "business_id": BIZ, "name": "Lynn Moss", "birthdate": "1981-01-01", "email": "moss@example.com"}]
    t["business_users"] += [
        {"business_id": BIZ, "user_id": "u-naiya", "status": "active", "role": "manager", "invited_email": "Naiya@Example.com"},
        {"business_id": BIZ, "user_id": "u-tiara", "status": "active", "role": "manager", "invited_email": "other@example.com",
         "contact_id": TIARA},
        {"business_id": BIZ, "user_id": "u-moss", "status": "active", "role": "manager", "invited_email": "moss@example.com"},
        {"business_id": BIZ, "user_id": "u-ana", "status": "active", "role": "member", "invited_email": "ana@example.com"},
        {"business_id": BIZ, "user_id": "u-gone", "status": "revoked", "role": "manager", "invited_email": "naiya@example.com"}]
    return church


def _room():
    return {p["contact_id"] for p in mpm.leaders_room_people(BIZ)}


def test_an_office_login_is_in_the_leaders_room_as_its_own_record(office):
    ids = _room()
    assert {NAIYA, TIARA} <= ids                 # matched by email; tied by contact_id
    assert not ids & {TWIN1, TWIN2}              # a family address names nobody
    assert mpm.office_contacts(BIZ) >= {NAIYA, TIARA}


def test_a_member_seat_or_a_removed_one_is_not_an_office_login(office):
    office.t["business_users"] = [s for s in office.t["business_users"] if s["user_id"] in ("u-ana", "u-gone")]
    assert mpm.office_contacts(BIZ) == set()
    assert ANA not in _room()


def test_a_failed_read_of_the_logins_leaves_the_leaders(office, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if path.startswith("/business_users") else real(path, *a, **k))
    ids = _room()
    assert STAFFER in ids and NAIYA not in ids   # the leaders still there; the office left out this once
    assert mpm.office_contacts(BIZ) is None


def test_the_monday_leaders_note_goes_to_them(office):
    import church_leaders_note as cln
    to = {r["email"].lower() for r in cln.recipients(BIZ)["to"]}
    assert {"naiya@example.com", "tiara@example.com"} <= to


def test_the_hand_to_list_keeps_them_as_logins_not_as_leaders(office):
    got = clt.leaders(BIZ)
    assert got is not None
    ids = {p["contact_id"] for p in got}
    assert not ids & {NAIYA, TIARA}


def test_a_seat_its_email_matched_keeps_that_record(office):
    me = bur.seat_person(BIZ, "u-naiya")
    assert me and me["contact_id"] == NAIYA and me["first_name"] == "Naiya"
    seat = next(s for s in office.t["business_users"] if s["user_id"] == "u-naiya")
    assert seat.get("contact_id") == NAIYA


def test_a_tied_seat_or_a_family_address_writes_nothing(office, monkeypatch):
    writes = []
    real = sb_clients.sb_patch_as_service
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body, *a, **k: writes.append(path) or real(path, body, *a, **k))
    assert bur.seat_person(BIZ, "u-tiara")["contact_id"] == TIARA
    assert bur.seat_person(BIZ, "u-moss") is None
    assert not [w for w in writes if w.startswith("/business_users")]


def test_a_failed_keep_still_greets_them(office, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", boom)
    assert bur.seat_person(BIZ, "u-naiya")["name"] == "Naiya Clark"
