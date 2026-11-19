# __tests__/test_member_alerts.py
#
# The member app's recent alerts: the bell's list on /my/notifications and
# its dot (member_alerts.py; Kevin, 2026-11-18: "yes build the bell list").
# Pins:
#   1. the kinds: what was really sent to this member (their notes, the
#      church-wide ones, the office's replies, their chats), only their kinds
#   2. privacy: a message or a prayer note says that something happened,
#      never what was written
#   3. seen and unseen: the dot flips on a new alert and off on opening the
#      page; it is kept, and a failure is never kept
#   4. the switches: MEMBER_ALERTS_LIST and the redesign's MEMBER_LUMEN
#   5. empty and failed reads: "Nothing yet"; a failed read shows the page
#      without the list, never a 500
#   6. speed: no other page reads anything for it
# Every person and church here is made up.

import asyncio
import pathlib
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import church_threads as ct
import member_alerts as ma
import member_push
import push_notifications as pn
import sb_clients

BIZ = "11111111-1111-1111-1111-111111111111"
ME = "22222222-2222-2222-2222-222222222222"
OTHER = "33333333-3333-3333-3333-333333333333"
G1 = "44444444-4444-4444-4444-444444444444"        # a group I'm in
G2 = "55555555-5555-5555-5555-555555555555"        # a group I'm not in
T_DIRECT, T_DECLINED, T_MUTED = (f"aaaaaaaa-0000-0000-0000-00000000000{i}" for i in (1, 2, 3))
T_G1, T_G2, T_LEADERS = (f"bbbbbbbb-0000-0000-0000-00000000000{i}" for i in (1, 2, 3))
R1 = "cccccccc-0000-0000-0000-000000000001"         # my prayer request

ALL_KINDS = {k: True for k in member_push.KIND_KEYS}


def church(kinds=None, chats=True, name="First Light Church"):
    return {"id": BIZ, "name": name,
            "settings": {"member_portal": {"enabled": True, "notifications": ALL_KINDS if kinds is None else kinds},
                         "messaging": {"enabled": chats}}}


def note(kind, title, body="", at="2026-11-17T15:00:00+00:00", url="/my", contact=ME, thread="church", **kw):
    return {"id": f"n-{kind}-{at}", "contact_id": contact, "thread": thread, "direction": "church", "kind": kind,
            "title": title, "body": body, "url": url, "created_at": at, **kw}


class FakeSB:
    """Answers each table from a list; counts what it was asked."""

    def __init__(self, **tables):
        self.t = {"church_thread_notes": [], "church_thread_reads": [], "member_push_prefs": [{"off": []}],
                  "member_push_sends": [], "ministry_care_requests": [], "msg_members": [{"enabled": True}],
                  "msg_participants": [], "group_members": [{"group_id": G1, "role": "member"}],
                  "msg_threads": [], "msg_messages": [], "groups": [{"id": G1, "name": "Young Adults"}],
                  "businesses": []}
        self.t.update(tables)
        self.asked, self.posts = [], []

    def sb_get_as_service(self, path, **k):
        self.asked.append(path)
        table = path.lstrip("/").split("?")[0]
        rows = self.t.get(table, [])
        if rows is None:
            return None
        if table == "member_push_sends" and "kind=eq.prayer" in path:
            return [r for r in rows if r.get("kind") == "prayer"]
        if table == "member_push_sends":
            return [r for r in rows if r.get("kind") != "prayer"]
        return list(rows)

    def sb_post_as_service(self, path, body, prefer=None, **k):
        self.posts.append((path, body))
        return [] if "return=minimal" in (prefer or "") else [body]


@pytest.fixture
def sb(monkeypatch):
    """Threads open and their tables there; every read from a FakeSB."""
    ma.forget()
    monkeypatch.delenv("MEMBER_ALERTS_LIST", raising=False)
    monkeypatch.setattr(ct, "open_for", lambda biz: True)
    monkeypatch.setattr(ct, "tables_ready", lambda fresh=False: True)

    def use(fake):
        monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.sb_get_as_service)
        monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.sb_post_as_service)
        return fake
    yield use
    ma.forget()


# ── 1. the kinds ─────────────────────────────────────────────────────

def test_the_list_is_what_was_sent_to_this_member_newest_first(sb):
    fake = sb(FakeSB(church_thread_notes=[
        note("events", "Tomorrow: Fall Picnic", "You said you're coming. See you there.",
             at="2026-11-17T21:00:00+00:00", url="/my/events"),
        note("sermons", "New: Light for the Road", "Pastor Sam Hill", at="2026-11-16T14:00:00+00:00",
             url="/my/sermons/9", contact=None),
        note("groups", "Young Adults", "Jo posted: Retreat signup", at="2026-11-15T18:00:00+00:00",
             url=f"/my/groups/{G1}/board", thread=f"group:{G1}"),
        note("news", "First Light Church", "Important: Thanksgiving service times",
             at="2026-11-14T12:00:00+00:00", url="/my/news/5"),
        note("prayer", "Someone prayed for you", "First Light Church prayed for your request.",
             at="2026-11-13T12:00:00+00:00", url="/my/prayer"),
    ]))
    rows = ma.recent_alerts(church(chats=False), ME)
    assert [r["kind"] for r in rows] == ["events", "sermons", "groups", "news", "prayer"]
    assert rows[0] == {"kind": "events", "label": "Event reminders", "title": "Tomorrow: Fall Picnic",
                       "body": "You said you're coming. See you there.",
                       "when": "2026-11-17T21:00:00.000000+00:00", "link": "/my/events"}
    assert rows[2]["title"] == "Young Adults" and rows[2]["body"] == "Jo posted: Retreat signup"
    # News carries the church's name as its title: the line is what it said.
    assert rows[3]["title"] == "Important: Thanksgiving service times" and rows[3]["body"] == ""
    assert rows[1]["label"] == "New sermons" and rows[1]["link"] == "/my/sermons/9"
    notes_read = next(p for p in fake.asked if p.startswith("/church_thread_notes"))
    # Their own rows and the church-wide ones, from the church only.
    assert f"or=(contact_id.eq.{ME},and(contact_id.is.null,thread.eq.church))" in notes_read
    assert "direction=eq.church" in notes_read


def test_only_their_kinds_the_churchs_switch_and_their_own(sb):
    sb(FakeSB(church_thread_notes=[note("events", "Tomorrow: Fall Picnic", at="2026-11-17T21:00:00+00:00"),
                                   note("sermons", "New: Light", at="2026-11-16T21:00:00+00:00", contact=None),
                                   note("kids", "Mia is checked in", at="2026-11-15T21:00:00+00:00")],
              member_push_prefs=[{"off": ["sermons"]}]))
    rows = ma.recent_alerts(church(kinds={"events": True, "sermons": True}, chats=False), ME)
    assert [r["kind"] for r in rows] == ["events"]          # sermons off by them, kids off by the church


def test_the_list_stops_at_its_limit(sb):
    sb(FakeSB(church_thread_notes=[note("events", f"Tomorrow: Night {i}", at=f"2026-11-{10 + i:02d}T12:00:00+00:00")
                                   for i in range(8)]))
    rows = ma.recent_alerts(church(chats=False), ME, limit=3)
    assert [r["title"] for r in rows] == ["Tomorrow: Night 7", "Tomorrow: Night 6", "Tomorrow: Night 5"]


def test_chats_only_the_ones_that_reach_this_member(sb):
    msgs = [{"thread_id": t, "created_at": f"2026-11-17T1{i}:00:00+00:00", "body": "SECRET WORDS"}
            for i, t in enumerate([T_DIRECT, T_DECLINED, T_MUTED, T_G1, T_G2, T_LEADERS])]
    msgs.append({"thread_id": T_DIRECT, "created_at": "2026-11-16T09:00:00+00:00"})   # older: same chat
    fake = sb(FakeSB(
        msg_participants=[{"thread_id": T_DIRECT, "state": "accepted"},
                          {"thread_id": T_DECLINED, "state": "declined"},
                          {"thread_id": T_MUTED, "state": "accepted", "muted": True},
                          {"thread_id": T_G2, "state": "accepted"},
                          {"thread_id": T_LEADERS, "state": "accepted", "notify": "evening"}],
        msg_threads=[{"id": T_DIRECT, "kind": "direct"}, {"id": T_DECLINED, "kind": "direct"},
                     {"id": T_MUTED, "kind": "direct"}, {"id": T_G1, "kind": "group", "group_id": G1},
                     {"id": T_G2, "kind": "group", "group_id": G2}, {"id": T_LEADERS, "kind": "leaders"}],
        msg_messages=msgs))
    rows = ma.recent_alerts(church(), ME)
    assert [(r["title"], r["link"]) for r in rows] == [
        ("New message in Young Adults", f"/my/groups/{G1}/chat"),     # in the group, every message
        ("New message", f"/my/messages/{T_DIRECT}"),                  # one row per chat, its newest
    ]
    assert all(r["kind"] == "messages" and r["label"] == "New messages" and r["body"] == "" for r in rows)
    msg_read = next(p for p in fake.asked if p.startswith("/msg_messages"))
    assert f"sender_contact_id=neq.{ME}" in msg_read and "status=eq.delivered" in msg_read
    assert "select=thread_id,created_at&" in msg_read                   # never the words
    assert T_DECLINED not in msg_read and T_MUTED not in msg_read and T_G2 not in msg_read


def test_no_chats_with_messages_off_or_messaging_off(sb):
    parts = [{"thread_id": T_DIRECT, "state": "accepted"}]
    threads = [{"id": T_DIRECT, "kind": "direct"}, {"id": T_G1, "kind": "group", "group_id": G1}]
    msgs = [{"thread_id": T_DIRECT, "created_at": "2026-11-17T10:00:00+00:00"},
            {"thread_id": T_G1, "created_at": "2026-11-17T11:00:00+00:00"}]
    fake = sb(FakeSB(msg_participants=parts, msg_threads=threads, msg_messages=msgs,
                     member_push_prefs=[{"off": ["messages"]}]))
    assert ma.recent_alerts(church(), ME) == []
    # Their first round is read alongside their choices; nothing after it.
    assert not any(p.startswith(("/msg_threads", "/msg_messages")) for p in fake.asked)
    fake.asked.clear()
    assert ma.recent_alerts(church(), ME, off={"messages"}) == []
    assert not any(p.startswith("/msg_") for p in fake.asked)            # told up front: none at all
    ma.forget()
    sb(FakeSB(msg_participants=parts, msg_threads=threads, msg_messages=msgs, msg_members=[{"enabled": False}]))
    # Their messaging switch is off: no group chat, a direct chat still counts.
    assert [r["link"] for r in ma.recent_alerts(church(), ME)] == [f"/my/messages/{T_DIRECT}"]


def test_while_threads_are_closed_only_what_names_this_member(sb, monkeypatch):
    monkeypatch.setattr(ct, "open_for", lambda biz: False)
    fake = sb(FakeSB(
        member_push_sends=[{"kind": "live", "title": "First Light Church is live", "body": "Sunday",
                            "url": "/my/live", "created_at": "2026-11-16T15:00:00+00:00"},
                           {"kind": "sermons", "title": "New: Light", "body": "", "url": "/my/sermons/2",
                            "created_at": "2026-11-15T15:00:00+00:00"},
                           {"kind": "prayer", "title": "Someone prayed for you",
                            "body": "First Light Church prayed for your request.", "url": "/my/prayer",
                            "created_at": "2026-11-14T15:00:00+00:00"}],
        ministry_care_requests=[{"id": R1}]))
    rows = ma.recent_alerts(church(chats=False), ME)
    assert [r["kind"] for r in rows] == ["live", "sermons", "prayer"]
    assert not any(p.startswith("/church_thread_notes") for p in fake.asked)
    wide = next(p for p in fake.asked if p.startswith("/member_push_sends") and "kind=in." in p)
    assert "kind=in.(announcements,live,sermons)" in wide
    prayed = next(p for p in fake.asked if "kind=eq.prayer" in p)
    assert f"%22prayed%3A{R1}%22" in prayed                  # only the claim for their own request
    assert any(p.startswith("/ministry_care_requests") and f"contact_id=eq.{ME}" in p and "select=id&" in p
               for p in fake.asked)


# ── 2. privacy ───────────────────────────────────────────────────────

def test_a_message_or_prayer_says_that_it_happened_never_what_was_written(sb):
    secret = "please pray my brother gets the job"
    sb(FakeSB(church_thread_notes=[
        note("reply", None, "Hi Ana, here is the private answer", at="2026-11-17T16:00:00+00:00"),
        note("prayer", "Someone prayed for you", "First Light Church prayed for your request.",
             at="2026-11-17T15:00:00+00:00", url="/my/prayer"),
        note("groups", "Young Adults", "Jo asked the group to pray", at="2026-11-17T14:00:00+00:00",
             url=f"/my/groups/{G1}/prayer", thread=f"group:{G1}"),
    ], msg_participants=[{"thread_id": T_DIRECT, "state": "accepted"}],
        msg_threads=[{"id": T_DIRECT, "kind": "direct"}],
        msg_messages=[{"thread_id": T_DIRECT, "created_at": "2026-11-17T13:00:00+00:00", "body": secret}]))
    rows = ma.recent_alerts(church(), ME)
    assert rows[0] == {"kind": "messages", "label": "New messages", "title": "New message from the church",
                       "body": "", "when": "2026-11-17T16:00:00.000000+00:00", "link": "/my/inbox/church"}
    html = ma.render_recent(rows, zone=timezone.utc)
    assert "private answer" not in html and secret not in html
    assert "Someone prayed for you" in html and "Jo asked the group to pray" in html and "New message" in html


def test_everything_is_escaped(sb):
    sb(FakeSB(church_thread_notes=[note("announcements", "<script>alert(1)</script>", "a & b", contact=None)]))
    html = ma.render_recent(ma.recent_alerts(church(chats=False), ME), zone=timezone.utc)
    assert "<script>alert" not in html and "&lt;script&gt;" in html and "a &amp; b" in html


def test_a_link_only_ever_opens_a_member_page(sb):
    sb(FakeSB(church_thread_notes=[note("announcements", "Hello", url="https://elsewhere.example/x", contact=None)]))
    assert ma.recent_alerts(church(chats=False), ME)[0]["link"] == "/my"


# ── 3. seen and unseen ───────────────────────────────────────────────

def test_the_dot_flips_on_a_new_alert_and_off_when_the_page_is_opened(sb):
    fake = sb(FakeSB(church_thread_notes=[note("events", "Tomorrow: Fall Picnic", at="2026-11-17T21:00:00+00:00")],
                     church_thread_reads=[{"read_at": "2026-11-17T20:00:00+00:00"}]))
    assert ma.alerts_unseen(church(chats=False), ME) is True
    # Kept: a second look reads nothing.
    before = len(fake.asked)
    assert ma.alerts_unseen(church(chats=False), ME) is True
    assert len(fake.asked) == before
    # Opening the page: the dot goes at once, and the last look is saved.
    assert ma.mark_seen(church(), ME, now=datetime(2026, 11, 17, 22, tzinfo=timezone.utc)) is True
    assert ma.alerts_unseen(church(chats=False), ME) is False
    path, body = fake.posts[-1]
    assert path.startswith("/church_thread_reads?on_conflict=business_id,contact_id,thread")
    assert body == {"business_id": BIZ, "contact_id": ME, "thread": "alerts",
                    "read_at": "2026-11-17T22:00:00+00:00"}
    # Another server copy, after it: nothing new.
    ma.forget()
    fake.t["church_thread_reads"] = [{"read_at": "2026-11-17T22:00:00+00:00"}]
    assert ma.alerts_unseen(church(chats=False), ME) is False
    # Something new arrives: the dot comes back once the kept answer is old.
    ma.forget()
    fake.t["church_thread_notes"].insert(0, note("sermons", "New: Light", at="2026-11-18T01:00:00+00:00",
                                                  contact=None))
    assert ma.alerts_unseen(church(chats=False), ME) is True


def test_never_opened_means_everything_is_new(sb):
    sb(FakeSB(church_thread_notes=[note("events", "Tomorrow: Fall Picnic")]))
    assert ma.alerts_unseen(church(chats=False), ME) is True
    sb(FakeSB())
    ma.forget()
    assert ma.alerts_unseen(church(chats=False), ME) is False       # nothing at all: no dot


def test_rows_since_the_last_look_are_marked_new_on_the_page(sb):
    sb(FakeSB(church_thread_notes=[note("events", "Tomorrow: Fall Picnic", at="2026-11-17T21:00:00+00:00"),
                                   note("sermons", "New: Light", at="2026-11-16T21:00:00+00:00", contact=None)]))
    rows = ma.recent_alerts(church(chats=False), ME)
    html = ma.render_recent(rows, zone=timezone.utc, seen="2026-11-17T00:00:00+00:00")
    assert html.count('class="al-row is-new"') == 1 and ">New, </span>" in html
    same = ma.render_recent(rows, zone=timezone.utc, seen="2026-11-17T21:00:00Z")      # seen it exactly
    assert 'class="al-row is-new"' not in same


def test_the_dot_is_hidden_when_it_cant_be_told_and_a_failure_is_never_kept(sb, monkeypatch):
    fake = sb(FakeSB(church_thread_notes=[note("events", "Tomorrow: Fall Picnic")], church_thread_reads=None))
    assert ma.alerts_unseen(church(chats=False), ME) is False          # the last look couldn't be read
    fake.t["church_thread_reads"] = []
    assert ma.alerts_unseen(church(chats=False), ME) is True           # ...and that "no" wasn't kept
    ma.forget()
    fake.t["church_thread_notes"] = None
    assert ma.alerts_unseen(church(chats=False), ME) is False          # the notes couldn't be read
    ma.forget()
    monkeypatch.setattr(ct, "tables_ready", lambda fresh=False: False)
    fake.t["church_thread_notes"] = [note("events", "Tomorrow: Fall Picnic")]
    assert ma.alerts_unseen(church(chats=False), ME) is False          # nowhere to keep the last look
    assert ma.mark_seen(church(), ME) is False
    monkeypatch.setattr(ct, "tables_ready", lambda fresh=False: True)
    monkeypatch.setenv("MEMBER_ALERTS_LIST", "off")
    assert ma.alerts_unseen(church(chats=False), ME) is False          # the switch


def test_the_dots_chats_are_kept_and_the_dot_reads_no_group_names(sb):
    fake = sb(FakeSB(msg_participants=[{"thread_id": T_DIRECT, "state": "accepted"}],
                     msg_threads=[{"id": T_DIRECT, "kind": "direct"}, {"id": T_G1, "kind": "group", "group_id": G1}],
                     msg_messages=[{"thread_id": T_G1, "created_at": "2026-11-17T11:00:00+00:00"}]))
    assert ma.alerts_unseen(church(), ME) is True
    assert not any(p.startswith("/groups") for p in fake.asked)
    first = len([p for p in fake.asked if p.startswith("/msg_participants")])
    ma._dot_kept().clear()                                           # the dot is old, the chats aren't
    ma.alerts_unseen(church(), ME)
    assert len([p for p in fake.asked if p.startswith("/msg_participants")]) == first


# ── 5. empty and failed reads ────────────────────────────────────────

def test_nothing_yet(sb):
    sb(FakeSB())
    rows = ma.recent_alerts(church(), ME)
    assert rows == []
    html = ma.render_recent(rows, zone=timezone.utc)
    assert "Nothing yet" in html and "Recent" in html


@pytest.mark.parametrize("table", ["church_thread_notes", "member_push_prefs", "msg_members", "msg_participants",
                                   "group_members", "msg_threads", "msg_messages", "groups"])
def test_a_failed_read_is_no_list(sb, table):
    fake = FakeSB(church_thread_notes=[note("events", "Tomorrow: Fall Picnic")],
                  msg_participants=[{"thread_id": T_DIRECT, "state": "accepted"}],
                  msg_threads=[{"id": T_DIRECT, "kind": "direct"}, {"id": T_G1, "kind": "group", "group_id": G1}],
                  msg_messages=[{"thread_id": T_G1, "created_at": "2026-11-17T11:00:00+00:00"}])
    fake.t[table] = None
    sb(fake)
    assert ma.recent_alerts(church(), ME) is None
    assert ma.render_recent(None) == ""


def test_a_read_that_raises_is_no_list_and_never_an_error(sb, monkeypatch):
    sb(FakeSB())
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert ma.recent_alerts(church(), ME) is None
    assert ma.alerts_unseen(church(), ME) is False


def test_made_up_ids_read_nothing(sb):
    fake = sb(FakeSB())
    assert ma.recent_alerts({"id": "not-a-church"}, ME) is None
    assert ma.alerts_unseen(church(), "x") is False
    assert fake.asked == []


# ── times, on the church's clock ─────────────────────────────────────

def test_times_are_on_the_churchs_clock():
    chicago = ZoneInfo("America/Chicago")
    now = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)          # noon in Chicago
    assert ma.when_label("2026-11-18T15:12:00+00:00", chicago, now) == "9:12 AM"
    assert ma.when_label("2026-11-18T03:30:00+00:00", chicago, now) == "Yesterday"   # 9:30 PM the 17th there
    assert ma.when_label("2026-11-14T15:00:00+00:00", chicago, now) == "Sat"
    assert ma.when_label("2026-11-03T15:00:00+00:00", chicago, now) == "Nov 3"
    assert ma.when_label("2025-11-03T15:00:00+00:00", chicago, now) == "Nov 3, 2025"
    assert ma.when_label("not a time", chicago, now) == ""


def test_a_row_opens_its_link_and_one_without_stays_put():
    rows = [{"kind": "events", "label": "Event reminders", "title": "Tomorrow: Fall Picnic", "body": "",
             "when": "2026-11-17T21:00:00+00:00", "link": "/my/events"},
            {"kind": "prayer", "label": "Prayer", "title": "Someone prayed for you", "body": "",
             "when": "2026-11-16T21:00:00+00:00", "link": ""}]
    html = ma.render_recent(rows, zone=timezone.utc)
    assert '<a class="al-row" href="/my/events">' in html and '<div class="al-row">' in html
    assert 'class="al-ic h-coral"' in html and 'class="al-ic h-brand"' in html


# ── 4. the page and its switches ─────────────────────────────────────

def _page_html(recent):
    import member_portal  # noqa: F401  (render_page's shell)
    req = SimpleNamespace(query_params={})
    return member_push.render_page(church({"live": True, "events": True}), None, req,
                                   {"id": ME, "name": "Ana Rivers"}, set(), recent=recent)


def test_the_page_shows_your_alerts_then_the_settings(monkeypatch):
    monkeypatch.setattr(pn, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(pn, "VAPID_PUBLIC_KEY", "pub-key")
    old = _page_html(None)
    assert "Your <em>alerts</em>" not in old and "What reaches this phone" not in old
    rows = [{"kind": "events", "label": "Event reminders", "title": "Tomorrow: Fall Picnic", "body": "",
             "when": "2026-11-17T21:00:00+00:00", "link": "/my/events"}]
    new = _page_html(ma.render_recent(rows, zone=timezone.utc))
    assert new.index("Your <em>alerts</em>") < new.index("Recent") < new.index("What reaches this phone") \
        < new.index('name="k_live"')
    failed = _page_html("")                                           # the list couldn't load
    assert "Your <em>alerts</em>" in failed and "Recent" not in failed and 'name="k_live"' in failed


# ── 4b. the page, through member_portal.serve ────────────────────────

MEMBER = {"id": ME, "name": "Ana Rivers", "email": "ana@example.test", "birthdate": "1980-05-01"}
PLATFORM = "owner@platform.test"


@pytest.fixture
def page(sb, monkeypatch):
    """member_portal.serve for one signed-in member at a made-up church,
    every read faked; records what the list read and what was marked."""
    import church_follow_up as cfu
    import giving_router
    import member_asks
    import member_cache
    import member_portal as mp
    member_cache.forget_all()
    biz = church({"live": True, "events": True})
    who = {"me": dict(MEMBER), "preview": False, "email": "ana@example.test"}
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": dict(biz), "site": {"slug": "first-light"}})
    monkeypatch.setattr(mp, "portal_active", lambda b: True)
    monkeypatch.setattr(mp, "_session_for", lambda req, ch: {
        "claims": {"em": who["email"], "cid": ME}, "people": [who["me"]], "me": who["me"], "preview": who["preview"]})
    monkeypatch.setattr(cfu, "is_church", lambda b: False)
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    monkeypatch.setattr(pn, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(pn, "VAPID_PUBLIC_KEY", "pub-key")
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", PLATFORM)
    monkeypatch.setattr(member_asks, "platform_church", lambda bid: str(bid) == BIZ)
    monkeypatch.setattr(ma, "zone_of", lambda b: ZoneInfo("America/Chicago"))
    marked, lists = [], []
    monkeypatch.setattr(ma, "mark_seen_later", lambda b, cid: marked.append(str(cid)))
    real = ma.recent_alerts

    def spy(*a, **k):
        lists.append(a)
        return who["rows"](*a, **k) if "rows" in who else real(*a, **k)
    monkeypatch.setattr(ma, "recent_alerts", spy)
    sb(FakeSB(church_thread_notes=[note("events", "Tomorrow: Fall Picnic", "You said you're coming. See you there.",
                                        url="/my/events")]))
    who.update(marked=marked, lists=lists)
    return who


def _get(path="/my/notifications"):
    import member_portal as mp
    from starlette.requests import Request
    host = "first-light.mysolutionist.app"
    req = Request({"type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "query_string": b"",
                   "scheme": "https", "server": (host, 443), "client": ("127.0.0.1", 1), "root_path": "",
                   "headers": [(b"host", host.encode())]})
    return asyncio.run(mp.serve(req, path))


def test_with_the_new_look_on_the_page_lists_and_marks_seen(page, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    resp = _get()
    html = resp.body.decode()
    assert resp.status_code == 200
    assert "Your <em>alerts</em>" in html and "Tomorrow: Fall Picnic" in html and 'href="/my/events"' in html
    assert html.index("Recent") < html.index("What reaches this phone") < html.index('name="k_live"')
    assert page["marked"] == [ME]


@pytest.mark.parametrize("lumen, alerts", [("off", None), ("on", "off"), ("preview", None)])
def test_off_by_either_switch_the_page_is_the_old_one_and_reads_nothing_for_it(page, monkeypatch, lumen, alerts):
    monkeypatch.setenv("MEMBER_LUMEN", lumen)
    if alerts:
        monkeypatch.setenv("MEMBER_ALERTS_LIST", alerts)
    html = _get().body.decode()
    assert "Your <em>alerts</em>" not in html and "Recent" not in html and 'name="k_live"' in html
    assert page["lists"] == [] and page["marked"] == []


def test_under_preview_the_owners_preview_sees_it_and_marks_nothing(page, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "preview")
    page["preview"] = True
    html = _get().body.decode()
    assert "Your <em>alerts</em>" in html and "Tomorrow: Fall Picnic" in html
    assert page["marked"] == []                                       # a preview never writes


def test_under_preview_the_platform_owners_own_sign_in_sees_it(page, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "preview")
    page["email"] = PLATFORM
    page["me"] = dict(MEMBER, email=PLATFORM)
    assert "Your <em>alerts</em>" in _get().body.decode()
    assert page["marked"] == [ME]


def test_a_failed_list_shows_the_page_without_it_and_marks_nothing(page, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    page["rows"] = lambda *a, **k: None
    resp = _get()
    html = resp.body.decode()
    assert resp.status_code == 200
    assert "Your <em>alerts</em>" in html and "Recent" not in html and 'name="k_live"' in html
    assert page["marked"] == []


def test_an_empty_list_says_nothing_yet(page, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    page["rows"] = lambda *a, **k: []
    assert "Nothing yet" in _get().body.decode()


def test_no_other_page_reads_for_the_list_or_the_dot(page, monkeypatch):
    monkeypatch.setenv("MEMBER_LUMEN", "on")

    def never(*a, **k):
        raise AssertionError("read for alerts on another page")
    monkeypatch.setattr(ma, "alerts_unseen", never)
    monkeypatch.setattr(ma, "seen_at", never)
    for path in ("/my/prayer", "/my/events", "/my/me"):
        assert _get(path).status_code == 200
    assert page["lists"] == []
