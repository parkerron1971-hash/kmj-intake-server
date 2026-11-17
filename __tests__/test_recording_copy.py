"""A service recording's smaller copy, which is also its download
(recording_copy.py; Kevin, 2026-11-17: "build").

Pinned here:
  1. The switch: CHURCH_STORAGE_SMALL_COPY off | owner | on, only where
     CHURCH_STORAGE is on, and only with the write key and the clip service.
  2. Starting a copy: the oldest recording first, one at a time, never while
     a clip run waits or the clip service is busy; what the clip service is
     handed (every segment signed with the read key, the upload signed with
     the write key, a finished playlist); a busy answer puts it back.
  3. Following it: ready only once its size is read back from the bucket and
     its length matches; anything else fails the try and deletes the object;
     a try that made way for clips isn't counted; three tries at most; a
     recording deleted meanwhile is tidied; nothing twice across replicas.
  4. Day 14: the full-quality segments and playlist go, never copy.mp4, only
     with a checked copy that is still there; marked only once all are gone.
  5. The meter: full + copy, then the copy alone; a Sunday stays full size;
     unknown columns decide nothing; the page's rows and the delete agree.
  6. The download: can_download and download_url, an hour, the church's name
     and date, the read key.
  7. The player: the copy from day 14 (and after the switch goes off), under
     the same rules of who may watch; the full recording before.
  8. Signing: PUT, HEAD and the attachment GET as botocore signs them.
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from xml.sax.saxutils import escape

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import church_storage as cs  # noqa: E402
import church_storage_router as csr  # noqa: E402
import church_texts  # noqa: E402
import member_asks  # noqa: E402
import recording_copy as rc  # noqa: E402
import sample_church  # noqa: E402
import sb_clients  # noqa: E402
import stream_relay_router as sr  # noqa: E402
from auth_supabase import require_user  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
OWNER = "44444444-4444-4444-4444-444444444444"
STRANGER = "77777777-7777-4777-8777-777777777777"
R2_HOST = "acct123.r2.cloudflarestorage.com"
R2 = f"https://{R2_HOST}"
READ_KEY, WRITE_KEY = "AKREAD", "AKWRITE"
GIB = 1024 ** 3
T0 = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)      # a Sunday, as the service ends
FORBIDDEN = ("r2", "cloudflare", "bucket", "postgrest", "supabase", "ffmpeg", "github", "claude")
PLAYLIST = ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n#EXT-X-PLAYLIST-TYPE:EVENT\n"
            "#EXTINF:4.000000,\n#EXT-X-PROGRAM-DATE-TIME:2026-11-22T15:00:00.000+0000\nseg_000000.ts\n"
            "#EXT-X-DISCONTINUITY\n#EXTINF:4.000000,\nseg_000001.ts\n#EXTINF:4.000,\n../../other/secret.ts\n")


def _sid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


class _User:
    def __init__(self, uid):
        self.id = uid
        self.email = f"{uid}@test"


def _params(path):
    table, _, q = path.lstrip("/").partition("?")
    return table, urllib.parse.parse_qs(q, keep_blank_values=True)


class DB:
    """Just enough PostgREST: eq/neq/lt/gt/gte/like/in/is.null/not.is.null,
    order, limit (so sb_get_all_as_service pages for real), and a PATCH that
    answers the rows it changed (the claims read that)."""

    def __init__(self):
        self.t = {k: [] for k in ("stream_sessions", "media_clip_runs", "sermons", "chief_notifications",
                                  "academy_courses", "academy_live_sessions", "church_storage_notes")}
        self.t["businesses"] = [
            {"id": BIZ, "owner_id": OWNER, "name": "Grace Church", "settings": {}, "comp_tier": "church_small",
             "subscription_plan": None, "subscription_status": "active"},
            {"id": OTHER, "owner_id": STRANGER, "name": "Iglesia Fé", "settings": {}, "comp_tier": "church_small",
             "subscription_plan": None, "subscription_status": "active"}]
        self.t["business_users"] = []
        self.fail = set()
        self.gets, self.patches = [], []

    def _match(self, row, q):
        for k, vals in q.items():
            if k in ("select", "order", "limit", "on_conflict"):
                continue
            v = vals[0]
            cell = row.get(k)
            if v == "is.null":
                ok = cell is None
            elif v == "not.is.null":
                ok = cell is not None
            elif v.startswith("eq."):
                ok = str(cell).lower() == v[3:].lower()
            elif v.startswith("neq."):
                ok = str(cell).lower() != v[4:].lower()
            elif v.startswith("lt."):
                ok = cell is not None and _cmp(cell, v[3:]) < 0
            elif v.startswith("gt."):
                ok = cell is not None and _cmp(cell, v[3:]) > 0
            elif v.startswith("gte."):
                ok = cell is not None and _cmp(cell, v[4:]) >= 0
            elif v.startswith("like."):
                ok = fnmatch(str(cell or ""), v[5:])
            elif v.startswith("in.("):
                ok = str(cell).lower() in v[4:-1].lower().split(",")
            else:
                raise AssertionError(f"filter not faked: {k}={v}")
            if not ok:
                return False
        return True

    def get(self, path, redact=False):
        self.gets.append(path)
        table, q = _params(path)
        if table in self.fail:
            return None
        rows = [dict(r) for r in self.t.get(table, []) if self._match(r, q)]
        if "order" in q:
            col, _, way = q["order"][0].partition(".")
            rows.sort(key=lambda r: str(r.get(col)), reverse=(way == "desc"))
        return rows[: int(q.get("limit", ["100000"])[0])]

    def post(self, path, body, prefer="return=representation", redact=False):
        if path.startswith("/rpc/"):
            return 0
        table, _ = _params(path)
        self.t.setdefault(table, []).append(dict(body))
        return [dict(body)]

    def patch(self, path, body):
        table, q = _params(path)
        self.patches.append((path, body))
        if table in self.fail:
            return None
        hit = [r for r in self.t.get(table, []) if self._match(r, q)]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]

    def session(self, n, *, biz=BIZ, size=6 * GIB, duration=7200, ended=None, **kw):
        sid = _sid(n)
        end = ended or (T0 - timedelta(days=40 - n))
        row = {"id": sid, "business_id": biz, "status": "ended", "bytes": size, "duration_s": duration,
               "started_at": (end - timedelta(seconds=duration)).isoformat(), "ended_at": end.isoformat(),
               "sermon_id": None, "playlist_path": sr.playlist_path(biz, sid), "removed_at": None,
               "keep_until": None, "warnings_sent": 0, "last_warned_at": None, "live_session_id": None,
               "copy_state": None, "copy_job": None, "copy_tries": 0, "copy_at": None, "copy_bytes": None,
               "copy_seconds": None, "copy_made_at": None, "copy_error": None, "full_removed_at": None, **kw}
        self.t["stream_sessions"].append(row)
        return row

    def one(self, sid):
        return next(r for r in self.t["stream_sessions"] if r["id"] == sid)


def _cmp(cell, value):
    a, b = str(cell), urllib.parse.unquote(value)
    try:
        return (float(a) > float(b)) - (float(a) < float(b))
    except ValueError:
        pass
    ta, tb = rc._at(a), rc._at(b)
    if ta and tb:
        return (ta > tb) - (ta < tb)
    return (a > b) - (a < b)


class _Resp:
    def __init__(self, status, text="", headers=None, body=None):
        self.status_code, self.text, self.headers, self._body = status, text, headers or {}, body

    def json(self):
        return self._body if self._body is not None else json.loads(self.text)


class Bucket:
    """The media bucket: LIST and DELETE signed with the write key, HEAD with
    the read key."""

    def __init__(self):
        self.objects = {}
        self.calls = []
        self.fail_delete, self.fail_list, self.fail_head = set(), False, False

    def add_recording(self, biz, sid, n=3, size=100):
        for i in range(n):
            self.objects[f"live/{biz}/{sid}/seg_{i:06d}.ts"] = size
        self.objects[f"live/{biz}/{sid}/index.m3u8"] = 10

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, url):
        p = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(p.query)
        assert p.scheme == "https" and p.netloc == R2_HOST
        cred = q["X-Amz-Credential"][0]
        self.calls.append((method, urllib.parse.unquote(p.path)))
        key = urllib.parse.unquote(p.path[len("/media/"):])
        if method == "HEAD":
            assert cred.startswith(READ_KEY + "/"), "a size is read with the read key"
            if self.fail_head:
                return _Resp(500)
            return _Resp(200, headers={"content-length": str(self.objects[key])}) if key in self.objects else _Resp(404)
        assert cred.startswith(WRITE_KEY + "/"), "a list or delete is signed with the write key"
        if method == "GET":
            assert p.path == "/media" and q["list-type"] == ["2"]
            if self.fail_list:
                return _Resp(500)
            prefix = q["prefix"][0]
            body = "".join(f"<Contents><Key>{escape(k)}</Key><Size>{v}</Size></Contents>"
                           for k, v in sorted(self.objects.items()) if k.startswith(prefix))
            return _Resp(200, '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                              f"<IsTruncated>false</IsTruncated>{body}</ListBucketResult>")
        assert method == "DELETE"
        if key in self.fail_delete:
            return _Resp(500)
        self.objects.pop(key, None)
        return _Resp(204)


class Clipper:
    """The clip service as recording_copy sees it."""

    def __init__(self, bucket):
        self.bucket = bucket
        self.jobs = {}
        self.posts = []
        self.busy, self.copies, self.answer = False, True, 202
        self.deleted = []
        self.calls = []

    def __call__(self, method, path, **kw):
        self.calls.append((method, path))
        if path == "/health":
            return _Resp(200, body={"ok": True, "busy": self.busy or any(
                j["status"] == "working" for j in self.jobs.values()), "copies": self.copies})
        job = path.rsplit("/", 1)[-1]
        if method == "POST":
            self.posts.append(kw["json"])
            if self.answer == 202:
                self.jobs[job] = {"status": "working", "stage": "making", "percent": 0.0, "error": None,
                                  "upload": kw["json"]["upload_url"]}
            return _Resp(self.answer, body={})
        if method == "DELETE":
            self.deleted.append(job)
            self.jobs.pop(job, None)
            return _Resp(200, body={"deleted": True})
        if job not in self.jobs:
            return _Resp(404, body={"detail": "Job not found"})
        return _Resp(200, body=self.jobs[job])

    def finish(self, job, *, size=1_400_000_000, seconds=7199.9, store=True):
        """The job uploads and completes (the object lands where the PUT points)."""
        up = urllib.parse.urlparse(self.jobs[job]["upload"])
        if store:
            self.bucket.objects[urllib.parse.unquote(up.path[len("/media/"):])] = size
        self.jobs[job] = {"status": "completed", "stage": "done", "percent": 100.0, "error": None,
                          "result": {"seconds": seconds, "bytes": size, "width": 1280, "height": 720,
                                     "audio": True, "md5": "x"}}

    def end(self, job, status, code, message="It stopped."):
        self.jobs[job] = {"status": status, "stage": "making", "percent": 40.0,
                          "error": {"message": message, "stage": "making", "code": code}}


@pytest.fixture
def world(monkeypatch):
    d = DB()
    bucket = Bucket()
    clip = Clipper(bucket)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
    monkeypatch.setattr(sample_church, "drop_samples", lambda rows, key="business_id": list(rows))
    monkeypatch.setattr(church_texts, "_church_rows", lambda: [dict(b) for b in d.t["businesses"]])
    monkeypatch.setattr(cs, "_client", lambda: bucket)
    monkeypatch.setattr(rc, "_clipper", clip)
    monkeypatch.setattr(sr, "_playlist_text", lambda s: PLAYLIST)
    monkeypatch.setattr(rc, "_COLUMNS", {"there": True, "at": 0.0})
    for k, v in {"STREAM_RELAY_SECRET": "relay-secret", "STREAM_DEST_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                 "STREAM_INGEST_URL": "rtmps://stream.example.app:443/live", "STREAM_R2_ENDPOINT": R2,
                 "STREAM_R2_BUCKET": "media", "STREAM_R2_ACCESS_KEY_ID": READ_KEY,
                 "STREAM_R2_SECRET_ACCESS_KEY": "read-secret", "STREAM_R2_WRITE_ACCESS_KEY_ID": WRITE_KEY,
                 "STREAM_R2_WRITE_SECRET_ACCESS_KEY": "write-secret", "CLIPPER_URL": "https://clipper.test",
                 "CLIPPER_TOKEN": "t" * 40, "CHURCH_STORAGE": "on", "CHURCH_STORAGE_SMALL_COPY": "on",
                 "LIMIT_CHURCH_SMALL_STORAGE_GB": "100"}.items():
        monkeypatch.setenv(k, v)
    sr._cache.clear()
    return d, bucket, clip


def _tick(at=T0):
    return rc.copy_tick(now=at)


def _start_one(world, n=1, **kw):
    d, bucket, clip = world
    s = d.session(n, **kw)
    bucket.add_recording(s["business_id"], s["id"])
    assert _tick()["started"] == 1
    return d.one(s["id"])


# ─── 1. The switch ───────────────────────────────────────────────────

def test_off_does_nothing_at_all(world, monkeypatch):
    d, bucket, clip = world
    monkeypatch.delenv("CHURCH_STORAGE_SMALL_COPY")
    d.session(1)
    assert rc.mode() == "off" and not rc.switched_on(BIZ) and not rc.downloads_on(BIZ)
    assert _tick() == {k: 0 for k in _tick()}
    assert d.gets == [] and clip.calls == []


def test_it_needs_the_storage_allowance_on_too(world, monkeypatch):
    monkeypatch.setenv("CHURCH_STORAGE", "off")
    assert not rc.switched_on(BIZ)
    monkeypatch.setenv("CHURCH_STORAGE", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: str(b) == BIZ)
    assert rc.switched_on(BIZ) and not rc.switched_on(OTHER)


def test_owner_is_the_platform_owners_churches_only(world, monkeypatch):
    d, bucket, clip = world
    monkeypatch.setenv("CHURCH_STORAGE_SMALL_COPY", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: str(b) == BIZ)
    theirs = d.session(1, biz=OTHER)            # older, but not switched on
    mine = d.session(2)
    bucket.add_recording(BIZ, mine["id"])
    assert _tick()["started"] == 1
    assert d.one(mine["id"])["copy_state"] == "working" and d.one(theirs["id"])["copy_state"] is None


@pytest.mark.parametrize("missing", ["STREAM_R2_WRITE_SECRET_ACCESS_KEY", "CLIPPER_URL", "STREAM_RELAY_SECRET"])
def test_nothing_without_the_write_key_or_the_clip_service(world, monkeypatch, missing, capsys):
    d, bucket, clip = world
    monkeypatch.delenv(missing)
    d.session(1)
    rc._SAID.clear()
    assert _tick()["started"] == 0 and clip.calls == []
    assert "isn't set" in capsys.readouterr().out


def test_nothing_before_the_migration(world, monkeypatch, capsys):
    d, bucket, clip = world
    monkeypatch.setattr(rc, "_COLUMNS", {"there": False, "at": 1e18})
    rc._SAID.clear()
    d.session(1)
    assert _tick()["errors"] == 1 and clip.calls == []
    assert "isn't applied" in capsys.readouterr().out


# ─── 2. Starting a copy ──────────────────────────────────────────────

def test_the_oldest_recording_goes_first_and_the_clip_service_gets_signed_links(world):
    d, bucket, clip = world
    newer, older = d.session(5), d.session(2)
    s = _start_one(world, n=1, duration=5400)                         # the oldest of all
    assert s["copy_state"] == "working" and s["copy_tries"] == 1 and s["copy_job"]
    assert d.one(newer["id"])["copy_state"] is None and d.one(older["id"])["copy_state"] is None
    [body] = clip.posts
    assert ("POST", f"/copies/{s['copy_job']}") in clip.calls
    assert body["seconds"] == 5400.0
    segs = [ln for ln in body["playlist"].splitlines() if ln and not ln.startswith("#")]
    assert len(segs) == 2 and "secret.ts" not in body["playlist"]
    for ln in segs:
        u = urllib.parse.urlparse(ln)
        q = urllib.parse.parse_qs(u.query)
        assert u.scheme == "https" and u.netloc == R2_HOST
        assert u.path.startswith(f"/media/live/{BIZ}/{s['id']}/seg_00000")
        assert q["X-Amz-Credential"][0].startswith(READ_KEY + "/") and q["X-Amz-Expires"] == [str(rc.JOB_LINK_S)]
    assert body["playlist"].rstrip().endswith("#EXT-X-ENDLIST")       # read as a finished video
    assert "#EXT-X-DISCONTINUITY" in body["playlist"]
    up = urllib.parse.urlparse(body["upload_url"])
    uq = urllib.parse.parse_qs(up.query)
    assert up.netloc == R2_HOST and up.path == f"/media/live/{BIZ}/{s['id']}/copy.mp4"
    assert uq["X-Amz-Credential"][0].startswith(WRITE_KEY + "/") and uq["X-Amz-Expires"] == [str(rc.JOB_LINK_S)]
    assert len(clip.posts) == 1                                       # one at a time


def test_one_copy_at_a_time(world):
    d, bucket, clip = world
    _start_one(world, n=1)
    d.session(2)
    assert _tick()["working"] == 1 and len(clip.posts) == 1


@pytest.mark.parametrize("status", ["queued", "working"])
def test_never_started_while_a_clip_run_waits(world, status):
    d, bucket, clip = world
    d.t["media_clip_runs"].append({"id": "r1", "status": status, "created_at": (T0 - timedelta(minutes=5)).isoformat()})
    d.session(1)
    assert _tick()["started"] == 0 and clip.posts == []
    # A run left queued hours ago (clips switched off) doesn't hold copies back for good.
    d.t["media_clip_runs"][0]["created_at"] = (T0 - timedelta(hours=3)).isoformat()
    assert _tick()["started"] == 1


def test_never_started_on_a_guess(world):
    d, bucket, clip = world
    d.session(1)
    d.fail.add("media_clip_runs")
    assert _tick()["started"] == 0 and clip.posts == []


def test_never_started_while_the_clip_service_is_busy_or_not_ready_for_copies(world, capsys):
    d, bucket, clip = world
    s = d.session(1)
    clip.busy = True
    assert _tick()["started"] == 0
    clip.busy, clip.copies = False, False
    rc._SAID.clear()
    assert _tick()["started"] == 0 and clip.posts == []
    assert "CLIPPER_COPY_HOSTS" in capsys.readouterr().out
    assert d.one(s["id"])["copy_state"] is None and d.one(s["id"])["copy_tries"] == 0


@pytest.mark.parametrize("answer", [409, 503])
def test_a_busy_answer_puts_it_back_uncounted(world, answer):
    d, bucket, clip = world
    s = d.session(1)
    clip.answer = answer
    assert _tick()["started"] == 0
    row = d.one(s["id"])
    assert row["copy_state"] is None and row["copy_tries"] == 0


def test_a_refusal_fails_the_try(world):
    d, bucket, clip = world
    s = d.session(1)
    t = d.session(2)
    clip.answer = 422
    _tick()
    assert d.one(s["id"])["copy_state"] == "failed" and d.one(s["id"])["copy_tries"] == 1
    assert d.one(t["id"])["copy_state"] == "failed"                   # the next one was tried too


def test_only_ended_recordings_in_their_own_folder(world):
    d, bucket, clip = world
    d.session(1, status="live")
    d.session(2, removed_at=T0.isoformat())
    d.session(3, playlist_path=f"live/{BIZ}/index.m3u8")
    d.session(4, bytes=0)
    d.session(5, duration=7 * 3600)                                   # past the clip service's limit
    assert rc.candidates(T0) == [] and _tick()["started"] == 0


def test_the_copys_folder_is_the_recordings_folder_by_the_deletes_own_rule(world):
    sid = _sid(1)
    for s in ({"id": sid, "playlist_path": sr.playlist_path(BIZ, sid)}, {"id": sid, "playlist_path": ""},
              {"id": sid, "playlist_path": f"live/{BIZ}/index.m3u8"}, {"id": "../x"},
              {"id": sid.upper(), "playlist_path": None}):
        assert rc.folder(BIZ, s) == cs.recording_prefix(BIZ, s)
    assert rc.copy_key(BIZ, {"id": sid}) == f"live/{BIZ}/{sid}/copy.mp4"
    assert rc.folder("not-a-church", {"id": sid}) is None


def test_a_missing_playlist_fails_and_a_failed_read_waits(world, monkeypatch):
    d, bucket, clip = world
    s = d.session(1)
    from fastapi import HTTPException

    def boom(_s):
        raise HTTPException(503, "Couldn't load just now.")
    monkeypatch.setattr(sr, "_playlist_text", boom)
    _tick()
    assert d.one(s["id"])["copy_state"] is None and d.one(s["id"])["copy_tries"] == 0
    monkeypatch.setattr(sr, "_playlist_text", lambda _s: None)
    _tick()
    assert d.one(s["id"])["copy_state"] == "failed" and clip.posts == []


def test_two_replicas_never_claim_the_same_try(world):
    d, bucket, clip = world
    s = d.session(1)
    stale = dict(s)
    assert rc._claim(stale, T0) is not None
    assert rc._claim(stale, T0) is None                               # the copy it read is out of date


# ─── 3. Following it ─────────────────────────────────────────────────

def test_ready_only_once_its_size_is_read_back_and_its_length_matches(world, capsys):
    d, bucket, clip = world
    s = _start_one(world)
    assert _tick(T0 + timedelta(minutes=2))["working"] == 1
    clip.finish(s["copy_job"])
    got = _tick(T0 + timedelta(minutes=30))
    assert got["made"] == 1
    row = d.one(s["id"])
    assert row["copy_state"] == "ready" and row["copy_bytes"] == 1_400_000_000 and row["copy_seconds"] == 7199.9
    assert row["copy_made_at"] == (T0 + timedelta(minutes=30)).isoformat() and row["copy_error"] is None
    assert s["copy_job"] in clip.deleted                              # forgotten by the clip service
    assert ("HEAD", f"/media/live/{BIZ}/{s['id']}/copy.mp4") in bucket.calls
    assert "ready: 1400000000 bytes" in capsys.readouterr().out


@pytest.mark.parametrize("how,why", [
    ({"store": False}, "wasn't in storage"),
    ({"size": 1000, "store": True}, None),                            # stored at another size below
    ({"seconds": 6500}, "runs 6500 s"),
])
def test_a_copy_that_doesnt_match_fails_and_is_deleted(world, how, why):
    d, bucket, clip = world
    s = _start_one(world)
    clip.finish(s["copy_job"], **how)
    key = f"live/{BIZ}/{s['id']}/copy.mp4"
    if why is None:
        bucket.objects[key] = 999                                     # not what was made
        why = "isn't the size that was made"
    assert _tick(T0 + timedelta(minutes=30))["failed"] == 1
    row = d.one(s["id"])
    assert row["copy_state"] == "failed" and why in row["copy_error"] and row["copy_bytes"] is None
    assert key not in bucket.objects


def test_a_short_recording_has_ten_seconds_of_slack():
    assert rc.length_ok(35, 30) and not rc.length_ok(41, 30)
    assert rc.length_ok(7200 * 1.019, 7200) and not rc.length_ok(7200 * 0.97, 7200)
    assert not rc.length_ok(0, 7200) and not rc.length_ok(7200, 0)


def test_a_failed_try_is_tried_again_an_hour_later_three_times_in_all(world):
    d, bucket, clip = world
    s = d.session(1)
    bucket.add_recording(BIZ, s["id"])
    at = T0
    for n in range(1, rc.MAX_TRIES + 1):
        assert _tick(at)["started"] == 1, n
        clip.end(d.one(s["id"])["copy_job"], "failed", "copy.segment", "Part of the recording could not be read.")
        assert _tick(at + timedelta(minutes=2))["failed"] == 1
        assert _tick(at + timedelta(minutes=30))["started"] == 0       # not before the hour
        at += timedelta(hours=1, minutes=5)
    row = d.one(s["id"])
    assert row["copy_state"] == "failed" and row["copy_tries"] == rc.MAX_TRIES
    assert "could not be read" in row["copy_error"]
    assert _tick(at + timedelta(days=1))["started"] == 0              # no more tries
    assert row["full_removed_at"] is None                             # the full recording stays


def test_a_copy_that_made_way_for_clips_is_not_counted(world):
    d, bucket, clip = world
    s = _start_one(world)
    first = s["copy_job"]
    clip.end(first, "cancelled", "job.yielded")
    d.t["media_clip_runs"].append({"id": "r1", "status": "working", "created_at": T0.isoformat()})
    got = _tick(T0 + timedelta(minutes=2))
    assert got["waiting"] == 1 and got["started"] == 0                # clips are still going
    row = d.one(s["id"])
    assert row["copy_state"] is None and row["copy_tries"] == 0
    d.t["media_clip_runs"].clear()
    assert _tick(T0 + timedelta(minutes=4))["started"] == 1           # made again, from the start
    assert d.one(s["id"])["copy_job"] != first and d.one(s["id"])["copy_tries"] == 1
    assert first in clip.deleted                                      # the yielded job was forgotten


def test_a_lost_job_fails_the_try(world):
    d, bucket, clip = world
    s = _start_one(world)
    clip.jobs.clear()                                                 # the clip service restarted
    assert _tick(T0 + timedelta(minutes=2))["failed"] == 1
    assert d.one(s["id"])["copy_error"] == "the clip service lost it"


def test_a_copy_stuck_for_hours_is_given_up(world):
    d, bucket, clip = world
    s = _start_one(world)
    assert _tick(T0 + timedelta(hours=3))["working"] == 1
    assert _tick(T0 + timedelta(hours=5))["failed"] == 1
    assert s["copy_job"] in clip.deleted


def test_a_clip_service_that_doesnt_answer_is_waited_for(world, monkeypatch):
    d, bucket, clip = world
    s = _start_one(world)

    def down(method, path, **kw):
        raise OSError("down")
    monkeypatch.setattr(rc, "_clipper", down)
    assert _tick(T0 + timedelta(minutes=2))["working"] == 1
    assert d.one(s["id"])["copy_state"] == "working"


def test_a_recording_deleted_while_its_copy_is_made_is_tidied(world):
    d, bucket, clip = world
    s = _start_one(world)
    # The church deletes it; the clip service's upload lands afterwards.
    assert cs.remove_recording(BIZ, d.one(s["id"]), now=T0) is not None
    clip.finish(s["copy_job"])
    assert f"live/{BIZ}/{s['id']}/copy.mp4" in bucket.objects
    assert _tick(T0 + timedelta(minutes=2))["tidied"] == 1
    assert not any(k.startswith(f"live/{BIZ}/{s['id']}/") for k in bucket.objects)
    row = d.one(s["id"])
    assert row["copy_state"] == "failed" and row["copy_bytes"] is None and row["removed_at"]


def test_a_recording_deleted_while_working_stops_the_job(world):
    d, bucket, clip = world
    s = _start_one(world)
    cs.remove_recording(BIZ, d.one(s["id"]), now=T0)
    assert _tick(T0 + timedelta(minutes=2))["working"] == 1 and s["copy_job"] in clip.deleted
    assert _tick(T0 + timedelta(minutes=4))["tidied"] == 1


def test_a_finished_copy_whose_size_cant_be_read_waits(world):
    d, bucket, clip = world
    s = _start_one(world)
    clip.finish(s["copy_job"])
    bucket.fail_head = True
    assert _tick(T0 + timedelta(minutes=2))["working"] == 1
    assert d.one(s["id"])["copy_state"] == "working"
    bucket.fail_head = False
    assert _tick(T0 + timedelta(minutes=4))["made"] == 1


# ─── 4. Day 14 ───────────────────────────────────────────────────────

def _ready(d, bucket, n=1, *, ended, size=1_400_000_000, **kw):
    s = d.session(n, ended=ended, copy_state="ready", copy_bytes=size, copy_seconds=7199.9,
                  copy_made_at=ended.isoformat(), **kw)
    bucket.add_recording(s["business_id"], s["id"], n=4, size=GIB)
    bucket.objects[f"live/{s['business_id']}/{s['id']}/copy.mp4"] = size
    return s


def test_day_14_takes_the_full_recording_and_keeps_the_copy(world, capsys):
    d, bucket, clip = world
    s = _ready(d, bucket, ended=T0 - timedelta(days=14, minutes=1))
    folder = f"live/{BIZ}/{s['id']}/"
    bucket.objects[folder + "seg_000099.ts.tmp"] = 5                  # not the recording's: left
    bucket.objects[folder + "sub/seg_000001.ts"] = 5                  # deeper: left
    assert _tick()["trimmed"] == 1
    assert sorted(k for k in bucket.objects if k.startswith(folder)) == [
        folder + "copy.mp4", folder + "seg_000099.ts.tmp", folder + "sub/seg_000001.ts"]
    row = d.one(s["id"])
    assert row["full_removed_at"] == T0.isoformat() and row["copy_state"] == "ready"
    assert "full-quality recording removed after 14 days" in capsys.readouterr().out


def test_not_before_14_days(world):
    d, bucket, clip = world
    _ready(d, bucket, ended=T0 - timedelta(days=13, hours=23))
    assert _tick()["trimmed"] == 0 and not any(c[0] == "DELETE" for c in bucket.calls)


def test_a_copy_gone_from_storage_keeps_the_full_recording_and_is_made_again(world):
    d, bucket, clip = world
    s = _ready(d, bucket, ended=T0 - timedelta(days=20))
    bucket.objects.pop(f"live/{BIZ}/{s['id']}/copy.mp4")
    assert _tick()["trimmed"] == 0
    row = d.one(s["id"])
    assert row["full_removed_at"] is None and row["copy_state"] == "failed" and row["copy_bytes"] is None
    assert sum(k.endswith(".ts") for k in bucket.objects) == 4
    assert _tick(T0 + timedelta(hours=2))["started"] == 1             # made again


@pytest.mark.parametrize("fault", ["head", "list", "delete"])
def test_a_failure_on_day_14_marks_nothing(world, fault):
    d, bucket, clip = world
    s = _ready(d, bucket, ended=T0 - timedelta(days=15))
    if fault == "head":
        bucket.fail_head = True
    elif fault == "list":
        bucket.fail_list = True
    else:
        bucket.fail_delete.add(f"live/{BIZ}/{s['id']}/seg_000002.ts")
    assert _tick()["trimmed"] == 0
    assert d.one(s["id"])["full_removed_at"] is None and d.one(s["id"])["copy_state"] == "ready"
    bucket.fail_head, bucket.fail_list = False, False
    bucket.fail_delete.clear()
    assert _tick(T0 + timedelta(minutes=2))["trimmed"] == 1           # the next tick finishes


def test_a_copy_not_checked_is_never_trimmed_on(world):
    d, bucket, clip = world
    s = _ready(d, bucket, ended=T0 - timedelta(days=20))
    d.one(s["id"])["copy_seconds"] = 3000                              # not the recording's length
    assert _tick()["trimmed"] == 0 and d.one(s["id"])["full_removed_at"] is None


def test_day_14_only_where_it_is_switched_on(world, monkeypatch):
    d, bucket, clip = world
    monkeypatch.setenv("CHURCH_STORAGE_SMALL_COPY", "owner")
    monkeypatch.setattr(member_asks, "platform_church", lambda b: False)
    _ready(d, bucket, ended=T0 - timedelta(days=20))
    assert _tick()["trimmed"] == 0


# ─── 5. The meter ────────────────────────────────────────────────────

def test_the_meter_counts_the_copy_beside_the_full_recording_then_alone(world):
    d, bucket, clip = world
    d.session(1, size=6 * GIB)                                                     # no copy yet
    d.session(2, size=6 * GIB, copy_state="ready", copy_bytes=GIB)                 # both, for now
    d.session(3, size=6 * GIB, copy_state="ready", copy_bytes=GIB,
              full_removed_at=T0.isoformat())                                      # the copy alone
    d.session(4, size=6 * GIB, copy_state="working")                               # not counted twice
    m = cs.used(BIZ)
    assert m["parts"]["recordings"] == 6 * GIB + 7 * GIB + GIB + 6 * GIB
    assert m["bytes_per_sunday"] == 6 * GIB                                        # a Sunday is still full size


def test_unknown_columns_decide_nothing(world, monkeypatch):
    d, bucket, clip = world
    d.session(1, size=6 * GIB, copy_state="ready", copy_bytes=GIB, full_removed_at=T0.isoformat())
    monkeypatch.setattr(rc, "_COLUMNS", {"there": None, "at": 0.0})
    d.fail.add("stream_sessions")                     # the probe fails, and not for a missing column
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"status": 503, "code": "", "message": ""})
    assert rc.copy_columns() is None and cs.session_cols() is None and cs.used(BIZ) is None
    # Before the migration: no copy columns, and the meter reads as it always did.
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"status": 400, "code": "42703", "message": "x"})
    assert rc.copy_columns() is False and cs.session_cols() == cs.SESSION_COLS
    d.fail.clear()
    monkeypatch.setattr(rc, "_COLUMNS", {"there": None, "at": 0.0})
    assert rc.copy_columns() is True and cs.session_cols().endswith(cs.COPY_COLS)


def test_the_page_rows_and_the_delete_say_what_a_recording_keeps(world):
    d, bucket, clip = world
    s = _ready(d, bucket, ended=T0 - timedelta(days=3), size=GIB)
    app = FastAPI()
    app.include_router(csr.router)
    app.dependency_overrides[require_user] = lambda: _User(OWNER)
    c = TestClient(app)
    got = c.get(f"/church/storage?business_id={BIZ}").json()
    assert got["recordings"][0]["bytes"] == 7 * GIB                   # 6 GB full + its 1 GB copy
    r = c.delete(f"/church/storage/recordings/{s['id']}?business_id={BIZ}")
    assert r.json() == {"removed": True, "freed_bytes": 7 * GIB}
    assert not any(k.startswith(f"live/{BIZ}/{s['id']}/") for k in bucket.objects)   # the copy went too


# ─── 6. The download ─────────────────────────────────────────────────

def _page(uid=OWNER):
    app = FastAPI()
    app.include_router(csr.router)
    app.dependency_overrides[require_user] = lambda: _User(uid)
    return TestClient(app)


def test_every_ready_copy_gets_a_download_link_for_an_hour(world):
    d, bucket, clip = world
    s = _ready(d, bucket, ended=datetime(2026, 11, 23, 2, 30, tzinfo=timezone.utc), duration=7200)
    d.session(2)                                                      # no copy yet
    got = _page().get(f"/church/storage?business_id={BIZ}").json()
    assert got["can_download"] is True
    by = {r["session_id"]: r for r in got["recordings"]}
    assert by[_sid(2)]["download_url"] is None
    url = by[s["id"]]["download_url"]
    u = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(u.query)
    assert u.scheme == "https" and u.netloc == R2_HOST and u.path == f"/media/live/{BIZ}/{s['id']}/copy.mp4"
    assert q["X-Amz-Credential"][0].startswith(READ_KEY + "/") and q["X-Amz-Expires"] == ["3600"]
    # Started 00:30 UTC on the 23rd: on the church's clock (UTC here) that is the 23rd.
    assert q["response-content-disposition"] == ['attachment; filename="Grace Church 2026-11-23.mp4"']
    assert q["response-content-type"] == ["video/mp4"]


def test_the_date_is_the_churchs_own(world, monkeypatch):
    from zoneinfo import ZoneInfo
    import business_marketing
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: ZoneInfo("America/Chicago"))
    name, tz = rc.church_label(BIZ)
    assert name == "Grace Church"
    assert rc.disposition(name, "2026-11-23T00:30:00+00:00", tz) == 'attachment; filename="Grace Church 2026-11-22.mp4"'


def test_a_name_with_other_letters_or_unsafe_marks():
    assert rc.disposition("Iglesia Fé", "2026-11-22T15:00:00+00:00", timezone.utc) == (
        "attachment; filename=\"Iglesia Fe 2026-11-22.mp4\"; filename*=UTF-8''Iglesia%20F%C3%A9%202026-11-22.mp4")
    got = rc.disposition('St. "Mark\'s"/Church; 100%\r\n', "2026-11-22T15:00:00+00:00", timezone.utc)
    assert got == 'attachment; filename="St. Mark\'s Church 100 2026-11-22.mp4"'
    assert rc.disposition("", None, timezone.utc).startswith('attachment; filename="Service recording ')
    assert rc.disposition("教会", "2026-11-22T15:00:00+00:00", timezone.utc).startswith(
        'attachment; filename="Service recording 2026-11-22.mp4"; filename*=UTF-8\'\'%E6%95%99')


def test_no_downloads_while_switched_off(world, monkeypatch):
    d, bucket, clip = world
    _ready(d, bucket, ended=T0 - timedelta(days=3))
    monkeypatch.setenv("CHURCH_STORAGE_SMALL_COPY", "off")
    got = _page().get(f"/church/storage?business_id={BIZ}").json()
    assert got["can_download"] is False and got["recordings"][0]["download_url"] is None


def test_the_church_name_is_read_once_and_only_when_a_link_is_offered(world):
    d, bucket, clip = world
    for n in range(1, 4):
        _ready(d, bucket, n, ended=T0 - timedelta(days=n))
    _page().get(f"/church/storage?business_id={BIZ}")
    assert sum(g.startswith("/businesses?id=eq.") and "name" in g for g in d.gets) == 1
    d.gets.clear()
    d.t["stream_sessions"] = []
    d.session(9)
    _page().get(f"/church/storage?business_id={BIZ}")
    assert not any("name" in g and g.startswith("/businesses?") for g in d.gets)


# ─── 7. The player ───────────────────────────────────────────────────

def _player():
    app = FastAPI()
    app.include_router(sr.router)
    return TestClient(app)


def _published(d, s):
    d.t["sermons"].append({"id": "p1", "business_id": BIZ, "published": True, "video_url": sr.watch_url(s["id"])})


def _plays(page):
    """('file', link) for the copy, ('hls', src) for the full recording."""
    import re
    m = re.search(r'data-kind="file" data-src="([^"]+)"', page.text)
    if m:
        return "file", m.group(1).replace("&amp;", "&")
    m = re.search(r'data-src="([^"]+)"', page.text)
    return ("hls", m.group(1).replace("&amp;", "&")) if m else (None, None)


def test_the_watch_page_plays_the_copy_once_the_full_recording_is_gone(world):
    d, bucket, clip = world
    s = _ready(d, bucket, ended=T0 - timedelta(days=20), full_removed_at=T0.isoformat())
    _published(d, s)
    page = _player().get(f"/stream-relay/watch/{s['id']}")
    kind, link = _plays(page)
    assert page.status_code == 200 and kind == "file"
    u = urllib.parse.urlparse(link)
    q = urllib.parse.parse_qs(u.query)
    assert u.netloc == R2_HOST and u.path == f"/media/live/{BIZ}/{s['id']}/copy.mp4"
    assert q["X-Amz-Credential"][0].startswith(READ_KEY + "/") and q["X-Amz-Expires"] == [str(rc.PLAY_LINK_S)]
    assert "hls.min.js" not in page.text                              # no player library for a file
    csp = page.headers["content-security-policy"]
    nonce = csp.split("'nonce-", 1)[1].split("'", 1)[0]
    assert f'<script nonce="{nonce}">' in page.text and R2 in csp.split("media-src", 1)[1].split(";")[0]
    assert "default-src 'none'" in csp and page.headers["cache-control"] == "no-store"


def test_from_day_14_the_ready_copy_plays_before_and_the_full_recording(world):
    d, bucket, clip = world
    old = _ready(d, bucket, 1, ended=datetime.now(timezone.utc) - timedelta(days=15))
    new = _ready(d, bucket, 2, ended=datetime.now(timezone.utc) - timedelta(days=2))
    none = d.session(3, ended=datetime.now(timezone.utc) - timedelta(days=30))
    for s in (old, new, none):
        _published(d, s)
    c = _player()
    assert _plays(c.get(f"/stream-relay/watch/{old['id']}"))[0] == "file"
    assert _plays(c.get(f"/stream-relay/watch/{new['id']}")) == ("hls", f"/stream-relay/media/{new['id']}/index.m3u8")
    assert _plays(c.get(f"/stream-relay/watch/{none['id']}"))[0] == "hls"


def test_who_may_watch_the_copy_is_unchanged(world):
    d, bucket, clip = world
    s = _ready(d, bucket, ended=T0 - timedelta(days=20), full_removed_at=T0.isoformat())
    c = _player()
    assert c.get(f"/stream-relay/watch/{s['id']}").status_code == 404     # a draft, no manager's link
    page = c.get(f"/stream-relay/watch/{s['id']}?t={sr.staff_token(s['id'])}")
    assert page.status_code == 200 and _plays(page)[0] == "file"
    assert c.get(f"/stream-relay/watch/{s['id']}?t=1.{'0' * 64}").status_code == 404


def test_the_copy_still_plays_after_the_switch_goes_off(world, monkeypatch):
    d, bucket, clip = world
    s = _ready(d, bucket, ended=T0 - timedelta(days=20), full_removed_at=T0.isoformat())
    _published(d, s)
    monkeypatch.setenv("CHURCH_STORAGE_SMALL_COPY", "off")
    monkeypatch.setenv("CHURCH_STORAGE", "off")
    assert _plays(_player().get(f"/stream-relay/watch/{s['id']}"))[0] == "file"


def test_before_the_migration_the_full_recording_plays(world, monkeypatch):
    d, bucket, clip = world
    s = d.session(1)
    _published(d, s)
    monkeypatch.setattr(rc, "_COLUMNS", {"there": False, "at": 1e18})
    reads = len(d.gets)
    assert _plays(_player().get(f"/stream-relay/watch/{s['id']}"))[0] == "hls"
    assert not any("full_removed_at" in g for g in d.gets[reads:])     # not even asked


def test_a_live_service_never_reads_the_copy(world):
    d, bucket, clip = world
    s = d.session(1, status="live")
    reads = len(d.gets)
    assert _plays(_player().get(f"/stream-relay/watch/{s['id']}"))[0] == "hls"
    assert not any("copy_state" in g for g in d.gets[reads:])


# ─── 8. Signing ──────────────────────────────────────────────────────

KID, SEC = "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
WHEN = datetime(2013, 5, 24, tzinfo=timezone.utc)
COPY = "/media/live/11111111-1111-1111-1111-111111111111/22222222-2222-4222-8222-222222222222/copy.mp4"


# What botocore 1.44.5's S3SigV4QueryAuth signs for the same request, key and
# moment (worked out once outside the repo, with the time pinned; the same
# script reproduces the DELETE pinned in test_church_storage.py).
@pytest.mark.parametrize("method,host,path,query,region,expires,want", [
    ("PUT", R2_HOST, COPY, None, "auto", 14400,
     "b0f930eeb56172afccfd44a3a90031603bd2ff5e1c1984d0deedfd17e29d8015"),
    ("PUT", "examplebucket.s3.amazonaws.com", "/test.txt", None, "us-east-1", 3600,
     "bd813e1bbd1dc21c323582d2bb1ba8b3051bc8991db4327cabb83e98af93bf6e"),
    ("HEAD", R2_HOST, COPY, None, "auto", 300,
     "fdf083755147eb19b13fe9fc7b4d14c312304de135c8ad8ef6e35fc72d398039"),
    ("GET", R2_HOST, COPY, {"response-content-disposition": 'attachment; filename="Grace Church 2026-11-22.mp4"',
                            "response-content-type": "video/mp4"}, "auto", 3600,
     "dad85afce2448ca0de6d0a41e0da74522e9ad8c80aeee56e2eb7ea8cf4212546"),
    ("GET", R2_HOST, COPY, {"response-content-disposition":
                            "attachment; filename=\"Iglesia Fe 2026-11-22.mp4\"; "
                            "filename*=UTF-8''Iglesia%20F%C3%A9%202026-11-22.mp4",
                            "response-content-type": "video/mp4"}, "auto", 3600,
     "b81f6c15d8357600d3df70eabb8600457886227614ee26fa02abaaf824482b91"),
])
def test_put_head_and_the_download_are_signed_as_botocore_signs_them(method, host, path, query, region,
                                                                    expires, want):
    url = sr.sigv4_presign("https", host, path, key_id=KID, secret=SEC, expires=expires, when=WHEN,
                           region=region, method=method, query=query)
    assert url.rsplit("X-Amz-Signature=", 1)[1] == want


def test_the_links_use_the_right_key_and_the_players_link_is_unchanged(world):
    put = sr.r2_write_link("PUT", "live/a/b/copy.mp4", expires=rc.JOB_LINK_S, when=WHEN)
    assert f"X-Amz-Credential={WRITE_KEY}%2F" in put and put.startswith(f"{R2}/media/live/a/b/copy.mp4?")
    get = sr.r2_link("live/a/b/seg_000001.ts", when=WHEN)
    same = sr.sigv4_presign("https", R2_HOST, "/media/live/a/b/seg_000001.ts", key_id=READ_KEY,
                            secret="read-secret", expires=sr.SEGMENT_LINK_S, when=WHEN)
    assert get == same                                                # the player's GET, byte for byte
    head = sr.r2_link("live/a/b/copy.mp4", 300, method="HEAD", when=WHEN)
    assert f"X-Amz-Credential={READ_KEY}%2F" in head and head != sr.r2_link("live/a/b/copy.mp4", 300, when=WHEN)


def test_practitioner_words_never_name_the_machinery():
    for text in (rc.disposition("Grace Church", "2026-11-22T15:00:00+00:00", timezone.utc),
                 csr.__doc__.split("Practitioner words")[0].split("download_url is")[1]):
        low = text.lower()
        assert not any(w in low for w in FORBIDDEN), text
