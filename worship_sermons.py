# worship_sermons.py — sermons from ChurchSavvy, for the church's team.
#
# Kevin, 2026-10-23 ("Church Areas and Keys"): a Media team gets the media
# part already set up. The office keeps sermons in its own Sermons page,
# which writes the tables straight through the database's seat rules
# (APPLY-2026-09-30-sermons.sql). A volunteer on ChurchSavvy's team has no
# seat, so their sermons go through here, as the server, and only the parts
# worship_team.CAN["sermons"] names (Media, Admin; the owner, an admin or a
# manager of the church is an admin there) change anything. Every part reads.
#
#   GET     /worship/sermons?business_id=        the sermons and series, newest first
#   POST    /worship/sermons                     a sermon
#   PATCH   /worship/sermons/{id}                change one
#   DELETE  /worship/sermons/{id}?business_id=   take one down
#   POST    /worship/sermon-series               a series
#   PATCH   /worship/sermon-series/{id}          rename or describe one
#   DELETE  /worship/sermon-series/{id}?business_id=   its sermons stay, outside a series
#
# The same limits as the tables' own checks, said in words before the
# database has to refuse. A series named by a sermon must be the church's
# own. A failed read or write is a 503, never an empty library.
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user
from worship_team import _gate, can, require, roles_of

router = APIRouter(prefix="/worship", tags=["worship"])

SERMON_FIELDS = ("series_id", "title", "preached_on", "speaker", "scripture", "summary", "questions",
                 "video_url", "audio_url", "published")
SERMON_SELECT = "id,series_id,title,preached_on,speaker,scripture,summary,questions,video_url,audio_url,published,updated_at"
SERIES_SELECT = "id,title,description,updated_at"
TEXT_LIMITS = {"title": 160, "speaker": 100, "scripture": 160, "summary": 2000, "questions": 2000}
LABELS = {"title": "The title", "speaker": "The speaker", "scripture": "The scripture",
          "summary": "The summary", "questions": "The questions"}
URL_MAX = 500


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _uuid(value: Any, what: str = "business") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} id isn't valid")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, "Sermons couldn't be read just now. Try again.")
    return rows


def _saved(rows: Any) -> Dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Try again.")
    return rows[0]


def _text(body: Dict[str, Any], key: str, *, required: bool = False) -> str:
    v = body.get(key)
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise HTTPException(400, f"{LABELS[key]} should be words")
    v = v.strip()
    if required and not v:
        raise HTTPException(400, f"{LABELS[key]} can't be empty")
    if len(v) > TEXT_LIMITS[key]:
        raise HTTPException(400, f"{LABELS[key]} is at most {TEXT_LIMITS[key]} characters")
    return v


def _link(body: Dict[str, Any], key: str) -> str:
    v = body.get(key) or ""
    if not isinstance(v, str):
        raise HTTPException(400, "A link should be an https:// address")
    v = v.strip()
    if v and (len(v) > URL_MAX or not v.startswith("https://") or re.search(r"\s", v)):
        raise HTTPException(400, "A link starts with https:// and is at most 500 characters")
    return v


def _series_of(biz: str, series_id: Any) -> Optional[str]:
    """A series the sermon points at, refused unless it's this church's."""
    if series_id in (None, ""):
        return None
    sid = _uuid(series_id, "series")
    if not _rows(f"/sermon_series?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select=id&limit=1"):
        raise HTTPException(404, "That series isn't this church's")
    return sid


def _sermon_change(biz: str, body: Dict[str, Any], *, new: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in SERMON_FIELDS:
        if not new and key not in body:
            continue
        if key == "series_id":
            out[key] = _series_of(biz, body.get(key))
        elif key == "preached_on":
            raw = body.get(key)
            try:
                out[key] = date.fromisoformat(str(raw)).isoformat()
            except (ValueError, TypeError):
                raise HTTPException(400, "The day it was preached, like 2026-10-25")
        elif key == "published":
            v = body.get(key, True)
            if not isinstance(v, bool):
                raise HTTPException(400, "Published is yes or no")
            out[key] = v
        elif key in ("video_url", "audio_url"):
            out[key] = _link(body, key)
        else:
            out[key] = _text(body, key, required=(key == "title"))
    return out


def _sermon(biz: str, sermon_id: str) -> Dict[str, Any]:
    rows = _rows(f"/sermons?id=eq.{_q(sermon_id)}&business_id=eq.{_q(biz)}&select=id&limit=1")
    if not rows:
        raise HTTPException(404, "That sermon isn't here")
    return rows[0]


def _one_series(biz: str, series_id: str) -> Dict[str, Any]:
    rows = _rows(f"/sermon_series?id=eq.{_q(series_id)}&business_id=eq.{_q(biz)}&select=id&limit=1")
    if not rows:
        raise HTTPException(404, "That series isn't here")
    return rows[0]


def _series_change(body: Dict[str, Any], *, new: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if new or "title" in body:
        t = body.get("title")
        if not isinstance(t, str) or not 1 <= len(t.strip()) <= 100:
            raise HTTPException(400, "A series needs a name (at most 100 characters)")
        out["title"] = t.strip()
    if new or "description" in body:
        d = body.get("description") or ""
        if not isinstance(d, str) or len(d.strip()) > 1000:
            raise HTTPException(400, "The description is at most 1000 characters")
        out["description"] = d.strip()
    return out


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("/sermons")
def list_sermons(business_id: str, user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid(business_id)
    roles = roles_of(biz, user)
    sermons = _rows(f"/sermons?business_id=eq.{_q(biz)}&select={SERMON_SELECT}&order=preached_on.desc&limit=500")
    series = _rows(f"/sermon_series?business_id=eq.{_q(biz)}&select={SERIES_SELECT}&order=title.asc&limit=200")
    import church_follow_up as cfu
    site = cfu.site_origin(biz)
    return {"sermons": sermons, "series": series, "can_write": can(roles, "sermons"),
            "public_base": f"{site}/sermons" if site else ""}


@router.post("/sermons")
def create_sermon(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    require(biz, user, "sermons")
    row = {"business_id": biz, **_sermon_change(biz, body, new=True)}
    return {"sermon": _saved(sb_clients.sb_post_as_service(f"/sermons?select={SERMON_SELECT}", row,
                                                           prefer="return=representation"))}


@router.patch("/sermons/{sermon_id}")
def change_sermon(sermon_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    require(biz, user, "sermons")
    sid = _uuid(sermon_id, "sermon")
    _sermon(biz, sid)
    change = _sermon_change(biz, body, new=False)
    if not change:
        raise HTTPException(400, "Nothing to change")
    change["updated_at"] = _now()
    return {"sermon": _saved(sb_clients.sb_patch_as_service(
        f"/sermons?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select={SERMON_SELECT}", change))}


@router.delete("/sermons/{sermon_id}")
def delete_sermon(sermon_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid(business_id)
    require(biz, user, "sermons")
    sid = _uuid(sermon_id, "sermon")
    _sermon(biz, sid)
    if not sb_clients.sb_delete_as_service(f"/sermons?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "It's still there. Try again.")
    return {"ok": True}


@router.post("/sermon-series")
def create_series(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    require(biz, user, "sermons")
    row = {"business_id": biz, **_series_change(body, new=True)}
    return {"series": _saved(sb_clients.sb_post_as_service(f"/sermon_series?select={SERIES_SELECT}", row,
                                                           prefer="return=representation"))}


@router.patch("/sermon-series/{series_id}")
def change_series(series_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    require(biz, user, "sermons")
    sid = _uuid(series_id, "series")
    _one_series(biz, sid)
    change = _series_change(body, new=False)
    if not change:
        raise HTTPException(400, "Nothing to change")
    change["updated_at"] = _now()
    return {"series": _saved(sb_clients.sb_patch_as_service(
        f"/sermon_series?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select={SERIES_SELECT}", change))}


@router.delete("/sermon-series/{series_id}")
def delete_series(series_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    """The series goes; its sermons stay, outside any series (the table's
    own `on delete set null`)."""
    _gate(user)
    biz = _uuid(business_id)
    require(biz, user, "sermons")
    sid = _uuid(series_id, "series")
    _one_series(biz, sid)
    if not sb_clients.sb_delete_as_service(f"/sermon_series?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}"):
        raise HTTPException(503, "It's still there. Try again.")
    return {"ok": True}
