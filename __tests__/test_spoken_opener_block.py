"""
test_spoken_opener_block.py — the call opener hint (voice latency arc 9/08).

The call now says "Let me take a look." aloud the instant a transcript
lands, while Chief thinks. If Chief then opens its reply with "Sure, let
me check…" the practitioner hears two acknowledgements in a row, which
is worse than the pause it replaced. The request carries what was said;
the voice lane's prompt tail tells Chief to continue from it.

What is pinned: the block names the exact phrase, forbids a second
acknowledgement, is empty when there is nothing to continue from,
collapses whitespace, caps length (a client field reaches the prompt),
and is appended only on the voice lane.
"""
from __future__ import annotations

import pathlib
import re
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

from _chief_source import chief_source  # noqa: E402
import chief_of_staff as cos  # noqa: E402


def test_block_names_the_phrase_and_forbids_a_second_opener():
    block = cos._spoken_opener_block("Let me take a look.")
    assert '"Let me take a look."' in block
    assert "do not repeat" in block
    assert "another acknowledgement" in block
    assert block.startswith("\n\n")


def test_block_is_empty_with_nothing_to_continue_from():
    assert cos._spoken_opener_block(None) == ""
    assert cos._spoken_opener_block("") == ""
    assert cos._spoken_opener_block("   ") == ""


def test_block_collapses_whitespace_and_caps_length():
    block = cos._spoken_opener_block("  Sure,\n   one   second.  ")
    assert '"Sure, one second."' in block
    long = "x" * 500
    block = cos._spoken_opener_block(long)
    quoted = re.search(r'"(x+)"', block).group(1)
    assert len(quoted) == 80


def test_request_carries_the_field_and_the_voice_lane_appends_it():
    assert "spoken_opener" in cos.ChatRequest.model_fields
    src = chief_source()
    # Appended right after the voice delivery block, on the voice lane only.
    m = re.search(
        r'if lane == "voice":\s*\n\s*system = system \+ chief_models\.VOICE_DELIVERY_BLOCK\s*\n'
        r'(?:\s*#.*\n)*\s*system = system \+ _spoken_opener_block\(req\.spoken_opener\)',
        src)
    assert m, "the opener block must ride the voice lane's delivery block"
