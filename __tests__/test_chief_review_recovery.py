import asyncio
import json
from unittest.mock import AsyncMock

import pytest
import chief_of_staff as chief
import chief_truth as truth


def unsupported(text='I texted your invoice.'):
    return json.dumps({'verdict': 'unsupported', 'claims': [
        {'text': text, 'kind': 'action', 'source_id': '', 'quote': '', 'gap': 'No send receipt'}]})


def supported():
    return json.dumps({'verdict': 'supported', 'claims': []})


def run(reviewer, repairer, **kwargs):
    return asyncio.run(truth.finalize_reply(None, 'I texted your invoice.', ctx={}, view_detail='',
        taken=[], message='Send an invoice through a text message.', business_id='test',
        reviewer=reviewer, repairer=repairer, **kwargs))


def test_rejected_action_recovers_to_checked_clarification_with_history():
    reviewer = AsyncMock(side_effect=[unsupported(), supported()])
    repairer = AsyncMock(return_value='Which invoice should I text?')
    history = [{'role': 'user', 'content': 'My client is Ada.'}]
    reply, metadata = run(reviewer, repairer, conversation_history=history)
    assert reply == 'Which invoice should I text?' and metadata['recovered']
    assert reviewer.await_count == 2 and repairer.await_count == 1
    payload = json.loads(repairer.call_args.args[2][0]['content'])
    assert payload['sources']['conversation:history:0']['text'] == history[0]['content']
    assert payload['sources']['turn:execution']['text'] == 'No action ran in this request.'
    assert payload['sources']['system:invoice_delivery']['kind'] == 'capability'
    assert repairer.call_args.kwargs['enable_web_search'] is False


def test_capability_is_supported_as_fact_without_an_execution_receipt():
    draft = 'Chief supports sending an existing invoice by email or SMS using send_invoice.'
    raw = json.dumps({'verdict': 'supported', 'claims': [
        {'text': draft, 'kind': 'fact', 'source_id': 'system:invoice_delivery', 'quote': draft}]})
    reply, meta = asyncio.run(truth.finalize_reply(None, draft, ctx={}, view_detail='', taken=[],
        message='Can you text invoices?', business_id='test', reviewer=AsyncMock(return_value=raw)))
    assert reply == draft and meta['status'] == 'supported'
    # The same capability source cannot prove actual execution.
    raw = raw.replace('"kind": "fact"', '"kind": "action"')
    verdict, _, reason = truth.assess_review(raw, draft, {
        'system:invoice_delivery': {'kind': 'capability', 'text': truth.CAPABILITY_EVIDENCE}})
    assert verdict == 'unsupported' and 'receipt' in reason


@pytest.mark.parametrize('second_review', ['', 'not json', unsupported('Which invoice should I text?')])
def test_repair_never_fails_open_or_retries_again(second_review):
    reviewer = AsyncMock(side_effect=[unsupported(), second_review])
    repairer = AsyncMock(return_value='Which invoice should I text?')
    reply, meta = run(reviewer, repairer)
    assert reply == truth.UNVERIFIED_REPLY and meta['status'] == 'withheld'
    assert reviewer.await_count == 2 and repairer.await_count == 1


@pytest.mark.parametrize('repair', ["I've sent the invoice.", '[ACTION:{"type":"send_invoice"}]',
                                  '', None])
def test_repair_cannot_emit_actions_or_unchecked_completions(repair):
    reviewer = AsyncMock(return_value=unsupported())
    reply, _ = run(reviewer, AsyncMock(return_value=repair))
    assert reply == truth.UNVERIFIED_REPLY
    reviewer.assert_awaited_once()


def test_repair_timeout_retains_withholding():
    reply, _ = run(AsyncMock(return_value=unsupported()), AsyncMock(side_effect=TimeoutError))
    assert reply == truth.UNVERIFIED_REPLY


def test_explanation_does_not_swallow_mixed_action_requests_or_invent_prior_failure():
    history = [{'role': 'assistant', 'content': truth.UNVERIFIED_REPLY}]
    assert truth.verification_explanation('What can you verify?', history)
    assert truth.verification_explanation('What can you verify? Send the invoice.', history) is None
    assert truth.verification_explanation('What can you verify?', []) is None
    assert truth.verification_explanation('What can you verify?',
        history + [{'role': 'assistant', 'content': 'The invoice was sent.'}]) is None


@pytest.mark.parametrize('surface', ['desktop', 'voice'])
def test_real_chat_followup_explains_verification_without_blocking_again(monkeypatch, surface):
    from scripts import chief_turn_eval as harness
    harness._stub_turn(monkeypatch, harness.BIZ)
    monkeypatch.setattr(chief, '_call_claude', AsyncMock(return_value='I can verify what I did.'))
    reviewer = AsyncMock(side_effect=AssertionError('Explanation must not need another review'))
    monkeypatch.setattr(truth, 'review_reply', reviewer)
    result = asyncio.run(chief.chief_chat(chief.ChatRequest(
        business_id=harness.BIZ['id'], message='What can you verify?', client_surface=surface,
        conversation_history=[chief.ChatMessage(role='assistant', content=truth.UNVERIFIED_REPLY)]), harness._Session()))
    assert result['grounding']['status'] == 'explained'
    assert result['response'] != truth.UNVERIFIED_REPLY and not result['actions_taken']
    assert 'actual result' in result['response']
    reviewer.assert_not_awaited()


@pytest.mark.parametrize('surface', ['desktop', 'voice'])
def test_real_chat_wires_bounded_recovery(monkeypatch, surface):
    from scripts import chief_turn_eval as harness
    harness._stub_turn(monkeypatch, harness.BIZ)
    monkeypatch.setattr(chief, '_call_claude', AsyncMock(return_value='I texted your invoice.'))
    monkeypatch.setattr(truth, 'review_reply', AsyncMock(side_effect=[unsupported(), supported()]))
    repairer = AsyncMock(return_value='Which invoice should I text?')
    monkeypatch.setattr(truth, 'repair_reply', repairer)
    result = asyncio.run(chief.chief_chat(chief.ChatRequest(
        business_id=harness.BIZ['id'], message='send an invoice through a text message.',
        client_surface=surface), harness._Session()))
    assert result['response'] == 'Which invoice should I text?'
    assert result['grounding']['recovered'] and not result['actions_taken']
    repairer.assert_awaited_once()
