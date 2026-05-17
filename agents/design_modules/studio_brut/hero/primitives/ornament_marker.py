"""Studio Brut ornament markers — squares, rectangles, circles, bars,
color blocks. Cathedral's diamond_motif is banned across Studio Brut
(STUDIO_BRUT_DESIGN.md anti-pattern). Each shape exposed here is a
member of Studio Brut's ornament vocabulary.

All shapes:
  - Apply --sb-ornament-opacity-mult + --sb-ornament-size-mult so
    the ornament treatment dimension can scale them at render time
  - Pick up --sb-ornament-glow filter when color_depth=radial_glows
  - Use sharp 90-degree corners (no border-radius) by default — Studio
    Brut's ornament discipline
  - Carry data-override-target so practitioners can recolor via
    Edit Mode

Sizing convention (matches Cathedral's _SIZE_PX for cross-module
muscle memory but values differ per shape semantics):

  small  → 16px (Cathedral diamond was 12px; Studio Brut's smallest
                 still reads as architectural)
  medium → 40px (Cathedral medium 24px; Studio Brut goes bigger)
  large  → 96px (Cathedral large 48px; Studio Brut leans into scale)
  xlarge → 240px (Cathedral xlarge 96px; Studio Brut's xlarge is a
                  near-room-scale color block)
"""
from __future__ import annotations

from html import escape
from typing import Literal

ShapeSize = Literal["small", "medium", "large", "xlarge"]

_SIZE_PX = {
    "small": 16,
    "medium": 40,
    "large": 96,
    "xlarge": 240,
}


def _scaled_size_expr(base_px: int) -> str:
    return f"calc({base_px}px * var(--sb-ornament-size-mult, 1))"


def _scaled_opacity_expr(base: float) -> str:
    return f"calc({base} * var(--sb-ornament-opacity-mult, 1))"


def render_square_marker(
    target_path: str,
    size: ShapeSize = "medium",
    position_style: str = "",
    *,
    color_var: str = "var(--brand-signal, #FACC15)",
    opacity: float = 1.0,
) -> str:
    """Solid square. Studio Brut's most common architectural ornament
    — appears in corners of color blocks, alongside oversized type, as
    accent marks adjacent to stats. Sharp corners, no rotation."""
    px = _SIZE_PX[size]
    safe_target = escape(target_path)
    pos = position_style.strip().strip(";")
    suffix = f"; {pos}" if pos else ""
    return (
        f'<div class="sb-hero-square sb-hero-square-{size}" '
        f'data-override-target="{safe_target}" '
        f'data-override-type="color" '
        f'style="width: {_scaled_size_expr(px)}; '
        f'height: {_scaled_size_expr(px)}; '
        f'background: {color_var}; '
        f'opacity: {_scaled_opacity_expr(opacity)}; '
        f'filter: var(--sb-ornament-glow, none); '
        f'pointer-events: none{suffix}">'
        f"</div>"
    )


def render_circle_marker(
    target_path: str,
    size: ShapeSize = "medium",
    position_style: str = "",
    *,
    color_var: str = "var(--brand-signal, #FACC15)",
    opacity: float = 1.0,
) -> str:
    """Solid circle. Used sparingly per design doc — as oversized
    framing devices, stat disc backgrounds, eyebrow markers. NEVER
    as soft decorative dot patterns."""
    px = _SIZE_PX[size]
    safe_target = escape(target_path)
    pos = position_style.strip().strip(";")
    suffix = f"; {pos}" if pos else ""
    return (
        f'<div class="sb-hero-circle sb-hero-circle-{size}" '
        f'data-override-target="{safe_target}" '
        f'data-override-type="color" '
        f'style="width: {_scaled_size_expr(px)}; '
        f'height: {_scaled_size_expr(px)}; '
        f'background: {color_var}; '
        f'border-radius: 50%; '
        f'opacity: {_scaled_opacity_expr(opacity)}; '
        f'filter: var(--sb-ornament-glow, none); '
        f'pointer-events: none{suffix}">'
        f"</div>"
    )


def render_bar(
    target_path: str,
    orientation: Literal["horizontal", "vertical"] = "horizontal",
    length: str = "100%",
    thickness_px: int = 8,
    position_style: str = "",
    *,
    color_var: str = "var(--brand-signal, #FACC15)",
    opacity: float = 1.0,
) -> str:
    """Thick bar (default 8px stroke — vs Cathedral's 1-2px thin
    rules). Studio Brut bars are architectural section dividers and
    intra-column structural elements, not delicate underlines."""
    safe_target = escape(target_path)
    pos = position_style.strip().strip(";")
    suffix = f"; {pos}" if pos else ""
    width = length if orientation == "horizontal" else f"{thickness_px}px"
    height = f"{thickness_px}px" if orientation == "horizontal" else length
    return (
        f'<div class="sb-hero-bar sb-hero-bar-{orientation}" '
        f'data-override-target="{safe_target}" '
        f'data-override-type="color" '
        f'style="width: {width}; '
        f'height: {height}; '
        f'background: {color_var}; '
        f'opacity: {_scaled_opacity_expr(opacity)}; '
        f'pointer-events: none{suffix}">'
        f"</div>"
    )


def render_color_block(
    target_path: str,
    width: str,
    height: str,
    position_style: str = "",
    *,
    color_var: str = "var(--brand-authority, #DC2626)",
    opacity: float = 1.0,
    z_index: int = 0,
) -> str:
    """Large solid color block — Studio Brut's most distinctive
    ornament. Used as architectural element: section halves, column
    backgrounds, layered backdrops behind content cards. The xlarge
    shape size enum doesn't fit (color blocks are arbitrarily sized);
    caller passes explicit width + height in any CSS units."""
    safe_target = escape(target_path)
    pos = position_style.strip().strip(";")
    suffix = f"; {pos}" if pos else ""
    return (
        f'<div class="sb-hero-color-block" '
        f'data-override-target="{safe_target}" '
        f'data-override-type="color" '
        f'style="width: {width}; '
        f'height: {height}; '
        f'background: {color_var}; '
        f'opacity: {_scaled_opacity_expr(opacity)}; '
        f'z-index: {z_index}; '
        f'pointer-events: none{suffix}">'
        f"</div>"
    )
