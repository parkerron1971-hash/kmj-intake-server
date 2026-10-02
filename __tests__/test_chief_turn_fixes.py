"""
test_chief_turn_fixes.py — the 2026-09-14 turn fixes.

Kevin gave Chief a task, waited through a long pause, and heard nothing
back. The log showed three things at once: the same lookup called three
times in one turn, the premium voice returning 429 (so the reply was
never spoken), and 12-15 seconds of every turn spent on the answer
check. And the greeting opened with the practitioner's full name.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import chief_tool_loop as loop


def test_the_same_read_twice_in_a_turn_is_answered_once(monkeypatch):
    runs = []

    async def fake_handler(client, biz, action):
        runs.append(dict(action))
        return {"type": "catch_up", "result": "0 updates", "label": "Catch-up · 0 updates"}

    monkeypatch.setitem(cos.ACTION_HANDLERS, "catch_up", fake_handler)

    async def go():
        loop.reset_turn()
        a = await loop.execute_tool_use(None, {"id": "biz-1"}, "catch_up", {"since": "friday"})
        b = await loop.execute_tool_use(None, {"id": "biz-1"}, "catch_up", {"since": "friday"})
        c = await loop.execute_tool_use(None, {"id": "biz-1"}, "catch_up", {"since": "monday"})
        return a, b, c

    a, b, c = asyncio.run(go())
    assert len(runs) == 2, "same args once, different args again"
    assert not a[0] and not b[0]
    assert b[1].startswith("Same lookup as earlier this turn")
    assert "0 updates" in b[1] and "do not look it up again" in b[1]
    assert not c[1].startswith("Same lookup")
    # the next turn starts clean
    loop.reset_turn()
    assert loop._reads_this_turn.get() == {}


def test_a_repeated_read_does_not_count_as_a_call_or_a_step(monkeypatch):
    async def fake_handler(client, biz, action):
        return {"type": "check_goals", "result": "2 on track", "label": "Goals"}

    monkeypatch.setitem(cos.ACTION_HANDLERS, "check_goals", fake_handler)
    sunk = []
    tok = cos._STREAM_SINK.set(sunk.append)
    try:
        async def go():
            loop.reset_turn()
            await loop.execute_tool_use(None, {"id": "biz-1"}, "check_goals", {})
            await loop.execute_tool_use(None, {"id": "biz-1"}, "check_goals", {})
            return loop._calls_this_turn.get()
        calls = asyncio.run(go())
    finally:
        cos._STREAM_SINK.reset(tok)
    assert calls == 1
    steps = [p for p in sunk if p.startswith(cos.STEP_PREFIX)]
    assert len(steps) == 2, "one start and one end, not two of each"


def test_greeting_asks_for_the_first_name():
    import chief_prompt
    src = pathlib.Path(chief_prompt.__file__).read_text(encoding="utf-8")
    assert "FIRST NAME only" in src and "never the full name" in src


def test_review_has_its_own_lane_on_the_chat_model():
    import chief_models
    assert chief_models.model_for("review") == chief_models.model_for("chat")


def test_busy_premium_voice_falls_back_instead_of_going_silent(monkeypatch):
    import whisper_proxy as wp

    class Upstream:
        status_code = 429

        async def aread(self):
            return b'{"detail":{"code":"concurrent_limit_exceeded"}}'

        async def aclose(self):
            pass

    class Client:
        def __init__(self, *a, **kw):
            pass

        def build_request(self, *a, **kw):
            return object()

        async def send(self, *a, **kw):
            return Upstream()

        async def aclose(self):
            pass

    monkeypatch.setattr(wp.httpx, "AsyncClient", Client)
    out = asyncio.run(wp._elevenlabs_speak("Hello there", "voice-1", "key"))
    assert out is None, "429 means: speak with the included voice"

    Upstream.status_code = 401
    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException):
        asyncio.run(wp._elevenlabs_speak("Hello there", "voice-1", "key"))
