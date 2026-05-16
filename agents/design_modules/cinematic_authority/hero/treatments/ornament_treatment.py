"""ornament_treatment — diamond density + prominence.

Three options:

  minimal   — diamond opacity scaled 0.55, size scaled 0.8. Variants
              skip optional ornament clusters. Restrained Cathedral
              for editorial / authority brands.

  signature — diamond opacity scaled 0.9, size scaled 1.0. Variants
              render their default ornament set. The Cathedral
              classic; clearly stated.

  heavy     — diamond opacity scaled 1.0, size scaled 1.4. Variants
              also render an extra ornament cluster (satellite
              diamonds) when this treatment is selected. Bold,
              decorated — ornament becomes visual co-star with content.

Variants consume:
  - the CSS variables via diamond_motif primitive, which applies
    --ca-ornament-opacity-mult + --ca-ornament-size-mult automatically
  - the ornament_extra_count integer via a structural branch:
      if treatments.ornament == 'heavy': render satellite cluster
      if treatments.ornament == 'minimal': skip optional ornaments
"""
from __future__ import annotations

from typing import Any, Dict

from ..types import OrnamentTreatment


def ornament_treatment_vars(value: OrnamentTreatment) -> Dict[str, str]:
    """Return CSS variable assignments. The primitive diamond_motif
    multiplies its inherent opacity + size by these scalars at render
    time."""
    if value == "minimal":
        return {
            "--ca-ornament-opacity-mult": "0.55",
            "--ca-ornament-size-mult": "0.8",
        }
    if value == "heavy":
        return {
            "--ca-ornament-opacity-mult": "1.0",
            "--ca-ornament-size-mult": "1.4",
        }
    # signature (default)
    return {
        "--ca-ornament-opacity-mult": "0.9",
        "--ca-ornament-size-mult": "1.0",
    }


def ornament_extras_count(value: OrnamentTreatment) -> int:
    """Structural hint for variants — how many extra 'satellite'
    diamonds to render beyond the variant's base set.

      minimal   → 0  (variants may also drop optional bases)
      signature → 0  (variants render their default cluster only)
      heavy     → 4  (variants add a scattered satellite cluster)
    """
    if value == "heavy":
        return 4
    return 0


def ornament_drops_optional(value: OrnamentTreatment) -> bool:
    """Structural hint — true when variants should skip 'optional'
    diamond clusters (e.g. crest flanks, corner stitches). Used for
    minimal treatment to lean editorial."""
    return value == "minimal"
