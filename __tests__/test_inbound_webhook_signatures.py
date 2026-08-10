"""Inbound webhooks verify their sender — REAL signatures end-to-end.

Three endpoints used to accept unverified payloads when their signing
secret was unset: /email/inbound (Resend), /sms/inbound (Telnyx, which
had no verification at all) and /webhooks/twilio/sms. All three feed
untrusted text into Chief's system prompt, and Chief can send — so the
default is now to drop what cannot be verified.

Two remain. Telnyx's endpoint was deleted with the provider rather than
kept and guarded; TestTelnyxIsRetired pins that it stays deleted.

These tests sign real Svix HMACs rather than monkeypatching the
verifiers, so a regression in the actual signing maths fails here.
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

# The cryptography importorskip that used to guard this module went with
# the Telnyx Ed25519 keypair. Svix HMACs need only hashlib/hmac, so these
# tests now run everywhere instead of skipping where it is absent.

import email_sender
import sms_service
import webhook_guard


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


# ── Telnyx is gone ───────────────────────────────────────────────────

class TestTelnyxIsRetired:
    """The Ed25519 verifier these tests used to exercise was added by
    this same audit and deleted three days later, with the provider.

    That is not a reversal. Signing /sms/inbound was correct while the
    endpoint was reachable and unverified; once Twilio was the only
    sender, the endpoint was an unused door into Chief's prompt, and
    removing a door beats fitting it with a better lock. What is worth
    pinning is that it does not quietly come back -- a re-added Telnyx
    fallback would be unreachable, unsigned by default, and invisible.
    """

    def test_the_verifier_is_gone(self):
        assert not hasattr(sms_service, "_verify_telnyx_signature")

    def test_the_send_path_is_gone(self):
        assert not hasattr(sms_service, "_send_via_telnyx")

    def test_no_inbound_route_survives(self):
        paths = [getattr(r, "path", "") for r in sms_service.router.routes]
        assert "/sms/inbound" not in paths

    def test_twilio_still_owns_inbound(self):
        """Guards the guard: the assertions above would also pass if SMS
        had simply stopped receiving anything at all."""
        import twilio_sms
        paths = [getattr(r, "path", "") for r in twilio_sms.router.routes]
        assert "/webhooks/twilio/sms" in paths
        assert "/webhooks/twilio/status" in paths


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
