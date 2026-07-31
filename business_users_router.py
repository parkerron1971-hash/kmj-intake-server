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

Seat caps (1/1/5 via PLAN_LIMITS.max_seats) are gate-ready: enforced only
when BILLING_ENFORCE=on.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    return {"ok": True, "role": r, "accountant": accountant}


class InviteBody(BaseModel):
    email: str
    role: str = "member"


@router.post("/invite")
async def invite(biz: str, body: InviteBody,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    inviter_role = require_role(biz, str(user.id), "manager")
    if body.role == "admin" and _ROLE_RANK[inviter_role] < _ROLE_RANK["admin"]:
        raise HTTPException(403, "only an admin or the owner can invite admins")
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,subscription_status,"
        f"subscription_plan&limit=1") or []
    biz_row = rows[0] if rows else {}
    if body.role not in _ROLES:
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

    res = sb_clients.sb_post_as_service("/business_users", {
        "business_id": biz, "invited_email": email, "role": body.role,
        "status": "invited", "invited_by": str(user.id),
        "invited_at": _now_iso(),
    })
    row = (res or [None])[0] if isinstance(res, list) else res
    if not row:
        raise HTTPException(500, "invite insert failed")
    accept_url = f"{_APP_BASE}/?team_invite={row.get('token')}"

    email_sent = False
    try:
        from email_sender import send_via_resend
        biz_name = biz_row.get("name") or "a business"
        await send_via_resend(
            to_email=email, to_name=None,
            from_email="invites@solutionist.studio", from_name="Solutionist System",
            reply_to=None,
            subject=f"{biz_name} invited you to their team",
            body=(f"You've been invited to join {biz_name} on Solutionist as a "
                  f"{body.role}.\n\nAccept your invitation (sign in or create your "
                  f"account first):\n{accept_url}\n\n— The Solutionist System"))
        email_sent = True
    except Exception as e:
        logger.warning(f"[team] invite email not sent: {e}")

    return {"ok": True, "member": row, "email_sent": email_sent,
            "accept_url": accept_url, "seats": cap}


@router.get("")
def list_team(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    require_role(biz, str(user.id), "manager")
    rows0 = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,subscription_status,subscription_plan&limit=1") or []
    biz_row = rows0[0] if rows0 else {}
    rows = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{biz}&status=in.(invited,active)"
        f"&order=invited_at.desc&limit=200"
        f"&select=id,invited_email,role,status,invited_at,joined_at") or []
    return {"ok": True, "members": rows,
            "seats": billing_limits.can_add_seat(biz, biz_row)}


class AcceptBody(BaseModel):
    token: str


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
    return {"ok": True, "business_id": inv.get("business_id"), "role": inv.get("role")}


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
