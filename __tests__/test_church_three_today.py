"""Today's routing at the three test churches (docs/CHURCH_LEADERS_MAP.md §5
PR 1, §6): the preservation baselines. Every later leaders PR runs these with
CHURCH_MAP closed and with it open on an empty map (filled=False), and both
must hold (rules c and d). With a filled map a church changes only where its
map says something.

Pinned, for each church: who can shepherd; the leaders room; where a card of
each stream goes; the chain above Youth's leader Y, and who Y's late task,
late youth follow-up (a day, three days) and drifting family (three Mondays)
reach; the money steps for $180, $250 and $600 and who gives each; the office
overseers; who a room request phones; the area each role sits in.

Where today is wrong for Grace or New Hope it is pinned anyway, marked WRONG
with the PR that changes it: that is what a baseline is."""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import church_duties as cd  # noqa: E402
import church_follow_up as cfu  # noqa: E402
import church_map as cm  # noqa: E402
import church_office_tasks as cot  # noqa: E402
import church_roles as cr  # noqa: E402
import church_shepherding as shep  # noqa: E402
import member_portal_messaging as mpm  # noqa: E402
from church_three import (CHURCHES, GRACE as GR, LOVE_CITY as LC, NAMES, NEW_HOPE as NH, build, church,  # noqa: E402
                          drift_told, late_follow_up, late_task, money, room_alerts)

Y = {LC: ("yolanda", "youth_pastor"), GR: ("yvette", "youth_minister"), NH: ("yusuf", "youth_pastor")}
ALL = pytest.mark.parametrize("biz", CHURCHES, ids=[NAMES[b] for b in CHURCHES])


@pytest.fixture(params=[(False, True), (True, True), (True, False)],
                ids=["map_off", "map_open_empty", "map_open_not_migrated"])
def db(request, monkeypatch):
    """Closed, open on an empty map, and open on a database without the
    map's migration (church_map.ready() false: every write leaves its
    columns out, every reader runs today's path)."""
    map_on, migrated = request.param
    return build(monkeypatch, map_on=map_on, filled=False, migrated=migrated)


def _names(db, ids):
    return sorted(db.label[str(i)] for i in ids)


# ─── Who shepherds ────────────────────────────────────────────────────

SHEPHERDING = {
    LC: ({"pastor": (True, None), "executive_pastor": (True, None), "associate_pastor": (True, None),
          "elders": (True, None), "ministers": (False, "ministers"), "prophets": (False, None)},
         ["Andre", "Jessica", "Kevin", "Marcus", "Tanya"]),
    # Grace's Deacon Board shepherds once its map flips can_shepherd (PR 4, test_church_map_switches);
    # on an empty map a care job's switch is off, as today.
    GR: ({"pastor": (True, None), "associate_ministers": (False, "ministers")}, ["Samuel"]),
    NH: ({"pastor": (True, None), "executive_pastor": (True, None), "associate_pastor": (True, None),
          "elders": (True, None), "ministers": (False, "ministers")},
         ["Abel", "Amara", "Asher", "Eden", "Elena", "Elliot", "Esther", "Ezra", "Nathan"]),
}


@ALL
def test_who_shepherds_today(db, biz):
    """Through the office's read and the shepherd's own (PR 4: where the map
    is open, the roles' switches decide; empty, they are today's rule)."""
    ctx = shep.load(biz)
    assert ({r["def"]["key"]: (r["shepherds"], r["switch"]) for r in ctx["roles"]},
            _names(db, ctx["shepherds"])) == SHEPHERDING[biz]
    assert _names(db, shep._member_ctx(biz)["shepherds"]) == SHEPHERDING[biz][1]


# ─── The leaders room ─────────────────────────────────────────────────

ROOM = {
    LC: ["Andre", "Angela", "Cora", "Eve", "Gloria", "Jessica", "Kevin", "Laquesha", "Marcus", "Minnie", "Naiya",
         "Paul", "Ruth", "Shapretta", "Tanya", "Tasha", "Tiara", "Tyrone", "Yolanda"],
    # Grace on a filled map (PR 4): Youth's overseer D1 (Daniel) is in; the Deacon Board leads only if
    # its can_lead is flipped, since nothing answers to it.
    GR: ["Samuel", "Sharon", "Thelma", "Yvette"],
    NH: ["Abel", "Amara", "Asher", "Celia", "Eden", "Elena", "Elliot", "Esther", "Ezra", "Kara", "Kira", "Mila",
         "Nathan", "Olive", "Owen", "Paige", "Sunny", "Tessa", "Wren", "Yusuf"],
}


@ALL
def test_the_leaders_room_today(db, biz):
    assert _names(db, (p["contact_id"] for p in mpm.leaders_room_people(biz))) == ROOM[biz]


# ─── Where a card goes ────────────────────────────────────────────────

ASK = {"baptism": ("baptism", []), "pastor_ask": ("connect", [{"q": "Anything else?", "a": "I’d like to talk with a pastor"}]),
       "care_need": ("connect", [{"q": "Anything else?", "a": "My mom is in the hospital"}]),
       "connect": ("connect", []), "visit": ("visit", []), "leftover": ("general", [])}
CHOOSE = {
    LC: {"baptism": ("Angela", "ministers", "Baptism cards go to the Ministers."),
         "pastor_ask": ("Marcus", "elders", "They asked to talk with a pastor."),
         "care_need": ("Andre", "associate_pastor", "Their card mentions a care need. Care needs go to the Associate Pastor."),
         "connect": ("Eve", "evangelists", "Connect cards go to the Evangelists."),
         "visit": ("Eve", "evangelists", "Plan your visit cards go to the Evangelists."),
         "leftover": ("Kevin", "pastor", "Cards without their own leader go to the senior pastor."),
         "Youth Ministry (YWD)": ("Tyrone", "team_leader", "They picked Youth Ministry (YWD), and Tyrone leads it."),
         "Hospitality Team": ("Tasha", "team_leader", "They picked Hospitality Team, and Tasha leads it."),
         "Graphic and web design": ("Andre", "associate_pastor",
                                    "Graphic and web design has no leader yet, so it goes to the Associate Pastor.")},
    GR: {"baptism": ("Samuel", "pastor", "No one holds a role that takes baptism cards yet. It’s with Samuel Gray until someone is named."),
         "pastor_ask": ("Samuel", "pastor", "They asked to talk with a pastor."),
         "care_need": ("Daniel", "deacons", "Their card mentions a care need. Care needs go to the Deacon Board."),
         "connect": ("Samuel", "pastor", "No one holds a role that takes connect cards yet. It’s with Samuel Gray until someone is named."),
         "visit": ("Samuel", "pastor", "No one holds a role that takes plan your visit cards yet. It’s with Samuel Gray until someone is named."),
         "leftover": ("Samuel", "pastor", "Cards without their own leader go to the senior pastor."),
         "Usher Board": ("Samuel", "pastor", "Usher Board has no leader yet. It’s with Samuel Gray until someone is named."),
         "Youth Ministry": ("Yvette", "youth_minister", "They picked Youth Ministry, which has no leader yet; it’s under the Youth Minister."),
         "Kitchen Committee": ("Samuel", "pastor", "Kitchen Committee has no leader yet. It’s with Samuel Gray until someone is named.")},
    NH: {"baptism": ("Nathan", "pastor", "No one holds a role that takes baptism cards yet. It’s with Nathan Cole until someone is named."),
         "pastor_ask": ("Eden", "elders", "They asked to talk with a pastor."),
         "care_need": ("Celia", "deacons", "Their card mentions a care need. Care needs go to the Deacons."),
         "connect": ("Nathan", "pastor", "No one holds a role that takes connect cards yet. It’s with Nathan Cole until someone is named."),
         "visit": ("Nathan", "pastor", "No one holds a role that takes plan your visit cards yet. It’s with Nathan Cole until someone is named."),
         "leftover": ("Nathan", "pastor", "Cards without their own leader go to the senior pastor."),
         "Worship Team": ("Wren", "worship_leader", "They picked Worship Team, which has no leader yet; it’s under the Worship Director."),
         "Youth Volunteers": ("Yusuf", "youth_pastor", "They picked Youth Volunteers, which has no leader yet; it’s under the Youth Director."),
         "Kids Check-in": ("Kara", "childrens_director", "They picked Kids Check-in, which has no leader yet; it’s under the Children’s Director."),
         "Guest Experience": ("Abel", "associate_pastor", "Guest Experience has no leader yet, so it goes to the Associate Pastor."),
         "Parking Team": ("Abel", "associate_pastor", "Parking Team has no leader yet, so it goes to the Associate Pastor.")},
}


@ALL
def test_where_each_card_goes_today(db, biz):
    """choose is handed the map as start() hands it (PR 4: made_for breaks
    the tie where it's open; empty, it is today's word)."""
    holders, defs, m = cfu.roles(biz), cr.defs(biz), cm.opened(biz)
    asks = dict(ASK, **{t: ("serve", [{"q": "Where would you like to serve?", "a": t}]) for t in cfu.teams(biz)})
    got = {}
    for label, (kind, answers) in asks.items():
        pick = cfu.choose(kind, answers, holders, {}, defs, m=m)
        got[label] = (db.label.get((pick["leader"] or {}).get("contact_id")), pick["role"], pick["reason"])
    assert got == CHOOSE[biz]


# ─── Late: the chain above Y, Y's task, Y's youth follow-up ───────────

LATE = {
    LC: ([("associate_pastor", ["Andre"]), ("pastor", ["Kevin"])], ["Andre"], [["Andre"], ["Kevin"]]),
    # WRONG for Grace (PR 6): Youth's overseer is deacon D1 (Daniel); today it skips to the Pastor, twice.
    GR: ([("pastor", ["Samuel"])], ["Samuel"], [["Samuel"], ["Samuel"]]),
    # WRONG for New Hope (PR 6): Youth's overseer is A2 (Amara); today every associate pastor is emailed.
    NH: ([("associate_pastor", ["Abel", "Amara", "Asher"]), ("pastor", ["Nathan"])], ["Abel", "Amara", "Asher"],
         [["Abel", "Amara", "Asher"], ["Nathan"]]),
}


@ALL
def test_late_work_climbs_the_chain_today(db, biz, monkeypatch):
    handle, key = Y[biz]
    holders = cfu.roles(biz)
    defs = cfu._effective_defs(cr.defs(biz), holders)
    above = cr.chain_above(cr.by_key(defs)[key], defs, cr.active_holders(holders), skip={db.who[biz][handle]})
    chain = [(d["key"], _names(db, (h["contact_id"] for h in hs))) for d, hs in above]
    assert (chain, late_task(monkeypatch, db, biz), late_follow_up(monkeypatch, db, biz)) == LATE[biz]


# ─── A drifting family, three Mondays ─────────────────────────────────

DRIFT = {
    LC: [["Marcus"], ["Kevin"], []],      # Marcus answers to Jessica on the map (PR 6)
    GR: [[], [], []],                     # D2 (Doris) shepherds them once the map flips it (PR 4; need 2)
    NH: [["Elena"], ["Nathan"], []],      # WRONG (PR 6): Elena answers to A2 (Amara)
}


@ALL
def test_a_drifting_family_is_told_up_the_chain_today(db, biz, monkeypatch):
    assert drift_told(monkeypatch, db, biz) == DRIFT[biz]


# ─── Money going out ──────────────────────────────────────────────────

T, P, B = "treasurer", "pastor", "board"
MONEY = {
    LC: ({18_000: [T], 25_000: [T], 60_000: [T, P]},
         {T: ["Minnie", "owner"], P: ["owner"], B: [], "board people": ["Marcus", "Tanya"]}),
    # Grace's $200 / $1,000, New Hope's $1,000 / $5,000 and its elders' board yes are its map's settings and
    # switches: on an empty map, the platform's $500 / $2,500 and the boards (PR 7, test_church_map_settings).
    GR: ({18_000: [T], 25_000: [T], 60_000: [T, P]}, {T: ["Thelma", "owner"], P: ["owner"], B: [], "board people": []}),
    NH: ({18_000: [T], 25_000: [T], 60_000: [T, P]}, {T: ["Tessa", "owner"], P: ["owner"], B: [], "board people": []}),
}


@ALL
def test_money_levels_today(db, biz):
    assert money(db, biz) == MONEY[biz]


# ─── The office's overseers, and a room request ───────────────────────

OFFICE = {
    LC: (["Jessica"], ["Jessica"], ["Minnie", "Naiya", "owner"]),  # Jessica holds Rooms but isn't phoned
    GR: ([], ["owner"], ["Sharon", "Thelma", "owner"]),
    # New Hope's Director of Operations (Owen) oversees the office once its map names the role (PR 7).
    NH: ([], ["owner"], ["Olive", "Owen", "Tessa", "owner"]),
}
# Where the map is open, empty too, a room request phones the rooms duty's holders (PR 7, member_asks.room_phones):
# Love City's Jessica holds Rooms (the Executive Pastor's lane). It is not a map setting, so it doesn't wait on one.
ROOMS_OPEN = {LC: ["Jessica", "Minnie", "Naiya", "owner"]}


@ALL
def test_the_office_overseers_and_who_a_room_request_phones_today(db, biz, monkeypatch):
    seats = cd._seats(biz)
    want = OFFICE[biz]
    if cm.opened(biz):
        want = (*want[:2], ROOMS_OPEN.get(biz, want[2]))
    assert (_names(db, cd._exec_users(biz, seats)), _names(db, cot.overseers(church(db, biz))),
            room_alerts(monkeypatch, db, biz)) == want


# ─── Where each role sits ─────────────────────────────────────────────

PEOPLE = ["pastor", "associate_pastor", "elders", "ministers", "intercessor_leader", "intercessors", "deacons",
          "care_team", "welcome_lead"]
PLACES = {
    LC: {"people_care": PEOPLE[:1] + ["executive_pastor"] + PEOPLE[1:4] + ["prophets"] + PEOPLE[4:],
         "worship_media": ["worship_leader"], "kids_youth": ["youth_pastor", "childrens_director"],
         None: ["team_leader"], "website_outreach": ["evangelists"], "groups_classes": ["class_teachers"],
         "office": ["administrator"], "giving_money": ["treasurer"]},
    GR: {"people_care": ["pastor", "associate_ministers", "intercessor_leader", "intercessors", "deacons", "deaconesses",
                         "mothers_board", "usher_board", "welcome_lead"],
         "worship_media": ["minister_of_music"], "kids_youth": ["youth_minister"], None: ["team_leader"],
         "groups_classes": ["sunday_school"], "giving_money": ["trustees", "treasurer"], "office": ["church_clerk"]},
    # The Director of Operations sits nowhere: its words say nothing and a ministry job has no area (PR 8).
    NH: {"people_care": PEOPLE[:1] + ["executive_pastor"] + PEOPLE[1:], "worship_media": ["worship_leader"],
         "kids_youth": ["youth_pastor", "childrens_director"], None: ["director_of_operations", "team_leader"],
         "groups_classes": ["class_teachers"], "office": ["administrator"], "giving_money": ["treasurer"]},
}


@ALL
def test_where_each_role_sits_today(db, biz):
    """Through places_for, as the areas read it (PR 8: where the map is open,
    each role's stored guess; empty, those are today's words)."""
    defs, got = cr.defs(biz), {}
    places = ca.places_for(biz, defs)
    for d in defs:
        got.setdefault(ca.place_role(d, places)["area"], []).append(d["key"])
    assert got == PLACES[biz]


# ─── The map the later PRs write ──────────────────────────────────────

def test_the_intended_map_names_only_each_churchs_own_people(monkeypatch):
    """filled=True keeps the map for PR 2 on; until then it changes nothing.
    Each department has one leader and one overseer, two people who hold an
    active role there; its duty is a real one; its serve options are on the
    church's card."""
    db = build(monkeypatch, filled=True)
    assert [len(db.map_intent[b]["departments"]) for b in CHURCHES] == [3, 1, 4]
    for b in CHURCHES:
        held = {h["contact_id"] for h in cfu.roles(b) if h["status"] == "active"}
        keys = {d["key"] for d in cr.defs(b)}
        m = db.map_intent[b]
        for d in m["departments"]:
            assert d["leader"] != d["overseer"] and {d["leader"], d["overseer"]} <= held, (b, d["name"])
            assert d["duty"] in cd.CATALOG and d["area"] in ca.AREAS
            assert {u[1] for u in d["units"] if u[0] == "serve_option"} <= set(cfu.teams(b))
            assert {u[1] for u in d["units"] if u[0] == "role"} <= keys
        assert set(m["answers_to"]) | set(m["answers_to"].values()) <= held
        assert set(m["roles"]) | set(m["settings"].get("office_overseer_roles", [])) <= keys
    assert build(monkeypatch, filled=False).map_intent == {}
