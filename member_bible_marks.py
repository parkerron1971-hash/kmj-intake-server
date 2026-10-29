"""
member_bible_marks.py — a member's own highlights, notes and bookmarks in
the member app's Bible.

Kevin, 2026-10-19 (the Bible "needs major upgrade ... and the ability to
highlight and take notes"; approved on the "Member App, Round Three"
canvas, boards 8 and 9).

One row per member per verse (bible_marks): a highlight in one of five
colours, a private note, a bookmark. They are the member's alone: no staff
route reads them, and the owner's Preview as a member neither shows nor
writes them (a preview is the owner seeing the app AS a member, and these
are private). They follow the member to any phone they sign in on.

    POST /my/bible/mark   JSON {book, chapter, verse, colour?, note?, bookmark?}
                          → {ok, mark} (mark null when nothing is left on it)

A row with no colour, no note and no bookmark is deleted.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import bible_text as bt
import sb_clients

logger = logging.getLogger("member_bible_marks")
router = APIRouter(tags=["member-portal"])

COLOURS = ("gold", "pink", "teal", "violet", "coral")
NOTE_MAX = 2000
LIST_MAX = 500
_FIELDS = "book,chapter,verse,colour,note,bookmarked,updated_at"


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _who(business_id: str, contact_id: str) -> str:
    return f"business_id=eq.{_q(business_id)}&contact_id=eq.{_q(contact_id)}"


def chapter_marks(business_id: str, contact_id: str, book: str, ch: int) -> Optional[Dict[int, Dict[str, Any]]]:
    """{verse: mark} for one chapter, or None when the read failed."""
    rows = sb_clients.sb_get_as_service(
        f"/bible_marks?{_who(business_id, contact_id)}&book=eq.{_q(book)}&chapter=eq.{int(ch)}&select={_FIELDS}")
    if not isinstance(rows, list):
        return None
    return {int(r["verse"]): r for r in rows}


def all_marks(business_id: str, contact_id: str) -> Optional[List[Dict[str, Any]]]:
    """The member's marks, newest first (at most 500), or None."""
    rows = sb_clients.sb_get_as_service(
        f"/bible_marks?{_who(business_id, contact_id)}&select={_FIELDS}&order=updated_at.desc&limit={LIST_MAX}")
    return rows if isinstance(rows, list) else None


def counts(rows: Optional[List[Dict[str, Any]]]) -> Dict[str, int]:
    rows = rows or []
    return {"highlights": sum(1 for r in rows if r.get("colour")),
            "notes": sum(1 for r in rows if (r.get("note") or "").strip()),
            "bookmarks": sum(1 for r in rows if r.get("bookmarked"))}


def clean(body: Dict[str, Any], tr: str = bt.DEFAULT) -> Optional[Dict[str, Any]]:
    """The change, checked: a real verse, a colour of the five (or '' to
    take it off), a note of at most 2000 characters, a bookmark yes or no.
    None when anything is off."""
    book = str(body.get("book") or "")
    try:
        ch, v = int(body.get("chapter")), int(body.get("verse"))
    except (TypeError, ValueError):
        return None
    verses = bt.chapter(book, ch, tr) if book in bt.NAME else None
    if not verses or not any(n == v for n, _ in verses):
        return None
    out: Dict[str, Any] = {"book": book, "chapter": ch, "verse": v}
    if "colour" in body:
        c = body.get("colour") or None
        if c is not None and c not in COLOURS:
            return None
        out["colour"] = c
    if "note" in body:
        note = str(body.get("note") or "").strip()
        if len(note) > NOTE_MAX:
            return None
        out["note"] = note or None
    if "bookmark" in body:
        if not isinstance(body.get("bookmark"), bool):
            return None
        out["bookmarked"] = body["bookmark"]
    return out if len(out) > 3 else None


def save(business_id: str, contact_id: str, change: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Apply one checked change to the member's mark on a verse. Returns
    {"mark": row or None}, or None when it didn't save."""
    key = (f"/bible_marks?{_who(business_id, contact_id)}&book=eq.{_q(change['book'])}"
           f"&chapter=eq.{change['chapter']}&verse=eq.{change['verse']}")
    now = sb_clients.sb_get_as_service(f"{key}&select={_FIELDS}")
    if not isinstance(now, list):
        return None
    row = {"colour": None, "note": None, "bookmarked": False, **(now[0] if now else {}), **change}
    if not row.get("colour") and not row.get("note") and not row.get("bookmarked"):
        if now and not sb_clients.sb_delete_as_service(key):
            return None
        return {"mark": None}
    saved = sb_clients.sb_post_as_service(
        "/bible_marks?on_conflict=business_id,contact_id,book,chapter,verse",
        {"business_id": business_id, "contact_id": contact_id, "book": change["book"], "chapter": change["chapter"],
         "verse": change["verse"], "colour": row.get("colour"), "note": row.get("note"),
         "bookmarked": bool(row.get("bookmarked")), "updated_at": datetime.now(timezone.utc).isoformat()},
        prefer="return=representation,resolution=merge-duplicates")
    if not isinstance(saved, list) or not saved:
        return None
    r = saved[0]
    return {"mark": {k: r.get(k) for k in ("book", "chapter", "verse", "colour", "note", "bookmarked")}}


@router.post("/my/bible/mark", include_in_schema=False)
async def mark(request: Request):
    """A highlight, a note or a bookmark on one verse, for the signed-in
    member themselves. JSON in, JSON out (the reader's script)."""
    import asyncio
    import member_portal as mp
    import member_portal_church as mpc
    if not mp._same_origin(request):
        return JSONResponse({"ok": False, "error": "origin"}, status_code=403, headers=mp._SECURE_HEADERS)
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable == "preview":
        return JSONResponse({"ok": False, "error": "preview"}, status_code=403, headers=mp._SECURE_HEADERS)
    if unavailable:
        return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503, headers=mp._SECURE_HEADERS)
    if not me:
        return JSONResponse({"ok": False, "error": "signin"}, status_code=401, headers=mp._SECURE_HEADERS)
    # Its own budget: highlighting through a chapter is many taps, and
    # member_action (30 an hour) is for RSVPs, prayers and details.
    import rate_limit
    if not rate_limit.allow("bible_mark", f"{church['business']['id']}|{me['id']}"):
        return JSONResponse({"ok": False, "error": "slow"}, status_code=429, headers=mp._SECURE_HEADERS)
    try:
        body = await request.json()
    except Exception:
        body = None
    change = clean(body, bt.translation(str((body or {}).get("t") or ""))) if isinstance(body, dict) else None
    if not change:
        return JSONResponse({"ok": False, "error": "bad"}, status_code=400, headers=mp._SECURE_HEADERS)
    out = await asyncio.to_thread(save, church["business"]["id"], str(me["id"]), change)
    if out is None:
        return JSONResponse({"ok": False, "error": "error"}, status_code=503, headers=mp._SECURE_HEADERS)
    return JSONResponse({"ok": True, **out}, headers=mp._SECURE_HEADERS)
