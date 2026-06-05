"""Phase D.4 PR 1 — Stripe Connect helper tests.

Focused on the security-critical paths:
  - verify_webhook_signature must accept genuine signatures, reject
    forged ones, reject stale timestamps, reject malformed headers
  - is_live_mode must derive cleanly from sk_test_/sk_live_ prefixes
  - oauth_url must include client_id + state + scope correctly
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sys, pathlib
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


# Stub env vars BEFORE import so module-level constants work.
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_CONNECT_CLIENT_ID", "ca_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_secret_value")

from stripe_connect_helpers import (  # noqa: E402
    is_live_mode,
    oauth_url,
    verify_webhook_signature,
)


# ─── is_live_mode ────────────────────────────────────────────────────


def test_is_live_mode_test_key_returns_false(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abc")
    assert is_live_mode() is False


def test_is_live_mode_live_key_returns_true(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_abc")
    assert is_live_mode() is True


def test_is_live_mode_missing_returns_false(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    assert is_live_mode() is False


# ─── oauth_url ───────────────────────────────────────────────────────


def test_oauth_url_includes_client_id():
    url = oauth_url(state="abc123")
    assert "client_id=ca_dummy" in url


def test_oauth_url_includes_state():
    url = oauth_url(state="abc123")
    assert "state=abc123" in url


def test_oauth_url_includes_read_write_scope():
    url = oauth_url(state="abc123")
    assert "scope=read_write" in url


def test_oauth_url_omits_redirect_uri_when_none():
    url = oauth_url(state="abc123", return_url=None)
    assert "redirect_uri" not in url


def test_oauth_url_includes_redirect_uri_when_set():
    url = oauth_url(state="abc123", return_url="https://app.example.com/return")
    assert "redirect_uri=https" in url


# ─── verify_webhook_signature ────────────────────────────────────────


SECRET = "whsec_test_secret_value"


def _sign(payload: bytes, t: int, secret: str = SECRET) -> str:
    """Build a Stripe-style signature header for the given payload."""
    signed = f"{t}.".encode("utf-8") + payload
    mac = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def test_verify_accepts_genuine_signature():
    payload = b'{"id":"evt_1","type":"account.updated"}'
    now = int(time.time())
    sig = _sign(payload, now)
    assert verify_webhook_signature(payload, sig, secret=SECRET) is True


def test_verify_rejects_forged_signature():
    payload = b'{"id":"evt_1","type":"account.updated"}'
    now = int(time.time())
    # Use a different secret on attacker side
    forged = _sign(payload, now, secret="wrong_secret")
    assert verify_webhook_signature(payload, forged, secret=SECRET) is False


def test_verify_rejects_stale_timestamp():
    payload = b'{"id":"evt_1"}'
    stale = int(time.time()) - 10_000  # ~3h old, far past 5min tolerance
    sig = _sign(payload, stale)
    assert verify_webhook_signature(payload, sig, secret=SECRET) is False


def test_verify_rejects_future_timestamp_beyond_tolerance():
    payload = b'{"id":"evt_1"}'
    future = int(time.time()) + 10_000
    sig = _sign(payload, future)
    assert verify_webhook_signature(payload, sig, secret=SECRET) is False


def test_verify_rejects_missing_t():
    payload = b'{"id":"evt_1"}'
    # Header has v1 but no t — should not authenticate.
    assert verify_webhook_signature(
        payload,
        sig_header="v1=deadbeef",
        secret=SECRET,
    ) is False


def test_verify_rejects_missing_v1():
    payload = b'{"id":"evt_1"}'
    now = int(time.time())
    assert verify_webhook_signature(
        payload,
        sig_header=f"t={now}",
        secret=SECRET,
    ) is False


def test_verify_rejects_malformed_header():
    payload = b'{"id":"evt_1"}'
    assert verify_webhook_signature(
        payload,
        sig_header="not a valid header",
        secret=SECRET,
    ) is False


def test_verify_rejects_empty_payload():
    now = int(time.time())
    sig = _sign(b'{}', now)
    assert verify_webhook_signature(b"", sig, secret=SECRET) is False


def test_verify_rejects_when_secret_missing(monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    payload = b'{"id":"evt_1"}'
    now = int(time.time())
    sig = _sign(payload, now)
    # No secret kwarg + no env var → can't verify → False
    assert verify_webhook_signature(payload, sig) is False


def test_verify_payload_tamper_resistance():
    """Changing the payload AFTER signing must invalidate the signature."""
    original = b'{"id":"evt_1","amount":100}'
    tampered = b'{"id":"evt_1","amount":999}'
    now = int(time.time())
    sig = _sign(original, now)
    assert verify_webhook_signature(tampered, sig, secret=SECRET) is False
    # And the original still verifies — sanity.
    assert verify_webhook_signature(original, sig, secret=SECRET) is True
