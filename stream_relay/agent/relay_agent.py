"""relay_agent.py — the stream relay's brain, beside MediaMTX on the droplet.

A church's streaming software sends one stream to
rtmps://stream.<domain>:443/live with its stream key, `<stream id>?key=<secret>`.
MediaMTX receives it on the path live/<stream id> (not a secret: MediaMTX
logs paths) and hands the secret only to this agent, in the auth request's
query. The agent does everything else:

  * decides who may stream (MediaMTX asks POST /auth; the backend knows the
    keys). A key the backend confirmed in the last OFFLINE_GRANT_S keeps
    working while the backend can't be reached, so a Sunday doesn't depend
    on Railway — but never past that window, and never once the backend
    has said no;
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
MAX_STREAMS at once; no new stream when free disk is under DISK_RESERVE_GB;
a recording stops (the copies to YouTube/Facebook keep going) past
MAX_RECORD_S, when its not-yet-uploaded backlog passes SPOOL_MAX_GB, or
while the disk is nearly full; a publisher sending more than
MAX_INGEST_MBPS for half a minute is disconnected.

Pure helpers sit at the top and import nothing outside the standard library,
so __tests__/test_stream_relay_agent.py can test them without aiohttp/boto3.
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
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


def key_id(key: str) -> str:
    """A short, non-reversible name for a key (the cache's file names)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


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
        self.offline_s = float(e("OFFLINE_GRANT_S") or 8 * 86400)
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
        self.stopped = True
        if self.proc is not None and self.proc.returncode is None:
            try:
                self.proc.terminate()
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
        self.bad_key: Optional[str] = None              # the key the backend refused (memory only)
        self.next_kick = 0.0
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

    # Keys the backend confirmed, for when it can't be reached. Named by a
    # hash of the key; holds the stream id and where copies go.

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key_id(key)}.json"

    def remember(self, key: str, stream_id: str, dests: List[Dict[str, str]]) -> None:
        p = self._cache_path(key)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"seen": time.time(), "stream_id": stream_id, "dests": dests}))
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)

    def recall(self, key: str, stream_id: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(self._cache_path(key).read_text())
        except (OSError, ValueError):
            return None
        fresh = time.time() - float(data.get("seen") or 0) < self.cfg.offline_s
        return data if fresh and data.get("stream_id") == stream_id else None

    def forget(self, key: Optional[str]) -> None:
        if not key:
            return
        try:
            self._cache_path(key).unlink()
        except OSError:
            pass

    async def may_publish(self, stream_id: str, key: str) -> bool:
        status, data = await self.backend("/stream-relay/relay/verify", {"stream_id": stream_id, "key": key})
        if status == 200:
            self.remember(key, stream_id, list(data.get("destinations") or []))
            return True
        if status in REFUSED:
            self.forget(key)
            return False
        # The backend can't answer (0 / 5xx): a key it confirmed within the
        # offline window keeps working, so Sunday doesn't depend on Railway.
        return self.recall(key, stream_id) is not None

    def free_disk(self) -> int:
        return shutil.disk_usage(self.cfg.work).free

    def refusal(self, stream_id: str) -> str:
        """Why a NEW stream can't start now ('' when it can). A church
        already here (reconnecting within its grace) is always let back."""
        if stream_id in self.lives:
            return ""
        if sum(1 for lv in self.lives.values() if lv.up) >= self.cfg.max_streams:
            return f"already carrying {self.cfg.max_streams} streams"
        if self.free_disk() < self.cfg.reserve:
            return "the disk is nearly full"
        return ""

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

    async def kick(self, live: Live) -> None:
        if not live.conn:
            return
        kind, cid = live.conn
        try:
            async with self.http.post(f"{self.cfg.mtx_api}/v3/{kind}/kick/{cid}", timeout=5) as r:
                log.warning("%s disconnected (%s)", live.stream_id, r.status)
        except Exception as e:
            log.warning("%s kick failed: %s", live.stream_id, type(e).__name__)

    # ── startup: pick up where the last agent left off ──

    def recover(self) -> None:
        runs = [r for r in (Run.load(self.cfg.work, p) for p in (self.cfg.work / "streams").glob(f"*/*/{JOURNAL}")) if r]
        runs.sort(key=lambda r: r.created)
        for run in runs:
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
        pubs = await self.publishers()
        if pubs is None:
            return
        now = time.time()
        for sid, p in pubs.items():
            live = self.lives.get(sid) or self.begin(sid)
            if live.conn != p["conn"]:
                live.rate.clear()
            live.conn = p["conn"]
            live.rate.append((now, p["bytes"]))
            if live.revoked:
                if p["key"] and p["key"] != live.bad_key:
                    live.revoked, live.bad_key, live.up = False, None, False   # back on a new key
                else:
                    if now >= live.next_kick:                  # still there on the refused key
                        live.next_kick = now + 10
                        await self.kick(live)
                    continue
            if p["key"]:
                live.key = p["key"]
            if not live.up:
                if live.down_since is not None and live.run.created < now - 1:
                    log.info("%s back after %.0fs: same recording", sid, now - live.down_since)
                live.up, live.down_since = True, None
                if not live.dests and live.key:
                    live.dests = list((self.recall(live.key, sid) or {}).get("dests") or [])
                self.start_writers(live)
                live.last_beat = 0.0
        for sid, live in list(self.lives.items()):
            if live.up and sid not in pubs:
                log.info("%s dropped; waiting %ss before calling it over", sid, int(self.cfg.grace))
                live.up, live.down_since = False, now
                self.stop_writers(live)
            elif not live.up and now - (live.down_since or now) >= self.cfg.grace:
                self.lives.pop(sid, None)
                self.stop_writers(live)
                self.end_run(live.run)
        for live in list(self.lives.values()):
            if live.key and not live.beating and now - live.last_beat >= self.cfg.beat_s:
                live.last_beat, live.beating = now, True
                asyncio.create_task(self.beat(live))
        if now >= self.next_limits:
            self.next_limits = now + 10
            await self.enforce_limits(now)

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
                self.remember(key, live.stream_id, dests)
                self.reconcile(live, dests)
            elif status == 409:
                self.split(live, data.get("detail") if isinstance(data.get("detail"), dict) else {})
            elif status in REFUSED:
                log.warning("%s: the backend refused this stream's key (%s); disconnecting", live.stream_id, status)
                self.forget(key)
                live.revoked, live.bad_key, live.key = True, key, None
                live.next_kick = time.time() + 10
                self.stop_writers(live)
                await self.kick(live)
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
        free = self.free_disk()
        for live in list(self.lives.values()):
            run = live.run
            if live.up and ingest_mbps(live.rate) > self.cfg.max_mbps and len(live.rate) >= 30:
                log.error("%s: sending %.0f Mbps (limit %.0f); disconnecting", live.stream_id,
                          ingest_mbps(live.rate), self.cfg.max_mbps)
                live.rate.clear()
                await self.kick(live)
            reason = ""
            if free < self.cfg.reserve // 2:
                reason = "disk"
            elif now - run.created > self.cfg.max_record_s:
                reason = "length"
            elif run.backlog() > self.cfg.spool_max:
                reason = "backlog"
            if reason and not run.stopped:
                run.stopped = reason
                run.save()
                if live.hls:
                    live.hls.stop()
                    live.hls = None
                log.error("%s: recording %s stopped (%s); copies to YouTube/Facebook continue",
                          live.stream_id, run.run_id, reason)
            elif run.stopped == "disk" and free > self.cfg.reserve and now - run.created <= self.cfg.max_record_s:
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
                    status, data = await self.backend("/stream-relay/relay/started", {
                        "stream_id": run.stream_id, "key": run.key, "run_id": run.run_id,
                        "recorded_s": int(run.seconds()), "bytes": run.bytes})
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
        if verdict == "check" and cred:
            sid, key = cred
            why = self.refusal(sid)
            if why:
                log.warning("%s: not taking a new stream: %s", sid, why)
                return web.Response(status=401)
            if await self.may_publish(sid, key):
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
