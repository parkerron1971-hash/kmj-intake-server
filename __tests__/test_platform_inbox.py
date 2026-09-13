# __tests__/test_platform_inbox.py
#
# The Mission Control inbox: mail addressed to the platform itself
# (kevin@/support@/... at INBOUND_EMAIL_DOMAIN) routes to platform_emails
# instead of dying as unknown_sender. These tests pin the address matcher
# and the /platform/inbox route surface.

from unittest import mock

from email_sender import _match_platform_address, _platform_local_parts


DOMAIN_ENV = {"INBOUND_EMAIL_DOMAIN": "mysolutionist.app"}


def test_named_address_matches_at_the_inbound_domain():
    with mock.patch.dict("os.environ", DOMAIN_ENV):
        assert _match_platform_address(["kevin@mysolutionist.app"]) == "kevin@mysolutionist.app"
        assert _match_platform_address(["support@mysolutionist.app"]) == "support@mysolutionist.app"


def test_wrong_domain_does_not_match_when_domain_configured():
    with mock.patch.dict("os.environ", DOMAIN_ENV):
        assert _match_platform_address(["kevin@othersite.com"]) is None


def test_reply_plus_addresses_never_match():
    with mock.patch.dict("os.environ", DOMAIN_ENV):
        assert _match_platform_address(["reply+abc12345+def67890@mysolutionist.app"]) is None


def test_unknown_local_part_does_not_match():
    with mock.patch.dict("os.environ", DOMAIN_ENV):
        assert _match_platform_address(["randomperson@mysolutionist.app"]) is None


def test_first_platform_recipient_wins_among_many():
    with mock.patch.dict("os.environ", DOMAIN_ENV):
        got = _match_platform_address(
            ["someone@gmail.com", "hello@mysolutionist.app", "kevin@mysolutionist.app"])
        assert got == "hello@mysolutionist.app"


def test_env_override_replaces_the_default_list():
    with mock.patch.dict(
        "os.environ", {**DOMAIN_ENV, "PLATFORM_INBOX_ADDRESSES": "ceo, press"}
    ):
        assert _platform_local_parts() == ["ceo", "press"]
        assert _match_platform_address(["ceo@mysolutionist.app"]) == "ceo@mysolutionist.app"
        # kevin is not in the overridden list
        assert _match_platform_address(["kevin@mysolutionist.app"]) is None


def test_unconfigured_domain_matches_on_local_part_alone():
    # A deploy that lost INBOUND_EMAIL_DOMAIN should still route rather
    # than drop.
    with mock.patch.dict("os.environ", {"INBOUND_EMAIL_DOMAIN": ""}):
        assert _match_platform_address(["support@anything.example"]) == "support@anything.example"


def test_reply_subject_prefixes_once():
    from platform_console import _reply_subject

    assert _reply_subject("Verify your account") == "Re: Verify your account"
    assert _reply_subject("Re: Verify your account") == "Re: Verify your account"
    assert _reply_subject("RE: shouting") == "RE: shouting"
    assert _reply_subject("") == "Re: (no subject)"


def test_platform_inbox_routes_exist_and_are_owner_gated():
    from platform_console import router

    by_path = {}
    for r in router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))

    assert "GET" in by_path.get("/platform/inbox", set())
    assert "GET" in by_path.get("/platform/inbox/{email_id}", set())
    assert "DELETE" in by_path.get("/platform/inbox/{email_id}", set())
    assert "POST" in by_path.get("/platform/inbox/{email_id}/reply", set())

    # Every inbox endpoint must carry the require_owner dependency —
    # this inbox is the platform owner's mail and nobody else's.
    from lead_admin import require_owner
    for r in router.routes:
        if not r.path.startswith("/platform/inbox"):
            continue
        deps = [d.call for d in r.dependant.dependencies]
        assert require_owner in deps, f"{r.path} is missing require_owner"


# ─── Compose (2026-09-13): starting a thread, not only answering one ──


def test_compose_routes_exist_and_sit_before_the_id_route():
    from platform_console import router

    by_path = {}
    order = []
    for r in router.routes:
        by_path.setdefault(r.path, set()).update(getattr(r, "methods", set()))
        order.append(r.path)

    assert "GET" in by_path.get("/platform/inbox/addresses", set())
    assert "POST" in by_path.get("/platform/inbox/compose", set())
    # FastAPI matches in registration order; "compose" must not be read
    # as an email id.
    assert order.index("/platform/inbox/compose") < order.index("/platform/inbox/{email_id}")
    assert order.index("/platform/inbox/addresses") < order.index("/platform/inbox/{email_id}")


def test_send_addresses_are_the_inbox_locals_at_the_inbound_domain():
    from platform_console import _platform_send_addresses

    with mock.patch.dict("os.environ", {**DOMAIN_ENV, "PLATFORM_INBOX_ADDRESSES": ""}):
        addrs = _platform_send_addresses()
        assert addrs[0] == "kevin@mysolutionist.app"
        assert "support@mysolutionist.app" in addrs
        # a reply to anything sent from here comes back to this inbox
        for a in addrs:
            assert _match_platform_address([a]) == a


def test_send_addresses_fall_back_to_the_default_sender_without_a_domain():
    from platform_console import _platform_send_addresses

    with mock.patch.dict("os.environ", {"INBOUND_EMAIL_DOMAIN": "",
                                        "RESEND_FROM_EMAIL": "Hello@Example.com"}):
        assert _platform_send_addresses() == ["hello@example.com"]


def test_email_shape():
    from platform_console import _looks_like_email

    assert _looks_like_email("someone@example.com")
    assert _looks_like_email("  first.last+tag@sub.example.co  ")
    assert not _looks_like_email("someone")
    assert not _looks_like_email("someone@")
    assert not _looks_like_email("Some One <someone@example.com>")
    assert not _looks_like_email("")


def test_direction_column_missing_matches_postgrest_wording():
    from platform_console import _direction_column_missing

    assert _direction_column_missing(
        '{"code":"42703","message":"column platform_emails.direction does not exist"}')
    assert _direction_column_missing(
        "{\"code\":\"PGRST204\",\"message\":\"Could not find the 'direction' column of 'platform_emails' in the schema cache\"}")
    assert not _direction_column_missing('{"message":"JWT expired"}')


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient; `responder(method, url, json)`
    returns the fake response."""
    responder = None
    calls = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None, **kw):
        type(self).calls.append(("POST", url, json))
        return type(self).responder("POST", url, json)


class _FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def _compose_client():
    """A test app with the owner gate replaced."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import platform_console
    from lead_admin import require_owner

    app = FastAPI()
    app.include_router(platform_console.router)
    app.dependency_overrides[require_owner] = lambda: {"email": "owner@example.com"}
    return TestClient(app)


def test_compose_rejects_bad_input_before_sending(monkeypatch):
    import email_sender

    sent = []

    async def fake_send(**kw):
        sent.append(kw)
        return {"id": "re_123"}

    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    c = _compose_client()
    with mock.patch.dict("os.environ", {**DOMAIN_ENV, "PLATFORM_INBOX_ADDRESSES": ""}):
        r = c.post("/platform/inbox/compose",
                   json={"to_email": "nope", "subject": "x", "body": "hi"})
        assert r.status_code == 400
        r = c.post("/platform/inbox/compose",
                   json={"to_email": "a@b.co", "subject": "x", "body": "   "})
        assert r.status_code == 400
        r = c.post("/platform/inbox/compose",
                   json={"to_email": "a@b.co", "subject": "x", "body": "hi",
                         "from_address": "ceo@somewhere-else.com"})
        assert r.status_code == 400
        assert "platform's addresses" in r.json()["detail"]
    assert sent == []


def test_compose_sends_from_a_platform_address_and_records_the_row(monkeypatch):
    import email_sender
    import platform_console

    sent = []

    async def fake_send(**kw):
        sent.append(kw)
        return {"id": "re_123"}

    def responder(method, url, body):
        assert url.endswith("/rest/v1/platform_emails")
        return _FakeResp(201, [{"id": "11111111-1111-1111-1111-111111111111",
                                "received_at": "2026-09-13T15:00:00+00:00", **body}])

    _FakeAsyncClient.responder = staticmethod(responder)
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    monkeypatch.setattr(platform_console.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(platform_console, "_service_headers", lambda: {"apikey": "test"})
    c = _compose_client()
    with mock.patch.dict("os.environ", {**DOMAIN_ENV, "PLATFORM_INBOX_ADDRESSES": ""}):
        r = c.post("/platform/inbox/compose", json={
            "to_email": " Someone@Example.com ",
            "to_name": "Someone",
            "from_address": "Support@MySolutionist.app",
            "subject": "  Hello from the platform ",
            "body": "Here is the thing.\n",
        })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True
    assert out["recorded"] is True
    assert out["migration_pending"] is None
    assert out["resend_id"] == "re_123"
    assert out["email"]["id"] == "11111111-1111-1111-1111-111111111111"

    assert len(sent) == 1
    assert sent[0]["from_email"] == "support@mysolutionist.app"
    assert sent[0]["from_name"] == "Support"
    assert sent[0]["reply_to"] == "support@mysolutionist.app"
    assert sent[0]["to_email"] == "Someone@Example.com"
    assert sent[0]["to_name"] == "Someone"
    assert sent[0]["subject"] == "Hello from the platform"

    assert len(_FakeAsyncClient.calls) == 1
    row = _FakeAsyncClient.calls[0][2]
    assert row["direction"] == "sent"
    assert row["to_address"] == "Someone@Example.com"
    assert row["from_email"] == "support@mysolutionist.app"
    assert row["read"] is True
    assert row["resend_id"] == "re_123"


def test_compose_still_sends_when_the_sent_column_is_not_there_yet(monkeypatch):
    import email_sender
    import platform_console

    async def fake_send(**kw):
        return {"id": "re_456"}

    def responder(method, url, body):
        return _FakeResp(
            400, {}, "{\"code\":\"PGRST204\",\"message\":\"Could not find the 'direction' column\"}")

    _FakeAsyncClient.responder = staticmethod(responder)
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    monkeypatch.setattr(platform_console.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(platform_console, "_service_headers", lambda: {"apikey": "test"})
    c = _compose_client()
    with mock.patch.dict("os.environ", {**DOMAIN_ENV, "PLATFORM_INBOX_ADDRESSES": ""}):
        r = c.post("/platform/inbox/compose", json={
            "to_email": "someone@example.com", "subject": "s", "body": "b"})
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is True
    assert out["recorded"] is False
    assert out["migration_pending"].endswith("platform-inbox-sent.sql")
    assert out["from_address"] == "kevin@mysolutionist.app"


def test_compose_reports_a_suppressed_recipient_as_502(monkeypatch):
    import email_sender

    async def fake_send(**kw):
        raise RuntimeError("Not sent: someone@example.com hard-bounced previously.")

    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    c = _compose_client()
    with mock.patch.dict("os.environ", {**DOMAIN_ENV, "PLATFORM_INBOX_ADDRESSES": ""}):
        r = c.post("/platform/inbox/compose", json={
            "to_email": "someone@example.com", "subject": "s", "body": "b"})
    assert r.status_code == 502
    assert "hard-bounced" in r.json()["detail"]
