"""
test_gather_context_wave2.py — the profile/brand/voice/playbook blocks
inside _gather_context run concurrently, not one after another.

Latency round 4 (2026-08-26). [Chief timing] showed context=2800-4800ms
on every turn even with warm=8 — the enrichment prelude was fixed on
8/14 (#584, test_chief_turn_latency), but INSIDE _gather_context a
second serial tail had regrown behind wave 1's gather: ten sequential
awaits (foundation, business profile, maturity, growth objectives, raw
profile, practitioner x2, brand, voice, playbook), each a Supabase
round trip, each waiting on the last. Plus the semantic memory match —
a SYNCHRONOUS OpenAI embedding call running directly on the event loop
every turn, blocking the whole process including other requests'
streams.

Same measurement discipline as the 8/14 file: drive the REAL
_gather_context twice, once instant and once with every wave-2 source
costing DELAY, and assert on the DIFFERENCE. Serial adds ~11*DELAY;
concurrent adds about one. And the same two guards: a broken source
degrades to its own fallback (never the gather), and speed must not
come from quietly dropping blocks.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import chief_of_staff as cos

DELAY = 0.10
N_WAVE2 = 11               # 10 blocks + the semantic match
BUDGET = DELAY * 4         # concurrent ≈ 1*DELAY; serial ≈ 11*DELAY

_BIZ = {"id": "biz-1", "name": "Biz", "type": "coach", "owner_id": "user-1",
        "settings": {}, "created_at": "2026-01-01T00:00:00Z"}


@pytest.fixture
def gather(monkeypatch):
    """Run the real _gather_context with every wave-2 source stubbed and
    delay-able. Returns run(delay, query_text=None) -> (elapsed, ctx)."""
    cost = {"delay": 0.0}
    called: set[str] = set()

    async def _fake_sb(client, method, path, body=None):
        return [dict(_BIZ)]
    monkeypatch.setattr(cos, "_sb", _fake_sb)

    def _sync(name, value=""):
        def inner(*a, **k):
            called.add(name)
            if cost["delay"]:
                time.sleep(cost["delay"])
            return value
        return inner

    async def _async_src(*a, **k):
        called.add("foundation")
        if cost["delay"]:
            await asyncio.sleep(cost["delay"])
        return ""

    # cos-namespace imports
    monkeypatch.setattr(cos.foundation_agent, "chief_context_block",
                        lambda biz_id: _async_src())
    monkeypatch.setattr(cos, "bp_chief_context_block", _sync("bp_block"))
    monkeypatch.setattr(cos.business_profile_agent, "get_profile",
                        _sync("bp_raw", {"brand_voice": "warm"}))
    monkeypatch.setattr(cos, "pp_chief_context_block", _sync("pp_block"))
    monkeypatch.setattr(cos.practitioner_profile_agent, "get_profile",
                        _sync("pp_raw", {}))
    monkeypatch.setattr(cos, "brand_engine_chief_context_block", _sync("brand"))
    monkeypatch.setattr(cos, "voice_chief_context_block", _sync("voice"))

    # lazily-imported modules — importlib returns the same module object,
    # so patching the module attr covers the in-thread import path.
    import maturity_engine
    import growth_objective_agent
    import chief_playbook
    import chief_memory_semantic
    monkeypatch.setattr(maturity_engine, "maturity_context_block",
                        _sync("maturity", "MATURITY_X"))
    monkeypatch.setattr(growth_objective_agent, "growth_context_block",
                        _sync("growth", ""))
    monkeypatch.setattr(chief_playbook, "context_block", _sync("playbook"))
    monkeypatch.setattr(
        chief_memory_semantic, "match",
        _sync("semantic", [{"id": "sem-1", "category": "insight",
                            "content": "semantic hit", "importance": 6,
                            "similarity": 0.88}]))

    def run(delay=0.0, query_text="what happened this week?"):
        cost["delay"] = delay
        started = time.monotonic()
        ctx = asyncio.run(cos._gather_context(None, "biz-1", query_text=query_text))
        return time.monotonic() - started, ctx

    run.called = called
    return run


def test_wave_two_does_not_wait_on_itself(gather):
    baseline, ctx = gather(delay=0.0)
    assert ctx.get("business")
    slowed, _ = gather(delay=DELAY)
    added = slowed - baseline
    assert added < BUDGET, (
        f"slowing {N_WAVE2} independent context blocks by {DELAY}s each "
        f"added {added:.2f}s ({baseline:.2f}s -> {slowed:.2f}s). Concurrent "
        f"costs about {DELAY}s; ~{N_WAVE2 * DELAY:.1f}s means the serial "
        f"tail has regrown AGAIN — see #584 and this file's header."
    )


def test_every_wave_two_source_still_runs(gather):
    gather(delay=0.0)
    assert len(gather.called) == N_WAVE2, (
        f"only {sorted(gather.called)} ran — speed from dropping context "
        f"is not the fix"
    )


def test_the_maturity_block_still_folds_into_the_profile(gather):
    """The old serial code appended maturity/growth onto the business
    profile block AFTER awaiting them. Concurrency must not lose that."""
    _, ctx = gather(delay=0.0)
    assert "MATURITY_X" in (ctx.get("business_profile_block") or "")


def test_semantic_hits_still_reach_the_memory_pool(gather):
    _, ctx = gather(delay=0.0)
    ids = {str(m.get("id")) for m in (ctx.get("memories") or [])}
    assert "sem-1" in ids, "the semantic match ran but its hits were dropped"


def test_no_query_text_skips_the_semantic_match(gather):
    gather(delay=0.0, query_text=None)
    assert "semantic" not in gather.called, (
        "the embedding call must not fire for turns with no message text"
    )


@pytest.mark.parametrize("target,attr", [
    ("cos", "bp_chief_context_block"),
    ("cos", "pp_chief_context_block"),
    ("cos", "brand_engine_chief_context_block"),
    ("cos", "voice_chief_context_block"),
    ("chief_playbook", "context_block"),
    ("chief_memory_semantic", "match"),
])
def test_one_broken_block_never_takes_the_gather_down(gather, monkeypatch,
                                                      target, attr):
    import importlib
    holder = cos if target == "cos" else importlib.import_module(target)

    def _boom(*a, **k):
        raise RuntimeError(f"{attr} is down")
    monkeypatch.setattr(holder, attr, _boom)
    _, ctx = gather(delay=0.0)
    assert ctx.get("business"), (
        f"{attr} raising must degrade its own block, not the gather"
    )
