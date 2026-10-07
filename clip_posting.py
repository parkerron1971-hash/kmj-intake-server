"""Post an approved clip, with its cover, to the business's connected accounts.

  POST /media-library/{business_id}/clips/{asset_id}/post   owner only

Grow → Video Clips: once a clip passes "Ready to post?" (media_library.approve),
its owner can post it now or at a time to the accounts connected in Build →
Social Media. It goes through the same door as every other post
(social_publish_router.send_post): the same record, daily cap, hand-off,
results and cancel, so it shows in Social Media's recent posts like any other.

THE CLIP. Only a clip approved as it is now (its review fingerprint,
media_library.fingerprint, still matches the approval) and the one the owner is
looking at (the app sends the fingerprint it showed). Anything else is a 409 in
plain words, before anything is signed or sent. The posting service fetches
the video by a signed link to the private file: an hour for a post going now;
for a scheduled post, until an hour past its time, because the file is fetched
when the post goes out. The link is handed over, never stored.

THE COVER. A cover goes with the video as its thumbnail. Covers are Image Studio
designs that name this clip (director.clip_id); only a READY cover of THIS
business that names THIS clip in the shape asked for is ever used, so an image
id from anywhere else is refused, never fetched. The clip is vertical (9:16),
so the story cover is its thumbnail wherever it plays as a vertical video:
Instagram and Facebook Reels, TikTok, YouTube Shorts, X, Threads, Pinterest.
The widescreen cover goes where a network frames a video in a 16:9 card
(LinkedIn, not switched on today), falling back to the story cover; a network
with neither posts with no thumbnail. The cover goes as a JPEG at the public
path Image Studio publishes an artwork to (a Reel cover must be a JPEG).

OWNER ONLY. Posting puts the business's name on public feeds, and covers are
the owner's (they spend credits). Auth + an owner check (service-role read of
businesses.owner_id), like every write that must not slide to members.

IDEMPOTENT. The app sends a request_id per Post tap; the post's id is derived
from it, so a retried tap returns the first post instead of a second. The same
clip, caption, covers, accounts and time again within a day is returned as
already sent (`already: true`), not posted twice.

TWO CALLERS, ONE POST. post_clip_for is the post itself; the endpoint below and
Chief's post_clip (chief_clip_actions.py) both call it, so every check above
holds the same way for a tap and for "Chief, post that clip".
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID, uuid5

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import clip_covers
import image_studio as images
import media_library
import sb_clients
import social_publish_router as social
import storage_links
from auth_supabase import UserSession

router = APIRouter(prefix='/media-library', tags=['clip posting'])
log = logging.getLogger(__name__)

Shape = Literal['story', 'wide']

# The cover each network shows for a vertical clip, best first. Past the list:
# no thumbnail (the network picks a frame). Never a widescreen cover on a
# vertical player: it would be cropped to a sliver.
COVER_SHAPES: Dict[str, tuple] = {
    'instagram': ('story',),   # Reel cover, 9:16
    'facebook': ('story',),    # Reel
    'tiktok': ('story',),
    'youtube': ('story',),     # a Short: vertical and under three minutes
    'x': ('story',),
    'threads': ('story',),
    'pinterest': ('story',),
    'linkedin': ('wide', 'story'),
}
# Where the vertical clip goes on a network that has a choice.
PLACEMENT = {'instagram': {'placement': 'reels'}, 'facebook': {'placement': 'reels'}}
LINK_MARGIN = 3600          # seconds a video link outlives the moment it is fetched
DUPLICATE_WINDOW = timedelta(days=1)


class ClipPost(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # One per Post tap: a retried tap with the same id never posts twice.
    request_id: UUID
    # The clip's review fingerprint as the app showed it.
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    # The owner's words; left out, the clip's caption, else its title.
    caption: Optional[str] = Field(default=None, max_length=63206)
    connection_ids: List[str] = Field(..., min_length=1, max_length=10)
    # ISO 8601 with a time zone; left out = now.
    scheduled_at: Optional[str] = None
    # The covers the owner saw, by shape. {} posts with no cover; left out,
    # the newest ready cover of each shape.
    covers: Optional[Dict[Shape, UUID]] = None


def _require_owner(business_id: str, user) -> None:
    rows = sb_clients.sb_get_as_service(f'/businesses?id=eq.{business_id}&select=owner_id&limit=1') or []
    if not rows:
        raise HTTPException(404, 'Business not found.')
    if str(rows[0].get('owner_id')) != str(user.id):
        raise HTTPException(403, 'Only the business owner can post its clips.')


def _clip(business_id: str, asset_id: str) -> Dict[str, Any]:
    rows = media_library.read(f'/media_assets?id=eq.{asset_id}&business_id=eq.{business_id}&kind=eq.clip&select=*&limit=1')
    if not rows:
        raise HTTPException(404, 'That clip is not in this business.')
    row = rows[0]
    if row.get('status') != 'ready':
        raise HTTPException(409, 'This clip is still being made. Post it once it is ready.')
    if row.get('source_removed_at'):
        raise HTTPException(409, 'This clip is no longer stored, so it cannot be posted.')
    return row


def approval_problem(row: Dict[str, Any]) -> Optional[str]:
    """'unapproved', 'changed' (approved, then changed), or None when the clip
    is approved as it is now."""
    approval = row.get('approval') or {}
    if not approval:
        return 'unapproved'
    if approval.get('fingerprint') != media_library.fingerprint(row):
        return 'changed'
    return None


def check_approved(row: Dict[str, Any], shown: str) -> str:
    """The clip's fingerprint, once it is approved as it is now and is the one
    the owner is looking at. A 409 in plain words otherwise."""
    current = media_library.fingerprint(row)
    problem = approval_problem(row)
    if problem == 'unapproved':
        raise HTTPException(409, 'Approve this clip in Ready to post before posting it.')
    if problem == 'changed':
        raise HTTPException(409, 'This clip changed after it was approved. Check it and approve it again before posting.')
    if shown != current:
        raise HTTPException(409, 'This clip changed since you opened it. Open it again and check it before posting.')
    return current


def _shape_of(artwork: Dict[str, Any]) -> str:
    return clip_covers.SHAPE_OF.get(artwork.get('size'), 'story')


def ready_covers(business_id: str, asset_id: str, wanted: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The covers that go with this post, by shape: each a ready design of this
    business that names this clip, in its shape. `wanted` names them ({} for
    none); left out, the newest ready one of each shape."""
    if wanted is not None and not wanted:
        return {}
    select = 'id,status,size,storage_path,created_at,director->>clip_id'
    base = (f'/image_artworks?business_id=eq.{business_id}&director->>clip_id=eq.{asset_id}'
            f'&status=eq.ready&select={select}')
    if wanted is None:
        rows = sb_clients.sb_get_as_service(base + '&order=created_at.desc&limit=50')
        if rows is None:
            raise HTTPException(503, 'The covers could not be read. Nothing was posted. Try again in a minute.')
        found: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            shape = _shape_of(row)
            if shape in clip_covers.SHAPES and shape not in found:
                found[shape] = row
        return found
    ids = {str(v) for v in wanted.values()}
    rows = sb_clients.sb_get_as_service(base + f"&id=in.({','.join(sorted(ids))})&limit=10")
    if rows is None:
        raise HTTPException(503, 'The covers could not be read. Nothing was posted. Try again in a minute.')
    by_id = {str(r['id']): r for r in rows}
    found = {}
    for shape, image_id in wanted.items():
        row = by_id.get(str(image_id))
        # Not ready, another clip's, another business's, or the other shape:
        # one answer for all of them, and nothing is fetched.
        if not row or row.get('clip_id') != asset_id or _shape_of(row) != shape:
            raise HTTPException(409, 'That cover is not a finished cover of this clip. Refresh and try again, or post without it.')
        found[shape] = row
    return found


def cover_for(platform: str, covers: Dict[str, Any]) -> Optional[str]:
    """The cover shape a network gets, from the covers there are (or None)."""
    return next((s for s in COVER_SHAPES.get(platform, ('story',)) if s in covers), None)


def default_caption(row: Dict[str, Any]) -> str:
    return ((row.get('configuration') or {}).get('caption') or '').strip() or (row.get('name') or '').strip()


def youtube_title(row: Dict[str, Any]) -> str:
    title = ' '.join((row.get('name') or 'Clip').replace('<', '').replace('>', '').split())
    return title[:100] or 'Clip'


def link_ttl(scheduled_at: Optional[str]) -> int:
    """How long the posting service can fetch the video: an hour now, or an
    hour past the scheduled time."""
    if not scheduled_at:
        return LINK_MARGIN
    due = datetime.fromisoformat(scheduled_at)
    return max(LINK_MARGIN, int((due - social._now()).total_seconds()) + LINK_MARGIN)


def approved_hash(asset_id: str, clip_fingerprint: str, caption: str, chosen: Dict[str, Optional[str]],
                  targets: List[Dict[str, Any]], scheduled_at: Optional[str]) -> str:
    """What the owner approved: this clip as approved, the words, the cover on
    each network, the accounts and the time. Never the video link, which
    changes every time it is signed."""
    blob = json.dumps({'clip': asset_id, 'clip_fingerprint': clip_fingerprint, 'caption': caption,
                       'covers': chosen, 'scheduled_at': scheduled_at,
                       'accounts': sorted(t['provider_account_id'] for t in targets)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def recent_duplicate(business_id: str, digest: str) -> Optional[Dict[str, Any]]:
    since = (social._now() - DUPLICATE_WINDOW).isoformat().replace('+', '%2B')
    rows = sb_clients.sb_get_as_service(
        f'/social_publications?business_id=eq.{business_id}&approved_hash=eq.{digest}'
        f'&created_at=gte.{since}&status=not.in.(failed,cancelled)'
        f'&select={social._SELECT}&order=created_at.desc&limit=1')
    if rows is None:
        # A failed read is not "no earlier post": a second tap would post twice.
        raise HTTPException(503, "Couldn't check for an earlier post. Nothing was posted. Try again in a minute.")
    return rows[0] if rows else None


@router.post('/{business_id}/clips/{asset_id}/post')
async def post_clip(business_id: UUID, asset_id: UUID, body: ClipPost,
                    session: UserSession = Depends(sb_clients.authed_request)):
    return await post_clip_for(
        str(business_id), str(session.user.id), str(asset_id), request_id=body.request_id,
        fingerprint=body.fingerprint, caption=body.caption, connection_ids=body.connection_ids,
        scheduled_at=body.scheduled_at, covers=body.covers)


async def post_clip_for(business_id: str, user_id: str, clip_id: str, *,
                        request_id: Union[UUID, str], fingerprint: str, caption: Optional[str],
                        connection_ids: List[str], scheduled_at: Optional[str],
                        covers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Post one approved clip for the person `user_id`, who must own the
    business. The endpoint above and Chief's post_clip both come here.
    Raises HTTPException in plain words; nothing is signed or sent until every
    check has passed. `fingerprint` is the clip as the caller showed it;
    `covers` None = the newest ready cover of each shape, {} = none."""
    biz = business_id
    user = SimpleNamespace(id=str(user_id))
    # Every database read runs in a thread: never on the event loop.
    await asyncio.to_thread(_require_owner, biz, user)
    await asyncio.to_thread(social._require_pilot, biz)
    try:
        clip_id = str(UUID(str(clip_id)))
    except ValueError:
        raise HTTPException(404, 'That clip is not in this business.')
    row = await asyncio.to_thread(_clip, biz, clip_id)
    fingerprint = check_approved(row, fingerprint)
    targets = await asyncio.to_thread(social._targets, biz, connection_ids)
    scheduled_at = social._schedule(scheduled_at)
    caption = (caption if caption is not None else default_caption(row)).strip()
    covers = await asyncio.to_thread(ready_covers, biz, clip_id, covers)
    platforms = list(dict.fromkeys(t['platform'] for t in targets))
    shape_for = {p: cover_for(p, covers) for p in platforms}
    chosen = {p: (str(covers[s]['id']) if s else None) for p, s in shape_for.items()}
    used = {p: ({'shape': s, 'image_id': chosen[p]} if s else None) for p, s in shape_for.items()}
    digest = approved_hash(clip_id, fingerprint, caption, chosen, targets, scheduled_at)
    publication_id = str(uuid5(UUID(clip_id), f'post:{request_id}'))

    # Already sent: this tap again, or the same post a moment ago.
    again = await asyncio.to_thread(social._publication, biz, publication_id)
    if again:
        if again.get('status') == 'failed':
            # The same tap, whose hand-off was refused: the same answer. The app
            # makes a new request_id for the next try.
            raise HTTPException(502, social.REFUSED)
        return {'ok': True, 'already': True, 'publication': social._public(again), 'covers': used}
    twin = await asyncio.to_thread(recent_duplicate, biz, digest)
    if twin:
        return {'ok': True, 'already': True, 'publication': social._public(twin), 'covers': used}

    video = await asyncio.to_thread(storage_links.signed_url_sync, media_library.BUCKET,
                                    media_library.object_path(row), ttl=link_ttl(scheduled_at))
    if not video:
        raise HTTPException(503, 'The clip could not be prepared for posting. Nothing was posted. Try again in a minute.')
    social._check(caption, [{'url': video, 'kind': 'video'}], targets)

    # Each cover in use, as the JPEG the networks take.
    thumbs: Dict[str, str] = {}
    shapes_used = sorted({s for s in shape_for.values() if s})
    if shapes_used:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                for shape in shapes_used:
                    thumbs[shape] = await images.delivery_jpeg(client, biz, covers[shape])
        except (HTTPException, httpx.HTTPError, OSError, ValueError) as error:
            log.warning('Clip cover not prepared for %s: %s', clip_id, getattr(error, 'detail', type(error).__name__))
            raise HTTPException(502, 'The cover could not be prepared. Nothing was posted. Try again, or post without the cover.')

    def item(shape: Optional[str]) -> Dict[str, Any]:
        return {'url': video, 'thumbnail_url': thumbs[shape]} if shape else {'url': video}

    configurations = {}
    for platform in platforms:
        conf: Dict[str, Any] = {'media': [item(shape_for[platform])], **PLACEMENT.get(platform, {})}
        if platform == 'youtube':
            conf['title'] = youtube_title(row)
        configurations[platform] = conf
    top = 'story' if 'story' in shapes_used else (shapes_used[0] if shapes_used else None)
    kept = [{'kind': 'video', 'clip_id': clip_id, 'name': row.get('name') or '',
             'thumbnail_url': thumbs.get(top) if top else None,
             'covers': {p: c for p, c in chosen.items() if c}}]

    publication, sent_now = await social.send_post(
        biz, user.id, caption=caption, media=kept, targets=targets,
        scheduled_at=scheduled_at, approved_hash=digest, provider_media=[item(top)],
        platform_configurations=configurations, publication_id=publication_id)
    if sent_now:
        media_library.audit(biz, user, 'post', clip_id)
    return {'ok': True, 'already': not sent_now, 'publication': social._public(publication), 'covers': used}
