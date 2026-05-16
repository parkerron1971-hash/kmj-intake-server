"""Variant 8 — TABULAR AUTHORITY.

Two-column 60/40 hero. Content stack LEFT (eyebrow + heading + subtitle
+ CTA). Numerical proof points RIGHT — 3 stat blocks vertically stacked,
each: a monospace numeral (clamp 48-80px) above a small-caps label,
separated by a small diamond marker. Cathedral meets data — restraint
with provable track record.

Best for: consultancy, authority brands with measurable history,
practitioners whose claim is backed by numbers (years experience,
projects shipped, industries served).

SPIKE CAVEAT — stats are placeholder. The 3 stat tuples below are
generic Cathedral-flavored defaults ('12 — YEARS', '84 — ENGAGEMENTS',
'6 — INDUSTRIES'). A full library would add a `stats: List[Stat]`
field to HeroContent so the Composer Agent fills business-specific
numbers. ONE-LINE FIX for production: extend HeroContent with
optional stats; Composer prompt asks for 3 numeric proof points;
this renderer reads them from content.stats instead of hardcoded.

Visual signature vs other variants:
  vs asymmetric_left (V2): V2 has an IMAGE in the right column;
    V8 has STATS. Same grid ratio (60/40), totally different content
    role for the right column. V8 has no image at all.
  vs annotated_hero (V10): V8 emphasizes NUMERICAL proof (track-record
    counts). V10 emphasizes METHODOLOGY steps (numbered process).
    They're cousins but the numbers carry different meaning.
"""
from __future__ import annotations

from html import escape
from typing import Dict, List, Tuple

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


# Spike default stats. Replace with content.stats when full library
# extends HeroContent (see SPIKE CAVEAT in module docstring).
_DEFAULT_STATS: List[Tuple[str, str]] = [
    ("12", "YEARS OF PRACTICE"),
    ("84", "ENGAGEMENTS DELIVERED"),
    ("6", "INDUSTRIES SERVED"),
]


def _render_stat_block(value: str, label: str, index: int) -> str:
    """Render one stat: large monospace numeral over a small-caps label,
    with a small diamond marker between them."""
    safe_value = escape(value)
    safe_label = escape(label)
    diamond = render_diamond_motif(
        f"hero.stat_{index}_marker",
        size="small",
        position_style="margin: 8px 0;",
    )
    return f"""<div class="ca-hero-stat-block" style="
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      padding: 0 0 24px 0;
    ">
      <div
        data-override-target="hero.stat_{index}_value"
        data-override-type="text"
        style="
          font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
          font-size: clamp(2.75rem, 6vw, 4.5rem);
          font-weight: 700;
          line-height: 1;
          color: var(--brand-authority, #0A1628);
          letter-spacing: -0.02em;
        "
      >{safe_value}</div>
      {diamond}
      <div
        data-override-target="hero.stat_{index}_label"
        data-override-type="text"
        style="
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.22em;
          text-transform: uppercase;
          color: var(--brand-text-primary, #0F172A);
          opacity: 0.75;
          font-family: var(--ca-sans, system-ui, -apple-system, sans-serif);
        "
      >{safe_label}</div>
    </div>"""


def render_tabular_authority(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 8 — content left, 3 stat blocks right."""
    content = context.composition.content
    treatments = context.composition.treatments

    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    stats_html = "\n".join(
        _render_stat_block(value, label, i + 1)
        for i, (value, label) in enumerate(_DEFAULT_STATS)
    )

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-tabular-authority"
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
  <div style="
    max-width: var(--hero-content-max-width, 1180px);
    margin: 0 auto;
    display: grid;
    grid-template-columns: 1.5fr 1fr;
    gap: var(--hero-column-gap, 64px);
    align-items: center;
  ">
    <div style="display: flex; flex-direction: column; align-items: flex-start;">
      {eyebrow_html}
      {heading_html}
      {subtitle_html}
      {cta_html}
    </div>
    <div style="
      border-left: 1px solid color-mix(in srgb, var(--brand-text-primary, #0F172A) 12%, transparent);
      padding-left: 32px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    ">
      {stats_html}
    </div>
  </div>
</section>"""
