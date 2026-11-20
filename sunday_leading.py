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
#
# A department's leader and its overseer (My department, docs/CHURCH_SCHEDULE.md
# section 8.8; the pastor's call 2, 2026-11-20): the same, for any of the
# Volunteers' Sunday teams that hang from a department they lead or oversee
# on the leaders map (church_week.department_team, asked on every write, so
# the check is the server's). Worship and production (ChurchSavvy's teams)
# stay read only for them (call 4). When they ask, offer or fill on a team
# someone else leads, that team's own leaders are told: a note of the
# serving kind (member_push, its push and the church's conversation),
# handed on after the write (member_push._later, never able to fail it),
# claimed once (ref_id), and waiting out the church's quiet hours.
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

import sunday_planning as sp
from sunday_planning import _ids, _q, _read

logger = logging.getLogger(__name__)

WEEKS = 5
KIND = "serving"            # member_push's kind: the team leader's own box on My serving decides


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
    """The team, when this member may schedule it: one they lead, or a
    Volunteers' team of a department they lead or oversee (then
    `by_department` is True, and its own leaders hear of what they do)."""
    team = next((t for t in led_teams(biz_id, cid) if t["group_id"] == gid), None)
    if team:
        return team
    import church_week
    team = church_week.department_team(biz_id, cid, gid) if sp.mode() != "off" else None
    if not team:
        raise HTTPException(404, "You don't lead that team.")
    return {**team, "by_department": True}


def _place_of_mine(biz_id: str, cid: str, pid: str):
    """(the place, its team) when the place is on a team this member may schedule."""
    place = sp._place_row(biz_id, pid)
    return place, _mine(biz_id, cid, str(place["group_id"]))


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
    # An event date (serve_dates) is the volunteer teams' only: a worship or production team's leader never sees it.
    services = [s for s in board.services if sp.serves(s, t)]
    rows = [r for r in board.rows if str(r["position_id"]) in place_ids and str(r["service_id"]) in
            {s["id"] for s in services}]
    who = sp._people(biz_id, [r.get("contact_id") for r in rows])
    return {
        "team": {**team, "call_time": t.get("call_time"), "max_month": t.get("max_month"), "places": t["places"],
                 "people": t["people"]},
        "services": services,
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
    place, team = _place_of_mine(biz_id, str(me["id"]), pid)
    out = sp.do_ask(biz_id, sid, pid, slot, person, _asker(me))
    if team.get("by_department"):
        a = out["assignment"]
        _tell_its_leaders(biz, me, team, "ask", {"service_id": sid, "place": place.get("name"), "id": a["id"],
                                                  "person_name": a.get("name"), "at": a.get("asked_at")})
    return out


def offer(biz: Dict[str, Any], me: Dict[str, Any], sid: str, pid: str, slot: int) -> Dict[str, Any]:
    biz_id = str(biz["id"])
    place, team = _place_of_mine(biz_id, str(me["id"]), pid)
    out = sp.do_offer(biz_id, sid, pid, slot, _asker(me))
    if team.get("by_department"):
        a = out["assignment"]
        _tell_its_leaders(biz, me, team, "offer", {"service_id": sid, "place": place.get("name"), "id": a["id"],
                                                    "at": a.get("asked_at")})
    return out


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
    team = _mine(biz_id, str(me["id"]), gid)
    out = sp.do_fill(biz_id, WEEKS, None, gid)
    if team.get("by_department") and out.get("asked"):
        _tell_its_leaders(biz, me, team, "fill", {"n": out["asked"], "id": out["ids"][0]})
    return out


def unfill(biz: Dict[str, Any], me: Dict[str, Any], gid: str, ids: List[str]) -> Dict[str, Any]:
    """Take back the fill: only asks on their team's places, not yet sent."""
    biz_id = str(biz["id"])
    _mine(biz_id, str(me["id"]), gid)
    places = {str(p["id"]) for p in _read(f"/serve_positions?business_id=eq.{_q(biz_id)}&group_id=eq.{_q(gid)}&select=id")}
    rows = _read(f"/serve_assignments?business_id=eq.{_q(biz_id)}&id=in.({_ids(ids)})&select=id,position_id") if ids else []
    return sp.do_unfill(biz_id, [str(r["id"]) for r in rows if str(r["position_id"]) in places])


# ─── Telling the team's own leaders (My department, call 2) ───────────

def _on(at: datetime) -> str:
    """"Sunday, Nov 22"."""
    return f"{at.strftime('%A')}, {at.strftime('%b')} {at.day}"


def words(what: str, asker: str, team: str, ctx: Dict[str, Any]) -> Dict[str, str]:
    """(title, body) of the note a team's own leader gets. Who did it, what
    and when; nothing private (a lock screen is not)."""
    if what == "fill":
        n = int(ctx.get("n") or 0)
        return {"title": f"{team}: {n} place{'' if n == 1 else 's'} asked for",
                "body": f"{asker} asked people for the next five Sundays. You'll see who on your team's Sundays."}
    day = ctx.get("day") or "a coming Sunday"
    if what == "offer":
        return {"title": f"{ctx['place']} was offered to {team}",
                "body": f"{asker} offered {ctx['place']}, {day}, to the whole team. The first yes takes it."}
    return {"title": f"{ctx.get('person_name') or 'Someone'} was asked for {ctx['place']}",
            "body": f"{asker} asked for {team}, {day}. You'll see it on your team's Sundays."}


def _tell_its_leaders(biz: Dict[str, Any], me: Dict[str, Any], team: Dict[str, Any], what: str,
                      ctx: Dict[str, Any]) -> None:
    """Hand the note on once the write has landed: off this request
    (member_push._later), and never able to fail the write it follows."""
    try:
        import member_push
        biz, me, team, ctx = dict(biz), dict(me), dict(team), dict(ctx)
        member_push._later(lambda: tell(biz, me, team, what, ctx))
    except Exception:  # noqa: BLE001 — a note is never worth failing the write it is about
        logger.warning("sunday leading: a note to a team's leaders wasn't handed on (%s)", what, exc_info=True)


def tell(biz: Dict[str, Any], me: Dict[str, Any], team: Dict[str, Any], what: str, ctx: Dict[str, Any]) -> int:
    """Tell the team's own leaders (never the one who did it) what a
    department's leader or overseer just did on their team: {what} is ask,
    offer or fill. One note a leader, claimed once (member_push_sends'
    ref_id), waiting out the church's quiet hours for whoever keeps them on.
    Phones reached."""
    import member_push
    biz_id, gid, cid = str(biz["id"]), str(team["group_id"]), str(me["id"])
    leaders = sorted({str(r["contact_id"]) for r in _read(
        f"/group_members?business_id=eq.{_q(biz_id)}&group_id=eq.{_q(gid)}&role=eq.leader&select=contact_id&limit=50")
        if r.get("contact_id")} - {cid})
    if not leaders:
        return 0
    ctx = dict(ctx)
    url = f"/my/lead/sundays?team={gid}"
    if ctx.get("service_id"):
        svc = _read(f"/worship_services?id=eq.{_q(ctx['service_id'])}&business_id=eq.{_q(biz_id)}"
                    f"&select=starts_at&limit=1")
        try:
            at = datetime.fromisoformat(str(svc[0]["starts_at"]).replace("Z", "+00:00")).astimezone(sp._zone(biz_id))
            ctx["day"] = _on(at)
        except (IndexError, KeyError, TypeError, ValueError):
            pass
        url += f"&day={ctx['service_id']}"
    w = words(what, _asker(me), team.get("name") or "Your team", ctx)
    reached = 0
    for leader in leaders:
        reached += member_push.send(biz, KIND, title=w["title"], body=w["body"], url=url, contact_ids=[leader],
                                    ref_id=f"dept-{what}-{ctx.get('id')}-{ctx.get('at') or ''}-{leader}"[:200],
                                    tag=f"serving-dept-{gid}"[:60], wait=True)
    return reached
