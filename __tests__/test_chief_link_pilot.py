import asyncio
import copy
import json
import time
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
import chief_link_pilot as pilot
import chief_of_staff as chief
import chief_tool_loop as loop
import policy_engine
import action_registry

BID = '00000000-0000-4000-8000-000000000001'
UID = '00000000-0000-4000-8000-000000000002'
OTHER = '00000000-0000-4000-8000-000000000003'
RID = 'lsrq_fixture123'


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv('CHIEF_LINK_PILOT_ENABLED', 'true')
    monkeypatch.setenv('CHIEF_LINK_PILOT_USER_ID', UID)
    monkeypatch.setenv('CHIEF_LINK_PILOT_BUSINESS_ID', BID)
    monkeypatch.setenv('CHIEF_LINK_PILOT_ENCRYPTION_KEY', Fernet.generate_key().decode())
    import business_access
    monkeypatch.setattr(business_access, 'assert_access', Mock())
    rows = {}

    def rpc(name, **args):
        row = rows.setdefault((args['p_business_id'], args['p_user_id']), {'encrypted_state': None, 'lease': None})
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
        else:
            row['lease'] = None
        return True

    monkeypatch.setattr(pilot, 'rpc', rpc)
    return rows


def seed(state):
    with pilot.Session(BID, UID) as s:
        s.state = copy.deepcopy(state)
        s.save()


def connected():
    return {'auth': {'access_token': 'PRIVATE_ACCESS', 'refresh_token': 'PRIVATE_REFRESH',
                     'scope': pilot.SCOPE, 'expires_at': time.time() + 3600}}


def test_tenant_and_feature_gates_before_database_or_provider(store, monkeypatch):
    provider = Mock(side_effect=AssertionError('must not call'))
    monkeypatch.setattr(pilot, 'request', provider)
    for bid, uid in [(OTHER, UID), (BID, OTHER), (BID, ''), ('', UID)]:
        with pytest.raises(pilot.PilotError):
            pilot.run(bid, uid, 'connect')
    monkeypatch.delenv('CHIEF_LINK_PILOT_ENABLED')
    with pytest.raises(pilot.PilotError):
        pilot.run(BID, UID, 'connect')
    assert not store
    provider.assert_not_called()


def test_ciphertext_is_bound_to_both_identities_and_leases_serialize(store):
    seed(connected())
    encrypted = store[(BID, UID)]['encrypted_state']
    assert 'PRIVATE' not in encrypted
    store[(OTHER, UID)] = {'encrypted_state': encrypted, 'lease': None}
    with pytest.raises(pilot.PilotError, match='safely'):
        with pilot.Session(OTHER, UID):
            pass
    with pilot.Session(BID, UID):
        with pytest.raises(pilot.PilotError, match='running'):
            with pilot.Session(BID, UID):
                pass


def test_connection_pending_poll_rate_and_safe_output(store, monkeypatch):
    replies = [(200, {'device_code': 'PRIVATE_DEVICE', 'verification_uri_complete':
                      'https://app.link.com/device/setup?user_code=fixture', 'expires_in': 600, 'interval': 5}),
               (400, {'error': 'slow_down'}),
               (200, {'access_token': 'PRIVATE_ACCESS', 'refresh_token': 'PRIVATE_REFRESH',
                      'scope': pilot.SCOPE, 'expires_in': 3600}), (200, {'name': 'PRIVATE_NAME'})]
    call = Mock(side_effect=replies)
    monkeypatch.setattr(pilot, 'request', call)
    first = pilot.run(BID, UID, 'connect')
    assert first['status'] == 'awaiting_connection' and 'PRIVATE' not in json.dumps(first)
    assert pilot.run(BID, UID, 'connect') == first
    pilot.run(BID, UID, 'status')
    assert call.call_count == 1
    for _ in range(2):
        with pilot.Session(BID, UID) as s:
            s.state['pending']['next_poll'] = 0
            s.save()
        result = pilot.run(BID, UID, 'status')
    assert result['connected'] and 'connection_url' not in result
    assert 'PRIVATE' not in json.dumps(result)
    assert call.call_args_list[0].kwargs['form']['scope'] == pilot.SCOPE


def test_expired_connection_does_not_poll(store, monkeypatch):
    seed({'pending': {'expires_at': 1}})
    call = Mock()
    monkeypatch.setattr(pilot, 'request', call)
    assert pilot.run(BID, UID, 'status')['status'] == 'disconnected'
    call.assert_not_called()


def test_test_request_journal_survives_network_failure_without_duplicate(store, monkeypatch):
    seed(connected())
    call = Mock(side_effect=pilot.PilotError('Network unavailable'))
    monkeypatch.setattr(pilot, 'request', call)
    with pytest.raises(pilot.PilotError):
        pilot.run(BID, UID, 'rehearse')
    payload = call.call_args.kwargs['body']
    assert payload['test'] is True and payload['amount'] == 100 and payload['currency'] == 'usd'
    assert 'approve' not in payload and 'payment_details' not in payload
    call.side_effect = [(409, {'error': {'duplicate_spend_request': {'id': RID, 'status': 'created'}}}),
                        (200, {'id': RID, 'approval_link': 'https://app.link.com/activity/approve/' + RID})]
    result = pilot.run(BID, UID, 'rehearse')
    assert call.call_args_list[1].kwargs['body'] == payload
    assert result['test_request_id'] == RID
    calls = call.call_count
    pilot.run(BID, UID, 'rehearse')
    assert call.call_count == calls


def test_verified_fake_card_never_escapes_and_is_canceled(store, monkeypatch):
    seed({**connected(), 'trial': {'key': 'key', 'id': RID, 'status': 'pending_approval'}})
    raw = {'id': RID, 'status': 'approved', 'card': {'number': '4242424242424242',
            'cvc': 'SECRET_CVC', 'exp_month': 12, 'exp_year': 2030, 'billing_address': {'name': 'PRIVATE_NAME'}}}
    call = Mock(side_effect=[(200, {'id': RID, 'status': 'approved'}), (200, raw),
                             (200, {'id': RID, 'status': 'canceled'})])
    monkeypatch.setattr(pilot, 'request', call)
    result = pilot.run(BID, UID, 'check')
    assert result['test_credential_verified'] and result['status'] == 'canceled'
    with pilot.Session(BID, UID) as s:
        journal = json.dumps(s.state['trial'])
    for forbidden in ['4242424242424242', 'SECRET_CVC', 'PRIVATE_NAME', 'PRIVATE_ACCESS']:
        assert forbidden not in json.dumps(result) + journal
    assert call.call_args.args[1].endswith('/cancel')


def test_unexpected_card_is_not_exposed_and_is_canceled(store, monkeypatch):
    seed({**connected(), 'trial': {'key': 'key', 'id': RID, 'status': 'approved'}})
    call = Mock(side_effect=[(200, {'id': RID, 'status': 'approved'}),
        (200, {'id': RID, 'status': 'approved', 'card': {'number': 'UNEXPECTED_SECRET'}}),
        (200, {'id': RID, 'status': 'canceled'})])
    monkeypatch.setattr(pilot, 'request', call)
    with pytest.raises(pilot.PilotError, match='expected fake card') as error:
        pilot.run(BID, UID, 'check')
    assert 'UNEXPECTED_SECRET' not in str(error.value)
    assert call.call_args.args[1].endswith('/cancel')


def test_refresh_persisted_before_any_spend(store, monkeypatch):
    state = connected()
    state['auth']['expires_at'] = 1
    seed(state)
    call = Mock(return_value=(200, {'access_token': 'ROTATED_ACCESS', 'refresh_token': 'ROTATED_REFRESH',
                                    'scope': pilot.SCOPE, 'expires_in': 3600}))
    monkeypatch.setattr(pilot, 'request', call)
    assert pilot.run(BID, UID, 'status')['connected']
    with pilot.Session(BID, UID) as s:
        assert s.state['auth']['refresh_token'] == 'ROTATED_REFRESH'
    assert 'refresh_token' in call.call_args_list[0].kwargs['form']


def test_revoked_token_is_detected_and_allows_reconnection(store, monkeypatch):
    seed(connected())
    call = Mock(side_effect=[(401, {}), (400, {'error': 'invalid_grant'})])
    monkeypatch.setattr(pilot, 'request', call)
    with pytest.raises(pilot.PilotError, match='no longer authorized'):
        pilot.run(BID, UID, 'status')
    with pilot.Session(BID, UID) as s:
        assert not s.state.get('auth')


def test_disconnect_cancels_then_revokes_and_erases(store, monkeypatch):
    seed({**connected(), 'trial': {'key': 'key', 'id': RID, 'status': 'pending_approval'}})
    call = Mock(side_effect=[(200, {'id': RID, 'status': 'canceled'}), (200, {})])
    monkeypatch.setattr(pilot, 'request', call)
    assert pilot.run(BID, UID, 'disconnect')['status'] == 'disconnected'
    assert call.call_args_list[0].args[1].endswith('/cancel')
    assert call.call_args_list[1].args[1] == '/device/revoke'
    with pilot.Session(BID, UID) as s:
        assert not s.state


@pytest.mark.parametrize('url', ['https://evil.test/device/x', 'http://app.link.com/device/x',
    'https://app.link.com@evil.test/device/x', 'https://app.link.com:443/device/x'])
def test_provider_url_validation(url):
    with pytest.raises(pilot.PilotError):
        pilot.safe_url(url, 'connect')


@pytest.mark.parametrize('surface,prompted', [('scheduler', True), ('workflow', False), ('agent', True),
    ('notification', True), ('chat', False)])
def test_nonchat_paths_blocked_even_when_prompted(surface, prompted):
    assert not policy_engine.evaluate(BID, verb='link_wallet_pilot', surface=surface,
                                     prompted=prompted, user_id=UID).allowed
    token = chief._TURN_USER_ID.set(UID)
    try:
        result = asyncio.run(pilot.dispatch(None, {'id': BID}, {'operation': 'connect'},
                                            surface=surface, prompted=prompted, user_id=UID))
        assert result['failed']
    finally:
        chief._TURN_USER_ID.reset(token)


def test_native_tool_uses_central_door_and_rejects_model_knobs(store, monkeypatch):
    token = chief._TURN_USER_ID.set(UID)
    monkeypatch.setattr(policy_engine, 'evaluate', lambda *a, **kw: policy_engine.Verdict(True, 'chat:owner', 'fixture'))
    monkeypatch.setattr(pilot, 'run', Mock(return_value={'type': 'link_wallet_pilot', 'result': 'fixture connected'}))
    try:
        loop.reset_turn(writes_allowed=True)
        assert any(t['name'] == 'link_wallet_pilot' for t in loop.tool_definitions_for_turn(True))
        assert not action_registry.may_expose_to_agent('link_wallet_pilot', allow_writes=True)
        assert asyncio.run(pilot.handle_link_wallet_pilot(None, {'id': BID}, {'operation': 'connect'}))['failed']
        async def native():
            error, _ = await loop.execute_tool_use(None, {'id': BID, 'owner_id': UID, 'settings': {}},
                                                   'link_wallet_pilot', {'operation': 'status'})
            assert not error
            assert not loop.remaining_tag_actions([{'type': 'link_wallet_pilot', 'operation': 'status'}])
        asyncio.run(native())
        pilot.run.assert_called_once_with(BID, UID, 'status')
        for extra in [{'test': False}, {'user_id': OTHER}, {'amount': 500}, {'token': 'PRIVATE'}]:
            result = asyncio.run(pilot.dispatch(None, {'id': BID}, {'operation': 'rehearse', **extra},
                                                surface='chat', prompted=True, user_id=UID))
            assert result['failed']
        assert pilot.run.call_count == 1
    finally:
        chief._TURN_USER_ID.reset(token)
        loop.reset_turn()


def test_provider_failures_do_not_return_raw_errors(store, monkeypatch):
    seed(connected())
    monkeypatch.setattr(pilot, 'request', Mock(return_value=(500, {'error': 'PRIVATE_PROVIDER_BODY'})))
    with pytest.raises(pilot.PilotError) as error:
        pilot.run(BID, UID, 'rehearse')
    assert 'PRIVATE_PROVIDER_BODY' not in str(error.value)
