"""
test_an_offer_is_not_a_claim.py — an offer is not a claim of work done (2026-09-26).

The new-business turn eval (#1063) found a new business's setup turns
withheld as "couldn't verify". Every setup question ends in an offer:
"Give me a name and a phone or email and I'll add them", and the greeting
example in Chief's own prompt, "I'll open those on your booking page".
has_completion_claim read each as work already done, so when the reviewer
returned no verdict the answer was withheld.

First-person future and offer phrasing ("I'll", "I will", "I can", "want
me to", "shall I", "let me know and I'll") is not a completion claim.
What is stated as done still is, and so are the two promises the history
already settled: "I'll create the invoice now" (#974) and "Let me open it"
(#1009). The sentence stream still holds anything the missing-action
retry would catch, because it speaks before that retry runs.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as chief
import chief_truth as truth

# Chief's own prompt, the launch greeting and the first-week greeting.
LAUNCH_EXAMPLE = ("What days and hours do you cut? I'll open those on your booking page "
                  "so people can only pick times you actually work.")
FIRST_WEEK_EXAMPLE = "Today, your hours: what days do you cut? I'll open those on your booking page."
# The day-one eval row "Where should I start?" (nb_barber_where_to_start).
WHERE_TO_START = ("Start with your people: everything else reads from that list. Who's one "
                  "regular you'd text today? Give me a name and a phone or email and I'll "
                  "add them.")


@pytest.mark.parametrize("reply", [
    LAUNCH_EXAMPLE,
    FIRST_WEEK_EXAMPLE,
    WHERE_TO_START,
    "I'll add them.",
    "I'll add them",
    "I’ll add them.",
    "I will add them.",
    "I can add them.",
    "Want me to add them?",
    "Shall I add them?",
    "Let me know and I'll add them.",
    "Let me know and I'll add them now.",
    "I'll create the invoice once you confirm.",
    "I'll open those on your booking page.",
    "You have no clients right now, so give me one name and I'll add them.",
    "Would you like me to create the invoice?",
])
def test_an_offer_or_a_promise_is_not_a_completion_claim(reply):
    assert not truth.has_completion_claim(reply), reply


@pytest.mark.parametrize("reply", [
    "I've added Jane.",
    "Done — saved.",
    "Done. Your booking page is open Tuesday to Saturday, nine to six.",
    "The appointment is booked.",
    # Under way, not offered (#974's pin).
    "I'll create the invoice now.",
    "I'm adding them now.",
    # A promise beside a claim does not hide the claim.
    "I've added Jane, and I'll add Tom once you send his email.",
    "I can confirm I've added Jane to your contacts.",
    # The navigation promise #1009 catches.
    "That's exactly what The Academy is built for. Let me open it.",
])
def test_work_stated_as_done_is_still_a_completion_claim(reply):
    assert truth.has_completion_claim(reply), reply


def test_a_plain_past_tense_claim_is_still_held_from_the_early_lanes():
    # "I booked" was never on the completion detector's list; the fast
    # lane and the stream hold it as a done-claim, and that stays.
    assert truth.fast_lane("I booked Maria for Friday.", {}) is None
    prover = truth._SentenceProver({})
    assert prover.prove("I booked Maria for Friday.", stream=True) == (False, None)
    assert prover.prove("I booked Maria for Friday.") == (False, None)


@pytest.mark.parametrize("draft", [LAUNCH_EXAMPLE, WHERE_TO_START])
def test_an_offer_flows_when_the_reviewer_returns_no_verdict(draft):
    result, meta = asyncio.run(truth.finalize_reply(
        None, draft, ctx={}, view_detail="", taken=[], message="Where should I start?",
        business_id="biz", reviewer=AsyncMock(return_value="")))
    assert result == draft
    assert meta["status"] in ("unchecked", "fast")


def test_a_claim_is_still_withheld_when_the_reviewer_returns_no_verdict():
    result, meta = asyncio.run(truth.finalize_reply(
        None, "I've added Jane to your contacts.", ctx={}, view_detail="", taken=[],
        message="Add Jane", business_id="biz", reviewer=AsyncMock(return_value="")))
    assert meta["status"] == "withheld"
    assert "I've added Jane" not in result


# ── the stream speaks before the missing-action retry ────────────────

def _stream(pieces):
    out = []
    s = chief._SentenceStreamer(out.append, truth.stream_prover({}))
    for p in pieces:
        s(p)
    s.close()
    return [x[len(chief.PROSE_PREFIX):] for x in out]


@pytest.mark.parametrize("sentence", [
    "Give me a name and a phone or email and I'll add them. ",
    "I'll pull that up. ",
    "I'll open it. ",
    "Once you confirm, I'll create the invoice. ",
])
def test_a_promise_the_retry_would_catch_never_streams_early(sentence):
    # The retry reads the draft as written and still sends these back
    # for their action; said early, they could not be taken back.
    assert chief._looks_like_completed_action(sentence)
    assert _stream([sentence, "Okay. "]) == []


def test_an_offer_the_retry_leaves_alone_still_streams():
    said = _stream(["Want me to take you there? ", "Tasha prefers mornings. "])
    assert said == ["Want me to take you there? "]
