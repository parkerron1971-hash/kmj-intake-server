"""Variant 9 — MASSIVE_LETTERFORM.

Single letterform (first character of the brand name or heading
emphasis word) rendered at 55vw scale as the section's primary
visual element. Content composed around the letterform asymmetrically
— eyebrow + heading + subtitle + CTA stack against the letter's
visual mass. The letter is the ornament; the ornament is the
hero's identity.

Studio Brut design-doc anchors:
  - "Type as ornament" — single letter at near-room-scale is exactly
    Section 4's named pattern
  - "Type as graphic" — letter IS the visual, not content
  - "Asymmetry" — letter offset to one side; content offset to other
  - "Dense" — content stacks tight against the letter's visual mass

Best for: identity-driven brands, brands whose initial IS their
identity (single-character monograms work especially well — KMJ's
"K", RoyalTeez's "R"). Lifestyle brands with a strong brand letter.
"""
from __future__ import annotations

from typing import Dict

from ..types import RenderContext
from ..primitives import (
    render_eyebrow,
    render_heading,
    render_subtitle,
    render_cta_button,
    render_oversized_letter,
    render_code_label,
)
from ._depth_helpers import SECTION_DEPTH_BG, render_satellite_ornaments


def _format_inline_vars(d: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())


def render_massive_letterform(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 9 — massive letterform as architectural ornament."""
    content = context.composition.content
    treatments = context.composition.treatments
    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    code_html = render_code_label(
        "MARK / 09",
        "hero.code_label",
        size_px=11,
        position_style="margin-bottom: 28px;",
    )

    # Pick the letter — first char of heading_emphasis if available,
    # otherwise first char of heading. Variant displays it at much
    # higher opacity than oversized_letter's typical bg-ornament use
    # (here it's MEANT to be readable as a letter, not just texture).
    initial = (content.heading_emphasis or content.heading or "S")[0].upper()
    letter = render_oversized_letter(
        initial,
        "hero.massive_letter",
        size_vw=55,
        opacity=0.85,
        color_var="var(--brand-authority, #DC2626)",
        rotation_deg=0,
        position_style=(
            "position: absolute; "
            "right: -6vw; bottom: -8vw; "
            "z-index: 1;"
        ),
    )

    sats = render_satellite_ornaments(treatments.ornament, "massive_letterform")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-massive-letterform"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    min-height: 680px;
    padding: var(--sb-section-padding-y, 80px) var(--sb-section-padding-x, 40px);
  "
>
  {letter}
  <!-- Content stacks on the left, against the letter's mass on the right -->
  <div style="
    position: relative;
    z-index: 3;
    max-width: 620px;
    margin: 0;
  ">
    {code_html}
    {eyebrow_html}
    {heading_html}
    {subtitle_html}
    {cta_html}
  </div>
  {sats}
</section>"""
