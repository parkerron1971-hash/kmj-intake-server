"""Treatment-to-CSS-variable translators. Each treatment file exports
one function that takes the treatment value and returns a dict of CSS
variable name → value. The render layer merges all dicts and injects
them as inline :root-scoped styles on the section.

Treatments compose orthogonally — 8 independent dimensions:
  Original 3 (structural rhythm — Phase 2):
    color_emphasis × spacing_density × emphasis_weight = 27 combos
  Visual depth 5 (Phase 2.6):
    background × color_depth × ornament × typography × image_treatment
    = 4 × 3 × 3 × 4 × 4 = 576 combos
  Combined per variant: 27 × 576 = 15,552
  Across 11 variants: ~171k structural combinations (the planning doc's
  51,840 figure treats image_treatment as no-op for text-only variants,
  which trims the image dimension down for ~6 of the 11).
"""

# Original 3 (Phase 2)
from .color_emphasis import color_emphasis_vars
from .spacing_density import spacing_density_vars
from .emphasis_weight import emphasis_weight_vars
# Visual depth 5 (Phase 2.6)
from .background_treatment import background_treatment_vars
from .color_depth_treatment import color_depth_vars
from .ornament_treatment import (
    ornament_treatment_vars,
    ornament_extras_count,
    ornament_drops_optional,
)
from .typography_personality import typography_personality_vars
from .image_treatment import image_treatment_vars

__all__ = [
    # Original 3
    "color_emphasis_vars",
    "spacing_density_vars",
    "emphasis_weight_vars",
    # Visual depth 5
    "background_treatment_vars",
    "color_depth_vars",
    "ornament_treatment_vars",
    "ornament_extras_count",
    "ornament_drops_optional",
    "typography_personality_vars",
    "image_treatment_vars",
]
