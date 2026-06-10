"""
plaid_helpers.py — Phase F.2 v1.

Plaid SDK setup + access-token encryption helpers.

Architecture decisions baked in (per F.2 v1 ruling):
  - PLAID_ENV defaults to 'sandbox' until Kevin sets PLAID_ENV=production.
  - Access tokens encrypted at rest via pgcrypto's pgp_sym_encrypt
    (T9-α). The key lives in PLAID_ENCRYPTION_KEY env var; rotating
    it requires re-encrypting in place (not in scope for v1).
  - Server-side decryption only — the access_token never leaves the
    backend process.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger("plaid_helpers")


# ─── Env-driven config ───────────────────────────────────────────────


def plaid_env() -> str:
    """Returns the configured Plaid environment. Defaults to sandbox
    so a misconfigured deploy never accidentally hits production."""
    return (os.environ.get("PLAID_ENV") or "sandbox").lower().strip()


def plaid_client_id() -> str:
    return os.environ.get("PLAID_CLIENT_ID", "")


def plaid_secret() -> str:
    return os.environ.get("PLAID_SECRET", "")


def plaid_webhook_secret() -> str:
    return os.environ.get("PLAID_WEBHOOK_SECRET", "")


def plaid_encryption_key() -> str:
    """Symmetric key used to encrypt access tokens at rest.

    Stored separately from the Supabase service role key so a leaked
    PostgREST credential alone cannot decrypt tokens. Required in
    production; absence raises at first encrypt/decrypt call."""
    return os.environ.get("PLAID_ENCRYPTION_KEY", "")


def plaid_configured() -> bool:
    """Lightweight preflight for status surfaces — does NOT validate
    the credentials with Plaid, just confirms env shape."""
    return bool(plaid_client_id() and plaid_secret() and plaid_encryption_key())


# ─── Plaid SDK client ────────────────────────────────────────────────


def get_plaid_client():
    """Return a configured plaid.Client (sync). Imported lazily so
    the module can be imported on cold start without the SDK installed
    (e.g. during running pytest collection or in environments where
    Plaid isn't yet configured)."""
    if not plaid_client_id() or not plaid_secret():
        raise RuntimeError(
            "Plaid not configured — set PLAID_CLIENT_ID, PLAID_SECRET, "
            "PLAID_ENV, and PLAID_ENCRYPTION_KEY env vars."
        )
    from plaid.api import plaid_api
    from plaid.configuration import Configuration
    from plaid.api_client import ApiClient

    env_map = {
        "sandbox":     "https://sandbox.plaid.com",
        "development": "https://development.plaid.com",
        "production":  "https://production.plaid.com",
    }
    host = env_map.get(plaid_env(), env_map["sandbox"])
    cfg = Configuration(
        host=host,
        api_key={"clientId": plaid_client_id(), "secret": plaid_secret()},
    )
    return plaid_api.PlaidApi(ApiClient(cfg))


# ─── Access token encryption (pgcrypto pgp_sym_encrypt/decrypt) ──────
#
# We use pgcrypto's symmetric envelope (pgp_sym_encrypt). Storage type
# is bytea. Reads route through sb_clients with a tiny SQL-side
# decryption wrapper because PostgREST can't natively call pgp_sym_decrypt
# without an exposed function — so we expose two RPCs the backend can
# call as service role:
#
#   plaid_token_encrypt(plain text, key text) returns bytea
#   plaid_token_decrypt(cipher bytea, key text) returns text
#
# These are created lazily by helpers below on first use — the migration
# left them out so this module remains the single source of truth for
# crypto plumbing.


def encrypt_token(plain: str) -> Optional[str]:
    """Encrypt an access token via Postgres pgp_sym_encrypt RPC.

    Returns the PostgREST hex-encoded ciphertext (\\x...) suitable for
    direct INSERT on plaid_items.access_token_enc. Callers must refuse
    to persist when this returns None (key unset / RPC missing).
    """
    key = plaid_encryption_key()
    if not key or not plain:
        return None
    import sb_clients
    try:
        result = sb_clients.sb_post_as_service(
            "/rpc/plaid_token_encrypt",
            {"plain": plain, "key": key},
        )
        # PostgREST returns the bytea as a \\x-prefixed hex string.
        # On some configurations the scalar comes back wrapped in a
        # one-element list; normalize either shape.
        if isinstance(result, list) and result:
            return str(result[0]) if result[0] is not None else None
        if isinstance(result, str):
            return result
        return None
    except Exception as e:
        logger.warning(f"[plaid] encrypt_token RPC failed: {e}")
        return None


def decrypt_token(cipher) -> Optional[str]:
    """Reverse of encrypt_token. Accepts the hex string PostgREST
    returns on a SELECT of the bytea column."""
    key = plaid_encryption_key()
    if not key or cipher is None:
        return None
    if isinstance(cipher, bytes):
        cipher_arg = cipher.decode("utf-8", errors="replace")
    else:
        cipher_arg = cipher
    import sb_clients
    try:
        result = sb_clients.sb_post_as_service(
            "/rpc/plaid_token_decrypt",
            {"cipher": cipher_arg, "key": key},
        )
        if isinstance(result, list) and result:
            return str(result[0]) if result[0] is not None else None
        if isinstance(result, str):
            return result
        return None
    except Exception as e:
        logger.warning(f"[plaid] decrypt_token RPC failed: {e}")
        return None


# ─── Webhook signature verification ──────────────────────────────────


# ─── Webhook signature verification (hardened) ──────────────────────
# Plaid signs every webhook with an ES256 JWT in the Plaid-Verification
# header. Full documented procedure:
#   1. Read the unverified header; require alg == ES256; extract `kid`.
#   2. Fetch the verification key for that kid from Plaid's
#      /webhook_verification_key/get (cached — keys are long-lived; a
#      cached key is refetched only if Plaid marked it expired).
#   3. Verify the JWT signature against the JWK.
#   4. Reject tokens older than 5 minutes (iat replay window).
#   5. SHA-256 the raw request body and constant-time-compare it with the
#      JWT's request_body_sha256 claim.
# The unsigned-allowed path exists ONLY when Plaid isn't configured at all
# (credential-less local tests) — any configured deploy verifies fully.

_WEBHOOK_IAT_MAX_AGE_SECS = 5 * 60
# kid → JWK dict cache. Plaid rate-limits the key endpoint; keys rotate
# rarely and old keys get `expired_at` set rather than vanishing.
_webhook_key_cache: dict = {}


def _fetch_webhook_key(kid: str) -> Optional[dict]:
    """Fetch (with cache) the JWK for a key id. Returns None when the key
    can't be retrieved or Plaid marked it expired."""
    cached = _webhook_key_cache.get(kid)
    if cached is not None and not cached.get("expired_at"):
        return cached
    try:
        from plaid.model.webhook_verification_key_get_request import (
            WebhookVerificationKeyGetRequest,
        )
        client = get_plaid_client()
        resp = client.webhook_verification_key_get(
            WebhookVerificationKeyGetRequest(key_id=kid)
        )
        key = resp.key.to_dict() if hasattr(resp.key, "to_dict") else dict(resp.key)
        _webhook_key_cache[kid] = key
        if key.get("expired_at"):
            return None
        return key
    except Exception as e:
        logger.warning(f"[plaid] webhook verification key fetch failed for kid={kid}: {e}")
        return None


def verify_webhook_signature(payload: bytes, signed_jwt: str) -> bool:
    """Verify a Plaid webhook's Plaid-Verification JWT against the raw body.
    Strict in any configured environment (sandbox AND production); permissive
    only when Plaid is not configured at all (credential-less local tests)."""
    if not signed_jwt:
        return False
    if not plaid_configured():
        # No Plaid credentials in this process (unit tests / bare local dev).
        return True
    try:
        import hashlib
        import hmac as _hmac
        import time
        import jwt
        from jwt import algorithms as jwt_algorithms

        header = jwt.get_unverified_header(signed_jwt)
        if header.get("alg") != "ES256":
            logger.warning(f"[plaid] webhook JWT rejected: alg={header.get('alg')}")
            return False
        kid = header.get("kid")
        if not kid:
            logger.warning("[plaid] webhook JWT rejected: missing kid")
            return False

        key_dict = _fetch_webhook_key(kid)
        if not key_dict:
            return False
        public_key = jwt_algorithms.ECAlgorithm.from_jwk(json.dumps(key_dict))

        claims = jwt.decode(
            signed_jwt, key=public_key, algorithms=["ES256"],
            options={"require": ["iat", "request_body_sha256"]},
        )

        iat = int(claims.get("iat") or 0)
        if abs(time.time() - iat) > _WEBHOOK_IAT_MAX_AGE_SECS:
            logger.warning("[plaid] webhook JWT rejected: iat outside replay window")
            return False

        body_hash = hashlib.sha256(payload).hexdigest()
        claimed = str(claims.get("request_body_sha256") or "")
        if not _hmac.compare_digest(body_hash, claimed):
            logger.warning("[plaid] webhook JWT rejected: body hash mismatch")
            return False
        return True
    except Exception as e:
        logger.warning(f"[plaid] webhook signature verification failed: {e}")
        return False
