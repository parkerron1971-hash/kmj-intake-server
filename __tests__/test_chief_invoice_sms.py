import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
import action_proposals
import chief_invoice_actions
import chief_invoice_sms as delivery
import chief_of_staff as chief
import sms_service

BIZ = {'id': '11111111-1111-4111-8111-111111111111', 'name': 'Example Co', 'settings': {}}
INVOICE = {'id': '22222222-2222-4222-8222-222222222222', 'business_id': BIZ['id'],
           'invoice_number': 'INV-007', 'status': 'draft', 'total': 125, 'currency': 'USD',
           'contact_id': '33333333-3333-4333-8333-333333333333', 'due_date': '2026-10-01',
           'items': [{'description': 'Consultation', 'quantity': 1}],
           'stripe_payment_url': 'https://buy.stripe.com/invoice_example'}
CONTACT = {'id': INVOICE['contact_id'], 'name': 'Ada', 'phone': '+12165550100', 'email': None}


@pytest.fixture
def setup(monkeypatch):
    rows = [deepcopy(INVOICE)]
    calls = []
    async def db(client, method, path, body=None):
        calls.append((method, path, body))
        return deepcopy(rows)
    monkeypatch.setattr(chief, '_sb', db)
    monkeypatch.setattr(chief_invoice_actions, 'sb_as_current_context', db)
    contact = AsyncMock(return_value=deepcopy(CONTACT))
    sms = AsyncMock(return_value={'status': 'sent', 'id': 'sms-1', 'telnyx_id': 'provider-1'})
    email = AsyncMock(side_effect=AssertionError('SMS must never send email'))
    monkeypatch.setattr(chief, '_validate_contact', contact)
    monkeypatch.setattr(sms_service, 'send_sms_core', sms)
    monkeypatch.setattr(chief, '_send_invoice_email', email)
    return rows, calls, contact, sms, email


def send(**kwargs):
    return asyncio.run(chief.handle_send_invoice(None, BIZ,
        {'type': 'send_invoice', 'invoice_id': INVOICE['id'], 'channel': 'sms', **kwargs}))


def test_text_routes_to_linked_phone_without_email_and_records_receipt(setup):
    rows, calls, contact, sms, email = setup
    result = send(to='+19999999999', message='Pay https://invented.example')
    assert result['sms_sent'] and result['channel'] == 'sms'
    assert result['provider_id'] == 'provider-1'
    args = sms.call_args.kwargs
    assert args['to'] == CONTACT['phone'] and args['contact_id'] == CONTACT['id']
    assert args['business_id'] == BIZ['id'] and args['sent_by'] == 'chief'
    assert all(s in args['message'] for s in ['INV-007', 'USD 125.00', 'Consultation', '2026-10-01', INVOICE['stripe_payment_url']])
    assert 'invented' not in args['message']
    email.assert_not_awaited()
    contact.assert_awaited_once_with(None, BIZ['id'], CONTACT['id'])
    assert all('business_id=eq.' + BIZ['id'] in path for method, path, _ in calls if method in ('GET', 'PATCH'))
    assert next(body for method, _, body in calls if method == 'PATCH')['status'] == 'sent'
    assert next(body for method, _, body in calls if method == 'POST')['data']['channel'] == 'sms'


@pytest.mark.parametrize('status', ['paid', 'cancelled', 'void', 'voided'])
def test_closed_invoice_never_sends(setup, status):
    setup[0][0]['status'] = status
    assert send()['failed']
    setup[3].assert_not_awaited()


@pytest.mark.parametrize('problem', ['phone', 'contact', 'invoice', 'ambiguous', 'missing_id'])
def test_missing_or_ambiguous_target_never_sends(setup, problem):
    if problem == 'phone':
        setup[2].return_value['phone'] = ''
    elif problem == 'contact':
        setup[2].return_value = None
    elif problem == 'invoice':
        setup[0].clear()
    elif problem == 'ambiguous':
        setup[0].append(deepcopy(INVOICE))
    result = send(invoice_id=None) if problem == 'missing_id' else send()
    assert result['failed']
    setup[3].assert_not_awaited()
    assert all(method == 'GET' for method, _, _ in setup[1])


@pytest.mark.parametrize('reason', ['Recipient opted out of texts (STOP).', 'SMS is not configured. Set TWILIO_* vars.', 'Provider unavailable'])
def test_send_failure_is_actionable_and_never_marks_sent(setup, reason):
    setup[3].side_effect = sms_service.SmsSendError(reason)
    result = send()
    assert result['failed'] and not result.get('sms_sent')
    assert 'TWILIO' not in result['result']
    assert all(method == 'GET' for method, _, _ in setup[1])


def test_no_provider_receipt_is_not_a_success(setup):
    setup[3].return_value = {'status': 'sent', 'id': 'sms-1'}
    result = send()
    assert result['failed'] and 'Check the SMS thread' in result['result']
    assert all(method == 'GET' for method, _, _ in setup[1])


def test_bookkeeping_failure_preserves_send_receipt(setup, monkeypatch):
    monkeypatch.setattr(chief, '_sb', AsyncMock(side_effect=RuntimeError('storage unavailable')))
    result = send()
    assert result['sms_sent'] and not result.get('failed')
    assert 'history could not be fully updated' in result['label']
    setup[3].assert_awaited_once()


def test_overdue_status_is_not_reset_on_resend(setup):
    setup[0][0]['status'] = 'overdue'
    assert send()['sms_sent']
    patch = next(body for method, _, body in setup[1] if method == 'PATCH')
    assert 'status' not in patch


def test_missing_link_uses_invoice_details_without_inventing_payment_url(setup):
    setup[0][0]['stripe_payment_url'] = None
    assert send()['sms_sent']
    assert 'Please reply for payment arrangements.' in setup[3].call_args.kwargs['message']
    assert 'https://' not in setup[3].call_args.kwargs['message']


@pytest.mark.parametrize('change', [
    {'total': 'NaN'}, {'total': 0}, {'stripe_payment_url': 'javascript:bad'},
    {'items': [{'description': 'x' * 1300}]},
])
def test_invalid_or_oversize_invoice_does_not_send_partial_details(setup, change):
    setup[0][0].update(change)
    assert send()['failed']
    setup[3].assert_not_awaited()


def test_invoice_number_and_latest_resolution_are_scoped(setup):
    assert send(invoice_id=None, invoice_number='INV-007')['sms_sent']
    assert 'invoice_number=eq.' in setup[1][0][1]
    setup[1].clear()
    assert send(invoice_id='latest')['sms_sent']
    assert all('business_id=eq.' + BIZ['id'] in path for method, path, _ in setup[1] if method == 'GET')


def test_bad_channel_cannot_fall_back_to_email(setup):
    assert send(channel='fax')['failed']
    setup[3].assert_not_awaited()
    setup[4].assert_not_awaited()


def test_email_remains_default(setup):
    # Reaching the existing email prerequisite proves an omitted channel
    # still uses email and does not silently text a contact without email.
    result = send(channel=None)
    assert result['failed'] and 'no email on file' in result['result']
    setup[3].assert_not_awaited()


def test_sms_channel_survives_proposal_and_invoice_chaining():
    action = action_proposals.action_for('propose_send_invoice', {'invoice_id': INVOICE['id'], 'channel': 'sms'})
    assert action['channel'] == 'sms' and 'by text' in action_proposals.describe(action)
    with pytest.raises(ValueError):
        action_proposals.action_for('propose_send_invoice', {'invoice_id': INVOICE['id'], 'channel': 'fax'})
    chained = chief._resolve_action_references({'type': 'send_invoice', 'channel': 'sms'},
        [{'type': 'create_invoice', 'invoice_id': INVOICE['id']}])
    assert chained['invoice_id'] == INVOICE['id'] and chained['channel'] == 'sms'
    explicit = chief._resolve_action_references({'type': 'send_invoice', 'channel': 'sms', 'invoice_number': 'INV-OTHER'},
        [{'type': 'create_invoice', 'invoice_id': INVOICE['id']}])
    assert 'invoice_id' not in explicit


def test_voice_gate_keeps_sms_channel_and_requires_confirmation(setup):
    async def run():
        voice = chief._TURN_IS_VOICE.set(True)
        confirmed = chief._TURN_CONFIRMED.set(False)
        try:
            action = {'type': 'send_invoice', 'channel': 'sms', 'invoice_id': INVOICE['id']}
            state, held = await chief._gate_class_c(None, BIZ, 'send_invoice', action, 0)
            assert state == 'handled' and held['failed']
            assert held['needs_confirmation'] and 'Ada' in held['result']
            assert 'USD 125.00' in held['result'] and '0100' in held['result']
            assert chief._deterministic_fallback_reply([held]) == held['label']
            assert 'Say "send it"' in held['label']
            chief._TURN_CONFIRMED.set(True)
            state, _ = await chief._gate_class_c(None, BIZ, 'send_invoice', action, 0)
            assert state == 'execute'
        finally:
            chief._TURN_IS_VOICE.reset(voice)
            chief._TURN_CONFIRMED.reset(confirmed)
    asyncio.run(run())
    setup[3].assert_not_awaited()


@pytest.mark.parametrize('surface,confirmed', [('desktop', False), ('voice', False), ('voice', True)])
def test_chat_tag_reaches_sms_handler_through_normal_approval_boundary(setup, monkeypatch, surface, confirmed):
    import chief_truth
    from scripts import chief_turn_eval as harness
    biz = {**BIZ, 'owner_id': harness._Session.user.id, 'type': 'coach'}
    harness._stub_turn(monkeypatch, biz)
    # Keep the real invoice lookup, handler, action gate, and final answer
    # boundary. Only database/provider/model seams use fixture responses.
    async def db(client, method, path, body=None):
        return [biz] if path.startswith('/businesses?') else [deepcopy(INVOICE)]
    monkeypatch.setattr(chief, '_sb', db)
    raw = '[ACTION:' + json.dumps({'type': 'send_invoice', 'invoice_id': INVOICE['id'], 'channel': 'sms'}) + ']'
    monkeypatch.setattr(chief, '_call_claude', AsyncMock(return_value=raw))
    # Reject narration deliberately: the real send receipt must survive it.
    monkeypatch.setattr(chief_truth, 'review_reply', AsyncMock(return_value='{"verdict":"unsupported","claims":[]}'))
    result = asyncio.run(chief.chief_chat(chief.ChatRequest(
        business_id=BIZ['id'], message='send it' if confirmed else 'Text invoice INV-007 to Ada.',
        client_surface=surface), harness._Session()))
    if surface == 'voice' and not confirmed:
        setup[3].assert_not_awaited()
        assert result['actions_taken'][0]['needs_confirmation']
        assert 'USD 125.00' in result['response'] and 'Say "send it"' in result['response']
    else:
        setup[3].assert_awaited_once()
        assert result['actions_taken'][0]['sms_sent']
        assert 'sent by text to Ada' in result['response']
        assert result['grounding']['status'] == 'receipts'
    setup[4].assert_not_awaited()
