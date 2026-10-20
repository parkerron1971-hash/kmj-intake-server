# __tests__/test_member_quiet_hours.py
#
# Quiet hours and the after-hours alert (Kevin, 2026-10-20: phone alerts for
# group news, "and allow for group to send message with an (after hours
# alert) which allows them to still send a message just incase they might
# have a prayer time outside of the hours"). Pins:
#   1. quiet hours are 9 PM to 7 AM on the church's own clock; a clock that
#      can't be read never holds a note back
#   2. in quiet hours, group news and messages wait for a member who keeps
#      quiet hours (the default); other kinds, and members who turned quiet
#      hours off, hear right away
#   3. an after-hours alert rings through for members who let it, and says so
#   4. after 7 AM the sweep delivers what waited: one note, or one summary;
#      stale notes and kinds switched off overnight are dropped
#   5. in the chat and on the Board: offered only in quiet hours, one a
#      night per person, never on a held message; it shows on the message
#   6. the member's own switches on /my/notifications

import asyncio
import pathlib
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_push as mp
import push_notifications as pn
from test_member_push import FakeSB, church, sub, wired  # noqa: F401


def _at(utc_hour, minute=0):
    return datetime(2026, 10, 21, utc_hour, minute, tzinfo=timezone.utc)


# ── 1. the clock ─────────────────────────────────────────────────────

def test_quiet_hours_are_nine_to_seven():
    assert [h for h in range(24) if mp.is_quiet_hour(h)] == [0, 1, 2, 3, 4, 5, 6, 21, 22, 23]


def test_the_churchs_own_clock(monkeypatch):
    import business_marketing
    monkeypatch.setenv("MEMBER_QUIET_HOURS", "on")
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: ZoneInfo("America/Detroit"))
    biz = {"id": "b", "owner_id": "o", "settings": {}}
    assert mp.quiet_hour(biz, _at(2, 30)) is True        # 10:30 PM in Detroit
    assert mp.quiet_hour(biz, _at(12)) is False          # 8 AM
    assert mp.quiet_hour(biz, _at(10, 59)) is True       # 6:59 AM
    assert mp.quiet_hour(biz, _at(11)) is False          # 7:00 AM


def test_a_clock_nobody_can_read_holds_nothing(monkeypatch):
    import business_marketing
    monkeypatch.setenv("MEMBER_QUIET_HOURS", "on")

    def broken(row):
        raise RuntimeError("profile read failed")
    monkeypatch.setattr(business_marketing, "business_tz", broken)
    assert mp.quiet_hour({"id": "b", "owner_id": "o"}, _at(3)) is False
    monkeypatch.setenv("MEMBER_QUIET_HOURS", "off")
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: ZoneInfo("UTC"))
    assert mp.quiet_hour({"id": "b", "owner_id": "o"}, _at(3)) is False


# ── 2/3. holding and ringing ─────────────────────────────────────────

@pytest.fixture
def night(monkeypatch):
    monkeypatch.setattr(mp, "quiet_hour", lambda business, now=None: True)


def _held(fake):
    return [b for path, body, _ in fake.posts if path.startswith("/member_push_held")
            for b in (body if isinstance(body, list) else [body])]


def test_group_news_waits_for_the_morning(wired, night):
    sent, use = wired
    fake = use(FakeSB(subs=[sub("a"), sub("b"), sub("c")],
                      prefs=[{"contact_id": "b", "off": [], "quiet": False}, {"contact_id": "c", "off": ["groups"]}]))
    n = mp.send(church(groups=True), "groups", title="Sisters in the City", body="Tasha posted: Potluck",
                url="/my/groups/g1/board", tag="group-g1")
    assert n == 1 and [c for c, _, _ in sent] == ["b"]                  # b turned quiet hours off
    assert [(h["contact_id"], h["tag"]) for h in _held(fake)] == [("a", "group-g1")]   # c turned groups off


def test_other_kinds_are_not_held(wired, night):
    sent, use = wired
    fake = use(FakeSB(subs=[sub("a")]))
    assert mp.send(church(live=True, kids=True), "live", title="Live") == 1
    assert mp.send(church(live=True, kids=True), "kids", title="Checked in") == 1
    assert _held(fake) == []


def test_an_after_hours_alert_rings_for_those_who_let_it(wired, night):
    sent, use = wired
    fake = use(FakeSB(subs=[sub("a"), sub("c")], prefs=[{"contact_id": "c", "off": [], "after_hours": False}]))
    mp.send(church(messages=True), "messages", title="New message in Sisters in the City", body="Open the app to read it.",
            url="/my/groups/g1/chat", tag="chat-t1", ring=True)
    assert [c for c, _, _ in sent] == ["a"]
    assert sent[0][1]["title"] == "After-hours alert · New message in Sisters in the City"[:mp.TITLE_MAX]
    assert [h["contact_id"] for h in _held(fake)] == ["c"]


def test_in_the_day_nothing_waits(wired, monkeypatch):
    monkeypatch.setattr(mp, "quiet_hour", lambda business, now=None: False)
    sent, use = wired
    fake = use(FakeSB(subs=[sub("a")]))
    mp.send(church(groups=True), "groups", title="Sisters in the City", ring=True)
    assert [c for c, _, _ in sent] == ["a"] and sent[0][1]["title"] == "Sisters in the City" and _held(fake) == []


# ── 4. the morning ───────────────────────────────────────────────────

class MorningSB(FakeSB):
    def __init__(self, held, prefs=(), on=("groups", "messages")):
        super().__init__(subs=[sub("a"), sub("b"), sub("c")], prefs=list(prefs))
        self.held = held
        self.on = on

    def sb_get_as_service(self, path):
        if path.startswith("/member_push_held"):
            return self.held
        if path.startswith("/businesses"):
            return [{**church(**{k: True for k in self.on}), "owner_id": "o"}]
        if path.startswith("/member_push_subscriptions"):
            cid = path.split("contact_id=eq.")[1].split("&")[0]
            return [s for s in self.subs if s["contact_id"] == cid]
        if path.startswith("/member_push_prefs"):
            cid = path.split("contact_id=eq.")[1].split("&")[0]
            return [p for p in self.prefs if p["contact_id"] == cid]
        return []


def _h(i, cid, kind, title, url, at="2026-10-21T02:00:00+00:00"):
    return {"id": f"h{i}", "business_id": "biz-push-1", "contact_id": cid, "kind": kind, "title": title,
            "body": "Open the app to read it.", "url": url, "tag": f"t{i}", "created_at": at}


def test_the_morning_delivers_what_waited(wired, monkeypatch):
    monkeypatch.setattr(mp, "quiet_hour", lambda business, now=None: False)
    sent, use = wired
    fake = use(MorningSB([
        _h(1, "a", "groups", "Sisters in the City", "/my/groups/g1/board"),
        _h(2, "b", "messages", "New message in Sisters in the City", "/my/groups/g1/chat"),
        _h(3, "b", "groups", "Ministers Alliance", "/my/groups/g2/board"),
        _h(4, "c", "groups", "Old news", "/my/groups/g1/board", at="2026-10-18T02:00:00+00:00"),
    ]))
    n = mp.sweep_held(_at(12))
    assert n == 2
    by = {c: p for c, p, _ in sent}
    assert by["a"]["title"] == "Sisters in the City" and by["a"]["url"] == "/my/groups/g1/board"
    assert by["b"]["title"] == "While you were resting"
    assert "Ministers Alliance" in by["b"]["body"] and "Sisters in the City" in by["b"]["body"]
    assert "c" not in by                                                 # stale: dropped, not sent
    assert len(fake.deletes) == 3 and all(d.startswith("/member_push_held") for d in fake.deletes)


def test_a_kind_switched_off_overnight_is_dropped(wired, monkeypatch):
    monkeypatch.setattr(mp, "quiet_hour", lambda business, now=None: False)
    sent, use = wired
    use(MorningSB([_h(1, "a", "groups", "Sisters", "/my/groups/g1/board"),
                   _h(2, "b", "groups", "Sisters", "/my/groups/g1/board")],
                  prefs=[{"contact_id": "b", "off": ["groups"]}], on=("groups",)))
    mp.sweep_held(_at(12))
    assert [c for c, _, _ in sent] == ["a"]
    use(MorningSB([_h(1, "a", "groups", "Sisters", "/my/groups/g1/board")], on=("messages",)))   # the church turned it off
    sent.clear()
    mp.sweep_held(_at(12))
    assert sent == []


def test_still_quiet_nothing_moves(wired, monkeypatch):
    monkeypatch.setattr(mp, "quiet_hour", lambda business, now=None: True)
    sent, use = wired
    fake = use(MorningSB([_h(1, "a", "groups", "Sisters", "/my/groups/g1/board")]))
    assert mp.sweep_held(_at(4)) == 0 and sent == [] and fake.deletes == []


# ── 5. the chat and the Board ────────────────────────────────────────

from test_member_group_chat import _msg, _page, church as chat_church  # noqa: E402,F401
from test_member_messaging import ANA, BEN, GRP, _group_tid, _send, env  # noqa: E402,F401


@pytest.fixture
def rung(monkeypatch):
    calls = []
    monkeypatch.setattr(mp, "tell_chat", lambda biz, t, acc, sender, ring=False: calls.append(ring))
    return calls


def _quiet(monkeypatch, on):
    monkeypatch.setattr(mp, "quiet_hour", lambda business, now=None: on)


def test_an_alert_in_the_chat_only_in_quiet_hours(chat_church, rung, monkeypatch):
    tid = _group_tid(chat_church, ANA, GRP)
    from test_member_group_chat import _post
    _quiet(monkeypatch, False)
    _post(chat_church, ANA, f"/my/messages/{tid}/send", {"body": "afternoon", "after_hours": "1"})
    assert not _msg(chat_church, "afternoon").get("after_hours") and rung == [False]
    assert "After-hours alert" not in _page(chat_church, ANA, f"/my/groups/{GRP}/chat").text
    _quiet(monkeypatch, True)
    page = _page(chat_church, ANA, f"/my/groups/{GRP}/chat").text
    assert 'name="after_hours"' in page
    _post(chat_church, ANA, f"/my/messages/{tid}/send", {"body": "Can we pray for Dana right now?", "after_hours": "1"})
    assert _msg(chat_church, "Can we pray for Dana right now?")["after_hours"] is True and rung[-1] is True
    assert 'class="gc-ahs"' in _page(chat_church, BEN, f"/my/groups/{GRP}/chat").text


def test_one_alert_a_night(chat_church, rung, monkeypatch):
    tid = _group_tid(chat_church, ANA, GRP)
    from test_member_group_chat import _post
    import member_portal_messaging as mpm
    monkeypatch.setattr(mpm, "alert_since", lambda: "2026-10-01T00:00:00+00:00")   # the fake's clock is Oct 2
    _quiet(monkeypatch, True)
    assert _post(chat_church, ANA, f"/my/messages/{tid}/send", {"body": "first", "after_hours": "1"}).json()["ok"]
    r = _post(chat_church, ANA, f"/my/messages/{tid}/send", {"body": "second", "after_hours": "1"})
    assert r.status_code == 429 and "after-hours alert tonight" in r.json()["error"]
    assert _post(chat_church, ANA, f"/my/messages/{tid}/send", {"body": "second, quietly"}).json()["ok"]
    assert _post(chat_church, BEN, f"/my/messages/{tid}/send", {"body": "Ben's own", "after_hours": "1"}).json()["ok"]


def test_a_held_message_never_rings(chat_church, rung, monkeypatch):
    tid = _group_tid(chat_church, ANA, GRP)
    from test_member_group_chat import _post
    _quiet(monkeypatch, True)
    chat_church.verdict = "harm"
    _post(chat_church, ANA, f"/my/messages/{tid}/send", {"body": "something unkind", "after_hours": "1"})
    m = _msg(chat_church, "something unkind")
    assert m["status"] == "held" and not m.get("after_hours") and rung == []


from test_member_portal_group_space import G, MONIQUE, TASHA, _me, _screen, fake  # noqa: E402,F401
import member_portal_groups as mpg  # noqa: E402
from test_member_portal_group_space import BUSINESS  # noqa: E402


def _board_post(title, alert):
    return asyncio.run(mpg.create_post(BUSINESS, _me(TASHA, "Tasha"), G, title, "Body", False, True, alert))


def test_a_leaders_post_as_an_alert(fake, monkeypatch):
    _screen(monkeypatch, "ok")
    _quiet(monkeypatch, False)
    assert _board_post("In the day", True) == (True, "post_up")
    assert not fake.t["group_posts"][-1].get("after_hours") and fake.rang[-1] is False
    _quiet(monkeypatch, True)
    assert _board_post("Prayer call at 10", True) == (True, "post_up")
    assert fake.t["group_posts"][-1]["after_hours"] is True and fake.rang[-1] is True
    assert _board_post("Another", True) == (False, "alert_used")
    assert _board_post("Another, quietly", False) == (True, "post_up")


def test_the_board_form_offers_it_only_in_quiet_hours():
    assert 'name="after_hours"' not in mpg._compose({"id": G, "name": "Sisters"}, False)
    assert 'name="after_hours"' in mpg._compose({"id": G, "name": "Sisters"}, True)


# ── 6. the member's switches ─────────────────────────────────────────

def test_the_notifications_page_has_quiet_hours_where_they_apply(monkeypatch):
    from starlette.requests import Request as SR
    monkeypatch.setattr(mp, "ready", lambda: True)
    monkeypatch.setattr(mp, "vapid_public", lambda: "k")
    import member_portal
    monkeypatch.setattr(member_portal, "_shell", lambda biz, site, title, body, **k: body)
    req = SR({"type": "http", "query_string": b"", "headers": []})
    me = {"id": "c1", "name": "Ana"}
    page = mp.render_page(church(groups=True), None, req, me, set(), {"quiet": False, "after_hours": True})
    assert 'name="quiet_shown"' in page and "Quiet hours" in page and "Let after-hours alerts ring" in page
    assert 'name="q_quiet" checked' not in page and 'name="q_after" checked' in page   # as they chose
    assert 'name="q_quiet"' not in mp.render_page(church(live=True), None, req, me, set(), None)


def test_saving_quiet_hours(monkeypatch):
    fake = FakeSB()
    monkeypatch.setattr(mp, "sb_clients", fake)
    assert mp.save_quiet("b", "c", False, True)
    path, body, prefer = fake.posts[-1]
    assert path.startswith("/member_push_prefs?on_conflict=business_id,contact_id")
    assert body["quiet"] is False and body["after_hours"] is True and "merge-duplicates" in prefer
    assert "off" not in body                                   # the kinds they turned off stay as they were


def test_the_page_saves_quiet_hours_only_when_it_showed_them(monkeypatch):
    import member_portal_church as mpc
    import member_spaces as msp
    from test_member_spaces_push import _form
    saved = []

    async def signed_in(request):
        return {"business": church(groups=True, messages=True)}, {"id": "m1"}, False
    monkeypatch.setattr(mpc, "_signed_in", signed_in)
    monkeypatch.setattr(mpc, "_allowed", lambda c, m: True)
    monkeypatch.setattr(mp, "save_turned_off", lambda b, c, off: True)
    monkeypatch.setattr(mp, "turned_off", lambda b, c: set())
    monkeypatch.setattr(mp, "save_quiet", lambda b, c, quiet, after: saved.append((quiet, after)) or True)
    monkeypatch.setattr(msp, "resolve", lambda b, me, wanted="": {"space": "church", "options": ["church"]})
    asyncio.run(mp.my_notifications_save(_form(b"k_groups=on&quiet_shown=1&q_after=on")))
    assert saved == [(False, True)]                     # quiet hours off, after-hours alerts still ring
    asyncio.run(mp.my_notifications_save(_form(b"k_groups=on")))
    assert saved == [(False, True)]                     # not shown: left as it was
