"""Phase 2.6 — shared helpers so each variant wires depth treatments
identically. Variants compose:

  1. SECTION_DEPTH_BG — paste into the section root's inline style
     (after the variant's own bg, since later declarations win)
  2. IMAGE_DEPTH_STYLE — paste into <img> element inline styles for
     image-using variants
  3. render_satellite_diamonds(ornament_treatment, ...) — returns
     scattered extra diamond elements when ornament=heavy

Keep these as plain string constants / pure functions so unit tests
can read them without importing FastAPI / Anthropic.
"""
from __future__ import annotations

import random
from typing import List

from ..primitives import render_diamond_motif


# Append after the variant's own style declarations. Vars fall back to
# warm-neutral / none so a variant rendered without treatments still
# behaves like the Phase 2.5 baseline.
SECTION_DEPTH_BG = (
    "background-color: var(--ca-bg-color, var(--brand-warm-neutral, #F8F6F1)); "
    "background-image: var(--ca-bg-image, none); "
    "background-size: var(--ca-bg-size, auto); "
    "background-repeat: var(--ca-bg-repeat, no-repeat); "
    "background-position: center center; "
    "background-blend-mode: var(--ca-bg-blend, normal); "
)


# Append into the inline style on <img> elements. The vars resolve to
# 'none' when image_treatment='clean' so this is safe to apply to all
# image-using variants unconditionally.
IMAGE_DEPTH_STYLE = (
    "filter: var(--ca-image-filter, none); "
    "-webkit-mask-image: var(--ca-image-mask, none); "
    "mask-image: var(--ca-image-mask, none); "
)


# Satellite diamond positions for ornament=heavy. Eight predefined
# scatter points around the section perimeter. We pick `count` of them
# using a deterministic seed (so the same variant renders the same
# scatter across reloads — important for testability).
_SATELLITE_POSITIONS = [
    ("8%",  "12%", "small"),
    ("88%", "18%", "small"),
    ("18%", "82%", "medium"),
    ("78%", "78%", "small"),
    ("52%", "8%",  "small"),
    ("32%", "92%", "small"),
    ("92%", "52%", "medium"),
    ("4%",  "62%", "small"),
]


def render_satellite_diamonds(
    ornament: str,
    seed_key: str,
    target_prefix: str = "hero.satellite",
) -> str:
    """Return ornament=heavy satellite diamond markup.

    ornament='minimal' / 'signature' → empty string (no extras).
    ornament='heavy' → 4 scattered satellite diamonds.

    seed_key keeps the satellite scatter deterministic per variant
    so the same variant always paints the same ornament constellation.
    """
    if ornament != "heavy":
        return ""
    rng = random.Random(hash(seed_key) & 0xFFFFFFFF)
    chosen = rng.sample(_SATELLITE_POSITIONS, k=4)
    parts: List[str] = []
    for i, (top, left, size) in enumerate(chosen):
        position = (
            f"position: absolute; "
            f"top: {top}; "
            f"left: {left}; "
            f"z-index: 1;"
        )
        parts.append(
            render_diamond_motif(
                f"{target_prefix}_{i}",
                size=size,
                position_style=position,
                opacity=0.55,
            )
        )
    return "\n".join(parts)
