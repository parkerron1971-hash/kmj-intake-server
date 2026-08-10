# test_push_notifications.py
# Chief-in-your-pocket — endpoint-execution tests (rule R3: request-path
# code ships with tests that EXECUTE the endpoint functions).

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import push_notifications as push
from auth_supabase import AuthedUser


def _user():
    return AuthedUser(id="11111111-1111-1111-1111-111111111111",
                      email="kevin@example.com", role="authenticated")


class FakeSBModule:
    """Minimal stand-in for sb_clients used by the push module."""
    def __init__(self):
        self.posts = []
        self.deletes = []
        self.get_rows = []

    def sb_post_as_service(self, path, body, prefer=None):
        self.posts.append((path, body, prefer))
        return [dict(body, id="sub-1")]

    def sb_delete_as_service(self, path):
        self.deletes.append(path)
        return True

    def sb_get_as_service(self, path):
        return list(self.get_rows)


@pytest.fixture()
def fake_sb(monkeypatch):
    fake = FakeSBModule()
    monkeypatch.setattr(push, "sb_clients", fake)

    # subscribe() now calls business_access.assert_access, which imports
    # sb_clients itself — patching push.sb_clients alone leaves the guard
    # reaching for a real service key. Make the caller the OWNER of b-1
    # so these tests exercise the guard rather than stub it away.
    import sb_clients as real_sb

    def _get(path):
        if path.startswith("/businesses?"):
            return [{"id": "b-1", "owner_id": _user().id}]
        if path.startswith("/business_users?"):
            return []          # owner has no seat row — the #464 shape
        return []

    monkeypatch.setattr(real_sb, "sb_get_as_service", _get)
    return fake


@pytest.fixture()
def sb_stranger(monkeypatch):
    """Same, but the business belongs to somebody else."""
    fake = FakeSBModule()
    monkeypatch.setattr(push, "sb_clients", fake)
    import sb_clients as real_sb

    def _get(path):
        if path.startswith("/businesses?"):
            return [{"id": "b-1", "owner_id": "99999999-9999-9999-9999-999999999999"}]
        return []

    monkeypatch.setattr(real_sb, "sb_get_as_service", _get)
    return fake


def _enable(monkeypatch):
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "pub")


def test_vapid_public_disabled_by_default(monkeypatch):
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", "")
    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "")
    out = push.vapid_public()
    assert out["enabled"] is False
    assert out["key"] is None


def test_vapid_public_enabled(monkeypatch):
    _enable(monkeypatch)
    out = push.vapid_public()
    assert out == {"enabled": True, "key": "pub"}


def test_subscribe_upserts_on_endpoint(monkeypatch, fake_sb):
    _enable(monkeypatch)
    body = push.SubscribeBody(
        business_id="b-1",
        subscription={"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}},
        user_agent="TestPhone",
    )
    out = push.subscribe(body, user=_user())
    assert out["ok"] is True
    path, row, prefer = fake_sb.posts[0]
    assert "on_conflict=endpoint" in path
    assert prefer == "resolution=merge-duplicates"
    assert row["endpoint"] == "https://push.example/abc"
    assert row["user_id"] == "11111111-1111-1111-1111-111111111111"
    assert row["business_id"] == "b-1"


def test_subscribe_rejects_missing_endpoint(monkeypatch, fake_sb):
    _enable(monkeypatch)
    from fastapi import HTTPException
    body = push.SubscribeBody(business_id="b-1", subscription={})
    with pytest.raises(HTTPException):
        push.subscribe(body, user=_user())


def test_subscribe_noops_when_disabled(monkeypatch, fake_sb):
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", "")
    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "")
    body = push.SubscribeBody(business_id="b-1", subscription={"endpoint": "e"})
    out = push.subscribe(body, user=_user())
    assert out == {"ok": False, "enabled": False}
    assert fake_sb.posts == []


def test_unsubscribe_scopes_to_caller(monkeypatch, fake_sb):
    out = push.unsubscribe(push.UnsubscribeBody(endpoint="https://push.example/abc"), user=_user())
    assert out["ok"] is True
    assert len(fake_sb.deletes) == 1
    assert "user_id=eq.11111111-1111-1111-1111-111111111111" in fake_sb.deletes[0]


def test_send_to_user_prunes_dead_subscription(monkeypatch, fake_sb):
    _enable(monkeypatch)
    fake_sb.get_rows = [{"endpoint": "https://push.example/dead",
                         "subscription": {"endpoint": "https://push.example/dead"}}]

    class FakeResp:
        status_code = 410

    class FakeWebPushException(Exception):
        def __init__(self):
            super().__init__("gone")
            self.response = FakeResp()

    import types
    fake_mod = types.ModuleType("pywebpush")

    def fake_webpush(**kwargs):
        raise FakeWebPushException()

    fake_mod.webpush = fake_webpush
    fake_mod.WebPushException = FakeWebPushException
    monkeypatch.setitem(sys.modules, "pywebpush", fake_mod)

    sent = push.send_to_user("u-1", title="t", body="b")
    assert sent == 0
    assert len(fake_sb.deletes) == 1  # dead endpoint pruned


def test_send_to_business_delivers(monkeypatch, fake_sb):
    _enable(monkeypatch)
    fake_sb.get_rows = [{"endpoint": "e1", "subscription": {"endpoint": "e1"}},
                        {"endpoint": "e2", "subscription": {"endpoint": "e2"}}]

    import types
    calls = []
    fake_mod = types.ModuleType("pywebpush")

    def fake_webpush(**kwargs):
        calls.append(kwargs)

    class FakeWebPushException(Exception):
        pass

    fake_mod.webpush = fake_webpush
    fake_mod.WebPushException = FakeWebPushException
    monkeypatch.setitem(sys.modules, "pywebpush", fake_mod)

    sent = push.send_to_business("b-1", title="Chief", body="hello", nav="operate:queue")
    assert sent == 2
    import json as _json
    payload = _json.loads(calls[0]["data"])
    assert payload["nav"] == "operate:queue"
    assert payload["title"] == "Chief"


def test_subscribe_refuses_a_business_the_caller_does_not_own(monkeypatch, sb_stranger):
    """send_to_business() fans out to every push_subscriptions row with
    that business_id. Unchecked, a signed-in stranger could subscribe to
    another practitioner's business and start receiving their morning
    brief, overdue invoices and session alerts."""
    from fastapi import HTTPException
    _enable(monkeypatch)
    body = push.SubscribeBody(
        business_id="b-1",
        subscription={"endpoint": "https://push.example/evil", "keys": {"p256dh": "x", "auth": "y"}},
    )
    with pytest.raises(HTTPException) as e:
        push.subscribe(body, user=_user())
    assert e.value.status_code == 404          # indistinguishable from "no such business"
    assert not sb_stranger.posts, "a refused subscribe still wrote a row"
