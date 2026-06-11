"""Arc 20 Phase B PR3 — inference gate (cache hit/miss/store, fail-open,
surface allow-list, metering interaction)."""
from __future__ import annotations

import asyncio
import json
import sys
import pathlib
from datetime import datetime, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import inference_gate as ig  # noqa: E402
import chief_llm  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("INFERENCE_GATE", raising=False)
    # Deterministic fake embedder (no network).
    monkeypatch.setattr(ig, "_embed", lambda text: [0.1] * 4)
    return fb


def test_gate_disabled_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ig.gate_enabled() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("INFERENCE_GATE", "off")
    assert ig.gate_enabled() is False


def test_surface_allow_list():
    assert ig.surface_cacheable("chief_llm") is True
    assert ig.surface_cacheable("ai_proxy", "score") is True
    assert ig.surface_cacheable("ai_proxy", "build") is False     # creative-ish
    assert ig.surface_cacheable("composer") is False              # never
    assert ig.surface_cacheable("ai_proxy", None) is False


def test_exact_hash_hit_and_bump(fake):
    fb = fake
    ig.store("b1", "chief_llm", "what is this adobe charge", "Software subscription.",
             "claude-haiku-4-5", 1000, 200)
    assert len(fb.rows("inference_cache")) == 1
    out = ig.lookup("b1", "chief_llm", "  What is THIS adobe   charge ")  # normalized
    assert out and out["cached"] and out["confidence"] == 1.0
    assert out["response"] == "Software subscription."
    row = fb.rows("inference_cache")[0]
    assert row["hit_count"] == 1 and row["cost_cents_saved"] > 0
    decisions = fb.rows("inference_gate_decisions")
    assert any(d["cache_hit"] for d in decisions)


def test_business_scoping(fake):
    fb = fake
    ig.store("b1", "chief_llm", "question q", "answer for b1", "m", 10, 10)
    out = ig.lookup("b2", "chief_llm", "question q")
    # b2 never sees b1's cache (exact path scoped; vector RPC scoped in SQL —
    # FakeSB has no RPC so this returns the miss path).
    assert not (out and out.get("cached"))


def test_fail_open_on_errors(fake, monkeypatch):
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda p: (_ for _ in ()).throw(RuntimeError("db down")))
    out = ig.lookup("b1", "chief_llm", "anything")
    assert out is None                                            # → Claude


def test_chief_llm_uses_cache_before_anthropic(fake, monkeypatch):
    """End-to-end: a cached bookkeeping answer short-circuits the API call
    entirely — and the metering gate still ran first (cache hits meter)."""
    fb = fake
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fb.rows("businesses").append({"id": "b1", "owner_id": "o", "name": "b",
                                  "settings": {}, "subscription_status": None,
                                  "subscription_plan": None})
    sys_p = chief_llm._system_prompt("b1", "coach")
    user_p = "TRANSACTION:\n- id=t1 ..."
    ig.store("b1", "chief_llm", sys_p + "\n###\n" + user_p,
             '{"answer": "Cached: looks like software.", "proposal": null}',
             "claude-haiku-4-5", 1500, 100)

    async def boom(*a, **k):
        raise AssertionError("Anthropic should NOT be called on a cache hit")
    monkeypatch.setattr("httpx.AsyncClient.post", boom)

    out = asyncio.run(chief_llm._call_claude(
        "b1", sys_p, user_p, max_tokens=500, endpoint="/chief/ask-transaction"))
    assert "Cached" in out


def test_store_skips_uncacheable_and_empty(fake):
    fb = fake
    ig.store("b1", "composer", "x", "y", "m", 1, 1)               # never cache
    ig.store("b1", "chief_llm", "x", "   ", "m", 1, 1)            # empty response
    assert fb.rows("inference_cache") == []


def test_store_uses_upsert_for_stale_refresh(fake, monkeypatch):
    """Finding 3: store() must UPSERT on the unique hash key so a post-TTL
    miss overwrites the stale row instead of dying on the unique index."""
    fb = fake
    calls = []
    import sb_clients
    real_post = sb_clients.sb_post_as_service
    def spy(path, body, prefer="rep"):
        calls.append({"path": path, "prefer": prefer})
        return real_post(path, body, prefer)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", spy)
    ig.store("b1", "chief_llm", "q-stale", "fresh answer", "m", 10, 10)
    cache_calls = [c for c in calls if c["path"].startswith("/inference_cache")]
    assert cache_calls, "store did not write"
    assert "on_conflict=business_id,surface,prompt_hash" in cache_calls[0]["path"]
    assert cache_calls[0]["prefer"] == "resolution=merge-duplicates"
    row = fb.rows("inference_cache")[0]
    assert row["hit_count"] == 0 and row["response"] == "fresh answer"


def test_stats_aggregate(fake):
    fb = fake
    ig.store("b1", "chief_llm", "q1", "a1", "claude-haiku-4-5", 100, 50)
    ig.lookup("b1", "chief_llm", "q1")     # hit
    ig.lookup("b1", "chief_llm", "q2")     # miss
    s = ig.stats()
    assert s["cache_entries"] == 1
    assert s["decisions_sampled"] >= 2
    assert 0 < s["cache_hit_rate"] < 1
    assert s["by_surface"]["chief_llm"]["hits"] == 1
