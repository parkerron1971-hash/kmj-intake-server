"""The clip service (clipper_worker/): auth, source-link rules, the job lifecycle
and the empty-spot check. The engine, the download and the face detector are
faked; nothing here needs FFmpeg, OpenCV or a network."""
import json
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import clipper_worker.service as svc
from clipper_worker.empty_spots import gaps, poster_time

TOKEN = 'x' * 40
AUTH = {'Authorization': 'Bearer ' + TOKEN}
SOURCE = 'https://project.supabase.co/storage/v1/object/sign/program-media/a.mp4?token=t'


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv('CLIPPER_TOKEN', TOKEN)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'sk-or-test')
    monkeypatch.setenv('CLIPPER_SOURCE_HOSTS', 'project.supabase.co')
    monkeypatch.setattr(svc, 'ROOT', tmp_path / 'jobs')
    svc.jobs.clear()
    yield TestClient(svc.app)
    # A job thread can still be in its cleanup after the status flips; let it
    # release the lock itself before the next test starts.
    assert svc.lock.acquire(timeout=5)
    svc.lock.release()
    svc.jobs.clear()


def fake_pipeline(monkeypatch, final=None, clips=2, spots=None, layouts=None):
    """Swap the slow parts for fakes that write what the real engine writes."""
    monkeypatch.setattr(svc, 'download', lambda url, target, state: target.write_bytes(b'video') or 5)
    monkeypatch.setattr(svc, 'probe', lambda path: 60.0)
    seen = {}

    def run_engine(state, config, env, job_dir):
        seen.update(config=config, env=env)
        if final is not None:
            return final
        out = job_dir / 'out' / config['job_id']
        out.mkdir(parents=True)
        rows = []
        for i in range(clips):
            (out / f'clip_{i:02d}.mp4').write_bytes(b'mp4')
            rows.append({'clip_index': i, 'summary': f'Moment {i}', 'start_time_ms': 1000 * i, 'end_time_ms': 1000 * i + 30000,
                         'duration_ms': 30000, 'virality_score': 0.8, 'tags': ['faith'],
                         'layout_type': (layouts or {}).get(i, 'talking_head'),
                         'editorial': {'flags': ['uncertain_unresolved_payoff']}})
        metrics = {'api_costs': {'total_estimated_cost_usd': 0.37}, 'stage_durations_seconds': {'transcription': 72.0},
                   'planned_clip_count': clips + 1, 'rendered_clip_count': clips, 'failed_clip_count': 1}
        (out / 'job_output.json').write_text(json.dumps({'clips': rows, 'metrics': metrics, 'source_video_duration_seconds': 60}))
        return {'type': 'result', 'status': 'completed'}

    monkeypatch.setattr(svc, 'run_engine', run_engine)
    monkeypatch.setattr(svc.empty_spots, 'detector', lambda: object())
    monkeypatch.setattr(svc.empty_spots, 'scan', lambda path, det: {
        'length': 30.0, 'face_coverage': 0.9, 'poster_at': 2.0,
        'empty_spots': (spots or {}).get(path.name, [])})
    monkeypatch.setattr(svc, 'make_poster', lambda video, at, target: target.write_bytes(b'jpg'))
    def make_frame(source, at, target):
        seen.setdefault('frames', []).append((source.name, source.is_file(), at))
        target.write_bytes(b'frame')
    monkeypatch.setattr(svc, 'make_frame', make_frame)
    def face_closeup(source, at, target, det, **span):
        seen.setdefault('faces', []).append((at, span))
        target.write_bytes(b'face')
        return 70, 90
    monkeypatch.setattr(svc.empty_spots, 'face_closeup', face_closeup)
    return seen


def wait_done(client, job_id):
    for _ in range(200):
        body = client.get(f'/jobs/{job_id}', headers=AUTH).json()
        if body['status'] != 'working':
            return body
        time.sleep(0.02)
    raise AssertionError('job never finished')


def test_every_job_route_needs_the_token(client):
    job = uuid4()
    assert client.post(f'/jobs/{job}', json={'source_url': SOURCE}).status_code == 401
    assert client.get(f'/jobs/{job}', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    assert client.get(f'/jobs/{job}/files/clip_00.mp4').status_code == 401
    assert client.delete(f'/jobs/{job}').status_code == 401
    assert client.get('/health').json()['ready'] is True


def test_a_non_ascii_auth_header_is_a_401_not_a_500(client):
    # The server decodes header bytes as latin-1, so these arrive as non-ASCII text.
    assert client.get(f'/jobs/{uuid4()}', headers={'Authorization': b'Bearer caf\xc3\xa9'}).status_code == 401


def test_a_short_configured_token_refuses_everything(client, monkeypatch):
    monkeypatch.setenv('CLIPPER_TOKEN', 'short')
    assert client.get(f'/jobs/{uuid4()}', headers={'Authorization': 'Bearer short'}).status_code == 401
    assert client.get('/health').json()['ready'] is False


@pytest.mark.parametrize('url', [
    'http://project.supabase.co/a.mp4',
    'https://evil.example/a.mp4',
    'https://user:pw@project.supabase.co/a.mp4',
    'https://project.supabase.co:8443/a.mp4',
    'https://project.supabase.co.evil.example/a.mp4',
    'file:///etc/passwd',
])
def test_only_signed_links_from_our_storage_are_accepted(client, url):
    assert client.post(f'/jobs/{uuid4()}', json={'source_url': url}, headers=AUTH).status_code == 422


def test_no_approved_hosts_means_no_jobs(client, monkeypatch):
    monkeypatch.setenv('CLIPPER_SOURCE_HOSTS', '')
    assert svc.source_allowed(SOURCE) is False


def test_options_are_checked_before_anything_runs():
    with pytest.raises(ValidationError):
        svc.Options(caption_preset='comic-sans')
    with pytest.raises(ValidationError):
        svc.Options(durations=['forever'])
    with pytest.raises(ValidationError):
        svc.Options(keyterms=['x' * 50])
    with pytest.raises(ValidationError):
        svc.JobRequest(source_url=SOURCE, options={}, extra='no')
    assert svc.Options(clip_request='   ').clip_request is None


def test_engine_gets_the_desktop_contract_and_no_service_token(client, monkeypatch):
    seen = fake_pipeline(monkeypatch)
    job = uuid4()
    options = {'durations': ['short', 'short', 'medium'], 'caption_preset': 'subtle', 'keyterms': ['Love City'], 'clip_request': 'For visitors'}
    assert client.post(f'/jobs/{job}', json={'source_url': SOURCE, 'options': options}, headers=AUTH).status_code == 202
    wait_done(client, job)
    config, env = seen['config'], seen['env']
    assert config['contract_version'] == 3 and config['workflow'] == 'automatic' and config['clipping_mode'] == 'quality'
    assert config['duration_ranges'] == ['short', 'medium'] and config['caption_preset'] == 'subtle'
    assert config['keyterms'] == ['Love City'] and config['clip_request'] == 'For visitors' and config['auto_clip_count'] is True
    assert env['OPENROUTER_API_KEY'] == 'sk-or-test' and env['LOCAL_MODE'] == 'true' and env['JEV_ENABLED'] == 'true'
    assert 'CLIPPER_TOKEN' not in env and TOKEN not in json.dumps(env)


def test_finished_job_reports_clips_with_empty_spots_and_serves_files(client, monkeypatch):
    spot = [{'from': 5.1, 'to': 20.0, 'seconds': 14.9}]
    fake_pipeline(monkeypatch, clips=2, spots={'clip_01.mp4': spot})
    job = uuid4()
    client.post(f'/jobs/{job}', json={'source_url': SOURCE}, headers=AUTH)
    body = wait_done(client, job)
    assert body['status'] == 'completed' and body['stage'] == 'done' and body['percent'] == 100.0
    clips = body['result']['clips']
    assert [c['title'] for c in clips] == ['Moment 0', 'Moment 1']
    assert clips[0]['empty_spots'] == [] and clips[1]['empty_spots'] == spot
    assert clips[1]['video'] == 'clip_01.mp4' and clips[1]['poster'] == 'clip_01.jpg'
    assert clips[0]['review_flags'] == ['uncertain_unresolved_payoff']
    assert body['result']['cost'] == {'total_estimated_cost_usd': 0.37}
    assert body['result']['counts'] == {'planned': 3, 'rendered': 2, 'failed': 1, 'checked': 2}
    assert body['result']['engine']['commit'] == svc.ENGINE_COMMIT
    assert client.get(f'/jobs/{job}/files/clip_01.mp4', headers=AUTH).content == b'mp4'
    assert client.get(f'/jobs/{job}/files/clip_01.jpg', headers=AUTH).content == b'jpg'
    for name in ('job_output.json', '..%2Fsource.mp4', 'engine.log', 'clip_1.mp4'):
        assert client.get(f'/jobs/{job}/files/{name}', headers=AUTH).status_code == 404
    assert not (svc.ROOT / str(job) / 'source.mp4').exists()
    assert client.delete(f'/jobs/{job}', headers=AUTH).status_code == 200
    assert client.get(f'/jobs/{job}', headers=AUTH).status_code == 404
    assert not (svc.ROOT / str(job)).exists()


def test_engine_failure_keeps_a_safe_reason_for_the_api(client, monkeypatch):
    fake_pipeline(monkeypatch, final={'type': 'error', 'message': 'OpenRouter rejected the transcription request.',
                                      'code': 'transcription.auth', 'stage': 'transcription'})
    job = uuid4()
    client.post(f'/jobs/{job}', json={'source_url': SOURCE}, headers=AUTH)
    body = wait_done(client, job)
    assert body['status'] == 'failed'
    assert body['error'] == {'message': 'OpenRouter rejected the transcription request.', 'stage': 'transcription', 'code': 'transcription.auth'}
    assert 'result' not in body
    assert client.get(f'/jobs/{job}/files/clip_00.mp4', headers=AUTH).status_code == 404
    assert not svc.lock.locked()


def test_a_crash_never_leaks_its_text(client, monkeypatch):
    fake_pipeline(monkeypatch)
    monkeypatch.setattr(svc, 'probe', lambda path: (_ for _ in ()).throw(RuntimeError('/home/clipper/jobs/secret?token=abc')))
    job = uuid4()
    client.post(f'/jobs/{job}', json={'source_url': SOURCE}, headers=AUTH)
    body = wait_done(client, job)
    assert body['status'] == 'failed' and body['error']['code'] == 'job.crashed'
    assert 'token' not in json.dumps(body)


def test_one_job_at_a_time_and_ids_are_not_reused(client, monkeypatch):
    release = threading.Event()
    fake_pipeline(monkeypatch)
    original = svc.run_engine
    monkeypatch.setattr(svc, 'run_engine', lambda *a: (release.wait(5), original(*a))[1])
    first = uuid4()
    assert client.post(f'/jobs/{first}', json={'source_url': SOURCE}, headers=AUTH).status_code == 202
    assert client.post(f'/jobs/{uuid4()}', json={'source_url': SOURCE}, headers=AUTH).status_code == 409
    assert client.post(f'/jobs/{first}', json={'source_url': SOURCE}, headers=AUTH).status_code == 409
    release.set()
    assert wait_done(client, first)['status'] == 'completed'
    assert client.post(f'/jobs/{uuid4()}', json={'source_url': SOURCE}, headers=AUTH).status_code == 202


def test_delete_stops_a_running_job_and_forgets_it(client, monkeypatch):
    fake_pipeline(monkeypatch)

    def slow_engine(state, config, env, job_dir):
        while True:
            svc.check_cancel(state)
            time.sleep(0.01)
    monkeypatch.setattr(svc, 'run_engine', slow_engine)
    job = uuid4()
    client.post(f'/jobs/{job}', json={'source_url': SOURCE}, headers=AUTH)
    assert client.delete(f'/jobs/{job}', headers=AUTH).status_code == 200
    for _ in range(200):
        if svc.jobs.get(str(job)) is None and not svc.lock.locked():
            break
        time.sleep(0.02)
    assert client.get(f'/jobs/{job}', headers=AUTH).status_code == 404
    assert not (svc.ROOT / str(job)).exists()


def test_missing_ai_key_is_refused_up_front(client, monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY')
    assert client.post(f'/jobs/{uuid4()}', json={'source_url': SOURCE}, headers=AUTH).status_code == 503


def fresh_state():
    return {'cancel': threading.Event(), 'started': time.monotonic(), 'stage': 'downloading', 'percent': 0.0}


def serve(body=b'', status=200, headers=None):
    import httpx
    return httpx.MockTransport(lambda request: httpx.Response(status, content=body, headers=headers or {}))


def test_download_writes_the_file_and_reports_progress(tmp_path):
    target, state = tmp_path / 'source.mp4', fresh_state()
    size = svc.download(SOURCE, target, state, transport=serve(b'x' * 3000, headers={'content-length': '3000'}))
    assert size == 3000 and target.read_bytes() == b'x' * 3000 and state['percent'] == 5.0


@pytest.mark.parametrize('body,headers,code', [
    (b'x' * 10, {'content-length': '999999'}, 'download.too_large'),   # declared too big: refused before reading
    (b'x' * 2000, {}, 'download.too_large'),                             # no length given, too big while streaming
    (b'', {}, 'download.empty'),
])
def test_download_size_limits(tmp_path, monkeypatch, body, headers, code):
    monkeypatch.setattr(svc, 'MAX_SOURCE_BYTES', 1000)
    with pytest.raises(svc.JobError) as caught:
        svc.download(SOURCE, tmp_path / 'source.mp4', fresh_state(), transport=serve(body, headers=headers))
    assert caught.value.code == code


@pytest.mark.parametrize('status', [302, 403, 404, 500])
def test_download_refuses_redirects_and_errors(tmp_path, status):
    transport = serve(b'', status=status, headers={'location': 'http://169.254.169.254/'})
    with pytest.raises(svc.JobError) as caught:
        svc.download(SOURCE, tmp_path / 'source.mp4', fresh_state(), transport=transport)
    assert caught.value.code == 'download.status'


@pytest.mark.parametrize('stdout,result', [
    ('{"format": {"duration": "3760.9"}, "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}', 3760.9),
    ('{"format": {"duration": "7201"}, "streams": [{"codec_type": "video"}]}', 'probe.too_long'),
    ('{"format": {"duration": "60"}, "streams": [{"codec_type": "audio"}]}', 'probe.no_video'),
    ('not json', 'probe.unreadable'),
    ('{"streams": []}', 'probe.unreadable'),
])
def test_probe_enforces_two_hours_and_real_video(tmp_path, monkeypatch, stdout, result):
    monkeypatch.setattr(svc.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=stdout))
    if isinstance(result, float):
        assert svc.probe(tmp_path / 'source.mp4') == result
    else:
        with pytest.raises(svc.JobError) as caught:
            svc.probe(tmp_path / 'source.mp4')
        assert caught.value.code == result


def test_a_job_past_its_time_limit_is_stopped(monkeypatch):
    monkeypatch.setattr(svc, 'JOB_SECONDS', 10)
    state = fresh_state() | {'started': time.monotonic() - 11}
    with pytest.raises(svc.JobError) as caught:
        svc.check_cancel(state)
    assert caught.value.code == 'job.timeout'


def test_a_poster_that_times_out_does_not_fail_the_job(tmp_path, monkeypatch):
    def slow(*args, **kwargs):
        raise svc.subprocess.TimeoutExpired('ffmpeg', 60)
    monkeypatch.setattr(svc.subprocess, 'run', slow)
    target = tmp_path / 'clip_00.jpg'
    svc.make_poster(tmp_path / 'clip_00.mp4', 2.0, target)
    assert not target.exists()


def test_progress_bands_match_the_engine():
    assert [svc.stage_for(p) for p in (0, 15, 29.9, 30, 49, 50, 90)] == ['listening'] * 3 + ['choosing'] * 2 + ['framing'] * 2


def test_empty_spot_runs():
    at = lambda *pairs: [(t, f) for t, f in pairs]
    # A 3.5 s gap counts, a 1 s gap does not, and a gap still open at the end closes at the clip's length.
    samples = at((0, True), (1.0, False), (4.5, True), (5.0, False), (6.0, True), (8.0, False))
    assert gaps(samples, end=12.0) == [{'from': 1.0, 'to': 4.5, 'seconds': 3.5}, {'from': 8.0, 'to': 12.0, 'seconds': 4.0}]
    assert gaps(at((0, True), (1, True)), end=2.0) == []
    assert gaps(at((0, False)), end=30.0) == [{'from': 0, 'to': 30.0, 'seconds': 30.0}]


def test_poster_is_the_most_centred_face_early_in_the_clip():
    # (seconds, face distance from centre): skip the opening, ignore the last 40%, pick the most centred.
    centred = [(0.5, 0.0), (2.0, 0.30), (5.0, 0.05), (9.0, 0.20), (25.0, 0.0)]
    assert poster_time(centred, length=30.0) == 5.0
    assert poster_time([(0.2, 0.4)], length=30.0) == 0.2
    assert poster_time([], length=30.0) == 1.0


def test_service_reads_engine_progress_lines(monkeypatch, tmp_path):
    """run_engine against a stand-in engine script: progress becomes stage and percent, the result line wins."""
    script = tmp_path / 'fake_runner.py'
    script.write_text(
        'import sys, json\n'
        'sys.stdin.read()\n'
        'print(json.dumps({"type": "progress", "percent": 40, "clips_done": 0, "clips_total": 0}))\n'
        'print("not json")\n'
        'print(json.dumps({"type": "progress", "percent": 60, "clips_done": 3, "clips_total": 16}))\n'
        'print(json.dumps({"type": "result", "status": "completed"}))\n')
    monkeypatch.setattr(svc, 'RUNNER', script)
    monkeypatch.setattr(svc, 'VENDOR', tmp_path)
    state = {'cancel': threading.Event(), 'started': time.monotonic(), 'stage': 'listening'}
    final = svc.run_engine(state, {'job_id': 'x'}, {'PATH': '', 'SYSTEMROOT': __import__('os').environ.get('SYSTEMROOT', '')}, tmp_path)
    assert final == {'type': 'result', 'status': 'completed'}
    assert state['stage'] == 'framing' and state['clips_done'] == 3 and state['clips_total'] == 16
    assert state['percent'] == round(5 + 60 * 0.85, 1)


def test_each_clip_gets_a_clean_frame_from_the_recording(client, monkeypatch):
    """The cover is designed from the poster's moment in the recording itself:
    no burned-in captions or title card. The recording is still deleted."""
    seen = fake_pipeline(monkeypatch, clips=2)
    job = uuid4()
    client.post(f'/jobs/{job}', json={'source_url': SOURCE}, headers=AUTH)
    body = wait_done(client, job)
    clips = body['result']['clips']
    assert [c['frame'] for c in clips] == ['clip_00_frame.jpg', 'clip_01_frame.jpg']
    # start_time_ms / 1000 + poster_at, read while the recording still existed
    assert seen['frames'] == [('source.mp4', True, 2.0), ('source.mp4', True, 3.0)]
    assert client.get(f'/jobs/{job}/files/clip_01_frame.jpg', headers=AUTH).content == b'frame'
    for name in ('clip_01_frame.mp4', 'clip_1_frame.jpg', 'source_frame.jpg'):
        assert client.get(f'/jobs/{job}/files/{name}', headers=AUTH).status_code == 404
    assert not (svc.ROOT / str(job) / 'source.mp4').exists()


def test_a_frame_that_times_out_does_not_fail_the_job(tmp_path, monkeypatch):
    def slow(*args, **kwargs):
        raise svc.subprocess.TimeoutExpired('ffmpeg', 60)
    monkeypatch.setattr(svc.subprocess, 'run', slow)
    target = tmp_path / 'clip_00_frame.jpg'
    svc.make_frame(tmp_path / 'source.mp4', 12.5, target)
    assert not target.exists()


@pytest.mark.parametrize('returncode,body', [(1, b''), (1, b'half'), (0, b'')])
def test_a_failed_or_empty_still_is_never_advertised(tmp_path, monkeypatch, returncode, body):
    """A seek past the end can exit non-zero or leave a 0-byte file; neither
    may reach the API as a frame or a poster."""
    def ffmpeg(args, **kwargs):
        svc.Path(args[-1]).write_bytes(body)
        return svc.subprocess.CompletedProcess(args, returncode)
    monkeypatch.setattr(svc.subprocess, 'run', ffmpeg)
    frame, poster = tmp_path / 'clip_00_frame.jpg', tmp_path / 'clip_00.jpg'
    svc.make_frame(tmp_path / 'source.mp4', 9999.0, frame)
    svc.make_poster(tmp_path / 'clip_00.mp4', 9999.0, poster)
    assert not frame.exists() and not poster.exists()


def test_each_clip_gets_a_face_close_up_for_its_cover(client, monkeypatch):
    fake_pipeline(monkeypatch, clips=1)
    job = uuid4()
    client.post(f'/jobs/{job}', json={'source_url': SOURCE}, headers=AUTH)
    body = wait_done(client, job)
    assert body['result']['clips'][0]['face'] == 'clip_00_face.jpg'
    assert client.get(f'/jobs/{job}/files/clip_00_face.jpg', headers=AUTH).content == b'face'


def test_no_face_in_frame_means_no_close_up(tmp_path):
    """A blank picture has no face: nothing is written and the cover uses the frame alone.
    Runs where the clip service's OpenCV is installed (its image, a dev box); CI has none."""
    cv2 = pytest.importorskip('cv2')
    import numpy as np
    video = tmp_path / 'blank.mp4'
    out = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 10, (320, 240))
    for _ in range(30):
        out.write(np.zeros((240, 320, 3), dtype=np.uint8))
    out.release()
    target = tmp_path / 'face.jpg'
    assert svc.empty_spots.face_closeup(video, 1.0, target, svc.empty_spots.detector()) is None
    assert not target.exists()


def test_the_close_up_box_stays_four_by_five_inside_the_frame():
    """Review of #1286: a big face in a short frame used to give a wider crop."""
    box = svc.empty_spots.closeup_box
    for full_w, full_h, face in ((1920, 1080, (900, 300, 120, 150)),   # a stage shot
                                 (1280, 720, (500, 100, 400, 480)),    # a big face, short frame
                                 (300, 1000, (100, 400, 150, 180))):   # a narrow frame
        left, top, w, h = box(full_w, full_h, *face)
        assert abs(h / w - 1.25) < 0.01, (full_w, full_h, w, h)
        assert left >= 0 and top >= 0 and left + w <= full_w and top + h <= full_h


def face_row(w=80, turn=0.0, tilt=0.0, eyes=0.42, confidence=0.92, x=600, y=200):
    """A YuNet row laid out like a real face: the eyes `eyes` face-widths apart,
    the nose tip `turn` eye-distances off their midpoint, one eye `tilt`
    eye-distances above the other."""
    h = w * 1.3
    d = eyes * w
    cx, eye_y = x + w / 2, y + h * 0.4
    mouth_y = y + h * 0.78
    return [x, y, w, h, cx - d / 2, eye_y - tilt * d / 2, cx + d / 2, eye_y + tilt * d / 2,
            cx + turn * d, y + h * 0.6, cx - d * 0.4, mouth_y, cx + d * 0.4, mouth_y, confidence]


def score(sharpness=40.0, frame=(1280, 720), **face):
    return svc.empty_spots.face_score(face_row(**face), *frame, sharpness)


def test_a_face_turned_to_the_camera_beats_one_looking_aside():
    """Kevin, 2026-10-06: the close-up chose a serious, looking-aside frame;
    a cover wants the person facing the camera."""
    assert score(turn=0.05) > score(turn=0.2) > score(turn=0.35)
    assert score(turn=0.6) is None                  # the nose far off the eyes' midpoint
    assert score(eyes=0.18) is None                 # the eyes collapsed together: a profile
    assert score(tilt=0.0) > score(tilt=0.3)


def test_a_slightly_smaller_face_on_face_beats_a_bigger_turned_one():
    # What the sermon check showed: a 76 px face-on frame over the 83 px poster frame looking aside.
    assert score(w=76, turn=0.05) > score(w=84, turn=0.3, sharpness=45.0)


def test_a_sharp_face_beats_a_blurred_one():
    assert score(sharpness=60.0) > score(sharpness=8.0) > 0


def test_a_bigger_face_beats_a_small_one_and_a_tiny_face_is_never_used():
    assert score(w=160) > score(w=60)
    assert score(w=20) is None                      # 20 px in a 720-tall frame: too few pixels for a likeness
    assert score(w=20, frame=(320, 240)) is not None


def test_an_unsure_face_loses_and_a_coin_flip_is_never_used():
    """A hand or the microphone across the face lowers the detector's confidence."""
    assert score(confidence=0.93) > score(confidence=0.7)
    assert score(confidence=0.5) is None


def test_the_face_is_looked_for_across_the_whole_clip():
    times = svc.empty_spots.sample_times(100.0, 1.5, start=90.0, end=150.0, spread=12)
    assert times == sorted(times)
    assert {98.5, 99.25, 100.0, 100.75, 101.5} <= set(times)        # around the poster moment
    across = [t for t in times if t not in (98.5, 99.25, 100.0, 100.75, 101.5)]
    assert len(across) == 12 and across[0] == 92.5 and across[-1] == 147.5   # the middle of each slice
    assert svc.empty_spots.sample_times(100.0, 1.5) == [98.5, 99.25, 100.0, 100.75, 101.5]
    assert svc.empty_spots.sample_times(0.5, 1.5)[0] == 0.0                   # never before the recording


def test_the_close_up_looks_across_each_clip_but_not_across_a_two_person_shot(client, monkeypatch):
    seen = fake_pipeline(monkeypatch, clips=2, layouts={1: 'two_shot'})
    job = uuid4()
    client.post(f'/jobs/{job}', json={'source_url': SOURCE}, headers=AUTH)
    assert wait_done(client, job)['status'] == 'completed'
    # Clip 0 is [0 s, 30 s] of the recording; clip 1 is two people, so only its poster moment.
    assert seen['faces'] == [(2.0, {'start': 0.0, 'end': 30.0}), (3.0, {})]


def test_face_sharpness_sees_blur():
    cv2 = pytest.importorskip('cv2')
    import numpy as np
    frame = np.zeros((400, 400, 3), dtype=np.uint8)
    frame[::8, :] = 255
    frame[:, ::8] = 255
    blurred = cv2.GaussianBlur(frame, (0, 0), 3)
    sharp = svc.empty_spots.face_sharpness(frame, 100, 100, 150, 180)
    assert sharp > svc.empty_spots.face_sharpness(blurred, 100, 100, 150, 180) * 4
    assert svc.empty_spots.face_sharpness(frame, 500, 500, 50, 60) == 0.0   # off the frame
