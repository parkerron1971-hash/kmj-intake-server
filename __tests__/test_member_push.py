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
