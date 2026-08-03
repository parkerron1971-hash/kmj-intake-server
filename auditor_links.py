"""
auditor_links.py — read-only ledger credentials for an outside reviewer.

A practice gets audited. The auditor is not a Solutionist customer and
never will be, so the History screen behind our login is not a proof to
them. The owner mints a link, hands it over, and revokes it when the
review is done.

THE SIGNATURE PROVES AUTHENTICITY. THE TABLE PROVIDES REVOCATION.
That split is lifted verbatim from mcp_tokens, and it is why a stateless
HMAC link (the store's download tokens) would be the wrong shape here: an
audit link must be revocable the instant a review ends, must expire on
its own if forgotten, and must be nameable — a credential you cannot
identify is one you will never revoke.

Narrower than an MCP token in three ways, on purpose:
  * one scope, `ledger:read`, and nothing may widen it;
  * an optional date window, so "the 2026 review" cannot wander into
    unrelated years;
  * a short default life (30 days), because a review ends.

Every use is written to the ledger it reads. Who looked, and when, is
part of the record — that is the Etherscan idea inverted: not public to
everyone, but accountable to the practice.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import sb_clients

logger = logging.getLogger("auditor_links")

# AUDITOR_LINK_SECRET first so rotating auditor credentials never
# invalidates agent credentials, and vice versa.
_SECRET_ENVS = ("AUDITOR_LINK_SECRET", "MCP_TOKEN_SECRET", "CUSTOMER_TOKEN_SECRET")

SCOPE_LEDGER_READ = "ledger:read"
KNOWN_SCOPES = (SCOPE_LEDGER_READ,)
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60      # a review ends
MAX_TTL_SECONDS = 180 * 24 * 60 * 60


def _secret() -> bytes:
    for env in _SECRET_ENVS:
        s = (os.environ.get(env) or "").strip()
        if s:
            return s.encode("utf-8")
    raise RuntimeError(
        "no token secret configured — set AUDITOR_LINK_SECRET before "
        "minting or verifying auditor links")


def _b64url_encode(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def token_hash(token: str) -> str:
    """What goes in the database. Never the token itself."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def mint(business_id: str, *, label: str = "unnamed",
         ttl_seconds: int = DEFAULT_TTL_SECONDS,
         window_start: Optional[str] = None,
         window_end: Optional[str] = None,
         created_by: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Mint a link. Returns (plaintext_token, row). The plaintext is
    returned ONCE and never stored."""
    ttl = max(60, min(int(ttl_seconds or DEFAULT_TTL_SECONDS), MAX_TTL_SECONDS))
    now = int(time.time())
    jti = secrets.token_urlsafe(16)
    payload = {
        "biz": str(business_id),
        "jti": jti,
        "scp": [SCOPE_LEDGER_READ],
        "iat": now,
        "exp": now + ttl,
    }
    # The window rides INSIDE the signed payload as well as the row, so a
    # tampered URL cannot widen what the link may see even if the row
    # were somehow read stale.
    if window_start:
        payload["ws"] = str(window_start)
    if window_end:
        payload["we"] = str(window_end)

    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = hmac.new(_secret(), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    token = f"{payload_b64}.{_b64url_encode(sig)}"

    row = {
        "business_id": str(business_id),
        "jti": jti,
        "token_hash": token_hash(token),
        "label": (label or "unnamed")[:120],
        "scopes": [SCOPE_LEDGER_READ],
        "window_start": window_start,
        "window_end": window_end,
        "created_by": created_by,
        "expires_at": _iso(now + ttl),
    }
    sb_clients.sb_post_as_service("/auditor_links", row, prefer="return=minimal")
    return token, row


def verify(token: str) -> Optional[Dict[str, Any]]:
    """Signature + expiry only, no DB. Returns claims, or None. Never
    raises — a malformed link is simply not a link."""
    try:
        if not isinstance(token, str) or token.count(".") != 1:
            return None
        payload_b64, sig_b64 = token.split(".", 1)
        expected = hmac.new(_secret(), payload_b64.encode("utf-8"),
                            hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_encode(expected), sig_b64):
            return None
        claims = json.loads(_b64url_decode(payload_b64))
        if not isinstance(claims, dict):
            return None
        exp = claims.get("exp")
        if not isinstance(exp, int) or exp <= time.time():
            return None
        if not claims.get("biz") or not claims.get("jti"):
            return None
        if SCOPE_LEDGER_READ not in (claims.get("scp") or []):
            return None
        return claims
    except Exception:
        return None


def is_revoked(jti: str) -> bool:
    """Fails CLOSED. An unknown row, a null result or a lookup error all
    mean revoked — on an external credential, "the check broke so access
    was granted" is the failure you least want."""
    if not jti:
        return True
    try:
        rows = sb_clients.sb_get_as_service(
            f"/auditor_links?jti=eq.{jti}&select=revoked_at&limit=1")
    except Exception as e:
        logger.warning("[auditor_links] revocation check failed, refusing: %s", e)
        return True
    if rows is None or not rows:
        return True
    return bool(rows[0].get("revoked_at"))


def touch(jti: str) -> None:
    """Best-effort usage stamp. Never raises."""
    try:
        rows = sb_clients.sb_get_as_service(
            f"/auditor_links?jti=eq.{jti}&select=use_count&limit=1") or []
        n = int((rows[0].get("use_count") if rows else 0) or 0)
        sb_clients.sb_patch_as_service(
            f"/auditor_links?jti=eq.{jti}",
            {"last_used_at": datetime.now(timezone.utc).isoformat(),
             "use_count": n + 1})
    except Exception as e:
        logger.info("[auditor_links] touch skipped: %s", e)


def list_links(business_id: str) -> List[Dict[str, Any]]:
    """What the owner sees. NEVER selects token_hash."""
    return sb_clients.sb_get_as_service(
        f"/auditor_links?business_id=eq.{business_id}"
        f"&select=jti,label,scopes,window_start,window_end,created_by,"
        f"created_at,expires_at,revoked_at,last_used_at,use_count"
        f"&order=created_at.desc&limit=100") or []


def revoke(business_id: str, jti: str) -> bool:
    """Scoped by business_id as well as jti, so a guessed jti from
    another tenant cannot revoke anything."""
    try:
        sb_clients.sb_patch_as_service(
            f"/auditor_links?jti=eq.{jti}&business_id=eq.{business_id}",
            {"revoked_at": datetime.now(timezone.utc).isoformat()})
        return True
    except Exception as e:
        logger.warning("[auditor_links] revoke failed: %s", e)
        return False


def resolve(token: str) -> Optional[Dict[str, Any]]:
    """The full door: signature → expiry → revocation → usage stamp.

    Returns a context dict the caller can trust, or None. Callers must
    never see the raw token beyond this point, and must never widen the
    window it returns.
    """
    claims = verify(token)
    if not claims:
        return None
    jti = str(claims.get("jti") or "")
    if is_revoked(jti):
        return None
    touch(jti)
    return {
        "business_id": str(claims.get("biz")),
        "jti": jti,
        "window_start": claims.get("ws"),
        "window_end": claims.get("we"),
    }
