"""
test_chief_advice_numbers.py — Chief's own advice numbers are not business facts (2026-10-07).

Replaying 25 real advice answers through the answer check, 10 were held
back as "couldn't verify", on Sonnet and on Haiku alike. Four of those
were lost to numbers that are part of the advice itself:

- "If you have fewer than 3 by the end of week 1, outreach is the problem"
- "If you're clearing under about 30 percent, you're likely underpriced"
- "Below 25 percent usually means a qualification or offer-clarity issue"
- "for example one free reschedule with 24 hours' notice"
- "At a 40 percent conversion rate, five packages needs about 12 discovery calls"

One more was a count the answer proved itself: "You have 3 sessions this
week (Marcus, Priya, Chris)", with all three in the calendar.

Still checked: anything that names a person, states a record ("you have",
"overdue", "paid") or leans on a figure of theirs ("your $150 rate").
"""
from __future__ import annotations

import json
import pathlib
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth


def _unsourced(claim):
    return json.dumps({"verdict": "unsupported", "claims": [
        {"text": claim, "kind": "fact", "source_id": "", "quote": "", "gap": "no source"}]})


ADVICE = [
    "If you have fewer than 3 by the end of week 1, outreach is the problem, and that's the lever to change.",
    "If you're clearing under about 30 percent, you're likely underpriced even if jobs feel busy.",
    "Below 25 percent usually means a qualification or offer-clarity issue.",
    "Don't judge it on fewer than about 8 calls.",
    "Aim to have next week's calendar at least 80% full by Friday.",
    "**Client engagement.** Count how many active clients you've had real contact with in the last 14 days.",
    "Then set a clear but humane policy, for example one free reschedule with 24 hours' notice, "
    "and later changes count as a used session or carry a fee.",
    "At a 40 percent conversion rate, five packages needs about 12 discovery calls a month.",
]

FACTS = [
    "You have fewer than 3 clients right now.",
    "Send Ada a reminder, she is 14 days late.",
    "Your revenue is under 30 percent of last year.",
    "If Ada pays her $450 by Friday, you clear 80% of the month.",
    "Over 90 days, revenue was $4,200.",
    "Keep your $150 rate for the 5 clients you have.",
    "Below 25 percent of your clients rebooked last month.",
]


@pytest.mark.parametrize("sentence", ADVICE)
def test_an_advice_number_is_delivered_as_said(sentence):
    claim = sentence.split(",")[0].replace("**Client engagement.** ", "")
    verdict, _, reason = truth.assess_review(_unsourced(claim), sentence, {})
    assert "no evidence" not in reason, reason


@pytest.mark.parametrize("sentence", ADVICE)
def test_an_advice_number_no_claim_covered_is_not_held(sentence):
    review = json.dumps({"verdict": "supported", "claims": []})
    verdict, _, reason = truth.assess_review(review, sentence, {})
    assert "has no reviewed claim" not in reason, reason


@pytest.mark.parametrize("sentence", FACTS)
def test_a_business_figure_is_still_checked(sentence):
    assert truth._advice_parameters(sentence) == set()
    verdict, _, reason = truth.assess_review(_unsourced(sentence.rstrip(".")), sentence, {})
    assert verdict == "unsupported", reason


def test_a_count_the_answer_lists_by_name_checks_against_the_record():
    sources = {"context:sessions": {"kind": "context", "complete": True, "text": json.dumps({"rows": [
        {"title": "Session with Marcus Reed"}, {"title": "Session with Priya Shah"},
        {"title": "Session with Chris Park"}]})}}
    reply = "You have 3 sessions this week (Marcus, Priya, Chris)."
    review = json.dumps({"verdict": "supported", "claims": [
        {"text": "You have 3 sessions this week (Marcus, Priya, Chris)", "kind": "fact",
         "source_id": "context:sessions", "quote": "Session with Marcus Reed"}]})
    verdict, _, reason = truth.assess_review(review, reply, sources)
    assert verdict == "supported", reason


@pytest.mark.parametrize("claim", [
    "You have 4 sessions this week (Marcus, Priya, Chris)",     # count does not match the names
    "You have 3 sessions this week (Marcus, Priya, Dana)",      # Dana is not on the calendar
])
def test_a_listed_count_that_does_not_add_up_is_still_held(claim):
    sources = {"context:sessions": {"kind": "context", "complete": True, "text": json.dumps({"rows": [
        {"title": "Session with Marcus Reed"}, {"title": "Session with Priya Shah"},
        {"title": "Session with Chris Park"}]})}}
    review = json.dumps({"verdict": "supported", "claims": [
        {"text": claim, "kind": "fact", "source_id": "context:sessions", "quote": "Session with Marcus Reed"}]})
    verdict, _, reason = truth.assess_review(review, claim + ".", sources)
    assert verdict == "unsupported", reason


def test_enumerated_count_reads_only_a_list_of_names():
    src = "Session with Marcus Reed / Priya Shah / Chris Park"
    assert truth._enumerated_count(Decimal(3), "3 sessions (Marcus, Priya and Chris)", src)
    assert not truth._enumerated_count(Decimal(3), "3 sessions this week", src)
