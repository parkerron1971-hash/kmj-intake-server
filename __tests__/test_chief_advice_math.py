"""
test_chief_advice_math.py — the owner's numbers and the math on advice (2026-09-24).

Live: "What should I charge per seat for a two-day coaching intensive, and
how would you fill 12 seats by November?" → withheld `claim number has no
evidence :: Twelve seats gets you $8,364` (12 asked × $697 recommended),
then the repair failed on `draft number 12 has no reviewed claim` — the 12
the owner asked for.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

ASK = {"conversation:current": {"kind": "conversation", "role": "user", "complete": True,
                                "text": "What should I charge per seat, and how would you fill 12 seats by November?"}}
REPLY = ("I'd price seats at $697. Twelve seats gets you $8,364. "
         "Fill the first half from people who already know your work.")


def _review(*claims):
    return json.dumps({"verdict": "supported", "claims": list(claims)})


def _unsourced(text):
    return {"text": text, "kind": "fact", "source_id": "", "quote": "", "gap": "projection"}


def test_the_projection_on_the_advice_is_not_a_fact_to_prove():
    raw = _review(_unsourced("Twelve seats gets you $8,364"))
    verdict, _, reason = truth.assess_review(raw, REPLY, ASK)
    assert "no evidence" not in reason and "has no reviewed claim" not in reason, reason


def test_the_owners_own_number_needs_no_claim():
    verdict, _, reason = truth.assess_review(_review(), REPLY, ASK)
    assert "draft number 12" not in reason, reason


def test_arithmetic_never_excuses_a_record_figure():
    reply = "I'd price seats at $75. Monica Walton owes $150."
    raw = _review(_unsourced("Monica Walton owes $150"))
    verdict, _, reason = truth.assess_review(raw, reply, ASK)
    assert verdict == "unsupported" and "no evidence" in reason, reason


def test_a_figure_no_arithmetic_explains_is_still_held():
    raw = _review(_unsourced("Twelve seats gets you $9,999"))
    verdict, _, reason = truth.assess_review(raw, REPLY.replace("8,364", "9,999"), ASK)
    assert verdict == "unsupported"
