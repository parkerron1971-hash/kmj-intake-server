"""Variant 10 — ANNOTATED HERO.

Two-column 1fr 1.4fr (40/60) layout. LEFT: annotation block — 3
numbered marginalia entries treating the hero's claim like an
academic / editorial structure ('01 — Premise', '02 — Practice',
'03 — Result'). Each annotation: monospace number, em-dash,
small-caps phrase, brief one-line description below. RIGHT: standard
content stack (eyebrow + heading + subtitle + CTA).

A thin vertical signal-color rule between the two columns ties them
as one composition.

Best for: process-driven businesses, methodology-focused practitioners,
brands whose claim is the SHAPE of their work as much as the work
itself (consultants who lead with method, coaches who teach a system,
craftspeople who explain their process).

SPIKE CAVEAT — annotation phrases are generic Cathedral defaults
('PREMISE', 'PRACTICE', 'RESULT'). Production fix: add
`annotations: Optional[List[Tuple[str, str]]]` to HeroContent so
Composer fills business-specific method steps. Same shape as
V8's stats SPIKE CAVEAT.

Visual signature vs other variants:
  vs asymmetric_left (V2) / asymmetric_right (V3): both have IMAGES;
    V10 has TEXT ANNOTATIONS in one column. No image at all.
  vs tabular_authority (V8): V8 has NUMERICAL stats; V10 has METHOD
    steps. V8 = data backing; V10 = methodology shape. Cousins but
    different intent (track record vs how-we-work).
  vs every other variant: V10 is the only variant whose left column
    is itself a structured text block. Editorial-academic feel.
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
)


def _format_inline_vars(var_dict: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in var_dict.items())


# Spike default annotations. Production: replace with content.annotations.
_DEFAULT_ANNOTATIONS: List[Tuple[str, str, str]] = [
    (
        "01",
        "PREMISE",
        "The opening question that frames the work.",
    ),
    (
        "02",
        "PRACTICE",
        "The deliberate process applied with care.",
    ),
    (
        "03",
        "RESULT",
        "The outcome that compounds over time.",
    ),
]


def _render_annotation(number: str, label: str, description: str, index: int) -> str:
    """Render one numbered marginalia entry."""
    safe_number = escape(number)
    safe_label = escape(label)
    safe_desc = escape(description)
    return f"""<div class="ca-hero-annotation" style="
      padding: 16px 0;
      border-bottom: 1px solid color-mix(in srgb, var(--brand-text-primary, #0F172A) 10%, transparent);
    ">
      <div style="
        display: flex;
        align-items: baseline;
        gap: 14px;
        margin-bottom: 6px;
      ">
        <span
          data-override-target="hero.annotation_{index}_number"
          data-override-type="text"
          style="
            font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
            font-size: 13px;
            font-weight: 700;
            color: var(--brand-signal, #C6952F);
            letter-spacing: 0.06em;
          "
        >{safe_number}</span>
        <span style="
          color: color-mix(in srgb, var(--brand-text-primary, #0F172A) 32%, transparent);
          font-size: 13px;
        ">—</span>
        <span
          data-override-target="hero.annotation_{index}_label"
          data-override-type="text"
          style="
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.22em;
            text-transform: uppercase;
            color: var(--brand-authority, #0A1628);
            font-family: var(--ca-sans, system-ui, -apple-system, sans-serif);
          "
        >{safe_label}</span>
      </div>
      <div
        data-override-target="hero.annotation_{index}_description"
        data-override-type="text"
        style="
          padding-left: 38px;
          font-size: 14px;
          line-height: 1.55;
          color: var(--brand-text-primary, #0F172A);
          opacity: 0.78;
          font-family: var(--ca-sans, system-ui, -apple-system, sans-serif);
        "
      >{safe_desc}</div>
    </div>"""


def render_annotated_hero(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 10 — annotations left, content right."""
    content = context.composition.content
    treatments = context.composition.treatments

    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    annotations_html = "\n".join(
        _render_annotation(num, label, desc, i + 1)
        for i, (num, label, desc) in enumerate(_DEFAULT_ANNOTATIONS)
    )

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-annotated-hero"
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
    grid-template-columns: 1fr 1.4fr;
    gap: var(--hero-column-gap, 64px);
    align-items: center;
  ">
    <div style="
      padding-right: 32px;
      border-right: 1px solid color-mix(in srgb, var(--brand-signal, #C6952F) 35%, transparent);
    ">
      <div
        data-override-target="hero.annotation_header"
        data-override-type="text"
        style="
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.28em;
          text-transform: uppercase;
          color: var(--brand-signal, #C6952F);
          margin-bottom: 24px;
          font-family: var(--ca-sans, system-ui, -apple-system, sans-serif);
        "
      >THE METHOD</div>
      {annotations_html}
    </div>
    <div style="display: flex; flex-direction: column; align-items: flex-start;">
      {eyebrow_html}
      {heading_html}
      {subtitle_html}
      {cta_html}
    </div>
  </div>
</section>"""
