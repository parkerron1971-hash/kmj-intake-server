"""
test_chief_spoken_counts.py — counts in words are checked, so record answers can stream (2026-09-23).

Live retest: "Which of my invoices are overdue…" answered right in 16 s,
but nothing streamed — "Five invoices are overdue right now, totaling
$265." is a sentence about the state of a record, and those were never
streamable. With the invoice summary on file it is provable, IF the
spelled "Five" is checked too: "Six invoices … $265" must never pass.

A state sentence now streams (or skips review) only when every figure —
spelled counts included — and its key words (invoices, overdue,
appointments) sit in one record item; a count must be a count in that
record (not its clock hour or a date's day); a sample or capped list
proves no count; and rankings, "nothing", "none", "only", "all" stay
with the reviewer.
"""
from __future__ import annotations

import json
import pathlib
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

SUMMARY = ["As of 2026-09-24: 5 invoices overdue, $265.00 in total (sent and past their due date; drafts are not overdue).",
           "Monica Walton owes $150.00 across 1 invoice, $150.00 of it overdue (1 invoice).",
           "Kevin McCloud owes $115.00 across 4 invoices, $115.00 of it overdue (4 invoices)."]
ROWS = [{"number": "INV-2026-007", "client": "Monica Walton", "total": 150.0, "status": "sent",
         "due_date": "2026-07-15", "days_overdue": 71}]
SESSIONS = [{"title": "Knotless Braids", "scheduled_for": "2026-09-24T15:00:00+00:00",
             "contacts": {"name": "Tasha Brown"}}]
SOURCES = {
    "context:invoice_summary": {"kind": "context", "text": json.dumps(SUMMARY)},
    "context:open_invoices": {"kind": "context", "text": json.dumps(ROWS)},
    "context:sessions": {"kind": "context", "text": json.dumps(SESSIONS)},
    "context:contacts_total": {"kind": "context", "text": "11"},
    "tool:contacts": {"kind": "record", "text": "Exact contacts total: 725. Loaded sample: 500."},
}


@pytest.fixture
def prover():
    return truth.stream_prover(SOURCES, ZoneInfo("America/Detroit"))


@pytest.mark.parametrize("sentence", [
    "Five invoices are overdue right now, totaling $265.",
    "5 invoices are overdue, $265 in total.",
    "Kevin McCloud owes $115 across four invoices.",
    "Monica Walton owes $150, now seventy-one days overdue.",
    "Your next appointment is September 24 at 11am with Tasha Brown.",
    "Pick one date this week.",
])
def test_record_backed_sentences_pass(prover, sentence):
    assert truth.streamable_sentence(prover, sentence), sentence


@pytest.mark.parametrize("sentence,why", [
    ("Six invoices are overdue right now, totaling $265.", "a spelled count the record contradicts"),
    ("Kevin McCloud owes $115 across three invoices.", "wrong spelled count"),
    ("You have 11 appointments this week.", "11 is the clock hour, not a count"),
    ("You have 24 invoices overdue.", "24 is a date's day, not a count"),
    ("You have 500 contacts.", "500 is a loaded sample, not the total"),
    ("Monica Walton owes the most, $150.", "a ranking the record cannot prove"),
    ("No invoices are overdue.", "nothing to count"),
    ("Cash on hand is about eleven dollars.", "cash is in no trusted record"),
])
def test_what_one_record_does_not_prove_is_held(prover, sentence, why):
    assert not truth.streamable_sentence(prover, sentence), why


def test_the_review_skip_lane_uses_the_same_proof():
    reply = "Five invoices are overdue right now, totaling $265. Kevin McCloud owes $115 across four invoices."
    assert truth.fast_lane(reply, SOURCES, ZoneInfo("America/Detroit")) is not None
    assert truth.fast_lane(reply.replace("Five", "Six"), SOURCES, ZoneInfo("America/Detroit")) is None


@pytest.mark.parametrize("text,expected", [
    ("Pick one date this week.", "Pick one date this week."),
    ("Kevin has four small overdue invoices.", "Kevin has 4 small overdue invoices."),
    ("about eleven dollars", "about 11 dollars"),
    ("ninety-six days past due", "96 days past due"),
    ("the one worth a call", "the one worth a call"),
    ("one of your clients", "one of your clients"),
])
def test_only_number_words_that_count_something_become_digits(text, expected):
    assert truth._counts_as_digits(text) == expected
