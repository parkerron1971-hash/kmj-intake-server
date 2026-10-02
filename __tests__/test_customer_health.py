"""Customer health raises the businesses that need a person, and never sends."""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import customer_health as ch

NOW = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)


def row(**kw):
    base = {"business_id": "b1", "name": "Bright Path Coaching", "type": "coach", "day": 1,
            "returned": True, "activated": True, "subscription_status": "trialing",
            "last_seen_at": (NOW - timedelta(days=1)).isoformat(),
            "onboarding": {"furthest_step_name": "brand"}, "plugins": {"done": 3, "total": 6, "next": "Connect your calendar"}}
    base.update(kw)
    return base


def test_signed_up_and_never_came_back():
    s = ch.signal(row(day=4, returned=False), NOW)
    assert s["code"] == "not_back" and "4 days ago" in s["title"]


def test_a_week_in_and_not_set_up_names_the_next_step():
    s = ch.signal(row(day=8, activated=False, plugins={"done": 1, "total": 6, "next": "Connect your calendar"}), NOW)
    assert s["code"] == "not_set_up" and "Connect your calendar" in s["facts"]


def test_gone_quiet_on_a_live_plan():
    s = ch.signal(row(day=40, last_seen_at=(NOW - timedelta(days=9)).isoformat()), NOW)
    assert s["code"] == "gone_quiet" and "9 days" in s["title"]


def test_healthy_or_too_new_raises_nothing():
    assert ch.signal(row(), NOW) is None
    assert ch.signal(row(day=1, returned=False), NOW) is None
    assert ch.signal(row(day=40, subscription_status="canceled",
                         last_seen_at=(NOW - timedelta(days=30)).isoformat()), NOW) is None


class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class FakeDB:
    def __init__(self, recent_titles=()):
        self.posts, self.recent = [], list(recent_titles)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        if url.endswith("platform_changelog"):
            return _Resp([{"title": t} for t in self.recent])
        return _Resp([{"id": "kevins-biz"}])

    async def post(self, url, headers=None, json=None):
        self.posts.append((url.rsplit("/", 1)[-1], json))
        return _Resp(None, 201)


def _run(monkeypatch, rows, db, note="Hi, it's Kevin. — Kevin"):
    import first_week
    import platform_watchdog
    import spend_guard
    monkeypatch.setattr(first_week, "first_week_report", lambda days=30, limit=25: {"businesses": rows})

    async def owner(c, h):
        return "kevin"

    async def draft(c, r, s):
        return note

    monkeypatch.setattr(platform_watchdog, "_owner_user_id", owner)
    monkeypatch.setattr(spend_guard, "over_budget", lambda *a, **k: False)
    monkeypatch.setattr(ch, "_draft_note", draft)
    monkeypatch.setattr(ch, "_service_headers", lambda: {})
    monkeypatch.setattr(ch.httpx, "AsyncClient", lambda **kw: db)
    return asyncio.run(ch.health_tick(now=NOW))


def test_tick_raises_with_a_draft_and_skips_owner_tests_and_repeats(monkeypatch):
    rows = [row(business_id="b1", name="Stuck Co", day=5, returned=False),
            row(business_id="kevins-biz", name="KMJ", day=5, returned=False),
            row(business_id="b3", name="FLIP TEST (safe to delete)", day=5, returned=False),
            row(business_id="b4", name="Already Raised", day=5, returned=False),
            row(business_id="b5", name="Healthy Co")]
    db = FakeDB(recent_titles=["Customer health: Already Raised signed up 5 days ago"])
    out = _run(monkeypatch, rows, db)
    assert out == {"ok": True, "raised": ["Stuck Co"]}
    [(t, item)] = [p for p in db.posts if p[0] == "platform_changelog"]
    assert item["status"] == "pending" and item["agent"] == "customer_health"
    assert "Suggested note from you (not sent)" in item["detail"]


def test_tick_caps_the_day(monkeypatch):
    rows = [row(business_id=f"b{i}", name=f"Biz {i}", day=5, returned=False) for i in range(9)]
    out = _run(monkeypatch, rows, FakeDB())
    assert len(out["raised"]) == ch.MAX_PER_DAY


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("CUSTOMER_HEALTH", "off")
    assert asyncio.run(ch.health_tick()) == {"skipped": True}
