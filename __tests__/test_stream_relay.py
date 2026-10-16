# __tests__/test_stream_relay.py
#
# Our own stream relay, the system's side (stream_relay_router.py). Pins:
# only a manager sees or changes a church's stream; the stream key is
# shown once and stored hashed, and a new key retires the old one; the
# YouTube/Facebook keys are stored encrypted and reach only the relay;
# the relay's routes fail closed without the shared secret; a stream
# that starts opens one live service with our own player (leaving a
# service the team started by hand alone) and is idempotent; a stream
# that ends closes it and leaves an unpublished sermon draft, but a
# five-minute sound check does not; our recordings play in our player.

import pathlib
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

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
OWNER = "44444444-4444-4444-4444-444444444444"
STRANGER = "77777777-7777-7777-7777-777777777777"
SECRET = "relay-secret-for-tests"
MEDIA = "https://media.example.app"
RELAY = {"x-relay-secret": SECRET}


class _User:
    def __init__(self, uid):
        self.id = uid


def _params(path):
    table, _, q = path.lstrip("/").partition("?")
    return table, urllib.parse.parse_qs(q, keep_blank_values=True)


class DB:
    """Just enough PostgREST for these tables, with the two one-live uniques."""

    def __init__(self):
        self.t = {k: [] for k in ("church_streams", "stream_sessions", "live_sessions", "sermons",
                                  "business_users")}
        self.t["businesses"] = [{"id": BIZ, "owner_id": OWNER, "name": "First Light", "settings": {}}]
        self.n = 0

    def _match(self, row, q):
        for k, vals in q.items():
            if k in ("select", "order", "limit"):
                continue
            v = vals[0]
            if v.startswith("eq.") and str(row.get(k)).lower() != v[3:].lower():
                return False
        return True

    def get(self, path):
        table, q = _params(path)
        rows = [dict(r) for r in self.t.get(table, []) if self._match(r, q)]
        if q.get("order", [""])[0].endswith(".desc"):
            col = q["order"][0].split(".")[0]
            rows.sort(key=lambda r: str(r.get(col)), reverse=True)
        return rows[: int(q.get("limit", ["10000"])[0])]

    def post(self, path, body, prefer=None):
        table, _ = _params(path)
        self.n += 1
        row = {"id": f"00000000-0000-4000-8000-{self.n:012d}",
               "started_at": (datetime(2026, 10, 18, 15, tzinfo=timezone.utc) + timedelta(seconds=self.n)).isoformat(),
               **body}
        if table in ("live_sessions", "stream_sessions"):
            row.setdefault("status", "live")
            if any(s["business_id"] == row["business_id"] and s["status"] == "live" for s in self.t[table]):
                return None
        if table == "church_streams":
            row.setdefault("sermon_drafts", True)
            for k in ("youtube", "facebook"):
                row.setdefault(f"{k}_on", False)
                row.setdefault(f"{k}_key_enc", "")
        self.t.setdefault(table, []).append(row)
        return [dict(row)]

    def patch(self, path, body):
        table, q = _params(path)
        hit = [r for r in self.t.get(table, []) if self._match(r, q)]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]


@pytest.fixture
def db(monkeypatch):
    d = DB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
    monkeypatch.setattr(live_router, "_tell_members_live", lambda biz, row: d.t.setdefault("told", []).append(row["id"]))
    monkeypatch.setattr(sr, "_local_now", lambda biz: datetime(2026, 10, 18, 11, 5))
    return d


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setenv("STREAM_RELAY_SECRET", SECRET)
    monkeypatch.setenv("STREAM_DEST_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("STREAM_INGEST_URL", "rtmp://stream.example.app/live")
    monkeypatch.setenv("MEDIA_PUBLIC_BASE", MEDIA)


def _app(uid=OWNER):
    app = FastAPI()
    app.include_router(sr.router)
    app.dependency_overrides[require_user] = lambda: _User(uid)
    return TestClient(app)


def _key(c):
    r = c.post("/stream-relay/key", json={"business_id": BIZ})
    assert r.status_code == 200, r.text
    return r.json()["key"]


# ─── the team's side ─────────────────────────────────────────────────


def test_nothing_happens_until_it_is_switched_on(db, monkeypatch):
    for n in ("STREAM_RELAY_SECRET", "STREAM_DEST_ENCRYPTION_KEY", "STREAM_INGEST_URL", "MEDIA_PUBLIC_BASE"):
        monkeypatch.delenv(n, raising=False)
    c = _app()
    r = c.get(f"/stream-relay?business_id={BIZ}")
    assert r.status_code == 200 and r.json()["ready"] is False and r.json()["has_key"] is False
    assert c.post("/stream-relay/key", json={"business_id": BIZ}).status_code == 503
    assert db.t["church_streams"] == []


def test_only_the_church_can_see_or_change_its_stream(db, ready):
    c = _app(STRANGER)
    assert c.get(f"/stream-relay?business_id={BIZ}").status_code == 403
    assert c.post("/stream-relay/key", json={"business_id": BIZ}).status_code == 403
    assert c.patch("/stream-relay/settings", json={"business_id": BIZ, "youtube_on": True}).status_code == 403


def test_the_key_is_shown_once_stored_hashed_and_a_new_one_retires_the_old(db, ready):
    c = _app()
    first = _key(c)
    row = db.t["church_streams"][0]
    assert first not in str(row) and row["key_hash"] == sr.key_hash(first)
    view = c.get(f"/stream-relay?business_id={BIZ}").json()
    assert view["has_key"] and view["key_last4"] == first[-4:] and "key" not in view
    assert view["server"] == "rtmp://stream.example.app/live"
    second = _key(c)
    assert second != first and len(db.t["church_streams"]) == 1
    relay = _app()
    assert relay.post("/stream-relay/relay/verify", json={"key": first}, headers=RELAY).status_code == 403
    assert relay.post("/stream-relay/relay/verify", json={"key": second}, headers=RELAY).status_code == 200


def test_youtube_and_facebook_keys_are_stored_encrypted(db, ready):
    c = _app()
    assert c.patch("/stream-relay/settings", json={"business_id": BIZ, "youtube_key": "abcd-efgh"}).status_code == 409
    _key(c)
    assert c.patch("/stream-relay/settings", json={"business_id": BIZ, "youtube_on": True}).status_code == 400
    r = c.patch("/stream-relay/settings", json={
        "business_id": BIZ, "youtube_key": "rtmp://a.rtmp.youtube.com/live2/abcd-efgh-ijkl", "youtube_on": True,
        "facebook_key": "FB-1234-0-AbCd?s_bl=1&a=xyz", "facebook_on": True})
    assert r.status_code == 200, r.text
    assert r.json()["youtube"] == {"on": True, "saved": True}
    row = db.t["church_streams"][0]
    assert "abcd-efgh-ijkl" not in str(row) and "FB-1234" not in str(row)
    dests = {d["name"]: d["url"] for d in sr.destinations_for(row)}
    assert dests == {"youtube": "rtmps://a.rtmps.youtube.com/live2/abcd-efgh-ijkl",
                     "facebook": "rtmps://live-api-s.facebook.com:443/rtmp/FB-1234-0-AbCd?s_bl=1&a=xyz"}
    # Clearing a key switches that copy off.
    r = c.patch("/stream-relay/settings", json={"business_id": BIZ, "facebook_key": ""})
    assert r.json()["facebook"] == {"on": False, "saved": False}
    bad = c.patch("/stream-relay/settings", json={"business_id": BIZ, "youtube_key": "abc <script>"})
    assert bad.status_code == 400


# ─── the relay's side ────────────────────────────────────────────────


def test_relay_routes_fail_closed(db, ready, monkeypatch):
    c = _app()
    key = _key(c)
    assert c.post("/stream-relay/relay/verify", json={"key": key}).status_code == 401
    assert c.post("/stream-relay/relay/verify", json={"key": key}, headers={"x-relay-secret": "nope"}).status_code == 401
    monkeypatch.delenv("STREAM_RELAY_SECRET")
    assert c.post("/stream-relay/relay/verify", json={"key": key}, headers=RELAY).status_code == 503
    assert c.post("/stream-relay/relay/started", json={"key": key}, headers=RELAY).status_code == 503


def test_a_stream_opens_one_live_service_with_our_player(db, ready):
    c = _app()
    key = _key(c)
    c.patch("/stream-relay/settings", json={"business_id": BIZ, "youtube_key": "yt-key-1", "youtube_on": True})
    r = c.post("/stream-relay/relay/started", json={"key": key}, headers=RELAY)
    assert r.status_code == 200, r.text
    out = r.json()
    sid = out["session_id"]
    assert out["playlist_path"] == f"live/{BIZ}/{sid}/index.m3u8"
    assert out["destinations"] == [{"name": "youtube", "label": "YouTube",
                                    "url": "rtmps://a.rtmps.youtube.com/live2/yt-key-1"}]
    live = db.t["live_sessions"]
    assert len(live) == 1 and live[0]["stream_url"] == f"{MEDIA}/{out['playlist_path']}"
    assert db.t["told"] == [live[0]["id"]]
    # The relay restarting mid-service, or asking twice, gets the same one.
    again = c.post("/stream-relay/relay/started", json={"key": key}, headers=RELAY).json()
    assert again["session_id"] == sid and len(db.t["stream_sessions"]) == 1 and len(live) == 1
    # Members' player for that link is ours.
    assert live_router.stream_embed(live[0]["stream_url"]) == f"{MEDIA}/player.html?v=/{out['playlist_path']}"


def test_a_service_the_team_started_by_hand_is_left_alone(db, ready):
    c = _app()
    key = _key(c)
    db.t["live_sessions"].append({"id": "manual", "business_id": BIZ, "status": "live",
                                  "stream_url": "https://youtube.com/live/abc"})
    out = c.post("/stream-relay/relay/started", json={"key": key}, headers=RELAY).json()
    assert len(db.t["live_sessions"]) == 1 and db.t["live_sessions"][0]["stream_url"].startswith("https://youtube")
    assert db.t["stream_sessions"][0].get("live_session_id") is None and out["session_id"]


def test_a_service_that_ends_leaves_a_sermon_draft(db, ready):
    c = _app()
    key = _key(c)
    sid = c.post("/stream-relay/relay/started", json={"key": key}, headers=RELAY).json()["session_id"]
    r = c.post("/stream-relay/relay/ended", json={"session_id": sid, "duration_s": 5400, "bytes": 4_000_000_000},
               headers=RELAY)
    assert r.status_code == 200, r.text
    s = db.t["stream_sessions"][0]
    assert s["status"] == "ended" and s["duration_s"] == 5400 and s["sermon_id"] == r.json()["sermon_id"]
    assert db.t["live_sessions"][0]["status"] == "ended"
    sermon = db.t["sermons"][0]
    assert sermon["published"] is False and sermon["preached_on"] == "2026-10-18"
    assert sermon["title"] == "Service, October 18, 2026"
    assert sermon["video_url"] == f"{MEDIA}/live/{BIZ}/{sid}/index.m3u8"
    # Told twice, it is still one draft.
    again = c.post("/stream-relay/relay/ended", json={"session_id": sid, "duration_s": 5400}, headers=RELAY)
    assert again.json()["sermon_id"] == sermon["id"] and len(db.t["sermons"]) == 1


def test_a_sound_check_is_not_a_sermon(db, ready):
    c = _app()
    key = _key(c)
    sid = c.post("/stream-relay/relay/started", json={"key": key}, headers=RELAY).json()["session_id"]
    c.post("/stream-relay/relay/ended", json={"session_id": sid, "duration_s": 120}, headers=RELAY)
    assert db.t["sermons"] == [] and db.t["stream_sessions"][0]["status"] == "ended"
    assert c.post("/stream-relay/relay/ended", json={"session_id": "not-a-uuid"}, headers=RELAY).status_code == 400


def test_the_church_can_turn_sermon_drafts_off(db, ready):
    c = _app()
    key = _key(c)
    c.patch("/stream-relay/settings", json={"business_id": BIZ, "sermon_drafts": False})
    sid = c.post("/stream-relay/relay/started", json={"key": key}, headers=RELAY).json()["session_id"]
    c.post("/stream-relay/relay/ended", json={"session_id": sid, "duration_s": 5400}, headers=RELAY)
    assert db.t["sermons"] == []


# ─── playback ────────────────────────────────────────────────────────


def test_only_our_own_recordings_play_in_our_player(ready):
    ok = f"{MEDIA}/live/{BIZ}/00000000-0000-4000-8000-000000000001/index.m3u8"
    assert sermons_public.video_embed_src(ok) == (
        f"{MEDIA}/player.html?v=/live/{BIZ}/00000000-0000-4000-8000-000000000001/index.m3u8")
    assert sermons_public.video_embed_src(ok.replace("media.example.app", "evil.example")) == ""
    assert sermons_public.video_embed_src(f"{MEDIA}/live/../secrets/index.m3u8") == ""
    assert sermons_public.video_embed_src(ok.replace("https://", "http://")) == ""
    # YouTube still works as before.
    assert sermons_public.video_embed_src("https://youtu.be/abc123") == "https://www.youtube-nocookie.com/embed/abc123"


def test_without_a_media_host_nothing_is_ours(monkeypatch):
    monkeypatch.delenv("MEDIA_PUBLIC_BASE", raising=False)
    assert sr.is_media_playlist(f"{MEDIA}/live/{BIZ}/{BIZ}/index.m3u8") is None
