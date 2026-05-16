"""Variant 3 — DIAGONAL_BAND.

Section split by a diagonal authority-color band running edge to edge
at -8deg (rotated rectangle). Content sits above the band on neutral
bg; signal-colored CTA pokes below the band acting as a visual
anchor. A thick bar at the section's top-left and a code label at
top-right serve as graphic wayfinding.

Studio Brut design-doc anchors:
  - "Color is architecture" — the diagonal band IS the section
    structure, not a decorative overlay
  - "Asymmetry" — diagonal rotation breaks any symmetric reading
  - "Sharp commits" — the band has hard edges, not feathered
  - "Layering" — CTA breaks across the band line on purpose

Best for: ceremonial-but-bold brands, lifestyle businesses with
attitude, brands whose story has a "turning point" the diagonal
implies (cuts, threads, transitions, refresh moments).
"""
from __future__ import annotations

from typing import Dict

from ..types import RenderContext
from ..primitives import (
    render_eyebrow,
    render_heading,
    render_subtitle,
    render_cta_button,
    render_bar,
    render_code_label,
)
from ._depth_helpers import SECTION_DEPTH_BG, render_satellite_ornaments


def _format_inline_vars(d: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())


def render_diagonal_band(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 3 — diagonal authority band."""
    content = context.composition.content
    treatments = context.composition.treatments
    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    top_bar = render_bar(
        "hero.top_bar",
        orientation="horizontal",
        length="120px",
        thickness_px=10,
        color_var="var(--brand-signal, #FACC15)",
        position_style="position: absolute; top: 32px; left: 40px; z-index: 3;",
    )
    code_html = render_code_label(
        "CUT / 03",
        "hero.code_label",
        size_px=11,
        position_style="position: absolute; top: 36px; right: 40px; z-index: 3;",
    )

    sats = render_satellite_ornaments(treatments.ornament, "diagonal_band")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-diagonal-band"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    min-height: 620px;
  "
>
  {top_bar}
  {code_html}
  <!-- Diagonal authority band — rotated rectangle anchored center -->
  <div
    data-override-target="hero.diagonal_band"
    data-override-type="color"
    style="
      position: absolute;
      left: -10%;
      right: -10%;
      top: 60%;
      height: 140px;
      background: var(--brand-authority, #DC2626);
      transform: rotate(-8deg);
      transform-origin: center;
      z-index: 1;
      pointer-events: none;
    "
  ></div>
  <div style="
    position: relative;
    z-index: 2;
    max-width: var(--sb-content-max-width, 1120px);
    margin: 0 auto;
    padding: 100px var(--sb-section-padding-x, 40px) 60px;
    text-align: center;
  ">
    {eyebrow_html}
    {heading_html}
    {subtitle_html}
    <div style="
      display: flex;
      justify-content: center;
      margin-top: 32px;
    ">
      {cta_html}
    </div>
  </div>
  {sats}
</section>"""
