"""Step 2's baseline (docs/CHURCH_LEADERS_STEP2.md §0.1, §6, §7 B1): what
today's code does at the fourth test church, Riverside, and that the three
churches' baselines hold with CHURCH_SETUP on.

Riverside (church_three) is an AME church of 60 people that nobody has set
up. It has no role settings row, no roles and no holders, its owner is not the
platform owner, and it was never seeded. Pinned, as test_church_three_today
pins the three, with the map closed, open on an empty map, and open before the
map's migration:
- what its first open does: it fills the library with the guessed type's
  titles, every one ACTIVE (B7 changes that, behind CHURCH_SETUP);
- which reads fill the library and which never do;
- before the first open and after it: the leaders room, where a card goes,
  the money steps and who gives the pastor's yes, the Shepherding page and
  where each role sits.

CHURCH_SETUP is unset, off or owner for Riverside here. B7 changes Riverside
only where it is on: under owner it opens only to the platform owner's own
church (§0.3), and Riverside's owner isn't the platform owner.

The three churches run every baseline in test_church_three_today, and their
library(), with CHURCH_SETUP=on. No code reads it yet, so this pins that
nothing changes for them when later PRs add it (§6)."""
from __future__ import annotations

import inspect
import os
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_areas as ca  # noqa: E402
import church_follow_up as cfu  # noqa: E402
import church_map as cm  # noqa: E402
import church_roles as cr  # noqa: E402
import church_shepherding as shep  # noqa: E402
import member_portal_messaging as mpm  # noqa: E402
import test_church_three_today as today  # noqa: E402
from church_three import (CHURCHES, FOUR, LOVE_CITY as LC, NAMES, OWNER_EMAIL, PLATFORM, R_OWNER,  # noqa: E402
                          RIVERSIDE as RV, build, church, money)

MODES = [(False, True), (True, True), (True, False)]
MODE_IDS = ["map_off", "map_open_empty", "map_open_not_migrated"]


@pytest.fixture(params=MODES, ids=MODE_IDS)
def mode(request):
    return request.param


@pytest.fixture(params=[None, "off", "owner"], ids=["setup_unset", "setup_off", "setup_owner"])
def db(request, monkeypatch, mode):
    """The four churches, Riverside as nobody has set it up. CHURCH_SETUP is
    every value but on: none of them may change Riverside (B7)."""
    if request.param is None:
        monkeypatch.delenv("CHURCH_SETUP", raising=False)
    else:
        monkeypatch.setenv("CHURCH_SETUP", request.param)
    map_on, migrated = mode
    return build(monkeypatch, map_on=map_on, filled=False, migrated=migrated)


def _mine(db, table):
    return [r for r in db.t.get(table, []) if r.get("business_id") == RV]


def _first_open(db):
    """The office opens Leaders & roles for the first time."""
    assert cr.library(church(db, RV)) is not None


# ─── Riverside, as nobody has set it up ───────────────────────────────

def test_riverside_is_a_church_nobody_has_set_up(db):
    b = church(db, RV)
    assert (b["name"], b["type"], b["owner_id"]) == ("Riverside AME Church", "ministry", R_OWNER)
    assert OWNER_EMAIL[R_OWNER] != PLATFORM and RV in FOUR and RV not in CHURCHES
    assert [len(_mine(db, t)) for t in ("contacts", "households", "household_adults")] == [60, 20, 40]
    assert not [t for t in ("church_role_settings", "church_role_defs", "church_leader_roles", "church_area_places",
                            "business_users", "church_departments", "church_department_units", "church_shepherds",
                            "intake_forms", "groups", "church_boards")
                if _mine(db, t)], "nothing is set up"
    assert cr.settings(RV) == {} and cr.defs(RV, with_drafts=True) == []
    # Its type is Chief's guess from its name; nothing stores it yet.
    assert cr.guess_type(b["name"], []) == ("ame", "Your name says Methodist.")


def test_under_the_default_switch_riverside_has_no_map(monkeypatch):
    """CHURCH_MAP=owner (the default) opens the map to the platform owner's
    login and church alone: Love City, never Riverside."""
    build(monkeypatch, filled=False)
    monkeypatch.setenv("CHURCH_MAP", "owner")
    assert (cm.church_open(RV), cm.opened(RV), cm.open_to(SimpleNamespace(email=OWNER_EMAIL[R_OWNER]))) == \
        (False, False, False)
    assert cm.church_open(LC) and cm.open_to(SimpleNamespace(email=PLATFORM))


# ─── Its first open ───────────────────────────────────────────────────

AME = ["pastor", "associate_ministers", "stewards", "intercessor_leader", "intercessors", "stewardesses",
       "class_leaders", "missionary_society", "minister_of_music", "ypd_director", "team_leader", "welcome_lead",
       "church_school", "trustees"]
HANDLES = {"pastor": ["leftover", "pastor_ask"], "associate_ministers": ["pastor_ask", "baptism"],
           "stewards": ["pastor_ask"], "intercessor_leader": ["prayer_shared"], "intercessors": ["prayer_passed"],
           "stewardesses": ["care_need"], "class_leaders": ["care_need"], "missionary_society": ["care_need"],
           "minister_of_music": ["serve"], "ypd_director": ["serve"], "team_leader": ["serve"],
           "welcome_lead": ["visit", "connect"], "church_school": [], "trustees": []}
# Chief's area guesses, stored as the roles are made where the map is open (step 1 PR 8). WRONG for
# Riverside: its "Prayer band" is the prayer team, but "band" reads as music (worship_media). No step 2 PR
# changes the words; the church's own pick on the areas page does, and is kept.
GUESSES = {"pastor": ("people_care", "pastor"), "associate_ministers": ("people_care", "ministers"),
           "class_leaders": ("groups_classes", "class"), "intercessor_leader": ("people_care", "prayer"),
           "intercessors": ("worship_media", "band"), "minister_of_music": ("worship_media", "music"),
           "welcome_lead": ("people_care", "hospitality"), "trustees": ("giving_money", "trustees")}


def test_the_first_open_fills_the_library_with_the_ame_titles_all_active_today(db, mode):
    """ensure_library on a church never seeded: Chief's guess at its type
    from its name, and that type's titles, each ACTIVE, from the catalog,
    with today's switches. B7 changes this behind CHURCH_SETUP: a new church
    (no seeded_at, no role row in any status, no holder row) gets the same
    rows as drafts (status 'draft', source 'template'), seeded_as 'draft',
    and no office overseer until it confirms (§6)."""
    map_on, migrated = mode
    st = cr.ensure_library(church(db, RV))
    assert {k: st.get(k) for k in ("church_type", "guessed_type", "guess_reason", "set_by", "office_overseer_roles")} \
        == {"church_type": "ame", "guessed_type": "ame", "guess_reason": "Your name says Methodist.",
            "set_by": "chief", "office_overseer_roles": None}            # no AME title oversees the office
    assert st.get("seeded_at") and len(_mine(db, "church_role_settings")) == 1
    defs = cr.defs(RV, with_drafts=True)
    assert [d["key"] for d in defs] == AME
    rows = {r["key"]: r for r in cr.TYPES["ame"]["rows"]}
    assert {d["key"]: (d["title"], d["job"], d["status"], d["source"], d["catalog_key"]) for d in defs} == \
        {k: (r["title"], r["job"], "active", "catalog", k) for k, r in rows.items()}
    assert {d["key"]: d["handles"] for d in defs} == HANDLES
    assert all(d["oversees_teams"] == [] for d in defs), "no Serve card, so no team under anyone"
    ids = {d["id"]: d["key"] for d in defs}
    assert {d["key"]: ids.get(d["reports_to"]) for d in defs} == \
        dict({k: "pastor" for k in AME}, pastor=None, intercessors="intercessor_leader")
    raw = {r["key"]: r for r in _mine(db, "church_role_defs")}
    if migrated:            # each row's switches are its catalog row's
        assert {k: {s: r[s] for s in (*cr.SWITCHES, "made_for")} for k, r in raw.items()} == \
            {k: cr._catalog_switches(rows[k], HANDLES[k]) for k in AME}
    else:
        assert not [k for r in raw.values() for k in r if k in (*cr.SWITCHES, "made_for")]
    assert {r["key"]: (r["area"], r["word"]) for r in _mine(db, "church_area_places")} == \
        (GUESSES if map_on and migrated else {})
    assert not _mine(db, "church_leader_roles"), "no one is asked into anything"

    # A second open changes nothing.
    before = [dict(r) for r in _mine(db, "church_role_defs") + _mine(db, "church_role_settings")]
    cr.ensure_library(church(db, RV))
    assert [dict(r) for r in _mine(db, "church_role_defs") + _mine(db, "church_role_settings")] == before


def test_leaders_and_roles_after_the_first_open(db):
    lib = cr.library(church(db, RV))
    assert lib["church_type"] == {"key": "ame", "label": "AME & Methodist", "guessed": "ame",
                                  "reason": "Your name says Methodist.", "set_by": "chief"}
    assert [(r["key"], r["status"], r["source"], r["holders"]) for r in lib["roles"]] == \
        [(k, "active", "catalog", []) for k in AME]
    assert (lib["teams"], lib["groups"], lib["kids_leaders"], lib["office"]) == ([], [], [], [])
    assert [r["key"] for r in next(t for t in lib["types"] if t["key"] == "ame")["rows"] if r["in_library"]] == \
        [r["key"] for r in cr.TYPES["ame"]["rows"]]


# The areas page (the office's Who sees what) opens the library too.
AREAS = {"worship_media": ["No one has joined the ChurchSavvy team yet."],
         "people_care": ["No one holds the senior pastor's role yet."],
         "giving_money": [], "kids_youth": [], "groups_classes": [],
         "messages_safety": ["Messaging needs two safety officers. It has 0."],
         "website_outreach": [], "office": []}


@pytest.mark.parametrize("opener", ["leaders_and_roles", "areas_page"])
def test_these_opens_fill_the_library(db, opener):
    b = church(db, RV)
    if opener == "leaders_and_roles":
        assert cr.library(b) is not None
    else:
        page = ca.build(b)
        assert {a["key"]: a["gaps"] for a in page["areas"]} == AREAS
        assert all(a["people"] == [] for a in page["areas"])
        assert (page["logins"], page["teams"], [u["key"] for u in page["unplaced"]]) == \
            ([], [], ["ypd_director", "team_leader"])
    assert [d["key"] for d in cr.defs(RV)] == AME and cr.settings(RV)["church_type"] == "ame"


def test_the_readers_never_fill_the_library(db):
    """A card coming in, Chief's lines, the leaders room, the Shepherding
    page and the money steps read Riverside as it is: they never seed it."""
    b = church(db, RV)
    assert cr.chief_lines(b) == ["The church hasn't set up its roles yet: no one holds a role, so every card goes to "
                                 "the office. The owner sets them up on Operate → Leaders & roles."]
    row = cfu.start(RV, db.who[RV]["henry"], card_key="connect", card_name="Connect card", kind="connect", answers=[])
    assert (row["leader_contact_id"], row["leader_role"], row["reason"]) == (
        None, "", "No one holds a role that takes connect cards yet. No one is named Pastor yet, so it’s with the "
                  "office.")
    assert mpm.leaders_room_people(RV) == []
    assert shep.overview(b) is not None and money(db, RV) is not None
    assert cr.settings(RV) == {} and cr.defs(RV, with_drafts=True) == [] and not _mine(db, "church_area_places")


# ─── Before the first open and after it ───────────────────────────────

FIRST_OPEN = pytest.mark.parametrize("opened", [False, True], ids=["never_opened", "after_first_open"])


@FIRST_OPEN
def test_the_leaders_room(db, opened):
    """No one holds a role, leads a group or has an office login."""
    if opened:
        _first_open(db)
    assert mpm.leaders_room_people(RV) == []


ASK = dict(today.ASK, **{"Usher Board": ("serve", [{"q": "Where would you like to serve?", "a": "Usher Board"}])})
# Every card goes to the office, active titles or none: no one holds one.
CHOOSE = {
    "baptism": "No one holds a role that takes baptism cards yet. No one is named Pastor yet, so it’s with the office.",
    "pastor_ask": "They asked to talk with a pastor. No one is named Pastor yet, so it’s with the office.",
    "care_need": "Their card mentions a care need. No one is named Pastor yet, so it’s with the office.",
    "connect": "No one holds a role that takes connect cards yet. No one is named Pastor yet, so it’s with the office.",
    "visit": "No one holds a role that takes plan your visit cards yet. No one is named Pastor yet, so it’s with the "
             "office.",
    "leftover": "No one is named Pastor yet, so it’s with the office.",
    "Usher Board": "Usher Board has no leader yet. No one is named Pastor yet, so it’s with the office.",
}


@FIRST_OPEN
def test_where_each_card_goes(db, opened):
    if opened:
        _first_open(db)
    holders, defs, m = cfu.roles(RV), cr.defs(RV), cm.opened(RV)
    got = {}
    for label, (kind, answers) in ASK.items():
        pick = cfu.choose(kind, answers, holders, {}, defs, m=m)
        got[label] = (pick["leader"], pick["role"], pick["reason"])
    assert got == {k: (None, "", why) for k, why in CHOOSE.items()}


T, P, B = "treasurer", "pastor", "board"


@FIRST_OPEN
def test_the_money_steps_and_the_pastors_yes(db, opened):
    """The platform's $500 / $2,500, and the owner gives the treasurer's
    step (there is no treasurer login). No one can give the pastor's yes the
    $600 request needs: no one holds the senior role, and the owner stands in
    only for a church that names no role for it (pastor_yes_roles '{}', step
    1 PR 7). §6's inferred risk, pinned as today's."""
    if opened:
        _first_open(db)
    assert money(db, RV) == ({18_000: [T], 25_000: [T], 60_000: [T, P]},
                             {T: ["owner"], P: [], B: [], "board people": []})


SHEPHERD_ROLES = [("pastor", True, None, True, []), ("associate_ministers", False, "ministers", False, []),
                  ("stewards", False, None, False, [])]
COUNTS = {"members": 60, "units": 40, "households": 20, "singles": 20, "placed": 0, "waiting": 40, "visitors": 0,
          "reached": 0, "drifting": 0, "not_reached_60": 0, "sundays_recorded": 0}


@FIRST_OPEN
def test_the_shepherding_page(db, opened):
    """Every family waits. Before the first open there is no lead role at
    all; after it the Pastor is the lead and shepherds, but no one holds it,
    so there is no shepherd (§6: Shepherding's lead, an inferred risk)."""
    if opened:
        _first_open(db)
    ov = shep.overview(church(db, RV))
    assert [(r["key"], r["shepherds"], r["switch"], r["lead"], r["holders"]) for r in ov["roles"]] == \
        (SHEPHERD_ROLES if opened else [])
    assert (ov["counts"], ov["shepherds"], ov["families_empty"], ov["draft"]) == (COUNTS, [], False, None)
    assert (ov["welcome"], ov["care_titles"]) == (
        ({"title": "Hospitality lead", "names": []}, ["Stewardesses", "Class Leaders", "Missionary Society president"])
        if opened else (None, []))


# The Prayer band (intercessors) in worship_media: WRONG, as GUESSES says.
PLACES = {"people_care": ["pastor", "associate_ministers", "stewards", "intercessor_leader", "stewardesses",
                          "missionary_society", "welcome_lead"],
          "worship_media": ["intercessors", "minister_of_music"], "groups_classes": ["class_leaders", "church_school"],
          None: ["ypd_director", "team_leader"], "giving_money": ["trustees"]}


@FIRST_OPEN
def test_where_each_role_sits(db, opened):
    """Through places_for, as the areas read it. The YPD director sits
    nowhere: "YPD" says nothing and a ministry job has no area."""
    if opened:
        _first_open(db)
    defs, got = cr.defs(RV), {}
    places = ca.places_for(RV, defs)
    for d in defs:
        got.setdefault(ca.place_role(d, places)["area"], []).append(d["key"])
    assert got == (PLACES if opened else {})


# ─── The three churches, with CHURCH_SETUP on ─────────────────────────

TODAY = [f for name, f in sorted(vars(today).items()) if name.startswith("test_") and name.endswith("_today")]
assert len(TODAY) >= 8, "every baseline in test_church_three_today runs here"


@pytest.fixture
def setup_on(monkeypatch, mode):
    monkeypatch.setenv("CHURCH_SETUP", "on")
    map_on, migrated = mode
    return build(monkeypatch, map_on=map_on, filled=False, migrated=migrated)


@pytest.mark.parametrize("check", TODAY, ids=[f.__name__ for f in TODAY])
@pytest.mark.parametrize("biz", CHURCHES, ids=[NAMES[b] for b in CHURCHES])
def test_the_three_churches_today_with_church_setup_on(setup_on, biz, check, monkeypatch):
    have = {"db": setup_on, "biz": biz, "monkeypatch": monkeypatch}
    check(**{k: have[k] for k in inspect.signature(check).parameters})


def _library(b):
    """library() as the page reads it, but for the fake's insert times."""
    lib = cr.library(b)
    return dict(lib, roles=[{k: v for k, v in r.items() if k != "created_at"} for r in lib["roles"]])


@pytest.mark.parametrize("map_on,migrated,filled",
                         [(*m, False) for m in MODES] + [(False, True, True), (True, True, True)],
                         ids=[*MODE_IDS, "map_off_filled", "map_open_filled"])
def test_the_three_libraries_are_the_same_with_church_setup_on(monkeypatch, map_on, migrated, filled):
    """Leaders & roles for each of the three, as test_church_three_today
    builds them and with their maps written, reads the same with
    CHURCH_SETUP on (§6: "library() included")."""
    def libraries():
        db = build(monkeypatch, map_on=map_on, filled=filled, migrated=migrated)
        return {b: _library(church(db, b)) for b in CHURCHES}

    monkeypatch.delenv("CHURCH_SETUP", raising=False)
    before = libraries()
    monkeypatch.setenv("CHURCH_SETUP", "on")
    assert libraries() == before
