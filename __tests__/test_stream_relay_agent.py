# __tests__/test_stream_relay_agent.py
#
# The relay agent on the droplet (stream_relay/agent/relay_agent.py). Pins:
# only a well-formed key on live/<key> can publish, and only this machine
# can read; every copy is `-c copy` (nothing re-encoded); a dropped stream
# never tells players "it's over" until the grace runs out, and a stream
# that comes back appends to the SAME recording; the finished playlist ends
# exactly once; no stream key reaches a log; a key that streamed before
# keeps working when the backend is down, and a refused key is forgotten.

import asyncio
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("relay_agent", ROOT / "stream_relay" / "agent" / "relay_agent.py")
ra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ra)

KEY = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"


def test_only_live_slash_a_key_is_a_stream():
    assert ra.key_from_path(f"live/{KEY}") == KEY
    for bad in (f"live/{KEY}/x", f"other/{KEY}", "live/short", "live/has space here 1234567", "", None):
        assert ra.key_from_path(bad) is None


def test_who_may_publish_and_read():
    assert ra.auth_decision({"action": "publish", "path": f"live/{KEY}", "ip": "203.0.113.9"}) == ("check", KEY)
    assert ra.auth_decision({"action": "publish", "path": "live/../x", "ip": "203.0.113.9"}) == ("deny", None)
    assert ra.auth_decision({"action": "read", "path": f"live/{KEY}", "ip": "127.0.0.1"}) == ("allow", None)
    assert ra.auth_decision({"action": "read", "path": f"live/{KEY}", "ip": "::1"}) == ("allow", None)
    assert ra.auth_decision({"action": "read", "path": f"live/{KEY}", "ip": "203.0.113.9"}) == ("deny", None)
    assert ra.auth_decision({"action": "api", "ip": "203.0.113.9"}) == ("deny", None)


def test_copies_are_never_re_encoded():
    src = f"rtsp://127.0.0.1:8554/live/{KEY}"
    fwd = ra.forward_cmd(src, "rtmps://a.rtmps.youtube.com/live2/yt")
    assert fwd[fwd.index("-c") + 1] == "copy" and fwd[-3:] == ["-f", "flv", "rtmps://a.rtmps.youtube.com/live2/yt"]
    hls = ra.hls_cmd(src, "/var/relay/s", resume=False)
    assert hls[hls.index("-c") + 1] == "copy"
    flags = hls[hls.index("-hls_flags") + 1]
    assert "omit_endlist" in flags and "append_list" in flags and "discont_start" not in flags
    assert hls[hls.index("-hls_playlist_type") + 1] == "event" and hls[hls.index("-hls_list_size") + 1] == "0"
    assert "discont_start" in ra.hls_cmd(src, "/var/relay/s", resume=True)[hls.index("-hls_flags") + 1]


def test_the_finished_recording_ends_once():
    text = "#EXTM3U\n#EXTINF:4.000,\nseg_000000.ts\n#EXTINF:3.5,\nseg_000001.ts\n"
    assert ra.playlist_seconds(text) == pytest.approx(7.5)
    done = ra.finalize_playlist(text)
    assert done.endswith("#EXT-X-ENDLIST\n") and ra.finalize_playlist(done).count("#EXT-X-ENDLIST") == 1


def test_segments_cache_forever_and_the_live_list_does_not():
    assert ra.object_headers("live/a/b/seg_000001.ts") == ("video/mp2t", "public, max-age=31536000, immutable")
    assert ra.object_headers("live/a/b/index.m3u8")[1] == "public, max-age=2"
    assert ra.object_headers("player.html")[0].startswith("text/html")


def test_restarts_back_off_and_stop_growing():
    assert [ra.backoff(n) for n in range(7)] == [1, 2, 4, 8, 16, 30, 30]


def test_no_stream_key_reaches_a_log():
    line = (f"rtsp://127.0.0.1:8554/live/{KEY}: error; "
            "rtmps://live-api-s.facebook.com:443/rtmp/FB-1-0-AbC?s_bl=1 refused; "
            "rtmps://a.rtmps.youtube.com/live2/abcd-efgh-ijkl closed")
    out = ra.redact(line)
    assert KEY not in out and "FB-1-0" not in out and "abcd-efgh" not in out
    assert out.count("<key>") == 3


# ─── the backend being down must not stop a Sunday ───────────────────


def _agent(tmp_path, status):
    cfg = ra.Config()
    cfg.work = tmp_path
    a = ra.Agent(cfg)

    async def backend(path, body):
        return status["code"], {}
    a.backend = backend
    return a


def test_a_known_key_keeps_working_when_the_backend_is_down(tmp_path):
    status = {"code": 200}
    a = _agent(tmp_path, status)
    assert asyncio.run(a.may_publish(KEY)) is True
    status["code"] = 0                       # Railway down
    assert asyncio.run(a.may_publish(KEY)) is True
    assert asyncio.run(a.may_publish("ZZZZZZZZZZZZZZZZZZZZ")) is False   # never seen: no
    status["code"] = 403                     # the church made a new key
    assert asyncio.run(a.may_publish(KEY)) is False
    status["code"] = 0
    assert asyncio.run(a.may_publish(KEY)) is False   # and the old one is forgotten


def test_the_cache_file_holds_no_key(tmp_path):
    a = _agent(tmp_path, {"code": 200})
    a.remember(KEY, [{"name": "youtube", "url": "rtmps://a.rtmps.youtube.com/live2/yt"}])
    names = [p.name for p in (tmp_path / "cache").iterdir()]
    assert names and all(KEY not in n for n in names)


# ─── a dropped stream resumes the same recording ─────────────────────


def test_a_stream_that_blinks_resumes_and_one_that_stays_gone_ends(tmp_path, monkeypatch):
    a = _agent(tmp_path, {"code": 200})
    a.cfg.grace = 600
    ready = {"keys": {KEY}}
    clock = {"t": 1000.0}
    starts, finished = [], []

    async def ready_keys():
        return set(ready["keys"])

    async def ask_started(live):
        live.info = {"session_id": "s1", "playlist_path": "live/b/s1/index.m3u8"}

    async def uploader(live):
        return None

    async def finish(live):
        finished.append(live)

    a.ready_keys = ready_keys
    a.ask_started = ask_started
    a.uploader = uploader
    a.finish = finish
    a.start_writers = lambda live: starts.append(live.runs) or setattr(live, "runs", live.runs + 1)
    monkeypatch.setattr(ra.time, "time", lambda: clock["t"])

    async def run():
        await a.tick()                       # up: one recording begins
        live = a.lives[KEY]
        assert live.up and starts == [0]
        ready["keys"] = set()
        clock["t"] += 5
        await a.tick()                       # dropped: waiting, not over
        assert KEY in a.lives and not live.up and finished == []
        ready["keys"] = {KEY}
        clock["t"] += 60
        await a.tick()                       # back within the grace: same Live, writers resume
        assert a.lives[KEY] is live and live.up and starts == [0, 1]
        ready["keys"] = set()
        clock["t"] += 5
        await a.tick()
        clock["t"] += 601
        await a.tick()                       # gone past the grace: over, once
        await asyncio.sleep(0)
        assert KEY not in a.lives and finished == [live]

    asyncio.run(run())
