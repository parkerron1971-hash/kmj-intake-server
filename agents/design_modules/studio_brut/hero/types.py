"""Pass 4.0g Phase B — Pydantic models for Studio Brut Hero compositions.

Parallel to cinematic_authority/hero/types.py but with Studio Brut's
own variant identifiers + IMAGE_USING_VARIANTS membership.

The 8 treatment DIMENSIONS are shared with Cathedral (same Literal
enum values) — Pass 4.0g Phase E (Composer refactor for module
awareness) will lift the dimension types into a shared location so
the Module Router can validate compositions against either module.
For Phase B, Studio Brut declares its own enum values matching
Cathedral's verbatim to keep the modules independently importable.

Studio Brut variant naming convention: snake_case nouns or noun
phrases that describe the COMPOSITION pattern, not the content
slot. Each variant name should be defensible against
STUDIO_BRUT_DESIGN.md."""
from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


# ─── Variant identifiers ────────────────────────────────────────────

# 11 Studio Brut Hero variants invented from the design doc DNA.
# Grouped here by structural personality for documentation; the
# Literal order doesn't affect rendering.
VariantId = Literal[
    # Color-block-architectural (no image, color drives structure)
    "color_block_split",     # asymmetric vertical color stripes 35/45/20
    "stacked_blocks",        # horizontal color bands stacked vertically
    "diagonal_band",         # diagonal authority band cutting the section
    # Type-as-graphic (type IS the visual)
    "oversize_statement",    # massive type filling 80vw, weight contrast
    "type_collage",          # words at dramatically different scales
    "massive_letterform",    # oversized single initial as background ornament
    # Image-led (with Studio Brut treatment, not Cathedral restraint)
    "edge_bleed_portrait",   # asymmetric 70/30, image bleeds to viewport edge
    "layered_card",          # content card overlapping image overlapping bg block
    "double_split",          # two-row asymmetric (image+eyebrow / heading+CTA)
    # Codified / stat-led
    "stat_strip",            # dense stat row across hero base
    "rotated_anchor",        # vertical 90deg rotated code/word as left-edge anchor
]

# Variants that use the hero_main image slot. Phase B locks this set
# at four; the others either replace imagery with color blocks +
# typography (Studio Brut DNA) or use text-only compositions.
IMAGE_USING_VARIANTS: frozenset = frozenset(
    {
        "edge_bleed_portrait",
        "layered_card",
        "double_split",
        # stat_strip is text+numbers only; massive_letterform uses type
        # as the visual; rotated_anchor relies on architectural type;
        # color_block_split / stacked_blocks / diagonal_band / type_collage
        # / oversize_statement are all text-only color-and-type compositions.
    }
)


# ─── Treatment dimensions (shared enums, own translators) ──────────

ColorEmphasis = Literal["signal_dominant", "authority_dominant", "dual_emphasis"]
SpacingDensity = Literal["generous", "standard", "compact"]
EmphasisWeight = Literal["heading_dominant", "balanced", "eyebrow_dominant"]

BackgroundTreatment = Literal["flat", "soft_gradient", "textured", "vignette"]
ColorDepthTreatment = Literal["flat", "gradient_accents", "radial_glows"]
OrnamentTreatment = Literal["minimal", "signature", "heavy"]
TypographyPersonality = Literal["editorial", "bold", "refined", "playful"]
ImageTreatment = Literal["clean", "filtered", "dramatic", "soft"]


class Treatments(BaseModel):
    """Eight orthogonal style dimensions. Same dimension names as
    Cathedral's Treatments model; Studio Brut's translators interpret
    the values through its own DNA (heavier baselines, bolder
    gradients, no diamonds, color-block architecture)."""

    color_emphasis: ColorEmphasis
    spacing_density: SpacingDensity
    emphasis_weight: EmphasisWeight
    background: BackgroundTreatment = "flat"
    color_depth: ColorDepthTreatment = "flat"
    ornament: OrnamentTreatment = "minimal"
    typography: TypographyPersonality = "editorial"
    image_treatment: ImageTreatment = "clean"


# ─── Hero content ───────────────────────────────────────────────────

class HeroContent(BaseModel):
    """Practitioner-facing copy fields. Studio Brut headings tend
    shorter than Cathedral's (4-7 words typical vs 8-12).

    `heading_emphasis` is the word that receives Studio Brut's
    emphasis treatment — NOT italic + signal (that's Cathedral's
    pattern). Studio Brut emphasis uses WEIGHT CONTRAST (heavy word
    among lighter words) or SCALE CONTRAST (oversize word) or COLOR
    CONTRAST (signal-colored word in authority context). The primitive
    decides which mode based on the active typography treatment."""

    eyebrow: str
    heading: str
    heading_emphasis: str = Field(
        description=(
            "Substring of heading that receives Studio Brut's emphasis "
            "treatment (weight contrast / scale contrast / color contrast — "
            "NEVER italic as signature). MUST be an exact substring of heading."
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
            "Slot name (e.g. 'hero_main') for variants that use an image. "
            "Null for text-only and color-block variants."
        ),
    )


# ─── Top-level composition ──────────────────────────────────────────

class StudioBrutHeroComposition(BaseModel):
    """Studio Brut's analogue of CathedralHeroComposition. Module
    Router (Phase D) dispatches between this and the Cathedral
    composition based on the business archetype."""

    section: Literal["hero"] = "hero"
    module: Literal["studio_brut"] = "studio_brut"
    variant: VariantId
    treatments: Treatments
    content: HeroContent
    reasoning: str = Field(
        description=(
            "1-2 sentences explaining variant + treatment selection for this "
            "specific business. Should reference Studio Brut DNA principles "
            "(color-as-architecture, type-as-graphic, asymmetry baseline, "
            "sharp commits, density). Note any variant gap if no perfect "
            "fit existed."
        ),
    )


# ─── Brand kit + render context ─────────────────────────────────────

class BrandKitColors(BaseModel):
    """Same 5-role shape Cathedral uses. Studio Brut interprets these
    colors more aggressively (full color blocks vs accent placement)
    but the contract is identical so the existing brand_kit_renderer
    infrastructure works for both modules."""

    primary: str
    secondary: str
    accent: str
    background: str
    text: str


class RenderContext(BaseModel):
    """Render-time context. Studio Brut variants consume the same
    shape Cathedral does so render_pipeline can be made module-aware
    in Phase E without changing the variant signatures."""

    composition: StudioBrutHeroComposition
    brand_kit: BrandKitColors
    business_id: str
    overrides: Dict[str, str] = Field(default_factory=dict)
    slot_resolutions: Dict[str, str] = Field(default_factory=dict)
