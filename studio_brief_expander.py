"""Brief Expander — LLM #2.

Takes a design recommendation from Pass 3.8a and expands it into a full
30-field DesignBrief via Claude Opus. Schema validation strict; partial
output salvaged with _validation_warnings flagged. Fonts always
deterministically overridden after LLM returns.
"""
from __future__ import annotations
import sys
import time
from typing import Optional

from studio_strands import get_strand
from studio_substrands import get_substrand
from studio_strand_fonts import resolve_font_pair
from studio_design_constants import LAYOUT_ARCHETYPE_DESCRIPTIONS
from studio_design_brief import get_default_brief, validate_design_brief
from studio_designer_agent import _call_claude, _extract_json


def _build_expander_prompt(bundle, recommendation, products) -> str:
    """Compose the Brief Expander LLM prompt. Pure function — no IO."""
    bundle = bundle or {}
    business = bundle.get("business") or {}
    voice = bundle.get("voice") or {}
    intel = bundle.get("practitioner_intelligence") or {}

    a_id = recommendation["strand_a_id"]
    b_id = recommendation["strand_b_id"]
    ratio_a = recommendation["ratio_a"]
    ratio_b = recommendation["ratio_b"]
    sub_id = recommendation.get("sub_strand_id")
    archetype = recommendation["layout_archetype"]
    accent_style = recommendation["accent_style"]
    site_type = recommendation["site_type"]

    strand_a = get_strand(a_id) or {}
    strand_b = get_strand(b_id) or {}
    sub_strand = get_substrand(sub_id) if sub_id else None

    sub_block = ""
    if sub_strand:
        sub_block = f"""
SUB-STRAND VARIANT: {sub_strand.get('name', sub_id)}
Temperature: {sub_strand.get('temperature', '')}
Color direction: {sub_strand.get('colorDirection', '')}
Typography direction: {sub_strand.get('typographyDirection', '')}
Spatial direction: {sub_strand.get('spatialDirection', '')}
Hero layout pattern: {sub_strand.get('heroLayout', '')}
Signature detail: {sub_strand.get('signatureDetail', '')}
Reference brands: {sub_strand.get('exampleBrands', '')}
"""

    archetype_desc = LAYOUT_ARCHETYPE_DESCRIPTIONS.get(archetype, "")

    products_block = ""
    if products:
        product_lines = []
        for p in products[:6]:
            if not isinstance(p, dict):
                continue
            name = (p.get("name") or "").strip()
            desc = (p.get("description") or "").strip()
            price = p.get("price")
            line = f"- {name}" if name else "- (unnamed)"
            if price:
                line += f" (${price})"
            if desc:
                line += f": {desc[:120]}"
            product_lines.append(line)
        products_block = "\n".join(product_lines)

    voice_dos = voice.get("voice_dos") or []
    voice_donts = voice.get("voice_donts") or []
    voice_dos_str = ", ".join(str(d) for d in voice_dos) or "(none)"
    voice_donts_str = ", ".join(str(d) for d in voice_donts) or "(none)"

    return f"""You are a senior creative director at KMJ Creative Solutions. Respond ONLY with a raw JSON object matching the DesignBrief shape. No markdown. No explanation.

Before generating any visual decisions, identify the TENSION STATEMENT — the single sentence that captures why these two strands create something more powerful together than either alone.

The tension is not a compromise. It is a productive contradiction that becomes the brand signature.

Example: Luxury + Brutalist = "Ceremony held inside raw structure — the unexpected container amplifies the content's value."

The ratio controls:
- Higher luxury ratio: more ceremonial copy register, longer sentences, gold appears sparingly
- Higher brutalist ratio: harder borders, shorter sentences, structural aggression
- Higher editorial ratio: typographic hierarchy dominates, asymmetry, pull-quotes
- Higher minimal ratio: radical negative space, one focal element, restraint in everything
- Higher dark ratio: atmospheric depth, glowing accents, cinematic pacing
- Higher bold ratio: type as illustration, rule-breaking scale, maximum contrast

# DESIGN PICK FROM DESIGNER AGENT (LLM #1)

STRAND A ({ratio_a}%): {strand_a.get('name', a_id)}
{strand_a.get('dna', '')}

STRAND B ({ratio_b}%): {strand_b.get('name', b_id)}
{strand_b.get('dna', '')}

SPATIAL DNA — how space behaves in each strand:

STRAND A spatial behavior:
{strand_a.get('spatialDNA', '')}

STRAND B spatial behavior:
{strand_b.get('spatialDNA', '')}

BLENDED SPATIAL APPROACH:
At {ratio_a}% / {ratio_b}%, synthesize a spatial direction that expresses both strands. The dominant strand controls the primary spatial gesture. The recessive strand introduces the tension.
{sub_block}
LAYOUT ARCHETYPE: {archetype}
{archetype_desc}

ACCENT STYLE: {accent_style}
SITE TYPE: {site_type}

# CLIENT INTELLIGENCE

Business: {business.get('name', 'Unknown')}
Type: {business.get('type', 'custom')}
Tagline: {business.get('tagline') or '(none)'}
Elevator pitch: {business.get('elevator_pitch') or '(none)'}

ABOUT ME (practitioner identity):
{intel.get('about_me') or '(none)'}

ABOUT MY BUSINESS:
{intel.get('about_business') or '(none)'}

STRATEGY TRACK:
{intel.get('strategy_track') or '(none)'}

VOICE:
Brand voice (canonical): {voice.get('brand_voice') or '(none)'}
Tone: {voice.get('tone') or '(none)'}
Voice dos: {voice_dos_str}
Voice donts: {voice_donts_str}

PRODUCTS / OFFERINGS:
{products_block or '(none)'}

# DELIVERABLE — DesignBrief shape

{{
  "conceptName": "string — a creative name for this design direction",
  "tagline": "string — one line that captures the vibe (use the practitioner's actual tagline if provided, otherwise generate)",
  "blendRatio": "string — e.g. '60% Editorial / 40% Luxury'",
  "industry": "string",
  "mood": "string — 3-5 words describing the emotional feel",
  "tensionStatement": "one sentence — the productive contradiction that IS the concept",
  "copyVoice": "tone, register, sentence energy — e.g. 'Punchy declarative. Masculine. Ceremonial.'",
  "animationCharacter": "type and feel of motion — one phrase — e.g. 'One ceremonial reveal. Unhurried. Gold last.'",
  "imageApproach": "photography treatment direction — e.g. 'Grayscale only. High contrast portraits.'",
  "spatialDirection": "one paragraph — how space moves through this page: rhythm, dominant axis, compression/release pattern, how sections relate spatially",
  "palette": [
    {{ "hex": "#xxxxxx", "name": "Color Name", "role": "primary | secondary | accent | background | text | highlight" }}
  ],
  "colorDiscipline": {{
    "accentRule": "when and how accent color appears",
    "ctaColor": "#hex — what color drives action buttons",
    "maxAccentPerSection": 2,
    "neutralUsage": "how neutral colors carry weight"
  }},
  "typography": {{
    "display": {{ "name": "Google Font Name", "weight": "700", "usage": "Hero headlines, section titles" }},
    "body": {{ "name": "Google Font Name", "weight": "400", "usage": "Paragraphs, descriptions" }},
    "accent": {{ "name": "Google Font Name", "weight": "500", "usage": "Labels, captions, nav" }}
  }},
  "philosophy": "string — 2-3 sentences on the design philosophy and WHY these choices work for THIS practitioner specifically",
  "sections": [
    {{ "name": "Section Name", "layout": "full-bleed | split | grid | centered | asymmetric", "designNote": "specific creative direction for THIS section", "copyDirection": "how copy reads in this section", "ctaText": "actual CTA button text if needed", "layoutType": "hero | grid | list | split | form | manifesto | full-bleed | centered" }}
  ],
  "accentConfig": {{
    "style": "{accent_style}",
    "primaryAccentType": "divider | watermark | symbol",
    "dividerStyle": "which divider fits this brand best (e.g. gold-rule-diamond, double-hairline, thin-rule)",
    "hasTexture": true,
    "hasWatermark": true,
    "symbolStyle": "which symbol style fits",
    "opacity": 0.08
  }},
  "colorSource": {{
    "hexAnchors": [],
    "colorNames": [],
    "interpretedColors": [],
    "fullyGenerated": true,
    "summary": "one sentence — what colors came from the client and what was designed"
  }},
  "buildNotes": "string — technical notes for the builder: spacing rules, animation notes, special considerations specific to this brief"
}}

# RULES

- For each section, the layoutType must express the spatial direction — not just the content. A luxury+brutalist hero is not centered — content sits lower, bordered by a gold rule. An editorial+minimal services section does not use a 3-column card grid — it uses an asymmetric list with one dominant item and subordinate items.
- Return exactly 5-8 palette colors, 5-8 sections, and real Google Font names.
- For ceremonial accents (gold, premium): set opacity 0.05-0.08. For bold accents: set 0.10-0.12.
- The tagline should be SHORT and SPECIFIC. Avoid generic agency-speak like "elevate the vision" or "transform your business."
- The conceptName should be evocative and original — like a creative director naming a campaign.
- Use the practitioner's actual voice + practitioner intelligence to write copyDirection per section. Don't invent generic copy.
- All hex colors 6 characters with leading #. Line color can be rgba.

Generate the complete DesignBrief JSON now."""


def _post_process_brief(brief, recommendation, selected_tagline=None):
    """Apply deterministic overrides after LLM returns.
    1. Force fonts via STRAND_FONT_MAP (Studio pattern)
    2. Override tagline if explicitly provided
    3. Add metadata
    """
    a_id = recommendation["strand_a_id"]
    b_id = recommendation["strand_b_id"]
    ratio_a = recommendation["ratio_a"]

    fonts = resolve_font_pair(a_id, b_id, ratio_a)

    if "typography" not in brief or not isinstance(brief["typography"], dict):
        brief["typography"] = {}

    for slot, font_name in [
        ("display", fonts["display"]),
        ("body", fonts["body"]),
        ("accent", fonts["accent"]),
    ]:
        existing = brief["typography"].get(slot)
        if not isinstance(existing, dict):
            brief["typography"][slot] = {"name": font_name, "weight": "400", "usage": ""}
        else:
            existing["name"] = font_name

    if selected_tagline:
        brief["tagline"] = selected_tagline

    # Pass through structural fields from recommendation if missing
    brief.setdefault("layoutArchetype", recommendation["layout_archetype"])
    brief.setdefault("siteType", recommendation["site_type"])
    brief.setdefault("subStrandId", recommendation.get("sub_strand_id"))

    brief["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    brief["schemaVersion"] = 1

    return brief


def expand_design_brief(bundle, recommendation, products):
    """Run the Brief Expander pipeline.

    Returns (brief: dict | None, error_message: str | None).
    On any LLM/parse/validation failure, returns the deterministic
    default brief with `_validation_warnings` flagged — never returns
    None on a recoverable error. Brief is None only if recommendation
    itself is missing required fields.
    """
    if not isinstance(recommendation, dict) or not recommendation.get("strand_a_id"):
        return None, "Invalid recommendation"

    business = (bundle or {}).get("business") or {}
    business_name = business.get("name", "Unknown")
    industry = business.get("type", "custom")

    # Cold-start path: deterministic default, no LLM call
    if recommendation.get("cold_start"):
        brief = get_default_brief(recommendation, business_name, industry)
        # Still post-process for consistent metadata + font override
        brief = _post_process_brief(brief, recommendation)
        return brief, None

    # Rich-data path: LLM #2
    try:
        prompt = _build_expander_prompt(bundle, recommendation, products)
        raw_output = _call_claude(prompt, max_tokens=4500)
    except Exception as e:
        print(f"[brief_expander] Claude call failed: {e}", file=sys.stderr)
        brief = get_default_brief(recommendation, business_name, industry)
        brief = _post_process_brief(brief, recommendation)
        brief["_validation_warnings"] = [
            f"LLM call failed, used default: {type(e).__name__}: {e}"
        ]
        return brief, None

    brief = _extract_json(raw_output)
    if not brief:
        print("[brief_expander] JSON extraction failed", file=sys.stderr)
        brief = get_default_brief(recommendation, business_name, industry)
        brief = _post_process_brief(brief, recommendation)
        brief["_validation_warnings"] = ["JSON extraction failed, used default"]
        return brief, None

    is_valid, errors, warnings = validate_design_brief(brief)
    if not is_valid:
        print(f"[brief_expander] Validation errors: {errors}", file=sys.stderr)
        brief = get_default_brief(recommendation, business_name, industry)
        brief = _post_process_brief(brief, recommendation)
        brief["_validation_warnings"] = [
            f"Validation failed: {'; '.join(errors[:3])}"
        ] + warnings
        return brief, None

    # Post-process (deterministic overrides)
    brief = _post_process_brief(brief, recommendation)

    if warnings:
        brief["_validation_warnings"] = warnings

    return brief, None
