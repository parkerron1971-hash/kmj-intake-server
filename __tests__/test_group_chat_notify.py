# __tests__/test_group_chat_notify.py
#
# How each person hears about a group's chat (group_chat_notify.py; the
# approved canvas "Church Groups, Together", board Notify: "Group chat:
# Every message · Evening summary · Off"). Pins:
#   1. "Every message" is what was live; "Evening summary" and "Off" get no
#      note per message; an after-hours alert still rings for them;
#      direct messages always note
#   2. "Off" still hears a reply to their own message
#   3. 7 PM on the church's clock: one note per chat for each evening
#      person, only for what's new since they read it or the last note,
#      first names, replies to them counted; never their own; once a day
#   4. only someone in the chat chooses, only for a group's chat or the
#      leaders room; the control shows under the chat

import pathlib
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import group_chat_notify as gcn
import member_push
from test_member_group_chat import _page, _post, church  # noqa: F401
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_member_messaging import ANA, BEN, BIZ, CARL, GRP, _group_tid, _send, env  # noqa: F401

DETROIT = ZoneInfo("America/Detroit")


def _at(h, m=0, day=2):
    return datetime(2026, 10, day, h, m, tzinfo=DETROIT).astimezone(timezone.utc)


@pytest.fixture
def chat(church, monkeypatch):
    church.biz["settings"]["member_portal"] = {"enabled": True, "notifications": {"messages": True}}
    church.t["group_members"].append({"group_id": GRP, "contact_id": CARL, "business_id": BIZ, "role": "member"})
    church.sent = []
    monkeypatch.setattr(member_push, "send", lambda biz, kind, **k: church.sent.append((kind, k)) or 1)
    monkeypatch.setattr(member_push, "_later", lambda fn, *a, **k: fn(*a, **k))
    import group_gatherings as gg
    monkeypatch.setattr(gg, "zone", lambda business: DETROIT)
    church.tid = _group_tid(church, ANA, GRP)
    return church


def _level(env, who, level):
    hit = next((p for p in env.t["msg_participants"] if p["thread_id"] == env.tid and p["contact_id"] == who), None)
    if hit:
        hit["notify"] = level
    else:
        env.t["msg_participants"].append({"thread_id": env.tid, "contact_id": who, "business_id": BIZ, "state": "active",
                                          "notify": level})


def _who_heard(env):
    out = []
    for kind, k in env.sent:
        out += [(c, k["title"]) for c in k["contact_ids"]]
    return sorted(out)


# ── 1. a note per message, or not ────────────────────────────────────

def test_every_message_is_what_was_live(chat):
    _send(chat, BEN, chat.tid, "See you Thursday")
    assert _who_heard(chat) == [(ANA, "New message in Tuesday Night"), (CARL, "New message in Tuesday Night")]


def test_evening_and_off_get_no_note_per_message(chat):
    _level(chat, ANA, "evening")
    _level(chat, CARL, "replies")
    _send(chat, BEN, chat.tid, "See you Thursday")
    assert chat.sent == []


def test_an_after_hours_alert_still_rings(chat):
    _level(chat, ANA, "evening")
    t = {"id": chat.tid, "kind": "group", "group_id": GRP}
    acc = {"people": {ANA: {"enabled": True}, BEN: {"enabled": True}}}
    assert member_push.chat_recipients(t, acc, BEN, chat.t["msg_participants"], ring=True) == [ANA]
    assert member_push.chat_recipients(t, acc, BEN, chat.t["msg_participants"]) == []
    direct = {"id": "d", "kind": "direct"}
    assert member_push.chat_recipients(direct, {"other": {"id": ANA}}, BEN,
                                       [{"contact_id": ANA, "notify": "evening"}]) == [ANA]   # a direct chat always


# ── 2. a reply, for Off ──────────────────────────────────────────────

def test_off_still_hears_a_reply_to_them(chat):
    _level(chat, CARL, "replies")
    _level(chat, ANA, "evening")
    _send(chat, CARL, chat.tid, "Who has the slow cooker?")
    chat.sent.clear()
    q = next(m for m in chat.t["msg_messages"] if m["body"] == "Who has the slow cooker?")
    _post(chat, BEN, f"/my/messages/{chat.tid}/send", {"body": "Jasmine has it", "reply_to": q["id"]})
    assert _who_heard(chat) == [(CARL, "New reply to you in Tuesday Night")]
    chat.sent.clear()
    _post(chat, BEN, f"/my/messages/{chat.tid}/send", {"body": "And napkins", "reply_to": q["id"]})
    _level(chat, CARL, "evening")
    _post(chat, BEN, f"/my/messages/{chat.tid}/send", {"body": "Thanks all", "reply_to": q["id"]})
    assert _who_heard(chat) == [(CARL, "New reply to you in Tuesday Night")]     # evening waits for 7 PM


# ── 3. the 7 PM note ─────────────────────────────────────────────────

def _say(env, who, body, at, reply_to=None):
    env.t["msg_messages"].append({"id": f"00000000-0000-4000-9999-{len(env.t['msg_messages']):012d}", "business_id": BIZ,
                                  "thread_id": env.tid, "sender_contact_id": who, "body": body, "status": "delivered",
                                  "reply_to": reply_to, "created_at": at.isoformat()})
    return env.t["msg_messages"][-1]["id"]


def test_seven_oclock_who_talked_and_replies_to_you(chat):
    _level(chat, ANA, "evening")
    mine = _say(chat, ANA, "Who's hosting?", _at(9))
    _say(chat, BEN, "Renée is", _at(10), reply_to=mine)
    _say(chat, CARL, "Bring chairs", _at(11))
    _say(chat, BEN, "Thanks", _at(12))
    assert gcn.evening(chat.biz, _at(18, 59)) == 0
    assert gcn.evening(chat.biz, _at(19, 5)) == 1
    kind, k = chat.sent[0]
    assert kind == "messages" and k["contact_ids"] == [ANA] and k["title"] == "Tuesday Night"
    assert k["body"] == "3 new messages from Ben and Carl · 1 reply to you"
    assert k["url"] == f"/my/groups/{GRP}/chat" and k["ref_id"] == f"chat-evening:{chat.tid}:{ANA}:2026-10-02"


def test_only_whats_new_and_only_when_there_is_some(chat):
    _level(chat, ANA, "evening")
    _say(chat, BEN, "Old news", _at(9))
    part = next(p for p in chat.t["msg_participants"] if p["contact_id"] == ANA and p["thread_id"] == chat.tid)
    part["last_read_at"] = _at(10).isoformat()               # she read it
    assert gcn.evening(chat.biz, _at(19, 5)) == 0
    _say(chat, ANA, "Only me", _at(11))
    assert gcn.evening(chat.biz, _at(19, 5)) == 0             # her own never counts
    _say(chat, CARL, "New", _at(12))
    assert gcn.evening(chat.biz, _at(19, 5)) == 1
    assert chat.sent[-1][1]["body"] == "1 new message from Carl" and part["summed_at"]
    _say(chat, BEN, "After the note", _at(19, 10))
    chat.sent.clear()
    gcn.evening(chat.biz, _at(19, 20))
    assert chat.sent[-1][1]["body"] == "1 new message from Ben"   # counted from the last note on (ref_id once a day)


def test_only_people_still_in_the_chat(chat):
    _level(chat, CARL, "evening")
    _say(chat, BEN, "Hello", _at(12))
    chat.t["group_members"] = [m for m in chat.t["group_members"] if m["contact_id"] != CARL]
    assert gcn.evening(chat.biz, _at(19, 5)) == 0
    chat.t["group_members"].append({"group_id": GRP, "contact_id": CARL, "business_id": BIZ, "role": "member"})
    next(p for p in chat.t["msg_participants"] if p["contact_id"] == CARL)["muted"] = True
    assert gcn.evening(chat.biz, _at(19, 5)) == 0


def test_names():
    assert gcn._names(["Ben Cole"]) == "Ben"
    assert gcn._names(["Ben Cole", "Carl Moss"]) == "Ben and Carl"
    assert gcn._names(["Ben Cole", "Carl Moss", "Ana Rivers", "Tia Rivers"]) == "Ben, Carl and 2 others"
    assert gcn._names(["Ben Cole", "Carl Moss", "Ana Rivers"]) == "Ben, Carl and 1 other"


# ── 4. choosing ──────────────────────────────────────────────────────

def _choose(env, who, data):
    import member_portal_groups as mpg
    from test_member_messaging import ORIGIN, HOST
    env.who["id"] = who
    app = FastAPI()
    app.include_router(mpg.router)
    return TestClient(app, base_url=f"https://{HOST}").post("/my/groups/chat/notify", data=data, headers=ORIGIN,
                                                            follow_redirects=False)


def test_choosing_under_the_chat(chat):
    page = _page(chat, ANA, f"/my/groups/{GRP}/chat").text
    assert "Notes: <b>Every message</b>" in page and 'action="/my/groups/chat/notify"' in page
    r = _choose(chat, ANA, {"thread": chat.tid, "level": "evening", "back": f"/my/groups/{GRP}/chat"})
    assert r.headers["location"] == f"/my/groups/{GRP}/chat?done=chat_evening"
    assert gcn.mine(BIZ, chat.tid, ANA) == "evening"
    assert "Notes: <b>Evening summary</b>" in _page(chat, ANA, f"/my/groups/{GRP}/chat").text


def test_only_someone_in_the_chat_chooses(chat):
    from test_member_messaging import TEEN
    r = _choose(chat, TEEN, {"thread": chat.tid, "level": "replies", "back": f"/my/groups/{GRP}/chat"})
    assert "err=gone_chat" in r.headers["location"] and gcn.mine(BIZ, chat.tid, TEEN) == "every"
    r = _choose(chat, ANA, {"thread": chat.tid, "level": "loud", "back": f"/my/groups/{GRP}/chat"})
    assert "err=error" in r.headers["location"]


def test_no_control_when_the_church_sends_no_message_notes(chat):
    chat.biz["settings"]["member_portal"] = {"enabled": True, "notifications": {}}
    assert "Notes: <b>" not in _page(chat, ANA, f"/my/groups/{GRP}/chat").text


def test_notifications_lists_each_group_chat(chat, monkeypatch):
    from html import escape
    from test_member_messaging import TEEN
    _level(chat, ANA, "evening")
    chats = gcn.my_chats(chat.biz, ANA)
    assert [(c["title"], c["level"]) for c in chats] == [("Tuesday Night", "evening")]
    assert gcn.my_chats(chat.biz, TEEN) == []                # the Youth chat hasn't been opened yet
    html = gcn.notifications_section(chats, escape)
    assert "Group chats" in html and 'name="back" value="/my/notifications"' in html
    assert 'value="evening" aria-pressed="true"' in html and "One quiet note at 7 PM" in html
    r = _choose(chat, ANA, {"thread": chat.tid, "level": "every", "back": "/my/notifications"})
    assert r.headers["location"] == "/my/notifications?done=chat_every"
    monkeypatch.setattr(member_push, "ready", lambda: True)
    monkeypatch.setattr(member_push, "vapid_public", lambda: "k")
    from test_member_group_chat import _page as _gp  # noqa: F401
    from starlette.requests import Request
    req = Request({"type": "http", "query_string": b"", "headers": []})
    page = member_push.render_page(chat.biz, None, req, {"id": ANA, "name": "Ana"}, set(), None, chats)
    assert "Group chats" in page
    chat.biz["settings"]["member_portal"]["notifications"] = {"groups": True}     # no message notes from this church
    page = member_push.render_page(chat.biz, None, req, {"id": ANA, "name": "Ana"}, set(), None, chats)
    assert "Group chats" not in page


def test_the_choice_is_read_with_the_chat(chat, monkeypatch):
    # The fake hands back whole rows whatever is selected; the live database doesn't.
    import member_portal_messaging as mpm
    import sb_clients
    seen = []
    real = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: seen.append(p) or real(p))
    mpm.participants(BIZ, chat.tid)
    assert any(p.startswith("/msg_participants") and "notify" in p.split("select=")[1].split(",") for p in seen)


def test_every_code_has_words():
    import member_portal_church as mpc
    assert {"chat_every", "chat_evening", "chat_replies"} <= set(mpc.DONE)
