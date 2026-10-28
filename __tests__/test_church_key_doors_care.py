"""Church Areas, step 2, part 1b: the Kids and Care doors (church_keys).
Kevin's picks 2026-10-26: guarded at the start, kids' medical notes and
pastors-only notes; the lock binds the owner too.

Pins:
  * Kids: once the church names a Kids & youth keeper, a manager (and the
    owner) sees that a child has medical or custody notes, never what they
    say, and can't write over them; the keeper, and a key, read them. A new
    child's first notes are still written by whoever registers them.
    Allergies stay open. With no keeper nothing changes
  * Care's inbox: the owner sees every request until the church names a
    People & care keeper; from then on the keeper does, and the owner (like
    every seat) sees only what was handed to them, unless they hold a key
  * the Follow-up board leaves out pastors-only notes (and says how many)
    for anyone the lock holds; writing one stays open
  * a failed read of the keepers is a 503, never an open door
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_keys as ck  # noqa: E402
import church_router  # noqa: E402
import kids_router as kr  # noqa: E402
import private_care  # noqa: E402
import sb_clients  # noqa: E402
from test_church_keys import BIZ, ID, PEOPLE, _later, _refused, db  # noqa: E402,F401

FAMILY = "44444444-4444-4444-8444-444444444444"
CHILD = "55555555-5555-4555-8555-555555555555"
STAMP = "2026-10-20T10:00:00+00:00"


@pytest.fixture
def kids(db):
    db.t.update(
        households=[{"id": FAMILY, "business_id": BIZ, "name": "The Hills", "created_at": STAMP, "updated_at": STAMP}],
        household_adults=[], household_pickups=[], contacts=[],
        children=[{"id": CHILD, "business_id": BIZ, "household_id": FAMILY, "first_name": "Ava", "last_name": "Hill",
                   "room": "Preschool", "active": True, "updated_at": STAMP}],
        child_care_notes=[{"child_id": CHILD, "business_id": BIZ, "allergies": "peanuts",
                           "medical": "Inhaler in her bag", "custody": "", "updated_at": STAMP}],
    )
    return db


def _child(user):
    fams = kr.list_families(business_id=BIZ, user=user)
    return fams, fams["families"][0]["children"][0]


def _key(area, who, keeper):
    asked = ck.ask(BIZ, PEOPLE[who], area, "Sunday")
    ck.answer(BIZ, PEOPLE[keeper], asked["key"]["id"], True)


# ─── Kids ─────────────────────────────────────────────────────────────

def test_with_no_kids_keeper_a_manager_reads_the_notes_as_before(kids):
    fams, ava = _child(PEOPLE["admin"])
    assert fams["can_see_private"] and not fams["private_locked"]
    assert ava["medical"] == "Inhaler in her bag" and ava["allergies"] == "peanuts"


def test_a_kids_keeper_locks_the_medical_and_custody_notes_the_owner_too(kids):
    ck.put_keeper(BIZ, PEOPLE["admin"], "kids_youth", ID["second"], True)
    for who in ("admin", "owner"):
        fams, ava = _child(PEOPLE[who])
        assert fams["private_locked"] and not fams["can_see_private"]
        assert "medical" not in ava and "custody" not in ava
        assert ava["has_private_notes"] is True and ava["allergies"] == "peanuts"
    fams, ava = _child(PEOPLE["second"])
    assert fams["can_see_private"] and ava["medical"] == "Inhaler in her bag"
    _key("kids_youth", "admin", "second")
    assert _child(PEOPLE["admin"])[1]["medical"] == "Inhaler in her bag"
    _later(kids, minutes=61)
    assert "medical" not in _child(PEOPLE["admin"])[1]


def test_a_member_still_sees_only_that_there_is_a_note(kids):
    ck.put_keeper(BIZ, PEOPLE["admin"], "kids_youth", ID["second"], True)
    fams, ava = _child(PEOPLE["member"])
    assert not fams["can_see_private"] and not fams["private_locked"] and ava["has_private_notes"]


def test_nobody_locked_writes_over_a_note_they_cant_read(kids):
    ck.put_keeper(BIZ, PEOPLE["admin"], "kids_youth", ID["second"], True)
    before = [dict(n) for n in kids.t["child_care_notes"]]
    e = _refused(kr.edit_child, CHILD, kr.ChildPatch(business_id=BIZ, medical="", expected_updated_at=STAMP),
                 user=PEOPLE["admin"])
    assert e.status_code == 403 and e.detail["code"] == "area_locked" and e.detail["area"] == "kids_youth"
    assert kids.t["child_care_notes"] == before and kids.t["children"][0]["updated_at"] == STAMP
    # The rest of the child, and the allergy, still save.
    kr.edit_child(CHILD, kr.ChildPatch(business_id=BIZ, room="Elementary", allergies="peanuts, eggs",
                                       expected_updated_at=STAMP), user=PEOPLE["admin"])
    assert kids.t["children"][0]["room"] == "Elementary"
    wrote = [w[2] for w in kids.writes if w[:2] == ("POST", "child_care_notes")]
    assert wrote[-1]["allergies"] == "peanuts, eggs" and "medical" not in wrote[-1] and "custody" not in wrote[-1]
    kr.edit_child(CHILD, kr.ChildPatch(business_id=BIZ, medical="Inhaler and an EpiPen"), user=PEOPLE["second"])
    wrote = [w[2] for w in kids.writes if w[:2] == ("POST", "child_care_notes")]
    assert wrote[-1]["medical"] == "Inhaler and an EpiPen"


def test_the_desk_still_records_a_new_childs_first_notes(kids):
    ck.put_keeper(BIZ, PEOPLE["admin"], "kids_youth", ID["second"], True)
    out = kr.add_child(kr.ChildIn(business_id=BIZ, household_id=FAMILY, first_name="Eli", medical="Type 1 diabetes"),
                       user=PEOPLE["admin"])
    assert any(n["child_id"] == out["child"]["id"] and n["medical"] == "Type 1 diabetes"
               for n in kids.t["child_care_notes"])


# ─── Care's inbox ─────────────────────────────────────────────────────

def test_care_inbox_the_owner_sees_everything_until_a_care_keeper_is_named(db):
    assert private_care.care_access(BIZ, PEOPLE["owner"]).scope == "all"
    assert private_care.care_access(BIZ, PEOPLE["pastor"]).scope == "assigned"
    ck.put_keeper(BIZ, PEOPLE["admin"], "people_care", ID["pastor"], True)
    assert private_care.care_access(BIZ, PEOPLE["pastor"]).scope == "all"
    assert private_care.care_access(BIZ, PEOPLE["owner"]).scope == "assigned"
    assert private_care.care_access(BIZ, PEOPLE["admin"]).scope == "assigned"
    _key("people_care", "owner", "pastor")
    assert private_care.care_access(BIZ, PEOPLE["owner"]).scope == "all"
    assert _refused(private_care.care_access, BIZ, PEOPLE["stranger"]).status_code == 403


def test_a_locked_owner_lists_only_what_was_handed_to_them(db):
    db.t["ministry_care_requests"] = [
        {"id": "r1", "business_id": BIZ, "created_at": STAMP, "status": "new", "submission": {}, "assigned_to": None},
        {"id": "r2", "business_id": BIZ, "created_at": STAMP, "status": "new", "submission": {}, "assigned_to": ID["owner"]}]
    db.t["ministry_care_notes"] = []
    ck.put_keeper(BIZ, PEOPLE["admin"], "people_care", ID["pastor"], True)
    seen = private_care.list_requests(BIZ, private_care.care_access(BIZ, PEOPLE["owner"]))
    assert [r["id"] for r in seen["requests"]] == ["r2"] and seen["scope"] == "assigned"
    seen = private_care.list_requests(BIZ, private_care.care_access(BIZ, PEOPLE["pastor"]))
    assert sorted(r["id"] for r in seen["requests"]) == ["r1", "r2"]


# ─── The Follow-up board ──────────────────────────────────────────────

@pytest.fixture
def board(db, monkeypatch):
    import church_follow_up
    notes = [{"id": "n1", "body": "Called, doing well", "pastors_only": False},
             {"id": "n2", "body": "Marriage is struggling", "pastors_only": True}]
    monkeypatch.setattr(church_follow_up, "board", lambda biz, **k: {
        "follow_ups": [{"id": "f1", "notes": [dict(n) for n in notes]}], "counts": {}, "leaders": []})
    return db


def _board(who):
    return church_router.follow_ups(business_id=BIZ, biz={"id": BIZ}, session=SimpleNamespace(user=PEOPLE[who]))


def test_the_board_leaves_out_pastors_only_notes_for_anyone_the_lock_holds(board):
    assert [n["id"] for n in _board("admin")["follow_ups"][0]["notes"]] == ["n1", "n2"]
    ck.put_keeper(BIZ, PEOPLE["admin"], "people_care", ID["pastor"], True)
    for who in ("admin", "owner"):
        out = _board(who)
        card = out["follow_ups"][0]
        assert [n["id"] for n in card["notes"]] == ["n1"] and card["pastors_notes_locked"] == 1
        assert out["pastors_only_locked"] is True and "Marriage" not in str(out)
    assert [n["id"] for n in _board("pastor")["follow_ups"][0]["notes"]] == ["n1", "n2"]
    _key("people_care", "admin", "pastor")
    assert "pastors_only_locked" not in _board("admin")


# ─── Failure ──────────────────────────────────────────────────────────

def test_a_failed_read_of_the_keepers_is_a_503_never_an_open_door(kids, board, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, **k: None if path.startswith("/church_keepers") else real(path, **k))
    assert _refused(kr.list_families, business_id=BIZ, user=PEOPLE["admin"]).status_code == 503
    assert _refused(private_care.care_access, BIZ, PEOPLE["owner"]).status_code == 503
    assert _refused(_board, "admin").status_code == 503


def test_opened_says_none_where_nothing_is_kept(db, monkeypatch):
    assert ck.opened(BIZ, PEOPLE["owner"], "people_care") is None
    ck.put_keeper(BIZ, PEOPLE["admin"], "people_care", ID["pastor"], True)
    assert ck.opened(BIZ, PEOPLE["owner"], "people_care") is False
    assert ck.opened(BIZ, PEOPLE["pastor"], "people_care") is True
    monkeypatch.setenv("CHURCH_KEYS", "off")
    assert ck.opened(BIZ, PEOPLE["owner"], "people_care") is None
