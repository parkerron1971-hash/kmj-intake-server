"""Variant 10 — DOUBLE_SPLIT (image-using).

Two-row asymmetric composition:
  Row 1 (60vh): 80/20 split — image bleeds to right edge (80%),
    small left column with eyebrow + code label + thick vertical bar
  Row 2 (40vh): 30/70 split — small left column with square ornament,
    large right column with heading + subtitle + CTA on neutral bg

The row-to-row width inversions create reading rhythm: row 1 weights
right (image), row 2 weights right (content). The eye travels both
ways across the same vertical axis.

Studio Brut design-doc anchors:
  - "Compound multi-row" composition family
  - "Asymmetric on both axes" — splits are 80/20 + 30/70, not 50/50
  - "Image bleed dramatic" — full right-edge bleed in row 1
  - "Layered composition" — image carries top weight, content carries
    bottom weight

Best for: visual practitioners whose hero needs to introduce both
the work (image) AND the practice (content) without one subordinating
the other. Photographers + writers, designers + strategists, dual-
discipline studios.
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
    render_bar,
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


def render_double_split(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 10 — two-row asymmetric image + content."""
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
        "DOUBLE / 10",
        "hero.code_label",
        size_px=11,
        position_style="margin-bottom: 16px;",
    )
    left_bar = render_bar(
        "hero.left_bar",
        orientation="vertical",
        length="80px",
        thickness_px=10,
        color_var="var(--brand-signal, #FACC15)",
        position_style="margin-top: 20px;",
    )
    row2_square = render_square_marker(
        "hero.row2_square",
        size="large",
        color_var="var(--brand-authority, #DC2626)",
        opacity=1.0,
        position_style="margin: auto;",
    )

    sats = render_satellite_ornaments(treatments.ornament, "double_split")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-double-split"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    min-height: 700px;
    display: flex;
    flex-direction: column;
  "
>
  <!-- Row 1: 80/20 image right -->
  <div style="
    flex: 0 0 60%;
    display: grid;
    grid-template-columns: 20% 80%;
    min-height: 380px;
  ">
    <div style="
      padding: 28px var(--sb-section-padding-x, 40px);
      display: flex;
      flex-direction: column;
    ">
      {code_html}
      {eyebrow_html}
      {left_bar}
    </div>
    <div style="
      position: relative;
      overflow: hidden;
      background: var(--brand-deep-secondary, #18181B);
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
  </div>
  <!-- Row 2: 30/70 content right -->
  <div style="
    flex: 0 0 40%;
    display: grid;
    grid-template-columns: 30% 70%;
    background: var(--brand-warm-neutral, #F4F4F0);
    min-height: 280px;
  ">
    <div
      data-override-target="hero.row2_block"
      data-override-type="color"
      style="
        background: var(--brand-signal, #FACC15);
        display: flex;
        align-items: center;
        justify-content: center;
      "
    >
      {row2_square}
    </div>
    <div style="
      padding: 32px var(--sb-section-padding-x, 40px);
      display: flex;
      flex-direction: column;
      justify-content: center;
    ">
      {heading_html}
      <div style="display: flex; gap: 32px; align-items: flex-end; flex-wrap: wrap;">
        <div style="flex: 1 1 280px;">{subtitle_html}</div>
        <div>{cta_html}</div>
      </div>
    </div>
  </div>
  {sats}
</section>"""
