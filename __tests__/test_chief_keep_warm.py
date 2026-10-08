"""
test_chief_keep_warm.py — a no-reply read keeps Chief's cached brief alive while the business is active (2026-10-07).

30 days: 37 re-writes of Chief's whole ~100k-token brief came 1-4 h after the
business's previous message, at ~35c each, because the cached copy lives an
hour after its last use. A read costs a tenth of the input price and resets
that hour. The ping re-sends what the last call had in front of its 1-hour
breakpoints, asks for no reply, and stops when the business goes quiet or
when a ping finds no copy to read.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_keep_warm as kw

ONE_H = {"type": "ephemeral", "ttl": "1h"}


def _payload():
    return {
        "model": "claude-sonnet-5-5", "max_tokens": 1600, "stream": True,
        "output_config": {"effort": "low"},
        "tools": [{"name": "get_contacts"}, {"name": "show_view"}],
        "system": [
            {"type": "text", "text": "UNIVERSAL", "cache_control": ONE_H},
            {"type": "text", "text": "MANUAL", "cache_control": ONE_H},
            {"type": "text", "text": "STATE", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "THIS TURN"},
        ],
        "messages": [{"role": "user", "content": "what's overdue?"}],
    }


def test_the_ping_is_the_cached_prefix_with_no_reply():
    ping = kw.ping_payload(_payload())
    assert ping["max_tokens"] == 0 and "stream" not in ping
    assert [b["text"] for b in ping["system"]] == ["UNIVERSAL", "MANUAL"]
    assert ping["tools"] == _payload()["tools"] and ping["output_config"] == {"effort": "low"}
    assert ping["model"] == "claude-sonnet-5-5"
    assert ping["messages"] == [{"role": "user", "content": "."}]


def test_nothing_cached_for_an_hour_means_no_ping():
    p = _payload()
    for b in p["system"]:
        b.pop("cache_control", None)
    assert kw.ping_payload(p) is None
    assert kw.ping_payload({"system": "one string"}) is None


def test_off_and_no_business_schedule_nothing(monkeypatch):
    monkeypatch.setenv("CHIEF_KEEP_WARM", "off")
    assert kw.remember("biz", _payload()) is False
    monkeypatch.setenv("CHIEF_KEEP_WARM", "on")
    assert kw.remember(None, _payload()) is False
    assert kw.remember("biz", _payload()) is False   # no running loop


class _Resp:
    def __init__(self, read, wrote, status=200):
        self.status_code = status
        self._u = {"cache_read_input_tokens": read, "cache_creation_input_tokens": wrote}

    def json(self):
        return {"usage": self._u, "content": [], "stop_reason": "max_tokens"}


def _wire(monkeypatch, responses, every=0.01, window=1.0):
    import llm_call
    import spend_guard
    sent = []

    async def apost(client, payload, **kw_):
        sent.append((payload, kw_))
        return responses.pop(0) if responses else _Resp(95000, 0)
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(llm_call, "api_key", lambda: "k")
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(kw, "every_s", lambda: every)
    monkeypatch.setattr(kw, "window_s", lambda: window)
    kw._tasks.clear()
    return sent


def test_pings_repeat_while_the_business_is_active(monkeypatch):
    sent = _wire(monkeypatch, [], every=0.01, window=30)

    async def run():
        assert kw.remember("biz-1", _payload(), {"anthropic-beta": "extended-cache-ttl-2025-04-11"})
        for _ in range(200):
            if len(sent) >= 2:
                break
            await asyncio.sleep(0.02)
        kw._tasks["biz-1"].cancel()
    asyncio.run(run())
    assert len(sent) >= 2
    payload, opts = sent[0]
    assert payload["max_tokens"] == 0 and opts["units"] == 0 and opts["task"] == "chief_keep_warm"
    assert opts["business_id"] == "biz-1"
    assert opts["extra_headers"] == {"anthropic-beta": "extended-cache-ttl-2025-04-11"}


def test_pings_stop_once_the_window_has_passed(monkeypatch):
    sent = _wire(monkeypatch, [], every=0.01, window=0.001)

    async def run():
        kw.remember("biz-1b", _payload())
        for _ in range(200):
            if "biz-1b" not in kw._tasks:
                break
            await asyncio.sleep(0.02)
    asyncio.run(run())
    assert "biz-1b" not in kw._tasks
    assert sent == []


def test_a_ping_that_writes_stops_the_pings(monkeypatch):
    sent = _wire(monkeypatch, [_Resp(0, 95000)], every=0.01, window=5)

    async def run():
        kw.remember("biz-2", _payload())
        await asyncio.sleep(0.1)
    asyncio.run(run())
    assert len(sent) == 1


def test_a_refused_ping_stops_the_pings(monkeypatch):
    sent = _wire(monkeypatch, [_Resp(0, 0, status=400)], every=0.01, window=5)

    async def run():
        kw.remember("biz-3", _payload())
        await asyncio.sleep(0.1)
    asyncio.run(run())
    assert len(sent) == 1


def test_a_new_message_restarts_the_clock(monkeypatch):
    _wire(monkeypatch, [], every=10, window=50)

    async def run():
        kw.remember("biz-4", _payload())
        first = kw._tasks["biz-4"]
        kw.remember("biz-4", _payload())
        await asyncio.sleep(0)
        assert first.cancelled() or first.done()
        assert kw._tasks["biz-4"] is not first
        kw._tasks["biz-4"].cancel()
    asyncio.run(run())


class _ChiefResp:
    status_code = 200
    text = ""

    def json(self):
        return {"stop_reason": "end_turn", "model": "claude-sonnet-5-5",
                "usage": {"input_tokens": 10, "output_tokens": 5,
                          "cache_read_input_tokens": 90000, "cache_creation_input_tokens": 0},
                "content": [{"type": "text", "text": "ok"}]}


def _chief_call(monkeypatch, role):
    import chief_of_staff as cos
    import llm_call
    import spend_guard
    seen = []

    async def apost(client, payload, **k):
        return _ChiefResp()
    monkeypatch.setattr(llm_call, "apost", apost)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "k")
    monkeypatch.setattr(cos, "log_api_usage", AsyncMock())
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(kw, "remember", lambda biz, payload, headers=None: seen.append((biz, payload, headers)) or True)
    system = ("U " * 600 + "[[CHIEF_GLOBAL_SPLIT]]" + "M " * 900 + "[[CHIEF_CACHE_SPLIT]]"
              + "STATE A\n\nSTATE B " * 300 + "[[CHIEF_TURN_SPLIT]]" + "TURN")
    asyncio.run(cos._call_claude(None, system, [{"role": "user", "content": "hi"}],
                                 business_id="biz-c", stable_tools=True, timing_role=role))
    return seen


def test_the_owners_main_call_schedules_the_pings(monkeypatch):
    seen = _chief_call(monkeypatch, "chief_main")
    assert len(seen) == 1 and seen[0][0] == "biz-c"
    assert kw.ping_payload(seen[0][1]) is not None


def test_auxiliary_calls_do_not(monkeypatch):
    assert _chief_call(monkeypatch, "chief_auxiliary") == []


# ── Daily users stay warm for a day (2026-10-07) ─────────────────────
# Simulated on 30 days of real call times: cold starts plus pings cost
# $37.27 with no keep-warm, $25.52 at 4 h and $18.56 at 24 h. A business
# that uses Chief most days keeps its brief warm through the night.

def _rows(*days):
    return [{"created_at": f"{d}T10:00:00Z"} for d in days]


def test_a_daily_user_gets_the_long_window(monkeypatch):
    import sb_clients
    kw._daily.clear()
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: _rows("2026-10-05", "2026-10-06", "2026-10-07", "2026-10-07"))
    assert kw.window_for("daily-biz") == kw.daily_window_s() == 24 * 3600


def test_two_days_of_use_keeps_the_short_window(monkeypatch):
    import sb_clients
    kw._daily.clear()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: _rows("2026-10-06", "2026-10-07"))
    assert kw.window_for("new-biz") == kw.window_s() == 4 * 3600


def test_a_failed_read_keeps_the_short_window(monkeypatch):
    import sb_clients
    kw._daily.clear()

    def boom(path):
        raise RuntimeError("no database")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", boom)
    assert kw.window_for("biz-x") == kw.window_s()


def test_daily_use_is_read_once_a_day(monkeypatch):
    import sb_clients
    kw._daily.clear()
    calls = []

    def get(path):
        calls.append(path)
        return _rows("2026-10-05", "2026-10-06", "2026-10-07")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    kw.window_for("biz-y")
    kw.window_for("biz-y")
    assert len(calls) == 1
    assert "endpoint=eq./chief/backend" in calls[0] and "business_id=eq.biz-y" in calls[0]


def test_a_daily_users_pings_outlast_the_short_window(monkeypatch):
    sent = _wire(monkeypatch, [], every=0.01, window=0.001)
    monkeypatch.setattr(kw, "window_for", lambda b: 30.0)

    async def run():
        kw.remember("biz-daily", _payload())
        for _ in range(200):
            if len(sent) >= 2:
                break
            await asyncio.sleep(0.02)
        kw._tasks["biz-daily"].cancel()
    asyncio.run(run())
    assert len(sent) >= 2
