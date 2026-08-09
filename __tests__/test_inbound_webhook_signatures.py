"""Inbound webhooks verify their sender — REAL signatures end-to-end.

Three endpoints used to accept unverified payloads when their signing
secret was unset: /email/inbound (Resend), /sms/inbound (Telnyx, which
had no verification at all) and /webhooks/twilio/sms. All three feed
untrusted text into Chief's system prompt, and Chief can send — so the
default is now to drop what cannot be verified.

These tests generate a real Ed25519 keypair and sign real Svix HMACs
rather than monkeypatching the verifiers, so a regression in the actual
signing maths fails here.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

ed = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")

import email_sender
import sms_service
import webhook_guard
from cryptography.hazmat.primitives import serialization


# ── Telnyx: a real Ed25519 keypair ───────────────────────────────────
_TELNYX_PRIVATE = ed.Ed25519PrivateKey.generate()
_TELNYX_PUBLIC_B64 = base64.b64encode(
    _TELNYX_PRIVATE.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
).decode()

_TELNYX_BODY = json.dumps(
    {"data": {"event_type": "message.received", "payload": {"text": "hi"}}}
).encode()


def _telnyx_headers(body: bytes = _TELNYX_BODY, *, ts: int | None = None,
                    sig: str | None = None) -> dict:
    ts = int(time.time()) if ts is None else ts
    if sig is None:
        signed = f"{ts}|".encode() + body
        sig = base64.b64encode(_TELNYX_PRIVATE.sign(signed)).decode()
    return {"telnyx-signature-ed25519": sig, "telnyx-timestamp": str(ts)}


# ── Resend/Svix: a real HMAC secret ──────────────────────────────────
_SVIX_KEY = b"0123456789abcdef0123456789abcdef"
_SVIX_SECRET = "whsec_" + base64.b64encode(_SVIX_KEY).decode()
_SVIX_BODY = json.dumps({"type": "email.received"}).encode()


def _svix_headers(body: bytes = _SVIX_BODY, *, ts: int | None = None,
                  sig: str | None = None, msg_id: str = "msg_1") -> dict:
    ts = int(time.time()) if ts is None else ts
    if sig is None:
        signed = f"{msg_id}.{ts}.".encode() + body
        digest = hmac.new(_SVIX_KEY, signed, hashlib.sha256).digest()
        sig = "v1," + base64.b64encode(digest).decode()
    return {"svix-id": msg_id, "svix-timestamp": str(ts), "svix-signature": sig}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No provider is on the unsigned allowlist unless a test says so."""
    monkeypatch.delenv("WEBHOOK_ALLOW_UNSIGNED", raising=False)
    monkeypatch.delenv("TELNYX_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)


# ── Telnyx ───────────────────────────────────────────────────────────

class TestTelnyxSignature:
    def test_valid_signature_accepted(self, monkeypatch):
        monkeypatch.setenv("TELNYX_PUBLIC_KEY", _TELNYX_PUBLIC_B64)
        assert sms_service._verify_telnyx_signature(_TELNYX_BODY, _telnyx_headers())

    def test_unset_public_key_now_rejects(self, monkeypatch):
        """The regression this PR exists for: no key used to mean no check."""
        assert not sms_service._verify_telnyx_signature(_TELNYX_BODY, _telnyx_headers())

    def test_tampered_body_rejected(self, monkeypatch):
        monkeypatch.setenv("TELNYX_PUBLIC_KEY", _TELNYX_PUBLIC_B64)
        headers = _telnyx_headers()
        assert not sms_service._verify_telnyx_signature(b'{"data":"forged"}', headers)

    def test_missing_headers_rejected(self, monkeypatch):
        monkeypatch.setenv("TELNYX_PUBLIC_KEY", _TELNYX_PUBLIC_B64)
        assert not sms_service._verify_telnyx_signature(_TELNYX_BODY, {})

    def test_stale_timestamp_rejected(self, monkeypatch):
        monkeypatch.setenv("TELNYX_PUBLIC_KEY", _TELNYX_PUBLIC_B64)
        old = int(time.time()) - 3600
        assert not sms_service._verify_telnyx_signature(
            _TELNYX_BODY, _telnyx_headers(ts=old))

    def test_malformed_timestamp_rejected(self, monkeypatch):
        monkeypatch.setenv("TELNYX_PUBLIC_KEY", _TELNYX_PUBLIC_B64)
        headers = _telnyx_headers()
        headers["telnyx-timestamp"] = "not-a-number"
        assert not sms_service._verify_telnyx_signature(_TELNYX_BODY, headers)

    def test_signature_from_a_different_key_rejected(self, monkeypatch):
        monkeypatch.setenv("TELNYX_PUBLIC_KEY", _TELNYX_PUBLIC_B64)
        other = ed.Ed25519PrivateKey.generate()
        ts = int(time.time())
        forged = base64.b64encode(
            other.sign(f"{ts}|".encode() + _TELNYX_BODY)).decode()
        assert not sms_service._verify_telnyx_signature(
            _TELNYX_BODY, _telnyx_headers(ts=ts, sig=forged))

    def test_explicit_allowlist_permits_unsigned(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", "telnyx")
        assert sms_service._verify_telnyx_signature(_TELNYX_BODY, {})

    def test_allowlist_is_per_provider(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", "resend")
        assert not sms_service._verify_telnyx_signature(_TELNYX_BODY, {})


# ── Resend ───────────────────────────────────────────────────────────

class TestResendSignature:
    def test_valid_signature_accepted(self, monkeypatch):
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", _SVIX_SECRET)
        assert email_sender._verify_resend_signature(_SVIX_BODY, _svix_headers())

    def test_unset_secret_now_rejects(self):
        """Was fail-OPEN by design; an inbound body reaches Chief's prompt."""
        assert not email_sender._verify_resend_signature(_SVIX_BODY, _svix_headers())

    def test_tampered_body_rejected(self, monkeypatch):
        monkeypatch.setenv("RESEND_WEBHOOK_SECRET", _SVIX_SECRET)
        assert not email_sender._verify_resend_signature(
            b'{"type":"forged"}', _svix_headers())

    def test_explicit_allowlist_permits_unsigned(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", "resend")
        assert email_sender._verify_resend_signature(_SVIX_BODY, {})


# ── Routed reply-to addresses are a query-injection surface ──────────

class TestRoutedAddressValidation:
    """`reply+{biz}+{contact}@domain` is chosen by the SENDER and both
    halves land in a PostgREST query string. Only the exact shape
    build_routed_reply_to emits — 8 hex chars, or "anon" — is accepted."""

    def _addr(self, local: str) -> str:
        return f"{local}@inbound.example.com"

    @pytest.fixture(autouse=True)
    def _domain(self, monkeypatch):
        monkeypatch.setenv("INBOUND_EMAIL_DOMAIN", "inbound.example.com")

    def test_wellformed_address_parses(self):
        got = email_sender._parse_routed_address(self._addr("reply+a1b2c3d4+e5f6a7b8"))
        assert got == {"biz_short": "a1b2c3d4", "contact_short": "e5f6a7b8"}

    def test_anon_contact_allowed(self):
        got = email_sender._parse_routed_address(self._addr("reply+a1b2c3d4+anon"))
        assert got["contact_short"] == "anon"

    def test_wildcard_business_rejected(self):
        """`reply+%+%@domain` made id=like.{biz}% match every business."""
        assert email_sender._parse_routed_address(self._addr("reply+%+%")) is None

    def test_wildcard_contact_rejected(self):
        assert email_sender._parse_routed_address(self._addr("reply+a1b2c3d4+%")) is None

    def test_query_param_injection_rejected(self):
        """An '&' in the token would append arbitrary PostgREST params."""
        assert email_sender._parse_routed_address(
            self._addr("reply+a1b2c3d4&limit=999+anon")) is None

    def test_non_hex_rejected(self):
        assert email_sender._parse_routed_address(self._addr("reply+zzzzzzzz+anon")) is None

    def test_wrong_length_rejected(self):
        assert email_sender._parse_routed_address(self._addr("reply+a1b2+anon")) is None

    def test_roundtrip_from_the_builder(self, monkeypatch):
        """Whatever build_routed_reply_to emits must survive the parser."""
        addr = email_sender.build_routed_reply_to(
            "a1b2c3d4-1111-2222-3333-444455556666",
            "e5f6a7b8-9999-8888-7777-666655554444")
        got = email_sender._parse_routed_address(addr)
        assert got == {"biz_short": "a1b2c3d4", "contact_short": "e5f6a7b8"}

    def test_roundtrip_with_no_contact(self, monkeypatch):
        addr = email_sender.build_routed_reply_to(
            "a1b2c3d4-1111-2222-3333-444455556666", None)
        assert email_sender._parse_routed_address(addr)["contact_short"] == "anon"


# ── The guard itself ─────────────────────────────────────────────────

class TestWebhookGuard:
    def test_default_is_closed(self):
        assert not webhook_guard.unsigned_allowed("resend")

    def test_all_opens_everything(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", "all")
        assert webhook_guard.unsigned_allowed("resend")
        assert webhook_guard.unsigned_allowed("telnyx")
        assert webhook_guard.unsigned_allowed("twilio")

    def test_comma_list_and_whitespace(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", " resend , telnyx ")
        assert webhook_guard.unsigned_allowed("resend")
        assert webhook_guard.unsigned_allowed("telnyx")
        assert not webhook_guard.unsigned_allowed("twilio")

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", "TELNYX")
        assert webhook_guard.unsigned_allowed("telnyx")

    def test_empty_string_is_closed(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_ALLOW_UNSIGNED", "   ")
        assert not webhook_guard.unsigned_allowed("resend")
