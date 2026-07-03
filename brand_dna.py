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


# ─── Token derivation ─────────────────────────────────────────────────

def derive_palette(design: Dict[str, Any], vibe: str, business_id: str) -> Dict[str, str]:
    """Full surface/ink system from up to 5 brand colors. Dark- or
    light-mode is taken from the brand background's luminance."""
    defaults = _VIBE_DEFAULTS[vibe]
    bg = design.get("background_color") if _parse_hex(design.get("background_color")) else defaults["bg"]
    accent = design.get("accent_color") if _parse_hex(design.get("accent_color")) else None
    primary = design.get("primary_color") if _parse_hex(design.get("primary_color")) else None
    secondary = design.get("secondary_color") if _parse_hex(design.get("secondary_color")) else None
    text = design.get("text_color") if _parse_hex(design.get("text_color")) else None

    accent = accent or primary or defaults["accent"]
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
        "on_accent": _on_color(accent),
        "primary": primary,
        "secondary": secondary or surface_2,
        "border": border,
    }


def derive_typography(design: Dict[str, Any], vibe: str, intensity: str) -> Dict[str, Any]:
    defaults = _VIBE_DEFAULTS[vibe]["fonts"]
    heading = (design.get("font_heading") or "").strip() or defaults[0]
    body = (design.get("font_body") or "").strip() or defaults[1]
    expr = (design.get("creative_expression") or {})
    if (expr.get("hero_font") or "").strip():
        heading = expr["hero_font"].strip()

    h1 = {"restrained": "clamp(2.6rem, 5vw, 4.2rem)",
          "confident": "clamp(3rem, 6.5vw, 5.2rem)",
          "bold": "clamp(3.4rem, 8vw, 6.4rem)"}[intensity]
    h2 = {"restrained": "clamp(1.9rem, 3.2vw, 2.6rem)",
          "confident": "clamp(2rem, 4vw, 3.1rem)",
          "bold": "clamp(2.2rem, 4.6vw, 3.6rem)"}[intensity]
    weight = {"restrained": 700, "confident": 800, "bold": 900}[intensity]
    return {
        "heading": heading,
        "body": body,
        "h1": h1, "h2": h2,
        "heading_weight": weight,
        "letter_tight": "-0.025em" if intensity != "restrained" else "-0.01em",
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
        return {"card": "14px", "button": "10px", "image": "12px"}
    return {"card": "22px", "button": "999px", "image": "18px"}     # warm default


def build_brand_dna(business_id: str, bundle: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The one entry point: brand bundle → complete token set."""
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
    palette = derive_palette(design, vibe, business_id)
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

    Deliberately NOT consumed yet: layout.symmetry (no renderer hook) and
    visual_metaphor (constructed hero not built) — flagged in the DRL doc.
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

    # ── Typography: display personality → vetted pair + weight shift ──
    pers = (d.get("typography") or {}).get("display_personality")
    if pers and not fonts_pinned:
        if _has(pers, "editorial", "literary", "serif", "heritage", "classic", "storyteller", "warm"):
            t["heading"], t["body"] = "Fraunces", "Source Sans 3"
        elif _has(pers, "refined", "quiet", "elegant", "understated", "luxur", "discreet"):
            t["heading"], t["body"] = "Libre Caslon Text", "Inter"
        elif _has(pers, "geometric", "modern", "bold", "brutal", "tech", "commanding", "expressive", "confident"):
            t["heading"], t["body"] = "Bricolage Grotesque", "Inter"
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
    if _has(mt, "still", "calm", "none", "minimal", "static"):
        out["motion"] = "subtle"
    elif _has(mt, "kinetic", "expressive", "playful", "rich", "dramatic", "alive"):
        out["motion"] = "rich"

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
    return f""":root {{
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
  --sx-font-heading: '{t['heading']}', Georgia, serif;
  --sx-font-body: '{t['body']}', -apple-system, sans-serif;
  --sx-h1: {t['h1']};
  --sx-h2: {t['h2']};
  --sx-heading-weight: {t['heading_weight']};
  --sx-letter-tight: {t['letter_tight']};
  --sx-section-pad: {r['section_pad']};
  --sx-gutter: {r['gutter']};
  --sx-content-max: {r['content_max']};
  --sx-radius-card: {rad['card']};
  --sx-radius-button: {rad['button']};
  --sx-radius-image: {rad['image']};
}}"""


def google_fonts_url(dna: Dict[str, Any]) -> str:
    fams: List[str] = []
    for name in (dna["typography"]["heading"], dna["typography"]["body"]):
        if name and name not in fams:
            fams.append(name)
    parts = [f"family={f.replace(' ', '+')}:wght@300;400;500;600;700;800;900" for f in fams]
    return "https://fonts.googleapis.com/css2?" + "&".join(parts) + "&display=swap"
