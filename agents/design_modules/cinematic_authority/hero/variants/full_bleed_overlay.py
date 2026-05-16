"""Variant 4 — FULL BLEED OVERLAY.

Hero image fills the entire section as a background. A dark overlay
derived from brand authority + alpha (typically ~60% opacity) sits
between the image and the text, ensuring legibility. Eyebrow,
heading (with italic emphasis), subtitle, and CTA stack centered
over the image.

Diamond motifs render as decorative overlays — translucent, in the
text-on-authority color, scattered as atmospheric marks.

CRITICAL color override: the text in this variant must read as
brand-text-on-authority (typically light on the dark overlay).
Whatever color_emphasis treatment was selected, the variant overrides
--heading-color, --subtitle-color, --eyebrow-color to the on-authority
text color. The CTA's --cta-bg stays signal (high contrast against
dark backdrop is on-brand for the dramatic feel).

Best for: dramatic brands, lifestyle businesses, retreats, premium
experiences, brands with strong photography that can carry the
section visually.

Visual signature vs other variants:
  vs every other variant: V4 is the only one with a full-bleed
    image background AND dark overlay. V2/V3 frame or column-bound
    the image; V5 contains it in a row column. V4 is the most
    cinematic, the most 'film poster.'

Layout sketch:
  ┌══════════════════════════════════════════┐
  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │ ← image
  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
  │ ░░░░░ EYEBROW ░░░░░░░░░░░░░░░░░░░░░░░░░░ │ ← overlay + text
  │ ░░░░░ Heading with italic ░░░░░░░░░░░░░░ │
  │ ░░░░░ subtitle line ░░░░░░░░░░░░░░░░░░░░ │
  │ ░░░░░░░░░░░░░ [CTA pill] ░░░░░░░░░░░░░░░ │
  └══════════════════════════════════════════┘
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


def _format_inline_vars(var_dict: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in var_dict.items())


def render_full_bleed_overlay(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 4 — full-bleed image with dark overlay and text."""
    content = context.composition.content
    treatments = context.composition.treatments

    # Override color treatment vars: text must be readable on the dark
    # overlay regardless of what color_emphasis treatment was selected.
    # Heading + subtitle + eyebrow all go to brand-text-on-authority.
    overlay_overrides = {
        "--heading-color": "var(--brand-text-on-authority, #FFFFFF)",
        "--subtitle-color": "var(--brand-text-on-authority, #FFFFFF)",
        "--eyebrow-color": "var(--brand-signal, #C6952F)",
        # CTA stays high-contrast (signal bg + text-on-signal) for the
        # dramatic feel. Don't override CTA vars.
    }
    merged_vars = {**brand_vars, **treatment_vars, **overlay_overrides}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    slot_name = content.image_slot_ref or "hero_main"
    image_url = context.slot_resolutions.get(slot_name, "")
    safe_alt = escape(f"{slot_name} — Hero image")

    # Atmospheric diamonds — translucent text-on-authority color so they
    # read as ghostly marks over the dark overlay.
    atmosphere_diamonds = "\n".join(
        [
            render_diamond_motif(
                "hero.diamond_atmosphere_1",
                size="medium",
                position_style="position: absolute; top: 14%; left: 8%; z-index: 3;",
                color_var="var(--brand-text-on-authority, #FFFFFF)",
                opacity=0.22,
            ),
            render_diamond_motif(
                "hero.diamond_atmosphere_2",
                size="small",
                position_style="position: absolute; top: 26%; right: 12%; z-index: 3;",
                color_var="var(--brand-signal, #C6952F)",
                opacity=0.55,
            ),
            render_diamond_motif(
                "hero.diamond_atmosphere_3",
                size="large",
                position_style="position: absolute; bottom: 18%; left: 18%; z-index: 3;",
                color_var="var(--brand-text-on-authority, #FFFFFF)",
                opacity=0.10,
            ),
        ]
    )

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-full-bleed-overlay"
  style="{section_style};
    position: relative;
    overflow: hidden;
    min-height: 640px;
    background: var(--brand-authority, #0A1628);
  "
>
  <!-- Full-bleed background image -->
  <img
    data-slot="{escape(slot_name)}"
    data-override-target="{escape(slot_name)}"
    data-override-type="image"
    src="{escape(image_url)}"
    alt="{safe_alt}"
    style="
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      z-index: 1;
    "
  />
  <!-- Dark overlay derived from authority color -->
  <div
    data-override-target="hero.overlay"
    data-override-type="color"
    style="
      position: absolute;
      inset: 0;
      background: var(--brand-authority, #0A1628);
      opacity: 0.62;
      z-index: 2;
    "
  ></div>
  {atmosphere_diamonds}
  <!-- Centered content over overlay -->
  <div style="
    position: relative;
    z-index: 4;
    max-width: var(--hero-content-max-width, 1180px);
    margin: 0 auto;
    padding-top: var(--hero-section-padding-y, 100px);
    padding-bottom: var(--hero-section-padding-y, 100px);
    padding-left: var(--hero-section-padding-x, 64px);
    padding-right: var(--hero-section-padding-x, 64px);
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    min-height: 640px;
    justify-content: center;
  ">
    {eyebrow_html}
    {heading_html}
    {subtitle_html}
    {cta_html}
  </div>
</section>"""
