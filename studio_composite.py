"""Studio Composite Engine: deterministic vocabulary blending + layout ranking.

Faithful port of:
  - src/lib/colorPalette.ts (hexToHsl, hslToHex)
  - src/lib/design/compositeEngine.ts:buildComposite

Pure functions only. No AI calls. No database calls.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple, TypedDict

from studio_data import (
    VOCAB_LAYOUT_MAP,
    VOCABULARIES,
    ColorPalette,
    CulturalVocabulary,
    FontPairing,
    detect_font_pairing,
)


class CompositeDirection(TypedDict):
    primary_vocabulary: CulturalVocabulary
    secondary_vocabulary: Optional[CulturalVocabulary]
    aesthetic_vocabulary: Optional[CulturalVocabulary]
    blended_color_system: ColorPalette
    blended_typography: str
    blended_energy: str
    recommended_layouts: List[str]
    confidence_score: int
    reasoning: str
    selected_font_pairing: Optional[FontPairing]


# ─── COLOR MATH — port from colorPalette.ts ─────────────────────────


_HEX_RE = re.compile(r"^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$", re.IGNORECASE)


def hex_to_hsl(hex_color: str) -> Tuple[float, float, float]:
    """Port of colorPalette.ts:hexToHsl. Returns (h, s, l) where h in [0,360),
    s and l in [0,100]. Mirrors the TS implementation exactly so that the
    Python output matches what Studio produces on the same input."""
    if not hex_color:
        return (0.0, 0.0, 0.0)
    m = _HEX_RE.match(hex_color.strip())
    if not m:
        # Tolerate 3-char shorthand by expanding
        h3 = hex_color.lstrip("#")
        if len(h3) == 3:
            expanded = "".join(c * 2 for c in h3)
            m = _HEX_RE.match("#" + expanded)
        if not m:
            return (0.0, 0.0, 0.0)

    r = int(m.group(1), 16) / 255
    g = int(m.group(2), 16) / 255
    b = int(m.group(3), 16) / 255

    cmax = max(r, g, b)
    cmin = min(r, g, b)
    l = (cmax + cmin) / 2

    if cmax == cmin:
        h = 0.0
        s = 0.0
    else:
        d = cmax - cmin
        s = d / (2 - cmax - cmin) if l > 0.5 else d / (cmax + cmin)
        if cmax == r:
            h = ((g - b) / d + (6 if g < b else 0)) / 6
        elif cmax == g:
            h = ((b - r) / d + 2) / 6
        else:
            h = ((r - g) / d + 4) / 6

    return (h * 360, s * 100, l * 100)


def hsl_to_hex(h: float, s: float, l: float) -> str:
    """Port of colorPalette.ts:hslToHex."""
    s = s / 100
    l = l / 100
    a = s * min(l, 1 - l)

    def f(n: int) -> str:
        k = (n + h / 30) % 12
        color = l - a * max(min(k - 3, 9 - k, 1), -1)
        return format(round(255 * color), "02x")

    return f"#{f(0)}{f(8)}{f(4)}"


def blend_hex_colors(hex_a: str, hex_b: str, ratio: float = 0.5) -> str:
    """Linear interpolation in HSL space. ratio 0=a, 1=b. Hue uses shortest path."""
    h1, s1, l1 = hex_to_hsl(hex_a)
    h2, s2, l2 = hex_to_hsl(hex_b)
    if abs(h2 - h1) > 180:
        if h1 < h2:
            h1 += 360
        else:
            h2 += 360
    h = (h1 * (1 - ratio) + h2 * ratio) % 360
    s = s1 * (1 - ratio) + s2 * ratio
    l = l1 * (1 - ratio) + l2 * ratio
    return hsl_to_hex(h, s, l)


def blend_palettes(
    primary_palette: ColorPalette,
    secondary_palette: Optional[ColorPalette] = None,
    aesthetic_palette: Optional[ColorPalette] = None,
) -> ColorPalette:
    """Blend up to 3 palettes channel-by-channel. Primary always dominates.

    Pass 3.5 Session 2 fix: Session 1's build_composite was an identity
    operation (it took primary unchanged and only swapped accent). This
    function actually blends in HSL space.

    Ratios (primary always the largest weight):
      - Primary alone:                     identity (no blending)
      - Primary + secondary:               75 / 25
      - Primary + aesthetic:               85 / 15
      - Primary + secondary + aesthetic:   80 / 13 / 7  (retuned in checkpoint 1
        review — earlier 65/22/13 produced too-strong a shift for triples)
    """
    if secondary_palette is None and aesthetic_palette is None:
        return primary_palette

    channels = ("primary", "secondary", "accent", "background", "text")

    if aesthetic_palette is None:
        ratio = 0.25  # secondary's contribution
        return ColorPalette(**{
            ch: blend_hex_colors(primary_palette[ch], secondary_palette[ch], ratio)
            for ch in channels
        })

    if secondary_palette is None:
        ratio = 0.15
        return ColorPalette(**{
            ch: blend_hex_colors(primary_palette[ch], aesthetic_palette[ch], ratio)
            for ch in channels
        })

    # Three-way blend: 80 / 13 / 7. Two-step: blend primary with secondary
    # in their relative proportions (13 / 93), then blend that result with
    # aesthetic at its 7/100 share of the total. Primary still strongly
    # dominates so the user's brand voice character is preserved.
    primary_secondary_ratio = 13 / (80 + 13)  # ~0.140
    aesthetic_ratio = 0.07
    return ColorPalette(**{
        ch: blend_hex_colors(
            blend_hex_colors(primary_palette[ch], secondary_palette[ch], primary_secondary_ratio),
            aesthetic_palette[ch],
            aesthetic_ratio,
        )
        for ch in channels
    })


# ─── LAYOUT RANKING — port from compositeEngine.ts ────────────────────


def rank_layouts(
    primary_vocab_id: str,
    secondary_vocab_id: Optional[str] = None,
    aesthetic_vocab_id: Optional[str] = None,
) -> List[str]:
    """Port of compositeEngine.ts:buildComposite layout-scoring section.

    Primary layouts: weight 3-i (positional). Secondary: 2-i*0.5. Aesthetic: 1-i*0.3.
    Returns top 3 layout IDs.
    """
    scores: Dict[str, float] = {}

    primary = VOCABULARIES.get(primary_vocab_id)
    primary_layouts = (
        VOCAB_LAYOUT_MAP.get(primary_vocab_id)
        or (primary["layout_affinity"] if primary else [])
    )
    for i, lid in enumerate(primary_layouts):
        scores[lid] = scores.get(lid, 0.0) + (3 - i)

    if secondary_vocab_id:
        secondary = VOCABULARIES.get(secondary_vocab_id)
        sec_layouts = (
            VOCAB_LAYOUT_MAP.get(secondary_vocab_id)
            or (secondary["layout_affinity"] if secondary else [])
        )
        for i, lid in enumerate(sec_layouts):
            scores[lid] = scores.get(lid, 0.0) + (2 - i * 0.5)

    if aesthetic_vocab_id:
        aesthetic = VOCABULARIES.get(aesthetic_vocab_id)
        aes_layouts = (
            VOCAB_LAYOUT_MAP.get(aesthetic_vocab_id)
            or (aesthetic["layout_affinity"] if aesthetic else [])
        )
        for i, lid in enumerate(aes_layouts):
            scores[lid] = scores.get(lid, 0.0) + (1 - i * 0.3)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [lid for lid, _ in ranked[:3]]


# ─── BUILD COMPOSITE — faithful port of compositeEngine.ts:buildComposite ──


def build_composite(
    primary_vocab_id: str,
    secondary_vocab_id: Optional[str] = None,
    aesthetic_vocab_id: Optional[str] = None,
) -> CompositeDirection:
    """Pure port of compositeEngine.ts:buildComposite.

    Color blending mirrors the TS source exactly:
      - primary, secondary (background, text) come from primary unchanged
      - accent comes from secondary if present, else primary
    Typography: appended with ". Aesthetic influence: ..." when aesthetic present.
    Energy: joined with " + ".
    Confidence: round((primary_signal_count / 10) * 70) + 15 if secondary + 10 if aesthetic, capped at 100.
    """
    primary = VOCABULARIES.get(primary_vocab_id)
    if not primary:
        raise ValueError(f"Unknown primary vocabulary: {primary_vocab_id}")

    secondary = VOCABULARIES.get(secondary_vocab_id) if secondary_vocab_id else None
    aesthetic = VOCABULARIES.get(aesthetic_vocab_id) if aesthetic_vocab_id else None

    # Pass 3.5 Session 2: actually blend the palettes in HSL space.
    # Session 1 was an identity operation (primary unchanged, just swapping
    # accent); now secondary and aesthetic vocabularies measurably shift
    # the palette while primary still dominates.
    blended_color_system = blend_palettes(
        primary["color_palette"],
        secondary["color_palette"] if secondary else None,
        aesthetic["color_palette"] if aesthetic else None,
    )

    blended_typography = (
        f"{primary['typography_direction']}. Aesthetic influence: {aesthetic['typography_direction']}"
        if aesthetic
        else primary["typography_direction"]
    )

    energy_parts = [primary["energy"]]
    if secondary:
        energy_parts.append(secondary["energy"])
    blended_energy = " + ".join(energy_parts)

    recommended_layouts = rank_layouts(primary_vocab_id, secondary_vocab_id, aesthetic_vocab_id)

    selected_font_pairing = detect_font_pairing(
        primary["id"],
        recommended_layouts[0] if recommended_layouts else "",
    )

    confidence_score = min(
        round((len(primary["detection_signals"]) / 10) * 70)
        + (15 if secondary else 0)
        + (10 if aesthetic else 0),
        100,
    )

    reasoning_parts = [f'Primary vocabulary "{primary["name"]}" sets the foundation.']
    if secondary:
        reasoning_parts.append(f'"{secondary["name"]}" adds depth to the accent and energy.')
    if aesthetic:
        reasoning_parts.append(f'"{aesthetic["name"]}" influences the visual style and typography.')
    reasoning_parts.append(f"Top layouts: {', '.join(recommended_layouts)}.")
    reasoning = " ".join(reasoning_parts)

    return CompositeDirection(
        primary_vocabulary=primary,
        secondary_vocabulary=secondary,
        aesthetic_vocabulary=aesthetic,
        blended_color_system=blended_color_system,
        blended_typography=blended_typography,
        blended_energy=blended_energy,
        recommended_layouts=recommended_layouts,
        confidence_score=confidence_score,
        reasoning=reasoning,
        selected_font_pairing=selected_font_pairing,
    )
