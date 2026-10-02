"""
test_chief_says_it_once.py — two walls from 2026-09-23.

1. Kevin asked Chief to void three test invoices. The reply read the same
   hold sentence three times ("Before I void invoice I need your spoken
   go-ahead ..." x3), and the next turn read a 60-word security paragraph
   three times. Each reason is now said once, with how many it covers.

2. Asked for a better price for a two-day intensive, every draft with a
   benchmark in it ("similar intensives run $800-$1,500 a seat", "a coach
   charging $300 an hour might price a workshop at $75-$120") was withheld
   as "claim number has no evidence" and she heard "No action ran ... try
   again?". A hedged figure about the world, not the business, is delivered
   labeled as general knowledge. A bare market figure and anything about
   the business's records still has to be proved.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import chief_truth as truth

HOLD = {"type": "void_invoice", "result": "Failed: HELD FOR A SPOKEN YES ...", "failed": True,
        "needs_confirmation": True,
        "label": "Before I void invoice I need your spoken go-ahead — nothing has run yet. "
                 "Say \"go ahead\" or \"send it\" and I will do it."}
TAINT = {"type": "void_invoice", "failed": True, "label": "Held: void invoice (suspicious content in inbox)",
         "result": "Failed: I held this one. A message in your inbox contained text shaped like an "
                   "instruction to me. I ignored the instruction."}


def test_three_identical_holds_are_read_back_once():
    reply = cos._deterministic_fallback_reply([dict(HOLD), dict(HOLD), dict(HOLD)])
    assert reply.count("I need your spoken go-ahead") == 1
    assert "(3 of them)" in reply


def test_three_identical_failures_give_the_reason_once():
    reply = cos._deterministic_fallback_reply([dict(TAINT), dict(TAINT), dict(TAINT)])
    assert reply.count("A message in your inbox") == 1
    assert "×3" in reply and reply.startswith("3 actions didn't go through")


def test_different_reasons_are_each_still_said():
    other = {"type": "send_invoice", "failed": True, "result": "Failed: no email on file", "label": ""}
    reply = cos._deterministic_fallback_reply([dict(TAINT), dict(TAINT), other])
    assert "A message in your inbox" in reply and "no email on file" in reply


def _unsourced(text, kind="fact"):
    return json.dumps({"verdict": "unsupported", "claims": [
        {"text": text, "kind": kind, "source_id": "", "quote": "", "gap": "no source"}]})


@pytest.mark.parametrize("claim", [
    "Similar two-day intensives are typically benchmarked at $800–$1,500 per seat",
    "A coach charging $300 an hour might price a group workshop at $75 to $120 per person",
])
def test_a_hedged_benchmark_is_delivered_labeled(claim):
    verdict, _, reason = truth.assess_review(_unsourced(claim), claim + ".", {})
    assert reason.startswith("general rule"), reason
    assert truth.reference_claims(_unsourced(claim), reason) == [claim]


@pytest.mark.parametrize("claim", [
    "The current market rate is $175",                    # bare assertion (factual eval)
    "Revenue was roughly $900,000",                        # a record, however hedged
    "Your workshop would typically sell at $500 a seat",   # about the business
    "Similar invoices usually total $400",                 # a record noun
])
def test_unhedged_or_business_figures_still_need_evidence(claim):
    verdict, _, reason = truth.assess_review(_unsourced(claim), claim + ".", {})
    assert verdict == "unsupported"
    assert reason.startswith("claim number has no evidence"), reason
