# __tests__/test_member_safety_officers.py
#
# Safety officers picked from a church's pastoral leaders (Kevin,
# 2026-10-20: yes to "pick from the Pastors and Elders you've already
# named"), working the Safety room from the Lead tab of their member app
# (member_portal_safety.py + messaging_router). Pins:
#   1. who can be picked: an ACTIVE senior/pastoral role only (not invited,
#      not a welcome lead); never someone who already has a team login or
#      is the owner, so nobody counts twice toward the two officers
#   2. the owner names and stands them down; two officers of either kind
#      before messaging can be on, and never fewer while it's on
#   3. only a named officer who still holds a pastoral role gets in; a
#      member who isn't sees nothing held
#   4. release / remove / close / pause act as the officer, recorded by
#      their contact id
#   5. opening a whole chat needs a reason, is logged with their contact,
#      and only then does the chat page open; its people are told
#   6. the preview never acts; a failed read never opens the room

import pathlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_portal as mp
import member_portal_messaging as mpm
import member_portal_safety as mps
import messaging_router as mr
from test_member_messaging import (ANA, BEN, BIZ, CARL, GRP, HOST, JSON, OFF1, OWNER, _send, _start,  # noqa: F401
                                   _tid, _User, env)


def _team(env, uid):
    """The team's side, as test_member_messaging's helper, but keeping this
    file's seats (one with a login email)."""
    from auth_supabase import require_user
    app = FastAPI()
    app.include_router(mr.router)
    app.dependency_overrides[require_user] = lambda: _User(uid)
    return TestClient(app)

ELDER = "00000000-0000-4000-8000-0000000000f1"     # Elder, active
EXEC = "00000000-0000-4000-8000-0000000000f2"      # Executive Pastor, still invited
GREETER = "00000000-0000-4000-8000-0000000000f3"   # Welcome lead, active (not pastoral)
STAFFER = "00000000-0000-4000-8000-0000000000f4"   # Associate Pastor with a team login
OWNERC = "00000000-0000-4000-8000-0000000000f5"    # the owner's own member record (Lead Pastor)


@pytest.fixture
def church(env, monkeypatch):
    t = env.t
    t["contacts"] += [
        {"id": ELDER, "business_id": BIZ, "name": "Ray Dunn", "birthdate": "1960-01-01", "email": "ray@example.com"},
        {"id": EXEC, "business_id": BIZ, "name": "Jess Mac", "birthdate": "1980-01-01", "email": "jess@example.com"},
        {"id": GREETER, "business_id": BIZ, "name": "Gail Ford", "birthdate": "1975-01-01", "email": "gail@example.com"},
        {"id": STAFFER, "business_id": BIZ, "name": "Sam Hart", "birthdate": "1977-01-01", "email": "sam@example.com"},
        {"id": OWNERC, "business_id": BIZ, "name": "Kev Pastor", "birthdate": "1970-01-01", "email": "owner@example.com"},
    ]
    t["church_role_defs"] = [
        {"id": f"def-{k}", "business_id": BIZ, "key": k, "title": title, "job": job, "status": "active", "sort": n,
         "created_at": "2026-10-17T00:00:00+00:00"}
        for n, (k, title, job) in enumerate([("pastor", "Lead Pastor", "senior"), ("elders", "Elders", "pastoral"),
                                             ("executive_pastor", "Executive Pastor", "pastoral"),
                                             ("associate_pastor", "Associate Pastor", "pastoral"),
                                             ("welcome_lead", "Welcome Team lead", "welcome")])]
    t["church_leader_roles"] = [
        {"id": "00000000-0000-4000-9999-000000000001", "scope": "", "invited_at": "2026-10-17T00:00:00+00:00", "business_id": BIZ, "contact_id": ELDER, "role": "elders", "status": "active"},
        {"id": "00000000-0000-4000-9999-000000000002", "scope": "", "invited_at": "2026-10-17T00:00:00+00:00", "business_id": BIZ, "contact_id": EXEC, "role": "executive_pastor", "status": "invited"},
        {"id": "00000000-0000-4000-9999-000000000003", "scope": "", "invited_at": "2026-10-17T00:00:00+00:00", "business_id": BIZ, "contact_id": GREETER, "role": "welcome_lead", "status": "active"},
        {"id": "00000000-0000-4000-9999-000000000004", "scope": "", "invited_at": "2026-10-17T00:00:00+00:00", "business_id": BIZ, "contact_id": STAFFER, "role": "associate_pastor", "status": "active"},
        {"id": "00000000-0000-4000-9999-000000000005", "scope": "", "invited_at": "2026-10-17T00:00:00+00:00", "business_id": BIZ, "contact_id": OWNERC, "role": "pastor", "status": "active"},
    ]
    t["business_users"] = [{"business_id": BIZ, "user_id": OFF1, "status": "active", "invited_email": "SAM@example.com",
                            "role": "admin"}]
    t["msg_member_officers"] = []
    monkeypatch.setattr(mr, "_owner_email", lambda owner_id: "owner@example.com")
    return env


def _officers_app(env, who):
    env.who["id"] = who
    app = FastAPI()
    app.include_router(mps.router)
    app.include_router(mpm.router)

    @app.get("/my/lead{rest:path}")
    async def _lead(rest: str, request: mp.Request):
        return await mp.serve(request, "/my/lead" + rest)

    @app.get("/my/messages{rest:path}")
    async def _msgs(rest: str, request: mp.Request):
        return await mp.serve(request, "/my/messages" + rest)
    return TestClient(app, base_url=f"https://{HOST}")


def _name_elder(church):
    r = _team(church, OWNER).post("/messaging/officers", json={"business_id": BIZ, "contact_id": ELDER, "officer": True})
    assert r.status_code == 200, r.text
    return r


def _held(church):
    """Ana writes something the check holds in her group's chat."""
    church.verdict = "harm"
    tid = _tid(_member_group(church))
    _send(church, ANA, tid, "something unkind")
    church.verdict = "ok"
    held = [m for m in church.t["msg_messages"] if m["status"] == "held"]
    assert held
    return tid, held[0]


def _member_group(church):
    import test_member_messaging as tmm
    return tmm._member(church, ANA).get(f"/my/messages/group/{GRP}", follow_redirects=False).headers["location"]


# ── 1. who can be picked ─────────────────────────────────────────────

def test_only_active_pastoral_leaders_without_a_login_are_offered(church):
    s = _team(church, OWNER).get("/messaging/settings", params={"business_id": BIZ}).json()
    offered = {p["contact_id"]: p for p in s["leaders"]}
    assert set(offered) == {ELDER}          # not invited, not a greeter, not a login, not the owner
    assert offered[ELDER]["title"] == "Elders" and offered[ELDER]["officer"] is False
    assert s["officer_count"] == 0


def test_someone_not_offered_cannot_be_named(church):
    for cid in (EXEC, GREETER, STAFFER, OWNERC, ANA):
        r = _team(church, OWNER).post("/messaging/officers", json={"business_id": BIZ, "contact_id": cid, "officer": True})
        assert r.status_code == 404, cid
    assert church.t["msg_member_officers"] == []


def test_only_the_owner_names_them(church):
    r = _team(church, OFF1).post("/messaging/officers", json={"business_id": BIZ, "contact_id": ELDER, "officer": True})
    assert r.status_code == 403 and church.t["msg_member_officers"] == []


# ── 2. two officers of either kind ───────────────────────────────────

def test_a_team_officer_and_an_elder_make_two(church):
    church.biz["settings"]["messaging"]["enabled"] = False
    owner = _team(church, OWNER)
    _name_elder(church)
    assert owner.patch("/messaging/settings", json={"business_id": BIZ, "enabled": True}).status_code == 409  # one
    assert owner.post("/messaging/officers", json={"business_id": BIZ, "user_id": OWNER, "officer": True}).status_code == 200
    assert owner.patch("/messaging/settings", json={"business_id": BIZ, "enabled": True}).status_code == 200  # two
    # On: neither can step down and leave one.
    assert owner.post("/messaging/officers", json={"business_id": BIZ, "contact_id": ELDER, "officer": False}).status_code == 409
    assert owner.post("/messaging/officers", json={"business_id": BIZ, "user_id": OWNER, "officer": False}).status_code == 409
    church.t["businesses"][0]["settings"]["messaging"]["enabled"] = False   # the row the router reads
    r = owner.post("/messaging/officers", json={"business_id": BIZ, "contact_id": ELDER, "officer": False})
    assert r.status_code == 200 and r.json()["member_officers"] == []


def test_an_officer_whose_role_ended_still_shows_to_be_stood_down(church):
    _name_elder(church)
    church.t["church_leader_roles"][0]["status"] = "declined"
    s = _team(church, OWNER).get("/messaging/settings", params={"business_id": BIZ}).json()
    gone = next(p for p in s["leaders"] if p["contact_id"] == ELDER)
    assert gone["officer"] is True and gone["title"] == "No pastoral role now"


# ── 3. who gets into the Safety room ────────────────────────────────

def test_a_named_elder_sees_what_was_held(church):
    _name_elder(church)
    _held(church)
    r = _officers_app(church, ELDER).get("/my/lead/safety")
    assert r.status_code == 200 and "something unkind" in r.text and "Release it" in r.text


def test_a_member_who_isnt_an_officer_sees_nothing_held(church):
    _held(church)
    for who in (ELDER, BEN):          # Ray isn't named yet; Ben is just a member
        r = _officers_app(church, who).get("/my/lead/safety")
        assert r.status_code == 403 and "something unkind" not in r.text


def test_an_officer_without_a_pastoral_role_is_shut_out(church):
    _name_elder(church)
    _held(church)
    church.t["church_leader_roles"][0]["status"] = "declined"
    r = _officers_app(church, ELDER).get("/my/lead/safety")
    assert r.status_code == 403 and "something unkind" not in r.text


def test_the_lead_page_door_shows_only_for_officers():
    assert mps.card(None) == ""
    assert "2 waiting" in mps.card(2) and 'href="/my/lead/safety"' in mps.card(2)


# ── 4. acting ────────────────────────────────────────────────────────

def test_release_and_remove_act_as_the_officer(church):
    _name_elder(church)
    tid, held = _held(church)
    c = _officers_app(church, ELDER)
    r = c.post("/my/lead/safety/act", data={"message_id": held["id"], "action": "remove"}, headers=JSON, follow_redirects=False)
    assert r.headers["location"] == "/my/lead/safety?done=removed"
    assert held["status"] == "removed" and held["removed_by"] == ELDER


def test_a_non_officer_cannot_act(church):
    tid, held = _held(church)
    r = _officers_app(church, BEN).post("/my/lead/safety/act", data={"message_id": held["id"], "action": "release"},
                                        headers=JSON, follow_redirects=False)
    assert "err=not_officer" in r.headers["location"] and held["status"] == "held"


def test_pause_turns_their_messaging_off(church):
    _name_elder(church)
    _officers_app(church, ELDER).post("/my/lead/safety/pause", data={"contact_id": ANA}, headers=JSON, follow_redirects=False)
    assert next(m for m in church.t["msg_members"] if m["contact_id"] == ANA)["enabled"] is False


# ── 5. opening a whole chat ──────────────────────────────────────────

def test_opening_a_whole_chat_needs_a_reason_and_is_logged(church):
    _name_elder(church)
    tid, _ = _held(church)
    c = _officers_app(church, ELDER)
    assert c.get(f"/my/lead/safety/chat/{tid}").status_code == 403            # no look logged yet
    r = c.post("/my/lead/safety/open", data={"thread_id": tid, "reason": ""}, headers=JSON, follow_redirects=False)
    assert "err=reason" in r.headers["location"] and church.t["msg_staff_views"] == []
    r = c.post("/my/lead/safety/open", data={"thread_id": tid, "reason": "A report about this chat"}, headers=JSON,
               follow_redirects=False)
    assert r.headers["location"] == f"/my/lead/safety/chat/{tid}"
    look = church.t["msg_staff_views"][0]
    assert look["contact_id"] == ELDER and look["user_id"] is None and look["reason"] == "A report about this chat"
    # The fake stamps rows on 2026-10-02; the page opens only within 30
    # minutes of the logged look.
    from datetime import datetime, timezone
    look["created_at"] = datetime.now(timezone.utc).isoformat()
    page = c.get(f"/my/lead/safety/chat/{tid}")
    assert page.status_code == 200 and "something unkind" in page.text
    # The people in that chat are told a safety officer reviewed it.
    import test_member_messaging as tmm
    assert "reviewed" in tmm._member(church, ANA).get(f"/my/messages/{tid}").text


# ── 6. preview, failed reads ─────────────────────────────────────────

def test_the_preview_never_acts(church):
    _name_elder(church)
    tid, held = _held(church)
    church.who["preview"] = True
    r = _officers_app(church, ELDER).post("/my/lead/safety/act", data={"message_id": held["id"], "action": "release"},
                                          headers=JSON, follow_redirects=False)
    assert "err=preview" in r.headers["location"] and held["status"] == "held"


def test_a_failed_read_never_opens_the_room(church, monkeypatch):
    _name_elder(church)
    _held(church)
    real = church.get

    def flaky(path):
        return None if path.lstrip("/").startswith("msg_member_officers") else real(path)
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", flaky)
    r = _officers_app(church, ELDER).get("/my/lead/safety")
    assert r.status_code == 503 and "something unkind" not in r.text
