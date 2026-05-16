"""Variant 3 — ASYMMETRIC RIGHT (Image Dominant).

Two-column hero. Image LEFT (50%) bleeds to the section edge (full-
bleed-left, half-section width). Content RIGHT (50%) sits at standard
section padding. Image is landscape-oriented (16:10 ratio) and gets
no frame — the image IS the visual statement, not framed art.

A signal-color accent rule runs vertically along the seam between
image and content (a 3px-wide × ~60% column-height bar), tying the
two columns together as one composition without diluting the image.

Best for: visual portfolio brands — designers, photographers, custom
apparel, anyone whose work IS the brand. The bleed-to-edge image
makes a stronger visual claim than V2's framed portrait.

Visual signature vs other variants:
  vs asymmetric_left: V2 = content left, framed portrait right (40%);
    V3 = bleed-edge landscape left (50%), content right.
    Different image role: V2 frames a portrait; V3 lets work speak.
  vs full_bleed_overlay: V3's image is half the section; V4's image
    is the entire section with overlay.

Layout sketch (50/50, image bleeds left edge):
  ┌─────────────────┐│┌─────────────────────────┐
  │                 │││ EYEBROW                 │
  │     image       │││ Heading with italic     │
  │     (16:10)     │││ Subtitle line           │
  │  bleeds to edge │││             [CTA pill]  │
  └─────────────────┘│└─────────────────────────┘
                     ▲ signal accent rule
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
)


def _format_inline_vars(var_dict: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in var_dict.items())


def render_asymmetric_right(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 3 — bleed-left landscape image, content right."""
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
    safe_alt = escape(f"{slot_name} — Hero image")

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-asymmetric-right"
  style="{section_style};
    position: relative;
    background: var(--brand-warm-neutral, #F8F6F1);
    padding-top: var(--hero-section-padding-y, 100px);
    padding-bottom: var(--hero-section-padding-y, 100px);
    overflow: hidden;
  "
>
  <div style="
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0;
    align-items: center;
    min-height: 480px;
  ">
    <!-- Image bleeds to the left edge of the section (no section padding on left side). -->
    <div style="
      position: relative;
      width: 100%;
      aspect-ratio: 16 / 10;
      background: var(--brand-deep-secondary, #122040);
      overflow: hidden;
    ">
      <img
        data-slot="{escape(slot_name)}"
        data-override-target="{escape(slot_name)}"
        data-override-type="image"
        src="{escape(image_url)}"
        alt="{safe_alt}"
        style="width: 100%; height: 100%; object-fit: cover; display: block;"
      />
      <!-- Vertical accent rule tying image to content column -->
      <div
        class="ca-hero-seam-rule"
        data-override-target="hero.accent_seam"
        data-override-type="color"
        style="
          position: absolute;
          top: 20%;
          right: 0;
          height: 60%;
          width: 3px;
          background: var(--brand-signal, #C6952F);
          transform: translateX(50%);
          z-index: 2;
        "
      ></div>
    </div>
    <!-- Content column with standard padding. -->
    <div style="
      padding-left: var(--hero-column-gap, 64px);
      padding-right: var(--hero-section-padding-x, 64px);
      display: flex;
      flex-direction: column;
      align-items: flex-start;
    ">
      {eyebrow_html}
      {heading_html}
      {subtitle_html}
      {cta_html}
    </div>
  </div>
</section>"""
