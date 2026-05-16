"""typography_personality — the heading family's character.

Four options:

  editorial  — Playfair Display (serif), weight 900, line-height 1.05,
               letter-spacing -0.025em. The Cathedral default. Refined,
               authoritative, classic editorial.

  bold       — Playfair Display, weight 900, line-height 0.95 (tighter),
               letter-spacing -0.04em (tighter). Confident, declarative,
               more visual weight per word.

  refined    — Playfair Display, weight 500 (lighter), line-height 1.15
               (more breathing), letter-spacing -0.005em. Poetic,
               elegant, contemplative.

  playful    — Playfair Display Italic (italic by default), weight 600,
               line-height 1.05, letter-spacing 0.005em. Creative, lively.
               Subtitle also picks up italic phrases (via
               --ca-subtitle-italic). Eyebrow tracking loosens.

Variants consume via primitives — heading.py, subtitle.py, eyebrow.py
read these CSS vars and fall back to their own defaults if unset."""
from __future__ import annotations

from typing import Dict

from ..types import TypographyPersonality


def typography_personality_vars(value: TypographyPersonality) -> Dict[str, str]:
    """Return CSS variable assignments for the given typography personality.

    Variables consumed by primitives:
      --ca-heading-weight       — font-weight on heading
      --ca-heading-line-height  — line-height on heading
      --ca-heading-tracking     — letter-spacing on heading
      --ca-heading-style        — font-style ('normal' or 'italic')
      --ca-subtitle-italic      — subtitle font-style override
      --ca-subtitle-weight      — subtitle font-weight
      --ca-eyebrow-tracking     — eyebrow letter-spacing (default 0.22em)
      --ca-eyebrow-weight       — eyebrow font-weight (default 700)
    """
    if value == "editorial":
        return {
            "--ca-heading-weight": "900",
            "--ca-heading-line-height": "1.05",
            "--ca-heading-tracking": "-0.025em",
            "--ca-heading-style": "normal",
            "--ca-subtitle-italic": "normal",
            "--ca-subtitle-weight": "400",
            "--ca-eyebrow-tracking": "0.22em",
            "--ca-eyebrow-weight": "700",
        }
    if value == "bold":
        return {
            "--ca-heading-weight": "900",
            "--ca-heading-line-height": "0.95",
            "--ca-heading-tracking": "-0.04em",
            "--ca-heading-style": "normal",
            "--ca-subtitle-italic": "normal",
            "--ca-subtitle-weight": "500",
            "--ca-eyebrow-tracking": "0.18em",
            "--ca-eyebrow-weight": "800",
        }
    if value == "refined":
        return {
            "--ca-heading-weight": "500",
            "--ca-heading-line-height": "1.15",
            "--ca-heading-tracking": "-0.005em",
            "--ca-heading-style": "normal",
            "--ca-subtitle-italic": "normal",
            "--ca-subtitle-weight": "300",
            "--ca-eyebrow-tracking": "0.28em",
            "--ca-eyebrow-weight": "500",
        }
    # playful
    return {
        "--ca-heading-weight": "600",
        "--ca-heading-line-height": "1.05",
        "--ca-heading-tracking": "0.005em",
        "--ca-heading-style": "italic",
        "--ca-subtitle-italic": "italic",
        "--ca-subtitle-weight": "400",
        "--ca-eyebrow-tracking": "0.32em",
        "--ca-eyebrow-weight": "600",
    }
