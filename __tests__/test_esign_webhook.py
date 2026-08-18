"""A signature nobody notices is a signature that did not happen.

Refresh only tells the truth while somebody is looking at the panel. A
document signed on a Sunday sat invisible until the next visit, and the
confirmation email that hangs off completion never went at all. The
webhook makes completion something that happens TO the system.

THE PAYLOAD IS NOT EVIDENCE. BoldSign's POST names a document id and
nothing else is read from it — the id is looked up in our own table and
the real status is fetched from the provider. So a forged webhook cannot
mark anything signed; the worst it does is make us re-poll a document we
already own. These tests pin that property, because the day it quietly
stops holding is the day an unauthenticated endpoint starts writing
completions.

They also pin idempotency. Every provider eventually delivers the same
webhook twice, and a second delivery must not emit contract_signed
twice, write a second audit row, or send the confirmation emails again.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import boldsign_router as br


# ── Fixtures ─────────────────────────────────────────────────────────

BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "owner_id": "owner-1"}

def _doc(status="sent"):
    return {
        "id": "row-1",
        "business_id": "biz-1",
        "document_id": "bs-doc-1",
        "title": "Revenue Share Agreement",
        "signer_name": "Aunt",
        "signer_email": "aunt@example.com",
        "status": status,
    }


class _Spy:
    """Records every side effect a completion is supposed to have."""
    def __init__(self):
        self.patched = []
        self.emitted = []
        self.audited = []
        self.emails = []


@pytest.fixture
def spy(monkeypatch):
    s = _Spy()

    monkeypatch.setattr(br.sb_clients, "sb_patch_as_service",
                        lambda path, body: s.patched.append((path, body)))

    import event_spine
    monkeypatch.setattr(event_spine, "emit",
                        lambda et, biz, payload, source=None: s.emitted.append(et))

    import audit_log
    monkeypatch.setattr(audit_log, "record",
                        lambda *a, **k: s.audited.append(k.get("verb")))

    async def _fake_emails(biz, doc):
        s.emails.append(doc["document_id"])
    monkeypatch.setattr(br, "_send_completion_emails", _fake_emails)

    return s


# ── The completion path ──────────────────────────────────────────────

def test_completion_fires_every_side_effect(spy):
    """Status, spine event, audit row, emails — all four or none."""
    out = asyncio.run(br._apply_status(_doc(), BIZ, "completed"))

    assert out["changed"] is True
    assert out["status"] == "completed"
    assert spy.emitted == ["contract_signed"]
    assert spy.audited == ["esign_completed"]
    assert spy.emails == ["bs-doc-1"]
    # completed_at is written, not left for a later pass to guess at.
    assert spy.patched[0][1]["completed_at"]


def test_redelivery_is_a_no_op(spy):
    """The second webhook for the same signature must cost nothing.

    Not 'mostly nothing' — no second event, no second audit row, and
    above all no second pair of emails landing on the signer."""
    already = _doc(status="completed")
    out = asyncio.run(br._apply_status(already, BIZ, "completed"))

    assert out["changed"] is False
    assert spy.emitted == []
    assert spy.audited == []
    assert spy.emails == []
    assert spy.patched == []


def test_non_completion_status_does_not_email(spy):
    """A decline is a status change, not a completion. It must not send
    a 'signed' confirmation with an executed copy that doesn't exist."""
    out = asyncio.run(br._apply_status(_doc(), BIZ, "declined"))

    assert out["changed"] is True
    assert spy.emitted == []
    assert spy.emails == []
    assert spy.patched[0][1]["status"] == "declined"
    assert "completed_at" not in spy.patched[0][1]


# ── The webhook cannot be used to forge a completion ─────────────────

def test_webhook_ignores_unknown_document(spy, monkeypatch):
    """A payload naming a document we never sent is logged and dropped —
    never inserted, never acted on."""
    monkeypatch.setattr(br.sb_clients, "sb_get_as_service", lambda path: [])

    out = asyncio.run(br.esign_webhook({"documentId": "not-ours"}))

    assert out["ok"] is True
    assert out["ignored"] == "unknown_document"
    assert spy.emitted == []
    assert spy.emails == []


def test_webhook_does_not_believe_the_payload(spy, monkeypatch):
    """THE LOAD-BEARING TEST.

    The payload screams 'completed'. The provider says the document is
    still out for signature. The provider wins — nothing is marked
    signed, nobody is emailed.

    If this ever fails, an unauthenticated POST can mark any document
    signed and mail an 'executed copy' to a counterparty."""
    def _get(path):
        if path.startswith("/esign_documents"):
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(br.sb_clients, "sb_get_as_service", _get)

    async def _still_out(document_id):
        return "sent"
    monkeypatch.setattr(br, "_live_status", _still_out)

    out = asyncio.run(br.esign_webhook({
        "documentId": "bs-doc-1",
        "status": "completed",          # the lie
        "data": {"status": "completed"},
    }))

    assert out["changed"] is False
    assert spy.emitted == []
    assert spy.emails == []


def test_webhook_applies_the_providers_truth(spy, monkeypatch):
    """The honest path: provider confirms completion, everything fires."""
    def _get(path):
        if path.startswith("/esign_documents"):
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(br.sb_clients, "sb_get_as_service", _get)

    async def _completed(document_id):
        return "completed"
    monkeypatch.setattr(br, "_live_status", _completed)

    out = asyncio.run(br.esign_webhook({"documentId": "bs-doc-1"}))

    assert out["changed"] is True
    assert out["status"] == "completed"
    assert spy.emitted == ["contract_signed"]
    assert spy.emails == ["bs-doc-1"]


def test_webhook_reads_the_nested_id_shape(spy, monkeypatch):
    """BoldSign nests the id differently across event shapes. Missing it
    means the webhook silently does nothing forever — which looks
    exactly like no webhook at all."""
    seen = {}
    def _get(path):
        if path.startswith("/esign_documents"):
            seen["path"] = path
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(br.sb_clients, "sb_get_as_service", _get)

    async def _completed(document_id):
        return "completed"
    monkeypatch.setattr(br, "_live_status", _completed)

    asyncio.run(br.esign_webhook({"data": {"documentId": "bs-doc-1"}}))
    assert "bs-doc-1" in seen["path"]


def test_webhook_always_returns_200(spy, monkeypatch):
    """A webhook that errors gets retried, then throttled, then disabled
    by the provider. Every branch returns ok."""
    monkeypatch.setattr(br.sb_clients, "sb_get_as_service", lambda path: [])

    for payload in ({}, {"documentId": ""}, {"data": {}}, {"documentId": "x"}):
        out = asyncio.run(br.esign_webhook(payload))
        assert out["ok"] is True


def test_secret_filters_noise_when_configured(spy, monkeypatch):
    """The secret is a noise filter, not the security boundary — but
    when it is set, a mismatch is dropped before any lookup."""
    monkeypatch.setenv("BOLDSIGN_WEBHOOK_SECRET", "s3cret")
    called = {"n": 0}
    def _get(path):
        called["n"] += 1
        return []
    monkeypatch.setattr(br.sb_clients, "sb_get_as_service", _get)

    out = asyncio.run(br.esign_webhook({"documentId": "bs-doc-1", "secret": "wrong"}))

    assert out["ignored"] == "auth"
    assert called["n"] == 0


# ── Who gets emailed ─────────────────────────────────────────────────

def test_signer_who_is_also_the_owner_gets_one_email(monkeypatch):
    """Kevin signing his own paperwork must not receive the same
    confirmation twice."""
    sent = []

    async def _fake_send(**kw):
        sent.append(kw["to_email"])
    async def _no_pdf(document_id):
        return None
    async def _owner(owner_id):
        return "kevin@example.com"

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", _fake_send)
    monkeypatch.setattr(br, "_signed_pdf_b64", _no_pdf)
    monkeypatch.setattr(br, "_owner_email", _owner)

    doc = _doc()
    doc["signer_email"] = "KEVIN@example.com"     # same person, different case
    asyncio.run(br._send_completion_emails(BIZ, doc))

    assert sent == ["kevin@example.com"]


def test_both_parties_are_emailed(monkeypatch):
    sent = []

    async def _fake_send(**kw):
        sent.append(kw["to_email"])
    async def _no_pdf(document_id):
        return None
    async def _owner(owner_id):
        return "kevin@example.com"

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", _fake_send)
    monkeypatch.setattr(br, "_signed_pdf_b64", _no_pdf)
    monkeypatch.setattr(br, "_owner_email", _owner)

    asyncio.run(br._send_completion_emails(BIZ, _doc()))

    assert sent == ["kevin@example.com", "aunt@example.com"]


def test_a_dead_email_provider_does_not_break_a_signature(monkeypatch):
    """The signature already happened and is already recorded. Resend
    having a bad afternoon must never surface as a failed webhook."""
    async def _boom(**kw):
        raise RuntimeError("resend is down")
    async def _no_pdf(document_id):
        return None
    async def _owner(owner_id):
        return "kevin@example.com"

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", _boom)
    monkeypatch.setattr(br, "_signed_pdf_b64", _no_pdf)
    monkeypatch.setattr(br, "_owner_email", _owner)

    asyncio.run(br._send_completion_emails(BIZ, _doc()))   # must not raise
