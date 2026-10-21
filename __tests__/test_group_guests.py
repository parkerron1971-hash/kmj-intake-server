# __tests__/test_group_guests.py
#
# First-time guests by name on a leader's roll (group_gatherings; the
# approved canvas "Church Groups, Together", board Roll). Pins:
#   1. only a leader, only on the day; a first name, a phone only if given
#   2. the guest count keeps up with the named guests (never below them)
#   3. a leader takes one off today's list; nobody else
#   4. the roll card lists them with Add guest; members never see them
#   5. exported, never re-imported

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_gatherings as gg
from test_group_gatherings import THURSDAY_NIGHT, _page, meet  # noqa: F401
from test_member_portal_group_space import BIZ, BUSINESS, G, MONIQUE, TASHA, _client, _me, fake  # noqa: F401

import pytest


@pytest.fixture
def night(meet):
    meet.t["group_meeting_guests"] = []
    meet.clock["now"] = THURSDAY_NIGHT
    return meet


def _add(who, first, phone=""):
    return gg.add_guest(BUSINESS, _me(who, "x"), G, first, phone)


def _meeting(fake):
    return fake.t["group_meetings"][0]


# ── 1. adding ────────────────────────────────────────────────────────

def test_a_leader_on_the_day(night):
    assert _add(TASHA, "  Ana  ", "(555) 010-0100 ext") == (True, "guest_added")
    g = night.t["group_meeting_guests"][0]
    assert (g["first_name"], g["phone"], g["added_by"], g["group_id"]) == ("Ana", "(555) 010-0100", TASHA, G)
    assert g["meeting_id"] == _meeting(night)["id"]


def test_only_a_leader_only_on_the_day(night):
    assert _add(MONIQUE, "Ana") == (False, "not_group_leader")
    night.clock["now"] = gg._now().__class__(2026, 10, 20, 14, 0, tzinfo=THURSDAY_NIGHT.tzinfo)   # Tuesday
    assert _add(TASHA, "Ana") == (False, "roll_closed")
    assert night.t["group_meeting_guests"] == []


def test_a_first_name_is_needed(night):
    assert _add(TASHA, "   ") == (False, "guest_empty")
    assert night.t["group_meeting_guests"] == []


# ── 2. the count ─────────────────────────────────────────────────────

def test_the_guest_count_keeps_up(night):
    _add(TASHA, "Ana")
    _add(TASHA, "Ben")
    assert _meeting(night)["visitors"] == 2
    assert gg.roll(BUSINESS, _me(TASHA, "x"), G, [TASHA], 0, "") == (True, "roll_saved")
    assert _meeting(night)["visitors"] == 2                     # never below the named guests
    gg.roll(BUSINESS, _me(TASHA, "x"), G, [TASHA], 5, "")
    assert _meeting(night)["visitors"] == 5                     # more who didn't give a name


# ── 3. taking one off ────────────────────────────────────────────────

def test_a_leader_takes_one_off(night):
    _add(TASHA, "Ana")
    gid = night.t["group_meeting_guests"][0]["id"]
    assert gg.remove_guest(BUSINESS, _me(MONIQUE, "x"), G, gid) == (False, "not_group_leader")
    assert len(night.t["group_meeting_guests"]) == 1
    assert gg.remove_guest(BUSINESS, _me(TASHA, "x"), G, gid) == (True, "guest_removed")
    assert night.t["group_meeting_guests"] == []


# ── 4. the card ──────────────────────────────────────────────────────

def test_the_roll_card(night):
    _add(TASHA, "Ana", "555-0100")
    html = _page(TASHA)
    assert "First-time guests" in html and "<b>Ana</b>" in html and "Phone saved" in html
    assert 'action="/my/groups/meet/guest"' in html and "Add a phone only if they said yes" in html
    member = _page(MONIQUE)
    assert "First-time guests" not in member and "Ana" not in member


def test_the_routes(night, monkeypatch):
    c = _client(monkeypatch, _me(TASHA, "Tasha"))
    r = c.post("/my/groups/meet/guest", data={"group_id": G, "first": "Ana", "phone": ""})
    assert r.headers["location"] == f"/my/groups/{G}/meet?done=guest_added"
    gid = night.t["group_meeting_guests"][0]["id"]
    r = c.post("/my/groups/meet/guest/remove", data={"group_id": G, "guest": gid})
    assert r.headers["location"] == f"/my/groups/{G}/meet?done=guest_removed"


def test_a_failed_read_never_shows_an_empty_list(night):
    _add(TASHA, "Ana")
    night.fail.add("group_meeting_guests")
    assert "Gatherings couldn’t load" in _page(TASHA)


# ── 5. words and the export ──────────────────────────────────────────

def test_words_and_the_export():
    import account_lifecycle as al
    import member_portal_church as mpc
    assert {"guest_added", "guest_removed"} <= set(mpc.DONE) and "guest_empty" in mpc.ERRORS
    t = al.BUSINESS_CHILD_TABLES
    assert t.index("group_meeting_guests") < t.index("group_meetings") < t.index("contacts")
    assert "group_meeting_guests" in al._IMPORT_SKIP
