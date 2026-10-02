"""
OAuth 2.1 in front of the MCP surface.

This is the first endpoint in the service that an unauthenticated stranger
is *supposed* to reach, so the tests are mostly about what it refuses.

Four properties carry the weight:

  No open redirect. Until client_id and redirect_uri are both known-good,
  an error renders as a page. Redirecting an error to an unvalidated URI
  would hand the request's parameters to whoever supplied it — and every
  real-world authorization-server breach of this shape started there.

  Registration is not authorization. RFC 7591 registration is open, per
  spec, so claude.ai can register itself. It must therefore grant nothing:
  a client_id is a name, and no code is issued without a live Agent Access
  key.

  Codes and refresh tokens are single use. Not "should be" — a second
  presentation must FAIL, because that is what turns a stolen credential
  from a working one into a detectable one.

  Revoking the key kills the phone. If the access token a refresh chain
  last issued has been revoked in Agent Access, the chain is dead. The
  alternative is a connection quietly alive on a credential the owner
  believes they switched off.
"""
from __future__ import annotations

import base64
import hashlib
import pathlib
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import mcp_oauth
import mcp_tokens


# ─── A fake Supabase, small enough to reason about ───────────────────

class _FakeDB:
    """Tables as lists of dicts; PostgREST-ish `?field=eq.value` filters.

    Deliberately not a mock library: these tests assert on what is STORED
    (hashes, never plaintext) as much as on what is returned, and a real
    dict is easier to make claims about than a call log.
    """

    def __init__(self) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {}

    @staticmethod
    def _split(path: str):
        p = path.lstrip("/")
        table, _, query = p.partition("?")
        filters = {}
        for part in query.split("&"):
            if "=" not in part:
                continue
            k, _, v = part.partition("=")
            if k in ("limit", "select", "order"):
                continue
            if v.startswith("eq."):
                filters[k] = v[3:]
            elif v == "is.null":
                filters[k] = None
        return table, filters

    def _match(self, row, filters):
        for k, v in filters.items():
            if v is None:
                if row.get(k) is not None:
                    return False
            elif str(row.get(k)) != str(v):
                return False
        return True

    def get(self, path: str):
        table, filters = self._split(path)
        return [r for r in self.tables.get(table, []) if self._match(r, filters)]

    def post(self, path: str, body: Dict[str, Any], prefer=None):
        table, _ = self._split(path)
        self.tables.setdefault(table, []).append(dict(body))
        return None

    def patch(self, path: str, body: Dict[str, Any]):
        table, filters = self._split(path)
        hit = [r for r in self.tables.get(table, []) if self._match(r, filters)]
        for r in hit:
            r.update(body)
        return hit


@pytest.fixture(autouse=True)
def db(monkeypatch):
    import sb_clients
    fake = _FakeDB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fake.patch)
    monkeypatch.setenv("MCP_TOKEN_SECRET", "test-secret-not-a-real-one")
    monkeypatch.setenv("MCP_PUBLIC_BASE_URL", "https://api.test")
    # The limiter has its own tests; here it must never be the reason
    # something failed, or every assertion below becomes ambiguous.
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda bucket, key: True)
    return fake


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(mcp_oauth.router)
    return TestClient(app)


# ─── PKCE helpers ────────────────────────────────────────────────────

VERIFIER = "a" * 64


def challenge_for(verifier: str) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


CHALLENGE = challenge_for(VERIFIER)
REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def register(client) -> str:
    r = client.post("/oauth/register", json={
        "client_name": "Claude", "redirect_uris": [REDIRECT]})
    assert r.status_code == 201
    return r.json()["client_id"]


def a_live_key(business_id: str = "biz-1") -> str:
    """A minted Agent Access key whose revocation row says 'live'."""
    token, row = mcp_tokens.mint(business_id, label="KAI — test")
    return token


def get_code(client, client_id: str, key: str) -> Optional[str]:
    r = client.post("/oauth/authorize", data={
        "client_id": client_id, "redirect_uri": REDIRECT, "state": "xyz",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "scope": "read", "agent_key": key, "decision": "approve",
    }, follow_redirects=False)
    if r.status_code != 302:
        return None
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return (q.get("code") or [None])[0]


# ─── Discovery ───────────────────────────────────────────────────────

def test_discovery_documents_point_at_each_other(client):
    """A client that knows only a URL has to be able to walk the chain."""
    pr = client.get("/.well-known/oauth-protected-resource").json()
    assert pr["resource"] == "https://api.test/mcp"
    assert pr["authorization_servers"] == ["https://api.test"]

    as_doc = client.get("/.well-known/oauth-authorization-server").json()
    assert as_doc["issuer"] == "https://api.test"
    assert as_doc["authorization_endpoint"] == "https://api.test/oauth/authorize"
    assert as_doc["token_endpoint"] == "https://api.test/oauth/token"
    assert as_doc["registration_endpoint"] == "https://api.test/oauth/register"


def test_the_path_suffixed_metadata_form_is_also_served(client):
    """Clients differ on which form they try; serving one is a silent
    'connection failed' for the half that try the other."""
    a = client.get("/.well-known/oauth-protected-resource").json()
    b = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert a == b


def test_plain_pkce_is_not_advertised(client):
    """S256 only. Advertising 'plain' invites a client to defeat PKCE."""
    doc = client.get("/.well-known/oauth-authorization-server").json()
    assert doc["code_challenge_methods_supported"] == ["S256"]


# ─── Registration ────────────────────────────────────────────────────

def test_registration_rejects_remote_http_redirects(client):
    """An authorization code on a plaintext wire is a leaked credential."""
    r = client.post("/oauth/register", json={
        "client_name": "sketchy", "redirect_uris": ["http://evil.test/cb"]})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_redirect_uri"


def test_registration_allows_loopback_http_for_native_clients(client):
    r = client.post("/oauth/register", json={
        "client_name": "native", "redirect_uris": ["http://127.0.0.1:7777/cb"]})
    assert r.status_code == 201


def test_registration_requires_a_redirect_uri(client):
    r = client.post("/oauth/register", json={"client_name": "nope"})
    assert r.status_code == 400


def test_registration_alone_grants_nothing(client, db):
    """The whole reason open registration is safe here: a client_id is a
    name, not a permission. Without a key, no code."""
    cid = register(client)
    assert get_code(client, cid, key="not-a-real-key") is None
    assert db.tables.get("mcp_oauth_codes", []) == []


# ─── /authorize refusals ─────────────────────────────────────────────

def test_unknown_client_does_not_redirect(client):
    """Renders an error page. Redirecting would trust an unvalidated URI."""
    r = client.get("/oauth/authorize", params={
        "client_id": "mcpc_nope", "redirect_uri": "https://evil.test/steal",
        "response_type": "code", "code_challenge": CHALLENGE,
        "code_challenge_method": "S256"}, follow_redirects=False)
    assert r.status_code == 400
    assert "location" not in {k.lower() for k in r.headers}


def test_unregistered_redirect_uri_does_not_redirect(client):
    """The open-redirect test. A registered client must not be usable as a
    launch pad for an arbitrary destination."""
    cid = register(client)
    r = client.get("/oauth/authorize", params={
        "client_id": cid, "redirect_uri": "https://evil.test/steal",
        "response_type": "code", "code_challenge": CHALLENGE,
        "code_challenge_method": "S256"}, follow_redirects=False)
    assert r.status_code == 400
    assert "location" not in {k.lower() for k in r.headers}
    assert "evil.test" not in r.text


def test_missing_pkce_is_refused(client):
    cid = register(client)
    r = client.get("/oauth/authorize", params={
        "client_id": cid, "redirect_uri": REDIRECT,
        "response_type": "code"}, follow_redirects=False)
    assert r.status_code == 302
    assert "invalid_request" in r.headers["location"]


def test_the_consent_page_refuses_to_be_framed(client):
    """A consent screen in an iframe is a clickjacking target."""
    cid = register(client)
    r = client.get("/oauth/authorize", params={
        "client_id": cid, "redirect_uri": REDIRECT, "response_type": "code",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256"})
    assert r.status_code == 200
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_denying_returns_access_denied(client, db):
    cid = register(client)
    r = client.post("/oauth/authorize", data={
        "client_id": cid, "redirect_uri": REDIRECT, "state": "xyz",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "agent_key": a_live_key(), "decision": "deny",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert "access_denied" in r.headers["location"]
    assert db.tables.get("mcp_oauth_codes", []) == []


def test_a_revoked_key_cannot_authorize(client, db):
    """The key is the credential. Revoking it must close this door too."""
    cid = register(client)
    key = a_live_key()
    claims = mcp_tokens.verify_mcp_token(key)
    db.tables["mcp_tokens"][0]["revoked_at"] = "2026-07-29T00:00:00+00:00"
    assert get_code(client, cid, key) is None
    assert db.tables.get("mcp_oauth_codes", []) == []


# ─── Happy path ──────────────────────────────────────────────────────

def exchange(client, cid, code, verifier=VERIFIER, redirect=REDIRECT):
    return client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect, "client_id": cid, "code_verifier": verifier})


def test_full_flow_issues_a_token_the_mcp_surface_accepts(client):
    """The point of the whole module: what comes out is an ordinary
    mcp_tokens credential, so mcp_server needed no change."""
    cid = register(client)
    code = get_code(client, cid, a_live_key("biz-42"))
    assert code

    r = exchange(client, cid, code)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["scope"] == "read"
    assert body["refresh_token"]

    claims = mcp_tokens.verify_mcp_token(body["access_token"])
    assert claims is not None
    assert claims["biz"] == "biz-42"
    assert claims["scp"] == ["read"]


def test_the_issued_token_appears_as_a_revocable_row(client, db):
    """It must show up in Agent Access like any hand-minted key — that is
    what makes one revoke button enough."""
    cid = register(client)
    code = get_code(client, cid, a_live_key())
    body = exchange(client, cid, code).json()
    rows = [r for r in db.tables["mcp_tokens"]
            if r["token_hash"] == mcp_tokens.token_hash(body["access_token"])]
    assert len(rows) == 1
    assert rows[0]["label"].startswith("OAuth · ")


def test_secrets_are_stored_only_as_hashes(client, db):
    """A dump of these tables must yield nothing usable."""
    cid = register(client)
    code = get_code(client, cid, a_live_key())
    stored = db.tables["mcp_oauth_codes"][0]
    assert code not in str(stored)
    assert stored["code_hash"] == hashlib.sha256(code.encode()).hexdigest()

    body = exchange(client, cid, code).json()
    r_row = db.tables["mcp_oauth_refresh"][0]
    assert body["refresh_token"] not in str(r_row)


# ─── Token endpoint refusals ─────────────────────────────────────────

def test_wrong_verifier_is_refused(client):
    """Without this, an intercepted code is enough on its own."""
    cid = register(client)
    code = get_code(client, cid, a_live_key())
    r = exchange(client, cid, code, verifier="b" * 64)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_a_code_works_exactly_once(client):
    cid = register(client)
    code = get_code(client, cid, a_live_key())
    assert exchange(client, cid, code).status_code == 200
    second = exchange(client, cid, code)
    assert second.status_code == 400
    assert second.json()["error"] == "invalid_grant"


def test_a_mismatched_redirect_uri_is_refused(client):
    """RFC 6749 §4.1.3 — a code stolen from one client must not be
    redeemable against another registration."""
    cid = register(client)
    code = get_code(client, cid, a_live_key())
    r = exchange(client, cid, code, redirect="https://claude.ai/other")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_unsupported_grant_type_is_named_as_such(client):
    r = client.post("/oauth/token", data={"grant_type": "password"})
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


def test_token_responses_are_never_cached(client):
    cid = register(client)
    code = get_code(client, cid, a_live_key())
    r = exchange(client, cid, code)
    assert r.headers["cache-control"] == "no-store"


# ─── Refresh ─────────────────────────────────────────────────────────

def refresh(client, cid, token):
    return client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": token, "client_id": cid})


def test_refresh_returns_a_new_pair(client):
    """Kevin authorizes once. Without this the connector dies at 90 days —
    in practice mid-question, on a phone, with no explanation."""
    cid = register(client)
    code = get_code(client, cid, a_live_key())
    first = exchange(client, cid, code).json()

    r = refresh(client, cid, first["refresh_token"])
    assert r.status_code == 200
    second = r.json()
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]
    assert mcp_tokens.verify_mcp_token(second["access_token"]) is not None


def test_a_refresh_token_cannot_be_replayed(client):
    """Rotation is what makes a copied token detectable rather than merely
    useless."""
    cid = register(client)
    code = get_code(client, cid, a_live_key())
    first = exchange(client, cid, code).json()
    assert refresh(client, cid, first["refresh_token"]).status_code == 200
    replay = refresh(client, cid, first["refresh_token"])
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_revoking_the_access_token_kills_the_refresh_chain(client, db):
    """The owner's kill switch has to reach the phone. Otherwise 'revoke'
    leaves a connection alive on a credential they switched off."""
    cid = register(client)
    code = get_code(client, cid, a_live_key())
    issued = exchange(client, cid, code).json()

    jti = mcp_tokens.verify_mcp_token(issued["access_token"])["jti"]
    for row in db.tables["mcp_tokens"]:
        if row["jti"] == jti:
            row["revoked_at"] = "2026-07-29T00:00:00+00:00"

    r = refresh(client, cid, issued["refresh_token"])
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_a_refresh_token_from_another_client_is_refused(client):
    cid = register(client)
    other = register(client)
    code = get_code(client, cid, a_live_key())
    issued = exchange(client, cid, code).json()
    r = refresh(client, other, issued["refresh_token"])
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


# ─── The grant is gated too ──────────────────────────────────────────
#
# mcp_server refuses the CALL; that is the load-bearing check. This
# refuses the CREDENTIAL, so a below-tier business never ends up holding
# a connector that answers "not on your plan" to every request — which
# is a worse experience, and a worse support ticket, than never having
# connected at all.

def test_a_business_without_a_plan_is_refused_the_grant(client, db, monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    db.tables["businesses"] = [{"id": "biz-1"}]          # no plan at all
    cid = register(client)

    r = client.post("/oauth/authorize", data={
        "client_id": cid, "redirect_uri": REDIRECT, "state": "xyz",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "scope": "read", "agent_key": a_live_key(), "decision": "approve",
    }, follow_redirects=False)

    assert r.status_code == 200, "answered on the consent page, not redirected"
    assert "active plan" in r.text
    assert db.tables.get("mcp_oauth_codes", []) == [], "a code was issued anyway"


def test_a_starter_business_gets_the_grant_narrowed_to_read(client, db, monkeypatch):
    """Read on every plan, write on Professional (2026-09-04). A Starter
    owner pasting a write key gets a read-only connection: narrower,
    never refused."""
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    db.tables["businesses"] = [{"id": "biz-1", "comp_tier": "starter"}]
    cid = register(client)
    token, _row = mcp_tokens.mint("biz-1", label="KAI — write", scopes=["read", "write"])

    r = client.post("/oauth/authorize", data={
        "client_id": cid, "redirect_uri": REDIRECT, "state": "xyz",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "scope": "read write", "agent_key": token, "decision": "approve",
    }, follow_redirects=False)

    assert r.status_code == 302, "the connection is made"
    codes = db.tables.get("mcp_oauth_codes", [])
    assert codes and codes[0]["scope"] == "read", "narrowed, not refused"


def test_a_professional_business_still_gets_the_grant(client, db, monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    db.tables["businesses"] = [{"id": "biz-1", "comp_tier": "professional"}]
    cid = register(client)
    assert get_code(client, cid, a_live_key()) is not None


def test_the_grant_gate_is_dormant_until_billing_enforce_is_on(client, db,
                                                               monkeypatch):
    monkeypatch.setenv("BILLING_ENFORCE", "off")
    db.tables["businesses"] = [{"id": "biz-1", "comp_tier": "starter"}]
    cid = register(client)
    assert get_code(client, cid, a_live_key()) is not None


def test_the_grant_gate_fails_OPEN(client, db, monkeypatch):
    """An entitlement gate. The refusals on this path that protect data —
    unknown client, unregistered redirect, revoked key, missing PKCE —
    all fail closed and must keep doing so. This one must not: a lookup
    blip locking a paying owner out of connecting is the worse outcome."""
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    import sb_clients

    def _boom(path):
        if path.startswith("/businesses"):
            raise RuntimeError("db down")
        return db.get(path)

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
    cid = register(client)
    assert get_code(client, cid, a_live_key()) is not None
