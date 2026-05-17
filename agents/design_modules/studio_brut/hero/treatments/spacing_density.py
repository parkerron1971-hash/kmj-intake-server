"""Studio Brut spacing_density — denser than Cathedral at every step
per design doc principle: "Studio Brut 'generous' is denser than
Cathedral 'generous'."

  generous → 100-140px section padding (Cathedral generous: 80-160px)
  standard → 60-90px section padding (Cathedral standard: 60-100px)
  compact  → 32-48px section padding (Cathedral compact: 40-60px)

Studio Brut's max-content-width also runs tighter than Cathedral's,
matching the principle that Studio Brut commits to dense columns
rather than wide editorial measure.
"""
from __future__ import annotations

from typing import Dict

from ..types import SpacingDensity


def spacing_density_vars(density: SpacingDensity) -> Dict[str, str]:
    """Return CSS variable assignments for the given spacing density."""
    if density == "generous":
        return {
            "--sb-section-padding-y": "clamp(60px, 9vw, 140px)",
            "--sb-section-padding-x": "clamp(24px, 5vw, 80px)",
            "--sb-gap":               "28px",
            "--sb-content-max-width": "1180px",
            "--sb-column-gap":        "64px",
        }
    if density == "compact":
        return {
            "--sb-section-padding-y": "clamp(28px, 4.5vw, 48px)",
            "--sb-section-padding-x": "clamp(16px, 3.5vw, 40px)",
            "--sb-gap":               "12px",
            "--sb-content-max-width": "1080px",
            "--sb-column-gap":        "32px",
        }
    # standard
    return {
        "--sb-section-padding-y": "clamp(40px, 6vw, 90px)",
        "--sb-section-padding-x": "clamp(20px, 4vw, 56px)",
        "--sb-gap":               "20px",
        "--sb-content-max-width": "1120px",
        "--sb-column-gap":        "48px",
    }
