"""
test_chief_shared_manual.py — the operating manual is cached once for every business (2026-10-08).

Chief's ~43k-token operating manual sat in the per-business cached block
only because the business's name and archetype were its first lines. Moved
below it, the manual joins the universal block: byte-identical for every
business, cached once, kept warm by any business's keep-warm pings. A
business's first message of the day then writes only its own ~4k-token
block (and its data snapshot) instead of ~48k. The words Chief sees are the
same lines, only reordered: nothing was cut, so its behavior does not move.
"""
from __future__ import annotations

import collections
import inspect
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos
import chief_prompt


def _ctx(name, btype, tone):
    return collections.defaultdict(lambda: [], {"business": {
        "id": name, "name": name, "type": btype, "settings": {}, "voice_profile": {"tone": tone}}})


BUSINESSES = [_ctx("Riverbend Coaching Co", "coaching", "warm"),
              _ctx("Fade Factory", "barbershop", "bold"),
              _ctx("Grace Church", "ministry", "gentle")]


def _split(text):
    shared, _, rest = text.partition("[[CHIEF_GLOBAL_SPLIT]]")
    own, _, _ = rest.partition("[[CHIEF_CACHE_SPLIT]]")
    return shared, own


def test_the_shared_block_is_the_same_for_every_business_and_turn_kind():
    blocks = set()
    for ctx in BUSINESSES:
        for greeting in (False, True):
            for suggestions in (False, True):
                shared, _ = _split(chief_prompt._build_system_prompt(
                    ctx, greeting, suggestions_active=suggestions))
                blocks.add(shared)
    assert len(blocks) == 1


def test_the_manual_is_in_the_shared_block_and_the_business_is_not():
    for ctx in BUSINESSES:
        shared, own = _split(chief_prompt._build_system_prompt(ctx, False))
        assert "YOU ARE THE CENTRAL ORCHESTRATOR" in shared
        assert "ACTIONS — INVOICES:" in shared
        assert ctx["business"]["name"] not in shared
        assert f"you operate as Chief of Staff for {ctx['business']['name']}" in own
        assert "ACTIONS — INVOICES:" not in own


def test_each_business_writes_only_a_small_block_of_its_own():
    shared, own = _split(chief_prompt._build_system_prompt(BUSINESSES[0], False))
    assert len(shared) // 4 > 30_000          # the manual: tens of thousands of tokens
    assert len(own) // 4 < 8_000              # the business's own lines: a few thousand


def test_the_small_block_warning_counts_the_whole_prefix():
    # Anthropic's ~1024-token minimum is on the prefix up to a breakpoint;
    # the per-business block alone may be small and still caches.
    src = inspect.getsource(cos._call_claude)
    assert "running += n" in src and "cacheable.append(running)" in src
