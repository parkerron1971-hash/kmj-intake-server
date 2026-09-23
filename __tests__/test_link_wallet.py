import base64
import copy
import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import link_wallet as wallet
import chief_link_pilot as pilot

BID = '00000000-0000-4000-8000-000000000001'
UID = '00000000-0000-4000-8000-000000000002'
OTHER = '00000000-0000-4000-8000-000000000003'
BASE = '/link/wallet/' + BID


@pytest.fixture
def setup(monkeypatch):
    for key, value in {'LINK_WALLET_ENABLED': 'true', 'LINK_WALLET_CLIENT_ID': 'client_fixture',
                       'LINK_WALLET_CLIENT_SECRET': 'PRIVATE_SECRET',
                       'LINK_WALLET_PUBLISHABLE_KEY': 'pk_live_fixture',
                       'LINK_WALLET_ENCRYPTION_KEY': Fernet.generate_key().decode()}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('CHIEF_LINK_PILOT_ENABLED', raising=False)
    rows = {}
    def rpc(name, **args):
        assert name.startswith('link_wallet_')
        if name == 'link_wallet_find_oauth':
            for (bid, uid), row in rows.items():
                if row.get('state_hash') == args['p_state_hash']:
                    return {'business_id': bid, 'user_id': uid}
            return None
        row = rows.setdefault((args['p_business_id'], args['p_user_id']),
                              {'encrypted_state': None, 'lease': None})
        lease = args['p_lease_id']
        if name.endswith('_acquire'):
            if row['lease']:
                return {'acquired': False}
            row['lease'] = lease
            return {'acquired': True, 'encrypted_state': row['encrypted_state']}
        if row['lease'] != lease:
            return False
        if name.endswith('_save'):
            row['encrypted_state'] = args['p_encrypted_state']
            row['state_hash'] = args.get('p_oauth_state_hash')
        else:
            row['lease'] = None
        return True
    monkeypatch.setattr(wallet, 'rpc', rpc)
    access = Mock()
    unlock = Mock()
    exchange = Mock(side_effect=AssertionError('unexpected provider call'))
    provider = Mock(side_effect=AssertionError('unexpected provider call'))
    monkeypatch.setattr(wallet.business_access, 'assert_access', access)
    monkeypatch.setattr(wallet, 'require_unlock', unlock)
    monkeypatch.setattr(wallet, 'oauth_request', exchange)
    monkeypatch.setattr(pilot, 'request', provider)
    app = FastAPI()
    app.include_router(wallet.router)
    identity = SimpleNamespace(user=SimpleNamespace(id=UID))
    app.dependency_overrides[wallet.sb_clients.authed_request] = lambda: identity
    return SimpleNamespace(client=TestClient(app), app=app, rows=rows, access=access,
                           unlock=unlock, exchange=exchange, provider=provider, identity=identity)


def tokens(refresh='PRIVATE_REFRESH'):
    return {'access_token': 'PRIVATE_ACCESS', 'refresh_token': refresh,
            'scope': pilot.SCOPE, 'expires_in': 3600, 'token_type': 'Bearer'}


def seed(state):
    with wallet.Session(BID, UID) as connection:
        connection.state = copy.deepcopy(state)
        connection.save()


def auth(expires=0):
    return {'auth': {'access_token': 'PRIVATE_ACCESS', 'refresh_token': 'PRIVATE_REFRESH',
                     'scope': pilot.SCOPE, 'expires_at': expires}}


def begin(s):
    result = s.client.post(BASE + '/connect')
    assert result.status_code == 200, result.text
    return result.json()


def callback(s, start, **params):
    return s.client.get('/link/oauth/callback', params={'state': start['state'], 'code': 'PRIVATE_CODE', **params})


def finish_body(start):
    return {'state': start['state'], 'verifier': start['verifier']}


def test_no_configuration_has_honest_readiness_and_never_opens_device_flow(setup, monkeypatch):
    monkeypatch.delenv('LINK_WALLET_ENABLED')
    monkeypatch.delenv('LINK_WALLET_ENCRYPTION_KEY')
    result = setup.client.get(BASE)
    assert result.status_code == 200
    assert result.json() == {'live_spending_enabled': False, 'customer_connections_available': False,
                             'customer': {'connected': False, 'connecting': False}, 'pilot': None}
    assert setup.client.post(BASE + '/connect').status_code == 503
    assert not setup.rows
    setup.provider.assert_not_called()
    setup.exchange.assert_not_called()


@pytest.mark.parametrize('method,path,payload', [
    ('get', '', None), ('post', '/connect', None), ('post', '/refresh', None),
    ('post', '/disconnect', None), ('post', '/complete', {'state': 'a'*43, 'verifier': 'b'*43}),
    ('post', '/pilot', {'operation': 'connect'}),
])
def test_every_wallet_route_checks_owner_before_storage(setup, method, path, payload):
    setup.access.side_effect = HTTPException(403, 'Forbidden')
    result = getattr(setup.client, method)(BASE + path, **({'json': payload} if payload else {}))
    assert result.status_code == 403
    assert not setup.rows
    setup.exchange.assert_not_called()
    setup.provider.assert_not_called()


def test_jwt_dependency_is_required(setup):
    def denied():
        raise HTTPException(401, 'Authentication required')
    setup.app.dependency_overrides[wallet.sb_clients.authed_request] = denied
    assert setup.client.get(BASE).status_code == 401
    setup.access.assert_not_called()
    assert not setup.rows


def test_step_up_denial_cannot_start_or_exchange(setup):
    setup.unlock.side_effect = HTTPException(403, {'code': 'ledger_locked'})
    assert setup.client.post(BASE + '/connect').status_code == 403
    assert not setup.rows
    setup.exchange.assert_not_called()


def test_pkce_scope_and_server_only_secrets(setup):
    start = begin(setup)
    setup.unlock.assert_called_once()
    url = urlsplit(start['authorization_url'])
    assert url.scheme == 'https' and url.netloc == 'login.link.com' and url.path == '/auth'
    params = parse_qs(url.query)
    assert params['redirect_uri'] == [wallet.CALLBACK]
    assert params['scope'] == [pilot.SCOPE]
    assert params['code_challenge_method'] == ['S256']
    assert 'client_secret' not in params
    assert 'PRIVATE' not in json.dumps(start)
    with wallet.Session(BID, UID) as connection:
        pending = connection.state['pending']
        assert pending['state_hash'] == wallet.digest(start['state'])
        challenge = base64.urlsafe_b64encode(hashlib.sha256(pending['pkce'].encode()).digest()).decode().rstrip('=')
        assert params['code_challenge'] == [challenge]
        assert pending['pkce'] not in json.dumps(start)
    encrypted = setup.rows[(BID, UID)]['encrypted_state']
    assert start['state'] not in encrypted and start['verifier'] not in encrypted


@pytest.mark.parametrize('change', ['state', 'verifier', 'business', 'user', 'expired', 'superseded'])
def test_oauth_rejects_wrong_binding_expiry_or_old_attempt(setup, change):
    start = begin(setup)
    body = finish_body(start)
    url = BASE + '/complete'
    if change in ('state', 'verifier'):
        body[change] = 'z' * 43
    elif change == 'business':
        url = url.replace(BID, OTHER)
    elif change == 'user':
        setup.identity.user.id = OTHER
    elif change == 'expired':
        with wallet.Session(BID, UID) as connection:
            connection.state['pending']['expires_at'] = time.time() - 1
            connection.save()
    else:
        begin(setup)
    assert setup.client.post(url, json=body).status_code == 400
    setup.exchange.assert_not_called()


def test_complete_stores_encrypted_tokens_once_and_returns_no_profile(setup):
    start = begin(setup)
    assert callback(setup, start).status_code == 200
    setup.exchange.side_effect = None
    setup.exchange.return_value = (200, tokens())
    result = setup.client.post(BASE + '/complete', json=finish_body(start))
    assert result.status_code == 200
    assert result.json()['connected'] is True
    assert 'PRIVATE' not in result.text
    assert result.headers['cache-control'] == 'no-store'
    assert setup.client.post(BASE + '/complete', json=finish_body(start)).status_code == 400
    assert setup.exchange.call_count == 1
    assert 'PRIVATE' not in setup.rows[(BID, UID)]['encrypted_state']
    assert setup.client.post(BASE + '/connect').status_code == 409


def test_ambiguous_exchange_is_consumed_no_replay_or_error_leak(setup):
    start = begin(setup)
    assert callback(setup, start).status_code == 200
    setup.exchange.side_effect = RuntimeError('PRIVATE_SECRET PRIVATE_CODE')
    result = setup.client.post(BASE + '/complete', json=finish_body(start))
    assert result.status_code == 503 and 'PRIVATE' not in result.text
    assert setup.client.post(BASE + '/complete', json=finish_body(start)).status_code == 400
    assert setup.exchange.call_count == 1


@pytest.mark.parametrize('invalid', ['scope', 'refresh_token', 'token_type'])
def test_incomplete_or_broader_authorization_never_connects(setup, invalid):
    start = begin(setup)
    assert callback(setup, start).status_code == 200
    data = tokens()
    data[invalid] = 'unexpected' if invalid != 'refresh_token' else ''
    setup.exchange.side_effect = None
    setup.exchange.return_value = (200, data)
    assert setup.client.post(BASE + '/complete', json=finish_body(start)).status_code == 409
    assert setup.client.get(BASE).json()['customer']['connected'] is False


def test_refresh_persists_rotation_before_api_and_discards_profile(setup):
    seed(auth())
    setup.exchange.side_effect = None
    setup.exchange.return_value = (200, tokens('PRIVATE_ROTATED'))
    def provider(*args, **kwargs):
        # Lease prevents another worker using stale refresh credentials.
        with pytest.raises(pilot.PilotError, match='running'):
            with wallet.Session(BID, UID):
                pass
        encrypted = setup.rows[(BID, UID)]['encrypted_state']
        state = json.loads(wallet.cipher().decrypt(encrypted.encode()))['state']
        assert state['auth']['refresh_token'] == 'PRIVATE_ROTATED'
        return 200, {'email': 'PRIVATE_EMAIL', 'name': 'PRIVATE_NAME'}
    setup.provider.side_effect = provider
    result = setup.client.post(BASE + '/refresh')
    assert result.status_code == 200 and 'PRIVATE' not in result.text
    assert result.json()['verified_at']
    assert setup.exchange.call_args.args[0] == '/auth/token'


def test_invalid_grant_removes_stale_authorization(setup):
    seed(auth())
    setup.exchange.side_effect = None
    setup.exchange.return_value = (400, {'error': 'invalid_grant'})
    assert setup.client.post(BASE + '/refresh').status_code == 409
    assert not setup.client.get(BASE).json()['customer']['connected']
    setup.provider.assert_not_called()


def test_failed_revoke_keeps_connection_then_success_clears(setup, monkeypatch):
    seed(auth(time.time() + 3600))
    monkeypatch.setenv('LINK_WALLET_ENABLED', 'false')
    setup.exchange.side_effect = None
    setup.exchange.return_value = (503, {'error': 'PRIVATE_RESPONSE'})
    assert setup.client.post(BASE + '/disconnect').status_code == 409
    with wallet.Session(BID, UID) as connection:
        assert connection.state['auth']
    setup.exchange.return_value = (200, {})
    assert setup.client.post(BASE + '/disconnect').json()['connected'] is False
    assert setup.exchange.call_args.args == ('/auth/revoke', {
        'token': 'PRIVATE_REFRESH', 'token_type_hint': 'refresh_token'})


def test_ciphertext_cannot_be_moved_to_another_business_or_owner(setup):
    seed(auth())
    encrypted = setup.rows[(BID, UID)]['encrypted_state']
    for key in ((OTHER, UID), (BID, OTHER)):
        setup.rows[key] = {'encrypted_state': encrypted, 'lease': None}
        with pytest.raises(pilot.PilotError, match='safely'):
            with wallet.Session(*key):
                pass
        assert setup.rows[key]['lease'] is None


def test_no_real_purchase_or_client_identity_knobs(setup):
    for body in ({'operation': 'purchase'}, {'operation': 'rehearse', 'amount': 1},
                 {'operation': 'connect', 'user_id': UID}, {'operation': 'rehearse', 'test': False}):
        assert setup.client.post(BASE + '/pilot', json=body).status_code == 422
    assert setup.client.post(BASE + '/pilot', json={'operation': 'connect'}).status_code == 403
    assert setup.client.post(BASE + '/spend').status_code == 404
    setup.provider.assert_not_called()


def test_private_actions_remain_gated_and_use_existing_pilot(setup, monkeypatch):
    monkeypatch.setattr(pilot, 'allowed', lambda bid, uid: bid == BID and uid == UID)
    run = Mock()
    monkeypatch.setattr(pilot, 'run', run)
    monkeypatch.setattr(wallet, 'wallet_snapshot', lambda *args: {'live_spending_enabled': False})
    result = setup.client.post(BASE + '/pilot', json={'operation': 'rehearse'})
    assert result.status_code == 200
    run.assert_called_once_with(BID, UID, 'rehearse')
    setup.unlock.assert_called_once()


def test_activity_is_an_explicit_allowlist():
    result = wallet.private_snapshot(SimpleNamespace(state={
        'auth': {'access_token': 'PRIVATE_ACCESS'},
        'trial': {'id': 'lsrq_fixture', 'status': 'canceled', 'verified': True, 'card': 'PRIVATE_CARD'},
        'previous_trial': {'id': 'lsrq_old', 'status': 'declined', 'raw': 'PRIVATE_BODY'}}))
    assert 'PRIVATE' not in json.dumps(result)
    assert len(result['activity']) == 2
    assert result['activity'][0]['test_credential_verified']


def test_callback_is_static_no_reflection_and_no_open_redirect(setup):
    result = setup.client.get('/link/oauth/callback?code=%3Cscript%3EPRIVATE_CODE%3C/script%3E'
                              '&state=PRIVATE_STATE&redirect_uri=https://evil.invalid')
    assert result.status_code == 400
    assert 'PRIVATE' not in result.text and 'evil.invalid' not in result.text
    assert result.headers['cache-control'] == 'no-store'
    assert result.headers['referrer-policy'] == 'no-referrer'
    assert "frame-ancestors 'none'" in result.headers['content-security-policy']
    assert "default-src 'none'" in result.headers['content-security-policy']
    setup.exchange.assert_not_called()


def test_completion_waits_for_callback_without_browser_opener(setup):
    start = begin(setup)
    waiting = setup.client.post(BASE + '/complete', json=finish_body(start))
    assert waiting.status_code == 202
    setup.exchange.assert_not_called()
    assert callback(setup, start).status_code == 200
    with wallet.Session(BID, UID) as connection:
        assert connection.state['pending']['code'] == 'PRIVATE_CODE'
    assert 'PRIVATE_CODE' not in setup.rows[(BID, UID)]['encrypted_state']
    setup.exchange.side_effect = None
    setup.exchange.return_value = (200, tokens())
    assert setup.client.post(BASE + '/complete', json=finish_body(start)).json()['connected']
    assert callback(setup, start).status_code == 400


def test_callback_replay_cannot_overwrite_code_and_denial_cannot_create_grant(setup):
    start = begin(setup)
    callback(setup, start)
    callback(setup, start, code='OTHER_CODE')
    with wallet.Session(BID, UID) as connection:
        assert connection.state['pending']['code'] == 'PRIVATE_CODE'
    start = begin(setup)
    callback(setup, start, error='access_denied')
    callback(setup, start)
    assert setup.client.post(BASE + '/complete', json=finish_body(start)).status_code == 409
    setup.exchange.assert_not_called()


def test_callback_expiry_and_random_state_do_not_store_code(setup):
    start = begin(setup)
    assert callback(setup, {'state': 'z'*43}).status_code == 400
    with wallet.Session(BID, UID) as connection:
        connection.state['pending']['expires_at'] = time.time() - 1
        connection.save()
    assert callback(setup, start).status_code == 400
    with wallet.Session(BID, UID) as connection:
        assert 'code' not in connection.state['pending']


def test_existing_connection_is_visible_when_new_connections_disabled(setup, monkeypatch):
    seed(auth(time.time() + 3600))
    monkeypatch.setenv('LINK_WALLET_ENABLED', 'false')
    result = setup.client.get(BASE).json()
    assert not result['customer_connections_available']
    assert result['customer']['connected']


def test_callback_retries_a_short_polling_lease_conflict(setup, monkeypatch):
    start = begin(setup)
    actual = wallet.Session.__enter__
    calls = 0
    def enter(self):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise wallet.Busy('busy')
        return actual(self)
    monkeypatch.setattr(wallet.Session, '__enter__', enter)
    monkeypatch.setattr(wallet.time, 'sleep', Mock())
    assert callback(setup, start).status_code == 200
    assert calls == 2
    setup.exchange.assert_not_called()
