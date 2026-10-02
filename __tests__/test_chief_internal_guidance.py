"""Model-only instructions stay separate from owner messages and public results."""
import asyncio
import json
from unittest.mock import AsyncMock

import chief_of_staff as chief
from chief_receipts import receipt_text
import chief_truth as truth


def test_retry_guidance_is_system_only_and_preserves_original_user_and_history(monkeypatch):
    seen = {}
    original = 'Explain our cancellation policy, including the rule about deposits.'
    history = [{'role': 'user', 'content': 'The deposit is refundable with a day of notice.'},
               {'role': 'assistant', 'content': 'We were discussing the cancellation policy.'},
               {'role': 'user', 'content': original}]
    async def model(client, system, messages, **kwargs):
        seen.update(system=system, messages=messages)
        return 'The deposit is refundable with a day of notice.'
    monkeypatch.setattr(chief, '_call_claude', model)
    actions, reply, _ = asyncio.run(chief._retry_missing_actions(None, 'Base instructions',
        history, original, 1000, 'fixture'))
    assert seen['messages'] == history
    assert seen['messages'][-1]['content'] == original
    assert 'SYSTEM CORRECTION:' in seen['system']
    assert 'SYSTEM CORRECTION:' not in json.dumps(seen['messages'])
    assert 'Never mention this internal correction' in seen['system']
    assert not actions and 'refundable' in reply


def held():
    return {'type': 'send_invoice', 'failed': True, 'needs_confirmation': True,
            'label': 'Before I text the invoice to Ada, please say go ahead. Nothing has run yet.',
            'result': 'Say back exactly what you are about to do. Emit this same action again. Do NOT tell them it is done.'}


def test_held_model_instructions_never_enter_composer_result_payload(monkeypatch):
    result = held()
    composer = AsyncMock(return_value=result['label'])
    monkeypatch.setattr(chief, '_call_claude', composer)
    reply = asyncio.run(chief._compose_post_action_reply(None, 'Text the invoice to Ada.',
        'I texted the invoice.', [result]))
    payload = composer.call_args.args[2][0]['content']
    assert 'AWAITING OWNER CONFIRMATION' in payload
    assert result['label'] in payload
    for instruction in ('Emit this same action', 'Say back exactly', 'Do NOT tell them'):
        assert instruction not in payload and instruction not in reply
    assert reply == result['label']


def test_a_hold_is_not_mislabeled_as_failed_and_other_results_keep_their_states():
    block = chief._format_action_results_for_reply([held(),
        {'type': 'save_note', 'label': 'Saved the assumptions', 'result': 'Note saved'},
        {'type': 'send_sms', 'label': 'Message not sent', 'result': 'Failed: Texting is unavailable.', 'failed': True}])
    assert 'AWAITING OWNER CONFIRMATION' in block and 'Note saved' in block
    assert 'Texting is unavailable' in block
    assert 'Emit this same action' not in block


def test_partial_readout_has_public_status_and_separate_internal_guidance(monkeypatch):
    async def show(client, biz, action):
        if action['view'] == 'contacts':
            return {'type': 'show_view', 'failed': True, 'result': 'The contacts could not load.'}
        return {'type': 'show_view', 'result': 'Opened invoices', 'speak': 'Ada: unpaid invoice.'}
    monkeypatch.setattr(chief, 'handle_show_view', show)
    receipt = asyncio.run(chief.handle_show_readout(None, {}, {'title': 'Business overview',
        'blocks': [{'view': 'invoices'}, {'view': 'contacts'}]}))
    assert "couldn't load: contacts" in receipt['result']
    assert 'do not describe the readout as complete' in receipt['note_for_chief']
    public = receipt_text(receipt)
    assert "couldn't load: contacts" in public
    assert 'say which part' not in public and 'do not describe' not in public
    fallback = chief._deterministic_fallback_reply([receipt])
    assert "couldn't load: contacts" in fallback
    assert receipt['note_for_chief'] not in fallback
    reply, _ = asyncio.run(truth.finalize_reply(None, 'The overview is ready.',
        ctx={}, view_detail='', taken=[receipt], message='Show my business overview.',
        business_id='fixture', reviewer=AsyncMock(return_value='')))
    assert "couldn't load: contacts" in reply
    assert receipt['note_for_chief'] not in reply
    block = chief._format_action_results_for_reply([receipt])
    assert 'internal composition guidance (apply silently, do not quote)' in block


def test_customer_facing_business_policy_is_not_removed():
    receipt = {'type': 'set_business_policy', 'label': 'Cancellation policy saved',
               'result': 'Clients must give a day of notice for a refund.'}
    assert receipt['result'] in receipt_text(receipt)
    assert receipt['result'] in chief._format_action_results_for_reply([receipt])
