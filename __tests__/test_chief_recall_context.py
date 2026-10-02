"""Conversation recall must return the detail it matched and honest read status."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import chief_of_staff as cos
import chief_tool_loop as loop


def recall(monkeypatch, rows, query="vision"):
    monkeypatch.setattr(cos, "_sb", AsyncMock(return_value=rows))
    return asyncio.run(cos.handle_recall_conversation(None, {"id": "biz"}, {"query": query}))


def archived(messages, summary="You: Let's discuss the business."):
    return {"summary": summary, "messages": messages, "key_topics": [],
            "ended_at": "2026-10-01T10:00:00Z", "message_count": len(messages)}


def test_recall_delivers_the_matching_detail_and_adjacent_answer(monkeypatch):
    row = archived([
        {"role": "user", "content": "Let us revisit our vision."},
        {"role": "assistant", "content": "We discussed helping new volunteers feel ready for their first shift."},
    ])
    result = recall(monkeypatch, [row])
    model_result = loop._shrink(result)
    assert "helping new volunteers" in model_result
    assert "user:" in model_result and "assistant:" in model_result
    assert "not execution receipts" in model_result


def test_recall_centers_long_message_excerpt_on_the_query(monkeypatch):
    row = archived([{"role": "user", "content": "Earlier topic. " * 200 +
                    "The vision is welcoming new volunteers into their first shift."}])
    result = recall(monkeypatch, [row])
    assert "welcoming new volunteers" in loop._shrink(result)


@pytest.mark.parametrize("rows", [None, {"error": "read unavailable"}])
def test_failed_recall_is_unavailable_not_empty(monkeypatch, rows):
    result = recall(monkeypatch, rows)
    assert result["failed"] is True
    assert result["result"] != "no_conversations"
    assert "unavailable" in result["summary"].lower()


def test_capped_search_does_not_claim_exhaustive_absence(monkeypatch):
    result = recall(monkeypatch, [archived([])] * 60)
    assert result["result"] == "no_matches"
    assert result["search_complete"] is False
    assert "60" in result["summary"] and "older" in result["summary"].lower()


def test_successful_empty_read_does_not_promise_archival_guarantees(monkeypatch):
    result = recall(monkeypatch, [])
    assert result["result"] == "no_conversations"
    assert "every conversation is kept" not in result["summary"]


def test_recall_remains_readable_inside_tool_result_budget(monkeypatch):
    rows = [archived([
        {"role": "user", "content": "Our vision " + "long context " * 100},
        {"role": "assistant", "content": "Discussed approach " + "details " * 100},
    ], summary="Summary " * 100) for _ in range(5)]
    result = recall(monkeypatch, rows)
    model_result = json.loads(loop._shrink(result))
    assert not model_result.get("truncated")
    assert len(model_result["conversations"]) == 5


def test_assistant_match_retains_the_owners_preceding_constraint(monkeypatch):
    row = archived([
        {"role": "user", "content": "Keep this as a draft; do not send anything."},
        {"role": "assistant", "content": "The vision draft centers on welcoming volunteers."},
        {"role": "user", "content": "Let us discuss something else."},
    ])
    result = recall(monkeypatch, [row])
    transcript = result["conversations"][0]
    assert "do not send anything" in transcript
    assert "vision draft" in transcript
    assert "something else" not in transcript


def test_matches_and_returned_excerpt_counts_are_distinct(monkeypatch):
    rows = [archived([{"role": "user", "content": "Our vision is helping volunteers."}])] * 60
    result = recall(monkeypatch, rows)
    assert result["result"] == "60 conversations"
    assert result["returned_count"] == len(result["conversations"]) == 5
    assert result["search_complete"] is False
