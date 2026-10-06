"""Find my best clips (clip_finder.py): switches, the allowance, uploads from
a computer, starting runs, and the worker that follows a run on the clip
service and files its clips. The database, storage and clip service are fakes."""
import json
from types import SimpleNamespace
from uuid import uuid5, UUID

import httpx
import pytest
from fastapi import HTTPException

import clip_finder as cf
import media_library as media

BIZ, SOURCE, RUN, OWNER, NEW, CLIP_A, CLIP_B, CLIP_C = [f'00000000-0000-4000-8000-{i:012d}' for i in range(1, 9)]
UPLOADING, SKIPPED, OLD, BUSY = [f'00000000-0000-4000-8000-{i:012d}' for i in range(11, 15)]
USER = SimpleNamespace(id=OWNER, email='owner@example.test')
TOKEN = 't' * 40


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv('CLIP_FINDER', 'on')
    monkeypatch.setenv('CLIPPER_URL', 'https://clipper.example.test')
    monkeypatch.setenv('CLIPPER_TOKEN', TOKEN)
    monkeypatch.setenv('CLIP_FINDER_BUSINESSES', BIZ)
    monkeypatch.setenv('SUPABASE_URL', 'https://abcdefgh.supabase.co')
    monkeypatch.setattr(media, 'access', lambda *a, **k: None)
    monkeypatch.setattr(cf, 'audit', lambda *a, **k: None)


class Store:
    """Records every write; reads come from a callable."""
    def __init__(self, monkeypatch, reads=None, post=None, patch=None):
        self.posts, self.patches, self.deletes = [], [], []
        self.reads = reads or (lambda path: [])
        monkeypatch.setattr(media, 'read', lambda path: self.reads(path))
        monkeypatch.setattr(cf.sb_clients, 'sb_post_as_service', lambda path, body, *a, **k: self._post(path, body, post))
        monkeypatch.setattr(cf.sb_clients, 'sb_patch_as_service', lambda path, body: self._patch(path, body, patch))
        monkeypatch.setattr(cf.sb_clients, 'sb_delete_as_service', lambda path: self.deletes.append(path) or True)

    def _post(self, path, body, post):
        self.posts.append((path, body))
        return post(path, body) if post else [dict(body, id=body.get('id', NEW))]

    def _patch(self, path, body, patch):
        self.patches.append((path, body))
        return patch(path, body) if patch else [body]


# ── switches and the allowance ───────────────────────────────────────

def test_off_unless_switched_on_configured_and_allowed(monkeypatch, on):
    assert cf.enabled(BIZ) and cf.enabled()
    assert not cf.enabled('00000000-0000-4000-8000-999999999999')
    monkeypatch.setenv('CLIP_FINDER_BUSINESSES', '*')
    assert cf.enabled('00000000-0000-4000-8000-999999999999')
    monkeypatch.setenv('CLIPPER_TOKEN', 'short')
    assert not cf.enabled(BIZ)
    monkeypatch.setenv('CLIPPER_TOKEN', TOKEN)
    monkeypatch.setenv('CLIP_FINDER', 'off')
    assert not cf.enabled(BIZ)


@pytest.mark.parametrize('used_hours,hours,units', [
    (0, 1, 0),          # well inside the 10 included hours
    (9.5, 1, 38),       # half an hour over: ceil(0.5 * 75)
    (10, 1, 75),        # fully past the allowance
    (12, 2, 150),
    (0, 10, 0),         # exactly the allowance
])
def test_actions_are_owed_only_past_ten_hours(used_hours, hours, units):
    assert cf.extra_units(used_hours * 3600, hours * 3600) == units


def test_month_usage_counts_active_and_finished_runs_only(monkeypatch, on):
    seen = []
    Store(monkeypatch, reads=lambda path: seen.append(path) or [{'source_seconds': 3600}, {'source_seconds': 1800}])
    assert cf.seconds_this_month(BIZ) == 5400
    assert 'status=in.(queued,working,completed)' in seen[0] and f'business_id=eq.{BIZ}' in seen[0]
    assert '+00:00' not in seen[0] and 'Z&' in seen[0]


# ── uploads from a computer ──────────────────────────────────────────

def upload(**changes):
    return cf.UploadStart(**({'name': 'Sunday sermon', 'byte_size': 485_000_000, 'mime_type': 'video/mp4', 'rights_confirmed': True} | changes))


def test_upload_rules():
    with pytest.raises(Exception):
        upload(byte_size=cf.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(Exception):
        upload(mime_type='video/x-msvideo')
    with pytest.raises(Exception):
        upload(rights_confirmed=False)


def test_upload_creates_a_private_slot_on_the_storage_host(monkeypatch, on):
    store = Store(monkeypatch, reads=lambda path: [{'byte_size': 1_000_000}])
    monkeypatch.setattr(cf, 'upload_token', lambda path: 'signed-token-for-' + path)
    out = cf.start_upload(BIZ, upload(), USER)
    path, row = store.posts[0]
    assert path == '/media_assets' and row['status'] == 'uploading' and row['kind'] == 'source'
    assert row['configuration']['origin'] == 'upload' and row['configuration']['authorized_to_copy'] is True
    assert out['upload']['endpoint'] == 'https://abcdefgh.storage.supabase.co/storage/v1/upload/resumable/sign'
    assert out['upload']['chunk_size'] == 6 * 1024 * 1024 and out['upload']['bucket'] == 'program-media'
    assert out['upload']['object_name'] == f'{BIZ}/{NEW}.source' and out['upload']['token'].endswith('.source')


def test_upload_refused_when_library_is_full(monkeypatch, on):
    seen = []
    Store(monkeypatch, reads=lambda path: seen.append(path) or [{'byte_size': cf.LIBRARY_BYTES - 10}])
    with pytest.raises(HTTPException) as caught:
        cf.start_upload(BIZ, upload(), USER)
    assert caught.value.status_code == 409
    # Recordings removed by the 7-day rule free their share of the allowance.
    assert 'source_removed_at=is.null' in seen[0] and 'status=neq.failed' in seen[0]


def test_upload_token_reads_either_response_shape(monkeypatch, on):
    client_type = httpx.Client
    for body in ({'url': '/object/upload/sign/program-media/a?token=abc123'}, {'token': 'abc123'}):
        transport = httpx.MockTransport(lambda request, body=body: httpx.Response(200, json=body))
        monkeypatch.setattr(cf.httpx, 'Client', lambda transport=transport, **kw: client_type(transport=transport))
        monkeypatch.setattr(cf.storage_links, 'service_headers', lambda: {})
        assert cf.upload_token('biz/a.source') == 'abc123'


def test_finish_upload_checks_size_then_length(monkeypatch, on):
    row = {'id': SOURCE, 'business_id': BIZ, 'kind': 'source', 'status': 'uploading', 'byte_size': 100}
    monkeypatch.setattr(media, 'asset', lambda *a: row)
    monkeypatch.setattr(cf.storage_links, 'signed_url_sync', lambda *a, **k: 'https://abcdefgh.supabase.co/signed')
    store = Store(monkeypatch)
    monkeypatch.setattr(cf, 'stored_size', lambda path: 60)
    with pytest.raises(HTTPException) as caught:
        cf.finish_upload(BIZ, SOURCE, USER)
    assert caught.value.status_code == 409 and not store.patches
    monkeypatch.setattr(cf, 'stored_size', lambda path: 100)
    monkeypatch.setattr(cf, 'probe_remote', lambda url: 3760.9)
    cf.finish_upload(BIZ, SOURCE, USER)
    path, body = store.patches[0]
    assert 'status=eq.uploading' in path and body['status'] == 'ready' and body['duration_seconds'] == 3760.9


def test_a_file_that_is_not_a_video_is_removed(monkeypatch, on):
    row = {'id': SOURCE, 'business_id': BIZ, 'kind': 'source', 'status': 'uploading', 'byte_size': 100}
    monkeypatch.setattr(media, 'asset', lambda *a: row)
    monkeypatch.setattr(cf, 'stored_size', lambda path: 100)
    monkeypatch.setattr(cf.storage_links, 'signed_url_sync', lambda *a, **k: 'https://abcdefgh.supabase.co/signed')
    removed = []
    monkeypatch.setattr(cf, 'remove_objects', lambda paths: removed.extend(paths))
    def bad(url):
        raise HTTPException(422, "That file isn't a video we can read.")
    monkeypatch.setattr(cf, 'probe_remote', bad)
    store = Store(monkeypatch)
    with pytest.raises(HTTPException):
        cf.finish_upload(BIZ, SOURCE, USER)
    assert removed == [f'{BIZ}/{SOURCE}.source'] and store.deletes and not store.patches


def test_a_check_that_could_not_run_keeps_the_upload(monkeypatch, on):
    row = {'id': SOURCE, 'business_id': BIZ, 'kind': 'source', 'status': 'uploading', 'byte_size': 100}
    monkeypatch.setattr(media, 'asset', lambda *a: row)
    monkeypatch.setattr(cf, 'stored_size', lambda path: 100)
    monkeypatch.setattr(cf.storage_links, 'signed_url_sync', lambda *a, **k: 'https://abcdefgh.supabase.co/signed')
    monkeypatch.setattr(cf, 'remove_objects', lambda paths: pytest.fail('a good upload was deleted'))
    def slow(url):
        raise HTTPException(503, 'Checking the recording took too long. Try again in a minute.')
    monkeypatch.setattr(cf, 'probe_remote', slow)
    store = Store(monkeypatch)
    with pytest.raises(HTTPException) as caught:
        cf.finish_upload(BIZ, SOURCE, USER)
    assert caught.value.status_code == 503 and not store.deletes and not store.patches


@pytest.mark.parametrize('stdout,returncode,stderr,expected', [
    ('{"format": {"duration": "61.5"}, "streams": [{"codec_type": "video", "width": 1280, "height": 720}]}', 0, '', 61.5),
    ('{"format": {"duration": "7300"}, "streams": [{"codec_type": "video"}]}', 0, '', 422),
    ('{"format": {"duration": "60"}, "streams": [{"codec_type": "audio"}]}', 0, '', 422),
    ('{"format": {"duration": "60"}, "streams": [{"codec_type": "video", "width": 7680, "height": 4320}]}', 0, '', 422),
    ('oops', 0, '', 422),
    ('', 1, 'signed: Invalid data found when processing input', 422),          # read it: not a video
    ('', 1, 'HTTP error 503 Service Unavailable', 503),                       # storage blip: try again
    ('', 1, 'Connection timed out', 503),
])
def test_remote_probe_rules(monkeypatch, stdout, returncode, stderr, expected):
    monkeypatch.setattr(cf.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr))
    if isinstance(expected, float):
        assert cf.probe_remote('https://abcdefgh.supabase.co/signed') == expected
    else:
        with pytest.raises(HTTPException) as caught:
            cf.probe_remote('https://abcdefgh.supabase.co/signed')
        assert caught.value.status_code == expected


def test_a_probe_timeout_is_retryable(monkeypatch):
    def slow(*a, **k):
        raise cf.subprocess.TimeoutExpired('ffprobe', 120)
    monkeypatch.setattr(cf.subprocess, 'run', slow)
    with pytest.raises(HTTPException) as caught:
        cf.probe_remote('https://abcdefgh.supabase.co/signed')
    assert caught.value.status_code == 503


# ── starting runs ────────────────────────────────────────────────────

def ready_source(**changes):
    return {'id': SOURCE, 'business_id': BIZ, 'kind': 'source', 'status': 'ready', 'duration_seconds': 3760.9,
            'name': 'Separate Them', 'source_removed_at': None} | changes


@pytest.fixture
def gates(monkeypatch):
    import billing_limits
    import spend_guard
    called = {'feature': [], 'units': []}
    monkeypatch.setattr(billing_limits, 'require_feature', lambda biz, feature: called['feature'].append(feature))
    monkeypatch.setattr(billing_limits, 'require_units', lambda biz: called['units'].append(biz))
    monkeypatch.setattr(spend_guard, 'over_budget', lambda biz=None: False)
    return called


def test_run_needs_the_switch_the_plan_and_a_ready_recording(monkeypatch, on, gates):
    monkeypatch.setattr(media, 'asset', lambda *a: ready_source())
    store = Store(monkeypatch, reads=lambda path: [])
    run = cf.start_run(BIZ, SOURCE, cf.FindClips(), USER)
    assert gates['feature'] == ['ai_clips'] and gates['units'] == []
    path, body = store.posts[0]
    assert path == '/media_clip_runs' and body['source_seconds'] == 3760.9
    assert body['options'] == {'lengths': ['short', 'medium'], 'caption_style': 'pop', 'look_for': None}
    assert run['id'] == NEW
    for broken in (ready_source(status='uploading'), ready_source(kind='clip'), ready_source(source_removed_at='2026-10-01T00:00:00Z')):
        monkeypatch.setattr(media, 'asset', lambda *a, b=broken: b)
        with pytest.raises(HTTPException) as caught:
            cf.start_run(BIZ, SOURCE, cf.FindClips(), USER)
        assert caught.value.status_code == 409


def test_run_refused_when_switched_off_for_the_business(monkeypatch, on, gates):
    monkeypatch.setenv('CLIP_FINDER_BUSINESSES', '')
    monkeypatch.setattr(media, 'asset', lambda *a: ready_source())
    with pytest.raises(HTTPException) as caught:
        cf.start_run(BIZ, SOURCE, cf.FindClips(), USER)
    assert caught.value.status_code == 503 and not gates['feature']


def test_past_the_allowance_needs_actions_left(monkeypatch, on, gates):
    monkeypatch.setattr(media, 'asset', lambda *a: ready_source())
    Store(monkeypatch, reads=lambda path: [{'source_seconds': 10 * 3600}] if 'media_clip_runs' in path else [])
    cf.start_run(BIZ, SOURCE, cf.FindClips(), USER)
    assert gates['units'] == [BIZ]


def test_a_second_active_run_is_refused(monkeypatch, on, gates):
    monkeypatch.setattr(media, 'asset', lambda *a: ready_source())
    Store(monkeypatch, post=lambda path, body: None)   # the one-active-run index
    with pytest.raises(HTTPException) as caught:
        cf.start_run(BIZ, SOURCE, cf.FindClips(), USER)
    assert caught.value.status_code == 409


def test_engine_options_map_the_screen_choices():
    assert cf.engine_options({'lengths': ['long'], 'caption_style': 'clean', 'look_for': 'For visitors'}) == {
        'durations': ['long'], 'caption_preset': 'subtle', 'clip_request': 'For visitors', 'aspect_ratio': '9:16'}


# ── the worker ───────────────────────────────────────────────────────

RESULT = {'clips': [
    {'index': 0, 'title': 'Hear God For Yourself', 'start_ms': 396000, 'end_ms': 415000, 'duration_ms': 19000,
     'score': 0.74, 'tags': ['faith'], 'review_flags': [], 'video': 'clip_00.mp4', 'poster': 'clip_00.jpg',
     'empty_spots': [], 'face_coverage': 1.0},
    {'index': 1, 'title': "Don't Judge Rightness By Feelings", 'start_ms': 2737000, 'end_ms': 2781000, 'duration_ms': 44000,
     'score': 0.72, 'tags': [], 'review_flags': ['uncertain_unresolved_payoff'], 'video': 'clip_01.mp4', 'poster': None,
     'empty_spots': [{'from': 5.1, 'to': 20.0, 'seconds': 14.9}], 'face_coverage': 0.58}],
    'cost': {'total_estimated_cost_usd': 0.367}, 'counts': {'planned': 2, 'rendered': 2, 'failed': 0, 'checked': 2},
    'timings': {'total': 302.0}}
RUN_ROW = {'id': RUN, 'business_id': BIZ, 'source_id': SOURCE, 'lease_id': '00000000-0000-4000-8000-000000000009',
           'status': 'working', 'options': {'lengths': ['short', 'medium'], 'caption_style': 'pop'},
           'source_seconds': 3760.9, 'created_by': OWNER, 'attempt': 1}


@pytest.fixture
def worker(monkeypatch, on, tmp_path):
    """A clip service that answers from a script, storage that records puts."""
    calls, puts, metered, notified = [], [], [], []
    script = {'GET': [httpx.Response(404)], 'POST': httpx.Response(202, json={'accepted': True}), 'DELETE': httpx.Response(200)}

    def clipper(method, path, **kwargs):
        calls.append((method, path, kwargs.get('json')))
        if method == 'GET':
            return script['GET'].pop(0) if len(script['GET']) > 1 else script['GET'][0]
        return script[method]
    monkeypatch.setattr(cf, 'clipper', clipper)
    monkeypatch.setattr(cf, 'fetch', lambda path, target: target.write_bytes(b'fake mp4 bytes' if path.endswith('.mp4') else b'jpg'))
    monkeypatch.setattr(cf, 'put_file', lambda local, path, ctype: puts.append((path, ctype)))
    monkeypatch.setattr(cf.storage_links, 'signed_url_sync', lambda bucket, path, ttl=None, **k: f'https://abcdefgh.supabase.co/signed/{path}?ttl={ttl}')
    monkeypatch.setattr(cf, 'POLL_SECONDS', 0)
    monkeypatch.setattr(cf, 'meter', lambda run, result, units: metered.append(units))
    monkeypatch.setattr(cf, 'notify', lambda run, source, filed, flagged: notified.append((filed, flagged)))
    return SimpleNamespace(calls=calls, puts=puts, metered=metered, notified=notified, script=script)


def completed(result=RESULT):
    return httpx.Response(200, json={'status': 'completed', 'stage': 'done', 'percent': 100, 'clips_done': 2, 'clips_total': 2, 'result': result})


def working(percent):
    return httpx.Response(200, json={'status': 'working', 'stage': 'framing', 'percent': percent, 'clips_done': 1, 'clips_total': 2})


def test_a_run_starts_the_job_follows_it_and_files_every_clip(monkeypatch, worker):
    worker.script['GET'] = [httpx.Response(404), working(40), working(80), completed()]
    store = Store(monkeypatch, reads=lambda path: [ready_source()] if f'id=eq.{SOURCE}' in path else [])
    cf.drive(dict(RUN_ROW))
    post = [c for c in worker.calls if c[0] == 'POST'][0]
    assert post[1] == f'/jobs/{RUN}' and post[2]['source_url'].endswith(f'{BIZ}/{SOURCE}.source?ttl=10800')
    assert post[2]['options']['caption_preset'] == 'pop'
    clips = [body for path, body in store.posts if path == '/media_assets']
    assert [c['id'] for c in clips] == [str(uuid5(UUID(RUN), 'clip-0')), str(uuid5(UUID(RUN), 'clip-1'))]
    assert clips[1]['configuration']['empty_spots'] == [{'from': 5.1, 'to': 20.0, 'seconds': 14.9}]
    assert clips[0]['configuration']['poster'] is True and clips[1]['configuration']['poster'] is False
    assert clips[0]['status'] == 'ready' and clips[0]['source_id'] == SOURCE and clips[0]['created_by'] == OWNER
    assert [p for p, _ in worker.puts] == [f'{BIZ}/{clips[0]["id"]}.mp4', f'{BIZ}/{clips[0]["id"]}.jpg', f'{BIZ}/{clips[1]["id"]}.mp4']
    # Every write to the run is fenced by its lease.
    assert all(f'lease_id=eq.{RUN_ROW["lease_id"]}' in path and 'status=eq.working' in path for path, _ in store.patches)
    final = store.patches[-1][1]
    assert final['status'] == 'completed' and final['counts']['planned'] == 2 and final['units'] == 0
    assert worker.metered == [0] and worker.notified == [(2, 1)]


def test_a_clean_frame_is_filed_beside_the_poster(monkeypatch, worker):
    with_frame = {**RESULT, 'clips': [dict(RESULT['clips'][0], frame='clip_00_frame.jpg'), RESULT['clips'][1]]}
    worker.script['GET'] = [httpx.Response(404), completed(with_frame)]
    store = Store(monkeypatch, reads=lambda path: [ready_source()] if f'id=eq.{SOURCE}' in path else [])
    cf.drive(dict(RUN_ROW))
    clips = [body for path, body in store.posts if path == '/media_assets']
    assert clips[0]['configuration']['frame'] is True and clips[1]['configuration']['frame'] is False
    assert (f'{BIZ}/{clips[0]["id"]}-frame.jpg', 'image/jpeg') in worker.puts
    assert cf.frame_path({'business_id': BIZ, 'id': clips[0]['id']}) == f'{BIZ}/{clips[0]["id"]}-frame.jpg'


def test_a_resumed_run_does_not_restart_the_job_or_refile_clips(monkeypatch, worker):
    worker.script['GET'] = [working(90), completed()]
    filed = {str(uuid5(UUID(RUN), 'clip-0'))}
    def reads(path):
        if f'id=eq.{SOURCE}' in path:
            return [ready_source()]
        return [{'id': 'x'}] if any(f'id=eq.{f}' in path for f in filed) else []
    store = Store(monkeypatch, reads=reads)
    cf.drive(dict(RUN_ROW))
    assert not [c for c in worker.calls if c[0] == 'POST']
    assert [body['id'] for path, body in store.posts if path == '/media_assets'] == [str(uuid5(UUID(RUN), 'clip-1'))]


def test_a_failed_job_becomes_a_failed_run_with_the_safe_reason(monkeypatch, worker):
    worker.script['GET'] = [httpx.Response(404), httpx.Response(200, json={'status': 'failed', 'error': {'message': 'Recordings can be up to 2 hours long.'}})]
    store = Store(monkeypatch, reads=lambda path: [ready_source()])
    monkeypatch.setattr(cf.sb_clients, 'sb_post_as_service', lambda path, body, *a, **k: [dict(RUN_ROW)] if 'claim_clip_run' in path else store._post(path, body, None))
    assert cf.work_once() is True
    failed = store.patches[-1][1]
    assert failed['status'] == 'failed' and failed['error'] == 'Recordings can be up to 2 hours long.'
    assert ('DELETE', f'/jobs/{RUN}', None) in worker.calls


def test_a_cancelled_run_stops_and_frees_the_clip_service(monkeypatch, worker):
    worker.script['GET'] = [httpx.Response(404), working(40)]
    store = Store(monkeypatch, reads=lambda path: [ready_source()], patch=lambda path, body: None)  # the fence no longer matches
    monkeypatch.setattr(cf.sb_clients, 'sb_post_as_service', lambda path, body, *a, **k: [dict(RUN_ROW)] if 'claim_clip_run' in path else store._post(path, body, None))
    assert cf.work_once() is True
    assert ('DELETE', f'/jobs/{RUN}', None) in worker.calls
    assert not any(body.get('status') == 'failed' for _, body in store.patches)


def test_an_unexpected_error_leaves_the_run_to_resume(monkeypatch, worker):
    store = Store(monkeypatch, reads=lambda path: [ready_source()])
    monkeypatch.setattr(cf.sb_clients, 'sb_post_as_service', lambda path, body, *a, **k: [dict(RUN_ROW)] if 'claim_clip_run' in path else None)
    monkeypatch.setattr(cf, 'drive', lambda run: (_ for _ in ()).throw(RuntimeError('network blip')))
    assert cf.work_once() is True
    assert not any(body.get('status') == 'failed' for _, body in store.patches)
    assert not [c for c in worker.calls if c[0] == 'DELETE']


def test_a_clip_that_cannot_be_filed_stops_the_run_before_completed(monkeypatch, worker):
    worker.script['GET'] = [httpx.Response(404), completed()]
    def post(path, body):
        if path == '/media_assets' and body['id'] == str(uuid5(UUID(RUN), 'clip-1')):
            return None   # the insert failed
        return [dict(body)]
    store = Store(monkeypatch, reads=lambda path: [ready_source()] if f'id=eq.{SOURCE}' in path else [], post=post)
    with pytest.raises(RuntimeError, match='could not be filed'):
        cf.drive(dict(RUN_ROW))
    assert not any(body.get('status') == 'completed' for _, body in store.patches)
    assert worker.metered == [] and worker.notified == []
    assert not [c for c in worker.calls if c[0] == 'DELETE']   # the job stays on the clip service to resume


def test_a_removed_recording_fails_the_run(monkeypatch, worker):
    Store(monkeypatch, reads=lambda path: [ready_source(source_removed_at='2026-10-01T00:00:00Z')])
    with pytest.raises(cf.RunFailed):
        cf.drive(dict(RUN_ROW))
    assert not worker.calls


def test_charges_count_the_month_before_this_run(monkeypatch, on):
    Store(monkeypatch, reads=lambda path: [{'source_seconds': 9 * 3600}, {'source_seconds': 3760.9}])
    # 9 h used before; this 62.7-minute run crosses 10 h by ~2.7 minutes.
    assert cf.units_for(dict(RUN_ROW)) == 4


def test_poster_links_are_signed_in_one_call(monkeypatch, on):
    rows = [{'id': CLIP_A, 'business_id': BIZ, 'kind': 'clip', 'status': 'ready', 'configuration': {'poster': True}},
            {'id': CLIP_B, 'business_id': BIZ, 'kind': 'clip', 'status': 'ready', 'configuration': {'poster': False}},
            {'id': CLIP_C, 'business_id': BIZ, 'kind': 'source', 'status': 'ready', 'configuration': {}}]
    asked = []
    def handler(request):
        asked.append(json.loads(request.content))
        return httpx.Response(200, json=[{'path': p, 'signedURL': f'/object/sign/program-media/{p}?token=x'} for p in json.loads(request.content)['paths']])
    client_type = httpx.Client
    monkeypatch.setattr(cf.httpx, 'Client', lambda **kw: client_type(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(cf.storage_links, 'service_headers', lambda: {})
    urls = cf.poster_urls(rows)
    assert list(urls) == [CLIP_A] and len(asked) == 1 and asked[0]['paths'] == [f'{BIZ}/{CLIP_A}.jpg']
    assert urls[CLIP_A].startswith('https://abcdefgh.supabase.co/storage/v1/object/sign/')


# ── keep, skip, rename ───────────────────────────────────────────────

def test_keep_skip_and_rename_only_finished_clips(monkeypatch, on):
    row = {'id': CLIP_A, 'business_id': BIZ, 'kind': 'clip', 'status': 'ready', 'configuration': {}}
    monkeypatch.setattr(media, 'asset', lambda *a: row)
    store = Store(monkeypatch)
    cf.update_clip(BIZ, CLIP_A, cf.ClipUpdate(decision='kept', name='Hear God For Yourself'), USER)
    body = store.patches[-1][1]
    assert body['decision'] == 'kept' and body['decided_at'].endswith('Z') and body['name'] == 'Hear God For Yourself'
    cf.update_clip(BIZ, CLIP_A, cf.ClipUpdate(clear_decision=True), USER)
    assert store.patches[-1][1] == {'decision': None, 'decided_at': None}
    monkeypatch.setattr(media, 'asset', lambda *a: row | {'kind': 'source'})
    with pytest.raises(HTTPException):
        cf.update_clip(BIZ, CLIP_A, cf.ClipUpdate(decision='skipped'), USER)


# ── storage rules ────────────────────────────────────────────────────

def test_sweep_applies_the_storage_rules(monkeypatch, on):
    def reads(path):
        if 'status=eq.uploading' in path:
            return [{'id': UPLOADING, 'business_id': BIZ, 'kind': 'source'}]
        if 'decision=eq.skipped' in path:
            return [{'id': SKIPPED, 'business_id': BIZ, 'kind': 'clip'}]
        if 'media_clip_runs?status=eq.completed' in path:
            return [{'source_id': OLD}, {'source_id': BUSY}]
        if f'media_clip_runs?source_id=eq.{BUSY}' in path:
            return [{'id': 'active'}]
        if f'media_clip_runs?source_id=eq.{OLD}' in path:
            return []
        if f'media_assets?id=eq.{OLD}' in path:
            return [{'id': OLD, 'business_id': BIZ, 'kind': 'source'}]
        return []
    store = Store(monkeypatch, reads=reads)
    removed = []
    monkeypatch.setattr(cf, 'remove_objects', lambda paths: removed.extend(paths))
    cf.sweep()
    assert f'{BIZ}/{UPLOADING}.source' in removed and f'{BIZ}/{SKIPPED}.mp4' in removed and f'{BIZ}/{SKIPPED}.jpg' in removed
    assert f'{BIZ}/{SKIPPED}-frame.jpg' in removed  # the clean frame goes with its clip
    assert f'{BIZ}/{OLD}.source' in removed and not any(BUSY in p for p in removed)
    assert any('source_removed_at' in body for _, body in store.patches)
    assert len(store.deletes) == 2


# ── the plan and the rest of the system ─────────────────────────────

def test_the_gate_is_growth_and_is_sold_on_the_cards_and_the_compare_table():
    import clip_finder
    import feature_gates
    import marketing_pages
    assert feature_gates.FEATURE_MIN_PLAN['ai_clips'] == 'practice'
    assert 'ai_clips' not in feature_gates.UNANNOUNCED_FEATURES
    assert set(feature_gates.UNANNOUNCED_FEATURES) <= set(feature_gates.FEATURE_MIN_PLAN)
    assert 'ai_clips' not in marketing_pages._NOT_A_ROW
    assert 'ai_clips' in feature_gates.plan_features('practice')
    assert 'ai_clips' not in feature_gates.plan_features('professional')
    for audience in feature_gates.AUDIENCE_PLAN_FEATURES.values():
        assert 'ai_clips' not in audience
    html = marketing_pages.render_compare()
    assert 'Find my best clips' in html
    # The row's allowance is the code's allowance.
    assert clip_finder.INCLUDED_SECONDS == 10 * 3600 and 'Ten hours of recordings a month' in html


def test_runs_travel_with_the_account_but_are_never_restored():
    import account_lifecycle
    src = open(account_lifecycle.__file__, encoding='utf-8').read()
    assert src.count('"media_clip_runs"') == 2
    assert 'media_clip_runs' in account_lifecycle._IMPORT_SKIP


def test_manual_clips_refuse_a_removed_recording(monkeypatch):
    monkeypatch.setattr(media, 'asset', lambda *a: ready_source(source_removed_at='2026-10-01T00:00:00Z', duration_seconds=60))
    body = media.Clip(source_id=SOURCE, name='Clip', start_seconds=1, end_seconds=10, caption='', destination='Review')
    with pytest.raises(HTTPException) as caught:
        media.create_clip(BIZ, body, USER)
    assert caught.value.status_code == 409


def test_a_hand_cut_clip_can_read_a_large_uploaded_recording(monkeypatch, tmp_path):
    """The manual cutter downloads the recording first; its cap follows the
    recording's stored size (uploads go to 5 GB), never below the Drive cap."""
    parent = ready_source(byte_size=3 * 1024 ** 3, sha256=None)
    row = {'id': RUN, 'business_id': BIZ, 'kind': 'clip', 'source_id': SOURCE, 'created_by': OWNER,
           'configuration': {'start_seconds': 1, 'end_seconds': 10}}
    monkeypatch.setattr(media, 'access', lambda *a, **k: None)
    monkeypatch.setattr(media, 'asset', lambda *a: parent)
    monkeypatch.setattr(media.storage_links, 'signed_url_sync', lambda *a, **k: 'https://abcdefgh.supabase.co/signed')
    caps = []
    def transfer(client, url, headers, target, maximum=media.MAX_BYTES):
        caps.append(maximum)
        raise ValueError('stop after the cap is chosen')
    monkeypatch.setattr(media, 'transfer_to_file', transfer)
    with pytest.raises(ValueError, match='stop after'):
        media.process(row)
    assert caps == [3 * 1024 ** 3]
