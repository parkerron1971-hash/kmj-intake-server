"""relay_agent.py — the stream relay's brain, beside MediaMTX on the droplet.

A church's streaming software sends one stream to rtmp://stream.<domain>/live
with its stream key. MediaMTX receives it; this agent does everything else:

  * decides who may stream (MediaMTX asks POST /auth; the backend knows the
    keys, and a key seen before keeps working if the backend is down on a
    Sunday morning);
  * notices a stream come up (it polls MediaMTX's local API), asks the
    backend where copies go, and starts one ffmpeg per destination
    (YouTube, Facebook) plus one that writes HLS for the member app. All
    copies are `-c copy`: nothing is re-encoded, so a $6 droplet carries it;
  * uploads the HLS segments and playlist to Cloudflare R2 as they are
    written, so members watch live from R2 (no cost per viewer);
  * waits GRACE_S after a stream drops before calling it over: a church
    whose internet blinks reconnects into the SAME recording;
  * then closes the playlist, uploads it, and tells the backend the service
    ended, which makes the sermon draft.

Pure helpers sit at the top and import nothing outside the standard library,
so __tests__/test_stream_relay_agent.py can test them without aiohttp/boto3.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("relay")

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
LOCAL_IPS = {"127.0.0.1", "::1"}
SEGMENT_SECONDS = 4
PLAYLIST = "index.m3u8"


# ─── pure helpers ────────────────────────────────────────────────────


def key_from_path(path: Any) -> Optional[str]:
    """'live/<key>' → the key, or None for any other path."""
    m = re.match(r"^live/([^/]+)$", str(path or ""))
    if m and KEY_RE.match(m.group(1)):
        return m.group(1)
    return None


def auth_decision(req: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """What to do with one MediaMTX auth request.

    ('check', key)  publish: ask the backend about this key
    ('allow', None) a read from this machine (our own ffmpeg copies)
    ('deny', None)  everything else: nobody watches from the relay itself
    """
    action = str(req.get("action") or "")
    ip = str(req.get("ip") or "")
    if action == "publish":
        key = key_from_path(req.get("path"))
        return ("check", key) if key else ("deny", None)
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
    """(Content-Type, Cache-Control) for an upload. Segments never change;
    the playlist changes every few seconds while live."""
    if name.endswith(".ts"):
        return "video/mp2t", "public, max-age=31536000, immutable"
    if name.endswith(".m3u8"):
        return "application/vnd.apple.mpegurl", "public, max-age=2"
    if name.endswith(".html"):
        return "text/html; charset=utf-8", "public, max-age=300"
    return "application/octet-stream", "public, max-age=60"


def backoff(attempt: int) -> float:
    return float(min(30, 2 ** max(0, attempt)))


def redact(text: str) -> str:
    """No stream key in a log line: ours (live/<key>) or a platform's."""
    text = re.sub(r"(rtmps?://[^\s/]+(?::\d+)?/[^\s/]+/)[^\s]+", r"\g<1><key>", text or "")
    return re.sub(r"(rtsp://[^\s/]+/live/)[^\s]+", r"\g<1><key>", text)


def key_id(key: str) -> str:
    """A short, non-reversible name for a key (logs, folders, the cache)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


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
        self.player = Path(e("PLAYER_HTML") or "/app/player.html")

    def missing(self) -> List[str]:
        need = {"BACKEND_URL": self.backend, "STREAM_RELAY_SECRET": self.secret,
                "R2_ENDPOINT": self.r2_endpoint, "R2_ACCESS_KEY_ID": self.r2_key,
                "R2_SECRET_ACCESS_KEY": self.r2_secret, "R2_BUCKET": self.r2_bucket}
        return [k for k, v in need.items() if not v]


# ─── one church's stream ─────────────────────────────────────────────


class Live:
    def __init__(self, key: str, work: Path) -> None:
        self.key = key
        self.kid = key_id(key)
        self.started = time.time()
        # One folder per church, not per start: an agent restarted mid-
        # service finds the playlist and appends instead of starting over
        # (which would overwrite the first half's segments in R2).
        self.dir = work / "streams" / self.kid
        self.info: Optional[Dict[str, Any]] = None      # from the backend's /started
        self.dests: List[Dict[str, str]] = []
        self.up = True
        self.down_since: Optional[float] = None
        self.runs = 0                                   # HLS writer starts (resume after the first)
        self.gen = 0                                    # bumped per (re)start: an old copy never doubles up
        self.tasks: List[asyncio.Task] = []
        self.procs: Dict[str, asyncio.subprocess.Process] = {}
        self.uploaded: Dict[str, int] = {}              # name -> size
        self.playlist_sig = ""
        self.bytes = 0


class Agent:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.lives: Dict[str, Live] = {}
        self.cache_dir = cfg.work / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.http = None
        self.s3 = None

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

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key_id(key)}.json"

    def remember(self, key: str, dests: List[Dict[str, str]]) -> None:
        p = self._cache_path(key)
        p.write_text(json.dumps({"seen": time.time(), "dests": dests}))
        os.chmod(p, 0o600)

    def recall(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(self._cache_path(key).read_text())
        except (OSError, ValueError):
            return None
        return data if time.time() - float(data.get("seen") or 0) < 30 * 86400 else None

    def forget(self, key: str) -> None:
        try:
            self._cache_path(key).unlink()
        except OSError:
            pass

    async def may_publish(self, key: str) -> bool:
        status, _ = await self.backend("/stream-relay/relay/verify", {"key": key})
        if status == 200:
            if not self.recall(key):
                self.remember(key, [])
            return True
        if status in (401, 403, 404):
            self.forget(key)
            return False
        # The backend can't answer (0 / 5xx): a key that streamed here in the
        # last 30 days keeps working, so Sunday doesn't depend on Railway.
        return self.recall(key) is not None

    # ── MediaMTX ──

    async def ready_keys(self) -> Optional[set]:
        try:
            async with self.http.get(f"{self.cfg.mtx_api}/v3/paths/list", timeout=5) as r:
                data = await r.json()
        except Exception as e:
            log.warning("mediamtx api: %s", type(e).__name__)
            return None
        keys = set()
        for item in data.get("items") or []:
            k = key_from_path(item.get("name"))
            if k and item.get("ready"):
                keys.add(k)
        return keys

    # ── the loop ──

    async def tick(self) -> None:
        ready = await self.ready_keys()
        if ready is None:
            return
        now = time.time()
        for key in ready:
            live = self.lives.get(key)
            if live is None:
                await self.begin(key)
            elif not live.up:
                log.info("%s back after %.0fs: same recording", live.kid, now - (live.down_since or now))
                live.up, live.down_since = True, None
                self.start_writers(live)
            elif live.info is None:
                await self.ask_started(live)
        for key, live in list(self.lives.items()):
            if live.up and key not in ready:
                log.info("%s dropped; waiting %ss before calling it over", live.kid, int(self.cfg.grace))
                live.up, live.down_since = False, now
            elif not live.up and now - (live.down_since or now) >= self.cfg.grace:
                # Off the loop: reporting the end may wait on Railway, and
                # other churches' streams must not wait with it.
                self.lives.pop(key, None)
                asyncio.create_task(self.finish(live))

    async def begin(self, key: str) -> None:
        live = Live(key, self.cfg.work)
        self.lives[key] = live
        log.info("%s is live", live.kid)
        await self.ask_started(live)
        self.claim_dir(live)
        if live.info is None:
            cached = self.recall(key) or {}
            live.dests = list(cached.get("dests") or [])
            log.warning("%s: backend unreachable, forwarding to %d remembered destination(s)",
                        live.kid, len(live.dests))
        self.start_writers(live)
        live.tasks.append(asyncio.create_task(self.uploader(live)))

    async def ask_started(self, live: Live) -> None:
        status, data = await self.backend("/stream-relay/relay/started", {"key": live.key})
        if status == 200 and data.get("session_id"):
            first = live.info is None and not live.procs
            live.info = data
            marker = live.dir / "session.txt"
            if live.dir.exists() and not marker.exists():
                marker.write_text(str(data["session_id"]))
            new = list(data.get("destinations") or [])
            self.remember(live.key, new)
            if not first and {d["url"] for d in new} != {d["url"] for d in live.dests}:
                live.dests = new
                for d in new:   # destinations learned late start now
                    if f"fwd:{d['name']}" not in live.procs:
                        live.tasks.append(asyncio.create_task(self.supervise(
                            live, live.gen, f"fwd:{d['name']}", forward_cmd(self.src(live), d["url"]))))
            else:
                live.dests = new

    def claim_dir(self, live: Live) -> None:
        """Use the church's folder for this session. A folder left by a
        DIFFERENT session (its end never reached the backend) is moved
        aside, kept, and not appended to."""
        marker = live.dir / "session.txt"
        sid = str((live.info or {}).get("session_id") or "")
        if live.dir.exists() and sid and marker.exists() and marker.read_text().strip() != sid:
            live.dir.rename(live.dir.with_name(f"{live.kid}-orphan-{int(time.time())}"))
        live.dir.mkdir(parents=True, exist_ok=True)
        if sid and not marker.exists():
            marker.write_text(sid)

    def src(self, live: Live) -> str:
        return f"{self.cfg.mtx_rtsp}/live/{live.key}"

    def start_writers(self, live: Live) -> None:
        resume = live.runs > 0 or (live.dir / PLAYLIST).exists()
        live.runs += 1
        live.gen += 1
        live.tasks = [t for t in live.tasks if not t.done()]
        live.tasks.append(asyncio.create_task(self.supervise(
            live, live.gen, "hls", hls_cmd(self.src(live), str(live.dir), resume), resume_after=True)))
        for d in live.dests:
            live.tasks.append(asyncio.create_task(self.supervise(
                live, live.gen, f"fwd:{d['name']}", forward_cmd(self.src(live), d["url"]))))

    def _current(self, live: Live, gen: int) -> bool:
        return live.up and live.gen == gen and self.lives.get(live.key) is live

    async def supervise(self, live: Live, gen: int, name: str, cmd: List[str],
                        resume_after: bool = False) -> None:
        """Run one copy for as long as the stream is up; restart it with a
        growing pause if it falls over (a platform hiccup, a bad key). A
        copy from before a reconnect stops itself (`gen`), so YouTube never
        gets two."""
        attempt = 0
        while self._current(live, gen):
            started = time.time()
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE)
            live.procs[name] = proc
            _, err = await proc.communicate()
            if live.procs.get(name) is proc:
                live.procs.pop(name, None)
            if not self._current(live, gen):
                return
            tail = (err or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
            log.warning("%s %s exited %s: %s", live.kid, name, proc.returncode,
                        redact(tail[0].replace(live.key, "<key>"))[:200])
            attempt = 0 if time.time() - started > 60 else attempt + 1
            await asyncio.sleep(backoff(attempt))
            if resume_after:
                cmd = hls_cmd(self.src(live), str(live.dir), resume=True)

    async def uploader(self, live: Live) -> None:
        while self.lives.get(live.key) is live:
            try:
                await self.upload_new(live)
            except Exception as e:
                log.warning("%s upload: %s", live.kid, type(e).__name__)
            await asyncio.sleep(1)

    async def upload_new(self, live: Live, final: bool = False) -> None:
        if live.info is None:
            return    # no session yet: segments wait on disk
        prefix = live.info["playlist_path"].rsplit("/", 1)[0]
        for f in sorted(live.dir.glob("seg_*.ts")):
            size = f.stat().st_size
            if live.uploaded.get(f.name) == size:
                if time.time() - f.stat().st_mtime > 120:
                    f.unlink(missing_ok=True)   # uploaded long ago: free the disk
                continue
            await self.put(f"{prefix}/{f.name}", f.read_bytes())
            live.uploaded[f.name] = size
            live.bytes += size
        pl = live.dir / PLAYLIST
        if pl.exists():
            text = pl.read_text()
            if final:
                text = finalize_playlist(text)
            sig = hashlib.sha256(text.encode()).hexdigest()
            if sig != live.playlist_sig:
                await self.put(f"{prefix}/{PLAYLIST}", text.encode())
                live.playlist_sig = sig

    async def put(self, name: str, body: bytes) -> None:
        ctype, cache = object_headers(name)
        await asyncio.get_running_loop().run_in_executor(None, lambda: self.s3.put_object(
            Bucket=self.cfg.r2_bucket, Key=name, Body=body, ContentType=ctype, CacheControl=cache))

    async def finish(self, live: Live) -> None:
        """The stream didn't come back: close the recording and tell the backend."""
        for p in list(live.procs.values()):
            if p.returncode is None:
                p.terminate()
        for t in live.tasks:
            t.cancel()
        await asyncio.gather(*live.tasks, return_exceptions=True)
        for _ in range(30):   # Railway may be down too: keep the recording until it's safe
            if live.info is None:
                await self.ask_started(live)
            if live.info is not None:
                try:
                    await self.upload_new(live, final=True)
                except Exception as e:
                    log.warning("%s final upload: %s", live.kid, type(e).__name__)
                    await asyncio.sleep(10)
                    continue
                pl = live.dir / PLAYLIST
                seconds = playlist_seconds(pl.read_text()) if pl.exists() else 0.0
                status, data = await self.backend("/stream-relay/relay/ended", {
                    "session_id": live.info["session_id"], "duration_s": int(seconds), "bytes": live.bytes})
                if status == 200:
                    log.info("%s ended: %.0f min, sermon draft %s", live.kid, seconds / 60,
                             "made" if data.get("sermon_id") else "not made")
                    shutil.rmtree(live.dir, ignore_errors=True)
                    return
            await asyncio.sleep(60)
        kept = live.dir.with_name(f"{live.kid}-unreported-{int(time.time())}")
        try:
            live.dir.rename(kept)
        except OSError:
            kept = live.dir
        log.error("%s: could not report the end; recording kept in %s", live.kid, kept)

    # ── the auth door MediaMTX calls ──

    async def handle_auth(self, request):
        from aiohttp import web
        try:
            req = await request.json()
        except Exception:
            return web.Response(status=400)
        verdict, key = auth_decision(req)
        if verdict == "allow":
            return web.Response(status=200)
        if verdict == "check" and key and await self.may_publish(key):
            return web.Response(status=200)
        return web.Response(status=401)

    async def handle_health(self, request):
        from aiohttp import web
        return web.json_response({"ok": True, "live": len(self.lives)})

    async def upload_player(self) -> None:
        try:
            await self.put("player.html", self.cfg.player.read_bytes())
        except Exception as e:
            log.warning("player upload: %s", type(e).__name__)

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
        app = web.Application()
        app.router.add_post("/auth", self.handle_auth)
        app.router.add_get("/health", self.handle_health)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        host, port = self.cfg.listen.rsplit(":", 1)
        await web.TCPSite(runner, host, int(port)).start()
        await self.upload_player()
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
