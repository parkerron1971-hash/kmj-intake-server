import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
import chief_call_feedback as feedback
import chief_of_staff as chief
import chief_fast_track as fast
import chief_stream_replay as replay
import model_router
import route_ledger


@pytest.mark.parametrize('message', [
    'You can hear the background too.', 'Okay, I heard it twice.',
    'Can you hear me?', 'Let me end that one.', 'Dobrý den.',
])
@pytest.mark.parametrize('allowed', [True, False])
def test_feedback_is_scoped_archived_and_never_runs_another_action(monkeypatch, message, allowed):
    import billing_limits
    import rate_limit
    import chief_build_runtime
    monkeypatch.setattr(rate_limit, 'allow', lambda *a: True)
    monkeypatch.setattr(billing_limits, 'require_chat_fair_use', lambda *a: None)
    monkeypatch.setattr(billing_limits, 'require_units', lambda *a: None)
    monkeypatch.setattr(chief_build_runtime, 'enabled', lambda: False)
    monkeypatch.setattr(chief, '_generate_missing_recurring_instances', AsyncMock(return_value=[]))
    monkeypatch.setattr(chief, '_sb', AsyncMock(return_value=[]))
    context = AsyncMock(return_value={'business': {'id': 'business'}} if allowed else None)
    monkeypatch.setattr(chief, '_gather_context', context)
    monkeypatch.setattr(chief, '_fetch_view_detail', AsyncMock(return_value=None))
    archive, model, actions = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(chief, '_archive_turn', archive)
    monkeypatch.setattr(chief, '_call_claude', model)
    monkeypatch.setattr(chief, '_execute_actions', actions)
    replay._receipts.clear()
    req = chief.ChatRequest(business_id='business', message=message, client_surface='voice',
                            request_id='feedback-turn', history=[
                                chief.ChatMessage(role='assistant', content='I will show your open invoices.')])
    session = SimpleNamespace(token='fixture-jwt', user=SimpleNamespace(id='owner'))
    async def run():
        token = chief._STREAM_SINK.set(lambda _: None)
        try:
            return await chief.chief_chat(req, session)
        finally:
            chief._STREAM_SINK.reset(token)
    if allowed:
        result = asyncio.run(run())
        assert result['response'] == feedback.for_request(req)
        assert result['actions_taken'] == []
        assert result['grounding']['status'] == 'acknowledged'
        archive.assert_awaited_once()
        assert replay.recover(req, 'owner') == result
        assert replay.recover(req, 'someone-else') is None
    else:
        with pytest.raises(HTTPException) as error:
            asyncio.run(run())
        assert error.value.status_code == 404
        archive.assert_not_awaited()
    model.assert_not_awaited()
    actions.assert_not_awaited()
    context.assert_awaited_once()
    replay._receipts.clear()


@pytest.mark.parametrize('message', [
    'Can you hear me and show all invoices?', 'Stop the recurring invoice.',
    'I heard it twice; can you change the invoice?',
    'You can hear the background too. Please show my calendar.',
])
def test_mixed_business_requests_are_not_swallowed(message):
    assert feedback.reply_for(message, voice=True) is None


def test_other_modes_and_images_keep_their_normal_path():
    for changes in ({'mode': 'strategy_coach'}, {'image_ids': ['image']}):
        req = SimpleNamespace(message='Can you hear me?', **changes)
        assert feedback.for_request(req) is None


def test_call_feedback_has_no_model_opening():
    req = chief.ChatRequest(business_id='business', message='You can hear the background too.', client_surface='voice')
    rec = route_ledger.RouteRecord(arrived=time.perf_counter(), business_id='business', user_id='owner')
    complexity = model_router.score(req.message)
    track = fast.TwoTrack(req, 'owner', rec, complexity, model_router.Route(model_router.LANE_FULL, 'fixture'))
    assert not track.model_opener
