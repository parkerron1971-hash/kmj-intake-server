"""Instant send in the member app (member_instant_send.py; Kevin,
2026-11-18: "the members app move slow when send messages in chat", then
"yes build all four"). A member's message shows the moment they tap Send;
the route answers the app's fetch in JSON. Pins, for each conversation
(the church's conversation, a private chat, a group's chat, the live room):

  1. sent: the answer carries the bubble drawn by the page's own renderer
  2. held and care: the page's own notice, word for word (care: 988, 911),
     the pastor's private note, the reviewers told, exactly as before
  3. refused (a cap, too soon, the check down, the owner's preview, a
     sample church, signed out): nothing saved, today's words, a status
  4. the check still runs before anything is saved; the same-origin check
     holds for a fetch as for a form
  5. a retry after a lost answer finds the message already saved instead of
     saving it twice; without retry=1 nothing is looked up
  6. the chat's poll: how many messages and the newest, and whether
     someone else wrote in between (fresh)
  7. MEMBER_INSTANT_SEND=off renders the scripts the pages had before
"""
import asyncio
import json
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_instant_send as mis
import member_portal as mp
import member_portal_church as mpc
import member_portal_groups as mpg
import member_portal_live as mpl
import member_portal_messaging as mpm
import member_portal_threads as mpt
import test_church_threads as tct
import test_member_group_chat as tgc
import test_live as tl
import test_member_messaging as tmm
from test_church_threads import fake, screen  # noqa: F401  (fixtures)
from test_live import db  # noqa: F401  (fixture)
from test_member_messaging import env  # noqa: F401  (fixture)
from test_member_group_chat import church  # noqa: F401  (fixture)

APP = {"accept": "application/json"}
NOW_ISO = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731


# ─── the church's conversation (member_portal_threads) ───────────────


def _say(c, body, **extra):
    return c.post("/my/inbox/church/send", data={"body": body, **extra}, headers={**tct.ORIGIN, **APP},
                  follow_redirects=False)


def _mine(f):
    return tct.notes(f, direction="member")


def test_church_sent_answers_with_its_own_bubble_and_day(fake, monkeypatch, screen):
    c = tct._app(fake, monkeypatch, tct.ANA)
    r = _say(c, "Can I bring <my> sister?")
    assert r.status_code == 200
    x = r.json()
    row = _mine(fake)[0]
    assert x["ok"] is True and x["code"] == "ct_sent" and x["id"] == row["id"]
    # The page's own bubble for it, escaped, at its time.
    assert x["html"] == mpt._bubble(row, timezone.utc)
    assert x["html"].startswith('<li class="mb-msg mb-mine">') and "&lt;my&gt;" in x["html"] and 'class="ct-at"' in x["html"]
    assert x["day"] == "Today" and x["day_html"] == '<li class="mb-msg ct-day" role="separator">Today</li>'
    assert "notice" not in x and "care" not in x
    # The office still hears, by first name only.
    assert sorted(u for u, _ in fake.staff) == sorted([tct.OWNER, tct.CLERK])
    # The plain form is untouched: a 303 back to the conversation.
    for r_ in _mine(fake):
        r_["created_at"] = tct.iso(tct.NOW - timedelta(minutes=5))
    plain = c.post("/my/inbox/church/send", data={"body": "plain"}, headers=tct.ORIGIN, follow_redirects=False)
    assert plain.status_code == 303 and plain.headers["location"] == "/my/inbox/church?done=ct_sent"


def test_church_held_shows_the_pages_held_notice(fake, monkeypatch, screen):
    screen["verdict"] = "harm"
    fake.add("msg_safety_officers", business_id=tct.BIZ, user_id=tct.OFFICER)
    x = _say(tct._app(fake, monkeypatch, tct.ANA), "something harmful").json()
    assert x["ok"] is True and x["code"] == "held"
    assert x["notice"] == mpc.flash_html(done="held") == (
        '<p class="mp-ok mp-flash" role="status">Your message was held for review by the church&#x27;s safety '
        'officers. Only you can see it for now.</p>')
    assert "Held for review. Only you can see it." in x["html"]
    assert _mine(fake)[0]["held"] is True
    assert [u for u, _ in fake.staff] == [tct.OFFICER]                 # the reviewers, as before


def test_church_care_shows_the_same_crisis_words_the_page_shows(fake, monkeypatch, screen):
    screen["verdict"] = "self_harm"
    c = tct._app(fake, monkeypatch, tct.ANA)
    x = _say(c, "I want to die").json()
    assert x["ok"] is True and x["code"] == "care" and x["care"] is True
    # Word for word what the reloaded page showed, in the same markup.
    assert x["notice"] in c.get("/my/inbox/church?done=care").text
    assert "988" in x["notice"] and "911" in x["notice"] and "Someone from the church will reach out to you." in x["notice"]
    assert _mine(fake)[0]["held"] is False
    assert len(fake.t["ministry_care_requests"]) == 1                  # the pastor's private note


@pytest.mark.parametrize("seed,code,status,words", [
    ("gap", "ct_gap", 429, "One moment, then send it again."),
    ("day", "ct_day", 429, "messages today. You can write again tomorrow."),
])
def test_church_caps_answer_in_todays_words(fake, monkeypatch, screen, seed, code, status, words):
    c = tct._app(fake, monkeypatch, tct.ANA)
    if seed == "gap":
        fake.note(contact_id=tct.ANA, direction="member", kind="message", body="just now", created_at=NOW_ISO())
    else:
        for i in range(tct.ct.DAY_MAX):
            fake.note(contact_id=tct.ANA, direction="member", kind="message", body=f"m{i}",
                      created_at=tct.iso(tct.NOW - timedelta(hours=1, minutes=i)))
    before = len(_mine(fake))
    r = _say(c, "one more")
    assert r.status_code == status and r.json()["ok"] is False and r.json()["code"] == code
    assert words in r.json()["error"]
    assert len(_mine(fake)) == before and fake.staff == []


def test_church_screen_down_saves_nothing(fake, monkeypatch, screen):
    screen["verdict"] = "down"
    r = _say(tct._app(fake, monkeypatch, tct.ANA), "Hello")
    assert r.status_code == 503 and r.json()["code"] == "screen_off"
    assert r.json()["error"] == mpc.ERRORS["screen_off"]
    assert _mine(fake) == [] and fake.staff == []


def test_church_the_check_runs_before_anything_is_saved(fake, monkeypatch, screen):
    seen = []
    import msg_screen

    async def watch(biz, text):
        seen.append(len(_mine(fake)))
        return "ok"
    monkeypatch.setattr(msg_screen, "screen", watch)
    assert _say(tct._app(fake, monkeypatch, tct.ANA), "Hello").json()["ok"]
    assert seen == [0] and len(_mine(fake)) == 1


def test_church_preview_sample_and_signed_out_save_nothing(fake, monkeypatch, screen):
    # The owner's preview reads, never writes.
    c = tct._app(fake, monkeypatch, tct.ANA)
    monkeypatch.setattr(mp, "_session_for", lambda req, church: {"preview": {"cid": tct.ANA}})
    r = _say(c, "hi")
    assert r.status_code == 403 and r.json()["code"] == "preview" and r.json()["error"] == mpc.ERRORS["preview"]
    # Signed out: said, never a redirect the app can't read.
    monkeypatch.setattr(mp, "_session_for", lambda req, church: None)
    r = _say(c, "hi")
    assert r.status_code == 401 and r.json()["code"] == "signed_out"
    # A sample church records and sends nothing: its conversation is closed
    # (church_threads keeps a sample quiet), and send_message says preview.
    fake.biz[tct.BIZ]["is_sample"] = True
    r = _say(tct._app(fake, monkeypatch, tct.ANA), "hi")
    assert r.status_code == 404 and r.json()["ok"] is False and r.json()["code"] == "gone_chat"
    monkeypatch.setattr(mpt, "entry_open", lambda biz: True)
    r = _say(tct._app(fake, monkeypatch, tct.ANA), "hi")
    assert r.status_code == 403 and r.json()["code"] == "preview" and r.json()["error"] == mpc.ERRORS["preview"]
    assert _mine(fake) == [] and fake.staff == []


def test_church_a_fetch_passes_the_same_origin_check_a_form_does(fake, monkeypatch, screen):
    c = tct._app(fake, monkeypatch, tct.ANA)
    r = c.post("/my/inbox/church/send", data={"body": "hi"}, headers={"origin": "https://evil.example", **APP})
    assert r.status_code == 403 and _mine(fake) == []
    r = c.post("/my/inbox/church/send", data={"body": "hi"},
               headers={"origin": "null", "sec-fetch-site": "cross-site", **APP})
    assert r.status_code == 403 and _mine(fake) == []
    r = c.post("/my/inbox/church/send", data={"body": "hi"},
               headers={"origin": "null", "sec-fetch-site": "same-origin", **APP})
    assert r.status_code == 200 and r.json()["ok"] and len(_mine(fake)) == 1


def test_church_a_retry_finds_the_message_already_saved(fake, monkeypatch, screen):
    c = tct._app(fake, monkeypatch, tct.ANA)
    first = _say(c, "Can I bring my sister?").json()
    told = len(fake.staff)
    again = _say(c, "Can I bring my sister?", retry="1")
    assert again.status_code == 200 and again.json()["ok"] and again.json()["id"] == first["id"]
    assert len(_mine(fake)) == 1 and len(fake.staff) == told           # saved once, told once
    # Without retry=1 the same words are a new message, and the gap holds.
    assert _say(c, "Can I bring my sister?").json()["code"] == "ct_gap"
    # A retry of words never saved goes through the whole check.
    _mine(fake)[0]["created_at"] = tct.iso(tct.NOW - timedelta(minutes=1))
    r = _say(c, "Something new", retry="1").json()
    assert r["ok"] and r["id"] != first["id"] and len(_mine(fake)) == 2


def test_church_a_retry_of_a_held_or_crisis_message_shows_its_notice(fake, monkeypatch, screen):
    c = tct._app(fake, monkeypatch, tct.ANA)
    screen["verdict"] = "harm"
    held = _say(c, "something harmful").json()
    assert _say(c, "something harmful", retry="1").json()["code"] == "held"
    _mine(fake)[0]["created_at"] = tct.iso(tct.NOW - timedelta(minutes=1))
    screen["verdict"] = "self_harm"
    _say(c, "I want to die")
    cares = len(fake.t["ministry_care_requests"])
    x = _say(c, "I want to die", retry="1").json()
    assert x["code"] == "care" and x["care"] is True and "988" in x["notice"]
    assert len(fake.t["ministry_care_requests"]) == cares             # the pastor isn't told twice
    # The check down on a retry still shows the crisis words (the floor).
    screen["verdict"] = "down"
    assert _say(c, "I want to die", retry="1").json()["code"] == "care"
    assert len(_mine(fake)) == 2 and held["ok"]


def test_church_a_bubble_that_cant_draw_never_looks_unsent(fake, monkeypatch, screen):
    def broken(*a, **kw):
        raise RuntimeError("draw")
    monkeypatch.setattr(mpt, "_bubble", broken)
    x = _say(tct._app(fake, monkeypatch, tct.ANA), "Hello").json()
    assert x["ok"] is True and x["code"] == "ct_sent" and "html" not in x and len(_mine(fake)) == 1


# ─── a private chat (member_portal_messaging) ────────────────────────


def _chat_send(e, who, tid, text, **extra):
    e.who["id"] = who
    return tmm._member(e, who).post(f"/my/messages/{tid}/send", data={"body": text, **extra}, headers=tmm.JSON)


def _msgs(e, tid):
    return [m for m in e.t["msg_messages"] if m["thread_id"] == tid]


def test_chat_sent_answers_with_its_bubble_and_the_polls_count(env):
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    first = _chat_send(env, tmm.ANA, tid, "See you <Tuesday>!", seen="").json()
    row = _msgs(env, tid)[0]
    assert first["ok"] and first["code"] == "sent" and first["id"] == row["id"]
    assert first["html"] == mpm._bubble(row, tmm.ANA, {}, reportable=False)
    assert "&lt;Tuesday&gt;" in first["html"] and 'class="mb-msg mb-mine"' in first["html"]
    assert first["count"] == 1 and first["fresh"] is True
    # The page shows the same bubble once it reloads.
    assert first["html"] in tmm._member(env, tmm.ANA).get(f"/my/messages/{tid}").text
    # Nobody else wrote in between: fresh.
    second = _chat_send(env, tmm.ANA, tid, "Bring chairs", seen=first["id"]).json()
    assert second["count"] == 2 and second["fresh"] is True
    # Ben wrote after what the page had: not fresh, so the poll reloads.
    _chat_send(env, tmm.BEN, tid, "Will do")
    third = _chat_send(env, tmm.ANA, tid, "Thanks", seen=second["id"]).json()
    assert third["count"] == 4 and third["fresh"] is False
    # The poll says which message is newest.
    feed = tmm._member(env, tmm.ANA).get(f"/my/messages/feed/{tid}").json()
    assert feed == {"count": 4, "last": third["id"]}


def test_chat_held_and_care_show_the_pages_notices(env):
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    env.verdict = "harm"
    x = _chat_send(env, tmm.ANA, tid, "something cruel").json()
    assert x["code"] == "held" and x["notice"] == mpc.flash_html(done="held")
    assert "Held for review. Only you can see it." in x["html"]
    env.verdict = "self_harm"
    x = _chat_send(env, tmm.ANA, tid, "I want to disappear").json()
    assert x["code"] == "care" and x["care"] is True
    assert x["notice"] in tmm._member(env, tmm.ANA).get(f"/my/messages/{tid}?done=care").text
    assert "988" in x["notice"] and len(env.t["ministry_care_requests"]) == 1


@pytest.mark.parametrize("case,code,status", [
    ("down", "screen_off", 503), ("slow", "slow_chat", 429), ("preview", "preview", 403), ("blocked", None, 403),
    ("declined", "declined", 403),
])
def test_chat_refused_sends_save_nothing_and_say_why(env, monkeypatch, case, code, status):
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    if case == "down":
        env.verdict = "down"
    elif case == "slow":
        import rate_limit
        monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: False)
    elif case == "preview":
        env.who["preview"] = True
    elif case == "blocked":
        env.t["msg_blocks"].append({"business_id": tmm.BIZ, "blocker_contact_id": tmm.BEN, "blocked_contact_id": tmm.ANA})
    elif case == "declined":
        for p in env.t["msg_participants"]:
            if p["thread_id"] == tid and p["contact_id"] == tmm.ANA:
                p["state"] = "declined"
    r = _chat_send(env, tmm.ANA, tid, "hello")
    assert r.status_code == status and r.json()["ok"] is False and r.json()["error"]
    if code:
        assert r.json()["error"] == mpc.ERRORS[code]
    assert _msgs(env, tid) == []


def test_chat_a_retry_finds_the_message_already_saved(env):
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    first = _chat_send(env, tmm.ANA, tid, "See you Tuesday!").json()
    _msgs(env, tid)[0]["created_at"] = NOW_ISO()                       # the fake's clock is October's
    again = _chat_send(env, tmm.ANA, tid, "See you Tuesday!", retry="1").json()
    assert again["ok"] and again["code"] == "sent" and again["id"] == first["id"] and len(_msgs(env, tid)) == 1
    # Without retry=1 the same words are a new message.
    assert _chat_send(env, tmm.ANA, tid, "See you Tuesday!").json()["id"] != first["id"]
    assert len(_msgs(env, tid)) == 2
    # Older than the window: a new message.
    for m in _msgs(env, tid):
        m["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    assert _chat_send(env, tmm.ANA, tid, "See you Tuesday!", retry="1").json()["id"] not in (first["id"],)
    assert len(_msgs(env, tid)) == 3


def test_chat_a_retry_of_a_crisis_message_shows_the_crisis_words(env):
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    env.verdict = "self_harm"
    _chat_send(env, tmm.ANA, tid, "I want to disappear")
    _msgs(env, tid)[0]["created_at"] = NOW_ISO()
    env.verdict = "down"                                               # no second check needed: the row says so
    x = _chat_send(env, tmm.ANA, tid, "I want to disappear", retry="1").json()
    assert x["code"] == "care" and "988" in x["notice"] and len(env.t["ministry_care_requests"]) == 1
    assert len(_msgs(env, tid)) == 1


# ─── a group's chat (member_portal_groups) ───────────────────────────


def test_group_sent_bubble_is_the_chat_pages_own(church):
    tid = tmm._group_tid(church, tmm.ANA, tmm.GRP)
    here = f"/my/groups/{tmm.GRP}/chat"
    x = tgc._post(church, tmm.ANA, f"/my/messages/{tid}/send", {"body": "Hello <all>", "back": here}).json()
    assert x["ok"] and x["code"] == "sent" and x["html"].startswith('<li class="gc-m mine"')
    # Love / Praying / Amen and Reply on their own message, as the page draws it.
    assert f'href="{here}?reply={x["id"]}#gc-compose">Reply</a>' in x["html"]
    page = tgc._page(church, tmm.ANA, here).text
    assert x["html"] in page


def test_group_a_reply_quotes_by_the_groups_name_setting(church):
    for g in church.t["groups"]:
        g["name_display"] = "first"
    tid = tmm._group_tid(church, tmm.ANA, tmm.GRP)
    here = f"/my/groups/{tmm.GRP}/chat"
    tmm._send(church, tmm.BEN, tid, "Who has the slow cooker?")
    asked = tgc._msg(church, "Who has the slow cooker?")
    x = tgc._post(church, tmm.ANA, f"/my/messages/{tid}/send",
                  {"body": "I do", "reply_to": asked["id"], "back": here}).json()
    assert '<span class="gc-q"><b>Ben</b><span>Who has the slow cooker?</span></span>' in x["html"]
    assert x["html"] in tgc._page(church, tmm.ANA, here).text


def test_group_board_only_and_leaders_only_still_refuse(church):
    tid = tmm._group_tid(church, tmm.ANA, tmm.GRP)
    for g in church.t["groups"]:
        if g["id"] == tmm.GRP:
            g["chat_writers"] = "leaders"
    r = tgc._post(church, tmm.ANA, f"/my/messages/{tid}/send", {"body": "hi", "back": f"/my/groups/{tmm.GRP}/chat"})
    assert r.status_code == 403 and r.json()["error"] == mpc.ERRORS["leaders_write"]
    assert not [m for m in church.t["msg_messages"] if m["body"] == "hi"]


# ─── the live room (member_portal_live) ──────────────────────────────


def test_live_room_gets_the_id_and_a_retry_is_the_same_message(db):
    tl._go_live(tl._team())
    m = tl._member()
    first = m.post("/my/live/chat", data={"body": "Amen"}, headers=tl.JSON).json()
    assert first["ok"] and first["id"]
    rows = [r for r in db.t["live_chat"] if r["body"] == "Amen"]
    rows[0]["created_at"] = NOW_ISO()                                  # the fake's clock is January's
    again = m.post("/my/live/chat", data={"body": "Amen", "retry": "1"}, headers=tl.JSON).json()
    assert again == {"ok": True, "id": first["id"]}
    assert len([r for r in db.t["live_chat"] if r["body"] == "Amen"]) == 1
    # Without retry=1, "Amen" twice is twice.
    m.post("/my/live/chat", data={"body": "Amen"}, headers=tl.JSON)
    assert len([r for r in db.t["live_chat"] if r["body"] == "Amen"]) == 2


def test_live_room_refusals_are_unchanged(db):
    tl._go_live(tl._team())
    m = tl._member()
    r = m.post("/my/live/chat", data={"body": "free stuff at spam.com", "retry": "1"}, headers=tl.JSON)
    assert r.status_code == 400 and r.json()["error"] == mpc.ERRORS["link"]
    db.who["preview"] = True
    r = m.post("/my/live/chat", data={"body": "hi"}, headers=tl.JSON)
    assert r.status_code == 403 and not db.t["live_chat"]


def test_the_live_room_says_whether_instant_send_is_on(db, monkeypatch):
    tl._go_live(tl._team())
    monkeypatch.delenv("MEMBER_INSTANT_SEND", raising=False)
    page = tl._room(monkeypatch).get("/my/live").text
    assert '"instant": true' in page and '"author": "Ana R."' in page and "function instantly(" in page
    monkeypatch.setenv("MEMBER_INSTANT_SEND", "off")
    assert '"instant": false' in tl._room(monkeypatch).get("/my/live").text


# ─── the pages' scripts, and the switch ──────────────────────────────


def _church_page(fake, monkeypatch):
    return tct._app(fake, monkeypatch, tct.ANA).get("/my/inbox/church").text


@pytest.mark.parametrize("switch", ["", "on", "off"])
def test_the_church_conversation_page_and_the_switch(fake, monkeypatch, switch):
    monkeypatch.setenv("MEMBER_INSTANT_SEND", switch)
    html = _church_page(fake, monkeypatch)
    if switch == "off":
        assert mpt.SCROLL_JS in html and "mis-css" not in html and '"kind": "ct"' not in html
    else:
        assert '"kind": "ct"' in html and "mis-css" in html and mpt.SCROLL_ONLY_JS in html
        assert "s.disabled=true" not in html                          # the old submit lock is gone


@pytest.mark.parametrize("switch", ["", "off"])
def test_a_private_chat_page_and_the_switch(env, monkeypatch, switch):
    monkeypatch.setenv("MEMBER_INSTANT_SEND", switch)
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    _chat_send(env, tmm.ANA, tid, "hi")
    chat = tmm._member(env, tmm.ANA).get(f"/my/messages/{tid}").text
    if switch == "off":
        assert mpm._poll_script(tid, 1) in chat and "mis-css" not in chat and "mb:sent" not in chat
    else:
        assert '"kind": "mb"' in chat and "addEventListener('mb:sent'" in chat and "x.d.care" not in chat
        assert f'"seen": "{_msgs(env, tid)[-1]["id"]}"' in chat
        assert mpm._instant_poll_script(tid, 1, _msgs(env, tid)[-1]["id"]) in chat


@pytest.mark.parametrize("switch", ["", "off"])
def test_a_group_chat_page_and_the_switch(church, monkeypatch, switch):
    monkeypatch.setenv("MEMBER_INSTANT_SEND", switch)
    tid = tmm._group_tid(church, tmm.ANA, tmm.GRP)
    group = tgc._page(church, tmm.ANA, f"/my/groups/{tmm.GRP}/chat").text
    if switch == "off":
        assert mpg._chat_script(tid, 0, 0) in group and "mis-css" not in group and "mb:sent" not in group
        assert mis.script("a", "b", "c", "d", "gc") == ""
    else:
        assert '"kind": "gc"' in group and "addEventListener('mb:sent'" in group and "x.d.care" not in group
        assert mpg._instant_chat_script(tid, 0, 0, "") in group


def test_the_live_rooms_instant_send_has_a_name_of_its_own():
    # The room already says `var quick` (the quick replies); a function by
    # that name was overwritten by it and the room's send stopped (caught
    # in Playwright, 2026-11-18).
    js = mpl.ROOM_JS
    assert js.count("function instantly(") == 1 and "var instantly" not in js and "instantly=" not in js


def test_the_scripts_are_valid_javascript(monkeypatch):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    monkeypatch.delenv("MEMBER_INSTANT_SEND", raising=False)
    scripts = [mis.script("gc-compose", "gc-list", "gc-say", "gc-err", "gc", seen="x"),
               mis.script("ct-compose", "ct-chat", "ct-say", "ct-err", "ct"),
               mpm._instant_poll_script("t", 3, "x"), mpg._instant_chat_script("t", 3, 1, "x"),
               mpt.SCROLL_ONLY_JS, "<script>" + mpl.ROOM_JS.replace("__CFG__", "{}") + "</script>"]
    for s in scripts:
        js = s.split("<script>", 1)[1].rsplit("</script>", 1)[0]
        res = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, encoding="utf-8", timeout=30)
        assert res.returncode == 0, res.stderr


def test_same_recent_only_matches_the_same_words_in_the_window():
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    rows = [{"id": "a", "body": "Amen", "created_at": (now - timedelta(minutes=2)).isoformat()},
            {"id": "b", "body": "Hello", "created_at": (now - timedelta(minutes=3)).isoformat()},
            {"id": "c", "body": "Old", "created_at": (now - timedelta(minutes=11)).isoformat()}]
    assert mis.same_recent(rows, "Hello", now=now)["id"] == "b"
    assert mis.same_recent(rows, "hello", now=now) is None
    assert mis.same_recent(rows, "Old", now=now) is None
    assert mis.same_recent([], "Amen", now=now) is None
