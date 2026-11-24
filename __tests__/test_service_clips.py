"""Clips from a service streamed through Solutionist (service_clips.py, and
its seams in clip_finder, media_library, clip_covers and church_storage).
The database, the bucket, the relay's playlist and the clip service are
fakes."""
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import clip_finder as cf
import media_library as media
import recording_copy
import service_clips as svc
import stream_relay_router as sr

from test_clip_finder import BIZ, OWNER, RUN, RESULT, USER, Store, completed, gates, on, worker  # noqa: F401

SID = 'aaaaaaaa-0000-4000-8000-000000000001'
SERMON = 'bbbbbbbb-0000-4000-8000-000000000002'
SOURCE = svc.source_id_for(SID)
NOW = datetime(2026, 11, 24, 18, 0, tzinfo=timezone.utc)
BUCKET = 'https://acct.r2.cloudflarestorage.com'


def session(**changes):
    return {'id': SID, 'business_id': BIZ, 'status': 'ended', 'bytes': 3 * 1024 ** 3, 'duration_s': 5400.0,
            'started_at': '2026-11-22T15:58:00Z', 'ended_at': '2026-11-22T17:28:00Z', 'sermon_id': SERMON,
            'playlist_path': None, 'removed_at': None, 'copy_state': 'ready', 'copy_bytes': 900_000_000,
            'full_removed_at': None} | changes


def service_source(**changes):
    return {'id': SOURCE, 'business_id': BIZ, 'kind': 'source', 'status': 'ready', 'duration_seconds': 5400.0,
            'name': 'The River (service, Sunday, November 22)', 'source_removed_at': None,
            'configuration': {'origin': 'service', 'stream_session_id': SID}} | changes


def playlist(segments=6, seconds=4.0, resume_at=3):
    lines = ['#EXTM3U', '#EXT-X-VERSION:3', '#EXT-X-TARGETDURATION:4', '#EXT-X-PLAYLIST-TYPE:EVENT',
             '#EXT-X-MEDIA-SEQUENCE:0']
    for i in range(segments):
        if i == resume_at:
            lines.append('#EXT-X-DISCONTINUITY')
        lines += [f'#EXTINF:{seconds:.6f},', f'seg_{i:06d}.ts']
    return '\n'.join(lines) + '\n'


@pytest.fixture
def relay(monkeypatch, on):
    """The relay's rows, playlist and signed links."""
    monkeypatch.setenv('SERVICE_CLIPS', 'on')
    state = SimpleNamespace(session=session(), playlist=playlist(), sermon=[{'title': 'The River'}], gets=[])

    def get(path):
        state.gets.append(path)
        if path.startswith('/stream_sessions'):
            return [state.session] if state.session else []
        if path.startswith('/sermons'):
            return state.sermon
        return []
    monkeypatch.setattr(svc.sb_clients, 'sb_get_as_service', get)
    monkeypatch.setattr(recording_copy, 'copy_columns', lambda: True)
    monkeypatch.setattr(sr, '_playlist_text', lambda s: state.playlist)
    monkeypatch.setattr(sr, 'r2_link', lambda key, expires=0, **k: f'{BUCKET}/media/{key}?X-Amz-Expires={expires}')
    monkeypatch.setattr(sr, '_church_tz', lambda biz: ZoneInfo('America/Detroit'))
    return state


# ── adding a service to Video Clips ──────────────────────────────────

def test_a_service_becomes_one_recording_in_video_clips(monkeypatch, relay):
    rows = []
    store = Store(monkeypatch, reads=lambda path: list(rows))
    made = svc.add_service(BIZ, SID, USER)
    path, body = store.posts[0]
    assert path == '/media_assets' and body['id'] == SOURCE == str(uuid5(svc.NAMESPACE, f'service-{SID}'))
    assert body['kind'] == 'source' and body['status'] == 'ready' and body['byte_size'] == 0
    assert body['duration_seconds'] == 5400.0 and body['created_by'] == OWNER
    assert body['configuration']['origin'] == 'service' and body['configuration']['stream_session_id'] == SID
    assert body['name'] == 'The River (service, Sunday, November 22)'          # the church's own clock
    assert made['id'] == SOURCE
    # Pressed again: the same row, nothing new written.
    rows.append(dict(body))
    assert svc.add_service(BIZ, SID.upper(), USER)['id'] == SOURCE and len(store.posts) == 1


def test_a_service_without_a_sermon_is_named_by_its_day(monkeypatch, relay):
    relay.session = session(sermon_id=None)
    store = Store(monkeypatch)
    svc.add_service(BIZ, SID, USER)
    assert store.posts[0][1]['name'] == 'Service, Sunday, November 22'


def test_two_presses_at_once_find_the_row_the_other_made(monkeypatch, relay):
    reads = iter([[], [service_source()]])
    Store(monkeypatch, reads=lambda path: next(reads), post=lambda path, body: None)
    assert svc.add_service(BIZ, SID, USER)['id'] == SOURCE


@pytest.mark.parametrize('row, code, words', [
    (None, 404, "isn't in this church's recordings"),
    (session(status='live', ended_at=None), 409, 'still live'),
    (session(removed_at='2026-11-23T00:00:00Z'), 409, 'was deleted'),
    (session(duration_s=0), 409, 'no recording'),
    (session(full_removed_at='2026-11-20T00:00:00Z', copy_state='failed', copy_bytes=None), 409, "isn't available"),
])
def test_only_an_ended_kept_service_can_be_added(monkeypatch, relay, row, code, words):
    relay.session = row
    store = Store(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        svc.add_service(BIZ, SID, USER)
    assert caught.value.status_code == code and words in caught.value.detail and not store.posts


def test_adding_a_service_follows_the_clip_switches(monkeypatch, relay):
    store = Store(monkeypatch)
    monkeypatch.setenv('SERVICE_CLIPS', 'off')
    with pytest.raises(HTTPException) as caught:
        svc.add_service(BIZ, SID, USER)
    assert caught.value.status_code == 503
    monkeypatch.setenv('SERVICE_CLIPS', 'on')
    monkeypatch.setenv('CLIP_FINDER', 'off')
    with pytest.raises(HTTPException):
        svc.add_service(BIZ, SID, USER)
    assert not store.posts


def test_another_churchs_service_is_never_read(monkeypatch, relay):
    Store(monkeypatch)
    svc.add_service(BIZ, SID, USER)
    reads = [p for p in relay.gets if p.startswith('/stream_sessions')]
    assert reads and all(f'business_id=eq.{BIZ}' in p and f'id=eq.{SID}' in p for p in reads)
    assert svc.read_session(BIZ, 'not-a-uuid') is None


def test_the_screen_is_told_when_services_can_be_clipped(monkeypatch, on):
    monkeypatch.setattr(cf, 'plan_allows', lambda biz: True)
    monkeypatch.setattr(cf, 'seconds_this_month', lambda biz: 0.0)
    monkeypatch.setattr(cf, 'cover_offer', lambda: {'available': False})
    import member_asks
    platform = {BIZ: False}
    monkeypatch.setattr(member_asks, 'platform_church', lambda biz: platform[biz])
    monkeypatch.delenv('SERVICE_CLIPS', raising=False)
    # Ships as owner: only the platform owner's church sees the button.
    assert svc.mode() == 'owner' and cf.configuration(BIZ)['services'] is False
    platform[BIZ] = True
    assert cf.configuration(BIZ)['services'] is True
    monkeypatch.setenv('SERVICE_CLIPS', 'off')
    assert cf.configuration(BIZ)['services'] is False
    monkeypatch.setenv('SERVICE_CLIPS', 'on')
    platform[BIZ] = False
    assert cf.configuration(BIZ)['services'] is True
    monkeypatch.setenv('SERVICE_CLIPS', 'sideways')
    assert svc.mode() == 'off'


# ── the stretch ──────────────────────────────────────────────────────

def test_the_playlist_is_cut_to_the_whole_segments_of_the_stretch():
    # The stretch starts inside the segment the relay resumed with.
    cut, offset, seconds = svc.cut_playlist(playlist(), 13.0, 20.0)
    lines = cut.splitlines()
    assert [l for l in lines if l.startswith('seg_')] == ['seg_000003.ts', 'seg_000004.ts']
    assert offset == 12.0 and seconds == 8.0
    assert lines[0] == '#EXTM3U' and lines[-1] == '#EXT-X-ENDLIST'
    # Nothing comes before the first segment now, so it carries no resume tag;
    # the playlist says nothing that would make ffmpeg read it as live.
    assert '#EXT-X-DISCONTINUITY' not in cut and 'PLAYLIST-TYPE' not in cut and 'MEDIA-SEQUENCE' not in cut
    # A resume inside the stretch is kept.
    assert '#EXT-X-DISCONTINUITY' in svc.cut_playlist(playlist(), 4.0, 18.0)[0]
    whole, offset, seconds = svc.cut_playlist(playlist() + '#EXT-X-ENDLIST\n', 0, 24.0)
    assert offset == 0.0 and seconds == 24.0 and whole.count('#EXT-X-ENDLIST') == 1
    assert svc.cut_playlist(playlist(), 30.0, 40.0)[0] is None


@pytest.mark.parametrize('frm, to, problem', [(5400.0, None, 'starts after'), (100.0, 130.0, 'at least a minute')])
def test_a_stretch_outside_the_service_is_refused(frm, to, problem):
    with pytest.raises(HTTPException) as caught:
        svc.stretch(service_source(), frm, to)
    assert caught.value.status_code == 422 and problem in caught.value.detail
    assert svc.stretch(service_source(), 1800, 9999) == {'start': 1800.0, 'end': 5400.0, 'seconds': 3600.0}


def test_the_sermon_has_to_end_after_it_starts():
    with pytest.raises(ValueError):
        cf.FindClips(from_seconds=600, to_seconds=600)
    assert cf.FindClips(from_seconds=600).to_seconds is None


# ── starting a run on a service ──────────────────────────────────────

def test_a_run_on_a_service_counts_only_the_stretch(monkeypatch, relay, gates):
    monkeypatch.setattr(media, 'asset', lambda *a: service_source())
    store = Store(monkeypatch)
    cf.start_run(BIZ, SOURCE, cf.FindClips(from_seconds=1800, to_seconds=4500), USER)
    body = store.posts[0][1]
    assert body['source_seconds'] == 2700.0
    assert body['options']['from_seconds'] == 1800 and body['options']['to_seconds'] == 4500
    assert gates['feature'] == ['ai_clips']


def test_a_service_over_two_hours_needs_the_sermons_times(monkeypatch, relay, gates):
    monkeypatch.setattr(media, 'asset', lambda *a: service_source(duration_seconds=9000.0))
    relay.session = session(duration_s=9000.0)
    store = Store(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        cf.start_run(BIZ, SOURCE, cf.FindClips(), USER)
    assert caught.value.status_code == 409 and 'where the sermon starts' in caught.value.detail
    cf.start_run(BIZ, SOURCE, cf.FindClips(from_seconds=3600, to_seconds=7200), USER)
    assert store.posts[0][1]['source_seconds'] == 3600.0


@pytest.mark.parametrize('row, words', [
    (session(removed_at='2026-11-23T00:00:00Z'), 'was deleted'),
    (session(full_removed_at='2026-11-20T00:00:00Z', copy_state=None, copy_bytes=None), "isn't available"),
])
def test_a_run_on_a_service_checks_it_is_still_there(monkeypatch, relay, gates, row, words):
    relay.session = row
    monkeypatch.setattr(media, 'asset', lambda *a: service_source())
    store = Store(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        cf.start_run(BIZ, SOURCE, cf.FindClips(), USER)
    assert caught.value.status_code == 409 and words in caught.value.detail and not store.posts


def test_a_deleted_services_row_refuses_a_run_in_its_own_words(monkeypatch, relay, gates):
    monkeypatch.setattr(media, 'asset', lambda *a: service_source(source_removed_at='2026-11-23T00:00:00Z'))
    with pytest.raises(HTTPException) as caught:
        cf.start_run(BIZ, SOURCE, cf.FindClips(), USER)
    assert "service's recording was deleted" in caught.value.detail


def test_an_upload_has_no_stretch(monkeypatch, on, gates):
    from test_clip_finder import ready_source
    monkeypatch.setattr(media, 'asset', lambda *a: ready_source())
    Store(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        cf.start_run(BIZ, ready_source()['id'], cf.FindClips(from_seconds=60), USER)
    assert caught.value.status_code == 422


# ── the worker on a service ──────────────────────────────────────────

def service_run(**options):
    return {'id': RUN, 'business_id': BIZ, 'source_id': SOURCE, 'lease_id': '00000000-0000-4000-8000-000000000009',
            'status': 'working', 'options': {'lengths': ['short'], 'caption_style': 'pop', **options},
            'source_seconds': 12.0, 'created_by': OWNER, 'attempt': 1, 'counts': None}


def test_a_run_reads_the_full_recording_from_the_bucket_and_files_clips_at_service_times(monkeypatch, relay, worker):
    import clip_finder
    monkeypatch.setattr(svc, '_now', lambda now=None: NOW)
    worker.script['GET'] = [httpx.Response(404), completed()]
    store = Store(monkeypatch, reads=lambda path: [service_source()] if f'id=eq.{SOURCE}' in path else [])
    relay.playlist = playlist(segments=30)
    cf.drive(service_run(from_seconds=10.0, to_seconds=78.0))
    post = [c for c in worker.calls if c[0] == 'POST'][0][2]
    assert 'source_url' not in post and 'offset' not in post and 'quality' not in post
    links = [l for l in post['playlist'].splitlines() if not l.startswith('#')]
    assert links == [f'{BUCKET}/media/live/{BIZ}/{SID}/seg_{i:06d}.ts?X-Amz-Expires={svc.JOB_LINK_S}' for i in range(2, 20)]
    assert post['playlist'].rstrip().endswith('#EXT-X-ENDLIST') and post['seconds'] == 72.0
    assert post['options']['durations'] == ['short']
    # The stretch's place in the service is kept on the run before the job starts…
    assert store.patches[0][1]['counts'] == {'offset': 8.0, 'quality': 'full'}
    # …and every clip is filed at its time in the whole service.
    clips = [body for path, body in store.posts if path == '/media_assets']
    assert clips[0]['configuration']['start_seconds'] == 8.0 + 396.0 and clips[0]['source_id'] == SOURCE
    final = store.patches[-1][1]
    assert final['status'] == 'completed' and final['counts']['planned'] == 2 and final['counts']['offset'] == 8.0


def test_a_resumed_service_run_files_at_the_offset_it_kept(monkeypatch, relay, worker):
    worker.script['GET'] = [completed()]
    store = Store(monkeypatch, reads=lambda path: [service_source()] if f'id=eq.{SOURCE}' in path else [])
    cf.drive(dict(service_run(), counts={'offset': 1800.0, 'quality': 'full'}))
    assert not [c for c in worker.calls if c[0] == 'POST']                   # the job was already running
    clips = [body for path, body in store.posts if path == '/media_assets']
    assert clips[0]['configuration']['start_seconds'] == 1800.0 + 396.0


def test_near_the_day_14_trim_the_copy_is_read(monkeypatch, relay, worker):
    later = datetime(2026, 12, 5, 18, 0, tzinfo=timezone.utc)                # 13 days after the service
    monkeypatch.setattr(svc, '_now', lambda now=None: later)
    worker.script['GET'] = [httpx.Response(404), completed()]
    store = Store(monkeypatch, reads=lambda path: [service_source()] if f'id=eq.{SOURCE}' in path else [])
    cf.drive(service_run(from_seconds=1800.0, to_seconds=4500.0))
    post = [c for c in worker.calls if c[0] == 'POST'][0][2]
    assert 'playlist' not in post
    assert post['recording_url'] == f'{BUCKET}/media/live/{BIZ}/{SID}/copy.mp4?X-Amz-Expires={svc.JOB_LINK_S}'
    assert (post['start'], post['end'], post['seconds']) == (1800.0, 4500.0, 2700.0)
    assert store.patches[0][1]['counts'] == {'offset': 1800.0, 'quality': 'copy'}


def test_a_stretch_too_big_for_full_quality_reads_the_copy_or_says_why(monkeypatch, relay, worker):
    monkeypatch.setattr(svc, '_now', lambda now=None: NOW)
    relay.session = session(bytes=6 * 1024 ** 3)
    worker.script['GET'] = [httpx.Response(404), completed()]
    Store(monkeypatch, reads=lambda path: [service_source()] if f'id=eq.{SOURCE}' in path else [])
    cf.drive(service_run())
    assert 'recording_url' in [c for c in worker.calls if c[0] == 'POST'][0][2]
    # No copy yet: the run fails in words, and the clip service is never asked.
    relay.session = session(bytes=6 * 1024 ** 3, copy_state='working', copy_bytes=None)
    worker.calls.clear()
    worker.script['GET'] = [httpx.Response(404)]
    with pytest.raises(cf.RunFailed) as caught:
        cf.drive(service_run())
    assert 'where the sermon starts and ends' in str(caught.value)
    assert not [c for c in worker.calls if c[0] == 'POST']


def test_a_service_deleted_before_its_run_starts_fails_the_run(monkeypatch, relay, worker):
    relay.session = session(removed_at='2026-11-23T00:00:00Z')
    worker.script['GET'] = [httpx.Response(404)]
    Store(monkeypatch, reads=lambda path: [service_source()] if f'id=eq.{SOURCE}' in path else [])
    with pytest.raises(cf.RunFailed) as caught:
        cf.drive(service_run())
    assert 'was deleted' in str(caught.value)


def test_the_sweep_never_removes_a_service(monkeypatch, on):
    removed = []
    monkeypatch.setattr(cf, 'remove_objects', lambda paths: removed.extend(paths))

    def reads(path):
        if path.startswith('/media_clip_runs?status=eq.completed'):
            return [{'source_id': SOURCE}]
        if path.startswith(f'/media_assets?id=eq.{SOURCE}'):
            return [service_source()]
        return []
    store = Store(monkeypatch, reads=reads)
    cf.sweep()
    assert not removed and not store.patches


# ── what the screen plays and cuts ───────────────────────────────────

def test_a_service_previews_its_smaller_copy_or_says_when_it_will(monkeypatch, relay):
    monkeypatch.setattr(media, 'asset', lambda *a: service_source())
    monkeypatch.setattr(media, 'audit', lambda *a: None)
    seen = media.playback(BIZ, SOURCE, USER)
    assert seen['url'] == f'{BUCKET}/media/live/{BIZ}/{SID}/copy.mp4?X-Amz-Expires=900'
    relay.session = session(copy_state='working', copy_bytes=None)
    seen = media.playback(BIZ, SOURCE, USER)
    assert seen['url'] is None and 'within the hour' in seen['note']
    with pytest.raises(HTTPException):
        media.playback(BIZ, SOURCE, USER, reviewed=True)                    # a service is never a handoff


def test_a_service_is_never_cut_by_hand(monkeypatch):
    monkeypatch.setattr(media, 'asset', lambda *a: service_source())
    body = media.Clip(source_id=SOURCE, name='A', start_seconds=10, end_seconds=40, caption='', destination='Instagram')
    with pytest.raises(HTTPException) as caught:
        media.create_clip(BIZ, body, USER)
    assert caught.value.status_code == 409 and 'download the service' in caught.value.detail


def test_a_service_clips_cover_face_reads_the_clip_itself(monkeypatch):
    import clip_covers
    asked = []
    monkeypatch.setenv('CLIPPER_URL', 'https://clipper.example.test')
    monkeypatch.setenv('CLIPPER_TOKEN', 't' * 40)
    monkeypatch.setattr(media, 'read', lambda path: [service_source()])
    monkeypatch.setattr(clip_covers.storage_links, 'signed_url_sync', lambda bucket, path, ttl=None, **k: f'https://signed/{path}')
    monkeypatch.setattr(cf, 'clipper', lambda method, path, **k: asked.append(k['json']) or httpx.Response(404, json={}))
    clip = {'id': 'cccccccc-0000-4000-8000-000000000003', 'business_id': BIZ, 'source_id': SOURCE, 'kind': 'clip',
            'duration_seconds': 30.0, 'configuration': {'start_seconds': 2196.0, 'end_seconds': 2226.0}}
    assert clip_covers.backfill_faces(clip) == 0
    # Never the service's (missing) library file: the clip, from its start.
    assert asked == [{'source_url': f'https://signed/{BIZ}/{clip["id"]}.mp4', 'start': 0.0, 'end': 30.0, 'count': 3}]


def test_deleting_the_recording_marks_its_video_clips_row(monkeypatch):
    patches = []
    monkeypatch.setattr(svc.sb_clients, 'sb_patch_as_service', lambda path, body: patches.append((path, body)) or [body])
    svc.forget_service(BIZ, SID, NOW)
    path, body = patches[0]
    assert f'id=eq.{SOURCE}' in path and f'business_id=eq.{BIZ}' in path and 'source_removed_at=is.null' in path
    assert body == {'source_removed_at': '2026-11-24T18:00:00Z'}


def test_the_route_adds_the_service_for_a_signed_in_person(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import media_library_router
    from auth_supabase import require_user
    app = FastAPI()
    app.include_router(media_library_router.router)
    app.dependency_overrides[require_user] = lambda: USER
    monkeypatch.setattr(svc, 'add_service', lambda biz, sid, user: {'id': SOURCE, 'for': str(sid), 'by': user.id})
    got = TestClient(app).post(f'/media-library/{BIZ}/services/{SID}')
    assert got.status_code == 200 and got.json()['asset'] == {'id': SOURCE, 'for': SID, 'by': OWNER}
    assert got.headers['cache-control'] == 'no-store'
    assert TestClient(app).post(f'/media-library/{BIZ}/services/not-a-uuid').status_code == 422


def test_the_screens_ask_what_they_may_offer(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import media_library_router
    from auth_supabase import require_user
    app = FastAPI()
    app.include_router(media_library_router.router)
    app.dependency_overrides[require_user] = lambda: USER
    allowed = {'ok': True}
    monkeypatch.setattr(media, 'access', lambda biz, user, *a, **k: None if allowed['ok'] else (_ for _ in ()).throw(HTTPException(403, 'No')))
    monkeypatch.setattr(cf, 'ready_for', lambda biz: True)
    monkeypatch.setenv('SERVICE_CLIPS', 'on')
    client = TestClient(app)
    assert client.get(f'/media-library/{BIZ}/services').json() == {'ok': True, 'services': True, 'clips': True}
    monkeypatch.setenv('SERVICE_CLIPS', 'off')
    assert client.get(f'/media-library/{BIZ}/services').json() == {'ok': True, 'services': False, 'clips': True}
    monkeypatch.setattr(cf, 'ready_for', lambda biz: False)
    monkeypatch.setenv('SERVICE_CLIPS', 'on')
    assert client.get(f'/media-library/{BIZ}/services').json() == {'ok': True, 'services': False, 'clips': False}
    allowed['ok'] = False
    assert client.get(f'/media-library/{BIZ}/services').status_code == 403
