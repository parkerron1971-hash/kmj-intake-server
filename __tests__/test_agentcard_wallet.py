"""Wallet security/lifecycle tests. No real provider, payment or customer credentials."""
import copy
import hashlib
import hmac
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from cryptography.fernet import Fernet

import agentcard_client as p
import agentcard_wallet as w
import agentcard_store as store

BID = '00000000-0000-4000-8000-000000000001'
UID = '00000000-0000-4000-8000-000000000002'
PID = '00000000-0000-4000-8000-000000000003'
APPROVAL = 'https://vault.agentcard.sh/authorize?id=cauth_test'


class MemoryWallet:
    def __init__(self, state=None):
        self.state = state or {}
        self.saved = []
    def save(self):
        self.saved.append(copy.deepcopy(self.state))


def cart_wallet(phase='cart'):
    return MemoryWallet({'connection': {'user_id': 'usr_test', 'access_token': 'PRIVATE',
        'refresh_token': 'PRIVATE_REFRESH', 'expires_at': time.time() + 3600},
        'cards': [{'id': 'vc_test', 'brand': 'visa', 'last4': '4242'}],
        'purchase': {'id': PID, 'phase': phase, 'conversation_id': 'conv_test',
                     'cart': {'hash': 'hash1', 'total_cents': 2306},
                     'approval_url': APPROVAL if phase == 'approval' else None}})


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    for key, value in {'AGENTCARD_MODE': 'sandbox', 'AGENTCARD_CHECKOUT_ENABLED': 'true',
        'AGENTCARD_ENABLED': 'true', 'AGENTCARD_CLIENT_ID': 'test-client',
        'AGENTCARD_CLIENT_SECRET': 'SYNTHETIC_SECRET', 'AGENTCARD_ENCRYPTION_KEY': Fernet.generate_key().decode()}.items():
        monkeypatch.setenv(key, value)
    p._cached.clear()


@pytest.mark.parametrize('url', ['http://vault.agentcard.sh/v?vs=x', 'https://vault.agentcard.sh.evil.test/v?vs=x',
    'https://user@vault.agentcard.sh/v?vs=x', 'https://vault.agentcard.sh:443/v?vs=x',
    'https://vault.agentcard.sh/v?vs=x#leak', 'https://vault.agentcard.sh/v?vs=x&redirect=https://evil.test',
    'https://vault.agentcard.sh\\@evil.test/v?vs=x', 'https://vault.agentcard.sh/v?vs=x&vs=y'])
def test_unsafe_enrollment_urls(url):
    assert p.safe_url(url, 'enroll') is None


def test_expected_provider_urls():
    assert p.safe_url('https://vault.agentcard.sh/v?vs=vs_test.token', 'enroll')
    assert p.safe_url(APPROVAL, 'approve')
    assert not p.safe_url(APPROVAL, 'enroll')


def test_signature_exact_bytes_replay_future_and_missing_secret():
    raw = b'{"id":"evt_test", "livemode":false}'
    sig = hmac.new(b'synthetic', b'1000.' + raw, hashlib.sha256).hexdigest()
    header = 't=1000,v1=' + sig
    assert w.verify_signature(raw, header, 'synthetic', now=1001)
    assert not w.verify_signature(raw.replace(b' ', b''), header, 'synthetic', now=1001)
    assert not w.verify_signature(raw, header, '', now=1001)
    assert not w.verify_signature(raw, header, 'synthetic', now=1400)
    assert not w.verify_signature(raw, header, 'synthetic', now=600)
    assert not w.verify_signature(raw, 'malformed', 'synthetic', now=1001)


def test_secrets_never_enter_snapshot():
    wallet = cart_wallet()
    data = json.dumps(w.snapshot(wallet))
    assert 'PRIVATE' not in data
    assert 'access_token' not in data
    assert 'refresh_token' not in data
    assert 'user_id' not in data


def test_checkout_claim_precedes_network_and_timeout_never_retries():
    wallet = cart_wallet()
    def timeout(*args, **kwargs):
        assert wallet.saved[-1]['purchase']['phase'] == 'submitting'
        raise p.AgentcardError()
    with patch.object(p, 'request', side_effect=timeout) as network:
        with pytest.raises(p.AgentcardError):
            w.checkout(wallet, w.Confirm(purchase_id=PID, cart_hash='hash1'))
        with pytest.raises(p.AgentcardError):
            w.checkout(wallet, w.Confirm(purchase_id=PID, cart_hash='hash1'))
        assert network.call_count == 1


@pytest.mark.parametrize('changes', [{'cart_hash': 'changed'}, {'purchase_id': BID}])
def test_stale_confirmation_never_reaches_provider(changes):
    with patch.object(p, 'request') as network:
        with pytest.raises(p.AgentcardError):
            w.checkout(cart_wallet(), w.Confirm(**dict({'purchase_id': PID, 'cart_hash': 'hash1'}, **changes)))
        network.assert_not_called()


def test_disabled_and_over_budget_checkout(monkeypatch):
    wallet = cart_wallet()
    for key, value in [('AGENTCARD_CHECKOUT_ENABLED', 'false'), ('AGENTCARD_MAX_PURCHASE_CENTS', '100')]:
        monkeypatch.setenv(key, value)
        with patch.object(p, 'request') as network, pytest.raises(p.AgentcardError):
            w.checkout(wallet, w.Confirm(purchase_id=PID, cart_hash='hash1'))
        network.assert_not_called()
        monkeypatch.setenv('AGENTCARD_CHECKOUT_ENABLED', 'true')


def test_approval_is_not_an_order_and_requires_verified_matching_amount():
    wallet = cart_wallet()
    with patch.object(p, 'request', return_value={'conversation_id': 'conv_test', 'decline_code': 'vault_approval_required',
            'status': 'declined', 'charge_status': 'none', 'approval_url': APPROVAL}):
        w.checkout(wallet, w.Confirm(purchase_id=PID, cart_hash='hash1'))
    assert wallet.state['purchase']['phase'] == 'approval'
    for status, amount in [('awaiting_approval', 2306), ('approved', 2400), ('expired', 2306)]:
        with patch.object(p, 'call', return_value={'id': 'cauth_test', 'status': status, 'amount': amount, 'currency': 'usd'}), patch.object(p, 'request') as network:
            with pytest.raises(p.AgentcardError):
                w.checkout(wallet, w.Confirm(purchase_id=PID, cart_hash='hash1'))
            network.assert_not_called()


def test_approved_resume_always_pins_vault_source_and_cart_hash():
    wallet = cart_wallet('approval')
    with patch.object(p, 'call', return_value={'id': 'cauth_test', 'status': 'approved', 'amount': 2306, 'currency': 'usd'}), patch.object(p, 'request', return_value={
        'conversation_id': 'conv_test', 'status': 'declined', 'charge_status': 'none', 'decline_code': 'sandbox_mode'}) as call:
        w.checkout(wallet, w.Confirm(purchase_id=PID, cart_hash='hash1'))
        assert call.call_args.args[2] == {'conversation_id': 'conv_test', 'confirm': 'hash1', 'payment_source': 'vault'}
    assert wallet.state['purchase']['phase'] == 'declined'
    assert 'no payment' in wallet.state['purchase']['message']


def test_changed_cart_requires_new_user_review():
    wallet = cart_wallet()
    cart = {'hash': 'new-hash', 'totalCents': 2400, 'items': [{'name': 'coffee', 'qty': 1}]}
    error = p.AgentcardError(status=409, data={'conversation_id': 'conv_test', 'carts': [cart]})
    with patch.object(p, 'request', side_effect=error):
        w.checkout(wallet, w.Confirm(purchase_id=PID, cart_hash='hash1'))
    assert wallet.state['purchase']['phase'] == 'cart'
    assert wallet.state['purchase']['cart']['hash'] == 'new-hash'


def test_turn_in_progress_does_not_release_claim():
    wallet = cart_wallet()
    with patch.object(p, 'request', side_effect=p.AgentcardError(status=409, data={
        'conversation_id': 'conv_test', 'code': 'turn_in_progress', 'carts': [{'hash': 'h'}]})), pytest.raises(p.AgentcardError):
        w.checkout(wallet, w.Confirm(purchase_id=PID, cart_hash='hash1'))
    assert wallet.state['purchase']['phase'] == 'submitting'


def test_only_settled_orders_are_reported_complete():
    for status, expected in [('confirming', 'reconciling'), ('settled', 'placed'), ('failed', 'reconciling')]:
        wallet = cart_wallet('submitting')
        with patch.object(p, 'request', return_value={'conversation_id': 'conv_test', 'turn_in_progress': False,
            'orders': [{'order_id': 'order-test', 'status': status, 'total_cents': 2306}]}):
            w.reconcile(wallet)
        assert wallet.state['purchase']['phase'] == expected


def test_refresh_token_timeout_does_not_reuse_token():
    wallet = cart_wallet()
    wallet.state['connection']['expires_at'] = 0
    with patch.object(p, 'call', side_effect=p.AgentcardError()) as network:
        with pytest.raises(p.AgentcardError):
            w.user_token(wallet)
        with pytest.raises(p.AgentcardError):
            w.user_token(wallet)
        assert network.call_count == 1


def test_prepare_never_sends_confirmation_or_payment_source():
    wallet = cart_wallet()
    wallet.state.pop('purchase')
    with patch.object(p, 'request', return_value={'conversation_id': 'conv_test', 'reply': 'Which coffee?', 'carts': []}) as network:
        w.prepare(wallet, PID, 'Find coffee')
        assert network.call_args.args[2] == {'ask': 'Find coffee'}
        w.prepare(wallet, PID, 'Find coffee')
        assert network.call_count == 1


def test_mode_mismatch_fails_before_customer_api():
    with patch.object(p, 'request', side_effect=[{'access_token': 'PRIVATE', 'expires_in': 3600}, {'test_mode': False}]), pytest.raises(p.AgentcardError):
        p.org_token()


def test_encryption_bound_to_customer_and_business():
    original = store.Wallet(BID, UID)
    sealed = store.cipher().encrypt(json.dumps({'identity': original.identity, 'state': {'connection': 'secret'}}).encode()).decode()
    with patch.object(store, 'rpc', return_value={'encrypted_state': sealed, 'revision': 0}):
        with store.Wallet(BID, UID) as opened:
            assert opened.state['connection'] == 'secret'
        with pytest.raises(p.AgentcardError):
            with store.Wallet(PID, UID):
                pass


def test_auth_owner_check_and_step_up_precede_wallet_access():
    app = FastAPI()
    app.include_router(w.router)
    client = TestClient(app)
    assert client.get('/agentcard/wallet/' + BID).status_code == 401
    app.dependency_overrides[w.sb_clients.authed_request] = lambda: SimpleNamespace(user=SimpleNamespace(id=UID, email='test@example.com'))
    with patch.object(w.business_access, 'assert_access', side_effect=HTTPException(403, 'Forbidden')), patch.object(w, 'Wallet') as storage:
        assert client.post('/agentcard/wallet/' + BID + '/connect').status_code == 403
        storage.assert_not_called()
    with patch.object(w.business_access, 'assert_access'), patch.object(w, 'Wallet') as storage:
        assert client.post('/agentcard/wallet/' + BID + '/confirm', json={'purchase_id': PID, 'cart_hash': 'hash1'}).status_code == 403
        storage.assert_not_called()
    client.close()


def test_approved_resume_timeout_cannot_replay_stale_approval():
    wallet = cart_wallet('approval')
    wallet.state['purchase']['confirmed_hash'] = 'hash1'
    auth = {'id': 'cauth_test', 'status': 'approved', 'amount': 2306, 'currency': 'usd'}
    with patch.object(p, 'call', return_value=auth), patch.object(p, 'request', side_effect=p.AgentcardError()):
        with pytest.raises(p.AgentcardError):
            w.checkout(wallet, w.Confirm(purchase_id=PID, cart_hash='hash1'))
    assert wallet.saved[-1]['purchase']['used_approval_ids'] == ['cauth_test']
    stale = {'conversation_id': 'conv_test', 'orders': [], 'last_checkout': {
        'code': 'vault_approval_required', 'charge_status': 'none', 'approval_url': APPROVAL}}
    with patch.object(w, 'refresh_cards'), patch.object(p, 'request', return_value=stale) as network, patch.object(p, 'call') as auth_call:
        w.refresh(wallet)
        w.refresh(wallet)
        assert all(call.args[0] == 'GET' for call in network.call_args_list)
        auth_call.assert_not_called()
    assert wallet.state['purchase']['phase'] == 'submitting'


def test_return_to_wallet_resumes_only_previously_confirmed_matching_cart():
    for confirmed_hash, expected in [(None, 0), ('changed', 0), ('hash1', 1)]:
        wallet = cart_wallet('approval')
        wallet.state['purchase']['confirmed_hash'] = confirmed_hash
        auth = {'id': 'cauth_test', 'status': 'approved', 'amount': 2306, 'currency': 'usd'}
        with patch.object(w, 'refresh_cards'), patch.object(w, 'reconcile'), patch.object(p, 'call', return_value=auth), patch.object(w, 'checkout') as checkout:
            w.refresh(wallet)
            assert checkout.call_count == expected


@pytest.mark.parametrize('order', [{'order_id': '', 'status': 'settled', 'total_cents': 2306},
    {'order_id': 'o', 'status': 'settled', 'total_cents': 2400},
    {'order_id': 'o', 'status': 'settled', 'total_cents': '2306'}])
def test_malformed_or_changed_receipt_is_not_success(order):
    wallet = cart_wallet('submitting')
    with patch.object(p, 'request', return_value={'conversation_id': 'conv_test', 'orders': [order]}):
        w.reconcile(wallet)
    assert wallet.state['purchase']['phase'] == 'reconciling'
