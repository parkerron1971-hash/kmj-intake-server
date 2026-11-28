"""Everyone who leads, in one place (church_leaders_all.py; mission M-8,
Kevin 2026-11-28). At the three test churches' Love City:

  1. one row a person a thing they lead: role holders, group leads and
     co-leaders by kind, Kids leaders; each with who they answer to, a
     person, or the fallback in words
  2. a class group pointing at its Course Studio class shows its teacher
     once, with both; a teacher with no group still shows
  3. the Worship part shows as a worship team leader, once
  4. the teams list (Sunday or not, Serve choice, leaders); the gaps
  5. before the group-leads file: still whole, no new columns asked for
  6. the route: a manager seat and up; a failed read is a 503
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

import church_leaders_all as cla  # noqa: E402
import church_map as cm  # noqa: E402
import sb_clients  # noqa: E402
from church_three import LOVE_CITY as LC, build, church  # noqa: E402

COURSE = "c0000000-0000-4000-8000-0000000000c1"
COURSE2 = "c0000000-0000-4000-8000-0000000000c2"
TEAM = "e0000000-0000-4000-8000-0000000000e1"
CLASSG = "e0000000-0000-4000-8000-0000000000e2"


@pytest.fixture
def lc(monkeypatch):
    db = build(monkeypatch)
    w = db.who[LC]
    for g in db.t["groups"]:
        g.update(answers_to_contact_id=None, course_id=None, serve_option=None)
    for m in db.t["group_members"]:
        m.setdefault("co_leader", False)
    sisters = next(g for g in db.t["groups"] if g["business_id"] == LC and g["name"] == "Sisters in the City")
    sisters["answers_to_contact_id"] = w["marcus"]
    db.t["group_members"].append({"group_id": sisters["id"], "business_id": LC, "contact_id": w["eve"], "role": "leader", "co_leader": True})
    db.t["groups"] += [
        {"id": TEAM, "business_id": LC, "name": "Praise and Worship", "active": True, "kind": "team",
         "answers_to_contact_id": None, "course_id": None, "serve_option": "Praise and Worship Team"},
        {"id": CLASSG, "business_id": LC, "name": "New Members class", "active": True, "kind": "class",
         "answers_to_contact_id": None, "course_id": COURSE, "serve_option": None}]
    db.t["group_members"].append({"group_id": CLASSG, "business_id": LC, "contact_id": w["iris"], "role": "leader", "co_leader": False})
    db.t["serve_teams"] = [{"group_id": TEAM, "business_id": LC, "owner": "churchsavvy"}]
    db.t["academy_courses"] = [{"id": COURSE, "business_id": LC, "title": "New Members", "status": "published", "private": False},
                               {"id": COURSE2, "business_id": LC, "title": "The Making", "status": "published", "private": False}]
    db.t["academy_teachers"] = [{"course_id": COURSE, "email": "IRIS@lovecity.org", "role": "teacher"},
                                {"course_id": COURSE2, "email": "ivy@lovecity.org", "role": "teacher"}]
    db.t["worship_team"] = [{"business_id": LC, "name": "Ruth O.", "email": "ruth@lovecity.org", "roles": ["worship"], "status": "active"},
                            {"business_id": LC, "name": "Booth", "email": "paul@lovecity.org", "roles": ["booth"], "status": "active"}]
    db.t["space_leaders"] = [{"business_id": LC, "contact_id": w["cora"], "space": "kids", "background_check_on": "2026-01-01"}]
    return db


def _rows(out, **match):
    return [r for r in out["rows"] if all(r.get(k) == v for k, v in match.items())]


def _of(out, name):
    return [r for r in out["rows"] if (r["who"] or {}).get("name") == name]


def test_role_holders_and_who_they_answer_to(lc):
    out = cla.everyone(church(lc, LC))
    marcus = next(r for r in _of(out, "Marcus Taylor") if r["kind"] == "role")
    assert marcus["leads"] == "Elders" and marcus["answers_to"]["name"] == "Jessica McCloud" and marcus["fallback"] is None
    tanya = next(r for r in _of(out, "Tanya Brooks") if r["kind"] == "role")
    assert tanya["answers_to"] is None and tanya["fallback"].endswith("(whoever holds it)")
    tasha = next(r for r in _of(out, "Tasha Williams") if r["kind"] == "role")
    assert tasha["leads"].startswith("Hospitality Team · ")


def test_group_leads_and_co_leaders_by_kind(lc):
    out = cla.everyone(church(lc, LC))
    gloria = _of(out, "Gloria Hunt")[0]
    assert gloria["kind"] == "group" and gloria["leads"] == "Sisters in the City" and not gloria["co_leader"]
    assert gloria["answers_to"]["name"] == "Marcus Taylor"
    eve = next(r for r in _of(out, "Eve Hall") if r["kind"] == "group")
    assert eve["co_leader"] and eve["answers_to"]["name"] == "Marcus Taylor"      # one person a group
    yolanda = next(r for r in _of(out, "Yolanda Reed") if r["kind"] == "group")
    assert yolanda["answers_to"] is None and yolanda["fallback"] == "the Youth department’s leader"


def test_a_class_teacher_shows_once_with_both(lc):
    out = cla.everyone(church(lc, LC))
    iris = [r for r in _of(out, "Iris Bell") if r["kind"] in ("group", "teacher")]
    assert len(iris) == 1 and iris[0]["kind"] == "group" and iris[0]["group_kind"] == "class"
    assert iris[0]["teaches"] == {"id": COURSE, "title": "New Members"}
    ivy = [r for r in _of(out, "Ivy Lane") if r["kind"] == "teacher"]
    assert len(ivy) == 1 and ivy[0]["leads"] == "The Making"


def test_the_worship_part_is_a_worship_team_leader_once(lc):
    out = cla.everyone(church(lc, LC))
    ruth = [r for r in _of(out, "Ruth Okafor") if r["kind"] == "worship"]
    assert len(ruth) == 1 and ruth[0]["leads"] == "Praise and Worship" and ruth[0]["part"] == "Worship"
    assert not [r for r in out["rows"] if r["kind"] == "worship" and (r["who"] or {}).get("name") == "Paul Mensah"]
    # Ruth leading the team herself: once, on the team's own row.
    lc.t["group_members"].append({"group_id": TEAM, "business_id": LC, "contact_id": lc.who[LC]["ruth"], "role": "leader", "co_leader": False})
    out = cla.everyone(church(lc, LC))
    assert [r["kind"] for r in _of(out, "Ruth Okafor") if r["kind"] in ("worship", "group")] == ["group"]


def test_teams_and_gaps(lc):
    out = cla.everyone(church(lc, LC))
    team = next(t for t in out["teams"] if t["group_id"] == TEAM)
    assert team == {"group_id": TEAM, "name": "Praise and Worship", "sunday": True, "serve_option": "Praise and Worship Team",
                    "leaders": []}
    assert {g["group_id"] for g in out["gaps"]} == {TEAM}
    assert out["counts"]["no_leader"] == 1 and out["counts"]["role_only"] >= 1
    assert _rows(out, kind="kids")[0]["who"]["name"] == "Cora Diaz"


def test_before_the_file_it_is_whole_and_asks_for_nothing_new(lc, monkeypatch):
    real = sb_clients.sb_get_as_service
    asked = []

    def get(path, *a, **k):
        if any(c in path for c in ("answers_to_contact_id,course_id", "co_leader")) or \
                (path.startswith("/groups?") and "answers_to_contact_id" in path):
            asked.append(path)
            return None
        return real(path, *a, **k)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    out = cla.everyone(church(lc, LC))
    assert out["group_leads_ready"] is False
    assert asked and all(p.endswith("&limit=1") for p in asked)      # the probes only, never a read
    assert _of(out, "Gloria Hunt")[0]["kind"] == "group" and _of(out, "Gloria Hunt")[0]["answers_to"] is None


def _client(monkeypatch, role):
    import business_access
    import church_router
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: role)
    app = FastAPI()
    app.include_router(church_router.router)
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id="u-x", email="x@example.com", user_metadata={})))
    return TestClient(app)


@pytest.mark.parametrize("role,code", [("owner", 200), ("manager", 200), ("member", 404), ("viewer", 404)])
def test_the_route_is_a_manager_seat_and_up(lc, monkeypatch, role, code):
    r = _client(monkeypatch, role).get(f"/church/leaders/everyone?business_id={LC}")
    assert r.status_code == code, r.text


def test_a_failed_read_is_a_503(lc, monkeypatch):
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path, *a, **k: None if path.startswith("/space_leaders") else real(path, *a, **k))
    r = _client(monkeypatch, "owner").get(f"/church/leaders/everyone?business_id={LC}")
    assert r.status_code == 503 and r.json()["detail"] == cla.UNREAD


# ── M-8 review S2: the worship team is the Sunday hub's own ──────────

def test_no_churchsavvy_worship_team_lists_no_worship_part(lc):
    lc.t["serve_teams"] = [{"group_id": TEAM, "business_id": LC, "owner": None}]        # the hub wants churchsavvy
    out = cla.everyone(church(lc, LC))
    assert [r for r in out["rows"] if r["kind"] == "worship"] == []                     # the hub's Planner, not a team leader


def test_a_vocal_team_is_the_worship_team(lc):
    next(g for g in lc.t["groups"] if g["id"] == TEAM)["name"] = "Vocal Team"
    out = cla.everyone(church(lc, LC))
    assert [r["leads"] for r in out["rows"] if r["kind"] == "worship"] == ["Vocal Team"]


# ── M-8 review M1: the lead is the earliest row, on every read ───────

def test_the_lead_is_the_earliest_plain_leader(lc):
    w = lc.who[LC]
    sisters = next(g for g in lc.t["groups"] if g["business_id"] == LC and g["name"] == "Sisters in the City")
    for m in lc.t["group_members"]:
        if m["group_id"] == sisters["id"]:
            m.update(co_leader=False, created_at="2026-10-01T00:00:00+00:00" if m["contact_id"] == w["gloria"]
                     else "2026-11-20T00:00:00+00:00")
    out = cla.everyone(church(lc, LC))
    rows = {r["who"]["name"]: r for r in out["rows"] if r["kind"] == "group" and r["leads"] == "Sisters in the City"}
    assert rows["Gloria Hunt"]["co_leader"] is False and rows["Eve Hall"]["co_leader"] is True
