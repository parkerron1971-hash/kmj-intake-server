# worship_router.py
#
# The church song library and Scripture on the spot, for Sunday screens
# (ChurchSavvy step 2; canvas "ChurchSavvy Presenter", boards 10-13 and 22).
#
#   GET    /worship/status?business_id=        is it on for this person, can they edit
#   POST   /worship/parse                      words -> sections, saves nothing
#   GET    /worship/songs?business_id=         the library (no words, just facts)
#   GET    /worship/songs/{id}?business_id=    one song, words and orders
#   POST   /worship/songs                      add a song (words as text, or sections)
#   PUT    /worship/songs/{id}                 change a song
#   DELETE /worship/songs/{id}?business_id=    take a song out of the library
#   POST   /worship/import/proclaim            the church's own Proclaim files -> songs
#   GET    /worship/scripture?q=&tr=           "rom 8 28" -> the passage as slides; "still waters" -> verses by their words
#
# The switch: WORSHIP_SONGS = off | owner | on (default owner). Features
# switch on on Thursdays (docs/OPERATIONS.md); until then only the platform
# owner reaches any of this, and everyone else gets the same 404 as a route
# that doesn't exist.
#
# The team (worship_team.py): anyone on it, or with a seat at the church,
# reads; a planner, the worship leader or an admin changes the library
# (the owner, an admin or a manager of the church is an admin); the booth
# fixes a typo in the words of the slide that's up, and nothing else.
# Table is server-only (supabase/APPLY-2026-10-19-worship-songs.sql).

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

import sb_clients
import worship_lyrics as wl
import worship_proclaim as wp
import worship_scripture as ws
from auth_supabase import AuthedUser, require_user
from worship_team import can, can_all, require, roles_of, ROLES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/worship", tags=["worship"])

MAX_WORDS_CHARS = 20000
MAX_IMPORT_FILES = 8
MAX_IMPORT_BYTES = 64 * 1024 * 1024  # PresentationManager.db at a busy church is ~26 MB
_SECTION_ID = re.compile(r"^[a-z]{1,2}\d{0,2}(-\d{1,2})?$")
_ARRANGEMENT_ID = re.compile(r"^[a-z0-9-]{1,20}$")
_KEY = re.compile(r"^[A-G](#|b)?m?$")
_LIST = ("id,title,needs_title,authors,ccli_number,copyright,public_domain,song_key,tempo,lines_per_slide,"
         "has_words,source,times_sung,last_sung,updated_at")
_FULL = ("id,title,needs_title,authors,ccli_number,copyright,public_domain,song_key,tempo,sections,arrangements,"
         "lines_per_slide,has_words,source,times_sung,last_sung,updated_at")


# ─── the switch ──────────────────────────────────────────────────────


def mode() -> str:
    m = (os.environ.get("WORSHIP_SONGS") or "owner").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_to(user: AuthedUser) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        owner = (os.environ.get("PLATFORM_OWNER_EMAIL") or "kmjcreativesolution@gmail.com").strip().lower()
        return (user.email or "").strip().lower() == owner
    return False


def _gate(user: AuthedUser) -> None:
    if not open_to(user):
        raise HTTPException(404, "Not Found")


# ─── helpers ─────────────────────────────────────────────────────────


def _uuid(value: Any, what: str = "business") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        raise HTTPException(400, f"That {what} id isn't valid")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _staff(biz: str, user: AuthedUser, what: str = "songs") -> set:
    """The caller's parts on the church's team (worship_team), refused unless one may do `what`."""
    return require(biz, user, what)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(body: Dict[str, Any], key: str, limit: int) -> str:
    v = body.get(key)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValueError(f"{key} should be text")
    v = v.strip()
    if len(v) > limit:
        raise ValueError(f"{key.replace('_', ' ').capitalize()} is too long (at most {limit} characters)")
    return v


def clean_sections(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > 40:
        raise ValueError("A song has at most 40 parts")
    out, seen = [], set()
    for s in raw:
        if not isinstance(s, dict):
            raise ValueError("Each part needs a name and words")
        sid = str(s.get("id") or "")
        kind = str(s.get("kind") or "other")
        if not _SECTION_ID.match(sid) or sid in seen:
            raise ValueError("Each part needs its own id")
        if kind not in wl.KIND_LABELS:
            raise ValueError(f"“{kind}” isn't a kind of part")
        label = str(s.get("label") or wl.KIND_LABELS[kind]).strip()[:40]
        number = s.get("number")
        number = int(number) if isinstance(number, (int, float)) and 0 < int(number) < 100 else None
        lines = s.get("lines") or []
        if not isinstance(lines, list) or len(lines) > 80 or not all(isinstance(ln, str) and len(ln) <= 200 for ln in lines):
            raise ValueError(f"{label} has too many lines, or a line that's too long")
        seen.add(sid)
        out.append({"id": sid, "kind": kind, "number": number, "label": label, "lines": [ln.rstrip() for ln in lines]})
    return out


def clean_arrangements(raw: Any, sections: List[Dict[str, Any]], fallback: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Orders that only name parts the song has. With none left, one "Main" order:
    `fallback` (the order the words were sung in) or every part once."""
    ids = {s["id"] for s in sections}
    out, seen = [], set()
    for a in (raw if isinstance(raw, list) else [])[:12]:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id") or "")
        if not _ARRANGEMENT_ID.match(aid) or aid in seen:
            continue
        name = str(a.get("name") or "").strip()[:40] or "Main"
        order = [str(x) for x in (a.get("order") or []) if str(x) in ids][:100]
        if order:
            seen.add(aid)
            out.append({"id": aid, "name": name, "order": order})
    if not out and sections:
        order = [i for i in (fallback or []) if i in ids] or [s["id"] for s in sections]
        out = [{"id": "main", "name": "Main", "order": order}]
    return out


def clean(body: Dict[str, Any], *, partial: bool = False, current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The fields a save writes, checked. `words` (text) is parsed into sections."""
    out: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
    if "words" in body:
        words = body.get("words") or ""
        if not isinstance(words, str) or len(words) > MAX_WORDS_CHARS:
            raise ValueError(f"The words are too long (at most {MAX_WORDS_CHARS} characters)")
        parsed = wl.parse_lyrics(words)
        meta = parsed["meta"]
        out["sections"] = parsed["sections"]
        out["_parsed_order"] = parsed["order"]
    elif "sections" in body:
        out["sections"] = clean_sections(body.get("sections"))
    if "title" in body or not partial:
        title = _text(body, "title", 160) or meta.get("title") or ""
        if not title:
            raise ValueError("Give the song a name")
        out["title"] = title
        out["needs_title"] = False
    for key, limit in (("authors", 300), ("copyright", 300)):
        if key in body:
            out[key] = _text(body, key, limit)
        elif meta.get(key) and not partial:
            out[key] = str(meta[key])[:limit]
    if "ccli_number" in body or (meta.get("ccli_number") and not partial):
        n = _text(body, "ccli_number", 12) if "ccli_number" in body else meta["ccli_number"]
        n = re.sub(r"\D", "", n)
        if n and not 3 <= len(n) <= 9:
            raise ValueError("A CCLI song number is 3 to 9 digits")
        out["ccli_number"] = n or None
    if "public_domain" in body:
        out["public_domain"] = bool(body.get("public_domain"))
    if "song_key" in body:
        k = _text(body, "song_key", 4)
        if k and not _KEY.match(k):
            raise ValueError("A key looks like G, Bb, F# or Em")
        out["song_key"] = k or None
    if "tempo" in body:
        t = body.get("tempo")
        if t in (None, ""):
            out["tempo"] = None
        elif isinstance(t, (int, float)) and 20 <= int(t) <= 300:
            out["tempo"] = int(t)
        else:
            raise ValueError("Tempo is a number of beats a minute, 20 to 300")
    if "lines_per_slide" in body:
        n = body.get("lines_per_slide")
        if not isinstance(n, int) or not 1 <= n <= 6:
            raise ValueError("Lines on a slide is 1 to 6")
        out["lines_per_slide"] = n
    if "source" in body and body.get("source") in ("typed", "pasted", "songselect", "photo", "hymnal"):
        out["source"] = body["source"]

    sections = out.get("sections")
    if sections is not None:
        out["has_words"] = wl.has_words({"sections": sections})
    parsed_order = out.pop("_parsed_order", None)
    if "arrangements" in body or sections is not None:
        secs = sections if sections is not None else (current or {}).get("sections") or []
        raw = body.get("arrangements") if "arrangements" in body else (current or {}).get("arrangements")
        out["arrangements"] = clean_arrangements(raw, secs, parsed_order)
    return out


def _list_out(row: Dict[str, Any]) -> Dict[str, Any]:
    o = {k: row.get(k) for k in ("id", "title", "needs_title", "authors", "ccli_number", "copyright", "public_domain",
                                 "song_key", "tempo", "lines_per_slide", "has_words", "source", "times_sung",
                                 "last_sung", "updated_at")}
    o["times_sung"] = o.get("times_sung") or {}
    return o


def _full_out(row: Dict[str, Any]) -> Dict[str, Any]:
    o = _list_out(row)
    o["sections"] = row.get("sections") or []
    o["arrangements"] = row.get("arrangements") or []
    return o


def _get_or_404(biz: str, song_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/worship_songs?id=eq.{_q(song_id)}&business_id=eq.{_q(biz)}&archived_at=is.null&select={_FULL}")
    if rows is None:
        raise HTTPException(503, "The song couldn't be read. Try again.")
    if not rows:
        raise HTTPException(404, "song not found")
    return rows[0]


# ─── routes ──────────────────────────────────────────────────────────


@router.get("/status")
def status(business_id: str, user: AuthedUser = Depends(require_user)):
    if not open_to(user):
        return {"enabled": False, "can_write": False}
    roles = roles_of(_uuid(business_id), user)
    allowed = can_all(roles)
    # can_write: the song library; `can` is each part of ChurchSavvy, `roles` the caller's parts.
    return {"enabled": True, "can_write": allowed["songs"], "can": allowed, "roles": [r for r in ROLES if r in roles]}


@router.post("/parse")
def parse(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    words = (body or {}).get("words") or ""
    if not isinstance(words, str) or len(words) > MAX_WORDS_CHARS:
        raise HTTPException(400, f"The words are too long (at most {MAX_WORDS_CHARS} characters)")
    parsed = wl.parse_lyrics(words)
    return {"sections": parsed["sections"], "order": parsed["order"], "meta": parsed["meta"],
            "has_words": wl.has_words(parsed)}


@router.get("/songs")
def list_songs(business_id: str, user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid(business_id)
    roles = roles_of(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/worship_songs?business_id=eq.{_q(biz)}&archived_at=is.null&select={_LIST}&order=title.asc&limit=2000")
    if rows is None:
        raise HTTPException(503, "The song library couldn't be read. Try again.")
    return {"songs": [_list_out(r) for r in rows], "can_write": can(roles, "songs")}


@router.get("/songs/{song_id}")
def get_song(song_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid(business_id)
    roles_of(biz, user)
    return {"song": _full_out(_get_or_404(biz, _uuid(song_id, "song")))}


@router.post("/songs")
def create_song(body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid((body or {}).get("business_id"))
    _staff(biz, user)
    try:
        fields = clean(body or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    fields.setdefault("sections", [])
    fields.setdefault("arrangements", [])
    fields.setdefault("has_words", False)
    now = _now()
    rows = sb_clients.sb_post_as_service("/worship_songs", {**fields, "business_id": biz, "created_at": now,
                                                            "updated_at": now}, prefer="return=representation")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That song didn't save. Try again.")
    return {"ok": True, "song": _full_out(rows[0])}


@router.put("/songs/{song_id}")
def save_song(song_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid((body or {}).get("business_id"))
    _staff(biz, user)
    sid = _uuid(song_id, "song")
    current = _get_or_404(biz, sid)
    try:
        fields = clean(body or {}, partial=True, current=current)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not fields:
        return {"ok": True, "song": _full_out(current)}
    fields["updated_at"] = _now()
    rows = sb_clients.sb_patch_as_service(
        f"/worship_songs?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select={_FULL}", fields)
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't save. Nothing changed; try again.")
    return {"ok": True, "song": _full_out(rows[0])}


@router.post("/songs/{song_id}/fix")
def fix_words(song_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    """The booth fixes a typo on the slide that's up (board "Live": "Fix the
    words on slide 5"): the slide's lines, as they were, become the fixed
    ones, in the song itself, so every Sunday after has them right. The
    booth's part allows this and nothing else in the library. The same
    number of lines, so the slides stay as they were planned."""
    _gate(user)
    body = body or {}
    biz = _uuid(body.get("business_id"))
    _staff(biz, user, "fix")
    sid = _uuid(song_id, "song")
    old, new, part = body.get("old"), body.get("new"), body.get("section_id")
    if (not isinstance(old, list) or not isinstance(new, list) or not old or len(old) != len(new) or len(old) > 12
            or not all(isinstance(x, str) and len(x) <= 200 for x in old + new)):
        raise HTTPException(400, "Fix the words on the slide's own lines")
    if not any(ln.strip() for ln in new):
        raise HTTPException(400, "The slide needs its words")
    current = _get_or_404(biz, sid)
    sections = [dict(s) for s in current.get("sections") or []]
    sec = next((s for s in sections if s.get("id") == part), None)
    lines = list((sec or {}).get("lines") or [])
    at = next((k for k in range(len(lines) - len(old) + 1)
               if [x.strip() for x in lines[k:k + len(old)]] == [x.strip() for x in old]), None)
    if sec is None or at is None:
        raise HTTPException(409, "The song changed since this slide went up. Fix it in Songs.")
    sec["lines"] = lines[:at] + [x.rstrip() for x in new] + lines[at + len(old):]
    rows = sb_clients.sb_patch_as_service(
        f"/worship_songs?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select={_FULL}",
        {"sections": sections, "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "The fix didn't save. Nothing changed; try again.")
    return {"ok": True, "song": _full_out(rows[0])}


@router.delete("/songs/{song_id}")
def remove_song(song_id: str, business_id: str, user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid(business_id)
    _staff(biz, user)
    sid = _uuid(song_id, "song")
    _get_or_404(biz, sid)
    rows = sb_clients.sb_patch_as_service(
        f"/worship_songs?id=eq.{_q(sid)}&business_id=eq.{_q(biz)}&select=id", {"archived_at": _now(), "updated_at": _now()})
    if not isinstance(rows, list) or not rows:
        raise HTTPException(503, "That didn't take the song out. Try again.")
    return {"ok": True}


# ─── bringing songs over from Proclaim ───────────────────────────────


def _proclaim_ref(title: str) -> str:
    return ("proclaim:" + re.sub(r"\s+", " ", title.strip().lower()))[:200]


def _import_rows(biz: str, songs: List[Dict[str, Any]]) -> Dict[str, Any]:
    existing = sb_clients.sb_get_as_service(
        f"/worship_songs?business_id=eq.{_q(biz)}&source=eq.proclaim&select=id,source_ref,has_words,archived_at")
    if existing is None:
        raise HTTPException(503, "The song library couldn't be read, so nothing was brought over. Try again.")
    by_ref = {r.get("source_ref"): r for r in existing}
    now = _now()
    new_rows: List[Dict[str, Any]] = []
    added = updated = already = 0
    for s in songs:
        ref = _proclaim_ref(s["title"] if not s["needs_title"] else "untitled " + ",".join(s["proclaim_song_ids"]))
        sung = {str(y): int(n) for y, n in (s.get("times_sung_by_year") or {}).items() if n}
        row = {
            "title": s["title"][:160], "needs_title": bool(s["needs_title"]),
            "song_key": s["key"] if s.get("key") and _KEY.match(s["key"]) else None,
            "sections": s["sections"], "has_words": bool(s["has_words"]),
            "arrangements": [{"id": "main", "name": "Main", "order": s["order"]}] if s["order"] else [],
            "source": "proclaim", "source_ref": ref, "times_sung": sung, "last_sung": s.get("last_sung"),
        }
        prior = by_ref.get(ref)
        if prior is None:
            new_rows.append({**row, "business_id": biz, "created_at": now, "updated_at": now})
            added += 1
        elif not prior.get("has_words") and row["has_words"] and not prior.get("archived_at"):
            # The church kept an empty copy; the words have turned up since.
            patch = {k: row[k] for k in ("sections", "has_words", "arrangements", "times_sung", "last_sung")}
            patch["updated_at"] = now
            got = sb_clients.sb_patch_as_service(f"/worship_songs?id=eq.{_q(prior['id'])}&select=id", patch)
            if not isinstance(got, list) or not got:
                raise HTTPException(503, "Some songs didn't save. Nothing is lost; run it again.")
            updated += 1
        else:
            already += 1
    for k in range(0, len(new_rows), 50):
        chunk = new_rows[k:k + 50]
        # Ask for the new ids: a return=minimal success has an empty body,
        # which sb_clients hands back as None, the same as a refusal.
        got = sb_clients.sb_post_as_service("/worship_songs?select=id", chunk, prefer="return=representation")
        if not isinstance(got, list) or len(got) != len(chunk):
            raise HTTPException(503, "Some songs didn't save. Nothing is lost; run it again and it picks up where it stopped.")
    return {"added": added, "updated": updated, "already_here": already}


# A plain def: FastAPI runs it in its thread pool, so the reads, the
# SQLite work and the saves below never hold up the event loop.
@router.post("/import/proclaim")
def import_proclaim(business_id: str = Form(...), files: List[UploadFile] = File(...),
                    user: AuthedUser = Depends(require_user)):
    _gate(user)
    biz = _uuid(business_id)
    _staff(biz, user)
    if not files or len(files) > MAX_IMPORT_FILES:
        raise HTTPException(400, f"Choose the Proclaim folder (at most {MAX_IMPORT_FILES} files are read)")
    tmp = Path(tempfile.mkdtemp(prefix="proclaim-"))
    try:
        paths: List[Path] = []
        for k, f in enumerate(files):
            dest = tmp / f"{k}.db"
            size = 0
            with open(dest, "wb") as out:
                while True:
                    chunk = f.file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_IMPORT_BYTES:
                        raise HTTPException(413, "One of those files is bigger than Proclaim's song and service files ever are")
                    out.write(chunk)
            paths.append(dest)
        kinds = [wp.kind_of(p) for p in paths]
        if not any(kinds):
            raise HTTPException(400, "Those files aren't Proclaim's. Choose the Proclaim folder itself.")
        result = wp.read_proclaim([p for p, k in zip(paths, kinds) if k])
        saved = _import_rows(biz, result["songs"])
        without = sorted((s["title"] for s in result["songs"] if not s["has_words"]), key=str.lower)
        return {"ok": True, **result["summary"], **saved, "without_words": len(without), "need_words": without[:40]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─── Scripture on the spot ───────────────────────────────────────────


@router.get("/scripture")
async def scripture(q: str, tr: str = "kjv", user: AuthedUser = Depends(require_user)):
    _gate(user)
    if not q.strip() or len(q) > 60:
        raise HTTPException(400, "Type a passage, like rom 8 28 or ps 23")
    return await asyncio.to_thread(ws.choices, q, tr)
