# __tests__/test_group_live.py
#
# Live group meetings (member_portal_group_live.py). Pins: only a leader
# the church approved can start or end one; one at a time per group; a
# YOUTH group waits for a second approved adult before anyone else gets
# in; Broadcast puts only hosts on camera; only the group's people can
# join; joining counts group attendance once; a meeting whose video room
# is gone is ended, not offered; the owner's preview never joins; the
# video library is pinned with an integrity hash.

import base64
import json
import pathlib
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_portal as mp
import member_portal_church as mpc
import member_portal_group_live as mgl

BIZ = "11111111-1111-1111-1111-111111111111"
GRP = "22222222-2222-2222-2222-222222222222"
LEAD = "33333333-3333-3333-3333-333333333333"     # approved host
LEAD2 = "44444444-4444-4444-4444-444444444444"    # second approved host
PLAIN_LEAD = "55555555-5555-5555-5555-555555555555"  # leader, not approved to host
MEMBER = "66666666-6666-6666-6666-666666666666"
STRANGER = "77777777-7777-7777-7777-777777777777"
HOST = "first-light.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}
JSON = {**ORIGIN, "accept": "application/json"}
PEOPLE = {LEAD: "Marcus Hill", LEAD2: "Tasha Hill", PLAIN_LEAD: "Ray Moss", MEMBER: "Ana Rivers", STRANGER: "Zed Cole"}


def _params(path):
    table, _, q = path.lstrip("/").partition("?")
    return table, urllib.parse.parse_qs(q, keep_blank_values=True)


class DB:
    def __init__(self, youth=False):
        self.t = {
            "groups": [{"id": GRP, "business_id": BIZ, "name": "Tuesday Night Group", "youth": youth, "active": True}],
            "group_members": [
                {"group_id": GRP, "contact_id": LEAD, "business_id": BIZ, "role": "leader", "can_host_live": True},
                {"group_id": GRP, "contact_id": LEAD2, "business_id": BIZ, "role": "leader", "can_host_live": True},
                {"group_id": GRP, "contact_id": PLAIN_LEAD, "business_id": BIZ, "role": "leader", "can_host_live": False},
                {"group_id": GRP, "contact_id": MEMBER, "business_id": BIZ, "role": "member", "can_host_live": False},
            ],
            "group_live_sessions": [], "group_meetings": [], "group_meeting_attendance": [],
        }
        self.n = 0

    def _match(self, row, q):
        for k, vals in q.items():
            if k in ("select", "order", "limit", "on_conflict"):
                continue
            v = vals[0]
            if v.startswith("eq.") and str(row.get(k)).lower() != v[3:].lower():
                return False
            if v.startswith("in.(") and str(row.get(k)) not in v[4:-1].split(","):
                return False
        return True

    def get(self, path):
        table, q = _params(path)
        return [dict(r) for r in self.t.get(table, []) if self._match(r, q)]

    def post(self, path, body, prefer=None):
        table, q = _params(path)
        self.n += 1
        row = {"id": body.get("id") or f"00000000-0000-4000-8000-{self.n:012d}", **body}
        if table == "group_live_sessions":
            row.setdefault("started_at", datetime.now(timezone.utc).isoformat())
            if any(s["group_id"] == row["group_id"] and s["status"] in ("waiting", "live") for s in self.t[table]):
                return None
        if table == "group_meetings":
            if any(m["group_id"] == row["group_id"] and m["met_on"] == row["met_on"] for m in self.t[table]):
                return []
        if table == "group_meeting_attendance":
            if any(a["meeting_id"] == row["meeting_id"] and a["contact_id"] == row["contact_id"] for a in self.t[table]):
                return []
        self.t.setdefault(table, []).append(row)
        return [dict(row)]

    def patch(self, path, body):
        table, q = _params(path)
        status = q.get("status", [""])[0]
        hit = []
        for r in self.t.get(table, []):
            if not self._match(r, {k: v for k, v in q.items() if k != "status"}):
                continue
            if status.startswith("in.(") and r.get("status") not in status[4:-1].split(","):
                continue
            if status.startswith("eq.") and r.get("status") != status[3:]:
                continue
            r.update(body)
            hit.append(dict(r))
        return hit


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "devkey")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "devsecret-devsecret-devsecret-1234")
    d = DB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
    biz = {"id": BIZ, "name": "First Light Church", "type": "church",
           "settings": {"member_portal": {"enabled": True}}, "stripe_account_id": None}
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": dict(biz), "site": {"slug": "first-light"}})
    d.who = {"id": MEMBER, "preview": False}
    monkeypatch.setattr(mp, "_session_for", lambda req, church: {
        "claims": {}, "people": [{"id": d.who["id"], "name": PEOPLE[d.who["id"]]}],
        "me": {"id": d.who["id"], "name": PEOPLE[d.who["id"]]}, "preview": d.who["preview"]})
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: True)
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    d.rooms, d.closed = set(), []

    async def create_room(room):
        d.rooms.add(room)

    async def room_open(room):
        return room in d.rooms

    async def close_room(room):
        d.closed.append(room)
        d.rooms.discard(room)
    monkeypatch.setattr(mgl, "create_room", create_room)
    monkeypatch.setattr(mgl, "room_open", room_open)
    monkeypatch.setattr(mgl, "close_room", close_room)
    return d


def _client():
    app = FastAPI()
    app.include_router(mgl.router)

    @app.get("/my/groups/live/{sid}")
    async def _page(sid: str, request: mp.Request):
        return await mp.serve(request, f"/my/groups/live/{sid}")
    return TestClient(app, base_url=f"https://{HOST}")


def _as(env, who):
    env.who["id"] = who
    return _client()


def _start(env, who=LEAD, mode="meeting"):
    return _as(env, who).post("/my/groups/live/start", data={"group_id": GRP, "mode": mode},
                              headers=ORIGIN, follow_redirects=False)


def _grants(token):
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["video"]


def _sid(env):
    return env.t["group_live_sessions"][-1]["id"]


def test_only_an_approved_leader_can_start(env):
    for who in (MEMBER, PLAIN_LEAD):
        r = _start(env, who)
        assert r.headers["location"] == "/my/groups?err=not_host"
    assert not env.t["group_live_sessions"] and not env.rooms
    r = _start(env, LEAD)
    sid = _sid(env)
    assert r.headers["location"] == f"/my/groups/live/{sid}"
    assert env.t["group_live_sessions"][0]["status"] == "live" and f"grp-{sid}" in env.rooms


def test_one_meeting_at_a_time(env):
    _start(env)
    sid = _sid(env)
    r = _start(env, LEAD2)
    assert r.headers["location"] == f"/my/groups/live/{sid}" and len(env.t["group_live_sessions"]) == 1


def test_a_youth_group_waits_for_a_second_approved_adult(env):
    env.t["groups"][0]["youth"] = True
    _start(env, LEAD)
    sid = _sid(env)
    assert env.t["group_live_sessions"][0]["status"] == "waiting"
    member = _as(env, MEMBER).post(f"/my/groups/live/{sid}/token", headers=JSON)
    assert member.status_code == 409 and "second adult" in member.json()["error"]
    assert "Waiting" in _as(env, MEMBER).get(f"/my/groups/live/{sid}").text
    assert _as(env, LEAD).post(f"/my/groups/live/{sid}/token", headers=JSON).status_code == 200
    assert env.t["group_live_sessions"][0]["status"] == "waiting"           # the same adult again: still waiting
    assert _as(env, PLAIN_LEAD).post(f"/my/groups/live/{sid}/token", headers=JSON).status_code == 409
    assert _as(env, LEAD2).post(f"/my/groups/live/{sid}/token", headers=JSON).status_code == 200
    s = env.t["group_live_sessions"][0]
    assert s["status"] == "live" and s["second_adult"] == LEAD2
    assert _as(env, MEMBER).post(f"/my/groups/live/{sid}/token", headers=JSON).status_code == 200


def test_broadcast_puts_only_hosts_on_camera(env):
    _start(env, LEAD, "broadcast")
    sid = _sid(env)
    host = _as(env, LEAD).post(f"/my/groups/live/{sid}/token", headers=JSON).json()
    member = _as(env, MEMBER).post(f"/my/groups/live/{sid}/token", headers=JSON).json()
    assert host["publish"] is True and _grants(host["token"])["canPublish"] is True
    assert member["publish"] is False and not _grants(member["token"]).get("canPublish")
    assert _grants(member["token"])["room"] == f"grp-{sid}"


def test_only_the_groups_people_can_join(env):
    _start(env)
    sid = _sid(env)
    r = _as(env, STRANGER).post(f"/my/groups/live/{sid}/token", headers=JSON)
    assert r.status_code == 403 and "token" not in r.json()


def test_joining_counts_group_attendance_once(env):
    _start(env)
    sid = _sid(env)
    for _ in range(2):
        assert _as(env, MEMBER).post(f"/my/groups/live/{sid}/token", headers=JSON).status_code == 200
    assert len(env.t["group_meetings"]) == 1
    assert [a["contact_id"] for a in env.t["group_meeting_attendance"]] == [MEMBER]


def test_a_meeting_whose_room_is_gone_is_ended_not_offered(env):
    _start(env)
    sid = _sid(env)
    env.rooms.clear()
    r = _as(env, MEMBER).post(f"/my/groups/live/{sid}/token", headers=JSON)
    assert r.status_code == 410 and env.t["group_live_sessions"][0]["status"] == "ended"


def test_only_an_approved_leader_ends_it_for_everyone(env):
    _start(env)
    sid = _sid(env)
    r = _as(env, MEMBER).post(f"/my/groups/live/{sid}/end", headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my/groups?err=not_host" and env.t["group_live_sessions"][0]["status"] == "live"
    r = _as(env, LEAD2).post(f"/my/groups/live/{sid}/end", headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my/groups?done=meeting_ended"
    assert env.t["group_live_sessions"][0]["status"] == "ended" and env.closed == [f"grp-{sid}"]
    assert "This meeting has ended" in _as(env, MEMBER).get(f"/my/groups/live/{sid}").text


def test_the_owners_preview_never_joins(env):
    _start(env)
    sid = _sid(env)
    env.who["preview"] = True
    r = _as(env, MEMBER).post(f"/my/groups/live/{sid}/token", headers=JSON)
    assert r.status_code == 403 and "preview" in r.json()["error"]
    r = _as(env, LEAD).post("/my/groups/live/start", data={"group_id": GRP}, headers=ORIGIN, follow_redirects=False)
    assert r.headers["location"] == "/my/groups?err=preview"


def test_the_video_library_is_pinned_with_its_hash(env):
    _start(env)
    page = _as(env, MEMBER).get(f"/my/groups/live/{_sid(env)}").text
    assert f'src="{mgl.LIVEKIT_JS}" integrity="{mgl.LIVEKIT_SRI}" crossorigin="anonymous"' in page
    assert "@2.22.3/" in mgl.LIVEKIT_JS and mgl.LIVEKIT_SRI.startswith("sha384-")
    assert "aren't recorded" in page


def test_the_groups_page_offers_start_to_hosts_and_join_to_everyone(env):
    host_card = mpc._group_card({"id": GRP, "name": "Tuesday Night Group", "kind": "Small group", "role": "leader",
                                 "host": True, "live": None, "leaders": []}, "leave", _pal())
    assert 'action="/my/groups/live/start"' in host_card and "Broadcast" in host_card
    member_card = mpc._group_card({"id": GRP, "name": "Tuesday Night Group", "kind": "Small group", "role": "member",
                                   "host": False, "live": None, "leaders": []}, "leave", _pal())
    assert "/my/groups/live/start" not in member_card
    live_card = mpc._group_card({"id": GRP, "name": "Tuesday Night Group", "kind": "Small group", "role": "member",
                                 "host": False, "live": {"id": "s1", "status": "live"}, "leaders": []}, "leave", _pal())
    assert 'href="/my/groups/live/s1"' in live_card and "Join live meeting" in live_card


def _pal():
    import member_app_ui as ui
    return ui.palette({"id": BIZ, "settings": {}}, {"accent": "#334155"})


# ─── staff drop-in (group_live_router.py) ────────────────────────────

OWNER_USER = "88888888-8888-8888-8888-888888888888"


class _User:
    def __init__(self, uid):
        self.id, self.email = uid, "pastor@example.com"


def _team(env, uid=OWNER_USER):
    import group_live_router as glr
    from auth_supabase import require_user
    env.t["businesses"] = [{"id": BIZ, "owner_id": OWNER_USER}]
    env.t["business_users"] = []
    app = FastAPI()
    app.include_router(glr.router)
    app.dependency_overrides[require_user] = lambda: _User(uid)
    return TestClient(app)


def test_staff_drop_in_as_church_staff_without_opening_a_youth_meeting(env):
    env.t["groups"][0]["youth"] = True
    _start(env, LEAD)
    sid = _sid(env)
    t = _team(env)
    assert [m["id"] for m in t.get("/group-live", params={"business_id": BIZ}).json()["meetings"]] == [sid]
    r = t.post(f"/group-live/{sid}/drop-in", json={"business_id": BIZ})
    assert r.status_code == 200
    payload = r.json()["token"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["sub"] == f"staff_{OWNER_USER}" and claims["name"] == "Church staff"
    assert "pastor@example.com" not in json.dumps(claims)
    assert env.t["group_live_sessions"][0]["status"] == "waiting"       # only the group's approved leaders open it
    assert env.t["group_meeting_attendance"] == []                      # staff aren't group attendance


def test_only_managers_drop_in_or_end(env):
    _start(env, LEAD)
    sid = _sid(env)
    stranger = _team(env, uid="99999999-9999-9999-9999-999999999999")
    assert stranger.post(f"/group-live/{sid}/drop-in", json={"business_id": BIZ}).status_code == 403
    assert stranger.post(f"/group-live/{sid}/end", json={"business_id": BIZ}).status_code == 403
    assert env.t["group_live_sessions"][0]["status"] == "live"


def test_staff_can_end_a_meeting_for_everyone(env):
    _start(env, LEAD)
    sid = _sid(env)
    assert _team(env).post(f"/group-live/{sid}/end", json={"business_id": BIZ}).status_code == 200
    assert env.t["group_live_sessions"][0]["status"] == "ended" and env.closed == [f"grp-{sid}"]
