"""
test_directors_cut_brief.py — Director's Cut arc 1: the canvas brief
gains the elicitation mechanisms (language + named bar + judge lessons
+ ambition license), all fail-open.

The brief compiler stays pure — run_canvas resolves everything onto ctx
first; these tests exercise the compiler side of that contract.
"""
from canvas_brief import compile_canvas_brief


def _ctx(**over):
    base = {
        "business": {"name": "KMJ Creative Solutions", "type": "consultant"},
        "dna": {"palette": {"accent": "#c79d26", "mode": "dark"},
                "typography": {"heading": "Fraunces", "body": "Inter"}},
        "site_prefs": {},
    }
    base.update(over)
    return base


_SPEC = [{"module": "hero", "variant": "", "content": {}},
         {"module": "offerings", "variant": "", "content": {}}]


def test_language_and_bar_sections_appear_when_provided():
    brief = compile_canvas_brief(_ctx(
        language_key="mural",
        language_because="person-forward creative with bold conviction",
        language_brief_text="Color-block bands; person-through-type; triad palette.",
        reference_bar="- Reference bar: a Nike campaign page.",
    ), None, _SPEC)
    assert "THE DESIGN LANGUAGE" in brief
    assert "mural" in brief
    assert "person-forward creative" in brief
    assert "THE BAR" in brief
    assert "Nike campaign" in brief


def test_judge_lessons_ride_the_brief():
    brief = compile_canvas_brief(_ctx(
        judge_lessons=[
            "Numbered nav items read as template pattern",
            "Circle ornaments feel orphaned — floating decoration",
        ],
    ), None, _SPEC)
    assert "THE JUDGE'S EYE" in brief
    assert "Numbered nav items" in brief
    assert "Circle ornaments" in brief


def test_license_always_present():
    brief = compile_canvas_brief(_ctx(), None, _SPEC)
    assert "THE LICENSE" in brief
    assert "FAILURE" in brief


def test_fail_open_without_director_context():
    # No language / bar / lessons on ctx → sections simply absent,
    # brief still compiles with the original anatomy.
    brief = compile_canvas_brief(_ctx(), None, _SPEC)
    assert "THE DESIGN LANGUAGE" not in brief
    assert "THE JUDGE'S EYE" not in brief
    assert "== OVERVIEW ==" in brief
    assert "== SECTION PLAN (in order) ==" in brief


def test_owners_words_lead_the_brief():
    brief = compile_canvas_brief(_ctx(
        owner_brief="deep navy with warm gold, typographic hero with motion",
    ), None, _SPEC)
    assert "THE OWNER'S WORDS" in brief
    assert "deep navy with warm gold" in brief
    # they lead — before the overview
    assert brief.index("THE OWNER'S WORDS") < brief.index("== OVERVIEW ==")


def test_owners_words_absent_without_prompt():
    brief = compile_canvas_brief(_ctx(), None, _SPEC)
    assert "THE OWNER'S WORDS" not in brief


def test_vision_loop_env_switch():
    import os
    from unittest import mock
    import canvas
    with mock.patch.dict(os.environ, {"CANVAS_VISION_LOOP": "off"}):
        assert canvas._vision_loop_enabled() is False
    with mock.patch.dict(os.environ, {"CANVAS_VISION_LOOP": "on"}):
        assert canvas._vision_loop_enabled() is True
    # default (unset) = ON — checked in a cleared env so the conftest
    # test guard doesn't leak in, and nothing leaks out
    with mock.patch.dict(os.environ, {}, clear=True):
        assert canvas._vision_loop_enabled() is True


def test_self_review_fails_open_without_screenshots():
    from unittest import mock
    import canvas
    with mock.patch("vision_grader._screenshot", return_value=None):
        assert canvas._self_review("<html></html>", "brief", "biz") is None


def test_judge_lessons_capped_and_truncated():
    brief = compile_canvas_brief(_ctx(
        judge_lessons=[f"note {i}: " + "x" * 400 for i in range(20)],
    ), None, _SPEC)
    assert brief.count("- note") == 8
    # each note truncated to 240 chars
    for line in brief.splitlines():
        if line.startswith("- note"):
            assert len(line) <= 243
