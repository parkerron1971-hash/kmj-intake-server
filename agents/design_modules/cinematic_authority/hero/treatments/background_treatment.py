"""background_treatment — section-level backdrop. Four options that
control how the section background carries depth:

  flat           — solid brand-warm-neutral. Editorial restraint, no
                   atmosphere. Cathedral classic for technical / authority
                   brands where the words carry weight.

  soft_gradient  — gentle multi-stop linear gradient from
                   brand-warm-neutral through an 8% signal tint to a 5%
                   authority tint. Adds depth without drama. Premium /
                   lifestyle feel.

  textured       — solid bg + a low-opacity SVG noise texture tiled on
                   top, blended via multiply. Tactile, crafted feel.
                   Custom apparel, artisan brands.

  vignette       — radial darken centered on the section (transparent at
                   center, 18% authority tint at edges). Cinematic focus
                   toward the content. Dramatic / authority brands.

Variant contract:
  Section root applies five vars uniformly:
    background-color: var(--ca-bg-color, var(--brand-warm-neutral, #F8F6F1));
    background-image: var(--ca-bg-image, none);
    background-size:  var(--ca-bg-size, auto);
    background-repeat: var(--ca-bg-repeat, no-repeat);
    background-blend-mode: var(--ca-bg-blend, normal);
  The variant's existing inline-style stack just appends these — the
  variant doesn't need to know which treatment was picked.
"""
from __future__ import annotations

from typing import Dict

from ..types import BackgroundTreatment


# Reusable SVG noise pattern, base64-encoded. Subtle dot pattern at ~6%
# opacity. Embedded inline so the renderer has zero asset-host concerns.
_NOISE_SVG_URL = (
    "url(\"data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180' "
    "viewBox='0 0 180 180'>"
    "<filter id='n'>"
    "<feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' "
    "stitchTiles='stitch'/>"
    "<feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.18 0'/>"
    "</filter>"
    "<rect width='100%25' height='100%25' filter='url(%23n)'/>"
    "</svg>\")"
)


def background_treatment_vars(value: BackgroundTreatment) -> Dict[str, str]:
    """Return CSS variable assignments for the given background treatment.

    Variables:
      --ca-bg-color    — backstop color (always set)
      --ca-bg-image    — background-image value (gradient/noise/vignette)
      --ca-bg-size     — background-size value (cover for gradients,
                         tile dimensions for textured)
      --ca-bg-repeat   — background-repeat (repeat for textured, no-repeat
                         for gradient/vignette)
      --ca-bg-blend    — background-blend-mode (multiply for textured to
                         settle the noise into the color, normal otherwise)
    """
    if value == "flat":
        return {
            "--ca-bg-color": "var(--brand-warm-neutral, #F8F6F1)",
            "--ca-bg-image": "none",
            "--ca-bg-size": "auto",
            "--ca-bg-repeat": "no-repeat",
            "--ca-bg-blend": "normal",
        }
    if value == "soft_gradient":
        return {
            "--ca-bg-color": "var(--brand-warm-neutral, #F8F6F1)",
            "--ca-bg-image": (
                "linear-gradient(135deg, "
                "var(--brand-warm-neutral, #F8F6F1) 0%, "
                "color-mix(in srgb, var(--brand-signal, #C6952F) 9%, "
                "var(--brand-warm-neutral, #F8F6F1)) 65%, "
                "color-mix(in srgb, var(--brand-authority, #0A1628) 6%, "
                "var(--brand-warm-neutral, #F8F6F1)) 100%)"
            ),
            "--ca-bg-size": "cover",
            "--ca-bg-repeat": "no-repeat",
            "--ca-bg-blend": "normal",
        }
    if value == "textured":
        return {
            "--ca-bg-color": "var(--brand-warm-neutral, #F8F6F1)",
            "--ca-bg-image": _NOISE_SVG_URL,
            "--ca-bg-size": "180px 180px",
            "--ca-bg-repeat": "repeat",
            "--ca-bg-blend": "multiply",
        }
    # vignette
    return {
        "--ca-bg-color": "var(--brand-warm-neutral, #F8F6F1)",
        "--ca-bg-image": (
            "radial-gradient(ellipse at center, "
            "transparent 38%, "
            "color-mix(in srgb, var(--brand-authority, #0A1628) 18%, "
            "transparent) 100%)"
        ),
        "--ca-bg-size": "cover",
        "--ca-bg-repeat": "no-repeat",
        "--ca-bg-blend": "normal",
    }
