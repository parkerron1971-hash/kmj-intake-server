"""A form's name is not a figure.

2026-09-22: "Can we do a 990 form to fill out" was answered twice with
"No action ran in this request. I couldn't verify my proposed answer."
Railway: `reply review withheld (draft number 990 has no reviewed claim)`.
The reviewer (rightly) did not list "Form 990" as a claim, and the sweep
for unreviewed figures read the form's name as a quantity.
"""
from __future__ import annotations

import json
import pathlib
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth


@pytest.mark.parametrize("text", [
    "Yes, we can work through Form 990 together.",
    "Let's start the 990 form.",
    "You may qualify as a Section 501(c)(3) organization.",
    "That goes on Schedule 1.",
    "See Publication 15 for payroll.",
    "Form 990-EZ or 990-N may fit better.",
    "I can prepare a 1099 form for the contractor.",
])
def test_a_document_name_carries_no_figure(text):
    assert truth._numbers(text) == set()


@pytest.mark.parametrize("text, expected", [
    ("You have 2 forms on file.", {Decimal(2)}),
    ("3 forms were submitted this week.", {Decimal(3)}),
    ("The invoice is $990.", {Decimal(990)}),
    ("990 people signed up.", {Decimal(990)}),
])
def test_a_real_quantity_still_counts(text, expected):
    assert truth._numbers(text) == expected


def test_the_990_reply_that_walled_now_passes():
    reply = ("Yes, we can put together Form 990 for the nonprofit. "
             "Tell me the fiscal year and I'll walk you through each part.")
    sources = {'conversation:current': {'kind': 'conversation', 'role': 'user',
                                         'text': 'Can we do a 990 form to fill out', 'complete': True},
               'turn:execution': {'kind': 'record', 'text': 'No action ran in this request.', 'complete': True}}
    raw = json.dumps({"verdict": "supported", "claims": []})
    verdict, _, reason = truth.assess_review(raw, reply, sources)
    assert verdict == 'supported', reason


def test_a_made_up_amount_beside_a_form_name_is_still_caught():
    reply = "Form 990 shows you raised $48,000 last year."
    raw = json.dumps({"verdict": "supported", "claims": []})
    verdict, _, reason = truth.assess_review(raw, reply, {})
    assert verdict == 'unsupported'
    assert '48000' in reason
