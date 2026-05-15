"""Diamond motif primitive — rotated square in brand signal color.
Cathedral signature: small geometric mark used as decorative anchor,
accent line endcap, or atmospheric overlay on dark sections.

Sizes:
  small  → 12px (inline mark, accent line cap)
  medium → 24px (corner decoration)
  large  → 48px (decorative anchor)
  xlarge → 96px (visual anchor in layered_diamond variant)

target_path makes the motif Edit-Mode-addressable so the practitioner
can recolor it via the BrandPalettePicker.
"""
from __future__ import annotations

from html import escape
from typing import Literal

DiamondSize = Literal["small", "medium", "large", "xlarge"]

_SIZE_PX = {
    "small": 12,
    "medium": 24,
    "large": 48,
    "xlarge": 96,
}


def render_diamond_motif(
    target_path: str,
    size: DiamondSize = "medium",
    position_style: str = "",
    *,
    color_var: str = "var(--brand-signal, #C6952F)",
    opacity: float = 1.0,
) -> str:
    """Render a single diamond mark.

    `position_style` is appended to the inline style — caller controls
    position (top/left/right/bottom or transforms) since variants
    use diamonds in different layout positions.
    `color_var` defaults to the brand signal CSS variable but can be
    overridden (e.g. authority color on a full-bleed overlay).
    """
    px = _SIZE_PX.get(size, _SIZE_PX["medium"])
    safe_target = escape(target_path)
    safe_position = position_style.strip().strip(";")
    suffix = f"; {safe_position}" if safe_position else ""
    return (
        f'<div class="ca-hero-diamond ca-hero-diamond-{size}" '
        f'data-override-target="{safe_target}" '
        f'data-override-type="color" '
        f'style="width: {px}px; '
        f'height: {px}px; '
        f'background: {color_var}; '
        f'opacity: {opacity}; '
        f'transform: rotate(45deg); '
        f'pointer-events: none{suffix}">'
        f"</div>"
    )
