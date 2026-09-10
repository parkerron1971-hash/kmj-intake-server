import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
import sb_clients
import chief_of_staff as chief
from __tests__.test_gather_context_wave2 import gather


@pytest.mark.parametrize('header,expected', [('0-0/725', 725), ('*/0', 0), ('0-0/*', None), ('', None)])
def test_count_uses_exact_range_with_users_rls(monkeypatch, header, expected):
    monkeypatch.setenv('SUPABASE_URL', 'https://db.example')
    client = type('Client', (), {'request': AsyncMock(return_value=httpx.Response(200,
        headers={'content-range': header}))})()
    with sb_clients.with_user_jwt('user-jwt'):
        result = asyncio.run(sb_clients.sb_count_as_current_context(client, '/contacts?business_id=eq.biz'))
    assert result == expected
    assert client.request.call_args.args[0] == 'HEAD'
    headers = client.request.call_args.kwargs['headers']
    assert headers['Authorization'] == 'Bearer user-jwt'
    assert headers['Prefer'] == 'count=exact'


def test_failed_user_count_never_retries_with_service_credentials(monkeypatch):
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'service-test-key')
    client = type('Client', (), {'request': AsyncMock(return_value=httpx.Response(403))})()
    with sb_clients.with_user_jwt('user-jwt'):
        assert asyncio.run(sb_clients.sb_count_as_current_context(client, '/contacts',
            allow_service_fallback=True)) is None
    assert client.request.await_count == 1
    assert client.request.call_args.kwargs['headers']['Authorization'] == 'Bearer user-jwt'


@pytest.mark.parametrize('exact', [725, None])
def test_context_never_calls_a_capped_page_the_total(gather, monkeypatch, exact):
    original = chief._sb
    async def rows(client, method, path, body=None):
        if path.startswith('/contacts?'):
            return [{'id': str(i), 'name': f'Person {i}', 'status': 'active'} for i in range(500)]
        return await original(client, method, path, body)
    monkeypatch.setattr(chief, '_sb', rows)
    monkeypatch.setattr(chief, '_sb_count', AsyncMock(return_value=exact))
    _, ctx = gather(query_text=None)
    assert ctx['contacts_total'] == exact
    assert ctx['contacts_loaded'] == 500
    assert ctx['contacts_complete'] is False
    prompt = chief._format_context_for_prompt(ctx)
    assert 'CONTACTS: 500 total' not in prompt
    assert 'loaded sample only' in prompt
    assert f"CONTACTS: {exact if exact is not None else 'unknown'} total" in prompt


def test_module_counts_can_exceed_500(gather, monkeypatch):
    monkeypatch.setattr(chief, '_sb_count', AsyncMock(return_value=901))
    _, ctx = gather(query_text=None)
    assert all(count == 901 for count in ctx['module_counts'].values())


def test_failed_profile_source_is_disclosed(gather, monkeypatch):
    def fail(*args):
        raise RuntimeError('down')
    monkeypatch.setattr(chief, 'bp_chief_context_block', fail)
    _, ctx = gather(query_text=None)
    assert ctx['context_quality']['unavailable']
    assert 'do not infer absence' in chief._format_context_for_prompt(ctx)
