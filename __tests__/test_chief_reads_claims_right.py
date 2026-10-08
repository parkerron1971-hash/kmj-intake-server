"""
test_chief_reads_claims_right.py — three claims the answer check misfiled (2026-10-07 replay).

On 22 recorded advice answers, Haiku 5.5 as the reviewer held back 10 good
answers to Sonnet's 6. The extra ones were claims filed under the wrong
kind, which the code then judged by the wrong rule:

- "I couldn't pull the full Retention report just now" filed as an action
  (and withheld for want of a write receipt). It says something did NOT
  happen.
- "ask Pat Johnson, Omar King and Lee Wright whether they know a couple..."
  filed as an action. It is Chief telling the owner what to do.
- "about 10 discovery calls, if half of them convert" filed as an estimate
  and withheld as "estimate without an explicit label": the hedge is in its
  own sentence.

Still held: a first-person write with no receipt, and a count of their
records dressed as an estimate.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

EXEC = {"turn:execution": {"kind": "record", "text": "No action ran in this request.", "complete": True}}


def _review(*claims, verdict="unsupported"):
    return json.dumps({"verdict": verdict, "claims": list(claims)})


def _action(text, gap="no write receipt"):
    return {"text": text, "kind": "action", "source_id": "", "quote": "", "gap": gap}


def test_a_read_that_failed_is_not_an_action_claim():
    reply = "I couldn't pull the full Retention report just now, so this is from the list I have."
    verdict, _, reason = truth.assess_review(_review(_action("I couldn't pull the full Retention report just now")),
                                             reply, dict(EXEC))
    assert "action claim without a write receipt" not in reason, reason


def test_an_instruction_to_the_owner_is_not_an_action_claim():
    text = "ask Pat Johnson, Omar King and Lee Wright whether they know a couple who would benefit"
    reply = "This week, " + text + "."
    verdict, _, reason = truth.assess_review(_review(_action(text)), reply, dict(EXEC))
    assert "action claim without a write receipt" not in reason, reason


def test_a_first_person_write_without_a_receipt_is_still_held():
    text = "I've sent Ada the invoice"
    verdict, _, reason = truth.assess_review(_review(_action(text)), text + ".", dict(EXEC))
    assert verdict == "unsupported" and "action claim without a write receipt" in reason, reason


SRC = {"context:offerings": {"kind": "context", "complete": True,
                             "text": json.dumps([{"name": "Discovery Call", "price": 0},
                                                 {"name": "3-Month Package", "price": 1200}])}}


def _estimate(text, quote='"price": 1200'):
    return {"text": text, "kind": "estimate", "source_id": "context:offerings", "quote": quote}


def test_an_estimate_hedged_in_its_own_sentence_is_labeled():
    reply = ("Five new clients in 30 days probably means about 10 discovery calls, "
             "if half of them convert.")
    verdict, _, reason = truth.assess_review(
        _review(_estimate("about 10 discovery calls, if half of them convert"), verdict="supported"),
        reply, dict(SRC))
    assert "estimate without an explicit label" not in reason, reason


def test_a_count_of_their_records_dressed_as_an_estimate_is_still_held():
    reply = "You have about 40 clients on file."
    verdict, _, reason = truth.assess_review(
        _review(_estimate("You have about 40 clients on file"), verdict="supported"), reply, dict(SRC))
    assert verdict == "unsupported", reason


def test_non_execution_reads_the_new_shapes():
    assert truth.is_non_execution_claim("I wasn't able to load your invoices")
    assert truth.is_non_execution_claim("I couldn't pull the report")
    assert not truth.is_non_execution_claim("I sent the invoice")


def test_owner_instruction_needs_no_subject():
    assert truth.is_owner_instruction("reach out personally to Ada and Sam")
    assert not truth.is_owner_instruction("I'll send Ada the invoice")
    assert not truth.is_owner_instruction("sent Ada the invoice")


# ── Two records in one claim (2026-10-08) ────────────────────────────
# "Your 1:1 Session is $150 and the 3-Month Package is $1,200" cites one
# quote; each figure is held to its own clause's record.

OFFERS = {"context:offerings": {"kind": "context", "complete": True, "text": json.dumps([
    {"name": "1:1 Coaching Session", "price": 150},
    {"name": "3-Month Coaching Package", "price": 1200}])}}


def _fact(text, quote):
    return {"text": text, "kind": "fact", "source_id": "context:offerings", "quote": quote}


def test_two_offerings_in_one_claim_each_check_against_their_own_record():
    text = "Your 1:1 Coaching Session is $150 and the 3-Month Coaching Package is $1,200"
    verdict, _, reason = truth.assess_review(
        _review(_fact(text, '"price": 150'), verdict="supported"), text + ".", dict(OFFERS))
    assert verdict == "supported", reason


def test_a_wrong_price_in_the_second_clause_is_still_held():
    text = "Your 1:1 Coaching Session is $150 and the 3-Month Coaching Package is $1,647"
    verdict, _, reason = truth.assess_review(
        _review(_fact(text, '"price": 150'), verdict="supported"), text + ".", dict(OFFERS))
    assert verdict == "unsupported" and "1647" in reason, reason


def test_a_price_moved_to_the_wrong_offering_is_still_held():
    text = "Your 1:1 Coaching Session is $1,200 and the 3-Month Coaching Package is $150"
    verdict, _, reason = truth.assess_review(
        _review(_fact(text, '"price": 150'), verdict="supported"), text + ".", dict(OFFERS))
    assert verdict == "unsupported", reason
