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
import re
from typing import Any, Dict, List, Optional, Tuple

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
    "formal": {"bg": "#0e1217", "accent": "#7fa8d9", "fonts": ("Libre Caslon Text", "Inter")},
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

# DRO schema enums map exactly; prose-ish labels resolve by keyword.
_PAIRING_EXACT = {
    "editorial_serif": "editorial_serif",
    "grotesque_bold": "bold_statement",
    "humanist_warm": "warm_humanist",
    "geometric_precise": "modern_grotesque",
    "expressive_display": "expressive_display",
    "condensed_impact": "condensed_impact",
}

_PAIRING_FUZZY = (
    ("quiet_luxury", ("quiet", "luxur", "elegant", "refined", "understated", "discreet")),
    ("heritage", ("heritage", "classic", "traditional", "timeless")),
    ("technical_precise", ("technical", "precis", "mono", "engineer", "system")),
    ("condensed_impact", ("condensed", "compact", "poster", "impact")),
    ("bold_statement", ("bold", "brutal", "loud", "statement", "commanding", "heavy", "black")),
    ("storyteller", ("story", "narrat", "literary", "book")),
    ("playful", ("playful", "fun", "round", "friendly", "joy", "whimsic")),
    ("warm_humanist", ("humanist", "warm", "human", "approachable", "welcom")),
    ("expressive_display", ("expressive", "artistic", "creative", "eccentric", "display")),
    ("editorial_serif", ("editorial", "serif", "magazine", "literati")),
    ("modern_grotesque", ("grotesque", "modern", "geometric", "minimal", "clean", "tech")),
)


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

    # Accent derivations — soft wash for chips/rules, strong for hovers.
    h, l, s = _hls(accent)
    accent_soft = _from_hls(h, (0.16 if dark_mode else 0.92), min(s, 0.55))
    accent_strong = _from_hls(h, l + (0.08 if dark_mode else -0.08), s)
    border = _shift_l(bg, 0.10 if dark_mode else -0.10)

    # Quality-floor arc 7 — the full-bleed accent band made --sx-on-accent
    # a body-text surface, so its contrast is now ENFORCED (4.5), not just
    # best-of-two.
    on_accent = _ensure_contrast(_on_color(accent), accent, 4.5)

    # AUTHORITY band (quality-floor arc 7): the deep chapter-break surface —
    # the role navy played in the original bar. Light grounds: the darkest
    # brand color pulled deep (hue kept, lightness ~0.13). Dark grounds: a
    # deeper-still accent-tinted tone so the band still reads as a distinct
    # chapter. Inks are contrast-enforced like every other pair; the accent
    # gets its own on-authority variant (3:1 — headings/marks scale).
    if dark_mode:
        ah, _al, asat = _hls(accent)
        bg_l = _hls(bg)[1]
        authority = _from_hls(ah, min(max(bg_l - 0.04, 0.03), 0.10),
                              min(asat * 0.5, 0.32))
    else:
        cands = [c for c in (primary, secondary, accent) if c and _parse_hex(c)]
        seed_color = min(cands, key=_luminance) if cands else text
        hh, _ll, ss = _hls(seed_color)
        authority = _from_hls(hh, 0.13, max(min(ss, 0.75), 0.25))
    on_authority = _ensure_contrast(
        "#f4f0e8" if _luminance(authority) < 0.5 else "#15130e", authority, 4.5)
    accent_on_authority = _ensure_contrast(accent, authority, 3.0)

    return {
        "mode": "dark" if dark_mode else "light",
        "bg": bg,
        "surface": surface,
        "surface2": surface_2,
        "text": text,
        "muted": muted,
        "accent": accent,
        "accent_soft": accent_soft,
        "accent_strong": accent_strong,
        "on_accent": on_accent,
        "primary": primary,
        "secondary": secondary or surface_2,
        "border": border,
        "authority": authority,
        "on_authority": on_authority,
        "accent_on_authority": accent_on_authority,
    }


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
    return {
        "heading": heading,
        "body": body,
        "h1": h1, "h2": h2,
        "heading_weight": weight,
        "h2_weight": h2_weight,
        "letter_tight": "-0.03em" if intensity != "restrained" else "-0.01em",
    }


def derive_rhythm(intensity: str) -> Dict[str, str]:
    pad = {"restrained": "clamp(72px, 9vw, 120px)",
           "confident": "clamp(84px, 11vw, 150px)",
           "bold": "clamp(96px, 13vw, 180px)"}[intensity]
    return {"section_pad": pad, "gutter": "clamp(20px, 4vw, 48px)", "content_max": "1180px"}


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
    out["palette"] = {**dna.get("palette", {}), **ground}
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
    out["palette"] = {**dna.get("palette", {}), **ground}
    return out


def apply_dro_style(dna: Dict[str, Any], decisions: Optional[Dict[str, Any]],
                    *, fonts_pinned: bool = False) -> Dict[str, Any]:
    """DRL render conformance (2026-07-03, quality pass).

    The DRO already authors typography personality, whitespace philosophy,
    layout density and motion temperature — and until now the renderer
    threw all of it away (only palette.base reached the pixels). Consume
    those axes ADDITIVELY:

      - tolerant string matching (DRO values are LLM-authored prose-ish
        labels, not enums); unknown values are a no-op
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
    if airy and not dense:
        r = derive_rhythm("bold")          # the airiest vetted tier
    elif dense and not airy:
        r = derive_rhythm("restrained")    # the tightest vetted tier

    # ── Motion temperature → the tier page_shell already reads ──
    mt = (d.get("motion") or {}).get("temperature")
    motion_stilled = _has(mt, "still", "calm", "none", "minimal", "static")
    if motion_stilled:
        out["motion"] = "subtle"
    elif _has(mt, "kinetic", "expressive", "playful", "rich", "dramatic", "alive"):
        out["motion"] = "rich"

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
    # confident) but never above the face's clamped heading weight (the
    # wmax clamp in apply_dro_style already capped heading_weight).
    try:
        h2w: Any = min(int(t.get("h2_weight") or t["heading_weight"]),
                       int(t["heading_weight"]))
    except (TypeError, ValueError):
        h2w = t["heading_weight"]
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
  --sx-border: {p['border']};
  --sx-authority: {p.get('authority') or p['surface2']};
  --sx-on-authority: {p.get('on_authority') or p['text']};
  --sx-accent-on-authority: {p.get('accent_on_authority') or p['accent']};
  --sx-font-heading: '{t['heading']}', Georgia, serif;
  --sx-font-body: '{t['body']}', -apple-system, sans-serif;
  --sx-h1: {t['h1']};
  --sx-h2: {t['h2']};
  --sx-heading-weight: {t['heading_weight']};
  --sx-h2-weight: {h2w};
  --sx-letter-tight: {t['letter_tight']};
  --sx-section-pad: {r['section_pad']};
  --sx-gutter: {r['gutter']};
  --sx-content-max: {r['content_max']};
  --sx-radius-card: {rad['card']};
  --sx-radius-button: {rad['button']};
  --sx-radius-image: {rad['image']};
  --sx-ease: cubic-bezier(0.16, 1, 0.3, 1);
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
}


def google_fonts_url(dna: Dict[str, Any]) -> str:
    """<link> URL loading exactly the chosen pairing. Unknown families
    (practitioner-pinned) request the near-universal 400;700."""
    fams: List[str] = []
    for name in (dna["typography"]["heading"], dna["typography"]["body"]):
        if name and name not in fams:
            fams.append(name)
    parts: List[str] = []
    for f in fams:
        axes = _GOOGLE_AXES.get(f, "wght@400;700")
        fam = f.replace(" ", "+")
        parts.append(f"family={fam}:{axes}" if axes else f"family={fam}")
    return "https://fonts.googleapis.com/css2?" + "&".join(parts) + "&display=swap"
