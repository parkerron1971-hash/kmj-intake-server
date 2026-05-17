"""Studio Brut depth helpers — sister to cinematic_authority's
_depth_helpers.py but emitting Studio Brut's ornament vocabulary
(squares + circles + bars) for satellite ornaments instead of
Cathedral's diamonds.

Three exports variants compose:

  1. SECTION_DEPTH_BG — paste into the section root's inline style;
     wires the --sb-bg-* CSS variables that background_treatment_vars
     emits. Falls back to brand-warm-neutral when no treatment fires.

  2. IMAGE_DEPTH_STYLE — paste into <img> inline styles for image-
     using variants. Wires --sb-image-filter + --sb-image-mask
     (overlay is applied via a wrapper <div> per variant when
     image_treatment is filtered/dramatic; see variant code).

  3. render_satellite_ornaments(ornament_treatment, seed_key) —
     returns 6 scattered satellite shapes when ornament=heavy.
     Uses a mix of squares + circles + small color blocks so the
     satellite cluster reads as Studio Brut, not Cathedral. Empty
     string for minimal + signature.
"""
from __future__ import annotations

import random
from typing import List

from ..primitives import (
    render_square_marker,
    render_circle_marker,
    render_color_block,
)


SECTION_DEPTH_BG = (
    "background-color: var(--sb-bg-color, var(--brand-warm-neutral, #F4F4F0)); "
    "background-image: var(--sb-bg-image, none); "
    "background-size: var(--sb-bg-size, auto); "
    "background-repeat: var(--sb-bg-repeat, no-repeat); "
    "background-position: center center; "
    "background-blend-mode: var(--sb-bg-blend, normal); "
)


IMAGE_DEPTH_STYLE = (
    "filter: var(--sb-image-filter, none); "
    "-webkit-mask-image: var(--sb-image-mask, none); "
    "mask-image: var(--sb-image-mask, none); "
)


# Scatter positions for satellite ornaments. Mix of small + medium
# sizes + shape types — squares dominate (Studio Brut's most common
# architectural ornament), circles + small color blocks add visual
# variety.
_SATELLITE_DEFS = [
    ("8%",  "10%", "square", "small"),
    ("88%", "14%", "square", "medium"),
    ("16%", "82%", "circle", "small"),
    ("78%", "86%", "square", "small"),
    ("48%", "6%",  "square", "small"),
    ("28%", "94%", "circle", "small"),
    ("94%", "48%", "block",  "32px"),   # block uses arbitrary px
    ("4%",  "58%", "square", "medium"),
]


def render_satellite_ornaments(
    ornament: str,
    seed_key: str,
    target_prefix: str = "hero.sat",
) -> str:
    """Return ornament=heavy satellite ornament markup.

    ornament='minimal' / 'signature' → empty string.
    ornament='heavy' → 6 scattered satellites (mix of squares + circles
                       + a color block). Studio Brut commits harder to
                       satellite density than Cathedral (6 vs 4).
    seed_key keeps the scatter deterministic per variant."""
    if ornament != "heavy":
        return ""
    rng = random.Random(hash(seed_key) & 0xFFFFFFFF)
    chosen = rng.sample(_SATELLITE_DEFS, k=6)
    parts: List[str] = []
    for i, (top, left, kind, size) in enumerate(chosen):
        position = (
            f"position: absolute; "
            f"top: {top}; "
            f"left: {left}; "
            f"z-index: 1;"
        )
        target = f"{target_prefix}_{i}"
        if kind == "square":
            parts.append(
                render_square_marker(
                    target, size=size, position_style=position, opacity=0.7,
                )
            )
        elif kind == "circle":
            parts.append(
                render_circle_marker(
                    target, size=size, position_style=position, opacity=0.7,
                )
            )
        else:  # "block"
            # 'size' here is a CSS length (e.g. "32px") — use it as
            # the color block dimensions.
            parts.append(
                render_color_block(
                    target,
                    width=size, height=size,
                    position_style=position,
                    opacity=0.6,
                )
            )
    return "\n".join(parts)
