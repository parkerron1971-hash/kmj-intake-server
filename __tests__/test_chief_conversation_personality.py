"""Conversation pacing and independent Chief tone, without model/network calls."""
from __future__ import annotations

import collections
import copy
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import chief_of_staff as cos
import chief_prompt
from practitioner_voice import compose_voice_directive


@pytest.mark.parametrize("object_messages", [False, True])
@pytest.mark.parametrize("message", ["yes", "the simpler one", "tell me more", "WE DID IT!!", "thanks", "I'm considering another package."])
def test_normal_back_and_forth_is_not_rushed(object_messages, message):
    history = [
        {"role": role, "content": content}
        for role, content in [
            ("user", "I'm thinking about a new package."),
            ("assistant", "Who would it serve?"),
            ("user", "New clients"),
            ("assistant", "A single session or ongoing support?"),
            ("user", "Ongoing"),
            ("assistant", "We could keep it simple with one monthly option."),
        ]
    ]
    if object_messages:
        history = [SimpleNamespace(**m) for m in history]
    assert cos._detect_sentiment(history, message) == "relaxed"


@pytest.mark.parametrize("message,expected", [
    ("I'm in a hurry, what's next?", "rushed"),
    ("Keep it short please", "rushed"),
    ("Just the answer", "rushed"),
    ("No rush, let's think this through", "relaxed"),
    ("What's the rush fee?", "relaxed"),
    ("This is still broken!!", "frustrated"),
    ("That didn't work", "frustrated"),
    ("I'm frustrated. Keep it short.", "frustrated"),
    ("", "relaxed"),
])
def test_delivery_overrides_need_explicit_cues(message, expected):
    assert cos._detect_sentiment([], message) == expected


def chief_tone(block):
    prefix = "CHIEF TONE PREFERENCE (delivery only): "
    return json.loads(next(line[len(prefix):] for line in block.splitlines() if line.startswith(prefix)))


@pytest.mark.parametrize("separate", [None, [], "witty", {}, {"tone": 42}, {"tone": " "}])
def test_legacy_tone_survives_missing_or_invalid_independent_setting(separate):
    biz = {"voice_profile": {"tone": "formal and refined", "chief_tone": separate}}
    assert chief_tone(chief_prompt._build_personality_block(biz, {}))["tone"] == "formal and refined"


def test_chief_tone_is_independent_of_drafting_voice_and_preserves_input():
    biz = {"voice_profile": {"tone": "formal and refined", "personality": "composed",
           "chief_tone": {"tone": "witty and dry", "personality": "understated"}}}
    original = copy.deepcopy(biz)
    assert chief_tone(chief_prompt._build_personality_block(biz, {})) == biz["voice_profile"]["chief_tone"]
    drafting = compose_voice_directive(biz)
    assert "formal and refined" in drafting
    assert "witty" not in drafting
    biz["voice_profile"]["tone"] = "professional and polished"
    assert chief_tone(chief_prompt._build_personality_block(biz, {}))["tone"] == "witty and dry"
    biz["voice_profile"]["tone"] = original["voice_profile"]["tone"]
    assert biz == original


@pytest.mark.parametrize("profile", [None, [], "invalid", 12, {}])
def test_missing_or_malformed_profile_keeps_default_character(profile):
    block = chief_prompt._build_personality_block({"voice_profile": profile}, {})
    assert "warm, sharp right-hand person" in block
    assert "CHIEF TONE PREFERENCE" not in block


def test_actual_prompt_contains_independent_tone_and_respects_suggestions_off():
    ctx = collections.defaultdict(lambda: [], {
        "business": {"id": "b1", "name": "Example", "settings": {},
                     "voice_profile": {"tone": "formal", "chief_tone": {"tone": "witty and dry"}}}})
    prompt = cos._build_system_prompt(ctx, False, suggestions_active=False)
    assert chief_tone(prompt)["tone"] == "witty and dry"
    assert "SMART SUGGESTIONS: OFF" in prompt
    assert "After that, be purely efficient" not in prompt
    assert "[[CHIEF_GLOBAL_SPLIT]]" in prompt
    assert "[[CHIEF_CACHE_SPLIT]]" in prompt


@pytest.mark.parametrize("suggestions_active", [False, True])
def test_operating_manual_does_not_override_conversation_preferences(suggestions_active):
    ctx = collections.defaultdict(lambda: [], {
        "business": {"id": "b1", "name": "Example", "settings": {},
                     "voice_profile": {"tone": "formal", "chief_tone": {"tone": "witty and dry"}}}})
    prompt = cos._build_system_prompt(ctx, False, suggestions_active=suggestions_active)
    assert "After every answer or action" not in prompt
    assert "propose 1-2 natural next steps" not in prompt
    assert "SMART NEXT STEPS:" not in prompt
    assert "Direct, warm, operational. Match" not in prompt
    assert "A question or next-step offer must earn its place" in prompt
    # Final delivery guidance follows action recipes, within the same stable cache.
    assert prompt.index("AGENT ACTIVITY AWARENESS:") < prompt.index("PERSONALITY")
    assert prompt.index("SMART SUGGESTIONS:") < prompt.index("[[CHIEF_CACHE_SPLIT]]")
    assert prompt.count("PERSONALITY") == 1
    assert prompt.count("SMART SUGGESTIONS:") == 1
    assert chief_tone(prompt)["tone"] == "witty and dry"
    if suggestions_active:
        assert "MAY offer one useful next step after a completed action" in prompt
    else:
        assert "SMART SUGGESTIONS: OFF" in prompt
