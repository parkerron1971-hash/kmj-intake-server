# __tests__/test_stream_relay_mediamtx.py
#
# The relay against the REAL MediaMTX 1.9.3 binary and real ffmpeg
# publishers, with the shipped mediamtx.yml (only its addresses and
# certificate paths swapped for local ones) and the real agent; the
# backend and the bucket are faked. Pins Codex R1/R2/R3 where they can
# actually break:
#   * the church's secret never appears in MediaMTX's output or the
#     agent's log — on a good publish, a refused publish, our own RTSP
#     reads, and a disconnect;
#   * only TLS gets in: plain RTMP to the ingest port fails;
#   * a key the backend refuses mid-stream is disconnected through
#     MediaMTX's own API;
#   * the hourly key re-check (every second here) runs alongside a live
#     stream without disturbing it, and sends only the key's hash.
#
# Needs the binary and ffmpeg, so it skips unless MEDIAMTX_BIN is set:
#   MEDIAMTX_BIN=/path/to/mediamtx python -m pytest __tests__/test_stream_relay_mediamtx.py
# (CI has neither; run it before changing mediamtx.yml or the agent's
# auth/publisher code.)

import asyncio
import datetime
import importlib.util
import logging
import os
import pathlib
import shutil
import socket
import subprocess

import pytest
import yaml

BIN = os.environ.get("MEDIAMTX_BIN") or ""
FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not (BIN and os.path.exists(BIN) and FFMPEG),
                                reason="needs MEDIAMTX_BIN (MediaMTX 1.9.3) and ffmpeg")

ROOT = pathlib.Path(__file__).resolve().parent.parent / "stream_relay"
SID = "3f9a0c1d2e4b5a6c7d8e"
KEY = "SeCrEtKeY0123456789abcdefghijKLMN"
BAD = "WrOnGkEy0123456789abcdefghijKLMNO"


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _cert(d):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
    (d / "privkey.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                      serialization.NoEncryption()))
    (d / "fullchain.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _publish(url, seconds, out):
    return subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast",
         "-g", "30", "-c:a", "aac", "-f", "flv", url], stdout=subprocess.DEVNULL, stderr=open(out, "wb"))


def test_the_secret_stays_out_of_every_log_and_a_refused_key_is_cut(tmp_path):
    spec = importlib.util.spec_from_file_location("relay_agent_it", ROOT / "agent" / "relay_agent.py")
    ra = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ra)
    import aiohttp
    from aiohttp import web

    rtmps, rtsp, api, auth = _port(), _port(), _port(), _port()
    tls = tmp_path / "tls"
    tls.mkdir()
    _cert(tls)
    conf = yaml.safe_load((ROOT / "mediamtx.yml").read_text())
    conf.update({"rtmpsAddress": f"127.0.0.1:{rtmps}", "rtspAddress": f"127.0.0.1:{rtsp}",
                 "apiAddress": f"127.0.0.1:{api}", "authHTTPAddress": f"http://127.0.0.1:{auth}/auth",
                 "rtmpServerKey": str(tls / "privkey.pem"), "rtmpServerCert": str(tls / "fullchain.pem")})
    (tmp_path / "mediamtx.yml").write_text(yaml.safe_dump(conf))
    mtx_log = tmp_path / "mediamtx.log"

    lines = []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(self.format(record))
    handler = Keep()
    ra.log.addHandler(handler)
    ra.log.setLevel(logging.DEBUG)

    state = {"revoked": False, "calls": [], "confirm_bodies": []}
    puts = {}
    copy_file = tmp_path / "youtube_copy.flv"

    class Agent(ra.Agent):
        async def backend(self, path, body):
            state["calls"].append(path)
            ok = body.get("key") == KEY and body.get("stream_id") == SID and not state["revoked"]
            if path.endswith("/confirm"):          # the hourly re-check (every second here)
                state["confirm_bodies"].append(repr(body))
                good = ra.key_hash(KEY)
                return 200, {"confirmed": [g["stream_id"] for g in body.get("grants") or []
                                           if g.get("stream_id") == SID and g.get("key_hash") == good
                                           and not state["revoked"]]}
            if path.endswith("/verify"):
                return (200, {"destinations": [{"name": "youtube", "url": str(copy_file)}]}) if ok else (403, {})
            if path.endswith("/started"):
                return (200, {"session_id": "00000000-0000-4000-8000-000000000001",
                              "playlist_path": "live/b/s/index.m3u8",
                              "destinations": [{"name": "youtube", "url": str(copy_file)}]}) if ok else (403, {})
            return 200, {}

        async def put(self, name, body):
            puts[name] = len(body)

    cfg = ra.Config()
    cfg.work, cfg.grace, cfg.beat_s, cfg.grant_sync_s = tmp_path / "work", 5, 2, 1
    cfg.mtx_api, cfg.mtx_rtsp = f"http://127.0.0.1:{api}", f"rtsp://127.0.0.1:{rtsp}"
    agent = Agent(cfg)

    async def scenario():
        mtx = subprocess.Popen([BIN, str(tmp_path / "mediamtx.yml")], stdout=open(mtx_log, "wb"),
                               stderr=subprocess.STDOUT, cwd=tmp_path)
        agent.http = aiohttp.ClientSession()
        app = web.Application()
        app.router.add_post("/auth", agent.handle_auth)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", auth).start()
        stop = asyncio.Event()

        async def loop():
            while not stop.is_set():
                try:
                    await agent.tick()
                except Exception:
                    ra.log.exception("tick failed")
                await asyncio.sleep(0.5)
        looper = asyncio.create_task(loop())
        pubs = []
        try:
            for _ in range(50):
                if await agent.publishers() is not None:
                    break
                await asyncio.sleep(0.2)
            # A wrong key, and plain RTMP to the TLS port: neither gets in.
            bad = _publish(f"rtmps://127.0.0.1:{rtmps}/live/{SID}?key={BAD}", 3, tmp_path / "bad.err")
            plain = _publish(f"rtmp://127.0.0.1:{rtmps}/live/{SID}?key={KEY}", 3, tmp_path / "plain.err")
            pubs += [bad, plain]
            assert await asyncio.to_thread(bad.wait, 30) != 0
            assert await asyncio.to_thread(plain.wait, 30) != 0
            assert SID not in agent.lives
            # The right key: recorded, uploaded and copied.
            good = _publish(f"rtmps://127.0.0.1:{rtmps}/live/{SID}?key={KEY}", 60, tmp_path / "good.err")
            pubs.append(good)
            for _ in range(60):
                await asyncio.sleep(0.5)
                if any(n.endswith(".ts") for n in puts) and copy_file.exists() and copy_file.stat().st_size > 0:
                    break
            assert SID in agent.lives and agent.lives[SID].up
            assert any(n.endswith(".ts") for n in puts) and "live/b/s/index.m3u8" in puts
            assert copy_file.stat().st_size > 0
            # The church replaces its key: the next heartbeat disconnects it.
            state["revoked"] = True
            assert await asyncio.to_thread(good.wait, 30) is not None
            assert agent.lives[SID].revoked
        finally:
            for p in pubs:
                if p.poll() is None:
                    p.kill()
            stop.set()
            await looper
            for lv in agent.lives.values():
                agent.stop_writers(lv)
            await asyncio.sleep(1)
            await agent.http.close()
            await runner.cleanup()
            mtx.terminate()
            mtx.wait(10)

    asyncio.run(scenario())
    ra.log.removeHandler(handler)
    mtx_text = mtx_log.read_text(errors="replace")
    agent_text = "\n".join(lines)
    assert f"live/{SID}" in mtx_text                        # it does log the path...
    assert "authentication failed" in mtx_text               # ...and the refusal...
    for secret in (KEY, BAD):                                # ...but never a secret
        assert secret not in mtx_text, "MediaMTX logged a stream key"
        assert secret not in agent_text, "the agent logged a stream key"
    assert "disconnected" in agent_text and "/stream-relay/relay/started" in state["calls"]
    # The good stream ran through re-checks, and they carried only the hash.
    assert any(ra.key_hash(KEY) in b for b in state["confirm_bodies"])
    assert all(KEY not in b for b in state["confirm_bodies"])
