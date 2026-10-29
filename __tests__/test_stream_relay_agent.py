# __tests__/test_stream_relay_agent.py
#
# The relay agent on the droplet (stream_relay/agent/relay_agent.py). Pins:
# the secret never rides in the path MediaMTX logs (live/<stream id>, the
# key in the query) and only this machine can read; every copy is
# `-c copy`; nothing uploaded is marked public; no stream key reaches a
# log; a key the backend confirmed keeps working while it is down — only
# for its own church and only for a bounded window — and a refused key is
# forgotten; a key the backend refuses mid-stream is cut at the next
# heartbeat (R3), and a running stream whose key the backend hasn't
# confirmed within the window is cut too, on the agent's own clock (R3-R);
# every remembered key (one per church, only its hash) is re-confirmed
# hourly, in chunks of 200: confirmed keys start their day again, keys left
# out are forgotten and their streams cut, and a failed, late or malformed
# re-check changes nothing (Kevin's call, 2026-10-29; C1-F); a heartbeat
# answered after the key ran out renews nothing (R3-F2), and a failed
# disconnect is retried from the agent's own pass (R3-F1);
# copies follow the backend's current destinations, and a stopped copy is
# killed if it won't stop (R11); a dropped stream resumes the same
# recording, a restarted agent picks up its journals and still finishes,
# and a finish retries until it is acknowledged (R4); a finish only ever
# removes its own run's folder (R5), and a journal left past the grace is
# finished, never appended to; the disk, the recording's length and
# backlog, the number of streams and the ingest rate are bounded (R6), with
# MediaMTX's API down, a disk that can't be read, and churches arriving at
# once (R6-R).

import asyncio
import hashlib
import importlib.util
import json
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("relay_agent", ROOT / "stream_relay" / "agent" / "relay_agent.py")
ra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ra)

SID = "3f9a0c1d2e4b5a6c7d8e"
SID2 = "0123456789abcdef0123"
SID3 = "abcdefabcdefabcdef01"
KEY = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"
NEW_KEY = "ZyXwVuTsRqPoNmLkJiHgFeDcBa543210"
SESSION = "00000000-0000-4000-8000-000000000001"
YT = {"name": "youtube", "label": "YouTube", "url": "rtmps://a.rtmps.youtube.com/live2/yt-1"}
FB = {"name": "facebook", "label": "Facebook", "url": "rtmps://live-api-s.facebook.com:443/rtmp/FB-1?s=1"}
STARTED = {"session_id": SESSION, "playlist_path": f"live/biz/{SESSION}/index.m3u8", "destinations": [YT]}


# ─── pure helpers ────────────────────────────────────────────────────


def test_the_path_names_the_church_and_the_secret_rides_in_the_query():
    assert ra.stream_id_from_path(f"live/{SID}") == SID
    for bad in (f"live/{KEY}", f"live/{SID}/x", f"other/{SID}", "live/short", "", None):
        assert ra.stream_id_from_path(bad) is None
    assert ra.key_from_query(f"key={KEY}") == KEY
    for bad in ("", "key=short", f"key={KEY}&key={KEY}", f"pass={KEY}", "key=has space in it 1234567890123"):
        assert ra.key_from_query(bad) is None


def test_who_may_publish_and_read():
    pub = {"action": "publish", "path": f"live/{SID}", "query": f"key={KEY}", "ip": "203.0.113.9"}
    assert ra.auth_decision(pub) == ("check", (SID, KEY))
    assert ra.auth_decision({**pub, "query": ""}) == ("deny", None)
    assert ra.auth_decision({**pub, "path": f"live/{KEY}", "query": ""}) == ("deny", None)   # the old shape
    assert ra.auth_decision({"action": "read", "path": f"live/{SID}", "ip": "127.0.0.1"}) == ("allow", None)
    assert ra.auth_decision({"action": "read", "path": f"live/{SID}", "ip": "::1"}) == ("allow", None)
    assert ra.auth_decision({"action": "read", "path": f"live/{SID}", "ip": "203.0.113.9"}) == ("deny", None)
    assert ra.auth_decision({"action": "api", "ip": "203.0.113.9"}) == ("deny", None)


def test_copies_are_never_re_encoded_and_carry_no_secret():
    src = f"rtsp://127.0.0.1:8554/live/{SID}"
    fwd = ra.forward_cmd(src, "rtmps://a.rtmps.youtube.com/live2/yt")
    assert fwd[fwd.index("-c") + 1] == "copy" and fwd[-3:] == ["-f", "flv", "rtmps://a.rtmps.youtube.com/live2/yt"]
    hls = ra.hls_cmd(src, "/var/relay/s", resume=False)
    assert hls[hls.index("-c") + 1] == "copy" and KEY not in " ".join(hls)
    flags = hls[hls.index("-hls_flags") + 1]
    assert "omit_endlist" in flags and "append_list" in flags and "discont_start" not in flags
    assert hls[hls.index("-hls_playlist_type") + 1] == "event" and hls[hls.index("-hls_list_size") + 1] == "0"
    assert "discont_start" in ra.hls_cmd(src, "/var/relay/s", resume=True)[hls.index("-hls_flags") + 1]


def test_the_finished_recording_ends_once():
    text = "#EXTM3U\n#EXTINF:4.000,\nseg_000000.ts\n#EXTINF:3.5,\nseg_000001.ts\n"
    assert ra.playlist_seconds(text) == pytest.approx(7.5)
    done = ra.finalize_playlist(text)
    assert done.endswith("#EXT-X-ENDLIST\n") and ra.finalize_playlist(done).count("#EXT-X-ENDLIST") == 1


def test_nothing_uploaded_is_marked_public():
    """Codex R7: the bucket is private; objects say so too."""
    assert ra.object_headers("live/a/b/seg_000001.ts") == ("video/mp2t", "private, max-age=31536000, immutable")
    assert ra.object_headers("live/a/b/index.m3u8") == ("application/vnd.apple.mpegurl", "private, no-cache")
    for name in ("live/a/b/seg_000001.ts", "live/a/b/index.m3u8", "player.html"):
        assert "public" not in ra.object_headers(name)[1]


def test_restarts_back_off_and_stop_growing():
    assert [ra.backoff(n) for n in range(7)] == [1, 2, 4, 8, 16, 30, 30]
    assert ra.backoff(20, cap=600) == 600


def test_no_stream_key_reaches_a_log():
    line = (f"rtmps://stream.example.app:443/live/{SID}?key={KEY}: error; "
            "rtmps://live-api-s.facebook.com:443/rtmp/FB-1-0-AbC?s_bl=1 refused; "
            "rtmps://a.rtmps.youtube.com/live2/abcd-efgh-ijkl closed; query 'key=" + KEY + "'")
    out = ra.redact(line)
    assert KEY not in out and "FB-1-0" not in out and "abcd-efgh" not in out


def test_the_ingest_rate_is_measured():
    assert ra.ingest_mbps(ra.collections.deque([(0.0, 0), (10.0, 12_500_000)])) == pytest.approx(10.0)
    assert ra.ingest_mbps(ra.collections.deque([(0.0, 0)])) == 0.0


# ─── a test agent: a fake backend, MediaMTX and bucket; no ffmpeg ────


class Harness:
    def __init__(self, tmp_path, monkeypatch, **cfg):
        c = ra.Config()
        c.work = tmp_path
        # Long enough that a test jumping hours ahead isn't cut for silence;
        # the tests of the window itself set their own.
        c.grace, c.beat_s, c.offline_s = 600, 60, 7 * 86400
        for k, v in cfg.items():
            setattr(c, k, v)
        self.clock = {"t": 1_000_000.0}
        monkeypatch.setattr(ra.time, "time", lambda: self.clock["t"])
        monkeypatch.setattr(ra, "backoff", lambda attempt, cap=30: 0)
        self.a = ra.Agent(c)
        self.calls, self.kicks, self.puts, self.copies = [], [], {}, []
        self.answers = {}                  # path's last part -> (status, data) or an async callable
        self.pubs = {}
        self.free = 50 * 10**9
        self.kick_works = True             # False: MediaMTX's kick fails and the publisher stays
        a = self.a

        async def backend(path, body):
            self.calls.append((path.rsplit("/", 1)[-1], dict(body)))
            ans = self.answers.get(path.rsplit("/", 1)[-1], (200, {}))
            return await ans(body) if callable(ans) else ans

        async def publishers():
            return {sid: dict(p) for sid, p in self.pubs.items()}

        async def kick(sid, conn):
            self.kicks.append(sid)
            if self.kick_works:
                self.pubs.pop(sid, None)
            return self.kick_works

        async def put(name, body):
            self.puts[name] = body

        async def supervise(sid, c, make_cmd):
            self.copies.append((c.name, c.url, make_cmd()))
            while not c.stopped:
                await asyncio.sleep(0.005)

        a.backend, a.publishers, a.kick, a.put, a.supervise = backend, publishers, kick, put, supervise
        a.free_disk = lambda: self.free
        self.started(STARTED)

    def started(self, data, status=200):
        self.answers["started"] = (status, data)

    def publish(self, sid=SID, key=KEY, nbytes=0, admit=True):
        """MediaMTX lists a publisher. It got in through /auth, so the
        backend confirmed its key just now (admit=False: the test let it
        in through handle_auth itself)."""
        if admit:
            self.a.remember(key, sid, [])
        self.pubs[sid] = {"key": key, "conn": ("rtmpsconns", f"conn-{sid}"), "bytes": nbytes}

    def later(self, s):
        self.clock["t"] += s

    def running(self, live):
        return sorted([n for n, c in live.fwd.items() if not c.stopped] + (["hls"] if live.hls else []))

    def said(self, what):
        return [b for p, b in self.calls if p == what]


def run(coro):
    return asyncio.run(coro)


async def settle():
    for _ in range(5):
        await asyncio.sleep(0.01)


def test_a_known_key_keeps_working_offline_only_for_its_church_and_a_while(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, offline_s=8 * 86400)
    a = h.a
    h.answers["verify"] = (200, {"destinations": [YT]})
    assert run(a.may_publish(SID, KEY)) is True
    h.answers["verify"] = (0, {})                                     # Railway down
    assert run(a.may_publish(SID, KEY)) is True
    assert run(a.may_publish(SID2, KEY)) is False                    # not on another church's path
    assert run(a.may_publish(SID, NEW_KEY)) is False                 # never seen: no
    h.later(8 * 86400 + 1)
    assert run(a.may_publish(SID, KEY)) is False                     # the window is bounded
    h.answers["verify"] = (200, {"destinations": []})
    assert run(a.may_publish(SID, KEY)) is True
    h.answers["verify"] = (403, {})                                   # the church made a new key
    assert run(a.may_publish(SID, KEY)) is False
    h.answers["verify"] = (0, {})
    assert run(a.may_publish(SID, KEY)) is False                     # and the old one is forgotten


def test_the_cache_file_holds_no_church_key(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.a.remember(KEY, SID, [YT])
    names = [p.name for p in (tmp_path / "cache").iterdir()]
    assert names and all(KEY not in n for n in names)
    assert all(KEY not in p.read_text() for p in (tmp_path / "cache").iterdir())


def test_a_stream_records_forwards_and_reports_its_session(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    a = h.a

    async def go():
        h.answers["verify"] = (200, {"destinations": [YT]})
        await a.may_publish(SID, KEY)                                 # MediaMTX's auth call
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        assert h.running(live) == ["hls", "youtube"]
        started = h.said("started")
        assert started and started[0]["run_id"] == live.run.run_id and started[0]["key"] == KEY
        assert live.run.session_id == SESSION
        journal = json.loads((live.run.dir / "run.json").read_text())
        assert journal["session_id"] == SESSION and journal["key"] is None   # no key on disk once known
        hls = [cmd for name, _, cmd in h.copies if name == "hls"][0]
        assert live.run.dir.parent.name == SID and hls[hls.index("-i") + 1].endswith(f"/live/{SID}")
    run(go())


def test_a_replaced_key_is_cut_at_the_next_heartbeat(tmp_path, monkeypatch):
    """Codex R3: the backend says no to a key mid-stream → disconnect, stop
    every copy, forget the key; a reconnect on the NEW key carries on."""
    h = Harness(tmp_path, monkeypatch)
    a = h.a

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        a.remember(KEY, SID, [YT])
        h.started({"detail": "unknown stream key"}, status=403)
        h.later(61)
        await a.tick()
        await settle()
        assert h.kicks == [SID] and h.running(live) == [] and live.revoked
        assert a.recall(KEY, SID) is None
        await a.tick()
        await settle()
        assert h.running(live) == []                                  # nothing restarts on the old key
        h.started({"session_id": SESSION, "playlist_path": f"live/biz/{SESSION}/index.m3u8", "destinations": [YT]})
        h.publish(key=NEW_KEY)
        await a.tick()
        await settle()
        assert a.lives[SID] is live and h.running(live) == ["hls", "youtube"] and not live.revoked
    run(go())


def test_a_refused_key_still_connected_is_disconnected_again_and_never_readmitted(tmp_path, monkeypatch):
    """Codex R3: if the first disconnect doesn't take, the refused key is
    neither picked back up nor left running; a new key that takes over the
    church's path (MediaMTX lets it replace the old publisher) carries on."""
    h = Harness(tmp_path, monkeypatch)
    a = h.a
    h.kick_works = False                                              # the publisher stays listed

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        h.started({"detail": "unknown stream key"}, status=403)
        h.later(61)
        await a.tick()
        await settle()
        assert h.kicks == [SID] and live.revoked and h.running(live) == []
        beats_on_old_key = len([b for b in h.said("started") if b["key"] == KEY])
        for _ in range(7):
            h.later(11)
            await a.tick()
            await settle()
        assert len(h.kicks) == 8 and live.revoked and live.key is None and h.running(live) == []
        assert len([b for b in h.said("started") if b["key"] == KEY]) == beats_on_old_key
        h.started({"session_id": SESSION, "playlist_path": "p/index.m3u8", "destinations": [YT]})
        h.publish(key=NEW_KEY)                                        # replaced on the same path, no drop
        await a.tick()
        await settle()
        assert not live.revoked and live.key == NEW_KEY and h.running(live) == ["hls", "youtube"]
        assert h.said("started")[-1]["key"] == NEW_KEY
    run(go())


def test_copies_follow_the_backends_destinations(tmp_path, monkeypatch):
    """Codex R11: a removed copy stops, a changed key restarts, a new one starts."""
    h = Harness(tmp_path, monkeypatch)
    a = h.a

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        yt = live.fwd["youtube"]
        h.started({"session_id": SESSION, "playlist_path": "p/index.m3u8", "destinations": []})
        h.later(61)
        await a.tick()
        await settle()
        assert yt.stopped and h.running(live) == ["hls"]
        moved = {**YT, "url": "rtmps://a.rtmps.youtube.com/live2/yt-2"}
        h.started({"session_id": SESSION, "playlist_path": "p/index.m3u8", "destinations": [moved, FB]})
        h.later(61)
        await a.tick()
        await settle()
        assert h.running(live) == ["facebook", "hls", "youtube"] and live.fwd["youtube"].url == moved["url"]
        h.started({}, status=0)                                       # the backend is down: keep going
        h.later(61)
        await a.tick()
        await settle()
        assert h.running(live) == ["facebook", "hls", "youtube"]
    run(go())


def test_a_dropped_stream_resumes_the_same_recording_and_one_gone_too_long_is_finished(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    a = h.a
    h.answers["ended"] = (200, {"sermon_id": "x"})

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        first = live.run
        h.pubs.clear()
        h.later(5)
        await a.tick()
        assert SID in a.lives and not live.up and h.running(live) == []
        h.publish()
        h.later(60)
        await a.tick()
        await settle()
        assert a.lives[SID] is live and live.run is first and h.running(live) == ["hls", "youtube"]
        h.pubs.clear()
        h.later(5)
        await a.tick()
        h.later(601)
        await a.tick()
        await settle()
        assert SID not in a.lives and h.said("ended")[0]["session_id"] == SESSION
        assert not first.dir.exists()
    run(go())


def test_a_restarted_agent_finishes_a_recording_left_waiting(tmp_path, monkeypatch):
    """Codex R4: the agent restarts while the church is offline; the
    journal still gets the service finished after the grace."""
    h = Harness(tmp_path, monkeypatch)
    old = ra.Run(tmp_path, SID)
    old.session_id, old.playlist_path = SESSION, f"live/biz/{SESSION}/index.m3u8"
    old.save()
    (old.dir / "index.m3u8").write_text("#EXTM3U\n#EXTINF:4.0,\nseg_000000.ts\n")
    (old.dir / "seg_000000.ts").write_bytes(b"x" * 10)
    h.answers["ended"] = (200, {})

    async def go():
        h.a.recover()
        assert h.a.recovered and h.a.lives[SID].run.run_id == old.run_id
        await h.a.tick()
        h.later(601)
        await h.a.tick()
        await settle()
        ended = h.said("ended")
        assert ended and ended[0]["session_id"] == SESSION and ended[0]["duration_s"] == 4
        assert h.puts[f"live/biz/{SESSION}/index.m3u8"].endswith(b"#EXT-X-ENDLIST\n")
        assert not old.dir.exists()
    run(go())


def test_a_restarted_agent_resumes_a_stream_still_coming_in(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    old = ra.Run(tmp_path, SID)
    old.session_id, old.playlist_path = SESSION, "p/index.m3u8"
    old.save()
    (old.dir / "index.m3u8").write_text("#EXTM3U\n")

    async def go():
        h.a.recover()
        h.publish()                                                   # MediaMTX kept the publisher
        await h.a.tick()
        await settle()
        live = h.a.lives[SID]
        assert live.run.run_id == old.run_id and h.running(live) == ["hls", "youtube"]
        hls = [cmd for name, _, cmd in h.copies if name == "hls"][0]
        assert "discont_start" in hls[hls.index("-hls_flags") + 1]   # appended, not overwritten
    run(go())


def test_a_finish_in_progress_at_restart_carries_on_until_acknowledged(tmp_path, monkeypatch):
    """Codex R4: no give-up after N tries; the journal outlives restarts."""
    h = Harness(tmp_path, monkeypatch)
    old = ra.Run(tmp_path, SID)
    old.session_id, old.playlist_path, old.state = SESSION, "p/index.m3u8", "finishing"
    old.save()
    answers = iter([(0, {}), (503, {}), (0, {}), (200, {"sermon_id": "s"})])

    async def ended(body):
        return next(answers)
    h.answers["ended"] = ended

    async def go():
        h.a.recover()
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not old.dir.exists() and not h.a.finishing:
                break
        assert len(h.said("ended")) == 4 and not old.dir.exists() and not h.a.finishing
    run(go())


def test_a_recording_made_while_the_backend_was_down_still_gets_its_session(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    a = h.a
    h.started({}, status=0)
    h.answers["ended"] = (200, {})

    async def go():
        h.publish()
        await a.tick()
        await settle()
        run_ = a.lives[SID].run
        assert run_.session_id is None and json.loads((run_.dir / "run.json").read_text())["key"] == KEY
        h.pubs.clear()
        h.later(5)
        await a.tick()
        h.started({"session_id": SESSION, "playlist_path": "p/index.m3u8", "destinations": []})
        h.later(601)
        await a.tick()
        await settle()
        assert h.said("ended")[0]["session_id"] == SESSION and not run_.dir.exists()
        asked_at_end = h.said("started")[-1]
        assert asked_at_end["ending"] is True and asked_at_end["key"] == KEY   # no "live now" after the fact
        assert all("ending" not in b for b in h.said("started")[:-1])
    run(go())


def test_a_slow_finish_never_touches_the_next_streams_recording(tmp_path, monkeypatch):
    """Codex R5: the church is back while the last service is still being
    reported; the new recording has its own folder and survives."""
    h = Harness(tmp_path, monkeypatch)
    a = h.a

    async def go():
        release = asyncio.Event()

        async def slow(body):
            await release.wait()
            return 200, {}
        h.answers["ended"] = slow
        h.publish()
        await a.tick()
        await settle()
        first = a.lives[SID].run
        h.pubs.clear()
        h.later(5)
        await a.tick()
        h.later(601)
        await a.tick()                                                # finishing, blocked
        await settle()
        h.publish()
        h.started({"session_id": "00000000-0000-4000-8000-000000000002", "playlist_path": "q/index.m3u8",
                   "destinations": []})
        await a.tick()
        await settle()
        second = a.lives[SID].run
        assert second.run_id != first.run_id and second.dir != first.dir
        (second.dir / "index.m3u8").write_text("#EXTM3U\n")
        release.set()
        await settle()
        assert not first.dir.exists() and (second.dir / "index.m3u8").exists()
    run(go())


def test_a_session_the_backend_closed_continues_in_a_new_recording(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    a = h.a
    h.answers["ended"] = (200, {})

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        first = live.run
        h.started({"detail": {"session_id": SESSION, "playlist_path": "p/index.m3u8"}}, status=409)
        h.later(61)
        await a.tick()
        await settle()
        assert live.run is not first and h.running(live) == ["hls", "youtube"]
        assert h.said("ended")[0]["session_id"] == SESSION
    run(go())


def test_a_full_disk_or_a_full_house_refuses_new_streams_only(tmp_path, monkeypatch):
    """Codex R6: admission control."""
    h = Harness(tmp_path, monkeypatch, max_streams=1, reserve=2 * 10**9)
    a = h.a
    assert a.refusal(SID) == ""
    h.free = 10**9
    assert "disk" in a.refusal(SID)
    h.free = 50 * 10**9

    async def go():
        h.publish()
        await a.tick()
        assert "streams" in a.refusal(SID2)
        assert a.refusal(SID) == ""                                    # the same church may come back

        class Req:
            async def json(self):
                return {"action": "publish", "path": f"live/{SID2}", "query": f"key={NEW_KEY}", "ip": "203.0.113.9"}
        r = await a.handle_auth(Req())
        assert r.status == 401 and not h.said("verify")              # refused before the backend is asked
    run(go())


@pytest.mark.parametrize("why", ["length", "backlog", "disk"])
def test_a_recording_that_runs_away_stops_but_the_copies_go_on(tmp_path, monkeypatch, why):
    """Codex R6: bounded length, upload backlog and disk; YouTube keeps its copy."""
    h = Harness(tmp_path, monkeypatch, max_record_s=6 * 3600, spool_max=1000, reserve=2 * 10**9)
    a = h.a

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        if why == "length":
            h.later(6 * 3600 + 1)
        elif why == "backlog":
            (live.run.dir / "seg_000000.ts").write_bytes(b"x" * 2000)
        else:
            h.free = 10**8
        h.later(11)
        await a.tick()
        await settle()
        assert live.run.stopped == why and h.running(live) == ["youtube"]
        assert json.loads((live.run.dir / "run.json").read_text())["stopped"] == why
        if why == "disk":
            h.free = 50 * 10**9
            h.later(11)
            await a.tick()
            await settle()
            assert live.run.stopped == "" and h.running(live) == ["hls", "youtube"]
    run(go())


def test_a_publisher_sending_too_much_is_disconnected(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, max_mbps=25)
    a = h.a

    async def go():
        for i in range(31):
            h.publish(nbytes=i * 5_000_000)                           # 40 Mbps
            await a.tick()
            h.later(1)
        await settle()
        assert h.kicks == [SID]
    run(go())


class Auth:
    """MediaMTX's auth request for a church's publish."""

    def __init__(self, sid=SID, key=KEY):
        self.body = {"action": "publish", "path": f"live/{sid}", "query": f"key={key}", "ip": "203.0.113.9"}

    async def json(self):
        return self.body


def test_a_stream_whose_key_goes_unconfirmed_past_the_window_is_cut(tmp_path, monkeypatch):
    """Codex R3-R: the backend stops answering mid-stream. The stream keeps
    going for OFFLINE_GRANT_S after its key was last confirmed, then the
    publisher is disconnected and every copy and the recording stop. It
    can't come back on the stale grant, and carries on once the backend
    confirms the key again."""
    h = Harness(tmp_path, monkeypatch, offline_s=120)
    a = h.a

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        assert h.running(live) == ["hls", "youtube"]
        h.started({}, status=503)
        h.answers["verify"] = (503, {})
        h.later(61)
        await a.tick()
        await settle()
        assert h.running(live) == ["hls", "youtube"] and not h.kicks      # inside the window
        h.later(60)                                                       # 121 s since the last confirmation
        await a.tick()
        await settle()
        assert a.recall(KEY, SID) is None
        assert h.kicks == [SID] and live.revoked and h.running(live) == []
        h.later(1)
        await a.tick()
        await settle()
        assert h.running(live) == []                                      # nothing restarts
        assert (await a.handle_auth(Auth())).status == 401                # no way back on the stale grant
        h.answers["verify"] = (200, {"destinations": [YT]})
        h.started(STARTED)
        h.later(5)
        assert (await a.handle_auth(Auth())).status == 200                # the backend knows the key again
        h.publish(admit=False)
        await a.tick()
        await settle()
        assert a.lives[SID] is live and not live.revoked and h.running(live) == ["hls", "youtube"]
    run(go())


def test_an_expired_grant_is_cut_even_while_mediamtx_cant_be_read(tmp_path, monkeypatch):
    """Codex R3-R: the deadline keeps its own clock. With MediaMTX's API down
    as well, the copies and the recording stop at expiry, and the
    disconnect is tried again every 10 s until it takes."""
    h = Harness(tmp_path, monkeypatch, offline_s=120)
    a = h.a
    listing = a.publishers

    async def unreadable():
        return None

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        h.started({}, status=0)
        h.kick_works = False
        a.publishers = unreadable
        h.later(121)
        await a.tick()
        await settle()
        assert live.revoked and h.running(live) == [] and h.kicks == [SID]
        a.publishers = listing                                            # the API is back; still connected
        for _ in range(3):
            h.later(11)
            await a.tick()
            await settle()
        assert h.kicks == [SID] * 4 and h.running(live) == []
    run(go())


def test_the_offline_window_is_short_unless_set(monkeypatch):
    """Codex R3-R, Kevin's call (2026-10-29): a day, re-confirmed every hour,
    unless OFFLINE_GRANT_S / GRANT_SYNC_S say otherwise."""
    for name in ("OFFLINE_GRANT_S", "GRANT_SYNC_S"):
        monkeypatch.delenv(name, raising=False)
    assert ra.Config().offline_s == 24 * 3600 and ra.Config().grant_sync_s == 3600
    monkeypatch.setenv("OFFLINE_GRANT_S", "600")
    monkeypatch.setenv("GRANT_SYNC_S", "60")
    assert ra.Config().offline_s == 600 and ra.Config().grant_sync_s == 60


def sha(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def confirm_all(body):
    """The backend's /relay/confirm when every key it's asked about is good."""
    return 200, {"confirmed": [g["stream_id"] for g in body["grants"]]}


def seen(tmp_path, sid):
    return json.loads((tmp_path / "cache" / f"{sid}.json").read_text())["seen"]


def test_an_hourly_reconfirm_keeps_every_remembered_key_fresh(tmp_path, monkeypatch):
    """Kevin's call: the agent re-confirms every key it remembers with the
    backend every GRANT_SYNC_S, sending only the hash the backend stores.
    A confirmation counts from when it was asked, and moves a running
    stream's deadline too: an outage that starts after the last re-check
    still leaves the whole window."""
    h = Harness(tmp_path, monkeypatch, offline_s=86400, grant_sync_s=3600, max_record_s=7 * 86400)
    a = h.a
    t0 = h.clock["t"]
    a.remember(NEW_KEY, SID2, [])
    h.answers["confirm"] = confirm_all

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        h.started({}, status=503)                                     # only the re-check confirms now
        h.later(3600)
        await a.tick()
        await settle()
        asked = h.said("confirm")
        assert len(asked) == 2
        assert sorted((g["stream_id"], g["key_hash"]) for g in asked[-1]["grants"]) == \
            sorted([(SID, sha(KEY)), (SID2, sha(NEW_KEY))])
        assert KEY not in json.dumps(asked) and NEW_KEY not in json.dumps(asked)
        assert seen(tmp_path, SID) == seen(tmp_path, SID2) == t0 + 3600
        h.answers["confirm"] = (0, {})                                # Railway goes down after that
        h.answers["verify"] = (0, {})
        h.later(86400 - 3600 + 60)                                    # a day and a minute since t0
        await a.tick()
        await settle()
        assert await a.may_publish(SID2, NEW_KEY)                     # the 1-hour re-check still holds
        assert h.running(live) == ["hls", "youtube"] and not h.kicks
        h.later(3600)                                                 # a day past the last re-check
        await a.tick()
        await settle()
        assert not await a.may_publish(SID2, NEW_KEY)
        assert h.kicks == [SID] and h.running(live) == []
    run(go())


def test_a_reconfirm_that_leaves_a_church_out_drops_it_and_cuts_its_stream(tmp_path, monkeypatch):
    """Kevin's call: a key the backend no longer confirms (replaced, or
    streaming switched off) is forgotten at the re-check, and a stream on it
    is cut as at expiry: disconnected, every copy and the recording stopped."""
    h = Harness(tmp_path, monkeypatch, offline_s=86400, grant_sync_s=3600)
    a = h.a
    a.remember(NEW_KEY, SID2, [])

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        h.started({}, status=503)
        h.answers["confirm"] = (200, {"confirmed": [SID2]})
        h.later(3600)
        await a.tick()
        await settle()
        assert a.recall(KEY, SID) is None and a.recall(NEW_KEY, SID2) is not None
        assert h.kicks == [SID] and live.revoked and h.running(live) == []
        h.answers["verify"] = (0, {})
        assert (await a.handle_auth(Auth())).status == 401
    run(go())


@pytest.mark.parametrize("answer", [(503, {}), (0, {}), (404, {"detail": "Not Found"}), (200, {}),
                                    (200, {"confirmed": SID})])
def test_a_reconfirm_that_fails_changes_nothing(tmp_path, monkeypatch, answer):
    """Kevin's call: a 5xx, a timeout, a backend without the route yet (404)
    or an answer without a `confirmed` list neither drops nor refreshes."""
    h = Harness(tmp_path, monkeypatch, offline_s=86400, grant_sync_s=3600)
    a = h.a
    t0 = h.clock["t"]

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        h.started({}, status=503)
        h.answers["confirm"] = answer
        h.later(3600)
        await a.tick()
        await settle()
        assert len(h.said("confirm")) == 2
        assert a.recall(KEY, SID) is not None and seen(tmp_path, SID) == t0
        assert not h.kicks and not live.revoked and h.running(live) == ["hls", "youtube"]
    run(go())


def test_a_reconfirm_answered_after_the_key_ran_out_doesnt_bring_it_back(tmp_path, monkeypatch):
    """Kevin's call: a re-check asked before a key ran out, and answered
    after, re-admits nothing: the key stays unusable and the stream cut at
    the deadline stays cut."""
    h = Harness(tmp_path, monkeypatch, offline_s=120, grant_sync_s=100)
    a = h.a

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        h.started({}, status=503)
        h.answers["verify"] = (0, {})
        gate = asyncio.Event()

        async def late(body):
            await gate.wait()
            return await confirm_all(body)
        h.answers["confirm"] = late
        h.later(100)
        await a.tick()                                                # the re-check is asked, unanswered
        await settle()
        assert len(h.said("confirm")) == 2
        h.later(21)
        await a.tick()                                                # 121 s: the key has run out
        await settle()
        assert live.revoked and h.running(live) == [] and h.kicks == [SID]
        gate.set()                                                    # the answer comes in now
        await settle()
        assert a.recall(KEY, SID) is None
        assert (await a.handle_auth(Auth())).status == 401
        h.later(1)
        await a.tick()
        await settle()
        assert live.revoked and h.running(live) == []
    run(go())


def test_reconfirms_go_in_chunks_of_200(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch, offline_s=86400, grant_sync_s=3600)
    a = h.a
    for i in range(450):
        a.remember(f"{i:032d}", f"{i:020x}", [])
    h.answers["confirm"] = confirm_all

    async def go():
        await a.tick()
        await settle()
        asked = h.said("confirm")
        assert [len(b["grants"]) for b in asked] == [200, 200, 50]
        assert len({g["stream_id"] for b in asked for g in b["grants"]}) == 450
    run(go())


def test_a_church_has_one_remembered_key(tmp_path, monkeypatch):
    """The re-check answers by church, so the agent remembers one key per
    church: a newly confirmed key replaces the old one, and refusing an old
    key doesn't forget the new one."""
    h = Harness(tmp_path, monkeypatch)
    a = h.a
    h.answers["verify"] = (200, {"destinations": []})
    assert run(a.may_publish(SID, KEY)) and run(a.may_publish(SID, NEW_KEY))
    h.answers["verify"] = (0, {})
    assert run(a.may_publish(SID, NEW_KEY)) and not run(a.may_publish(SID, KEY))
    h.answers["verify"] = (403, {})
    assert not run(a.may_publish(SID, KEY))
    h.answers["verify"] = (0, {})
    assert run(a.may_publish(SID, NEW_KEY))


@pytest.mark.parametrize("bad", [[None], [{"stream_id": SID}], [True], ["not-a-stream-id"], [SID2, None]],
                         ids=["null", "object", "true", "not-a-stream-id", "one-bad-member"])
def test_a_malformed_confirmed_list_changes_nothing(tmp_path, monkeypatch, bad):
    """Codex C1-F: a `confirmed` list with any member that isn't a stream id
    is a malformed answer, and a malformed answer changes nothing: no key is
    renewed, none is dropped, no stream is cut."""
    h = Harness(tmp_path, monkeypatch, offline_s=86400, grant_sync_s=3600)
    a = h.a
    t0 = h.clock["t"]
    a.remember(NEW_KEY, SID2, [])

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        h.started({}, status=503)
        h.answers["confirm"] = (200, {"confirmed": bad})
        h.later(3600)
        await a.tick()
        await settle()
        assert a.recall(KEY, SID) is not None and seen(tmp_path, SID) == t0
        assert a.recall(NEW_KEY, SID2) is not None and seen(tmp_path, SID2) == t0
        assert not live.revoked and not h.kicks and h.running(live) == ["hls", "youtube"]
    run(go())


def test_a_failed_disconnect_is_retried_while_mediamtx_cant_list_publishers(tmp_path, monkeypatch):
    """Codex R3-F1: the disconnect of a stream whose key ran out is retried
    every 10 s from the agent's own pass, on the connection it saved, until
    it takes; it doesn't wait for MediaMTX's listing to come back. Once a
    kick takes, the retries stop."""
    h = Harness(tmp_path, monkeypatch, offline_s=120)
    a = h.a

    async def unreadable():
        return None

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        h.started({}, status=503)
        h.kick_works = False
        a.publishers = unreadable
        h.later(121)
        await a.tick()
        await settle()
        for _ in range(3):
            h.later(11)
            await a.tick()
            await settle()
        assert h.kicks == [SID] * 4 and live.revoked and h.running(live) == []
        h.kick_works = True                                           # MediaMTX's kick works again
        h.later(11)
        await a.tick()
        await settle()
        for _ in range(3):
            h.later(11)
            await a.tick()
            await settle()
        assert h.kicks == [SID] * 5                                   # it took: no more tries
    run(go())


def test_a_heartbeat_answered_after_the_key_ran_out_doesnt_bring_it_back(tmp_path, monkeypatch):
    """Codex R3-F2: a heartbeat asked before the key ran out and answered
    after renews nothing. The stream stays cut and the key can't get back in
    while the backend is down; only a fresh /auth makes a new grant."""
    h = Harness(tmp_path, monkeypatch, offline_s=120, grant_sync_s=3600)
    a = h.a

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        gate = asyncio.Event()

        async def late(body):
            await gate.wait()
            return 200, STARTED
        h.answers["started"] = late
        h.kick_works = False
        h.later(115)
        await a.tick()                                                # the heartbeat is asked at 115 s
        await settle()
        h.later(6)
        await a.tick()                                                # 121 s: the key has run out
        await settle()
        assert live.revoked
        gate.set()                                                    # the 200 comes in now
        await settle()
        h.started({}, status=503)
        h.later(1)
        await a.tick()
        await settle()
        assert live.revoked and h.running(live) == []
        h.answers["verify"] = (503, {})
        assert not await a.may_publish(SID, KEY)
        assert a.recall(KEY, SID) is None
        h.answers["verify"] = (200, {"destinations": []})             # a fresh /auth does
        assert await a.may_publish(SID, KEY)
    run(go())


@pytest.mark.parametrize("disk", ["full", "unreadable"])
def test_recording_limits_hold_while_mediamtx_cant_be_read(tmp_path, monkeypatch, disk):
    """Codex R6-R: the limits don't wait on finding publishers, and a disk
    that can't be read counts as full."""
    h = Harness(tmp_path, monkeypatch, reserve=2 * 10**9)
    a = h.a

    async def unreadable():
        return None

    def broken():
        raise OSError("I/O error")

    async def go():
        h.publish()
        await a.tick()
        await settle()
        live = a.lives[SID]
        a.publishers = unreadable
        if disk == "full":
            h.free = 0
        else:
            a.free_disk = broken
        h.later(11)
        await a.tick()
        await settle()
        assert live.run.stopped == "disk" and live.hls is None and h.running(live) == ["youtube"]
    run(go())


def test_a_disk_that_cant_be_read_refuses_new_streams(tmp_path, monkeypatch):
    """Codex R6-R: a failed check of the disk refuses; it never lets in."""
    h = Harness(tmp_path, monkeypatch)
    a = h.a

    def broken():
        raise OSError("I/O error")
    a.free_disk = broken
    assert a.refusal(SID) != ""
    assert run(a.handle_auth(Auth())).status == 401 and not h.said("verify")


def test_simultaneous_new_streams_never_pass_the_limit(tmp_path, monkeypatch):
    """Codex R6-R: three churches ask at once with room for one. A church
    holds its place from the moment it is let in (before the backend has
    answered), so the other two are refused without asking the backend. A
    place nobody connects on is freed after a short hold, and a church the
    backend turns down gives its place back at once."""
    h = Harness(tmp_path, monkeypatch, max_streams=1)
    a = h.a

    async def go():
        gate = asyncio.Event()

        async def slow_verify(body):
            await gate.wait()
            return 200, {"destinations": []}
        h.answers["verify"] = slow_verify
        three = [asyncio.create_task(a.handle_auth(Auth(sid))) for sid in (SID, SID2, SID3)]
        await settle()
        gate.set()
        replies = [(await t).status for t in three]
        assert replies.count(200) == 1 and len(h.said("verify")) == 1
        assert "streams" in a.refusal(SID2)                              # held, though not listed yet
        h.later(ra.ADMIT_HOLD_S + 1)                                     # it never connected
        assert a.refusal(SID2) == ""
        h.answers["verify"] = (403, {})
        assert (await a.handle_auth(Auth(SID2))).status == 401
        h.answers["verify"] = (200, {})
        assert (await a.handle_auth(Auth(SID3))).status == 200
    run(go())


def test_the_limit_holds_for_publishers_found_and_churches_waiting_to_come_back(tmp_path, monkeypatch):
    """Codex R6-R: MediaMTX lists more publishers than the limit (let in by
    an agent that then restarted, say): only the limit is carried and the
    rest are disconnected. A church that dropped keeps its place for its
    grace, so its return can't push the relay past the limit."""
    h = Harness(tmp_path, monkeypatch, max_streams=1)
    a = h.a

    async def go():
        h.publish(SID)
        h.publish(SID2, key=NEW_KEY)                                  # each church has its own key
        await a.tick()
        await settle()
        assert list(a.lives) == [SID] and h.kicks == [SID2]
        assert h.running(a.lives[SID]) == ["hls", "youtube"]
        h.pubs.clear()
        h.later(5)
        await a.tick()
        assert not a.lives[SID].up and "streams" in a.refusal(SID2)
        assert a.refusal(SID) == ""
    run(go())


def test_a_recording_left_longer_than_the_grace_is_finished_not_resumed(tmp_path, monkeypatch):
    """Bot review on #1461: a church that streams after the agent was down
    past the grace (a droplet off for days) gets a NEW recording; the old
    one is finished, never appended to."""
    h = Harness(tmp_path, monkeypatch)
    h.answers["ended"] = (200, {})
    old = ra.Run(tmp_path, SID)
    old.session_id, old.playlist_path = SESSION, "p/index.m3u8"
    old.save()
    (old.dir / "index.m3u8").write_text("#EXTM3U\n#EXTINF:4.0,\nseg_000000.ts\n")
    then = h.clock["t"] - 601
    for f in old.dir.iterdir():
        os.utime(f, (then, then))

    async def go():
        h.a.recover()
        h.publish()
        await h.a.tick()
        await settle()
        live = h.a.lives[SID]
        assert live.run.run_id != old.run_id
        assert h.said("ended") and h.said("ended")[0]["session_id"] == SESSION
        hls = [cmd for name, _, cmd in h.copies if name == "hls"][0]
        assert "discont_start" not in hls[hls.index("-hls_flags") + 1]
    run(go())


def test_a_stopped_copy_that_ignores_the_signal_is_killed(monkeypatch):
    """Codex R11 follow-up: stopping a copy is bounded. It is asked to stop,
    then killed, so a cut stream's copies really end."""
    monkeypatch.setattr(ra, "KILL_AFTER_S", 0.01)

    class Stubborn:
        returncode = None

        def __init__(self):
            self.signals = []

        def terminate(self):
            self.signals.append("term")

        def kill(self):
            self.signals.append("kill")
            self.returncode = -9

    async def go():
        c = ra.Copy("youtube", YT["url"])
        c.proc = p = Stubborn()
        c.stop()
        await asyncio.sleep(0.05)
        assert p.signals == ["term", "kill"]
    run(go())


def test_ffmpeg_chatter_is_kept_short(tmp_path, monkeypatch):
    """Codex R6: stderr is read as it comes, and only the tail is kept."""
    cfg = ra.Config()
    cfg.work = tmp_path
    a = ra.Agent(cfg)
    c = ra.Copy("hls")
    noisy = [sys.executable, "-c", "import sys\nfor i in range(20000): sys.stderr.write('x' * 50 + '\\n')\nsys.exit(3)"]
    calls = {"n": 0}

    def make():
        calls["n"] += 1
        if calls["n"] > 1:
            c.stopped = True
        return noisy
    monkeypatch.setattr(ra, "backoff", lambda attempt, cap=30: 0)
    run(a.supervise(SID, c, make))
    assert len(c.tail) <= 5 and c.tail[-1] == "x" * 50
