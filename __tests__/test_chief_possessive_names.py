"""
test_chief_possessive_names.py — "Monica's" is Monica's record (2026-10-18).

Replaying 25 recorded advice answers with the review on Haiku 5.5, "Monica's
$1,200 invoice is overdue" was held as "claim number 1200 is not in the
quote" in both thinking settings: the reviewer quoted her invoice's status,
and the corroboration that should have found $1,200 on her invoice row
looked for the word "monica's", which no record holds. "Monica owes $1,200"
passed. The free sentence prover had the same blind spot, so a possessive
sentence about a record always went to the paid check.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

SOURCES = {
    "context:open_invoices": {"kind": "context", "complete": True, "text": json.dumps([
        {"number": "INV-010", "client": "Monica Walton", "total": 1200, "status": "overdue",
         "due_date": "2026-09-15"},
        {"number": "INV-011", "client": "Jordan Lee", "total": 150, "status": "sent",
         "due_date": "2026-10-10"}])},
}
STATUS_QUOTE = '"client": "Monica Walton"'


def _review(claim, quote=STATUS_QUOTE):
    return json.dumps({"verdict": "supported", "claims": [
        {"text": claim, "kind": "fact", "source_id": "context:open_invoices", "quote": quote}]})


@pytest.mark.parametrize("claim", [
    "Monica's $1,200 invoice is overdue",
    "Monica’s $1,200 invoice is overdue",          # the curly apostrophe models write
    "Monica Walton's $1,200 invoice is overdue",
])
def test_a_possessive_name_finds_her_own_record(claim):
    verdict, _, reason = truth.assess_review(_review(claim), claim + ".", dict(SOURCES))
    assert verdict == "supported", reason


@pytest.mark.parametrize("claim", [
    "Monica's $1,500 invoice is overdue",          # no record holds 1,500
    "Jordan's $1,200 invoice is overdue",          # 1,200 is Monica's, not Jordan's
])
def test_a_possessive_does_not_lend_someone_elses_figure(claim):
    quote = '"client": "Jordan Lee"' if "Jordan" in claim else STATUS_QUOTE
    verdict, _, reason = truth.assess_review(_review(claim, quote), claim + ".", dict(SOURCES))
    assert verdict == "unsupported" and "is not in the quote" in reason, reason


def test_the_free_prover_reads_a_possessive_too():
    assert truth.fast_lane("Monica's $1,200 invoice is overdue.", dict(SOURCES)) is not None
    assert truth.fast_lane("Jordan's $1,200 invoice is overdue.", dict(SOURCES)) is None
    assert truth.fast_lane("Monica's $1,500 invoice is overdue.", dict(SOURCES)) is None


def test_record_names_drop_the_possessive_and_contractions():
    assert truth._record_names(["Monica's", "James'", "O'Neil", "Let's", "Here's"]) == [
        "monica", "james", "o'neil"]
