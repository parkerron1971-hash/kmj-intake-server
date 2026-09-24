"""
test_chief_advice_keeps_its_page.py — pricing advice beside an opened page (2026-09-23).

Live test: "help me think through pricing and how to fill the seats" →
Chief opened Strategy Track, the review withheld the draft (`claim number
8,15 is not in the quote :: the sweet spot for group size is 8-15
participants` — a ballpark the reviewer tried to cite), and because a
page had been opened, no repair ran: the whole reply was the page label.

A cited ballpark about the world is now labeled general knowledge like
an uncited one, and a turn that only opened a page still gets its answer
repaired — shown under the page label.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_truth as truth

NAV = {"type": "navigate", "result": "opened", "label": "Opened BUILD → strategy-track"}
CLAIM = "the sweet spot for group size is 8-15 participants"


def _cited_ballpark():
    return json.dumps({"verdict": "unsupported", "claims": [
        {"text": CLAIM, "kind": "fact", "source_id": "context:blueprint_block",
         "quote": "a two-day intensive for coaches"}]})


def test_a_cited_ballpark_is_general_knowledge_not_a_bad_citation():
    sources = {"context:blueprint_block": {"kind": "context", "text": "Plan a two-day intensive for coaches in November."}}
    verdict, _, reason = truth.assess_review(_cited_ballpark(), "Keep it small; " + CLAIM + ".", sources)
    assert reason.startswith("general rule"), reason
    assert truth.reference_claims(_cited_ballpark(), reason) == [CLAIM]


def test_a_cited_business_figure_is_still_a_bad_citation():
    raw = json.dumps({"verdict": "supported", "claims": [
        {"text": "your revenue is typically $900 a month", "kind": "fact",
         "source_id": "context:blueprint_block", "quote": "a two-day intensive"}]})
    sources = {"context:blueprint_block": {"kind": "context", "text": "a two-day intensive"}}
    verdict, _, reason = truth.assess_review(raw, "Note: your revenue is typically $900 a month.", sources)
    assert verdict == "unsupported" and "is not in the quote" in reason


def test_an_opened_page_does_not_stop_the_answer_being_repaired():
    calls = {"n": 0}

    async def reviewer(client, system, messages, **kw):
        calls["n"] += 1
        if calls["n"] == 1:   # the draft: a figure it cannot back
            return json.dumps({"verdict": "supported", "claims": [
                {"text": "you have 40 past clients to invite", "kind": "fact",
                 "source_id": "context:contacts_total", "quote": "11"}]})
        return json.dumps({"verdict": "supported", "claims": []})

    repaired = "Start with the people who already know your work, then open seats to your wider list."
    out, meta = asyncio.run(truth.finalize_reply(
        None, "Note: you have 40 past clients to invite.", ctx={"contacts_total": 11}, view_detail="",
        taken=[NAV], message="help me fill the seats", business_id="biz", reviewer=reviewer,
        repairer=AsyncMock(return_value=repaired)))
    assert out == "Opened BUILD → strategy-track\n\n" + repaired
    assert meta.get("recovered")


def test_when_the_repair_fails_the_page_label_says_what_was_left_out():
    reviewer = AsyncMock(return_value=json.dumps({"verdict": "supported", "claims": [
        {"text": "you have 40 past clients", "kind": "fact", "source_id": "context:contacts_total", "quote": "11"}]}))
    out, meta = asyncio.run(truth.finalize_reply(
        None, "Note: you have 40 past clients.", ctx={"contacts_total": 11}, view_detail="",
        taken=[NAV], message="help me fill the seats", business_id="biz", reviewer=reviewer,
        repairer=AsyncMock(return_value="")))
    assert out.startswith("Opened BUILD → strategy-track")
    assert "left the rest of my answer out" in out and "try again" not in out
