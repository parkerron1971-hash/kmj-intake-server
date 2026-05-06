"""Decoration scheme: JSON contract between AI generation and layout rendering.

A decoration scheme overrides Pass 3.7/3.7b deterministic decoration with
per-business unique values. Schema is strict; invalid fields rejected.
"""
from __future__ import annotations
from typing import TypedDict, Optional, Literal
import re


class ColorTokens(TypedDict, total=False):
    bg: str
    bg2: str
    bg3: str
    accent: str
    accent_secondary: Optional[str]
    text: str
    muted: str
    line: str


class Typography(TypedDict, total=False):
    font_display: str
    font_body: str
    font_accent: str
    h1_size: str
    h1_letter_spacing: str
    h2_size: str
    eyebrow_letter_spacing: str


class SpatialDNA(TypedDict, total=False):
    section_x: str
    section_y: str
    container_width: str


class Decorations(TypedDict, total=False):
    section_divider_style: Literal[
        "gold-rule-diamond",
        "double-hairline",
        "ornamental",
        "geometric",
        "organic",
        "thin-line",
        "minimal",
    ]
    accent_style: Literal[
        "ceremonial",
        "cinematic",
        "editorial",
        "cultural-african",
        "botanical",
        "structural",
    ]
    watermark_motif: Optional[str]
    corner_treatment: Literal["thin-gold", "soft-glow", "geometric", "none"]
    strand: Literal["dark", "light", "warm", "cool"]


class MotionRichness(TypedDict, total=False):
    enable_ghost_numbers: bool
    enable_marquee_strips: bool
    enable_magnetic_buttons: bool
    enable_statement_bars: bool
    stagger_delays: list
    parallax_backgrounds: bool


class DecorationScheme(TypedDict, total=False):
    schema_version: int
    generated_at: str
    color_tokens: ColorTokens
    typography: Typography
    spatial_dna: SpatialDNA
    decorations: Decorations
    motion_richness: MotionRichness
    marquee_text: Optional[str]
    statement_bar_quotes: list


VALID_DIVIDER_STYLES = {
    "gold-rule-diamond", "double-hairline", "ornamental", "geometric",
    "organic", "thin-line", "minimal",
}
VALID_ACCENT_STYLES = {
    "ceremonial", "cinematic", "editorial", "cultural-african",
    "botanical", "structural",
}
VALID_CORNER_TREATMENTS = {"thin-gold", "soft-glow", "geometric", "none"}
VALID_STRANDS = {"dark", "light", "warm", "cool"}


HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
CLAMP_RE = re.compile(
    r"^clamp\(\s*[\d.]+(?:rem|px|em|vh|vw),\s*[\d.]+(?:rem|px|em|vh|vw),\s*[\d.]+(?:rem|px|em|vh|vw)\s*\)$"
)
SIMPLE_SIZE_RE = re.compile(r"^[\d.]+(?:rem|px|em|vh|vw)$")


def validate_color(value) -> bool:
    return isinstance(value, str) and bool(HEX_COLOR_RE.match(value))


def validate_clamp_or_simple_size(value) -> bool:
    if not isinstance(value, str):
        return False
    if CLAMP_RE.match(value):
        return True
    return bool(SIMPLE_SIZE_RE.match(value))


def validate_decoration_scheme(scheme):
    """Validate a decoration scheme. Returns (is_valid, error_message)."""
    if not isinstance(scheme, dict):
        return False, "Scheme must be a dict"

    if scheme.get("schema_version") != 1:
        return False, "schema_version must be 1"

    color_tokens = scheme.get("color_tokens", {})
    if color_tokens:
        for key in ("bg", "bg2", "bg3", "accent", "accent_secondary", "text", "muted"):
            if key in color_tokens and not validate_color(color_tokens[key]):
                return False, f"Invalid color in color_tokens.{key}: {color_tokens[key]}"

    decorations = scheme.get("decorations", {})
    if decorations:
        if "section_divider_style" in decorations and decorations["section_divider_style"] not in VALID_DIVIDER_STYLES:
            return False, "Invalid section_divider_style"
        if "accent_style" in decorations and decorations["accent_style"] not in VALID_ACCENT_STYLES:
            return False, "Invalid accent_style"
        if "corner_treatment" in decorations and decorations["corner_treatment"] not in VALID_CORNER_TREATMENTS:
            return False, "Invalid corner_treatment"
        if "strand" in decorations and decorations["strand"] not in VALID_STRANDS:
            return False, "Invalid strand"

    typography = scheme.get("typography", {})
    if typography:
        for size_key in ("h1_size", "h2_size"):
            if size_key in typography and not validate_clamp_or_simple_size(typography[size_key]):
                return False, f"Invalid typography.{size_key}: must be clamp() or simple size"

    spatial = scheme.get("spatial_dna", {})
    if spatial:
        for key in ("section_x", "section_y"):
            if key in spatial and not validate_clamp_or_simple_size(spatial[key]):
                return False, f"Invalid spatial_dna.{key}"

    motion = scheme.get("motion_richness", {})
    if motion:
        for bool_key in (
            "enable_ghost_numbers", "enable_marquee_strips",
            "enable_magnetic_buttons", "enable_statement_bars",
            "parallax_backgrounds",
        ):
            if bool_key in motion and not isinstance(motion[bool_key], bool):
                return False, f"motion_richness.{bool_key} must be boolean"
        if "stagger_delays" in motion:
            delays = motion["stagger_delays"]
            if not isinstance(delays, list) or not all(
                isinstance(d, (int, float)) and 0 <= d <= 2 for d in delays
            ):
                return False, "stagger_delays must be list of numbers 0-2"

    quotes = scheme.get("statement_bar_quotes", [])
    if not isinstance(quotes, list) or len(quotes) > 5:
        return False, "statement_bar_quotes must be list with at most 5 items"
    for q in quotes:
        if not isinstance(q, str) or len(q) > 200:
            return False, "Each statement bar quote must be string under 200 chars"

    if "marquee_text" in scheme:
        mt = scheme["marquee_text"]
        if mt is not None and (not isinstance(mt, str) or len(mt) > 500):
            return False, "marquee_text must be string under 500 chars or null"

    return True, ""


def get_default_scheme(vocab_id=None):
    """Return a sensible default scheme. Used as fallback when no generated scheme exists."""
    return {
        "schema_version": 1,
        "color_tokens": {},
        "typography": {},
        "spatial_dna": {},
        "decorations": {
            "section_divider_style": "thin-line",
            "accent_style": "editorial",
            "corner_treatment": "none",
            "strand": "light",
        },
        "motion_richness": {
            "enable_ghost_numbers": False,
            "enable_marquee_strips": False,
            "enable_magnetic_buttons": False,
            "enable_statement_bars": False,
            "stagger_delays": [0.08, 0.16, 0.24, 0.32],
            "parallax_backgrounds": False,
        },
        "marquee_text": None,
        "statement_bar_quotes": [],
    }


def safe_read(scheme, path, default=None):
    """Safely read a nested path from scheme. Returns default on any failure.
    path: dot-separated, e.g. 'color_tokens.accent'
    """
    if not scheme or not isinstance(scheme, dict):
        return default
    try:
        node = scheme
        for key in path.split("."):
            if not isinstance(node, dict):
                return default
            if key not in node:
                return default
            node = node[key]
        return node
    except Exception:
        return default
