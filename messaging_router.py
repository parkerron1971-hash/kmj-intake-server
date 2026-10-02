"""
messaging_router.py — the church team's side of member messaging.

Kevin's rules (2026-09-29 / 10-02): staff do NOT read members' chats. Only
the church's named SAFETY OFFICERS — at least two before messaging can be
turned on — see what was held by the check or reported by a member, in
the Safety room. Opening a chat there needs a reason, is logged, and the
people in that chat are told (member_portal_messaging shows the notice).

  GET   /messaging/settings?business_id=        on/off, keep-for days, officers (any team member;
                                                the owner also gets the team to choose from)
  PATCH /messaging/settings                     {business_id, enabled?, retention_days?} — the owner
  POST  /messaging/officers                     {business_id, user_id, officer} — the owner
  GET   /messaging/safety?business_id=          held messages + open reports — officers only
  POST  /messaging/safety/open                  {business_id, thread_id, reason} — logged
  POST  /messaging/safety/message               {business_id, message_id, action: release|remove}
  POST  /messaging/safety/report                {business_id, report_id, outcome}
  POST  /messaging/safety/pause                 {business_id, contact_id} — turn their messaging off

Who can message (birthdates, the per-person switch, parent links) is set
on the Messaging page through RLS; the database lets only a manager turn
those ON (APPLY-2026-10-02-messaging.sql).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user
from kids_router import _uuid, require

router = APIRouter(tags=["messaging"])

MIN_OFFICERS = 2


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unavailable() -> HTTPException:
    return HTTPException(503, "Messaging couldn't load just now. Please try again.")


def officers(business_id: str) -> List[str]:
    rows = sb_clients.sb_get_as_service(
        f"/msg_safety_officers?business_id=eq.{_q(business_id)}&select=user_id&limit=50")
    if not isinstance(rows, list):
        raise _unavailable()
    return [str(r["user_id"]) for r in rows]


def require_officer(business_id: str, user: AuthedUser) -> None:
    """A safety officer of this church, with a live seat. Refuses (403)."""
    if str(user.id) not in officers(business_id):
        raise HTTPException(403, "Only the church's safety officers can open the Safety room.")


def team(business_id: str, owner_id: str, viewer: AuthedUser) -> List[Dict[str, Any]]:
    """The people who can be officers: the owner and active seats."""
    rows = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{_q(business_id)}&status=eq.active"
        f"&select=user_id,invited_email,role&limit=200")
    if not isinstance(rows, list):
        raise _unavailable()
    out = [{"user_id": str(owner_id), "role": "owner",
            "label": "You" if str(viewer.id) == str(owner_id) else "The owner"}]
    out += [{"user_id": str(r["user_id"]), "role": r.get("role") or "member",
             "label": r.get("invited_email") or "Teammate"}
            for r in rows if r.get("user_id") and str(r["user_id"]) != str(owner_id)]
    return out


def _biz_settings(business_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(business_id)}&select=id,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise _unavailable()
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _names(business_id: str, ids) -> Dict[str, str]:
    want = sorted({str(i) for i in ids if i})
    out: Dict[str, str] = {}
    for i in range(0, len(want), 150):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({','.join(want[i:i + 150])})&select=id,name")
        if not isinstance(rows, list):
            raise _unavailable()
        out.update({str(r["id"]): r.get("name") or "Someone" for r in rows})
    return out


# ─── settings ────────────────────────────────────────────────────────


class SettingsIn(BaseModel):
    business_id: str
    enabled: Optional[bool] = None
    retention_days: Optional[int] = Field(default=None, ge=30, le=3650)


@router.get("/messaging/settings")
def get_settings(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business_id")
    require(biz, user, "viewer")
    row = _biz_settings(biz)
    s = ((row.get("settings") or {}).get("messaging") or {})
    offs = officers(biz)
    out = {"enabled": bool(s.get("enabled")), "retention_days": int(s.get("retention_days") or 365),
           "officers": offs, "min_officers": MIN_OFFICERS, "you_are_officer": str(user.id) in offs,
           "you_are_owner": str(row.get("owner_id")) == str(user.id)}
    if out["you_are_owner"]:
        out["team"] = [{**p, "officer": p["user_id"] in offs} for p in team(biz, row.get("owner_id"), user)]
    return out


@router.patch("/messaging/settings")
def patch_settings(body: SettingsIn, user: AuthedUser = Depends(require_user)):
    biz_id = _uuid(body.business_id, "business_id")
    require(biz_id, user, "owner")
    biz = _biz_settings(biz_id)
    settings = dict(biz.get("settings") or {})
    cfg = dict(settings.get("messaging") or {})
    if body.enabled is True and len(officers(biz_id)) < MIN_OFFICERS:
        raise HTTPException(409, f"Name at least {MIN_OFFICERS} safety officers before turning messaging on.")
    if body.enabled is not None:
        cfg["enabled"] = body.enabled
    if body.retention_days is not None:
        cfg["retention_days"] = body.retention_days
    settings["messaging"] = cfg
    saved = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(biz_id)}", {"settings": settings})
    if not saved:
        raise HTTPException(503, "That change didn't save. Please try again.")
    return {"enabled": bool(cfg.get("enabled")), "retention_days": int(cfg.get("retention_days") or 365)}


class OfficerIn(BaseModel):
    business_id: str
    user_id: str
    officer: bool


@router.post("/messaging/officers")
def set_officer(body: OfficerIn, user: AuthedUser = Depends(require_user)):
    """The owner names (or stands down) a safety officer. While messaging
    is on there are never fewer than two."""
    biz_id = _uuid(body.business_id, "business_id")
    require(biz_id, user, "owner")
    who = _uuid(body.user_id, "user_id")
    biz = _biz_settings(biz_id)
    if who not in {p["user_id"] for p in team(biz_id, biz.get("owner_id"), user)}:
        raise HTTPException(404, "That person isn't on your team.")
    offs = officers(biz_id)
    if body.officer:
        if who not in offs:
            saved = sb_clients.sb_post_as_service(
                "/msg_safety_officers", {"business_id": biz_id, "user_id": who, "added_by": str(user.id)})
            if not isinstance(saved, list) or not saved:
                raise HTTPException(503, "That didn't save. Please try again.")
    elif who in offs:
        on = bool(((biz.get("settings") or {}).get("messaging") or {}).get("enabled"))
        if on and len(offs) <= MIN_OFFICERS:
            raise HTTPException(409, f"Messaging is on, so it needs {MIN_OFFICERS} safety officers. "
                                     "Name another officer first, or turn messaging off.")
        if not sb_clients.sb_delete_as_service(
                f"/msg_safety_officers?business_id=eq.{_q(biz_id)}&user_id=eq.{_q(who)}"):
            raise HTTPException(503, "That didn't save. Please try again.")
    return {"officers": officers(biz_id)}


# ─── the Safety room ─────────────────────────────────────────────────


class OpenIn(BaseModel):
    business_id: str
    thread_id: str
    reason: str = Field(min_length=3, max_length=300)


class MessageIn(BaseModel):
    business_id: str
    message_id: str
    action: str


class ReportIn(BaseModel):
    business_id: str
    report_id: str
    outcome: str = Field(default="", max_length=500)


class PauseIn(BaseModel):
    business_id: str
    contact_id: str


@router.get("/messaging/safety")
def safety_queue(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business_id")
    require(biz, user, "viewer")
    require_officer(biz, user)
    held = sb_clients.sb_get_as_service(
        f"/msg_messages?business_id=eq.{_q(biz)}&status=eq.held"
        f"&select=id,thread_id,sender_contact_id,body,flag,created_at&order=created_at.desc&limit=200")
    reports = sb_clients.sb_get_as_service(
        f"/msg_reports?business_id=eq.{_q(biz)}&status=eq.open"
        f"&select=id,message_id,reporter_contact_id,reason,created_at&order=created_at.desc&limit=200")
    if not isinstance(held, list) or not isinstance(reports, list):
        raise _unavailable()
    reported_ids = sorted({str(r["message_id"]) for r in reports})
    reported: List[Dict[str, Any]] = []
    if reported_ids:
        reported = sb_clients.sb_get_as_service(
            f"/msg_messages?business_id=eq.{_q(biz)}&id=in.({','.join(reported_ids)})"
            f"&select=id,thread_id,sender_contact_id,body,status,created_at")
        if not isinstance(reported, list):
            raise _unavailable()
    by_id = {str(m["id"]): m for m in reported}
    names = _names(biz, [m.get("sender_contact_id") for m in held + reported]
                   + [r.get("reporter_contact_id") for r in reports])
    return {
        "held": [{**m, "sender": names.get(str(m.get("sender_contact_id")), "Someone")} for m in held],
        "reports": [{**r, "reporter": names.get(str(r.get("reporter_contact_id")), "Someone"),
                     "message": {**by_id.get(str(r["message_id"]), {}),
                                 "sender": names.get(str(by_id.get(str(r["message_id"]), {}).get("sender_contact_id")), "Someone")}}
                    for r in reports],
    }


@router.post("/messaging/safety/open")
def open_thread(body: OpenIn, user: AuthedUser = Depends(require_user)):
    """Open a whole chat. Logged with the reason; its people are told."""
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "viewer")
    require_officer(biz, user)
    tid = _uuid(body.thread_id, "thread_id")
    t = sb_clients.sb_get_as_service(f"/msg_threads?id=eq.{_q(tid)}&business_id=eq.{_q(biz)}&select=id,kind,group_id&limit=1")
    if not isinstance(t, list):
        raise _unavailable()
    if not t:
        raise HTTPException(404, "That chat isn't here.")
    logged = sb_clients.sb_post_as_service("/msg_staff_views", {
        "business_id": biz, "thread_id": tid, "user_id": str(user.id), "reason": " ".join(body.reason.split())[:300]})
    if not isinstance(logged, list) or not logged:
        raise HTTPException(503, "The review couldn't be logged, so the chat wasn't opened. Please try again.")
    msgs = sb_clients.sb_get_as_service(
        f"/msg_messages?thread_id=eq.{_q(tid)}&business_id=eq.{_q(biz)}"
        f"&select=id,sender_contact_id,body,status,flag,created_at&order=created_at.asc&limit=500")
    if not isinstance(msgs, list):
        raise _unavailable()
    names = _names(biz, [m.get("sender_contact_id") for m in msgs])
    return {"thread": t[0], "messages": [{**m, "sender": names.get(str(m.get("sender_contact_id")), "Someone")} for m in msgs]}


@router.post("/messaging/safety/message")
def act_on_message(body: MessageIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "viewer")
    require_officer(biz, user)
    if body.action not in ("release", "remove"):
        raise HTTPException(400, "Choose release or remove.")
    mid = _uuid(body.message_id, "message_id")
    patch = ({"status": "delivered"} if body.action == "release"
             else {"status": "removed", "removed_by": str(user.id), "removed_at": now_iso()})
    saved = sb_clients.sb_patch_as_service(f"/msg_messages?id=eq.{_q(mid)}&business_id=eq.{_q(biz)}", patch)
    if not isinstance(saved, list):
        raise HTTPException(503, "That didn't save. Please try again.")
    if not saved:
        raise HTTPException(404, "That message isn't here.")
    return {"ok": True, "status": saved[0]["status"]}


@router.post("/messaging/safety/report")
def close_report(body: ReportIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "viewer")
    require_officer(biz, user)
    rid = _uuid(body.report_id, "report_id")
    saved = sb_clients.sb_patch_as_service(
        f"/msg_reports?id=eq.{_q(rid)}&business_id=eq.{_q(biz)}&status=eq.open",
        {"status": "closed", "outcome": body.outcome.strip()[:500], "closed_by": str(user.id), "closed_at": now_iso()})
    if not isinstance(saved, list):
        raise HTTPException(503, "That didn't save. Please try again.")
    return {"ok": True}


@router.post("/messaging/safety/pause")
def pause_member(body: PauseIn, user: AuthedUser = Depends(require_user)):
    """Turn someone's messaging off (a manager can turn it back on)."""
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "viewer")
    require_officer(biz, user)
    cid = _uuid(body.contact_id, "contact_id")
    saved = sb_clients.sb_patch_as_service(
        f"/msg_members?contact_id=eq.{_q(cid)}&business_id=eq.{_q(biz)}",
        {"enabled": False, "updated_at": now_iso()})
    if not isinstance(saved, list):
        raise HTTPException(503, "That didn't save. Please try again.")
    return {"ok": True}
