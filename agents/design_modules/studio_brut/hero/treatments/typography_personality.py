"""Studio Brut typography_personality — display sans / condensed sans
/ brutalist sans (NEVER classical romantic serif). Default font stack
declared in heading.py uses Druk / Bebas Neue / Space Grotesk /
Archivo Black / Inter at extreme weights.

The four typography options map onto Studio Brut's emphasis-mode
selector in heading.py (color / weight / scale / scale_color), so the
typography dimension simultaneously controls:
  - heading font weight + line-height + tracking + case
  - subtitle weight + italic
  - eyebrow tracking + weight + italic permission
  - heading emphasis-mode (which is the most visually significant
    distinction between Studio Brut typography settings)

Options:
  editorial — baseline. weight 800, line-height 0.95, tracking -0.02em,
              no italic, eyebrow tracking 0.22em / weight 800. Heading
              emphasis = COLOR contrast (signal-colored word).

  bold      — weight 900, line-height 0.9, tracking -0.04em (tightest),
              text-transform UPPERCASE, eyebrow tracking 0.18em /
              weight 900. Heading emphasis = WEIGHT contrast.

  refined   — weight 600 (lighter than baseline), line-height 1.0,
              tracking 0em (normal), eyebrow tracking 0.30em / weight
              500. Heading emphasis = SCALE contrast (oversized word
              among smaller).

  playful   — weight 700, line-height 0.95, tracking -0.01em + italic
              permitted on eyebrow + subtitle (not heading itself).
              Eyebrow tracking 0.36em / weight 600. Heading emphasis =
              SCALE + COLOR combined (oversized AND signal-colored).
"""
from __future__ import annotations

from typing import Dict

from ..types import TypographyPersonality


def typography_personality_vars(value: TypographyPersonality) -> Dict[str, str]:
    """Return CSS variable assignments for the given typography personality."""
    if value == "editorial":
        return {
            "--sb-heading-weight":      "800",
            "--sb-heading-line-height": "0.95",
            "--sb-heading-tracking":    "-0.02em",
            "--sb-heading-style":       "normal",
            "--sb-heading-case":        "none",
            "--sb-subtitle-italic":     "normal",
            "--sb-subtitle-weight":     "500",
            "--sb-eyebrow-tracking":    "0.22em",
            "--sb-eyebrow-weight":      "800",
            "--sb-eyebrow-style":       "normal",
            "--sb-cta-style":           "normal",
        }
    if value == "bold":
        return {
            "--sb-heading-weight":      "900",
            "--sb-heading-line-height": "0.9",
            "--sb-heading-tracking":    "-0.04em",
            "--sb-heading-style":       "normal",
            "--sb-heading-case":        "uppercase",
            "--sb-subtitle-italic":     "normal",
            "--sb-subtitle-weight":     "600",
            "--sb-eyebrow-tracking":    "0.18em",
            "--sb-eyebrow-weight":      "900",
            "--sb-eyebrow-style":       "normal",
            "--sb-cta-style":           "normal",
        }
    if value == "refined":
        return {
            "--sb-heading-weight":      "600",
            "--sb-heading-line-height": "1.0",
            "--sb-heading-tracking":    "0em",
            "--sb-heading-style":       "normal",
            "--sb-heading-case":        "none",
            "--sb-subtitle-italic":     "normal",
            "--sb-subtitle-weight":     "400",
            "--sb-eyebrow-tracking":    "0.30em",
            "--sb-eyebrow-weight":      "500",
            "--sb-eyebrow-style":       "normal",
            "--sb-cta-style":           "normal",
        }
    # playful
    return {
        "--sb-heading-weight":      "700",
        "--sb-heading-line-height": "0.95",
        "--sb-heading-tracking":    "-0.01em",
        "--sb-heading-style":       "normal",  # heading body stays upright
        "--sb-heading-case":        "none",
        "--sb-subtitle-italic":     "italic",
        "--sb-subtitle-weight":     "500",
        "--sb-eyebrow-tracking":    "0.36em",
        "--sb-eyebrow-weight":      "600",
        "--sb-eyebrow-style":       "italic",
        "--sb-cta-style":           "italic",
    }
