"""
test_chief_advice_is_not_an_action.py — a strategy question gets its answer (2026-09-28).

Live, on a call: Kevin asked how to relaunch and restructure KMJ Creative
Solutions. Three turns in a row ended in a canned line instead of advice:

1. The advice draft said "... done." mid-sentence. The missing-action
   detector matched "done." anywhere, re-asked the question as an
   operation, and when the retry (rightly) ran nothing, the whole answer
   was replaced with "I couldn't start that operation."
2. The answer check could have cut one doubtful "$750" sentence, but the
   claim it names is cut at 80 characters and that cut ended on a space,
   so the lookup missed and the whole answer was withheld as "No action
   ran in this request."
3. "Yes." to "want me to try again?" hit the same failed-retry line.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import chief_truth


@pytest.mark.parametrize("text", [
    "Start by naming the one offer you will sell. Once the testing is done. you can price it.",
    "Get the EIN handled first, and the rest gets done.",
    "The hardest part is already done.",
    "If you've sent the proposal, follow up in three days.",
    "When you're creating the offer, lead with the outcome.",
    "Have you sent the invoice to Ada yet?",
])
def test_advice_is_not_a_completed_action(text):
    assert not cos._looks_like_completed_action(text), text


@pytest.mark.parametrize("text", [
    "Done.",
    "Done — Ada is on your list.",
    "All done!",
    "That's done.",
    "I've added Ada to your contacts — want me to send her a welcome?",
    "Your edit is queued.",
    "Sent the invoice to Ada.",
])
def test_a_real_claim_still_counts(text):
    assert cos._looks_like_completed_action(text), text


def test_trigger_names_the_bare_done():
    assert cos._completed_action_trigger("Done. She is on the list.") == "phrase:'done'"


def test_a_failed_retry_that_just_answers_is_delivered():
    advice = ("Relaunching starts with one clear offer: a 90-day intensive for "
              "early-stage founders. Nothing needs to run for that; it is a decision.")
    with patch.object(cos, '_call_claude', new_callable=AsyncMock, return_value=advice):
        actions, clean, _ = asyncio.run(cos._retry_missing_actions(
            None, 'system', [{'role': 'user', 'content': 'How should I relaunch?'}],
            'How should I relaunch?', 2000, 'test-model'))
    assert actions == []
    assert clean == advice


def test_a_failed_retry_that_still_claims_is_replaced():
    with patch.object(cos, '_call_claude', new_callable=AsyncMock, return_value="Done. It's queued."):
        actions, clean, _ = asyncio.run(cos._retry_missing_actions(
            None, 'system', [{'role': 'user', 'content': 'Edit the flyer'}],
            'Edit the flyer', 2000, 'test-model'))
    assert actions == [] and "couldn't start" in clean


def test_the_retry_is_told_advice_needs_no_operation():
    seen = {}

    async def model(client, system, messages, **kwargs):
        seen['correction'] = system
        return ''
    with patch.object(cos, '_call_claude', side_effect=model):
        asyncio.run(cos._retry_missing_actions(None, 'system', [], 'How should I relaunch?',
                                               2000, 'test-model'))
    assert 'needs no operation' in seen['correction']


def test_a_claim_cut_on_a_space_is_still_found_and_trimmed():
    # The live claim: 80 characters in, the cut lands right after "$3,000 ".
    claim = ("90-day intensives for faith-driven, early-stage entrepreneurs, priced at "
             "$3,000 or four payments of $750.")
    assert claim[:80].endswith(' ')
    reply = ("Here is how I would relaunch. Lead with one offer. " + claim
             + " Then build a waitlist before you build anything else, and talk to "
               "ten past clients this month about what they would pay for.")
    sources = {'context:offerings': {'kind': 'record', 'complete': True,
               'text': '90-day intensives for faith-driven, early-stage entrepreneurs, priced at $3,000'}}
    review = json.dumps({'verdict': 'supported', 'claims': [{'text': claim, 'kind': 'fact',
                                     'source_id': 'context:offerings',
                                     'quote': '90-day intensives for faith-driven, early-stage '
                                              'entrepreneurs, priced at $3,000'}]})
    reason = chief_truth._claim_fail('claim number 750 is not in the quote', claim)
    out = chief_truth._trim_unsupported(review, reply, sources, reason)
    assert out is not None, 'the failed claim must be found and cut'
    draft = out[0]
    assert '$750' not in draft
    assert 'waitlist' in draft
