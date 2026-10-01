import asyncio
import json
import logging
from contextlib import asynccontextmanager

import httpx
import pytest

import chief_request_timing as timing
import llm_call
import route_ledger


class Response:
    status_code = 200
    def __init__(self, clock, lines):
        self.clock, self.lines = clock, lines
    async def aiter_lines(self):
        for line in self.lines:
            self.clock[0] += .1
            yield line
    async def aread(self):
        return b"unchanged"


@pytest.fixture
def clock(monkeypatch):
    value = [10.0]
    monkeypatch.setattr(timing.time, "perf_counter", lambda: value[0])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return value


def test_dispatch_headers_first_text_and_signed_handoff(clock, caplog):
    caplog.set_level(logging.INFO, logger="chief.request_timing")
    trace = timing.Trace(10, "turn-one")
    trace.work_started()
    clock[0] = 10.2
    main = trace.start("main", "main-model", "sse")
    clock[0] = 10.3
    trace.start("opener", "small-model", "sse")
    clock[0] = 10.5
    main.headers(200)
    main.observe({"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "secret"}})
    assert main.data["first_text_ms"] is None
    clock[0] = 10.7
    main.observe({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "private business text"}})
    clock[0] = 11
    main.observe({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "more"}})
    main.finish("complete")
    snap = trace.snapshot()
    assert snap["main_prepare_ms"] == 200
    assert snap["lead_to_main_request_ms"] == -100
    assert main.data["first_text_ms"] == 700
    assert main.data["first_text_wait_ms"] == 500
    assert main.data["headers_ms"] == 500
    assert "private business text" not in caplog.text and "secret" not in caplog.text
    assert '"event": "dispatch"' in caplog.text and '"request_id": "turn-one"' in caplog.text


def test_real_seam_starts_only_at_context_entry_and_preserves_lines(clock):
    lines = ['data: {"type":"message_start"}', 'data: malformed',
             'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}',
             'data: {"type":"message_stop"}']
    trace = timing.Trace(10, "stream-turn")
    response = Response(clock, lines)
    class Client:
        @asynccontextmanager
        async def stream(self, *args, **kwargs):
            clock[0] += .2
            yield response
    async def run():
        context = llm_call.astream(Client(), {"model":"small"}, task="/chief/opener", timing_trace=trace)
        assert not trace.calls
        clock[0] += .1
        async with context as resp:
            assert await resp.aread() == b"unchanged"
            actual = [line async for line in resp.aiter_lines()]
            assert actual == lines
    asyncio.run(run())
    call = trace.calls[0].data
    assert (call["start_ms"], call["headers_ms"], call["first_text_ms"], call["end_ms"]) == (100,300,600,700)
    assert call["outcome"] == "complete" and call["role"] == "opener"


@pytest.mark.parametrize("event,expected", [(None,"incomplete"), ({"type":"error","error":{"message":"private"}},"provider_error")])
def test_incomplete_and_provider_failure_are_not_success(clock,event,expected):
    trace = timing.Trace(10,"failure")
    @asynccontextmanager
    async def context():
        yield Response(clock, [] if event is None else ["data: "+json.dumps(event)])
    async def run():
        async with timing.stream(context(),trace,"main","model") as resp:
            async for _ in resp.aiter_lines():
                pass
    asyncio.run(run())
    assert trace.calls[0].data["outcome"] == expected
    assert trace.calls[0].data["first_text_ms"] is None


def test_cancellation_records_dispatch_and_closes_transport(clock):
    trace = timing.Trace(10,"cancelled")
    closed = []
    @asynccontextmanager
    async def context():
        try:
            yield Response(clock, [])
        finally:
            closed.append(True)
    async def run():
        with pytest.raises(asyncio.CancelledError):
            async with timing.stream(context(),trace,"main","model"):
                raise asyncio.CancelledError()
    asyncio.run(run())
    assert closed == [True]
    assert trace.calls[0].data["outcome"] == "cancelled"


def test_trace_context_isolated_across_parallel_turns_and_json_has_no_ttft(clock,monkeypatch):
    monkeypatch.setattr(llm_call,"_meter",lambda *args,**kwargs:None)
    first, second = timing.Trace(10,"first"), timing.Trace(10,"second")
    class Client:
        async def post(self,*args,**kwargs):
            await asyncio.sleep(0)
            return httpx.Response(200,json={"content":[{"type":"text","text":"private"}]})
    async def one(trace):
        token = timing.CURRENT.set(trace)
        try:
            await llm_call.apost(Client(),{"model":trace.request_id},task="chief_main")
        finally:
            timing.CURRENT.reset(token)
    async def run():
        await asyncio.gather(one(first),one(second))
        assert timing.CURRENT.get() is None
    asyncio.run(run())
    for trace in (first,second):
        call = trace.calls[0].data
        assert len(trace.calls)==1 and call["model"]==trace.request_id
        assert call["role"]=="main" and call["outcome"]=="complete"
        assert call["first_text_ms"] is None and call["headers_ms"] is None


def test_absent_roles_stay_unknown_and_db_row_has_no_new_columns(clock):
    rec = route_ledger.RouteRecord(arrived=10, request_id="trace-only")
    assert rec.flow_metrics()["model_timing"]["lead_to_main_request_ms"] is None
    assert rec.flow_metrics()["model_timing"]["main_prepare_ms"] is None
    assert "model_timing" not in rec.row() and "trace" not in rec.row()
    assert timing.role_for("arbitrary private text","chief_truth")=="review"


def test_retry_calls_remain_separate_and_snapshot_is_bounded(clock):
    trace = timing.Trace(10,"retry")
    for _ in range(40):
        call = trace.start("main","model","sse")
        call.finish("http_error")
    assert len(trace.snapshot()["calls"]) == 32
    assert trace.snapshot()["calls"][1]["call"] == 2


def test_frontend_request_id_is_used_by_real_plan_trace(monkeypatch):
    from types import SimpleNamespace
    import chief_fast_track as fast
    monkeypatch.setattr(fast, "enabled", lambda: True)
    monkeypatch.setattr(fast, "known_good", lambda *a: False)
    req = SimpleNamespace(request_id="frontend-voice-turn", message="How is the business?",
                          business_id="business", conversation_id="conversation", client_surface="voice")
    session = SimpleNamespace(user=SimpleNamespace(id="owner"))
    track = fast.plan(req, session)
    assert track.rec.request_id == "frontend-voice-turn"
    assert track.rec.trace.request_id == "frontend-voice-turn"


def test_dispatch_logs_survive_production_root_warning():
    import pathlib
    import subprocess
    import sys
    result = subprocess.run([sys.executable,"-c",
        "import logging; logging.getLogger().setLevel(logging.WARNING); "
        "import chief_request_timing as t; "
        "t.Trace(t.time.perf_counter(),'production-visibility').start('main','model','sse')"],
        cwd=pathlib.Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert '[chief request]' in result.stderr and 'production-visibility' in result.stderr


@pytest.mark.parametrize("endpoint", ["/chief/headline", "/chief/voice-bridge"])
def test_tally_only_preview_still_streams_with_inherited_trace(clock,monkeypatch,endpoint):
    import chief_fast_track as fast
    import chief_headline as headline
    trace = timing.Trace(10,"preview-turn")
    class Client:
        @asynccontextmanager
        async def stream(self,*args,**kwargs):
            yield Response(clock, [
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Verified preview."}}',
                'data: {"type":"message_stop"}'])
    monkeypatch.setattr(fast,"client",lambda:Client())
    async def run():
        token = timing.CURRENT.set(trace)
        try:
            out = {}
            pieces = [piece async for piece in fast.stream_text("system",[],model="small",max_tokens=20,
                rec=headline._TallyOnly(),endpoint=endpoint,units=0,business_id=None,out=out)]
            assert pieces == ["Verified preview."] and "error" not in out
        finally:
            timing.CURRENT.reset(token)
    asyncio.run(run())
    assert trace.calls[0].data["role"] == "preview"
    assert trace.calls[0].data["outcome"] == "complete"
