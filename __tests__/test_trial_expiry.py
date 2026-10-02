"""Trials given inside the app end on their own.

SM&M Infinite Affairs read `trialing` for a month after its app-granted
trial ended, because only Stripe ever ended a trial. The hourly tick makes
a lapsed app trial look exactly like a lapsed Stripe trial: canceled,
tier starter.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import trial_expiry as te

NOW = datetime(2026, 10, 1, 23, 0, tzinfo=timezone.utc)


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


class FakeDB:
    def __init__(self, rows, read_status=200, patch_lands=True):
        self.rows, self.read_status, self.patch_lands = rows, read_status, patch_lands
        self.gets, self.patches, self.posts, self.runs = [], [], [], []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        self.gets.append(params)
        return _Resp(self.read_status, self.rows if self.read_status < 400 else {"message": "x"})

    async def patch(self, url, headers=None, params=None, json=None):
        self.patches.append((params, json))
        return _Resp(200, [{"id": params["id"]}] if self.patch_lands else [])

    async def post(self, url, headers=None, json=None):
        (self.runs if "platform_agent_runs" in url else self.posts).append(json)
        return _Resp(201, None)


def run(monkeypatch, db):
    monkeypatch.setattr(te, "_service_headers", lambda: {})
    monkeypatch.setattr(te.httpx, "AsyncClient", lambda **kw: db)
    return asyncio.run(te.expire_tick(now=NOW))


def test_a_lapsed_app_trial_becomes_canceled_like_a_stripe_trial(monkeypatch):
    db = FakeDB([{"id": "b1", "name": "SM&M Infinite Affairs",
                  "trial_ends_at": "2026-08-31T00:00:00+00:00"}])
    out = run(monkeypatch, db)
    assert out == {"ok": True, "expired": ["SM&M Infinite Affairs"]}
    [(params, body)] = db.patches
    assert body == {"subscription_status": "canceled", "tier": "starter"}
    # Guarded: only while it is still a lapsed, Stripe-less trial.
    assert params["subscription_status"] == "eq.trialing"
    assert params["stripe_subscription_id"] == "is.null"
    assert params["trial_ends_at"].startswith("lt.")
    [note] = db.posts
    assert note["title"] == "Trial ended: SM&M Infinite Affairs"
    [r] = db.runs
    assert r["agent"] == "trial_expiry" and r["ok"] is True and r["findings"] == 1


def test_only_app_trials_without_comp_are_read(monkeypatch):
    db = FakeDB([])
    run(monkeypatch, db)
    [q] = db.gets
    assert q["subscription_status"] == "eq.trialing"
    assert q["stripe_subscription_id"] == "is.null"   # Stripe trials end themselves
    assert q["comp_tier"] == "is.null"                 # comped businesses never lapse
    assert q["trial_ends_at"].startswith("lt.")


def test_a_trial_extended_at_the_same_moment_is_left_alone(monkeypatch):
    db = FakeDB([{"id": "b1", "name": "Raced", "trial_ends_at": "2026-09-30T00:00:00+00:00"}],
                patch_lands=False)
    out = run(monkeypatch, db)
    assert out == {"ok": True, "expired": []}
    assert db.posts == []
    # A quiet pass still leaves its run row, so the Agents card shows it ran.
    [r] = db.runs
    assert r["findings"] == 0 and r["summary"] == "no app trials past their end"


def test_a_failed_read_changes_nothing(monkeypatch):
    db = FakeDB([], read_status=500)
    out = run(monkeypatch, db)
    assert out["ok"] is False and db.patches == []
    [r] = db.runs
    assert r["ok"] is False


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("TRIAL_EXPIRY", "off")
    assert asyncio.run(te.expire_tick()) == {"skipped": True}
