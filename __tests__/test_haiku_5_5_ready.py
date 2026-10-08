"""
test_haiku_5_5_ready.py — the code prices and calls Claude Haiku 5.5 correctly (2026-10-07).

Haiku 5.5 shipped on 2026-10-07: $0.10 in / $0.50 out per million tokens
for a prompt up to 100k tokens and 5x that above it, adaptive thinking that
can be turned off, effort levels, and (like the rest of its generation) no
assistant prefill. The same pricing check found Sonnet 5.5 and Opus 5.5
cache reads cost 0.05x the input price, not 0.1x, so the ledger had priced
every Sonnet 5.5 cache read at twice its cost.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import api_usage_logger as aul
import model_ladder


def test_haiku_5_5_short_prompt_prices():
    # 1k fresh in, 500 out, 20k cache read: 21k-token prompt, the short row.
    assert aul._compute_cost_cents("claude-haiku-5-5", 1000, 500, 20000, 0) == 0.055


def test_haiku_5_5_long_prompt_pays_the_long_row():
    # 1k fresh + 120k read = a 121k-token prompt: $0.50 in / $2.50 out.
    assert aul._compute_cost_cents("claude-haiku-5-5", 1000, 500, 120000, 0) == 0.775


def test_the_long_row_starts_above_100k_tokens():
    at = aul._compute_cost_cents("claude-haiku-5-5", 100_000, 0, 0, 0)
    over = aul._compute_cost_cents("claude-haiku-5-5", 100_001, 0, 0, 0)
    assert at == 1.0 and over >= 5.0


def test_cache_reads_by_model():
    million = 1_000_000
    assert aul._compute_cost_cents("claude-sonnet-5-5", 0, 0, million, 0) == 10.0   # $0.10
    assert aul._compute_cost_cents("claude-opus-5-5", 0, 0, million, 0) == 20.0     # $0.20
    assert aul._compute_cost_cents("claude-sonnet-5", 0, 0, million, 0) == 20.0     # $0.20
    assert aul._compute_cost_cents("claude-haiku-4-5-20251001", 0, 0, million, 0) == 10.0
    assert aul.cache_read_mult("claude-fable-5-1") == 0.025


def test_the_route_tally_uses_the_same_read_price():
    import route_ledger
    t = route_ledger.Tally()
    t.add("claude-sonnet-5-5", cache_read=1_000_000)
    assert t.cost_cents() == 10.0


def test_haiku_5_5_takes_effort_and_can_turn_thinking_off():
    assert model_ladder.effort_kwargs("claude-haiku-5-5", "low") == {"output_config": {"effort": "low"}}
    assert model_ladder.effort_kwargs("claude-haiku-4-5-20251001", "low") == {}
    assert model_ladder.thinking_off_kwargs("claude-haiku-5-5") == {"thinking": {"type": "disabled"}}
    assert model_ladder.thinking_off_kwargs("claude-haiku-4-5-20251001") == {}


def test_the_classifier_prefills_only_haiku_4(monkeypatch):
    import asyncio
    import chief_fast_track as fast
    import chief_models
    import route_ledger
    sent = []

    async def fake_stream(system, messages, **kw):
        sent.append(messages)
        if False:
            yield ""
    monkeypatch.setattr(fast, "stream_text", fake_stream)
    for model, prefilled in (("claude-haiku-4-5-20251001", True), ("claude-haiku-5-5", False)):
        monkeypatch.setattr(chief_models, "model_for", lambda lane, plan=None, _m=model: _m)
        sent.clear()
        asyncio.run(fast.classify("is my site live?", "", rec=route_ledger.RouteRecord(arrived=0.0), business_id=None))
        assert sent and (sent[0][-1].get("role") == "assistant") is prefilled
