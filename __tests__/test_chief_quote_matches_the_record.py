"""
test_chief_quote_matches_the_record.py — a fair quote of one record counts (2026-09-23).

Live retest after #1002: "Which of my invoices are overdue right now, and
who owes me the most?" → 41 s → "No action ran … try again?". The log:
`quote is not in the cited source :: INV-2026-010 · Kevin McCloud · $5 ·
96 days overdue`. The reviewer cited the right invoice in its own words;
the record is JSON. A quote now counts when one item of the cited record
holds every word and figure of it. Verbatim is still required for the
practitioner's own words, and a quote that mixes records, changes a
figure, or flips a word still fails.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

ROWS = [
    {"id": "a", "number": "INV-2026-010", "client": "Kevin McCloud", "total": 5.0, "status": "sent",
     "due_date": "2026-06-20", "days_overdue": 96},
    {"id": "b", "number": "INV-2026-007", "client": "Monica Walton", "total": 150.0, "status": "sent",
     "due_date": "2026-07-15", "days_overdue": 71},
]
SOURCES = {"context:open_invoices": {"kind": "context", "complete": False, "text": json.dumps(ROWS)}}


def _review(claim, quote, sid="context:open_invoices"):
    return json.dumps({"verdict": "supported", "claims": [
        {"text": claim, "kind": "fact", "source_id": sid, "quote": quote}]})


def test_the_logged_quote_is_accepted():
    claim = "INV-2026-010 for Kevin McCloud, $5, is 96 days overdue"
    verdict, cited, reason = truth.assess_review(
        _review(claim, "INV-2026-010 · Kevin McCloud · $5 · 96 days overdue"), claim + ".", SOURCES)
    assert verdict == "supported", reason


@pytest.mark.parametrize("claim,quote", [
    ("Kevin McCloud owes $150", "Kevin McCloud · $150"),                   # figure from another row
    ("INV-2026-010 is 97 days overdue", "INV-2026-010 · 97 days overdue"),  # changed figure
    ("Monica Walton's invoice is paid", "Monica Walton · paid"),            # "paid" is not in "sent"
    ("Kevin's invoice is not overdue", "Kevin McCloud · not overdue"),      # a flipped word
])
def test_a_quote_the_record_does_not_hold_still_fails(claim, quote):
    verdict, _, reason = truth.assess_review(_review(claim, quote), claim + ".", SOURCES)
    assert verdict == "unsupported"
    assert "quote is not in the cited source" in reason


def test_the_practitioners_words_stay_verbatim():
    sources = {"conversation:current": {"kind": "conversation", "role": "user", "complete": True,
                                        "text": "Thursday I close at 5:30pm"}}
    claim = "You close at 5:30pm on Thursday"
    verdict, _, reason = truth.assess_review(
        _review(claim, "close Thursday 5:30pm", sid="conversation:current"), claim + ".", sources)
    assert verdict == "unsupported" and "quote is not in the cited source" in reason


def test_verbatim_still_works():
    claim = "Monica Walton's invoice is 71 days overdue"
    verdict, _, reason = truth.assess_review(
        _review(claim, '"client": "Monica Walton", "total": 150.0, "status": "sent", '
                       '"due_date": "2026-07-15", "days_overdue": 71'), claim + ".", SOURCES)
    assert verdict == "supported", reason


def test_a_repair_with_only_an_aside_unsourced_is_delivered_with_it_named():
    import asyncio
    from unittest.mock import AsyncMock
    calls = {"n": 0}

    async def reviewer(client, system, messages, **kw):
        calls["n"] += 1
        if calls["n"] == 1:   # first draft: a wrong figure -> withheld
            return _review("INV-2026-010 is 97 days overdue", "INV-2026-010 · 97 days overdue")
        return json.dumps({"verdict": "unsupported", "claims": [
            {"text": "INV-2026-010 is 96 days overdue", "kind": "fact",
             "source_id": "context:open_invoices", "quote": "INV-2026-010 · 96 days overdue"},
            {"text": "those look like your own test invoices", "kind": "fact",
             "source_id": "", "quote": "", "gap": "no source says they are tests"}]})

    repaired = "INV-2026-010 is 96 days overdue, but those look like your own test invoices."
    out, meta = asyncio.run(truth.finalize_reply(
        None, "INV-2026-010 is 97 days overdue.", ctx={"open_invoices": ROWS}, view_detail="",
        taken=[], message="what's overdue?", business_id="biz", reviewer=reviewer,
        repairer=AsyncMock(return_value=repaired)))
    assert out.startswith(repaired)
    assert "still unverified" in out and "try again" not in out
    assert meta["status"] == "caveated" and meta.get("recovered")
