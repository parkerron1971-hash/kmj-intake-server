"""Studio Brut hero primitives — shared rendering fragments.

Different from Cathedral primitives in two important ways:

  1. heading.render_heading does NOT use italic-emphasis-word as
     signature. Studio Brut emphasis is weight contrast / scale
     contrast / color contrast, selected based on the active
     typography treatment.

  2. ornament_marker exposes render_square_marker, render_circle_marker,
     render_bar, render_color_block — NEVER diamonds. The
     STUDIO_BRUT_DESIGN.md anti-pattern list bans diamond ornaments
     across the module.

A separate type_ornament primitive emits oversized-letter and
repeated-word decorative type compositions (Studio Brut's "type as
ornament" principle from Section 4).
"""

from .heading import render_heading
from .eyebrow import render_eyebrow
from .subtitle import render_subtitle
from .cta_button import render_cta_button
from .ornament_marker import (
    render_square_marker,
    render_circle_marker,
    render_bar,
    render_color_block,
)
from .type_ornament import (
    render_oversized_letter,
    render_code_label,
)

__all__ = [
    "render_heading",
    "render_eyebrow",
    "render_subtitle",
    "render_cta_button",
    "render_square_marker",
    "render_circle_marker",
    "render_bar",
    "render_color_block",
    "render_oversized_letter",
    "render_code_label",
]
