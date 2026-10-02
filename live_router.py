"""
live_router.py — Live, the team's side (Kevin's church plan, 2026-09-30).

The church streams where it already does (YouTube, Facebook, Vimeo); in
the app the team starts a live service with that link, and members
watch it inside the member app (member_portal_live.py) with a chat that
is OURS: signed-in members only, first name and last initial, no links,
and moderated from here — hide a message, pause a person for this
service, close the chat. "I'm here" counts a member as online
attendance for the service the session is tied to. Prayer never goes
in the chat; the member app sends it privately to Prayer & care.

  GET   /live?business_id=                 now live (with chat + who's here) and recent
  POST  /live/start                        {business_id, title, stream_url, entry_id?}
  PATCH /live/{sid}                        {business_id, chat_open?, stream_url?, title?}
  POST  /live/{sid}/end                    {business_id}
  GET   /live/{sid}/chat?business_id=      every message (hidden ones flagged), who's here, who's paused
  POST  /live/{sid}/chat                   {business_id, body}  — the host's own message
  POST  /live/{sid}/messages/{mid}/hide    {business_id, hidden}
  POST  /live/{sid}/mute                   {business_id, contact_id, muted}

Seats: any member of the team can watch the chat; running the service
and moderating is a manager's (kids_router.require). The tables are
server-only (APPLY-2026-09-30-live.sql). Every read that fails is a 503,
never an empty chat.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import sb_clients
from auth_supabase import AuthedUser, require_user
from kids_router import _uuid, require

router = APIRouter(tags=["live"])

BODY_MAX = 500
TITLE_MAX = 120
LINK_RE = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|io|co|me|ly|app|tv|link)\b)", re.IGNORECASE)


# ─── pure helpers (member_portal_live uses these too) ────────────────


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def author_for(name: Any) -> str:
    """'Ana Rivers' → 'Ana R.' — what other members see beside a message."""
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "A member"
    return f"{parts[0][:40]} {parts[-1][0].upper()}." if len(parts) > 1 else parts[0][:40]


def clean_body(text: Any) -> str:
    return " ".join(str(text or "").split())[:BODY_MAX]


def has_link(text: str) -> bool:
    """Members can't post links in the chat (spam, and nothing to vet)."""
    return bool(LINK_RE.search(text or ""))


def valid_stream_url(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return True
    try:
        p = urlparse(u)
    except ValueError:
        return False
    return p.scheme == "https" and bool(p.hostname) and len(u) <= 500 and not any(c in u for c in "\r\n<>\"'")


def stream_embed(url: str) -> str:
    """The player src for the stream link, or '' (the page links out).
    A YouTube CHANNEL link plays whatever that channel has live now."""
    from sermons_public import video_embed_src
    u = (url or "").strip()
    try:
        p = urlparse(u)
    except ValueError:
        return ""
    host = (p.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    m = re.match(r"^/channel/(UC[A-Za-z0-9_-]{10,40})(?:/live)?/?$", p.path or "")
    if p.scheme == "https" and host == "youtube.com" and m:
        return f"https://www.youtube.com/embed/live_stream?channel={m.group(1)}"
    return video_embed_src(u)


# ─── reads ───────────────────────────────────────────────────────────


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _unavailable() -> HTTPException:
    return HTTPException(503, "Live couldn't load just now. Please try again.")


def current(business_id: str) -> Optional[Dict[str, Any]]:
    """The church's live session, {} when none, None when the read failed."""
    rows = sb_clients.sb_get_as_service(
        f"/live_sessions?business_id=eq.{_q(business_id)}&status=eq.live"
        f"&select=id,title,stream_url,entry_id,chat_open,chat_version,started_at&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else {}


def session(business_id: str, sid: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/live_sessions?id=eq.{_q(sid)}&business_id=eq.{_q(business_id)}"
        f"&select=id,title,stream_url,entry_id,status,chat_open,chat_version,started_at,ended_at&limit=1")
    if not isinstance(rows, list):
        raise _unavailable()
    if not rows:
        raise HTTPException(404, "That live service isn't here.")
    return rows[0]


def messages(business_id: str, sid: str, include_hidden: bool, limit: int = 200) -> Optional[List[Dict[str, Any]]]:
    """Oldest first (the newest `limit`), or None when the read failed."""
    hidden = "" if include_hidden else "&hidden=eq.false"
    rows = sb_clients.sb_get_as_service(
        f"/live_chat?session_id=eq.{_q(sid)}&business_id=eq.{_q(business_id)}{hidden}"
        f"&select=id,contact_id,author,host,body,hidden,created_at&order=created_at.desc&limit={int(limit)}")
    if not isinstance(rows, list):
        return None
    return list(reversed(rows))


def here(business_id: str, sid: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(
        f"/live_presence?session_id=eq.{_q(sid)}&business_id=eq.{_q(business_id)}"
        f"&select=contact_id,created_at&order=created_at.asc&limit=5000")
    return rows if isinstance(rows, list) else None


def muted(business_id: str, sid: str) -> Optional[List[str]]:
    rows = sb_clients.sb_get_as_service(
        f"/live_mutes?session_id=eq.{_q(sid)}&business_id=eq.{_q(business_id)}&select=contact_id&limit=5000")
    return [str(r["contact_id"]) for r in rows] if isinstance(rows, list) else None


def _names(business_id: str, ids: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for i in range(0, len(ids), 150):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({','.join(ids[i:i + 150])})&select=id,name")
        if not isinstance(rows, list):
            raise _unavailable()
        out.update({str(r["id"]): r.get("name") or "" for r in rows})
    return out


# ─── team routes ─────────────────────────────────────────────────────


class StartIn(BaseModel):
    business_id: str
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    stream_url: str = ""
    entry_id: Optional[str] = None


class PatchIn(BaseModel):
    business_id: str
    chat_open: Optional[bool] = None
    stream_url: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=TITLE_MAX)


class BizIn(BaseModel):
    business_id: str


class ChatIn(BaseModel):
    business_id: str
    body: str = Field(min_length=1, max_length=2000)


class HideIn(BaseModel):
    business_id: str
    hidden: bool


class MuteIn(BaseModel):
    business_id: str
    contact_id: str
    muted: bool


def _saved_one(rows: Any) -> Dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Please try again.")
    return rows[0]


@router.get("/live")
def live_overview(business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business_id")
    require(biz, user, "member")
    cur = current(biz)
    if cur is None:
        raise _unavailable()
    recent = sb_clients.sb_get_as_service(
        f"/live_sessions?business_id=eq.{_q(biz)}&status=eq.ended"
        f"&select=id,title,started_at,ended_at&order=started_at.desc&limit=10")
    if not isinstance(recent, list):
        raise _unavailable()
    live = None
    if cur:
        people = here(biz, cur["id"])
        if people is None:
            raise _unavailable()
        live = {**cur, "embed": stream_embed(cur.get("stream_url") or ""), "here": len(people)}
    for r in recent:
        people = here(biz, r["id"])
        r["here"] = len(people) if people is not None else None
    return {"live": live, "recent": recent}


@router.post("/live/start")
def live_start(body: StartIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    url = body.stream_url.strip()
    if not valid_stream_url(url):
        raise HTTPException(400, "Paste the stream's https:// link (YouTube, Facebook or Vimeo).")
    entry = _uuid(body.entry_id, "entry_id") if body.entry_id else None
    cur = current(biz)
    if cur is None:
        raise _unavailable()
    if cur:
        raise HTTPException(409, "You're already live. End that service first.")
    rows = sb_clients.sb_post_as_service("/live_sessions", {
        "business_id": biz, "title": " ".join(body.title.split())[:TITLE_MAX], "stream_url": url,
        "entry_id": entry, "status": "live", "chat_open": True, "started_by": str(user.id)})
    if not isinstance(rows, list) or not rows:
        # Two managers pressing Go live at once: the database keeps one.
        again = current(biz)
        if again:
            raise HTTPException(409, "You're already live. End that service first.")
        raise HTTPException(503, "Going live didn't save. Please try again.")
    return {"ok": True, "live": {**rows[0], "embed": stream_embed(url), "here": 0}}


@router.patch("/live/{sid}")
def live_patch(sid: str, body: PatchIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    s = session(biz, _uuid(sid, "session"))
    if s["status"] != "live":
        raise HTTPException(409, "That service has ended.")
    patch: Dict[str, Any] = {"updated_at": now_iso()}
    if body.chat_open is not None:
        patch["chat_open"] = body.chat_open
    if body.stream_url is not None:
        if not valid_stream_url(body.stream_url):
            raise HTTPException(400, "Paste the stream's https:// link (YouTube, Facebook or Vimeo).")
        patch["stream_url"] = body.stream_url.strip()
    if body.title is not None and body.title.strip():
        patch["title"] = " ".join(body.title.split())[:TITLE_MAX]
    row = _saved_one(sb_clients.sb_patch_as_service(
        f"/live_sessions?id=eq.{_q(s['id'])}&business_id=eq.{_q(biz)}&status=eq.live", patch))
    return {"ok": True, "live": {**row, "embed": stream_embed(row.get("stream_url") or "")}}


@router.post("/live/{sid}/end")
def live_end(sid: str, body: BizIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    s = session(biz, _uuid(sid, "session"))
    if s["status"] == "ended":
        return {"ok": True}
    _saved_one(sb_clients.sb_patch_as_service(
        f"/live_sessions?id=eq.{_q(s['id'])}&business_id=eq.{_q(biz)}&status=eq.live",
        {"status": "ended", "ended_at": now_iso(), "updated_at": now_iso()}))
    return {"ok": True}


@router.get("/live/{sid}/chat")
def live_chat(sid: str, business_id: str = Query(...), user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id, "business_id")
    require(biz, user, "member")
    s = session(biz, _uuid(sid, "session"))
    msgs, people, paused = messages(biz, s["id"], True), here(biz, s["id"]), muted(biz, s["id"])
    if msgs is None or people is None or paused is None:
        raise _unavailable()
    names = _names(biz, sorted({str(p["contact_id"]) for p in people}))
    return {"session": s, "v": s.get("chat_version") or 0, "messages": msgs, "muted": paused,
            "here": [{"contact_id": p["contact_id"], "name": names.get(str(p["contact_id"]), "")} for p in people]}


@router.post("/live/{sid}/chat")
def live_host_message(sid: str, body: ChatIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    s = session(biz, _uuid(sid, "session"))
    if s["status"] != "live":
        raise HTTPException(409, "That service has ended.")
    text = clean_body(body.body)
    if not text:
        raise HTTPException(400, "Write a message first.")
    row = _saved_one(sb_clients.sb_post_as_service("/live_chat", {
        "business_id": biz, "session_id": s["id"], "contact_id": None, "author": "Host", "host": True, "body": text}))
    return {"ok": True, "message": row}


@router.post("/live/{sid}/messages/{mid}/hide")
def live_hide(sid: str, mid: str, body: HideIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    s = session(biz, _uuid(sid, "session"))
    patch = ({"hidden": True, "hidden_by": str(user.id), "hidden_at": now_iso()} if body.hidden
             else {"hidden": False, "hidden_by": None, "hidden_at": None})
    row = _saved_one(sb_clients.sb_patch_as_service(
        f"/live_chat?id=eq.{_q(_uuid(mid, 'message'))}&session_id=eq.{_q(s['id'])}&business_id=eq.{_q(biz)}", patch))
    return {"ok": True, "message": row}


@router.post("/live/{sid}/mute")
def live_mute(sid: str, body: MuteIn, user: AuthedUser = Depends(require_user)):
    biz = _uuid(body.business_id, "business_id")
    require(biz, user, "manager")
    s = session(biz, _uuid(sid, "session"))
    cid = _uuid(body.contact_id, "contact_id")
    if body.muted:
        rows = sb_clients.sb_post_as_service(
            "/live_mutes?on_conflict=session_id,contact_id",
            {"session_id": s["id"], "contact_id": cid, "business_id": biz, "muted_by": str(user.id)},
            prefer="return=representation,resolution=ignore-duplicates")
        if rows is None:
            raise HTTPException(503, "That didn't save. Please try again.")
    else:
        if not sb_clients.sb_delete_as_service(
                f"/live_mutes?session_id=eq.{_q(s['id'])}&contact_id=eq.{_q(cid)}&business_id=eq.{_q(biz)}"):
            raise HTTPException(503, "That didn't save. Please try again.")
    return {"ok": True, "muted": body.muted}
