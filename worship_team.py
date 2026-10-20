# worship_team.py — who does what in a church's ChurchSavvy (design
# canvas TXrKfJhDkPsXfSsQjhdeoq, board 30 "Team and roles"; Kevin
# 2026-10-20: "these are a go").
#
#   GET     /worship/team?business_id=      the team (an admin)
#   POST    /worship/team/invite            invite someone to a part (an admin)
#   PUT     /worship/team/{id}              change their parts (an admin)
#   DELETE  /worship/team/{id}              take them off the team (an admin)
#   GET     /worship/team/invite?t=         what an invite link is for (no sign-in:
#                                           the sign-up screen says whose team it is)
#   POST    /worship/team/accept            join with an invite's link (signed in)
#   GET     /worship/team/mine              the churches I'm on the team of
#
# Each person opens ChurchSavvy to their own part and changes only what it
# allows:
#   planner   plans Sundays, sermon slides, templates; runs the screens
#   worship   songs and the order, keys, stage notes; never the screens
#   booth     runs the screens and fixes a typo live; never the plan
#   admin     everything, the setup and who's on the team
# The owner, an admin or a manager of the church in Solutionist is an
# admin here without being invited.
#
# A volunteer is NOT a Solutionist seat. A seat (business_users) is read
# access to the whole business through the database's own rules
# (is_business_member): its people, its giving, its books. A booth
# volunteer must never get that, so the team lives in its own table, which
# only this server reads, and opens only the worship routes, each through
# roles_of / require below.
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import billing_context
import sb_clients
from app_base import app_base_url
from auth_supabase import AuthedUser, require_user
from business_users_router import role_of

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])

STAFF_ROLES = ("owner", "admin", "manager")
ROLES = ("planner", "worship", "booth", "admin")
ROLE_LABEL = {"planner": "Planner", "worship": "Worship leader", "booth": "Booth", "admin": "Admin"}
# What each part may change. Reading is open to every part.
CAN: Dict[str, Set[str]] = {
    "plan": {"admin", "planner", "worship"},
    "songs": {"admin", "planner", "worship"},
    "media": {"admin", "planner", "worship"},
    "fix": {"admin", "planner", "worship", "booth"},
    "run": {"admin", "planner", "booth"},
    "setup": {"admin"},
}
REFUSED = {
    "plan": "Your part on the team doesn't change the plan. A planner or the worship leader does.",
    "songs": "Your part on the team doesn't change the song library.",
    "media": "Your part on the team doesn't change the library.",
    "fix": "Your part on the team doesn't change the words.",
    "run": "Your part on the team doesn't run the screens. The booth does.",
    "setup": "Only an admin changes the setup.",
}
MAX_TEAM = 60
INVITE_DAYS = 30
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
_FIELDS = "id,name,email,roles,status,token,user_id,invited_at,joined_at"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _uuid(value: Any, what: str = "business") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} id isn't valid")


def _gate(user: AuthedUser) -> None:
    from worship_router import open_to
    if not open_to(user):
        raise HTTPException(404, "Not Found")


def _switch_off() -> bool:
    from worship_router import mode
    return mode() == "off"


# ─── who may do what ─────────────────────────────────────────────────


def _seat(biz: str, user: AuthedUser) -> Optional[str]:
    try:
        return role_of(biz, str(user.id))
    except Exception as e:
        logger.error("[worship-team] seat lookup failed for %s/%s: %s", biz, user.id, e)
        raise HTTPException(503, "access check unavailable") from e


def _team_roles(biz: str, user: AuthedUser) -> Set[str]:
    rows = sb_clients.sb_get_as_service(
        f"/worship_team?business_id=eq.{_q(biz)}&user_id=eq.{_q(user.id)}&status=eq.active&select=roles&limit=1")
    if rows is None:
        raise HTTPException(503, "access check unavailable")
    return {r for r in (rows[0].get("roles") or []) if r in ROLES} if rows else set()


def roles_of(biz: str, user: AuthedUser) -> Set[str]:
    """This person's parts in a church's ChurchSavvy: every part for the
    owner, an admin or a manager; their team parts for anyone else (none
    for a viewer or member seat, who reads only). A stranger gets the same
    404 as a church that isn't there."""
    seat = _seat(biz, user)
    if seat in STAFF_ROLES:
        billing_context.set_current(biz)
        return set(ROLES)
    team = _team_roles(biz, user)
    if not seat and not team:
        raise HTTPException(404, "business not found")
    billing_context.set_current(biz)
    return set(team)


def can(roles: Set[str], what: str) -> bool:
    return bool(roles & CAN[what])


def can_all(roles: Set[str]) -> Dict[str, bool]:
    return {k: can(roles, k) for k in CAN}


def require(biz: str, user: AuthedUser, what: str) -> Set[str]:
    roles = roles_of(biz, user)
    if not can(roles, what):
        raise HTTPException(403, REFUSED[what])
    return roles


# ─── the team ────────────────────────────────────────────────────────


def _clean_roles(raw: Any) -> List[str]:
    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, "Pick at least one part: planner, worship leader, booth or admin")
    if any(not isinstance(r, str) or r not in ROLES for r in raw):
        raise HTTPException(400, "A part is planner, worship leader, booth or admin")
    return [r for r in ROLES if r in raw]


def _link(token: str) -> str:
    return f"{app_base_url()}/churchsavvy/join?t={token}"


def _out(row: Dict[str, Any], me: str) -> Dict[str, Any]:
    out = {k: row.get(k) for k in ("id", "name", "email", "roles", "status", "invited_at", "joined_at")}
    out["you"] = bool(row.get("user_id")) and str(row.get("user_id")) == me
    # An invite not yet taken keeps its link, so it can be sent again (by text, say).
    if row.get("status") == "invited":
        out["link"] = _link(row.get("token"))
    return out


def _church(biz: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=id,name,owner_id,settings&limit=1") or []
    return rows[0] if rows else {}


def _row(biz: str, member_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/worship_team?id=eq.{_q(member_id)}&business_id=eq.{_q(biz)}&status=in.(invited,active)&select={_FIELDS}&limit=1")
    if rows is None:
        raise HTTPException(503, "The team couldn't be read. Try again.")
    if not rows:
        raise HTTPException(404, "They aren't on the team")
    return rows[0]


@router.get("/team")
def list_team(business_id: str, user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid(business_id)
    require(biz, user, "setup")
    rows = sb_clients.sb_get_as_service(
        f"/worship_team?business_id=eq.{_q(biz)}&status=in.(invited,active)&select={_FIELDS}&order=invited_at.asc")
    if rows is None:
        raise HTTPException(503, "The team couldn't be read. Try again.")
    # The church's own admins in Solutionist: admins here without an invite.
    church = _church(biz)
    settings = church.get("settings") if isinstance(church.get("settings"), dict) else {}
    staff: List[Dict[str, Any]] = [{"name": (settings.get("practitioner_name") or "").strip() or "The owner",
                                    "kind": "owner", "you": str(church.get("owner_id")) == str(user.id)}]
    seats = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{_q(biz)}&status=eq.active&role=in.(admin,manager)&select=invited_email,user_id") or []
    staff += [{"name": s.get("invited_email") or "", "kind": "seat", "you": str(s.get("user_id")) == str(user.id)} for s in seats]
    return {"team": [_out(r, str(user.id)) for r in rows], "staff": staff, "roles": list(ROLES)}


@router.post("/team/invite")
async def invite(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    require(biz, user, "setup")
    name = body.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise HTTPException(400, "Their name, so the team list makes sense (at most 80 characters)")
    email = body.get("email") or ""
    if not isinstance(email, str) or (email.strip() and not _EMAIL.match(email.strip())):
        raise HTTPException(400, "That email doesn't look right")
    email = email.strip().lower() or None
    roles = _clean_roles(body.get("roles"))
    rows = sb_clients.sb_get_as_service(
        f"/worship_team?business_id=eq.{_q(biz)}&status=in.(invited,active)&select=id,email")
    if rows is None:
        raise HTTPException(503, "The team couldn't be read. Try again.")
    if len(rows) >= MAX_TEAM:
        raise HTTPException(400, f"A team is at most {MAX_TEAM} people")
    if email and any((r.get("email") or "") == email for r in rows):
        raise HTTPException(409, "They're already invited. Their link is in the team list.")
    saved = sb_clients.sb_post_as_service("/worship_team?select=" + _FIELDS, {
        "business_id": biz, "name": name.strip(), "email": email, "roles": roles,
        "status": "invited", "invited_by": str(user.id), "invited_at": _now().isoformat(),
    }, prefer="return=representation")
    row = saved[0] if isinstance(saved, list) and saved else None
    if not row:
        raise HTTPException(503, "The invite didn't save. Try again.")
    emailed = False
    if email:
        church = _church(biz).get("name") or "Your church"
        parts = " and ".join(ROLE_LABEL[r].lower() for r in roles)
        try:
            from email_sender import send_via_resend
            await send_via_resend(
                to_email=email, to_name=name.strip(),
                from_email="invites@mysolutionist.app", from_name="ChurchSavvy", reply_to=None,
                subject=f"{church} invited you to their Sunday team",
                body=(f"Hi {name.strip()},\n\n{church} invited you to their Sunday team on ChurchSavvy, "
                      f"as {parts}.\n\nJoin here (sign in, or make your account, with this email):\n"
                      f"{_link(row['token'])}\n\n— ChurchSavvy"),
                business_id=biz)
            emailed = True
        except Exception as e:
            logger.warning("[worship-team] invite email not sent: %s", e)
    return {"member": _out(row, str(user.id)), "link": _link(row["token"]), "emailed": emailed}


@router.put("/team/{member_id}")
def change_roles(member_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    require(biz, user, "setup")
    row = _row(biz, _uuid(member_id, "team member"))
    roles = _clean_roles(body.get("roles"))
    saved = sb_clients.sb_patch_as_service(f"/worship_team?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}",
                                           {"roles": roles})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "That didn't save. Try again.")
    return {"member": _out({**row, "roles": roles}, str(user.id))}


@router.delete("/team/{member_id}")
def remove(member_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid(business_id)
    require(biz, user, "setup")
    row = _row(biz, _uuid(member_id, "team member"))
    saved = sb_clients.sb_patch_as_service(f"/worship_team?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz)}",
                                           {"status": "removed", "removed_at": _now().isoformat()})
    if not isinstance(saved, list) or not saved:
        raise HTTPException(503, "They're still on the team. Try again.")
    return {"ok": True}


def invite_from_token(token: Any, user: Optional[AuthedUser]) -> Dict[str, Any]:
    """The invite an invite link names, for the signed-in person taking it
    (or, with no one signed in yet, for the sign-up screen). The token names
    exactly one invite and the church comes from that row: the caller never
    names a church. Refuses a link that was taken back, one someone else
    already took, and one a month old."""
    token = _uuid(token, "invite")
    rows = sb_clients.sb_get_as_service(
        f"/worship_team?token=eq.{_q(token)}&select=business_id,{_FIELDS}&limit=1", redact=True)
    if rows is None:
        raise HTTPException(503, "The invite couldn't be read. Try again.")
    if not rows or rows[0].get("status") == "removed":
        raise HTTPException(410, "This invite was taken back. Ask for a new one.")
    inv = rows[0]
    if inv.get("status") == "active":
        if user is None or str(inv.get("user_id")) != str(user.id):
            raise HTTPException(409, "Someone already joined with this invite. Ask for a new one.")
        return inv
    invited = datetime.fromisoformat(str(inv.get("invited_at")).replace("Z", "+00:00"))
    if _now() - invited > timedelta(days=INVITE_DAYS):
        raise HTTPException(410, "This invite is too old. Ask for a new one.")
    return inv


@router.get("/team/invite")
def invite_info(t: str):
    """Whose team an invite link joins, before anyone signs in: the church,
    the invitee's name and email (to fill in the form) and their parts."""
    if _switch_off():
        raise HTTPException(404, "Not Found")
    inv = invite_from_token(t, None)
    church = _church(str(inv.get("business_id"))).get("name") or ""
    return {"church": church, "name": inv.get("name") or "", "email": inv.get("email") or "",
            "roles": inv.get("roles") or []}


@router.post("/team/accept")
def accept(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """Join a church's team with an invite's link. Taking the same link twice
    is fine; someone else's taken link isn't. Joining a church you're
    already on adds the new parts to the ones you have."""
    if _switch_off():
        raise HTTPException(404, "Not Found")
    inv = invite_from_token((body or {}).get("token"), user)
    biz = str(inv["business_id"])
    church = _church(biz).get("name") or ""
    if inv.get("status") == "active":
        return {"business_id": biz, "church": church, "roles": inv.get("roles") or []}
    mine = sb_clients.sb_get_as_service(
        f"/worship_team?business_id=eq.{_q(biz)}&user_id=eq.{_q(user.id)}&status=eq.active&select=id,roles&limit=1")
    if mine is None:
        raise HTTPException(503, "The invite couldn't be read. Try again.")
    if mine:
        roles = [r for r in ROLES if r in set(mine[0].get("roles") or []) | set(inv.get("roles") or [])]
        joined = sb_clients.sb_patch_as_service(f"/worship_team?id=eq.{_q(mine[0]['id'])}", {"roles": roles})
        done = sb_clients.sb_patch_as_service(f"/worship_team?id=eq.{_q(inv['id'])}&status=eq.invited",
                                              {"status": "removed", "removed_at": _now().isoformat()})
    else:
        roles = inv.get("roles") or []
        joined = done = sb_clients.sb_patch_as_service(
            f"/worship_team?id=eq.{_q(inv['id'])}&status=eq.invited",
            {"status": "active", "user_id": str(user.id), "joined_at": _now().isoformat()})
    if not isinstance(joined, list) or not joined or not isinstance(done, list) or not done:
        raise HTTPException(503, "You didn't join yet. Try the link again.")
    return {"business_id": biz, "church": church, "roles": roles}


@router.get("/team/mine")
def mine(user: AuthedUser = Depends(require_user)):
    """The churches this person is on the team of (not their own Solutionist
    businesses, which the app already has), so ChurchSavvy can open one.
    Takes no church from the caller: only their own rows, by their sign-in."""
    if _switch_off():
        return {"churches": []}
    return {"churches": _my_churches(user)}


def _my_churches(user: AuthedUser) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/worship_team?user_id=eq.{_q(user.id)}&status=eq.active&select=business_id,roles")
    if rows is None:
        raise HTTPException(503, "Your churches couldn't be read. Try again.")
    if not rows:
        return []
    ids = ",".join(_q(r["business_id"]) for r in rows)
    names = {str(b["id"]): b.get("name") or "" for b in
             (sb_clients.sb_get_as_service(f"/businesses?id=in.({ids})&is_active=eq.true&select=id,name") or [])}
    return [{"business_id": str(r["business_id"]), "name": names[str(r["business_id"])],
             "roles": [x for x in ROLES if x in (r.get("roles") or [])]}
            for r in rows if str(r["business_id"]) in names]
