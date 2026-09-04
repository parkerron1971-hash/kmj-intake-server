"""
OAuth scopes on the MCP surface (Stage 4, 2026-09-03).

The grant is what the client asked for, capped by what the pasted key
carries. Narrower silently; wider never. The fixtures and helpers are
test_mcp_oauth's own, imported so this file cannot drift into testing a
different flow than the one that ships.
"""
from __future__ import annotations

import pathlib
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import mcp_tokens
from test_mcp_oauth import (  # noqa: F401 — fixtures must be in scope
    CHALLENGE, REDIRECT, a_live_key, client, db, exchange, refresh, register)


def _code_with_scope(client, cid, key, scope):
    r = client.post("/oauth/authorize", data={
        "client_id": cid, "redirect_uri": REDIRECT, "state": "s",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "scope": scope, "agent_key": key, "decision": "approve",
    }, follow_redirects=False)
    assert r.status_code == 302, r.text
    q = parse_qs(urlsplit(r.headers["location"]).query)
    return q["code"][0]


def _write_key(business_id="biz-1"):
    token, _ = mcp_tokens.mint(business_id, label="agent", scopes=["read", "write"])
    return token


def test_a_write_request_against_a_read_only_key_yields_read_only(client):
    cid = register(client)
    code = _code_with_scope(client, cid, a_live_key(), "read write")
    body = exchange(client, cid, code).json()
    assert body["scope"] == "read"
    assert mcp_tokens.verify_mcp_token(body["access_token"])["scp"] == ["read"]


def test_a_write_request_against_a_write_key_yields_write(client):
    cid = register(client)
    code = _code_with_scope(client, cid, _write_key(), "read write")
    body = exchange(client, cid, code).json()
    assert body["scope"] == "read write"
    assert mcp_tokens.verify_mcp_token(body["access_token"])["scp"] == ["read", "write"]


def test_a_read_request_against_a_write_key_stays_read(client):
    """The client decides how much it wants; the key decides how much it
    may have. Asking for less gets less."""
    cid = register(client)
    code = _code_with_scope(client, cid, _write_key(), "read")
    body = exchange(client, cid, code).json()
    assert body["scope"] == "read"


def test_unknown_scopes_are_never_granted(client):
    cid = register(client)
    code = _code_with_scope(client, cid, _write_key(), "read write admin delete")
    body = exchange(client, cid, code).json()
    assert body["scope"] == "read write"


def test_refresh_carries_the_granted_scope_and_cannot_widen_it(client):
    cid = register(client)
    code = _code_with_scope(client, cid, _write_key(), "read write")
    first = exchange(client, cid, code).json()
    second = refresh(client, cid, first["refresh_token"]).json()
    assert second["scope"] == "read write"

    cid2 = register(client)
    code2 = _code_with_scope(client, cid2, a_live_key(), "read write")
    narrow = exchange(client, cid2, code2).json()
    again = refresh(client, cid2, narrow["refresh_token"]).json()
    assert again["scope"] == "read", "a refresh cannot widen what consent narrowed"


def test_the_consent_page_says_what_a_write_grant_means(client):
    cid = register(client)
    r = client.get("/oauth/authorize", params={
        "client_id": cid, "redirect_uri": REDIRECT, "response_type": "code",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "scope": "read write"})
    assert r.status_code == 200
    text = r.text.lower()
    assert "keep records" in text
    assert "cannot send anything to a client" in text
    assert "read-only key connects read-only" in text

    r = client.get("/oauth/authorize", params={
        "client_id": cid, "redirect_uri": REDIRECT, "response_type": "code",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "scope": "read"})
    assert "read-only." in r.text.lower()


def test_metadata_advertises_both_scopes(client):
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.json()["scopes_supported"] == ["read", "write"]
