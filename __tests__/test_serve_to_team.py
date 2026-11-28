"""Serve sign-ups go to the team's own leader, and the old Team leader rows
move onto the team (M-8, part 4; Kevin 2026-11-28). At Love City:

  1. a Serve card choice a team answers for (groups.serve_option, else the
     team's name) goes to that team's lead first, the record the Sunday hub
     calls its Team leader; with none, today's routing as before
  2. team_leads: the lead before co-leaders; a failed read is {} (the card
     goes as it did)
  3. the move list: lead, co_leader, already, asked (never moved), no_team;
     applying adds the team's own leader row and keeps the role row
  4. the owner or an admin only
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_follow_up as cfu  # noqa: E402
import church_roles as cr  # noqa: E402
import church_team_moves as ctm  # noqa: E402
import sb_clients  # noqa: E402
from church_three import LOVE_CITY as LC, build  # noqa: E402

WELCOME = "e0000000-0000-4000-8000-0000000000a1"
YOUTH_TEAM = "e0000000-0000-4000-8000-0000000000a2"
PARKING = "e0000000-0000-4000-8000-0000000000a3"


@pytest.fixture
def lc(monkeypatch):
    db = build(monkeypatch)
    w = db.who[LC]
    db.t["groups"] += [
        {"id": WELCOME, "business_id": LC, "name": "Welcome", "active": True, "kind": "team", "serve_option": "Hospitality Team"},
        {"id": YOUTH_TEAM, "business_id": LC, "name": "Youth Ministry (YWD)", "active": True, "kind": "team", "serve_option": None},
        {"id": PARKING, "business_id": LC, "name": "Parking", "active": True, "kind": "team", "serve_option": None}]
    db.t["group_members"] += [
        {"group_id": YOUTH_TEAM, "business_id": LC, "contact_id": w["yolanda"], "role": "leader", "co_leader": False},
        {"group_id": PARKING, "business_id": LC, "contact_id": w["calvin"], "role": "leader", "co_leader": True},
        {"group_id": PARKING, "business_id": LC, "contact_id": w["dana"], "role": "leader", "co_leader": False}]
    for m in db.t["group_members"]:
        m.setdefault("co_leader", False)
    for g in db.t["groups"]:
        g.setdefault("serve_option", None)
    # Someone asked to lead a team who hasn't said yes, and a team with no group.
    db.t["church_leader_roles"] += [
        {"id": "h-asked", "business_id": LC, "contact_id": w["gloria"], "role": "team_leader", "scope": "Parking",
         "status": "invited", "invited_at": "2026-11-01T00:00:00+00:00", "answered_at": None, "answers_to_contact_id": None},
        {"id": "h-noteam", "business_id": LC, "contact_id": w["eve"], "role": "team_leader", "scope": "City Serve: outreach",
         "status": "active", "invited_at": "2026-11-01T00:00:00+00:00", "answered_at": None, "answers_to_contact_id": None}]
    real = sb_clients.sb_post_as_service

    def post(path, body, *a, **k):
        if path.startswith("/group_members?on_conflict=group_id,contact_id"):
            out = []
            for b in body:
                old = next((r for r in db.t["group_members"]
                            if r["group_id"] == b["group_id"] and r["contact_id"] == b["contact_id"]), None)
                if old:
                    old.update(b)
                else:
                    db.t["group_members"].append(dict(b))
                    old = db.t["group_members"][-1]
                out.append(dict(old))
            return out
        return real(path, body, *a, **k)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    return db





def _pick(team, teams):
    roles, defs = cfu.roles(LC), cr.defs(LC)
    return cfu.choose("serve", [{"q": "Where would you like to serve?", "a": team}], roles, {}, defs, teams=teams)


def test_a_sign_up_goes_to_the_teams_own_leader_first(lc):
    w = lc.who[LC]
    before = _pick("Youth Ministry (YWD)", None)
    assert before["leader"]["contact_id"] == w["tyrone"]                 # the old Team leader row
    after = _pick("Youth Ministry (YWD)", cfu.team_leads(LC, cr.defs(LC)))
    assert after["leader"]["contact_id"] == w["yolanda"] and after["role"] == "team_leader"
    assert "Yolanda leads Youth Ministry (YWD)" in after["reason"]


def test_the_serve_choice_names_the_team(lc):
    w = lc.who[LC]
    lc.t["group_members"].append({"group_id": WELCOME, "business_id": LC, "contact_id": w["ivy"], "role": "leader", "co_leader": False})
    got = _pick("Hospitality Team", cfu.team_leads(LC, cr.defs(LC)))
    assert got["leader"]["contact_id"] == w["ivy"] and "leads Welcome" in got["reason"]


def test_a_team_with_no_leader_goes_as_before(lc):
    w = lc.who[LC]
    got = _pick("Hospitality Team", cfu.team_leads(LC, cr.defs(LC)))     # Welcome has no leader yet
    assert got["leader"]["contact_id"] == w["tasha"]


def test_the_lead_before_co_leaders_and_a_failed_read_is_empty(lc, monkeypatch):
    w = lc.who[LC]
    t = cfu.team_leads(LC, cr.defs(LC))
    assert [r["contact_id"] for r in t["parking"]] == [w["dana"], w["calvin"]]
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if path.startswith("/group_members?business_id") and "role=eq.leader" in path
                        else real(path, *a, **k))
    assert cfu.team_leads(LC, cr.defs(LC)) == {}


def test_the_move_list(lc):
    w = lc.who[LC]
    rows = {r["name"]: r for r in ctm.plan(LC)["rows"]}
    assert rows["Tasha Williams"]["will"] == "lead" and rows["Tasha Williams"]["team"]["name"] == "Welcome"
    assert rows["Tyrone Banks"]["will"] == "co_leader"
    assert rows["Gloria Hunt"]["will"] == "asked"
    assert rows["Eve Hall"]["will"] == "no_team"
    assert w  # the fixture's people


def test_applying_adds_the_teams_own_row_and_keeps_the_role(lc):
    w = lc.who[LC]
    ids = [r["holder_id"] for r in ctm.plan(LC)["rows"]]
    out = ctm.apply(LC, ids)
    assert sorted((m["name"], m["as"]) for m in out["moved"]) == [("Tasha Williams", "lead"), ("Tyrone Banks", "co_leader")]
    assert any(m["group_id"] == WELCOME and m["contact_id"] == w["tasha"] and m["role"] == "leader" and m["co_leader"] is False
               for m in lc.t["group_members"])
    assert any(m["group_id"] == YOUTH_TEAM and m["contact_id"] == w["tyrone"] and m["co_leader"] is True for m in lc.t["group_members"])
    assert not any(m["contact_id"] == w["gloria"] and m["group_id"] == PARKING for m in lc.t["group_members"])   # asked: never
    assert any(h["contact_id"] == w["tasha"] and h["role"] == "team_leader" for h in lc.t["church_leader_roles"])   # kept
    assert {r["name"]: r["will"] for r in out["rows"]}["Tasha Williams"] == "already"


def _client(monkeypatch, role):
    import business_access
    import church_router
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: role)
    app = FastAPI()
    app.include_router(church_router.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id="u-x", email="x@example.com", user_metadata={})))
    return TestClient(app)


@pytest.mark.parametrize("role,code", [("owner", 200), ("admin", 200), ("manager", 404)])
def test_the_owner_or_an_admin(lc, monkeypatch, role, code):
    c = _client(monkeypatch, role)
    assert c.get(f"/church/leaders/team-moves?business_id={LC}").status_code == code
    r = c.post(f"/church/leaders/team-moves/apply?business_id={LC}", json={"holder_ids": []})
    assert r.status_code == (400 if code == 200 else code)


# ── M-8 review M3: no church's routing changes before its switch-on ──

@pytest.mark.parametrize("mode,who", [("off", "tyrone"), ("on", "yolanda")])
def test_a_serve_card_goes_to_the_team_only_where_group_leads_is_on(lc, monkeypatch, mode, who):
    monkeypatch.setenv("GROUP_LEADS", mode)
    w = lc.who[LC]
    row = cfu.start(LC, w["calvin"], card_key=f"serve-{mode}", card_name="Serve with us", kind="serve",
                    answers=[{"q": "Where would you like to serve?", "a": "Youth Ministry (YWD)"}])
    assert row is not None
    assert row["leader_contact_id"] == w[who]


def test_owner_mode_is_the_platform_owners_church_only(monkeypatch):
    import member_asks
    monkeypatch.setenv("GROUP_LEADS", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: b == LC)
    assert cfu.group_leads_open(LC) and not cfu.group_leads_open("2b000000-0000-4000-8000-000000000000")


# ── M-8 review S5: one lead a team; the note goes out ────────────────

def test_two_movers_for_one_leaderless_team_one_lead_one_co_leader(lc):
    w = lc.who[LC]
    lc.t["church_leader_roles"].append(
        {"id": "h-second", "business_id": LC, "contact_id": w["ivy"], "role": "team_leader", "scope": "Hospitality Team",
         "status": "active", "invited_at": "2026-11-02T00:00:00+00:00", "answered_at": None, "answers_to_contact_id": None})
    rows = {r["name"]: r["will"] for r in ctm.plan(LC)["rows"]}
    assert rows["Tasha Williams"] == "lead" and rows["Ivy Lane"] == "co_leader"
    # Only the second picked: they become the lead, since the team has none.
    out = ctm.apply(LC, ["h-second"])
    assert [(m["name"], m["as"]) for m in out["moved"]] == [("Ivy Lane", "lead")]
    assert {r["name"]: r["will"] for r in out["rows"]}["Tasha Williams"] == "co_leader"


def test_moves_send_the_note_through_group_leads(lc, monkeypatch):
    import asyncio
    import types
    told = []

    async def tell(business, g, new):
        told.append((g["name"], sorted(new)))
        return {"phones": len(new), "emailed": 0}
    monkeypatch.setitem(sys.modules, "church_group_leads", types.SimpleNamespace(tell=tell))
    out = ctm.apply(LC, [r["holder_id"] for r in ctm.plan(LC)["rows"]])
    n = asyncio.run(ctm.tell_moved({"id": LC, "name": "Love City"}, out["moved"]))
    w = lc.who[LC]
    assert n == 2 and sorted(told) == [("Welcome", [(w["tasha"], False)]), ("Youth Ministry (YWD)", [(w["tyrone"], True)])]
