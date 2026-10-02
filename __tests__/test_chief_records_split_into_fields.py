"""
test_chief_records_split_into_fields.py — a nested tool result is checked field by field (2026-09-23).

Live: "Which clients haven't heard from me in a while, and do any of them
owe me money?" → 47 s → "No action ran … try again?". Log: `claim number
60 is not in the quote :: Six contacts have gone quiet, all lapsed (60+
days silent)`. The growth report's own definitions say lapsed is "no
recorded contact for 60 or more days", but the result was one JSON item,
and one hedge in it ("Missing dates remain unknown") disqualified it all.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

REPORT = {
    "section": "client_health",
    "counts": {"at_risk": 2, "lapsed": 6},
    "lapsed": [{"name": "Monica Walton", "days_quiet": 124}, {"name": "Tasha Brown", "days_quiet": 71}],
    "definitions": {
        "at_risk": "Not lapsed, and health below 40 or no recorded contact for 30 or more days.",
        "lapsed": "Status inactive/churned, or no recorded contact for 60 or more days.",
        "history": "For someone never contacted, elapsed days start at contact creation. Missing dates remain unknown.",
    },
}
SOURCES = {"tool:growth_report": {"kind": "record", "complete": True, "text": json.dumps(REPORT)}}


def test_fields_are_items_and_a_hedge_stays_in_its_own_field():
    items = truth._record_items(json.dumps(REPORT))
    assert "counts.lapsed: 6" in items
    assert any(i.startswith("definitions.lapsed:") and "60 or more days" in i for i in items)
    assert any(i.startswith("lapsed: ") and "Monica Walton" in i for i in items)


def test_the_logged_claim_is_supported():
    claim = "Six contacts have gone quiet, all lapsed (60+ days silent)"
    raw = json.dumps({"verdict": "supported", "claims": [
        {"text": claim, "kind": "fact", "source_id": "tool:growth_report", "quote": '"lapsed": 6'}]})
    verdict, _, reason = truth.assess_review(raw, claim + ".", SOURCES)
    assert verdict == "supported", reason


def test_a_person_and_their_figure_still_share_one_element():
    items = truth._record_items(json.dumps(REPORT))
    prover = truth._SentenceProver(SOURCES)
    assert prover.prove("Monica Walton has been quiet 124 days.")[0]
    assert not prover.prove("Tasha Brown has been quiet 124 days.")[0]
