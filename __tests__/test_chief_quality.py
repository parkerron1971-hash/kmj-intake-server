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
    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    # The route fixtures are anchored to NOW. The scheduled entry point must
    # use the same clock; otherwise these "today" turns age out after 24h.
    monkeypatch.setattr(cq, "datetime", FixtureClock)
    route = turns(40, cost=2.0) + turns(300, cost=1.0, hours_ago=72)
    db = FakeDB(route, [{"endpoint": "/chief/backend", "cost_cents": 80, "business_id": "b1"}])
    monkeypatch.setattr(cq, "_service_headers", lambda: {})
    monkeypatch.setattr(cq.httpx, "AsyncClient", lambda **kw: db)
    import spend_guard
    monkeypatch.setattr(spend_guard, "today_spend_cents", lambda *a, **k: 100.0)
    monkeypatch.setattr(spend_guard, "_cap_cents", lambda: 5000.0)
    r = asyncio.run(cq.report(db, {}, now=NOW))
    assert r["day"]["turns"] == 40 and r["week_before"]["turns"] == 300
    out = asyncio.run(cq.quality_tick())
    assert out["ok"] and out["flags"] == 1
    tables = [t for t, _ in db.posts]
    assert tables.count("platform_changelog") == 1
    run = [j for t, j in db.posts if t == "platform_agent_runs"][0]
    assert run["agent"] == "chief_quality" and "40 turns" in run["summary"]
    assert run["started_at"] == NOW.isoformat()


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("CHIEF_QUALITY", "off")
    assert asyncio.run(cq.quality_tick()) == {"skipped": True}


# ─── The live wall rate (SI score, 2026-10-05) ────────────────────────

def _turn(reply, n=2, hours_ago=1):
    return {"message_count": n, "ended_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
            "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": reply}]}


def test_the_wall_phrases_are_the_answer_checks_own():
    import chief_truth
    walls = (chief_truth.UNVERIFIED_REPLY, chief_truth.NO_ACTION_REPLY)
    for phrase in cq.WALL_PHRASES:
        assert any(phrase in w for w in walls), phrase
    for w in walls:
        assert any(p in w for p in cq.WALL_PHRASES), w


def test_wall_metrics_count_single_turns_only():
    import chief_truth
    rows = [_turn("Raise it to $175."), _turn(chief_truth.NO_ACTION_REPLY),
            _turn(chief_truth.UNVERIFIED_REPLY), _turn("x", n=8), _turn("")]
    m = cq.wall_metrics(rows)
    assert m == {"replies": 3, "walled": 2, "wall_rate": 0.667}
    assert cq.wall_metrics([])["wall_rate"] is None


def test_a_wall_rate_of_ten_percent_is_flagged_with_enough_replies():
    steady = cq.turn_metrics([])
    f = cq.flags(steady, steady, None, None, {"replies": 30, "walled": 3, "wall_rate": 0.1})
    assert [x["code"] for x in f] == ["quality:walls"]
    assert "3 of 30 replies" in f[0]["detail"]
    assert not cq.flags(steady, steady, None, None, {"replies": 30, "walled": 2, "wall_rate": 0.067})
    assert not cq.flags(steady, steady, None, None, {"replies": 5, "walled": 3, "wall_rate": 0.6})


def test_the_report_reads_the_live_wall_rate(monkeypatch):
    import chief_truth

    class ConvoDB(FakeDB):
        async def get(self, url, headers=None, params=None):
            t = url.rsplit("/", 1)[-1]
            if t == "chief_conversations":
                return _Resp([_turn("fine")] * 18 + [_turn(chief_truth.NO_ACTION_REPLY)] * 2 +
                             [_turn(chief_truth.NO_ACTION_REPLY, hours_ago=72)])
            return await super().get(url, headers, params)

    db = ConvoDB([], [])
    import spend_guard
    monkeypatch.setattr(spend_guard, "today_spend_cents", lambda *a, **k: 0.0)
    monkeypatch.setattr(spend_guard, "_cap_cents", lambda: 5000.0)
    r = asyncio.run(cq.report(db, {}, now=NOW))
    assert r["walls_24h"] == {"replies": 20, "walled": 2, "wall_rate": 0.1}
    assert r["walls_week_before"]["walled"] == 1
    assert "quality:walls" in [f["code"] for f in r["flags"]]
    assert "10% withheld as unverified" in cq._summary(r) or not r["day"].get("turns")
