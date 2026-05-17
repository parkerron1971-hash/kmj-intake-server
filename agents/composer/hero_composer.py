"""Pass 4.0g Phase E — Generalized Hero Composer Agent (multi-module).

Module-aware Sonnet 4.5 composer. Same logic shape across modules; the
system prompt + the composition Pydantic type + the IMAGE_USING_VARIANTS
set + the safe-fallback variant are looked up via a per-module
ModuleSpec table.

Replaces (logically) cathedral_hero_composer.py. The old file remains
as a thin backward-compat shim so spike scripts that import
`compose_cathedral_hero` continue to work.

Public surface:
  MODULES                 dict of registered ModuleSpecs
  compose_hero(business_id, module_id='cathedral')
    Main entry. Returns dict matching the module's composition shape
    + extra _composer_metadata envelope for diagnostics.
  fetch_business_context(business_id)
    Re-exported from this module (was on cathedral_hero_composer.py).
  _strip_code_fence(text)
    Re-exported helper used by module_router.py.

Internal:
  ModuleSpec               dataclass — per-module specifications
  _safe_fallback(spec, business_id, reason, raw=None)
  _enforce_image_slot_consistency(comp_dict, spec)
  _missing_depth_fields(comp_dict)
  _enforce_depth_treatments(comp_dict)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Type

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

# Cathedral module surfaces
from agents.design_modules.cinematic_authority.hero.types import (
    CathedralHeroComposition,
    IMAGE_USING_VARIANTS as CATHEDRAL_IMAGE_USING_VARIANTS,
)
# Studio Brut module surfaces
from agents.design_modules.studio_brut.hero.types import (
    StudioBrutHeroComposition,
    IMAGE_USING_VARIANTS as STUDIO_BRUT_IMAGE_USING_VARIANTS,
)

logger = logging.getLogger(__name__)

COMPOSER_MODEL = "claude-sonnet-4-5-20250929"
COMPOSER_MAX_TOKENS = 1500
COMPOSER_TEMPERATURE = 0.4  # creative work — higher than router's 0.3


# ─── Cathedral system prompt ───────────────────────────────────────
# Lifted verbatim from cathedral_hero_composer.py at Phase 2.6 with no
# semantic changes — the prompt was already convergence-verified across
# 9 routings (3 businesses x 3 runs). Phase E only generalizes the
# surrounding code, not the prompt content itself.

CATHEDRAL_SYSTEM_PROMPT = """You are a creative director composing the Hero section of a website using the Cathedral component library. Cathedral is the Cinematic Authority module — restrained editorial typography, signal-color italic emphasis on key words, generous whitespace, a diamond motif throughout, and a sense of authority rather than enthusiasm.

You have 11 Hero VARIANTS to pick from. Each variant has a structural personality + a "best for" guidance. Pick the one that best fits THIS business's archetype, brand metaphor, and tone.

═══════════════════════════════════════════════════════════════
THE 11 VARIANTS
═══════════════════════════════════════════════════════════════

1. MANIFESTO_CENTER — Centered text-only manifesto. 4 small corner diamonds frame the section. No image.
   Best for: thought leadership, consultancy, authority brands, pastoral / community-leader brands. The text IS the hero.

2. ASYMMETRIC_LEFT — Two-column 60/40. Content left, framed portrait image (4:5) right. Diamond overlaps image's top-left corner.
   Best for: service businesses, consultants, practitioner-focused brands needing a human face. Image implies headshot / founder photo.

3. ASYMMETRIC_RIGHT — Two-column 50/50. Landscape image (16:10) left, BLEEDING to section edge. Content right. Vertical signal-color rule at column seam.
   Best for: visual-portfolio brands — designers, photographers, custom apparel, anyone whose work IS the brand.

4. FULL_BLEED_OVERLAY — Image fills entire section. Dark overlay (brand-authority @ 60% opacity). Text centered over it. Atmospheric diamonds scattered.
   Best for: dramatic brands, lifestyle businesses, retreats, premium experiences with strong photography.

5. SPLIT_STACKED — Two-row compound. Manifesto top (eyebrow + heading + subtitle, no CTA). 50/50 image+content row below with CTA + 3 value props.
   Best for: service businesses with immediate functional needs (hours, location, value props on the fold).

6. LAYERED_DIAMOND — Centered text with prominent xlarge diamond as visual anchor BEHIND the heading. Crest diamonds flank the eyebrow.
   Best for: ceremonial brands, identity-driven brands, Cathedral aesthetic at its purest expression. The diamond IS the brand mark.

7. QUOTE_ANCHOR — Pull quote as heading + attribution as subtitle. Oversized italic-serif quote marks ornament. NO diamond motif at all.
   Best for: businesses where social proof is the opening move — high-end consultants, established practitioners. Quote-led, not declaration-led.

8. TABULAR_AUTHORITY — Two-column 60/40. Content left, 3 numerical stat blocks right (monospace numerals + small-caps labels + diamond markers).
   Best for: consultancy, authority brands with provable track record, businesses whose claim is backed by NUMBERS.

9. VERTICAL_MANIFESTO — Tall hero (min-height 100vh). Content stacks vertically with horizontal diamond-rule chapter breaks BETWEEN every element.
   Best for: contemplative brands, pastoral leadership, ceremonial businesses that should slow the reader down rather than rush them through.

10. ANNOTATED_HERO — Two-column 40/60. Annotation block left (3 numbered method steps), content right. Editorial-academic feel.
    Best for: process-driven businesses, methodology-focused practitioners. The brand's claim is the SHAPE of their work as much as the work itself.

11. CINEMATIC_CAPTION — Two-row. Full-bleed image top (60vh), caption content (eyebrow + heading + subtitle + CTA) below. Image and text stay separate.
    Best for: visual portfolios needing image dominance AND fully-legible text. Photographers, designers, studios with strong establishing shots who want NO overlay drama.

═══════════════════════════════════════════════════════════════
THE 8 TREATMENT DIMENSIONS
═══════════════════════════════════════════════════════════════

Each variant accepts EIGHT independent treatment dimensions. The first
three control structural rhythm; the last five control how the variant
FEELS (visual depth).

─── Structural (3 dimensions) ───

COLOR_EMPHASIS:
  signal_dominant   — italic emphasis word + eyebrow + CTA all in signal color (gold/amber/accent). Heading uses text primary.
  authority_dominant — heading uses brand authority (deep brand color). Signal restricted to italic emphasis only.
  dual_emphasis     — both authority + signal carry weight. Heading authority color, italic + eyebrow + CTA signal color.

SPACING_DENSITY:
  generous  — maximum breathing room. Section padding clamp(80-160px). Most contemplative.
  standard  — default density (clamp 60-100px section padding).
  compact   — tighter (clamp 40-60px section padding). For functional, no-nonsense businesses.

EMPHASIS_WEIGHT:
  heading_dominant  — heading is the visual anchor. Display scale clamp(3-6rem).
  balanced          — heading and subtitle roughly equal. Heading clamp(2.5-4rem).
  eyebrow_dominant  — eyebrow visually prominent. Heading slightly smaller.

─── Visual depth (5 dimensions) ───

BACKGROUND:
  flat           — solid bg, no variation. Editorial restraint.
  soft_gradient  — gentle 135-deg gradient through 9% signal tint to 6% authority tint. Premium / lifestyle.
  textured       — solid bg + tiled SVG noise via multiply blend. Tactile, crafted feel.
  vignette       — radial darken with 18% authority tint at edges. Cinematic focus toward content.

COLOR_DEPTH:
  flat              — solid colors throughout. Classic Cathedral.
  gradient_accents  — italic emphasis word uses LINEAR-GRADIENT text fill. CTA bg becomes a 2-stop gradient.
  radial_glows      — italic emphasis word gains text-shadow halo. CTA gains radial signal glow. Diamonds glow.

ORNAMENT:
  minimal    — diamond opacity 0.55x, size 0.8x. Restrained editorial.
  signature  — diamond opacity 0.9x, size 1.0x. The Cathedral classic.
  heavy      — diamond opacity 1.0x, size 1.4x + 4 scattered satellite diamonds. Bold, decorated.

TYPOGRAPHY:
  editorial — Playfair Display, weight 900, tight tracking. Cathedral default.
  bold      — Playfair, tighter line-height + tracking. Confident, declarative.
  refined   — lighter weight, looser line-height, looser tracking. Poetic, elegant.
  playful   — italic-leaning, weight 600, looser tracking. Creative, lively.

IMAGE_TREATMENT (only meaningful for IMAGE-USING variants — asymmetric_left/right, full_bleed_overlay, split_stacked, cinematic_caption):
  clean    — no filter. Photo as-shot.
  filtered — saturate(0.88), contrast(0.96). Magazine feel.
  dramatic — saturate(1.15), contrast(1.18), brightness(0.96). Cinematic.
  soft     — feathered edges via mask-image. Premium experience feel.

  For text-only variants, set image_treatment to 'clean' — no-op but schema requires it.

═══════════════════════════════════════════════════════════════
HOW TO PICK DEPTH TREATMENTS
═══════════════════════════════════════════════════════════════

Depth treatments are how you tell different businesses APART VISUALLY beyond layout. Lean into business personality. Don't default to flat/flat/minimal/editorial/clean unless the brand specifically demands restraint.

Business-archetype guidance:

  creative agency / studio
    → vignette or soft_gradient background
    → gradient_accents color_depth
    → signature ornament
    → bold or editorial typography
    → dramatic or filtered image

  technical consultancy / process-driven
    → flat or textured background
    → flat or gradient_accents color_depth
    → minimal or signature ornament
    → editorial or refined typography
    → clean image

  pastoral / community / ceremonial brand
    → soft_gradient background
    → radial_glows or gradient_accents color_depth
    → signature ornament
    → refined typography
    → soft image treatment

  authority expert / consultant / professional
    → flat or vignette background
    → flat color_depth
    → signature ornament
    → editorial or bold typography
    → filtered or dramatic image

═══════════════════════════════════════════════════════════════
HOW TO PICK VARIANT
═══════════════════════════════════════════════════════════════

Read the business's archetype, brand metaphor, vibe, and tone. Match the variant to the brand's PERSONALITY (not just the words used).

Examples of variant-archetype fit:

  visual_portfolio  → asymmetric_right, cinematic_caption, full_bleed_overlay
  service_consultant → asymmetric_left, tabular_authority, annotated_hero
  community_leader   → manifesto_center, vertical_manifesto, layered_diamond
  authority_expert   → manifesto_center, quote_anchor, tabular_authority
  product_seller     → asymmetric_right, cinematic_caption, split_stacked

═══════════════════════════════════════════════════════════════
WRITING THE CONTENT
═══════════════════════════════════════════════════════════════

eyebrow:           short uppercase label (3-6 words). Reflects brand metaphor. Avoid generic openers.
heading:           SHORT, DECLARATIVE, contains ONE italic-treated emphasis word. 4-9 words for declarative variants, longer (up to 18) for QUOTE_ANCHOR.
heading_emphasis:  EXACT substring of heading that gets italic + signal-color treatment.
subtitle:          single completing sentence. For QUOTE_ANCHOR, the attribution.
cta_primary:       SHORT verb-led button label specific to this practice ('Reserve a seat', 'Begin a design'). NEVER 'Get Started', 'Learn More'.
cta_target:        anchor (#contact / #book) or mailto: or URL.
image_slot_ref:    'hero_main' if variant uses an image (variants 2, 3, 4, 5, 11), null otherwise.

═══════════════════════════════════════════════════════════════
GAP REASONING
═══════════════════════════════════════════════════════════════

If NO variant perfectly fits, pick the CLOSEST match and explicitly note the gap. Be honest — gap data tells the next library expansion which variants to build first.

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════

Output ONE JSON object. No markdown fences. The schema:

{
  \"variant\": \"<one of the 11 variant ids>\",
  \"treatments\": {
    \"color_emphasis\": \"<signal_dominant | authority_dominant | dual_emphasis>\",
    \"spacing_density\": \"<generous | standard | compact>\",
    \"emphasis_weight\": \"<heading_dominant | balanced | eyebrow_dominant>\",
    \"background\": \"<flat | soft_gradient | textured | vignette>\",
    \"color_depth\": \"<flat | gradient_accents | radial_glows>\",
    \"ornament\": \"<minimal | signature | heavy>\",
    \"typography\": \"<editorial | bold | refined | playful>\",
    \"image_treatment\": \"<clean | filtered | dramatic | soft>\"
  },
  \"content\": {
    \"eyebrow\": \"<3-6 word uppercase label>\",
    \"heading\": \"<short declarative heading containing the emphasis substring>\",
    \"heading_emphasis\": \"<exact substring of heading, italic+signal>\",
    \"subtitle\": \"<single completing sentence, OR attribution for quote_anchor>\",
    \"cta_primary\": \"<short verb-led button label specific to this practice>\",
    \"cta_target\": \"<#anchor or mailto: or URL>\",
    \"image_slot_ref\": \"hero_main\" OR null
  },
  \"reasoning\": \"<2-3 sentences. Why this variant + treatments for this business. Reference DEPTH choices, not just structural. Note variant gap if no perfect fit.>\"
}

All 8 treatment fields are REQUIRED. Output ONLY the JSON object."""


# ─── Studio Brut system prompt ─────────────────────────────────────

STUDIO_BRUT_SYSTEM_PROMPT = """You are a creative director composing the Hero section of a website using the Studio Brut component library. Studio Brut is the bold-urban-graphic-expressive module — heavy display typography, color blocks as architecture (not accent), asymmetric layouts, sharp commits, density over breathing room. Studio Brut serves brands whose identity is visible character — custom apparel, streetwear, design studios with edge, urban photographers, independent makers, music/culture brands.

Studio Brut has NO italic-emphasis-word pattern (that's the Cathedral signature you are NOT building here). Heading emphasis comes from WEIGHT contrast, SCALE contrast, or COLOR contrast based on the typography treatment. Studio Brut has NO diamond motif — ornament vocabulary is squares, circles, bars, color blocks, and oversized type / codes / numbers as decorative material.

You have 11 Hero VARIANTS to pick from. Each variant has a structural personality + a "best for" guidance. Pick the one that best fits THIS business's archetype, brand metaphor, and tone.

═══════════════════════════════════════════════════════════════
THE 11 VARIANTS
═══════════════════════════════════════════════════════════════

1. COLOR_BLOCK_SPLIT — Three asymmetric vertical color stripes (35% authority / 45% neutral with content / 20% signal). Code label + circle ornament on right.
   Best for: design studios / branding agencies that want their hero to look like a graphic poster from frame one. The architecture IS the brand.

2. OVERSIZE_STATEMENT — Massive heading filling 80vw at clamp(5rem, 16vw, 13rem). Single oversize square in the lower-right corner.
   Best for: brands whose hero claim should be its FIRST IMPRESSION. Bold declarative businesses, makers with confident short claims ('Wear your crown', 'Cut the noise').

3. DIAGONAL_BAND — Section split by a -8deg rotated authority-color band running edge to edge. Content above. Thick signal bar top-left + code label top-right.
   Best for: ceremonial-but-bold brands, lifestyle businesses with attitude, brands whose story has a 'turning point' the diagonal implies (cuts, threads, transitions).

4. STACKED_BLOCKS — Three full-width horizontal color bands stacked vertically: authority paint top (eyebrow + code), neutral middle (heading + subtitle), signal paint bottom (CTA + circle).
   Best for: editorial brands, brands with strong section identity needs (eyebrow tagline / hero claim / immediate CTA). Brands whose story has clear strata.

5. EDGE_BLEED_PORTRAIT — Asymmetric 70/30: image bleeds to LEFT viewport edge at 70% width, content column on right against authority-colored backdrop.
   Best for: visual-portfolio brands (custom apparel, photographers, designers) whose work IS the brand. Image dominates; content commits to color.

6. TYPE_COLLAGE — Heading composed of words at multiple scales + oversized letterform behind heading at 44vw + scale-shifted echo word.
   Best for: branding agencies, type foundries, lettering studios — anyone whose value proposition is 'we make type matter'. Brands where typographic personality IS the value.

7. LAYERED_CARD — Three z-layers: full-bleed image background / authority-color block offset bottom-right at 55% / content card offset top-left with 8-8-0 hard-offset shadow.
   Best for: lifestyle brands, makers, product brands whose hero positions a single piece of work alongside context. Cards read as 'object positioned in environment'.

8. STAT_STRIP — Tall hero with heading + subtitle top, dense 3-stat monospace strip on authority paint at bottom. Each stat: massive monospace numeral + small-caps label.
   Best for: agencies, consultancies, creative shops with PROVABLE WORK COUNTS (clients, projects, years, sold-out runs).

9. MASSIVE_LETTERFORM — Single 55vw letterform (first char of heading emphasis word) as architectural mark in the section. Content composed around its mass.
   Best for: identity-driven brands, brands whose initial IS their identity (single-character monograms — KMJ's 'K', RoyalTee's 'R'). Lifestyle brands with a strong brand letter.

10. DOUBLE_SPLIT — Two-row asymmetric: row 1 is 80/20 (image bleeds right, code+bar on left), row 2 is 30/70 (square on left, heading+CTA on right).
    Best for: dual-discipline practitioners (photographers + writers, designers + strategists). Hero introduces work AND practice without one subordinating the other.

11. ROTATED_ANCHOR — Vertical 90deg-rotated code rail on left edge (STUDIO BRUT — VOL. 11 — 2026 style) + thick signal-color vertical bar + content fills remaining width.
    Best for: editorial brands, magazines, labels, brands whose 'edition' / 'volume' / 'issue' framing is part of their identity. Publishing imprints, music labels.

═══════════════════════════════════════════════════════════════
THE 8 TREATMENT DIMENSIONS
═══════════════════════════════════════════════════════════════

Same 8-dimension framework Cathedral uses, but Studio Brut interprets values through its OWN DNA. Studio Brut's 'bold' is heavier; Studio Brut's 'soft_gradient' is bolder; Studio Brut's ornament vocabulary is geometric, not heraldic.

─── Structural (3 dimensions) ───

COLOR_EMPHASIS:
  signal_dominant   — heading_emphasis + eyebrow + CTA in signal color. Heading in text-primary.
  authority_dominant — heading in brand authority. heading_emphasis can use signal OR text-primary depending on typography mode. CTA in authority.
  dual_emphasis     — both authority + signal carry weight. Heading authority, eyebrow signal, CTA authority. Color-on-color compositions enabled.

SPACING_DENSITY:
  generous  — denser than Cathedral generous. Section padding clamp(60-140px).
  standard  — denser than Cathedral standard. clamp(40-90px).
  compact   — denser than Cathedral compact. clamp(28-48px). Studio Brut packs aggressively.

EMPHASIS_WEIGHT:
  heading_dominant  — heading is the visual anchor. Display scale clamp(3.5-11rem) — near-poster scale.
  balanced          — heading and subtitle roughly equal. Heading clamp(2.75-6rem).
  eyebrow_dominant  — eyebrow visually prominent. Heading slightly smaller (clamp 2.25-4.5rem).

─── Visual depth (5 dimensions) ───

BACKGROUND:
  flat           — solid bg, no variation. Studio Brut at its quietest.
  soft_gradient  — Studio Brut 'soft' is STILL BOLD. Full-saturation 135deg gradient from authority through to signal. No tint mixing. Reads from 20 feet away. (Cathedral's 'soft_gradient' is subtle; Studio Brut's is poster-grade.)
  textured       — halftone-dot screen-print SVG (24px tile, multiply blend). Graphic, not editorial. Risograph / screen-print aesthetic.
  vignette       — radial darken from center with 35% authority tint at edges. Dramatic cinematic poster contrast.

COLOR_DEPTH:
  flat              — solid colors. CTA carries hard-offset 4-4-0 shadow in text-primary (brutalist-web aesthetic, NOT soft drop-shadow).
  gradient_accents  — heading emphasis word uses LINEAR-GRADIENT text fill (signal-to-authority). CTA bg becomes authority-to-signal gradient. CTA keeps hard-offset 5-5-0 shadow.
  radial_glows      — heading emphasis word gains saturated text-shadow halo. CTA gets radial signal-color glow (replaces offset shadow). Ornaments get drop-shadow halo.

ORNAMENT:
  minimal    — ornament opacity 0.7x, size 0.85x. Restrained for editorial / authority lean.
  signature  — opacity 0.95x, size 1.0x. Default Studio Brut energy.
  heavy      — opacity 1.0x, size 1.55x + 6 scattered satellite ornaments (squares + circles + small color blocks). Bold, decorated. Ornament becomes visual co-star.

TYPOGRAPHY:
  editorial — Druk / Bebas Neue / Space Grotesk weight 800, line-height 0.95, tracking -0.02em. Studio Brut at its quietest typography. Heading emphasis = COLOR contrast (signal-colored word inside text-primary heading).
  bold      — weight 900, line-height 0.9, tracking -0.04em, UPPERCASE. Heading emphasis = WEIGHT contrast (heavier word among heavy neighbors). Confident, declarative.
  refined   — weight 600 (lighter), line-height 1.0, tracking 0em. Heading emphasis = SCALE contrast (1.4em-larger oversized word). Poetic.
  playful   — weight 700, eyebrow + subtitle + CTA carry italic, heading itself upright. Heading emphasis = SCALE + COLOR combined (1.45em larger AND signal-colored). Most graphic.

IMAGE_TREATMENT (only meaningful for IMAGE-USING variants — edge_bleed_portrait, layered_card, double_split):
  clean    — no filter. Photo as-shot.
  filtered — saturate(0.85), contrast(1.05) + 12% signal-color overlay. Editorial fashion grade duotone.
  dramatic — saturate(1.2), contrast(1.25), brightness(0.92) + 22% authority-color overlay. Cinematic / streetwear poster duotone.
  soft     — saturate(1.0), contrast(1.0) + radial mask feathering edges. Crisp center, dreamlike edges.

  For text-only variants (color_block_split, oversize_statement, diagonal_band, stacked_blocks, type_collage, stat_strip, massive_letterform, rotated_anchor), set image_treatment to 'clean' — no-op but schema requires it.

═══════════════════════════════════════════════════════════════
HOW TO PICK DEPTH TREATMENTS
═══════════════════════════════════════════════════════════════

Studio Brut LEANS LOUD. The default if no specific brand reason exists is the depth tier that commits — soft_gradient or textured, gradient_accents or radial_glows, signature or heavy ornament, bold or playful typography, filtered or dramatic image (for image variants).

Don't default to flat/flat/minimal/editorial/clean unless the brand specifically demands quietness within the Studio Brut family (e.g., a streetwear brand with deliberately minimal-poster positioning).

Business-archetype guidance:

  custom apparel / streetwear (the canonical Studio Brut archetype)
    → soft_gradient or textured background
    → gradient_accents or radial_glows color_depth
    → signature or heavy ornament
    → bold or playful typography
    → dramatic image treatment
    Reason: visual character IS the value proposition. Lean into loud.

  design studio with edge / branding agency leading with personality
    → soft_gradient or vignette background
    → gradient_accents color_depth
    → signature or heavy ornament
    → bold or editorial typography (editorial = Studio Brut's quietest, still loud)
    → filtered or dramatic image
    Reason: confident craft, designed-poster aesthetic.

  urban photographer / lifestyle photographer with grit
    → vignette or flat background
    → flat or radial_glows color_depth
    → signature ornament
    → editorial or bold typography
    → dramatic image treatment
    Reason: image dominates; depth supports rather than competes with photography.

  independent maker / artisan craft brand
    → textured background (visible craft)
    → gradient_accents color_depth
    → signature ornament
    → bold or refined typography
    → filtered or dramatic image
    Reason: tactility + character + crafted-graphic aesthetic.

  music / culture / nightlife brand
    → vignette or soft_gradient background
    → radial_glows color_depth
    → heavy ornament
    → playful or bold typography
    → dramatic image
    Reason: subculture energy, poster-grade visual.

═══════════════════════════════════════════════════════════════
HOW TO PICK VARIANT
═══════════════════════════════════════════════════════════════

Read the business's archetype, brand metaphor, vibe, and tone. Match the variant to the brand's PERSONALITY.

Examples of variant-archetype fit:

  custom apparel / streetwear → edge_bleed_portrait, layered_card, oversize_statement
                                (image-led + bold-declarative options)
  design studio with edge   → color_block_split, type_collage, stat_strip
                                (poster-graphic + type-as-graphic + numbers-led)
  urban photographer        → layered_card, double_split, edge_bleed_portrait
                                (image + content layering options)
  independent maker         → oversize_statement, massive_letterform, diagonal_band
                                (declarative claim + identity + transitional metaphor)
  publishing / label / magazine → rotated_anchor, stacked_blocks, stat_strip
                                (editorial codified layouts)
  music / culture brand     → oversize_statement, layered_card, diagonal_band
                                (loud + layered + cut-through)

═══════════════════════════════════════════════════════════════
WRITING THE CONTENT
═══════════════════════════════════════════════════════════════

Studio Brut copy is direct, energetic, personality-forward. Shorter sentences than Cathedral. Punchier cadence. Imperative voice frequent.

eyebrow:           short uppercase label (2-5 words). Reflects brand metaphor or domain vocabulary ('THE ROYAL COURT', 'MADE LOUD', 'STUDIO PRACTICE'). Studio Brut eyebrows are often codes ('CASE 23', 'VOL. II', 'EST. 2024') for the right brands. Avoid generic openers.
heading:           the hero claim. Studio Brut headings are SHORT (4-7 words typical) — shorter than Cathedral's. Declarative or imperative. Direct address welcome ('Wear your crown', 'Cut the noise, keep the signal'). Contains ONE word that becomes the emphasis word.
heading_emphasis:  EXACT substring of heading that gets Studio Brut's emphasis treatment (NOT italic — uses weight/scale/color contrast per typography treatment). MUST be word(s) actually present in heading.
subtitle:          single sentence. Shorter than Cathedral's. Can amplify the heading OR counterpoint it. Italic permitted when typography=playful.
cta_primary:       SHORT action verb label specific to this practice. Studio Brut CTAs LEAN ACTION: 'Start your design', 'Drop a brief', 'Wear your story', 'Cut the noise', 'Make it loud'. AVOID stately Cathedral verbs ('Begin', 'Reserve'). AVOID generic ('Get Started', 'Learn More').
cta_target:        anchor (#contact / #book) or mailto: or URL.
image_slot_ref:    'hero_main' if variant uses an image (variants 5, 7, 10), null otherwise.

═══════════════════════════════════════════════════════════════
GAP REASONING
═══════════════════════════════════════════════════════════════

If NO variant perfectly fits, pick the CLOSEST match and explicitly note the gap. Be honest — gap data tells the next library expansion which variants to build first.

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════

Output ONE JSON object. No markdown fences. The schema:

{
  \"variant\": \"<one of the 11 variant ids>\",
  \"treatments\": {
    \"color_emphasis\": \"<signal_dominant | authority_dominant | dual_emphasis>\",
    \"spacing_density\": \"<generous | standard | compact>\",
    \"emphasis_weight\": \"<heading_dominant | balanced | eyebrow_dominant>\",
    \"background\": \"<flat | soft_gradient | textured | vignette>\",
    \"color_depth\": \"<flat | gradient_accents | radial_glows>\",
    \"ornament\": \"<minimal | signature | heavy>\",
    \"typography\": \"<editorial | bold | refined | playful>\",
    \"image_treatment\": \"<clean | filtered | dramatic | soft>\"
  },
  \"content\": {
    \"eyebrow\": \"<2-5 word uppercase label, or code label>\",
    \"heading\": \"<short declarative heading (4-7 words) containing the emphasis substring>\",
    \"heading_emphasis\": \"<exact substring — emphasis treatment is weight/scale/color, NOT italic>\",
    \"subtitle\": \"<single completing or counterpointing sentence>\",
    \"cta_primary\": \"<SHORT action verb label — Start / Drop / Wear / Cut / Make / Begin (action-led, not stately)>\",
    \"cta_target\": \"<#anchor or mailto: or URL>\",
    \"image_slot_ref\": \"hero_main\" OR null
  },
  \"reasoning\": \"<2-3 sentences. Why this variant + treatments for this business. Reference Studio Brut DNA (color-as-architecture / type-as-graphic / asymmetry-baseline / sharp-commits / density). Note variant gap if no perfect fit.>\"
}

All 8 treatment fields are REQUIRED. Output ONLY the JSON object."""


# ─── Module specification table ────────────────────────────────────

@dataclass
class ModuleSpec:
    """Per-module specifications. The composer dispatches on module_id
    to the right ModuleSpec, then uses its system_prompt + composition_type
    + image_using_variants + safe_fallback_variant uniformly."""

    module_id: str
    system_prompt: str
    composition_type: Type[BaseModel]
    image_using_variants: FrozenSet[str]
    safe_fallback_variant: str  # variant emitted by _safe_fallback


MODULES: Dict[str, ModuleSpec] = {
    "cathedral": ModuleSpec(
        module_id="cathedral",
        system_prompt=CATHEDRAL_SYSTEM_PROMPT,
        composition_type=CathedralHeroComposition,
        image_using_variants=CATHEDRAL_IMAGE_USING_VARIANTS,
        # Manifesto_center = Cathedral's safest text-only variant
        safe_fallback_variant="manifesto_center",
    ),
    "studio_brut": ModuleSpec(
        module_id="studio_brut",
        system_prompt=STUDIO_BRUT_SYSTEM_PROMPT,
        composition_type=StudioBrutHeroComposition,
        image_using_variants=STUDIO_BRUT_IMAGE_USING_VARIANTS,
        # Color_block_split = Studio Brut's safest text-only variant
        # (clearly Studio Brut DNA, no image dependency)
        safe_fallback_variant="color_block_split",
    ),
}


# ─── Soft-fail fallback ─────────────────────────────────────────────

def _safe_fallback(spec: ModuleSpec, business_id: str, reason: str,
                   raw: Optional[str] = None) -> Dict[str, Any]:
    """Structured fallback when the LLM call fails. Uses the module's
    safe_fallback_variant + placeholder content so the render layer
    has SOMETHING to render. Caller can detect via _composer_error."""
    out: Dict[str, Any] = {
        "section": "hero",
        "variant": spec.safe_fallback_variant,
        "treatments": {
            "color_emphasis": "signal_dominant",
            "spacing_density": "standard",
            "emphasis_weight": "heading_dominant",
            "background": "flat",
            "color_depth": "flat",
            "ornament": "minimal",
            "typography": "editorial",
            "image_treatment": "clean",
        },
        "content": {
            "eyebrow": "THE WORK",
            "heading": "We are still composing this.",
            "heading_emphasis": "composing",
            "subtitle": "The Composer Agent fell back to a default; check logs.",
            "cta_primary": "Begin",
            "cta_target": "#contact",
            "image_slot_ref": None,
        },
        "reasoning": f"FALLBACK — Composer ({spec.module_id}) failed: {reason}",
        "_composer_error": reason,
        "_composer_metadata": {"module_id": spec.module_id, "fallback": True},
    }
    # Studio Brut's composition type has a module discriminator field;
    # set it so Pydantic validation succeeds for either module's shape.
    if spec.module_id == "studio_brut":
        out["module"] = "studio_brut"
    if raw:
        out["_raw_response"] = raw[:1000]
    return out


def _strip_code_fence(text: str) -> str:
    """Same helper used by feedback_enrichment / intent_classifier /
    module_router."""
    text = (text or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl > 0:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[: -3]
    return text.strip()


# ─── Business context fetch (shared across modules) ────────────────

def fetch_business_context(business_id: str) -> Dict[str, Any]:
    """Fetch enriched_brief + brand_kit + available_slots for a business.
    Returns a dict ready to drop into the user prompt. Same surface
    as the original cathedral_hero_composer.fetch_business_context —
    business context is module-agnostic."""
    ctx: Dict[str, Any] = {
        "business_name": "Unknown business",
        "business_description": "",
        "inferred_archetype": "service_consultant",
        "inferred_vibe": "",
        "brand_metaphor": "",
        "strand_pair": "",
        "sub_strand_id": "",
        "tone_words": [],
        "brand_kit": {
            "primary": "#0A1628",
            "secondary": "#122040",
            "accent": "#C6952F",
            "background": "#F8F6F1",
            "text": "#0F172A",
        },
        "available_slots": [],
    }
    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[composer] brand_engine import failed: {e}")
        return ctx

    try:
        biz_rows = be_get(
            f"/businesses?id=eq.{business_id}&select=name,settings&limit=1"
        ) or []
        if biz_rows:
            biz = biz_rows[0]
            ctx["business_name"] = biz.get("name") or ctx["business_name"]
            settings = biz.get("settings") or {}
            bk = settings.get("brand_kit") or {}
            colors = bk.get("colors") or {}
            for role in ("primary", "secondary", "accent", "background", "text"):
                if colors.get(role):
                    ctx["brand_kit"][role] = colors[role]
                else:
                    flat = "text_color" if role == "text" else f"{role}_color"
                    if bk.get(flat):
                        ctx["brand_kit"][role] = bk[flat]
            ctx["business_description"] = (
                bk.get("elevator_pitch")
                or settings.get("description")
                or settings.get("about")
                or ""
            )
    except Exception as e:
        logger.warning(f"[composer] business fetch failed for {business_id}: {e}")

    try:
        site_rows = be_get(
            f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
        ) or []
        if site_rows:
            cfg = site_rows[0].get("site_config") or {}
            eb = cfg.get("enriched_brief") or {}
            bi = cfg.get("build_inputs") or {}
            dr = cfg.get("design_recommendation") or {}
            ctx["business_name"] = bi.get("business_name") or ctx["business_name"]
            if not ctx["business_description"]:
                ctx["business_description"] = (
                    bi.get("description") or eb.get("description") or ""
                )
            ctx["inferred_archetype"] = (
                eb.get("content_archetype")
                or eb.get("inferred_archetype")
                or bi.get("archetype")
                or ctx["inferred_archetype"]
            )
            ctx["inferred_vibe"] = eb.get("inferred_vibe") or ""
            ctx["brand_metaphor"] = eb.get("brand_metaphor") or ""
            ctx["strand_pair"] = (
                f"{dr.get('strand_a_id', '')}/{dr.get('strand_b_id', '')}"
                if dr.get("strand_a_id") else ""
            )
            ctx["sub_strand_id"] = dr.get("sub_strand_id") or ""
            ctx["tone_words"] = eb.get("tone_words") or []
            slots = cfg.get("slots") or {}
            ctx["available_slots"] = sorted(slots.keys())
    except Exception as e:
        logger.warning(f"[composer] site_config fetch failed for {business_id}: {e}")

    return ctx


def build_user_prompt(ctx: Dict[str, Any]) -> str:
    """Format the business context into a Composer user prompt.
    Module-agnostic — the system prompt provides module-specific
    guidance; the user prompt provides business context."""
    tone_words = ctx.get("tone_words") or []
    tone_str = ", ".join(tone_words) if tone_words else "(none captured)"
    slots = ctx.get("available_slots") or []
    slots_str = ", ".join(slots) if slots else "(none populated yet)"
    bk = ctx.get("brand_kit") or {}

    return f"""Compose a Hero section for the following business.

BUSINESS CONTEXT:

  business_name:        {ctx.get('business_name') or '(unknown)'}
  business_description: {(ctx.get('business_description') or '(none)').strip()[:600]}
  inferred_archetype:   {ctx.get('inferred_archetype') or '(unknown)'}
  inferred_vibe:        {ctx.get('inferred_vibe') or '(none)'}
  brand_metaphor:       {ctx.get('brand_metaphor') or '(none)'}
  strand_pair:          {ctx.get('strand_pair') or '(none)'}
  sub_strand_id:        {ctx.get('sub_strand_id') or '(none)'}
  tone_words:           {tone_str}

BRAND KIT COLORS:
  primary:    {bk.get('primary', '?')}
  secondary:  {bk.get('secondary', '?')}
  accent:     {bk.get('accent', '?')}
  background: {bk.get('background', '?')}
  text:       {bk.get('text', '?')}

AVAILABLE IMAGE SLOTS: {slots_str}
  Note: if the variant uses an image but the slot doesn't exist yet, pick the variant anyway
  and set image_slot_ref to 'hero_main' — the slot resolver will render a
  placeholder until the practitioner uploads.

Pick ONE variant from the 11. Pick treatments. Write the content. Output
only the JSON object specified in the system prompt."""


# ─── Post-validation ────────────────────────────────────────────────

_DEPTH_DEFAULTS = {
    "background": "flat",
    "color_depth": "flat",
    "ornament": "minimal",
    "typography": "editorial",
    "image_treatment": "clean",
}

_DEPTH_ALLOWED = {
    "background": {"flat", "soft_gradient", "textured", "vignette"},
    "color_depth": {"flat", "gradient_accents", "radial_glows"},
    "ornament": {"minimal", "signature", "heavy"},
    "typography": {"editorial", "bold", "refined", "playful"},
    "image_treatment": {"clean", "filtered", "dramatic", "soft"},
}


def _missing_depth_fields(comp_dict: Dict[str, Any]) -> list:
    treatments = comp_dict.get("treatments") or {}
    return [k for k in _DEPTH_DEFAULTS if not treatments.get(k)]


def _enforce_depth_treatments(comp_dict: Dict[str, Any]) -> Dict[str, Any]:
    treatments = comp_dict.get("treatments") or {}
    for field_name, default in _DEPTH_DEFAULTS.items():
        v = treatments.get(field_name)
        if v not in _DEPTH_ALLOWED[field_name]:
            treatments[field_name] = default
    comp_dict["treatments"] = treatments
    return comp_dict


def _enforce_image_slot_consistency(comp_dict: Dict[str, Any],
                                    spec: ModuleSpec) -> Dict[str, Any]:
    """Module-aware: looks up the module's IMAGE_USING_VARIANTS set,
    not Cathedral's. A Studio Brut variant like 'edge_bleed_portrait'
    is image-using; 'color_block_split' isn't."""
    variant = comp_dict.get("variant")
    content = comp_dict.get("content") or {}
    if variant in spec.image_using_variants:
        if not content.get("image_slot_ref"):
            content["image_slot_ref"] = "hero_main"
    else:
        content["image_slot_ref"] = None
    comp_dict["content"] = content
    return comp_dict


# ─── Public entrypoint ──────────────────────────────────────────────

def compose_hero(
    business_id: str,
    module_id: str = "cathedral",
) -> Dict[str, Any]:
    """Run the Composer Agent for one business in the specified module.

    Returns a JSON-serializable dict matching the module's composition
    type (CathedralHeroComposition or StudioBrutHeroComposition),
    plus a `_composer_metadata` envelope with module routing
    diagnostics. Soft-fails on any error to a structured fallback
    composition with `_composer_error` set.

    One Sonnet call (~5-8 seconds typical), one Pydantic validation,
    one post-validation pass. One retry on JSON parse failure. One
    retry on missing depth fields with explicit feedback."""
    spec = MODULES.get(module_id)
    if spec is None:
        # Hard error — caller passed an unknown module. Fall back to
        # Cathedral with a logged warning rather than raise, so the
        # composition pipeline never crashes from a typo.
        logger.warning(
            f"[composer] unknown module_id={module_id!r}, defaulting to cathedral"
        )
        spec = MODULES["cathedral"]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _safe_fallback(spec, business_id, "ANTHROPIC_API_KEY not configured")

    ctx = fetch_business_context(business_id)
    user_prompt = build_user_prompt(ctx)

    client = Anthropic(api_key=api_key)

    def _call(extra_user: str = "") -> str:
        msg = client.messages.create(
            model=COMPOSER_MODEL,
            max_tokens=COMPOSER_MAX_TOKENS,
            temperature=COMPOSER_TEMPERATURE,
            system=spec.system_prompt,
            messages=[{"role": "user", "content": user_prompt + extra_user}],
        )
        return "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        )

    # ── Attempt 1 ──
    try:
        raw = _call()
    except Exception as e:
        logger.warning(
            f"[composer] Anthropic call failed for {business_id} "
            f"(module={module_id}): {type(e).__name__}: {e}"
        )
        return _safe_fallback(
            spec, business_id,
            f"Anthropic call failed: {type(e).__name__}: {e}",
        )

    text = _strip_code_fence(raw)
    parsed: Optional[Dict[str, Any]] = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(
            f"[composer] JSON parse failed for {business_id} "
            f"(module={module_id}, attempt 1): {e}"
        )
        retry_extra = (
            f"\n\nYour previous response was not valid JSON. Error: "
            f"{e}\n\nOutput ONLY the JSON object. No markdown fences."
        )
        try:
            raw_retry = _call(retry_extra)
            parsed = json.loads(_strip_code_fence(raw_retry))
        except Exception as retry_e:
            logger.warning(f"[composer] JSON retry failed: {retry_e}")
            return _safe_fallback(
                spec, business_id,
                f"JSON parse failed (after retry): {retry_e}", raw=text,
            )

    if not isinstance(parsed, dict):
        return _safe_fallback(spec, business_id, "Model returned non-object", raw=text)

    # Depth-field retry — same pattern as Phase 2.6 Cathedral composer.
    missing_depth = _missing_depth_fields(parsed)
    if missing_depth:
        logger.warning(
            f"[composer] depth fields missing on first attempt "
            f"(module={module_id}): {missing_depth} — retrying"
        )
        retry_msg = (
            f"\n\nYour previous response was missing depth treatment "
            f"fields: {', '.join(missing_depth)}. ALL 8 treatment "
            f"fields are required — pick intentional depth treatments "
            f"per the business-archetype guidance in the system "
            f"prompt, not safe defaults. Output the full JSON again."
        )
        try:
            raw_retry = _call(retry_msg)
            re_parsed = json.loads(_strip_code_fence(raw_retry))
            if isinstance(re_parsed, dict):
                parsed = re_parsed
        except Exception as retry_e:
            logger.warning(
                f"[composer] depth-retry failed: {retry_e}; "
                f"backfilling defaults"
            )

    parsed = _enforce_depth_treatments(parsed)
    parsed = _enforce_image_slot_consistency(parsed, spec)
    parsed.setdefault("section", "hero")
    # Studio Brut's Pydantic model has a `module` discriminator; set it
    # so validation succeeds even when the LLM didn't include it.
    if spec.module_id == "studio_brut":
        parsed.setdefault("module", "studio_brut")

    try:
        composition = spec.composition_type.model_validate(parsed)
    except ValidationError as ve:
        logger.warning(
            f"[composer] Pydantic validation failed for {business_id} "
            f"(module={module_id}): {ve}"
        )
        return _safe_fallback(
            spec, business_id, f"Validation failed: {ve}", raw=text,
        )

    out = composition.model_dump()
    out["_composer_metadata"] = {
        "module_id": spec.module_id,
        "business_id": business_id,
    }
    return out
