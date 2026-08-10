"""Every Chief turn records which prompt shape it sent.

640 metered turns say caching almost never happens: 627 neither wrote
nor read a cached token, and input is ~86% of what a turn costs. But the
machinery is NOT broken — when the full operating-manual prompt goes
out it caches correctly (one day in the sample read 632k tokens back).

The spend sits somewhere else: 381 calls in the 5k-15k input band,
$34.93 of $47.15 total, with ONE cache hit between them. What could not
be settled from outside is which prompt those 381 carry, because
api_usage records the ENDPOINT and not the shape — every /chief/backend
row looks identical.

So the shape rides onto the row, and the next question is a SELECT
rather than a week of archaeology.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import inspect

import pytest

import chief_of_staff as cos

SRC = inspect.getsource(cos._call_claude)


class TestTheShapeIsRecorded:
    def test_all_three_shapes_are_named(self):
        for shape in ("cached-3seg", "cached-2seg", "uncached-single"):
            assert f'"{shape}"' in SRC, f"{shape} is never assigned"

    def test_it_defaults_to_uncached(self):
        """The default has to be the pessimistic one. If an unrecognised
        prompt were labelled as cached, the query that answers 'what are
        we actually sending' would answer it wrongly."""
        i = SRC.index('prompt_shape = "uncached-single"')
        j = SRC.index('if isinstance(system, str) and "[[CHIEF_CACHE_SPLIT]]"')
        assert i < j, "the shape must default before the split is examined"

    def test_both_success_paths_carry_it(self):
        """Streaming and non-streaming both log usage. Tagging one and
        not the other would split the data in half without saying so."""
        assert SRC.count("task_type=prompt_shape") == 2


class TestTheSilentFailureIsMadeLoud:
    def test_an_undersized_segment_warns(self):
        """A cache_control segment under the model's minimum cacheable
        prefix is ACCEPTED and silently never cached — no error, no
        warning, just a bill. That is exactly the shape of failure this
        whole investigation was chasing."""
        assert "below the ~1024-token" in SRC
        assert "logger.warning" in SRC

    def test_it_only_measures_segments_that_asked_to_be_cached(self):
        """A short dynamic tail is fine and expected — it was never going
        to be cached. Warning on it would train people to ignore the
        warning."""
        assert '"cache_control" in b' in SRC


class TestTheSplitStillWorks:
    def test_a_three_segment_prompt_produces_three_blocks(self):
        import collections
        ctx = collections.defaultdict(lambda: [], {
            "business": {"id": "b1", "name": "Biz",
                         "settings": {"practitioner_name": "K"},
                         "voice_profile": {}}})
        # A sentinel that cannot collide with prompt prose. "LIVE"
        # appears inside the operating manual, so the first version of
        # this test failed against correct code.
        SENTINEL = "ZZ_DYNAMIC_SENTINEL_9471"
        s = cos._build_system_prompt(ctx, False, session_context=SENTINEL)
        assert "[[CHIEF_GLOBAL_SPLIT]]" in s
        assert "[[CHIEF_CACHE_SPLIT]]" in s
        stable, _, dynamic = s.partition("[[CHIEF_CACHE_SPLIT]]")
        universal, _, per_business = stable.partition("[[CHIEF_GLOBAL_SPLIT]]")
        # The per-business manual is the token win and must clear the
        # minimum on its own, or the breakpoint buys nothing.
        assert len(per_business) // 4 > 1024, (
            "the per-business segment is below the cacheable minimum — the "
            "middle breakpoint would be decorative")
        assert SENTINEL in dynamic
        assert SENTINEL not in stable, (
            "dynamic state leaked into the cacheable prefix — the prefix "
            "then changes every turn and nothing ever caches")
