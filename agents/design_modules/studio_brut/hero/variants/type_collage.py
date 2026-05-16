"""Variant 6 — TYPE_COLLAGE.

Heading composed of words at dramatically different scales rather
than uniform size. The render uses the existing heading primitive
for the standard heading line, then ALSO renders an oversize-letter
behind/overlapping the heading and a separate scale-shifted word
beneath as a graphic continuation. The result reads as a typographic
collage rather than a single line of headline.

Studio Brut design-doc anchors:
  - "Type as graphic" — multiple scales within one composition
  - "Type compositions as graphic art" — explicitly the variant's
    organizing principle
  - "Layering" — oversize letter sits behind heading; heading sits
    on top; secondary word floats free
  - "Asymmetry" — the letter is off-axis, the secondary word floats
    in a non-grid position

Best for: branding agencies, type foundries, designers whose work IS
typography, lettering studios, anyone whose value proposition is
"we make type matter."
"""
from __future__ import annotations

from typing import Dict

from ..types import RenderContext
from ..primitives import (
    render_eyebrow,
    render_heading,
    render_subtitle,
    render_cta_button,
    render_oversized_letter,
    render_code_label,
)
from ._depth_helpers import SECTION_DEPTH_BG, render_satellite_ornaments


def _format_inline_vars(d: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())


def render_type_collage(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 6 — type-as-graphic collage."""
    content = context.composition.content
    treatments = context.composition.treatments
    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    code_html = render_code_label(
        "MARK / 06",
        "hero.code_label",
        size_px=11,
        position_style="margin-bottom: 28px;",
    )

    # Oversize letterform using the FIRST char of the heading-emphasis
    # word so the collage echoes the brand's voice. Sits behind the
    # heading at low opacity.
    initial = (content.heading_emphasis or content.heading or "S")[0].upper()
    oversize = render_oversized_letter(
        initial,
        "hero.oversize_letter",
        size_vw=44,
        opacity=0.08,
        color_var="var(--brand-authority, #DC2626)",
        rotation_deg=-6,
        position_style=(
            "position: absolute; "
            "top: 50%; left: 50%; "
            "transform: translate(-50%, -50%) rotate(-6deg); "
            "z-index: 0;"
        ),
    )

    # Secondary scale-shifted echo of one word, floating off-axis.
    # Pulled directly from heading_emphasis for semantic resonance.
    echo_word = (content.heading_emphasis or "").upper()
    echo_html = (
        f'<div class="sb-hero-type-echo" '
        f'data-override-target="hero.echo_word" '
        f'data-override-type="text" '
        f'style="font-size: clamp(2.5rem, 7vw, 5rem); '
        f'font-weight: 300; '
        f'letter-spacing: 0.05em; '
        f'text-transform: uppercase; '
        f'color: var(--brand-signal, #FACC15); '
        f'opacity: 0.85; '
        f'font-family: var(--sb-display-stack, "Druk", "Bebas Neue", '
        f'"Space Grotesk", "Archivo Black", "Inter", system-ui, sans-serif); '
        f'line-height: 1; '
        f'margin: 24px 0 32px; '
        f'text-align: right;">'
        f"{echo_word}"
        f"</div>"
    )

    sats = render_satellite_ornaments(treatments.ornament, "type_collage")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-type-collage"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    min-height: 620px;
    padding: var(--sb-section-padding-y, 80px) var(--sb-section-padding-x, 40px);
  "
>
  {oversize}
  <div style="
    position: relative;
    z-index: 2;
    max-width: var(--sb-content-max-width, 1120px);
    margin: 0 auto;
  ">
    {code_html}
    {eyebrow_html}
    {heading_html}
    {echo_html}
    <div style="display: flex; align-items: flex-end; gap: 48px; flex-wrap: wrap;">
      <div style="flex: 1 1 320px;">{subtitle_html}</div>
      <div>{cta_html}</div>
    </div>
  </div>
  {sats}
</section>"""
