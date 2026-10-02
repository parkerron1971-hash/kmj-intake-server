"""
Scoped credentials for the agent-facing surface — Build 3.

A token here is the first credential in this system that lives in somebody
else's config file. That changes what the tests need to prove: not "does
it work" so much as what happens when it is stolen, expired, revoked,
forged, or pointed at the wrong tenant.

Two properties carry most of the weight.

The signature proves authenticity; the TABLE provides revocation. They are
separate steps because the first must be cheap enough to reject a forgery
without touching the database, and the second must make "revoke" mean
"stops working now" rather than "stops working when it expires".

A presented-but-bad token is REFUSED, never fallen through. Silent
fallback between credential kinds is how a revoked key keeps working.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import mcp_tokens as mt


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("MCP_TOKEN_SECRET", "test-secret-not-a-real-one")


@pytest.fixture
def _no_db(monkeypatch):
    """Stub the write so minting does not need Supabase."""
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: None)


# ─── mint / verify ───────────────────────────────────────────────────

def test_mint_returns_a_verifiable_token(_no_db):
    token, row = mt.mint("biz-1", label="laptop")
    claims = mt.verify_mcp_token(token)
    assert claims["biz"] == "biz-1"
    assert claims["jti"] == row["jti"]
    assert claims["scp"] == ["read"]


def test_the_plaintext_is_never_stored(_no_db):
    """A database dump must yield hashes, not working credentials."""
    token, row = mt.mint("biz-1")
    assert token not in json.dumps(row)
    assert row["token_hash"] == mt.token_hash(token)
    assert len(row["token_hash"]) == 64


def test_a_tampered_payload_fails(_no_db):
    """Swap the payload for another business, keep the signature."""
    token, _ = mt.mint("biz-1")
    _payload, sig = token.split(".", 1)
    other, _ = mt.mint("biz-EVIL")
    forged = other.split(".", 1)[0] + "." + sig
    assert mt.verify_mcp_token(forged) is None


def test_a_token_signed_with_another_secret_fails(monkeypatch, _no_db):
    token, _ = mt.mint("biz-1")
    monkeypatch.setenv("MCP_TOKEN_SECRET", "a-different-secret")
    assert mt.verify_mcp_token(token) is None


def test_expired_tokens_fail(_no_db):
    token, _ = mt.mint("biz-1", ttl_seconds=-1)
    assert mt.verify_mcp_token(token) is None


@pytest.mark.parametrize("junk", ["", "nonsense", "a.b.c", "....", None, 12345])
def test_malformed_tokens_fail(junk):
    assert mt.verify_mcp_token(junk) is None


def test_missing_secret_refuses_rather_than_defaulting(monkeypatch):
    """A signing secret that silently defaulted would make every token
    forgeable by anyone who read the file."""
    monkeypatch.delenv("MCP_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("CUSTOMER_TOKEN_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        mt._secret()


def test_unknown_scopes_are_dropped_not_honoured(_no_db):
    _t, row = mt.mint("biz-1", scopes=["read", "write", "admin"])
    # `write` became a real scope on 2026-09-03; `admin` is still nothing.
    assert row["scopes"] == ["read", "write"]


def test_write_always_carries_read(_no_db):
    """A key that can change a record it cannot look at is a worse
    credential, not a narrower one."""
    _t, row = mt.mint("biz-1", scopes=["write"])
    assert row["scopes"] == ["read", "write"]
    claims = mt.verify_mcp_token(_t)
    assert claims["scp"] == ["read", "write"]


def test_scopes_never_end_up_empty(_no_db):
    _t, row = mt.mint("biz-1", scopes=["nonsense"])
    assert row["scopes"] == ["read"]


# ─── revocation ──────────────────────────────────────────────────────

def test_revoked_token_is_rejected(monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p: [{"revoked_at": "2026-07-28T00:00:00Z"}])
    assert mt.is_revoked("jti-1") is True


def test_live_token_is_not_revoked(monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p: [{"revoked_at": None}])
    assert mt.is_revoked("jti-1") is False


def test_revocation_check_fails_CLOSED(monkeypatch):
    """The uncomfortable choice, and the right one: a database blip must
    not briefly re-enable every credential the owner thought they killed."""
    import sb_clients

    def _boom(p):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
    assert mt.is_revoked("jti-1") is True


def test_unknown_jti_is_treated_as_revoked(monkeypatch):
    """Signed by us but with no row: minted against another database, or
    the row was deleted. Either way this deployment does not know it."""
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [])
    assert mt.is_revoked("jti-ghost") is True


def test_empty_jti_is_revoked():
    assert mt.is_revoked("") is True
    assert mt.is_revoked(None) is True


def test_revoke_is_scoped_by_business(monkeypatch):
    """Revocation is a WRITE, and writes get the same tenancy treatment as
    reads — a guessed jti from another tenant must not revoke anything."""
    seen = {}
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: seen.update({"path": path}))
    mt.revoke("biz-1", "jti-9")
    assert "business_id=eq.biz-1" in seen["path"]
    assert "jti=eq.jti-9" in seen["path"]


def test_list_never_returns_the_hash(monkeypatch):
    """The owner has no use for it and it should not travel to a browser."""
    import sb_clients
    captured = {}
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p: captured.update({"p": p}) or [])
    mt.list_tokens("biz-1")
    assert "token_hash" not in captured["p"]


def test_touch_never_raises(monkeypatch):
    """Usage stats must never gate a call."""
    import sb_clients

    def _boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(sb_clients, "sb_patch_as_service", _boom)
    mt.touch("jti-1")  # must not raise


# ─── endpoint wiring ─────────────────────────────────────────────────

class _Req:
    def __init__(self, auth=None):
        self.headers = {"authorization": auth} if auth else {}


def test_no_bearer_means_no_token_caller():
    import mcp_server as mcp
    assert mcp._caller_from_token(_Req()) is None


def test_a_jwt_is_left_for_the_jwt_path():
    """A Supabase JWT is also a bearer token. Ours has two dot-parts, a JWT
    has three — anything with three is not ours to fail."""
    import mcp_server as mcp
    assert mcp._caller_from_token(_Req("Bearer aaa.bbb.ccc")) is None


def test_a_bad_token_is_refused_not_passed_along(_no_db):
    """Silent fallback between credentials is how a revoked key keeps
    working. A presented-but-bad token must stop the request."""
    import mcp_server as mcp
    with pytest.raises(mcp._TokenRefused):
        mcp._caller_from_token(_Req("Bearer bogus.signature"))


def test_a_revoked_token_is_refused(monkeypatch, _no_db):
    import mcp_server as mcp
    import sb_clients
    token, _ = mt.mint("biz-1")
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p: [{"revoked_at": "2026-07-28T00:00:00Z"}])
    with pytest.raises(mcp._TokenRefused):
        mcp._caller_from_token(_Req(f"Bearer {token}"))


def test_a_good_token_yields_its_business_from_the_signed_claim(monkeypatch, _no_db):
    """The business comes from the SIGNATURE, never from the request."""
    import mcp_server as mcp
    import sb_clients
    token, _ = mt.mint("biz-42")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p: [{"revoked_at": None}])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda p, b: None)
    caller = mcp._caller_from_token(_Req(f"Bearer {token}"))
    assert caller.kind == "token"
    assert caller.business_id == "biz-42"
    assert "read" in caller.scopes


def test_token_without_read_scope_cannot_call_tools():
    """Scope is checked before the registry, so a scoped-out token is
    refused even for a verb that is otherwise perfectly exposable."""
    import asyncio
    import mcp_server as mcp
    caller = mcp.Caller("token", "token:x", business_id="biz-1", scopes=[])
    allowed, ok, msg, _ = asyncio.run(mcp._call_tool("catch_up", {}, caller))
    assert allowed is False and ok is False
    assert "scope" in msg


def test_migration_stores_a_hash_and_revokes_grants():
    sql = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "supabase/APPLY-2026-07-28-mcp-tokens.sql").read_text(encoding="utf-8")
    ddl = "\n".join(line.split("--")[0] for line in sql.splitlines())
    assert "token_hash" in ddl
    assert "revoked_at" in ddl
    assert "REVOKE ALL ON public.mcp_tokens FROM anon, authenticated" in ddl
    assert "CREATE POLICY" not in ddl
