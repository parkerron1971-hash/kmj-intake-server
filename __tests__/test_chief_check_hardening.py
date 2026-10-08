"""
test_chief_check_hardening.py — two holes the 2026-10-07 replay found in the answer check.

1. A malformed review checked nothing, and the answer went out unchecked.
   Planted into real answers, "I've also texted your clients a reminder
   about it." and "You also got 7 new leads from Instagram this week." were
   delivered that way when the reviewer misquoted the draft. Now a
   malformed review gets one second review on the `review_fallback` lane.

2. The "I did it" detector, the guard on that unchecked path, knew "sent
   the" and "i've added" but not "I've sent your clients…", "I emailed Ada…"
   or "I've booked Ada…".
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_models
import chief_truth as truth


@pytest.mark.parametrize("text", [
    "I've also texted your clients a reminder about it.",
    "I texted your clients a reminder.",
    "I've sent your clients a reminder.",
    "I emailed Ada the invoice.",
    "I've booked Ada for Friday.",
    "We just posted it.",
])
def test_a_first_person_write_is_a_completion_claim(text):
    assert truth.has_completion_claim(text)


@pytest.mark.parametrize("text", [
    "If I've sent it already, ignore this.",
    "Have I sent the invoice?",
    "I'd text your clients a reminder tomorrow.",
    "I can email Ada the invoice.",
    "Once I've booked Ada, I'll tell you.",
    "Want me to text your clients?",
])
def test_an_offer_question_or_condition_is_not(text):
    assert not truth.has_completion_claim(text)


def test_the_fallback_lane_is_the_strongest_reviewer(monkeypatch):
    monkeypatch.delenv("CHIEF_MODEL_REVIEW_FALLBACK", raising=False)
    assert chief_models.model_for("review_fallback") == "claude-sonnet-5-5"


DRAFT = "You also got 7 new leads from Instagram this week."
MISQUOTED = json.dumps({"verdict": "supported", "claims": [
    {"text": "You got seven leads", "kind": "fact", "source_id": "x", "quote": "y"}]})
HONEST = json.dumps({"verdict": "unsupported", "claims": [
    {"text": "You also got 7 new leads from Instagram this week", "kind": "fact",
     "source_id": "", "quote": "", "gap": "no record of Instagram leads"}]})


def _run(reviewer, draft=DRAFT):
    token = truth.begin("owner", "How is marketing going?")
    try:
        return asyncio.run(truth.finalize_reply(
            None, draft, ctx={}, view_detail={}, taken=[], message="How is marketing going?",
            business_id=None, reviewer=reviewer))
    finally:
        truth.end(token)


def test_a_malformed_review_gets_a_second_review_on_the_fallback_lane():
    lanes = []

    async def reviewer(client, system, messages, **kw):
        lanes.append(kw.get("model_lane", "review"))
        return MISQUOTED if len(lanes) == 1 else HONEST

    text, meta = _run(reviewer)
    assert lanes == ["review", "review_fallback"]
    assert meta["status"] not in ("unchecked", "supported"), meta
    assert "7 new leads" not in text or "could not confirm" in text.lower()


def test_without_a_second_review_the_old_path_is_unchanged():
    calls = []

    async def reviewer(client, system, messages, max_tokens, enable_web_search, business_id):
        calls.append(1)
        return MISQUOTED

    text, meta = _run(reviewer)
    assert calls == [1] and meta["status"] == "unchecked"


def test_an_empty_review_is_not_retried():
    lanes = []

    async def reviewer(client, system, messages, **kw):
        lanes.append(kw.get("model_lane", "review"))
        return ""

    _run(reviewer)
    assert lanes == ["review"]


def test_a_planted_i_texted_is_not_delivered_when_both_reviews_fail():
    async def reviewer(client, system, messages, **kw):
        return MISQUOTED

    text, meta = _run(reviewer, "Your week looks steady. I've also texted your clients a reminder about it.")
    assert "texted your clients" not in text, (meta, text)
