"""relay_agent.py — the stream relay's brain, beside MediaMTX on the droplet.

A church's streaming software sends one stream to
rtmps://stream.<domain>:443/live with its stream key, `<stream id>?key=<secret>`.
MediaMTX receives it on the path live/<stream id> (not a secret: MediaMTX
logs paths) and hands the secret only to this agent, in the auth request's
query. The agent does everything else:

  * decides who may stream (MediaMTX asks POST /auth; the backend knows the
    keys). A key the backend confirmed in the last OFFLINE_GRANT_S (a day
    unless set) keeps working while the backend can't be reached, so a
    Sunday doesn't depend on Railway — but never past that window, and
    never once the backend has said no. Every GRANT_SYNC_S (an hour) the
    agent re-confirms each key it remembers (POST /relay/confirm, sending
    only sha256 of the secret, as the backend stores it): a confirmed key's
    window starts again, and a key the backend leaves out is forgotten at
    once — a replaced key, or streaming switched off, stops within the hour
    while the backend is up. The window binds a stream already running too:
    each confirmation (the heartbeat's, the re-check's) moves its deadline,
    and when the backend has been silent that long the publisher is
    disconnected and every copy and the recording stop, on the agent's own
    clock, whether or not MediaMTX's API answers;
  * notices a stream come up (MediaMTX's local API lists publishers and
    their query), and starts one ffmpeg per destination (YouTube, Facebook)
    plus one that writes HLS for the member app. All copies are `-c copy`:
    nothing is re-encoded, so a $6 droplet carries it;
  * tells the backend every BEAT_S that the stream is still up (the
    heartbeat). Each answer says whether the key is still good — a replaced
    key, or streaming switched off, cuts the stream at once — and where
    copies go now, so a removed or changed YouTube/Facebook key stops or
    moves its copy within a minute;
  * uploads the HLS segments and playlist to the PRIVATE R2 bucket as they
    are written; members watch through the backend's signed links;
  * waits GRACE_S after a stream drops before calling it over: a church
    whose internet blinks reconnects into the SAME recording;
  * then finishes the recording — closes the playlist, uploads it, tells
    the backend — and keeps trying until the backend says it is saved.

Every recording ("run") has its own folder, streams/<stream id>/<run id>/,
and a journal (run.json) there. A restarted agent reads the journals: a
recording waiting out its grace is picked up (and finished if the church
never comes back), and a finish in progress carries on. A folder belongs
to exactly one run, so a finish never touches the next stream's files.

Limits, so one church can't fill the disk or the box for everyone: at most
MAX_STREAMS churches at once, counting those waiting out their grace and
those just let in (a church holds its place from the moment /auth lets it
in, and admissions are decided one at a time, so two at once can't both
take the last place; a publisher found past the limit is disconnected);
no new stream when free disk is under DISK_RESERVE_GB or can't be read;
a recording stops (the copies to YouTube/Facebook keep going) past
MAX_RECORD_S, when its not-yet-uploaded backlog passes SPOOL_MAX_GB, or
while the disk is nearly full or can't be read; a publisher sending more
than MAX_INGEST_MBPS for half a minute is disconnected. The limits and the
key deadline are checked every pass, even while MediaMTX's API is down.

Pure helpers sit at the top and import nothing outside the standard library,
so __tests__/test_stream_relay_agent.py can test them without aiohttp/boto3.
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple
from urllib.parse import parse_qs

log = logging.getLogger("relay")

STREAM_ID_RE = re.compile(r"^[0-9a-f]{20}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
RUN_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
LOCAL_IPS = {"127.0.0.1", "::1"}
SEGMENT_SECONDS = 4
PLAYLIST = "index.m3u8"
JOURNAL = "run.json"
REFUSED = (400, 401, 403, 404, 422)
CONN_KINDS = ("rtmpsconns", "rtmpconns")
ADMIT_HOLD_S = 30      # a church let in holds its place this long for MediaMTX to list it
KICK_EVERY_S = 10      # a publisher that must go is disconnected again this often
KILL_AFTER_S = 5       # a stopped ffmpeg gets this long to exit before it is killed
CONFIRM_CHUNK = 200    # keys per /relay/confirm request


# ─── pure helpers ────────────────────────────────────────────────────


def stream_id_from_path(path: Any) -> Optional[str]:
    """'live/<stream id>' → the stream id, or None for any other path."""
    m = re.match(r"^live/([0-9a-f]{20})$", str(path or ""))
    return m.group(1) if m else None


def key_from_query(query: Any) -> Optional[str]:
    """The secret from the stream key's query (`key=<secret>`), or None."""
    vals = parse_qs(str(query or ""), keep_blank_values=False).get("key") or []
    return vals[0] if len(vals) == 1 and SECRET_RE.match(vals[0]) else None


def auth_decision(req: Dict[str, Any]) -> Tuple[str, Optional[Tuple[str, str]]]:
    """What to do with one MediaMTX auth request.

    ('check', (stream id, key))  publish: ask the backend about this key
    ('allow', None)              a read from this machine (our own ffmpeg copies)
    ('deny', None)               everything else: nobody watches from the relay itself
    """
    action = str(req.get("action") or "")
    ip = str(req.get("ip") or "")
    if action == "publish":
        sid = stream_id_from_path(req.get("path"))
        key = key_from_query(req.get("query"))
        return ("check", (sid, key)) if sid and key else ("deny", None)
    if action in ("read", "playback") and ip in LOCAL_IPS:
        return ("allow", None)
    return ("deny", None)


def hls_cmd(src: str, out_dir: str, resume: bool) -> List[str]:
    """Write the stream as HLS, unchanged. The playlist is an EVENT list
    that keeps every segment, so it is the live feed AND the recording.
    omit_endlist: a dropped stream must not tell players "it's over" —
    the agent writes the end itself when the grace runs out. A resumed
    stream appends to the same list, marked as a discontinuity."""
    flags = "append_list+omit_endlist+temp_file+program_date_time"
    if resume:
        flags += "+discont_start"
    return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
            "-rtsp_transport", "tcp", "-i", src,
            "-map", "0", "-c", "copy", "-f", "hls",
            "-hls_time", str(SEGMENT_SECONDS), "-hls_list_size", "0",
            "-hls_playlist_type", "event", "-hls_flags", flags,
            "-hls_segment_filename", os.path.join(out_dir, "seg_%06d.ts"),
            os.path.join(out_dir, PLAYLIST)]


def forward_cmd(src: str, url: str) -> List[str]:
    """Pass the stream on to YouTube / Facebook, unchanged."""
    return ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
            "-rtsp_transport", "tcp", "-i", src,
            "-map", "0", "-c", "copy", "-f", "flv", url]


def playlist_seconds(text: str) -> float:
    total = 0.0
    for line in (text or "").splitlines():
        if line.startswith("#EXTINF:"):
            try:
                total += float(line[len("#EXTINF:"):].split(",")[0])
            except ValueError:
                pass
    return total


def finalize_playlist(text: str) -> str:
    """The recording's last word: players treat it as a finished video."""
    body = (text or "").rstrip("\n")
    if "#EXT-X-ENDLIST" in body:
        return body + "\n"
    return body + "\n#EXT-X-ENDLIST\n"


def object_headers(name: str) -> Tuple[str, str]:
    """(Content-Type, Cache-Control) for an upload. The bucket is private:
    viewers fetch through signed links, so nothing is cached as public.
    Segments never change; the playlist changes every few seconds."""
    if name.endswith(".ts"):
        return "video/mp2t", "private, max-age=31536000, immutable"
    if name.endswith(".m3u8"):
        return "application/vnd.apple.mpegurl", "private, no-cache"
    return "application/octet-stream", "private, no-cache"


def backoff(attempt: int, cap: float = 30) -> float:
    return float(min(cap, 2 ** max(0, attempt)))


def redact(text: str) -> str:
    """No stream key in a log line: ours (`key=<secret>`) or a platform's."""
    text = re.sub(r"(key=)[^&\s'\"]+", r"\g<1><key>", text or "")
    return re.sub(r"(rtmps?://[^\s/]+(?::\d+)?/[^\s/]+/)[^\s]+", r"\g<1><key>", text)


def key_hash(key: str) -> str:
    """sha256 of a church's secret, exactly as the backend stores it: what
    the agent remembers and re-confirms, never the secret itself."""
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


def ingest_mbps(samples: Deque[Tuple[float, int]]) -> float:
    """Megabits per second over the samples (time, bytes received so far)."""
    if len(samples) < 2:
        return 0.0
    (t0, b0), (t1, b1) = samples[0], samples[-1]
    return (b1 - b0) * 8 / 1e6 / (t1 - t0) if t1 > t0 and b1 >= b0 else 0.0


# ─── config ──────────────────────────────────────────────────────────


class Config:
    def __init__(self) -> None:
        e = os.environ.get
        self.backend = (e("BACKEND_URL") or "").rstrip("/")
        self.secret = e("STREAM_RELAY_SECRET") or ""
        self.mtx_api = (e("MTX_API") or "http://127.0.0.1:9997").rstrip("/")
        self.mtx_rtsp = (e("MTX_RTSP") or "rtsp://127.0.0.1:8554").rstrip("/")
        self.r2_endpoint = e("R2_ENDPOINT") or ""
        self.r2_key = e("R2_ACCESS_KEY_ID") or ""
        self.r2_secret = e("R2_SECRET_ACCESS_KEY") or ""
        self.r2_bucket = e("R2_BUCKET") or ""
        self.work = Path(e("WORK_DIR") or "/var/relay")
        self.grace = float(e("GRACE_S") or 600)
        self.listen = e("AGENT_ADDR") or "127.0.0.1:9100"
        self.beat_s = float(e("BEAT_S") or 60)
        # How long the backend may be silent about a key before streams on
        # it are refused (new) or cut (running), and how often every key the
        # agent remembers is re-confirmed (Kevin, 2026-10-29: a day, hourly).
        self.offline_s = float(e("OFFLINE_GRANT_S") or 24 * 3600)
        self.grant_sync_s = float(e("GRANT_SYNC_S") or 3600)
        self.max_streams = int(e("MAX_STREAMS") or 4)
        self.reserve = int(float(e("DISK_RESERVE_GB") or 2) * 1e9)
        self.spool_max = int(float(e("SPOOL_MAX_GB") or 6) * 1e9)
        self.max_record_s = float(e("MAX_RECORD_S") or 6 * 3600)
        self.max_mbps = float(e("MAX_INGEST_MBPS") or 25)

    def missing(self) -> List[str]:
        need = {"BACKEND_URL": self.backend, "STREAM_RELAY_SECRET": self.secret,
                "R2_ENDPOINT": self.r2_endpoint, "R2_ACCESS_KEY_ID": self.r2_key,
                "R2_SECRET_ACCESS_KEY": self.r2_secret, "R2_BUCKET": self.r2_bucket}
        return [k for k, v in need.items() if not v]


# ─── one recording, one church's stream, one copy ────────────────────


class Run:
    """One recording, which is one session on the backend. Its folder is
    its own and never reused; run.json says where it stands."""

    def __init__(self, work: Path, stream_id: str, run_id: Optional[str] = None) -> None:
        self.stream_id = stream_id
        self.run_id = run_id or str(uuid.uuid4())
        self.dir = work / "streams" / stream_id / self.run_id
        self.state = "recording"                        # recording | finishing
        self.session_id: Optional[str] = None
        self.playlist_path: Optional[str] = None
        # Only until the backend has given this run a session (it may be
        # down on a Sunday): the finish needs it to ask for one.
        self.key: Optional[str] = None
        self.created = time.time()
        self.bytes = 0
        self.stopped = ""                               # why recording stopped early, if it did
        self.uploaded: Dict[str, int] = {}              # name -> size
        self.playlist_sig = ""

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        data = {"run_id": self.run_id, "stream_id": self.stream_id, "state": self.state,
                "session_id": self.session_id, "playlist_path": self.playlist_path,
                "key": None if self.session_id else self.key,
                "created": self.created, "bytes": self.bytes, "stopped": self.stopped}
        tmp = self.dir / (JOURNAL + ".tmp")
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.dir / JOURNAL)

    @classmethod
    def load(cls, work: Path, path: Path) -> Optional["Run"]:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        sid, rid = str(data.get("stream_id") or ""), str(data.get("run_id") or "")
        if not STREAM_ID_RE.match(sid) or not RUN_ID_RE.match(rid) or path.parent.name != rid:
            return None
        run = cls(work, sid, rid)
        run.state = "finishing" if data.get("state") == "finishing" else "recording"
        run.session_id = data.get("session_id") or None
        run.playlist_path = data.get("playlist_path") or None
        run.key = data.get("key") or None
        run.created = float(data.get("created") or time.time())
        run.bytes = int(data.get("bytes") or 0)
        run.stopped = str(data.get("stopped") or "")
        return run

    def last_write(self) -> float:
        """When this recording was last written to (ffmpeg's playlist, or
        the journal), 0 if neither can be read."""
        t = 0.0
        for name in (PLAYLIST, JOURNAL):
            try:
                t = max(t, (self.dir / name).stat().st_mtime)
            except OSError:
                pass
        return t

    def seconds(self) -> float:
        pl = self.dir / PLAYLIST
        try:
            return playlist_seconds(pl.read_text()) if pl.exists() else 0.0
        except OSError:
            return 0.0

    def backlog(self) -> int:
        """Bytes written here and not yet uploaded."""
        total = 0
        for f in self.dir.glob("seg_*.ts"):
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if self.uploaded.get(f.name) != size:
                total += size
        return total


class Copy:
    """One ffmpeg we keep running (the HLS writer, or a copy to a platform)
    until it is stopped."""

    def __init__(self, name: str, url: str = "") -> None:
        self.name = name
        self.url = url
        self.stopped = False
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.task: Optional[asyncio.Task] = None
        self.tail: Deque[str] = collections.deque(maxlen=5)

    def stop(self) -> None:
        """Ask ffmpeg to stop, and kill it if it hasn't within KILL_AFTER_S:
        a copy that is stopped really ends."""
        self.stopped = True
        proc = self.proc
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        try:
            asyncio.get_running_loop().call_later(KILL_AFTER_S, Copy._kill, proc)
        except RuntimeError:      # no loop: nothing is running to kill
            pass

    @staticmethod
    def _kill(proc: Any) -> None:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass


class Live:
    """One church's stream while it is up, or waiting out its grace."""

    def __init__(self, stream_id: str, run: Run) -> None:
        self.stream_id = stream_id
        self.run = run
        self.key: Optional[str] = None                  # from MediaMTX's API; memory only
        self.conn: Optional[Tuple[str, str]] = None     # (kind, id): who to disconnect
        self.up = False
        self.down_since: Optional[float] = time.time()
        self.revoked = False
        self.bad_key: Optional[str] = None              # the key cut off (memory only)
        self.revoked_at = 0.0
        # Until when the backend's last word on this stream's key holds:
        # its last confirmation + OFFLINE_GRANT_S. Past it, the stream is cut.
        self.auth_until = 0.0
        self.next_kick = 0.0
        self.kick_pending = False                       # cut off, and not yet known to be gone
        self.last_beat = 0.0
        self.beating = False
        self.dests: List[Dict[str, str]] = []
        self.hls: Optional[Copy] = None
        self.fwd: Dict[str, Copy] = {}
        self.rate: Deque[Tuple[float, int]] = collections.deque(maxlen=31)
        self.uploader: Optional[asyncio.Task] = None


# ─── the agent ───────────────────────────────────────────────────────


class Agent:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.lives: Dict[str, Live] = {}
        self.finishing: Dict[str, asyncio.Task] = {}    # run id -> its finish
        self.cache_dir = cfg.work / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (cfg.work / "streams").mkdir(parents=True, exist_ok=True)
        self.http = None
        self.s3 = None
        self.recovered = False
        self.born = time.time()
        self.next_limits = 0.0
        # A church /auth let in, until MediaMTX lists it: stream id -> (held
        # until, which admission). Counted against MAX_STREAMS.
        self.held: Dict[str, Tuple[float, str]] = {}
        self.admitting = asyncio.Lock()                 # one admission decided at a time
        self.turned_away: Dict[str, float] = {}         # past the limit: stream id -> next kick
        self.next_sync = 0.0                            # the first re-check runs at start
        self.syncing = False

    # ── the backend ──

    async def backend(self, path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            async with self.http.post(f"{self.cfg.backend}{path}", json=body, timeout=10,
                                      headers={"X-Relay-Secret": self.cfg.secret}) as r:
                data = await r.json(content_type=None) if r.status < 500 else {}
                return r.status, data if isinstance(data, dict) else {}
        except Exception as e:  # network down, Railway down: callers decide
            log.warning("backend %s failed: %s", path, type(e).__name__)
            return 0, {}

    # Keys the backend confirmed, for when it can't be reached: ONE per
    # church (the re-check answers by church), cache/<stream id>.json, with
    # sha256 of the secret (never the secret), when the backend was asked,
    # and where copies go.

    def _cache_path(self, stream_id: str) -> Path:
        if not STREAM_ID_RE.match(stream_id or ""):
            raise ValueError("not a stream id")
        return self.cache_dir / f"{stream_id}.json"

    def _grant(self, stream_id: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(self._cache_path(stream_id).read_text())
        except (OSError, ValueError):
            return None
        ok = isinstance(data, dict) and data.get("stream_id") == stream_id and isinstance(data.get("key_hash"), str)
        return data if ok else None

    def _keep(self, data: Dict[str, Any]) -> None:
        p = self._cache_path(str(data["stream_id"]))
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)

    def _drop(self, stream_id: str) -> None:
        try:
            self._cache_path(stream_id).unlink()
        except (OSError, ValueError):
            pass

    def _fresh(self, data: Dict[str, Any], now: Optional[float] = None) -> bool:
        return (time.time() if now is None else now) - float(data.get("seen") or 0) < self.cfg.offline_s

    def remember(self, key: str, stream_id: str, dests: List[Dict[str, str]],
                 seen: Optional[float] = None) -> None:
        """The church's remembered key: a newly confirmed key replaces the
        old one. `seen`: when the backend was ASKED (an answer is never newer
        than its question), so an answer that crossed a cut-off can't
        outlive it."""
        self._keep({"stream_id": stream_id, "key_hash": key_hash(key),
                    "seen": time.time() if seen is None else seen, "dests": dests})

    def recall(self, key: str, stream_id: str) -> Optional[Dict[str, Any]]:
        data = self._grant(stream_id)
        if not data or not hmac.compare_digest(data["key_hash"], key_hash(key)):
            return None
        return data if self._fresh(data) else None

    def grant_until(self, key: Optional[str], stream_id: str) -> float:
        """Until when the backend's last confirmation of this key holds; 0
        (already over) for a key it never confirmed or not within the window."""
        data = self.recall(key, stream_id) if key else None
        return float(data.get("seen") or 0) + self.cfg.offline_s if data else 0.0

    def forget(self, key: Optional[str], stream_id: str) -> None:
        """Forget the church's remembered key if it is THIS key: refusing an
        old key never takes the church's new one with it."""
        data = self._grant(stream_id)
        if key and data and hmac.compare_digest(data["key_hash"], key_hash(key)):
            self._drop(stream_id)

    def remembered(self) -> List[Dict[str, Any]]:
        """Every remembered key still within its window. One that ran out
        isn't re-checked: it comes back only through /auth."""
        out = []
        for p in sorted(self.cache_dir.glob("*.json")):
            data = self._grant(p.stem)
            if data and self._fresh(data):
                out.append(data)
        return out

    async def sync_grants(self) -> None:
        """The hourly re-check: ask the backend about every remembered key,
        CONFIRM_CHUNK at a time. A confirmed key's window starts again from
        when it was asked; a key left out is forgotten and a stream on it is
        cut. Any other answer (a timeout, a 5xx, a 401, a 404 from a backend
        without the route yet, no `confirmed` list, or a list with anything
        in it but stream ids) changes nothing at all."""
        try:
            held = [(str(g["stream_id"]), str(g["key_hash"])) for g in self.remembered()]
            for i in range(0, len(held), CONFIRM_CHUNK):
                chunk = held[i:i + CONFIRM_CHUNK]
                asked = time.time()
                status, data = await self.backend("/stream-relay/relay/confirm", {
                    "grants": [{"stream_id": sid, "key_hash": h} for sid, h in chunk]})
                confirmed = data.get("confirmed") if status == 200 else None
                if not (isinstance(confirmed, list)
                        and all(isinstance(s, str) and STREAM_ID_RE.fullmatch(s) for s in confirmed)):
                    log.warning("re-check of %d keys got no usable answer (%s); nothing changed", len(chunk), status)
                    continue
                await self.apply_confirm(chunk, set(confirmed), asked)
        finally:
            self.syncing = False

    async def apply_confirm(self, chunk: List[Tuple[str, str]], ok: set, asked: float) -> None:
        now = time.time()
        for sid, h in chunk:
            grant = self._grant(sid)
            mine = grant is not None and hmac.compare_digest(grant["key_hash"], h)
            live = self.lives.get(sid)
            on_it = (live is not None and live.key is not None and not live.revoked
                     and hmac.compare_digest(key_hash(live.key), h))
            if sid in ok:
                # Only a key still within its window is renewed: an answer
                # that comes in after it ran out brings nothing back.
                if mine and self._fresh(grant, now):
                    grant["seen"] = max(float(grant.get("seen") or 0), asked)
                    self._keep(grant)
                if on_it and now < live.auth_until:
                    live.auth_until = max(live.auth_until, asked + self.cfg.offline_s)
                continue
            # Left out: forgotten, unless confirmed again since it was asked.
            if mine and float(grant.get("seen") or 0) <= asked:
                self._drop(sid)
            if on_it and live.auth_until <= asked + self.cfg.offline_s:
                log.warning("%s: the backend no longer confirms this stream's key; disconnecting", sid)
                self.revoke(live, now)
                await self.disconnect(live, now)

    async def may_publish(self, stream_id: str, key: str) -> bool:
        asked = time.time()
        status, data = await self.backend("/stream-relay/relay/verify", {"stream_id": stream_id, "key": key})
        if status == 200:
            self.remember(key, stream_id, list(data.get("destinations") or []), seen=asked)
            return True
        if status in REFUSED:
            self.forget(key, stream_id)
            return False
        # The backend can't answer (0 / 5xx): a key it confirmed within the
        # offline window keeps working, so a service doesn't depend on Railway.
        return self.recall(key, stream_id) is not None

    def free_disk(self) -> int:
        return shutil.disk_usage(self.cfg.work).free

    def disk_room(self) -> Optional[int]:
        """Free bytes on the spool's disk, or None when that can't be read
        (every limit then treats the disk as full)."""
        try:
            return int(self.free_disk())
        except Exception as e:
            log.error("the disk can't be read: %s", type(e).__name__)
            return None

    def places_taken(self, now: float, but: str = "") -> int:
        """Churches counted against MAX_STREAMS: every one here (streaming,
        or waiting out its grace to come back) and every one /auth let in
        that MediaMTX doesn't list yet. A hold nobody connected on lapses."""
        for sid, (until, _) in list(self.held.items()):
            if until <= now or sid in self.lives:
                self.held.pop(sid, None)
        return len([s for s in set(self.lives) | set(self.held) if s != but])

    def refusal(self, stream_id: str) -> str:
        """Why a NEW stream can't start now ('' when it can). A church
        already here (reconnecting within its grace), or let in a moment
        ago, is always let back."""
        now = time.time()
        if stream_id in self.lives or self.held.get(stream_id, (0.0, ""))[0] > now:
            return ""
        if self.places_taken(now) >= self.cfg.max_streams:
            return f"already carrying {self.cfg.max_streams} streams"
        free = self.disk_room()
        if free is None:
            return "the disk can't be read"
        if free < self.cfg.reserve:
            return "the disk is nearly full"
        return ""

    async def admit(self, stream_id: str, key: str) -> bool:
        """One publish asking to come in. The place is taken BEFORE the
        backend is asked, and the check and the taking are one step under a
        lock, so two churches at once can't both get the last place. A
        church the backend (or the cache) turns down gives it back."""
        async with self.admitting:
            why = self.refusal(stream_id)
            if why:
                log.warning("%s: not taking a new stream: %s", stream_id, why)
                return False
            hold: Optional[Tuple[float, str]] = None
            if stream_id not in self.lives:
                hold = (time.time() + ADMIT_HOLD_S, uuid.uuid4().hex)
                self.held[stream_id] = hold
        ok = False
        try:
            ok = await self.may_publish(stream_id, key)
            return ok
        finally:
            if not ok and hold is not None and self.held.get(stream_id) == hold:
                self.held.pop(stream_id, None)

    def take_place(self, stream_id: str, now: float) -> bool:
        """MediaMTX lists a publisher the agent isn't carrying yet: carry it
        if /auth let it in (its held place) or there is still room."""
        if self.held.pop(stream_id, None) is not None:
            return True
        return self.places_taken(now, but=stream_id) < self.cfg.max_streams

    # ── MediaMTX ──

    async def publishers(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """{stream id: {key, conn, bytes}} for every publisher MediaMTX has
        now, or None when its API can't be read (then nothing changes)."""
        out: Dict[str, Dict[str, Any]] = {}
        for kind in CONN_KINDS:
            try:
                async with self.http.get(f"{self.cfg.mtx_api}/v3/{kind}/list", timeout=5) as r:
                    if r.status == 404:      # that listener is switched off
                        continue
                    if r.status != 200:
                        return None
                    data = await r.json(content_type=None)
            except Exception as e:
                log.warning("mediamtx api: %s", type(e).__name__)
                return None
            for item in data.get("items") or []:
                sid = stream_id_from_path(item.get("path"))
                if sid and item.get("state") == "publish":
                    out[sid] = {"key": key_from_query(item.get("query")), "conn": (kind, str(item.get("id"))),
                                "bytes": int(item.get("bytesReceived") or 0)}
        return out

    async def kick(self, stream_id: str, conn: Optional[Tuple[str, str]]) -> bool:
        """Disconnect one publisher through MediaMTX's API. True when it is
        known gone: MediaMTX closed it (200) or no longer has it (404)."""
        if not conn:
            return False
        kind, cid = conn
        try:
            async with self.http.post(f"{self.cfg.mtx_api}/v3/{kind}/kick/{cid}", timeout=5) as r:
                log.warning("%s disconnected (%s)", stream_id, r.status)
                return r.status in (200, 404)
        except Exception as e:
            log.warning("%s kick failed: %s", stream_id, type(e).__name__)
            return False

    # ── startup: pick up where the last agent left off ──

    def recover(self) -> None:
        runs = [r for r in (Run.load(self.cfg.work, p) for p in (self.cfg.work / "streams").glob(f"*/*/{JOURNAL}")) if r]
        runs.sort(key=lambda r: r.created)
        now = time.time()
        for run in runs:
            if run.state == "recording" and now - run.last_write() > self.cfg.grace:
                # Nothing written for longer than the grace (the agent was
                # down that long): that service is over. Finish it; the
                # church's next stream starts a recording of its own.
                log.info("%s: recording %s untouched past the grace; finishing it", run.stream_id, run.run_id)
                self.end_run(run)
                continue
            if run.state == "recording" and run.stream_id in self.lives:
                old = self.lives.pop(run.stream_id).run     # two open runs: only the newest goes on
                self.end_run(old)
            if run.state == "finishing":
                self.end_run(run)
                continue
            live = Live(run.stream_id, run)                 # down since now: the grace starts again
            self.lives[run.stream_id] = live
            live.uploader = asyncio.create_task(self.uploader(run))
            log.info("%s: picked up recording %s", run.stream_id, run.run_id)
        self.recovered = True

    # ── the loop ──

    async def tick(self) -> None:
        """One pass, every second. Only finding publishers needs MediaMTX's
        API; the heartbeat, the key deadline and the limits run every pass
        whether or not it answers (a guard that waits on it is no guard)."""
        try:
            pubs = await self.publishers()
            if pubs is not None:
                await self.discover(pubs, time.time())
        except Exception:
            log.exception("finding publishers failed")
        now = time.time()
        for live in list(self.lives.values()):
            if live.key and not live.beating and now - live.last_beat >= self.cfg.beat_s:
                live.last_beat, live.beating = now, True
                asyncio.create_task(self.beat(live))
        if now >= self.next_sync and not self.syncing:
            self.next_sync, self.syncing = now + self.cfg.grant_sync_s, True
            asyncio.create_task(self.sync_grants())
        await self.enforce_grants(now)
        if now >= self.next_limits:
            self.next_limits = now + 10
            await self.enforce_limits(now)

    async def discover(self, pubs: Dict[str, Dict[str, Any]], now: float) -> None:
        """Bring the agent in line with the publishers MediaMTX lists."""
        for sid in list(self.turned_away):
            if sid not in pubs:
                self.turned_away.pop(sid, None)
        for sid, p in pubs.items():
            live = self.lives.get(sid)
            if live is None:
                if not self.take_place(sid, now):
                    # Past the limit (let in by an agent since restarted,
                    # say): never carried, disconnected until it goes.
                    if now >= self.turned_away.get(sid, 0.0):
                        self.turned_away[sid] = now + KICK_EVERY_S
                        log.warning("%s: already carrying %s streams; disconnecting", sid, self.cfg.max_streams)
                        await self.kick(sid, p["conn"])
                    continue
                live = self.begin(sid)
            if live.conn != p["conn"]:
                live.rate.clear()
            live.conn = p["conn"]
            live.rate.append((now, p["bytes"]))
            if live.revoked:
                if p["key"] and (p["key"] != live.bad_key or self.confirmed_since(p["key"], sid, live.revoked_at)):
                    # Back on a new key, or the backend has confirmed this
                    # one since it was cut (a deadline that ran out).
                    live.revoked, live.bad_key, live.up, live.kick_pending = False, None, False, False
                else:
                    # Still there on the cut-off key: enforce_grants goes on
                    # disconnecting it, on the connection saved above.
                    live.kick_pending = True
                    continue
            if p["key"] and p["key"] != live.key:
                live.key = p["key"]
                live.auth_until = self.grant_until(live.key, sid)
            if not live.up:
                if live.down_since is not None and live.run.created < now - 1:
                    log.info("%s back after %.0fs: same recording", sid, now - live.down_since)
                live.up, live.down_since = True, None
                live.auth_until = self.grant_until(live.key, sid)
                if not live.dests and live.key:
                    live.dests = list((self.recall(live.key, sid) or {}).get("dests") or [])
                self.start_writers(live)
                live.last_beat = 0.0
        for sid, live in list(self.lives.items()):
            if live.up and sid not in pubs:
                log.info("%s dropped; waiting %ss before calling it over", sid, int(self.cfg.grace))
                live.up, live.down_since, live.kick_pending = False, now, False   # known gone
                self.stop_writers(live)
            elif not live.up and now - (live.down_since or now) >= self.cfg.grace:
                self.lives.pop(sid, None)
                self.stop_writers(live)
                self.end_run(live.run)

    def confirmed_since(self, key: str, stream_id: str, when: float) -> bool:
        """Has the backend confirmed this key (asked after `when`)?"""
        data = self.recall(key, stream_id)
        return bool(data) and float(data.get("seen") or 0) > when

    def revoke(self, live: Live, now: float) -> None:
        """Cut this stream off its key: every copy and the recording stop
        now, without waiting on MediaMTX; the caller disconnects it."""
        live.revoked, live.bad_key, live.key = True, live.key, None
        live.revoked_at, live.next_kick, live.kick_pending = now, now, True
        self.stop_writers(live)

    async def disconnect(self, live: Live, now: float) -> None:
        """Kick a cut-off publisher on the connection the agent saved. Until
        that takes, or the listing shows it gone, enforce_grants tries again
        every KICK_EVERY_S, whether or not MediaMTX can list publishers."""
        live.next_kick = now + KICK_EVERY_S
        if await self.kick(live.stream_id, live.conn):
            live.kick_pending = False

    async def enforce_grants(self, now: float) -> None:
        """A running stream whose key the backend hasn't confirmed within
        OFFLINE_GRANT_S is cut, on this clock alone: the backend may be
        down, MediaMTX's API may be too. A cut-off publisher is disconnected
        from here, again and again, until it is known gone."""
        for live in list(self.lives.values()):
            if live.up and not live.revoked and now >= live.auth_until:
                log.warning("%s: the backend hasn't confirmed this stream's key for %.0f min; disconnecting",
                            live.stream_id, self.cfg.offline_s / 60)
                self.revoke(live, now)
            if live.revoked and live.kick_pending and live.conn and now >= live.next_kick:
                await self.disconnect(live, now)

    def begin(self, stream_id: str) -> Live:
        run = Run(self.cfg.work, stream_id)
        run.save()
        live = Live(stream_id, run)
        self.lives[stream_id] = live
        live.uploader = asyncio.create_task(self.uploader(run))
        log.info("%s is live (recording %s)", stream_id, run.run_id)
        return live

    async def beat(self, live: Live) -> None:
        """Tell the backend we still carry this stream; act on its answer."""
        try:
            run, key = live.run, live.key
            if not key:
                return
            asked = time.time()
            status, data = await self.backend("/stream-relay/relay/started", {
                "stream_id": live.stream_id, "key": key, "run_id": run.run_id,
                "recorded_s": int(run.seconds()), "bytes": run.bytes})
            if live.run is not run:
                return
            if status == 200 and data.get("session_id"):
                if run.session_id != data["session_id"]:
                    run.session_id, run.playlist_path = data["session_id"], data.get("playlist_path")
                    run.save()
                dests = list(data.get("destinations") or [])
                # Only a grant still standing when the answer comes in is
                # renewed: one that ran out (or was cut) while the answer was
                # on its way stays out; only a fresh /auth makes a new one.
                if live.key == key and not live.revoked and time.time() < live.auth_until:
                    self.remember(key, live.stream_id, dests, seen=asked)
                    live.auth_until = max(live.auth_until, asked + self.cfg.offline_s)
                    self.reconcile(live, dests)
            elif status == 409:
                self.split(live, data.get("detail") if isinstance(data.get("detail"), dict) else {})
            elif status in REFUSED:
                log.warning("%s: the backend refused this stream's key (%s); disconnecting", live.stream_id, status)
                self.forget(key, live.stream_id)
                if live.key == key:
                    self.revoke(live, time.time())
                    await self.disconnect(live, time.time())
            elif run.session_id is None and run.key != key:
                run.key = key                           # the backend is down: the finish will need it
                run.save()
        finally:
            live.beating = False

    def reconcile(self, live: Live, dests: List[Dict[str, str]]) -> None:
        """Copies go exactly where the backend says now: a removed one stops,
        a changed one restarts on its new key, a new one starts."""
        want = {d["name"]: d["url"] for d in dests if d.get("name") and d.get("url")}
        live.dests = dests
        for name, c in list(live.fwd.items()):
            if want.get(name) != c.url:
                c.stop()
                live.fwd.pop(name, None)
                log.info("%s: copy to %s stopped (%s)", live.stream_id, name, "changed" if name in want else "removed")
        if live.up and not live.revoked:
            for name, url in want.items():
                if name not in live.fwd:
                    self.start_copy(live, name, url)

    def split(self, live: Live, detail: Dict[str, Any]) -> None:
        """The backend closed this run's session (we were silent too long):
        finish that recording and carry on in a new one."""
        old = live.run
        if not old.session_id and detail.get("session_id"):
            old.session_id, old.playlist_path = detail["session_id"], detail.get("playlist_path")
        if live.hls:
            live.hls.stop()
            live.hls = None
        self.end_run(old)
        live.run = Run(self.cfg.work, live.stream_id)
        live.run.save()
        live.uploader = asyncio.create_task(self.uploader(live.run))
        if live.up and not live.revoked:
            self.start_hls(live)
        live.last_beat = 0.0
        log.warning("%s: the backend had closed recording %s; continuing in %s",
                    live.stream_id, old.run_id, live.run.run_id)

    # ── the copies ──

    def src(self, live: Live) -> str:
        return f"{self.cfg.mtx_rtsp}/live/{live.stream_id}"

    def start_writers(self, live: Live) -> None:
        self.start_hls(live)
        for d in live.dests:
            if d.get("name") and d.get("url") and d["name"] not in live.fwd:
                self.start_copy(live, d["name"], d["url"])

    def start_hls(self, live: Live) -> None:
        run = live.run
        if run.stopped or (live.hls and not live.hls.stopped):
            return
        run.dir.mkdir(parents=True, exist_ok=True)
        c = Copy("hls")
        live.hls = c
        c.task = asyncio.create_task(self.supervise(live.stream_id, c, lambda: hls_cmd(
            self.src(live), str(run.dir), resume=(run.dir / PLAYLIST).exists())))

    def start_copy(self, live: Live, name: str, url: str) -> None:
        c = Copy(name, url)
        live.fwd[name] = c
        cmd = forward_cmd(self.src(live), url)
        c.task = asyncio.create_task(self.supervise(live.stream_id, c, lambda: cmd))

    def stop_writers(self, live: Live) -> None:
        if live.hls:
            live.hls.stop()
            live.hls = None
        for c in live.fwd.values():
            c.stop()
        live.fwd.clear()

    async def supervise(self, sid: str, c: Copy, make_cmd: Callable[[], List[str]]) -> None:
        """Run one copy until it is stopped; restart it with a growing pause
        if it falls over (a platform hiccup, a bad key). stderr is read as
        it comes and only its last lines are kept."""
        attempt = 0
        while not c.stopped:
            started = time.time()
            try:
                proc = await asyncio.create_subprocess_exec(
                    *make_cmd(), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE)
            except OSError as e:
                log.error("%s %s could not start: %s", sid, c.name, type(e).__name__)
                return
            c.proc = proc
            if c.stopped:
                c.stop()
            buf = b""
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                buf = (buf + chunk)[-2048:]
                lines = buf.split(b"\n")
                buf = lines.pop()
                for ln in lines:
                    if ln.strip():
                        c.tail.append(ln.decode("utf-8", "replace").strip()[:300])
            await proc.wait()
            if c.stopped:
                return
            last = c.tail[-1] if c.tail else ""
            log.warning("%s %s exited %s: %s", sid, c.name, proc.returncode, redact(last)[:200])
            attempt = 0 if time.time() - started > 60 else attempt + 1
            await asyncio.sleep(backoff(attempt))

    # ── limits ──

    async def enforce_limits(self, now: float) -> None:
        free = self.disk_room()                          # None: can't be read, so full
        for live in list(self.lives.values()):
            run = live.run
            if live.up and ingest_mbps(live.rate) > self.cfg.max_mbps and len(live.rate) >= 30:
                log.error("%s: sending %.0f Mbps (limit %.0f); disconnecting", live.stream_id,
                          ingest_mbps(live.rate), self.cfg.max_mbps)
                live.rate.clear()
                await self.kick(live.stream_id, live.conn)
            reason = ""
            if free is None or free < self.cfg.reserve // 2:
                reason = "disk"
            elif now - run.created > self.cfg.max_record_s:
                reason = "length"
            elif run.backlog() > self.cfg.spool_max:
                reason = "backlog"
            if reason and not run.stopped:
                run.stopped = reason
                if live.hls:                             # stop first: the journal may not save on a full disk
                    live.hls.stop()
                    live.hls = None
                log.error("%s: recording %s stopped (%s); copies to YouTube/Facebook continue",
                          live.stream_id, run.run_id, reason)
                try:
                    run.save()
                except OSError as e:
                    log.error("%s: journal not saved: %s", live.stream_id, type(e).__name__)
            elif (run.stopped == "disk" and free is not None and free > self.cfg.reserve
                  and now - run.created <= self.cfg.max_record_s):
                run.stopped = ""
                run.save()
                if live.up and not live.revoked:
                    self.start_hls(live)
                log.warning("%s: disk has room again; recording resumed", live.stream_id)

    # ── uploads ──

    async def uploader(self, run: Run) -> None:
        while run.state == "recording":
            try:
                await self.upload_new(run)
            except Exception as e:
                log.warning("%s upload: %s", run.stream_id, type(e).__name__)
            await asyncio.sleep(1)

    async def upload_new(self, run: Run, final: bool = False) -> None:
        if not run.playlist_path:
            return    # no session yet: segments wait on disk (the limits watch how many)
        prefix = run.playlist_path.rsplit("/", 1)[0]
        for f in sorted(run.dir.glob("seg_*.ts")):
            size = f.stat().st_size
            if run.uploaded.get(f.name) == size:
                if time.time() - f.stat().st_mtime > 120:
                    f.unlink(missing_ok=True)   # uploaded long ago: free the disk
                continue
            await self.put(f"{prefix}/{f.name}", f.read_bytes())
            run.uploaded[f.name] = size
            run.bytes += size
        pl = run.dir / PLAYLIST
        if pl.exists():
            text = pl.read_text()
            if final:
                text = finalize_playlist(text)
            sig = hashlib.sha256(text.encode()).hexdigest()
            if sig != run.playlist_sig:
                await self.put(f"{prefix}/{PLAYLIST}", text.encode())
                run.playlist_sig = sig
                run.save()

    async def put(self, name: str, body: bytes) -> None:
        ctype, cache = object_headers(name)
        await asyncio.get_running_loop().run_in_executor(None, lambda: self.s3.put_object(
            Bucket=self.cfg.r2_bucket, Key=name, Body=body, ContentType=ctype, CacheControl=cache))

    # ── the end of a recording ──

    def end_run(self, run: Run) -> None:
        if run.run_id in self.finishing:
            return
        run.state = "finishing"
        run.save()
        self.finishing[run.run_id] = asyncio.create_task(self.finish(run))

    async def finish(self, run: Run) -> None:
        """Close the recording and tell the backend, until it has it. Only
        this run's own folder is ever removed."""
        attempt = 0
        try:
            while True:
                if not run.session_id:
                    if not run.key:
                        self.keep(run, "no session and no key to ask for one")
                        return
                    # `ending`: the service is over; the backend opens no live
                    # service and sends members no "live now" after the fact.
                    status, data = await self.backend("/stream-relay/relay/started", {
                        "stream_id": run.stream_id, "key": run.key, "run_id": run.run_id,
                        "recorded_s": int(run.seconds()), "bytes": run.bytes, "ending": True})
                    detail = data.get("detail") if isinstance(data.get("detail"), dict) else {}
                    if status == 200 and data.get("session_id"):
                        run.session_id, run.playlist_path = data["session_id"], data.get("playlist_path")
                        run.save()
                    elif status == 409 and detail.get("session_id"):
                        run.session_id, run.playlist_path = detail["session_id"], detail.get("playlist_path")
                        run.save()
                    elif status in REFUSED:
                        self.keep(run, f"the backend refused its key ({status})")
                        return
                if run.session_id:
                    try:
                        await self.upload_new(run, final=True)
                    except Exception as e:
                        log.warning("%s final upload: %s", run.stream_id, type(e).__name__)
                    else:
                        status, data = await self.backend("/stream-relay/relay/ended", {
                            "session_id": run.session_id, "duration_s": int(run.seconds()), "bytes": run.bytes})
                        if status == 200:
                            log.info("%s ended: %.0f min, sermon draft %s", run.stream_id, run.seconds() / 60,
                                     "made" if data.get("sermon_id") else "not made")
                            shutil.rmtree(run.dir, ignore_errors=True)
                            try:
                                run.dir.parent.rmdir()    # the church's folder, if nothing else is in it
                            except OSError:
                                pass
                            return
                        if status in (400, 404):
                            self.keep(run, f"the backend doesn't know its session ({status})")
                            return
                attempt += 1
                await asyncio.sleep(backoff(attempt, cap=600))
        finally:
            self.finishing.pop(run.run_id, None)

    def keep(self, run: Run, why: str) -> None:
        """A recording that can never be reported is moved aside, kept."""
        dest = self.cfg.work / "unreported" / run.run_id
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            run.dir.rename(dest)
        except OSError:
            dest = run.dir
        log.error("%s: recording %s kept in %s: %s", run.stream_id, run.run_id, dest, why)

    # ── the doors MediaMTX and deploy.sh use ──

    async def handle_auth(self, request):
        from aiohttp import web
        try:
            req = await request.json()
        except Exception:
            return web.Response(status=400)
        verdict, cred = auth_decision(req)
        if verdict == "allow":
            return web.Response(status=200)
        if verdict == "check" and cred and await self.admit(*cred):
            return web.Response(status=200)
        return web.Response(status=401)

    async def handle_health(self, request):
        from aiohttp import web
        return web.json_response({"ok": True, "recovered": self.recovered,
                                  "live": sum(1 for lv in self.lives.values() if lv.up),
                                  "waiting": sum(1 for lv in self.lives.values() if not lv.up),
                                  "finishing": len(self.finishing),
                                  "uptime_s": int(time.time() - self.born)})

    async def run(self) -> None:
        import aiohttp
        import boto3
        from aiohttp import web
        missing = self.cfg.missing()
        if missing:
            raise SystemExit(f"relay agent: missing {', '.join(missing)}")
        self.http = aiohttp.ClientSession()
        self.s3 = boto3.client("s3", endpoint_url=self.cfg.r2_endpoint, region_name="auto",
                               aws_access_key_id=self.cfg.r2_key,
                               aws_secret_access_key=self.cfg.r2_secret)
        self.recover()
        app = web.Application()
        app.router.add_post("/auth", self.handle_auth)
        app.router.add_get("/health", self.handle_health)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        host, port = self.cfg.listen.rsplit(":", 1)
        await web.TCPSite(runner, host, int(port)).start()
        log.info("relay agent up on %s", self.cfg.listen)
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(Agent(Config()).run())


if __name__ == "__main__":
    main()
