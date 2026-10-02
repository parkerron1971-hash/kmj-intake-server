"""
test_chief_cache_holds_still.py — Chief's cached prompt stays byte-identical between turns (2026-09-24).

api_usage over 4 days: the main Chief call re-wrote ~29k tokens of prompt
cache per call on average (~7c of a ~10c call). Two causes, both measured
by building KMJ's real prompt twice 70 s apart:

1. The CACHED state segment carried two microsecond clocks —
   `DATA QUALITY: {"retrieved_at": "...T11:34:52.076830+00:00"}` and
   `EMAIL DATE CONTEXT: ... snapshot at ...T07:34:52.076830-04:00` — so the
   ~12.5k-token segment was re-written on every message.
2. Tools render before the system prompt, and web_search was added or
   dropped per message, so every flip invalidated the 45k-token operating
   manual (11 full re-writes inside its own 1-hour window, ~27c each).
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import llm_call


def test_data_quality_carries_the_date_not_the_clock():
    ctx = {"context_quality": {"retrieved_at": "2026-09-24T11:34:52.076830+00:00",
                               "unavailable": [], "lists_are_samples": True}}
    q = cos._quality_for_prompt(ctx)
    assert q["retrieved_on"] == "2026-09-24" and "retrieved_at" not in q
    later = {"context_quality": {**ctx["context_quality"], "retrieved_at": "2026-09-24T11:36:15.210134+00:00"}}
    assert cos._quality_for_prompt(later) == q


def test_the_email_date_line_has_no_snapshot_time():
    line = "Today is 2026-09-24 in America/Detroit; snapshot at 2026-09-24T07:34:52.076830-04:00."
    assert cos._SNAPSHOT_AT.sub(".", line) == "Today is 2026-09-24 in America/Detroit."
    unknown = "Snapshot date unavailable; do not infer today. Display timezone: UTC."
    assert cos._SNAPSHOT_AT.sub(".", unknown) == unknown


class _Resp:
    status_code = 200

    def __init__(self):
        self.text = ""

    def json(self):
        return {"stop_reason": "end_turn", "usage": {},
                "content": [{"type": "text", "text": "ok"}]}


def _send(monkeypatch, *, allowed):
    sent = {}

    async def apost(client, payload, **kw):
        sent.update(json.loads(json.dumps(payload)))
        return _Resp()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "k")
    monkeypatch.setattr(cos, "log_api_usage", AsyncMock())
    monkeypatch.setattr(cos, "CHIEF_WEB_SEARCH_ENABLED", True)
    system = ("UNIVERSAL " * 600 + "[[CHIEF_GLOBAL_SPLIT]]" + "MANUAL " * 900
              + "[[CHIEF_CACHE_SPLIT]]" + "STATE " * 900 + "[[CHIEF_TURN_SPLIT]]" + "TURN")
    asyncio.run(cos._call_claude(None, system, [{"role": "user", "content": "hi"}],
                                 enable_web_search=allowed, stable_tools=True))
    return sent


def test_the_tool_list_and_cached_blocks_do_not_change_with_the_message(monkeypatch):
    searchable = _send(monkeypatch, allowed=True)
    own_data = _send(monkeypatch, allowed=False)
    assert searchable["tools"] == own_data["tools"]
    assert any(t.get("name") == "web_search" for t in own_data["tools"])
    cached = lambda p: [b["text"] for b in p["system"] if "cache_control" in b]
    assert cached(searchable) == cached(own_data)
    assert "NOT THIS TURN" in own_data["system"][-1]["text"]
    assert "NOT THIS TURN" not in searchable["system"][-1]["text"]


def test_callers_without_stable_tools_are_unchanged(monkeypatch):
    sent = {}

    async def apost(client, payload, **kw):
        sent.update(payload)
        return _Resp()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "k")
    monkeypatch.setattr(cos, "log_api_usage", AsyncMock())
    monkeypatch.setattr(cos, "CHIEF_WEB_SEARCH_ENABLED", True)
    asyncio.run(cos._call_claude(None, "plain", [{"role": "user", "content": "hi"}],
                                 enable_web_search=False))
    assert "tools" not in sent


def test_the_main_turn_uses_stable_tools():
    import inspect
    assert "stable_tools=True" in inspect.getsource(cos.chief_chat)
