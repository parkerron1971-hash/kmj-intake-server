"""
recording_copy.py — one smaller MP4 of every service recording, which is
also its download (Kevin approved this on 2026-11-17: "build").

THE PROMISES (Kevin's words)
  "Two weeks after a service, its recording is saved again at a smaller
   size (about 1.3 GB instead of 6), and it still looks right on a phone.
   Clips get cut before then, from the full-quality copy."
  "Every recording gets a Download button, so deleting never means losing
   it."

THE COPY
  One MP4 per recording, live/<business>/<session>/copy.mp4, in the same
  private media bucket and the same folder as the recording's segments, so
  deleting the recording (church_storage.remove_recording lists and deletes
  the whole folder) takes the copy with it. H.264 at about 720p (aspect
  kept, never upscaled), ~1.5 Mbps video, AAC 96 kbps, +faststart: about
  0.7 GB an hour, 1.3-1.4 GB for a two-hour service.

WHO MAKES IT
  The clip service (clipper_worker, POST /copies/<job>). It holds no storage
  key: this module hands it the recording's playlist with every segment
  signed (the read key) and a signed PUT for copy.mp4 (the write key), both
  good for JOB_LINK_S, then follows the job. The clip service runs one job
  at a time and "Find my best clips" always goes first: no copy is started
  while a clip run is queued or working, and a clip run that reaches the
  clip service while a copy is being made stops the copy (the clip
  service's own rule, job.yielded). A copy that yielded is made again later
  and the try isn't counted.

THE STEPS (copy_tick, every 2 minutes on the worker; the stream_sessions
columns are APPLY-2026-11-17-recording-small-copy.sql's)
  copy_state  null     no copy yet: the oldest ended recordings go first
              queued   claimed, being handed to the clip service
              working  the clip service has it
              ready    made AND checked: its size read back from the bucket
                       matches what the clip service uploaded, and its
                       length is within 2% (10 s at least) of the
                       recording's own duration_s
              failed   a try failed (copy_error says why); tried again an
                       hour later, MAX_TRIES tries in all
  copy_job (the clip service's job id), copy_tries, copy_at (when the state
  last moved), copy_bytes and copy_seconds (only once ready), copy_made_at,
  copy_error, full_removed_at. Every move is a conditional write on the job
  id and the state it moves from, so a second replica, a retry or an API
  restart can never make, count or remove anything twice. A recording the
  church deletes while its copy is being made is tidied: the job is stopped
  and a copy that landed anyway is deleted.

DAY 14 (trim)
  Once a copy is ready and its service ended KEEP_FULL_DAYS ago, the
  full-quality segments and playlist (the .ts and .m3u8 objects in the
  folder, never copy.mp4) are deleted and full_removed_at is set, only
  after the copy is read back from the bucket at its recorded size. From
  day 14 the watch page plays the copy (play_link), also while the removal
  is still pending, and with the switch off once the segments are gone.

THE METER (church_storage.stored_bytes)
  bytes + copy_bytes while the full recording is there, copy_bytes after
  full_removed_at. A copy therefore takes its room on top of the recording
  for its first 14 days. bytes_per_sunday stays the full size.

CLIPS
  "Find my best clips" makes clips from recordings uploaded to the media
  library (clip_finder), not from these service recordings: today nothing
  turns a relay recording into a clip source. When something does, it must
  read the full-quality recording while it exists (full_removed_at null)
  and the copy after.

THE SWITCH
  CHURCH_STORAGE_SMALL_COPY: off (the default) | owner (the platform owner's
  churches, member_asks.platform_church) | on, and only where CHURCH_STORAGE
  is on too. Making copies also needs the write key, the clip service
  (CLIPPER_URL, CLIPPER_TOKEN) and, on the clip service, CLIPPER_COPY_HOSTS
  (the bucket's host). Off: nothing is made or removed, can_download is
  false, no download links. Everything worth knowing in production is
  print()ed with [recording_copy] (Railway shows print only).
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

COPY_NAME = "copy.mp4"
KEEP_FULL_DAYS = 14
MAX_TRIES = 3
RETRY_AFTER = timedelta(hours=1)
STUCK_AFTER = timedelta(hours=4)        # the clip service stops its own job at 3 hours
JOB_LINK_S = 4 * 3600                   # the clip service's segment links and upload link
DOWNLOAD_LINK_S = 3600
PLAY_LINK_S = 4 * 3600                  # as long as a playlist's segment links
HEAD_LINK_S = 300
LENGTH_SLACK = 0.02
LENGTH_SLACK_MIN_S = 10
MAX_COPY_SECONDS = 6 * 3600             # the clip service's own limit (a single upload stays under 5 GB)
START_LOOK = 5                          # recordings tried per start
TRIM_PER_TICK = 3
CLIP_RUN_LIFE = timedelta(hours=2)      # claim_clip_run fails a run older than this
COLUMNS_RECHECK_S = 600
MISSING_SAY_S = 3600
NAME_MAX = 80

COPY_COLS = ("copy_state,copy_job,copy_tries,copy_at,copy_bytes,copy_seconds,copy_made_at,copy_error,"
             "full_removed_at")
COLS = ("id,business_id,status,bytes,duration_s,started_at,ended_at,sermon_id,playlist_path,removed_at,"
        + COPY_COLS)
BUSY = ("queued", "working")

_COLUMNS: Dict[str, Any] = {"there": None, "at": 0.0}
_SAID: Dict[str, float] = {}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _at(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _int(v: Any) -> int:
    try:
        return max(int(float(v or 0)), 0)
    except (TypeError, ValueError):
        return 0


def _num(v: Any) -> float:
    try:
        return max(float(v or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _say_once(what: str, text: str) -> None:
    """A misconfiguration, printed at most once an hour per process."""
    if time.monotonic() - _SAID.get(what, -MISSING_SAY_S) >= MISSING_SAY_S:
        _SAID[what] = time.monotonic()
        print(f"[recording_copy] {text}", flush=True)


# ─── The switch, and what it needs ───────────────────────────────────

def mode() -> str:
    m = (os.environ.get("CHURCH_STORAGE_SMALL_COPY") or "off").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(business_id: Any) -> bool:
    """Copies and downloads for this church: the switch says so (owner: the
    platform owner's churches) AND its storage allowance is switched on. A
    failed read is a no."""
    m = mode()
    if m == "off":
        return False
    import church_storage
    if not church_storage.switched_on(business_id):
        return False
    if m == "on":
        return True
    import member_asks
    return member_asks.platform_church(business_id)


def clip_service_set() -> bool:
    return bool((os.environ.get("CLIPPER_URL") or "").strip()) and len(os.environ.get("CLIPPER_TOKEN", "")) >= 32


def ready() -> bool:
    """Everything making a copy needs on this server: the media bucket's read
    key (the stream relay is ready), the write key, the clip service."""
    import stream_relay_router as sr
    return sr.is_ready() and sr.r2_write_config() is not None and clip_service_set()


def downloads_on(business_id: Any) -> bool:
    """The storage page offers downloads (can_download)."""
    import stream_relay_router as sr
    return sr.is_ready() and switched_on(business_id)


def copy_columns() -> Optional[bool]:
    """Whether stream_sessions has the copy columns (the migration is
    applied). True is kept for good, False for COLUMNS_RECHECK_S; None when
    it couldn't be told (a failed read that wasn't "no such column")."""
    if _COLUMNS["there"] is True:
        return True
    if _COLUMNS["there"] is False and time.monotonic() - _COLUMNS["at"] < COLUMNS_RECHECK_S:
        return False
    rows = sb_clients.sb_get_as_service("/stream_sessions?select=id,full_removed_at&limit=1")
    if isinstance(rows, list):
        there = True
    elif (sb_clients.last_error() or {}).get("code") in ("42703", "PGRST204"):   # no such column
        there = False
    else:
        return None
    _COLUMNS.update(there=there, at=time.monotonic())
    return there


# ─── One recording's copy ────────────────────────────────────────────

def folder(business_id: Any, s: Dict[str, Any]) -> Optional[str]:
    """The recording's folder, live/<business>/<session>/, by the same rule
    as church_storage.recording_prefix (only where the relay writes, never a
    stored path anywhere else), without its print: the copy job asks about
    every recording every few minutes."""
    import stream_relay_router as sr
    biz, sid = str(business_id or "").lower(), str(s.get("id") or "").lower()
    if not sr.UUID_RE.match(sid) or not sr.UUID_RE.match(biz):
        return None
    expected = sr.playlist_path(biz, sid)
    if (str(s.get("playlist_path") or "").strip() or expected) != expected:
        return None
    return expected[: -len("index.m3u8")]


def copy_key(business_id: Any, s: Dict[str, Any]) -> Optional[str]:
    """live/<business>/<session>/copy.mp4, in the recording's own folder
    (None for a recording stored anywhere unexpected, which never gets a
    copy)."""
    prefix = folder(business_id, s)
    return prefix + COPY_NAME if prefix else None


def copy_ready(s: Dict[str, Any]) -> bool:
    return s.get("copy_state") == "ready" and _int(s.get("copy_bytes")) > 0


def length_ok(copy_seconds: Any, duration_s: Any) -> bool:
    """The copy runs as long as the recording, within 2% (10 s at least)."""
    want, got = _num(duration_s), _num(copy_seconds)
    if want <= 0 or got <= 0:
        return False
    return abs(got - want) <= max(want * LENGTH_SLACK, LENGTH_SLACK_MIN_S)


def plays_copy(s: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """The watch page plays the copy: once the full-quality segments are
    gone, or once a checked copy is the one that stays (KEEP_FULL_DAYS after
    the service, also while the removal is pending)."""
    if s.get("full_removed_at"):
        return True
    if not copy_ready(s):
        return False
    ended = _at(s.get("ended_at"))
    return ended is not None and ended <= _now(now) - timedelta(days=KEEP_FULL_DAYS)


def copy_row(sid: str) -> Optional[Dict[str, Any]]:
    """A session's copy columns, read fresh. None before the migration and
    on a failed read (the full recording plays)."""
    if copy_columns() is not True:
        return None
    rows = sb_clients.sb_get_as_service(
        f"/stream_sessions?id=eq.{_q(sid)}&select=id,ended_at,{COPY_COLS}&limit=1")
    return rows[0] if isinstance(rows, list) and rows else None


def play_link(business_id: str, s: Dict[str, Any], now: Optional[datetime] = None) -> Optional[str]:
    """The watch page's link to the copy (the read key, PLAY_LINK_S), or None
    while the full recording is the one to play. The caller has already
    checked this request may watch (stream_relay_router.media_access)."""
    import stream_relay_router as sr
    row = copy_row(str(s.get("id") or "").lower())
    if not row or not plays_copy({**s, **row}, now):
        return None
    key = copy_key(business_id, s)
    return sr.r2_link(key, PLAY_LINK_S) if key else None


# ─── The download ────────────────────────────────────────────────────

_UNSAFE = re.compile(r'[\x00-\x1f\x7f"\\/:*?<>|;%]+')


def church_label(business_id: str) -> Tuple[str, Any]:
    """(the church's name, its clock) for the download's file name; a
    generic name and UTC when they can't be read (the link still works)."""
    name, tz = "", timezone.utc
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(business_id)}&select=id,owner_id,name,settings&limit=1")
    if isinstance(rows, list) and rows:
        name = str(rows[0].get("name") or "")
        try:
            import business_marketing
            tz = business_marketing.business_tz(rows[0])
        except Exception:  # noqa: BLE001  (a clock that can't be read: the date on UTC)
            tz = timezone.utc
    return name, tz


def disposition(church: str, started: Any, tz: Any) -> str:
    """attachment; filename="<Church> <date>.mp4", the date the service
    started on the church's clock (2026-11-22). Plain ASCII in filename=,
    and the church's own spelling in filename*= when it has other letters."""
    day = (_at(started) or datetime.now(timezone.utc)).astimezone(tz).date().isoformat()
    own = " ".join(_UNSAFE.sub(" ", church or "").split())[:NAME_MAX].strip() or "Service recording"
    plain = " ".join(unicodedata.normalize("NFKD", own).encode("ascii", "ignore").decode("ascii").split())
    plain = plain or "Service recording"
    out = f'attachment; filename="{plain} {day}.mp4"'
    if plain != own:
        out += f"; filename*=UTF-8''{quote(f'{own} {day}.mp4', safe='')}"
    return out


def download_link(business_id: str, s: Dict[str, Any], church: str, tz: Any,
                  when: Optional[datetime] = None) -> Optional[str]:
    """A private https link that saves the copy as a file, good for an hour
    (the read key). None until the copy is ready."""
    import stream_relay_router as sr
    key = copy_key(business_id, s) if copy_ready(s) else None
    if not key:
        return None
    url = sr.r2_link(key, DOWNLOAD_LINK_S, when=when, query={
        "response-content-disposition": disposition(church, s.get("started_at"), tz),
        "response-content-type": "video/mp4"})
    return url if url.startswith("https://") else None


# ─── The bucket (the copy's size, deleting it) ───────────────────────

def head_size(key: str) -> Optional[int]:
    """The copy's size as the bucket has it: 0 when it isn't there, None
    when the bucket couldn't be asked."""
    import church_storage as cs
    import stream_relay_router as sr
    try:
        with cs._client() as client:
            r = client.request("HEAD", sr.r2_link(key, HEAD_LINK_S, method="HEAD"))
    except Exception as e:  # noqa: BLE001
        print(f"[recording_copy] size check failed: {type(e).__name__}", flush=True)
        return None
    if r.status_code == 404:
        return 0
    if r.status_code != 200:
        print(f"[recording_copy] size check answered {r.status_code}", flush=True)
        return None
    try:
        return int(r.headers.get("content-length") or 0)
    except (TypeError, ValueError):
        return None


def delete_copy(key: Optional[str]) -> bool:
    """The copy's object gone (or never there)."""
    if not key:
        return True
    import church_storage as cs
    with cs._client() as client:
        return cs._delete_all(client, [key])


def full_keys(prefix: str, keys: List[str]) -> List[str]:
    """The full-quality recording in a folder listing: its segments and
    playlist, directly in the folder. Never copy.mp4, nothing else."""
    out = []
    for k in keys:
        rest = k[len(prefix):] if k.startswith(prefix) else ""
        if rest and "/" not in rest and rest != COPY_NAME and rest.endswith((".ts", ".m3u8")):
            out.append(k)
    return out


# ─── The clip service ────────────────────────────────────────────────

def _clipper(method: str, path: str, **kwargs):
    import clip_finder
    return clip_finder.clipper(method, path, **kwargs)


def clips_waiting(now: Optional[datetime] = None) -> Optional[bool]:
    """A "Find my best clips" run is queued or working (they go first). Only
    runs from the last CLIP_RUN_LIFE count: claim_clip_run fails anything
    older, so a run left queued while clips are switched off never holds
    copies back for good. None when it couldn't be read: no copy starts on
    a guess."""
    since = _q(_iso(_now(now) - CLIP_RUN_LIFE))
    rows = sb_clients.sb_get_as_service(
        f"/media_clip_runs?status=in.(queued,working)&created_at=gte.{since}&select=id&limit=1")
    return bool(rows) if isinstance(rows, list) else None


def clipper_idle() -> bool:
    """The clip service answers, is not busy, and takes copies."""
    try:
        r = _clipper("GET", "/health")
        body = r.json() if r.status_code == 200 else {}
    except Exception as e:  # noqa: BLE001
        print(f"[recording_copy] clip service not reached: {type(e).__name__}", flush=True)
        return False
    if not isinstance(body, dict):
        return False
    if body.get("copies") is not True:
        _say_once("hosts", "the clip service doesn't take copies yet (CLIPPER_COPY_HOSTS)")
        return False
    return body.get("busy") is False


def _forget_job(job: Any) -> None:
    if not job:
        return
    try:
        _clipper("DELETE", f"/copies/{job}")
    except Exception as e:  # noqa: BLE001  (it forgets on its own after a couple of hours)
        print(f"[recording_copy] clip service job not forgotten: {type(e).__name__}", flush=True)


# ─── Moving a copy along ─────────────────────────────────────────────

def _path(s: Dict[str, Any]) -> str:
    return f"/stream_sessions?id=eq.{_q(s['id'])}&business_id=eq.{_q(s['business_id'])}"


def _on_job(s: Dict[str, Any]) -> str:
    """The write only lands while this try is still the one under way."""
    return f"{_path(s)}&copy_job=eq.{_q(s.get('copy_job'))}&copy_state=in.(queued,working)"


def _sid8(s: Dict[str, Any]) -> str:
    return str(s.get("id") or "")[:8]


def _claim(s: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    """This try is ours: from no copy (or a failed one) to queued, with a
    new job id and the try counted. None when another got there first."""
    n = _int(s.get("copy_tries"))
    was = "copy_state=is.null" if s.get("copy_state") is None else "copy_state=eq.failed"
    body = {"copy_state": "queued", "copy_job": str(uuid.uuid4()), "copy_tries": n + 1,
            "copy_at": _iso(now), "copy_error": None}
    got = sb_clients.sb_patch_as_service(
        f"{_path(s)}&status=eq.ended&removed_at=is.null&full_removed_at=is.null&{was}&copy_tries=eq.{n}", body)
    return {**s, **body} if isinstance(got, list) and got else None


def _revert(s: Dict[str, Any], now: datetime, why: str) -> str:
    """Not this try's fault (the clip service was busy, a clip run came
    first, a read failed): back to where it was, the try not counted."""
    n = _int(s.get("copy_tries"))
    sb_clients.sb_patch_as_service(_on_job(s), {
        "copy_state": None if n <= 1 else "failed", "copy_tries": max(n - 1, 0), "copy_at": _iso(now)})
    print(f"[recording_copy] copy of {_sid8(s)} waits: {why}", flush=True)
    return "waiting"


def _fail(s: Dict[str, Any], why: str, now: datetime) -> str:
    """This try failed (it stays counted). Tried again RETRY_AFTER later,
    MAX_TRIES tries in all; the full recording is kept meanwhile."""
    got = sb_clients.sb_patch_as_service(_on_job(s), {
        "copy_state": "failed", "copy_at": _iso(now), "copy_error": why[:300]})
    if not isinstance(got, list):
        return "working"                     # not saved: the next tick sees it again
    left = MAX_TRIES - _int(s.get("copy_tries"))
    print(f"[recording_copy] copy of {_sid8(s)} failed ({why}); "
          f"{f'{left} more tries' if left > 0 else 'no more tries'}", flush=True)
    return "failed"


def _tidy_removed(s: Dict[str, Any], now: datetime) -> str:
    """The church deleted the recording while its copy was being made: a
    copy that landed after the folder was emptied is deleted too, then the
    try is closed. If the delete doesn't go through, the next tick tries."""
    if not delete_copy(copy_key(s["business_id"], s)):
        return "working"
    sb_clients.sb_patch_as_service(_on_job(s), {
        "copy_state": "failed", "copy_bytes": None, "copy_at": _iso(now),
        "copy_error": "the recording was deleted"})
    print(f"[recording_copy] {_sid8(s)} was deleted while its copy was made; tidied", flush=True)
    return "tidied"


def _fresh(s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(f"{_path(s)}&select={COLS}&limit=1")
    if not isinstance(rows, list):
        return None
    return rows[0] if rows else {}


def _finish(s: Dict[str, Any], result: Dict[str, Any], now: datetime) -> str:
    """The clip service made and uploaded it: read its size back from the
    bucket and check its length, then it is ready. Anything that doesn't
    match fails this try and the object is deleted."""
    cur = _fresh(s)
    if cur is None:
        return "working"
    if not cur or cur.get("removed_at"):
        _forget_job(s.get("copy_job"))
        return _tidy_removed(s, now)
    key = copy_key(s["business_id"], s)
    size = head_size(key) if key else 0
    if size is None:
        return "working"                     # the clip service keeps the result for hours
    seconds = _num(result.get("seconds"))
    why = ""
    if size <= 0:
        why = "the copy wasn't in storage"
    elif size != _int(result.get("bytes")):
        why = "the copy in storage isn't the size that was made"
    elif not length_ok(seconds, s.get("duration_s")):
        why = f"the copy runs {seconds:.0f} s, the recording {_int(s.get('duration_s'))} s"
    if why:
        if size and not delete_copy(key):
            return "working"
        _forget_job(s.get("copy_job"))
        return _fail(s, why, now)
    stamp = _iso(now)
    got = sb_clients.sb_patch_as_service(f"{_on_job(s)}&removed_at=is.null", {
        "copy_state": "ready", "copy_bytes": size, "copy_seconds": round(seconds, 2), "copy_made_at": stamp,
        "copy_at": stamp, "copy_error": None})
    if not isinstance(got, list):
        return "working"
    if not got:
        again = _fresh(s)
        if again is not None and (not again or again.get("removed_at")):
            _forget_job(s.get("copy_job"))
            return _tidy_removed(s, now)
        return "working"
    _forget_job(s.get("copy_job"))
    print(f"[recording_copy] copy of {_sid8(s)} ready: {size} bytes ({_int(s.get('bytes'))} full), "
          f"{seconds:.0f} s, {result.get('width')}x{result.get('height')}", flush=True)
    return "made"


def follow(s: Dict[str, Any], now: datetime) -> str:
    """One copy under way, one step: "working" while it is, else what became
    of it (made, failed, waiting, tidied)."""
    job = s.get("copy_job")
    if not job:
        return _fail(s, "no job", now)
    try:
        r = _clipper("GET", f"/copies/{job}")
    except Exception as e:  # noqa: BLE001
        print(f"[recording_copy] clip service not reached: {type(e).__name__}", flush=True)
        r = None
    stuck = (_at(s.get("copy_at")) or now) < now - STUCK_AFTER
    if r is None or (r.status_code != 404 and r.status_code != 200):
        if stuck:
            _forget_job(job)
            return _fail(s, "the clip service didn't answer for hours", now)
        return "working"
    if r.status_code == 404:
        # Restarted, or never got it: this try is over.
        return _tidy_removed(s, now) if s.get("removed_at") else _fail(s, "the clip service lost it", now)
    try:
        st = r.json()
    except ValueError:
        return "working"
    status = st.get("status")
    error = st.get("error") or {}
    if status == "working":
        if s.get("removed_at"):
            _forget_job(job)                 # stops it; the next tick tidies up
            return "working"
        if stuck:
            _forget_job(job)
            return _fail(s, "it took too long", now)
        if s.get("copy_state") == "queued":
            sb_clients.sb_patch_as_service(_on_job(s), {"copy_state": "working", "copy_at": _iso(now)})
        return "working"
    if status == "completed":
        return _finish(s, st.get("result") or {}, now)
    _forget_job(job)
    if s.get("removed_at"):
        return _tidy_removed(s, now)
    if status == "cancelled" and error.get("code") == "job.yielded":
        return _revert(s, now, "a clip run came first")
    return _fail(s, str(error.get("message") or status or "it stopped")[:200], now)


def candidates(now: datetime) -> Optional[List[Dict[str, Any]]]:
    """Ended recordings with no copy (or a failed try due again), for
    churches where it is switched on, oldest first. None when a read failed."""
    import sample_church
    base = f"/stream_sessions?status=eq.ended&removed_at=is.null&full_removed_at=is.null&select={COLS}"
    due = _q(_iso(now - RETRY_AFTER))
    try:
        rows = (sb_clients.sb_get_all_as_service(f"{base}&copy_state=is.null", key="id", strict=True) or [])
        rows += (sb_clients.sb_get_all_as_service(
            f"{base}&copy_state=eq.failed&copy_tries=lt.{MAX_TRIES}&copy_at=lt.{due}",
            key="id", strict=True) or [])
    except Exception as e:  # noqa: BLE001
        print(f"[recording_copy] recordings not read: {type(e).__name__}", flush=True)
        return None
    on: Dict[str, bool] = {}
    out = []
    for s in sample_church.drop_samples(rows):
        biz = str(s.get("business_id") or "")
        if biz not in on:
            on[biz] = switched_on(biz)
        if (on[biz] and s.get("ended_at") and _int(s.get("bytes")) > 0
                and 0 < _num(s.get("duration_s")) <= MAX_COPY_SECONDS and folder(biz, s)):
            out.append(s)
    out.sort(key=lambda s: str(s.get("ended_at") or ""))
    return out


def _hand_over(s: Dict[str, Any], now: datetime) -> str:
    """Give the clip service this try: the recording's playlist with every
    segment signed, and the signed upload. "started", "waiting" (put back,
    nothing counted) or "failed"."""
    import stream_relay_router as sr
    from fastapi import HTTPException
    key = copy_key(s["business_id"], s)
    if not key:
        return _fail(s, "the recording isn't where it should be", now)
    try:
        text = sr._playlist_text(s)
    except HTTPException:
        return _revert(s, now, "its playlist couldn't be read just now")
    if text is None:
        return _fail(s, "the recording's playlist is missing", now)
    folder = key[: -len(COPY_NAME)].rstrip("/")
    playlist = sr.sign_playlist(text, folder, lambda k: sr.r2_link(k, JOB_LINK_S))
    if not any(line and not line.startswith("#") for line in playlist.splitlines()):
        return _fail(s, "the recording's playlist has no video", now)
    if "#EXT-X-ENDLIST" not in playlist:
        playlist += "#EXT-X-ENDLIST\n"       # it is over: read from its start, never as live
    upload = sr.r2_write_link("PUT", key, expires=JOB_LINK_S)
    if upload is None:
        return _revert(s, now, "the key that may write isn't set")
    try:
        r = _clipper("POST", f"/copies/{s['copy_job']}",
                     json={"playlist": playlist, "upload_url": upload, "seconds": _num(s.get("duration_s"))})
    except Exception as e:  # noqa: BLE001
        # It may have it or not: the next tick asks it (a lost try fails, counted).
        print(f"[recording_copy] copy of {_sid8(s)} handed over without an answer: {type(e).__name__}",
              flush=True)
        return "started"
    if r.status_code == 202:
        sb_clients.sb_patch_as_service(_on_job(s), {"copy_state": "working", "copy_at": _iso(now)})
        print(f"[recording_copy] making the copy of {_sid8(s)} ({_int(s.get('duration_s'))} s, "
              f"try {_int(s.get('copy_tries'))})", flush=True)
        return "started"
    if r.status_code == 409 or r.status_code >= 500:
        return _revert(s, now, f"the clip service answered {r.status_code}")
    return _fail(s, f"the clip service refused it ({r.status_code})", now)


def start_next(now: datetime) -> bool:
    """Start one copy, when no clip run is waiting and the clip service is
    free. True when one was handed over."""
    if clips_waiting(now) is not False or not clipper_idle():
        return False
    rows = candidates(now)
    for s in (rows or [])[:START_LOOK]:
        mine = _claim(s, now)
        if mine is None:
            continue
        got = _hand_over(mine, now)
        if got == "started":
            return True
        if got == "waiting":
            return False
    return False


def trim_one(s: Dict[str, Any], now: datetime) -> bool:
    """Day 14 for one recording: its copy read back at its recorded size,
    then the full-quality segments and playlist deleted, then
    full_removed_at. Anything short of that changes nothing."""
    import church_storage as cs
    sid8 = _sid8(s)
    if not copy_ready(s) or not length_ok(s.get("copy_seconds"), s.get("duration_s")):
        print(f"[recording_copy] {sid8}: the copy isn't checked; the full recording stays", flush=True)
        return False
    key = copy_key(s["business_id"], s)
    if not key:
        return False
    size = head_size(key)
    if size is None:
        return False
    if size != _int(s.get("copy_bytes")):
        # Gone or changed: it is made again, and the full recording stays.
        sb_clients.sb_patch_as_service(
            f"{_path(s)}&copy_state=eq.ready&full_removed_at=is.null",
            {"copy_state": "failed", "copy_bytes": None, "copy_seconds": None, "copy_at": _iso(now),
             "copy_error": "the copy in storage didn't match"})
        print(f"[recording_copy] {sid8}: the copy in storage didn't match ({size} bytes); made again", flush=True)
        return False
    prefix = key[: -len(COPY_NAME)]
    with cs._client() as client:
        keys = cs._list(client, prefix)
        if keys is None:
            return False
        full = full_keys(prefix, keys)
        if not cs._delete_all(client, full):
            return False
    got = sb_clients.sb_patch_as_service(
        f"{_path(s)}&copy_state=eq.ready&full_removed_at=is.null&removed_at=is.null",
        {"full_removed_at": _iso(now)})
    if not isinstance(got, list):
        return False
    cs._forget(str(s["id"]).lower())
    if got:
        print(f"[recording_copy] {sid8}: full-quality recording removed after {KEEP_FULL_DAYS} days "
              f"({len(full)} files, {_int(s.get('bytes'))} bytes); its {_int(s.get('copy_bytes'))}-byte "
              f"copy stays", flush=True)
    return bool(got)


def trim(now: datetime) -> Optional[int]:
    """Day 14, a few recordings a tick. None when the read failed."""
    import sample_church
    cutoff = _q(_iso(now - timedelta(days=KEEP_FULL_DAYS)))
    try:
        rows = sb_clients.sb_get_all_as_service(
            f"/stream_sessions?status=eq.ended&copy_state=eq.ready&full_removed_at=is.null&removed_at=is.null"
            f"&ended_at=lt.{cutoff}&select={COLS}", key="id", strict=True) or []
    except Exception as e:  # noqa: BLE001
        print(f"[recording_copy] day-14 read failed: {type(e).__name__}", flush=True)
        return None
    rows = [s for s in sample_church.drop_samples(rows) if switched_on(s.get("business_id"))]
    rows.sort(key=lambda s: str(s.get("ended_at") or ""))
    done = 0
    for s in rows[:TRIM_PER_TICK]:
        try:
            done += int(trim_one(s, now))
        except Exception as e:  # noqa: BLE001
            print(f"[recording_copy] day 14 for {_sid8(s)} stopped: {type(e).__name__}", flush=True)
    return done


def copy_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every couple of minutes, where the switch is on: follow the copy under
    way, take away the full recordings whose 14 days are up, and start the
    next copy when nothing else is running. One recording's failure never
    stops the rest."""
    out = {"working": 0, "made": 0, "failed": 0, "waiting": 0, "tidied": 0, "started": 0, "trimmed": 0,
           "errors": 0}
    if mode() == "off":
        return out
    if not ready():
        _say_once("ready", "switched on, but the write key or the clip service isn't set")
        return out
    there = copy_columns()
    if there is not True:
        if there is False:
            _say_once("columns", "switched on, but APPLY-2026-11-17-recording-small-copy.sql isn't applied")
        out["errors"] += 1
        return out
    stamp = _now(now)
    try:
        busy = sb_clients.sb_get_all_as_service(
            f"/stream_sessions?copy_state=in.(queued,working)&select={COLS}", key="id", strict=True) or []
    except Exception as e:  # noqa: BLE001
        print(f"[recording_copy] copies under way not read: {type(e).__name__}", flush=True)
        out["errors"] += 1
        return out
    for s in busy:
        try:
            got = follow(s, stamp)
        except Exception as e:  # noqa: BLE001
            print(f"[recording_copy] following {_sid8(s)} stopped: {type(e).__name__}: {e}", flush=True)
            got = "working"
            out["errors"] += 1
        out[got if got in out else "working"] += 1
    trimmed = trim(stamp)
    if trimmed is None:
        out["errors"] += 1
    else:
        out["trimmed"] = trimmed
    if not out["working"]:
        try:
            out["started"] = int(start_next(stamp))
        except Exception as e:  # noqa: BLE001
            print(f"[recording_copy] start stopped: {type(e).__name__}: {e}", flush=True)
            out["errors"] += 1
    if any(out[k] for k in ("made", "failed", "tidied", "started", "trimmed")):
        print(f"[recording_copy] tick: {out}", flush=True)
    return out
