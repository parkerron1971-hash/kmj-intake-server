"""Two loose ends of the answer check, both from 2026-09-22.

1. `reply recovery rejected (review is not JSON)`: the reviewer wrapped
   its JSON in a sentence, the repaired answer was never checked, and the
   practitioner heard "No action ran in this request".
2. A public rule stated from general knowledge ("the 990-N is for gross
   receipts of $50,000 or less") has no business record to cite, and a
   figure without a citation withheld the whole answer. It now reaches the
   practitioner labeled as general knowledge. Business figures keep the
   full check.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth


def _run(reply, reviewer, repairer=None, message="Can we do a 990 form", budget_s=45.0):
    return asyncio.run(truth.finalize_reply(None, reply, ctx={}, view_detail="", taken=[],
        message=message, business_id="biz", reviewer=reviewer, repairer=repairer, budget_s=budget_s))


def _reviewer(*outputs):
    calls = []

    async def review(client, system, messages, **kw):
        calls.append(messages)
        return outputs[min(len(calls), len(outputs)) - 1]
    review.calls = calls
    return review


# ── 1. a review with words around it is still a review ─────────────────

def test_json_after_a_sentence_is_read():
    reply = "Which fiscal year is this for?"
    raw = 'Here is my review:\n{"verdict": "supported", "claims": []}\nAll good.'
    verdict, _, reason = truth.assess_review(raw, reply, {})
    assert verdict == 'supported', reason


def test_a_fenced_block_after_prose_is_read():
    raw = 'Review below.\n```json\n{"verdict": "supported", "claims": []}\n```'
    assert truth.assess_review(raw, "Which fiscal year?", {})[0] == 'supported'


def test_prose_with_no_review_object_is_still_invalid():
    verdict, _, reason = truth.assess_review('I think this looks fine {mostly}.', "Hi.", {})
    assert verdict == 'invalid' and reason == 'review is not JSON'


def test_wrapped_json_is_checked_like_any_review():
    # Being lenient about the wrapper must not be lenient about the content.
    raw = 'Sure: {"verdict": "supported", "claims": []}'
    verdict, _, reason = truth.assess_review(raw, "You earned $900 last month.", {})
    assert verdict == 'unsupported' and '900' in reason


def _repair_run(second_review):
    first = json.dumps({"verdict": "unsupported", "claims": [
        {"text": "I texted your invoice.", "kind": "action", "source_id": "", "quote": "", "gap": "no receipt"}]})
    review = _reviewer(first, second_review)

    async def repairer(client, system, messages, **kw):
        return "Which invoice should I text?"

    return _run("I texted your invoice.", review, repairer, message="text the invoice"), review


def test_a_wrapped_recheck_of_a_repair_recovers_the_answer():
    (result, meta), review = _repair_run('My check: {"verdict": "supported", "claims": []}')
    assert result == "Which invoice should I text?" and meta.get("recovered")
    assert len(review.calls) == 2


def test_an_unreadable_recheck_still_withholds_without_asking_again():
    (result, meta), review = _repair_run("Looks fine to me.")
    assert result == truth.NO_ACTION_REPLY and meta["status"] == "withheld"
    assert len(review.calls) == 2


# ── 2. a public rule is delivered as general knowledge ────────────────

RULE = "the 990-N is for gross receipts of $50,000 or less"
REPLY = ("Yes, we can prepare it. For a small nonprofit, " + RULE +
         ", so tell me roughly what came in last year.")


def _rule_review(kind="reference", text=RULE, gap=None):
    claim = {"text": text, "kind": kind, "source_id": "", "quote": ""}
    if gap:
        claim["gap"] = gap
    return json.dumps({"verdict": "unsupported", "claims": [claim]})


def test_a_public_threshold_is_delivered_labeled_not_withheld():
    result, meta = _run(REPLY, _reviewer(_rule_review()))
    assert result.startswith(REPLY)
    assert "general rules from what I know, not from your records" in result
    assert RULE in result
    assert meta["status"] == "caveated" and meta["references"] == [RULE]
    assert "still unverified" not in result


def test_a_reference_with_a_gap_note_is_still_a_reference():
    result, meta = _run(REPLY, _reviewer(_rule_review(gap="general knowledge")))
    assert meta["status"] == "caveated" and meta["references"] == [RULE]


def test_a_business_figure_labeled_reference_keeps_the_full_check():
    reply = "Your gross receipts were $48,000, so the 990-EZ fits."
    raw = _rule_review(text="Your gross receipts were $48,000")
    verdict, _, reason = truth.assess_review(raw, reply, {})
    assert verdict == 'unsupported' and reason.startswith('claim number has no evidence')
    result, meta = _run(reply, _reviewer(raw))
    assert meta["status"] == "withheld"
    assert "48,000" not in result


def test_the_same_figure_as_a_plain_fact_is_still_withheld():
    result, meta = _run(REPLY, _reviewer(_rule_review(kind="fact", gap="no source")))
    assert meta["status"] == "withheld"


def test_a_rule_and_a_prose_gap_show_both_notes():
    raw = json.dumps({"verdict": "unsupported", "claims": [
        {"text": RULE, "kind": "reference", "source_id": "", "quote": ""},
        {"text": "tell me roughly what came in last year", "kind": "fact", "source_id": "", "quote": "",
         "gap": "not a fact"}]})
    result, meta = _run(REPLY, _reviewer(raw))
    assert "still unverified" in result and "general rules from what I know" in result
    assert meta["gaps"] and meta["references"] == [RULE]


def test_a_rule_beside_a_completion_claim_is_not_delivered():
    reply = "I filed your 990-N. " + RULE + "."
    raw = json.dumps({"verdict": "unsupported", "claims": [
        {"text": RULE, "kind": "reference", "source_id": "", "quote": ""},
        {"text": "I filed your 990-N", "kind": "action", "source_id": "", "quote": "", "gap": "no receipt"}]})
    result, meta = _run(reply, _reviewer(raw))
    assert meta["status"] == "withheld"
    assert "filed" not in result


def test_a_cited_reference_is_checked_like_a_fact():
    sources = {"web:https://irs.gov/990n": {"kind": "research", "text": "gross receipts normally $50,000 or less",
                                           "complete": True}}
    good = json.dumps({"verdict": "supported", "claims": [
        {"text": RULE, "kind": "reference", "source_id": "web:https://irs.gov/990n", "quote": "$50,000 or less"}]})
    assert truth.assess_review(good, REPLY, sources)[0] == 'supported'
    bad = json.dumps({"verdict": "supported", "claims": [
        {"text": RULE, "kind": "reference", "source_id": "web:https://irs.gov/990n", "quote": "$25,000 or less"}]})
    assert truth.assess_review(bad, REPLY, sources)[0] == 'unsupported'
