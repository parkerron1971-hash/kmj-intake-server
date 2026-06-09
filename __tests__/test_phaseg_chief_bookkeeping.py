"""Phase G — Chief Bookkeeping Intelligence — focused logic tests.

Pure in-process logic; Supabase + Stripe are mocked (same philosophy as the
F.2 test suite)."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_bookkeeping as cb


def test_needs_attention_thresholds():
    # Not linked → never needs attention.
    assert cb.needs_attention({"linked": False, "unmatched": 9, "uncategorized": 9}) is False
    # Linked + any unmatched → attention (threshold 0).
    assert cb.needs_attention({"linked": True, "unmatched": 1, "uncategorized": 0}) is True
    # Linked + uncategorized must exceed 5.
    assert cb.needs_attention({"linked": True, "unmatched": 0, "uncategorized": 5}) is False
    assert cb.needs_attention({"linked": True, "unmatched": 0, "uncategorized": 6}) is True


def test_approve_categorize_patches_and_marks(monkeypatch):
    import sb_clients
    patches = []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{
        "id": "p1", "business_id": "biz1", "status": "pending",
        "proposal_type": "propose_categorize", "plaid_transaction_id": "t1",
        "proposed": {"plaid_transaction_id": "t1", "business_category": "operating",
                     "business_subcategory": None},
    }])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: patches.append((path, body)))

    out = cb.approve_proposal("biz1", "p1")
    assert out["executed"] == "propose_categorize"
    # First patch updates the transaction's bucket; second marks the proposal.
    tx_patch = next(b for p, b in patches if "plaid_transactions" in p)
    assert tx_patch["business_category"] == "operating"
    prop_patch = next(b for p, b in patches if "chief_bookkeeping_proposals" in p)
    assert prop_patch["status"] == "approved"


def test_approve_is_idempotent_when_already_resolved(monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{
        "id": "p1", "business_id": "biz1", "status": "approved",
        "proposal_type": "propose_categorize", "proposed": {},
    }])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: pytest.fail("must not re-execute a resolved proposal"))
    out = cb.approve_proposal("biz1", "p1")
    assert out["already"] == "approved"


def test_reject_with_override_captures_learning_signal(monkeypatch):
    import sb_clients
    posts = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{
        "id": "p1", "business_id": "biz1", "status": "pending",
        "proposal_type": "propose_categorize", "proposed": {"business_category": "operating"},
    }])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: None)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, prefer=None: posts.append((path, body)))

    cb.reject_proposal("biz1", "p1", override={"business_category": "tax"}, override_reason="it's a tax payment")
    signal = next(b for p, b in posts if "chief_learning_signals" in p)
    assert signal["proposal_type"] == "propose_categorize"
    assert signal["practitioner_override"] == {"business_category": "tax"}
    assert signal["original_proposal"] == {"business_category": "operating"}


def test_reject_without_override_skips_signal(monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{
        "id": "p1", "business_id": "biz1", "status": "pending",
        "proposal_type": "propose_match", "proposed": {},
    }])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: None)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda path, body, prefer=None: pytest.fail("no signal without override"))
    out = cb.reject_proposal("biz1", "p1")
    assert out["ok"] is True


def test_gather_and_format_empty_without_linked_bank(monkeypatch):
    import sb_clients
    # No active plaid_items → empty block (keeps prompt clean).
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [])
    assert cb.gather_and_format("biz1", "consultant") == ""
