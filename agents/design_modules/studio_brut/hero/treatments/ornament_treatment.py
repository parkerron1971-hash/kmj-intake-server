"""Studio Brut ornament_treatment — squares, circles, bars, color
blocks (NEVER diamonds).

Studio Brut's ornament scaling runs hotter than Cathedral's at each
step because Studio Brut accepts louder visual presence:

  minimal   — opacity 0.7, size 0.85. Restrained but still visible.
  signature — opacity 0.95, size 1.0. Default Studio Brut energy.
  heavy     — opacity 1.0, size 1.55. Bold, decorated, ornament-as-
              co-star. Variants also render satellite ornaments
              (squares + circles + bars) when this treatment fires.

The structural helpers (ornament_extras_count, ornament_drops_optional)
follow the same contract as Cathedral so variants can branch
identically.
"""
from __future__ import annotations

from typing import Dict

from ..types import OrnamentTreatment


def ornament_treatment_vars(value: OrnamentTreatment) -> Dict[str, str]:
    """Return CSS variable assignments — multipliers applied by
    primitive ornament functions via calc()."""
    if value == "minimal":
        return {
            "--sb-ornament-opacity-mult": "0.7",
            "--sb-ornament-size-mult":    "0.85",
        }
    if value == "heavy":
        return {
            "--sb-ornament-opacity-mult": "1.0",
            "--sb-ornament-size-mult":    "1.55",
        }
    # signature (default)
    return {
        "--sb-ornament-opacity-mult": "0.95",
        "--sb-ornament-size-mult":    "1.0",
    }


def ornament_extras_count(value: OrnamentTreatment) -> int:
    """How many satellite ornaments to render beyond a variant's
    base set. Studio Brut heavy delivers 6 satellites (vs Cathedral's
    4) — Studio Brut commits harder to ornament density."""
    if value == "heavy":
        return 6
    return 0


def ornament_drops_optional(value: OrnamentTreatment) -> bool:
    """True when variants should skip optional ornament clusters —
    used for minimal to lean architectural-restrained."""
    return value == "minimal"
