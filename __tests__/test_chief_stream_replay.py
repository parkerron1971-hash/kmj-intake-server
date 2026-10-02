import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
import chief_of_staff as chief
import chief_stream_replay as replay


@pytest.fixture(autouse=True)
def clean_receipts():
    replay._receipts.clear()
    yield
    replay._receipts.clear()


def request(**kwargs):
    return chief.ChatRequest(**{'business_id': 'business', 'message': 'Fix Week 3',
                               'request_id': 'one-ui-turn', **kwargs})


def result():
    return {'response': 'Removed the placeholder and saved Week 3.',
            'actions_taken': [{'type': 'save_course_content', 'result': 'saved',
                               'frontend_event': {'name': 'solutionist-course-updated'}}]}


def test_lost_final_event_replay_preserves_saved_message_and_navigation():
    payload = result()
    replay.remember(request(), 'owner', payload)
    payload['actions_taken'].clear()
    assert replay.recover(request(), 'owner') == result()
    recovered = replay.recover(request(), 'owner')
    recovered['actions_taken'].clear()
    assert replay.recover(request(), 'owner') == result()


def test_replay_is_scoped_to_user_business_and_exact_request():
    replay.remember(request(), 'owner', result())
    assert replay.recover(request(), 'other-user') is None
    for changes in ({'business_id': 'other'}, {'request_id': 'new-ui-turn'},
                    {'message': 'Create a different course'}, {'request_id': None}):
        assert replay.recover(request(**changes), 'owner') is None


def test_missing_request_id_is_never_cached():
    replay.remember(request(request_id=None), 'owner', result())
    assert not replay._receipts


def test_receipts_expire_and_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(replay.time, 'monotonic', lambda: 100)
    for index in range(replay.MAX_ENTRIES + 1):
        replay.remember(request(request_id=str(index)), 'owner', result())
    assert len(replay._receipts) == replay.MAX_ENTRIES
    assert replay.recover(request(request_id='0'), 'owner') is None
    monkeypatch.setattr(replay.time, 'monotonic', lambda: 100 + replay.TTL_SECONDS)
    assert replay.recover(request(request_id='1'), 'owner') is None
    assert not replay._receipts


def test_oversized_results_are_not_retained():
    replay.remember(request(), 'owner', {'response': 'x' * replay.MAX_PAYLOAD_BYTES})
    assert not replay._receipts


@pytest.mark.parametrize('allowed', [True, False])
def test_plain_endpoint_reuses_receipt_only_after_session_context_read(monkeypatch, allowed):
    import billing_limits
    import rate_limit
    monkeypatch.setattr(rate_limit, 'allow', lambda *a: True)
    monkeypatch.setattr(billing_limits, 'require_chat_fair_use', lambda *a: None)
    monkeypatch.setattr(billing_limits, 'require_units', lambda *a: None)
    monkeypatch.setattr(chief, '_generate_missing_recurring_instances', AsyncMock(return_value=[]))
    monkeypatch.setattr(chief, '_sb', AsyncMock(return_value=[]))
    context = AsyncMock(return_value={'business': {'id': 'business'}} if allowed else None)
    monkeypatch.setattr(chief, '_gather_context', context)
    monkeypatch.setattr(chief, '_fetch_view_detail', AsyncMock(return_value=None))
    model = AsyncMock()
    monkeypatch.setattr(chief, '_call_claude', model)
    replay.remember(request(), 'owner', result())
    session = SimpleNamespace(token='test-session', user=SimpleNamespace(id='owner'))
    if allowed:
        assert asyncio.run(chief.chief_chat(request(), session)) == result()
    else:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(chief.chief_chat(request(), session))
        assert exc.value.status_code == 404
    context.assert_awaited_once()
    model.assert_not_called()
