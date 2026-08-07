"""Anchoring on a clock.

Two providers protect against one network failing. They do nothing about
the likeliest failure, which was nobody anchoring at all — so the tests
that matter here are about the sweep running, staying a no-op when there
is nothing to do, and not becoming a machine that feeds itself work.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import anchor_scheduler as sched  # noqa: E402
import ledger_anchor as la  # noqa: E402


class _DB:
    """chain_state + anchors, and a count of how many reads it took."""

    def __init__(self, heads, anchors):
        self.heads = heads          # [(business_id, head_sequence)]
        self.anchors = anchors      # [(business_id, provider, last_sequence)]
        self.reads = 0
        self.posts = []

    def get(self, path):
        self.reads += 1
        if "/ledger_chain_state" in path:
            return [{"business_id": b, "last_sequence": s} for b, s in self.heads]
        if "/ledger_anchors" in path:
            return [{"business_id": b, "provider": p, "last_sequence": s}
                    for b, p, s in self.anchors]
        return []

    def post(self, path, body, prefer=None):
        self.posts.append((path, body))
        return [body]


def _wire(monkeypatch, db, providers="alpha,beta", anchor_fn=None):
    monkeypatch.setenv("LEDGER_ANCHOR_PROVIDERS", providers)
    monkeypatch.setenv("LEDGER_ANCHOR_SCHEDULE", "on")
    monkeypatch.setattr(sched.sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sched.sb_clients, "sb_post_as_service", db.post)
    calls = []

    def default_anchor(business_id, **kw):
        calls.append(business_id)
        return {"ok": True, "anchored": True, "providers": [
            {"provider": "alpha", "anchored": True},
            {"provider": "beta", "anchored": True}]}

    monkeypatch.setattr(la, "anchor_business", anchor_fn or default_anchor)
    return calls


# ─── The work list ───────────────────────────────────────────────────

def test_a_tenant_behind_on_only_one_provider_is_still_picked_up(monkeypatch):
    """The entire point of two providers is that one can be behind while
    the other is current. A work list that asked 'is this tenant
    anchored' without asking 'by whom' would skip exactly the tenant
    whose redundancy has quietly stopped working."""
    db = _DB(heads=[("b1", 10)], anchors=[("b1", "alpha", 10), ("b1", "beta", 4)])
    _wire(monkeypatch, db)
    assert [b for b, _ in sched._work_list()] == ["b1"]


def test_a_fully_anchored_tenant_is_left_alone(monkeypatch):
    """The sweep must be a genuine no-op for a quiet practice, or it
    becomes a machine that generates its own work."""
    db = _DB(heads=[("b1", 10)], anchors=[("b1", "alpha", 10), ("b1", "beta", 10)])
    _wire(monkeypatch, db)
    assert sched._work_list() == []


def test_a_tenant_that_has_never_been_anchored_is_picked_up(monkeypatch):
    db = _DB(heads=[("b1", 3)], anchors=[])
    _wire(monkeypatch, db)
    assert [b for b, _ in sched._work_list()] == ["b1"]


def test_the_most_exposed_tenant_goes_first(monkeypatch):
    """When a backlog exceeds the per-tick cap, the tenant with the most
    unprovable records should not be the one that waits."""
    db = _DB(
        heads=[("small", 10), ("huge", 900), ("mid", 100)],
        anchors=[("small", "alpha", 9), ("huge", "alpha", 1), ("mid", "alpha", 50)])
    _wire(monkeypatch, db, providers="alpha")
    assert [b for b, _ in sched._work_list()] == ["huge", "mid", "small"]


def test_the_work_list_does_not_grow_a_query_per_tenant(monkeypatch):
    """The obvious implementation asks each tenant in turn, which is one
    round trip per tenant per tick and gets worse forever."""
    many = [(f"b{i}", 100) for i in range(200)]
    db = _DB(heads=many, anchors=[])
    _wire(monkeypatch, db)
    sched._work_list()
    assert db.reads == 2, f"expected 2 queries regardless of tenant count, got {db.reads}"


def test_an_empty_ledger_is_not_work(monkeypatch):
    db = _DB(heads=[("b1", 0)], anchors=[])
    _wire(monkeypatch, db)
    assert sched._work_list() == []


# ─── The sweep ───────────────────────────────────────────────────────

def test_the_sweep_writes_no_ledger_entry(monkeypatch):
    """THE load-bearing decision. The owner-triggered route records
    `ledger:anchored`, which is right for a rare deliberate human act. On
    a six-hourly schedule the same write is a perpetual motion machine:
    each sweep creates a row, that row is new unanchored activity, so the
    next sweep has work, forever. A quiet ledger would fill with nothing
    but records of its own anchoring.
    """
    db = _DB(heads=[("b1", 5)], anchors=[])
    _wire(monkeypatch, db)
    asyncio.run(sched.sweep_tick())
    assert not [p for p, _ in db.posts if "audit_log" in p], \
        "the scheduled sweep must not write to the ledger it is anchoring"


def test_a_quiet_platform_anchors_nothing(monkeypatch):
    db = _DB(heads=[("b1", 5)], anchors=[("b1", "alpha", 5), ("b1", "beta", 5)])
    calls = _wire(monkeypatch, db)
    out = asyncio.run(sched.sweep_tick())
    assert calls == []
    assert out["attempted"] == 0 and out["anchored"] == 0


def test_the_kill_switch_stops_it(monkeypatch):
    db = _DB(heads=[("b1", 5)], anchors=[])
    calls = _wire(monkeypatch, db)
    monkeypatch.setenv("LEDGER_ANCHOR_SCHEDULE", "off")
    out = asyncio.run(sched.sweep_tick())
    assert calls == []
    assert "skipped" in out


def test_one_tenant_raising_does_not_end_the_sweep(monkeypatch):
    seen = []

    def flaky(business_id, **kw):
        seen.append(business_id)
        if business_id == "bad":
            raise RuntimeError("supabase unreachable")
        return {"ok": True, "anchored": True, "providers": []}

    db = _DB(heads=[("bad", 100), ("good", 50)], anchors=[])
    _wire(monkeypatch, db, providers="alpha", anchor_fn=flaky)
    out = asyncio.run(sched.sweep_tick())
    assert seen == ["bad", "good"], "the sweep must continue past a broken tenant"
    assert out["anchored"] == 1


def test_a_capped_sweep_says_so_rather_than_looking_complete(monkeypatch):
    """A truncated sweep reporting plain success would read as
    'everything is anchored' when it is not."""
    db = _DB(heads=[(f"b{i}", 100) for i in range(10)], anchors=[])
    _wire(monkeypatch, db, providers="alpha")
    monkeypatch.setenv("LEDGER_ANCHOR_MAX_PER_TICK", "3")
    out = asyncio.run(sched.sweep_tick())
    assert out["attempted"] == 3
    assert out["behind"] == 10
    assert out["deferred"] == 7


def test_provider_failures_are_counted_per_provider(monkeypatch):
    def half_broken(business_id, **kw):
        return {"ok": False, "anchored": True, "providers": [
            {"provider": "alpha", "anchored": True},
            {"provider": "beta", "error": "network unreachable"}]}

    db = _DB(heads=[("b1", 5)], anchors=[])
    _wire(monkeypatch, db, anchor_fn=half_broken)
    out = asyncio.run(sched.sweep_tick())
    assert out["per_provider"]["alpha"]["anchored"] == 1
    assert out["per_provider"]["beta"]["failed"] == 1


def test_the_sweep_does_not_park_the_event_loop(monkeypatch):
    """anchor_business talks to Hedera and the OpenTimestamps calendars
    over SYNCHRONOUS http — one Hedera submit measured 5.8s. Called
    directly from the coroutine it would freeze the API's event loop for
    minutes at a time, every interval, and every request the server was
    serving would hang behind an anchoring job nobody asked about.
    """
    import time

    def slow(business_id, **kw):
        time.sleep(0.15)          # blocking, exactly like the real one
        return {"ok": True, "anchored": True, "providers": []}

    db = _DB(heads=[("b1", 5), ("b2", 5), ("b3", 5)], anchors=[])
    _wire(monkeypatch, db, providers="alpha", anchor_fn=slow)

    async def scenario():
        beats = []
        done = asyncio.Event()

        async def heartbeat():
            while not done.is_set():
                beats.append(1)
                await asyncio.sleep(0.005)

        hb = asyncio.create_task(heartbeat())
        await sched.sweep_tick()
        done.set()
        await hb
        return len(beats)

    beats = asyncio.run(scenario())
    # ~0.45s of blocking work. Off the loop: ~90 beats. On it: 1 or 2.
    assert beats > 10, f"the event loop was parked during the sweep ({beats} beats)"


# ─── What silence means ──────────────────────────────────────────────

def test_staleness_follows_the_interval_when_scheduled(monkeypatch):
    """Before the sweep existed, quiet meant 'nobody asked' and flagging
    it would have been crying wolf. With a schedule running, quiet means
    the schedule did not run — so the threshold has to move with it
    rather than staying the constant that was true on the day it was
    written."""
    monkeypatch.setenv("LEDGER_ANCHOR_SCHEDULE", "on")
    monkeypatch.setenv("LEDGER_ANCHOR_INTERVAL_HOURS", "6")
    assert la.stale_after_hours() == 12
    monkeypatch.setenv("LEDGER_ANCHOR_INTERVAL_HOURS", "24")
    assert la.stale_after_hours() == 48


def test_a_tight_interval_does_not_make_every_gap_an_outage(monkeypatch):
    monkeypatch.setenv("LEDGER_ANCHOR_SCHEDULE", "on")
    monkeypatch.setenv("LEDGER_ANCHOR_INTERVAL_HOURS", "0.5")
    assert la.stale_after_hours() == 6, "there is a floor under the threshold"


def test_with_no_schedule_silence_stays_forgiving(monkeypatch):
    monkeypatch.setenv("LEDGER_ANCHOR_SCHEDULE", "off")
    assert la.stale_after_hours() == la.UNSCHEDULED_STALE_HOURS


def test_a_junk_interval_falls_back_rather_than_crashing_boot(monkeypatch):
    """This value is read at scheduler registration — a bad env var must
    not stop the app from starting."""
    monkeypatch.setenv("LEDGER_ANCHOR_INTERVAL_HOURS", "not-a-number")
    assert la.schedule_interval_hours() == la.DEFAULT_INTERVAL_HOURS
    monkeypatch.setenv("LEDGER_ANCHOR_INTERVAL_HOURS", "0")
    assert la.schedule_interval_hours() == la.DEFAULT_INTERVAL_HOURS


def test_health_reports_whether_anything_is_driving_anchoring(monkeypatch):
    """Without this the panel cannot tell the operator what silence
    means, because the answer genuinely differs."""
    monkeypatch.setattr(la.sb_clients, "sb_get_as_service", lambda p: [])
    monkeypatch.setenv("LEDGER_ANCHOR_SCHEDULE", "on")
    assert la.anchor_health()["scheduled"] is True
    monkeypatch.setenv("LEDGER_ANCHOR_SCHEDULE", "off")
    assert la.anchor_health()["scheduled"] is False


def test_the_job_is_registered_and_leader_gated():
    """Two replicas both sweeping would anchor the same window twice and
    hit the per-provider unique index — a constraint error, not a
    harmless duplicate."""
    src = (_here.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'id="ledger_anchor_sweep"' in src
    assert 'g("ledger_anchor_sweep"' in src, "must go through scheduler_lock.gate"
