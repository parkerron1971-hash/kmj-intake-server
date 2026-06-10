"""
business_collaborators_router.py — Phase I.3 PR3 — accountant collaborators.

Owner invites an accountant by email → token link (+ best-effort email) →
invitee accepts. The owner-facing management ships here; the full
accountant-operates-the-business experience is the v2 accountant arc.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("business_collaborators_router")

router = APIRouter(prefix="/collaborators", tags=["collaborators"])

_APP_BASE = "https://app.solutionist.studio"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def is_active_accountant(business_id: str, user_id: str) -> bool:
    """Reusable check for future cross-router grants (accountant can read
    reports / propose closes / run reconciliation)."""
    rows = sb_clients.sb_get_as_service(
        f"/business_collaborators?business_id=eq.{business_id}&user_id=eq.{user_id}"
        f"&status=eq.active&role=eq.accountant&select=id&limit=1") or []
    return bool(rows)


class InviteBody(BaseModel):
    email: str
    role: str = "accountant"


@router.post("/invite")
async def invite(biz: str, body: InviteBody,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner(biz, user)
    if body.role not in ("accountant", "viewer", "editor"):
        raise HTTPException(400, "invalid role")
    email = (body.email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(400, "a valid email is required")

    res = sb_clients.sb_post_as_service("/business_collaborators", {
        "business_id": biz, "invited_email": email, "role": body.role,
        "status": "pending", "invited_by": str(user.id),
    })
    row = (res or [None])[0] if isinstance(res, list) else res
    if not row:
        raise HTTPException(500, "failed to create invitation")
    accept_url = f"{_APP_BASE}/accept-invite?token={row.get('token')}"

    email_sent = False
    try:
        from email_sender import send_via_resend
        await send_via_resend(
            to_email=email, to_name=None,
            from_email="invites@solutionist.studio", from_name="Solutionist System",
            reply_to=None,
            subject=f"{biz_row.get('name')} invited you to collaborate on their books",
            body=(f"You've been invited to collaborate as a {body.role} on "
                  f"{biz_row.get('name')}'s bookkeeping in Solutionist System.\n\n"
                  f"Accept your invitation: {accept_url}\n\n"
                  f"This link expires in 7 days. If you don't have an account yet, "
                  f"you'll be able to create one."))
        email_sent = True
    except Exception as e:
        # Per the I.3 stop condition: if email can't send, return the link so
        # the owner can share it manually. Don't fail the invite.
        logger.warning(f"[collaborators] invite email not sent: {e}")

    return {"ok": True, "collaborator": row, "email_sent": email_sent, "accept_url": accept_url}


@router.get("")
def list_collaborators(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/business_collaborators?business_id=eq.{biz}"
        f"&order=invited_at.desc&limit=200"
        f"&select=id,invited_email,role,status,invited_at,accepted_at,expiration_at") or []
    # Mark expired pendings (display-only; status flips lazily here).
    now = _now_iso()
    for r in rows:
        if r.get("status") == "pending" and (r.get("expiration_at") or "") < now:
            r["status"] = "expired"
    return {"ok": True, "collaborators": rows}


class AcceptBody(BaseModel):
    token: str


@router.post("/accept")
def accept(body: AcceptBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Invitee accepts via the token link (must be signed in)."""
    rows = sb_clients.sb_get_as_service(
        f"/business_collaborators?token=eq.{body.token}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "invitation not found")
    inv = rows[0]
    if inv.get("status") == "revoked":
        raise HTTPException(409, "this invitation was revoked")
    if (inv.get("expiration_at") or "") < _now_iso():
        sb_clients.sb_patch_as_service(
            f"/business_collaborators?id=eq.{inv['id']}", {"status": "expired"})
        raise HTTPException(409, "this invitation has expired")
    sb_clients.sb_patch_as_service(
        f"/business_collaborators?id=eq.{inv['id']}",
        {"status": "active", "user_id": str(user.id), "accepted_at": _now_iso()})
    return {"ok": True, "business_id": inv.get("business_id"), "role": inv.get("role")}


@router.post("/{collaborator_id}/revoke")
def revoke(collaborator_id: str, biz: str,
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    sb_clients.sb_patch_as_service(
        f"/business_collaborators?id=eq.{collaborator_id}&business_id=eq.{biz}",
        {"status": "revoked", "revoked_at": _now_iso()})
    return {"ok": True}
