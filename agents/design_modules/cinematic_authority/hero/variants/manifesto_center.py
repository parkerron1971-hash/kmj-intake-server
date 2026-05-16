"""Variant 1 — MANIFESTO CENTER.

Centered hero, text-only. The text IS the hero. Eyebrow, heading (with
italic emphasis word), subtitle, CTA — all centered, symmetric.
Decorative diamond motifs at the four corners of the section frame
the composition without competing for attention.

Best for: thought leadership, consultancy, authority brands, pastoral
or community-leader brands, anyone whose words carry the weight.

Visual signature vs other variants:
  vs layered_diamond: NO central diamond — V1 is pure text; V6 has a
    prominent diamond as visual focal point.
  vs asymmetric_left/right: V1 is centered + single-column; V2/V3 are
    two-column with image.
  vs full_bleed_overlay: V1 sits on warm-neutral; V4 has image background.
  vs split_stacked: V1 is one cohesive block; V5 is manifesto + columns.
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


def _format_inline_vars(var_dict: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in var_dict.items())


def render_manifesto_center(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 1 — centered text-only manifesto."""
    content = context.composition.content
    treatments = context.composition.treatments

    # Inline section vars: merge brand + treatment dicts. Section-scoped
    # so multiple Heros on the same page don't collide.
    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    # Four small corner diamonds — decorative frame, NOT focal.
    # Positioned absolute within the relatively-positioned section.
    corner_diamonds = "\n".join(
        [
            render_diamond_motif(
                f"hero.diamond_corner_{i}",
                size="small",
                position_style=position,
                opacity=0.55,
            )
            for i, position in enumerate(
                [
                    "position: absolute; top: 32px; left: 32px;",
                    "position: absolute; top: 32px; right: 32px;",
                    "position: absolute; bottom: 32px; left: 32px;",
                    "position: absolute; bottom: 32px; right: 32px;",
                ],
                start=1,
            )
        ]
    )

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-manifesto-center"
  style="{section_style};
    position: relative;
    background: var(--brand-warm-neutral, #F8F6F1);
    padding-top: var(--hero-section-padding-y, 100px);
    padding-bottom: var(--hero-section-padding-y, 100px);
    padding-left: var(--hero-section-padding-x, 64px);
    padding-right: var(--hero-section-padding-x, 64px);
    overflow: hidden;
  "
>
  {corner_diamonds}
  <div style="
    max-width: var(--hero-content-max-width, 1180px);
    margin: 0 auto;
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
</section>"""
