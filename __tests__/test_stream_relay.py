# __tests__/test_stream_relay.py
#
# Our own stream relay, the system's side (stream_relay_router.py). Pins:
# only a manager sees or changes a church's stream; the stream key is shown
# once (`<stream id>?key=<secret>`) and stored hashed, a new key retires the
# old one, and a key only works on its own church's path; YouTube/Facebook
# keys are stored encrypted and reach only the relay; the relay's routes
# fail closed without the shared secret AND while streaming is switched off;
# a stream opens one live service with our own player, and every step of a
# start or an end is repeatable — a failed read or write is a 503 the relay
# retries, never a 200 that leaves a service half open (Codex B2/B3); two
# ends at once make one draft; members hear "live" once per window (B4); a
# new run closes the old run's session and a silent one is swept; nothing
# in the bucket is public — the player plays live, a published sermon, or a
# manager's signed link, and every segment is a short-lived signed link (B1).
# Codex's re-check (2026-10-16), fixed 10-29: an old run's late heartbeat or
# finishing retry never retires the run that is live now, and a run only
# takes over from one that stopped beating (B2-R); a start retry racing the
# sweep can't open a live service for a finished session (B3-R). Those
# changes of state are database functions under one lock per church; the
# fake below mirrors them, and the same sequences were run against real
# Postgres when they were written.

import pathlib
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import live_router
import sermons_public
import stream_relay_router as sr
from auth_supabase import require_user

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
OWNER = "44444444-4444-4444-4444-444444444444"
STRANGER = "77777777-7777-7777-7777-777777777777"
SECRET = "relay-secret-for-tests"
R2 = "https://acct123.r2.cloudflarestorage.com"
RELAY = {"x-relay-secret": SECRET}
RUN_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RUN_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
RUN_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
EDT = timezone(timedelta(hours=-4))
_REAL_CHURCH_TZ = sr._church_tz


class _User:
    def __init__(self, uid):
        self.id = uid


def _params(path):
    table, _, q = path.lstrip("/").partition("?")
    return table, urllib.parse.parse_qs(q, keep_blank_values=True)


class DB:
    """Just enough PostgREST for these tables: eq/neq/gte/like/in filters,
    explicit ids, ignore-duplicates, the two one-live uniques, and the
    stream relay's four database functions
    (APPLY-2026-10-29-stream-relay-transitions.sql), each one step, as the
    church's lock makes them."""

    def __init__(self):
        self.t = {k: [] for k in ("church_streams", "stream_sessions", "live_sessions", "sermons",
                                  "business_users")}
        self.t["businesses"] = [{"id": BIZ, "owner_id": OWNER, "name": "First Light", "settings": {}}]
        self.n = 0
        self.fail = {}          # (method, table or function) -> how many calls fail next, unsaved
        self.lose = {}          # (method, table or function) -> how many save, then lose their answer

    def _boom(self, method, table, book=None):
        book = self.fail if book is None else book
        left = book.get((method, table), 0)
        if left:
            book[(method, table)] = left - 1
            return True
        return False

    # ── the database functions ──

    def _one(self, table, rid):
        return next((r for r in self.t[table] if str(r["id"]) == str(rid)), None)

    def _new_session(self, biz, sid, playlist, status, now, rec=0, size=0):
        self.n += 1
        start = datetime(2026, 10, 18, 15, tzinfo=timezone.utc) + timedelta(seconds=self.n - rec)
        row = {"id": sid, "business_id": biz, "status": status, "live_session_id": None, "sermon_id": None,
               "playlist_path": playlist, "duration_s": rec, "bytes": max(int(size or 0), 0),
               "started_at": start.isoformat(), "last_seen_at": now.isoformat(),
               "ended_at": now.isoformat() if status == "ending" else None}
        self.t["stream_sessions"].append(row)
        return row

    def _retire(self, sid, prefix, at):
        s = self._one("stream_sessions", sid)
        if s is None:
            return
        if s["status"] == "live":
            s["status"], s["ended_at"] = "ending", s.get("ended_at") or at
        for live in self.t["live_sessions"]:
            if live["business_id"] == s["business_id"] and live["status"] == "live" and (
                    live["id"] == s.get("live_session_id") or live.get("stream_url") == prefix + s["id"]):
                live.update(status="ended", ended_at=at, updated_at=at)

    def stream_relay_claim(self, p_business, p_session, p_playlist, p_ending, p_recorded_s, p_bytes,
                           p_quiet_s, p_watch_prefix):
        now = datetime.now(timezone.utc)
        s = self._one("stream_sessions", p_session)
        if s is not None:
            if s["business_id"] != p_business:
                return {"outcome": "foreign"}
            return {"outcome": "live" if s["status"] == "live" else "closed", "session": dict(s)}
        if p_ending:
            rec = max(int(p_recorded_s or 0), 0)
            s = self._new_session(p_business, p_session, p_playlist, "ending", now, rec, p_bytes)
            return {"outcome": "opened", "session": dict(s)}
        cur = next((r for r in self.t["stream_sessions"]
                    if r["business_id"] == p_business and r["status"] == "live"), None)
        retired = None
        if cur is not None:
            seen = sr._parse_ts(cur.get("last_seen_at") or cur.get("started_at"))
            if seen > now - timedelta(seconds=p_quiet_s):
                return {"outcome": "busy", "holder": cur["id"]}
            self._retire(cur["id"], p_watch_prefix, now.isoformat())
            retired = dict(cur)
        s = self._new_session(p_business, p_session, p_playlist, "live", now)
        return {"outcome": "opened", "session": dict(s), "retired": retired}

    def stream_relay_open_live(self, p_session, p_live, p_stream_url, p_title, p_watch_prefix):
        s = self._one("stream_sessions", p_session)
        if s is None:
            return {"outcome": "missing"}
        if s["status"] != "live":
            return {"outcome": "closed", "session": dict(s)}
        if s.get("live_session_id"):
            return {"outcome": "linked", "live_id": s["live_session_id"]}
        now = datetime.now(timezone.utc).isoformat()
        cur = next((r for r in self.t["live_sessions"]
                    if r["business_id"] == s["business_id"] and r["status"] == "live"), None)
        if cur is not None:
            if cur.get("stream_url") == p_stream_url:
                s["live_session_id"] = cur["id"]
                return {"outcome": "adopted", "live": dict(cur)}
            if not str(cur.get("stream_url") or "").startswith(p_watch_prefix):
                return {"outcome": "manual"}
            cur.update(status="ended", ended_at=now, updated_at=now)
        s["live_session_id"] = p_live
        if self._one("live_sessions", p_live) is not None:
            return {"outcome": "linked", "live_id": p_live}
        self.n += 1
        made = {"id": p_live, "business_id": s["business_id"], "title": p_title, "stream_url": p_stream_url,
                "status": "live", "chat_open": True, "ended_at": None,
                "started_at": (datetime.now(timezone.utc) + timedelta(seconds=self.n)).isoformat()}
        self.t["live_sessions"].append(made)
        return {"outcome": "opened", "live": dict(made)}

    def stream_relay_close(self, p_session, p_watch_prefix):
        s = self._one("stream_sessions", p_session)
        if s is None:
            return {"outcome": "missing"}
        if s["status"] == "ended":
            return {"outcome": "ended", "session": dict(s)}
        self._retire(p_session, p_watch_prefix, datetime.now(timezone.utc).isoformat())
        return {"outcome": "ending", "session": dict(s)}

    def rpc(self, name, args):
        if self._boom("RPC", name):
            return None
        out = getattr(self, name)(**args)
        return None if self._boom("RPC", name, self.lose) else out

    def _match(self, row, q):
        for k, vals in q.items():
            if k in ("select", "order", "limit", "on_conflict"):
                continue
            v = vals[0]
            cell = row.get(k)
            if v.startswith("eq.") and str(cell).lower() != v[3:].lower():
                return False
            if v.startswith("neq.") and str(cell).lower() == v[4:].lower():
                return False
            if v.startswith("gte.") and not (cell is not None and str(cell) >= v[4:]):
                return False
            if v.startswith("like.") and not fnmatch(str(cell or ""), v[5:]):
                return False
            if v.startswith("in.(") and str(cell).lower() not in v[4:-1].lower().split(","):
                return False
        return True

    def get(self, path):
        table, q = _params(path)
        if self._boom("GET", table):
            return None
        rows = [dict(r) for r in self.t.get(table, []) if self._match(r, q)]
        if q.get("order", [""])[0].endswith(".desc"):
            col = q["order"][0].split(".")[0]
            rows.sort(key=lambda r: str(r.get(col)), reverse=True)
        return rows[: int(q.get("limit", ["10000"])[0])]

    def post(self, path, body, prefer=None):
        if path.startswith("/rpc/"):
            return self.rpc(path[len("/rpc/"):], body)
        table, _ = _params(path)
        if self._boom("POST", table):
            return None
        self.n += 1
        # A stream session's start is pinned (its draft is dated by it); a
        # live service's is the real clock, which the members' alert
        # cooldown compares with now (pinned, it went stale after 10-18).
        epoch = (datetime(2026, 10, 18, 15, tzinfo=timezone.utc) if table == "stream_sessions"
                 else datetime.now(timezone.utc))
        row = {"id": f"00000000-0000-4000-8000-{self.n:012d}",
               "started_at": (epoch + timedelta(seconds=self.n)).isoformat(),
               **body}
        if any(r["id"] == row["id"] for r in self.t.setdefault(table, [])):
            return [] if "ignore-duplicates" in (prefer or "") else None
        if table in ("live_sessions", "stream_sessions"):
            row.setdefault("status", "live")
            row.setdefault("duration_s", 0)
            row.setdefault("bytes", 0)
            if any(s["business_id"] == row["business_id"] and s["status"] == "live" for s in self.t[table]):
                return None
        if table == "stream_sessions":
            row.setdefault("live_session_id", None)
            row.setdefault("sermon_id", None)
            row.setdefault("last_seen_at", None)
        if table == "church_streams":
            row.setdefault("sermon_drafts", True)
            for k in ("youtube", "facebook"):
                row.setdefault(f"{k}_on", False)
                row.setdefault(f"{k}_key_enc", "")
        self.t[table].append(row)
        return None if self._boom("POST", table, self.lose) else [dict(row)]

    def patch(self, path, body):
        table, q = _params(path)
        if self._boom("PATCH", table):
            return None
        hit = [r for r in self.t.get(table, []) if self._match(r, q)]
        for r in hit:
            r.update(body)
        return None if self._boom("PATCH", table, self.lose) else [dict(r) for r in hit]


@pytest.fixture
def db(monkeypatch):
    d = DB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
    monkeypatch.setattr(live_router, "_tell_members_live", lambda biz, row: d.t.setdefault("told", []).append(row["id"]))
    monkeypatch.setattr(sr, "_church_tz", lambda biz: EDT)
    sr._cache.clear()
    return d


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setenv("STREAM_RELAY_SECRET", SECRET)
    monkeypatch.setenv("STREAM_DEST_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("STREAM_INGEST_URL", "rtmps://stream.example.app:443/live")
    monkeypatch.setenv("STREAM_R2_ENDPOINT", R2)
    monkeypatch.setenv("STREAM_R2_BUCKET", "media")
    monkeypatch.setenv("STREAM_R2_ACCESS_KEY_ID", "AKIDTEST")
    monkeypatch.setenv("STREAM_R2_SECRET_ACCESS_KEY", "r2-secret-for-tests")


ALL_ENV = ("STREAM_RELAY_SECRET", "STREAM_DEST_ENCRYPTION_KEY", "STREAM_INGEST_URL", "STREAM_R2_ENDPOINT",
           "STREAM_R2_BUCKET", "STREAM_R2_ACCESS_KEY_ID", "STREAM_R2_SECRET_ACCESS_KEY")


def _app(uid=OWNER):
    app = FastAPI()
    app.include_router(sr.router)
    app.dependency_overrides[require_user] = lambda: _User(uid)
    return TestClient(app)


def _key(c):
    r = c.post("/stream-relay/key", json={"business_id": BIZ})
    assert r.status_code == 200, r.text
    return r.json()["key"]


def _parts(full):
    stream_id, _, q = full.partition("?")
    assert q.startswith("key=")
    return stream_id, q[len("key="):]


def _start(c, full, run=RUN_A, **extra):
    stream_id, secret = _parts(full)
    return c.post("/stream-relay/relay/started", headers=RELAY,
                  json={"stream_id": stream_id, "key": secret, "run_id": run, **extra})


def _verify(c, full):
    stream_id, secret = _parts(full)
    return c.post("/stream-relay/relay/verify", headers=RELAY, json={"stream_id": stream_id, "key": secret})


def _end(c, sid, duration=5400, **extra):
    return c.post("/stream-relay/relay/ended", headers=RELAY,
                  json={"session_id": sid, "duration_s": duration, **extra})


# ─── the team's side ─────────────────────────────────────────────────


def test_nothing_happens_until_it_is_switched_on(db, monkeypatch):
    for n in ALL_ENV:
        monkeypatch.delenv(n, raising=False)
    c = _app()
    r = c.get(f"/stream-relay?business_id={BIZ}")
    assert r.status_code == 200 and r.json()["ready"] is False and r.json()["has_key"] is False
    assert c.post("/stream-relay/key", json={"business_id": BIZ}).status_code == 503
    assert db.t["church_streams"] == []


@pytest.mark.parametrize("name,value", [
    ("STREAM_INGEST_URL", "rtmp://stream.example.app/live"),       # plaintext ingest is not "on"
    ("STREAM_DEST_ENCRYPTION_KEY", "not-a-fernet-key"),
    ("STREAM_R2_ENDPOINT", "http://acct123.r2.cloudflarestorage.com"),
    ("STREAM_R2_SECRET_ACCESS_KEY", ""),
])
def test_half_set_up_is_not_switched_on(ready, monkeypatch, name, value):
    assert sr.is_ready() is True
    monkeypatch.setenv(name, value)
    assert sr.is_ready() is False


def test_only_the_church_can_see_or_change_its_stream(db, ready):
    c = _app(STRANGER)
    assert c.get(f"/stream-relay?business_id={BIZ}").status_code == 403
    assert c.post("/stream-relay/key", json={"business_id": BIZ}).status_code == 403
    assert c.patch("/stream-relay/settings", json={"business_id": BIZ, "youtube_on": True}).status_code == 403


def test_the_key_is_shown_once_stored_hashed_and_a_new_one_retires_the_old(db, ready):
    c = _app()
    first = _key(c)
    stream_id, secret = _parts(first)
    assert stream_id == sr.stream_id_for(BIZ) and len(secret) == 32
    row = db.t["church_streams"][0]
    assert secret not in str(row) and row["key_hash"] == sr.key_hash(secret)
    view = c.get(f"/stream-relay?business_id={BIZ}").json()
    assert view["has_key"] and view["key_last4"] == secret[-4:] and "key" not in view
    assert view["server"] == "rtmps://stream.example.app:443/live"
    second = _key(c)
    assert second != first and _parts(second)[0] == stream_id and len(db.t["church_streams"]) == 1
    assert _verify(c, first).status_code == 403
    assert _verify(c, second).status_code == 200
    assert _start(c, first).status_code == 403          # a stream on the old key is cut at its next beat


def test_a_key_works_only_on_its_own_churchs_path(db, ready):
    c = _app()
    _, secret = _parts(_key(c))
    stolen_path = sr.stream_id_for(OTHER)
    r = c.post("/stream-relay/relay/verify", headers=RELAY, json={"stream_id": stolen_path, "key": secret})
    assert r.status_code == 403


def test_youtube_and_facebook_keys_are_stored_encrypted(db, ready):
    c = _app()
    assert c.patch("/stream-relay/settings", json={"business_id": BIZ, "youtube_key": "abcd-efgh"}).status_code == 409
    full = _key(c)
    assert c.patch("/stream-relay/settings", json={"business_id": BIZ, "youtube_on": True}).status_code == 400
    r = c.patch("/stream-relay/settings", json={
        "business_id": BIZ, "youtube_key": "rtmp://a.rtmp.youtube.com/live2/abcd-efgh-ijkl", "youtube_on": True,
        "facebook_key": "FB-1234-0-AbCd?s_bl=1&a=xyz", "facebook_on": True})
    assert r.status_code == 200, r.text
    assert r.json()["youtube"] == {"on": True, "saved": True}
    row = db.t["church_streams"][0]
    assert "abcd-efgh-ijkl" not in str(row) and "FB-1234" not in str(row)
    dests = {d["name"]: d["url"] for d in _verify(c, full).json()["destinations"]}
    assert dests == {"youtube": "rtmps://a.rtmps.youtube.com/live2/abcd-efgh-ijkl",
                     "facebook": "rtmps://live-api-s.facebook.com:443/rtmp/FB-1234-0-AbCd?s_bl=1&a=xyz"}
    # Clearing a key switches that copy off, and the relay's next beat sees it gone.
    r = c.patch("/stream-relay/settings", json={"business_id": BIZ, "facebook_key": ""})
    assert r.json()["facebook"] == {"on": False, "saved": False}
    assert [d["name"] for d in _start(c, full).json()["destinations"]] == ["youtube"]
    bad = c.patch("/stream-relay/settings", json={"business_id": BIZ, "youtube_key": "abc <script>"})
    assert bad.status_code == 400


# ─── the relay's side ────────────────────────────────────────────────


def test_relay_routes_fail_closed(db, ready, monkeypatch):
    c = _app()
    full = _key(c)
    stream_id, secret = _parts(full)
    body = {"stream_id": stream_id, "key": secret}
    assert c.post("/stream-relay/relay/verify", json=body).status_code == 401
    assert c.post("/stream-relay/relay/verify", json=body, headers={"x-relay-secret": "nope"}).status_code == 401
    monkeypatch.delenv("STREAM_RELAY_SECRET")
    assert c.post("/stream-relay/relay/verify", json=body, headers=RELAY).status_code == 503
    assert _start(c, full).status_code == 503


def test_switched_off_means_no_church_can_stream_but_a_service_can_still_end(db, ready, monkeypatch):
    """Codex B5: readiness closes the relay's door, not just the panel."""
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    for n in ("STREAM_DEST_ENCRYPTION_KEY", "STREAM_INGEST_URL", "STREAM_R2_ENDPOINT"):
        monkeypatch.delenv(n)
    assert _verify(c, full).status_code == 403
    assert _start(c, full).status_code == 403
    assert _end(c, sid, 120).status_code == 200            # nothing is stranded
    assert db.t["stream_sessions"][0]["status"] == "ended" and db.t["live_sessions"][0]["status"] == "ended"


def test_a_stream_opens_one_live_service_with_our_player(db, ready):
    c = _app()
    full = _key(c)
    c.patch("/stream-relay/settings", json={"business_id": BIZ, "youtube_key": "yt-key-1", "youtube_on": True})
    r = _start(c, full)
    assert r.status_code == 200, r.text
    out = r.json()
    sid = out["session_id"]
    assert sid == sr.session_id_for(BIZ, RUN_A)
    assert out["playlist_path"] == f"live/{BIZ}/{sid}/index.m3u8"
    assert out["destinations"] == [{"name": "youtube", "label": "YouTube",
                                    "url": "rtmps://a.rtmps.youtube.com/live2/yt-key-1"}]
    live = db.t["live_sessions"]
    assert len(live) == 1 and live[0]["stream_url"] == sr.watch_url(sid)
    assert db.t["stream_sessions"][0]["live_session_id"] == live[0]["id"]
    assert db.t["told"] == [live[0]["id"]]
    # The heartbeat (and a restarted relay on the same run) gets the same one.
    again = _start(c, full, recorded_s=600, bytes=1234).json()
    assert again["session_id"] == sid and len(db.t["stream_sessions"]) == 1 and len(live) == 1
    s = db.t["stream_sessions"][0]
    assert s["duration_s"] == 600 and s["bytes"] == 1234 and s["last_seen_at"]
    assert db.t["told"] == [live[0]["id"]]
    # Members' player for that link is ours.
    assert live_router.stream_embed(live[0]["stream_url"]) == sr.watch_url(sid)


def test_a_service_the_team_started_by_hand_is_left_alone(db, ready):
    c = _app()
    full = _key(c)
    db.t["live_sessions"].append({"id": "manual", "business_id": BIZ, "status": "live",
                                  "stream_url": "https://youtube.com/live/abc"})
    out = _start(c, full).json()
    assert len(db.t["live_sessions"]) == 1 and db.t["live_sessions"][0]["stream_url"].startswith("https://youtube")
    assert db.t["stream_sessions"][0].get("live_session_id") is None and out["session_id"]


def test_a_failed_live_service_step_is_retried_not_taken_for_a_manual_service(db, ready):
    """Codex B2: the live-service step failing must not look like 'the team
    is live'. (Its read of the live service now happens inside the
    database step, under the church's lock.)"""
    c = _app()
    full = _key(c)
    db.fail[("RPC", "stream_relay_open_live")] = 1
    assert _start(c, full).status_code == 503
    assert db.t["live_sessions"] == []
    assert _start(c, full).status_code == 200
    assert len(db.t["live_sessions"]) == 1 and len(db.t["stream_sessions"]) == 1
    assert db.t["stream_sessions"][0]["live_session_id"] == db.t["live_sessions"][0]["id"]


@pytest.mark.parametrize("how,step", [
    ("fail", "stream_relay_claim"), ("fail", "stream_relay_open_live"),
    ("lose", "stream_relay_claim"), ("lose", "stream_relay_open_live")])
def test_a_half_finished_start_is_repaired_by_the_retry(db, ready, how, step):
    """Codex B2: a step that failed, or that saved and then lost its answer
    (Codex's commit-then-lose-link probe), is a 503, and the relay's retry
    (same run) finishes the same session: one session, one linked live
    service. The live service is opened and linked in one step, so there
    is no half-linked service left to find."""
    c = _app()
    full = _key(c)
    (db.fail if how == "fail" else db.lose)[("RPC", step)] = 1
    assert _start(c, full).status_code == 503
    r = _start(c, full)
    assert r.status_code == 200, r.text
    assert len(db.t["stream_sessions"]) == 1 and len(db.t["live_sessions"]) == 1
    s = db.t["stream_sessions"][0]
    assert s["id"] == r.json()["session_id"] and s["live_session_id"] == db.t["live_sessions"][0]["id"]
    assert s["playlist_path"] == f"live/{BIZ}/{s['id']}/index.m3u8"


def test_a_service_that_ends_leaves_a_sermon_draft(db, ready):
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    r = _end(c, sid, 5400, bytes=4_000_000_000)
    assert r.status_code == 200, r.text
    s = db.t["stream_sessions"][0]
    assert s["status"] == "ended" and s["duration_s"] == 5400 and s["sermon_id"] == r.json()["sermon_id"]
    assert db.t["live_sessions"][0]["status"] == "ended"
    sermon = db.t["sermons"][0]
    assert sermon["published"] is False and sermon["preached_on"] == "2026-10-18"
    assert sermon["title"] == "Service, October 18, 2026"
    assert sermon["video_url"] == sr.watch_url(sid)
    # Told twice, it is still one draft.
    again = _end(c, sid, 5400)
    assert again.json()["sermon_id"] == sermon["id"] and len(db.t["sermons"]) == 1


def test_a_failed_close_is_a_503_and_the_retry_closes_it(db, ready):
    """Codex B3: never 200 with the live service still open."""
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    db.fail[("RPC", "stream_relay_close")] = 1
    assert _end(c, sid).status_code == 503
    assert db.t["live_sessions"][0]["status"] == "live" and db.t["stream_sessions"][0]["status"] == "live"
    assert _end(c, sid).status_code == 200
    assert db.t["live_sessions"][0]["status"] == "ended" and len(db.t["sermons"]) == 1


def test_a_close_that_saved_but_lost_its_answer_is_finished_by_the_retry(db, ready):
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    db.lose[("RPC", "stream_relay_close")] = 1
    assert _end(c, sid).status_code == 503
    assert db.t["live_sessions"][0]["status"] == "ended" and _row(db, sid)["status"] == "ending"
    assert _end(c, sid).status_code == 200
    assert _row(db, sid)["status"] == "ended" and len(db.t["sermons"]) == 1


@pytest.mark.parametrize("book", ["fail", "lose"])
def test_a_failed_draft_is_a_503_and_the_retry_saves_it(db, ready, book):
    """Failed, or saved with its answer lost (Codex's commit-then-lose-
    sermon probe): one draft either way. The live service is closed
    already, so members aren't left on "live" while it is retried."""
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    getattr(db, book)[("POST", "sermons")] = 1
    assert _end(c, sid).status_code == 503
    assert db.t["stream_sessions"][0]["status"] == "ending" and _live_services(db) == []
    assert _end(c, sid).status_code == 200
    assert len(db.t["sermons"]) == 1 and db.t["stream_sessions"][0]["sermon_id"] == db.t["sermons"][0]["id"]


@pytest.mark.parametrize("book", ["fail", "lose"])
def test_a_failed_final_mark_is_a_503_and_the_retry_makes_no_second_draft(db, ready, book):
    """The PR bot's item 2: the last write (ending -> ended, with the
    draft's id) is checked, and its retry makes no second draft."""
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    getattr(db, book)[("PATCH", "stream_sessions")] = 1
    assert _end(c, sid).status_code == 503
    assert len(db.t["sermons"]) == 1
    r = _end(c, sid)
    assert r.status_code == 200 and r.json()["sermon_id"] == db.t["sermons"][0]["id"]
    assert len(db.t["sermons"]) == 1 and _row(db, sid)["status"] == "ended"
    assert _row(db, sid)["sermon_id"] == db.t["sermons"][0]["id"]


def test_two_ends_that_draft_together_make_one_draft(db, ready, monkeypatch):
    """Both ends are past the close and saving the draft at once."""
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    real = sr._sermon_draft
    inner = []

    def at_once(biz, s):
        if not inner:
            inner.append(None)
            # The other end runs to completion in between (the route itself,
            # called directly: a request inside a request stalls TestClient).
            inner[0] = sr.relay_ended(sr.EndedIn(session_id=sid, duration_s=5400), x_relay_secret=SECRET)
        return real(biz, s)
    monkeypatch.setattr(sr, "_sermon_draft", at_once)
    outer = _end(c, sid)
    assert outer.status_code == 200 and inner[0]["ok"] is True
    assert len(db.t["sermons"]) == 1
    assert outer.json()["sermon_id"] == inner[0]["sermon_id"] == db.t["sermons"][0]["id"]
    assert _row(db, sid)["sermon_id"] == db.t["sermons"][0]["id"]


def test_a_service_left_ending_is_finished_by_the_sweep(db, ready):
    """Its relay is gone after the live service closed but before the draft
    saved: the sweep finishes it after ENDING_GRACE_S."""
    c = _app()
    full = _key(c)
    sid = _start(c, full, recorded_s=2400).json()["session_id"]
    db.fail[("POST", "sermons")] = 1
    assert _end(c, sid, 2400).status_code == 503
    s = _row(db, sid)
    assert s["status"] == "ending" and sr.sweep_stale() == 0
    s["ended_at"] = (datetime.now(timezone.utc) - timedelta(seconds=sr.ENDING_GRACE_S + 60)).isoformat()
    assert sr.sweep_stale() == 1
    assert s["status"] == "ended" and len(db.t["sermons"]) == 1 and s["sermon_id"] == db.t["sermons"][0]["id"]


def test_two_ends_that_read_together_make_one_draft(db, ready, monkeypatch):
    """Codex B3: both callbacks read 'live' before either wrote."""
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    snapshot = dict(db.t["stream_sessions"][0])
    real = db.get

    def stale(path):
        if path.startswith("/stream_sessions?id="):
            return [dict(snapshot)]
        return real(path)
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", stale)
    a, b = _end(c, sid), _end(c, sid)
    assert a.status_code == b.status_code == 200
    assert len(db.t["sermons"]) == 1 and a.json()["sermon_id"] == b.json()["sermon_id"]


def test_a_sound_check_is_not_a_sermon(db, ready):
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    _end(c, sid, 120)
    assert db.t["sermons"] == [] and db.t["stream_sessions"][0]["status"] == "ended"
    assert _end(c, "not-a-uuid").status_code == 400


def test_the_church_can_turn_sermon_drafts_off(db, ready):
    c = _app()
    full = _key(c)
    c.patch("/stream-relay/settings", json={"business_id": BIZ, "sermon_drafts": False})
    sid = _start(c, full).json()["session_id"]
    _end(c, sid)
    assert db.t["sermons"] == []


def test_members_hear_live_once_for_a_burst_of_starts(db, ready):
    """Codex B4: three short start/stop cycles are one alert."""
    c = _app()
    full = _key(c)
    for run in (RUN_A, RUN_B, "cccccccc-cccc-4ccc-8ccc-cccccccccccc"):
        sid = _start(c, full, run).json()["session_id"]
        assert _end(c, sid, 30).status_code == 200
    assert len(db.t["live_sessions"]) == 3 and len(db.t["told"]) == 1


def test_a_new_run_closes_a_quiet_old_runs_session_first(db, ready):
    """Codex R5 (backend half): a reconnect after the grace never lands in
    the session that is being finished; the old run's late end is a no-op.
    The new run waits (503) until the old one has missed its beats (B2-R)."""
    c = _app()
    full = _key(c)
    a = _start(c, full, RUN_A).json()["session_id"]
    _start(c, full, RUN_A, recorded_s=3600)               # its last beat: an hour in
    assert _start(c, full, RUN_B).status_code == 503       # A only just beat
    _row(db, a)["last_seen_at"] = (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat()
    b = _start(c, full, RUN_B).json()["session_id"]
    assert a != b
    old, new = db.t["stream_sessions"]
    assert old["status"] == "ended" and old["duration_s"] == 3600 and new["status"] == "live"
    assert db.t["live_sessions"][0]["status"] == "ended" and db.t["live_sessions"][1]["status"] == "live"
    draft = old["sermon_id"]
    assert draft and len(db.t["sermons"]) == 1
    late = _end(c, a, 3700)
    assert late.status_code == 200 and late.json()["sermon_id"] == draft and len(db.t["sermons"]) == 1


def test_a_run_whose_session_was_closed_is_told_to_start_over(db, ready):
    """The 409 names the closed session, so the relay can still upload
    that recording's last part and report its end."""
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    _end(c, sid)
    r = _start(c, full)
    assert r.status_code == 409
    assert r.json()["detail"]["session_id"] == sid
    assert r.json()["detail"]["playlist_path"] == f"live/{BIZ}/{sid}/index.m3u8"


def test_a_session_asked_for_only_at_the_end_never_tells_members_its_live(db, ready):
    """The backend was down for the whole service: the relay asks for a
    session as it finishes. No live service, no "live now" alert after
    the fact; the draft is still made."""
    c = _app()
    full = _key(c)
    r = _start(c, full, ending=True)
    assert r.status_code == 200
    assert db.t["live_sessions"] == [] and db.t.get("told", []) == []
    assert _end(c, r.json()["session_id"]).status_code == 200 and len(db.t["sermons"]) == 1


def test_a_session_the_relay_stopped_reporting_is_swept(db, ready):
    """Codex R4 (backend half): a lost relay never leaves a service live."""
    c = _app()
    full = _key(c)
    _start(c, full, recorded_s=2400)
    s = db.t["stream_sessions"][0]
    s["last_seen_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    assert sr.sweep_stale() == 0 and s["status"] == "live"
    s["last_seen_at"] = (datetime.now(timezone.utc) - timedelta(minutes=50)).isoformat()
    assert sr.sweep_stale() == 1
    assert s["status"] == "ended" and db.t["live_sessions"][0]["status"] == "ended" and len(db.t["sermons"]) == 1


def test_the_sweep_does_nothing_before_its_column_exists(db, ready):
    c = _app()
    full = _key(c)
    _start(c, full)
    s = db.t["stream_sessions"][0]
    del s["last_seen_at"]
    s["started_at"] = "2026-01-01T00:00:00+00:00"
    assert sr.sweep_stale() == 0 and s["status"] == "live"


# ─── an old run never retires a newer one (Codex B2-R) ───────────────


def _row(db, sid):
    return next(s for s in db.t["stream_sessions"] if s["id"] == sid)


def _live_services(db):
    return [s for s in db.t["live_sessions"] if s["status"] == "live"]


def _a_ended_then_b_live(c, full, db):
    a = _start(c, full, RUN_A).json()["session_id"]
    assert _end(c, a).status_code == 200
    b = _start(c, full, RUN_B).json()["session_id"]
    assert _row(db, b)["status"] == "live" and len(_live_services(db)) == 1
    return a, b


def test_an_old_runs_ending_retry_never_closes_the_live_run(db, ready):
    """A's finisher without a saved session id asks for A as it ends,
    after B went live. A is named back (409); B keeps its live service."""
    c = _app()
    full = _key(c)
    a, b = _a_ended_then_b_live(c, full, db)
    late = _start(c, full, RUN_A, ending=True, recorded_s=5400)
    assert late.status_code == 409 and late.json()["detail"]["session_id"] == a
    assert _row(db, b)["status"] == "live", "the old run's retry closed the live run"
    assert [s["id"] for s in _live_services(db)] == [_row(db, b)["live_session_id"]]
    assert _start(c, full, RUN_B).status_code == 200      # B's next beat is not told to split
    assert len(db.t["sermons"]) == 1


def test_an_old_runs_heartbeat_never_closes_the_live_run(db, ready):
    c = _app()
    full = _key(c)
    a, b = _a_ended_then_b_live(c, full, db)
    late = _start(c, full, RUN_A, recorded_s=600)
    assert late.status_code == 409 and late.json()["detail"]["session_id"] == a
    assert _row(db, b)["status"] == "live" and len(_live_services(db)) == 1
    assert _start(c, full, RUN_B).status_code == 200


def test_a_recording_the_backend_never_saw_finishes_beside_the_live_run(db, ready):
    """The backend was down for all of C; C's finisher asks for a session
    while B is live. C gets its own (already over), B is never touched."""
    c = _app()
    full = _key(c)
    b = _start(c, full, RUN_B).json()["session_id"]
    r = _start(c, full, RUN_C, ending=True, recorded_s=3600, bytes=99)
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    assert sid == sr.session_id_for(BIZ, RUN_C) and _row(db, sid)["status"] != "live"
    assert _row(db, b)["status"] == "live" and len(_live_services(db)) == 1
    assert _end(c, sid, 3600).status_code == 200
    assert _row(db, sid)["status"] == "ended" and len(db.t["sermons"]) == 1
    assert _row(db, b)["status"] == "live" and len(_live_services(db)) == 1
    assert db.t.get("told", []) == [_row(db, b)["live_session_id"]]


def test_a_run_still_beating_is_never_taken_over(db, ready):
    """A run the backend has never seen is not newer just because its id
    differs: while B beats, C is told to ask again (503) and B is left
    alone. Once B has missed its beats, C takes over."""
    c = _app()
    full = _key(c)
    b = _start(c, full, RUN_B, recorded_s=3600).json()["session_id"]
    r = _start(c, full, RUN_C)
    assert r.status_code == 503
    assert r.json()["detail"] == {"error": "another run is live", "key_ok": True,
                                  "retry_after_s": sr.HANDOVER_QUIET_S}
    assert _row(db, b)["status"] == "live" and len(_live_services(db)) == 1
    assert all(s["id"] != sr.session_id_for(BIZ, RUN_C) for s in db.t["stream_sessions"])
    _row(db, b)["last_seen_at"] = (datetime.now(timezone.utc) - timedelta(seconds=sr.HANDOVER_QUIET_S + 30)).isoformat()
    r = _start(c, full, RUN_C)
    assert r.status_code == 200, r.text
    assert _row(db, b)["status"] == "ended" and _row(db, b)["sermon_id"]
    assert [s["stream_url"] for s in _live_services(db)] == [sr.watch_url(r.json()["session_id"])]


# ─── start, end and the sweep can't interleave (Codex B3-R) ──────────


def _half_started(c, full, db, monkeypatch):
    """A start that saved its session but stopped before its live service."""
    real = sr._ensure_live_service

    def stops(biz, s):
        raise sr.HTTPException(503, "live read failed")
    monkeypatch.setattr(sr, "_ensure_live_service", stops)
    assert _start(c, full).status_code == 503
    monkeypatch.setattr(sr, "_ensure_live_service", real)
    s = db.t["stream_sessions"][0]
    assert s["status"] == "live" and not s.get("live_session_id") and db.t["live_sessions"] == []
    return s, real


def test_a_start_retry_that_loses_the_race_with_the_sweep_opens_nothing(db, ready, monkeypatch):
    """Codex's interleaving: the retry pauses just before its live service,
    the sweep finishes the session, the retry resumes. It must not open a
    live service nobody will ever close; it is told the session ended."""
    c = _app()
    full = _key(c)
    s, real = _half_started(c, full, db, monkeypatch)
    s["last_seen_at"] = "2000-01-01T00:00:00+00:00"

    def sweep_wins(biz, sess):
        assert sr.sweep_stale() == 1
        return real(biz, sess)
    monkeypatch.setattr(sr, "_ensure_live_service", sweep_wins)
    r = _start(c, full)
    assert r.status_code == 409 and r.json()["detail"]["session_id"] == s["id"]
    assert _live_services(db) == [], "a live service was opened for a session already finished"
    assert s["status"] == "ended" and db.t.get("told", []) == []


def test_a_live_service_opened_just_before_the_sweep_is_closed_by_it(db, ready, monkeypatch):
    """The other order: the sweep has read the session (no live service
    yet), the retry opens one, then the sweep finishes. It closes it."""
    c = _app()
    full = _key(c)
    s, _ = _half_started(c, full, db, monkeypatch)
    s["last_seen_at"] = "2000-01-01T00:00:00+00:00"
    real_finalize = sr.finalize

    def retry_wins(sess, duration, size):
        assert _start(c, full).status_code == 200
        assert len(_live_services(db)) == 1
        return real_finalize(sess, duration, size)
    monkeypatch.setattr(sr, "finalize", retry_wins)
    assert sr.sweep_stale() == 1
    assert _live_services(db) == [] and s["status"] == "ended"


# ─── every write checked, every failed read a retry (the PR bot) ────


def test_a_failed_settings_read_at_the_end_is_a_503_never_a_draft(db, ready):
    """Bot item 1: a church with drafts off whose settings didn't load is
    not a church with drafts on."""
    c = _app()
    full = _key(c)
    c.patch("/stream-relay/settings", json={"business_id": BIZ, "sermon_drafts": False})
    sid = _start(c, full).json()["session_id"]
    db.fail[("GET", "church_streams")] = 1
    assert _end(c, sid).status_code == 503
    assert db.t["sermons"] == [] and _row(db, sid)["status"] != "ended"
    assert _live_services(db) == []                         # members aren't left watching "live"
    assert _end(c, sid).status_code == 200
    assert db.t["sermons"] == [] and _row(db, sid)["status"] == "ended"


def _at_ten_thirty_pm_pacific(db, sid):
    # 03:30 UTC on the 19th is 8:30 PM on the 18th in Los Angeles.
    _row(db, sid)["started_at"] = "2026-10-19T03:30:00+00:00"
    db.t["businesses"][0]["settings"] = {"availability": {"timezone": "America/Los_Angeles"}}


def test_the_draft_is_dated_on_the_churchs_own_clock(db, ready, monkeypatch):
    """The bot's 'worth a look': the real time-zone path, not a stand-in."""
    monkeypatch.setattr(sr, "_church_tz", _REAL_CHURCH_TZ)
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    _at_ten_thirty_pm_pacific(db, sid)
    assert _end(c, sid).status_code == 200
    assert db.t["sermons"][0]["preached_on"] == "2026-10-18"
    assert db.t["sermons"][0]["title"] == "Service, October 18, 2026"


def test_a_failed_time_zone_read_is_a_503_not_a_utc_date(db, ready, monkeypatch):
    """A failed read was taken for 'no time zone' (UTC): near midnight the
    sermon landed on the wrong day, for good."""
    monkeypatch.setattr(sr, "_church_tz", _REAL_CHURCH_TZ)
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    _at_ten_thirty_pm_pacific(db, sid)
    db.fail[("GET", "businesses")] = 1
    assert _end(c, sid).status_code == 503
    assert db.t["sermons"] == []
    assert _end(c, sid).status_code == 200
    assert db.t["sermons"][0]["preached_on"] == "2026-10-18"


def test_the_database_functions_take_what_the_router_sends(db, ready, monkeypatch):
    """PostgREST finds a function by its argument names: one name off and
    production answers 404 while the fake here still works. Pin every call
    the router makes to the signatures in the migration itself."""
    import re as _re
    sql = (pathlib.Path(__file__).resolve().parent.parent / "supabase"
           / "APPLY-2026-10-29-stream-relay-transitions.sql").read_text(encoding="utf-8")
    signatures = {
        name: {p.split()[0] for p in params.replace("\n", " ").split(",") if p.strip()}
        for name, params in _re.findall(r"create or replace function public\.(\w+)\((.*?)\)\s*returns", sql, _re.S)}
    assert set(signatures) == {"stream_relay_claim", "stream_relay_open_live", "stream_relay_close",
                               "stream_relay_retire"}
    calls = []
    real = db.post

    def post(path, body, prefer=None):
        if path.startswith("/rpc/"):
            calls.append((path[len("/rpc/"):], set(body)))
        return real(path, body, prefer)
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    _end(c, sid)
    _start(c, full, RUN_B, ending=True)
    assert {name for name, _ in calls} == {"stream_relay_claim", "stream_relay_open_live", "stream_relay_close"}
    for name, args in calls:
        assert args == signatures[name], name


# ─── playback: nothing in the bucket is public ──────────────────────


PLAYLIST = ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-PLAYLIST-TYPE:EVENT\n#EXTINF:4.000,\nseg_000000.ts\n"
            "#EXTINF:4.000,\nseg_000001.ts\n#EXTINF:4.000,\n../../other/secret.ts\n")


@pytest.fixture
def bucket(monkeypatch):
    import httpx
    asked = []

    class R:
        def __init__(self, code, text):
            self.status_code, self.text = code, text

    def get(url, timeout=None):
        asked.append(url)
        return R(200, PLAYLIST)
    monkeypatch.setattr(httpx, "get", get)
    return asked


def _ended_draft(c, db):
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    _end(c, sid)
    return sid


def test_the_draft_link_is_our_player_never_the_bucket(db, ready):
    c = _app()
    sid = _ended_draft(c, db)
    url = db.t["sermons"][0]["video_url"]
    assert url == sr.watch_url(sid) and "r2.cloudflarestorage.com" not in url and "/live/" not in url


def test_live_plays_for_anyone_and_the_playlist_is_signed(db, ready, bucket):
    c = _app()
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    page = c.get(f"/stream-relay/watch/{sid}")
    assert page.status_code == 200 and f'data-src="/stream-relay/media/{sid}/index.m3u8"' in page.text
    csp = page.headers["content-security-policy"]
    assert R2 in csp and "frame-ancestors" not in csp and page.headers["cache-control"] == "no-store"
    pl = c.get(f"/stream-relay/media/{sid}/index.m3u8")
    assert pl.status_code == 200 and pl.headers["cache-control"] == "no-store"
    lines = [ln for ln in pl.text.splitlines() if not ln.startswith("#")]
    assert len(lines) == 2 and "secret.ts" not in pl.text
    for ln in lines:
        assert ln.startswith(f"{R2}/media/live/{BIZ}/{sid}/seg_00000") and "X-Amz-Signature=" in ln
        assert f"X-Amz-Expires={sr.SEGMENT_LINK_S}" in ln
    assert pl.text.count("#EXTINF") == 2                     # the dropped line took its EXTINF with it
    assert bucket and "X-Amz-Signature=" in bucket[0]          # the playlist itself was read signed too


def test_an_unpublished_recording_plays_only_with_a_managers_link(db, ready, bucket):
    """Codex B1/R7: after the service, a member who kept the link gets nothing."""
    c = _app()
    sid = _ended_draft(c, db)
    assert c.get(f"/stream-relay/watch/{sid}").status_code == 404
    assert c.get(f"/stream-relay/media/{sid}/index.m3u8").status_code == 404
    link = c.get(f"/stream-relay?business_id={BIZ}").json()["recent"][0]["watch_url"]
    assert link.startswith(sr.watch_url(sid) + "?t=")
    path = urllib.parse.urlparse(link)
    assert c.get(f"{path.path}?{path.query}").status_code == 200
    t = urllib.parse.parse_qs(path.query)["t"][0]
    assert c.get(f"/stream-relay/media/{sid}/index.m3u8?t={t}").status_code == 200
    exp, sig = t.split(".")
    assert c.get(f"/stream-relay/media/{sid}/index.m3u8?t={exp}.{'0' * len(sig)}").status_code == 404
    assert c.get(f"/stream-relay/media/{sid}/index.m3u8?t={int(exp) + 1}.{sig}").status_code == 404
    other = "00000000-0000-4000-8000-0000000000ff"
    assert sr.token_ok(other, t) is False
    assert sr.token_ok(sid, sr.staff_token(sid, now=0)) is False      # expired long ago


def test_publishing_the_sermon_makes_it_public(db, ready, bucket):
    c = _app()
    sid = _ended_draft(c, db)
    db.t["sermons"][0]["published"] = True
    sr._cache.clear()
    assert c.get(f"/stream-relay/watch/{sid}").status_code == 200
    pl = c.get(f"/stream-relay/media/{sid}/index.m3u8")
    assert pl.status_code == 200 and pl.headers["cache-control"].startswith("private")


def test_unknown_or_switched_off_recordings_are_not_found(db, ready, bucket, monkeypatch):
    c = _app()
    assert c.get("/stream-relay/watch/not-a-session").status_code == 404
    assert c.get("/stream-relay/media/00000000-0000-4000-8000-0000000000aa/index.m3u8").status_code == 404
    full = _key(c)
    sid = _start(c, full).json()["session_id"]
    monkeypatch.delenv("STREAM_R2_ENDPOINT")
    assert c.get(f"/stream-relay/media/{sid}/index.m3u8").status_code == 404


def test_r2_links_are_aws_signature_v4():
    """AWS's published example for a presigned GET (S3 docs, sigv4 query auth)."""
    url = sr.sigv4_presign("https", "examplebucket.s3.amazonaws.com", "/test.txt",
                           key_id="AKIAIOSFODNN7EXAMPLE", secret="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                           expires=86400, when=datetime(2013, 5, 24, tzinfo=timezone.utc), region="us-east-1")
    assert url.endswith("X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404")


def test_only_our_own_recordings_play_in_our_player(ready):
    sid = "00000000-0000-4000-8000-000000000001"
    ok = sr.watch_url(sid)
    assert sermons_public.video_embed_src(ok) == ok
    assert sermons_public.video_embed_src(ok.replace(urllib.parse.urlparse(ok).hostname, "evil.example")) == ""
    assert sermons_public.video_embed_src(ok.replace("https://", "http://")) == ""
    assert sermons_public.video_embed_src(ok.replace(sid, "../secrets")) == ""
    # YouTube still works as before.
    assert sermons_public.video_embed_src("https://youtu.be/abc123") == "https://www.youtube-nocookie.com/embed/abc123"


def test_a_managers_link_never_reaches_the_access_log():
    import access_log_redaction
    line = 'GET /stream-relay/watch/abc?t=1760000000.deadbeef HTTP/1.1'
    assert "deadbeef" not in access_log_redaction.redact(line)
    assert "deadbeef" not in access_log_redaction.redact("/stream-relay/media/abc/index.m3u8?t=1.deadbeef")
