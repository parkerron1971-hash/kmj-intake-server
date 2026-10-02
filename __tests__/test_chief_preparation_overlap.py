"""Real chief_chat preparation preserves authorization, freshness and cleanup."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

import billing_context
import billing_limits
import chief_build_runtime
import chief_of_staff as chief
import chief_prewarm
import chief_stream_replay
import chief_truth
import rate_limit
import sb_clients
import vertical_context

BIZ = {'id': 'biz', 'owner_id': 'owner', 'name': 'Fixture', 'type': 'coach',
       'created_at': '2026-01-01', 'settings': {}}
NAMES = ['voice_examples', 'session_context', 'mentor_active', 'forecast',
         'relationship_insights', 'time_block', 'habit_block', 'bookkeeping_block']


@pytest.fixture
def prep(monkeypatch):
    monkeypatch.setattr(rate_limit, 'allow', lambda *a: True)
    monkeypatch.setattr(billing_limits, 'require_chat_fair_use', lambda *a: None)
    monkeypatch.setattr(billing_limits, 'require_units', lambda *a: None)
    monkeypatch.setattr(chief_build_runtime, 'enabled', lambda: False)
    monkeypatch.setattr(chief, '_generate_missing_recurring_instances', AsyncMock(return_value=[]))
    monkeypatch.setattr(chief, '_sb', AsyncMock(return_value=[dict(BIZ)]))
    monkeypatch.setattr(chief, '_spawn_turn_sweeps', Mock())
    monkeypatch.setattr(chief, '_spawn_proactive_suggestions', Mock())
    monkeypatch.setattr(chief, '_fetch_view_detail', AsyncMock(return_value=None))
    monkeypatch.setattr(chief, '_setup_snapshot_wanted', lambda *a, **k: False)
    context = AsyncMock(return_value={'business': dict(BIZ), 'contacts_total': 10, 'sessions': []})
    monkeypatch.setattr(chief, '_gather_context', context)
    warm = Mock(return_value={})
    monkeypatch.setattr(chief_prewarm, 'take', warm)
    learned = Mock(return_value='learned')
    monkeypatch.setattr(vertical_context, 'build_vertical_learned_block', learned)
    replay = AsyncMock(return_value=None)
    monkeypatch.setattr(chief_stream_replay, 'recover_async', replay)
    factory_calls = []
    def sources(client, biz):
        async def fetch(name):
            factory_calls.append((name, biz['type']))
            return 'fresh:' + biz['type']
        return {name: (lambda n=name: fetch(n), '') for name in NAMES}
    source_factory = Mock(side_effect=sources)
    monkeypatch.setattr(chief, '_context_sources', source_factory)
    captured = {}
    def reached_prompt_setup(_):
        captured['sources'] = dict(chief_truth._turn.get().sources)
        raise HTTPException(490, 'preparation complete')
    monkeypatch.setattr(chief, '_format_setup_block', reached_prompt_setup)
    model = AsyncMock()
    monkeypatch.setattr(chief, '_call_claude', model)
    return SimpleNamespace(context=context, warm=warm, learned=learned, replay=replay,
                           sources=source_factory, calls=factory_calls, captured=captured, model=model)


async def request(*, streamed=True, message='Help me think through a customer conversation'):
    token = chief._STREAM_SINK.set((lambda _: None) if streamed else None)
    try:
        return await chief.chief_chat(chief.ChatRequest(business_id='biz', message=message,
                                     client_surface='voice'),
                                     SimpleNamespace(token='jwt-owner', user=SimpleNamespace(id='owner')))
    finally:
        chief._STREAM_SINK.reset(token)


def test_learned_retrieval_overlaps_snapshot_with_scoped_context(prep, monkeypatch):
    started, release = threading.Event(), threading.Event()
    observed = []
    def learned(biz, message):
        observed.append((biz, message, sb_clients.get_current_user_jwt(), billing_context.current()))
        started.set()
        release.wait(2)
        return 'learned'
    monkeypatch.setattr(vertical_context, 'build_vertical_learned_block', learned)
    async def context(*args, **kwargs):
        assert await asyncio.to_thread(started.wait, 1), 'enrichment waited for the whole snapshot'
        release.set()
        return {'business': dict(BIZ), 'contacts_total': 10, 'sessions': []}
    monkeypatch.setattr(chief, '_gather_context', context)
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(request())
        assert exc.value.status_code == 490
    finally:
        release.set()
    assert observed == [(BIZ, 'Help me think through a customer conversation', 'jwt-owner', 'biz')]
    assert len(prep.calls) == 8
    prep.warm.assert_called_once_with('owner', 'biz')
    prep.model.assert_not_awaited()


@pytest.mark.parametrize('denial', ['billing', 'missing', 'wrong_owner'])
def test_no_preparation_before_admission_and_scoped_business(prep, monkeypatch, denial):
    if denial == 'billing':
        def denied(*args): raise HTTPException(402, 'allowance')
        monkeypatch.setattr(billing_limits, 'require_units', denied)
    else:
        monkeypatch.setattr(chief, '_sb', AsyncMock(return_value=[] if denial == 'missing' else [{**BIZ, 'owner_id': 'other'}]))
        prep.context.return_value = None
    with pytest.raises(HTTPException) as exc:
        asyncio.run(request())
    assert exc.value.status_code == (402 if denial == 'billing' else 404)
    prep.sources.assert_not_called()
    prep.learned.assert_not_called()
    prep.warm.assert_not_called()


def test_post_replay_has_no_extra_retrieval(prep):
    prep.replay.return_value = {'response': 'already completed', 'actions_taken': []}
    result = asyncio.run(request(streamed=False))
    assert result == prep.replay.return_value
    prep.sources.assert_not_called()
    prep.learned.assert_not_called()
    prep.warm.assert_not_called()


def test_feedback_does_not_start_unused_retrieval(prep, monkeypatch):
    monkeypatch.setattr(chief, '_archive_turn', AsyncMock())
    result = asyncio.run(request(message='Um...'))
    assert result['response'] == 'Take your time.'
    prep.sources.assert_not_called()
    prep.learned.assert_not_called()
    prep.warm.assert_not_called()


@pytest.mark.parametrize('exit_kind', ['cancel', 'denied_snapshot'])
def test_pending_reads_drain_before_http_client_closes(prep, monkeypatch, exit_kind):
    async def run():
        started = asyncio.Event()
        observed = []
        def sources(client, biz):
            async def waiting():
                started.set()
                try: await asyncio.Future()
                finally: observed.append(('drained', client.is_closed))
            return {'voice_examples': (waiting, '')}
        monkeypatch.setattr(chief, '_context_sources', sources)
        async def context(*args, **kwargs):
            await started.wait()
            if exit_kind == 'denied_snapshot': return None
            await asyncio.Future()
        monkeypatch.setattr(chief, '_gather_context', context)
        task = asyncio.create_task(request())
        await started.wait()
        if exit_kind == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        else:
            with pytest.raises(HTTPException) as exc: await task
            assert exc.value.status_code == 404
        assert observed == [('drained', False)]
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    asyncio.run(run())


def test_changed_authoritative_business_rebuilds_prep_without_reconsuming_warm(prep):
    prep.context.return_value['business'] = {**BIZ, 'type': 'consultant'}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(request())
    assert exc.value.status_code == 490
    assert [call.args[1]['type'] for call in prep.sources.call_args_list] == ['coach', 'consultant']
    prep.warm.assert_called_once()
    assert 'consultant' in prep.captured['sources']['context:voice_examples']['text']


def test_warm_sources_do_not_construct_duplicate_reads(prep):
    prep.warm.return_value = {name: 'warm value' for name in NAMES}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(request())
    assert exc.value.status_code == 490
    assert prep.calls == []
    prep.warm.assert_called_once()


def test_failed_optional_source_keeps_unavailable_marker(prep, monkeypatch):
    original = prep.sources.side_effect
    def sources(client, biz):
        result = original(client, biz)
        async def broken(): raise RuntimeError('fixture source unavailable')
        result['voice_examples'] = (broken, '')
        return result
    prep.sources.side_effect = sources
    with pytest.raises(HTTPException) as exc:
        asyncio.run(request())
    assert exc.value.status_code == 490
    assert 'context:voice_examples' not in prep.captured['sources']
    assert 'context:session_context' in prep.captured['sources']


def test_snapshot_failure_drains_the_other_read_before_client_close(prep, monkeypatch):
    async def run():
        started = asyncio.Event()
        observed = []
        async def view(client, *args):
            started.set()
            try: await asyncio.Future()
            finally: observed.append(client.is_closed)
        async def context(*args, **kwargs):
            await started.wait()
            raise HTTPException(503, 'snapshot unavailable')
        monkeypatch.setattr(chief, '_fetch_view_detail', view)
        monkeypatch.setattr(chief, '_gather_context', context)
        with pytest.raises(HTTPException) as exc: await request()
        assert exc.value.status_code == 503
        assert observed == [False]
    asyncio.run(run())


def test_setup_probe_still_waits_for_authoritative_snapshot(prep, monkeypatch):
    order = []
    async def context(*args, **kwargs):
        await asyncio.sleep(0)
        order.append('snapshot')
        return {'business': dict(BIZ), 'contacts_total': 0, 'sessions': []}
    def wanted(*args, **kwargs):
        assert order == ['snapshot']
        return True
    def setup(biz):
        order.append('setup')
        return None
    monkeypatch.setattr(chief, '_gather_context', context)
    monkeypatch.setattr(chief, '_setup_snapshot_wanted', wanted)
    monkeypatch.setattr(chief, '_fetch_setup_snapshot', setup)
    with pytest.raises(HTTPException) as exc: asyncio.run(request())
    assert exc.value.status_code == 490
    assert order == ['snapshot', 'setup']
