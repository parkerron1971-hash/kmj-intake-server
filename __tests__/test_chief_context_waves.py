"""
test_chief_context_waves.py — the context snapshot's waves overlap (2026-09-23).

A voice turn spent 2.3 s in "context" although its enrichment was
prewarmed. _gather_context ran four waves one after another: 23 PostgREST
reads, then the exact contact count, then eleven profile/brand/playbook/
semantic-memory blocks, then the module counts. All but three of the
blocks need only biz_id, so they now start with the reads; the owner-keyed
blocks and the module counts are the only second wave.

Measured the way test_chief_turn_latency does: drive it with every source
instant and with every source costing DELAY, and assert on the difference.
Four serial waves add ~4*DELAY; overlapped, ~2*DELAY.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos

DELAY = 0.15
_BIZ = {"id": "biz-1", "name": "Biz", "type": "coach", "owner_id": "user-1", "settings": {}}


def _patch(monkeypatch, delay, calls):
    async def sb(client, method, path, *a, **k):
        calls.append(path.split("?")[0])
        await asyncio.sleep(delay)
        if path.startswith("/businesses"):
            return [dict(_BIZ)]
        if path.startswith("/custom_modules"):
            return [{"id": "m1", "name": "M", "slug": "m", "schema": {}, "archetype": None}]
        return []

    async def sb_count(client, path, *a, **k):
        calls.append("count:" + path.split("?")[0])
        await asyncio.sleep(delay)
        return 3

    def slow(value):
        def f(*a, **k):
            calls.append("block")
            time.sleep(delay)
            return value
        return f

    async def slow_async(*a, **k):
        calls.append("block")
        await asyncio.sleep(delay)
        return ""

    monkeypatch.setattr(cos, "_sb", sb)
    monkeypatch.setattr(cos, "_sb_count", sb_count)
    monkeypatch.setattr(cos.foundation_agent, "chief_context_block", slow_async)
    for name in ("bp_chief_context_block", "brand_engine_chief_context_block",
                 "pp_chief_context_block", "voice_chief_context_block"):
        monkeypatch.setattr(cos, name, slow(""))
    monkeypatch.setattr(cos.business_profile_agent, "get_profile", slow({}))
    monkeypatch.setattr(cos.practitioner_profile_agent, "get_profile", slow({}))
    import business_blueprint, chief_memory_semantic, chief_playbook, growth_objective_agent, maturity_engine
    monkeypatch.setattr(maturity_engine, "maturity_context_block", slow(""))
    monkeypatch.setattr(growth_objective_agent, "growth_context_block", slow(""))
    monkeypatch.setattr(chief_playbook, "context_block", slow(""))
    monkeypatch.setattr(chief_memory_semantic, "match", slow([]))
    monkeypatch.setattr(business_blueprint, "context_block", slow(""))


def _drive():
    async def run():
        # Enough worker threads that the pool never queues the blocks;
        # the production pool's size is not what this test measures.
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(32))
        t0 = time.monotonic()
        ctx = await cos._gather_context(None, "biz-1", "when is my next appointment?")
        return ctx, time.monotonic() - t0
    return asyncio.run(run())


def test_the_waves_overlap(monkeypatch):
    _patch(monkeypatch, 0.0, [])
    _, base = _drive()
    _patch(monkeypatch, DELAY, [])
    ctx, slow_ = _drive()
    added = slow_ - base
    assert ctx and ctx.get("business", {}).get("id") == "biz-1"
    # Serial waves add ~4*DELAY (0.6 s); overlapped ~2*DELAY (0.3 s).
    assert added < DELAY * 3, f"context added {added:.2f}s for a {DELAY}s source delay"


def test_every_block_and_count_still_runs(monkeypatch):
    calls = []
    _patch(monkeypatch, 0.0, calls)
    ctx, _ = _drive()
    assert calls.count("block") == 12          # 9 business-keyed + 3 owner-keyed
    assert "count:/contacts" in calls
    assert "count:/module_entries" in calls
    assert ctx["contacts_total"] == 3


def test_a_missing_business_cancels_the_early_wave(monkeypatch):
    calls = []
    _patch(monkeypatch, 0.0, calls)

    async def no_biz(client, method, path, *a, **k):
        return []
    monkeypatch.setattr(cos, "_sb", no_biz)
    ctx, _ = _drive()
    assert ctx == {}
