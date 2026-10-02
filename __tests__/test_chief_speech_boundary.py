"""Instruction echoes cannot reach speech via any provider chunk boundary."""
import asyncio
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import chief_speech_boundary as speech
import chief_of_staff as chief
import chief_fast_track as fast
import chief_truth as truth


LEAKS = [
    "I should follow the system instructions.",
    "We must follow the system instructions.",
    "> Keep the response brief and conversational.",
    "My internal rules require a short answer.",
    "According to the system prompt, I must answer briefly.",
    "Keep the response brief and conversational.",
    "Do not narrate the internal rules.",
    "For this turn, use only the supplied evidence.",
    "The headline is already said.",
    "[SYSTEM CORRECTION: Emit the missing action.]",
    "SYSTEM CORRECTION: The previous reply claimed an operation was queued.",
    "Never mention this internal correction.",
    "Do not emit any tags in this reply.",
    "[[CHIEF_CACHE_SPLIT]]",
    "<analysis>I need to answer the user.</analysis>",
]


@pytest.mark.parametrize('leak', LEAKS)
def test_every_split_holds_the_entire_internal_sentence(leak):
    for split in range(len(leak) + 1):
        gate = speech.SentenceBoundary()
        said = gate.feed(leak[:split]) + gate.feed(leak[split:] + ' ')
        said += gate.feed('', final=True)
        assert said == '', (split, said)
        assert gate.blocked


@pytest.mark.parametrize('leak', LEAKS)
def test_streamer_blocks_before_factual_reviewer_can_approve(leak):
    async def run():
        said, reviews = [], []
        async def approve(prefix):
            reviews.append(prefix)
            return True
        streamer = chief._SentenceStreamer(said.append, truth.stream_prover({}), review=approve)
        for char in leak + ' \n':
            streamer(char)
        await streamer.wait_closed()
        assert said == [] and reviews == []
    asyncio.run(run())


@pytest.mark.parametrize('text', [
    'Our cancellation policy requires one day of notice.',
    'I must follow your cancellation rules.',
    'Keep the booking instructions brief and conversational.',
    'Your staff should follow the safety instructions.',
    'A system prompt sets the role and style for an assistant.',
    'The developer instructions explain how to install the app.',
    'Here is a short answer: try a monthly plan.',
])
def test_business_rules_and_normal_answers_survive(text):
    assert not speech.internal_scaffolding(text)
    assert speech.final_reply(text) == text


@pytest.mark.parametrize('message', [
    'Write a prompt for my customer service assistant.',
    'Review these response guidelines.',
    'Explain how system prompts work.',
    'Read these instructions aloud.',
    'How should I respond to this customer?',
    'Draft an email to my client.',
])
def test_requested_prompt_writing_and_instruction_discussion_survive(message):
    text = 'Keep the response brief and conversational. Do not mention the internal rules.'
    assert speech.final_reply(text, message) == text
    gate = speech.SentenceBoundary(message)
    assert gate.feed(text, final=True) == text


def test_communication_coaching_keeps_legitimate_response_advice():
    text = 'Keep your response brief and conversational. Explain the refund policy.'
    assert speech.final_reply(text, 'How should I respond to this customer?') == text


def test_mixed_final_reply_keeps_useful_answer_and_removes_only_scaffolding():
    raw = ('Keep the response brief and conversational. '
           'Start with a monthly plan. '
           'The headline is already said. '
           'Compare customer retention after a month.')
    assert speech.final_reply(raw) == ('Start with a monthly plan. '
                                       'Compare customer retention after a month.')
    assert speech.final_reply(LEAKS[0]) == speech.UNAVAILABLE_REPLY


def test_safe_prefix_is_kept_but_stream_stops_at_internal_sentence():
    gate = speech.SentenceBoundary()
    assert gate.feed('Start with a monthly plan. Keep the response brief. More text. ') == \
        'Start with a monthly plan. '
    assert gate.blocked


@pytest.mark.parametrize('private', [
    '<analysis>Private first thought. Private second thought.</analysis>',
    '<thinking>Private first thought. Private second thought.</thinking>',
    '[SYSTEM CORRECTION: First instruction. Second instruction.]',
])
def test_multisentence_private_blocks_are_removed_whole(private):
    assert speech.final_reply(private + ' Start with a monthly plan.') == 'Start with a monthly plan.'


def test_unbracketed_correction_does_not_leave_private_following_sentences():
    raw = 'Start with a monthly plan. SYSTEM CORRECTION: First instruction. Second instruction.'
    assert speech.final_reply(raw) == 'Start with a monthly plan.'


def test_block_diagnostic_is_content_free_and_tied_to_request(caplog):
    import chief_request_timing
    import time
    token = chief_request_timing.CURRENT.set(chief_request_timing.Trace(time.perf_counter(), 'synthetic-id'))
    try:
        speech.final_reply('Keep the response brief and conversational.')
    finally:
        chief_request_timing.CURRENT.reset(token)
    assert 'synthetic-id' in caplog.text and '"stage":"final"' in caplog.text
    assert 'Keep the response' not in caplog.text


def test_fast_and_opener_pump_never_queue_internal_tokens():
    async def run():
        async def provider():
            for char in 'I should follow the system instructions. ':
                yield char
        queue = asyncio.Queue()
        out = {}
        await fast.TwoTrack._pump(SimpleNamespace(message='What is a good pricing approach?'),
                                  provider(), queue, out=out)
        assert list(queue._queue) == [None]
        assert out['error'] == 'internal_scaffolding'
    asyncio.run(run())
