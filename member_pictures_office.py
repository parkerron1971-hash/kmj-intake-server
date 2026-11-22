"""
member_pictures_office.py — the app's pictures, from the office.

Kevin approved the Member page mock, 2026-11-22 ("this is a good build"):
Settings → Member page gets a Pictures section, every picture spot in the
member app in one grid, changed from the office as well as from the app's
own edit mode. It is the same store (settings.member_portal.pictures, keyed
by spot, looks colour / bw / church) and the same checks: everything here
saves through member_app_pictures.put, so a change in either place shows in
both, and an upload is made safe, checked and kept exactly as the app's is.

    GET  /member-portal/{biz}/pictures          every spot with what it shows
                                                now, its look and where the
                                                picture came from; the photos
                                                to pick from (the church's own,
                                                and its messages' video stills);
                                                the pictures that pick
                                                themselves (the latest message,
                                                each series' art)
    POST /member-portal/{biz}/pictures          save one spot (multipart: key,
                                                look, pick = a photo's address |
                                                "yt:<video id>" | "default",
                                                optional photo, label)
    POST /member-portal/{biz}/pictures/remove   {key, look?}: the spot shows no
                                                photo (its default picture)

Who may: the same people as in the app (member_app_pictures.may_edit): the
church's owner, and the people the owner named (photo_editors), here when
they hold an office login on the church whose email is the one on their
record. Everyone else: 403. Every read and write is the service role.

A message's video still (pick "yt:<id>", one of the church's own published
messages) is fetched on the server (member_yt_pictures.get, the wide one),
then made safe and kept like an upload. It isn't sent to the picture check:
the app already shows these stills, unchecked, as the message's art.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("member_pictures_office")
router = APIRouter(tags=["member-portal"])

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
VID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
STILLS_MAX = 12
SERIES_MAX = 24
# An occasion's "who can see it" is worked out per person; the office lists
# the spots of everything the whole church can see.
NOBODY = {"id": "00000000-0000-0000-0000-000000000000", "name": ""}
# The ERRORS key put() returns, as the answer's status.
STATUS = {"slow": 429, "busy": 503, "error": 503}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


# ─── who may ─────────────────────────────────────────────────────────


def _who(business_id: str, user: AuthedUser) -> Tuple[Dict[str, Any], str]:
    """(the church, who is changing pictures: "owner:<id>" | "member:<contact
    id>"), or an HTTPException."""
    import member_app_pictures as mapic
    import member_portal as mp
    if not UUID_RE.fullmatch(str(business_id or "").lower()):
        raise HTTPException(404, "business not found")
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(business_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "Pictures couldn't load just now. Please try again.")
    if not rows:
        raise HTTPException(404, "business not found")
    biz = rows[0]
    if not mp.portal_eligible(biz):
        raise HTTPException(404, "Not Found")
    if str(biz.get("owner_id")) == str(user.id):
        return biz, f"owner:{user.id}"
    # Anyone else needs a login on this church first (the same 404 a stranger gets) ...
    import business_access
    business_access.assert_access(business_id, user, "member")
    # ... and to be one of the people the owner named, by the email on their record.
    email = str(user.email or "").strip().lower()
    ids = mapic.editors(biz)
    if email and ids:
        people = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(i) for i in ids)})&select=id,email")
        for p in people if isinstance(people, list) else []:
            if str(p.get("email") or "").strip().lower() == email:
                return biz, f"member:{p['id']}"
    raise HTTPException(403, "Only the owner and the people named to change pictures can change the app's pictures.")


def _site(biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from business_sites_helpers import get_business_site
    return get_business_site(_q(biz["id"]))


# ─── what's where ────────────────────────────────────────────────────


def _source(key: str, how: str, url: str, kind: str, website: set) -> str:
    if (how == "default" or not url) and key == "pastor":
        return "No picture chosen: their own profile photo, or their initials"
    if how == "default" or not url:
        return "No picture: initials show" if kind in ("groups", "youth") else "No picture: your colour shows"
    if how == "named":
        return "Your website photo, matched by its name"
    return "Your website photo" if url in website else "Your photo"


def stills(lib: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """The church's newest messages' video stills: {pick, url, title}."""
    import member_yt_pictures as myp
    from sermons_public import youtube_id
    out, seen = [], set()
    for s in (lib or {}).get("sermons") or []:
        vid = youtube_id(str(s.get("video_url") or ""))
        if not VID_RE.fullmatch(vid or "") or vid in seen:
            continue
        url = myp.picture_url(s.get("video_url"), wide=False)
        if url:
            seen.add(vid)
            out.append({"pick": f"yt:{vid}", "url": url, "title": str(s.get("title") or "")})
        if len(out) >= STILLS_MAX:
            break
    return out


def automatic(lib: Optional[Dict[str, Any]], site) -> List[Dict[str, str]]:
    """The pictures that pick themselves: the latest message's (its series'
    art, else its video still) and each series' art from the website."""
    import member_app_photos as photos
    import member_yt_pictures as myp
    if not lib:
        return []
    titles = {str(x.get("id")): str(x.get("title") or "") for x in lib.get("series") or []}
    out: List[Dict[str, str]] = []
    sermons = lib.get("sermons") or []
    if sermons:
        s = sermons[0]
        series = titles.get(str(s.get("series_id") or ""), "")
        art = photos.series_art(site, series) if series else ""
        still = "" if art else myp.picture_url(s.get("video_url"), wide=True)
        out.append({"key": "message", "label": "Latest message", "group": "Home",
                    "where": str(s.get("title") or "Your newest message"), "url": art or still,
                    "source": ("Its series artwork, automatic" if art else
                               "Its YouTube still, automatic" if still else "No picture: your colour shows")})
    used = {str(s.get("series_id")) for s in sermons if s.get("series_id")}
    for sid, title in titles.items():
        if sid not in used or not title:
            continue
        art = photos.series_art(site, title)
        out.append({"key": f"series:{sid}", "label": title, "group": "Series", "where": "Its messages on Watch",
                    "url": art, "source": "Series artwork from your website" if art else "No artwork yet: your colour shows"})
        if len(out) > SERIES_MAX:
            break
    return out


def listing(biz: Dict[str, Any], site, occasions, groups, devotionals, lib) -> Dict[str, Any]:
    import member_app_photos as photos
    import member_app_pictures as mapic
    pool = photos.photos(biz, site, limit=None)
    website = set(pool)
    spots = []
    for s in mapic.spots(biz, occasions, groups, devotionals):
        url, look, how = mapic.current(biz, site, pool, s)
        spots.append({"key": s["key"], "label": s["label"], "where": s["where"], "kind": s["kind"],
                      "group": s["group"], "url": url, "look": look or "colour", "how": how,
                      "source": _source(s["key"], how, url, s["kind"], website)})
    return {"ok": True, "spots": spots, "photos": mapic.library(biz, site)[:120],
            "stills": stills(lib), "automatic": automatic(lib, site),
            "looks": [{"key": "colour", "label": "Colour"}, {"key": "bw", "label": "Black & white"},
                      {"key": "church", "label": "Church colour"}]}


@router.get("/member-portal/{business_id}/pictures")
async def list_pictures(business_id: str, user: AuthedUser = Depends(require_user)):
    import devotionals as devs_mod
    import member_app_pictures as mapic
    import member_portal_church as mpc
    import member_portal_sermons as mps
    biz, _ = await asyncio.to_thread(_who, business_id, user)
    site = await asyncio.to_thread(_site, biz)
    occ, groups, devs, lib = await asyncio.gather(
        asyncio.to_thread(mpc.upcoming_for, biz["id"], NOBODY),
        asyncio.to_thread(mapic.church_groups, biz["id"]),
        asyncio.to_thread(devs_mod.catalog, biz["id"]),
        asyncio.to_thread(mps.load_library, biz["id"]))
    if groups is None:
        raise HTTPException(503, "Pictures couldn't load just now. Please try again.")
    return await asyncio.to_thread(listing, biz, site, occ, groups, devs, lib)


# ─── saving ──────────────────────────────────────────────────────────


def _answer(err: str) -> Dict[str, Any]:
    import member_app_pictures as mapic
    if err:
        raise HTTPException(STATUS.get(err, 400), mapic.ERRORS.get(err, mapic.ERRORS["error"]))
    return {"ok": True, "message": mapic.DONE["picture"]}


async def _still(business_id: str, vid: str) -> Optional[bytes]:
    """A message's video still, wide, when the video is one of the church's
    own published messages; None otherwise or when YouTube didn't answer."""
    import member_portal_sermons as mps
    import member_yt_pictures as myp
    from sermons_public import youtube_id
    lib = await asyncio.to_thread(mps.load_library, business_id)
    if not lib or not any(youtube_id(str(s.get("video_url") or "")) == vid for s in lib.get("sermons") or []):
        return None
    return await asyncio.to_thread(myp.get, vid, True) or None


@router.post("/member-portal/{business_id}/pictures")
async def save_picture(business_id: str, request: Request, user: AuthedUser = Depends(require_user)):
    import member_app_pictures as mapic
    biz, who = await asyncio.to_thread(_who, business_id, user)
    try:
        form = await request.form()
    except Exception:
        raise HTTPException(400, mapic.ERRORS["error"])
    key = str(form.get("key") or "")
    if not mapic.KEY_RE.fullmatch(key):
        raise HTTPException(400, mapic.ERRORS["error"])
    pick = str(form.get("pick") or "")
    upload = form.get("photo")
    raw, screen = b"", True
    if hasattr(upload, "read"):
        raw = await upload.read(mapic.MAX_BYTES + 1)
    if not raw and pick.startswith("yt:"):
        vid = pick[3:]
        got = await _still(biz["id"], vid) if VID_RE.fullmatch(vid) else None
        if not got:
            raise HTTPException(400, "That message's picture couldn't be read just now. Choose another.")
        raw, screen = got, False
    site = await asyncio.to_thread(_site, biz)
    err = await mapic.put(biz, site, key, str(form.get("look") or "colour"), pick, raw, who=who,
                          label=str(form.get("label") or "")[:120], screen=screen)
    return _answer(err)


@router.post("/member-portal/{business_id}/pictures/remove")
async def remove_picture(business_id: str, body: Dict[str, Any], user: AuthedUser = Depends(require_user)):
    import member_app_pictures as mapic
    biz, who = await asyncio.to_thread(_who, business_id, user)
    key = str((body or {}).get("key") or "")
    if not mapic.KEY_RE.fullmatch(key):
        raise HTTPException(400, mapic.ERRORS["error"])
    err = await mapic.put(biz, None, key, str((body or {}).get("look") or "colour"), "default", b"", who=who)
    return _answer(err)
