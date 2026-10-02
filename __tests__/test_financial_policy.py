import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

import financial_policy as policy
import stripe_checkout_helpers as checkout
import contractors_router
import quickbooks_router
import stripe_proxy


@pytest.fixture
def store(monkeypatch):
    state = {'mode': 'view_only', 'calls': [], 'current': True, 'historical': True}
    def get(path):
        state['calls'].append(path)
        if path.startswith('/business_financial_policies?'):
            return [{'business_id': 'biz', 'mode': state['mode']}]
        if path.startswith('/businesses?'):
            return [{'id': 'biz'}] if state['current'] else []
        if path.startswith('/business_financial_account_locks?'):
            return [{'business_id': 'biz'}] if state['historical'] else []
        raise AssertionError(path)
    monkeypatch.setattr(policy.sb_clients, 'sb_get_as_service', get)
    def forbidden(*a, **k):
        pytest.fail('Blocked financial action reached an external provider')
    monkeypatch.setattr(checkout.httpx, 'AsyncClient', forbidden)
    return state


def test_lock_survives_disconnection_and_caller_settings_cannot_override(store):
    store['current'] = False
    with pytest.raises(HTTPException) as exc:
        policy.require_stripe_write('acct_example')
    assert exc.value.status_code == 403
    store['mode'] = 'standard'
    policy.require_stripe_write('acct_example')


def test_unknown_account_is_not_a_platform_fallback(store):
    store.update(current=False, historical=False)
    with pytest.raises(HTTPException) as exc:
        policy.require_stripe_write('acct_unknown')
    assert exc.value.status_code == 409


def test_unavailable_policy_store_fails_closed(store, monkeypatch):
    monkeypatch.setattr(policy.sb_clients, 'sb_get_as_service', lambda path: None)
    with pytest.raises(HTTPException) as exc:
        policy.require_operational_write('biz')
    assert exc.value.status_code == 503


@pytest.mark.parametrize('operation', ['checkout', 'refund', 'saved_card', 'invoice_link', 'giving', 'manual_link', 'contractor', 'quickbooks'])
def test_every_operational_provider_write_is_blocked_before_network(store, operation):
    async def invoke():
        if operation == 'checkout':
            return await checkout.create_checkout_session(stripe_account_id='acct_example', line_items=[{'name': 'Test', 'amount_cents': 100, 'quantity': 1}], success_url='https://example.test/ok', cancel_url='https://example.test/cancel', source_type='manual', source_id='record')
        if operation == 'refund':
            return await checkout.create_refund(stripe_account_id='acct_example', charge_id='ch_test')
        if operation == 'saved_card':
            return await checkout.charge_saved_payment_method(stripe_account_id='acct_example', customer_id='cus_test', amount_cents=100, description='Test')
        if operation == 'invoice_link':
            return await checkout.create_invoice_checkout(stripe_account_id='acct_example', invoice_id='invoice', amount_cents=100)
        if operation == 'giving':
            return await checkout.create_giving_checkout(stripe_account_id='acct_example', gift_id='gift', business_id='biz', amount_cents=100, fund='general', fund_label='General', fund_kind='general', monthly=True, giver_name=None, giver_email=None, success_url='https://example.test/ok', cancel_url='https://example.test/cancel')
        if operation == 'manual_link':
            return await stripe_proxy._create_stripe_payment_link(1, 'usd', 'Test', business_id='biz')
        if operation == 'contractor':
            return await contractors_router._stripe_post('/transfers', {'metadata[business_id]': 'biz'})
        return await quickbooks_router._qbo_post('biz', '/journalentry', {})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(invoke())
    assert exc.value.status_code == 403


def test_normal_business_policy_can_still_allow_operations(store):
    store['mode'] = 'standard'
    policy.require_operational_write('biz')
    policy.require_stripe_write('acct_example')
