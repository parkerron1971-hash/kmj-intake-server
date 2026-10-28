# __tests__/test_group_bring.py
#
# "Bring something" (group_bring.py on the group page's Meet tab; the
# approved canvas "Church Groups, Together", boards Meet and Main). Pins:
#   1. only a group's leaders add to a list, only for a coming gathering,
#      and each thing is checked like a Board post first
#   2. "I'll bring it": people in the group, one open thing each, never a
#      thing someone else holds (even when two taps race); someone who left
#      the group no longer holds anything
#   3. Undo is only your own; a leader takes things off
#   4. the Meet tab: "2 still open" / "All covered", I'll bring it / Undo,
#      nothing for a member when no list is out, the Home card's line
#   5. the 5 PM reminder tells each person what they're bringing, once

import asyncio
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_bring as gb
import group_gatherings as gg
import msg_screen
from test_group_gatherings import _at, _g, _page, meet  # noqa: F401
from test_member_portal_group_space import (BIZ, BUSINESS, G, MONIQUE, ROCHELLE, TASHA, TEEN,  # noqa: F401
                                            _client, _me, fake)


@pytest.fixture
def bring(meet, monkeypatch):
    meet.t["group_bring"] = []
    meet.screened = []

    async def screen(business_id, text):
        meet.screened.append(text)
        if meet.screen == "down":
            raise msg_screen.ScreenUnavailable()
        return meet.screen
    meet.screen = "ok"
    monkeypatch.setattr(msg_screen, "screen", screen)
    return meet


def _add(who, what, day=""):
    return asyncio.run(gb.add(BUSINESS, _me(who, "x"), G, day, what))


def _items(fake):
    return [(i["what"], i["met_on"], i.get("contact_id")) for i in fake.t["group_bring"]]


def _id(fake, what):
    return next(i["id"] for i in fake.t["group_bring"] if i["what"] == what)


# ── 1. adding ────────────────────────────────────────────────────────

def test_a_leader_adds_to_the_next_gathering_or_a_later_one(bring):
    assert _add(TASHA, "  Main   dish ") == (True, "bring_added")
    assert _add(TASHA, "Dessert", "2026-11-19") == (True, "bring_added")
    assert _items(bring) == [("Main dish", "2026-10-22", None), ("Dessert", "2026-11-19", None)]
    assert bring.screened == ["Main dish", "Dessert"]          # checked like a Board post
    assert bring.t["group_bring"][0]["added_by"] == TASHA


def test_only_a_leader_and_only_for_a_coming_gathering(bring):
    assert _add(MONIQUE, "Greens") == (False, "not_group_leader")
    assert _add(ROCHELLE, "Greens") == (False, "not_in_group")
    assert _add(TASHA, "Greens", "2026-10-15") == (False, "no_gathering")      # already happened
    assert _add(TASHA, "Greens", "2026-10-23") == (False, "no_gathering")      # not a gathering day
    _g(bring)["meet_skips"] = ["2026-10-29"]
    assert _add(TASHA, "Greens", "2026-10-29") == (False, "no_gathering")      # skipped
    assert _add(TASHA, "   ") == (False, "bring_empty")
    _g(bring).update(meet_day=None, meet_time=None)
    assert _add(TASHA, "Greens") == (False, "no_gathering")
    assert bring.t["group_bring"] == []


def test_nothing_goes_up_unchecked(bring):
    bring.screen = "harm"
    assert _add(TASHA, "something cruel") == (False, "post_no")
    bring.screen = "down"
    assert _add(TASHA, "Drinks") == (False, "post_busy")
    assert bring.t["group_bring"] == []


def test_a_list_has_room_for_thirty(bring):
    bring.t["group_bring"] = [{"id": f"bbbbbbbb-0000-0000-0000-{n:012d}", "business_id": BIZ, "group_id": G,
                               "met_on": "2026-10-22", "what": f"Thing {n}", "contact_id": None} for n in range(30)]
    assert _add(TASHA, "One more") == (False, "bring_full")


# ── 2. I'll bring it ─────────────────────────────────────────────────

def test_one_open_thing_each(bring):
    _add(TASHA, "Main dish")
    _add(TASHA, "Dessert")
    assert gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Dessert")) == (True, "bring_claimed")
    assert gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Dessert")) == (True, "bring_claimed")       # again: fine
    assert gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Main dish")) == (False, "bring_one_each")
    assert gb.claim(BUSINESS, _me(TEEN, "x"), G, _id(bring, "Dessert")) == (False, "bring_taken")
    assert gb.claim(BUSINESS, _me(ROCHELLE, "x"), G, _id(bring, "Main dish")) == (False, "not_in_group")
    assert _items(bring) == [("Main dish", "2026-10-22", None), ("Dessert", "2026-10-22", MONIQUE)]


def test_one_each_is_per_gathering(bring):
    _add(TASHA, "Dessert")
    _add(TASHA, "Drinks", "2026-10-29")
    gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Dessert"))
    assert gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Drinks")) == (True, "bring_claimed")


def test_two_taps_at_once_never_take_it_from_someone(bring, monkeypatch):
    _add(TASHA, "Dessert")
    stale = dict(bring.t["group_bring"][0])                 # what Monique's tap read
    bring.t["group_bring"][0]["contact_id"] = TEEN         # Kayla got there first
    monkeypatch.setattr(gb, "_item", lambda *a: stale)
    assert gb.claim(BUSINESS, _me(MONIQUE, "x"), G, stale["id"]) == (False, "bring_taken")
    assert bring.t["group_bring"][0]["contact_id"] == TEEN


def test_someone_who_left_no_longer_holds_it(bring):
    _add(TASHA, "Dessert")
    bring.t["group_bring"][0]["contact_id"] = ROCHELLE     # not in the group (any more)
    assert gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Dessert")) == (True, "bring_claimed")
    assert bring.t["group_bring"][0]["contact_id"] == MONIQUE


def test_a_past_gathering_is_closed(bring):
    _add(TASHA, "Dessert")
    bring.clock["now"] = _at(2026, 10, 23, 9)              # the morning after
    assert gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Dessert")) == (False, "bring_gone")
    assert gb.claim(BUSINESS, _me(MONIQUE, "x"), G, "bbbbbbbb-0000-0000-0000-000000000999") == (False, "bring_gone")


# ── 3. undo and remove ───────────────────────────────────────────────

def test_undo_is_only_your_own(bring):
    _add(TASHA, "Dessert")
    gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Dessert"))
    assert gb.unclaim(BUSINESS, _me(TEEN, "x"), G, _id(bring, "Dessert")) == (True, "bring_undone")
    assert bring.t["group_bring"][0]["contact_id"] == MONIQUE
    assert gb.unclaim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Dessert")) == (True, "bring_undone")
    assert bring.t["group_bring"][0]["contact_id"] is None


def test_only_a_leader_takes_things_off(bring):
    _add(TASHA, "Dessert")
    assert gb.remove(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Dessert")) == (False, "not_group_leader")
    assert len(bring.t["group_bring"]) == 1
    assert gb.remove(BUSINESS, _me(TASHA, "x"), G, _id(bring, "Dessert")) == (True, "bring_removed")
    assert bring.t["group_bring"] == []


# ── 4. the Meet tab ──────────────────────────────────────────────────

def test_the_list_on_the_meet_tab(bring):
    for what in ("Main dish", "Greens", "Dessert"):
        _add(TASHA, what)
    gb.claim(BUSINESS, _me(TASHA, "x"), G, _id(bring, "Main dish"))
    html = _page(MONIQUE)
    assert "Bring something" in html and "2 still open" in html
    assert html.count("I’ll bring it</button>") == 2 and "Tasha" in html and "Nobody yet" in html
    assert 'action="/my/groups/meet/bring/remove"' not in html and 'action="/my/groups/meet/bring/add"' not in html
    gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Greens"))
    html = _page(MONIQUE)
    assert "I’ll bring it</button>" not in html                 # one each: the rest stay for others
    assert ">Undo</button>" in html and "<small>You</small>" in html and "1 still open" in html
    gb.claim(BUSINESS, _me(TEEN, "x"), G, _id(bring, "Dessert"))
    assert "All covered" in _page(MONIQUE)


def test_a_member_sees_nothing_until_a_list_is_out(bring):
    assert "Bring something" not in _page(MONIQUE)
    leader = _page(TASHA)
    assert "Sharing a meal?" in leader and 'action="/my/groups/meet/bring/add"' in leader
    assert "<option value=\"2026-11-19\">Thu, Nov 19</option>" in leader               # a later gathering can be planned for


def test_a_leader_can_take_things_off_and_add_more(bring):
    _add(TASHA, "Dessert")
    html = _page(TASHA)
    assert 'action="/my/groups/meet/bring/remove"' in html and 'action="/my/groups/meet/bring/add"' in html
    assert "Sharing a meal?" not in html


def test_a_later_gatherings_list_says_which_day(bring):
    _add(TASHA, "Dessert", "2026-11-19")
    html = _page(MONIQUE)
    assert "For Thursday, November 19" in html and "1 still open" in html


def test_home_says_whats_still_open(bring):
    _add(TASHA, "Dessert")
    _add(TASHA, "Drinks", "2026-10-29")
    html = _page(MONIQUE, "")
    assert "Bring something · 1 still open" in html


def test_a_failed_read_never_shows_an_empty_list(bring):
    bring.fail.add("group_bring")
    assert "Gatherings couldn’t load" in _page(MONIQUE)


# ── 5. the reminder ──────────────────────────────────────────────────

def test_the_reminder_says_what_youre_bringing(bring, monkeypatch):
    import member_push
    sent = []
    monkeypatch.setattr(member_push, "send", lambda biz, kind, **k: sent.append(k) or 1)
    _add(TASHA, "Dessert")
    gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Dessert"))
    assert gg.reminders(BUSINESS, _at(2026, 10, 22, 17)) == 2
    mine = next(k for k in sent if k["contact_ids"] == [MONIQUE])
    assert mine["body"].endswith("· You’re bringing Dessert") and mine["ref_id"] == f"gathering:{G}:2026-10-22:{MONIQUE}"
    rest = next(k for k in sent if k["ref_id"] == f"gathering:{G}:2026-10-22")
    assert sorted(rest["contact_ids"]) == sorted([TASHA, TEEN]) and "bringing" not in rest["body"]


def test_a_later_tick_sends_nobody_a_second_one(bring, monkeypatch):
    import member_push
    sent = []
    monkeypatch.setattr(member_push, "send", lambda biz, kind, **k: sent.append(k) or 1)
    bring.t["member_push_sends"] = [{"business_id": BIZ, "kind": "groups", "ref_id": f"gathering:{G}:2026-10-22", "id": "s1"}]
    _add(TASHA, "Dessert")
    gb.claim(BUSINESS, _me(MONIQUE, "x"), G, _id(bring, "Dessert"))    # picked after 5 PM's went out
    assert gg.reminders(BUSINESS, _at(2026, 10, 22, 17, 30)) == 0 and sent == []


# ── the routes and the export ────────────────────────────────────────

def test_routes_land_back_on_meet(bring, monkeypatch):
    c = _client(monkeypatch, _me(TASHA, "Tasha"))
    r = c.post("/my/groups/meet/bring/add", data={"group_id": G, "what": "Dessert"})
    assert r.headers["location"] == f"/my/groups/{G}/meet?done=bring_added"
    r = _client(monkeypatch, _me(MONIQUE, "Monique")).post(
        "/my/groups/meet/bring/claim", data={"group_id": G, "item": _id(bring, "Dessert")})
    assert r.headers["location"] == f"/my/groups/{G}/meet?done=bring_claimed"
    r = _client(monkeypatch, _me(MONIQUE, "Monique")).post("/my/groups/meet/bring/claim", data={"group_id": G, "item": "x"})
    assert r.headers["location"] == f"/my/groups/{G}/meet?err=bring_gone"


def test_every_code_has_words():
    import member_portal_church as mpc
    for code in ("bring_added", "bring_removed", "bring_claimed", "bring_undone"):
        assert code in mpc.DONE
    for code in ("bring_empty", "bring_full", "bring_gone", "bring_taken", "bring_one_each"):
        assert code in mpc.ERRORS


def test_lists_are_in_the_export_and_never_reimported():
    import account_lifecycle as al
    t = al.BUSINESS_CHILD_TABLES
    assert t.index("group_bring") < t.index("groups") < t.index("contacts")
    assert "group_bring" in al._IMPORT_SKIP
