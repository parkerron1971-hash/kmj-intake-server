"""Find my best clips: one long recording → short vertical clips to review.

Grow → Video Clips. The API never cuts video itself. It keeps the recording
private in program-media, hands the clip service (clipper_worker/, its own
Railway service) a signed link, follows the job, and files each finished
clip into media_assets as a ready clip carrying its empty-spot notices. The
existing review and handoff steps apply to these clips unchanged.

A run survives an API restart: the clip service keeps the job under the
run's id, so the next claim picks up where the last one stopped instead of
paying for the recording twice.

Plan: Growth (the Solutionist plan, feature key `ai_clips`). Ten hours of
recordings a month are included; each hour past that costs 75 actions.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import subprocess
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid5

import httpx
from fastapi import HTTPException
from pydantic import Field

import media_library
import sb_clients
import storage_links
from program_outcomes import StrictModel

log = logging.getLogger('uvicorn.error')  # the logger Railway shows for the scheduler
FEATURE = 'ai_clips'
BUCKET = media_library.BUCKET
MAX_UPLOAD_BYTES = 5 * 1024 ** 3
MAX_CLIP_BYTES = 600 * 1024 ** 2
LIBRARY_BYTES = 20 * 1024 ** 3          # same allowance enqueue_media_asset enforces
CHUNK_BYTES = 6 * 1024 * 1024           # Supabase resumable uploads require exactly 6 MB
INCLUDED_SECONDS = 10 * 3600
UNITS_PER_EXTRA_HOUR = 75
POLL_SECONDS = 8
CAPTION_STYLES = {'pop': 'pop', 'clean': 'subtle', 'headline': 'headline'}
UPLOAD_TYPES = ('video/mp4', 'video/quicktime', 'video/webm')
RUN_COLUMNS = 'id,business_id,source_id,status,stage,percent,clips_done,clips_total,options,source_seconds,error,counts,units,created_at,finished_at'


class UploadStart(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    byte_size: int = Field(gt=0, le=MAX_UPLOAD_BYTES)
    mime_type: Literal[UPLOAD_TYPES]
    rights_confirmed: Literal[True]


class CoverPlan(StrictModel):
    """Covers designed as the clips are made (clip_covers.cover_tick)."""
    sizes: list[Literal['story', 'wide']] = Field(default_factory=lambda: ['story', 'wide'], min_length=1, max_length=2)
    style_image_id: Optional[UUID] = None
    note: Optional[str] = Field(default=None, max_length=300)


class FindClips(StrictModel):
    lengths: list[Literal['short', 'medium', 'long']] = Field(default_factory=lambda: ['short', 'medium'], min_length=1, max_length=3)
    caption_style: Literal['pop', 'clean', 'headline'] = 'pop'
    look_for: Optional[str] = Field(default=None, max_length=1000)
    covers: Optional[CoverPlan] = None


class ClipUpdate(StrictModel):
    decision: Optional[Literal['kept', 'skipped']] = None
    clear_decision: bool = False
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)


class Cancelled(Exception):
    pass


class RunFailed(Exception):
    pass


# ── switches and allowance ───────────────────────────────────────────

def enabled(business_id=None):
    if os.getenv('CLIP_FINDER', 'off') != 'on' or not os.getenv('CLIPPER_URL') or len(os.getenv('CLIPPER_TOKEN', '')) < 32:
        return False
    if business_id is None:
        return True
    allowed = {b.strip() for b in os.getenv('CLIP_FINDER_BUSINESSES', '').split(',') if b.strip()}
    return '*' in allowed or str(business_id) in allowed


def _z(moment):
    # '+00:00' reads as a space inside a PostgREST query string.
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def seconds_this_month(business_id):
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = media_library.read(f'/media_clip_runs?business_id=eq.{media_library.key(business_id)}'
                              f'&status=in.(queued,working,completed)&created_at=gte.{_z(start)}&select=id,source_seconds')
    return sum(float(r.get('source_seconds') or 0) for r in rows)


def extra_units(used_seconds, seconds):
    """Actions owed for the part of this recording past the month's included hours."""
    before = max(0.0, used_seconds - INCLUDED_SECONDS)
    after = max(0.0, used_seconds + seconds - INCLUDED_SECONDS)
    return math.ceil((after - before) / 3600 * UNITS_PER_EXTRA_HOUR) if after > before else 0


def configuration(business_id):
    used = seconds_this_month(business_id) if enabled(business_id) else 0.0
    return {'available': enabled(business_id), 'included_hours': INCLUDED_SECONDS // 3600,
            'used_hours': round(used / 3600, 1), 'actions_per_extra_hour': UNITS_PER_EXTRA_HOUR,
            'max_upload_bytes': MAX_UPLOAD_BYTES, 'caption_styles': list(CAPTION_STYLES), 'lengths': ['short', 'medium', 'long'],
            'covers': cover_offer()}


def cover_offer():
    """What a cover costs and how many a run designs, for the app to price it."""
    import clip_covers
    import image_studio
    from chief_code import flyer_verb
    return {'available': flyer_verb() == 'design_flyer', 'credits_each': image_studio.image_units('high'),
            'clip_limit': clip_covers.AUTO_CLIP_LIMIT, 'shapes': list(clip_covers.SHAPES)}


def library_bytes(business_id):
    # Recordings removed under the 7-day rule no longer take up the allowance
    # (enqueue_media_asset counts the same way).
    rows = media_library.read(f'/media_assets?business_id=eq.{media_library.key(business_id)}&status=neq.failed'
                              '&source_removed_at=is.null&select=byte_size')
    return sum(int(r.get('byte_size') or 0) for r in rows)


# ── storage helpers ──────────────────────────────────────────────────

def _supabase():
    return os.environ['SUPABASE_URL'].rstrip('/')


def resumable_endpoint():
    """Large files go straight to the storage host, as Supabase recommends.

    The signed-token variant lives at /upload/resumable/sign. The plain
    /upload/resumable route ignores x-signature and wants a login token
    ("Invalid Compact JWS"), which the private bucket then refuses; probed
    against production 2026-10-05."""
    host = urlsplit(_supabase()).hostname or ''
    if host.endswith('.supabase.co'):
        return f'https://{host.split(".")[0]}.storage.supabase.co/storage/v1/upload/resumable/sign'
    return _supabase() + '/storage/v1/upload/resumable/sign'


def upload_token(path):
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        response = client.post(f'{_supabase()}/storage/v1/object/upload/sign/{BUCKET}/{path}', headers=storage_links.service_headers(), json={})
    if response.status_code != 200:
        raise HTTPException(503, 'The upload could not be prepared. Try again.')
    data = response.json()
    token = data.get('token') or (parse_qs(urlsplit(data.get('url') or '').query).get('token') or [None])[0]
    if not token:
        raise HTTPException(503, 'The upload could not be prepared. Try again.')
    return token


def stored_size(path):
    folder, _, name = path.rpartition('/')
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        response = client.post(f'{_supabase()}/storage/v1/object/list/{BUCKET}', headers=storage_links.service_headers(),
                               json={'prefix': folder + '/', 'search': name, 'limit': 5})
    if response.status_code != 200:
        return None
    for item in response.json() or []:
        if item.get('name') == name:
            return int(((item.get('metadata') or {}).get('size')) or 0)
    return None


def remove_objects(paths):
    if not paths:
        return
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            client.request('DELETE', f'{_supabase()}/storage/v1/object/{BUCKET}', headers=storage_links.service_headers(), json={'prefixes': list(paths)})
    except httpx.HTTPError:
        log.warning('Clip storage cleanup failed for %d objects', len(paths))


def put_file(local, path, content_type):
    size = Path(local).stat().st_size
    with httpx.Client(timeout=httpx.Timeout(60, write=600), follow_redirects=False) as client, open(local, 'rb') as content:
        response = client.post(f'{_supabase()}/storage/v1/object/{BUCKET}/{path}', content=media_library.upload_chunks(content),
                               headers={**storage_links.service_headers(), 'Content-Type': content_type, 'Content-Length': str(size), 'x-upsert': 'true'})
    if response.status_code >= 400:
        raise RunFailed('A finished clip could not be saved. Try again.')


NOT_A_VIDEO = "That file isn't a video we can read. Try an MP4, MOV or WebM."


def probe_remote(url):
    """Duration of a stored recording, read with range requests (no full download).

    422 only when ffprobe read the file and it is not a usable video; a
    timeout, a missing tool or a storage hiccup is a retryable 503, so the
    caller never deletes a good upload over a blip."""
    try:
        done = subprocess.run([shutil.which('ffprobe') or 'ffprobe', '-v', 'error', '-protocol_whitelist', 'https,tls,tcp,crypto',
                               '-show_entries', 'format=duration:stream=codec_type,width,height', '-of', 'json', url],
                              capture_output=True, text=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        raise HTTPException(503, 'Checking the recording took too long. Try again in a minute.') from None
    if done.returncode != 0:
        if 'Invalid data found' in (done.stderr or '') or 'moov atom not found' in (done.stderr or ''):
            raise HTTPException(422, NOT_A_VIDEO)
        raise HTTPException(503, 'The recording could not be checked right now. Try again in a minute.')
    try:
        data = json.loads(done.stdout or '{}')
        duration = float(data['format']['duration'])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, NOT_A_VIDEO) from None
    videos = [s for s in data.get('streams', []) if s.get('codec_type') == 'video']
    if not videos:
        raise HTTPException(422, 'That file has no video in it.')
    if not 0 < duration <= media_library.MAX_SECONDS:
        raise HTTPException(422, 'Recordings can be up to 2 hours long.')
    if any(int(s.get('width', 0)) * int(s.get('height', 0)) > 3840 * 2160 for s in videos):
        raise HTTPException(422, 'Recordings can be up to 4K.')
    return duration


def poster_path(row):
    return media_library.key(row['business_id']) + '/' + media_library.key(row['id']) + '.jpg'


def face_path(row, n=1):
    """A head-and-shoulders close-up from the recording: the cover's guide to
    the face and hair. n 2 and 3 are more close-ups from other moments."""
    return media_library.key(row['business_id']) + '/' + media_library.key(row['id']) + ('-face.jpg' if n == 1 else f'-face{n}.jpg')


def frame_path(row):
    """The clean frame behind a clip's cover: the poster's moment, taken from
    the recording without captions or a title card."""
    return media_library.key(row['business_id']) + '/' + media_library.key(row['id']) + '-frame.jpg'


def poster_urls(rows):
    """One signing call for every poster on the page."""
    wanted = {poster_path(r): str(r['id']) for r in rows
              if r.get('kind') == 'clip' and r.get('status') == 'ready' and (r.get('configuration') or {}).get('poster')}
    if not wanted:
        return {}
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.post(f'{_supabase()}/storage/v1/object/sign/{BUCKET}', headers=storage_links.service_headers(),
                                   json={'expiresIn': 900, 'paths': list(wanted)})
        if response.status_code != 200:
            return {}
        return {wanted[item['path']]: _supabase() + '/storage/v1' + item['signedURL']
                for item in response.json() if item.get('signedURL') and item.get('path') in wanted}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {}


# ── uploads from a computer ──────────────────────────────────────────

def audit(business_id, user_id, action, payload):
    import audit_log
    audit_log.record(str(business_id), actor_type='user', actor_id=str(user_id), verb='media_' + action,
                     ok=True, summary='Private media ' + action.replace('_', ' '), payload=payload, source='clip_finder')


def start_upload(business_id, body, user):
    media_library.access(business_id, user)
    if library_bytes(business_id) + body.byte_size > LIBRARY_BYTES:
        raise HTTPException(409, 'This media library has reached its 20 GB allowance. Remove recordings you no longer need first.')
    row = media_library.one(sb_clients.sb_post_as_service('/media_assets', {
        'business_id': media_library.key(business_id), 'kind': 'source', 'name': body.name, 'status': 'uploading',
        'byte_size': body.byte_size, 'created_by': str(user.id),
        'configuration': {'origin': 'upload', 'mime_type': body.mime_type, 'authorized_to_copy': True,
                          'permission_note': 'Uploaded from a computer by a manager who confirmed the right to use it.'}}))
    token = upload_token(media_library.object_path(row))
    audit(business_id, user.id, 'upload_start', {'asset_id': str(row['id']), 'bytes': body.byte_size})
    return {'asset': media_library.public(row), 'upload': {
        'endpoint': resumable_endpoint(), 'token': token, 'bucket': BUCKET, 'object_name': media_library.object_path(row),
        'content_type': body.mime_type, 'chunk_size': CHUNK_BYTES}}


def finish_upload(business_id, asset_id, user):
    row = media_library.asset(business_id, asset_id, user)
    if row['kind'] != 'source' or row['status'] != 'uploading':
        raise HTTPException(409, 'This upload is already finished.')
    path = media_library.object_path(row)
    if stored_size(path) != int(row['byte_size']):
        raise HTTPException(409, "The upload isn't complete yet. Keep this page open until it finishes.")
    url = storage_links.signed_url_sync(BUCKET, path, ttl=900)
    if not url:
        raise HTTPException(503, 'The recording could not be checked. Try again.')
    try:
        duration = probe_remote(url)
    except HTTPException as error:
        if error.status_code == 422:
            # The file itself is not a usable video: nothing to keep.
            remove_objects([path])
            sb_clients.sb_delete_as_service(f'/media_assets?id=eq.{media_library.key(asset_id)}&status=eq.uploading')
        raise
    saved = media_library.one(sb_clients.sb_patch_as_service(
        f'/media_assets?id=eq.{media_library.key(asset_id)}&business_id=eq.{media_library.key(business_id)}&status=eq.uploading',
        {'status': 'ready', 'duration_seconds': duration, 'finished_at': _z(datetime.now(timezone.utc))}))
    audit(business_id, user.id, 'upload_finish', {'asset_id': str(asset_id), 'seconds': round(duration)})
    return media_library.public(saved)


def cancel_upload(business_id, asset_id, user):
    row = media_library.asset(business_id, asset_id, user)
    if row['status'] != 'uploading':
        raise HTTPException(409, 'Only an unfinished upload can be cancelled here.')
    remove_objects([media_library.object_path(row)])
    sb_clients.sb_delete_as_service(f'/media_assets?id=eq.{media_library.key(asset_id)}&status=eq.uploading')
    return {'cancelled': True}


# ── starting, listing and cancelling runs ────────────────────────────

def public_run(row):
    return {k: row.get(k) for k in RUN_COLUMNS.split(',')}


def runs(business_id, user):
    media_library.access(business_id, user)
    return [public_run(r) for r in media_library.read(
        f'/media_clip_runs?business_id=eq.{media_library.key(business_id)}&select={RUN_COLUMNS}&order=created_at.desc&limit=20')]


def start_run(business_id, source_id, body, user):
    source = media_library.asset(business_id, source_id, user)
    if not enabled(business_id):
        raise HTTPException(503, "Find my best clips isn't switched on for this business yet.")
    import billing_limits
    import spend_guard
    billing_limits.require_feature(str(business_id), FEATURE)
    if spend_guard.over_budget(str(business_id)):
        raise HTTPException(429, 'AI work is paused for this business right now. Try again later.')
    if source['kind'] != 'source' or source['status'] != 'ready' or source.get('source_removed_at'):
        raise HTTPException(409, 'Choose a recording that has finished uploading.')
    seconds = float(source.get('duration_seconds') or 0)
    if not 0 < seconds <= media_library.MAX_SECONDS:
        raise HTTPException(409, 'Recordings can be up to 2 hours long.')
    if extra_units(seconds_this_month(business_id), seconds):
        billing_limits.require_units(str(business_id))
    # About 0.4 GB of clips per hour of recording; leave room before starting.
    if library_bytes(business_id) + int(seconds / 3600 * 600 * 1024 ** 2) > LIBRARY_BYTES:
        raise HTTPException(409, 'This media library is nearly full. Remove recordings or clips you no longer need first.')
    if body.covers:
        # Covers spend the business's credits, so only its owner can ask for them.
        owner = sb_clients.sb_get_as_service(f'/businesses?id=eq.{media_library.key(business_id)}&select=owner_id&limit=1') or []
        if not owner or str(owner[0].get('owner_id')) != str(user.id):
            raise HTTPException(403, 'Only the owner can have covers designed with the clips.')
        if not cover_offer()['available']:
            raise HTTPException(409, 'Designed covers are switched off right now. Find the clips without them.')
    row = sb_clients.sb_post_as_service('/media_clip_runs', {
        'business_id': media_library.key(business_id), 'source_id': media_library.key(source_id),
        # No covers key unless covers were asked for: a JSON null would still
        # match the cover step's options->covers=not.is.null.
        'options': body.model_dump(mode='json', exclude={'covers'} if body.covers is None else None),
        'source_seconds': seconds, 'created_by': str(user.id)})
    if not row:
        # The one-active-run index refused it.
        raise HTTPException(409, 'Clips are already being found for this business. Wait for that to finish.')
    row = media_library.one(row)
    audit(business_id, user.id, 'clips_start', {'run_id': str(row['id']), 'source_id': str(source_id)})
    return public_run(row)


def cancel_run(business_id, run_id, user):
    media_library.access(business_id, user)
    done = sb_clients.sb_patch_as_service(
        f'/media_clip_runs?id=eq.{media_library.key(run_id)}&business_id=eq.{media_library.key(business_id)}&status=in.(queued,working)',
        {'status': 'cancelled', 'stage': 'cancelled', 'finished_at': _z(datetime.now(timezone.utc))})
    if not done:
        raise HTTPException(409, 'That run has already finished.')
    return {'cancelled': True}


def update_clip(business_id, asset_id, body, user):
    row = media_library.asset(business_id, asset_id, user)
    if row['kind'] != 'clip' or row['status'] != 'ready':
        raise HTTPException(409, 'Only a finished clip can be kept, skipped or renamed.')
    change = {}
    if body.clear_decision:
        change.update(decision=None, decided_at=None)
    elif body.decision:
        change.update(decision=body.decision, decided_at=_z(datetime.now(timezone.utc)))
    if body.name:
        change['name'] = body.name
    if not change:
        return media_library.public(row)
    saved = media_library.one(sb_clients.sb_patch_as_service(
        f'/media_assets?id=eq.{media_library.key(asset_id)}&business_id=eq.{media_library.key(business_id)}', change))
    return media_library.public(saved)


# ── the worker: drive one run on the clip service ────────────────────

def clipper(method, path, **kwargs):
    url = os.environ['CLIPPER_URL'].rstrip('/') + path
    headers = {'Authorization': 'Bearer ' + os.environ['CLIPPER_TOKEN']}
    with httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=False) as client:
        return client.request(method, url, headers=headers, **kwargs)


def fence(run):
    return f'/media_clip_runs?id=eq.{run["id"]}&lease_id=eq.{run["lease_id"]}&status=eq.working'


def lease():
    return _z(datetime.now(timezone.utc) + timedelta(minutes=2))


def report(run, **values):
    if not sb_clients.sb_patch_as_service(fence(run), values | {'lease_until': lease()}):
        raise Cancelled()


def engine_options(options):
    chosen = FindClips.model_validate(options)
    return {'durations': chosen.lengths, 'caption_preset': CAPTION_STYLES[chosen.caption_style],
            'clip_request': chosen.look_for, 'aspect_ratio': '9:16'}


def clip_asset_id(run, index):
    """Stable per run and clip, so a resumed run never files a clip twice."""
    return uuid5(UUID(str(run['id'])), f'clip-{index}')


def fetch(path, target):
    url = os.environ['CLIPPER_URL'].rstrip('/') + path
    headers = {'Authorization': 'Bearer ' + os.environ['CLIPPER_TOKEN']}
    with httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=False) as client:
        media_library.transfer_to_file(client, url, headers, Path(target), maximum=MAX_CLIP_BYTES)


def file_clips(run, source, result):
    job = f'/jobs/{run["id"]}'
    rows = result.get('clips') or []
    filed = 0
    for n, clip in enumerate(rows):
        asset_id = clip_asset_id(run, clip['index'])
        exists = media_library.read(f'/media_assets?id=eq.{asset_id}&select=id&limit=1')
        if not exists:
            with tempfile.TemporaryDirectory(prefix='solutionist-clips-') as folder:
                video = Path(folder) / 'clip.mp4'
                fetch(f'{job}/files/{clip["video"]}', video)
                with video.open('rb') as stream:
                    sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                base = media_library.key(run['business_id']) + '/' + str(asset_id)
                put_file(video, base + '.mp4', 'video/mp4')
                poster = False
                if clip.get('poster'):
                    try:
                        image = Path(folder) / 'poster.jpg'
                        fetch(f'{job}/files/{clip["poster"]}', image)
                        put_file(image, base + '.jpg', 'image/jpeg')
                        poster = True
                    except (ValueError, RunFailed, httpx.HTTPError):
                        log.warning('Poster not saved for clip %s', asset_id)
                face = False
                if clip.get('face'):
                    try:
                        image = Path(folder) / 'face.jpg'
                        fetch(f'{job}/files/{clip["face"]}', image)
                        put_file(image, base + '-face.jpg', 'image/jpeg')
                        face = True
                    except (ValueError, RunFailed, httpx.HTTPError):
                        log.warning('Face close-up not saved for clip %s', asset_id)
                frame = False
                if clip.get('frame'):
                    try:
                        image = Path(folder) / 'frame.jpg'
                        fetch(f'{job}/files/{clip["frame"]}', image)
                        put_file(image, base + '-frame.jpg', 'image/jpeg')
                        frame = True
                    except (ValueError, RunFailed, httpx.HTTPError):
                        log.warning('Clean frame not saved for clip %s', asset_id)
                start, end = (clip.get('start_ms') or 0) / 1000, (clip.get('end_ms') or 0) / 1000
                saved = sb_clients.sb_post_as_service('/media_assets', {
                    'id': str(asset_id), 'business_id': media_library.key(run['business_id']), 'kind': 'clip',
                    'source_id': media_library.key(source['id']), 'name': (clip.get('title') or f'Clip {n + 1}')[:160],
                    'status': 'ready', 'byte_size': video.stat().st_size, 'sha256': sha,
                    'duration_seconds': (clip.get('duration_ms') or 0) / 1000, 'created_by': str(run['created_by']),
                    'finished_at': _z(datetime.now(timezone.utc)),
                    'configuration': {'origin': 'ai', 'run_id': str(run['id']), 'index': clip['index'],
                                      'start_seconds': start, 'end_seconds': end, 'score': clip.get('score'),
                                      'tags': clip.get('tags') or [], 'review_flags': clip.get('review_flags') or [],
                                      'empty_spots': clip.get('empty_spots') or [], 'face_coverage': clip.get('face_coverage'),
                                      'poster': poster, 'frame': frame, 'face': face, 'caption': '', 'destination': ''}})
                if not saved:
                    # Never report a clip that isn't in the library. Stop here and
                    # let the lease lapse: the next claim resumes, and the stable
                    # ids skip every clip already filed.
                    raise RuntimeError(f'Clip {clip["index"]} could not be filed')
        filed += 1
        report(run, stage='saving', percent=round(99 * (filed / max(1, len(rows))), 1), clips_done=filed, clips_total=len(rows))
    return filed


def units_for(run):
    """Actions owed for this run: only the part past the month's included hours."""
    used_before = seconds_this_month(run['business_id']) - float(run['source_seconds'])
    return extra_units(max(0.0, used_before), float(run['source_seconds']))


def meter(run, result, units):
    """Cost goes on the books once, after the run is recorded as completed."""
    cost = ((result.get('cost') or {}).get('total_estimated_cost_usd') or 0) * 100
    try:
        import api_usage_logger
        api_usage_logger.log_api_usage_sync(endpoint='clip_finder', model='bridgeclip', input_tokens=0, output_tokens=0,
                                            business_id=str(run['business_id']), task_type='clip_finder',
                                            cost_cents_override=round(cost * 1.055, 2), units=units,
                                            duration_ms=int(((result.get('timings') or {}).get('total') or 0) * 1000))
    except Exception:
        log.warning('Clip run %s could not be metered', run['id'])


def notify(run, source, filed, flagged):
    look = f' {flagged} need a quick look.' if flagged else ''
    title, body = f'{filed} clips are ready', f'From “{source.get("name") or "your recording"}.”{look}'
    try:
        sb_clients.sb_post_as_service('/chief_notifications', {
            'business_id': str(run['business_id']), 'type': 'success', 'title': title, 'body': body, 'status': 'unread',
            'data': {'kind': 'clips_ready', 'run_id': str(run['id']), 'source_id': str(source['id'])}})
    except Exception:
        log.warning('Clip run %s notification failed', run['id'])
    try:
        import push_notifications
        push_notifications.send_to_user(str(run['created_by']), title=title, body=body[:160], nav='grow:video-clips', tag=f'clips-{run["id"]}')
    except Exception:
        log.warning('Clip run %s push failed', run['id'])


def drive(run):
    job = f'/jobs/{run["id"]}'
    source = media_library.read(f'/media_assets?id=eq.{media_library.key(run["source_id"])}&select=*&limit=1')
    if not source or source[0]['status'] != 'ready' or source[0].get('source_removed_at'):
        raise RunFailed('The recording is no longer available.')
    source = source[0]
    state = clipper('GET', job)
    if state.status_code == 404:
        url = storage_links.signed_url_sync(BUCKET, media_library.object_path(source), ttl=3 * 3600)
        if not url:
            raise RunFailed('The recording could not be opened. Try again.')
        started = clipper('POST', job, json={'source_url': url, 'options': engine_options(run['options'])})
        if started.status_code == 409:
            raise RunFailed('The clip service is busy. Try again in a few minutes.')
        if started.status_code >= 400:
            raise RunFailed('The clip service could not take this recording. Try again.')
    elif state.status_code != 200:
        raise RunFailed('The clip service is unavailable. Try again.')
    while True:
        response = clipper('GET', job)
        if response.status_code == 404:
            raise RunFailed('The clip service restarted during this run. Try again.')
        status = response.json()
        if status['status'] == 'completed':
            result = status.get('result') or {}
            filed = file_clips(run, source, result)
            units = units_for(run)
            flagged = sum(1 for c in result.get('clips') or [] if c.get('empty_spots'))
            # Completed first, then the charge: a crash in between can lose a
            # charge but can never bill a resumed run twice.
            report(run, status='completed', stage='done', percent=100, clips_done=filed, clips_total=filed,
                   counts=result.get('counts'), cost=result.get('cost'), timings=result.get('timings'), units=units,
                   finished_at=_z(datetime.now(timezone.utc)))
            meter(run, result, units)
            notify(run, source, filed, flagged)
            return
        if status['status'] in ('failed', 'cancelled'):
            raise RunFailed((status.get('error') or {}).get('message') or 'Finding clips failed. Try again.')
        report(run, stage=status.get('stage') or 'working', percent=status.get('percent') or 0,
               clips_done=status.get('clips_done') or 0, clips_total=status.get('clips_total') or 0)
        time.sleep(POLL_SECONDS)


def forget_job(run):
    try:
        clipper('DELETE', f'/jobs/{run["id"]}')
    except httpx.HTTPError:
        log.warning('Clip service job %s was not deleted', run['id'])


def work_once():
    if not enabled():
        return False
    claimed = sb_clients.sb_post_as_service('/rpc/claim_clip_run', {})
    if not claimed:
        return False
    run = media_library.one(claimed)
    if not run.get('id'):
        return False
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(25):
            try:
                sb_clients.sb_patch_as_service(fence(run), {'lease_until': lease()})
            except Exception:
                log.warning('Clip run heartbeat could not renew')
    beat = threading.Thread(target=heartbeat, daemon=True)
    beat.start()
    try:
        drive(run)
        forget_job(run)
    except Cancelled:
        log.info('Clip run cancelled: %s', run['id'])
        forget_job(run)
    except RunFailed as error:
        sb_clients.sb_patch_as_service(fence(run), {'status': 'failed', 'stage': 'failed', 'error': str(error)[:600],
                                                    'finished_at': _z(datetime.now(timezone.utc))})
        forget_job(run)
    except Exception:
        # Leave the lease to lapse: the next claim resumes the same clip-service job.
        log.exception('Clip run %s stopped; it will resume', run['id'])
    finally:
        stop.set()
        beat.join(timeout=2)
    return True


async def tick():
    if not enabled():
        return
    import asyncio
    await asyncio.to_thread(work_once)


# ── keeping storage tidy (Kevin's rules, 2026-10-05) ─────────────────

def sweep():
    """Recordings go 7 days after their clips were made; skipped clips go
    after 30 days; uploads abandoned for a day are removed."""
    now = datetime.now(timezone.utc)
    for row in media_library.read(f'/media_assets?status=eq.uploading&created_at=lt.{_z(now - timedelta(days=1))}&select=id,business_id,kind&limit=200'):
        remove_objects([media_library.object_path(row)])
        sb_clients.sb_delete_as_service(f'/media_assets?id=eq.{row["id"]}&status=eq.uploading')
    for row in media_library.read(f'/media_assets?kind=eq.clip&decision=eq.skipped&decided_at=lt.{_z(now - timedelta(days=30))}&select=id,business_id,kind&limit=200'):
        remove_objects([media_library.object_path(row), poster_path(row), frame_path(row), face_path(row), face_path(row, 2), face_path(row, 3)])
        sb_clients.sb_delete_as_service(f'/media_assets?id=eq.{row["id"]}&decision=eq.skipped')
    done = media_library.read(f'/media_clip_runs?status=eq.completed&finished_at=lt.{_z(now - timedelta(days=7))}&select=source_id&limit=500')
    for source_id in {r['source_id'] for r in done}:
        if media_library.read(f'/media_clip_runs?source_id=eq.{source_id}&status=in.(queued,working)&select=id&limit=1'):
            continue
        rows = media_library.read(f'/media_assets?id=eq.{source_id}&kind=eq.source&source_removed_at=is.null&select=id,business_id,kind&limit=1')
        if rows:
            remove_objects([media_library.object_path(rows[0])])
            sb_clients.sb_patch_as_service(f'/media_assets?id=eq.{source_id}&source_removed_at=is.null', {'source_removed_at': _z(now)})


async def sweep_tick():
    if os.getenv('CLIP_FINDER', 'off') != 'on':
        return
    import asyncio
    await asyncio.to_thread(sweep)
