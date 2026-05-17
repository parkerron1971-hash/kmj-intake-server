"""Variant 9 — VERTICAL MANIFESTO.

Tall hero — min-height 100vh. Content stacks vertically with deliberate
breathing room and horizontal diamond-rule separators between each
element: eyebrow → diamond-rule → heading → diamond-rule → subtitle →
diamond-rule → CTA. Each element has its own moment in the vertical
journey.

The diamond-rule is a 48px horizontal line in brand signal color with
a small diamond marker centered ON the line — like a fancy chapter
break in an editorial book.

Best for: contemplative brands, pastoral leadership, ceremonial
businesses, anyone whose hero should slow the reader down rather
than speed them through.

Visual signature vs other variants:
  vs manifesto_center (V1): V1 is standard height with 4 corner
    diamonds. V9 is min-height 100vh with diamond-rule separators
    BETWEEN every element. Different role for the diamond motif:
    V1 = frame, V9 = rhythm punctuation.
  vs layered_diamond (V6): V6 has 1 large anchor diamond behind the
    heading. V9 has 3 horizontal diamond-rule separators between
    elements. Different roles: V6 = focal anchor, V9 = rhythm marks.
  vs every other variant: V9 is the only variant explicitly TALL
    (100vh+). The vertical journey is the design intent.
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


def _render_diamond_rule(target_path: str) -> str:
    """Horizontal rule with a diamond marker centered on it.
    Used as the vertical journey's chapter-break punctuation."""
    diamond = render_diamond_motif(
        target_path,
        size="small",
        position_style="margin: 0;",
        opacity=1.0,
    )
    return f"""<div class="ca-hero-diamond-rule" style="
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 14px;
      margin: 56px 0;
      width: 100%;
    ">
      <div style="
        width: 96px;
        height: 1px;
        background: color-mix(in srgb, var(--brand-signal, #C6952F) 65%, transparent);
      "></div>
      {diamond}
      <div style="
        width: 96px;
        height: 1px;
        background: color-mix(in srgb, var(--brand-signal, #C6952F) 65%, transparent);
      "></div>
    </div>"""


def render_vertical_manifesto(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 9 — tall hero with diamond-rule chapter breaks."""
    content = context.composition.content
    treatments = context.composition.treatments

    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-vertical-manifesto"
  style="{section_style};
    position: relative;
    background-color: var(--ca-bg-color, var(--brand-warm-neutral, #F8F6F1));
    background-image: var(--ca-bg-image, none);
    background-size: var(--ca-bg-size, auto);
    background-repeat: var(--ca-bg-repeat, no-repeat);
    background-position: center center;
    background-blend-mode: var(--ca-bg-blend, normal);
    padding-top: 80px;
    padding-bottom: 80px;
    padding-left: var(--hero-section-padding-x, 64px);
    padding-right: var(--hero-section-padding-x, 64px);
    overflow: hidden;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  "
>
  <div style="
    max-width: 760px;
    width: 100%;
    margin: 0 auto;
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
  ">
    {eyebrow_html}
    {_render_diamond_rule("hero.diamond_rule_1")}
    {heading_html}
    {_render_diamond_rule("hero.diamond_rule_2")}
    {subtitle_html}
    {_render_diamond_rule("hero.diamond_rule_3")}
    {cta_html}
  </div>
{render_satellite_diamonds(treatments.ornament, 'vertical_manifesto')}
</section>"""
