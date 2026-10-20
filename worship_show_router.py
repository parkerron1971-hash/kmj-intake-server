# worship_show_router.py — Sundays on screens (ChurchSavvy, step 2; Kevin
# 2026-10-19: "keep going with step 2 I want the entire thing built").
#
# Signed in (the church's seats; the owner, an admin or a manager changes):
#   GET/POST          /worship/services                  a church's services
#   GET/PUT/DELETE    /worship/services/{id}             one (DELETE archives)
#   GET               /worship/services/{id}/show        as slides (worship_show)
#   GET/POST          /worship/screens                   each screen it shows on
#   PUT/DELETE        /worship/screens/{id}
#   POST              /worship/screens/{id}/new-link     retire a screen's link
#   GET/PUT           /worship/look                      the look every slide wears
#   GET/POST          /worship/live                      what's on screen now
#
# No sign-in; a screen's own link (its token) is the key, and it opens
# only what that screen shows:
#   GET  /worship/screen/{token}          the screen, the church's look and brand
#   GET  /worship/screen/{token}/show     the live service as slides
#   GET  /worship/screen/{token}/events   what's on screen now, as it changes
#                                         (Server-Sent Events)
#
# Behind the same switch as the song library (worship_router.mode()): off
# answers 404 everywhere; owner opens the signed-in routes to the
# platform owner only. Screen links work whenever the switch isn't off,
# since only someone the switch let in could have made one.
#
# LIVE. The booth posts the slide; this process hands it to every waiting
# screen at once (LiveHub) and keeps it in worship_live, so a restart or
# a screen that joins late picks up where Sunday is. `rev` is milliseconds
# since 1970 and only goes up. A second copy of the server would still
# reach its screens: a waiting screen re-reads the row every 15 seconds.
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

import sb_clients
import worship_show as wsh
from auth_supabase import AuthedUser, require_user
from business_access import assert_access
from worship_router import mode, open_to

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])

STAFF_ROLES = ("owner", "admin", "manager")
MAX_SCREENS = 20
WAIT_SECONDS = 15.0
PREAMBLE_BYTES = 16384
_SONG_FIELDS = "id,title,song_key,authors,ccli_number,copyright,public_domain,sections,arrangements,lines_per_slide"
_SERVICE_LIST = "id,title,starts_at,is_template,notes,updated_at,items"
_SCREEN_FIELDS = "id,name,role,width,height,fit,led,token,sort,updated_at"


# ─── helpers ─────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _uuid(value: Any, what: str = "business") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} id isn't valid")


def _gate(user: AuthedUser) -> None:
    if not open_to(user):
        raise HTTPException(404, "Not Found")


def _seat(biz: str, user: AuthedUser) -> str:
    _gate(user)
    return assert_access(biz, user)


def _staff(biz: str, user: AuthedUser) -> str:
    _gate(user)
    role = assert_access(biz, user)
    if role not in STAFF_ROLES:
        raise HTTPException(403, "Only the owner, an admin or a manager runs Sunday's screens")
    return role


def _read(path: str, what: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if rows is None:
        raise HTTPException(503, f"{what} couldn't be read. Try again.")
    return rows


def _brand(biz: str, look: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The church's name and the parts of its brand kit a screen draws with (never the rest of its settings).
    A church with no brand kit (ChurchSavvy on its own) draws with the colors and logo set in its look."""
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=name,settings&limit=1") or []
    row = rows[0] if rows else {}
    kit = ((row.get("settings") or {}).get("brand_kit") or {}) if isinstance(row.get("settings"), dict) else {}
    keep = {k: kit[k] for k in ("colors", "font_pair", "font_heading", "font_body", "logo_url", "primary_color",
                                 "secondary_color", "accent_color") if k in kit}
    own = (look or {}).get("brand") or {}
    if not keep and any(own.values()):
        keep = {"colors": {k: own[k] for k in ("primary", "accent", "background") if own.get(k)}}
        if own.get("logo_url"):
            keep["logo_url"] = own["logo_url"]
    return {"name": row.get("name") or "", "brand_kit": keep}


def _look(biz: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/worship_settings?business_id=eq.{_q(biz)}&select=look&limit=1") or []
    try:
        return wsh.clean_look(rows[0]["look"] if rows else {})
    except ValueError:
        return wsh.clean_look({})


def _service(biz: str, sid: str) -> Dict[str, Any]:
    rows = _read(f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&archived_at=is.null"
                 f"&select=id,title,starts_at,items,notes,is_template,updated_at", "The service")
    if not rows:
        raise HTTPException(404, "service not found")
    return rows[0]


def _songs_for(biz: str, items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    ids = wsh.song_ids(items)
    if not ids:
        return {}
    rows = _read(f"/worship_songs?business_id=eq.{_q(biz)}&id=in.({','.join(ids)})&select={_SONG_FIELDS}", "The songs")
    return {r["id"]: r for r in rows}


def _show(biz: str, service: Dict[str, Any]) -> Dict[str, Any]:
    show = wsh.compile_show(service, _songs_for(biz, service.get("items") or []))
    show["look"] = _look(biz)
    show["church"] = _brand(biz, show["look"])
    return show


# ─── the live hub ────────────────────────────────────────────────────


class LiveHub:
    """The newest state per church, and every screen waiting on it. Safe to
    publish from a worker thread: waiters are woken on their own loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Dict[str, Tuple[int, Dict[str, Any]]] = {}
        self._waiters: Dict[str, set] = {}

    def latest(self, biz: str) -> Optional[Tuple[int, Dict[str, Any]]]:
        with self._lock:
            return self._latest.get(biz)

    def publish(self, biz: str, rev: int, state: Dict[str, Any]) -> bool:
        with self._lock:
            cur = self._latest.get(biz)
            if cur and cur[0] >= rev:
                return False
            self._latest[biz] = (rev, state)
            waiters = list(self._waiters.get(biz, ()))
        for loop, ev in waiters:
            try:
                loop.call_soon_threadsafe(ev.set)
            except RuntimeError:  # that screen's loop is gone
                pass
        return True

    async def wait(self, biz: str, after: int, timeout: float) -> Optional[Tuple[int, Dict[str, Any]]]:
        loop = asyncio.get_running_loop()
        ev = asyncio.Event()
        entry = (loop, ev)
        with self._lock:
            self._waiters.setdefault(biz, set()).add(entry)
        try:
            cur = self.latest(biz)
            if cur and cur[0] > after:
                return cur
            try:
                await asyncio.wait_for(ev.wait(), timeout)
            except asyncio.TimeoutError:
                pass
            cur = self.latest(biz)
            return cur if cur and cur[0] > after else None
        finally:
            with self._lock:
                s = self._waiters.get(biz)
                if s is not None:
                    s.discard(entry)
                    if not s:
                        self._waiters.pop(biz, None)


HUB = LiveHub()


def _live_row(biz: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(f"/worship_live?business_id=eq.{_q(biz)}&select=rev,state&limit=1")
    if not rows:
        return None
    return int(rows[0].get("rev") or 0), rows[0].get("state") or {}


def _current(biz: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    """The hub's state, or the saved one (and the hub learns it)."""
    cur = HUB.latest(biz)
    if cur:
        return cur
    row = _live_row(biz)
    if row:
        HUB.publish(biz, row[0], row[1])
    return row


# ─── services ────────────────────────────────────────────────────────


def _service_out(row: Dict[str, Any], full: bool = False) -> Dict[str, Any]:
    items = row.get("items") or []
    out = {k: row.get(k) for k in ("id", "title", "starts_at", "is_template", "notes", "updated_at")}
    out["item_count"] = sum(1 for i in items if i.get("kind") != "section")
    out["minutes"] = round(sum(float(i.get("minutes") or 0) for i in items), 1)
    if full:
        out["items"] = items
    return out


def _clean_service(body: Dict[str, Any], partial: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "title" in body or not partial:
        title = str(body.get("title") or "").strip() or ("" if partial else "Sunday service")
        if not title or len(title) > 120:
            raise ValueError("A service's name is 1 to 120 characters")
        out["title"] = title
    if "starts_at" in body:
        v = body.get("starts_at")
        if v in (None, ""):
            out["starts_at"] = None
        else:
            try:
                out["starts_at"] = datetime.fromisoformat(str(v).replace("Z", "+00:00")).isoformat()
            except ValueError:
                raise ValueError("The start time isn't a date and time")
    if "items" in body:
        out["items"] = wsh.clean_items(body.get("items"))
    if "notes" in body:
        notes = str(body.get("notes") or "")
        if len(notes) > 4000:
            raise ValueError("Notes are at most 4,000 characters")
        out["notes"] = notes
    if "is_template" in body:
        out["is_template"] = bool(body.get("is_template"))
    return out


@router.get("/services")
def list_services(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    role = _seat(biz, user)
    rows = _read(f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&select={_SERVICE_LIST}"
                 f"&order=starts_at.desc.nullslast&limit=200", "Your services")
    return {"services": [_service_out(r) for r in rows], "can_write": role in STAFF_ROLES}


@router.get("/services/{service_id}")
def get_service(service_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _seat(biz, user)
    return {"service": _service_out(_service(biz, _uuid(service_id, "service")), full=True)}


@router.get("/services/{service_id}/show")
def get_show(service_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _seat(biz, user)
    return _show(biz, _service(biz, _uuid(service_id, "service")))


@router.post("/services")
def create_service(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user)
    try:
        fields = _clean_service(body, partial=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.get("from_id"):
        # Start from a template or a past Sunday: its items, fresh title and time.
        src = _service(biz, _uuid(body.get("from_id"), "service"))
        fields.setdefault("items", src.get("items") or [])
        if "notes" not in fields:
            fields["notes"] = src.get("notes") or ""
    now = _now()
    rows = sb_clients.sb_post_as_service("/worship_services?select=" + _SERVICE_LIST,
                                         {**fields, "business_id": biz, "created_at": now, "updated_at": now})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That service didn't save. Try again.")
    return {"ok": True, "service": _service_out(rows[0], full=True)}


@router.put("/services/{service_id}")
def save_service(service_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user)
    sid = _uuid(service_id, "service")
    current = _service(biz, sid)
    try:
        fields = _clean_service(body, partial=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not fields:
        return {"ok": True, "service": _service_out(current, full=True)}
    fields["updated_at"] = _now()
    rows = sb_clients.sb_patch_as_service(
        f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select={_SERVICE_LIST}", fields)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Nothing changed; try again.")
    return {"ok": True, "service": _service_out(rows[0], full=True)}


@router.delete("/services/{service_id}")
def remove_service(service_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _staff(biz, user)
    sid = _uuid(service_id, "service")
    _service(biz, sid)
    rows = sb_clients.sb_patch_as_service(f"/worship_services?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select=id",
                                          {"archived_at": _now(), "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't take the service out. Try again.")
    return {"ok": True}


# ─── screens ─────────────────────────────────────────────────────────


def _clean_screen(body: Dict[str, Any], partial: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "name" in body or not partial:
        name = str(body.get("name") or "").strip()
        if not name or len(name) > 60:
            raise ValueError("Give the screen a name (up to 60 characters)")
        out["name"] = name
    if "role" in body or not partial:
        role = body.get("role") or "room"
        if role not in wsh.ROLES:
            raise ValueError("A screen is the room, the stream, an LED wall, the stage or the lobby")
        out["role"] = role
    for key, lo, hi, label in (("width", 320, 16384, "Width"), ("height", 120, 8192, "Height")):
        if key in body:
            v = body.get(key)
            if not isinstance(v, int) or not lo <= v <= hi:
                raise ValueError(f"{label} is {lo} to {hi} pixels")
            out[key] = v
    if "fit" in body:
        if body.get("fit") not in ("wide", "stretch", "center"):
            raise ValueError("Slides fit wide, stretched or centered")
        out["fit"] = body["fit"]
    if "led" in body:
        led = body.get("led") or {}
        if not isinstance(led, dict):
            raise ValueError("The LED wall's panels aren't right")
        clean = {}
        for key, lo, hi in (("across", 1, 40), ("down", 1, 20), ("px", 32, 512)):
            if key in led:
                v = led[key]
                if not isinstance(v, int) or not lo <= v <= hi:
                    raise ValueError(f"Panels {key} is {lo} to {hi}")
                clean[key] = v
        out["led"] = clean
    if "sort" in body:
        v = body.get("sort")
        if not isinstance(v, int) or not 0 <= v <= 1000:
            raise ValueError("That isn't a place in the list")
        out["sort"] = v
    return out


def _screen_out(row: Dict[str, Any], with_link: bool) -> Dict[str, Any]:
    out = {k: row.get(k) for k in ("id", "name", "role", "width", "height", "fit", "led", "sort", "updated_at")}
    if with_link:
        out["token"] = row.get("token")
    return out


@router.get("/screens")
def list_screens(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    role = _seat(biz, user)
    rows = _read(f"/worship_screens?business_id=eq.{_q(biz)}&archived_at=is.null&select={_SCREEN_FIELDS}"
                 f"&order=sort.asc,created_at.asc", "Your screens")
    staff = role in STAFF_ROLES
    return {"screens": [_screen_out(r, staff) for r in rows], "can_write": staff}


@router.post("/screens")
def create_screen(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user)
    try:
        fields = _clean_screen(body, partial=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    have = _read(f"/worship_screens?business_id=eq.{_q(biz)}&archived_at=is.null&select=id", "Your screens")
    if len(have) >= MAX_SCREENS:
        raise HTTPException(400, f"A church has at most {MAX_SCREENS} screens")
    now = _now()
    rows = sb_clients.sb_post_as_service("/worship_screens?select=" + _SCREEN_FIELDS, {
        **fields, "business_id": biz, "token": secrets.token_urlsafe(32), "sort": fields.get("sort", len(have)),
        "created_at": now, "updated_at": now})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That screen didn't save. Try again.")
    return {"ok": True, "screen": _screen_out(rows[0], True)}


def _own_screen(biz: str, sid: str) -> Dict[str, Any]:
    rows = _read(f"/worship_screens?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&archived_at=is.null&select=id", "The screen")
    if not rows:
        raise HTTPException(404, "screen not found")
    return rows[0]


@router.put("/screens/{screen_id}")
def save_screen(screen_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user)
    sid = _uuid(screen_id, "screen")
    _own_screen(biz, sid)
    try:
        fields = _clean_screen(body, partial=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    fields["updated_at"] = _now()
    rows = sb_clients.sb_patch_as_service(
        f"/worship_screens?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select={_SCREEN_FIELDS}", fields)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Nothing changed; try again.")
    return {"ok": True, "screen": _screen_out(rows[0], True)}


@router.post("/screens/{screen_id}/new-link")
def new_screen_link(screen_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    biz = _uuid((body or {}).get("business_id"))
    _staff(biz, user)
    sid = _uuid(screen_id, "screen")
    _own_screen(biz, sid)
    rows = sb_clients.sb_patch_as_service(
        f"/worship_screens?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select={_SCREEN_FIELDS}",
        {"token": secrets.token_urlsafe(32), "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "The new link didn't save. The old one still works; try again.")
    return {"ok": True, "screen": _screen_out(rows[0], True)}


@router.delete("/screens/{screen_id}")
def remove_screen(screen_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _staff(biz, user)
    sid = _uuid(screen_id, "screen")
    _own_screen(biz, sid)
    # A removed screen's link stops working: archived rows never answer.
    rows = sb_clients.sb_patch_as_service(f"/worship_screens?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select=id",
                                          {"archived_at": _now(), "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't take the screen out. Try again.")
    return {"ok": True}


# ─── the look ────────────────────────────────────────────────────────


@router.get("/look")
def get_look(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    role = _seat(biz, user)
    look = _look(biz)
    return {"look": look, "church": _brand(biz, look), "can_write": role in STAFF_ROLES}


@router.put("/look")
def save_look(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user)
    try:
        look = wsh.clean_look(body.get("look"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    rows = sb_clients.sb_post_as_service("/worship_settings?on_conflict=business_id&select=look",
                                         {"business_id": biz, "look": look, "updated_at": _now()},
                                         prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "The look didn't save. Nothing changed; try again.")
    return {"ok": True, "look": look}


# ─── what's on screen now ────────────────────────────────────────────


@router.get("/live")
def get_live(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    _seat(biz, user)
    cur = _current(biz)
    return {"rev": cur[0] if cur else 0, "state": cur[1] if cur else None}


@router.post("/live")
def set_live(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user)
    try:
        state = wsh.clean_live(body.get("state"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if len(json.dumps(state)) > 50000:
        raise HTTPException(400, "That passage is too long to put up at once. Show part of it.")
    state["at"] = _now()
    prev = _current(biz)
    rev = max(int(time.time() * 1000), (prev[0] + 1) if prev else 0)
    HUB.publish(biz, rev, state)
    row = {"business_id": biz, "service_id": state.get("service_id"), "state": state, "rev": rev, "updated_at": state["at"]}
    saved = sb_clients.sb_post_as_service("/worship_live?on_conflict=business_id&select=rev", row,
                                          prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        # The screens already have it; only a restart would lose it.
        logger.warning("[worship] live state for %s didn't save (rev %s)", biz, rev)
    return {"ok": True, "rev": rev, "saved": bool(saved)}


# ─── a screen's own link ─────────────────────────────────────────────


def screen_from_token(token: str) -> Dict[str, Any]:
    if mode() == "off" or not (32 <= len(token) <= 64) or not all(c.isalnum() or c in "-_" for c in token):
        raise HTTPException(404, "Not Found")
    rows = sb_clients.sb_get_as_service(
        f"/worship_screens?token=eq.{_q(token)}&archived_at=is.null&select=business_id,{_SCREEN_FIELDS}&limit=1",
        redact=True)
    if rows is None:
        raise HTTPException(503, "The screen couldn't be reached. It tries again by itself.")
    if not rows:
        raise HTTPException(404, "This screen's link was changed or removed")
    return rows[0]


@router.get("/screen/{token}")
def screen_info(token: str):
    screen = screen_from_token(token)
    biz = screen["business_id"]
    look = _look(biz)
    return {"screen": _screen_out(screen, False), "church": _brand(biz, look), "look": look}


@router.get("/screen/{token}/show")
def screen_show(token: str):
    screen = screen_from_token(token)
    biz = screen["business_id"]
    cur = _current(biz)
    sid = (cur[1] if cur else {}).get("service_id")
    if not sid:
        return {"service": None, "items": [], "slide_count": 0, "missing": [], "look": _look(biz), "church": _brand(biz, _look(biz))}
    try:
        show = _show(biz, _service(biz, sid))
    except HTTPException as e:
        if e.status_code == 404:
            return {"service": None, "items": [], "slide_count": 0, "missing": [], "look": _look(biz), "church": _brand(biz, _look(biz))}
        raise
    # A screen never gets the booth's notes.
    for item in show["items"]:
        item.pop("notes", None)
    return show


def _sse(rev: int, state: Dict[str, Any]) -> str:
    return f"id: {rev}\nevent: live\ndata: {json.dumps({'rev': rev, 'state': state})}\n\n"


@router.get("/screen/{token}/events")
async def screen_events(token: str, request: Request):
    screen = await asyncio.to_thread(screen_from_token, token)
    biz = screen["business_id"]

    async def events():
        # Railway's edge flushes a response only once ~16 KB has piled up,
        # so a slide (a few hundred bytes) would sit there until the screen
        # gave up. A 16 KB comment first crosses that line, and every event
        # after it goes straight through (what Chief's stream does; clients
        # ignore ":" lines). Found 2026-10-19: the first live screen heard
        # nothing for 20 seconds.
        yield ":" + (" " * PREAMBLE_BYTES) + "\n\n"
        yield "retry: 2000\n\n"
        last = -1
        cur = await asyncio.to_thread(_current, biz)
        if cur:
            yield _sse(*cur)
            last = cur[0]
        while not await request.is_disconnected():
            got = await HUB.wait(biz, last, WAIT_SECONDS)
            if got is None:
                # Quiet for a while: a heartbeat, and a look at the saved
                # row in case another copy of the server took the booth's post.
                row = await asyncio.to_thread(_live_row, biz)
                if row and row[0] > last:
                    HUB.publish(biz, row[0], row[1])
                    got = row
            if got is not None:
                yield _sse(*got)
                last = got[0]
            else:
                yield ": still here\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
