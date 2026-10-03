"""Chief quality & cost: the nightly arithmetic, and only real slips flagged."""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_quality as cq

NOW = datetime(2026, 10, 2, 7, 0, tzinfo=timezone.utc)


def turns(n, *, cost=1.0, ttft=800, slo_met=True, cache=True, error=None, hours_ago=1):
    t = (NOW - timedelta(hours=hours_ago)).isoformat()
    return [{"created_at": t, "cost_cents": cost, "ttft_ms": ttft, "slo_applies": True,
             "slo_met": slo_met, "escalated": False, "error": error, "cache_hit": cache}
            for _ in range(n)]


def test_metrics():
    m = cq.turn_metrics(turns(8, cost=2.0, ttft=500) + turns(2, cost=2.0, ttft=3000, slo_met=False))
    assert m["turns"] == 10 and m["cost_per_turn_cents"] == 2.0
    assert m["ttft_p50_ms"] == 500 and m["ttft_p90_ms"] == 3000
    assert m["slo_met_rate"] == 0.8 and m["error_rate"] == 0.0


def test_a_steady_day_flags_nothing():
    day, base = cq.turn_metrics(turns(40)), cq.turn_metrics(turns(300))
    assert cq.flags(day, base, 1000, 5000) == []


def test_cost_per_turn_up_is_flagged():
    day, base = cq.turn_metrics(turns(40, cost=2.0)), cq.turn_metrics(turns(300, cost=1.0))
    assert [f["code"] for f in cq.flags(day, base, None, None)] == ["cost:per_turn_up"]


def test_speed_cache_errors_and_cap():
    day = cq.turn_metrics(turns(30, slo_met=False, cache=False, error="boom") + turns(10))
    base = cq.turn_metrics(turns(300))
    codes = {f["code"] for f in cq.flags(day, base, 4000, 5000)}
    assert codes == {"speed:slo", "cost:cache_drop", "quality:errors", "cost:near_cap"}


def test_too_few_turns_means_no_trend_flags():
    day, base = cq.turn_metrics(turns(5, cost=9.0)), cq.turn_metrics(turns(300))
    assert cq.flags(day, base, None, None) == []


def test_spend_summary():
    s = cq.spend_summary([{"endpoint": "/chief/backend", "cost_cents": 10, "business_id": "b1"},
                          {"endpoint": "/ai/tts-el", "cost_cents": 4, "business_id": "b1"},
                          {"endpoint": "/chief/backend", "cost_cents": 6, "business_id": None}])
    assert s["total_cents"] == 20 and s["top_endpoints"][0] == ("/chief/backend", 16.0)
    assert s["top_businesses"] == [("b1", 14.0)]


class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class FakeDB:
    def __init__(self, route, usage):
        self.route, self.usage, self.posts = route, usage, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        t = url.rsplit("/", 1)[-1]
        return _Resp(self.route if t == "model_route_log" else self.usage)

    async def post(self, url, headers=None, json=None):
        self.posts.append((url.rsplit("/", 1)[-1], json))
        return _Resp(None, 201)


def test_tick_splits_the_windows_records_and_flags(monkeypatch):
    route = turns(40, cost=2.0) + turns(300, cost=1.0, hours_ago=72)
    db = FakeDB(route, [{"endpoint": "/chief/backend", "cost_cents": 80, "business_id": "b1"}])
    monkeypatch.setattr(cq, "_service_headers", lambda: {})
    monkeypatch.setattr(cq.httpx, "AsyncClient", lambda **kw: db)
    import spend_guard
    monkeypatch.setattr(spend_guard, "today_spend_cents", lambda *a, **k: 100.0)
    monkeypatch.setattr(spend_guard, "_cap_cents", lambda: 5000.0)
    # quality_tick reads the real clock; the fixtures sit around NOW. Without
    # this the test passed for one day and then every PR's CI failed, the
    # fixture turns having aged out of the tick's "last day" window.

    class _FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr(cq, "datetime", _FrozenClock)
    r = asyncio.run(cq.report(db, {}, now=NOW))
    assert r["day"]["turns"] == 40 and r["week_before"]["turns"] == 300
    out = asyncio.run(cq.quality_tick())
    assert out["ok"] and out["flags"] == 1
    tables = [t for t, _ in db.posts]
    assert tables.count("platform_changelog") == 1
    run = [j for t, j in db.posts if t == "platform_agent_runs"][0]
    assert run["agent"] == "chief_quality" and "40 turns" in run["summary"]


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("CHIEF_QUALITY", "off")
    assert asyncio.run(cq.quality_tick()) == {"skipped": True}
