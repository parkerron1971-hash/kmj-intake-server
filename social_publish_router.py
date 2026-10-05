"""social_publish_router.py — part 2 of practitioner posting: send a post
to the business's connected social accounts through Post for Me.

  POST /social/media-slot?business_id                 manager+  where to upload one photo or video
  POST /social/publish?business_id                    manager+  post now or schedule
  GET  /social/publications?business_id               viewer+   recent posts + how each went
  POST /social/publications/{id}/cancel?business_id   manager+  a scheduled post, before it goes

THE CLICK IS THE APPROVAL. A person with manager rights or above pressed
Post or Schedule on exactly this caption, these photos and these
accounts. What they approved is fingerprinted (approved_hash) and kept
with who approved it. Nothing here posts on its own; Chief and the weekly
plan will come through the same door with their own approval step.

Each post is checked before it leaves: every target is one of THIS
business's connected accounts; Instagram needs a photo or video; TikTok
and YouTube need a video; captions fit each network (X: 280); a schedule
is in the future and within 90 days; and a day holds at most
POSTS_PER_DAY_CAP posts, so a loop can't flood someone's feed.

How it went comes back per account from Post for Me. GET refreshes the
posts still in flight when it is read (part 3's webhook will push the
same thing); a result carries the live post's link or the network's
error.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import post_for_me
import sb_clients
from auth_supabase import UserSession
from business_access import business_access

logger = logging.getLogger("social_publish")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] social_publish: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

router = APIRouter(tags=["social-publish"])

POSTS_PER_DAY_CAP = 25
CAPTION_LIMITS = {"x": 280, "instagram": 2200, "facebook": 63206, "tiktok": 2200,
                  "youtube": 5000, "linkedin": 3000, "pinterest": 500, "threads": 500}
NEEDS_MEDIA = {"instagram"}
NEEDS_VIDEO = {"tiktok", "youtube"}
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm")
_IN_FLIGHT = ("posting", "scheduled")
_SELECT = ("id,caption,media,targets,status,scheduled_at,results,created_at,"
           "provider_post_id,approved_by")


class MediaItem(BaseModel):
    url: str = Field(..., max_length=2048)
    # 'video' or 'image'. Said by the client from the file it picked,
    # because a Post for Me media link need not end in an extension.
    kind: Literal["image", "video"] = "image"


class PublishBody(BaseModel):
    caption: str = Field("", max_length=63206)
    connection_ids: List[str] = Field(..., min_length=1, max_length=10)
    media: List[MediaItem] = Field(default_factory=list, max_length=10)
    scheduled_at: Optional[str] = None      # ISO 8601; None = now


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_video(url: str) -> bool:
    return urlparse(url).path.lower().endswith(VIDEO_EXT)


def _require_pilot(business_id: str) -> None:
    if not post_for_me.configured():
        raise HTTPException(503, "Posting isn't set up on the server yet.")
    if not post_for_me.allowed_for(business_id):
        raise HTTPException(403, "Posting to your social accounts isn't switched on for this business yet.")


def _targets(business_id: str, connection_ids: List[str]) -> List[Dict[str, Any]]:
    """The chosen connections, each one this business's and connected."""
    ids = sorted(set(connection_ids))
    rows = sb_clients.sb_get_as_service(
        f"/social_connections?business_id=eq.{business_id}&status=eq.connected"
        f"&id=in.({','.join(quote(i) for i in ids)})"
        f"&select=id,platform,username,provider_account_id") or []
    if len(rows) != len(ids):
        raise HTTPException(400, "One of those accounts isn't connected to this business.")
    return [{"connection_id": r["id"], "platform": r["platform"], "username": r.get("username"),
             "provider_account_id": r["provider_account_id"]} for r in rows]


def _check(caption: str, media: List[Dict[str, str]], targets: List[Dict[str, Any]]) -> None:
    if not caption and not media:
        raise HTTPException(400, "Write something or add a photo first.")
    for m in media:
        p = urlparse(m["url"])
        if p.scheme != "https" or not p.netloc:
            raise HTTPException(400, "Photos and videos need to be web links that start with https.")
    has_video = any(m["kind"] == "video" or _is_video(m["url"]) for m in media)
    for t in targets:
        name = post_for_me_label(t["platform"])
        limit = CAPTION_LIMITS.get(t["platform"])
        if limit and len(caption) > limit:
            raise HTTPException(400, f"{name} allows {limit} characters; this caption has {len(caption)}.")
        if t["platform"] in NEEDS_MEDIA and not media:
            raise HTTPException(400, f"{name} needs a photo or video.")
        if t["platform"] in NEEDS_VIDEO and not has_video:
            raise HTTPException(400, f"{name} needs a video.")


def post_for_me_label(platform: str) -> str:
    return {"x": "X", "tiktok": "TikTok", "youtube": "YouTube", "linkedin": "LinkedIn"}.get(
        platform, platform.capitalize())


def _schedule(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "That date and time didn't read right.")
    if when.tzinfo is None:
        raise HTTPException(400, "The time needs a time zone.")
    when = when.astimezone(timezone.utc)
    if when < _now() + timedelta(seconds=60):
        raise HTTPException(400, "Pick a time at least a minute from now.")
    if when > _now() + timedelta(days=90):
        raise HTTPException(400, "Posts can be scheduled up to 90 days ahead.")
    return when.isoformat()


def _fingerprint(caption: str, media: List[Dict[str, str]], targets: List[Dict[str, Any]],
                 scheduled_at: Optional[str]) -> str:
    """What the person approved: the words, the photos, the accounts, the time."""
    blob = json.dumps({"caption": caption, "media": media, "scheduled_at": scheduled_at,
                       "accounts": sorted(t["provider_account_id"] for t in targets)},
                      sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _public(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": row["id"], "caption": row.get("caption"), "media": row.get("media") or [],
            "targets": [{"platform": t.get("platform"), "username": t.get("username")}
                        for t in (row.get("targets") or [])],
            "status": row.get("status"), "scheduled_at": row.get("scheduled_at"),
            "results": row.get("results") or [], "created_at": row.get("created_at")}


# ─── Upload ──────────────────────────────────────────────────────────

@router.post("/social/media-slot")
async def media_slot(business_id: str, biz: dict = Depends(business_access("manager"))):
    """Where the browser uploads one photo or video (straight to Post for
    Me). Hands out a short-lived signed upload link, never our key."""
    _require_pilot(business_id)
    try:
        return {"ok": True, **(await post_for_me.upload_slot())}
    except post_for_me.PostForMeError:
        raise HTTPException(502, "Couldn't get an upload spot. Try again in a minute.")


# ─── Post ────────────────────────────────────────────────────────────

@router.post("/social/publish")
async def publish(business_id: str, body: PublishBody,
                  biz: dict = Depends(business_access("manager")),
                  session: UserSession = Depends(sb_clients.authed_request)):
    _require_pilot(business_id)
    caption = (body.caption or "").strip()
    media = [{"url": m.url.strip(), "kind": m.kind} for m in body.media if m.url and m.url.strip()]
    targets = _targets(business_id, body.connection_ids)
    _check(caption, media, targets)
    scheduled_at = _schedule(body.scheduled_at)

    since = (_now() - timedelta(days=1)).isoformat().replace("+", "%2B")
    today = sb_clients.sb_get_as_service(
        f"/social_publications?business_id=eq.{business_id}&created_at=gte.{since}"
        f"&status=neq.failed&select=id&limit={POSTS_PER_DAY_CAP + 1}") or []
    if len(today) >= POSTS_PER_DAY_CAP:
        raise HTTPException(429, f"That's {POSTS_PER_DAY_CAP} posts in a day. Try again tomorrow.")

    created = sb_clients.sb_post_as_service("/social_publications", {
        "business_id": business_id, "caption": caption, "media": media,
        "targets": targets, "status": "scheduled" if scheduled_at else "posting",
        "scheduled_at": scheduled_at, "approved_by": str(session.user.id),
        "approved_hash": _fingerprint(caption, media, targets, scheduled_at),
    })
    row = (created or [None])[0] if isinstance(created, list) else created
    if not row or not row.get("id"):
        raise HTTPException(500, "Couldn't save the post. Nothing was sent.")
    try:
        sent = await post_for_me.create_post(
            caption=caption, account_ids=[t["provider_account_id"] for t in targets],
            media_urls=[m["url"] for m in media], external_id=row["id"], scheduled_at=scheduled_at)
    except post_for_me.PostForMeError:
        sb_clients.sb_patch_as_service(f"/social_publications?id=eq.{row['id']}", {
            "status": "failed", "updated_at": _now().isoformat(),
            "results": [{"platform": None, "success": False,
                         "error": "The posting service didn't accept it."}]})
        raise HTTPException(502, "The posting service didn't accept the post. Nothing went out; try again in a minute.")
    sb_clients.sb_patch_as_service(f"/social_publications?id=eq.{row['id']}", {
        "provider_post_id": sent["id"], "updated_at": _now().isoformat()})
    row["provider_post_id"] = sent["id"]
    logger.info("[social] %s %s to %d account(s)", business_id[:8],
                "scheduled" if scheduled_at else "posting", len(targets))
    return {"ok": True, "publication": _public(row)}


# ─── How it went ─────────────────────────────────────────────────────

def _settle(row: Dict[str, Any], results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-account outcome, labelled with the account, and the overall status."""
    by_acct = {t["provider_account_id"]: t for t in (row.get("targets") or [])}
    labelled = []
    for r in results:
        t = by_acct.get(r.get("social_account_id")) or {}
        labelled.append({"platform": t.get("platform"), "username": t.get("username"),
                         "success": r["success"], "url": r.get("url"), "error": r.get("error")})
    if len(results) < len(by_acct):
        status = row.get("status") if row.get("status") in _IN_FLIGHT else "posting"
    elif all(r["success"] for r in labelled):
        status = "posted"
    elif any(r["success"] for r in labelled):
        status = "partly_posted"
    else:
        status = "failed"
    return {"status": status, "results": labelled}


async def _refresh(row: Dict[str, Any]) -> Dict[str, Any]:
    due = row.get("scheduled_at")
    if due and datetime.fromisoformat(str(due).replace("Z", "+00:00")) > _now():
        return row
    try:
        results = await post_for_me.post_results(row["provider_post_id"])
    except post_for_me.PostForMeError:
        return row
    settled = _settle(row, results)
    if settled["status"] != row.get("status") or settled["results"] != (row.get("results") or []):
        sb_clients.sb_patch_as_service(f"/social_publications?id=eq.{row['id']}",
                                       {**settled, "updated_at": _now().isoformat()})
        row = {**row, **settled}
    return row


@router.get("/social/publications")
async def list_publications(business_id: str, biz: dict = Depends(business_access("viewer"))):
    rows = sb_clients.sb_get_as_service(
        f"/social_publications?business_id=eq.{business_id}&order=created_at.desc"
        f"&limit=20&select={_SELECT}") or []
    out = []
    refreshed = 0
    for r in rows:
        if r.get("status") in _IN_FLIGHT and r.get("provider_post_id") and refreshed < 5:
            r = await _refresh(r)
            refreshed += 1
        out.append(_public(r))
    return {"ok": True, "publications": out}


@router.post("/social/publications/{publication_id}/cancel")
async def cancel_publication(business_id: str, publication_id: str,
                             biz: dict = Depends(business_access("manager"))):
    rows = sb_clients.sb_get_as_service(
        f"/social_publications?id=eq.{quote(publication_id)}&business_id=eq.{business_id}"
        f"&select={_SELECT}&limit=1") or []
    if not rows:
        raise HTTPException(404, "That post isn't on this business.")
    row = rows[0]
    due = row.get("scheduled_at")
    if row.get("status") != "scheduled" or not due \
            or datetime.fromisoformat(str(due).replace("Z", "+00:00")) <= _now():
        raise HTTPException(409, "Only a scheduled post that hasn't gone out can be cancelled.")
    if row.get("provider_post_id"):
        try:
            await post_for_me.cancel_post(row["provider_post_id"])
        except post_for_me.PostForMeError as e:
            if e.status != 404:
                raise HTTPException(502, "Couldn't reach the posting service. Try again in a minute.")
    sb_clients.sb_patch_as_service(f"/social_publications?id=eq.{row['id']}",
                                   {"status": "cancelled", "updated_at": _now().isoformat()})
    return {"ok": True, "publication": _public({**row, "status": "cancelled"})}
