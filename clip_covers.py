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

Two shapes (Kevin, 2026-10-06: "I like the full screen videos covers along
with the story size ... have both"): story is 9:16 for Reels, Shorts and
TikTok; wide is 16:9 for a YouTube thumbnail. A cover can follow a picture the
owner likes (a style reference: its look, never its words or people) and a
short note about the look. Find my best clips can design them as the clips are
made: cover_tick() covers the run's best clips once it completes.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
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

LIKENESS = ('The person in the reference photo is the hero: keep their exact likeness (face, hair, skin tone, build, '
            'clothing and anything they hold) and do not change their identity, age or expression. ')
GOAL = ('A cover image for a short video clip titled "{title}". ' + LIKENESS +
        'Cut them out and make them large, so their face reads at phone-thumbnail '
        'size. Bold, high-contrast and made to stop a scroll. Keep the top 8% and the bottom 14% free of lettering: '
        'the apps cover those edges.')
WIDE_GOAL = ('A widescreen 16:9 video thumbnail for a video titled "{title}". ' + LIKENESS +
             'Make them large on one side with the title huge beside them, so it reads at the small size a video '
             'list shows. Bold, high-contrast and made to be clicked. Keep the bottom-right corner (about a fifth '
             'of the width and the bottom sixth) free of lettering and faces: the video length sits there.')

# The shapes a cover comes in, and the size each is drawn at.
SHAPES = {'story': '1088x1920', 'wide': '1920x1088'}
SHAPE_OF = {'1088x1920': 'story', '1920x1088': 'wide', '1024x1024': 'square'}
Shape = Literal['story', 'wide']
STYLE_USE = 'The look to follow: copy its layout, type treatment, palette, light and texture only; never its words, people or logos.'
# Covers designed along with a Find my best clips run: the best-scoring clips
# first, at most this many. Each shape is one design (30 credits), and a
# business can start 20 designs a day (reserve_image_artwork), so 6 clips in
# both shapes leaves room for Make cover and flyers the same day.
AUTO_CLIP_LIMIT = int(os.environ.get('CLIP_COVER_LIMIT', '6'))
AUTO_WINDOW = timedelta(hours=6)


class Cover(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # The app's idempotency key: a second tap with the same id never pays twice.
    request_id: UUID
    # The words on the cover; the clip's title when left out.
    words: Optional[list[str]] = Field(default=None, min_length=1, max_length=4)
    # One shape (the original field) or several at once: story and wide.
    size: Literal['1088x1920', '1920x1088', '1024x1024'] = '1088x1920'
    sizes: Optional[list[Shape]] = Field(default=None, min_length=1, max_length=2)
    # A picture in this business's gallery whose look the cover follows.
    style_image_id: Optional[UUID] = None
    # A few words about the look: "keep it dark, almost black and white".
    note: Optional[str] = Field(default=None, max_length=300)


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
        'status': 'ready', 'storage_path': path, 'cost_usd': 0},
        server_write=True)
    return image_id


def covers_for(business_id, rows):
    """Each clip's story cover (the original single cover); see shaped_covers."""
    return {clip: shapes['story'] for clip, shapes in shaped_covers(business_id, rows).items() if 'story' in shapes}


def shaped_covers(business_id, rows):
    """Each clip's covers by shape ({clip: {'story': id, 'wide': id}}), read
    from the designs that name it: per shape, the newest one that has not
    failed. A cover still designing is shown as designing (so the card never
    offers a second paid Make cover), and a failed attempt never hides an
    earlier good cover; with only failures, the newest failure shows. A failed
    read means no covers shown, never an error on the clips."""
    clips = [media_library.key(r['id']) for r in rows if r.get('kind') == 'clip']
    found = []
    for start in range(0, len(clips), 100):  # keep each query URL short
        batch = sb_clients.sb_get_as_service(
            f"/image_artworks?business_id=eq.{media_library.key(business_id)}"
            f"&director->>clip_id=in.({','.join(clips[start:start + 100])})"
            "&select=id,status,size,director->>clip_id,created_at&order=created_at.desc&limit=1000")
        if batch is None:
            log.warning('Clip covers could not be read for business %s', business_id)
            return {}
        found.extend(batch)
    best = {}
    for row in sorted(found, key=lambda r: r.get('created_at') or '', reverse=True):
        key = (row.get('clip_id'), SHAPE_OF.get(row.get('size'), 'story'))
        failed = row.get('status') == 'failed'
        if key not in best or (best[key][1] and not failed):
            best[key] = (row['id'], failed)
    shaped = {}
    for (clip, shape), (image_id, _) in best.items():
        shaped.setdefault(clip, {})[shape] = image_id
    return shaped


# Clips whose recording had no usable face for a close-up, in this process:
# asked once, then the cover uses the stage frame alone.
_no_face = set()


def backfill_face(row):
    """A close-up for a clip made before close-ups existed (2026-10-06: Kevin's
    "Don't Judge Rightness By Feelings" cover was about 75% him, drawn from a
    wide shot where his face was 30 px and turned). The clip service reads the
    clip's stretch of the recording while it is kept (7 days), else the clip
    itself, and the close-up is saved where a clip run would have put it. The
    clip's configuration stays as it is: it is permanent once it exists."""
    if str(row['id']) in _no_face or not os.environ.get('CLIPPER_URL') or not os.environ.get('CLIPPER_TOKEN'):
        return False
    cfg = row.get('configuration') or {}
    source = media_library.read(f"/media_assets?id=eq.{media_library.key(row.get('source_id') or row['id'])}"
                                f"&business_id=eq.{media_library.key(row['business_id'])}&select=*&limit=1") if row.get('source_id') else []
    start, end = cfg.get('start_seconds'), cfg.get('end_seconds')
    if source and source[0].get('status') == 'ready' and not source[0].get('source_removed_at') and start is not None and end:
        url = storage_links.signed_url_sync(media_library.BUCKET, media_library.object_path(source[0]), ttl=900)
    else:
        url, start, end = storage_links.signed_url_sync(media_library.BUCKET, media_library.object_path(row), ttl=900), 0.0, float(row.get('duration_seconds') or 0)
    if not url or not end:
        return False
    try:
        response = clip_finder.clipper('POST', '/faces', json={'source_url': url, 'start': float(start), 'end': float(end)})
    except httpx.HTTPError:
        log.warning('Face close-up could not be requested for clip %s', row['id'])
        return False
    if response.status_code == 404:
        # Remember only the endpoint's own answer: a clip service from before
        # /faces existed also says 404 (Not Found), and that is not this clip's fault.
        try:
            said = (response.json() or {}).get('detail')
        except ValueError:
            said = None
        if said == 'No usable face in that stretch':
            _no_face.add(str(row['id']))
        return False
    if response.status_code != 200 or not response.content:
        log.warning('Face close-up for clip %s: clip service answered %s', row['id'], response.status_code)
        return False
    import tempfile
    with tempfile.TemporaryDirectory(prefix='clip-face-') as folder:
        local = os.path.join(folder, 'face.jpg')
        with open(local, 'wb') as out:
            out.write(response.content)
        try:
            clip_finder.put_file(local, clip_finder.face_path(row), 'image/jpeg')
        except clip_finder.RunFailed:
            log.warning('Face close-up for clip %s could not be saved', row['id'])
            return False
    return True


async def subject_references(client, biz, row, user_id):
    """The clip's pictures of the speaker: the face close-up first (the
    authority on the face and hair: likeness over 90%), then the stage frame.
    A clip from before close-ups gets one made now (backfill_face)."""
    references = [{'id': await frame_artwork(client, biz, row, user_id), 'role': 'subject',
                   'use': 'The speaker on stage: pose, body and clothes. Keep their exact likeness.'}]
    # Best effort, like making it: a close-up that cannot be read or made
    # leaves the cover to the stage frame alone instead of failing it.
    face_id = None
    try:
        face_id = await frame_artwork(client, biz, row, user_id, kind='face')
    except HTTPException:
        if not (row.get('configuration') or {}).get('face') and await asyncio.to_thread(backfill_face, row):
            try:
                face_id = await frame_artwork(client, biz, row, user_id, kind='face')
            except HTTPException:
                face_id = None
        if face_id is None:
            log.warning('No face close-up for clip %s; using the frame alone', row['id'])
    if face_id:
        references.insert(0, {'id': face_id, 'role': 'subject',
                              'use': 'Close-up of the same person: match this face, beard, hairline and hairstyle exactly.'})
    return references


def cover_action(row, *, size, words, references, style_image_id=None, note=None):
    """The design request for one cover of one clip."""
    goal = (WIDE_GOAL if size == SHAPES['wide'] else GOAL).format(title=row.get('name') or 'this clip')
    note = (note or '').strip()[:300]
    if note:
        goal += ' The owner asked for this look: ' + note
    references = list(references)
    if style_image_id:
        references.append({'id': str(style_image_id), 'role': 'style', 'use': STYLE_USE})
    noun = 'thumbnail' if size == SHAPES['wide'] else 'cover'
    return {'goal': goal, 'exact_copy': words, 'size': size, 'references': references,
            'owner_request': f'Make a {noun} for this clip' + (f'. Look: {note}' if note else ''),
            'clip_id': str(row['id'])}


async def design(client, biz, action, turn):
    """One design, under a stable turn id: the same request never pays twice."""
    turn_token = images.turn_id.set(turn)
    index = images.turn_image_index.set(0)
    try:
        return await creative_director.handle_design_flyer(client, biz, action)
    finally:
        images.turn_id.reset(turn_token)
        images.turn_image_index.reset(index)


def words_for(row, words=None):
    words = [w.strip()[:200] for w in (words or [row.get('name') or '']) if w and w.strip()]
    if not words:
        raise HTTPException(422, 'Say what the cover should read, or give the clip a title first.')
    return words


@router.post('/{business_id}/clips/{asset_id}/cover', status_code=202)
async def make_cover(business_id: UUID, asset_id: UUID, body: Cover,
                     session: UserSession = Depends(sb_clients.authed_request)):
    sizes = [SHAPES[shape] for shape in dict.fromkeys(body.sizes)] if body.sizes else [body.size]
    async with httpx.AsyncClient(timeout=60) as client:
        # The owner only, checked before anything about the clip is read or
        # revealed: a cover spends the business's credits, like Image Studio.
        biz = await images.business(client, business_id)
        row = await asyncio.to_thread(clip_row, business_id, asset_id)
        words = words_for(row, body.words)
        references = await subject_references(client, biz, row, session.user.id)
        busy = await asyncio.to_thread(designing_now, business_id, asset_id)
        covers, errors, result = {}, {}, None
        for size in sizes:
            shape = SHAPE_OF[size]
            if size in busy:
                # A cover in this shape is still being designed (the one made
                # with the clips, or a tap a moment ago): never pay twice.
                errors[shape] = 'A cover in this shape is already being designed.'
                continue
            action = cover_action(row, size=size, words=words, references=references,
                                  style_image_id=body.style_image_id, note=body.note)
            # A single-shape request keeps the original turn id, so a retried
            # tap from an older app still lands on the same design.
            turn = f'clip-cover:{asset_id}:{body.request_id}' + ('' if body.sizes is None else f':{shape}')
            try:
                result = await design(client, biz, action, turn)
            except HTTPException as error:
                # One shape can fail (the credits ran out after the first) while
                # the other is already designing: report both, never hide the first.
                if not covers and size == sizes[-1]:
                    raise
                errors[shape] = str(error.detail)
                continue
            covers[shape] = result.get('image') or {}
    if not covers:
        raise HTTPException(409 if all('already being designed' in e for e in errors.values()) else 402,
                            next(iter(errors.values()), 'The cover could not be started.'))
    return {'ok': True, 'cover': next(iter(covers.values())), 'covers': covers, 'errors': errors,
            'clip_id': str(asset_id), 'result': (result or {}).get('result') or ''}


# -- designed along with the clips ---------------------------------------

# Attempts per (clip, shape) in this process: a design that cannot start
# (no credits, the spend limit, the daily cap) is tried twice, then the owner
# is told once and the clip keeps its Make cover button. Kept in memory on
# purpose: a restart allows two more tries (they cost nothing until a design
# starts) and at most one more notice, inside the 6-hour window.
_tries = {}
_told = set()
TRIES = 2


def designing_now(business_id, clip_id):
    """The sizes this clip has a cover still being designed in."""
    rows = sb_clients.sb_get_as_service(
        f"/image_artworks?business_id=eq.{media_library.key(business_id)}&director->>clip_id=eq.{media_library.key(clip_id)}"
        "&status=in.(queued,working)&select=size&limit=20") or []
    return {r.get('size') for r in rows}


def run_clips(run):
    """The run's clips that can take a cover, best score first, capped."""
    rows = media_library.read(
        f"/media_assets?business_id=eq.{media_library.key(run['business_id'])}&kind=eq.clip&status=eq.ready"
        f"&configuration->>run_id=eq.{media_library.key(run['id'])}&select=*&limit=200")
    rows = [r for r in rows if r.get('decision') != 'skipped' and (r.get('configuration') or {}).get('frame')]
    rows.sort(key=lambda r: -float((r.get('configuration') or {}).get('score') or 0))
    return rows[:AUTO_CLIP_LIMIT]


async def cover_run(client, run):
    """Design every cover the run asked for that does not exist yet, and
    return (made, why_stopped). why_stopped is the last reason a design could
    not start, once every missing cover has used its tries; None otherwise.
    Stable turn ids make it safe to call again: a design already made is
    skipped, and a second call for the same clip and shape lands on it."""
    plan = (run.get('options') or {}).get('covers') or {}
    shapes = [s for s in dict.fromkeys(plan.get('sizes') or ['story', 'wide']) if s in SHAPES]
    rows = await asyncio.to_thread(run_clips, run)
    if not rows or not shapes:
        return 0, None
    existing = await asyncio.to_thread(shaped_covers, run['business_id'], rows)
    missing = [(row, s) for row in rows for s in shapes if s not in existing.get(str(row['id']), {})]
    todo = [(row, s) for row, s in missing if _tries.get((str(row['id']), s), 0) < TRIES]
    if not todo:
        return 0, None
    if len(_tries) > 5000:
        _tries.clear()
    # The run's owner, checked again by images.business: covers spend credits.
    actor = images.build_actor.set({'business_id': str(run['business_id']), 'user_id': str(run['created_by'])})
    made, reason, pictures = 0, None, {}
    try:
        biz = await images.business(client, run['business_id'])
        for row, shape in todo:
            key = (str(row['id']), shape)
            _tries[key] = _tries.get(key, 0) + 1
            try:
                if key[0] not in pictures:
                    pictures[key[0]] = await subject_references(client, biz, row, run['created_by'])
                action = cover_action(row, size=SHAPES[shape], words=words_for(row), references=pictures[key[0]],
                                      style_image_id=plan.get('style_image_id'), note=plan.get('note'))
                await design(client, biz, action, f'clip-cover:{row["id"]}:auto-{run["id"]}:{shape}')
                made += 1
            except HTTPException as error:
                reason = str(error.detail)
                log.warning('Clip cover not started for %s (%s): %s', key[0], shape, reason)
    finally:
        images.build_actor.reset(actor)
    spent = all(_tries.get((str(row['id']), s), 0) >= TRIES for row, s in missing
                if s not in existing.get(str(row['id']), {}))
    return made, (reason if reason and spent else None)


def runs_wanting_covers():
    since = clip_finder._z(datetime.now(timezone.utc) - AUTO_WINDOW)
    return sb_clients.sb_get_as_service(
        f'/media_clip_runs?status=eq.completed&finished_at=gte.{since}&options->covers=not.is.null'
        '&select=id,business_id,created_by,options,finished_at&order=finished_at.asc&limit=10') or []


def tell_owner_covers_stopped(run, reason):
    """One Chief notice per run, marked as told only once it is written."""
    if run['id'] in _told:
        return
    try:
        written = sb_clients.sb_post_as_service('/chief_notifications', {
            'business_id': str(run['business_id']), 'type': 'warning', 'title': 'Some covers were not designed',
            'body': f'{reason} The clips are ready; tap Make cover on any clip when you want one.'[:400],
            'status': 'unread', 'data': {'kind': 'clip_covers_stopped', 'run_id': str(run['id'])}})
    except Exception:
        written = None
    if written:
        _told.add(run['id'])
    else:
        log.warning('Clip covers notice failed for run %s', run['id'])


async def cover_tick():
    """Covers for the runs that asked for them. A business out of credits or
    past its spend limit is told once, and its clips keep Make cover."""
    if not clip_finder.enabled():
        return
    runs = await asyncio.to_thread(runs_wanting_covers)
    if not runs:
        return
    async with httpx.AsyncClient(timeout=60) as client:
        for run in runs:
            try:
                _, stopped = await cover_run(client, run)
            except HTTPException as error:
                # The run as a whole could not be read or acted for (the owner
                # changed, storage unavailable): logged, tried again next tick.
                log.warning('Clip covers paused for run %s: %s', run['id'], error.detail)
                continue
            except Exception:
                log.exception('Clip covers failed for run %s', run['id'])
                continue
            if stopped:
                await asyncio.to_thread(tell_owner_covers_stopped, run, stopped)
