# sunday_hub.py — Church Savvy's one Sunday hub (mission M-7; Kevin's
# decisions church-office-1, 2026-11-27, kai/reviews/church-savvy-sunday-
# structure.md). The switch, who holds which Sunday role, and the question
# the read wall asks.
#
# SUNDAY_HUB = off | owner | on (default off). One launch: everything merges
# dark, then `on` turns the hub, the roles and every wall on for every church
# at the same moment. Off answers exactly as before, and stays the safety
# switch after launch.
#
# The roles are built from what a church already gives out, never from
# title words (test_church_no_title_words): seats (business_users), duties
# (church_duties), ChurchSavvy's team parts (worship_team) and the leaders of
# its Sunday teams (group_members.role = 'leader'). One person can hold
# several; the owner and the Admin logins hold them all.
#   pastor        the owner and Admin seats: everything; approves a Sunday
#                 for live changes; sees the offering
#   planner       the Planner or ChurchSavvy Admin part (a person invited to
#                 it, or the sunday_plan / production_schedule /
#                 churchsavvy_team duty): the whole plan
#   team_leader   leads a Sunday team, or holds the Worship part (the
#                 church's worship team; Planner where it has none yet): their
#                 own team's spots, notes and part of the plan
#   media_tech    the Booth or Media part (or the stream duty): screens, the
#                 stream, clips; the plan only on a Sunday the pastor opened
#   ministry_ops  the ministry_ops duty (the Sunday & Serving lane's): every
#                 team's serving; worship and production filled only once
#                 their leader or the pastor opens the team
# A reader is anyone holding a role, a Sunday duty or a team part. With the
# switch on, nobody else reads a Sunday plan (the wall, require_reader).
#
#   GET  /worship/status            (worship_router) carries `sunday_hub` and `sunday`
#   PUT  /worship/service-word      {business_id, word: "Sunday" | "service" | null}
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Set
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])

ROLES = ("pastor", "planner", "team_leader", "media_tech", "ministry_ops")
ROLE_LABEL = {"pastor": "Pastor", "planner": "Planner", "team_leader": "Team leader",
              "media_tech": "Media & tech", "ministry_ops": "Ministry operations"}
# The duties (church_duties.CATALOG) that are Sunday work: whoever holds one
# reads the Sunday plans, even holding no role (the announcements, the
# sermon, the count).
SUNDAY_DUTIES: FrozenSet[str] = frozenset({
    "sunday_plan", "production_schedule", "churchsavvy_team", "announcements", "stream", "sermons", "clips",
    "serve_schedule", "serve_teams", "new_volunteers", "background_checks", "serving_thanks", "events",
    "outreach_nights", "attendance", "ministry_ops"})
# The Ministry operations role is the whole volunteer side: given together,
# these are the Sunday & Serving lane's duties (church_duties.STARTER).
MINISTRY_OPS_DUTIES = ("ministry_ops", "serve_schedule", "serve_teams", "new_volunteers", "background_checks",
                       "serving_thanks", "events", "outreach_nights", "attendance")
# A Sunday team that is the church's worship team, or its media and tech
# team, by name: the defaults for whose a plan item is (team areas) and who
# the Worship part leads. A church can say otherwise in Sunday setup.
WORSHIP_WORDS = ("worship", "praise", "band", "choir", "music", "singers", "vocal")
PRODUCTION_WORDS = ("production", "sound", "audio", "camera", "stream", "media", "tech", "booth", "lights",
                    "slides", "projection")
WORDS = ("Sunday", "service")
WALL = "Sunday plans open to the church's Sunday roles."


# ─── the switch ──────────────────────────────────────────────────────


def mode() -> str:
    m = (os.environ.get("SUNDAY_HUB") or "off").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: Any) -> bool:
    """Whether the hub is on for this login: every church at `on`, the
    platform owner's login alone at `owner`, nobody at `off` (a typo'd value
    reads as off)."""
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (getattr(user, "email", None) or "").strip().lower() == owner
    return False


# ─── reads ───────────────────────────────────────────────────────────


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _ids(values: Any) -> str:
    return ",".join(_q(v) for v in values)


def _need(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise HTTPException(503, "Who does what on Sunday couldn't be read just now. Try again.")
    return rows


def _escape_ilike(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def person_of(biz: str, user: Any) -> Optional[str]:
    """The church's own person (contacts.id) behind this login: the one its
    seat is tied to (business_users.contact_id); else the one person whose
    email is the login's (the seat's invited email, or the sign-in's own),
    and only when exactly one of the church's people has it. None when
    nobody, or more than one, matches."""
    uid = str(getattr(user, "id", "") or "")
    seats = _need(f"/business_users?business_id=eq.{_q(biz)}&user_id=eq.{_q(uid)}&status=eq.active"
                  "&select=contact_id,invited_email&limit=1") if uid else []
    seat = seats[0] if seats else {}
    if seat.get("contact_id"):
        return str(seat["contact_id"])
    email = (seat.get("invited_email") or getattr(user, "email", None) or "").strip().lower()
    if not email or "@" not in email:
        return None
    people = [c for c in _need(f"/contacts?business_id=eq.{_q(biz)}&email=ilike.{_q(_escape_ilike(email))}"
                               "&select=id,email&limit=5")
              if (c.get("email") or "").strip().lower() == email]
    return str(people[0]["id"]) if len(people) == 1 else None


def sunday_teams(biz: str) -> List[Dict[str, Any]]:
    """The church's Sunday teams: [{group_id, name, owner}], by name."""
    import sunday_planning as sp
    serve = sp._serve_rows(f"/serve_teams?business_id=eq.{_q(biz)}", "group_id")
    if not serve:
        return []
    owners = {str(s["group_id"]): s["owner"] for s in serve}
    groups = _need(f"/groups?business_id=eq.{_q(biz)}&id=in.({_ids(owners)})&active=eq.true"
                   "&select=id,name&order=name.asc&limit=200")
    return [{"group_id": str(g["id"]), "name": g["name"], "owner": owners[str(g["id"])]} for g in groups]


def _named(teams: List[Dict[str, Any]], words: tuple) -> Optional[Dict[str, Any]]:
    """The first ChurchSavvy-owned team whose name says one of `words`."""
    for t in teams:
        low = str(t.get("name") or "").lower()
        if t.get("owner") == "churchsavvy" and any(w in low for w in words):
            return t
    return None


def worship_team(teams: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return _named(teams, WORSHIP_WORDS)


def production_team(teams: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return _named(teams, PRODUCTION_WORDS)


# ─── who holds what ──────────────────────────────────────────────────


def standing(biz: str, user: Any) -> Dict[str, Any]:
    """One login's Sunday standing at one church, worked out from what the
    church already gave it: {seat, roles, reader, leads, approve, parts,
    duties, contact_id}. A read that fails is a 503, never "no role"."""
    import church_duties
    import worship_team as wt
    uid = str(getattr(user, "id", "") or "")
    try:
        seat = wt.role_of(biz, uid)
    except Exception as e:
        logger.error("[sunday-hub] seat lookup failed for %s/%s: %s", biz, uid, e)
        raise HTTPException(503, "Who does what on Sunday couldn't be read just now. Try again.") from e
    team_parts: Set[str] = set(wt.parts_of(biz, uid))
    duties: FrozenSet[str] = frozenset()
    church = True
    if seat in ("owner", "admin", "manager"):
        st = church_duties.standing(biz, uid)
        duties = frozenset(st.get("duties") or ())
        church = bool(st.get("church", True))
    parts: Set[str] = set(team_parts)
    if seat in ("owner", "admin") or (seat == "manager" and not church):
        parts = set(wt.ROLES)
    elif seat == "manager":
        parts |= wt.duty_parts(duties)

    teams: Optional[List[Dict[str, Any]]] = None
    leads: List[Dict[str, Any]] = []
    cid: Optional[str] = None
    roles: Set[str] = set()
    if seat in ("owner", "admin"):
        roles = set(ROLES)
    else:
        if parts & {"planner", "admin"}:
            roles.add("planner")
        cid = person_of(biz, user)
        if cid:
            import sunday_leading as sl
            led = sl.led_teams(biz, cid)
            if led:
                teams = sunday_teams(biz)
                owner_of = {t["group_id"]: t["owner"] for t in teams}
                leads = [{"group_id": t["group_id"], "name": t["name"], "owner": owner_of.get(t["group_id"], "volunteers")}
                         for t in led]
        if "worship" in parts:
            teams = teams if teams is not None else sunday_teams(biz)
            w = worship_team(teams)
            if w is None:
                roles.add("planner")
            elif not any(t["group_id"] == w["group_id"] for t in leads):
                leads.append(dict(w))
        if leads:
            roles.add("team_leader")
        if parts & {"booth", "media"}:
            roles.add("media_tech")
        if "ministry_ops" in duties:
            roles.add("ministry_ops")
    reader = bool(roles) or bool(duties & SUNDAY_DUTIES) or bool(team_parts)
    return {"seat": seat, "roles": [r for r in ROLES if r in roles], "reader": reader,
            "leads": sorted(leads, key=lambda t: str(t["name"]).lower()), "approve": seat in ("owner", "admin"),
            "parts": parts, "duties": duties, "contact_id": cid}


def require_reader(biz: str, user: Any) -> Optional[Dict[str, Any]]:
    """The read wall: with the hub on for this login, its standing, or 403
    unless it holds a Sunday role, duty or part. With the hub off, None and
    nothing is asked (every route answers as before)."""
    if not open_to(user):
        return None
    st = standing(biz, user)
    if not st["reader"]:
        raise HTTPException(403, WALL)
    return st


def sees_giving(biz: str, user: Any) -> Optional[bool]:
    """Whether this login sees the offering by service: the gate Giving →
    by service keeps (giving_services._gate: finance people behind the
    giving keeper, where giving by service is on). None when it couldn't be
    read just now (shown as not seen)."""
    import giving_services
    try:
        giving_services._gate(biz, user)
        return True
    except HTTPException as e:
        return None if e.status_code >= 500 else False
    except Exception as e:
        logger.warning("[sunday-hub] giving gate unreadable for %s: %s", biz, e)
        return None


# ─── "This Sunday" or "Next service" ─────────────────────────────────


def _chosen_word(biz: str) -> Optional[str]:
    """The church's own choice (worship_settings.service_word), or None.
    Before the migration the column isn't there and the read fails: none."""
    rows = sb_clients.sb_get_as_service(f"/worship_settings?business_id=eq.{_q(biz)}&select=service_word&limit=1")
    word = (rows[0].get("service_word") if rows else None) if isinstance(rows, list) else None
    return word if word in WORDS else None


def worked_out_word(biz: str) -> str:
    """"Sunday" when most of the church's plans (its coming and recent
    services and its templates, never an event date) fall on a Sunday on
    its own clock; else "service". None yet: "Sunday"."""
    import business_marketing
    import serve_dates as sd
    rows = sb_clients.sb_get_as_service(
        f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null{sd.plans_only()}"
        "&starts_at=not.is.null&select=starts_at&order=starts_at.desc&limit=40")
    if not rows:
        return "Sunday"
    church = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=id,settings&limit=1") or [{"id": biz}]
    zone = business_marketing.business_tz(church[0])
    days = []
    for r in rows:
        try:
            days.append(datetime.fromisoformat(str(r["starts_at"]).replace("Z", "+00:00")).astimezone(zone).weekday())
        except (TypeError, ValueError):
            continue
    if not days:
        return "Sunday"
    return "Sunday" if sum(1 for d in days if d == 6) * 2 >= len(days) else "service"


def service_word(biz: str) -> Dict[str, Any]:
    chosen = _chosen_word(biz)
    if chosen:
        return {"service_word": chosen, "service_word_set": True}
    try:
        return {"service_word": worked_out_word(biz), "service_word_set": False}
    except Exception as e:
        logger.warning("[sunday-hub] service word not worked out for %s: %s", biz, e)
        return {"service_word": "Sunday", "service_word_set": False}


# ─── what /worship/status carries ────────────────────────────────────


def status_block(biz: str, user: Any) -> Dict[str, Any]:
    """The `sunday` block of GET /worship/status (the hub on for this login)."""
    st = standing(biz, user)
    giving = st["approve"] or bool(sees_giving(biz, user)) if st["reader"] else False
    return {"roles": st["roles"], "reader": st["reader"], "leads": st["leads"], "approve": st["approve"],
            "giving": bool(giving), **service_word(biz)}


# ─── the church's word ───────────────────────────────────────────────


@router.put("/service-word")
def put_service_word(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Sunday setup: the church says "This Sunday" or "Next service" itself
    (null: work it out again). The setup part (worship_team CAN["setup"])."""
    import worship_team as wt
    from worship_router import _uuid
    if not open_to(user):
        raise HTTPException(404, "Not Found")
    body = body or {}
    biz = _uuid(body.get("business_id"))
    wt.require(biz, user, "setup")
    word = body.get("word")
    if word is not None and word not in WORDS:
        raise HTTPException(400, 'The word is "Sunday" or "service"')
    saved = sb_clients.sb_post_as_service(
        "/worship_settings?on_conflict=business_id",
        {"business_id": biz, "service_word": word, "updated_at": datetime.now(timezone.utc).isoformat()},
        prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list):
        raise HTTPException(503, "That didn't save. Try again.")
    return service_word(biz)
