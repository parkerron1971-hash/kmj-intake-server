"""
test_chief_duration_units.py — the answer check reads durations and units (2026-09-23).

A stylist entered her service menu by voice. The receipts said
"Created offering: Kids Small Box Braids at $70.0 (300 min)"; Chief's
replies said "$70, 5 hours". The quote held 300, the draft said 5, and
the reply was withheld as "claim number 5 is not in the quote". Seven of
twenty-four replies that evening came back as "No action ran in this
request... Would you like me to try again?" and she asked again each
time. A duration is the same figure in minutes or hours, a measure with
its unit glued on ("54in") is still a number, and a figure the
practitioner said herself is not one Chief made up.
"""
from __future__ import annotations

import json
import pathlib
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth


def _review(text, quote, sid="result:0", kind="action"):
    return json.dumps({"verdict": "supported",
                       "claims": [{"text": text, "kind": kind, "source_id": sid, "quote": quote}]})


def _receipt(label):
    return {"result:0": {"kind": "receipt", "complete": True,
                         "text": json.dumps({"type": "create_offering", "result": "created", "label": label},
                                            ensure_ascii=False)}}


@pytest.mark.parametrize("text,twins", [
    ("(360 min)", {Decimal(6)}),
    ("(150 min)", {Decimal("2.5")}),
    ("90 minutes", {Decimal("1.5")}),
    ("2.5 hours", {Decimal(150)}),
    ("6 hrs", {Decimal(360)}),
    ("1 hour", {Decimal(60)}),
    ("20 min", set()),          # 0.333 hours is not a figure anyone says
    ("$90 for 360 clients", set()),
])
def test_a_duration_can_be_said_in_the_other_unit(text, twins):
    assert truth._duration_twins(text) == twins


@pytest.mark.parametrize("text,expected", [
    ("54in Hair", ["54"]),
    ("(360min)", ["360"]),
    ("2hrs", ["2"]),
    ("INV-2026-007 for $150", ["150"]),
    ("hash a54in9", []),
])
def test_a_unit_glued_to_a_number_is_still_a_number(text, expected):
    assert truth._figures(text) == expected


# The drafts the log recorded as withheld on 2026-09-23, against the
# receipt each was checked against.
@pytest.mark.parametrize("draft,claim,label", [
    ("Kids Small Box Braids, $70, 5 hours, saved.",
     "Kids Small Box Braids, $70, 5 hours, saved.",
     "Created offering: Kids Small Box Braids at $70.0 (300 min)"),
    ("Added — Natural Hair Two-Strand Twists at $50, 2.5 hours.",
     "Added — Natural Hair Two-Strand Twists at $50, 2.5 hours.",
     "Created offering: Natural Hair Two-Strand Twists at $50.0 (150 min)"),
    ("Tribal Braids with Knotless in the Back and Fulani Braids, each $90 at 6 hours.",
     "Tribal Braids with Knotless in the Back and Fulani Braids, each $90 at 6 hours",
     "Created offering: Tribal Braids with Knotless in the Back at $90.0 (360 min)"),
    ("Adult Medium Knotless Braids (54 inch hair) — $90, 6 hours base.",
     "Adult Medium Knotless Braids (54 inch hair) — $90, 6 hours base",
     "Created offering: Adult Medium Knotless Braids (54in Hair) at $90.0 (360 min)"),
])
def test_hours_in_the_draft_match_minutes_in_the_receipt(draft, claim, label):
    verdict, cited, reason = truth.assess_review(_review(claim, label), draft, _receipt(label))
    assert verdict == "supported", reason
    assert cited == ["result:0"]


def test_a_wrong_duration_is_still_caught():
    # Seen the same evening and rightly withheld: natural hair was $30 at
    # 150 min, the draft said $40 at 2 hours.
    label = "Created offering: Kids Braided Hairstyle - Natural Hair at $30.0 (150 min)"
    verdict, _, reason = truth.assess_review(
        _review("Kids braided with natural hair, $40, 2 hours", label),
        "Kids braided with natural hair, $40, 2 hours", _receipt(label))
    assert verdict == "unsupported"
    assert "is not in the quote" in reason


def _no_source_review(text):
    return json.dumps({"verdict": "unsupported", "claims": [
        {"text": text, "kind": "fact", "source_id": "", "quote": "", "gap": "no record of booking rules"}]})


def _conversation(user_text):
    return {"conversation:current": {"kind": "conversation", "role": "user",
                                     "text": user_text, "complete": True}}


def test_the_practitioners_own_figures_reach_her_named_as_unverified():
    user = ("Depending on the styles for Thursday. If it is a 2 hour appointment it need to be "
            "booked no later than 3:30pm because I need to be done at 5:30pm.")
    claim = "A 2-hour style simply won't show as bookable after 3:30 pm on Thursdays"
    verdict, _, reason = truth.assess_review(_no_source_review(claim), claim + ".", _conversation(user))
    assert verdict == "unsupported"
    assert reason.startswith("claim without support"), reason
    assert truth.unconfirmed_claims(_no_source_review(claim), reason) == [claim]


def test_figures_said_in_words_count_as_hers():
    user = "if I get someone to book a two-hour hair appointment at 3:30, I still have to be done by 5:30"
    claim = "a 2 hour style wouldn't appear as bookable any later than 3:30pm"
    verdict, _, reason = truth.assess_review(_no_source_review(claim), claim, _conversation(user))
    assert reason.startswith("claim without support"), reason


def test_a_figure_she_never_said_is_still_withheld():
    user = "When is my Thursday cutoff?"
    claim = "Your last Thursday booking is at 3:30 pm"
    verdict, _, reason = truth.assess_review(_no_source_review(claim), claim, _conversation(user))
    assert verdict == "unsupported"
    assert reason.startswith("claim number has no evidence"), reason


def test_her_figures_do_not_loosen_a_record_backed_claim():
    # She says $50; the invoice says $40. Chief agreeing with her against
    # the record is exactly what the check exists to stop.
    sources = {**_conversation("I charged her $50, right?"),
               "record:0": {"kind": "record", "complete": True, "text": "INV-2026-013 total 40.00"}}
    claim = "Yes, you charged her $50"
    verdict, _, reason = truth.assess_review(
        _review(claim, "INV-2026-013 total 40.00", sid="record:0", kind="fact"), claim, sources)
    assert verdict == "unsupported"
    assert "claim number 50 is not in the quote" in reason
