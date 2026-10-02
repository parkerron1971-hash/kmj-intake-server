"""S6 per-business email identity — the resolution seam + domain router.

Covers:
  1. resolve_from_address: verified custom vs fallback vs partial config.
  2. send_via_resend: identity applied in-funnel (explicit business_id
     AND routed-reply-to inference), explicit non-platform froms never
     overridden, and the suppression gate still consulted for
     custom-domain sends.
  3. email_domains_router: owner-only auth, connect/verify happy path
     with a mocked Resend client, half-write prevention on API failure,
     disconnect.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import email_sender  # noqa: E402
import email_domains_router as edr  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


VERIFIED_CFG = {
    "domain": "studiok.com",
    "from_local_part": "hello",
    "from_name": "Sarah from Studio K",
    "resend_domain_id": "dom_1",
    "status": "verified",
    "records": [],
}


def _biz(cfg=None, name="Studio K"):
    settings = {"email_domain": cfg} if cfg is not None else {}
    return {"id": "b1" + "0" * 30, "name": name, "settings": settings}


def _u(uid):
    return type("U", (), {"id": uid})()


# ─── 1. resolve_from_address ─────────────────────────────────────────


def test_resolve_verified_custom_wins():
    email, name = email_sender.resolve_from_address(
        _biz(VERIFIED_CFG), default_email="noreply@mysolutionist.app",
        default_name="Platform")
    assert email == "hello@studiok.com"
    assert name == "Sarah from Studio K"


def test_resolve_verified_without_display_name_falls_to_caller_then_biz():
    cfg = {**VERIFIED_CFG, "from_name": ""}
    _, name = email_sender.resolve_from_address(
        _biz(cfg), default_email="x@mysolutionist.app", default_name="Caller Name")
    assert name == "Caller Name"
    _, name = email_sender.resolve_from_address(
        _biz(cfg), default_email="x@mysolutionist.app")
    assert name == "Studio K"


def test_resolve_pending_falls_back_to_platform():
    cfg = {**VERIFIED_CFG, "status": "pending"}
    email, _ = email_sender.resolve_from_address(
        _biz(cfg), default_email="receipts@mysolutionist.app")
    assert email == "receipts@mysolutionist.app"


@pytest.mark.parametrize("broken", [
    {**VERIFIED_CFG, "from_local_part": ""},          # no local part
    {**VERIFIED_CFG, "domain": ""},                   # no domain
    {**VERIFIED_CFG, "from_local_part": "a@b"},       # junk local part
    "not-a-dict",                                     # malformed blob
    None,                                             # nothing configured
])
def test_resolve_partial_config_falls_back(broken):
    biz = {"id": "b", "name": "X", "settings": {"email_domain": broken}}
    email, _ = email_sender.resolve_from_address(
        biz, default_email="noreply@mysolutionist.app")
    assert email == "noreply@mysolutionist.app"


def test_resolve_default_email_env_fallback(monkeypatch):
    monkeypatch.setenv("RESEND_FROM_EMAIL", "env@mysolutionist.app")
    email, _ = email_sender.resolve_from_address(_biz(None))
    assert email == "env@mysolutionist.app"


# ─── 2. send_via_resend in-funnel identity ───────────────────────────


class _FakeResp:
    status_code = 200
    text = '{"id": "email_1"}'

    def json(self):
        return {"id": "email_1"}


class _FakeAsyncClient:
    sent = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None, **k):
        _FakeAsyncClient.sent.append({"url": url, "json": json})
        return _FakeResp()


@pytest.fixture
def wired_send(monkeypatch):
    """send_via_resend with Resend + suppression + identity lookup faked."""
    _FakeAsyncClient.sent = []
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setattr(email_sender.httpx, "AsyncClient", _FakeAsyncClient)

    async def _not_suppressed(email):
        return None
    monkeypatch.setattr(email_sender, "is_suppressed", _not_suppressed)

    email_sender._IDENTITY_CACHE.clear()
    calls = {}

    async def _row(business_id=None, biz_prefix=None):
        calls["business_id"] = business_id
        calls["biz_prefix"] = biz_prefix
        return _biz(VERIFIED_CFG)
    monkeypatch.setattr(email_sender, "_business_identity_row", _row)
    return calls


def _last_payload():
    assert _FakeAsyncClient.sent, "nothing was sent"
    return _FakeAsyncClient.sent[-1]["json"]


def test_send_with_business_id_uses_custom_identity(wired_send):
    asyncio.run(email_sender.send_via_resend(
        to_email="donor@example.com", to_name="Donor",
        from_email="noreply@mysolutionist.app", from_name="Studio K",
        subject="s", body="b", reply_to="reply+b100+c100@in.mysolutionist.app",
        business_id="b1"))
    payload = _last_payload()
    assert payload["from"] == "Sarah from Studio K <hello@studiok.com>"
    # Reply routing continuity: the routed platform reply-to is untouched.
    assert payload["reply_to"] == "reply+b100+c100@in.mysolutionist.app"
    # Unsubscribe machinery unchanged.
    assert "List-Unsubscribe" in payload["headers"]


def test_send_routed_reply_to_infers_business(monkeypatch, wired_send):
    monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "in.mysolutionist.app")
    asyncio.run(email_sender.send_via_resend(
        to_email="c@example.com", to_name=None,
        from_email="noreply@mysolutionist.app", from_name="Studio K",
        subject="s", body="b",
        reply_to="reply+abcd1234+efgh5678@in.mysolutionist.app"))
    assert wired_send["biz_prefix"] == "abcd1234"
    assert _last_payload()["from"] == "Sarah from Studio K <hello@studiok.com>"


def test_send_explicit_custom_from_never_overridden(wired_send):
    asyncio.run(email_sender.send_via_resend(
        to_email="c@example.com", to_name=None,
        from_email="invites@solutionist.studio", from_name="Solutionist System",
        subject="s", body="b", reply_to=None, business_id="b1"))
    assert _last_payload()["from"] == "Solutionist System <invites@solutionist.studio>"


def test_send_platform_default_without_business_stays_platform(wired_send):
    asyncio.run(email_sender.send_via_resend(
        to_email="c@example.com", to_name=None,
        from_email="noreply@mysolutionist.app", from_name="The Solutionist System",
        subject="s", body="b", reply_to=None))
    assert _last_payload()["from"] == (
        "The Solutionist System <noreply@mysolutionist.app>")


def test_suppression_gate_still_blocks_custom_domain_sends(monkeypatch, wired_send):
    async def _suppressed(email):
        return {"email": email, "reason": "complained"}
    monkeypatch.setattr(email_sender, "is_suppressed", _suppressed)
    with pytest.raises(RuntimeError):
        asyncio.run(email_sender.send_via_resend(
            to_email="spam@example.com", to_name=None,
            from_email="noreply@mysolutionist.app", from_name="Studio K",
            subject="s", body="b", reply_to=None, business_id="b1"))
    assert _FakeAsyncClient.sent == []  # nothing reached Resend


def test_identity_lookup_failure_fails_open(monkeypatch, wired_send):
    async def _boom(business_id=None, biz_prefix=None):
        raise RuntimeError("db down")
    monkeypatch.setattr(email_sender, "_business_identity_row", _boom)
    asyncio.run(email_sender.send_via_resend(
        to_email="c@example.com", to_name=None,
        from_email="noreply@mysolutionist.app", from_name="Studio K",
        subject="s", body="b", reply_to=None, business_id="b1"))
    assert _last_payload()["from"] == "Studio K <noreply@mysolutionist.app>"


# ─── 3. email_domains_router ─────────────────────────────────────────


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append(
        {"id": "b1", "owner_id": "owner1", "name": "Studio K", "settings": {}})
    return fb


def _fake_resend(monkeypatch, responses):
    """responses: {(method, path_prefix): dict | Exception}. Records calls."""
    calls = []

    async def _resend(method, path, json_body=None):
        calls.append((method, path, json_body))
        for (m, p), out in responses.items():
            if m == method and path.startswith(p):
                if isinstance(out, Exception):
                    raise out
                return out
        return {}
    monkeypatch.setattr(edr, "_resend", _resend)
    return calls


CREATED = {"id": "dom_1", "status": "not_started",
           "records": [{"record": "SPF", "type": "TXT", "name": "send",
                        "value": "v=spf1 include:amazonses.com ~all",
                        "ttl": "Auto", "status": "not_started"},
                       {"record": "DKIM", "type": "TXT",
                        "name": "resend._domainkey", "value": "p=MIGf...",
                        "ttl": "Auto", "status": "not_started"}]}


def _biz_settings(fb):
    return fb.rows("businesses")[0].get("settings") or {}


def test_connect_owner_only(fake, monkeypatch):
    _fake_resend(monkeypatch, {("POST", ""): CREATED})
    body = edr.ConnectBody(domain="studiok.com", from_local_part="hello")
    # a manager seat is not enough
    fake.rows("business_users").append(
        {"business_id": "b1", "user_id": "mgr1", "role": "manager",
         "status": "active"})
    for uid in ("stranger", "mgr1"):
        with pytest.raises(HTTPException) as e:
            asyncio.run(edr.connect_domain("b1", body, _u(uid)))
        assert e.value.status_code == 403
    assert _biz_settings(fake) == {}  # nothing written


def test_connect_happy_path(fake, monkeypatch):
    calls = _fake_resend(monkeypatch, {("POST", ""): CREATED})
    body = edr.ConnectBody(domain="StudioK.com", from_local_part="Hello",
                           from_name="Sarah from Studio K")
    out = asyncio.run(edr.connect_domain("b1", body, _u("owner1")))
    assert calls[0] == ("POST", "", {"name": "studiok.com"})
    assert out["status"] == "pending"
    assert out["preview"]["rendered"] == "Sarah from Studio K <hello@studiok.com>"
    # Resend's two records plus OUR recommended DMARC row (optional).
    assert [r["record"] for r in out["records"]] == ["SPF", "DKIM", "DMARC"]
    assert out["records"][-1]["optional"] is True
    cfg = _biz_settings(fake)["email_domain"]
    assert len(cfg["records"]) == 2          # the stored blob stays Resend-only
    assert cfg["resend_domain_id"] == "dom_1"
    assert cfg["status"] == "pending"
    assert cfg["domain"] == "studiok.com"
    assert cfg["from_local_part"] == "hello"


def test_connect_rejects_bad_input(fake, monkeypatch):
    _fake_resend(monkeypatch, {("POST", ""): CREATED})
    for domain, local in [("not a domain", "hello"),
                          ("mysolutionist.app", "hello"),
                          ("studiok.com", "hi there")]:
        with pytest.raises(HTTPException) as e:
            asyncio.run(edr.connect_domain(
                "b1", edr.ConnectBody(domain=domain, from_local_part=local),
                _u("owner1")))
        assert e.value.status_code == 400
    assert _biz_settings(fake) == {}


def test_connect_missing_api_key_is_503_and_no_write(fake, monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        asyncio.run(edr.connect_domain(
            "b1", edr.ConnectBody(domain="studiok.com", from_local_part="hello"),
            _u("owner1")))
    assert e.value.status_code == 503
    assert _biz_settings(fake) == {}


def test_connect_resend_error_never_half_writes(fake, monkeypatch):
    _fake_resend(monkeypatch,
                 {("POST", ""): HTTPException(502, "Email provider error: nope")})
    with pytest.raises(HTTPException) as e:
        asyncio.run(edr.connect_domain(
            "b1", edr.ConnectBody(domain="studiok.com", from_local_part="hello"),
            _u("owner1")))
    assert e.value.status_code == 502
    assert _biz_settings(fake) == {}


def test_connect_settings_write_failure_rolls_back_resend(fake, monkeypatch):
    calls = _fake_resend(monkeypatch, {("POST", ""): CREATED,
                                       ("DELETE", "/dom_1"): {}})
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: None)
    with pytest.raises(HTTPException) as e:
        asyncio.run(edr.connect_domain(
            "b1", edr.ConnectBody(domain="studiok.com", from_local_part="hello"),
            _u("owner1")))
    assert e.value.status_code == 500
    assert ("DELETE", "/dom_1", None) in calls  # orphan cleaned up


def test_connect_twice_conflicts(fake, monkeypatch):
    _fake_resend(monkeypatch, {("POST", ""): CREATED})
    body = edr.ConnectBody(domain="studiok.com", from_local_part="hello")
    asyncio.run(edr.connect_domain("b1", body, _u("owner1")))
    with pytest.raises(HTTPException) as e:
        asyncio.run(edr.connect_domain("b1", body, _u("owner1")))
    assert e.value.status_code == 409


def test_verify_happy_path_marks_active(fake, monkeypatch):
    _fake_resend(monkeypatch, {("POST", ""): CREATED})
    asyncio.run(edr.connect_domain(
        "b1", edr.ConnectBody(domain="studiok.com", from_local_part="hello"),
        _u("owner1")))
    _fake_resend(monkeypatch, {
        ("POST", "/dom_1/verify"): {},
        ("GET", "/dom_1"): {**CREATED, "status": "verified"},
    })
    out = asyncio.run(edr.verify_domain("b1", _u("owner1")))
    assert out["status"] == "verified"
    cfg = _biz_settings(fake)["email_domain"]
    assert cfg["status"] == "verified"
    assert cfg["verified_at"]
    # ...and the seam now resolves the custom sender for this business.
    biz_row = fake.rows("businesses")[0]
    email, name = email_sender.resolve_from_address(
        biz_row, default_email="noreply@mysolutionist.app")
    assert email == "hello@studiok.com"


def test_verify_still_pending_is_honest(fake, monkeypatch):
    _fake_resend(monkeypatch, {("POST", ""): CREATED})
    asyncio.run(edr.connect_domain(
        "b1", edr.ConnectBody(domain="studiok.com", from_local_part="hello"),
        _u("owner1")))
    _fake_resend(monkeypatch, {
        ("POST", "/dom_1/verify"): {},
        ("GET", "/dom_1"): {**CREATED, "status": "pending"},
    })
    out = asyncio.run(edr.verify_domain("b1", _u("owner1")))
    assert out["status"] == "pending"
    assert _biz_settings(fake)["email_domain"]["status"] == "pending"


def test_status_and_disconnect(fake, monkeypatch):
    # not connected yet
    out = asyncio.run(edr.domain_status("b1", _u("owner1")))
    assert out == {"ok": True, "connected": False}
    _fake_resend(monkeypatch, {("POST", ""): CREATED,
                               ("GET", "/dom_1"): {**CREATED, "status": "pending"},
                               ("DELETE", "/dom_1"): {}})
    asyncio.run(edr.connect_domain(
        "b1", edr.ConnectBody(domain="studiok.com", from_local_part="hello"),
        _u("owner1")))
    out = asyncio.run(edr.domain_status("b1", _u("owner1")))
    assert out["connected"] is True and out["live_status"] == "pending"
    out = asyncio.run(edr.disconnect_domain("b1", _u("owner1")))
    assert out["connected"] is False
    assert _biz_settings(fake) == {}


def test_status_verify_disconnect_owner_only(fake, monkeypatch):
    _fake_resend(monkeypatch, {("POST", ""): CREATED})
    asyncio.run(edr.connect_domain(
        "b1", edr.ConnectBody(domain="studiok.com", from_local_part="hello"),
        _u("owner1")))
    for fn in (edr.domain_status, edr.verify_domain, edr.disconnect_domain):
        with pytest.raises(HTTPException) as e:
            asyncio.run(fn("b1", _u("stranger")))
        assert e.value.status_code == 403
