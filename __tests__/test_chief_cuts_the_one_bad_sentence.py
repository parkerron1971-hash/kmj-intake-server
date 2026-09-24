"""
test_chief_cuts_the_one_bad_sentence.py — one unprovable figure costs one sentence (2026-09-24).

Live: "What should I charge per seat for a two-day coaching intensive, and
how would you fill 12 seats by November?" → a 1,971-character answer
withheld over `claim number has no evidence :: the 90-day group cohort
sells at $750`, the model repair timed out, and after 66 s the owner read
"No action ran … try again?". Now the failing sentence is cut, the rest is
re-checked with the same review (no second model call), and the answer is
delivered with one line saying a figure was left out.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

DRAFT = ("For a two-day intensive, I'd price seats at $797. "
         "That sits under the 90-day group cohort, which sells at $750 per month. "
         "Fill it from people who already know your work first, then open it to your wider list. "
         "Start the outreach this week so you have six weeks of runway.")
BAD = "the 90-day group cohort, which sells at $750 per month"


def _review(extra=()):
    return json.dumps({"verdict": "unsupported", "claims": [
        {"text": "I'd price seats at $797", "kind": "fact", "source_id": "", "quote": "", "gap": "advice"},
        {"text": BAD, "kind": "fact", "source_id": "", "quote": "", "gap": "no record of this price"},
        *extra]})


def _finalize(draft, raw, repairer=None):
    return asyncio.run(truth.finalize_reply(
        None, draft, ctx={}, view_detail="", taken=[], message="what should I charge?",
        business_id="biz", reviewer=AsyncMock(return_value=raw), repairer=repairer))


def test_the_bad_sentence_is_cut_and_the_advice_delivered():
    repairer = AsyncMock(return_value="should not be needed")
    out, meta = _finalize(DRAFT, _review(), repairer)
    assert "$750" not in out
    assert "I'd price seats at $797." in out and "wider list" in out
    assert "left out one figure" in out and "try again" not in out
    assert meta["status"] == "trimmed" and meta["cuts"] == 1
    repairer.assert_not_awaited()


def test_a_one_sentence_bad_answer_is_still_withheld():
    raw = json.dumps({"verdict": "unsupported", "claims": [
        {"text": "Revenue was $900,000", "kind": "fact", "source_id": "", "quote": "", "gap": "none"}]})
    out, meta = _finalize("Revenue was $900,000.", raw)
    assert "$900,000" not in out and meta["status"] == "withheld"


def test_cutting_most_of_the_answer_is_not_a_rescue():
    draft = "Your revenue was $9,000. Your costs were $8,000. Keep going."
    raw = json.dumps({"verdict": "unsupported", "claims": [
        {"text": "Your revenue was $9,000", "kind": "fact", "source_id": "", "quote": "", "gap": "x"},
        {"text": "Your costs were $8,000", "kind": "fact", "source_id": "", "quote": "", "gap": "x"}]})
    out, meta = _finalize(draft, raw)
    assert "$9,000" not in out and "$8,000" not in out
    assert meta["status"] == "withheld"
