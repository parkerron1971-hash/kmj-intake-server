"""A designed cover for a clip.

The same engine as a chat flyer (creative_director.handle_design_flyer: plan,
draw, check the finished picture, repair once; 30 credits), with the clip's
clean frame as the subject and the clip's title as its words. "Remember this
style" on one cover gives every later cover the same look, so a sermon series
reads as a set.

The cover's id is saved in the clip's configuration, which is part of what an
approval covers: a clip goes out with its cover, so a new cover after approval
asks for a fresh look first.
"""
from __future__ import annotations

import asyncio
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


async def frame_artwork(client, biz, row, user_id):
    """The clean frame, copied once into the business's private image gallery,
    so the Director treats it like any picture the owner uploaded."""
    image_id = str(uuid5(UUID(media_library.key(row['id'])), 'cover-frame'))
    if await images.db(client, 'GET', f"/image_artworks?id=eq.{image_id}&business_id=eq.{UUID(str(biz['id']))}"):
        return image_id
    url = (os.environ.get('SUPABASE_URL', '').rstrip('/') + f'/storage/v1/object/{media_library.BUCKET}/'
           + clip_finder.frame_path(row))
    response = await client.get(url, headers=storage_links.service_headers())
    if not response.is_success:
        raise HTTPException(502, 'The clip frame could not be loaded. Try again.')
    raw = images.normalize_image(response.content)
    path = f"{biz['id']}/{image_id}.png"
    await images.store(client, path, raw, 'image/png')
    await images.db(client, 'POST', '/image_artworks', {
        'id': image_id, 'business_id': str(biz['id']), 'owner_id': str(user_id),
        'prompt': f"Clean frame: {row.get('name') or 'clip'}"[:180], 'status': 'ready', 'storage_path': path},
        server_write=True)
    return image_id


def remember_cover(row, image_id):
    # Read again: the design took a minute, and the clip may have changed meanwhile.
    fresh = media_library.read(f"/media_assets?id=eq.{media_library.key(row['id'])}"
                               f"&business_id=eq.{media_library.key(row['business_id'])}&select=configuration&limit=1")
    configuration = dict((fresh[0] if fresh else row).get('configuration') or {}, cover_image_id=str(image_id))
    media_library.one(sb_clients.sb_patch_as_service(
        f"/media_assets?id=eq.{media_library.key(row['id'])}&business_id=eq.{media_library.key(row['business_id'])}",
        {'configuration': configuration}))


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
        turn = images.turn_id.set(f'clip-cover:{asset_id}:{body.request_id}')
        index = images.turn_image_index.set(0)
        try:
            result = await creative_director.handle_design_flyer(client, biz, {
                'goal': GOAL.format(title=row.get('name') or 'this clip'), 'exact_copy': words, 'size': body.size,
                'references': [{'id': frame_id, 'role': 'subject', 'use': 'The speaker in this clip. Keep their exact likeness.'}],
                'owner_request': 'Make a cover for this clip'})
        finally:
            images.turn_id.reset(turn)
            images.turn_image_index.reset(index)
    cover = result.get('image') or {}
    if cover.get('id'):
        await asyncio.to_thread(remember_cover, row, cover['id'])
    return {'ok': True, 'cover': cover, 'result': result['result']}
