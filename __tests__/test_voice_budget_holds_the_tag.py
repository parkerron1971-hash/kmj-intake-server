"""The voice lane's output ceiling must fit an artifact tag, not just words.

Kevin, 2026-08-18, after visuals had been fixed once already: "there
seem to still be a bug in the artifact setup ... chief is having a
problem producing visuals."

The cause was a number set before the feature existed. 700 output
tokens was generous when a voice reply was ONLY spoken words. It
stopped being true the day Chief could put things on screen: the
[ACTION:] tag is emitted in the SAME completion as the reply and
usually after it, so a rich one — an 8-step show_plan, a 4-block
show_readout — ran the budget out mid-JSON.

And a truncated tag is DROPPED (chief_of_staff._extract_actions_and_clean),
which is the worst shape a failure can take: the reply reads fine, the
turn returns 200, and the thing the practitioner was told to look at
never existed.

These tests pin the budget against the artifacts it has to carry, so
the next display verb — or the next person tuning latency — cannot
quietly reintroduce it.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_models
import chief_of_staff as cos


# Deliberately conservative: JSON punctuation tokenizes WORSE than prose,
# so chars/3 over-estimates cost rather than flattering the budget.
def _tokens(text: str) -> int:
    return len(text) // 3


# The biggest tags the prompt actually invites the model to emit.
_BIG_PLAN = (
    '[ACTION:{"type":"show_plan","title":"Get the overdue money in and keep it in",'
    '"steps":['
    + ",".join(
        '{"step":"Call the client and ask for a date %d","why":"ninety days is past what a reminder fixes",'
        '"when":"today"}' % i for i in range(8)
    )
    + "]}]"
)
_BIG_READOUT = (
    '[ACTION:{"type":"show_readout","title":"How the month is running",'
    '"blocks":['
    + ",".join(
        '{"view":"invoices","filter":"overdue","form":"chart","group_by":"client"}'
        for _ in range(4)
    )
    + '],"note":"Week four carried the month — the Halcyon retainer landing, and the three '
      'genuinely late add up to about two thousand."}]'
)
# The prompt asks for under ~110 words. Take it at its word, at the top
# of the range, in long words.
_FULL_SPOKEN_REPLY = " ".join(["approximately"] * 110)


def _voice_budget() -> int:
    lane = chief_models.lane_for_chat("chief", "voice")
    assert lane == "voice", "a spoken turn must ride the voice lane"
    return chief_models.max_tokens_for(lane, default=1600)


def test_the_voice_budget_fits_a_full_reply_plus_the_biggest_plan():
    need = _tokens(_FULL_SPOKEN_REPLY) + _tokens(_BIG_PLAN)
    assert _voice_budget() >= need, (
        f"voice lane allows {_voice_budget()} tokens but a full spoken reply plus an "
        f"8-step show_plan needs ~{need}. The tag is emitted in the same completion "
        f"and gets cut mid-JSON, and a truncated tag is DROPPED — so Chief says "
        f"'here, look at this' and nothing appears."
    )


def test_the_voice_budget_fits_a_full_reply_plus_the_biggest_readout():
    need = _tokens(_FULL_SPOKEN_REPLY) + _tokens(_BIG_READOUT)
    assert _voice_budget() >= need, (
        f"voice lane allows {_voice_budget()} tokens but a full spoken reply plus a "
        f"4-block show_readout needs ~{need}."
    )


def test_there_is_real_headroom_not_a_hairline_pass():
    """A budget that only just fits is the same bug waiting for a
    slightly chattier turn. Require room for both artifacts at once —
    Chief can legitimately show and then plan in one breath."""
    need = _tokens(_FULL_SPOKEN_REPLY) + _tokens(_BIG_PLAN) + _tokens(_BIG_READOUT)
    assert _voice_budget() >= need, (
        f"voice lane {_voice_budget()} < {need} — no headroom for a turn that both "
        f"shows something and proposes a plan"
    )


def test_a_truncated_tag_is_counted_and_not_silent():
    """It used to be a bare print into stdout. That is how it went
    unnoticed: every other signal said the turn succeeded."""
    tok = cos._TRUNCATED_TAGS.set(0)
    try:
        actions, clean = cos._extract_actions_and_clean(
            'Here, look at this. [ACTION:{"type":"show_view","view":"invoi'
        )
        assert actions == [], "a half-written tag must never execute"
        assert cos.truncated_tags() == 1, "the drop must be countable, not just printed"
        assert "[ACTION" not in clean, "the fragment must not leak into what is spoken"
    finally:
        cos._TRUNCATED_TAGS.reset(tok)


def test_a_complete_tag_still_parses_and_is_not_counted():
    tok = cos._TRUNCATED_TAGS.set(0)
    try:
        actions, clean = cos._extract_actions_and_clean(
            'Here you go. [ACTION:{"type":"show_view","view":"invoices","filter":"open"}]'
        )
        assert [a["type"] for a in actions] == ["show_view"]
        assert cos.truncated_tags() == 0
    finally:
        cos._TRUNCATED_TAGS.reset(tok)
