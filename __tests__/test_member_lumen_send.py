# __tests__/test_member_lumen_send.py
#
# Look 5.1's share sheet: "Send to someone at church" (Kevin approved, after
# #1986 left the mock's last row out). Pins:
#   - the row is on the sheet only while Messages' own count for the page says
#     the church's chats are on and this member may chat (a birthdate, their
#     switch on, the guidelines agreed); no read more, unknown is hidden;
#   - it opens Messages' picker, /my/messages?say=<title and public link>: the
#     note on top, then only conversations a member writes in (group chats while
#     open, private chats) and Start a chat, each carrying the note; never the
#     church office, chat requests or Your teens; the messaging rules hold
#     (teens, blocks, the church's switch, a member who can't chat sees the gate);
#   - choosing someone opens the conversation with the note IN THE BOX, unsent;
#   - `say` is capped, one line, escaped on the page and quoted in links;
#   - without `say` every page is as it was.

import pathlib
import re
import sys
from datetime import timedelta
from urllib.parse import quote

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_lumen_share as mls
import member_portal_messaging as mpm
import member_portal_threads as mpt
import test_church_threads as tct
import test_member_messaging as tmm
from test_church_threads import fake  # noqa: F401  (fixture)
from test_member_group_chat import _page as group_page, church as gchurch  # noqa: F401  (fixture)
from test_member_messaging import env  # noqa: F401  (fixture)

SAY = "Hope Has a Name https://grace.church/sermons/0f8e6b7a-1c2d-4e5f-8a9b-0c1d2e3f4a5b"
Q = quote(SAY, safe="")


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    mpt._COUNTS.clear()
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    yield
    mpt._COUNTS.clear()


class _Req:
    def __init__(self, q):
        self.query_params = q


def _main(html):
    return html[html.index("<main"):html.index("</main>")]


# ─── the note ────────────────────────────────────────────────────────


def test_say_is_one_line_capped_and_quoted():
    assert mpm.say_of(_Req({})) == ""
    assert mpm.say_of(_Req({"say": "  Hope\x00 Has\n\ta   Name  "})) == "Hope Has a Name"
    assert len(mpm.say_of(_Req({"say": "x" * 5000}))) == mpm.SAY_MAX == mls.SAY_MAX
    assert mpm.with_say("/my/messages/to/a", "") == "/my/messages/to/a"
    assert mpm.with_say("/my/messages/to/a", 'A & "B" https://x.org/?a=1') == (
        "/my/messages/to/a?say=A%20%26%20%22B%22%20https%3A%2F%2Fx.org%2F%3Fa%3D1")


# ─── when the row shows ──────────────────────────────────────────────


def test_the_row_rides_on_messages_own_count():
    tok = mpt.NOW.set({"chats": True, "total": 0})
    try:
        assert mls.send_open() is True
        mpt.NOW.set({"chats": False, "total": 3})
        assert mls.send_open() is False
        mpt.NOW.set(None)                                                      # not read: hidden
        assert mls.send_open() is False
    finally:
        mpt.NOW.reset(tok)
    assert mls.page_js("<a class=lm-share>", send=True).endswith('defer data-send="1"></script>')
    assert 'data-send' not in mls.page_js("<a class=lm-share>") and mls.page_js("<p>", send=True) == ""


def test_counts_says_whether_this_member_may_chat(fake, monkeypatch):  # noqa: F811
    import asyncio
    biz, ana = fake.biz[tct.BIZ], next(c for c in fake.t["contacts"] if c["id"] == tct.ANA)
    got = asyncio.run(mpt.counts(biz, ana))
    assert got is not None and got["chats"] is False                          # the church's chats are off
    tct._chats_on(fake, tct.ANA, tct.BEN)
    mpt._COUNTS.clear()
    fake.gets.clear()
    got = asyncio.run(mpt.counts(biz, ana))
    assert got["chats"] is True
    profile_reads = [g for g in fake.gets if g.startswith("/msg_members")]
    assert len(profile_reads) == 1                                            # the read counts already made
    for m in fake.t["msg_members"]:
        if m["contact_id"] == tct.ANA:
            m["guidelines_at"] = None                                         # hasn't agreed to the guidelines
    mpt._COUNTS.clear()
    assert asyncio.run(mpt.counts(biz, ana))["chats"] is False


# ─── the picker (church threads open: the one inbox) ─────────────────


def _together(fake, monkeypatch):  # noqa: F811
    tct._seed_conversation(fake)
    tct._chats_on(fake, tct.ANA, tct.BEN, tct.CAL)
    gtid = tct._group_chat(fake, last_read=tct.iso(tct.NOW - timedelta(minutes=45)))
    dtid = tct._direct_chat(fake, tct.BEN)
    rtid = tct._direct_chat(fake, tct.CAL, state="requested")
    monkeypatch.setattr(mpt, "_zone", lambda biz: tct.timezone.utc)
    return tct._app(fake, monkeypatch, tct.ANA), gtid, dtid, rtid


def test_the_picker_carries_the_note_to_people_and_groups(fake, monkeypatch):  # noqa: F811
    c, gtid, dtid, rtid = _together(fake, monkeypatch)
    plain = c.get("/my/messages").text
    assert "lm-say" not in plain and 'href="/my/inbox/church"' in _main(plain)     # without say, as it was
    html = c.get(f"/my/messages?say={Q}").text
    main = _main(html)
    card = main[main.index('<div class="lm-req lm-say">'):]
    assert "<b>Send to someone at church</b>" in card and SAY in card
    assert "Your note waits in the box until you press Send." in main
    hrefs = re.findall(r'href="([^"]+)"', main[main.index('class="lm-req lm-say"'):])
    assert f"/my/groups/{tct.GROUP}/chat?say={Q}" in hrefs                     # the group's chat
    assert f"/my/messages/{dtid}?say={Q}" in hrefs                             # a private chat
    assert "/my/inbox/church" not in hrefs and "lm-pin" not in main          # never the church office
    assert "wants to chat" not in main and f"/my/messages/{rtid}/accept" not in main   # nor a request
    assert all("say=" in h for h in hrefs if h.startswith(("/my/messages/", "/my/groups/")))
    assert not [w for w in fake.writes if w[1] == "msg_messages"]            # nothing sent


def test_the_note_is_escaped_on_the_page_and_quoted_in_links(fake, monkeypatch):  # noqa: F811
    c, *_ = _together(fake, monkeypatch)
    evil = '<script>alert(1)</script> "x" https://grace.church/'
    main = _main(c.get(f"/my/messages?say={quote(evil, safe='')}").text)
    assert "<script>alert(1)" not in main and "&lt;script&gt;alert(1)&lt;/script&gt; &quot;x&quot;" in main
    assert f"say={quote(evil, safe='')}" in main


def test_a_member_who_cant_chat_sees_the_gate_not_the_picker(fake, monkeypatch):  # noqa: F811
    c, *_ = _together(fake, monkeypatch)
    fake.t["msg_members"] = [m for m in fake.t["msg_members"] if m["contact_id"] != tct.ANA]
    main = _main(c.get(f"/my/messages?say={Q}").text)
    assert "lm-say" not in main and "say=" not in main
    fake.biz[tct.BIZ]["settings"]["messaging"] = {"enabled": False}           # the church's chats off
    main = _main(c.get(f"/my/messages?say={Q}").text)
    assert "lm-say" not in main and "say=" not in main


# ─── the picker (church threads closed), the rules, the conversation ─


def test_start_a_chat_carries_the_note_and_keeps_the_rules(env):  # noqa: F811
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    main = _main(tmm._member(env, tmm.ANA).get(f"/my/messages?say={Q}").text)
    assert "<b>Send to someone at church</b>" in main
    assert f'href="/my/messages/{tid}?say={Q}"' in main                       # the chat with Ben
    starts = re.findall(r'href="/my/messages/to/([^"?]+)\?say=', main)
    assert starts and all(s != tmm.ANA for s in starts)
    # A teen's picker lists no adult outside their family (member_messaging_rules: no private adult-teen chats).
    teen = _main(tmm._member(env, tmm.TEEN).get(f"/my/messages?say={Q}").text)
    for adult in (tmm.ANA, tmm.BEN, tmm.CARL):
        assert f"/my/messages/to/{adult}?" not in teen


def test_choosing_someone_opens_the_conversation_with_the_note_unsent(env):  # noqa: F811
    before = len(env.t.get("msg_messages", []))
    r = tmm._member(env, tmm.ANA).get(f"/my/messages/to/{tmm.BEN}?say={Q}")
    assert r.status_code == 200
    box = re.search(r'<input id="mb-say"[^>]*>', r.text).group(0)
    assert f'value="{SAY}"' in box
    assert len(env.t.get("msg_messages", [])) == before                        # the member presses Send
    # A block holds: a blocked pair never opens with a note.
    tid = tmm._tid(tmm._start(env, tmm.ANA, tmm.BEN))
    tmm._member(env, tmm.BEN).post(f"/my/messages/{tid}/block", headers=tmm.ORIGIN, follow_redirects=False)
    r = tmm._member(env, tmm.ANA).get(f"/my/messages/to/{tmm.BEN}?say={Q}", follow_redirects=False)
    assert r.status_code == 303 and "say=" not in r.headers["location"]


def test_a_groups_chat_opens_with_the_note_in_the_box(gchurch, monkeypatch):  # noqa: F811
    html = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}/chat?say={Q}").text
    box = re.search(r'<input id="gc-say"[^>]*>', html).group(0)
    assert f'value="{SAY}"' in box and "required" in box                    # in the box, the member presses Send
    plain = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}/chat").text
    assert 'value=' not in re.search(r'<input id="gc-say"[^>]*>', plain).group(0)    # as it was
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    old = group_page(gchurch, tmm.ANA, f"/my/groups/{tmm.GRP}/chat?say={Q}").text
    assert 'value=' not in re.search(r'<input id="gc-say"[^>]*>', old).group(0)      # today's look: no picker
