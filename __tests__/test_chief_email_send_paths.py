"""Chief's outbound email path — what the practitioner is TOLD happened.

The send itself has been exercised for a long time. What had not been is
the one outcome where the queue row is left untouched: `doc_guard` refuses
a document with blockers, `_do_approve_one` returns BEFORE it patches
anything, and nothing is approved and nothing is sent.

The HTTP door (`approvals_router`) already answered 409 for that. Chief's
door had no branch for it at all, so "blocked" fell through to the bare
"approved" string and the action card read "✓ Approved: <subject>" over a
document still sitting in the queue. A practitioner told their contract was
approved has no reason to look at it again.

These tests pin the honest wording on all four paths that can hit the gate,
plus the identity argument every Chief send now carries.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import asyncio

import pytest

import chief_of_staff as cos

BIZ = {"id": "biz1", "name": "Test Co", "owner_id": "u1", "settings": {}}
ROW = {"id": "q1", "business_id": "biz1", "status": "draft",
       "subject": "Engagement Letter — Marcus Webb", "body": "x" * 40,
       "contact_id": "c1", "action_type": "document", "agent": "contract"}

BLOCKED = {"ok": False, "sent": False, "reason": "blocked",
           "blocked": {"error": "document_blocked", "blockers": 2,
                       "message": "The fee table does not add up. 2 things in "
                                  "this document would be wrong in front of "
                                  "the client."},
           "message": "The fee table does not add up. 2 things in this "
                      "document would be wrong in front of the client."}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def gate(monkeypatch):
    """Serve the queue row; make every approval come back blocked."""
    patched = []

    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/agent_queue"):
            return [dict(ROW)]
        if method == "PATCH":
            patched.append((path, body))
        return []

    async def _approve(client, biz, item, **kw):
        return dict(BLOCKED)

    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(cos, "_do_approve_one", _approve)
    return patched


def _assert_honest(res):
    assert res.get("failed") is True, (
        "a blocked document is a failure — without the flag it is narrated "
        "and audited as a success (#345 seam)")
    assert res.get("email_sent") is False
    low = res["result"].lower()
    assert "not approved" in low and "not sent" in low
    assert "approved and sent" not in low
    assert res["label"].startswith("Held:")
    assert "fee table" in res["result"], "the guard's own reason, verbatim"


def test_approve_draft_reports_a_blocked_document_as_held(gate):
    res = _run(cos.handle_approve_draft(None, BIZ, {"queue_id": "q1"}))
    _assert_honest(res)


def test_draft_and_send_reports_a_blocked_document_as_held(gate, monkeypatch):
    async def _draft(client, biz, action):
        return {"type": "draft_email", "result": "queued for approval",
                "label": "Email", "queue_id": "q1",
                "draft_preview": {"subject": ROW["subject"], "body": "x"}}

    monkeypatch.setattr(cos, "handle_draft_email", _draft)
    res = _run(cos.handle_draft_and_send(None, BIZ, {"contact_id": "c1"}))
    _assert_honest(res)
    assert res.get("draft_preview"), "the draft is real even when the send isn't"


def test_edit_draft_says_the_edit_landed_and_the_approval_did_not(gate):
    res = _run(cos.handle_edit_draft(None, BIZ, {
        "queue_id": "q1", "new_body": "y" * 40}))
    assert res.get("failed") is True
    assert res["result"].lower().startswith("edit saved")
    assert "not approved" in res["result"].lower()
    assert res.get("draft_preview")


def test_bulk_approve_names_what_it_held(gate, monkeypatch):
    async def _query(client, biz_id, filter_str):
        return [dict(ROW), dict(ROW, id="q2", subject="NDA — Acme")]

    monkeypatch.setattr(cos, "_query_queue_by_filter", _query)
    res = _run(cos.handle_bulk_approve(None, BIZ, {"filter": "all"}))
    assert "2 held for review" in res["result"], (
        "held documents used to vanish into the denominator with nothing "
        "naming them")
    assert res["sent_count"] == 0
    assert len(res["blocked_items"]) == 2


def test_a_clean_approval_is_still_narrated_as_one(monkeypatch):
    """The gate must not have made every approval sound suspicious."""
    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/agent_queue"):
            return [dict(ROW)]
        return []

    async def _approve(client, biz, item, **kw):
        return {"ok": True, "sent": True, "reason": None,
                "to_email": "m@x.com", "to_name": "Marcus", "provider_id": "re_1"}

    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(cos, "_do_approve_one", _approve)
    res = _run(cos.handle_approve_draft(None, BIZ, {"queue_id": "q1"}))
    assert res["result"] == "approved and sent"
    assert res.get("failed") is not True
    assert res["email_sent"] is True


# ─── whose name is on the envelope ────────────────────────────────────

def test_chief_sends_carry_the_business_id(monkeypatch):
    """send_via_resend swaps in a business's VERIFIED custom sending domain
    when the send is attributable to it. Chief passed only a routed
    reply-to, which is None on any deployment without INBOUND_EMAIL_DOMAIN
    — so a practitioner who had verified their own domain still had every
    Chief email leave as the platform."""
    seen = {}

    async def _sb(client, method, path, body=None):
        if method == "GET" and path.startswith("/contacts"):
            return [{"id": "c1", "name": "Marcus", "email": "m@x.com"}]
        return []

    async def _send(**kwargs):
        seen.update(kwargs)
        return {"id": "re_1"}

    import email_sender
    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(email_sender, "send_via_resend", _send)
    monkeypatch.setattr(email_sender, "build_routed_reply_to",
                        lambda b, c: None)   # INBOUND_EMAIL_DOMAIN unset
    monkeypatch.setenv("RESEND_API_KEY", "re_test")

    out = _run(cos._send_queued_email(None, BIZ, dict(ROW)))
    assert out["sent"] is True
    assert seen.get("business_id") == "biz1"
