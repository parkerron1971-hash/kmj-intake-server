"""DesignBrief — 30-field JSON contract that drives rendering.

Output of LLM #2 (Brief Expander). Consumed by layout archetype renderers
in Pass 3.8c. Schema ported verbatim from Studio's TypeScript.
"""
from __future__ import annotations
from typing import TypedDict, Optional
import re
import time


# ── Field type definitions ──

class PaletteColor(TypedDict, total=False):
    hex: str
    name: str
    role: str  # primary | secondary | accent | background | text | highlight


class TypographyEntry(TypedDict, total=False):
    name: str
    weight: str
    usage: str


class Typography(TypedDict, total=False):
    display: TypographyEntry
    body: TypographyEntry
    accent: TypographyEntry


class ColorDiscipline(TypedDict, total=False):
    accentRule: str
    ctaColor: str
    maxAccentPerSection: int
    neutralUsage: str


class AccentConfig(TypedDict, total=False):
    style: str
    primaryAccentType: str  # divider | watermark | symbol
    dividerStyle: str
    hasTexture: bool
    hasWatermark: bool
    symbolStyle: str
    opacity: float


class DesignSection(TypedDict, total=False):
    name: str
    layout: str  # full-bleed | split | grid | centered | asymmetric
    designNote: str
    copyDirection: Optional[str]
    ctaText: Optional[str]
    layoutType: str  # hero | grid | list | split | form | manifesto | full-bleed | centered


class ColorSource(TypedDict, total=False):
    hexAnchors: list
    colorNames: list
    interpretedColors: list
    fullyGenerated: bool
    summary: str


class DesignBrief(TypedDict, total=False):
    # Core identity
    conceptName: str
    tagline: str
    blendRatio: str
    industry: str
    mood: str

    # Strategic direction
    tensionStatement: str
    philosophy: str
    copyVoice: str
    animationCharacter: str
    imageApproach: str
    spatialDirection: str

    # Color system
    palette: list  # list[PaletteColor]
    colorDiscipline: ColorDiscipline
    colorSource: ColorSource

    # Typography
    typography: Typography

    # Layout & structure
    sections: list  # list[DesignSection]
    layoutArchetype: str
    siteType: str
    accentConfig: AccentConfig
    subStrandId: Optional[str]

    # Build notes & metadata
    buildNotes: str
    generatedAt: str
    schemaVersion: int  # always 1

    # Validation flags
    _validation_warnings: Optional[list]


# ── Validators ──

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
RGBA_RE = re.compile(r"^rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*[\d.]+\s*\)$")

VALID_LAYOUT_TYPES = {"hero", "grid", "list", "split", "form", "manifesto", "full-bleed", "centered"}
VALID_LAYOUT_FIELDS = {"full-bleed", "split", "grid", "centered", "asymmetric"}
VALID_PALETTE_ROLES = {"primary", "secondary", "accent", "background", "text", "highlight"}
VALID_ACCENT_TYPES = {"divider", "watermark", "symbol"}


def validate_color(value) -> bool:
    if not isinstance(value, str):
        return False
    return bool(HEX_RE.match(value)) or bool(RGBA_RE.match(value))


def validate_design_brief(brief):
    """Validate a DesignBrief.
    Returns (is_valid, hard_errors, soft_warnings).
    Soft warnings don't fail validation but get tracked in _validation_warnings.
    """
    if not isinstance(brief, dict):
        return False, ["Brief must be a dict"], []

    errors = []
    warnings = []

    # Required string fields
    required_strings = [
        "conceptName", "tagline", "blendRatio", "industry", "mood",
        "tensionStatement", "philosophy", "copyVoice", "spatialDirection",
        "buildNotes",
    ]
    for field in required_strings:
        v = brief.get(field)
        if not isinstance(v, str) or not v.strip():
            errors.append(f"Missing or empty required string: {field}")

    # Palette validation
    palette = brief.get("palette", [])
    if not isinstance(palette, list) or len(palette) < 3:
        errors.append("palette must be list of at least 3 colors")
    else:
        for i, color in enumerate(palette):
            if not isinstance(color, dict):
                errors.append(f"palette[{i}] must be dict")
                continue
            if not validate_color(color.get("hex", "")):
                errors.append(f"palette[{i}].hex invalid: {color.get('hex')}")
            if not isinstance(color.get("name"), str):
                warnings.append(f"palette[{i}].name not a string")
            if color.get("role") not in VALID_PALETTE_ROLES:
                warnings.append(f"palette[{i}].role invalid: {color.get('role')}")

    # Typography validation
    typography = brief.get("typography", {})
    if not isinstance(typography, dict):
        errors.append("typography must be dict")
    else:
        for slot in ("display", "body", "accent"):
            slot_val = typography.get(slot)
            if not isinstance(slot_val, dict):
                errors.append(f"typography.{slot} must be dict")
                continue
            if not isinstance(slot_val.get("name"), str):
                errors.append(f"typography.{slot}.name must be string")

    # Sections validation
    sections = brief.get("sections", [])
    if not isinstance(sections, list) or len(sections) < 4:
        errors.append("sections must be list of at least 4 sections")
    else:
        for i, section in enumerate(sections):
            if not isinstance(section, dict):
                errors.append(f"sections[{i}] must be dict")
                continue
            if not isinstance(section.get("name"), str):
                warnings.append(f"sections[{i}].name not a string")
            if section.get("layoutType") not in VALID_LAYOUT_TYPES:
                warnings.append(f"sections[{i}].layoutType invalid: {section.get('layoutType')}")

    # ColorDiscipline validation
    cd = brief.get("colorDiscipline", {})
    if not isinstance(cd, dict):
        errors.append("colorDiscipline must be dict")
    else:
        if not isinstance(cd.get("accentRule"), str):
            warnings.append("colorDiscipline.accentRule should be string")
        if not validate_color(cd.get("ctaColor", "")):
            warnings.append(f"colorDiscipline.ctaColor invalid: {cd.get('ctaColor')}")
        max_accent = cd.get("maxAccentPerSection")
        if not isinstance(max_accent, int) or max_accent < 1 or max_accent > 5:
            warnings.append("colorDiscipline.maxAccentPerSection should be int 1-5")

    # AccentConfig validation
    ac = brief.get("accentConfig", {})
    if isinstance(ac, dict):
        if "opacity" in ac:
            opacity = ac["opacity"]
            if not isinstance(opacity, (int, float)) or not 0 <= opacity <= 1:
                warnings.append(f"accentConfig.opacity should be 0-1: {opacity}")
        if "primaryAccentType" in ac and ac["primaryAccentType"] not in VALID_ACCENT_TYPES:
            warnings.append(f"accentConfig.primaryAccentType invalid: {ac['primaryAccentType']}")

    # Schema version (soft — auto-set by post-process)
    if brief.get("schemaVersion") not in (None, 1):
        warnings.append("schemaVersion should be 1")

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


def get_default_brief(recommendation, business_name: str, industry: str):
    """Build a deterministic brief from a recommendation.
    Used as cold-start path AND as fallback when LLM expansion fails.
    """
    from studio_strands import get_strand
    from studio_strand_fonts import resolve_font_pair

    a_id = recommendation.get("strand_a_id", "minimal")
    b_id = recommendation.get("strand_b_id", "editorial")
    ratio_a = recommendation.get("ratio_a", 60)
    ratio_b = recommendation.get("ratio_b", 40)
    sub_strand_id = recommendation.get("sub_strand_id")
    archetype = recommendation.get("layout_archetype", "split")
    accent_style = recommendation.get("accent_style", "editorial")
    site_type = recommendation.get("site_type", "full-site")

    strand_a = get_strand(a_id) or {}
    strand_b = get_strand(b_id) or {}
    fonts = resolve_font_pair(a_id, b_id, ratio_a)

    # Default palette from strand A swatches
    swatches_a = strand_a.get("swatches", ["#000000", "#ffffff", "#888888", "#cccccc"])
    palette = [
        {"hex": swatches_a[0], "name": "Background", "role": "background"},
        {"hex": swatches_a[1] if len(swatches_a) > 1 else "#FFFFFF", "name": "Surface", "role": "secondary"},
        {"hex": swatches_a[2] if len(swatches_a) > 2 else "#888888", "name": "Accent", "role": "accent"},
        {"hex": swatches_a[3] if len(swatches_a) > 3 else "#CCCCCC", "name": "Text", "role": "text"},
        {"hex": "#FFFFFF", "name": "Highlight", "role": "highlight"},
    ]

    return {
        "conceptName": f"{strand_a.get('name', a_id)} x {strand_b.get('name', b_id)}",
        "tagline": business_name or "Welcome",
        "blendRatio": f"{ratio_a}% {strand_a.get('name', a_id)} / {ratio_b}% {strand_b.get('name', b_id)}",
        "industry": industry or "custom",
        "mood": "Considered, intentional, designed",
        "tensionStatement": f"{strand_a.get('name', a_id)} structure carries {strand_b.get('name', b_id)} energy.",
        "philosophy": f"This direction blends the spatial logic of {strand_a.get('name', a_id)} with the {strand_b.get('name', b_id)} strand's {strand_b.get('desc', 'character')}.",
        "copyVoice": "Clear, direct, intentional.",
        "animationCharacter": "Restrained. Reveals, not animations.",
        "imageApproach": "Photographic. High contrast. Honest.",
        "spatialDirection": strand_a.get("spatialDNA", "Asymmetry is structural; negative space carries weight.") or "Asymmetry is structural.",
        "palette": palette,
        "colorDiscipline": {
            "accentRule": "Accent color appears once per section, never decoratively.",
            "ctaColor": swatches_a[2] if len(swatches_a) > 2 else "#888888",
            "maxAccentPerSection": 1,
            "neutralUsage": "Neutral colors carry the structure.",
        },
        "colorSource": {
            "hexAnchors": [],
            "colorNames": [],
            "interpretedColors": [],
            "fullyGenerated": True,
            "summary": "Generated from strand defaults (no client colors specified).",
        },
        "typography": {
            "display": {"name": fonts["display"], "weight": "700", "usage": "Hero headlines, section titles"},
            "body": {"name": fonts["body"], "weight": "400", "usage": "Paragraphs, descriptions"},
            "accent": {"name": fonts["accent"], "weight": "500", "usage": "Labels, captions, nav"},
        },
        "sections": [
            {"name": "Hero", "layout": "full-bleed", "designNote": "Establish presence", "copyDirection": "Strong opening, intentional pause", "ctaText": "Begin", "layoutType": "hero"},
            {"name": "About", "layout": "split", "designNote": "Practitioner identity", "copyDirection": "First-person, direct", "ctaText": None, "layoutType": "split"},
            {"name": "Offerings", "layout": "grid", "designNote": "Services or products", "copyDirection": "Specific, named, priced where appropriate", "ctaText": "Learn more", "layoutType": "grid"},
            {"name": "Process", "layout": "centered", "designNote": "How working together unfolds", "copyDirection": "Sequential, ceremonial", "ctaText": None, "layoutType": "list"},
            {"name": "Closing", "layout": "centered", "designNote": "Final call", "copyDirection": "Direct invitation", "ctaText": "Begin", "layoutType": "centered"},
        ],
        "layoutArchetype": archetype,
        "siteType": site_type,
        "accentConfig": {
            "style": accent_style,
            "primaryAccentType": "divider",
            "dividerStyle": "thin-rule",
            "hasTexture": False,
            "hasWatermark": False,
            "symbolStyle": "minimal",
            "opacity": 0.08,
        },
        "subStrandId": sub_strand_id,
        "buildNotes": "Deterministic default brief. Generated without LLM expansion.",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "schemaVersion": 1,
    }
