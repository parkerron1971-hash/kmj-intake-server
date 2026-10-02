"""
test_chief_checker_sees_offerings.py — the answer check reads what the business sells (2026-09-24).

Live: pricing advice quoting "the 90-day individual intensive at $3,000"
and "the Group Cohort at $750" — both active offerings — was withheld as
"claim number has no evidence": the offerings table never reached Chief's
context records or the review evidence.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

OFFERINGS = [{"name": "Individual 90-Day Intensive", "price": 3000.0, "category": "package"},
             {"name": "Group Cohort (90 Days)", "price": 750.0, "category": "package"}]
FAT = {k: "x" * 10000 for k in ("blueprint_block", "playbook_block", "brand_block", "voice_block",
                                 "foundation_block", "practitioner_block")}


def test_offerings_reach_the_evidence_and_survive_a_full_context():
    sources = truth.evidence_for_review({**FAT, "offerings": OFFERINGS}, "", [])
    assert "context:offerings" in sources and "3000" in sources["context:offerings"]["text"]


def test_the_withheld_claim_is_supported_by_the_offering():
    sources = truth.evidence_for_review({"offerings": OFFERINGS}, "", [])
    claim = "the Individual 90-Day Intensive at $3,000"
    raw = json.dumps({"verdict": "supported", "claims": [
        {"text": claim, "kind": "fact", "source_id": "context:offerings",
         "quote": "Individual 90-Day Intensive · $3,000"}]})
    verdict, _, reason = truth.assess_review(raw, "Price it under " + claim + ".", sources)
    assert verdict == "supported", reason


def test_the_fast_lane_can_prove_an_offering_price():
    sources = truth.evidence_for_review({"offerings": OFFERINGS}, "", [])
    assert truth.fast_lane("Your Group Cohort is $750.", sources) is not None
    assert truth.fast_lane("Your Group Cohort is $900.", sources) is None


def test_the_academy_track_is_evidence_too():
    track = {"pricing_strategy": {"tiers": [{"name": "Intensive", "price": 3000}]}}
    sources = truth.evidence_for_review({"strategy_track": track}, "", [])
    assert "context:strategy_track" in sources
