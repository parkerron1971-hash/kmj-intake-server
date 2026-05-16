"""Variant 7 — LAYERED_CARD (image-using).

Three z-layers offset asymmetrically:
  z=0 — full-width image fills the section background
  z=1 — an authority-color block offset bottom-right at 55% width
  z=2 — a content card (neutral bg) offset top-left, overlapping
        both the image and the color block

The card has Studio Brut's hard-offset shadow (8-8-0 in
text-primary). Layout reads as a physically stacked composition —
real z-depth as design tool per the design doc.

Studio Brut design-doc anchors:
  - "Layering and stacking" — three z-layers, deliberately offset
  - "Layered card" pattern named directly in Section 5
  - "Asymmetry" — every layer offset in a different direction
  - "Sharp commits" — card has hard corners + hard-offset shadow,
    no soft drop-shadow

Best for: lifestyle brands, makers, product brands whose hero is
about positioning a single piece of work alongside context. Cards
read as "object positioned in environment."
"""
from __future__ import annotations

from html import escape
from typing import Dict

from ..types import RenderContext
from ..primitives import (
    render_eyebrow,
    render_heading,
    render_subtitle,
    render_cta_button,
    render_square_marker,
    render_code_label,
)
from ._depth_helpers import (
    SECTION_DEPTH_BG,
    IMAGE_DEPTH_STYLE,
    render_satellite_ornaments,
)


def _format_inline_vars(d: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())


def render_layered_card(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 7 — three-layer card composition."""
    content = context.composition.content
    treatments = context.composition.treatments
    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    slot_name = content.image_slot_ref or "hero_main"
    image_url = context.slot_resolutions.get(slot_name, "")
    safe_alt = escape(f"{slot_name} hero image")

    code_html = render_code_label(
        "LOT / 07",
        "hero.code_label",
        size_px=11,
        position_style="margin-bottom: 20px;",
    )

    card_square = render_square_marker(
        "hero.card_corner_square",
        size="small",
        color_var="var(--brand-signal, #FACC15)",
        opacity=1.0,
        position_style=(
            "position: absolute; "
            "top: -12px; right: -12px; "
            "z-index: 5;"
        ),
    )

    sats = render_satellite_ornaments(treatments.ornament, "layered_card")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-layered-card"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    min-height: 720px;
  "
>
  <!-- z=0: full-bleed image bg -->
  <div style="
    position: absolute;
    inset: 0;
    z-index: 0;
    overflow: hidden;
  ">
    <img
      data-slot="{escape(slot_name)}"
      data-override-target="{escape(slot_name)}"
      data-override-type="image"
      src="{escape(image_url)}"
      alt="{safe_alt}"
      style="
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
        {IMAGE_DEPTH_STYLE}
      "
    />
    <div aria-hidden="true" style="
      position: absolute; inset: 0;
      background: var(--sb-image-overlay, none);
      pointer-events: none;
    "></div>
  </div>
  <!-- z=1: authority color block offset bottom-right -->
  <div
    data-override-target="hero.layer_block"
    data-override-type="color"
    style="
      position: absolute;
      right: 0;
      bottom: 0;
      width: 55%;
      height: 65%;
      background: var(--brand-authority, #DC2626);
      z-index: 1;
      pointer-events: none;
    "
  ></div>
  <!-- z=2: content card offset top-left -->
  <div style="
    position: relative;
    z-index: 2;
    max-width: 540px;
    margin: 80px 0 80px var(--sb-section-padding-x, 40px);
    padding: 40px;
    background: var(--brand-warm-neutral, #F4F4F0);
    box-shadow: 8px 8px 0 var(--brand-text-primary, #09090B);
  ">
    {card_square}
    {code_html}
    {eyebrow_html}
    {heading_html}
    {subtitle_html}
    {cta_html}
  </div>
  {sats}
</section>"""
