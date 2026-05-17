"""Variant 6 — LAYERED DIAMOND.

Centered hero where the diamond IS the visual identity — not a corner
decoration but a structural anchor. One large diamond rendered behind
the heading text (rotated 45°, signal-color, semi-translucent), with
the heading layered on top. The diamond is unmistakably central; the
text reads through and around it.

Additional diamond marks (small) flank the eyebrow as crests, giving
the composition a ceremonial / heraldic feel.

Best for: ceremonial / identity-driven brands, Cathedral at its
purest expression, brands where the diamond motif IS the brand mark.

Visual signature vs other variants:
  vs manifesto_center: V1 = pure text, decorative corner diamonds;
    V6 = ONE giant diamond as visual anchor, text layered with it.
  Both are centered + text-only; differentiation is via diamond
  scale + position (subtle frame vs. focal focal anchor).

Layout sketch:
       ◆     EYEBROW     ◆
              ╔══════╗
        Heading ◇ overlaps
              ╚══════╝
            subtitle line
              [CTA pill]
"""
from __future__ import annotations

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


def render_layered_diamond(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 6 — diamond-as-anchor centered manifesto."""
    content = context.composition.content
    treatments = context.composition.treatments

    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    # The ANCHOR diamond — xlarge (96px), semi-translucent, positioned
    # absolute behind the heading. Text layers above via z-index.
    anchor_diamond = render_diamond_motif(
        "hero.diamond_anchor",
        size="xlarge",
        position_style=(
            "position: absolute; "
            "top: 50%; "
            "left: 50%; "
            "transform: translate(-50%, -50%) rotate(45deg); "
            "z-index: 0;"
        ),
        opacity=0.18,
    )

    # Flanking crest diamonds beside the eyebrow — small, full opacity.
    crest_left = render_diamond_motif(
        "hero.diamond_crest_left",
        size="small",
        position_style="margin: 0 14px;",
    )
    crest_right = render_diamond_motif(
        "hero.diamond_crest_right",
        size="small",
        position_style="margin: 0 14px;",
    )

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-layered-diamond"
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
    position: relative;
    max-width: var(--hero-content-max-width, 1180px);
    margin: 0 auto;
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
  ">
    {anchor_diamond}
    <div style="
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin-bottom: var(--hero-text-rhythm-gap, 24px);
      position: relative;
      z-index: 1;
    ">
      {crest_left}
      {eyebrow_html}
      {crest_right}
    </div>
    <div style="position: relative; z-index: 1;">
      {heading_html}
    </div>
    <div style="position: relative; z-index: 1;">
      {subtitle_html}
    </div>
    <div style="position: relative; z-index: 1;">
      {cta_html}
    </div>
  </div>
{render_satellite_diamonds(treatments.ornament, 'layered_diamond')}
</section>"""
