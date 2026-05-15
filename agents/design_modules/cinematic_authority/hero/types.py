"""Pass 4.0f spike — Pydantic models for Cathedral Hero compositions.

The Composer Agent (Phase 3) produces a CathedralHeroComposition; the
render layer (Phase 4) consumes a RenderContext (composition + brand
kit + overrides + slot resolutions) and emits an HTML <section>.

These types are the single source of truth for what variants and
treatments are valid — Composer's JSON output gets validated against
them, and variant renderers consume already-validated objects.
"""
from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


# ─── Variant identifiers ────────────────────────────────────────────

VariantId = Literal[
    "manifesto_center",
    "asymmetric_left",
    "asymmetric_right",
    "full_bleed_overlay",
    "split_stacked",
    "layered_diamond",
]

# Subset of variants that use an image (hero_main slot). Image-using
# variants must have image_slot_ref set; non-image variants must have
# it null. The Composer Agent honors this; the post-validation step in
# Phase 3 enforces it.
IMAGE_USING_VARIANTS: frozenset = frozenset(
    {"asymmetric_left", "asymmetric_right", "full_bleed_overlay", "split_stacked"}
)


# ─── Treatment dimensions ───────────────────────────────────────────

ColorEmphasis = Literal["signal_dominant", "authority_dominant", "dual_emphasis"]
SpacingDensity = Literal["generous", "standard", "compact"]
EmphasisWeight = Literal["heading_dominant", "balanced", "eyebrow_dominant"]


class Treatments(BaseModel):
    """Three orthogonal style dimensions applied to any variant. Each
    dimension has 3 options → 27 treatment combinations per variant.
    Treatment values translate to CSS-variable assignments scoped to
    the rendered section (see treatments/*.py)."""

    color_emphasis: ColorEmphasis
    spacing_density: SpacingDensity
    emphasis_weight: EmphasisWeight


# ─── Hero content ───────────────────────────────────────────────────

class HeroContent(BaseModel):
    """Practitioner-facing copy fields for the Hero section. Composer
    Agent fills these from the enriched brief; the practitioner edits
    them post-render via Edit Mode (Pass 4.0e PART 2).

    `heading_emphasis` must be an exact substring of `heading` — the
    render layer wraps it in an italic signal-colored <em>. When the
    Composer returns a non-substring, the render layer falls back to
    the first 'noun phrase' (whitespace-bounded segment) of heading."""

    eyebrow: str
    heading: str
    heading_emphasis: str = Field(
        description=(
            "Italic-treated word/phrase within heading. MUST be an "
            "exact substring of heading."
        ),
    )
    subtitle: str
    cta_primary: str
    cta_target: str = Field(
        description="Anchor (#...) or mailto: or URL the CTA links to.",
    )
    image_slot_ref: Optional[str] = Field(
        default=None,
        description=(
            "Slot name (e.g. 'hero_main') for variants that use an "
            "image. Null for text-only variants."
        ),
    )


# ─── Top-level composition ──────────────────────────────────────────

class CathedralHeroComposition(BaseModel):
    """The Composer Agent's output — a complete description of a Hero
    section without any pixel-level details. Render layer + brand kit
    + overrides produce the final HTML."""

    section: Literal["hero"] = "hero"
    variant: VariantId
    treatments: Treatments
    content: HeroContent
    reasoning: str = Field(
        description=(
            "1-2 sentences explaining variant + treatment selection "
            "for this specific business. Captured for spike "
            "evaluation; persisted for audit in production."
        ),
    )


# ─── Brand kit + render context ─────────────────────────────────────

class BrandKitColors(BaseModel):
    """The 5 canonical role colors from businesses.settings.brand_kit.
    These map to the --brand-* CSS variables via brand_kit_renderer
    (existing Pass 4.0d PART 3 module). Field names match the nested
    brand_kit shape on businesses.settings.brand_kit.colors."""

    primary: str
    secondary: str
    accent: str
    background: str
    text: str


class RenderContext(BaseModel):
    """Everything the render layer needs to emit a Hero <section>.

    overrides: keyed by target_path (e.g. 'hero.heading') → override
      value (string). Mirrors site_content_overrides row shape.
    slot_resolutions: keyed by slot name (e.g. 'hero_main') → resolved
      URL. Pre-fetched by the caller to avoid the renderer touching
      Supabase directly.
    """

    composition: CathedralHeroComposition
    brand_kit: BrandKitColors
    business_id: str
    overrides: Dict[str, str] = Field(default_factory=dict)
    slot_resolutions: Dict[str, str] = Field(default_factory=dict)
