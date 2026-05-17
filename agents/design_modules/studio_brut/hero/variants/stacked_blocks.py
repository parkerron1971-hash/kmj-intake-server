"""Variant 4 — STACKED_BLOCKS.

Three full-width horizontal color bands stacked vertically:
  Top band — authority paint, eyebrow + code label, modest height
  Middle band — neutral, heading + subtitle, generous height
  Bottom band — signal paint, CTA + circle ornament, modest height

Each band carries hard-edged top + bottom seams. No transitions
between bands.

Studio Brut design-doc anchors:
  - "Vertical color stacks" — exactly the layered architectural
    pattern from Section 5
  - "Color is architecture" — each band defines a stratum
  - "Sharp commits" — band-to-band transitions are abrupt
  - "Density variation" — top + bottom bands are dense; middle
    is generous to let heading breathe

Best for: editorial brands, brands with a strong section identity
needs (eyebrow tagline / hero claim / immediate CTA), brands whose
story has clear strata (label → message → action).
"""
from __future__ import annotations

from typing import Dict

from ..types import RenderContext
from ..primitives import (
    render_eyebrow,
    render_heading,
    render_subtitle,
    render_cta_button,
    render_circle_marker,
    render_code_label,
)
from ._depth_helpers import SECTION_DEPTH_BG, render_satellite_ornaments


def _format_inline_vars(d: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())


def render_stacked_blocks(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 4 — three stacked horizontal color bands."""
    content = context.composition.content
    treatments = context.composition.treatments
    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    code_html = render_code_label(
        "VOL. 04",
        "hero.top_code",
        color_var="var(--brand-text-on-authority, #FFFFFF)",
        size_px=11,
        position_style="margin-left: auto;",
    )
    bottom_circle = render_circle_marker(
        "hero.bottom_circle",
        size="medium",
        color_var="var(--brand-text-on-signal, #09090B)",
        opacity=0.9,
    )

    sats = render_satellite_ornaments(treatments.ornament, "stacked_blocks")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-stacked-blocks"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    min-height: 660px;
  "
>
  <!-- Top band: authority paint with eyebrow + code -->
  <div
    data-override-target="hero.top_band"
    data-override-type="color"
    style="
      background: var(--brand-authority, #DC2626);
      padding: 24px var(--sb-section-padding-x, 40px);
      color: var(--brand-text-on-authority, #FFFFFF);
      display: flex;
      align-items: center;
      gap: 24px;
      --sb-eyebrow-color: var(--brand-text-on-authority, #FFFFFF);
    "
  >
    {eyebrow_html}
    {code_html}
  </div>
  <!-- Middle band: neutral, heading + subtitle, generous -->
  <div style="
    flex: 1 1 auto;
    background: var(--brand-warm-neutral, #F4F4F0);
    padding: 64px var(--sb-section-padding-x, 40px);
    display: flex;
    flex-direction: column;
    justify-content: center;
    max-width: var(--sb-content-max-width, 1120px);
    margin: 0 auto;
    width: 100%;
    box-sizing: border-box;
  ">
    {heading_html}
    {subtitle_html}
  </div>
  <!-- Bottom band: signal paint with CTA + circle ornament -->
  <div
    data-override-target="hero.bottom_band"
    data-override-type="color"
    style="
      background: var(--brand-signal, #FACC15);
      padding: 28px var(--sb-section-padding-x, 40px);
      display: flex;
      align-items: center;
      gap: 32px;
      justify-content: space-between;
    "
  >
    {cta_html}
    {bottom_circle}
  </div>
  {sats}
</section>"""
