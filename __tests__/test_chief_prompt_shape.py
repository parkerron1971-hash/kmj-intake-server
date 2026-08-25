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
    def test_all_four_shapes_are_named(self):
        for shape in ("cached-4seg", "cached-3seg", "cached-2seg",
                      "uncached-single"):
            assert f'"{shape}"' in SRC, f"{shape} is never assigned"

    def test_an_unrecognised_prompt_falls_back_to_uncached(self):
        """The fallback has to be the pessimistic one. If a prompt with no
        cache markers were labelled cached, the query that answers 'what
        are we actually sending' would answer it wrongly.

        Asserted on the FALLBACK RETURN rather than on statement order —
        the first version of this test pinned the order of two lines and
        broke the moment the builder became a function, against code that
        was still correct.
        """
        assert 'return system, "uncached-single"' in SRC, (
            "the no-markers path must return the uncached label")
        # ...and the 1h suffix must never be appended to it, or an
        # uncached prompt would be reported as an extended-cache one.
        assert 'if _extended and prompt_shape != "uncached-single"' in SRC

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


class TestTheTurnSplit:
    """Cache round 3 (2026-08-25): api_usage showed every turn paying
    ~13k UNCACHED input tokens — the whole state tail rebuilt at full
    price although most of it only changes when the business's data
    changes. [[CHIEF_TURN_SPLIT]] carves the snapshot into a THIRD
    cached segment (default 5-minute ttl); only the true per-turn tail
    stays uncached."""

    def _ctx(self):
        import collections
        return collections.defaultdict(lambda: [], {
            "business": {"id": "b1", "name": "Biz",
                         "settings": {"practitioner_name": "K"},
                         "voice_profile": {}}})

    def test_the_template_carries_the_turn_split(self):
        s = cos._build_system_prompt(self._ctx(), False)
        assert "[[CHIEF_TURN_SPLIT]]" in s
        assert s.index("[[CHIEF_CACHE_SPLIT]]") < s.index("[[CHIEF_TURN_SPLIT]]")

    def test_state_and_turn_land_on_their_own_sides(self):
        """session_context is a data snapshot → the cached STATE side.
        time_block is the clock → the uncached TURN side. A clock in the
        cached segment would break its byte-identity every ~minute,
        which is the exact failure this split exists to avoid."""
        STATE_S = "ZZ_STATE_SENTINEL_5531"
        TURN_S = "ZZ_TURN_SENTINEL_7712"
        s = cos._build_system_prompt(self._ctx(), False,
                                     session_context=STATE_S,
                                     time_block=TURN_S)
        _, _, tail = s.partition("[[CHIEF_CACHE_SPLIT]]")
        state, _, turn = tail.partition("[[CHIEF_TURN_SPLIT]]")
        assert STATE_S in state and STATE_S not in turn
        assert TURN_S in turn and TURN_S not in state, (
            "the clock leaked into the cached state segment")

    def test_the_state_segment_is_byte_stable_across_builds(self):
        """Two builds with identical inputs must produce an identical
        state segment — any drift means a hidden clock or randomness,
        and the cache would miss on every turn while looking healthy."""
        a = cos._build_system_prompt(self._ctx(), False, session_context="X")
        b = cos._build_system_prompt(self._ctx(), False, session_context="X")
        seg = lambda s: s.partition("[[CHIEF_CACHE_SPLIT]]")[2].partition("[[CHIEF_TURN_SPLIT]]")[0]
        assert seg(a) == seg(b), "the state segment is not deterministic"

    def test_the_builder_emits_four_blocks_with_the_right_ttls(self):
        """Source-level, like the rest of this file: the 4seg branch
        exists, and the state segment cache-controls on the PLAIN
        5-minute ephemeral — never the extended ttl, because Anthropic
        requires longer-ttl segments earlier in the prefix and staleness
        of an hour is not wanted on live data anyway."""
        assert '"cached-4seg"' in SRC
        assert 'dynamic.partition("[[CHIEF_TURN_SPLIT]]")' in SRC
        assert '"cache_control": {"type": "ephemeral"}' in SRC, (
            "the state segment must cache on the plain 5-minute default")

    def test_the_jit_directive_lands_below_the_turn_split(self):
        """A per-message directive at the head of the cached state
        segment would break its byte-stability on exactly the turns it
        fires. It must prefer the TURN marker."""
        chat_src = inspect.getsource(cos.chief_chat)
        assert 'marker = ("[[CHIEF_TURN_SPLIT]]"' in chat_src

    def test_the_fallback_never_leaks_the_marker(self):
        import fallback_brain
        raw = ("UNIVERSAL[[CHIEF_GLOBAL_SPLIT]]MANUAL" + "m" * 4000
               + "[[CHIEF_CACHE_SPLIT]]STATE" + "s" * 500
               + "[[CHIEF_TURN_SPLIT]]TURNTAIL")
        out = fallback_brain._fallback_system(raw)
        assert "CHIEF_TURN_SPLIT" not in out, (
            "the new marker leaked into the fallback prompt text")
        assert "TURNTAIL" in out or "STATE" in out
