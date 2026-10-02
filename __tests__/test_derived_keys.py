"""
Per-business signing keys for the other two long-lived credentials
(2026-09-04): agent keys (mcp_tokens) and auditor links (auditor_links).

The customer-token change proved the shape; these pin that the two
surfaces took it faithfully — their own purpose string, their own root,
containment across businesses, legacy tokens honoured until each
sunset, and a v2 token never retried against the root.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import auditor_links as al
import customer_token as ct
import mcp_tokens as mt


@pytest.fixture(autouse=True)
def _roots(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "customer-root")
    monkeypatch.setenv("MCP_TOKEN_SECRET", "mcp-root")
    monkeypatch.setenv("AUDITOR_LINK_SECRET", "auditor-root")
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer=None: [dict(b)])


def _forge(claims, key, encode):
    p64 = encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    sig = hmac.new(key, p64.encode(), hashlib.sha256).digest()
    return f"{p64}.{encode(sig)}"


# ─── agent keys ──────────────────────────────────────────────────────

def test_agent_keys_carry_v2_and_verify():
    tok, row = mt.mint("biz-a", label="x")
    claims = mt.verify_mcp_token(tok)
    assert claims and claims["biz"] == "biz-a" and claims["v"] == mt.TOKEN_VERSION


def test_agent_key_derives_from_its_own_root_and_purpose():
    k = mt._signing_key("biz-a")
    assert k == ct.derive_key("agent-key", "biz-a", root=b"mcp-root")
    assert k != ct.derive_key("customer-token", "biz-a", root=b"mcp-root")
    assert k != ct.derive_key("agent-key", "biz-a", root=b"customer-root")
    assert mt._signing_key("biz-a") != mt._signing_key("biz-b")


def test_a_root_signed_v2_agent_key_is_refused():
    now = int(time.time())
    tok = _forge({"biz": "biz-a", "jti": "j", "scp": ["read"], "iat": now,
                  "exp": now + 600, "v": 2}, b"mcp-root", mt._b64url_encode)
    assert mt.verify_mcp_token(tok) is None


def test_one_businesss_agent_key_cannot_mint_for_another():
    now = int(time.time())
    tok = _forge({"biz": "biz-b", "jti": "j", "scp": ["read"], "iat": now,
                  "exp": now + 600, "v": 2}, mt._signing_key("biz-a"), mt._b64url_encode)
    assert mt.verify_mcp_token(tok) is None


def test_legacy_agent_keys_in_config_files_still_work():
    now = int(time.time())
    tok = _forge({"biz": "biz-a", "jti": "j", "scp": ["read"], "iat": now,
                  "exp": now + 600}, b"mcp-root", mt._b64url_encode)
    claims = mt.verify_mcp_token(tok)
    assert claims and claims["jti"] == "j" and "v" not in claims


def test_agent_key_unknown_version_is_refused():
    now = int(time.time())
    for key in (b"mcp-root", mt._signing_key("biz-a")):
        tok = _forge({"biz": "biz-a", "jti": "j", "scp": ["read"], "iat": now,
                      "exp": now + 600, "v": 7}, key, mt._b64url_encode)
        assert mt.verify_mcp_token(tok) is None


def test_agent_key_sunset_has_not_passed():
    assert _dt.date.today().isoformat() < mt.LEGACY_SUNSET, (
        "delete the `version is None` branch in mcp_tokens.verify_mcp_token and this test")


# ─── auditor links ───────────────────────────────────────────────────

def test_auditor_links_carry_v2_and_verify():
    tok, row = al.mint("biz-a", label="review")
    claims = al.verify(tok)
    assert claims and claims["biz"] == "biz-a" and claims["v"] == al.TOKEN_VERSION
    assert al.SCOPE_LEDGER_READ in claims["scp"]


def test_auditor_link_key_is_its_own():
    assert al._signing_key("biz-a") == ct.derive_key("auditor-link", "biz-a", root=b"auditor-root")
    assert al._signing_key("biz-a") != mt._signing_key("biz-a")
    assert al._signing_key("biz-a") != al._signing_key("biz-b")


def test_a_root_signed_v2_auditor_link_is_refused():
    now = int(time.time())
    tok = _forge({"biz": "biz-a", "jti": "j", "scp": [al.SCOPE_LEDGER_READ], "iat": now,
                  "exp": now + 600, "v": 2}, b"auditor-root", al._b64url_encode)
    assert al.verify(tok) is None


def test_legacy_auditor_links_in_inboxes_still_work():
    now = int(time.time())
    tok = _forge({"biz": "biz-a", "jti": "j", "scp": [al.SCOPE_LEDGER_READ], "iat": now,
                  "exp": now + 600}, b"auditor-root", al._b64url_encode)
    assert al.verify(tok)


def test_auditor_link_sunset_is_later_than_its_max_ttl():
    """MAX_TTL is 180 days, so a legacy link can be live longer than a
    customer token or an agent key. The sunset must respect that."""
    deploy = _dt.date(2026, 9, 4)
    sunset = _dt.date.fromisoformat(al.LEGACY_SUNSET)
    assert (sunset - deploy).days >= al.MAX_TTL_SECONDS // 86400
    assert _dt.date.today().isoformat() < al.LEGACY_SUNSET


def test_the_ledger_records_the_migration_as_applied():
    ledger = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "docs/MIGRATIONS.md").read_text(encoding="utf-8")
    row = next(l for l in ledger.splitlines() if "chief-jobs-heartbeat" in l)
    assert "**applied**" in row
