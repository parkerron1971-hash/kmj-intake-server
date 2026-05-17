"""Studio Brut color_depth_treatment — gradients on accents and CTA,
hard-offset shadows (not soft drop-shadows) per Studio Brut DNA.

Options:
  flat              — solid colors. CTA gets a hard 4-4-0 offset shadow
                      in text-primary color (brutalist-web aesthetic),
                      NOT a soft blurred drop-shadow.
  gradient_accents  — heading emphasis word uses gradient text fill
                      (signal-to-authority). CTA bg becomes authority-
                      to-signal gradient with offset shadow intact.
  radial_glows      — heading emphasis word gains saturated text-shadow
                      halo. CTA gets radial signal-color glow halo
                      replacing the offset shadow.
"""
from __future__ import annotations

from typing import Dict

from ..types import ColorDepthTreatment


def color_depth_vars(value: ColorDepthTreatment) -> Dict[str, str]:
    """Return CSS variable assignments for the given color depth."""
    if value == "flat":
        return {
            "--sb-emphasis-bg":         "transparent",
            "--sb-emphasis-bg-clip":    "border-box",
            "--sb-emphasis-text-fill":  "var(--sb-emphasis-color, var(--brand-signal, #FACC15))",
            "--sb-emphasis-glow":       "none",
            "--sb-cta-bg-image":        "none",
            # Brutalist hard-offset shadow (not soft blurred)
            "--sb-cta-glow": "4px 4px 0 var(--brand-text-primary, #09090B)",
            "--sb-ornament-glow":       "none",
        }
    if value == "gradient_accents":
        return {
            "--sb-emphasis-bg": (
                "linear-gradient(135deg, "
                "var(--brand-signal, #FACC15) 0%, "
                "var(--brand-authority, #DC2626) 100%)"
            ),
            "--sb-emphasis-bg-clip":    "text",
            "--sb-emphasis-text-fill":  "transparent",
            "--sb-emphasis-glow":       "none",
            "--sb-cta-bg-image": (
                "linear-gradient(135deg, "
                "var(--brand-authority, #DC2626) 0%, "
                "var(--brand-signal, #FACC15) 100%)"
            ),
            # Keep the hard-offset shadow even with gradient — Studio
            # Brut layering language stays consistent.
            "--sb-cta-glow": "5px 5px 0 var(--brand-text-primary, #09090B)",
            "--sb-ornament-glow":       "none",
        }
    # radial_glows
    return {
        "--sb-emphasis-bg":         "transparent",
        "--sb-emphasis-bg-clip":    "border-box",
        "--sb-emphasis-text-fill":  "var(--sb-emphasis-color, var(--brand-signal, #FACC15))",
        "--sb-emphasis-glow": (
            "0 0 32px color-mix(in srgb, var(--brand-signal, #FACC15) 55%, transparent), "
            "0 0 12px color-mix(in srgb, var(--brand-signal, #FACC15) 80%, transparent)"
        ),
        "--sb-cta-bg-image": (
            "radial-gradient(ellipse at center, "
            "color-mix(in srgb, var(--brand-signal, #FACC15) 100%, transparent) 50%, "
            "var(--brand-authority, #DC2626) 100%)"
        ),
        # Glow shadow replaces hard-offset for radial_glows
        "--sb-cta-glow": (
            "0 0 40px color-mix(in srgb, var(--brand-signal, #FACC15) 50%, transparent), "
            "0 10px 28px rgba(0, 0, 0, 0.25)"
        ),
        "--sb-ornament-glow": (
            "drop-shadow(0 0 10px color-mix(in srgb, "
            "var(--brand-signal, #FACC15) 65%, transparent))"
        ),
    }
