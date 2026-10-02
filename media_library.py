"""Private selected-file imports and deterministic, reviewed clip handoffs.

No media is sent to an AI model or social provider by this module. Drive grants
are short-lived, encrypted, excluded from export, and erased when work finishes.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Literal
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from pydantic import Field, SecretStr, model_validator

import sb_clients
import storage_links
from program_outcomes import StrictModel

log = logging.getLogger(__name__)
BUCKET = 'program-media'
MAX_BYTES = 1024 ** 3
MAX_SECONDS = 7200
DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.file'
PUBLIC_COLUMNS = 'id,business_id,kind,source_id,name,status,configuration,drive_file_id,source_version,byte_size,duration_seconds,sha256,error,created_by,created_at,finished_at,approval'


class DriveImport(StrictModel):
    file_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{10,200}$')
    access_token: SecretStr
    permission_note: str = Field(min_length=10, max_length=1000)
    authorized_to_copy: Literal[True]


class Clip(StrictModel):
    source_id: UUID
    name: str = Field(min_length=1, max_length=160)
    start_seconds: float = Field(ge=0, le=MAX_SECONDS, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, le=MAX_SECONDS, allow_inf_nan=False)
    caption: str = Field(max_length=3000)
    destination: str = Field(min_length=3, max_length=200)

    @model_validator(mode='after')
    def duration(self):
        if not 5 <= self.end_seconds - self.start_seconds <= 90:
            raise ValueError('Choose a clip between 5 and 90 seconds long.')
        return self


class Review(StrictModel):
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    permission_note: str = Field(min_length=10, max_length=1000)
    rights_confirmed: Literal[True]
    privacy_checked: Literal[True]
    caption_checked: Literal[True]
    destination_checked: Literal[True]


def key(value):
    return str(UUID(str(value)))


def access(business_id, user, minimum='manager'):
    from business_users_router import require_role
    return require_role(key(business_id), str(user.id), minimum)


def read(path):
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise HTTPException(503, 'The media library is unavailable.')
    return rows


def one(value):
    value = value[0] if isinstance(value, list) and value else value
    if not isinstance(value, dict) or not value:
        raise HTTPException(503, 'The media change could not be confirmed.')
    return value


def crypto():
    from cryptography.fernet import Fernet
    root = os.environ.get('MEDIA_TOKEN_ENCRYPTION_KEY')
    if root:
        return Fernet(root.encode())
    # Domain separation from the existing runtime-only TIN key; never plaintext.
    root = os.environ.get('TIN_ENCRYPTION_KEY')
    if not root:
        raise HTTPException(503, 'Private media processing is not configured.')
    derived = hmac.new(root.encode(), b'solutionist-media-token-v1', hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def configuration():
    configured = bool(os.environ.get('GOOGLE_CLIENT_ID') and os.environ.get('GOOGLE_PICKER_API_KEY') and os.environ.get('GOOGLE_CLOUD_PROJECT_NUMBER'))
    return {'drive_configured': configured,
            'client_id': os.environ.get('GOOGLE_CLIENT_ID') if configured else None,
            'picker_key': os.environ.get('GOOGLE_PICKER_API_KEY') if configured else None,
            'project_number': os.environ.get('GOOGLE_CLOUD_PROJECT_NUMBER') if configured else None,
            'processing_available': bool(shutil.which('ffmpeg') and shutil.which('ffprobe') and os.environ.get('MEDIA_PROCESSING') == 'on'),
            'max_file_bytes': MAX_BYTES, 'max_recording_seconds': MAX_SECONDS,
            'clip_min_seconds': 5, 'clip_max_seconds': 90, 'automatic_publishing': False}


def public(row):
    result = {k: row.get(k) for k in PUBLIC_COLUMNS.split(',')}
    if row.get('kind') == 'clip' and row.get('status') == 'ready':
        result['fingerprint'] = fingerprint(row)
    return result


def asset(business_id, asset_id, user):
    access(business_id, user)
    rows = read(f'/media_assets?id=eq.{key(asset_id)}&business_id=eq.{key(business_id)}&select=*&limit=1')
    if not rows:
        raise HTTPException(404, 'Media item not found.')
    return rows[0]


def fingerprint(row):
    content = {k: row.get(k) for k in ('id', 'source_id', 'sha256', 'configuration')}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def enqueue(business_id, user, data):
    access(business_id, user)
    if not configuration()['processing_available']:
        raise HTTPException(503, 'Video processing is not configured yet.')
    row = one(sb_clients.sb_post_as_service('/rpc/enqueue_media_asset', {
        'p_business_id': key(business_id), 'p_actor_id': str(user.id), 'p_asset': data}))
    if row.get('refused'):
        raise HTTPException(409, row['refused'])
    audit(business_id, user, 'queue', row['id'])
    return public(row)


def import_drive(business_id, body, user):
    access(business_id, user)
    if not configuration()['drive_configured']:
        raise HTTPException(503, 'Google Drive selection is not configured yet.')
    token = body.access_token.get_secret_value()
    if not 20 <= len(token) <= 4096:
        raise HTTPException(422, 'Select the file from Google Drive again.')
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        check = client.get('https://oauth2.googleapis.com/tokeninfo', params={'access_token': token})
        if check.status_code != 200:
            raise HTTPException(403, 'Google authorization expired. Select the file again.')
        grant = check.json()
        if grant.get('aud') != os.environ.get('GOOGLE_CLIENT_ID') or set(grant.get('scope', '').split()) != {DRIVE_SCOPE}:
            raise HTTPException(403, 'Use the selected-file Google Drive connection for this application.')
        response = client.get('https://www.googleapis.com/drive/v3/files/' + body.file_id,
            params={'fields': 'id,name,mimeType,size,version,capabilities(canDownload),trashed', 'supportsAllDrives': 'true'},
            headers={'Authorization': 'Bearer ' + token})
        if response.status_code != 200:
            raise HTTPException(403, 'This selected Drive file is not available.')
        file = response.json()
    size = int(file.get('size') or 0)
    if file.get('trashed') or not file.get('capabilities', {}).get('canDownload') or file.get('mimeType') not in ('video/mp4', 'video/quicktime', 'video/webm') or not 0 < size <= MAX_BYTES:
        raise HTTPException(422, 'Choose a downloadable MP4, MOV or WebM recording up to 1 GB.')
    secret = crypto().encrypt(token.encode()).decode()
    return enqueue(business_id, user, {'kind': 'source', 'name': str(file.get('name') or 'Recording')[:160],
        'drive_file_id': body.file_id, 'source_version': str(file.get('version')),
        'byte_size': size, 'encrypted_token': secret,
        'configuration': {'permission_note': body.permission_note, 'authorized_to_copy': True, 'mime_type': file['mimeType']}})


def create_clip(business_id, body, user):
    source = asset(business_id, body.source_id, user)
    if source['kind'] != 'source' or source['status'] != 'ready':
        raise HTTPException(409, 'Wait for the recording to finish importing.')
    if body.end_seconds > float(source['duration_seconds']):
        raise HTTPException(422, 'The clip ends after the recording ends.')
    return enqueue(business_id, user, {'kind': 'clip', 'name': body.name, 'source_id': str(body.source_id),
        'byte_size': 0, 'configuration': body.model_dump(mode='json')})


def approve(business_id, asset_id, body, user):
    row = asset(business_id, asset_id, user)
    if row['kind'] != 'clip' or row['status'] != 'ready' or fingerprint(row) != body.fingerprint:
        raise HTTPException(409, 'Review this finished clip and its current caption and destination first.')
    if row.get('approval'):
        return public(row)
    approval = body.model_dump() | {'by': str(user.id), 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    result = one(sb_clients.sb_patch_as_service(f'/media_assets?id=eq.{key(asset_id)}&business_id=eq.{key(business_id)}&status=eq.ready', {'approval': approval}))
    audit(business_id, user, 'approve', asset_id)
    return public(result)


def audit(business_id, user, action, asset_id):
    import audit_log
    audit_log.record(str(business_id), actor_type='user', actor_id=str(user.id), verb='media_' + action,
                     ok=True, summary='Private media ' + action, payload={'asset_id': str(asset_id)}, source='media_library')


def playback(business_id, asset_id, user, reviewed=False):
    row = asset(business_id, asset_id, user)
    if row['status'] != 'ready':
        raise HTTPException(409, 'This recording is not ready.')
    if reviewed and (row['kind'] != 'clip' or (row.get('approval') or {}).get('fingerprint') != fingerprint(row)):
        raise HTTPException(409, 'Approve this exact clip before creating a reviewed handoff.')
    url = storage_links.signed_url_sync(BUCKET, object_path(row), ttl=900,
                                       download_as='reviewed-clip.mp4' if reviewed else None)
    if not url:
        raise HTTPException(503, 'The private media link could not be created.')
    audit(business_id, user, 'download' if reviewed else 'preview', asset_id)
    return {'url': url, 'expires_in': 900, 'caption': (row.get('configuration') or {}).get('caption', ''),
            'destination': (row.get('configuration') or {}).get('destination', '')}


def object_path(row):
    return key(row['business_id']) + '/' + key(row['id']) + ('.mp4' if row['kind'] == 'clip' else '.source')


def transfer_to_file(client, url, headers, target, maximum=MAX_BYTES):
    count, deadline = 0, time.monotonic() + 600
    with client.stream('GET', url, headers=headers) as response:
        if response.status_code != 200:
            raise ValueError('The recording could not be downloaded. Select the source again.')
        with target.open('wb') as dest:
            for chunk in response.iter_bytes(1024 * 1024):
                count += len(chunk)
                if count > maximum or time.monotonic() > deadline:
                    raise ValueError('The source exceeded the download size or time limit.')
                dest.write(chunk)
    return count


def upload_chunks(content):
    deadline = time.monotonic() + 600
    while chunk := content.read(1024 * 1024):
        if time.monotonic() > deadline:
            raise ValueError('Saving the media exceeded the time limit. Try again later.')
        yield chunk


def probe(path):
    result = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-protocol_whitelist', 'file,pipe',
        '-format_whitelist', 'mov,matroska,webm', '-show_entries', 'format=duration:stream=codec_type,width,height',
        '-of', 'json', str(path)], capture_output=True, timeout=30, check=True)
    data = json.loads(result.stdout)
    duration = float(data['format']['duration'])
    videos = [s for s in data.get('streams', []) if s.get('codec_type') == 'video']
    if not 0 < duration <= MAX_SECONDS or not videos or any(int(s.get('width', 0)) * int(s.get('height', 0)) > 3840 * 2160 for s in videos):
        raise ValueError('Use a recording up to two hours and 4K resolution.')
    return duration


def render_clip(source, target, config):
    clip = Clip.model_validate(config)
    args = [shutil.which('ffmpeg'), '-nostdin', '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe',
        '-format_whitelist', 'mov,matroska,webm', '-ss', str(clip.start_seconds), '-i', str(source),
        '-t', str(clip.end_seconds - clip.start_seconds), '-map', '0:v:0', '-map', '0:a:0?',
        '-map_metadata', '-1', '-map_chapters', '-1', '-vf',
        'scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-threads', '2', '-r', '30',
        '-c:a', 'aac', '-b:a', '128k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-fs', str(100 * 1024 ** 2), str(target)]
    subprocess.run(args, capture_output=True, check=True, timeout=480)
    actual = probe(target)
    if abs(actual - (clip.end_seconds - clip.start_seconds)) > 1.0:
        raise ValueError('The rendered clip was incomplete. Choose a shorter segment.')


def process(row):
    from auth_supabase import AuthedUser
    user = AuthedUser(id=str(row['created_by']), email='', role='authenticated')
    access(row['business_id'], user)
    with tempfile.TemporaryDirectory(prefix='solutionist-media-') as folder:
        source = Path(folder) / 'source.bin'
        with httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=False) as client:
            if row['kind'] == 'source':
                token = crypto().decrypt(row['encrypted_token'].encode(), ttl=3600).decode()
                headers = {'Authorization': 'Bearer ' + token}
                endpoint = 'https://www.googleapis.com/drive/v3/files/' + row['drive_file_id']
                before = client.get(endpoint, headers=headers, params={'fields': 'version,size', 'supportsAllDrives': 'true'})
                if before.status_code != 200 or str(before.json().get('version')) != row['source_version']:
                    raise ValueError('The Drive recording changed. Select it again.')
                size = transfer_to_file(client, endpoint + '?alt=media&supportsAllDrives=true', headers, source)
                after = client.get(endpoint, headers=headers, params={'fields': 'version', 'supportsAllDrives': 'true'})
                if after.status_code != 200 or str(after.json().get('version')) != row['source_version'] or size != row['byte_size']:
                    raise ValueError('The Drive recording changed during import. Select it again.')
                output = source
                duration = probe(source)
            else:
                parent = asset(row['business_id'], row['source_id'], user)
                url = storage_links.signed_url_sync(BUCKET, object_path(parent), ttl=900)
                if not url:
                    raise ValueError('The source recording is unavailable.')
                transfer_to_file(client, url, {}, source)
                with source.open('rb') as content:
                    if hashlib.file_digest(content, 'sha256').hexdigest() != parent['sha256']:
                        raise ValueError('The source recording checksum did not match.')
                output = Path(folder) / 'clip.mp4'
                render_clip(source, output, row['configuration'])
                duration = probe(output)
            access(row['business_id'], user)
            with output.open('rb') as content:
                checksum = hashlib.file_digest(content, 'sha256').hexdigest()
                content.seek(0)
                response = client.post(os.environ['SUPABASE_URL'].rstrip('/') + '/storage/v1/object/' + BUCKET + '/' + object_path(row),
                    headers={**storage_links.service_headers(), 'Content-Type': row['configuration'].get('mime_type', 'video/mp4'), 'Content-Length': str(output.stat().st_size), 'x-upsert': 'false'}, content=upload_chunks(content))
            if response.status_code >= 400:
                raise ValueError('The processed recording could not be saved.')
            return {'status': 'ready', 'duration_seconds': duration, 'sha256': checksum, 'byte_size': output.stat().st_size}


def work_once():
    if not configuration()['processing_available']:
        return
    claimed = sb_clients.sb_post_as_service('/rpc/claim_media_asset', {})
    if not claimed:
        return
    row = one(claimed)
    if not row.get('id'):
        return
    try:
        result = process(row)
    except Exception as exc:
        # Never persist provider URLs, grants, or raw stderr into user-visible jobs.
        log.warning('Media processing failed (%s): %s', row['id'], type(exc).__name__)
        result = {'status': 'failed', 'error': str(exc)[:240] if isinstance(exc, ValueError) else 'Processing was interrupted or the source was unavailable. Select the file or create the clip again.'}
    result.update(encrypted_token=None, finished_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    sb_clients.sb_patch_as_service(f'/media_assets?id=eq.{key(row["id"])}&status=eq.processing&lease_id=eq.{key(row["lease_id"])}', result)


async def tick():
    if os.environ.get('MEDIA_PROCESSING', 'off') != 'on':
        return
    await asyncio.to_thread(work_once)
