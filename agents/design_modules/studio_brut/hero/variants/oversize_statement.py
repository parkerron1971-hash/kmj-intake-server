"""Variant 2 — OVERSIZE_STATEMENT.

Massive heading filling 80vw at clamp(5rem, 16vw, 13rem) — type IS
the visual. Heading dominates the frame; eyebrow tucks above-left in
a code label, subtitle and CTA hang in a compact column below.
Single oversize square ornament in the lower-right corner.

Studio Brut design-doc anchors:
  - "Type is graphic material" — headline at near-room-scale
  - "Asymmetry baseline" — content stacks left, square anchors right
  - "Sharp commits" — large square ornament, hard edges
  - "Density" — eyebrow / heading / subtitle / CTA in a tight stack
    despite the headline taking 50%+ of viewport height

Best for: brands whose hero claim should be its first impression — bold
declarative businesses, design studios with edge, makers whose work
demands the largest possible voice.
"""
from __future__ import annotations

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
from ._depth_helpers import SECTION_DEPTH_BG, render_satellite_ornaments


def _format_inline_vars(d: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())


def render_oversize_statement(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 2 — oversized type-as-graphic statement."""
    content = context.composition.content
    treatments = context.composition.treatments
    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    code_html = render_code_label(
        "PROOF / 02",
        "hero.code_label",
        size_px=12,
        position_style="margin-bottom: 24px;",
    )

    corner_square = render_square_marker(
        "hero.corner_square",
        size="xlarge",
        color_var="var(--brand-signal, #FACC15)",
        opacity=1.0,
        position_style=(
            "position: absolute; "
            "right: -40px; bottom: -40px; "
            "z-index: 0;"
        ),
    )

    sats = render_satellite_ornaments(treatments.ornament, "oversize_statement")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-oversize-statement"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    min-height: 640px;
    padding: var(--sb-section-padding-y, 80px) var(--sb-section-padding-x, 40px);
  "
>
  {corner_square}
  <div style="
    position: relative;
    z-index: 2;
    max-width: var(--sb-content-max-width, 1120px);
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    height: 100%;
  ">
    {code_html}
    {eyebrow_html}
    {heading_html}
    <div style="
      display: flex;
      gap: 48px;
      align-items: flex-end;
      flex-wrap: wrap;
      margin-top: 24px;
    ">
      <div style="flex: 1 1 320px;">
        {subtitle_html}
      </div>
      <div>
        {cta_html}
      </div>
    </div>
  </div>
  {sats}
</section>"""
