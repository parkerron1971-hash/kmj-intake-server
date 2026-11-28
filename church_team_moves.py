"""church_team_moves.py — the old Team leader rows onto the team itself (M-8).

Before M-8, Leaders & roles named a Serve team's leader as a role holder
whose `scope` was the team's name on the Serve card (church_leader_roles,
covers = team). The Sunday hub (M-7) and everything since read the team's own
leader row (group_members.role = 'leader'), so someone named the old way is
not a team leader in the hub. This lists those rows and, when the office says
yes, adds each one to its team's own leaders. Nothing moves on its own
(Kevin sees the list first, from the review), and nothing is taken away: the
role row stays, so a Serve sign-up still finds them either way.

    GET  /church/leaders/team-moves?business_id=          the list
    POST /church/leaders/team-moves/apply?business_id=    {holder_ids: [...]}

Each row says what would happen: `lead` (the team has no leader: they become
its lead), `co_leader` (it has one: they join as a co-leader), `already`
(they lead it now), `asked` (they were asked and haven't said yes: never
moved; name them on the team once they do), or `no_team` (no serving team by
that name or Serve choice yet: make the team first). The owner or an admin.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import sb_clients
from business_access import business_access

router = APIRouter(tags=["church"])

UNREAD = "Your team leaders couldn't be read just now. Try again."
UNSAVED = "That didn't save. Nothing else changed. Try again."
WORDS = {"lead": "Becomes the team's leader", "co_leader": "Joins as a co-leader", "already": "Already leads the team",
         "asked": "Asked, hasn't said yes: name them on the team once they do",
         "no_team": "No serving team by that name yet: make the team first"}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, UNREAD)
    return rows


def plan(biz: str) -> Dict[str, Any]:
    import church_follow_up as cfu
    import church_roles as cr
    defs = cr.defs(biz)
    holders = cfu.roles(biz)
    if defs is None or holders is None:
        raise HTTPException(503, UNREAD)
    team_keys = {d["key"] for d in defs if d.get("covers") == "team"}
    q = _q(biz)
    has_choice = isinstance(sb_clients.sb_get_as_service(f"/groups?business_id=eq.{q}&select=serve_option&limit=1"), list)
    has_co = isinstance(sb_clients.sb_get_as_service(f"/group_members?business_id=eq.{q}&select=co_leader&limit=1"), list)
    groups = _need(f"/groups?business_id=eq.{q}&kind=eq.team&active=eq.true"
                   f"&select=id,name{',serve_option' if has_choice else ''}&order=name.asc&limit=500")
    by_choice: Dict[str, Dict[str, Any]] = {}
    for g in groups:
        for label in ((g.get("serve_option") if has_choice else None), g.get("name")):
            if label and cfu._norm(label) not in by_choice:
                by_choice[cfu._norm(label)] = g
    leads = _need(f"/group_members?business_id=eq.{q}&role=eq.leader&select=group_id,contact_id&limit=2000") if groups else []
    rows = []
    for h in holders:
        if h["role"] not in team_keys or not h.get("scope"):
            continue
        g = by_choice.get(cfu._norm(h["scope"]))
        mine = [str(r["contact_id"]) for r in leads if g and str(r["group_id"]) == str(g["id"])]
        if h.get("status") != "active":
            will = "asked"
        elif not g:
            will = "no_team"
        elif h["contact_id"] in mine:
            will = "already"
        else:
            will = "co_leader" if mine else "lead"
        rows.append({"holder_id": h["id"], "contact_id": h["contact_id"], "name": h["name"], "status": h.get("status"),
                     "serve_choice": h["scope"], "team": {"group_id": str(g["id"]), "name": g.get("name") or ""} if g else None,
                     "will": will, "says": WORDS[will]})
    return {"rows": rows, "co_leaders_ready": has_co}


def apply(biz: str, holder_ids: List[str]) -> Dict[str, Any]:
    p = plan(biz)
    want = {str(x) for x in holder_ids}
    moved = []
    for r in p["rows"]:
        if r["holder_id"] not in want or r["will"] not in ("lead", "co_leader"):
            continue
        row = {"group_id": r["team"]["group_id"], "contact_id": r["contact_id"], "business_id": biz, "role": "leader"}
        if p["co_leaders_ready"]:
            row["co_leader"] = r["will"] == "co_leader"
        saved = sb_clients.sb_post_as_service("/group_members?on_conflict=group_id,contact_id", [row],
                                              prefer="resolution=merge-duplicates,return=representation")
        if not isinstance(saved, list) or not saved:
            raise HTTPException(503, UNSAVED)
        moved.append({"holder_id": r["holder_id"], "name": r["name"], "team": r["team"]["name"], "as": r["will"]})
    return {"moved": moved, **plan(biz)}


@router.get("/leaders/team-moves")
def team_moves(business_id: str = Query(...), biz: Dict[str, Any] = Depends(business_access("admin"))):
    return plan(str(biz["id"]))


class MovesIn(BaseModel):
    holder_ids: List[str]


@router.post("/leaders/team-moves/apply")
def team_moves_apply(body: MovesIn, business_id: str = Query(...), biz: Dict[str, Any] = Depends(business_access("admin"))):
    if not body.holder_ids or len(body.holder_ids) > 100:
        raise HTTPException(400, "Pick the people to move, at most 100 at once.")
    return apply(str(biz["id"]), body.holder_ids)
