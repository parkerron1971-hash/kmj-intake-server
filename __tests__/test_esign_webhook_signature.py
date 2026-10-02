"""Proving the delivery came from DocuSeal.

THE BUG THIS FILE EXISTS FOR. The first cut of the webhook (adapter #1,
BoldSign) checked `payload["secret"]` against the configured env var.
No e-sign provider puts a secret in the body — they sign the request
with an HMAC header. So setting the env var, which looks exactly like
hardening, would have rejected every genuine delivery and left
signatures silently not arriving. Nothing failed loudly; the webhook
would simply never have worked, and the manual Check status button would
have hidden it.

That is the silent-conditional-drop shape: a guard whose condition can
never be true. `test_a_real_delivery_carries_no_secret_field` is the one
that would have caught it, and it is written to keep catching it.

WHY IT MATTERS AGAIN AT THE PROVIDER SWAP. DocuSeal secures a webhook
two mutually exclusive ways: the HMAC below, and a custom header whose
value is the raw secret. A verifier that understood only one of them
would reject every delivery from a practitioner who configured the
other — the identical bug, arriving from the opposite direction. Both
are accepted, and both are pinned here.

THE SIGNATURE IS THE FIRST CHECK, NOT THE ONLY ONE. Even a perfectly
forged delivery cannot mark a document signed, because the handler
re-reads the real status from DocuSeal (see test_esign_webhook.py).
These tests cover the first door; that file covers the second.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import docuseal_router as dr


SECRET = "whsec_test_key"
BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "owner_id": "owner-1"}
SUBMISSION_ID = "4021"


def _doc(status="sent"):
    return {
        "id": "row-1", "business_id": "biz-1", "document_id": SUBMISSION_ID,
        "title": "Revenue Share Agreement", "signer_name": "Aunt",
        "signer_email": "aunt@example.com", "status": status,
    }


class FakeRequest:
    """Only what the handler touches: raw bytes and headers."""
    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


def sign(body: bytes, secret: str = SECRET, ts: int | None = None) -> str:
    """Build a header the way DocuSeal builds it: '<t>.<hex hmac>' over
    the literal string '{t}.{raw body}'."""
    ts = ts if ts is not None else int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body,
                   hashlib.sha256).hexdigest()
    return f"{ts}.{mac}"


# A real DocuSeal delivery shape. Note what is NOT in it: any "secret".
REAL_BODY = json.dumps({
    "event_type": "form.completed",
    "timestamp": "2026-08-30T12:00:00Z",
    "data": {
        "id": 77,
        "email": "aunt@example.com",
        "status": "completed",
        "submission": {"id": int(SUBMISSION_ID), "status": "completed"},
    },
}).encode()


@pytest.fixture
def wired(monkeypatch):
    """Handler reaches a real document and DocuSeal confirms completion."""
    def _get(path):
        if path.startswith("/esign_documents"):
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(dr.sb_clients, "sb_patch_as_service", lambda *a, **k: None)

    async def _completed(document_id):
        return "completed"
    monkeypatch.setattr(dr, "_live_status", _completed)

    async def _no_emails(biz, doc):
        return None
    monkeypatch.setattr(dr, "_send_completion_emails", _no_emails)

    import event_spine, audit_log
    monkeypatch.setattr(event_spine, "emit", lambda *a, **k: None)
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: None)


# ── The regression ───────────────────────────────────────────────────

def test_a_real_delivery_carries_no_secret_field(wired, monkeypatch):
    """THE LOAD-BEARING TEST.

    A genuine, correctly-signed DocuSeal delivery with the secret
    configured. The body contains no "secret" key, because DocuSeal
    never sends one. This must be accepted.

    Against adapter #1's first implementation — which compared
    payload["secret"] to the env var — this returned ignored=auth and
    every real signature was dropped on the floor."""
    monkeypatch.setenv("DOCUSEAL_WEBHOOK_SECRET", SECRET)
    assert b"secret" not in REAL_BODY

    req = FakeRequest(REAL_BODY, {"X-Docuseal-Signature": sign(REAL_BODY)})
    out = asyncio.run(dr.esign_webhook(req))

    assert out.get("ignored") is None, f"genuine delivery rejected: {out}"
    assert out["changed"] is True
    assert out["status"] == "completed"


def test_the_handler_reads_docuseals_header_name(wired, monkeypatch):
    """A correct HMAC under the WRONG header name proves nothing. Pinned
    because the port changed the name from X-BoldSign-Signature, and a
    stale constant here would reject every delivery while every unit
    test that passes the header explicitly still passed."""
    assert dr.SIGNATURE_HEADER == "X-Docuseal-Signature"

    monkeypatch.setenv("DOCUSEAL_WEBHOOK_SECRET", SECRET)
    out = asyncio.run(dr.esign_webhook(
        FakeRequest(REAL_BODY, {"X-BoldSign-Signature": sign(REAL_BODY)})))
    assert out["ignored"] == "bad_signature"


# ── Signature verification ───────────────────────────────────────────

def test_bad_signature_is_rejected(wired, monkeypatch):
    monkeypatch.setenv("DOCUSEAL_WEBHOOK_SECRET", SECRET)
    req = FakeRequest(REAL_BODY, {"X-Docuseal-Signature": sign(REAL_BODY, "wrong-key")})
    out = asyncio.run(dr.esign_webhook(req))
    assert out["ignored"] == "bad_signature"


def test_missing_header_is_rejected_when_secret_is_set(wired, monkeypatch):
    monkeypatch.setenv("DOCUSEAL_WEBHOOK_SECRET", SECRET)
    out = asyncio.run(dr.esign_webhook(FakeRequest(REAL_BODY, {})))
    assert out["ignored"] == "bad_signature"


def test_the_shared_secret_form_is_accepted(wired, monkeypatch):
    """DocuSeal's OTHER documented mode: a header carrying the raw
    secret rather than an HMAC. A practitioner who configures this one
    must not find that signatures silently never arrive."""
    monkeypatch.setenv("DOCUSEAL_WEBHOOK_SECRET", SECRET)
    out = asyncio.run(dr.esign_webhook(
        FakeRequest(REAL_BODY, {"X-Docuseal-Signature": SECRET})))
    assert out.get("ignored") is None
    assert out["changed"] is True


def test_a_shared_secret_containing_a_dot_still_matches():
    """The parser splits on '.', so a dotted secret compared against the
    parsed half could never match — the same can-never-be-true guard
    this file exists to prevent, one layer down. Compared against the
    whole header instead."""
    dotted = "whsec_v1.abc.def"
    assert dr.verify_webhook_signature(b"{}", dotted, dotted) is True
    assert dr.verify_webhook_signature(b"{}", "whsec_v1.abc.WRONG", dotted) is False


def test_body_is_verified_byte_for_byte(monkeypatch):
    """The signature covers the RAW bytes. Re-serialising the parsed
    JSON reorders keys and changes spacing, and the HMAC stops matching
    — which is why the handler reads bytes rather than taking a dict."""
    reserialised = json.dumps(json.loads(REAL_BODY), indent=2).encode()
    assert reserialised != REAL_BODY
    header = sign(REAL_BODY)

    assert dr.verify_webhook_signature(REAL_BODY, header, SECRET) is True
    assert dr.verify_webhook_signature(reserialised, header, SECRET) is False


def test_unset_secret_lets_deliveries_through(wired, monkeypatch):
    """Signatures must work before anyone finds the dashboard page. The
    second check — re-reading status from DocuSeal — is what makes this
    safe, not the secret."""
    monkeypatch.delenv("DOCUSEAL_WEBHOOK_SECRET", raising=False)
    out = asyncio.run(dr.esign_webhook(FakeRequest(REAL_BODY, {})))
    assert out.get("ignored") is None
    assert out["changed"] is True


def test_stale_timestamp_is_logged_not_rejected(wired, monkeypatch):
    """A deliberate departure from the documented advice.

    Replay is already inert here: the handler re-reads the real status
    and _apply_status is idempotent, so a replayed 'form.completed'
    either re-applies what the row already says or is contradicted by
    the provider. Rejecting on age would buy nothing and would drop a
    legitimate late retry — the failure that actually costs someone a
    confirmation email."""
    monkeypatch.setenv("DOCUSEAL_WEBHOOK_SECRET", SECRET)
    old_ts = int(time.time()) - 3600
    header = sign(REAL_BODY, ts=old_ts)

    out = asyncio.run(dr.esign_webhook(FakeRequest(REAL_BODY, {"X-Docuseal-Signature": header})))
    assert out.get("ignored") is None
    assert out["changed"] is True


# ── Header parsing ───────────────────────────────────────────────────

@pytest.mark.parametrize("header", [
    "", "garbage", "1.", ".", "notanumber.abc", "1.deadbeef", ".abc",
])
def test_malformed_headers_never_crash(header):
    """A parser that raises on a malformed header turns a bad request
    into a 500, and a 500 is what gets a webhook disabled."""
    assert dr.verify_webhook_signature(b"{}", header, SECRET) is False


def test_parser_reads_the_documented_format():
    ts, sig = dr._parse_signature_header("1668693823.aaabbb")
    assert ts == "1668693823"
    assert sig == "aaabbb"


def test_parser_reports_the_shared_secret_form_as_untimestamped():
    ts, sig = dr._parse_signature_header("whsec_plain")
    assert ts is None
    assert sig == "whsec_plain"


def test_timestamp_age_survives_the_untimestamped_form():
    """_timestamp_age runs on every signed delivery. A shared-secret
    header has no timestamp, and that must read as 'unknown age', not
    raise inside the handler."""
    assert dr._timestamp_age("whsec_plain") is None
    assert dr._timestamp_age("") is None
    assert dr._timestamp_age(f"{int(time.time()) - 10}.abc") >= 10


def test_non_json_body_is_ignored_not_crashed(wired, monkeypatch):
    monkeypatch.delenv("DOCUSEAL_WEBHOOK_SECRET", raising=False)
    out = asyncio.run(dr.esign_webhook(FakeRequest(b"<html>nope</html>", {})))
    assert out["ok"] is True
    assert out["ignored"] == "bad_json"


def test_submission_id_is_read_from_the_signed_body(wired, monkeypatch):
    """The shape DocuSeal actually sends nests the submission under
    data. Missing it means the webhook silently does nothing forever,
    which looks exactly like no webhook at all."""
    monkeypatch.delenv("DOCUSEAL_WEBHOOK_SECRET", raising=False)
    seen = {}

    def _get(path):
        if path.startswith("/esign_documents"):
            seen["path"] = path
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", _get)

    asyncio.run(dr.esign_webhook(FakeRequest(REAL_BODY, {})))
    assert f"eq.{SUBMISSION_ID}" in seen["path"]
