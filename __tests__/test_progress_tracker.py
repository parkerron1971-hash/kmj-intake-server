"""
test_progress_tracker.py — the sixth archetype, and the reason it exists.

The generic-fallback banner had recorded exactly two shapes on live
modules by 2026-09-05: a credit-repair consultant's Credit Profiles
("needs a CreditScoreTracker archetype with time-series visualization
... and milestone alerts") and three barber reward trackers ("needs a
RewardProgress archetype ... visual progress bar (e.g. 5/7 haircuts)").
Both are a number moving toward a target. progress_tracker is that.

Three things have to hold, or Chief still builds a plain table:

  1. The archetype is REACHABLE — in the Literal, the metadata, the
     param models, and the prompt palette (the enum test covers the
     parity; this file covers the params contract).
  2. The trigger it promises — target_reached — actually fires, in the
     right direction, once per crossing.
  3. Chief's own prompt KNOWS the surface exists. A generator that can
     build a tracker behind a Chief that has never heard of one is the
     inspect_module bug again (registered, exposed, never named).
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import build_skills as bs
import module_agent as ma
import module_inspect as mi
import module_spec_generator as msg
import module_vocabulary as mv


# ─── fixtures ────────────────────────────────────────────────────────

def _fields():
    return [
        {"name": "client", "type": "contact_link", "label": "Client", "required": True},
        {"name": "score", "type": "number", "label": "Score", "required": True},
        {"name": "pulled_on", "type": "date", "label": "Pulled on"},
        {"name": "goal", "type": "number", "label": "Goal"},
        {"name": "notes", "type": "textarea", "label": "Notes"},
    ]


def _tracker(**params):
    base_params = {"mode": "reading", "subject_field": "client",
                   "value_field": "score", "date_field": "pulled_on",
                   "target": 720, "direction": "up", "milestones": [620, 680, 720]}
    base_params.update(params)
    return {
        "slug": "credit-profiles", "name": "Credit Profiles",
        "description": "Each client's score over time", "intake_excerpt": "track scores",
        "reasoning": "a number toward a goal",
        "archetype": "progress_tracker",
        "archetype_params": base_params,
        "schema": {"fields": _fields(), "views": ["list"], "default_view": "list"},
        "agent_config": {"enabled": True, "triggers": [
            {"type": "target_reached", "action": "draft_notification",
             "template": "{{contact_name}} hit 720"}]},
    }


# ─── 1. reachable, and the params contract ───────────────────────────

def test_registered_everywhere():
    assert "progress_tracker" in msg.ARCHETYPE_METADATA
    assert "progress_tracker" in msg._ARCHETYPE_PARAM_MODELS
    assert "progress_tracker" in msg.suggestable_archetypes()
    assert "progress_tracker" not in msg._SINGLE_INSTANCE_ARCHETYPES, (
        "a consultant tracks credit scores AND a savings goal; both must exist")


def test_a_good_tracker_validates():
    spec = msg.ModuleSpec.model_validate(_tracker())
    assert spec.archetype == "progress_tracker"
    assert spec.archetype_params["target"] == 720
    assert spec.archetype_params["direction"] == "up"


def test_reading_mode_needs_a_value_field():
    with pytest.raises(ValueError, match="value_field is required"):
        msg.ModuleSpec.model_validate(_tracker(value_field=None))


def test_count_mode_does_not_need_a_value_field():
    msg.ModuleSpec.model_validate(_tracker(mode="count", value_field=None))


def test_value_field_must_be_numeric():
    """A text column charts as NaN. Refused, not repaired."""
    with pytest.raises(ValueError, match="value_field 'notes' must be one of"):
        msg.ModuleSpec.model_validate(_tracker(value_field="notes"))


def test_field_refs_must_exist():
    with pytest.raises(ValueError, match="subject_field 'ghost' is not in schema.fields"):
        msg.ModuleSpec.model_validate(_tracker(subject_field="ghost"))


def test_date_field_must_be_a_date():
    with pytest.raises(ValueError, match="date_field 'score' must be one of"):
        msg.ModuleSpec.model_validate(_tracker(date_field="score"))


def test_a_target_is_required_one_way_or_the_other():
    with pytest.raises(ValueError, match="needs a target"):
        msg.ModuleSpec.model_validate(_tracker(target=None))
    msg.ModuleSpec.model_validate(_tracker(target=None, target_field="goal"))


def test_two_targets_disagree():
    with pytest.raises(ValueError, match="not both"):
        msg.ModuleSpec.model_validate(_tracker(target=720, target_field="goal"))


def test_direction_is_a_closed_choice():
    """Free text here would let 'higher' through, and the FE would treat
    it as 'up' by default — silently right for a score and silently
    wrong for a weight."""
    with pytest.raises(ValueError):
        msg.ModuleSpec.model_validate(_tracker(direction="higher"))


def test_the_prompt_teaches_the_trigger_and_both_modes():
    p = msg._SYSTEM_PROMPT
    assert "progress_tracker" in p
    assert "target_reached" in p
    assert '"count"' in p or "count —" in p
    assert "direction" in p


def test_upgrade_guidance_lets_a_fallback_module_move_to_a_real_archetype():
    """Credit Profiles is live on fallback_generic. The upgrade path used
    to pin the archetype unchanged, so upgrading it would have produced
    the same generic table with fresher field flags."""
    assert "fallback_generic" in msg._UPGRADE_GUIDANCE
    assert "pick that" in msg._UPGRADE_GUIDANCE


# ─── 2. the trigger ──────────────────────────────────────────────────

def test_target_reached_is_a_trigger_kind_the_agent_dispatches():
    assert "target_reached" in mv.TRIGGER_KINDS
    import inspect
    assert 'ttype == "target_reached"' in inspect.getsource(ma)


@pytest.mark.parametrize("prev,now,target,direction,expect", [
    (680, 725, 720, "up", True),      # crossed going up
    (725, 730, 720, "up", False),     # already there — no re-fire
    (None, 740, 720, "up", True),     # first reading already past it
    (700, 710, 720, "up", False),     # not there yet
    (185, 179, 180, "down", True),    # crossed going down (weight)
    (179, 175, 180, "down", False),   # already under
    (185, 182, 180, "down", False),   # not there yet
    (None, 180, 180, "down", True),   # equal counts as reached
])
def test_crossing_is_direction_aware_and_fires_once(prev, now, target, direction, expect):
    assert ma._crossed(prev, now, target, direction) is expect


def test_nan_and_text_are_not_readings():
    assert ma._to_number("abc") is None
    assert ma._to_number(float("nan")) is None
    assert ma._to_number("720") == 720.0


def test_inspector_accepts_the_trigger_on_a_tracker():
    rep = mi.inspect_module_schema(
        {"fields": _fields(), "views": ["list"]},
        {"triggers": [{"type": "target_reached", "action": "draft_notification"}]},
        "progress_tracker")
    assert rep["renderable"]
    assert not [w for w in rep["warnings"] if "target_reached" in w]


def test_inspector_warns_when_the_trigger_is_on_the_wrong_archetype():
    rep = mi.inspect_module_schema(
        {"fields": _fields(), "views": ["list"]},
        {"triggers": [{"type": "target_reached", "action": "draft_notification"}]},
        "work_pipeline")
    assert any("target_reached" in w and "never fire" in w for w in rep["warnings"])


def test_inspector_stays_quiet_when_it_does_not_know_the_archetype():
    """A caller that cannot say which archetype the module is must not
    be told about a fault the inspector cannot see."""
    rep = mi.inspect_module_schema(
        {"fields": _fields(), "views": ["list"]},
        {"triggers": [{"type": "target_reached", "action": "draft_notification"}]})
    assert not [w for w in rep["warnings"] if "target_reached" in w]


# ─── 3. the skill, and Chief's awareness ─────────────────────────────

def test_the_tracker_skill_selects_on_the_live_intake():
    """The words from the live Credit Profiles intake, and the reward
    intake, both pull the tracker skill first."""
    for text in (
        "I help clients repair their credit and want to see each score climb toward 720",
        "every seventh haircut is free, track visits",
        "track my clients' weight loss progress week by week",
    ):
        names = [s["name"] for s in bs.select_skills(text, "consultant")]
        assert names and names[0] == "tracker-module", (text, names)


def test_the_tracker_skill_does_not_hijack_a_booking():
    names = [s["name"] for s in bs.select_skills(
        "I need to keep track of my appointments and who showed up", "barber")]
    assert "tracker-module" not in names[:1], names


def test_chief_prompt_names_every_suggestable_archetype():
    """Registered is not the same as offered. Every archetype Chief may
    suggest must be described in the block Chief's prompt carries, by its
    practitioner-facing label."""
    block = msg.module_palette_block()
    for name in msg.suggestable_archetypes():
        assert msg.ARCHETYPE_METADATA[name]["label"] in block, name
    assert "Generic Module" not in block


def test_chief_prompt_source_carries_the_palette():
    # chief_prompt and chief_of_staff import each other; the app always
    # enters through chief_of_staff, so the test does too.
    import chief_of_staff  # noqa: F401
    import chief_prompt
    import inspect
    src = inspect.getsource(chief_prompt)
    assert "{_module_palette_block()}" in src, (
        "the palette function exists but the prompt never interpolates it")
    assert "Progress" in chief_prompt._module_palette_block()


def test_every_metadata_entry_has_a_pitch():
    for name, meta in msg.ARCHETYPE_METADATA.items():
        assert (meta.get("pitch") or "").strip(), f"{name} has no pitch for Chief"


# ─── the sentence that made Chief refuse (2026-09-05, live) ──────────

def test_chief_prompt_does_not_describe_upgrade_as_booking_only():
    """Live: Kevin pressed 'Ask Chief to upgrade it' on Credit Profiles and
    Chief answered that the upgrade 'currently only refines one archetype —
    booking_calendar' and offered a build request instead. The handler had
    no such guard; Chief was reading its own action description, which
    still said so. The prompt must describe the upgrade as re-reading the
    module against the current palette, and must forbid offering a build
    request for a shape the palette already has."""
    import chief_of_staff  # noqa: F401 — import order (circular)
    import chief_prompt
    import inspect
    src = inspect.getsource(chief_prompt)
    assert "service catalog for booking_calendar). Renders" not in src
    assert "WHAT YOU BUILD WELL" in src.split("upgrade_module_archetype", 1)[1][:1500]
    assert "never offer queue_build_request for one" in src
