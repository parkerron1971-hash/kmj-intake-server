"""Long inputs, conversation provenance and regression cases from owner reports.

Provider/database seams are mocked; the actual request and answer boundary run.
"""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import chief_of_staff as chief
import chief_truth as truth


def claim(text, sid='', quote='', kind='fact', gap=None):
    value = dict(text=text, source_id=sid, quote=quote, kind=kind)
    if gap:
        value['gap'] = gap
    return value


def review(*claims):
    return json.dumps({'verdict': 'unsupported', 'claims': list(claims)})


def finalize(draft, raw, **kwargs):
    return asyncio.run(truth.finalize_reply(
        None, draft, ctx={'contacts_total': 725}, view_detail='', taken=[],
        message='Please help me with this', business_id='fixture',
        reviewer=AsyncMock(return_value=raw), **kwargs))


@pytest.mark.parametrize('surface', ['desktop', 'voice'])
def test_full_long_request_and_prior_turns_reach_author_and_checker(monkeypatch, surface):
    from scripts import chief_turn_eval as harness
    harness._stub_turn(monkeypatch, harness.BIZ)
    # Well beyond a two-minute transcript and the per-source evidence limit.
    message = 'Here is the background for my request. ' * 650 + 'Please use the teal version.'
    history = [chief.ChatMessage(role='user', content='The design should feel calm.'),
               chief.ChatMessage(role='assistant', content='We can use a restrained palette.')]
    draft = 'You asked for the teal version and a calm design.'
    author = AsyncMock(return_value=draft)
    monkeypatch.setattr(chief, '_call_claude', author)
    captured = {}

    async def reviewer(client, system, messages, **kwargs):
        payload = json.loads(messages[0]['content'])
        captured.update(payload)
        sources = payload['sources']
        assert payload['owner_message'] == message
        assert sources['conversation:current']['text'] == message
        assert sources['conversation:history:0']['text'] == history[0].content
        assert sources['conversation:history:1']['role'] == 'assistant'
        return review(
            claim('teal version', 'conversation:current', 'teal version'),
            claim('calm design', 'conversation:history:0', 'feel calm'))

    monkeypatch.setattr(truth, 'review_reply', reviewer)
    result = asyncio.run(chief.chief_chat(chief.ChatRequest(
        business_id=harness.BIZ['id'], message=message,
        conversation_history=history, client_surface=surface), harness._Session()))
    assert captured
    authored_messages = author.call_args.args[2]
    assert any(message in m['content'] for m in authored_messages if isinstance(m['content'], str))
    assert result['response'] == draft
    assert result['grounding']['status'] == 'supported'
    assert not result['actions_taken']


def test_history_window_matches_author_without_clipping_long_prior_requests():
    history = [{'role': 'user', 'content': str(i) + 'x' * 1000} for i in range(45)]
    history[-1]['content'] = 'Keep this opening instruction. ' + 'background ' * 2500
    sources = truth.conversation_for_review('Keep the final instruction', history)
    prior = [s for sid, s in sources.items() if sid != 'conversation:current']
    assert len(prior) == truth.MAX_REVIEW_HISTORY_MESSAGES == chief.MAX_HISTORY
    assert sources['conversation:history:0']['text'] == history[-30]['content']
    assert sources['conversation:history:29']['text'] == history[-1]['content']
    assert all(s['complete'] for s in prior)
    records = truth.evidence_for_review({'contacts_total': 725}, '', [])
    records.update(sources)
    assert records['context:contacts_total']['text'] == '725'


@pytest.mark.parametrize('kind', ['fact', 'action'])
def test_earlier_assistant_completion_is_not_execution_evidence(kind):
    draft = "I've sent the email."
    result, metadata = finalize(draft, review(claim(draft, 'conversation:history:0', draft, kind)),
        conversation_history=[{'role': 'assistant', 'content': draft}])
    assert result == truth.UNVERIFIED_REPLY
    assert metadata['status'] == 'withheld'


def test_reviewer_cannot_add_a_gap_that_was_never_in_the_answer(monkeypatch):
    # This pins the reviewer's contract; the fast lane would skip it.
    monkeypatch.setenv('CHIEF_REVIEW_FAST_LANE', 'off')
    draft = 'Let us work through this.'
    result, metadata = finalize(draft, review(claim('You paid the invoice', gap='No receipt')))
    assert result == draft
    assert 'paid' not in result
    assert metadata['status'] == 'unchecked'


@pytest.mark.parametrize('gap_first', [True, False])
def test_prose_gap_does_not_hide_a_later_bad_number(gap_first):
    gap = claim('We have exchanged messages.', gap='Missing conversation')
    bad = claim('900 contacts', 'context:contacts_total', '725')
    result, metadata = finalize('We have exchanged messages. You have 900 contacts.',
                               review(*([gap, bad] if gap_first else [bad, gap])))
    # The bad number never reaches the owner. Since 2026-09-24 its sentence
    # is cut and the rest delivered with the gap named, instead of the
    # whole answer withheld.
    assert '900' not in result
    assert metadata['status'] in ('withheld', 'caveated')
    if metadata['status'] == 'caveated':
        assert "left out one figure" in result and 'still unverified' in result


@pytest.mark.parametrize('extra', ['There are 900 contacts.', 'See https://invented.example.'])
def test_prose_gap_does_not_skip_unreviewed_figures_or_links(extra):
    result, metadata = finalize('We have exchanged messages. ' + extra,
                               review(claim('We have exchanged messages.', gap='Missing conversation')))
    # The unreviewed figure or link never reaches the owner (cut or withheld).
    assert '900' not in result and 'invented.example' not in result
    assert metadata['status'] in ('withheld', 'caveated')


def test_numeric_gap_cannot_deliver_an_unsupported_amount():
    result, metadata = finalize('You earned $900.', review(claim('$900', gap='Missing ledger')))
    assert result == truth.UNVERIFIED_REPLY
    assert metadata['status'] == 'withheld'


def test_fragment_is_labeled_as_an_excerpt_without_blaming_question_length():
    fragment = 'despite the back-and-forth texts'
    draft = 'We are still working through this, ' + fragment + '.'
    result, metadata = finalize(draft, review(claim(fragment, gap='No messages supplied')))
    assert result.startswith(draft)
    assert '\n- “' + fragment + '”' in result
    assert 'I could not confirm:' not in result
    assert metadata['status'] == 'caveated'
    assert 'narrow' not in truth.UNVERIFIED_REPLY
    assert 'rephrase' not in truth.UNVERIFIED_REPLY
