"""The person chain (docs/CHURCH_LEADERS_MAP.md §3, §5 PR 6): where a church's
map is open, who a late item, a drifting family or a waiting prayer goes up to
is church_map.chain_for, from the person: their department's overseer, the
item's department's leader then overseer, the person they answer to, then
today's chain (church_roles.chain_above).

The scenario test holds needs 2 and 4 at all three churches, and
test_church_three_today every baseline with the map closed, open and empty,
and open before the migration. Here: where the map says nothing the chain is
today's; New Hope's other associate pastors never hear of a Youth item; a loop
ends; a vacant or no-longer-qualifying person is passed over; the support duty
is never a step; the closed switch keeps every baseline; a failed map read is
a failed read; prayer and a group leader's task."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.dirname(HERE), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_follow_up as cfu  # noqa: E402
import church_map as cm  # noqa: E402
import church_prayer as cp  # noqa: E402
import church_roles as cr  # noqa: E402
from church_three import (CHURCHES, GRACE as GR, LOVE_CITY as LC, NAMES, NEW_HOPE as NH, _mail, build,  # noqa: E402
                          drift_told, late_follow_up, late_task)
from test_church_three_today import DRIFT, LATE  # noqa: E402

ALL = pytest.mark.parametrize("biz", CHURCHES, ids=[NAMES[b] for b in CHURCHES])


def _ctx(biz):
    holders = cfu.roles(biz)
    defs = cfu._effective_defs(cr.defs(biz), holders)
    return cm.opened(biz), defs, cr.active_holders(holders), holders


def chain(db, biz, handle, *, group_id=None):
    """chain_for from this person's first role, as the sweeps call it: their
    team is their holder row's scope; [(step title, [first names])]."""
    m, defs, held, holders = _ctx(biz)
    cid = db.who[biz][handle]
    h = next(h for h in holders if h["contact_id"] == cid and h["status"] == "active")
    steps = cm.chain_for(m, defs, held, cid, cr.by_key(defs)[h["role"]], team=h["scope"], group_id=group_id,
                         skip={cid})
    return [(s["title"], [db.label[p["contact_id"]] for p in ps]) for s, ps in steps]


def _dept(db, biz, name):
    return next(d for d in db.t["church_departments"] if d["business_id"] == biz and d["name"] == name)


def _row(db, biz, handle, key):
    return next(h for h in db.t["church_leader_roles"]
                if h["business_id"] == biz and h["contact_id"] == db.who[biz][handle] and h["role"] == key)


def _role(db, biz, key):
    return next(d for d in db.t["church_role_defs"] if d["business_id"] == biz and d["key"] == key)


# ─── Where the map says nothing ───────────────────────────────────────

@ALL
@pytest.mark.parametrize("filled", [False, True], ids=["empty", "filled"])
def test_where_the_map_says_nothing_the_chain_is_todays(monkeypatch, biz, filled):
    """Every holder, on an empty map; on a filled one, everyone who leads no
    department, answers to no one, and whose role and team hang from none."""
    build(monkeypatch, filled=filled)
    m, defs, held, holders = _ctx(biz)
    checked = 0
    for h in (h for h in holders if h["status"] == "active"):
        role, cid = cr.by_key(defs)[h["role"]], h["contact_id"]
        if m.led_by(cid) or m.answers_to(cid, h["role"]) or m.department_of("serve_option", h["scope"]) \
                or m.department_of("role", role["id"]):
            continue
        checked += 1
        assert cm.chain_for(m, defs, held, cid, role, team=h["scope"], skip={cid}) == \
            cr.chain_above(role, defs, held, team=h["scope"], skip={cid}), (NAMES[biz], h["role"])
    assert checked >= 4
    assert cm.chain_for(m, defs, held, None, None) == cr.chain_above(None, defs, held), "no leader: the senior role"


def test_a_shepherd_in_no_department_with_no_answers_to_climbs_todays_chain(monkeypatch):
    """Love City's other elder, Tanya, answers to no one: her drifting
    family climbs as Marcus's did before the map (the baseline)."""
    db = build(monkeypatch)
    for s in db.t["church_shepherds"]:
        if s["business_id"] == LC:
            s["shepherd_contact_id"] = db.who[LC]["tanya"]
    assert drift_told(monkeypatch, db, LC) == [["Tanya"], ["Kevin"], []]
    assert DRIFT[LC] == [["Marcus"], ["Kevin"], []]


# ─── New Hope: one associate pastor for Youth ─────────────────────────

def test_new_hopes_other_associate_pastors_never_hear_of_a_youth_item(monkeypatch):
    for filled, told in ((False, {"Abel", "Amara", "Asher"}), (True, {"Amara"})):
        db = build(monkeypatch, filled=filled)
        heard = set(late_task(monkeypatch, db, NH)) | {n for day in late_follow_up(monkeypatch, db, NH) for n in day}
        assert heard & {"Abel", "Amara", "Asher"} == told, filled
    assert chain(db, NH, "yusuf") == [("Youth overseer", ["Amara"]), ("Senior Pastor", ["Nathan"])]


# ─── Steps, loops, the passed over ────────────────────────────────────

def test_a_team_leader_goes_to_the_teams_department_leader_then_its_overseer(monkeypatch):
    db = build(monkeypatch)
    assert chain(db, LC, "tyrone") == [("Youth leader", ["Yolanda"]), ("Youth overseer", ["Andre"]),
                                       ("Lead Pastor", ["Kevin"])]
    assert chain(db, LC, "iris") == [("Prayer leader", ["Ruth"]), ("Prayer overseer", ["Paul"]),
                                     ("Lead Pastor", ["Kevin"])], "the role hangs from Prayer"


def test_answers_to_loops_end(monkeypatch):
    db = build(monkeypatch)
    _row(db, LC, "jessica", "executive_pastor")["answers_to_contact_id"] = db.who[LC]["marcus"]   # A↔B
    assert chain(db, LC, "marcus") == [("Executive Pastor", ["Jessica"]), ("Lead Pastor", ["Kevin"])]
    assert chain(db, LC, "jessica") == [("Elders", ["Marcus"]), ("Lead Pastor", ["Kevin"])]
    assert drift_told(monkeypatch, db, LC) == [["Marcus"], ["Jessica"], ["Kevin"]]


def test_department_loops_end(monkeypatch):
    """Youth: Yolanda leads, Andre oversees; a second department the other way round."""
    db = build(monkeypatch)
    cr.update_role(LC, _role(db, LC, "youth_pastor")["id"], {"can_oversee": True})
    db.t["church_departments"].append(dict(_dept(db, LC, "Youth"), id=db.nid("church_departments"), name="Loop",
                                           leader_contact_id=db.who[LC]["andre"],
                                           overseer_contact_id=db.who[LC]["yolanda"]))
    assert chain(db, LC, "yolanda") == [("Youth overseer", ["Andre"]), ("Lead Pastor", ["Kevin"])]
    assert chain(db, LC, "andre") == [("Loop overseer", ["Yolanda"]), ("Lead Pastor", ["Kevin"])]


def test_a_vacant_or_no_longer_qualifying_person_is_passed_over(monkeypatch):
    db = build(monkeypatch)
    _dept(db, LC, "Youth")["leader_contact_id"] = None                 # a vacant leader: on to the overseer
    assert chain(db, LC, "tyrone") == [("Youth overseer", ["Andre"]), ("Lead Pastor", ["Kevin"])]
    _dept(db, NH, "Youth")["overseer_contact_id"] = db.who[NH]["hugo"]   # holds no role: today's chain
    assert late_task(monkeypatch, db, NH) == LATE[NH][1] == ["Abel", "Amara", "Asher"]
    cr.update_role(GR, _role(db, GR, "deacons")["id"], {"can_oversee": False})   # D1 no longer oversees
    assert late_task(monkeypatch, db, GR) == LATE[GR][1] == ["Samuel"]
    _row(db, LC, "marcus", "elders")["answers_to_contact_id"] = db.who[LC]["gloria"]   # holds no role
    assert drift_told(monkeypatch, db, LC) == DRIFT[LC]


def test_several_departments_send_to_each_overseer_once_unless_the_item_says_which(monkeypatch):
    db = build(monkeypatch)
    kids = _dept(db, NH, "Kids")
    kids.update(leader_contact_id=db.who[NH]["yusuf"], overseer_contact_id=db.who[NH]["asher"])
    assert chain(db, NH, "yusuf")[0] == ("Youth and Kids overseers", ["Amara", "Asher"])
    youth = next(g["id"] for g in db.t["groups"] if g["business_id"] == NH and g["name"] == "Youth")
    assert chain(db, NH, "yusuf", group_id=youth)[0] == ("Youth overseer", ["Amara"])
    kids["overseer_contact_id"] = db.who[NH]["amara"]
    assert chain(db, NH, "yusuf")[:2] == [("Youth and Kids overseer", ["Amara"]), ("Senior Pastor", ["Nathan"])]


@ALL
def test_the_support_duty_is_never_a_step(monkeypatch, biz):
    """Love City's Jessica holds Youth's duty and a role; she isn't in its line."""
    db = build(monkeypatch)
    handles = [k for k in db.who[biz] if "@" not in k and k != "family"]
    before = {h: chain(db, biz, h) for h in handles if any(r["contact_id"] == db.who[biz][h]
                                                        for r in db.t["church_leader_roles"])}
    for d in db.t["church_departments"]:
        if d["business_id"] == biz:
            d["support_duty"] = None
    assert {h: chain(db, biz, h) for h in before} == before
    if biz == LC:
        assert "Jessica" not in {n for _t, ns in before["yolanda"] + before["tyrone"] for n in ns}


# ─── The switch, a failed read ────────────────────────────────────────

@pytest.mark.parametrize("mode", ["off", "owner"])
def test_the_closed_switch_keeps_every_baseline(monkeypatch, mode):
    """A filled map, closed: today's chain. Owner opens Love City alone."""
    db = build(monkeypatch)
    monkeypatch.setenv("CHURCH_MAP", mode)
    for biz in CHURCHES:
        got = (late_task(monkeypatch, db, biz), late_follow_up(monkeypatch, db, biz), drift_told(monkeypatch, db, biz))
        want = (LATE[biz][1], LATE[biz][2], DRIFT[biz])
        if mode == "owner" and biz == LC:
            want = (["Andre"], [["Andre"], ["Kevin"]], [["Marcus"], ["Jessica"], ["Kevin"]])
        assert got == want, (mode, NAMES[biz])


def test_a_failed_map_read_is_a_failed_read(monkeypatch):
    """Never today's people: nothing is sent, nothing is claimed."""
    db = build(monkeypatch)
    monkeypatch.setattr(cm, "load", lambda biz: None)
    assert late_task(monkeypatch, db, NH) == [] and all(t["late_told_at"] is None for t in db.t["tasks"])
    assert late_follow_up(monkeypatch, db, NH) == [[], []]
    assert drift_told(monkeypatch, db, NH) == [[], [], []]
    assert cp.pass_targets(LC, {"id": db.who[LC]["ruth"]}) is None


# ─── Prayer, a group leader's task ────────────────────────────────────

def _prayer_late(monkeypatch, db, handle, key):
    """Who a prayer request waiting with this leader emails a day late, then three."""
    row = {"id": "5f000000-0000-4000-8000-000000000001", "business_id": LC, "leader_contact_id": db.who[LC][handle],
           "leader_role": key, "leader_due_at": "2026-10-26T12:00:00+00:00", "leader_told_at": "2026-10-25T12:00:00+00:00",
           "leader_late_level": 0, "leader_prayed_at": None, "submission": {"name": "Pat Doe"}}
    db.t["ministry_care_requests"] = [row]
    sent, out = _mail(monkeypatch), []
    for days in (1, 3):
        sent.clear()
        asyncio.run(cp._sweep_church(LC, [dict(row)], cfu._parse(row["leader_due_at"]) + timedelta(days=days, hours=1),
                                     dict.fromkeys(("told", "nudged", "overseer_told", "next_up"), 0)))
        out.append(sorted(db.label[c["id"]] for c in db.t["contacts"] for to, _k in sent if c["email"] == to))
    return out


def test_a_waiting_prayer_climbs_the_prayer_leaders_department(monkeypatch):
    db = build(monkeypatch, filled=False)
    today = _prayer_late(monkeypatch, db, "ruth", "intercessor_leader")
    db = build(monkeypatch)
    assert _prayer_late(monkeypatch, db, "ruth", "intercessor_leader") == [["Paul"], ["Kevin"]] != today


def test_a_prayer_leader_may_pass_to_who_answers_to_them_as_a_person(monkeypatch):
    db = build(monkeypatch)
    _row(db, LC, "ivy", "intercessors")["answers_to_contact_id"] = db.who[LC]["paul"]
    paul = {"id": db.who[LC]["paul"]}
    assert [db.label[t["contact_id"]] for t in cp.pass_targets(LC, paul)] == ["Ivy"]
    assert sorted(db.label[t["contact_id"]] for t in cp.pass_targets(LC, {"id": db.who[LC]["ruth"]})) == ["Iris", "Ivy"]
    monkeypatch.setenv("CHURCH_MAP", "off")
    assert cp.pass_targets(LC, paul) == []


def test_a_group_leader_with_no_role_goes_to_the_groups_department(monkeypatch):
    db = build(monkeypatch)
    youth = next(g["id"] for g in db.t["groups"] if g["business_id"] == LC and g["name"] == "Youth")
    db.t["group_members"].append({"group_id": youth, "business_id": LC, "contact_id": db.who[LC]["gloria"],
                                  "role": "leader"})
    task = next(t for t in db.t["tasks"] if t["business_id"] == LC)
    task["assigned_contact_id"] = db.who[LC]["gloria"]
    assert late_task(monkeypatch, db, LC) == ["Yolanda"], "Youth's leader"
    task["late_told_at"] = None
    _dept(db, LC, "Youth")["leader_contact_id"] = None
    assert late_task(monkeypatch, db, LC) == ["Andre"], "a vacant leader: its overseer"
    task["late_told_at"] = None
    monkeypatch.setenv("CHURCH_MAP", "off")
    assert late_task(monkeypatch, db, LC) == ["Kevin"], "closed: back to whoever handed it out (the owner)"
