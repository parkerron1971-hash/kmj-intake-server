"""One voice on color (2026-09-04, the barbershop bench). builder_v2's
hard rule 7 says write the spec's hexes; the moves block appended to
the same prompt said NEVER a hex literal. The atelier and the canvas
still live under a token-only validator and keep the ban."""
import atelier
import builder_v2
import canvas
import design_moves


def test_the_builder_is_no_longer_told_two_things():
    assert "NEVER a hex literal" not in builder_v2._SYSTEM
    assert "write the spec's hexes ONCE, in :root" in builder_v2._SYSTEM
    # the primitives themselves still ride, tint rule and all
    assert "TINTING RULE" in builder_v2._SYSTEM
    assert "color-mix(in srgb" in builder_v2._SYSTEM


def test_rule_seven_says_once_in_root():
    assert "once, as :root custom properties" in builder_v2._SYSTEM


def test_token_only_surfaces_keep_the_ban():
    assert "NEVER a hex literal" in atelier._SYSTEM_PROMPT
    assert "NEVER a hex literal" in canvas._SYSTEM_PROMPT


def test_the_block_defaults_to_the_token_law():
    assert "NEVER a hex literal" in design_moves.builder_block()
    assert "NEVER a hex literal" not in design_moves.builder_block(color_law="hexes")
