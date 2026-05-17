"""Studio Brut color_emphasis — same 3 options as Cathedral but
interpreted through Studio Brut's "color as architecture" DNA. Where
Cathedral's color_emphasis decides which role gets the italic accent,
Studio Brut's decides which role becomes the section's PRIMARY paint
when a variant uses color-block architecture, and which role anchors
the CTA / eyebrow / heading-emphasis word.

Options:
  signal_dominant   — eyebrow + heading_emphasis + CTA in signal.
                      Section paint defaults to neutral or authority.
                      The signal color is the architectural accent.
  authority_dominant — eyebrow + CTA in authority. heading_emphasis
                      can use signal OR text-primary depending on
                      typography mode. Variants that paint sections
                      may use authority as the dominant paint.
  dual_emphasis     — both authority + signal carry weight. Eyebrow in
                      signal, CTA in authority, heading-emphasis in
                      signal. Color-on-color compositions enabled.
"""
from __future__ import annotations

from typing import Dict

from ..types import ColorEmphasis


def color_emphasis_vars(emphasis: ColorEmphasis) -> Dict[str, str]:
    """Return CSS variable assignments for the given color emphasis.
    Variables consumed by Studio Brut primitives."""
    if emphasis == "signal_dominant":
        return {
            "--sb-heading-color":   "var(--brand-text-primary)",
            "--sb-emphasis-color":  "var(--brand-signal)",
            "--sb-eyebrow-color":   "var(--brand-signal)",
            "--sb-subtitle-color":  "var(--brand-text-primary)",
            "--cta-bg":             "var(--brand-signal)",
            "--cta-text":           "var(--brand-text-on-signal)",
        }
    if emphasis == "authority_dominant":
        return {
            "--sb-heading-color":   "var(--brand-authority)",
            "--sb-emphasis-color":  "var(--brand-signal)",
            "--sb-eyebrow-color":   "var(--brand-authority)",
            "--sb-subtitle-color":  "var(--brand-text-primary)",
            "--cta-bg":             "var(--brand-authority)",
            "--cta-text":           "var(--brand-text-on-authority)",
        }
    # dual_emphasis
    return {
        "--sb-heading-color":   "var(--brand-authority)",
        "--sb-emphasis-color":  "var(--brand-signal)",
        "--sb-eyebrow-color":   "var(--brand-signal)",
        "--sb-subtitle-color":  "var(--brand-text-primary)",
        "--cta-bg":             "var(--brand-authority)",
        "--cta-text":           "var(--brand-text-on-authority)",
    }
