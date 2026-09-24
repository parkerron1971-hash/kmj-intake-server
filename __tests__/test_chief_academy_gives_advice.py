"""
test_chief_academy_gives_advice.py — Chief answers planning questions (2026-09-24).

Kevin: "it should always give advice, because if the session was done,
that advice would be wanted — but also give thought to, if the Academy is
not done, going back to finish." And it should say "Solutionist Academy" /
"Strategy Session". Live 9/23, asked what to charge for a two-day
intensive, Chief answered only "...that's exactly what The Academy is built
to work through with you... Let me open it." — the ACADEMY AWARENESS block
told it to deflect every pricing / business-model question.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff  # noqa: F401 — load order: chief_of_staff imports chief_prompt
import chief_prompt as cp

BIZ = {"settings": {"track": "strategy"}}
UNFINISHED = {"current_phase": "pricing_strategy", "status": "in_progress",
              "phases": {"discovery": {"summary": "coaching intensives"}},
              "market_research": {"gaps": "no weekend format"}}
FINISHED = {"current_phase": "launch_plan", "status": "complete",
            "phases": {"discovery": {"summary": "x"}},
            **{p: {"x": 1} for p in cp.STRATEGY_PHASES if p not in ("discovery", "service_packages")},
            "service_packages": [{"name": "Intensive"}]}


def test_the_deflection_is_gone_and_advice_comes_first():
    block = cp._format_strategy_block(BIZ, UNFINISHED)
    assert "ANSWER THEM" in block and "Never deflect" in block
    assert "That's a Strategy Session question" not in block
    assert '"type":"navigate"' not in block


def test_an_unfinished_academy_gets_one_closing_offer_to_finish():
    block = cp._format_strategy_block(BIZ, UNFINISHED)
    assert "Still to do: Business Model Canvas, Pricing Strategy" in block
    assert "ONE short closing line" in block and "do not navigate unless they say yes" in block


def test_a_finished_academy_is_built_on_not_sent_back_to():
    block = cp._format_strategy_block(BIZ, FINISHED)
    assert "Their Academy is finished" in block
    assert "Still to do" not in block and "closing line" not in block


def test_it_is_called_the_solutionist_academy_and_a_strategy_session():
    block = cp._format_strategy_block(BIZ, UNFINISHED)
    assert "SOLUTIONIST ACADEMY" in block and "STRATEGY SESSION" in block


def test_no_track_row_still_answers():
    block = cp._format_strategy_block(BIZ, None)
    assert "ANSWER THEM" in block and "closing line" in block
