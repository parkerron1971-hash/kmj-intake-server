"""The simple invoice route skips model/context work, never admission or action gates."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
import pytest

import chief_invoice_readout as readout
import chief_of_staff as chief
import chief_stream_replay as replay
import sb_clients


BIZ = {'id': 'fixture-business', 'owner_id': 'fixture-owner', 'name': 'Example Studio', 'settings': {}}
SESSION = SimpleNamespace(token='fixture-jwt', user=SimpleNamespace(id='fixture-owner'))
ROWS = [{'id': 'fixture-invoice', 'invoice_number': 'DEMO-1', 'total': 35, 'status': 'sent',
         'due_date': '2026-10-01', 'contacts': {'name': 'Ada Sample'}}]


def arrange(monkeypatch, *, biz=BIZ, allowed=True, rows=ROWS):
    import billing_limits
    import rate_limit
    import chief_build_runtime
    import policy_engine
    import audit_log
    rate = Mock(return_value=True)
    fair, units = Mock(), Mock()
    monkeypatch.setattr(rate_limit, 'allow', rate)
    monkeypatch.setattr(billing_limits, 'require_chat_fair_use', fair)
    monkeypatch.setattr(billing_limits, 'require_units', units)
    monkeypatch.setattr(chief_build_runtime, 'enabled', lambda: False)
    recurrence = AsyncMock(return_value=[])
    monkeypatch.setattr(chief, '_generate_missing_recurring_instances', recurrence)
    monkeypatch.setattr(chief, '_spawn_turn_sweeps', Mock())
    context = AsyncMock(return_value=None)
    monkeypatch.setattr(chief, '_gather_context', context)
    monkeypatch.setattr(chief, '_fetch_view_detail', AsyncMock(return_value={}))
    model = AsyncMock(side_effect=AssertionError('No main model should be called'))
    monkeypatch.setattr(chief, '_call_claude', model)
    archive, activity = AsyncMock(), AsyncMock()
    monkeypatch.setattr(chief, '_archive_turn', archive)
    monkeypatch.setattr(chief, '_log_chief_activity', activity)
    audit = Mock()
    monkeypatch.setattr(audit_log, 'record_chief_turn', audit)
    policy = Mock(return_value=SimpleNamespace(allowed=allowed, rule='owner', reason='Permission denied'))
    monkeypatch.setattr(policy_engine, 'evaluate', policy)
    async def db(client, method, path, *args):
        assert sb_clients.get_current_user_jwt() == 'fixture-jwt'
        assert method == 'GET', 'Only scoped reads are expected from the existing action door'
        if path.startswith('/businesses?'):
            assert 'id=eq.fixture-business' in path
            return [deepcopy(biz)] if biz is not None else []
        if path.startswith('/invoices?'):
            assert 'business_id=eq.fixture-business' in path
            return deepcopy(rows)
        raise AssertionError(path)
    db_mock = AsyncMock(side_effect=db)
    monkeypatch.setattr(chief, '_sb', db_mock)
    replay._receipts.clear()
    return SimpleNamespace(db=db_mock, model=model, context=context, archive=archive, activity=activity,
                           policy=policy, rate=rate, fair=fair, units=units, recurrence=recurrence, audit=audit)


def request(message='Show my invoices.', **kwargs):
    return chief.ChatRequest(business_id='fixture-business', message=message,
                             request_id='invoice-shortcut-fixture', **kwargs)


def test_owner_invoice_read_uses_action_door_and_skips_context_and_model(monkeypatch):
    env = arrange(monkeypatch)
    result = asyncio.run(chief.chief_chat(request(), SESSION))
    assert '$35.00' in result['response'] and 'Ada Sample' in result['response']
    assert result['grounding']['status'] == 'records'
    assert result['actions_taken'][0]['_authorized_by'] == 'owner'
    assert result['actions_taken'][0]['view'] == 'invoices'
    env.context.assert_not_awaited()
    env.model.assert_not_awaited()
    env.rate.assert_called_once()
    env.fair.assert_called_once_with('fixture-business')
    env.units.assert_called_once_with('fixture-business')
    env.recurrence.assert_awaited_once()
    env.policy.assert_called_once()
    assert env.policy.call_args.kwargs['user_id'] == SESSION.user.id
    assert env.policy.call_args.kwargs['verb'] == 'show_view'
    env.archive.assert_awaited_once()
    env.activity.assert_awaited_once()
    env.audit.assert_called_once()
    assert env.audit.call_args.kwargs['taken'][0]['_authorized_by'] == 'owner'
    assert sb_clients.get_current_user_jwt() != 'fixture-jwt'


@pytest.mark.parametrize('gate,code', [('rate', 429), ('fair', 429), ('units', 402)])
def test_admission_refusal_happens_before_invoice_or_business_reads(monkeypatch, gate, code):
    env = arrange(monkeypatch)
    if gate == 'rate':
        env.rate.return_value = False
    else:
        getattr(env, gate).side_effect = HTTPException(code, 'Fixture admission refusal')
    with pytest.raises(HTTPException) as err:
        asyncio.run(chief.chief_chat(request(), SESSION))
    assert err.value.status_code == code
    env.db.assert_not_awaited()
    env.policy.assert_not_called()


@pytest.mark.parametrize('biz', [None, {**BIZ, 'owner_id': 'other-owner'}, {**BIZ, 'id': 'other-business'},
                               {**BIZ, 'owner_id': None}])
def test_shortcut_requires_exact_scoped_business_and_owner(monkeypatch, biz):
    env = arrange(monkeypatch, biz=biz)
    with pytest.raises(HTTPException) as err:
        asyncio.run(chief.chief_chat(request(), SESSION))
    assert err.value.status_code == 404  # normal scoped-context path returned no business
    env.context.assert_awaited_once()
    assert all('/invoices?' not in call.args[2] for call in env.db.await_args_list)
    env.policy.assert_not_called()


def test_policy_refusal_never_reads_invoices_or_falls_through_to_model(monkeypatch):
    env = arrange(monkeypatch, allowed=False)
    result = asyncio.run(chief.chief_chat(request(), SESSION))
    assert result['actions_taken'][0]['failed']
    assert 'Ada Sample' not in result['response']
    assert all('/invoices?' not in call.args[2] for call in env.db.await_args_list)
    env.context.assert_not_awaited()
    env.model.assert_not_awaited()


@pytest.mark.parametrize('message,kwargs', [
    ('Show invoices and send reminders.', {}), ('Show invoices and tell me who to call first.', {}),
    ('Show invoices for Ada', {}), ('Do not show invoices', {}), ('Show invoices', {'mode': 'strategy_coach'}),
    ('Show invoices', {'image_ids': ['fixture-image']}), ('Yes', {}),
])
def test_mixed_requests_and_other_modes_keep_normal_context_path(monkeypatch, message, kwargs):
    env = arrange(monkeypatch)
    with pytest.raises(HTTPException):
        asyncio.run(chief.chief_chat(request(message, **kwargs), SESSION))
    env.context.assert_awaited_once()
    env.policy.assert_not_called()


@pytest.mark.parametrize('message,filt,form', [
    ('List my invoices', 'open', 'list'), ('Show all invoices', 'all', 'list'),
    ('Show paid invoices as a chart', 'paid', 'chart'), ('Show overdue invoices in a timeline', 'overdue', 'timeline'),
])
def test_request_translates_only_known_read_scope_and_form(message, filt, form):
    assert readout.request_action(request(message)) == {'type': 'show_view', 'view': 'invoices', 'filter': filt, 'form': form}


def test_stream_steps_and_final_receipt_replay_do_not_repeat_read(monkeypatch):
    env = arrange(monkeypatch)
    req = request(client_surface='voice')
    pieces = []
    async def run():
        token = chief._STREAM_SINK.set(pieces.append)
        try:
            first = await chief.chief_chat(req, SESSION)
        finally:
            chief._STREAM_SINK.reset(token)
        second = await chief.chief_chat(req, SESSION)
        return first, second
    first, second = asyncio.run(run())
    assert first == second
    assert sum('/invoices?' in c.args[2] for c in env.db.await_args_list) == 1
    assert env.policy.call_count == 1
    assert env.archive.await_count == 1
    events = [json.loads(p[len(chief.STEP_PREFIX):]) for p in pieces if p.startswith(chief.STEP_PREFIX)]
    assert events and any(e.get('state') == 'done' for e in events)
    assert first['actions_taken'][0]['rows'][0]['number'] == 'DEMO-1'
    assert replay.recover(req, 'different-owner') is None
    replay._receipts.clear()


def test_failed_read_does_not_retry_or_claim_empty_invoices(monkeypatch):
    env = arrange(monkeypatch, rows=None)
    result = asyncio.run(chief.chief_chat(request(), SESSION))
    assert result['actions_taken'][0]['failed']
    assert 'No open invoices match' not in result['response']
    assert sum('/invoices?' in c.args[2] for c in env.db.await_args_list) == 1
    env.context.assert_not_awaited()
    env.model.assert_not_awaited()


def test_revoked_owner_access_cannot_recover_a_cached_invoice_payload(monkeypatch):
    env = arrange(monkeypatch, biz={**BIZ, 'owner_id': 'new-owner'})
    req = request()
    replay.remember(req, SESSION.user.id, {'response': 'Prior private invoice', 'actions_taken': []})
    try:
        with pytest.raises(HTTPException) as err:
            asyncio.run(chief.chief_chat(req, SESSION))
        assert err.value.status_code == 404
        env.policy.assert_not_called()
    finally:
        replay._receipts.clear()
