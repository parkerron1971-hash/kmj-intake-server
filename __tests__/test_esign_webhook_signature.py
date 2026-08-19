"""Proving the delivery came from BoldSign.

THE BUG THIS FILE EXISTS FOR. The first cut of the webhook checked
`payload["secret"]` against BOLDSIGN_WEBHOOK_SECRET. BoldSign does not
put a secret in the body — it signs the request with an
X-BoldSign-Signature HMAC header. So setting the env var, which looks
exactly like hardening, would have rejected every genuine delivery and
left signatures silently not arriving. Nothing failed loudly; the
webhook would simply never have worked, and the manual Check status
button would have hidden it.

That is the silent-conditional-drop shape: a guard whose condition can
never be true. `test_a_real_delivery_carries_no_secret_field` is the one
that would have caught it, and it is written to keep catching it.

THE SIGNATURE IS THE FIRST CHECK, NOT THE ONLY ONE. Even a perfectly
forged delivery cannot mark a document signed, because the handler
re-reads the real status from BoldSign (see test_esign_webhook.py).
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

import boldsign_router as br


SECRET = "whsec_test_key"
BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "owner_id": "owner-1"}


def _doc(status="sent"):
    return {
        "id": "row-1", "business_id": "biz-1", "document_id": "bs-doc-1",
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


def sign(body: bytes, secret: str = SECRET, ts: int | None = None,
         extra: str = "") -> str:
    """Build a header the way BoldSign builds it."""
    ts = ts if ts is not None else int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body,
                   hashlib.sha256).hexdigest()
    return f"t={ts}, s0={mac}{extra}"


# A real BoldSign delivery shape. Note what is NOT in it: any "secret".
REAL_BODY = json.dumps({
    "event": {"id": "ca7bf729", "created": 1668693823,
              "eventType": "Signed", "environment": "Live"},
    "document": {"documentId": "bs-doc-1", "status": "Completed"},
}).encode()


@pytest.fixture
def wired(monkeypatch):
    """Handler reaches a real document and BoldSign confirms completion."""
    def _get(path):
        if path.startswith("/esign_documents"):
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(br.sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(br.sb_clients, "sb_patch_as_service", lambda *a, **k: None)

    async def _completed(document_id):
        return "completed"
    monkeypatch.setattr(br, "_live_status", _completed)

    async def _no_emails(biz, doc):
        return None
    monkeypatch.setattr(br, "_send_completion_emails", _no_emails)

    import event_spine, audit_log
    monkeypatch.setattr(event_spine, "emit", lambda *a, **k: None)
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: None)


# ── The regression ───────────────────────────────────────────────────

def test_a_real_delivery_carries_no_secret_field(wired, monkeypatch):
    """THE LOAD-BEARING TEST.

    A genuine, correctly-signed BoldSign delivery with the secret
    configured. The body contains no "secret" key, because BoldSign
    never sends one. This must be accepted.

    Against the first implementation — which compared
    payload["secret"] to the env var — this returned ignored=auth and
    every real signature was dropped on the floor."""
    monkeypatch.setenv("BOLDSIGN_WEBHOOK_SECRET", SECRET)
    assert b"secret" not in REAL_BODY

    req = FakeRequest(REAL_BODY, {"X-BoldSign-Signature": sign(REAL_BODY)})
    out = asyncio.run(br.esign_webhook(req))

    assert out.get("ignored") is None, f"genuine delivery rejected: {out}"
    assert out["changed"] is True
    assert out["status"] == "completed"


# ── Signature verification ───────────────────────────────────────────

def test_bad_signature_is_rejected(wired, monkeypatch):
    monkeypatch.setenv("BOLDSIGN_WEBHOOK_SECRET", SECRET)
    req = FakeRequest(REAL_BODY, {"X-BoldSign-Signature": sign(REAL_BODY, "wrong-key")})
    out = asyncio.run(br.esign_webhook(req))
    assert out["ignored"] == "bad_signature"


def test_missing_header_is_rejected_when_secret_is_set(wired, monkeypatch):
    monkeypatch.setenv("BOLDSIGN_WEBHOOK_SECRET", SECRET)
    out = asyncio.run(br.esign_webhook(FakeRequest(REAL_BODY, {})))
    assert out["ignored"] == "bad_signature"


def test_rotated_key_still_verifies(wired, monkeypatch):
    """While a secret is being rolled BoldSign sends both. Matching
    EITHER is a pass, or every delivery fails during the rotation."""
    monkeypatch.setenv("BOLDSIGN_WEBHOOK_SECRET", SECRET)
    ts = int(time.time())
    old = hmac.new(SECRET.encode(), f"{ts}.".encode() + REAL_BODY,
                   hashlib.sha256).hexdigest()
    header = f"t={ts}, s0=deadbeef, s1={old}"

    out = asyncio.run(br.esign_webhook(FakeRequest(REAL_BODY, {"X-BoldSign-Signature": header})))
    assert out.get("ignored") is None
    assert out["changed"] is True


def test_body_is_verified_byte_for_byte(monkeypatch):
    """The signature covers the RAW bytes. Re-serialising the parsed
    JSON reorders keys and changes spacing, and the HMAC stops matching
    — which is why the handler reads bytes rather than taking a dict."""
    reserialised = json.dumps(json.loads(REAL_BODY), indent=2).encode()
    assert reserialised != REAL_BODY
    header = sign(REAL_BODY)

    assert br.verify_webhook_signature(REAL_BODY, header, SECRET) is True
    assert br.verify_webhook_signature(reserialised, header, SECRET) is False


def test_unset_secret_lets_deliveries_through(wired, monkeypatch):
    """Signatures must work before anyone finds the dashboard page. The
    second check — re-reading status from BoldSign — is what makes this
    safe, not the secret."""
    monkeypatch.delenv("BOLDSIGN_WEBHOOK_SECRET", raising=False)
    out = asyncio.run(br.esign_webhook(FakeRequest(REAL_BODY, {})))
    assert out.get("ignored") is None
    assert out["changed"] is True


def test_stale_timestamp_is_logged_not_rejected(wired, monkeypatch):
    """A deliberate departure from the documented advice.

    Replay is already inert here: the handler re-reads the real status
    and _apply_status is idempotent, so a replayed 'Signed' either
    re-applies what the row already says or is contradicted by the
    provider. Rejecting on age would buy nothing and would drop a
    legitimate late retry — the failure that actually costs someone a
    confirmation email."""
    monkeypatch.setenv("BOLDSIGN_WEBHOOK_SECRET", SECRET)
    old_ts = int(time.time()) - 3600
    header = sign(REAL_BODY, ts=old_ts)

    out = asyncio.run(br.esign_webhook(FakeRequest(REAL_BODY, {"X-BoldSign-Signature": header})))
    assert out.get("ignored") is None
    assert out["changed"] is True


# ── Header parsing ───────────────────────────────────────────────────

@pytest.mark.parametrize("header", [
    "", "garbage", "t=", "s0=abc", "t=notanumber, s0=abc", "t=1, s0=",
])
def test_malformed_headers_never_crash(header):
    """A parser that raises on a malformed header turns a bad request
    into a 500, and a 500 is what gets a webhook disabled."""
    assert br.verify_webhook_signature(b"{}", header, SECRET) is False


def test_parser_reads_the_documented_format():
    ts, sigs = br._parse_signature_header("t=1668693823, s0=aaa, s1=bbb")
    assert ts == "1668693823"
    assert sigs == ["aaa", "bbb"]


def test_non_json_body_is_ignored_not_crashed(wired, monkeypatch):
    monkeypatch.delenv("BOLDSIGN_WEBHOOK_SECRET", raising=False)
    out = asyncio.run(br.esign_webhook(FakeRequest(b"<html>nope</html>", {})))
    assert out["ok"] is True
    assert out["ignored"] == "bad_json"


def test_document_id_read_from_the_document_block(wired, monkeypatch):
    """The shape BoldSign actually sends nests the id under "document".
    Missing it means the webhook silently does nothing forever, which
    looks exactly like no webhook at all."""
    monkeypatch.delenv("BOLDSIGN_WEBHOOK_SECRET", raising=False)
    seen = {}

    def _get(path):
        if path.startswith("/esign_documents"):
            seen["path"] = path
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(br.sb_clients, "sb_get_as_service", _get)

    asyncio.run(br.esign_webhook(FakeRequest(REAL_BODY, {})))
    assert "bs-doc-1" in seen["path"]
