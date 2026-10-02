"""Image edits travel through the real Chief tool loop and authorization door."""
import asyncio
import contextlib
import json
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

import action_registry
import chief_of_staff as chief
import chief_tool_loop as loop
import image_studio as studio
import llm_call
import mcp_server
from __tests__.test_tool_loop import _FakeResp, _StreamResp, _sse_final


@pytest.fixture(autouse=True)
def reset():
    loop.reset_turn()
    yield
    loop.reset_turn()


@pytest.mark.parametrize('surface,prompted,allowed', [
    ('chat', True, True), ('chat', False, True), ('agent', False, True), ('chat', True, False)])
def test_image_tool_is_only_offered_and_dispatchable_on_prompted_chat(surface, prompted, allowed, monkeypatch):
    door = AsyncMock(return_value=[{'type': 'generate_image', 'result': 'Queued', 'image': {'id': 'new'}}])
    monkeypatch.setattr(chief, '_execute_actions', door)
    loop.reset_turn(allowed, surface=surface, prompted=prompted)
    expected = surface == 'chat' and prompted and allowed
    assert ('generate_image' in {t['name'] for t in loop.tool_definitions_for_turn(allowed)}) == expected
    error, _ = asyncio.run(loop.execute_tool_use(None, {}, 'generate_image', {'prompt': 'Make an image'}))
    assert error != expected
    assert door.await_count == int(expected)
    assert 'generate_image' not in mcp_server.WRITE_TOOL_SCHEMAS
    assert not action_registry.may_expose_to_agent('generate_image', allow_writes=True)


@pytest.mark.parametrize('failed', [False, True])
def test_duplicate_native_and_tag_calls_cannot_pay_twice(failed, monkeypatch):
    door = AsyncMock(return_value=[{'type': 'generate_image', 'result': 'Failed: unavailable' if failed else 'Queued', 'failed': failed}])
    monkeypatch.setattr(chief, '_execute_actions', door)
    async def run():
        loop.reset_turn(True)
        await loop.execute_tool_use(None, {}, 'generate_image', {'prompt': 'Add 90-Day Intensive'})
        error, _ = await loop.execute_tool_use(None, {}, 'generate_image', {'prompt': 'Retry the edit'})
        assert error
        assert loop.remaining_tag_actions([{'type': 'generate_image'}, {'type': 'show_view'}]) == [{'type': 'show_view'}]
        assert len(loop.writes_this_turn()) == 1
    asyncio.run(run())
    door.assert_awaited_once()


@pytest.mark.parametrize('streamed', [False, True])
def test_edit_tool_returns_actual_landscape_job_before_final_reply(streamed, monkeypatch):
    biz = {'id': str(uuid4()), 'owner_id': str(uuid4()), 'settings': {}}
    source_id, new_id = str(uuid4()), str(uuid4())
    args = {'prompt': 'Add 90-Day Intensive beneath 50% OFF. Keep the same layout.', 'reference_ids': [source_id]}
    card = {'id': new_id, 'business_id': biz['id'], 'status': 'queued', 'size': '1536x1024', 'prompt': args['prompt']}
    monkeypatch.setattr(studio, 'db', AsyncMock(return_value=[]))
    owned = AsyncMock(return_value={'id': source_id, 'size': '1536x1024', 'status': 'ready'})
    monkeypatch.setattr(studio, 'artwork', owned)
    create = AsyncMock(return_value=card)
    monkeypatch.setattr(studio, 'create', create)
    monkeypatch.setattr(chief, '_anthropic_key', lambda: 'test-key')
    monkeypatch.setattr(chief, 'log_api_usage', AsyncMock())
    monkeypatch.setattr(chief, '_sb', AsyncMock(return_value=[]))
    payloads = []
    tool = {'type': 'tool_use', 'id': 'image-edit', 'name': 'generate_image', 'input': args}
    def response(payload):
        payloads.append(json.loads(json.dumps(payload)))
        if len(payloads) == 1:
            assert 'generate_image' in {t['name'] for t in payload['tools']}
            return {'stop_reason': 'tool_use', 'usage': {}, 'content': [tool]}
        result = json.loads(payload['messages'][-1]['content'][0]['content'])
        assert result['image'] == card
        assert result.get('_authorized_by')
        return {'stop_reason': 'end_turn', 'usage': {}, 'content': [{'type': 'text', 'text': 'The edit is queued. See the new image card.'}]}
    async def apost(client, payload, **kwargs):
        return _FakeResp(response(payload))
    @contextlib.asynccontextmanager
    async def astream(client, payload, **kwargs):
        body = response(payload)
        if body['stop_reason'] == 'tool_use':
            lines = [
                'data: ' + json.dumps({'type': 'message_start', 'message': {'usage': {}}}),
                'data: ' + json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {**tool, 'input': {}}}),
                'data: ' + json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(args)}}),
                'data: ' + json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}, 'usage': {}}),
            ]
        else:
            lines = _sse_final(body['content'][0]['text'])
        yield _StreamResp(lines)
    monkeypatch.setattr(llm_call, 'apost', apost)
    monkeypatch.setattr(llm_call, 'astream', astream)
    async def run():
        loop.reset_turn(True)
        owner = chief._TURN_USER_ID.set(biz['owner_id'])
        turn = studio.turn_id.set('regression-edit')
        index = studio.turn_image_index.set(0)
        try:
            result = await chief._call_claude(None, 'Use generate_image for the requested edit.',
                [{'role': 'user', 'content': args['prompt']}], enable_web_search=False,
                read_tools=loop.tool_definitions_for_turn(True), tool_biz=biz,
                stream_sink=(lambda text: None) if streamed else None)
            assert 'queued' in result
            assert loop.writes_this_turn()[0]['image'] == card
        finally:
            chief._TURN_USER_ID.reset(owner)
            studio.turn_id.reset(turn)
            studio.turn_image_index.reset(index)
    asyncio.run(run())
    create.assert_awaited_once()
    request = create.call_args.args[0]
    assert request.size == '1536x1024'
    assert [str(i) for i in request.reference_ids] == [source_id]
    owned.assert_awaited_once_with(None, biz['id'], source_id)
    assert len(payloads) == 2


@pytest.mark.parametrize('claim', [
    'Adding "90-Day Intensive" beneath "50% OFF" now, same typography style, same layout otherwise.',
    'Generating the edit now: adding "90-Day Intensive" beneath "50% OFF".',
    "I'm rendering the flyer now.",
])
def test_reported_unsupported_claims_trigger_recovery(claim):
    assert chief._looks_like_completed_action(claim)


@pytest.mark.parametrize('text', ['Would you like me to add a heading?', 'The layout looks good.', 'If you want a new image, say so.'])
def test_discussion_does_not_trigger_recovery(text):
    assert not chief._looks_like_completed_action(text)


def test_workspace_defaults_are_separate_from_user_direction():
    req = chief.ChatRequest(business_id=str(uuid4()), message='same layout', image_preferences={
        'new_image_size': '1024x1536', 'quality': 'high', 'brand': 'Test business'})
    assert req.message == 'same layout'
    assert 'NEW images only' in req.image_preferences.context()
    assert 'preserve the existing artwork' in req.image_preferences.context()


def test_held_image_call_never_reaches_generation(monkeypatch):
    monkeypatch.setattr(chief, 'untrusted_taint', lambda: True)
    create = AsyncMock()
    monkeypatch.setattr(studio, 'create', create)
    async def run():
        loop.reset_turn(True)
        error, text = await loop.execute_tool_use(None, {'id': str(uuid4())}, 'generate_image', {'prompt': 'Edit the flyer'})
        assert error and 'held' in text.lower()
        assert loop.writes_this_turn()[0]['failed']
    asyncio.run(run())
    create.assert_not_awaited()


def test_unexpected_door_failure_is_retained_and_cannot_be_retried(monkeypatch):
    door = AsyncMock(side_effect=RuntimeError('unavailable'))
    monkeypatch.setattr(chief, '_execute_actions', door)
    async def run():
        loop.reset_turn(True)
        error, text = await loop.execute_tool_use(None, {}, 'generate_image', {'prompt': 'Edit the flyer'})
        assert error and 'did not go through' in text
        assert chief._action_failed(loop.writes_this_turn()[0])
        await loop.execute_tool_use(None, {}, 'generate_image', {'prompt': 'Try again'})
        assert loop.remaining_tag_actions([{'type': 'generate_image'}]) == []
    asyncio.run(run())
    door.assert_awaited_once()


@pytest.mark.parametrize('narration', ['The edit is queued.', None])
def test_edit_retry_can_execute_native_tool_and_retain_the_card(monkeypatch, narration):
    card = {'id': str(uuid4()), 'status': 'queued'}
    monkeypatch.setattr(chief, '_execute_actions', AsyncMock(return_value=[{
        'type': 'generate_image', 'result': 'Queued', 'image': card}]))
    async def model(client, system, messages, **kwargs):
        assert kwargs['read_tools']
        await loop.execute_tool_use(None, {}, 'generate_image', {'prompt': 'Add 90-Day Intensive'})
        return narration
    monkeypatch.setattr(chief, '_call_claude', model)
    async def run():
        loop.reset_turn(True)
        actions, clean, _ = await chief._retry_missing_actions(None, 'system', [],
            'Add 90-Day Intensive', 1600, 'test', read_tools=loop.tool_definitions_for_turn(True), tool_biz={})
        assert actions == []
        assert clean == (narration or 'Your image request was accepted. The new image card shows its progress.')
        assert loop.writes_this_turn()[0]['image'] == card
    asyncio.run(run())


@pytest.mark.parametrize('requested,expected', [(None, '1536x1024'), ('1024x1536', '1024x1536')])
def test_edit_retains_size_unless_explicit_resize(requested, expected, monkeypatch):
    monkeypatch.setattr(studio, 'db', AsyncMock(return_value=[]))
    owned = AsyncMock(return_value={'size': '1536x1024'})
    monkeypatch.setattr(studio, 'artwork', owned)
    create = AsyncMock(return_value={})
    monkeypatch.setattr(studio, 'create', create)
    args = {'prompt': 'Add 90-Day Intensive', 'reference_ids': [str(uuid4())]}
    if requested:
        args['size'] = requested
    asyncio.run(studio.handle_generate_image(None, {'id': str(uuid4())}, args))
    assert create.call_args.args[0].size == expected
    assert owned.await_count == int(requested is None)
