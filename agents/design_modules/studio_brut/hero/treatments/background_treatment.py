"""Studio Brut background_treatment — bold-leaning interpretation of
the 4 background options.

Per STUDIO_BRUT_DESIGN.md Section 4 + Section 5: gradients are bold
(authority-to-signal full-bleed, never soft 5-10% fades). Textures
are graphic (halftone screen-print aesthetic, not subtle noise).
Vignette commits to dramatic contrast rather than Cathedral's gentle
edge-darken.

Options:
  flat           — solid brand-warm-neutral OR brand-authority OR a
                   chosen brand color depending on variant. Variants
                   typically set --sb-bg-color directly via inline
                   style; this translator just clears any image layer.

  soft_gradient  — Studio Brut "soft" is still bold: 135deg gradient
                   from authority to signal at FULL saturation. This
                   is what Cathedral calls "bold gradient." Studio
                   Brut doesn't have a Cathedral-style soft gradient
                   option; the dimension just maps to bold.

  textured       — halftone-dot screen-print SVG at 24px tile size,
                   higher opacity than Cathedral's 18% noise. Sits
                   over brand-warm-neutral, blended via multiply.

  vignette       — radial darken with 35% authority tint at edges
                   (vs Cathedral's gentle 18%). Cinematic poster
                   contrast.
"""
from __future__ import annotations

from typing import Dict

from ..types import BackgroundTreatment


# Halftone-dot screen-print pattern. Inline SVG, base64-free, encoded
# inline. ~24px tile, dots at 4px diameter, 22% opacity black.
# Reads as risograph / screen-print texture rather than Cathedral's
# fractal noise.
_HALFTONE_SVG_URL = (
    "url(\"data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24' "
    "viewBox='0 0 24 24'>"
    "<circle cx='6' cy='6' r='1.6' fill='%23000000' fill-opacity='0.22'/>"
    "<circle cx='18' cy='6' r='1.6' fill='%23000000' fill-opacity='0.22'/>"
    "<circle cx='6' cy='18' r='1.6' fill='%23000000' fill-opacity='0.22'/>"
    "<circle cx='18' cy='18' r='1.6' fill='%23000000' fill-opacity='0.22'/>"
    "</svg>\")"
)


def background_treatment_vars(value: BackgroundTreatment) -> Dict[str, str]:
    """Return CSS variable assignments for the given background treatment."""
    if value == "flat":
        return {
            "--sb-bg-color":  "var(--brand-warm-neutral, #F4F4F0)",
            "--sb-bg-image":  "none",
            "--sb-bg-size":   "auto",
            "--sb-bg-repeat": "no-repeat",
            "--sb-bg-blend":  "normal",
        }
    if value == "soft_gradient":
        # Studio Brut "soft" still commits. Full-saturation
        # authority-to-signal at 135deg, no tint mixing.
        return {
            "--sb-bg-color":  "var(--brand-warm-neutral, #F4F4F0)",
            "--sb-bg-image":  (
                "linear-gradient(135deg, "
                "var(--brand-authority, #DC2626) 0%, "
                "var(--brand-authority, #DC2626) 50%, "
                "var(--brand-signal, #FACC15) 100%)"
            ),
            "--sb-bg-size":   "cover",
            "--sb-bg-repeat": "no-repeat",
            "--sb-bg-blend":  "normal",
        }
    if value == "textured":
        return {
            "--sb-bg-color":  "var(--brand-warm-neutral, #F4F4F0)",
            "--sb-bg-image":  _HALFTONE_SVG_URL,
            "--sb-bg-size":   "24px 24px",
            "--sb-bg-repeat": "repeat",
            "--sb-bg-blend":  "multiply",
        }
    # vignette
    return {
        "--sb-bg-color":  "var(--brand-warm-neutral, #F4F4F0)",
        "--sb-bg-image":  (
            "radial-gradient(ellipse at center, "
            "transparent 30%, "
            "color-mix(in srgb, var(--brand-authority, #DC2626) 35%, "
            "transparent) 100%)"
        ),
        "--sb-bg-size":   "cover",
        "--sb-bg-repeat": "no-repeat",
        "--sb-bg-blend":  "normal",
    }
