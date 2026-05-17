"""Variant 11 — CINEMATIC CAPTION.

Two-stack hero. Row 1: full-bleed image (60vh tall, fills section
width edge-to-edge with no padding). Row 2: standard content stack
on warm-neutral background — eyebrow + heading (with italic emphasis)
+ subtitle + CTA, centered, treated as the image's caption.

A thin signal-color rule sits flush against the image's bottom edge,
acting as the seam between visual and text. The relationship is
'establishing shot → caption' — image declares the world, text
introduces what the practitioner does in it.

Best for: visual portfolios that want image dominance WITHOUT overlay
drama, brands needing both image AND fully-legible text, photographers
/ designers / studios who lead with a defining image but want their
words clean and unobstructed.

Visual signature vs other variants:
  vs full_bleed_overlay (V4): V4 puts image + dark overlay + text
    in ONE layered section. V11 separates them: image fills top half,
    text fills bottom half. Both image-led, but V11 keeps text
    unobstructed.
  vs asymmetric_left (V2) / asymmetric_right (V3): V2/V3 are side-
    by-side two-column. V11 is top/bottom two-row. Different axis.
  vs split_stacked (V5): V5 has the MANIFESTO on top and the
    image+CTA-row BELOW. V11 reverses that — IMAGE on top, content
    BELOW. Different priority: V5 puts the words first, V11 puts the
    image first. Same component, different storytelling order.
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


def render_cinematic_caption(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 11 — full-bleed image top, caption content below."""
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

    # Small diamond marker centered on the seam between image and caption,
    # like a film slate. Decorative anchor at the transition.
    seam_diamond = render_diamond_motif(
        "hero.diamond_seam",
        size="medium",
        position_style=(
            "position: absolute; "
            "left: 50%; "
            "top: 100%; "
            "transform: translate(-50%, -50%) rotate(45deg); "
            "z-index: 3;"
        ),
        opacity=1.0,
    )

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-cinematic-caption"
  style="{section_style};
    position: relative;
    background-color: var(--ca-bg-color, var(--brand-warm-neutral, #F8F6F1));
    background-image: var(--ca-bg-image, none);
    background-size: var(--ca-bg-size, auto);
    background-repeat: var(--ca-bg-repeat, no-repeat);
    background-position: center center;
    background-blend-mode: var(--ca-bg-blend, normal);
    overflow: hidden;
  "
>
  <!-- Row 1: full-bleed establishing image (60vh tall) -->
  <div style="
    position: relative;
    width: 100%;
    height: 60vh;
    min-height: 420px;
    background: var(--brand-deep-secondary, #122040);
    overflow: visible;
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
        display: block; filter: var(--ca-image-filter, none); -webkit-mask-image: var(--ca-image-mask, none); mask-image: var(--ca-image-mask, none);"
    />
    <!-- Signal-color seam rule flush against image bottom -->
    <div
      data-override-target="hero.accent_seam"
      data-override-type="color"
      style="
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 4px;
        background: var(--brand-signal, #C6952F);
        z-index: 2;
      "
    ></div>
    {seam_diamond}
  </div>
  <!-- Row 2: caption content below image, on warm-neutral background -->
  <div style="
    max-width: var(--hero-content-max-width, 1180px);
    margin: 0 auto;
    padding-top: 80px;
    padding-bottom: var(--hero-section-padding-y, 100px);
    padding-left: var(--hero-section-padding-x, 64px);
    padding-right: var(--hero-section-padding-x, 64px);
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
  ">
    {eyebrow_html}
    {heading_html}
    {subtitle_html}
    {cta_html}
  </div>
{render_satellite_diamonds(treatments.ornament, 'cinematic_caption')}
</section>"""
