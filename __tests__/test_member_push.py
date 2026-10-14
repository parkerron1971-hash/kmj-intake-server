"""Notifications on members' phones (Subsplash exit plan, decision 1:
Kevin, 2026-10-14, yes). The rule: members can turn each kind off, and
nothing goes out without the church's switch."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import member_push as mp
import push_notifications as pn

BIZ = "biz-push-1"


def church(**on):
    return {"id": BIZ, "name": "Love City Church",
            "settings": {"member_portal": {"enabled": True, "notifications": on}}}


class FakeSB:
    def __init__(self, subs=(), prefs=(), sends=(), claim=True):
        self.subs, self.prefs, self.sends, self.claim = list(subs), list(prefs), list(sends), claim
        self.posts, self.patches, self.deletes = [], [], []

    def sb_get_as_service(self, path):
        if path.startswith("/member_push_subscriptions"):
            return self.subs
        if path.startswith("/member_push_prefs"):
            return self.prefs
        if path.startswith("/member_push_sends"):
            return self.sends
        if path.startswith("/businesses"):
            return [church(announcements=True)]
        return []

    def sb_post_as_service(self, path, body, prefer=None):
        self.posts.append((path, body, prefer))
        if path.startswith("/member_push_sends"):
            return [{"id": "log-1", **body}] if self.claim else []
        return [body]

    def sb_patch_as_service(self, path, body):
        self.patches.append((path, body))
        return [body]

    def sb_delete_as_service(self, path):
        self.deletes.append(path)
        return True


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setattr(pn, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(pn, "VAPID_PUBLIC_KEY", "pub-key")
    sent = []
    monkeypatch.setattr(pn, "_send_one", lambda row, payload, table="push_subscriptions":
                        sent.append((row["contact_id"], payload, table)) or True)

    def use(fake):
        monkeypatch.setattr(mp, "sb_clients", fake)
        return fake
    return sent, use


def sub(cid, n=1):
    return {"id": f"s-{cid}-{n}", "contact_id": cid, "endpoint": f"https://push.example/{cid}/{n}",
            "subscription": {"endpoint": f"https://push.example/{cid}/{n}"}}


# ─── the church's switch and the member's choice ─────────────────────

def test_every_kind_is_off_until_the_church_turns_it_on():
    assert mp.church_kinds({}) == set()
    assert mp.church_kinds({"member_portal": {"notifications": {"live": True, "messages": False,
                                                                "bogus": True}}}) == {"live"}
    assert mp.clean_switches({"live": True, "announcements": False}) == {"live": True, "announcements": False}
    for bad in ({"bogus": True}, {"live": "yes"}, ["live"]):
        with pytest.raises(HTTPException):
            mp.clean_switches(bad)


def test_nothing_sends_without_push_keys_or_the_churchs_switch(wired, monkeypatch):
    sent, use = wired
    use(FakeSB(subs=[sub("a")]))
    assert mp.send(church(), "live", title="Live") == 0          # church switch off
    assert mp.send(church(live=True), "nope", title="x") == 0     # unknown kind
    monkeypatch.setattr(pn, "VAPID_PRIVATE_KEY", "")
    assert mp.send(church(live=True), "live", title="Live") == 0  # server not set up
    assert sent == []


def test_a_member_who_turned_a_kind_off_does_not_get_it(wired):
    sent, use = wired
    use(FakeSB(subs=[sub("a"), sub("a", 2), sub("b"), sub("c")],
               prefs=[{"contact_id": "b", "off": ["live"]}, {"contact_id": "c", "off": ["messages"]}]))
    n = mp.send(church(live=True), "live", title="Love City is live", body="Sunday", url="/my/live")
    assert n == 3                                  # both of a's phones, and c
    assert sorted(c for c, _, _ in sent) == ["a", "a", "c"]
    assert all(t == "member_push_subscriptions" for _, _, t in sent)   # prunes members' table
    assert sent[0][1] == {"title": "Love City is live", "body": "Sunday", "url": "/my/live", "tag": "live-"}


def test_a_ref_is_sent_once(wired):
    sent, use = wired
    fake = use(FakeSB(subs=[sub("a")]))
    assert mp.send(church(live=True), "live", title="Live", ref_id="sess-1") == 1
    assert fake.patches == [("/member_push_sends?id=eq.log-1", {"recipients": 1})]
    use(FakeSB(subs=[sub("a")], claim=False))       # the row already exists
    assert mp.send(church(live=True), "live", title="Live", ref_id="sess-1") == 0
    assert len(sent) == 1


def test_only_named_people_and_only_member_pages(wired):
    sent, use = wired
    use(FakeSB(subs=[sub("a"), sub("b")]))
    mp.send(church(messages=True), "messages", title="New message", url="https://evil.example",
            contact_ids=["b"])
    assert [c for c, _, _ in sent] == ["b"]
    assert sent[0][1]["url"] == "/my"
    for good in ("/my", "/my/live", "/my/messages/123?x=1"):
        assert mp._safe_url(good) == good
    for bad in ("/myx", "//evil.example", "javascript:alert(1)", "/admin"):
        assert mp._safe_url(bad) == "/my"


def test_a_send_failure_never_raises(wired, monkeypatch):
    sent, use = wired
    use(FakeSB(subs=[sub("a")]))
    monkeypatch.setattr(mp, "_send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert mp.send(church(live=True), "live", title="x") == 0


# ─── devices ─────────────────────────────────────────────────────────

def test_only_a_real_push_subscription_is_kept():
    good = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
            "keys": {"p256dh": "B" * 87, "auth": "a" * 22}, "expirationTime": None}
    assert mp.valid_subscription(good) == {"endpoint": good["endpoint"], "keys": good["keys"]}
    for bad in (None, {}, {**good, "endpoint": "http://insecure.example/x"},
                {**good, "keys": {"p256dh": "x"}}, {**good, "endpoint": "https://a b"}):
        assert mp.valid_subscription(bad) is None


# ─── what the member sees ────────────────────────────────────────────

def test_the_page_offers_only_what_the_church_turned_on(wired):
    import member_portal
    req = SimpleNamespace(query_params={})
    html = mp.render_page(church(live=True, announcements=True), None, req, {"id": "a", "name": "A"},
                          {"live"})
    assert 'name="k_live"' in html and 'name="k_announcements"' in html
    assert 'name="k_messages"' not in html
    assert 'name="k_live" ' in html and 'name="k_live" checked' not in html   # turned off by them
    assert "pub-key" in html and "requestPermission" in html
    off_page = mp.render_page(church(), None, req, {"id": "a", "name": "A"}, set())
    assert "hasn&#x27;t turned on notifications" in off_page


def test_home_card_only_when_the_church_offers_something(wired):
    assert mp.home_card(church()) == ""
    assert "Turn on notifications" in mp.home_card(church(live=True))


# ─── the staff announcement ──────────────────────────────────────────

def _staff(monkeypatch, allowed=True):
    import business_access
    def gate(biz, user, role):
        assert role == "manager"
        if not allowed:
            raise HTTPException(404, "not found")
    monkeypatch.setattr(business_access, "assert_access", gate)


def test_announce_needs_staff_a_title_and_the_switch(wired, monkeypatch):
    sent, use = wired
    fake = use(FakeSB(subs=[sub("a"), sub("b")]))
    _staff(monkeypatch, allowed=False)
    with pytest.raises(HTTPException):
        mp.announce(BIZ, {"title": "Hi"}, SimpleNamespace(id="u1"))
    _staff(monkeypatch)
    with pytest.raises(HTTPException) as e:
        mp.announce(BIZ, {"title": "  "}, SimpleNamespace(id="u1"))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        mp.announce(BIZ, {"title": "x" * 61}, SimpleNamespace(id="u1"))
    assert e.value.status_code == 400
    out = mp.announce(BIZ, {"title": "Service moved to 10am", "body": "See you Sunday"},
                      SimpleNamespace(id="u1"))
    assert out == {"ok": True, "reached": 2}
    log = [b for p, b, _ in fake.posts if p.startswith("/member_push_sends")][0]
    assert log["kind"] == "announcements" and log["sent_by"] == "u1"


def test_announcements_stop_at_three_a_day(wired, monkeypatch):
    sent, use = wired
    use(FakeSB(subs=[sub("a")], sends=[{"id": 1}, {"id": 2}, {"id": 3}]))
    _staff(monkeypatch)
    with pytest.raises(HTTPException) as e:
        mp.announce(BIZ, {"title": "One more"}, SimpleNamespace(id="u1"))
    assert e.value.status_code == 429 and sent == []


# ─── the church's switch lives in the member page settings ───────────

def test_owner_switches_kinds_on_and_the_rest_of_the_settings_survive(monkeypatch):
    import member_portal
    stored = {"member_portal": {"enabled": True, "epoch": 5, "notifications": {"live": True}},
              "giving": {"enabled": True}}
    writes = []

    class SB:
        def sb_get_as_service(self, path):
            return [{"settings": stored}]

        def sb_patch_as_service(self, path, body):
            writes.append(body)
            return [body]

    monkeypatch.setattr(member_portal, "sb_clients", SB())
    monkeypatch.setattr(member_portal, "_require_owner",
                        lambda b, u: {"id": BIZ, "type": "church", "settings": stored})
    import business_sites_helpers
    monkeypatch.setattr(business_sites_helpers, "ensure_business_site", lambda biz: ({"slug": "lc"}, False))
    out = member_portal.patch_member_portal_config(
        BIZ, {"notifications": {"announcements": True}}, SimpleNamespace(id="owner"))
    saved = writes[0]["settings"]
    assert saved["member_portal"]["notifications"] == {"live": True, "announcements": True}
    assert saved["member_portal"]["epoch"] == 5 and saved["giving"] == {"enabled": True}
    kinds = {k["key"]: k["on"] for k in out["notifications"]["kinds"]}
    assert kinds["announcements"] and kinds["live"] and not kinds["messages"]
    with pytest.raises(HTTPException):
        member_portal.patch_member_portal_config(BIZ, {"notifications": {"spam": True}},
                                                 SimpleNamespace(id="owner"))


# ─── going live tells members ────────────────────────────────────────

def test_going_live_sends_one_live_note(monkeypatch):
    import live_router
    import threading
    calls = []

    class SB:
        def sb_get_as_service(self, path):
            return [church(live=True)]

    monkeypatch.setattr(live_router, "sb_clients", SB())
    monkeypatch.setattr(mp, "send", lambda biz, kind, **kw: calls.append((kind, kw)) or 1)

    class Now:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(threading, "Thread", Now)
    live_router._tell_members_live(BIZ, {"id": "sess-9", "title": "Sunday service"})
    assert calls == [("live", {"title": "Love City Church is live", "body": "Sunday service",
                               "url": "/my/live", "ref_id": "sess-9"})]


# ─── automatic notes (messages, prayer, sermons, events) ─────────────

class _Now:
    """threading.Thread stand-in that runs the target at once."""
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


def test_chat_recipients_skip_sender_declined_muted_and_messaging_off():
    direct = {"id": "t1", "kind": "direct"}
    acc = {"other": {"id": "b"}, "people": {}}
    assert mp.chat_recipients(direct, acc, "a", [{"contact_id": "b", "state": "active"}]) == ["b"]
    assert mp.chat_recipients(direct, acc, "a", [{"contact_id": "b", "state": "declined"}]) == []
    assert mp.chat_recipients(direct, acc, "a", [{"contact_id": "b", "muted": True}]) == []
    group = {"id": "t2", "kind": "group", "group_id": "g1"}
    acc = {"people": {"a": {"enabled": True}, "b": {"enabled": True}, "c": {"enabled": False},
                      "d": {"enabled": True}}}
    assert sorted(mp.chat_recipients(group, acc, "a", [{"contact_id": "d", "muted": True}])) == ["b"]


def test_a_new_message_says_only_that_one_arrived(wired, monkeypatch):
    import threading
    import member_portal_messaging as mpm
    sent, use = wired
    fake = use(FakeSB(subs=[sub("b"), sub("c")]))
    orig = fake.sb_get_as_service
    fake.sb_get_as_service = lambda path: [{"name": "Youth"}] if path.startswith("/groups") else orig(path)
    monkeypatch.setattr(threading, "Thread", _Now)
    monkeypatch.setattr(mpm, "participants", lambda biz, tid: [])
    t = {"id": "t9", "kind": "group", "group_id": "g1"}
    acc = {"people": {"a": {"enabled": True}, "b": {"enabled": True}, "c": {"enabled": True}}}
    mp.tell_chat(church(messages=True), t, acc, "a")
    assert sorted(c for c, _, _ in sent) == ["b", "c"]
    assert sent[0][1] == {"title": "New message in Youth", "body": "Open the app to read it.",
                          "url": "/my/messages/t9", "tag": "chat-t9"}
    sent.clear()
    mp.tell_chat(church(), t, acc, "a")          # messages not switched on by the church
    assert sent == []


def test_the_member_who_asked_hears_the_church_prayed(wired, monkeypatch):
    import threading
    sent, use = wired
    fake = use(FakeSB(subs=[sub("asker"), sub("other")]))
    orig = fake.sb_get_as_service
    fake.sb_get_as_service = lambda path: [church(prayer=True)] if path.startswith("/businesses") else orig(path)
    monkeypatch.setattr(threading, "Thread", _Now)
    mp.tell_prayed(BIZ, "asker", "req-1")
    assert [c for c, _, _ in sent] == ["asker"]
    assert sent[0][1]["title"] == "Someone prayed for you" and sent[0][1]["url"] == "/my/prayer"
    assert "req-1" not in str(sent[0][1])        # nothing of the request itself
    sent.clear()
    mp.tell_prayed(BIZ, None, "req-2")
    assert sent == []


def test_marking_prayed_tells_the_asker_once(monkeypatch):
    import private_care as pc
    calls = []
    monkeypatch.setattr(mp, "tell_prayed", lambda *a: calls.append(a))
    state = {"prayed_at": None}
    rid = "11111111-1111-1111-1111-111111111111"
    biz = "22222222-2222-2222-2222-222222222222"

    class SB:
        def sb_get_as_service(self, path):
            return [{"id": rid, "status": "new", "prayed_at": state["prayed_at"],
                     "contact_id": "asker", "assigned_to": None}]

        def sb_patch_as_service(self, path, body):
            if "prayed_at" in body:
                state["prayed_at"] = body["prayed_at"]
            return [{"id": rid, **body}]

    monkeypatch.setattr(pc, "sb_clients", SB())
    pc.update_request(biz, rid, prayed=True)
    assert calls == [(biz, "asker", rid)]
    pc.update_request(biz, rid, prayed=True)     # already prayed: no second note
    pc.update_request(biz, rid, status="reviewed")
    assert len(calls) == 1


def test_the_newest_recent_sermon_is_announced_once(wired, monkeypatch):
    from datetime import datetime, timezone
    calls = []
    monkeypatch.setattr(mp, "send", lambda biz, kind, **kw: calls.append((kind, kw)) or 2)
    now = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)

    class SB:
        rows = []

        def sb_get_as_service(self, path):
            assert "order=created_at.desc&limit=1" in path and "published=is.true" in path
            return self.rows

    fake = SB()
    monkeypatch.setattr(mp, "sb_clients", fake)
    fake.rows = [{"id": "s1", "title": "To the Future", "speaker": "Pastor Kevin", "preached_on": "2026-10-11"}]
    assert mp._sweep_sermons(church(sermons=True), now=now) == 2
    assert calls == [("sermons", {"title": "New: To the Future", "body": "Pastor Kevin",
                                  "url": "/my/sermons/s1", "ref_id": "sermon:s1"})]
    fake.rows = [{"id": "s0", "title": "Old", "preached_on": "2025-01-05"}]   # an old one added late
    assert mp._sweep_sermons(church(sermons=True), now=now) == 0
    fake.rows = []
    assert mp._sweep_sermons(church(sermons=True), now=now) == 0


def test_event_reminders_go_the_afternoon_before_to_yes_answers(wired, monkeypatch):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    import business_marketing
    import events_rsvp_router as er
    import member_portal_church as mpc
    calls = []
    monkeypatch.setattr(mp, "send", lambda biz, kind, **kw: calls.append((kind, kw)) or 1)
    monkeypatch.setattr(business_marketing, "business_tz", lambda biz: ZoneInfo("America/Detroit"))
    monkeypatch.setattr(mpc, "_roster_modules", lambda biz: [{"id": "m1", "archetype_params": {}}])

    class SB:
        def sb_get_as_service(self, path):
            return [{"id": "e1", "module_id": "m1", "data": {}}]

    monkeypatch.setattr(mp, "sb_clients", SB())
    monkeypatch.setattr(er, "resolve_fields", lambda params: {"signups_field": "signups"})
    monkeypatch.setattr(er, "build_occasions", lambda mods, by, today=None, include=None: [
        {"entry_id": "e1", "module_id": "m1", "title": "Fall Picnic", "date": "2026-10-15"},
        {"entry_id": "e1", "module_id": "m1", "title": "Later", "date": "2026-10-20"}])
    monkeypatch.setattr(er, "read_signups", lambda data, field: [
        {"contact_id": "a", "status": "yes"}, {"contact_id": "b", "status": "no"},
        {"contact_id": "c"}, {"name": "No record", "status": "yes"}])
    # 2026-10-14 17:30 in Detroit = 21:30 UTC: inside the afternoon window.
    afternoon = datetime(2026, 10, 14, 21, 30, tzinfo=timezone.utc)
    assert mp._sweep_events(church(events=True), now=afternoon) == 1
    kind, kw = calls[0]
    assert kind == "events" and kw["contact_ids"] == ["a", "c"]
    assert kw["title"] == "Tomorrow: Fall Picnic" and kw["ref_id"] == "event:e1:2026-10-15"
    calls.clear()
    # 09:00 in Detroit: not the afternoon, nothing goes.
    morning = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)
    assert mp._sweep_events(church(events=True), now=morning) == 0
    assert calls == []


def test_the_sweep_only_reads_churches_with_a_clock_kind_on(wired, monkeypatch):
    seen = []

    class SB:
        def sb_get_as_service(self, path):
            seen.append(path)
            return [church(sermons=True),
                    {"id": "bad", "settings": {"member_portal": {"notifications": {"events": True}}}}]

    def broken(biz):
        raise RuntimeError("one church broke")

    monkeypatch.setattr(mp, "sb_clients", SB())
    monkeypatch.setattr(mp, "_sweep_sermons", lambda biz: 1)
    monkeypatch.setattr(mp, "_sweep_events", broken)
    assert mp.sweep_tick() == {"sermons": 1, "events": 0}
    assert "notifications->>sermons.eq.true" in seen[0] and "notifications->>events.eq.true" in seen[0]


def test_the_hooks_are_wired_where_things_happen():
    import inspect
    import member_portal_messaging as mpm
    src = inspect.getsource(mpm.send)
    assert 'if status_ == "delivered":' in src and "member_push.tell_chat(" in src
    auto = open("kmj_intake_automation.py", encoding="utf-8").read()
    assert 'g("member_push_sweep", _member_push.sweep_tick)' in auto
