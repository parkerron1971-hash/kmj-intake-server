"""
test_presentation.py — how a module feels is part of the spec.

Kevin 2026-09-05: the tracker worked but felt like a plain form. The
generalization pattern applied to feel: the model decides the empty-state
sentence, the celebration line, the milestone names and the register from
the practitioner's own words; the output is a closed validated shape; the
archetype component draws it. Three things have to hold:

  1. The shape is closed and safe — a bad value reads oddly at worst,
     never breaks a build (presentation_from_spec never raises).
  2. It reaches the row — materialize writes it, upgrade carries it.
  3. The prompt teaches it — every key, every tone, and the rule that
     every module gets an empty_line.
"""
from __future__ import annotations

import inspect
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import build_skills as bs
import module_spec_generator as msg


def _spec(**over):
    base = {
        "slug": "credit-profiles", "name": "Credit Profiles", "description": "d",
        "intake_excerpt": "i", "reasoning": "r",
        "archetype": "fallback_generic", "archetype_fallback_reason": "test",
        "schema": {"fields": [{"name": "t", "type": "text", "label": "T"}], "views": ["list"]},
    }
    base.update(over)
    return base


# ─── 1. the shape ─────────────────────────────────────────────────────

def test_default_is_empty_and_every_key_optional():
    spec = msg.ModuleSpec.model_validate(_spec())
    assert spec.presentation.model_dump(exclude_none=True) == {"milestone_labels": {}}


def test_a_full_presentation_validates():
    p = {"empty_line": "Pull the first report and the climb starts here.",
         "reached_line": "Prime territory — 720 and climbing.",
         "milestone_labels": {"620": "Fair", "680": "Good", "720": "Prime"},
         "tone": "bold"}
    spec = msg.ModuleSpec.model_validate(_spec(presentation=p))
    assert spec.presentation.tone == "bold"
    assert spec.presentation.milestone_labels["720"] == "Prime"


def test_tone_is_a_closed_choice():
    with pytest.raises(ValueError):
        msg.ModuleSpec.model_validate(_spec(presentation={"tone": "exciting"}))


def test_milestone_keys_must_be_numbers():
    with pytest.raises(ValueError, match="is not a number"):
        msg.ModuleSpec.model_validate(_spec(presentation={"milestone_labels": {"prime": "720"}}))


def test_a_line_stays_one_line():
    with pytest.raises(ValueError):
        msg.ModuleSpec.model_validate(_spec(presentation={"empty_line": "x" * 141}))


def test_blank_lines_and_labels_are_dropped_not_kept():
    spec = msg.ModuleSpec.model_validate(_spec(presentation={
        "empty_line": "   ", "milestone_labels": {"620": "  ", "680": "Good"}}))
    assert spec.presentation.empty_line is None
    assert spec.presentation.milestone_labels == {"680": "Good"}


def test_presentation_from_spec_never_raises():
    """The row write must not fail over a feel. A malformed blob renders
    the archetype's defaults."""
    assert msg.presentation_from_spec({"presentation": {"tone": "nope"}}) == {}
    assert msg.presentation_from_spec({"presentation": "not a dict"}) == {}
    assert msg.presentation_from_spec({}) == {}
    out = msg.presentation_from_spec({"presentation": {"empty_line": "Go.", "tone": "warm"}})
    assert out == {"empty_line": "Go.", "tone": "warm", "milestone_labels": {}}


# ─── 2. it reaches the row ────────────────────────────────────────────

def test_materialize_writes_presentation_and_upgrade_carries_it():
    src = inspect.getsource(msg)
    assert '"presentation": presentation_from_spec(spec)' in src, (
        "materialize_spec's write_payload does not carry presentation — "
        "the model's choice would be captured and discarded, the exact "
        "public_display bug of 2026-08-13")
    assert '"presentation": module.get("presentation") or {}' in src, (
        "regenerate_for_upgrade does not show the model the current "
        "presentation, so an upgrade would overwrite lines the practitioner "
        "may have come to like")
    assert "PRESENTATION: if the current presentation is empty" in msg._UPGRADE_GUIDANCE


# ─── 3. the prompt teaches it ─────────────────────────────────────────

@pytest.mark.parametrize("key", ["empty_line", "reached_line", "milestone_labels", "tone"])
def test_prompt_teaches_every_presentation_key(key):
    assert key in msg._SYSTEM_PROMPT


@pytest.mark.parametrize("tone", msg.TONES)
def test_prompt_teaches_every_tone(tone):
    block = msg._SYSTEM_PROMPT.split("PRESENTATION — how the module FEELS", 1)[1]
    assert f'"{tone}"' in block


def test_prompt_forbids_the_generic_empty_state():
    assert '"No data yet"' in msg._SYSTEM_PROMPT


def test_tracker_skill_carries_presentation_guidance():
    skill = next(s for s in bs.load_skills() if s["name"] == "tracker-module")
    assert "reached_line" in skill["body"]
    assert "milestone_labels" in skill["body"]
