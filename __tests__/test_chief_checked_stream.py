import asyncio
import json

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

import chief_of_staff as chief


@pytest.mark.parametrize('failure', [None, 'exception', 'json_response'])
def test_only_checked_reply_reaches_text_and_speech(monkeypatch, failure):
    async def run():
        release = asyncio.Event()
        async def fake_chat(req, session):
            sink = chief._STREAM_SINK.get()
            sink("I've sent the email.")
            chief._turn_status('checking the result')
            await release.wait()
            if failure == 'exception':
                raise HTTPException(503, 'unavailable')
            if failure == 'json_response':
                return JSONResponse({'error': 'unavailable'}, status_code=500)
            return {'response': 'The email failed. Nothing was sent.', 'actions_taken': []}
        monkeypatch.setattr(chief, 'chief_chat', fake_chat)
        response = await chief.chief_chat_stream(
            chief.ChatRequest(business_id='fixture', message='Send email'), None)
        iterator = response.body_iterator
        assert (await anext(iterator)).startswith(':')
        first = await anext(iterator)
        assert '"type": "status"' in first
        assert "I've sent" not in first
        release.set()
        rest = [frame async for frame in iterator]
        events = [json.loads(f.removeprefix('data: ').strip()) for f in rest if f.startswith('data:')]
        assert "I've sent" not in str(events)
        deltas = [e['text'] for e in events if e['type'] == 'delta']
        if failure:
            assert deltas == []
            assert events[-1]['type'] == 'error'
        else:
            assert deltas == ['The email failed. Nothing was sent.']
            assert events[-1]['payload']['response'] == ''.join(deltas)
    asyncio.run(run())
