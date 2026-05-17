"""Variant 11 — ROTATED_ANCHOR.

Vertical 90deg-rotated code/label on the left edge of the section as
architectural element (e.g., "STUDIO BRUT — VOL. 11 — 2026"). Content
fills the remaining width to the right, anchored against the rotated
left rail. A thick signal-color bar runs vertically alongside the
rotated code, acting as visual rail.

Studio Brut design-doc anchors:
  - "Codification as design choice" — rotated code label is exactly
    Section 4's named pattern
  - "Type as ornament" — type as architectural element, not text
  - "Asymmetry" — entire composition leans against the left rail
  - "Density" — single column of content; rail eats minimal width

Best for: editorial brands, magazines, labels, brands whose
"edition" / "volume" / "issue" framing is part of their identity.
Also works for record labels, periodicals, publishing imprints.
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
    render_square_marker,
)
from ._depth_helpers import SECTION_DEPTH_BG, render_satellite_ornaments


def _format_inline_vars(d: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())


def render_rotated_anchor(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 11 — vertical rotated code rail + content."""
    content = context.composition.content
    treatments = context.composition.treatments
    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    rail_bar = render_bar(
        "hero.rail_bar",
        orientation="vertical",
        length="60%",
        thickness_px=10,
        color_var="var(--brand-signal, #FACC15)",
        position_style=(
            "position: absolute; "
            "left: 48px; top: 20%; "
            "z-index: 2;"
        ),
    )
    corner_square = render_square_marker(
        "hero.corner_square",
        size="medium",
        color_var="var(--brand-authority, #DC2626)",
        opacity=1.0,
        position_style=(
            "position: absolute; "
            "right: 40px; top: 40px; "
            "z-index: 3;"
        ),
    )

    # Rotated code rail. Uses inline markup rather than the code_label
    # primitive because the rotation transform is variant-specific.
    rotated_code = (
        f'<div class="sb-hero-rotated-code" '
        f'data-override-target="hero.rotated_code" '
        f'data-override-type="text" '
        f'style="position: absolute; '
        f'left: 24px; top: 80px; '
        f'transform: rotate(-90deg); '
        f'transform-origin: left top; '
        f'font-family: var(--sb-mono-stack, \'JetBrains Mono\', '
        f'\'Space Mono\', monospace); '
        f'font-size: 12px; '
        f'font-weight: 700; '
        f'letter-spacing: 0.28em; '
        f'text-transform: uppercase; '
        f'color: var(--brand-text-primary, #09090B); '
        f'white-space: nowrap; '
        f'z-index: 4;">'
        f"STUDIO BRUT — VOL. 11 — 2026"
        f"</div>"
    )

    sats = render_satellite_ornaments(treatments.ornament, "rotated_anchor")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-rotated-anchor"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    min-height: 640px;
    padding: var(--sb-section-padding-y, 80px) var(--sb-section-padding-x, 40px)
            var(--sb-section-padding-y, 80px) 120px;
  "
>
  {rotated_code}
  {rail_bar}
  {corner_square}
  <div style="
    position: relative;
    z-index: 3;
    max-width: 760px;
  ">
    {eyebrow_html}
    {heading_html}
    {subtitle_html}
    {cta_html}
  </div>
  {sats}
</section>"""
