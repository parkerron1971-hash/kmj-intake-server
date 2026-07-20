"""DRO enum coercion + vision-grader animation settle (2026-07-20).

The 07-20 KMJ build authored a well-aligned DRO that validation discarded
over one invented enum value (hero_concept.direction='photographic_hero'),
dropping the build to the minimal bland DRO. Coercion now snaps out-of-enum
values (alias → fuzzy → drop) inside _validate_dro. Separately, the vision
grader screenshotted pages mid-entrance-animation and judged them broken;
it now fast-forwards animations before shooting.
"""
import agents.composer.drl.passes as passes
import vision_grader


def _valid_dro():
    block = {"because": "x", "from_signals": ["opening_posture"]}
    return {"decisions": {dec: dict(block) for dec in passes.REQUIRED_DECISIONS}}


def test_enum_alias_snap():
    dro = _valid_dro()
    dro["decisions"]["hero_concept"]["direction"] = "photographic_hero"
    assert passes._validate_dro(dro) == []
    assert dro["decisions"]["hero_concept"]["direction"] == "portrait_presence"


def test_enum_fuzzy_snap():
    dro = _valid_dro()
    dro["decisions"]["hero_concept"]["direction"] = "visual_metaphore"
    assert passes._validate_dro(dro) == []
    assert dro["decisions"]["hero_concept"]["direction"] == "visual_metaphor"


def test_enum_no_match_drops_field():
    dro = _valid_dro()
    dro["decisions"]["hero_concept"]["direction"] = "zzz_no_such_axis"
    assert passes._validate_dro(dro) == []
    assert "direction" not in dro["decisions"]["hero_concept"]


def test_valid_values_untouched():
    dro = _valid_dro()
    dro["decisions"]["palette"]["base"] = "deep_dark"
    dro["decisions"]["layout"]["hierarchy_approach"] = "modular_blocks"
    assert passes._validate_dro(dro) == []
    assert dro["decisions"]["palette"]["base"] == "deep_dark"
    assert dro["decisions"]["layout"]["hierarchy_approach"] == "modular_blocks"


def test_structural_problems_still_reported():
    dro = _valid_dro()
    dro["decisions"]["layout"] = {"symmetry": "grid_modular"}  # no because/from_signals
    del dro["decisions"]["motion"]
    problems = passes._validate_dro(dro)
    assert any("layout" in p and "because" in p for p in problems)
    assert any("motion" in p for p in problems)


def test_coercion_idempotent():
    dro = _valid_dro()
    dro["decisions"]["hero_concept"]["direction"] = "photographic_hero"
    assert passes._validate_dro(dro) == []
    assert passes._validate_dro(dro) == []
    assert dro["decisions"]["hero_concept"]["direction"] == "portrait_presence"


def test_grader_settles_animations_before_screenshot():
    assert "animation-delay:0s" in vision_grader._ANIMATION_SETTLE_CSS
    assert "animation-duration:0.01s" in vision_grader._ANIMATION_SETTLE_CSS
