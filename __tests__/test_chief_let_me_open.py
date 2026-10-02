"""
test_chief_let_me_open.py — "Let me open it" with nothing opened is caught (2026-09-23).

Live: asked for pricing help, Chief said "...that's exactly what The
Academy is built to work through with you ... Let me open it." and the
turn ran no action at all (actions=0). A plain promise to open a page now
counts as a described action, so the missing-action retry runs; an offer
("want me to open it?") never does.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos


@pytest.mark.parametrize("text", [
    "That's exactly what The Academy is built for. Let me open it.",
    "I'll pull up your invoices.",
    "Taking you there.",
    "Opening it now.",
])
def test_a_plain_promise_to_open_is_an_action_claim(text):
    assert cos._looks_like_completed_action(text), text


@pytest.mark.parametrize("text", [
    "Want me to open it?",
    "I'll open it once you're ready.",
    "If you'd like, I'll pull up your invoices.",
    "Say the word and I'll take you there.",
    "Here's the pricing I'd suggest for the intensive.",
])
def test_an_offer_is_not(text):
    assert not cos._looks_like_completed_action(text), text
