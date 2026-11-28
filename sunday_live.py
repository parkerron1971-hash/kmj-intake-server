# sunday_live.py — the one Sunday hub's plan writes (mission M-7): the
# pastor's "open for live changes" mark, whose each plan item is, and who
# may change which part of a plan once SUNDAY_HUB is on.
#
#   PUT /worship/services/{service_id}/live-ok   {business_id, on}     owner and Admin seats
#   GET /worship/team-areas?business_id=                              any Sunday reader
#   PUT /worship/team-areas                      {business_id, areas}  the setup part
#
# With the hub on, a plan write (worship_show_router: create, save, take out)
# asks check_plan_write instead of the Plan part alone (Kevin's decisions
# church-office-1, 2026-11-27):
#   pastor, planner   the whole plan, as before
#   team_leader       only their own team's items (an item's `team`, else its
#                     kind's team area). Adding, taking out or moving items,
#                     and the title, time or notes, are the planner's
#   media_tech        nothing, except on a Sunday the pastor opened for live
#                     changes: then that Sunday's whole plan, until its day ends
# The booth's typo fix (POST /worship/songs/{id}/fix, the "fix" part) is not a
# plan write and stays open on every Sunday. With the hub off, nothing here
# is asked: the Plan part decides, as before.
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
import sunday_hub as hub
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])

NOT_OPENED = "The pastor hasn't opened this Sunday for live changes."
THE_ORDER = "The order is the planner's. You can change your team's items."
ONLY_PASTOR = "Only the pastor or an admin opens a Sunday for live changes."
LIVE_ONLY = "On a live Sunday, media and tech change its items and notes. Its time and name stay the planner's."
# What media & tech may change on a Sunday the pastor opened: the plan's
# items and notes, never when it is, its name, or whether it's a template.
LIVE_FIELDS = ("items", "notes")
SERVICE_FIELDS = ("title", "starts_at", "notes", "is_template")


def _q(v: Any) -> str:
    from urllib.parse import quote
    return quote(str(v), safe="")


# ─── who may change which part of a plan ─────────────────────────────


def whole_plan(st: Dict[str, Any]) -> bool:
    return bool({"pastor", "planner"} & set(st["roles"]))


def check_plan_write(biz: str, user: Any, roles: Set[str], op: str, sid: Optional[str] = None,
                     current: Optional[Dict[str, Any]] = None, fields: Optional[Dict[str, Any]] = None) -> None:
    """With the hub on, 403 unless this login may make this plan write.
    `roles` are its parts (worship_team.roles_of), `op` is create, save or
    remove; a save names the service, its row and the cleaned fields. With
    the hub off, the Plan part alone decides (worship_team.require)."""
    import worship_team as wt
    if not hub.open_to(user):
        if not wt.can(roles, "plan"):
            raise HTTPException(403, wt.REFUSED["plan"])
        return
    st = hub.standing(biz, user)
    if whole_plan(st):
        return
    if op == "save" and sid and roles & {"booth", "media"} and hub.live_ok(biz, sid)["on"]:
        if fields and any(k not in LIVE_FIELDS for k in fields):
            raise HTTPException(403, LIVE_ONLY)
        return
    if op == "save" and "team_leader" in st["roles"] and current is not None and fields is not None:
        _leader_scope(biz, st, current, fields)
        return
    if roles & {"booth", "media"} or "media_tech" in st["roles"]:
        raise HTTPException(403, NOT_OPENED)
    if "team_leader" in st["roles"]:
        raise HTTPException(403, THE_ORDER)
    raise HTTPException(403, wt.REFUSED["plan"])


def _leader_scope(biz: str, st: Dict[str, Any], current: Dict[str, Any], fields: Dict[str, Any]) -> None:
    """A team leader's save: the same items in the same order, and only
    items of teams they lead changed (never an item's team)."""
    if any(k in fields for k in SERVICE_FIELDS):
        raise HTTPException(403, THE_ORDER)
    if "items" not in fields:
        return
    old: List[Dict[str, Any]] = current.get("items") or []
    new: List[Dict[str, Any]] = fields["items"] or []
    if [i.get("id") for i in old] != [i.get("id") for i in new]:
        raise HTTPException(403, THE_ORDER)
    teams = hub.sunday_teams(biz)
    names = {t["group_id"]: t["name"] for t in teams}
    areas = hub.team_areas(biz, teams)
    mine = {t["group_id"] for t in st["leads"]}
    for was, now in zip(old, new):
        if was == now:
            continue
        whose = hub.item_team(was, areas)
        if whose not in mine:
            raise HTTPException(403, f"That item is the {names.get(whose, 'planner')}'s."
                                if whose else "That item is the planner's.")
        if hub.item_team(now, areas) != whose:
            raise HTTPException(403, "Only the planner moves an item to another team.")


# ─── the live-changes mark ───────────────────────────────────────────


def _end_of_day(biz: str, starts_at: Optional[str]) -> datetime:
    """The end of the service's day on the church's clock (today's when it
    has no time yet), in UTC."""
    import business_marketing
    church = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=id,settings&limit=1") or [{"id": biz}]
    zone = business_marketing.business_tz(church[0])
    try:
        at = datetime.fromisoformat(str(starts_at).replace("Z", "+00:00")) if starts_at else None
    except ValueError:
        at = None
    day = (at or datetime.now(timezone.utc)).astimezone(zone).date()
    return datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=zone).astimezone(timezone.utc) - timedelta(seconds=1)


@router.put("/services/{service_id}/live-ok")
def put_live_ok(service_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """The pastor opens (or closes) one Sunday for live changes: media & tech
    may change its plan until its day ends on the church's clock."""
    import worship_show_router as wsr
    from worship_team import roles_of
    if not hub.open_to(user):
        raise HTTPException(404, "Not Found")
    wsr._gate(user)
    body = body or {}
    biz = wsr._uuid(body.get("business_id"))
    roles_of(biz, user, part=None)
    if not hub.standing(biz, user)["approve"]:
        raise HTTPException(403, ONLY_PASTOR)
    sid = wsr._uuid(service_id, "service")
    row = wsr._service(biz, sid)
    on = body.get("on") is True
    patch = ({"live_ok_until": _end_of_day(biz, row.get("starts_at")).isoformat(), "live_ok_by": str(user.id)}
             if on else {"live_ok_until": None, "live_ok_by": None})
    saved = sb_clients.sb_patch_as_service(f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select=id", patch)
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Nothing changed; try again.")
    return {"live_ok": hub.live_ok(biz, sid)}


def live_marks(biz: str) -> Dict[str, Dict[str, Any]]:
    """service id -> {until, by}, for the church's Sundays open for live
    changes now (one read for the list, one name a person who opened one).
    A failed read: no marks."""
    now = datetime.now(timezone.utc).isoformat()
    rows = sb_clients.sb_get_as_service(f"/worship_services?business_id=eq.{_q(biz)}&live_ok_until=gt.{_q(now)}"
                                        "&select=id,live_ok_until,live_ok_by&limit=50")
    if not isinstance(rows, list):
        return {}
    names: Dict[str, str] = {}
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        by = str(r.get("live_ok_by") or "")
        if by and by not in names:
            names[by] = hub.login_name(biz, by)
        out[str(r["id"])] = {"until": r["live_ok_until"], "by": {"name": names[by]} if by else None}
    return out


# ─── team areas ──────────────────────────────────────────────────────


@router.get("/team-areas")
def get_team_areas(business_id: str, user: AuthedUser = Depends(require_user)):
    import worship_show_router as wsr
    from worship_team import roles_of
    if not hub.open_to(user):
        raise HTTPException(404, "Not Found")
    wsr._gate(user)
    biz = wsr._uuid(business_id)
    roles_of(biz, user, part=None)
    teams = hub.sunday_teams(biz)
    return {"areas": hub.team_areas(biz, teams), "teams": teams}


@router.put("/team-areas")
def put_team_areas(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Sunday setup: whose each kind of plan item is (null: nobody's, the
    planner's). A kind left out goes back to the default by team name."""
    import worship_show_router as wsr
    import worship_team as wt
    if not hub.open_to(user):
        raise HTTPException(404, "Not Found")
    wsr._gate(user)
    body = body or {}
    biz = wsr._uuid(body.get("business_id"))
    wt.require(biz, user, "setup")
    areas = body.get("areas")
    if not isinstance(areas, dict) or any(k not in hub.AREA_KINDS for k in areas):
        raise HTTPException(400, "Areas are kinds of item, each a Sunday team or none")
    ids = {t["group_id"] for t in hub.sunday_teams(biz)}
    clean: Dict[str, Optional[str]] = {}
    for kind, gid in areas.items():
        if gid in (None, ""):
            clean[kind] = None
        elif str(gid).lower() in ids:
            clean[kind] = str(gid).lower()
        else:
            raise HTTPException(400, "That isn't one of the church's Sunday teams")
    saved = sb_clients.sb_post_as_service(
        "/worship_settings?on_conflict=business_id",
        {"business_id": biz, "team_areas": clean, "updated_at": datetime.now(timezone.utc).isoformat()},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list):
        raise HTTPException(503, "That didn't save. Try again.")
    return get_team_areas(biz, user)
