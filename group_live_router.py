"""
group_live_router.py — the team's side of live group meetings.

Kevin's decisions (2026-09-29) included "staff can drop in": a manager
(or admin, or the owner) can see which groups are meeting live right now,
join any of them from the app, and end one for everyone when they must
(a safety lever). Members host and join from the member app
(member_portal_group_live.py); this is only the team's door.

  GET  /group-live?business_id=        open meetings: group, mode, status, since
  POST /group-live/{sid}/drop-in       {business_id} — a 60-second join token
  POST /group-live/{sid}/end           {business_id} — end it for everyone

Staff show in the meeting as "Church staff" (never their email), start
with camera and microphone off, don't count as group attendance, and
don't open a youth meeting that is waiting for its second approved adult
leader — only the group's own approved leaders do that.
"""
from __future__ import annotations

from typing import Any, Dict
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user
from kids_router import _uuid, require

router = APIRouter(tags=["group-live"])


def _q(v: Any) -> str:
    return quote(str(v), safe="")


class BizIn(BaseModel):
    business_id: str


def _session(business_id: str, sid: str) -> Dict[str, Any]:
    import member_portal_group_live as mgl
    s = mgl.session(business_id, sid)
    if s is None:
        raise HTTPException(503, "Group meetings couldn't load just now. Please try again.")
    if not s:
        raise HTTPException(404, "That meeting isn't here.")
    return s


@router.get("/group-live")
def open_meetings(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business_id")
    require(biz, user, "member")
    rows = sb_clients.sb_get_as_service(
        f"/group_live_sessions?business_id=eq.{_q(biz)}&status=in.(waiting,live)"
        f"&select=id,group_id,mode,status,started_at&order=started_at.desc&limit=200")
    if not isinstance(rows, list):
        raise HTTPException(503, "Group meetings couldn't load just now. Please try again.")
    return {"meetings": rows}


@router.post("/group-live/{sid}/drop-in")
async def drop_in(sid: str, body: BizIn, user: AuthedUser = Depends(require_user)):
    import asyncio
    import member_portal_group_live as mgl
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    s = await asyncio.to_thread(_session, biz, _uuid(sid, "session"))
    if s["status"] == "ended":
        raise HTTPException(410, "This meeting has ended.")
    if not mgl.video_ready():
        raise HTTPException(503, "Live meetings aren't available right now.")
    try:
        alive = await mgl.room_open(s["room_name"])
    except Exception:
        raise HTTPException(503, "Video isn't reachable just now. Please try again in a moment.")
    if not alive:
        await asyncio.to_thread(
            sb_clients.sb_patch_as_service,
            f"/group_live_sessions?id=eq.{_q(s['id'])}&business_id=eq.{_q(biz)}&status=in.(waiting,live)",
            {"status": "ended", "ended_at": mgl.now_iso(), "updated_at": mgl.now_iso()})
        raise HTTPException(410, "This meeting has ended.")
    tok = mgl.mint(s["room_name"], f"staff_{user.id}", "Church staff", True, False)
    return {"ok": True, "server_url": tok["server_url"], "token": tok["token"], "mode": s["mode"],
            "status": s["status"], "session_id": s["id"]}


@router.post("/group-live/{sid}/end")
async def end_for_everyone(sid: str, body: BizIn, user: AuthedUser = Depends(require_user)):
    import asyncio
    import member_portal_group_live as mgl
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    s = await asyncio.to_thread(_session, biz, _uuid(sid, "session"))
    if s["status"] != "ended":
        saved = await asyncio.to_thread(
            sb_clients.sb_patch_as_service,
            f"/group_live_sessions?id=eq.{_q(s['id'])}&business_id=eq.{_q(biz)}",
            {"status": "ended", "ended_at": mgl.now_iso(), "updated_at": mgl.now_iso()})
        if not isinstance(saved, list):
            raise HTTPException(503, "That didn't save. Please try again.")
        try:
            await mgl.close_room(s["room_name"])
        except Exception:
            pass
    return {"ok": True}
