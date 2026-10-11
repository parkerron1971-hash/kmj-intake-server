import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import square_connector as sq
import square_connect_router as routes
from access_log_redaction import redact, scrub_sentry_event, RedactCredentialPaths
from auth_supabase import AuthedUser, require_user

BIZ = "11111111-1111-4111-8111-111111111111"
USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TOKENS = {"access_token": "private-access", "refresh_token": "private-refresh", "merchant_id": "merchant1",
          "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()}


@pytest.fixture
def cfg():
    return sq.Config("sandbox", "sandbox-app", "private-secret", Fernet.generate_key().decode(),
                     "https://api.example.com/connect/square/callback", "https://app.example.com", frozenset([USER]))


@pytest.fixture
def client(monkeypatch, cfg):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(USER, None, "authenticated")
    monkeypatch.setattr(sq, "config", lambda: cfg)
    monkeypatch.setattr(routes, "owner", lambda business, user: None)
    with TestClient(app, base_url="https://api.example.com") as c:
        yield c


def test_config_fails_closed(monkeypatch):
    monkeypatch.setenv("SQUARE_ENABLED", "false")
    with pytest.raises(HTTPException) as exc:
        sq.config()
    assert exc.value.status_code == 503
    monkeypatch.setenv("SQUARE_ENABLED", "true")
    monkeypatch.delenv("SQUARE_TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(HTTPException):
        sq.config()


def test_encryption_and_wrong_key(cfg):
    encrypted = sq.seal(cfg, TOKENS)
    assert "private-access" not in encrypted and "private-refresh" not in encrypted
    assert sq.unseal(cfg, encrypted) == TOKENS
    other = sq.Config(cfg.environment, cfg.app_id, cfg.secret, Fernet.generate_key().decode(), cfg.callback, cfg.app_url, cfg.owners)
    with pytest.raises(HTTPException):
        sq.unseal(other, encrypted)
    assert "private-secret" not in repr(cfg)


def test_oauth_roundtrip_cookie_and_ciphertext(client, monkeypatch, cfg):
    saved = {}
    async def rpc(name, **kwargs):
        saved[name] = kwargs
        if name == "claim":
            return [{"business_id": BIZ, "user_id": USER, "attempt_id": BIZ}]
        return True
    async def square(*args, **kwargs):
        saved["exchange"] = kwargs
        return TOKENS
    monkeypatch.setattr(sq, "rpc", rpc)
    monkeypatch.setattr(sq, "square", square)
    start = client.post("/connect/square/start", params={"business_id": BIZ})
    assert start.status_code == 200
    ticket = parse_qs(urlsplit(start.json()["authorize_url"]).query)["ticket"][0]
    assert saved["start"]["p_ticket"] == sq.digest(ticket)
    begin = client.get(start.json()["authorize_url"], follow_redirects=False)
    assert begin.status_code == 303
    url = urlsplit(begin.headers["location"])
    assert url.netloc == "connect.squareupsandbox.com"
    query = parse_qs(url.query)
    assert set(query["scope"][0].split()) == {"APPOINTMENTS_READ", "APPOINTMENTS_ALL_READ", "MERCHANT_PROFILE_READ"}
    assert not any("WRITE" in scope or "PAYMENT" in scope for scope in sq.SCOPES)
    assert query["session"] == ["false"]
    assert "HttpOnly" in begin.headers["set-cookie"] and "Secure" in begin.headers["set-cookie"]
    state = query["state"][0]
    assert saved["begin"]["p_state"] == sq.digest(state)
    response = client.get("/connect/square/callback", params={"state": state, "code": "private-code"})
    assert response.status_code == 200
    assert "Square is connected" in response.text
    assert "https://app.example.com/#/build/integrations" in response.text
    assert "Nothing has been imported" in response.text
    assert sq.unseal(cfg, saved["finish"]["p_credentials"]) == TOKENS
    assert saved["exchange"]["body"]["redirect_uri"] == cfg.callback
    for secret in ["private-code", "private-access", "private-refresh", "private-secret", state]:
        assert secret not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_missing_cookie_cannot_exchange(client, monkeypatch):
    async def unexpected(*args, **kwargs):
        pytest.fail("No state or Square request allowed without browser binding")
    monkeypatch.setattr(sq, "rpc", unexpected)
    response = client.get("/connect/square/callback?state=stolen&code=stolen-code")
    assert response.status_code == 400


def test_replayed_callback_cannot_exchange(client, monkeypatch):
    async def rpc(*args, **kwargs):
        return []
    async def unexpected(*args, **kwargs):
        pytest.fail("Replayed state must never exchange a code")
    monkeypatch.setattr(sq, "rpc", rpc)
    monkeypatch.setattr(sq, "square", unexpected)
    client.cookies.set(routes.cookie_name("state"), "cookie")
    assert client.get("/connect/square/callback?state=state&code=private-code").status_code == 400


@pytest.mark.parametrize("suffix", ["error=access_denied", "code=private-code"])
def test_callback_rechecks_owner_and_denial(client, monkeypatch, suffix):
    async def rpc(*args, **kwargs):
        return [{"business_id": BIZ, "user_id": USER, "attempt_id": BIZ}]
    async def unexpected(*args, **kwargs):
        pytest.fail("Denied authorizations must never exchange tokens")
    def no_owner(*args):
        raise HTTPException(404, "business not found")
    monkeypatch.setattr(sq, "rpc", rpc)
    monkeypatch.setattr(sq, "square", unexpected)
    if suffix.startswith("code"):
        monkeypatch.setattr(routes, "owner", no_owner)
    client.cookies.set(routes.cookie_name("state"), "cookie")
    assert client.get("/connect/square/callback?state=state&"+suffix).status_code in (400,503)


def test_status_does_not_expose_credentials(client, monkeypatch):
    async def connection(*args):
        return {"status": "connected", "merchant_id": "merchant1", "credentials": "private-ciphertext",
                "state_hash": "private-state", "connected_at": "now"}
    monkeypatch.setattr(sq, "connection", connection)
    response = client.get("/square/status", params={"business_id": BIZ})
    assert response.json()["connected"] is True
    assert response.json()["booking_sync_enabled"] is False
    assert "private" not in response.text


@pytest.mark.parametrize("method,path", [("post","/connect/square/start"), ("get","/square/status"),
                                           ("get","/square/locations"), ("delete","/square/connection")])
def test_owner_gate_precedes_storage(client, monkeypatch, method, path):
    def denied(*args):
        raise HTTPException(404, "business not found")
    async def unexpected(*args, **kwargs):
        pytest.fail("Cross-tenant access reached storage")
    monkeypatch.setattr(routes, "owner", denied)
    monkeypatch.setattr(sq, "connection", unexpected)
    monkeypatch.setattr(sq, "rpc", unexpected)
    assert getattr(client, method)(path, params={"business_id": BIZ}).status_code == 404


def test_disconnect_failure_disables_access_and_retains_retry(client, monkeypatch):
    called = []
    async def rpc(name, **kwargs):
        called.append(name)
        return [{"merchant_id": "merchant1", "revision": BIZ}]
    async def square(cfg, method, path, **kwargs):
        assert called == ["disconnect"]
        assert kwargs["revoke"] is True
        assert kwargs["body"] == {"client_id": cfg.app_id, "merchant_id": "merchant1"}
        raise HTTPException(502, "upstream failed")
    monkeypatch.setattr(sq, "rpc", rpc)
    monkeypatch.setattr(sq, "square", square)
    response = client.delete("/square/connection", params={"business_id": BIZ})
    assert response.status_code == 202
    assert response.json()["revocation_pending"] is True
    assert called == ["disconnect"]


def test_locations_whitelist(client, monkeypatch):
    async def current(*args):
        return {"connection_id": BIZ, "selection_revision": BIZ, "selected_location_ids": []}
    monkeypatch.setattr(routes.bookings, "current", current)
    async def token(*args):
        return "private-access"
    async def square(*args, **kwargs):
        return {"locations": [{"id":"L1", "name":"Main", "status":"ACTIVE", "timezone":"America/New_York", "tax_ids":"private"}]}
    monkeypatch.setattr(sq, "access_token", token)
    monkeypatch.setattr(sq, "square", square)
    response = client.get("/square/locations", params={"business_id": BIZ})
    assert response.json()["locations"][0]["id"] == "L1"
    assert "private" not in response.text


def test_refresh_losing_to_disconnect_never_returns_token(monkeypatch, cfg):
    calls = []
    async def connection(*args):
        calls.append("read")
        if len(calls) == 1:
            return {"status":"connected", "credentials":sq.seal(cfg,TOKENS), "merchant_id":"merchant1",
                    "expires_at":datetime.now(timezone.utc).isoformat(), "revision":BIZ}
        return {"status":"revocation_pending"}
    async def square(*args, **kwargs):
        assert kwargs["body"]["grant_type"] == "refresh_token"
        return TOKENS
    async def rpc(*args, **kwargs):
        return False
    monkeypatch.setattr(sq, "connection", connection)
    monkeypatch.setattr(sq, "square", square)
    monkeypatch.setattr(sq, "rpc", rpc)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(sq.access_token(BIZ,cfg))
    assert exc.value.status_code == 409


@pytest.mark.parametrize("status", [400,401,403,429,500])
def test_upstream_errors_never_echo_secrets(monkeypatch, cfg, status):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(status,json={"errors":[{"detail":"private-access private-secret"}]}))
    monkeypatch.setattr(sq.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(sq.square(cfg,"GET","/v2/locations",token="private-access"))
    assert "private" not in str(exc.value)


def test_service_storage_outage_is_not_empty_result(monkeypatch):
    monkeypatch.setattr(sq.sb_clients,"sb_headers_service", lambda:{"Authorization":"Bearer service"})
    monkeypatch.setattr(sq.sb_clients,"sb_url", lambda:"https://db.example.com")
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(500,text="private-ciphertext"))
    monkeypatch.setattr(sq.httpx,"AsyncClient",lambda **kwargs:original(transport=transport,**kwargs))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(sq.rpc("claim",p_state="private-state"))
    assert exc.value.status_code == 503 and "private" not in str(exc.value)


def test_log_and_sentry_redaction():
    url="https://api.example.com/connect/square/callback?code=private-code&state=private-state"
    assert "private" not in redact(url)
    assert scrub_sentry_event({"request":{"url":url,"query_string":"code=private-code"},"extra":{"tokens":"private"}}) is None
    assert scrub_sentry_event({"transaction":"/square/locations","exception":{"locals":"private"}}) is None
    record=logging.LogRecord("uvicorn.access",20,"",0,"GET %s",(url,),None)
    assert RedactCredentialPaths().filter(record)
    assert "private" not in record.getMessage()


@pytest.mark.parametrize("status,code,pending", [("revocation_pending",202,True),("disconnected",200,False),("connected",409,None)])
def test_disconnect_lost_revision_reports_current_state(client, monkeypatch, status, code, pending):
    async def rpc(name, **kwargs):
        return [{"merchant_id":"merchant1", "revision": BIZ}] if name == "disconnect" else False
    async def square(*args, **kwargs):
        return {"success": True}
    async def connection(*args):
        return {"status": status}
    monkeypatch.setattr(sq, "rpc", rpc)
    monkeypatch.setattr(sq, "square", square)
    monkeypatch.setattr(sq, "connection", connection)
    response = client.delete("/square/connection", params={"business_id": BIZ})
    assert response.status_code == code
    if pending is not None:
        assert response.json()["revocation_pending"] is pending
        assert response.json()["disconnected"] is True


@pytest.mark.parametrize("status", [401, 403])
def test_appointments_onboarding_is_not_a_stale_location_conflict(monkeypatch, cfg, status):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(status, json={"errors": [
        {"code": "UNAUTHORIZED", "detail": "Merchant not onboarded to Appointments"},
        {"detail": "private-access private-secret"},
    ]}))
    monkeypatch.setattr(sq.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(sq.square(cfg, "GET", "/v2/bookings", token="private-access"))
    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "square_appointments_setup_required"}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(sq.square(cfg, "GET", "/v2/locations", token="private-access"))
    assert exc.value.status_code == 409
    assert exc.value.detail == {"code": "square_authorization_required"}


@pytest.mark.parametrize("errors", [None, {}, [None], [{"code": "UNAUTHORIZED", "detail": "private revised provider message"}]])
def test_unknown_booking_auth_errors_are_redacted_and_observable(monkeypatch, cfg, caplog, errors):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"errors": errors}))
    monkeypatch.setattr(sq.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(sq.square(cfg, "GET", "/v2/bookings", token="private-access"))
    assert exc.value.detail == {"code": "square_authorization_required"}
    assert "/v2/bookings authorization failure (status=401)" in caplog.text
    assert "private" not in caplog.text + str(exc.value.detail)
