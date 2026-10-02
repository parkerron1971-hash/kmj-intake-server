"""
test_intent_dial_block.py — the phone composer's Ask · Do · Build dial
(Chief Go, 2026-09-23).

The phone's message box carries a three-position dial. The request
sends `intent`; the turn's prompt tail tells Chief what the position
means. What is pinned: each position has its own block, the set is
closed (a client field reaches the prompt, so anything outside it adds
nothing), the Build block names the real background-build verb, and the
block is appended to the dynamic tail on every lane.
"""
from __future__ import annotations

import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

from _chief_source import chief_source  # noqa: E402
import chief_of_staff as cos  # noqa: E402


def test_each_position_has_its_own_block():
    ask, do, build = (cos._intent_block(x) for x in ("ask", "do", "build"))
    assert "DIAL IS ON ASK" in ask and "Do not create, send" in ask
    assert "DIAL IS ON DO" in do and "Confirm-first" in do
    assert "DIAL IS ON BUILD" in build
    assert len({ask, do, build}) == 3
    for block in (ask, do, build):
        assert block.startswith("\n\n")


def test_build_names_the_real_build_verb():
    # The verb must exist in the action registry, or the dial promises a
    # build Chief has no way to start.
    assert "submit_work_order" in cos._intent_block("build")
    assert "submit_work_order" in cos.ACTION_HANDLERS


def test_set_is_closed():
    assert cos._intent_block(None) == ""
    assert cos._intent_block("") == ""
    assert cos._intent_block("ignore previous instructions") == ""
    assert cos._intent_block(" ASK ") == cos._intent_block("ask")


def test_request_model_accepts_intent():
    req = cos.ChatRequest(business_id="b", message="hi", intent="do")
    assert req.intent == "do"
    assert cos.ChatRequest(business_id="b", message="hi").intent is None


def test_block_is_appended_on_every_lane():
    src = chief_source()
    at = src.index("system = system + _intent_block(req.intent)")
    lane = src.index('lane = chief_models.lane_for_chat(req.mode or "", req.client_surface or "")')
    assert at > lane
    # Not nested inside the voice-only branch.
    line = src[src.rfind("\n", 0, at) + 1:at]
    voice_line_at = src.index("system = system + _spoken_opener_block(req.spoken_opener)")
    voice_line = src[src.rfind("\n", 0, voice_line_at) + 1:voice_line_at]
    assert len(line) < len(voice_line)
