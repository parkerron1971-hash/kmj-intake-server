"""The one Sunday hub: team leaders in the office, and ministry operations
(sunday_planning.py, sunday_order.py; M-7, Kevin's decisions church-office-1,
2026-11-27).

Pins:
  * a team's own leader (a login whose person leads the team) asks, offers,
    takes back and fills their own team's spots from the office, and writes
    their team's note on the order; another team's spot, another team's
    note and the note for everyone stay refused
  * ministry operations (the ministry_ops duty) schedules the Volunteers'
    teams; worship and production's spots are refused ("...hasn't opened its
    spots to ministry operations.") until the pastor or that team's leader
    opens the team; then they are filled, and the team's leaders are told
  * opening a team: the owner, an Admin or that team's own leader; sent on
    its own; 404 with the switch off
  * Teams and Who serves when say which teams are open and which are mine
  * ministry_ops alone (no lane) schedules the Volunteers' teams
  * with the switch off, every rule is as before"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sunday_leading as sl  # noqa: E402
import sunday_order  # noqa: E402
from sunday_hub_fixture import BIZ, JO, KENDRA, MARCUS, PRODUCTION, WELCOME, WORSHIP, church  # noqa: E402,F401


@pytest.fixture
def board(church, monkeypatch):
    church.app.include_router(sunday_order.router)
    church.db.t["serve_notes"] = []
    church.db.KEYS = {**church.db.KEYS, "serve_notes": ("service_id", "item_id", "team")}
    as_ = church.as_
    assert as_("owner").post("/planning/sundays", json={"business_id": BIZ, "count": 2}).status_code == 200
    s1, s2 = (s["id"] for s in sorted(church.db.t["worship_services"], key=lambda s: s["starts_at"]))
    for s in church.db.t["worship_services"]:
        s["items"] = [{"id": "i1", "kind": "song", "song_id": None}]
    places = {}
    for gid, name, person in ((PRODUCTION, "Sound", KENDRA), (WELCOME, "Greeter", JO), (WORSHIP, "Keys", MARCUS)):
        r = as_("owner").post("/planning/positions", json={"business_id": BIZ, "group_id": gid, "name": name})
        assert r.status_code == 200, r.text
        pid = r.json()["place"]["id"] if "place" in r.json() else r.json()["position"]["id"]
        assert as_("owner").put(f"/planning/positions/{pid}/people", json={
            "business_id": BIZ, "people": [{"contact_id": person, "level": "trained"}]}).status_code == 200
        places[gid] = (pid, person)
    told = []
    monkeypatch.setattr(sl, "_tell_its_leaders", lambda biz, me, team, what, ctx: told.append((team["group_id"], what)))
    church.s1, church.s2, church.places, church.told = s1, s2, places, told
    return church


def _ask(c, who, gid, sid=None):
    pid, person = c.places[gid]
    return c.as_(who).post("/planning/ask", json={"business_id": BIZ, "service_id": sid or c.s2,
                                                  "position_id": pid, "contact_id": person})


def _open(c, who, gid, on=True, **extra):
    return c.as_(who).patch(f"/planning/teams/{gid}", json={"business_id": BIZ, "open_to_ops": on, **extra})


# ─── a team's own leader ──────────────────────────────────────────────

def test_a_leader_schedules_their_own_team(board):
    r = _ask(board, "leader", WELCOME)
    assert r.status_code == 200, r.text
    assert board.as_("leader").delete(f"/planning/assignments/{r.json()['assignment']['id']}",
                                      params={"business_id": BIZ}).status_code == 200
    pid, _ = board.places[WELCOME]
    assert board.as_("leader").post("/planning/offer", json={"business_id": BIZ, "service_id": board.s1,
                                                             "position_id": pid}).status_code == 200
    filled = board.as_("leader").post("/planning/fill", json={"business_id": BIZ, "group_id": WELCOME, "weeks": 2})
    assert filled.status_code == 200, filled.text
    back = board.as_("leader").post("/planning/unfill", json={"business_id": BIZ, "ids": filled.json()["ids"]})
    assert back.json()["taken_back"] == filled.json()["asked"]
    assert board.told == []                                  # their own team: nobody to tell


def test_a_leader_never_schedules_another_team(board):
    for gid in (PRODUCTION, WORSHIP):
        assert _ask(board, "leader", gid).status_code == 403
        assert board.as_("leader").post("/planning/fill", json={"business_id": BIZ, "group_id": gid}).status_code == 403
    # Someone else's ask on Production isn't theirs to take back.
    other = _ask(board, "owner", PRODUCTION).json()["assignment"]["id"]
    assert board.as_("leader").delete(f"/planning/assignments/{other}", params={"business_id": BIZ}).status_code == 403
    assert board.as_("leader").post("/planning/unfill", json={"business_id": BIZ, "ids": [other]}).json()["taken_back"] == 0


def test_a_leader_writes_their_teams_note(board):
    note = lambda team: board.as_("leader").put("/planning/order/notes", json={  # noqa: E731
        "business_id": BIZ, "service_id": board.s1, "item_id": "i1", "team": team, "note": "Doors at 10:45"})
    assert note(WELCOME).status_code == 200
    assert note(PRODUCTION).status_code == 403
    assert note("all").status_code == 403


# ─── ministry operations ─────────────────────────────────────────────

def test_ministry_ops_fills_the_volunteers_and_waits_to_be_opened(board):
    assert _ask(board, "ministry", WELCOME).status_code == 200
    r = _ask(board, "ministry", PRODUCTION)
    assert r.status_code == 403 and r.json()["detail"] == "Production's leader hasn't opened its spots to ministry operations."
    assert board.as_("ministry").post("/planning/fill", json={"business_id": BIZ, "group_id": WORSHIP}).status_code == 403
    assert _open(board, "owner", PRODUCTION).json() == {"group_id": PRODUCTION, "open_to_ops": True}
    assert _ask(board, "ministry", PRODUCTION).status_code == 200
    assert board.told == [(PRODUCTION, "ask")]
    assert _ask(board, "ministry", WORSHIP).status_code == 403          # still closed
    _open(board, "admin", PRODUCTION, on=False)
    assert _ask(board, "ministry", PRODUCTION, sid=board.s1).status_code == 403


def test_ministry_ops_alone_schedules_the_volunteers(board):
    board.state["duties"]["u-volsched"] = {"ministry_ops"}
    assert _ask(board, "volsched", WELCOME).status_code == 200
    assert _ask(board, "volsched", PRODUCTION).status_code == 403


# ─── opening a team ───────────────────────────────────────────────────

def test_who_opens_a_team(board):
    assert _open(board, "leader", WELCOME).status_code == 200                  # its own leader
    assert _open(board, "leader", PRODUCTION).status_code == 403
    for who in ("planner", "ministry", "booth", "csadmin"):
        r = _open(board, who, PRODUCTION)
        assert r.status_code == 403, who
    assert _open(board, "owner", PRODUCTION, max_month=2).status_code == 400   # on its own
    assert board.as_("owner").patch(f"/planning/teams/{PRODUCTION}",
                                    json={"business_id": BIZ, "open_to_ops": "yes"}).status_code == 400


def test_the_reads_say_open_and_mine(board):
    _open(board, "owner", PRODUCTION)
    teams = {t["group_id"]: t for t in board.as_("leader").get("/planning/teams", params={"business_id": BIZ}).json()["teams"]}
    assert (teams[PRODUCTION]["open_to_ops"], teams[PRODUCTION]["mine"]) == (True, False)
    assert (teams[WELCOME]["open_to_ops"], teams[WELCOME]["mine"]) == (False, True)
    sched = board.as_("ministry").get("/planning/schedule", params={"business_id": BIZ}).json()["teams"]
    assert {t["group_id"]: t["open_to_ops"] for t in sched}[PRODUCTION] is True


# ─── the switch off ───────────────────────────────────────────────────

def test_off_every_rule_is_as_before(board, monkeypatch):
    monkeypatch.setenv("SUNDAY_HUB", "off")
    assert _ask(board, "leader", WELCOME).status_code == 403                    # a leader schedules from the member app
    assert _open(board, "owner", PRODUCTION).status_code == 404
    assert _ask(board, "ministry", WELCOME).status_code == 200                  # serve_schedule, as before
    assert _ask(board, "ministry", PRODUCTION).status_code == 403
    teams = board.as_("owner").get("/planning/teams", params={"business_id": BIZ}).json()["teams"]
    assert all("open_to_ops" not in t and "mine" not in t for t in teams)
