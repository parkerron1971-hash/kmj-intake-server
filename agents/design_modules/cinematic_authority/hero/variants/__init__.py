"""The eleven Cathedral Hero variants. Each is one function consuming
a (RenderContext, brand_vars, treatment_vars) tuple and returning an
HTML <section> string.

Combinatorial math: 11 variants × 3 color emphases × 3 spacing densities
× 3 emphasis weights = 297 unique structural compositions. Multiplied
by content + brand kit variation, the effective unique-Hero space is
in the millions — the spike thesis.

Variant cluster by structural personality:
  Text-anchored centered:
    manifesto_center  (1) — symmetric + corner diamonds
    layered_diamond   (6) — anchor diamond behind heading
    quote_anchor      (7) — pull-quote led, no diamonds, big quote marks
    vertical_manifesto (9) — tall 100vh+ + diamond-rule chapter breaks

  Two-column with image:
    asymmetric_left   (2) — 60/40, framed portrait right
    asymmetric_right  (3) — 50/50, bleed landscape left

  Two-column without image (text-only):
    tabular_authority (8) — content left, 3 numeric stats right
    annotated_hero   (10) — annotations left, content right

  Compound (multi-row):
    split_stacked     (5) — manifesto top, image + value props row below
    cinematic_caption (11) — full-bleed image top, caption content below

  Image-dominant (single section):
    full_bleed_overlay (4) — image fills section, dark overlay + text
"""

# Phase 2 — original 6
from .manifesto_center import render_manifesto_center
from .asymmetric_left import render_asymmetric_left
from .asymmetric_right import render_asymmetric_right
from .full_bleed_overlay import render_full_bleed_overlay
from .split_stacked import render_split_stacked
from .layered_diamond import render_layered_diamond
# Phase 2.5 — library expansion
from .quote_anchor import render_quote_anchor
from .tabular_authority import render_tabular_authority
from .vertical_manifesto import render_vertical_manifesto
from .annotated_hero import render_annotated_hero
from .cinematic_caption import render_cinematic_caption

VARIANT_REGISTRY = {
    "manifesto_center": render_manifesto_center,
    "asymmetric_left": render_asymmetric_left,
    "asymmetric_right": render_asymmetric_right,
    "full_bleed_overlay": render_full_bleed_overlay,
    "split_stacked": render_split_stacked,
    "layered_diamond": render_layered_diamond,
    "quote_anchor": render_quote_anchor,
    "tabular_authority": render_tabular_authority,
    "vertical_manifesto": render_vertical_manifesto,
    "annotated_hero": render_annotated_hero,
    "cinematic_caption": render_cinematic_caption,
}

__all__ = ["VARIANT_REGISTRY", *VARIANT_REGISTRY.keys()]
