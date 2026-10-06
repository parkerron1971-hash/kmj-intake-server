"""A designed cover for a clip.

The same engine as a chat flyer (creative_director.handle_design_flyer: plan,
draw, check the finished picture, repair once; 30 credits), with the clip's
clean frame as the subject and the clip's title as its words. "Remember this
style" on one cover gives every later cover the same look, so a sermon series
reads as a set.

The link lives on the cover (its director record names the clip), never on
the clip: the database makes a clip's configuration permanent once it exists
(preserve_media_review), so a reviewed clip cannot change underneath its
approval. covers_for() reads the links back for the Video Clips list.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal, Optional
from uuid import UUID, uuid5

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

import clip_finder
import creative_director
import image_studio as images
import media_library
import sb_clients
import storage_links
from auth_supabase import UserSession

router = APIRouter(prefix='/media-library', tags=['clip covers'])
log = logging.getLogger(__name__)

GOAL = ('A cover image for a short video clip titled "{title}". The person in the reference photo is the hero: '
        'keep their exact likeness (face, hair, skin tone, build, clothing and anything they hold) and do not change '
        'their identity, age or expression. Cut them out and make them large, so their face reads at phone-thumbnail '
        'size. Bold, high-contrast and made to stop a scroll. Keep the top 8% and the bottom 14% free of lettering: '
        'the apps cover those edges.')


class Cover(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # The app's idempotency key: a second tap with the same id never pays twice.
    request_id: UUID
    # The words on the cover; the clip's title when left out.
    words: Optional[list[str]] = Field(default=None, min_length=1, max_length=4)
    # Clips are vertical, so is the cover; wide is for a YouTube thumbnail.
    size: Literal['1088x1920', '1920x1088', '1024x1024'] = '1088x1920'


def clip_row(business_id, asset_id):
    rows = media_library.read(f'/media_assets?id=eq.{media_library.key(asset_id)}'
                              f'&business_id=eq.{media_library.key(business_id)}&kind=eq.clip&select=*&limit=1')
    if not rows or rows[0].get('status') != 'ready':
        raise HTTPException(404, 'That clip is not in this business.')
    if not (rows[0].get('configuration') or {}).get('frame'):
        raise HTTPException(409, 'This clip has no clean frame to design a cover from. Clips found from now on have one.')
    return rows[0]


async def frame_artwork(client, biz, row, user_id, kind='frame'):
    """The clean frame (or the face close-up, kind='face'), copied once into the
    business's private image gallery, so the Director treats it like any
    picture the owner uploaded."""
    image_id = str(uuid5(UUID(media_library.key(row['id'])), f'cover-{kind}'))
    if await images.db(client, 'GET', f"/image_artworks?id=eq.{image_id}&business_id=eq.{UUID(str(biz['id']))}"):
        return image_id
    url = (os.environ.get('SUPABASE_URL', '').rstrip('/') + f'/storage/v1/object/{media_library.BUCKET}/'
           + (clip_finder.face_path(row) if kind == 'face' else clip_finder.frame_path(row)))
    response = await client.get(url, headers=storage_links.service_headers())
    if not response.is_success:
        raise HTTPException(502, 'The clip frame could not be loaded. Try again.')
    raw = images.normalize_image(response.content)
    path = f"{biz['id']}/{image_id}.png"
    await images.store(client, path, raw, 'image/png')
    await images.db(client, 'POST', '/image_artworks', {
        'id': image_id, 'business_id': str(biz['id']), 'owner_id': str(user_id),
        'prompt': f"{'Face close-up' if kind == 'face' else 'Clean frame'}: {row.get('name') or 'clip'}"[:180],
        'status': 'ready', 'storage_path': path},
        server_write=True)
    return image_id


def covers_for(business_id, rows):
    """Each clip's cover, read from the designs that name it: the newest one
    that has not failed. A cover still designing is shown as designing (so the
    card never offers a second paid Make cover), and a failed attempt never
    hides an earlier good cover; with only failures, the newest failure shows.
    A failed read means no covers shown, never an error on the clips."""
    clips = [media_library.key(r['id']) for r in rows if r.get('kind') == 'clip']
    found = []
    for start in range(0, len(clips), 100):  # keep each query URL short
        batch = sb_clients.sb_get_as_service(
            f"/image_artworks?business_id=eq.{media_library.key(business_id)}"
            f"&director->>clip_id=in.({','.join(clips[start:start + 100])})"
            "&select=id,status,director->>clip_id,created_at&order=created_at.desc&limit=1000")
        if batch is None:
            log.warning('Clip covers could not be read for business %s', business_id)
            return {}
        found.extend(batch)
    best = {}
    for row in sorted(found, key=lambda r: r.get('created_at') or '', reverse=True):
        clip, failed = row.get('clip_id'), row.get('status') == 'failed'
        if clip not in best or (best[clip][1] and not failed):
            best[clip] = (row['id'], failed)
    return {clip: image_id for clip, (image_id, _) in best.items()}


@router.post('/{business_id}/clips/{asset_id}/cover', status_code=202)
async def make_cover(business_id: UUID, asset_id: UUID, body: Cover,
                     session: UserSession = Depends(sb_clients.authed_request)):
    async with httpx.AsyncClient(timeout=60) as client:
        # The owner only, checked before anything about the clip is read or
        # revealed: a cover spends the business's credits, like Image Studio.
        biz = await images.business(client, business_id)
        row = await asyncio.to_thread(clip_row, business_id, asset_id)
        words = [w.strip()[:200] for w in (body.words or [row.get('name') or '']) if w and w.strip()]
        if not words:
            raise HTTPException(422, 'Say what the cover should read, or give the clip a title first.')
        frame_id = await frame_artwork(client, biz, row, session.user.id)
        references = [{'id': frame_id, 'role': 'subject', 'use': 'The speaker on stage: pose, body and clothes. Keep their exact likeness.'}]
        if (row.get('configuration') or {}).get('face'):
            # The face close-up is the authority on the face and hair (likeness over 90%).
            # Best effort, like making it: a close-up that cannot be read leaves the
            # cover to the stage frame alone instead of failing it.
            try:
                face_id = await frame_artwork(client, biz, row, session.user.id, kind='face')
            except HTTPException:
                log.warning('Face close-up could not be loaded for clip %s; using the frame alone', asset_id)
            else:
                references.insert(0, {'id': face_id, 'role': 'subject',
                                      'use': 'Close-up of the same person: match this face, beard, hairline and hairstyle exactly.'})
        turn = images.turn_id.set(f'clip-cover:{asset_id}:{body.request_id}')
        index = images.turn_image_index.set(0)
        try:
            result = await creative_director.handle_design_flyer(client, biz, {
                'goal': GOAL.format(title=row.get('name') or 'this clip'), 'exact_copy': words, 'size': body.size,
                'references': references,
                'owner_request': 'Make a cover for this clip', 'clip_id': str(asset_id)})
        finally:
            images.turn_id.reset(turn)
            images.turn_image_index.reset(index)
    return {'ok': True, 'cover': result.get('image') or {}, 'clip_id': str(asset_id), 'result': result['result']}
