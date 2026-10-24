# sunday_leading.py — ChurchSavvy Planning, step 7: a team's own leader
# schedules their team (Kevin, 2026-10-23, call 4: "TEAM LEADERS schedule
# their own team (admins anyone)"; design canvas Ct88v7pxpq5a4PGYX3MuQQ,
# board 4: "Marcus leads Production, so he sees and fills Production. He
# still sees who on his team is serving on another team that hour, so he
# never double-books them"). The pages are member_portal_leading.py, in the
# member app's Lead tab: a leader is a member (a contact), never a seat.
#
# A leader is someone the church made a leader of the Sunday team's group
# (group_members.role = 'leader'). They see their team's Sundays and do what
# the office does for that team only: ask someone on the team, offer a place
# to the whole team, take back an ask, fill the coming Sundays fairly and
# take that fill back. Every write checks that the place is their team's.
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

import sunday_planning as sp
from sunday_planning import _ids, _q, _read

WEEKS = 5


def led_teams(biz_id: str, cid: str) -> List[Dict[str, Any]]:
    """The Sunday teams this member leads, by name."""
    if sp.mode() == "off":
        return []
    led = [str(r["group_id"]) for r in _read(
        f"/group_members?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}&role=eq.leader&select=group_id&limit=200")]
    if not led:
        return []
    serve = {str(t["group_id"]) for t in _read(
        f"/serve_teams?business_id=eq.{_q(biz_id)}&group_id=in.({_ids(led)})&select=group_id")}
    if not serve:
        return []
    groups = _read(f"/groups?business_id=eq.{_q(biz_id)}&id=in.({_ids(serve)})&active=eq.true&select=id,name&order=name.asc")
    return [{"group_id": str(g["id"]), "name": g["name"]} for g in groups]


def leads_a_team(biz_id: str, cid: str) -> bool:
    try:
        return bool(led_teams(biz_id, cid))
    except HTTPException:
        return False


def _mine(biz_id: str, cid: str, gid: str) -> Dict[str, Any]:
    team = next((t for t in led_teams(biz_id, cid) if t["group_id"] == gid), None)
    if not team:
        raise HTTPException(404, "You don't lead that team.")
    return team


def _place_of_mine(biz_id: str, cid: str, pid: str) -> Dict[str, Any]:
    place = sp._place_row(biz_id, pid)
    _mine(biz_id, cid, str(place["group_id"]))
    return place


def team_view(biz: Dict[str, Any], cid: str, gid: str, start: Optional[str] = None) -> Dict[str, Any]:
    """Their team's coming Sundays: each place and who holds it, and for
    each person on the team whether they're away or already serving that
    hour on another team (so they're never double-booked)."""
    biz_id = str(biz["id"])
    team = _mine(biz_id, cid, gid)
    board = sp._Board(biz_id, start, WEEKS)
    t = next((x for x in board.teams if x["group_id"] == gid), None)
    if not t:
        raise HTTPException(404, "You don't lead that team.")
    place_ids = {p["id"] for p in t["places"]}
    rows = [r for r in board.rows if str(r["position_id"]) in place_ids and str(r["service_id"]) in
            {s["id"] for s in board.services}]
    who = sp._people(biz_id, [r.get("contact_id") for r in rows])
    return {
        "team": {**team, "call_time": t.get("call_time"), "max_month": t.get("max_month"), "places": t["places"],
                 "people": t["people"]},
        "services": board.services,
        "assignments": [sp._assignment_out(r, who) for r in rows],
        "board": board,
    }


def candidates(biz: Dict[str, Any], cid: str, sid: str, pid: str) -> List[Dict[str, Any]]:
    biz_id = str(biz["id"])
    _place_of_mine(biz_id, cid, pid)
    return sp._service_board(biz_id, sid).candidates(sid, pid)


def _asker(me: Dict[str, Any]) -> str:
    return ((me.get("name") or "").strip() or "Your team's leader")[:80]


def ask(biz: Dict[str, Any], me: Dict[str, Any], sid: str, pid: str, slot: int, person: str) -> Dict[str, Any]:
    biz_id = str(biz["id"])
    _place_of_mine(biz_id, str(me["id"]), pid)
    return sp.do_ask(biz_id, sid, pid, slot, person, _asker(me))


def offer(biz: Dict[str, Any], me: Dict[str, Any], sid: str, pid: str, slot: int) -> Dict[str, Any]:
    biz_id = str(biz["id"])
    _place_of_mine(biz_id, str(me["id"]), pid)
    return sp.do_offer(biz_id, sid, pid, slot, _asker(me))


def take_back(biz: Dict[str, Any], me: Dict[str, Any], aid: str) -> Dict[str, Any]:
    """An ask nobody has said yes to: theirs to take back. A yes stays: taking
    someone off a Sunday they agreed to is a conversation, then the office."""
    biz_id = str(biz["id"])
    row = sp._assignment(biz_id, aid)
    _place_of_mine(biz_id, str(me["id"]), str(row["position_id"]))
    if row["status"] == "yes":
        raise HTTPException(409, "They already said yes. Talk with them first; the office can take them off.")
    return sp.do_take_back(biz_id, aid)


def fill(biz: Dict[str, Any], me: Dict[str, Any], gid: str) -> Dict[str, Any]:
    biz_id = str(biz["id"])
    _mine(biz_id, str(me["id"]), gid)
    return sp.do_fill(biz_id, WEEKS, None, gid)


def unfill(biz: Dict[str, Any], me: Dict[str, Any], gid: str, ids: List[str]) -> Dict[str, Any]:
    """Take back the fill: only asks on their team's places, not yet sent."""
    biz_id = str(biz["id"])
    _mine(biz_id, str(me["id"]), gid)
    places = {str(p["id"]) for p in _read(f"/serve_positions?business_id=eq.{_q(biz_id)}&group_id=eq.{_q(gid)}&select=id")}
    rows = _read(f"/serve_assignments?business_id=eq.{_q(biz_id)}&id=in.({_ids(ids)})&select=id,position_id") if ids else []
    return sp.do_unfill(biz_id, [str(r["id"]) for r in rows if str(r["position_id"]) in places])
