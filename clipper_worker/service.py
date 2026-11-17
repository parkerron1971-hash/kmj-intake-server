"""Isolated clip-finding service for Video Clips. Holds an OpenRouter key only.

The API sends a short-lived signed link to one private recording. This service
downloads it, runs the pinned BridgeClip engine (vendor/bridgeclip, see
README.md), checks every finished clip for stretches with nobody on screen,
and keeps the clips until the API collects them. It has no database or storage
credentials, runs one job at a time, and forgets a job when the API deletes it
or when it is RESULT_TTL seconds old.

It also makes a service recording's smaller copy (POST /copies/<job>, the API's
recording_copy.py): the API sends the recording's playlist with every segment
signed and a signed upload link, and this service reads the segments, encodes
one 720p MP4 and uploads it. Copies share the one-job rule, and a clip job
always goes first: a clip job that arrives while a copy is being made stops
the copy (job.yielded) and takes its turn.
"""
import base64
import hashlib
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
from fastapi.responses import FileResponse, Response
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
# The smaller copy of a service recording (POST /copies/<job>).
COPY_SECONDS = int(os.getenv('CLIPPER_COPY_SECONDS', '10800'))
COPY_MAX_SECONDS = int(os.getenv('CLIPPER_COPY_MAX_SECONDS', str(6 * 3600)))
COPY_STALL_SECONDS = 600              # nothing new encoded this long: the reading stalled
COPY_MAX_BYTES = 5 * 1024 ** 3        # one PUT
COPY_PLAYLIST_CHARS = 8_000_000       # ~1 MB is a 2-hour service
YIELD_WAIT_SECONDS = 30               # a copy stops within seconds when a clip job needs the service
# About 720p, the aspect kept, never upscaled: a landscape picture fits in
# 1280x720, a portrait one in 720x1280.
COPY_SCALE = ("scale=w='if(gte(iw,ih),min(1280,iw),min(720,iw))':h='if(gte(iw,ih),min(720,ih),min(1280,ih))'"
              ":force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p")
# ffmpeg's HLS reader skips a segment it can't read and carries on (exit 0):
# that is a copy with a hole in it, so it fails the job.
SEGMENT_LOST = ('Failed to open segment', 'failed too many times', 'Failed to reload playlist')
CAPTION_PRESETS = ('pop', 'spotlight', 'impact', 'glow', 'boxed', 'sweep', 'editorial', 'hype', 'punch', 'neon', 'headline', 'paper', 'subtle')
FILE_NAME = re.compile(r'^clip_\d{2}(\.mp4|\.jpg|_frame\.jpg|_face\.jpg)$')
# Only these reach the engine process; the service token never does.
ENGINE_ENV_KEEP = ('PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'FONTCONFIG_FILE', 'SYSTEMROOT', 'WINDIR', 'USERPROFILE', 'LOCALAPPDATA')

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
log = logging.getLogger('clipper')
lock = threading.Lock()
# POST /faces runs beside a job; two at a time keeps it from crowding one.
FACE_SLOTS = 2
face_slots = threading.BoundedSemaphore(FACE_SLOTS)
jobs = {}
# The job holding `lock` (its state), so a clip job can ask a copy to make way.
holder = {'state': None}


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


class CopyRequest(BaseModel):
    """A service recording's smaller copy: its playlist with every segment a
    signed https link, the signed link to upload the MP4 to, and how long the
    recording is (for the progress)."""
    model_config = ConfigDict(extra='forbid')
    playlist: str = Field(min_length=8, max_length=COPY_PLAYLIST_CHARS)
    upload_url: str = Field(max_length=4096)
    seconds: float = Field(gt=0, le=COPY_MAX_SECONDS)


class FaceRequest(BaseModel):
    """Face close-ups for a clip: the clip's stretch of the recording (or the
    clip itself), read over the network. count 1 answers one JPEG; more
    answers JSON with up to that many, best first."""
    model_config = ConfigDict(extra='forbid')
    source_url: str = Field(max_length=4096)
    start: float = Field(ge=0, le=MAX_SOURCE_SECONDS)
    end: float = Field(gt=0, le=MAX_SOURCE_SECONDS)
    count: int = Field(default=1, ge=1, le=3)


class LikenessRequest(BaseModel):
    """A finished cover and the photos of the person it must look like, as
    base64 images (JPEG or PNG)."""
    model_config = ConfigDict(extra='forbid')
    image_b64: str = Field(max_length=16_000_000)
    references_b64: list[str] = Field(min_length=1, max_length=4)


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


def source_allowed(url, hosts_env='CLIPPER_SOURCE_HOSTS'):
    """Signed links from our own storage only: https, an approved host, no
    credentials. Clip jobs and close-ups read CLIPPER_SOURCE_HOSTS; a copy's
    segments and its upload read CLIPPER_COPY_HOSTS (the media bucket's host
    alone), so allowing copies never widens what a clip job may fetch."""
    hosts = {h.strip().lower() for h in os.getenv(hosts_env, '').split(',') if h.strip()}
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
    if time.monotonic() - state['started'] > state.get('limit', JOB_SECONDS):
        raise JobError(state.get('too_long', 'Finding clips took too long and was stopped.'), state['stage'], 'job.timeout')


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


def grab_frame(args, target):
    """One ffmpeg still. True only for a real picture: a non-zero exit or an
    empty file (a seek past the end) is removed, never advertised."""
    try:
        done = subprocess.run(args, capture_output=True, timeout=60)
        if done.returncode == 0 and Path(target).is_file() and Path(target).stat().st_size > 0:
            return True
    except (subprocess.SubprocessError, OSError):
        pass
    Path(target).unlink(missing_ok=True)
    return False


def make_poster(video, at, target):
    """Best effort: a clip without a poster still reaches review."""
    if not grab_frame(['ffmpeg', '-v', 'error', '-y', '-ss', f'{at:.2f}', '-i', str(video), '-frames:v', '1',
                       '-vf', 'scale=540:-2', '-q:v', '4', str(target)], target):
        log.warning('Poster frame failed for %s', video.name)


def make_frame(source, at, target):
    """The same moment as the poster, from the recording itself: no captions,
    no title card, full resolution (capped at 1920 wide). A cover is designed
    from this. Best effort, like the poster."""
    if not grab_frame(['ffmpeg', '-v', 'error', '-y', '-ss', f'{at:.2f}', '-i', str(source), '-frames:v', '1',
                       '-vf', "scale='min(1920,iw)':-2", '-q:v', '2', str(target)], target):
        log.warning('Clean frame failed at %.2fs', at)


def check_clips(state, manifest_path, source=None):
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
        frame = clip_dir / f'clip_{index:02d}_frame.jpg'
        face = clip_dir / f'clip_{index:02d}_face.jpg'
        if source is not None and source.is_file():
            # A clip is cut straight from [start, end] of the recording, so the
            # poster's moment in the clip is start + poster_at in the source.
            start = (row.get('start_time_ms') or 0) / 1000
            moment = start + found['poster_at']
            make_frame(source, moment, frame)
            # The cover's face is the best one anywhere in the clip, except in
            # a two-person shot, where another moment can be the other person.
            end = (row.get('end_time_ms') or 0) / 1000 or start + found['length']
            span = {} if row.get('layout_type') == 'two_shot' else {'start': start, 'end': end}
            try:
                empty_spots.face_closeup(source, moment, face, detector, **span)
            except Exception:  # best effort, like the poster: a cover still has the frame
                log.warning('Face close-up failed at %.2fs', moment)
                face.unlink(missing_ok=True)
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
            'frame': frame.name if frame.is_file() else None,
            'face': face.name if face.is_file() else None,
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
        if not final or final.get('type') != 'result':
            source.unlink(missing_ok=True)
            error = final or {}
            log_engine_tail(job_dir)
            raise JobError(error.get('message') or 'Finding clips failed. Try again.', error.get('stage') or state['stage'], error.get('code') or 'engine.failed')
        manifest = next((job_dir / 'out').rglob('job_output.json'), None)
        if manifest is None:
            raise JobError('Finding clips failed. Try again.', 'saving', 'engine.no_manifest')
        try:
            clip_dir, result = check_clips(state, manifest, source)
        finally:
            # Kept only long enough for the clean frames.
            source.unlink(missing_ok=True)
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
        release_lock()


def release_lock():
    holder['state'] = None
    lock.release()


def take_turn():
    """A clip job's turn while a copy holds the service: the copy stops (the
    API makes it again later, without counting it against the copy) and the
    lock passes to the clip job. True when the caller now holds the lock."""
    current = holder.get('state')
    if not current or current.get('kind') != 'copy':
        return False
    current['yielded'] = True
    current['cancel'].set()
    print('[clipper] a clip job came in; the copy being made stops and is made later', flush=True)
    return lock.acquire(timeout=YIELD_WAIT_SECONDS)


# -- a service recording's smaller copy -----------------------------------

def checked_playlist(text):
    """The recording's playlist as ffmpeg will read it, or None. Every line
    that isn't a tag must be a signed https link on CLIPPER_COPY_HOSTS; no tag
    may point anywhere (keys, maps, other playlists). It always ends with
    EXT-X-ENDLIST, so it is read from its start as a finished video, never
    as a live stream."""
    lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
    if not lines or lines[0] != '#EXTM3U':
        return None
    segments = 0
    for line in lines[1:]:
        if line.startswith('#'):
            if 'URI=' in line.upper() or line.upper().startswith('#EXT-X-STREAM-INF'):
                return None
            continue
        if not source_allowed(line, 'CLIPPER_COPY_HOSTS'):
            return None
        segments += 1
    if not segments:
        return None
    if '#EXT-X-ENDLIST' not in lines:
        lines.append('#EXT-X-ENDLIST')
    return '\n'.join(lines) + '\n'


def copy_cmd(playlist, target):
    """H.264 about 720p at ~1.5 Mbps and AAC 96 kbps, ready to play while it
    loads (+faststart). ffmpeg reads the local playlist, then only https."""
    return ['ffmpeg', '-nostdin', '-hide_banner', '-v', 'warning', '-y',
            '-protocol_whitelist', 'file,https,tls,tcp,crypto', '-seg_max_retry', '3',
            '-i', str(playlist), '-map', '0:v:0', '-map', '0:a:0?', '-vf', COPY_SCALE,
            '-c:v', 'libx264', '-preset', 'veryfast', '-profile:v', 'high',
            '-b:v', '1500k', '-maxrate', '2000k', '-bufsize', '3000k', '-g', '120',
            '-c:a', 'aac', '-b:a', '96k', '-ac', '2', '-movflags', '+faststart',
            '-progress', 'pipe:1', '-nostats', str(target)]


def run_copy(state, cmd, job_dir, seconds):
    """Run ffmpeg and follow its -progress lines. Stops on a cancel, the job's
    time limit, or COPY_STALL_SECONDS with nothing new encoded."""
    lines = queue.Queue()
    log_path = job_dir / 'ffmpeg.log'
    with open(log_path, 'w', encoding='utf-8') as ffmpeg_log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ffmpeg_log, stdin=subprocess.DEVNULL,
                                text=True, encoding='utf-8', errors='replace', start_new_session=os.name != 'nt')

        def reader():
            for line in proc.stdout:
                lines.put(line)
        follower = threading.Thread(target=reader, daemon=True)
        follower.start()
        moved, done_us = time.monotonic(), 0
        try:
            while True:
                try:
                    line = lines.get(timeout=0.5)
                except queue.Empty:
                    if not follower.is_alive() and lines.empty():
                        break
                    line = ''
                name, _, value = line.strip().partition('=')
                if name in ('out_time_us', 'out_time_ms') and value.isdigit() and int(value) > done_us:
                    done_us, moved = int(value), time.monotonic()
                    state['percent'] = round(min(89.0, 89 * done_us / 1e6 / seconds), 1)
                check_cancel(state)
                if time.monotonic() - moved > COPY_STALL_SECONDS:
                    raise JobError('Reading the recording stalled. It will be tried again.', 'making', 'copy.stalled')
            proc.wait(timeout=30)
        finally:
            stop(proc)
    said = log_path.read_text(encoding='utf-8', errors='replace')
    if proc.returncode != 0:
        print(f'[clipper] copy: ffmpeg exited {proc.returncode}: {said[-1500:]}', flush=True)
        raise JobError('The recording could not be read. It will be tried again.', 'making', 'copy.ffmpeg')
    if any(words in said for words in SEGMENT_LOST):
        print(f'[clipper] copy: part of the recording could not be read: {said[-1500:]}', flush=True)
        raise JobError('Part of the recording could not be read. It will be tried again.', 'making', 'copy.segment')


def probe_copy(path):
    """(seconds, width, height, has audio) of the finished copy."""
    try:
        done = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,width,height',
                               '-of', 'json', str(path)], capture_output=True, text=True, timeout=120)
        data = json.loads(done.stdout or '{}')
        seconds = float(data['format']['duration'])
    except (subprocess.SubprocessError, ValueError, KeyError, TypeError):
        raise JobError('The copy could not be checked.', 'checking', 'copy.unreadable') from None
    video = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
    if video is None or seconds <= 0:
        raise JobError('The copy has no video in it.', 'checking', 'copy.no_video')
    audio = any(s.get('codec_type') == 'audio' for s in data.get('streams', []))
    return seconds, int(video.get('width') or 0), int(video.get('height') or 0), audio


def upload(url, path, state, transport=None):
    """One PUT of the finished copy to its signed link (a whole file, its
    length declared: the bucket refuses a chunked upload). Returns the MD5,
    checked against the ETag the bucket answers for a single PUT."""
    size = path.stat().st_size
    digest = hashlib.md5()

    def chunks():
        sent = 0
        with open(path, 'rb') as content:
            while True:
                block = content.read(1024 * 1024)
                if not block:
                    return
                digest.update(block)
                sent += len(block)
                state['percent'] = round(90 + 9 * sent / max(size, 1), 1)
                check_cancel(state)
                yield block
    timeout = httpx.Timeout(60.0, write=300.0, read=300.0)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
            response = client.put(url, content=chunks(), headers={'Content-Length': str(size), 'Content-Type': 'video/mp4'})
    except httpx.HTTPError as error:
        raise JobError('The copy could not be saved. It will be tried again.', 'uploading', 'upload.failed') from error
    if response.status_code != 200:
        print(f'[clipper] copy upload answered {response.status_code}', flush=True)
        raise JobError('The copy could not be saved. It will be tried again.', 'uploading', 'upload.status')
    md5 = digest.hexdigest()
    etag = (response.headers.get('etag') or '').strip('"').lower()
    if etag and '-' not in etag and etag != md5:
        raise JobError('The copy was not saved whole. It will be tried again.', 'uploading', 'upload.mismatch')
    return md5


def work_copy(job_id, request, state):
    job_dir = state['dir']
    try:
        playlist = job_dir / 'recording.m3u8'
        playlist.write_text(state.pop('playlist'), encoding='utf-8')
        target = job_dir / 'copy.mp4'
        run_copy(state, copy_cmd(playlist, target), job_dir, request.seconds)
        state.update(stage='checking', percent=89.0)
        seconds, width, height, audio = probe_copy(target)
        size = target.stat().st_size
        if not size or size >= COPY_MAX_BYTES:
            raise JobError('The copy came out too large to save.', 'checking', 'copy.too_large')
        state.update(stage='uploading', percent=90.0)
        md5 = upload(request.upload_url, target, state)
        result = {'seconds': round(seconds, 2), 'bytes': size, 'width': width, 'height': height, 'audio': audio,
                  'md5': md5, 'timings': {'total': round(time.monotonic() - state['started'], 1)}}
        state.update(status='completed', stage='done', percent=100.0, result=result)
        print(f'[clipper] copy {job_id[:8]} saved: {size} bytes, {seconds:.0f} s, {width}x{height}, '
              f'{result["timings"]["total"]:.0f} s to make', flush=True)
    except Cancelled:
        if state.get('yielded'):
            state.update(status='cancelled', error={'message': 'Stopped so clips could be made; it is made again later.',
                                                    'stage': state['stage'], 'code': 'job.yielded'})
        else:
            state.update(status='cancelled', error={'message': 'Stopped.', 'stage': state['stage'], 'code': 'job.cancelled'})
    except JobError as error:
        print(f'[clipper] copy {job_id[:8]} failed: {error.code}', flush=True)
        state.update(status='failed', error={'message': error.message, 'stage': error.stage, 'code': error.code})
    except Exception as error:  # Never surface raw provider or path text.
        print(f'[clipper] copy {job_id[:8]} crashed ({type(error).__name__})', flush=True)
        state.update(status='failed', error={'message': 'Making the copy failed. It will be tried again.',
                                             'stage': state['stage'], 'code': 'job.crashed'})
    finally:
        state['finished'] = time.monotonic()
        # Nothing is kept here: the copy is in the bucket, or there is none.
        shutil.rmtree(job_dir, ignore_errors=True)
        if state.get('deleted'):
            jobs.pop(job_id, None)
        release_lock()


def public_copy(state):
    view = {k: state.get(k) for k in ('status', 'stage', 'percent', 'error')}
    if state['status'] == 'completed':
        view['result'] = state['result']
    return view


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
    current = holder.get('state') or {}
    token = len(os.getenv('CLIPPER_TOKEN', '')) >= 32
    return {'ok': True, 'service': 'clipper', 'engine': ENGINE_COMMIT[:7], 'busy': lock.locked(),
            'ready': token and bool(os.getenv('OPENROUTER_API_KEY')),
            'copies': token and bool(os.getenv('CLIPPER_COPY_HOSTS', '').strip()),
            'job': current.get('kind') if lock.locked() else None}


@app.post('/jobs/{job_id}', status_code=202, dependencies=[Depends(authorized)])
def start(job_id: UUID, request: JobRequest):
    if not source_allowed(request.source_url):
        raise HTTPException(422, 'Source link not allowed')
    if not os.getenv('OPENROUTER_API_KEY'):
        raise HTTPException(503, 'Clip service is missing its AI key')
    key = str(job_id)
    if key in jobs:
        raise HTTPException(409, 'Job already exists')
    # Clips go first: a copy being made stops and gives up the service.
    if not lock.acquire(blocking=False) and not take_turn():
        raise HTTPException(409, 'Clip service busy')
    try:
        job_dir = ROOT / key
        shutil.rmtree(job_dir, ignore_errors=True)
        job_dir.mkdir(parents=True)
        state = {'status': 'working', 'stage': 'downloading', 'percent': 0.0, 'clips_done': 0, 'clips_total': 0,
                 'error': None, 'dir': job_dir, 'cancel': threading.Event(), 'started': time.monotonic(), 'kind': 'clips'}
        jobs[key] = state
        holder['state'] = state
        threading.Thread(target=work, args=(key, request, state), daemon=True).start()
    except BaseException:
        jobs.pop(key, None)
        release_lock()
        raise
    return {'accepted': True}


@app.post('/copies/{job_id}', status_code=202, dependencies=[Depends(authorized)])
def start_copy(job_id: UUID, request: CopyRequest):
    """Make one recording's smaller copy and upload it. 422 for a segment or
    an upload link off CLIPPER_COPY_HOSTS; 409 while any job runs (the API
    tries later)."""
    playlist = checked_playlist(request.playlist)
    if playlist is None or not source_allowed(request.upload_url, 'CLIPPER_COPY_HOSTS'):
        raise HTTPException(422, 'Source link not allowed')
    key = str(job_id)
    if key in jobs:
        raise HTTPException(409, 'Job already exists')
    if not lock.acquire(blocking=False):
        raise HTTPException(409, 'Clip service busy')
    try:
        job_dir = ROOT / key
        shutil.rmtree(job_dir, ignore_errors=True)
        job_dir.mkdir(parents=True)
        state = {'status': 'working', 'stage': 'making', 'percent': 0.0, 'error': None, 'dir': job_dir,
                 'cancel': threading.Event(), 'started': time.monotonic(), 'kind': 'copy', 'playlist': playlist,
                 'limit': COPY_SECONDS, 'too_long': 'Making the copy took too long and was stopped.'}
        jobs[key] = state
        holder['state'] = state
        threading.Thread(target=work_copy, args=(key, request, state), daemon=True).start()
    except BaseException:
        jobs.pop(key, None)
        release_lock()
        raise
    return {'accepted': True}


@app.get('/copies/{job_id}', dependencies=[Depends(authorized)])
def copy_status(job_id: UUID):
    state = jobs.get(str(job_id))
    if not state or state.get('kind') != 'copy':
        raise HTTPException(404, 'Job not found')
    return public_copy(state)


@app.delete('/copies/{job_id}', dependencies=[Depends(authorized)])
def copy_delete(job_id: UUID):
    key = str(job_id)
    state = jobs.get(key)
    if state and state.get('kind') == 'copy':
        drop(key, state)
    return {'deleted': True}


@app.post('/faces', dependencies=[Depends(authorized)])
def faces(request: FaceRequest):
    """The best face in [start, end] of the video at source_url, as a JPEG
    close-up (the same picker and crop as a clip run's clip_NN_face.jpg).
    404 when no usable face is there. Runs beside a job: its own detector,
    its own temporary folder, nothing kept."""
    if not source_allowed(request.source_url):
        raise HTTPException(422, 'Source link not allowed')
    if request.end <= request.start:
        raise HTTPException(422, 'The end must come after the start')
    # At most FACE_SLOTS at once beside a job: a sync endpoint uses the threadpool.
    if not face_slots.acquire(timeout=5):
        raise HTTPException(503, 'Busy making close-ups; try again')
    try:
        with tempfile.TemporaryDirectory(prefix='clipper-face-') as folder:
            target = Path(folder) / 'face.jpg'
            try:
                frames = empty_spots.remote_frames(request.source_url, request.start, min(request.end, request.start + 600), folder)
            except empty_spots.FramesUnreadable as error:
                # Not a verdict on the clip: the caller may ask again.
                raise HTTPException(502, str(error)) from None
            if request.count > 1:
                found = []
                for _, frame, box in empty_spots.best_faces(frames, empty_spots.detector(), request.count):
                    jpeg = encode_jpeg(empty_spots.closeup_image(frame, box))
                    if jpeg:
                        found.append({'jpeg_b64': base64.b64encode(jpeg).decode(), 'size': [round(box[2]), round(box[3])]})
                if not found:
                    raise HTTPException(404, 'No usable face in that stretch')
                return {'faces': found}
            size = empty_spots.pick_closeup(frames, target, empty_spots.detector())
            if not size or not target.is_file():
                raise HTTPException(404, 'No usable face in that stretch')
            return Response(content=target.read_bytes(), media_type='image/jpeg', headers={'X-Face-Size': f'{size[0]}x{size[1]}'})
    finally:
        face_slots.release()


def encode_jpeg(image):
    if image is None:
        return None
    import cv2
    ok, data = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return data.tobytes() if ok else None


def decode_image(text):
    try:
        raw = base64.b64decode(text, validate=True)
    except ValueError:
        raise HTTPException(422, 'An image is not valid base64') from None
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(422, 'An image could not be read')
    return image


@app.post('/likeness', dependencies=[Depends(authorized)])
def likeness_check(request: LikenessRequest):
    """How much the face on a finished cover looks like the person in the
    reference photos (face recognition, SFace cosine; see empty_spots)."""
    image = decode_image(request.image_b64)
    references = [decode_image(text) for text in request.references_b64]
    if not face_slots.acquire(timeout=5):
        raise HTTPException(503, 'Busy; try again')
    try:
        score, scores = empty_spots.likeness(image, references, empty_spots.recognizer())
    finally:
        face_slots.release()
    return {'score': score, 'scores': scores, 'face_found': score is not None}


def clip_job(job_id):
    """A clip job's state; a copy is never one (it has its own routes)."""
    state = jobs.get(str(job_id))
    return state if state and state.get('kind', 'clips') == 'clips' else None


@app.get('/jobs/{job_id}', dependencies=[Depends(authorized)])
def status(job_id: UUID):
    state = clip_job(job_id)
    if not state:
        raise HTTPException(404, 'Job not found')
    return public(state)


@app.get('/jobs/{job_id}/files/{name}', dependencies=[Depends(authorized)])
def file(job_id: UUID, name: str):
    state = clip_job(job_id)
    if not state or state['status'] != 'completed' or not FILE_NAME.match(name):
        raise HTTPException(404, 'File not found')
    path = state['clip_dir'] / name
    if not path.is_file():
        raise HTTPException(404, 'File not found')
    return FileResponse(path, media_type='video/mp4' if name.endswith('.mp4') else 'image/jpeg')


def drop(key, state):
    """Stop a running job (it forgets itself once stopped), or forget a
    finished one and its files."""
    if state['status'] == 'working':
        state['deleted'] = True
        state['cancel'].set()
    else:
        forget(key)


@app.delete('/jobs/{job_id}', dependencies=[Depends(authorized)])
def delete(job_id: UUID):
    key = str(job_id)
    state = clip_job(key)
    if state:
        drop(key, state)
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
