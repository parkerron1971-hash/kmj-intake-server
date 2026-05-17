"""The eleven Studio Brut Hero variants. Each is one function consuming
a (RenderContext, brand_vars, treatment_vars) tuple and returning an
HTML <section> string.

Variants invented from STUDIO_BRUT_DESIGN.md DNA — NOT mirrors of
Cathedral. Combinatorial math: 11 variants × 3 color emphases × 3
spacing densities × 3 emphasis weights × 4 backgrounds × 3 color
depths × 3 ornaments × 4 typographies × 4 image treatments =
51,840 unique structural compositions per Studio Brut variant family
(equal to the Cathedral combinatorial space — by design).

Variant cluster by structural personality:

  Color-block-architectural (text-only color compositions):
    color_block_split  (1)  asymmetric 35/45/20 vertical color stripes
    stacked_blocks     (4)  three horizontal color bands stacked
    diagonal_band      (3)  diagonal authority band cutting section

  Type-as-graphic (type IS the visual):
    oversize_statement (2)  massive heading at 80vw + corner square
    type_collage       (6)  multi-scale word composition + echo word
    massive_letterform (9)  single letter at 55vw as architectural mark

  Image-led (with Studio Brut treatment):
    edge_bleed_portrait(5)  asymmetric 70/30, image bleeds left edge
    layered_card       (7)  three z-layers (image / block / card)
    double_split      (10)  two-row asymmetric (image+code / heading+CTA)

  Codified / stat-led:
    stat_strip         (8)  heading top, 3-stat monospace strip bottom
    rotated_anchor    (11)  vertical 90deg code rail + content
"""

from .color_block_split import render_color_block_split
from .oversize_statement import render_oversize_statement
from .diagonal_band import render_diagonal_band
from .stacked_blocks import render_stacked_blocks
from .edge_bleed_portrait import render_edge_bleed_portrait
from .type_collage import render_type_collage
from .layered_card import render_layered_card
from .stat_strip import render_stat_strip
from .massive_letterform import render_massive_letterform
from .double_split import render_double_split
from .rotated_anchor import render_rotated_anchor

VARIANT_REGISTRY = {
    "color_block_split":  render_color_block_split,
    "oversize_statement": render_oversize_statement,
    "diagonal_band":      render_diagonal_band,
    "stacked_blocks":     render_stacked_blocks,
    "edge_bleed_portrait": render_edge_bleed_portrait,
    "type_collage":       render_type_collage,
    "layered_card":       render_layered_card,
    "stat_strip":         render_stat_strip,
    "massive_letterform": render_massive_letterform,
    "double_split":       render_double_split,
    "rotated_anchor":     render_rotated_anchor,
}

__all__ = ["VARIANT_REGISTRY"]
