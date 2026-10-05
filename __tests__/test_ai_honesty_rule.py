"""
test_ai_honesty_rule.py — every Solutionist voice says it is an AI when asked.

Bot-disclosure laws (California, Utah, Colorado, the EU) expect a plain
answer, and the SI naming must never become a way around one. Before this
rule nothing in Chief's prompt, the fast lane that answers short questions
like "are you a bot?", or the website concierge said what to do when asked
(found by the SI review, 2026-10-05).
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_fast_track
import chief_of_staff as cos
import site_concierge


def test_chief_and_both_coaches_say_they_are_an_ai():
    # CHIEF_SHARED_CORE is shared by Chief, the Strategy Coach and the
    # Business Coach, so the rule reaches all three.
    core = cos.CHIEF_SHARED_CORE
    assert "say plainly that you are an AI" in core
    assert "never claim or imply you are human" in core
    assert "never a way around saying you are an AI" in core


def test_the_fast_lane_says_it_too():
    # Short questions with no records ("are you a real person?") are
    # answered by Haiku alone, without Chief's main prompt.
    assert "say plainly that you are an AI" in chief_fast_track._FAST_SYSTEM
    assert "Never claim or imply you are human" in chief_fast_track._FAST_SYSTEM


def test_the_website_concierge_says_it_to_visitors():
    prompt = site_concierge.build_system_prompt(
        {"business": {"name": "Bloom Studio", "vertical": "salon"}})
    assert "you are an AI assistant for Bloom Studio, not a person" in prompt
    assert "Never claim or imply you are human" in prompt
