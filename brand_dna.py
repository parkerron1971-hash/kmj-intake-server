"""
brand_dna.py — Arc 26 PR1 — deterministic Brand DNA interpreter.

Reads the Brand Engine bundle (brand_engine.get_bundle) and derives the
full design-token set the section module library renders from: derived
palette (surfaces, tints, borders, on-colors — all contrast-checked),
type scale, spacing rhythm, radius language, motion level, accent style.

Design stance (Arc 26 ruling): the LLM never writes HTML or CSS. All
visual derivation is color/typography MATH here, so every output is
legible and on-brand by construction. Creativity enters through the
variation space (these tokens × module expression variants × page
composition), not through generation randomness.

Pure functions, no I/O except build_brand_dna()'s bundle fetch.
"""
from __future__ import annotations

import colorsys
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Color math ───────────────────────────────────────────────────────

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def _parse_hex(value: Optional[str]) -> Optional[Tuple[float, float, float]]:
    """#rrggbb / #rgb → (r, g, b) in 0..1, or None if unparseable."""
    if not value:
        return None
    m = _HEX_RE.match(str(value).strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _to_hex(rgb: Tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def _hls(hex_color: str) -> Tuple[float, float, float]:
    rgb = _parse_hex(hex_color) or (0.5, 0.5, 0.5)
    return colorsys.rgb_to_hls(*rgb)


def _from_hls(h: float, l: float, s: float) -> str:
    return _to_hex(colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s))))


def _luminance(hex_color: str) -> float:
    """WCAG relative luminance."""
    rgb = _parse_hex(hex_color) or (0.5, 0.5, 0.5)
    chan = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _shift_l(hex_color: str, delta: float) -> str:
    h, l, s = _hls(hex_color)
    return _from_hls(h, l + delta, s)


def _with_l(hex_color: str, l: float) -> str:
    h, _, s = _hls(hex_color)
    return _from_hls(h, l, s)


def _ensure_contrast(fg: str, bg: str, minimum: float = 4.5) -> str:
    """Nudge fg lightness away from bg until WCAG contrast holds."""
    if _contrast(fg, bg) >= minimum:
        return fg
    step = 0.06 if _luminance(bg) < 0.5 else -0.06
    out = fg
    for _ in range(12):
        out = _shift_l(out, step)
        if _contrast(out, bg) >= minimum:
            return out
    return "#f5f4f0" if _luminance(bg) < 0.5 else "#15130e"


def _on_color(bg: str) -> str:
    """Black-ish or white-ish, whichever reads better on bg."""
    return "#101010" if _contrast("#101010", bg) >= _contrast("#fafafa", bg) else "#fafafa"


# ─── Vibe-keyed defaults (used only for fields the brand kit lacks) ───

_VIBE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "warm":   {"bg": "#171310", "accent": "#d99a4e", "fonts": ("Fraunces", "Source Sans 3")},
    # B5 (2026-07-18): formal was cold-steel-blue on dark blue-charcoal —
    # doctrine D11's banned "cold blue on dark" smell, handed to EVERY
    # kit-less formal business as the default. Now a warm ink ground with
    # a muted brass accent (distinct from warm's orange and bold's gold).
    "formal": {"bg": "#141210", "accent": "#c9a96a", "fonts": ("Libre Caslon Text", "Inter")},
    "bold":   {"bg": "#0a0a0a", "accent": "#e8c15a", "fonts": ("Bricolage Grotesque", "Inter")},
}

_INTENSITY_ORDER = ("restrained", "confident", "bold")


# ─── Typography range (Arc 3 "Expressive Range") ──────────────────────
# One distinct, vetted Google-font pairing per DRO display personality —
# chosen like a type director: display faces categorically distinct,
# body faces genuinely readable. wmin/wmax clamp --sx-heading-weight to
# the weights the face actually ships (no faux-bold synthesis on
# weight-locked display faces like Anton / Archivo Black), `letter`
# overrides letter-spacing where the face wants it.
FONT_PAIRINGS: Dict[str, Dict[str, Any]] = {
    "editorial_serif":    {"heading": "Fraunces", "body": "Source Sans 3", "wmax": 900},
    "heritage":           {"heading": "Libre Caslon Text", "body": "Lora", "wmax": 700},
    "modern_grotesque":   {"heading": "Space Grotesk", "body": "Inter", "wmax": 700},
    "warm_humanist":      {"heading": "Bricolage Grotesque", "body": "Nunito Sans", "wmax": 800},
    "bold_statement":     {"heading": "Archivo Black", "body": "Archivo", "wmax": 400, "letter": "-0.01em"},
    "storyteller":        {"heading": "Newsreader", "body": "Source Sans 3", "wmax": 700},
    "quiet_luxury":       {"heading": "Cormorant Garamond", "body": "Outfit", "wmin": 500, "wmax": 600, "letter": "0.01em"},
    "technical_precise":  {"heading": "IBM Plex Mono", "body": "IBM Plex Sans", "wmax": 600, "letter": "0em"},
    "playful":            {"heading": "Baloo 2", "body": "Karla", "wmax": 800},
    "condensed_impact":   {"heading": "Anton", "body": "Barlow", "wmax": 400, "letter": "0em"},
    "expressive_display": {"heading": "Syne", "body": "Manrope", "wmax": 800},
}

# Design audit P2 (2026-07-18) — THE THIRD TYPE ROLE. Pairings whose
# display face has no usable italic-serif axis get a distinct accent
# face for editorial moments (the italic accent word, pull-quotes,
# eyebrow flourishes). Serif-headed pairings use their own heading
# italics — accent defaults to the heading face.
# P3 widening (2026-07-18): all six used to collapse onto Playfair
# Display — every sans-display site shared one italic voice, a template
# tell. Now five distinct editorial italics, cast against the display
# face's character (a didone against the black grotesque, Plex Serif
# inside the Plex superfamilies, Merriweather's round sturdiness for
# the playful face).
ACCENT_FACES: Dict[str, str] = {
    "condensed_impact":   "Cormorant Garamond",
    "bold_statement":     "Playfair Display",
    "expressive_display": "Lora",
    "modern_grotesque":   "IBM Plex Serif",
    "technical_precise":  "IBM Plex Serif",
    "playful":            "Merriweather",
}

# Hybrid font selection (Kevin's ruling): the practitioner's style
# pick (interview type_personality) CONSTRAINS the pairing family;
# the DRO still applies taste within it. brand_fonts pins the kit.
TYPE_PERSONALITY_PAIRINGS: Dict[str, list] = {
    "statement":      ["condensed_impact", "bold_statement", "expressive_display"],
    "editorial":      ["editorial_serif", "storyteller", "quiet_luxury"],
    "modern_minimal": ["modern_grotesque", "technical_precise"],
    "classic":        ["heritage", "quiet_luxury", "editorial_serif"],
    "handcrafted":    ["warm_humanist", "playful"],
}

# DRO schema enums map exactly; prose-ish labels resolve by keyword.
_PAIRING_EXACT = {
    "editorial_serif": "editorial_serif",
    "grotesque_bold": "bold_statement",
    "humanist_warm": "warm_humanist",
    "geometric_precise": "modern_grotesque",
    "expressive_display": "expressive_display",
    "condensed_impact": "condensed_impact",
}

# Arc B (2026-07-21, the Anton-on-a-luxury-page defect): order IS the
# tie-break. A DRO that writes "condensed editorial display" used to
# resolve condensed_impact because the impact families sat above the
# refined ones — the live editorial-luxury build shipped Anton for every
# heading. Refined/serif-led families now match FIRST, so any mixed
# description resolves toward refinement; pure impact language
# ("brutal", "poster") still lands on the impact faces unambiguously.
_PAIRING_FUZZY = (
    ("quiet_luxury", ("quiet", "luxur", "elegant", "refined", "understated", "discreet")),
    ("heritage", ("heritage", "classic", "traditional", "timeless")),
    ("editorial_serif", ("editorial", "serif", "magazine", "literati")),
    ("storyteller", ("story", "narrat", "literary", "book")),
    ("technical_precise", ("technical", "precis", "mono", "engineer", "system")),
    ("warm_humanist", ("humanist", "warm", "human", "approachable", "welcom",
                       "calm", "serene", "sooth", "gentle", "grounded")),
    ("playful", ("playful", "fun", "round", "friendly", "joy", "whimsic")),
    ("condensed_impact", ("condensed", "compact", "poster", "impact")),
    ("bold_statement", ("bold", "brutal", "loud", "statement", "commanding", "heavy", "black")),
    ("expressive_display", ("expressive", "artistic", "creative", "eccentric", "display")),
    ("modern_grotesque", ("grotesque", "modern", "geometric", "minimal", "clean", "tech")),
)


# Arc M (2026-07-10) — the field study's #1 tell: generic faces used as
# DISPLAY type. These are fine as body faces; as headings they read as
# template output. When a brand kit carries one of these as the heading
# font WITHOUT fonts_locked, the composer demotes the pin and lets the
# pairing system (above) dress the page instead.
GENERIC_DISPLAY_FACES = {
    "inter", "open sans", "roboto", "lato", "montserrat", "arial",
    "helvetica", "helvetica neue", "verdana", "tahoma", "segoe ui",
    "system-ui", "sans-serif",
}


def is_generic_display(font_name: Any) -> bool:
    """True when `font_name` is too generic to serve as a display face."""
    return str(font_name or "").strip().lower() in GENERIC_DISPLAY_FACES


# ── COLOR WORDS AS SEEDS (2026-07-23, adopted from Kevin's Studio) ────
# Owners describe colors three ways: exact hex (used verbatim — already
# handled by colors.love), NAMED colors ("navy and gold"), or FEELINGS
# ("warm and earthy"). Names resolve through a variant lens — a rich/
# deep navy is not a bright corporate navy — chosen from modifier words
# in the same phrase. Deterministic, rubric not lookup: unknown words
# simply contribute nothing (fail-open to today's behavior).
_NAMED_COLORS: Dict[str, Dict[str, str]] = {
    #        default     deep/luxury  warm        bright
    "navy":      {"d": "#1f3a5f", "x": "#141f38", "w": "#27456d", "b": "#2456a4"},
    "blue":      {"d": "#2a6bb0", "x": "#1b3a5e", "w": "#3d7ab5", "b": "#2f88e0"},
    "gold":      {"d": "#c79d26", "x": "#a67c1a", "w": "#d4a940", "b": "#e8b830"},
    "green":     {"d": "#2f7d4f", "x": "#1f4d36", "w": "#4c7a51", "b": "#29d665"},
    "sage":      {"d": "#8a9a7b", "x": "#68785c", "w": "#9aa888", "b": "#a3b18a"},
    "emerald":   {"d": "#199761", "x": "#0f6b45", "w": "#2aa06d", "b": "#17c27a"},
    "red":       {"d": "#c0392b", "x": "#7e1f1f", "w": "#c74a33", "b": "#e13b2f"},
    "burgundy":  {"d": "#6e1f33", "x": "#4e1524", "w": "#7d2c3e", "b": "#8e2743"},
    "purple":    {"d": "#6d4b9e", "x": "#42306b", "w": "#7d5aa5", "b": "#8b5cf6"},
    "lavender":  {"d": "#a48fd0", "x": "#7f6ab0", "w": "#b09cd8", "b": "#b8a5ec"},
    "teal":      {"d": "#1f7a83", "x": "#14555c", "w": "#2c868c", "b": "#14b8c4"},
    "black":     {"d": "#141414", "x": "#0a0a0a", "w": "#1c1814", "b": "#202020"},
    "white":     {"d": "#f5f2ec", "x": "#efe9df", "w": "#f7f1e6", "b": "#ffffff"},
    "cream":     {"d": "#efe6d4", "x": "#e5d8bf", "w": "#f2e8d2", "b": "#f7efdd"},
    "brown":     {"d": "#6d4c33", "x": "#4b3221", "w": "#7a5638", "b": "#8a5a2c"},
    "tan":       {"d": "#c9a97e", "x": "#a9885e", "w": "#d2b088", "b": "#dcbd92"},
    "terracotta": {"d": "#b5541c", "x": "#8e3f13", "w": "#c06026", "b": "#d0642a"},
    "pink":      {"d": "#d16b96", "x": "#a94b74", "w": "#d87ba0", "b": "#f472b6"},
    "blush":     {"d": "#e6b8b8", "x": "#cf9b9b", "w": "#ecc4bf", "b": "#f4cccc"},
    "orange":    {"d": "#d97a2b", "x": "#a95c1c", "w": "#e08636", "b": "#f97316"},
    "yellow":    {"d": "#d9b32b", "x": "#ac8c1d", "w": "#e0bd3d", "b": "#facc15"},
    "gray":      {"d": "#6f7680", "x": "#4a4f57", "w": "#7d7a72", "b": "#9aa1ab"},
    "grey":      {"d": "#6f7680", "x": "#4a4f57", "w": "#7d7a72", "b": "#9aa1ab"},
    "charcoal":  {"d": "#33373d", "x": "#24272c", "w": "#3a3733", "b": "#42474f"},
    "olive":     {"d": "#6b6b35", "x": "#4c4c26", "w": "#787840", "b": "#8a8a3d"},
}
_FEELING_SEEDS: Dict[str, str] = {
    "warm": "#b5541c", "earth": "#7a5c3e", "moody": "#232733",
    "airy": "#dfe7ee", "calm": "#5b7c99", "bold": "#c8102e",
    "fresh": "#2f9e6e", "rich": "#5c2a3d", "luxur": "#0f1b2d",
    "sunny": "#e8a13a", "ocean": "#1b6f8a", "forest": "#1f4d36",
    "royal": "#3b2a6d", "minimal": "#1a1a1a", "soft": "#e9dfd6",
}


def interpret_color_words(words: Any) -> List[str]:
    """'navy and gold' / 'warm and earthy' → up to 3 seed hexes that ride
    colors.love downstream (anchors, not rules — derive_palette still
    designs the supporting cast). Modifier words in the phrase pick the
    variant: deep/dark/rich/luxur → x, warm/earth → w,
    bright/vibrant/bold/neon → b, else default."""
    s = str(words or "").lower()
    if not s.strip():
        return []
    variant = "d"
    if any(m in s for m in ("deep", "dark", "rich", "luxur", "elegant")):
        variant = "x"
    elif any(m in s for m in ("bright", "vibrant", "neon", "electric", "bold")):
        variant = "b"
    elif any(m in s for m in ("warm", "earth", "cozy", "golden")):
        variant = "w"
    seeds: List[str] = []
    for name, variants in _NAMED_COLORS.items():
        if name in s and len(seeds) < 3:
            hexv = variants.get(variant, variants["d"])
            if hexv not in seeds:
                seeds.append(hexv)
    if not seeds:
        for feel, hexv in _FEELING_SEEDS.items():
            if feel in s and len(seeds) < 2 and hexv not in seeds:
                seeds.append(hexv)
    return seeds


def resolve_font_pairing(display_personality: Any) -> Optional[str]:
    """DRO typography.display_personality (schema enum OR prose-ish
    label) → FONT_PAIRINGS key, or None when nothing matches."""
    s = str(display_personality or "").strip().lower()
    if not s:
        return None
    if s in _PAIRING_EXACT:
        return _PAIRING_EXACT[s]
    for key, words in _PAIRING_FUZZY:
        if any(w in s for w in words):
            return key
    return None


def _seed_int(business_id: str, salt: str = "") -> int:
    """Stable per-business seed so derivation is deterministic but
    distinct across businesses (no two brands share tie-break choices)."""
    return int(hashlib.sha256(f"{business_id}:{salt}".encode()).hexdigest()[:8], 16)


def _infer_vibe(bundle: Dict[str, Any]) -> str:
    design = bundle.get("design") or {}
    fam = (design.get("vibe_family") or "").lower()
    if fam in _VIBE_DEFAULTS:
        return fam
    tone_words = " ".join(
        (bundle.get("voice") or {}).get("tone_words") or []
        if isinstance((bundle.get("voice") or {}).get("tone_words"), list)
        else [str((bundle.get("voice") or {}).get("tone_words") or "")]
    ).lower()
    if any(w in tone_words for w in ("warm", "welcom", "ministry", "community", "nurtur")):
        return "warm"
    if any(w in tone_words for w in ("bold", "edgy", "creative", "confident", "fearless")):
        return "bold"
    return "formal"


def _infer_intensity(bundle: Dict[str, Any], vibe: str) -> str:
    expr = ((bundle.get("design") or {}).get("creative_expression") or
            ((bundle.get("business") or {}).get("settings") or {}).get("creative_expression") or {})
    level = (expr.get("intensity") or "").lower()
    if level in _INTENSITY_ORDER:
        return level
    return {"warm": "confident", "formal": "restrained", "bold": "bold"}[vibe]


# ─── Owner color-language steering (Smart Sites Arc 5) ────────────────
# site_prefs.colors {use_brand, love[], avoid[]} nudges ACCENT derivation
# deterministically: a fixed word→hue map (hex passthrough), an avoid-
# family rotation, and use_brand=False dropping brand-kit colors from
# accent derivation. WCAG enforcement downstream is untouched — the
# steered accent flows through the same _ensure_contrast/_on_color math.

_COLOR_WORDS: Dict[str, str] = {
    "terracotta": "#c56a4a", "turquoise": "#3ab0a2", "burgundy": "#6d2331",
    "charcoal": "#3a3a3c", "lavender": "#b19cd9", "mustard": "#d4a017",
    "emerald": "#2e8b57", "magenta": "#c2185b", "crimson": "#a51c30",
    "forest": "#2c5f2d", "indigo": "#3f51b5", "violet": "#7f3fbf",
    "maroon": "#701c1c", "salmon": "#e8907e", "copper": "#b87333",
    "bronze": "#a97142", "silver": "#a8a9ad", "purple": "#7d5ba6",
    "orange": "#e07b39", "yellow": "#e8c15a", "coral": "#e2725b",
    "olive": "#7a7d3a", "blush": "#e8b4b8", "peach": "#f2b380",
    "cream": "#f2e8d5", "beige": "#d9c7a7", "brown": "#7a5c43",
    "black": "#1a1a1a", "white": "#f7f5f0", "green": "#3f7d4e",
    "sage": "#9caf88", "rust": "#b7410e", "navy": "#1f3a5f",
    "teal": "#2a7f7f", "gold": "#d4af37", "pink": "#d98ca0",
    "blue": "#3a6ea5", "grey": "#8a8a8e", "gray": "#8a8a8e",
    "rose": "#c96f7b", "plum": "#8e4585", "mint": "#98d7c2",
    "sky": "#7ab8d9", "red": "#b0413e", "tan": "#c9a97a",
}
_HUE_FAMILY_DEG = 30.0     # ± window that counts as "the same hue family"
_NEUTRAL_SAT = 0.14        # HSV saturation floor below which a color is neutral


def pref_color_to_hex(token: Any) -> Optional[str]:
    """One owner color token ('sage', 'sage green', '#9caf88') → hex.
    Earliest word match wins (longer name on a tie) so 'sage green'
    resolves to sage, the specific modifier, not green."""
    s = str(token or "").strip().lower()
    if not s:
        return None
    rgb = _parse_hex(s)
    if rgb:
        return _to_hex(rgb)
    best: Optional[Tuple[Tuple[int, int], str]] = None
    for word in _COLOR_WORDS:
        i = s.find(word)
        if i >= 0 and (best is None or (i, -len(word)) < best[0]):
            best = ((i, -len(word)), word)
    return _COLOR_WORDS[best[1]] if best else None


def _hue_sat(hex_color: str) -> Tuple[float, float]:
    """(hue 0..1, HSV saturation). HSV — not HLS — saturation, which
    would read near-white creams as fully saturated."""
    import colorsys
    rgb = _parse_hex(hex_color) or (0.5, 0.5, 0.5)
    h, s, _v = colorsys.rgb_to_hsv(*rgb)
    return h, s


def _in_hue_family(candidate: str, avoid_hexes: List[str]) -> bool:
    """True when `candidate` lands in any avoided hue family. Neutral
    avoids (charcoal/gray/...) match neutral candidates by saturation."""
    ch, cs = _hue_sat(candidate)
    for av in avoid_hexes:
        ah, as_ = _hue_sat(av)
        if as_ < _NEUTRAL_SAT:
            if cs < _NEUTRAL_SAT:
                return True
            continue
        if cs < _NEUTRAL_SAT:
            continue
        dh = abs(ch - ah)
        dh = min(dh, 1.0 - dh) * 360.0
        if dh <= _HUE_FAMILY_DEG:
            return True
    return False


def _steer_accent(accent: str, love_hexes: List[str], avoid_hexes: List[str],
                  fallback: str) -> str:
    """Avoid-family rotation: when the derived accent lands in an avoided
    hue family, rotate to the next candidate (loved colors first, then the
    vibe default, then 60° hue rotations of the accent itself)."""
    if not avoid_hexes or not _in_hue_family(accent, avoid_hexes):
        return accent
    h, l, s = _hls(accent)
    rotations = [_from_hls((h + step / 360.0) % 1.0, l, max(s, 0.35))
                 for step in (60, 120, 180, 240, 300)]
    for cand in [*love_hexes, fallback, *rotations]:
        if cand and _parse_hex(cand) and not _in_hue_family(cand, avoid_hexes):
            return cand
    return accent      # everything is avoided — owner contradiction, keep


# ─── Token derivation ─────────────────────────────────────────────────

def derive_palette(design: Dict[str, Any], vibe: str, business_id: str,
                   color_prefs: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Full surface/ink system from up to 5 brand colors. Dark- or
    light-mode is taken from the brand background's luminance.

    Arc 5: `color_prefs` (sanitized site_prefs.colors) steers the accent:
    use_brand=False ignores brand-kit colors for accent derivation, loved
    colors nudge accent choice when no brand accent applies, avoided hue
    families rotate the accent to the next candidate."""
    prefs = color_prefs if isinstance(color_prefs, dict) else {}
    ignore_brand = prefs.get("use_brand") is False
    love_hexes = [h for h in (pref_color_to_hex(t) for t in (prefs.get("love") or [])[:4]) if h]
    avoid_hexes = [h for h in (pref_color_to_hex(t) for t in (prefs.get("avoid") or [])[:4]) if h]

    defaults = _VIBE_DEFAULTS[vibe]
    bg = design.get("background_color") if _parse_hex(design.get("background_color")) else defaults["bg"]
    accent = design.get("accent_color") if _parse_hex(design.get("accent_color")) else None
    primary = design.get("primary_color") if _parse_hex(design.get("primary_color")) else None
    secondary = design.get("secondary_color") if _parse_hex(design.get("secondary_color")) else None
    text = design.get("text_color") if _parse_hex(design.get("text_color")) else None

    if ignore_brand:
        # Owner explicitly diverging from the brand kit for this site.
        accent = primary = secondary = None

    if (accent or primary) is None and love_hexes:
        accent = love_hexes[0]                  # loved color leads
    accent = accent or primary or defaults["accent"]
    accent = _steer_accent(accent, love_hexes, avoid_hexes, defaults["accent"])
    primary = primary or accent

    dark_mode = _luminance(bg) < 0.35
    lift = 0.05 if dark_mode else -0.04

    surface = _shift_l(bg, lift)                 # cards
    surface_2 = _shift_l(bg, lift * 1.9)         # raised / alternate bands
    text = text or ("#f2f0ea" if dark_mode else "#181614")
    text = _ensure_contrast(text, bg, 7.0)
    muted = _ensure_contrast(_shift_l(text, -0.22 if dark_mode else 0.22), bg, 4.5)
    border = _shift_l(bg, 0.10 if dark_mode else -0.10)

    palette = {
        "bg": bg,
        "surface": surface,
        "surface2": surface_2,
        "text": text,
        "muted": muted,
        "accent": accent,
        "primary": primary,
        # secondary intentionally raw here (may be None) — the accent-family
        # derivation seeds authority from the REAL brand secondary only;
        # the neutral surface_2 default is applied after.
        "secondary": secondary,
        "border": border,
    }
    palette = rederive_accent_family(palette)
    palette["secondary"] = secondary or surface_2
    return palette


def rederive_accent_family(palette: Dict[str, Any]) -> Dict[str, Any]:
    """Arc 9 boundary fix — derive (or RE-derive) every accent-family +
    authority color against the palette's CURRENT ground.

    Root cause of the live-site autopsy's worst finding: apply_dro_palette
    / apply_owner_ground swap the neutral ground (bg/surface/text/…) but
    used to keep the accent family derived against the ORIGINAL brand-kit
    ground — a light-kit accent_soft (#dff6e7 pale mint) survived onto a
    deep_dark page, accent_strong sat DARKER than the accent (backwards
    hover), and authority carried a maroon derived against a light bg.

    This is the single accent-family derivation both derive_palette and
    the ground-swap paths share. Every output is keyed on the CURRENT bg
    luminance; contrast enforcement is unchanged. Returns a new dict —
    input untouched."""
    p = dict(palette)
    bg = p.get("bg") if _parse_hex(p.get("bg")) else "#111111"
    accent = p.get("accent") if _parse_hex(p.get("accent")) else "#d99a4e"
    text = p.get("text") if _parse_hex(p.get("text")) else None
    dark_mode = _luminance(bg) < 0.35

    # Accent derivations — soft wash for chips/rules, strong for hovers.
    # Dark grounds: soft is a DARK tint, strong is LIGHTER than the accent
    # (hover moves toward the light); light grounds mirror.
    h, l, s = _hls(accent)
    p["accent_soft"] = _from_hls(h, (0.16 if dark_mode else 0.92), min(s, 0.55))
    p["accent_strong"] = _from_hls(h, l + (0.08 if dark_mode else -0.08), s)

    # Design audit P2 (2026-07-18) — THE SECOND ACCENT. Brand Studio
    # stores a secondary color and derive_palette carried it, but the
    # emitter dropped it: two-accent brands (gold + green) were
    # impossible by construction. When the secondary is genuinely
    # chromatic AND a different hue family than the accent, derive a
    # small family against the CURRENT ground. Neutral/near-accent
    # secondaries stay inactive — no accidental rainbow.
    p.pop("secondary_active", None)
    _sec = p.get("secondary") if _parse_hex(p.get("secondary")) else None
    if _sec:
        hs, ls, ss = _hls(_sec)
        _hue_gap = min(abs(hs - h), 1 - abs(hs - h)) * 360
        if ss > 0.18 and _hue_gap > 30:
            p["secondary_active"] = True
            p["secondary_soft"] = _from_hls(hs, (0.16 if dark_mode else 0.92), min(ss, 0.55))
            p["secondary_strong"] = _from_hls(hs, ls + (0.08 if dark_mode else -0.08), ss)

    # Quality-floor arc 7 — the full-bleed accent band made --sx-on-accent
    # a body-text surface, so its contrast is now ENFORCED (4.5), not just
    # best-of-two.
    p["on_accent"] = _ensure_contrast(_on_color(accent), accent, 4.5)

    # AUTHORITY band (quality-floor arc 7): the deep chapter-break surface —
    # the role navy played in the original bar. Light grounds: the darkest
    # brand color pulled deep (hue kept, lightness ~0.13). Dark grounds: a
    # deeper-still accent-tinted tone so the band still reads as a distinct
    # chapter. Inks are contrast-enforced like every other pair; the accent
    # gets its own on-authority variant (3:1 — headings/marks scale).
    if dark_mode:
        bg_l = _hls(bg)[1]
        authority = _from_hls(h, min(max(bg_l - 0.04, 0.03), 0.10),
                              min(s * 0.5, 0.32))
    else:
        cands = [c for c in (p.get("primary"), p.get("secondary"), accent)
                 if c and _parse_hex(c)]
        seed_color = min(cands, key=_luminance) if cands else (text or "#15130e")
        hh, _ll, ss = _hls(seed_color)
        authority = _from_hls(hh, 0.13, max(min(ss, 0.75), 0.25))
    p["authority"] = authority
    p["on_authority"] = _ensure_contrast(
        "#f4f0e8" if _luminance(authority) < 0.5 else "#15130e", authority, 4.5)
    p["accent_on_authority"] = _ensure_contrast(accent, authority, 3.0)

    # Arc 9 fix 8 — ACCENT CHROMA GOVERNOR: a large-area variant of the
    # accent for full-bleed fills (cta_band / statband grounds). A raw
    # S=1.0 neon accent is a fine 18px CTA pill and a blinding 300px band.
    p["accent_ground"] = _govern_accent(accent, bg)
    p["on_accent_ground"] = _ensure_contrast(
        _on_color(p["accent_ground"]), p["accent_ground"], 4.5)

    p["mode"] = "dark" if dark_mode else "light"
    return p


# Brand fidelity (2026-07-14, Kevin): the practitioner's brand color should
# be the color the site builds from. The large-fill governor now barely
# touches it — a light guard against pure S=1.0 neon on a 300px band, not a
# mute. (Small ink already uses the exact brand accent; this brings the big
# color bands close to it too.)
_ACCENT_GROUND_SAT_CAP = 0.88     # HSV saturation ceiling for large fills (was .72)
_ACCENT_GROUND_PULL = 0.18        # how far lightness moves toward comfort (was .35)


def _govern_accent(accent: str, bg: str) -> str:
    """Large-area accent: HLS lightness pulled part-way toward the
    ground's comfort zone (dark grounds want a deeper band, light
    grounds a calmer mid), THEN HSV saturation capped at
    _ACCENT_GROUND_SAT_CAP — cap last, because a lightness move
    re-inflates HSV saturation. Small ink keeps the raw --sx-accent;
    only full-bleed fills use this."""
    h, l, s = _hls(accent if _parse_hex(accent) else "#d99a4e")
    target_l = 0.42 if _luminance(bg) < 0.35 else 0.52
    pulled = _from_hls(h, l + (target_l - l) * _ACCENT_GROUND_PULL, s)
    rgb = _parse_hex(pulled) or (0.5, 0.5, 0.5)
    hh, ss, vv = colorsys.rgb_to_hsv(*rgb)
    return _to_hex(colorsys.hsv_to_rgb(hh, min(ss, _ACCENT_GROUND_SAT_CAP), vv))


def derive_typography(design: Dict[str, Any], vibe: str, intensity: str) -> Dict[str, Any]:
    defaults = _VIBE_DEFAULTS[vibe]["fonts"]
    heading = (design.get("font_heading") or "").strip() or defaults[0]
    body = (design.get("font_body") or "").strip() or defaults[1]
    expr = (design.get("creative_expression") or {})
    if (expr.get("hero_font") or "").strip():
        heading = expr["hero_font"].strip()

    # Quality-floor arc 7 — DISPLAY FLOORS from the original bar
    # (cinematic_authority_intelligence.md §3): confident is the default
    # bar — h1 clamp(3.7rem, 9vw, 5.4rem) w900 / h2 clamp(2.4rem, 5vw,
    # 3.5rem) w800. Restrained stays a deliberate step down but its h1
    # min rises to 3.2rem; bold sits a step above confident.
    h1 = {"restrained": "clamp(3.2rem, 5.5vw, 4.2rem)",
          "confident": "clamp(3.7rem, 9vw, 5.4rem)",
          "bold": "clamp(3.9rem, 9.5vw, 6.4rem)"}[intensity]
    h2 = {"restrained": "clamp(1.9rem, 3.2vw, 2.6rem)",
          "confident": "clamp(2.4rem, 5vw, 3.5rem)",
          "bold": "clamp(2.6rem, 5.4vw, 3.8rem)"}[intensity]
    weight = {"restrained": 700, "confident": 900, "bold": 900}[intensity]
    h2_weight = {"restrained": 700, "confident": 800, "bold": 900}[intensity]
    # Site quality (2026-07-14): fill the missing scale rungs. The scale
    # used to jump h2 (huge) → body (flat 16.5px) with nothing between; h3,
    # a lead size and a caption size give real hierarchy (a ~1.25 ratio
    # modular feel) so sections read as designed, not just big-then-small.
    h3 = {"restrained": "clamp(1.3rem, 2.1vw, 1.6rem)",
          "confident": "clamp(1.4rem, 2.5vw, 1.8rem)",
          "bold": "clamp(1.5rem, 2.7vw, 1.95rem)"}[intensity]
    return {
        "heading": heading,
        "body": body,
        "h1": h1, "h2": h2, "h3": h3,
        "lead": "clamp(1.1rem, 1.6vw, 1.3rem)",   # intro / lead paragraphs
        "small": "0.82rem",                        # captions / fine print
        "heading_weight": weight,
        "h2_weight": h2_weight,
        "h3_weight": {"restrained": 600, "confident": 700, "bold": 800}[intensity],
        "letter_tight": "-0.03em" if intensity != "restrained" else "-0.01em",
    }


def derive_rhythm(intensity: str) -> Dict[str, Any]:
    pad = {"restrained": "clamp(72px, 9vw, 120px)",
           "confident": "clamp(84px, 11vw, 150px)",
           "bold": "clamp(96px, 13vw, 180px)"}[intensity]
    # Site quality (2026-07-14): an 8pt spacing scale. Modules had only
    # section_pad + gutter and reached for ad-hoc px/clamp literals for
    # everything smaller; these named steps give consistent internal rhythm
    # (--sx-space-1..8) to adopt in place of magic numbers.
    space = {"1": "4px", "2": "8px", "3": "12px", "4": "16px",
             "5": "24px", "6": "32px", "7": "48px", "8": "64px"}
    # P3 (2026-07-18): the measure widens with the tier — every page used
    # to share one 1180px column (a template tell). Restrained pages hold
    # a closer measure; bold pages get a wider stage.
    content_max = {"restrained": "1100px", "confident": "1180px",
                   "bold": "1280px"}[intensity]
    return {"section_pad": pad, "gutter": "clamp(20px, 4vw, 48px)",
            "content_max": content_max, "space": space}


def derive_radius(vibe: str, intensity: str) -> Dict[str, str]:
    if vibe == "bold" and intensity == "bold":
        return {"card": "4px", "button": "6px", "image": "8px"}     # brutalist edge
    if vibe == "formal":
        # Arc 3 finish: the 999px pill CTA is a quality-bar signature —
        # formal keeps its quieter cards/images but CTAs go full pill.
        return {"card": "14px", "button": "999px", "image": "12px"}
    # Quality-floor arc 7: default card radius 22 → 28px — the original
    # bar's signature "premium modern app" corner (brut stays sharp,
    # formal stays 14px — deliberate identities keep their language).
    return {"card": "28px", "button": "999px", "image": "18px"}     # warm default


def build_brand_dna(business_id: str, bundle: Optional[Dict[str, Any]] = None,
                    color_prefs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The one entry point: brand bundle → complete token set.
    `color_prefs` (Arc 5) = sanitized site_prefs.colors — see derive_palette."""
    if bundle is None:
        import brand_engine
        bundle = brand_engine.get_bundle(business_id) or {}

    design = dict(bundle.get("design") or {})
    # creative_expression may live on the bundle design block or settings
    settings = ((bundle.get("business") or {}).get("settings") or {})
    if "creative_expression" not in design and settings.get("brand_kit"):
        design["creative_expression"] = (settings["brand_kit"] or {}).get("creative_expression") or {}

    vibe = _infer_vibe(bundle)
    intensity = _infer_intensity(bundle, vibe)
    palette = derive_palette(design, vibe, business_id, color_prefs=color_prefs)
    typography = derive_typography(design, vibe, intensity)

    expr = design.get("creative_expression") or {}
    accent_style = (expr.get("hero_accent") or "").strip() or \
        {"warm": "soft_rule", "formal": "thin_rule", "bold": "block_mark"}[vibe]

    return {
        "business_id": business_id,
        "vibe": vibe,
        "intensity": intensity,
        "accent_style": accent_style,
        "palette": palette,
        "typography": typography,
        "rhythm": derive_rhythm(intensity),
        "radius": derive_radius(vibe, intensity),
        "motion": {"restrained": "subtle", "confident": "standard", "bold": "rich"}[intensity],
        "seed": _seed_int(business_id),
    }


# ─── Arc 6 "Creative Engine" — rule-break vocabulary ──────────────────
# The DRO authors decisions.rule_break {what, where, because} in free
# text; the renderer can only DO a small deterministic vocabulary. This
# mapping is the bridge: keyword-match `what` (+`where`) onto the closest
# treatment. Default = oversize_headline (the safest loud move).
#
#   oversize_headline   — hero display type clamps up a tier
#   hard_silence        — the emptiest section doubles its vertical
#                         whitespace and drops all ornament (marked
#                         sx-rb-target by site_modules.render_page)
#   wrong_accent_moment — ONE hero moment (CTA + accent word) uses a
#                         deliberately-shifted hue (150° rotation,
#                         WCAG-checked → palette.accent_break)
#   broken_grid         — the about/pullquote image breaks its column
#                         (offset + slight rotation)

RULE_BREAK_TREATMENTS = ("oversize_headline", "hard_silence",
                         "wrong_accent_moment", "broken_grid")

# Ordered: first family whose keyword hits wins (silence before type so
# "quiet oversized emptiness" reads as silence; accent before grid so
# "wrong color on the grid CTA" reads as the accent moment).
_RULE_BREAK_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("hard_silence", ("silence", "empty", "emptiness", "whitespace", "void",
                      "pause", "breath", "nothing", "blank", "quiet section",
                      "negative space", "stillness")),
    ("wrong_accent_moment", ("accent", "color", "colour", "hue", "clash",
                             "wrong color", "off-palette", "off palette",
                             "unexpected color", "discordant", "jarring")),
    ("broken_grid", ("grid", "offset", "misalign", "off-axis", "off axis",
                     "tilt", "rotate", "overlap", "collide", "column",
                     "escape", "spill", "crooked", "askew")),
    ("oversize_headline", ("oversize", "oversized", "huge", "massive",
                           "giant", "too big", "too large", "scale",
                           "headline", "display type", "type size",
                           "enormous", "monumental")),
)


def resolve_rule_break(rule_break: Any) -> str:
    """DRO decisions.rule_break (free text) → one treatment from
    RULE_BREAK_TREATMENTS, deterministically. Empty/absent → ''."""
    rb = rule_break if isinstance(rule_break, dict) else {}
    blob = f"{rb.get('what') or ''} {rb.get('where') or ''}".strip().lower()
    if not blob:
        return ""
    for treatment, words in _RULE_BREAK_KEYWORDS:
        if any(w in blob for w in words):
            return treatment
    return "oversize_headline"


def derive_break_accent(accent: str, bg: str) -> Tuple[str, str]:
    """The wrong_accent_moment color: rotate the accent hue 150° (wrong on
    purpose — near-complement, never a neighbor), floor the saturation so
    it reads as a CHOICE, then WCAG-check against the page ground the same
    way every other ink is checked. Returns (accent_break, on_accent_break)."""
    h, l, s = _hls(accent or "#d99a4e")
    cand = _from_hls((h + 150.0 / 360.0) % 1.0, l, max(s, 0.45))
    cand = _ensure_contrast(cand, bg or "#111111", 4.5)
    return cand, _on_color(cand)


# ─── DRL palette discipline ───────────────────────────────────────────
# The Design Rationale Object decides palette.base ("dark is a stage, light
# is a room"). We swap the NEUTRAL ground (bg/surface/text/muted/border) to a
# clean preset for that base while KEEPING the brand accent — so the site
# reads as the intended stage/room without losing brand identity.
_BASE_GROUNDS: Dict[str, Dict[str, str]] = {
    "deep_dark":    {"bg": "#0c0c0e", "surface": "#16161a", "surface2": "#1e1e24", "text": "#f4f3f1", "muted": "#a8a6a2", "border": "#2a2a30"},
    "soft_dark":    {"bg": "#181a1f", "surface": "#212430", "surface2": "#2a2e3a", "text": "#eef0f3", "muted": "#a6abb6", "border": "#333845"},
    "warm_light":   {"bg": "#faf7f2", "surface": "#ffffff", "surface2": "#f1ece3", "text": "#1f1b16", "muted": "#6b6258", "border": "#e6ded2"},
    "cool_light":   {"bg": "#f7f9fb", "surface": "#ffffff", "surface2": "#eef2f6", "text": "#161a1f", "muted": "#5e6873", "border": "#e0e6ec"},
    "paper_neutral": {"bg": "#f5f1ea", "surface": "#fffdf9", "surface2": "#ebe5da", "text": "#26221c", "muted": "#6f665a", "border": "#e2dacd"},
}


def apply_dro_palette(dna: Dict[str, Any], dro_palette: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a copy of `dna` with its neutral ground swapped to the DRO's
    palette.base preset (brand accent preserved). No-op if base is unknown."""
    ground = _BASE_GROUNDS.get((dro_palette or {}).get("base") or "")
    if not ground:
        return dna
    out = dict(dna)
    # Arc 9 boundary fix: the accent FAMILY (soft/strong/on/authority/…)
    # must be re-derived against the NEW ground — a light-kit accent_soft
    # on a deep_dark page was the live autopsy's worst finding.
    out["palette"] = rederive_accent_family({**dna.get("palette", {}), **ground})
    return out


# Design audit P2/B1 (2026-07-18) — palette.temperature reaches the pixels.
# The DRO authors warm / cool / neutral_warm / neutral_cool; until now only
# the IMAGE GRADE read it (_base.image_treatment_class) — the neutral ground
# itself never moved, so a "warm" DRO on a cool-light brand kit still
# rendered cool. The nudge forces the neutral family's hue to the authored
# temperature (lightness untouched, saturation floored only on true grays so
# the shift is visible but never loud), then re-derives the accent family
# against the nudged grounds (same Arc 9 discipline as apply_dro_palette).
# Called by site_composer right after apply_dro_palette; the owner's hard
# color direction (apply_owner_ground) still beats it, same precedence as
# the DRO's palette.base.
_TEMP_NUDGE: Dict[str, Tuple[float, float]] = {
    #             hue (0..1)   sat floor for grays
    "warm":         (0.075,    0.035),     # ~27° — tan / cream
    "neutral_warm": (0.075,    0.018),
    "cool":         (0.580,    0.030),     # ~209° — slate
    "neutral_cool": (0.580,    0.016),
}
_TEMP_NEUTRAL_FIELDS = ("bg", "surface", "surface2", "border")


def apply_dro_temperature(dna: Dict[str, Any], temperature: Optional[str]) -> Dict[str, Any]:
    """Nudge the neutral ground family toward the DRO's palette.temperature.
    Returns a copy; input untouched. No-op (with a warning) for values
    outside the schema enum — an authored axis must never silently vanish."""
    key = str(temperature or "").strip().lower()
    if not key:
        return dna
    nudge = _TEMP_NUDGE.get(key)
    if not nudge:
        logger.warning("[brand_dna] DRO palette.temperature %r matched no renderer",
                       temperature)
        return dna
    hue, sat_floor = nudge
    pal = dict(dna.get("palette") or {})
    for field in _TEMP_NEUTRAL_FIELDS:
        if not _parse_hex(pal.get(field)):
            continue
        h, l, s = _hls(pal[field])
        pal[field] = _from_hls(hue, l, max(s, sat_floor))
    out = dict(dna)
    out["palette"] = rederive_accent_family(pal)
    return out


def apply_owner_ground(dna: Dict[str, Any], direction: Optional[str]) -> Dict[str, Any]:
    """Arc 5 — the OWNER's chosen color direction (site_prefs.colors.
    direction) maps 1:1 onto _BASE_GROUNDS and is a HARD preference:
    site_composer applies it after apply_dro_palette so the owner's
    ground beats the model's, and on no-DRO composes it's the ground,
    period. Same neutral-ground swap discipline (brand accent kept)."""
    ground = _BASE_GROUNDS.get(str(direction or "").strip().lower())
    if not ground:
        return dna
    out = dict(dna)
    # Arc 9 boundary fix: re-derive the accent family against the owner's
    # ground (same discipline as apply_dro_palette).
    out["palette"] = rederive_accent_family({**dna.get("palette", {}), **ground})
    return out


def apply_dro_style(dna: Dict[str, Any], decisions: Optional[Dict[str, Any]],
                    owner_pairings: Optional[list] = None,
                    *, fonts_pinned: bool = False,
                    extra_direction_evidence: str = "") -> Dict[str, Any]:
    """DRL render conformance (2026-07-03, quality pass).

    The DRO already authors typography personality, whitespace philosophy,
    layout density and motion temperature — and until now the renderer
    threw all of it away (only palette.base reached the pixels). Consume
    those axes ADDITIVELY:

      - tolerant string matching (DRO values are LLM-authored prose-ish
        labels, not enums); unknown values are a no-op but never silent —
        B1 logs a warning for any authored axis that matches no renderer
      - practitioner-pinned fonts (brand kit / creative-expression) are
        never overridden — same precedence as derive_typography
      - DRO-absent composes return the dna untouched, byte-for-byte

    layout.symmetry and hero visual_metaphor are consumed ELSEWHERE
    (Arc 3): site_composer._apply_symmetry_preference steers defaulted
    section variants and _apply_hero_direction maps visual_metaphor to
    the constructed hero. The Arc 4 quality gate verifies both post-render.
    """
    d = decisions or {}
    if not d:
        return dna
    out = dict(dna)
    t = dict(out.get("typography") or {})
    r = dict(out.get("rhythm") or {})

    def _has(v: Any, *words: str) -> bool:
        s = str(v or "").lower()
        return any(w in s for w in words)

    # ── Typography: display personality → its OWN vetted pairing ──
    # Arc 3 "Expressive Range": every DRO personality (and prose-ish
    # label) resolves to a distinct pairing via FONT_PAIRINGS instead of
    # collapsing onto 3 pairs. Practitioner-pinned fonts still win.
    tspec = d.get("typography") or {}
    pers = tspec.get("display_personality")
    pairing_key = resolve_font_pairing(pers)
    # THIN-DRO FALLBACK (2026-07-22, the "generic default" defect): a
    # starved DRO usually ships no display_personality, so no pairing
    # resolved and the BRAND-KIT heading ruled every rebuild by forfeit
    # (live case: kit Anton on a DRO that reasoned "calm and dark, one
    # warm accent"). The DRO's own prose still carries direction words —
    # resolve the pairing from that evidence before surrendering to the
    # kit default. Rubric, not lookup: any word the fuzzy map understands
    # counts, wherever the DRO said it.
    if not pairing_key:
        _hc = d.get("hero_concept") or {}
        _prose = " ".join(str(x or "") for x in (
            (d.get("whitespace") or {}).get("philosophy"),
            (d.get("whitespace") or {}).get("approach"),
            (d.get("palette") or {}).get("accent_strategy"),
            (d.get("palette") or {}).get("temperature"),
            _hc.get("concept_statement"),
            d.get("first_impression"),
            extra_direction_evidence))
        pairing_key = resolve_font_pairing(_prose)
        if pairing_key:
            logger.info(f"[brand_dna] pairing from DRO prose (thin "
                        f"display_personality): {pairing_key}")
    # Arc B (2026-07-21) — DIRECTION COHERENCE: when the DRO's own
    # aesthetic evidence reads refined (editorial / luxury / quiet
    # whitespace) but the resolved pairing is an impact face, the
    # execution contradicts the direction — the live defect set Anton
    # as the display face of a "60% editorial + 40% luxury" page. The
    # direction wins: impact pairings snap to the refined family.
    _ws_spec = d.get("whitespace") or {}
    # Vocabulary decoupling (2026-07-21): a starved/thin DRO carries no
    # refined words, which let neon ride through every guard — the
    # business's design VOCABULARY (e.g. 'sovereign-authority') is
    # direction evidence that exists even when the DRO is thin, so the
    # caller passes it in via extra_direction_evidence.
    _refined_evidence = _has(
        f"{pers or ''} {_ws_spec.get('philosophy') or ''} "
        f"{_ws_spec.get('approach') or ''} "
        f"{(d.get('palette') or {}).get('accent_strategy') or ''} "
        f"{extra_direction_evidence or ''}",
        "editorial", "luxur", "quiet", "refined", "understated",
        "elegant", "monastic", "literar", "essay", "sovereign",
        "heritage", "prestig")
    if _refined_evidence and pairing_key in ("condensed_impact",
                                             "bold_statement"):
        pairing_key = "quiet_luxury" if _has(pers, "luxur", "quiet",
                                             "refined", "elegant") \
            else "editorial_serif"
    # Hybrid (P2): the owner's type_personality constrains the family —
    # the DRO picks within it, or the family's lead pairing applies.
    if owner_pairings:
        if not pairing_key or pairing_key not in owner_pairings:
            pairing_key = owner_pairings[0]
    if _has(pers, "quiet", "understated", "refined", "discreet"):
        try:
            t["heading_weight"] = min(int(t.get("heading_weight") or 700), 700)
        except (TypeError, ValueError):
            pass
        t["letter_tight"] = "-0.01em"
    elif _has(pers, "loud", "brutal", "commanding", "expressive"):
        try:
            t["heading_weight"] = max(int(t.get("heading_weight") or 700), 800)
        except (TypeError, ValueError):
            pass
    if pairing_key and not fonts_pinned:
        pair = FONT_PAIRINGS[pairing_key]
        t["heading"], t["body"] = pair["heading"], pair["body"]
        # P2 — the third role rides the pairing choice.
        t["accent"] = ACCENT_FACES.get(pairing_key) or pair["heading"]
        # body_personality refinement: an explicitly serif body reads as
        # Lora (the vetted readable serif) when the pairing chose a sans.
        if _has(tspec.get("body_personality"), "serif") and t["body"] != "Lora":
            t["body"] = "Lora"
        # Clamp the heading weight to what the display face actually
        # ships — no faux-bold on weight-locked faces.
        try:
            w = int(t.get("heading_weight") or 700)
        except (TypeError, ValueError):
            w = 700
        t["heading_weight"] = max(min(w, pair.get("wmax", 900)), pair.get("wmin", 300))
        if pair.get("letter"):
            t["letter_tight"] = pair["letter"]

    # ── Whitespace / density → whole rhythm-tier swap (pads are clamp()
    #    strings, so we move between the vetted tiers, never invent px) ──
    ws = d.get("whitespace") or {}
    ws_text = f"{ws.get('philosophy') or ''} {ws.get('approach') or ''} {ws.get('strategy') or ''}"
    density = (d.get("layout") or {}).get("density")
    airy = _has(ws_text, "generous", "luxur", "breath", "air", "sanctuar", "monastic") \
        or _has(density, "airy", "sparse", "minimal", "spacious")
    dense = _has(ws_text, "compress", "tight", "efficient", "packed") \
        or _has(density, "dense", "packed", "rich", "abundant")
    phil = str(ws.get("philosophy") or "").strip().lower()
    ws_matched = True
    if airy and not dense:
        r = derive_rhythm("bold")          # the airiest vetted tier
    elif dense and not airy:
        r = derive_rhythm("restrained")    # the tightest vetted tier
    # B1 (2026-07-18): the remaining schema philosophies render too —
    # confidence_air already lands above via the "air" keyword; the other
    # three used to fall through and change NOTHING on the page.
    elif phil in ("warm_close", "dense_energy"):
        r = derive_rhythm("restrained")    # intimate / packed cadence
    elif phil == "editorial_rhythm":
        # Middle tier + the alternating long/short pad cadence, which
        # page_shell adds as the sx-editorial-rhythm body class.
        r = derive_rhythm("confident")
    elif phil:
        ws_matched = False
    if not ws_matched:
        logger.warning("[brand_dna] DRO whitespace.philosophy %r matched no renderer",
                       ws.get("philosophy"))

    # ── Motion temperature → the tier page_shell already reads ──
    # B1: subtle_entrance and ambient_breathing used to no-op (a bold
    # business kept the rich tier even when the DRO asked for calm).
    # "entrance" is a real fourth tier: arrival choreography ships,
    # perpetual loops are stilled (base_css loop_kill + interstitials).
    mt = (d.get("motion") or {}).get("temperature")
    motion_stilled = _has(mt, "still", "calm", "none", "minimal", "static")
    motion_matched = True
    if motion_stilled:
        out["motion"] = "subtle"
    elif _has(mt, "subtle_entrance", "entrance_only", "entrance only"):
        out["motion"] = "entrance"      # arrivals only — loops stilled
    elif _has(mt, "ambient", "breathing"):
        out["motion"] = "standard"      # arrivals + the slow ambient loops
    elif _has(mt, "kinetic", "expressive", "playful", "rich", "dramatic", "alive"):
        out["motion"] = "rich"
    else:
        motion_matched = False
    if mt and not motion_matched:
        logger.warning("[brand_dna] DRO motion.temperature %r matched no renderer", mt)
    # B1: every schema accent_strategy now renders (single_semantic and
    # tonal_monochrome via page_shell body classes, dual_complement /
    # vivid_block via the image grade) — warn on anything outside them.
    strat = str((d.get("palette") or {}).get("accent_strategy") or "").strip().lower()
    if strat and strat not in ("single_semantic", "dual_complement",
                               "tonal_monochrome", "vivid_block"):
        logger.warning("[brand_dna] DRO palette.accent_strategy %r matched no renderer",
                       strat)

    # ── Arc 6: tension = the character engine. Deterministic + documented:
    #    pole_a (the ROOT pole) drives the typography pairing — but only
    #    when the DRO's display_personality didn't already resolve one and
    #    fonts aren't practitioner-pinned; pole_b (the ENERGY pole) biases
    #    the motion tier — energetic words lift to rich, calm words drop
    #    to subtle — unless the DRO's motion.temperature explicitly stilled
    #    the page (an explicit still always wins). Net effect: heritage-
    #    pole + electric-pole → classic serif pairing WITH the vivid
    #    energy, both poles visible at once.
    tn = d.get("tension") or {}
    pole_a, pole_b = str(tn.get("pole_a") or ""), str(tn.get("pole_b") or "")
    if pole_a and pole_b:
        if not pairing_key and not fonts_pinned:
            tension_key = resolve_font_pairing(pole_a)
            if tension_key:
                pair = FONT_PAIRINGS[tension_key]
                t["heading"], t["body"] = pair["heading"], pair["body"]
                try:
                    w = int(t.get("heading_weight") or 700)
                except (TypeError, ValueError):
                    w = 700
                t["heading_weight"] = max(min(w, pair.get("wmax", 900)),
                                          pair.get("wmin", 300))
                if pair.get("letter"):
                    t["letter_tight"] = pair["letter"]
        if not motion_stilled:
            if _has(pole_b, "electric", "vivid", "bold", "alive", "energetic",
                    "loud", "neon", "fierce", "kinetic", "wild"):
                out["motion"] = "rich"
            elif _has(pole_b, "calm", "still", "quiet", "serene", "hushed",
                      "monastic"):
                out["motion"] = "subtle"

    # ── Arc 6: wrong_accent_moment rule-break → a WCAG-checked shifted
    #    accent lands in the palette; page_shell + base_css spend it on
    #    exactly ONE hero moment (--sx-accent-break).
    if resolve_rule_break(d.get("rule_break")) == "wrong_accent_moment":
        pal = dict(out.get("palette") or {})
        brk, on_brk = derive_break_accent(pal.get("accent") or "",
                                          pal.get("bg") or "")
        pal["accent_break"], pal["on_accent_break"] = brk, on_brk
        out["palette"] = pal

    # ── Arc B (2026-07-21) — REFINED-DIRECTION CHROMA GOVERNOR ──
    # The live editorial-luxury build shipped --sx-accent #00ff59: a
    # pure-neon ink reads tech/athletic and contradicts a refined
    # direction on every element it touches. When the SAME refined
    # evidence that steers typography is present AND the accent (or
    # active secondary) carries near-maximum saturation, chroma pulls
    # to a refined ceiling — hue and lightness stay THEIRS (brand
    # fidelity: this is the brand color composed, not replaced), and
    # the whole accent family re-derives so soft/strong/ground stay
    # consistent. Non-refined directions keep full neon on purpose.
    if _refined_evidence:
        pal = dict(out.get("palette") or {})
        changed = False
        for key in ("accent", "secondary"):
            v = pal.get(key)
            if not (v and _parse_hex(v)):
                continue
            hh, ll, ssat = _hls(v)
            if ssat > 0.80:
                pal[key] = _from_hls(hh, ll, 0.68)
                changed = True
        if changed:
            out["palette"] = rederive_accent_family(pal)

    out["typography"] = t
    out["rhythm"] = r
    return out


# ─── CSS emission ─────────────────────────────────────────────────────

def css_variables(dna: Dict[str, Any]) -> str:
    """The :root block every module's CSS references. Modules use ONLY
    these variables — never raw hex — so brand edits re-skin the whole
    site without touching a single module."""
    p, t = dna["palette"], dna["typography"]
    r, rad = dna["rhythm"], dna["radius"]
    # Arc 6 — wrong_accent_moment rule-break vars (only when derived).
    break_vars = ""
    if p.get("accent_break"):
        break_vars = (f"\n  --sx-accent-break: {p['accent_break']};"
                      f"\n  --sx-on-accent-break: {p.get('on_accent_break') or '#101010'};")
    # Quality-floor arc 7 — h2 weight rides one step below h1 (900/800 at
    # confident) but never above the face's clamped heading weight. Arc 9:
    # both weights come from emitted_heading_weights, the shared helper
    # google_fonts_url also reads — the CSS never demands a weight the
    # fonts <link> didn't load (the live faux-bold-900 bug).
    hw, h2w = emitted_heading_weights(dna)
    return f""":root {{{break_vars}
  --sx-bg: {p['bg']};
  --sx-surface: {p['surface']};
  --sx-surface-2: {p['surface2']};
  --sx-text: {p['text']};
  --sx-muted: {p['muted']};
  --sx-accent: {p['accent']};
  --sx-accent-soft: {p['accent_soft']};
  --sx-accent-strong: {p['accent_strong']};
  --sx-on-accent: {p['on_accent']};
  --sx-accent-ground: {p.get('accent_ground') or p['accent']};
  --sx-on-accent-ground: {p.get('on_accent_ground') or p['on_accent']};
  --sx-border: {p['border']};
  --sx-authority: {p.get('authority') or p['surface2']};
  --sx-on-authority: {p.get('on_authority') or p['text']};
  --sx-accent-on-authority: {p.get('accent_on_authority') or p['accent']};
  --sx-font-heading: '{t['heading']}', Georgia, serif;
  --sx-font-body: '{t['body']}', -apple-system, sans-serif;
  --sx-font-accent: '{t.get('accent') or t['heading']}', Georgia, serif;{_secondary_vars(p)}
  --sx-h1: {t['h1']};
  --sx-h2: {t['h2']};
  --sx-h3: {t.get('h3', '1.6rem')};
  --sx-lead: {t.get('lead', '1.2rem')};
  --sx-small: {t.get('small', '.82rem')};
  --sx-heading-weight: {hw};
  --sx-h2-weight: {h2w};
  --sx-h3-weight: {t.get('h3_weight', 700)};
  --sx-letter-tight: {t['letter_tight']};
  --sx-section-pad: {r['section_pad']};
  --sx-gutter: {r['gutter']};
  --sx-content-max: {r['content_max']};
  --sx-space-1: {r.get('space', {}).get('1', '4px')};
  --sx-space-2: {r.get('space', {}).get('2', '8px')};
  --sx-space-3: {r.get('space', {}).get('3', '12px')};
  --sx-space-4: {r.get('space', {}).get('4', '16px')};
  --sx-space-5: {r.get('space', {}).get('5', '24px')};
  --sx-space-6: {r.get('space', {}).get('6', '32px')};
  --sx-space-7: {r.get('space', {}).get('7', '48px')};
  --sx-space-8: {r.get('space', {}).get('8', '64px')};
  --sx-radius-card: {rad['card']};
  --sx-radius-button: {rad['button']};
  --sx-radius-image: {rad['image']};
  --sx-ease: cubic-bezier(0.16, 1, 0.3, 1);
  --sx-dur-quick: .45s;
  --sx-dur-scene: .9s;
  --sx-dur-grand: 1.6s;
  --sx-stagger: .12s;
}}"""


# Per-family css2 axis specs (Arc 3): variable fonts get ranges, static
# fonts get explicit weight lists, single-weight display faces load bare.
# Requesting weights a family doesn't ship makes the css2 endpoint 400 —
# this registry loads exactly what each face offers. Italic axes ride
# along for the faces the accent-word idiom italicizes.
_GOOGLE_AXES: Dict[str, Optional[str]] = {
    "Fraunces": "ital,opsz,wght@0,9..144,300..900;1,9..144,300..900",
    "Source Sans 3": "ital,wght@0,300..900;1,300..900",
    "Libre Caslon Text": "ital,wght@0,400;0,700;1,400",
    "Lora": "ital,wght@0,400..700;1,400..700",
    "Space Grotesk": "wght@300..700",
    "Inter": "wght@300..900",
    "Bricolage Grotesque": "opsz,wght@12..96,200..800",
    "Nunito Sans": "opsz,wght@6..12,300..1000",
    "Archivo Black": None,
    "Archivo": "wght@400..900",
    "Newsreader": "ital,opsz,wght@0,6..72,300..800;1,6..72,300..800",
    "Cormorant Garamond": "ital,wght@0,300;0,400;0,500;0,600;0,700;1,400;1,500",
    "Outfit": "wght@300..900",
    "IBM Plex Mono": "ital,wght@0,400;0,500;0,600;1,400",
    "IBM Plex Sans": "ital,wght@0,300;0,400;0,500;0,600;0,700;1,400",
    "Baloo 2": "wght@400..800",
    "Karla": "ital,wght@0,300..800;1,300..800",
    "Anton": None,
    "Barlow": "ital,wght@0,400;0,500;0,600;0,700;1,400",
    "Syne": "wght@400..800",
    "Manrope": "wght@300..800",
    # Arc 9 boundary fix — common brand-kit picks (the BrandHub font menu
    # faces): pinned brand fonts used to fall to the generic 400;700
    # request, so a 900-weight heading faux-bolded (the live Montserrat
    # bug). Variable families get their real ranges; static-only families
    # get their real instance lists.
    "Montserrat": "ital,wght@0,100..900;1,100..900",
    "Open Sans": "ital,wght@0,300..800;1,300..800",
    "Lato": "ital,wght@0,100;0,300;0,400;0,700;0,900;1,400;1,700",
    "Raleway": "ital,wght@0,100..900;1,100..900",
    "Roboto": "ital,wght@0,300;0,400;0,500;0,700;0,900;1,400",
    "Poppins": "ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;0,900;1,400",
    "Playfair Display": "ital,wght@0,400..900;1,400..900",
    # P3 — the widened accent-face registry entries (real shipped axes,
    # so the italic request + weight logic stay exact).
    "IBM Plex Serif": "ital,wght@0,300;0,400;0,500;0,600;0,700;1,400;1,500;1,600",
    "Merriweather": "ital,wght@0,300;0,400;0,700;0,900;1,400",
    "Nunito": "ital,wght@0,200..1000;1,200..1000",
    "Oswald": "wght@200..700",
}

# Unknown (practitioner-pinned, off-registry) families: never DEMAND a
# weight above this tier — 400/700/800 are the widely-shipped instances;
# 900 on an unknown face is a faux-bold gamble.
_UNKNOWN_FAMILY_WMAX = 800


def _family_wmax(family: str) -> int:
    """Heaviest weight a family can actually deliver: parsed from its
    _GOOGLE_AXES spec (registry families), _UNKNOWN_FAMILY_WMAX for
    off-registry families, 400 for bare single-weight faces (Anton)."""
    if family not in _GOOGLE_AXES:
        return _UNKNOWN_FAMILY_WMAX
    axes = _GOOGLE_AXES[family]
    if not axes:
        return 400
    weights = [int(n) for n in re.findall(r"\d+", axes) if 100 <= int(n) <= 1000]
    return max(weights) if weights else 400


def emitted_heading_weights(dna: Dict[str, Any]) -> Tuple[int, int]:
    """The (h1, h2) weights the page's CSS actually emits — the single
    source css_variables AND google_fonts_url read, so the stylesheet
    never demands a weight the fonts <link> doesn't request (Arc 9:
    'the css asks for nothing the link doesn't load').

    h2 never exceeds h1; the heading weight clamps to what the face can
    deliver — the registry max for known families, the 700/800 tier
    (_UNKNOWN_FAMILY_WMAX) for unknown ones."""
    t = dna.get("typography") or {}
    try:
        hw = int(t.get("heading_weight") or 700)
    except (TypeError, ValueError):
        hw = 700
    try:
        h2w = int(t.get("h2_weight") or hw)
    except (TypeError, ValueError):
        h2w = hw
    hw = min(hw, _family_wmax(t.get("heading") or ""))
    return hw, min(h2w, hw)


def _secondary_vars(p: Dict[str, Any]) -> str:
    """Emitted only when the brand carries an ACTIVE second accent."""
    if not p.get("secondary_active"):
        return ""
    return (f"\n  --sx-secondary: {p['secondary']};"
            f"\n  --sx-secondary-soft: {p['secondary_soft']};"
            f"\n  --sx-secondary-strong: {p['secondary_strong']};")


def google_fonts_url(dna: Dict[str, Any]) -> str:
    """<link> URL loading exactly the chosen pairing.

    THE RULE (Arc 9): the css asks for nothing the link doesn't load.
    Known families load their registry axes (real shipped weights/ranges).
    Unknown families (practitioner-pinned, off-registry) request exactly
    the weights the page emits — 400/700 plus the clamped heading weights
    from emitted_heading_weights — instead of a blind 400;700 that left
    heavier headings faux-bolding."""
    heading = dna["typography"]["heading"]
    body = dna["typography"]["body"]
    # P2 — load the accent face when it is a distinct third family.
    accent_face = dna["typography"].get("accent") or heading
    hw, h2w = emitted_heading_weights(dna)
    fams: List[str] = []
    for name in (heading, body, accent_face):
        if name and name not in fams:
            fams.append(name)
    parts: List[str] = []
    for f in fams:
        if f in _GOOGLE_AXES:
            axes = _GOOGLE_AXES[f]
        else:
            weights = {400, 700}
            if f == heading:
                weights.update((hw, h2w))
            axes = "wght@" + ";".join(str(w) for w in sorted(weights))
        fam = f.replace(" ", "+")
        parts.append(f"family={fam}:{axes}" if axes else f"family={fam}")
    return "https://fonts.googleapis.com/css2?" + "&".join(parts) + "&display=swap"
