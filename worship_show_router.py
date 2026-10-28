# worship_show_router.py — Sundays on screens (ChurchSavvy, step 2; Kevin
# 2026-10-19: "keep going with step 2 I want the entire thing built").
#
# Signed in. Anyone on the church's team reads; each part changes its own
# (worship_team.py): the plan (planner, worship leader), the screens and
# the look (admin), what's on screen now (planner, booth). The owner, an
# admin or a manager of the church is an admin.
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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

import sb_clients
import worship_show as wsh
from auth_supabase import AuthedUser, require_user
from worship_team import can, can_all, require, roles_of
from worship_router import mode, open_to

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])

MAX_SCREENS = 20
WAIT_SECONDS = 15.0
PREAMBLE_BYTES = 16384
_SONG_FIELDS = "id,title,song_key,authors,ccli_number,copyright,public_domain,sections,arrangements,lines_per_slide"
_SERVICE_LIST = "id,title,starts_at,is_template,notes,updated_at,items"
_SCREEN_FIELDS = "id,name,role,width,height,fit,led,stage,lobby,token,sort,updated_at"


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


def _seat(biz: str, user: AuthedUser) -> set:
    """Anyone on the church's team (worship_team): their parts."""
    _gate(user)
    return roles_of(biz, user)


def _staff(biz: str, user: AuthedUser, what: str) -> set:
    """Refused unless one of the caller's parts may do `what` (plan, run, setup)."""
    _gate(user)
    return require(biz, user, what)


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
    items = service.get("items") or []
    board = None
    if wsh.uses_board(items):
        # The announcement spot and the welcome loop fill themselves from the board
        # for the service's day. A board that can't be read leaves the rest of Sunday
        # on screen (the loop shows the logo) rather than taking the service down.
        from worship_announce_router import board_for  # it imports this module's helpers
        try:
            board = board_for(biz, service.get("starts_at"))
        except HTTPException:
            logger.warning("worship show: the announcements board couldn't be read for %s", biz)
            board = []
    show = wsh.compile_show(service, _songs_for(biz, items), board)
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
    roles = _seat(biz, user)
    rows = _read(f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&select={_SERVICE_LIST}"
                 f"&order=starts_at.desc.nullslast&limit=200", "Your services")
    # can_write: the plan; `can`: each part of ChurchSavvy the caller's team parts allow.
    return {"services": [_service_out(r) for r in rows], "can_write": can(roles, "plan"), "can": can_all(roles)}


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
    _staff(biz, user, "plan")
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
    _staff(biz, user, "plan")
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
    _staff(biz, user, "plan")
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
    if "stage" in body:
        out["stage"] = wsh.clean_stage(body.get("stage"))
    if "lobby" in body:
        # A lobby TV's own week (round 5, board 26).
        out["lobby"] = wsh.clean_lobby(body.get("lobby"))
    return out


def _screen_out(row: Dict[str, Any], with_link: bool) -> Dict[str, Any]:
    out = {k: row.get(k) for k in ("id", "name", "role", "width", "height", "fit", "led", "sort", "updated_at")}
    out["stage"] = wsh.clean_stage(row.get("stage"))
    try:
        out["lobby"] = wsh.clean_lobby(row.get("lobby"))
    except ValueError:
        # A saved week that no longer passes (an older shape) follows the booth.
        out["lobby"] = wsh.clean_lobby({})
    if with_link:
        out["token"] = row.get("token")
    return out


@router.get("/screens")
def list_screens(business_id: str, user: AuthedUser = Depends(require_user)):
    biz = _uuid(business_id)
    roles = _seat(biz, user)
    rows = _read(f"/worship_screens?business_id=eq.{_q(biz)}&archived_at=is.null&select={_SCREEN_FIELDS}"
                 f"&order=sort.asc,created_at.asc", "Your screens")
    # Only the setup ever sees a screen's link.
    setup = can(roles, "setup")
    return {"screens": [_screen_out(r, setup) for r in rows], "can_write": setup}


@router.post("/screens")
def create_screen(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, "setup")
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
    _staff(biz, user, "setup")
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
    _staff(biz, user, "setup")
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
    _staff(biz, user, "setup")
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
    roles = _seat(biz, user)
    look = _look(biz)
    return {"look": look, "church": _brand(biz, look), "can_write": can(roles, "setup")}


@router.put("/look")
def save_look(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, "setup")
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
    _staff(biz, user, "run")
    try:
        state = wsh.clean_live(body.get("state"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if len(json.dumps(state)) > 50000:
        raise HTTPException(400, "That passage is too long to put up at once. Show part of it.")
    with _church_lock(biz):
        state["at"] = _now()
        prev = _current(biz)
        # The preacher's ask and the service's log ride along from the state before (round 5, board 24).
        wsh.carry_ask(prev[1] if prev else None, state)
        wsh.carry_log(prev[1] if prev else None, state, state["at"])
        rev, saved = _put_live(biz, state, prev)
    return {"ok": True, "rev": rev, "saved": saved}


_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _church_lock(biz: str) -> threading.Lock:
    """One church's writes to its live state, one at a time: a press and the preacher's
    ask each read the state, add to it and write it back, so neither may land in between
    the other's read and write (the server runs as one copy; the hub is this process's)."""
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(biz, threading.Lock())


def _put_live(biz: str, state: Dict[str, Any], prev: Optional[Tuple[int, Dict[str, Any]]]) -> Tuple[int, bool]:
    """Every screen hears it at once, then it's saved for a screen that joins later."""
    rev = max(int(time.time() * 1000), (prev[0] + 1) if prev else 0)
    HUB.publish(biz, rev, state)
    row = {"business_id": biz, "service_id": state.get("service_id"), "state": state, "rev": rev, "updated_at": _now()}
    saved = sb_clients.sb_post_as_service("/worship_live?on_conflict=business_id&select=rev", row,
                                          prefer="resolution=merge-duplicates,return=representation")
    if not isinstance(saved, list) or not saved:
        # The screens already have it; only a restart would lose it.
        logger.warning("[worship] live state for %s didn't save (rev %s)", biz, rev)
    return rev, bool(saved)


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
    # A screen never gets the booth's notes; only a stage screen gets the notes for the stage.
    stage = screen.get("role") == "stage"
    for item in show["items"]:
        item.pop("notes", None)
        if not stage:
            item.pop("stage", None)
            for s in item.get("slides") or []:
                if s.get("kind") == "text":
                    s.pop("notes", None)
    return show


@router.post("/screen/{token}/ask")
def screen_ask(token: str):
    """The preacher's phone asks the booth for 5 more minutes (round 5, board 24).
    Only a stage screen's link can; the booth says yes or no."""
    screen = screen_from_token(token)
    if screen.get("role") != "stage":
        raise HTTPException(403, "Only a stage screen can ask the booth for more time")
    biz = screen["business_id"]
    with _church_lock(biz):
        prev = _current(biz)
        state = dict(prev[1]) if prev else {}
        item = state.get("item_id")
        if not item or state.get("adhoc"):
            raise HTTPException(409, "Nothing from the plan is up to ask more time for")
        old = state.get("ask")
        if isinstance(old, dict) and old.get("item_id") == item:
            answered = old.get("answered_at")
            # Asked already and waiting, or answered a moment ago: a second tap asks nothing new.
            if not old.get("answer") or (isinstance(answered, str) and _age(answered) < ASK_AGAIN_SECONDS):
                return {"ok": True, "ask": old, "saved": True}
        state["ask"] = {"minutes": wsh.ASK_MINUTES, "item_id": item, "from": screen.get("name") or "The stage",
                        "at": _now(), "answer": None, "answered_at": None}
        _, saved = _put_live(biz, state, prev)
    # Like a press: the booth and the screens have it either way; only a restart would lose an unsaved one.
    return {"ok": True, "ask": state["ask"], "saved": saved}


ASK_AGAIN_SECONDS = 30


def _age(iso: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


@router.get("/screen/{token}/lobby")
def screen_lobby(token: str):
    """A lobby TV running on its own (round 5, board 26): its week, the announcements
    marked Lobby for today, a verse for the day (KJV), and the next service, with the
    church's clock so the TV keeps the church's time whatever its own says."""
    screen = screen_from_token(token)
    if screen.get("role") != "lobby":
        raise HTTPException(403, "Only a lobby screen runs on its own")
    biz = screen["business_id"]
    look = _look(biz)
    from worship_announce_router import board_for, church_today, church_zone  # it imports this module's helpers
    zone = church_zone(biz)
    try:
        board = board_for(biz, None, "lobby")
    except HTTPException:
        # A board that can't be read leaves the logo, the verse and the clock.
        logger.warning("worship lobby: the announcements board couldn't be read for %s", biz)
        board = []
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=3)).isoformat()
    rows = _read(f"/worship_services?business_id=eq.{_q(biz)}&archived_at=is.null&is_template=eq.false"
                 f"&starts_at=gte.{_q(since)}&select=id,title,starts_at&order=starts_at.asc&limit=1", "The next service")
    nxt = {"id": rows[0]["id"], "title": rows[0].get("title") or "", "starts_at": rows[0].get("starts_at")} if rows else None
    return {"lobby": _screen_out(screen, False)["lobby"], "slides": board, "verse": wsh.lobby_verse(church_today(biz)),
            "next": nxt, "zone": str(zone.key) if hasattr(zone, "key") else "UTC", "look": look, "church": _brand(biz, look)}


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
