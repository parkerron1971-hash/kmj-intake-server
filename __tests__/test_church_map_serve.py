"""A Serve sign-up for a team with no leader goes to its department
(docs/CHURCH_LEADERS_MAP.md §3, the church_follow_up row): where a church's map
is open and the team's Serve option hangs from an active department, that
department's leader, else its overseer, while they still qualify, before
today's oversees_teams. A team with a leader of its own, or in no department,
is today's; so are an empty map, a closed switch and a database before the
migration. A failed map read leaves the sign-up waiting, as any failed read
does. The late ladder then climbs church_map.chain_for from whoever has it."""
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
import church_roles as cr  # noqa: E402
from church_three import (CHURCHES, GRACE as GR, LOVE_CITY as LC, NAMES, NEW_HOPE as NH, _by_email, _mail,  # noqa: E402
                          build, church)
from test_church_three_today import CHOOSE  # noqa: E402

YWD = "Youth Ministry (YWD)"
NO_LEADER = "They picked Youth Ministry (YWD), which has no leader yet; "
TODAY = ("Yolanda", "youth_pastor", NO_LEADER + "it’s under the Youth Pastor.")     # oversees_teams


def pick(db, biz, team):
    """Where a Serve sign-up for this team goes, handed the map as start() hands it."""
    p = cfu.choose("serve", [{"q": "Where would you like to serve?", "a": team}], cfu.roles(biz), {}, cr.defs(biz),
                   m=cm.opened(biz))
    return db.label.get((p["leader"] or {}).get("contact_id")), p["role"], p["reason"]


def no_team_leader(db, biz=LC, team=YWD):
    db.t["church_leader_roles"] = [h for h in db.t["church_leader_roles"]
                                   if not (h["business_id"] == biz and h["role"] == "team_leader" and h["scope"] == team)]


def youth(db):
    return next(d for d in db.t["church_departments"] if d["business_id"] == LC and d["name"] == "Youth")


def _role(db, key):
    return next(d for d in db.t["church_role_defs"] if d["business_id"] == LC and d["key"] == key)


# ─── The department decides ───────────────────────────────────────────

def test_a_team_with_no_leader_goes_to_its_departments_leader_then_its_overseer(monkeypatch):
    db = build(monkeypatch)
    no_team_leader(db)
    assert pick(db, LC, YWD) == ("Yolanda", "youth_pastor", NO_LEADER + "it goes to the Youth leader.")
    youth(db)["leader_contact_id"] = db.who[LC]["cora"]                 # before the role that oversees the team
    assert pick(db, LC, YWD) == ("Cora", "childrens_director", NO_LEADER + "it goes to the Youth leader.")
    youth(db)["leader_contact_id"] = None                                # vacant: its overseer
    assert pick(db, LC, YWD) == ("Andre", "associate_pastor", NO_LEADER + "it goes to the Youth overseer.")
    youth(db)["overseer_contact_id"] = None                              # both vacant: today's rule
    assert pick(db, LC, YWD) == TODAY


def test_a_leader_or_overseer_who_no_longer_qualifies_is_passed_over(monkeypatch):
    db = build(monkeypatch)
    no_team_leader(db)
    cr.update_role(LC, _role(db, "youth_pastor")["id"], {"can_lead": False})
    assert pick(db, LC, YWD) == ("Andre", "associate_pastor", NO_LEADER + "it goes to the Youth overseer.")
    cr.update_role(LC, _role(db, "associate_pastor")["id"], {"can_oversee": False})
    assert pick(db, LC, YWD) == TODAY
    youth(db)["status"] = "draft"                                       # a draft department routes nothing
    cr.update_role(LC, _role(db, "youth_pastor")["id"], {"can_lead": True})
    assert pick(db, LC, YWD) == TODAY


@pytest.mark.parametrize("biz", CHURCHES, ids=[NAMES[b] for b in CHURCHES])
def test_a_team_with_its_own_leader_or_in_no_department_is_todays(monkeypatch, biz):
    """A filled map: Love City's team leaders keep their teams, and every team
    in no department goes where it goes today. The other churches' teams that
    hang from a department reach the same person, now by the department."""
    db = build(monkeypatch)
    got = {t: pick(db, biz, t) for t in cfu.teams(biz)}
    by_dept = {GR: {"Youth Ministry": "Youth"},
               NH: {"Worship Team": "Worship", "Youth Volunteers": "Youth", "Kids Check-in": "Kids"}}.get(biz, {})
    for t, (who, role, why) in got.items():
        if t in by_dept:
            team = by_dept[t]
            assert (who, role) == CHOOSE[biz][t][:2] and why.endswith(f"it goes to the {team} leader."), t
        else:
            assert (who, role, why) == CHOOSE[biz][t], t
    if biz == LC:
        no_team_leader(db)
        assert pick(db, LC, "Hospitality Team") == CHOOSE[LC]["Hospitality Team"]
        assert pick(db, LC, "Graphic and web design") == CHOOSE[LC]["Graphic and web design"]


# ─── Where the map says nothing, or is closed ─────────────────────────

@pytest.mark.parametrize("map_on,migrated", [(True, True), (True, False), (False, True)],
                         ids=["open_empty", "open_not_migrated", "closed"])
def test_an_empty_map_a_closed_switch_and_no_migration_are_todays(monkeypatch, map_on, migrated):
    db = build(monkeypatch, map_on=map_on, filled=False, migrated=migrated)
    no_team_leader(db)
    assert pick(db, LC, YWD) == TODAY
    for biz in CHURCHES:
        assert {t: pick(db, biz, t) for t in cfu.teams(biz) if t != YWD} == \
            {t: CHOOSE[biz][t] for t in cfu.teams(biz) if t != YWD}


@pytest.mark.parametrize("mode", ["off", "owner"])
def test_a_filled_map_closed_is_todays(monkeypatch, mode):
    """Owner opens Love City alone."""
    db = build(monkeypatch)
    no_team_leader(db)
    youth(db)["leader_contact_id"] = None
    monkeypatch.setenv("CHURCH_MAP", mode)
    assert pick(db, LC, YWD) == (TODAY if mode == "off" else
                                 ("Andre", "associate_pastor", NO_LEADER + "it goes to the Youth overseer."))
    assert pick(db, GR, "Youth Ministry") == CHOOSE[GR]["Youth Ministry"]
    assert pick(db, NH, "Kids Check-in") == CHOOSE[NH]["Kids Check-in"]


# ─── A card comes in, a failed read, the late ladder ──────────────────

def sign_up(db, handle, team=YWD):
    form = next(f for f in db.t["intake_forms"] if f["business_id"] == LC)
    return cfu.on_intake_form(church(db, LC), form, {"team": team}, db.who[LC][handle])


def late(monkeypatch, db, row):
    """Who this follow-up emails a day late, then three days late."""
    sent, out = _mail(monkeypatch), []
    row = dict(row, leader_told_at=row["assigned_at"])
    for days in (1, 3):
        sent.clear()
        stats = dict.fromkeys(("told", "office", "reached", "nudged", "overseer_told", "next_up"), 0)
        asyncio.run(cfu._sweep_church(LC, [dict(row)], cfu._parse(row["due_at"]) + timedelta(days=days, hours=1), stats))
        out.append(_by_email(db, LC, [to for to, _k in sent]))
    return out


def test_the_follow_up_is_the_department_persons_and_climbs_their_chain(monkeypatch):
    db = build(monkeypatch)
    no_team_leader(db)
    row = sign_up(db, "gloria")
    assert (db.label[row["leader_contact_id"]], row["leader_role"]) == ("Yolanda", "youth_pastor")
    assert row["reason"] == NO_LEADER + "it goes to the Youth leader."
    assert late(monkeypatch, db, row) == [["Andre"], ["Kevin"]], "Youth's overseer, then one further"
    youth(db)["leader_contact_id"] = None
    row = sign_up(db, "calvin")
    assert (db.label[row["leader_contact_id"]], row["leader_role"]) == ("Andre", "associate_pastor")
    assert late(monkeypatch, db, row) == [["Kevin"], ["Kevin"]]


def test_a_failed_map_read_leaves_the_sign_up_waiting(monkeypatch):
    """Never today's people: no follow-up, no note."""
    db = build(monkeypatch)
    no_team_leader(db)
    before = (len(db.t["church_follow_ups"]), len(db.t["church_follow_up_notes"]))
    monkeypatch.setattr(cm, "load", lambda biz: None)
    assert sign_up(db, "gloria") is None
    assert (len(db.t["church_follow_ups"]), len(db.t["church_follow_up_notes"])) == before
