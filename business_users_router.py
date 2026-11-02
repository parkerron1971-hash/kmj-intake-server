"""
business_users_router.py — Phase E v1.1 — multi-seat team membership
(Practice tier). Mirrors the I.3 PR3 accountant-collaborator pattern:
owner invites by email → token link (best-effort email) → invitee accepts
while signed in. business_users is SEPARATE from business_collaborators
(accountants are a bookkeeping role; team members are operators).

Roles: owner (implicit — the businesses.owner_id), admin, member.
v1 access: active members SEE the business (businesses SELECT RLS) and
admins can update business settings (businesses UPDATE RLS). Role-scoped
write access across every operational table is the held "multi-role
permission system beyond v1" (Category D) — surfaced, not snuck in.

Seat caps (1/3/7 via PLAN_LIMITS.max_seats) are gate-ready: enforced only
when BILLING_ENFORCE=on.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import ledger_unlock
import sb_clients
import billing_limits
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("business_users")

router = APIRouter(prefix="/team", tags=["team"])

from app_base import app_base_url
_APP_BASE = app_base_url()
# Category D multi-role v2: viewer < member < manager < admin < owner.
_ROLES = ("admin", "manager", "member", "viewer")
_ROLE_RANK = {"viewer": 1, "member": 2, "manager": 3, "admin": 4, "owner": 5}


def role_of(biz: str, user_id: str) -> Optional[str]:
    """The caller's role on a business: 'owner', their active business_users
    role, or None. The shared resolution every router can adopt."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1") or []
    if rows and str(rows[0].get("owner_id")) == str(user_id):
        return "owner"
    mem = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{biz}&user_id=eq.{user_id}"
        f"&status=eq.active&select=role&limit=1") or []
    return (mem[0].get("role") if mem else None)


def require_role(biz: str, user_id: str, min_role: str) -> str:
    """403 unless the caller's role rank ≥ min_role. Returns the role."""
    from fastapi import HTTPException as _HTTPException
    r = role_of(biz, user_id)
    if not r or _ROLE_RANK.get(r, 0) < _ROLE_RANK.get(min_role, 99):
        raise _HTTPException(403, f"requires {min_role} access or above")
    return r


def require_business_admin(business_id: str, user: AuthedUser) -> str:
    """The gate the agent runners share: 404 if no such business, 403
    unless the caller is admin or above. Returns the role.

    Lives here because this module already owns role resolution. The
    alternative was these eight lines copied into six agent files, where
    copies drift and one of them quietly keeps letting people in.
    `role_of` ranks the owner above admin, so owners still pass.

    The 404 comes BEFORE the role check on purpose: "no such business"
    is not a permissions answer, and require_role cannot tell them apart.
    """
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    return require_role(business_id, str(user.id), "admin")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Who a login is ───────────────────────────────────────────────────
# The business's settings name its owner (practitioner_name). A seat is
# someone else, but until 2026-10-28 it had no name of its own, so every
# "you" in the app read the owner's: Love City's office logins signed up
# and were greeted as Kevin. A seat's person is the business's record of
# them (contacts), tied at the invite or at accept, or found by the
# invite's email; failing that, the name they gave when they signed up.

def _clean_name(v: Any) -> str:
    return " ".join("".join(ch for ch in w if ch.isprintable()) for w in str(v or "").split())[:80].strip()


def _person_of(contact: Dict[str, Any]) -> Dict[str, Any]:
    name = _clean_name(contact.get("name"))
    return {"name": name or None, "first_name": name.split(" ")[0] if name else None,
            "contact_id": str(contact.get("id"))}


def _contacts_by_email(biz: str, email: Any) -> List[Dict[str, Any]]:
    """The business's people with exactly this email, any case. A family
    often shares one address, so this can be several."""
    email = str(email or "").strip().lower()
    if not email or "@" not in email:
        return []
    pat = email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{quote(str(biz), safe='')}&email=ilike.{quote(pat, safe='')}"
        f"&select=id,name,email&limit=10") or []
    return [r for r in rows if str(r.get("email") or "").strip().lower() == email]


def match_contact(biz: str, email: Any, name: Any = "") -> Optional[Dict[str, Any]]:
    """The one person an email names. With several (a shared family
    address), the one whose first name is `name`'s; else no one, since a
    guess would greet the wrong person."""
    rows = _contacts_by_email(biz, email)
    if len(rows) == 1:
        return rows[0]
    first = _clean_name(name).split(" ")[0].lower()
    hits = [r for r in rows if first and _clean_name(r.get("name")).split(" ")[0].lower() == first]
    return hits[0] if len(hits) == 1 else None


def _contact(biz: str, contact_id: Any) -> Optional[Dict[str, Any]]:
    if not contact_id:
        return None
    rows = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{quote(str(biz), safe='')}&id=eq.{quote(str(contact_id), safe='')}"
        f"&select=id,name,email&limit=1") or []
    return rows[0] if rows else None


def _person_for_seat(biz: str, seat: Dict[str, Any], keep: Optional[str] = None) -> Optional[Dict[str, Any]]:
    c = _contact(biz, seat.get("contact_id"))
    if not c:
        c = match_contact(biz, seat.get("invited_email"), seat.get("name"))
        if c and keep and not seat.get("contact_id"):
            _keep_contact(biz, keep, str(c.get("id")))
    if c:
        return _person_of(c)
    name = _clean_name(seat.get("name"))
    return {"name": name, "first_name": name.split(" ")[0], "contact_id": None} if name else None


def _keep_contact(biz: str, user_id: str, contact_id: str) -> None:
    """An active seat its email matched to one member record keeps that
    record (Love City's office checkup, 2026-11-01: three of five logins
    were tied by email alone, so changing the email on the record would
    have lost the name). Only where nothing is tied yet; a failed write
    costs nothing, and the next read matches again."""
    try:
        sb_clients.sb_patch_as_service(
            f"/business_users?business_id=eq.{quote(str(biz), safe='')}&user_id=eq.{quote(str(user_id), safe='')}"
            f"&status=eq.active&contact_id=is.null", {"contact_id": contact_id})
    except Exception:
        logger.warning("seat person: couldn't keep the matched record for a seat on %s", str(biz)[:8], exc_info=True)


def seat_person(biz: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Who an active seat on a business is: {name, first_name, contact_id},
    or None when nothing names them (and for the owner, whom the business's
    settings name). The app greets with it, and Chief says who it's helping.
    A seat its email matches to one record keeps that record from then on."""
    seat = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{quote(str(biz), safe='')}&user_id=eq.{quote(str(user_id), safe='')}"
        f"&status=eq.active&select=invited_email,contact_id,name&limit=1") or []
    return _person_for_seat(biz, seat[0], keep=str(user_id)) if seat else None


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,subscription_status,"
        f"subscription_plan&limit=1") or []
    if not rows or str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not your business")
    return rows[0]


@router.get("/my-role")
def my_role(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The caller's own standing on a business — drives client-side
    surface shaping (an accountant collaborator gets the books-only
    view; team seats get the full app at their rank). Informational,
    never a security boundary: every router enforces server-side."""
    r = role_of(biz, str(user.id))
    accountant = False
    if not r:
        from business_collaborators_router import is_active_accountant
        accountant = is_active_accountant(biz, str(user.id))
    out: Dict[str, Any] = {"ok": True, "role": r, "accountant": accountant}
    # Who this login is, so the app greets them and not the owner. Absent
    # for the owner (the business's settings name them) and when nothing
    # names this login yet.
    if r and r != "owner":
        me = seat_person(biz, str(user.id))
        if me:
            out["me"] = me
    # A church's office login sees the areas it works in (church_areas,
    # "Who sees what"); null is the whole church. Absent when it doesn't apply.
    if r:
        import church_areas
        view = church_areas.my_areas(biz, str(user.id), r)
        if view is not None:
            out["areas"] = view["areas"]
            out["areas_by"] = view["by"]
            # Their lane's name, for the office's header ("Minnie · Treasurer").
            if r != "owner":
                out["lane"] = _lane_label(biz, str(user.id), r, view["areas"])
    # A church login's duties (church_duties): the jobs it does, so the app
    # shows each button to the login that does the job; every key for the
    # owner and the admins. Absent when they don't apply, and when they
    # couldn't be read: my-role never fails for them.
    if r:
        try:
            import church_duties
            duties = church_duties.duties_of(biz, str(user.id), r)
            if duties is not None:
                out["duties"] = duties
        except Exception as e:  # noqa: BLE001 — my-role runs on every app load
            logger.warning(f"[team] my-role duties not read for {biz}: {e}")
    return out


def _lane_label(biz: str, user_id: str, role: str, areas: Any) -> Optional[str]:
    """The lane a seat was given (stored at the invite or in Logins & areas),
    else the lane its areas are exactly, else None. Only the stored one can
    say Treasurer: an admin's areas are the whole church."""
    import church_areas
    seat = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{quote(str(biz), safe='')}&user_id=eq.{quote(str(user_id), safe='')}"
        f"&status=eq.active&select=lane&limit=1") or []
    key = seat[0].get("lane") if seat else None
    if key not in church_areas.LANES:
        key = church_areas.lane_of(role, areas if isinstance(areas, list) else None)
    return church_areas.LANES[key]["label"] if key in church_areas.LANES else None


class InviteBody(BaseModel):
    email: str
    role: str = "member"
    # A church's office lane (church_areas.LANES): it sets the role and the
    # areas, so the login is set up the moment they accept.
    lane: Optional[str] = None
    # Who they are in the business's records (contacts), when the inviter
    # knows. Without it the invite's email finds them, if it names one.
    contact_id: Optional[str] = None


@router.post("/invite")
async def invite(biz: str, body: InviteBody, request: Request,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    # STEP-UP on the GRANT only. Revoking is the emergency brake and
    # must never have friction in front of it.
    ledger_unlock.require_unlock(request, str(user.id), ledger_unlock.SCOPE_ACCESS)
    inviter_role = require_role(biz, str(user.id), "manager")
    lane = None
    if body.lane:
        import church_areas
        lane = church_areas.lane_for_invite(biz, body.lane)
    role = lane["role"] if lane else body.role
    if role == "admin" and _ROLE_RANK[inviter_role] < _ROLE_RANK["admin"]:
        raise HTTPException(403, "only an admin or the owner can invite admins")
    # comp_tier in the select (flip-test class, 2026-08-22): without it a
    # comped business resolves to NO plan and the seat cap reads 1 —
    # blocking the very accounts comp_tier exists to unblock.
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,subscription_status,"
        f"subscription_plan,comp_tier&limit=1") or []
    biz_row = rows[0] if rows else {}
    if role not in _ROLES:
        raise HTTPException(400, f"role must be one of {_ROLES}")
    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "valid email required")

    # Seat cap (gate-ready; enforced only with BILLING_ENFORCE=on).
    cap = billing_limits.can_add_seat(biz, biz_row)
    if cap["enforce"] and not cap["allowed"]:
        raise HTTPException(402, {
            "error": "seat_cap_reached",
            "message": f"Your plan includes {cap['limit']} seat(s) — this business "
                       f"is using {cap['count']}. Upgrade to add more teammates.",
            **{k: cap[k] for k in ("count", "limit")}})

    existing = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{biz}&invited_email=eq.{email}"
        f"&status=in.(invited,active)&select=id&limit=1") or []
    if existing:
        raise HTTPException(409, "this person is already invited or active")
    person = _contact(biz, body.contact_id) if body.contact_id else match_contact(biz, email)
    if body.contact_id and not person:
        raise HTTPException(404, "that person isn't in this business's records")

    res = sb_clients.sb_post_as_service("/business_users", {
        "business_id": biz, "invited_email": email, "role": role,
        "status": "invited", "invited_by": str(user.id),
        "invited_at": _now_iso(),
        **({"areas": lane["areas"]} if lane and lane["areas"] else {}),
        **({"lane": lane["key"]} if lane else {}),
        **({"contact_id": str(person["id"])} if person else {}),
    })
    row = (res or [None])[0] if isinstance(res, list) else res
    if not row:
        raise HTTPException(500, "invite insert failed")
    # A church's invite opens at its own office door (office_door).
    import office_door
    door = office_door.path_for(biz)
    accept_url = f"{_APP_BASE}{door or '/'}?team_invite={row.get('token')}"

    email_sent = False
    try:
        from email_sender import send_via_resend
        biz_name = biz_row.get("name") or "a business"
        named = _person_of(person) if person else {}
        hello = f"Hi {named['first_name']},\n\n" if named.get("first_name") else ""
        as_what = lane["label"] if lane else "a " + role
        if door:
            # From the church, about its office: no Solutionist sign-up pitch.
            sender = biz_name[:60]
            subject = f"Your {biz_name} office login"
            text = (f"{hello}{biz_name} has set up your office login, in {as_what}.\n\n"
                    f"Open your invitation to make your account (or sign in if you have one):\n{accept_url}\n\n"
                    f"— {biz_name}")
        else:
            sender = "Solutionist System"
            subject = f"{biz_name} invited you to their team"
            text = (f"{hello}You've been invited to join {biz_name} on Solutionist as {as_what}.\n\n"
                    f"Accept your invitation (sign in or create your account first):\n{accept_url}\n\n"
                    f"— The Solutionist System")
        await send_via_resend(
            to_email=email, to_name=named.get("name"),
            from_email="invites@mysolutionist.app", from_name=sender,
            reply_to=None, subject=subject, body=text)
        email_sent = True
    except Exception as e:
        logger.warning(f"[team] invite email not sent: {e}")

    return {"ok": True, "member": row, "email_sent": email_sent,
            "accept_url": accept_url, "seats": cap, "lane": lane["key"] if lane else None}


@router.get("")
def list_team(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_role(biz, str(user.id), "manager")
    rows0 = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,subscription_status,subscription_plan,comp_tier&limit=1") or []
    biz_row = rows0[0] if rows0 else {}
    rows = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{biz}&status=in.(invited,active)"
        f"&order=invited_at.desc&limit=200"
        f"&select=id,invited_email,role,status,invited_at,joined_at,contact_id,name") or []
    for r in rows:
        r["person"] = _person_for_seat(biz, r)
    return {"ok": True, "members": rows,
            "seats": billing_limits.can_add_seat(biz, biz_row)}


@router.get("/validate")
def validate_invite(token: str) -> Dict[str, Any]:
    """Front-door check for an invite link, mirroring
    /access/invites/validate: the auth screen calls this BEFORE a session
    exists, so a brand-new invitee can unlock sign-up (instead of the
    waitlist) and get their email prefilled. No auth on purpose — the
    token is the secret, and the response reveals only what the invite
    email already told its holder, plus who they are to the business (the
    name it knows them by, and their lane), so the page welcomes them as
    themselves. Acceptance still requires a session (POST /team/accept)."""
    tok = (token or "").strip()
    if not tok:
        return {"ok": True, "valid": False}
    rows = sb_clients.sb_get_as_service(
        f"/business_users?token=eq.{quote(tok, safe='')}"
        f"&status=in.(invited,active)"
        f"&select=invited_email,role,status,business_id,areas,contact_id,name,lane&limit=1") or []
    if not rows:
        return {"ok": True, "valid": False}
    inv = rows[0]
    biz = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{inv.get('business_id')}&select=name&limit=1") or []
    person = _person_for_seat(str(inv.get("business_id")), inv) or {}
    import church_areas
    import office_door
    lane = inv.get("lane") if inv.get("lane") in church_areas.LANES else church_areas.lane_of(
        inv.get("role"), inv.get("areas") if isinstance(inv.get("areas"), list) else None)
    church = office_door.church_by_business(inv.get("business_id"))
    return {"ok": True, "valid": True,
            "email": inv.get("invited_email"),
            "role": inv.get("role"),
            "business_name": (biz[0].get("name") if biz else None),
            "name": person.get("name"),
            "first_name": person.get("first_name"),
            "lane": church_areas.LANES[lane]["label"] if lane else None,
            # A church's invite opens at its office door, in its colours,
            # even on a link sent before the door existed.
            "door": office_door.brand(church) if church else None,
            "already_active": inv.get("status") == "active"}


@router.get("/door")
def office_door_look(church: str) -> Dict[str, Any]:
    """A church's office door (office_door): its name, colours and logo, for
    the app's sign-in at /office/<slug>. No auth: it is what the church's
    public site already shows. {ok: false} for anything but a church's live
    site, and the app shows its own sign-in."""
    import office_door
    found = office_door.church_by_slug(church)
    return {"ok": True, "door": office_door.brand(found)} if found else {"ok": False}


class AcceptBody(BaseModel):
    token: str
    # The name they gave when they signed up: what the app calls them when
    # the business has no record of them, and what tells two people apart
    # who share one family email.
    name: Optional[str] = None


@router.post("/accept")
def accept(body: AcceptBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Invitee accepts via the token link (must be signed in)."""
    rows = sb_clients.sb_get_as_service(
        f"/business_users?token=eq.{body.token}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "invitation not found")
    inv = rows[0]
    if inv.get("status") == "revoked":
        raise HTTPException(409, "this invitation was revoked")
    if inv.get("status") == "active":
        return {"ok": True, "already": True, "business_id": inv.get("business_id")}
    sb_clients.sb_patch_as_service(
        f"/business_users?id=eq.{inv['id']}",
        {"status": "active", "user_id": str(user.id), "joined_at": _now_iso()})
    # Then who they are, on its own write: a seat that can't be named still
    # gets in. The invite's email finds their record, else the address they
    # signed up with.
    biz = str(inv.get("business_id"))
    name = _clean_name(body.name)
    tie: Dict[str, Any] = {"name": name} if name else {}
    if not inv.get("contact_id"):
        c = match_contact(biz, inv.get("invited_email"), name) or match_contact(biz, getattr(user, "email", None), name)
        if c:
            tie["contact_id"] = str(c["id"])
    if tie:
        sb_clients.sb_patch_as_service(f"/business_users?id=eq.{inv['id']}", tie)
    return {"ok": True, "business_id": inv.get("business_id"), "role": inv.get("role"),
            "me": _person_for_seat(biz, {**inv, **tie})}


@router.post("/{member_id}/revoke")
def revoke(member_id: str, biz: str,
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    caller = require_role(biz, str(user.id), "manager")
    # A manager can't revoke an admin (rank discipline).
    target = sb_clients.sb_get_as_service(
        f"/business_users?id=eq.{member_id}&business_id=eq.{biz}&select=role&limit=1") or []
    if target and _ROLE_RANK.get(target[0].get("role"), 0) >= _ROLE_RANK.get(caller, 0) \
            and caller != "owner":
        raise HTTPException(403, "you can only remove roles below your own")
    sb_clients.sb_patch_as_service(
        f"/business_users?id=eq.{member_id}&business_id=eq.{biz}",
        {"status": "revoked", "revoked_at": _now_iso()})
    return {"ok": True}
