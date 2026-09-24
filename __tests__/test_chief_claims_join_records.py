"""
test_chief_claims_join_records.py — one sentence can join two records (2026-09-23).

Live: "What does my schedule look like this week, and which clients haven't
heard from me in a while?" → 62 s → "No action ran … try again?". Log:
`claim number 150 is not in the quote :: Monica Walton, 124 days, and she's
the one carrying $150 overdue` — her contact row (124 days) and her invoice
row ($150) are two records; one quote can hold only one.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

SOURCES = {
    "context:contacts_lookup": {"kind": "context", "text": json.dumps([
        {"name": "Monica Walton", "status": "active", "days_since_contact": 124},
        {"name": "Tasha Brown", "status": "lead", "days_since_contact": 40}])},
    "context:open_invoices": {"kind": "context", "text": json.dumps([
        {"number": "INV-2026-007", "client": "Monica Walton", "total": 150.0, "status": "sent",
         "due_date": "2026-07-15", "days_overdue": 71}])},
}
CLAIM = "Monica Walton, 124 days, and she's the one carrying $150 overdue"


def _review(claim, quote='"name": "Monica Walton", "status": "active", "days_since_contact": 124'):
    return json.dumps({"verdict": "supported", "claims": [
        {"text": claim, "kind": "fact", "source_id": "context:contacts_lookup", "quote": quote}]})


def test_the_logged_claim_is_corroborated_by_her_invoice():
    verdict, _, reason = truth.assess_review(_review(CLAIM), CLAIM + ".", SOURCES)
    assert verdict == "supported", reason


@pytest.mark.parametrize("claim", [
    "Monica Walton, 124 days, and she's the one carrying $200 overdue",   # no record holds 200
    "Tasha Brown, 124 days, and she's the one carrying $150 overdue",     # 150 is Monica's, not Tasha's
])
def test_a_figure_from_someone_elses_record_still_fails(claim):
    quote = '"name": "Tasha Brown", "status": "lead", "days_since_contact": 40' if "Tasha" in claim else None
    raw = _review(claim, quote) if quote else _review(claim)
    verdict, _, reason = truth.assess_review(raw, claim + ".", SOURCES)
    assert verdict == "unsupported" and "is not in the quote" in reason, reason


def test_a_claim_that_names_nothing_is_not_corroborated_by_a_stray_number():
    claim = "about 150 of them"
    verdict, _, reason = truth.assess_review(_review(claim), claim + ".", SOURCES)
    assert verdict == "unsupported"
