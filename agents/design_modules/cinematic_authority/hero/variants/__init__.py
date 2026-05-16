"""The six Cathedral Hero variants. Each is one function consuming a
(RenderContext, brand_vars, treatment_vars) tuple and returning an HTML
<section> string.

Combinatorial math: 6 variants × 3 color emphases × 3 spacing densities
× 3 emphasis weights = 162 unique structural compositions. Multiplied
by content + brand kit variation, the effective unique-Hero space is
millions of combinations — the spike thesis.

Variant cluster by structural personality:
  Text-anchored:    manifesto_center, layered_diamond
  Two-column:       asymmetric_left (60/40), asymmetric_right (50/50)
  Compound:         split_stacked (manifesto + columns)
  Image-dominant:   full_bleed_overlay
"""

from .manifesto_center import render_manifesto_center
from .asymmetric_left import render_asymmetric_left
from .asymmetric_right import render_asymmetric_right
from .full_bleed_overlay import render_full_bleed_overlay
from .split_stacked import render_split_stacked
from .layered_diamond import render_layered_diamond

VARIANT_REGISTRY = {
    "manifesto_center": render_manifesto_center,
    "asymmetric_left": render_asymmetric_left,
    "asymmetric_right": render_asymmetric_right,
    "full_bleed_overlay": render_full_bleed_overlay,
    "split_stacked": render_split_stacked,
    "layered_diamond": render_layered_diamond,
}

__all__ = ["VARIANT_REGISTRY", *VARIANT_REGISTRY.keys()]
