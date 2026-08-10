"""
test_growth_doctrine.py — the Growth Doctrine loads on growth turns and
NOWHERE else.

Two things are actually at risk here and both are tested against the
injected payload, never against the prose:

  1. THE GATE. The doctrine costs ~700 tokens. If it fires on ordinary
     operational turns it is rent on every invoice question, and — the
     2026-07-16 failure — it turns up inside a persona that must never
     see operational law. So the negative cases are the real suite.
  2. THE WIRING. A block builder that nothing interpolates is a silent
     no-op: the code looks correct, the tests pass, and the model never
     sees a word of it. test_prompt_actually_carries_the_block renders
     the real system prompt and looks for the text.
"""
import os
from unittest import mock

import pytest

import growth_doctrine as gd


# ─── The gate fires when it should ───────────────────────────────────

# Phrased the way a practitioner actually types, not the way a marketer
# would label the category.
GROWTH_MESSAGES = [
    "how do i get more clients?",
    "I want to run ads for the fall session",
    "nobody is booking lately, what should I do",
    "can you help me write a subject line for this",
    "should I start a newsletter?",
    "my landing page isn't converting",
    "what's a good lead magnet for a law firm",
    "it's been a slow month, how do I drum up business",
    "how do i promote my new program",
    "I need to grow my list",
    "thinking about a referral program",
    "what should my pricing strategy be",
]


@pytest.mark.parametrize("msg", GROWTH_MESSAGES)
def test_growth_turns_load_the_doctrine(msg):
    assert gd.is_growth_turn(msg), f"should have fired: {msg!r}"
    assert gd.context_block(msg).strip(), "fired but produced no block"


def test_marketing_rooms_fire_on_any_message():
    """Standing in the funnel, every question is a growth question."""
    assert gd.is_growth_turn("what am I looking at", sub_tab="funnel")
    assert gd.is_growth_turn("hey", tab="campaigns")
    assert gd.context_block("hey", sub_tab="campaigns").strip()


# ─── The gate stays shut when it should (the load-bearing half) ──────

# Ordinary operational traffic. Several of these deliberately contain
# words a naive matcher would grab — "sell", "grow", "offer", "content",
# "post", "client", "customer" — because those words are why the gate is
# phrase-based instead of keyword-based.
OPERATIONAL_MESSAGES = [
    "send Sandra her invoice",
    "what's on my calendar tomorrow",
    "did the payment from Marcus come through",
    "add a note to this client's file",
    "reschedule Thursday to next week",
    "how much did I make last month",
    "categorize these transactions",
    "what does this customer still owe me",
    "post this to the module",
    "I want to grow as a practitioner this year",
    "do we sell that in a package already",
    "what's the content of that note",
    "we're opening a second location in Seoul",
    "add an offering for the intake call",
]


@pytest.mark.parametrize("msg", OPERATIONAL_MESSAGES)
def test_operational_turns_stay_clean(msg):
    assert not gd.is_growth_turn(msg), f"false positive on: {msg!r}"
    assert gd.context_block(msg) == ""


def test_seoul_is_not_seo():
    """Word-boundary proof for the shortest trigger in the set. If this
    ever regresses, every travel-adjacent sentence pays 700 tokens."""
    assert not gd.is_growth_turn("we're opening in Seoul")
    assert gd.is_growth_turn("how's our seo looking")


def test_punctuation_does_not_hide_a_trigger():
    assert gd.is_growth_turn("marketing?")
    assert gd.is_growth_turn("(campaign) ideas")
    assert gd.is_growth_turn("MORE CLIENTS!!")


# ─── Mode + kill switch ──────────────────────────────────────────────

def test_strategy_coach_never_receives_operational_law():
    """The coach is a different persona. It is structurally excluded
    upstream too; this is the second lock on the same door."""
    msg = "how do i get more clients?"
    assert gd.is_growth_turn(msg)
    assert gd.context_block(msg, mode="strategy_coach") == ""


def test_kill_switch_silences_every_path():
    msg = "how do i get more clients?"
    with mock.patch.dict(os.environ, {"GROWTH_DOCTRINE": "off"}):
        assert gd.context_block(msg) == ""
        assert gd.context_block("hey", sub_tab="funnel") == ""
        assert gd.with_growth_doctrine("SYSTEM") == "SYSTEM"


def test_gate_never_raises():
    """A gate that throws takes the whole turn down with it."""
    assert gd.context_block(None) == ""          # type: ignore[arg-type]
    assert gd.context_block("") == ""
    assert not gd.is_growth_turn("")


# ─── The payload ─────────────────────────────────────────────────────

def test_block_carries_every_law_and_the_ladder():
    """All twelve laws survive into the injected text — a truncated or
    reflowed doctrine is a silent partial load."""
    block = gd.context_block("how do i get more clients?")
    for n in range(1, 13):
        assert f"G{n} " in block, f"G{n} missing from the injected block"
    assert "THE FOUR RUNGS" in block


def test_composer_helper_prepends_rather_than_replaces():
    out = gd.with_growth_doctrine("STAGE PROMPT")
    assert out.endswith("STAGE PROMPT")
    assert "G1 THE LADDER" in out


# ─── The wiring ──────────────────────────────────────────────────────

class _EmptyCtx(dict):
    """_build_system_prompt reads a few dozen context keys unguarded.
    Enumerating them here would make this test a maintenance tax on
    unrelated work, so anything unset reads as empty."""
    def __missing__(self, key):
        return []


def _min_ctx():
    return _EmptyCtx(business={"id": "b1", "name": "Test Co", "type": "coach",
                               "settings": {}, "voice_profile": {}})


def test_prompt_actually_carries_the_block():
    """_build_system_prompt must interpolate growth_block. Without this
    test the parameter can exist, be passed, and be dropped on the floor
    by a missing placeholder — with every unit test still green."""
    import chief_of_staff as cos

    ctx = _min_ctx()
    marker = "G12 SUGGEST ONLY WHAT YOU CAN DO"

    with_block = cos._build_system_prompt(
        ctx, False, growth_block=gd.context_block("how do i get more clients?"))
    assert marker in with_block

    without_block = cos._build_system_prompt(ctx, False)
    assert marker not in without_block, (
        "the doctrine leaked into a turn that never asked for it")


def test_coach_prompt_cannot_carry_the_block():
    """Belt and braces: even handed a non-empty block, coach mode returns
    a prompt built from a different template entirely."""
    import chief_of_staff as cos

    ctx = _min_ctx()
    out = cos._build_system_prompt(
        ctx, False, mode="strategy_coach",
        growth_block=gd.DOCTRINE)
    assert "G12 SUGGEST ONLY WHAT YOU CAN DO" not in out


class TestEveryCoachIsExcludedIncludingTheOnesNotWrittenYet:
    """_EXCLUDED_MODES named `strategy_coach` and nothing else, while
    `business_coach` already existed — so the second coach was not
    excluded. It never leaked, because that mode returns its own prompt
    before growth_block is ever consumed.

    Which is the exact sentence in this module's own comment, repeated:
    the 2026-07-16 leak happened because a gate that "could not be
    reached" was reached. A list of coaches is a thing that goes stale;
    the suffix is the actual rule.
    """

    QUESTION = "how do I get more customers"

    @pytest.mark.parametrize("mode", [
        "strategy_coach", "business_coach", "design_coach",
        "some_future_coach",
    ])
    def test_no_coach_receives_operational_law(self, mode):
        assert gd.context_block(
            self.QUESTION, mode=mode, tab=None) == ""

    @pytest.mark.parametrize("mode", ["chief_chat", None, ""])
    def test_the_operational_chief_still_gets_it(self, mode):
        """Guarding the guard: an over-broad exclusion that silenced
        everything would pass every test above."""
        assert gd.context_block(
            self.QUESTION, mode=mode, tab=None) != ""

    def test_a_non_growth_turn_still_costs_nothing(self):
        assert gd.context_block(
            "what did I spend on rent", mode="chief_chat", tab=None) == ""
