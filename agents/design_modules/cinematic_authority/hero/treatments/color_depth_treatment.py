"""color_depth_treatment — gradient + glow treatment on accent elements.

Three options, all affect the same surfaces (italic emphasis word in
heading, CTA button, accent lines/seams):

  flat              — solid colors throughout. Clean, minimal, the
                      Cathedral default.

  gradient_accents  — italic emphasis word uses linear-gradient text
                      fill (signal → secondary). CTA bg becomes a
                      2-stop signal-to-darken gradient. Accent lines
                      fade at the endcaps. Dynamic, alive.

  radial_glows      — italic emphasis word retains solid color but
                      gains a subtle text-shadow halo. CTA gains a
                      radial signal glow behind it. Decorative
                      diamonds get a soft glow. Luxe, ethereal.

The primitives (heading, cta_button) reference these CSS vars and
fall back to flat values when unset so they remain usable in isolation."""
from __future__ import annotations

from typing import Dict

from ..types import ColorDepthTreatment


def color_depth_vars(value: ColorDepthTreatment) -> Dict[str, str]:
    """Return CSS variable assignments for the given color depth treatment.

    Variables consumed by primitives:
      --ca-emphasis-bg          — background of italic emphasis <em>
                                  (e.g. 'transparent' or a gradient)
      --ca-emphasis-bg-clip     — '-webkit-background-clip' value
                                  ('border-box' or 'text')
      --ca-emphasis-text-fill   — '-webkit-text-fill-color' (color or
                                  'transparent' when gradient bg-clipped)
      --ca-emphasis-glow        — text-shadow halo (default: 'none')
      --ca-cta-bg-image         — background-image on CTA (default: 'none')
      --ca-cta-glow             — box-shadow radial glow on CTA
      --ca-accent-fade          — background gradient mask for seam rules
                                  (default 'linear-gradient(transparent,transparent)')
      --ca-diamond-glow         — filter halo on diamond motifs
    """
    if value == "flat":
        return {
            "--ca-emphasis-bg": "transparent",
            "--ca-emphasis-bg-clip": "border-box",
            "--ca-emphasis-text-fill": "var(--emphasis-color, var(--brand-signal, #C6952F))",
            "--ca-emphasis-glow": "none",
            "--ca-cta-bg-image": "none",
            "--ca-cta-glow": "0 8px 24px rgba(0, 0, 0, 0.12)",
            "--ca-accent-fade": (
                "linear-gradient(to right, "
                "var(--brand-signal, #C6952F), "
                "var(--brand-signal, #C6952F))"
            ),
            "--ca-diamond-glow": "none",
        }
    if value == "gradient_accents":
        return {
            "--ca-emphasis-bg": (
                "linear-gradient(135deg, "
                "var(--brand-signal, #C6952F) 0%, "
                "color-mix(in srgb, var(--brand-signal, #C6952F) 50%, "
                "var(--brand-deep-secondary, #122040)) 100%)"
            ),
            "--ca-emphasis-bg-clip": "text",
            "--ca-emphasis-text-fill": "transparent",
            "--ca-emphasis-glow": "none",
            "--ca-cta-bg-image": (
                "linear-gradient(135deg, "
                "var(--brand-signal, #C6952F) 0%, "
                "color-mix(in srgb, var(--brand-signal, #C6952F) 70%, "
                "var(--brand-authority, #0A1628)) 100%)"
            ),
            "--ca-cta-glow": (
                "0 12px 28px rgba(0, 0, 0, 0.18), "
                "0 4px 10px color-mix(in srgb, "
                "var(--brand-signal, #C6952F) 30%, transparent)"
            ),
            "--ca-accent-fade": (
                "linear-gradient(to right, "
                "transparent 0%, "
                "var(--brand-signal, #C6952F) 25%, "
                "var(--brand-signal, #C6952F) 75%, "
                "transparent 100%)"
            ),
            "--ca-diamond-glow": "none",
        }
    # radial_glows
    return {
        "--ca-emphasis-bg": "transparent",
        "--ca-emphasis-bg-clip": "border-box",
        "--ca-emphasis-text-fill": "var(--emphasis-color, var(--brand-signal, #C6952F))",
        "--ca-emphasis-glow": (
            "0 0 24px color-mix(in srgb, "
            "var(--brand-signal, #C6952F) 45%, transparent), "
            "0 0 8px color-mix(in srgb, "
            "var(--brand-signal, #C6952F) 60%, transparent)"
        ),
        "--ca-cta-bg-image": (
            "radial-gradient(ellipse at center, "
            "color-mix(in srgb, var(--brand-signal, #C6952F) 100%, transparent) 60%, "
            "color-mix(in srgb, var(--brand-signal, #C6952F) 80%, "
            "var(--brand-authority, #0A1628)) 100%)"
        ),
        "--ca-cta-glow": (
            "0 0 36px color-mix(in srgb, "
            "var(--brand-signal, #C6952F) 38%, transparent), "
            "0 8px 24px rgba(0, 0, 0, 0.18)"
        ),
        "--ca-accent-fade": (
            "linear-gradient(to right, "
            "var(--brand-signal, #C6952F), "
            "var(--brand-signal, #C6952F))"
        ),
        "--ca-diamond-glow": (
            "drop-shadow(0 0 8px color-mix(in srgb, "
            "var(--brand-signal, #C6952F) 60%, transparent))"
        ),
    }
