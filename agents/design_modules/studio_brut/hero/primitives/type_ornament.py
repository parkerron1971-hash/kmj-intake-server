"""Studio Brut type-as-ornament primitives. Per the design doc Section
4, Studio Brut treats type as raw decorative material — oversized
letterforms, code labels, repeated word patterns.

Two primitives surfaced here:

  render_oversized_letter — single letter at 30-60vw scale, used as
    background ornament behind content. Faded to low opacity so it
    reads as architectural texture, not as legible text.

  render_code_label — short code/label in monospace ("CASE 23.041",
    "VOL. II", "EST. 2024", "SVC.04") used as design vocabulary
    element. Smaller scale than oversized_letter, fully legible.
"""
from __future__ import annotations

from html import escape


def render_oversized_letter(
    letter: str,
    target_path: str,
    position_style: str = "",
    *,
    size_vw: int = 40,
    opacity: float = 0.08,
    color_var: str = "var(--brand-authority, #DC2626)",
    rotation_deg: int = 0,
) -> str:
    """Render a single letter at huge scale as background ornament.

    Caller controls position (absolute placement with top/right/bottom/
    left). Opacity defaults low (0.08) because the letter is decorative
    texture, not a visible word. Practitioner sees the shape; reader
    sees an architectural pattern."""
    safe_target = escape(target_path)
    safe_letter = escape(letter[:1] if letter else "S")  # 1 char only
    pos = position_style.strip().strip(";")
    suffix = f"; {pos}" if pos else ""
    transform = (
        f"rotate({rotation_deg}deg)" if rotation_deg else "none"
    )
    return (
        f'<div class="sb-hero-oversized-letter" '
        f'data-override-target="{safe_target}" '
        f'data-override-type="color" '
        f'style="font-size: {size_vw}vw; '
        f'font-weight: 900; '
        f'line-height: 0.8; '
        f'color: {color_var}; '
        f'opacity: {opacity}; '
        f'font-family: var(--sb-display-stack, "Druk", "Archivo Black", '
        f'"Inter", system-ui, sans-serif); '
        f'transform: {transform}; '
        f'pointer-events: none; '
        f'user-select: none{suffix}">'
        f"{safe_letter}"
        f"</div>"
    )


def render_code_label(
    text: str,
    target_path: str,
    *,
    color_var: str = "var(--brand-text-primary, #09090B)",
    size_px: int = 11,
    position_style: str = "",
) -> str:
    """Render a short codified label in monospace. Studio Brut design
    vocabulary — "CASE 23.041", "VOL. II", "EST. 2024", "SVC.04". The
    label is fully legible (high opacity, small size) and functions as
    a graphic-design element + a wayfinding signal."""
    safe_target = escape(target_path)
    safe_text = escape(text or "CASE 00")
    pos = position_style.strip().strip(";")
    suffix = f"; {pos}" if pos else ""
    return (
        f'<div class="sb-hero-code-label" '
        f'data-override-target="{safe_target}" '
        f'data-override-type="text" '
        f'style="font-size: {size_px}px; '
        f'font-weight: 700; '
        f'letter-spacing: 0.18em; '
        f'text-transform: uppercase; '
        f'color: {color_var}; '
        f'font-family: var(--sb-mono-stack, "Inter Mono", "JetBrains Mono", '
        f'"Space Mono", "SF Mono", ui-monospace, monospace); '
        f'line-height: 1{suffix}">'
        f"{safe_text}"
        f"</div>"
    )
