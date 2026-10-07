"""Post a finished design (or just words) to the business's connected accounts.

Chief's post_image (chief_social_actions.py) comes here: "post the flyer to
Instagram and Facebook", "schedule that design for Thursday at 9". It goes
through the same door as every other post (social_publish_router.send_post):
the same record, daily cap, hand-off, results and cancel, so it shows in
Build, Social Media's recent posts like any other.

THE PICTURE. Only a READY Image Studio artwork of THIS business (an
image_artworks row read with the service role, filtered by business) is ever
used, so an image id from anywhere else is refused, never fetched. It goes as
a JPEG at the public path Image Studio publishes an artwork to
(image_studio.delivery_jpeg): Instagram takes JPEG, and the same artwork
always lands at the same path, so a retry replaces its copy. The JPEG is made
only after every check below has passed.

THE BUILD ACTOR. delivery_jpeg reads the private original and writes the
public copy through image_studio's storage headers, which want the signed-in
person's JWT. On a run with no JWT (a worker, the weekly desk) they would
401, so the call is made with image_studio.build_actor bound to
{business_id, user_id} for that one call and reset after, whatever happens:
storage_headers then refuses any path outside this business's folder, and the
binding never outlives the call or leaks to another business.

WORDS ONLY. With no picture the post is text: Instagram needs a picture and
TikTok and YouTube take only videos, so those accounts are left out and the
answer says so (`dropped`); if nothing is left, nothing is posted. A picture
is never sent to TikTok or YouTube for the same reason.

OWNER ONLY. Posting puts the business's name on public feeds. An owner check
(service-role read of businesses.owner_id), like every write that must not
slide to members, then the posting pilot gate.

NEVER TWICE. The post's id is a uuid5 of the caller's request id, so a
retried request returns the first post instead of a second. The same picture,
words, accounts and time again within a day is returned as already sent
(`already: true`). A failed read is never "no earlier post": it refuses.

Every database call runs in a thread. Every refusal is an HTTPException in
plain words that says nothing was posted.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from fastapi import HTTPException

import image_studio as images
import sb_clients
import social_publish_router as social

log = logging.getLogger(__name__)

FLYER_PREFIX = 'EDITABLE_FLYER_V1\n'
OWNER_BRIEF = 'OWNER BRIEF:\n'
# What a design row is read with. director->>goal comes back as `goal`,
# director->>clip_id as `clip_id` (a clip cover).
COLUMNS = ('id,business_id,status,size,storage_path,prompt,model,created_at,'
           'director->>goal,director->>clip_id')
# _check only needs to know a picture goes with the post; its real link is
# made after every check has passed, then checked again.
_PICTURE_TO_COME = {'url': 'https://picture.pending/design.jpg', 'kind': 'image'}


def _require_owner(business_id: str, user_id: str) -> None:
    rows = sb_clients.sb_get_as_service(f'/businesses?id=eq.{business_id}&select=owner_id&limit=1')
    if rows is None:
        raise HTTPException(503, "Couldn't confirm this business just now. Nothing was posted. Try again in a minute.")
    if not rows:
        raise HTTPException(404, 'Business not found. Nothing was posted.')
    if str(rows[0].get('owner_id')) != str(user_id):
        raise HTTPException(403, 'Only the business owner can post for it. Nothing was posted.')


def ready_artwork(business_id: str, image_id: Any) -> Dict[str, Any]:
    """The design asked for: a ready artwork of THIS business with a stored
    picture. Another business's id gets the same answer as a missing one."""
    try:
        image_id = str(UUID(str(image_id)))
    except ValueError:
        raise HTTPException(404, "That design isn't in this business's Media Library. Nothing was posted.")
    rows = sb_clients.sb_get_as_service(
        f'/image_artworks?id=eq.{image_id}&business_id=eq.{business_id}&select={COLUMNS}&limit=1')
    if rows is None:
        raise HTTPException(503, "Couldn't read that design just now. Nothing was posted. Try again in a minute.")
    if not rows or str(rows[0].get('business_id')) != str(business_id):
        raise HTTPException(404, "That design isn't in this business's Media Library. Nothing was posted.")
    row = rows[0]
    status = row.get('status')
    if status in ('queued', 'working'):
        raise HTTPException(409, 'That design is still being made. Post it once it is ready. Nothing was posted.')
    if status != 'ready' or not row.get('storage_path'):
        raise HTTPException(409, "That design didn't finish, so it can't be posted. Nothing was posted.")
    return row


def design_title(row: Dict[str, Any]) -> str:
    """The name the owner knows a design by, as Image Studio shows it
    (image_studio.present): the Creative Director's goal, the flyer's title,
    the owner's brief, else the first line of its prompt."""
    prompt = str(row.get('prompt') or '')
    title: Any = row.get('goal') or ''
    if not title and prompt.startswith(FLYER_PREFIX):
        try:
            title = json.loads(prompt.split('\n', 1)[1]).get('title') or ''
        except (ValueError, TypeError, AttributeError):
            title = ''
    if not title and OWNER_BRIEF in prompt:
        title = prompt.split(OWNER_BRIEF, 1)[1].split('\nCOMPOSITION DIRECTION:', 1)[0]
    if not title and not prompt.startswith(FLYER_PREFIX):
        title = prompt.split('\n', 1)[0]
    title = ' '.join(str(title).split())
    return title[:77] + '…' if len(title) > 80 else title


def is_design(row: Dict[str, Any]) -> bool:
    """Made in Image Studio (generated or composed), not an uploaded photo."""
    return bool(row.get('model')) or str(row.get('prompt') or '').startswith(FLYER_PREFIX)


def fit_targets(targets: List[Dict[str, Any]], has_picture: bool) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(kept, dropped): the accounts this post can go to, and those it can't,
    each dropped one with why ('needs_picture' or 'needs_video')."""
    kept, dropped = [], []
    for t in targets:
        if t['platform'] in social.NEEDS_VIDEO:
            dropped.append({'platform': t['platform'], 'username': t.get('username'), 'why': 'needs_video'})
        elif not has_picture and t['platform'] in social.NEEDS_MEDIA:
            dropped.append({'platform': t['platform'], 'username': t.get('username'), 'why': 'needs_picture'})
        else:
            kept.append(t)
    return kept, dropped


def said_and(items: List[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return ''.join(items)
    return ', '.join(items[:-1]) + ' and ' + items[-1]


def why_dropped(dropped: List[Dict[str, Any]]) -> List[str]:
    """'Instagram needs a picture', 'TikTok and YouTube take only videos'."""
    picture = list(dict.fromkeys(social.post_for_me_label(d['platform']) for d in dropped if d['why'] == 'needs_picture'))
    video = list(dict.fromkeys(social.post_for_me_label(d['platform']) for d in dropped if d['why'] == 'needs_video'))
    why = []
    if picture:
        why.append(f"{said_and(picture)} {'needs' if len(picture) == 1 else 'need'} a picture")
    if video:
        why.append(f"{said_and(video)} {'takes' if len(video) == 1 else 'take'} only videos")
    return why


def _nowhere(dropped: List[Dict[str, Any]]) -> str:
    why = why_dropped(dropped)
    return f"None of those accounts can take this post ({'; '.join(why)}). Nothing was posted."


def approved_hash(image_id: Optional[str], caption: str, targets: List[Dict[str, Any]],
                  scheduled_at: Optional[str]) -> str:
    """What the owner asked for: this picture (or none), the words, the
    accounts and the time. Never the picture's link."""
    blob = json.dumps({'image': image_id, 'caption': caption, 'scheduled_at': scheduled_at,
                       'accounts': sorted(t['provider_account_id'] for t in targets)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def publication_id_for(business_id: str, image_id: Optional[str], request_id: Union[UUID, str]) -> str:
    return str(uuid5(NAMESPACE_URL, f'post-image:{business_id}:{image_id or "words"}:{request_id}'))


def recent_duplicate(business_id: str, digest: str) -> Optional[Dict[str, Any]]:
    """The same post in the last day, if there is one."""
    import clip_posting
    since = (social._now() - clip_posting.DUPLICATE_WINDOW).isoformat().replace('+', '%2B')
    rows = sb_clients.sb_get_as_service(
        f'/social_publications?business_id=eq.{business_id}&approved_hash=eq.{digest}'
        f'&created_at=gte.{since}&status=not.in.(failed,cancelled)'
        f'&select={social._SELECT}&order=created_at.desc&limit=1')
    if rows is None:
        # A failed read is not "no earlier post": a second ask would post twice.
        raise HTTPException(503, "Couldn't check for an earlier post. Nothing was posted. Try again in a minute.")
    return rows[0] if rows else None


def _earlier(business_id: str, publication_id: str) -> Optional[Dict[str, Any]]:
    """The post this request already made, if any. Unlike
    social._publication, a failed read refuses instead of reading as none."""
    rows = sb_clients.sb_get_as_service(
        f'/social_publications?id=eq.{publication_id}&business_id=eq.{business_id}'
        f'&select={social._SELECT}&limit=1')
    if rows is None:
        raise HTTPException(503, "Couldn't check for an earlier post. Nothing was posted. Try again in a minute.")
    return rows[0] if rows else None


async def delivery_link(business_id: str, user_id: str, row: Dict[str, Any]) -> str:
    """The design as a public JPEG, made with the build actor bound to this
    business and person for this one call (see the module docstring)."""
    token = images.build_actor.set({'business_id': str(business_id), 'user_id': str(user_id)})
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            return await images.delivery_jpeg(client, str(business_id), row)
    except (HTTPException, httpx.HTTPError, OSError, ValueError) as error:
        log.warning('Design not prepared for posting %s: %s', row.get('id'),
                    getattr(error, 'detail', type(error).__name__))
        raise HTTPException(502, 'The design could not be prepared for posting. Nothing was posted. Try again in a minute.')
    finally:
        images.build_actor.reset(token)


def _image_out(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {'id': str(row['id']), 'title': design_title(row), 'design': is_design(row)}


async def post_image_for(business_id: str, user_id: str, image_id: Optional[str], *,
                         request_id: Union[UUID, str], caption: Optional[str],
                         connection_ids: List[str], scheduled_at: Optional[str]) -> Dict[str, Any]:
    """Post one ready design (or, with image_id None, just words) for the
    person `user_id`, who must own the business, to the connected accounts
    named, now or at `scheduled_at` (ISO with a zone). Raises HTTPException in
    plain words; nothing is prepared or sent until every check has passed.
    Returns {ok, already, publication, image, dropped}."""
    biz = str(business_id)
    user_id = str(user_id)
    await asyncio.to_thread(_require_owner, biz, user_id)
    await asyncio.to_thread(social._require_pilot, biz)
    row = await asyncio.to_thread(ready_artwork, biz, image_id) if image_id is not None else None
    if not connection_ids:
        raise HTTPException(400, 'Choose at least one connected account. Nothing was posted.')
    targets = await asyncio.to_thread(social._targets, biz, connection_ids)
    targets, dropped = fit_targets(targets, has_picture=row is not None)
    if not targets:
        raise HTTPException(400, _nowhere(dropped))
    scheduled_at = social._schedule(scheduled_at)
    caption = (caption or '').strip()
    if row is None and not caption:
        raise HTTPException(400, 'Write something to post, or choose a design. Nothing was posted.')
    social._check(caption, [_PICTURE_TO_COME] if row else [], targets)

    image_key = str(row['id']) if row else None
    digest = approved_hash(image_key, caption, targets, scheduled_at)
    publication_id = publication_id_for(biz, image_key, request_id)
    out = {'image': _image_out(row), 'dropped': dropped}

    # Already sent: this request again, or the same post a moment ago.
    again = await asyncio.to_thread(_earlier, biz, publication_id)
    if again:
        if again.get('status') == 'failed':
            # The same request, whose hand-off was refused: the same answer.
            raise HTTPException(502, social.REFUSED)
        return {'ok': True, 'already': True, 'publication': social._public(again), **out}
    twin = await asyncio.to_thread(recent_duplicate, biz, digest)
    if twin:
        return {'ok': True, 'already': True, 'publication': social._public(twin), **out}

    media: List[Dict[str, Any]] = []
    if row:
        link = await delivery_link(biz, user_id, row)
        social._check(caption, [{'url': link, 'kind': 'image'}], targets)
        media = [{'url': link, 'kind': 'image', 'image_id': image_key, 'title': design_title(row)}]

    publication, sent_now = await social.send_post(
        biz, user_id, caption=caption, media=media, targets=targets, scheduled_at=scheduled_at,
        approved_hash=digest, publication_id=publication_id)
    return {'ok': True, 'already': not sent_now, 'publication': social._public(publication), **out}
