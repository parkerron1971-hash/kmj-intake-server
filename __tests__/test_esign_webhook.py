"""A signature nobody notices is a signature that did not happen.

Refresh only tells the truth while somebody is looking at the panel. A
document signed on a Sunday sat invisible until the next visit, and the
confirmation email that hangs off completion never went at all. The
webhook makes completion something that happens TO the system.

THE PAYLOAD IS NOT EVIDENCE. DocuSeal's POST names a submission id and
nothing else is read from it — the id is looked up in our own table and
the real status is fetched from the provider. So a forged webhook cannot
mark anything signed; the worst it does is make us re-poll a document we
already own. These tests pin that property, because the day it quietly
stops holding is the day an unauthenticated endpoint starts writing
completions.

They also pin idempotency. Every provider eventually delivers the same
webhook twice, and a second delivery must not emit contract_signed
twice, write a second audit row, or send the confirmation emails again.

AND THEY PIN WHICH ID WE READ. That is new with adapter #2 and it is the
nastiest thing in the file — see the two id-family tests below.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import docuseal_router as dr


class _Req:
    """The handler reads raw bytes and headers; that is all this needs.

    The signature check is covered in test_esign_webhook_signature.py —
    these tests run with no secret configured, so they exercise the
    second and more important door: the handler does not believe the
    payload regardless of who sent it."""
    def __init__(self, payload: dict, headers: dict | None = None):
        self._body = json.dumps(payload).encode()
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


# ── Fixtures ─────────────────────────────────────────────────────────

BIZ = {"id": "biz-1", "name": "KMJ Creative Solutions", "owner_id": "owner-1"}

SUBMISSION_ID = "4021"
SUBMITTER_ID = "77"


def _doc(status="sent"):
    return {
        "id": "row-1",
        "business_id": "biz-1",
        "document_id": SUBMISSION_ID,
        "title": "Revenue Share Agreement",
        "signer_name": "Aunt",
        "signer_email": "aunt@example.com",
        "status": status,
    }


def _form_completed(submission_id=SUBMISSION_ID, submitter_id=SUBMITTER_ID):
    """The shape DocuSeal actually sends for form.* events: `data` is the
    SUBMITTER, and the submission is nested one level down."""
    return {
        "event_type": "form.completed",
        "timestamp": "2026-08-30T12:00:00Z",
        "data": {
            "id": int(submitter_id),
            "email": "aunt@example.com",
            "status": "completed",
            "submission": {"id": int(submission_id), "status": "completed"},
        },
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
    # These tests are about the second door, not the signature.
    monkeypatch.delenv("DOCUSEAL_WEBHOOK_SECRET", raising=False)

    monkeypatch.setattr(dr.sb_clients, "sb_patch_as_service",
                        lambda path, body: s.patched.append((path, body)))

    import event_spine
    monkeypatch.setattr(event_spine, "emit",
                        lambda et, biz, payload, source=None: s.emitted.append(et))

    import audit_log
    monkeypatch.setattr(audit_log, "record",
                        lambda *a, **k: s.audited.append(k.get("verb")))

    async def _fake_emails(biz, doc):
        s.emails.append(doc["document_id"])
    monkeypatch.setattr(dr, "_send_completion_emails", _fake_emails)

    return s


# ── The completion path ──────────────────────────────────────────────

def test_completion_fires_every_side_effect(spy):
    """Status, spine event, audit row, emails — all four or none."""
    out = asyncio.run(dr._apply_status(_doc(), BIZ, "completed"))

    assert out["changed"] is True
    assert out["status"] == "completed"
    assert spy.emitted == ["contract_signed"]
    assert spy.audited == ["esign_completed"]
    assert spy.emails == [SUBMISSION_ID]
    # completed_at is written, not left for a later pass to guess at.
    assert spy.patched[0][1]["completed_at"]


def test_redelivery_is_a_no_op(spy):
    """The second webhook for the same signature must cost nothing.

    Not 'mostly nothing' — no second event, no second audit row, and
    above all no second pair of emails landing on the signer."""
    already = _doc(status="completed")
    out = asyncio.run(dr._apply_status(already, BIZ, "completed"))

    assert out["changed"] is False
    assert spy.emitted == []
    assert spy.audited == []
    assert spy.emails == []
    assert spy.patched == []


def test_non_completion_status_does_not_email(spy):
    """A decline is a status change, not a completion. It must not send
    a 'signed' confirmation with an executed copy that doesn't exist."""
    out = asyncio.run(dr._apply_status(_doc(), BIZ, "declined"))

    assert out["changed"] is True
    assert spy.emitted == []
    assert spy.emails == []
    assert spy.patched[0][1]["status"] == "declined"
    assert "completed_at" not in spy.patched[0][1]


# ── Which id we read ─────────────────────────────────────────────────

def test_form_events_read_the_nested_submission_id(spy, monkeypatch):
    """For form.* events the submission id is at data.submission.id.
    Missing it means the webhook silently does nothing forever — which
    looks exactly like no webhook at all."""
    seen = {}
    def _get(path):
        if path.startswith("/esign_documents"):
            seen["path"] = path
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", _get)

    async def _completed(document_id):
        return "completed"
    monkeypatch.setattr(dr, "_live_status", _completed)

    out = asyncio.run(dr.esign_webhook(_Req(_form_completed())))
    assert f"document_id=eq.{SUBMISSION_ID}" in seen["path"]
    assert out["changed"] is True


def test_a_form_event_never_reads_the_submitter_id(spy, monkeypatch):
    """THE LOAD-BEARING TEST OF THIS FILE.

    `data.id` on a form.* event is the SUBMITTER id. Submitters and
    submissions are separate integer sequences, so it is an ordinary
    number that will one day equal some other business's submission id.
    Reading it would not throw, would not log, and would not fail a
    smoke test — it would silently refresh the wrong agreement, and on a
    completion it would mail somebody else's executed contract out.

    Here the submitter id is deliberately made to collide with a real
    submission id belonging to a DIFFERENT business. The lookup must
    still go out for the nested submission id, never the submitter."""
    other_biz_doc = dict(_doc(), id="row-9", business_id="biz-9",
                         document_id=SUBMITTER_ID)
    looked_up = []

    def _get(path):
        if path.startswith("/esign_documents"):
            looked_up.append(path)
            # Whatever id was asked for, hand back a matching row — so a
            # wrong read produces a plausible success, not an obvious miss.
            if f"eq.{SUBMITTER_ID}" in path:
                return [other_biz_doc]
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", _get)

    async def _completed(document_id):
        return "completed"
    monkeypatch.setattr(dr, "_live_status", _completed)

    asyncio.run(dr.esign_webhook(_Req(_form_completed())))

    doc_lookups = [p for p in looked_up if p.startswith("/esign_documents")]
    assert doc_lookups, "no document lookup happened at all"
    assert f"eq.{SUBMISSION_ID}" in doc_lookups[0]
    assert f"eq.{SUBMITTER_ID}" not in doc_lookups[0], (
        "read the submitter id as if it were the submission id")


def test_submission_events_read_the_top_level_id(spy, monkeypatch):
    """For submission.* events `data` IS the submission, so data.id is
    the right field. The two families genuinely differ; the handler has
    to know which one it is holding."""
    seen = {}
    def _get(path):
        if path.startswith("/esign_documents"):
            seen["path"] = path
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", _get)

    async def _completed(document_id):
        return "completed"
    monkeypatch.setattr(dr, "_live_status", _completed)

    out = asyncio.run(dr.esign_webhook(_Req({
        "event_type": "submission.completed",
        "data": {"id": int(SUBMISSION_ID), "status": "completed"},
    })))
    assert f"eq.{SUBMISSION_ID}" in seen["path"]
    assert out["changed"] is True


def test_an_unclassifiable_event_never_guesses(spy, monkeypatch):
    """An event family we have never seen must fall through to fields
    that name a submission explicitly, not to a bare `id`."""
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", lambda path: [])

    out = asyncio.run(dr.esign_webhook(_Req({
        "event_type": "something.new",
        "data": {"id": int(SUBMITTER_ID)},
    })))
    assert out["ignored"] == "no_document_id"


# ── The webhook cannot be used to forge a completion ─────────────────

def test_webhook_ignores_unknown_document(spy, monkeypatch):
    """A payload naming a submission we never sent is logged and dropped
    — never inserted, never acted on."""
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", lambda path: [])

    out = asyncio.run(dr.esign_webhook(_Req(_form_completed(submission_id="9999"))))

    assert out["ok"] is True
    assert out["ignored"] == "unknown_document"
    assert spy.emitted == []
    assert spy.emails == []


def test_webhook_does_not_believe_the_payload(spy, monkeypatch):
    """THE OTHER LOAD-BEARING TEST.

    The payload screams 'completed'. The provider says the document is
    still out for signature. The provider wins — nothing is marked
    signed, nobody is emailed.

    If this ever fails, an unauthenticated POST can mark any document
    signed and mail an 'executed copy' to a counterparty."""
    def _get(path):
        if path.startswith("/esign_documents"):
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", _get)

    async def _still_out(document_id):
        return "sent"
    monkeypatch.setattr(dr, "_live_status", _still_out)

    out = asyncio.run(dr.esign_webhook(_Req(_form_completed())))   # the lie

    assert out["changed"] is False
    assert spy.emitted == []
    assert spy.emails == []


def test_webhook_applies_the_providers_truth(spy, monkeypatch):
    """The honest path: provider confirms completion, everything fires."""
    def _get(path):
        if path.startswith("/esign_documents"):
            return [_doc(status="sent")]
        return [BIZ]
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", _get)

    async def _completed(document_id):
        return "completed"
    monkeypatch.setattr(dr, "_live_status", _completed)

    out = asyncio.run(dr.esign_webhook(_Req(_form_completed())))

    assert out["changed"] is True
    assert out["status"] == "completed"
    assert spy.emitted == ["contract_signed"]
    assert spy.emails == [SUBMISSION_ID]


def test_webhook_always_returns_200(spy, monkeypatch):
    """A webhook that errors gets retried, then throttled, then disabled
    by the provider. Every branch returns ok."""
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", lambda path: [])

    for payload in ({}, {"event_type": "form.completed"},
                    {"event_type": "form.completed", "data": {}},
                    {"data": {"submission": {}}},
                    {"event_type": "submission.completed", "data": {"id": "x"}}):
        out = asyncio.run(dr.esign_webhook(_Req(payload)))
        assert out["ok"] is True


def test_unsigned_delivery_is_dropped_before_any_lookup(spy, monkeypatch):
    """With a secret configured, an unsigned delivery never reaches the
    database. Full signature coverage lives in
    test_esign_webhook_signature.py — this pins that the check happens
    FIRST, so an anonymous flood cannot make us do lookups."""
    monkeypatch.setenv("DOCUSEAL_WEBHOOK_SECRET", "s3cret")
    called = {"n": 0}
    def _get(path):
        called["n"] += 1
        return []
    monkeypatch.setattr(dr.sb_clients, "sb_get_as_service", _get)

    out = asyncio.run(dr.esign_webhook(_Req(_form_completed())))

    assert out["ignored"] == "bad_signature"
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
    monkeypatch.setattr(dr, "_signed_pdf_b64", _no_pdf)
    monkeypatch.setattr(dr, "_owner_email", _owner)

    doc = _doc()
    doc["signer_email"] = "KEVIN@example.com"     # same person, different case
    asyncio.run(dr._send_completion_emails(BIZ, doc))

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
    monkeypatch.setattr(dr, "_signed_pdf_b64", _no_pdf)
    monkeypatch.setattr(dr, "_owner_email", _owner)

    asyncio.run(dr._send_completion_emails(BIZ, _doc()))

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
    monkeypatch.setattr(dr, "_signed_pdf_b64", _no_pdf)
    monkeypatch.setattr(dr, "_owner_email", _owner)

    asyncio.run(dr._send_completion_emails(BIZ, _doc()))   # must not raise
