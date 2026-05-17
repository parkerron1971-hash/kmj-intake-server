"""Studio Brut treatment translators. Same 8-dimension framework as
Cathedral, different value interpretations grounded in Studio Brut's
DNA per STUDIO_BRUT_DESIGN.md.

Variable prefix convention: --sb-* (Studio Brut) vs Cathedral's --ca-*.
Distinct prefixes prevent any accidental cross-module CSS bleed when
both modules ever coexist in the same DOM (which they shouldn't, but
the discipline costs nothing).
"""

from .color_emphasis import color_emphasis_vars
from .spacing_density import spacing_density_vars
from .emphasis_weight import emphasis_weight_vars
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
    "color_emphasis_vars",
    "spacing_density_vars",
    "emphasis_weight_vars",
    "background_treatment_vars",
    "color_depth_vars",
    "ornament_treatment_vars",
    "ornament_extras_count",
    "ornament_drops_optional",
    "typography_personality_vars",
    "image_treatment_vars",
]
