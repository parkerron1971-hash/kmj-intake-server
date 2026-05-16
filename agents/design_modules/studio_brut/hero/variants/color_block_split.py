"""Variant 1 — COLOR_BLOCK_SPLIT.

Three asymmetric vertical color stripes spanning the section: 35%
authority paint (left) / 45% neutral (middle, content lives here) /
20% signal paint (right, ornamented with a code label + circle marker).

Studio Brut design-doc anchors:
  - "Color is architecture, not accent" — entire columns of color
    define the layout's structure
  - "Asymmetry is the baseline" — 35/45/20 split, not 33/33/33
  - "Sharp commits" — hard boundaries between color columns,
    no transitions
  - "Density over breathing room" — middle column packs eyebrow +
    heading + subtitle + CTA + a hard-offset shadow on the CTA

Best for: design studios / agencies that want their hero to look
like a graphic poster from frame one — visual portfolio brands
whose website should feel like a design artifact itself.
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
    render_circle_marker,
    render_code_label,
)
from ._depth_helpers import SECTION_DEPTH_BG, render_satellite_ornaments


def _format_inline_vars(d: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())


def render_color_block_split(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 1 — asymmetric vertical color stripes."""
    content = context.composition.content
    treatments = context.composition.treatments
    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    # Right-column ornament — code label + circle, tightly composed.
    right_code = render_code_label(
        "STUDIO / 01",
        "hero.right_code",
        color_var="var(--brand-text-on-signal, #09090B)",
        size_px=11,
        position_style="margin-bottom: 16px;",
    )
    right_circle = render_circle_marker(
        "hero.right_circle",
        size="large",
        color_var="var(--brand-text-on-signal, #09090B)",
        opacity=0.9,
        position_style="margin-top: auto;",
    )

    sats = render_satellite_ornaments(treatments.ornament, "color_block_split")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-color-block-split"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    min-height: 540px;
    display: grid;
    grid-template-columns: 35% 45% 20%;
  "
>
  <!-- Left: authority paint column, purely architectural -->
  <div
    data-override-target="hero.left_block"
    data-override-type="color"
    style="
      background: var(--brand-authority, #DC2626);
      min-height: inherit;
    "
  ></div>
  <!-- Middle: neutral content column -->
  <div style="
    padding-top: var(--sb-section-padding-y, 80px);
    padding-bottom: var(--sb-section-padding-y, 80px);
    padding-left: var(--sb-section-padding-x, 40px);
    padding-right: var(--sb-section-padding-x, 40px);
    display: flex;
    flex-direction: column;
    justify-content: center;
  ">
    {eyebrow_html}
    {heading_html}
    {subtitle_html}
    {cta_html}
  </div>
  <!-- Right: signal paint column with code + circle ornaments -->
  <div
    data-override-target="hero.right_block"
    data-override-type="color"
    style="
      background: var(--brand-signal, #FACC15);
      min-height: inherit;
      padding: 32px 24px;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
    "
  >
    {right_code}
    {right_circle}
  </div>
  {sats}
</section>"""
