"""Spoken receipt fallbacks name the operation, target, and actual state."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import chief_of_staff as chief
import chief_truth as truth
from chief_receipts import receipt_lines


def moved(name, previous="lead", current="inactive"):
    return {"type": "update_contact_status", "label": name,
            "result": f"{previous} \u2192 {current}"}


def finalize(receipts, review=""):
    draft = "I've completed the entire cleanup and sent everyone a message."
    if review == "reject":
        review = json.dumps({"verdict": "unsupported", "claims": [
            {"text": draft, "kind": "action", "source_id": "", "quote": "", "gap": "no send receipt"}]})
    return asyncio.run(truth.finalize_reply(None, draft, ctx={}, view_detail={},
        taken=receipts, message="Clean up those leads", business_id="fixture",
        reviewer=AsyncMock(return_value=review)))


@pytest.mark.parametrize("review", ["", "reject"])
def test_checked_fallback_speaks_operation_and_names_in_one_sentence(review):
    result, meta = finalize([moved(name) for name in ("Ada", "Ben", "Cy")], review)
    assert result.startswith("Moved three leads to inactive: Ada, Ben, Cy.")
    assert meta["status"] == "receipts"
    assert "everyone a message" not in result
    assert "rest of what you asked for isn't done" not in result


def test_composer_receives_result_even_when_label_is_only_a_name():
    result = chief._format_action_results_for_reply([moved("Ada")])
    assert "Ada" in result and "lead \u2192 inactive" in result


def test_empty_composer_cannot_restore_optimistic_completed_batch(monkeypatch):
    monkeypatch.setattr(chief, "_call_claude", AsyncMock(return_value=""))
    receipts = [moved("Ada"), {"type": "enqueue_job", "label": "Remaining cleanup", "result": "queued"}]
    result = asyncio.run(chief._compose_post_action_reply(None, "Clean up my leads",
        "Done. All leads are inactive.", receipts, "fixture"))
    assert "Moved Ada from lead to inactive." in result
    assert "Remaining cleanup: queued" in result
    assert "All leads" not in result and "completed" not in result


def test_already_inactive_is_not_reported_as_a_new_change():
    result = receipt_lines([{"type": "update_contact_status", "label": "Ada", "result": "already inactive"}])
    assert result == ["Ada: already inactive"]


def test_distinct_status_changes_are_not_merged():
    result = receipt_lines([moved("Ada"), moved("Ben", "active", "inactive"), moved("Cy")])
    assert result == ["Moved two leads to inactive: Ada, Cy.", "Moved Ben from active to inactive."]


def test_failed_and_held_results_never_count_as_completed():
    held = {"type": "send_sms", "label": "Before I send Ben a text, say send it.",
            "result": "HELD: emit this action again", "needs_confirmation": True, "failed": True}
    failed = {"type": "update_contact_status", "label": "Cy", "result": "Failed: read-only contact", "failed": True}
    result = chief._deterministic_fallback_reply([moved("Ada"), held, failed])
    assert "Moved Ada from lead to inactive." in result
    assert "read-only contact" in result
    assert held["label"] in result
    assert "emit this action" not in result
    assert "three" not in result and "completed" not in result


def test_pending_work_is_not_called_completed_beside_a_failure():
    result = chief._deterministic_fallback_reply([
        {"type": "enqueue_job", "label": "Remaining cleanup", "result": "queued"},
        {"type": "send_sms", "failed": True, "label": "Ada", "result": "Failed: offline"}])
    assert "Remaining cleanup: queued." in result
    assert "completed" not in result and "went through" not in result.split("queued.")[0]


@pytest.mark.parametrize("message,expected", [
    ("What is 1 + 1?", "2."), ("what's 1+1", "2."), ("Calculate 12 - 5.", "7."),
    ("-3 * 4", "-12."), ("999999999+999999999", "1999999998."),
])
def test_elementary_arithmetic_is_an_exact_answer_without_business_review(message, expected):
    reviewer = AsyncMock(side_effect=AssertionError("arithmetic needs no business evidence"))
    answer, meta = asyncio.run(truth.finalize_reply(None,
        "The answer is two. Would you like help with your business?", ctx={}, view_detail={},
        taken=[], message=message, business_id="fixture", reviewer=reviewer))
    assert answer == expected and meta["status"] == "calculated"
    reviewer.assert_not_awaited()


@pytest.mark.parametrize("message", [
    "What is 1+1 and send Ada an email", "We have 1+1 leads", "1+1? What is our revenue?",
    "1+1 million dollars", "1/0", "1000000000+1", "__import__('os')", "1+1=3",
])
def test_arithmetic_fast_answer_does_not_swallow_tasks_units_or_explanations(message):
    assert truth.elementary_arithmetic_reply(message) is None


def test_arithmetic_never_hides_an_actual_failed_receipt():
    answer, meta = asyncio.run(truth.finalize_reply(None, "2.", ctx={}, view_detail={},
        taken=[{"type": "send_sms", "failed": True, "result": "Failed: offline", "label": "Ada"}],
        message="1+1", business_id="fixture", reviewer=AsyncMock()))
    assert "didn't go through" in answer and meta["status"] == "receipts"


@pytest.mark.parametrize("message", ["Thanks, that helped.", "Thank you!", "Thanks Chief", "Thank you for your help"])
def test_a_pure_thank_you_ends_without_reopening_business_review(message):
    reviewer = AsyncMock(side_effect=AssertionError("acknowledgments need no business review"))
    answer, meta = asyncio.run(truth.finalize_reply(None,
        "Glad it helped. Tell me which customer you want to talk to next.", ctx={}, view_detail={},
        taken=[], message=message, business_id="fixture", reviewer=reviewer))
    assert answer == "You're welcome." and meta["status"] == "acknowledged"
    reviewer.assert_not_awaited()


@pytest.mark.parametrize("message", ["Thanks, did you send it?", "Thank you, move Ada to inactive", "Thanks for nothing", "Thanks, but that is wrong"])
def test_mixed_or_negative_thanks_are_not_treated_as_simple_acknowledgments(message):
    assert truth.conversation_check_reply(message) is None
