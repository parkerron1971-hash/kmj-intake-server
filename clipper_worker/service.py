"""Isolated clip-finding service for Video Clips. Holds an OpenRouter key only.

The API sends a short-lived signed link to one private recording. This service
downloads it, runs the pinned BridgeClip engine (vendor/bridgeclip, see
README.md), checks every finished clip for stretches with nobody on screen,
and keeps the clips until the API collects them. It has no database or storage
credentials, runs one job at a time, and forgets a job when the API deletes it
or when it is RESULT_TTL seconds old.
"""
import hmac
import json
import logging
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from clipper_worker import empty_spots

ENGINE_COMMIT = 'b996820ef80fa324a3ad233bef1aac5cc6936804'
VENDOR = Path(__file__).parent / 'vendor' / 'bridgeclip'
RUNNER = VENDOR / 'bridge' / 'bridge_runner.py'
ROOT = Path(os.getenv('CLIPPER_WORK_DIR') or Path(tempfile.gettempdir()) / 'clipper')
MAX_SOURCE_BYTES = int(os.getenv('CLIPPER_MAX_SOURCE_BYTES', str(5 * 1024 ** 3)))
MAX_SOURCE_SECONDS = int(os.getenv('CLIPPER_MAX_SOURCE_SECONDS', '7200'))
JOB_SECONDS = int(os.getenv('CLIPPER_JOB_SECONDS', '3600'))
RESULT_TTL = int(os.getenv('CLIPPER_RESULT_TTL', '7200'))
CAPTION_PRESETS = ('pop', 'spotlight', 'impact', 'glow', 'boxed', 'sweep', 'editorial', 'hype', 'punch', 'neon', 'headline', 'paper', 'subtle')
FILE_NAME = re.compile(r'^clip_\d{2}\.(mp4|jpg)$')
# Only these reach the engine process; the service token never does.
ENGINE_ENV_KEEP = ('PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'FONTCONFIG_FILE', 'SYSTEMROOT', 'WINDIR', 'USERPROFILE', 'LOCALAPPDATA')

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
log = logging.getLogger('clipper')
lock = threading.Lock()
jobs = {}


class Options(BaseModel):
    model_config = ConfigDict(extra='forbid')
    durations: list[Literal['xshort', 'short', 'medium', 'long']] = Field(default_factory=lambda: ['short', 'medium'], min_length=1, max_length=4)
    caption_preset: Literal[CAPTION_PRESETS] = 'pop'
    aspect_ratio: Literal['9:16', '16:9'] = '9:16'
    clip_request: Optional[str] = Field(default=None, max_length=1000)
    keyterms: list[str] = Field(default_factory=list, max_length=100)
    max_clips: Optional[int] = Field(default=None, ge=1, le=30)

    @field_validator('keyterms')
    @classmethod
    def short_terms(cls, value):
        if any(not term.strip() or len(term) > 49 for term in value):
            raise ValueError('Each key term must be 1 to 49 characters')
        return [term.strip() for term in value]

    @field_validator('clip_request')
    @classmethod
    def real_request(cls, value):
        return (value or '').strip() or None


class JobRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_url: str = Field(max_length=4096)
    options: Options = Field(default_factory=Options)


class JobError(Exception):
    def __init__(self, message, stage, code):
        super().__init__(message)
        self.message, self.stage, self.code = message, stage, code


class Cancelled(Exception):
    pass


def authorized(authorization: str = Header(default='')):
    expected = os.getenv('CLIPPER_TOKEN', '')
    # Compare bytes: compare_digest raises on non-ASCII str, which would be a 500.
    if len(expected) < 32 or not hmac.compare_digest(authorization.encode(), ('Bearer ' + expected).encode()):
        raise HTTPException(401, 'Unauthorized')


def source_allowed(url):
    """Signed links from our own storage only: https, an approved host, no credentials."""
    hosts = {h.strip().lower() for h in os.getenv('CLIPPER_SOURCE_HOSTS', '').split(',') if h.strip()}
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == 'https' and not parts.username and not parts.password
            and port in (None, 443) and (parts.hostname or '').lower() in hosts)


def engine_env(job_dir):
    env = {k: v for k, v in os.environ.items() if k in ENGINE_ENV_KEEP}
    env.update({
        'OPENROUTER_API_KEY': os.getenv('OPENROUTER_API_KEY', ''),
        'LOCAL_MODE': 'true',
        'LOCAL_OUTPUT_DIR': str(job_dir / 'out'),
        'JEV_ENABLED': 'true',
        'PYTHONPATH': str(VENDOR / 'engine'),
        'BRIDGECLIP_WORK_ROOT': str(job_dir / 'work'),
        'PYTHONUNBUFFERED': '1',
        'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONIOENCODING': 'utf-8',
    })
    return env


def engine_config(job_id, source, out_dir, options):
    """The desktop app's job contract (bridge_runner.validate_config, version 3)."""
    return {
        'contract_version': 3,
        'job_id': str(job_id),
        'video_url': str(source),
        'output_dir': str(out_dir),
        'workflow': 'automatic',
        'clipping_mode': 'quality',
        'aspect_ratio': options.aspect_ratio,
        'layout_style': 'auto',
        'layout_vision_enabled': True,
        'duration_ranges': list(dict.fromkeys(options.durations)),
        'auto_clip_count': options.max_clips is None,
        'max_clips': options.max_clips,
        'include_captions': True,
        'include_title': True,
        'caption_preset': options.caption_preset,
        'pacing': 'tight',
        'video_speed': 1.0,
        'keyterms': options.keyterms or None,
        'clip_request': options.clip_request,
    }


def stage_for(percent):
    """Engine progress bands, measured on the 2026-10-05 rehearsal run."""
    if percent < 30:
        return 'listening'
    if percent < 50:
        return 'choosing'
    return 'framing'


def check_cancel(state):
    if state['cancel'].is_set():
        raise Cancelled()
    if time.monotonic() - state['started'] > JOB_SECONDS:
        raise JobError('Finding clips took too long and was stopped.', state['stage'], 'job.timeout')


def download(url, target, state, transport=None):
    timeout = httpx.Timeout(60.0, read=120.0)
    size = 0
    with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
        with client.stream('GET', url) as response:
            if response.status_code != 200:
                raise JobError('The recording could not be downloaded. Try again.', 'downloading', 'download.status')
            declared = int(response.headers.get('content-length') or 0)
            if declared > MAX_SOURCE_BYTES:
                raise JobError('Recordings can be up to 5 GB.', 'downloading', 'download.too_large')
            with open(target, 'wb') as out:
                for chunk in response.iter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_SOURCE_BYTES:
                        raise JobError('Recordings can be up to 5 GB.', 'downloading', 'download.too_large')
                    out.write(chunk)
                    if declared:
                        state['percent'] = round(5 * size / declared, 1)
                    check_cancel(state)
    if not size:
        raise JobError('The recording was empty.', 'downloading', 'download.empty')
    return size


def probe(path):
    try:
        done = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', str(path)],
                              capture_output=True, text=True, timeout=120)
        data = json.loads(done.stdout or '{}')
        duration = float(data['format']['duration'])
    except (subprocess.SubprocessError, ValueError, KeyError, TypeError):
        raise JobError("That file isn't a video we can read.", 'downloading', 'probe.unreadable') from None
    if not any(s.get('codec_type') == 'video' for s in data.get('streams', [])):
        raise JobError("That file has no video in it.", 'downloading', 'probe.no_video')
    if not 0 < duration <= MAX_SOURCE_SECONDS:
        raise JobError('Recordings can be up to 2 hours long.', 'downloading', 'probe.too_long')
    return duration


def stop(proc):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name != 'nt':
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()


def run_engine(state, config, env, job_dir):
    """Run bridge_runner.py and follow its JSON-line protocol. Returns the final message."""
    lines = queue.Queue()
    with open(job_dir / 'engine.log', 'w', encoding='utf-8') as engine_log:
        proc = subprocess.Popen([sys.executable, str(RUNNER)], cwd=str(VENDOR), env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=engine_log,
                                text=True, encoding='utf-8', errors='replace', start_new_session=os.name != 'nt')
        proc.stdin.write(json.dumps(config))
        proc.stdin.close()

        def reader():
            for line in proc.stdout:
                lines.put(line)
        follower = threading.Thread(target=reader, daemon=True)
        follower.start()
        final = None
        try:
            while True:
                try:
                    line = lines.get(timeout=0.5)
                except queue.Empty:
                    # The last lines can still be in flight after the process exits;
                    # stop only once the reader has hit end of output.
                    if not follower.is_alive() and lines.empty():
                        break
                    check_cancel(state)
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if message.get('type') == 'progress':
                    percent = float(message.get('percent') or 0)
                    state.update(stage=stage_for(percent), percent=round(5 + percent * 0.85, 1),
                                 clips_done=message.get('clips_done') or 0, clips_total=message.get('clips_total') or 0)
                elif message.get('type') in ('result', 'error'):
                    final = message
                check_cancel(state)
        finally:
            stop(proc)
    return final


def make_poster(video, at, target):
    """Best effort: a clip without a poster still reaches review."""
    try:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{at:.2f}', '-i', str(video), '-frames:v', '1', '-vf', 'scale=540:-2', '-q:v', '4', str(target)],
                       capture_output=True, timeout=60)
    except (subprocess.SubprocessError, OSError):
        log.warning('Poster frame failed for %s', video.name)
        Path(target).unlink(missing_ok=True)


def check_clips(state, manifest_path):
    """Run the empty-spot check on every finished clip and build the result the API stores."""
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    clip_dir = manifest_path.parent
    detector = empty_spots.detector()
    clips = []
    rows = data.get('clips') or []
    state.update(stage='checking', clips_done=0, clips_total=len(rows))
    for n, row in enumerate(rows):
        check_cancel(state)
        index = int(row['clip_index'])
        video = clip_dir / f'clip_{index:02d}.mp4'
        if not video.is_file():
            continue
        found = empty_spots.scan(video, detector)
        poster = clip_dir / f'clip_{index:02d}.jpg'
        make_poster(video, found['poster_at'], poster)
        editorial = row.get('editorial') or {}
        clips.append({
            'index': index,
            'title': row.get('summary') or f'Clip {index + 1}',
            'start_ms': row.get('start_time_ms'),
            'end_ms': row.get('end_time_ms'),
            'duration_ms': row.get('duration_ms'),
            'score': row.get('virality_score'),
            'tags': row.get('tags') or [],
            'layout': row.get('layout_type'),
            'review_flags': editorial.get('flags') or [],
            'video': video.name,
            'poster': poster.name if poster.is_file() else None,
            'bytes': video.stat().st_size,
            'empty_spots': found['empty_spots'],
            'face_coverage': found['face_coverage'],
        })
        state.update(clips_done=n + 1, percent=round(90 + 9 * (n + 1) / max(1, len(rows)), 1))
    metrics = data.get('metrics') or {}
    return clip_dir, {
        'engine': {'name': 'bridgeclip', 'commit': ENGINE_COMMIT},
        'source': {'duration_seconds': data.get('source_video_duration_seconds')},
        # Planned moments can drop out at review or fail to render; say so instead of hiding it.
        'counts': {'planned': metrics.get('planned_clip_count'), 'rendered': metrics.get('rendered_clip_count'),
                   'failed': metrics.get('failed_clip_count'), 'checked': len(clips)},
        'clips': clips,
        'cost': metrics.get('api_costs'),
        'timings': metrics.get('stage_durations_seconds'),
    }


def work(job_id, request, state):
    job_dir = state['dir']
    try:
        source = job_dir / 'source.mp4'
        (job_dir / 'out').mkdir(parents=True, exist_ok=True)
        (job_dir / 'work').mkdir(parents=True, exist_ok=True)
        state['source_bytes'] = download(request.source_url, source, state)
        probe(source)
        state.update(stage='listening', percent=5.0)
        final = run_engine(state, engine_config(job_id, source, job_dir / 'out', request.options), engine_env(job_dir), job_dir)
        source.unlink(missing_ok=True)
        if not final or final.get('type') != 'result':
            error = final or {}
            log_engine_tail(job_dir)
            raise JobError(error.get('message') or 'Finding clips failed. Try again.', error.get('stage') or state['stage'], error.get('code') or 'engine.failed')
        manifest = next((job_dir / 'out').rglob('job_output.json'), None)
        if manifest is None:
            raise JobError('Finding clips failed. Try again.', 'saving', 'engine.no_manifest')
        clip_dir, result = check_clips(state, manifest)
        result['source']['bytes'] = state.get('source_bytes')
        result['timings'] = dict(result.get('timings') or {}, total=round(time.monotonic() - state['started'], 1))
        state.update(status='completed', stage='done', percent=100.0, result=result, clip_dir=clip_dir)
    except Cancelled:
        state.update(status='cancelled', error={'message': 'Stopped.', 'stage': state['stage'], 'code': 'job.cancelled'})
    except JobError as error:
        state.update(status='failed', error={'message': error.message, 'stage': error.stage, 'code': error.code})
    except Exception as error:  # Never surface raw provider or path text.
        log.exception('Clip job failed (%s)', type(error).__name__)
        state.update(status='failed', error={'message': 'Finding clips failed. Try again.', 'stage': state['stage'], 'code': 'job.crashed'})
    finally:
        state['finished'] = time.monotonic()
        shutil.rmtree(job_dir / 'work', ignore_errors=True)
        (job_dir / 'source.mp4').unlink(missing_ok=True)
        if state.get('deleted'):
            forget(job_id)
        elif state['status'] != 'completed':
            # Keep the status so the API can read why; the files are no use.
            shutil.rmtree(job_dir, ignore_errors=True)
        lock.release()


def log_engine_tail(job_dir):
    """The engine's own log filter already strips keys, links and paths."""
    try:
        text = (job_dir / 'engine.log').read_text(encoding='utf-8', errors='replace')
    except OSError:
        return
    log.error('Clip engine failed. Last log lines:\n%s', text[-4000:])


def forget(job_id):
    state = jobs.pop(job_id, None)
    if state:
        shutil.rmtree(state['dir'], ignore_errors=True)


def sweep():
    while True:
        time.sleep(300)
        now = time.monotonic()
        for job_id, state in list(jobs.items()):
            if state.get('finished') and now - state['finished'] > RESULT_TTL:
                forget(job_id)


def public(state):
    view = {k: state.get(k) for k in ('status', 'stage', 'percent', 'clips_done', 'clips_total', 'error')}
    if state['status'] == 'completed':
        view['result'] = state['result']
    return view


@app.get('/health')
def health():
    return {'ok': True, 'service': 'clipper', 'engine': ENGINE_COMMIT[:7], 'busy': lock.locked(),
            'ready': len(os.getenv('CLIPPER_TOKEN', '')) >= 32 and bool(os.getenv('OPENROUTER_API_KEY'))}


@app.post('/jobs/{job_id}', status_code=202, dependencies=[Depends(authorized)])
def start(job_id: UUID, request: JobRequest):
    if not source_allowed(request.source_url):
        raise HTTPException(422, 'Source link not allowed')
    if not os.getenv('OPENROUTER_API_KEY'):
        raise HTTPException(503, 'Clip service is missing its AI key')
    key = str(job_id)
    if key in jobs:
        raise HTTPException(409, 'Job already exists')
    if not lock.acquire(blocking=False):
        raise HTTPException(409, 'Clip service busy')
    try:
        job_dir = ROOT / key
        shutil.rmtree(job_dir, ignore_errors=True)
        job_dir.mkdir(parents=True)
        state = {'status': 'working', 'stage': 'downloading', 'percent': 0.0, 'clips_done': 0, 'clips_total': 0,
                 'error': None, 'dir': job_dir, 'cancel': threading.Event(), 'started': time.monotonic()}
        jobs[key] = state
        threading.Thread(target=work, args=(key, request, state), daemon=True).start()
    except BaseException:
        jobs.pop(key, None)
        lock.release()
        raise
    return {'accepted': True}


@app.get('/jobs/{job_id}', dependencies=[Depends(authorized)])
def status(job_id: UUID):
    state = jobs.get(str(job_id))
    if not state:
        raise HTTPException(404, 'Job not found')
    return public(state)


@app.get('/jobs/{job_id}/files/{name}', dependencies=[Depends(authorized)])
def file(job_id: UUID, name: str):
    state = jobs.get(str(job_id))
    if not state or state['status'] != 'completed' or not FILE_NAME.match(name):
        raise HTTPException(404, 'File not found')
    path = state['clip_dir'] / name
    if not path.is_file():
        raise HTTPException(404, 'File not found')
    return FileResponse(path, media_type='video/mp4' if name.endswith('.mp4') else 'image/jpeg')


@app.delete('/jobs/{job_id}', dependencies=[Depends(authorized)])
def delete(job_id: UUID):
    key = str(job_id)
    state = jobs.get(key)
    if state and state['status'] == 'working':
        state['deleted'] = True
        state['cancel'].set()
    elif state:
        forget(key)
    return {'deleted': True}


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=sweep, daemon=True).start()
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8080')), log_level='info')


if __name__ == '__main__':
    main()
