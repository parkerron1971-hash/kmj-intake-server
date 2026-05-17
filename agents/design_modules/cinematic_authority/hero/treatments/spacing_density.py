"""spacing_density treatment — controls section padding + element gaps.

Three options:
  generous  — 160px top/bottom section padding, larger element gaps.
              Cathedral at its most contemplative.
  standard  — 100px top/bottom. Default density.
  compact   — 60px top/bottom. Tighter element gaps.
              Cathedral at its most efficient.

The primitives also read --hero-section-padding-y, --hero-gap, and
--hero-content-max-width values from these vars. Variants compose
those for their layout choices.
"""
from __future__ import annotations

from typing import Dict

from ..types import SpacingDensity


def spacing_density_vars(density: SpacingDensity) -> Dict[str, str]:
    """Return CSS variable assignments for the given spacing density."""
    if density == "generous":
        return {
            "--hero-section-padding-y": "clamp(80px, 12vw, 160px)",
            "--hero-section-padding-x": "clamp(24px, 5vw, 80px)",
            "--hero-gap": "32px",
            "--hero-content-max-width": "1240px",
            "--hero-column-gap": "80px",
        }
    if density == "compact":
        return {
            "--hero-section-padding-y": "clamp(40px, 6vw, 60px)",
            "--hero-section-padding-x": "clamp(16px, 4vw, 48px)",
            "--hero-gap": "16px",
            "--hero-content-max-width": "1120px",
            "--hero-column-gap": "48px",
        }
    # standard
    return {
        "--hero-section-padding-y": "clamp(60px, 9vw, 100px)",
        "--hero-section-padding-x": "clamp(20px, 4.5vw, 64px)",
        "--hero-gap": "24px",
        "--hero-content-max-width": "1180px",
        "--hero-column-gap": "64px",
    }
