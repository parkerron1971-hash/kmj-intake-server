# __tests__/test_live.py
#
# Live (live_router.py + member_portal_live.py). Pins: one live service
# at a time; only managers run and moderate it; members chat by first
# name + last initial, never see each other's record ids, can't post
# links, can't post when paused or when the chat is closed; a hidden
# message leaves every phone's feed; "I'm here" counts online attendance
# once (and not on top of a check-in at the door); the owner's preview
# reads but never writes; between services the tab shows no dead stream.

import pathlib
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import live_router as lr
import member_portal as mp
import member_portal_church as mpc
import member_portal_live as mpl
from auth_supabase import require_user

BIZ = "11111111-1111-1111-1111-111111111111"
OWNER = "44444444-4444-4444-4444-444444444444"
ANA = "33333333-3333-3333-3333-333333333333"
BEN = "55555555-5555-5555-5555-555555555555"
ENTRY = "66666666-6666-6666-6666-666666666666"
HOST = "first-light.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}
JSON = {**ORIGIN, "accept": "application/json"}


class _User:
    def __init__(self, uid):
        self.id = uid


def _params(path):
    table, _, q = path.lstrip("/").partition("?")
    return table, urllib.parse.parse_qs(q, keep_blank_values=True)


class DB:
    """Just enough PostgREST: eq./is.null filters, desc order, limits,
    the one-live and one-check-in uniques, and the chat_version trigger."""

    def __init__(self):
        self.t = {k: [] for k in ("live_sessions", "live_chat", "live_mutes", "live_presence", "attendance")}
        self.t["businesses"] = [{"id": BIZ, "owner_id": OWNER}]
        self.t["contacts"] = [{"id": ANA, "business_id": BIZ, "name": "Ana Rivers"},
                              {"id": BEN, "business_id": BIZ, "name": "Ben Okafor"}]
        self.t["business_users"] = []
        self.n = 0
        self.fail = False

    def _match(self, row, q):
        for k, vals in q.items():
            if k in ("select", "order", "limit", "on_conflict"):
                continue
            v = vals[0]
            if v.startswith("eq."):
                if str(row.get(k)).lower() != v[3:].lower() and not (v[3:] in ("true", "false") and str(row.get(k)).lower() == v[3:]):
                    return False
            elif v == "is.null" and row.get(k) is not None:
                return False
            elif v.startswith("in.("):
                if str(row.get(k)) not in v[4:-1].split(","):
                    return False
        return True

    def get(self, path):
        if self.fail:
            return None
        table, q = _params(path)
        rows = [dict(r) for r in self.t.get(table, []) if self._match(r, q)]
        if q.get("order", [""])[0].endswith(".desc"):
            col = q["order"][0].split(".")[0]
            rows.sort(key=lambda r: str(r.get(col)), reverse=True)
        return rows[: int(q.get("limit", ["10000"])[0])]

    def post(self, path, body, prefer=None):
        table, q = _params(path)
        self.n += 1
        row = {"id": f"00000000-0000-4000-8000-{self.n:012d}",
               "created_at": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self.n)).isoformat(),
               **body}
        if table == "live_chat":
            row.setdefault("hidden", False)                   # the column's default
        if table == "live_sessions":
            row.setdefault("chat_version", 0)
            if any(s["business_id"] == row["business_id"] and s["status"] == "live" for s in self.t[table]):
                return None
        if table in ("live_presence", "live_mutes"):
            if any(r["session_id"] == row["session_id"] and r["contact_id"] == row["contact_id"] for r in self.t[table]):
                return [] if "ignore-duplicates" in (prefer or "") else None
        if table == "attendance":
            if any(r["entry_id"] == row["entry_id"] and r["contact_id"] == row["contact_id"] for r in self.t[table]):
                return None
        self.t.setdefault(table, []).append(row)
        if table == "live_chat":
            self._bump(row["session_id"])
        return [dict(row)]

    def patch(self, path, body):
        table, q = _params(path)
        hit = [r for r in self.t.get(table, []) if self._match(r, q)]
        for r in hit:
            r.update(body)
            if table == "live_chat":
                self._bump(r["session_id"])
        return [dict(r) for r in hit]

    def delete(self, path):
        table, q = _params(path)
        self.t[table] = [r for r in self.t.get(table, []) if not self._match(r, q)]
        return True

    def _bump(self, sid):
        for s in self.t["live_sessions"]:
            if s["id"] == sid:
                s["chat_version"] = int(s.get("chat_version") or 0) + 1


@pytest.fixture
def db(monkeypatch):
    d = DB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", d.delete)
    biz = {"id": BIZ, "name": "First Light Church", "type": "church", "owner_id": OWNER,
           "settings": {"member_portal": {"enabled": True}}, "stripe_account_id": None}
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": dict(biz), "site": {"slug": "first-light"}})
    d.who = {"me": {"id": ANA, "name": "Ana Rivers", "email": "ana@example.com"}, "preview": False}
    monkeypatch.setattr(mp, "_session_for", lambda req, church: (
        {"claims": {}, "people": [d.who["me"]], "me": d.who["me"], "preview": d.who["preview"]}))
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: True)
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: [])
    import member_portal_sermons as mps
    monkeypatch.setattr(mps, "load_library", lambda b: {"sermons": [], "series": []})
    return d


def _team(uid=OWNER):
    app = FastAPI()
    app.include_router(lr.router)
    app.dependency_overrides[require_user] = lambda: _User(uid)
    return TestClient(app)


def _member():
    app = FastAPI()
    app.include_router(mpl.router)

    @app.get("/my/live")
    async def _live(request: mp.Request):
        return await mp.serve(request, "/my/live")

    @app.get("/my/live/feed")
    async def _feed(request: mp.Request):
        return await mp.serve(request, "/my/live/feed")
    return TestClient(app, base_url=f"https://{HOST}")


def _go_live(t, url="https://www.youtube.com/watch?v=abc123", entry=ENTRY):
    r = t.post("/live/start", json={"business_id": BIZ, "title": "Sunday Worship", "stream_url": url, "entry_id": entry})
    assert r.status_code == 200, r.text
    return r.json()["live"]["id"]


# ─── pure ────────────────────────────────────────────────────────────


def test_names_links_and_streams():
    assert lr.author_for("Ana Rivers") == "Ana R." and lr.author_for("Cher") == "Cher" and lr.author_for("") == "A member"
    assert lr.has_link("see https://x.co") and lr.has_link("go to www.spam") and lr.has_link("visit cheap.com now")
    assert not lr.has_link("Amen, so good to be here")
    assert lr.stream_embed("https://www.youtube.com/channel/UCabcdefghij1234567890/live") == \
        "https://www.youtube.com/embed/live_stream?channel=UCabcdefghij1234567890"
    assert "youtube-nocookie.com/embed/abc123" in lr.stream_embed("https://youtu.be/abc123")
    assert lr.valid_stream_url("") and not lr.valid_stream_url("http://insecure.example") \
        and not lr.valid_stream_url('https://x.com/"><script>')


# ─── the team ────────────────────────────────────────────────────────


def test_one_live_service_at_a_time_and_only_managers_run_it(db):
    t = _team()
    _go_live(t)
    again = t.post("/live/start", json={"business_id": BIZ, "title": "Again", "stream_url": ""})
    assert again.status_code == 409
    assert _team(uid="99999999-9999-9999-9999-999999999999").post(
        "/live/start", json={"business_id": BIZ, "title": "x", "stream_url": ""}).status_code == 403
    assert t.post("/live/start", json={"business_id": BIZ, "title": "x", "stream_url": "http://nope"}).status_code in (400, 409)


def test_ending_turns_the_tab_back_to_between_services(db):
    t = _team()
    sid = _go_live(t)
    assert t.post(f"/live/{sid}/end", json={"business_id": BIZ}).status_code == 200
    assert lr.current(BIZ) == {}
    page = _member().get("/my/live").text
    assert "No service is live right now" in page and "<iframe" not in page


# ─── members ─────────────────────────────────────────────────────────


def test_members_watch_and_chat_by_first_name_and_initial(db):
    t = _team()
    _go_live(t)
    m = _member()
    page = m.get("/my/live").text
    assert "youtube-nocookie.com/embed/abc123" in page and "I'm here</button>" in page
    r = m.post("/my/live/chat", data={"body": "  Good morning   church! "}, headers=JSON)
    assert r.status_code == 200 and r.json() == {"ok": True}
    feed = m.get("/my/live/feed?v=0").json()
    assert feed["live"] and not feed["same"]
    assert feed["messages"] == [{"id": feed["messages"][0]["id"], "author": "Ana R.", "body": "Good morning church!",
                                 "host": False, "mine": True, "at": feed["messages"][0]["at"]}]
    assert ANA not in m.get("/my/live/feed?v=0").text                 # never a record id
    assert m.get(f"/my/live/feed?v={feed['v']}").json()["same"] is True


def test_no_links_no_posting_when_paused_or_closed(db):
    t = _team()
    sid = _go_live(t)
    m = _member()
    r = m.post("/my/live/chat", data={"body": "free stuff at spam.com"}, headers=JSON)
    assert r.status_code == 400 and "Links" in r.json()["error"]
    assert t.post(f"/live/{sid}/mute", json={"business_id": BIZ, "contact_id": ANA, "muted": True}).status_code == 200
    r = m.post("/my/live/chat", data={"body": "hello"}, headers=JSON)
    assert r.status_code == 403 and "paused" in r.json()["error"]
    assert "paused your chat" in m.get("/my/live").text
    t.post(f"/live/{sid}/mute", json={"business_id": BIZ, "contact_id": ANA, "muted": False})
    t.patch(f"/live/{sid}", json={"business_id": BIZ, "chat_open": False})
    r = m.post("/my/live/chat", data={"body": "hello"}, headers=JSON)
    assert r.status_code == 409 and "closed" in r.json()["error"]
    assert not db.t["live_chat"]


def test_a_hidden_message_leaves_every_feed(db):
    t = _team()
    sid = _go_live(t)
    m = _member()
    m.post("/my/live/chat", data={"body": "something unkind"}, headers=JSON)
    mid = db.t["live_chat"][0]["id"]
    assert t.post(f"/live/{sid}/messages/{mid}/hide", json={"business_id": BIZ, "hidden": True}).status_code == 200
    feed = m.get("/my/live/feed?v=0").json()
    assert feed["messages"] == []
    team_view = t.get(f"/live/{sid}/chat", params={"business_id": BIZ}).json()
    assert team_view["messages"][0]["hidden"] is True                 # the team still sees it, flagged


def test_the_host_posts_as_host(db):
    t = _team()
    sid = _go_live(t)
    assert t.post(f"/live/{sid}/chat", json={"business_id": BIZ, "body": "Welcome, family!"}).status_code == 200
    msg = _member().get("/my/live/feed?v=0").json()["messages"][0]
    assert msg["host"] is True and msg["author"] == "Host" and msg["mine"] is False


def test_im_here_counts_online_attendance_once(db):
    t = _team()
    sid = _go_live(t)
    m = _member()
    for _ in range(2):
        r = m.post("/my/live/here", headers=ORIGIN, follow_redirects=False)
        assert r.headers["location"] == "/my/live?done=here"
    assert len(db.t["live_presence"]) == 1
    assert [(a["contact_id"], a["method"], a["entry_id"]) for a in db.t["attendance"]] == [(ANA, "online", ENTRY)]
    assert "You're here</span>" in m.get("/my/live").text
    names = t.get(f"/live/{sid}/chat", params={"business_id": BIZ}).json()["here"]
    assert names == [{"contact_id": ANA, "name": "Ana Rivers"}]


def test_checked_in_at_the_door_is_not_counted_twice(db):
    t = _team()
    _go_live(t)
    db.t["attendance"].append({"id": "a1", "business_id": BIZ, "entry_id": ENTRY, "contact_id": ANA,
                               "name": "Ana Rivers", "method": "staff"})
    _member().post("/my/live/here", headers=ORIGIN, follow_redirects=False)
    assert [a["method"] for a in db.t["attendance"]] == ["staff"]


def test_the_owners_preview_reads_but_never_writes(db):
    t = _team()
    _go_live(t)
    db.who["preview"] = True
    m = _member()
    assert m.get("/my/live").status_code == 200
    r = m.post("/my/live/chat", data={"body": "hi"}, headers=JSON)
    assert r.status_code == 403 and "preview" in r.json()["error"]
    m.post("/my/live/here", headers=ORIGIN, follow_redirects=False)
    assert not db.t["live_chat"] and not db.t["live_presence"] and not db.t["attendance"]


def test_a_failed_read_is_said_never_off_air(db):
    _team()
    db.fail = True
    page = _member().get("/my/live")
    assert page.status_code == 503 and "couldn't load" in page.text and "No service is live" not in page.text
