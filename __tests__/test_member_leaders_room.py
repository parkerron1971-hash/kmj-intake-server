# __tests__/test_member_leaders_room.py
#
# All group leaders: one room per church where everyone who leads a group
# and the church's pastors talk together (Kevin, 2026-10-20: "yes all group
# leaders room would be great"; member_portal_groups /my/groups/leaders on
# member_portal_messaging's thread kind "leaders"). Pins:
#   1. who's in it, read live: leaders of ACTIVE groups and ACTIVE pastoral
#      roles; never a plain member, an invited pastor, or a non-pastoral role
#   2. the room's page for the people in it; "not here" for anyone else
#   3. it's a real chat: sending, replies and reactions work; a message is
#      checked like any other
#   4. Messages lists it for the people in it and opens it on its page
#   5. doors on Connect and on the Lead page, only for the people in it and
#      only once messaging is on (nothing dead-ends)
#   6. its push says where it's from and opens the room

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
from test_member_messaging import ANA, BEN, BIZ, CARL, GRP, HOST, JSON, TEEN, YOUTH, env  # noqa: F401
from test_member_safety_officers import ELDER, EXEC, GREETER, OWNERC, STAFFER, church  # noqa: F401

ROOM = "/my/groups/leaders"


@pytest.fixture
def room(church):
    # The pastors use the member app too.
    church.t["msg_members"] += [{"contact_id": c, "business_id": BIZ, "enabled": True,
                                 "guidelines_at": "2026-10-01T00:00:00+00:00"} for c in (ELDER, GREETER)]
    church.t.setdefault("msg_reactions", [])
    return church


def _app(env, who):
    env.who["id"] = who
    app = FastAPI()
    app.include_router(mpm.router)
    app.include_router(mps.router)

    @app.get("/my{rest:path}")
    async def _any(rest: str, request: mp.Request):
        return await mp.serve(request, "/my" + rest)
    return TestClient(app, base_url=f"https://{HOST}")


def _tid(env):
    return mpm.ensure_leaders_thread(BIZ)


# ── 1. who's in it ───────────────────────────────────────────────────

def test_leaders_of_active_groups_and_active_pastors_are_in(room):
    ids = {p["contact_id"] for p in mpm.leaders_room_people(BIZ)}
    assert ids == {BEN, CARL, ELDER, STAFFER, OWNERC}
    assert not ids & {ANA, TEEN, EXEC, GREETER}      # a member, a teen, an invited pastor, a welcome lead


def test_leading_an_archived_group_doesnt_count(room):
    next(g for g in room.t["groups"] if g["id"] == YOUTH)["active"] = False
    assert CARL not in {p["contact_id"] for p in mpm.leaders_room_people(BIZ)}


def test_a_failed_read_is_none_not_empty(room, monkeypatch):
    import sb_clients
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: None if p.startswith("/church_leader_roles") else real(p))
    assert mpm.leaders_room_people(BIZ) is None
    assert mpm.in_leaders_room(BIZ, BEN) is None


# ── 2. the page ──────────────────────────────────────────────────────

def test_the_room_opens_for_a_group_leader(room):
    r = _app(room, BEN).get(ROOM)
    assert r.status_code == 200 and "All group leaders" in r.text and 'id="gc-compose"' in r.text
    assert "5 people" in r.text
    assert room.t["msg_threads"][0]["kind"] == "leaders"     # made on first visit, one per church
    _app(room, ELDER).get(ROOM)
    assert len([t for t in room.t["msg_threads"] if t["kind"] == "leaders"]) == 1


def test_anyone_else_is_told_its_for_leaders(room):
    for who in (ANA, GREETER):
        r = _app(room, who).get(ROOM)
        assert r.status_code == 404 and "This room is for" in r.text and 'id="gc-compose"' not in r.text


def test_with_messaging_off_the_room_says_so(room):
    room.biz["settings"]["messaging"]["enabled"] = False
    assert "turns on messaging" in _app(room, BEN).get(ROOM).text


# ── 3. a real chat ───────────────────────────────────────────────────

def test_a_pastor_and_a_leader_talk(room):
    tid = _tid(room)
    c = _app(room, ELDER)
    c.post(f"/my/messages/{tid}/send", data={"body": "Thank you for shepherding this week"}, headers=JSON)
    m = next(x for x in room.t["msg_messages"] if x["body"] == "Thank you for shepherding this week")
    assert m["status"] == "delivered"
    b = _app(room, BEN)
    assert b.post(f"/my/messages/{tid}/send", data={"body": "Amen, thank you", "reply_to": m["id"]}, headers=JSON).json()["ok"]
    assert b.post(f"/my/messages/{tid}/react", data={"message_id": m["id"], "kind": "amen"}, headers=JSON).json() == {"ok": True, "on": True}
    page = b.get(ROOM).text
    assert "Thank you for shepherding this week" in page and 'class="gc-q"' in page and "Ray Dunn" in page


def test_someone_outside_cannot_write_or_react(room):
    tid = _tid(room)
    _app(room, BEN).post(f"/my/messages/{tid}/send", data={"body": "leaders only"}, headers=JSON)
    m = next(x for x in room.t["msg_messages"] if x["body"] == "leaders only")
    a = _app(room, ANA)
    assert a.post(f"/my/messages/{tid}/send", data={"body": "can I?"}, headers=JSON).status_code in (403, 404)
    assert a.post(f"/my/messages/{tid}/react", data={"message_id": m["id"], "kind": "love"}, headers=JSON).status_code == 404
    assert not any(x["body"] == "can I?" for x in room.t["msg_messages"]) and room.t["msg_reactions"] == []


def test_a_send_from_the_room_comes_back_to_it(room):
    tid = _tid(room)
    r = _app(room, BEN).post(f"/my/messages/{tid}/send", data={"body": "hello", "back": ROOM},
                             headers={"Origin": f"https://{HOST}"}, follow_redirects=False)
    assert r.headers["location"].startswith(ROOM)


# ── 4. Messages ──────────────────────────────────────────────────────

def test_messages_lists_it_for_the_people_in_it_and_opens_the_page(room):
    tid = _tid(room)
    _app(room, ELDER).post(f"/my/messages/{tid}/send", data={"body": "Leaders meeting Saturday"}, headers=JSON)
    chats, _ = mpm.inbox_rows(BIZ, BEN)
    row = next(c for c in chats if c["id"] == tid)
    assert row["title"] == "All group leaders" and row["unread"] == 1
    assert not any(c["id"] == tid for c in mpm.inbox_rows(BIZ, ANA)[0])
    r = _app(room, BEN).get(f"/my/messages/{tid}", follow_redirects=False)
    assert r.headers["location"] == ROOM


# ── 5. doors ─────────────────────────────────────────────────────────

def test_connect_shows_the_door_only_to_the_people_in_it(room):
    assert 'href="/my/groups/leaders"' in _app(room, BEN).get("/my/groups").text
    assert 'href="/my/groups/leaders"' not in _app(room, ANA).get("/my/groups").text
    room.biz["settings"]["messaging"]["enabled"] = False
    assert 'href="/my/groups/leaders"' not in _app(room, BEN).get("/my/groups").text


def test_the_lead_page_has_the_door_for_a_pastor(room):
    assert 'href="/my/groups/leaders"' in _app(room, ELDER).get("/my/lead").text
    assert 'href="/my/groups/leaders"' not in _app(room, GREETER).get("/my/lead").text   # a role, but not pastoral


# ── 6. its push ──────────────────────────────────────────────────────

def test_its_push_names_the_room_and_opens_it(room, monkeypatch):
    import member_push as mpu
    sent = []
    monkeypatch.setattr(mpu, "church_kinds", lambda s: {"messages"})
    monkeypatch.setattr(mpu, "_later", lambda fn, *a: fn(*a))
    monkeypatch.setattr(mpu, "send", lambda biz, kind, **k: sent.append(k))
    t = {"id": _tid(room), "kind": "leaders", "group_id": None}
    acc = mpm.chat_access(BIZ, t, BEN)
    mpu.tell_chat(room.biz, t, acc, BEN)
    assert sent and sent[0]["title"] == "New message in All group leaders" and sent[0]["url"] == ROOM
    assert BEN not in sent[0]["contact_ids"] and ELDER in sent[0]["contact_ids"]
