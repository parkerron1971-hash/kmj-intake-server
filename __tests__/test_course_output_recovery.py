"""Course tools must save before a streamed promise becomes the final reply."""
import asyncio
import contextlib
import copy
import json

import pytest
import chief_of_staff as cos
import chief_tool_loop as ctl
import llm_call
from chief_academy_actions import COURSE_AUTHORING_MAX_TOKENS, COURSE_INCOMPLETE_REPLY


def response(name=None, text='', stop=None):
    content = [{'type': 'text', 'text': text}] if text else []
    if name:
        content.append({'type': 'tool_use', 'id': name, 'name': name,
                        'input': {'request_key': 'same-save', 'lessons': [{'title': 'Week 1'}]}})
    return {'content': content, 'stop_reason': stop or ('tool_use' if name else 'end_turn'),
            'usage': {'input_tokens': 20, 'output_tokens': 1600 if stop == 'max_tokens' else 30}}


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body
        self.text = json.dumps(body)

    def json(self):
        return self.body

    async def aiter_lines(self):
        for i, block in enumerate(self.body['content']):
            yield 'data: ' + json.dumps({'type': 'content_block_start', 'index': i, 'content_block': block})
            if block['type'] == 'text':
                delta = {'type': 'text_delta', 'text': block['text']}
            else:
                value = json.dumps(block['input'])
                if self.body['stop_reason'] == 'max_tokens':
                    value = value[:12]  # A truly incomplete tool payload must never be dispatched.
                delta = {'type': 'input_json_delta', 'partial_json': value}
            yield 'data: ' + json.dumps({'type': 'content_block_delta', 'index': i, 'delta': delta})
        yield 'data: ' + json.dumps({'type': 'message_delta', 'delta': {'stop_reason': self.body['stop_reason']}, 'usage': self.body['usage']})


@pytest.fixture
def run_model(monkeypatch):
    async def noop(*args, **kwargs):
        pass
    monkeypatch.setattr(cos, '_anthropic_key', lambda: 'test-key')
    monkeypatch.setattr(cos, 'log_api_usage', noop)
    monkeypatch.setattr(cos.asyncio, 'sleep', noop)

    def run(scripts, streaming):
        payloads, executed, sunk = [], [], []

        def next_response(payload):
            payloads.append(copy.deepcopy(payload))
            return Response(scripts[len(payloads) - 1])

        async def post(client, payload, **kwargs):
            return next_response(payload)

        @contextlib.asynccontextmanager
        async def stream(client, payload, **kwargs):
            yield next_response(payload)

        async def tool_round(client, biz, content, count):
            tools = [b for b in content if b['type'] == 'tool_use']
            executed.extend(tools)
            return ({'role': 'assistant', 'content': content},
                    {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': b['id'], 'content': '{"saved":true}'} for b in tools]}, len(tools))

        monkeypatch.setattr(llm_call, 'apost', post)
        monkeypatch.setattr(llm_call, 'astream', stream)
        monkeypatch.setattr(ctl, 'run_tool_round', tool_round)
        result = asyncio.run(cos._call_claude(None, 'SYSTEM', [{'role': 'user', 'content': 'Build my course'}],
            max_tokens=1600, enable_web_search=False, read_tools=ctl.read_tool_definitions(),
            tool_biz={'id': 'test'}, stream_sink=sunk.append if streaming else None))
        return result, payloads, executed, sunk
    return run


@pytest.mark.parametrize('streaming', [True, False])
def test_lookup_gives_the_course_save_room_before_generation(run_model, streaming):
    result, payloads, executed, _ = run_model([
        response('inspect_course'), response('save_course_content', 'Building now.'), response(text='Saved the course.')
    ], streaming)
    assert [p['max_tokens'] for p in payloads] == [1600, COURSE_AUTHORING_MAX_TOKENS, COURSE_AUTHORING_MAX_TOKENS]
    assert [t['name'] for t in executed] == ['inspect_course', 'save_course_content']
    assert result.endswith('Saved the course.')


@pytest.mark.parametrize('streaming', [True, False])
def test_truncated_course_call_retries_without_executing_partial_json(run_model, streaming):
    result, payloads, executed, sunk = run_model([
        response('save_course_content', 'Building now.', 'max_tokens'),
        response('save_course_content', 'Building now.'), response(text='Saved the course.')
    ], streaming)
    assert len(executed) == 1
    assert executed[0]['input']['request_key'] == 'same-save'
    assert payloads[0]['messages'] == payloads[1]['messages']
    assert payloads[1]['max_tokens'] == COURSE_AUTHORING_MAX_TOKENS
    assert result.endswith('Saved the course.')
    if streaming:
        assert ''.join(sunk).count('Building now.') == 1


@pytest.mark.parametrize('streaming', [True, False])
def test_second_truncation_is_explicit_and_bounded(run_model, streaming):
    result, payloads, executed, _ = run_model([
        response('save_course_content', 'Building now.', 'max_tokens'),
        response('save_course_content', 'Building now.', 'max_tokens')
    ], streaming)
    assert result == COURSE_INCOMPLETE_REPLY
    assert len(payloads) == 2
    assert not executed


@pytest.mark.parametrize('streaming', [True, False])
def test_normal_tool_round_keeps_chat_budget(run_model, streaming):
    _, payloads, _, _ = run_model([response('check_goals'), response(text='Two goals.')], streaming)
    assert all(p['max_tokens'] == 1600 for p in payloads)


def test_silent_course_work_gets_stream_heartbeats(monkeypatch):
    real_wait = asyncio.wait

    async def quick_wait(tasks, **kwargs):
        assert kwargs['timeout'] == 15
        return await real_wait(tasks, timeout=0.001, return_when=kwargs['return_when'])

    async def check():
        finish = asyncio.Event()

        async def chat(*args):
            await finish.wait()
            return {'response': 'Saved.', 'actions_taken': []}

        monkeypatch.setattr(cos, 'chief_chat', chat)
        monkeypatch.setattr(cos.asyncio, 'wait', quick_wait)
        stream = await cos.chief_chat_stream(cos.ChatRequest(business_id='test', message='Build course'), None)
        it = stream.body_iterator
        assert (await anext(it)).startswith(':')
        assert await anext(it) == ': keep-alive\n\n'
        finish.set()
        assert '"type": "final"' in await anext(it)
        await it.aclose()
    asyncio.run(check())
