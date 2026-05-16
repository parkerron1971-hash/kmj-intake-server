"""Variant 5 — EDGE_BLEED_PORTRAIT (image-using).

Asymmetric 70/30 hero: image bleeds to the LEFT viewport edge at 70%
width, content column occupies the right 30% against a saturated
authority-colored backdrop. Image overlay tint pushes the photo
toward duotone when image_treatment is filtered/dramatic.

Studio Brut design-doc anchors:
  - "Image bleed dramatic, never half-measure" — left bleed commits
    fully to viewport edge
  - "Asymmetry pushed further" — 70/30 split, not 50/50 or 60/40
  - "Layered composition" — content column has its own color backdrop;
    image overlay layer; image; all stacked
  - "Color is architecture" — content column's authority backdrop
    isn't decoration, it's the right-side wall

Best for: visual-portfolio brands (custom apparel, photographers,
designers) whose work IS the brand. The image dominates; the
content column delivers the claim with maximum contrast.
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


def render_edge_bleed_portrait(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 5 — 70/30 image-bleed with content column."""
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

    accent_square = render_square_marker(
        "hero.accent_square",
        size="medium",
        color_var="var(--brand-signal, #FACC15)",
        opacity=1.0,
        position_style=(
            "position: absolute; "
            "left: calc(70% - 24px); top: 32px; "
            "z-index: 4;"
        ),
    )
    code_html = render_code_label(
        "FIELD / 05",
        "hero.code_label",
        color_var="var(--brand-text-on-authority, #FFFFFF)",
        size_px=11,
        position_style="margin-bottom: 24px;",
    )

    sats = render_satellite_ornaments(treatments.ornament, "edge_bleed_portrait")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-edge-bleed-portrait"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    min-height: 640px;
    display: grid;
    grid-template-columns: 70% 30%;
  "
>
  <!-- Image column (70%) — bleeds to left viewport edge -->
  <div style="
    position: relative;
    height: 100%;
    min-height: 640px;
    background: var(--brand-deep-secondary, #18181B);
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
    <!-- Image overlay layer for filtered/dramatic image treatments -->
    <div aria-hidden="true" style="
      position: absolute; inset: 0;
      background: var(--sb-image-overlay, none);
      pointer-events: none;
    "></div>
  </div>
  <!-- Content column (30%) — authority backdrop -->
  <div
    data-override-target="hero.content_block"
    data-override-type="color"
    style="
      background: var(--brand-authority, #DC2626);
      padding: var(--sb-section-padding-y, 80px) var(--sb-section-padding-x, 40px);
      display: flex;
      flex-direction: column;
      justify-content: center;
      color: var(--brand-text-on-authority, #FFFFFF);
      --sb-eyebrow-color: var(--brand-text-on-authority, #FFFFFF);
      --sb-heading-color: var(--brand-text-on-authority, #FFFFFF);
      --sb-subtitle-color: var(--brand-text-on-authority, #FFFFFF);
      position: relative;
      z-index: 2;
    "
  >
    {code_html}
    {eyebrow_html}
    {heading_html}
    {subtitle_html}
    {cta_html}
  </div>
  {accent_square}
  {sats}
</section>"""
