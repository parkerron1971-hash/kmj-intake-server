"""
test_chief_advice_gets_through.py — asked for thoughts, Chief's advice
reaches the practitioner (2026-09-28).

Kevin: "if people are asking for thoughts it should give some level of
direction advice that can really be helpful." Fifteen advice questions run
live on Sonnet 5.5, twice: 8 of 30 answers withheld whole ("No action ran …
try again?"), none clean. Every sentence below is from those drafts. None
was a false figure about the business; each was the advice itself.

Still checked, and pinned here too: anything about the records (what they
have, what came in, what is owed, a named client), and a bare statement
with no advice in it.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

RECORDS = {"context:contacts_lookup": {"kind": "context", "complete": False, "text": json.dumps(
    [{"name": "Marcus Reed", "status": "active"}, {"name": "Monica Walton", "status": "active"},
     {"name": "Ada Lovelace", "status": "lead"}])},
           "context:offerings": {"kind": "context", "complete": False, "text": json.dumps(
    [{"name": "Founders Table", "price": 1500}])}}


def _unsourced(text, kind="fact"):
    return json.dumps({"verdict": "unsupported", "claims": [
        {"text": text, "kind": kind, "source_id": "", "quote": "", "gap": "no source"}]})


def _verdict(text, reply=None, kind="fact"):
    reply = reply or text
    return truth.assess_review(_unsourced(text, kind), reply, RECORDS)


# ── advice goes through ────────────────────────────────────────────────

@pytest.mark.parametrize("sentence", [
    # plan math
    "Five clients usually takes about 10 to 15 discovery calls.",
    "If a third of discovery calls turn into clients, that's 18 calls a month, or about 4 a week.",
    "Selling single sessions at $200, you'd need 50 sessions a month.",
    "Discovery calls per week = ($10k ÷ average client value) ÷ close rate ÷ 4.3 weeks.",
    # a suggested policy
    "Ask for 24 hours' notice, and charge the full session inside that window.",
    # general know-how worded as such
    "Most coaching packages run six to eight sessions.",
    # general know-how with no figure, not about the business
    "Warm contacts convert far better than cold ones.",
])
def test_advice_sentences_are_delivered_as_said(sentence):
    verdict, _, reason = _verdict(sentence.rstrip("."), sentence)
    assert verdict == "supported", reason


@pytest.mark.parametrize("sentence", [
    "I can draft a short invitation to Ada for a discovery call.",
    "I can put the three blocks on your calendar as recurring reminders.",
    "I can create the package in your catalog.",
    "I can also set this as a tracked assignment, five new contacts by October 28.",
])
def test_an_offer_of_work_is_not_a_claim(sentence):
    verdict, _, reason = _verdict(sentence.rstrip("."), sentence)
    assert verdict == "supported", reason


def test_a_plans_own_shape_is_not_a_figure_to_prove():
    reply = ("Here's the plan.\n\n**Week 1: Build the base.** Set up the Discovery Call.\n"
             "**Weeks 2-3:** reach out to 10 people a week.\n"
             "- **Monday to Thursday, 40 minutes:** reach out to people.\n"
             "What do you want the business to do in the next 90 days?")
    verdict, _, reason = truth.assess_review(json.dumps({"verdict": "supported", "claims": []}), reply, RECORDS)
    assert verdict == "supported", reason


# ── the records keep the full check ────────────────────────────────────

@pytest.mark.parametrize("sentence", [
    "Revenue was about $900,000.",                  # a record noun stated as fact, hedge or not
    "We made about $4,000 in September.",           # the business's own past
    "You have 12 clients who haven't booked.",
    "Monica Walton owes $150.",                     # a named client
    "The 90-day group cohort sells at $750 per month.",   # a bare statement, no advice in it
    "The current market rate is $175.",
    "Twelve seats gets you $9,999.",
    "I can send Monica's $150 reminder now.",       # an offer carrying money
    "Most of them are active.",                     # "them" is the records, not a general group
    "Many of your clients pay late.",
    "Your workshop would typically sell at $500 a seat.",
    "Similar invoices usually total $400.",
])
def test_a_claim_about_the_records_still_needs_its_record(sentence):
    verdict, _, reason = _verdict(sentence.rstrip("."), sentence)
    assert verdict == "unsupported", (sentence, reason)


def test_a_benchmark_with_figures_is_delivered_labeled_not_silent():
    # 2026-09-23: benchmarks reach the owner marked as general knowledge.
    for text, kind in (("Many coaches land somewhere around 30 to 50 percent", "reference"),
                       ("Similar two-day intensives typically run $800 to $1,500 a seat", "fact")):
        verdict, _, reason = _verdict(text, text + ".", kind)
        assert reason.startswith("general rule"), (text, reason)


def test_a_bare_public_rule_keeps_its_official_source_label():
    rule = "The 990-N is for gross receipts of $50,000 or less"
    verdict, _, reason = _verdict(rule, rule + ".", kind="reference")
    assert verdict == "unsupported" and reason.startswith("general rule"), reason


def test_a_plan_figure_in_a_record_sentence_is_still_swept():
    reply = "You have 12 clients. Week 1: reach out to them."
    verdict, _, reason = truth.assess_review(json.dumps({"verdict": "supported", "claims": []}), reply, RECORDS)
    assert verdict == "unsupported" and "12" in reason, reason


# ── a long answer is cut, not withheld ─────────────────────────────────

ADVICE = ("Start with the people who already know you, because a warm yes is the fastest first sale. "
          "Build one clear offer and a booking link so every conversation has somewhere to go. "
          "Then block two mornings a week for outreach and keep a simple list of who you talked to. "
          "Ask each happy client for one introduction, and thank them when it turns into a call. ") * 3


def test_a_question_turn_gets_more_cuts_before_it_is_given_up():
    bad = " ".join(f"There are {n} contacts in group {chr(65 + i)}." for i, n in enumerate((901, 902, 903, 904, 905)))
    draft = bad + " " + ADVICE
    raw = json.dumps({"verdict": "supported", "claims": []})
    out, meta = asyncio.run(truth.finalize_reply(
        None, draft, ctx={}, view_detail="", taken=[], message="How do I get more clients?",
        business_id="biz", reviewer=AsyncMock(return_value=raw),
        repairer=AsyncMock(side_effect=AssertionError("no repair needed"))))
    assert meta["status"] == "trimmed", meta
    assert "901" not in out and "905" not in out and "warm yes" in out


# ── the doubt list names only what is still in doubt ───────────────────
# Live advice eval, 2026-09-28: answers caveated for one real doubt listed
# the cleared advice too ("If about one in three discovery calls becomes a
# client, five clients means roughly 12 to 15 calls" under "still
# unverified"), undoing on screen what the verdict had decided.

def test_a_caveat_lists_the_real_doubt_and_not_the_cleared_advice():
    plan = "If about one in three discovery calls becomes a client, five clients means roughly 12 to 15 calls."
    offer = "I can set this up as a tracked goal, so it shows on your dashboard each week."
    doubt = "The capacity report wouldn't load."
    draft = f"{plan} {offer} {doubt}"
    raw = json.dumps({"verdict": "unsupported", "claims": [
        {"text": t.rstrip("."), "kind": "fact", "source_id": "", "quote": "", "gap": "no source"}
        for t in (plan, offer, doubt)]})
    out, meta = asyncio.run(truth.finalize_reply(
        None, draft, ctx={}, view_detail="", taken=[], message="How do I get five clients?",
        business_id="biz", reviewer=AsyncMock(return_value=raw)))
    assert meta["status"] == "caveated", meta
    assert meta["gaps"] == [doubt.rstrip(".")], meta["gaps"]
    assert out.startswith(draft)


# ── planning math on a real record ─────────────────────────────────────
# Live advice eval (2026-09-28): two answers withheld whole over
# "estimate without an explicit label" — planning math the reviewer tied to
# the $1,200 package, hedged with "if" and "works out to" rather than
# "roughly".

PACKAGE = {"context:offerings": {"kind": "context", "complete": False,
                                  "text": json.dumps([{"name": "3-Month Coaching Package", "price": 1200}])}}


def _estimate(text, quote="1200"):
    return json.dumps({"verdict": "supported", "claims": [
        {"text": text, "kind": "estimate", "source_id": "context:offerings", "quote": quote}]})


def test_conditional_planning_math_on_a_record_labels_itself():
    for text in ("If the package includes 12 weekly sessions, you're charging $100 per session",
                 "Your $1200 package, spread over three months, which works out to about $400 a month"):
        verdict, _, reason = truth.assess_review(_estimate(text), text + ".", PACKAGE)
        assert verdict == "supported", (text, reason)


def test_an_unlabeled_estimate_is_cut_not_the_whole_answer():
    bad = "The package nets $950 after costs"
    draft = bad + ". " + ADVICE
    raw = _estimate(bad)
    out, meta = asyncio.run(truth.finalize_reply(
        None, draft, ctx={}, view_detail="", taken=[], message="How's my package doing?",
        business_id="biz", reviewer=AsyncMock(return_value=raw)))
    assert "$950" not in out and "warm yes" in out, meta
    assert meta["status"] in ("trimmed", "caveated"), meta
