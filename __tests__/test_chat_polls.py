# __tests__/test_chat_polls.py
#
# Polls in a group's chat (chat_polls + member_portal_messaging send/vote +
# member_portal_groups; the approved canvas "Church Groups, Together",
# boards Chat and Settings). Pins:
#   1. anyone who writes in the chat posts a poll: the question is the
#      message, 2-4 different choices ride along, and the question and
#      choices are checked together; a held poll is held whole
#   2. polls are for group chats and the leaders' room, never a private
#      chat; a group's leaders turn them off, and a member can't
#   3. one vote per person: the same choice again takes it back, another
#      changes it; nobody outside the chat votes; voting closes after a week
#   4. everyone sees the counts, never who voted; the composer's + offers a
#      poll (when the group has them) and the prayer wall

import pathlib
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import chat_polls as cp
import member_portal as mp
import member_portal_groups as mpg
import member_portal_messaging as mpm
from test_member_group_chat import _msg, _page, _post, church  # noqa: F401
from test_member_messaging import ANA, BEN, BIZ, CARL, GRP, HOST, JSON, ORIGIN, _group_tid, env  # noqa: F401


@pytest.fixture
def polls(church, monkeypatch):
    church.t.setdefault("msg_polls", [])
    church.t.setdefault("msg_poll_votes", [])
    church.screened = []
    import msg_screen

    async def screen(b, text):
        church.screened.append(text)
        return "harm" if "harmful" in text else church.verdict
    monkeypatch.setattr(msg_screen, "screen", screen)
    # PostgREST's upsert on (message_id, contact_id), which the fake leaves out.
    real = church.post

    def post(path, body, prefer=None):
        if path.startswith("/msg_poll_votes") and "merge-duplicates" in (prefer or ""):
            hit = next((v for v in church.t["msg_poll_votes"]
                        if v["message_id"] == body["message_id"] and v["contact_id"] == body["contact_id"]), None)
            if hit:
                hit.update(body)
                return [dict(hit)]
        return real(path, body, prefer)
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    return church


def _ask(env, who, tid, q="Potluck theme for Nov 19?", choices=("Soul food", "Breakfast for dinner", "Taco bar", "")):
    return _post(env, who, f"/my/messages/{tid}/send", {"body": q, "poll": "1", "choice": list(choices)})


def _vote(env, who, tid, mid, choice):
    return _post(env, who, f"/my/messages/{tid}/vote", {"message_id": mid, "choice": str(choice)})


# ── 1. posting one ───────────────────────────────────────────────────

def test_a_member_posts_a_poll(polls):
    tid = _group_tid(polls, ANA, GRP)
    assert _ask(polls, ANA, tid, choices=("  Soul   food ", "Breakfast for dinner", "soul food", "Taco bar")).json()["ok"]
    m = _msg(polls, "Potluck theme for Nov 19?")
    p = polls.t["msg_polls"][0]
    assert p["message_id"] == m["id"] and p["choices"] == ["Soul food", "Breakfast for dinner", "Taco bar"]   # tidied, no repeat
    assert p["business_id"] == BIZ
    closes = datetime.fromisoformat(p["closes_at"])
    assert timedelta(days=6, hours=23) < closes - datetime.now(timezone.utc) <= timedelta(days=7)
    assert polls.screened[-1] == "Potluck theme for Nov 19?\nSoul food\nBreakfast for dinner\nTaco bar"


def test_a_poll_needs_two_different_choices(polls):
    tid = _group_tid(polls, ANA, GRP)
    r = _ask(polls, ANA, tid, choices=("Yes", "yes", " ", ""))
    assert r.status_code == 400 and "two different choices" in r.json()["error"]
    assert not polls.t["msg_messages"] and not polls.t["msg_polls"]


def test_four_choices_at_most(polls):
    tid = _group_tid(polls, ANA, GRP)
    _ask(polls, ANA, tid, choices=("A", "B", "C", "D", "E"))
    assert polls.t["msg_polls"][0]["choices"] == ["A", "B", "C", "D"]


def test_a_harmful_choice_holds_the_whole_poll(polls):
    tid = _group_tid(polls, ANA, GRP)
    _ask(polls, ANA, tid, q="Which one?", choices=("Fine", "something harmful"))
    m = _msg(polls, "Which one?")
    assert m["status"] == "held" and polls.t["msg_polls"][0]["message_id"] == m["id"]
    mine = _page(polls, ANA, f"/my/groups/{GRP}/chat").text
    assert "Which one?" in mine and "Held for review" in mine and 'action="/my/messages/' + tid + '/vote"' not in mine
    assert "Which one?" not in _page(polls, BEN, f"/my/groups/{GRP}/chat").text


def test_no_choices_saved_no_poll(polls, monkeypatch):
    tid = _group_tid(polls, ANA, GRP)
    real = mpm.sb_clients.sb_post_as_service
    monkeypatch.setattr(mpm.sb_clients, "sb_post_as_service",
                        lambda path, *a, **k: None if path.startswith("/msg_polls") else real(path, *a, **k))
    r = _ask(polls, ANA, tid)
    assert r.status_code == 503 and _msg(polls, "Potluck theme for Nov 19?")["status"] == "removed"


# ── 2. where ─────────────────────────────────────────────────────────

def test_never_in_a_private_chat(polls):
    from test_member_messaging import _start, _tid
    tid = _tid(_start(polls, ANA, BEN))
    r = _ask(polls, ANA, tid)
    assert r.status_code == 403 and not polls.t["msg_polls"] and not polls.t["msg_messages"]


def test_a_groups_leaders_turn_polls_off(polls):
    tid = _group_tid(polls, ANA, GRP)
    polls.t["groups"][0]["chat_extras"] = False
    r = _ask(polls, ANA, tid)
    assert r.status_code == 403 and "turned polls off" in r.json()["error"] and not polls.t["msg_polls"]
    page = _page(polls, ANA, f"/my/groups/{GRP}/chat?make=poll").text
    assert "?make=poll" not in page and 'id="gc-pollform"' not in page and 'id="gc-compose"' in page


def _groups_app(env, who):
    env.who["id"] = who
    app = FastAPI()
    app.include_router(mpg.router)
    return TestClient(app, base_url=f"https://{HOST}", follow_redirects=False)


def test_the_switch_is_the_leaders(polls):
    _group_tid(polls, ANA, GRP)
    people = _page(polls, BEN, f"/my/groups/{GRP}/people").text
    assert "Polls in the chat" in people and 'action="/my/groups/extras"' in people
    assert 'action="/my/groups/extras"' not in _page(polls, ANA, f"/my/groups/{GRP}/people").text
    r = _groups_app(polls, ANA).post("/my/groups/extras", data={"group_id": GRP, "on": "0"}, headers=ORIGIN)
    assert "err=not_group_leader" in r.headers["location"] and polls.t["groups"][0].get("chat_extras") is not False
    r = _groups_app(polls, BEN).post("/my/groups/extras", data={"group_id": GRP, "on": "0"}, headers=ORIGIN)
    assert r.headers["location"] == f"/my/groups/{GRP}/people?done=extras_off" and polls.t["groups"][0]["chat_extras"] is False
    _groups_app(polls, BEN).post("/my/groups/extras", data={"group_id": GRP, "on": "1"}, headers=ORIGIN)
    assert polls.t["groups"][0]["chat_extras"] is True
    polls.t["groups"][0]["chat_on"] = False                                        # a Board-only group has no chat to poll in
    assert "Polls in the chat" not in _page(polls, BEN, f"/my/groups/{GRP}/people").text


# ── 3. voting ────────────────────────────────────────────────────────

def test_one_vote_each_and_tap_again_to_take_it_back(polls):
    tid = _group_tid(polls, ANA, GRP)
    _ask(polls, BEN, tid)
    mid = _msg(polls, "Potluck theme for Nov 19?")["id"]
    assert _vote(polls, ANA, tid, mid, 0).json()["ok"]
    assert _vote(polls, BEN, tid, mid, 2).json()["ok"]
    assert sorted((v["contact_id"], v["choice"]) for v in polls.t["msg_poll_votes"]) == sorted([(ANA, 0), (BEN, 2)])
    _vote(polls, ANA, tid, mid, 1)                                                  # changes
    assert [v["choice"] for v in polls.t["msg_poll_votes"] if v["contact_id"] == ANA] == [1]
    _vote(polls, ANA, tid, mid, 1)                                                  # the same again: taken back
    assert [v["contact_id"] for v in polls.t["msg_poll_votes"]] == [BEN]


def test_no_such_choice_or_not_a_poll(polls):
    tid = _group_tid(polls, ANA, GRP)
    _ask(polls, BEN, tid)
    mid = _msg(polls, "Potluck theme for Nov 19?")["id"]
    assert _vote(polls, ANA, tid, mid, 3).status_code == 409
    assert _vote(polls, ANA, tid, mid, "x").status_code == 400
    _post(polls, ANA, f"/my/messages/{tid}/send", {"body": "just words"})
    assert _vote(polls, ANA, tid, _msg(polls, "just words")["id"], 0).status_code == 409
    assert polls.t["msg_poll_votes"] == []


def test_only_the_chat_votes(polls):
    tid = _group_tid(polls, ANA, GRP)
    _ask(polls, BEN, tid)
    r = _vote(polls, CARL, tid, _msg(polls, "Potluck theme for Nov 19?")["id"], 0)    # Carl isn't in the group
    assert r.status_code == 404 and polls.t["msg_poll_votes"] == []


def test_voting_closes(polls):
    tid = _group_tid(polls, ANA, GRP)
    _ask(polls, BEN, tid)
    mid = _msg(polls, "Potluck theme for Nov 19?")["id"]
    _vote(polls, ANA, tid, mid, 0)
    polls.t["msg_polls"][0]["closes_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    r = _vote(polls, BEN, tid, mid, 1)
    assert r.status_code == 409 and "closed" in r.json()["error"] and len(polls.t["msg_poll_votes"]) == 1
    page = _page(polls, ANA, f"/my/groups/{GRP}/chat").text
    assert f"/my/messages/{tid}/vote" not in page and "You voted · 1 vote · closed" in page
    assert '<button class="gc-po' not in page and '<span class="gc-po on" role="img"' in page


# ── 4. what everyone sees ────────────────────────────────────────────

def test_everyone_sees_the_counts_never_who(polls):
    tid = _group_tid(polls, ANA, GRP)
    _ask(polls, BEN, tid)
    mid = _msg(polls, "Potluck theme for Nov 19?")["id"]
    _vote(polls, ANA, tid, mid, 0)
    _vote(polls, BEN, tid, mid, 2)
    page = _page(polls, ANA, f"/my/groups/{GRP}/chat").text
    assert '<summary class="gc-pq">Potluck theme for Nov 19?</summary>' in page        # tap it to react, reply or report
    assert 'value="0" aria-pressed="true" aria-label="Soul food, 1 vote, your vote"' in page
    assert 'value="2" aria-pressed="false" aria-label="Taco bar, 1 vote"' in page
    assert 'style="width:50%"' in page and 'aria-label="Breakfast for dinner, 0 votes"' in page
    assert "You voted · 2 votes · closes " in page
    other = _page(polls, BEN, f"/my/groups/{GRP}/chat").text
    assert 'aria-label="Taco bar, 1 vote, your vote"' in other and 'aria-label="Soul food, 1 vote"' in other
    assert "Ana Rivers" not in other.split("Potluck theme")[1].split("</li>")[0]                 # never who voted


def test_the_plus_offers_a_poll_and_the_prayer_wall(polls):
    _group_tid(polls, ANA, GRP)
    page = _page(polls, ANA, f"/my/groups/{GRP}/chat").text
    assert f'href="/my/groups/{GRP}/chat?make=poll#gc-pollform"' in page and f'href="/my/groups/{GRP}/prayer"' in page
    form = _page(polls, ANA, f"/my/groups/{GRP}/chat?make=poll").text
    assert 'id="gc-pollform"' in form and 'name="poll" value="1"' in form and form.count('name="choice"') == 4
    assert "Everyone sees the counts, never who voted." in form
    assert "if(document.getElementById('gc-pollform'))return;" in form              # a new message never wipes a half-typed poll


def test_the_leaders_room_has_polls_and_no_prayer_wall(polls, monkeypatch):
    from test_member_leaders_room import ROOM, _app
    monkeypatch.setattr(mpm, "leaders_room_people", lambda b: [{"contact_id": BEN, "role": "leader"}])
    page = _app(polls, BEN).get(ROOM).text
    assert f'href="{ROOM}?make=poll#gc-pollform"' in page and "/prayer" not in page.split('class="gc-tray"')[1].split("</details>")[0]


def test_closes_in_the_churchs_time():
    tz = ZoneInfo("America/Chicago")
    now = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)                         # Tuesday 10 AM in Chicago
    at = lambda **kw: now + timedelta(**kw)  # noqa: E731
    assert cp.closes_text(at(days=7), now, tz) == "closes Tue, Oct 27"
    assert cp.closes_text(at(days=3), now, tz) == "closes Friday"
    assert cp.closes_text(at(days=1), now, tz) == "closes tomorrow"
    assert cp.closes_text(at(hours=9), now, tz) == "closes tonight"
    assert cp.closes_text(at(hours=2), now, tz) == "closes today"
    assert cp.closes_text(at(minutes=-1), now, tz) == "closed"


def test_words():
    import member_portal_church as mpc
    assert {"poll_choices", "poll_where", "polls_off", "poll_closed", "poll_gone"} <= set(mpc.ERRORS)
    assert {"voted", "unvoted", "extras_on", "extras_off"} <= set(mpc.DONE)
