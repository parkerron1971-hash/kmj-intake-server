"""
test_opener_classifier_haiku_5_5.py — the opening line and the router's tie-breaker run on Haiku 5.5 (2026-10-07).

Kevin approved moving those two after a head-to-head on 12 real-shaped
messages: the same opener gate pass rate, a classifier a third faster with
valid JSON every time, about 7x cheaper. Both run with thinking off. The
`fast` lane (answers Haiku gives alone, headline, voice preview, helpers)
stays on Haiku 4.5 until it is measured the same way.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_fast_track as fast
import chief_models


def test_the_two_lanes_and_the_one_that_stays(monkeypatch):
    for lane in ("opener", "route", "fast"):
        monkeypatch.delenv(f"CHIEF_MODEL_{lane.upper()}", raising=False)
    assert chief_models.model_for("opener") == "claude-haiku-5-5"
    assert chief_models.model_for("route") == "claude-haiku-5-5"
    assert chief_models.model_for("fast") == "claude-haiku-4-5-20251001"


def test_each_lane_rolls_back_without_a_deploy(monkeypatch):
    monkeypatch.setenv("CHIEF_MODEL_OPENER", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("CHIEF_MODEL_ROUTE", "claude-haiku-4-5-20251001")
    assert chief_models.model_for("opener") == "claude-haiku-4-5-20251001"
    assert chief_models.model_for("route") == "claude-haiku-4-5-20251001"


def test_the_opener_asks_for_the_opener_lane():
    src = inspect.getsource(fast)
    assert 'endpoint="/chief/opener"' in src
    block = src[src.index('content = opener_request(self.message'):src.index('endpoint="/chief/opener"')]
    assert 'model_for("opener")' in block


class _Resp:
    status_code = 200

    async def aiter_lines(self):
        for line in ('data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}',
                     'data: {"type":"message_stop"}'):
            yield line


class _Ctx:
    async def __aenter__(self):
        return _Resp()

    async def __aexit__(self, *a):
        return False


def _sent_payload(monkeypatch, model):
    import llm_call
    import route_ledger
    sent = {}

    def astream(client, payload, **kw):
        sent.update(payload)
        return _Ctx()
    monkeypatch.setattr(llm_call, "astream", astream)
    monkeypatch.setattr(fast, "client", lambda: None)

    async def run():
        async for _ in fast.stream_text("sys", [{"role": "user", "content": "hi"}], model=model,
                                        max_tokens=60, rec=route_ledger.RouteRecord(arrived=0.0),
                                        endpoint="/chief/route", units=0, business_id=None, out={}):
            pass
    asyncio.run(run())
    return sent


def test_haiku_5_5_runs_with_thinking_off(monkeypatch):
    sent = _sent_payload(monkeypatch, "claude-haiku-5-5")
    assert sent.get("thinking") == {"type": "disabled"}


def test_haiku_4_5_is_sent_exactly_as_before(monkeypatch):
    sent = _sent_payload(monkeypatch, "claude-haiku-4-5-20251001")
    assert sent and "thinking" not in sent
