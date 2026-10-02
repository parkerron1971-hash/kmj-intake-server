import io
import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import media_library as media

BIZ, SOURCE, CLIP, OWNER = [f'00000000-0000-4000-8000-{i:012d}' for i in range(1, 5)]
USER = SimpleNamespace(id=OWNER, email='test@example.test')


def clip(**changes):
    return media.Clip(source_id=SOURCE, name='Synthetic clip', start_seconds=1, end_seconds=7,
                      caption='Synthetic recording', destination='Review account', **changes)


@pytest.mark.parametrize('start,end', [(0, 4), (0, 91), (8, 2), (-1, 9), (float('nan'), 10), (0, float('inf'))])
def test_clip_bounds_reject_invalid_segments(start, end):
    with pytest.raises(ValidationError):
        media.Clip(source_id=SOURCE, name='Clip', start_seconds=start, end_seconds=end, caption='', destination='Review')


def test_review_requires_all_explicit_confirmations():
    data = {'fingerprint': 'a' * 64, 'permission_note': 'Recorded authorization', 'rights_confirmed': True,
            'privacy_checked': True, 'caption_checked': True, 'destination_checked': True}
    for field in ('rights_confirmed', 'privacy_checked', 'caption_checked', 'destination_checked'):
        with pytest.raises(ValidationError):
            media.Review.model_validate(data | {field: False})


def test_secret_not_returned_in_public_row_or_export():
    row = {'id': CLIP, 'business_id': BIZ, 'kind': 'source', 'encrypted_token': 'SECRET', 'lease_id': 'SECRET'}
    assert 'SECRET' not in json.dumps(media.public(row))
    from account_lifecycle import _TABLE_SELECT, _IMPORT_SKIP
    assert 'encrypted_token' not in _TABLE_SELECT['media_assets']
    assert 'media_assets' in _IMPORT_SKIP


def test_media_grant_encryption_fails_closed_and_is_domain_separated(monkeypatch):
    monkeypatch.delenv('MEDIA_TOKEN_ENCRYPTION_KEY', raising=False)
    monkeypatch.delenv('TIN_ENCRYPTION_KEY', raising=False)
    with pytest.raises(HTTPException):
        media.crypto()
    monkeypatch.setenv('TIN_ENCRYPTION_KEY', 'synthetic-test-key')
    cipher = media.crypto().encrypt(b'private-drive-grant')
    assert b'private-drive-grant' not in cipher
    assert media.crypto().decrypt(cipher) == b'private-drive-grant'


def test_changed_caption_destination_or_video_invalidates_fingerprint():
    row = {'id': CLIP, 'source_id': SOURCE, 'sha256': 'a' * 64, 'configuration': clip().model_dump(mode='json')}
    original = media.fingerprint(row)
    for key, value in [('caption', 'Different caption'), ('destination', 'Different account'), ('start_seconds', 2)]:
        changed = deepcopy(row)
        changed['configuration'][key] = value
        assert media.fingerprint(changed) != original
    assert media.fingerprint(row | {'sha256': 'b' * 64}) != original


def test_denied_user_never_reads_media_store(monkeypatch):
    import business_users_router
    def deny(*a):
        raise HTTPException(403, 'Denied')
    monkeypatch.setattr(business_users_router, 'require_role', deny)
    monkeypatch.setattr(media, 'read', lambda *a: pytest.fail('Unauthorized media read'))
    with pytest.raises(HTTPException):
        media.asset(BIZ, CLIP, USER)


def test_asset_lookup_is_business_scoped(monkeypatch):
    monkeypatch.setattr(media, 'access', lambda *a: None)
    def read(path):
        assert f'business_id=eq.{BIZ}' in path and f'id=eq.{CLIP}' in path
        return []
    monkeypatch.setattr(media, 'read', read)
    with pytest.raises(HTTPException) as exc:
        media.asset(BIZ, CLIP, USER)
    assert exc.value.status_code == 404


def test_unreviewed_download_cannot_create_storage_link(monkeypatch):
    row = {'id': CLIP, 'kind': 'clip', 'status': 'ready', 'configuration': {}, 'approval': None}
    monkeypatch.setattr(media, 'asset', lambda *a: row)
    monkeypatch.setattr(media.storage_links, 'signed_url_sync', lambda *a, **k: pytest.fail('Unreviewed handoff signed'))
    with pytest.raises(HTTPException) as exc:
        media.playback(BIZ, CLIP, USER, reviewed=True)
    assert exc.value.status_code == 409


def test_bounded_download_refuses_oversized_body(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'x' * 11))
    with httpx.Client(transport=transport) as client, pytest.raises(ValueError, match='size or time'):
        media.transfer_to_file(client, 'https://example.test/fixture', {}, tmp_path / 'source', maximum=10)


def test_failed_job_erases_drive_secret_and_does_not_return_provider_error(monkeypatch):
    row = {'id': SOURCE, 'business_id': BIZ, 'lease_id': CLIP}
    monkeypatch.setattr(media, 'configuration', lambda: {'processing_available': True})
    monkeypatch.setattr(media.sb_clients, 'sb_post_as_service', lambda *a: row)
    def fail(*a):
        raise RuntimeError('Secret provider grant must not leak')
    monkeypatch.setattr(media, 'process', fail)
    writes = []
    monkeypatch.setattr(media.sb_clients, 'sb_patch_as_service', lambda path, body: writes.append((path, body)))
    media.work_once()
    assert writes[0][1]['encrypted_token'] is None
    assert writes[0][1]['status'] == 'failed'
    assert 'Secret provider' not in writes[0][1]['error']
    assert f'lease_id=eq.{CLIP}' in writes[0][0]


@pytest.mark.parametrize('case,expected', [('valid', None), ('wrong_app', 403), ('broad_scope', 403), ('download_denied', 422), ('oversized', 422)])
def test_drive_import_checks_grant_and_file_before_queuing(monkeypatch, case, expected):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'configured-client')
    monkeypatch.setenv('TIN_ENCRYPTION_KEY', 'synthetic-key')
    monkeypatch.delenv('MEDIA_TOKEN_ENCRYPTION_KEY', raising=False)
    monkeypatch.setattr(media, 'access', lambda *a: None)
    monkeypatch.setattr(media, 'configuration', lambda: {'drive_configured': True})
    grant = {'aud': 'wrong' if case == 'wrong_app' else 'configured-client', 'scope': media.DRIVE_SCOPE + (' extra-scope' if case == 'broad_scope' else '')}
    file = {'name': 'Synthetic recording', 'mimeType': 'video/mp4', 'size': media.MAX_BYTES + 1 if case == 'oversized' else 100,
            'version': '42', 'capabilities': {'canDownload': case != 'download_denied'}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=grant if request.url.path.endswith('tokeninfo') else file))
    client_type = httpx.Client
    monkeypatch.setattr(media.httpx, 'Client', lambda **kwargs: client_type(transport=transport))
    queued = []
    monkeypatch.setattr(media, 'enqueue', lambda business, user, data: queued.append(data) or {'id': SOURCE})
    body = media.DriveImport(file_id='selected_file_123', access_token='synthetic-access-grant-only', permission_note='Synthetic permission record', authorized_to_copy=True)
    if expected:
        with pytest.raises(HTTPException) as exc:
            media.import_drive(BIZ, body, USER)
        assert exc.value.status_code == expected
        assert not queued
    else:
        assert media.import_drive(BIZ, body, USER) == {'id': SOURCE}
        assert queued[0]['source_version'] == '42'
        assert 'synthetic-access-grant-only' not in json.dumps(queued)
        assert media.crypto().decrypt(queued[0]['encrypted_token'].encode()) == b'synthetic-access-grant-only'


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg integration tool unavailable')
def test_real_clip_render_preserves_duration_and_vertical_canvas(tmp_path):
    source, target = tmp_path / 'source.mp4', tmp_path / 'clip.mp4'
    subprocess.run([shutil.which('ffmpeg'), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
        'testsrc2=size=320x240:rate=15', '-t', '8', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True, timeout=30)
    media.render_clip(source, target, clip().model_dump(mode='json'))
    assert abs(media.probe(target) - 6) < .1
    result = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-show_entries', 'stream=width,height', '-of', 'json', str(target)], capture_output=True, check=True)
    stream = json.loads(result.stdout)['streams'][0]
    assert (stream['width'], stream['height']) == (720, 1280)
