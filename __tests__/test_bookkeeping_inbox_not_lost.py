"""A bookkeeping proposal sent to the Inbox is never lost on the way.

send_to_inbox posted with prefer=None (no body back, so success and
failure looked alike) and marked the proposal sent_to_inbox either way.
agent_queue had no `data` column, so every insert failed and every
proposal sent to the Inbox vanished from both places.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_bookkeeping
import sb_clients


@pytest.fixture
def proposal(monkeypatch):
    monkeypatch.setattr(chief_bookkeeping, "_get_proposal", lambda b, p: {
        "id": p, "proposal_type": "propose_match", "reasoning": "Matches the deposit"})
    patches = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda path, body: patches.append((path, body)))
    return patches


def test_failed_insert_leaves_the_proposal_to_review(monkeypatch, proposal):
    from fastapi import HTTPException
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        chief_bookkeeping.send_to_inbox("b1", "p1")
    assert e.value.status_code == 502
    assert proposal == [], "a proposal must not be marked sent when nothing landed"


def test_landed_insert_marks_it_sent_and_carries_the_link(monkeypatch, proposal):
    posted = []

    def fake_post(path, body, **kw):
        posted.append((path, body, kw))
        return [{"id": "q1"}]

    monkeypatch.setattr(sb_clients, "sb_post_as_service", fake_post)
    assert chief_bookkeeping.send_to_inbox("b1", "p1") == {"ok": True}
    [(path, body, kw)] = posted
    assert path == "/agent_queue"
    assert body["data"]["chief_bookkeeping_proposal_id"] == "p1"
    assert kw.get("prefer", "return=representation") is not None, "the insert must report what landed"
    [(patch_path, patch_body)] = proposal
    assert "id=eq.p1" in patch_path and patch_body["status"] == "sent_to_inbox"
