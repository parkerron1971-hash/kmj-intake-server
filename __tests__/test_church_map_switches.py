"""Switches replace words (docs/CHURCH_LEADERS_MAP.md §3, §5 PR 4): where a
church's map is open, a role's stored switches decide who shepherds
(church_shepherding.role_rows), which role a card's stream goes to when two
tie (church_follow_up.choose, made_for) and who sits in the leaders room
(member_portal_messaging, can_lead), not its title or its job.

test_church_three_today holds every baseline with the map closed, open and
empty, and open without the migration. Here: what a filled map changes, that
a title no longer does, and that a failed map read is a failed read."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_follow_up as cfu  # noqa: E402
import church_map as cm  # noqa: E402
import church_roles as cr  # noqa: E402
import church_shepherding as shep  # noqa: E402
import member_portal_messaging as mpm  # noqa: E402
import sb_clients  # noqa: E402
from church_three import GRACE, LOVE_CITY as LC, NEW_HOPE as NH, build, church  # noqa: E402
from test_church_three_today import ROOM, SHEPHERDING  # noqa: E402

CARE = [{"q": "Anything else?", "a": "My mom is in the hospital"}]


def _names(db, ids):
    return sorted(db.label[str(i)] for i in ids)


def _shepherds(db, biz):
    return _names(db, shep.load(biz)["shepherds"])


def _room(db, biz):
    return _names(db, (p["contact_id"] for p in mpm.leaders_room_people(biz)))


def _role(db, biz, key):
    return next(d for d in db.t["church_role_defs"] if d["business_id"] == biz and d["key"] == key)


def _hold(db, biz, key, cid):
    db.t["church_leader_roles"].append({"id": db.nid("church_leader_roles"), "business_id": biz, "contact_id": cid,
                                        "role": key, "scope": "", "status": "active",
                                        "invited_at": "2026-10-01T00:00:00+00:00", "answered_at": None,
                                        "answers_to_contact_id": None})


def _card(db, biz):
    """Where a care-need card goes, through start() as a card comes in."""
    n = len(db.t["church_follow_ups"])
    row = cfu.start(biz, db.who[biz]["n200"], card_key=f"form:care-{n}", card_name="Connect card", kind="connect",
                    answers=CARE)
    return row["leader_role"]


# ─── Who shepherds ────────────────────────────────────────────────────

def test_graces_deacon_board_shepherds_once_its_switch_is_flipped(monkeypatch):
    db = build(monkeypatch, filled=False)
    assert _shepherds(db, GRACE) == ["Samuel"], "not flipped: a care job's switch is off, as today"
    db = build(monkeypatch)                     # the map flips the Deacon Board's can_shepherd on
    row = next(r for r in shep.load(GRACE)["roles"] if r["def"]["key"] == "deacons")
    assert (row["shepherds"], row["switch"], row["lead"]) == (True, None, False)
    both = ["Daniel", "Della", "Doris", "Dwight", "Samuel"]
    assert _shepherds(db, GRACE) == _names(db, shep._member_ctx(GRACE)["shepherds"]) == both
    mine = shep.my_families(GRACE, db.who[GRACE]["doris"])
    assert ([f["name"] for f in mine["families"]], mine["chain"]) == (["The Jordan family"], ["Samuel Gray"])
    for closed in ("off", "owner"):             # owner: only the platform owner's church, Love City
        monkeypatch.setenv("CHURCH_MAP", closed)
        assert _shepherds(db, GRACE) == ["Samuel"], f"{closed}: today's titles, whatever the switch says"


def test_a_role_that_follows_ministers_follows_the_toggle_both_ways(monkeypatch):
    """Can_shepherd null follows the church's Ministers setting: Love City's
    Ministers, and a pastoral role with no minister word in its title."""
    db = build(monkeypatch, filled=False)
    chap = cr.create_role(church(db, LC), {"title": "Chaplains", "job": "pastoral", "can_shepherd": None})
    assert chap["can_shepherd"] is None
    _hold(db, LC, chap["key"], db.who[LC]["gloria"])
    for on in (True, False, True):
        # The office's toggle (church_shepherd_settings.ministers), as its row.
        db.t["church_shepherd_settings"] = [{"business_id": LC, "ministers": on}]
        ctx = shep.load(LC)
        rows = {r["def"]["key"]: (r["shepherds"], r["switch"]) for r in ctx["roles"]}
        assert rows["ministers"] == rows["chaplains"] == (on, "ministers")
        assert {"Angela", "Gloria"} & set(_names(db, ctx["shepherds"])) == ({"Angela", "Gloria"} if on else set())
    monkeypatch.setenv("CHURCH_MAP", "off")
    rows = {r["def"]["key"]: (r["shepherds"], r["switch"]) for r in shep.load(LC)["roles"]}
    assert (rows["ministers"], rows["chaplains"]) == ((True, "ministers"), (False, None)), "closed: the title"


# ─── A title no longer decides ────────────────────────────────────────

def test_a_new_title_changes_neither_who_shepherds_nor_which_role_a_card_goes_to(monkeypatch):
    """New Hope's Elders become the Council, and its Deacons the Care Deacons
    (with someone on the Care team, which the care stream is made for)."""
    db = build(monkeypatch, filled=False)
    _hold(db, NH, "care_team", db.who[NH]["n100"])
    before = (_shepherds(db, NH), _card(db, NH))
    assert before == (SHEPHERDING[NH][1], "care_team")
    for key, title in (("elders", "Council"), ("deacons", "Care Deacons")):
        cr.update_role(NH, _role(db, NH, key)["id"], {"title": title})
    assert (_shepherds(db, NH), _card(db, NH)) == before, "open: the switches decide"
    monkeypatch.setenv("CHURCH_MAP", "off")
    assert (_shepherds(db, NH), _card(db, NH)) == (["Abel", "Amara", "Asher", "Nathan"], "deacons"), \
        "closed, the words still decide (until PR 9): no shepherd word, and a tie on 'care'"


def test_made_for_breaks_the_tie_where_the_map_is_open_and_a_legacy_role_carries_its_catalogs():
    defs = [{"id": "r1", "key": "baptism_helpers", "title": "Baptism helpers", "job": "pastoral", "covers": "church",
             "reports_to": None, "oversees_teams": [], "handles": ["baptism"], "status": "active"},
            {"id": "r2", "key": "aides", "title": "Aides", "job": "pastoral", "covers": "church",
             "reports_to": None, "oversees_teams": [], "handles": ["baptism"], "status": "active"}]
    holders = [{"id": f"h{n}", "contact_id": f"c{n}", "role": d["key"], "status": "active", "name": f"Person {n}"}
               for n, d in enumerate(defs, 1)]
    m = cm.Map("b", roles={"r1": {"made_for": []}, "r2": {"made_for": ["baptism", "care_need"]}})
    assert cfu.choose("baptism", [], holders, {}, defs)["role"] == "baptism_helpers", "closed: the word"
    assert cfu.choose("baptism", [], holders, {}, defs, m=m)["role"] == "aides", "open: made_for"
    assert cm.made_for(m, defs[1]) == ["baptism"], "only ever among its handles"
    eff = cr.by_key(cfu._effective_defs([], [{"role": "baptism_minister"}, {"role": "welcome_lead"}]))
    assert {k: eff["baptism_minister"][k] for k in (*cr.SWITCHES, "made_for")} == {
        "can_shepherd": None, "can_oversee": True, "can_lead": True, "can_board_yes": False, "can_see_all": False,
        "made_for": ["baptism"]}
    assert (cm.made_for(m, eff["baptism_minister"]), cm.can(m, eff["welcome_lead"])["lead"]) == (["baptism"], True)


# ─── The leaders room ─────────────────────────────────────────────────

def _dept(db, biz, name, leader, overseer, status="active"):
    db.t["church_departments"].append({
        "id": db.nid("church_departments"), "business_id": biz, "name": name, "leader_contact_id": leader,
        "overseer_contact_id": overseer, "support_duty": None, "area": None, "status": status, "source": "office",
        "sort": 0, "updated_by": None, "updated_at": "2026-11-03T12:00:00+00:00"})


def test_the_leaders_room_reads_can_lead_and_seats_department_people_who_hold_a_role(monkeypatch):
    db = build(monkeypatch)
    w = db.who[GRACE]
    assert _room(db, GRACE) == sorted(ROOM[GRACE] + ["Daniel"]), "Youth's overseer, a deacon"
    assert (_room(db, LC), _room(db, NH)) == (ROOM[LC], ROOM[NH]), "their department people are in already"
    _dept(db, GRACE, "Kitchen", w["g20"], w["dwight"])
    _dept(db, GRACE, "Ushers", w["della"], w["doris"], status="draft")
    assert _room(db, GRACE) == sorted(ROOM[GRACE] + ["Daniel", "Dwight"]), \
        "an active department's people who hold a role: not G20, who holds none, nor a draft's"
    cr.update_role(GRACE, _role(db, GRACE, "deacons")["id"], {"can_lead": True})
    assert _room(db, GRACE) == sorted(ROOM[GRACE] + ["Daniel", "Della", "Doris", "Dwight"]), "can_lead, not the job"
    monkeypatch.setenv("CHURCH_MAP", "off")
    assert _room(db, GRACE) == ROOM[GRACE], "closed: the job list, and no departments"


def test_the_leaders_room_keeps_the_answers_to_seat_on_an_open_map(monkeypatch):
    """Love City's Intercessor leader is in because the Intercessors answer
    to her (a prayer job, can_lead off), not because of a department."""
    db = build(monkeypatch, filled=False)
    ruth = db.who[LC]["ruth"]
    assert ruth in {p["contact_id"] for p in mpm.leaders_room_people(LC)}
    _role(db, LC, "intercessors")["reports_to"] = None
    assert ruth not in {p["contact_id"] for p in mpm.leaders_room_people(LC)}, "nobody answers to her now"


# ─── A failed map read ────────────────────────────────────────────────

def test_a_failed_map_read_is_a_failed_read_never_todays_people(monkeypatch):
    db = build(monkeypatch)
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p, **k: None if p.startswith("/church_departments?") else real(p, **k))
    assert (shep.load(LC), shep._member_ctx(LC), mpm.leaders_room_people(LC)) == (None, None, None)
    n = len(db.t["church_follow_ups"])
    assert cfu.start(LC, db.who[LC]["gloria"], card_key="form:care", card_name="Connect card", kind="connect",
                     answers=CARE) is None and len(db.t["church_follow_ups"]) == n, "the card waits, as on any failed read"
    monkeypatch.setenv("CHURCH_MAP", "off")
    assert shep.load(LC) and mpm.leaders_room_people(LC) is not None, "closed, the map is never read"
