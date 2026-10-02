"""Fast-model transport must distinguish completed answers from partial SSE."""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import chief_fast_track as fast
import route_ledger


@pytest.mark.parametrize("terminal,expected", [
    ([], "incomplete_stream"),
    ([{"type": "error", "error": {"type": "overloaded_error"}}], "overloaded_error"),
    ([{"type": "message_delta", "delta": {"stop_reason": "end_turn"}}], "incomplete_stream"),
    ([{"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
      {"type": "message_stop"}], None),
    ([{"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
      {"type": "message_stop"}], None),
])
def test_stream_completion_and_provider_errors_are_reported(monkeypatch, terminal, expected):
    async def lines():
        events = [{"type": "message_start", "message": {"usage": {"input_tokens": 12}}},
                  {"type": "content_block_delta", "delta": {
                      "type": "text_delta", "text": "A useful partial answer"}}] + terminal
        for event in events:
            yield "data: " + json.dumps(event)
    @asynccontextmanager
    async def transport(*args, **kwargs):
        yield SimpleNamespace(status_code=200, aiter_lines=lines)
    monkeypatch.setattr(fast, "client", lambda: None)
    monkeypatch.setattr(fast.llm_call, "astream", transport)
    usage = []
    monkeypatch.setattr(fast, "_log_usage", lambda *args, **kwargs: usage.append(kwargs))
    out = {}
    async def run():
        return [piece async for piece in fast.stream_text(
            "system", [{"role": "user", "content": "Question"}], model="test-model",
            max_tokens=50, rec=SimpleNamespace(tally=route_ledger.Tally()),
            endpoint="/test", units=0, business_id=None, out=out)]
    assert asyncio.run(run()) == ["A useful partial answer"]
    assert out.get("error") == expected
    assert usage[-1]["ok"] is (expected is None)
    if terminal and terminal[-1]["type"] == "message_stop":
        assert out["stop_reason"] == terminal[-2]["delta"]["stop_reason"]
