"""The scheduling route checks access, avoids writes and speaks before archiving."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

import chief_of_staff as chief
import chief_availability_readout as readout
import chief_stream_replay as replay
import sb_clients

BIZ = {'id': 'fixture-biz', 'owner_id': 'fixture-owner', 'settings': {}}
SESSION = SimpleNamespace(token='fixture-token', user=SimpleNamespace(id='fixture-owner'))
TEXT = ('Check whether two consultation appointments would fit next Tuesday at '
        '10:00 and 10:30 a.m., using my business timezone. Check them together '
        "against my existing bookings and capacity. Don't book or change anything.")
RESULT = {'response': 'Those times conflict. Nothing was booked.', 'actions_taken': [],
          'grounding': {'status': 'records', 'sources': ['availability']}}


def request(**kwargs):
    return chief.ChatRequest(business_id=BIZ['id'], message=TEXT,
                             request_id='availability-fixture', **kwargs)


def arrange(monkeypatch, biz=BIZ):
    import chief_availability
    import billing_limits
    import rate_limit
    rate = Mock(return_value=True)
    fair, units = Mock(), Mock()
    monkeypatch.setattr(rate_limit, 'allow', rate)
    monkeypatch.setattr(billing_limits, 'require_chat_fair_use', fair)
    monkeypatch.setattr(billing_limits, 'require_units', units)
    recurrence, sweeps = AsyncMock(return_value=[]), Mock()
    monkeypatch.setattr(chief, '_generate_missing_recurring_instances', recurrence)
    monkeypatch.setattr(chief, '_spawn_turn_sweeps', sweeps)
    context = AsyncMock(return_value=None)
    monkeypatch.setattr(chief, '_gather_context', context)
    monkeypatch.setattr(chief, '_fetch_view_detail', AsyncMock(return_value={}))
    model = AsyncMock(side_effect=AssertionError('No model on checked scheduling route'))
    monkeypatch.setattr(chief, '_call_claude', model)
    archive = AsyncMock()
    monkeypatch.setattr(chief, '_archive_turn', archive)
    checker = AsyncMock(return_value=deepcopy(RESULT))
    monkeypatch.setattr(chief_availability, 'check_request', checker)

    async def db(client, method, path, *args):
        assert sb_clients.get_current_user_jwt() == SESSION.token
        assert method == 'GET'
        assert path == '/businesses?id=eq.fixture-biz&select=*&limit=1'
        return [deepcopy(biz)] if biz else []
    db_mock = AsyncMock(side_effect=db)
    monkeypatch.setattr(chief, '_sb', db_mock)
    replay._receipts.clear()
    return SimpleNamespace(rate=rate, fair=fair, units=units, recurrence=recurrence,
                           sweeps=sweeps, context=context, model=model, archive=archive,
                           checker=checker, db=db_mock)


def test_checked_route_skips_model_context_and_housekeeping(monkeypatch):
    env = arrange(monkeypatch)
    result = asyncio.run(chief.chief_chat(request(), SESSION))
    assert result == RESULT
    env.checker.assert_awaited_once()
    assert env.checker.call_args.args[2] == BIZ
    env.context.assert_not_awaited()
    env.model.assert_not_awaited()
    env.recurrence.assert_not_awaited()
    env.sweeps.assert_not_called()
    env.archive.assert_awaited_once()
    env.rate.assert_called_once()
    env.fair.assert_called_once_with(BIZ['id'])
    env.units.assert_called_once_with(BIZ['id'])
    assert sb_clients.get_current_user_jwt() != SESSION.token


@pytest.mark.parametrize('gate,code', [('rate', 429), ('fair', 429), ('units', 402)])
def test_admission_precedes_schedule_reads(monkeypatch, gate, code):
    env = arrange(monkeypatch)
    if gate == 'rate':
        env.rate.return_value = False
    else:
        getattr(env, gate).side_effect = HTTPException(code, 'Fixture refusal')
    with pytest.raises(HTTPException) as err:
        asyncio.run(chief.chief_chat(request(), SESSION))
    assert err.value.status_code == code
    env.db.assert_not_awaited()
    env.checker.assert_not_awaited()


@pytest.mark.parametrize('biz', [None, {**BIZ, 'id': 'other-biz'},
                                {**BIZ, 'owner_id': 'other-owner'}, {**BIZ, 'owner_id': None}])
def test_scope_checked_before_calculation_or_replay(monkeypatch, biz):
    env = arrange(monkeypatch, biz)
    req = request()
    replay.remember(req, SESSION.user.id, RESULT)
    try:
        with pytest.raises(HTTPException) as err:
            asyncio.run(chief.chief_chat(req, SESSION))
        assert err.value.status_code == 404
        env.checker.assert_not_awaited()
    finally:
        replay._receipts.clear()


def test_checked_audio_precedes_archive_and_retry_does_not_repeat_check(monkeypatch):
    env = arrange(monkeypatch)
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        pieces = []
        async def archive(*args):
            entered.set()
            await release.wait()
        env.archive.side_effect = archive
        token = chief._STREAM_SINK.set(pieces.append)
        req = request(client_surface='voice')
        task = asyncio.create_task(chief.chief_chat(req, SESSION))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert pieces == [chief.PROSE_PREFIX + RESULT['response']]
            assert not task.done()
            release.set()
            first = await task
        finally:
            release.set()
            chief._STREAM_SINK.reset(token)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        second = await chief.chief_chat(req, SESSION)
        assert first == second
    try:
        asyncio.run(run())
        env.checker.assert_awaited_once()
        env.archive.assert_awaited_once()
    finally:
        replay._receipts.clear()


def test_cancellation_never_emits_unfinished_check(monkeypatch):
    env = arrange(monkeypatch)
    async def run():
        entered = asyncio.Event()
        async def checking(*args):
            entered.set()
            await asyncio.Future()
        env.checker.side_effect = checking
        pieces = []
        token = chief._STREAM_SINK.set(pieces.append)
        task = asyncio.create_task(chief.chief_chat(request(), SESSION))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert pieces == []
            env.archive.assert_not_awaited()
        finally:
            chief._STREAM_SINK.reset(token)
    asyncio.run(run())


def test_readout_rejects_action_payload(monkeypatch):
    env = arrange(monkeypatch)
    env.checker.return_value = {**RESULT, 'actions_taken': [{'type': 'create_booking'}]}
    with pytest.raises(ValueError):
        asyncio.run(readout.serve_request(None, request(), SESSION, BIZ))
    env.archive.assert_not_awaited()


def test_stream_final_matches_checked_speech_without_generic_caveat(monkeypatch):
    env = arrange(monkeypatch)
    import chief_fast_track
    monkeypatch.setattr(chief_fast_track, 'plan', lambda *args: None)
    async def run():
        stream = await chief.chief_chat_stream(request(client_surface='voice'), SESSION)
        frames = [frame async for frame in stream.body_iterator]
        events = [json.loads(frame.removeprefix('data: ').strip())
                  for frame in frames if frame.startswith('data: ')]
        spoken = ''.join(event['text'] for event in events if event['type'] == 'delta')
        final = next(event['payload'] for event in events if event['type'] == 'final')
        assert spoken == RESULT['response'] == final['response']
        assert "couldn't verify" not in spoken and 'No action ran' not in spoken
        assert final['actions_taken'] == []
    try:
        asyncio.run(run())
        env.checker.assert_awaited_once()
        env.model.assert_not_awaited()
    finally:
        replay._receipts.clear()


def test_appointment_question_never_routes_to_record_free_answer():
    import model_router
    decision = model_router.decide(model_router.score(TEXT))
    assert decision.lane == model_router.LANE_FULL
