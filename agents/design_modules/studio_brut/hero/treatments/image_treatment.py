"""Studio Brut image_treatment — duotone + high-contrast filters per
the design doc's "image as graphic statement" principle (Section 6).

Where Cathedral's image filters are subtle (saturate 0.88, contrast
0.96), Studio Brut's commit harder. The dramatic option uses
real graphic-design contrast values. The filtered option produces an
editorial-fashion grade. Soft adds a slight blur-to-edge mask but
keeps the high-saturation center.

A bonus option for image variants: when image_treatment is 'filtered'
or 'dramatic', the --sb-image-overlay variable adds a saturated
brand-color overlay at low opacity (multiply blend) to push the image
toward duotone territory without doing actual GPU duotone processing.

Options:
  clean    — no filter. Photo as-shot.
  filtered — saturate(0.85) contrast(1.05) + signal-color overlay
             at 12% opacity. Editorial fashion grade.
  dramatic — saturate(1.2) contrast(1.25) brightness(0.92) + authority
             overlay at 22% opacity. Cinematic / streetwear poster.
  soft     — saturate(1.0) contrast(1.0) + radial mask feathering edges.
             Premium experience feel; the only Studio Brut image
             option that lets the photo read naturally.
"""
from __future__ import annotations

from typing import Dict

from ..types import ImageTreatment


def image_treatment_vars(value: ImageTreatment) -> Dict[str, str]:
    """Return CSS variable assignments for the given image treatment."""
    if value == "clean":
        return {
            "--sb-image-filter":  "none",
            "--sb-image-mask":    "none",
            "--sb-image-overlay": "none",
        }
    if value == "filtered":
        return {
            "--sb-image-filter":  "saturate(0.85) contrast(1.05)",
            "--sb-image-mask":    "none",
            # Brand-signal overlay — pushes the image toward warm
            # editorial duotone without GPU processing.
            "--sb-image-overlay": (
                "linear-gradient(0deg, "
                "color-mix(in srgb, var(--brand-signal, #FACC15) 12%, transparent) 0%, "
                "color-mix(in srgb, var(--brand-signal, #FACC15) 12%, transparent) 100%)"
            ),
        }
    if value == "dramatic":
        return {
            "--sb-image-filter":  "saturate(1.2) contrast(1.25) brightness(0.92)",
            "--sb-image-mask":    "none",
            # Brand-authority overlay — pushes the image toward
            # streetwear-poster duotone.
            "--sb-image-overlay": (
                "linear-gradient(180deg, "
                "color-mix(in srgb, var(--brand-authority, #DC2626) 22%, transparent) 0%, "
                "color-mix(in srgb, var(--brand-authority, #DC2626) 22%, transparent) 100%)"
            ),
        }
    # soft
    return {
        "--sb-image-filter":  "saturate(1.0) contrast(1.0)",
        "--sb-image-mask": (
            "radial-gradient(ellipse at center, "
            "rgba(0,0,0,1) 55%, "
            "rgba(0,0,0,0.5) 90%, "
            "rgba(0,0,0,0) 100%)"
        ),
        "--sb-image-overlay": "none",
    }
