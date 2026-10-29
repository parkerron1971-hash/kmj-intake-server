# __tests__/test_member_group_chat.py
#
# A group's chat inside the group (member_portal_groups Chat tab +
# member_portal_messaging, 2026-10-20: "there is no area where people can
# communicate like a chat"). Pins:
#   1. a group's chat opens inside the group for its members; a linked
#      parent still reads it read-only in Messages
#   2. the page says why someone can't chat yet (messaging off, Board-only,
#      no birthdate, guidelines) instead of a dead end
#   3. a reply quotes a delivered message in the SAME chat, never another's
#   4. Love / Praying / Amen: one of each per person, pressing again takes it
#      back; only the chat's members react
#   5. a leader of THAT group takes a message down: it's removed (not
#      deleted), the safety officers get a report, members stop seeing it
#   6. the office's switches hold: Board-only refuses a send; leaders-only
#      refuses a member and lets a leader write
#   7. a "back" field returns only to a group's chat page

import pathlib
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_portal as mp
import member_portal_messaging as mpm
from test_member_messaging import (ANA, BEN, BIZ, CARL, GRP, HOST, JSON, ORIGIN, PARENT, TEEN, YOUTH, _group_tid,  # noqa: F401
                                   _member, _send, env)


@pytest.fixture
def church(env):
    for g in env.t["groups"]:
        g.update(active=True, kind="small_group", description="", meets="Thursdays", location="", capacity=None,
                 open_to_join=True, join_mode="ask", name_display="full", youth=False, chat_on=True, chat_writers="all")
    env.t.setdefault("msg_reactions", [])
    return env


def _page(env, who, path, **kw):
    env.who["id"] = who
    app = FastAPI()
    app.include_router(mpm.router)

    @app.get("/my/groups{rest:path}")
    async def _groups(rest: str, request: mp.Request):
        return await mp.serve(request, "/my/groups" + rest)
    return TestClient(app, base_url=f"https://{HOST}").get(path, **kw)


def _post(env, who, path, data, json=True):
    env.who["id"] = who
    app = FastAPI()
    app.include_router(mpm.router)
    return TestClient(app, base_url=f"https://{HOST}").post(path, data=data, headers=JSON if json else ORIGIN,
                                                            follow_redirects=False)


def _msg(env, body):
    return next(m for m in env.t["msg_messages"] if m["body"] == body)


# ── 1. where the chat lives ──────────────────────────────────────────

def test_the_groups_chat_opens_inside_the_group(church):
    tid = _group_tid(church, ANA, GRP)
    r = _member(church, ANA).get(f"/my/messages/{tid}", follow_redirects=False)
    assert r.headers["location"] == f"/my/groups/{GRP}/chat"
    _send(church, BEN, tid, "Welcome, everyone")
    page = _page(church, ANA, f"/my/groups/{GRP}/chat")
    assert page.status_code == 200 and "Welcome, everyone" in page.text and 'id="gc-compose"' in page.text
    assert "Ben Cole" in page.text          # the group shows full names (its leader's choice)


def test_a_linked_parent_still_reads_in_messages(church):
    tid = _group_tid(church, TEEN, YOUTH)
    r = _member(church, PARENT).get(f"/my/messages/{tid}", follow_redirects=False)
    assert r.status_code == 200 and "as their parent" in r.text


# ── 2. why not yet ───────────────────────────────────────────────────

def test_the_page_says_why_not_yet(church):
    church.biz["settings"]["messaging"]["enabled"] = False
    assert "turns on messaging" in _page(church, ANA, f"/my/groups/{GRP}/chat").text
    church.biz["settings"]["messaging"]["enabled"] = True
    church.t["groups"][0]["chat_on"] = False
    assert "Board only" in _page(church, ANA, f"/my/groups/{GRP}/chat").text
    church.t["groups"][0]["chat_on"] = True
    next(m for m in church.t["msg_members"] if m["contact_id"] == ANA)["guidelines_at"] = None
    page = _page(church, ANA, f"/my/groups/{GRP}/chat").text
    assert "I agree" in page and f'value="/my/groups/{GRP}/chat"' in page
    r = _post(church, ANA, "/my/messages/guidelines", {"back": f"/my/groups/{GRP}/chat"}, json=False)
    assert r.headers["location"].startswith(f"/my/groups/{GRP}/chat")


# ── 3. replies ───────────────────────────────────────────────────────

def test_a_reply_quotes_a_message_in_the_same_chat(church):
    tid = _group_tid(church, ANA, GRP)
    _send(church, BEN, tid, "Who has the slow cooker?")
    first = _msg(church, "Who has the slow cooker?")
    _post(church, ANA, f"/my/messages/{tid}/send", {"body": "I do", "reply_to": first["id"]})
    assert _msg(church, "I do")["reply_to"] == first["id"]
    page = _page(church, ANA, f"/my/groups/{GRP}/chat").text
    assert 'class="gc-q"' in page and "Who has the slow cooker?" in page


def test_a_reply_to_another_chat_is_dropped(church):
    other = _group_tid(church, TEEN, YOUTH)
    church.t["group_members"].append({"group_id": YOUTH, "contact_id": BEN, "business_id": BIZ, "role": "leader"})
    _send(church, BEN, other, "youth news")
    tid = _group_tid(church, ANA, GRP)
    _post(church, ANA, f"/my/messages/{tid}/send", {"body": "hello", "reply_to": _msg(church, "youth news")["id"]})
    assert not _msg(church, "hello").get("reply_to")


# ── 4. reactions ─────────────────────────────────────────────────────

def test_reactions_toggle_one_of_each(church):
    tid = _group_tid(church, ANA, GRP)
    _send(church, BEN, tid, "Pray for my mom")
    mid = _msg(church, "Pray for my mom")["id"]
    for _ in range(2):
        _post(church, ANA, f"/my/messages/{tid}/react", {"message_id": mid, "kind": "pray"})
    assert church.t["msg_reactions"] == []          # pressed twice: taken back
    r = _post(church, ANA, f"/my/messages/{tid}/react", {"message_id": mid, "kind": "pray"})
    assert r.json() == {"ok": True, "on": True}
    assert [(x["contact_id"], x["kind"]) for x in church.t["msg_reactions"]] == [(ANA, "pray")]
    assert _post(church, ANA, f"/my/messages/{tid}/react", {"message_id": mid, "kind": "fire"}).status_code == 400


def test_only_the_chats_members_react(church):
    tid = _group_tid(church, ANA, GRP)
    _send(church, BEN, tid, "hello")
    r = _post(church, CARL, f"/my/messages/{tid}/react", {"message_id": _msg(church, "hello")["id"], "kind": "love"})
    assert r.status_code == 404 and church.t["msg_reactions"] == []


# ── 5. a leader takes one down ───────────────────────────────────────

def test_a_leader_takes_a_message_down_and_the_officers_are_told(church):
    tid = _group_tid(church, ANA, GRP)
    _send(church, ANA, tid, "an unkind thing")
    m = _msg(church, "an unkind thing")
    assert _post(church, ANA, f"/my/messages/{tid}/hide", {"message_id": m["id"]}).status_code == 403   # Ana isn't a leader
    assert m["status"] == "delivered"
    r = _post(church, BEN, f"/my/messages/{tid}/hide", {"message_id": m["id"]})                       # Ben leads GRP
    assert r.json()["ok"] and m["status"] == "removed" and m["removed_by"] == BEN
    rep = church.t["msg_reports"][-1]
    assert rep["message_id"] == m["id"] and rep["reporter_contact_id"] == BEN and "leader" in rep["reason"]
    assert "an unkind thing" not in _page(church, ANA, f"/my/groups/{GRP}/chat").text


def test_if_the_officers_cant_be_told_nothing_comes_down(church, monkeypatch):
    tid = _group_tid(church, ANA, GRP)
    _send(church, ANA, tid, "hello all")
    m = _msg(church, "hello all")
    real = mpm.sb_clients.sb_post_as_service
    monkeypatch.setattr(mpm.sb_clients, "sb_post_as_service",
                        lambda path, *a, **k: None if path.startswith("/msg_reports") else real(path, *a, **k))
    r = _post(church, BEN, f"/my/messages/{tid}/hide", {"message_id": m["id"]})
    assert r.status_code == 503 and m["status"] == "delivered" and not m.get("removed_by")


def test_a_leader_of_another_group_cannot_take_one_down(church):
    tid = _group_tid(church, ANA, GRP)
    _send(church, ANA, tid, "hi")
    church.t["group_members"].append({"group_id": GRP, "contact_id": CARL, "business_id": BIZ, "role": "member"})
    r = _post(church, CARL, f"/my/messages/{tid}/hide", {"message_id": _msg(church, "hi")["id"]})   # Carl leads YOUTH
    assert r.status_code == 403 and _msg(church, "hi")["status"] == "delivered"


# ── 6. the office's switches ─────────────────────────────────────────

def test_board_only_refuses_a_send(church):
    tid = _group_tid(church, ANA, GRP)
    church.t["groups"][0]["chat_on"] = False
    r = _send(church, ANA, tid, "hello")
    assert r.status_code == 403 and "Board only" in r.json()["error"]


def test_leaders_only_lets_a_leader_write_and_not_a_member(church):
    tid = _group_tid(church, ANA, GRP)
    church.t["groups"][0]["chat_writers"] = "leaders"
    r = _send(church, ANA, tid, "can I?")
    assert r.status_code == 403 and "leaders write" in r.json()["error"]
    assert _send(church, BEN, tid, "yes, from the leader").json()["ok"]
    assert 'id="gc-compose"' not in _page(church, ANA, f"/my/groups/{GRP}/chat").text


# ── 7. coming back ───────────────────────────────────────────────────

def test_back_returns_only_to_a_groups_chat(church):
    tid = _group_tid(church, ANA, GRP)
    r = _post(church, ANA, f"/my/messages/{tid}/send", {"body": "one", "back": f"/my/groups/{GRP}/chat"}, json=False)
    assert r.headers["location"].startswith(f"/my/groups/{GRP}/chat")
    r = _post(church, ANA, f"/my/messages/{tid}/send", {"body": "two", "back": "https://evil.example/"}, json=False)
    assert r.headers["location"].startswith(f"/my/messages/{tid}")


# ── 8. the church's export ───────────────────────────────────────────

def test_reactions_are_in_the_export_before_their_messages_and_never_reimported():
    import account_lifecycle as al
    t = al.BUSINESS_CHILD_TABLES
    assert t.index("msg_reactions") < t.index("msg_messages")
    assert "msg_reactions" in al._IMPORT_SKIP
