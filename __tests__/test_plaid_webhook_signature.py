"""Plaid webhook signature hardening — REAL ES256 end-to-end verification.

Generates an actual ES256 keypair, signs real JWTs the way Plaid does
(kid header + iat + request_body_sha256 claims), and exercises every
acceptance/rejection path of the hardened verifier."""
from __future__ import annotations

import sys
import pathlib
import hashlib
import json
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

jwt = pytest.importorskip("jwt")
ec_mod = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec")

import plaid_helpers as ph
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


# ── one ES256 keypair for the module ─────────────────────────────────
_PRIVATE = ec.generate_private_key(ec.SECP256R1())
_PRIVATE_PEM = _PRIVATE.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
_PUBLIC_JWK = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(_PRIVATE.public_key()))
_PUBLIC_JWK.update({"kid": "test-kid", "alg": "ES256", "use": "sig",
                    "created_at": int(time.time()), "expired_at": None})

_BODY = b'{"webhook_type":"TRANSACTIONS","webhook_code":"SYNC_UPDATES_AVAILABLE"}'


def _sign(body: bytes = _BODY, *, iat: int = None, kid: str = "test-kid",
          alg: str = "ES256", body_hash: str = None) -> str:
    claims = {
        "iat": iat if iat is not None else int(time.time()),
        "request_body_sha256": body_hash if body_hash is not None
        else hashlib.sha256(body).hexdigest(),
    }
    return jwt.encode(claims, _PRIVATE_PEM, algorithm=alg, headers={"kid": kid})


@pytest.fixture
def configured(monkeypatch):
    """Plaid 'configured' + the key fetch returns our test JWK."""
    monkeypatch.setattr(ph, "plaid_configured", lambda: True)
    monkeypatch.setattr(ph, "_fetch_webhook_key",
                        lambda kid: dict(_PUBLIC_JWK) if kid == "test-kid" else None)


def test_valid_signature_passes(configured):
    assert ph.verify_webhook_signature(_BODY, _sign()) is True


def test_body_tamper_rejected(configured):
    token = _sign(_BODY)
    assert ph.verify_webhook_signature(b'{"tampered":true}', token) is False


def test_wrong_hash_claim_rejected(configured):
    token = _sign(body_hash=hashlib.sha256(b"other").hexdigest())
    assert ph.verify_webhook_signature(_BODY, token) is False


def test_stale_iat_rejected(configured):
    token = _sign(iat=int(time.time()) - 600)   # 10 min old > 5 min window
    assert ph.verify_webhook_signature(_BODY, token) is False


def test_unknown_kid_rejected(configured):
    token = _sign(kid="unknown-kid")
    assert ph.verify_webhook_signature(_BODY, token) is False


def test_wrong_key_signature_rejected(configured):
    # Signed by a DIFFERENT private key but claiming our kid.
    other = ec.generate_private_key(ec.SECP256R1())
    other_pem = other.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    token = jwt.encode(
        {"iat": int(time.time()), "request_body_sha256": hashlib.sha256(_BODY).hexdigest()},
        other_pem, algorithm="ES256", headers={"kid": "test-kid"})
    assert ph.verify_webhook_signature(_BODY, token) is False


def test_non_es256_rejected(configured):
    # HS256 token (alg confusion attempt) must be rejected on the alg check.
    token = jwt.encode(
        {"iat": int(time.time()), "request_body_sha256": hashlib.sha256(_BODY).hexdigest()},
        "shared-secret-padded-to-32-bytes!!", algorithm="HS256", headers={"kid": "test-kid"})
    assert ph.verify_webhook_signature(_BODY, token) is False


def test_missing_header_rejected(configured):
    assert ph.verify_webhook_signature(_BODY, "") is False
    assert ph.verify_webhook_signature(_BODY, "not.a.jwt") is False


def test_expired_key_rejected(configured, monkeypatch):
    expired = dict(_PUBLIC_JWK); expired["expired_at"] = int(time.time())
    # _fetch_webhook_key returns None for expired keys — model that contract.
    monkeypatch.setattr(ph, "_fetch_webhook_key",
                        lambda kid: None if expired.get("expired_at") else expired)
    assert ph.verify_webhook_signature(_BODY, _sign()) is False


def test_unconfigured_local_bypass(monkeypatch):
    # ONLY when plaid isn't configured at all (credential-less tests).
    monkeypatch.setattr(ph, "plaid_configured", lambda: False)
    assert ph.verify_webhook_signature(_BODY, "anything") is True
    assert ph.verify_webhook_signature(_BODY, "") is False   # still needs a header
