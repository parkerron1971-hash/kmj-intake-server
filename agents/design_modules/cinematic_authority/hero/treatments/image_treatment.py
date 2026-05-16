"""image_treatment — filter on hero <img> elements.

Four options. Only image-using variants meaningfully consume these
(text-only variants pass 'clean' through with no visible effect):

  clean      — no filter. Photo as-shot.

  filtered   — subtle editorial grade: saturate(0.88), contrast(0.96).
               Slightly desaturated, slightly softer. Magazine feel.

  dramatic   — high impact: saturate(1.15), contrast(1.18), brightness(0.96).
               Richer colors, deeper shadows. Cinematic.

  soft       — slight blur on edges (mask-image radial). The image
               remains crisp at the center and feathers at the
               edges. Premium / dreamlike experience feel.

Variants apply via inline style on <img>:
  filter: var(--ca-image-filter, none);
  -webkit-mask-image: var(--ca-image-mask, none);
          mask-image: var(--ca-image-mask, none);
"""
from __future__ import annotations

from typing import Dict

from ..types import ImageTreatment


def image_treatment_vars(value: ImageTreatment) -> Dict[str, str]:
    """Return CSS variable assignments for the given image treatment.

    Variables:
      --ca-image-filter   — CSS filter value (default 'none')
      --ca-image-mask     — mask-image (default 'none', soft uses radial)
      --ca-image-overlay  — gradient overlay color stack (default 'none')
    """
    if value == "clean":
        return {
            "--ca-image-filter": "none",
            "--ca-image-mask": "none",
            "--ca-image-overlay": "none",
        }
    if value == "filtered":
        return {
            "--ca-image-filter": "saturate(0.88) contrast(0.96)",
            "--ca-image-mask": "none",
            "--ca-image-overlay": (
                "linear-gradient(180deg, "
                "color-mix(in srgb, var(--brand-warm-neutral, #F8F6F1) 8%, "
                "transparent) 0%, transparent 30%)"
            ),
        }
    if value == "dramatic":
        return {
            "--ca-image-filter": "saturate(1.15) contrast(1.18) brightness(0.96)",
            "--ca-image-mask": "none",
            "--ca-image-overlay": (
                "linear-gradient(180deg, "
                "transparent 50%, "
                "color-mix(in srgb, var(--brand-authority, #0A1628) 22%, "
                "transparent) 100%)"
            ),
        }
    # soft
    return {
        "--ca-image-filter": "saturate(0.95) contrast(0.98)",
        "--ca-image-mask": (
            "radial-gradient(ellipse at center, "
            "rgba(0,0,0,1) 50%, "
            "rgba(0,0,0,0.6) 88%, "
            "rgba(0,0,0,0) 100%)"
        ),
        "--ca-image-overlay": "none",
    }
