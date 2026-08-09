"""
test_design_moves.py — the vocabulary must have renderers.

THE BUG THIS FILE EXISTS TO MAKE IMPOSSIBLE (2026-08-09 design review):
spec_author taught the Director thirteen named moves — THE THREAD, THE
STAGE LIGHT, THE FOIL and ten more — and a grep of the ENTIRE render path
found zero implementations of any of them. The Director committed real
specs to moves no builder had ever heard of, the judge correctly reported
them missing, and that complaint was recycled into the next brief as a
prohibition. A full build burned per iteration.

The load-bearing test here is `test_every_primitive_passes_the_validator`.
A primitive that cannot survive atelier_validator is not a renderer — it
is the same promise-without-delivery in a new place, and it fails LOUDER
than the original bug because the validator discards the whole chunk
(hero included) on a colour violation.
"""
import re

import pytest

import design_moves
from design_moves import MOVES, MOVE_NAMES


# ─── 1. The vocabulary is one list ───────────────────────────────────

def test_the_director_and_the_builders_read_the_same_list():
    """The original defect was two vocabularies: one taught to the
    Director, none taught to the builders. Both blocks are now generated
    from MOVES, so a move cannot appear in one and not the other."""
    director = design_moves.director_block()
    builder = design_moves.builder_block()
    for name in MOVE_NAMES:
        assert name in director, f"{name} missing from the Director's block"
        assert name in builder, f"{name} missing from the builder's block"


def test_every_move_has_a_real_primitive():
    """A move with an empty or hand-wavy css field is the old bug."""
    for name, m in MOVES.items():
        assert m.css.strip(), f"{name} has no primitive"
        assert "{" in m.css and "}" in m.css, f"{name}'s primitive is not CSS"
        assert ".scope" in m.css, f"{name}'s primitive must be scopeable"
        assert m.intent.strip() and m.recur.strip(), name


def test_recurrence_is_specified_because_one_use_is_decoration():
    """The spec's own doctrine: 'a move used once is decoration; used
    three ways it becomes the site's spine.' The Director cannot honour
    that unless each move says where it recurs."""
    for name, m in MOVES.items():
        assert len(m.recur) > 20, f"{name}'s recurrence rule is too thin"


# ─── 2. The load-bearing one ─────────────────────────────────────────

def _fragment_for(css: str, uid: str = "abc12345"):
    scoped = css.replace(".scope", f".atl-{uid}")
    html = (f'<section class="atl-{uid}">'
            f'<h2>A heading</h2><p>Body copy that is long enough to read '
            f'like real prose rather than filler.</p></section>')
    return html, scoped


@pytest.mark.parametrize("name", MOVE_NAMES)
def test_every_primitive_passes_the_validator(name):
    """THE TEST THAT MATTERS.

    atelier_validator does not warn on a colour violation — it fails the
    fragment, and canvas.py then discards the entire chunk and renders
    that section from module templates while the build still reports
    success. So a primitive that trips the validator would reproduce the
    original bug with an extra step.

    Specifically this pins that the primitives never use: hex literals,
    rgb()/hsl()/lab()/lch()/oklch(), non-neutral rgba(), or url()/data:."""
    import atelier_validator as av
    html, css = _fragment_for(MOVES[name].css)
    _ok, problems = av.validate_fragment(html, css, uid="abc12345",
                                         kind="hero", data={})
    forbidden = [p for p in problems
                 if any(k in p.lower() for k in
                        ("color", "colour", "rgba", "external", "url"))]
    assert not forbidden, f"{name} primitive is not renderable: {forbidden}"


def test_the_banned_syntax_is_actually_still_banned():
    """Control for the test above: prove the validator would catch the
    spec's 'natural' form, so a passing primitive means something.

    rgba(217,165,20,0.28) is exactly what the blueprint asks for and
    exactly what the validator rejects — the collision at the heart of
    the review."""
    import atelier_validator as av
    html, css = _fragment_for(
        ".scope .glow{background:radial-gradient(circle,"
        "rgba(217,165,20,0.28),transparent 60%);}")
    _ok, problems = av.validate_fragment(html, css, uid="abc12345",
                                         kind="hero", data={})
    assert any("rgba()" in p for p in problems), \
        "the validator stopped rejecting non-neutral rgba — re-check the " \
        "primitives, they may no longer be proving anything"


# ─── 3. The tinting rule must be taught, since nobody guesses it ─────

def test_color_mix_is_taught_not_merely_used():
    """color-mix appeared 134 times in site_modules/ and ZERO times in
    every authoring prompt. The deterministic templates built the glow
    the AI authors were forbidden to build and never told about."""
    block = design_moves.builder_block()
    assert "color-mix(in srgb" in block
    assert "var(--sx-accent)" in block
    # And it is stated as a rule, not just embedded in snippets.
    assert "TINTING RULE" in block


def test_primitives_tint_with_tokens_never_literals():
    joined = "\n".join(m.css for m in MOVES.values())
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", joined), "hex literal"
    assert not re.search(r"\b(?:rgb|hsl|hwb|lab|lch|oklab|oklch)\(", joined)
    assert "url(" not in joined and "data:" not in joined
    # rgba survives only in the two neutral forms the validator permits.
    for m in re.finditer(r"rgba\([^)]*\)", joined):
        assert re.match(r"rgba\(\s*(?:0\s*,\s*0\s*,\s*0|255\s*,\s*255\s*,\s*255)",
                        m.group(0)), m.group(0)


# ─── 4. Motion discipline the live page got wrong ────────────────────

def test_motion_primitives_respect_reduced_motion():
    for name, m in MOVES.items():
        if m.group != "MOTION":
            continue
        assert "prefers-reduced-motion" in m.css, \
            f"{name} animates without a reduced-motion escape"


def test_kinetic_hero_does_not_animate_a_property_js_also_drives():
    """THE LIVE BUG THIS ENCODES: KMJ's signature cursor-drifting glow is
    written by JS to element.style.transform and silently discarded,
    because a CSS animation with fill-mode:forwards outranks inline
    styles for ever. The measured computed transform stayed
    matrix(1,0,0,1,0,0) at every cursor position.

    THE STAGE LIGHT therefore animates NOTHING, and THE KINETIC HERO
    animates transform only on elements no script drives."""
    assert "animation" not in MOVES["THE STAGE LIGHT"].css, \
        "the stage light must stay animation-free so a cursor-drift or " \
        "scroll handler can own its transform"
    kinetic = MOVES["THE KINETIC HERO"].css
    assert "forwards" in kinetic and "sx-line" in kinetic


def test_the_stage_light_has_a_core_and_a_spill():
    """A single flat radial reads as fog, not a lamp — which is what
    shipped, and what the judge scored motif_visibility 6 for."""
    css = MOVES["THE STAGE LIGHT"].css
    assert "sx-stage-core" in css and "sx-stage-spill" in css
    assert "sx-grain" in css, "grain is half the move"


def test_move_names_in_reads_a_spec():
    txt = "Section 4: the page commits to THE STAGE LIGHT and THE FOIL."
    found = design_moves.move_names_in(txt)
    assert "THE STAGE LIGHT" in found and "THE FOIL" in found
    assert "THE ORBIT" not in found


# ─── 5. The wiring — every author is actually taught ─────────────────

def test_every_authoring_prompt_teaches_the_primitives():
    """The gap was not that the primitives were wrong. There were none,
    and no prompt carried them. Pin all four surfaces so a future prompt
    refactor cannot quietly drop the half that does the rendering."""
    import atelier, canvas, builder_v2
    surfaces = {
        "atelier": atelier._SYSTEM_PROMPT,
        "atelier refine": atelier._REFINE_SYSTEM_PROMPT,
        "canvas": canvas._SYSTEM_PROMPT,
        "builder_v2": builder_v2._SYSTEM,
    }
    for label, prompt in surfaces.items():
        assert "color-mix(in srgb" in prompt, f"{label} not taught the tint"
        assert "TINTING RULE" in prompt, f"{label} missing the stated rule"
        for move in ("THE STAGE LIGHT", "THE FOIL", "THE THREAD"):
            assert move in prompt, f"{label} missing {move}"


def test_the_director_vocabulary_is_generated_not_hardcoded():
    """spec_author used to carry its own literal list, which is how it
    drifted to thirteen moves with zero renderers."""
    import spec_author
    assert "{MOVES_VOCABULARY}" not in spec_author._SYSTEM, \
        "placeholder left unsubstituted — the Director lost its vocabulary"
    for name in MOVE_NAMES:
        assert name in spec_author._SYSTEM, f"{name} missing from the Director"
    assert "RECURRENCE:" in spec_author._SYSTEM


def test_director_and_builders_cannot_drift():
    """The invariant, stated once: anything the Director may name, a
    builder has been handed a working primitive for."""
    import spec_author
    import atelier
    for name in MOVE_NAMES:
        assert name in spec_author._SYSTEM and name in atelier._SYSTEM_PROMPT, name
