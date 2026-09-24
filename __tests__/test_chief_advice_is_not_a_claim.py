"""
test_chief_advice_is_not_a_claim.py — Chief's recommendation is advice (2026-09-23).

Live retest: "What should I charge per seat for a two-day coaching
intensive, and how would you fill 12 seats by November?" → 46 s → "No
action ran … try again?". Log: `claim number has no evidence :: $797-$1,197
per seat range` — the price Chief RECOMMENDED — then a repair failed on
`claim number 2026 is not in the quote :: … in 2026`. A recommendation
cannot be proved, only given; a year said as a date is the clock.

Still checked: a recommendation leaning on a business figure ("below your
$1,500 Founders' Table", "since your 11 clients"), and a bare market
figure stated as fact (the factual eval's $175).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth


def _unsourced(claim):
    return json.dumps({"verdict": "unsupported", "claims": [
        {"text": claim, "kind": "fact", "source_id": "", "quote": "", "gap": "no source"}]})


@pytest.mark.parametrize("claim,reply", [
    ("$797-$1,197 per seat range",
     "For a two-day intensive I'd price seats in the $797-$1,197 per seat range."),
    ("price it at $900", "I would price it at $900 a seat."),
    ("Aim for 12 seats", "Aim for 12 seats and open a waitlist after that."),
])
def test_a_recommendation_is_delivered_as_said(claim, reply):
    verdict, _, reason = truth.assess_review(_unsourced(claim), reply, {})
    assert verdict == "supported", reason


@pytest.mark.parametrize("claim,reply", [
    ("below your $1,500 Founders Table", "I'd keep it below your $1,500 Founders Table."),
    ("since your 11 clients", "Charge $900 since your 11 clients already know you."),
    ("The current market rate is $175", "The current market rate is $175."),
])
def test_a_business_figure_or_a_bare_market_fact_is_still_checked(claim, reply):
    verdict, _, reason = truth.assess_review(_unsourced(claim), reply, {})
    assert verdict == "unsupported" and "no evidence" in reason, reason


def test_the_years_on_the_clock_are_not_figures_to_prove():
    this = dt.date.today().year
    claim = f"most coaching packages in {this} are sold as three-month programs"
    verdict, _, reason = truth.assess_review(_unsourced(claim), claim + ".", {})
    assert "no evidence" not in reason, reason
    far = f"coaching in {this - 10} averaged $200"
    verdict, _, reason = truth.assess_review(_unsourced(far), far + ".", {})
    assert "no evidence" in reason


def test_a_recommendations_figures_need_no_claim_of_their_own():
    reply = "Here's how I'd do it. I'd price seats at $797 and aim for 12 people."
    raw = json.dumps({"verdict": "supported", "claims": []})
    verdict, _, reason = truth.assess_review(raw, reply, {})
    assert verdict == "supported", reason


def test_anchoring_a_price_is_advice():
    # Live 9/24: "I'd anchor at $997 per seat" was listed as unverified.
    claim = "anchor at $997 per seat"
    reply = "Given your positioning, I'd anchor at $997 per seat."
    verdict, _, reason = truth.assess_review(_unsourced(claim), reply, {})
    assert verdict == "supported", reason
