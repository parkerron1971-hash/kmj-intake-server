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
        self.t["module_entries"] = [{"id": ENTRY, "business_id": BIZ, "status": "active", "data": {}}]
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
        if table == "rpc/live_add_hearts":                    # APPLY-2026-10-30-live-hearts.sql
            for s in self.t["live_sessions"]:
                if s["id"] == body["p_session"] and s["business_id"] == body["p_business"] and s["status"] == "live":
                    s["hearts"] = int(s.get("hearts") or 0) + max(1, min(int(body["p_n"]), 30))
                    return s["hearts"]
            return None
        self.n += 1
        row = {"id": f"00000000-0000-4000-8000-{self.n:012d}",
               "created_at": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self.n)).isoformat(),
               **body}
        if table == "live_chat":
            row.setdefault("hidden", False)                   # the column's default
        if table == "live_sessions":
            row.setdefault("chat_version", 0)
            row.setdefault("hearts", 0)
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
    # The tests above the live room's pin the page before it, which is
    # LIVE_ROOM=off (the way back); the room's own tests turn it on.
    monkeypatch.setenv("LIVE_ROOM", "off")
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


# ─── the live room (LIVE_ROOM, Kevin 2026-10-30) ─────────────────────
# Pins: it's everyone's by default (Kevin: "turn it on for everyone now"),
# owner keeps it to the owner's preview, and off is the page before it;
# the host's newest message is pinned; the count of who's
# here is never "0" for a failed read; "I'm here", prayer and hearts
# answer JSON so the video keeps playing; hearts are counted on the
# service (clamped), ride the poll, and the preview never adds any; Give
# opens the church's own funds and amounts, and only while it takes gifts.


def _room(monkeypatch, mode="on"):
    monkeypatch.setenv("LIVE_ROOM", mode)
    m = _member()
    m.app.include_router(mpc.router)
    return m


def test_the_room_is_everyones_and_the_switch_is_the_way_back(db, monkeypatch):
    _go_live(_team())
    monkeypatch.delenv("LIVE_ROOM", raising=False)
    m = _member()
    assert 'id="lv-room"' in m.get("/my/live").text                # on (the default): every member has the room
    monkeypatch.setenv("LIVE_ROOM", "owner")
    assert 'id="lv-room"' not in m.get("/my/live").text            # owner: members keep the page before it...
    db.who["preview"] = True
    assert 'id="lv-room"' in m.get("/my/live").text                # ...and only the owner's preview has the room
    monkeypatch.setenv("LIVE_ROOM", "off")
    assert 'id="lv-room"' not in m.get("/my/live").text
    monkeypatch.setenv("LIVE_ROOM", "sideways")                    # anything else is off
    assert mpl.room_mode() == "off"


def test_the_room_pins_the_host_and_counts_whos_here(db, monkeypatch):
    t = _team()
    sid = _go_live(t)
    m = _room(monkeypatch)
    t.post(f"/live/{sid}/chat", json={"business_id": BIZ, "body": "Welcome home, church!"})
    m.post("/my/live/chat", data={"body": "Good morning <b>church</b>"}, headers=JSON)
    r = m.post("/my/live/here", headers=JSON)
    assert r.status_code == 200 and r.json() == {"ok": True, "here": 1}
    page = m.get("/my/live").text
    assert 'id="lv-room"' in page and "youtube-nocookie.com/embed/abc123" in page
    assert 'id="lv-pin-b">Welcome home, church!</span>' in page            # the host's newest message, pinned
    assert '<b class="lv-who">First Light Church</b><span class="lv-tag">Host</span>' in page
    assert '<b class="lv-who">You</b> Good morning &lt;b&gt;church&lt;/b&gt;' in page
    assert "<b data-here-n>1</b> here" in page and "You&#x27;re here</span>" in page
    assert 'action="/my/live/here"' not in page                            # already here: no button
    assert 'name="body" value="Amen"' in page and 'aria-label="Send a heart"' in page
    assert ANA not in page and 'data-sheet="lv-give"' not in page          # no record ids; no gifts in the app yet
    assert '<a class="lv-pill" href="/my/give">' in page                   # Give still says how to give


def test_a_failed_count_is_hidden_never_zero(db, monkeypatch):
    _go_live(_team())
    m = _room(monkeypatch)
    monkeypatch.setattr(mpl, "here_count", lambda b, s: None)
    page = m.get("/my/live").text
    assert 'id="lv-herewrap" hidden' in page
    assert "here" not in m.get("/my/live/feed?v=0&n=1").json()


def test_a_closed_or_paused_chat_takes_no_replies_or_hearts(db, monkeypatch):
    t = _team()
    sid = _go_live(t)
    m = _room(monkeypatch)
    t.post(f"/live/{sid}/mute", json={"business_id": BIZ, "contact_id": ANA, "muted": True})
    page = m.get("/my/live").text
    assert "paused your chat" in page and 'id="lv-quick"' not in page and 'id="mb-compose"' not in page
    t.patch(f"/live/{sid}", json={"business_id": BIZ, "chat_open": False})
    assert "The chat is closed right now." in m.get("/my/live").text
    r = m.post("/my/live/heart", data={"n": "3"}, headers=JSON)
    assert r.status_code == 409 and db.t["live_sessions"][0]["hearts"] == 0


def test_hearts_are_counted_on_the_service_and_ride_the_poll(db, monkeypatch):
    _go_live(_team())
    m = _room(monkeypatch)
    assert m.post("/my/live/heart", data={"n": "5"}, headers=JSON).json() == {"ok": True, "hearts": 5}
    assert m.post("/my/live/heart", data={"n": "999"}, headers=JSON).json()["hearts"] == 35   # a batch is 30 at most
    assert m.post("/my/live/heart", data={"n": "lots"}, headers=JSON).json()["hearts"] == 36  # nonsense is one
    feed = m.get("/my/live/feed?v=0").json()
    assert feed["hearts"] == 36 and "here" not in feed                    # here only when asked
    same = m.get(f"/my/live/feed?v={feed['v']}&n=1").json()
    assert same["same"] is True and same["hearts"] == 36 and same["here"] == 0
    assert db.t["live_chat"] == []                                        # a heart is never a message
    db.who["preview"] = True
    r = m.post("/my/live/heart", data={"n": "4"}, headers=JSON)
    assert r.status_code == 403 and db.t["live_sessions"][0]["hearts"] == 36


def test_the_prayer_sheet_sends_privately_without_leaving(db, monkeypatch):
    _go_live(_team())
    m = _room(monkeypatch)
    sent = []
    monkeypatch.setattr(mpc, "load_me", lambda b, c: {"id": ANA, "name": "Ana Rivers"})
    monkeypatch.setattr(mpc, "save_prayer", lambda b, me, text, confidential, youth=False, wants_call=False:
                        sent.append((text, confidential, wants_call)) or True)
    page = m.get("/my/live").text
    assert 'id="lv-prayer-f" method="post" action="/my/prayer"' in page and 'name="wants_call"' in page
    r = m.post("/my/prayer", data={"request": "For my mother", "share": "pastors", "wants_call": "yes"}, headers=JSON)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert sent == [("For my mother", True, True)]
    assert m.post("/my/prayer", data={"request": " "}, headers=JSON).json()["error"].startswith("Write your prayer")
    r = m.post("/my/prayer", data={"request": "x"}, headers=ORIGIN, follow_redirects=False)
    assert r.status_code in (302, 303) and r.headers["location"].startswith("/my")   # the page's own form still redirects
    db.who["preview"] = True
    r = m.post("/my/prayer", data={"request": "x", "share": "team"}, headers=JSON)
    assert r.status_code == 403 and "preview" in r.json()["error"] and len(sent) == 2


def test_give_opens_the_churchs_own_funds_and_amounts(db, monkeypatch):
    _go_live(_team())
    m = _room(monkeypatch)
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: True)
    settings = {"member_portal": {"enabled": True},
                "giving": {"funds": ["Tithes & Offering", "Food Pantry"], "preset_amounts": [20, 40, 80, 150, 500]}}
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": {
        "id": BIZ, "name": "First Light Church", "type": "church", "owner_id": OWNER, "settings": settings,
        "stripe_account_id": None}, "site": {"slug": "first-light"}})
    page = m.get("/my/live").text
    assert 'data-sheet="lv-give"' in page and 'id="lv-give-f" method="get" action="/my/give"' in page
    assert 'name="fund" value="Food Pantry"' in page and 'value="Tithes &amp; Offering" checked' in page
    assert 'value="40" checked><span>$40</span>' in page and "$500" not in page   # the first four amounts


def test_names_keep_their_colour_on_every_phone():
    assert mpl.initials_of("Ana R.") == "AR" and mpl.initials_of("Cher") == "C" and mpl.initials_of("") == "?"
    # the page's script sums charCodeAt (UTF-16 units): an emoji counts as two
    name = "Ana \U0001F64F R."
    units = name.encode("utf-16-le")
    total = sum(int.from_bytes(units[i:i + 2], "little") for i in range(0, len(units), 2))
    assert total != sum(map(ord, name)) and mpl.family_of(name) == mpl.FAMILIES[total % 4]
    assert mpl.family_of("Ana R.") == mpl.FAMILIES[sum(map(ord, "Ana R.")) % 4]
