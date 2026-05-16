"""Variant 2 — ASYMMETRIC LEFT.

Two-column hero. Content LEFT (60%), portrait-oriented practitioner
image RIGHT (40%). Image is framed with a thin gold-color (signal)
border, giving it a 'gold-framed glass panel' feel. A diamond motif
overlaps the image's top-left corner, breaking the frame line for
a moment of visual tension.

Best for: service businesses, consultants, practitioner-focused brands
that need to put a human face on the offering. The image is sized to
imply a portrait — headshot, founder photo, hands-at-work.

Visual signature vs other variants:
  vs asymmetric_right: V2 puts CONTENT on the left, image on right
    (40%, portrait). V3 puts IMAGE on the left (50%, landscape),
    bleeding to the section edge. V2 frames the image; V3 lets
    it dominate.
  vs manifesto_center / layered_diamond: V2 has an image; V1/V6
    don't.
  vs split_stacked: V2 is one row, content + image side-by-side;
    V5 stacks the manifesto above a separate image+CTA row.
  vs full_bleed_overlay: V2 frames the image as a contained
    panel; V4 fills the section with image + dark overlay.

Layout sketch (60/40):
  ┌─────────────────────────┬──────────────┐
  │ EYEBROW                 │  ◆           │
  │ Heading with italic     │ ┌──────────┐ │
  │ Subtitle line           │ │  image   │ │
  │ [CTA pill]              │ │  4:5     │ │
  │                         │ └──────────┘ │
  └─────────────────────────┴──────────────┘
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
    render_diamond_motif,
)
from ._depth_helpers import render_satellite_diamonds


def _format_inline_vars(var_dict: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in var_dict.items())


def render_asymmetric_left(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 2 — content left, framed portrait image right."""
    content = context.composition.content
    treatments = context.composition.treatments

    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    # Image src: pulled from context.slot_resolutions if present.
    # Otherwise empty — the existing slot_resolver will substitute at
    # render time when this HTML flows through smart_sites.
    slot_name = content.image_slot_ref or "hero_main"
    image_url = context.slot_resolutions.get(slot_name, "")
    safe_alt = escape(f"{slot_name} — Hero image")

    # Diamond overlapping the image's top-left corner. Position-absolute
    # within the image container.
    corner_diamond = render_diamond_motif(
        "hero.diamond_image_overlap",
        size="medium",
        position_style="position: absolute; top: -12px; left: -12px; z-index: 2;",
    )

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-asymmetric-left"
  style="{section_style};
    position: relative;
    background-color: var(--ca-bg-color, var(--brand-warm-neutral, #F8F6F1));
    background-image: var(--ca-bg-image, none);
    background-size: var(--ca-bg-size, auto);
    background-repeat: var(--ca-bg-repeat, no-repeat);
    background-position: center center;
    background-blend-mode: var(--ca-bg-blend, normal);
    padding-top: var(--hero-section-padding-y, 100px);
    padding-bottom: var(--hero-section-padding-y, 100px);
    padding-left: var(--hero-section-padding-x, 64px);
    padding-right: var(--hero-section-padding-x, 64px);
    overflow: hidden;
  "
>
  <div style="
    max-width: var(--hero-content-max-width, 1180px);
    margin: 0 auto;
    display: grid;
    grid-template-columns: 1.5fr 1fr;
    gap: var(--hero-column-gap, 64px);
    align-items: center;
  ">
    <div style="text-align: left; display: flex; flex-direction: column; align-items: flex-start;">
      {eyebrow_html}
      {heading_html}
      {subtitle_html}
      {cta_html}
    </div>
    <div style="position: relative;">
      {corner_diamond}
      <div style="
        position: relative;
        aspect-ratio: 4 / 5;
        overflow: hidden;
        border: 2px solid var(--brand-signal, #C6952F);
        box-shadow: 0 24px 48px rgba(0, 0, 0, 0.18);
        background: var(--brand-deep-secondary, #122040);
      ">
        <img
          data-slot="{escape(slot_name)}"
          data-override-target="{escape(slot_name)}"
          data-override-type="image"
          src="{escape(image_url)}"
          alt="{safe_alt}"
          style="width: 100%; height: 100%; object-fit: cover; display: block; filter: var(--ca-image-filter, none); -webkit-mask-image: var(--ca-image-mask, none); mask-image: var(--ca-image-mask, none);"
        />
      </div>
    </div>
  </div>
{render_satellite_diamonds(treatments.ornament, 'asymmetric_left')}
</section>"""
