"""
mcp_tokens.py — scoped credentials for the agent-facing surface.

Build 3 of Stage 1. Extends the HMAC pattern in `customer_token.py`
rather than inventing one: `<payload_b64>.<sig_b64>`, HMAC-SHA256,
`hmac.compare_digest`. Same shape, different claims and one addition.

WHY NOT JUST KEEP USING THE OWNER'S JWT
  Builds 1 and 2 authenticated with the owner's Supabase JWT, which was
  right for a read-only single-tenant experiment. It stops being right
  the moment a credential has to live in an external client's config
  file: a JWT there cannot be scoped, cannot be named, expires on a
  schedule you do not control, and revoking it means changing the
  password you log in with. These are the opposite of all four.

THE SIGNATURE PROVES AUTHENTICITY. THE TABLE PROVIDES REVOCATION.
  Verification is deliberately two steps, and they answer different
  questions:

    verify_mcp_token()   is this token real and unexpired? Pure crypto,
                         no database, no network. Cheap enough to run
                         before anything else.
    is_revoked()         has it been switched off since? One indexed
                         read on `jti`.

  Splitting them matters because the first is what makes a forged or
  expired token cheap to reject, and the second is what makes "revoke"
  mean "stops working now" rather than "stops working when it expires".

WHAT IS STORED
  The SHA-256 hash of the token, never the token. The plaintext is
  returned once by `mint()` and is then unrecoverable. A database dump
  yields hashes.

FAIL CLOSED
  Every ambiguous case here resolves to "no". A missing secret, an
  unreadable table, a malformed claim — all refuse. That is the opposite
  of the practitioner-facing modules in this service, and deliberately
  so: this is the surface where being wrong is expensive.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

import sb_clients

logger = logging.getLogger("mcp_tokens")

# Reuses the customer-token secret when a dedicated one is not set, so the
# surface works the moment it deploys. MCP_TOKEN_SECRET overrides — and
# should be set, because rotating it then revokes every agent credential
# WITHOUT also invalidating every customer widget link.
_SECRET_ENVS = ("MCP_TOKEN_SECRET", "CUSTOMER_TOKEN_SECRET")

DEFAULT_TTL_SECONDS = 90 * 24 * 60 * 60      # 90 days
SCOPE_READ = "read"
# `write` lets the holder call the class A verbs the MCP surface offers —
# reversible records only. It is NOT "everything Chief can do": class C
# (sends, money, hard deletes) has no scope and never will, and class B
# does not exist until an outbox does. See action_registry's header.
SCOPE_WRITE = "write"
KNOWN_SCOPES = (SCOPE_READ, SCOPE_WRITE)


def normalize_scopes(scopes: Optional[List[str]]) -> List[str]:
    """Unknown scopes are dropped, never honoured; the result is never
    empty; and `write` always carries `read` with it, because an agent
    that can change a record it cannot look at is a worse credential,
    not a narrower one."""
    keep = [s for s in (scopes or []) if s in KNOWN_SCOPES]
    if SCOPE_WRITE in keep and SCOPE_READ not in keep:
        keep.append(SCOPE_READ)
    return sorted(set(keep)) or [SCOPE_READ]


def _secret() -> bytes:
    """The ROOT. Since 2026-09-04 it never signs a key directly; each
    business signs with a key derived from it (see _signing_key)."""
    for env in _SECRET_ENVS:
        s = (os.environ.get(env) or "").strip()
        if s:
            return s.encode("utf-8")
    # Fail closed. A signing secret that silently defaults would make every
    # token forgeable by anyone who read this file.
    raise RuntimeError(
        "no token secret configured — set MCP_TOKEN_SECRET (preferred) or "
        "CUSTOMER_TOKEN_SECRET before minting or verifying MCP tokens")


# PER-BUSINESS SIGNING KEYS (2026-09-04). An agent key lives in somebody
# else's config file, which is the strongest reason for containment: a
# key recovered for one business must not be able to mint for another.
# HKDF over `agent-key|v2|<business_id>` from the root, the same helper
# and the same shape customer_token adopted the same day. Tokens carry
# `v: 2`; a token with no `v` was signed by the root directly and
# verifies against it until LEGACY_SUNSET (every such token has expired
# by then — 90-day TTL, and OAuth refreshes reissue in the new format).
# When the sunset passes, delete the legacy branch; a test says so.
TOKEN_VERSION = 2
LEGACY_SUNSET = "2026-12-04"
_PURPOSE = "agent-key"


def _signing_key(business_id: str) -> bytes:
    from customer_token import derive_key
    return derive_key(_PURPOSE, str(business_id), root=_secret())


def _peek(payload_b64: str) -> Optional[Dict[str, Any]]:
    try:
        claims = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None
    return claims if isinstance(claims, dict) else None


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def token_hash(token: str) -> str:
    """What goes in the database."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


# ─── mint ────────────────────────────────────────────────────────────

def mint(business_id: str, *, label: str = "unnamed",
         scopes: Optional[List[str]] = None,
         ttl_seconds: int = DEFAULT_TTL_SECONDS,
         created_by: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Create a token. Returns (plaintext, row).

    The plaintext is returned ONCE and never stored. Callers must show it
    to the owner immediately; there is no path to recover it afterwards,
    by design.
    """
    scopes = normalize_scopes(scopes or [SCOPE_READ])
    now = int(time.time())
    jti = secrets.token_urlsafe(16)
    payload = {
        "biz": str(business_id),
        "jti": jti,
        "scp": sorted(scopes),
        "iat": now,
        "exp": now + int(ttl_seconds),
        "v": TOKEN_VERSION,
    }
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = hmac.new(_signing_key(business_id), payload_b64.encode("utf-8"),
                   hashlib.sha256).digest()
    token = f"{payload_b64}.{_b64url_encode(sig)}"

    row = {
        "business_id": str(business_id),
        "jti": jti,
        "token_hash": token_hash(token),
        "label": (label or "unnamed")[:120],
        "scopes": sorted(scopes),
        "created_by": created_by,
        "expires_at": _iso(now + int(ttl_seconds)),
    }
    sb_clients.sb_post_as_service("/mcp_tokens", row, prefer="return=minimal")
    logger.info("[mcp_tokens] minted jti=%s label=%r scopes=%s", jti, label, scopes)
    return token, row


def _iso(epoch: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


# ─── verify ──────────────────────────────────────────────────────────

def verify_mcp_token(token: str) -> Optional[Dict[str, Any]]:
    """Signature + expiry only. Returns claims, or None.

    Pure crypto — no database, no network. This runs first precisely so
    that a forged or expired token costs nothing to reject.
    """
    if not isinstance(token, str) or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError:
        return None
    # The claims pick the key (they are not secret — base64 in a header);
    # nothing is trusted until the signature holds. A forged `biz` only
    # selects a key that will not.
    claims = _peek(payload_b64)
    if not claims or not claims.get("biz"):
        return None
    version = claims.get("v")
    try:
        if version == TOKEN_VERSION:
            key = _signing_key(str(claims["biz"]))
        elif version is None:
            key = _secret()          # LEGACY — dead after LEGACY_SUNSET
        else:
            return None
        expected = hmac.new(key, payload_b64.encode("utf-8"),
                            hashlib.sha256).digest()
        actual = _b64url_decode(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(expected, actual):
        return None
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp <= int(time.time()):
        return None
    if not claims.get("biz") or not claims.get("jti"):
        return None
    return claims


def is_revoked(jti: str) -> bool:
    """Has this token been switched off? Fails CLOSED — if the check
    cannot be performed, the token is treated as revoked.

    That is the uncomfortable choice and the right one: the alternative
    is a database blip briefly re-enabling every credential the owner
    thought they had killed.
    """
    if not jti:
        return True
    try:
        rows = sb_clients.sb_get_as_service(
            f"/mcp_tokens?jti=eq.{jti}&select=revoked_at&limit=1")
    except Exception as e:
        logger.warning("[mcp_tokens] revocation check failed, refusing: %s", e)
        return True
    if rows is None:
        return True
    if not rows:
        # Signed by us, but no row: minted against a different database,
        # or the row was deleted. Either way it is not a credential this
        # deployment recognises.
        logger.warning("[mcp_tokens] no row for jti=%s — refusing", jti)
        return True
    return bool(rows[0].get("revoked_at"))


def has_scope(claims: Dict[str, Any], scope: str) -> bool:
    scopes = claims.get("scp")
    return isinstance(scopes, list) and scope in scopes


def touch(jti: str) -> None:
    """Record use. Best-effort — usage stats must never gate a call.

    Deliberately not a counter increment via RPC: a lost update here is
    worth nothing, and a failed call because the stats write deadlocked
    would be worth a great deal.
    """
    try:
        from datetime import datetime, timezone
        sb_clients.sb_patch_as_service(
            f"/mcp_tokens?jti=eq.{jti}",
            {"last_used_at": datetime.now(timezone.utc).isoformat()})
    except Exception:
        pass


# ─── management ──────────────────────────────────────────────────────

def list_tokens(business_id: str) -> List[Dict[str, Any]]:
    """Tokens for a business. Never returns a hash — the owner has no use
    for it and it should not travel to a browser."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/mcp_tokens?business_id=eq.{business_id}"
            f"&order=created_at.desc&limit=100"
            f"&select=id,jti,label,scopes,created_at,expires_at,"
            f"revoked_at,last_used_at,use_count") or []
        return rows
    except Exception as e:
        logger.warning("[mcp_tokens] list failed: %s", e)
        return []


def revoke(business_id: str, jti: str) -> bool:
    """Switch a token off. Scoped by business_id as well as jti so that a
    guessed jti from another tenant cannot revoke anything — revocation is
    a write, and writes get the same tenancy treatment as reads."""
    if not jti:
        return False
    try:
        from datetime import datetime, timezone
        sb_clients.sb_patch_as_service(
            f"/mcp_tokens?jti=eq.{jti}&business_id=eq.{business_id}",
            {"revoked_at": datetime.now(timezone.utc).isoformat()})
        logger.info("[mcp_tokens] revoked jti=%s", jti)
        return True
    except Exception as e:
        logger.warning("[mcp_tokens] revoke failed: %s", e)
        return False
