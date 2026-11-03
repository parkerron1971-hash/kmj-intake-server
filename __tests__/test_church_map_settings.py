"""Settings take effect; room asks go to the rooms duty (docs/CHURCH_LEADERS_MAP.md
§3, §5 PR 7). Where a church's map is open (church_map.opened): its money
levels (null is the platform's $500 / $2,500), who gives the pastor's yes
(pastor_yes_roles; none named is the owner), every board-yes role holder as a
board member, and the roles that oversee the office (office_overseer_roles);
and a room request phones the rooms duty's holders.

The scenario test holds needs 1 and 3 at all three churches, and
test_church_three_today every baseline closed, open and empty, and before the
migration. Here: Love City with its settings unset is today's; Grace's and New
Hope's levels; the pastor's yes narrowed, and none named; a board-yes holder's
yes, by their person and by a login; New Hope's office overseer; the rooms
duty decides who is phoned; a filled map, closed, is today's; a failed map
read is a failed read."""
from __future__ import annotations

import os
import sys

import pytest
from fastapi import HTTPException

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_checks  # noqa: E402
import church_duties as cd  # noqa: E402
import church_map as cm  # noqa: E402
import church_money_levels as cml  # noqa: E402
import church_office_tasks as cot  # noqa: E402
import member_portal_board as mpb  # noqa: E402
from church_three import (CHURCHES, GRACE as GR, LOVE_CITY as LC, NAMES, NEW_HOPE as NH, build, church,  # noqa: E402
                          money, money_me, room_alerts, uid)
from test_church_three_today import MONEY, OFFICE, ROOMS_OPEN  # noqa: E402

T, P, B = "treasurer", "pastor", "board"
TODAY_WORDS = ("The money levels say who says yes: the treasurer, the pastor too from $500, and a board member "
               "too over $2,500. The limit and the Giving keeper don't decide while they're on.")


def _names(db, ids):
    return sorted(db.label[str(i)] for i in ids)


def _owner_me(db, biz):
    b = church(db, biz)
    return money_me(db, biz, b["owner_id"], "owner", "")


def _settings(db, biz, **said):
    next(s for s in db.t["church_role_settings"] if s["business_id"] == biz).update(said)


def _rid(db, biz, key):
    return next(d["id"] for d in db.t["church_role_defs"] if d["business_id"] == biz and d["key"] == key)


def _office(db, biz):
    return (_names(db, cd._exec_users(biz, cd._seats(biz))), _names(db, cot.overseers(church(db, biz))))


# ─── Love City, its settings unset ────────────────────────────────────

@pytest.mark.parametrize("filled", [False, True], ids=["empty", "filled"])
def test_love_citys_money_and_office_overseers_with_its_settings_unset_are_the_baseline(monkeypatch, filled):
    db = build(monkeypatch, filled=filled)
    m = cm.opened(LC)
    assert m and m.settings["pastor_from_cents"] is m.settings["board_over_cents"] is None
    assert m.settings["pastor_yes_roles"] is None
    assert money(db, LC) == MONEY[LC]
    assert _office(db, LC) == OFFICE[LC][:2]
    me = _owner_me(db, LC)
    assert cml.levels_of(me) == (cml.PASTOR_FROM_CENTS, cml.BOARD_OVER_CENTS)
    assert church_checks.levels_on(me) == TODAY_WORDS
    view = cml.page_view(me)
    assert (view["pastor_from_cents"], view["board_over_cents"]) == (50_000, 250_000)


# ─── The church's own levels ──────────────────────────────────────────

def test_grace_and_new_hope_ask_their_own_levels(monkeypatch):
    db = build(monkeypatch)
    for biz, levels, words, needs in (
            (GR, (20_000, 100_000), ("from $200", "over $1,000"),
             {18_000: [T], 25_000: [T, P], 60_000: [T, P]}),
            (NH, (100_000, 500_000), ("from $1,000", "over $5,000"),
             {18_000: [T], 25_000: [T], 60_000: [T]})):
        me = _owner_me(db, biz)
        assert cml.levels_of(me) == levels
        assert money(db, biz)[0] == needs, NAMES[biz]
        view = cml.page_view(me)
        assert (view["pastor_from_cents"], view["board_over_cents"]) == levels
        assert all(w in church_checks.levels_on(me) for w in words)
    assert cml.required(100_000, levels=(20_000, 100_000)) == [T, P]
    assert cml.required(100_001, levels=(20_000, 100_000)) == [T, P, B]
    assert cml.required(600_000, levels=(100_000, 500_000)) == [T, P, B]
    assert cml.required(99_999, over_budget=True, levels=(100_000, 500_000)) == [T, B]


# ─── Who gives the pastor's yes ───────────────────────────────────────

def test_pastor_yes_roles_narrows_who_gives_the_pastors_yes(monkeypatch):
    """New Hope names its Director of Operations: Owen's login gives it, and
    the Senior Pastor's (the owner's) no longer does."""
    db = build(monkeypatch)
    assert money(db, NH)[1][P] == ["owner"]
    _settings(db, NH, pastor_yes_roles=[_rid(db, NH, "director_of_operations")])
    assert money(db, NH)[1][P] == ["Owen"]
    assert [p["name"] for p in cml.pastors(_owner_me(db, NH))] == ["Owen Diaz"]


def test_none_named_falls_back_to_the_owner(monkeypatch):
    """'{}' (or roles since archived): the owner's login gives the pastor's
    yes, even where the senior role's holder has no login."""
    db = build(monkeypatch)
    nathan = next(c for c in db.t["contacts"] if c["id"] == db.who[NH]["nathan"])
    nathan["email"] = "nathan.cole@newhope.church"      # no login by the Senior Pastor's email now
    assert money(db, NH)[1][P] == []
    _settings(db, NH, pastor_yes_roles=[])
    assert money(db, NH)[1][P] == ["owner"]
    assert cml.pastors(_owner_me(db, NH)) == [{"name": "Pastor Nathan", "email": "nathan@newhope.church",
                                               "logins": [church(db, NH)["owner_id"]]}]
    gone = _rid(db, NH, "director_of_operations")
    next(d for d in db.t["church_role_defs"] if d["id"] == gone)["status"] = "archived"
    _settings(db, NH, pastor_yes_roles=[gone])
    assert money(db, NH)[1][P] == ["owner"]


# ─── A board-yes role ─────────────────────────────────────────────────

def test_a_board_yes_role_holder_gives_the_boards_yes_and_sees_the_approvals(monkeypatch):
    """New Hope's elders sit on no board: their role's board-yes switch gives
    them the board's step, from the member app by their person and from an
    office login by its email. Closed, they are nobody's board."""
    db = build(monkeypatch)
    assert money(db, NH)[1]["board people"] == ["Eden", "Elena", "Elliot", "Esther", "Ezra"]
    rid = "5f000000-0000-4000-8000-000000000001"
    db.t["church_check_requests"] = [{
        "id": rid, "business_id": NH, "status": "new", "amount_cents": 600_000, "payee": "Camp Pinewood",
        "ministry": "Youth", "about": "Summer camp", "contact_id": None, "asker_name": "", "source": "office",
        "created_by": db.who[NH]["tessa@"], "created_at": "2026-10-28T15:00:00+00:00"}]
    db.t["church_check_approvals"].append({"id": "a1", "business_id": NH, "request_id": rid, "step": T,
                                           "user_id": db.who[NH]["tessa@"], "contact_id": None,
                                           "created_at": "2026-10-28T16:00:00+00:00"})
    elena = {"id": db.who[NH]["elena"], "name": "Elena Ruiz", "email": "elena@newhope.church"}
    view = cml.member_view(church(db, NH), elena)
    assert [x["row"]["id"] for x in view["waiting"]] == [rid]
    lv = view["waiting"][0]["levels"]
    assert (lv["needs"], lv["missing"], lv["mine"]) == ([T, P, B], [P, B], "board")
    assert view["board_over_cents"] == 500_000 and "Over $5,000" in mpb._money_door(0, view["board_over_cents"])
    ezra = uid(3, 9)
    db.t["business_users"].append({"business_id": NH, "user_id": ezra, "role": "viewer", "status": "active",
                                   "invited_email": "ezra@newhope.church", "lane": None, "areas": None,
                                   "contact_id": None, "name": "Ezra Kim"})
    db.label[ezra] = "Ezra"
    assert cml.steps_of(money_me(db, NH, ezra, "viewer", "ezra@newhope.church")) == {B}
    assert money(db, NH)[1][B] == ["Ezra"]
    monkeypatch.setenv("CHURCH_MAP", "off")
    with pytest.raises(HTTPException) as e:
        cml.member_view(church(db, NH), elena)
    assert e.value.status_code == 403
    assert money(db, NH)[1][B] == [] and money(db, NH)[1]["board people"] == []


# ─── Who oversees the office ──────────────────────────────────────────

def test_new_hopes_director_of_operations_oversees_the_office_through_the_setting(monkeypatch):
    db = build(monkeypatch)
    assert _office(db, NH) == (["Owen"], ["Owen"])
    assert cd.EXEC in cd.standing(NH, db.who[NH]["owen@"])["lanes"]
    _settings(db, NH, office_overseer_roles=[])           # none named: nobody, so the owner hears
    assert _office(db, NH) == ([], ["owner"])
    _settings(db, LC, office_overseer_roles=None)         # never set: today's rule, the Executive Pastor role
    assert _office(db, LC) == (["Jessica"], ["Jessica"])
    _settings(db, LC, office_overseer_roles=[_rid(db, LC, "associate_pastor")])
    assert _office(db, LC) == ([], ["owner"]), "Andre has no login: nobody, so the owner"


# ─── A room request ───────────────────────────────────────────────────

ALL = pytest.mark.parametrize("biz", CHURCHES, ids=[NAMES[b] for b in CHURCHES])
MOVED_TO = {LC: "laquesha", GR: "sharon", NH: "sunny"}
PHONED = {LC: ["Laquesha", "Minnie", "owner"], GR: ["Sharon", "Thelma", "owner"], NH: ["Sunny", "Tessa", "owner"]}


@ALL
def test_a_room_request_phones_only_the_rooms_dutys_holders(monkeypatch, biz):
    """The rooms duty moved to one Manager: the owner, the admins and her,
    never another login that works the office, nor People & Care."""
    db = build(monkeypatch)
    b = church(db, biz)
    cd.move(b, "rooms", [db.who[biz][MOVED_TO[biz] + "@"]], b["owner_id"])
    got = room_alerts(monkeypatch, db, biz)
    assert got == _names(db, cd.holders_of(biz, "rooms")) == PHONED[biz]
    assert not {"Tiara", "Paige", "Naiya", "Olive", "Jessica", "Owen"} & set(got)


def test_who_holds_a_duty_reads_the_map_once_for_every_manager(monkeypatch):
    """#1717 review: each Manager's standing reads overseer_keys (and, with
    no lane, its areas), which load the map; one holders_of call, a room
    request and the duties page each load it once."""
    import church_areas as ca
    import member_asks
    db = build(monkeypatch)
    loads, real = [], cm.load
    monkeypatch.setattr(cm, "load", lambda biz: loads.append(str(biz)) or real(biz))
    for biz, ask in ((LC, lambda: cd.holders_of(LC, "rooms")), (NH, lambda: cd.holders_of(NH, "rooms")),
                     (LC, lambda: member_asks.room_phones(LC)), (LC, lambda: cd.build(church(db, LC)))):
        cd._CACHE.clear()
        ca._MY_CACHE.clear()
        loads.clear()
        ask()
        assert loads == [biz], (NAMES[biz], len(loads))
    assert len([s for s in db.t["business_users"] if s["business_id"] == NH and s["role"] == "manager"]) == 6
    assert _names(db, member_asks.room_phones(LC)) == ROOMS_OPEN[LC]


# ─── The switch, a failed read ────────────────────────────────────────

@pytest.mark.parametrize("mode", ["off", "owner"])
def test_a_filled_map_closed_keeps_every_baseline(monkeypatch, mode):
    """Owner opens Love City alone, whose settings are unset: only its room
    request changes, to the rooms duty."""
    db = build(monkeypatch)
    monkeypatch.setenv("CHURCH_MAP", mode)
    for biz in CHURCHES:
        office = OFFICE[biz]
        if mode == "owner" and biz == LC:
            office = (*office[:2], ROOMS_OPEN[LC])
        got = (money(db, biz), (*_office(db, biz), room_alerts(monkeypatch, db, biz)))
        assert got == (MONEY[biz], office), (mode, NAMES[biz])
        assert church_checks.levels_on(_owner_me(db, biz)) == TODAY_WORDS


def test_a_failed_map_read_is_a_failed_read(monkeypatch):
    """Never today's people: the money levels and the duties are a 503; a
    late office task and a room request go to the owner alone, as a failed
    read there always has."""
    db = build(monkeypatch)
    monkeypatch.setattr(cm, "load", lambda biz: None)
    for read in (lambda: money(db, NH), lambda: cd._exec_users(LC, cd._seats(LC)),
                 lambda: cml.member_view(church(db, NH), {"id": db.who[NH]["elena"], "email": "elena@newhope.church"})):
        with pytest.raises(HTTPException) as e:
            read()
        assert e.value.status_code == 503
    assert _names(db, cot.overseers(church(db, LC))) == ["owner"]
    assert room_alerts(monkeypatch, db, LC) == ["owner"]
