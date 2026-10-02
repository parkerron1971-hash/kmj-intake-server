"""Exercise admission, the real UI action door, speech and replay together."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import audit_log
import chief_of_staff as chief
import chief_quick_plan as quick
import chief_stream_replay as replay
import policy_engine
from __tests__.test_chief_preparation_overlap import prep

MESSAGE = ('Show me a short suggested plan for the next two days. '
           'Only show the plan; do not create tasks, send messages, or change records.')
SESSION = SimpleNamespace(token='jwt-owner', user=SimpleNamespace(id='owner'))


def setup(monkeypatch, prep, allowed=True):
    monkeypatch.setattr(quick.llm_call, 'api_key', lambda: '')
    archive, activity, audit = AsyncMock(), AsyncMock(), Mock()
    monkeypatch.setattr(chief, '_archive_turn', archive)
    monkeypatch.setattr(chief, '_log_chief_activity', activity)
    monkeypatch.setattr(audit_log, 'record_chief_turn', audit)
    policy = Mock(return_value=SimpleNamespace(allowed=allowed, rule='owner', reason='Permission denied'))
    monkeypatch.setattr(policy_engine, 'evaluate', policy)
    prep.context.return_value.update({
        'open_invoices': [{'number': 'DEMO-4', 'client': 'Ada Sample', 'status': 'sent'}],
        'sms_messages': [{'read': False}], 'queue': [{'id': 'draft'}]})
    # Use the actual scoped in-process stream recovery.
    monkeypatch.setattr(replay, 'recover_async', AsyncMock(side_effect=lambda req, user: replay.recover(req, user)))
    replay._receipts.clear()
    return SimpleNamespace(archive=archive, activity=activity, audit=audit, policy=policy)


@pytest.mark.parametrize('allowed', [True, False])
def test_real_chat_uses_only_ui_action_and_replays_checked_reply(prep, monkeypatch, allowed):
    env = setup(monkeypatch, prep, allowed)
    req = chief.ChatRequest(business_id='biz', message=MESSAGE,
                            client_surface='voice', request_id='quick-plan-integration')
    pieces = []
    async def run():
        token = chief._STREAM_SINK.set(pieces.append)
        try:
            result = await chief.chief_chat(req, SESSION)
        finally:
            chief._STREAM_SINK.reset(token)
        replayed = await chief.chief_chat(req, SESSION)
        return result, replayed
    try:
        result, replayed = asyncio.run(run())
        assert result == replayed
        prep.sources.assert_not_called()
        prep.learned.assert_not_called()
        prep.model.assert_not_awaited()
        env.policy.assert_called_once()
        assert env.policy.call_args.kwargs['verb'] == 'show_plan'
        assert env.policy.call_args.kwargs['user_id'] == 'owner'
        env.archive.assert_awaited_once()
        env.audit.assert_called_once()
        assert [p[len(chief.PROSE_PREFIX):] for p in pieces if p.startswith(chief.PROSE_PREFIX)] == [result['response']]
        if allowed:
            card = result['actions_taken'][0]
            assert result['grounding']['status'] == 'proposed'
            assert card['_authorized_by'] == 'owner'
            assert len(card['steps']) == 4
            for row in card['steps']:
                assert row['step'].rstrip('.') in result['response']
            assert 'Ada Sample' in result['response'] and 'DEMO-4' in result['response']
        else:
            assert result['actions_taken'][0]['failed']
            assert 'Ada Sample' not in result['response']
    finally:
        replay._receipts.clear()


def test_plan_speech_precedes_slow_archive(prep, monkeypatch):
    env = setup(monkeypatch, prep)
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        pieces = []
        async def archive(*args, **kwargs):
            entered.set()
            await release.wait()
        env.archive.side_effect = archive
        token = chief._STREAM_SINK.set(pieces.append)
        task = asyncio.create_task(chief.chief_chat(chief.ChatRequest(business_id='biz', message=MESSAGE), SESSION))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert not task.done()
            assert any(p.startswith(chief.PROSE_PREFIX) and 'DEMO-4' in p for p in pieces)
            release.set()
            result = await task
            assert [p[len(chief.PROSE_PREFIX):] for p in pieces if p.startswith(chief.PROSE_PREFIX)] == [result['response']]
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            chief._STREAM_SINK.reset(token)
    asyncio.run(run())
